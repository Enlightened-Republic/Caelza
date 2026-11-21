//! Caelza: the agent finds its voice (vision M10 §10, slice P2b).
//!
//! A voice is how the agent's replies sound when a device reads them aloud:
//! a browser voice (the PC dashboard's speech synthesis), a phone voice (the
//! Caelza app's text-to-speech engine) or an ElevenLabs voice (fetched from
//! the Runtime with the owner's key; those work on every device). The choice
//! is `agents/<alias>/voice.json`; the voices on offer are
//! `<install root>/voices.json`, which the devices report to the gateway
//! (`POST /api/voice/offer`) and the gateway fills for ElevenLabs when a key
//! is set (`GET /api/voice/elevenlabs`). api_voice.rs serves both files and
//! uses the same checks as this tool, so the dashboard and the agent agree.
//!
//! The owner's first yes: `[persona] free` (the Looks page's "Let it be
//! itself" switch, read through `look::Gate` at each call). Until it is on,
//! `show` works and `set` / `reset` are refused with the way to ask.
use std::path::{Path, PathBuf};

use async_trait::async_trait;
use caelza_api::tool::{Tool, ToolOutput, ToolResult};
use caelza_config::schema::Config;
use serde_json::{Map, Value, json};

pub use crate::look::{Gate, NOT_FREE};

/// `agents/<alias>/voice.json`.
pub const VOICE_FILE: &str = "voice.json";
/// `<install root>/voices.json`: what the devices offered.
pub const OFFERED_FILE: &str = "voices.json";
pub const ENGINES: [&str; 3] = ["browser", "phone", "elevenlabs"];
pub const MAX_ID_CHARS: usize = 120;
pub const MAX_NAME_CHARS: usize = 120;
pub const MAX_WHY_CHARS: usize = 280;
pub const MAX_OFFERED: usize = 200;
/// Speed and pitch, as the browsers take them (1 is the voice as it comes).
pub const RATE_RANGE: (f64, f64) = (0.5, 2.0);
pub const PITCH_RANGE: (f64, f64) = (0.5, 2.0);

pub fn voice_path(root: &Path, alias: &str) -> PathBuf {
    root.join("agents").join(alias).join(VOICE_FILE)
}

pub fn offered_path(root: &Path) -> PathBuf {
    root.join(OFFERED_FILE)
}

/// A voice id or name: one line of printable text, bounded.
pub fn text_ok(s: &str, max: usize) -> bool {
    let n = s.chars().count();
    n >= 1 && n <= max && !s.chars().any(char::is_control)
}

fn number_in(v: Option<&Value>, field: &str, range: (f64, f64)) -> Result<Option<f64>, String> {
    match v {
        None | Some(Value::Null) => Ok(None),
        Some(x) => {
            let f = x.as_f64().ok_or_else(|| format!("{field} must be a number"))?;
            if !(range.0..=range.1).contains(&f) {
                return Err(format!("{field} must be between {} and {}", range.0, range.1));
            }
            Ok(Some((f * 100.0).round() / 100.0))
        }
    }
}

