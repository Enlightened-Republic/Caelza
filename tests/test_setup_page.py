"""The simplified setup (vision M4 phase 4a): Cael's screens at /setup.

One curated catalog (bundle/models.json) feeds two wheels in two places: the
dashboard's /setup (an overlay page plus patch 0009) and the Android app's
first run (ModelCatalog.kt over a pinned copy of the file). These tests keep
the catalog well-formed, the copies equal, the patch honest about what it
touches, the strings the page uses present, and the tag vocabulary the same
in the script, the page and the app.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = REPO_ROOT / "bundle" / "models.json"
ANDROID_ASSET = REPO_ROOT / "android" / "app" / "src" / "main" / "assets" / "models.json"
OVERLAY = REPO_ROOT / "runtime" / "overlay" / "web" / "src" / "pages" / "setup"
PATCH = (REPO_ROOT / "runtime" / "patches" / "0009-simplified-setup.patch").read_text()
PAGE = (OVERLAY / "Setup.tsx").read_text()
LOGIC = (OVERLAY / "setup.logic.ts").read_text()
LOGIC_TEST = (OVERLAY / "setup.logic.test.ts").read_text()
WHEEL = (OVERLAY / "WheelPicker.tsx").read_text()
BRAND_CSS = (REPO_ROOT / "runtime" / "overlay" / "web" / "src" / "caelza-brand.css").read_text()
BUILD_SH = (REPO_ROOT / "runtime" / "build.sh").read_text()
KOTLIN = (REPO_ROOT / "android" / "app" / "src" / "main" / "java" / "tech" / "enlightenedrepublic" / "caelza" / "firstrun" / "ModelCatalog.kt").read_text()
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import model_catalog  # noqa: E402

catalog = model_catalog.load(CATALOG)


def test_the_catalog_is_well_formed():
    assert model_catalog.check(catalog) == []
    assert [p["id"] for p in catalog["providers"]] == ["anthropic", "openai", "gemini", "openrouter", "groq", "deepseek", "mistral", "xai"]
    # The Runtime says gemini where models.dev says google.
    assert next(p for p in catalog["providers"] if p["id"] == "gemini")["models_dev"] == "google"
    assert model_catalog.picks(catalog)["anthropic"] == "claude-sonnet-5-5"


def test_the_checker_catches_the_mistakes_an_edit_makes():
    broken = json.loads(json.dumps(catalog))
    p = broken["providers"][0]
    p["models"][1]["tag"] = "best"  # two best picks
    p["models"].append({"id": "claude-sonnet-5-5", "label": "dup"})  # a repeat
    p["models"].append({"id": "x", "label": "x", "tag": "cheapest"})  # a tag that is not one
    broken["providers"].append(dict(broken["providers"][1], id="openai"))  # a provider twice
    broken["providers"][2]["key_page"] = "http://plain"
    broken["providers"][3]["models"].append("gpt-5")  # a bare string where an object goes
    broken["providers"].append("mistral")  # the same, one level up
    problems = model_catalog.check(broken)
    assert any("model entries must be objects" in m and "gpt-5" in m for m in problems)
    assert any("providers[9]: must be an object, not str" in m for m in problems), problems
    assert any("exactly one model must be tagged 'best'" in m for m in problems)
    assert any("listed twice" in m and "claude-sonnet-5-5" in m for m in problems)
    assert any("unknown tag 'cheapest'" in m for m in problems)
    assert any("provider openai: listed twice" in m for m in problems)
    assert any("key_page must be an https URL" in m for m in problems)
    # The first row must be the best pick: the wheel rests on it.
    reordered = json.loads(json.dumps(catalog))
    reordered["providers"][0]["models"].reverse()
    assert any("first model must be the 'best' pick" in m for m in model_catalog.check(reordered))


def test_every_id_is_checked_against_models_dev():
    models_dev = {
        "anthropic": {"models": {m["id"]: {} for m in catalog["providers"][0]["models"]}},
        "google": {"models": {"gemini-4-argon": {}}},
    }
    problems = model_catalog.check_against_models_dev(catalog, models_dev)
    assert not any("provider anthropic" in m for m in problems)
    assert any("models.dev/google does not list 'gemini-3.8-flash'" in m for m in problems)
    assert any("models.dev has no provider 'openai'" in m for m in problems)
    # The CLI: the shape alone passes offline.
    out = subprocess.run([sys.executable, "-I", str(REPO_ROOT / "scripts" / "model_catalog.py"), "check"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("ok: 8 providers")


def test_the_app_carries_the_same_catalog_byte_for_byte():
    assert ANDROID_ASSET.read_bytes() == CATALOG.read_bytes(), "run python3 scripts/model_catalog.py sync"
    assert 'const val ASSET = "models.json"' in KOTLIN


def test_the_tag_vocabulary_is_one_in_the_script_the_page_and_the_app():
    tags = list(model_catalog.TAGS)
    assert tags == list(catalog["tags"])
    assert f'export const TAGS: readonly Tag[] = {json.dumps(tags)};' in LOGIC
    for tag in tags:
        assert f'"{tag}"' in LOGIC.split("export type Tag =")[1].split(";")[0]
        assert f"'setup.tag_{tag}': " in PATCH, tag
        assert f'"{tag}" to "{catalog["tags"][tag]}"' in KOTLIN, tag
        assert f".cz-tag-{tag} {{" in BRAND_CSS, tag


def test_the_page_imports_the_catalog_the_build_copies():
    assert 'import catalogJson from "./models.json";' in PAGE
    assert 'cp "$ROOT/bundle/models.json" "$WORK/web/src/pages/setup/models.json"' in BUILD_SH
    # The logic test finds the catalog beside it in the staged tree or in the bundle from the overlay.
    assert 'new URL("./models.json", here)' in LOGIC_TEST and "bundle/models.json" in LOGIC_TEST


def test_patch_touches_only_the_files_it_claims():
    touched = sorted({line.split()[1][2:] for line in PATCH.splitlines() if line.startswith("+++ b/")})
    assert touched == [
        "web/package.json",
        "web/src/App.tsx",
        "web/src/components/layout/Sidebar.tsx",
        "web/src/lib/i18n.ts",
        "web/src/router/lazyPages.tsx",
        "web/src/router/router.tsx",
        "web/tsconfig.app.json",
    ]


def test_the_patch_routes_setup_lands_fresh_installs_on_it_and_lists_the_test():
    assert '+      <Route path="/setup" element={<Setup />} />' in PATCH
    assert "+export const Setup = lazy(() => import('../pages/setup/Setup'));" in PATCH
    assert '-          navigate("/quickstart", { replace: true });' in PATCH
    assert '+          navigate("/setup", { replace: true });' in PATCH
    assert "+      { to: '/setup', icon: Rocket, labelKey: 'nav.setup' }," in PATCH
    assert '+    "resolveJsonModule": true,' in PATCH
    assert "src/pages/quickstart/doors.logic.test.ts src/pages/setup/setup.logic.test.ts" in PATCH
    # The full wizard stays where it was.
    assert '<Route path="/quickstart" element={<Quickstart />} />' not in "".join(l for l in PATCH.splitlines() if l.startswith("-"))


def test_every_string_the_page_uses_is_in_the_patch():
    used = set(re.findall(r'"(setup\.[a-z_]+)"', PAGE))
    used |= set(re.findall(r"\bt\(\"(setup\.[a-z_]+)\"", PAGE))
    added = set(re.findall(r"^\+    '(setup\.[a-z_]+)': ", PATCH, re.M))
    assert used and used <= added, sorted(used - added)
    assert "+    'nav.setup': 'Set up'," in PATCH
    # Cael's voice on the screens that matter.
    for key, phrase in (
        ("setup.title_doors", "Hi, I'm Cael"),
        ("setup.body_key", "stays encrypted on this device"),
        ("setup.body_model", "best all-rounder"),
        ("setup.advanced", "Advanced setup"),
    ):
        line = re.search(rf"^\+    '{re.escape(key)}': (.*),$", PATCH, re.M).group(1)
        assert phrase in json.loads(line), key


def test_the_page_stages_upstreams_shapes_and_the_wheel_is_a_listbox():
    # The key door writes <provider>.default, the local door <runner>.local (the doors' logic).
    assert 'export const KEY_ALIAS = "default";' in LOGIC
    assert "stagedLocalProvider(runner, pick.model" in PAGE and "stagedKeyProvider(providerId, model" in PAGE
    # ... unless that alias exists already: the Runtime refuses one that does, so the next free one is taken.
    assert "export function providerAlias(" in LOGIC
    assert "providerAlias(aliases, providerId)" in PAGE and "providerAlias(aliases, runner, LOCAL_ALIAS)" in PAGE
    assert "state?.model_providers ?? []" in PAGE, "the aliases the config holds come from the quickstart state"
    # A key never rides along to the next provider; the live list never moves the wheel off the owner's choice;
    # a provider the Runtime lists nothing for goes to the typed box; Enter does what the button does.
    assert 'setKey("");' in PAGE
    assert "!mRows.some((r) => r.id === model)" in PAGE
    assert "if (live !== null && mRows.length === 0) setTyped(true);" in PAGE
    assert "live === null && mRows.length === 0" in PAGE
    assert PAGE.count("onKeyDown={onEnter(") == 3
    assert "quickstartApply(submission(" in PAGE
    assert 'to="/quickstart"' in PAGE, "the full wizard is one tap away"
    # Everything the owner is not asked takes a default the daemon lists.
    for fn in ("pickPreset", "pickMemory", "pickRuntime", "agentName"):
        assert f"export function {fn}(" in LOGIC, fn
    assert 'role="listbox"' in WHEEL and 'role="option"' in WHEEL and "scroll-snap-type: y mandatory" in BRAND_CSS
    assert "ArrowDown" in WHEEL and "ArrowUp" in WHEEL


def test_manifest_points_at_the_setup():
    rt = MANIFEST["components"]["runtime"]
    assert rt["setup_page"] == "runtime/overlay/web/src/pages/setup/Setup.tsx"
    assert rt["setup_patch"] == "runtime/patches/0009-simplified-setup.patch"
    assert rt["model_catalog"] == "bundle/models.json"
    assert MANIFEST["android"]["model_catalog_asset"] == "android/app/src/main/assets/models.json"
    assert (REPO_ROOT / rt["setup_page"]).is_file() and (REPO_ROOT / rt["setup_patch"]).is_file()
