//! xanima brain service backend: Caelza's Mind as a native [`Memory`].
//!
//! `xanima-server` owns one private brain per agent plus a shared brain and
//! serves the brain tools over MCP Streamable HTTP (`POST {url}/mcp`, stateless,
//! JSON responses, one bearer token per agent). This backend speaks that
//! protocol directly, so the Runtime's per-turn recall and auto-save reach the
//! brain without a tool call, and the service's sleep (consolidation, decay,
//! forgetting) keeps running on its own.
//!
//! Mapping:
//! - `recall` → `brain_query` (`format = json`; private + shared, fused by the service)
//! - `store` with category `conversation` → `brain_episode_append` (the turn log sleep consolidates)
//! - `store` with any other category → `brain_write` (label = key; `core` → semantic, `daily` → episodic)
//! - `get` / `forget` → `brain_query` by label, then `brain_forget`
//! - `count` / `stats` → `brain_stats`; `health_check` → `GET /health`
//! - `list` → empty: the service has no enumerate-everything tool
//!
//! Agents: the runtime passes an agent alias on scoped operations; each alias
//! resolves to its own token (`token_file` with `{agent}`), so the service's
//! per-agent isolation and the `AgentScopedMemory` wrapper agree.

use super::traits::{
    Memory, MemoryCategory, MemoryEntry, MemoryKind, MemoryStats, StoreOptions,
    is_recent_recall_query,
};
use anyhow::{Context, Result, bail};
use async_trait::async_trait;
use parking_lot::{Mutex, RwLock};
use serde_json::{Value, json};
use std::cmp::Ordering as CmpOrdering;
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

/// The service's loopback listener.
pub const DEFAULT_URL: &str = "http://127.0.0.1:18790";
/// One token per agent; `{agent}` is the agent alias.
pub const DEFAULT_TOKEN_FILE: &str = "~/.xanima/tokens/{agent}.token";

const LABEL_MAX: usize = 500;
const CONTENT_MAX: usize = 100_000;
const EPISODE_MAX: usize = 32_000;
const SESSION_MAX: usize = 512;
const QUERY_LIMIT_MAX: usize = 1000;
/// Node types `brain_write` accepts.
const WRITE_NODE_TYPES: [&str; 9] = [
    "identity",
    "semantic",
    "episodic",
    "pattern",
    "skill",
    "goal",
    "emotion",
    "procedural",
    "schema",
];

/// Connection settings, resolved from `[storage.xanima.<alias>]`.
#[derive(Debug, Clone)]
pub struct XanimaSettings {
    /// Base URL without a trailing slash.
    pub url: String,
    /// One token for every agent (overrides `token_file`).
    pub token: Option<String>,
    /// Token file path template; `{agent}` is replaced by the agent alias.
    pub token_file: String,
    /// Agent used by operations that carry no agent.
    pub agent: String,
    /// `all`, `private` or `shared`.
    pub scope: String,
    /// Per-request timeout.
    pub timeout: Duration,
}

impl XanimaSettings {
    /// Loopback defaults for `url`.
    pub fn new(url: &str) -> Self {
        Self {
            url: url.trim().trim_end_matches('/').to_string(),
            token: None,
            token_file: DEFAULT_TOKEN_FILE.to_string(),
            agent: "main".to_string(),
            scope: "all".to_string(),
            timeout: Duration::from_secs(20),
        }
    }

    /// Validate and resolve a typed storage entry.
    pub fn from_storage(cfg: &caelza_config::schema::XanimaStorageConfig) -> Result<Self> {
        let url = cfg.url.trim().trim_end_matches('/');
        if url.is_empty() {
            bail!("xanima memory backend requires `url` in [storage.xanima.<alias>]");
        }
        if !(url.starts_with("http://") || url.starts_with("https://")) {
            bail!("xanima `url` must start with http:// or https://, got {url:?}");
        }
        let scope = cfg.scope.trim().to_ascii_lowercase();
        if !matches!(scope.as_str(), "all" | "private" | "shared") {
            bail!("xanima `scope` must be all, private or shared, got {:?}", cfg.scope);
        }
        let agent = cfg.agent.trim();
        if agent.is_empty() {
            bail!("xanima `agent` must name the default agent alias (for example \"main\")");
        }
        let clean = |s: &Option<String>| {
            s.as_deref()
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .map(str::to_string)
        };
        Ok(Self {
            url: url.to_string(),
            token: clean(&cfg.token),
            token_file: clean(&cfg.token_file).unwrap_or_else(|| DEFAULT_TOKEN_FILE.to_string()),
            agent: agent.to_string(),
            scope,
            timeout: Duration::from_secs(cfg.timeout_secs.max(1)),
        })
    }
}

/// The xanima brain service as a memory backend.
pub struct XanimaMemory {
    alias: String,
    client: reqwest::Client,
    settings: XanimaSettings,
    /// Tokens read from token files, by agent alias.
    tokens: RwLock<HashMap<String, String>>,
    /// Warnings already emitted (missing sibling tokens, unsupported operations).
    warned: Mutex<HashSet<String>>,
    next_id: AtomicU64,
}

impl XanimaMemory {
    /// Build the backend on the runtime's proxied HTTP client. Nothing is
    /// contacted until the first operation.
    pub fn new(alias: &str, settings: XanimaSettings) -> Self {
        let client = caelza_config::schema::build_runtime_proxy_client("memory.xanima");
        Self::with_client(alias, settings, client)
    }

    /// Build the backend on a caller-supplied client (tests, custom proxies).
    pub fn with_client(alias: &str, settings: XanimaSettings, client: reqwest::Client) -> Self {
        Self {
            alias: alias.to_string(),
            client,
            settings,
            tokens: RwLock::new(HashMap::new()),
            warned: Mutex::new(HashSet::new()),
            next_id: AtomicU64::new(1),
        }
    }

    pub fn settings(&self) -> &XanimaSettings {
        &self.settings
    }

