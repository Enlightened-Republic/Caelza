<p align="center">
  <img src="brand/hero.png" alt="Enlightened Republic presents Caelza — the embodied agent runtime" width="100%" />
</p>

<h1 align="center">Caelza</h1>

<p align="center"><strong>The embodied agent runtime.</strong><br/>
An agent that lives on your own hardware, remembers across months, and acts on the devices around it.</p>

<p align="center"><sub><a href="https://www.enlightenedrepublic.tech"><img src="https://enlightenedrepublic.online/assets/er-profile-pic.png" alt="" width="20" align="absmiddle" /></a>&nbsp; Built by <a href="https://www.enlightenedrepublic.tech">Enlightened Republic</a>, the lab behind SharpWave and xanima. · EST. 2026</sub></p>

<p align="center">
  <a href="https://github.com/Enlightened-Republic/Caelza/releases/download/v0.2.0/caelza-app-0.2.0.apk"><img src="https://img.shields.io/badge/%E2%AC%87%EF%B8%8F_Install_the_Android_app-APK_v0.2.0-00d4ff?style=for-the-badge&logo=android&logoColor=white" alt="Install the Android app (APK v0.2.0)" /></a>
  &nbsp;
  <a href="https://github.com/Enlightened-Republic/Caelza/releases/download/v0.2.0/Caelza-Setup.exe"><img src="https://img.shields.io/badge/%E2%AC%87%EF%B8%8F_Install_on_Windows-Setup.exe_v0.2.0-7b6bff?style=for-the-badge" alt="Install on Windows (Caelza-Setup.exe v0.2.0)" /></a>
</p>

> [!WARNING]
> **This is a testing build.** Caelza is early, unfinished software and is being tested right now. Expect bugs, rough edges and breaking changes. Don't rely on it for anything important, and don't give it access to anything you can't afford to lose. The Windows installer is unsigned, so SmartScreen asks once before it runs. The APK is release-signed from v0.2.0 on, so later versions install over it; if you still have the v0.1.0 build, uninstall it first.

## Try it on your Android phone

