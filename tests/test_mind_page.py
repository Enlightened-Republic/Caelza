"""UI phase 2a: the Memory page. The gateway proxy module, the page, the
client and the wiring patch stay in step; the routes the page calls are the
routes the gateway mounts."""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay"
PATCH = (REPO_ROOT / "runtime" / "patches" / "0003-mind-page.patch").read_text()
API_MIND = (OVERLAY / "crates" / "caelza-gateway" / "src" / "api_mind.rs").read_text()
CLIENT = (OVERLAY / "web" / "src" / "lib" / "mind.ts").read_text()
PAGE = (OVERLAY / "web" / "src" / "pages" / "Memory.tsx").read_text()


def test_patch_touches_only_the_files_it_claims():
    touched = sorted({line.split()[1][2:] for line in PATCH.splitlines() if line.startswith("+++ b/")})
    assert touched == [
        "crates/caelza-gateway/src/lib.rs",
        "web/src/components/layout/Sidebar.tsx",
        "web/src/router/lazyPages.tsx",
        "web/src/router/router.tsx",
    ]
    assert "+pub mod api_mind;" in PATCH
    assert '+        <Route path="/memory" element={<Memory />} />' in PATCH
    assert "-        <Route path=\"/memory\" element={<Navigate to=\"/?tab=memories\" replace />} />" in PATCH
    assert "+      { to: '/memory', icon: Brain, labelKey: 'nav.memory' }," in PATCH


def test_the_page_calls_only_routes_the_gateway_mounts():
    mounted = set(re.findall(r'"(/api/mind/[a-z]+)"', PATCH))
    called = set(re.findall(r"(/api/mind/[a-z]+)", CLIENT))
    assert mounted == called == {"/api/mind/status", "/api/mind/recall", "/api/mind/forget", "/api/mind/review"}
    for handler in ("handle_mind_status", "handle_mind_recall", "handle_mind_forget",
                    "handle_mind_review_list", "handle_mind_review_decide"):
        assert f"pub async fn {handler}" in API_MIND, handler
        assert f"api_mind::{handler}" in PATCH, handler


def test_tokens_stay_on_the_host():
    # The page never sees a bearer token for the brain service: it only reads
    # whether one exists and where the gateway expects it.
    code = "\n".join(line for line in CLIENT.splitlines() if not line.strip().startswith("//"))
    assert "token" not in code.replace("has_token", "").replace("token_file", "").lower()
    assert "Authorization" not in CLIENT and "Bearer" not in CLIENT
    assert "require_auth(&state, &headers)" in API_MIND
    assert API_MIND.count("require_auth(&state, &headers)") == 5, "every route is behind the dashboard's auth"
    assert "XanimaMemory::new" in API_MIND and "has_token" in API_MIND


def test_page_uses_the_shared_primitives_and_the_brand_eyebrow():
    for primitive in ("PageHeader", "Card", "StatCard", "Badge", "Button", "ConfirmDialog", "Select"):
        assert primitive in PAGE, primitive
    assert "cz-eyebrow" in PAGE
    assert "Forget this memory?" in PAGE
