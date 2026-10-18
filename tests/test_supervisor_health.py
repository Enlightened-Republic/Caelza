from caelza_body.supervisor import CrashLoop, heartbeat_age


def test_crashloop_trips_after_n_in_window():
    cl = CrashLoop(n=3, window=100.0)
    cl.record_exit(0.0)
    cl.record_exit(10.0)
    assert not cl.tripped(10.0)
    cl.record_exit(20.0)
    assert cl.tripped(20.0)


def test_crashloop_ignores_old_exits():
    cl = CrashLoop(n=3, window=100.0)
    cl.record_exit(0.0)
    cl.record_exit(10.0)
    cl.record_exit(200.0)
    assert not cl.tripped(200.0)


def test_crashloop_reset():
    cl = CrashLoop(n=2, window=100.0)
    cl.record_exit(0.0)
    cl.record_exit(1.0)
    cl.reset()
    assert not cl.tripped(1.0)


def test_heartbeat_age_missing_is_inf(tmp_path):
    assert heartbeat_age(tmp_path, now=100.0) == float("inf")


def test_heartbeat_age_fresh(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    hb = run / "heartbeat"
    hb.write_text("")
    import os
    os.utime(hb, (90.0, 90.0))
    assert heartbeat_age(tmp_path, now=100.0) == 10.0
