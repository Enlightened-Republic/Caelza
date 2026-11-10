# Caelza — vision, architecture, brainstorm

**Status:** Draft for discussion (2026-10-18). Supersedes the Airframe Lite
framing; the Airframe Lite design docs in this directory describe what is now
the **Body** layer and remain accurate for it.

---

## 1. What Caelza is

Caelza is an agent that lives on your own hardware, out in the world: a phone in
a pocket, a Pi on a shelf, a hub at home. It talks to you in the channels you
already use, remembers across months, acts on devices around it, and can be
trusted to run unattended because the parts that keep it alive cannot be
modified by the parts that think.

Three layers, three words, and the product name for the whole:

| Layer | What | Comes from |
|---|---|---|
| **Runtime** | agent loop, 20+ model providers, 30+ channels, tools, security policy, SOP engine, cron, gateway, dashboard, WASM plugins, hardware peripherals | rebranded ZeroClaw build (`runtime/`) |
| **Mind** | autonomic long-term memory: graph + forgetting curve + sleep | xanima (formerly openwave) on xanima-core (`mind/`) |
| **Body** | the device: termux-api sensors, ADB control of self and paired phones, the immutable supervisor with git-backed self-modification and rollback | Airframe Lite (`caelza_body/`) |

## 2. Why rebuild on ZeroClaw (decision record)

Airframe Lite is ~6.7k lines of Python: one model (MiniMax M3), one channel
(Telegram), hand-rolled loop, context, session and tool registry. It proved the
thesis (a supervised, self-modifying agent on a locked-bootloader phone, running
for weeks) and it is at the point where every next feature is infrastructure:
more providers, more channels, a UI, approvals, scheduling, plugins.

ZeroClaw already has all of that, in one static Rust binary that fits the
phone's RAM budget, with an Android target in its release matrix and a plugin
host. It is MIT OR Apache-2.0 and actively maintained (v0.8.6, 22 crates). What
it does **not** have is what Airframe Lite is: a body. No termux-api sensors, no
ADB fleet control with safety logging and pre-removal snapshots, no immutable
supervisor that probes a self-modified build before promoting it, no offline
degradation designed for a device that loses Wi-Fi.

So: take ZeroClaw as the Runtime, keep Airframe Lite as the Body, put xanima
between them as the Mind. The alternative (OpenClaw, TypeScript, 182 extensions,
57k files) is the richer ecosystem but needs Node 24+ and far more RAM; it is
the wrong engine for a 5 GB phone, and the right place to borrow ideas from
(§6).

Rebrand, not fork: `runtime/build.sh` regenerates the Caelza tree from a pinned
upstream commit with a rename map and brand assets. Tracking upstream is a
one-line pin bump. "ZeroClaw" is a trademark, which makes the rename a
requirement for redistribution, not vanity.

## 3. Target architecture

```
                 owner ── Telegram / Discord / voice / dashboard ──┐
                                                                   ▼
 ┌───────────────────────── Caelza Runtime (caelza, Rust) ─────────────────────┐
 │  channels → agent loop → providers (M3, Anthropic, OpenAI, Ollama, …)       │
 │  security policy · tool receipts · SOP engine · cron · gateway + dashboard   │
 │  tools: shell · browser · http · MCP servers ──────────────┐                 │
 └───────────────┬───────────────────────────────────────────┼─────────────────┘
                 │ Memory trait (XanimaMemory)             │ MCP (stdio or http)
                 ▼                                           ▼
 ┌──────── Caelza Mind ────────┐                 ┌──────── Caelza Body ────────┐
 │ xanima-server            │                 │ caelza-body MCP server      │
 │  shared brain + per-agent   │                 │  sensors_* (camera, mic,    │
 │  brains, tokens, sleep      │                 │   location, notifs, tts…)   │
 │ xanima (OpenClaw gateways)  │                 │  device_* (ADB self+remote, │
 │ xanima MCP (IDE agents)     │                 │   snapshots, audit log)     │
 └─────────────────────────────┘                 │  shell_run                  │
                                                 │ supervisor.py (immutable)   │
                                                 │  probe · promote · rollback │
                                                 └─────────────────────────────┘
```

Deployment shapes, all from the same bundle:

1. **Phone-only** (today's Niba): Runtime (`aarch64-linux-android`), Body and
   the xanima engine all in Termux on one phone.
2. **Hub + bodies**: Runtime and Mind on a Pi/NUC/VPS; one or more phones run
   only the Body, reached over Tailscale. Fleet management falls out of this.
3. **Dev box**: everything on a laptop with the dashboard; the phone is a
   paired body for testing.

### 3.1 The Body becomes an MCP server

`caelza_body/agent/tools/*` already have the shape of MCP tools (name, JSON schema,
handler) and `mcp` is already a dependency. `caelza-body` wraps them as a stdio
MCP server the Runtime spawns (or an `http` one it reaches over Tailscale).
Dangerous-op semantics stay in the Body: `reason` required, audit log, package
snapshot before any removal. The Runtime's approval policy adds a second gate on
top (`always_ask = ["body__device_uninstall", …]`).

**Shipped (M2, first half):** `caelza-body` (`caelza_body/mcp_server.py`,
console script from `pip install -e .`) serves the registry's 35 tools (39 since M5) over
stdio with the schemas passed through untouched; each tool is classified
read-only / destructive / neutral and carries the matching MCP annotations;
screenshots and photos come back as image content, which the Runtime attaches
to the reply; `caelza-body probe` is the health check. `body/caelza-body.example.toml`
is the Runtime wiring with the risk profile derived from those classes, and
`body/README.md` the operator doc. The memory tools are not served (the Mind
owns memory).

The Python agent loop, model wrapper, Telegram transport and SQLite session go
away once the Runtime owns the turn (the second half of M2, a per-phone switch
after M1). The supervisor stays, and now guards the Body's own code plus the
Runtime binary (§3.3).

### 3.2 The Mind

See `mind/README.md`. Short version: tools path now (`sharpwave` MCP), service
path for shared brains (`xanima-server`), then a native `XanimaMemory`
backend in the Runtime so recall is automatic per turn.

### 3.3 The Caelza app (Android + web) and Shizuku

The product people install is an **app**, not a Termux session. Two surfaces,
one Runtime:

- **Web app**: the Runtime's dashboard, phone-first (§7), installable as a PWA.
  It already exists; the redesign makes it the primary surface.
- **Android app**: a native companion that owns the Body. It replaces the
  Termux:API + loopback-ADB bring-up with things an app can do properly:
  a foreground service that survives Doze, a notification listener, an
  accessibility service for on-screen control, camera/mic/location through the
  normal Android APIs, and a WebView/PWA shell for the dashboard. It also
  supervises the Runtime binary (`aarch64-linux-android`) and the local model
  runner (§3.4), and packages the first-run wizard.

**Shizuku** is the privilege layer for that app. [Shizuku](https://github.com/RikkaApps/Shizuku)
(Apache-2.0) runs a small server with shell (`adb`) privileges, started once
per boot from Android's wireless-debugging pairing on-device (or from root /
the Sui Magisk module on rooted devices), and lets apps call system APIs
through it over Binder. That is exactly the reach the Body gets today by
pairing `adb` to `127.0.0.1` from Termux (`pm`, `settings`, `appops`, `input`,
`dumpsys`, `screencap`), without a terminal, without root, and with the
standard Shizuku permission prompt the user already understands from other
apps. The Body's `device_*` tools map onto it one to one:

| Body tool today (Termux + loopback ADB) | Caelza app + Shizuku |
|---|---|
| `device_shell` / `device_logcat` / `device_packages` | Shizuku `newProcess` / `IPackageManager` |
| `device_uninstall` / `device_disable` / `device_appops` / `device_settings` | `IPackageManager`, `IAppOpsService`, `Settings` via Shizuku binder |
| `device_input` / `device_screencap` / `device_ui_dump` | accessibility service + MediaProjection, Shizuku `input` as fallback |
| self-ADB pairing in `scripts/setup.py` | Shizuku's own pairing flow (one dialog) |
| paired remote phones over ADB | unchanged: the app runs `adb` against remotes, or each remote runs the app |

Shizuku needs re-starting after every reboot unless the device is rooted, so
the app's first-run wizard explains the "start Shizuku" step and the
supervisor treats a missing Shizuku server as a degraded Body (sensors still
work, privileged device ops report "needs Shizuku").

**Decision (2026-10-18): Termux + loopback ADB stays the primary path** for
the current test device, and Shizuku is an *optional permission*, granted the
way the Runtime's risk profiles grant capabilities rather than a different
product. Concretely:

- `body.privilege = "adb" | "shizuku"` in the Body config, default `adb`. The
  `device_*` tools are the same either way; only the transport underneath
  changes, so SOPs and approvals do not care which one is active.
- Two one-line installs, same Body: `curl … install.sh | sh` in Termux (ships
  now, `install.sh` at the repo root) and the app's installer when the app
  exists. Both end in the same Cael-led setup.
- A phone can run both: Termux for the headless agent, the app for the screen,
  Shizuku granted to whichever asks. Nothing is retired.

### 3.4 A free local model by default, bring your own to customise

Caelza should work with **no account and no API key**. Quickstart offers two
doors:

1. **Free, local**: DeepSeek R1 (MIT-licensed, including the distilled sizes).
   The Runtime already speaks Ollama and any OpenAI-compatible endpoint, so this
   is a default, not new plumbing.
2. **Bring your own**: any provider the Runtime supports (Anthropic, OpenAI,
   OpenRouter, MiniMax, Ollama, a custom endpoint) with the user's key, routed
   per agent with fallback chains.

The honest size ladder, by where the Runtime runs:

| Where | Runner | Default model | Notes |
|---|---|---|---|
| Hub / laptop / VPS (16 GB+) | Ollama | `deepseek-r1:14b` (8b on 8–12 GB) | tool use is usable; reasoning tokens are visible in the dashboard |
| Phone, 6–8 GB RAM | llama.cpp (Termux package or bundled in the app) | `DeepSeek-R1-Distill-Qwen-7B` Q4 | tight; keep context short |
| Phone, ≤ 5 GB RAM (the REVVL) | llama.cpp | `DeepSeek-R1-Distill-Qwen-1.5B` Q4 (~1.1 GB) | chat and explanation only; not reliable for multi-step tool calls |

So the local model has two jobs and one job it does not get by default:

- **Cael, the Guide** (`guide/CAEL.md`; he/him): the in-app helper who explains
  what an API key is, what a provider is, what Shizuku does, why an approval
  prompt appeared, and walks through setup in plain language. Warm, cute and
  personable on purpose: people should like him. This is the "super user
  friendly" layer: the same Cael who greets visitors on
  enlightenedrepublic.tech, here inside the product, running free and offline.
  Even the 1.5B model is good at this.
- **Offline reasoning**: when the phone has no network, the local model
  handles the Airframe "offline mode" cases (queued device actions, simple
  questions) instead of the canned "offline, will process later" reply.
- **The working brain** of a fully autonomous agent only when the hardware
  can run 8B+ well. Below that, the Guide suggests bringing a cloud model for
  the agent loop and keeps the local one for help and offline. The Runtime's
  per-agent provider routing makes "local Guide + cloud agent" one config.

Embeddings for the Mind stay local too: xanima defaults to
`ollama/qwen3-embedding:0.6b`.

### 3.5 Self-modification, generalised

Airframe Lite's loop was edit → test → commit → restart → probe → promote or
roll back, all on the phone. In Caelza the mutable surface splits:

| Surface | Who changes it | Guard |
|---|---|---|
| Runtime binary | CI, from this repo | last-good binary kept; supervisor swaps and probes (`caelza --version`, gateway health) and rolls back. **Shipped (M6):** `caelza_body/runtime_guard.py` + `caelza-body runtime update` |
| Runtime config, prompts, skills, SOPs | the agent, through its own tools | config validation fails closed; the supervisor snapshots `~/.caelza` before each self-change (**shipped** before each Runtime swap, M6) |
| Body code (`caelza_body/`) | the agent | unchanged: pytest → commit → restart → probe → promote/rollback |
| `supervisor.py` | nobody | deny-listed, as today |

**Forge (shipped, M6):** the agent proposes Runtime changes as pull requests
to this repo over the git channel (upstream's `channel-git`, built into every
release): `forge-propose` frames the change, reads the files as they are on
`main`, drafts the new content and the PR, and after the owner's gate writes
a `forge/<topic>` branch and a draft PR through `git_forge`; CI builds and
tests it; a human merges; a `v*` tag releases; the channel's
`release.published` starts `forge-release`, which asks the owner and hands
the tag to the guard (`body__runtime_update`). The agent improves its own
engine without ever holding the compiler (`docs/forge.md`).

Deployment shape 1 (phone-only) therefore becomes: the Caelza app hosts the
Body (via Shizuku), supervises the Runtime binary and the local model, and
shows the web app. No Termux required; Termux remains the headless option.

## 4. From Airframe Lite to Caelza: what carries over

| Airframe Lite | Caelza |
|---|---|
| `supervisor.py` | unchanged, guards Body + Runtime binary |
| `tools/sensors.py`, `tools/device.py`, `tools/shell.py`, `adb.py`, `devices.py` | `caelza-body` MCP server |
| `tools/selfmod.py` | unchanged for Body; Runtime-side config edits via runtime tools |
| `tools/web.py` (Firecrawl search/read/map/crawl, multi-provider search, IP geolocation) | keep as Body tools until the Runtime's browser/http tools cover them; the geolocation + time-in-context pieces move into the system prompt assembly |
| `memory.py`, `tools/memtools.py`, `memreset.py` | superseded by Mind (same engine, same db) |
| `loop.py`, `model.py`, `context.py`, `session.py`, `telegram.py`, `redact.py` | superseded by Runtime |
| `scripts/setup.py` | becomes the Body half of the one-command installer |
| `docs/examples/revvl-7-debloat` | becomes the first **SOP playbook** (§5) |

## 5. What ZeroClaw gives us that we should lean into

- **SOP engine**: event-triggered Standard Operating Procedures with approval
  gates and resumable runs. The Airframe "capability playbooks" (debloat,
  malware removal, new-phone setup, diagnostics) are SOPs, not markdown the
  model hopefully follows. "Grandma's phone has a popup" → SOP: screencap →
  identify foreground package → confirm sideloaded → snapshot → approval →
  disable → appops deny → remember. **Shipped (M5):** the four live in
  `body/sops/` with the reads as Body tools (`device_foreground`,
  `device_suspects`, `device_debloat_plan`, `device_health`) and one
  confirmation gate each, right before the step that acts.
- **Security policy**: supervised autonomy by default, risk profiles, allow/deny
  lists per tool, cryptographic tool receipts on every action. Body tools plug
  straight into this.
- **Hardware `Peripheral` trait**: GPIO / I2C / SPI / USB on Pi, STM32, ESP32.
  Bodies are not only phones.
- **Voice**: `voice.rs`, `voice_call.rs`, `voice_wake.rs` channels exist. The
  HeyCyan glasses plan (agent-design §14.1) lands on these instead of a bespoke
  path.
- **Gateway + dashboard**: chat, memory browser, config editor, cron, tool
  inspection, ACP for IDEs. The UI we redo (§7) rather than build.
- **WASM plugin host** with a stable ABI we deliberately kept (`zeroclaw:plugin`),
  so the upstream plugin ecosystem works unchanged.
- **Relay (`caelrelay`)**: NAT traversal for bodies behind carrier networks.

## 6. Borrow list from OpenClaw

OpenClaw (2026.10.4) is the reference for product polish. What to port, by
priority, and where it lands in Caelza:

**P0 — do first**

| OpenClaw | Caelza equivalent |
|---|---|
| **Nodes / device-pair**: phones and laptops pair to the gateway with a code and advertise capabilities (camera, screen, location, canvas, voice) | the Body pairing model. QR/code pairing from the dashboard; a Body advertises its tool set; fleet view |
| **Memory plugin slot** (one active memory plugin; `memory-core`, `memory-lancedb`, `active-memory`) | the `XanimaMemory` backend as the one Mind; same "exactly one memory backend" rule |
| **`doctor --fix`** config migrations | adopt the contract: every config shape change ships a migration; `caelza doctor --fix` |
| **Code Mode (QuickJS)**: the model writes a short script that calls tools instead of one tool call per turn | big win on a phone's token budget and latency; upstream has `tool_search` deferred loading, Code Mode is the next step |
| **web-readability / web-search / web-fetch** | Airframe's Firecrawl tools already do this; keep them until the Runtime's browser tool matches |
| **talk-voice / voice-call / tts-local / sherpa-onnx** | map onto the Runtime's voice channels for the glasses |

**P1 — next**

| OpenClaw | Caelza equivalent |
|---|---|
| **Canvas**: the agent renders a live UI on a device | a Body surface: the phone screen as the agent's canvas (screencap/ui_dump are the read side; canvas is the write side) |
| **Session share / session cards** | shareable transcripts from the dashboard |
| **Workboard** | a task board the agent and owner both edit; backs long-running SOPs |
| **Skills via ClawHub** (publish first, bundle rarely) | Caelza skill bundles; xanima's skill-evolution output feeds it |
| **autoreview** | review-before-commit for Body self-modifications |
| **geolocation**, **camsnap**, **peekaboo** (camera/screen skills) | already Body tools; borrow the UX (one-tap in dashboard) |
| **diagnostics-otel / prometheus** | upstream has prometheus; add OTel export |
| **llm-task** (structured sub-task to a cheaper model) | map onto Runtime subagents with provider routing |

**P2 — later**

| OpenClaw | Caelza equivalent |
|---|---|
| **Native apps** (`apps/android`, `apps/ios`, `apps/macos`) | the Caelza Android app (§3.3): OpenClaw's `apps/android` is the reference for structure (foreground service, node pairing, camera/screen/canvas surfaces); Caelza adds Shizuku for privileged device ops and hosts the Runtime + local model on-device. Promoted from "later" to a milestone (M7) |
| **Onboarding wizard** (`openclaw onboard`, the setup wizard with provider choice and safe defaults) | the Guide-led first run (§3.4): "free local" vs "bring your own key", Shizuku step, approvals explained in plain language |
| **Team gateway** (multi-human sessions, co-author credit) | household/fleet mode: several owners, one Caelza |
| **imessage, whatsapp, signal, matrix…** | upstream Runtime already has most; enable per deployment |
| **ClawHub provenance / vetted publishers** | a plugin registry for Caelza skill bundles |

Not borrowing: cloud sandbox providers, hosted services, the TypeScript
plugin API itself.

## 7. UI redesign

### Principles

1. **Phone-first.** The dashboard is most often opened on the phone that *is*
   the agent, over Tailscale. Every page works at 390 px wide, one hand.
2. **Status before chat.** The home screen answers "is it alive, is it
   remembering, what did it do while I was away" before showing a composer.
3. **Bodies are first-class.** Devices, sensors and paired phones are a top-level
   section, not a settings page.
4. **It is an Enlightened Republic product.** The Build Lab system
   (`enlightenedrepublic.tech`) with Caelza's cosmic tint: space-black
   backgrounds with a violet cast, cyan does the work, purple marks the brand,
   Inter Tight + JetBrains Mono with mono eyebrows in caps, the mark (the
   constellation Caelum drawn as a bolt) and the Orbitron wordmark in the
   cyan→purple gradient, and the nebula/dot-matrix backdrop on hero surfaces
   only. One glowing element per view; the gradient is a flourish.
5. **Keep the stack.** React 19 + Vite + Tailwind 4, the upstream dashboard's
   component library and theme system. Redesign is tokens, IA and new pages,
   not a rewrite.

### Information architecture

```
Home        Runtime · Mind · Body status, last 24h digest (from the Mind), pending approvals
Chat        sessions; model picker; approvals inline
Bodies      paired devices, live sensors, screen/camera, package snapshots, pair-a-device
Memory      brain stats, recall preview, graph browse, review queue (xanima control-ui, ported)
Procedures  SOPs: library, runs, approvals, resumable state
Automations cron + heartbeats
Skills      skill bundles, MCP servers, plugins
Settings    providers, channels, security policy, appearance
```

### Phases

| Phase | Scope | Status |
|---|---|---|
| 0 | Enlightened Republic palette as the dashboard default (`caelza-dark` / `caelza-light` registered in `themes.json` and set as defaults); mark, banner, favicons, Tauri icons; Inter Tight as the UI face | **done by the pipeline** (`theme-map.txt`, `lib/dashboard_theme.py`, `brand/`) |
| 1 | Accent picker labels; sidebar lockup (Orbitron wordmark in the drawer) with the parent attribution in both footers; Inter Tight / JetBrains Mono / Orbitron self-hosted from `brand/fonts` and Inter Tight as the default UI face; pairing (login) screen with the "ENLIGHTENED REPUBLIC™ PRESENTS" lockup; **installable as a PWA** (manifest, icons, offline app shell via a service worker the gateway lets claim the SPA root) | **shipped** (`runtime/overlay/web/`, `runtime/patches/0002-ui-phase1.patch`, `brand/make_assets.py`) |
| 2 | **Memory** page: the Mind at a glance (brains, beliefs, sleep, attention), recall by query with forget, the review queue (quarantine / soul imports) with accept and reject; all through the gateway's `/api/mind/*`, which holds the brain tokens. **Bodies** page: this phone and the paired phones with reachability, battery / whereabouts / notifications, screen and camera captures, the package list, pair and unpair a phone; all through the gateway's `/api/bodies/*`, which owns the connection to the Body's MCP server | **shipped**: Memory (`runtime/overlay/web/src/pages/Memory.tsx`, `runtime/overlay/crates/caelza-gateway/src/api_mind.rs`, `runtime/patches/0003-mind-page.patch`) and Bodies (`runtime/overlay/web/src/pages/Bodies.tsx`, `runtime/overlay/crates/caelza-gateway/src/api_bodies.rs`, `runtime/patches/0004-bodies-page.patch`) |
| 3 | **Home** as status before chat: Runtime · Mind · Body tiles, what waits on the owner (procedure runs at a gate, memory changes awaiting review), what happened while they were away (the Mind's attention, last sleep, commitments and open questions over `/api/mind/digest`; the Runtime's runs and sessions of the last day); the upstream dashboard keeps its tabs at `/dashboard`. **Procedures** as the front door to the SOP engine: waiting, running, the library, finished. Then the **phone-first pass** across every page | **shipped**: 3a, Home (`runtime/overlay/web/src/pages/Home.tsx`) and Procedures (`Procedures.tsx`) with `ApprovalQueue.tsx` shared, the digest route in `api_mind.rs`, `runtime/patches/0005-home-procedures.patch`; 3b, the phone-first pass measured at 390 × 844 with `runtime/tools/phone-shots` over every route: phone rules in `caelza-brand.css` (16 px gutters, tables scroll inside their card, 36 px controls on touch screens) and `runtime/patches/0006-phone-first.patch` (header actions wrap, globe-only language button, chat toolbar wraps, Runs padding and titles, no font CDN); reference screens in `docs/design/screens/390/` |

Brand tokens: `brand/tokens.css` / `tokens.json`; guide: `brand/BRAND.md`.

## 8. Brainstorm — the badass list

Grouped, unranked inside each group. ★ = cheap given what we already have.

**Embodiment**
- ★ Fleet: many bodies, one mind. Named device groups, bulk SOP runs ("update all the family phones"). **Shipped (M6):** `caelza-body serve --http` + `fleet join`, groups, the Run dialog's "every phone in family".
- Glasses as a body: wake word on the BT mic, photo trigger over BLE, TTS back (agent-design §14.1), on the Runtime's voice channels.
- GPIO bodies: a Pi with a relay board is a body; same tool shape (`body__gpio_set`).
- Car: OBD-II dongle over BT as a sensor body. Trip log into memory; "why did the check-engine light come on" with the codes already recalled.
- Home: the phone's own sensors as a presence detector (Wi-Fi scan, motion, mic level) feeding SOPs.

**Autonomy**
- ★ Playbooks as SOPs: debloat, malware removal, new-phone setup, diagnostics (agent-design §14.2) with approval gates.
- Proactive monitor from the Mind: xanima already scores importance and has a "proactive monitor"; surface "things you probably want to know" at a scheduled check-in, not as spam.
- ★ Forge (§3.5): the agent ships PRs to its own engine. **Shipped (M6):** `forge-propose` and `forge-release`, `runtime/caelza.forge.example.toml`, the release built with `channel-git`.
- Offline-first SOPs: scripted device actions that run with no model (the Airframe offline mode, formalised).

**Memory**
- Shared brain across bodies; private per agent (service already does it).
- Dreaming visible: a "what I consolidated last night" card on Home.
- Skill evolution → skill bundles: recurring patterns become procedures the agent can run without the model (xanima `skillEvolution`).
- Memory review as spaced repetition for the *owner*: "you told me X in March, still true?"

**Safety**
- ★ Tool receipts + Body audit log + package snapshots: one timeline per device, exportable.
- Verifiable Intent (upstream module): sign the intent of an SOP run; a paired phone can refuse an unsigned command.
- Two-person rule for destructive fleet ops.
- "Prove you're you" for the owner: the voice-biometric gate was dropped in Airframe; revisit as an approval factor, not a login.

**Developer**
- ★ Evals (upstream `caelza-eval` crate): regression suite for Body SOPs against an emulator.
- One-command installer that reads `bundle/manifest.toml`.
- `caelza doctor --fix` with Body checks (termux-api perms, self-ADB pairing, battery whitelist).
- Nightly upstream pin bump PR with the residual check as the gate.

**Product**
- ★ QR pairing of a new body from the dashboard.
- Dashboard "Body" live view: camera, screen, location, battery, notifications.
- Caelza relay (`caelrelay`) hosted by us as an optional service for bodies on carrier NAT.
- The Caelza Android app with Shizuku (§3.3) and the web app as a PWA.
- **Free by default**: DeepSeek R1 local, no key, no account (§3.4); "bring your own" for everything else.
- **Cael** (he/him): the local model as an always-available explainer (what is an API key, what did that approval mean, how do I pair a phone), warm and plain, offline. The same Cael who greets visitors on `enlightenedrepublic.tech`; persona in `guide/CAEL.md`.
- Model picker that shows the honest ladder: what runs on *this* device, what it is good for, and when to bring a cloud model.
- One-tap "explain this screen" anywhere in the app, answered by the Guide. *(Shipped: M8c, Cael in the top bar.)*

## 9. Roadmap

| Milestone | Deliverable | Depends on |
|---|---|---|
| **M0 Rebrand** | this PR: Caelza identity, `runtime/` pipeline producing a `caelza` binary from the pin, brand assets, Mind wiring docs, this doc | — |
| **M1 Runtime on the phone** | **Shipped:** the install path and the config. `runtime/termux-install.sh` puts the release's `aarch64-linux-android` build in `$PREFIX/bin` with the dashboard where the gateway finds it (optional Termux:Boot script); `runtime/caelza.phone.example.toml` is the phone config (Telegram alias + peer group through the Runtime, Mind path A, Body MCP, a `phone` risk profile), validated against the binary; `./runtime/build.sh --target aarch64-linux-android` does the NDK cross-build the release workflow runs (verified 2026-10-19 with NDK r27c: 14 min, a 34 MB aarch64 PIE linked against Bionic, only libc/libm/libdl); a release build carries the tag's version in its crates (`runtime/lib/stamp_version.py`, from `CAELZA_BUILD_ID`), so `caelza --version` answers what both installers probe for. **Open:** first run on the REVVL beside Niba. | a `v*` tag for the first release asset |
| **M2 Body as MCP** | **Shipped:** `caelza-body` stdio MCP server (`caelza_body/mcp_server.py`) exposing the 35 sensors/device/shell/web/selfmod tools with the Airframe safety semantics, every tool classified read-only / destructive / neutral, images returned as MCP image content; the Runtime wiring + risk profile (`body/caelza-body.example.toml`). **Open:** the Python loop retired per phone once the Runtime runs there | M1 for the retirement |
| **M3 Mind native** | **Shipped:** `XanimaMemory`, a native `Memory` backend in the Runtime over `xanima-server`'s MCP Streamable HTTP (`runtime/overlay/.../xanima.rs` + `runtime/patches/0001-xanima-memory-backend.patch`: `[memory] backend = "xanima"`, `[storage.xanima.<alias>]` with one token per agent, dashboard picker entry). Per-turn recall → `brain_query`, auto-saved turns → `brain_episode_append`, facts → `brain_write`, forget → `brain_forget`; unit-tested against a canned service and smoke-tested against a live `xanima-server` 0.5.0. Noise filtering is the service's own (`brain_episode_append` drops heartbeat/cron/`NO_REPLY` turns). **Shipped (the standing context and provisioning):** the brain's `brain_turn_context` (identity, active goals, the goals note, the current task) opens the `[Memory context]` block on every turn through a `turn_context_for_agent` hook on the `Memory` trait that the wrappers forward (`runtime/patches/0008-mind-turn-context.patch`), re-rendered each turn and never stored in history so it outlives compaction, its notes acked on the next assistant auto-save; an agent with no token file gets a brain and a token through `brain_provision_agent` with a provision-scoped token (`provision_token_file`), so a new `[agents.<alias>]` needs no manual mint. **Shipped (the Mind from the release):** every `v*` release carries `xanima-server` built, as `caelza-mind-<version>.tgz` beside the Runtime tarballs and the APK (`mind/pack.sh` fetches the commit `bundle/manifest.toml` pins as `service_commit`, 0.7.0, builds it and `npm pack`s the server workspace; release.yml's `mind` job, which never holds the Runtime's release back), and `mind/install.sh` installs it on a hub or in Termux: the asset looked up and checksummed the way the Runtime's is, `npm install --omit=dev` under `~/.local/share/caelza/mind` (the two native sqlite modules prebuilt for Linux x86_64 and aarch64, built on Termux), a `caelza-mind` launcher, and with `CAELZA_SERVICE=1` the Termux:Boot script or the systemd user unit that starts it after a reboot; so a hub gets its Mind with one line, no checkout and no build. **Bug check (the Mind's scripts, a fresh agent):** a release with no `.sha256` beside the tarball installed it unverified with a note (refused now, `CAELZA_SKIP_CHECKSUM=1` to override); the launcher baked in the node path the install saw (it looks on PATH first) and used `/usr/bin/env` on Termux (Termux's own `sh`); the systemd unit's `ExecStart` was unquoted; `jq` in the next steps was never installed; the manifest's schema and tool count were 0.5.0's. (The last-24h digest shipped with Home, M4 phase 3a: `/api/mind/digest` in `api_mind.rs`.) **Open:** the shared brain across bodies (one service, many Runtimes: `brain_room`, `brain_publish`, `brain_subscribe`); `xanima-server` on npm itself, should upstream publish it, which would make `npm i -g` the install. | xanima rename shipped |
| **M1.5 Free local default** | **Shipped:** `scripts/model-setup.sh` + `scripts/model_ladder.py` (RAM × platform → agent and guide tiers, tested): installs llama.cpp (Termux package) or expects Ollama, fetches the DeepSeek R1 GGUFs against pinned sha256s or pulls the Ollama tags, writes the `llamacpp.*` / `ollama.*` provider aliases, points `agents.main` at the local model when it has none, creates Cael (`agents.cael`, profile `guide`: `readonly` + `deny_all_tools`) with `guide/cael.system.md` as his SOUL.md; `runtime/caelza.local-model.example.toml` is the readable wiring. **Shipped (the two doors):** the dashboard's quickstart opens on the two doors (`runtime/overlay/web/src/pages/quickstart/Doors.tsx` + `runtime/patches/0007-quickstart-doors.patch`): free and local stages the ladder's DeepSeek R1 for this device as `<runner>.local` with Cael's honest line, bring your own key is upstream's provider form; the ladder in the overlay is pinned to `scripts/model_ladder.py`. **Shipped (Cael's corpus):** `scripts/cael_corpus.py` chunks the owner-facing pages of the Runtime's book, the README, the Mind and Body READMEs and `guide/FAQ.md` into `guide/corpus.jsonl` (kept current by CI against the staged book) and loads them into Cael's memory through the gateway's `/api/memory`, where the Runtime's per-turn recall finds them; the app loads its bundled copy itself. `knowledge_bundles` stays schema-only at the pin, so memory is the corpus path. **M1.5 is complete.** | M1 for the phone run |
| **M4 UI phases 1–2** | **Phase 1 + PWA shipped:** the brand faces self-hosted (Inter Tight default, Orbitron wordmark), the lockup in the drawer and on the pairing screen, the parent attribution in the footers, labelled accents; `manifest.webmanifest` + icons + `sw.js` (offline app shell, API never cached) with the gateway's `Service-Worker-Allowed` for the SPA root. **Phase 2a shipped:** the Memory page (`/memory`, in the sidebar's Home group): brains, beliefs, sleep and attention from `brain_stats` / `brain_status`, recall by query with forget, the review queue with accept / reject; the gateway's `/api/mind/*` proxies the brain service with the host-side tokens. **Phase 2b shipped:** the Bodies page (`/bodies`, beside Memory): this phone and the paired phones from `device_list`, battery / whereabouts / notifications from the sensors tools, screen and camera captures as images, the package list, pair and unpair over ADB wireless debugging; the gateway's `/api/bodies/*` keeps one connection to the Body's MCP server (`caelza-body serve`) and makes the tool calls. **Phase 3a shipped:** Home (`/`) as status before chat: Runtime, Mind and Body tiles, "waiting on you" (procedure runs at a gate with approve / deny, memory changes awaiting review), "since you were away" (the Mind's attention, last sleep, open commitments and questions through `/api/mind/digest`; runs and sessions of the last day); the upstream dashboard at `/dashboard` with the old `/?tab=` links forwarded. Procedures (`/procedures`) fronting the SOP engine: waiting, running with stop, the library, finished this week. **Phase 3b shipped:** the phone-first pass, measured at 390 × 844 over every route with `runtime/tools/phone-shots` (sideways scroll, elements past the edge, controls under 32 px): phone rules in the brand stylesheet, patch 0006 for what CSS cannot reach, reference screens in `docs/design/screens/390/`. **Phase 4a shipped:** the simplified setup (`/setup`, `runtime/overlay/web/src/pages/setup/` + patch 0009): Cael's screens in the brand's own colours, one decision each, outside the dashboard chrome. The two doors first; behind "bring your own key" a scroll wheel of the providers most people bring (`bundle/models.json`, the curated catalog `scripts/model_catalog.py check --online` verifies against models.dev; "more" adds every key provider the Runtime lists), a wheel of that provider's models with Cael's picks pinned on top (best, fast and cheap, strongest, free) above the Runtime's live catalog, one box for the key with where to get one, then "Try it"; behind "free and local" the ladder's pick for this device. Risk, runtime, memory and the agent's name take defaults and the whole thing goes through upstream's `/api/quickstart/apply`, so the result is what the full wizard writes; a fresh install lands on `/setup`, the wizard stays at `/quickstart` as "Advanced setup", and "Set up" heads the sidebar's Configure group. The Android app's first run spins the same catalog with two native wheels (`firstrun/ModelCatalog.kt`). **Phase 4b shipped:** the brand pass over every dashboard page (`caelza-brand.css` + patch 0010): the mark and the wordmark in the top bar on every width under a hairline of the mark gradient, page titles in the mark gradient, the primary action filled cyan → violet (the pairing screen's too), Space with the nebula glows behind every page (theme variables, so another theme gets a plain base), cards with a hairline of light on their top edge; the reference screens in `docs/design/screens/390/` retaken. **Bug check (a fresh agent over phases 4a and 4b, the real ones fixed):** a second setup for a provider failed on "alias already exists" with no way past it (the next free alias, `default2`, `local2`, is taken, as the agent's name already was); the live model list arriving after the owner had spun the wheel reset it to the pick (the list now only adds rows under the choice); a key pasted for one provider rode along to the next (cleared); a provider the Runtime lists nothing for said "asking" forever (it goes to the typed box); Enter on the key box did nothing (it does what the button does); Cael's bubble was dark glass in Caelza Light and the page titles started from a cyan that is 1.4:1 on the light base (the bubble takes the theme's surface, the gradient is a theme variable; the setup page, Space in every theme, pins the dark palette's text and surfaces for its subtree, since under Caelza Light its text went near-black on Space); at 390 px the top bar could not shrink and the palette button drew over the wordmark (the wordmark yields below 460 px); the glows were `background-attachment: fixed`, which iOS Safari ignores (a fixed layer of their own); the muted grey on the setup page's text buttons was under AA (secondary now); the catalog checker crashed on an entry that was not an object. **Shipped (the local door on a PC):** "free and local" goes all the way on a computer: the setup page asks the computer's own Ollama what it has (`runtime/overlay/web/src/pages/setup/ollama.logic.ts`: `/api/tags` and a streamed `/api/pull` straight from the browser, which Ollama's default CORS allows for localhost origins; only a page open on the computer itself probes), shows a **Get Ollama** link and **Check again** when nothing answers at `127.0.0.1:11434`, and when the ladder's pick (or Cael's 1.5B) is not pulled yet the primary button becomes **Download N GB and use this**: each model pulls with its own bar (Ollama's status lines as five words, the GB done of the total), the download can be stopped and resumes, then the same apply as "Use this". A page open from another device gets the `ollama pull` line instead. **M4 is complete.** | M2, M3 |
| **M5 SOP playbooks** | **Shipped:** the four playbooks as SOPs in `body/sops/` (`phone-debloat`, `phone-malware-removal`, `phone-new-setup`, `phone-diagnostics`): manual trigger, owned by `agents.main`, `auto` mode with one `requires_confirmation` gate per procedure right before the step that changes the phone (diagnostics has none); the deterministic half as four read-only Body tools (`device_debloat_plan` over a curated list seeded from the REVVL 7 log, `device_suspects` with risk flags, `device_foreground`, `device_health` with the setup checklist); `caelza-body playbooks --install` and `install.sh` put them in `~/.caelza/shared/sops`, `[sop] sops_dir` in the phone config loads them, the Procedures library gives each a **Run** that asks which phone; validated by the Runtime's own `caelza sop validate`. Evals: `tests/test_playbook_evals.py` runs the classifier over the 297-package REVVL snapshot and the parsers over recorded output, and against a live emulator or phone with `CAELZA_EVAL_SERIAL`. **Open:** a recorded run of each playbook end to end on the REVVL (the first device run, M1), the eval crate (`caelza-eval`) replaying those runs. | M2 |
| **M6 Fleet + Forge** | **Shipped (fleet):** the hub + bodies shape. Each phone serves its Body over Streamable HTTP behind a bearer token (`caelza-body serve --http`, loopback unless `--host` names the Tailscale address, `/health` open, `/mcp` locked, DNS-rebinding checks); the hub's Body joins phones as devices (`device_join` / `caelza-body fleet join`, the token in a 0600 file, never in the registry) and forwards every tool call naming one, sensors included, images included, with an audit line per destructive call; `device_list` shows kinds and groups, `device_pair` / `device_tag` set groups, the Procedures Run dialog fans a playbook out over a group with one gate per phone; `runtime/caelza.hub.example.toml` is the hub's Runtime config. Tested end to end against a real `--http` Body with the recorded phone (`tests/test_fleet.py`). **Shipped (Runtime guard):** `caelza_body/runtime_guard.py` (stdlib, immutable like the supervisor): `caelza-body runtime update` finds the release for this target, downloads and verifies the archive against its `.sha256`, unpacks into `~/.caelza-body/runtime/<version>` (refusing escaping members), probes the binary in the work dir on a copy of the config (`--version` must match, `gateway start` must serve `/health` on a port nothing else answers), snapshots `~/.caelza` (config, agents, shared), moves `current` and leaves `last-good` on the version that was running, asks the supervisor to restart; a binary that does not hold is never installed. The supervisor runs `caelza daemon` from `current` beside the agent, restarts on request (which also revives a halted Runtime), promotes the new version to `last-good` once it has held for ten minutes, rolls back to `last-good` on a crash loop, halts without a rollback when another Runtime already holds the gateway port, and halts when last-good loops. `runtime status / rollback / link` by hand; `tests/test_runtime_guard.py` drives it with a fake release and a fake gateway, and the real binary when `CAELZA_BIN` is set. **Shipped (Forge):** the git channel as `channels.git.forge` (a GitHub App on the repo; `runtime/caelza.forge.example.toml` with the events table and the gates), every release built with `channel-git`, `forge-propose` (frame, read `main`, draft; after the gate a `forge/<topic>` branch and a draft PR through `git_forge`) and `forge-release` (on `release.published`, or a tag by hand: the owner approves, `body__runtime_update` hands the tag to the guard), the Body's `runtime` tool group (`runtime_status`, `runtime_update`); validated by the Runtime's `sop validate` with the channel configured; `docs/forge.md`. **M6 is complete.** **Open:** the first live forge PR from a phone (the App installed on the repo, a `v*` release with the Android leg). | M2–M5 |
| **M8 Looks and the Shop** | **Shipped (M8a, the looks):** every agent has a pixel character: one piece per layer (backdrop, body, outfit, hair, hat, face, accessory) in the owner's colours (skin, hair, outfit, accent, eyes), drawn as code on a 40 × 44 grid in `looks/parts.py` in a key palette, exported by `scripts/looks.py` to the dashboard's public files and composed, outlined and recoloured in the browser (`runtime/overlay/web/src/looks/Look.tsx`, the maths mirrored in `looks.logic.ts` and pinned to the Python by `tests/test_looks.py`). It blinks on its own and talks in the chat header while the agent answers. Cael's look is fixed (the constellation hoodie, galaxy eyes, violet hair on Space); every other agent is dealt one from its name until the owner dresses it at `/looks/<alias>` (a tab per layer, the pieces of the packs in the wardrobe, a colour row per slot, save). The look lives on the Runtime (`api_looks.rs`: `/api/looks/{alias}` under `agents/<alias>/look.json`), so the phone and the desktop show the same. **Shipped (M8b, the shop):** `/shop` lists the packs of `looks/catalog.json` with their sheets: Starter (always yours), Cosmic (free, one tap adds it to the wardrobe at `/api/looks/wardrobe`), Arcade (coming soon); a priced pack carries an `unlock` slot for signed codes once the gateway verifies them. Adding a pack is drawing its pieces in `parts.py`, listing them in the catalog and running `export`; `check` keeps the catalog, the drawings and the exports in step. **Shipped (M8c, Cael everywhere):** his look in the top bar of every page opens "explain this screen" (`runtime/overlay/web/src/guide/CaelButton.tsx` + patch 0012): one paragraph and one next step per screen in his words, with no model needed; below it a question, answered by the `cael` agent over the gateway's chat socket in one guide conversation the browser keeps (his look talks while he answers; whole, the answer renders as markdown in the chat's styles, M8f); without Cael set up, the panel still explains and points at the setup. **Shipped (M8d, the look in the conversation):** the agent's look stands beside each of its bubbles and on its chat tab, held still (the transcript does not fidget); the live turn's look talks while the answer streams in; Home has "Your agents" (each agent's look, the ones talked to last first with when and how much, a tap opens the chat, a link to dress them) and the look beside each conversation that moved; one composed frame per look and frame is shared by every copy on the page (patch 0013 for the chat and the tab bar, the overlay's Home for the rest). **Shipped (M8e, the Arcade pack and the unlock codes):** the first priced pack, drawn (a CRT backdrop with the invaders on it, a bomber jacket, a mohawk, a backwards cap, sprite eyes, shades, a coin beside the head), opens with a code the owner mints (`scripts/unlock_codes.py`: Ed25519 in plain Python, `<PACK>-<ID>-<signature>`, the signing key kept out of the repo) and the Runtime checks against the public key baked into the gateway (`api_looks.rs`, through rustls' ring provider, so no new crate; the catalog carries the same key) at `POST /api/looks/wardrobe/unlock`; the wardrobe remembers the unlock, so the pack goes back in with one tap after a remove; the Shop's slot takes the code and says what is wrong with one that is not. **Bug check (a fresh agent over M8a–f, the real ones fixed):** the browser drew no outline on a look with a backdrop (the outline is computed from the silhouette mask now, over the backdrop and under the face, as parts.py does); a top-bar re-render mid-answer disconnected Cael's stream (the panel's teardown runs once, Escape reads the closer through a ref, focus lands in the ask box once he is there); a part PNG that failed to load poisoned the look cache (forgotten and retried); the wardrobe's writes under one lock with a temp file per write, a wardrobe file that is not one refused rather than emptied; the CLI refuses a non-canonical code the Runtime refuses; a wardrobe that fails to load stays unknown (the Shop offers a retry, the customizer does not lock anything) instead of an empty stand-in the next tap would save; `looks.py check` refuses a pack id with a hyphen; "60 min ago" is "1 h ago". **Shipped (M8g, the avatar):** "Save as avatar" on the customizer downloads the look as a 512 px PNG (the closed frame at the largest whole scale that fits, the edges continued into the margins, Space behind a look with no backdrop) for Telegram, Discord or anywhere a profile picture goes; `scripts/looks.py avatar` writes the same file from a saved `look.json`, the two geometries pinned to each other. **Shipped (Cael knows it):** the FAQ, and so his corpus, carries the looks, the customizer, the Shop and its packs, the unlock codes, the avatar and his own panel in the owner's words. **Open:** a storefront link per pack (`buy` in the catalog) once there is one. | M4 |
| **M7 Caelza Android app** | **Shipped (M7a, the shell):** `android/`, a Gradle/Kotlin app (`tech.enlightenedrepublic.caelza`, minSdk 28, targetSdk 28 on purpose: W^X, see `docs/design/android-app.md` §2) that installs the Runtime from this repo's releases through the guard's pipeline in Kotlin (`ReleaseInstaller`: the `aarch64-linux-android` archive, its `.sha256`, unpack, probe on a copy of the config, install, `current` / `last-good` as the Body's guard keeps them), runs `caelza daemon` as a foreground service with the supervisor's ladder (`RuntimeService`: restart, roll back to last-good on a crash loop, halt when last-good loops or another Runtime holds the port), starts it after a reboot, shows the dashboard in a WebView the moment `/health` answers, and reads where Shizuku stands; JVM unit tests over a fake release; CI builds the APK (`.github/workflows/android.yml`). **Shipped (M7b, the Body):** the `device` group in Kotlin over Shizuku (`android/.../body/`), served to the Runtime as the Body MCP server on `127.0.0.1:42618/mcp` the way `caelza-body serve --http` serves it (the same token file, audit log and package snapshots under `files/.caelza-body`), the Runtime's config wired on first start (`body` http server, bundle, `[agents.main]`, the `phone` risk profile), the playbook parsers and tables ported with their recordings replayed in Gradle, the contract pinned from both sides against `caelza-body list-tools` (`scripts/android_body_fixtures.py`); Shizuku missing is a degraded Body (`needs Shizuku`), not a crash. **Shipped (M7c, the sensors):** the nine `sensors_*` tools through the Android APIs (`AndroidSensors`: `BatteryManager`, a `NotificationListenerService`, `ClipboardManager`, `LocationManager` + `WifiManager` + the keyless IP lookup, camera2 with a settling preview, `MediaRecorder`, `TextToSpeech`, the torch) answering in `termux-api`'s shapes so the tools, the playbooks and the Bodies page see no difference; a permission not granted is `needs the camera permission: Settings › …`, and the strip's third line asks for what is missing. **Shipped (M7d, the first run and the local model):** Cael leads the first run (`firstrun/`): the Runtime installed, a brain through the two doors of §3.4 (free and local: llama.cpp's own prebuilt Android build pinned by tag and sha256 plus the ladder's GGUF for this phone's RAM, verified and resumable, `llama-server` on `127.0.0.1:8080` run beside the Runtime by the service; bring your own key: Anthropic, OpenAI or OpenRouter under `<provider>.default`), Shizuku, the permissions with their reasons, the battery exemption, a word about hubs, start; both doors write the config through the Runtime's own `caelza config set` and create Cael as `agents.cael` with his `SOUL.md`. **Shipped (the launcher icon):** the brand mark as an adaptive icon, rendered by `brand/make_assets.py --android` from `tokens.json` (the mark inside the safe circle over the nebula backdrop; the silhouette as the monochrome layer for themed icons and the notification's status-bar icon) and kept in step by CI. **Shipped (the release's Android leg):** a `v*` tag builds the app as well and attaches `caelza-app-<version>.apk` with its `.sha256` to the release, versioned from the tag (`scripts/app_version.py`: `v0.1.0` → `0.1.0` / versionCode 1000, `BUILD_ID` in the bug report), signed with the release keystore when the repo's secrets hold one and `-debug-signed` otherwise; the logs screen (`logs/LogsActivity.kt`) shows every log the app writes with secrets blanked and shares a bug report. **Bug check (a fresh agent over the Kotlin, the real ones fixed):** the Body server read a request's body (up to 16 MiB) before it looked at the token, with no cap on connections (a request that cannot pass is refused before a byte of its body is read; eight connections at a time, the ninth told so); the shell handed its token to any page whose path ended in `/health` and followed any link inside the WebView (the token goes only to the gateway's own origin, scheme, host and port all three, and every other link opens in the browser); a `caelza` that hung held the service forever (its output is drained beside a deadline, `Processes.run`, the installer's probe the same way); a model download whose `.part` was already whole asked for byte N of N and wedged on the 416 (the whole part is hashed and moved, or thrown away and fetched again); the Body's wiring went into the config before the server had bound its port; a supervisor error outside the ladder died silently (it halts with the message); a JSON-quoted key (`"api_key": "…"`) and the gateway's boxed pairing code slipped through the bug report's scrubber; the corpus loader was launched twice on a restart. **The first phone run (the owner's REVVL 7 5G, v0.1.0):** the free door never finished its download. The cause was in the repo, reproduced with two HEAD requests: the ladder's byte pins were 64 (1.5B) and 320 (7B) bytes short of Hugging Face's files while the hash pins were right, so the Termux installer (hash only) worked and the app (hash and size) downloaded the whole gigabyte, threw it away as "short", and did it five times. The pins are corrected from the files' own headers and `scripts/model_ladder.py --check-online` compares every pin with Hugging Face's `x-linked-size` and `x-linked-etag` (the Kotlin ladder and the fixture are pinned to the Python numbers); the store now refuses a server size that disagrees with the pin before the first byte, and a longer-than-pinned download as a stale pin rather than a retry; the first run keeps the screen on while it downloads and writes the local door's lines and failures to `install.log`, so the Logs screen's bug report says what happened. **Open:** the first real `llama-server` start on the REVVL (memory on a 3.5 GB phone); the accessibility service and MediaProjection for this phone's screen without Shizuku; the fleet tools in the app; the binder path instead of shell commands; the W^X decision measured on the REVVL. | M2, M1.5, M4 |

## 10. Decisions (taken 2026-10-18) and what is still open

| # | Question | Decision |
|---|---|---|
| 1 | xanima naming | **Shipped** (2026-10-18/19): both repos' `main` carry the rename, and `xanima-openclaw`, `xanima-core` and `xanima` 0.5.0 are on npm with the plugin on ClawHub as `xanima`. Plugin id `xanima` (legacy id `openwave` honoured), service `xanima-server` (private, runs from a checkout), brains in `~/.xanima`, env `XANIMA_BRAIN_TOKEN`, an upgrade CLI. |
| 2 | Repo rename | **Rename `airframe-lite` → `caelza` now** (GitHub Settings, redirects keep old links). Every URL in this repo already assumes it. |
| 3 | Body package | **`caelza_body`**, state in `~/.caelza-body`, env `CAELZA_BODY_HOME`. The reference agent persona stays "Niba". The legacy `~/.niba` / `NIBA_HOME` are honoured until `python scripts/setup.py --migrate` runs on the phone. |
| 4 | Licence | **MIT** for this repo (Body, pipeline, brand, docs). Runtime stays MIT OR Apache-2.0 from upstream; fonts OFL. |
| 5 | Public URLs | Pointed at `enlightenedrepublic.tech` and the GitHub repo in `runtime/rename-map.txt`; swap in a product domain if one appears. |
| 6 | Dashboard bundle | **GitHub Actions builds it on release** (`.github/workflows/release.yml`: `cargo web build` with Node 24, shipped in each tarball). Nothing generated is committed. |
| 7 | Privilege path | **Termux + loopback ADB is primary** for the current test device. Shizuku is an *optional permission*, the way the Runtime's risk profiles grant capabilities: `body.privilege = "adb" \| "shizuku"`. Both ship as one-line installs: `install.sh` for Termux now, the app's installer when the app exists. |
| 8 | Local model | **Bundle the 1.5B Guide model; offer 7B/14B as a download** sized to RAM at quickstart; bring-your-own key is the other door. |
| 9 | The Guide | **Cael**, short for Caelza, he/him: one character with the chat on `enlightenedrepublic.tech` (renamed from Marley 2026-10-20), there scoping projects for the lab, here helping you run Caelza; warm, cute and personable on purpose (decided 2026-10-20). Persona and prompt in `guide/CAEL.md`. |
| 10 | The mark | Bolt alone is the default; the leaning C stays opt-in. Still being sat with. |

Still open:

- The `xanima-openclaw` README is rewritten on `main` (PR #12, 2026-10-19) and reaches npm/ClawHub at the next publish. Left there: `package.json` repository URLs still say `openwave`, the plugin manifest's token/server descriptions, and the `brain-docs/*.md` the agent reads through `brain_docs` still describe openwave on sharpwave-core 0.4.2.
- Both upstream repos were renamed on GitHub (`openwave` → `xanima-openclaw`, `sharpwave` → `xanima`); the Markdown links and `bundle/manifest.toml` `repo` / `engine_repo` in this repo now use the new names (2026-10-20); the old ones redirect.
- Whether the Body's `caelza-body-last-good` git tag should replace `niba-last-good` on deployed phones (left as is so the phone's rollback pointer survives the rename).
- A product domain for Caelza, if any.
