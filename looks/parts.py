"""The pixel part library behind every agent's look (vision M8).

A look is a 40 x 44 pixel character built from one part per layer:
backdrop, body, outfit, hair, hat, face, accessory. Every part is drawn as
code here (rectangles on the grid), in a *key palette*: the skin, hair,
outfit, accent and eye pixels are written in improbable key colours, and the
renderer (this module for previews and checks, `Look.tsx` on the dashboard)
swaps each key for the owner's chosen colour and its light and dark tones.
So one part drawn once comes in every colour, and a pack is a handful of
functions.

`scripts/looks.py export` writes each part as a PNG under the dashboard's
public files (the browser composes them), draws the shop's preview sheets,
and `check` keeps those in step with this file and the catalog.

Grid conventions (shared with the dashboard's renderer): head box x 11..28,
y 10..27; eyes start at x = 14 and x = 22, y 17..20; mouth y 24..27; body
from y 29. Draw order: backdrop, then the silhouette layers (body, outfit,
hair, hat) which get one outline around their union, then the detail layers
(face, accessory) on top, unoutlined.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image

W, H = 40, 44
FRAMES = ("closed", "open", "blink")

#: The key colours (what the exported PNGs hold) per recolourable slot and tone.
KEYS: dict[str, dict[str, tuple[int, int, int]]] = {
    "skin": {"d": (200, 1, 1), "m": (250, 1, 1), "l": (255, 120, 120)},
    "hair": {"d": (1, 200, 1), "m": (1, 250, 1), "l": (120, 255, 120)},
    "outfit": {"d": (1, 1, 200), "m": (1, 1, 250), "l": (120, 120, 255)},
    "accent": {"d": (200, 1, 200), "m": (250, 1, 250), "l": (255, 120, 255)},
    "eyes": {"m": (1, 250, 250)},
}

#: Colours that never change: the outline, whites, the mouth, the stars.
FIXED: dict[str, tuple[int, int, int]] = {
    "o": (13, 8, 32),       # outline, near-black tinted to the palette
    "wh": (255, 255, 255),
    "dk": (19, 12, 46),     # pupils, deep shadow
    "mc": (74, 24, 48),     # mouth
    "mg": (255, 61, 242),   # tongue, gems
    "bl": (245, 138, 168),  # blush
    "st": (234, 252, 255),  # star
    "yl": (255, 230, 77),   # sun
    "space": (5, 3, 16),
    "bg2": (12, 9, 24),
    "bg4": (26, 21, 48),
    "navy": (26, 18, 80),
    "nebula": (58, 29, 110),
    "pink": (255, 79, 184),
    "purple": (180, 79, 255),
    "cyan": (34, 230, 255),
}

#: Name -> RGB for the drawing functions: key tones as `skin`, `skin_d`, `skin_l` …
NAMES: dict[str, tuple[int, int, int]] = dict(FIXED)
for _slot, _tones in KEYS.items():
    for _tone, _rgb in _tones.items():
        NAMES[_slot if _tone == "m" else f"{_slot}_{_tone}"] = _rgb

#: Layer order: (layer, stage). The silhouette layers get the outline.
LAYERS: tuple[tuple[str, str], ...] = (
    ("backdrop", "backdrop"),
    ("body", "silhouette"),
    ("outfit", "silhouette"),
    ("hair", "silhouette"),
    ("hat", "silhouette"),
    ("face", "detail"),
    ("accessory", "detail"),
)
LAYER_ORDER = [layer for layer, _ in LAYERS]
SLOTS = ("skin", "hair", "outfit", "accent", "eyes")


class Canvas:
    def __init__(self) -> None:
        self.im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        self.px = self.im.load()

    def p(self, x: int, y: int, c: str | tuple[int, int, int]) -> None:
        if 0 <= x < W and 0 <= y < H:
            rgb = NAMES[c] if isinstance(c, str) else c
            self.px[x, y] = (*rgb, 255)

    def r(self, x: int, y: int, w: int, h: int, c: str | tuple[int, int, int]) -> None:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.p(xx, yy, c)

    def clear(self, x: int, y: int, w: int = 1, h: int = 1) -> None:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                if 0 <= xx < W and 0 <= yy < H:
                    self.px[xx, yy] = (0, 0, 0, 0)

    def fill(self, c: str) -> None:
        self.r(0, 0, W, H, c)

    def paste(self, other: "Canvas") -> None:
        self.im.alpha_composite(other.im)
        self.px = self.im.load()


# ---------------------------------------------------------------------------
# The part registry

Draw = Callable[[Canvas, str], None]


@dataclass
class Part:
    id: str
    layer: str
    name: str
    pack: str
    draw: Draw
    #: Which slots the part recolours (for the customizer's colour rows).
    slots: tuple[str, ...] = field(default_factory=tuple)


PARTS: dict[str, Part] = {}


def part(pid: str, name: str, pack: str, slots: tuple[str, ...] = ()) -> Callable[[Draw], Draw]:
    layer = pid.split(".", 1)[0]
    if layer not in LAYER_ORDER:
        raise ValueError(f"{pid}: unknown layer {layer!r}")

    def register(fn: Draw) -> Draw:
        if pid in PARTS:
            raise ValueError(f"{pid} registered twice")
        PARTS[pid] = Part(pid, layer, name, pack, fn, slots)
        return fn

    return register


def nothing(_c: Canvas, _frame: str) -> None:
    return None


# ---- backdrops ---------------------------------------------------------------

part("backdrop.none", "Plain", "starter")(nothing)


@part("backdrop.space", "Space", "starter")
def _backdrop_space(c: Canvas, _f: str) -> None:
    c.fill("space")
    for x, y in ((3, 4), (9, 12), (34, 3), (37, 15), (2, 30), (36, 36), (30, 24), (6, 40), (20, 2), (26, 9)):
        c.p(x, y, "st")
    for x, y in ((14, 6), (33, 30), (5, 20)):
        c.p(x, y, "cyan")
    c.p(31, 8, "purple")
    c.p(8, 34, "pink")


@part("backdrop.grid", "Grid", "starter")
def _backdrop_grid(c: Canvas, _f: str) -> None:
    c.fill("bg2")
    for x in range(3, W, 8):
        c.r(x, 0, 1, H, "bg4")
    for y in range(3, H, 8):
        c.r(0, y, W, 1, "bg4")


@part("backdrop.sunset", "Sunset", "starter")
def _backdrop_sunset(c: Canvas, _f: str) -> None:
    c.r(0, 0, W, 16, "navy")
    c.r(0, 16, W, 14, "purple")
    c.r(0, 30, W, 14, "pink")
    # The sun, low on the right.
    c.r(24, 10, 8, 2, "yl")
    c.r(23, 12, 10, 6, "yl")
    c.r(24, 18, 8, 2, "yl")
    c.r(22, 14, 12, 2, "yl")


@part("backdrop.nebula", "Nebula", "cosmic")
def _backdrop_nebula(c: Canvas, _f: str) -> None:
    c.fill("space")
    for x, y, w, h in ((0, 0, 14, 9), (3, 9, 6, 5), (28, 32, 12, 12), (24, 38, 5, 6), (31, 27, 6, 5)):
        c.r(x, y, w, h, "nebula")
    for x, y in ((2, 3), (8, 6), (11, 11), (33, 35), (37, 40), (29, 30)):
        c.p(x, y, "purple")
    for x, y in ((5, 14), (34, 5), (37, 18), (2, 36), (20, 1), (38, 26), (7, 42)):
        c.p(x, y, "st")
    for x, y in ((9, 2), (31, 12), (36, 31)):
        c.p(x, y, "cyan")


# ---- bodies -----------------------------------------------------------------

def _torso(c: Canvas) -> None:
    c.r(8, 32, 24, 12, "skin_d")


@part("body.sprout", "Sprout", "starter", ("skin",))
def _body_sprout(c: Canvas, _f: str) -> None:
    c.r(11, 10, 18, 18, "skin")
    c.r(13, 28, 14, 1, "skin")
    c.r(10, 18, 1, 4, "skin")
    c.r(29, 18, 1, 4, "skin")
    c.r(11, 26, 18, 2, "skin_d")
    c.r(13, 28, 14, 1, "skin_d")
    c.r(16, 29, 8, 3, "skin_d")
    _torso(c)


@part("body.bot", "Bot", "starter", ("skin",))
def _body_bot(c: Canvas, _f: str) -> None:
    c.r(11, 10, 18, 18, "skin")
    for x, y in ((11, 10), (28, 10), (11, 27), (28, 27)):
        c.clear(x, y)
    c.r(15, 8, 10, 2, "skin_d")
    c.r(9, 16, 2, 4, "skin_d")
    c.r(29, 16, 2, 4, "skin_d")
    c.r(12, 25, 16, 2, "skin_d")
    c.r(16, 28, 8, 4, "skin_d")
    c.r(18, 31, 4, 1, "skin_l")
    _torso(c)


@part("body.orb", "Orb", "cosmic", ("skin",))
def _body_orb(c: Canvas, _f: str) -> None:
    # A rounder head: the corners chamfered two deep.
    c.r(11, 10, 18, 18, "skin")
    for x, y in ((11, 10), (12, 10), (11, 11), (27, 10), (28, 10), (28, 11), (11, 27), (11, 26), (12, 27), (28, 27), (28, 26), (27, 27)):
        c.clear(x, y)
    c.r(13, 12, 3, 1, "skin_l")
    c.r(12, 13, 1, 2, "skin_l")
    c.r(13, 26, 14, 1, "skin_d")
    c.r(16, 28, 8, 4, "skin_d")
    _torso(c)


# ---- outfits ----------------------------------------------------------------

@part("outfit.hoodie", "Hoodie", "starter", ("outfit", "accent"))
def _outfit_hoodie(c: Canvas, _f: str) -> None:
    c.r(5, 35, 30, 9, "outfit")
    c.r(7, 32, 26, 3, "outfit")
    c.r(12, 31, 16, 3, "outfit_d")
    c.r(16, 34, 1, 6, "accent")
    c.r(23, 34, 1, 6, "accent")
    c.r(6, 35, 1, 9, "outfit_l")


@part("outfit.tee", "Tee", "starter", ("outfit", "accent", "skin"))
def _outfit_tee(c: Canvas, _f: str) -> None:
    c.r(6, 33, 28, 11, "outfit")
    c.r(5, 38, 2, 6, "skin")
    c.r(33, 38, 2, 6, "skin")
    c.r(15, 32, 10, 2, "outfit_d")
    c.r(12, 38, 16, 1, "accent")
    c.r(7, 33, 1, 5, "outfit_l")


@part("outfit.jacket", "Jacket", "starter", ("outfit", "accent"))
def _outfit_jacket(c: Canvas, _f: str) -> None:
    c.r(5, 33, 30, 11, "outfit")
    c.r(17, 33, 6, 11, "dk")
    c.r(19, 34, 2, 10, "accent")
    c.r(14, 32, 3, 6, "outfit_l")
    c.r(23, 32, 3, 6, "outfit_l")
    c.r(8, 39, 4, 3, "outfit_d")
    c.r(28, 39, 4, 3, "outfit_d")


@part("outfit.cloak", "Cloak", "starter", ("outfit", "accent"))
def _outfit_cloak(c: Canvas, _f: str) -> None:
    c.r(4, 33, 32, 11, "outfit")
    c.r(13, 34, 14, 10, "outfit_d")
    c.r(18, 32, 4, 2, "accent")
    c.r(10, 36, 1, 8, "outfit_d")
    c.r(29, 36, 1, 8, "outfit_d")
    c.r(5, 33, 1, 11, "outfit_l")


@part("outfit.constellation", "Constellation hoodie", "cosmic", ("outfit", "accent"))
def _outfit_constellation(c: Canvas, _f: str) -> None:
    _outfit_hoodie(c, _f)
    # Caelum as a bolt on the chest pocket side, the brand's own figure.
    for x, y in ((27, 36), (26, 37), (26, 38), (28, 38), (27, 39), (27, 40)):
        c.p(x, y, "accent_l")
    for x, y in ((27, 36), (26, 38), (27, 40)):
        c.p(x, y, "st")
    c.p(10, 37, "st")
    c.p(12, 40, "st")


# ---- hair --------------------------------------------------------------------

part("hair.none", "None", "starter")(nothing)


@part("hair.swoop", "Swoop", "starter", ("hair",))
def _hair_swoop(c: Canvas, _f: str) -> None:
    c.r(10, 7, 20, 6, "hair")
    c.r(12, 4, 4, 3, "hair")
    c.r(18, 2, 5, 5, "hair")
    c.r(25, 4, 4, 3, "hair")
    c.r(10, 13, 2, 7, "hair")
    c.r(28, 13, 2, 7, "hair")
    c.r(12, 13, 5, 1, "hair")
    c.r(23, 13, 5, 1, "hair")
    c.r(20, 6, 2, 7, "hair_l")
    c.r(10, 12, 20, 1, "hair_d")


@part("hair.bob", "Bob", "starter", ("hair",))
def _hair_bob(c: Canvas, _f: str) -> None:
    c.r(10, 6, 20, 7, "hair")
    c.r(9, 12, 3, 12, "hair")
    c.r(28, 12, 3, 12, "hair")
    c.r(11, 13, 8, 2, "hair")
    c.r(21, 13, 7, 1, "hair")
    c.r(13, 8, 4, 1, "hair_l")
    c.r(9, 22, 3, 2, "hair_d")
    c.r(28, 22, 3, 2, "hair_d")


@part("hair.buns", "Buns", "starter", ("hair", "accent"))
def _hair_buns(c: Canvas, _f: str) -> None:
    c.r(11, 7, 18, 6, "hair")
    c.r(5, 5, 6, 6, "hair")
    c.r(29, 5, 6, 6, "hair")
    c.r(7, 7, 2, 2, "hair_d")
    c.r(31, 7, 2, 2, "hair_d")
    c.r(6, 10, 4, 1, "accent")
    c.r(30, 10, 4, 1, "accent")
    c.r(12, 13, 6, 1, "hair")
    c.r(22, 13, 6, 1, "hair")
    c.r(10, 12, 2, 5, "hair")
    c.r(28, 12, 2, 5, "hair")
    c.r(14, 8, 3, 1, "hair_l")


@part("hair.spikes", "Spikes", "starter", ("hair",))
def _hair_spikes(c: Canvas, _f: str) -> None:
    c.r(10, 8, 20, 5, "hair")
    for x, y, h in ((9, 4, 5), (14, 2, 7), (19, 1, 8), (24, 2, 7), (29, 4, 5)):
        c.r(x, y, 3, h, "hair")
        c.p(x + 1, y, "hair_l")
    c.r(10, 13, 2, 5, "hair")
    c.r(28, 13, 2, 5, "hair")
    c.r(10, 12, 20, 1, "hair_d")


@part("hair.long", "Long", "starter", ("hair",))
def _hair_long(c: Canvas, _f: str) -> None:
    c.r(10, 6, 20, 7, "hair")
    c.r(8, 12, 3, 20, "hair")
    c.r(29, 12, 3, 20, "hair")
    c.r(10, 22, 1, 10, "hair_d")
    c.r(29, 22, 1, 10, "hair_d")
    c.r(12, 13, 7, 1, "hair")
    c.r(21, 13, 7, 1, "hair")
    c.r(14, 8, 2, 2, "hair_l")
    c.r(8, 30, 3, 2, "hair_d")
    c.r(29, 30, 3, 2, "hair_d")


@part("hair.nebula", "Nebula", "cosmic", ("hair",))
def _hair_nebula(c: Canvas, _f: str) -> None:
    c.r(10, 6, 20, 7, "hair")
    c.r(8, 4, 6, 5, "hair")
    c.r(26, 4, 6, 5, "hair")
    c.r(16, 2, 8, 5, "hair")
    c.r(10, 13, 2, 8, "hair")
    c.r(28, 13, 2, 8, "hair")
    c.r(12, 13, 5, 1, "hair")
    c.r(23, 13, 5, 1, "hair")
    c.r(18, 4, 1, 7, "hair_l")
    c.r(24, 8, 1, 3, "hair_l")
    for x, y in ((13, 6), (22, 4), (27, 8), (11, 10), (29, 15)):
        c.p(x, y, "st")
    c.r(10, 12, 20, 1, "hair_d")


# ---- hats -------------------------------------------------------------------

part("hat.none", "None", "starter")(nothing)


@part("hat.beanie", "Beanie", "starter", ("accent",))
def _hat_beanie(c: Canvas, _f: str) -> None:
    c.r(9, 5, 22, 9, "accent")
    c.r(9, 12, 22, 2, "accent_d")
    c.r(18, 2, 4, 3, "accent_l")
    c.r(12, 7, 2, 4, "accent_l")


@part("hat.cap", "Cap", "starter", ("accent",))
def _hat_cap(c: Canvas, _f: str) -> None:
    c.r(10, 6, 20, 7, "accent")
    c.r(4, 12, 18, 2, "accent_d")
    c.r(19, 5, 2, 1, "accent_l")
    c.r(12, 8, 3, 1, "accent_l")
    c.r(10, 12, 20, 1, "accent_d")


@part("hat.halo", "Halo", "starter", ("accent",))
def _hat_halo(c: Canvas, _f: str) -> None:
    c.r(14, 2, 12, 1, "accent_l")
    c.r(12, 3, 2, 2, "accent_l")
    c.r(26, 3, 2, 2, "accent_l")
    c.r(14, 5, 12, 1, "accent_l")
    c.p(17, 2, "st")
    c.p(23, 5, "st")


@part("hat.crown", "Crown", "cosmic", ("accent",))
def _hat_crown(c: Canvas, _f: str) -> None:
    c.r(12, 5, 16, 4, "accent")
    c.r(12, 2, 2, 3, "accent")
    c.r(18, 1, 4, 4, "accent")
    c.r(26, 2, 2, 3, "accent")
    c.p(13, 6, "mg")
    c.r(19, 6, 2, 1, "mg")
    c.p(26, 6, "mg")
    c.r(12, 8, 16, 1, "accent_d")


# ---- faces (frame-aware) ------------------------------------------------------

def _brows(c: Canvas, style: str) -> None:
    if style == "up":
        c.r(14, 14, 4, 1, "o")
        c.r(22, 14, 4, 1, "o")
    else:
        c.r(14, 15, 4, 1, "o")
        c.r(22, 15, 4, 1, "o")


def _nose(c: Canvas) -> None:
    c.r(19, 21, 2, 1, "skin_d")


def _mouth(c: Canvas, kind: str) -> None:
    if kind == "closed":
        c.r(18, 24, 4, 1, "mc")
    elif kind == "open":
        c.r(18, 24, 4, 3, "mc")
        c.r(19, 26, 2, 1, "mg")
    elif kind == "smile":
        for x, y in ((17, 23), (18, 24), (22, 23), (21, 24)):
            c.p(x, y, "mc")
        c.r(19, 25, 2, 1, "mc")
    elif kind == "big":
        c.r(17, 24, 6, 1, "mc")
        c.r(18, 25, 4, 2, "mc")
        c.r(19, 26, 2, 1, "mg")
    elif kind == "smirk":
        c.r(18, 25, 3, 1, "mc")
        c.p(21, 24, "mc")
        c.p(22, 23, "mc")


def _blink(c: Canvas, x: int) -> None:
    c.r(x, 19, 4, 1, "o")


def _face(eyes: Callable[[Canvas, int], None], brows: str = "n", closed: str = "closed", opened: str = "open",
          blink_eyes: Callable[[Canvas, int], None] = _blink) -> Draw:
    def draw(c: Canvas, frame: str) -> None:
        _nose(c)
        _brows(c, brows)
        for x in (14, 22):
            (blink_eyes if frame == "blink" else eyes)(c, x)
        _mouth(c, opened if frame == "open" else closed)

    return draw


def _eye_round(c: Canvas, x: int) -> None:
    c.r(x, 17, 4, 4, "wh")
    c.r(x + 1, 17, 2, 4, "eyes")
    c.r(x + 1, 18, 2, 2, "dk")
    c.p(x + 1, 18, "wh")


def _eye_half(c: Canvas, x: int) -> None:
    c.r(x, 19, 4, 2, "wh")
    c.r(x + 1, 19, 2, 2, "eyes")
    c.r(x + 1, 20, 2, 1, "dk")
    c.r(x, 18, 4, 1, "o")


def _eye_star(c: Canvas, x: int) -> None:
    c.r(x + 1, 16, 2, 5, "eyes")
    c.r(x, 17, 4, 3, "eyes")
    c.r(x + 1, 18, 2, 1, "wh")


def _eye_galaxy(c: Canvas, x: int) -> None:
    c.r(x, 16, 4, 5, "dk")
    c.p(x + 1, 17, "wh")
    c.p(x + 2, 19, "eyes")
    c.p(x + 3, 17, "mg")
    c.p(x, 19, "mg")
    c.p(x + 2, 20, "wh")


def _eye_happy(c: Canvas, x: int) -> None:
    for x2, y in ((x, 19), (x + 1, 18), (x + 2, 18), (x + 3, 19)):
        c.p(x2, y, "o")


def _eye_swirl(c: Canvas, x: int) -> None:
    c.r(x, 17, 4, 4, "eyes")
    c.r(x + 1, 18, 2, 2, "dk")
    c.p(x + 1, 18, "eyes")
    c.p(x + 2, 19, "eyes")


def _eye_dot(c: Canvas, x: int) -> None:
    c.r(x + 1, 17, 2, 4, "dk")
    c.p(x + 1, 17, "eyes")


part("face.round", "Round", "starter", ("eyes",))(_face(_eye_round))
part("face.half", "Half-lidded", "starter", ("eyes",))(_face(_eye_half, closed="smirk"))
part("face.star", "Starry", "starter", ("eyes",))(_face(_eye_star, brows="up"))
part("face.happy", "Happy", "starter", ())(_face(_eye_happy, closed="smile", opened="big", blink_eyes=_eye_happy))
part("face.dot", "Dot", "starter", ("eyes",))(_face(_eye_dot))
part("face.galaxy", "Galaxy", "cosmic", ("eyes",))(_face(_eye_galaxy, brows="up"))
part("face.swirl", "Swirl", "cosmic", ("eyes",))(_face(_eye_swirl, closed="smile", opened="big"))


# ---- accessories ---------------------------------------------------------------

part("accessory.none", "None", "starter")(nothing)


@part("accessory.glasses", "Glasses", "starter", ("accent",))
def _accessory_glasses(c: Canvas, _f: str) -> None:
    for x in (13, 21):
        c.r(x, 16, 6, 1, "accent_d")
        c.r(x, 21, 6, 1, "accent_d")
        c.r(x, 16, 1, 6, "accent_d")
        c.r(x + 5, 16, 1, 6, "accent_d")
    c.r(19, 18, 2, 1, "accent_d")
    c.r(10, 17, 3, 1, "accent_d")
    c.r(27, 17, 3, 1, "accent_d")


@part("accessory.visor", "Visor", "starter", ("accent",))
def _accessory_visor(c: Canvas, _f: str) -> None:
    c.r(12, 16, 16, 5, "accent")
    c.r(13, 17, 6, 1, "accent_l")
    c.r(10, 17, 2, 3, "accent_d")
    c.r(28, 17, 2, 3, "accent_d")


@part("accessory.headphones", "Headphones", "starter", ("accent",))
def _accessory_headphones(c: Canvas, _f: str) -> None:
    c.r(10, 6, 20, 1, "accent_d")
    c.r(9, 7, 1, 8, "accent_d")
    c.r(30, 7, 1, 8, "accent_d")
    c.r(8, 15, 3, 6, "accent")
    c.r(29, 15, 3, 6, "accent")
    c.r(9, 17, 1, 2, "accent_l")
    c.r(30, 17, 1, 2, "accent_l")


@part("accessory.blush", "Blush", "starter", ())
def _accessory_blush(c: Canvas, _f: str) -> None:
    c.r(12, 22, 2, 1, "bl")
    c.r(26, 22, 2, 1, "bl")


@part("accessory.antenna", "Antenna", "cosmic", ("accent",))
def _accessory_antenna(c: Canvas, _f: str) -> None:
    c.r(19, 3, 2, 6, "accent_d")
    c.r(18, 1, 4, 2, "accent_l")
    c.r(19, 0, 2, 1, "st")


# ---------------------------------------------------------------------------
# Composing and recolouring

def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    # floor(x + 0.5), the same rounding as the dashboard's Math.floor(x + 0.5): Python's round() is banker's.
    return tuple(int(a[i] + (b[i] - a[i]) * t + 0.5) for i in range(3))  # type: ignore[return-value]


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def ramp(h: str) -> dict[str, tuple[int, int, int]]:
    """The three tones of a chosen colour: the colour, 40 % toward the outline, 38 % toward white."""
    m = hex_to_rgb(h)
    return {"m": m, "d": _mix(m, FIXED["o"], 0.40), "l": _mix(m, (255, 255, 255), 0.38)}


def outline(c: Canvas) -> None:
    """One pixel of outline around the silhouette, on transparent pixels only."""
    px = c.px
    pts = []
    for y in range(H):
        for x in range(W):
            if px[x, y][3] == 0:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < W and 0 <= ny < H and px[nx, ny][3] > 0:
                        pts.append((x, y))
                        break
    for x, y in pts:
        c.p(x, y, "o")


def recolor(c: Canvas, colors: dict[str, str]) -> None:
    table: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    for slot, tones in KEYS.items():
        chosen = colors.get(slot)
        if not chosen:
            continue
        r = ramp(chosen)
        for tone, key in tones.items():
            table[key] = r[tone]
    px = c.px
    for y in range(H):
        for x in range(W):
            p = px[x, y]
            if p[3] and (p[0], p[1], p[2]) in table:
                px[x, y] = (*table[(p[0], p[1], p[2])], p[3])


def compose(parts: dict[str, str], frame: str = "closed", colors: dict[str, str] | None = None) -> Image.Image:
    """The character: parts by layer, one frame, recoloured when colours are given."""
    if frame not in FRAMES:
        raise ValueError(f"unknown frame {frame!r}")
    out = Canvas()
    sil = Canvas()
    det = Canvas()
    for layer, stage in LAYERS:
        pid = parts.get(layer)
        if not pid:
            continue
        p = PARTS[pid]
        if p.layer != layer:
            raise ValueError(f"{pid} is not a {layer} part")
        target = {"backdrop": out, "silhouette": sil, "detail": det}[stage]
        p.draw(target, frame)
    outline(sil)
    out.paste(sil)
    out.paste(det)
    if colors:
        recolor(out, colors)
    return out.im


def render_part(pid: str, frame: str = "closed") -> Image.Image:
    """One part alone, in the key palette: what the exporter writes."""
    c = Canvas()
    PARTS[pid].draw(c, frame)
    return c.im


# ---------------------------------------------------------------------------
# Defaults

#: Cael's look is fixed: the constellation hoodie, galaxy eyes, violet hair on Space.
CAEL_LOOK: dict = {
    "version": 1,
    "parts": {
        "backdrop": "backdrop.space",
        "body": "body.sprout",
        "outfit": "outfit.constellation",
        "hair": "hair.swoop",
        "hat": "hat.none",
        "face": "face.galaxy",
        "accessory": "accessory.none",
    },
    "colors": {"skin": "#e0a98a", "hair": "#7b6bff", "outfit": "#1a1250", "accent": "#22e6ff", "eyes": "#22e6ff"},
}


def fnv1a(text: str) -> int:
    h = 0x811C9DC5
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def default_look(alias: str, catalog: dict) -> dict:
    """Every agent has a face from day one: Cael's own, or one dealt from its name (the same deal on the dashboard)."""
    if alias == "cael":
        return json.loads(json.dumps(CAEL_LOOK))
    starter = [p for p in catalog["parts"] if p["pack"] == "starter"]
    by_layer: dict[str, list[str]] = {}
    for p in starter:
        by_layer.setdefault(p["layer"], []).append(p["id"])
    h = fnv1a(alias)
    parts: dict[str, str] = {}
    for i, layer in enumerate(LAYER_ORDER):
        ids = by_layer[layer]
        parts[layer] = ids[(h >> (i * 4)) % len(ids)]
    colors: dict[str, str] = {}
    for i, slot in enumerate(SLOTS):
        palette = catalog["colors"][slot]
        colors[slot] = palette[(h >> (i * 3 + 7)) % len(palette)]
    return {"version": 1, "parts": parts, "colors": colors}


def load_catalog(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
