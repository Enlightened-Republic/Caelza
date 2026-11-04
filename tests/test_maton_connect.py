"""The Maton wiring: the example config the Runtime reads, and the script that writes it."""
from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = tomllib.loads((REPO_ROOT / "runtime" / "caelza.maton.example.toml").read_text())
SCRIPT = REPO_ROOT / "scripts" / "maton-connect.sh"


def test_example_is_an_http_mcp_server_with_no_key_in_it():
    (server,) = EXAMPLE["mcp"]["servers"]
    assert server["name"] == "maton"
    assert server["transport"] == "http"
    assert server["url"] == "https://mcp.maton.ai"
    assert "headers" not in server, "the key is a secret: it is set with `caelza config set`, never in the file"
    assert EXAMPLE["mcp_bundles"]["maton"]["servers"] == ["maton"]
    assert "maton" in EXAMPLE["agents"]["main"]["mcp_bundles"]


def test_script_and_example_agree_on_the_server():
    text = SCRIPT.read_text()
    (server,) = EXAMPLE["mcp"]["servers"]
    assert f'URL="{server["url"]}"' in text
    assert "mcp.servers.maton.headers.Authorization" in text
    assert "mcp.servers.maton.transport http" in text
    assert f"tool_timeout_secs {server['tool_timeout_secs']}" in text


def test_script_never_takes_the_key_on_a_command_line():
    text = SCRIPT.read_text()
    assert "Authorization\" \"" not in text and "Authorization '" not in text
    assert "read -r" not in text, "the key goes through caelza's masked prompt, not a shell read"


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh")
def test_dry_run_writes_nothing_and_exits_clean(tmp_path):
    out = subprocess.run(
        ["sh", str(SCRIPT), "--dry-run"],
        capture_output=True, text=True, env={"CAELZA_CONFIG_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert out.returncode == 0, out.stderr
    assert "mcp.maton.ai" in out.stdout + out.stderr
    assert list(tmp_path.iterdir()) == []
