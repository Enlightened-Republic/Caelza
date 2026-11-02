//! Caelza: the looks (vision M8), the per-agent pixel character and the
//! owner's wardrobe, kept on the Runtime so every device sees the same.
//!
//! - `GET    /api/looks/wardrobe`        → `{version, packs}` (an empty wardrobe when none was saved)
//! - `PUT    /api/looks/wardrobe`        ← `{version: 1, packs: [...]}`
//! - `GET    /api/looks/{alias}`         → `{alias, look}`; `look` is null until one is saved (the dashboard deals a default)
//! - `PUT    /api/looks/{alias}`         ← `{version: 1, parts: {layer: part}, colors: {slot: "#rrggbb"}}`
//! - `DELETE /api/looks/{alias}`         → back to the default
//!
//! The files are `<install root>/agents/<alias>/look.json` and
//! `<install root>/looks/wardrobe.json`. The gateway checks the shape (the
//! layers, the slots, the colours, the sizes); the catalog of parts belongs
//! to the dashboard, which drops any part it no longer knows.
use super::AppState;
use super::api::require_auth;
use axum::{
    extract::{Path as AxumPath, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Json, Response},
};
use caelza_config::schema::Config;
use serde_json::{Map, Value, json};
use std::path::PathBuf;

pub const LOOK_FILE: &str = "look.json";
pub const WARDROBE_FILE: &str = "wardrobe.json";
pub const LAYERS: [&str; 7] = ["backdrop", "body", "outfit", "hair", "hat", "face", "accessory"];
pub const SLOTS: [&str; 5] = ["skin", "hair", "outfit", "accent", "eyes"];
/// A look or a wardrobe is small; anything bigger is not one.
const MAX_BYTES: usize = 16 * 1024;
const MAX_PACKS: usize = 64;

fn error_response(status: StatusCode, message: impl Into<String>) -> Response {
    (status, Json(json!({"error": message.into()}))).into_response()
}

/// An agent alias as the config spells them: one word of letters, digits, `_` and `-`.
pub(crate) fn alias_ok(alias: &str) -> bool {
    !alias.is_empty()
        && alias.len() <= 64
        && alias != "wardrobe"
        && alias
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}

fn look_path(config: &Config, alias: &str) -> PathBuf {
    config.install_root_dir().join("agents").join(alias).join(LOOK_FILE)
}

fn wardrobe_path(config: &Config) -> PathBuf {
    config.install_root_dir().join("looks").join(WARDROBE_FILE)
}

fn read_json(path: &PathBuf) -> Result<Option<Value>, String> {
    match std::fs::read(path) {
        Ok(bytes) => {
            if bytes.len() > MAX_BYTES {
                return Err(format!("{} is too large to be a look", path.display()));
            }
            serde_json::from_slice(&bytes)
                .map(Some)
                .map_err(|e| format!("{} is not JSON: {e}", path.display()))
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(format!("reading {}: {e}", path.display())),
    }
}

/// Write whole or not at all: a sibling temp file, then a rename.
fn write_json(path: &PathBuf, value: &Value) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| format!("{} has no parent", path.display()))?;
    std::fs::create_dir_all(parent).map_err(|e| format!("creating {}: {e}", parent.display()))?;
    let tmp = path.with_extension("json.tmp");
    let text = serde_json::to_string_pretty(value).map_err(|e| e.to_string())?;
    std::fs::write(&tmp, text.as_bytes()).map_err(|e| format!("writing {}: {e}", tmp.display()))?;
    std::fs::rename(&tmp, path).map_err(|e| format!("renaming into {}: {e}", path.display()))
}

fn is_hex_color(s: &str) -> bool {
    s.len() == 7 && s.starts_with('#') && s[1..].chars().all(|c| c.is_ascii_hexdigit())
}

fn is_part_id(s: &str, layer: &str) -> bool {
    s.len() <= 64
        && s.starts_with(layer)
        && s[layer.len()..].starts_with('.')
        && s[layer.len() + 1..]
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
        && s.len() > layer.len() + 1
}

