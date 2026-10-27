"""Many bodies, one mind: the Body over HTTP, and reaching other Bodies.

Deployment shape 2 (vision §3): the Runtime and the Mind run on a hub; each
phone runs its own Body. Two pieces make that one fleet:

- **Serving.** ``caelza-body serve --http`` puts the Body's MCP server on
  Streamable HTTP (the same transport the Runtime's ``transport = "http"``
  speaks) behind a bearer token, bound to loopback unless told otherwise
  (a Tailscale address is the intended "otherwise"). ``/health`` answers
  unauthenticated with the server's name so a hub can tell reachability from
  a bad token.

- **Reaching.** A Body registers another Body as a device (``device_join``,
  or ``caelza-body fleet join``): a registry entry with the remote's URL and a
  token file. From then on every tool call whose ``device`` names that entry
  is forwarded to the remote Body as a call on *its* ``self`` (``forward``),
  images included. The address space does not change: ``device`` is
  ``self``, an ADB-paired phone, or a joined Body, and the playbooks, the
  dashboard and the risk profile do not care which.

The forwarding hook sits in ``caelza_body.agent.tools.dispatch`` so the stdio
server, the HTTP server and the Python agent loop all get it. Nothing here
is imported by the tools at module level; ``forward`` looks the registry up
through ``caelza_body.agent.tools.device`` when called.
"""
from __future__ import annotations

import base64
import contextlib
import hmac
import json
import logging
import mimetypes
import os
import secrets
import time
from pathlib import Path

import anyio
import httpx

log = logging.getLogger("caelza-body.fleet")

#: The MCP endpoint path the HTTP server mounts and the hub's URLs end with.
MCP_PATH = "/mcp"
HEALTH_PATH = "/health"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 42618
TOKEN_FILE = "run/http-token"
#: Tool names forwarded to a remote Body that this Body audit-logs as well.
FLEET_LOG = "logs/fleet.log"
#: Per-call budget when reaching a remote Body (mic recordings take 60 s).
REMOTE_TIMEOUT = 150.0


# ---------------------------------------------------------------------------
# The bearer token
# ---------------------------------------------------------------------------

def token_path(body_home: Path | str) -> Path:
    return Path(body_home) / TOKEN_FILE


def fresh_token(generate=secrets.token_urlsafe) -> str:
    """A new bearer token that starts with a letter or digit, so it can be
    pasted after `--token` on a command line (a leading `-` reads as an
    option; `_` is kept out too for the same eye)."""
    while True:
        token = generate(32)
        if token and token[0] not in "-_":
            return token


