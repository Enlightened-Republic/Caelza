from caelza_body.agent.context import build_messages, user_text
from caelza_body.agent.session import Session


class FakeMem:
    def __init__(self, hits): self.hits = hits
    def recall(self, q, k=8): return self.hits


def test_build_messages_shape(tmp_path):
    p = tmp_path / "prompt.md"; p.write_text("You are Niba.")
    s = Session(tmp_path / "s.db")
    s.append("user", "earlier"); s.append("assistant", "ok")
    msgs = build_messages(prompt_path=p, session=s,
                          memory=FakeMem([{"text": "owner likes tea"}]),
                          user_content="hello")
    assert msgs[0]["role"] == "system"
    assert "You are Niba." in msgs[0]["content"]
    assert {"role": "user", "content": "earlier"} in msgs
    mem = [m for m in msgs if isinstance(m.get("content"), str)
           and "owner likes tea" in m["content"]]
    assert mem and mem[0]["role"] == "user"
    assert "not a message from the owner" in mem[0]["content"].lower()
    assert msgs[-1] == {"role": "user", "content": "hello"}


def test_no_memory_block_when_empty(tmp_path):
    p = tmp_path / "p.md"; p.write_text("x")
    s = Session(tmp_path / "s.db")
    msgs = build_messages(prompt_path=p, session=s, memory=FakeMem([]), user_content="hi")
    assert sum(1 for m in msgs if m["role"] == "system") == 1


def test_user_text_from_parts():
    parts = [{"type": "text", "text": "what is this"}, {"type": "image_url", "image_url": {"url": "x"}}]
    assert user_text(parts) == "what is this"


def test_system_message_carries_the_current_time(tmp_path):
    p = tmp_path / "p.md"; p.write_text("You are the agent.")
    s = Session(tmp_path / "s.db")
    class M:
        def recall(self, q, k=8): return []
    msgs = build_messages(prompt_path=p, session=s, memory=M(), user_content="hi")
    sysmsg = msgs[0]["content"]
    assert "You are the agent." in sysmsg
    assert "Current time:" in sysmsg
    # a 4-digit year appears
    import re
    assert re.search(r"20\d\d-\d\d-\d\d", sysmsg)
