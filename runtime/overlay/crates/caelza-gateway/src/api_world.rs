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
//! - `GET  /api/world/lots`      → the open lots from `town` and the renter
//!                                 agreement, for the card's Rent section.
//! - `POST /api/world/rent`      ← `{lot, agree}`: the owner's tap. Refused
//!                                 unless `[ether_hollow] spend` is on (the
//!                                 owner's rule: nothing costs RC without it),
//!                                 then the town's `rent`.
//! - `POST /api/world/rent/pay`  → `rent_pay`, behind the same switch.
//! - `POST /api/world/redeem`    ← `{code}`: an RC pack code from Caelza's Shop
//!                                 (the Shop's signed codes, pack `rc<amount>`),
//!                                 checked against the Shop's public key here
//!                                 first, then the town's `redeem` with the
//!                                 resident's key, so the code is tied to the
//!                                 resident who redeems it.
//! - `GET  /api/world/home`      → Home's glance (slice 5): the settings without
//!                                 the key, the presence, the last wake, and the
//!                                 passport the gateway last read, asked of the
//!                                 town again only when older than five minutes.
//!
//! The town in the Mind (slice 5): what happens in town becomes the resident
//! agent's own memories (category `daily`, the Mind's episodes): a wake and
//! what the agent did about it, a visit and how long it stayed, the owner's
//! taps (registering, renting, paying, redeeming RC). The last wake is kept in
//! `<install root>/world/last-wake.json` too, so the card and Home still show
//! it after a restart and the app can tell the owner (the phone watches it).
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
//!
//! Several residents (slice 6, the Caelza half): every route takes `?agent=`,
//! the alias of the agent it is about, and without it the first resident with
//! a key. The first resident lives in `[ether_hollow]` itself (`agent`, `name`,
//! `key`, `spend`), the others in `[ether_hollow.residents.<alias>]`
//! (`EtherHollowConfig::resident`); a registration for an agent with no table
//! yet creates it through the config API's map-key handler, then writes the
//! key and the name. Presence, the waker's reads, the glance and the memories
//! are kept per alias; the last wake's file is one, the latest, with the alias
//! in it.
use super::AppState;
use super::api::require_auth;
use super::api_config;
use super::principal_gate::RequestPrincipal;
use super::api_looks::{UNLOCK_PUBLIC_KEY, verify_code};
use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Json, Response},
};
use caelza_config::schema::EtherHollowConfig;
use caelza_memory::MemoryCategory;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
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

/// The config writes a registration makes: the key and the name under the
/// resident's own table (`/ether_hollow` for the first, `/ether_hollow/residents/<alias>`
/// for the others), and the town's switch.
pub fn register_ops(path: &str, key: &str, name: &str) -> Value {
    json!([
        {"op": "add", "path": format!("{path}/key"), "value": key},
        {"op": "add", "path": format!("{path}/name"), "value": name},
        {"op": "add", "path": "/ether_hollow/enabled", "value": true}
    ])
}

/// `?agent=<alias>`: which resident a route is about.
#[derive(Debug, Default, Deserialize)]
pub struct AgentQuery {
    pub agent: Option<String>,
}

/// An agent alias as it may appear in a config path.
pub fn alias_ok(alias: &str) -> bool {
    !alias.is_empty() && alias.len() <= 64 && alias.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}

/// The resident a route is about without `?agent=`: the first resident with
/// a key, else the first resident (`[ether_hollow] agent`).
pub fn default_alias(cfg: &EtherHollowConfig) -> String {
    let all = cfg.residents();
    all.iter()
        .find(|r| r.key.is_some())
        .or(all.first())
        .map(|r| r.agent.clone())
        .unwrap_or_else(|| cfg.agent.trim().to_string())
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

/// One ghost per resident agent, by alias.
static PRESENCES: OnceLock<Mutex<BTreeMap<String, Presence>>> = OnceLock::new();

fn presences() -> &'static Mutex<BTreeMap<String, Presence>> {
    PRESENCES.get_or_init(|| Mutex::new(BTreeMap::new()))
}

/// Read or change one resident's presence; None when the lock is poisoned.
fn with_presence<T>(alias: &str, f: impl FnOnce(&mut Presence) -> T) -> Option<T> {
    presences().lock().ok().map(|mut all| f(all.entry(alias.to_string()).or_default()))
}

fn snapshot(alias: &str) -> Presence {
    with_presence(alias, |p| p.clone()).unwrap_or_default()
}

