"""The Mind wiring example: the native xanima backend block the Runtime reads,
in step with the manifest and the backend's own defaults."""
from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = tomllib.loads((REPO_ROOT / "mind" / "caelza-mind.example.toml").read_text())
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
OVERLAY = (REPO_ROOT / "runtime" / "overlay" / "crates" / "caelza-memory" / "src" / "xanima.rs").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0001-xanima-memory-backend.patch").read_text()


def test_native_backend_is_selected_with_the_runtime_schema():
    assert EXAMPLE["schema_version"] == 3
    assert EXAMPLE["memory"]["backend"] == "xanima"
    storage = EXAMPLE["storage"]["xanima"]["default"]
    assert storage["url"] == "http://127.0.0.1:18790"
    assert "{agent}" in storage["token_file"]
    assert storage["scope"] in ("all", "private", "shared")
    assert storage["agent"] == "main"
    assert "token" not in storage, "the example never carries a plaintext token"


def test_example_defaults_match_the_backend_defaults():
    storage = EXAMPLE["storage"]["xanima"]["default"]
    assert f'pub const DEFAULT_URL: &str = "{storage["url"]}";' in OVERLAY
    assert f'pub const DEFAULT_TOKEN_FILE: &str = "{storage["token_file"]}";' in OVERLAY
    assert f'"{storage["url"]}".into()' in PATCH  # the config schema's default_xanima_url


def test_manifest_points_at_the_native_backend():
    mind = MANIFEST["components"]["mind"]
    assert mind["native_backend"] == "xanima"
    assert mind["native_config"] == "mind/caelza-mind.example.toml"
    assert (REPO_ROOT / mind["native_overlay"]).is_file()
    assert (REPO_ROOT / mind["native_patch"]).is_file()
    assert mind["service_url"] == EXAMPLE["storage"]["xanima"]["default"]["url"]


def test_patch_touches_only_the_runtime_files_it_claims():
    touched = sorted({line.split()[1][2:] for line in PATCH.splitlines() if line.startswith("+++ b/")})
    assert touched == [
        "crates/caelza-api/src/attribution.rs",
        "crates/caelza-config/src/schema.rs",
        "crates/caelza-config/src/sections.rs",
        "crates/caelza-gateway/src/api_sections.rs",
        "crates/caelza-memory/src/backend.rs",
        "crates/caelza-memory/src/lib.rs",
    ]
    # The MCP tool path and the bundle both still describe the service.
    servers = {s["name"]: s for s in EXAMPLE["mcp"]["servers"]}
    assert servers["brain-service"]["url"] == "http://127.0.0.1:18790/mcp"
