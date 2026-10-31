#!/usr/bin/env python3
"""Render Caelza brand assets with Pillow.

    python3 brand/make_assets.py                 # → brand/out/ (+ brand/hero.png for the README)
    python3 brand/make_assets.py --runtime DIR   # write into a staged runtime tree
    python3 brand/make_assets.py --android android/app           # the app's launcher icon (committed)
    python3 brand/make_assets.py --android android/app --check   # … is in step with this script (CI)
    python3 brand/make_assets.py --art-icons     # opt in to the illustration for app icons ≥ 128 px

The mark is the constellation Caelum drawn as a lightning bolt: its four main
stars at the bolt's turning points and the constellation line as the bolt's
spine, in the cyan→violet→purple gradient. A chamfered C in the waist is
opt-in (--with-c / mark.c.enabled). Everything is drawn from brand/tokens.json
so every build is reproducible without an SVG rasteriser; brand/logo.svg
(and logo-with-c.svg) carry the same geometry. The illustrations under
brand/art/ are reference material; the bolt hero is copied into the runtime
docs, the figure icon is used only with --art-icons.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageStat

HERE = Path(__file__).resolve().parent
TOKENS = json.loads((HERE / "tokens.json").read_text(encoding="utf-8"))
C = TOKENS["color"]
M = TOKENS["mark"]
PARENT = TOKENS["parent"]

SS = 4  # supersampling factor for antialiasing
RGBA = tuple[int, int, int, int]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _hex(h: str, a: int = 255) -> RGBA:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def _lerp(a: RGBA, b: RGBA, t: float) -> RGBA:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(4))  # type: ignore[return-value]


def _stops(t: float, stops: list[str]) -> RGBA:
    cols = [_hex(s) for s in stops]
    t = min(max(t, 0.0), 1.0)
    seg = t * (len(cols) - 1)
    i = min(int(seg), len(cols) - 2)
    return _lerp(cols[i], cols[i + 1], seg - i)


def _font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    rel = TOKENS["font"]["files"][kind]
    fallback = {
        "mono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "body": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    }.get(kind, "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    for p in (HERE / rel, Path(fallback)):
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()  # type: ignore[return-value]


def _gradient_image(w: int, h: int, stops: list[str], *, direction: str) -> Image.Image:
    """A gradient fill: "horizontal" (left→right), "vertical" (top→bottom) or
    "diagonal" (top-left→bottom-right)."""
    g = Image.new("RGBA", (w, h))
    px = g.load()
    for y in range(h):
        for x in range(w):
            fx, fy = x / max(w - 1, 1), y / max(h - 1, 1)
            t = fy if direction == "vertical" else (fx + fy) / 2 if direction == "diagonal" else fx
            px[x, y] = _stops(t, stops)
    return g


def _through_mask(mask: Image.Image, stops: list[str], *, direction: str, alpha: float = 1.0) -> Image.Image:
    """Colour a luminance mask with a gradient (cheap: gradient at 1/8 res, upscaled)."""
    w, h = mask.size
    g = _gradient_image(max(w // 8, 2), max(h // 8, 2), stops, direction=direction).resize((w, h), Image.BILINEAR)
    if alpha < 1.0:
        mask = mask.point(lambda v: int(v * alpha))
    g.putalpha(mask)
    return g


def _tracked_text(d: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.FreeTypeFont,
                  fill: RGBA, tracking_em: float) -> int:
    x, y = xy
    extra = int(font.size * tracking_em)
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += int(d.textlength(ch, font=font)) + extra
    return x


def _tracked_width(d: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, tracking_em: float) -> int:
    extra = int(font.size * tracking_em)
    return sum(int(d.textlength(ch, font=font)) + extra for ch in text) - extra


def _star(cx: float, cy: float, r: float, inner: float = 0.33) -> list[tuple[float, float]]:
    pts = []
    for k in range(8):
        ang = math.radians(-90 + 45 * k)
        rad = r if k % 2 == 0 else r * inner
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    return pts


# ---------------------------------------------------------------------------
# the mark
# ---------------------------------------------------------------------------

def _closed_stroke_mask(size_px: int, pts: list[tuple[float, float]], width: float) -> Image.Image:
    """Luminance mask of a closed polyline stroked at `width` with round joints."""
    m = Image.new("L", (size_px, size_px), 0)
    md = ImageDraw.Draw(m)
    md.line(pts + [pts[0]], fill=255, width=max(int(width), 1), joint="curve")
    for p in pts:
        md.ellipse([p[0] - width / 2, p[1] - width / 2, p[0] + width / 2, p[1] + width / 2], fill=255)
    return m


def c_points(scale: float = 1.0) -> list[tuple[float, float]]:
    """The C polygon with the bolt's lean applied (shear about y = 0.5)."""
    k = M["c"].get("shear", 0.0)
    return [((x + k * (0.5 - y)) * scale, y * scale) for x, y in M["c"]["polygon"]]