/// The shape of a look: version 1, one part id per layer named after its
/// layer, one `#rrggbb` per slot, nothing else. Returns the look as stored.
pub(crate) fn validate_look(value: &Value) -> Result<Value, String> {
    let obj = value.as_object().ok_or("a look is an object")?;
    if obj.get("version").and_then(Value::as_i64) != Some(1) {
        return Err("version must be 1".into());
    }
    let parts = obj
        .get("parts")
        .and_then(Value::as_object)
        .ok_or("parts must be an object of layer -> part id")?;
    let mut clean_parts = Map::new();
    for layer in LAYERS {
        let id = parts
            .get(layer)
            .and_then(Value::as_str)
            .ok_or_else(|| format!("parts.{layer} is required"))?;
        if !is_part_id(id, layer) {
            return Err(format!("parts.{layer}: {id:?} is not a {layer} part id"));
        }
        clean_parts.insert(layer.to_string(), Value::String(id.to_string()));
    }
    for key in parts.keys() {
        if !LAYERS.contains(&key.as_str()) {
            return Err(format!("parts.{key} is not a layer"));
        }
    }
    let colors = obj
        .get("colors")
        .and_then(Value::as_object)
        .ok_or("colors must be an object of slot -> #rrggbb")?;
    let mut clean_colors = Map::new();
    for slot in SLOTS {
        let c = colors
            .get(slot)
            .and_then(Value::as_str)
            .ok_or_else(|| format!("colors.{slot} is required"))?;
        if !is_hex_color(c) {
            return Err(format!("colors.{slot}: {c:?} is not #rrggbb"));
        }
        clean_colors.insert(slot.to_string(), Value::String(c.to_ascii_lowercase()));
    }
    for key in colors.keys() {
        if !SLOTS.contains(&key.as_str()) {
            return Err(format!("colors.{key} is not a slot"));
        }
    }
    Ok(json!({"version": 1, "parts": clean_parts, "colors": clean_colors}))
}

/// The shape of a wardrobe: version 1 and a short list of pack ids.
pub(crate) fn validate_wardrobe(value: &Value) -> Result<Value, String> {
    let obj = value.as_object().ok_or("a wardrobe is an object")?;
    if obj.get("version").and_then(Value::as_i64) != Some(1) {
        return Err("version must be 1".into());
    }
    let packs = obj
        .get("packs")
        .and_then(Value::as_array)
        .ok_or("packs must be a list of pack ids")?;
    if packs.len() > MAX_PACKS {
        return Err(format!("at most {MAX_PACKS} packs"));
    }
    let mut clean: Vec<String> = Vec::new();
    for p in packs {
        let id = p.as_str().ok_or("a pack id is a string")?;
        if id.is_empty()
            || id.len() > 64
            || !id.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
        {
            return Err(format!("{id:?} is not a pack id"));
        }
        if !clean.iter().any(|c| c == id) {
            clean.push(id.to_string());
        }
    }
    Ok(json!({"version": 1, "packs": clean}))
}

fn known_agent(config: &Config, alias: &str) -> bool {
    config.agents.contains_key(alias)
}

/// GET /api/looks/{alias}
pub async fn handle_look_get(
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
    let config = state.config.read().clone();
    match read_json(&look_path(&config, &alias)) {
        Ok(look) => Json(json!({"alias": alias, "look": look})).into_response(),
        Err(e) => error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    }
}

/// PUT /api/looks/{alias}
pub async fn handle_look_put(
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
    let look = match validate_look(&body) {
        Ok(l) => l,
        Err(e) => return error_response(StatusCode::BAD_REQUEST, e),
    };
    match write_json(&look_path(&config, &alias), &look) {
        Ok(()) => Json(json!({"alias": alias, "look": look})).into_response(),
        Err(e) => error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    }
}

/// DELETE /api/looks/{alias}: back to the default.
pub async fn handle_look_delete(
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
    let config = state.config.read().clone();
    let path = look_path(&config, &alias);
    match std::fs::remove_file(&path) {
        Ok(()) => Json(json!({"alias": alias, "look": Value::Null})).into_response(),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            Json(json!({"alias": alias, "look": Value::Null})).into_response()
        }
        Err(e) => error_response(StatusCode::INTERNAL_SERVER_ERROR, format!("removing {}: {e}", path.display())),
    }
}