def write_secret(path: Path | str, text: str) -> Path:
    """Write a token file nobody else can read, from its first byte: the
    directory 0700, the file created 0600 rather than written and then
    chmodded (an existing file is re-moded too)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    for target, mode in ((p.parent, 0o700),):
        try:
            target.chmod(mode)
        except OSError:
            pass
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return p


def load_or_create_token(path: Path | str) -> str:
    """The token in ``path``, created (0600) when the file is missing."""
    p = Path(path)
    if p.is_file():
        token = p.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = fresh_token()
    write_secret(p, token + "\n")
    return token


def read_token(path: Path | str) -> str:
    return Path(path).read_text(encoding="utf-8").strip()


def bearer_ok(header: str | None, token: str) -> bool:
    """`Authorization: Bearer <token>` against the token, in constant time.
    Non-ASCII (headers arrive latin-1 decoded) is a plain refusal, not the
    `TypeError` `compare_digest` raises for it."""
    if not header or not header.startswith("Bearer "):
        return False
    candidate = header[len("Bearer "):].strip()
    if not candidate or not candidate.isascii() or not token.isascii():
        return False
    return hmac.compare_digest(candidate, token)


# ---------------------------------------------------------------------------
# Serving the Body over HTTP
# ---------------------------------------------------------------------------

def allowed_hosts_for(host: str, port: int, extra=()) -> list[str]:
    """The Host headers the server accepts (DNS-rebinding protection): the
    bind address, loopback, and whatever the operator adds (a MagicDNS name)."""
    hosts = [f"{host}:{port}", host, f"127.0.0.1:{port}", "127.0.0.1", f"localhost:{port}", "localhost"]
    for h in extra:
        h = str(h).strip()
        if h and h not in hosts:
            hosts.append(h)
            if ":" not in h:
                hosts.append(f"{h}:{port}")
    return hosts


def build_app(server, token: str, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, allow_hosts=()):
    """A Starlette app: ``/mcp`` (bearer token, Streamable HTTP) and
    ``/health`` (no auth: name, version, tool count)."""
    import contextlib

    from mcp.server.streamable_http import TransportSecuritySettings
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route

    from caelza_body.agent import tools

    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts_for(host, port, allow_hosts),
    )
    manager = StreamableHTTPSessionManager(app=server, security_settings=security)

    class McpEndpoint:
        """The MCP endpoint as a raw ASGI app (a `Route`, not a `Mount`, so
        `/mcp` is served as-is with no trailing-slash redirect): the bearer
        token first, then the session manager."""

        async def __call__(self, scope, receive, send):
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            if not bearer_ok(headers.get("authorization"), token):
                await Response("unauthorized", status_code=401, media_type="text/plain")(scope, receive, send)
                return
            await manager.handle_request(scope, receive, send)

    async def health(_request):
        return JSONResponse({"ok": True, "name": "caelza-body", "tools": len(tools.REGISTRY), "mcp": MCP_PATH})

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with manager.run():
            yield

    return Starlette(
        routes=[Route(HEALTH_PATH, health, methods=["GET"]), Route(MCP_PATH, McpEndpoint())],
        lifespan=lifespan,
    )


def serve_http(server, token: str, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, allow_hosts=()) -> None:
    """Run the Body on HTTP until interrupted. Blocks."""
    import uvicorn

    app = build_app(server, token, host=host, port=port, allow_hosts=allow_hosts)
    uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)


# ---------------------------------------------------------------------------
# Reaching a remote Body
# ---------------------------------------------------------------------------

class RemoteBody:
    """One remote Body: its MCP URL and bearer token. Every call opens its own
    session (initialize, call, close), which survives the remote restarting."""

    def __init__(self, url: str, token: str, timeout: float = REMOTE_TIMEOUT):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def health_url(self) -> str:
        base = self.url[: -len(MCP_PATH)] if self.url.endswith(MCP_PATH) else self.url
        return base + HEALTH_PATH

    def health(self, timeout: float = 4.0) -> dict | None:
        """``/health`` as a dict, or None when the remote does not answer."""
        try:
            r = httpx.get(self.health_url(), timeout=timeout)
            if r.status_code != 200:
                return None
            data = r.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    @contextlib.asynccontextmanager
    async def _connect(self):
        """An initialised `ClientSession` on the remote, closed on exit."""
        import mcp.client.streamable_http as sh
        from mcp import ClientSession

        if hasattr(sh, "streamable_http_client"):
            timeout = httpx.Timeout(self.timeout, connect=10.0)
            async with sh.create_mcp_http_client(headers=self.headers, timeout=timeout) as http_client:
                async with sh.streamable_http_client(self.url, http_client=http_client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        init = await session.initialize()
                        yield session, init
        else:  # pragma: no cover - older SDKs
            async with sh.streamablehttp_client(self.url, headers=self.headers, timeout=self.timeout,
                                                sse_read_timeout=self.timeout) as (read, write, _):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    yield session, init

    async def _probe(self) -> dict:
        async with self._connect() as (session, init):
            listed = await session.list_tools()
            return {
                "name": init.serverInfo.name,
                "version": init.serverInfo.version,
                "tools": sorted(t.name for t in listed.tools),
            }

    def probe(self) -> dict:
        """Initialize and list tools; raises when the remote is not a Body."""
        info = anyio.run(self._probe)
        if info.get("name") != "caelza-body":
            raise ValueError(f"{self.url} is an MCP server named {info.get('name')!r}, not a Caelza Body")
        return info

    async def _call(self, name: str, args: dict) -> tuple[str, list[tuple[bytes, str]], bool]:
        async with self._connect() as (session, _init):
            result = await session.call_tool(name, args)
        texts: list[str] = []
        images: list[tuple[bytes, str]] = []
        for block in result.content:
            kind = getattr(block, "type", None)
            if kind == "text":
                texts.append(block.text)
            elif kind == "image":
                images.append((base64.b64decode(block.data), block.mimeType))
        return "\n".join(texts), images, bool(result.isError)

    def call(self, name: str, args: dict) -> tuple[str, list[tuple[bytes, str]], bool]:
        """``(text, [(bytes, mime)], is_error)`` for one tool call."""
        return anyio.run(self._call, name, args)


def remote_for(entry: dict, timeout: float = REMOTE_TIMEOUT) -> RemoteBody:
    return RemoteBody(entry["url"], read_token(entry["token_file"]), timeout=timeout)


# ---------------------------------------------------------------------------
# Forwarding
# ---------------------------------------------------------------------------

def _registry():
    from caelza_body.agent.tools import device
    return device.registry


def _body_home() -> Path | None:
    from caelza_body.agent.tools import device
    return device._BODY_HOME


def remote_entry(name: str) -> dict | None:
    """The registry entry when ``name`` is a joined Body; else None."""
    if not name or name == "self":
        return None
    registry = _registry()
    if registry is None:
        return None
    entry = registry.get(name)
    if entry and entry.get("url"):
        return entry
    return None


def _save_images(name: str, images: list[tuple[bytes, str]]) -> None:
    from caelza_body.agent.tools.media import emit_image

    home = _body_home()
    if home is None:
        return
    tmp = home / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    for data, mime in images:
        ext = mimetypes.guess_extension(mime or "") or ".bin"
        path = tmp / f"remote-{name}-{time.time_ns()}{ext}"
        path.write_bytes(data)
        emit_image(str(path), mime)


#: Arguments the audit line never shows: a joined Body's token, a pairing code.
SECRET_ARGS = frozenset({"token", "code", "password", "secret"})


def _log_forward(name: str, tool: str, args: dict, outcome: str) -> None:
    from caelza_body import mcp_server

    if tool not in mcp_server.DESTRUCTIVE:
        return
    home = _body_home()
    if home is None:
        return
    logf = home / FLEET_LOG
    logf.parent.mkdir(parents=True, exist_ok=True)
    shown = {k: ("<redacted>" if k in SECRET_ARGS else v) for k, v in args.items() if k != "device"}
    with logf.open("a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')}\t{name}\t{tool}\t{json.dumps(shown)}\t{outcome}\n")


def takes_device(tool: str) -> bool:
    """Does this tool's schema have a `device` argument? Only those are
    forwarded: `device_join(..., device="grandma")` names no phone to run
    on, it is a stray argument, and the call stays local (where the schema
    check refuses it) instead of carrying a token across the fleet."""
    from caelza_body.agent import tools

    schema = tools._SCHEMAS.get(tool) or {}
    return "device" in schema.get("function", {}).get("parameters", {}).get("properties", {})


def leaf_exception(e: BaseException) -> BaseException:
    """The first real error inside anyio's exception groups, so the model
    reads `ConnectError: connection refused` rather than `ExceptionGroup:
    unhandled errors in a TaskGroup`."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    return e


