# The Caelza bundle

"Caelza" the product is three components shipped together. `manifest.toml` is
the machine-readable pin list; this file is the human version.

```
┌──────────────────────────────────────────────────────────────────────┐
│  Caelza                                                              │
│                                                                      │
│   ┌──────────────┐    ┌──────────────┐    ┌────────────────────┐    │
│   │   Runtime    │    │     Mind     │    │        Body        │    │
│   │              │◀──▶│              │    │                    │    │
│   │ caelza (Rust)│    │ xanima       │    │ niba (Python)      │    │
│   │ loop·tools·  │    │ sharpwave-   │◀──▶│ supervisor·sensors·│    │
│   │ channels·    │    │ core engine  │    │ ADB·self-mod       │    │
│   │ gateway·UI   │    │ brain service│    │ (Termux/Android)   │    │
│   └──────┬───────┘    └──────────────┘    └─────────┬──────────┘    │
│          │                 MCP / HTTP               │ MCP (stdio)   │
│          └──────────────────────────────────────────┘               │
└──────────────────────────────────────────────────────────────────────┘
```

| Component | What it is | Where | Pin |
|---|---|---|---|
| **Runtime** | the agent engine, a rebranded ZeroClaw build | `runtime/` → binary `caelza` | upstream `c473221` (v0.8.6) |
| **Mind** | autonomic long-term memory: xanima (formerly openwave) on the sharpwave-core engine | [Enlightened-Republic/openwave](https://github.com/Enlightened-Republic/openwave) | 0.2.0 / core 0.4.5 |
| **Body** | the device layer: termux-api sensors, ADB device control, the immutable supervisor with git-backed rollback | `niba/` in this repo | this repo |

How they connect today and where that is going is in
[`../mind/README.md`](../mind/README.md) (Mind ↔ Runtime) and
[`../docs/design/caelza-vision.md`](../docs/design/caelza-vision.md) (the whole
picture, the roadmap, the UI redesign).

## Install (current state)

1. **Runtime**: `./runtime/build.sh` → `runtime/dist/caelza`, then
   `caelza quickstart`. Config lives at `~/.caelza/config.toml`.
2. **Mind**: `npm i -g sharpwave` and register it as an MCP server in the
   runtime config (`mind/caelza-mind.example.toml`). For the autonomic path run
   `sharpwave-server` and point xanima's remote mode at it.
3. **Body**: on the phone, `python scripts/setup.py` (unchanged from Airframe
   Lite; see the top-level README).

A one-command installer that does all three is on the roadmap; the manifest is
what it will read.
