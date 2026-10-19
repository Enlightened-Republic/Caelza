from __future__ import annotations

import os
import threading
import time
from pathlib import Path

__all__ = ["beat", "start_daemon", "DEFAULT_INTERVAL"]

DEFAULT_INTERVAL = 15.0


def beat(body_home: Path) -> None:
    run = Path(body_home) / "run"
    run.mkdir(parents=True, exist_ok=True)
    # Atomic: a reader must never catch the file mid-truncate and parse "".
    tmp = run / "heartbeat.tmp"
    tmp.write_text(str(time.time()))
    dst = run / "heartbeat"
    # POSIX os.replace is atomic and never blocks. On Windows it raises
    # PermissionError while a reader holds the target open (a transient
    # sharing violation) — retry briefly rather than skip a beat.
    for _ in range(10):
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            time.sleep(0.01)
    os.replace(tmp, dst)  # last attempt — let it raise if it truly can't


def start_daemon(body_home: Path, interval: float = DEFAULT_INTERVAL,
                 stop: threading.Event | None = None) -> threading.Thread:
    """Beat every `interval` seconds from a daemon thread, and return it.

    The turn loop cannot carry the heartbeat: `get_updates` long-polls and a
    single turn can make MAX_ROUNDS model calls at timeout=180 each, both well
    past the supervisor's HEARTBEAT_MAX_AGE of 60s. The supervisor would SIGTERM
    the agent mid-turn, and because the offset is persisted *before* the turn
    runs, that message would be silently lost.

    The first beat is synchronous so there is never a window where the file is
    missing after `run()` has started.

    `stop` is an optional Event that ends the thread when set; the wait is done
    on the Event rather than `time.sleep` so the interval is interruptible.
    """
    beat(body_home)
    stop = stop if stop is not None else threading.Event()

    def _loop() -> None:
        while not stop.wait(interval):
            try:
                beat(body_home)
            except OSError:  # a transient FS error must not kill the heartbeat
                pass

    t = threading.Thread(target=_loop, name="caelza-body-heartbeat", daemon=True)
    t.start()
    return t
