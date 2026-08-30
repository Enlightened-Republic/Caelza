# Niba Device & Sensor Tools — Implementation Plan (Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give Niba hands and senses on the phone — a shell tool, `termux-api` sensor wrappers (camera/mic/location/notifications/TTS/clipboard/battery/torch), and an ADB tool surface that controls her own phone and any paired remote Android device — plus a `niba setup` command that automates the whole first-boot bring-up.

**Architecture:** Additive tool modules registered through the existing `niba.agent.tools` registry (Plan 1). No changes to the supervisor or the model layer. One new cross-cutting mechanism: a **media sink** so an image-producing tool (camera, screencap) actually reaches M3 as an image, not just a file path. Device targeting is a `device=` argument on every `device_*` tool: `"self"` = the phone's own loopback ADB, any other name = a `~/.niba/devices.json` registry entry.

**Tech Stack:** Python 3.11+ on Termux/arm64. `termux-api` binaries (`termux-camera-photo`, etc.). `adb` (Termux `pkg install android-tools`). `pytest`. No new Python deps.

**Spec:** `docs/superpowers/specs/2026-08-29-niba-design.md` §5.5–5.7, §14.0 — read before starting.

## Global Constraints

- **Non-root.** Self-ADB is `adb connect 127.0.0.1:<wireless-debug-port>`; it grants shell-user reach (`pm`, `settings`, `input`, `dumpsys`, `am`, `screencap`) — nothing more.
- **Termux target.** `adb` = `pkg install android-tools`. `termux-*` binaries need the Termux:API app (installed) + runtime permissions (the setup command grants them).
- **Tool naming:** `shell_run`; `sensors_<thing>` (`sensors_camera_photo`, …); `device_<verb>` (`device_list`, `device_shell`, …). Registered via `niba.agent.tools.tool(name, description, parameters)`.
- **`device=` default is `"self"`** on every `device_*` tool that acts on a device.
- **Device registry** is a plain JSON file at `$NIBA_HOME/devices.json` — never SharpWave.
- **Dangerous device ops** (`device_uninstall`, `device_disable`, `device_settings` with a value, `device_appops`) require a `reason: str` argument, are appended to `$NIBA_HOME/logs/device-actions.log`, and — for any package removal on any device — write a `pm list packages -f` snapshot to `$NIBA_HOME/snapshots/<device>-<unix_ts>.txt` first.
- **Output caps:** shell/adb-shell output truncated to ~8 KB. `device_logcat` bounded by `lines`.
- **Media sink:** tools that produce an image append `(path: str, mime: str)` to `niba.agent.tools.PENDING_MEDIA`; `loop.handle_turn` drains it into a `{"role":"user","content":[image parts]}` message before the next `model.complete`.
- **Commits:** one per step where shown; AI-agent trailer `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- **Config:** `configure(niba_home)` (module-level, called once at startup, like `selfmod.configure`) before `register()`'s tools are used. Wire every new module into `niba/agent/main.py` `_register_tools` and `loop.probe`.

---

## File Structure

| File | Responsibility |
|---|---|
| `niba/agent/tools/shell.py` | `shell_run` — bounded Termux shell. |
| `niba/agent/tools/media.py` | `PENDING_MEDIA` list + `emit_image(path, mime)` helper; re-exported from `tools/__init__.py`. |
| `niba/agent/tools/sensors.py` | `termux-api` wrappers. Camera/mic call `emit_image` / return a path. |
| `niba/agent/devices.py` | `DeviceRegistry` — load/save/add/remove/get against `$NIBA_HOME/devices.json`. |
| `niba/agent/adb.py` | `Adb` — resolve `device` name → serial, run `adb` commands, `connect_self()`, `pair(host, code)`. |
| `niba/agent/tools/device.py` | The `device_*` tools; composes `DeviceRegistry` + `Adb`; dangerous-op logging + snapshots. |
| `scripts/setup.py` | `niba setup` — automated first-boot bring-up. |
| `niba/agent/loop.py` | (modify) drain `PENDING_MEDIA` into an image message each round. |
| `niba/agent/main.py` | (modify) register + configure the new modules. |
| `tests/tools/test_shell.py`, `test_sensors.py`, `test_device.py`; `tests/test_devices.py`, `tests/test_adb.py`, `tests/test_media_sink.py` | |

---

## Task 1: `shell_run` tool

**Files:** Create `niba/agent/tools/shell.py`, `tests/tools/test_shell.py`.

**Interfaces:**
- Produces: `register()` registers `shell_run`. `shell_run(cmd: str, timeout: int = 60) -> str` — runs `cmd` via `subprocess.run(cmd, shell=True, ...)` in Termux, merges stdout+stderr, returns `f"exit {rc}\n{output[-8000:]}"`; on `TimeoutExpired` returns `f"error: timed out after {timeout}s"`.

- [ ] **Step 1: failing test** — `tests/tools/test_shell.py`:

```python
import pytest
from niba.agent import tools
from niba.agent.tools import shell


