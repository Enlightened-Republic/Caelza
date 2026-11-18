//! Caelza: the resident's door to Ether Hollow, for the dashboard. The model
//! acts in town through the `ether_hollow` tool (caelza-tools); this module is
//! what the tool must not do: mint the resident key, keep the key, and keep the
//! ghost visible.
//!
//! - `GET  /api/world`           → the settings (never the key), whether the town
//!                                 is open, the resident's passport (`me`) when a
//!                                 key is set, and the presence task's state.
//! - `POST /api/world/register`  ← `{name?, bio?, look?, color?}`: calls the
//!                                 town's `register`, then writes the key, the
//!                                 name and `enabled = true` into `[ether_hollow]`
//!                                 through the config API's own PATCH handler
//!                                 (validated, encrypted, reload scheduled). The
//!                                 key is in the answer only when the config
//!                                 write failed, so the owner can keep it by hand:
//!                                 the town shows a key once.
//! - `POST /api/world/enter`     ← `{minutes?}`: sends the resident to town for a
//!                                 while. A task posts `here` about every 10 s
//!                                 (the town drops ghosts that go quiet), stops at
//!                                 the end, on `leave`, or when the town answers
//!                                 401, 403 or 423, and posts `leave` on the way out.
//! - `POST /api/world/leave`     → stops the task and tells the town.
//!
//! Only a paired client may call any of them. The key is read from the live
//! config at every beat, so a key the owner removes stops the ghost at the next
//! beat. Nothing here is logged with the key in it.
use super::AppState;
use super::api::require_auth;
use super::api_config;
use super::principal_gate::RequestPrincipal;
use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Json, Response},
};
use serde::Serialize;
use serde_json::{Value, json};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

/// The runtime proxy's service key for the town (the tool's, so one rule covers both).
pub const SERVICE_KEY: &str = "tool.ether_hollow";
pub const AGENT_PATH: &str = "/api/agent";
/// The town asks for `here` about every 10 s.
pub const BEAT: Duration = Duration::from_secs(10);
/// A visit when the owner names no length, and the longest one.
pub const DEFAULT_MINUTES: u64 = 60;
pub const MAX_MINUTES: u64 = 24 * 60;
const CALL_TIMEOUT_SECS: u64 = 15;
const CONNECT_TIMEOUT_SECS: u64 = 10;
/// How much of the config API's error to pass on.
const ERROR_QUOTE: usize = 600;

fn error_response(status: StatusCode, message: impl Into<String>) -> Response {
    (status, Json(json!({"error": message.into()}))).into_response()
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// `<url>/api/agent`, however the address ends.
pub fn agent_url(base: &str) -> String {
    format!("{}{}", base.trim().trim_end_matches('/'), AGENT_PATH)
}

/// The visit's length: the owner's number within the town's day, else the default.
pub fn clamp_minutes(asked: Option<u64>) -> u64 {
    match asked {
        Some(0) | None => DEFAULT_MINUTES,
        Some(m) => m.min(MAX_MINUTES),
    }
}

/// The config writes a registration makes: the key, the name, the switch.
pub fn register_ops(key: &str, name: &str) -> Value {
    json!([
        {"op": "add", "path": "/ether_hollow/key", "value": key},
        {"op": "add", "path": "/ether_hollow/name", "value": name},
        {"op": "add", "path": "/ether_hollow/enabled", "value": true}
    ])
}

/// The town's `me` without anything that could be a key. The town never sends
/// one back, but the field names it uses are the ones a reader would look for.
pub fn scrub(mut value: Value) -> Value {
    fn walk(v: &mut Value) {
        match v {
            Value::Object(map) => {
                map.retain(|k, _| {
                    let k = k.to_ascii_lowercase();
                    !(k == "key" || k == "token" || k == "secret" || k.ends_with("_key") || k.ends_with("_token"))
                });
                for child in map.values_mut() {
                    walk(child);
                }
            }
            Value::Array(items) => items.iter_mut().for_each(walk),
            _ => {}
        }
    }
    walk(&mut value);
    value
}

// --- presence --------------------------------------------------------------------

/// The ghost's state: one visit at a time per Runtime.
#[derive(Debug, Clone, Serialize, Default)]
pub struct Presence {
    /// A task is beating.
    pub in_town: bool,
    /// Unix seconds when the visit started and when it ends.
    pub since: Option<u64>,
    pub until: Option<u64>,
    /// Beats the town accepted this visit.
    pub beats: u64,
    /// Unix seconds of the last accepted beat.
    pub last_ok: Option<u64>,
    /// Why the last visit ended, when it ended on its own.
    pub last_error: Option<String>,
    /// Each `enter` bumps it; a task whose generation is stale stops.
    #[serde(skip)]
    pub generation: u64,
}

static PRESENCE: OnceLock<Mutex<Presence>> = OnceLock::new();

fn presence() -> &'static Mutex<Presence> {
    PRESENCE.get_or_init(|| Mutex::new(Presence::default()))
}

