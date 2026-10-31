"""M7b: the Android app's Body carries the Python Body's device-tool contract.

`android/app/src/main/java/tech/enlightenedrepublic/caelza/body/` is the
`device` group in Kotlin, served over Shizuku on loopback. Two fixtures under
`android/app/src/test/fixtures/` (written by `scripts/android_body_fixtures.py`)
pin the contract from both sides: this file checks they are current against
the Python server, the Gradle tests check the Kotlin port against them. The
rest here reads the Kotlin sources the way `test_bodies_page.py` reads the
gateway's Rust: the names and classes served, the state-dir layout, the port.
"""
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

import pytest

from caelza_body import fleet
from caelza_body import mcp_server as srv
from caelza_body.agent import playbooks as pb
from caelza_body.agent import tools

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "android" / "app"
FIXTURES = APP / "src" / "test" / "fixtures"
KT = APP / "src" / "main" / "java" / "tech" / "enlightenedrepublic" / "caelza"
BODY_SRC = KT / "body"
TOOLS_KT = (BODY_SRC / "BodyTools.kt").read_text()
HOME_KT = (BODY_SRC / "BodyHome.kt").read_text()
SERVER_KT = (BODY_SRC / "BodyServer.kt").read_text()
STORE_KT = (KT / "runtime" / "RuntimeStore.kt").read_text()
CLI_KT = (KT / "runtime" / "CaelzaCli.kt").read_text()
LLAMA_KT = (KT / "model" / "LlamaRuntime.kt").read_text()
LADDER_KT = (KT / "model" / "ModelLadder.kt").read_text()
REGENERATE = "stale fixture: run `python scripts/android_body_fixtures.py` and commit the result"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import android_body_fixtures as fixtures  # noqa: E402
import model_ladder  # noqa: E402

FLEET_TOOLS = {"device_pair", "device_unpair", "device_join", "device_tag"}
#: The groups the app's Body serves (M7b the device tools, M7c the sensors).
GROUPS = ("sensors", "device")


@pytest.fixture
def device_group(tmp_path):
    names = srv.register_tools(srv.load_settings(tmp_path / "home", REPO_ROOT), GROUPS)
    yield names
    tools.reset()


def _kotlin_specs() -> dict[str, str]:
    """`Spec("device_x", Safety.CLASS, ...)` in BodyTools.kt → {name: class}."""
    found = re.findall(r'Spec\(\s*"((?:device|sensors)_[a-z_]+)",\s*Safety\.(READ_ONLY|DESTRUCTIVE|NEUTRAL)', TOOLS_KT)
    assert found, "no Spec(...) entries found in BodyTools.kt"
    return dict(found)


def _kotlin_const(source: str, name: str) -> str:
    m = re.search(rf'const val {name}\s*=\s*"([^"]*)"', source) or re.search(rf"const val {name}\s*=\s*(\d+)", source)
    assert m, f"{name} not found"
    return m.group(1)


# --- the fixtures are current ---------------------------------------------------

def test_tool_fixture_matches_the_python_servers_list_tools(device_group):
    listed = sorted((t.model_dump(mode="json", exclude_none=True) for t in srv.mcp_tools()), key=lambda t: t["name"])
    assert json.loads((FIXTURES / "body-tools.json").read_text()) == listed, REGENERATE
    assert {t["name"] for t in listed} == set(device_group)


def test_tables_fixture_matches_the_playbook_module():
    assert json.loads((FIXTURES / "debloat-tables.json").read_text()) == pb.export_tables(), REGENERATE
    export = pb.export_tables()
    assert set(export["remove"]) == set(pb.REMOVE) and set(export["optional"]) == set(pb.OPTIONAL)
    assert export["health_script"] == pb.HEALTH_SCRIPT and export["admin_grep"] == pb.ADMIN_GREP


def test_ladder_fixture_matches_the_model_ladder():
    """M7d: the app's ModelLadder.kt is the Python ladder's phone branch; the fixture carries the pins and sample picks."""
    assert json.loads((FIXTURES / "model-ladder.json").read_text()) == fixtures.ladder(), REGENERATE
    # The Kotlin pins are the Python pins, literally.
    for tier, g in model_ladder.GGUF.items():
        assert f'"{g["sha256"]}"' in LADDER_KT and g["file"] in LADDER_KT and str(g["bytes"]).replace("_", "") in LADDER_KT.replace("_", ""), tier
    assert 'GUIDE_TIER = "1.5b"' in LADDER_KT and 'SERVER_PORT = 8080' in LADDER_KT and "CONTEXT = 4096" in LADDER_KT


def test_the_app_carries_caels_persona_as_the_installer_writes_it():
    """The bundled SOUL.md is guide/cael.system.md; the IDENTITY.md card is model-setup.sh's heredoc."""
    assert (APP / "src" / "main" / "assets" / "cael.system.md").read_text() == (REPO_ROOT / "guide" / "cael.system.md").read_text(), \
        "copy guide/cael.system.md to android/app/src/main/assets/cael.system.md"
    setup = (REPO_ROOT / "scripts" / "model-setup.sh").read_text()
    _, _, rest = setup.partition("\"$ws/IDENTITY.md\" <<'EOF'\n")
    card, _, _ = rest.partition("EOF\n")
    kotlin = re.search(r'const val IDENTITY = ((?:"[^"\n]*"\s*\+?\s*)+)', CLI_KT)
    assert kotlin, "CaelzaCli.IDENTITY not found"
    assembled = "".join(json.loads(part) for part in re.findall(r'"(?:[^"\\]|\\.)*"', kotlin.group(1)))
    assert assembled == card
    # The local model door writes the same `caelza config set` paths model-setup.sh writes.
    first_run = (KT / "firstrun" / "FirstRun.kt").read_text()
    for path in ("providers.models.llamacpp.local.model", "providers.models.llamacpp.guide.model", "agents.main.model_provider",
                 "agents.cael.model_provider", "agents.cael.risk_profile", "risk_profiles.guide.level", "risk_profiles.guide.deny_all_tools"):
        assert path in first_run and (path.replace("llamacpp.", "$RUNNER.") in setup or path in setup), path
    assert "--no-interactive" in CLI_KT


