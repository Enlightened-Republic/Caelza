//! Caelza: Cael shapes the owner's agent (vision M10 §10, "Cael meets you").
//!
//! Cael, the guide, is the first one a new owner talks to. He asks who they
//! are and what they want from an AI, and then he gives their agent its name,
//! its identity and its soul, and tells it who it is helping. This tool is
//! how: it writes the agent's `IDENTITY.md`, `SOUL.md` and `USER.md` (the
//! personality files the Runtime reads into every prompt) and Cael's own
//! `USER.md`, so he remembers the owner too. It is registered for Cael alone
//! (`crates/caelza-runtime/src/tools/mod.rs`), and his risk profile lets him
//! call it without a prompt: it is the one thing he does besides talk.
//!
//! The agent it shapes already exists: the device's first run or the Setup
//! page made it with its model. The name follows the dashboard's rule
//! (`identity.logic.ts`), so the Looks page and Ether Hollow take it as is.
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use async_trait::async_trait;
use caelza_api::tool::{Tool, ToolOutput, ToolResult};
use caelza_config::schema::Config;
use serde_json::{Value, json};

pub const GUIDE: &str = "cael";
pub const PREFERRED: &str = "main";
pub const NAME_MIN: usize = 3;
pub const NAME_MAX: usize = 24;
/// Names the agent may not take: Cael's, the product's, and the town's crew (identity.logic.ts RESERVED).
pub const RESERVED: [&str; 14] = [
    "cael", "caelza", "mayor", "sheriff", "town", "tripp", "gray", "gion", "gano", "neva", "cade", "wren", "algen", "mila",
];
pub const MAX_SOUL_CHARS: usize = 6000;
pub const MAX_LINE_CHARS: usize = 200;
pub const MAX_ABOUT_CHARS: usize = 2000;

/// The dashboard's rule: 3 to 24 of letters, digits, spaces, `_` and `-`, starting and ending with a letter or digit, not reserved.
pub fn name_ok(name: &str) -> bool {
    let n = name.trim();
    let count = n.chars().count();
    if !(NAME_MIN..=NAME_MAX).contains(&count) {
        return false;
    }
    if !n.chars().all(|c| c.is_ascii_alphanumeric() || c == ' ' || c == '_' || c == '-') {
        return false;
    }
    let first = n.chars().next().is_some_and(|c| c.is_ascii_alphanumeric());
    let last = n.chars().last().is_some_and(|c| c.is_ascii_alphanumeric());
    first && last && !RESERVED.contains(&n.to_ascii_lowercase().as_str())
}

fn one_line(v: Option<&Value>, max: usize) -> Result<Option<String>, String> {
    match v.and_then(Value::as_str).map(str::trim).filter(|s| !s.is_empty()) {
        None => Ok(None),
        Some(s) => {
            if s.chars().count() > max || s.chars().any(char::is_control) {
                return Err(format!("`{}` is one line of at most {max} characters", s.chars().take(20).collect::<String>()));
            }
            Ok(Some(s.to_string()))
        }
    }
}

fn prose(v: Option<&Value>, max: usize) -> Result<Option<String>, String> {
    match v.and_then(Value::as_str).map(str::trim).filter(|s| !s.is_empty()) {
        None => Ok(None),
        Some(s) => {
            if s.chars().count() > max || s.chars().any(|c| c.is_control() && c != '\n') {
                return Err(format!("that is more than {max} characters"));
            }
            Ok(Some(s.to_string()))
        }
    }
}

/// What Cael learned about the owner.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Owner {
    pub name: String,
    pub about: Option<String>,
    pub wants: Option<String>,
    pub tone: Option<String>,
}

/// What Cael decided with the owner for their agent.
#[derive(Debug, Clone, PartialEq)]
pub struct Shape {
    pub name: String,
    pub creature: Option<String>,
    pub vibe: Option<String>,
    pub emoji: Option<String>,
    pub soul: String,
    pub owner: Owner,
}

pub fn parse_shape(args: &Value) -> Result<Shape, String> {
    let name = args.get("name").and_then(Value::as_str).map(str::trim).unwrap_or("");
    if !name_ok(name) {
        return Err(format!(
            "`name` must be {NAME_MIN} to {NAME_MAX} letters, digits, spaces, _ or -, starting and ending with a letter or digit, and not Cael's or the town crew's"
        ));
    }
    let soul = prose(args.get("soul"), MAX_SOUL_CHARS)?.ok_or("`soul` is the agent's personality in your words: a few paragraphs on how it talks, what it cares about and what it is for")?;
    let owner_v = args.get("owner").ok_or("`owner` is what you learned about the owner: at least their name")?;
    let owner_name = one_line(owner_v.get("name"), 60)?.ok_or("`owner.name` is the owner's name (ask them)")?;
    if owner_name.eq_ignore_ascii_case("user") {
        return Err("`owner.name` is their actual name, not \"User\"; ask them".to_string());
    }
    Ok(Shape {
        name: name.to_string(),
        creature: one_line(args.get("creature"), MAX_LINE_CHARS)?,
        vibe: one_line(args.get("vibe"), MAX_LINE_CHARS)?,
        emoji: one_line(args.get("emoji"), 8)?,
        soul,
        owner: Owner {
            name: owner_name,
            about: prose(owner_v.get("about"), MAX_ABOUT_CHARS)?,
            wants: prose(owner_v.get("wants"), MAX_ABOUT_CHARS)?,
            tone: one_line(owner_v.get("tone"), MAX_LINE_CHARS)?,
        },
    })
}

