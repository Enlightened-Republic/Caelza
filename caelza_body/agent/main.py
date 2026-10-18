from __future__ import annotations

import os
import signal
import sys

from caelza_body.agent import config as _config
from caelza_body.agent import loop, tools
from caelza_body.agent.memory import Memory, spawn_sharpwave_session
from caelza_body.agent.model import Model
from caelza_body.agent.redact import Redactor
from caelza_body.agent.session import Session
from caelza_body.agent.telegram import Telegram, api_client
from caelza_body.agent.tools import device, memreset, selfmod, sensors, shell, web


def _register_tools(repo_root, body_home, firecrawl_api_key="",
                    tavily_api_key="", searchapi_api_key=""):  # pragma: no cover
    tools.reset()
    selfmod.configure(repo_root, body_home)
    selfmod.register()
    sensors.configure(body_home)
    sensors.register()
    shell.register()
    device.configure(body_home)
    device.register()
    web.configure(body_home, firecrawl_api_key, tavily_api_key, searchapi_api_key)
    web.register()


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
        _register_tools(cfg.repo_root, cfg.body_home, cfg.firecrawl_api_key,
                        cfg.tavily_api_key, cfg.searchapi_api_key)
        raise SystemExit(loop.probe(cfg))

    _register_tools(cfg.repo_root, cfg.body_home, cfg.firecrawl_api_key,
                    cfg.tavily_api_key, cfg.searchapi_api_key)
    # One shared client, based at Telegram's API root because Telegram calls use
    # relative paths. Model's absolute api.minimax.io URLs override base_url.
    client = api_client()
    session = Session(cfg.body_home / "session.db")
    token = _config.load_mmx_token(cfg.mmx_config_path)
    redactor = Redactor(_config.secret_values(cfg, token))
    model = Model(cfg, session, client)

    def _no_memory(name, args):
        raise RuntimeError("no memory backend")

    close = lambda: None  # noqa: E731
    if os.environ.get("CAELZA_BODY_NO_SHARPWAVE"):
        print("CAELZA_BODY_NO_SHARPWAVE set — running memory-less")
        call_tool = _no_memory
    else:
        try:
            call_tool, close = spawn_sharpwave_session(cfg.body_home / "sharpwave" / "db")
        except Exception as e:  # noqa: BLE001 - memory is optional; run without it
            print(f"memory backend unavailable ({type(e).__name__}: {e}) — running memory-less")
            call_tool = _no_memory

    memory = Memory(call_tool)
    from caelza_body.agent.tools import memtools
    memtools.configure(memory)
    memtools.register()
    memreset.configure(memory)
    memreset.register()
    telegram = Telegram(cfg.telegram_token, client)
    try:
        loop.run(cfg=cfg, telegram=telegram, model=model, memory=memory,
                 session=session, tools_mod=tools, prompt_path=_prompt_path(cfg.repo_root),
                 redactor=redactor)
    finally:
        close()


def _prompt_path(repo_root):  # pragma: no cover
    """The owner's `prompt.md` (gitignored) if present, else the shipped template."""
    agent_dir = repo_root / "caelza_body" / "agent"
    personal = agent_dir / "prompt.md"
    return personal if personal.exists() else agent_dir / "prompt.example.md"


if __name__ == "__main__":  # pragma: no cover
    main()
