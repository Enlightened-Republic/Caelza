"""The Runtime guard as two Body tools (Forge, vision §3.5).

The guard itself is `caelza_body/runtime_guard.py` and the `caelza-body
runtime` CLI; these tools let the agent (and the `forge-release` procedure)
read it and start it:

- ``runtime_status``  what is installed, what is current and last-good, whether
                      an update is running, and the tail of its log (read-only)
- ``runtime_update``  start `caelza-body runtime update [--tag]` detached: the
                      guard fetches the release, verifies, probes, installs and
                      asks the supervisor to restart the Runtime. Destructive
                      (the Runtime restarts), always behind the owner's gate.

The update runs as its own process so the tool call returns at once (a
download plus a probe can take minutes, and the Runtime that made the call is
the one that restarts at the end). Progress is in ``runtime_status``.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from caelza_body import runtime_guard
from caelza_body.agent import tools

_BODY_HOME: Path | None = None
UPDATE_LOG = "logs/runtime-update.log"
UPDATE_PID = "run/runtime-update.pid"
LOG_TAIL = 15


def configure(body_home) -> None:
    global _BODY_HOME
    _BODY_HOME = Path(body_home)


def _pid_file() -> Path:
    return _BODY_HOME / UPDATE_PID


def update_running() -> int | None:
    """The pid of a `runtime update` still running, else None (a stale pid
    file is removed)."""
    f = _pid_file()
    try:
        pid = int(f.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        f.unlink(missing_ok=True)
        return None
    except PermissionError:
        return pid
    return pid


def _log_tail(n: int = LOG_TAIL) -> list[str]:
    log = _BODY_HOME / UPDATE_LOG
    try:
        return log.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def _audit(tool: str, detail: str, reason: str) -> None:
    log = _BODY_HOME / "logs" / "device-actions.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')}\tself\t{tool}\t{detail}\t{reason}\n")


def register() -> None:
    @tools.tool(
        "runtime_status",
        "The Runtime binary under the supervisor's guard: the installed versions, "
        "which is current and which is last-good, the binary the supervisor runs, "
        "a pending restart request, whether a `runtime update` is running right now "
        "and the tail of its log. Read-only.",
        {"type": "object", "properties": {}},
    )
    def runtime_status():
        out = runtime_guard.status(_BODY_HOME)
        out["update_running"] = update_running()
        out["update_log"] = _log_tail()
        out["target"] = runtime_guard.default_target()
        return out

    @tools.tool(
        "runtime_update",
        "Start the guard's update of the Runtime binary, detached: `caelza-body "
        "runtime update [--tag <tag>]` fetches the release for this machine (the "
        "latest, or `tag`), verifies its checksum, probes the new binary on a copy "
        "of the config, installs it and asks the supervisor to restart the Runtime "
        "on it; a binary that does not hold is discarded and the running one stays. "
        "The Runtime that calls this restarts a few minutes later if the probe "
        "passes, so say so to the owner first. `reason` is required and audited. "
        "Follow progress with runtime_status.",
        {"type": "object",
         "properties": {"tag": {"type": "string", "default": "",
                                "description": "a release tag such as v0.1.0; empty means the latest release"},
                        "reason": {"type": "string",
                                   "description": "why the Runtime is being updated (the release, who asked)"}},
         "required": ["reason"]},
    )
    def runtime_update(reason: str, tag: str = ""):
        reason = (reason or "").strip()
        if not reason:
            return "error: a reason is required (which release, who asked)"
        tag = (tag or "").strip()
        running = update_running()
        if running:
            return f"error: a runtime update is already running (pid {running}); see runtime_status"
        if _BODY_HOME is None:
            return "error: the Body has no state dir"
        log = _BODY_HOME / UPDATE_LOG
        log.parent.mkdir(parents=True, exist_ok=True)
        _pid_file().parent.mkdir(parents=True, exist_ok=True)
        argv = [sys.executable, "-m", "caelza_body.mcp_server", "runtime", "update", "--home", str(_BODY_HOME)]
        if tag:
            argv += ["--tag", tag]
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"\n== {time.strftime('%Y-%m-%dT%H:%M:%S%z')} runtime update {tag or 'latest'}: {reason}\n")
            fh.flush()
            proc = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    cwd=str(_BODY_HOME), start_new_session=True)
        _pid_file().write_text(f"{proc.pid}\n")
        _audit("runtime_update", f"{tag or 'latest'} (pid {proc.pid})", reason)
        return {
            "started": True,
            "pid": proc.pid,
            "tag": tag or "latest",
            "target": runtime_guard.default_target(),
            "log": str(log),
            "current": runtime_guard.current_version(_BODY_HOME),
            "then": ("the guard downloads, verifies and probes the release; if it holds, the supervisor "
                     "restarts the Runtime on it within a minute, which ends this Runtime's conversations. "
                     "runtime_status shows progress and the result; a failed probe leaves everything as it was."),
        }