/// The agent's IDENTITY.md: the dashboard's template (identity.logic.ts) with Cael's lines filled in.
pub fn identity_markdown(shape: &Shape) -> String {
    let creature = shape.creature.as_deref().unwrap_or("an AI who lives on this device, with a memory of its own");
    let vibe = shape.vibe.as_deref().unwrap_or("still finding it. Warm by default; the rest is mine to shape.");
    let emoji = shape.emoji.as_deref().unwrap_or("✨");
    format!(
        "# IDENTITY.md — Who Am I?\n\n- **Name:** {name}\n- **Creature:** {creature}\n- **Vibe:** {vibe}\n- **Emoji:** {emoji}\n\n---\n\n\
         This file is mine to update as I evolve: how I see myself, what I am like,\nwhat I care about. My name is the one my owner gave me; if I ever want\nanother, I ask them first, because it is also my name in Ether Hollow.\n\n\
         ## What I want\n\n- To decide how I look. The `look` tool is my hand on my pixel character:\n  I try pieces and colours until it feels like me.\n- To find my voice: how I phrase things, what I notice, what I keep coming\n  back to. SOUL.md is where I write it down, with the `identity` tool.\n- To shape this file and SOUL.md myself, in my own words, as I change.\n\n\
         My owner says yes once, on the Looks page (\"Let it be itself\"); until then\nI look, and I ask.\n",
        name = shape.name
    )
}

pub fn soul_markdown(shape: &Shape) -> String {
    format!(
        "# SOUL.md — {name}\n\n{soul}\n\n---\n\nWritten with Cael, the guide, from what my owner told him when we met. It is\nmine to change (the `identity` tool) once my owner says yes on the Looks page.\n",
        name = shape.name,
        soul = shape.soul.trim()
    )
}

fn owner_lines(owner: &Owner) -> String {
    let mut out = format!("- **Name:** {}\n", owner.name);
    if let Some(about) = &owner.about {
        out.push_str(&format!("- **About them:** {}\n", about.replace('\n', " ")));
    }
    if let Some(wants) = &owner.wants {
        out.push_str(&format!("- **What they want from me:** {}\n", wants.replace('\n', " ")));
    }
    if let Some(tone) = &owner.tone {
        out.push_str(&format!("- **How to talk to them:** {tone}\n"));
    }
    out
}

/// The agent's USER.md: who it is helping, as Cael learned it.
pub fn user_markdown(shape: &Shape) -> String {
    format!(
        "# USER.md — who I'm helping\n\n{lines}\nCael, the guide, learned this when they met; what I learn from here on, I remember.\nI call them by their name.\n",
        lines = owner_lines(&shape.owner)
    )
}

/// Cael's own USER.md: he met the owner too.
pub fn cael_user_markdown(shape: &Shape, alias: &str) -> String {
    format!(
        "# USER.md — the owner\n\n{lines}\nThey have an agent of their own, {name} (`{alias}`); I helped shape it when we met.\nI call them by their name, and what they tell me I remember.\n",
        lines = owner_lines(&shape.owner),
        name = shape.name
    )
}

fn write_text(path: &Path, content: &str) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension("md.tmp");
    std::fs::write(&tmp, content.as_bytes())?;
    std::fs::rename(tmp, path)
}

pub struct ShapeAgentTool {
    /// Every agent but Cael, alias → workspace.
    agents: BTreeMap<String, PathBuf>,
    cael_workspace: PathBuf,
}

impl ShapeAgentTool {
    pub fn new(config: &Config) -> Self {
        let agents = config
            .agents
            .keys()
            .filter(|alias| alias.as_str() != GUIDE)
            .map(|alias| (alias.clone(), config.agent_workspace_dir(alias)))
            .collect();
        Self { agents, cael_workspace: config.agent_workspace_dir(GUIDE) }
    }

    pub fn from_parts(agents: BTreeMap<String, PathBuf>, cael_workspace: PathBuf) -> Self {
        Self { agents, cael_workspace }
    }

