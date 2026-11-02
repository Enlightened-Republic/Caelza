"""The looks and the shop (vision M8): every agent's pixel character.

One part library (looks/parts.py) drawn in a key palette, one catalog
(looks/catalog.json), one exporter (scripts/looks.py) writing the PNGs the
dashboard composes; the renderer's maths lives twice (parts.py for previews
and checks, web/src/looks/looks.logic.ts for the dashboard) and these tests
pin the two to each other: the hash and the deal, the colour ramps, the
layer order, the key colours. Patch 0011 and the gateway's api_looks.rs are
pinned the way the other slices are.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = REPO_ROOT / "looks" / "catalog.json"
OVERLAY = REPO_ROOT / "runtime" / "overlay" / "web" / "src"
LOGIC = (OVERLAY / "looks" / "looks.logic.ts").read_text()
LOGIC_TEST = (OVERLAY / "looks" / "looks.logic.test.ts").read_text()
LOOK_TSX = (OVERLAY / "looks" / "Look.tsx").read_text()
LOOKS_PAGE = (OVERLAY / "pages" / "Looks.tsx").read_text()
SHOP_PAGE = (OVERLAY / "pages" / "Shop.tsx").read_text()
API_RS = (REPO_ROOT / "runtime" / "overlay" / "crates" / "caelza-gateway" / "src" / "api_looks.rs").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0011-looks-and-shop.patch").read_text()
# The unlock codes (M8e) moved the Shop's priced-pack strings into patch 0014.
PATCH_UNLOCK = (REPO_ROOT / "runtime" / "patches" / "0014-unlock-codes.patch").read_text()
BUILD_SH = (REPO_ROOT / "runtime" / "build.sh").read_text()
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())

sys.path.insert(0, str(REPO_ROOT / "looks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import parts as lib  # noqa: E402  (imports without Pillow; drawing needs it)

catalog = lib.load_catalog(CATALOG)


def test_the_catalog_the_parts_and_the_exports_agree():
    """Needs Pillow (the brand CI job has it and runs `scripts/looks.py check` too)."""
    pytest.importorskip("PIL")
    import looks as cli

    assert cli.check(catalog) == []
    assert [p["id"] for p in catalog["packs"]] == ["starter", "cosmic", "arcade"]
    assert sum(1 for p in catalog["parts"] if p["pack"] == "starter") >= 25
    out = subprocess.run([sys.executable, "-I", str(REPO_ROOT / "scripts" / "looks.py"), "check"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("ok:")


def test_every_part_renders_in_every_frame_and_only_faces_change_between_frames():
    pytest.importorskip("PIL")
    for pid, part in lib.PARTS.items():
        frames = {f: lib.render_part(pid, f).tobytes() for f in lib.FRAMES}
        if part.layer == "face":
            assert frames["closed"] != frames["open"], f"{pid}: the mouth opens"
            assert frames["closed"] != frames["blink"] or pid == "face.happy", f"{pid}: the eyes close"
        else:
            assert frames["closed"] == frames["open"] == frames["blink"], f"{pid}: only faces animate"
    # A whole look composes, is outlined (the outline colour appears) and recoloured (no key colour survives).
    im = lib.compose(lib.CAEL_LOOK["parts"], "open", lib.CAEL_LOOK["colors"])
    pixels = {px[:3] for px in im.get_flattened_data() if px[3]} if hasattr(im, "get_flattened_data") else {px[:3] for px in im.getdata() if px[3]}
    assert lib.FIXED["o"] in pixels
    keys = {rgb for tones in lib.KEYS.values() for rgb in tones.values()}
    assert not (pixels & keys), "every key colour was swapped"
    assert lib.ramp("#22e6ff")["m"] in pixels, "Cael's cyan eyes"


def test_the_catalog_lists_every_part_once_with_a_starter_for_every_layer():
    """The Pillow-free half of `scripts/looks.py check`, so the Body job keeps the catalog honest."""
    ids = [p["id"] for p in catalog["parts"]]
    assert len(ids) == len(set(ids)) and set(ids) == set(lib.PARTS)
    for p in catalog["parts"]:
        lp = lib.PARTS[p["id"]]
        assert (p["layer"], p["name"], p["pack"], tuple(p["slots"])) == (lp.layer, lp.name, lp.pack, lp.slots), p["id"]
    assert catalog["layers"] == lib.LAYER_ORDER and catalog["frames"] == list(lib.FRAMES) and catalog["slots"] == list(lib.SLOTS)
    for layer in lib.LAYER_ORDER:
        assert any(p["layer"] == layer and p["pack"] == "starter" for p in catalog["parts"]), layer
    assert catalog["cael"] == {"parts": lib.CAEL_LOOK["parts"], "colors": lib.CAEL_LOOK["colors"]}
    for p in catalog["parts"]:
        for path in ([f"{p['layer']}/{p['id'].split('.', 1)[1]}.{f}.png" for f in lib.FRAMES] if p["layer"] == "face" else [f"{p['layer']}/{p['id'].split('.', 1)[1]}.png"]):
            assert (REPO_ROOT / "runtime" / "overlay" / "web" / "public" / "looks" / "parts" / path).is_file(), path
    for pack in catalog["packs"]:
        assert (REPO_ROOT / "runtime" / "overlay" / "web" / "public" / "looks" / "sheets" / f"{pack['id']}.png").is_file(), pack["id"]


def test_the_dashboards_maths_is_parts_pys():
    # The hash: FNV-1a 32-bit, the same vectors the node test pins.
    assert lib.fnv1a("") == 0x811C9DC5 and lib.fnv1a("a") == 0xE40C292C and lib.fnv1a("foobar") == 0xBF9CF968
    assert "0x811c9dc5" in LOGIC and "0x01000193" in LOGIC and 'fnv1a("foobar"), 0xbf9cf968' in LOGIC_TEST
    # The ramps: floor(x + 0.5) on both sides, 40 % toward the outline, 38 % toward white.
    assert lib.ramp("#22e6ff") == {"m": (34, 230, 255), "d": (26, 141, 166), "l": (118, 240, 255)}
    assert "l: [118, 240, 255]" in LOGIC_TEST
    assert "mix(m, OUTLINE, 0.4)" in LOGIC and "mix(m, [255, 255, 255], 0.38)" in LOGIC and "Math.floor(" in LOGIC
    # The keys, the outline, the layers, the slots.
    for slot, tones in lib.KEYS.items():
        for tone, rgb in tones.items():
            assert f"{tone}: [{rgb[0]}, {rgb[1]}, {rgb[2]}]" in LOGIC, (slot, tone)
    assert f"OUTLINE: [number, number, number] = [{lib.FIXED['o'][0]}, {lib.FIXED['o'][1]}, {lib.FIXED['o'][2]}]" in LOGIC
    assert f'LAYERS: readonly Layer[] = {json.dumps(lib.LAYER_ORDER)}' in LOGIC
    assert f'SLOTS: readonly Slot[] = {json.dumps(list(lib.SLOTS))}' in LOGIC
    # The deal: starter parts by layer, h >>> (i * 4); palettes, h >>> (i * 3 + 7).
    assert "(h >>> (i * 4)) % ids.length" in LOGIC and "(h >>> (i * 3 + 7)) % palette.length" in LOGIC
    main = lib.default_look("main", catalog)
    assert all(lib.PARTS[pid].pack == "starter" for pid in main["parts"].values())
    assert lib.default_look("cael", catalog)["parts"] == catalog["cael"]["parts"]
    assert lib.default_look("niba", catalog) != main


def test_the_gateway_keeps_the_look_and_the_wardrobe_on_the_runtime():
    for route in ('"/api/looks/wardrobe"', '"/api/looks/{alias}"'):
        assert route in PATCH, route
    assert "+pub mod api_looks;" in PATCH
    for handler in ("handle_look_get", "handle_look_put", "handle_look_delete", "handle_wardrobe_get", "handle_wardrobe_put"):
        assert f"pub async fn {handler}(" in API_RS, handler
        assert f"api_looks::{handler}" in PATCH, handler
    assert f'LAYERS: [&str; 7] = {json.dumps(lib.LAYER_ORDER)}' in API_RS
    assert f'SLOTS: [&str; 5] = {json.dumps(list(lib.SLOTS))}' in API_RS
    assert 'alias != "wardrobe"' in API_RS, "the wardrobe route never collides with an agent"
    assert "require_auth(&state, &headers)" in API_RS
    assert ".join(\"agents\").join(alias).join(LOOK_FILE)" in API_RS and 'join("looks").join(WARDROBE_FILE)' in API_RS
    assert "std::fs::rename(&tmp, path)" in API_RS, "written whole or not at all"


def test_patch_touches_only_the_files_it_claims():
    touched = sorted({line.split()[1][2:] for line in PATCH.splitlines() if line.startswith("+++ b/")})
    assert touched == [
        "crates/caelza-gateway/src/lib.rs",
        "web/package.json",
        "web/src/components/AgentCard.tsx",
        "web/src/components/layout/Header.tsx",
        "web/src/components/layout/Layout.tsx",
        "web/src/components/layout/Sidebar.tsx",
        "web/src/lib/api.ts",
        "web/src/lib/i18n.ts",
        "web/src/pages/AgentChat.tsx",
        "web/src/router/lazyPages.tsx",
        "web/src/router/router.tsx",
    ]
    assert '+        <Route path="/looks/:alias" element={<Looks />} />' in PATCH and '+        <Route path="/shop" element={<Shop />} />' in PATCH
    assert "+      { to: '/looks', icon: Shirt, labelKey: 'nav.looks' }," in PATCH
    assert "+          <AgentLook alias={agentAlias} size={28} talking={typing} />" in PATCH, "the chat header talks"
    assert "+        <AgentLook alias={agent.alias} size={34} />" in PATCH
    assert "src/pages/setup/setup.logic.test.ts src/looks/looks.logic.test.ts" in PATCH
    assert 'cp "$ROOT/looks/catalog.json" "$WORK/web/src/looks/catalog.json"' in BUILD_SH


def test_every_string_the_pages_use_is_in_the_patch():
    used = set(re.findall(r'"((?:looks|shop)\.[a-z_]+)"', LOOKS_PAGE + SHOP_PAGE))
    used |= {f"looks.layer_{layer}" for layer in lib.LAYER_ORDER} | {f"looks.slot_{slot}" for slot in lib.SLOTS}
    added = set(re.findall(r"^\+    '((?:looks|shop)\.[a-z_]+)': ", PATCH + PATCH_UNLOCK, re.M))
    removed = set(re.findall(r"^-    '((?:looks|shop)\.[a-z_]+)': ", PATCH_UNLOCK, re.M))
    assert used and used <= added - removed, sorted(used - (added - removed))
    assert "+    'nav.looks': 'Looks'," in PATCH and "+    'nav.shop': 'Shop'," in PATCH


def test_the_avatar_is_the_frame_at_the_largest_whole_scale_the_edges_continued():
    """The Python avatar and the dashboard's share one geometry; the CLI writes the file."""
    assert lib.avatar_geometry(512) == {"size": 512, "scale": 11, "ox": 36, "oy": 14}
    assert lib.avatar_geometry(100, 2, 3) == {"size": 100, "scale": 33, "ox": 17, "oy": 0}
    assert "assert.deepEqual(avatarGeometry(AVATAR_SIZE), { size: 512, scale: 11, ox: 36, oy: 14 });" in LOGIC_TEST
    assert "assert.deepEqual(avatarGeometry(100, 2, 3), { size: 100, scale: 33, ox: 17, oy: 0 });" in LOGIC_TEST
    bare = lib.default_look("main", catalog)
    bare["parts"]["backdrop"] = "backdrop.none"
    assert lib.avatar_look(bare)["parts"]["backdrop"] == "backdrop.space"
    assert lib.avatar_look(lib.CAEL_LOOK)["parts"]["backdrop"] == "backdrop.space"
    pytest.importorskip("PIL")
    look = lib.default_look("cael", catalog)
    frame = lib.compose(look["parts"], "closed", look["colors"]).load()
    im = lib.avatar(look, 512)
    assert im.size == (512, 512)
    px = im.load()
    assert px[0, 0] == frame[0, 0] and px[511, 511] == frame[39, 43], "the corners continue the frame's corners"
    assert px[36, 14] == frame[0, 0] and px[36 + 11 * 20 + 5, 14 + 11 * 20 + 5] == frame[20, 20], "scale 11 from (36, 14)"
    assert px[256, 511] == frame[20, 43], "below the frame, its last row goes on (the torso)"
    assert all(px[x, 0][3] == 255 for x in range(512)), "Space behind: no transparent margin"
    # The dashboard's export and the button.
    assert "export async function avatarPng(look: LookData, size = AVATAR_SIZE): Promise<Blob>" in LOOK_TSX
    assert "sampleAvatar(data.data, GRID.width, GRID.height, g)" in LOOK_TSX and 'throw new Error("a piece of the look did not load; try again");' in LOOK_TSX
    assert "export function saveBlob(blob: Blob, filename: string): void" in LOOK_TSX
    assert "saveBlob(await avatarPng(look), `${alias}-avatar.png`);" in LOOKS_PAGE


