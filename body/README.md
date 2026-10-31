# Caelza Body as an MCP server (`caelza-body`)

The Body is the device layer: termux-api sensors, ADB control of this phone
and paired phones, a shell, the web tools, and the self-modification tools,
all guarded by the immutable supervisor. Until now only the Python agent loop
could reach them. `caelza-body` serves the same tools over MCP so the
**Runtime** (`caelza`) can drive the phone directly (vision doc §3.1,
milestone M2).

```
caelza (Runtime)  ──stdio──▶  caelza-body serve  ──▶  termux-api / adb / sh / repo
                                  │
                                  └─ $CAELZA_BODY_HOME: devices.json, audit log,
                                     package snapshots, tmp captures
```

Nothing about the tools changed. `caelza_body/agent/tools/*` register into one
registry; the agent loop reads it to build its function-calling schema, and
`caelza-body` reads the same registry to answer `tools/list`. The JSON schemas
pass through untouched, so a `reason` is still required where the Body
requires it, the audit log at `~/.caelza-body/logs/device-actions.log` still
gets every dangerous op, and `device_uninstall` / `device_disable` still
snapshot the package list and abort if the snapshot is empty.

## Install and run

On the phone, in the Body checkout (`install.sh` already does the install):

```bash
pip install -e .            # puts `caelza-body` on PATH
caelza-body probe           # {"ok": true, "tools": 41, ...} and exit 0
caelza-body list-tools      # every tool, its schema and safety hints, as JSON
caelza-body serve           # the stdio server; this is what the Runtime runs
caelza-body serve --http    # the same over Streamable HTTP + a bearer token, for a hub (see Fleet)
caelza-body fleet           # the phones this Body reaches; `fleet join` adds a phone's Body
caelza-body playbooks       # the phone playbooks (body/sops); --install puts them where the Runtime loads SOPs
caelza-body runtime update  # the Runtime binary under the supervisor's guard: fetch a release, verify, probe, swap
```

`--home DIR` overrides the state dir (default `$CAELZA_BODY_HOME`, then
`~/.caelza-body`), `--repo-root DIR` the checkout the `self_*` tools edit, and
`--tools selfmod,sensors,shell,device,web` picks the groups to expose. The
server reads the optional `[firecrawl]` / `[tavily]` / `[searchapi]` keys from
`config.toml` and needs nothing else from it: no Telegram token, no model.

Then merge [`caelza-body.example.toml`](caelza-body.example.toml) into
`~/.caelza/config.toml`: an `mcp.servers` entry named `body`, a bundle, the
grant to `agents.main`, and a risk profile. Tool names reach the agent as
`body__<tool>` (`body__device_list`).

## Tools and their safety class

Every tool is in exactly one class (`tests/test_mcp_server.py` enforces it),
and the class is what the example risk profile is generated from.

| class | MCP hints | Runtime policy | tools |
|---|---|---|---|
| **read-only** | `readOnlyHint`, `idempotentHint` | `auto_approve` | `device_list`, `device_packages`, `device_logcat`, `device_settings`, `device_ui_dump`, `device_screencap`, `device_debloat_plan`, `device_suspects`, `device_foreground`, `device_health`, `sensors_battery`, `sensors_notifications`, `sensors_clipboard_get`, `sensors_location`, `self_read_file`, `self_list_tree`, `web_search`, `web_read`, `web_map`, `web_crawl_result`, `runtime_status` |
| **destructive** | `destructiveHint` | `always_ask` | `device_uninstall`, `device_disable`, `device_settings_put`, `device_appops`, `device_pair`, `device_unpair`, `device_join`, `device_shell`, `shell_run`, `self_write_file`, `self_commit`, `self_request_restart`, `runtime_update` |
| **neutral** | none | the profile's normal policy | `device_input`, `device_tag`, `sensors_camera_photo`, `sensors_mic_record`, `sensors_tts_speak`, `sensors_clipboard_set`, `sensors_torch`, `self_run_tests`, `web_crawl` |

The memory tools (`memory_recall`, `memory_remember`, `memory_reset`) are not
served: the Mind owns memory now ([`../mind/README.md`](../mind/README.md)).

