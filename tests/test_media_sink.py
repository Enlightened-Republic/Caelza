import base64
from niba.agent import tools
from niba.agent.tools import media
from niba.agent.loop import handle_turn, _drained_image_parts
from niba.agent.session import Session
from niba.agent.redact import Redactor
from niba.agent.telegram import Update
from niba.agent.model import Assistant, ToolCall


def test_emit_and_drain():
    media.PENDING_MEDIA.clear()
    media.emit_image("/tmp/a.png", "image/png")
    assert tools.drain() == [("/tmp/a.png", "image/png")]
    assert tools.drain() == []


def test_drained_parts_skip_a_vanished_capture(tmp_path):
    parts = _drained_image_parts([(str(tmp_path / "gone.png"), "image/png")])
    assert len(parts) == 1 and parts[0]["type"] == "text"
    assert "image unavailable" in parts[0]["text"] and "gone.png" in parts[0]["text"]


def test_drained_parts_cap_at_three_images(tmp_path):
    media_batch = []
    for i in range(5):
        p = tmp_path / f"{i}.png"
        p.write_bytes(b"PNG-" + bytes([i]))
        media_batch.append((str(p), "image/png"))
    parts = _drained_image_parts(media_batch)
    imgs = [x for x in parts if x.get("type") == "image_url"]
    assert len(imgs) == 3
    assert any(x.get("type") == "text" and "dropped" in x["text"] for x in parts)


def test_drained_parts_cap_total_bytes(tmp_path, monkeypatch):
    import niba.agent.loop as loop_mod
    # one 200-byte png encodes to ~272 chars; cap at 400 -> first fits, second
    # pushes over, so exactly one image survives.
    monkeypatch.setattr(loop_mod, "MAX_DRAIN_ENCODED_BYTES", 400)
    batch = []
    for i in range(3):
        p = tmp_path / f"{i}.png"
        p.write_bytes(b"X" * 200)
        batch.append((str(p), "image/png"))
    parts = loop_mod._drained_image_parts(batch)
    imgs = [x for x in parts if x.get("type") == "image_url"]
    assert len(imgs) == 1  # first fits; the rest are over-budget
    assert any(x.get("type") == "text" and "over" in x["text"] for x in parts)


def test_drained_parts_cap_applies_to_the_first_image_too(tmp_path, monkeypatch):
    """Imp-3: a single oversized capture is dropped, not waved through to be
    re-uploaded on every subsequent round."""
    import niba.agent.loop as loop_mod
    monkeypatch.setattr(loop_mod, "MAX_DRAIN_ENCODED_BYTES", 50)
    p = tmp_path / "huge.png"
    p.write_bytes(b"X" * 500)
    parts = loop_mod._drained_image_parts([(str(p), "image/png")])
    assert not [x for x in parts if x.get("type") == "image_url"]
    assert any("over" in x.get("text", "") for x in parts)


def test_turn_completes_when_a_drained_image_is_missing(tmp_path):
    tools.reset(); media.PENDING_MEDIA.clear()

    @tools.tool("snap", "d", {"type": "object", "properties": {}})
    def snap():
        media.emit_image(str(tmp_path / "never-written.png"), "image/png")
        return "captured"

    class M:
        def __init__(s): s.seen = []
        def complete(s, messages, toolz):
            s.seen.append(messages)
            if len(s.seen) == 1:
                return Assistant(None, [ToolCall("c1", "snap", {})],
                                 {"role": "assistant", "tool_calls": [
                                     {"id": "c1", "type": "function",
                                      "function": {"name": "snap", "arguments": "{}"}}]})
            return Assistant("done", [], {"role": "assistant", "content": "done"})

    class FakeMem:
        def recall(s, q, k=8): return []
        def remember(s, t, links=None): return "n1"

    sent = []
    class FakeTg:
        def send_typing(s, c): pass
        def send_message(s, c, t): sent.append(t)
        def download_file(s, *a): raise AssertionError

    prompt = tmp_path / "p.md"; prompt.write_text("x")
    m = M()
    handle_turn(update=Update(1, 42, text="look"), telegram=FakeTg(), model=m,
                memory=FakeMem(), session=Session(tmp_path / "s.db"), tools_mod=tools,
                prompt_path=prompt, cfg=None, redactor=Redactor([]), tmp_dir=tmp_path)
    assert sent == ["done"]
    round2 = m.seen[1]
    texts = [part["text"] for msg in round2 if isinstance(msg.get("content"), list)
             for part in msg["content"] if part.get("type") == "text"]
    assert any("image unavailable" in t for t in texts)


def test_image_tool_result_reaches_model_as_image(tmp_path):
    img = tmp_path / "shot.png"; img.write_bytes(b"PNGDATA")
    tools.reset(); media.PENDING_MEDIA.clear()

    @tools.tool("snap", "d", {"type": "object", "properties": {}})
    def snap():
        media.emit_image(str(img), "image/png")
        return "captured"

    class M:
        def __init__(s): s.seen = []
        def complete(s, messages, toolz):
            s.seen.append(messages)
            if len(s.seen) == 1:
                return Assistant(None, [ToolCall("c1", "snap", {})],
                                 {"role": "assistant", "tool_calls": [
                                     {"id": "c1", "type": "function",
                                      "function": {"name": "snap", "arguments": "{}"}}]})
            return Assistant("i see it", [], {"role": "assistant", "content": "i see it"})

    class FakeMem:
        def recall(s, q, k=8): return []
        def remember(s, t, links=None): return "n1"

    sent = []
    class FakeTg:
        def send_typing(s, c): pass
        def send_message(s, c, t): sent.append(t)
        def download_file(s, *a): raise AssertionError

    prompt = tmp_path / "p.md"; prompt.write_text("x")
    m = M()
    handle_turn(update=Update(1, 42, text="what do you see"), telegram=FakeTg(), model=m,
                memory=FakeMem(), session=Session(tmp_path / "s.db"), tools_mod=tools,
                prompt_path=prompt, cfg=None, redactor=Redactor([]), tmp_dir=tmp_path)
    # round 2's messages must contain an image part carrying the file's bytes
    round2 = m.seen[1]
    imgs = [part for msg in round2 if isinstance(msg.get("content"), list)
            for part in msg["content"] if part.get("type") == "image_url"]
    assert imgs and base64.b64encode(b"PNGDATA").decode() in imgs[0]["image_url"]["url"]
    assert sent == ["i see it"]
