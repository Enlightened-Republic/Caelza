"""The 3D printer skill and its example config."""
from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = (REPO_ROOT / "skills" / "3d-printer" / "SKILL.md").read_text(encoding="utf-8")
EXAMPLE = tomllib.loads((REPO_ROOT / "runtime" / "caelza.printer.example.toml").read_text(encoding="utf-8"))


def test_frontmatter_names_the_skill_after_its_directory():
    assert SKILL.startswith("---\n")
    front = SKILL.split("---\n")[1]
    assert "name: 3d-printer\n" in front
    assert "description: " in front


def test_skill_gates_pause_and_cancel_and_leaves_the_dangerous_calls_out():
    assert "Ask the owner first" in SKILL
    # Mentioned only to forbid them.
    for forbidden in ("emergency", "G-code", "start a print"):
        assert forbidden in SKILL.split("## Rules")[1]
    assert "/printer/emergency_stop" not in SKILL
    assert "/printer/gcode/script" not in SKILL


def test_example_allows_a_single_private_host_not_all_of_them():
    http = EXAMPLE["http_request"]
    assert http["allowed_private_hosts"] and "*" not in http["allowed_private_hosts"]
    assert "allow_private_hosts" not in http
    assert "printers" in EXAMPLE["agents"]["main"]["skill_bundles"]
