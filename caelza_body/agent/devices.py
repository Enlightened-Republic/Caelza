from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _groups(value) -> list[str]:
    """Normalise a groups value: a list, or a comma-separated string."""
    if value is None:
        return []
    if isinstance(value, str):
        value = value.split(",")
    seen: list[str] = []
    for g in value:
        g = str(g).strip()
        if g and g not in seen:
            seen.append(g)
    return seen


class DeviceRegistry:
    """JSON-based registry for the phones this Body reaches.

    Two kinds of entry share one address space (the `device` argument every
    device tool takes):

    - ``adb``: a phone paired over ADB wireless debugging; ``host`` is its
      ``ip:port`` and every tool runs ``adb -s <host>`` against it.
    - ``http``: a phone running its own Body (``caelza-body serve --http``);
      ``url`` is its MCP endpoint and ``token_file`` holds the bearer token.
      Tool calls naming it are forwarded to that Body (``caelza_body.fleet``).

    Every entry may carry ``groups`` (``["family", "test-bench"]``) so a
    procedure can be run on a whole group at once.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._stamp = None
        self._data = self._load()

    def _stat(self):
        try:
            st = self.path.stat()
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def _load(self) -> dict[str, dict]:
        """Load registry from disk. Returns empty dict if missing, unreadable,
        corrupt, or not a JSON object — never raises into startup."""
        self._stamp = self._stat()
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, ValueError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _refresh(self) -> None:
        """Re-read the file when someone else wrote it: `caelza-body fleet
        join` runs beside a long-lived Body, and the Body must see the new
        phone, and must not drop it with its next save."""
        if self._stat() != self._stamp:
            self._data = self._load()

    def _save(self) -> None:
        """Persist current state to disk atomically (write tmp, then rename), so
        a kill mid-write can't leave truncated JSON that reads back as empty;
        the tmp name is per process, so two writers never race on one."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        os.replace(tmp, self.path)
        self._stamp = self._stat()

    def _now_iso(self) -> str:
        """Current time in ISO 8601 format."""
        return datetime.now(timezone.utc).isoformat()

    def add(self, name: str, host: str, notes: str = "", groups=None) -> None:
        """Register a phone paired over ADB."""
        self._refresh()
        now = self._now_iso()
        self._data[name] = {
            "host": host,
            "paired_at": now,
            "last_seen": now,
            "notes": notes,
            "groups": _groups(groups),
        }
        self._save()

    def add_remote(self, name: str, url: str, token_file: str, notes: str = "", groups=None) -> None:
        """Register a phone that runs its own Body, reached over HTTP."""
        self._refresh()
        now = self._now_iso()
        self._data[name] = {
            "url": url,
            "token_file": str(token_file),
            "paired_at": now,
            "last_seen": now,
            "notes": notes,
            "groups": _groups(groups),
        }
        self._save()

    def remove(self, name: str) -> None:
        """Remove a device. No-op if not found."""
        self._refresh()
        self._data.pop(name, None)
        self._save()

    def get(self, name: str) -> dict | None:
        """Get device entry, or None if not found."""
        self._refresh()
        return self._data.get(name)

    def all(self) -> dict[str, dict]:
        """Return a copy of all registered devices (mutating it won't persist)."""
        self._refresh()
        return dict(self._data)

    def touch(self, name: str) -> None:
        """Update last_seen timestamp for a device."""
        self._refresh()
        if name in self._data:
            self._data[name]["last_seen"] = self._now_iso()
            self._save()

    # --- kinds and groups --------------------------------------------------

    @staticmethod
    def kind_of(entry: dict | None) -> str:
        """``http`` for a remote Body, ``adb`` for a paired phone."""
        return "http" if entry and entry.get("url") else "adb"

    def kind(self, name: str) -> str | None:
        entry = self.get(name)
        return None if entry is None else self.kind_of(entry)

    def set_groups(self, name: str, groups) -> list[str] | None:
        """Replace a device's groups; None when the device is unknown."""
        self._refresh()
        entry = self._data.get(name)
        if entry is None:
            return None
        entry["groups"] = _groups(groups)
        self._save()
        return list(entry["groups"])

    def groups(self) -> dict[str, list[str]]:
        """``{group: [device names]}``, names sorted, groups sorted."""
        self._refresh()
        out: dict[str, list[str]] = {}
        for name, entry in self._data.items():
            for g in _groups(entry.get("groups")):
                out.setdefault(g, []).append(name)
        return {g: sorted(names) for g, names in sorted(out.items())}

    def in_group(self, group: str) -> list[str]:
        return self.groups().get(group.strip(), [])