/// GET /api/looks/wardrobe
pub async fn handle_wardrobe_get(State(state): State<AppState>, headers: HeaderMap) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let config = state.config.read().clone();
    match read_json(&wardrobe_path(&config)) {
        Ok(Some(w)) => Json(w).into_response(),
        Ok(None) => Json(json!({"version": 1, "packs": []})).into_response(),
        Err(e) => error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    }
}

/// PUT /api/looks/wardrobe
pub async fn handle_wardrobe_put(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let wardrobe = match validate_wardrobe(&body) {
        Ok(w) => w,
        Err(e) => return error_response(StatusCode::BAD_REQUEST, e),
    };
    let config = state.config.read().clone();
    match write_json(&wardrobe_path(&config), &wardrobe) {
        Ok(()) => Json(wardrobe).into_response(),
        Err(e) => error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn good_look() -> Value {
        json!({
            "version": 1,
            "parts": {
                "backdrop": "backdrop.space", "body": "body.sprout", "outfit": "outfit.hoodie",
                "hair": "hair.swoop", "hat": "hat.none", "face": "face.round", "accessory": "accessory.none"
            },
            "colors": {"skin": "#E0A98A", "hair": "#7b6bff", "outfit": "#1a1250", "accent": "#22e6ff", "eyes": "#22e6ff"}
        })
    }

    #[test]
    fn a_look_is_one_part_per_layer_and_one_colour_per_slot() {
        let clean = validate_look(&good_look()).expect("valid");
        assert_eq!(clean["colors"]["skin"], "#e0a98a", "colours are lowercased");
        assert_eq!(clean["parts"]["hat"], "hat.none");
        let mut bad = good_look();
        bad["parts"]["hat"] = json!("hair.swoop");
        assert_eq!(validate_look(&bad).unwrap_err(), "parts.hat: \"hair.swoop\" is not a hat part id");
        let mut bad = good_look();
        bad["colors"]["eyes"] = json!("blue");
        assert_eq!(validate_look(&bad).unwrap_err(), "colors.eyes: \"blue\" is not #rrggbb");
        let mut bad = good_look();
        bad["parts"].as_object_mut().unwrap().remove("face");
        assert_eq!(validate_look(&bad).unwrap_err(), "parts.face is required");
        let mut bad = good_look();
        bad["parts"]["wings"] = json!("wings.big");
        assert_eq!(validate_look(&bad).unwrap_err(), "parts.wings is not a layer");
        let mut bad = good_look();
        bad["version"] = json!(2);
        assert_eq!(validate_look(&bad).unwrap_err(), "version must be 1");
        assert!(validate_look(&json!("nope")).is_err());
    }

    #[test]
    fn a_wardrobe_is_a_short_list_of_pack_ids_without_repeats() {
        let w = validate_wardrobe(&json!({"version": 1, "packs": ["cosmic", "cosmic", "arcade"]})).expect("valid");
        assert_eq!(w["packs"], json!(["cosmic", "arcade"]));
        assert!(validate_wardrobe(&json!({"version": 1, "packs": ["../x"]})).is_err());
        assert!(validate_wardrobe(&json!({"version": 1, "packs": "cosmic"})).is_err());
        let many: Vec<String> = (0..65).map(|i| format!("p{i}")).collect();
        assert!(validate_wardrobe(&json!({"version": 1, "packs": many})).is_err());
    }

    #[test]
    fn aliases_are_one_word_and_never_the_wardrobe() {
        assert!(alias_ok("main") && alias_ok("cael") && alias_ok("agent_2-b"));
        assert!(!alias_ok("") && !alias_ok("wardrobe") && !alias_ok("../main") && !alias_ok("a b"));
    }

    #[test]
    fn files_are_written_whole_and_read_back() {
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join("agents").join("main").join(LOOK_FILE);
        assert_eq!(read_json(&path).expect("missing is none"), None);
        write_json(&path, &good_look()).expect("written");
        assert_eq!(read_json(&path).expect("read").unwrap()["parts"]["body"], "body.sprout");
        assert!(!path.with_extension("json.tmp").exists(), "the temp file was renamed away");
    }
}
