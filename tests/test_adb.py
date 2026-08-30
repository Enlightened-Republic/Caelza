import os
import stat

import pytest

from niba.agent import adb as adb_mod
from niba.agent.adb import Adb
from niba.agent.devices import DeviceRegistry


@pytest.fixture
def fake_adb(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    p = bindir / "adb"
    p.write_text(
        '#!/bin/sh\n'
        'case "$*" in\n'
        '  *"connect"*) echo "connected to $2";;\n'
        '  *"pair"*) echo "Successfully paired";;\n'
        '  *"-s "*" shell getprop"*) echo "REFERENCE-DEVICE";;\n'
        '  *) echo "args: $*";;\n'
        'esac\n')
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return tmp_path


def test_serial_resolution(fake_adb, tmp_path):
    r = DeviceRegistry(tmp_path / "d.json")
    r.add("gma", "10.0.0.5:5555")
    a = Adb(r, self_serial="127.0.0.1:5555")
    assert a.serial("self") == "127.0.0.1:5555"
    assert a.serial("gma") == "10.0.0.5:5555"


def test_serial_unknown_device_raises(fake_adb, tmp_path):
    a = Adb(DeviceRegistry(tmp_path / "d.json"), self_serial="127.0.0.1:5555")
    with pytest.raises(KeyError):
        a.serial("nope")


def test_run_targets_the_right_serial(fake_adb, tmp_path):
    a = Adb(DeviceRegistry(tmp_path / "d.json"), self_serial="127.0.0.1:5555")
    out = a.run("self", "shell", "echo", "hi")
    assert "-s 127.0.0.1:5555 shell echo hi" in out
    assert out.startswith("exit 0\n")


def test_connect_self(fake_adb, tmp_path):
    assert Adb(DeviceRegistry(tmp_path / "d.json")).connect_self() is True


def test_pair_registers(fake_adb, tmp_path):
    r = DeviceRegistry(tmp_path / "d.json")
    status = Adb(r).pair("gma", "10.0.0.5:5555", "123456")
    assert r.get("gma")["host"] == "10.0.0.5:5555"
    assert isinstance(status, str) and status


def test_default_self_serial_is_5555(fake_adb, tmp_path):
    a = Adb(DeviceRegistry(tmp_path / "d.json"))
    assert a.serial("self") == "127.0.0.1:5555"


def test_self_port_file_overrides_default(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "run").mkdir(parents=True)
    (home / "run" / "adb-self-port").write_text("41337\n")
    monkeypatch.setattr(adb_mod, "_NIBA_HOME", home)
    a = Adb(DeviceRegistry(tmp_path / "d.json"))
    assert a.serial("self") == "127.0.0.1:41337"


def test_self_serial_is_reread_after_construction(tmp_path, monkeypatch):
    """I2: Android reassigns the wireless-debugging port on every reboot; a
    port-file written after the Adb is built must take effect with no restart."""
    home = tmp_path / "home"
    (home / "run").mkdir(parents=True)
    monkeypatch.setattr(adb_mod, "_NIBA_HOME", home)
    a = Adb(DeviceRegistry(tmp_path / "d.json"))
    assert a.serial("self") == "127.0.0.1:5555"  # no file yet -> default
    (home / "run" / "adb-self-port").write_text("52000\n")
    assert a.serial("self") == "127.0.0.1:52000"  # picked up, no reconstruct
    # an explicit constructor override still wins
    b = Adb(DeviceRegistry(tmp_path / "d.json"), self_serial="127.0.0.1:5555")
    assert b.serial("self") == "127.0.0.1:5555"


def test_connect_self_falls_back_to_a_scanned_loopback_port(tmp_path, monkeypatch):
    """I1/I2: recorded port dead -> adopt a live 127.0.0.1:<port> from `adb devices`."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    p = bindir / "adb"
    p.write_text(
        '#!/bin/sh\n'
        'case "$*" in\n'
        '  "connect 127.0.0.1:5555") echo "cannot connect to 127.0.0.1:5555: ...";;\n'
        '  "connect 127.0.0.1:41000") echo "connected to 127.0.0.1:41000";;\n'
        '  *"devices"*) printf "List of devices attached\\n'
        '127.0.0.1:39000\\toffline\\n127.0.0.1:41000\\tdevice\\n";;\n'
        '  *) echo "args: $*";;\n'
        'esac\n')
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    # no explicit override -> default 127.0.0.1:5555, which the fake rejects, so
    # connect_self must scan `adb devices`, skip the offline entry, adopt :41000
    a = Adb(DeviceRegistry(tmp_path / "d.json"))
    assert a.connect_self() is True
    assert a.serial("self") == "127.0.0.1:41000"


def test_adb_missing_is_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    a = Adb(DeviceRegistry(tmp_path / "d.json"), self_serial="127.0.0.1:5555")
    out = a.run("self", "shell", "true")
    assert "exit 127" in out
    assert "adb not found" in out


def test_remote_exit_127_is_passed_through_not_masked(tmp_path, monkeypatch):
    """`adb shell <missing-cmd>` legitimately exits 127; it must not be reported
    as 'adb not found'."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    p = bindir / "adb"
    p.write_text('#!/bin/sh\necho "/system/bin/sh: nosuchcmd: inaccessible or not found"\nexit 127\n')
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    a = Adb(DeviceRegistry(tmp_path / "d.json"), self_serial="127.0.0.1:5555")
    out = a.run("self", "shell", "nosuchcmd")
    assert out.startswith("exit 127\n")
    assert "adb not found" not in out
    assert "nosuchcmd" in out


def test_remote_output_containing_adb_not_found_is_not_masked(tmp_path, monkeypatch):
    """A real device line that literally says `adb: not found` (rc 0) must be
    returned intact, not swallowed by the missing-binary sniff."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    p = bindir / "adb"
    p.write_text('#!/bin/sh\necho "127|/system/bin/sh: adb: not found"\nexit 0\n')
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    a = Adb(DeviceRegistry(tmp_path / "d.json"), self_serial="127.0.0.1:5555")
    out = a.run("self", "shell", "which adb")
    assert out.startswith("exit 0\n")
    assert "adb: not found" in out
    assert "pkg install android-tools" not in out


def test_configure_defaults_tmpdir_for_a_boot_launched_agent(tmp_path, monkeypatch):
    """Termux:Boot gives the supervisor no TMPDIR; adb.configure must default it
    so the first `adb` call doesn't die on its server socket/log."""
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.setenv("PREFIX", str(tmp_path / "usr"))
    adb_mod.configure(tmp_path / "home")
    assert os.environ["TMPDIR"] == str(tmp_path / "usr" / "tmp")
    assert (tmp_path / "usr" / "tmp").is_dir()


def test_configure_keeps_an_existing_tmpdir(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", "/already/set")
    monkeypatch.setenv("PREFIX", str(tmp_path))
    adb_mod.configure(tmp_path / "home")
    assert os.environ["TMPDIR"] == "/already/set"


def test_run_reconnects_once_when_the_server_forgot_the_device(tmp_path, monkeypatch):
    """adb server restarts lose `connect` state; a 'device not found' must
    trigger one reconnect + retry, not just surface the error."""
    bindir = tmp_path / "bin"; bindir.mkdir()
    state = bindir / "connected"
    p = bindir / "adb"
    p.write_text(
        '#!/bin/sh\n'
        f'S="{state}"\n'
        'case "$*" in\n'
        '  *"connect"*) : > "$S"; echo "connected to $2";;\n'
        '  *"shell"*) if [ -f "$S" ]; then echo "hello from device"; '
        'else echo "error: device \'\'\'127.0.0.1:5555\'\'\' not found"; exit 1; fi;;\n'
        '  *) echo "args: $*";;\n'
        'esac\n')
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    a = Adb(DeviceRegistry(tmp_path / "d.json"), self_serial="127.0.0.1:5555")
    out = a.run("self", "shell", "echo", "hi")   # first call: not connected -> retry
    assert "hello from device" in out
    assert state.exists()
