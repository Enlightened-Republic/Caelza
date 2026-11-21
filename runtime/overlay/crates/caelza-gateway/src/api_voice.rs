//! Caelza: the voice (vision M10 §10, slice P2b), kept on the Runtime so every
//! device reads the agent's replies aloud the same way.
//!
//! - `GET    /api/voice/offer`         → `{version, engines: {<engine>: {voices, offered_at, by}}}`
//! - `POST   /api/voice/offer`         ← `{engine: "browser" | "phone", voices: [{id, name, lang?}], by?}`:
//!                                       what a device can speak with (the dashboard offers the browser's
//!                                       voices when it opens a chat, the app the phone's)
//! - `GET    /api/voice/elevenlabs`    → `{configured, voices}`: the owner's ElevenLabs voices, fetched
//!                                       with the key in `[providers.tts.elevenlabs.<alias>]` (upstream's
//!                                       own section) and kept as the `elevenlabs` offer
//! - `GET    /api/voice/{alias}`       → `{alias, voice}`; `voice` is null until one is chosen
//! - `PUT    /api/voice/{alias}`       ← `{version: 1, engine, voice, name?, rate?, pitch?, why?}`
//! - `DELETE /api/voice/{alias}`       → back to the device's own voice
//! - `POST   /api/voice/{alias}/speak` ← `{text, voice?}` → `audio/mpeg`: the text in the agent's
//!                                       ElevenLabs voice (or `voice`), through upstream's provider
//!
//! The files are `<install root>/agents/<alias>/voice.json` and
//! `<install root>/voices.json`; caelza-tools' `voice` tool reads and writes
//! the same files with the same checks (`caelza_tools::voice`), so the agent
//! and the dashboard agree on what a voice is.
use super::AppState;
use super::api::require_auth;
use axum::{
    extract::{Path as AxumPath, State},
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Json, Response},
};
use caelza_channels::tts::{ElevenLabsTtsProvider, TtsProvider};
use caelza_config::schema::{Config, ElevenLabsTtsProviderConfig, TtsProviderConfig};
use caelza_tools::voice::{ENGINES, offered_path, tidy_offer, validate_voice, voice_path};
use serde_json::{Value, json};
use std::collections::HashMap;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};

/// The offer's read-modify-write under one lock: two devices offering at once
/// would otherwise lose one engine's list.
static OFFER_LOCK: parking_lot::Mutex<()> = parking_lot::Mutex::new(());
/// A temp file per write: two writers of one file must not share a name.
static WRITE_SEQ: AtomicU64 = AtomicU64::new(0);

/// Three engines of up to 200 voices with labels: well under this.
const MAX_BYTES: usize = 512 * 1024;
/// A reply read aloud, at most (the dashboard cuts at a sentence before sending).
pub const MAX_SPEAK_CHARS: usize = 2000;
const MAX_BY_CHARS: usize = 40;
pub const ELEVENLABS_VOICES_URL: &str = "https://api.elevenlabs.io/v1/voices";
/// ElevenLabs' documented default; upstream's provider falls back to a retired model.
pub const ELEVENLABS_DEFAULT_MODEL: &str = "eleven_multilingual_v2";
/// The proxy service key upstream's ElevenLabs provider uses.
const SERVICE_KEY: &str = "channel.tts.elevenlabs";
const CALL_TIMEOUT_SECS: u64 = 20;
const CONNECT_TIMEOUT_SECS: u64 = 10;

fn error_response(status: StatusCode, message: impl Into<String>) -> Response {
    (status, Json(json!({"error": message.into()}))).into_response()
}

/// An agent alias; the two fixed routes are not aliases.
pub(crate) fn alias_ok(alias: &str) -> bool {
    super::api_looks::alias_ok(alias) && alias != "offer" && alias != "elevenlabs"
}

