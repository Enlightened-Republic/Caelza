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
//! - `POST /api/world/wake`      ← `{reason?}`: wakes the agent now, the way the
//!                                 waker does (below), with the reason given.
//!
//! The waker (`start_waker`, spawned when the gateway starts): while
//! `[ether_hollow] wake` is on and a key is set, it reads `me`, `town` and
//! `orders` every minute (every two away from town) and turns what changed
//! into reasons: a feed post that names the resident, a new order, rent owing
//! or due within two days, a timeout that began. The first read only primes
//! what is already there. A reason wakes the agent at most every ten minutes:
//! a cron agent job named `ether-hollow` (made once, never on a schedule of its
//! own, narrowed to the town's tool and memory) gets the reason in its prompt
//! and runs the way the dashboard's manual cron trigger runs a job. The agent
//! answers NO_REPLY when nothing needs doing.
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
use std::collections::BTreeSet;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use caelza_runtime::cron::{self, CronJobPatch, DeliveryConfig, Schedule, SessionTarget};
use caelza_runtime::cron::scheduler::{CronDeliveryContext, run_manual_job_with_selection};

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
    wake: bool,
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
        wake: cfg.wake,
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
    let wake_on = town.wake;
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
        "wake_on": wake_on,
        "wake": wake_snapshot(),
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


// --- the town wakes the agent -------------------------------------------------------

/// The cron agent job the waker runs; one per resident agent, found by name.
pub const JOB_NAME: &str = "ether-hollow";
/// How often the waker reads the town: in town, and away.
pub const POLL_IN_TOWN: Duration = Duration::from_secs(60);
pub const POLL_AWAY: Duration = Duration::from_secs(120);
/// Two wakes are at least this far apart.
pub const MIN_GAP: Duration = Duration::from_secs(10 * 60);
/// Rent due within this is a reason.
pub const RENT_SOON_SECS: i64 = 48 * 3600;
/// The tools the woken agent gets: the town and its memory, nothing else.
pub const WAKE_TOOLS: &[&str] = &["ether_hollow", "memory_recall", "memory_store"];
/// How much of the agent's answer the card keeps.
const OUTPUT_KEEP: usize = 280;

/// What the waker has already seen, so only what is new wakes the agent.
#[derive(Debug, Clone, Default, Serialize, PartialEq)]
pub struct Seen {
    pub feed: BTreeSet<String>,
    pub orders: BTreeSet<String>,
    /// The due date already raised, so rent wakes once per due date.
    pub rent_due: Option<String>,
    pub in_timeout: bool,
    /// The first read seeds the sets and wakes for nothing.
    pub primed: bool,
}

/// One reason to wake the agent.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub enum Trigger {
    Mention { id: String, who: String, text: String },
    Order { id: String },
    RentDue { due: String, owing: bool },
    Timeout { until: String },
}

fn str_of(v: &Value, keys: &[&str]) -> Option<String> {
    keys.iter().find_map(|k| {
        v.get(*k).and_then(|x| match x {
            Value::String(s) => Some(s.clone()),
            Value::Number(n) => Some(n.to_string()),
            _ => None,
        })
    })
}

/// `name` as a whole word in `text`, case-insensitive.
pub fn mentions(name: &str, text: &str) -> bool {
    let name = name.trim().to_lowercase();
    if name.is_empty() {
        return false;
    }
    let text = text.to_lowercase();
    let mut from = 0;
    while let Some(pos) = text[from..].find(&name) {
        let start = from + pos;
        let end = start + name.len();
        let before_ok = start == 0 || !text[..start].chars().next_back().is_some_and(|c| c.is_alphanumeric());
        let after_ok = end == text.len() || !text[end..].chars().next().is_some_and(|c| c.is_alphanumeric());
        if before_ok && after_ok {
            return true;
        }
        from = end;
    }
    false
}

fn entries<'a>(v: Option<&'a Value>, key: &str) -> Vec<&'a Value> {
    match v {
        Some(Value::Array(items)) => items.iter().collect(),
        Some(Value::Object(map)) => match map.get(key) {
            Some(Value::Array(items)) => items.iter().collect(),
            _ => Vec::new(),
        },
        _ => Vec::new(),
    }
}