/// `{version: 1, engine, voice, name?, rate?, pitch?, why?}`, checked and tidied.
pub fn validate_voice(body: &Value) -> Result<Value, String> {
    let obj = body.as_object().ok_or("a voice is an object")?;
    let engine = obj.get("engine").and_then(Value::as_str).map(str::trim).unwrap_or("");
    if !ENGINES.contains(&engine) {
        return Err(format!("engine must be one of {}", ENGINES.join(", ")));
    }
    let voice = obj.get("voice").and_then(Value::as_str).map(str::trim).unwrap_or("");
    if !text_ok(voice, MAX_ID_CHARS) {
        return Err(format!("voice must be the voice's id, 1 to {MAX_ID_CHARS} characters"));
    }
    if engine == "elevenlabs" && !voice.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
        return Err("an ElevenLabs voice id is letters, digits, - and _".to_string());
    }
    let mut out = Map::new();
    out.insert("version".into(), json!(1));
    out.insert("engine".into(), Value::String(engine.to_string()));
    out.insert("voice".into(), Value::String(voice.to_string()));
    if let Some(name) = obj.get("name").and_then(Value::as_str).map(str::trim).filter(|s| !s.is_empty()) {
        if !text_ok(name, MAX_NAME_CHARS) {
            return Err(format!("name is at most {MAX_NAME_CHARS} characters, one line"));
        }
        out.insert("name".into(), Value::String(name.to_string()));
    }
    if let Some(rate) = number_in(obj.get("rate"), "rate", RATE_RANGE)? {
        out.insert("rate".into(), json!(rate));
    }
    if let Some(pitch) = number_in(obj.get("pitch"), "pitch", PITCH_RANGE)? {
        out.insert("pitch".into(), json!(pitch));
    }
    if let Some(why) = obj.get("why").and_then(Value::as_str).map(str::trim).filter(|s| !s.is_empty()) {
        if why.chars().count() > MAX_WHY_CHARS || why.chars().any(|c| c.is_control() && c != '\n') {
            return Err(format!("why is at most {MAX_WHY_CHARS} characters"));
        }
        out.insert("why".into(), Value::String(why.to_string()));
    }
    Ok(Value::Object(out))
}