@pytest.fixture(autouse=True)
def _clean():
    tools.reset(); shell.register(); yield; tools.reset()


def test_runs_and_reports_exit_and_output():
    out = tools.dispatch("shell_run", {"cmd": "echo hi; exit 3"})
    assert "exit 3" in out and "hi" in out


def test_timeout():
    out = tools.dispatch("shell_run", {"cmd": "sleep 5", "timeout": 1})
    assert out.startswith("error: timed out")


def test_output_is_capped():
    out = tools.dispatch("shell_run", {"cmd": "yes x | head -c 20000"})
    assert len(out) < 8200
```

- [ ] **Step 2: run — FAIL** (`ModuleNotFoundError`).

- [ ] **Step 3: implement** — `niba/agent/tools/shell.py`:

```python
from __future__ import annotations

import subprocess

from niba.agent import tools

CAP = 8000


def register():
    @tools.tool("shell_run", "Run a shell command in Niba's Termux environment.",
                {"type": "object",
                 "properties": {"cmd": {"type": "string"},
                                "timeout": {"type": "integer", "default": 60}},
                 "required": ["cmd"]})
    def shell_run(cmd, timeout=60):
        try:
            p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                               timeout=timeout)
        except subprocess.TimeoutExpired:
            return f"error: timed out after {timeout}s"
        out = (p.stdout + p.stderr)[-CAP:]
        return f"exit {p.returncode}\n{out}"
```

- [ ] **Step 4: run — PASS.**
- [ ] **Step 5: commit** — `git add niba/agent/tools/shell.py tests/tools/test_shell.py && git commit -m "feat: shell_run tool"`

---

## Task 2: media sink

**Files:** Create `niba/agent/tools/media.py`, `tests/test_media_sink.py`. Modify `niba/agent/tools/__init__.py` (re-export), `niba/agent/loop.py`.

**Interfaces:**
- Produces:
  - `niba/agent/tools/media.py`: module-level `PENDING_MEDIA: list[tuple[str, str]]`; `emit_image(path: str, mime: str = "image/jpeg") -> None` appends `(path, mime)`; `drain() -> list[tuple[str,str]]` returns and clears.
  - `tools/__init__.py` re-exports `PENDING_MEDIA`, `emit_image`, `drain` (so `tools.drain()` works).
  - `loop.handle_turn`: after each tool-dispatch round, before looping back to `model.complete`, if `tools_mod.drain()` returns items, append `{"role": "user", "content": [ {"type": "text", "text": "(tool output — image)"}, *[image_part(p, m) for p, m in items] ]}` to `messages`. `image_part` = the same data-URI builder `_photo_content` uses (factor it into `_image_part(path, mime)` in loop.py).

- [ ] **Step 1: failing tests** — `tests/test_media_sink.py`:

```python
import base64
from niba.agent import tools
from niba.agent.tools import media
from niba.agent.loop import handle_turn
from niba.agent.session import Session
from niba.agent.redact import Redactor
from niba.agent.telegram import Update
from niba.agent.model import Assistant, ToolCall


