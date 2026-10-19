import sys, subprocess, time
from pathlib import Path
import pytest
from caelza_body import supervisor


class FakeChild:
    def __init__(self, script=None, exits_with=None, heartbeat=False):
        self.script = script
        self.exits_with = exits_with
        self._started = False
        self._exited = False
        self.name = "agent"
        self.log_dir = Path(".")
    def start(self): self._started = True
    @property
    def running(self):
        return self._started and not self._exited and self.exits_with is None
    @property
    def returncode(self):
        return self.exits_with
    def stop(self, timeout=5.0): self._exited = True


@pytest.fixture
def home(tmp_path):
    (tmp_path / "run").mkdir()
    return tmp_path


def make(home, git_repo, **kw):
    alerts = []
    sup = supervisor.Supervisor(
        git_repo, home,
        alert=alerts.append,
        spawn_agent=kw.get("spawn_agent", lambda: FakeChild()),
        spawn_probe=kw.get("spawn_probe", lambda: FakeChild()),
        spawn_sidecar=kw.get("spawn_sidecar", lambda: FakeChild()),
        clock=kw.get("clock", lambda: 0.0),
        sleep=lambda s: None,
    )
    return sup, alerts


def test_tick_starts_children(home, git_repo):
    sup, _ = make(home, git_repo)
    sup.tick()
    assert sup.agent.running
    assert sup.sidecar.running


def test_restart_request_promotes_on_probe_ok(home, git_repo, monkeypatch):
    good = supervisor.current_commit(git_repo)
    supervisor.set_last_good(git_repo, good)
    (git_repo / "a.txt").write_text("change\n")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "c2"], cwd=git_repo, check=True)
    new = supervisor.current_commit(git_repo)
    (home / "run" / "restart-request").write_text(
        '{"reason": "feature", "commit": "%s"}' % new
    )
    monkeypatch.setattr(supervisor, "run_probe", lambda *a, **k: (True, "ok"))
    sup, alerts = make(home, git_repo)
    sup.tick()  # first tick starts the agent
    sup.tick()  # second tick reads + processes the restart-request
    assert supervisor.last_good(git_repo) == new
    assert any("feature" in a for a in alerts)


def test_restart_request_rolls_back_on_probe_fail(home, git_repo, monkeypatch):
    good = supervisor.current_commit(git_repo)
    supervisor.set_last_good(git_repo, good)
    (git_repo / "a.txt").write_text("bad\n")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "bad"], cwd=git_repo, check=True)
    (home / "run" / "restart-request").write_text(
        '{"reason": "oops", "commit": "%s"}' % supervisor.current_commit(git_repo)
    )
    monkeypatch.setattr(supervisor, "run_probe", lambda *a, **k: (False, "ImportError"))
    sup, alerts = make(home, git_repo)
    sup.tick()  # first tick starts the agent
    sup.tick()  # second tick reads + processes the restart-request
    assert supervisor.current_commit(git_repo) == good
    assert any("rolled back" in a.lower() for a in alerts)


def test_agent_crash_loop_triggers_rollback(home, git_repo, monkeypatch):
    good = supervisor.current_commit(git_repo)
    supervisor.set_last_good(git_repo, good)
    t = {"now": 0.0}
    sup, alerts = make(home, git_repo,
                       spawn_agent=lambda: FakeChild(exits_with=1),
                       clock=lambda: t["now"])
    for _ in range(4):
        sup.tick()
        t["now"] += 1.0
    assert any("rolled back" in a.lower() or "crash" in a.lower() for a in alerts)


def test_stale_heartbeat_restarts_agent(home, git_repo, monkeypatch):
    sup, _ = make(home, git_repo)
    sup.tick()  # starts the agent (and sidecar)
    first_agent = sup.agent
    assert first_agent.running
    monkeypatch.setattr(supervisor, "heartbeat_age", lambda *a, **k: 9999.0)
    sup._agent_started_at = -10000.0  # push past the fresh-agent grace window
    sup.tick()
    assert first_agent._exited  # old agent was stopped
    assert sup.agent is not first_agent
    assert sup.agent.running


def test_fresh_agent_not_restarted_within_grace(home, git_repo):
    sup, _ = make(home, git_repo)
    sup.tick()  # starts the agent; no heartbeat file written yet
    agent = sup.agent
    assert not (home / "run" / "heartbeat").exists()
    sup.tick()  # still within the grace window -> must NOT restart
    assert sup.agent is agent
    assert not agent._exited


# --- C2: the terminal `halted` state must be reachable ---------------------

class FlakyChild(FakeChild):
    """Reports running on the first poll after start, dead on every poll after.

    This is the realistic crash shape the reviewer flagged: an agent that
    survives one 2s supervisor tick and then dies. It used to reset the
    `_last_good_looping` latch every other tick, so `_halted` was unreachable.
    """

    def __init__(self):
        super().__init__()
        self._polls = 0

    def start(self):
        super().start()
        self._polls = 0

    @property
    def running(self):
        if not self._started or self._exited:
            return False
        self._polls += 1
        return self._polls <= 1


def test_agent_that_survives_one_tick_still_reaches_halted(home, git_repo):
    supervisor.set_last_good(git_repo, supervisor.current_commit(git_repo))
    t = {"now": 0.0}
    sup, alerts = make(home, git_repo,
                       spawn_agent=lambda: FlakyChild(),
                       clock=lambda: t["now"])

    for _ in range(40):
        sup.tick()
        t["now"] += 1.0
        if sup._halted:
            break

    assert sup._halted is True, "supervisor never latched into the terminal halted state"
    manual = [a for a in alerts if "manual fix needed" in a]
    assert len(manual) == 1, f"expected exactly one manual-fix alert, got {manual}"

    # Once halted the supervisor idles: no more alerts, no more exit-counting.
    alerts_before = list(alerts)
    exits_before = len(sup.crashes._exits)
    agent_before = sup.agent
    for _ in range(5):
        sup.tick()
        t["now"] += 1.0
    assert alerts == alerts_before
    assert len(sup.crashes._exits) == exits_before
    assert sup.agent is agent_before  # no restarts either


def test_successful_promote_clears_the_halt_latch(home, git_repo, monkeypatch):
    """Spec §5.1: the latch is cleared on a successful promote, and only there."""
    supervisor.set_last_good(git_repo, supervisor.current_commit(git_repo))
    (git_repo / "a.txt").write_text("change\n")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "c2"], cwd=git_repo, check=True)
    new = supervisor.current_commit(git_repo)
    monkeypatch.setattr(supervisor, "run_probe", lambda *a, **k: (True, "ok"))

    sup, _ = make(home, git_repo)
    sup.tick()  # start the agent
    sup._last_good_looping = True
    (home / "run" / "restart-request").write_text(
        '{"reason": "feature", "commit": "%s"}' % new
    )
    sup.tick()
    assert sup._last_good_looping is False


def test_sidecar_none_is_tolerated_and_not_respun(home, git_repo):
    """spawn_sidecar returning None (disabled) must not crash or spin-respawn."""
    calls = {"n": 0}
    def spawn_none():
        calls["n"] += 1
        return None
    sup, _ = make(home, git_repo, spawn_sidecar=spawn_none)
    sup.tick(); sup.tick(); sup.tick()
    assert sup.sidecar is None
    assert calls["n"] == 1  # backoff: tried once, then held off (clock is fixed at 0)
