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
| **Mind** | autonomic long-term memory: graph + forgetting curve + sleep | xanima (openwave) on sharpwave-core (`mind/`) |
| **Body** | the device: termux-api sensors, ADB control of self and paired phones, the immutable supervisor with git-backed self-modification and rollback | Airframe Lite (`niba/`) |

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
                 │ Memory trait (SharpwaveMemory)             │ MCP (stdio or http)
                 ▼                                           ▼
 ┌──────── Caelza Mind ────────┐                 ┌──────── Caelza Body ────────┐
 │ sharpwave-server            │                 │ caelza-body MCP server      │
 │  shared brain + per-agent   │                 │  sensors_* (camera, mic,    │
 │  brains, tokens, sleep      │                 │   location, notifs, tts…)   │
 │ xanima (OpenClaw gateways)  │                 │  device_* (ADB self+remote, │
 │ sharpwave MCP (IDE agents)  │                 │   snapshots, audit log)     │
 └─────────────────────────────┘                 │  shell_run                  │
                                                 │ supervisor.py (immutable)   │
                                                 │  probe · promote · rollback │
                                                 └─────────────────────────────┘
```

Deployment shapes, all from the same bundle:

1. **Phone-only** (today's Niba): Runtime (`aarch64-linux-android`), Body and
   the sharpwave engine all in Termux on one phone.
2. **Hub + bodies**: Runtime and Mind on a Pi/NUC/VPS; one or more phones run
   only the Body, reached over Tailscale. Fleet management falls out of this.
3. **Dev box**: everything on a laptop with the dashboard; the phone is a
   paired body for testing.

### 3.1 The Body becomes an MCP server

`niba/agent/tools/*` already have the shape of MCP tools (name, JSON schema,
handler) and `mcp` is already a dependency. `caelza-body` wraps them as a stdio
MCP server the Runtime spawns (or an `http` one it reaches over Tailscale).
Dangerous-op semantics stay in the Body: `reason` required, audit log, package
snapshot before any removal. The Runtime's approval policy adds a second gate on
top (`always_ask = ["body__device_uninstall", …]`).

The Python agent loop, model wrapper, Telegram transport and SQLite session go
away once the Runtime owns the turn. The supervisor stays, and now guards the
Body's own code plus the Runtime binary (§3.3).

### 3.2 The Mind

See `mind/README.md`. Short version: tools path now (`sharpwave` MCP), service
path for shared brains (`sharpwave-server`), then a native `SharpwaveMemory`
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
work, privileged device ops report "needs Shizuku"). Termux stays supported as
the headless path for devices without the app.

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

- **Guide**: the in-app helper that explains what an API key is, what a
  provider is, what Shizuku does, why an approval prompt appeared, and walks
  through setup in plain language. This is the "super user friendly" layer:
  a Marley-style assistant inside the product, running free and offline.
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
| Runtime binary | CI, from this repo | last-good binary kept; supervisor swaps and probes (`caelza --version`, gateway health) and rolls back |
| Runtime config, prompts, skills, SOPs | the agent, through its own tools | config validation fails closed; the supervisor snapshots `~/.caelza` before each self-change |
| Body code (`niba/`) | the agent | unchanged: pytest → commit → restart → probe → promote/rollback |
| `supervisor.py` | nobody | deny-listed, as today |

The step after that is **Forge**: the agent proposes Runtime changes as pull
requests to this repo over the git channel (upstream has `channel-git`); CI
builds the binary; the supervisor pulls the release. The agent then improves
its own engine without ever holding the compiler.

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
  disable → appops deny → remember.
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
| **Memory plugin slot** (one active memory plugin; `memory-core`, `memory-lancedb`, `active-memory`) | the `SharpwaveMemory` backend as the one Mind; same "exactly one memory backend" rule |
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
| 1 | Accent picker labels ("Teal", "Purple"…); sidebar lockup with the parent attribution in the footer; load Inter Tight / JetBrains Mono from `brand/fonts`; login screen with the "ENLIGHTENED REPUBLIC™ PRESENTS" lockup | next |
| 2 | **Bodies** page (devices, sensors, pairing) and **Memory** page (port xanima control-ui) | after `caelza-body` MCP + service path |
| 3 | Home as status/digest; Procedures page on the SOP engine; phone-first layout pass across every page | |

Brand tokens: `brand/tokens.css` / `tokens.json`; guide: `brand/BRAND.md`.

## 8. Brainstorm — the badass list

Grouped, unranked inside each group. ★ = cheap given what we already have.

**Embodiment**
- ★ Fleet: many bodies, one mind. Named device groups, bulk SOP runs ("update all the family phones").
- Glasses as a body: wake word on the BT mic, photo trigger over BLE, TTS back (agent-design §14.1), on the Runtime's voice channels.
- GPIO bodies: a Pi with a relay board is a body; same tool shape (`body__gpio_set`).
- Car: OBD-II dongle over BT as a sensor body. Trip log into memory; "why did the check-engine light come on" with the codes already recalled.
- Home: the phone's own sensors as a presence detector (Wi-Fi scan, motion, mic level) feeding SOPs.

**Autonomy**
- ★ Playbooks as SOPs: debloat, malware removal, new-phone setup, diagnostics (agent-design §14.2) with approval gates.
- Proactive monitor from the Mind: xanima already scores importance and has a "proactive monitor"; surface "things you probably want to know" at a scheduled check-in, not as spam.
- Forge (§3.3): the agent ships PRs to its own engine.
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
- **The Guide**: the local model as an always-available explainer (what is an API key, what did that approval mean, how do I pair a phone), in the Republic's voice, offline. Could share a name and prompt lineage with Marley on `enlightenedrepublic.tech`.
- Model picker that shows the honest ladder: what runs on *this* device, what it is good for, and when to bring a cloud model.
- One-tap "explain this screen" anywhere in the app, answered by the Guide.

## 9. Roadmap

| Milestone | Deliverable | Depends on |
|---|---|---|
| **M0 Rebrand** | this PR: Caelza identity, `runtime/` pipeline producing a `caelza` binary from the pin, brand assets, Mind wiring docs, this doc | — |
| **M1 Runtime on the phone** | `caelza` built for `aarch64-linux-android`, running in Termux beside Niba; Telegram via the Runtime; sharpwave MCP (Mind path A) | NDK cross-build |
| **M2 Body as MCP** | `caelza-body` stdio MCP server exposing sensors/device/shell with the Airframe safety semantics; Runtime risk profile for it; Python loop retired | M1 |
| **M3 Mind native** | `SharpwaveMemory` backend in the Runtime over `sharpwave-server`; auto-provisioned per-agent brains; noise filtering ported | xanima rename shipped; service published |
| **M1.5 Free local default** | Quickstart door 1: DeepSeek R1 via Ollama (hub) or llama.cpp (phone) with the size ladder; the Guide persona; "bring your own" as door 2 | M1 |
| **M4 UI phases 1–2** | Caelza themes as default, Bodies page, Memory page; web app installable as a PWA | M2, M3 |
| **M5 SOP playbooks** | debloat / malware / new-phone / diagnostics as SOPs with approvals; evals on an emulator | M2 |
| **M6 Fleet + Forge** | hub + bodies deployment; supervisor guards the Runtime binary; agent-authored PRs | M2–M5 |
| **M7 Caelza Android app** | native companion: Body via Shizuku, foreground service, accessibility + notification access, hosts Runtime + local model, WebView/PWA dashboard, Guide-led first run | M2, M1.5, M4 |

## 10. Open decisions

1. **xanima packaging**: npm name, plugin id and ClawHub slug all `xanima`?
   The Mind docs assume yes (table in `mind/README.md`).
2. **Repo rename**: `airframe-lite` → `caelza` on GitHub (redirects keep old
   links working). Everything in this PR already points at the new name.
3. **Body package name**: keep `niba` as the reference agent (`~/.niba`,
   `NIBA_HOME`, unchanged on the deployed phone) or rename to `caelza_body`?
   This PR keeps `niba` to avoid touching the running device.
4. **Licence for this repo**: Airframe Lite has no LICENSE file ("private while
   early"). The Runtime is MIT OR Apache-2.0 and the Mind is MIT; the Body
   needs a licence before the bundle is public.
5. **Public URLs**: the rename map points docs/site/Discord at the GitHub repo
   for now. Swap in real domains in `runtime/rename-map.txt` when they exist.
6. **Dashboard build**: upstream needs Node 24+ to rebuild `web/dist`; the
   pipeline rebrands the source and assets but does not rebuild the bundle.
   Decide whether release CI builds it or we vendor a built `dist`.
7. **Shizuku as the primary privilege path**: in the Android app, Shizuku
   replaces loopback ADB. Keep the Termux/ADB path as the headless fallback,
   or drop it once the app ships?
8. **Local model ladder**: which DeepSeek R1 sizes to ship as defaults per RAM
   tier, and whether the app downloads weights on first run (1–9 GB) or ships
   only the 1.5B Guide model and offers the rest as a download.
9. **The Guide's name and voice**: reuse Marley (the `.tech` chatbot) inside
   Caelza, or a sibling persona with the same prompt lineage?
