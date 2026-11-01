"""M6 Forge: the agent proposes Runtime changes as pull requests over the
Runtime's git channel, CI builds the release, the guard pulls it.

The Forge is mostly wiring around what the Runtime already has (the git
channel, the `git_forge` tool, channel-triggered SOPs): two procedures, the
channel config, the release build with `channel-git` in, and the two Body
tools (`runtime_status`, `runtime_update`) that close the loop on this
machine. These tests keep that wiring sound, and run the Runtime's own `sop
validate` over the procedures with the channel configured when a binary is
at hand."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from caelza_body import mcp_server as srv
from caelza_body import runtime_guard as rg
from caelza_body.agent import playbooks as pb
from caelza_body.agent import tools
from caelza_body.agent.tools import runtime as rt

REPO_ROOT = Path(__file__).resolve().parents[1]
FORGE_EXAMPLE = REPO_ROOT / "runtime" / "caelza.forge.example.toml"
FORGE_CHANNEL = '''
[channels.git.forge]
enabled = true
provider = "github"
app_id = 1
repos = ["Enlightened-Republic/Caelza"]

[channels.git.forge.events]
"release.published" = { sop = "forge-release" }
"workflow_run.failed" = { message = true }
'''


@pytest.fixture(scope="module")
def forge() -> dict[str, pb.Playbook]:
    return {p.name: p for p in pb.shipped_playbooks(REPO_ROOT) if p.name.startswith("forge-")}


@pytest.fixture(scope="module")
def served(tmp_path_factory) -> set[str]:
    settings = srv.load_settings(tmp_path_factory.mktemp("body-home"), REPO_ROOT)
    names = set(srv.register_tools(settings, srv.GROUPS))
    tools.reset()
    return names


# --- the procedures ------------------------------------------------------------

def test_the_two_forge_procedures_ship_with_the_right_triggers(forge):
    assert sorted(forge) == ["forge-propose", "forge-release"]
    for p in forge.values():
        meta = p.manifest["sop"]
        assert meta["agent"] == "main" and meta["execution_mode"] == "auto", p.name
        assert meta["admission_policy"] == "hold" and meta["max_concurrent"] == 1, (p.name, "one at a time")
        assert "manual" in {t["type"] for t in p.triggers}, p.name
    assert [t["type"] for t in forge["forge-propose"].triggers] == ["manual"]
    release = next(t for t in forge["forge-release"].triggers if t["type"] == "channel")
    assert release["channel"] == "git" and release["alias"] == "forge"
    assert release["condition"] == '$.event_type == "release.published"'


def test_the_writes_sit_behind_the_gate_and_the_reads_do_not(forge, served):
    propose = forge["forge-propose"]
    assert propose.gates == [3] and propose.steps[2].title == "Propose"
    assert set(propose.steps[2].tools) == {"git_forge"} == set(propose.steps[2].allow_tools)
    for step in propose.steps[:2]:
        assert set(step.tools) == {"git_forge"} == set(step.allow_tools) and not step.requires_confirmation
    assert propose.steps[3].tools == [] and not propose.steps[3].requires_confirmation, "the report calls nothing"

    release = forge["forge-release"]
    assert release.gates == [2] and release.steps[1].title == "Update"
    assert set(release.steps[1].tools) == {"body__runtime_update"}
    assert set(release.steps[1].allow_tools) == {"body__runtime_update", "body__runtime_status"}
    assert set(release.steps[0].tools) == {"body__runtime_status", "git_forge"} and not release.steps[0].requires_confirmation
    assert set(release.steps[2].tools) == {"body__runtime_status"} and not release.steps[2].requires_confirmation

    body_tools = {t.removeprefix("body__") for p in forge.values() for t in p.tools if t.startswith("body__")}
    assert body_tools == {"runtime_status", "runtime_update"} and body_tools <= served
    assert {t for p in forge.values() for t in p.tools if not t.startswith("body__")} == {"git_forge"}
    assert "runtime_update" in srv.DESTRUCTIVE and "runtime_status" in srv.READ_ONLY


def test_the_proposal_surface_is_bounded_in_the_text(forge):
    md = (forge["forge-propose"].path / "SOP.md").read_text()
    for never in ("`.github/workflows/**`", "`caelza_body/supervisor.py`", "`caelza_body/runtime_guard.py`",
                  "never writes to\n`main`"):
        assert never in md, never
    assert "draft: true" in md and "forge/<slug>" in md and 'resource: "pull", action:\n   "create"' in md
    release = (forge["forge-release"].path / "SOP.md").read_text()
    assert "body__runtime_update(tag, reason)" in release and "Do not call it twice" in release
    assert "experimental and may be missing" in release


# --- the wiring ----------------------------------------------------------------

def test_the_forge_example_wires_the_channel_the_events_and_the_gates():
    cfg = tomllib.loads(FORGE_EXAMPLE.read_text())
    ch = cfg["channels"]["git"]["forge"]
    assert ch["enabled"] is True and ch["provider"] == "github" and ch["repos"] == ["Enlightened-Republic/Caelza"]
    assert ch["mention_only"] is True and ch["poll_interval_secs"] >= 15
    assert ch["events"]["release.published"] == {"sop": "forge-release"}
    assert ch["events"]["workflow_run.failed"] == {"message": True}
    assert ch["events"]["pull_request.merged"] == {"message": True}
    assert "private_key" not in ch and "private_key_path" not in ch, "the key is set with `caelza config set`, never written here"
    assert cfg["peer_groups"]["git_forge"]["channel"] == "git.forge"
    assert "git.forge" in cfg["agents"]["main"]["channels"]
    text = FORGE_EXAMPLE.read_text()
    assert "caelza config set channels.git.forge.private_key" in text
    assert '"git_forge", "body__runtime_update"' in text and '"body__runtime_status"' in text


def test_the_release_and_the_gate_build_the_git_channel_in():
    """Upstream keeps `channel-git` out of its lean default; without it the
    binary says "Git (configured, not compiled)" and the Forge is a config
    block that does nothing."""
    release = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "cargo build --release --locked -p caelza --features channel-git" in release
    build = (REPO_ROOT / "runtime" / "build.sh").read_text()
    assert 'FEATURES="${CAELZA_FEATURES-channel-git}"' in build


def test_the_runtime_tools_are_classified_and_gated_in_every_example():
    assert "runtime" in srv.GROUPS and srv.PROBE_TOOL["runtime"] == "runtime_status"
    assert "runtime_status" in srv.READ_ONLY and "runtime_update" in srv.DESTRUCTIVE
    for cfg in ("body/caelza-body.example.toml", "runtime/caelza.phone.example.toml", "runtime/caelza.hub.example.toml"):
        data = tomllib.loads((REPO_ROOT / cfg).read_text())
        profile = data["risk_profiles"][data["agents"]["main"]["risk_profile"]]
        assert "body__runtime_status" in profile["auto_approve"], cfg
        assert "body__runtime_update" in profile["always_ask"], cfg
    rust = (REPO_ROOT / "runtime" / "overlay" / "crates" / "caelza-gateway" / "src" / "api_bodies.rs").read_text()
    assert '"runtime_status",' in rust and '"runtime_update",' in rust


# --- the Body tools ------------------------------------------------------------

@pytest.fixture
def body(tmp_path):
    home = tmp_path / "home"
    settings = srv.load_settings(home, REPO_ROOT)
    names = srv.register_tools(settings, ("runtime",))
    yield home, set(names)
    tools.reset()


def call(tool, **args):
    out = tools.dispatch(tool, args)
    return json.loads(out) if out.startswith("{") else out


def test_runtime_status_reads_the_guard(body):
    home, names = body
    assert names == {"runtime_status", "runtime_update"}
    s = call("runtime_status")
    assert s["current"] is None and s["installed"] == [] and s["update_running"] is None and s["update_log"] == []
    assert s["target"] == rg.default_target()
    d = rg.version_dir(home, "0.1.0")
    d.mkdir(parents=True)
    (d / "caelza").write_text("#!/bin/sh\n")
    rg.promote(home, "0.1.0")
    rg.request_restart(home, "by hand", "0.1.0")
    s = call("runtime_status")
    assert s["current"] == s["last_good"] == "0.1.0" and s["binary"].endswith("0.1.0/caelza")
    assert s["restart_requested"]["version"] == "0.1.0"


def test_runtime_update_needs_a_reason_starts_detached_and_refuses_a_second(body, monkeypatch):
    home, _ = body
    assert call("runtime_update", reason="  ").startswith("error: a reason is required")
    spawned: list = []

    class Proc:
        pid = os.getpid()  # alive for the whole test

    def fake_popen(argv, **kw):
        spawned.append((argv, kw))
        kw["stdout"].write("found v0.1.1: caelza-0.1.1-x86_64-unknown-linux-gnu.tar.gz\n")
        return Proc()

    monkeypatch.setattr(rt.subprocess, "Popen", fake_popen)
    out = call("runtime_update", reason="v0.1.1 is out; the owner approved", tag="v0.1.1")
    assert out["started"] is True and out["pid"] == os.getpid() and out["tag"] == "v0.1.1" and out["current"] is None
    # The device tools' self-connect thread (device.py, `caelza-body-adb-self`) may
    # spawn its `adb connect` through the same patched Popen first; the update's
    # own spawn is the one naming the server module.
    argv, kw = next((a, k) for a, k in spawned if "caelza_body.mcp_server" in a)
    assert argv[1:] == ["-m", "caelza_body.mcp_server", "runtime", "update", "--home", str(home), "--tag", "v0.1.1"]
    assert kw["start_new_session"] is True and kw["stdin"] is subprocess.DEVNULL and kw["cwd"] == str(home)
    assert (home / rt.UPDATE_PID).read_text().strip() == str(os.getpid())
    log = (home / rt.UPDATE_LOG).read_text()
    assert "runtime update v0.1.1: v0.1.1 is out; the owner approved" in log and "found v0.1.1" in log
    audit = (home / "logs" / "device-actions.log").read_text()
    assert "\tself\truntime_update\tv0.1.1 (pid" in audit and "the owner approved" in audit

    status = call("runtime_status")
    assert status["update_running"] == os.getpid() and any("found v0.1.1" in ln for ln in status["update_log"])
    assert call("runtime_update", reason="again").startswith("error: a runtime update is already running")

    # A pid that is gone clears the way, and the stale pid file with it (a pid
    # beyond pid_max can never be alive, unlike a small number on a busy box).
    (home / rt.UPDATE_PID).write_text(f"{2**31 - 7}\n")
    assert rt.update_running() is None and not (home / rt.UPDATE_PID).exists()
    (home / rt.UPDATE_PID).write_text("not a pid\n")
    assert rt.update_running() is None
    out = call("runtime_update", reason="the latest, by hand")
    assert out["tag"] == "latest" and spawned[1][0][-2:] == ["--home", str(home)]


# --- the Runtime's own validator, with the channel configured -------------------

def _caelza_bin() -> str | None:
    explicit = os.environ.get("CAELZA_BIN")
    if explicit and Path(explicit).is_file():
        return explicit
    return shutil.which("caelza")


@pytest.mark.skipif(_caelza_bin() is None, reason="no caelza binary (set CAELZA_BIN or put caelza on PATH)")
def test_the_runtime_validates_the_forge_procedures_with_the_channel_configured(tmp_path):
    root = tmp_path / "install"
    (root / "shared" / "sops").mkdir(parents=True)
    (root / "config.toml").write_text(
        'schema_version = 3\n\n[agents.main]\nenabled = true\nmodel_provider = "llamacpp.local"\n\n'
        '[providers.models.llamacpp.local]\nmodel = "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M"\n\n'
        '[sop]\nsops_dir = "shared/sops"\nstep_scope_enforce = true\n' + FORGE_CHANNEL)
    pb.install_playbooks(REPO_ROOT, root / "shared" / "sops")
    run = subprocess.run([_caelza_bin(), "--config-dir", str(root), "sop", "validate"],
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    for name in ("forge-propose", "forge-release"):
        assert f"{name} — valid" in run.stdout, run.stdout
    show = subprocess.run([_caelza_bin(), "--config-dir", str(root), "sop", "show", "forge-release"],
                          capture_output=True, text=True, timeout=120).stdout
    assert "2. Update [confirmation required]" in show, show
    show = subprocess.run([_caelza_bin(), "--config-dir", str(root), "sop", "show", "forge-propose"],
                          capture_output=True, text=True, timeout=120).stdout
    assert "3. Propose [confirmation required]" in show, show


# --- the docs tell the loop ---------------------------------------------------------

def test_the_docs_and_counts_follow():
    doc = (REPO_ROOT / "docs" / "forge.md").read_text()
    for needle in ("Contents", "Pull requests", "Actions", "Webhook", "channel-git", "forge-propose", "forge-release",
                   "git_forge", "runtime_update", "caelza config set channels.git.forge.private_key"):
        assert needle in doc, needle
    assert "43 tools" in (REPO_ROOT / "README.md").read_text()
    manifest = (REPO_ROOT / "bundle" / "manifest.toml").read_text()
    assert "tools = 43" in manifest and "forge" in manifest
    vision = (REPO_ROOT / "docs" / "design" / "caelza-vision.md").read_text()
    assert "M6 is complete" in vision and "forge-propose" in vision
    body_readme = (REPO_ROOT / "body" / "README.md").read_text()
    assert "## Forge" in body_readme and "`runtime_status`" in body_readme and "`runtime_update`" in body_readme
