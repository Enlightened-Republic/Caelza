"""UI phase 1 (vision §7): the dashboard wears the brand and installs as an
app. The overlay files, the patch and the asset renderer stay in step."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay" / "web"
PATCH = (REPO_ROOT / "runtime" / "patches" / "0002-ui-phase1.patch").read_text()
BRAND_CSS = (OVERLAY / "src" / "caelza-brand.css").read_text()
SW = (OVERLAY / "public" / "sw.js").read_text()
MANIFEST = json.loads((OVERLAY / "public" / "manifest.webmanifest").read_text())
TOKENS = json.loads((REPO_ROOT / "brand" / "tokens.json").read_text())


def test_manifest_is_an_installable_caelza():
    assert MANIFEST["name"] == MANIFEST["short_name"] == "Caelza"
    assert MANIFEST["display"] == "standalone"
    # Relative to /_app/manifest.webmanifest, so a path prefix still resolves.
    assert MANIFEST["start_url"] == MANIFEST["scope"] == "../"
    assert MANIFEST["theme_color"] == MANIFEST["background_color"] == TOKENS["color"]["void"]
    sizes = {(i["sizes"], i.get("purpose", "any")) for i in MANIFEST["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes
    for icon in MANIFEST["icons"]:
        assert not icon["src"].startswith("/"), "icon paths are relative to the manifest"


def test_service_worker_never_caches_the_gateway():
    for live in ("api", "ws", "acp", "admin", "pair", "health", "webhook"):
        assert re.search(rf"\b{live}\b", SW), live
    assert "self.skipWaiting()" in SW and "clients.claim()" in SW
    assert "/_app/assets/" in SW  # hashed bundles are cache-first
    assert "request.method !== 'GET'" in SW


def test_brand_css_covers_every_vendored_font():
    vendored = sorted(p.name for p in (REPO_ROOT / "brand" / "fonts").glob("*.ttf"))
    referenced = sorted(set(re.findall(r"/fonts/([A-Za-z0-9-]+\.ttf)", BRAND_CSS)))
    assert referenced == vendored == [
        "InterTight-400.ttf",
        "InterTight-700.ttf",
        "JetBrainsMono-500.ttf",
        "Orbitron-900.ttf",
    ]
    assert "font-family: 'Orbitron'" in BRAND_CSS and ".cz-wordmark" in BRAND_CSS
    assert "ENLIGHTENED REPUBLIC" in (OVERLAY / "src" / "components" / "brand" / "CaelzaLockup.tsx").read_text()


def test_patch_touches_only_the_files_it_claims():
    touched = sorted({line.split()[1][2:] for line in PATCH.splitlines() if line.startswith("+++ b/")})
    assert touched == [
        "crates/caelza-gateway/src/static_files.rs",
        "web/index.html",
        "web/src/App.tsx",
        "web/src/components/SettingsModal.tsx",
        "web/src/components/layout/Sidebar.tsx",
        "web/src/contexts/ThemeContext.tsx",
        "web/src/index.css",
        "web/src/main.tsx",
    ]
    assert '+@import "./caelza-brand.css";' in PATCH
    assert "+    <link rel=\"manifest\" href=\"/_app/manifest.webmanifest\" />" in PATCH
    assert "service-worker-allowed" in PATCH
    assert "+  uiFont: 'inter-tight'," in PATCH


def test_asset_renderer_writes_fonts_and_pwa_icons(tmp_path):
    pytest.importorskip("PIL")
    sys.path.insert(0, str(REPO_ROOT / "brand"))
    import make_assets  # noqa: E402

    icon = make_assets.maskable_icon(64)
    assert icon.size == (64, 64)
    # The maskable icon has an opaque void backdrop: every launcher shape keeps the bolt.
    assert icon.getpixel((1, 1))[3] == 255
    make_assets.render_runtime(tmp_path)
    public = tmp_path / "web" / "public"
    for name in ("icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png", "logo.png"):
        assert (public / name).is_file(), name
    assert sorted(p.name for p in (public / "fonts").glob("*.ttf")) == [
        "InterTight-400.ttf",
        "InterTight-700.ttf",
        "JetBrainsMono-500.ttf",
        "Orbitron-900.ttf",
    ]
    assert (public / "fonts" / "OFL-Orbitron.txt").is_file(), "the licences travel with the fonts"
