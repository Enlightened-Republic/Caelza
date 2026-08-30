# Airframe Lite

A supervised, self-modifying autonomous agent that lives on a device **as its
body** — camera, mic, speaker, shell, and ADB reach into other devices. It talks
to its owner over chat (Telegram) and, later, voice with a wake word.

"Lite" because it's the small build: one phone, one owner, a Python agent + an
immutable supervisor. The reference agent is named **Niba**.

## Why "airframe"

The airframe is the load-bearing structure everything else bolts onto. This repo
is that structure for an embodied agent: the part that stays put and keeps the
agent alive and recoverable while everything above it — identity, tools, skills —
changes.

## How it holds together

```
supervisor.py  (immutable — you cannot edit it, the agent cannot edit it)
  └─ spawns the agent, and on every restart request:
       git-commits → probes the new build → promotes it, or rolls back to
       the last-good commit and reports what broke. Crash-loop guard with a
       terminal halt. Heartbeat on its own thread.

niba/agent/
  loop.py        chat long-poll → context assembly → model → tool dispatch loop
  model.py       MiniMax M3 (OpenAI-compatible); retries transient transport errors
  context.py     system prompt + recent turns + retrieved memory + the new message
  memory.py      adapter over a SharpWave MCP server (long-term memory)
  session.py     SQLite transcript + token/usage accounting
  telegram.py    the chat transport
  heartbeat.py   liveness file the supervisor watches
  redact.py      strips secrets from anything that could be logged or sent
  proc.py        one hardened subprocess runner (own process group, SIGKILL on
                 timeout — a backgrounded child can't wedge the agent)
  tools/
    selfmod.py   self_read_file / self_write_file / self_run_tests / self_commit /
                 self_request_restart  (deny-list: supervisor.py, .git/, secrets)
    memtools.py  memory_remember / memory_recall
    shell.py     shell_run
    sensors.py   sensors_camera_photo / _mic_record / _location / _notifications /
                 _tts_speak / _clipboard_* / _battery / _torch   (termux-api)
    device.py    device_shell / _screencap / _ui_dump / _packages / _logcat /
                 _settings / _input, and dangerous ops (uninstall / disable /
                 settings_put / appops / pair) that require a reason, are
                 audit-logged, and snapshot the package list before any removal
    media.py     image tools reach the model as images, not file paths
  adb.py         resolve device name → serial, run adb, connect-self, pair
  devices.py     JSON registry of paired devices ($NIBA_HOME/devices.json)
```

Target runtime: **Termux on non-root Android**. Python 3.11+, Node (for the
SharpWave memory server). `adb` via `pkg install android-tools`.

## Quickstart (on the device, in Termux)

```bash
git clone https://github.com/Enlightened-Republic/airframe-lite ~/niba
cd ~/niba
cp niba/agent/prompt.example.md niba/agent/prompt.md   # then edit it — name, owner, purpose
python scripts/setup.py                                  # walks every bring-up step
```

`scripts/setup.py` runs: package installs, the SharpWave + `mcp` installs,
`termux-api` permission grants, battery-optimisation exemption, model login,
self-ADB pairing, `~/.niba/config.toml`, the Termux:Boot script, and a final
"message me on Telegram" check. `--dry-run` prints the plan without doing
anything.

## Config

`~/.niba/config.toml` (written by setup; never committed):

```toml
[telegram]
bot_token = "..."
owner_chat_id = 0            # setup captures this from your first message
[openrouter]
api_key = "..."             # embeddings for memory; FTS fallback if absent
[minimax]
mmx_config_path = "~/.mmx/config.json"
[limits]
model_calls_per_hour = 120
monthly_token_budget = 1600000000
[model]                      # optional — cellular-friendly defaults shown
timeout_seconds = 180
max_attempts = 3
```

The model uses the `mmx` CLI's OAuth token (`mmx auth login`). No API key needed.

## Self-modification

The agent can rewrite any of its own code except `niba/supervisor.py`. The loop
is: `self_write_file` → `self_run_tests` → `self_commit` → `self_request_restart`.
The supervisor probes the new build in a separate process before promoting it; a
build that doesn't boot is rolled back to the last-good commit and the owner is
told what broke.

## Tests

```bash
pip install -e ".[dev]"
python -m pytest -q
```

The suite runs on a dev box (Windows/macOS/Linux) — subprocess-based tests fall
back through `sh` and skip real `termux-api`/`adb`. It also runs green on-device.

## Design docs

- [`docs/design/agent-design.md`](docs/design/agent-design.md) — the full spec
- [`docs/design/plan-1-core.md`](docs/design/plan-1-core.md) — core agent + supervisor
- [`docs/design/plan-2-device-tools.md`](docs/design/plan-2-device-tools.md) — device/sensor/ADB tools
- [`docs/examples/revvl-7-debloat/`](docs/examples/revvl-7-debloat/) — worked example: debloating a carrier phone for an agent

## Status

Reference agent ("Niba") is deployed and running on a T-Mobile REVVL 7 5G.
Private while it's early. Dependency: [SharpWave](https://github.com/Enlightened-Republic/sharpwave) (memory).
