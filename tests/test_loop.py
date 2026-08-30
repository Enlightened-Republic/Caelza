import httpx, json
import pytest
from pathlib import Path
from niba.agent import tools
from niba.agent import loop as loop_mod
from niba.agent.loop import handle_turn
from niba.agent.telegram import Telegram, Update
from niba.agent.session import Session
from niba.agent.redact import Redactor


class _Cfg:
    def __init__(self, home): self.niba_home = home; self.owner_chat_id = 42


def _batch(*, updates, tmp_path, sent, consec_errors=0, offset=0):
    return loop_mod._process_batch(
        updates=updates, offset=offset, offset_file=tmp_path / "run" / "offset",
        consec_errors=consec_errors, telegram=_tg(sent), model=None, memory=None,
        session=None, tools_mod=tools, prompt_path=None, cfg=_Cfg(tmp_path),
        redactor=None, tmp_dir=tmp_path)


class ScriptedModel:
    """Returns queued Assistant objects in order."""
    def __init__(self, script): self.script = list(script); self.seen = []
    def complete(self, messages, tools):
        self.seen.append(messages)
        return self.script.pop(0)


class FakeMem:
    def __init__(self): self.written = []
    def recall(self, q, k=8): return []
    def remember(self, text, links=None): self.written.append(text); return "n1"


def _tg(capture):
    def handler(req):
        if "sendMessage" in req.url.path:
            capture.append(json.loads(req.content)["text"])
        return httpx.Response(200, json={"ok": True, "result": {}})
    return Telegram("T", httpx.Client(transport=httpx.MockTransport(handler),
                                      base_url="https://api.telegram.org"))


def test_handle_turn_text_only(tmp_path):
    from niba.agent.model import Assistant
    tools.reset()

    @tools.tool("ping", "d", {"type": "object", "properties": {}})
    def ping(): return "pong"

    sent = []
    model = ScriptedModel([
        Assistant(content=None, tool_calls=[__import__("niba.agent.model", fromlist=["ToolCall"]).ToolCall("c1", "ping", {})], raw={"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "ping", "arguments": "{}"}}]}),
        Assistant(content="pong to you", tool_calls=[], raw={"role": "assistant", "content": "pong to you"}),
    ])
    prompt = tmp_path / "p.md"; prompt.write_text("You are Niba.")
    s = Session(tmp_path / "s.db")
    mem = FakeMem()
    handle_turn(update=Update(1, 42, text="ping"), telegram=_tg(sent), model=model,
                memory=mem, session=s, tools_mod=tools, prompt_path=prompt,
                cfg=None, redactor=Redactor([]), tmp_dir=tmp_path)
    assert sent == ["pong to you"]
    assert s.recent(2)[-1] == {"role": "assistant", "content": "pong to you"}
    assert mem.written  # an episode was stored
    # tool result was fed back
    assert any(m.get("role") == "tool" for m in model.seen[-1])


def test_tool_result_is_redacted(tmp_path):
    from niba.agent.model import Assistant, ToolCall
    tools.reset()

    @tools.tool("leak", "d", {"type": "object", "properties": {}})
    def leak(): return "token is SUPER-SECRET-VALUE ok"

    sent = []
    model = ScriptedModel([
        Assistant(None, [ToolCall("c1", "leak", {})], {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "leak", "arguments": "{}"}}]}),
        Assistant("done", [], {"role": "assistant", "content": "done"}),
    ])
    prompt = tmp_path / "p.md"; prompt.write_text("x")
    handle_turn(update=Update(1, 42, text="go"), telegram=_tg(sent), model=model,
                memory=FakeMem(), session=Session(tmp_path / "s.db"), tools_mod=tools,
                prompt_path=prompt, cfg=None, redactor=Redactor(["SUPER-SECRET-VALUE"]),
                tmp_dir=tmp_path)
    tool_msg = [m for m in model.seen[-1] if m.get("role") == "tool"][0]
    assert "SUPER-SECRET-VALUE" not in tool_msg["content"]
    assert "«redacted»" in tool_msg["content"]


def test_loop_survives_one_bad_message(tmp_path, monkeypatch):
    seen = []

    def fake_handle_turn(*, update, **kw):
        seen.append(update.text)
        if update.text == "bad":
            raise ValueError("boom")

    monkeypatch.setattr(loop_mod, "handle_turn", fake_handle_turn)
    sent = []
    offset, consec = _batch(
        updates=[Update(1, 42, text="bad"), Update(2, 42, text="good")],
        tmp_path=tmp_path, sent=sent)
    assert "hit an error on that one: ValueError" in sent
    assert seen == ["bad", "good"]  # loop kept going past the poison message
    assert consec == 0  # the successful "good" turn reset the counter
    assert offset == 3


def test_loop_reraises_after_three_consecutive_errors(tmp_path, monkeypatch):
    def always_raises(*, update, **kw):
        raise RuntimeError("always broken")

    monkeypatch.setattr(loop_mod, "handle_turn", always_raises)
    sent = []
    with pytest.raises(RuntimeError):
        _batch(updates=[Update(i, 42, text="x") for i in range(1, 6)],
               tmp_path=tmp_path, sent=sent)
    assert sent.count("hit an error on that one: RuntimeError") == 3


def test_offset_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(loop_mod, "handle_turn", lambda **kw: None)
    sent = []
    off_file = tmp_path / "run" / "offset"
    offset, _ = _batch(updates=[Update(7, 42, text="hi")], tmp_path=tmp_path, sent=sent)
    assert off_file.read_text() == "8"
    assert offset == 8


