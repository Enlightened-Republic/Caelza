//! The Body on the dashboard: `/api/bodies/*`.
//!
//! The dashboard's Bodies page talks to the Body (`caelza-body`, the device
//! layer served over MCP) through the Runtime, never directly: the gateway
//! reads the `[[mcp.servers]]` entry named `body`, keeps one connection to it
//! for the dashboard and makes the device, sensor and capture tool calls
//! itself. Results stay the Body's own (text, or an image block for a
//! screenshot or a photo); the gateway parses the few shapes the page needs.
//! When no Body is configured, `/api/bodies/status` says so and how to wire
//! one in; every other route answers 409.
//!
//! Routes (all behind the dashboard's pairing auth):
//! - `GET    /api/bodies/status?server=`                        wiring, connection, the tools the Body serves
//! - `GET    /api/bodies/devices?server=`                       `device_list`: this phone and the paired phones
//! - `GET    /api/bodies/sensors?kind=&server=`                 `sensors_battery` | `sensors_location` (quick) | `sensors_notifications`
//! - `GET    /api/bodies/packages?device=&flags=&server=`       `device_packages`
//! - `GET    /api/bodies/capture?kind=&device=&facing=&server=` `device_screencap` | `sensors_camera_photo`, the image as base64
//! - `POST   /api/bodies/pair`    `{name, host, code, notes?, server?}` → `device_pair`
//! - `DELETE /api/bodies/pair`    `{name, server?}` → `device_unpair`

use super::AppState;
use super::api::require_auth;
use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Json, Response},
};
use caelza_config::schema::{Config, McpServerConfig};
use caelza_tools::mcp_client::McpServer;
use serde::Deserialize;
use serde_json::{Value, json};
use std::collections::{BTreeMap, HashMap};
use std::sync::OnceLock;
use tokio::sync::Mutex;

/// The `[[mcp.servers]]` entry the page reads when none is named.
pub(crate) const DEFAULT_SERVER: &str = "body";
/// The Body's executable (`caelza-body serve`), so a server under another name
/// still counts as a Body.
pub(crate) const BODY_COMMAND: &str = "caelza-body";

pub(crate) const ENABLE_HINT: &str = "Add the [[mcp.servers]] entry named \"body\" from body/caelza-body.example.toml \
     (command = \"caelza-body\", args = [\"serve\"]), keep [mcp] enabled = true, and restart the daemon.";

/// The Body's own safety classes (`caelza_body/mcp_server.py`); the Runtime's
/// `McpToolDef` carries no annotations, so the dashboard reads them from here.
/// `tests/test_bodies_page.py` keeps these equal to the Python sets.
pub(crate) const READ_ONLY: &[&str] = &[
    "device_list",
    "device_packages",
    "device_logcat",
    "device_settings",
    "device_ui_dump",
    "device_screencap",
    "device_debloat_plan",
    "device_suspects",
    "device_foreground",
    "device_health",
    "sensors_battery",
    "sensors_notifications",
    "sensors_clipboard_get",
    "sensors_location",
    "self_read_file",
    "self_list_tree",
    "web_search",
    "web_read",
    "web_map",
    "web_crawl_result",
];
pub(crate) const DESTRUCTIVE: &[&str] = &[
    "device_uninstall",
    "device_disable",
    "device_settings_put",
    "device_appops",
    "device_pair",
    "device_unpair",
    "device_join",
    "device_shell",
    "shell_run",
    "self_write_file",
    "self_commit",
    "self_request_restart",
];

/// How the Body is wired for this install, read from the live config.
#[derive(Debug)]
pub(crate) enum BodyWiring {
    /// No usable entry; `reason` says what is missing.
    Disabled { reason: String },
    /// The `[[mcp.servers]]` entry to connect to.
    Enabled(McpServerConfig),
}