    /// Where `agent`'s token file lives.
    pub fn token_path_for(&self, agent: &str) -> PathBuf {
        expand_home(&self.settings.token_file.replace("{agent}", agent))
    }

    /// The bearer token for `agent`: the configured token, else the agent's
    /// token file. `Ok(None)` when there is no token source (the file is absent).
    fn token_for(&self, agent: &str) -> Result<Option<String>> {
        if let Some(token) = &self.settings.token {
            return Ok(Some(token.clone()));
        }
        if let Some(token) = self.tokens.read().get(agent) {
            return Ok(Some(token.clone()));
        }
        let path = self.token_path_for(agent);
        let raw = match std::fs::read_to_string(&path) {
            Ok(raw) => raw,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(e) => {
                return Err(e)
                    .with_context(|| format!("xanima: reading token file {}", path.display()));
            }
        };
        let token = raw.trim().to_string();
        if token.is_empty() {
            bail!("xanima: token file {} is empty", path.display());
        }
        self.tokens
            .write()
            .insert(agent.to_string(), token.clone());
        Ok(Some(token))
    }

    fn no_token_error(&self, agent: &str) -> anyhow::Error {
        anyhow::anyhow!(
            "xanima: no token for agent {agent:?}. Put one in {} \
             (xanima-server token mint --agent {agent} --scopes read,write --json | jq -r .token) \
             or set storage.xanima.<alias>.token",
            self.token_path_for(agent).display()
        )
    }

    fn require_token(&self, agent: &str) -> Result<String> {
        self.token_for(agent)?
            .ok_or_else(|| self.no_token_error(agent))
    }

    fn warn_once(&self, key: &str, message: &str, attrs: Value) {
        if !self.warned.lock().insert(key.to_string()) {
            return;
        }
        ::caelza_log::record!(
            WARN,
            ::caelza_log::Event::new(module_path!(), ::caelza_log::Action::Note)
                .with_outcome(::caelza_log::EventOutcome::Unknown)
                .with_attrs(attrs),
            message
        );
    }

    /// The agent whose brain answers operations that name no agent.
    pub fn agent(&self) -> &str {
        &self.settings.agent
    }

    /// Whether a token source exists for `agent`: the configured token, or
    /// the agent's token file on disk.
    pub fn has_token(&self, agent: &str) -> bool {
        matches!(self.token_for(agent), Ok(Some(_)))
    }

    /// One brain tool call for operator surfaces (the dashboard's Mind page):
    /// the tool's text reply, parsed as JSON when it is JSON, else wrapped as
    /// `{"text": ...}`. Errors carry the service's own message.
    pub async fn call_tool_json(&self, agent: &str, tool: &str, arguments: Value) -> Result<Value> {
        let text = self.call_tool(agent, tool, arguments).await?;
        Ok(serde_json::from_str::<Value>(&text).unwrap_or_else(|_| json!({"text": text})))
    }

