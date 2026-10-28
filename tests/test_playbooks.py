"""M5: the phone playbooks in body/sops are sound SOP definitions. Every tool a
step names is one the Body serves, every destructive tool sits behind a
confirmation gate and read steps never do, each procedure has an owning agent
and a manual trigger, the SOP.md steps parse the way the Runtime parses them,
the CLI installs them, and (when a `caelza` binary is at hand) the Runtime's
own `sop validate` passes them."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from caelza_body import mcp_server as srv
from caelza_body.agent import playbooks as pb
from caelza_body.agent import tools

REPO_ROOT = Path(__file__).resolve().parents[1]
SOPS = REPO_ROOT / "body" / "sops"
PHONE = ("phone-debloat", "phone-diagnostics", "phone-malware-removal", "phone-new-setup")
FORGE = ("forge-propose", "forge-release")
EXPECTED = tuple(sorted(PHONE + FORGE))
PREFIX = "body__"
#: Runtime-native tools a procedure may name beside the Body's `body__*`.
RUNTIME_TOOLS = {"git_forge"}


@pytest.fixture(scope="module")
def served(tmp_path_factory) -> set[str]:
    settings = srv.load_settings(tmp_path_factory.mktemp("body-home"), REPO_ROOT)
    names = set(srv.register_tools(settings, srv.GROUPS))
    tools.reset()
    return names


@pytest.fixture(scope="module")
def playbooks() -> dict[str, pb.Playbook]:
    return {p.name: p for p in pb.shipped_playbooks(REPO_ROOT)}


@pytest.fixture(scope="module")
def phone_playbooks(playbooks) -> dict[str, pb.Playbook]:
    return {n: p for n, p in playbooks.items() if n in PHONE}


# --- the set -----------------------------------------------------------------

def test_the_playbooks_ship(playbooks):
    assert tuple(sorted(playbooks)) == EXPECTED
    for name, p in playbooks.items():
        assert p.path.name == name, "the directory is the SOP's address"
        assert (p.path / "SOP.toml").is_file() and (p.path / "SOP.md").is_file()
        assert p.description and len(p.description) > 40
        assert p.version.count(".") == 2


def test_manifest_fields_the_runtime_needs(playbooks):
    for p in playbooks.values():
        meta = p.manifest["sop"]
        assert meta["agent"] == "main", f"{p.name}: the dashboard's Run refuses an unowned procedure"
        assert {t["type"] for t in p.triggers} >= {"manual"}, p.name
        assert meta["execution_mode"] == "auto", f"{p.name}: the gates are per step, not a start prompt"
        if p.name in PHONE:
            # The Procedures page fans a group out as one run per phone: `hold` would
            # defer every phone after the first, `coalesce` would answer with the
            # first phone's run; both looked like "engine off" or a silent skip.
            assert meta["admission_policy"] == "parallel", p.name
            assert meta["max_concurrent"] >= 4, p.name


# --- steps -------------------------------------------------------------------

def test_steps_are_numbered_titled_and_bodied(playbooks):
    for p in playbooks.values():
        assert [s.number for s in p.steps] == list(range(1, len(p.steps) + 1)), p.name
        for s in p.steps:
            assert s.title and not s.title.startswith("**"), (p.name, s.number)
            assert len(s.body) > 80, (p.name, s.number, "a step is an instruction, not a label")
            assert s.kind == "execute", "the gates are requires_confirmation on the step that acts"


def test_every_tool_named_is_one_the_body_serves(playbooks, served):
    for p in playbooks.values():
        assert p.tools, p.name
        for tool in p.tools:
            if tool in RUNTIME_TOOLS:
                continue  # the Runtime's own (git_forge), checked in tests/test_forge.py
            assert tool.startswith(PREFIX), (p.name, tool, "tools reach the agent as body__<tool>")
            assert tool.removeprefix(PREFIX) in served, (p.name, tool)


def test_destructive_tools_sit_behind_a_gate_and_reads_do_not(phone_playbooks):
    destructive = {PREFIX + t for t in srv.DESTRUCTIVE}
    for p in phone_playbooks.values():
        gated = []
        for s in p.steps:
            names = set(s.tools) | set(s.allow_tools)
            if names & destructive:
                assert s.requires_confirmation, (p.name, s.number, sorted(names & destructive))
                assert s.allow_tools, (p.name, s.number, "a gated step pins its tools for step_scope_enforce")
                assert set(s.tools) <= set(s.allow_tools), (p.name, s.number)
                gated.append(s.number)
            else:
                assert not s.requires_confirmation, (p.name, s.number, "a read step never prompts")
        assert gated == p.gates
        if p.name == "phone-diagnostics":
            assert gated == [], "diagnostics changes nothing"
        else:
            assert len(gated) == 1, (p.name, "one gate, right before the step that acts")
            assert 1 < gated[0] < len(p.steps), (p.name, "a read before, a check after")


def test_each_playbook_acts_with_exactly_the_tools_its_readme_row_says(playbooks):
    acts = {
        "phone-debloat": {"body__device_uninstall", "body__device_disable"},
        "phone-malware-removal": {"body__device_disable", "body__device_appops"},
        "phone-new-setup": {"body__device_shell", "body__device_settings_put"},
    }
    for name, expected in acts.items():
        step = next(s for s in playbooks[name].steps if s.requires_confirmation)
        assert set(step.tools) == expected, name
    # Malware removal never uninstalls: disabling keeps the evidence and is reversible.
    assert "body__device_uninstall" not in playbooks["phone-malware-removal"].tools
    # Every playbook reads through the four playbook tools somewhere.
    reads = {"body__device_debloat_plan", "body__device_suspects", "body__device_foreground", "body__device_health"}
    assert reads <= set().union(*(p.tools for p in playbooks.values()))


def test_the_parser_reads_the_runtime_grammar():
    md = """# T