def test_emit_and_drain():
    media.PENDING_MEDIA.clear()
    media.emit_image("/tmp/a.png", "image/png")
    assert tools.drain() == [("/tmp/a.png", "image/png")]
    assert tools.drain() == []


def test_image_tool_result_reaches_model_as_image(tmp_path):
    img = tmp_path / "shot.png"; img.write_bytes(b"PNGDATA")
    tools.reset(); media.PENDING_MEDIA.clear()

    @tools.tool("snap", "d", {"type": "object", "properties": {}})
    def snap():
        media.emit_image(str(img), "image/png")
        return "captured"

    class M:
        def __init__(s): s.seen = []
        def complete(s, messages, toolz):
            s.seen.append(messages)
            if len(s.seen) == 1:
                return Assistant(None, [ToolCall("c1", "snap", {})],
                                 {"role": "assistant", "tool_calls": [
                                     {"id": "c1", "type": "function",
                                      "function": {"name": "snap", "arguments": "{}"}}]})
            return Assistant("i see it", [], {"role": "assistant", "content": "i see it"})

    class FakeMem:
        def recall(s, q, k=8): return []
        def remember(s, t, links=None): return "n1"

    sent = []
    class FakeTg:
        def send_typing(s, c): pass
        def send_message(s, c, t): sent.append(t)
        def download_file(s, *a): raise AssertionError

    prompt = tmp_path / "p.md"; prompt.write_text("x")
    m = M()
    handle_turn(update=Update(1, 42, text="what do you see"), telegram=FakeTg(), model=m,
                memory=FakeMem(), session=Session(tmp_path / "s.db"), tools_mod=tools,
                prompt_path=prompt, cfg=None, redactor=Redactor([]), tmp_dir=tmp_path)
    # round 2's messages must contain an image part carrying the file's bytes
    round2 = m.seen[1]
    imgs = [part for msg in round2 if isinstance(msg.get("content"), list)
            for part in msg["content"] if part.get("type") == "image_url"]
    assert imgs and base64.b64encode(b"PNGDATA").decode() in imgs[0]["image_url"]["url"]
    assert sent == ["i see it"]
```

- [ ] **Step 2: run — FAIL.**

- [ ] **Step 3: implement `media.py`:**

```python
from __future__ import annotations

PENDING_MEDIA: list[tuple[str, str]] = []


def emit_image(path: str, mime: str = "image/jpeg") -> None:
    PENDING_MEDIA.append((path, mime))


def drain() -> list[tuple[str, str]]:
    items = list(PENDING_MEDIA)
    PENDING_MEDIA.clear()
    return items
```

- [ ] **Step 4: re-export from `tools/__init__.py`** — add at the bottom:

```python
from niba.agent.tools.media import PENDING_MEDIA, drain, emit_image  # noqa: E402,F401
```

- [ ] **Step 5: wire into `loop.py`** — factor the data-URI builder out of `_photo_content` into:

```python
def _image_part(path, mime):
    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
```

and in `handle_turn`, right after the `for call in assistant.tool_calls:` block that appends tool results, add:

```python
        media = tools_mod.drain()
        if media:
            messages.append({"role": "user", "content": [
                {"type": "text", "text": "(tool output — image)"},
                *[_image_part(p, m) for p, m in media],
            ]})