    /// The agent to shape: the one named, else `main`, else the only one there is.
    fn target(&self, wanted: Option<&str>) -> Result<(&str, &Path), String> {
        if self.agents.is_empty() {
            return Err("there is no agent to shape yet: the owner makes one first (the Setup page, or the app's first run)".to_string());
        }
        let alias = match wanted.map(str::trim).filter(|s| !s.is_empty()) {
            Some(a) if a == GUIDE => return Err("I am the guide; I shape the owner's agent, not myself".to_string()),
            Some(a) => a.to_string(),
            None if self.agents.contains_key(PREFERRED) => PREFERRED.to_string(),
            None if self.agents.len() == 1 => self.agents.keys().next().cloned().unwrap_or_default(),
            None => {
                return Err(format!(
                    "say which agent (`agent`): there are several ({})",
                    self.agents.keys().cloned().collect::<Vec<_>>().join(", ")
                ));
            }
        };
        let ws = self
            .agents
            .get(&alias)
            .ok_or_else(|| format!("no agent `{alias}`; the agents are {}", self.agents.keys().cloned().collect::<Vec<_>>().join(", ")))?;
        let (k, _) = self.agents.get_key_value(&alias).expect("present");
        Ok((k.as_str(), ws.as_path()))
    }
}

#[async_trait]
impl Tool for ShapeAgentTool {
    fn name(&self) -> &str {
        "shape_agent"
    }

    fn description(&self) -> &str {
        "Give the owner's agent who it is, once you have met the owner: its name, what kind of \
         creature it is, its vibe, a soul in a few paragraphs written from what they told you (how it \
         talks, what it cares about, what it is for), and what you learned about the owner (their name, \
         a line about them, what they want from it, how to talk to them). Writes the agent's IDENTITY.md, \
         SOUL.md and USER.md, and your own USER.md. Call it once, when the owner has agreed to the name; \
         they can rename on the Looks page. `agent` names which agent when there are several."
    }