## Safety
Not steps.

## Steps

1. **Read** — Look first.
   Second line of the body.
   - tools: body__device_health, body__device_list
   - kind: execute

2. **Act** - Do it.
   - tools: body__device_disable
   - allow-tools: body__device_disable, body__device_packages
   - requires_confirmation: true
   - prompt: Approve {{device}}?

3. Plain title without bold
   - kind: approval

## Notes
4. **Not a step** — after the section.
"""
    steps = pb.parse_sop_steps(md)
    assert [(s.number, s.title) for s in steps] == [(1, "Read"), (2, "Act"), (3, "Plain title without bold")]
    assert steps[0].body == "Look first.\nSecond line of the body."
    assert steps[0].tools == ["body__device_health", "body__device_list"]
    assert steps[1].requires_confirmation and steps[1].allow_tools[1] == "body__device_packages"
    assert steps[1].prompt == "Approve {{device}}?"
    assert steps[2].kind == "checkpoint" and steps[2].gated
    assert not steps[0].gated


# --- the CLI -----------------------------------------------------------------

def test_cli_lists_steps_gates_and_tools(tmp_path, capsys):
    rc = srv.main(["playbooks", "--home", str(tmp_path / "h"), "--repo-root", str(REPO_ROOT)])
    tools.reset()
    assert rc == 0
    out = capsys.readouterr().out
    for name in EXPECTED:
        assert f"{name} v1.0.0:" in out
    assert "gates at 2" in out and "gates at none" in out and "gates at 3" in out
    assert "body__device_debloat_plan" in out


def statuses(out: str) -> list[str]:
    """The status column of `--install`'s per-playbook lines, in order."""
    return re.findall(r"^\s*(installed|updated|unchanged|kept)  /", out, re.M)


