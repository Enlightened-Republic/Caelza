# Caelza brand

**Enlightened Republic™ presents Caelza.**

[Enlightened Republic](https://www.enlightenedrepublic.tech) is the umbrella:
the lab that builds everything else (SharpWave, xanima, Alt Aliens, the Build
Lab services). Caelza is one of its products. It inherits the Republic's Build
Lab system (type, spacing, eyebrows, the palette) and adds its own identity on
top: a mark, a wordmark face, and a cosmic backdrop.

**Caelza** (KAY-el-za), from *caelum*, Latin for sky. Airframe Lite was the
load-bearing structure; Caelza is what it was for: an agent on real hardware,
out in the world, under an open sky.

Tagline: **The embodied agent runtime.**

## The mark: Caelum as a bolt

**Caelum** is a real constellation, the chisel, a faint little figure in the
southern sky next to Eridanus. Its four main stars, δ, α, β and γ Caeli, form a
bent line. The Caelza mark draws that line as a **lightning bolt**: the four
stars sit at the bolt's four turning points and the constellation line is the
bolt's zigzag spine. A chamfered **C** sits in the centre, drawn as an outlined
neon letter.

| Star | Brightness (mag) | Where it sits |
|---|---|---|
| α Caeli | 4.45, the brightest | the left notch, the biggest glyph |
| γ Caeli | 4.55 | the head of the bolt |
| β Caeli | 5.05 | the right notch |
| δ Caeli | 5.07 | the tip |

The sky figure is a hook; the bolt takes the liberty of a zigzag and a mirror,
as star globes do. Star order and relative brightness are kept, so it is
still Caelum. Three faint minor stars add texture and carry no lines.

Construction:

- Bolt outline in the mark gradient (cyan `#22e6ff` → violet `#7b6bff` →
  purple `#b44fff`, top to bottom) with a soft glow; the bolt body is a
  translucent space-black so the stars read on any surface.
- Constellation spine: a thin bright line δ → α → β → γ, drawn under the C.
- The C: dark fill, then the outline drawn as **two parallel neon lines** (a
  gradient stroke with its centre cut back out), with glow. That double line
  is what makes it read as a letter instead of a bar.
- Stars are four-point glyphs with a cyan glow and a bright core, sized by
  brightness.
- At 40 px and above everything glows. Below that it is flat.
- Geometry in `tokens.json` → `mark` (`bolt`, `c_polygon`, `stars`,
  `constellation`, `minor_stars`); vector in `logo.svg`; `make_assets.py`
  renders PNG/ICO/ICNS from the same numbers.

Minimum size 16 px (favicon). Never recolour the gradient; on a single-colour
surface use flat primary cyan. Never fill the bolt solid.

## The art

Two illustrations live in `art/` as **reference material**, not as the mark:

| File | What | Status |
|---|---|---|
| `art/caelza-hero-src.jpg` | a bolt-C with constellation stars over a starfield and dot matrix, wordmark below | the direction the mark and backdrop follow; copied into the runtime docs as `caelza-hero-art.jpg` |
| `art/caelza-app-icon-src.png` | a constellation figure in a neon-framed rounded square | undecided. Not used by default; `make_assets.py --art-icons` swaps it in for app icons at 128 px and above if wanted |

App icons use the geometric mark on the cosmic backdrop inside a neon gradient
frame at every size by default.

## The lockup

```
ENLIGHTENED REPUBLIC™ PRESENTS          ← eyebrow: JetBrains Mono, caps, 0.16em, dim
[mark]  CAELZA                          ← wordmark: Orbitron 900, caps, 0.06em, gradient fill
        The embodied agent runtime.     ← tagline: Inter Tight 400, muted
```

- The eyebrow always reads `ENLIGHTENED REPUBLIC™ PRESENTS`, with the ™, in
  the Republic's eyebrow style.
- The wordmark is **Orbitron** (SIL OFL), caps, filled with the mark gradient
  running left to right, with a faint glow. It is the one place Orbitron
  appears; headings and UI stay Inter Tight.
- On web surfaces the Republic's own mark (the neon ring with the alien) may
  sit left of the eyebrow at nav size (≤ 56 px). Never recoloured, never
  inside the Caelza mark.
- Banners use the **cosmic backdrop**: space black `#050310`, purple nebula
  glows (top-left and bottom-right) with a faint pink one, a starfield, and the
  cyan dot matrix fading out from the mark. `make_assets.py` renders it;
  `tokens.css` has a CSS approximation (`--cz-hero-bg`).

## Colour

The Build Lab palette (`enlightenedrepublic.tech/styles.css`) with Caelza's
cosmic tint: the darks carry a violet cast, and primary moves from the Lab's
teal to the mark's cyan. Dark is the default; `caelza-light` is derived and
should stay rare.

| Token | Hex | Role |
|---|---|---|
| Space | `#050310` | hero / banner / login backdrops |
| Void | `#06040f` | app base background |
| Bg 2 / 3 / 4 | `#0c0918` `#120e22` `#1a1530` | surface, elevated, hover surfaces |
| Bone | `#e8e4f0` | primary text |
| Muted / Dim / Faint | `#a8a8c0` `#6e6e85` `#4a4a5e` | secondary text, eyebrows, hints |
| **Primary (cyan)** | `#22e6ff` (light `#7af0ff`) | links, focus, primary buttons, status dot, the top of the mark |
| Violet | `#7b6bff` | the middle of the mark gradient |
| **Purple** | `#b44fff` | second accent: selection, the "™" dot, nebula glows, the bottom of the mark |
| Teal | `#00f5d4` | the Lab's primary; available, not default in Caelza |
| Pink | `#ff2d78` | sparingly: errors, the hot end of the Republic gradient |
| Yellow | `#ffe600` | warnings, "needs you" |
| Green | `#39ff14` | success |
| Star | `#eafcff` | constellation stars, highlights |
| Mark gradient | `#22e6ff → #7b6bff → #b44fff` | the bolt, the wordmark, one hairline per view |
| Republic gradient | `#ff4fb8 → #b44fff → #22e6ff` | parent-brand moments only |

Rules of thumb: cyan does the work; purple marks the brand; the gradient is a
flourish, not a fill; status colours are reserved for status. One glowing
element per view.

## Type

- **Orbitron 900** for the wordmark only.
- **Inter Tight** for everything you read: headings 700 at −0.02em, body 400,
  brand text 700 at 0.06em.
- **JetBrains Mono** for everything that labels: eyebrows, kickers, badges,
  pills, HUD text, code. Eyebrows are uppercase at 0.16em, 11 px, dim.
- The Republic's pixel faces (Jersey 10, VT323, Silkscreen) belong to the
  `.online` broadcast side of the house and are not used in Caelza.

Fonts are vendored in `fonts/` (SIL OFL 1.1, licences alongside) so renders
are reproducible.

## Voice

The Republic's voice, in product form: short declaratives, section labels in
caps, dry confidence. "We build things that actually work." "Signal in the
noise." Caelza copy says what happened and what to do next. The irreverence
and profanity of `enlightenedrepublic.online` stay on the broadcast side; the
product is plain.

Always `ENLIGHTENED REPUBLIC™` (caps, with ™) when the parent is named in UI
chrome; `Enlightened Republic` in prose; `EST. 2026` where the Republic signs
things.

## Files

```
brand/
├── BRAND.md         this guide
├── tokens.json      colours, type, radii, motion, parent links, mark geometry (source of truth)
├── tokens.css       the same as CSS custom properties, dark + derived light, hero backdrop
├── logo.svg         the mark, vector (Caelum as a bolt: gradient strokes, glow, spine, stars, outlined C)
├── hero.png         the rendered README banner (regenerated by make_assets.py)
├── art/             reference illustrations (bolt hero; the figure icon, undecided)
├── make_assets.py   renders mark / icons / wordmark / banners (brand/out, or into a runtime tree; --art-icons opt-in)
├── fonts/           Orbitron 900, Inter Tight 400/700, JetBrains Mono 500 + OFL licences
└── out/             rendered assets (git-ignored; `python3 brand/make_assets.py`)
```
