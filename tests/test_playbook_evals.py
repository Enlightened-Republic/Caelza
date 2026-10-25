"""The playbooks' evals: their deterministic half over recorded phone output.

The debloat classifier over the 297-package REVVL 7 snapshot
(`docs/examples/revvl-7-debloat`), the foreground, package, app-ops and health
parsers over recordings in `tests/fixtures/playbooks/`, the risk scorer, and
the four playbook tools end to end over a recorded `adb`. With
`CAELZA_EVAL_SERIAL=<adb serial>` (an emulator's `emulator-5554`, or a phone)
the live evals also run the tools against that device.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from caelza_body.agent import adb as adb_mod
from caelza_body.agent import playbooks as pb
from caelza_body.agent import tools
from caelza_body.agent.adb import Adb
from caelza_body.agent.devices import DeviceRegistry
from caelza_body.agent.tools import device, playbook

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "playbooks"
SNAPSHOT = REPO_ROOT / "docs" / "examples" / "revvl-7-debloat" / "packages-snapshot.txt"
LOG = (REPO_ROOT / "docs" / "examples" / "revvl-7-debloat" / "README.md").read_text()
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def snapshot_packages() -> dict[str, dict]:
    return pb.parse_packages(SNAPSHOT.read_text())


def log_table(heading: str) -> set[str]:
    """The package column of one table in the REVVL debloat log."""
    section = LOG.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]
    return {line.split("`")[1] for line in section.splitlines() if line.startswith("| `")}


# --- the debloat classifier over the REVVL 7 ---------------------------------

def test_snapshot_parses_to_the_297_packages_with_paths():
    pkgs = snapshot_packages()
    assert len(pkgs) == 297
    assert pkgs["com.google.android.gms"]["path"].startswith("/")
    assert pkgs["com.metro.minus1"]["path"].endswith(".apk")


def test_the_log_s_carrier_junk_lands_in_remove_or_disable():
    plan = pb.debloat_plan(snapshot_packages())
    offered = {i["pkg"]: cls for cls in ("remove", "disable") for i in plan[cls]}
    carrier = {
        "com.metro.minus1", "com.metropcs.metrozone", "com.ironsrc.aura.tmo",
        "com.nuance.nmc.sihome.metropcs", "com.vitastudio.mahjong", "in.playsimple.newwordsearch",
        "in.playsimple.triple.tile.matchgame.pair.three.puzzle.object.royale",
        "com.amazon.storm.lightning.client.aosp", "com.tmobile.pr.adapt",
        "com.tmobile.echolocate", "com.tmobile.echolocate.system", "com.tmobile.dm.cm", "com.tmobile.dm.ms.services",
    }
    assert carrier <= set(offered), carrier - set(offered)
    assert {p for p in carrier if p.startswith("com.tmobile.echolocate") or p.startswith("com.tmobile.dm")} == {
        p for p, cls in offered.items() if cls == "disable" and p in carrier}
    for item in plan["remove"] + plan["disable"]:
        assert item["why"] and item["reason"].startswith("phone-debloat: ")


def test_the_log_s_google_apps_are_offered_as_optional_never_planned():
    plan = pb.debloat_plan(snapshot_packages())
    optional = {i["pkg"] for i in plan["optional"]}
    google = {p for p in log_table("Uninstalled") | log_table("Disabled") if p.startswith(("com.google.android", "com.android.chrome"))}
    assert google <= optional, google - optional
    planned = {i["pkg"] for i in plan["remove"] + plan["disable"]}
    assert not planned & google
    # The SIM-unlock pieces are the owner's call too: a locked phone needs them.
    assert {"com.tmobile.rsuapp", "com.tmobile.rsusrv", "com.tmobile.rsuadapter.qualcomm"} <= optional
    for item in plan["optional"]:
        assert "reason" not in item, "optional packages carry no ready-made reason: the owner names them"


def test_nothing_the_phone_needs_is_ever_offered():
    plan = pb.debloat_plan(snapshot_packages())
    offered = {i["pkg"] for cls in ("remove", "disable", "optional") for i in plan[cls]}
    needed = {
        "android", "com.android.systemui", "com.android.launcher3", "com.android.dialer", "com.android.phone",
        "com.android.settings", "com.android.carrierconfig", "com.android.vending", "com.google.android.gms",
        "com.google.android.gsf", "com.google.android.permissioncontroller", "com.google.android.setupwizard",
        "com.google.android.euicc", "com.google.android.webview", "com.google.android.tts",
        "com.google.android.inputmethod.latin", "com.google.android.as", "com.google.android.marvin.talkback",
        "com.tailscale.ipn", "com.qualcomm.qti.telephonyservice", "com.qti.phone", "vendor.qti.iwlan",
        "org.codeaurora.ims", "com.wingtech.carrierconfig", "com.android.providers.telephony",
    }
    assert not needed & offered, needed & offered
    for pkg in needed:
        assert pb.classify(pkg)[0] == "keep", pkg
    # Overlays and vendor pieces are keep by pattern, whatever their name.
    assert pb.classify("com.android.internal.display.cutout.emulation.hole")[0] == "keep"
    assert pb.classify("com.odm.euiccoverlay")[0] == "keep"


def test_counts_add_up_and_review_is_only_the_owner_s_own_apps():
    pkgs = snapshot_packages()
    third = {"com.govee.home", "com.tailscale.ipn"}
    plan = pb.debloat_plan(pkgs, third_party=third, disabled={"com.tmobile.echolocate"}, keep=["com.metro.minus1"])
    listed = sum(len(plan[c]) for c in ("remove", "disable", "optional", "review"))
    assert listed + plan["keep"] + len(plan["already_disabled"]) == plan["total"] == 297
    assert plan["third_party"] == 2
    assert [i["pkg"] for i in plan["review"]] == ["com.govee.home"]
    assert plan["review"][0]["why"].startswith("third-party app the list does not know")
    assert plan["already_disabled"] == ["com.tmobile.echolocate"]
    assert plan["pinned"] == ["com.metro.minus1"]
    assert "com.metro.minus1" not in {i["pkg"] for i in plan["remove"]}, "the owner's keep wins over the table"
    # An unknown system package is kept, not reviewed.
    assert all(i["third_party"] is False for i in plan["remove"] if i["pkg"].startswith("com.tmobile"))


def test_exact_names_win_over_patterns_and_the_first_pattern_wins():
    assert pb.classify("com.tmobile.pr.adapt") == ("remove", pb.REMOVE["com.tmobile.pr.adapt"])
    assert pb.classify("com.tmobile.vvm.application")[0] == "optional"
    assert pb.classify("com.facebook.katana")[0] == "optional"
    assert pb.classify("com.facebook.appmanager")[0] == "remove"
    assert pb.classify("com.dti.att")[0] == "remove"
    assert pb.classify("com.termux.api")[0] == "keep"
    assert pb.classify("org.example.mine") == ("", "")


# --- the parsers over recordings ----------------------------------------------

def test_foreground_parses_both_dumpsys_shapes():
    fg = pb.parse_foreground((FIXTURES / "window-popup.txt").read_text())
    assert fg["package"] == "com.example.flashlightpro"
    assert fg["activity"] == "com.example.flashlightpro.ui.OfferActivity"
    alt = pb.parse_foreground("    topResumedActivity=ActivityRecord{5e6f u0 com.android.launcher3/.uioverrides.QuickstepLauncher t7}")
    assert alt["package"] == "com.android.launcher3" and alt["activity"] == "com.android.launcher3.uioverrides.QuickstepLauncher"
    shade = pb.parse_foreground("  mCurrentFocus=Window{1a2b u0 NotificationShade}\n  mFocusedApp=null")
    assert shade["package"] is None and shade["note"] == "the notification shade is open"
    assert pb.parse_foreground("  mCurrentFocus=null")["note"] == "nothing has focus (screen off?)"


def test_package_appops_and_component_lists_parse():
    sections = pb.split_sections((FIXTURES / "suspects.txt").read_text(), "@@caelza:")
    info = pb.parse_dumpsys_package(sections["pkg com.example.flashlightpro"])
    assert info["system"] is False and info["version"] == "3.2.1"
    assert info["first_install"] == "2026-10-20 18:02:11"
    assert info["installer"] == "com.google.android.packageinstaller"
    assert "android.permission.SYSTEM_ALERT_WINDOW" in info["permissions"]
    assert pb.parse_dumpsys_package("    pkgFlags=[ SYSTEM HAS_CODE ]")["system"] is True
    ops = pb.parse_appops(sections["ops com.example.flashlightpro"])
    assert ops == {"SYSTEM_ALERT_WINDOW": "allow", "RUN_IN_BACKGROUND": "allow", "REQUEST_INSTALL_PACKAGES": "allow"}
    assert pb.parse_component_list(sections["accessibility"]) == {"com.example.flashlightpro"}
    assert pb.parse_component_list(sections["listeners"]) == set()
    assert pb.parse_device_admins("    admin=com.corp.mdm/.AdminReceiver\n  ComponentInfo{com.other.app/.Admin}") == {"com.corp.mdm", "com.other.app"}
    detail = (FIXTURES / "foreground-detail.txt").read_text()
    assert pb.parse_packages(detail.split("@@caelza:pkg")[0])["com.example.flashlightpro"]["installer"] == "com.google.android.packageinstaller"


def test_risk_scoring_separates_the_sideloaded_overlay_app_from_an_ordinary_one():
    sections = pb.split_sections((FIXTURES / "suspects.txt").read_text(), "@@caelza:")
    bad = pb.risk_flags(
        "com.example.flashlightpro", installer="com.google.android.packageinstaller",
        info=pb.parse_dumpsys_package(sections["pkg com.example.flashlightpro"]),
        appops=pb.parse_appops(sections["ops com.example.flashlightpro"]),
        accessibility={"com.example.flashlightpro"}, now=NOW)
    assert bad["risk"] == "high" and bad["sideloaded"] is True
    assert set(bad["flags"]) == {"sideloaded", "overlay", "accessibility", "install_packages", "sms", "recent"}
    dull = pb.risk_flags(
        "com.cleaner.boost.master", installer=None,
        info=pb.parse_dumpsys_package(sections["pkg com.cleaner.boost.master"]),
        appops=pb.parse_appops(sections["ops com.cleaner.boost.master"]), now=NOW)
    assert dull["risk"] == "low" and dull["flags"] == ["sideloaded"]
    play = pb.risk_flags("com.govee.home", installer="com.android.vending", info={"permissions": ["android.permission.CAMERA"]}, appops={}, now=NOW)
    assert play["risk"] == "low" and play["sideloaded"] is False and play["flags"] == ["camera"]
    trusted = pb.risk_flags("com.termux", installer=None, info={}, appops={}, now=NOW)
    assert trusted["flags"] == [] and trusted["sideloaded"] is False


def test_health_parses_the_whole_recording():
    h = pb.parse_health((FIXTURES / "health.txt").read_text())
    assert h["identity"] == {"manufacturer": "T-Mobile", "model": "TMRV075G", "android": "16", "security_patch": "2026-09-05", "sdk": "36"}
    assert h["battery"] == {"percent": 87, "status": "charging", "health": "good", "temperature_c": 28.5, "plugged": True}
    assert h["storage"] == {"size_gb": 110.0, "used_gb": 77.4, "free_gb": 32.6, "used_percent": 71}
    assert h["memory"] == {"total_mb": 5555, "available_mb": 2941, "used_percent": 47}
    assert h["uptime"] == {"seconds": 193822, "text": "2d 5h 50m"}
    assert h["thermal"] == {"status": 0, "status_text": "none", "hottest_c": 38.0}
    assert h["top"][0] == {"cpu": 10.0, "name": "system_server"} and len(h["top"]) == 4
    assert h["crashes"] == {"fatal_exceptions": 2, "processes": ["com.example.flashlightpro"]}
    assert h["network"] == ["wlan0 192.168.1.23/24", "tun0 100.101.102.103/32"]
    setup = h["setup"]
    assert setup["wireless_debugging"] and setup["developer_options"] and setup["termux_installed"]
    assert setup["termux_api_installed"] and not setup["termux_boot_installed"] and setup["tailscale_installed"]
    assert setup["termux_battery_unrestricted"] and not setup["termux_api_battery_unrestricted"]
    assert setup["stay_awake_plugged_in"] is False and setup["animations_off"] is False
    assert setup["verified_boot"] == "green" and setup["bootloader_locked"] is True
    assert h["attention"] == ["2 crash(es) in the crash log: com.example.flashlightpro"]


def test_health_attention_speaks_up_when_something_is_wrong():
    h = {
        "battery": {"percent": 9, "status": "discharging", "temperature_c": 44.0, "health": "overheat"},
        "storage": {"free_gb": 1.2}, "memory": {"available_mb": 310}, "thermal": {"status": 3, "status_text": "severe"},
        "crashes": {"fatal_exceptions": 0, "processes": []},
        "setup": {"termux_installed": True, "termux_battery_unrestricted": False, "verified_boot": "orange"},
    }
    notes = pb.health_attention(h)
    assert notes == [
        "battery at 9% and discharging", "battery hot: 44.0 °C", "battery health: overheat",
        "only 1.2 GB free", "memory tight: 310 MB available", "thermal status severe",
        "Termux is not exempt from battery optimisation", "verified boot state: orange",
    ]
    assert pb.parse_health("garbage")["error"] == "health script did not finish"


# --- the four tools end to end over a recorded adb ---------------------------

@pytest.fixture
def recorded_phone(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "adb"
    shutil.copy(FIXTURES / "adb.py", fake)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CAELZA_FIXTURES", str(FIXTURES))
    monkeypatch.setenv("CAELZA_SNAPSHOT", str(SNAPSHOT))

    class Clock(datetime):  # the recording was made on NOW's day
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(playbook, "datetime", Clock)
    tools.reset()
    device.configure(tmp_path / "home")
    device.register()
    playbook.register()
    yield tmp_path
    tools.reset()


def call(name, **args):
    out = tools.dispatch(name, args)
    return json.loads(out) if out.startswith("{") else out


def test_debloat_plan_tool_runs_the_classifier_over_the_phone(recorded_phone):
    plan = call("device_debloat_plan", device="self")
    assert plan["device"] == "self" and plan["total"] == 301
    assert plan["third_party"] == 6
    assert "com.metro.minus1" in {i["pkg"] for i in plan["remove"]}
    assert plan["already_disabled"] == ["com.tmobile.echolocate"]
    assert [i["pkg"] for i in plan["review"]] == ["com.cleaner.boost.master", "com.example.flashlightpro", "com.govee.home"]
    assert "device_uninstall" in plan["how"]
    pinned = call("device_debloat_plan", device="self", keep="com.metro.minus1, com.metropcs.metrozone")
    assert pinned["pinned"] == ["com.metro.minus1", "com.metropcs.metrozone"]
    assert not {"com.metro.minus1", "com.metropcs.metrozone"} & {i["pkg"] for i in pinned["remove"]}


def test_suspects_tool_names_the_sideloaded_apps_highest_risk_first(recorded_phone):
    s = call("device_suspects", device="self")
    assert s["third_party"] == 6 and s["sideloaded"] == 2 and s["inspected"] == 2 and s["truncated"] is False
    assert [r["pkg"] for r in s["suspects"]] == ["com.example.flashlightpro", "com.cleaner.boost.master"]
    assert s["suspects"][0]["risk"] == "high" and s["suspects"][1]["risk"] == "low"
    assert set(s["suspects"][0]["flags"]) == {"sideloaded", "overlay", "accessibility", "install_packages", "sms", "recent"}
    assert s["suspects"][1]["flags"] == ["sideloaded"]
    assert s["accessibility_services"] == ["com.example.flashlightpro"]
    assert s["device_admins"] == [] and s["notification_listeners"] == []
    assert "SYSTEM_ALERT_WINDOW" in s["how"]


def test_foreground_tool_identifies_the_popup_and_who_installed_it(recorded_phone):
    fg = call("device_foreground", device="self")
    assert fg["package"] == "com.example.flashlightpro"
    assert fg["activity"] == "com.example.flashlightpro.ui.OfferActivity"
    assert fg["installer"] == "com.google.android.packageinstaller" and fg["sideloaded"] is True
    assert fg["system"] is False and fg["note"] == "sideloaded: not from an app store"
    assert {"sideloaded", "overlay", "accessibility", "sms"} <= set(fg["flags"])


def test_health_tool_returns_the_checklist_and_attention(recorded_phone):
    h = call("device_health", device="self")
    assert h["device"] == "self" and h["identity"]["model"] == "TMRV075G"
    assert h["setup"]["termux_boot_installed"] is False
    assert h["attention"] == ["2 crash(es) in the crash log: com.example.flashlightpro"]


def test_tools_refuse_an_unknown_device_and_report_a_missing_adb(recorded_phone, monkeypatch):
    assert call("device_health", device="nope") == "error: unknown device 'nope'"
    monkeypatch.setenv("PATH", str(recorded_phone / "empty"))
    out = call("device_debloat_plan", device="self")
    assert out.startswith("error:") and "adb" in out


def test_the_playbook_tools_are_read_only_in_every_table(recorded_phone):
    from caelza_body import mcp_server as srv
    new = {"device_debloat_plan", "device_suspects", "device_foreground", "device_health"}
    assert new <= srv.READ_ONLY and new <= set(tools.REGISTRY)
    for name in new:
        schema = tools._SCHEMAS[name]["function"]["parameters"]
        assert "reason" not in schema.get("required", []), "a read never needs a reason"
        assert schema["properties"]["device"]["default"] == "self"


# --- live, against an emulator or a phone ------------------------------------

SERIAL = os.environ.get("CAELZA_EVAL_SERIAL")


@pytest.mark.skipif(not SERIAL, reason="set CAELZA_EVAL_SERIAL=<adb serial> (e.g. emulator-5554) to run the live evals")
def test_live_playbook_tools_against_the_device(tmp_path, monkeypatch):
    tools.reset()
    device.configure(tmp_path / "home")
    monkeypatch.setattr(device, "adb", Adb(DeviceRegistry(tmp_path / "d.json"), self_serial=SERIAL))
    monkeypatch.setattr(adb_mod, "_BODY_HOME", tmp_path / "home")
    device.register()
    playbook.register()
    try:
        health = call("device_health")
        assert isinstance(health, dict) and health["identity"]["model"], health
        assert health["battery"]["percent"] is not None and "setup" in health
        plan = call("device_debloat_plan")
        assert plan["total"] > 50 and plan["keep"] > 0, plan
        offered = {i["pkg"] for c in ("remove", "disable", "optional") for i in plan[c]}
        assert not offered & {"android", "com.android.systemui", "com.google.android.gms"}
        suspects = call("device_suspects")
        assert isinstance(suspects["suspects"], list) and suspects["third_party"] >= suspects["sideloaded"]
        fg = call("device_foreground")
        assert "package" in fg
    finally:
        tools.reset()
