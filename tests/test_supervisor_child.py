import sys
import time
from pathlib import Path
from niba.supervisor import Child


def _child(tmp_path, name, code):
    script = tmp_path / f"{name}.py"
    script.write_text(code)
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    return Child(name, [sys.executable, str(script)], cwd=tmp_path, log_dir=logs)


def test_child_runs_and_exits_zero(tmp_path):
    c = _child(tmp_path, "ok", "print('hello')")
    c.start()
    for _ in range(50):
        if not c.running:
            break
        time.sleep(0.1)
    assert c.returncode == 0
    assert "hello" in (tmp_path / "logs" / "ok.log").read_text()


def test_child_nonzero_exit_is_visible(tmp_path):
    c = _child(tmp_path, "bad", "import sys; sys.exit(3)")
    c.start()
    for _ in range(50):
        if not c.running:
            break
        time.sleep(0.1)
    assert c.returncode == 3


def test_stop_terminates_a_hung_child(tmp_path):
    c = _child(tmp_path, "hang", "import time\nwhile True: time.sleep(1)")
    c.start()
    assert c.running
    c.stop(timeout=2.0)
    assert not c.running


def test_log_rotation_keeps_previous(tmp_path):
    c1 = _child(tmp_path, "svc", "print('run one')")
    c1.start(); time.sleep(0.3)
    c1.stop()
    c2 = _child(tmp_path, "svc", "print('run two')")
    c2.start(); time.sleep(0.3)
    logs = tmp_path / "logs"
    assert "run two" in (logs / "svc.log").read_text()
    assert "run one" in (logs / "svc.log.prev").read_text()
