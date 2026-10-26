"""Niba supervisor. IMMUTABLE — the agent must never edit this file.

Stdlib only. Owns the git repo, supervises the agent child, and guarantees
recovery to the last known-good commit. Since M6 it also runs the Runtime
binary (`caelza daemon`) from `~/.caelza-body/runtime/current` and rolls it
back to `last-good` on a crash loop (`caelza_body/runtime_guard.py`, also
immutable, does the fetching, probing and swapping on request).
"""
from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import TextIO

from caelza_body import runtime_guard

LAST_GOOD_TAG = "niba-last-good"


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def current_commit(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD")


def commit_exists(repo: Path, sha: str) -> bool:
    try:
        git(repo, "cat-file", "-e", f"{sha}^{{commit}}")
        return True
    except subprocess.CalledProcessError:
        return False


def last_good(repo: Path) -> str | None:
    try:
        return git(repo, "rev-list", "-n", "1", LAST_GOOD_TAG)
    except subprocess.CalledProcessError:
        return None


def set_last_good(repo: Path, sha: str) -> None:
    git(repo, "tag", "-f", LAST_GOOD_TAG, sha)


def reset_hard(repo: Path, sha: str) -> None:
    git(repo, "reset", "--hard", sha)


class Child:
    """Supervisor for a child process with log rotation and graceful shutdown."""

    def __init__(
        self, name: str, argv: list[str], cwd: Path, log_dir: Path, env: dict | None = None
    ) -> None:
        """Initialize a child process supervisor.

        Args:
            name: Child process name (used for log file).
            argv: Command and arguments to execute.
            cwd: Working directory for the subprocess.
            log_dir: Directory to write logs to.
            env: Optional environment variables to merge with parent's environ.
        """
        self.name = name
        self.argv = argv
        self.cwd = Path(cwd)
        self.log_dir = Path(log_dir)
        self.env = env
        self._proc: subprocess.Popen | None = None
        self._log: TextIO | None = None

    def start(self) -> None:
        """Spawn the subprocess with stdout+stderr logged to log_dir/<name>.log.

        Rotates any existing log to <name>.log.prev. If this Child was previously
        started, reaps the old process and closes its log file.
        """
        # Reap and close any existing process and log
        if self._proc is not None:
            if self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait()
            self._proc = None
        if self._log is not None:
            self._log.close()
            self._log = None

        self.log_dir.mkdir(parents=True, exist_ok=True)
        cur = self.log_dir / f"{self.name}.log"
        if cur.exists():
            cur.replace(self.log_dir / f"{self.name}.log.prev")
        self._log = open(cur, "w", buffering=1)
        env = {**os.environ, **(self.env or {})}
        self._proc = subprocess.Popen(
            self.argv, cwd=self.cwd, stdout=self._log,
            stderr=subprocess.STDOUT, env=env, start_new_session=True,
        )

    @property
    def running(self) -> bool:
        """Check if the child process is currently running."""
        return self._proc is not None and self._proc.poll() is None

    @property
    def returncode(self) -> int | None:
        """Get the exit code of the child process, or None if still running."""
        return None if self._proc is None else self._proc.poll()

    @property
    def pid(self) -> int | None:
        """Get the process ID of the child process, or None if not started."""
        return None if self._proc is None else self._proc.pid

    def stop(self, timeout: float = 5.0) -> None:
        """Gracefully terminate the child process.

        Sends SIGTERM (or terminate on Windows), waits for the timeout, then
        escalates to SIGKILL (or kill on Windows) if still running.
        Closes the log file when done.
        """
        # Always close the log file, even if process has already exited
        if self._log is not None:
            self._log.close()
            self._log = None

        if self._proc is None or self._proc.poll() is not None:
            return
        # Cross-platform stop: POSIX uses process groups, Windows uses terminate/kill
        if hasattr(os, "getpgid"):
            # POSIX: use process group with SIGTERM then SIGKILL
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except (ProcessLookupError, AttributeError):
                pass
            try:
                self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
                except (ProcessLookupError, AttributeError):
                    pass
                self._proc.wait(timeout=timeout)
        else:
            # Windows: use terminate/kill
            self._proc.terminate()
            try:
                self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=timeout)


