"""caelza-body: the Caelza Body as an MCP server.

The Runtime (``caelza``) spawns this over stdio and gets the Body's tools:
sensors (camera, mic, location, notifications, TTS, clipboard, battery,
torch), ADB control of this phone and paired phones, ``shell_run``, the
web tools and the self-modification tools. The Airframe safety semantics stay
inside the Body: dangerous device ops require a ``reason``, are audit-logged
to ``$CAELZA_BODY_HOME/logs/device-actions.log`` and snapshot the package
list before any removal. The Runtime's approval policy adds a second gate on
top (``body/caelza-body.example.toml``).

    caelza-body serve        # stdio MCP server (what the Runtime runs)
    caelza-body list-tools   # JSON of every tool, its schema and safety hints
    caelza-body probe        # register everything; exit 0 if the Body is sane

In ``serve`` mode stdout is the MCP transport, so nothing here (or in the tool
modules this loads) may print to stdout. Diagnostics go to stderr.

The tool modules are the same ones the Python agent loop uses, so the two can
run side by side on one phone while the Runtime takes over the turn.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from caelza_body.agent import config as _config
from caelza_body.agent import tools
from caelza_body.agent.tools import device, media, selfmod, sensors, shell, web

SERVER_NAME = "caelza-body"
SERVER_VERSION = "0.1.0"
INSTRUCTIONS = (
    "This server is the agent's body: a phone (and any paired phones) reached "
    "through Termux. 'self' always means the phone this server runs on. "
    "Tools marked DANGEROUS change device state; they need a `reason`, which "
    "is written to the Body's audit log, and removals snapshot the package "
    "list first. Screenshots and photos come back as image content and are "
    "also saved under the Body's tmp dir, whose path is in the text result."
)

#: Tool groups, in registration order. ``--tools`` selects a subset.
GROUPS = ("selfmod", "sensors", "shell", "device", "web")

#: Pure reads. readOnlyHint=True, idempotentHint=True; the natural
#: ``auto_approve`` list for the Runtime.
READ_ONLY = frozenset({
    "device_list", "device_packages", "device_logcat", "device_settings",
    "device_ui_dump", "device_screencap",
    "sensors_battery", "sensors_notifications", "sensors_clipboard_get",
    "sensors_location",
    "self_read_file", "self_list_tree",
    "web_search", "web_read", "web_map", "web_crawl_result",
})

#: Changes device or repo state in ways the agent cannot undo on its own, or
#: runs arbitrary commands. destructiveHint=True; the ``always_ask`` list.
DESTRUCTIVE = frozenset({
    "device_uninstall", "device_disable", "device_settings_put", "device_appops",
    "device_pair", "device_unpair", "device_shell",
    "shell_run",
    "self_write_file", "self_commit", "self_request_restart",
})

#: Acts on the world but is reversible or self-contained (a capture, a tap,
#: speaking, running the test suite). Neither hint is set.
NEUTRAL = frozenset({
    "device_input",
    "sensors_camera_photo", "sensors_mic_record", "sensors_tts_speak",
    "sensors_clipboard_set", "sensors_torch",
    "self_run_tests",
    "web_crawl",
})

#: One tool per group whose absence means the group failed to register.
PROBE_TOOL = {
    "selfmod": "self_read_file",
    "sensors": "sensors_battery",
    "shell": "shell_run",
    "device": "device_list",
    "web": "web_search",
}

log = logging.getLogger(SERVER_NAME)


@dataclass(frozen=True)
class BodySettings:
    """What the server needs from ``$CAELZA_BODY_HOME/config.toml``: the state
    dir, the repo root (for the self-modification tools) and the optional web
    API keys. Unlike the agent loop it does not need Telegram or a model."""
    body_home: Path
    repo_root: Path
    firecrawl_api_key: str = ""
    tavily_api_key: str = ""
    searchapi_api_key: str = ""


def load_settings(body_home: Path | str | None = None,
                  repo_root: Path | str | None = None) -> BodySettings:
    home = Path(body_home) if body_home else _config.resolve_home()
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]
    keys = {"firecrawl_api_key": "", "tavily_api_key": "", "searchapi_api_key": ""}
    cfg_path = home / "config.toml"
    if cfg_path.is_file():
        try:
            data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as e:
            log.warning("ignoring unreadable %s: %s", cfg_path, e)
            data = {}
        for section in ("firecrawl", "tavily", "searchapi"):
            block = data.get(section)
            if isinstance(block, dict):
                keys[f"{section}_api_key"] = str(block.get("api_key") or "")
    return BodySettings(body_home=home, repo_root=root, **keys)


def register_tools(settings: BodySettings, groups=GROUPS) -> list[str]:
    """(Re)build the tool registry for ``groups``. Returns the registered names."""
    unknown = sorted(set(groups) - set(GROUPS))
    if unknown:
        raise ValueError(f"unknown tool group(s) {unknown}; choose from {', '.join(GROUPS)}")
    tools.reset()
    settings.body_home.mkdir(parents=True, exist_ok=True)
    if "selfmod" in groups:
        selfmod.configure(settings.repo_root, settings.body_home)
        selfmod.register()
    if "sensors" in groups:
        sensors.configure(settings.body_home)
        sensors.register()
    if "shell" in groups:
        shell.register()
    if "device" in groups:
        device.configure(settings.body_home)
        device.register()
    if "web" in groups:
        web.configure(settings.body_home, settings.firecrawl_api_key,
                      settings.tavily_api_key, settings.searchapi_api_key)
        web.register()
    return sorted(tools.REGISTRY)


def annotations_for(name: str) -> types.ToolAnnotations:
    read_only = name in READ_ONLY
    return types.ToolAnnotations(
        readOnlyHint=read_only,
        destructiveHint=name in DESTRUCTIVE,
        idempotentHint=read_only,
        openWorldHint=name.startswith("web_") or name == "sensors_location",
    )


def mcp_tools() -> list[types.Tool]:
    """The registry's OpenAI-style function specs as MCP tools. The JSON
    schemas are passed through untouched, so `reason` stays required where
    the Body requires it."""
    out: list[types.Tool] = []
    for spec in tools.schemas():
        fn = spec["function"]
        out.append(types.Tool(
            name=fn["name"],
            description=fn["description"],
            inputSchema=fn["parameters"],
            annotations=annotations_for(fn["name"]),
        ))
    return out


_lock: anyio.Lock | None = None


def _call_lock() -> anyio.Lock:
    global _lock
    if _lock is None:
        _lock = anyio.Lock()
    return _lock


def _image_blocks(path: str, mime: str) -> list[types.TextContent | types.ImageContent]:
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        return [types.TextContent(type="text", text=f"image at {path} could not be read: {e}")]
    return [
        types.ImageContent(type="image", data=base64.b64encode(data).decode("ascii"),
                           mimeType=mime),
        types.TextContent(type="text", text=f"image saved at {path} ({mime}, {len(data)} bytes)"),
    ]


async def call_tool(name: str, arguments: dict | None) -> types.CallToolResult:
    """Dispatch one call through the registry.

    The tool functions are synchronous and block on subprocesses (adb,
    termux-api, shell) for up to minutes, so they run on a worker thread.
    Calls are serialized: the Body is one phone, and the image hand-off
    (``emit_image`` → ``PENDING_MEDIA``) is per call, not per request.
    """
    args = dict(arguments or {})
    async with _call_lock():
        media.drain()  # anything a failed earlier call left behind is not ours
        text = await anyio.to_thread.run_sync(tools.dispatch, name, args)
        images = media.drain()
    content: list[types.TextContent | types.ImageContent] = [
        types.TextContent(type="text", text=text)]
    for path, mime in images:
        content.extend(_image_blocks(path, mime))
    return types.CallToolResult(content=content, isError=text.startswith("error:"))


def build_server() -> Server:
    server = Server(SERVER_NAME, version=SERVER_VERSION, instructions=INSTRUCTIONS)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return mcp_tools()

    @server.call_tool(validate_input=True)
    async def _call_tool(name: str, arguments: dict | None) -> types.CallToolResult:
        return await call_tool(name, arguments)

    return server


async def serve_stdio(server: Server) -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def probe(names: list[str], groups, settings: BodySettings) -> int:
    """Exit 0 when every requested group registered and every schema converts.
    Prints one JSON line (this is not the transport)."""
    missing = [PROBE_TOOL[g] for g in groups if PROBE_TOOL[g] not in names]
    if missing:
        print(json.dumps({"ok": False, "missing": missing}))
        return 1
    specs = mcp_tools()
    print(json.dumps({"ok": True, "tools": len(specs), "home": str(settings.body_home),
                      "groups": list(groups)}))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="caelza-body",
        description="The Caelza Body as an MCP server (stdio).")
    p.add_argument("command", nargs="?", choices=("serve", "list-tools", "probe"),
                   default="serve")
    p.add_argument("--home", type=Path, default=None,
                   help="Body state dir (default: $CAELZA_BODY_HOME, else ~/.caelza-body)")
    p.add_argument("--repo-root", type=Path, default=None,
                   help="the Body checkout the self_* tools edit (default: this package's repo)")
    p.add_argument("--tools", default=",".join(GROUPS),
                   help=f"comma-separated groups to expose (default: all of {', '.join(GROUPS)})")
    a = p.parse_args(argv)
    groups = tuple(g.strip() for g in a.tools.split(",") if g.strip())

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    settings = load_settings(a.home, a.repo_root)
    try:
        names = register_tools(settings, groups)
    except ValueError as e:
        p.error(str(e))

    if a.command == "list-tools":
        print(json.dumps([t.model_dump(mode="json", exclude_none=True) for t in mcp_tools()],
                         indent=2))
        return 0
    if a.command == "probe":
        return probe(names, groups, settings)

    print(f"{SERVER_NAME} {SERVER_VERSION}: {len(names)} tools ({','.join(groups)}), "
          f"home={settings.body_home}", file=sys.stderr, flush=True)
    anyio.run(serve_stdio, build_server())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
