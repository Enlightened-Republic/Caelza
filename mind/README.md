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
| `xanima-openclaw` 0.7.0 | the OpenClaw plugin, id `xanima` (legacy id `openwave` honoured), bin `xanima-openclaw-upgrade` | npm; ClawHub as `clawhub:xanima`; repo [Enlightened-Republic/xanima-openclaw](https://github.com/Enlightened-Republic/xanima-openclaw) `main` |
| `xanima-core` 0.7.0 | the engine (formerly `sharpwave-core`) | npm; repo [Enlightened-Republic/xanima](https://github.com/Enlightened-Republic/xanima) `main`, `packages/core` |
| `xanima` 0.7.0 | the stdio MCP server (formerly `sharpwave`), bins `xanima` and `sharpwave` | npm; `packages/mcp` |
| `xanima-server` 0.7.0 | the brain service (formerly `sharpwave-server`), bins `xanima-server`, `xanima-client` plus the old names | **private, not on npm**: every Caelza release carries it built, as `caelza-mind-<version>.tgz` (`mind/pack.sh` packs the commit `bundle/manifest.toml` pins as `service_commit`), and `mind/install.sh` installs it as `caelza-mind` on a hub or in Termux. From a checkout: `npm run build --workspace xanima-server`, then `node packages/server/dist/cli.js serve` |

What moved, and what did not:

| | before | now |
|---|---|---|
| plugin config entry | `plugins.entries.openwave` | `plugins.entries.xanima`; an empty entry falls back to the openwave block with a warning; `xanima-openclaw-upgrade --config <openclaw.json> --write` copies it |
| plugin token env | `OPENWAVE_BRAIN_TOKEN` | `XANIMA_BRAIN_TOKEN` (old name accepted with a warning) |
| local brains | `~/.sharpwave/<agent>/brain.db` | `~/.xanima/<agent>/brain.db`; `~/.sharpwave` is read until `xanima-server migrate` copies it (never moved or deleted) |
| engine env vars | `SHARPWAVE_DATA_DIR`, `SHARPWAVE_DB_PATH`, `SHARPWAVE_AGENT_ID`, `SHARPWAVE_EMBEDDING_MODEL`, … | unchanged |
| service root / port | `~/.sharpwave/service/`, `127.0.0.1:18790` | unchanged |
| host cron id | `openwave:consolidation` | unchanged (rename deferred) |
| tools | 16 `brain_*` | 42 `brain_*` at 0.7.0 (schema v28); names unchanged and permanent |
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
It is a private workspace package, so it does not come from npm: every Caelza
release carries it built as `caelza-mind-<version>.tgz`, and `sh mind/install.sh`
(Termux or a Linux hub) looks the asset up, checks its `.sha256`, installs it
under `~/.local/share/caelza/mind` with `npm install --omit=dev` (the two native
sqlite modules come prebuilt for Linux and are built on Termux) and writes the
`caelza-mind` launcher; `CAELZA_SERVICE=1` adds the Termux:Boot script or the
systemd user unit that starts it after a reboot. On Windows,
`mind/windows-install.ps1` (`irm … | iex`, Node.js 22) does the same into
`%LOCALAPPDATA%\Caelza\mind` with a `caelza-mind.cmd` launcher beside
`caelza.exe`, mints the Runtime's tokens into `%USERPROFILE%\.xanima\tokens`
and sets `memory.backend = "xanima"` when the Runtime is installed and not
running; `CAELZA_SERVICE=1` adds a Startup-folder shortcut, and the Start
menu's Caelza starts the Mind before the Runtime once the launcher exists. `mind/pack.sh` makes the same
tarball from the commit the manifest pins (`service_commit`; while the xanima
repo is private the fetch needs `CAELZA_MIND_TOKEN`, a token with read access
to it, which release.yml takes from the `XANIMA_READ_TOKEN` secret). This is exactly the endpoint xanima's **remote brain
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
| `turn_context_for_agent` (every turn, ahead of the recalled entries) | `brain_turn_context` with `query`, `session_key`, `owner_turn` | the agent's standing context as the service's own host shows it: `[BRAIN: identity]`, `[BRAIN: active goals]`, the `[BRAIN: goals]` note, `[BRAIN: now]` (the current task); it opens the `[Memory context]` block, re-rendered every turn and never stored in history, so it outlives context compaction; capped by `turn_context_max_chars`; the note ids it carries are acked on the next assistant auto-save; a read-only token (Cael's) is told once and skipped |
| `recall(query)` (every turn, context assembly) | `brain_query` with `format = json`, `scope` from config | private + shared, fused by the service; confidence and `created_at` carried into the entry; empty or `*` queries recall nothing (the service needs a query) |
| `store` of an auto-saved turn (`conversation`) | `brain_episode_append` | role from the key (`user_msg_*` → user, `assistant_resp_*` → assistant); the service's own noise filter drops heartbeat / cron / `NO_REPLY` turns |
| `store` of a fact (`core`, `daily`, custom) | `brain_write` | label = key; `core` → `semantic`, `daily` → `episodic`, a custom category that names a node type is used as is; importance passes through, pinned → 1.0 |
| `get` / `forget` by key | `brain_query` on the label, then `brain_forget` | the newest node with that exact label |
| `count` / `stats` | `brain_stats` | nodes per brain and per type |
| `health_check` | `GET /health` | no token |
| `list` | none | the service has no enumerate-everything call; `caelza memory list` is empty on this backend |
| an agent with no token file | `brain_provision_agent` with `agentId`, called with the provision-scoped token in `provision_token_file` | the service makes the agent's brain and mints its token (the scopes in the service's `provisioning.scopes`, `read, write, shared-write` by default); the backend writes `~/.xanima/tokens/<agent>.token` owner-only and carries on, so a new `[agents.<alias>]` needs no manual mint; loopback only, by the service's rule; a failure is said once and the usual "no token" error names both ways out |

Selected with `[memory] backend = "xanima"`; `[storage.xanima.<alias>]` holds
`url` (default `http://127.0.0.1:18790`), `token_file`
(`~/.xanima/tokens/{agent}.token`, one token per agent alias) or a single
`token`, `agent` (the brain for operations that name no agent), `scope`,
`timeout_secs`, `turn_context` (default true) with `turn_context_max_chars`
(1500), and `provision_token_file` (`~/.xanima/tokens/provision.token`; `""`
turns provisioning off). A bare `backend = "xanima"` with no storage block uses
those defaults. Agents: the `AgentScopedMemory` wrapper passes the agent alias,
the backend picks that alias's token, so the service's private brains and the
runtime's isolation agree; recall across granted siblings
(`workspace.read_memory_from`) queries each sibling's brain with its own token
and skips siblings that have none; the standing context is always the bound
agent's own. Sleep stays in the service: the runtime runs no consolidation
timers and reads what the service dreamt.

Mint tokens once per agent, or once for the provisioner and let the backend
mint the rest:

```sh
# caelza-mind is the launcher mind/install.sh writes; from a checkout it is node packages/server/dist/cli.js
caelza-mind token mint --agent main --scopes read,write --json | jq -r .token > ~/.xanima/tokens/main.token
caelza-mind token mint --agent cael --scopes read       --json | jq -r .token > ~/.xanima/tokens/cael.token
# or: one provision-scoped token, and every new agent gets a brain on first use
caelza-mind token mint --agent provisioner --scopes provision --json | jq -r .token > ~/.xanima/tokens/provision.token
```

`brain_turn_context` needs the `write` scope: an agent on a read-only token
(Cael, as minted above) gets recall but no standing context, which the backend
says once in the log and then stops asking. A provisioned token carries the
service's default scopes, so a provisioned Cael would get the header too.

`caelza-mind.example.toml` has the block; `caelza memory stats` against a
running service is the smoke test, and the memory crate's ignored live test
(`cargo test -p caelza-memory --lib -- xanima::tests::live --include-ignored`
with `CAELZA_XANIMA_E2E_URL`, `CAELZA_XANIMA_E2E_TOKEN_FILE` and, to exercise
provisioning, `CAELZA_XANIMA_E2E_PROVISION_TOKEN_FILE`) walks store, recall,
the standing context, the ack and forget against the real service. The
contract the backend speaks was read from the service's source
(`packages/server/src/{tools,provision,tokens}.ts` at 0.7.0): the tool
arguments, the JSON keys of the replies (`identity`, `activeGoals`, `text`,
`now`, `noteIds`; `status`, `token`), the scopes and the loopback rule.

Still open from xanima's host-side behaviour: the last-24h digest. The
system-noise filter is already in the service (`brain_episode_append` skips
heartbeat polls, cron wakes and `NO_REPLY`), so the runtime's own heartbeats
and cron turns never become memories.

### Later

- **One Mind for every device: shipped** (the consumer shape of the shared
  brain). The Memory page's *Your other devices* card, on the device that
  runs the service, writes this machine's home-network or Tailscale address
  into the service's `config.json` (`tailnetHosts`, its own non-wildcard
  bind policy), mints a `caelza-share` token for the default agent into its
  `tokens.json` (the hash only, as `token mint` does; a fresh token on every
  Share) and shows a join code (`caelza-mind:` + base64url of the service
  URL, the agent and the token); *Stop sharing* removes the address and
  revokes every `caelza-share` token. The *Join a Mind on another device*
  card on the other device probes the code (`POST /api/mind/probe`:
  `/health`, then `brain_stats` with the token) and writes
  `[storage.xanima.default]` (`url`, `token` encrypted at rest, `agent`,
  provisioning off) and `memory.backend = "xanima"` through the config API;
  the service's own address needs one restart, the joined Runtime one
  restart. Gateway routes `GET|POST|DELETE /api/mind/share` and
  `POST /api/mind/probe` in `runtime/overlay/crates/caelza-gateway/src/api_mind_share.rs`.
- **The fleet shape.** One service, many named agents (the phone's, a hub's,
  a Pi's): private brains per agent, the shared brain and rooms for what the
  fleet knows together. The service already models this (`brain_room`,
  `brain_publish`, `brain_subscribe`); the Memory page's share is the
  one-agent case of it.
- **Skill evolution → Caelza skills.** `skillEvolution` generates a skill file
  when a pattern recurs; write them into the runtime's skill-bundle directory
  so the agent grows its own playbooks.
- **Memory page in the dashboard: shipped** (M4 phase 2a). `/memory` shows the
  brains (`brain_stats`), the status counts and attention lines
  (`brain_status`), recall by query with a forget action (`brain_query`,
  `brain_forget`) and the review queue with accept / reject (`brain_review`;
  deciding needs an admin-scoped token on the service). The browser never
  holds a brain token: the gateway's `/api/mind/status|recall|forget|review`
  (`runtime/overlay/crates/caelza-gateway/src/api_mind.rs`) resolve the
  active `xanima` storage entry and call the service with the agent's token
  file. Still to port from xanima's control UI: graph browse (`brain_expand`)
  and identity history.

## Files

```
mind/
├── README.md                  this
├── caelza-mind.example.toml   MCP server blocks for paths A and B, the native backend's block
├── pack.sh                    builds xanima-server at the manifest's pinned commit and packs it as caelza-mind-<version>.tgz (release.yml runs it)
└── install.sh                 installs that tarball from the release as `caelza-mind` (Termux or a Linux hub), optionally as a boot service
```
