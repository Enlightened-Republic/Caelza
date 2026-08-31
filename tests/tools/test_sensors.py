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
    """When GPS mode is used with missing binary, return clean error.
    In quick mode (default), we fall back to IP geolocation, so it won't error."""
    bindir = tmp_path / "bin"; bindir.mkdir()
    monkeypatch.setenv("PATH", str(bindir))
    tools.reset(); media.PENDING_MEDIA.clear()
    sensors.configure(tmp_path); sensors.register()
    # don't let quick mode make a real IP-geo call (leaks the owner's city/ISP)
    monkeypatch.setattr(sensors, "_ipgeo", lambda: {})
    # GPS mode should error when termux-location is missing
    assert tools.dispatch("sensors_location", {"mode": "gps"}).startswith("error:")
    # Quick mode should return JSON even without termux binaries (uses IP geolocation fallback)
    out = json.loads(tools.dispatch("sensors_location", {}))
    assert "wifi" in out and "approx" in out


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


def test_location_quick_combines_wifi_and_ipgeo(tmp_path, monkeypatch):
    import niba.agent.tools.sensors as s
    tools.reset(); s.configure(tmp_path); s.register()
    monkeypatch.setattr(s, "_run", lambda argv, timeout=30:
                        '{"ssid":"HomeNet","ip":"192.168.1.5","rssi":-46}'
                        if "wifi" in argv[0] else "SHOULD-NOT-CALL")
    monkeypatch.setattr(s, "_ipgeo", lambda: {"city": "Rivertown", "region": "Montana",
                                              "country": "United States",
                                              "latitude": 44.0, "longitude": -121.0,
                                              "isp": "Northwind Cable"})
    out = json.loads(tools.dispatch("sensors_location", {}))  # mode defaults to quick
    assert out["wifi"]["ssid"] == "HomeNet"
    assert out["approx"]["city"] == "Rivertown" and out["approx"]["country"] == "United States"


def test_location_gps_mode_uses_termux_location(tmp_path, monkeypatch):
    import niba.agent.tools.sensors as s
    tools.reset(); s.configure(tmp_path); s.register()
    seen = {}
    monkeypatch.setattr(s, "_run", lambda argv, timeout=30: (seen.setdefault("argv", argv), '{"latitude":1.0}')[1])
    out = tools.dispatch("sensors_location", {"mode": "gps"})
    assert seen["argv"] == ["termux-location", "-p", "gps"]
    assert "latitude" in out


def test_location_accuracy_backcompat(tmp_path, monkeypatch):
    import niba.agent.tools.sensors as s
    tools.reset(); s.configure(tmp_path); s.register()
    seen = {}
    monkeypatch.setattr(s, "_run", lambda argv, timeout=30: (seen.setdefault("argv", argv), "{}")[1])
    tools.dispatch("sensors_location", {"accuracy": "fine"})
    assert seen["argv"] == ["termux-location", "-p", "gps"]


def test_ipgeo_falls_back_to_second_service(monkeypatch):
    import niba.agent.tools.sensors as s
    import httpx
    def fake(method, url, **kw):
        req = httpx.Request(method, url)
        if "ipwho.is" in url:
            return httpx.Response(500, text="down", request=req)
        return httpx.Response(200, request=req, json={
            "city": "Centerport", "region": "Oregon", "country_name": "United States",
            "latitude": 45.5, "longitude": -122.6})
    monkeypatch.setattr(s.httpx, "request", fake)
    g = s._ipgeo()
    assert g["city"] == "Centerport" and g["country"] == "United States"
