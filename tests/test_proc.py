"""C2 + I6: the one hardened subprocess runner."""
import sys
import time

import pytest

from niba.agent import proc


def test_exit_code_and_output_are_returned():
    rc, out, via_shell = proc.run(["sh", "-c", "echo hi; exit 3"], timeout=5)
    assert rc == 3
    assert "hi" in out


def test_backgrounded_child_does_not_hold_the_pipe_open():
    """The regression test for the whole item: a backgrounded grandchild must
    not keep `run()` blocked past the timeout."""
    start = time.monotonic()
    rc, out, _ = proc.run(["sh", "-c", "sleep 10 & echo started"], timeout=2)
    elapsed = time.monotonic() - start
    assert elapsed < 6, f"run() blocked {elapsed:.1f}s on a backgrounded child"
    assert rc == -1
    assert "timed out" in out


def test_str_form_runs_via_shell():
    rc, out, via_shell = proc.run("echo viashell", timeout=5)
    assert rc == 0
    assert "viashell" in out
    assert via_shell is True


def test_missing_binary_does_not_raise():
    rc, out, via_shell = proc.run(["definitely-not-a-real-binary-xyz"], timeout=5)
    assert rc == 127
    assert via_shell is True
    assert proc.missing_executable(rc, out, "definitely-not-a-real-binary-xyz", via_shell)


def test_binary_mode_returns_raw_bytes():
    # via python, not `printf '\xNN'` — that's a bashism dash doesn't honour
    rc, out, _ = proc.run(
        [sys.executable, "-c", r"import sys; sys.stdout.buffer.write(b'\x89PNG')"],
        timeout=5, binary=True)
    assert rc == 0
    assert out == b"\x89PNG"


def test_text_output_is_capped():
    rc, out, _ = proc.run(["sh", "-c", "yes x | head -c 20000"], timeout=10)
    assert len(out) < 8100
    assert out.endswith("…(truncated)")


def test_cap_none_does_not_truncate():
    rc, out, _ = proc.run(["sh", "-c", "yes x | head -c 20000"], timeout=10, cap=None)
    assert len(out) >= 20000


def test_cap_tail_keeps_the_end():
    rc, out, _ = proc.run(
        ["sh", "-c", "printf 'HEAD'; yes x | head -c 20000; printf 'TAILMARK'"],
        timeout=10, cap=8000, cap_tail=True)
    assert out.endswith("TAILMARK")
    assert "HEAD" not in out
    assert out.startswith("…(truncated)")


def test_binary_mode_discards_stderr_noise():
    """C1: adb writes its 'daemon starting' banner to stderr; in binary mode it
    must not get prepended to the payload (a PNG)."""
    rc, out, _ = proc.run(
        [sys.executable, "-c",
         r"import sys; sys.stderr.write('daemon not running'); sys.stderr.flush(); "
         r"sys.stdout.buffer.write(b'\x89PNG\r\n\x1a\n body')"],
        timeout=5, binary=True)
    assert rc == 0
    assert out.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"daemon" not in out


def test_missing_executable_ignores_direct_exec_path():
    assert proc.missing_executable(127, "adb: not found", "adb", via_shell=False) is False


def test_missing_executable_needs_both_rc_127_and_the_message():
    # rc 0 with a coincidental "adb: not found" in a device line -> not masked
    assert proc.missing_executable(0, "foo adb: not found bar", "adb", via_shell=True) is False
    # rc 127 from a real `adb shell nosuchcmd` -> different message, not masked
    out = "/system/bin/sh: nosuchcmd: inaccessible or not found"
    assert proc.missing_executable(127, out, "adb", via_shell=True) is False
    # rc 127 AND the shell's not-found message -> masked
    assert proc.missing_executable(127, "sh: 1: adb: not found", "adb", via_shell=True) is True
