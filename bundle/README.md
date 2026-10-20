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
│   │ caelza (Rust)│    │ xanima       │    │ caelza_body (Py)   │    │
│   │ loop·tools·  │    │ xanima-core  │◀──▶│ supervisor·sensors·│    │
│   │ channels·    │    │ engine       │    │ ADB·self-mod       │    │
│   │ gateway·UI   │    │ brain service│    │ (Termux/Android)   │    │
│   └──────┬───────┘    └──────────────┘    └─────────┬──────────┘    │
│          │                 MCP / HTTP               │ MCP (stdio)   │
│          └──────────────────────────────────────────┘               │
└──────────────────────────────────────────────────────────────────────┘
```

| Component | What it is | Where | Pin |
|---|---|---|---|
| **Runtime** | the agent engine, a rebranded ZeroClaw build | `runtime/` → binary `caelza` | upstream `c473221` (v0.8.6) |
| **Mind** | autonomic long-term memory: xanima (formerly openwave) on the xanima-core engine | [Enlightened-Republic/xanima-openclaw](https://github.com/Enlightened-Republic/xanima-openclaw); npm `xanima-openclaw`, `xanima-core`, `xanima`; ClawHub `xanima` | 0.5.0 / core 0.5.0 |
| **Body** | the device layer: termux-api sensors, ADB device control, the immutable supervisor with git-backed rollback | `caelza_body/` in this repo | this repo |

How they connect today and where that is going is in
[`../mind/README.md`](../mind/README.md) (Mind ↔ Runtime) and
[`../docs/design/caelza-vision.md`](../docs/design/caelza-vision.md) (the whole
picture, the roadmap, the UI redesign).

## Install (current state)

1. **Runtime**: `./runtime/build.sh` → `runtime/dist/caelza`, then
   `caelza quickstart`. Config lives at `~/.caelza/config.toml`.
2. **Mind**: `npm i -g xanima` (the engine's MCP server; keeps a `sharpwave`
   alias bin) and register it as an MCP server in the runtime config
   (`mind/caelza-mind.example.toml`). For the autonomic path run
   `xanima-server` from a sharpwave checkout and point xanima's remote mode at it.
3. **Body**: on the phone, `install.sh` or `python scripts/setup.py` (see the
   top-level README). Then merge `body/caelza-body.example.toml` into the
   runtime config so the Runtime spawns `caelza-body serve` and gets the
   Body's tools as `body__<tool>` ([`../body/README.md`](../body/README.md)).

A one-command installer that does all three is on the roadmap; the manifest is
what it will read.
