import httpx
from pathlib import Path
from niba.agent.telegram import Telegram


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.telegram.org")


def test_get_updates_parses_text_and_photo():
    def handler(req):
        assert "getUpdates" in req.url.path
        return httpx.Response(200, json={"ok": True, "result": [
            {"update_id": 1, "message": {"chat": {"id": 42}, "text": "hi"}},
            {"update_id": 2, "message": {"chat": {"id": 42}, "photo": [
                {"file_id": "small"}, {"file_id": "big"}]}},
        ]})
    tg = Telegram("T", _client(handler))
    ups = tg.get_updates(offset=0)
    assert ups[0].text == "hi"
    assert ups[1].photo_file_id == "big"


def test_send_message_splits_long_text():
    seen = []
    def handler(req):
        import json
        seen.append(json.loads(req.content)["text"])
        return httpx.Response(200, json={"ok": True, "result": {}})
    tg = Telegram("T", _client(handler))
    tg.send_message(42, "x" * 9000)
    assert len(seen) == 3


def test_download_file(tmp_path):
    def handler(req):
        if "getFile" in req.url.path:
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "photos/p.jpg"}})
        return httpx.Response(200, content=b"JPEGDATA")
    tg = Telegram("T", _client(handler))
    out = tg.download_file("fid", tmp_path / "p.jpg")
    assert out.read_bytes() == b"JPEGDATA"


def test_send_typing():
    seen = []
    def handler(req):
        import json
        if "sendChatAction" in req.url.path:
            seen.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "result": True})
    tg = Telegram("T", _client(handler))
    tg.send_typing(42)
    assert seen == [{"chat_id": 42, "action": "typing"}]
