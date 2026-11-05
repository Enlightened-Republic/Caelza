<p align="center">
  <img src="brand/hero.png" alt="Enlightened Republic presents Caelza — the embodied agent runtime" width="100%" />
</p>

<h1 align="center">Caelza</h1>

<p align="center"><strong>The embodied agent runtime.</strong><br/>
An agent that lives on your own hardware, remembers across months, and acts on the devices around it.</p>

<p align="center"><sub><a href="https://www.enlightenedrepublic.tech"><img src="https://enlightenedrepublic.online/assets/er-profile-pic.png" alt="" width="20" align="absmiddle" /></a>&nbsp; Built by <a href="https://www.enlightenedrepublic.tech">Enlightened Republic</a>, the lab behind SharpWave and xanima. · EST. 2026</sub></p>

<p align="center">
  <a href="https://github.com/Enlightened-Republic/Caelza/releases/download/v0.1.0/caelza-app-0.1.0-debug-signed.apk"><img src="https://img.shields.io/badge/%E2%AC%87%EF%B8%8F_Install_the_Android_app-APK_v0.1.0-00d4ff?style=for-the-badge&logo=android&logoColor=white" alt="Install the Android app (APK v0.1.0)" /></a>
</p>

> [!WARNING]
> **This is a testing build.** Caelza is early, unfinished software and is being tested right now. Expect bugs, rough edges and breaking changes. Don't rely on it for anything important, and don't give it access to anything you can't afford to lose. The APK is debug-signed, so it will not upgrade in place to a later release-signed build.

## Try it on your Android phone

