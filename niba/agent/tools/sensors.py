from __future__ import annotations

import time
from pathlib import Path

from niba.agent import proc
from niba.agent import tools
from niba.agent.tools.media import emit_image

#: Where camera / mic captures are written. Set by configure().
_TMP: Path = Path(".")

CAP = 6000


#: I10: prune tmp captures older than this on configure().
TMP_MAX_AGE_S = 24 * 3600


def configure(niba_home) -> None:
    """Point captures at <niba_home>/tmp (the test passes a tmp dir directly)."""
    global _TMP
    p = Path(niba_home)
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
        "Get the current location as JSON (accuracy: 'coarse' or 'fine').",
        {"type": "object",
         "properties": {"accuracy": {"type": "string", "enum": ["coarse", "fine"],
                                     "default": "coarse"}}},
    )
    def sensors_location(accuracy: str = "coarse"):
        provider = "network" if accuracy == "coarse" else "gps"
        return _run(["termux-location", "-p", provider], timeout=60)

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
