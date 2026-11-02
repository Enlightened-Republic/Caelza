//! Caelza: the looks (vision M8), the per-agent pixel character and the
//! owner's wardrobe, kept on the Runtime so every device sees the same.
//!
//! - `GET    /api/looks/wardrobe`        → `{version, packs, unlocks}` (an empty wardrobe when none was saved)
//! - `PUT    /api/looks/wardrobe`        ← `{version: 1, packs: [...]}`; the stored `unlocks` stay as they are
//! - `POST   /api/looks/wardrobe/unlock` ← `{code}`: a priced pack's code, checked against `UNLOCK_PUBLIC_KEY`;
//!                                         the pack joins `packs` and `unlocks[pack]` remembers the code's id
//! - `GET    /api/looks/{alias}`         → `{alias, look}`; `look` is null until one is saved (the dashboard deals a default)
//! - `PUT    /api/looks/{alias}`         ← `{version: 1, parts: {layer: part}, colors: {slot: "#rrggbb"}}`
//! - `DELETE /api/looks/{alias}`         → back to the default
//!
//! The files are `<install root>/agents/<alias>/look.json` and
//! `<install root>/looks/wardrobe.json`. The gateway checks the shape (the
//! layers, the slots, the colours, the sizes); the catalog of parts belongs
//! to the dashboard, which drops any part it no longer knows.
//!
//! An unlock code is `<PACK>-<ID>-<SIGNATURE>`: the pack, eight characters
//! that make the code its own, and an Ed25519 signature (base64url, no
//! padding) over `caelza-unlock:v1:<pack>:<id>` by the key the owner keeps
//! (scripts/unlock_codes.py mints them). Only the public key ships, so the
//! Runtime can check a code but never make one. Ed25519 comes from rustls'
//! ring provider, already linked for TLS; nothing new is pulled in.
use super::AppState;
use super::api::require_auth;
use axum::{
    extract::{Path as AxumPath, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Json, Response},
};
use base64::Engine as _;
use caelza_config::schema::Config;
use rustls::pki_types::alg_id;
use serde_json::{Map, Value, json};
use std::path::PathBuf;

pub const LOOK_FILE: &str = "look.json";
pub const WARDROBE_FILE: &str = "wardrobe.json";
pub const LAYERS: [&str; 7] = ["backdrop", "body", "outfit", "hair", "hat", "face", "accessory"];
pub const SLOTS: [&str; 5] = ["skin", "hair", "outfit", "accent", "eyes"];
/// A look or a wardrobe is small; anything bigger is not one.
const MAX_BYTES: usize = 16 * 1024;
const MAX_PACKS: usize = 64;

/// The public half of the key that signs unlock codes; looks/catalog.json
/// `unlock.public_key` carries the same hex, and tests/test_unlock_codes.py
/// keeps the two equal. Rotate with `scripts/unlock_codes.py keygen`.
pub const UNLOCK_PUBLIC_KEY: &str = "eaf8d0dc38c503f966837e457fbb66131a63d28969e510954c0cd83c3aa9ead1";
const UNLOCK_MESSAGE_PREFIX: &str = "caelza-unlock:v1:";
/// The characters of a code's id: no 0/O or 1/I to confuse.
const CODE_ID_ALPHABET: &str = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
const CODE_ID_LEN: usize = 8;
const MAX_CODE_LEN: usize = 160;

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

fn is_pack_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 64
        && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}

fn is_code_id(id: &str) -> bool {
    id.len() == CODE_ID_LEN && id.chars().all(|c| CODE_ID_ALPHABET.contains(c))
}

/// The shape of a wardrobe: version 1, a short list of pack ids, and the
/// unlocks (pack id → the id of the code that opened it), which only the
/// unlock route adds to.
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
        if !is_pack_id(id) {
            return Err(format!("{id:?} is not a pack id"));
        }
        if !clean.iter().any(|c| c == id) {
            clean.push(id.to_string());
        }
    }
    let mut unlocks = Map::new();
    if let Some(raw) = obj.get("unlocks") {
        let raw = raw
            .as_object()
            .ok_or("unlocks must be an object of pack id -> code id")?;
        if raw.len() > MAX_PACKS {
            return Err(format!("at most {MAX_PACKS} unlocks"));
        }
        for (pack, id) in raw {
            if !is_pack_id(pack) {
                return Err(format!("unlocks: {pack:?} is not a pack id"));
            }
            let id = id.as_str().ok_or("a code id is a string")?;
            if !is_code_id(id) {
                return Err(format!("unlocks.{pack}: {id:?} is not a code id"));
            }
            unlocks.insert(pack.clone(), Value::String(id.to_string()));
        }
    }
    Ok(json!({"version": 1, "packs": clean, "unlocks": unlocks}))
}

