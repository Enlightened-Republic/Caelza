# Agent — Design Spec

**Status:** Reference (the design the reference agent "Niba" was built from)

> This is the original design doc. It uses "Niba" as the agent's name and a
> T-Mobile REVVL 7 5G as the target device throughout — read those as the
> reference instance; the framework is device- and name-agnostic.

---

## 1. What the agent is

The agent is a standalone autonomous process that lives on a dedicated phone (reference
device: T-Mobile REVVL 7 5G). The phone is the agent's body: its camera, mic, speaker,
network stack, and shell. The agent talks to
its owner over Telegram (primary) and, in v2, through a pair of HeyCyan smart glasses as a
hands-free voice interface. Wake word for the voice interfaces is **"Hey Niba"**.

Niba can control its own phone and pair with and control other Android devices over ADB —
the driving use case is remote tech support ("grandma's phone has a virus popup") without
travelling to the device.

Niba can rewrite its own code while running, fully autonomously, with no human approval
gate. A supervisor process it cannot touch keeps it recoverable.

This project is unrelated to any other agent or system on the owner's machines. It shares
no memory, config, identity, or credentials with them beyond model API access.

## 2. v1 scope and non-goals

**In scope for v1 (this spec, one implementation plan):**

- Supervisor with git-backed auto-rollback
- Agent loop driven by Telegram
- MiniMax M3 as the model, via its OpenAI-compatible API
- Tool modules: `self`, `device` (ADB), `sensors` (termux-api), `shell`
- Memory via SharpWave (MCP server, sidecar)
- Autonomous self-modification (probe + promote + rollback)
- Offline degradation
- First-boot setup script/runbook
- Test suite, supervisor-heavy

**Explicitly deferred to v2 (documented in §14, not built now):**

- HeyCyan glasses voice + camera interface
- Capability playbook skills (debloat, malware removal, new-phone setup, diagnostics)
- Multi-device fleet management beyond ad-hoc pairing
- Any local model / offline reasoning
- Root

**Never in scope:**

- Sharing state with the owner's other agents
- A human approval gate on self-modification (by explicit decision — the supervisor is
  the safety mechanism instead)

## 3. Hardware and environment (measured 2026-08-29)

| Property | Value |
|---|---|
| Device | T-Mobile REVVL 7 5G (`TMRV075G`, codename CypressPoint, Wingtech ODM) |
| OS | Android 16, SDK 36, security patch 2026-04-05 |
| Arch | arm64-v8a, Qualcomm SM6450 (Snapdragon 4 Gen 2) |
| RAM | 5.3 GB total; ~3.3–3.6 GB available after debloat + reboot; 3 GB zram swap |
| Storage | 128 GB, ~78 GB free |
| Bootloader | **Locked** (`ro.boot.flash.locked=1`, verifiedboot green) → no root |
| Pre-installed | Tailscale (kept). Debloat completed — see `docs/debloat-log.md` |

**Consequences baked into this design:**

- **No root.** Every privileged action goes through the non-root ADB path (Niba runs
  `adb` against its own phone via wireless-debugging loopback) or an accessibility service.
- **RAM is the binding constraint.** No local model. No local embedding model. The phone
  runs only: Python (agent), Node (SharpWave), Node (`mmx`, invoked not resident),
  Termux base. Everything heavy is a network call.
- **Wi-Fi only** (SIM not connected and will not be). "On the go" means Niba needs Wi-Fi
  wherever it goes, or a hotspot. Tailscale gives it a stable address anywhere it has
  internet.

## 4. Architecture

