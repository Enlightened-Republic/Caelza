import os, stat, json
import pytest
from niba.agent import tools
from niba.agent.tools import sensors, media


@pytest.fixture
def fake_termux(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"; bindir.mkdir()
    def make(name, body):
        p = bindir / name; p.write_text("#!/bin/sh\n" + body)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    make("termux-camera-photo", 'printf "" > "$3"; echo ok')          # $3 = outfile
    make("termux-battery-status", 'echo \'{"percentage": 88}\'')
    make("termux-tts-speak", 'exit 0')
    make("termux-clipboard-get", 'echo cliptext')
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    tools.reset(); media.PENDING_MEDIA.clear()
    sensors.configure(tmp_path); sensors.register()
    return tmp_path


def test_camera_emits_image(fake_termux):
    out = tools.dispatch("sensors_camera_photo", {"facing": "front"})
    assert "captured" in out
    assert len(media.PENDING_MEDIA) == 1 and media.PENDING_MEDIA[0][0].endswith(".jpg")


def test_battery_returns_json(fake_termux):
    assert json.loads(tools.dispatch("sensors_battery", {}))["percentage"] == 88


def test_clipboard_get(fake_termux):
    assert tools.dispatch("sensors_clipboard_get", {}).strip() == "cliptext"


def test_missing_binary_is_a_clean_error(tmp_path, monkeypatch):
    """A truly-absent termux-* binary is a clean `error:` string, not a crash.
    PATH is a single empty dir, so neither termux-location nor even `sh` is
    findable — proc.run must still hand back a 127 the tool reports cleanly.
    Holds on a real Termux box too (where the binaries otherwise exist)."""
    bindir = tmp_path / "bin"; bindir.mkdir()
    monkeypatch.setenv("PATH", str(bindir))
    tools.reset(); media.PENDING_MEDIA.clear()
    sensors.configure(tmp_path); sensors.register()
    assert tools.dispatch("sensors_location", {}).startswith("error:")


def test_configure_prunes_old_captures(tmp_path):
    tmpd = tmp_path / "tmp"; tmpd.mkdir()
    old = tmpd / "mic-old.m4a"; old.write_bytes(b"x")
    new = tmpd / "mic-new.m4a"; new.write_bytes(b"x")
    os.utime(old, (0, 0))
    sensors.configure(tmp_path)
    assert not old.exists() and new.exists()


def test_mic_record_clamps_to_60s(fake_termux, monkeypatch):
    seen = {}
    monkeypatch.setattr(sensors, "_run",
                        lambda argv, timeout=30: seen.setdefault("argv", list(argv)) and "" or "")
    monkeypatch.setattr(sensors.time, "sleep", lambda s: seen.__setitem__("slept", s))
    tools.dispatch("sensors_mic_record", {"seconds": 9999})
    argv = seen["argv"]
    assert argv[argv.index("-l") + 1] == "60"
    assert seen["slept"] <= 60
