import shutil
import pytest
from caelza_body.agent.memory import Memory


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


def test_sharpwave_env_pins_agent_and_db_path(tmp_path):
    from caelza_body.agent.memory import _sharpwave_env, NIBA_AGENT_ID
    env = _sharpwave_env(tmp_path / "sharpwave" / "db", NIBA_AGENT_ID)
    assert env["SHARPWAVE_AGENT_ID"] == "niba"
    assert env["SHARPWAVE_DB_PATH"].replace("\\", "/").endswith("sharpwave/db/brain.db")
    assert "SHARPWAVE_DB" not in env  # the 0.2.1 key is gone
    assert "PATH" in env  # inherits the real environment


_RESET_OK = ('Brain reset for "niba".\n'
             'Backup: /data/.sharpwave/niba/brain.db.20260831-000000.bak\n'
             'Cleared: 12 nodes, 5 edges, 3 episodes, 0 vectors, 0 associations, 1 working-memory rows.')


def test_memory_reset_passes_confirm_and_returns_backend_text():
    seen = []
    def call_tool(name, args):
        seen.append((name, args))
        return {"raw": _RESET_OK}
    out = Memory(call_tool).reset("niba")
    assert seen == [("brain_reset", {"confirm": "niba"})]
    assert out.startswith('Brain reset for "niba".') and "Backup:" in out


def test_memory_reset_returns_backend_error_text_unwrapped():
    m = Memory(lambda n, a: {"raw": "Error: aborted before wiping anything — backup failed: disk full"})
    assert m.reset("niba").startswith("Error:")


def test_memory_reset_propagates_when_backend_is_unreachable():
    def call_tool(name, args):
        raise RuntimeError("no memory backend")
    with pytest.raises(RuntimeError):
        Memory(call_tool).reset("niba")


def test_memory_reset_success_clears_queued_writes():
    m = Memory(lambda n, a: {"raw": _RESET_OK})
    m._pending = ["a queued pre-wipe note", "another"]
    m.reset("niba")
    assert m._pending == []


def test_memory_reset_failure_keeps_queued_writes():
    m = Memory(lambda n, a: {"raw": "Error: refused — brain_reset needs confirm"})
    m._pending = ["a queued pre-wipe note"]
    m.reset("niba")
    assert m._pending == ["a queued pre-wipe note"]


@pytest.mark.skipif(
    not shutil.which("sharpwave"),
    reason="sharpwave (npm i -g) required for the live SharpWave adapter round-trip",
)
def test_memory_adapter_roundtrip(tmp_path):
    """Live: Memory -> spawn_sharpwave_session adapter -> sharpwave@0.2.x -> back."""
    from caelza_body.agent.memory import spawn_sharpwave_session
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