    /// One MCP `tools/call` round trip. Returns the joined text content.
    async fn call_tool(&self, agent: &str, tool: &str, arguments: Value) -> Result<String> {
        let token = self.require_token(agent)?;
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let body = json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        });
        let url = format!("{}/mcp", self.settings.url);
        let response = self
            .client
            .post(&url)
            .bearer_auth(&token)
            .header("accept", "application/json, text/event-stream")
            .header("content-type", "application/json")
            .timeout(self.settings.timeout)
            .json(&body)
            .send()
            .await
            .with_context(|| {
                format!("xanima: {tool}: POST {url} failed (is xanima-server running?)")
            })?;
        let status = response.status();
        let text = response
            .text()
            .await
            .with_context(|| format!("xanima: {tool}: reading the reply from {url}"))?;
        if status == reqwest::StatusCode::UNAUTHORIZED {
            // A rotated token file is picked up on the next call.
            self.tokens.write().remove(agent);
            bail!(
                "xanima: the token for agent {agent:?} was rejected (401) by {url}; \
                 mint a new one: xanima-server token mint --agent {agent} --scopes read,write"
            );
        }
        if !status.is_success() {
            bail!("xanima: {tool}: HTTP {status} from {url}: {}", snippet(&text));
        }
        let payload = parse_rpc_body(&text)
            .with_context(|| format!("xanima: {tool}: unreadable reply from {url}: {}", snippet(&text)))?;
        if let Some(err) = payload.get("error") {
            bail!(
                "xanima: {tool}: {}",
                err.get("message").and_then(Value::as_str).unwrap_or("rpc error")
            );
        }
        let result = payload.get("result").cloned().unwrap_or(Value::Null);
        let out = result
            .get("content")
            .and_then(Value::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter_map(|c| c.get("text").and_then(Value::as_str))
                    .collect::<Vec<_>>()
                    .join("\n")
            })
            .unwrap_or_default();
        if result.get("isError").and_then(Value::as_bool) == Some(true) {
            bail!("xanima: {tool}: {}", snippet(&out));
        }
        Ok(out)
    }

    /// `brain_query` in JSON form, as memory entries attributed to `agent`.
    async fn query_brain(&self, agent: &str, query: &str, limit: usize) -> Result<Vec<MemoryEntry>> {
        let limit = limit.clamp(1, QUERY_LIMIT_MAX);
        let text = self
            .call_tool(
                agent,
                "brain_query",
                json!({
                    "query": query,
                    "limit": limit,
                    "scope": self.settings.scope,
                    "format": "json",
                }),
            )
            .await?;
        let payload: Value = match serde_json::from_str(&text) {
            Ok(v) => v,
            Err(_) if text.trim_start().starts_with("No matching") => return Ok(Vec::new()),
            Err(e) => bail!("xanima: brain_query returned no JSON ({e}): {}", snippet(&text)),
        };
        Ok(payload
            .get("results")
            .and_then(Value::as_array)
            .map(|rows| rows.iter().filter_map(|n| entry_from_node(n, agent)).collect())
            .unwrap_or_default())
    }

    /// The newest node whose label is exactly `key`.
    async fn find_by_label(&self, agent: &str, key: &str) -> Result<Option<MemoryEntry>> {
        let key = key.trim();
        if key.is_empty() {
            return Ok(None);
        }
        let mut hits: Vec<MemoryEntry> = self
            .query_brain(agent, key, 20)
            .await?
            .into_iter()
            .filter(|e| e.key == key)
            .collect();
        hits.sort_by(|a, b| b.timestamp.cmp(&a.timestamp));
        Ok(hits.into_iter().next())
    }

    /// Recall across `agents` (each with its own token), deduplicated by node
    /// id, best score first. Agents without a token are skipped with one
    /// warning; when none is reachable the first agent's missing token is the error.
    async fn recall_agents(
        &self,
        agents: &[&str],
        query: &str,
        limit: usize,
        since: Option<&str>,
        until: Option<&str>,
    ) -> Result<Vec<MemoryEntry>> {
        if is_recent_recall_query(query) || limit == 0 || agents.is_empty() {
            return Ok(Vec::new());
        }
        let mut seen = HashSet::new();
        let mut out = Vec::new();
        let mut reachable = 0usize;
        for agent in agents {
            if self.token_for(agent)?.is_none() {
                self.warn_once(
                    &format!("token:{agent}"),
                    "xanima: no token for this agent; its brain is skipped",
                    json!({"agent": agent, "token_file": self.token_path_for(agent).display().to_string()}),
                );
                continue;
            }
            reachable += 1;
            for entry in self.query_brain(agent, query, limit).await? {
                if within(&entry, since, until) && seen.insert(entry.id.clone()) {
                    out.push(entry);
                }
            }
        }
        if reachable == 0 {
            return Err(self.no_token_error(agents[0]));
        }
        out.sort_by(|a, b| {
            b.score
                .unwrap_or(0.0)
                .partial_cmp(&a.score.unwrap_or(0.0))
                .unwrap_or(CmpOrdering::Equal)
        });
        out.truncate(limit);
        Ok(out)
    }

    /// Store one entry into `agent`'s brain.
    #[allow(clippy::too_many_arguments)]
    async fn write(
        &self,
        agent: &str,
        key: &str,
        content: &str,
        category: &MemoryCategory,
        session_id: Option<&str>,
        importance: Option<f64>,
        kind: Option<&MemoryKind>,
        pinned: bool,
    ) -> Result<()> {
        let content = content.trim();
        if content.is_empty() {
            return Ok(());
        }
        if matches!(category, MemoryCategory::Conversation) {
            let role = if crate::is_assistant_autosave_key(key) {
                "assistant"
            } else if crate::is_user_autosave_key(key) {
                "user"
            } else {
                "tool"
            };
            let session = session_id
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .map(str::to_string)
                .unwrap_or_else(|| format!("caelza:{agent}"));
            let mut args = json!({
                "session_id": truncate(&session, SESSION_MAX),
                "role": role,
                "content": truncate(content, EPISODE_MAX),
                "meta": {"key": key, "source": "caelza"},
            });
            if let Some(i) = importance {
                args["importance"] = json!(clamp01(i));
            }
            self.call_tool(agent, "brain_episode_append", args).await?;
            return Ok(());
        }
        let label = if key.trim().is_empty() {
            truncate(content, 60)
        } else {
            truncate(key.trim(), LABEL_MAX)
        };
        let mut args = json!({
            "type": node_type_for(category, kind),
            "label": label,
            "content": truncate(content, CONTENT_MAX),
        });
        if let Some(i) = importance.map(clamp01).or(pinned.then_some(1.0)) {
            args["importance"] = json!(i);
        }
        self.call_tool(agent, "brain_write", args).await?;
        Ok(())
    }

    async fn brain_stats(&self, agent: &str) -> Result<Vec<Value>> {
        let text = self
            .call_tool(
                agent,
                "brain_stats",
                json!({"visibility": self.settings.scope, "format": "json"}),
            )
            .await?;
        let payload: Value = serde_json::from_str(&text)
            .with_context(|| format!("xanima: brain_stats returned no JSON: {}", snippet(&text)))?;
        Ok(payload
            .get("brains")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default())
    }

    async fn count_for(&self, agent: &str) -> Result<usize> {
        Ok(self
            .brain_stats(agent)
            .await?
            .iter()
            .filter_map(|b| b.get("nodes").and_then(Value::as_u64))
            .sum::<u64>() as usize)
    }
}

impl ::caelza_api::attribution::Attributable for XanimaMemory {
    fn role(&self) -> ::caelza_api::attribution::Role {
        ::caelza_api::attribution::Role::Memory(::caelza_api::attribution::MemoryKind::Xanima)
    }
    fn alias(&self) -> &str {
        &self.alias
    }
}

#[async_trait]
impl Memory for XanimaMemory {
    fn name(&self) -> &str {
        "xanima"
    }

    async fn store(
        &self,
        key: &str,
        content: &str,
        category: MemoryCategory,
        session_id: Option<&str>,
    ) -> Result<()> {
        self.write(&self.settings.agent, key, content, &category, session_id, None, None, false)
            .await
    }

    async fn store_with_metadata(
        &self,
        key: &str,
        content: &str,
        category: MemoryCategory,
        session_id: Option<&str>,
        _namespace: Option<&str>,
        importance: Option<f64>,
    ) -> Result<()> {
        self.write(
            &self.settings.agent,
            key,
            content,
            &category,
            session_id,
            importance,
            None,
            false,
        )
        .await
    }

    async fn store_with_options(
        &self,
        key: &str,
        content: &str,
        category: MemoryCategory,
        session_id: Option<&str>,
        options: StoreOptions,
    ) -> Result<()> {
        self.store_with_options_and_agent(key, content, category, session_id, options, None)
            .await
    }

    async fn store_with_options_and_agent(
        &self,
        key: &str,
        content: &str,
        category: MemoryCategory,
        session_id: Option<&str>,
        options: StoreOptions,
        agent_id: Option<&str>,
    ) -> Result<()> {
        if options.tenant_id.is_some() {
            bail!(
                "xanima memory backend has no tenant dimension; drop tenant_id or use the sqlite backend"
            );
        }
        let agent = agent_id.unwrap_or(&self.settings.agent);
        self.write(
            agent,
            key,
            content,
            &category,
            session_id,
            options.importance,
            options.kind.as_ref(),
            options.pinned,
        )
        .await
    }

