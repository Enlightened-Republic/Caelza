from __future__ import annotations

import os
import signal
import sys

from niba.agent import config as _config
from niba.agent import loop, tools
from niba.agent.memory import Memory, spawn_sharpwave_session
from niba.agent.model import Model
from niba.agent.redact import Redactor
from niba.agent.session import Session
from niba.agent.telegram import Telegram, api_client
from niba.agent.tools import device, selfmod, sensors, shell


def _register_tools(repo_root, niba_home):  # pragma: no cover
    tools.reset()
    selfmod.configure(repo_root, niba_home)
    selfmod.register()
    sensors.configure(niba_home)
    sensors.register()
    shell.register()
    device.configure(niba_home)
    device.register()


def _install_sigterm_handler():  # pragma: no cover
    """The supervisor stops the agent with SIGTERM. Python's default SIGTERM
    exits without running `finally:` blocks, so the `close()` that shuts down
    the SharpWave MCP child never fires and the node process leaks as an orphan
    fighting the next agent for the brain.db lock. Turn SIGTERM into SystemExit
    so `main()`'s try/finally runs."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))


def main(argv=None):  # pragma: no cover
    argv = argv if argv is not None else sys.argv[1:]
    _install_sigterm_handler()
    cfg = _config.load_config()

    if "--probe" in argv:
        _register_tools(cfg.repo_root, cfg.niba_home)
        raise SystemExit(loop.probe(cfg))

    _register_tools(cfg.repo_root, cfg.niba_home)
    # One shared client, based at Telegram's API root because Telegram calls use
    # relative paths. Model's absolute api.minimax.io URLs override base_url.
    client = api_client()
    session = Session(cfg.niba_home / "session.db")
    token = _config.load_mmx_token(cfg.mmx_config_path)
    redactor = Redactor(_config.secret_values(cfg, token))
    model = Model(cfg, session, client)

    def _no_memory(name, args):
        raise RuntimeError("no memory backend")

    close = lambda: None  # noqa: E731
    if os.environ.get("NIBA_NO_SHARPWAVE"):
        print("NIBA_NO_SHARPWAVE set — running memory-less")
        call_tool = _no_memory
    else:
        try:
            call_tool, close = spawn_sharpwave_session(cfg.niba_home / "sharpwave" / "db")
        except Exception as e:  # noqa: BLE001 - memory is optional; run without it
            print(f"memory backend unavailable ({type(e).__name__}: {e}) — running memory-less")
            call_tool = _no_memory

    memory = Memory(call_tool)
    from niba.agent.tools import memtools
    memtools.configure(memory)
    memtools.register()
    telegram = Telegram(cfg.telegram_token, client)
    try:
        loop.run(cfg=cfg, telegram=telegram, model=model, memory=memory,
                 session=session, tools_mod=tools, prompt_path=_prompt_path(cfg.repo_root),
                 redactor=redactor)
    finally:
        close()


def _prompt_path(repo_root):  # pragma: no cover
    """The owner's `prompt.md` (gitignored) if present, else the shipped template."""
    agent_dir = repo_root / "niba" / "agent"
    personal = agent_dir / "prompt.md"
    return personal if personal.exists() else agent_dir / "prompt.example.md"


if __name__ == "__main__":  # pragma: no cover
    main()