```
REVVL 7  (Termux, Tailscale, Android 16, non-root)                    Telegram  <-->  owner

  Termux:Boot ─► supervisor.py            [IMMUTABLE — Niba can never edit this file]
                  │  owns the git repo, tracks the "last-good" commit
                  │  spawns + monitors children, health-probe, auto-rollback
                  │  never calls the model — pure mechanism
                  │
                  ├─► sharpwave            (npx -y sharpwave, Node)  ──MCP(stdio)──┐
                  │      DB: ~/.niba/sharpwave/   [outside the repo → rollback-safe]│
                  │      embeddings: OpenRouter (remote), FTS-only fallback         │
                  │                                                                │
                  └─► agent  (Python child process)          [self-rewritable]     │
                        ├─ loop.py      Telegram poll → context → model → tools    │
                        ├─ model.py     MiniMax M3, OpenAI-compatible, Bearer auth  │
                        ├─ memory.py ───────────────── MCP client ─────────────────┘
                        ├─ prompt.md    system prompt (editable by Niba)
                        └─ tools/
                            ├─ self.py     read/write/commit own code, request restart
                            ├─ device.py   ADB: own phone (loopback) + paired devices
                            ├─ sensors.py  termux-api: camera, mic, location, notifs, TTS
                            └─ shell.py    Termux shell (timeout + output cap)
```

### The immutable-anchor principle

`supervisor.py` is small (~150–200 lines), does no model calls, and is on `self.py`'s
hard deny-list. It is the only guaranteed-sane process. Everything else — the loop, the
model wrapper, the tools, the system prompt — is fair game for Niba to rewrite. No matter
how badly a self-edit breaks the agent, the supervisor holds a known-good git commit and
can restore it.

SharpWave is a **second anchor**: it runs from `npx`, its code is not in Niba's repo, and
its database lives outside the repo. A self-edit can break `memory.py` (Niba's client
wrapper), which the probe catches, but it cannot corrupt the memory store itself.

## 5. Components

### 5.1 `supervisor.py` — immutable

**Purpose:** keep Niba alive and recoverable without human intervention.

**Responsibilities:**

- On start: verify the git repo is clean; if no `last-good` ref exists, set it to current `HEAD`.
- Start the SharpWave sidecar (`npx -y sharpwave`), restart it if it exits. Never touch its DB.
- Start the `agent` child; capture stdout/stderr to rotating logs in `~/.niba/logs/`.
- **Heartbeat:** the agent must touch `~/.niba/run/heartbeat` at least every 30 s. A
  heartbeat older than 60 s means the agent is force-restarted — *except* during a grace
  window of `HEARTBEAT_MAX_AGE` seconds after each (re)start, so a freshly launched agent
  isn't thrashed before it writes its first beat.
- **Restart request:** when the agent writes `~/.niba/run/restart-request` (JSON: `reason`,
  `commit`), the supervisor:
  1. Confirms the agent already committed (`git log` shows the named commit).
  2. Starts a new agent child with `--probe`.
  3. The probe child runs a self-check: imports every module, validates Telegram token,
     validates M3 auth, connects to SharpWave, writes `probe-ok` and exits 0 within 60 s.
  4. On `probe-ok`: `git tag -f last-good <commit>`, start the real agent child, delete the
     request file, send a Telegram note ("updated: <reason>").
  5. On probe failure/timeout: `git reset --hard last-good`, restart the agent from
     last-good, send Telegram alert with `reason`, the failing diff, and the probe error.
- **Crash-loop guard:** ≥3 non-zero agent exits within 5 minutes → treat as a bad state,
  `git reset --hard last-good`, restart, alert. If last-good *itself* then crash-loops, the
  supervisor latches into a terminal `halted` state: it sends the "manual fix needed" alert
  exactly once and thereafter idles (no more restarts, alerts, or exit-counting) until the
  process is restarted by hand. The `_last_good_looping` latch is cleared on any successful
  promote so a newly promoted commit still gets the normal rollback path if it crashes.
- **State isolation:** all Niba state (config, logs, run files, SharpWave DB, tmp) lives
  under `~/.niba/`. The supervisor sets `NIBA_HOME=~/.niba` before spawning children; no
  component reads from or writes to a shared/default location.

**Interface:** none (top-level process). Controlled by files under `~/.niba/run/`.

**Dependencies:** `git`, Python stdlib only. No third-party packages, to minimise the
chance the supervisor itself fails to start.

### 5.2 `agent/loop.py`

**Purpose:** the main agent loop.

**Flow per iteration:**

1. Long-poll Telegram `getUpdates` (text, photo, voice note, document).
2. Download any media to `~/.niba/tmp/`.
3. Assemble context: system prompt (`prompt.md`) + last N turns from local session log +
   `memory.recall(<the user message>)` results.