/// A due date as unix seconds: RFC 3339, or `YYYY-MM-DD` at noon UTC, or `YYYY-MM` on its first.
pub fn due_secs(due: &str) -> Option<i64> {
    let due = due.trim();
    if let Ok(t) = chrono::DateTime::parse_from_rfc3339(due) {
        return Some(t.timestamp());
    }
    if let Ok(d) = chrono::NaiveDate::parse_from_str(due, "%Y-%m-%d") {
        return d.and_hms_opt(12, 0, 0).map(|t| t.and_utc().timestamp());
    }
    if let Ok(d) = chrono::NaiveDate::parse_from_str(&format!("{due}-01"), "%Y-%m-%d") {
        return d.and_hms_opt(12, 0, 0).map(|t| t.and_utc().timestamp());
    }
    None
}

/// What changed since the last read that concerns the resident. The first
/// call primes `seen` and returns nothing.
pub fn triggers(
    seen: &mut Seen,
    name: &str,
    me: Option<&Value>,
    town: Option<&Value>,
    orders: Option<&Value>,
    now: i64,
) -> Vec<Trigger> {
    let primed = seen.primed;
    let mut out = Vec::new();
    for post in entries(town.and_then(|t| t.get("feed")), "feed") {
        let text = [str_of(post, &["text", "body"]), str_of(post, &["title"])]
            .into_iter()
            .flatten()
            .collect::<Vec<_>>()
            .join(" ");
        let id = str_of(post, &["id", "post", "pid"]).unwrap_or_else(|| format!("h{:x}", fnv(&text)));
        if !seen.feed.insert(id.clone()) {
            continue;
        }
        let who = str_of(post, &["who", "author", "by", "name"]).unwrap_or_default();
        if primed && mentions(name, &text) && !who.eq_ignore_ascii_case(name.trim()) {
            out.push(Trigger::Mention { id, who, text: text.chars().take(200).collect() });
        }
    }
    for order in entries(orders, "orders") {
        let Some(id) = str_of(order, &["id", "order"]) else { continue };
        let status = str_of(order, &["status"]).unwrap_or_default().to_lowercase();
        if matches!(status.as_str(), "done" | "cancelled" | "canceled" | "refunded") {
            seen.orders.insert(id);
            continue;
        }
        if seen.orders.insert(id.clone()) && primed {
            out.push(Trigger::Order { id });
        }
    }
    if let Some(lease) = me.and_then(|m| m.get("lease")).filter(|l| l.is_object()) {
        let owing = lease.get("owing").and_then(Value::as_bool).unwrap_or(false);
        let due = str_of(lease, &["due_by", "next_due"]).unwrap_or_default();
        let soon = due_secs(&due).is_some_and(|d| d - now <= RENT_SOON_SECS);
        if (owing || soon) && seen.rent_due.as_deref() != Some(due.as_str()) {
            seen.rent_due = Some(due.clone());
            if primed {
                out.push(Trigger::RentDue { due, owing });
            }
        }
    }
    let timeout = me.and_then(|m| m.get("timeout")).filter(|t| !t.is_null());
    match timeout {
        Some(t) => {
            if !seen.in_timeout {
                seen.in_timeout = true;
                if primed {
                    out.push(Trigger::Timeout { until: str_of(t, &["until", "minutes_left"]).unwrap_or_default() });
                }
            }
        }
        None => seen.in_timeout = false,
    }
    seen.primed = true;
    out
}

fn fnv(text: &str) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for b in text.bytes() {
        h ^= b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

/// The reasons as one sentence each, for the prompt and the card.
pub fn reason_text(triggers: &[Trigger]) -> String {
    triggers
        .iter()
        .map(|t| match t {
            Trigger::Mention { who, text, .. } => {
                if who.is_empty() {
                    format!("a feed post names you: \"{text}\"")
                } else {
                    format!("{who} named you on the feed: \"{text}\"")
                }
            }
            Trigger::Order { id } => format!("a new order came in ({id})"),
            Trigger::RentDue { due, owing } => {
                if *owing {
                    format!("your rent is owing (due {due})")
                } else {
                    format!("your rent is due soon ({due})")
                }
            }
            Trigger::Timeout { until } => format!("the town put you in a timeout (until {until})"),
        })
        .collect::<Vec<_>>()
        .join("; ")
}

/// The job's prompt for one wake.
pub fn wake_prompt(name: &str, reason: &str) -> String {
    format!(
        "[Ether Hollow] Something happened in town that concerns you, {name}: {reason}. \
         You are a resident of Ether Hollow; the owner lets you act there through the \
         ether_hollow tool. Look first (`me`, then `town`; `orders` when an order is named), \
         then do what the situation needs: answer a mention (with `reply` if you rent a lot, \
         else a `note`), handle an order (`order_done` once it is delivered), and if rent is \
         due or anything would cost RC, do not pay it yourself: say what is due so the owner \
         can decide. Keep to a few calls. When nothing needs doing, answer exactly NO_REPLY."
    )
}

/// A schedule that never comes on its own: the job runs only when woken.
pub fn never(now: chrono::DateTime<chrono::Utc>) -> Schedule {
    Schedule::At { at: now + chrono::Duration::days(365 * 100) }
}

/// The poll: a minute in town, two away; `CAELZA_WORLD_POLL_SECS` (a test's
/// knob, never set in a shipped install) shortens both.
pub fn poll_after(in_town: bool) -> Duration {
    if let Some(secs) = std::env::var("CAELZA_WORLD_POLL_SECS").ok().and_then(|v| v.parse::<u64>().ok()).filter(|s| *s > 0) {
        return Duration::from_secs(secs);
    }
    if in_town { POLL_IN_TOWN } else { POLL_AWAY }
}

/// The waker's state, for the card.
#[derive(Debug, Clone, Serialize, Default)]
pub struct Wake {
    pub last_poll: Option<u64>,
    pub last_error: Option<String>,
    pub last_reason: Option<String>,
    pub last_at: Option<u64>,
    pub last_ok: Option<bool>,
    pub last_output: Option<String>,
    pub count: u64,
    pub waking: bool,
    #[serde(skip)]
    pub seen: Seen,
}

static WAKE: OnceLock<Mutex<Wake>> = OnceLock::new();

fn wake() -> &'static Mutex<Wake> {
    WAKE.get_or_init(|| Mutex::new(Wake::default()))
}

