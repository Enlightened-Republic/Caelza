import shutil
import pytest
from niba.agent.memory import Memory


def test_remember_calls_brain_write():
    seen = []
    def call_tool(name, args):
        seen.append((name, args))
        return {"id": "n42"}
    m = Memory(call_tool)
    assert m.remember("a fact", links=["n1"]) == "n42"
    assert seen[0][0] == "brain_write"
    assert seen[0][1]["text"] == "a fact"


def test_recall_returns_results_list():
    def call_tool(name, args):
        return {"results": [{"id": "n1", "text": "x", "score": 0.9}]}
    assert Memory(call_tool).recall("q")[0]["id"] == "n1"


def test_recall_swallows_errors():
    def call_tool(name, args):
        raise RuntimeError("sharpwave down")
    assert Memory(call_tool).recall("q") == []


@pytest.mark.skipif(
    not shutil.which("sharpwave"),
    reason="sharpwave (npm i -g) required for the live SharpWave adapter round-trip",
)
def test_memory_adapter_roundtrip(tmp_path):
    """Live: Memory -> spawn_sharpwave_session adapter -> sharpwave@0.2.x -> back."""
    from niba.agent.memory import spawn_sharpwave_session
    call_tool, close = spawn_sharpwave_session(tmp_path / "db")
    try:
        m = Memory(call_tool)
        nid = m.remember("Niba's owner keeps a red kayak in the garage")
        assert isinstance(nid, str) and len(nid) >= 8
        hits = m.recall("where is the kayak")
        assert isinstance(hits, list) and hits
        assert any("kayak" in (h.get("text") or "") for h in hits)
    finally:
        close()