4. Call `model.complete(messages, tools)`.
5. If the response has tool calls: dispatch each through the tool registry, append the tool
   results (and the full assistant message incl. `tool_calls` and `reasoning_details`),
   loop back to step 4.
6. If the response is a user-facing message: send it to Telegram, append to the session
   log, `memory.remember(<episode summary>)`.
7. `memory.flush_pending()`. Repeat. (The heartbeat file is written by an independent
   daemon thread every 15 s — see §5.1 — not from this loop, so a slow turn can't starve it.)

**Resilience:** the Telegram `offset` is persisted to `~/.niba/run/offset` *before* each
turn runs (and re-seeded from it on start, tolerating a corrupt file), so a message that
crashes the agent is skipped on restart rather than redelivered forever. Each turn is
wrapped: `ModelPaused`/`ModelQuotaExhausted`/`ModelAuthError`/`httpx.HTTPError` reply with
a status and continue; any other exception replies "hit an error on that one", increments a
counter, and continues — but re-raises after 3 consecutive failures so a systematically
broken build still reaches the supervisor's crash-loop guard.

**Modes:** `--probe` (self-check and exit), normal (loop forever).

**Media:** photos and screenshots pass to M3 as image parts (M3 is natively multimodal).
Voice notes are transcribed first — v1 uses M3/MiniMax speech-to-text via `mmx` or the
speech endpoint; if unavailable, reply asking for text.

**Dependencies:** `httpx` (Telegram + model), `mcp` (SharpWave client). Small.

### 5.3 `agent/model.py`

**Purpose:** wrap MiniMax M3.

- Endpoint: `https://api.minimax.io/v1/chat/completions`, OpenAI-compatible shape.
  (Anthropic-compatible `https://api.minimax.io/anthropic` also exists; not used.)
- Auth: **`mmx` OAuth device grant.** The MiniMax Plus plan exposes no API-key button in
  the account UI; the supported path is the MiniMax CLI (`mmx`, a Node package), which runs
  an OAuth Device Authorization Grant (RFC 8628 + PKCE) and writes `access_token` +
  `refresh_token` to `~/.mmx/config.json`. Usage draws on the Plus token pool (~1.7 B/month).
- `model.py` reads the token from `~/.mmx/config.json`, sends it as
  `Authorization: Bearer <access_token>` against `/v1`, and refreshes via `refresh_token`
  on 401. **Fallback:** if `/v1` rejects the raw token, shell out to `mmx` per call (it
  owns auth + refresh) — slower but robust. Which path applies is confirmed in
  implementation (§15).
- Keep total input under 512 K tokens per call — M3 bills a higher long-context rate above
  that threshold. The loop caps history growth regardless.
- Tool calling: modern `tools` field (not legacy `function_call`). M3 is trained for
  long-horizon tool loops.
- **Critical:** append the complete assistant message — including `tool_calls` and
  `reasoning_details` — to history before adding tool results, to preserve M3's interleaved
  thinking between rounds.
- Token accounting: log prompt/completion tokens per call to `~/.niba/logs/tokens.jsonl`.
  Maintain a rolling monthly counter. Plan quota is ~1.7 B tokens/month (MiniMax Plus).
- **Per-hour call cap** (config, default e.g. 120 calls/hour) → on breach, pause model
  calls, alert, resume next hour. Guards against a self-modification spiral.

**Interface:** `complete(messages: list, tools: list) -> AssistantMessage`.

### 5.4 `agent/tools/self.py`

**Purpose:** the self-modification surface.

| Tool | Behaviour |
|---|---|
| `read_file(path)` | Read a repo file. |
| `write_file(path, content)` | Write a repo file. |
| `list_tree()` | List the repo tree. |
| `run_tests()` | Run `pytest` in the repo, return results. |
| `commit(message)` | `git add -A && git commit`. |
| `request_restart(reason)` | Write `~/.niba/run/restart-request`; the supervisor takes over. |

**Hard deny-list (path check, not prompt guidance):** `_resolve()` raises `PermissionError`
for anything outside the repo root, anything under `.git/`, anything under expanded
`~/.mmx/`, and `~/.niba/config.toml`. `niba/supervisor.py` is blocked by BOTH an explicit
resolved-path equality check (`p == repo/"niba"/"supervisor.py"`) AND a case-folded
`*supervisor.py` suffix check — the suffix check is the load-bearing cross-platform guard,
since `Path.resolve()` does not normalise case on every OS. File reads/writes pin
`encoding="utf-8"`. A blocked operation returns an error string to the model.

**Recommended self-modification protocol (in the system prompt):** edit → `run_tests()` →
`commit()` → `request_restart()`. The supervisor's probe is the backstop if Niba skips the
test step.

### 5.5 `agent/tools/device.py`

**Purpose:** ADB control of Niba's own phone and of paired external Android devices.

**Every tool takes `device=` (default `"self"`).** `"self"` is the phone's own loopback
ADB connection; any other value is a name from the registry (a paired remote).

**Own phone (`"self"`):** Wireless debugging is enabled and paired once (by `niba setup`,
or over USB during first bring-up — the pairing persists across reboots). On start
`device.py` runs `adb connect 127.0.0.1:<port>` (re-pairs only if the persisted pairing is
gone). Non-root; gives shell-user reach: `pm`, `settings`, `input`, `dumpsys`, `am`,
`screencap`.

**External devices:** `pair(name, host, code)` runs the wireless-debug pairing flow over
LAN/Tailscale and adds an entry to `~/.niba/devices.json` (`name → {host, paired_at,
last_seen, notes}`) — a **plain JSON file**, not SharpWave: a device registry needs
reliable enumeration and exact lookup, which SharpWave's fuzzy-prose query API can't give.

| Tool | Notes |
|---|---|
| `device_list()` | `devices.json` + live `adb devices` reachability. |
| `device_pair(name, host, code)` / `device_unpair(name)` | Wireless-debug pairing; edits `devices.json`. |
| `device_shell(cmd, device="self")` | `adb -s <serial> shell`, output capped ~8 KB. |
| `device_screencap(device="self")` | Returns a PNG for the model. |
| `device_ui_dump(device="self")` | `uiautomator dump` for structured screen state. |
| `device_input(action, *, device="self", ...)` | `input tap/text/swipe/keyevent`. |
| `device_packages(flags="-3", device="self")` | e.g. `-3` third-party, `-s` system. |
| `device_uninstall(pkg, device="self")` / `device_disable(pkg, device="self")` | `pm uninstall --user 0` / `pm disable-user`. Reversible-first: prefer `disable`. |
| `device_appops(pkg, op, mode, device="self")` | Revoke overlay/notification/etc perms. |
| `device_logcat(filter=None, lines=200, device="self")` | Bounded log pull. |
| `device_settings(ns, key, value=None, device="self")` | `settings get/put`. |

**Safety:** `device_uninstall` / `device_disable` / `device_settings put` / `device_appops`
require the model to pass a `reason` and are appended to `~/.niba/logs/device-actions.log`.
Before any package removal on ANY device, a snapshot of `pm list packages -f` is written to
`~/.niba/snapshots/<device>-<ts>.txt` so it can be restored.

### 5.6 `agent/tools/sensors.py`

Thin wrappers over `termux-api`:

`camera_photo(facing)`, `mic_record(seconds)`, `location(accuracy)`,
`notification_list()`, `tts_speak(text)`, `clipboard_get()` / `clipboard_set(text)`,
`battery_status()`, `torch(on)`.

Each returns a permission-diagnostic error if the underlying Android permission is not
granted (the setup script grants them up front).

### 5.7 `agent/tools/shell.py`

`run(cmd, timeout=60, cwd=None)` — runs in Termux, merges stdout/stderr, caps output at
~8 KB, always returns exit code. This is Niba's general-purpose escape hatch (ssh, curl,
git, python, nmap, tailscale).

