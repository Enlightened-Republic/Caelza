//! Caelza: the Connect page (your apps, your home, your printer, with no
//! shell). The config side of a connection goes through the config API the
//! dashboard already has: `POST /api/config/map-key` makes the
//! `[[mcp.servers]]` row by name and one `PATCH /api/config` fills it, grants
//! it to the agent and keeps the secret encrypted. What the config API cannot
//! do is put a skill on disk, and the 3D printer is a skill. These routes do
//! that for the skills the Runtime carries built in (`skills/<name>/SKILL.md`
//! in the Caelza repo, copied beside this file by runtime/build.sh):
//!
//! - `GET  /api/connect/skills?agent=<alias>` → `{agent, dir, skills: {name: {installed, path}}}`
//! - `POST /api/connect/skills/{name}`       ← `{agent}`: writes `<workspace>/skills/<name>/SKILL.md`,
//!                                              the agent's own workspace skills, which load with no
//!                                              bundle → `{agent, name, path, installed: true}`
//!
//! Only a paired client may call them, like every other route; the agent must
//! exist in the config; the name must be one of the bundled skills. The file is
//! written whole or not at all (a temp file beside it, then a rename), and an
//! install over an existing copy refreshes it to this build's text.
use super::AppState;
use super::api::require_auth;
use super::api_looks::alias_ok;
use axum::{
    extract::{Path as AxumPath, Query, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Json, Response},
};
use caelza_config::schema::Config;
use serde_json::{Map, Value, json};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

/// The skills the Runtime carries, by name, with the SKILL.md each installs.
pub const BUNDLED: &[(&str, &str)] = &[("3d-printer", include_str!("connect_skill_3d_printer.md"))];

/// The agent the page connects things for when none is named.
const DEFAULT_AGENT: &str = "main";

/// A temp file per write: two writers of one file must not share a name.
static WRITE_SEQ: AtomicU64 = AtomicU64::new(0);

fn error_response(status: StatusCode, message: impl Into<String>) -> Response {
    (status, Json(json!({"error": message.into()}))).into_response()
}

pub fn bundled(name: &str) -> Option<&'static str> {
    BUNDLED.iter().find(|(n, _)| *n == name).map(|(_, text)| *text)
}

/// Where an agent's workspace skills live; the Runtime loads every `<dir>/<name>/SKILL.md` for it.
pub fn skills_dir(config: &Config, agent: &str) -> PathBuf {
    config.agent_workspace_dir(agent).join("skills")
}

fn known_agent(config: &Config, alias: &str) -> bool {
    config.agents.contains_key(alias)
}

fn agent_or_default(named: Option<&str>) -> String {
    match named.map(str::trim) {
        Some(a) if !a.is_empty() => a.to_string(),
        _ => DEFAULT_AGENT.to_string(),
    }
}

/// Write whole or not at all: a sibling temp file of its own, then a rename.
fn write_text(path: &PathBuf, text: &str) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| format!("{} has no parent", path.display()))?;
    std::fs::create_dir_all(parent).map_err(|e| format!("creating {}: {e}", parent.display()))?;
    let seq = WRITE_SEQ.fetch_add(1, Ordering::Relaxed);
    let tmp = path.with_extension(format!("md.{}.{seq}.tmp", std::process::id()));
    std::fs::write(&tmp, text.as_bytes()).map_err(|e| format!("writing {}: {e}", tmp.display()))?;
    std::fs::rename(&tmp, path).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        format!("renaming into {}: {e}", path.display())
    })
}

fn skills_report(config: &Config, agent: &str) -> Value {
    let dir = skills_dir(config, agent);
    let mut skills = Map::new();
    for (name, _) in BUNDLED {
        let path = dir.join(name).join("SKILL.md");
        skills.insert(
            (*name).to_string(),
            json!({"installed": path.is_file(), "path": path.display().to_string()}),
        );
    }
    json!({"agent": agent, "dir": dir.display().to_string(), "skills": Value::Object(skills)})
}

/// GET /api/connect/skills?agent=<alias>
pub async fn handle_skills_get(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<HashMap<String, String>>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let agent = agent_or_default(query.get("agent").map(String::as_str));
    if !alias_ok(&agent) {
        return error_response(StatusCode::BAD_REQUEST, "not an agent alias");
    }
    let config = state.config.read().clone();
    if !known_agent(&config, &agent) {
        return error_response(StatusCode::NOT_FOUND, format!("no agent {agent:?} in the config"));
    }
    Json(skills_report(&config, &agent)).into_response()
}

/// POST /api/connect/skills/{name}
pub async fn handle_skill_install(
    State(state): State<AppState>,
    headers: HeaderMap,
    AxumPath(name): AxumPath<String>,
    Json(body): Json<Value>,
) -> Response {
    if let Err(e) = require_auth(&state, &headers) {
        return e.into_response();
    }
    let Some(text) = bundled(&name) else {
        return error_response(StatusCode::NOT_FOUND, format!("no bundled skill {name:?}"));
    };
    let agent = agent_or_default(body.get("agent").and_then(Value::as_str));
    if !alias_ok(&agent) {
        return error_response(StatusCode::BAD_REQUEST, "not an agent alias");
    }
    let config = state.config.read().clone();
    if !known_agent(&config, &agent) {
        return error_response(StatusCode::NOT_FOUND, format!("no agent {agent:?} in the config"));
    }
    let path = skills_dir(&config, &agent).join(&name).join("SKILL.md");
    if let Err(e) = write_text(&path, text) {
        return error_response(StatusCode::INTERNAL_SERVER_ERROR, e);
    }
    Json(json!({"agent": agent, "name": name, "path": path.display().to_string(), "installed": true})).into_response()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_bundled_printer_skill_is_the_repos_and_names_itself() {
        let text = bundled("3d-printer").expect("the printer skill is bundled");
        assert!(text.starts_with("---\nname: 3d-printer\n"), "the SKILL.md front matter names the skill");
        assert!(text.contains("Moonraker") && text.contains("OctoPrint"));
        assert!(bundled("nope").is_none());
    }

    #[test]
    fn the_skill_lands_in_the_agents_workspace_and_is_reported() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let mut config = Config::default();
        config.config_path = tmp.path().join("config.toml");
        config.agents.insert("main".to_string(), Default::default());
        let report = skills_report(&config, "main");
        assert_eq!(report["skills"]["3d-printer"]["installed"], Value::Bool(false));
        let path = skills_dir(&config, "main").join("3d-printer").join("SKILL.md");
        write_text(&path, bundled("3d-printer").unwrap()).expect("written");
        assert!(path.is_file());
        assert!(path.starts_with(config.agent_workspace_dir("main")));
        let report = skills_report(&config, "main");
        assert_eq!(report["skills"]["3d-printer"]["installed"], Value::Bool(true));
        assert_eq!(report["skills"]["3d-printer"]["path"], Value::String(path.display().to_string()));
        assert_eq!(agent_or_default(None), "main");
        assert_eq!(agent_or_default(Some("  ")), "main");
        assert_eq!(agent_or_default(Some("cael")), "cael");
    }
}
