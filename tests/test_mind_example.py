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
TURN_CONTEXT_PATCH = (REPO_ROOT / "runtime" / "patches" / "0008-mind-turn-context.patch").read_text()


def test_native_backend_is_selected_with_the_runtime_schema():
    assert EXAMPLE["schema_version"] == 3
    assert EXAMPLE["memory"]["backend"] == "xanima"
    storage = EXAMPLE["storage"]["xanima"]["default"]
    assert storage["url"] == "http://127.0.0.1:18790"
    assert "{agent}" in storage["token_file"]
    assert storage["scope"] in ("all", "private", "shared")
    assert storage["agent"] == "main"
    assert "token" not in storage, "the example never carries a plaintext token"
    assert storage["turn_context"] is True
    assert "{agent}" not in storage["provision_token_file"], "one provision token for every agent"


def test_example_defaults_match_the_backend_defaults():
    storage = EXAMPLE["storage"]["xanima"]["default"]
    assert f'pub const DEFAULT_URL: &str = "{storage["url"]}";' in OVERLAY
    assert f'pub const DEFAULT_TOKEN_FILE: &str = "{storage["token_file"]}";' in OVERLAY
    assert f'"{storage["url"]}".into()' in PATCH  # the config schema's default_xanima_url
    assert f'pub const DEFAULT_PROVISION_TOKEN_FILE: &str = "{storage["provision_token_file"]}";' in OVERLAY
    assert f"pub const DEFAULT_TURN_CONTEXT_MAX_CHARS: usize = {storage['turn_context_max_chars']:_};" in OVERLAY
    assert f"fn default_xanima_turn_context_max_chars() -> usize {{\n+    {storage['turn_context_max_chars']}\n" in TURN_CONTEXT_PATCH
    assert "+            turn_context: true," in TURN_CONTEXT_PATCH


def test_the_backend_speaks_the_services_contract():
    """The argument and reply keys of the two service tools, as read from the
    service's source (packages/server/src/{tools,provision}.ts at 0.7.0)."""
    assert '"brain_turn_context"' in OVERLAY and '"brain_provision_agent"' in OVERLAY
    for key in ('"query"', '"session_key"', '"owner_turn"', '"ack_note_ids"'):
        assert key in OVERLAY, key
    assert '"agentId": agent' in OVERLAY, "provisioning names the agent as the service spells it"
    for key in ('"identity"', '"activeGoals"', '"noteIds"', '"status"', '"token"'):
        assert f"get({key})" in OVERLAY, key
    assert 'for key in ["text", "now"]' in OVERLAY, "the goals note and the current task, already headed blocks"
    assert "write scope" in OVERLAY and "already-provisioned" in OVERLAY
    assert '.mode(0o600)' in OVERLAY, "a minted token file is owner-only"


def test_the_turn_context_patch_touches_the_trait_the_wrappers_the_schema_and_the_renderer():
    touched = sorted({line.split()[1][2:] for line in TURN_CONTEXT_PATCH.splitlines() if line.startswith("+++ b/")})
    assert touched == [
        "crates/caelza-api/src/memory_traits.rs",
        "crates/caelza-config/src/schema.rs",
        "crates/caelza-memory/src/agent_scoped.rs",
        "crates/caelza-memory/src/audit.rs",
        "crates/caelza-memory/src/retrieval.rs",
        "crates/caelza-memory/src/scanned.rs",
        "crates/caelza-runtime/src/agent/memory_inject.rs",
    ]
    assert TURN_CONTEXT_PATCH.count("async fn turn_context_for_agent(") >= 6, "the trait's default and every wrapper in the per-agent chain"
    assert "+        .turn_context_for_agent(" in TURN_CONTEXT_PATCH and "+            !exclude_conversation," in TURN_CONTEXT_PATCH
    assert "pub provision_token_file: Option<String>," in TURN_CONTEXT_PATCH
    assert (REPO_ROOT / MANIFEST["components"]["mind"]["turn_context_patch"]).is_file()


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
