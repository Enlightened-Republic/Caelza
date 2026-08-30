import subprocess
import pytest
from niba.agent import tools
from niba.agent.tools import selfmod


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=r, check=True)
    (r / "niba").mkdir()
    (r / "niba" / "supervisor.py").write_text("# immutable\n")
    (r / "niba" / "agent").mkdir()
    (r / "niba" / "agent" / "loop.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=r, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=r, check=True)
    home = tmp_path / "home"; (home / "run").mkdir(parents=True)
    tools.reset()
    selfmod.register()
    selfmod.configure(r, home)
    return r, home


def test_read_and_write(repo):
    r, _ = repo
    assert "x = 1" in tools.dispatch("self_read_file", {"path": "niba/agent/loop.py"})
    tools.dispatch("self_write_file", {"path": "niba/agent/loop.py", "content": "x = 2\n"})
    assert (r / "niba" / "agent" / "loop.py").read_text() == "x = 2\n"


def test_cannot_touch_supervisor(repo):
    out = tools.dispatch("self_write_file", {"path": "niba/supervisor.py", "content": "evil"})
    assert out.startswith("error: PermissionError")


def test_cannot_touch_supervisor_uppercase(repo):
    out = tools.dispatch("self_write_file", {"path": "niba/SUPERVISOR.py", "content": "evil"})
    assert out.startswith("error: PermissionError")


def test_cannot_escape_repo(repo):
    out = tools.dispatch("self_read_file", {"path": "../../etc/hosts"})
    assert out.startswith("error: PermissionError")


def test_commit_then_request_restart(repo):
    r, home = repo
    tools.dispatch("self_write_file", {"path": "niba/agent/loop.py", "content": "x = 3\n"})
    sha = tools.dispatch("self_commit", {"message": "bump x"})
    assert len(sha) >= 7
    tools.dispatch("self_request_restart", {"reason": "bump x"})
    import json
    req = json.loads((home / "run" / "restart-request").read_text())
    assert req["reason"] == "bump x"
    assert len(req["commit"]) == 40


def test_configure_sets_a_repo_identity_when_missing(tmp_path):
    """A freshly-deployed phone repo has no git identity; configure() must add
    one so self_commit doesn't abort."""
    r = tmp_path / "bare"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    (r / "niba").mkdir()
    (r / "f.txt").write_text("hi\n")
    home = tmp_path / "h"; (home / "run").mkdir(parents=True)
    selfmod.configure(r, home)
    name = subprocess.run(["git", "config", "user.name"], cwd=r,
                          capture_output=True, text=True).stdout.strip()
    email = subprocess.run(["git", "config", "user.email"], cwd=r,
                           capture_output=True, text=True).stdout.strip()
    assert name == "Niba" and "@" in email


def test_configure_does_not_override_existing_identity(tmp_path):
    r = tmp_path / "named"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.name", "Someone Else"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.email", "x@y"], cwd=r, check=True)
    home = tmp_path / "h"; (home / "run").mkdir(parents=True)
    selfmod.configure(r, home)
    name = subprocess.run(["git", "config", "user.name"], cwd=r,
                          capture_output=True, text=True).stdout.strip()
    assert name == "Someone Else"
