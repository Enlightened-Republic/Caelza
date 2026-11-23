import os, stat, json
import pytest
from caelza_body.agent import tools
from caelza_body.agent.tools import sensors, media


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
    # No Runtime beside the Body unless a test writes one (the agent's chosen voice).
    monkeypatch.setenv(sensors.RUNTIME_DIR_ENV, str(tmp_path / ".caelza"))
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
    import caelza_body.agent.tools.sensors as s
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
    import caelza_body.agent.tools.sensors as s
    tools.reset(); s.configure(tmp_path); s.register()
    seen = {}
    monkeypatch.setattr(s, "_run", lambda argv, timeout=30: (seen.setdefault("argv", argv), '{"latitude":1.0}')[1])
    out = tools.dispatch("sensors_location", {"mode": "gps"})
    assert seen["argv"] == ["termux-location", "-p", "gps"]
    assert "latitude" in out


def test_location_accuracy_backcompat(tmp_path, monkeypatch):
    import caelza_body.agent.tools.sensors as s
    tools.reset(); s.configure(tmp_path); s.register()
    seen = {}
    monkeypatch.setattr(s, "_run", lambda argv, timeout=30: (seen.setdefault("argv", argv), "{}")[1])
    tools.dispatch("sensors_location", {"accuracy": "fine"})
    assert seen["argv"] == ["termux-location", "-p", "gps"]


# --- the agent's own voice (P2c) -------------------------------------------------

def _runtime(tmp_path, voice=None, config='[agents.main]\nmcp_bundles = ["body"]\nrisk_profile = "phone"\n', offered=None, alias="main"):
    """A Runtime config dir beside the Body: the agent carrying it, its voice.json, the phone's offer."""
    cfg = tmp_path / ".caelza"
    (cfg / "agents" / alias).mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(config)
    if voice is not None:
        (cfg / "agents" / alias / sensors.VOICE_FILE).write_text(json.dumps(voice))
    if offered is not None:
        (cfg / sensors.OFFERED_FILE).write_text(json.dumps(offered))
    return cfg


def _capture(monkeypatch):
    seen = {}
    monkeypatch.setattr(sensors, "_run", lambda argv, timeout=30: (seen.setdefault("argv", list(argv)), "")[1])
    return seen


PHONE_OFFER = {"version": 1, "engines": {"phone": {"voices": [
    {"id": "en-gb-x-gba-local", "name": "en-GB · en-gb-x-gba-local", "lang": "en-GB"},
    {"id": "en-us-x-iom-local", "name": "en-US · en-us-x-iom-local", "lang": "en-US"}]}}}


def test_tts_speaks_in_the_chosen_phone_voice(fake_termux, monkeypatch):
    _runtime(fake_termux, voice={"engine": "phone", "voice": "en-gb-x-gba-local", "rate": 1.2, "pitch": 0.9}, offered=PHONE_OFFER)
    seen = _capture(monkeypatch)
    assert tools.dispatch("sensors_tts_speak", {"text": "hello"}) == "spoken"
    assert seen["argv"] == ["termux-tts-speak", "-l", "en", "-n", "GB", "-r", "1.2", "-p", "0.9", "hello"]


def test_tts_without_a_choice_is_the_plain_command(fake_termux, monkeypatch):
    seen = _capture(monkeypatch)
    assert tools.dispatch("sensors_tts_speak", {"text": "hello"}) == "spoken"
    assert seen["argv"] == ["termux-tts-speak", "hello"]
    # A Runtime with no voice.json is the same.
    _runtime(fake_termux)
    seen.clear()
    tools.dispatch("sensors_tts_speak", {"text": "hello"})
    assert seen["argv"] == ["termux-tts-speak", "hello"]


def test_tts_elevenlabs_voice_is_spoken_by_the_phone_and_the_answer_says_so(fake_termux, monkeypatch):
    _runtime(fake_termux, voice={"engine": "elevenlabs", "voice": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel"})
    seen = _capture(monkeypatch)
    assert tools.dispatch("sensors_tts_speak", {"text": "hello"}) == sensors.ELEVENLABS_ELSEWHERE
    assert seen["argv"] == ["termux-tts-speak", "hello"]


def test_tts_argv_takes_the_locale_apart_bounds_the_numbers_and_leaves_other_engines_alone():
    assert sensors.tts_argv("x", {"engine": "phone", "voice": "v", "lang": "zh-Hant-TW", "rate": 9, "pitch": 0.1}) == \
        ["termux-tts-speak", "-l", "zh", "-n", "TW", "-r", "2", "-p", "0.5", "x"]
    assert sensors.tts_argv("x", {"engine": "phone", "voice": "v", "lang": "es-419", "rate": "fast"}) == ["termux-tts-speak", "-l", "es", "-n", "419", "x"]
    assert sensors.tts_argv("x", {"engine": "phone", "voice": "v"}) == ["termux-tts-speak", "x"]
    assert sensors.tts_argv("x", {"engine": "browser", "voice": "Samantha", "rate": 1.5}) == ["termux-tts-speak", "x"]
    assert sensors.tts_argv("x", None) == ["termux-tts-speak", "x"]


def test_body_agent_is_the_one_carrying_the_body_and_main_wins():
    assert sensors.body_agent("") == "main"
    assert sensors.body_agent('[agents.main]\nmodel_provider = "x"\n') == "main"
    assert sensors.body_agent('[agents.cael]\nrisk_profile = "guide"\n\n[agents.moss]\nmcp_bundles = ["body"]\n') == "moss"
    assert sensors.body_agent('[agents.moss]\nmcp_bundles = ["body"]\n\n[agents.main]\nmcp_bundles = ["body", "other"]\n') == "main"
    assert sensors.body_agent('[mcp_bundles.body]\nservers = ["body"]\n\n[agents.cael]\nmcp_bundles = ["notes"]\n') == "main"
    assert sensors.body_agent("not = toml = [") == "main"


def test_chosen_voice_reads_the_body_agents_file_and_fills_the_language(tmp_path):
    cfg = _runtime(tmp_path, voice={"engine": "phone", "voice": "en-us-x-iom-local"}, offered=PHONE_OFFER,
                   config='[agents.cael]\nrisk_profile = "guide"\n\n[agents.moss]\nmcp_bundles = ["body"]\n', alias="moss")
    (cfg / "agents" / "main").mkdir()
    (cfg / "agents" / "main" / sensors.VOICE_FILE).write_text(json.dumps({"engine": "phone", "voice": "en-gb-x-gba-local"}))
    choice = sensors.chosen_voice(cfg)
    assert choice["voice"] == "en-us-x-iom-local" and choice["lang"] == "en-US", "moss carries the Body, not main"
    assert sensors.chosen_voice(tmp_path / "nowhere") is None
    (cfg / "agents" / "moss" / sensors.VOICE_FILE).write_text('{"engine": "radio", "voice": "x"}')
    assert sensors.chosen_voice(cfg) is None
    (cfg / "agents" / "moss" / sensors.VOICE_FILE).write_text("not json")
    assert sensors.chosen_voice(cfg) is None


def test_ipgeo_falls_back_to_second_service(monkeypatch):
    import caelza_body.agent.tools.sensors as s
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
