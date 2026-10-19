import pytest
from caelza_body.agent import tools
from caelza_body.agent.tools import shell


@pytest.fixture(autouse=True)
def _clean():
    tools.reset(); shell.register(); yield; tools.reset()


def test_runs_and_reports_exit_and_output():
    out = tools.dispatch("shell_run", {"cmd": "echo hi; exit 3"})
    assert "exit 3" in out and "hi" in out


def test_timeout():
    import sys
    cmd = f'"{sys.executable}" -c "import time; time.sleep(5)"'
    out = tools.dispatch("shell_run", {"cmd": cmd, "timeout": 1})
    assert out.startswith("error: timed out")


def test_output_is_capped():
    out = tools.dispatch("shell_run", {"cmd": "yes x | head -c 20000"})
    assert len(out) < 8200


def test_cap_keeps_the_tail_not_the_head():
    """Build errors / pytest summaries / log tails live at the END of the output;
    shell_run must keep those, not the first 8 KB of setup noise."""
    cmd = 'for i in $(seq 1 5000); do echo padding line $i; done; echo FINAL_MARKER_LINE'
    out = tools.dispatch("shell_run", {"cmd": cmd})
    assert "FINAL_MARKER_LINE" in out
    assert "…(truncated)" in out
    assert "padding line 1 " not in out  # the head was dropped
