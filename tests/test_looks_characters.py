"""Looks: added packs worn in one tap, and a downloaded PNGtuber as a character (patch 0031).

The gateway's character library (api_looks.rs), the dashboard's import
(looks/characters.logic.ts, lib/characters.ts) and the patch that routes it
must agree on the ids, the frames and the size limit. The behaviour itself is
under `cargo test -p caelza-gateway api_looks` and `node --experimental-strip-types
--test src/looks/looks.logic.test.ts` in the staged web tree.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay"
WEB = OVERLAY / "web" / "src"
API = (OVERLAY / "crates" / "caelza-gateway" / "src" / "api_looks.rs").read_text(encoding="utf-8")
LOGIC = (WEB / "looks" / "characters.logic.ts").read_text(encoding="utf-8")
LOOKS_LOGIC = (WEB / "looks" / "looks.logic.ts").read_text(encoding="utf-8")
PATCH = (REPO_ROOT / "runtime" / "patches" / "0031-looks-packs-and-characters.patch").read_text(encoding="utf-8")
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text(encoding="utf-8"))


def test_the_manifest_names_the_patch():
    assert MANIFEST["components"]["runtime"]["looks_characters_patch"] == "runtime/patches/0031-looks-packs-and-characters.patch"


def test_the_patch_routes_every_handler():
    for route, handlers in {
        '"/api/looks/characters"': ["handle_characters_list"],
        '"/api/looks/characters/{id}"': ["handle_character_put", "handle_character_delete"],
        '"/api/looks/characters/{id}/{frame}"': ["handle_character_frame_get", "handle_character_frame_put"],
    }.items():
        assert route in PATCH, route
        for h in handlers:
            assert f"api_looks::{h}" in PATCH, h
            assert f"pub async fn {h}(" in API, h


def test_a_frame_fits_under_the_gateways_body_limit_on_both_sides():
    assert "pub const MAX_FRAME_BYTES: usize = 60 * 1024;" in API
    assert "export const MAX_FRAME_BYTES = 60 * 1024;" in LOGIC
    assert 60 * 1024 < 65_536  # lib.rs MAX_BODY_SIZE, the gateway-wide RequestBodyLimitLayer


def test_the_frames_and_the_ids_are_the_same_on_both_sides():
    assert 'pub const FRAMES: [&str; 3] = ["closed", "open", "blink"];' in API
    ts = re.search(r"export const CHARACTER_ID = (/.+/);", LOGIC).group(1)
    assert ts == re.search(r"export const CHARACTER_ID = (/.+/);", LOOKS_LOGIC).group(1)
    assert ts == "/^[a-z0-9][a-z0-9-]{0,47}$/"
    assert "id.len() <= 48" in API


def test_characters_is_never_an_agent_alias():
    assert "&& alias != CHARACTERS_DIR" in API
    assert 'pub const CHARACTERS_DIR: &str = "characters";' in API


def test_a_look_keeps_its_parts_under_a_character():
    # The parts stay required: a look wearing a character still falls back to them,
    # and the agent's own look tool (caelza-tools look.rs) edits them.
    assert 'clean["character"] = Value::String(id.clone())' in API
    assert '.ok_or_else(|| format!("parts.{layer} is required"))?' in API


def test_the_strings_and_the_pages_say_where_a_pack_went():
    shop = (WEB / "pages" / "Shop.tsx").read_text(encoding="utf-8")
    looks = (WEB / "pages" / "Looks.tsx").read_text(encoding="utf-8")
    assert 't("shop.wear_it")' in shop and 't("shop.added")' in shop
    assert "data-packs-card" in looks and "wearPack(" in looks
    assert "data-characters-card" in looks and "importCharacter(" in looks
    for key in ["shop.wear_it", "shop.added", "looks.packs_title", "looks.pack_wear", "looks.characters_title", "looks.character_import"]:
        assert f"+    '{key}':" in PATCH, key
