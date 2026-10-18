"""One hardened subprocess runner shared by every tool that shells out.

`subprocess.run(capture_output=True, timeout=…)` does NOT kill backgrounded
grandchildren, and its post-timeout `communicate()` blocks on the inherited
stdout pipe until every writer closes it. On the phone a model doing
`tailscaled &` / starting `sshd` would wedge the Telegram poll thread forever
while the heartbeat daemon keeps beating — so the supervisor never restarts or
rolls back. `run()` here runs the command in its own process group and, on
timeout, SIGKILLs the whole group so nothing can hold the pipe open.
"""
from __future__ import annotations

import os
import shlex
import signal
import subprocess

DEFAULT_CAP = 8000

#: Grace window for the best-effort second read after a timeout kill.
_KILL_GRACE = 3


def _first_token(argv) -> str:
    if isinstance(argv, list):
        return str(argv[0]) if argv else ""
    try:
        parts = shlex.split(argv)
    except ValueError:
        parts = argv.split()
    return parts[0] if parts else ""


def _kill_group(p) -> None:
    """SIGKILL the whole process group (POSIX) or just the process (Windows)."""
    if hasattr(os, "killpg") and hasattr(os, "getpgid"):
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
    else:  # pragma: no cover - Windows dev box
        try:
            p.kill()
        except OSError:
            pass


def missing_executable(rc: int, out, name: str, via_shell: bool) -> bool:
    """Heuristic: did the command fail because `name` itself isn't installed?

    Only meaningful on the `sh -c` fallback path — a direct exec of a missing
    binary raises OSError inside `run()` and never reaches a caller as a normal
    result, and a bare `rc == 127` from a real `adb shell <missing-cmd>` is a
    legitimate remote result that must pass through untouched.
    """
    if not via_shell or rc != 127:
        return False
    low = (out or "")
    if isinstance(low, bytes):
        low = low.decode("utf-8", "replace")
    low = low.lower()
    name = name.lower()
    # `sh -c "<name> …"` when <name> isn't on PATH: exits 127 AND prints
    # "<name>: not found" / "<name>: command not found". Both conditions are
    # required — a real `adb shell <missing-cmd>` also exits 127 (different
    # message), and a device line that merely contains "adb: not found" with
    # rc 0 must pass through.
    return (f"{name}: not found" in low
            or f"{name}: command not found" in low)


def run(argv, *, timeout: int, cap: int | None = DEFAULT_CAP, binary: bool = False,
        cap_tail: bool = False):
    """Run a command as its own process group; SIGKILL the group on timeout.

    argv: list[str] (exec'd directly — the Termux path) OR str (run via `sh -c`).
    Returns ``(returncode: int, output, via_shell: bool)``. `output` is text
    unless `binary=True` (then bytes, uncapped). On timeout returns
    ``(-1, "error: timed out after {timeout}s"/b"", via_shell)``. On a genuinely
    missing executable returns ``(127, "<name>: not found …"/b"", True)``.
    In text mode stderr is merged into stdout; in binary mode stderr is
    discarded so it can't prepend noise (e.g. adb's "daemon starting" banner)
    to the payload. `cap` (text mode only): output trimmed to `cap` chars —
    from the head, or from the tail when `cap_tail` (shell/log output puts the
    useful part last). stdin is always /dev/null. Never raises for command
    failure; only for truly unexpected errors.
    """
    as_list = argv if isinstance(argv, list) else None
    popen_kw = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL if binary else subprocess.STDOUT,
        start_new_session=True,  # POSIX: own process group. Windows: ignored.
        text=(not binary),
    )

    via_shell = False
    p = None
    if as_list is not None:
        try:
            p = subprocess.Popen(as_list, **popen_kw)
        except OSError:
            # dev box can't bare-exec a `#!/bin/sh` fake, or the binary is
            # missing — retry through a shell.
            p = None
    if p is None:
        via_shell = True
        shell_cmd = (argv if isinstance(argv, str)
                     else shlex.join(str(a) for a in as_list))
        try:
            p = subprocess.Popen(["sh", "-c", shell_cmd], **popen_kw)
        except OSError:
            name = _first_token(argv)
            if binary:
                return (127, b"", True)
            return (127, f"{name}: not found — is it installed?", True)

    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(p)
        try:
            out, _ = p.communicate(timeout=_KILL_GRACE)
        except subprocess.TimeoutExpired:
            out = b"" if binary else ""
        if binary:
            return (-1, b"", via_shell)
        return (-1, f"error: timed out after {timeout}s", via_shell)

    rc = p.returncode
    if binary:
        return (rc, out or b"", via_shell)
    out = out or ""
    if cap is not None and len(out) > cap:
        out = ("…(truncated)\n" + out[-cap:]) if cap_tail else (out[:cap] + "\n…(truncated)")
    return (rc, out, via_shell)