/// The voices one engine offered (`engines.<engine>.voices`), as the file has them.
pub fn offered_voices(offered: &Value, engine: &str) -> Vec<Value> {
    offered
        .get("engines")
        .and_then(|e| e.get(engine))
        .and_then(|e| e.get("voices"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

/// A device's offer, tidied: `{id, name, lang?}` each, at most MAX_OFFERED, ids once.
pub fn tidy_offer(voices: &Value) -> Result<Vec<Value>, String> {
    let list = voices.as_array().ok_or("voices must be a list")?;
    let mut seen = std::collections::BTreeSet::new();
    let mut out = Vec::new();
    for v in list {
        let id = v.get("id").and_then(Value::as_str).map(str::trim).unwrap_or("");
        if !text_ok(id, MAX_ID_CHARS) {
            return Err(format!("a voice id is 1 to {MAX_ID_CHARS} characters"));
        }
        if !seen.insert(id.to_string()) {
            continue;
        }
        let name = v.get("name").and_then(Value::as_str).map(str::trim).filter(|s| text_ok(s, MAX_NAME_CHARS)).unwrap_or(id);
        let mut entry = Map::new();
        entry.insert("id".into(), Value::String(id.to_string()));
        entry.insert("name".into(), Value::String(name.to_string()));
        if let Some(lang) = v.get("lang").and_then(Value::as_str).map(str::trim).filter(|s| text_ok(s, 35)) {
            entry.insert("lang".into(), Value::String(lang.to_string()));
        }
        for extra in ["gender", "accent", "age", "description"] {
            if let Some(x) = v.get(extra).and_then(Value::as_str).map(str::trim).filter(|s| text_ok(s, MAX_NAME_CHARS)) {
                entry.insert(extra.into(), Value::String(x.to_string()));
            }
        }
        out.push(Value::Object(entry));
        if out.len() >= MAX_OFFERED {
            break;
        }
    }
    Ok(out)
}

/// The chosen voice must be one its engine offered, when that engine offered
/// any; the entry's name fills `name` when the choice has none.
pub fn check_offered(choice: &mut Value, offered: &Value) -> Result<(), String> {
    let engine = choice["engine"].as_str().unwrap_or("").to_string();
    let id = choice["voice"].as_str().unwrap_or("").to_string();
    let list = offered_voices(offered, &engine);
    if list.is_empty() {
        return Ok(());
    }
    match list.iter().find(|v| v["id"].as_str() == Some(id.as_str())) {
        Some(entry) => {
            if choice.get("name").is_none()
                && let Some(name) = entry["name"].as_str()
            {
                choice["name"] = Value::String(name.to_string());
            }
            Ok(())
        }
        None => {
            let some: Vec<String> = list
                .iter()
                .take(8)
                .filter_map(|v| v["id"].as_str().map(|s| format!("`{s}`")))
                .collect();
            Err(format!(
                "`{id}` is not a {engine} voice on offer; `show` lists them (for example {})",
                some.join(", ")
            ))
        }
    }
}

fn read_json(path: &Path) -> Option<Value> {
    let text = std::fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok()
}

fn write_json(path: &Path, value: &Value) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, serde_json::to_vec_pretty(value)?)?;
    std::fs::rename(tmp, path)
}

pub struct VoiceTool {
    alias: String,
    root: PathBuf,
    gate: Gate,
    /// The owner added an ElevenLabs key (read when the tool was built).
    elevenlabs: bool,
}

impl VoiceTool {
    pub fn new(config: &Config, alias: &str) -> Self {
        let elevenlabs = config
            .providers
            .tts
            .elevenlabs
            .values()
            .any(|p| p.base.api_key.as_deref().is_some_and(|k| !k.trim().is_empty()));
        Self::from_parts(alias, config.install_root_dir(), Gate::new(config), elevenlabs)
    }

    pub fn from_parts(alias: &str, root: PathBuf, gate: Gate, elevenlabs: bool) -> Self {
        Self { alias: alias.to_string(), root, gate, elevenlabs }
    }

    fn offered(&self) -> Value {
        read_json(&offered_path(&self.root)).unwrap_or_else(|| json!({"version": 1, "engines": {}}))
    }

    fn current(&self) -> Option<Value> {
        read_json(&voice_path(&self.root, &self.alias)).filter(|v| v.get("engine").is_some())
    }

    fn show(&self, free: bool) -> Value {
        let offered = self.offered();
        let mut on_offer = Map::new();
        for engine in ENGINES {
            on_offer.insert(engine.to_string(), Value::Array(offered_voices(&offered, engine)));
        }
        let elevenlabs_ready = self.elevenlabs || !offered_voices(&offered, "elevenlabs").is_empty();
        json!({
            "voice": self.current(),
            "offered": on_offer,
            "elevenlabs_key": elevenlabs_ready,
            "free": free,
            "notes": [
                "browser voices are the PC dashboard's and phone voices the Caelza app's: each speaks only where it was offered; an ElevenLabs voice speaks on every device once the owner added a key on the Connect page.",
                "an empty list means no device has offered that engine's voices yet (the dashboard offers them when it opens a chat).",
                if free { "pick with `set {engine, voice, why}`; say in `why`, in a sentence, why that one is you." } else { NOT_FREE }
            ]
        })
    }
}

#[async_trait]
impl Tool for VoiceTool {
    fn name(&self) -> &str {
        "voice"
    }

    fn description(&self) -> &str {
        "Your own voice: how your replies sound when a device reads them aloud. `show` lists the \
         voices on offer by engine (browser: the PC dashboard's; phone: the Caelza app's; elevenlabs: \
         the owner's ElevenLabs voices, which work everywhere) and what you chose. `set {engine, \
         voice, why, rate?, pitch?}` picks one by its id and says why in a sentence; `reset` goes \
         back to the device's own default. You choose once your owner has said yes (the Looks page's \
         \"Let it be itself\"); until then, `show` and ask."
    }

    fn parameters_schema(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "action": { "type": "string", "enum": ["show", "set", "reset"], "description": "show the voices on offer and your choice; set one; reset to the device default." },
                "engine": { "type": "string", "enum": ENGINES, "description": "set: browser, phone or elevenlabs." },
                "voice": { "type": "string", "description": "set: the voice's id, from `show`." },
                "why": { "type": "string", "description": "set: one sentence on why this voice is you (shown to your owner)." },
                "rate": { "type": "number", "description": "set: speed, 0.5 to 2 (1 is as it comes)." },
                "pitch": { "type": "number", "description": "set: pitch, 0.5 to 2 (1 is as it comes)." }
            },
            "required": ["action"],
            "additionalProperties": false
        })
    }

    async fn execute(&self, args: Value) -> anyhow::Result<ToolResult> {
        let action = args.get("action").and_then(Value::as_str).unwrap_or("").trim();
        let free = self.gate.is_free();
        match action {
            "show" => Ok(ToolResult::ok(ToolOutput::json(self.show(free)))),
            "set" => {
                if !free {
                    return Ok(ToolResult::err(NOT_FREE));
                }
                let mut choice = match validate_voice(&args) {
                    Ok(c) => c,
                    Err(e) => return Ok(ToolResult::err(e)),
                };
                if let Err(e) = check_offered(&mut choice, &self.offered()) {
                    return Ok(ToolResult::err(e));
                }
                match write_json(&voice_path(&self.root, &self.alias), &choice) {
                    Ok(()) => Ok(ToolResult::ok(ToolOutput::json(json!({
                        "saved": true,
                        "voice": choice,
                        "note": "the dashboard and the app read replies aloud in it from now on, where the owner turned reading aloud on"
                    })))),
                    Err(e) => Ok(ToolResult::err(format!("could not save the voice: {e}"))),
                }
            }
            "reset" => {
                if !free {
                    return Ok(ToolResult::err(NOT_FREE));
                }
                match std::fs::remove_file(voice_path(&self.root, &self.alias)) {
                    Ok(()) => {}
                    Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                    Err(e) => return Ok(ToolResult::err(format!("could not reset the voice: {e}"))),
                }
                Ok(ToolResult::ok(ToolOutput::json(json!({"saved": false, "voice": Value::Null}))))
            }
            "" => Ok(ToolResult::err("Missing required parameter 'action'")),
            other => Ok(ToolResult::err(format!("`{other}` is not an action; the actions are show, set, reset."))),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static N: AtomicUsize = AtomicUsize::new(0);

    fn root() -> PathBuf {
        let root = std::env::temp_dir()
            .join(format!("caelza-voice-{}-{}", std::process::id(), N.fetch_add(1, Ordering::Relaxed)));
        std::fs::create_dir_all(&root).unwrap();
        root
    }

    fn tool(free: bool) -> (VoiceTool, PathBuf) {
        let root = root();
        (VoiceTool::from_parts("main", root.clone(), Gate::fixed(free), false), root)
    }

    fn data(r: &ToolResult) -> Value {
        r.output.data().cloned().expect("json output")
    }

    fn offer(root: &Path, engine: &str, ids: &[(&str, &str)]) {
        let mut offered = read_json(&offered_path(root)).unwrap_or_else(|| json!({"version": 1, "engines": {}}));
        let voices: Vec<Value> = ids.iter().map(|(id, name)| json!({"id": id, "name": name, "lang": "en-US"})).collect();
        offered["engines"][engine] = json!({"voices": voices, "offered_at": 1, "by": "test"});
        write_json(&offered_path(root), &offered).unwrap();
    }

    #[test]
    fn validate_voice_keeps_the_shape_the_dashboard_writes() {
        let ok = validate_voice(&json!({"engine": "browser", "voice": "Google US English", "rate": 1.1, "pitch": 0.9, "why": "warm and clear", "name": "Google US English"})).unwrap();
        assert_eq!(ok["version"], 1);
        assert_eq!(ok["rate"], 1.1);
        assert_eq!(ok["why"], "warm and clear");
        let minimal = validate_voice(&json!({"engine": "phone", "voice": "en-us-x-iom-local"})).unwrap();
        assert!(minimal.get("rate").is_none() && minimal.get("why").is_none());
        for bad in [
            json!({"engine": "radio", "voice": "x"}),
            json!({"engine": "browser", "voice": ""}),
            json!({"engine": "browser", "voice": "a\u{7}b"}),
            json!({"engine": "elevenlabs", "voice": "not an id!"}),
            json!({"engine": "browser", "voice": "x", "rate": 3}),
            json!({"engine": "browser", "voice": "x", "pitch": "high"}),
            json!({"engine": "browser", "voice": "x", "why": "w".repeat(MAX_WHY_CHARS + 1)}),
            json!(["engine"]),
        ] {
            assert!(validate_voice(&bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn tidy_offer_caps_dedupes_and_keeps_the_useful_labels() {
        let mut many: Vec<Value> = (0..MAX_OFFERED + 20).map(|i| json!({"id": format!("v{i}"), "name": format!("Voice {i}")})).collect();
        many.push(json!({"id": "v1", "name": "again"}));
        let tidy = tidy_offer(&Value::Array(many)).unwrap();
        assert_eq!(tidy.len(), MAX_OFFERED);
        let labelled = tidy_offer(&json!([{"id": "21m00", "name": "Rachel", "lang": "en", "gender": "female", "accent": "american", "age": "young", "description": "calm", "ignored": "x"}])).unwrap();
        assert_eq!(labelled[0]["gender"], "female");
        assert!(labelled[0].get("ignored").is_none());
        assert!(tidy_offer(&json!([{"name": "no id"}])).is_err());
        assert!(tidy_offer(&json!("nope")).is_err());
        let nameless = tidy_offer(&json!([{"id": "only-id"}])).unwrap();
        assert_eq!(nameless[0]["name"], "only-id");
    }

    #[test]
    fn check_offered_holds_the_choice_to_the_list_when_there_is_one() {
        let offered = json!({"version": 1, "engines": {"browser": {"voices": [{"id": "uri:1", "name": "Samantha"}]}}});
        let mut fine = json!({"version": 1, "engine": "browser", "voice": "uri:1"});
        check_offered(&mut fine, &offered).unwrap();
        assert_eq!(fine["name"], "Samantha", "the name fills in from the offer");
        let mut other = json!({"version": 1, "engine": "browser", "voice": "uri:9"});
        let err = check_offered(&mut other, &offered).unwrap_err();
        assert!(err.contains("`uri:1`"));
        // No list for the engine yet: any id passes (the device will say).
        let mut phone = json!({"version": 1, "engine": "phone", "voice": "en-gb-x-gba-local"});
        check_offered(&mut phone, &offered).unwrap();
    }

    #[tokio::test]
    async fn show_works_before_the_yes_and_set_waits_for_it() {
        let (t, _root) = tool(false);
        let shown = t.execute(json!({"action": "show"})).await.unwrap();
        assert!(shown.success);
        let d = data(&shown);
        assert!(d["voice"].is_null());
        assert_eq!(d["free"], false);
        assert_eq!(d["offered"]["browser"], json!([]));
        let set = t.execute(json!({"action": "set", "engine": "browser", "voice": "x"})).await.unwrap();
        assert!(!set.success && set.error.as_deref().unwrap().contains("Let it be itself"));
        assert!(!t.execute(json!({"action": "reset"})).await.unwrap().success);
    }

    #[tokio::test]
    async fn set_picks_from_the_offer_and_reset_forgets() {
        let (t, root) = tool(true);
        offer(&root, "elevenlabs", &[("21m00Tcm4TlvDq8ikWAM", "Rachel"), ("AZnzlk1XvdvUeBnXmlld", "Domi")]);
        let r = t.execute(json!({"action": "set", "engine": "elevenlabs", "voice": "21m00Tcm4TlvDq8ikWAM", "why": "calm and a little dry, like me"})).await.unwrap();
        assert!(r.success, "{:?}", r.error);
        let saved: Value = serde_json::from_str(&std::fs::read_to_string(root.join("agents/main/voice.json")).unwrap()).unwrap();
        assert_eq!(saved["name"], "Rachel");
        assert_eq!(saved["why"], "calm and a little dry, like me");
        let wrong = t.execute(json!({"action": "set", "engine": "elevenlabs", "voice": "nobody"})).await.unwrap();
        assert!(!wrong.success);
        assert!(wrong.error.as_deref().unwrap().contains("`21m00Tcm4TlvDq8ikWAM`"), "{:?}", wrong.error);
        let shown = data(&t.execute(json!({"action": "show"})).await.unwrap());
        assert_eq!(shown["voice"]["voice"], "21m00Tcm4TlvDq8ikWAM");
        assert_eq!(shown["elevenlabs_key"], true, "an offered list counts as a key");
        for bad in [json!({"action": "set"}), json!({"action": "set", "engine": "browser"}), json!({"action": "sing"}), json!({})] {
            assert!(!t.execute(bad.clone()).await.unwrap().success, "{bad}");
        }
        let reset = t.execute(json!({"action": "reset"})).await.unwrap();
        assert!(reset.success);
        assert!(!root.join("agents/main/voice.json").exists());
    }
}