fn read_json(path: &Path) -> Result<Option<Value>, String> {
    match std::fs::read(path) {
        Ok(bytes) => {
            if bytes.len() > MAX_BYTES {
                return Err(format!("{} is too large to be a voice file", path.display()));
            }
            serde_json::from_slice(&bytes)
                .map(Some)
                .map_err(|e| format!("{} is not JSON: {e}", path.display()))
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(format!("reading {}: {e}", path.display())),
    }
}

/// Write whole or not at all: a sibling temp file of its own, then a rename.
fn write_json(path: &Path, value: &Value) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| format!("{} has no parent", path.display()))?;
    std::fs::create_dir_all(parent).map_err(|e| format!("creating {}: {e}", parent.display()))?;
    let seq = WRITE_SEQ.fetch_add(1, Ordering::Relaxed);
    let tmp = path.with_extension(format!("json.{}.{seq}.tmp", std::process::id()));
    let text = serde_json::to_string_pretty(value).map_err(|e| e.to_string())?;
    std::fs::write(&tmp, text.as_bytes()).map_err(|e| format!("writing {}: {e}", tmp.display()))?;
    std::fs::rename(&tmp, path).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        format!("renaming into {}: {e}", path.display())
    })
}

fn empty_offer() -> Value {
    json!({"version": 1, "engines": {}})
}

fn now_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn known_agent(config: &Config, alias: &str) -> bool {
    config.agents.contains_key(alias)
}

/// The ElevenLabs instance the owner set: `default`, else the first by name;
/// only with a key. The model falls back to ElevenLabs' documented default.
pub(crate) fn elevenlabs_provider(
    map: &HashMap<String, ElevenLabsTtsProviderConfig>,
) -> Option<(String, TtsProviderConfig)> {
    let alias = if map.contains_key("default") {
        "default".to_string()
    } else {
        let mut keys: Vec<&String> = map.keys().collect();
        keys.sort();
        (*keys.first()?).clone()
    };
    let mut base = map.get(&alias)?.base.clone();
    base.api_key.as_deref().map(str::trim).filter(|k| !k.is_empty())?;
    if base.model.as_deref().map(str::trim).unwrap_or("").is_empty() {
        base.model = Some(ELEVENLABS_DEFAULT_MODEL.to_string());
    }
    Some((alias, base))
}

/// ElevenLabs' `GET /v1/voices` answer as an offer: `{id, name, lang?, gender?, accent?, age?, description?}`.
pub(crate) fn elevenlabs_offer(answer: &Value) -> Vec<Value> {
    answer["voices"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|v| {
            let id = v["voice_id"].as_str()?;
            let name = v["name"].as_str().unwrap_or(id);
            let labels = &v["labels"];
            let mut entry = json!({"id": id, "name": name});
            for (from, to) in [
                ("language", "lang"),
                ("gender", "gender"),
                ("accent", "accent"),
                ("age", "age"),
                ("description", "description"),
                ("descriptive", "description"),
                ("use_case", "description"),
            ] {
                if let Some(s) = labels[from].as_str().map(str::trim).filter(|s| !s.is_empty())
                    && entry.get(to).is_none()
                {
                    entry[to] = json!(s);
                }
            }
            Some(entry)
        })
        .collect()
}

/// One engine's offer into `voices.json`; the other engines' lists stay.
fn store_offer(root: &Path, engine: &str, voices: Vec<Value>, by: &str) -> Result<usize, String> {
    let _guard = OFFER_LOCK.lock();
    let path = offered_path(root);
    let mut offered = read_json(&path)?.unwrap_or_else(empty_offer);
    if !offered.get("engines").is_some_and(Value::is_object) {
        offered = empty_offer();
    }
    let count = voices.len();
    offered["engines"][engine] = json!({"voices": voices, "offered_at": now_secs(), "by": by});
    write_json(&path, &offered)?;
    Ok(count)
}

/// GET /api/voice/offer
pub async fn handle_offer_get(State(state): State<AppState>, headers: HeaderMap) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let root = state.config.read().install_root_dir();
    match read_json(&offered_path(&root)) {
        Ok(Some(offered)) if offered.get("engines").is_some_and(Value::is_object) => Json(offered).into_response(),
        Ok(_) => Json(empty_offer()).into_response(),
        Err(e) => error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    }
}

