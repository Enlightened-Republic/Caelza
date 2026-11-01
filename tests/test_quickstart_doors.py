"""The two doors on quickstart's first screen (vision §3.4, the M1.5 carry-over).

The dashboard's Quickstart page opened on a provider dropdown. Now its first
screen is two doors: "Free and local" stages the ladder's DeepSeek R1 for this
device as `<runner>.local`, the alias scripts/model-setup.sh and the app's
first run write, with Cael's honest line; "Bring your own key" is upstream's
provider form as it was. The doors are an overlay (Doors.tsx + doors.logic.ts,
tested with node) and a patch to the page, the strings and the web test list;
these tests keep the overlay's ladder in step with scripts/model_ladder.py and
the patch honest about what it touches.
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay" / "web" / "src" / "pages" / "quickstart"
PATCH = (REPO_ROOT / "runtime" / "patches" / "0007-quickstart-doors.patch").read_text()
LOGIC = (OVERLAY / "doors.logic.ts").read_text()
LOGIC_TEST = (OVERLAY / "doors.logic.test.ts").read_text()
DOORS = (OVERLAY / "Doors.tsx").read_text()

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import model_ladder  # noqa: E402


def test_patch_touches_only_the_files_it_claims():
    touched = sorted({line.split()[1][2:] for line in PATCH.splitlines() if line.startswith("+++ b/")})
    assert touched == ["web/package.json", "web/src/lib/i18n.ts", "web/src/pages/quickstart/Quickstart.tsx"]


def test_the_page_opens_on_the_doors_and_both_stage_through_one_callback():
    assert '+import Doors from "./Doors";' in PATCH and '+import { doorOf } from "./doors.logic";' in PATCH
    assert "+  const stageProvider = (p: StagedProvider) => {" in PATCH
    assert "-          <ProviderForm\n+          <Doors\n             state={state}\n-            onStage={(p) => {" in PATCH, \
        "the page renders the doors where the provider form was; the inline stage callback is hoisted"
    assert '+            keyDoor={<ProviderForm state={state} onStage={stageProvider} />}' in PATCH
    assert "+            onStage={stageProvider}" in PATCH
    assert 'doorOf(form.provider) === "local" ? "quickstart.door_local" : "quickstart.door_key"' in PATCH, "the summary names the door"
    # The web test list runs the door's logic tests beside upstream's.
    assert "src/pages/quickstart/runtime-selection.test.ts src/pages/quickstart/doors.logic.test.ts" in PATCH


def test_every_string_the_doors_use_is_in_the_patch():
    used = set(re.findall(r't\("(quickstart\.door_[a-z_]+)"\)', DOORS))
    used |= set(re.findall(r'"(quickstart\.door_[a-z_]+)"', DOORS))
    added = set(re.findall(r"^\+    '(quickstart\.door_[a-z_]+)': ", PATCH, re.M))
    assert used and used <= added, sorted(used - added)
    assert "quickstart.door_local" in added and "quickstart.door_key" in added
    then = re.search(r"^\+    'quickstart\.door_then': \"(.*)\",$", PATCH, re.M).group(1)
    assert "sh scripts/model-setup.sh" in then and "creates Cael" in then, "the door says what fetches the model and makes Cael"
    assert "two doors" in re.search(r"^\+    'quickstart\.description': \"(.*)\",$", PATCH, re.M).group(1)


def test_the_overlays_ladder_is_the_python_ladder():
    """Names, thresholds and the honest notes, word for word."""
    for tier, name in model_ladder.OLLAMA.items():
        assert f'"{tier}": "{name}"' in LOGIC, tier
    for tier, g in model_ladder.GGUF.items():
        assert f'"{tier}": "{g["name"]}"' in LOGIC, tier
    assert f'GUIDE_TIER = "{model_ladder.GUIDE_TIER}"' in LOGIC
    assert 'LOCAL_ALIAS = "local"' in LOGIC
    for ram, platform in ((3_500, "termux"), (7_600, "termux"), (4 * 1024, "linux"), (7_600, "linux"),
                          (12 * 1024, "linux"), (16 * 1024, "linux")):
        p = model_ladder.pick(ram, platform)
        assert p.provider_alias_agent == f"{p.runner}.local"
        for note in p.notes:
            assert note in LOGIC, (platform, ram, note)
        assert p.agent.name in LOGIC and p.guide.name in LOGIC
    # The thresholds the picks hinge on.
    for edge in ("ramMb >= 6 * 1024", "ramMb >= 8 * 1024", "ramMb >= 16 * 1024"):
        assert edge in LOGIC, edge
    # The node tests exercise the same sample points as the Python ladder.
    for sample in ("3_500", "7_600", "12 * 1024", "16 * 1024", "4 * 1024"):
        assert sample in LOGIC_TEST, sample


def test_the_local_door_stages_the_runner_alias_and_keeps_the_key_door_upstreams():
    assert 'return { provider_type: runner, alias: LOCAL_ALIAS, model: model.trim(), fields };' in LOGIC
    assert "stagedLocalProvider(runner, model, nonEmptyFields(fieldValues))" in DOORS
    assert 'quickstartFields({ section: "model_provider", type_key: runner })' in DOORS, "the daemon's enum rows are seeded like upstream's form"
    assert "keyDoor" in DOORS and "ProviderForm" not in DOORS, "the key door is upstream's form, handed in by the page"
    assert '"llamacpp"' in LOGIC and '"ollama"' in LOGIC
    assert "guessDefaults(nav.userAgent, nav.deviceMemory ?? null)" in DOORS, "the browser's guess, with the pickers still showing"
    assert "sm:grid-cols-2" in DOORS, "phone-first: the doors stack at 390 px"


def test_docs_and_the_manifest_name_the_patch():
    assert "0007" in (REPO_ROOT / "runtime" / "README.md").read_text()
    manifest = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
    assert manifest["components"]["runtime"]["quickstart_doors_patch"] == "runtime/patches/0007-quickstart-doors.patch"
    assert manifest["components"]["runtime"]["quickstart_doors"] == "runtime/overlay/web/src/pages/quickstart/Doors.tsx"
    vision = (REPO_ROOT / "docs" / "design" / "caelza-vision.md").read_text()
    assert "quickstart's own first screen still lists providers" not in vision
    assert "0007-quickstart-doors.patch" in vision
