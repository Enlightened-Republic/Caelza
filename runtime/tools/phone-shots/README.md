# phone-shots: the dashboard at phone width

The vision's first UI principle is phone-first: every page works at 390 px,
one hand. This is the tool that checks it. It drives a real Chromium through
Playwright over every dashboard route at 390 × 844, takes a full-page
screenshot of each, and measures what a phone would get wrong: does the
document scroll sideways, which elements stick out past the right edge, and
which controls are too small to tap (under 32 px).

```
runtime/tools/phone-shots/
├── shoot.js        the Playwright run: routes, screenshots, measurements, report.json
├── mock-proxy.js   canned /api/mind/* and /api/bodies/* in front of a gateway that lacks them
└── README.md       this
```

## Run it

You need a gateway serving the dashboard you want to measure, with pairing
off, and `playwright-core` plus a Chromium. The cloud image keeps a Chromium
under `/opt/pw-browsers`; point `PLAYWRIGHT_CHROMIUM` at any other.

```sh
# 1. A gateway with the built dashboard and no pairing prompt.
cat >> "$HOME/.caelza-shots/config.toml" <<'EOF'
[gateway]
host = "127.0.0.1"
port = 42617
require_pairing = false
web_dist_dir = "/path/to/runtime/.build/src/web/dist"
EOF
caelza gateway start --config-dir "$HOME/.caelza-shots" &

# 2. Optional: canned Mind and Body answers when the gateway binary predates
#    /api/mind and /api/bodies (or no brain service / Body is running).
node mock-proxy.js 42700 42617 &

# 3. The run. Arguments: base URL, output dir, width, height, device scale, routes.
npm i playwright-core
node shoot.js http://127.0.0.1:42700 ./shots 390 844 2
node shoot.js http://127.0.0.1:42700 ./shots-docs 390 844 1 "home,bodies,memory,drawer"
```

One line per route prints as it goes:

```
home                 ok                 offenders=0 smallTargets=1
tools                ok                 offenders=53 smallTargets=1
```

`ok` means the document does not scroll sideways. `offenders` counts elements
whose right edge passes the viewport; `report.json` lists the worst twelve
with their classes. Elements inside a scroll container (the dashboard's tab
bar, a table in an `overflow-x-auto` card, the SOP canvas) count too, so
read the list rather than the number. `smallTargets` counts tappable things
under 32 px; the sidebar footer's version label is the one that always
remains.

`drawer` opens the mobile menu from Home and shoots the viewport.

## What the pass changed (M4 phase 3b)

Most of it is CSS in `runtime/overlay/web/src/caelza-brand.css`, which sits
outside Tailwind's layers and therefore covers every page without touching
upstream markup: 16 px page gutters under 640 px, tables that scroll inside
their card, and a 36 px minimum for buttons, inputs, selects and flex links on
touch screens. `runtime/patches/0006-phone-first.patch` carries what CSS
cannot: the page header's actions slot wraps, the header's language button
keeps only its globe on a phone, the chat toolbar wraps, the Runs page gets
its page padding and a title, and the mono face is no longer fetched from a
font CDN. The before/after measurements are in the PR that shipped it; the
documentation set lives in `docs/design/screens/390/`.