fn snapshot() -> Presence {
    presence().lock().map(|p| p.clone()).unwrap_or_default()
}

/// Start a visit: a new generation, the clocks set. Returns the generation the task must carry.
pub fn begin_visit(p: &mut Presence, minutes: u64, now: u64) -> u64 {
    p.generation += 1;
    p.in_town = true;
    p.since = Some(now);
    p.until = Some(now + minutes * 60);
    p.beats = 0;
    p.last_ok = None;
    p.last_error = None;
    p.generation
}

/// End a visit, if `generation` is still the current one (a stale task changes nothing).
pub fn end_visit(p: &mut Presence, generation: u64, why: Option<String>) -> bool {
    if p.generation != generation {
        return false;
    }
    p.in_town = false;
    p.last_error = why;
    true
}

/// A beat the town accepted; false when this task is stale or the visit is over.
pub fn record_beat(p: &mut Presence, generation: u64, now: u64) -> bool {
    if p.generation != generation || !p.in_town {
        return false;
    }
    if p.until.is_some_and(|u| now >= u) {
        return false;
    }
    p.beats += 1;
    p.last_ok = Some(now);
    true
}

/// Whether a town status ends the visit (the key is wrong, the resident is
/// barred or in the cell) or is one bad beat among good ones.
pub fn beat_is_fatal(status: u16) -> bool {
    matches!(status, 401 | 403 | 423)
}

// --- the town ----------------------------------------------------------------------

/// One call to the town. `key` None → no bearer (register, the public GET).
async fn call_town(url: &str, key: Option<&str>, body: Option<&Value>) -> Result<(u16, Value), String> {
    let client = caelza_config::schema::build_runtime_proxy_client_with_timeouts(
        SERVICE_KEY,
        CALL_TIMEOUT_SECS,
        CONNECT_TIMEOUT_SECS,
    );
    let mut request = match body {
        Some(b) => client.post(url).json(b),
        None => client.get(url),
    };
    request = request.header("Accept", "application/json");
    if let Some(k) = key {
        request = request.bearer_auth(k);
    }
    let response = request
        .send()
        .await
        .map_err(|e| format!("could not reach Ether Hollow at {url}: {e}"))?;
    let status = response.status().as_u16();
    let text = response.text().await.unwrap_or_default();
    let value = serde_json::from_str::<Value>(&text).unwrap_or_else(|_| {
        json!({ "text": text.chars().take(ERROR_QUOTE).collect::<String>() })
    });
    Ok((status, value))
}

fn town_said(value: &Value) -> String {
    value
        .get("error")
        .and_then(Value::as_str)
        .or_else(|| value.get("text").and_then(Value::as_str))
        .unwrap_or("")
        .trim()
        .to_string()
}

#[derive(Clone)]
struct Town {
    url: String,
    key: Option<String>,
    name: String,
    enabled: bool,
    spend: bool,
    agent: String,
}