/// POST /api/voice/offer: a device says what it can speak with.
pub async fn handle_offer_post(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let engine = body.get("engine").and_then(Value::as_str).map(str::trim).unwrap_or("");
    if !ENGINES.contains(&engine) {
        return error_response(StatusCode::BAD_REQUEST, format!("engine must be one of {}", ENGINES.join(", ")));
    }
    if engine == "elevenlabs" {
        return error_response(StatusCode::BAD_REQUEST, "the Runtime fetches the ElevenLabs voices itself (GET /api/voice/elevenlabs)");
    }
    let voices = match tidy_offer(body.get("voices").unwrap_or(&Value::Null)) {
        Ok(v) => v,
        Err(e) => return error_response(StatusCode::BAD_REQUEST, e),
    };
    let by = body
        .get("by")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty() && s.chars().count() <= MAX_BY_CHARS && !s.chars().any(char::is_control))
        .unwrap_or("device");
    let root = state.config.read().install_root_dir();
    match store_offer(&root, engine, voices, by) {
        Ok(count) => Json(json!({"engine": engine, "count": count})).into_response(),
        Err(e) => error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    }
}

/// GET /api/voice/elevenlabs: the owner's voices, with the key; the list becomes the `elevenlabs` offer.
pub async fn handle_elevenlabs_get(State(state): State<AppState>, headers: HeaderMap) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let config = state.config.read().clone();
    let Some((_alias, base)) = elevenlabs_provider(&config.providers.tts.elevenlabs) else {
        return Json(json!({"configured": false, "voices": []})).into_response();
    };
    let key = base.api_key.clone().unwrap_or_default();
    let client = caelza_config::schema::build_runtime_proxy_client_with_timeouts(
        SERVICE_KEY,
        CALL_TIMEOUT_SECS,
        CONNECT_TIMEOUT_SECS,
    );
    let response = client
        .get(ELEVENLABS_VOICES_URL)
        .header("xi-api-key", key.trim())
        .header("Accept", "application/json")
        .send()
        .await;
    let response = match response {
        Ok(r) => r,
        Err(e) => return error_response(StatusCode::BAD_GATEWAY, format!("could not reach ElevenLabs: {e}")),
    };
    let status = response.status().as_u16();
    let text = response.text().await.unwrap_or_default();
    if status == 401 {
        return error_response(StatusCode::BAD_GATEWAY, "ElevenLabs refused the key; check it on the Connect page");
    }
    if !(200..300).contains(&status) {
        return error_response(StatusCode::BAD_GATEWAY, format!("ElevenLabs answered {status}"));
    }
    let answer: Value = match serde_json::from_str(&text) {
        Ok(v) => v,
        Err(e) => return error_response(StatusCode::BAD_GATEWAY, format!("ElevenLabs sent something that is not JSON: {e}")),
    };
    let voices = match tidy_offer(&Value::Array(elevenlabs_offer(&answer))) {
        Ok(v) => v,
        Err(e) => return error_response(StatusCode::BAD_GATEWAY, e),
    };
    if let Err(e) = store_offer(&config.install_root_dir(), "elevenlabs", voices.clone(), "runtime") {
        return error_response(StatusCode::INTERNAL_SERVER_ERROR, e);
    }
    Json(json!({"configured": true, "voices": voices})).into_response()
}

/// GET /api/voice/{alias}
pub async fn handle_voice_get(
    State(state): State<AppState>,
    headers: HeaderMap,
    AxumPath(alias): AxumPath<String>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    if !alias_ok(&alias) {
        return error_response(StatusCode::BAD_REQUEST, "not an agent alias");
    }
    let root = state.config.read().install_root_dir();
    match read_json(&voice_path(&root, &alias)) {
        Ok(voice) => Json(json!({"alias": alias, "voice": voice})).into_response(),
        Err(e) => error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    }
}

