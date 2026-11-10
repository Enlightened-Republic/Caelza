"""The Home Assistant wiring: the example config and the script that writes it."""
from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = tomllib.loads((REPO_ROOT / "runtime" / "caelza.homeassistant.example.toml").read_text(encoding="utf-8"))
SCRIPT = REPO_ROOT / "scripts" / "home-connect.sh"


def test_example_is_an_http_mcp_server_with_no_token_in_it():
    (server,) = EXAMPLE["mcp"]["servers"]
    assert server["name"] == "homeassistant"
    assert server["transport"] == "http"
    assert server["url"].endswith("/api/mcp/assist"), "Device control only: entities exposed to voice assistants"
    assert "headers" not in server
    assert EXAMPLE["mcp_bundles"]["homeassistant"]["servers"] == ["homeassistant"]
    assert "homeassistant" in EXAMPLE["agents"]["main"]["mcp_bundles"]


def test_script_and_example_agree_and_never_take_the_token_on_a_command_line():
    text = SCRIPT.read_text(encoding="utf-8")
    (server,) = EXAMPLE["mcp"]["servers"]
    assert '/api/mcp/assist"' in text
    assert f'TIMEOUT={server["tool_timeout_secs"]}' in text
    # The row is a keyed list entry: made through `config patch`, the token through the masked prompt.
    assert "config patch -" in text
    assert '"path": "/mcp/servers/$NAME/transport", "value": "http"' in text
    assert '"path": "/agents/$AGENT/mcp_bundles", "value": [$merged]' in text
    assert 'config set "mcp.servers.$NAME.headers.Authorization"' in text
    assert "config set mcp.servers.homeassistant." not in text
    assert "read -r" not in text
    assert "Authorization\" \"" not in text


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh")
def test_dry_run_writes_nothing(tmp_path):
    out = subprocess.run(
        ["sh", str(SCRIPT), "--dry-run", "http://192.168.1.5:8123"],
        capture_output=True, text=True, env={"CAELZA_CONFIG_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert out.returncode == 0, out.stderr
    assert "192.168.1.5:8123/api/mcp/assist" in out.stdout + out.stderr
    assert list(tmp_path.iterdir()) == []
