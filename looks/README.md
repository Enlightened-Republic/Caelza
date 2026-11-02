# Looks: every agent's pixel character

Vision M8. An agent is a character, not a bot icon: one piece per layer
(backdrop, body, outfit, hair, hat, face, accessory) in the owner's colours
(skin, hair, outfit, accent, eyes), drawn on a 40 × 44 grid. It blinks, and it
talks in the chat while the agent answers.

```
looks/
├── parts.py       every piece as code (rectangles on the grid) in the key palette; compose(), recolor(), the defaults
├── catalog.json   the packs the Shop sells and the pieces each holds, the colour palettes, Cael's look
└── README.md      this
scripts/looks.py   export | check | render <alias> | lineup
runtime/overlay/web/public/looks/parts/<layer>/<piece>[.<frame>].png   what `export` writes (1x, key palette)
runtime/overlay/web/public/looks/sheets/<pack>.png                     every piece of a pack on a base look
runtime/overlay/web/src/looks/                                          the dashboard's renderer and logic
runtime/overlay/crates/caelza-gateway/src/api_looks.rs                  /api/looks/{alias}, /api/looks/wardrobe
```

## How a piece becomes every colour

A piece is drawn once, in *key colours*: improbable RGB values per slot and
tone (`skin`, `skin_d`, `skin_l`, …; `KEYS` in parts.py). The renderer swaps
each key for the owner's chosen colour and its two tones (40 % toward the
outline, 38 % toward white). The same maths runs in Python (previews, the
sheets, the checks) and in the browser (`looks.logic.ts`), and
`tests/test_looks.py` pins the two: the hash that deals a default, the ramps,
the layer order, the keys.

Draw order: the backdrop; then the silhouette layers (body, outfit, hair,
hat), which get one outline around their union; then the detail layers (face,
accessory) on top. Faces have three frames: `closed`, `open`, `blink`.

## Adding a pack

1. Draw the pieces in `parts.py` with the `@part("layer.name", "Name", "pack", ("slots",))` decorator; keep to the grid conventions at the top of the file and BRAND.md's palette.
2. List the pack and its pieces in `catalog.json` (`price: "free"` or `{"usd": n}` with an `unlock`; `status: "available"`, or `"soon"` with no pieces yet).
3. `python3 scripts/looks.py export`, then look at `runtime/overlay/web/public/looks/sheets/<pack>.png`.
4. `python3 scripts/looks.py check` (CI runs it through `tests/test_looks.py`).

Every agent gets a default dealt from its name until the owner dresses it;
Cael's is fixed (`CAEL_LOOK`). A saved look lives on the Runtime at
`~/.caelza/agents/<alias>/look.json`; the wardrobe (the packs the owner
added) at `~/.caelza/looks/wardrobe.json`.
