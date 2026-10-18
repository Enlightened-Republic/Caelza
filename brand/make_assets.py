#!/usr/bin/env python3
"""Render the Caelza mark, favicons, app icons and banners with Pillow.

    python3 brand/make_assets.py                 # → brand/out/
    python3 brand/make_assets.py --runtime DIR   # write into a staged runtime tree

Caelza is an Enlightened Republic product: the mark is the ER neon ring opened
into a C, in the ER gradient, with a yellow signal star in the gap; banners use
the Build Lab backdrop (purple/pink radial glows over a dot grid) and the
"ENLIGHTENED REPUBLIC™ PRESENTS" eyebrow in JetBrains Mono. Everything is drawn
geometrically from brand/tokens.json so builds are reproducible with no SVG
rasteriser; brand/logo.svg carries the same geometry for design tools.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
TOKENS = json.loads((HERE / "tokens.json").read_text(encoding="utf-8"))
C = TOKENS["color"]
PARENT = TOKENS["parent"]

SS = 4  # supersampling factor for antialiasing

RGBA = tuple[int, int, int, int]


def _hex(h: str, a: int = 255) -> RGBA:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def _lerp(a: RGBA, b: RGBA, t: float) -> RGBA:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(4))  # type: ignore[return-value]


def _gradient(t: float) -> RGBA:
    """The ER gradient along the ring: cyan (t=0) → purple (0.5) → pink (1)."""
    stops = [_hex(C["gradient"][2]), _hex(C["gradient"][1]), _hex(C["gradient"][0])]
    if t <= 0.5:
        return _lerp(stops[0], stops[1], t / 0.5)
    return _lerp(stops[1], stops[2], (t - 0.5) / 0.5)


def _font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    rel = TOKENS["font"]["files"][kind]
    candidates = [HERE / rel]
    if kind == "mono":
        candidates += [Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf")]
    elif kind == "display":
        candidates += [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")]
    else:
        candidates += [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    for p in candidates:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()  # type: ignore[return-value]


def _tracked_text(d: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.FreeTypeFont,
                  fill: RGBA, tracking_em: float) -> int:
    """Draw text with letter-spacing (as a fraction of the font size). Returns end x."""
    x, y = xy
    extra = int(font.size * tracking_em)
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += int(d.textlength(ch, font=font)) + extra
    return x


# ---------------------------------------------------------------------------
# The mark
# ---------------------------------------------------------------------------

def draw_mark(size: int, *, background: str | None = None, radius_frac: float = 0.0,
              glow: bool = True) -> Image.Image:
    s = size * SS
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    if background:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * radius_frac), fill=_hex(background))
        # Faint purple glow at the top, like the Build Lab hero backdrop.
        halo = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        hd = ImageDraw.Draw(halo)
        hd.ellipse([-s * 0.2, -s * 0.55, s * 1.2, s * 0.45], fill=_hex(C["purple"], 40))
        halo = halo.filter(ImageFilter.GaussianBlur(s * 0.12))
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * radius_frac), fill=255)
        im.paste(Image.alpha_composite(im, halo), (0, 0), mask)
        d = ImageDraw.Draw(im)

    M = TOKENS["mark"]
    cx = cy = s / 2
    R = s * M["ring_radius"]
    W = s * M["ring_width"]
    gap_half = M["gap_half_angle_deg"]
    start, end = gap_half, 360 - gap_half           # PIL: 0° = 3 o'clock, clockwise
    bbox = [cx - R, cy - R, cx + R, cy + R]

    def paint_ring(target: Image.Image, width: float, alpha: int) -> None:
        td = ImageDraw.Draw(target)
        steps = 240
        for i in range(steps):
            a0 = start + (end - start) * i / steps
            a1 = start + (end - start) * (i + 1) / steps + 0.6   # overlap hides seams
            col = _gradient(i / steps)
            td.arc(bbox, a0, a1, fill=(col[0], col[1], col[2], alpha), width=int(width))
        for ang, t in ((start, 0.0), (end, 1.0)):   # round caps
            x = cx + R * math.cos(math.radians(ang))
            y = cy + R * math.sin(math.radians(ang))
            col = _gradient(t)
            td.ellipse([x - width / 2, y - width / 2, x + width / 2, y + width / 2],
                       fill=(col[0], col[1], col[2], alpha))

    # Star geometry (shared by glow and crisp layers).
    sx, sy = cx + R * 1.02, cy
    outer, inner = s * M["star_outer"], s * M["star_inner"]
    star = []
    for k in range(8):
        ang = math.radians(-90 + 45 * k)
        rad = outer if k % 2 == 0 else inner
        star.append((sx + rad * math.cos(ang), sy + rad * math.sin(ang)))

    if glow and size >= 48:
        layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        paint_ring(layer, W * 1.6, 110)
        ImageDraw.Draw(layer).polygon(star, fill=_hex(C["yellow"], 120))
        layer = layer.filter(ImageFilter.GaussianBlur(s * 0.035))
        im = Image.alpha_composite(im, layer)

    crisp = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    paint_ring(crisp, W, 255)
    ImageDraw.Draw(crisp).polygon(star, fill=_hex(C["yellow"]))
    im = Image.alpha_composite(im, crisp)
    return im.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Banner: Build Lab backdrop + mark + "ENLIGHTENED REPUBLIC™ PRESENTS / CAELZA"
# ---------------------------------------------------------------------------

def _backdrop(w: int, h: int) -> Image.Image:
    im = Image.new("RGBA", (w, h), _hex(C["void"]))
    # Dot grid, 24 px at 1x.
    d = ImageDraw.Draw(im)
    step = 24 * 2
    for y in range(0, h, step):
        for x in range(0, w, step):
            d.point((x, y), fill=(255, 255, 255, 8))
    # Purple glow at top centre, pink glow at the right.
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([w * 0.1, -h * 0.9, w * 0.9, h * 0.5], fill=_hex(C["purple"], 42))
    gd.ellipse([w * 0.55, -h * 0.2, w * 1.15, h * 0.8], fill=_hex(C["pink"], 18))
    glow = glow.filter(ImageFilter.GaussianBlur(h * 0.18))
    return Image.alpha_composite(im, glow)


def draw_banner(w: int, h: int, *, with_text: bool = True) -> Image.Image:
    W, H = w * 2, h * 2
    im = _backdrop(W, H)

    mark = draw_mark(int(H * 0.64))
    mx = int(W * 0.07)
    im.alpha_composite(mark, (mx, int((H - mark.height) / 2)))

    if with_text:
        d = ImageDraw.Draw(im)
        eyebrow = _font("mono", int(H * 0.052))
        title = _font("display", int(H * 0.40))
        sub = _font("body", int(H * 0.085))
        meta = _font("mono", int(H * 0.040))

        x = mx + mark.width + int(H * 0.16)
        y = int(H * 0.17)
        _tracked_text(d, (x, y), PARENT["presents"], eyebrow, _hex(C["text_dim"]), 0.16)
        y += int(H * 0.11)
        _tracked_text(d, (x, y), "CAELZA", title, _hex(C["text"]), 0.04)
        y += int(H * 0.47)
        d.text((x + int(H * 0.01), y), TOKENS["tagline"], font=sub, fill=_hex(C["text_muted"]))

        # Bottom-right meta line with the teal status dot, as on the Build Lab hero.
        label = f"{PARENT['est']}   ·   {PARENT['site'].removeprefix('https://')}"
        tw = int(d.textlength(label, font=meta)) + int(len(label) * meta.size * 0.04)
        lx, ly = W - tw - int(H * 0.08), H - int(H * 0.11)
        dot_r = int(H * 0.012)
        d.ellipse([lx - dot_r * 4, ly + meta.size * 0.45 - dot_r, lx - dot_r * 2, ly + meta.size * 0.45 + dot_r],
                  fill=_hex(C["teal"]))
        _tracked_text(d, (lx, ly), label, meta, _hex(C["text_dim"]), 0.04)

        # Gradient hairline under the lockup.
        gy = int(H * 0.21) + int(H * 0.11) + int(H * 0.47) + int(H * 0.13)
        gw = int(W * 0.30)
        for i in range(gw):
            col = _gradient(1 - i / gw)
            d.line([(x + i, gy), (x + i, gy + 2)], fill=(col[0], col[1], col[2], 200))

    return im.resize((w, h), Image.LANCZOS).convert("RGB")


# ---------------------------------------------------------------------------

def save_png(im: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "PNG", optimize=True)


def render_set(out: Path) -> None:
    """Loose asset set for the repo (brand/out)."""
    save_png(draw_mark(1024), out / "caelza-mark-1024.png")
    save_png(draw_mark(512), out / "caelza-mark-512.png")
    save_png(draw_mark(512, background=C["void"], radius_frac=0.22), out / "caelza-icon-512.png")
    save_png(draw_banner(1600, 500), out / "caelza-banner.png")
    save_png(draw_banner(1600, 500, with_text=False), out / "caelza-banner-bg.png")
    draw_mark(256).save(out / "favicon.ico", format="ICO",
                        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def render_runtime(root: Path) -> None:
    """Write assets at the paths the (renamed) upstream tree expects."""
    svg = (HERE / "logo.svg").read_text(encoding="utf-8")
    mark256 = draw_mark(256)
    save_png(mark256, root / "web/public/logo.png")
    save_png(mark256, root / "web/dist/logo.png")
    save_png(mark256, root / "docs/book/theme/favicon.png")
    (root / "docs/book/theme/favicon.svg").write_text(svg, encoding="utf-8")
    save_png(draw_mark(512), root / ".github/assets/caelza-logo.png")
    save_png(draw_banner(1672, 523), root / "docs/assets/caelza-banner.png")
    save_png(draw_banner(1672, 523, with_text=False), root / "docs/assets/caelza-banner-bg.png")

    icons = root / "apps/tauri/icons"
    if icons.is_dir():
        for f in icons.glob("*.png"):
            if f.name.startswith("tray-"):
                continue  # status glyphs, brand-neutral
            with Image.open(f) as old:
                w, _ = old.size
            save_png(draw_mark(w, background=C["void"], radius_frac=0.22), f)
        draw_mark(256, background=C["void"], radius_frac=0.22).save(
            icons / "icon.ico", format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        try:
            draw_mark(1024, background=C["void"], radius_frac=0.22).save(icons / "icon.icns", format="ICNS")
        except Exception as exc:  # pragma: no cover - platform dependent
            print(f"warning: icon.icns not regenerated ({exc}); upstream icns left in place")
        (icons / "icon.svg").write_text(svg, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runtime", type=Path, help="staged runtime tree to write assets into")
    ap.add_argument("--out", type=Path, default=HERE / "out", help="loose asset output dir (default brand/out)")
    args = ap.parse_args()
    if args.runtime:
        render_runtime(args.runtime.resolve())
        print(f"brand assets written into {args.runtime}")
    else:
        render_set(args.out)
        print(f"brand assets written to {args.out}")


if __name__ == "__main__":
    main()