1. On your phone, tap the **Install the Android app** button above (or [download the APK](https://github.com/Enlightened-Republic/Caelza/releases/download/v0.2.0/caelza-app-0.2.0.apk)).
2. Open the downloaded file. If Android asks, allow your browser or Files app to **install unknown apps**, then tap **Install**.
3. Open **Caelza** and follow Cael's first-run screens. The app downloads the runtime on first run, so connect to Wi-Fi first.
4. Something broke? Use **Logs** in the app to share a bug report.

## Try it on your Windows PC

Experimental: the Windows build is new and has not had many real runs yet.

1. Tap the **Install on Windows** button above (or [download Caelza-Setup.exe](https://github.com/Enlightened-Republic/Caelza/releases/download/v0.2.0/Caelza-Setup.exe)) and run it. SmartScreen will warn because the installer is unsigned: click **More info**, then **Run anyway**. No admin rights are needed; it installs for your user only.
2. Open **Caelza** from the Start menu. The agent starts in a minimised window and your browser opens the dashboard.
3. Click **Pair** on the first screen (the code is already filled in), then follow Cael's setup: a free local model or your own provider key. The free model runs through [Ollama](https://ollama.com/download); Cael checks whether it is installed, points you to its download if not, and fetches the model for you (one click, a progress bar, a few GB).
4. Something broke? The agent's minimised window shows what it is doing; copy its text into an [issue](https://github.com/Enlightened-Republic/Caelza/issues).

### What else it does

Shipped and new; some of it has not met the real thing yet, so tell us what breaks:

- **Your apps, connected.** Gmail, Calendar, Drive, Notion, Slack and about a hundred more through [Maton](https://maton.ai): make a free Maton account, connect your apps there, and paste one Maton key on the dashboard's **Connect** page. Reading is free; sending, posting, paying and deleting always ask you first.
- **Smart home.** Lights, switches, thermostats and locks through Home Assistant's own MCP server (2025.2 or newer): its address and a long-lived token on the **Connect** page. Locks and doors always ask first. Not yet tried against a real Home Assistant.
- **3D printers.** Status, progress, temperatures and a camera snapshot over Wi-Fi for Moonraker (Klipper, Mainsail, Fluidd) and OctoPrint, with pause and cancel behind your yes; Bambu Lab is not supported yet. The printer's address on the **Connect** page. Not yet tried against a real printer.
- **Updates that arrive by themselves.** The app checks the releases every six hours, tells you when a newer Caelza is ready, downloads it, checks it against its published checksum and hands it to Android's installer, which asks you once. The Runtime inside updates through its guard.

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

On Windows 10/11 (experimental, new and untested in real use): download
`Caelza-Setup.exe` from the [latest release](https://github.com/Enlightened-Republic/Caelza/releases/latest)
and run it (it is unsigned, so SmartScreen asks once: "More info", then "Run
anyway"). The Start menu entry starts the agent and opens the dashboard; the
first time, Cael walks you through setup in the browser. Or, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/Enlightened-Republic/Caelza/main/runtime/windows-install.ps1 | iex
caelza daemon        # then open http://127.0.0.1:42617 in your browser
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

The Body's design comes from Niba, the original phone-body agent, which has
since been renamed Cael. The code, paths and docs now use the Caelza names; the
only place the old name survives is the `~/.niba` folder that a phone set up
before the rename still has (see the migration note below).

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

Caelza is open source. Each of the three layers is licensed on its own, and
the parts we wrote are ours and MIT-licensed.

| Part | Who wrote it | License |
|---|---|---|
| **Body** (`caelza_body/`, `body/`), the build pipeline (`runtime/` scripts and patches), the Android app (`android/`), Cael's guide (`guide/`), the brand assets and the docs | Enlightened Republic | [MIT](LICENSE) |
| **Mind**: [xanima](https://github.com/Enlightened-Republic/xanima-openclaw) and the [xanima-core](https://github.com/Enlightened-Republic/xanima) engine (formerly openwave and sharpwave-core) | Enlightened Republic | MIT |
| **Runtime** engine: the compiled `caelza` binary, built from [ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw) | ZeroClaw authors, rebranded by our pipeline | MIT OR Apache-2.0, your choice |
| **Fonts** in `brand/fonts/` | their authors | SIL OFL 1.1 |

### What you can do

MIT is about as permissive as licenses get. For the MIT parts you may use
Caelza for yourself, for your business or for clients; change it; fork it;
redistribute it; and sell products built on it, including closed-source ones,
with no fee and no need to ask. The one condition is that you keep the
copyright notice and the license text with any copy or substantial portion
of the code you pass on. There is no warranty: the software is provided as is,
and Enlightened Republic is not liable for what it does, so read the testing
warning at the top before you hand it access to anything you care about.

### What is ours, and what is not

The Body (the device layer and its safety model), the Mind (xanima) and the
Android app are original Enlightened Republic work. The Runtime is not: the
agent engine inside it is ZeroClaw, and our pipeline fetches a pinned upstream
commit, renames and re-themes it, and writes the upstream notices into every
build. Credit for that engine belongs to the ZeroClaw authors. If you
redistribute a Caelza Runtime binary, keep those notices with it.

### Things that are not covered by our license

- **Model weights.** Caelza ships no models; it downloads them on your device.
  DeepSeek R1 is MIT, but the distilled sizes are built on other base models
  that carry their own terms (Qwen-based sizes are Apache 2.0; the 8B is
  Llama-based and follows Meta's Llama license). Check the card of the exact
  model you pull if you plan to use it commercially.
- **Services you connect.** Maton, Home Assistant, Telegram, your model
  provider and anything else you wire up have their own terms, and your use of
  them is between you and them.
- **Other dependencies.** Third-party libraries (for example Shizuku, which is
  Apache 2.0) keep their own licenses.

This is a plain-language summary, not legal advice. The license files are the
authority: [`LICENSE`](LICENSE), [`runtime/README.md`](runtime/README.md) and
the `NOTICE` inside every Runtime build.
