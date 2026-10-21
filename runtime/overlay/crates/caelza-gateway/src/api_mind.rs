//! The Mind on the dashboard: `/api/mind/*`.
//!
//! The dashboard's Memory page talks to the xanima brain service through the
//! Runtime, never directly: the gateway resolves the active `xanima` storage
//! entry, picks the agent's bearer token on the host and makes the brain tool
//! calls itself, so tokens never reach a browser. When the Mind is not the
//! active memory backend, `/api/mind/status` says so and how to turn it on;
//! every other route answers 409.
//!
//! Routes (all behind the dashboard's pairing auth):
//! - `GET  /api/mind/status?agent=`      health, brain stats and status per brain
//! - `GET  /api/mind/recall?q=&limit=&agent=`  `brain_query` (format json)
//! - `POST /api/mind/forget`             `{node_id, agent?, visibility?}` → `brain_forget`
//! - `GET  /api/mind/review?agent=&status=`     the review queue (`brain_review list`)
//! - `POST /api/mind/review`             `{id, action: accept|reject, reason?, agent?}`
//! - `GET  /api/mind/digest?agent=`      what the Mind would tell you first: attention,
//!   focus and last sleep (`brain_status`), open commitments (`brain_commitments`),
//!   open questions (`brain_list_open`); the Home page's "since you were away"

use super::AppState;
use super::api::require_auth;
use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Json, Response},
};
use caelza_config::schema::{ActiveStorage, Config, XanimaStorageConfig};
use caelza_memory::{Memory, XanimaMemory, XanimaSettings, backend_kind_from_dotted};
use serde::Deserialize;
use serde_json::{Value, json};

/// How the Mind is wired for this install, read from the live config.
#[derive(Debug)]
pub(crate) enum MindWiring {
    /// `[memory] backend` is something else; `backend` is its value.
    Disabled { backend: String },
    /// The xanima backend, with its resolved connection settings.
    Enabled(XanimaSettings),
}

pub(crate) const ENABLE_HINT: &str = "Set [memory] backend = \"xanima\" with a [storage.xanima.default] block \
     (mind/caelza-mind.example.toml), mint one token per agent with `xanima-server token mint`, \
     and restart the daemon.";

pub(crate) fn mind_wiring(config: &Config) -> Result<MindWiring, String> {
    let backend = config.memory.backend.trim().to_string();
    if backend_kind_from_dotted(&backend) != "xanima" {
        return Ok(MindWiring::Disabled { backend });
    }
    let storage = match config.resolve_active_storage() {
        ActiveStorage::Xanima(x) => x.clone(),
        _ => XanimaStorageConfig::default(),
    };
    XanimaSettings::from_storage(&storage)
        .map(MindWiring::Enabled)
        .map_err(|e| e.to_string())
}

fn error_response(status: StatusCode, message: impl Into<String>) -> Response {
    (status, Json(json!({"error": message.into()}))).into_response()
}

/// The configured Mind, or the response that explains why there is none.
fn open_mind(state: &AppState) -> Result<(Config, XanimaSettings, XanimaMemory), Response> {
    let config = state.config.read().clone();
    match mind_wiring(&config) {
        Err(e) => Err(error_response(StatusCode::INTERNAL_SERVER_ERROR, e)),
        Ok(MindWiring::Disabled { backend }) => Err((
            StatusCode::CONFLICT,
            Json(json!({
                "error": format!("The Mind is not the active memory backend (memory.backend = {backend:?})"),
                "enabled": false,
                "backend": backend,
                "hint": ENABLE_HINT,
            })),
        )
            .into_response()),
        Ok(MindWiring::Enabled(settings)) => {
            let memory = XanimaMemory::new("xanima", settings.clone());
            Ok((config, settings, memory))
        }
    }
}

