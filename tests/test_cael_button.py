"""Cael in the top bar: "explain this screen" on every page (vision §3.4).

The button is Cael's look; the panel explains the screen in his words with
no model needed and lets the owner ask him anything about it over the
gateway's chat socket. These tests keep the strings complete for every
screen the logic names, the patch honest about what it touches, and the
panel wired to the one guide conversation.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay" / "web" / "src"
LOGIC = (OVERLAY / "guide" / "guide.logic.ts").read_text()
BUTTON = (OVERLAY / "guide" / "CaelButton.tsx").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0012-cael-explain.patch").read_text()
BRAND_CSS = (OVERLAY / "caelza-brand.css").read_text()
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
SOUL = (REPO_ROOT / "guide" / "cael.system.md").read_text()

SCREENS = re.findall(r'^  \| "([a-z-]+)"$', LOGIC.split("export type Screen =")[1].split(";")[0], re.M)


def test_every_screen_has_its_words_and_a_next_step():
    assert len(SCREENS) >= 25 and "home" in SCREENS and "other" in SCREENS
    added = dict(re.findall(r"^\+    '(guide\.[a-z_]+)': (.*),$", PATCH, re.M))
    for screen in SCREENS:
        key = screen.replace("-", "_")
        for prefix in ("guide.screen_", "guide.next_"):
            assert f"{prefix}{key}" in added, f"{prefix}{key}"
            text = json.loads(added[f"{prefix}{key}"])
            assert 20 <= len(text) <= 400, (prefix, key, len(text))
    # The panel's own strings.
    for key in ("guide.open", "guide.title", "guide.this_screen", "guide.ask_placeholder", "guide.send", "guide.not_set_up", "guide.set_up", "guide.closed", "guide.timeout", "guide.go", "guide.close"):
        assert key in added, key
    used = set(re.findall(r'"(guide\.[a-z_]+)"', BUTTON))
    assert used <= set(added), sorted(used - set(added))
    # Cael's voice: he explains and points at the next step; he does not act for the owner.
    for key, value in added.items():
        text = json.loads(value).lower()
        assert "zeroclaw" not in text, key
    assert "nothing here is a trick question" in json.loads(added["guide.screen_setup"]).lower()


def test_the_routes_map_to_screens_the_top_bar_names():
    for route in ("bodies", "memory", "procedures", "agents", "agent", "looks", "shop", "setup", "quickstart", "config", "tools", "skills", "sops", "runs", "integrations", "plugins", "cron", "dashboard", "logs", "pairing", "doctor", "canvas"):
        assert f'  {route}: "{route}",' in LOGIC, route
    assert '"acp-console": "acp",' in LOGIC
    assert 'if (first === "setup" && segments.length > 1) return "config";' in LOGIC, "the config explorer's deep link stays config"
    for screen in SCREENS:
        assert f'  {screen.replace("-", "_") if screen != "acp" else "acp"}: "nav.' in BUTTON or screen == "other", screen


def test_the_panel_asks_cael_over_the_chat_socket_in_one_guide_conversation():
    assert 'new WebSocketClient({ agentAlias: "cael", sessionId: guideSessionId(storage), autoReconnect: false })' in BUTTON
    assert 'export const GUIDE_SESSION_STORAGE = "caelza_guide_session";' in LOGIC
    assert "ws.sendMessage(question(title, pathname, q))" in BUTTON
    assert "foldReply(current, msg)" in BUTTON
    assert "caelReady(agents)" in BUTTON and 'getQuickstartState()' in BUTTON, "no Cael, no ask box: the setup link instead"
    assert '<AgentLook alias="cael" size={56} talking={busy} />' in BUTTON, "Cael talks while he answers"
    assert "ANSWER_TIMEOUT_MS = 90_000" in BUTTON
    assert 'case "chunk":' in LOGIC and 'case "done":' in LOGIC and 'case "error":' in LOGIC and 'case "chunk_reset":' in LOGIC


def test_patch_touches_only_the_files_it_claims():
    touched = sorted({line.split()[1][2:] for line in PATCH.splitlines() if line.startswith("+++ b/")})
    assert touched == ["web/package.json", "web/src/components/layout/Header.tsx", "web/src/lib/i18n.ts"]
    assert "+import { CaelButton } from '@/guide/CaelButton';" in PATCH
    assert "+          <CaelButton />" in PATCH
    assert "src/looks/looks.logic.test.ts src/guide/guide.logic.test.ts" in PATCH
    for cls in (".cz-cael-btn {", ".cz-guide-panel {", ".cz-guide-backdrop {", ".cz-guide-a {"):
        assert cls in BRAND_CSS, cls


def test_manifest_points_at_the_guide_button():
    rt = MANIFEST["components"]["runtime"]
    assert rt["guide_button"] == "runtime/overlay/web/src/guide/CaelButton.tsx"
    assert rt["guide_patch"] == "runtime/patches/0012-cael-explain.patch"
    assert (REPO_ROOT / rt["guide_button"]).is_file() and (REPO_ROOT / rt["guide_patch"]).is_file()
    # The guide's own rules: he explains, he does not act.
    assert "You do not run tools" in SOUL
