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
bolt's zigzag spine. That is the whole mark. The name is carried by the
wordmark, not by a letter inside the bolt.

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
  translucent space-black so the stars read on any surface. The waist (the
  run between the two notches) is long, so the spine has room.
- Constellation spine: a thin bright line δ → α → β → γ.
- Stars are four-point glyphs with a cyan glow and a bright core, sized by
  brightness. Three faint minor stars add texture and carry no lines.
- At 40 px and above everything glows. Below that it is flat.
- Geometry in `tokens.json` → `mark` (`bolt`, `stars`, `constellation`,
  `minor_stars`); vector in `logo.svg`; `make_assets.py` renders
  PNG/ICO/ICNS from the same numbers.

**The optional C.** A chamfered C can sit in the bolt's waist: symmetric arms,
outlined as two parallel neon lines, and sheared to lean with the bolt so its
verticals run parallel to the bolt's edges. It is off by default because it
competes with the stars and its outline goes faint at icon sizes. Turn it on
with `mark.c.enabled: true` in `tokens.json` or `make_assets.py --with-c`;
the vector is `logo-with-c.svg`.

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

The Android app's launcher icon is **adaptive** (the launcher picks the shape),
so it has no frame: `make_assets.py --android android/app` renders the mark
alone onto the foreground layer, inside the 66 dp circle every shape shows,
the backdrop's nebula as the background layer (no stars or dots: they would
swim with the parallax), and the mark's silhouette as a monochrome vector that
Android 13 tints for themed icons and the Runtime notification uses as its
status-bar icon. The layers are committed under the app's `res/`;
`make_assets.py --android android/app --check` (run by CI) compares them with
a fresh render.

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

The one surface that wears more is the simplified setup (`/setup` on the
dashboard, the first run in the app): Space as the backdrop with the nebula
glows, the title in the mark gradient, the screen's one primary button filled
cyan → violet, Cael's bubble on Bg 3 with a violet rule. It is the first thing a
new owner sees, so it carries the brand. The pages behind it wear less, and
the same things on every one of them: the mark and the wordmark in the top
bar under a hairline of the mark gradient, the page title in the mark
gradient (the one glowing element), the primary button filled cyan → violet,
Space with the two nebula glows behind the cards. The Republic gradient still
appears only in the parent's own moments.

The agents' pixel characters (`looks/`) use the palette above for their
colour swatches and `#0d0820` for every outline; a pack's new pieces should
keep to it, with one accent that repeats.

## Type

- **Orbitron 900** for the wordmark only.
- **Inter Tight** for everything you read: headings 700 at −0.02em, body 400,
  brand text 700 at 0.06em.
- **JetBrains Mono** for everything that labels: eyebrows, kickers, badges,
  pills, HUD text, code. Eyebrows are uppercase at 0.16em, 11 px, dim.
- The Republic's pixel faces (Jersey 10, VT323, Silkscreen) belong to the
  `.online` broadcast side of the house and are not used in Caelza.

Fonts are vendored in `fonts/` (SIL OFL 1.1, licences alongside) so renders
are reproducible, and the dashboard serves the same files: `make_assets.py
--runtime` copies them into `web/public/fonts`, `runtime/overlay/web/src/caelza-brand.css`
declares them, and Inter Tight is the dashboard's default UI face. The lockup
and the footer attribution are one component,
`runtime/overlay/web/src/components/brand/CaelzaLockup.tsx`.

## Voice

The Republic's voice, in product form: short declaratives, section labels in
caps, dry confidence. "We build things that actually work." "Signal in the
noise." Caelza copy says what happened and what to do next. The irreverence
and profanity of `enlightenedrepublic.online` stay on the broadcast side; the
product is plain. **Cael**, the in-app guide (the same Cael who chats on
`enlightenedrepublic.tech`), is the warm face of it: friendly and personable,
still clear and short, says what happened and what to do next, no
exclamation-mark spam, no hype. His persona and prompt are in `guide/CAEL.md`.

Always `ENLIGHTENED REPUBLIC™` (caps, with ™) when the parent is named in UI
chrome; `Enlightened Republic` in prose; `EST. 2026` where the Republic signs
things.

## Files

```
brand/
├── BRAND.md         this guide
├── tokens.json      colours, type, radii, motion, parent links, mark geometry (source of truth)
├── tokens.css       the same as CSS custom properties, dark + derived light, hero backdrop
├── logo.svg         the mark, vector (Caelum as a bolt: gradient strokes, glow, spine, stars)
├── logo-with-c.svg  the opt-in variant with the chamfered C in the waist
├── hero.png         the rendered README banner (regenerated by make_assets.py)
├── art/             reference illustrations (bolt hero; the figure icon, undecided)
├── make_assets.py   renders mark / icons / wordmark / banners (brand/out, or into a runtime tree; --with-c and --art-icons opt-in)
├── fonts/           Orbitron 900, Inter Tight 400/700, JetBrains Mono 500 + OFL licences
└── out/             rendered assets (git-ignored; `python3 brand/make_assets.py`)
```
