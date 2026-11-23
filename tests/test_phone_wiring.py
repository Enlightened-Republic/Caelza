"""The phone's first run and the agent it makes (v0.6.1).

v0.6.0 on a phone left `main` unable to start: the app's own first run wrote
the agent's model with `caelza config set` before the Body was wired, and the
wiring then skipped the block that carried the risk profile and the Body. The
dashboard's setup, seeing `main` taken, made a `main2`. These pins keep the
repair in the app, the setup adopting the device's agent, the two agents'
USER.md (so neither calls the owner "User"), the Plugins page out of the menu,
and the Memory page and FAQ saying what a phone does about the Mind.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ANDROID = REPO_ROOT / "android" / "app" / "src"
STORE = (ANDROID / "main" / "java" / "tech" / "enlightenedrepublic" / "caelza" / "runtime" / "RuntimeStore.kt").read_text()
CLI = (ANDROID / "main" / "java" / "tech" / "enlightenedrepublic" / "caelza" / "runtime" / "CaelzaCli.kt").read_text()
WIRING_TEST = (ANDROID / "test" / "java" / "tech" / "enlightenedrepublic" / "caelza" / "runtime" / "BodyWiringTest.kt").read_text()
WEB = REPO_ROOT / "runtime" / "overlay" / "web" / "src"
SETUP = (WEB / "pages" / "setup" / "Setup.tsx").read_text()
LOGIC = (WEB / "lib" / "identity.logic.ts").read_text()
CLIENT = (WEB / "lib" / "identity.ts").read_text()
MEMORY = (WEB / "pages" / "Memory.tsx").read_text()
FAQ = (REPO_ROOT / "guide" / "FAQ.md").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0025-menu.patch").read_text()
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
RELEASE = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text()


def test_the_body_wiring_repairs_an_agent_another_writer_made_first():
    assert "fun repairMainAgent(text: String): String" in STORE
    assert "val repaired = repairGuideProfile(repairMainAgent(text))" in STORE
    assert 'missing.append("\\nrisk_profile = \\"phone\\"")' in STORE
    assert 'missing.append("\\nmcp_bundles = [\\"body\\"]")' in STORE
    # The whole file is rewritten only when something changed; the second run adds nothing.
    assert "if (changed) config.writeText(text)" in STORE
    assert "fun an_agent_the_first_run_made_first_gets_its_profile_and_its_body" in WIRING_TEST
    assert "fun repair_adds_only_what_the_section_lacks_and_leaves_other_sections_alone" in WIRING_TEST


def test_the_setup_adopts_the_devices_agent_instead_of_making_a_second():
    assert "getProp(`agents.${AGENT_NAME}.model_provider`)" in SETUP
    assert "const adoptMain = async () => {" in SETUP
    assert "await setAgentName(AGENT_NAME, label);" in SETUP
    assert 'await putProp("onboard_state.quickstart_completed", true)' in SETUP
    assert "name: [1, adopt ? 1 : 3]," in SETUP
    assert "if (adopt) void adoptMain();" in SETUP and 'else go("doors");' in SETUP
    # Both paths give the agent a USER.md of its own, so it never calls the owner "User".
    assert SETUP.count("userTemplate()") == 2
    assert 'export const USER_FILE = "USER.md";' in LOGIC and "export function userTemplate(" in LOGIC
    assert 'never \\"User\\"' in LOGIC
    assert "export function setUserFile(" in CLIENT and "export function putPersonality(" in CLIENT


def test_cael_gets_his_own_user_and_agents_files():
    assert "if (!user.isFile || STOCK_USER.containsMatchIn(user.readText())) user.writeText(USER)" in CLI
    assert 'if (!agents.isFile || agents.readText().contains("I run no tools")) agents.writeText(AGENTS)' in CLI
    assert 'never \\"User\\"' in CLI


def test_the_plugins_page_leaves_the_menu():
    files = re.findall(r"^\+\+\+ b/(.+)$", PATCH, flags=re.M)
    assert files == ["web/src/components/layout/Sidebar.tsx"], files
    assert "-      { to: '/plugins', icon: Blocks, labelKey: 'nav.plugins' }," in PATCH
    assert "-  Blocks," in PATCH
    patch = MANIFEST["components"]["runtime"]["menu_patch"]
    assert (REPO_ROOT / patch).is_file() and patch.endswith("0025-menu.patch")


def test_the_memory_page_and_the_faq_say_what_a_phone_does_about_the_mind():
    assert "it runs on a PC or a hub, not on a phone." in MEMORY
    assert "join the one your PC or hub" in MEMORY
    assert "On a phone the app does not run it" in FAQ
    assert "On a phone the app runs it" not in FAQ
    corpus = (REPO_ROOT / "guide" / "corpus.jsonl").read_text()
    assert "the phone joins the Mind your PC or" in corpus
    assert corpus == (REPO_ROOT / "android" / "app" / "src" / "main" / "assets" / "cael-corpus.jsonl").read_text()


def test_the_release_notes_carry_the_phone_fix():
    assert MANIFEST["caelza"]["version"] == "0.7.0"
    assert "v0.6.1 fixed the phone's first run" in RELEASE