def draw_mark(size: int, *, glow: bool = True, with_c: bool | None = None) -> Image.Image:
    """Caelum as a bolt: neon gradient outline, the constellation as its spine,
    and (by default) an outlined C in the centre."""
    s = size * SS
    bolt = [(x * s, y * s) for x, y in M["bolt"]]
    cpoly = c_points(s)
    sw = M["stroke"] * s
    cw, cgap = M["c"]["outline"] * s, M["c"]["inner_gap"] * s
    stops = C["gradient_mark"]
    direction = M.get("gradient_direction", "vertical")
    big = glow and size >= 40
    stars = M["stars"]
    if with_c is None:
        with_c = bool(M["c"].get("enabled", True))

    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    # Translucent dark fill inside the bolt so the stars read on any surface.
    ImageDraw.Draw(im).polygon(bolt, fill=_hex(C["void"], 185))

    # Bolt outline with glow.
    if big:
        halo = _closed_stroke_mask(s, bolt, sw * 1.9).filter(ImageFilter.GaussianBlur(s * 0.028))
        im = Image.alpha_composite(im, _through_mask(halo, stops, direction=direction, alpha=0.6))
    im = Image.alpha_composite(im, _through_mask(_closed_stroke_mask(s, bolt, sw), stops, direction=direction))

    # Constellation spine: delta → alpha → beta → gamma, under the C.
    spine = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sd = ImageDraw.Draw(spine)
    for a, b in M["constellation"]:
        (x0, y0), (x1, y1) = stars[a]["pos"], stars[b]["pos"]
        sd.line([(x0 * s, y0 * s), (x1 * s, y1 * s)], fill=_hex(C["star"], 150), width=max(int(s * 0.007), 1))
    if big:
        spine = Image.alpha_composite(spine.filter(ImageFilter.GaussianBlur(s * 0.006)), spine)
    im = Image.alpha_composite(im, spine)

    # The C: dark fill, then a neon outline drawn as two parallel lines (a
    # gradient stroke with its centre line cut back out), with glow.
    if with_c:
        cfill = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        ImageDraw.Draw(cfill).polygon(cpoly, fill=_hex(C["void"], 215))
        im = Image.alpha_composite(im, cfill)
        outline = _closed_stroke_mask(s, cpoly, cw)
        if big:
            halo = _closed_stroke_mask(s, cpoly, cw * 2.2).filter(ImageFilter.GaussianBlur(s * 0.022))
            im = Image.alpha_composite(im, _through_mask(halo, stops, direction=direction, alpha=0.55))
            inner = _closed_stroke_mask(s, cpoly, cgap)
            outline = Image.composite(Image.new("L", (s, s), 0), outline, inner)
        im = Image.alpha_composite(im, _through_mask(outline, stops, direction=direction))

    # Stars: the four of Caelum (glyph size by brightness) plus faint minors.
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    if big:
        g = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        gd = ImageDraw.Draw(g)
        for st in stars.values():
            (x, y), r = st["pos"], st["r"]
            gd.polygon(_star(x * s, y * s, r * s * 1.5), fill=_hex(C["primary"], 170))
        layer = Image.alpha_composite(layer, g.filter(ImageFilter.GaussianBlur(s * 0.014)))
    ld = ImageDraw.Draw(layer)
    for st in stars.values():
        (x, y), r = st["pos"], st["r"]
        ld.polygon(_star(x * s, y * s, r * s), fill=_hex(C["star"]))
        ld.ellipse([x * s - r * s * 0.18, y * s - r * s * 0.18, x * s + r * s * 0.18, y * s + r * s * 0.18],
                   fill=_hex(C["primary_light"]))
    for x, y, r in M.get("minor_stars", []):
        ld.ellipse([x * s - r * s, y * s - r * s, x * s + r * s, y * s + r * s], fill=_hex(C["star"], 200))
    im = Image.alpha_composite(im, layer)
    return im.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------------------
