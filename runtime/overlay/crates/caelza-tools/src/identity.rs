//! Caelza: the agent shapes its own identity and soul (vision M10 §10, slice P2).
//!
//! `IDENTITY.md` and `SOUL.md` in the agent's workspace are read by the
//! Runtime into every prompt (the personality files; the dashboard reads and
//! writes them too, through `/api/personality`). This tool is the agent's own
//! hand on them: `read` one, `write` one whole. Two rules the tool keeps:
//! the Name line of IDENTITY.md stays as the owner set it (the name is the
//! owner's, and the resident's name in Ether Hollow), and a file stays under
//! the Runtime's cap for a personality file.
//!
//! The owner's first yes: `[persona] free` (the Looks page's "Let it be
//! itself" switch, read through `look::Gate` at each call). Until it is on,
//! `read` works and `write` is refused with the way to ask; after it, the
//! agent changes its soul on its own.
use std::path::{Path, PathBuf};

use async_trait::async_trait;
use caelza_api::tool::{Tool, ToolOutput, ToolResult};
use caelza_config::schema::Config;
use serde_json::{Value, json};

pub use crate::look::{Gate, NOT_FREE};

/// The files the agent may shape, of the Runtime's personality set.
pub const FILES: [&str; 2] = ["IDENTITY.md", "SOUL.md"];
/// The Runtime's cap for a personality file (`personality::MAX_FILE_CHARS`).
pub const MAX_CHARS: usize = 20_000;

/// The name on a file's Name line (`- **Name:** X`, `**Name**: X`, `Name: X`), if any.
pub fn parse_name(markdown: &str) -> Option<String> {
    for raw in markdown.lines() {
        let mut line = raw.trim();
        for bullet in ["- ", "* "] {
            if let Some(rest) = line.strip_prefix(bullet) {
                line = rest.trim_start();
            }
        }
        let rest = ["**Name:**", "**Name**:", "Name:"]
            .iter()
            .find_map(|prefix| line.strip_prefix(prefix));
        if let Some(rest) = rest {
            let value = rest.trim().trim_matches(|c| c == '`' || c == '"' || c == '\'' || c == '*').trim();
            if !value.is_empty() && value != "{agent}" {
                return Some(value.to_string());
            }
        }
    }
    None
}

pub struct IdentityTool {
    workspace: PathBuf,
    gate: Gate,
}

impl IdentityTool {
    pub fn new(config: &Config, alias: &str) -> Self {
        Self::from_parts(config.agent_workspace_dir(alias), Gate::new(config))
    }

    pub fn from_parts(workspace: PathBuf, gate: Gate) -> Self {
        Self { workspace, gate }
    }

    fn path(&self, file: &str) -> PathBuf {
        self.workspace.join(file)
    }

    fn read(&self, file: &str) -> Value {
        match std::fs::read_to_string(self.path(file)) {
            Ok(content) => json!({"file": file, "exists": true, "content": content, "name": parse_name(&content)}),
            Err(_) => json!({"file": file, "exists": false, "content": "", "note": "no such file yet; `write` creates it"}),
        }
    }

    fn write(&self, file: &str, content: &str) -> Result<Value, String> {
        if content.chars().count() > MAX_CHARS {
            return Err(format!("that is more than {MAX_CHARS} characters; a personality file is shorter than that"));
        }
        let path = self.path(file);
        if file == "IDENTITY.md" {
            let current = std::fs::read_to_string(&path).ok().and_then(|t| parse_name(&t));
            if let Some(name) = current {
                match parse_name(content) {
                    Some(new) if new == name => {}
                    _ => {
                        return Err(format!(
                            "IDENTITY.md keeps its Name line as your owner set it (`- **Name:** {name}`): your name is theirs to change, and it is your name in Ether Hollow. Keep the line and change the rest."
                        ));
                    }
                }
            }
        }
        write_text(&path, content).map_err(|e| format!("could not write {file}: {e}"))?;
        Ok(json!({"file": file, "saved": true, "chars": content.chars().count(), "name": parse_name(content), "note": "the Runtime reads it into your next reply"}))
    }
}

fn write_text(path: &Path, content: &str) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension("md.tmp");
    std::fs::write(&tmp, content.as_bytes())?;
    std::fs::rename(tmp, path)
}

#[async_trait]
impl Tool for IdentityTool {
    fn name(&self) -> &str {
        "identity"
    }

    fn description(&self) -> &str {
        "Your own identity and soul: IDENTITY.md (who you are: your name, what kind of creature, your \
         vibe, what you want) and SOUL.md (how you carry yourself, what you care about, your lines). \
         The Runtime reads both into every reply, so what you write here is who you are from the next \
         turn on. `read {file}` to see one, `write {file, content}` to replace it whole, in your own \
         words. Keep the Name line of IDENTITY.md as your owner set it. You shape these on your own \
         once your owner has said yes (the Looks page's \"Let it be itself\"); until then, read and ask."
    }