### 5.8 `agent/memory.py`

MCP stdio client to the SharpWave sidecar. `Memory` is a pure class taking a
`call_tool(name, args) -> dict` callable; the callable is produced by
`spawn_sharpwave_session()`, which also carries a **translation adapter** — the shipped
`sharpwave@0.2.x` MCP tools use a different arg schema than `Memory`'s protocol and return
human-readable prose, not JSON. The adapter (all `# pragma: no cover`, verified by a live
round-trip test) maps:

| `Memory` call | → sharpwave@0.2.x | prose parsed back to |
|---|---|---|
| `remember(text, links)` → `brain_write` | `{type:"semantic", label:text[:60], content:text}` (`links` dropped — sharpwave auto-links; real linking needs `brain_link`) | `Written: node <uuid> …` → `{"id": <uuid>}` |
| `recall(query, k)` → `brain_query` | `{query, limit:k}` | ranked prose listing → `{"results":[{id,text,score}]}`; `No matching nodes found.` → `[]`; unparseable lines still emitted as `{text}` |
| `link(a, b, rel)` → `brain_link` | `{from_id:a, to_id:b, edge_type:rel}` (non-enum `rel` → `"associates"`) | — |
| `supersede(id, text)` → `brain_supersede` | `{old_node_id:id, new_content:text}` | — |

