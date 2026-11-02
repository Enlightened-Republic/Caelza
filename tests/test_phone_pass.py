"""UI phase 3b: the phone-first pass. The brand stylesheet carries the phone
rules, patch 0006 carries what CSS cannot, the measuring tool and the
reference screenshots are in the repo, and the Home and Procedures pages
explain a disabled SOP engine instead of printing an error."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay"
CSS = (OVERLAY / "web" / "src" / "caelza-brand.css").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0006-phone-first.patch").read_text()
HOME = (OVERLAY / "web" / "src" / "pages" / "Home.tsx").read_text()
PROCEDURES = (OVERLAY / "web" / "src" / "pages" / "Procedures.tsx").read_text()
LOGIC = (OVERLAY / "web" / "src" / "pages" / "home.logic.ts").read_text()
TOOLS = REPO_ROOT / "runtime" / "tools" / "phone-shots"
SCREENS = REPO_ROOT / "docs" / "design" / "screens" / "390"


def test_the_stylesheet_carries_the_phone_rules():
    phone = CSS.split("Phone-first")[1]
    assert "@media (max-width: 640px)" in phone
    assert "@media (pointer: coarse), (max-width: 640px)" in phone
    # 16 px gutters on the page root only, never the cards inside it.
    assert re.search(r"main > \.p-6,\s*main > \* > \.p-6 \{\s*padding: 1rem;", phone)
    # Tables scroll inside their card.
    assert re.search(r"main table \{[^}]*display: block;[^}]*overflow-x: auto;", phone, re.S)
    # Thumb-sized controls, text buttons and flex links included; checkboxes left alone.
    assert "min-height: 2.25rem" in phone and "min-width: 2.25rem" in phone
    assert "a.inline-flex" in phone and 'input:not([type="checkbox"])' in phone


def test_patch_touches_only_the_files_it_claims():
    touched = sorted({line.split()[1][2:] for line in PATCH.splitlines() if line.startswith("+++ b/")})
    assert touched == [
        "web/src/components/layout/Header.tsx",
        "web/src/components/layout/Layout.tsx",
        "web/src/components/ui/PageHeader.tsx",
        "web/src/contexts/ThemeContext.tsx",
        "web/src/pages/AgentChat.tsx",
        "web/src/pages/Runs.tsx",
        "web/src/pages/Tools.tsx",
    ]
    # The page header's actions slot wraps and shrinks instead of overflowing.
    assert '-        <div className="flex items-center gap-2 flex-shrink-0">{actions}</div>' in PATCH
    assert '+        <div className="flex items-center gap-2 flex-wrap min-w-0 max-w-full">{actions}</div>' in PATCH
    # The language button keeps only its globe on a phone.
    assert '+              <span className="hidden sm:inline">{locale.toUpperCase()}</span>' in PATCH
    # Tools' search spans the row on a phone; the chat toolbar wraps and its model name yields.
    assert '+            <div className="relative w-full sm:w-64">' in PATCH
    assert "flex-wrap gap-y-2 px-4 py-2" in PATCH and "max-w-[40vw] sm:max-w-[180px]" in PATCH
    # Runs gets the page padding every other page has; SOPs, Runs and Plugins get titles.
    assert '+    <div className="p-6 space-y-4">' in PATCH
    assert PATCH.count("+  runs: 'nav.runs',") == 2 and PATCH.count("+  sops: 'nav.sops',") == 2
    # The mono face is vendored; nothing is fetched from a font CDN any more.
    assert "-  if (font === 'jetbrains') loadGoogleFont('JetBrains Mono');" in PATCH
    assert "+  if (font === 'jetbrains')" not in PATCH


def test_a_disabled_sop_engine_is_explained_not_shouted():
    assert "export function sopEngineOff" in LOGIC and "SOP subsystem not enabled" in LOGIC
    for page in (HOME, PROCEDURES):
        assert "sopEngineOff(" in page and ("SOP_OFF_TEXT" in page or "sopOffText(" in page)
    # Procedures tells a standalone gateway (procedures listed, engine absent) from a config with the engine off.
    assert "sopOffText(" in PROCEDURES and "SOP_ENGINE_NOT_RUNNING_TEXT" in LOGIC and "caelza daemon" in LOGIC


def test_the_measuring_tool_and_the_reference_screens_are_in_the_repo():
    for name in ("shoot.js", "mock-proxy.js", "README.md"):
        assert (TOOLS / name).is_file(), name
    for script in ("shoot.js", "mock-proxy.js"):
        subprocess.run(["node", "--check", str(TOOLS / script)], check=True)
    shoot = (TOOLS / "shoot.js").read_text()
    # Every top-level section the vision names is on the route list.
    for route in ("'/'", "'/bodies'", "'/memory'", "'/procedures'", "'/dashboard'", "'/agents'"):
        assert route in shoot, route
    assert "390" in shoot and "deviceScaleFactor" in shoot
    expected = {"home", "bodies", "memory", "procedures", "procedures-run", "dashboard", "agent-chat", "tools", "runs", "drawer",
                "quickstart-doors", "quickstart-local-door",
                "setup-doors", "setup-provider", "setup-model", "setup-key", "setup-local",
                "looks", "looks-dress", "shop", "agents", "cael-explain"}
    assert {p.stem for p in SCREENS.glob("*.png")} == expected
    for png in SCREENS.glob("*.png"):
        assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", png.name
        assert png.stat().st_size < 150_000, f"{png.name} is {png.stat().st_size} bytes; keep the set at 1x"
    assert (SCREENS.parent / "README.md").is_file()