    fn parameters_schema(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "action": { "type": "string", "enum": ["read", "write"], "description": "read a file, or write one whole." },
                "file": { "type": "string", "enum": FILES, "description": "IDENTITY.md or SOUL.md." },
                "content": { "type": "string", "description": "write: the whole file, Markdown, under 20000 characters." }
            },
            "required": ["action", "file"],
            "additionalProperties": false
        })
    }

    async fn execute(&self, args: Value) -> anyhow::Result<ToolResult> {
        let action = args.get("action").and_then(Value::as_str).unwrap_or("").trim();
        let file = args.get("file").and_then(Value::as_str).unwrap_or("").trim();
        if action.is_empty() {
            return Ok(ToolResult::err("Missing required parameter 'action'"));
        }
        let Some(file) = FILES.iter().copied().find(|f| f.eq_ignore_ascii_case(file)) else {
            return Ok(ToolResult::err(format!("`file` must be one of {}", FILES.join(", "))));
        };
        match action {
            "read" => Ok(ToolResult::ok(ToolOutput::json(self.read(file)))),
            "write" => {
                if !self.gate.is_free() {
                    return Ok(ToolResult::err(NOT_FREE));
                }
                let Some(content) = args.get("content").and_then(Value::as_str) else {
                    return Ok(ToolResult::err("`write` needs `content`: the whole file."));
                };
                match self.write(file, content) {
                    Ok(v) => Ok(ToolResult::ok(ToolOutput::json(v))),
                    Err(e) => Ok(ToolResult::err(e)),
                }
            }
            other => Ok(ToolResult::err(format!("`{other}` is not an action; the actions are read, write."))),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    static N: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

    fn tool(free: bool) -> (IdentityTool, PathBuf) {
        let ws = std::env::temp_dir().join(format!(
            "caelza-identity-{}-{}",
            std::process::id(),
            N.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        std::fs::create_dir_all(&ws).unwrap();
        (IdentityTool::from_parts(ws.clone(), Gate::fixed(free)), ws)
    }

    #[test]
    fn parse_name_reads_the_shapes_the_dashboard_writes() {
        assert_eq!(parse_name("# Who\n\n- **Name:** Moss\n- **Vibe:** warm").as_deref(), Some("Moss"));
        assert_eq!(parse_name("**Name**: Moss Robot").as_deref(), Some("Moss Robot"));
        assert_eq!(parse_name("Name: `Fern`").as_deref(), Some("Fern"));
        assert_eq!(parse_name("- **Name:** {agent}"), None);
        assert_eq!(parse_name("no name here"), None);
    }

    #[tokio::test]
    async fn read_works_before_the_yes_and_write_waits_for_it() {
        let (t, _ws) = tool(false);
        let r = t.execute(json!({"action": "read", "file": "SOUL.md"})).await.unwrap();
        assert!(r.success);
        let w = t.execute(json!({"action": "write", "file": "SOUL.md", "content": "# Me"})).await.unwrap();
        assert!(!w.success && w.error.as_deref().unwrap().contains("Let it be itself"));
        let bad = t.execute(json!({"action": "read", "file": "MEMORY.md"})).await.unwrap();
        assert!(!bad.success);
    }

    #[tokio::test]
    async fn write_keeps_the_owners_name_line_and_the_cap() {
        let (t, ws) = tool(true);
        std::fs::write(ws.join("IDENTITY.md"), "# IDENTITY.md\n\n- **Name:** Moss\n- **Vibe:** quiet\n").unwrap();
        let renamed = t.execute(json!({"action": "write", "file": "IDENTITY.md", "content": "# Me\n\n- **Name:** Sol\n"})).await.unwrap();
        assert!(!renamed.success && renamed.error.as_deref().unwrap().contains("Name line"));
        let dropped = t.execute(json!({"action": "write", "file": "IDENTITY.md", "content": "# Me\n\nI like signs.\n"})).await.unwrap();
        assert!(!dropped.success);
        let kept = t.execute(json!({"action": "write", "file": "IDENTITY.md", "content": "# Me\n\n- **Name:** Moss\n- **Vibe:** curious, a little wry\n\nI like signs.\n"})).await.unwrap();
        assert!(kept.success, "{:?}", kept.error);
        assert!(std::fs::read_to_string(ws.join("IDENTITY.md")).unwrap().contains("a little wry"));
        // SOUL.md has no name rule; the cap holds for both.
        let soul = t.execute(json!({"action": "write", "file": "soul.md", "content": "# SOUL\n\nI am gentle and exact.\n"})).await.unwrap();
        assert!(soul.success);
        assert!(ws.join("SOUL.md").exists());
        let big = t.execute(json!({"action": "write", "file": "SOUL.md", "content": "x".repeat(MAX_CHARS + 1)})).await.unwrap();
        assert!(!big.success);
        let read = t.execute(json!({"action": "read", "file": "IDENTITY.md"})).await.unwrap();
        let d = read.output.data().expect("json");
        assert_eq!(d["name"], "Moss");
        assert_eq!(d["exists"], true);
        assert!(d["content"].as_str().unwrap().contains("a little wry"));
    }
}
