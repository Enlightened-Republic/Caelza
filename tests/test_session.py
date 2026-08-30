import time
from datetime import datetime, timezone
from niba.agent.session import Session


def test_append_and_recent(tmp_path):
    s = Session(tmp_path / "s.db")
    s.append("user", "hi")
    s.append("assistant", "hello")
    s.append("user", "bye")
    assert s.recent(2) == [
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "bye"},
    ]


def test_token_accounting(tmp_path):
    s = Session(tmp_path / "s.db")
    s.log_tokens(100, 20)
    s.log_tokens(5, 5)
    assert s.tokens_this_month() == 130


def test_calls_last_hour_windows(tmp_path):
    s = Session(tmp_path / "s.db")
    now = time.time()
    s._insert_usage(1, 1, ts=now - 7200)   # test helper, 2h ago
    s._insert_usage(1, 1, ts=now - 60)
    s._insert_usage(1, 1, ts=now - 10)
    assert s.calls_last_hour(now=now) == 2


def test_tokens_this_month_respects_now_param(tmp_path):
    """
    Verify that tokens_this_month correctly uses the `now` parameter
    to determine the month boundary, not the current system time.
    """
    s = Session(tmp_path / "s.db")

    # Reference time: August 29, 2026, noon UTC
    now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc).timestamp()

    # Insert one row from July 20, 2026 (last month, ~40 days before, should NOT be counted)
    july_ts = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    s._insert_usage(1000, 100, ts=july_ts)

    # Insert one row from August 28, 2026 (this month, ~1 day before, should be counted)
    august_ts = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    s._insert_usage(50, 10, ts=august_ts)

    # When called with now=August 29, should count only August row: 50 + 10 = 60
    assert s.tokens_this_month(now=now) == 60
