"""Read-only device tools: inspect paired phones and this phone over adb.

`configure()` wires up a `DeviceRegistry` + `Adb` for `$NIBA_HOME/devices.json`.
`register()` registers the read tools. More `@tools.tool` defs (write/UI actions)
are appended to `register()` by a later task — keep each one self-contained and
use `_unknown(device)` for the "is this device known?" guard.
"""
from __future__ import annotations

import shlex
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from niba.agent import adb as _adb_mod
from niba.agent import proc
from niba.agent import tools
from niba.agent.adb import Adb
from niba.agent.devices import DeviceRegistry
from niba.agent.tools.media import emit_image

#: Set by configure().
_NIBA_HOME: Path | None = None
_TMP: Path | None = None
registry: DeviceRegistry | None = None
adb: Adb | None = None

#: adb screencap can be slow on a cold device.
SCREENCAP_TIMEOUT = 30

#: I10: keep $NIBA_HOME/tmp and $NIBA_HOME/snapshots from growing without bound.
TMP_MAX_AGE_S = 24 * 3600
KEEP_SNAPSHOTS = 20


def _prune() -> None:
    """Best-effort: drop tmp captures older than 24h and old package snapshots.
    A prune failure must never break startup."""
    if _TMP is None or _NIBA_HOME is None:
        return  # configure() hasn't run — never touch the cwd
    try:
        cutoff = time.time() - TMP_MAX_AGE_S
        for f in _TMP.glob("*"):
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
    except Exception:  # noqa: BLE001
        pass
    try:
        snaps = sorted((_NIBA_HOME / "snapshots").glob("*"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for f in snaps[KEEP_SNAPSHOTS:]:
            f.unlink()
    except Exception:  # noqa: BLE001
        pass


def configure(niba_home) -> None:
    """Wire the module to <niba_home>: registry, Adb, and a tmp dir for captures."""
    global _NIBA_HOME, _TMP, registry, adb
    _NIBA_HOME = Path(niba_home)
    _adb_mod.configure(_NIBA_HOME)  # so the self-port file is found
    registry = DeviceRegistry(_NIBA_HOME / "devices.json")
    adb = Adb(registry)
    _TMP = _NIBA_HOME / "tmp"
    _TMP.mkdir(parents=True, exist_ok=True)
    _prune()
    # Spec §5.5: on start, device.py runs `adb connect 127.0.0.1:<port>` so the
    # first self-targeting tool call after a reboot works. Off the calling
    # thread: connect_self() can spend tens of seconds scanning, and configure()
    # runs inside the supervisor's 60s probe budget on the --probe path.
    threading.Thread(target=_connect_self_quietly, name="niba-adb-self",
                     daemon=True).start()


def _connect_self_quietly() -> None:
    try:
        adb.connect_self()
    except Exception:  # noqa: BLE001 - a phone without wireless debugging still boots
        pass


def _unknown(device: str) -> str | None:
    """Return an `error:` string if `device` is not resolvable, else None."""
    try:
        adb.serial(device)
        return None
    except KeyError:
        return f"error: unknown device {device!r}"


def _log_action(device: str, tool: str, detail: str, reason: str) -> None:
    """Append one audit line for a state-changing device action."""
    log = _NIBA_HOME / "logs" / "device-actions.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"{ts}\t{device}\t{tool}\t{detail}\t{reason}\n")


def _snapshot(device: str) -> tuple[str, str]:
    """Dump the FULL (uncapped) package list to $NIBA_HOME/snapshots/ before a
    removal. Returns ``(snapshot_path, snapshot_text)`` so the caller can check
    the snapshot actually captured something before removing anything.
    """
    out = adb.run_uncapped(device, "shell", "pm", "list", "packages", "-f",
                           timeout=30)
    snap = _NIBA_HOME / "snapshots" / f"{device}-{time.time_ns()}.txt"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(out, encoding="utf-8")
    return str(snap), out


def _screencap_bytes(serial: str) -> tuple[bytes | None, str]:
    """`adb -s <serial> exec-out screencap -p` as raw bytes (text mode corrupts
    PNGs). Runs through `proc.run` (own process group, group-killed on timeout,
    stdin closed)."""
    # binary mode: proc.run discards stderr so adb's "* daemon starting" banner
    # can't prepend noise to the PNG.
    argv = ["adb", "-s", serial, "exec-out", "screencap", "-p"]
    rc, data, _ = proc.run(argv, timeout=SCREENCAP_TIMEOUT, binary=True)
    if rc != 0 or not data:
        return None, f"screencap failed: exit {rc}"
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None, f"screencap did not return a PNG: {data[:80]!r}"
    return data, ""


def register() -> None:
    @tools.tool(
        "device_list",
        "List paired devices with reachability, plus this phone ('self').",
        {"type": "object", "properties": {}},
    )
    def device_list():
        scan = _adb_mod._adb("devices", timeout=10)
        online = set()
        for line in scan.splitlines():
            parts = line.split()
            # `<serial>\t<state>` — require the serial as a whole token in the
            # `device` state, so 10.0.0.5:555 doesn't match on :5555.
            if len(parts) >= 2 and parts[1] == "device":
                online.add(parts[0])
        out: dict[str, dict] = {}
        for name, entry in registry.all().items():
            host = entry.get("host", "")
            out[name] = {
                "host": host,
                "last_seen": entry.get("last_seen"),
                "reachable": bool(host) and host in online,
            }
        out["self"] = {"reachable": adb.connect_self()}
        return out

    @tools.tool(
        "device_shell",
        "Run a shell command on a device via adb ('self' = this phone).",
        {"type": "object",
         "properties": {"cmd": {"type": "string"},
                        "device": {"type": "string", "default": "self"}},
         "required": ["cmd"]},
    )
    def device_shell(cmd: str, device: str = "self"):
        return _unknown(device) or adb.run(device, "shell", cmd)

    @tools.tool(
        "device_screencap",
        "Capture a PNG screenshot of a device and attach it to the reply.",
        {"type": "object",
         "properties": {"device": {"type": "string", "default": "self"}}},
    )
    def device_screencap(device: str = "self"):
        err = _unknown(device)
        if err:
            return err
        data, why = _screencap_bytes(adb.serial(device))
        if data is None:
            return f"error: {why}"
        path = _TMP / f"screen-{device}-{time.time_ns()}.png"
        path.write_bytes(data)
        emit_image(str(path), "image/png")
        return "screenshot captured"

    @tools.tool(
        "device_ui_dump",
        "Dump the current on-screen UI hierarchy as XML.",
        {"type": "object",
         "properties": {"device": {"type": "string", "default": "self"}}},
    )
    def device_ui_dump(device: str = "self"):
        return _unknown(device) or adb.run(
            device, "shell",
            "uiautomator dump /sdcard/u.xml && cat /sdcard/u.xml")

    @tools.tool(
        "device_packages",
        "List installed packages ('-3' third-party only by default).",
        {"type": "object",
         "properties": {"flags": {"type": "string", "default": "-3"},
                        "device": {"type": "string", "default": "self"}}},
    )
    def device_packages(flags: str = "-3", device: str = "self"):
        return _unknown(device) or adb.run(
            device, "shell", "pm", "list", "packages", *shlex.split(flags))

    @tools.tool(
        "device_logcat",
        "Fetch recent logcat lines from a device.",
        {"type": "object",
         "properties": {"filter": {"type": "string"},
                        "lines": {"type": "integer", "default": 200},
                        "device": {"type": "string", "default": "self"}}},
    )
    def device_logcat(filter: str | None = None, lines: int = 200,
                      device: str = "self"):
        return _unknown(device) or adb.run(
            device, "logcat", "-d", "-t", str(lines),
            *([filter] if filter else []))

    @tools.tool(
        "device_settings",
        "Read a device setting: `settings get <ns> <key>`.",
        {"type": "object",
         "properties": {"ns": {"type": "string"},
                        "key": {"type": "string"},
                        "device": {"type": "string", "default": "self"}},
         "required": ["ns", "key"]},
    )
    def device_settings(ns: str, key: str, device: str = "self"):
        return _unknown(device) or adb.run(
            device, "shell", "settings", "get", ns, key)

    @tools.tool(
        "device_pair",
        "Pair with a device over adb wireless debugging and register it.",
        {"type": "object",
         "properties": {"name": {"type": "string"},
                        "host": {"type": "string"},
                        "code": {"type": "string"},
                        "notes": {"type": "string", "default": ""}},
         "required": ["name", "host", "code"]},
    )
    def device_pair(name: str, host: str, code: str, notes: str = ""):
        return adb.pair(name, host, code, notes)

    @tools.tool(
        "device_unpair",
        "Forget a paired device (remove it from the registry).",
        {"type": "object",
         "properties": {"name": {"type": "string"}},
         "required": ["name"]},
    )
    def device_unpair(name: str):
        registry.remove(name)
        return f"unpaired {name!r}"

    @tools.tool(
        "device_input",
        "Inject an input event: tap / swipe / text / keyevent.",
        {"type": "object",
         "properties": {"action": {"type": "string",
                                   "enum": ["tap", "swipe", "text", "keyevent"]},
                        "device": {"type": "string", "default": "self"},
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "x2": {"type": "integer"},
                        "y2": {"type": "integer"},
                        "text": {"type": "string"},
                        "key": {"type": "string"}},
         "required": ["action"]},
    )
    def device_input(action, device="self", x=None, y=None, x2=None, y2=None,
                     text=None, key=None):
        err = _unknown(device)
        if err:
            return err
        if action == "tap":
            return adb.run(device, "shell", "input", "tap", str(x), str(y))
        if action == "swipe":
            return adb.run(device, "shell", "input", "swipe",
                           str(x), str(y), str(x2), str(y2))
        if action == "text":
            return adb.run(device, "shell", "input", "text", text)
        if action == "keyevent":
            return adb.run(device, "shell", "input", "keyevent", str(key))
        return f"error: unknown input action {action!r}"

    @tools.tool(
        "device_settings_put",
        "DANGEROUS: write a device setting "
        "(`settings put <ns> <key> <value>`). Requires a reason (audit-logged).",
        {"type": "object",
         "properties": {"ns": {"type": "string"},
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                        "reason": {"type": "string"},
                        "device": {"type": "string", "default": "self"}},
         "required": ["ns", "key", "value", "reason"]},
    )
    def device_settings_put(ns, key, value, reason, device="self"):
        err = _unknown(device)
        if err:
            return err
        _log_action(device, "device_settings_put", f"{ns} {key}={value}", reason)
        return adb.run(device, "shell", "settings", "put", ns, key, value)

    @tools.tool(
        "device_appops",
        "DANGEROUS: set an app-ops mode (`appops set <pkg> <op> <mode>`). "
        "Requires a reason (audit-logged).",
        {"type": "object",
         "properties": {"pkg": {"type": "string"},
                        "op": {"type": "string"},
                        "mode": {"type": "string"},
                        "reason": {"type": "string"},
                        "device": {"type": "string", "default": "self"}},
         "required": ["pkg", "op", "mode", "reason"]},
    )
    def device_appops(pkg, op, mode, reason, device="self"):
        err = _unknown(device)
        if err:
            return err
        _log_action(device, "device_appops", f"{pkg} {op}={mode}", reason)
        return adb.run(device, "shell", "appops", "set", pkg, op, mode)

    @tools.tool(
        "device_uninstall",
        "DANGEROUS: uninstall a package for user 0. Snapshots the package "
        "list first and audit-logs the reason.",
        {"type": "object",
         "properties": {"pkg": {"type": "string"},
                        "reason": {"type": "string"},
                        "device": {"type": "string", "default": "self"}},
         "required": ["pkg", "reason"]},
    )
    def device_uninstall(pkg, reason, device="self"):
        err = _unknown(device)
        if err:
            return err
        snap, snap_out = _snapshot(device)
        if "package:" not in snap_out:
            _log_action(device, "device_uninstall",
                        f"{pkg} (snapshot {snap} — ABORTED: no package list)",
                        reason)
            return (f"error: snapshot failed, not removing {pkg}: "
                    f"{snap_out[:200]}")
        _log_action(device, "device_uninstall", f"{pkg} (snapshot {snap})",
                    reason)
        return adb.run(device, "shell", "pm", "uninstall", "--user", "0", pkg)

    @tools.tool(
        "device_disable",
        "DANGEROUS: disable a package for user 0. Snapshots the package "
        "list first and audit-logs the reason.",
        {"type": "object",
         "properties": {"pkg": {"type": "string"},
                        "reason": {"type": "string"},
                        "device": {"type": "string", "default": "self"}},
         "required": ["pkg", "reason"]},
    )
    def device_disable(pkg, reason, device="self"):
        err = _unknown(device)
        if err:
            return err
        snap, snap_out = _snapshot(device)
        if "package:" not in snap_out:
            _log_action(device, "device_disable",
                        f"{pkg} (snapshot {snap} — ABORTED: no package list)",
                        reason)
            return (f"error: snapshot failed, not removing {pkg}: "
                    f"{snap_out[:200]}")
        _log_action(device, "device_disable", f"{pkg} (snapshot {snap})", reason)
        return adb.run(device, "shell", "pm", "disable-user", "--user", "0", pkg)
