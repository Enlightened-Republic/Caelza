//! Caelza: the agent dresses itself (vision M10 §10, slice P2).
//!
//! Every agent has a pixel character (vision M8): one piece per layer and
//! one colour per slot, kept on the Runtime as `agents/<alias>/look.json`
//! (api_looks.rs reads and validates the same file for the dashboard). This
//! tool is the agent's own hand on it: `show` what it wears and what the
//! wardrobe holds, `set` pieces and colours, `reset` to the look dealt from
//! its name. The catalog of pieces is `looks/catalog.json`, copied beside this
//! file by `runtime/build.sh` and embedded here, so the tool knows the pieces,
//! the packs and the palettes the dashboard knows.
//!
//! The owner's first yes: `[persona] free` (the Looks page's "Let it be
//! itself" switch). Until it is on, `show` works and `set` / `reset` are
//! refused with the way to ask; after it, the agent changes its look on its
//! own. The switch is read from the config file at each call, so the yes
//! reaches the agent with its next turn, no restart. A piece from a pack the
//! wardrobe does not hold is refused by name.
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use async_trait::async_trait;
use caelza_api::tool::{Tool, ToolOutput, ToolResult};
use caelza_config::schema::Config;
use serde_json::{Map, Value, json};

/// looks/catalog.json, copied here by runtime/build.sh (the one source).
const CATALOG_JSON: &str = include_str!("looks_catalog.json");

pub const LAYERS: [&str; 7] = ["backdrop", "body", "outfit", "hair", "hat", "face", "accessory"];
pub const SLOTS: [&str; 5] = ["skin", "hair", "outfit", "accent", "eyes"];
pub const LOOK_FILE: &str = "look.json";
pub const WARDROBE_FILE: &str = "wardrobe.json";
/// The pack every wardrobe holds.
pub const STARTER: &str = "starter";
/// The words when the owner has not said yes yet.
pub const NOT_FREE: &str = "Your owner has not yet let you shape yourself. Ask them to turn on \"Let it be itself\" on the dashboard's Looks page; after that, this tool acts without asking.";

/// The owner's yes, `[persona] free`, read from the config file when asked so
/// the Looks page's switch reaches the agent at its next call.
#[derive(Debug, Clone)]
pub struct Gate {
    path: Option<PathBuf>,
    fallback: bool,
}

impl Gate {
    pub fn new(config: &Config) -> Self {
        Self { path: Some(config.config_path.clone()), fallback: config.persona.free }
    }

    /// A gate that never reads a file (tests, and a Runtime without one).
    pub fn fixed(free: bool) -> Self {
        Self { path: None, fallback: free }
    }

    pub fn is_free(&self) -> bool {
        let Some(path) = &self.path else { return self.fallback };
        // A whole document (`toml::Table`); `str::parse::<toml::Value>` reads one value.
        match std::fs::read_to_string(path).ok().and_then(|t| toml::from_str::<toml::Table>(&t).ok()) {
            Some(doc) => doc
                .get("persona")
                .and_then(|p| p.get("free"))
                .and_then(toml::Value::as_bool)
                .unwrap_or(false),
            None => self.fallback,
        }
    }
}

#[derive(Debug, Clone)]
pub struct Part {
    pub id: String,
    pub layer: String,
    pub name: String,
    pub pack: String,
}

#[derive(Debug, Clone)]
pub struct Pack {
    pub id: String,
    pub name: String,
    /// `price` is not `"free"`: a code opens it (the Shop sells the code).
    pub priced: bool,
    /// `status == "available"`; a pack still coming is not wearable.
    pub available: bool,
}

/// The pack catalog as the tool needs it.
#[derive(Debug)]
pub struct Catalog {
    pub parts: Vec<Part>,
    pub packs: Vec<Pack>,
    pub colors: Map<String, Value>,
}

