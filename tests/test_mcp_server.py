"""caelza-body: the Body's tool registry served over MCP.

The registry (`caelza_body.agent.tools`) is the source of truth; the server
must expose it without changing a schema, carry the safety classification for
every tool, hand emitted images back as image content, and survive a real
stdio round trip with the reference MCP client.
"""
from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path

import anyio
import pytest
from mcp import types

from caelza_body import mcp_server as srv
from caelza_body.agent import tools
from caelza_body.agent.tools import media

REPO_ROOT = Path(__file__).resolve().parents[1]
ALL_GROUPS = srv.GROUPS


@pytest.fixture
def body(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = srv.load_settings(tmp_path / "home", repo)
    names = srv.register_tools(settings, ALL_GROUPS)
    yield settings, names
    tools.reset()


# --- the tool list is the registry, schemas untouched -----------------------

def test_tool_list_mirrors_registry(body):
    _, names = body
    specs = {t.name: t for t in srv.mcp_tools()}
    assert set(specs) == set(names) == set(tools.REGISTRY)
    for spec in tools.schemas():
        fn = spec["function"]
        assert specs[fn["name"]].inputSchema == fn["parameters"]
        assert specs[fn["name"]].description == fn["description"]


def test_dangerous_ops_still_require_a_reason(body):
    """The Body's safety semantics ride along in the schema the Runtime sees."""
    specs = {t.name: t for t in srv.mcp_tools()}
    for name in ("device_uninstall", "device_disable", "device_settings_put", "device_appops"):
        assert "reason" in specs[name].inputSchema["required"], name
        assert specs[name].annotations.destructiveHint is True
        assert specs[name].annotations.readOnlyHint is False


def test_every_tool_is_classified_exactly_once(body):
    """A new tool must be placed in READ_ONLY, DESTRUCTIVE or NEUTRAL before it
    ships, so the Runtime's approval lists never silently miss it."""
    _, names = body
    classes = (srv.READ_ONLY, srv.DESTRUCTIVE, srv.NEUTRAL)
    for name in names:
        hits = sum(name in c for c in classes)
        assert hits == 1, f"{name} is in {hits} classes (expected exactly 1)"
    stale = (srv.READ_ONLY | srv.DESTRUCTIVE | srv.NEUTRAL) - set(names)
    assert not stale, f"classified but not registered: {sorted(stale)}"


def test_read_only_tools_are_annotated_as_such(body):
    specs = {t.name: t for t in srv.mcp_tools()}
    assert specs["sensors_battery"].annotations.readOnlyHint is True
    assert specs["sensors_battery"].annotations.idempotentHint is True
    assert specs["sensors_battery"].annotations.destructiveHint is False
    assert specs["web_search"].annotations.openWorldHint is True
    assert specs["device_input"].annotations.readOnlyHint is False
    assert specs["device_input"].annotations.destructiveHint is False


# --- the Runtime wiring example stays in sync with the code -----------------

def test_example_runtime_config_names_real_tools_and_gates_every_destructive_one(body):
    _, names = body
    cfg = tomllib.loads((REPO_ROOT / "body" / "caelza-body.example.toml").read_text())
    server = cfg["mcp"]["servers"][0]
    assert server["name"] == "body" and server["transport"] == "stdio"
    assert server["command"] == "caelza-body"
    profile = cfg["risk_profiles"]["main"]
    auto, ask = set(profile["auto_approve"]), set(profile["always_ask"])
    for entry in auto | ask:
        assert entry.startswith("body__"), entry
        assert entry.removeprefix("body__") in names, entry
    assert {f"body__{n}" for n in srv.DESTRUCTIVE} <= ask
    assert {f"body__{n}" for n in srv.READ_ONLY} == auto
    assert not (auto & ask)
    assert "body" in cfg["mcp_bundles"] and cfg["mcp_bundles"]["body"]["servers"] == ["body"]
    assert "body" in cfg["agents"]["main"]["mcp_bundles"]
    # A risk profile applies only to agents that name it.
    assert cfg["agents"]["main"]["risk_profile"] == "main"


def test_phone_example_carries_the_same_body_policy(body):
    """runtime/caelza.phone.example.toml repeats the Body blocks so one merge is
    enough; it must not drift from body/caelza-body.example.toml."""
    _, names = body
    body_cfg = tomllib.loads((REPO_ROOT / "body" / "caelza-body.example.toml").read_text())
    phone = tomllib.loads((REPO_ROOT / "runtime" / "caelza.phone.example.toml").read_text())
    # Without the version line the runtime treats the file as the legacy v1
    # layout and folds `[channels.telegram.home]` into the `default` alias.
    assert phone["schema_version"] == 3 == body_cfg["schema_version"]
    body_server = next(s for s in phone["mcp"]["servers"] if s["name"] == "body")
    assert body_server["command"] == "caelza-body" and body_server["args"] == ["serve"]
    assert phone["mcp_bundles"]["body"]["servers"] == ["body"]
    agent = phone["agents"]["main"]
    assert "body" in agent["mcp_bundles"] and agent["risk_profile"] in phone["risk_profiles"]
    profile = phone["risk_profiles"][agent["risk_profile"]]
    body_only = lambda entries: {e for e in entries if e.startswith("body__")}  # noqa: E731
    assert body_only(profile["auto_approve"]) == set(body_cfg["risk_profiles"]["main"]["auto_approve"])
    assert body_only(profile["always_ask"]) == set(body_cfg["risk_profiles"]["main"]["always_ask"])
    for entry in body_only(profile["auto_approve"]) | body_only(profile["always_ask"]):
        assert entry.removeprefix("body__") in names, entry


# --- calls: text, errors, images --------------------------------------------

@pytest.fixture
def fake_tools(tmp_path):
    tools.reset()

    @tools.tool("fake_ok", "returns a dict", {"type": "object", "properties": {"n": {"type": "integer"}}})
    def fake_ok(n=1):
        return {"n": n}

    @tools.tool("fake_err", "returns an error string", {"type": "object", "properties": {}})
    def fake_err():
        return "error: nope"

    @tools.tool("fake_shot", "emits an image", {"type": "object", "properties": {}})
    def fake_shot():
        p = tmp_path / "shot.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        media.emit_image(str(p), "image/png")
        return "screenshot captured"

    @tools.tool("fake_lost", "emits an image that vanished", {"type": "object", "properties": {}})
    def fake_lost():
        media.emit_image(str(tmp_path / "gone.jpg"), "image/jpeg")
        return "photo captured"

    yield tmp_path
    tools.reset()


def test_call_wraps_registry_text(fake_tools):
    res = anyio.run(srv.call_tool, "fake_ok", {"n": 7})
    assert res.isError is False
    assert [c.type for c in res.content] == ["text"]
    assert json.loads(res.content[0].text) == {"n": 7}


def test_call_marks_error_strings_as_errors(fake_tools):
    res = anyio.run(srv.call_tool, "fake_err", {})
    assert res.isError is True and res.content[0].text == "error: nope"
    res = anyio.run(srv.call_tool, "no_such_tool", {})
    assert res.isError is True and res.content[0].text.startswith("error: unknown tool")


def test_call_attaches_emitted_images_and_their_path(fake_tools):
    res = anyio.run(srv.call_tool, "fake_shot", {})
    assert res.isError is False
    text, image, where = res.content
    assert text.text == "screenshot captured"
    assert isinstance(image, types.ImageContent)
    assert image.mimeType == "image/png"
    import base64
    assert base64.b64decode(image.data) == b"\x89PNG\r\n\x1a\nfake"
    assert str(fake_tools / "shot.png") in where.text
    assert media.PENDING_MEDIA == []  # handed off, not left for the next call


def test_missing_image_file_is_reported_not_fatal(fake_tools):
    res = anyio.run(srv.call_tool, "fake_lost", {})
    assert res.isError is False
    assert res.content[0].text == "photo captured"
    assert "could not be read" in res.content[1].text
    assert all(c.type == "text" for c in res.content)


# --- settings ----------------------------------------------------------------

def test_load_settings_without_a_config_file(tmp_path):
    s = srv.load_settings(tmp_path / "nowhere", tmp_path)
    assert s.body_home == tmp_path / "nowhere"
    assert s.repo_root == tmp_path
    assert (s.firecrawl_api_key, s.tavily_api_key, s.searchapi_api_key) == ("", "", "")


def test_load_settings_reads_web_keys_but_needs_no_telegram(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[firecrawl]\napi_key = "fc-1"\n[tavily]\napi_key = "tv-1"\n')
    s = srv.load_settings(tmp_path)
    assert (s.firecrawl_api_key, s.tavily_api_key, s.searchapi_api_key) == ("fc-1", "tv-1", "")
    assert s.repo_root == REPO_ROOT


def test_load_settings_defaults_to_the_body_home(monkeypatch, tmp_path):
    monkeypatch.setenv("CAELZA_BODY_HOME", str(tmp_path / "h"))
    assert srv.load_settings().body_home == tmp_path / "h"


def test_register_tools_rejects_unknown_group(tmp_path):
    with pytest.raises(ValueError, match="unknown tool group"):
        srv.register_tools(srv.load_settings(tmp_path, tmp_path), ("sensors", "jetpack"))
    tools.reset()


def test_register_tools_honours_group_selection(tmp_path):
    names = srv.register_tools(srv.load_settings(tmp_path, tmp_path), ("shell", "sensors"))
    assert "shell_run" in names and "sensors_battery" in names
    assert not any(n.startswith(("device_", "web_", "self_")) for n in names)
    tools.reset()


# --- CLI ---------------------------------------------------------------------

def test_probe_reports_ok_and_tool_count(tmp_path, capsys):
    rc = srv.main(["probe", "--home", str(tmp_path / "h"), "--repo-root", str(tmp_path),
                   "--tools", "shell,sensors"])
    tools.reset()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["tools"] == 10 and out["groups"] == ["shell", "sensors"]
    assert (tmp_path / "h").is_dir()  # the state dir is created on first run


def test_list_tools_prints_schemas_and_hints(tmp_path, capsys):
    rc = srv.main(["list-tools", "--home", str(tmp_path), "--repo-root", str(tmp_path),
                   "--tools", "device"])
    tools.reset()
    assert rc == 0
    listed = json.loads(capsys.readouterr().out)
    by_name = {t["name"]: t for t in listed}
    assert "device_uninstall" in by_name
    assert by_name["device_uninstall"]["annotations"]["destructiveHint"] is True
    assert by_name["device_uninstall"]["inputSchema"]["required"] == ["pkg", "reason"]


def test_unknown_group_is_a_usage_error(tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        srv.main(["probe", "--home", str(tmp_path), "--tools", "nope"])
    assert e.value.code == 2
    assert "unknown tool group" in capsys.readouterr().err


# --- the real thing: a stdio round trip with the reference client -----------

async def test_stdio_roundtrip_with_the_reference_client(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "caelza_body.mcp_server", "serve", "--home", str(tmp_path / "home"),
              "--repo-root", str(tmp_path), "--tools", "shell"],
        env=env,
    )
    with anyio.fail_after(90):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.serverInfo.name == "caelza-body"
                assert "body" in (init.instructions or "")

                listed = await session.list_tools()
                assert [t.name for t in listed.tools] == ["shell_run"]
                assert listed.tools[0].annotations.destructiveHint is True

                ok = await session.call_tool("shell_run", {"cmd": "echo caelza-body-ok"})
                assert ok.isError is False
                assert "caelza-body-ok" in ok.content[0].text

                # Input validation happens server-side, before the Body runs anything.
                bad = await session.call_tool("shell_run", {})
                assert bad.isError is True

                unknown = await session.call_tool("sensors_battery", {})
                assert unknown.isError is True