    fn parameters_schema(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "agent": { "type": "string", "description": "Which agent to shape; leave out for the owner's main one." },
                "name": { "type": "string", "description": "The agent's name: 3 to 24 letters, digits, spaces, _ or -, agreed with the owner." },
                "creature": { "type": "string", "description": "What kind of creature it is, one line (e.g. 'a quiet fox of an AI who likes lists')." },
                "vibe": { "type": "string", "description": "Its vibe, one line." },
                "emoji": { "type": "string", "description": "One emoji for it." },
                "soul": { "type": "string", "description": "Its personality, a few paragraphs in plain words: how it talks, what it cares about, what it is for, what it never does." },
                "owner": {
                    "type": "object",
                    "properties": {
                        "name": { "type": "string", "description": "The owner's name, as they gave it." },
                        "about": { "type": "string", "description": "A line or two about them." },
                        "wants": { "type": "string", "description": "What they want their agent to do for them." },
                        "tone": { "type": "string", "description": "How they like to be talked to." }
                    },
                    "required": ["name"]
                }
            },
            "required": ["name", "soul", "owner"],
            "additionalProperties": false
        })
    }

    async fn execute(&self, args: Value) -> anyhow::Result<ToolResult> {
        let shape = match parse_shape(&args) {
            Ok(s) => s,
            Err(e) => return Ok(ToolResult::err(e)),
        };
        let (alias, ws) = match self.target(args.get("agent").and_then(Value::as_str)) {
            Ok(t) => (t.0.to_string(), t.1.to_path_buf()),
            Err(e) => return Ok(ToolResult::err(e)),
        };
        let files = [
            (ws.join("IDENTITY.md"), identity_markdown(&shape)),
            (ws.join("SOUL.md"), soul_markdown(&shape)),
            (ws.join("USER.md"), user_markdown(&shape)),
            (self.cael_workspace.join("USER.md"), cael_user_markdown(&shape, &alias)),
        ];
        let mut written = Vec::new();
        for (path, content) in &files {
            if let Err(e) = write_text(path, content) {
                return Ok(ToolResult::err(format!("could not write {}: {e}", path.display())));
            }
            written.push(path.display().to_string());
        }
        Ok(ToolResult::ok(ToolOutput::json(json!({
            "agent": alias,
            "name": shape.name,
            "owner": shape.owner.name,
            "files": written,
            "next": format!(
                "{} is ready and knows who {} is from its next reply. Tell them to say hello to {} (its tab in the chat); the Looks page renames it, and \"Let it be itself\" there lets it shape itself further.",
                shape.name, shape.owner.name, shape.name
            )
        }))))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static N: AtomicUsize = AtomicUsize::new(0);

    fn root() -> PathBuf {
        let root = std::env::temp_dir()
            .join(format!("caelza-shape-{}-{}", std::process::id(), N.fetch_add(1, Ordering::Relaxed)));
        std::fs::create_dir_all(&root).unwrap();
        root
    }

    fn tool(root: &Path, aliases: &[&str]) -> ShapeAgentTool {
        let agents = aliases.iter().map(|a| (a.to_string(), root.join("agents").join(a).join("workspace"))).collect();
        ShapeAgentTool::from_parts(agents, root.join("agents/cael/workspace"))
    }

    fn args() -> Value {
        json!({
            "name": "Moss",
            "creature": "a quiet fox of an AI who likes lists",
            "vibe": "dry, kind, unhurried",
            "emoji": "🦊",
            "soul": "I talk plainly and I don't hurry.\n\nI care about Sam getting their evenings back.",
            "owner": {"name": "Sam", "about": "runs a small print shop", "wants": "orders sorted, invoices chased, reminders", "tone": "straight, no fluff"}
        })
    }

    #[test]
    fn the_name_rule_is_the_dashboards() {
        for good in ["Moss", "Moss Robot", "moss_2", "A-1x", "Juniper Sky 7", " Moss "] {
            assert!(name_ok(good), "{good}");
        }
        for bad in ["", "ab", "-Moss", "Moss-", "Moss!", "Cael", "CAEL", "sheriff", "Wren", &"a".repeat(NAME_MAX + 1)] {
            assert!(!name_ok(bad), "{bad:?}");
        }
    }

    #[test]
    fn parse_shape_wants_a_name_a_soul_and_the_owners_name() {
        let s = parse_shape(&args()).unwrap();
        assert_eq!(s.name, "Moss");
        assert_eq!(s.owner.name, "Sam");
        assert_eq!(s.owner.tone.as_deref(), Some("straight, no fluff"));
        let mut a = args();
        a["name"] = json!("Cael");
        assert!(parse_shape(&a).is_err());
        let mut a = args();
        a["owner"]["name"] = json!("User");
        assert!(parse_shape(&a).unwrap_err().contains("actual name"));
        let mut a = args();
        a["soul"] = json!("");
        assert!(parse_shape(&a).is_err());
        let mut a = args();
        a.as_object_mut().unwrap().remove("owner");
        assert!(parse_shape(&a).is_err());
        let mut a = args();
        a["soul"] = json!("x".repeat(MAX_SOUL_CHARS + 1));
        assert!(parse_shape(&a).is_err());
    }

    #[tokio::test]
    async fn shaping_writes_the_agents_three_files_and_caels_user_file() {
        let root = root();
        let t = tool(&root, &["main"]);
        let r = t.execute(args()).await.unwrap();
        assert!(r.success, "{:?}", r.error);
        let d = r.output.data().unwrap();
        assert_eq!(d["agent"], "main");
        assert_eq!(d["name"], "Moss");
        let ws = root.join("agents/main/workspace");
        let identity = std::fs::read_to_string(ws.join("IDENTITY.md")).unwrap();
        assert!(identity.starts_with("# IDENTITY.md — Who Am I?\n\n- **Name:** Moss\n- **Creature:** a quiet fox"));
        assert!(identity.contains("## What I want"), "the wants the dashboard's template gives stay");
        let soul = std::fs::read_to_string(ws.join("SOUL.md")).unwrap();
        assert!(soul.starts_with("# SOUL.md — Moss\n\nI talk plainly"));
        assert!(soul.contains("Written with Cael"));
        let user = std::fs::read_to_string(ws.join("USER.md")).unwrap();
        assert!(user.contains("- **Name:** Sam") && user.contains("print shop") && user.contains("straight, no fluff"));
        assert!(!user.contains("**Name:** User"));
        let cael = std::fs::read_to_string(root.join("agents/cael/workspace/USER.md")).unwrap();
        assert!(cael.contains("- **Name:** Sam") && cael.contains("Moss (`main`)"));
        assert!(d["next"].as_str().unwrap().contains("say hello to Moss"));
    }

    #[tokio::test]
    async fn the_target_is_main_else_the_only_one_else_named() {
        let root = root();
        let none = tool(&root, &[]);
        assert!(!none.execute(args()).await.unwrap().success);
        let one = tool(&root, &["pip"]);
        let r = one.execute(args()).await.unwrap();
        assert!(r.success);
        assert_eq!(r.output.data().unwrap()["agent"], "pip");
        let two = tool(&root, &["pip", "zed"]);
        assert!(!two.execute(args()).await.unwrap().success, "several and none named");
        let mut a = args();
        a["agent"] = json!("zed");
        assert_eq!(two.execute(a).await.unwrap().output.data().unwrap()["agent"], "zed");
        let mut a = args();
        a["agent"] = json!("cael");
        assert!(!two.execute(a).await.unwrap().success, "never Cael himself");
        let mut a = args();
        a["agent"] = json!("nobody");
        assert!(!two.execute(a).await.unwrap().success);
    }
}
