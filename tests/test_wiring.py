"""C1 + I2: the shared httpx client / Telegram wiring, and probe redaction.

These cover the gap the reviewer found: every other test injects
``base_url=`` into its own client, so nothing ever asserted that the client
``main()`` and ``loop.probe()`` actually build has one.
"""
import json

import httpx

from caelza_body.agent import loop as loop_mod
from caelza_body.agent import telegram as telegram_mod
from caelza_body.agent.config import Config
from caelza_body.agent.model import Model
from caelza_body.agent.session import Session
from caelza_body.agent.telegram import TELEGRAM_API_BASE, Telegram


def _cfg(tmp_path, token="BOT-TOKEN-123456"):
    (tmp_path / "mmx.json").write_text(
        json.dumps({"access_token": "AT-123456", "refresh_token": "RT-123456"})
    )
    return Config(
        telegram_token=token,
        owner_chat_id=42,
        openrouter_api_key="OR-KEY-123456",
        model_calls_per_hour=100,
        monthly_token_budget=10**12,
        body_home=tmp_path,
        repo_root=tmp_path,
        mmx_config_path=tmp_path / "mmx.json",
    )


# --- C1: the shared client must carry Telegram's base_url ------------------

def test_api_client_has_telegram_base_url():
    with telegram_mod.api_client() as c:
        assert str(c.base_url).rstrip("/") == TELEGRAM_API_BASE


def test_telegram_over_the_real_client_resolves_relative_paths():
    """A Telegram built the way main()/probe() build it must reach the API.

    The transport records the absolute URL httpx resolved the relative
    ``/bot<token>/<method>`` path to.
    """
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200, json={"ok": True, "result": {"username": "niba_bot"}})

    with telegram_mod.api_client(transport=httpx.MockTransport(handler)) as client:
        tg = Telegram("TOK", client)
        assert tg.get_me() == {"username": "niba_bot"}
    assert seen == ["https://api.telegram.org/botTOK/getMe"]


def test_telegram_download_file_resolves_relative_path(tmp_path):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        if "getFile" in req.url.path:
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "photos/p.jpg"}})
        return httpx.Response(200, content=b"JPEG")

    with telegram_mod.api_client(transport=httpx.MockTransport(handler)) as client:
        Telegram("TOK", client).download_file("fid", tmp_path / "out.jpg")
    assert seen[-1] == "https://api.telegram.org/file/botTOK/photos/p.jpg"


def test_model_absolute_url_overrides_telegram_base_url(tmp_path):
    """The one client is shared: Model's absolute URLs must not be rebased."""
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })

    with telegram_mod.api_client(transport=httpx.MockTransport(handler)) as client:
        m = Model(_cfg(tmp_path), Session(tmp_path / "s.db"), client)
        assert m.complete([{"role": "user", "content": "hi"}], []).content == "hi"
    assert seen == ["https://api.minimax.io/v1/chat/completions"]


# --- C1: probe must exercise that same wiring ------------------------------

def _patch_api_client(monkeypatch, handler):
    monkeypatch.setattr(
        telegram_mod, "api_client",
        lambda transport=None: httpx.Client(
            base_url=TELEGRAM_API_BASE, transport=httpx.MockTransport(handler)),
    )


def test_probe_ok_calls_get_me_through_a_real_telegram(tmp_path, monkeypatch):
    from caelza_body.agent import main as main_mod
    cfg = _cfg(tmp_path)
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200, json={"ok": True, "result": {"id": 1}})

    _patch_api_client(monkeypatch, handler)
    main_mod._register_tools(cfg.repo_root, cfg.body_home)
    assert loop_mod.probe(cfg) == 0
    assert seen == [f"https://api.telegram.org/bot{cfg.telegram_token}/getMe"]
    assert (tmp_path / "run" / "probe-ok").read_text() == "ok"


def test_probe_fails_when_telegram_call_fails(tmp_path, monkeypatch):
    from caelza_body.agent import main as main_mod
    cfg = _cfg(tmp_path)
    _patch_api_client(monkeypatch, lambda req: httpx.Response(500, text="boom"))
    main_mod._register_tools(cfg.repo_root, cfg.body_home)
    assert loop_mod.probe(cfg) == 1
    assert not (tmp_path / "run" / "probe-ok").exists()


def test_probe_fails_when_the_mmx_token_file_is_missing(tmp_path, monkeypatch):
    from caelza_body.agent import main as main_mod
    cfg = _cfg(tmp_path)
    (tmp_path / "mmx.json").unlink()
    _patch_api_client(monkeypatch, lambda req: httpx.Response(200, json={"ok": True, "result": {}}))
    main_mod._register_tools(cfg.repo_root, cfg.body_home)
    assert loop_mod.probe(cfg) == 1
    assert not (tmp_path / "run" / "probe-ok").exists()


# --- I2: the bot token must never reach probe.log --------------------------

def test_probe_failure_output_redacts_the_bot_token(tmp_path, monkeypatch, capsys):
    from caelza_body.agent import main as main_mod
    cfg = _cfg(tmp_path)
    _patch_api_client(monkeypatch, lambda req: httpx.Response(401, text="Unauthorized"))
    main_mod._register_tools(cfg.repo_root, cfg.body_home)
    assert loop_mod.probe(cfg) == 1
    out = capsys.readouterr().out
    assert "probe failed" in out
    assert cfg.telegram_token not in out  # httpx puts the request URL in the error string
    assert "«redacted»" in out


def test_probe_redacts_even_when_the_mmx_token_file_is_missing(tmp_path, monkeypatch, capsys):
    """The Redactor must be built before anything can fail, tolerating no token file."""
    from caelza_body.agent import main as main_mod
    cfg = _cfg(tmp_path)
    (tmp_path / "mmx.json").unlink()
    _patch_api_client(monkeypatch, lambda req: httpx.Response(401, text="Unauthorized"))
    main_mod._register_tools(cfg.repo_root, cfg.body_home)
    assert loop_mod.probe(cfg) == 1
    out = capsys.readouterr().out
    assert cfg.telegram_token not in out
    assert "«redacted»" in out


# --- tool registration via _register_tools + probe --------------------------

def test_all_v1_and_plan2_a_tools_register():
    from caelza_body.agent import tools
    from caelza_body.agent.tools import selfmod, shell, sensors, memtools, web
    tools.reset()
    selfmod.register(); shell.register(); sensors.register(); web.register()
    memtools.configure(object()); memtools.register()
    names = set(tools.REGISTRY)
    assert {"self_read_file", "shell_run", "sensors_camera_photo",
            "memory_recall", "web_search"} <= names


def test_memory_reset_absent_from_probe_then_registers_and_dispatches(tmp_path):
    """memory_reset needs the live Memory built in main(), so _register_tools
    (the probe path — no backend) must never register it. Once wired with a
    real Memory it registers AND dispatches."""
    from caelza_body.agent import main as main_mod, tools
    from caelza_body.agent.tools import memreset
    from caelza_body.agent.memory import Memory
    tools.reset()
    main_mod._register_tools(tmp_path, tmp_path)
    assert "memory_reset" not in tools.REGISTRY

    memreset.configure(Memory(lambda n, a: {"raw": 'Brain reset for "niba".\nBackup: /x'}))
    memreset.register()
    assert "memory_reset" in tools.REGISTRY
    assert tools.dispatch("memory_reset", {"confirm": "niba"}).startswith("Brain reset")
