# Caelza Mind — xanima

The Mind is Caelza's long-term memory. It is **xanima**, the renamed
[openwave](https://github.com/Enlightened-Republic/openwave) plugin, on the
[sharpwave-core](https://github.com/Enlightened-Republic/sharpwave) engine:
a graph memory with an FSRS forgetting curve, typed edges, supersession, and a
sleep system (slow-wave / REM consolidation, awake replay, LLM fact extraction)
that improves the graph between sessions.

Airframe Lite already used sharpwave over MCP (`caelza_body/agent/memory.py`). Caelza
keeps the same engine and the same brain databases (`~/.sharpwave/<agent>/brain.db`,
schema v17), so nothing migrates; what changes is how the runtime reaches it.

## Naming

| | openwave (0.2.0) | xanima |
|---|---|---|
| npm package / ClawHub slug | `openwave` | `xanima` |
| plugin id (`openclaw.plugin.json` → `id`) | `openwave` | `xanima` |
| config entry | `plugins.entries.openwave` | `plugins.entries.xanima` |
| host cron id | `openwave:consolidation` | `xanima:consolidation` |
| token env var | `OPENWAVE_BRAIN_TOKEN` | `XANIMA_BRAIN_TOKEN` |
| log prefix | `[openwave]` | `[xanima]` |
| brain db path | `~/.sharpwave/<agent>/brain.db` | unchanged (engine-owned) |
| engine | `sharpwave-core ^0.4.5` | unchanged |

**Decided (2026-10-18): xanima everywhere.** The rename lands in the openwave
repo as one clean break; until that ships, every reference here that says
xanima resolves to openwave 0.2.0, and the bundle manifest records both names.
Checklist for the openwave-side change:

1. `package.json` → `"name": "xanima"`, repo URL, keywords; publish `xanima`
   to npm and ClawHub (`clawhub:xanima`); deprecate `openwave` on npm with a
   pointer.
2. `openclaw.plugin.json` → `"id": "xanima"`, `"name": "xanima"`.
3. Config entry `plugins.entries.xanima`; allowlist entries; the `[xanima]`
   log prefix; `XANIMA_BRAIN_TOKEN` env (read `OPENWAVE_BRAIN_TOKEN` as a
   fallback for one release).
4. Host cron id `xanima:consolidation`; on `gateway_start` remove a leftover
   `openwave:consolidation`, the way the legacy-cleanup code already drops
   older job names.
5. Leave `brainTokenFile` paths and `~/.sharpwave/<agent>/brain.db` alone;
   they are engine-owned and users have them on disk.
6. README, HAILEY.md, the `.tech` site card and the sharpwave README pointer.

## How the Runtime talks to the Mind

xanima is an **OpenClaw plugin**: it hooks OpenClaw's turn lifecycle
(`before_prompt_build`, `agent_turn_prepare`, `llm_output`, `agent_end`) and
runs timers in the gateway process. The Caelza runtime is a Rust binary with its
own plugin host (WASM, `zeroclaw:plugin` ABI) and a `Memory` trait, so the
plugin itself cannot be loaded as-is. The engine behind it can, in three steps.

### A. Tools path (works now)

Register the `sharpwave` stdio MCP server in `~/.caelza/config.toml`
(`caelza-mind.example.toml`). The agent gets the `brain_*` tools and can
recall and write deliberately. No per-turn injection, no sleep system in
the runtime; the MCP server consolidates on its own schedule.

### B. Service path (works now; the bridge everything else uses)

Run `sharpwave-server`, the brain service: one process owning a shared brain
plus one private brain per agent, serving the brain tools over MCP Streamable
HTTP on `127.0.0.1:18790` with per-agent bearer tokens. This is exactly the
endpoint xanima's **remote brain mode** speaks, so one service serves an
OpenClaw gateway (through xanima) and a Caelza runtime (through its `http`
MCP transport) with the same brains. Auto-provisioning (`brain_provision_agent`,
provision-scoped token on loopback) gives new Caelza agents a brain with no
restart.

### C. Native `Memory` backend (the actual integration; next)

The runtime's memory crate (`caelza-memory`, upstream `zeroclaw-memory`) ships
backends behind one trait: `SqliteMemory`, `QdrantMemory`, `PostgresMemory`,
`MarkdownMemory`, `LucidMemory`, `NoneMemory`, plus wrappers (`AgentScopedMemory`,
`AuditedMemory`, `ScannedMemory`). Add **`SharpwaveMemory`**: an `impl Memory`
that talks to the brain service from step B.

- `recall(query)` → `brain_query` (private + shared, RRF-fused, spread across
  the graph). This is what the runtime calls while assembling context, so
  recall becomes automatic per turn, which is the thing the MCP tools path
  cannot give.
- `store(...)` → `brain_episode_append` (turn log) and `brain_write` (explicit
  facts). Importance from the runtime's existing scorer.
- `forget` / `supersede` → `brain_forget` / `brain_supersede`.
- Session start → `brain_review` + the identity/goal header, pinned via the
  runtime's system-prompt assembly (upstream `pinned_resources` is the model).
- Sleep stays in the service. The runtime does not run consolidation timers;
  it reads what the service dreamt.

Selected with `[memory] backend = "sharpwave"` plus `url` and a token file
(`~/.sharpwave/tokens/{agent}.token`, same convention as xanima). The
`AgentScopedMemory` wrapper already isolates agents; the service's per-agent
tokens enforce it a second time.

What xanima does that step C should port, in priority order: the never-compacted
identity/goals header; query-relevant recall block; always-on procedural rules;
last-24h digest; system-turn noise filtering (`isSystemNoiseTurn`: heartbeat
polls, cron wakes, `NO_REPLY`, must not become memories); importance clamp for
automation turns. The runtime has heartbeats and cron too, so the same classes
of noise exist.

### Later

- **Shared brain across bodies.** One service, many Caelza runtimes (the phone,
  a hub, a Pi): private brains per agent, the shared brain for what the fleet
  knows together. The service already models this.
- **Skill evolution → Caelza skills.** sharpwave-core's `skillEvolution`
  generates a skill file when a pattern recurs; write them into the runtime's
  skill-bundle directory so the agent grows its own playbooks.
- **Memory page in the dashboard.** xanima ships a control UI
  (`src/control-ui.ts`): brain stats, recall preview, graph browse. Port it to
  the Caelza dashboard's Memory section against the service API.

## Files

```
mind/
├── README.md                  this
└── caelza-mind.example.toml   MCP server blocks for paths A and B
```
