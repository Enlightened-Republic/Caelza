# Caelza Mind — xanima

The Mind is Caelza's long-term memory. It is **xanima** (formerly openwave) on
the **xanima-core** engine (formerly sharpwave-core): a graph memory with an
FSRS forgetting curve, typed edges, supersession, beliefs with confidence and
provenance, a decision ledger, goals and drift checks, reflection, and a sleep
system (slow-wave / REM consolidation, awake replay, LLM fact extraction) that
improves the graph between sessions.

Airframe Lite already used the engine over MCP (`caelza_body/agent/memory.py`).
Caelza keeps the same engine and the same brain databases, so nothing migrates;
what changes is how the runtime reaches it.

## Where xanima is

The rebrand shipped on 2026-10-18/19: both repos' `main` branches carry it
(merged through the `xanima/release-cleanup` PRs) and the packages are on npm.

| Package | What | Where |
|---|---|---|
| `xanima-openclaw` 0.5.0 | the OpenClaw plugin, id `xanima` (legacy id `openwave` honoured), bin `xanima-openclaw-upgrade` | npm; ClawHub as `clawhub:xanima`; repo [Enlightened-Republic/openwave](https://github.com/Enlightened-Republic/openwave) `main` |
| `xanima-core` 0.5.0 | the engine (formerly `sharpwave-core`) | npm; repo [Enlightened-Republic/sharpwave](https://github.com/Enlightened-Republic/sharpwave) `main`, `packages/core` |
| `xanima` 0.5.0 | the stdio MCP server (formerly `sharpwave`), bins `xanima` and `sharpwave` | npm; `packages/mcp` |
| `xanima-server` 0.5.0 | the brain service (formerly `sharpwave-server`), bins `xanima-server`, `xanima-client` plus the old names | **private, not on npm**: build from a sharpwave checkout (`npm run build --workspace xanima-server`) and run `node packages/server/dist/cli.js serve` |

What moved, and what did not:

| | before | now |
|---|---|---|
| plugin config entry | `plugins.entries.openwave` | `plugins.entries.xanima`; an empty entry falls back to the openwave block with a warning; `xanima-openclaw-upgrade --config <openclaw.json> --write` copies it |
| plugin token env | `OPENWAVE_BRAIN_TOKEN` | `XANIMA_BRAIN_TOKEN` (old name accepted with a warning) |
| local brains | `~/.sharpwave/<agent>/brain.db` | `~/.xanima/<agent>/brain.db`; `~/.sharpwave` is read until `xanima-server migrate` copies it (never moved or deleted) |
| engine env vars | `SHARPWAVE_DATA_DIR`, `SHARPWAVE_DB_PATH`, `SHARPWAVE_AGENT_ID`, `SHARPWAVE_EMBEDDING_MODEL`, … | unchanged |
| service root / port | `~/.sharpwave/service/`, `127.0.0.1:18790` | unchanged |
| host cron id | `openwave:consolidation` | unchanged (rename deferred) |
| tools | 16 `brain_*` | 43 `brain_*`, schema v25; names unchanged and permanent |
| old packages on npm | `openwave` 0.1.1, `sharpwave` 0.4.1, `sharpwave-core` 0.4.5 | still listed, not deprecated; the `sharpwave` bin now ships inside `xanima` |

One lag worth knowing: the published `xanima-openclaw` README still shows the
old install commands (`clawhub:openwave`, `npm:openwave`,
`plugins.entries.openwave`) under the new banner. The commands that work are
`openclaw plugins install clawhub:xanima --accept-capabilities` and
`plugins.entries.xanima`.

## How the Runtime talks to the Mind

xanima is an **OpenClaw plugin**: it hooks OpenClaw's turn lifecycle
(`before_prompt_build`, `agent_turn_prepare`, `llm_output`, `agent_end`) and
runs timers in the gateway process. The Caelza runtime is a Rust binary with its
own plugin host (WASM, `zeroclaw:plugin` ABI) and a `Memory` trait, so the
plugin itself cannot be loaded as-is. The engine behind it can, in three steps.

### A. Tools path (works now)

`npm i -g xanima`, then register the stdio MCP server in `~/.caelza/config.toml`
(`caelza-mind.example.toml`). The `sharpwave` bin is kept as an alias, so an
existing config keeps working. The agent gets the `brain_*` tools and can
recall and write deliberately. No per-turn injection, no sleep system in the
runtime; the MCP server consolidates on its own schedule.

### B. Service path (works now; the bridge everything else uses)

Run `xanima-server`, the brain service: one process owning a shared brain plus
one private brain per agent, serving the brain tools over MCP Streamable HTTP
on `127.0.0.1:18790` with per-agent bearer tokens (`xanima-server token mint`).
It is a private workspace package, so it runs from a sharpwave checkout rather
than an npm install. This is exactly the endpoint xanima's **remote brain
mode** speaks, so one service serves an OpenClaw gateway (through xanima) and
a Caelza runtime (through its `http` MCP transport) with the same brains.
Auto-provisioning (`brain_provision_agent`, a provision-scoped token on
loopback) gives new Caelza agents a brain with no restart. `xanima-server
brain adopt` takes an existing `brain.db` as an agent's private brain, which is
how the phone's current brain moves in.

### C. Native `Memory` backend (shipped: milestone M3)

The runtime's memory crate (`caelza-memory`, upstream `zeroclaw-memory`) ships
backends behind one trait: `SqliteMemory`, `QdrantMemory`, `PostgresMemory`,
`MarkdownMemory`, `LucidMemory`, `NoneMemory`, plus wrappers (`AgentScopedMemory`,
`AuditedMemory`, `ScannedMemory`). Caelza adds **`XanimaMemory`**, an `impl
Memory` that speaks the brain service's MCP Streamable HTTP directly
(`POST /mcp`, JSON-RPC `tools/call`, one bearer token per agent). It is carried
as `runtime/overlay/crates/caelza-memory/src/xanima.rs` plus
`runtime/patches/0001-xanima-memory-backend.patch` (the config schema, the
backend registry, the factory, the dashboard picker) and goes into every build
`runtime/build.sh` makes.

| Runtime call | Brain service | Note |
|---|---|---|
| `recall(query)` (every turn, context assembly) | `brain_query` with `format = json`, `scope` from config | private + shared, fused by the service; confidence and `created_at` carried into the entry; empty or `*` queries recall nothing (the service needs a query) |
| `store` of an auto-saved turn (`conversation`) | `brain_episode_append` | role from the key (`user_msg_*` → user, `assistant_resp_*` → assistant); the service's own noise filter drops heartbeat / cron / `NO_REPLY` turns |
| `store` of a fact (`core`, `daily`, custom) | `brain_write` | label = key; `core` → `semantic`, `daily` → `episodic`, a custom category that names a node type is used as is; importance passes through, pinned → 1.0 |
| `get` / `forget` by key | `brain_query` on the label, then `brain_forget` | the newest node with that exact label |
| `count` / `stats` | `brain_stats` | nodes per brain and per type |
| `health_check` | `GET /health` | no token |
| `list` | none | the service has no enumerate-everything call; `caelza memory list` is empty on this backend |

Selected with `[memory] backend = "xanima"`; `[storage.xanima.<alias>]` holds
`url` (default `http://127.0.0.1:18790`), `token_file`
(`~/.xanima/tokens/{agent}.token`, one token per agent alias) or a single
`token`, `agent` (the brain for operations that name no agent), `scope` and
`timeout_secs`. A bare `backend = "xanima"` with no storage block uses those
defaults. Agents: the `AgentScopedMemory` wrapper passes the agent alias, the
backend picks that alias's token, so the service's private brains and the
runtime's isolation agree; recall across granted siblings
(`workspace.read_memory_from`) queries each sibling's brain with its own token
and skips siblings that have none. Sleep stays in the service: the runtime runs
no consolidation timers and reads what the service dreamt.

Mint tokens once per agent:

```sh
xanima-server token mint --agent main --scopes read,write --json | jq -r .token > ~/.xanima/tokens/main.token
xanima-server token mint --agent cael --scopes read       --json | jq -r .token > ~/.xanima/tokens/cael.token
```

`caelza-mind.example.toml` has the block; `caelza memory stats` against a
running service is the smoke test.

Still open from xanima's host-side behaviour, in priority order: the
never-compacted identity/goals header and the `[BRAIN: goals]` alignment note
(`brain_turn_context`, pinned through the runtime's system-prompt assembly);
auto-provisioned brains for new agents (`brain_provision_agent`, so a new
`[agents.<alias>]` needs no manual mint); the last-24h digest. The system-noise
filter is already in the service (`brain_episode_append` skips heartbeat polls,
cron wakes and `NO_REPLY`), so the runtime's own heartbeats and cron turns
never become memories.

### Later

- **Shared brain across bodies.** One service, many Caelza runtimes (the phone,
  a hub, a Pi): private brains per agent, the shared brain and rooms for what
  the fleet knows together. The service already models this (`brain_room`,
  `brain_publish`, `brain_subscribe`).
- **Skill evolution → Caelza skills.** `skillEvolution` generates a skill file
  when a pattern recurs; write them into the runtime's skill-bundle directory
  so the agent grows its own playbooks.
- **Memory page in the dashboard.** xanima ships a control UI
  (`src/control-ui.ts`): brain stats, recall preview, graph browse, identity
  history. Port it to the Caelza dashboard's Memory section against the
  service API.

## Files

```
mind/
├── README.md                  this
└── caelza-mind.example.toml   MCP server blocks for paths A and B
```
