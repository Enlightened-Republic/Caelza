"""The agent's name (vision M10 §10, slice P1).

The name is the Name line of the agent's IDENTITY.md, one of the personality
files the Runtime reads into every prompt and upstream's gateway already
serves (`GET/PUT /api/personality/IDENTITY.md?agent=<alias>`). The first run
asks for it, the Looks page renames, the chat header, the tabs, Home and the
town card say it. These tests keep the overlay, the patch, the manifest, the
FAQ and Cael's corpus saying the same thing; the logic's own behaviour is under
the web suite (`identity.logic.test.ts`).
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB = REPO_ROOT / "runtime" / "overlay" / "web" / "src"
LOGIC = (WEB / "lib" / "identity.logic.ts").read_text()
LOGIC_TEST = (WEB / "lib" / "identity.logic.test.ts").read_text()
CLIENT = (WEB / "lib" / "identity.ts").read_text()
HOOK = (WEB / "lib" / "agentName.tsx").read_text()
SETUP = (WEB / "pages" / "setup" / "Setup.tsx").read_text()
SETUP_LOGIC = (WEB / "pages" / "setup" / "setup.logic.ts").read_text()
LOOKS = (WEB / "pages" / "Looks.tsx").read_text()
HOME = (WEB / "pages" / "Home.tsx").read_text()
WORLD = (WEB / "pages" / "connect" / "World.tsx").read_text()
WORLD_LOGIC = (WEB / "pages" / "connect" / "world.logic.ts").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0022-agent-name.patch").read_text()
FAQ = (REPO_ROOT / "guide" / "FAQ.md").read_text()
README = (REPO_ROOT / "README.md").read_text()
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
NOTE = (REPO_ROOT / "docs" / "design" / "ether-hollow-open-world.md").read_text()


def ts_string_list(source: str, name: str) -> list[str]:
    body = re.search(rf"export const {name} = \[(.*?)\];", source, flags=re.S).group(1)
    return re.findall(r'"([^"]+)"', body)


def test_the_name_lives_in_identity_md_through_upstreams_personality_api():
    assert 'export const IDENTITY_FILE = "IDENTITY.md";' in LOGIC
    assert "/api/personality/${IDENTITY_FILE}?agent=${encodeURIComponent(alias)}" in CLIENT
    assert 'method: "PUT"' in CLIENT and "JSON.stringify({ content })" in CLIENT
    # A rename keeps the rest of the file: the agent's own words stay.
    assert "withName(current?.content, name)" in CLIENT
    for fn in ("parseName", "withName", "identityTemplate", "displayName", "nameOk", "suggestName"):
        assert f"export function {fn}(" in LOGIC, fn
        assert fn in LOGIC_TEST, fn


def test_the_rule_is_the_towns_and_the_reserved_names_are_caels_and_the_crews():
    # The town takes 3-24 of letters, digits, spaces, _ and -; the agent's rule is that, anchored on a letter or digit.
    assert "NAME_RULE = /^[A-Za-z0-9 _-]{3,24}$/" in WORLD_LOGIC
    assert "export const NAME_RULE = /^[A-Za-z0-9][A-Za-z0-9 _-]{1,22}[A-Za-z0-9]$/;" in LOGIC
    reserved = ts_string_list(LOGIC, "RESERVED")
    for who in ("cael", "caelza", "mayor", "sheriff", "town", "tripp", "gray", "gion", "gano", "neva", "cade", "wren", "algen", "mila"):
        assert who in reserved, who
    suggestions = ts_string_list(LOGIC, "SUGGESTIONS")
    assert len(suggestions) >= 24 and len(set(suggestions)) == len(suggestions)
    rule = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{1,22}[A-Za-z0-9]$")
    for s in suggestions:
        assert rule.match(s) and s.lower() not in reserved, s


def test_the_first_run_asks_first_and_writes_the_name_once_the_agent_exists():
    assert 'export type Screen = "name" | "doors"' in SETUP_LOGIC
    assert 'useState<Screen>("name")' in SETUP
    assert "suggestName(AGENT_NAME)" in SETUP and "suggestName(AGENT_NAME, deal + 1)" in SETUP
    assert "await setAgentName(res.agent.alias, label);" in SETUP
    assert "rememberAgentName(res.agent.alias, label);" in SETUP
    # The done screen greets the name, not the alias.
    assert "{ agent: done.label, model: done.provider.model" in SETUP
    for marker in ("data-setup-name", "data-setup-name-next", "data-setup-name-another"):
        assert marker in SETUP, marker
    assert 'doors: "name"' in SETUP, "Back from the doors returns to the name"


def test_the_looks_page_renames_everyone_but_cael_and_every_page_says_the_name():
    assert "data-name-card" in LOOKS and 'alias !== "cael"' in LOOKS
    assert "await setAgentName(alias, next);" in LOOKS and "rememberAgentName(alias, next);" in LOOKS
    assert "title={shown}" in LOOKS and "<AgentNameText alias={a.alias} />" in LOOKS
    assert "useAgentName(tile.alias)" in HOME
    assert "useAgentName(agent)" in WORLD and "nameOk(agentLabel)" in WORLD
    # Cael keeps his proper name without a file.
    assert 'alias === "cael" ? "Cael" : alias' in LOGIC
    assert "export function AgentNameText(" in HOOK and "export function useAgentName(" in HOOK


def test_the_patch_touches_the_header_the_tabs_the_strings_and_the_test_list_only():
    files = re.findall(r"^\+\+\+ b/(.+)$", PATCH, flags=re.M)
    assert files == [
        "web/package.json",
        "web/src/components/ChatTabBar.tsx",
        "web/src/lib/i18n.ts",
        "web/src/pages/AgentChat.tsx",
    ], files
    assert "+src/lib/identity.logic.test.ts" in PATCH.replace("src/pages/connect/world.logic.test.ts src/lib/identity.logic.test.ts", "+src/lib/identity.logic.test.ts") or "identity.logic.test.ts" in PATCH
    assert '+          <span className="text-sm font-medium text-pc-text">{agentLabel}</span>' in PATCH
    assert "+                <AgentNameText alias={tab.alias} />" in PATCH
    assert '+                    <span className="truncate"><AgentNameText alias={alias} /></span>' in PATCH
    # Every name.* string the pages use is added by this patch.
    used = set(re.findall(r'\bt\("(name\.[a-z_]+)"\)', SETUP + LOOKS))
    added = set(re.findall(r"^\+    '(name\.[a-z_]+)': ", PATCH, re.M))
    assert used and used <= added, sorted(used - added)
    body = re.search(r"^\+    'name\.body': (.*),$", PATCH, re.M).group(1)
    assert "I'm Cael, the guide" in json.loads(body) and "Your AI is not me" in json.loads(body)


def test_the_manifest_the_faq_the_readme_and_the_note_agree():
    patch = MANIFEST["components"]["runtime"]["agent_name_patch"]
    assert (REPO_ROOT / patch).is_file() and patch.endswith("0022-agent-name.patch")
    assert "## Can I name or rename my agent?" in FAQ
    faq_entry = FAQ.split("## Can I name or rename my agent?")[1].split("\n## ")[0]
    for phrase in ("Looks", "Name card", "every reply", "Ether Hollow", "Cael"):
        assert phrase in faq_entry, phrase
    assert "Has a name and a face" in README
    assert "**P1 · A name of its own" in NOTE and "Shipped 2026-11-21" in NOTE.split("**P1 · A name of its own")[1].split("**P2")[0]
    # Cael's corpus carries the FAQ entry, and the app's copy is the same file.
    corpus = (REPO_ROOT / "guide" / "corpus.jsonl").read_text()
    assert "Can I name or rename my agent?" in corpus
    assert corpus == (REPO_ROOT / "android" / "app" / "src" / "main" / "assets" / "cael-corpus.jsonl").read_text()
