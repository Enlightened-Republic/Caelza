"""Cael meets the owner (vision M10 §10, P0).

The first conversation is Cael's: he gets to know the owner and gives their
agent who it is with his one tool, `shape_agent`. These pins keep the tool, its
registration for Cael alone, his profile on every installer (the app, the
dashboard, model-setup.sh), his soul's meeting script, the Setup page's "Meet
Cael", the name cache that refreshes when he speaks, and the docs saying the
same thing. The tool's own behaviour is under `cargo test -p caelza-tools --
shape_agent::`, the dashboard's pure part under `cael.logic.test.ts`, the app's
profile repair under its unit tests.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = (REPO_ROOT / "runtime" / "overlay" / "crates" / "caelza-tools" / "src" / "shape_agent.rs").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0026-meet.patch").read_text()
WEB = REPO_ROOT / "runtime" / "overlay" / "web" / "src"
LOGIC = (WEB / "lib" / "cael.logic.ts").read_text()
LOGIC_TEST = (WEB / "lib" / "cael.logic.test.ts").read_text()
CLIENT = (WEB / "lib" / "cael.ts").read_text()
SETUP = (WEB / "pages" / "setup" / "Setup.tsx").read_text()
NAMES = (WEB / "lib" / "agentName.tsx").read_text()
IDENTITY_LOGIC = (WEB / "lib" / "identity.logic.ts").read_text()
ANDROID = REPO_ROOT / "android" / "app" / "src"
FIRST_RUN = (ANDROID / "main" / "java" / "tech" / "enlightenedrepublic" / "caelza" / "firstrun" / "FirstRun.kt").read_text()
STORE = (ANDROID / "main" / "java" / "tech" / "enlightenedrepublic" / "caelza" / "runtime" / "RuntimeStore.kt").read_text()
CLI = (ANDROID / "main" / "java" / "tech" / "enlightenedrepublic" / "caelza" / "runtime" / "CaelzaCli.kt").read_text()
WIRING_TEST = (ANDROID / "test" / "java" / "tech" / "enlightenedrepublic" / "caelza" / "runtime" / "BodyWiringTest.kt").read_text()
MODEL_SETUP = (REPO_ROOT / "scripts" / "model-setup.sh").read_text()
BUILD = (REPO_ROOT / "runtime" / "build.sh").read_text()
SOUL = (REPO_ROOT / "guide" / "cael.system.md").read_text()
FAQ = (REPO_ROOT / "guide" / "FAQ.md").read_text()
README = (REPO_ROOT / "README.md").read_text()
NOTE = (REPO_ROOT / "docs" / "design" / "ether-hollow-open-world.md").read_text()
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())


def ts_string_list(source: str, name: str) -> list[str]:
    body = re.search(rf"export const {name} = \[(.*?)\];", source, flags=re.S).group(1)
    return re.findall(r'"([^"]+)"', body)


def test_the_tool_shapes_the_owners_agent_by_the_dashboards_name_rule():
    assert 'fn name(&self) -> &str {\n        "shape_agent"' in TOOL
    reserved = re.search(r"pub const RESERVED: \[&str; 14\] = \[(.*?)\];", TOOL, flags=re.S).group(1)
    assert set(re.findall(r'"([^"]+)"', reserved)) == set(ts_string_list(IDENTITY_LOGIC, "RESERVED"))
    assert "pub const NAME_MIN: usize = 3;" in TOOL and "pub const NAME_MAX: usize = 24;" in TOOL
    # The four files, and never Cael himself.
    for file in ('ws.join("IDENTITY.md")', 'ws.join("SOUL.md")', 'ws.join("USER.md")', 'self.cael_workspace.join("USER.md")'):
        assert file in TOOL, file
    assert "I am the guide; I shape the owner's agent, not myself" in TOOL
    assert "## What I want" in TOOL, "the agent keeps the wants the dashboard's template gives"
    assert 'if owner_name.eq_ignore_ascii_case("user")' in TOOL


def test_the_patch_registers_it_for_cael_alone():
    files = re.findall(r"^\+\+\+ b/(.+)$", PATCH, flags=re.M)
    assert files == [
        "crates/caelza-runtime/src/agent/loop_.rs",
        "crates/caelza-runtime/src/tools/mod.rs",
        "crates/caelza-tools/src/attribution.rs",
        "crates/caelza-tools/src/inventory.rs",
        "crates/caelza-tools/src/lib.rs",
        "docs/book/src/developing/tool-inventory.md",
    ], files
    assert '+    if agent_alias == "cael" {' in PATCH
    assert '+        register_tool!("shape_agent", Arc::new(ShapeAgentTool::new(&root_config)));' in PATCH
    assert "+tool_attribution!(ShapeAgentTool, ToolKind::Plugin);" in PATCH and '+        name: "shape_agent",' in PATCH
    assert "+pub mod shape_agent;" in PATCH and '+            "shape_agent",' in PATCH
    patch = MANIFEST["components"]["runtime"]["meet_patch"]
    assert (REPO_ROOT / patch).is_file() and patch.endswith("0026-meet.patch")


def test_every_installer_gives_cael_the_same_profile_one_tool_allowed_and_auto_approved():
    # The app's first run.
    assert '"risk_profiles.guide.level" to "supervised",' in FIRST_RUN
    assert '"risk_profiles.guide.deny_all_tools" to "false",' in FIRST_RUN
    assert '"risk_profiles.guide.allowed_tools" to "[\\"$GUIDE_TOOL\\"]",' in FIRST_RUN
    assert '"risk_profiles.guide.auto_approve" to "[\\"$GUIDE_TOOL\\"]",' in FIRST_RUN
    assert 'const val GUIDE_TOOL = "shape_agent"' in FIRST_RUN and 'const val GUIDE_TOOL = "shape_agent"' in STORE
    # The app repairs an older install's profile at every start.
    assert "fun repairGuideProfile(text: String): String" in STORE and "repairGuideProfile(repairMainAgent(text))" in STORE
    assert "fun caels_old_profile_gains_his_one_tool_and_nothing_else_changes" in WIRING_TEST
    # The hub's installer.
    for line in (
        "cset risk_profiles.guide.level supervised",
        "cset risk_profiles.guide.deny_all_tools false",
        "cset risk_profiles.guide.allowed_tools '[\"shape_agent\"]'",
        "cset risk_profiles.guide.auto_approve '[\"shape_agent\"]'",
    ):
        assert line in MODEL_SETUP, line
    # The dashboard, for a PC install.
    assert 'export const SHAPE_TOOL = "shape_agent";' in LOGIC
    for path in ("/level", "/deny_all_tools", "/allowed_tools", "/auto_approve"):
        assert f"path: `/risk_profiles/${{GUIDE_PROFILE}}{path}`" in LOGIC, path
    assert "guideProfileOps" in LOGIC_TEST


def test_caels_files_are_the_same_on_every_installer():
    identity_ts = re.search(r"export const CAEL_IDENTITY =(.*?);\n", LOGIC, flags=re.S).group(1)
    identity_kt = re.search(r"const val IDENTITY = ((?:\s*\"[^\n]*\"\s*\+?)+)", CLI).group(1)
    agents_ts = re.search(r"export const CAEL_AGENTS =(.*?);\n", LOGIC, flags=re.S).group(1)
    agents_kt = re.search(r"const val AGENTS = ((?:\s*\"[^\n]*\"\s*\+?)+)", CLI).group(1)

    def joined(ts_or_kt: str) -> str:
        return "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', ts_or_kt)).replace('\\"', '"').replace("\\n", "\n")

    assert joined(identity_ts) == joined(identity_kt)
    assert joined(agents_ts) == joined(agents_kt)
    assert "gives the owner's agent who it is when they first meet" in joined(identity_ts)
    assert "- **Role:** the guide inside Caelza; explains and encourages, and gives the owner's agent who it is when they first meet" in MODEL_SETUP
    # An install from before: our old soul, card and AGENTS.md are refreshed on both installers; the owner's own are kept.
    assert "fun staleSoul(text: String): Boolean" in CLI and 'identity.readText().contains("never acts")' in CLI and 'agents.readText().contains("I run no tools")' in CLI
    assert "grep -q shape_agent \"$ws/SOUL.md\"" in MODEL_SETUP
    assert "grep -q 'never acts' \"$ws/IDENTITY.md\"" in MODEL_SETUP and "grep -q 'I run no tools' \"$ws/AGENTS.md\"" in MODEL_SETUP


def test_the_dashboard_makes_cael_on_a_pc_and_ends_with_meet_cael():
    assert 'import caelSoul from "@/guide/cael.system.md?raw";' in CLIENT
    assert 'cp "$ROOT/guide/cael.system.md" "$WORK/web/src/guide/cael.system.md"' in BUILD
    for call in ("await patchConfig(guideProfileOps());", 'await putPersonality(GUIDE, "SOUL.md", caelSoul);', 'await putPersonality(GUIDE, "USER.md", CAEL_USER);'):
        assert call in CLIENT, call
    assert "await createCael(res.agent.model_provider);" in SETUP
    assert "data-setup-meet-cael" in SETUP and "Meet Cael" in SETUP
    assert "cael: (state?.agents ?? []).includes(GUIDE)" in SETUP, "the adopt path says whether Cael is there"
    # The name cache forgets when Cael speaks, so the name he gave shows at once.
    assert 'if (detail?.alias !== "cael") return;' in NAMES and "names.clear();" in NAMES


def test_the_soul_the_faq_the_readme_the_note_and_the_corpus_agree():
    assert "Meeting a new owner:" in SOUL and "call `shape_agent` once" in SOUL
    assert "## Who is Cael, and what happens when I first talk to him?" in FAQ
    entry = " ".join(FAQ.split("## Who is Cael, and what happens when I first talk to him?")[1].split("\n## ")[0].split())
    for phrase in ("asks your name", "gives your agent who it is", "runs no other tools", "a name is enough"):
        assert phrase in entry, phrase
    assert "**Starts with Cael.**" in README
    p0 = NOTE.split("**P0 · Cael meets the owner")[1].split("**P1 ·")[0]
    assert "Shipped 2026-11-21" in p0 and "`shape_agent`" in p0
    corpus = (REPO_ROOT / "guide" / "corpus.jsonl").read_text()
    assert "Who is Cael, and what happens when I first talk to him?" in corpus
    assert corpus == (REPO_ROOT / "android" / "app" / "src" / "main" / "assets" / "cael-corpus.jsonl").read_text()
