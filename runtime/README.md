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
├── overlay/           files copied over the renamed tree: crates/caelza-memory/src/xanima.rs (the Mind as a native
│                      memory backend); crates/caelza-gateway/src/api_mind.rs (/api/mind, the brain service proxied
│                      for the dashboard); crates/caelza-gateway/src/api_bodies.rs (/api/bodies, the Body's MCP server
│                      reached for the dashboard); web/ brand CSS, the lockup component, PWA manifest + service worker,
│                      the Home, Bodies, Memory and Procedures pages, the shared ApprovalQueue
├── patches/           *.patch applied after the rename: 0001 xanima memory backend (config schema, backend registry,
│                      factory, dashboard picker); 0002 UI phase 1 (fonts default, lockup, attribution, accent labels,
│                      PWA hooks, Service-Worker-Allowed in the gateway); 0003 the Memory page (routes, router, sidebar);
│                      0004 the Bodies page (routes, router, sidebar, the nav.bodies string); 0005 Home and Procedures
│                      (the digest route, Home at /, the dashboard at /dashboard, sidebar + palette + titles, strings);
│                      0006 the phone-first pass (header actions wrap, globe-only language button, chat toolbar wraps,
│                      Runs padding and titles, no font CDN)
├── tools/phone-shots/ Playwright over every dashboard route at 390 × 844: screenshots, sideways scroll, elements past
│                      the edge, controls under 32 px; a mock proxy for the Mind and Body routes
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

`build.sh` builds with `--features channel-git` (the Forge's git channel,
[`../docs/forge.md`](../docs/forge.md), which upstream keeps out of its lean
default), the same flag the release workflow passes; `CAELZA_FEATURES=` drops
it, `--features <list>` replaces it.

Requirements: Rust `>= 1.96` (upstream `rust-version`), `git`, `perl`, `tar`,
and `python3` with Pillow for the brand assets (or `--skip-assets`). The web
dashboard is **not** rebuilt by this script; upstream builds it in CI with
Node 24+. `runtime/.build/src/web` is the rebranded source for `npm run build`
when you want a fresh `web/dist`.

Outputs are git-ignored: `.cache/` (upstream checkout), `.build/` (staged tree
+ cargo target dir, kept warm between runs), `dist/` (the binary).

### Android / Termux (the phone)

On the phone, install the release build in Termux with one line (the Body has
its own installer, `../install.sh`):

```bash
curl -fsSL https://raw.githubusercontent.com/Enlightened-Republic/caelza/main/runtime/termux-install.sh | sh
```

[`termux-install.sh`](termux-install.sh) finds the latest release (or
`CAELZA_VERSION=v0.1.0`), downloads `caelza-<ver>-aarch64-linux-android.tar.gz`,
checks its `.sha256`, puts `caelza` in `$PREFIX/bin` and the dashboard in
`~/.local/share/caelza/web/dist` (the gateway finds it there), and prints the
next steps. While the repo is private, export `GITHUB_TOKEN` first.
`CAELZA_BOOT=1` also writes a Termux:Boot script that starts `caelza daemon`
after a reboot. Then [`caelza.phone.example.toml`](caelza.phone.example.toml)
is the config to merge after `caelza quickstart`: Telegram through the Runtime,
the Mind and the Body as MCP servers, and the risk profile for them.

To cross-build the Android binary yourself (the release workflow does this on
every `v*` tag; the target is marked experimental there):

```bash
rustup target add aarch64-linux-android
export ANDROID_NDK_HOME=/path/to/android-ndk-r27c    # or put its llvm bin dir on PATH
./runtime/build.sh --target aarch64-linux-android      # → runtime/dist/caelza-aarch64-linux-android
```

`--target` passes the triple to cargo, points the `cc` crate at the NDK clang
for the bundled sqlite and `ring`, and names the output after the target so it
never clobbers the host binary. Verified with NDK r27c against the current pin:
a 34 MB `aarch64` PIE linked against Bionic (`/system/bin/linker64`; only
`libc`, `libm`, `libdl`), 14 minutes on a laptop-class box.

The release profile is `opt-level = "z"`, `lto = "fat"`, `codegen-units = 1`,
so the final link of the `caelza` crate is the expensive step: measured at a
**12 GB peak** of resident memory for the Android target. A hosted GitHub
runner has 7 GB, which is why `release.yml` gives the two aarch64 legs an
8 GiB swapfile (on the runner's `/mnt` scratch disk) and `--jobs 2`, the same
recipe upstream uses for its aarch64 Linux releases. It is also why building
natively on the phone is not the intended path: the REVVL's 8 GB would hit the
same wall at the link. Build on a box, ship the archive. Building natively inside Termux
(`pkg install rust`) also works but takes hours on a phone; the release build
is the intended path. The TUI (`caelcode`, upstream `zerocode`) does not build
for Android, so the Android archive carries `caelza` only.

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
   If `0001-xanima-memory-backend.patch` no longer applies, re-apply its hunks
   by hand on the renamed tree, then regenerate it with `diff -u` against a
   pristine copy of each file it names (`a/<path>` / `b/<path>` labels; the
   leading paragraph is kept by `patch`). `tests/test_mind_example.py` checks
   the file list and the defaults it carries.
4. Commit the delta. The rebranded tree itself is never committed.

## Trademark note

"ZeroClaw" and the ZeroClaw logo are trademarks of ZeroClaw Labs. A
redistributed build must not use them, which is the reason this pipeline exists
rather than a plain fork. The licences permit the code; the name and logo are
replaced everywhere a user could see them.
