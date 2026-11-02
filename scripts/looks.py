#!/usr/bin/env python3
"""The looks: export the pixel parts, draw the shop's sheets, keep it all in step.

    python3 scripts/looks.py export            # parts -> runtime/overlay/web/public/looks/parts, sheets -> .../sheets
    python3 scripts/looks.py check             # the catalog agrees with looks/parts.py and the exported PNGs are current
    python3 scripts/looks.py render <alias> out.png [--frame open] [--scale 8]
    python3 scripts/looks.py lineup out.png    # Cael and a few dealt defaults, side by side

Every part is drawn once in looks/parts.py in the key palette; `export`
writes one PNG per part (three for a face: closed, open, blink) at 1x, which
the dashboard's renderer composes, outlines and recolours. The sheets show
every part of a pack on a base look, for the Shop page and the docs.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "looks"))
import parts as lib  # noqa: E402

CATALOG = REPO_ROOT / "looks" / "catalog.json"
PUBLIC = REPO_ROOT / "runtime" / "overlay" / "web" / "public" / "looks"
PARTS_DIR = PUBLIC / "parts"
SHEETS_DIR = PUBLIC / "sheets"

#: The base every pack sheet dresses: the starter default, in Cael's colours.
SHEET_BASE_PARTS = {
    "backdrop": "backdrop.none",
    "body": "body.sprout",
    "outfit": "outfit.hoodie",
    "hair": "hair.swoop",
    "hat": "hat.none",
    "face": "face.round",
    "accessory": "accessory.none",
}
SHEET_COLORS = {"skin": "#e0a98a", "hair": "#7b6bff", "outfit": "#1a1250", "accent": "#22e6ff", "eyes": "#22e6ff"}


def png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def part_files(pid: str) -> list[tuple[Path, str]]:
    """(path, frame) for every PNG a part exports."""
    layer, name = pid.split(".", 1)
    if layer == "face":
        return [(PARTS_DIR / layer / f"{name}.{frame}.png", frame) for frame in lib.FRAMES]
    return [(PARTS_DIR / layer / f"{name}.png", "closed")]


def expected_files(catalog: dict) -> dict[Path, bytes]:
    out: dict[Path, bytes] = {}
    for p in catalog["parts"]:
        for path, frame in part_files(p["id"]):
            out[path] = png_bytes(lib.render_part(p["id"], frame))
    return out


def sheet(catalog: dict, pack: str, scale: int = 4, cols: int = 6) -> Image.Image:
    """Every part of a pack on the base look, labelled, in the pack's own order."""
    items = [p for p in catalog["parts"] if p["pack"] == pack]
    if not items:
        im = Image.new("RGBA", (cols * lib.W * scale, lib.H * scale + 24), (12, 9, 24, 255))
        return im
    cw, ch = lib.W * scale + 8, lib.H * scale + 26
    rows = -(-len(items) // cols)
    im = Image.new("RGBA", (cw * cols, ch * rows), (12, 9, 24, 255))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=12)
    except TypeError:
        font = ImageFont.load_default()
    for i, p in enumerate(items):
        parts = dict(SHEET_BASE_PARTS)
        parts[p["layer"]] = p["id"]
        frame = "open" if p["layer"] == "face" else "closed"
        char = lib.compose(parts, frame, SHEET_COLORS).resize((lib.W * scale, lib.H * scale), Image.NEAREST)
        ox, oy = (i % cols) * cw + 4, (i // cols) * ch + 4
        d.rectangle([ox - 2, oy - 2, ox + lib.W * scale + 1, oy + lib.H * scale + 1], fill=(18, 14, 34, 255))
        im.alpha_composite(char, (ox, oy))
        d.text((ox, oy + lib.H * scale + 4), p["name"], fill=(168, 168, 192, 255), font=font)
    return im


def export(catalog: dict) -> int:
    n = 0
    for path, data in expected_files(catalog).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
            n += 1
    SHEETS_DIR.mkdir(parents=True, exist_ok=True)
    for pack in catalog["packs"]:
        data = png_bytes(sheet(catalog, pack["id"]))
        path = SHEETS_DIR / f"{pack['id']}.png"
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
            n += 1
    return n


def check(catalog: dict) -> list[str]:
    problems: list[str] = []
    ids = {p["id"] for p in catalog["parts"]}
    if ids != set(lib.PARTS):
        problems.append(f"catalog parts and parts.py differ: only in catalog {sorted(ids - set(lib.PARTS))}, only in parts.py {sorted(set(lib.PARTS) - ids)}")
    packs = {p["id"] for p in catalog["packs"]}
    for p in catalog["parts"]:
        lp = lib.PARTS.get(p["id"])
        if lp is None:
            continue
        if p["layer"] != lp.layer or p["name"] != lp.name or p["pack"] != lp.pack or tuple(p["slots"]) != lp.slots:
            problems.append(f"{p['id']}: catalog says {p['layer']}/{p['name']}/{p['pack']}/{p['slots']}, parts.py says {lp.layer}/{lp.name}/{lp.pack}/{list(lp.slots)}")
        if p["pack"] not in packs:
            problems.append(f"{p['id']}: pack {p['pack']!r} is not in the catalog")
    if catalog["layers"] != lib.LAYER_ORDER:
        problems.append("catalog layers are not parts.py's order")
    if catalog["frames"] != list(lib.FRAMES) or catalog["slots"] != list(lib.SLOTS):
        problems.append("catalog frames or slots differ from parts.py")
    for layer in lib.LAYER_ORDER:
        if not any(p["layer"] == layer and p["pack"] == "starter" for p in catalog["parts"]):
            problems.append(f"the starter pack has no {layer} part (every default needs one)")
    for pack in catalog["packs"]:
        if pack["status"] not in ("available", "soon"):
            problems.append(f"pack {pack['id']}: status must be available or soon")
        if pack["status"] == "soon" and any(p["pack"] == pack["id"] for p in catalog["parts"]):
            problems.append(f"pack {pack['id']}: a soon pack lists parts")
        if pack["status"] == "available" and pack["id"] != "starter" and not any(p["pack"] == pack["id"] for p in catalog["parts"]):
            problems.append(f"pack {pack['id']}: an available pack with no parts")
        if pack["price"] != "free" and "unlock" not in pack:
            problems.append(f"pack {pack['id']}: a priced pack needs an unlock")
    for slot in lib.SLOTS:
        for h in catalog["colors"][slot]:
            if len(h) != 7 or not h.startswith("#"):
                problems.append(f"colors.{slot}: {h!r} is not #rrggbb")
    cael = catalog["cael"]
    if cael != {"parts": lib.CAEL_LOOK["parts"], "colors": lib.CAEL_LOOK["colors"]}:
        problems.append("the catalog's cael look differs from parts.py CAEL_LOOK")
    for pid in cael["parts"].values():
        if pid not in ids:
            problems.append(f"cael wears {pid}, which is not in the catalog")
    # Every part renders in every frame, and the key palette is the only recolourable thing in it.
    keys = {rgb for tones in lib.KEYS.values() for rgb in tones.values()}
    fixed = set(lib.FIXED.values())
    for pid in lib.PARTS:
        for frame in lib.FRAMES:
            im = lib.render_part(pid, frame)
            for px in im.get_flattened_data() if hasattr(im, 'get_flattened_data') else im.getdata():
                if px[3] and (px[0], px[1], px[2]) not in keys | fixed:
                    problems.append(f"{pid} ({frame}) has the colour {px[:3]} which is neither a key nor a fixed colour")
                    break
    for path, data in expected_files(catalog).items():
        if not path.exists():
            problems.append(f"missing {path.relative_to(REPO_ROOT)}: run scripts/looks.py export")
        elif path.read_bytes() != data:
            problems.append(f"stale {path.relative_to(REPO_ROOT)}: run scripts/looks.py export")
    for pack in catalog["packs"]:
        path = SHEETS_DIR / f"{pack['id']}.png"
        if not path.exists() or path.read_bytes() != png_bytes(sheet(catalog, pack["id"])):
            problems.append(f"sheet for {pack['id']} is missing or stale: run scripts/looks.py export")
    return problems


def render_alias(catalog: dict, alias: str, frame: str, scale: int) -> Image.Image:
    look = lib.default_look(alias, catalog)
    return lib.compose(look["parts"], frame, look["colors"]).resize((lib.W * scale, lib.H * scale), Image.NEAREST)


def lineup(catalog: dict, aliases: list[str], scale: int = 6) -> Image.Image:
    im = Image.new("RGBA", (len(aliases) * (lib.W * scale + 12) + 12, lib.H * scale + 40), (5, 3, 16, 255))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:
        font = ImageFont.load_default()
    for i, alias in enumerate(aliases):
        x = 12 + i * (lib.W * scale + 12)
        im.alpha_composite(render_alias(catalog, alias, "closed", scale), (x, 8))
        d.text((x, lib.H * scale + 14), alias, fill=(168, 168, 192, 255), font=font)
    return im


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export")
    sub.add_parser("check")
    r = sub.add_parser("render")
    r.add_argument("alias")
    r.add_argument("out", type=Path)
    r.add_argument("--frame", default="closed", choices=lib.FRAMES)
    r.add_argument("--scale", type=int, default=8)
    lu = sub.add_parser("lineup")
    lu.add_argument("out", type=Path)
    lu.add_argument("--aliases", default="cael,main,niba,atlas,pixel,juno")
    args = ap.parse_args(argv)
    catalog = lib.load_catalog(CATALOG)
    if args.cmd == "export":
        n = export(catalog)
        print(f"exported: {n} file(s) written, {len(lib.PARTS)} parts, {len(catalog['packs'])} sheets")
        return 0
    if args.cmd == "render":
        render_alias(catalog, args.alias, args.frame, args.scale).save(args.out)
        print(f"wrote {args.out}")
        return 0
    if args.cmd == "lineup":
        lineup(catalog, [a.strip() for a in args.aliases.split(",") if a.strip()]).save(args.out)
        print(f"wrote {args.out}")
        return 0
    problems = check(catalog)
    for line in problems:
        print(line, file=sys.stderr)
    if not problems:
        print(f"ok: {len(lib.PARTS)} parts in {len(catalog['packs'])} packs, exports current")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
