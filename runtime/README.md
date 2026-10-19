# Caelza Runtime

The Caelza runtime is the agent engine: the loop, model providers, channels,
tools, security policy, SOP engine, cron, gateway and web dashboard. It is a
**rebranded build of [ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw)**
(MIT OR Apache-2.0), produced from a pinned upstream commit by the pipeline in
this directory. Nothing here is a hand-maintained fork: the delta from upstream
is a rename map, a theme map, brand assets, an optional overlay and patches.

```
runtime/
├── upstream.toml      pinned upstream repo + commit + version
├── brand.env          product / org / repo variables
├── rename-map.txt     ordered literal replacements (paths + contents)
├── protect.txt        tokens the rename must never touch (plugin ABI namespace)
├── exclude.txt        files whose contents stay verbatim (licences, changelog)
├── theme-map.txt      dashboard fallback palette → Enlightened Republic tokens
├── overlay/           files copied over the renamed tree (optional)
├── patches/           *.patch applied after the rename (optional)
├── lib/rename.pl      the replacement engine
├── lib/dashboard_theme.py  registers caelza-dark / caelza-light as the dashboard defaults
└── build.sh           fetch → rebrand → cargo build
```

## Build

```bash
./runtime/build.sh                 # fetch pin, rebrand, cargo build --release → runtime/dist/caelza
./runtime/build.sh --check-only    # same, but cargo check (the CI gate)
./runtime/build.sh --no-build      # produce the rebranded tree only (runtime/.build/src)
./runtime/build.sh --from ~/src/zeroclaw   # reuse a checkout already at the pinned commit
```

Requirements: Rust `>= 1.96` (upstream `rust-version`), `git`, `perl`, `tar`,
and `python3` with Pillow for the brand assets (or `--skip-assets`). The web
dashboard is **not** rebuilt by this script; upstream builds it in CI with
Node 24+. `runtime/.build/src/web` is the rebranded source for `npm run build`
when you want a fresh `web/dist`.

Outputs are git-ignored: `.cache/` (upstream checkout), `.build/` (staged tree
+ cargo target dir, kept warm between runs), `dist/` (the binary).

### Android / Termux

Upstream publishes an experimental `aarch64-linux-android` binary and documents
the NDK cross-build; the same applies here:

```bash
rustup target add aarch64-linux-android
export ANDROID_NDK_HOME=/path/to/ndk
export PATH=$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin:$PATH
./runtime/build.sh --no-build
(cd runtime/.build/src && cargo build --release --target aarch64-linux-android -p caelza)
```

The TUI (`caelcode`, upstream `zerocode`) does not build for Android.

## What gets renamed

| Upstream | Caelza |
|---|---|
| `zeroclaw` / `ZeroClaw` / `ZEROCLAW` | `caelza` / `Caelza` / `CAELZA` |
| `zerocode` (TUI) | `caelcode` |
| `zerorelay` (relay) | `caelrelay` |
| `zeroclaw-labs`, `ZeroClaw Labs` | `Enlightened-Republic`, `Enlightened Republic` |
| `zeroclaw.com`, `docs.zeroclaw.com`, Discord | the Caelza GitHub repo / discussions |
| `~/.zeroclaw/config.toml` | `~/.caelza/config.toml` |
| `ZEROCLAW_*` env vars | `CAELZA_*` |
| crate names `zeroclaw-*` | `caelza-*` |

**Not renamed, on purpose:** the WASM plugin ABI namespace `zeroclaw:plugin@0.1.0`
(and the generated Rust path `zeroclaw::plugin`). It is baked into prebuilt
`.component` fixtures and into every third-party ZeroClaw plugin. Keeping it
means Caelza loads upstream WASM plugins unchanged. `LICENSE-*`, the upstream
`NOTICE` and `CHANGELOG-next.md` are kept verbatim; the build prepends a fork
notice and writes `UPSTREAM.md` with the exact provenance.

The residual check at the end of the pipeline fails if any upstream brand token
survives outside those protected places, so a new upstream commit that adds a
`zeroclaw`-named thing somewhere unexpected breaks the build loudly rather than
leaking into a release.

## Theme

Two steps make the dashboard look like an Enlightened Republic product:

1. `lib/dashboard_theme.py` builds `caelza-dark` and `caelza-light` from
   [`../brand/tokens.json`](../brand/tokens.json), inserts them at the top of
   the dashboard theme registry (`web/src/contexts/themes.json`) and sets them
   as `DEFAULT_DARK_THEME` / `DEFAULT_LIGHT_THEME` in `colorThemes.ts`. Every
   upstream theme stays selectable.
2. `theme-map.txt` rewrites the hard-coded `:root` fallbacks in `index.css` and
   the `cyan` accent preset in `ThemeContext.tsx` to the same tokens (teal on
   void, Inter Tight), so nothing flashes grey before the theme applies.

The accent picker's internal id for teal stays `cyan`; relabelling it is UI
phase 1 in `docs/design/caelza-vision.md`.

## Tracking upstream

1. Edit `upstream.toml` → new `commit` / `version`.
2. `./runtime/build.sh --check-only`.
3. If the residual check fails, extend `rename-map.txt` (or `protect.txt` /
   `exclude.txt`). If compilation fails, add a patch under `patches/`.
4. Commit the delta. The rebranded tree itself is never committed.

## Trademark note

"ZeroClaw" and the ZeroClaw logo are trademarks of ZeroClaw Labs. A
redistributed build must not use them, which is the reason this pipeline exists
rather than a plain fork. The licences permit the code; the name and logo are
replaced everywhere a user could see them.