/// The brain to talk to: a configured agent alias, or the install default.
fn resolve_agent(
    config: &Config,
    settings: &XanimaSettings,
    requested: Option<&str>,
) -> Result<String, Response> {
    match requested.map(str::trim).filter(|s| !s.is_empty()) {
        None => Ok(settings.agent.clone()),
        Some(alias) if config.agent(alias).is_some() => Ok(alias.to_string()),
        Some(alias) => Err(error_response(
            StatusCode::BAD_REQUEST,
            format!("Unknown agent {alias:?} (no [agents.{alias}] entry configured)"),
        )),
    }
}

#[derive(Debug, Deserialize)]
pub struct AgentQuery {
    #[serde(default)]
    pub agent: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct RecallQuery {
    pub q: String,
    #[serde(default)]
    pub limit: Option<usize>,
    #[serde(default)]
    pub agent: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct ReviewQuery {
    #[serde(default)]
    pub agent: Option<String>,
    /// pending (default) | accepted | rejected | logged | all
    #[serde(default)]
    pub status: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct ForgetBody {
    pub node_id: String,
    #[serde(default)]
    pub agent: Option<String>,
    /// `private` (default) or `shared`.
    #[serde(default)]
    pub visibility: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct ReviewDecision {
    pub id: String,
    /// `accept` or `reject`.
    pub action: String,
    #[serde(default)]
    pub reason: Option<String>,
    #[serde(default)]
    pub agent: Option<String>,
}

/// GET /api/mind/status
pub async fn handle_mind_status(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<AgentQuery>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let config = state.config.read().clone();
    let settings = match mind_wiring(&config) {
        Err(e) => return error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
        Ok(MindWiring::Disabled { backend }) => {
            return Json(json!({
                "enabled": false,
                "backend": backend,
                "hint": ENABLE_HINT,
            }))
            .into_response();
        }
        Ok(MindWiring::Enabled(settings)) => settings,
    };
    let agent = match resolve_agent(&config, &settings, q.agent.as_deref()) {
        Ok(a) => a,
        Err(r) => return r,
    };
    let memory = XanimaMemory::new("xanima", settings.clone());
    let healthy = memory.health_check().await;
    let has_token = memory.has_token(&agent);
    let mut agents: Vec<String> = config.agents.keys().cloned().collect();
    agents.sort();
    let mut errors: Vec<String> = Vec::new();
    let mut stats = Value::Null;
    let mut status = Value::Null;
    if healthy && has_token {
        match memory
            .call_tool_json(
                &agent,
                "brain_stats",
                json!({"visibility": settings.scope, "format": "json"}),
            )
            .await
        {
            Ok(v) => stats = v,
            Err(e) => errors.push(e.to_string()),
        }
        match memory
            .call_tool_json(
                &agent,
                "brain_status",
                json!({"visibility": settings.scope, "format": "json"}),
            )
            .await
        {
            Ok(v) => status = v,
            Err(e) => errors.push(e.to_string()),
        }
    }
    Json(json!({
        "enabled": true,
        "healthy": healthy,
        "url": settings.url,
        "scope": settings.scope,
        "agent": agent,
        "default_agent": settings.agent,
        "agents": agents,
        "has_token": has_token,
        "token_file": memory.token_path_for(&agent).display().to_string(),
        "stats": stats,
        "status": status,
        "errors": errors,
    }))
    .into_response()
}

/// GET /api/mind/recall?q=&limit=&agent=
pub async fn handle_mind_recall(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<RecallQuery>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let query = q.q.trim();
    if query.is_empty() {
        return error_response(StatusCode::BAD_REQUEST, "q is required");
    }
    let (config, settings, memory) = match open_mind(&state) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let agent = match resolve_agent(&config, &settings, q.agent.as_deref()) {
        Ok(a) => a,
        Err(r) => return r,
    };
    let limit = q.limit.unwrap_or(12).clamp(1, 100);
    match memory
        .call_tool_json(
            &agent,
            "brain_query",
            json!({"query": query, "limit": limit, "scope": settings.scope, "format": "json"}),
        )
        .await
    {
        Ok(payload) => {
            let results = payload
                .get("results")
                .cloned()
                .unwrap_or_else(|| Value::Array(Vec::new()));
            Json(json!({"agent": agent, "query": query, "results": results})).into_response()
        }
        Err(e) => error_response(StatusCode::BAD_GATEWAY, e.to_string()),
    }
}

/// POST /api/mind/forget
pub async fn handle_mind_forget(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<ForgetBody>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let node_id = body.node_id.trim();
    if node_id.is_empty() {
        return error_response(StatusCode::BAD_REQUEST, "node_id is required");
    }
    let (config, settings, memory) = match open_mind(&state) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let agent = match resolve_agent(&config, &settings, body.agent.as_deref()) {
        Ok(a) => a,
        Err(r) => return r,
    };
    let mut args = json!({"node_id": node_id});
    if body.visibility.as_deref() == Some("shared") {
        args["visibility"] = json!("shared");
    }
    match memory.call_tool_json(&agent, "brain_forget", args).await {
        Ok(reply) => Json(json!({
            "status": "ok",
            "agent": agent,
            "node_id": node_id,
            "text": reply.get("text").cloned().unwrap_or(reply),
        }))
        .into_response(),
        Err(e) => error_response(StatusCode::BAD_GATEWAY, e.to_string()),
    }
}

/// GET /api/mind/review?agent=&status=
pub async fn handle_mind_review_list(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<ReviewQuery>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let (config, settings, memory) = match open_mind(&state) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let agent = match resolve_agent(&config, &settings, q.agent.as_deref()) {
        Ok(a) => a,
        Err(r) => return r,
    };
    let status = match q.status.as_deref().map(str::trim) {
        None | Some("") => "pending",
        Some(s @ ("pending" | "accepted" | "rejected" | "logged" | "all")) => s,
        Some(other) => {
            return error_response(
                StatusCode::BAD_REQUEST,
                format!("status must be pending, accepted, rejected, logged or all, not {other:?}"),
            );
        }
    };
    match memory
        .call_tool_json(&agent, "brain_review", json!({"action": "list", "status": status}))
        .await
    {
        Ok(reply) => {
            let raw = reply
                .get("text")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string();
            Json(json!({
                "agent": agent,
                "status": status,
                "items": parse_review_lines(&raw),
                "raw": raw,
            }))
            .into_response()
        }
        Err(e) => error_response(StatusCode::BAD_GATEWAY, e.to_string()),
    }
}

/// POST /api/mind/review
pub async fn handle_mind_review_decide(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<ReviewDecision>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let action = body.action.trim();
    if action != "accept" && action != "reject" {
        return error_response(StatusCode::BAD_REQUEST, "action must be accept or reject");
    }
    let id = body.id.trim();
    if id.is_empty() {
        return error_response(StatusCode::BAD_REQUEST, "id is required");
    }
    let (config, settings, memory) = match open_mind(&state) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let agent = match resolve_agent(&config, &settings, body.agent.as_deref()) {
        Ok(a) => a,
        Err(r) => return r,
    };
    let mut args = json!({"action": action, "id": id});
    if let Some(reason) = body.reason.as_deref().map(str::trim).filter(|r| !r.is_empty()) {
        args["reason"] = json!(reason);
    }
    match memory.call_tool_json(&agent, "brain_review", args).await {
        Ok(reply) => Json(json!({
            "status": "ok",
            "agent": agent,
            "id": id,
            "action": action,
            "text": reply.get("text").cloned().unwrap_or(reply),
        }))
        .into_response(),
        // The service refuses accept/reject without an admin-scoped token; its
        // message says so, and the page shows it as is.
        Err(e) => error_response(StatusCode::BAD_GATEWAY, e.to_string()),
    }
}

/// GET /api/mind/digest?agent=
pub async fn handle_mind_digest(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<AgentQuery>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let (config, settings, memory) = match open_mind(&state) {
        Ok(m) => m,
        Err(r) => return r,
    };
    let agent = match resolve_agent(&config, &settings, q.agent.as_deref()) {
        Ok(a) => a,
        Err(r) => return r,
    };
    let mut errors: Vec<String> = Vec::new();
    let mut take = |result: anyhow::Result<Value>| -> Value {
        match result {
            Ok(v) => v,
            Err(e) => {
                errors.push(e.to_string());
                Value::Null
            }
        }
    };
    let status = take(
        memory
            .call_tool_json(
                &agent,
                "brain_status",
                json!({"visibility": "private", "format": "json"}),
            )
            .await,
    );
    let commitments = take(
        memory
            .call_tool_json(
                &agent,
                "brain_commitments",
                json!({"status": "open", "format": "json"}),
            )
            .await,
    );
    let open = take(
        memory
            .call_tool_json(
                &agent,
                "brain_list_open",
                json!({"status": "active", "limit": 8, "format": "json"}),
            )
            .await,
    );
    let brain = private_brain(&status).cloned().unwrap_or(Value::Null);
    Json(json!({
        "agent": agent,
        "attention": brain.get("attention").cloned().unwrap_or_else(|| json!([])),
        "focus": brain.get("focus").cloned().unwrap_or(Value::Null),
        "last_sleep": brain.get("lastSleep").cloned().unwrap_or(Value::Null),
        "commitments": digest_items(&commitments, "commitments"),
        "open_items": digest_items(&open, "items"),
        "errors": errors,
    }))
    .into_response()
}

/// The private brain's entry in a `brain_status` JSON reply, else the first brain.
pub(crate) fn private_brain(status: &Value) -> Option<&Value> {
    let brains = status.get("brains")?.as_array()?;
    brains
        .iter()
        .find(|b| b.get("brain").and_then(Value::as_str) == Some("private"))
        .or_else(|| brains.first())
}

/// The array under `key` in a continuity tool's JSON reply. A text reply
/// ("No commitments match.") or a failed call is an empty list.
pub(crate) fn digest_items(reply: &Value, key: &str) -> Vec<Value> {
    reply
        .get(key)
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

/// `brain_review list` answers in text, one item per line:
/// `<id> [<status>] <kind> (<section>) <label>[ ⚠ <flags>]: <reason>`.
/// Lines that are not items (the count header, "No pending review items.") are
/// dropped.
pub(crate) fn parse_review_lines(text: &str) -> Vec<Value> {
    text.lines().filter_map(parse_review_line).collect()
}

pub(crate) fn parse_review_line(line: &str) -> Option<Value> {
    let line = line.trim();
    let (id, rest) = line.split_once(" [")?;
    if id.is_empty() || id.contains(' ') {
        return None;
    }
    let (status, rest) = rest.split_once("] ")?;
    let (kind, rest) = rest.split_once(" (")?;
    let (section, rest) = rest.split_once(") ")?;
    let (label_part, reason) = match rest.rsplit_once(": ") {
        Some((label, reason)) => (label, Some(reason.trim())),
        None => (rest.trim_end_matches(':'), None),
    };
    let (label, flags): (&str, Vec<String>) = match label_part.split_once(" \u{26a0} ") {
        Some((label, flags)) => (label, flags.split(", ").map(str::to_string).collect()),
        None => (label_part, Vec::new()),
    };
    Some(json!({
        "id": id,
        "status": status,
        "kind": kind,
        "section": section,
        "label": label.trim(),
        "flags": flags,
        "reason": reason.filter(|r| !r.is_empty()),
        "raw": line,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn review_lines_parse_items_and_skip_headers() {
        let text = "2 review item(s) (pending):\n\
                    rev_1a2b [pending] quarantine (identity) New name for me ⚠ untrusted, tool-output: identity write from tool output\n\
                    rev_3c4d [pending] identity_change (values) I value speed over care: proposed by main";
        let items = parse_review_lines(text);
        assert_eq!(items.len(), 2);
        assert_eq!(items[0]["id"], "rev_1a2b");
        assert_eq!(items[0]["status"], "pending");
        assert_eq!(items[0]["kind"], "quarantine");
        assert_eq!(items[0]["section"], "identity");
        assert_eq!(items[0]["label"], "New name for me");
        assert_eq!(items[0]["flags"], json!(["untrusted", "tool-output"]));
        assert_eq!(items[0]["reason"], "identity write from tool output");
        assert_eq!(items[1]["kind"], "identity_change");
        assert_eq!(items[1]["flags"], json!([]));
        assert_eq!(items[1]["label"], "I value speed over care");
        assert_eq!(items[1]["reason"], "proposed by main");
        assert!(parse_review_lines("No pending review items.").is_empty());
        assert!(parse_review_line("").is_none());
    }

    #[test]
    fn digest_reads_the_private_brain_and_the_item_lists() {
        let status = json!({
            "agentId": "main",
            "brains": [
                {"brain": "shared", "attention": ["shared note"]},
                {"brain": "private", "attention": ["a", "b"], "focus": "ship the page"},
            ],
        });
        assert_eq!(private_brain(&status).unwrap()["focus"], "ship the page");
        let only_shared = json!({"brains": [{"brain": "shared"}]});
        assert_eq!(private_brain(&only_shared).unwrap()["brain"], "shared");
        assert!(private_brain(&json!({"text": "error: no brain"})).is_none());
        assert!(private_brain(&Value::Null).is_none());

        let commitments = json!({"commitments": [{"title": "call back"}, {"title": "ship"}]});
        assert_eq!(digest_items(&commitments, "commitments").len(), 2);
        assert!(digest_items(&json!({"text": "No commitments match."}), "commitments").is_empty());
        assert!(digest_items(&Value::Null, "items").is_empty());
    }

    #[test]
    fn mind_wiring_reads_the_memory_backend() {
        let config = Config::default();
        match mind_wiring(&config).unwrap() {
            MindWiring::Disabled { backend } => assert!(!backend.is_empty()),
            other => panic!("default config must not enable the Mind: {other:?}"),
        }

        let mut config = Config::default();
        config.memory.backend = "xanima".into();
        match mind_wiring(&config).unwrap() {
            MindWiring::Enabled(settings) => {
                assert_eq!(settings.url, caelza_memory::xanima::DEFAULT_URL);
                assert_eq!(settings.agent, "main");
            }
            other => panic!("bare xanima backend must use the loopback defaults: {other:?}"),
        }

        let mut config = Config::default();
        config.memory.backend = "xanima.hub".into();
        let mut entry = XanimaStorageConfig::default();
        entry.url = "http://hub.local:18790/".into();
        entry.agent = "clamps".into();
        entry.scope = "private".into();
        config.storage.xanima.insert("hub".into(), entry);
        match mind_wiring(&config).unwrap() {
            MindWiring::Enabled(settings) => {
                assert_eq!(settings.url, "http://hub.local:18790");
                assert_eq!(settings.agent, "clamps");
                assert_eq!(settings.scope, "private");
            }
            other => panic!("expected the hub entry: {other:?}"),
        }

        let mut bad = config.clone();
        bad.storage.xanima.get_mut("hub").unwrap().scope = "everything".into();
        assert!(mind_wiring(&bad).is_err());
    }

    #[test]
    fn resolve_agent_requires_a_configured_alias() {
        let mut config = Config::default();
        config.memory.backend = "xanima".into();
        let MindWiring::Enabled(settings) = mind_wiring(&config).unwrap() else {
            panic!("enabled");
        };
        assert_eq!(resolve_agent(&config, &settings, None).unwrap(), "main");
        assert_eq!(resolve_agent(&config, &settings, Some("  ")).unwrap(), "main");
        assert!(resolve_agent(&config, &settings, Some("ghost")).is_err());
        config
            .agents
            .insert("beta".into(), caelza_config::schema::AliasedAgentConfig::default());
        assert_eq!(resolve_agent(&config, &settings, Some("beta")).unwrap(), "beta");
    }
}