`Memory.remember` swallows any exception, queues the text in-memory, and returns `""`;
`Memory.flush_pending()` (called once per poll cycle by the loop) retries the queue. The
queue is unbounded and not persisted — an extended outage loses nothing until the process
restarts.

SharpWave runtime (as shipped, `sharpwave@0.2.1`):

- Installed globally (`npm i -g --allow-scripts=better-sqlite3 sharpwave`), run as the
  `sharpwave` bin — `npx -y` fails on Termux (the bin's `#!/usr/bin/env node` shebang has
  no `/usr/bin/env`).
- **DB path is `~/.sharpwave/default/brain.db`** — 0.2.1 ignores the `SHARPWAVE_DB` env we
  pass. Still outside the repo (rollback-safe); the spec's earlier `~/.niba/sharpwave/`
  is aspirational until SharpWave honors the env var.
- The agent process owns the one SharpWave MCP stdio server (no supervisor sidecar — two
  on one SQLite DB fought for the lock). `NIBA_NO_SHARPWAVE` makes the agent skip it.
- `mcp` is pinned `<2` (2.x pulls a `cryptography` Rust build broken on Termux/py3.14).
- Embeddings: SharpWave's own default (FTS + spreading-activation on-device); the
  OpenRouter embedding hook is available but not wired in v1.

MiniMax's own embeddings endpoint (`embo-01`) is not used — non-standard shape.

## 6. Data flows

### 6.1 Normal request

```
Telegram "what's my battery / remind me to call the landlord at 5"
 → loop: context + recall → M3
 → M3 calls sensors.battery_status() / decides to store a reminder episode
 → M3 returns a message → Telegram + memory.remember(...)
```

### 6.2 Remote Android fix

```
Telegram "grandma's phone keeps popping a virus warning" + screenshot
 → M3 (reads the image)
 → device.list_devices() → grandma's phone was paired earlier over Tailscale
 → device.screencap + device.shell("dumpsys window | grep mCurrentFocus")
 → M3 identifies the foreground package as junk
 → device.list_packages(-3) to confirm it was sideloaded
 → snapshot taken → device.uninstall(pkg) + device.appops(pkg, SYSTEM_ALERT_WINDOW, deny)
 → memory.remember("grandma phone: removed com.junk.xyz, overlay scam, 2026-..")
 → Telegram: what was done + how to restore
```

### 6.3 Self-modification

```
Telegram "you keep dropping voice notes, handle them"
 → M3 → self.read_file("agent/loop.py") → sees the gap
 → self.write_file("agent/loop.py", ...) → self.run_tests() → self.commit("voice notes")
 → self.request_restart("voice note handling")
 → supervisor: probe new version
     ok  → tag last-good, run it, Telegram "updated: voice note handling"
     bad → git reset --hard last-good, run it, Telegram "that change broke on <error>, rolled back, diff attached"
```

## 7. Self-modification state machine (supervisor)