    async fn store_with_agent(
        &self,
        key: &str,
        content: &str,
        category: MemoryCategory,
        session_id: Option<&str>,
        _namespace: Option<&str>,
        importance: Option<f64>,
        agent_id: Option<&str>,
    ) -> Result<()> {
        let agent = agent_id.unwrap_or(&self.settings.agent);
        self.write(agent, key, content, &category, session_id, importance, None, false)
            .await
    }

    async fn recall(
        &self,
        query: &str,
        limit: usize,
        _session_id: Option<&str>,
        since: Option<&str>,
        until: Option<&str>,
    ) -> Result<Vec<MemoryEntry>> {
        self.recall_agents(&[self.settings.agent.as_str()], query, limit, since, until)
            .await
    }

    async fn recall_for_agents(
        &self,
        allowed_agent_ids: &[&str],
        query: &str,
        limit: usize,
        _session_id: Option<&str>,
        since: Option<&str>,
        until: Option<&str>,
    ) -> Result<Vec<MemoryEntry>> {
        if allowed_agent_ids.is_empty() {
            return self.recall(query, limit, None, since, until).await;
        }
        let mut agents: Vec<&str> = Vec::with_capacity(allowed_agent_ids.len());
        for agent in allowed_agent_ids {
            if !agents.contains(agent) {
                agents.push(agent);
            }
        }
        self.recall_agents(&agents, query, limit, since, until).await
    }

    async fn get(&self, key: &str) -> Result<Option<MemoryEntry>> {
        self.find_by_label(&self.settings.agent, key).await
    }

    async fn get_for_agent(&self, key: &str, agent_id: &str) -> Result<Option<MemoryEntry>> {
        self.find_by_label(agent_id, key).await
    }

    async fn list(
        &self,
        _category: Option<&MemoryCategory>,
        _session_id: Option<&str>,
    ) -> Result<Vec<MemoryEntry>> {
        self.warn_once(
            "list",
            "xanima: the brain service has no list-everything call; recall by query or use the brain tools",
            json!({"url": self.settings.url}),
        );
        Ok(Vec::new())
    }

    async fn forget(&self, key: &str) -> Result<bool> {
        self.forget_for_agent(key, &self.settings.agent).await
    }

    async fn forget_for_agent(&self, key: &str, agent_id: &str) -> Result<bool> {
        let Some(hit) = self.find_by_label(agent_id, key).await? else {
            return Ok(false);
        };
        let mut args = json!({"node_id": hit.id});
        if hit.namespace == "shared" {
            args["visibility"] = json!("shared");
        }
        self.call_tool(agent_id, "brain_forget", args).await?;
        Ok(true)
    }

    async fn purge_session_for_agent(&self, _session_id: &str, _agent_id: &str) -> Result<usize> {
        // Episodes stay in the brain for sleep to consolidate; nothing is purged.
        Ok(0)
    }

    async fn count(&self) -> Result<usize> {
        self.count_for(&self.settings.agent).await
    }

    async fn count_agent(&self, agent_alias: &str) -> Result<usize> {
        self.count_for(agent_alias).await
    }

    async fn health_check(&self) -> bool {
        let url = format!("{}/health", self.settings.url);
        match self.client.get(&url).timeout(self.settings.timeout).send().await {
            Ok(response) if response.status().is_success() => true,
            Ok(response) => {
                self.warn_once(
                    "health",
                    "xanima: health check failed",
                    json!({"url": url, "status": response.status().as_u16()}),
                );
                false
            }
            Err(e) => {
                self.warn_once(
                    "health",
                    "xanima: health check failed (is xanima-server running?)",
                    json!({"url": url, "error": e.to_string()}),
                );
                false
            }
        }
    }

    async fn stats(&self) -> Result<MemoryStats> {
        let brains = self.brain_stats(&self.settings.agent).await?;
        let mut by_type: Vec<(String, u64)> = Vec::new();
        let mut total = 0u64;
        for brain in &brains {
            total += brain.get("nodes").and_then(Value::as_u64).unwrap_or(0);
            if let Some(types) = brain.get("nodesByType").and_then(Value::as_object) {
                for (node_type, n) in types {
                    let n = n.as_u64().unwrap_or(0);
                    match by_type.iter_mut().find(|(t, _)| t == node_type) {
                        Some(row) => row.1 += n,
                        None => by_type.push((node_type.clone(), n)),
                    }
                }
            }
        }
        by_type.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
        Ok(MemoryStats {
            total_rows: total,
            by_category: by_type,
            ..MemoryStats::default()
        })
    }
}

// ─── helpers ─────────────────────────────────────────────────────────────────

/// Parse a Streamable HTTP reply: plain JSON, or an SSE stream whose last
/// `data:` frame carries the JSON-RPC result.
fn parse_rpc_body(text: &str) -> Result<Value> {
    let trimmed = text.trim();
    if trimmed.starts_with('{') {
        return serde_json::from_str(trimmed).context("not a JSON object");
    }
    let mut last = None;
    for line in trimmed.lines() {
        if let Some(data) = line.strip_prefix("data:")
            && let Ok(frame) = serde_json::from_str::<Value>(data.trim())
            && (frame.get("result").is_some() || frame.get("error").is_some())
        {
            last = Some(frame);
        }
    }
    last.ok_or_else(|| anyhow::anyhow!("no JSON-RPC frame in the reply"))
}

