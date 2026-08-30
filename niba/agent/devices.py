from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class DeviceRegistry:
    """JSON-based registry for paired devices."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict[str, dict]:
        """Load registry from disk. Returns empty dict if missing, unreadable,
        corrupt, or not a JSON object — never raises into startup."""
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, ValueError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        """Persist current state to disk atomically (write tmp, then rename), so
        a kill mid-write can't leave truncated JSON that reads back as empty."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        os.replace(tmp, self.path)

    def _now_iso(self) -> str:
        """Current time in ISO 8601 format."""
        return datetime.now(timezone.utc).isoformat()

    def add(self, name: str, host: str, notes: str = "") -> None:
        """Register a new device."""
        now = self._now_iso()
        self._data[name] = {
            "host": host,
            "paired_at": now,
            "last_seen": now,
            "notes": notes,
        }
        self._save()

    def remove(self, name: str) -> None:
        """Remove a device. No-op if not found."""
        self._data.pop(name, None)
        self._save()

    def get(self, name: str) -> dict | None:
        """Get device entry, or None if not found."""
        return self._data.get(name)

    def all(self) -> dict[str, dict]:
        """Return a copy of all registered devices (mutating it won't persist)."""
        return dict(self._data)

    def touch(self, name: str) -> None:
        """Update last_seen timestamp for a device."""
        if name in self._data:
            self._data[name]["last_seen"] = self._now_iso()
            self._save()
