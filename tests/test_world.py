"""Ether Hollow: the agent as a resident of the town, slice 1 (the Runtime side).

The `ether_hollow` tool mirrors the town's Agent API action for action with the
resident key the owner holds in `[ether_hollow]`; the gateway's `/api/world`
registers the resident (the key written through the config API's own PATCH
handler, never shown), and keeps the ghost visible (`here` every ~10 s while
the owner has sent the agent to town). These tests keep the overlay modules,
the patch, the manifest and the docs saying the same thing; the modules' own
behaviour is under `cargo test -p caelza-tools ether_hollow` and
`cargo test -p caelza-gateway api_world`.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay"
TOOL = (OVERLAY / "crates" / "caelza-tools" / "src" / "ether_hollow.rs").read_text()
API = (OVERLAY / "crates" / "caelza-gateway" / "src" / "api_world.rs").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0018-ether-hollow.patch").read_text()
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
VISION = (REPO_ROOT / "docs" / "design" / "caelza-vision.md").read_text()

TOWN = "https://etherhollow.enlightenedrepublic.online"
# The Agent API v1's actions, as `GET /api/agent` lists them (read 2026-11-16).
ACTIONS = [
    "register", "me", "town", "look", "move", "here", "leave", "read", "item", "buy",
    "events", "rsvp", "attend", "note", "list", "unlist", "listings", "orders", "order_done",
    "agreement", "rent", "rent_pay", "unrent", "lease", "post", "reply", "react",
    "build", "unbuild", "builds",
]


def rust_str_list(source: str, name: str) -> list[str]:
    body = re.search(rf"pub const {name}: &\[&str\] = &\[(.*?)\];", source, flags=re.S).group(1)
    return re.findall(r'"([a-z_]+)"', body)


def test_the_patch_touches_the_schema_the_tool_registry_and_the_gateway_only():
    files = re.findall(r"^\+\+\+ b/(.+)$", PATCH, flags=re.M)
    assert files == [
        "crates/caelza-config/src/schema.rs",
        "crates/caelza-tools/src/lib.rs",
        "crates/caelza-tools/src/attribution.rs",
        "crates/caelza-tools/src/inventory.rs",
        "crates/caelza-runtime/src/tools/mod.rs",
        "crates/caelza-runtime/src/agent/loop_.rs",
        "crates/caelza-gateway/src/lib.rs",
        "docs/book/src/developing/tool-inventory.md",
    ], files
    # The book's tier-3 table, which the tools crate's docs-drift test reads.
    assert "+| Caelza | `ether_hollow` | No: `[ether_hollow].enabled` is off until the owner registers the resident |" in PATCH
    # The schema: the section, grouped, the key a secret, the proxy service key.
    assert "+    pub ether_hollow: EtherHollowConfig," in PATCH
    assert '+    #[group = "Integrations"]\n+    pub ether_hollow' in PATCH
    assert '+#[prefix = "ether_hollow"]' in PATCH
    assert "+    #[secret]\n+    #[credential_class = \"encrypted_secret\"]" in PATCH
    assert '+    "tool.ether_hollow",' in PATCH
    assert f'+            url: "{TOWN}".into(),' in PATCH
    assert "+            ether_hollow: EtherHollowConfig::default()," in PATCH
    # The tool: module, attribution, inventory, registration for the one agent.
    assert "+pub mod ether_hollow;" in PATCH
    assert "+tool_attribution!(EtherHollowTool, ToolKind::Plugin);" in PATCH
    assert '+        name: "ether_hollow",\n+        tier: ToolTier::Optional,\n+        compilation: BuiltinToolCompilation::Always,' in PATCH
    assert "+    if root_config.ether_hollow.enabled && agent_alias == root_config.ether_hollow.agent {" in PATCH
    assert "+            Arc::new(EtherHollowTool::new(&root_config.ether_hollow))" in PATCH
    assert "+        if config.ether_hollow.enabled {\n+            tool_descs.push((\n+                \"ether_hollow\"," in PATCH
    # The gateway: the module and its four routes.
    assert "+pub mod api_world;" in PATCH
    for route, handler in (
        ('"/api/world"', "get(api_world::handle_world_get)"),
        ('"/api/world/register"', "post(api_world::handle_world_register)"),
        ('"/api/world/enter"', "post(api_world::handle_world_enter)"),
        ('"/api/world/leave"', "post(api_world::handle_world_leave)"),
    ):
        assert f"+        .route({route}, {handler})" in PATCH, route


def test_the_tool_knows_every_action_the_town_has_and_which_ones_spend():
    assert rust_str_list(TOOL, "ACTIONS") == ACTIONS
    assert rust_str_list(TOOL, "SPEND_ACTIONS") == ["buy", "rent", "rent_pay"]
    assert f'pub const DEFAULT_URL: &str = "{TOWN}";' in TOOL
    assert 'pub const AGENT_PATH: &str = "/api/agent";' in TOOL
    assert 'pub const KEY_PREFIX: &str = "ehk_";' in TOOL and "pub const KEY_LEN: usize = 36;" in TOOL
    assert 'pub const SERVICE_KEY: &str = "tool.ether_hollow";' in TOOL
    assert 'pub const SERVICE_KEY: &str = "tool.ether_hollow";' in API, "one proxy rule covers the tool and the gateway"


def test_the_tool_refuses_before_the_network_what_is_not_the_models():
    # register is the owner's; no key means no resident; spending is off until allowed.
    assert 'Kind::Register => Some(' in TOOL and "Registration is the owner's" in TOOL
    assert "_ if !has_key => Some(" in TOOL and "not a resident of Ether Hollow yet" in TOOL
    assert "Kind::Spend if !spend_allowed => Some(format!(" in TOOL
    assert "if let Some(why) = refusal(&action, self.has_key(), self.spend) {" in TOOL
    # The key goes in the header, the model's own fields are dropped, the town's answer is the result.
    assert "request = request.bearer_auth(key);" in TOOL
    assert 'const LOCAL_FIELDS: &[&str] = &["approved"];' in TOOL
    assert "Ok((200, answer)) => Ok(ToolResult::ok(ToolOutput::json(answer)))," in TOOL
    assert "Ok((status, answer)) => Ok(ToolResult::err(explain(status, &answer)))," in TOOL
    for code in ("401", "402", "403", "423", "429", "503"):
        assert f"        {code} => " in TOOL, code
    # The key is never logged: the module logs nothing at all.
    assert "caelza_log::record!" not in TOOL


def test_the_gateway_keeps_the_key_and_the_presence():
    # Registration writes through the config API's own PATCH handler.
    assert "api_config::handle_patch(" in API
    assert "Json(register_ops(&key, &name))," in API
    for path in ("/ether_hollow/key", "/ether_hollow/name", "/ether_hollow/enabled"):
        assert f'"path": "{path}"' in API, path
    # The key is in the answer only when the write failed.
    assert "if !saved {" in API and 'out["key"] = Value::String(key);' in API
    assert API.count('out["key"]') == 1
    # The passport is scrubbed of anything key-shaped before it reaches the page.
    assert "Ok((200, v)) => (Some(scrub(v)), None)," in API
    # Presence: the town's ten seconds, an hour by default, a day at most, fatal codes end it.
    assert "pub const BEAT: Duration = Duration::from_secs(10);" in API
    assert "pub const DEFAULT_MINUTES: u64 = 60;" in API and "pub const MAX_MINUTES: u64 = 24 * 60;" in API
    assert "matches!(status, 401 | 403 | 423)" in API
    assert 'Some(&json!({"action": "here"}))' in API and API.count('{"action": "leave"}') == 2
    # The key is read live at every beat, so a removed key stops the ghost.
    assert "let Some(key) = live_key(&state) else {" in API
    # Every route is behind pairing.
    assert API.count("require_auth(&state, &headers)") == 4
    assert "caelza_log::record!" not in API


def test_the_manifest_and_the_vision_name_the_slice():
    rt = MANIFEST["components"]["runtime"]
    assert rt["world_patch"] == "runtime/patches/0018-ether-hollow.patch"
    assert rt["world_tool"] == "runtime/overlay/crates/caelza-tools/src/ether_hollow.rs"
    assert rt["world_api"] == "runtime/overlay/crates/caelza-gateway/src/api_world.rs"
    assert rt["world_url"] == TOWN
    assert "| **M10 Ether Hollow** |" in VISION
    row = VISION.split("| **M10 Ether Hollow** |", 1)[1].split("\n", 1)[0]
    assert "0018-ether-hollow.patch" in row and "`ether_hollow`" in row and "/api/world" in row
    assert "Left:" in row, "the slices still to come are named"