# --- the Kotlin Body serves the device group, less the fleet tools, in the same classes

def test_kotlin_serves_the_device_group_minus_the_fleet_tools(device_group):
    specs = _kotlin_specs()
    assert set(specs) == set(device_group) - FLEET_TOOLS
    assert {n for n in specs if n.startswith("sensors_")} == {n for n in device_group if n.startswith("sensors_")}
    # Every sensor carries the `device` argument accept_device adds, with its wording.
    for name in (n for n in specs if n.startswith("sensors_")):
        schema = tools._SCHEMAS[name]["function"]["parameters"]
        assert schema["properties"]["device"]["description"].startswith("`self` (this phone)")
        assert f'"{name}", Safety.' in TOOLS_KT and "an ADB-paired phone cannot answer this" in TOOLS_KT
    not_served = re.search(r"val NOT_SERVED = listOf\((.*?)\)", TOOLS_KT, re.S)
    assert not_served and set(re.findall(r'"([a-z_]+)"', not_served.group(1))) == FLEET_TOOLS
    for name, cls in specs.items():
        table = {"READ_ONLY": srv.READ_ONLY, "DESTRUCTIVE": srv.DESTRUCTIVE, "NEUTRAL": srv.NEUTRAL}[cls]
        assert name in table, f"{name} is {cls} in Kotlin but not in the Python Body"


def test_kotlin_layout_port_and_names_are_the_python_bodys():
    assert _kotlin_const(HOME_KT, "TOKEN_FILE") == fleet.TOKEN_FILE
    assert _kotlin_const(HOME_KT, "AUDIT_LOG") == "logs/device-actions.log"
    assert _kotlin_const(HOME_KT, "DIR_NAME") == ".caelza-body"
    assert int(_kotlin_const(SERVER_KT, "PORT")) == fleet.DEFAULT_PORT
    assert int(_kotlin_const(STORE_KT, "BODY_PORT")) == fleet.DEFAULT_PORT
    assert _kotlin_const(SERVER_KT, "MCP_PATH") == fleet.MCP_PATH
    assert _kotlin_const(SERVER_KT, "HEALTH_PATH") == fleet.HEALTH_PATH
    assert _kotlin_const(SERVER_KT, "SERVER_NAME") == srv.SERVER_NAME
    assert _kotlin_const(SERVER_KT, "SERVER_VERSION") == srv.SERVER_VERSION
    # The Runtime reaches it the way the hub example reaches a phone: transport http, the token in headers.Authorization.
    assert 'transport = "http"' in STORE_KT and "headers = { Authorization = \"Bearer $token\" }" in STORE_KT
    assert "url = \"http://127.0.0.1:$port/mcp\"" in STORE_KT


def test_the_runtime_wiring_gates_the_bodys_classes():
    """The risk profile the app writes is generated from the Kotlin specs: READ_ONLY auto-approved, DESTRUCTIVE always asked."""
    assert "BodyTools.names(BodyTools.Safety.READ_ONLY)" in STORE_KT.split("auto_approve")[1].split("always_ask")[0]
    assert "BodyTools.names(BodyTools.Safety.DESTRUCTIVE)" in STORE_KT.split("always_ask")[1]
    assert 'level = \\"supervised\\"' in STORE_KT


# --- the repo points at it -------------------------------------------------------

def test_manifest_and_ci_point_at_the_app_body():
    manifest = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())["android"]
    assert manifest["body"] == "android/app/src/main/java/tech/enlightenedrepublic/caelza/body"
    assert manifest["body_port"] == fleet.DEFAULT_PORT
    assert manifest["body_tools"] == len(_kotlin_specs())
    assert manifest["body_fixtures"] == "scripts/android_body_fixtures.py"
    # M7d: the first run and the local model runner.
    assert manifest["first_run"] == "android/app/src/main/java/tech/enlightenedrepublic/caelza/firstrun"
    pin = re.search(r'LlamaPin\("(b\d+)", "([0-9a-f]{64})", ([\d_]+)L\)', LLAMA_KT)
    assert pin, "LlamaPin.CURRENT not found"
    assert manifest["llama_pin"] == pin.group(1) and manifest["llama_sha256"] == pin.group(2)
    assert manifest["model_server_port"] == 8080 and manifest["models_dir"] == ".caelza/models"
    # The Gradle tests replay the repo's recordings, so the android job runs when those change too.
    workflow = (REPO_ROOT / ".github" / "workflows" / "android.yml").read_text()
    for trigger in ("push", "pull_request"):
        block = workflow.split(f"  {trigger}:", 1)[1].split("\n\n", 1)[0]
        for path in ("android/**", "tests/fixtures/playbooks/**", "docs/examples/revvl-7-debloat/**"):
            assert f'"{path}"' in block, (trigger, path)