/// PUT /api/voice/{alias}
pub async fn handle_voice_put(
    State(state): State<AppState>,
    headers: HeaderMap,
    AxumPath(alias): AxumPath<String>,
    Json(body): Json<Value>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    if !alias_ok(&alias) {
        return error_response(StatusCode::BAD_REQUEST, "not an agent alias");
    }
    let config = state.config.read().clone();
    if !known_agent(&config, &alias) {
        return error_response(StatusCode::NOT_FOUND, format!("no agent {alias:?} in the config"));
    }
    let voice = match validate_voice(&body) {
        Ok(v) => v,
        Err(e) => return error_response(StatusCode::BAD_REQUEST, e),
    };
    match write_json(&voice_path(&config.install_root_dir(), &alias), &voice) {
        Ok(()) => Json(json!({"alias": alias, "voice": voice})).into_response(),
        Err(e) => error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    }
}

/// DELETE /api/voice/{alias}: back to the device's own voice.
pub async fn handle_voice_delete(
    State(state): State<AppState>,
    headers: HeaderMap,
    AxumPath(alias): AxumPath<String>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    if !alias_ok(&alias) {
        return error_response(StatusCode::BAD_REQUEST, "not an agent alias");
    }
    let root = state.config.read().install_root_dir();
    match std::fs::remove_file(voice_path(&root, &alias)) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => return error_response(StatusCode::INTERNAL_SERVER_ERROR, format!("removing the voice: {e}")),
    }
    Json(json!({"alias": alias, "voice": Value::Null})).into_response()
}