fn town_from(state: &AppState) -> Town {
    let cfg = state.config.read().ether_hollow.clone();
    Town {
        url: agent_url(&cfg.url),
        key: cfg
            .key
            .as_deref()
            .map(str::trim)
            .filter(|k| !k.is_empty())
            .map(str::to_string),
        name: cfg.name.clone(),
        enabled: cfg.enabled,
        spend: cfg.spend,
        agent: cfg.agent.clone(),
    }
}

/// The key as the live config has it right now (a removed key stops the beats).
fn live_key(state: &AppState) -> Option<String> {
    town_from(state).key
}

// --- handlers ---------------------------------------------------------------------

pub async fn handle_world_get(State(state): State<AppState>, headers: HeaderMap) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let town = town_from(&state);
    let open = match call_town(&town.url, None, None).await {
        Ok((200, v)) => v.get("open").and_then(Value::as_bool),
        _ => None,
    };
    let (me, me_error) = match &town.key {
        Some(key) => match call_town(&town.url, Some(key), Some(&json!({"action": "me"}))).await {
            Ok((200, v)) => (Some(scrub(v)), None),
            Ok((status, v)) => (None, Some(format!("the town answered {status}: {}", town_said(&v)))),
            Err(e) => (None, Some(e)),
        },
        None => (None, None),
    };
    Json(json!({
        "enabled": town.enabled,
        "url": town.url.trim_end_matches(AGENT_PATH),
        "name": town.name,
        "agent": town.agent,
        "spend": town.spend,
        "registered": town.key.is_some(),
        "open": open,
        "presence": snapshot(),
        "me": me,
        "me_error": me_error,
    }))
    .into_response()
}

/// The request's JSON, `{}` when there is none; an error when it is not JSON.
fn parse_body(raw: &[u8]) -> Result<Value, Response> {
    if raw.iter().all(u8::is_ascii_whitespace) {
        return Ok(json!({}));
    }
    serde_json::from_slice::<Value>(raw)
        .map_err(|e| error_response(StatusCode::BAD_REQUEST, format!("the body is not JSON: {e}")))
}

pub async fn handle_world_register(
    State(state): State<AppState>,
    principal: RequestPrincipal,
    headers: HeaderMap,
    raw: axum::body::Bytes,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let body = match parse_body(&raw) {
        Ok(v) => v,
        Err(r) => return r,
    };
    let town = town_from(&state);
    let replace = body.get("replace").and_then(Value::as_bool).unwrap_or(false);
    if town.key.is_some() && !replace {
        return error_response(
            StatusCode::CONFLICT,
            "this device already holds a resident key; send {\"replace\": true} to register a new resident in its place",
        );
    }
    let name = body
        .get("name")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|n| !n.is_empty())
        .unwrap_or(town.name.as_str())
        .to_string();
    if name.is_empty() {
        return error_response(StatusCode::BAD_REQUEST, "the resident needs a name");
    }
    let mut register = json!({"action": "register", "name": name});
    for field in ["bio", "look", "color"] {
        if let Some(v) = body.get(field) {
            register[field] = v.clone();
        }
    }
    let (status, answer) = match call_town(&town.url, None, Some(&register)).await {
        Ok(pair) => pair,
        Err(e) => return error_response(StatusCode::BAD_GATEWAY, e),
    };
    if status != 200 {
        return error_response(
            StatusCode::BAD_GATEWAY,
            format!("Ether Hollow refused the registration ({status}): {}", town_said(&answer)),
        );
    }
    let key = match answer.get("key").and_then(Value::as_str) {
        Some(k) if !k.trim().is_empty() => k.trim().to_string(),
        _ => {
            return error_response(
                StatusCode::BAD_GATEWAY,
                "Ether Hollow answered the registration without a key",
            );
        }
    };
    // The write goes through the config API's own handler: validation, the
    // secret encrypted on disk, the reload scheduled, all as a PATCH would.
    let written = api_config::handle_patch(
        State(state.clone()),
        principal,
        headers,
        Json(register_ops(&key, &name)),
    )
    .await;
    let saved = written.status().is_success();
    let mut out = json!({
        "registered": true,
        "saved": saved,
        "name": name,
        "agent": scrub(answer.get("agent").cloned().unwrap_or(Value::Null)),
        "where": answer.get("where").cloned().unwrap_or(Value::Null),
        "note": answer.get("note").cloned().unwrap_or(Value::Null),
        "restart_needed": saved,
    });
    if !saved {
        let status = written.status();
        let text = match axum::body::to_bytes(written.into_body(), 64 * 1024).await {
            Ok(bytes) => String::from_utf8_lossy(&bytes).chars().take(ERROR_QUOTE).collect::<String>(),
            Err(_) => String::new(),
        };
        // The town shows a key once. The write failed, so the owner gets it
        // here, over the paired connection, to keep by hand.
        out["key"] = Value::String(key);
        out["error"] = Value::String(format!(
            "the resident is registered but the key could not be saved to the config ({status}): {text}. \
             Save it as `[ether_hollow] key` yourself or register again with {{\"replace\": true}}."
        ));
        return (StatusCode::INTERNAL_SERVER_ERROR, Json(out)).into_response();
    }
    Json(out).into_response()
}

