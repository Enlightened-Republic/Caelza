# Dashboard screens

Reference screenshots of the Caelza dashboard, taken with
`runtime/tools/phone-shots` against a running gateway. They document the
phone-first pass (vision §7, M4 phase 3b) and are the baseline the next pass
compares against; regenerate them with the same tool when a page changes.

## `390/` — phone width, 390 × 844, 1× scale, dark

The set was retaken after the brand pass (M4 phase 4b): the mark and the
wordmark in the top bar, page titles in the mark gradient, the primary button
cyan → violet, Space with the nebula glows behind every page.

| file | what it shows |
|---|---|
| `home.png` | Home: the Runtime / Mind / Body tiles, your agents with their looks (M8d: the one you talked to last first, a tap opens its chat), waiting on you, the digest with the look beside each conversation that moved |
| `bodies.png` | Bodies: this phone and the paired phones, senses, capture, packages |
| `memory.png` | Memory: the brains, status, recall, the review queue |
| `procedures.png` | Procedures: waiting, running, the library with the four phone playbooks (M5), finished |
| `procedures-run.png` | the Run dialog for `phone-debloat`: which phone, what to leave alone, where the gate is |
| `dashboard.png` | the upstream dashboard at `/dashboard`, its tab bar scrolling |
| `agent-chat.png` | the chat: the agent's look in the header and on its tab, beside each of its bubbles (held still) and talking beside the answer as it streams in (M8d); the toolbar wrapped onto two rows |
| `tools.png` | Tools, its controls wrapped and the CLI table scrolling inside its card |
| `runs.png` | SOP Runs with its page padding and a header title |
| `drawer.png` | the mobile menu: Home, Bodies, Memory, Procedures first |
| `quickstart-doors.png` | Quickstart's first screen: the two doors, free and local or bring your own key (vision §3.4) |
| `quickstart-local-door.png` | the local door: where Caelza runs, the RAM band, the ladder's model, Cael's line and the honest notes |
| `setup-doors.png` | the simplified setup (`/setup`, M4 phase 4a): Cael's hello and the two doors, in the brand's colours |
| `setup-provider.png` | the provider wheel: the curated eight, "More providers" for the rest the Runtime lists |
| `setup-model.png` | the model wheel: Cael's picks tagged on top (best pick, fast and cheap, strongest), the live catalog below |
| `setup-key.png` | the key box with where to get one, the show/hide eye, the chosen provider and model |
| `setup-local.png` | the local door: this phone or a computer, the RAM wheel, the ladder's pick and the honest notes |
| `looks.png` | Looks (M8): every agent as its pixel character, Cael's fixed and main's dealt from its name |
| `looks-dress.png` | the customizer: the preview that blinks and talks, a tab per layer, the pieces, the colour rows |
| `shop.png` | the Shop: the packs with their sheets, Starter always yours, Cosmic one tap away, Arcade coming soon |
| `agents.png` | the agents list with each agent's look in its row |
| `cael-explain.png` | Cael's panel from the top bar on Bodies: what the screen is, the next step, a question answered in his words |

The two quickstart shots were taken over the vite dev server with the daemon's
answers canned (Playwright routes for `/api/quickstart/*`, `/api/status`, the
pairing and reload probes), an Android user agent and this box's
`deviceMemory`, so the local door opens on the phone runner at the 8 GB band.
The setup shots were taken the same way (the catalog endpoint canned with a
few Anthropic models so the model wheel shows the live list under the picks).

## The app's launcher icon

| file | what it shows |
|---|---|
| `launcher-icon.png` | the adaptive icon (`brand/make_assets.py --android android/app`, android-app.md §5) as a round launcher and a squircle one show it, and the whole 108 dp layer |

The Mind and Body content in these shots comes from the tool's mock proxy
(canned `brain_stats`, `brain_status`, `device_list`, sensor readings), the
rest from a real gateway. The Procedures shots (M5) have the playbooks
installed under the gateway's `shared/sops`; the gateway runs standalone
(`caelza gateway start`), so the page says the engine is not running in this
process, which is what a standalone gateway is.
