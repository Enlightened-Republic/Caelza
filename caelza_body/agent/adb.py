from __future__ import annotations

import os
import re
from pathlib import Path

from caelza_body.agent import proc
from caelza_body.agent.devices import DeviceRegistry

#: A loopback serial in `adb devices` output that is actually connected
#: (state column == "device", not "offline"/"unauthorized").
_LOOPBACK_ONLINE = re.compile(r"^(127\.0\.0\.1:\d+)\s+device\b", re.M)
#: How many rediscovered candidates connect_self() will try.
_MAX_SCAN_CANDIDATES = 3

#: Niba home dir, set by configure(). Used to locate run/adb-self-port.
_BODY_HOME: Path | None = None

#: Merged-output cap (~8 KB) for a single adb invocation.
CAP = 8000

DEFAULT_SELF_PORT = 5555


def configure(body_home) -> None:
    """Point the module at <body_home> (for run/adb-self-port lookup)."""
    global _BODY_HOME
    _BODY_HOME = Path(body_home)
    _ensure_tmpdir()


def _ensure_tmpdir() -> None:
    """The adb client needs a writable TMPDIR for its server socket + logs.
    Termux:Boot hands the supervisor a minimal env with no TMPDIR, so a
    boot-launched agent's first `adb` call would die with
    `cannot open /tmp/adb.*.log: Permission denied`. Default it to $PREFIX/tmp."""
    if os.environ.get("TMPDIR"):
        return
    prefix = os.environ.get("PREFIX")
    if not prefix:
        return
    tmp = Path(prefix) / "tmp"
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        os.environ["TMPDIR"] = str(tmp)
    except OSError:
        pass


def _self_port() -> int:
    """Self-ADB port: $CAELZA_BODY_HOME/run/adb-self-port if present, else 5555."""
    if _BODY_HOME is not None:
        f = Path(_BODY_HOME) / "run" / "adb-self-port"
        if f.exists():
            try:
                return int(f.read_text().strip())
            except (ValueError, OSError):
                pass
    return DEFAULT_SELF_PORT


def _adb(*args: str, timeout: int, cap: int | None = CAP) -> str:
    """Run one `adb` invocation via `proc.run` (own process group, group-killed
    on timeout, stdin closed); return `f"exit {rc}\\n{merged output}"`, capped.

    A genuinely absent adb is reported cleanly, but only when `proc.run` had to
    fall through to `sh -c` and the shell said the command was missing — a bare
    remote rc==127 (`adb shell <missing-cmd>`) reaches the caller intact.
    """
    argv = ["adb", *[str(a) for a in args]]
    not_found = "exit 127\nadb not found — pkg install android-tools"
    rc, out, via_shell = proc.run(argv, timeout=timeout, cap=cap)
    if rc == -1 and out.startswith("error: timed out"):
        return f"exit -1\nadb timed out after {timeout}s"
    if proc.missing_executable(rc, out, "adb", via_shell):
        return not_found
    return f"exit {rc}\n{out}"


class Adb:
    """Thin wrapper over the `adb` binary, keyed off a DeviceRegistry."""

    def __init__(self, registry: DeviceRegistry, self_serial: str | None = None):
        self.registry = registry
        #: An explicit constructor override always wins.
        self._self_override = self_serial
        #: A port connect_self() rediscovered from `adb devices` when the
        #: recorded one was dead. Kept separate from the override so a fresh
        #: run/adb-self-port (setup.py re-run) still takes precedence.
        self._discovered_serial: str | None = None

    @property
    def self_serial(self) -> str:
        """This phone's adb serial. Constructor override, else a rediscovered
        port, else run/adb-self-port (re-read every access — Android reassigns
        the wireless-debugging port on every reboot / toggle), else the default."""
        return (self._self_override or self._discovered_serial
                or f"127.0.0.1:{_self_port()}")

    def serial(self, device: str) -> str:
        """Resolve a device name to an adb serial. Raises KeyError if unknown."""
        if device == "self":
            return self.self_serial
        entry = self.registry.get(device)
        if entry is None:
            raise KeyError(device)
        return entry["host"]

    @staticmethod
    def _lost_device(out: str) -> bool:
        low = out.lower()
        return ("not found" in low or "device offline" in low
                or "no devices" in low) and "error" in low

    def run(self, device: str, *args: str, timeout: int = 30, cap=CAP) -> str:
        """`adb -s <serial> <args...>`; merged output, capped, `exit N` prefix.

        The adb server's `connect` state is lost whenever the server restarts
        (a crash-loop, a stray `adb kill-server`, a reboot). If a call comes
        back "device not found", reconnect once and retry."""
        serial = self.serial(device)
        out = _adb("-s", serial, *args, timeout=timeout, cap=cap)
        if self._lost_device(out) and self._reconnect(device):
            out = _adb("-s", self.serial(device), *args, timeout=timeout, cap=cap)
        return out

    def _reconnect(self, device: str) -> bool:
        if device == "self":
            return self.connect_self()
        entry = self.registry.get(device)
        return bool(entry) and self._connected(
            _adb("connect", entry["host"], timeout=30))

    def run_uncapped(self, device: str, *args: str, timeout: int = 30) -> str:
        """Like `run`, but with no output cap — for a pre-removal snapshot that
        must hold the whole package list (250-400 entries on a real phone)."""
        return self.run(device, *args, timeout=timeout, cap=None)

    @staticmethod
    def _connected(out: str) -> bool:
        low = out.lower()
        return "connected" in low and "cannot" not in low and "unable" not in low

    def connect_self(self) -> bool:
        """`adb connect <self_serial>`; True on connected/already connected.

        If the recorded/default port is dead, adopt the first *online*
        `127.0.0.1:<port>` from `adb devices` (bounded to a few candidates) for
        the rest of the process — but a later fresh run/adb-self-port still wins.
        """
        if self._self_override:
            return self._connected(_adb("connect", self._self_override, timeout=30))

        file_serial = f"127.0.0.1:{_self_port()}"
        tried: set[str] = set()
        # File port first when it differs from a past discovery — a setup.py
        # re-run must be able to supersede a stale adopted port.
        order = [file_serial, self._discovered_serial] \
            if file_serial != self._discovered_serial \
            else [self._discovered_serial]
        for serial in order:
            if not serial or serial in tried:
                continue
            tried.add(serial)
            if self._connected(_adb("connect", serial, timeout=30)):
                if serial == file_serial:
                    self._discovered_serial = None
                return True

        scan = _adb("devices", timeout=10)
        for cand in _LOOPBACK_ONLINE.findall(scan)[:_MAX_SCAN_CANDIDATES]:
            if cand in tried:
                continue
            tried.add(cand)
            if self._connected(_adb("connect", cand, timeout=30)):
                self._discovered_serial = cand
                return True
        return False

    def pair(self, name: str, host: str, code: str, notes: str = "") -> str:
        """`adb pair <host> <code>`; on success connect + register the device."""
        out = _adb("pair", host, code, timeout=30)
        if "success" in out.lower():
            _adb("connect", host, timeout=30)
            self.registry.add(name, host, notes)
            return f"paired '{name}' at {host} and registered"
        return f"pair failed for {host}:\n{out}"
