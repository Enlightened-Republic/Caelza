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
    caelza-body serve --http # the same over Streamable HTTP + bearer token, for
                             # a hub Runtime or another Body across Tailscale
    caelza-body fleet        # the phones this Body reaches; join / forget / tag
    caelza-body runtime      # the Runtime binary under the supervisor's guard:
                             # status / update (fetch, verify, probe, swap) / rollback / link
    caelza-body list-tools   # JSON of every tool, its schema and safety hints
    caelza-body probe        # register everything; exit 0 if the Body is sane
    caelza-body playbooks    # the phone playbooks (body/sops); --install copies
                             # them into the Runtime's sops dir

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
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from caelza_body import fleet
from caelza_body import runtime_guard
from caelza_body.agent import config as _config
from caelza_body.agent import playbooks
from caelza_body.agent import tools
from caelza_body.agent.tools import device, media, playbook, selfmod, sensors, shell, web

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

#: Tool groups, in registration order. ``--tools`` selects a subset. The
#: playbook reads (``device_debloat_plan``, ``device_suspects``,
#: ``device_foreground``, ``device_health``) belong to ``device``.
GROUPS = ("selfmod", "sensors", "shell", "device", "web")

#: Where the Runtime loads SOPs from when ``[sop] sops_dir = "shared/sops"``
#: (relative to the directory holding its config.toml).
DEFAULT_SOPS_DIR = "~/.caelza/shared/sops"

#: Pure reads. readOnlyHint=True, idempotentHint=True; the natural
#: ``auto_approve`` list for the Runtime.
READ_ONLY = frozenset({
    "device_list", "device_packages", "device_logcat", "device_settings",
    "device_ui_dump", "device_screencap",
    "device_debloat_plan", "device_suspects", "device_foreground", "device_health",
    "sensors_battery", "sensors_notifications", "sensors_clipboard_get",
    "sensors_location",
    "self_read_file", "self_list_tree",
    "web_search", "web_read", "web_map", "web_crawl_result",
})

#: Changes device or repo state in ways the agent cannot undo on its own, or
#: runs arbitrary commands. destructiveHint=True; the ``always_ask`` list.
DESTRUCTIVE = frozenset({
    "device_uninstall", "device_disable", "device_settings_put", "device_appops",
    "device_pair", "device_unpair", "device_join", "device_shell",
    "shell_run",
    "self_write_file", "self_commit", "self_request_restart",
})