1. On your phone, tap the **Install the Android app** button above (or [download the APK](https://github.com/Enlightened-Republic/Caelza/releases/download/v0.1.0/caelza-app-0.1.0-debug-signed.apk)).
2. Open the downloaded file. If Android asks, allow your browser or Files app to **install unknown apps**, then tap **Install**.
3. Open **Caelza** and follow Cael's first-run screens. The app downloads the runtime on first run, so connect to Wi-Fi first.
4. Something broke? Use **Logs** in the app to share a bug report.

### What's coming

Planned, not shipped yet. This build does not have any of it, and the order may change:

- **Your apps, connected.** Gmail, Calendar, Drive, Notion, Slack and more through [Maton](https://maton.ai), with Cael walking you through each sign-in. Reading is free; sending, posting, paying and deleting always ask you first.
- **Smart home.** Lights, locks, cameras and thermostats through Home Assistant.
- **3D printers.** Status, progress and a camera snapshot over Wi-Fi (Moonraker and OctoPrint first, Bambu after), with pause and cancel behind an approval.
- **Updates that arrive by themselves.** Today a new version means installing the new APK over this one by hand. We're working on the app telling you when an update is ready and installing it for you.

Want something else? Open an [issue](https://github.com/Enlightened-Republic/Caelza/issues).

---

Caelza is three layers shipped as one product (`bundle/manifest.toml`):

| Layer | What | Where |
|---|---|---|
| **Runtime** | the engine: agent loop, 20+ model providers, 30+ channels, tools, security policy, SOP engine, cron, gateway + web dashboard, WASM plugins, hardware peripherals. A rebranded build of [ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw), regenerated from a pinned commit. | [`runtime/`](runtime/) |
| **Mind** | autonomic long-term memory: a graph with a real forgetting curve and a sleep system. [xanima](https://github.com/Enlightened-Republic/xanima-openclaw) (formerly openwave) on the [xanima-core](https://github.com/Enlightened-Republic/xanima) engine (formerly sharpwave-core), both on npm at 0.5.0. | [`mind/`](mind/) |
| **Body** | the device layer: camera, mic, location, notifications and TTS through termux-api; ADB control of its own phone and paired phones with audit logging and pre-removal snapshots; an immutable supervisor that probes self-modified builds and rolls back. Served to the Runtime as the `caelza-body` MCP server. | [`caelza_body/`](caelza_body/), [`body/`](body/) |

Read [`docs/design/caelza-vision.md`](docs/design/caelza-vision.md) for the
architecture, the roadmap, what we are borrowing from
[OpenClaw](https://github.com/openclaw/openclaw), and the UI redesign.
Brand: [`brand/BRAND.md`](brand/BRAND.md). Caelza uses the Enlightened Republic
Build Lab design system (Inter Tight, JetBrains Mono, the Republic palette)
with its own identity on top: the mark is the constellation **Caelum** drawn
as a lightning bolt, its four stars at the bolt's turning points, in neon
cyan→purple, with the Orbitron wordmark and the cosmic backdrop.

## Runtime

```bash
./runtime/build.sh                  # fetch the pinned upstream, rebrand, cargo build --release
./runtime/dist/caelza quickstart    # pick a provider, write ~/.caelza/config.toml
./runtime/dist/caelza agent -a main # chat
```

`./runtime/build.sh --check-only` is the fast gate (cargo check). The pipeline
renames everything a user can see (`zeroclaw` → `caelza`, the TUI `zerocode` →
`caelcode`, the relay → `caelrelay`, config at `~/.caelza/`), swaps in the
Caelza palette and mark, and keeps the WASM plugin ABI namespace so upstream
plugins load unchanged. Details and the upstream pin: [`runtime/README.md`](runtime/README.md).

On Windows 10/11 (experimental, new and untested in real use), in PowerShell:

```powershell
irm https://raw.githubusercontent.com/Enlightened-Republic/Caelza/main/runtime/windows-install.ps1 | iex
caelza quickstart
```

On the phone, in Termux, the release build installs with one line:

```bash
curl -fsSL https://raw.githubusercontent.com/Enlightened-Republic/caelza/main/runtime/termux-install.sh | sh
caelza quickstart                    # provider + first agent
# then merge runtime/caelza.phone.example.toml: Telegram, Mind, Body, risk profile
caelza daemon                        # gateway on http://127.0.0.1:42617 + channels
```

## Mind

```bash
# xanima-server, the brain service, from the latest Caelza release → the `caelza-mind` launcher
# (Termux or a Linux hub; CAELZA_SERVICE=1 also installs what starts it after a reboot)
curl -fsSL https://raw.githubusercontent.com/Enlightened-Republic/caelza/main/mind/install.sh | sh
caelza-mind serve &                      # one brain per agent plus a shared one, on 127.0.0.1:18790
caelza-mind token mint --agent main --scopes read,write --json | jq -r .token > ~/.xanima/tokens/main.token
caelza config set memory.backend xanima  # the Runtime's own memory is the brain service (mind/caelza-mind.example.toml has the whole block)
caelza memory stats                      # the smoke test
```

That is the native backend (`XanimaMemory`, built into every `caelza`
binary): recall on every turn, every turn into the brain's episode log, and the
service's sleep doing the forgetting. The two tool paths (the stdio `xanima`
MCP server, the same service as an `http` MCP server) are for deliberate memory
work and are described in [`mind/README.md`](mind/README.md).

## Body

A supervised, self-modifying Python agent that treats a phone as its body.
Target runtime: **Termux on non-root Android**, Python 3.11+. The reference
device is a T-Mobile REVVL 7 5G.

```
caelza_body/supervisor.py   immutable: git-commits → probes the new build → promotes it
                     or rolls back to last-good; crash-loop guard; heartbeat
caelza_body/agent/
  loop.py            chat long-poll → context → model → tool dispatch
  model.py           MiniMax M3 (OpenAI-compatible)
  memory.py          sharpwave over MCP (same engine as the Mind)
  tools/
    sensors.py       camera / mic / location / notifications / tts / clipboard / battery / torch
    device.py        ADB: shell, screencap, ui_dump, packages, logcat, settings, input;
                     dangerous ops require a reason, are audit-logged, snapshot first
    selfmod.py       self_read_file / self_write_file / self_run_tests / self_commit / self_request_restart
    web.py           Firecrawl search / read / map / crawl / extract, multi-provider search
    shell.py         shell_run
```

On the phone, in Termux (Termux, Termux:API and Termux:Boot from F-Droid), one line:

```bash
curl -fsSL https://raw.githubusercontent.com/Enlightened-Republic/caelza/main/install.sh | sh
```

That installs packages, clones to `~/caelza`, installs the package and hands
off to `python scripts/setup.py`, which walks the steps that need you. By hand:

```bash
git clone https://github.com/Enlightened-Republic/caelza ~/caelza
cd ~/caelza
cp caelza_body/agent/prompt.example.md caelza_body/agent/prompt.md   # name, owner, purpose
python scripts/setup.py                                  # walks every bring-up step
```

Config lives in `~/.caelza-body/config.toml` (never committed). A phone set up
before the Caelza rename needs one migration after pulling this: `python
scripts/setup.py --migrate` moves the old `~/.niba` folder to `~/.caelza-body` and replaces
the boot script. Until then the legacy paths still boot. Tests run on a dev box
or on-device:

```bash
pip install -e ".[dev]"
python -m pytest -q
```

The Body is also an MCP server. `caelza-body serve` (installed with the
package) exposes the same 43 tools to the Runtime over stdio with the safety
semantics intact: `reason` required on dangerous ops, the audit log, package
snapshots before any removal. [`body/caelza-body.example.toml`](body/caelza-body.example.toml)
is the Runtime wiring, including a risk profile that auto-approves the reads
and asks before anything irreversible; [`body/README.md`](body/README.md) has
the details. Retiring the Python loop in favour of the Runtime is a per-phone
switch once the Runtime runs there (vision doc §3.1). The **Caelza Android
app** ([`android/`](android/), M7) is the product people install instead of a
Termux session: Cael leads the first run, it installs the Runtime from the
releases, runs it as a foreground service, shows the dashboard, serves the
Body's device tools and sensors to the Runtime (device control over
[Shizuku](https://github.com/RikkaApps/Shizuku), without root or Termux),
and runs the free local model beside it (§3.3,
[`docs/design/android-app.md`](docs/design/android-app.md)).

## Models

Caelza works with no account and no API key. Door 1 is **DeepSeek R1, free and
local**; door 2 is **bring your own** (any provider the Runtime supports:
Anthropic, OpenAI, OpenRouter, MiniMax, Ollama, any OpenAI-compatible endpoint).

```bash
sh scripts/model-setup.sh --dry-run   # what this device gets
sh scripts/model-setup.sh             # fetch the models, configure the Runtime, create Cael
```

The ladder ([`scripts/model_ladder.py`](scripts/model_ladder.py)) is honest
about size: a hub with 16 GB runs `deepseek-r1:14b` on Ollama, 8 GB runs `8b`;
a phone with 6 GB or more runs the 7B Q4 on llama.cpp (the Termux package),
a smaller phone runs the 1.5B for chat and explanation only. GGUFs are verified
against pinned checksums. The 1.5B always comes along: it is **Cael**, the
in-app guide (`agents.cael`, read-only, no tools), who explains keys,
providers, approvals and pairing in plain language, offline (§3.4,
[`guide/CAEL.md`](guide/CAEL.md), persona in [`guide/cael.system.md`](guide/cael.system.md)).
He answers from a corpus of the docs ([`guide/FAQ.md`](guide/FAQ.md), the
READMEs, the Runtime's book) that `scripts/cael_corpus.py` loads into his
memory; the app does it on its own.
The wiring in TOML: [`runtime/caelza.local-model.example.toml`](runtime/caelza.local-model.example.toml).

## Design docs

- [`docs/design/caelza-vision.md`](docs/design/caelza-vision.md) — Caelza: architecture, roadmap, borrow list, UI
- [`docs/design/agent-design.md`](docs/design/agent-design.md) — Body spec (written before the Caelza rename)
- [`docs/design/plan-1-core.md`](docs/design/plan-1-core.md), [`plan-2-device-tools.md`](docs/design/plan-2-device-tools.md) — Body implementation plans
- [`docs/examples/revvl-7-debloat/`](docs/examples/revvl-7-debloat/) — worked example: debloating a carrier phone for an agent

## Status

The reference Body is deployed and running. Runtime pipeline builds from
upstream `c473221` (v0.8.6). Public for testing: expect rough edges.

## License

MIT for this repository (the Body, the pipeline, the brand and the docs). The
Runtime binary is built from ZeroClaw under MIT OR Apache-2.0; the pipeline
writes the upstream notices into every build. Fonts are SIL OFL 1.1.
