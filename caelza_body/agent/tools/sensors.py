from __future__ import annotations

import time
from pathlib import Path

import httpx

from caelza_body.agent import proc
from caelza_body.agent import tools
from caelza_body.agent.tools.media import emit_image

#: Where camera / mic captures are written. Set by configure().
_TMP: Path = Path(".")

CAP = 6000


#: I10: prune tmp captures older than this on configure().
TMP_MAX_AGE_S = 24 * 3600


def configure(body_home) -> None:
    """Point captures at <body_home>/tmp (the test passes a tmp dir directly)."""
    global _TMP
    p = Path(body_home)
    # Accept either a home dir or an explicit tmp dir; keep captures out of the root.
    _TMP = p if p.name == "tmp" else p / "tmp"
    _TMP.mkdir(parents=True, exist_ok=True)
    _prune_tmp()


def _prune_tmp() -> None:
    """Best-effort: drop mic/camera captures older than 24h. Never raises."""
    try:
        cutoff = time.time() - TMP_MAX_AGE_S
        for f in _TMP.glob("*"):
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
    except Exception:  # noqa: BLE001
        pass


def _run(argv, timeout: int = 30) -> str:
    """Run a termux-* command via `proc.run` (own process group, group-killed on
    timeout, stdin closed), merge stdout+stderr, cap ~6 KB."""
    _not_found = (f"error: {argv[0]} not found — is Termux:API installed? "
                  f"grant its permissions in Android settings")
    rc, out, via_shell = proc.run(argv, timeout=timeout, cap=CAP)
    if rc == -1 and out.startswith("error: timed out"):
        return f"error: {argv[0]} timed out after {timeout}s"
    if rc != 0:
        low = out.lower()
        if (proc.missing_executable(rc, out, argv[0], via_shell)
                or rc == 127 or "not found" in low or "no such file" in low):
            return _not_found
        tail = out.strip()[-2000:]
        if "permission" in low or "denied" in low or "not granted" in low:
            return (f"error: {argv[0]} exited {rc} (Termux:API permission "
                    f"not granted? grant it in Android settings): {tail}")
        return f"error: {argv[0]} exited {rc}: {tail}"
    return out


def _ts() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"


def _ipgeo() -> dict:
    """Approximate location from the public IP. Keyless. {} on failure."""
    for url, keymap in (
        ("https://ipwho.is/", {"city": "city", "region": "region", "country": "country",
                               "latitude": "latitude", "longitude": "longitude"}),
        ("https://ipapi.co/json/", {"city": "city", "region": "region", "country": "country_name",
                                    "latitude": "latitude", "longitude": "longitude"}),
    ):
        try:
            r = httpx.request("GET", url, timeout=8)
            if r.status_code >= 400:
                continue
            d = r.json()
            if not isinstance(d, dict) or d.get("success") is False:
                continue
            # ipapi.co signals its rate limit as {"error": true, "reason": "RateLimited"}
            if d.get("error") or d.get("reason") == "RateLimited":
                continue
            out = {k: d.get(src) for k, src in keymap.items() if d.get(src) is not None}
            conn = d.get("connection") or {}
            if conn.get("isp"):
                out["isp"] = conn["isp"]
            elif d.get("org"):
                out["isp"] = d["org"]
            if out.get("city") or out.get("latitude"):
                return out
        except Exception:  # noqa: BLE001
            continue
    return {}