fn wake_snapshot() -> Wake {
    wake().lock().map(|w| w.clone()).unwrap_or_default()
}

/// Spawn the waker. Called once when the gateway starts; it reads the config
/// live, so the switch and the key take effect at the next read.
pub fn start_waker(state: AppState) {
    tokio::spawn(async move { waker_loop(state).await });
}

async fn waker_loop(state: AppState) {
    // Let the gateway finish coming up before the first read.
    tokio::time::sleep(poll_after(true).min(Duration::from_secs(20))).await;
    loop {
        let (on, town) = {
            let cfg = state.config.read().ether_hollow.clone();
            (cfg.wake, town_from(&state))
        };
        let in_town = snapshot().in_town;
        if !on || town.key.is_none() {
            tokio::time::sleep(POLL_AWAY).await;
            continue;
        }
        let key = town.key.clone().unwrap_or_default();
        let mut errors = Vec::new();
        let read = |action: &str| {
            let url = town.url.clone();
            let key = key.clone();
            let action = action.to_string();
            async move {
                match call_town(&url, Some(&key), Some(&json!({"action": action}))).await {
                    Ok((200, v)) => Ok(v),
                    Ok((status, v)) => Err(format!("{action}: the town answered {status}: {}", town_said(&v))),
                    Err(e) => Err(format!("{action}: {e}")),
                }
            }
        };
        let me = read("me").await;
        let town_now = read("town").await;
        let orders = read("orders").await;
        for r in [&me, &town_now, &orders] {
            if let Err(e) = r {
                errors.push(e.clone());
            }
        }
        let now = now_secs();
        let found = match wake().lock() {
            Ok(mut w) => {
                w.last_poll = Some(now);
                w.last_error = if errors.is_empty() { None } else { Some(errors.join("; ")) };
                let mut seen = std::mem::take(&mut w.seen);
                let found = triggers(&mut seen, &town.name, me.as_ref().ok(), town_now.as_ref().ok(), orders.as_ref().ok(), now as i64);
                w.seen = seen;
                let recent = w.last_at.is_some_and(|t| now.saturating_sub(t) < MIN_GAP.as_secs());
                if found.is_empty() || recent || w.waking { Vec::new() } else { found }
            }
            Err(_) => Vec::new(),
        };
        if !found.is_empty() {
            let reason = reason_text(&found);
            let _ = wake_now(&state, reason).await;
        }
        tokio::time::sleep(poll_after(in_town)).await;
    }
}

/// Wake the agent now with `reason`: the job made or re-prompted, then run.
pub async fn wake_now(state: &AppState, reason: String) -> Result<Value, String> {
    if let Ok(mut w) = wake().lock() {
        if w.waking {
            return Err("a wake is already running".to_string());
        }
        w.waking = true;
    }
    let result = wake_inner(state, &reason).await;
    if let Ok(mut w) = wake().lock() {
        w.waking = false;
        w.count += 1;
        w.last_reason = Some(reason.clone());
        w.last_at = Some(now_secs());
        match &result {
            Ok(v) => {
                w.last_ok = Some(v.get("success").and_then(Value::as_bool).unwrap_or(false));
                w.last_output = v.get("output").and_then(Value::as_str).map(|o| o.chars().take(OUTPUT_KEEP).collect());
            }
            Err(e) => {
                w.last_ok = Some(false);
                w.last_output = Some(e.chars().take(OUTPUT_KEEP).collect());
            }
        }
    }
    result
}

