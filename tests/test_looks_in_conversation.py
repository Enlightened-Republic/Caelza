"""The look where the owner talks to the agent (vision M8, the fourth slice).

Beside each of the agent's bubbles and on its chat tab the look holds still;
the live turn's look talks while the answer streams. Home has the agents with
their looks (the ones talked to last first, a tap opens the chat) and the look
beside each conversation that moved. These tests keep patch 0013 honest about
what it touches, the renderer sharing one composed frame per look, and the
Home strip wired to the Runtime's agent list.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay" / "web" / "src"
LOOK_TSX = (OVERLAY / "looks" / "Look.tsx").read_text()
HOME = (OVERLAY / "pages" / "Home.tsx").read_text()
HOME_LOGIC = (OVERLAY / "pages" / "home.logic.ts").read_text()
HOME_TEST = (OVERLAY / "pages" / "home.logic.test.ts").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0013-looks-in-conversation.patch").read_text()
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
VISION = (REPO_ROOT / "docs" / "design" / "caelza-vision.md").read_text()


def test_patch_touches_only_the_files_it_claims():
    touched = sorted({line.split()[1][2:] for line in PATCH.splitlines() if line.startswith("+++ b/")})
    assert touched == ["web/package.json", "web/src/components/ChatTabBar.tsx", "web/src/pages/AgentChat.tsx"]
    # The Bot icon leaves the chat and the tab bar: the look is the agent now.
    assert "-import { Send, Square, Bot, User," in PATCH and "+import { Send, Square, User," in PATCH
    assert "-import { Plus, X, Columns2, Square, Bot, Loader2 } from 'lucide-react';" in PATCH
    assert "+import { AgentLook } from '@/looks/Look';" in PATCH
    assert "-              <Bot className" in PATCH or "-            <Bot className" in PATCH
    assert "<Bot " not in "\n".join(line for line in PATCH.splitlines() if line.startswith("+"))


def test_the_transcript_holds_still_and_the_live_turn_talks():
    assert '+            <AgentLook alias={agentAlias} size={28} frame="closed" decorative />' in PATCH, "a bubble's look is still"
    assert "+              <AgentLook alias={agentAlias} size={28} talking decorative />" in PATCH, "the streaming turn's look talks"
    assert "+  agentAlias: string;" in PATCH and "+              agentAlias={agentAlias}" in PATCH, "the bubble knows whose it is"
    assert '+              <AgentLook alias={tab.alias} size={18} frame="closed" decorative className="shrink-0" />' in PATCH, "the tab"
    assert '+                    <AgentLook alias={alias} size={18} frame="closed" decorative className="shrink-0" />' in PATCH, "the picker"
    # The web test list now runs the Home, Bodies and Mind logic tests too.
    added = [line for line in PATCH.splitlines() if line.startswith('+    "test": ')]
    assert len(added) == 1
    for test in ("src/pages/home.logic.test.ts", "src/pages/bodies.logic.test.ts", "src/pages/mind.logic.test.ts"):
        assert test in added[0], test
        assert (OVERLAY / test.removeprefix("src/")).is_file(), test


def test_the_renderer_shares_one_composed_frame_per_look_and_can_be_decorative():
    assert "const composed = new Map<string, Promise<Composed>>();" in LOOK_TSX
    assert "const COMPOSED_LIMIT = 240;" in LOOK_TSX and "composed.clear()" in LOOK_TSX, "the customizer's tweaks do not grow it without bound"
    assert "if (!c.complete && composed.get(id) === mine) composed.delete(id);" in LOOK_TSX, "a frame missing a part is drawn but not kept"
    assert "images.delete(url);" in LOOK_TSX, "a part that failed to load is fetched again next time"
    assert "return { data, complete: loaded.every((img) => img !== null) };" in LOOK_TSX
    assert "composedFrame(key, look, shown)" in LOOK_TSX
    assert "frames.current" not in LOOK_TSX, "no per-instance cache beside the shared one"
    assert 'decorative ? { "aria-hidden": true as const } : { role: "img", "aria-label": title ?? "the agent\'s look", title }' in LOOK_TSX
    agent_look = LOOK_TSX.split("export function AgentLook(")[1]
    for prop in ("frame,", "decorative = false,", "frame?: Frame;", "decorative?: boolean;"):
        assert prop in agent_look, prop
    assert "title={decorative ? undefined : alias}" in agent_look


def test_home_shows_the_agents_with_their_looks_the_last_talked_to_first():
    assert "getMapKeys('agents')" in HOME, "the agents come from the Runtime's config map, like the picker's"
    assert "agentTiles(agents.data ?? [], sessions.data ?? [])" in HOME
    assert "Your agents" in HOME and "Tap one to talk to it." in HOME
    assert '<AgentLook alias={tile.alias} size={40} decorative />' in HOME, "the tile's look is alive, like the agents list"
    assert 'to="/looks"' in HOME and 'to="/setup"' in HOME, "a way to dress them, and a way to make one when there is none"
    assert '<AgentLook alias={s.agent_alias} size={18} frame="closed" decorative className="shrink-0" />' in HOME, "the conversations that moved"
    assert "export function agentTiles(" in HOME_LOGIC and "export function agoLabel(" in HOME_LOGIC
    assert "if (a.last && b.last) return b.last.at.localeCompare(a.last.at) || a.i - b.i;" in HOME_LOGIC, "most recent first, config order after"
    assert "`/agent/${encodeURIComponent(alias)}`" in HOME_LOGIC
    assert re.search(r"^test\('the agents on Home", HOME_TEST, re.M) and "agoLabel(" in HOME_TEST


def test_manifest_and_vision_carry_the_slice():
    rt = MANIFEST["components"]["runtime"]
    assert rt["conversation_patch"] == "runtime/patches/0013-looks-in-conversation.patch"
    assert (REPO_ROOT / rt["conversation_patch"]).is_file()
    assert "**Shipped (M8d" in VISION
    assert "the look in the message bubbles and the Home tiles" not in VISION.split("**Open:**")[-1][:400]