/// A server is a Body when it is called `body` (or `body-<something>`) or when
/// it runs the Body's executable under another name.
pub(crate) fn is_body_server(server: &McpServerConfig) -> bool {
    let name = server.name.trim();
    if name == DEFAULT_SERVER
        || name.starts_with("body-")
        || name.starts_with("body_")
        || name.starts_with("body.")
    {
        return true;
    }
    std::path::Path::new(server.command.trim())
        .file_name()
        .and_then(|f| f.to_str())
        .is_some_and(|f| f == BODY_COMMAND)
}

/// The Bodies this config knows, by server name.
pub(crate) fn candidate_servers(config: &Config) -> Vec<String> {
    let mut names: Vec<String> = config
        .mcp
        .servers
        .iter()
        .filter(|s| is_body_server(s))
        .map(|s| s.name.clone())
        .collect();
    names.sort();
    names.dedup();
    names
}

pub(crate) fn body_wiring(config: &Config, requested: Option<&str>) -> BodyWiring {
    if !config.mcp.enabled {
        return BodyWiring::Disabled {
            reason: "[mcp] enabled = false, so the Runtime loads no MCP servers".to_string(),
        };
    }
    let name = requested
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or(DEFAULT_SERVER);
    match config.mcp.servers.iter().find(|s| s.name == name) {
        Some(server) => BodyWiring::Enabled(server.clone()),
        None => BodyWiring::Disabled {
            reason: format!("no [[mcp.servers]] entry named {name:?}"),
        },
    }
}

struct BodyLink {
    fingerprint: String,
    server: McpServer,
}

fn links() -> &'static Mutex<HashMap<String, BodyLink>> {
    static LINKS: OnceLock<Mutex<HashMap<String, BodyLink>>> = OnceLock::new();
    LINKS.get_or_init(|| Mutex::new(HashMap::new()))
}

/// One live connection per configured Body, kept for the gateway's lifetime
/// and replaced when its entry changes or its transport dies. A stdio Body is
/// a `caelza-body serve` child of the gateway, the same way the agent runs it.
async fn body_server(config: &McpServerConfig) -> anyhow::Result<McpServer> {
    let fingerprint = serde_json::to_string(config)?;
    let mut map = links().lock().await;
    if let Some(link) = map.get(&config.name)
        && link.fingerprint == fingerprint
        && link.server.health_check()
    {
        return Ok(link.server.clone());
    }
    let server = McpServer::connect(config.clone()).await?;
    map.insert(
        config.name.clone(),
        BodyLink {
            fingerprint,
            server: server.clone(),
        },
    );
    Ok(server)
}

pub(crate) fn tool_class(name: &str) -> &'static str {
    if READ_ONLY.contains(&name) {
        "read-only"
    } else if DESTRUCTIVE.contains(&name) {
        "destructive"
    } else {
        "neutral"
    }
}

/// The Body's tool groups by name prefix: `self_*` is the `selfmod` group.
pub(crate) fn tool_group(name: &str) -> &str {
    match name.split_once('_') {
        Some(("self", _)) => "selfmod",
        Some((group, _)) => group,
        None => name,
    }
}

/// The text blocks of a tool result, joined.
pub(crate) fn text_of(result: &Value) -> String {
    result
        .get("content")
        .and_then(Value::as_array)
        .map(|blocks| {
            blocks
                .iter()
                .filter(|b| b.get("type").and_then(Value::as_str) == Some("text"))
                .filter_map(|b| b.get("text").and_then(Value::as_str))
                .collect::<Vec<_>>()
                .join("\n")
        })
        .unwrap_or_default()
}

/// The first image block of a tool result as `(mime, base64)`.
pub(crate) fn image_of(result: &Value) -> Option<(String, String)> {
    let block = result
        .get("content")?
        .as_array()?
        .iter()
        .find(|b| b.get("type").and_then(Value::as_str) == Some("image"))?;
    let data = block.get("data").and_then(Value::as_str)?;
    let mime = block
        .get("mimeType")
        .and_then(Value::as_str)
        .unwrap_or("image/png");
    Some((mime.to_string(), data.to_string()))
}

/// The Body answers in text; many of its tools answer with JSON text.
pub(crate) fn json_or_text(text: &str) -> Value {
    serde_json::from_str::<Value>(text.trim()).unwrap_or_else(|_| json!({"text": text}))
}