/// One `brain_query` result row as a memory entry visible to `agent`.
fn entry_from_node(node: &Value, agent: &str) -> Option<MemoryEntry> {
    let id = node.get("id").and_then(Value::as_str)?.to_string();
    let node_type = node.get("type").and_then(Value::as_str).unwrap_or("semantic");
    let brain = node.get("brain").and_then(Value::as_str).unwrap_or("private");
    let label = node
        .get("label")
        .and_then(Value::as_str)
        .filter(|l| !l.trim().is_empty())
        .unwrap_or(id.as_str())
        .to_string();
    let content = node
        .get("content")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let timestamp = match node.get("created_at") {
        Some(Value::Number(n)) => n
            .as_f64()
            .and_then(|ms| ms_to_rfc3339(ms as i64))
            .unwrap_or_else(now_rfc3339),
        Some(Value::String(s)) => chrono::DateTime::parse_from_rfc3339(s)
            .map(|t| t.with_timezone(&chrono::Utc).to_rfc3339_opts(chrono::SecondsFormat::Secs, true))
            .unwrap_or_else(|_| now_rfc3339()),
        _ => now_rfc3339(),
    };
    let writer = node
        .get("writer")
        .and_then(Value::as_str)
        .filter(|w| !w.is_empty())
        .map(str::to_string);
    let namespace = match brain {
        "room" => format!(
            "room:{}",
            node.get("room").and_then(Value::as_str).unwrap_or("?")
        ),
        other => other.to_string(),
    };
    Some(MemoryEntry {
        id,
        key: label,
        content,
        category: category_for_node_type(node_type),
        timestamp,
        session_id: None,
        score: node.get("score").and_then(Value::as_f64),
        namespace,
        importance: node.get("importance").and_then(Value::as_f64),
        superseded_by: None,
        kind: kind_for_node_type(node_type),
        pinned: false,
        tenant_id: None,
        principal_id: None,
        // Display: who wrote it. Scope: the agent whose token saw it, so the
        // scoped wrapper keeps shared-brain rows the service already allowed.
        agent_alias: writer.or_else(|| Some(agent.to_string())),
        agent_id: Some(agent.to_string()),
    })
}

fn category_for_node_type(node_type: &str) -> MemoryCategory {
    match node_type {
        "episodic" | "emotion" => MemoryCategory::Daily,
        "semantic" | "identity" | "goal" | "pattern" | "skill" | "procedural" | "schema"
        | "decision" => MemoryCategory::Core,
        other => MemoryCategory::Custom(other.to_string()),
    }
}

fn kind_for_node_type(node_type: &str) -> Option<MemoryKind> {
    match node_type {
        "episodic" => Some(MemoryKind::Episodic),
        "procedural" | "skill" => Some(MemoryKind::Procedural),
        _ => None,
    }
}

/// The `brain_write` node type for a runtime category (and typed kind, when given).
fn node_type_for(category: &MemoryCategory, kind: Option<&MemoryKind>) -> String {
    match kind {
        Some(MemoryKind::Episodic) => return "episodic".to_string(),
        Some(MemoryKind::Procedural) => return "procedural".to_string(),
        Some(MemoryKind::Semantic(_)) => return "semantic".to_string(),
        None => {}
    }
    match category {
        MemoryCategory::Core => "semantic".to_string(),
        MemoryCategory::Daily | MemoryCategory::Conversation => "episodic".to_string(),
        MemoryCategory::Custom(name) => {
            let name = name.trim().to_ascii_lowercase();
            if WRITE_NODE_TYPES.contains(&name.as_str()) {
                name
            } else {
                "semantic".to_string()
            }
        }
    }
}

fn within(entry: &MemoryEntry, since: Option<&str>, until: Option<&str>) -> bool {
    let Ok(ts) = chrono::DateTime::parse_from_rfc3339(&entry.timestamp) else {
        return true;
    };
    if let Some(since) = since.and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
        && ts < since
    {
        return false;
    }
    if let Some(until) = until.and_then(|u| chrono::DateTime::parse_from_rfc3339(u).ok())
        && ts > until
    {
        return false;
    }
    true
}

fn ms_to_rfc3339(ms: i64) -> Option<String> {
    chrono::DateTime::<chrono::Utc>::from_timestamp_millis(ms)
        .map(|t| t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true))
}

fn now_rfc3339() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

fn clamp01(v: f64) -> f64 {
    if v.is_finite() { v.clamp(0.0, 1.0) } else { 0.5 }
}

fn truncate(s: &str, max_chars: usize) -> String {
    s.chars().take(max_chars).collect()
}

fn snippet(s: &str) -> String {
    let one_line = s.split_whitespace().collect::<Vec<_>>().join(" ");
    truncate(&one_line, 240)
}