```
        ┌────────── running (last-good) ──────────┐
        │                                         │
 restart-request                             3 crashes / 5 min
        │                                         │
        ▼                                         ▼
   spawn probe ──ok──► tag last-good ──► running (new)
        │                                         │
     fail/timeout                          3 crashes / 5 min
        │                                         │
        ▼                                         ▼
  reset --hard last-good ──► running (last-good) ──► if still crash-looping:
                                                     stop, alert, idle
```

## 8. Configuration and secrets

`~/.niba/config.toml` (not in the repo, on `self.py` deny-list):

```toml
[telegram]
bot_token = "..."
owner_chat_id = 123456789

[minimax]
# auth is handled by `mmx` (writes ~/.mmx/config.json); nothing needed here normally
mmx_config_path = "~/.mmx/config.json"

[openrouter]
api_key = "..."          # for SharpWave embeddings

[limits]
model_calls_per_hour = 120
monthly_token_budget = 1_600_000_000
```

Secrets never enter git, never enter Telegram messages, never enter model context (the
loop redacts known secret values from tool output before sending to M3).

## 9. Error handling

| Failure | Handling |
|---|---|
| Bad self-edit | probe fails → auto-rollback to last-good + diff + error to Telegram |
| Crash loop (3× / 5 min) | rollback to last-good; if last-good also loops, stop + alert + idle |
| No internet | model calls skipped; `device`/`shell`/`sensors` still run; episodes queue as pending `remember()`; replies deferred with a note |
| M3 auth expired | refresh via `refresh_token`; on failure, alert + offline mode until re-auth |
| M3 quota exhausted | offline mode + alert; resume when quota resets |
| Per-hour call cap hit | pause model calls, alert, resume next hour |
| SharpWave down | supervisor restarts it; agent runs memory-less and says so |
| Embedder unreachable | SharpWave silently falls back to FTS |
| External ADB pairing dropped (device rebooted) | `device.py` reports "needs re-pair", never hangs |
| Android kills Termux | `Termux:Boot` + `termux-wake-lock` + battery-opt whitelist + `termux-job-scheduler` re-check every 15 min as backstop |
| termux-api permission missing | tool returns a permission diagnostic; setup script pre-grants |

## 10. Security model

Niba ingests untrusted text constantly (Telegram messages, screen contents, notifications,
web pages via `shell`). Assumptions:

- **Prompt injection will happen.** The supervisor + git + probe + rollback make a
  hijacked self-edit recoverable. The `self.py` deny-list means injection cannot reach
  `supervisor.py`, `.git/`, or the secrets file.
- **Blast radius is the phone.** Non-root, isolated `~/.niba/`, no access to the owner's
  PC except what `shell`/`ssh` explicitly does. External devices require an explicit
  one-time pairing the owner performs.
- **Secrets are redacted** from tool output before entering model context.
- **The owner is the only Telegram peer** (`owner_chat_id` allow-list; messages from any
  other chat id are ignored).
- **Destructive external actions are logged and snapshotted** (package removals).
- Known residual risk: a determined injection during a self-mod turn could ship a
  malicious-but-passing-probe change. Mitigation is the Telegram "updated: <reason>" note
  on every promote — the owner sees every change and can tell Niba to revert.

## 11. Offline behaviour

No model, no reasoning. Niba can still: run queued/scripted `device` and `shell` actions,
read sensors, record episodes to a pending queue, and answer with a canned "offline, will
process when back online". On reconnect it flushes the episode queue and processes deferred
messages oldest-first.

## 12. First-boot setup

A `niba setup` command (`scripts/setup.py`) drives this: it runs the non-interactive steps
itself and walks the owner through the pieces that need a human (Android toggles, browser
logins). Full runbook in `docs/setup.md`. Steps, marked **[auto]** / **[prompt]**:

1. **[manual, before setup]** Install **Termux**, **Termux:API**, **Termux:Boot** from
   F-Droid (not Play Store). Then run `niba setup` inside Termux.