```

- [ ] **Step 6: run — PASS.** Also run the full suite (`pytest -q`) — `test_loop.py` must still pass.
- [ ] **Step 7: commit** — `feat: media sink so image tools reach the model`

---

## Task 3: `sensors.py` (termux-api wrappers)

**Files:** Create `niba/agent/tools/sensors.py`, `tests/tools/test_sensors.py`.

**Interfaces:**
- Consumes: `emit_image` (Task 2), `tools.tool` registry.
- Produces: `configure(niba_home)` (stores the tmp dir for captures); `register()` registers:

| Tool | Command | Result |
|---|---|---|
| `sensors_camera_photo(facing="back")` | `termux-camera-photo -c {0\|1} <tmp>/cam-<ts>.jpg` | `emit_image(path)`; returns `"photo captured"` |
| `sensors_mic_record(seconds=8)` | `termux-microphone-record -l {seconds} -f <tmp>/mic-<ts>.m4a` then `-q` to stop | returns the file path (M3 STT is a later concern) |
| `sensors_location(accuracy="coarse")` | `termux-location -p {network\|gps}` | returns the JSON string |
| `sensors_notifications()` | `termux-notification-list` | returns the JSON string (trim to ~6 KB) |
| `sensors_tts_speak(text)` | `termux-tts-speak {text}` | returns `"spoken"` |
| `sensors_clipboard_get()` | `termux-clipboard-get` | returns the text |
| `sensors_clipboard_set(text)` | `termux-clipboard-set {text}` | returns `"set"` |
| `sensors_battery()` | `termux-battery-status` | returns the JSON string |
| `sensors_torch(on=True)` | `termux-torch {on\|off}` | returns `"torch {on\|off}"` |

Each wraps a helper `_run(argv, timeout=30) -> str` (merges stdout/stderr, caps 6 KB). If the binary is missing or exits non-zero with a permission hint, return `f"error: {argv[0]} failed (permission not granted? run: termux-setup + grant in Android settings): {tail}"`.

- [ ] **Step 1: failing test** — `tests/tools/test_sensors.py` (put fake `termux-*` scripts on `PATH` via a `tmp_path` bin dir + `monkeypatch.setenv("PATH", ...)`):

```python
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


def test_missing_binary_is_a_clean_error(fake_termux):
    assert tools.dispatch("sensors_location", {}).startswith("error:")
```

- [ ] **Step 2: run — FAIL.**
- [ ] **Step 3: implement `sensors.py`** per the table (helper `_run`, `configure`, `register`). Camera: `-c 0` for back, `-c 1` for front.
- [ ] **Step 4: run — PASS.**
- [ ] **Step 5: commit** — `feat: termux-api sensor tools`

---

## Task 4: wire shell + sensors + media into main + probe

**Files:** Modify `niba/agent/main.py`, `niba/agent/loop.py` (`probe`), `tests/test_wiring.py`.

**Interfaces:**
- `main._register_tools(repo_root, niba_home)` gains: `shell.register()`; `sensors.configure(niba_home); sensors.register()`.
- `loop.probe` — after `_register_tools`, assert `"shell_run" in tools.REGISTRY` and `"sensors_battery" in tools.REGISTRY` (a cheap "did registration run" check); non-zero if missing.

- [ ] **Step 1: failing test** — add to `tests/test_wiring.py`:

```python
def test_all_v1_and_plan2_a_tools_register():
    from niba.agent import tools
    from niba.agent.tools import selfmod, shell, sensors, memtools
    tools.reset()
    selfmod.register(); shell.register(); sensors.register(); memtools.configure(object())
    memtools.register()
    names = set(tools.REGISTRY)
    assert {"self_read_file", "shell_run", "sensors_camera_photo", "memory_recall"} <= names
```

- [ ] **Step 2: run — FAIL** (import error / missing names).
- [ ] **Step 3: implement** the `main._register_tools` + `probe` edits.
- [ ] **Step 4: run — PASS** + full suite.
- [ ] **Step 5: commit** — `feat: register shell + sensor tools`

---

## Task 5: `DeviceRegistry`

**Files:** Create `niba/agent/devices.py`, `tests/test_devices.py`.

**Interfaces:**
- Produces: `class DeviceRegistry(path: Path)`:
  - `.add(name: str, host: str, notes: str = "") -> None` (sets `paired_at` = ISO now via `datetime.now(timezone.utc)`, `last_seen` = same)
  - `.remove(name: str) -> None`
  - `.get(name: str) -> dict | None` (`{host, paired_at, last_seen, notes}`)
  - `.all() -> dict[str, dict]`
  - `.touch(name: str) -> None` (updates `last_seen`)
  - Persists to `path` (JSON, `{name: {...}}`) on every mutation; tolerates a missing/corrupt file (starts empty).

- [ ] **Step 1: failing test** — `tests/test_devices.py`:

```python
import json
from niba.agent.devices import DeviceRegistry