// ---- unlock codes ------------------------------------------------------------------

/// A code taken apart: `(pack, id, signature)`. The pack and the id read in
/// any case; the signature is base64url without padding, 64 bytes.
pub(crate) fn parse_code(code: &str) -> Result<(String, String, Vec<u8>), String> {
    let text: String = code.chars().filter(|c| !c.is_whitespace()).collect();
    if text.is_empty() || text.len() > MAX_CODE_LEN {
        return Err("not an unlock code".into());
    }
    let mut parts = text.splitn(3, '-');
    let (pack, id, sig) = match (parts.next(), parts.next(), parts.next()) {
        (Some(p), Some(i), Some(s)) => (p.to_ascii_lowercase(), i.to_ascii_uppercase(), s),
        _ => return Err("not an unlock code".into()),
    };
    if !is_pack_id(&pack) || !is_code_id(&id) {
        return Err("not an unlock code".into());
    }
    let signature = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(sig)
        .map_err(|_| "not an unlock code".to_string())?;
    if signature.len() != 64 {
        return Err("not an unlock code".into());
    }
    Ok((pack, id, signature))
}

/// Ed25519 through rustls' ring provider: the raw 32-byte key, the message, the 64-byte signature.
fn ed25519_ok(public_key: &[u8], message: &[u8], signature: &[u8]) -> bool {
    rustls::crypto::ring::default_provider()
        .signature_verification_algorithms
        .all
        .iter()
        .find(|a| a.public_key_alg_id() == alg_id::ED25519 && a.signature_alg_id() == alg_id::ED25519)
        .is_some_and(|a| a.verify_signature(public_key, message, signature).is_ok())
}

/// `(pack, id)` of a good code under the public key given as hex.
pub(crate) fn verify_code(code: &str, public_key_hex: &str) -> Result<(String, String), String> {
    let (pack, id, signature) = parse_code(code)?;
    let public_key = hex::decode(public_key_hex).map_err(|_| "the unlock key is not hex".to_string())?;
    if public_key.len() != 32 {
        return Err("the unlock key is not 32 bytes".into());
    }
    let message = format!("{UNLOCK_MESSAGE_PREFIX}{pack}:{id}");
    if ed25519_ok(&public_key, message.as_bytes(), &signature) {
        Ok((pack, id))
    } else {
        Err("the code does not check out".into())
    }
}

fn empty_wardrobe() -> Value {
    json!({"version": 1, "packs": [], "unlocks": {}})
}

/// The stored wardrobe, whole; a missing or broken file reads as empty.
fn stored_wardrobe(config: &Config) -> Result<Value, String> {
    match read_json(&wardrobe_path(config))? {
        Some(raw) => Ok(validate_wardrobe(&raw).unwrap_or_else(|_| empty_wardrobe())),
        None => Ok(empty_wardrobe()),
    }
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
        Ok(None) => Json(empty_wardrobe()).into_response(),
        Err(e) => error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    }
}

/// PUT /api/looks/wardrobe: the packs as sent; the unlocks as stored (only a code changes them).
pub async fn handle_wardrobe_put(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let mut wardrobe = match validate_wardrobe(&body) {
        Ok(w) => w,
        Err(e) => return error_response(StatusCode::BAD_REQUEST, e),
    };
    let config = state.config.read().clone();
    match stored_wardrobe(&config) {
        Ok(stored) => wardrobe["unlocks"] = stored["unlocks"].clone(),
        Err(e) => return error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    }
    match write_json(&wardrobe_path(&config), &wardrobe) {
        Ok(()) => Json(wardrobe).into_response(),
        Err(e) => error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    }
}