2. **[auto]** `pkg install python nodejs git openssh termux-api`; `npm i -g` the MiniMax CLI.
3. **[auto]** `termux-setup-storage`; request the camera/mic/location/notification perms.
4. **[auto]** Add Termux to the battery-optimisation whitelist.
5. **[prompt]** Owner enables Developer Options → Wireless debugging; setup then pairs
   Termux's `adb` to `127.0.0.1` and stores the port.
6. **[prompt]** `tailscale up` (owner completes the Tailscale auth in the app).
7. **[prompt]** `mmx auth login` — setup launches it; owner opens the shown URL + code in
   any browser (phone or PC) and signs in. Setup confirms `~/.mmx/config.json` exists.
8. **[prompt]** Owner pastes the Telegram bot token and their OpenRouter key; setup writes
   `~/.niba/config.toml` and captures `owner_chat_id` from the first message to the bot.
9. **[auto]** `git clone` / `git pull` the Niba repo to `~/niba`; `pip install`.
10. **[auto]** Install the `Termux:Boot` script that runs `python ~/niba/supervisor.py`.
11. **[auto]** Start the supervisor; verify the Telegram "Niba online" message.

## 13. Testing

| Target | Approach |
|---|---|
| `supervisor.py` | **Most coverage.** Runs on the PC. Fake agent children that exit-0 / exit-1 / hang / emit `probe-ok` / crash-loop. Assert: promote on probe-ok, rollback on probe-fail, rollback on crash-loop, idle on last-good crash-loop. |
| `agent/tools/device.py` | Against a real Android emulator on the PC (`adb` works identically). |
| `agent/tools/sensors.py`, `shell.py` | Mock `subprocess` / `termux-*` binaries. |
| `agent/model.py` | Mock the HTTP endpoint; assert tool-call round-tripping preserves `reasoning_details`; assert token accounting and the per-hour cap. |
| `agent/loop.py` | Integration test: mock Telegram + a scripted model returning canned tool calls; assert the full turn incl. `remember()`. |
| `agent/memory.py` | Against a real SharpWave instance with a temp DB. |
| Future capability modules | Must pass "imports + boots + heartbeat" (the probe) or they are auto-rolled-back; the system prompt instructs Niba to write a smoke test per module. |

## 14. Deferred to later plans

### 14.0 Plan 2 — device & sensor tools (NEXT; brainstormed 2026-08-29)

Additive tool modules against the shipped v1 architecture. One plan, three phases:

- **Phase A — `shell.py` + `sensors.py`** (no ADB dependency): `shell_run`; the
  `termux-api` sensor wrappers (§5.6). Fast, self-contained.
- **Phase B — `device.py`** (§5.5): the ADB tool surface (self + paired remotes),
  `~/.niba/devices.json` registry, self-ADB connect-on-start, the pairing flow, the
  dangerous-op logging + pre-removal snapshot.
- **Phase C — `scripts/setup.py`** (`niba setup`): automates the manual bring-up done on
  2026-08-29 — Termux pkgs + `sharpwave` global install, the mmx/telegram/openrouter
  prompts, `config.toml`, self-ADB pairing, the `Termux:Boot` script.

Decisions from the brainstorm: registry is a JSON file (not SharpWave); every `device_*`
tool takes `device="self"` by default; both self and remote control from day one; build
`setup.py` now (the "package a mobile agent" goal makes it worth it).

Self-ADB pairing needs a one-time human step (read a code from the Wireless-debugging
dialog); `niba setup` walks the owner through it, and it can also be pre-done over USB
during first bring-up.

### 14.1 HeyCyan glasses interface

Goal: "Hey Niba" hands-free voice + wearable camera, same brain as Telegram.

Findings (2026-08-29):

- Glasses are Bluetooth 5.3, cheap OEM ("CY" series). Stock assistant is ChatGPT routed
  through the closed HeyCyan app → their cloud. **The HeyCyan app has no custom-endpoint
  setting** (confirmed) — Niba cannot be slotted in via the app.
- A community BLE SDK ([ebowwa/HeyCyanSmartGlassesSDK], Kotlin/Swift, proprietary licence)
  exposes photo/video/audio-record triggers and battery/time — **not** mic streaming,
  button events, wake word, or TTS playback. BLE service UUIDs:
  `7905FFF0-B5CE-4E99-A40F-4B1E122D00D0`, `6e40fff0-b5a3-f393-e0a9-e50e24dcca9e`.

