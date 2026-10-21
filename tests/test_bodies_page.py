"""UI phase 2b: the Bodies page. The gateway's Body proxy module, the page, the
client and the wiring patch stay in step; the routes the page calls are the
routes the gateway mounts; the tool classes the gateway shows are the Body's
own."""
from __future__ import annotations

import re
from pathlib import Path

from caelza_body import mcp_server as srv

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay"
PATCH = (REPO_ROOT / "runtime" / "patches" / "0004-bodies-page.patch").read_text()
API_BODIES = (OVERLAY / "crates" / "caelza-gateway" / "src" / "api_bodies.rs").read_text()
CLIENT = (OVERLAY / "web" / "src" / "lib" / "bodies.ts").read_text()
PAGE = (OVERLAY / "web" / "src" / "pages" / "Bodies.tsx").read_text()
EXAMPLE = (REPO_ROOT / "body" / "caelza-body.example.toml").read_text()

HANDLERS = (
    "handle_bodies_status", "handle_bodies_devices", "handle_bodies_sensors",
    "handle_bodies_packages", "handle_bodies_capture", "handle_bodies_pair",
    "handle_bodies_unpair",
)


def _rust_str_array(name: str) -> set[str]:
    """The string literals of `pub(crate) const NAME: &[&str] = &[ ... ];`."""
    m = re.search(rf"const {name}: &\[&str\] = &\[(.*?)\];", API_BODIES, re.S)
    assert m, name
    return set(re.findall(r'"([a-z_]+)"', m.group(1)))


def test_patch_touches_only_the_files_it_claims():
    touched = sorted({line.split()[1][2:] for line in PATCH.splitlines() if line.startswith("+++ b/")})
    assert touched == [
        "crates/caelza-gateway/src/lib.rs",
        "web/src/components/layout/Sidebar.tsx",
        "web/src/lib/i18n.ts",
        "web/src/router/lazyPages.tsx",
        "web/src/router/router.tsx",
    ]
    assert "+pub mod api_bodies;" in PATCH
    assert '+        <Route path="/bodies" element={<Bodies />} />' in PATCH
    assert "+      { to: '/bodies', icon: TabletSmartphone, labelKey: 'nav.bodies' }," in PATCH
    assert "+    'nav.bodies': 'Bodies'," in PATCH
    # Bodies sits between the Dashboard and Memory items, the vision's order.
    home = PATCH.index("labelKey: 'nav.dashboard'")
    assert home < PATCH.index("labelKey: 'nav.bodies'") < PATCH.index("labelKey: 'nav.memory'")


def test_the_page_calls_only_routes_the_gateway_mounts():
    mounted = set(re.findall(r'"(/api/bodies/[a-z]+)"', PATCH))
    called = set(re.findall(r"(/api/bodies/[a-z]+)", CLIENT))
    assert mounted == called == {
        "/api/bodies/status", "/api/bodies/devices", "/api/bodies/sensors",
        "/api/bodies/packages", "/api/bodies/capture", "/api/bodies/pair",
    }
    for handler in HANDLERS:
        assert f"pub async fn {handler}" in API_BODIES, handler
        assert f"api_bodies::{handler}" in PATCH, handler
    # Pairing is POST, forgetting a device is DELETE on the same path.
    assert "post(api_bodies::handle_bodies_pair).delete(api_bodies::handle_bodies_unpair)" in PATCH
    assert "method: 'POST'" in CLIENT and "method: 'DELETE'" in CLIENT


def test_every_route_is_behind_the_dashboards_auth():
    assert API_BODIES.count("require_auth(&state, &headers)") == len(HANDLERS)
    # The gateway talks to the Body the way the agent does: the Runtime's MCP client.
    assert "use caelza_tools::mcp_client::McpServer;" in API_BODIES
    assert "McpServer::connect(config.clone())" in API_BODIES
    # The browser never learns a Body token or spawns anything; it only sees names.
    assert "Authorization" not in CLIENT and "Bearer" not in CLIENT


def test_tool_classes_are_the_bodys_own():
    assert _rust_str_array("READ_ONLY") == set(srv.READ_ONLY)
    assert _rust_str_array("DESTRUCTIVE") == set(srv.DESTRUCTIVE)


def test_the_page_only_calls_tools_the_body_serves():
    # The handlers only: not the class tables above them, not the Rust tests below.
    handlers = API_BODIES.split("#[cfg(test)]")[0]
    handlers = re.sub(r"const (READ_ONLY|DESTRUCTIVE): &\[&str\] = &\[.*?\];", "", handlers, flags=re.S)
    called = set(re.findall(r'"((?:device|sensors)_[a-z_]+)"', handlers))
    served = set(srv.READ_ONLY) | set(srv.DESTRUCTIVE) | set(srv.NEUTRAL)
    assert called <= served, called - served
    # The destructive ones the page reaches are exactly pairing, which the
    # example risk profile already lists under always_ask for the agent.
    destructive_called = called & set(srv.DESTRUCTIVE)
    assert destructive_called == {"device_pair", "device_unpair"}
    for tool in destructive_called:
        assert f'"body__{tool}"' in EXAMPLE.split("always_ask")[1]


def test_page_uses_the_shared_primitives_and_the_brand_eyebrow():
    for primitive in ("PageHeader", "Card", "StatCard", "Badge", "Button", "ConfirmDialog", "Select"):
        assert primitive in PAGE, primitive
    assert "cz-eyebrow" in PAGE
    assert "Forget this device?" in PAGE
    # Images arrive as base64 JSON and render as data URLs; no second auth path.
    assert "captureDataUrl" in PAGE and "data:${capture.mime};base64," in CLIENT
