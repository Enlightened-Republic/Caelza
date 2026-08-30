from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"


def api_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """The one httpx client the whole agent shares.

    ``base_url`` is Telegram's API root because :class:`Telegram` posts to
    relative paths (``/bot<token>/<method>``, ``/file/bot<token>/<path>``).
    ``Model`` passes absolute ``https://api.minimax.io/...`` URLs, and an
    absolute URL overrides ``base_url`` in httpx, so one client serves both.
    """
    return httpx.Client(base_url=TELEGRAM_API_BASE, transport=transport)


@dataclass
class Update:
    update_id: int
    chat_id: int
    text: str | None = None
    photo_file_id: str | None = None
    voice_file_id: str | None = None
    document_file_id: str | None = None


class Telegram:
    def __init__(self, token: str, client: httpx.Client):
        self.token = token
        self.c = client

    def _api(self, method, **params):
        r = self.c.post(f"/bot{self.token}/{method}", json=params, timeout=70)
        r.raise_for_status()
        return r.json()["result"]

    def get_me(self) -> dict:
        """`getMe` — the cheapest call that proves token + wiring are live."""
        return self._api("getMe")

    def send_typing(self, chat_id) -> None:
        """Show the 'typing…' indicator (lasts ~5s; re-send for longer work)."""
        try:
            self._api("sendChatAction", chat_id=chat_id, action="typing")
        except httpx.HTTPError:
            pass  # cosmetic — never let it break a turn

    def get_updates(self, offset, timeout=25):
        result = self._api(
            "getUpdates", offset=offset, timeout=timeout,
            allowed_updates=["message"],
        )
        ups = []
        for item in result:
            msg = item.get("message")
            if not msg:
                continue
            photo = msg.get("photo")
            ups.append(Update(
                update_id=item["update_id"],
                chat_id=msg["chat"]["id"],
                text=msg.get("text"),
                photo_file_id=photo[-1]["file_id"] if photo else None,
                voice_file_id=(msg.get("voice") or {}).get("file_id"),
                document_file_id=(msg.get("document") or {}).get("file_id"),
            ))
        return ups

    def send_message(self, chat_id, text):
        for i in range(0, max(len(text), 1), 4000):
            self._api("sendMessage", chat_id=chat_id, text=text[i:i + 4000] or " ")

    def download_file(self, file_id, dest: Path):
        meta = self._api("getFile", file_id=file_id)
        r = self.c.get(f"/file/bot{self.token}/{meta['file_path']}", timeout=60)
        r.raise_for_status()
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return dest