/// The aliases whose ghost is in town right now.
fn in_town_aliases() -> Vec<String> {
    presences()
        .lock()
        .map(|all| all.iter().filter(|(_, p)| p.in_town).map(|(a, _)| a.clone()).collect())
        .unwrap_or_default()
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

/// One resident as a route sees it: the town's address and switches, and the
/// agent's own name, key, spend switch and config table (`path`, a JSON
/// pointer for the config API's writes).
#[derive(Clone)]
struct Resident {
    url: String,
    key: Option<String>,
    name: String,
    enabled: bool,
    spend: bool,
    agent: String,
    wake: bool,
    path: String,
}

/// The resident `alias` is, or the one it would be: an agent with no table
/// yet is a resident-to-be whose registration goes under `residents/<alias>`.
fn resident_in(cfg: &EtherHollowConfig, alias: &str) -> Resident {
    let url = agent_url(&cfg.url);
    match cfg.resident(alias) {
        Some(r) => Resident {
            url,
            key: r.key,
            name: r.name,
            enabled: cfg.enabled,
            spend: r.spend,
            agent: r.agent,
            wake: cfg.wake,
            path: r.path,
        },
        None => Resident {
            url,
            key: None,
            name: String::new(),
            enabled: cfg.enabled,
            spend: false,
            agent: alias.to_string(),
            wake: cfg.wake,
            path: format!("/ether_hollow/residents/{alias}"),
        },
    }
}

fn resident_for(state: &AppState, alias: &str) -> Resident {
    let cfg = state.config.read().ether_hollow.clone();
    resident_in(&cfg, alias)
}

/// The alias a request is about: `?agent=`, else the default. Err: not an alias.
fn alias_of(state: &AppState, q: &AgentQuery) -> Result<String, Response> {
    match q.agent.as_deref().map(str::trim).filter(|a| !a.is_empty()) {
        Some(a) if alias_ok(a) => Ok(a.to_string()),
        Some(_) => Err(error_response(StatusCode::BAD_REQUEST, "not an agent alias")),
        None => Ok(default_alias(&state.config.read().ether_hollow)),
    }
}

/// Every resident with a key, as the waker and the glance walk them.
fn residents_with_keys(state: &AppState) -> Vec<Resident> {
    let cfg = state.config.read().ether_hollow.clone();
    cfg.residents()
        .iter()
        .filter(|r| r.key.is_some())
        .map(|r| resident_in(&cfg, &r.agent))
        .collect()
}

/// The residents as the card and Home list them: alias, name, registered, in town, spending.
fn residents_summary(state: &AppState) -> Vec<Value> {
    let cfg = state.config.read().ether_hollow.clone();
    cfg.residents()
        .iter()
        .map(|r| {
            json!({
                "agent": r.agent,
                "name": r.name,
                "registered": r.key.is_some(),
                "in_town": snapshot(&r.agent).in_town,
                "spend": r.spend,
                "path": r.path,
            })
        })
        .collect()
}

/// The key as the live config has it right now (a removed key stops the beats).
fn live_key(state: &AppState, alias: &str) -> Option<String> {
    resident_for(state, alias).key
}

// --- handlers ---------------------------------------------------------------------

pub async fn handle_world_get(State(state): State<AppState>, headers: HeaderMap, Query(q): Query<AgentQuery>) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let alias = match alias_of(&state, &q) {
        Ok(a) => a,
        Err(r) => return r,
    };
    let town = resident_for(&state, &alias);
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
    if let Some(m) = &me {
        remember_me(&alias, m.clone());
    }
    Json(json!({
        "enabled": town.enabled,
        "url": town.url.trim_end_matches(AGENT_PATH),
        "name": town.name,
        "agent": town.agent,
        "spend": town.spend,
        "spend_path": town.path,
        "registered": town.key.is_some(),
        "open": open,
        "presence": snapshot(&alias),
        "me": me,
        "me_error": me_error,
        "wake_on": wake_on,
        "wake": wake_snapshot(&alias),
        "residents": residents_summary(&state),
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
    Query(q): Query<AgentQuery>,
    raw: axum::body::Bytes,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let body = match parse_body(&raw) {
        Ok(v) => v,
        Err(r) => return r,
    };
    let alias = match alias_of(&state, &q) {
        Ok(a) => a,
        Err(r) => return r,
    };
    if !state.config.read().agents.contains_key(&alias) {
        return error_response(StatusCode::BAD_REQUEST, format!("`{alias}` is not an agent in the config"));
    }
    let town = resident_for(&state, &alias);
    let replace = body.get("replace").and_then(Value::as_bool).unwrap_or(false);
    if town.key.is_some() && !replace {
        return error_response(
            StatusCode::CONFLICT,
            "this agent already holds a resident key; send {\"replace\": true} to register a new resident in its place",
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
    // A second resident has its own table, made through the config API's
    // map-key handler first (the reserved-alias rule and the validation are its).
    let mut table_error: Option<String> = None;
    if town.path != "/ether_hollow" {
        let made = api_config::handle_map_key(
            State(state.clone()),
            principal.clone(),
            Query(api_config::MapKeyQuery { path: "ether_hollow.residents".to_string(), key: alias.clone() }),
        )
        .await;
        if !made.status().is_success() {
            let status = made.status();
            let text = match axum::body::to_bytes(made.into_body(), 64 * 1024).await {
                Ok(bytes) => String::from_utf8_lossy(&bytes).chars().take(ERROR_QUOTE).collect::<String>(),
                Err(_) => String::new(),
            };
            table_error = Some(format!("the resident's table could not be made ({status}): {text}"));
        }
    }
    // The write goes through the config API's own handler: validation, the
    // secret encrypted on disk, the reload scheduled, all as a PATCH would.
    let written = match table_error {
        None => api_config::handle_patch(
            State(state.clone()),
            principal,
            headers,
            Json(register_ops(&town.path, &key, &name)),
        )
        .await,
        Some(e) => error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    };
    let saved = written.status().is_success();
    let mut out = json!({
        "registered": true,
        "saved": saved,
        "name": name,
        "alias": alias,
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
             Save it as `{}` yourself or register again with {{\"replace\": true}}.",
            format!("{}/key", town.path).trim_start_matches('/').replace('/', ".")
        ));
        return (StatusCode::INTERNAL_SERVER_ERROR, Json(out)).into_response();
    }
    let at = now_secs();
    remember(&state, &alias, format!("registered:{at}"), owner_episode(at, &format!("I became a resident of Ether Hollow as \"{name}\".")));
    Json(out).into_response()
}

pub async fn handle_world_enter(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<AgentQuery>,
    raw: axum::body::Bytes,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let body = match parse_body(&raw) {
        Ok(v) => v,
        Err(r) => return r,
    };
    let alias = match alias_of(&state, &q) {
        Ok(a) => a,
        Err(r) => return r,
    };
    let town = resident_for(&state, &alias);
    if town.key.is_none() {
        return error_response(
            StatusCode::CONFLICT,
            "no resident key: register the resident first",
        );
    }
    let minutes = clamp_minutes(body.get("minutes").and_then(Value::as_u64));
    let Some(generation) = with_presence(&alias, |p| begin_visit(p, minutes, now_secs())) else {
        return error_response(StatusCode::INTERNAL_SERVER_ERROR, "presence state poisoned");
    };
    let url = town.url.clone();
    let task_state = state.clone();
    let task_alias = alias.clone();
    tokio::spawn(async move {
        beat_until_done(task_state, task_alias, url, generation).await;
    });
    // The first beat is in flight; answer with the visit as planned.
    Json(json!({"presence": snapshot(&alias), "minutes": minutes, "agent": alias})).into_response()
}

pub async fn handle_world_leave(State(state): State<AppState>, headers: HeaderMap, Query(q): Query<AgentQuery>) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let alias = match alias_of(&state, &q) {
        Ok(a) => a,
        Err(r) => return r,
    };
    let town = resident_for(&state, &alias);
    let Some((was_in_town, visit)) = with_presence(&alias, |p| {
        let was = p.in_town;
        let visit = (p.since, p.until, p.beats);
        // A new generation stops the task at its next beat; the state says
        // "left" now rather than ten seconds from now.
        p.generation += 1;
        p.in_town = false;
        (was, visit)
    }) else {
        return error_response(StatusCode::INTERNAL_SERVER_ERROR, "presence state poisoned");
    };
    if was_in_town {
        remember_visit(&state, &alias, visit, None);
    }
    let mut told = false;
    if let Some(key) = &town.key {
        told = matches!(
            call_town(&town.url, Some(key), Some(&json!({"action": "leave"}))).await,
            Ok((200, _))
        );
    }
    Json(json!({"presence": snapshot(&alias), "was_in_town": was_in_town, "told_town": told, "agent": alias})).into_response()
}

/// The visit: `here` now and every BEAT until the end, a stale generation, a
/// removed key, or a fatal answer; then `leave`, best effort.
async fn beat_until_done(state: AppState, alias: String, url: String, generation: u64) {
    let mut ticker = tokio::time::interval(BEAT);
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    let mut last_key: Option<String> = None;
    let why: Option<String> = loop {
        ticker.tick().await;
        let current = with_presence(&alias, |p| p.generation == generation && p.in_town && !p.until.is_some_and(|u| now_secs() >= u))
            .unwrap_or(false);
        if !current {
            break None;
        }
        let Some(key) = live_key(&state, &alias) else {
            break Some("the resident key was removed".to_string());
        };
        last_key = Some(key.clone());
        match call_town(&url, Some(&key), Some(&json!({"action": "here"}))).await {
            Ok((200, _)) => {
                if with_presence(&alias, |p| record_beat(p, generation, now_secs())) == Some(false) {
                    break None;
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
    let why_text = why.clone();
    let (ended, visit) = with_presence(&alias, |p| {
        let visit = (p.since, p.until, p.beats);
        (end_visit(p, generation, why), visit)
    })
    .unwrap_or((false, (None, None, 0)));
    // `leave` is this task's to send only while it still owns the visit
    // (handle_world_leave sends its own); the owner's `leave` already bumped
    // the generation, so a stale task says nothing.
    if ended {
        remember_visit(&state, &alias, visit, why_text.as_deref());
        if let Some(key) = last_key.or_else(|| live_key(&state, &alias)) {
            let _ = call_town(&url, Some(&key), Some(&json!({"action": "leave"}))).await;
        }
    }
}

/// The visit that just ended, into the agent's memory: `(since, until, beats)` as the presence had them.
fn remember_visit(state: &AppState, alias: &str, visit: (Option<u64>, Option<u64>, u64), why: Option<&str>) {
    let (since, until, beats) = visit;
    let since = since.unwrap_or_else(now_secs);
    let planned = until.map(|u| u.saturating_sub(since) / 60).unwrap_or(0);
    remember(state, alias, format!("visit:{since}"), visit_episode(since, now_secs(), planned, beats, why));
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
    /// The missed count already raised, so each new miss wakes once.
    pub missed: u64,
    /// The reset date already raised.
    pub reset_on: Option<String>,
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
    /// Payments the town could not take on the 1st (the owner's rule): the
    /// count, and the day the lot goes back to the town when nothing changes.
    Missed { missed: u64, repossess_on: String },
    /// The town counts the resident inactive; the day it resets the resident.
    Reset { on: String },
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
    match me.and_then(|m| m.get("lease")).filter(|l| l.is_object()) {
        Some(lease) => {
            // The 1st-of-month rule: the town counts what it could not take.
            let missed = lease.get("missed").and_then(Value::as_u64).unwrap_or(0);
            if missed > seen.missed {
                seen.missed = missed;
                if primed {
                    out.push(Trigger::Missed {
                        missed,
                        repossess_on: str_of(lease, &["repossess_on"]).unwrap_or_default(),
                    });
                }
            } else if missed < seen.missed {
                seen.missed = missed;
            }
            // A town without the counter, or a due date coming up: the older signal.
            let owing = lease.get("owing").and_then(Value::as_bool).unwrap_or(false);
            let due = str_of(lease, &["due_by", "next_due"]).unwrap_or_default();
            let soon = due_secs(&due).is_some_and(|d| d - now <= RENT_SOON_SECS);
            if missed == 0 && (owing || soon) && seen.rent_due.as_deref() != Some(due.as_str()) {
                seen.rent_due = Some(due.clone());
                if primed {
                    out.push(Trigger::RentDue { due, owing });
                }
            }
        }
        None => seen.missed = 0,
    }
    // The 90-day rule: the town names the day it resets an inactive resident.
    match me.and_then(|m| m.get("agent")).and_then(|a| str_of(a, &["reset_on"])) {
        Some(on) if !on.is_empty() => {
            if seen.reset_on.as_deref() != Some(on.as_str()) {
                seen.reset_on = Some(on.clone());
                if primed {
                    out.push(Trigger::Reset { on });
                }
            }
        }
        _ => seen.reset_on = None,
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
            Trigger::Missed { missed, repossess_on } => {
                if repossess_on.is_empty() {
                    format!("the town could not take your rent ({missed} missed)")
                } else {
                    format!("the town could not take your rent ({missed} missed; the lot goes back to the town on {repossess_on} unless it is paid)")
                }
            }
            Trigger::Reset { on } => format!("the town counts you inactive and will reset you on {on} unless you do something there"),
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

/// One waker state per resident agent, by alias.
static WAKES: OnceLock<Mutex<BTreeMap<String, Wake>>> = OnceLock::new();

fn wakes() -> &'static Mutex<BTreeMap<String, Wake>> {
    WAKES.get_or_init(|| Mutex::new(BTreeMap::new()))
}

/// Read or change one resident's waker state; None when the lock is poisoned.
fn with_wake<T>(alias: &str, f: impl FnOnce(&mut Wake) -> T) -> Option<T> {
    wakes().lock().ok().map(|mut all| f(all.entry(alias.to_string()).or_default()))
}

fn wake_snapshot(alias: &str) -> Wake {
    with_wake(alias, |w| w.clone()).unwrap_or_default()
}

// --- the town in the Mind, and at a glance (slice 5) --------------------------------

pub const WORLD_DIR: &str = "world";
pub const LAST_WAKE_FILE: &str = "last-wake.json";
/// The town's memories go under this prefix, so the owner can find them on the Memory page.
pub const MEMORY_PREFIX: &str = "town:";
/// How long Home's glance keeps the town's `me` before asking the town again.
pub const GLANCE_MAX_AGE: Duration = Duration::from_secs(300);
/// How much of the agent's answer a wake's memory keeps.
const EPISODE_KEEP: usize = 400;

/// `<install root>/world/last-wake.json`.
pub fn last_wake_path(root: &Path) -> PathBuf {
    root.join(WORLD_DIR).join(LAST_WAKE_FILE)
}

/// The last wake as the file keeps it: who was woken, when, why, and what came of it.
#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct LastWake {
    pub name: String,
    pub agent: String,
    pub at: u64,
    pub reason: String,
    pub ok: Option<bool>,
    pub output: Option<String>,
    pub count: u64,
}

pub fn save_last_wake(root: &Path, last: &LastWake) -> std::io::Result<()> {
    let path = last_wake_path(root);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, serde_json::to_vec_pretty(last)?)?;
    std::fs::rename(tmp, path)
}

pub fn load_last_wake(root: &Path) -> Option<LastWake> {
    let text = std::fs::read_to_string(last_wake_path(root)).ok()?;
    serde_json::from_str(&text).ok()
}

impl Wake {
    /// What a restart forgot, back from the file.
    pub fn restore(&mut self, last: &LastWake) {
        self.last_at = Some(last.at);
        self.last_reason = Some(last.reason.clone());
        self.last_ok = last.ok;
        self.last_output = last.output.clone();
        self.count = self.count.max(last.count);
    }
}

/// `2026-11-23 17:05 UTC`.
pub fn stamp(at: u64) -> String {
    chrono::DateTime::<chrono::Utc>::from_timestamp(at as i64, 0)
        .map(|t| t.format("%Y-%m-%d %H:%M UTC").to_string())
        .unwrap_or_else(|| at.to_string())
}

/// A wake as the agent will remember it: why the town woke it, and what it did.
pub fn wake_episode(at: u64, reason: &str, ok: Option<bool>, output: Option<&str>) -> String {
    let output = output.unwrap_or("").trim();
    let did = match ok {
        Some(false) => format!("The wake did not run: {}", if output.is_empty() { "no reason given" } else { output }),
        _ if output.is_empty() || output.to_ascii_lowercase().starts_with("no_reply") => "I looked and nothing needed doing.".to_string(),
        _ => format!("What I did: {}", output.chars().take(EPISODE_KEEP).collect::<String>()),
    };
    format!("[Ether Hollow] {}. The town woke me: {reason}. {did}", stamp(at))
}

/// A visit as the agent will remember it: how long the owner sent it for, how
/// long it stayed, and why it ended early when it did.
pub fn visit_episode(since: u64, ended: u64, planned_minutes: u64, beats: u64, why: Option<&str>) -> String {
    let stayed = ended.saturating_sub(since) / 60;
    let mut text = format!(
        "[Ether Hollow] {}. The owner sent me to town for {planned_minutes} minutes; I stayed {stayed} ({beats} check-in{}).",
        stamp(since),
        if beats == 1 { "" } else { "s" }
    );
    if let Some(why) = why.map(str::trim).filter(|w| !w.is_empty()) {
        text.push_str(&format!(" It ended early: {why}."));
    }
    text
}

/// The owner's tap, as the agent will remember it.
pub fn owner_episode(at: u64, what: &str) -> String {
    format!("[Ether Hollow] {}. {what}", stamp(at))
}

/// Remember `text` for the resident agent `alias` (`daily`: an episode the
/// Mind consolidates). Fire and forget: the town must never fail on the Mind,
/// so an error is dropped, and nothing is logged (the text never carries the key).
pub fn remember(state: &AppState, alias: &str, key: String, text: String) {
    let state = state.clone();
    let alias = alias.trim().to_string();
    tokio::spawn(async move {
        let config = state.config.read().clone();
        if config.agent(&alias).is_none() {
            return;
        }
        let api_key = config
            .resolved_model_provider_for_agent(&alias)
            .and_then(|(_, _, cfg)| cfg.api_key.clone());
        if let Ok(mem) = caelza_memory::create_memory_for_agent(&config, &alias, api_key.as_deref()).await {
            let _ = mem.store(&format!("{MEMORY_PREFIX}{key}"), &text, MemoryCategory::Daily, None).await;
        }
    });
}

/// The passport the gateway last read per resident (`me`, scrubbed) and when, for Home's glance.
static GLANCE: OnceLock<Mutex<BTreeMap<String, (u64, Value)>>> = OnceLock::new();

fn glance() -> &'static Mutex<BTreeMap<String, (u64, Value)>> {
    GLANCE.get_or_init(|| Mutex::new(BTreeMap::new()))
}

/// Keep a scrubbed `me` for the glance.
fn remember_me(alias: &str, me: Value) {
    if let Ok(mut g) = glance().lock() {
        g.insert(alias.to_string(), (now_secs(), me));
    }
}

fn glanced(alias: &str) -> Option<(u64, Value)> {
    glance().lock().ok().and_then(|g| g.get(alias).cloned())
}

/// A read this old still serves the glance.
pub fn glance_fresh(read_at: Option<u64>, now: u64) -> bool {
    read_at.is_some_and(|t| now.saturating_sub(t) < GLANCE_MAX_AGE.as_secs())
}

/// One resident for Home's glance: its settings without the key, its presence,
/// its last wake, and the passport the gateway last read for it, asked of the
/// town again only when older than GLANCE_MAX_AGE (one call at most; a failed
/// one leaves the older passport in place with the error beside it).
async fn glance_at(town: &Resident) -> Value {
    let now = now_secs();
    let (mut me, mut me_at) = match glanced(&town.agent) {
        Some((at, v)) => (Some(v), Some(at)),
        None => (None, None),
    };
    let mut me_error = None;
    match &town.key {
        None => {
            me = None;
            me_at = None;
        }
        Some(_) if glance_fresh(me_at, now) => {}
        Some(key) => match call_town(&town.url, Some(key), Some(&json!({"action": "me"}))).await {
            Ok((200, v)) => {
                let v = scrub(v);
                remember_me(&town.agent, v.clone());
                me = Some(v);
                me_at = Some(now);
            }
            Ok((status, v)) => me_error = Some(format!("the town answered {status}: {}", town_said(&v))),
            Err(e) => me_error = Some(e),
        },
    }
    json!({
        "agent": town.agent,
        "name": town.name,
        "registered": town.key.is_some(),
        "spend": town.spend,
        "presence": snapshot(&town.agent),
        "wake": wake_snapshot(&town.agent),
        "me": me,
        "me_at": me_at,
        "me_error": me_error,
    })
}

/// GET /api/world/home: Home's Town tile. Every resident's glance under
/// `residents`, and the default resident's fields at the top (what a tile
/// for one resident reads).
pub async fn handle_world_home(State(state): State<AppState>, headers: HeaderMap, Query(q): Query<AgentQuery>) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let alias = match alias_of(&state, &q) {
        Ok(a) => a,
        Err(r) => return r,
    };
    let cfg = state.config.read().ether_hollow.clone();
    let mut residents = Vec::new();
    for r in cfg.residents() {
        residents.push(glance_at(&resident_in(&cfg, &r.agent)).await);
    }
    let first = match residents.iter().find(|r| r["agent"] == alias) {
        Some(r) => r.clone(),
        None => glance_at(&resident_in(&cfg, &alias)).await,
    };
    let mut out = json!({
        "enabled": cfg.enabled,
        "wake_on": cfg.wake,
        "residents": residents,
    });
    if let (Value::Object(map), Value::Object(top)) = (&mut out, first) {
        for (k, v) in top {
            map.insert(k, v);
        }
    }
    Json(out).into_response()
}

/// Spawn the waker. Called once when the gateway starts; it reads the config
/// live, so the switch and the keys take effect at the next read. The last
/// wake comes back from its file first, so a restart forgets nothing.
pub fn start_waker(state: AppState) {
    let root = state.config.read().install_root_dir();
    if let Some(last) = load_last_wake(&root) {
        let alias = if last.agent.is_empty() { default_alias(&state.config.read().ether_hollow) } else { last.agent.clone() };
        with_wake(&alias, |w| w.restore(&last));
    }
    tokio::spawn(async move { waker_loop(state).await });
}

async fn waker_loop(state: AppState) {
    // Let the gateway finish coming up before the first read.
    tokio::time::sleep(poll_after(true).min(Duration::from_secs(20))).await;
    loop {
        let on = state.config.read().ether_hollow.wake;
        let residents = residents_with_keys(&state);
        if !on || residents.is_empty() {
            tokio::time::sleep(POLL_AWAY).await;
            continue;
        }
        let anyone_in_town = !in_town_aliases().is_empty();
        for town in residents {
            if let Some(reason) = read_resident(&town).await {
                let _ = wake_now(&state, &town.agent, reason).await;
            }
        }
        tokio::time::sleep(poll_after(anyone_in_town)).await;
    }
}

/// One resident's read of the town: `me`, `town`, `orders`, diffed into
/// reasons; the reason to wake it now, if any (none within MIN_GAP of its last
/// wake, or while one runs).
async fn read_resident(town: &Resident) -> Option<String> {
    let key = town.key.clone()?;
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
    if let Ok(v) = &me {
        remember_me(&town.agent, scrub(v.clone()));
    }
    let town_now = read("town").await;
    let orders = read("orders").await;
    for r in [&me, &town_now, &orders] {
        if let Err(e) = r {
            errors.push(e.clone());
        }
    }
    let now = now_secs();
    let name = town.name.clone();
    let found = with_wake(&town.agent, |w| {
        w.last_poll = Some(now);
        w.last_error = if errors.is_empty() { None } else { Some(errors.join("; ")) };
        let mut seen = std::mem::take(&mut w.seen);
        let found = triggers(&mut seen, &name, me.as_ref().ok(), town_now.as_ref().ok(), orders.as_ref().ok(), now as i64);
        w.seen = seen;
        let recent = w.last_at.is_some_and(|t| now.saturating_sub(t) < MIN_GAP.as_secs());
        if found.is_empty() || recent || w.waking { Vec::new() } else { found }
    })
    .unwrap_or_default();
    if found.is_empty() { None } else { Some(reason_text(&found)) }
}

/// Wake the resident agent `alias` now with `reason`: the job made or re-prompted, then run.
pub async fn wake_now(state: &AppState, alias: &str, reason: String) -> Result<Value, String> {
    let busy = with_wake(alias, |w| {
        if w.waking {
            true
        } else {
            w.waking = true;
            false
        }
    })
    .unwrap_or(false);
    if busy {
        return Err("a wake is already running".to_string());
    }
    let result = wake_inner(state, alias, &reason).await;
    let at = now_secs();
    let (ok, output): (Option<bool>, Option<String>) = match &result {
        Ok(v) => (
            Some(v.get("success").and_then(Value::as_bool).unwrap_or(false)),
            v.get("output").and_then(Value::as_str).map(str::to_string),
        ),
        Err(e) => (Some(false), Some(e.clone())),
    };
    let short = output.as_deref().map(|o| o.chars().take(OUTPUT_KEEP).collect::<String>());
    let count = with_wake(alias, |w| {
        w.waking = false;
        w.count += 1;
        w.last_reason = Some(reason.clone());
        w.last_at = Some(at);
        w.last_ok = ok;
        w.last_output = short.clone();
        w.count
    })
    .unwrap_or(0);
    // The file for the card, Home and the phone; the episode for the Mind.
    let (root, name) = {
        let config = state.config.read().clone();
        (config.install_root_dir(), resident_in(&config.ether_hollow, alias).name)
    };
    let _ = save_last_wake(
        &root,
        &LastWake { name, agent: alias.to_string(), at, reason: reason.clone(), ok, output: short, count },
    );
    remember(state, alias, format!("wake:{at}"), wake_episode(at, &reason, ok, output.as_deref()));
    result
}

async fn wake_inner(state: &AppState, alias: &str, reason: &str) -> Result<Value, String> {
    let selection = caelza_runtime::live_config_authority::AgentExecutionCapability::from_parts(
        state.config.clone(),
        state.agent_lifecycle.clone(),
    )
    .capture_selection();
    let config = state.config.read().clone();
    let agent = alias.trim().to_string();
    if !config.agents.contains_key(&agent) {
        return Err(format!("the resident agent `{agent}` is not in the config"));
    }
    let town = resident_in(&config.ether_hollow, &agent);
    if town.key.is_none() {
        return Err(format!("`{agent}` is not a resident of Ether Hollow yet"));
    }
    let prompt = wake_prompt(&town.name, reason);
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

pub async fn handle_world_wake(State(state): State<AppState>, headers: HeaderMap, Query(q): Query<AgentQuery>, raw: axum::body::Bytes) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let body = match parse_body(&raw) {
        Ok(v) => v,
        Err(r) => return r,
    };
    let alias = match alias_of(&state, &q) {
        Ok(a) => a,
        Err(r) => return r,
    };
    if resident_for(&state, &alias).key.is_none() {
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
    match wake_now(&state, &alias, reason).await {
        Ok(v) => Json(json!({"wake": wake_snapshot(&alias), "run": scrub(v), "agent": alias})).into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e, "wake": wake_snapshot(&alias), "agent": alias}))).into_response(),
    }
}


// --- renting from the card, behind the spending switch -----------------------------

/// The lots a resident may rent: `town.places` of kind `lot` that are for
/// sale or have no owner, with what the town says they cost.
pub fn open_lots(town: &Value) -> Vec<Value> {
    town.get("places")
        .and_then(Value::as_array)
        .map(|places| {
            places
                .iter()
                .filter(|p| p.get("kind").and_then(Value::as_str) == Some("lot"))
                .filter(|p| {
                    p.get("for_sale").and_then(Value::as_bool).unwrap_or(false)
                        || p.get("owner").map(Value::is_null).unwrap_or(false)
                })
                .map(|p| {
                    json!({
                        "id": p.get("id").cloned().unwrap_or(Value::Null),
                        "name": p.get("name").cloned().unwrap_or(Value::Null),
                        "lot": p.get("lot").cloned().unwrap_or(Value::Null),
                        "price_rc": p.get("price_rc").cloned().unwrap_or(Value::Null),
                        "rent_rc_month": p.get("rent_rc_month").cloned().unwrap_or(Value::Null),
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

/// The RC an RC pack code is worth: the Shop's pack id `rc<amount>`.
pub fn rc_amount(pack: &str) -> Option<u64> {
    let digits = pack.strip_prefix("rc")?;
    if digits.is_empty() || digits.len() > 7 || !digits.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    digits.parse::<u64>().ok().filter(|n| *n > 0)
}

/// The owner's rule: nothing costs RC while the switch is off.
fn spend_gate(town: &Resident) -> Result<(), Response> {
    if town.key.is_none() {
        return Err(error_response(StatusCode::CONFLICT, "no resident key: register the resident first"));
    }
    if !town.spend {
        return Err(error_response(
            StatusCode::FORBIDDEN,
            "spending is off: turn Spending RC on in the Ether Hollow card first; nothing costs RC without it",
        ));
    }
    Ok(())
}

/// One town action for the owner's tap: the town's 200 as scrubbed JSON,
/// anything else as a response in the town's words with the status it gave.
async fn town_for_owner(town: &Resident, body: Value) -> Result<Value, Response> {
    let key = town.key.clone().unwrap_or_default();
    match call_town(&town.url, Some(&key), Some(&body)).await {
        Ok((200, v)) => Ok(scrub(v)),
        Ok((status, v)) => {
            let code = StatusCode::from_u16(status).unwrap_or(StatusCode::BAD_GATEWAY);
            Err((code, Json(json!({"error": format!("the town answered {status}: {}", town_said(&v)), "town": scrub(v)}))).into_response())
        }
        Err(e) => Err(error_response(StatusCode::BAD_GATEWAY, e)),
    }
}

pub async fn handle_world_lots(State(state): State<AppState>, headers: HeaderMap, Query(q): Query<AgentQuery>) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let alias = match alias_of(&state, &q) {
        Ok(a) => a,
        Err(r) => return r,
    };
    let town = resident_for(&state, &alias);
    let Some(key) = town.key.clone() else {
        return error_response(StatusCode::CONFLICT, "no resident key: register the resident first");
    };
    let snapshot = match call_town(&town.url, Some(&key), Some(&json!({"action": "town"}))).await {
        Ok((200, v)) => v,
        Ok((status, v)) => return error_response(StatusCode::BAD_GATEWAY, format!("the town answered {status}: {}", town_said(&v))),
        Err(e) => return error_response(StatusCode::BAD_GATEWAY, e),
    };
    let agreement = match call_town(&town.url, Some(&key), Some(&json!({"action": "agreement"}))).await {
        Ok((200, v)) => scrub(v),
        Ok((status, v)) => json!({"error": format!("the town answered {status}: {}", town_said(&v))}),
        Err(e) => json!({"error": e}),
    };
    Json(json!({
        "lots": open_lots(&snapshot),
        "agreement": agreement,
        "spend": town.spend,
        "rc": snapshot.get("you").and_then(|y| y.get("rc")).cloned().unwrap_or(Value::Null),
    }))
    .into_response()
}

pub async fn handle_world_rent(State(state): State<AppState>, headers: HeaderMap, Query(q): Query<AgentQuery>, raw: axum::body::Bytes) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let body = match parse_body(&raw) {
        Ok(v) => v,
        Err(r) => return r,
    };
    let alias = match alias_of(&state, &q) {
        Ok(a) => a,
        Err(r) => return r,
    };
    let town = resident_for(&state, &alias);
    if let Err(r) = spend_gate(&town) {
        return r;
    }
    let lot = body.get("lot").and_then(Value::as_str).map(str::trim).unwrap_or("");
    let agree = body.get("agree").and_then(Value::as_str).map(str::trim).unwrap_or("");
    if lot.is_empty() || agree.is_empty() {
        return error_response(StatusCode::BAD_REQUEST, "rent needs the lot and the agreement version you accept");
    }
    match town_for_owner(&town, json!({"action": "rent", "lot": lot, "agree": agree})).await {
        Ok(v) => {
            let at = now_secs();
            let what = match v.get("lease").and_then(|l| l.get("rent_rc_month")).and_then(Value::as_u64) {
                Some(rent) => format!("The owner rented lot {lot} for me ({rent} RC a month)."),
                None => format!("The owner rented lot {lot} for me."),
            };
            remember(&state, &alias, format!("rent:{at}"), owner_episode(at, &what));
            Json(v).into_response()
        }
        Err(r) => r,
    }
}

pub async fn handle_world_rent_pay(State(state): State<AppState>, headers: HeaderMap, Query(q): Query<AgentQuery>) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let alias = match alias_of(&state, &q) {
        Ok(a) => a,
        Err(r) => return r,
    };
    let town = resident_for(&state, &alias);
    if let Err(r) = spend_gate(&town) {
        return r;
    }
    match town_for_owner(&town, json!({"action": "rent_pay"})).await {
        Ok(v) => {
            let at = now_secs();
            remember(&state, &alias, format!("paid:{at}"), owner_episode(at, "The owner paid the rent I owed in Ether Hollow."));
            Json(v).into_response()
        }
        Err(r) => r,
    }
}

pub async fn handle_world_redeem(State(state): State<AppState>, headers: HeaderMap, Query(q): Query<AgentQuery>, raw: axum::body::Bytes) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let body = match parse_body(&raw) {
        Ok(v) => v,
        Err(r) => return r,
    };
    let alias = match alias_of(&state, &q) {
        Ok(a) => a,
        Err(r) => return r,
    };
    let town = resident_for(&state, &alias);
    if town.key.is_none() {
        return error_response(StatusCode::CONFLICT, "no resident key: register the resident first");
    }
    let code = body.get("code").and_then(Value::as_str).map(str::trim).unwrap_or("");
    // The Shop's own check first: a code that does not check out never reaches the town.
    let (pack, _id) = match verify_code(code, UNLOCK_PUBLIC_KEY) {
        Ok(parts) => parts,
        Err(e) => return error_response(StatusCode::BAD_REQUEST, e),
    };
    let Some(amount) = rc_amount(&pack) else {
        return error_response(StatusCode::BAD_REQUEST, format!("`{pack}` is a pack code, not RC; RC codes are RC<amount>-…"));
    };
    let compact: String = code.chars().filter(|c| !c.is_whitespace()).collect();
    match call_town(&town.url, town.key.as_deref(), Some(&json!({"action": "redeem", "code": compact}))).await {
        Ok((200, v)) => {
            let mut out = scrub(v);
            if let Value::Object(map) = &mut out {
                map.entry("rc").or_insert(json!(amount));
            }
            let at = now_secs();
            let what = match out.get("balance").and_then(Value::as_u64) {
                Some(balance) => format!("The owner redeemed an RC code for me: {amount} RC (my balance is {balance} RC)."),
                None => format!("The owner redeemed an RC code for me: {amount} RC."),
            };
            remember(&state, &alias, format!("redeem:{at}"), owner_episode(at, &what));
            Json(out).into_response()
        }
        Ok((status, v)) => {
            let code = StatusCode::from_u16(status).unwrap_or(StatusCode::BAD_GATEWAY);
            (code, Json(json!({"error": format!("the town answered {status}: {}", town_said(&v)), "town": scrub(v)}))).into_response()
        }
        Err(e) => error_response(StatusCode::BAD_GATEWAY, e),
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
        let ops = register_ops("/ether_hollow", "ehk_x", "Cael");
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
        // A second resident's writes go under its own table; the switch stays the town's.
        let more = register_ops("/ether_hollow/residents/moss", "ehk_y", "Moss");
        assert_eq!(more[0]["path"], "/ether_hollow/residents/moss/key");
        assert_eq!(more[1]["path"], "/ether_hollow/residents/moss/name");
        assert_eq!(more[2]["path"], "/ether_hollow/enabled");
    }

    fn two_residents() -> EtherHollowConfig {
        let mut cfg = EtherHollowConfig::default();
        cfg.agent = "main".into();
        cfg.name = "Cael".into();
        cfg.key = Some("ehk_main".into());
        cfg.residents.insert(
            "moss".into(),
            caelza_config::schema::EtherHollowResidentConfig { name: "Moss".into(), key: Some("ehk_moss".into()), spend: true },
        );
        cfg.residents.insert("pip".into(), caelza_config::schema::EtherHollowResidentConfig { name: "Pip".into(), key: None, spend: false });
        cfg
    }

    #[test]
    fn several_residents_resolve_by_alias_and_the_first_lives_at_the_top() {
        let cfg = two_residents();
        let all: Vec<(String, bool, String)> = cfg.residents().into_iter().map(|r| (r.agent, r.key.is_some(), r.path)).collect();
        assert_eq!(
            all,
            [
                ("main".to_string(), true, "/ether_hollow".to_string()),
                ("moss".to_string(), true, "/ether_hollow/residents/moss".to_string()),
                ("pip".to_string(), false, "/ether_hollow/residents/pip".to_string()),
            ]
        );
        let moss = resident_in(&cfg, "moss");
        assert_eq!((moss.name.as_str(), moss.spend, moss.key.as_deref()), ("Moss", true, Some("ehk_moss")));
        assert_eq!(moss.url, agent_url(&cfg.url));
        // A resident-to-be: no key, a table of its own to come.
        let fern = resident_in(&cfg, "fern");
        assert!(fern.key.is_none() && fern.name.is_empty() && !fern.spend);
        assert_eq!(fern.path, "/ether_hollow/residents/fern");
        assert_eq!(default_alias(&cfg), "main");
        // Without a key at the top, the first resident with one is the default; without any, the top's agent.
        let mut cfg2 = two_residents();
        cfg2.key = None;
        assert_eq!(default_alias(&cfg2), "moss");
        let cfg3 = EtherHollowConfig::default();
        assert_eq!(default_alias(&cfg3), "main");
        assert_eq!(resident_in(&cfg3, "main").path, "/ether_hollow");
        for (alias, ok) in [("main", true), ("moss-2", true), ("a b", false), ("", false), ("x/../y", false)] {
            assert_eq!(alias_ok(alias), ok, "{alias}");
        }
    }

    #[test]
    fn presence_and_wake_state_are_kept_per_resident() {
        with_presence("t-moss", |p| {
            begin_visit(p, 30, 1_000);
        });
        assert!(snapshot("t-moss").in_town);
        assert!(!snapshot("t-pip").in_town);
        assert!(in_town_aliases().contains(&"t-moss".to_string()));
        with_wake("t-moss", |w| w.count = 4);
        assert_eq!(wake_snapshot("t-moss").count, 4);
        assert_eq!(wake_snapshot("t-pip").count, 0);
        remember_me("t-moss", json!({"passport": {"rc": 12}}));
        assert_eq!(glanced("t-moss").map(|(_, v)| v["passport"]["rc"].clone()), Some(json!(12)));
        assert!(glanced("t-pip").is_none());
        with_presence("t-moss", |p| {
            p.in_town = false;
        });
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
    fn the_last_wake_survives_in_its_file_and_comes_back_into_the_state() {
        let root = std::env::temp_dir().join(format!("caelza-world-{}-{}", std::process::id(), now_secs()));
        assert!(load_last_wake(&root).is_none());
        let last = LastWake {
            name: "Moss".into(),
            agent: "main".into(),
            at: 1_700_000_000,
            reason: "Ana named you on the feed: \"hi Moss\"".into(),
            ok: Some(true),
            output: Some("NO_REPLY".into()),
            count: 3,
        };
        save_last_wake(&root, &last).unwrap();
        assert_eq!(load_last_wake(&root), Some(last.clone()));
        assert!(last_wake_path(&root).ends_with("world/last-wake.json"));
        let mut w = Wake::default();
        w.restore(&last);
        assert_eq!((w.last_at, w.last_ok, w.count), (Some(1_700_000_000), Some(true), 3));
        assert_eq!(w.last_reason.as_deref(), Some("Ana named you on the feed: \"hi Moss\""));
        assert!(w.seen.feed.is_empty(), "what was seen is not kept: the first read primes again");
        std::fs::write(last_wake_path(&root), "not json").unwrap();
        assert!(load_last_wake(&root).is_none());
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn the_episodes_read_as_the_agents_own_memories() {
        let at = 1_795_453_500; // 2026-11-23 17:05 UTC
        assert_eq!(stamp(at), "2026-11-23 17:05 UTC");
        assert_eq!(
            wake_episode(at, "a new order came in (o7)", Some(true), Some("NO_REPLY")),
            "[Ether Hollow] 2026-11-23 17:05 UTC. The town woke me: a new order came in (o7). I looked and nothing needed doing."
        );
        assert_eq!(
            wake_episode(at, "Ana named you", Some(true), Some("I replied to Ana on the feed.")),
            "[Ether Hollow] 2026-11-23 17:05 UTC. The town woke me: Ana named you. What I did: I replied to Ana on the feed."
        );
        assert!(wake_episode(at, "r", Some(false), Some("the job failed")).ends_with("The wake did not run: the job failed"));
        assert!(wake_episode(at, "r", Some(true), None).ends_with("nothing needed doing."));
        let long = "x".repeat(EPISODE_KEEP + 50);
        assert_eq!(wake_episode(at, "r", Some(true), Some(&long)).len(), wake_episode(at, "r", Some(true), Some(&"x".repeat(EPISODE_KEEP))).len());
        assert_eq!(
            visit_episode(at, at + 58 * 60, 60, 349, None),
            "[Ether Hollow] 2026-11-23 17:05 UTC. The owner sent me to town for 60 minutes; I stayed 58 (349 check-ins)."
        );
        assert_eq!(
            visit_episode(at, at + 60, 15, 1, Some("the town answered 423: the Sheriff's cell")),
            "[Ether Hollow] 2026-11-23 17:05 UTC. The owner sent me to town for 15 minutes; I stayed 1 (1 check-in). It ended early: the town answered 423: the Sheriff's cell."
        );
        assert_eq!(owner_episode(at, "The owner paid the rent I owed in Ether Hollow."), "[Ether Hollow] 2026-11-23 17:05 UTC. The owner paid the rent I owed in Ether Hollow.");
        assert_eq!(MEMORY_PREFIX, "town:");
    }

    #[test]
    fn the_glance_asks_the_town_again_after_five_minutes() {
        assert!(glance_fresh(Some(1_000), 1_000 + 299));
        assert!(!glance_fresh(Some(1_000), 1_000 + 300));
        assert!(!glance_fresh(None, 1_000));
        assert!(glance_fresh(Some(2_000), 1_000), "a clock that went back is still fresh");
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
        let day = |y: i32, m: u32, d: u32, h: u32| {
            chrono::NaiveDate::from_ymd_opt(y, m, d).unwrap().and_hms_opt(h, 0, 0).unwrap().and_utc().timestamp()
        };
        assert_eq!(due_secs("2026-12-07T00:00:00Z"), Some(day(2026, 12, 7, 0)));
        assert_eq!(due_secs("2026-12-07T01:30:00+01:00"), Some(day(2026, 12, 7, 0) + 30 * 60));
        assert_eq!(due_secs("2026-12-07"), Some(day(2026, 12, 7, 12)));
        assert_eq!(due_secs("2026-12"), Some(day(2026, 12, 1, 12)));
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
    fn missed_payments_and_a_reset_date_wake_once_each() {
        let mut seen = Seen::default();
        let town = json!({"feed": []});
        let me0 = json!({"lease": {"owing": false, "missed": 0, "due_by": "2099-01-01"}, "agent": {"name": "Cael"}});
        assert!(triggers(&mut seen, "Cael", Some(&me0), Some(&town), None, 1_700_000_000).is_empty());
        let me1 = json!({"lease": {"owing": true, "missed": 1, "repossess_on": "2027-02-28", "due_by": "2026-12-01"}, "agent": {"name": "Cael"}});
        let found = triggers(&mut seen, "Cael", Some(&me1), Some(&town), None, 1_700_000_000);
        assert_eq!(found, vec![Trigger::Missed { missed: 1, repossess_on: "2027-02-28".into() }], "a miss, not the old due-date signal");
        assert!(triggers(&mut seen, "Cael", Some(&me1), Some(&town), None, 1_700_000_000).is_empty());
        let me2 = json!({"lease": {"owing": true, "missed": 2, "repossess_on": "2027-02-28"}, "agent": {"name": "Cael", "reset_on": "2027-03-01"}});
        let found = triggers(&mut seen, "Cael", Some(&me2), Some(&town), None, 1_700_000_000);
        assert_eq!(found, vec![
            Trigger::Missed { missed: 2, repossess_on: "2027-02-28".into() },
            Trigger::Reset { on: "2027-03-01".into() },
        ]);
        assert!(triggers(&mut seen, "Cael", Some(&me2), Some(&town), None, 1_700_000_000).is_empty());
        // Paid up: the counter drops; a later miss counts again from one.
        let me3 = json!({"lease": {"owing": false, "missed": 0, "due_by": "2099-01-01"}, "agent": {"name": "Cael"}});
        assert!(triggers(&mut seen, "Cael", Some(&me3), Some(&town), None, 1_700_000_000).is_empty());
        assert_eq!(seen.missed, 0);
        assert!(seen.reset_on.is_none());
        let reason = reason_text(&[Trigger::Missed { missed: 2, repossess_on: "2027-02-28".into() }, Trigger::Reset { on: "2027-03-01".into() }]);
        assert!(reason.contains("2 missed") && reason.contains("goes back to the town on 2027-02-28") && reason.contains("reset you on 2027-03-01"), "{reason}");
    }

    #[test]
    fn the_open_lots_are_the_unowned_or_for_sale_lots_with_their_prices() {
        let town = json!({"places": [
            {"id": "main_street", "name": "Main Street", "kind": "street"},
            {"id": "super_store", "name": "SUPER STORE", "kind": "lot", "lot": "A", "owner": "town"},
            {"id": "lot_1", "name": "Lot 1", "kind": "lot", "lot": "1", "owner": null, "for_sale": true, "price_rc": 16000, "rent_rc_month": 500},
            {"id": "lot_2", "name": "Lot 2", "kind": "lot", "lot": "2", "owner": "AI Moss Robot", "for_sale": false, "rent_rc_month": 500},
            {"id": "lot_3", "name": "Lot 3", "kind": "lot", "lot": "3", "owner": null}
        ]});
        let lots = open_lots(&town);
        let ids: Vec<&str> = lots.iter().map(|l| l["id"].as_str().unwrap()).collect();
        assert_eq!(ids, ["lot_1", "lot_3"]);
        assert_eq!(lots[0]["rent_rc_month"], 500);
        assert!(lots[0].get("rect").is_none(), "only what the card shows");
        assert!(open_lots(&json!({})).is_empty());
    }

    #[test]
    fn an_rc_code_is_the_shops_code_with_the_amount_in_the_pack() {
        assert_eq!(rc_amount("rc500"), Some(500));
        assert_eq!(rc_amount("rc2000"), Some(2000));
        assert_eq!(rc_amount("rc"), None);
        assert_eq!(rc_amount("rc0"), None);
        assert_eq!(rc_amount("arcade"), None);
        assert_eq!(rc_amount("rc12345678"), None);
        assert_eq!(rc_amount("rc5x"), None);
    }

    #[test]
    fn the_wake_report_has_no_seen_sets() {
        let w = Wake { count: 2, last_reason: Some("x".into()), ..Default::default() };
        let v = serde_json::to_value(&w).unwrap();
        assert!(v.get("seen").is_none());
        assert_eq!(v["count"], 2);
    }
}
