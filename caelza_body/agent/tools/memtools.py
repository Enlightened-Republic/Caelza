from __future__ import annotations

from caelza_body.agent import tools

_MEM = None


def configure(memory):
    global _MEM
    _MEM = memory


def register():
    @tools.tool("memory_remember", "Store an important fact in long-term memory.",
                {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})
    def memory_remember(text):
        return f"stored ({_MEM.remember(text)})"

    @tools.tool("memory_recall", "Search long-term memory.",
                {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})
    def memory_recall(query):
        hits = _MEM.recall(query)
        return "\n".join(f"- {h.get('text', '')}" for h in hits) or "(nothing)"