fn expand_home(path: &str) -> PathBuf {
    if let Some(rest) = path.strip_prefix("~/")
        && let Some(home) = std::env::var_os("HOME")
    {
        return PathBuf::from(home).join(rest);
    }
    PathBuf::from(path)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::{TcpListener, TcpStream};
    use std::thread;

    struct Recorded {
        request_line: String,
        authorization: Option<String>,
        body: Value,
    }

    struct Fixture {
        endpoint: String,
        handle: thread::JoinHandle<Vec<Recorded>>,
    }

    impl Fixture {
        fn finish(self) -> Vec<Recorded> {
            self.handle.join().unwrap()
        }
    }

    fn read_http_request(stream: &mut TcpStream) -> String {
        let mut request = Vec::new();
        let mut buffer = [0; 4096];
        loop {
            let read = stream.read(&mut buffer).unwrap();
            assert!(read > 0, "xanima fixture: client closed before the request arrived");
            request.extend_from_slice(&buffer[..read]);
            let Some(header_end) = request.windows(4).position(|w| w == b"\r\n\r\n") else {
                continue;
            };
            let header = String::from_utf8_lossy(&request[..header_end]).to_string();
            let content_length = header
                .lines()
                .find_map(|line| {
                    let (name, value) = line.split_once(':')?;
                    name.eq_ignore_ascii_case("content-length")
                        .then(|| value.trim().parse::<usize>().unwrap())
                })
                .unwrap_or(0);
            if request.len() >= header_end + 4 + content_length {
                return String::from_utf8(request).unwrap();
            }
        }
    }

    /// A canned xanima-server answering `responses` in order (status, body).
    fn serve(responses: Vec<(u16, String)>) -> Fixture {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let endpoint = format!("http://{}", listener.local_addr().unwrap());
        let handle = thread::spawn(move || {
            let mut recorded = Vec::new();
            for (status, body) in responses {
                let (mut stream, _) = listener.accept().unwrap();
                let raw = read_http_request(&mut stream);
                let (head, payload) = raw.split_once("\r\n\r\n").unwrap();
                let request_line = head.lines().next().unwrap().to_string();
                let authorization = head.lines().find_map(|l| {
                    let (k, v) = l.split_once(':')?;
                    k.eq_ignore_ascii_case("authorization")
                        .then(|| v.trim().to_string())
                });
                recorded.push(Recorded {
                    request_line,
                    authorization,
                    body: serde_json::from_str(payload).unwrap_or(Value::Null),
                });
                let reason = match status {
                    200 => "OK",
                    401 => "Unauthorized",
                    _ => "Error",
                };
                write!(
                    stream,
                    "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                )
                .unwrap();
                stream.flush().unwrap();
            }
            recorded
        });
        Fixture { endpoint, handle }
    }

    fn rpc_text(text: &str) -> String {
        json!({"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}})
            .to_string()
    }

    fn rpc_tool_error(text: &str) -> String {
        json!({"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}], "isError": true}})
            .to_string()
    }

    fn query_json(results: Value) -> String {
        rpc_text(&json!({"results": results}).to_string())
    }

    fn client() -> reqwest::Client {
        reqwest::Client::builder().no_proxy().build().unwrap()
    }

    fn memory_with_token(endpoint: &str, token: &str) -> XanimaMemory {
        let mut settings = XanimaSettings::new(endpoint);
        settings.token = Some(token.to_string());
        XanimaMemory::with_client("xanima", settings, client())
    }

    fn memory_with_token_dir(endpoint: &str, dir: &std::path::Path, agent: &str) -> XanimaMemory {
        let mut settings = XanimaSettings::new(endpoint);
        settings.token_file = dir.join("{agent}.token").display().to_string();
        settings.agent = agent.to_string();
        XanimaMemory::with_client("xanima", settings, client())
    }

    #[test]
    fn settings_from_storage_validate_and_default() {
        let cfg = caelza_config::schema::XanimaStorageConfig::default();
        let s = XanimaSettings::from_storage(&cfg).unwrap();
        assert_eq!(s.url, DEFAULT_URL);
        assert_eq!(s.token_file, DEFAULT_TOKEN_FILE);
        assert_eq!(s.agent, "main");
        assert_eq!(s.scope, "all");
        assert_eq!(s.timeout, Duration::from_secs(20));

        let mut bad = caelza_config::schema::XanimaStorageConfig::default();
        bad.scope = "everything".into();
        assert!(XanimaSettings::from_storage(&bad).is_err());
        let mut bad = caelza_config::schema::XanimaStorageConfig::default();
        bad.url = "127.0.0.1:18790".into();
        assert!(XanimaSettings::from_storage(&bad).is_err());
        let mut trailing = caelza_config::schema::XanimaStorageConfig::default();
        trailing.url = "http://brain.local:18790/".into();
        trailing.token = Some("  swt_x  ".into());
        let s = XanimaSettings::from_storage(&trailing).unwrap();
        assert_eq!(s.url, "http://brain.local:18790");
        assert_eq!(s.token.as_deref(), Some("swt_x"));
    }

    #[test]
    fn node_types_map_both_ways() {
        assert_eq!(node_type_for(&MemoryCategory::Core, None), "semantic");
        assert_eq!(node_type_for(&MemoryCategory::Daily, None), "episodic");
        assert_eq!(node_type_for(&MemoryCategory::Custom("goal".into()), None), "goal");
        assert_eq!(node_type_for(&MemoryCategory::Custom("weird".into()), None), "semantic");
        assert_eq!(
            node_type_for(&MemoryCategory::Core, Some(&MemoryKind::Procedural)),
            "procedural"
        );
        assert_eq!(category_for_node_type("episodic"), MemoryCategory::Daily);
        assert_eq!(category_for_node_type("identity"), MemoryCategory::Core);
        assert_eq!(
            category_for_node_type("reflection"),
            MemoryCategory::Custom("reflection".into())
        );
        assert_eq!(kind_for_node_type("skill"), Some(MemoryKind::Procedural));
        assert!(parse_rpc_body("event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"content\":[]}}\n\n").is_ok());
        assert!(parse_rpc_body("nonsense").is_err());
    }

    #[tokio::test]
    async fn recall_maps_brain_query_json_to_entries() {
        let fixture = serve(vec![(
            200,
            query_json(json!([
                {"brain": "private", "id": "n1", "type": "semantic", "label": "owner_name",
                 "content": "The owner is Ada", "score": 0.91, "importance": 0.7,
                 "writer": "main", "created_at": 1_760_000_000_000i64},
                {"brain": "shared", "id": "n2", "type": "episodic", "label": "hub_boot",
                 "content": "the hub rebooted", "score": 0.4, "writer": "hub"}
            ])),
        )]);
        let memory = memory_with_token(&fixture.endpoint, "swt_test");

        let entries = memory.recall("who is the owner", 5, None, None, None).await.unwrap();
        let recorded = fixture.finish();

        assert_eq!(recorded.len(), 1);
        assert_eq!(recorded[0].request_line, "POST /mcp HTTP/1.1");
        assert_eq!(recorded[0].authorization.as_deref(), Some("Bearer swt_test"));
        let body = &recorded[0].body;
        assert_eq!(body["method"], "tools/call");
        assert_eq!(body["params"]["name"], "brain_query");
        assert_eq!(body["params"]["arguments"]["query"], "who is the owner");
        assert_eq!(body["params"]["arguments"]["limit"], 5);
        assert_eq!(body["params"]["arguments"]["scope"], "all");
        assert_eq!(body["params"]["arguments"]["format"], "json");

        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].id, "n1");
        assert_eq!(entries[0].key, "owner_name");
        assert_eq!(entries[0].content, "The owner is Ada");
        assert_eq!(entries[0].category, MemoryCategory::Core);
        assert_eq!(entries[0].namespace, "private");
        assert_eq!(entries[0].score, Some(0.91));
        assert_eq!(entries[0].importance, Some(0.7));
        assert!(entries[0].timestamp.starts_with("2025-10-09T"), "{}", entries[0].timestamp);
        assert_eq!(entries[0].agent_id.as_deref(), Some("main"));
        assert_eq!(entries[1].category, MemoryCategory::Daily);
        assert_eq!(entries[1].namespace, "shared");
        assert_eq!(entries[1].agent_alias.as_deref(), Some("hub"));
        assert_eq!(entries[1].agent_id.as_deref(), Some("main"));
        assert_eq!(entries[1].kind, Some(MemoryKind::Episodic));
    }

    #[tokio::test]
    async fn empty_query_and_empty_results_recall_nothing_without_a_call() {
        let fixture = serve(vec![(200, query_json(json!([])))]);
        let memory = memory_with_token(&fixture.endpoint, "swt_test");
        assert!(memory.recall("", 5, None, None, None).await.unwrap().is_empty());
        assert!(memory.recall("*", 5, None, None, None).await.unwrap().is_empty());
        assert!(memory.recall("anything", 5, None, None, None).await.unwrap().is_empty());
        assert_eq!(fixture.finish().len(), 1);
    }

    #[tokio::test]
    async fn store_routes_turns_to_episodes_and_facts_to_nodes() {
        let fixture = serve(vec![
            (200, rpc_text("Appended: episode 7 (user) brain=private writer=main importance=0.40")),
            (200, rpc_text("Written: node n9 (semantic) \"owner_name\" brain=private writer=main")),
            (200, rpc_text("Written: node n10 (procedural) \"deploy\" brain=private writer=main")),
        ]);
        let memory = memory_with_token(&fixture.endpoint, "swt_test");

        memory
            .store("user_msg_1700000000", "hello there", MemoryCategory::Conversation, Some("telegram:42"))
            .await
            .unwrap();
        memory
            .store_with_metadata("owner_name", "Ada", MemoryCategory::Core, None, Some("default"), Some(0.8))
            .await
            .unwrap();
        memory
            .store_with_options(
                "deploy",
                "ssh then systemctl restart",
                MemoryCategory::Core,
                None,
                StoreOptions::default().with_kind(MemoryKind::Procedural).pinned(true),
            )
            .await
            .unwrap();
        let recorded = fixture.finish();

        let a = &recorded[0].body["params"];
        assert_eq!(a["name"], "brain_episode_append");
        assert_eq!(a["arguments"]["role"], "user");
        assert_eq!(a["arguments"]["session_id"], "telegram:42");
        assert_eq!(a["arguments"]["content"], "hello there");
        assert_eq!(a["arguments"]["meta"]["key"], "user_msg_1700000000");

        let b = &recorded[1].body["params"];
        assert_eq!(b["name"], "brain_write");
        assert_eq!(b["arguments"]["type"], "semantic");
        assert_eq!(b["arguments"]["label"], "owner_name");
        assert_eq!(b["arguments"]["content"], "Ada");
        assert_eq!(b["arguments"]["importance"], 0.8);

        let c = &recorded[2].body["params"];
        assert_eq!(c["name"], "brain_write");
        assert_eq!(c["arguments"]["type"], "procedural");
        assert_eq!(c["arguments"]["importance"], 1.0);
    }

    #[tokio::test]
    async fn forget_finds_the_node_by_label_then_forgets_it() {
        let fixture = serve(vec![
            (
                200,
                query_json(json!([
                    {"brain": "private", "id": "old", "type": "semantic", "label": "owner_name", "content": "x", "created_at": 1_700_000_000_000i64},
                    {"brain": "private", "id": "new", "type": "semantic", "label": "owner_name", "content": "y", "created_at": 1_760_000_000_000i64},
                    {"brain": "private", "id": "other", "type": "semantic", "label": "owner_names", "content": "z"}
                ])),
            ),
            (200, rpc_text("Forgotten: new\n(brain=private)")),
            (200, query_json(json!([]))),
        ]);
        let memory = memory_with_token(&fixture.endpoint, "swt_test");

        assert!(memory.forget("owner_name").await.unwrap());
        assert!(!memory.forget("nothing_here").await.unwrap());
        let recorded = fixture.finish();

        assert_eq!(recorded.len(), 3);
        assert_eq!(recorded[0].body["params"]["name"], "brain_query");
        assert_eq!(recorded[1].body["params"]["name"], "brain_forget");
        assert_eq!(recorded[1].body["params"]["arguments"]["node_id"], "new");
        assert!(recorded[1].body["params"]["arguments"].get("visibility").is_none());
    }

    #[tokio::test]
    async fn tool_errors_and_rejected_tokens_are_clear() {
        let fixture = serve(vec![
            (200, rpc_tool_error("Error: forbidden — this token has no write scope")),
            (401, json!({"jsonrpc": "2.0", "error": {"code": -32001, "message": "Unauthorized"}, "id": null}).to_string()),
        ]);
        let memory = memory_with_token(&fixture.endpoint, "swt_test");

        let err = memory
            .store("k", "v", MemoryCategory::Core, None)
            .await
            .unwrap_err()
            .to_string();
        assert!(err.contains("brain_write") && err.contains("write scope"), "{err}");

        let err = memory
            .store("k", "v", MemoryCategory::Core, None)
            .await
            .unwrap_err()
            .to_string();
        assert!(err.contains("401") && err.contains("token mint"), "{err}");
        fixture.finish();
    }

    #[tokio::test]
    async fn per_agent_token_files_pick_the_agent_token() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("alpha.token"), "swt_alpha\n").unwrap();
        std::fs::write(dir.path().join("beta.token"), "swt_beta").unwrap();
        let fixture = serve(vec![
            (200, rpc_text("Written: node 1")),
            (200, rpc_text("Written: node 2")),
        ]);
        let memory = memory_with_token_dir(&fixture.endpoint, dir.path(), "alpha");

        memory.store("k", "v", MemoryCategory::Core, None).await.unwrap();
        memory
            .store_with_agent("k", "v", MemoryCategory::Core, None, None, None, Some("beta"))
            .await
            .unwrap();
        let recorded = fixture.finish();
        assert_eq!(recorded[0].authorization.as_deref(), Some("Bearer swt_alpha"));
        assert_eq!(recorded[1].authorization.as_deref(), Some("Bearer swt_beta"));

        let err = memory
            .store_with_agent("k", "v", MemoryCategory::Core, None, None, None, Some("ghost"))
            .await
            .unwrap_err()
            .to_string();
        assert!(err.contains("ghost.token") && err.contains("token mint"), "{err}");
    }

    #[tokio::test]
    async fn recall_for_agents_skips_brains_without_a_token_but_needs_one() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("alpha.token"), "swt_alpha").unwrap();
        let fixture = serve(vec![(
            200,
            query_json(json!([{"brain": "private", "id": "n1", "type": "semantic", "label": "l", "content": "c", "score": 0.5}])),
        )]);
        let memory = memory_with_token_dir(&fixture.endpoint, dir.path(), "alpha");

        let entries = memory
            .recall_for_agents(&["alpha", "ghost"], "l", 5, None, None, None)
            .await
            .unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].agent_id.as_deref(), Some("alpha"));

        let err = memory
            .recall_for_agents(&["ghost"], "l", 5, None, None, None)
            .await
            .unwrap_err()
            .to_string();
        assert!(err.contains("no token for agent \"ghost\""), "{err}");
        assert_eq!(fixture.finish().len(), 1);
    }

    #[tokio::test]
    async fn count_and_stats_read_brain_stats_and_health_hits_health() {
        let stats = json!({"agentId": "main", "brains": [
            {"brain": "private", "nodes": 12, "nodesByType": {"semantic": 9, "episodic": 3}},
            {"brain": "shared", "nodes": 3, "nodesByType": {"semantic": 3}}
        ]});
        let fixture = serve(vec![
            (200, rpc_text(&stats.to_string())),
            (200, rpc_text(&stats.to_string())),
            (200, json!({"status": "ok", "version": "0.5.0"}).to_string()),
        ]);
        let memory = memory_with_token(&fixture.endpoint, "swt_test");

        assert_eq!(memory.count().await.unwrap(), 15);
        let s = memory.stats().await.unwrap();
        assert_eq!(s.total_rows, 15);
        assert_eq!(s.by_category, vec![("semantic".to_string(), 12), ("episodic".to_string(), 3)]);
        assert!(memory.health_check().await);
        let recorded = fixture.finish();
        assert_eq!(recorded[0].body["params"]["name"], "brain_stats");
        assert_eq!(recorded[0].body["params"]["arguments"]["visibility"], "all");
        assert_eq!(recorded[2].request_line, "GET /health HTTP/1.1");
        assert!(recorded[2].authorization.is_none());
    }

    /// Live round trip against a running service. Not part of the normal run:
    ///
    /// ```sh
    /// CAELZA_XANIMA_E2E_URL=http://127.0.0.1:18790 \
    /// CAELZA_XANIMA_E2E_TOKEN_FILE=~/.xanima/tokens/{agent}.token \
    /// cargo test -p caelza-memory --lib -- xanima::tests::live --include-ignored
    /// ```
    #[tokio::test]
    #[ignore = "needs a running xanima-server (CAELZA_XANIMA_E2E_URL, CAELZA_XANIMA_E2E_TOKEN_FILE)"]
    async fn live_round_trip_against_a_running_service() {
        let Ok(url) = std::env::var("CAELZA_XANIMA_E2E_URL") else {
            eprintln!("CAELZA_XANIMA_E2E_URL unset; skipping");
            return;
        };
        let mut settings = XanimaSettings::new(&url);
        settings.token_file = std::env::var("CAELZA_XANIMA_E2E_TOKEN_FILE")
            .expect("CAELZA_XANIMA_E2E_TOKEN_FILE ({agent} placeholder allowed)");
        settings.agent = std::env::var("CAELZA_XANIMA_E2E_AGENT").unwrap_or_else(|_| "main".into());
        let memory = XanimaMemory::with_client("xanima", settings, client());

        assert!(memory.health_check().await, "service at {url} is not healthy");
        let key = format!("e2e_{}", uuid::Uuid::new_v4().simple());
        let fact = "Caelza end-to-end check: the hub in the attic is called Tycho";
        memory.store(&key, fact, MemoryCategory::Core, None).await.unwrap();
        memory
            .store(
                "user_msg_e2e",
                "please remember that the hub in the attic is called Tycho",
                MemoryCategory::Conversation,
                Some("caelza:e2e"),
            )
            .await
            .unwrap();

        let hits = memory
            .recall("what is the hub in the attic called", 5, None, None, None)
            .await
            .unwrap();
        assert!(hits.iter().any(|h| h.key == key), "recall missed the fact: {hits:?}");
        let got = memory.get(&key).await.unwrap().expect("get by key");
        assert_eq!(got.content, fact);
        assert_eq!(got.category, MemoryCategory::Core);
        assert!(memory.count().await.unwrap() >= 1);
        assert!(memory.stats().await.unwrap().total_rows >= 1);

        assert!(memory.forget(&key).await.unwrap(), "forget should find the node");
        assert!(memory.get(&key).await.unwrap().is_none(), "forgotten node still recalled");
        assert!(!memory.forget(&key).await.unwrap());
    }

    #[tokio::test]
    async fn health_is_false_when_nothing_listens() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let endpoint = format!("http://{}", listener.local_addr().unwrap());
        drop(listener);
        let memory = memory_with_token(&endpoint, "swt_test");
        assert!(!memory.health_check().await);
        assert!(memory.list(None, None).await.unwrap().is_empty());
        assert_eq!(memory.name(), "xanima");
    }
}
