"""The chat says which agent it is (patch 0030).

A chat with a new agent used to read "Caelza Agent" twice: the top bar's
section title "Agent" beside the wordmark, and the empty chat's heading. The
owner could not tell their own agent from Cael, the setup guide. These tests
keep the patch, the overlay module and the manifest saying the same thing;
the logic's own behaviour is under `node --experimental-strip-types --test
src/lib/activeChat.logic.test.ts` in the staged web tree.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB = REPO_ROOT / "runtime" / "overlay" / "web" / "src"
PATCH = (REPO_ROOT / "runtime" / "patches" / "0030-chat-shows-the-agent.patch").read_text(encoding="utf-8")
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text(encoding="utf-8"))


def test_the_manifest_names_the_patch():
    assert MANIFEST["components"]["runtime"]["chat_agent_patch"] == "runtime/patches/0030-chat-shows-the-agent.patch"


def test_the_empty_chat_no_longer_says_the_products_name():
    assert '-    \'agentchat.empty_title\': "Caelza Agent",' in PATCH
    assert '+    \'agentchat.empty_title\': "{name}",' in PATCH
    assert "withAgentName(t('agentchat.empty_title'), agentLabel)" in PATCH


def test_the_top_bar_names_the_agent_in_front():
    # The workspace mirrors tabs with replaceState, which the router never sees:
    # the top bar must read the tab in front, not the address.
    assert "+++ b/web/src/components/layout/Header.tsx" in PATCH
    assert "chatAgentFor(location.pathname, useActiveChatAgent())" in PATCH
    assert "+++ b/web/src/pages/ChatWorkspace.tsx" in PATCH
    assert "setActiveChatAgent(frontAlias)" in PATCH
    assert "chatAgentFor(pathname, useActiveChatAgent())" in PATCH  # the browser tab title


def test_the_logic_and_its_test_ship_in_the_overlay_and_the_test_list():
    assert (WEB / "lib" / "activeChat.ts").is_file()
    assert (WEB / "lib" / "activeChat.logic.ts").is_file()
    assert (WEB / "lib" / "activeChat.logic.test.ts").is_file()
    assert "src/lib/activeChat.logic.test.ts" in PATCH


def test_the_name_cache_survives_a_stub_window():
    # sessionLifecycle.test.ts renders the chat under a stub window with no
    # listeners; importing the name cache must not throw there.
    src = (WEB / "lib" / "agentName.tsx").read_text(encoding="utf-8")
    assert 'typeof window.addEventListener === "function"' in src
