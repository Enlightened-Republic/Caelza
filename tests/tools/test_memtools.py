from caelza_body.agent import tools
from caelza_body.agent.tools import memtools


class FakeMem:
    def recall(self, q, k=8): return [{"text": "owner's cat is Mochi"}]
    def remember(self, text, links=None): self.last = text; return "n9"


def test_memory_tools():
    tools.reset()
    fm = FakeMem()
    memtools.configure(fm)
    memtools.register()
    assert "n9" in tools.dispatch("memory_remember", {"text": "new fact"})
    assert "Mochi" in tools.dispatch("memory_recall", {"query": "cat"})