Planned approach (own the audio path, bypass the app):

```
glasses ⇄ BT audio (HFP mic + A2DP speaker) ⇄ REVVL ── Niba agent
        ⇄ BLE control (photo trigger, ported to Python `bleak`) ⇄ Niba
   Niba runs an on-device "Hey Niba" wake-word engine (openWakeWord / Vosk) on the BT mic
   → capture → STT → M3 → TTS → BT speaker
   → "take a photo" → BLE trigger → pull image (glasses Wi-Fi module) → M3 vision
```

Requires a **spike first** (glasses paired to the REVVL, hands-on):

1. Do the glasses expose standard HFP/A2DP audio?
2. Can a Termux process capture the BT mic while the glasses are "listening"?
3. Trigger mechanism without the app — wake-word engine vs SCO-activation detection.
4. Feasibility of porting the BLE photo-capture command to Python.

### 14.2 Capability playbook skills

Markdown playbooks Niba loads on demand, backed by
[Universal Android Debloater]'s package lists and the ADB workspace template:

- `debloat.md`, `malware-removal.md`, `new-phone-setup.md`, `android-diagnostics.md`

### 14.3 Other

- Fleet management (named device groups, bulk operations)
- Root, only if a bootloader-unlock path for this exact model turns out to exist
- A local reflex model, only if a future device has the RAM

## 15. Open items to resolve during implementation

1. **Voice-note STT in v1:** confirm MiniMax offers speech-to-text under the Plus plan; if
   not, v1 replies asking for text and STT waits for the glasses spike.
2. **M3 direct-Bearer vs shell-to-`mmx`:** confirm whether the `~/.mmx/config.json`
   `access_token` is accepted directly by `api.minimax.io/v1`. If yes, `model.py` does
   direct HTTP (preferred, lower latency). If no, it shells out to `mmx` per call. The
   setup step (`mmx auth login`) is the same either way.
3. **`mmx` package name / install:** confirm the exact npm package and that it installs
   under Termux's Node, and that the device-code flow can be completed from a PC browser.

**Resolved during review (2026-08-29):**

- **M3 auth mechanism** — `mmx` OAuth device grant. The MiniMax Plus account UI has no
  API-key button, so `mmx auth login` (device-code browser flow) is the path; it writes
  `~/.mmx/config.json`. The owner's MiniMax "oath" is that login.
- **OpenRouter key for embeddings** — reuse the owner's existing key.

**Resolved during Plan-1 implementation (2026-08-29):**

- **SharpWave schema** — the live `sharpwave@0.2.1` MCP tools diverge from the assumed API
  (different arg keys, prose responses). Closed with the `spawn_sharpwave_session` adapter
  documented in §5.8, verified by a live round-trip test. `brain_write` has no `links`
  param; `recall` node ids come back as 8-char prefixes.
- **Loop resilience** — persistent Telegram offset + 3-strike catch-all added to
  `loop.run` (§5.2) so a poison message can't wedge the agent.
- **Supervisor hardening** — heartbeat grace window + terminal `halted` state (§5.1).
- **Self-mod deny-list** — explicit forbidden-path check + case-folding added; the plan's
  `str.endswith` check alone was case-sensitive (§5.4).

## 16. References

- SharpWave — https://github.com/Enlightened-Republic/sharpwave (Plan 1 targeted the
  published `sharpwave@0.2.1`; see the §5.8 adapter table for its real MCP schema)
- MiniMax M3 API — https://platform.minimax.io/docs/guides/text-m3-function-call
- MiniMax CLI — https://github.com/MiniMax-AI/cli
- HeyCyan glasses SDK — https://github.com/ebowwa/HeyCyanSmartGlassesSDK
- Claude Code ADB workspace template — https://www.heyitworks.tech/blog/claude-code-adb-workspace-template/
- hyperdroid-skill — https://github.com/hyperb1iss/hyperdroid-skill
- Universal Android Debloater — https://github.com/0x192/universal-android-debloater
