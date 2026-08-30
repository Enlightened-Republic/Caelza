"""C3: the heartbeat must not depend on the turn loop making progress.

``get_updates`` long-polls and ``handle_turn`` can run MAX_ROUNDS model calls at
timeout=180 each, both far longer than the supervisor's HEARTBEAT_MAX_AGE of 60s.
A daemon thread keeps beating regardless.
"""
import threading
import time

from niba.agent import heartbeat


def _hb(niba_home):
    return niba_home / "run" / "heartbeat"


def test_beat_writes_the_file(tmp_path):
    heartbeat.beat(tmp_path)
    assert _hb(tmp_path).exists()


def test_start_daemon_beats_repeatedly_without_a_turn_loop(tmp_path):
    hb = _hb(tmp_path)
    stop = threading.Event()
    t = heartbeat.start_daemon(tmp_path, interval=0.02, stop=stop)
    try:
        assert t.daemon is True
        assert hb.exists()  # first beat is synchronous — never a blind window

        # Sample until we have seen the file advance at least twice.
        seen, mtimes = [], []
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and len(seen) < 3:
            text = hb.read_text()
            if not seen or text != seen[-1]:
                seen.append(text)
                mtimes.append(hb.stat().st_mtime)
            time.sleep(0.005)
    finally:
        stop.set()
        t.join(timeout=2.0)

    assert len(seen) >= 3, f"heartbeat only advanced {len(seen) - 1} time(s): {seen}"
    assert mtimes == sorted(mtimes)
    assert float(seen[-1]) > float(seen[0])
    assert not t.is_alive()


def test_start_daemon_interval_is_interruptible(tmp_path):
    """The wait is on the Event, not time.sleep — a long interval still stops."""
    stop = threading.Event()
    t = heartbeat.start_daemon(tmp_path, interval=3600.0, stop=stop)
    stop.set()
    t.join(timeout=2.0)
    assert not t.is_alive()