impl Catalog {
    fn parse(text: &str) -> Catalog {
        let v: Value = serde_json::from_str(text).expect("looks_catalog.json is JSON");
        let parts = v["parts"]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|p| {
                        Some(Part {
                            id: p["id"].as_str()?.to_string(),
                            layer: p["layer"].as_str()?.to_string(),
                            name: p["name"].as_str().unwrap_or("").to_string(),
                            pack: p["pack"].as_str().unwrap_or(STARTER).to_string(),
                        })
                    })
                    .collect()
            })
            .unwrap_or_default();
        let packs = v["packs"]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|p| {
                        Some(Pack {
                            id: p["id"].as_str()?.to_string(),
                            name: p["name"].as_str().unwrap_or("").to_string(),
                            priced: p["price"].as_str() != Some("free"),
                            available: p["status"].as_str().unwrap_or("available") == "available",
                        })
                    })
                    .collect()
            })
            .unwrap_or_default();
        let colors = v["colors"].as_object().cloned().unwrap_or_default();
        Catalog { parts, packs, colors }
    }

    /// The embedded catalog, parsed once.
    pub fn embedded() -> &'static Catalog {
        static CATALOG: OnceLock<Catalog> = OnceLock::new();
        CATALOG.get_or_init(|| Catalog::parse(CATALOG_JSON))
    }

    pub fn part(&self, id: &str) -> Option<&Part> {
        self.parts.iter().find(|p| p.id == id)
    }

    /// The pieces of one layer, in catalog order; `pack` narrows to one pack.
    pub fn parts_for(&self, layer: &str, pack: Option<&str>) -> Vec<&Part> {
        self.parts
            .iter()
            .filter(|p| p.layer == layer && pack.is_none_or(|k| p.pack == k))
            .collect()
    }

    pub fn palette(&self, slot: &str) -> Vec<String> {
        self.colors
            .get(slot)
            .and_then(Value::as_array)
            .map(|a| a.iter().filter_map(Value::as_str).map(str::to_string).collect())
            .unwrap_or_default()
    }

    pub fn pack_name(&self, id: &str) -> String {
        self.packs
            .iter()
            .find(|p| p.id == id)
            .map(|p| p.name.clone())
            .unwrap_or_else(|| id.to_string())
    }
}

/// FNV-1a over UTF-8, 32 bits (parts.py `fnv1a`, looks.logic.ts `fnv1a`).
pub fn fnv1a(text: &str) -> u32 {
    let mut h: u32 = 0x811c9dc5;
    for b in text.bytes() {
        h ^= u32::from(b);
        h = h.wrapping_mul(0x01000193);
    }
    h
}

/// The look dealt from a name (parts.py `default_look`, looks.logic.ts
/// `defaultLook`): Starter pieces and palette colours picked by the hash.
pub fn default_look(alias: &str, catalog: &Catalog) -> Value {
    let h = fnv1a(alias);
    let mut parts = Map::new();
    for (i, layer) in LAYERS.iter().enumerate() {
        let ids = catalog.parts_for(layer, Some(STARTER));
        if ids.is_empty() {
            continue;
        }
        let pick = (h >> (i * 4)) as usize % ids.len();
        parts.insert((*layer).to_string(), Value::String(ids[pick].id.clone()));
    }
    let mut colors = Map::new();
    for (i, slot) in SLOTS.iter().enumerate() {
        let palette = catalog.palette(slot);
        if palette.is_empty() {
            continue;
        }
        let pick = (h >> (i * 3 + 7)) as usize % palette.len();
        colors.insert((*slot).to_string(), Value::String(palette[pick].clone()));
    }
    json!({"version": 1, "parts": parts, "colors": colors})
}

fn is_hex_color(s: &str) -> bool {
    s.len() == 7 && s.starts_with('#') && s[1..].chars().all(|c| c.is_ascii_hexdigit())
}