#: Acts on the world but is reversible or self-contained (a capture, a tap,
#: speaking, running the test suite). Neither hint is set.
NEUTRAL = frozenset({
    "device_input", "device_tag",
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
        playbook.register()
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


def list_playbooks(settings: BodySettings, install: str | None, force: bool) -> int:
    """Print the shipped playbooks (name, version, steps, gates, the tools they
    use); with ``install`` copy them into that directory. Exit 1 when the
    checkout ships none (wrong ``--repo-root``)."""
    shipped = playbooks.shipped_playbooks(settings.repo_root)
    if not shipped:
        print(f"no playbooks under {playbooks.shipped_root(settings.repo_root)}", file=sys.stderr)
        return 1
    for pb in shipped:
        gates = ", ".join(str(n) for n in pb.gates) or "none"
        print(f"{pb.name} v{pb.version}: {pb.description}")
        print(f"  {len(pb.steps)} steps, gates at {gates}; agent {pb.agent or '-'}; "
              f"tools {', '.join(sorted(pb.tools)) or '-'}")
    if install is not None:
        dest = Path(install).expanduser()
        for name, status in playbooks.install_playbooks(settings.repo_root, dest, force=force):
            print(f"{status:>9}  {dest / name}")
        print("Runtime: set [sop] sops_dir = \"shared/sops\" (runtime/caelza.phone.example.toml) "
              "and restart the daemon; the Procedures page lists them.")
    return 0


def fleet_command(a, settings: BodySettings) -> int:
    """`caelza-body fleet [list|join|forget|tag]`: the registry through the
    same tools the agent uses, so the CLI and the agent agree."""
    if a.action == "list":
        listed = json.loads(tools.dispatch("device_list", {}))
        for name, row in listed.items():
            where = row.get("url") or row.get("host") or "this phone"
            groups = ", ".join(row.get("groups") or []) or "-"
            state = "reachable" if row.get("reachable") else "unreachable"
            print(f"{name:<16} {row.get('kind', '?'):<5} {state:<11} groups {groups:<20} {where}")
        return 0
    if not a.name:
        print(f"fleet {a.action} needs a device name", file=sys.stderr)
        return 2
    if a.action == "join":
        if not a.url or not (a.token or a.token_file):
            print("fleet join needs --url and --token (or --token-file)", file=sys.stderr)
            return 2
        token = a.token or fleet.read_token(a.token_file)
        out = tools.dispatch("device_join", {"name": a.name, "url": a.url, "token": token,
                                             "groups": a.groups, "notes": a.notes})
    elif a.action == "forget":
        out = tools.dispatch("device_unpair", {"name": a.name})
    else:
        out = tools.dispatch("device_tag", {"name": a.name, "groups": a.groups})
    print(out)
    return 1 if out.startswith("error:") else 0


def runtime_command(a, settings: BodySettings) -> int:
    """`caelza-body runtime [status|update|rollback|link]` over `runtime_guard`."""
    home = settings.body_home
    if a.action == "status":
        print(json.dumps(runtime_guard.status(home), indent=2))
        return 0
    if a.action == "rollback":
        rolled = runtime_guard.rollback(home)
        if rolled:
            runtime_guard.request_restart(home, "rolled back by hand", rolled)
            print(f"current -> {rolled}; the supervisor restarts the Runtime on it")
            return 0
        print("nothing to roll back to: no last-good other than current", file=sys.stderr)
        return 1
    if a.action == "link":
        link = runtime_guard.link_into_path(home, a.bindir)
        if link is None:
            print("no runtime installed, or no $PREFIX/bin to link into (pass --bindir)", file=sys.stderr)
            return 1
        print(f"{link} -> {os.readlink(link)}")
        if runtime_guard.defer_boot_script() == "patched":
            print("the Termux:Boot script now leaves the Runtime to the supervisor")
        return 0
    if a.tag and a.archive:
        print("--tag and --archive do not go together: the archive is the release", file=sys.stderr)
        return 2
    token = a.token or os.environ.get("GITHUB_TOKEN")
    try:
        result = runtime_guard.update(home, repo=a.repo, target=a.target, tag=a.tag, token=token,
                                      archive=a.archive, config_dir=a.config_dir, port=a.probe_port,
                                      timeout=a.probe_timeout, log=lambda m: print(m, file=sys.stderr))
    except Exception as e:  # noqa: BLE001 - the reason is the answer
        print(f"update failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result.get("promoted") or result.get("detail") == "already current" else 1


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", type=Path, default=None,
                        help="Body state dir (default: $CAELZA_BODY_HOME, else ~/.caelza-body)")
    common.add_argument("--repo-root", type=Path, default=None,
                        help="the Body checkout the self_* tools edit (default: this package's repo)")
    common.add_argument("--tools", default=",".join(GROUPS),
                        help=f"comma-separated groups to expose (default: all of {', '.join(GROUPS)})")

    p = argparse.ArgumentParser(prog="caelza-body",
                                description="The Caelza Body as an MCP server (stdio, or HTTP for a fleet).")
    sub = p.add_subparsers(dest="command")
    serve = sub.add_parser("serve", parents=[common], help="serve the Body's tools over MCP")
    serve.add_argument("--http", action="store_true",
                       help="Streamable HTTP with a bearer token instead of stdio (a hub reaches this phone)")
    serve.add_argument("--host", default=fleet.DEFAULT_HOST,
                       help=f"bind address for --http (default {fleet.DEFAULT_HOST}; use the phone's Tailscale address for a hub)")
    serve.add_argument("--port", type=int, default=fleet.DEFAULT_PORT, help=f"port for --http (default {fleet.DEFAULT_PORT})")
    serve.add_argument("--token-file", type=Path, default=None,
                       help=f"bearer token file for --http (default <home>/{fleet.TOKEN_FILE}, created when missing)")
    serve.add_argument("--allow-host", action="append", default=[], metavar="HOST",
                       help="an extra Host header to accept (a MagicDNS name); repeatable")
    sub.add_parser("list-tools", parents=[common], help="every tool, its schema and safety hints, as JSON")
    sub.add_parser("probe", parents=[common], help="register everything; exit 0 if the Body is sane")
    pb = sub.add_parser("playbooks", parents=[common], help="the phone playbooks (body/sops)")
    pb.add_argument("--install", metavar="DIR", nargs="?", const=DEFAULT_SOPS_DIR, default=None,
                    help=f"copy the shipped SOPs into DIR (default {DEFAULT_SOPS_DIR}); "
                         "a copy you edited is kept unless --force")
    pb.add_argument("--force", action="store_true",
                    help="with --install: overwrite copies that differ from the shipped ones")
    fl = sub.add_parser("fleet", parents=[common], help="the phones this Body reaches")
    fl.add_argument("action", nargs="?", choices=("list", "join", "forget", "tag"), default="list")
    fl.add_argument("name", nargs="?", help="the device name for join / forget / tag")
    fl.add_argument("--url", help="join: the remote Body's MCP URL (http://<tailscale-ip>:42618/mcp)")
    fl.add_argument("--token", help="join: the remote's bearer token (write --token=<token> if it starts with a dash)")
    fl.add_argument("--token-file", type=Path, help="join: read the token from this file instead")
    fl.add_argument("--groups", default="", help="join / tag: comma-separated groups")
    fl.add_argument("--notes", default="", help="join: a note for the registry")
    rt = sub.add_parser("runtime", parents=[common], help="the Runtime binary under the supervisor's guard")
    rt.add_argument("action", nargs="?", choices=("status", "update", "rollback", "link"), default="status")
    rt.add_argument("--tag", help="update: a release tag (default: the latest release)")
    rt.add_argument("--repo", default=runtime_guard.DEFAULT_REPO, help="update: the GitHub repo with the releases")
    rt.add_argument("--target", default=None, help=f"update: the release target (default for this machine: {runtime_guard.default_target()})")
    rt.add_argument("--token", default=None, help="update: a GitHub token for a private repo (default $GITHUB_TOKEN)")
    rt.add_argument("--archive", type=Path, default=None, help="update: install this release tarball instead of fetching one")
    rt.add_argument("--config-dir", type=Path, default=None, help="update: the Runtime's config dir to probe with and snapshot (default ~/.caelza)")
    rt.add_argument("--probe-port", type=int, default=runtime_guard.PROBE_PORT, help="update: the port the probe gateway listens on")
    rt.add_argument("--probe-timeout", type=float, default=runtime_guard.PROBE_TIMEOUT, help="update: seconds to wait for /health")
    rt.add_argument("--bindir", type=Path, default=None, help="link: the bin dir to put the caelza symlink in (default $PREFIX/bin)")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-"):
        argv.insert(0, "serve")  # `caelza-body` alone serves, as it always did
    p = build_parser()
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
    if a.command == "playbooks":
        return list_playbooks(settings, a.install, a.force)
    if a.command == "fleet":
        return fleet_command(a, settings)
    if a.command == "runtime":
        return runtime_command(a, settings)

    if a.http:
        token_file = a.token_file or fleet.token_path(settings.body_home)
        token = fleet.load_or_create_token(token_file)
        print(f"{SERVER_NAME} {SERVER_VERSION}: {len(names)} tools ({','.join(groups)}), "
              f"home={settings.body_home}", file=sys.stderr, flush=True)
        print(f"http://{a.host}:{a.port}{fleet.MCP_PATH}  (bearer token in {token_file}; "
              f"/health answers without it)", file=sys.stderr, flush=True)
        if a.host not in ("127.0.0.1", "localhost", "::1"):
            print("bound beyond loopback: keep this behind Tailscale or a firewall; "
                  "the token is the only lock", file=sys.stderr, flush=True)
        fleet.serve_http(build_server(), token, host=a.host, port=a.port, allow_hosts=a.allow_host)
        return 0

    print(f"{SERVER_NAME} {SERVER_VERSION}: {len(names)} tools ({','.join(groups)}), "
          f"home={settings.body_home}", file=sys.stderr, flush=True)
    anyio.run(serve_stdio, build_server())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
