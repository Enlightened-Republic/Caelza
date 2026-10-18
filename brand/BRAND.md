# Caelza brand

**Enlightened Republic™ presents Caelza.**

[Enlightened Republic](https://www.enlightenedrepublic.tech) is the umbrella:
the lab that builds everything else (SharpWave, xanima, Alt Aliens, the Build
Lab services). Caelza is one of its products, so Caelza does not get its own
visual language. It uses the Republic's Build Lab system, with one mark and one
word of its own.

**Caelza** (KAY-el-za), from *caelum*, Latin for sky. Airframe Lite was the
load-bearing structure; Caelza is what it was for: an agent on real hardware,
out in the world, under an open sky.

Tagline: **The embodied agent runtime.**

## The lockup

```
ENLIGHTENED REPUBLIC™ PRESENTS          ← eyebrow: JetBrains Mono, caps, 0.16em, dim
[mark]  CAELZA                          ← wordmark: Inter Tight 700, caps, 0.04em, bone
        The embodied agent runtime.     ← tagline: Inter Tight 400, muted
```

- The eyebrow always reads `ENLIGHTENED REPUBLIC™ PRESENTS`, with the ™. It is
  set in the Republic's eyebrow style, never larger than the wordmark's x-height.
- On web surfaces the Republic's own mark (the neon ring with the alien,
  `er-profile-pic.png`) may sit left of the eyebrow at nav size (≤ 56 px). It is
  never recoloured, cropped, or placed inside the Caelza mark.
- The Caelza mark sits left of the wordmark. In a sidebar rail or favicon the
  mark stands alone; the parent attribution lives in the footer or About.
- Banners use the Build Lab backdrop: `#0a0a12`, a purple radial glow at the top,
  a faint pink glow right, a 24 px dot grid at 3% white, plus one gradient
  hairline. `make_assets.py` renders all of this.

## The mark

The Republic's logo is a neon ring. Caelza's mark is **that ring, opened into a
C**, in the Republic gradient: cyan at the lower end, purple through the body,
pink at the upper end. A yellow four-point **signal star** sits in the gap.

- The ring is the horizon and a C. Open on the right because the agent reaches
  out; it is not a closed box.
- The star is the agent: small, bright, at the opening. Yellow is the
  Republic's signal colour, and the only warm colour in the system.
- At 48 px and above the ring and star carry a soft neon glow, like the parent
  mark. Below that they are flat.
- Geometry in `tokens.json` → `mark`, vector in `logo.svg`; `make_assets.py`
  renders PNG/ICO/ICNS sets without an SVG rasteriser.

## Colour

The Build Lab palette (`enlightenedrepublic.tech/styles.css`), verbatim. Dark
is the default; there is no Republic light theme, so `caelza-light` is derived
and should stay rare.

| Token | Hex | Role |
|---|---|---|
| Void | `#0a0a12` | base background |
| Bg 2 / 3 / 4 | `#0f1018` `#14141f` `#1a1b25` | surface, elevated, hover surfaces |
| Bone | `#e8e4f0` | primary text |
| Muted / Dim / Faint | `#a8a8c0` `#6e6e85` `#4a4a5e` | secondary text, eyebrows, hints |
| **Teal** | `#00f5d4` (hover `#6cffe6`) | primary accent: links, focus, primary buttons, the status dot |
| **Purple** | `#b44fff` | second accent: the "™" dot, hero glow, selected states |
| Pink | `#ff2d78` | sparingly: errors, the hot end of the gradient |
| **Yellow** | `#ffe600` | signal: the star, warnings, "needs you" |
| Green | `#39ff14` | success |
| Gradient | `#ff4fb8 → #b44fff → #22e6ff` | the ring, one hairline per view |

Rules of thumb, from the Republic's sites: teal does the work; purple marks
the brand; pink and yellow appear once each at most; the gradient is a
flourish, not a fill. Status colours are reserved for status.

## Type

- **Inter Tight** for everything you read: headings 700 at −0.02em, body 400,
  brand text 700 at 0.06em.
- **JetBrains Mono** for everything that labels: eyebrows, kickers, badges,
  pills, HUD text, code. Eyebrows are uppercase at 0.16em, 11 px, dim.
- The Republic's pixel faces (Jersey 10, VT323, Silkscreen) belong to the
  `.online` broadcast side of the house. Caelza is a Build Lab product and
  does not use them.

Fonts are vendored in `fonts/` (SIL OFL 1.1, licences alongside) so banner
renders are reproducible.

## Voice

The Republic's voice, in product form: short declaratives, section labels in
caps, dry confidence. "We build things that actually work." "Signal in the
noise." Caelza copy says what happened and what to do next. The irreverence
and profanity of `enlightenedrepublic.online` stay on the broadcast side; the
product is plain.

Always: `ENLIGHTENED REPUBLIC™` (caps, with ™) when the parent is named in UI
chrome; `Enlightened Republic` in prose. `EST. 2026` where the Republic signs
things.

## Files

```
brand/
├── BRAND.md         this guide
├── tokens.json      colours, type, radii, motion, parent links, mark geometry (source of truth)
├── tokens.css       the same as CSS custom properties, dark + derived light
├── logo.svg         the mark, vector (gradient + glow)
├── make_assets.py   renders PNG/ICO/ICNS sets (brand/out, or into a runtime tree)
├── fonts/           Inter Tight 400/700, JetBrains Mono 500 + OFL licences
└── out/             rendered assets (git-ignored; `python3 brand/make_assets.py`)
```