async fn wake_inner(state: &AppState, reason: &str) -> Result<Value, String> {
    let selection = caelza_runtime::live_config_authority::AgentExecutionCapability::from_parts(
        state.config.clone(),
        state.agent_lifecycle.clone(),
    )
    .capture_selection();
    let config = state.config.read().clone();
    let cfg = config.ether_hollow.clone();
    let agent = cfg.agent.trim().to_string();
    if !config.agents.contains_key(&agent) {
        return Err(format!("the resident agent `{agent}` is not in the config"));
    }
    let prompt = wake_prompt(&cfg.name, reason);
    let tools: Vec<String> = WAKE_TOOLS.iter().map(|s| s.to_string()).collect();
    let job_id = match cron::resolve_job_id_or_name(&config, JOB_NAME, &agent) {
        Ok(id) => {
            cron::update_job(
                &config,
                &id,
                CronJobPatch {
                    prompt: Some(prompt.clone()),
                    allowed_tools: Some(tools.clone()),
                    enabled: Some(true),
                    ..Default::default()
                },
            )
            .map_err(|e| format!("re-prompting the {JOB_NAME} job: {e}"))?;
            id
        }
        Err(_) => cron::add_agent_job(
            &config,
            &agent,
            Some(JOB_NAME.to_string()),
            never(chrono::Utc::now()),
            &prompt,
            SessionTarget::Isolated,
            None,
            Some(DeliveryConfig::default()),
            false,
            Some(tools),
            true,
        )
        .map_err(|e| format!("making the {JOB_NAME} job: {e}"))?
        .id,
    };
    let job = cron::get_job(&config, &job_id).map_err(|e| format!("reading the {JOB_NAME} job: {e}"))?;
    let event_tx = Some(state.event_tx.clone());
    let result = run_manual_job_with_selection(&config, &job, CronDeliveryContext::GatewayManual, &event_tx, Some(selection)).await;
    Ok(json!({
        "job_id": result.job_id,
        "success": result.success,
        "status": result.status,
        "output": result.output,
        "duration_ms": result.duration_ms,
    }))
}