/// POST /api/looks/wardrobe/unlock: `{code}` → the wardrobe with the code's
/// pack in it and the unlock remembered. A code that does not check out is a
/// 400 with a plain reason.
pub async fn handle_wardrobe_unlock(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let code = body.get("code").and_then(Value::as_str).unwrap_or("");
    let (pack, id) = match verify_code(code, UNLOCK_PUBLIC_KEY) {
        Ok(found) => found,
        Err(e) => return error_response(StatusCode::BAD_REQUEST, e),
    };
    let config = state.config.read().clone();
    let current = match stored_wardrobe(&config) {
        Ok(w) => w,
        Err(e) => return error_response(StatusCode::INTERNAL_SERVER_ERROR, e),
    };
    let mut packs: Vec<Value> = current["packs"].as_array().cloned().unwrap_or_default();
    if !packs.iter().any(|p| p.as_str() == Some(pack.as_str())) {
        packs.push(Value::String(pack.clone()));
    }
    let mut unlocks = current["unlocks"].as_object().cloned().unwrap_or_default();
    unlocks.insert(pack.clone(), Value::String(id));
    let wardrobe = json!({"version": 1, "packs": packs, "unlocks": unlocks});
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
        assert_eq!(w["unlocks"], json!({}), "no unlocks is an empty object");
        assert!(validate_wardrobe(&json!({"version": 1, "packs": ["../x"]})).is_err());
        assert!(validate_wardrobe(&json!({"version": 1, "packs": "cosmic"})).is_err());
        let many: Vec<String> = (0..65).map(|i| format!("p{i}")).collect();
        assert!(validate_wardrobe(&json!({"version": 1, "packs": many})).is_err());
        let w = validate_wardrobe(&json!({"version": 1, "packs": ["arcade"], "unlocks": {"arcade": "TEST2345"}})).expect("valid");
        assert_eq!(w["unlocks"]["arcade"], "TEST2345");
        assert_eq!(
            validate_wardrobe(&json!({"version": 1, "packs": [], "unlocks": {"arcade": "test0"}})).unwrap_err(),
            "unlocks.arcade: \"test0\" is not a code id"
        );
        assert!(validate_wardrobe(&json!({"version": 1, "packs": [], "unlocks": ["arcade"]})).is_err());
    }

    // The test key: seed sha256("caelza test unlock key"); the code is what
    // scripts/unlock_codes.py mints for the arcade pack with the id TEST2345
    // (tests/test_unlock_codes.py mints it again and compares).
    const TEST_PUBLIC_KEY: &str = "fc5dc039a50e26f718ae5063b4d20c7121f468210209eab175ef880934667a7e";
    const TEST_CODE: &str = "ARCADE-TEST2345-Pnj8FQev4WFjpZzV5W7lLxPCuAfWQVi5tqaTVoXR4xsirpwYtC907gtdHruBANsm2J_goTsOL6fOd2qclwMRBg";

    #[test]
    fn an_unlock_code_is_a_pack_an_id_and_a_signature_that_checks_out() {
        let (pack, id, sig) = parse_code(TEST_CODE).expect("parses");
        assert_eq!((pack.as_str(), id.as_str(), sig.len()), ("arcade", "TEST2345", 64));
        assert_eq!(parse_code(" arcade-test2345-Pnj8FQev4WFjpZzV5W7lLxPCuAfWQVi5tqaTVoXR4xsirpwYtC907gtdHruBANsm2J_goTsOL6fOd2qclwMRBg ").expect("case and spaces do not matter").1, "TEST2345");
        assert_eq!(verify_code(TEST_CODE, TEST_PUBLIC_KEY).expect("good"), ("arcade".to_string(), "TEST2345".to_string()));
        assert_eq!(verify_code(TEST_CODE, UNLOCK_PUBLIC_KEY).unwrap_err(), "the code does not check out", "the test key is not the shop's");
        let other_pack = TEST_CODE.replacen("ARCADE", "COSMIC", 1);
        assert_eq!(verify_code(&other_pack, TEST_PUBLIC_KEY).unwrap_err(), "the code does not check out");
        let other_id = TEST_CODE.replacen("TEST2345", "TEST2346", 1);
        assert_eq!(verify_code(&other_id, TEST_PUBLIC_KEY).unwrap_err(), "the code does not check out");
        // A character of the signature changed (one in the middle: the last one
        // also carries padding bits, and a non-canonical tail fails the parse).
        let mut chars: Vec<char> = TEST_CODE.chars().collect();
        chars[40] = if chars[40] == 'A' { 'B' } else { 'A' };
        let tampered: String = chars.into_iter().collect();
        assert_eq!(verify_code(&tampered, TEST_PUBLIC_KEY).unwrap_err(), "the code does not check out");
        let mut tail = TEST_CODE.to_string();
        tail.pop();
        tail.push('h');
        assert_eq!(parse_code(&tail).unwrap_err(), "not an unlock code", "padding bits set: not even a code");
        for bad in ["", "ARCADE", "ARCADE-TEST2345", "ARCADE-TEST2345-short", "ARCADE-TEST0345-Pnj8", "AR CADE-TEST2345-x"] {
            assert_eq!(parse_code(bad).unwrap_err(), "not an unlock code", "{bad:?}");
        }
        assert!(parse_code(&"A".repeat(200)).is_err());
        assert_eq!(verify_code(TEST_CODE, "zz").unwrap_err(), "the unlock key is not hex");
        assert_eq!(verify_code(TEST_CODE, "ab").unwrap_err(), "the unlock key is not 32 bytes");
        assert_eq!(hex::decode(UNLOCK_PUBLIC_KEY).expect("hex").len(), 32, "the shop's key is a key");
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