HEARTBEAT_MAX_AGE = 60.0
CRASH_LOOP_N = 3
CRASH_LOOP_WINDOW = 300.0
PROBE_TIMEOUT = 60.0


class CrashLoop:
    def __init__(self, n=CRASH_LOOP_N, window=CRASH_LOOP_WINDOW):
        self.n = n
        self.window = window
        self._exits: list[float] = []

    def record_exit(self, now):
        self._exits.append(now)

    def tripped(self, now):
        recent = [t for t in self._exits if now - t <= self.window]
        return len(recent) >= self.n

    def reset(self):
        self._exits.clear()


def heartbeat_age(body_home: Path, now: float) -> float:
    hb = Path(body_home) / "run" / "heartbeat"
    if not hb.exists():
        return float("inf")
    return now - hb.stat().st_mtime


import json
import time

RUN = "run"


def _run_dir(body_home: Path) -> Path:
    d = Path(body_home) / RUN
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_restart_request(body_home: Path):
    f = _run_dir(body_home) / "restart-request"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text())
        if isinstance(data, dict) and "reason" in data and "commit" in data:
            return data
    except json.JSONDecodeError:
        pass
    return None


def clear_restart_request(body_home: Path):
    (_run_dir(body_home) / "restart-request").unlink(missing_ok=True)


def run_probe(repo, body_home, spawn_probe, timeout=PROBE_TIMEOUT):
    ok_marker = _run_dir(body_home) / "probe-ok"
    ok_marker.unlink(missing_ok=True)
    child = spawn_probe()
    child.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not child.running:
            break
        time.sleep(0.2)
    if child.running:
        child.stop()
        return False, f"probe timed out\n{_log_tail(child)}"
    if child.returncode != 0:
        return False, _log_tail(child)
    if not ok_marker.exists():
        return False, f"probe exited 0 but wrote no probe-ok marker\n{_log_tail(child)}"
    return True, "ok"


def _log_tail(child: "Child", n: int = 40) -> str:
    log = child.log_dir / f"{child.name}.log"
    if not log.exists():
        return ""
    return "\n".join(log.read_text().splitlines()[-n:])


REDACTED = "<redacted>"


def redact_secrets(text: str, secrets) -> str:
    """Strip secret values out of alert text. Stdlib-only twin of agent.Redactor.

    The probe tail and the git diff both flow into `alert()`, and httpx error
    strings carry the full request URL — including `/bot<token>/`.
    """
    for s in secrets:
        if s and len(s) >= 6:
            text = text.replace(s, REDACTED)
    return text