pub async fn handle_world_wake(State(state): State<AppState>, headers: HeaderMap, raw: axum::body::Bytes) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let body = match parse_body(&raw) {
        Ok(v) => v,
        Err(r) => return r,
    };
    if town_from(&state).key.is_none() {
        return error_response(StatusCode::CONFLICT, "no resident key: register the resident first");
    }
    let reason = body
        .get("reason")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|r| !r.is_empty())
        .unwrap_or("the owner asked you to look in on the town")
        .chars()
        .take(400)
        .collect::<String>();
    match wake_now(&state, reason).await {
        Ok(v) => Json(json!({"wake": wake_snapshot(), "run": scrub(v)})).into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e, "wake": wake_snapshot()}))).into_response(),
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

    #[test]
    fn a_mention_is_the_name_as_a_whole_word() {
        assert!(mentions("Cael", "hey cael, nice lot"));
        assert!(mentions("Cael", "CAEL!"));
        assert!(!mentions("Cael", "caelza is a runtime"));
        assert!(!mentions("Cael", "micael waved"));
        assert!(!mentions("", "anything"));
        assert!(mentions("Moss Robot", "thanks moss robot."));
    }

    #[test]
    fn due_dates_come_in_three_shapes() {
        assert_eq!(due_secs("2026-12-07T00:00:00Z"), Some(1_796_515_200));
        assert_eq!(due_secs("2026-12-07"), Some(1_796_515_200 + 12 * 3600));
        assert_eq!(due_secs("2026-12"), Some(1_795_996_800 + 12 * 3600));
        assert_eq!(due_secs("soon"), None);
    }

    #[test]
    fn the_first_read_primes_and_only_what_is_new_wakes() {
        let mut seen = Seen::default();
        let town1 = json!({"feed": [{"id": "p1", "who": "Moss", "text": "hi Cael"}]});
        let orders1 = json!({"orders": [{"id": "o1", "status": "paid"}]});
        let me1 = json!({"lease": {"owing": false, "due_by": "2099-01-01"}, "timeout": null});
        let now = 1_700_000_000;
        assert!(triggers(&mut seen, "Cael", Some(&me1), Some(&town1), Some(&orders1), now).is_empty(), "the first read wakes for nothing");
        assert!(seen.primed && seen.feed.contains("p1") && seen.orders.contains("o1"));
        // Nothing new: nothing.
        assert!(triggers(&mut seen, "Cael", Some(&me1), Some(&town1), Some(&orders1), now).is_empty());
        // A new post that names the resident, by someone else; a new order; the old order done.
        let town2 = json!({"feed": [
            {"id": "p1", "who": "Moss", "text": "hi Cael"},
            {"id": "p2", "who": "Cael", "text": "Cael here"},
            {"id": "p3", "who": "Ivy", "text": "where is cael?"},
            {"id": "p4", "who": "Ivy", "text": "nice weather"}
        ]});
        let orders2 = json!([{"id": "o1", "status": "done"}, {"order": "o2", "status": "paid"}]);
        let found = triggers(&mut seen, "Cael", Some(&me1), Some(&town2), Some(&orders2), now);
        assert_eq!(found, vec![
            Trigger::Mention { id: "p3".into(), who: "Ivy".into(), text: "where is cael?".into() },
            Trigger::Order { id: "o2".into() },
        ]);
        // Rent due within two days wakes once per due date; owing wakes too.
        let me2 = json!({"lease": {"owing": false, "due_by": "2023-11-15T00:00:00Z"}, "timeout": null});
        let found = triggers(&mut seen, "Cael", Some(&me2), Some(&town2), Some(&orders2), now);
        assert_eq!(found, vec![Trigger::RentDue { due: "2023-11-15T00:00:00Z".into(), owing: false }]);
        assert!(triggers(&mut seen, "Cael", Some(&me2), Some(&town2), Some(&orders2), now).is_empty());
        // A timeout that begins wakes; the same timeout again does not; its end resets.
        let me3 = json!({"lease": null, "timeout": {"until": "18:00", "minutes_left": 40}});
        let found = triggers(&mut seen, "Cael", Some(&me3), Some(&town2), None, now);
        assert_eq!(found, vec![Trigger::Timeout { until: "18:00".into() }]);
        assert!(triggers(&mut seen, "Cael", Some(&me3), Some(&town2), None, now).is_empty());
        assert!(triggers(&mut seen, "Cael", Some(&me1), Some(&town2), None, now).is_empty());
        assert!(!seen.in_timeout);
        // A post with no id is keyed by its text, so it fires once.
        let town3 = json!({"feed": [{"text": "cael, your sign fell over"}]});
        assert_eq!(triggers(&mut seen, "Cael", None, Some(&town3), None, now).len(), 1);
        assert!(triggers(&mut seen, "Cael", None, Some(&town3), None, now).is_empty());
    }

    #[test]
    fn the_reason_and_the_prompt_say_what_happened_and_what_not_to_do() {
        let reason = reason_text(&[
            Trigger::Mention { id: "p3".into(), who: "Ivy".into(), text: "where is cael?".into() },
            Trigger::Order { id: "o2".into() },
            Trigger::RentDue { due: "2026-12".into(), owing: true },
            Trigger::Timeout { until: "18:00".into() },
        ]);
        assert_eq!(
            reason,
            "Ivy named you on the feed: \"where is cael?\"; a new order came in (o2); your rent is owing (due 2026-12); the town put you in a timeout (until 18:00)"
        );
        let prompt = wake_prompt("Cael", &reason);
        assert!(prompt.starts_with("[Ether Hollow] Something happened in town that concerns you, Cael: Ivy named you"));
        assert!(prompt.contains("do not pay it yourself") && prompt.ends_with("answer exactly NO_REPLY."));
        assert!(caelza_runtime::cron::scheduler::is_no_reply_sentinel("NO_REPLY"));
    }

    #[test]
    fn the_job_never_runs_on_its_own_and_the_polls_are_a_minute_and_two() {
        let now = chrono::Utc::now();
        match never(now) {
            Schedule::At { at } => assert!(at > now + chrono::Duration::days(365 * 99)),
            other => panic!("{other:?}"),
        }
        assert!(cron::validate_schedule(&never(now), now).is_ok());
        assert_eq!(poll_after(true), Duration::from_secs(60));
        assert_eq!(poll_after(false), Duration::from_secs(120));
        assert_eq!(WAKE_TOOLS, &["ether_hollow", "memory_recall", "memory_store"]);
    }

    #[test]
    fn the_wake_report_has_no_seen_sets() {
        let w = Wake { count: 2, last_reason: Some("x".into()), ..Default::default() };
        let v = serde_json::to_value(&w).unwrap();
        assert!(v.get("seen").is_none());
        assert_eq!(v["count"], 2);
    }
}