def test_add_get_all_remove(tmp_path):
    r = DeviceRegistry(tmp_path / "d.json")
    r.add("grandma", "192.168.1.9:5555", notes="her pixel")
    assert r.get("grandma")["host"] == "192.168.1.9:5555"
    assert "grandma" in r.all()
    r.remove("grandma")
    assert r.get("grandma") is None
    # persisted
    assert json.loads((tmp_path / "d.json").read_text()) == {}


def test_corrupt_file_starts_empty(tmp_path):
    (tmp_path / "d.json").write_text("{not json")
    assert DeviceRegistry(tmp_path / "d.json").all() == {}


def test_touch_updates_last_seen(tmp_path):
    r = DeviceRegistry(tmp_path / "d.json")
    r.add("x", "h")
    before = r.get("x")["last_seen"]
    import time; time.sleep(0.01)
    r.touch("x")
    assert r.get("x")["last_seen"] >= before
```

- [ ] **Step 2: run — FAIL.**
- [ ] **Step 3: implement `devices.py`.**
- [ ] **Step 4: run — PASS.**
- [ ] **Step 5: commit** — `feat: device registry`

---

## Task 6: `Adb` runner + self-connect + pair

**Files:** Create `niba/agent/adb.py`, `tests/test_adb.py`.

**Interfaces:**
- Consumes: `DeviceRegistry` (Task 5).
- Produces: `class Adb(registry: DeviceRegistry, self_serial: str = "127.0.0.1:<port>")`:
  - `SELF_PORT` read from `$NIBA_HOME/run/adb-self-port` if present, else default `5555`; `self_serial = f"127.0.0.1:{port}"`.
  - `.serial(device: str) -> str` — `"self"` → `self_serial`; otherwise `registry.get(device)["host"]` (raise `KeyError` → surfaced as tool error if unknown).
  - `.run(device: str, *args: str, timeout: int = 30) -> str` — `adb -s <serial> <args...>`, merged output capped ~8 KB, prefixed `f"exit {rc}\n"`.
  - `.connect_self() -> bool` — `adb connect <self_serial>`; True on `connected`/`already connected`.
  - `.pair(name: str, host: str, code: str, notes: str = "") -> str` — `adb pair <host_pair_addr> <code>`; on success `adb connect <host>` + `registry.add(name, host, notes)`; returns a status string.
  - All `adb` invocations go through one `_adb(*args, timeout)` helper (so tests fake a single `adb` binary).

- [ ] **Step 1: failing test** — `tests/test_adb.py` (fake `adb` script that echoes its args + canned responses):

```python
import os, stat
import pytest
from niba.agent.devices import DeviceRegistry
from niba.agent.adb import Adb