def register() -> None:
    @tools.tool(
        "sensors_camera_photo",
        "Take a photo with the phone camera (facing: 'back' or 'front').",
        {"type": "object",
         "properties": {"facing": {"type": "string", "enum": ["back", "front"],
                                   "default": "back"}}},
    )
    def sensors_camera_photo(facing: str = "back"):
        cam = "1" if facing == "front" else "0"
        out = _TMP / f"cam-{_ts()}.jpg"
        res = _run(["termux-camera-photo", "-c", cam, str(out)], timeout=60)
        if res.startswith("error:"):
            return res
        if not out.exists():
            return f"error: termux-camera-photo produced no file: {res}"
        # emit_image reads the file lazily at end of turn — do NOT delete it.
        emit_image(str(out), "image/jpeg")
        return "photo captured"

    @tools.tool(
        "sensors_mic_record",
        "Record from the microphone for N seconds (max 60); returns the .m4a "
        "file path. Blocks the turn for the duration, so keep it short.",
        {"type": "object",
         "properties": {"seconds": {"type": "integer", "default": 8}}},
    )
    def sensors_mic_record(seconds: int = 8):
        seconds = max(1, min(int(seconds), 60))
        out = _TMP / f"mic-{_ts()}.m4a"
        started = _run(["termux-microphone-record", "-l", str(seconds), "-f", str(out)],
                       timeout=60)
        if started.startswith("error:"):
            return started
        time.sleep(seconds)
        _run(["termux-microphone-record", "-q"], timeout=60)
        return str(out)

    @tools.tool(
        "sensors_location",
        "Where the phone is. mode='quick' (default): wifi network + approximate "
        "city from the public IP, fast and reliable. mode='gps'/'network': real "
        "coordinates from termux-location (slow, can hang indoors).",
        {"type": "object",
         "properties": {"mode": {"type": "string", "enum": ["quick", "gps", "network"],
                                 "default": "quick"},
                        "accuracy": {"type": "string", "enum": ["coarse", "fine"]}},
        },
    )
    def sensors_location(mode="quick", accuracy=None):
        if accuracy and mode == "quick":
            mode = "network" if accuracy == "coarse" else "gps"
        if mode in ("gps", "network"):
            return _run(["termux-location", "-p", mode], timeout=60)
        import json as _json
        wifi_raw = _run(["termux-wifi-connectioninfo"], timeout=15)
        try:
            wifi = _json.loads(wifi_raw)
        except (ValueError, TypeError):
            wifi = {"raw": wifi_raw[:300]}
        return _json.dumps({"wifi": wifi, "approx": _ipgeo(),
                            "note": "approx is city-level from the IP; call with mode='gps' for coordinates"})

    @tools.tool(
        "sensors_notifications",
        "List the phone's current status-bar notifications as JSON.",
        {"type": "object", "properties": {}},
    )
    def sensors_notifications():
        return _run(["termux-notification-list"])

    @tools.tool(
        "sensors_tts_speak",
        "Speak text aloud through the phone's text-to-speech engine.",
        {"type": "object", "properties": {"text": {"type": "string"}},
         "required": ["text"]},
    )
    def sensors_tts_speak(text: str):
        res = _run(["termux-tts-speak", text])
        return res if res.startswith("error:") else "spoken"

    @tools.tool(
        "sensors_clipboard_get",
        "Read the phone's clipboard.",
        {"type": "object", "properties": {}},
    )
    def sensors_clipboard_get():
        return _run(["termux-clipboard-get"])

    @tools.tool(
        "sensors_clipboard_set",
        "Write text to the phone's clipboard.",
        {"type": "object", "properties": {"text": {"type": "string"}},
         "required": ["text"]},
    )
    def sensors_clipboard_set(text: str):
        res = _run(["termux-clipboard-set", text])
        return res if res.startswith("error:") else "set"

    @tools.tool(
        "sensors_battery",
        "Get the phone's battery status as JSON.",
        {"type": "object", "properties": {}},
    )
    def sensors_battery():
        return _run(["termux-battery-status"])

    @tools.tool(
        "sensors_torch",
        "Turn the phone's flashlight on or off.",
        {"type": "object", "properties": {"on": {"type": "boolean", "default": True}}},
    )
    def sensors_torch(on: bool = True):
        state = "on" if on else "off"
        res = _run(["termux-torch", state])
        return res if res.startswith("error:") else f"torch {state}"
