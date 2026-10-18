<p align="center">
  <img src="brand/hero.png" alt="Enlightened Republic presents Caelza — the embodied agent runtime" width="100%" />
</p>

<h1 align="center">Caelza</h1>

<p align="center"><strong>The embodied agent runtime.</strong><br/>
An agent that lives on your own hardware, remembers across months, and acts on the devices around it.</p>

<p align="center"><sub><a href="https://www.enlightenedrepublic.tech"><img src="https://enlightenedrepublic.online/assets/er-profile-pic.png" alt="" width="20" align="absmiddle" /></a>&nbsp; Built by <a href="https://www.enlightenedrepublic.tech">Enlightened Republic</a>, the lab behind SharpWave and xanima. · EST. 2026</sub></p>

---

Caelza is three layers shipped as one product (`bundle/manifest.toml`):

| Layer | What | Where |
|---|---|---|
| **Runtime** | the engine: agent loop, 20+ model providers, 30+ channels, tools, security policy, SOP engine, cron, gateway + web dashboard, WASM plugins, hardware peripherals. A rebranded build of [ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw), regenerated from a pinned commit. | [`runtime/`](runtime/) |
| **Mind** | autonomic long-term memory: a graph with a real forgetting curve and a sleep system. [xanima](https://github.com/Enlightened-Republic/openwave) (formerly openwave) on the [sharpwave-core](https://github.com/Enlightened-Republic/sharpwave) engine. | [`mind/`](mind/) |
| **Body** | the device layer: camera, mic, location, notifications and TTS through termux-api; ADB control of its own phone and paired phones with audit logging and pre-removal snapshots; an immutable supervisor that probes self-modified builds and rolls back. Formerly **Airframe Lite**. | [`niba/`](niba/) |

Read [`docs/design/caelza-vision.md`](docs/design/caelza-vision.md) for the
architecture, the roadmap, what we are borrowing from
[OpenClaw](https://github.com/openclaw/openclaw), and the UI redesign.
Brand: [`brand/BRAND.md`](brand/BRAND.md). Caelza uses the Enlightened Republic
Build Lab design system (Inter Tight, JetBrains Mono, the Republic palette)
with its own identity on top: the bolt-C mark in neon cyan→purple, the
Orbitron wordmark, constellation stars and the cosmic backdrop.

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

## Mind

```bash
npm i -g sharpwave                       # the memory engine's MCP server
# then merge mind/caelza-mind.example.toml into ~/.caelza/config.toml
```

That is the tools path. The service path (`sharpwave-server`, one brain per
agent plus a shared one, same endpoint xanima's remote mode uses) and the
native `Memory` backend that makes recall automatic per turn are described in
[`mind/README.md`](mind/README.md).

## Body (the Airframe Lite layer)

A supervised, self-modifying Python agent that treats a phone as its body.
Target runtime: **Termux on non-root Android**, Python 3.11+. The reference
agent is named **Niba** and runs on a T-Mobile REVVL 7 5G.

```
niba/supervisor.py   immutable: git-commits → probes the new build → promotes it
                     or rolls back to last-good; crash-loop guard; heartbeat
niba/agent/
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

On the phone, in Termux:

```bash
git clone https://github.com/Enlightened-Republic/caelza ~/niba
cd ~/niba
cp niba/agent/prompt.example.md niba/agent/prompt.md   # name, owner, purpose
python scripts/setup.py                                  # walks every bring-up step
```

Config lives in `~/.niba/config.toml` (never committed). Tests run on a dev box
or on-device:

```bash
pip install -e ".[dev]"
python -m pytest -q
```

The Body's roadmap is to become `caelza-body`, an MCP server the Runtime spawns,
so the Python loop retires and the sensors, ADB tools and supervisor stay
(vision doc §3.1). After that comes the **Caelza Android app**, which hosts the
Body natively and uses [Shizuku](https://github.com/RikkaApps/Shizuku) for
shell-level device control without root or Termux (§3.3).

## Models

Caelza works with no account and no API key: quickstart offers **DeepSeek R1,
free and local** (Ollama on a hub, llama.cpp on the phone, sized to the
device) and a **bring your own** door for any provider the Runtime supports
(Anthropic, OpenAI, OpenRouter, MiniMax, Ollama, any OpenAI-compatible
endpoint). The local model also powers the in-app **Guide**, which explains
keys, providers, approvals and pairing in plain language, offline (§3.4).

## Design docs

- [`docs/design/caelza-vision.md`](docs/design/caelza-vision.md) — Caelza: architecture, roadmap, borrow list, UI
- [`docs/design/agent-design.md`](docs/design/agent-design.md) — Body spec (written as Airframe Lite / Niba)
- [`docs/design/plan-1-core.md`](docs/design/plan-1-core.md), [`plan-2-device-tools.md`](docs/design/plan-2-device-tools.md) — Body implementation plans
- [`docs/examples/revvl-7-debloat/`](docs/examples/revvl-7-debloat/) — worked example: debloating a carrier phone for an agent

## Status

Reference Body ("Niba") is deployed and running. Runtime pipeline builds from
upstream `c473221` (v0.8.6). Private while it's early.
