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
| `xanima-openclaw` 0.5.0 | the OpenClaw plugin, id `xanima` (legacy id `openwave` honoured), bin `xanima-openclaw-upgrade` | npm; ClawHub as `clawhub:xanima`; repo [Enlightened-Republic/xanima-openclaw](https://github.com/Enlightened-Republic/xanima-openclaw) `main` |
| `xanima-core` 0.5.0 | the engine (formerly `sharpwave-core`) | npm; repo [Enlightened-Republic/xanima](https://github.com/Enlightened-Republic/xanima) `main`, `packages/core` |
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

### C. Native `Memory` backend (the actual integration; next)

The runtime's memory crate (`caelza-memory`, upstream `zeroclaw-memory`) ships
backends behind one trait: `SqliteMemory`, `QdrantMemory`, `PostgresMemory`,
`MarkdownMemory`, `LucidMemory`, `NoneMemory`, plus wrappers (`AgentScopedMemory`,
`AuditedMemory`, `ScannedMemory`). Add **`XanimaMemory`**: an `impl Memory` that
talks to the brain service from step B.

- `recall(query)` → `brain_query` (private + shared, RRF-fused, spread across
  the graph, with confidence and relative-time labels). This is what the
  runtime calls while assembling context, so recall becomes automatic per turn,
  which is the thing the MCP tools path cannot give.
- `store(...)` → `brain_episode_append` (turn log) and `brain_write` (explicit
  facts). Importance from the runtime's existing scorer.
- `forget` / `supersede` / `retract` → `brain_forget` / `brain_supersede` /
  `brain_retract`.
- Session start → `brain_briefing` + the identity/goal header, pinned via the
  runtime's system-prompt assembly (upstream `pinned_resources` is the model).
- Sleep stays in the service. The runtime does not run consolidation timers;
  it reads what the service dreamt.

Selected with `[memory] backend = "xanima"` plus `url` and a token file
(`~/.sharpwave/tokens/{agent}.token`, the same convention xanima uses). The
`AgentScopedMemory` wrapper already isolates agents; the service's per-agent
tokens enforce it a second time.

What xanima does that step C should port, in priority order: the never-compacted
identity/goals header; query-relevant recall block; always-on procedural rules;
last-24h digest; the `[BRAIN: goals]` alignment note and open-question line;
system-turn noise filtering (`isSystemNoiseTurn`: heartbeat polls, cron wakes,
`NO_REPLY`, must not become memories); importance clamp for automation turns.
The runtime has heartbeats and cron too, so the same classes of noise exist.

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