/// `device_list` answers `{<name>: {kind, host | url, groups, last_seen, reachable}, self: {reachable}}`.
/// Rows: this phone first, then the paired phones and joined Bodies by name.
pub(crate) fn device_rows(value: &Value) -> Vec<Value> {
    let Some(map) = value.as_object() else {
        return Vec::new();
    };
    let mut rows: Vec<Value> = map
        .iter()
        .map(|(name, entry)| {
            let kind = entry
                .get("kind")
                .and_then(Value::as_str)
                .map(str::to_string)
                .unwrap_or_else(|| {
                    if name == "self" {
                        "self".to_string()
                    } else if entry.get("url").and_then(Value::as_str).is_some() {
                        "http".to_string()
                    } else {
                        "adb".to_string()
                    }
                });
            let groups: Vec<String> = entry
                .get("groups")
                .and_then(Value::as_array)
                .map(|g| g.iter().filter_map(Value::as_str).map(str::to_string).collect())
                .unwrap_or_default();
            json!({
                "name": name,
                "self": name == "self",
                "kind": kind,
                "host": entry.get("host").cloned().unwrap_or(Value::Null),
                "url": entry.get("url").cloned().unwrap_or(Value::Null),
                "groups": groups,
                "last_seen": entry.get("last_seen").cloned().unwrap_or(Value::Null),
                "reachable": entry.get("reachable").and_then(Value::as_bool).unwrap_or(false),
            })
        })
        .collect();
    rows.sort_by(|a, b| {
        let self_a = a["self"].as_bool().unwrap_or(false);
        let self_b = b["self"].as_bool().unwrap_or(false);
        self_b
            .cmp(&self_a)
            .then_with(|| a["name"].as_str().cmp(&b["name"].as_str()))
    });
    rows
}

/// `pm list packages` lines: `package:com.example`, or with `-f`
/// `package:/data/app/.../base.apk=com.example` (the path may hold `=`).
pub(crate) fn parse_packages(text: &str) -> Vec<Value> {
    let mut out: Vec<Value> = text
        .lines()
        .filter_map(|line| {
            let rest = line.trim().strip_prefix("package:")?;
            let (path, name) = match rest.rsplit_once('=') {
                Some((path, name)) if path.starts_with('/') => (Some(path), name),
                _ => (None, rest),
            };
            let name = name.trim();
            if name.is_empty() {
                return None;
            }
            Some(json!({"name": name, "path": path}))
        })
        .collect();
    out.sort_by(|a, b| a["name"].as_str().cmp(&b["name"].as_str()));
    out
}

fn error_response(status: StatusCode, message: impl Into<String>) -> Response {
    (status, Json(json!({"error": message.into()}))).into_response()
}

fn server_info(server: &McpServerConfig) -> Value {
    json!({
        "name": server.name,
        "transport": server.transport.wire_name(),
        "command": server.command,
        "args": server.args,
        "url": server.url,
        "tool_timeout_secs": server.tool_timeout_secs,
    })
}

/// The configured Body, connected, or the response that explains why there is none.
async fn open_body(
    state: &AppState,
    requested: Option<&str>,
) -> Result<(McpServerConfig, McpServer), Response> {
    let config = state.config.read().clone();
    let server_cfg = match body_wiring(&config, requested) {
        BodyWiring::Disabled { reason } => {
            return Err((
                StatusCode::CONFLICT,
                Json(json!({
                    "error": format!("No Body is configured ({reason})"),
                    "enabled": false,
                    "reason": reason,
                    "hint": ENABLE_HINT,
                    "servers": candidate_servers(&config),
                })),
            )
                .into_response());
        }
        BodyWiring::Enabled(server) => server,
    };
    match body_server(&server_cfg).await {
        Ok(server) => Ok((server_cfg, server)),
        Err(e) => Err(error_response(
            StatusCode::BAD_GATEWAY,
            format!("The Body `{}` did not answer: {e}", server_cfg.name),
        )),
    }
}

