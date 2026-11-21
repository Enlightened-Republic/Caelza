"""The free-will buddy (vision M10 §10, slice P2a: the look and the files).

Two tools of the agent's own, `look` and `identity`, behind one yes from the
owner: `[persona] free`, the Looks page's "Let it be itself" switch. The tools
read the switch from the config file at each call, keep the owner's Name line
and the wardrobe's packs, and are registered for every agent but Cael. These
tests keep the overlay, the patch, the build script, the manifest, the FAQ,
the README, the design note and Cael's corpus saying the same thing; the
tools' own behaviour is under `cargo test -p caelza-tools`, the switch's patch
under the web suite (`persona.logic.test.ts`).
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "runtime" / "overlay" / "crates" / "caelza-tools" / "src"
LOOK = (TOOLS / "look.rs").read_text()
IDENTITY = (TOOLS / "identity.rs").read_text()
WEB = REPO_ROOT / "runtime" / "overlay" / "web" / "src"
LOGIC = (WEB / "lib" / "persona.logic.ts").read_text()
LOGIC_TEST = (WEB / "lib" / "persona.logic.test.ts").read_text()
IDENTITY_LOGIC = (WEB / "lib" / "identity.logic.ts").read_text()
IDENTITY_LOGIC_TEST = (WEB / "lib" / "identity.logic.test.ts").read_text()
LOOKS = (WEB / "pages" / "Looks.tsx").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0023-persona.patch").read_text()
BUILD = (REPO_ROOT / "runtime" / "build.sh").read_text()
FAQ = (REPO_ROOT / "guide" / "FAQ.md").read_text()
README = (REPO_ROOT / "README.md").read_text()
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
NOTE = (REPO_ROOT / "docs" / "design" / "ether-hollow-open-world.md").read_text()
CATALOG = json.loads((REPO_ROOT / "looks" / "catalog.json").read_text())

FAQ_TITLE = "## Can my agent change its own look and personality?"


def test_the_look_tool_embeds_the_one_catalog_and_knows_the_dashboards_layers_and_slots():
    assert 'include_str!("looks_catalog.json")' in LOOK
    assert 'cp "$ROOT/looks/catalog.json" "$WORK/crates/caelza-tools/src/looks_catalog.json"' in BUILD
    assert CATALOG["layers"] == ["backdrop", "body", "outfit", "hair", "hat", "face", "accessory"]
    assert CATALOG["slots"] == ["skin", "hair", "outfit", "accent", "eyes"]
    assert 'pub const LAYERS: [&str; 7] = ["backdrop", "body", "outfit", "hair", "hat", "face", "accessory"];' in LOOK
    assert 'pub const SLOTS: [&str; 5] = ["skin", "hair", "outfit", "accent", "eyes"];' in LOOK
    # The same files the dashboard reads and writes (api_looks.rs).
    assert 'pub const LOOK_FILE: &str = "look.json";' in LOOK and 'pub const WARDROBE_FILE: &str = "wardrobe.json";' in LOOK
    assert '.join("agents").join(&self.alias).join(LOOK_FILE)' in LOOK
    assert '.join("looks").join(WARDROBE_FILE)' in LOOK
    # A priced pack is worn only once a code opened it, as on the Looks page.
    assert 'priced: p["price"].as_str() != Some("free"),' in LOOK
    assert "if pack.priced && !unlocked {" in LOOK


def test_both_tools_wait_for_the_owners_one_yes_read_live_from_the_config():
    assert 'v.get("persona").and_then(|p| p.get("free"))' in LOOK
    assert "Let it be itself" in LOOK, "the refusal says where the yes is"
    assert "pub use crate::look::{Gate, NOT_FREE};" in IDENTITY
    assert "if !self.gate.is_free() {" in IDENTITY
    for guarded in ('"set" => {\n                if !free {', '"reset" => {\n                if !free {'):
        assert guarded in LOOK, guarded
    # Showing and reading never need the yes.
    assert '"show" => Ok(ToolResult::ok(' in LOOK and '"read" => Ok(ToolResult::ok(' in IDENTITY


def test_the_identity_tool_keeps_the_owners_name_line_and_the_runtimes_cap():
    assert 'pub const FILES: [&str; 2] = ["IDENTITY.md", "SOUL.md"];' in IDENTITY
    assert "pub const MAX_CHARS: usize = 20_000;" in IDENTITY
    assert 'if file == "IDENTITY.md" {' in IDENTITY and "Name line" in IDENTITY


def test_the_patch_wires_the_tools_in_for_everyone_but_cael():
    files = re.findall(r"^\+\+\+ b/(.+)$", PATCH, flags=re.M)
    assert files == [
        "crates/caelza-config/src/schema.rs",
        "crates/caelza-runtime/src/agent/loop_.rs",
        "crates/caelza-runtime/src/tools/mod.rs",
        "crates/caelza-tools/src/attribution.rs",
        "crates/caelza-tools/src/inventory.rs",
        "crates/caelza-tools/src/lib.rs",
        "docs/book/src/developing/tool-inventory.md",
        "web/package.json",
        "web/src/lib/i18n.ts",
    ], files
    assert "+pub struct PersonaConfig {" in PATCH and "+    pub free: bool," in PATCH
    assert '+#[prefix = "persona"]' in PATCH and '+    #[group = "Agent"]' in PATCH
    assert PATCH.count("+            persona: PersonaConfig::default(),") == 3
    assert '+    if agent_alias != "cael" {' in PATCH
    assert '+        register_tool!("look", Arc::new(LookTool::new(&root_config, agent_alias)));' in PATCH
    assert '+        register_tool!("identity", Arc::new(IdentityTool::new(&root_config, agent_alias)));' in PATCH
    assert "+tool_attribution!(LookTool, ToolKind::Plugin);" in PATCH
    assert "+tool_attribution!(IdentityTool, ToolKind::Plugin);" in PATCH
    assert '+        name: "look",' in PATCH and '+        name: "identity",' in PATCH
    assert "+pub mod look;" in PATCH and "+pub mod identity;" in PATCH
    assert '+            "look",' in PATCH and '+            "identity",' in PATCH, "the prompt's tool lines"
    assert "src/lib/persona.logic.test.ts" in PATCH
    # Every persona.* string the page uses is added by this patch.
    used = set(re.findall(r'\bt\("(persona\.[a-z_]+)"\)', LOOKS)) | set(re.findall(r'\? "(persona\.[a-z_]+)" : "(?:persona\.[a-z_]+)"', LOOKS))
    used |= set(re.findall(r'\? "persona\.[a-z_]+" : "(persona\.[a-z_]+)"', LOOKS))
    added = set(re.findall(r"^\+    '(persona\.[a-z_]+)': ", PATCH, re.M))
    assert used and used <= added, sorted(used - added)
    assert "'persona.card_title': \"Let it be itself\"" in PATCH


def test_the_looks_page_has_the_switch_for_everyone_but_cael():
    assert "data-free-card" in LOOKS and "data-free-switch" in LOOKS
    assert 'getProp("persona.free")' in LOOKS
    assert "await patchConfig(freeOps(on, profile, autoApprove));" in LOOKS
    assert LOOKS.count('{alias !== "cael" ? (') == 2, "the Name card and the switch, neither for Cael"
    assert 'export const PERSONA_TOOLS = ["look", "identity"] as const;' in LOGIC
    assert 'path: "/persona/free"' in LOGIC and "/risk_profiles/${profile}/auto_approve" in LOGIC
    assert "freeOps" in LOGIC_TEST and "PERSONA_TOOLS" in LOGIC_TEST


def test_a_new_agent_starts_with_its_wants_and_the_docs_agree():
    assert '"## What I want",' in IDENTITY_LOGIC
    for want in ("`look` tool", "`identity` tool", "Let it be itself"):
        assert want in IDENTITY_LOGIC, want
    assert "What I want" in IDENTITY_LOGIC_TEST
    patch = MANIFEST["components"]["runtime"]["persona_patch"]
    assert (REPO_ROOT / patch).is_file() and patch.endswith("0023-persona.patch")
    assert FAQ_TITLE in FAQ
    entry = " ".join(FAQ.split(FAQ_TITLE)[1].split("\n## ")[0].split())
    for phrase in ("Let it be itself", "Looks", "`look`", "`identity`", "Name line", "Cael"):
        assert phrase in entry, phrase
    assert "Let it be itself" in README
    p2 = NOTE.split("**P2 · Wants, a look and a voice")[1].split("**P3 ·")[0]
    assert "Shipped" in p2 and "2026-11-21" in p2 and "`voice`" in p2
    # Cael's corpus carries the FAQ entry, and the app's copy is the same file.
    corpus = (REPO_ROOT / "guide" / "corpus.jsonl").read_text()
    assert FAQ_TITLE.lstrip("# ") in corpus
    assert corpus == (REPO_ROOT / "android" / "app" / "src" / "main" / "assets" / "cael-corpus.jsonl").read_text()