def test_cli_installs_keeps_edits_and_forces(tmp_path, capsys):
    dest = tmp_path / "sops"
    args = ["playbooks", "--home", str(tmp_path / "h"), "--repo-root", str(REPO_ROOT)]
    assert srv.main([*args, "--install", str(dest)]) == 0
    tools.reset()
    out = capsys.readouterr().out
    assert statuses(out) == ["installed"] * len(EXPECTED) and "sops_dir" in out
    assert sorted(p.name for p in dest.iterdir()) == list(EXPECTED)
    assert tomllib.loads((dest / "phone-debloat" / "SOP.toml").read_text())["sop"]["name"] == "phone-debloat"

    assert srv.main([*args, "--install", str(dest)]) == 0
    tools.reset()
    assert statuses(capsys.readouterr().out) == ["unchanged"] * len(EXPECTED)

    (dest / "phone-debloat" / "SOP.md").write_text("# mine\n")
    assert srv.main([*args, "--install", str(dest)]) == 0
    tools.reset()
    debloat = EXPECTED.index("phone-debloat")
    expect = ["unchanged"] * len(EXPECTED)
    expect[debloat] = "kept"
    assert statuses(capsys.readouterr().out) == expect
    assert (dest / "phone-debloat" / "SOP.md").read_text() == "# mine\n"

    assert srv.main([*args, "--install", str(dest), "--force"]) == 0
    tools.reset()
    expect[debloat] = "updated"
    assert statuses(capsys.readouterr().out) == expect
    assert (dest / "phone-debloat" / "SOP.md").read_text() == (SOPS / "phone-debloat" / "SOP.md").read_text()


def test_cli_without_shipped_playbooks_fails_plainly(tmp_path, capsys):
    rc = srv.main(["playbooks", "--home", str(tmp_path / "h"), "--repo-root", str(tmp_path)])
    tools.reset()
    assert rc == 1 and "no playbooks under" in capsys.readouterr().err


# --- the wiring around them --------------------------------------------------

def test_phone_config_and_installers_turn_the_engine_on():
    phone = tomllib.loads((REPO_ROOT / "runtime" / "caelza.phone.example.toml").read_text())
    assert phone["sop"]["sops_dir"] == "shared/sops"
    install = (REPO_ROOT / "install.sh").read_text()
    assert "caelza-body playbooks --install" in install
    readme = (SOPS / "README.md").read_text()
    for name in EXPECTED:
        assert f"`{name}`" in readme
    procedures = (REPO_ROOT / "runtime" / "overlay" / "web" / "src" / "pages" / "Procedures.tsx").read_text()
    assert "runSop(" in procedures and "isPlaybook(" in procedures


def test_the_example_log_points_at_the_playbook():
    log = (REPO_ROOT / "docs" / "examples" / "revvl-7-debloat" / "README.md").read_text()
    assert "phone-debloat" in log


# --- the Runtime's own validator, when a binary is at hand ---------------------

def _caelza_bin() -> str | None:
    explicit = os.environ.get("CAELZA_BIN")
    if explicit and Path(explicit).is_file():
        return explicit
    return shutil.which("caelza")


@pytest.mark.skipif(_caelza_bin() is None, reason="no caelza binary (set CAELZA_BIN or put caelza on PATH)")
def test_runtime_validates_the_set(tmp_path):
    root = tmp_path / "install"
    (root / "shared" / "sops").mkdir(parents=True)
    (root / "config.toml").write_text(
        'schema_version = 3\n\n[agents.main]\nenabled = true\nmodel_provider = "llamacpp.local"\n\n'
        '[providers.models.llamacpp.local]\nmodel = "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M"\n\n'
        '[sop]\nsops_dir = "shared/sops"\nstep_scope_enforce = true\n')
    assert all(status == "installed" for _, status in pb.install_playbooks(REPO_ROOT, root / "shared" / "sops"))
    run = subprocess.run([_caelza_bin(), "--config-dir", str(root), "sop", "validate"],
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "All SOPs passed validation" in run.stdout
    for name in EXPECTED:
        assert f"{name} — valid" in run.stdout, run.stdout
    show = subprocess.run([_caelza_bin(), "--config-dir", str(root), "sop", "show", "phone-debloat"],
                          capture_output=True, text=True, timeout=120).stdout
    assert "2. Apply what was approved [confirmation required]" in show
    assert "1. Take stock and write the plan\n" in show
