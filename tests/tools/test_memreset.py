from niba.agent import tools
from niba.agent.tools import memreset

_RESET_OK = ('Brain reset for "niba".\n'
             'Backup: /data/.sharpwave/niba/brain.db.20260831-120000.bak\n'
             'Cleared: 3 nodes, 1 edges, 0 episodes, 0 vectors, 0 associations, 0 working-memory rows.')


class FakeMemory:
    def __init__(self, reply=_RESET_OK):
        self.calls = []
        self._reply = reply

    def reset(self, confirm):
        self.calls.append(confirm)
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


def _wire(mem):
    tools.reset()
    memreset.configure(mem, agent_id="niba")
    memreset.register()


def test_wrong_confirm_is_a_noop_error():
    mem = FakeMemory()
    _wire(mem)
    out = tools.dispatch("memory_reset", {"confirm": "yes"})
    assert out.startswith("error:") and "niba" in out
    assert mem.calls == []  # never touched the backend


def test_success_returns_backend_text_with_backup_path():
    mem = FakeMemory()
    _wire(mem)
    out = tools.dispatch("memory_reset", {"confirm": "niba"})
    assert mem.calls == ["niba"]
    assert out.startswith('Brain reset for "niba".')
    assert "Backup: /data/.sharpwave/niba/brain.db.20260831-120000.bak" in out


def test_backend_refusal_is_reported_as_error_not_success():
    mem = FakeMemory(reply="Error: refused — brain_reset needs confirm")
    _wire(mem)
    out = tools.dispatch("memory_reset", {"confirm": "niba"})
    assert out.startswith("error:") and "nothing was wiped" in out
    assert "Error: refused" in out


def test_backup_failure_is_reported_as_error():
    mem = FakeMemory(reply="Error: aborted before wiping anything — backup failed: disk full")
    _wire(mem)
    out = tools.dispatch("memory_reset", {"confirm": "niba"})
    assert out.startswith("error:") and "disk full" in out


def test_empty_backend_reply_is_reported_as_error():
    mem = FakeMemory(reply="")
    _wire(mem)
    out = tools.dispatch("memory_reset", {"confirm": "niba"})
    assert out.startswith("error:")
    assert mem.calls == ["niba"]  # the call was made; we just can't confirm it worked


def test_unreachable_backend_is_reported_as_error_nothing_wiped():
    mem = FakeMemory(reply=RuntimeError("no memory backend"))
    _wire(mem)
    out = tools.dispatch("memory_reset", {"confirm": "niba"})
    assert out.startswith("error:") and "nothing wiped" in out