def forward(tool: str, args: dict, remote_factory=remote_for) -> str | None:
    """Forward ``tool(args)`` to the Body that ``args['device']`` names, as a
    call on that Body's own phone. None when the call is local (no ``device``,
    ``self``, an ADB-paired phone, or a tool that takes no ``device``)."""
    device = args.get("device")
    if not isinstance(device, str) or not takes_device(tool):
        return None
    entry = remote_entry(device)
    if entry is None:
        return None
    remote_args = {k: v for k, v in args.items() if k != "device"}
    remote_args["device"] = "self"
    try:
        remote = remote_factory(entry)
        text, images, is_error = remote.call(tool, remote_args)
    except Exception as e:  # noqa: BLE001 - a dead remote is a result, not a crash
        cause = leaf_exception(e)
        _log_forward(device, tool, args, f"unreachable: {type(cause).__name__}")
        return f"error: {device!r} ({entry['url']}) did not answer: {type(cause).__name__}: {cause}"
    _save_images(device, images)
    _log_forward(device, tool, args, "error" if is_error else "ok")
    if is_error and not text.startswith("error:"):
        text = "error: " + (text or "remote call failed")
    return text


def reachability(entry: dict, remote_factory=remote_for) -> bool:
    try:
        return remote_factory(entry).health() is not None
    except Exception:  # noqa: BLE001
        return False