The four `device_*` reads added for the playbooks (M5) live in
`caelza_body/agent/tools/playbook.py` and register with the `device` group:
`device_debloat_plan` (the curated debloat list applied to what is installed),
`device_suspects` (sideloaded apps with the permissions malware wants, scored),
`device_foreground` (what is on screen and who installed it) and
`device_health` (identity, battery, storage, memory, uptime, heat, crashes,
the setup checklist, in one adb call). Their parsing is pure code in
`caelza_body/agent/playbooks.py`, run by `tests/test_playbook_evals.py` over
recorded phone output.

## How calls behave

- **Serialized.** One tool call runs at a time. The Body is one phone, and the
  tool functions block on `adb` / `termux-*` / `sh` for up to minutes, so they
  run on a worker thread while the server keeps answering pings.
- **Errors.** A tool that returns an `error: …` string (the Body's convention)
  comes back with `isError: true` and that text, so the Runtime treats it as a
  failed call rather than a result. Arguments are validated against the schema
  before the Body runs anything.
- **Images.** `device_screencap` and `sensors_camera_photo` return the picture
  as MCP image content plus a text block with the saved path under
  `~/.caelza-body/tmp/`. The Runtime carries image content as an attachment
  on the reply and never shows the base64 to the model. Captures older than
  24 h are pruned on the next start.
- **Timeouts.** `tool_timeout_secs` in the Runtime config caps a call from the
  outside; the Body's own caps are `shell_run` 300 s, `sensors_mic_record`
  60 s, `device_screencap` 30 s.

## Side by side with the agent loop

`caelza-body` does not replace the supervisor or the Python loop. On a phone
that runs Niba today, the supervisor keeps running the loop, and the Runtime
spawns `caelza-body` in addition. Both use the same tool code and the same
state dir, so pairing a device in one is visible in the other. Retiring the
loop (the rest of M2: the Runtime owns the turn, the supervisor guards the
Body code and the Runtime binary) is a per-phone switch once the Runtime is
running there (M1).

## Fleet: a hub and its phones

Deployment shape 2 (vision §3): the Runtime and the Mind on a hub, each phone
running only its Body. Two pieces, both in `caelza_body/fleet.py` (M6):

**Serving.** `caelza-body serve --http` puts the same tools on Streamable
HTTP, the transport the Runtime's `transport = "http"` speaks, behind a
bearer token that is created on first run in `~/.caelza-body/run/http-token`
(mode 0600). It binds loopback unless `--host` says otherwise; the phone's
Tailscale address is the intended otherwise, and the server says so on
stderr. `/health` answers without the token (name, version, tool count) so
reachability and a bad token read differently; `/mcp` refuses anything but
the right `Authorization: Bearer`. Host headers are checked (DNS-rebinding
protection): the bind address and loopback by default, `--allow-host
niba.tail.ts.net` for a MagicDNS name.

**Reaching.** On the hub, `caelza-body fleet join grandma --url
http://100.64.0.9:42618/mcp --token <token> --groups family` (or the agent's
`device_join`) checks the remote answers as a Body, stores the token in
`~/.caelza-body/fleet/grandma.token` (never in `devices.json`) and registers
the phone. From then on **every tool call whose `device` names it runs on that
phone**, as a call on its own `self`: `device_health(device="grandma")`,
`device_uninstall(pkg, reason, device="grandma")`, and, new in M6, the
sensors too (`sensors_battery(device="grandma")`, a photo from her camera).
Images come back as images and are saved under this Body's `tmp/`. The
playbooks, the dashboard and the risk profile do not know the difference: the
`device` in a procedure's trigger payload is `self`, an ADB-paired phone or a
joined Body, and `body__device_uninstall` asks the owner either way. The
remote Body audit-logs and snapshots on its phone as if the agent ran there;
the hub adds one line per forwarded destructive call to `logs/fleet.log`,
with a `token` or `code` argument redacted. Only a tool whose schema has a
`device` argument is forwarded: `device_join(..., device="grandma")` names no
phone to run on, so it stays local and is refused there, and a joined phone's
token never travels in a stray argument. The registry file is re-read when
another process wrote it, so `caelza-body fleet join` beside a running Body
is seen at once and kept by the Body's next save; a name cannot flip between
a paired phone and a joined Body without `device_unpair` first; token files
are created 0600 inside 0700 directories.

**In the app.** The Caelza Android app serves this same Body over HTTP on the
phone it runs on: its `device` group in Kotlin over Shizuku (M7b) and its
`sensors` group through the Android APIs (M7c, answering in `termux-api`'s
shapes), on `127.0.0.1:42618/mcp` behind the same token file layout, audit
log and snapshots, with the same tool names, schemas and classes
(`android/app/src/main/java/tech/enlightenedrepublic/caelza/body/`,
pinned against `caelza-body list-tools` by `scripts/android_body_fixtures.py`
and `tests/test_android_body.py`). The fleet tools stay here: the app's Body
is one phone, and `device_join` from a hub reaches it like any other.

`device_list` shows the fleet with kinds (`self`, `adb`, `http`), reachability
(a remote's `/health`) and **groups**. `device_pair … groups="family"`,
`device_tag`, or `caelza-body fleet tag grandma --groups family` set them; the
Procedures page's Run offers "every phone in family" and starts one run per
phone, each with its own gate. An ADB-paired phone cannot answer a sensor
(there is no termux-api behind `adb`), and `shell_run`, the `self_*` and the
`web_*` tools stay this Body's own.

[`../runtime/caelza.hub.example.toml`](../runtime/caelza.hub.example.toml) is
the hub's Runtime config: the hub's own `caelza-body serve` is the Body the
Runtime talks to, with the joined phones behind it. A phone can also be a
Runtime MCP server directly (`transport = "http"`, `url`, the token in
`headers.Authorization`); its tools then arrive as `body-grandma__<tool>`,
which the Bodies page lists but the playbooks do not name, so the fleet Body
is the recommended path. Keep the HTTP endpoint behind Tailscale or a
firewall: the token is the only lock.

## The Runtime under the guard

Vision §3.5: the Runtime binary is built by CI from this repo
(`.github/workflows/release.yml`), and the supervisor pulls it onto the phone
the way the Body's own code is promoted. `caelza_body/runtime_guard.py`,
stdlib only and as immutable as the supervisor, does the work (M6):

```sh
caelza-body runtime update            # the latest release for this machine (GITHUB_TOKEN for a private repo)
caelza-body runtime update --tag v0.1.0
caelza-body runtime update --archive caelza-0.1.0-aarch64-linux-android.tar.gz   # no network
caelza-body runtime status            # current, last-good, what is installed
caelza-body runtime rollback          # current -> last-good, by hand
caelza-body runtime link              # $PREFIX/bin/caelza -> the current binary
```

`update` finds the release's archive for this target (`aarch64-linux-android`
in Termux), downloads it and its `.sha256`, verifies, unpacks into
`~/.caelza-body/runtime/<version>/` (refusing an archive that escapes its
directory), and **probes** the new binary before trusting it: `caelza
--version` must answer with the release's version, and `caelza gateway start`
on a probe port must serve `/health` within a minute. Only then it snapshots
`~/.caelza` (the config, the agents' files, the shared SOPs and skills; never
the data) into `~/.caelza-body/snapshots/`, points `current` and `last-good`
at the version, and asks the supervisor to restart the Runtime. A binary that
does not hold is deleted and the one running stays current; nothing else is
touched.

The probe runs the new gateway on a **copy** of `~/.caelza` (the config, its
`.secret_key`, the shared SOPs and skills, the agents' files minus their
workspaces) in the work dir: the live dir belongs to the Runtime that is
running, which holds its lock and its data there. The probe also refuses a
probe port that something else already answers on, so a stale gateway can
never vouch for a new binary. `update` moves `current` to the new version and
leaves `last-good` on the version that was running; the supervisor promotes
the new one to `last-good` once it has held for ten minutes. A version that
is current is never reinstalled over itself, and `prune` keeps current,
last-good and the version still running.

The supervisor runs `caelza daemon` from `runtime/current` as a child beside
the agent, restarts it when the guard asks, and on a crash loop points
`current` back at `last-good` and restarts it; a crash loop on last-good
itself halts the Runtime and alerts for a human, the same ladder the Body's
own code gets. A later `runtime update` (or `runtime rollback`) revives a
halted Runtime: its restart request is read first. Before blaming a crash
loop on the binary the supervisor checks whether another Runtime already
answers on the gateway port (a `caelza daemon` started by hand, or by an old
Termux:Boot script): then it halts without rolling back and says so. Whatever
goes wrong inside the Runtime guard is alerted, never raised, so the agent's
own ladder keeps running; Ctrl-C, SIGTERM and an unexpected error all end
with the children stopped. With no runtime installed the supervisor leaves
the Runtime to whatever runs it today (the Termux:Boot script from
`runtime/termux-install.sh`); after the first `runtime update` plus `runtime
link`, that script steps aside (`update` and `link` add the line that exits
when `runtime/current` exists; a fresh install ships with it) and the shell
runs the guarded binary.

## On the dashboard

The Runtime's dashboard has a **Bodies** page (`/bodies`, M4 phase 2b): this
phone and the paired phones with reachability (`device_list`), battery,
whereabouts and notifications (`sensors_battery`, `sensors_location` in quick
mode, `sensors_notifications`), a screenshot of any paired phone and a photo
from this phone's camera (`device_screencap`, `sensors_camera_photo`), the
package list (`device_packages`), and pair / unpair over ADB wireless
debugging (`device_pair`, `device_unpair`). The gateway's `/api/bodies/*`
(`runtime/overlay/crates/caelza-gateway/src/api_bodies.rs`) reads the
`[[mcp.servers]]` entry named `body` (another name works through `?server=`;
any entry whose command is `caelza-body` counts as a Body), keeps one
connection to it for the gateway's lifetime and makes the tool calls with the
Runtime's own MCP client, so the browser never spawns or reaches the Body
directly. A Body started with `--tools` shows only the sections its groups
serve. The page's pair and unpair are the owner's own hand on the phone; the
agent's calls to the same tools still go through the risk profile above.

## The phone playbooks (`sops/`)

Four standard operating procedures for the Runtime's SOP engine, the Airframe
capability playbooks as procedures with approval gates (milestone M5):
`phone-debloat`, `phone-malware-removal`, `phone-new-setup`,
`phone-diagnostics`. Each is a `SOP.toml` + `SOP.md` directory the Runtime
loads as-is; the reads are the playbook tools above, the one step per
procedure that changes the phone carries `requires_confirmation` and parks the
run until the owner approves it on the Procedures page (which gives each a
**Run** that asks which phone), on Home, or over `caelza sop approve`.
`caelza-body playbooks --install` copies them into `~/.caelza/shared/sops`,
`install.sh` does the same on a phone, and `[sop] sops_dir = "shared/sops"`
in the Runtime config loads them. [`sops/README.md`](sops/README.md) has the
table, the gates, the evals and how to run them against an emulator.

The reads behind them err on the owner's side: `device_debloat_plan` reads
who installed each third-party package and sends one the owner installed from
a store to `review` even when the table knows its name as a carrier preload;
`device_suspects` and `device_foreground` read ordinary device admins (the
`pkg/.Receiver:` lines, not only owners), grep the sensitive permissions
before the list is cut, and do not call a preload a sideload; every remote
script must come back with its end marker, or it is reported as cut off
rather than parsed short.

## Forge

The agent improves its own engine without holding the compiler (vision §3.5,
M6; [`../docs/forge.md`](../docs/forge.md) is the walkthrough). Two
procedures in `sops/` and a tool group close the loop:

- `forge-propose` frames a Runtime change, reads the files as they are on
  `main`, drafts the new content and the pull request, and after the owner's
  gate writes a `forge/<topic>` branch and a **draft PR** through
  `git_forge`, the Runtime's forge tool over its git channel (a GitHub App on
  the repo; [`../runtime/caelza.forge.example.toml`](../runtime/caelza.forge.example.toml)).
  CI builds and tests the branch; a human merges; a `v*` tag releases.
- `forge-release` starts from the channel's `release.published` event (or by
  hand with a tag): it reads the release and whether this machine's archive
  is in it, tells the owner, and after their gate calls `runtime_update`.
- The `runtime` group (`caelza-body serve --tools …,runtime`, on the machine
  that runs the Runtime): `runtime_status` is `caelza-body runtime status`
  plus whether an update is running and the tail of its log;
  `runtime_update(reason, tag?)` starts `caelza-body runtime update` detached
  (the guard above does the rest and the supervisor restarts the Runtime),
  logging to `logs/runtime-update.log` and auditing the reason. It is
  destructive and always asks.

The release workflow builds every archive with `--features channel-git`
(upstream keeps the git channel out of its lean default), and `build.sh`
passes the same flag.

## Next
- The supervisor probes `caelza-body probe` alongside the loop's probe, and
  self-modification commits that break the server roll back the same way.
- Shizuku as an alternative to ADB for `device_*` on the phone itself (§3.3).
