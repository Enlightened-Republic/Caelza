import json
import sys
import subprocess
from pathlib import Path
import pytest
from caelza_body import supervisor


@pytest.fixture
def body_home(tmp_path):
    h = tmp_path / "home"
    (h / "run").mkdir(parents=True)
    return h


def _probe_child(tmp_path, body_home, body):
    script = tmp_path / "probe.py"
    script.write_text(body)
    logs = tmp_path / "logs"; logs.mkdir(exist_ok=True)
    return lambda: supervisor.Child(
        "probe", [sys.executable, str(script)], cwd=tmp_path, log_dir=logs,
        env={"CAELZA_BODY_HOME": str(body_home)},
    )


def test_restart_request_roundtrip(body_home):
    assert supervisor.read_restart_request(body_home) is None
    (body_home / "run" / "restart-request").write_text(
        json.dumps({"reason": "x", "commit": "abc"})
    )
    assert supervisor.read_restart_request(body_home)["reason"] == "x"
    supervisor.clear_restart_request(body_home)
    assert supervisor.read_restart_request(body_home) is None


def test_probe_ok(tmp_path, body_home):
    spawn = _probe_child(
        tmp_path, body_home,
        "import os\n"
        "open(os.path.join(os.environ['CAELZA_BODY_HOME'], 'run', 'probe-ok'), 'w').close()\n",
    )
    ok, _ = supervisor.run_probe(tmp_path, body_home, spawn, timeout=10)
    assert ok is True


def test_probe_fails_on_nonzero_exit(tmp_path, body_home):
    spawn = _probe_child(tmp_path, body_home, "import sys; sys.exit(1)")
    ok, detail = supervisor.run_probe(tmp_path, body_home, spawn, timeout=10)
    assert ok is False


def test_probe_fails_on_timeout(tmp_path, body_home):
    spawn = _probe_child(tmp_path, body_home, "import time\nwhile True: time.sleep(1)")
    ok, _ = supervisor.run_probe(tmp_path, body_home, spawn, timeout=1)
    assert ok is False


def test_rollback_restores_last_good(git_repo, body_home):
    good = supervisor.current_commit(git_repo)
    supervisor.set_last_good(git_repo, good)
    (git_repo / "a.txt").write_text("bad\n")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "bad"], cwd=git_repo, check=True)
    diff = supervisor.rollback(git_repo, body_home, "boom")
    assert "bad" in diff
    assert (git_repo / "a.txt").read_text() == "one\n"


# --- I1: reset --hard leaves untracked files behind ------------------------

def test_rollback_removes_untracked_files(git_repo, body_home):
    """self_write_file never commits, so a *new* file survives reset --hard.

    `sitecustomize.py` and a root `conftest.py` are both auto-imported by
    Python, so surviving a rollback makes the repo structurally unrecoverable.
    """
    good = supervisor.current_commit(git_repo)
    supervisor.set_last_good(git_repo, good)
    (git_repo / "sitecustomize.py").write_text("raise SystemExit('poison')\n")
    (git_repo / "newdir").mkdir()
    (git_repo / "newdir" / "conftest.py").write_text("boom\n")

    supervisor.rollback(git_repo, body_home, "boom")

    assert not (git_repo / "sitecustomize.py").exists()
    assert not (git_repo / "newdir").exists()
    assert supervisor.current_commit(git_repo) == good


def test_rollback_keeps_gitignored_files(git_repo, body_home):
    """`git clean -fd` (no -x) must not wipe ignored dev state (the sdd workspace)."""
    (git_repo / ".gitignore").write_text("keepme/\n")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "ignore"], cwd=git_repo, check=True)
    good = supervisor.current_commit(git_repo)
    supervisor.set_last_good(git_repo, good)
    (git_repo / "keepme").mkdir()
    (git_repo / "keepme" / "notes.md").write_text("valuable\n")

    supervisor.rollback(git_repo, body_home, "boom")

    assert (git_repo / "keepme" / "notes.md").read_text() == "valuable\n"


# --- I2: alerts must not carry the bot token to Telegram -------------------

def test_redact_secrets_replaces_every_secret():
    out = supervisor.redact_secrets("url /bot123456:ABCDEF/ and key ORKEY123456",
                                    ["123456:ABCDEF", "ORKEY123456"])
    assert "123456:ABCDEF" not in out
    assert "ORKEY123456" not in out
    assert out.count("<redacted>") == 2


def test_redact_secrets_ignores_empty_and_short_values():
    assert supervisor.redact_secrets("abc", ["", None, "ab"]) == "abc"


def test_alert_scrubs_the_token_before_sending():
    """The probe tail (and the git diff) flow straight into alert()."""
    token = "123456:AAHtokenvalue"
    sent = []
    alert = supervisor.build_alert(
        chat_id=42, token=token, secrets=[token, "OR-KEY-123456"],
        post=lambda url, payload: sent.append((url, payload)),
    )
    alert(f"probe failed: HTTPStatusError: ... for url "
          f"'https://api.telegram.org/bot{token}/getMe' key=OR-KEY-123456")
    (url, payload) = sent[0]
    assert token not in payload["text"]
    assert "OR-KEY-123456" not in payload["text"]
    assert "<redacted>" in payload["text"]
    assert payload["chat_id"] == 42
    assert url == f"https://api.telegram.org/bot{token}/sendMessage"


def test_alert_scrubs_before_truncating_to_4000():
    token = "123456:AAHtokenvalue"
    sent = []
    alert = supervisor.build_alert(
        chat_id=1, token=token, secrets=[token],
        post=lambda url, payload: sent.append(payload),
    )
    alert("x" * 3995 + token + "y" * 500)
    assert token not in sent[0]["text"]
    assert len(sent[0]["text"]) <= 4000


def test_alert_swallows_transport_errors():
    def boom(url, payload):
        raise RuntimeError("network down")
    supervisor.build_alert(chat_id=1, token="t", secrets=[], post=boom)("hi")