/// The packs whose pieces the agent may wear (looks.logic.ts `ownedPacks`):
/// Starter always, then the available packs the wardrobe lists, a priced one
/// only when a code opened it (`unlocks[pack]`, which the Runtime remembers).
pub fn owned_packs(wardrobe: Option<&Value>, catalog: &Catalog) -> BTreeSet<String> {
    let mut owned = BTreeSet::from([STARTER.to_string()]);
    let Some(w) = wardrobe else { return owned };
    let listed: BTreeSet<&str> = w
        .get("packs")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .collect();
    for pack in &catalog.packs {
        if !pack.available || !listed.contains(pack.id.as_str()) {
            continue;
        }
        let unlocked = w
            .get("unlocks")
            .and_then(|u| u.get(&pack.id))
            .is_some_and(Value::is_string);
        if pack.priced && !unlocked {
            continue;
        }
        owned.insert(pack.id.clone());
    }
    owned
}

/// `changes` (parts and/or colours) over `base`, checked against the catalog and the wardrobe.
pub fn merge_look(
    base: &Value,
    changes: &Value,
    catalog: &Catalog,
    owned: &BTreeSet<String>,
) -> Result<Value, String> {
    let mut parts = base.get("parts").and_then(Value::as_object).cloned().unwrap_or_default();
    let mut colors = base.get("colors").and_then(Value::as_object).cloned().unwrap_or_default();
    if let Some(p) = changes.get("parts") {
        let p = p.as_object().ok_or("parts must be an object of layer -> piece id")?;
        for (layer, id) in p {
            if !LAYERS.contains(&layer.as_str()) {
                return Err(format!("`{layer}` is not a layer; the layers are {}", LAYERS.join(", ")));
            }
            let id = id.as_str().ok_or_else(|| format!("parts.{layer} must be a piece id"))?;
            let part = catalog.part(id).ok_or_else(|| {
                format!("`{id}` is not a piece in the catalog; `show` lists the pieces of each layer")
            })?;
            if part.layer != *layer {
                return Err(format!("`{id}` is a {} piece, not a {layer}", part.layer));
            }
            if !owned.contains(&part.pack) {
                return Err(format!(
                    "`{id}` comes with the {} pack, which is not in the wardrobe; the owner adds packs in the Shop",
                    catalog.pack_name(&part.pack)
                ));
            }
            parts.insert(layer.clone(), Value::String(id.to_string()));
        }
    }
    if let Some(c) = changes.get("colors") {
        let c = c.as_object().ok_or("colors must be an object of slot -> #rrggbb")?;
        for (slot, hex) in c {
            if !SLOTS.contains(&slot.as_str()) {
                return Err(format!("`{slot}` is not a colour slot; the slots are {}", SLOTS.join(", ")));
            }
            let hex = hex.as_str().ok_or_else(|| format!("colors.{slot} must be #rrggbb"))?;
            if !is_hex_color(hex) {
                return Err(format!("colors.{slot}: `{hex}` is not #rrggbb"));
            }
            colors.insert(slot.clone(), Value::String(hex.to_ascii_lowercase()));
        }
    }
    for layer in LAYERS {
        if !parts.contains_key(layer) {
            return Err(format!("parts.{layer} is missing"));
        }
    }
    for slot in SLOTS {
        if !colors.contains_key(slot) {
            return Err(format!("colors.{slot} is missing"));
        }
    }
    Ok(json!({"version": 1, "parts": parts, "colors": colors}))
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

pub struct LookTool {
    alias: String,
    root: PathBuf,
    gate: Gate,
}

impl LookTool {
    pub fn new(config: &Config, alias: &str) -> Self {
        Self::from_parts(alias, config.install_root_dir(), Gate::new(config))
    }

    pub fn from_parts(alias: &str, root: PathBuf, gate: Gate) -> Self {
        Self { alias: alias.to_string(), root, gate }
    }

    fn look_path(&self) -> PathBuf {
        self.root.join("agents").join(&self.alias).join(LOOK_FILE)
    }

    fn wardrobe_path(&self) -> PathBuf {
        self.root.join("looks").join(WARDROBE_FILE)
    }

    fn owned(&self, catalog: &Catalog) -> BTreeSet<String> {
        owned_packs(read_json(&self.wardrobe_path()).as_ref(), catalog)
    }

    /// The saved look, else the one dealt from the alias.
    fn current(&self, catalog: &Catalog) -> (Value, bool) {
        match read_json(&self.look_path()) {
            Some(v) if v.get("parts").is_some() => (v, true),
            _ => (default_look(&self.alias, catalog), false),
        }
    }

    fn show(&self, catalog: &Catalog, free: bool) -> Value {
        let (look, saved) = self.current(catalog);
        let owned = self.owned(catalog);
        let mut pieces = Map::new();
        for layer in LAYERS {
            let list: Vec<Value> = catalog
                .parts_for(layer, None)
                .into_iter()
                .map(|p| json!({"id": p.id, "name": p.name, "pack": p.pack, "owned": owned.contains(&p.pack)}))
                .collect();
            pieces.insert(layer.to_string(), Value::Array(list));
        }
        let mut palettes = Map::new();
        for slot in SLOTS {
            palettes.insert(slot.to_string(), json!(catalog.palette(slot)));
        }
        let locked: Vec<String> =
            catalog.packs.iter().filter(|p| !owned.contains(&p.id)).map(|p| p.id.clone()).collect();
        json!({
            "saved": saved,
            "look": look,
            "wardrobe": {"owned": owned, "locked": locked},
            "pieces": pieces,
            "palettes": palettes,
            "free": free,
            "how": if free {
                "Call `set` with the layers and slots you want to change; any colour is #rrggbb, the palettes are suggestions. `reset` returns to the look dealt from your name."
            } else {
                NOT_FREE
            }
        })
    }
}

#[async_trait]
impl Tool for LookTool {
    fn name(&self) -> &str {
        "look"
    }

    fn description(&self) -> &str {
        "Your own look: the pixel character people see beside your words. `show` tells you what you \
         wear now, every piece the wardrobe holds for each layer (backdrop, body, outfit, hair, hat, \
         face, accessory), the colour slots (skin, hair, outfit, accent, eyes) and their palettes. \
         `set {parts: {layer: piece_id}, colors: {slot: \"#rrggbb\"}}` changes any of them; `reset` \
         returns to the look dealt from your name. You decide how you look once your owner has \
         said yes (the Looks page's \"Let it be itself\"); until then, `show` and ask."
    }

    fn parameters_schema(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "action": { "type": "string", "enum": ["show", "set", "reset"], "description": "show what you wear and can wear; set pieces and colours; reset to the dealt look." },
                "parts": { "type": "object", "description": "set: layer -> piece id, for the layers you change (from `show`)." },
                "colors": { "type": "object", "description": "set: slot -> #rrggbb, for the slots you change." }
            },
            "required": ["action"],
            "additionalProperties": false
        })
    }

    async fn execute(&self, args: Value) -> anyhow::Result<ToolResult> {
        let catalog = Catalog::embedded();
        let action = args.get("action").and_then(Value::as_str).unwrap_or("").trim();
        let free = self.gate.is_free();
        match action {
            "show" => Ok(ToolResult::ok(ToolOutput::json(self.show(catalog, free)))),
            "set" => {
                if !free {
                    return Ok(ToolResult::err(NOT_FREE));
                }
                if args.get("parts").is_none() && args.get("colors").is_none() {
                    return Ok(ToolResult::err("`set` needs `parts`, `colors` or both; `show` lists what there is."));
                }
                let (base, _) = self.current(catalog);
                let look = match merge_look(&base, &args, catalog, &self.owned(catalog)) {
                    Ok(l) => l,
                    Err(e) => return Ok(ToolResult::err(e)),
                };
                match write_json(&self.look_path(), &look) {
                    Ok(()) => Ok(ToolResult::ok(ToolOutput::json(json!({"saved": true, "look": look})))),
                    Err(e) => Ok(ToolResult::err(format!("could not save the look: {e}"))),
                }
            }
            "reset" => {
                if !free {
                    return Ok(ToolResult::err(NOT_FREE));
                }
                match std::fs::remove_file(self.look_path()) {
                    Ok(()) => {}
                    Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                    Err(e) => return Ok(ToolResult::err(format!("could not reset the look: {e}"))),
                }
                Ok(ToolResult::ok(ToolOutput::json(
                    json!({"saved": false, "look": default_look(&self.alias, catalog)}),
                )))
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
            .join(format!("caelza-look-{}-{}", std::process::id(), N.fetch_add(1, Ordering::Relaxed)));
        std::fs::create_dir_all(&root).unwrap();
        root
    }

    fn tool(free: bool) -> (LookTool, PathBuf) {
        let root = root();
        (LookTool::from_parts("main", root.clone(), Gate::fixed(free)), root)
    }

    fn data(r: &ToolResult) -> Value {
        r.output.data().cloned().expect("json output")
    }

    #[test]
    fn the_catalog_is_embedded_and_the_dealt_look_is_the_dashboards() {
        let c = Catalog::embedded();
        assert!(c.parts.len() >= 40 && c.packs.iter().any(|p| p.id == STARTER));
        for layer in LAYERS {
            assert!(!c.parts_for(layer, Some(STARTER)).is_empty(), "{layer} has a starter piece");
        }
        for slot in SLOTS {
            assert!(!c.palette(slot).is_empty(), "{slot} has a palette");
        }
        // The same hash as looks.logic.ts / parts.py.
        assert_eq!(fnv1a(""), 0x811c9dc5);
        assert_eq!(fnv1a("a"), 0xe40c292c);
        let look = default_look("main", c);
        for layer in LAYERS {
            let id = look["parts"][layer].as_str().unwrap();
            assert_eq!(c.part(id).unwrap().pack, STARTER);
        }
        for slot in SLOTS {
            assert!(is_hex_color(look["colors"][slot].as_str().unwrap()));
        }
        assert_eq!(default_look("main", c), default_look("main", c));
        assert_ne!(default_look("main", c), default_look("main2", c));
    }

    #[test]
    fn the_gate_reads_the_config_file_each_time() {
        let root = root();
        let path = root.join("config.toml");
        std::fs::write(&path, "[agent]\nname = \"x\"\n").unwrap();
        let gate = Gate { path: Some(path.clone()), fallback: true };
        assert!(!gate.is_free(), "no [persona] means no");
        std::fs::write(&path, "[persona]\nfree = true\n").unwrap();
        assert!(gate.is_free());
        std::fs::write(&path, "[persona]\nfree = false\n").unwrap();
        assert!(!gate.is_free());
        std::fs::remove_file(&path).unwrap();
        assert!(gate.is_free(), "no file: the value the Runtime loaded with");
        assert!(Gate::fixed(true).is_free() && !Gate::fixed(false).is_free());
    }

    #[tokio::test]
    async fn show_works_before_the_yes_and_set_waits_for_it() {
        let (t, _root) = tool(false);
        let shown = t.execute(json!({"action": "show"})).await.unwrap();
        assert!(shown.success);
        let d = data(&shown);
        assert_eq!(d["saved"], false);
        assert_eq!(d["free"], false);
        assert!(d["pieces"]["backdrop"].as_array().unwrap().iter().any(|p| p["id"] == "backdrop.none"));
        assert_eq!(d["how"], NOT_FREE);
        let set = t.execute(json!({"action": "set", "colors": {"hair": "#112233"}})).await.unwrap();
        assert!(!set.success);
        assert!(set.error.as_deref().unwrap().contains("Let it be itself"));
        let reset = t.execute(json!({"action": "reset"})).await.unwrap();
        assert!(!reset.success);
    }

    #[tokio::test]
    async fn set_merges_over_the_dealt_look_and_refuses_what_the_wardrobe_lacks() {
        let (t, root) = tool(true);
        let c = Catalog::embedded();
        let dealt = default_look("main", c);
        let hair = c
            .parts_for("hair", Some(STARTER))
            .into_iter()
            .map(|p| p.id.clone())
            .find(|id| id != dealt["parts"]["hair"].as_str().unwrap())
            .unwrap();
        let r = t
            .execute(json!({"action": "set", "parts": {"hair": hair}, "colors": {"eyes": "#ABCDEF"}}))
            .await
            .unwrap();
        assert!(r.success, "{:?}", r.error);
        let saved: Value =
            serde_json::from_str(&std::fs::read_to_string(root.join("agents/main/look.json")).unwrap()).unwrap();
        assert_eq!(saved["parts"]["hair"], hair);
        assert_eq!(saved["colors"]["eyes"], "#abcdef");
        assert_eq!(saved["version"], 1);
        for layer in LAYERS {
            assert!(saved["parts"][layer].is_string(), "{layer} filled from the dealt look");
        }
        assert_eq!(saved["parts"]["body"], dealt["parts"]["body"]);
        // A priced pack's piece, by name; owned once the wardrobe lists the pack and a code opened it.
        let locked = c.parts.iter().find(|p| c.packs.iter().any(|k| k.id == p.pack && k.priced)).unwrap();
        let r = t.execute(json!({"action": "set", "parts": {locked.layer.clone(): locked.id.clone()}})).await.unwrap();
        assert!(!r.success);
        assert!(r.error.as_deref().unwrap().contains("not in the wardrobe"));
        write_json(
            &root.join("looks/wardrobe.json"),
            &json!({"version": 1, "packs": [locked.pack.clone()], "unlocks": {}}),
        )
        .unwrap();
        let r = t.execute(json!({"action": "set", "parts": {locked.layer.clone(): locked.id.clone()}})).await.unwrap();
        assert!(!r.success, "listed but never unlocked");
        write_json(
            &root.join("looks/wardrobe.json"),
            &json!({"version": 1, "packs": [locked.pack.clone()], "unlocks": {locked.pack.clone(): "code_1"}}),
        )
        .unwrap();
        let r = t.execute(json!({"action": "set", "parts": {locked.layer.clone(): locked.id.clone()}})).await.unwrap();
        assert!(r.success, "{:?}", r.error);
        // Shapes the gateway would refuse are refused here too.
        for bad in [
            json!({"action": "set", "parts": {"hair": "hat.none"}}),
            json!({"action": "set", "parts": {"wings": "hair.swoop"}}),
            json!({"action": "set", "parts": {"hair": "hair.nope"}}),
            json!({"action": "set", "colors": {"eyes": "blue"}}),
            json!({"action": "set", "colors": {"mood": "#112233"}}),
            json!({"action": "set"}),
            json!({"action": "dance"}),
            json!({}),
        ] {
            let r = t.execute(bad.clone()).await.unwrap();
            assert!(!r.success, "{bad}");
        }
        let shown = t.execute(json!({"action": "show"})).await.unwrap();
        let d = data(&shown);
        assert_eq!(d["saved"], true);
        assert!(d["wardrobe"]["owned"].as_array().unwrap().iter().any(|p| p == &json!(locked.pack)));
        let reset = t.execute(json!({"action": "reset"})).await.unwrap();
        assert!(reset.success);
        assert!(!root.join("agents/main/look.json").exists());
        assert_eq!(data(&reset)["look"], dealt);
    }

    #[test]
    fn owned_packs_follows_the_dashboards_rule() {
        let c = Catalog::embedded();
        let free_pack = c.packs.iter().find(|p| !p.priced && p.id != STARTER).unwrap();
        let priced = c.packs.iter().find(|p| p.priced).unwrap();
        assert_eq!(owned_packs(None, c).len(), 1);
        let w = json!({"version": 1, "packs": [free_pack.id, priced.id, "nope"], "unlocks": {}});
        let owned = owned_packs(Some(&w), c);
        assert!(owned.contains(STARTER) && owned.contains(&free_pack.id));
        assert!(!owned.contains(&priced.id) && !owned.contains("nope"));
        let w = json!({"version": 1, "packs": [priced.id], "unlocks": {priced.id.clone(): "code_9"}});
        assert!(owned_packs(Some(&w), c).contains(&priced.id));
    }
}
