import json
import os
import stat

import pytest

from caelza_body.agent import tools
from caelza_body.agent.tools import device, media


@pytest.fixture
def fake_adb(tmp_path, monkeypatch):
    """A `#!/bin/sh` fake `adb` on PATH. Branch order matters — first `case`
    match wins, so the binary `exec-out screencap` branch precedes the
    catch-all that echoes its args."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    p = bindir / "adb"
    p.write_text(
        '#!/bin/sh\n'
        'case "$*" in\n'
        "  *\"exec-out\"*\"screencap\"*) printf '\\211PNG\\r\\n\\032\\nPNGBODY';;\n"
        '  *"pair"*) echo "Successfully paired";;\n'
        '  *"connect"*) echo "connected to $2";;\n'
        '  *"devices"*) echo "List of devices attached";;\n'
        '  *"pm list packages"*)\n'
        '    echo "args: $*"\n'
        '    i=0; while [ $i -lt 160 ]; do\n'
        '      echo "package:/data/app/~~aaaaaaaaaaaaaaaaaaaaaa==/com.fake$i-bbbbbbbbbbbb==/base.apk=com.fake$i"\n'
        '      i=$((i+1))\n'
        '    done;;\n'
        '  *) echo "args: $*";;\n'
        'esac\n')
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return tmp_path


@pytest.fixture(autouse=True)
def _cfg(fake_adb, tmp_path):
    tools.reset()
    media.PENDING_MEDIA.clear()
    device.configure(tmp_path)
    device.register()


def test_configure_connects_self_on_start(tmp_path, monkeypatch):
    """I1: device.configure() must best-effort `adb connect` this phone —
    off the calling thread (Imp-2: it must not block the supervisor probe)."""
    import time as _t
    from caelza_body.agent.adb import Adb
    calls = []
    monkeypatch.setattr(Adb, "connect_self", lambda self: calls.append(1) or True)
    device.configure(tmp_path)
    for _ in range(200):  # the connect runs on a daemon thread
        if calls:
            break
        _t.sleep(0.01)
    assert calls, "configure() did not call adb.connect_self()"


def test_configure_survives_connect_self_failure(tmp_path, monkeypatch):
    from caelza_body.agent.adb import Adb
    def boom(self):
        raise RuntimeError("no wireless debugging")
    monkeypatch.setattr(Adb, "connect_self", boom)
    device.configure(tmp_path)  # must not raise


def test_device_shell_self():
    assert "echo hi" in tools.dispatch("device_shell", {"cmd": "echo hi"})


def test_device_screencap_emits_image():
    out = tools.dispatch("device_screencap", {})
    assert "captured" in out and len(media.PENDING_MEDIA) == 1
    assert media.PENDING_MEDIA[0][0].endswith(".png")
    assert media.PENDING_MEDIA[0][1] == "image/png"


def test_screencap_rejects_non_png_output(tmp_path, monkeypatch):
    bindir = tmp_path / "bin_nopng"
    bindir.mkdir()
    p = bindir / "adb"
    p.write_text('#!/bin/sh\ncase "$*" in\n'
                 '  *"screencap"*) echo "WARNING: adb build noise";;\n'
                 '  *"connect"*) echo "connected to $2";;\n'
                 '  *) echo "args: $*";;\n'
                 'esac\n')
    p.chmod(p.stat().st_mode | 0o111)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    tools.reset(); media.PENDING_MEDIA.clear()
    device.configure(tmp_path); device.register()
    out = tools.dispatch("device_screencap", {})
    assert out.startswith("error:") and "did not return a PNG" in out
    assert not media.PENDING_MEDIA


def test_device_list_reachable_requires_whole_token_device_state(tmp_path, monkeypatch):
    bindir = tmp_path / "bin_list"
    bindir.mkdir()
    p = bindir / "adb"
    p.write_text('#!/bin/sh\ncase "$*" in\n'
                 '  *"devices"*) printf "List of devices attached\\n10.0.0.5:5555\\tdevice\\n";;\n'
                 '  *"connect"*) echo "connected to $2";;\n'
                 '  *) echo "args: $*";;\n'
                 'esac\n')
    p.chmod(p.stat().st_mode | 0o111)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    tools.reset()
    device.configure(tmp_path); device.register()
    device.registry.add("near", "10.0.0.5:5555")
    device.registry.add("other", "10.0.0.5:555")  # substring of the real one
    parsed = json.loads(tools.dispatch("device_list", {}))
    assert parsed["near"]["reachable"] is True
    assert parsed["other"]["reachable"] is False


def test_device_shell_unknown_device_is_error():
    out = tools.dispatch("device_shell", {"cmd": "x", "device": "nope"})
    assert out.startswith("error:")


def test_device_packages_returns_pm_output():
    out = tools.dispatch("device_packages", {})
    assert "pm list packages -3" in out


def test_device_settings_get():
    out = tools.dispatch("device_settings", {"ns": "system", "key": "screen_brightness"})
    assert "settings get system screen_brightness" in out


def test_device_list_includes_self():
    parsed = json.loads(tools.dispatch("device_list", {}))
    assert "self" in parsed and "reachable" in parsed["self"]


def test_uninstall_snapshots_and_logs(tmp_path):
    tools.dispatch("device_uninstall", {"pkg": "com.junk", "reason": "adware"})
    snaps = list((tmp_path / "snapshots").glob("self-*.txt"))
    assert snaps
    log = (tmp_path / "logs" / "device-actions.log").read_text()
    assert "com.junk" in log and "adware" in log


def test_snapshot_is_uncapped(tmp_path):
    """A >8 KB package list must survive the pre-removal snapshot intact."""
    tools.dispatch("device_uninstall", {"pkg": "com.fake5", "reason": "test"})
    snap = next((tmp_path / "snapshots").glob("self-*.txt"))
    text = snap.read_text()
    assert text.count("package:") > 100
    assert len(text) > 8000  # would have been capped at 8000 via adb.run


def test_uninstall_aborts_when_snapshot_has_no_packages(tmp_path, monkeypatch):
    """Device offline: `_snapshot` returns an error, so the removal must not run."""
    bindir = tmp_path / "bin_offline"
    bindir.mkdir()
    p = bindir / "adb"
    p.write_text(
        '#!/bin/sh\n'
        'case "$*" in\n'
        '  *"pm list packages"*) echo "error: no devices/emulators found"; exit 1;;\n'
        '  *"uninstall"*) echo "PM-UNINSTALL-RAN";;\n'
        '  *) echo "args: $*";;\n'
        'esac\n')
    p.chmod(p.stat().st_mode | 0o111)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    tools.reset()
    device.configure(tmp_path)
    device.register()

    out = tools.dispatch("device_uninstall", {"pkg": "com.junk", "reason": "adware"})
    assert out.startswith("error:")
    assert "PM-UNINSTALL-RAN" not in out
    # the aborted attempt is still audit-logged
    log = (tmp_path / "logs" / "device-actions.log").read_text()
    assert "ABORTED" in log and "com.junk" in log


def test_configure_prunes_old_tmp_and_extra_snapshots(tmp_path):
    tmpd = tmp_path / "tmp"
    old = tmpd / "old.png"; old.write_bytes(b"x")
    recent = tmpd / "recent.png"; recent.write_bytes(b"x")
    os.utime(old, (0, 0))  # epoch: far older than 24h
    snapd = tmp_path / "snapshots"; snapd.mkdir(exist_ok=True)
    for i in range(25):
        s = snapd / f"self-{i:03d}.txt"; s.write_text("package:x")
        os.utime(s, (1_000_000 + i, 1_000_000 + i))

    device.configure(tmp_path)

    assert not old.exists() and recent.exists()
    remaining = sorted(p.name for p in snapd.glob("*"))
    assert len(remaining) == 20
    assert "self-024.txt" in remaining and "self-000.txt" not in remaining


def test_dangerous_tool_requires_reason():
    out = tools.dispatch("device_disable", {"pkg": "com.x"})  # no reason
    assert out.startswith("error:")  # dispatch surfaces the TypeError


def test_input_tap():
    out = tools.dispatch("device_input", {"action": "tap", "x": 100, "y": 200})
    assert "input tap 100 200" in out


def test_device_pair_registers():
    out = tools.dispatch(
        "device_pair",
        {"name": "gma", "host": "10.0.0.5:5555", "code": "123456"},
    )
    assert "gma" in out
    parsed = json.loads(tools.dispatch("device_list", {}))
    assert "gma" in parsed


def test_device_unpair_removes():
    tools.dispatch(
        "device_pair",
        {"name": "gma", "host": "10.0.0.5:5555", "code": "123456"},
    )
    tools.dispatch("device_unpair", {"name": "gma"})
    parsed = json.loads(tools.dispatch("device_list", {}))
    assert "gma" not in parsed


def test_settings_put_writes_action_log(tmp_path):
    tools.dispatch("device_settings_put", {
        "ns": "system", "key": "screen_brightness", "value": "50",
        "reason": "dim for night",
    })
    log = (tmp_path / "logs" / "device-actions.log").read_text()
    assert "screen_brightness=50" in log and "dim for night" in log


def test_settings_put_value_is_one_argv_piece_not_a_shell_string(tmp_path):
    """I5: a value with shell metacharacters must not become a second command,
    and the audit log must match what ran."""
    out = tools.dispatch("device_settings_put", {
        "ns": "system", "key": "k", "value": "1 ; pm uninstall com.foo",
        "reason": "audit-integrity",
    })
    assert "settings put system k 1 ; pm uninstall com.foo" in out
    log = (tmp_path / "logs" / "device-actions.log").read_text()
    assert "k=1 ; pm uninstall com.foo" in log


def test_device_input_swipe():
    out = tools.dispatch("device_input", {
        "action": "swipe", "x": 0, "y": 0, "x2": 100, "y2": 200,
    })
    assert "input swipe 0 0 100 200" in out
