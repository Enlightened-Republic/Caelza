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
scripts/looks.py   export | check | render <alias> | lineup | avatar <alias>
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
2. List the pack and its pieces in `catalog.json` (`price: "free"`, or `{"usd": n}` with `"unlock": "code"`; `status: "available"`, or `"soon"` with no pieces yet; `buy` is the storefront link once there is one).
3. `python3 scripts/looks.py export`, then look at `runtime/overlay/web/public/looks/sheets/<pack>.png`.
4. `python3 scripts/looks.py check` (CI runs it through `tests/test_looks.py`).

## The look as a profile picture

"Save as avatar" on the customizer (`/looks/<alias>`) downloads
`<alias>-avatar.png`: the look's closed frame on a 512 × 512 square at the
largest whole scale that fits (11, so 440 × 484 centred), the margins filled
by continuing the frame's edge (the backdrop's bands and lines, the torso)
rather than a border, and Space behind a look that has no backdrop. The same
file from the command line, for a saved look or the default:

```
python3 scripts/looks.py avatar main out.png --look ~/.caelza/agents/main/look.json
python3 scripts/looks.py avatar cael cael.png
```

`avatar_geometry` in `parts.py` and `avatarGeometry` in `looks.logic.ts` are
the same maths, pinned by the tests. Telegram, Discord and the rest accept it
as is.

## Selling a pack: unlock codes

A priced pack (the Arcade pack is the first) opens with a code the owner
mints and the Runtime checks; nothing else is needed, so a pack can be sold
through any storefront that can hand out a code after payment.

```
python3 scripts/unlock_codes.py keygen --out ~/.caelza-keys/unlock.key      # once: the signing key, kept out of the repo
python3 scripts/unlock_codes.py mint --key ~/.caelza-keys/unlock.key --pack arcade --count 10
python3 scripts/unlock_codes.py verify ARCADE-7K3PQ2M9-…                    # against the catalog's public key
```

A code is `<PACK>-<ID>-<SIGNATURE>`: the pack, eight characters that make
it its own (no 0/O or 1/I), and an Ed25519 signature over
`caelza-unlock:v1:<pack>:<id>`. The public key lives in two places that
`tests/test_unlock_codes.py` keeps equal: `catalog.json` (`unlock.public_key`)
and the gateway (`api_looks.rs` `UNLOCK_PUBLIC_KEY`, verified through rustls'
ring provider, so no new crate). The owner pastes a code into the Shop; the
Runtime verifies it (`POST /api/looks/wardrobe/unlock`), puts the pack in the
wardrobe and remembers the unlock, so the pack goes back in with one tap
after a remove. Rotating the key is `keygen` again and the two hex strings
updated; codes minted with the old key stop working, unlocks already
recorded stay. A code is cosmetic: this is an honest storefront, not DRM.

Every agent gets a default dealt from its name until the owner dresses it;
Cael's is fixed (`CAEL_LOOK`). A saved look lives on the Runtime at
`~/.caelza/agents/<alias>/look.json`; the wardrobe (the packs the owner
added) at `~/.caelza/looks/wardrobe.json`.
