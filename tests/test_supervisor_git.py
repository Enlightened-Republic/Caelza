import subprocess
import pytest
from niba import supervisor


def test_current_commit_matches_git(git_repo):
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=git_repo, capture_output=True, text=True
    ).stdout.strip()
    assert supervisor.current_commit(git_repo) == expected


def test_last_good_none_then_set(git_repo):
    assert supervisor.last_good(git_repo) is None
    sha = supervisor.current_commit(git_repo)
    supervisor.set_last_good(git_repo, sha)
    assert supervisor.last_good(git_repo) == sha


def test_set_last_good_is_movable(git_repo):
    first = supervisor.current_commit(git_repo)
    supervisor.set_last_good(git_repo, first)
    (git_repo / "b.txt").write_text("two\n")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "second"], cwd=git_repo, check=True)
    second = supervisor.current_commit(git_repo)
    supervisor.set_last_good(git_repo, second)
    assert supervisor.last_good(git_repo) == second


def test_reset_hard_discards_working_changes(git_repo):
    good = supervisor.current_commit(git_repo)
    (git_repo / "a.txt").write_text("broken\n")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "bad"], cwd=git_repo, check=True)
    supervisor.reset_hard(git_repo, good)
    assert (git_repo / "a.txt").read_text() == "one\n"
    assert supervisor.current_commit(git_repo) == good


def test_commit_exists(git_repo):
    assert supervisor.commit_exists(git_repo, supervisor.current_commit(git_repo))
    assert not supervisor.commit_exists(git_repo, "0" * 40)