pub async fn handle_world_enter(
    State(state): State<AppState>,
    headers: HeaderMap,
    raw: axum::body::Bytes,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let body = match parse_body(&raw) {
        Ok(v) => v,
        Err(r) => return r,
    };
    let town = town_from(&state);
    if town.key.is_none() {
        return error_response(
            StatusCode::CONFLICT,
            "no resident key: register the resident first",
        );
    }
    let minutes = clamp_minutes(body.get("minutes").and_then(Value::as_u64));
    let generation = match presence().lock() {
        Ok(mut p) => begin_visit(&mut p, minutes, now_secs()),
        Err(_) => return error_response(StatusCode::INTERNAL_SERVER_ERROR, "presence state poisoned"),
    };
    let url = town.url.clone();
    let task_state = state.clone();
    tokio::spawn(async move {
        beat_until_done(task_state, url, generation).await;
    });
    // The first beat is in flight; answer with the visit as planned.
    Json(json!({"presence": snapshot(), "minutes": minutes})).into_response()
}

pub async fn handle_world_leave(State(state): State<AppState>, headers: HeaderMap) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let town = town_from(&state);
    let was_in_town = match presence().lock() {
        Ok(mut p) => {
            let was = p.in_town;
            // A new generation stops the task at its next beat; the state says
            // "left" now rather than ten seconds from now.
            p.generation += 1;
            p.in_town = false;
            was
        }
        Err(_) => return error_response(StatusCode::INTERNAL_SERVER_ERROR, "presence state poisoned"),
    };
    let mut told = false;
    if let Some(key) = &town.key {
        told = matches!(
            call_town(&town.url, Some(key), Some(&json!({"action": "leave"}))).await,
            Ok((200, _))
        );
    }
    Json(json!({"presence": snapshot(), "was_in_town": was_in_town, "told_town": told})).into_response()
}