fn elevenlabs_id_ok(id: &str) -> bool {
    !id.is_empty() && id.len() <= 120 && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

/// POST /api/voice/{alias}/speak: `{text, voice?}` → `audio/mpeg` in the agent's ElevenLabs voice.
pub async fn handle_speak(
    State(state): State<AppState>,
    headers: HeaderMap,
    AxumPath(alias): AxumPath<String>,
    Json(body): Json<Value>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    if !alias_ok(&alias) {
        return error_response(StatusCode::BAD_REQUEST, "not an agent alias");
    }
    let text = body.get("text").and_then(Value::as_str).map(str::trim).unwrap_or("");
    let chars = text.chars().count();
    if chars == 0 {
        return error_response(StatusCode::BAD_REQUEST, "text is empty");
    }
    if chars > MAX_SPEAK_CHARS {
        return error_response(StatusCode::BAD_REQUEST, format!("text is longer than {MAX_SPEAK_CHARS} characters"));
    }
    let config = state.config.read().clone();
    let Some((provider_alias, base)) = elevenlabs_provider(&config.providers.tts.elevenlabs) else {
        return error_response(StatusCode::NOT_FOUND, "no ElevenLabs key yet; add one on the Connect page");
    };
    let voice_id = match body.get("voice").and_then(Value::as_str).map(str::trim).filter(|s| !s.is_empty()) {
        Some(v) => v.to_string(),
        None => match read_json(&voice_path(&config.install_root_dir(), &alias)) {
            Ok(Some(v)) if v["engine"] == "elevenlabs" => v["voice"].as_str().unwrap_or("").to_string(),
            Ok(_) => {
                return error_response(StatusCode::CONFLICT, "this agent's voice is not an ElevenLabs voice; the device speaks it itself");
            }
            Err(e) => return error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
        },
    };
    if !elevenlabs_id_ok(&voice_id) {
        return error_response(StatusCode::BAD_REQUEST, "not an ElevenLabs voice id");
    }
    let provider = match ElevenLabsTtsProvider::new(&provider_alias, &base) {
        Ok(p) => p,
        Err(e) => return error_response(StatusCode::INTERNAL_SERVER_ERROR, format!("ElevenLabs is not set up: {e}")),
    };
    match provider.synthesize(text, &voice_id).await {
        Ok(bytes) => (
            StatusCode::OK,
            [(header::CONTENT_TYPE, "audio/mpeg"), (header::CACHE_CONTROL, "no-store")],
            bytes,
        )
            .into_response(),
        Err(e) => error_response(StatusCode::BAD_GATEWAY, format!("ElevenLabs did not speak: {e}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn instance(key: Option<&str>, model: Option<&str>) -> ElevenLabsTtsProviderConfig {
        ElevenLabsTtsProviderConfig {
            base: TtsProviderConfig {
                api_key: key.map(str::to_string),
                model: model.map(str::to_string),
                ..TtsProviderConfig::default()
            },
        }
    }

    #[test]
    fn the_two_fixed_routes_are_not_aliases() {
        assert!(alias_ok("main") && alias_ok("cael") && alias_ok("agent-2"));
        assert!(!alias_ok("offer") && !alias_ok("elevenlabs") && !alias_ok("wardrobe") && !alias_ok("a b"));
    }

    #[test]
    fn the_provider_is_default_else_the_first_by_name_and_needs_a_key() {
        let mut map = HashMap::new();
        assert!(elevenlabs_provider(&map).is_none());
        map.insert("zed".to_string(), instance(Some("k-zed"), None));
        map.insert("amy".to_string(), instance(Some("k-amy"), Some("eleven_flash_v2_5")));
        let (alias, base) = elevenlabs_provider(&map).unwrap();
        assert_eq!(alias, "amy");
        assert_eq!(base.model.as_deref(), Some("eleven_flash_v2_5"));
        map.insert("default".to_string(), instance(Some(" k-default "), Some("  ")));
        let (alias, base) = elevenlabs_provider(&map).unwrap();
        assert_eq!(alias, "default");
        assert_eq!(base.model.as_deref(), Some(ELEVENLABS_DEFAULT_MODEL), "a blank model gets the documented default");
        map.insert("default".to_string(), instance(Some(""), None));
        assert!(elevenlabs_provider(&map).is_none(), "default without a key: none, even with others around");
    }

    #[test]
    fn the_elevenlabs_answer_becomes_an_offer_with_its_labels() {
        let answer = json!({"voices": [
            {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel", "labels": {"accent": "american", "description": "calm", "age": "young", "gender": "female", "use_case": "narration"}, "category": "premade"},
            {"voice_id": "x9", "labels": {"language": "en", "descriptive": "warm"}},
            {"name": "no id"},
        ]});
        let offer = tidy_offer(&Value::Array(elevenlabs_offer(&answer))).unwrap();
        assert_eq!(offer.len(), 2);
        assert_eq!(offer[0]["name"], "Rachel");
        assert_eq!(offer[0]["gender"], "female");
        assert_eq!(offer[0]["description"], "calm", "the first description label wins");
        assert_eq!(offer[1]["name"], "x9");
        assert_eq!(offer[1]["lang"], "en");
        assert_eq!(offer[1]["description"], "warm");
        assert!(elevenlabs_offer(&json!({})).is_empty());
    }

    #[test]
    fn store_offer_keeps_the_other_engines() {
        let root = std::env::temp_dir().join(format!("caelza-voice-api-{}-{}", std::process::id(), WRITE_SEQ.fetch_add(1, Ordering::Relaxed)));
        std::fs::create_dir_all(&root).unwrap();
        assert_eq!(store_offer(&root, "browser", vec![json!({"id": "a", "name": "A"})], "dashboard").unwrap(), 1);
        assert_eq!(store_offer(&root, "phone", vec![json!({"id": "p", "name": "P"}), json!({"id": "q", "name": "Q"})], "app").unwrap(), 2);
        let offered = read_json(&offered_path(&root)).unwrap().unwrap();
        assert_eq!(offered["engines"]["browser"]["voices"][0]["id"], "a");
        assert_eq!(offered["engines"]["phone"]["voices"].as_array().unwrap().len(), 2);
        assert_eq!(offered["engines"]["phone"]["by"], "app");
        assert!(offered["engines"]["browser"]["offered_at"].as_u64().unwrap() > 0);
        // A broken file is replaced, not appended to.
        std::fs::write(offered_path(&root), b"[]").unwrap();
        store_offer(&root, "browser", vec![], "dashboard").unwrap();
        let offered = read_json(&offered_path(&root)).unwrap().unwrap();
        assert_eq!(offered["engines"]["browser"]["voices"], json!([]));
        assert!(elevenlabs_id_ok("21m00Tcm4TlvDq8ikWAM") && !elevenlabs_id_ok("") && !elevenlabs_id_ok("a b"));
    }
}