@pytest.fixture
def fake_adb(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"; bindir.mkdir()
    p = bindir / "adb"
    p.write_text(
        '#!/bin/sh\n'
        'case "$*" in\n'
        '  *"connect"*) echo "connected to $2";;\n'
        '  *"pair"*) echo "Successfully paired";;\n'
        '  *"-s "*" shell getprop"*) echo "TMRV075G";;\n'
        '  *) echo "args: $*";;\n'
        'esac\n')
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return tmp_path


def test_serial_resolution(fake_adb, tmp_path):
    r = DeviceRegistry(tmp_path / "d.json"); r.add("gma", "10.0.0.5:5555")
    a = Adb(r, self_serial="127.0.0.1:5555")
    assert a.serial("self") == "127.0.0.1:5555"
    assert a.serial("gma") == "10.0.0.5:5555"


def test_run_targets_the_right_serial(fake_adb, tmp_path):
    a = Adb(DeviceRegistry(tmp_path / "d.json"), self_serial="127.0.0.1:5555")
    out = a.run("self", "shell", "echo", "hi")
    assert "-s 127.0.0.1:5555 shell echo hi" in out


def test_connect_self(fake_adb, tmp_path):
    assert Adb(DeviceRegistry(tmp_path / "d.json")).connect_self() is True


def test_pair_registers(fake_adb, tmp_path):
    r = DeviceRegistry(tmp_path / "d.json")
    Adb(r).pair("gma", "10.0.0.5:5555", "123456")
    assert r.get("gma")["host"] == "10.0.0.5:5555"
```

- [ ] **Step 2: run — FAIL.**
- [ ] **Step 3: implement `adb.py`.**
- [ ] **Step 4: run — PASS.**
- [ ] **Step 5: commit** — `feat: adb runner + self-connect + pair`

---

## Task 7: `device.py` read tools

**Files:** Create `niba/agent/tools/device.py`, `tests/tools/test_device.py`.

**Interfaces:**
- Consumes: `Adb`, `DeviceRegistry`, `emit_image`, `tools.tool`.
- Produces: `configure(niba_home)` — builds the `DeviceRegistry($NIBA_HOME/devices.json)` + `Adb`, stores module-side; `register()` registers the read tools:

| Tool | Behaviour |
|---|---|
| `device_list()` | `{name: {host, last_seen, reachable: bool}}` from registry + `adb devices`; plus `"self": {reachable: connect_self()}` |
| `device_shell(cmd, device="self")` | `adb.run(device, "shell", cmd)` |
| `device_screencap(device="self")` | `adb -s .. exec-out screencap -p` → save to `$NIBA_HOME/tmp/screen-<device>-<ts>.png` → `emit_image(path, "image/png")` → return `"screenshot captured"` |
| `device_ui_dump(device="self")` | `adb.run(device, "shell", "uiautomator dump /sdcard/u.xml && cat /sdcard/u.xml")`, capped |
| `device_packages(flags="-3", device="self")` | `adb.run(device, "shell", "pm list packages " + flags)` |
| `device_logcat(filter=None, lines=200, device="self")` | `adb.run(device, "logcat", "-d", "-t", str(lines), *( [filter] if filter else [] ))` |
| `device_settings(ns, key, device="self")` | GET only here: `adb.run(device, "shell", f"settings get {ns} {key}")` |

- [ ] **Step 1: failing test** — `tests/tools/test_device.py` (reuse the `fake_adb` pattern; add `exec-out screencap` → prints `PNG` bytes):

```python
import pytest
from niba.agent import tools
from niba.agent.tools import device, media
# fake_adb fixture copied/imported; screencap branch: *"exec-out screencap"*) printf 'PNGBYTES';;

@pytest.fixture(autouse=True)
def _cfg(fake_adb, tmp_path):
    tools.reset(); media.PENDING_MEDIA.clear()
    device.configure(tmp_path); device.register()


def test_device_shell_self():
    assert "echo hi" in tools.dispatch("device_shell", {"cmd": "echo hi"})


def test_device_screencap_emits_image(tmp_path):
    out = tools.dispatch("device_screencap", {})
    assert "captured" in out and len(media.PENDING_MEDIA) == 1


def test_device_shell_unknown_device_is_error():
    out = tools.dispatch("device_shell", {"cmd": "x", "device": "nope"})
    assert out.startswith("error:")
```

- [ ] **Step 2: run — FAIL.**
- [ ] **Step 3: implement the read tools.**
- [ ] **Step 4: run — PASS.**
- [ ] **Step 5: commit** — `feat: device read tools (shell, screencap, ui_dump, packages, logcat)`

---

## Task 8: `device.py` write / dangerous tools + pair

**Files:** Modify `niba/agent/tools/device.py`, `tests/tools/test_device.py`.

**Interfaces:**
- Produces (added to `register()`):

| Tool | Behaviour |
|---|---|
| `device_pair(name, host, code, notes="")` | `adb.pair(...)` |
| `device_unpair(name)` | `registry.remove(name)` |
| `device_input(action, device="self", x=None, y=None, x2=None, y2=None, text=None, key=None)` | `action` ∈ `tap`(x,y) / `swipe`(x,y,x2,y2) / `text`(text) / `keyevent`(key). `adb.run(device, "shell", "input", ...)` |
| `device_settings_put(ns, key, value, reason, device="self")` | dangerous: log + `adb.run(device, "shell", f"settings put {ns} {key} {value}")` |
| `device_appops(pkg, op, mode, reason, device="self")` | dangerous: log + `adb.run(device, "shell", f"appops set {pkg} {op} {mode}")` |
| `device_uninstall(pkg, reason, device="self")` | dangerous: **snapshot first** (`_snapshot(device)`), log, `adb.run(device, "shell", f"pm uninstall --user 0 {pkg}")` |
| `device_disable(pkg, reason, device="self")` | dangerous: snapshot, log, `pm disable-user --user 0 {pkg}` |

- `_log_action(device, tool, detail, reason)` → appends a line to `$NIBA_HOME/logs/device-actions.log`.
- `_snapshot(device)` → `adb.run(device, "shell", "pm list packages -f")` written to `$NIBA_HOME/snapshots/<device>-<ts>.txt`.
- Dangerous tools' JSON schema has `reason` in `required`.

- [ ] **Step 1: failing tests** — add to `tests/tools/test_device.py`:

```python
def test_uninstall_snapshots_and_logs(tmp_path):
    tools.dispatch("device_uninstall", {"pkg": "com.junk", "reason": "adware"})
    snaps = list((tmp_path / "snapshots").glob("self-*.txt"))
    assert snaps
    log = (tmp_path / "logs" / "device-actions.log").read_text()
    assert "com.junk" in log and "adware" in log


def test_dangerous_tool_requires_reason():
    out = tools.dispatch("device_disable", {"pkg": "com.x"})  # no reason
    assert out.startswith("error:")  # dispatch surfaces the TypeError


def test_input_tap():
    out = tools.dispatch("device_input", {"action": "tap", "x": 100, "y": 200})
    assert "input tap 100 200" in out
```

- [ ] **Step 2: run — FAIL.**
- [ ] **Step 3: implement** the write/dangerous tools + `_log_action` + `_snapshot`.
- [ ] **Step 4: run — PASS** + full suite.
- [ ] **Step 5: commit** — `feat: device write + dangerous tools with logging + snapshots`

---

## Task 9: wire `device` into main + probe; `scripts/setup.py`

**Files:** Modify `niba/agent/main.py`, `niba/agent/loop.py`; create `scripts/setup.py`, `tests/test_setup.py`.

**Interfaces:**
- `main._register_tools`: `device.configure(niba_home); device.register()`.
- `loop.probe`: assert `"device_list"` in registry.
- `scripts/setup.py` — `python scripts/setup.py [--dry-run]`. Pure-helper functions (testable) + an `run()` that sequences them:
  - `pkg_install()` — `pkg install -y python nodejs git openssh termux-api android-tools`
  - `sharpwave_install()` — `npm i -g --allow-scripts=better-sqlite3 sharpwave` + `termux-fix-shebang $(command -v sharpwave)`
  - `mcp_install()` — `pip install "mcp>=1.0,<2" httpx`
  - `grant_perms()` — `termux-setup-storage`; print the Android-settings permissions the owner must grant for `termux-api`
  - `write_config(telegram_token, owner_chat_id, openrouter_key)` — write `$NIBA_HOME/config.toml`
  - `mmx_login()` — run `mmx auth login` (interactive; the human completes the browser step)
  - `pair_self_adb()` — walk the human through enabling Wireless debugging, read the port + pairing code, `adb pair` + write `$NIBA_HOME/run/adb-self-port`
  - `install_boot_script()` — write `~/.termux/boot/niba`
  - `capture_owner_chat_id(telegram_token)` — poll `getUpdates` until a message arrives, return its chat id
  - Each step: `[auto]` runs; `[prompt]` prints instructions and waits for Enter / an input value. `--dry-run` prints the plan and exits.

- [ ] **Step 1: failing test** — `tests/test_setup.py` (test the pure helpers; the interactive `run()` only via `--dry-run`):

```python
import sys, subprocess
from pathlib import Path


def test_write_config(tmp_path, monkeypatch):
    monkeypatch.setenv("NIBA_HOME", str(tmp_path))
    sys.path.insert(0, "scripts")
    import setup
    setup.write_config("TG", 42, "OR", niba_home=tmp_path)
    text = (tmp_path / "config.toml").read_text()
    assert 'bot_token = "TG"' in text and "owner_chat_id = 42" in text and 'api_key = "OR"' in text


def test_dry_run_lists_steps():
    out = subprocess.run([sys.executable, "scripts/setup.py", "--dry-run"],
                         capture_output=True, text=True)
    assert "pkg_install" in out.stdout and "mmx_login" in out.stdout
    assert out.returncode == 0
```

- [ ] **Step 2: run — FAIL.**
- [ ] **Step 3: implement** `scripts/setup.py` + the `main`/`probe` wiring.
- [ ] **Step 4: run — PASS** + full suite.
- [ ] **Step 5: commit** — `feat: device wiring + niba setup command`

---

## Self-Review

**Spec coverage:**

| Spec item | Task |
|---|---|
| §5.7 `shell_run` | 1 |
| §5.6 sensor wrappers | 3 |
| image tools reach the model | 2 (media sink) — *not in the spec explicitly; a real gap, added* |
| §5.5 `device_*` self + remote, `device=` param | 6, 7, 8 |
| §5.5 JSON registry `~/.niba/devices.json` | 5 |
| §5.5 self-ADB connect-on-start | 6 (`connect_self`), 9 (`pair_self_adb` in setup) |
| §5.5 dangerous-op `reason` + `device-actions.log` + pre-removal snapshot | 8 |
| §14.0 Phase C `niba setup` | 9 |
| wire into main + probe | 4, 9 |

**Gaps found:**
- **Media sink** isn't in the spec — but `sensors_camera_photo` / `device_screencap` are useless without it. Added as Task 2 and noted in Global Constraints; fold the mechanism into spec §5.2 after this plan lands.
- `mic_record` → STT is still deferred (spec §15 open item). `sensors_mic_record` returns a path; nothing transcribes it yet. Acceptable for this plan.
- `scripts/setup.py`'s interactive steps are lightly tested (helpers + `--dry-run` only). Genuinely interactive; the real test is running it on phone #2.

**Deferred from `niba setup` (final-review I8, spec §12):** the
battery-optimisation whitelist (§12 step 4) and a final "start the supervisor /
verify the Telegram reply" step (§12 step 11) were added to `STEPS` in the
final-fix wave (`battery_unrestrict`, `verify`). `tailscale up` (§12 step 6) and
the repo `git clone` / `pip install -e .` (§12 step 9) are **deliberately out of
scope**: `niba setup` is run *from* the clone (`python scripts/setup.py`), so the
clone + install and the Tailscale auth are bootstrap-before-setup, documented in
`docs/setup.md` rather than automated by the script.

**Placeholder scan:** none — every step has real code or a concrete command table.

**Type consistency:** `device=` default `"self"` everywhere; `Adb.serial`/`.run` signatures consistent T6→T7→T8; `DeviceRegistry` methods consistent T5→T6→T7→T8; `emit_image`/`drain` consistent T2→T3→T7; `tools.tool`/`tools.dispatch`/`tools.reset` per Plan 1. `configure(niba_home)` + `register()` pattern matches `selfmod`.