# the cosmic backdrop
# ---------------------------------------------------------------------------

def backdrop(w: int, h: int, *, seed: int = 7, matrix_center: tuple[float, float] = (0.5, 0.5),
             detail: bool | None = None) -> Image.Image:
    """Space black, nebula glows, a starfield and the dot matrix. All at 2x.
    `detail` adds the dots and stars; by default they come at banner sizes and
    stay off at icon sizes, where they would be noise."""
    rnd = random.Random(seed)
    im = Image.new("RGBA", (w, h), _hex(C["space"]))

    neb = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    nd = ImageDraw.Draw(neb)
    for (fx, fy, fr, col, a) in (
        (0.18, 0.10, 0.55, C["purple"], 46),
        (0.85, 0.85, 0.50, C["purple"], 36),
        (0.80, 0.15, 0.35, C["pink"], 22),
        (0.30, 0.85, 0.35, C["primary"], 20),
    ):
        r = fr * h
        nd.ellipse([fx * w - r, fy * h - r, fx * w + r, fy * h + r], fill=_hex(col, a))
    im = Image.alpha_composite(im, neb.filter(ImageFilter.GaussianBlur(h * 0.22)))
    if detail is None:
        detail = min(w, h) >= 48 * SS
    if not detail:
        return im  # nebula only

    # Dot matrix with a radial falloff around matrix_center.
    dots = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dots)
    step = max(int(h * 0.028), 6)
    cxp, cyp = matrix_center[0] * w, matrix_center[1] * h
    rad = h * 0.75
    for y in range(step // 2, h, step):
        for x in range(step // 2, w, step):
            dist = math.hypot(x - cxp, y - cyp) / rad
            a = int(70 * max(0.0, 1 - dist) ** 1.6)
            if a > 2:
                r = max(step * 0.09, 1)
                dd.ellipse([x - r, y - r, x + r, y + r], fill=_hex(C["primary"], a))
    im = Image.alpha_composite(im, dots)

    # Starfield.
    stars = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stars)
    for _ in range(int(w * h / 9000)):
        x, y = rnd.uniform(0, w), rnd.uniform(0, h)
        r = rnd.choice([0.6, 0.8, 1.0, 1.4, 2.0]) * h / 500
        a = rnd.randint(70, 220)
        col = _hex(rnd.choice([C["star"], C["star"], C["primary"], C["purple_light"]]), a)
        sd.ellipse([x - r, y - r, x + r, y + r], fill=col)
    for _ in range(6):  # a few bright four-point stars
        x, y = rnd.uniform(0.05, 0.95) * w, rnd.uniform(0.08, 0.92) * h
        sd.polygon(_star(x, y, h * 0.012), fill=_hex(C["star"], 200))
    return Image.alpha_composite(im, stars)


def rounded_mask(w: int, h: int, radius: int) -> Image.Image:
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    return m


# ---------------------------------------------------------------------------
# wordmark + banner
# ---------------------------------------------------------------------------

def wordmark(height: int, *, tracking: float = 0.06, glow: bool = True) -> Image.Image:
    """CAELZA in Orbitron, filled with the cyan→purple gradient, on transparent."""
    font = _font("wordmark", height)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    w = _tracked_width(probe, "CAELZA", font, tracking) + height // 2
    h = int(height * 1.35)
    mask = Image.new("L", (w, h), 0)
    _tracked_text(ImageDraw.Draw(mask), (height // 8, int(height * 0.1)), "CAELZA", font, 255, tracking)  # type: ignore[arg-type]
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if glow:
        halo = mask.filter(ImageFilter.GaussianBlur(height * 0.08))
        im = Image.alpha_composite(im, _through_mask(halo, C["gradient_mark"], direction="horizontal", alpha=0.55))
    return Image.alpha_composite(im, _through_mask(mask, C["gradient_mark"], direction="horizontal"))


def draw_banner(w: int, h: int, *, with_text: bool = True) -> Image.Image:
    W, H = w * 2, h * 2
    im = backdrop(W, H, matrix_center=(0.22, 0.5))
    mark = draw_mark(int(H * 0.86))
    mx = int(W * 0.09)
    im.alpha_composite(mark, (mx, int((H - mark.height) / 2)))

    if with_text:
        d = ImageDraw.Draw(im)
        eyebrow = _font("mono", int(H * 0.052))
        sub = _font("body", int(H * 0.082))
        meta = _font("mono", int(H * 0.040))
        x = mx + mark.width + int(H * 0.08)
        y = int(H * 0.20)
        _tracked_text(d, (x, y), PARENT["presents"], eyebrow, _hex(C["text_dim"]), 0.16)
        wm = wordmark(int(H * 0.30))
        im.alpha_composite(wm, (x - int(H * 0.04), y + int(H * 0.07)))
        d = ImageDraw.Draw(im)
        ty = y + int(H * 0.07) + wm.height - int(H * 0.02)
        d.text((x, ty), TOKENS["tagline"], font=sub, fill=_hex(C["text_muted"]))
        # Gradient hairline + meta.
        gy = ty + int(H * 0.15)
        gw = int(W * 0.26)
        for i in range(gw):
            col = _stops(i / gw, C["gradient_mark"])
            d.line([(x + i, gy), (x + i, gy + 2)], fill=(col[0], col[1], col[2], 220))
        label = f"{PARENT['est']}   ·   {PARENT['site'].removeprefix('https://')}"
        _tracked_text(d, (x + gw + int(H * 0.05), gy - int(meta.size * 0.45)), label, meta, _hex(C["text_dim"]), 0.04)
    return im.resize((w, h), Image.LANCZOS).convert("RGB")


# ---------------------------------------------------------------------------
# app icons
# ---------------------------------------------------------------------------

def art_icon_square() -> Image.Image | None:
    """The source app-icon illustration cropped to its own bounds, squared."""
    p = HERE / TOKENS["art"]["app_icon"]
    if not p.exists():
        return None
    src = Image.open(p).convert("RGBA")
    bbox = src.getchannel("A").getbbox() or src.getbbox()
    crop = src.crop(bbox)
    side = max(crop.size)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.alpha_composite(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
    return sq


def icon(size: int, *, art: Image.Image | None = None) -> Image.Image:
    """App icon: backdrop + neon frame + the mark. With `art` (opt-in via
    --art-icons) the illustration is used instead at 128 px and above."""
    if art is not None and size >= 128:
        return art.resize((size, size), Image.LANCZOS)
    s = size * SS
    radius = int(s * 0.22)
    im = backdrop(s, s, seed=3)
    im.putalpha(rounded_mask(s, s, radius))
    # Neon gradient frame with glow.
    fm = Image.new("L", (s, s), 0)
    ImageDraw.Draw(fm).rounded_rectangle([int(s * 0.03)] * 2 + [s - int(s * 0.03)] * 2,
                                         radius=int(radius * 0.9), outline=255, width=max(int(s * 0.022), 1))
    if size >= 40:
        im = Image.alpha_composite(im, _through_mask(fm.filter(ImageFilter.GaussianBlur(s * 0.02)),
                                                     C["gradient_mark"], direction="diagonal", alpha=0.7))
    im = Image.alpha_composite(im, _through_mask(fm, C["gradient_mark"], direction="diagonal"))
    mark = draw_mark(int(size * 0.74), glow=size >= 40).resize((int(s * 0.74), int(s * 0.74)), Image.LANCZOS)
    im.alpha_composite(mark, ((s - mark.width) // 2, (s - mark.height) // 2))
    return im.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------------------
# output sets
# ---------------------------------------------------------------------------

def maskable_icon(size: int) -> Image.Image:
    """Maskable PWA icon: the mark inside the 80 % safe zone on the void, no
    frame, so every launcher shape (circle, squircle, teardrop) keeps the bolt."""
    im = Image.new("RGBA", (size, size), TOKENS["color"]["void"])
    mark = draw_mark(int(size * 0.62))
    im.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
    return im


def save_png(im: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "PNG", optimize=True)


def render_set(out: Path, *, use_art: bool = False) -> None:
    art = art_icon_square() if use_art else None
    save_png(draw_mark(1024), out / "caelza-mark-1024.png")
    save_png(draw_mark(512), out / "caelza-mark-512.png")
    save_png(icon(512), out / "caelza-icon-512.png")
    if art is not None:
        save_png(icon(1024, art=art), out / "caelza-icon-art-1024.png")
    save_png(wordmark(160), out / "caelza-wordmark.png")
    banner = draw_banner(1600, 500)
    save_png(banner, out / "caelza-banner.png")
    save_png(draw_banner(1600, 500, with_text=False), out / "caelza-banner-bg.png")
    save_png(banner, HERE / "hero.png")  # committed: the README hero
    draw_mark(256).save(out / "favicon.ico", format="ICO",
                        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def render_runtime(root: Path, *, use_art: bool = False) -> None:
    """Write assets at the paths the (renamed) upstream tree expects."""
    svg = (HERE / "logo.svg").read_text(encoding="utf-8")
    art = art_icon_square() if use_art else None
    mark256 = draw_mark(256)
    save_png(mark256, root / "web/public/logo.png")
    save_png(mark256, root / "web/dist/logo.png")
    # The dashboard's own faces (brand/fonts, SIL OFL, licences alongside) and
    # the installable app's icons. web/src/caelza-brand.css and
    # web/public/manifest.webmanifest (runtime/overlay) reference them.
    fonts_dir = root / "web/public/fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    for f in sorted((HERE / "fonts").iterdir()):
        if f.suffix == ".ttf" or f.name.startswith("OFL-"):
            (fonts_dir / f.name).write_bytes(f.read_bytes())
    save_png(icon(192, art=art), root / "web/public/icon-192.png")
    save_png(icon(512, art=art), root / "web/public/icon-512.png")
    save_png(icon(180, art=art), root / "web/public/apple-touch-icon.png")
    save_png(maskable_icon(512), root / "web/public/icon-maskable-512.png")
    save_png(mark256, root / "docs/book/theme/favicon.png")
    (root / "docs/book/theme/favicon.svg").write_text(svg, encoding="utf-8")
    save_png(draw_mark(512), root / ".github/assets/caelza-logo.png")
    save_png(draw_banner(1672, 523), root / "docs/assets/caelza-banner.png")
    save_png(draw_banner(1672, 523, with_text=False), root / "docs/assets/caelza-banner-bg.png")
    hero = HERE / TOKENS["art"]["hero"]
    if hero.exists():
        (root / "docs/assets").mkdir(parents=True, exist_ok=True)
        (root / "docs/assets/caelza-hero-art.jpg").write_bytes(hero.read_bytes())

    icons = root / "apps/tauri/icons"
    if icons.is_dir():
        for f in icons.glob("*.png"):
            if f.name.startswith("tray-"):
                continue  # status glyphs, brand-neutral
            with Image.open(f) as old:
                w, _ = old.size
            save_png(icon(w, art=art), f)
        icon(256, art=art).save(icons / "icon.ico", format="ICO",
                                sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        try:
            icon(1024, art=art).save(icons / "icon.icns", format="ICNS")
        except Exception as exc:  # pragma: no cover - platform dependent
            print(f"warning: icon.icns not regenerated ({exc}); upstream icns left in place")
        (icons / "icon.svg").write_text(svg, encoding="utf-8")


# ---------------------------------------------------------------------------
# the Android launcher icon
# ---------------------------------------------------------------------------
#
# An adaptive icon: two 108 dp layers the launcher masks to its own shape
# (circle, squircle, teardrop…), showing the centre 72 dp and, for most shapes,
# about 66 dp of it. The mark stays inside that circle so no shape clips the
# bolt; the nebula backdrop fills the rest and moves with the parallax. The
# third layer is the mark's silhouette, which Android 13 tints for themed
# icons and the Runtime notification uses as its status-bar icon. The files
# are committed under android/app/src/main/res; `--check` keeps them in step.

ADAPTIVE_DP = 108
ANDROID_DENSITIES = {"mdpi": 1.0, "hdpi": 1.5, "xhdpi": 2.0, "xxhdpi": 3.0, "xxxhdpi": 4.0}
LAUNCHER_MARK = 0.56   # the mark's canvas as a fraction of the layer: its bolt then spans ~57 dp of the 66 dp safe circle
MONO_STROKE = 2.2      # the silhouette's stroke relative to the mark's: it has to read at 24 dp in the status bar
MONO_STAR = 1.7        # and its stars likewise


def launcher_foreground(size: int) -> Image.Image:
    """Foreground layer: the mark alone, centred in the safe zone, transparent elsewhere."""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mark = draw_mark(int(size * LAUNCHER_MARK))
    im.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
    return im


def launcher_background(size: int) -> Image.Image:
    """Background layer: the cosmic backdrop's nebula on space black, opaque; no
    stars or dots, which would be noise under a mask and swim with the parallax."""
    return backdrop(size, size, seed=3, detail=False).convert("RGB")


def launcher_monochrome_vector() -> str:
    """A VectorDrawable of the mark's silhouette in the adaptive icon's 108 dp
    viewport, white on transparent: the bolt as a stroked outline (never filled,
    BRAND.md) and the four stars of Caelum as discs. The system tints it, so it
    carries no colour and no gradient."""
    v = ADAPTIVE_DP
    side = v * LAUNCHER_MARK
    off = (v - side) / 2

    def pt(x: float, y: float) -> str:
        return f"{off + x * side:.2f},{off + y * side:.2f}"

    bolt = "M" + " L".join(pt(x, y) for x, y in M["bolt"]) + " Z"
    stars = []
    for st in M["stars"].values():
        (x, y), r = st["pos"], st["r"] * side * MONO_STAR
        cx, cy = off + x * side, off + y * side
        stars.append(f"M{cx - r:.2f},{cy:.2f} a{r:.2f},{r:.2f} 0 1 0 {2 * r:.2f},0 a{r:.2f},{r:.2f} 0 1 0 {-2 * r:.2f},0 Z")
    stroke = M["stroke"] * side * MONO_STROKE
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!-- Generated by brand/make_assets.py (its android target) from brand/tokens.json; do not edit by hand.
     The mark's silhouette (the bolt's outline and the four stars of Caelum), white on transparent,
     in the adaptive icon's 108 dp viewport: the monochrome layer Android 13 tints for themed icons,
     and the Runtime notification's status-bar icon. -->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="{v}dp"
    android:height="{v}dp"
    android:viewportWidth="{v}"
    android:viewportHeight="{v}">
    <path
        android:pathData="{bolt}"
        android:strokeColor="#FFFFFFFF"
        android:strokeWidth="{stroke:.2f}"
        android:strokeLineJoin="round"
        android:strokeLineCap="round"
        android:fillColor="#00000000" />
    <path
        android:pathData="{' '.join(stars)}"
        android:fillColor="#FFFFFFFF" />
</vector>
'''


def android_targets(app: Path) -> dict[Path, tuple]:
    """Every file the launcher icon is made of → (renderer, size | None)."""
    res = app / "src" / "main" / "res"
    targets: dict[Path, tuple] = {}
    for dpi, scale in ANDROID_DENSITIES.items():
        px = int(ADAPTIVE_DP * scale)
        targets[res / f"mipmap-{dpi}" / "ic_launcher_foreground.png"] = (launcher_foreground, px)
        targets[res / f"mipmap-{dpi}" / "ic_launcher_background.png"] = (launcher_background, px)
    targets[res / "drawable" / "ic_launcher_monochrome.xml"] = (launcher_monochrome_vector, None)
    return targets


def render_android(app: Path) -> list[Path]:
    """Write the launcher icon into the app module (android/app)."""
    written = []
    for path, (render, size) in android_targets(app).items():
        if size is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render(), encoding="utf-8")
        else:
            save_png(render(size), path)
        written.append(path)
    return written


def check_android(app: Path, *, max_diff: int = 16, mean_diff: float = 0.75) -> list[str]:
    """What differs between the committed launcher icon and a fresh render: a
    missing file, a changed vector, a layer whose pixels drift past the tolerance
    (another Pillow's resampling moves a pixel by a few levels; a changed mark or
    palette moves them by far more). Empty when everything is in step."""
    drift = []
    for path, (render, size) in android_targets(app).items():
        if not path.is_file():
            drift.append(f"{path}: missing (run make_assets.py --android)")
            continue
        if size is None:
            if path.read_text(encoding="utf-8") != render():
                drift.append(f"{path}: the vector differs from the generator's")
            continue
        fresh = render(size).convert("RGBA")
        with Image.open(path) as f:
            have = f.convert("RGBA")
        if have.size != fresh.size:
            drift.append(f"{path}: {have.size[0]}x{have.size[1]} px, expected {size}x{size}")
            continue
        diff = ImageChops.difference(have, fresh)
        worst = max(hi for _, hi in diff.getextrema())
        mean = sum(ImageStat.Stat(diff).mean) / 4
        if worst > max_diff or mean > mean_diff:
            drift.append(f"{path}: pixels differ (max {worst}, mean {mean:.2f}; tolerance {max_diff} / {mean_diff})")
    return drift


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runtime", type=Path, help="staged runtime tree to write assets into")
    ap.add_argument("--android", type=Path, metavar="APP",
                    help="Android app module (android/app) to write the launcher icon into: the adaptive icon's "
                         "layers at every density and the monochrome vector")
    ap.add_argument("--check", action="store_true",
                    help="with --android: compare the committed files with a fresh render instead of writing; exit 1 on drift")
    ap.add_argument("--out", type=Path, default=HERE / "out", help="loose asset output dir (default brand/out)")
    ap.add_argument("--art-icons", action="store_true",
                    help="use the illustration in brand/art for app icons >= 128 px instead of the geometric mark")
    cgrp = ap.add_mutually_exclusive_group()
    cgrp.add_argument("--with-c", dest="with_c", action="store_true", default=None,
                      help="draw the C inside the bolt (overrides tokens.json mark.c.enabled)")
    cgrp.add_argument("--no-c", dest="with_c", action="store_false",
                      help="bolt, spine and stars only")
    args = ap.parse_args()
    if args.with_c is not None:
        M["c"]["enabled"] = args.with_c
    if args.android:
        app = args.android.resolve()
        if args.check:
            drift = check_android(app)
            for line in drift:
                print(f"drift: {line}")
            print(f"launcher icon {'differs from' if drift else 'in step with'} the generator ({app})")
            sys.exit(1 if drift else 0)
        render_android(app)
        print(f"launcher icon written into {app}")
    elif args.runtime:
        render_runtime(args.runtime.resolve(), use_art=args.art_icons)
        print(f"brand assets written into {args.runtime}")
    else:
        render_set(args.out, use_art=args.art_icons)
        print(f"brand assets written to {args.out} (and brand/hero.png)")


if __name__ == "__main__":
    main()