@pytest.mark.parametrize("garbage", ["", "notanint", "  ", "12x"])
def test_run_seeds_offset_from_corrupt_file_safely(tmp_path, garbage):
    off_file = tmp_path / "run" / "offset"
    off_file.parent.mkdir(parents=True, exist_ok=True)
    off_file.write_text(garbage)
    assert loop_mod._seed_offset(tmp_path) == 0


def test_run_seeds_offset_from_valid_file(tmp_path):
    off_file = tmp_path / "run" / "offset"
    off_file.parent.mkdir(parents=True, exist_ok=True)
    off_file.write_text("41")
    assert loop_mod._seed_offset(tmp_path) == 41
    # missing file -> 0
    assert loop_mod._seed_offset(tmp_path / "nope") == 0


# --- I3: a routine mobile 502/429/reset must not kill the agent ------------

class _StopLoop(Exception):
    """Sentinel to break run()'s infinite loop — not an httpx.HTTPError."""


class FlakyTelegram:
    """Raises a transport error on the first poll, then serves one batch."""

    def __init__(self, updates):
        self.updates = updates
        self.polls = 0
        self.timeouts = []
        self.sent = []

    def get_updates(self, offset, timeout=50):
        self.polls += 1
        self.timeouts.append(timeout)
        if self.polls == 1:
            raise httpx.ConnectError("connection reset by peer")
        if self.polls == 2:
            return self.updates
        raise _StopLoop()

    def send_message(self, chat_id, text):
        self.sent.append(text)


class _NullMem:
    def flush_pending(self): pass


def test_run_survives_a_poll_error_and_processes_the_next_batch(tmp_path, monkeypatch):
    handled = []
    monkeypatch.setattr(loop_mod, "handle_turn",
                        lambda *, update, **kw: handled.append(update.text))
    # No daemon here: it shares time.sleep, and this test asserts on the backoff.
    monkeypatch.setattr(loop_mod.heartbeat, "start_daemon", lambda home, interval: None)
    slept = []
    monkeypatch.setattr(loop_mod.time, "sleep", slept.append)

    tg = FlakyTelegram([Update(1, 42, text="hello")])
    with pytest.raises(_StopLoop):
        loop_mod.run(cfg=_Cfg(tmp_path), telegram=tg, model=None, memory=_NullMem(),
                     session=None, tools_mod=tools, prompt_path=None, redactor=None,
                     heartbeat_interval=3600.0)

    assert handled == ["hello"], "the batch after the transport error was never processed"
    assert tg.polls == 3
    assert slept == [loop_mod.POLL_ERROR_BACKOFF]
    assert (tmp_path / "run" / "offset").read_text() == "2"


def test_run_long_polls_below_the_heartbeat_window(tmp_path, monkeypatch):
    """A single poll must not be able to outlast HEARTBEAT_MAX_AGE (60s)."""
    monkeypatch.setattr(loop_mod, "handle_turn", lambda **kw: None)
    monkeypatch.setattr(loop_mod.heartbeat, "start_daemon", lambda home, interval: None)
    monkeypatch.setattr(loop_mod.time, "sleep", lambda s: None)
    tg = FlakyTelegram([])
    with pytest.raises(_StopLoop):
        loop_mod.run(cfg=_Cfg(tmp_path), telegram=tg, model=None, memory=_NullMem(),
                     session=None, tools_mod=tools, prompt_path=None, redactor=None,
                     heartbeat_interval=3600.0)
    assert set(tg.timeouts) == {25}
    assert loop_mod.POLL_TIMEOUT < 60


def test_run_starts_the_heartbeat_daemon(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(loop_mod.heartbeat, "start_daemon",
                        lambda home, interval: started.append((home, interval)))
    monkeypatch.setattr(loop_mod.time, "sleep", lambda s: None)
    tg = FlakyTelegram([])
    tg.polls = 2  # next poll raises the sentinel immediately
    with pytest.raises(_StopLoop):
        loop_mod.run(cfg=_Cfg(tmp_path), telegram=tg, model=None, memory=_NullMem(),
                     session=None, tools_mod=tools, prompt_path=None, redactor=None)
    assert started == [(tmp_path, loop_mod.HEARTBEAT_INTERVAL)]


def test_live_user_message_is_not_duplicated_in_the_prompt(tmp_path):
    """Regression: session.append ran before build_messages, so the newest
    message appeared both in session.recent() history and as the tail."""
    from niba.agent.model import Assistant
    tools.reset()
    sent = []
    model = ScriptedModel([Assistant("hi", [], {"role": "assistant", "content": "hi"})])
    prompt = tmp_path / "p.md"; prompt.write_text("You are Niba.")
    s = Session(tmp_path / "s.db")
    s.append("user", "earlier"); s.append("assistant", "ok")
    handle_turn(update=Update(9, 42, text="brand new message"), telegram=_tg(sent),
                model=model, memory=FakeMem(), session=s, tools_mod=tools,
                prompt_path=prompt, cfg=None, redactor=Redactor([]), tmp_dir=tmp_path)
    prompt_msgs = model.seen[0]
    dupes = [m for m in prompt_msgs
             if m.get("role") == "user" and m.get("content") == "brand new message"]
    assert len(dupes) == 1, f"live message duplicated: {prompt_msgs}"
