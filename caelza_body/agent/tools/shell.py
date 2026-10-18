from __future__ import annotations

from caelza_body.agent import proc
from caelza_body.agent import tools

CAP = 8000


def register():
    @tools.tool("shell_run", "Run a shell command in Niba's Termux environment.",
                {"type": "object",
                 "properties": {"cmd": {"type": "string"},
                                "timeout": {"type": "integer", "default": 60}},
                 "required": ["cmd"]})
    def shell_run(cmd, timeout=60):
        timeout = max(1, min(int(timeout), 300))
        # keep the TAIL — build errors, pytest summaries and log tails live last
        rc, out, _ = proc.run(cmd, timeout=timeout, cap=CAP, cap_tail=True)
        if rc == -1 and out.startswith("error: timed out"):
            return out
        return f"exit {rc}\n{out}"
