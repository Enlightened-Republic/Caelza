"""The brand pass over every dashboard page (vision M4 phase 4b).

The theme map gives the dashboard our palette; the pass makes it ours: the
mark and the wordmark in the top bar, page titles in the mark gradient, the
primary action filled cyan → violet, Space with the nebula glows behind every
page. Most of it is CSS in the overlay's brand stylesheet; patch 0010 carries
the four hunks CSS cannot (the top bar, the layout root, PageHeader, Button).
"""
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PATCH = (REPO_ROOT / "runtime" / "patches" / "0010-brand-pass.patch").read_text()
BRAND_CSS = (REPO_ROOT / "runtime" / "overlay" / "web" / "src" / "caelza-brand.css").read_text()
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
TOKENS = json.loads((REPO_ROOT / "brand" / "tokens.json").read_text())

sys.path.insert(0, str(REPO_ROOT / "runtime" / "lib"))
import dashboard_theme  # noqa: E402


def test_patch_touches_only_the_files_it_claims():
    touched = sorted({line.split()[1][2:] for line in PATCH.splitlines() if line.startswith("+++ b/")})
    assert touched == [
        "web/src/components/layout/Header.tsx",
        "web/src/components/layout/Layout.tsx",
        "web/src/components/ui/Button.tsx",
        "web/src/components/ui/PageHeader.tsx",
    ]


def test_the_top_bar_wears_the_mark_and_the_wordmark_on_every_width():
    assert "+import { Mark, Wordmark } from '@/components/brand/CaelzaLockup';" in PATCH
    assert "+            <Mark src={`${basePath}/_app/logo.png`} size={28} />" in PATCH
    # The wordmark yields below 460 px: at 390 the six controls fill the bar and it was drawn under the palette button.
    assert '+            <Wordmark size="sm" className="hidden min-[460px]:inline" />' in PATCH
    assert '+          <div className="flex items-center gap-2 min-w-0">' in PATCH
    # The page title keeps its place on a desktop; the page's own header carries it on a phone.
    assert '+          <h1 className="hidden md:block' in PATCH
    assert '-          <h1 className="h-9 leading-9 text-lg font-semibold tracking-tight truncate min-w-0" style={{ color: \'var(--pc-text-primary)\' }}>{pageTitle}</h1>' in PATCH
    assert '+      <header className="cz-topbar' in PATCH and ".cz-topbar {" in BRAND_CSS


def test_titles_buttons_and_the_backdrop_take_the_brand():
    assert '+        <h1 className="cz-page-title' in PATCH and ".cz-page-title {" in BRAND_CSS
    assert "+    'cz-btn-gradient bg-pc-accent border-transparent" in PATCH and ".cz-btn-gradient," in BRAND_CSS
    assert '+    <div className="cz-space min-h-screen bg-pc-base text-pc-text">' in PATCH and ".cz-space {" in BRAND_CSS
    # The gradient is the mark's (cyan → violet → purple), not the parent's.
    assert "background: var(--cz-gradient-mark);" in BRAND_CSS.split(".cz-page-title {")[1].split("}")[0]
    # The glows fall back to nothing, so a theme without them gets a plain base.
    assert "var(--cz-glow-1, transparent)" in BRAND_CSS and "var(--cz-glow-2, transparent)" in BRAND_CSS
    # The glows on a fixed layer of their own: background-attachment: fixed is ignored by iOS Safari.
    assert ".cz-space::before {" in BRAND_CSS and "background-attachment: fixed" not in BRAND_CSS
    # Cael's bubble takes the theme's surface in the dashboard; the setup page (Space in every theme) keeps the dark glass.
    bubble = BRAND_CSS.split(".cz-bubble {")[1].split("}")[0]
    assert "background: var(--pc-bg-elevated);" in bubble and ".cz-setup .cz-bubble {" in BRAND_CSS
    # Text the owner acts on is never the muted grey (4.1:1 on Space, under AA at 13-14 px).
    for rule in (".cz-btn-text {", ".cz-setup-foot a {", ".cz-kicker {"):
        assert "color: var(--pc-text-secondary);" in BRAND_CSS.split(rule)[1].split("}")[0], rule
    # The pairing screen's and the error boundary's primary button follow.
    assert re.search(r"^\.btn-electric \{", BRAND_CSS, re.M)


def test_the_theme_carries_the_glow_colours():
    dark, light = dashboard_theme.theme_entries(TOKENS)
    purple = TOKENS["color"]["purple"]
    r, g, b = int(purple[1:3], 16), int(purple[3:5], 16), int(purple[5:7], 16)
    assert dark["vars"]["--cz-glow-1"] == f"rgba({r},{g},{b},0.22)"
    assert dark["vars"]["--cz-glow-2"].startswith("rgba(34,230,255,")
    # Faint on the light base: a tint, not a glow.
    assert float(light["vars"]["--cz-glow-1"].rsplit(",", 1)[1].rstrip(")")) < 0.1
    assert float(light["vars"]["--cz-glow-2"].rsplit(",", 1)[1].rstrip(")")) < 0.1
    # The title gradient per theme: the mark's on dark; on light it starts from the light primary (the mark's
    # cyan is 1.4:1 on the light base). The theme vars go inline on :root, so they win over the stylesheet's default.
    assert dark["vars"]["--cz-gradient-mark"] == "linear-gradient(90deg, #22e6ff 0%, #7b6bff 50%, #b44fff 100%)"
    assert light["vars"]["--cz-gradient-mark"].startswith("linear-gradient(90deg, #0a8fb0 0%,")


def test_manifest_points_at_the_pass():
    rt = MANIFEST["components"]["runtime"]
    assert rt["brand_pass_patch"] == "runtime/patches/0010-brand-pass.patch"
    assert (REPO_ROOT / rt["brand_pass_patch"]).is_file()
