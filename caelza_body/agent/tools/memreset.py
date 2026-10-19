from __future__ import annotations

from caelza_body.agent import tools
from caelza_body.agent.memory import NIBA_AGENT_ID

_MEM = None
_AGENT_ID = NIBA_AGENT_ID


def configure(memory, agent_id: str = NIBA_AGENT_ID):
    global _MEM, _AGENT_ID
    _MEM = memory
    _AGENT_ID = agent_id


def register():
    @tools.tool(
        "memory_reset",
        "DESTRUCTIVE. Wipe your entire long-term memory (every node, edge, and "
        "episode) back to empty. SharpWave takes a timestamped .db backup first. "
        "Pass confirm='niba' (your agent id) to proceed.",
        {"type": "object",
         "properties": {"confirm": {"type": "string",
                                    "description": "must equal your agent id 'niba'"}},
         "required": ["confirm"]},
    )
    def memory_reset(confirm):
        if confirm != _AGENT_ID:
            return (f"error: confirm must be exactly '{_AGENT_ID}' (the agent id) "
                    f"to wipe the brain — nothing was done")
        try:
            text = _MEM.reset(confirm)
        except Exception as e:  # noqa: BLE001 - backend down: nothing was wiped
            return f"error: reset failed, nothing wiped — {type(e).__name__}: {e}"
        if text.startswith("Brain reset for"):
            return text  # includes 'Backup: <path>' and the cleared-counts line
        return ("error: reset did not confirm — assume nothing was wiped — "
                f"backend said: {text or '(no reply)'}")
