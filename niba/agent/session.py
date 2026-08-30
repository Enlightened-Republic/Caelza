from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path


class Session:
    def __init__(self, db_path: Path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS messages "
            "(id INTEGER PRIMARY KEY, ts REAL, role TEXT, content TEXT, meta TEXT)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS usage "
            "(id INTEGER PRIMARY KEY, ts REAL, prompt_tokens INT, completion_tokens INT)"
        )
        self.db.commit()

    def append(self, role, content, meta=None):
        self.db.execute(
            "INSERT INTO messages (ts, role, content, meta) VALUES (?,?,?,?)",
            (time.time(), role, content, json.dumps(meta) if meta else None),
        )
        self.db.commit()

    def recent(self, n):
        rows = self.db.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def log_tokens(self, prompt, completion):
        self._insert_usage(prompt, completion, ts=time.time())

    def _insert_usage(self, prompt, completion, ts):
        self.db.execute(
            "INSERT INTO usage (ts, prompt_tokens, completion_tokens) VALUES (?,?,?)",
            (ts, prompt, completion),
        )
        self.db.commit()

    def tokens_this_month(self, now=None):
        now = now or time.time()
        start = datetime.fromtimestamp(now, tz=timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        row = self.db.execute(
            "SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0) "
            "FROM usage WHERE ts >= ?", (start,)
        ).fetchone()
        return int(row[0])

    def calls_last_hour(self, now=None):
        now = now or time.time()
        row = self.db.execute(
            "SELECT COUNT(*) FROM usage WHERE ts >= ?", (now - 3600,)
        ).fetchone()
        return int(row[0])

    def close(self):
        self.db.close()