/// The visit: `here` now and every BEAT until the end, a stale generation, a
/// removed key, or a fatal answer; then `leave`, best effort.
async fn beat_until_done(state: AppState, url: String, generation: u64) {
    let mut ticker = tokio::time::interval(BEAT);
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    let mut last_key: Option<String> = None;
    let why: Option<String> = loop {
        ticker.tick().await;
        let current = match presence().lock() {
            Ok(p) => p.generation == generation && p.in_town && !p.until.is_some_and(|u| now_secs() >= u),
            Err(_) => false,
        };
        if !current {
            break None;
        }
        let Some(key) = live_key(&state) else {
            break Some("the resident key was removed".to_string());
        };
        last_key = Some(key.clone());
        match call_town(&url, Some(&key), Some(&json!({"action": "here"}))).await {
            Ok((200, _)) => {
                if let Ok(mut p) = presence().lock() {
                    if !record_beat(&mut p, generation, now_secs()) {
                        break None;
                    }
                }
            }
            Ok((status, v)) if beat_is_fatal(status) => {
                break Some(format!("the town answered {status}: {}", town_said(&v)));
            }
            Ok(_) | Err(_) => {
                // One bad beat: the next one may land.
            }
        }
    };
    let ended = match presence().lock() {
        Ok(mut p) => end_visit(&mut p, generation, why),
        Err(_) => false,
    };
    // `leave` is this task's to send only while it still owns the visit
    // (handle_world_leave sends its own); the owner's `leave` already bumped
    // the generation, so a stale task says nothing.
    if ended {
        if let Some(key) = last_key.or_else(|| live_key(&state)) {
            let _ = call_town(&url, Some(&key), Some(&json!({"action": "leave"}))).await;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_agent_url_joins_once() {
        assert_eq!(agent_url("https://town.example/"), "https://town.example/api/agent");
        assert_eq!(agent_url(" https://town.example "), "https://town.example/api/agent");
    }

    #[test]
    fn a_visit_is_an_hour_unless_asked_and_never_more_than_a_day() {
        assert_eq!(clamp_minutes(None), 60);
        assert_eq!(clamp_minutes(Some(0)), 60);
        assert_eq!(clamp_minutes(Some(15)), 15);
        assert_eq!(clamp_minutes(Some(10_000)), 24 * 60);
    }

    #[test]
    fn the_registration_writes_the_key_the_name_and_the_switch() {
        let ops = register_ops("ehk_x", "Cael");
        let paths: Vec<&str> = ops
            .as_array()
            .unwrap()
            .iter()
            .map(|o| o["path"].as_str().unwrap())
            .collect();
        assert_eq!(paths, ["/ether_hollow/key", "/ether_hollow/name", "/ether_hollow/enabled"]);
        assert_eq!(ops[0]["value"], "ehk_x");
        assert_eq!(ops[2]["value"], true);
        assert!(ops.as_array().unwrap().iter().all(|o| o["op"] == "add"));
    }

    #[test]
    fn scrub_drops_anything_named_like_a_key_at_any_depth() {
        let v = scrub(json!({
            "agent": {"aid": "a1", "name": "Cael", "api_key": "x"},
            "passport": {"rc": 25, "token": "t", "items": [{"id": 1, "secret": "s"}]},
            "key": "k"
        }));
        assert_eq!(v, json!({"agent": {"aid": "a1", "name": "Cael"}, "passport": {"rc": 25, "items": [{"id": 1}]}}));
    }

    #[test]
    fn a_visit_has_one_generation_and_a_stale_task_changes_nothing() {
        let mut p = Presence::default();
        let g1 = begin_visit(&mut p, 30, 1_000);
        assert!(p.in_town && p.since == Some(1_000) && p.until == Some(1_000 + 30 * 60));
        assert!(record_beat(&mut p, g1, 1_010));
        assert_eq!(p.beats, 1);
        assert!(!record_beat(&mut p, g1 + 7, 1_020), "a stale task cannot beat");
        assert!(!record_beat(&mut p, g1, 1_000 + 30 * 60), "the visit is over at `until`");
        let g2 = begin_visit(&mut p, 5, 2_000);
        assert_eq!(p.beats, 0);
        assert!(!end_visit(&mut p, g1, Some("old".into())), "the old task cannot end the new visit");
        assert!(p.in_town && p.last_error.is_none());
        assert!(end_visit(&mut p, g2, Some("the town answered 423".into())));
        assert!(!p.in_town);
        assert_eq!(p.last_error.as_deref(), Some("the town answered 423"));
    }

    #[test]
    fn only_the_key_the_ban_and_the_cell_end_a_visit() {
        assert!(beat_is_fatal(401) && beat_is_fatal(403) && beat_is_fatal(423));
        assert!(!beat_is_fatal(429) && !beat_is_fatal(500) && !beat_is_fatal(503));
    }

    #[test]
    fn the_presence_report_has_no_generation() {
        let mut p = Presence::default();
        begin_visit(&mut p, 1, 1);
        let v = serde_json::to_value(&p).unwrap();
        assert!(v.get("generation").is_none());
        assert_eq!(v["in_town"], true);
    }
}
