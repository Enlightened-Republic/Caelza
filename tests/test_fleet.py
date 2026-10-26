"""M6 fleet: the Body over HTTP, and reaching other Bodies.

A remote Body is a real `caelza-body serve --http` subprocess with the
recorded phone (`tests/fixtures/playbooks/adb.py`) as its adb; the hub side
is this process's own registry and tools. Between them: the bearer token,
`/health`, the MCP round trip, `device_join`, forwarding by device name
(images and the audit line included), groups, and the `fleet` CLI.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from caelza_body import fleet
from caelza_body import mcp_server as srv
from caelza_body.agent import tools
from caelza_body.agent.devices import DeviceRegistry
from caelza_body.agent.tools import device, media

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "playbooks"
SNAPSHOT = REPO_ROOT / "docs" / "examples" / "revvl-7-debloat" / "packages-snapshot.txt"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def recorded_adb(tmp_path, monkeypatch):
    """The recorded phone on PATH as `adb`, for this process and for children."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "adb"
    shutil.copy(FIXTURES / "adb.py", fake)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CAELZA_FIXTURES", str(FIXTURES))
    monkeypatch.setenv("CAELZA_SNAPSHOT", str(SNAPSHOT))
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    return tmp_path


@pytest.fixture
def remote(recorded_adb):
    """A phone running its own Body over HTTP, with the recorded adb."""
    port = free_port()
    home = recorded_adb / "remote-home"
    log = (recorded_adb / "remote.log").open("w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "caelza_body.mcp_server", "serve", "--http", "--port", str(port),
         "--home", str(home), "--repo-root", str(recorded_adb), "--tools", "device,sensors"],
        stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ))
    url = f"http://127.0.0.1:{port}{fleet.MCP_PATH}"
    health = f"http://127.0.0.1:{port}{fleet.HEALTH_PATH}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            log.close()
            raise RuntimeError("remote Body exited:\n" + (recorded_adb / "remote.log").read_text())
        try:
            if httpx.get(health, timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("remote Body never answered /health:\n" + (recorded_adb / "remote.log").read_text())
    token = fleet.read_token(fleet.token_path(home))
    yield {"url": url, "health": health, "token": token, "home": home, "port": port}
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.close()


@pytest.fixture
def hub(recorded_adb):
    """This process as the hub's Body: device + sensors tools over a fresh home."""
    home = recorded_adb / "hub-home"
    settings = srv.load_settings(home, recorded_adb)
    srv.register_tools(settings, ("device", "sensors"))
    yield home
    tools.reset()


def call(tool, **args):
    out = tools.dispatch(tool, args)
    return json.loads(out) if out.startswith("{") else out


# --- the token and the server --------------------------------------------------

def test_token_is_created_once_and_private(tmp_path):
    path = tmp_path / "run" / "http-token"
    first = fleet.load_or_create_token(path)
    assert len(first) >= 40 and path.read_text().strip() == first
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert fleet.load_or_create_token(path) == first
    assert fleet.read_token(path) == first
    assert fleet.bearer_ok(f"Bearer {first}", first)
    assert not fleet.bearer_ok(f"Bearer {first}x", first)
    assert not fleet.bearer_ok(first, first) and not fleet.bearer_ok(None, first)


def test_a_fresh_token_never_starts_with_a_dash_or_underscore():
    """`--token <token>` on the command line: a leading `-` would read as an
    option (CI met `-e-F9…` and argparse refused it)."""
    draws = iter(["-e-F9Mx86mZOdg1QkBQOb23vJSg9ZLOs1-60dadn3T0", "_underscored", "", "Ok3Ltoken"])
    assert fleet.fresh_token(generate=lambda n: next(draws)) == "Ok3Ltoken"
    for _ in range(64):
        assert fleet.fresh_token()[0] not in "-_"
    # The CLI still takes an awkward token in the `--token=` form.
    a = srv.build_parser().parse_args(["fleet", "join", "phone", "--url", "http://x/mcp", "--token=-starts-with-dash"])
    assert a.token == "-starts-with-dash"


def test_allowed_hosts_cover_the_bind_address_loopback_and_extras():
    hosts = fleet.allowed_hosts_for("100.64.0.9", 42618, ["niba.tail.ts.net"])
    assert "100.64.0.9:42618" in hosts and "127.0.0.1:42618" in hosts and "localhost" in hosts
    assert "niba.tail.ts.net" in hosts and "niba.tail.ts.net:42618" in hosts


def test_health_is_open_and_mcp_is_locked(remote):
    h = httpx.get(remote["health"], timeout=5).json()
    assert h["ok"] is True and h["name"] == "caelza-body" and h["tools"] > 10 and h["mcp"] == "/mcp"
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    assert httpx.post(remote["url"], json=body, timeout=5).status_code == 401
    bad = {"Authorization": "Bearer nope", "Accept": "application/json, text/event-stream"}
    assert httpx.post(remote["url"], json=body, headers=bad, timeout=5).status_code == 401


def test_a_remote_body_answers_the_mcp_round_trip(remote):
    rb = fleet.RemoteBody(remote["url"], remote["token"])
    assert rb.health_url() == remote["health"] and rb.health()["name"] == "caelza-body"
    info = rb.probe()
    assert info["name"] == "caelza-body" and "device_health" in info["tools"] and "sensors_battery" in info["tools"]
    assert "shell_run" not in info["tools"], "the remote was started with --tools device,sensors"
    text, images, is_error = rb.call("device_health", {"device": "self"})
    assert not is_error and images == []
    assert json.loads(text)["identity"]["model"] == "TMRV075G"
    text, _, is_error = rb.call("device_health", {"device": "nope"})
    assert is_error and text.startswith("error: unknown device")
    with pytest.raises(Exception):  # nothing listens on port 9: the connection error is the answer
        fleet.RemoteBody("http://127.0.0.1:9/mcp", "x", timeout=1).probe()


# --- the hub: join, forward, groups --------------------------------------------

def test_join_then_every_call_naming_the_phone_runs_there(remote, hub):
    joined = call("device_join", name="phone", url=remote["url"], token=remote["token"], groups="family, bench")
    assert joined.startswith("joined 'phone' at ") and "tools, caelza-body" in joined
    entry = device.registry.get("phone")
    assert entry["url"] == remote["url"] and entry["groups"] == ["family", "bench"]
    token_file = Path(entry["token_file"])
    assert token_file.read_text().strip() == remote["token"]
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert remote["token"] not in json.dumps(device.registry.all()), "the registry names the token file, never the token"

    # A device tool: the hub never runs adb for it; the remote does.
    health = call("device_health", device="phone")
    assert health["identity"]["model"] == "TMRV075G" and health["device"] == "self"
    # A playbook read, forwarded the same way.
    plan = call("device_debloat_plan", device="phone")
    assert plan["total"] == 301 and "com.metro.minus1" in {i["pkg"] for i in plan["remove"]}
    # A sensor: the remote's own (the recorded phone has no termux-api, which is the proof it ran there).
    out = call("sensors_battery", device="phone")
    assert out.startswith("error:") and "termux-battery-status" in out
    # The same sensor against an ADB-paired phone is refused locally in plain words.
    device.registry.add("gma", "10.0.0.5:5555", groups="family")
    local = call("sensors_battery", device="gma")
    assert local.startswith("error: sensors_battery is a sensor of this phone") and "device_join" in local
    assert call("sensors_battery", device="self").startswith("error:")  # local, no termux-api here either

    listed = call("device_list")
    assert listed["self"]["kind"] == "self"
    assert listed["phone"]["kind"] == "http" and listed["phone"]["reachable"] is True
    assert listed["phone"]["url"] == remote["url"] and listed["phone"]["groups"] == ["family", "bench"]
    assert listed["gma"]["kind"] == "adb" and listed["gma"]["host"] == "10.0.0.5:5555" and listed["gma"]["groups"] == ["family"]
    assert device.registry.groups() == {"bench": ["phone"], "family": ["gma", "phone"]}
    assert device.registry.in_group("family") == ["gma", "phone"] and device.registry.in_group("nope") == []

    assert call("device_tag", name="phone", groups="bench") == "phone: groups bench"
    assert call("device_tag", name="gma", groups="") == "gma: groups (none)"
    assert call("device_tag", name="nope", groups="x").startswith("error: unknown device")

    assert call("device_unpair", name="phone") == "unpaired 'phone'"
    assert not token_file.exists() and device.registry.get("phone") is None


def test_destructive_forwards_are_audited_on_the_hub_too(remote, hub):
    call("device_join", name="phone", url=remote["url"], token=remote["token"])
    out = call("device_disable", device="phone", pkg="com.metro.minus1", reason="test")
    assert "pm disable-user --user 0 com.metro.minus1" in out
    line = (hub / fleet.FLEET_LOG).read_text().strip().splitlines()[-1]
    assert "\tphone\tdevice_disable\t" in line and '"pkg": "com.metro.minus1"' in line and line.endswith("\tok")
    # Reads leave no audit line.
    call("device_health", device="phone")
    assert len((hub / fleet.FLEET_LOG).read_text().strip().splitlines()) == 1
    # The remote's own audit log has the action too (snapshot + reason), as if the agent ran there.
    remote_log = remote["home"] / "logs" / "device-actions.log"
    assert "device_disable\tcom.metro.minus1 (snapshot" in remote_log.read_text()


def test_join_refuses_bad_names_urls_and_silent_endpoints(hub):
    assert call("device_join", name="self", url="http://x/mcp", token="t").startswith("error: 'self' is not a device name")
    assert call("device_join", name="bad name", url="http://x/mcp", token="t").startswith("error:")
    assert call("device_join", name="p", url="x", token="t") == "error: url must start with http:// or https://, got 'x'"
    assert call("device_join", name="p", url="http://127.0.0.1:9", token=" ") == "error: token is empty"
    out = call("device_join", name="p", url="http://127.0.0.1:9", token="t")
    assert out.startswith("error: http://127.0.0.1:9/mcp did not answer as a Body")
    assert device.registry.get("p") is None
    assert call("device_pair", name="self", host="h", code="1").startswith("error: 'self' is not a device name")


def test_images_from_a_remote_are_saved_here_and_handed_on(hub, monkeypatch):
    device.registry.add_remote("phone", "http://127.0.0.1:1/mcp", str(hub / "fleet" / "phone.token"))
    (hub / "fleet").mkdir(exist_ok=True)
    (hub / "fleet" / "phone.token").write_text("t\n")

    class Stub:
        def call(self, name, args):
            assert name == "device_screencap" and args == {"device": "self"}
            return "screenshot captured", [(b"\x89PNG\r\n\x1a\nfake", "image/png")], False

    media.drain()
    out = fleet.forward("device_screencap", {"device": "phone"}, remote_factory=lambda entry: Stub())
    assert out == "screenshot captured"
    (path, mime), = media.drain()
    assert mime == "image/png" and path.startswith(str(hub / "tmp" / "remote-phone-")) and path.endswith(".png")
    assert Path(path).read_bytes().startswith(b"\x89PNG")


def test_forward_is_local_for_self_adb_and_no_device_and_plain_when_the_remote_is_down(hub):
    assert fleet.forward("device_health", {}) is None
    assert fleet.forward("device_health", {"device": "self"}) is None
    device.registry.add("gma", "10.0.0.5:5555")
    assert fleet.forward("device_health", {"device": "gma"}) is None
    device.registry.add_remote("phone", "http://127.0.0.1:9/mcp", str(hub / "t"))
    (hub / "t").write_text("t\n")
    out = fleet.forward("device_health", {"device": "phone"})
    assert out.startswith("error: 'phone' (http://127.0.0.1:9/mcp) did not answer")
    assert "device_health" not in (hub / fleet.FLEET_LOG).read_text() if (hub / fleet.FLEET_LOG).exists() else True
    assert fleet.reachability(device.registry.get("phone")) is False


# --- the registry ----------------------------------------------------------------

def test_registry_keeps_kinds_and_groups(tmp_path):
    r = DeviceRegistry(tmp_path / "d.json")
    r.add("gma", "10.0.0.5:5555", notes="her pixel", groups="family, family, spare")
    r.add_remote("phone", "http://100.64.0.9:42618/mcp", "/x/phone.token", groups=["bench"])
    assert r.kind("gma") == "adb" and r.kind("phone") == "http" and r.kind("nope") is None
    assert r.get("gma")["groups"] == ["family", "spare"]
    assert r.groups() == {"bench": ["phone"], "family": ["gma"], "spare": ["gma"]}
    assert r.set_groups("phone", "family") == ["family"] and r.set_groups("nope", "x") is None
    again = DeviceRegistry(tmp_path / "d.json")
    assert again.get("phone")["token_file"] == "/x/phone.token" and again.in_group("family") == ["gma", "phone"]


# --- the CLI ---------------------------------------------------------------------

def test_fleet_cli_lists_joins_tags_and_forgets(remote, recorded_adb, capsys):
    home = recorded_adb / "cli-home"
    common = ["--home", str(home), "--repo-root", str(recorded_adb), "--tools", "device"]
    assert srv.main(["fleet", "join", "phone", "--url", remote["url"], "--token", remote["token"],
                     "--groups", "family", *common]) == 0
    tools.reset()
    assert capsys.readouterr().out.startswith("joined 'phone' at ")
    assert srv.main(["fleet", *common]) == 0
    tools.reset()
    out = capsys.readouterr().out
    assert "phone" in out and "http" in out and "reachable" in out and "family" in out and "self" in out
    assert srv.main(["fleet", "tag", "phone", "--groups", "bench", *common]) == 0
    tools.reset()
    assert capsys.readouterr().out.strip() == "phone: groups bench"
    assert srv.main(["fleet", "forget", "phone", *common]) == 0
    tools.reset()
    assert capsys.readouterr().out.strip() == "unpaired 'phone'"
    assert srv.main(["fleet", "join", "phone", *common]) == 2
    tools.reset()
    assert "needs --url" in capsys.readouterr().err
    assert srv.main(["fleet", "forget", *common]) == 2
    tools.reset()


def test_the_bare_command_still_means_serve_and_old_invocations_parse():
    p = srv.build_parser()
    a = p.parse_args(["probe", "--home", "/h", "--tools", "shell,sensors"])
    assert a.command == "probe" and a.tools == "shell,sensors"
    a = p.parse_args(["serve", "--http", "--host", "100.64.0.9", "--allow-host", "niba.tail.ts.net"])
    assert a.http and a.host == "100.64.0.9" and a.port == fleet.DEFAULT_PORT and a.allow_host == ["niba.tail.ts.net"]
    a = p.parse_args(["playbooks", "--install"])
    assert a.install == srv.DEFAULT_SOPS_DIR
    assert p.parse_args(["fleet"]).action == "list"


def test_the_new_tools_are_classified_and_the_profiles_gate_join():
    assert "device_join" in srv.DESTRUCTIVE and "device_tag" in srv.NEUTRAL
    import tomllib
    for cfg in ("body/caelza-body.example.toml", "runtime/caelza.phone.example.toml"):
        text = (REPO_ROOT / cfg).read_text()
        assert '"body__device_join"' in text.split("always_ask")[1], cfg
        tomllib.loads(text)


def test_the_hub_example_carries_the_same_body_policy_and_turns_the_engine_on():
    """runtime/caelza.hub.example.toml: the hub's Body is the fleet Body on
    stdio, gated exactly like a phone's, with the playbooks loaded."""
    import tomllib
    body_cfg = tomllib.loads((REPO_ROOT / "body" / "caelza-body.example.toml").read_text())
    hub = tomllib.loads((REPO_ROOT / "runtime" / "caelza.hub.example.toml").read_text())
    assert hub["schema_version"] == 3
    body_server = next(s for s in hub["mcp"]["servers"] if s["name"] == "body")
    assert body_server["command"] == "caelza-body" and body_server["args"] == ["serve"]
    assert hub["mcp_bundles"]["body"]["servers"] == ["body"] and hub["sop"]["sops_dir"] == "shared/sops"
    agent = hub["agents"]["main"]
    profile = hub["risk_profiles"][agent["risk_profile"]]
    body_only = lambda entries: {e for e in entries if e.startswith("body__")}  # noqa: E731
    assert body_only(profile["auto_approve"]) == set(body_cfg["risk_profiles"]["main"]["auto_approve"])
    assert body_only(profile["always_ask"]) == set(body_cfg["risk_profiles"]["main"]["always_ask"])
    assert "body__device_join" in profile["always_ask"]
    # The direct-HTTP alternative is documented, commented out, with the token kept out of the file.
    text = (REPO_ROOT / "runtime" / "caelza.hub.example.toml").read_text()
    assert '# transport = "http"' in text and "headers.Authorization" in text and "Bearer" not in text