def test_the_avatar_cli_writes_the_file_for_a_saved_look(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    saved = tmp_path / "look.json"
    look = lib.default_look("main", catalog)
    look["parts"]["backdrop"] = "backdrop.none"
    look["colors"]["hair"] = "#ff2d78"
    saved.write_text(json.dumps(look))
    out = tmp_path / "main-avatar.png"
    r = subprocess.run([sys.executable, "-I", str(REPO_ROOT / "scripts" / "looks.py"), "avatar", "main", str(out), "--look", str(saved), "--size", "128"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == f"wrote {out} (128 x 128)", r.stderr
    im = Image.open(out)
    assert im.size == (128, 128)
    assert im.getpixel((0, 0)) == (*lib.FIXED["space"], 255), "no backdrop saved: Space behind the avatar"
    assert any(im.getpixel((x, y))[:3] == (255, 45, 120) for x in range(0, 128, 2) for y in range(0, 64, 2)), "the saved hair colour is in it"


def test_the_renderer_composes_the_same_way():
    assert 'import catalogJson from "./catalog.json";' in LOOK_TSX
    assert "finishPixels(data.data, sil, width, height, recolorTable(look.colors), det)" in LOOK_TSX, "the detail mask: the outline goes over the backdrop and under the face"
    assert "the outline goes over an opaque backdrop" in LOGIC_TEST
    assert "160" in LOOK_TSX and "2500 + Math.random() * 2500" in LOOK_TSX, "the mouth at 160 ms, a blink every 2.5 to 5 s"
    assert "export function useAgentLook" in LOOK_TSX and "export function AgentLook" in LOOK_TSX


def test_manifest_points_at_the_looks():
    rt = MANIFEST["components"]["runtime"]
    assert rt["looks_catalog"] == "looks/catalog.json"
    assert rt["looks_parts"] == "looks/parts.py"
    assert rt["looks_api"] == "runtime/overlay/crates/caelza-gateway/src/api_looks.rs"
    assert rt["looks_patch"] == "runtime/patches/0011-looks-and-shop.patch"
    for key in ("looks_catalog", "looks_parts", "looks_api", "looks_patch"):
        assert (REPO_ROOT / rt[key]).is_file(), key