def build_alert(chat_id, token, secrets, post=None):
    """Build the `alert(text)` callable. Scrubs secrets, then truncates."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    def _post(u, payload):
        import httpx
        httpx.post(u, json=payload, timeout=15)

    send = post or _post

    def alert(text):
        try:
            send(url, {"chat_id": chat_id,
                       "text": redact_secrets(text, secrets)[:4000]})
        except Exception:  # noqa: BLE001 - an alert must never take the supervisor down
            pass

    return alert


def promote(repo, body_home, commit):
    set_last_good(repo, commit)
    clear_restart_request(body_home)


def rollback(repo, body_home, reason):
    good = last_good(repo)
    diff = ""
    if good:
        try:
            diff = git(repo, "diff", f"{good}..HEAD")
        except subprocess.CalledProcessError:
            diff = ""
        reset_hard(repo, good)
        # `reset --hard` does not remove untracked files, and self_write_file
        # never commits. A new file the agent wrote (`sitecustomize.py`, a root
        # `conftest.py` — both auto-imported by Python) would otherwise survive
        # every rollback and leave the repo structurally unrecoverable.
        # No -x: all runtime state lives under ~/.caelza-body/ (spec §146), and the
        # ignored dev files in the repo (the sdd workspace) must be kept.
        git(repo, "clean", "-fd")
    clear_restart_request(body_home)
    return diff


class Supervisor:
    def __init__(self, repo, body_home, *, alert, spawn_agent, spawn_probe,
                 spawn_sidecar, spawn_runtime=None, clock=time.monotonic, sleep=time.sleep):
        self.repo = Path(repo)
        self.body_home = Path(body_home)
        self.alert = alert
        self._spawn_agent = spawn_agent
        self._spawn_probe = spawn_probe
        self._spawn_sidecar = spawn_sidecar
        #: Returns a Child running `caelza daemon` from the current runtime,
        #: or None when no runtime is installed. Unset: the Runtime is not ours.
        self._spawn_runtime = spawn_runtime
        self._clock = clock
        self._sleep = sleep
        self.agent = None
        self.sidecar = None
        self.runtime = None
        self._sidecar_next_try = 0.0
        self.crashes = CrashLoop()
        self.runtime_crashes = CrashLoop()
        self._last_good_looping = False
        self._runtime_last_good_looping = False
        self._halted = False
        self._runtime_halted = False
        self._agent_started_at = 0.0
        if last_good(self.repo) is None:
            set_last_good(self.repo, current_commit(self.repo))

    SIDECAR_RETRY_BACKOFF = 60.0

    def _ensure_sidecar(self):
        if self.sidecar is not None and self.sidecar.running:
            return
        if self._clock() < self._sidecar_next_try:
            return  # backing off — a dead sidecar shouldn't spin-respawn every tick
        self._sidecar_next_try = self._clock() + self.SIDECAR_RETRY_BACKOFF
        child = self._spawn_sidecar()
        if child is None:  # sidecar disabled (e.g. CAELZA_BODY_NO_SHARPWAVE)
            self.sidecar = None
            return
        self.sidecar = child
        self.sidecar.start()

    def _start_agent(self):
        self.agent = self._spawn_agent()
        self.agent.start()
        self._agent_started_at = self._real_now()

    def _start_runtime(self):
        child = self._spawn_runtime()
        if child is None:
            self.runtime = None
            return
        self.runtime = child
        self.runtime.start()

    def _tick_runtime(self):
        """Run the Runtime binary and keep it on a binary that holds.

        A restart request (`runtime_guard.update` promoted a probed
        version) restarts the child on `current`. A crash loop rolls
        `current` back to `last-good` and restarts; a crash loop on
        last-good itself halts the Runtime and asks for a human.
        """
        if self._spawn_runtime is None or self._runtime_halted:
            return
        req = runtime_guard.read_restart_request(self.body_home)
        if req:
            runtime_guard.clear_restart_request(self.body_home)
            if self.runtime is not None:
                self.runtime.stop()
            self.runtime_crashes.reset()
            self._runtime_last_good_looping = False
            self.alert(f"runtime: restarting on {req.get('version') or '?'}: {req.get('reason', '')}")
            self._start_runtime()
            return
        if self.runtime is None:
            self._start_runtime()
            return
        if not self.runtime.running:
            now = self._clock()
            self.runtime_crashes.record_exit(now)
            if self.runtime_crashes.tripped(now):
                if self._runtime_last_good_looping:
                    self.alert("runtime: the last-good binary is crash-looping. stopping it. manual fix needed.")
                    self._runtime_halted = True
                    return
                rolled = runtime_guard.rollback(self.body_home)
                if rolled:
                    self.alert(f"runtime crash-looped, rolled back to last-good {rolled}.")
                else:
                    self.alert("runtime crash-looped and there is no other last-good binary; restarting it once more.")
                self.runtime_crashes.reset()
                self._runtime_last_good_looping = True
            self._start_runtime()

    def tick(self):
        self._ensure_sidecar()
        self._tick_runtime()
        if self._halted:
            return
        if self.agent is None:
            self._start_agent()
            return

        req = read_restart_request(self.body_home)
        if req and commit_exists(self.repo, req["commit"]):
            self.agent.stop()
            ok, detail = run_probe(self.repo, self.body_home, self._spawn_probe)
            if ok:
                promote(self.repo, self.body_home, req["commit"])
                self.alert(f"updated: {req['reason']}")
                self._last_good_looping = False
            else:
                diff = rollback(self.repo, self.body_home, req["reason"])
                self.alert(
                    f"change '{req['reason']}' failed probe, rolled back.\n"
                    f"{detail}\n\n{diff[:3000]}"
                )
            self._start_agent()
            return

        if not self.agent.running:
            now = self._clock()
            self.crashes.record_exit(now)
            if self.crashes.tripped(now):
                if self._last_good_looping:
                    self.alert("last-good is crash-looping. stopping. manual fix needed.")
                    self._halted = True
                    return
                diff = rollback(self.repo, self.body_home, "crash loop")
                self.alert(f"agent crash-looped, rolled back to last-good.\n{diff[:3000]}")
                self.crashes.reset()
                self._last_good_looping = True
            self._start_agent()
            return

        # NOTE: the `_last_good_looping` latch is NOT cleared here. Spec §5.1:
        # it is cleared on a successful promote only. Clearing it whenever the
        # agent happens to be alive on a tick made the terminal `halted` state
        # unreachable for any agent that survived a single 2s tick.
        if (self._real_now() - self._agent_started_at > HEARTBEAT_MAX_AGE
                and heartbeat_age(self.body_home, self._real_now()) > HEARTBEAT_MAX_AGE):
            self.agent.stop()
            self._start_agent()

    def _real_now(self):
        return time.time()

    def run(self):
        try:
            while True:
                self.tick()
                self._sleep(2.0)
        except KeyboardInterrupt:
            if self.agent:
                self.agent.stop()
            if self.sidecar:
                self.sidecar.stop()
            if self.runtime:
                self.runtime.stop()


def main():  # pragma: no cover - wiring, exercised in staging
    import os
    from caelza_body.agent import config as _config

    repo = Path(__file__).resolve().parent.parent
    body_home = _config.resolve_home()   # honours the legacy NIBA_HOME / ~/.niba
    os.environ["CAELZA_BODY_HOME"] = str(body_home)
    cfg = _config.load_config()

    secrets = [cfg.telegram_token, cfg.openrouter_api_key]
    try:
        mmx = _config.load_mmx_token(cfg.mmx_config_path)
        secrets += [mmx.access_token, mmx.refresh_token]
    except Exception:  # noqa: BLE001 - no token file yet is fine, still scrub the rest
        pass
    alert = build_alert(cfg.owner_chat_id, cfg.telegram_token, secrets)

    logs = body_home / "logs"
    env = {"CAELZA_BODY_HOME": str(body_home)}
    run_sh = str(repo / "scripts" / "run-agent.sh")

    def spawn_agent():
        return Child("agent", ["sh", run_sh], cwd=repo, log_dir=logs, env=env)

    def spawn_probe():
        return Child("probe", ["sh", run_sh, "--probe"], cwd=repo, log_dir=logs, env=env)

    def spawn_sidecar():
        # The agent process owns its own SharpWave (one MCP stdio server per its
        # own lifetime) — a second supervisor-owned copy on the same DB just
        # fights it for the SQLite lock. No sidecar.
        return None

    def spawn_runtime():
        # The Runtime binary the guard installed (`caelza-body runtime update`);
        # none installed means the Runtime is run some other way (or not yet).
        binary = runtime_guard.current_binary(body_home)
        if binary is None:
            return None
        return Child("runtime", [str(binary), "daemon"], cwd=body_home, log_dir=logs,
                     env={**env, "CAELZA_SUPERVISED": "1"})

    Supervisor(repo, body_home, alert=alert, spawn_agent=spawn_agent,
               spawn_probe=spawn_probe, spawn_sidecar=spawn_sidecar,
               spawn_runtime=spawn_runtime).run()


if __name__ == "__main__":
    main()
