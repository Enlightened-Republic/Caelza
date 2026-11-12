"""UI phase 2a: the Memory page. The gateway proxy module, the page, the
client and the wiring patch stay in step; the routes the page calls are the
routes the gateway mounts."""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay"
PATCH = (REPO_ROOT / "runtime" / "patches" / "0003-mind-page.patch").read_text()
# Phase 3a (Home) added the digest route to the same module; its wiring lives in patch 0005.
PATCH_HOME = (REPO_ROOT / "runtime" / "patches" / "0005-home-procedures.patch").read_text()
PATCH_SHARE = (REPO_ROOT / "runtime" / "patches" / "0016-mind-share.patch").read_text()
PATCH_INSTALL = (REPO_ROOT / "runtime" / "patches" / "0017-mind-install.patch").read_text()
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
    mounted = {route for patch in (PATCH, PATCH_HOME, PATCH_SHARE, PATCH_INSTALL) for route in re.findall(r'"(/api/mind/[a-z]+)"', patch)}
    called = set(re.findall(r"(/api/mind/[a-z]+)", CLIENT))
    assert mounted == called == {"/api/mind/status", "/api/mind/recall", "/api/mind/forget", "/api/mind/review", "/api/mind/digest",
                                 "/api/mind/share", "/api/mind/probe", "/api/mind/install"}
    for handler in ("handle_mind_status", "handle_mind_recall", "handle_mind_forget",
                    "handle_mind_review_list", "handle_mind_review_decide"):
        assert f"pub async fn {handler}" in API_MIND, handler
        assert f"api_mind::{handler}" in PATCH, handler
    assert "api_mind::handle_mind_digest" in PATCH_HOME


def test_tokens_stay_on_the_host():
    # The page never sees a bearer token for the brain service: it only reads
    # whether one exists and where the gateway expects it. The one exception is
    # the join code's token on the device that joins another device's Mind: the
    # probe hands it back to the page that pasted the code, for the one config
    # write that stores it encrypted (tests/test_mind_share.py pins that path).
    code = "\n".join(line for line in CLIENT.splitlines() if not line.strip().startswith("//") and not line.strip().startswith("/**"))
    probe_field = "  /** The code's token, back from the gateway for the config write. */\n  token: string;\n"
    assert probe_field in CLIENT.split("export interface MindProbeResult")[1].split("}")[0] + "}"
    # token_id is the entry's public handle (what `token list` prints), share_tokens a count.
    scrubbed = code.replace("has_token", "").replace("token_file", "").replace("share_tokens", "").replace("tokens_path", "").replace("tokens_dir", "").replace("token_id", "").replace("  token: string;\n", "", 1)
    assert "token" not in scrubbed.lower()
    assert "Authorization" not in CLIENT and "Bearer" not in CLIENT
    assert "require_auth(&state, &headers)" in API_MIND
    assert API_MIND.count("require_auth(&state, &headers)") == 6, "every route (digest included) is behind the dashboard's auth"
    assert "XanimaMemory::new" in API_MIND and "has_token" in API_MIND


def test_page_uses_the_shared_primitives_and_the_brand_eyebrow():
    for primitive in ("PageHeader", "Card", "StatCard", "Badge", "Button", "ConfirmDialog", "Select"):
        assert primitive in PAGE, primitive
    assert "cz-eyebrow" in PAGE
    assert "Forget this memory?" in PAGE