/// A Body started with `--tools` may serve fewer groups; say which.
async fn ensure_tool(server: &McpServer, tool: &str) -> Result<(), Response> {
    let tools = server.tools().await;
    if tools.iter().any(|t| t.name == tool) {
        return Ok(());
    }
    let mut groups: Vec<&str> = tools.iter().map(|t| tool_group(&t.name)).collect();
    groups.sort_unstable();
    groups.dedup();
    Err(error_response(
        StatusCode::NOT_FOUND,
        format!(
            "This Body does not serve `{tool}` (groups served: {}); start it with that group in --tools",
            if groups.is_empty() { "none".to_string() } else { groups.join(", ") }
        ),
    ))
}

async fn call(server: &McpServer, tool: &str, args: Value) -> Result<Value, Response> {
    ensure_tool(server, tool).await?;
    server
        .call_tool(tool, args)
        .await
        .map_err(|e| error_response(StatusCode::BAD_GATEWAY, e.to_string()))
}

fn device_or_self(device: Option<&str>) -> &str {
    device
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or("self")
}

#[derive(Debug, Deserialize)]
pub struct ServerQuery {
    #[serde(default)]
    pub server: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct SensorQuery {
    /// battery | location | notifications
    pub kind: String,
    #[serde(default)]
    pub server: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct PackagesQuery {
    #[serde(default)]
    pub device: Option<String>,
    /// `pm list packages` switches: `-3` (default), `-s`, `-f`, or `all` for none.
    #[serde(default)]
    pub flags: Option<String>,
    #[serde(default)]
    pub server: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct CaptureQuery {
    /// screen | camera
    pub kind: String,
    #[serde(default)]
    pub device: Option<String>,
    /// camera only: back (default) | front
    #[serde(default)]
    pub facing: Option<String>,
    #[serde(default)]
    pub server: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct PairBody {
    pub name: String,
    /// `host:port` from the other phone's Wireless debugging screen.
    pub host: String,
    /// The six-digit pairing code shown there.
    pub code: String,
    #[serde(default)]
    pub notes: Option<String>,
    /// Comma-separated groups a procedure can target as a whole.
    #[serde(default)]
    pub groups: Option<String>,
    #[serde(default)]
    pub server: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct UnpairBody {
    pub name: String,
    #[serde(default)]
    pub server: Option<String>,
}

/// GET /api/bodies/status
pub async fn handle_bodies_status(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<ServerQuery>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let config = state.config.read().clone();
    let servers = candidate_servers(&config);
    let server_cfg = match body_wiring(&config, q.server.as_deref()) {
        BodyWiring::Disabled { reason } => {
            return Json(json!({
                "enabled": false,
                "reason": reason,
                "hint": ENABLE_HINT,
                "mcp_enabled": config.mcp.enabled,
                "servers": servers,
            }))
            .into_response();
        }
        BodyWiring::Enabled(server) => server,
    };
    let (connected, error, tools) = match body_server(&server_cfg).await {
        Ok(server) => {
            let names: Vec<String> = server.tools().await.into_iter().map(|t| t.name).collect();
            (true, Value::Null, names)
        }
        Err(e) => (false, json!(e.to_string()), Vec::new()),
    };
    let mut groups: BTreeMap<String, usize> = BTreeMap::new();
    let mut classes: BTreeMap<String, usize> = BTreeMap::new();
    for name in &tools {
        *groups.entry(tool_group(name).to_string()).or_default() += 1;
        *classes.entry(tool_class(name).to_string()).or_default() += 1;
    }
    Json(json!({
        "enabled": true,
        "server": server_info(&server_cfg),
        "servers": servers,
        "connected": connected,
        "error": error,
        "tools": tools,
        "groups": groups,
        "classes": classes,
    }))
    .into_response()
}

/// GET /api/bodies/devices
pub async fn handle_bodies_devices(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<ServerQuery>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let (cfg, server) = match open_body(&state, q.server.as_deref()).await {
        Ok(b) => b,
        Err(r) => return r,
    };
    let result = match call(&server, "device_list", json!({})).await {
        Ok(v) => v,
        Err(r) => return r,
    };
    let text = text_of(&result);
    let value = json_or_text(&text);
    Json(json!({
        "server": cfg.name,
        "devices": device_rows(&value),
        "text": text,
    }))
    .into_response()
}

/// GET /api/bodies/sensors?kind=
pub async fn handle_bodies_sensors(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<SensorQuery>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let kind = q.kind.trim();
    let (tool, args) = match kind {
        "battery" => ("sensors_battery", json!({})),
        "location" => ("sensors_location", json!({"mode": "quick"})),
        "notifications" => ("sensors_notifications", json!({})),
        other => {
            return error_response(
                StatusCode::BAD_REQUEST,
                format!("kind must be battery, location or notifications, not {other:?}"),
            );
        }
    };
    let (cfg, server) = match open_body(&state, q.server.as_deref()).await {
        Ok(b) => b,
        Err(r) => return r,
    };
    let result = match call(&server, tool, args).await {
        Ok(v) => v,
        Err(r) => return r,
    };
    let text = text_of(&result);
    Json(json!({
        "server": cfg.name,
        "kind": kind,
        "data": json_or_text(&text),
        "text": text,
    }))
    .into_response()
}

/// GET /api/bodies/packages?device=&flags=
pub async fn handle_bodies_packages(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<PackagesQuery>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let device = device_or_self(q.device.as_deref());
    let flags = match q.flags.as_deref().map(str::trim) {
        None | Some("") => "-3",
        Some("all") => "",
        Some(f) if f.len() <= 16 && f.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == ' ') => f,
        Some(_) => {
            return error_response(
                StatusCode::BAD_REQUEST,
                "flags may only hold `pm list packages` switches such as -3, -s or -f, or `all`",
            );
        }
    };
    let (cfg, server) = match open_body(&state, q.server.as_deref()).await {
        Ok(b) => b,
        Err(r) => return r,
    };
    let result = match call(
        &server,
        "device_packages",
        json!({"device": device, "flags": flags}),
    )
    .await
    {
        Ok(v) => v,
        Err(r) => return r,
    };
    let packages = parse_packages(&text_of(&result));
    Json(json!({
        "server": cfg.name,
        "device": device,
        "flags": flags,
        "count": packages.len(),
        "packages": packages,
    }))
    .into_response()
}

/// GET /api/bodies/capture?kind=&device=&facing=
pub async fn handle_bodies_capture(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<CaptureQuery>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let device = device_or_self(q.device.as_deref());
    let kind = q.kind.trim();
    let (tool, args, facing) = match kind {
        "screen" => ("device_screencap", json!({"device": device}), Value::Null),
        "camera" => {
            let facing = match q.facing.as_deref().map(str::trim) {
                None | Some("") | Some("back") => "back",
                Some("front") => "front",
                Some(other) => {
                    return error_response(
                        StatusCode::BAD_REQUEST,
                        format!("facing must be back or front, not {other:?}"),
                    );
                }
            };
            ("sensors_camera_photo", json!({"facing": facing}), json!(facing))
        }
        other => {
            return error_response(
                StatusCode::BAD_REQUEST,
                format!("kind must be screen or camera, not {other:?}"),
            );
        }
    };
    let (cfg, server) = match open_body(&state, q.server.as_deref()).await {
        Ok(b) => b,
        Err(r) => return r,
    };
    let result = match call(&server, tool, args).await {
        Ok(v) => v,
        Err(r) => return r,
    };
    let text = text_of(&result);
    match image_of(&result) {
        Some((mime, data)) => Json(json!({
            "server": cfg.name,
            "kind": kind,
            "device": device,
            "facing": facing,
            "mime": mime,
            "data": data,
            "text": text,
        }))
        .into_response(),
        None => error_response(
            StatusCode::BAD_GATEWAY,
            format!("The Body returned no image: {text}"),
        ),
    }
}

/// POST /api/bodies/pair
pub async fn handle_bodies_pair(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<PairBody>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let name = body.name.trim();
    let host = body.host.trim();
    let code = body.code.trim();
    if name.is_empty() || host.is_empty() || code.is_empty() {
        return error_response(StatusCode::BAD_REQUEST, "name, host and code are required");
    }
    if name == "self"
        || !name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
    {
        return error_response(
            StatusCode::BAD_REQUEST,
            "name must be letters, digits, '-', '_' or '.', and not `self`",
        );
    }
    if host.chars().any(char::is_whitespace) {
        return error_response(StatusCode::BAD_REQUEST, "host must be host:port with no spaces");
    }
    let (cfg, server) = match open_body(&state, body.server.as_deref()).await {
        Ok(b) => b,
        Err(r) => return r,
    };
    let mut args = json!({"name": name, "host": host, "code": code});
    if let Some(notes) = body
        .notes
        .as_deref()
        .map(str::trim)
        .filter(|n| !n.is_empty())
    {
        args["notes"] = json!(notes);
    }
    if let Some(groups) = body
        .groups
        .as_deref()
        .map(str::trim)
        .filter(|g| !g.is_empty())
    {
        args["groups"] = json!(groups);
    }
    let result = match call(&server, "device_pair", args).await {
        Ok(v) => v,
        Err(r) => return r,
    };
    // The Body answers `paired '<name>' at <host> and registered`, or
    // `pair failed for <host>:` with adb's text; neither is an MCP error.
    let text = text_of(&result);
    let ok = text.starts_with("paired ");
    Json(json!({
        "status": if ok { "ok" } else { "failed" },
        "server": cfg.name,
        "name": name,
        "host": host,
        "text": text,
    }))
    .into_response()
}

/// DELETE /api/bodies/pair
pub async fn handle_bodies_unpair(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<UnpairBody>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let name = body.name.trim();
    if name.is_empty() {
        return error_response(StatusCode::BAD_REQUEST, "name is required");
    }
    if name == "self" {
        return error_response(
            StatusCode::BAD_REQUEST,
            "this phone is the Body itself and cannot be unpaired",
        );
    }
    let (cfg, server) = match open_body(&state, body.server.as_deref()).await {
        Ok(b) => b,
        Err(r) => return r,
    };
    let result = match call(&server, "device_unpair", json!({"name": name})).await {
        Ok(v) => v,
        Err(r) => return r,
    };
    Json(json!({
        "status": "ok",
        "server": cfg.name,
        "name": name,
        "text": text_of(&result),
    }))
    .into_response()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn body_entry(name: &str, command: &str) -> McpServerConfig {
        McpServerConfig {
            name: name.to_string(),
            command: command.to_string(),
            args: vec!["serve".to_string()],
            ..McpServerConfig::default()
        }
    }

    #[test]
    fn body_wiring_finds_the_body_entry() {
        let config = Config::default();
        match body_wiring(&config, None) {
            BodyWiring::Disabled { reason } => assert!(reason.contains("\"body\""), "{reason}"),
            other => panic!("a default config has no Body: {other:?}"),
        }

        let mut config = Config::default();
        config.mcp.servers.push(body_entry("body", "caelza-body"));
        match body_wiring(&config, None) {
            BodyWiring::Enabled(server) => {
                assert_eq!(server.name, "body");
                assert_eq!(server.command, "caelza-body");
                assert_eq!(server.transport.wire_name(), "stdio");
            }
            other => panic!("expected the body entry: {other:?}"),
        }
        match body_wiring(&config, Some("  ")) {
            BodyWiring::Enabled(server) => assert_eq!(server.name, "body"),
            other => panic!("blank means the default: {other:?}"),
        }
        match body_wiring(&config, Some("ghost")) {
            BodyWiring::Disabled { reason } => assert!(reason.contains("\"ghost\""), "{reason}"),
            other => panic!("an unknown name is disabled: {other:?}"),
        }

        config.mcp.enabled = false;
        match body_wiring(&config, None) {
            BodyWiring::Disabled { reason } => assert!(reason.contains("[mcp] enabled"), "{reason}"),
            other => panic!("mcp off disables every Body: {other:?}"),
        }
    }

    #[test]
    fn candidate_servers_are_the_bodies_only() {
        let mut config = Config::default();
        config.mcp.servers.push(body_entry("github", "github-mcp"));
        config.mcp.servers.push(body_entry("body-pi", "caelza-body"));
        config.mcp.servers.push(body_entry("phone", "/usr/local/bin/caelza-body"));
        config.mcp.servers.push(body_entry("body", "caelza-body"));
        assert_eq!(candidate_servers(&config), vec!["body", "body-pi", "phone"]);
        assert!(candidate_servers(&Config::default()).is_empty());
    }

    #[test]
    fn tools_are_classed_and_grouped_like_the_body_does() {
        assert_eq!(tool_class("device_list"), "read-only");
        assert_eq!(tool_class("device_pair"), "destructive");
        assert_eq!(tool_class("sensors_torch"), "neutral");
        assert_eq!(tool_group("device_list"), "device");
        assert_eq!(tool_group("self_read_file"), "selfmod");
        assert_eq!(tool_group("shell_run"), "shell");
        assert_eq!(tool_group("web_search"), "web");
        assert_eq!(tool_group("odd"), "odd");
        for name in READ_ONLY {
            assert!(!DESTRUCTIVE.contains(name), "{name} is in both classes");
        }
    }

    #[test]
    fn text_and_image_blocks_are_read() {
        let result = json!({
            "content": [
                {"type": "text", "text": "screenshot captured"},
                {"type": "image", "data": "iVBORw0KGgo=", "mimeType": "image/png"},
                {"type": "text", "text": "image saved at /tmp/x.png"},
            ],
            "isError": false,
        });
        assert_eq!(text_of(&result), "screenshot captured\nimage saved at /tmp/x.png");
        assert_eq!(
            image_of(&result),
            Some(("image/png".to_string(), "iVBORw0KGgo=".to_string()))
        );
        assert_eq!(image_of(&json!({"content": []})), None);
        assert_eq!(text_of(&json!({})), "");
        assert_eq!(json_or_text("{\"percentage\": 80}")["percentage"], 80);
        assert_eq!(json_or_text("plain words")["text"], "plain words");
    }

    #[test]
    fn device_rows_put_this_phone_first() {
        let listed = json!({
            "pixel": {"host": "10.0.0.5:5555", "last_seen": "2026-10-20T10:00:00+00:00", "reachable": true},
            "self": {"reachable": true},
            "fold": {"host": "10.0.0.9:5555", "last_seen": null, "reachable": false},
        });
        let rows = device_rows(&listed);
        assert_eq!(rows.len(), 3);
        assert_eq!(rows[0]["name"], "self");
        assert_eq!(rows[0]["self"], true);
        assert_eq!(rows[0]["host"], Value::Null);
        assert_eq!(rows[1]["name"], "fold");
        assert_eq!(rows[1]["reachable"], false);
        assert_eq!(rows[2]["name"], "pixel");
        assert_eq!(rows[2]["host"], "10.0.0.5:5555");
        assert!(device_rows(&json!("not a map")).is_empty());
    }

    #[test]
    fn packages_parse_both_pm_formats() {
        let text = "package:com.zeta\npackage:/data/app/~~a==/com.alpha-b==/base.apk=com.alpha\n\nnoise\npackage:";
        let packages = parse_packages(text);
        assert_eq!(packages.len(), 2);
        assert_eq!(packages[0]["name"], "com.alpha");
        assert_eq!(packages[0]["path"], "/data/app/~~a==/com.alpha-b==/base.apk");
        assert_eq!(packages[1]["name"], "com.zeta");
        assert_eq!(packages[1]["path"], Value::Null);
    }

    #[test]
    fn device_defaults_to_self() {
        assert_eq!(device_or_self(None), "self");
        assert_eq!(device_or_self(Some("  ")), "self");
        assert_eq!(device_or_self(Some(" pixel ")), "pixel");
    }
}
