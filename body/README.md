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
| **read-only** | `readOnlyHint`, `idempotentHint` | `auto_approve` | `device_list`, `device_packages`, `device_logcat`, `device_settings`, `device_ui_dump`, `device_screencap`, `device_debloat_plan`, `device_suspects`, `device_foreground`, `device_health`, `sensors_battery`, `sensors_notifications`, `sensors_clipboard_get`, `sensors_location`, `self_read_file`, `self_list_tree`, `web_search`, `web_read`, `web_map`, `web_crawl_result` |
| **destructive** | `destructiveHint` | `always_ask` | `device_uninstall`, `device_disable`, `device_settings_put`, `device_appops`, `device_pair`, `device_unpair`, `device_join`, `device_shell`, `shell_run`, `self_write_file`, `self_commit`, `self_request_restart` |
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
the hub adds one line per forwarded destructive call to `logs/fleet.log`.

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

## Next

- The supervisor guards the Runtime binary too (vision §3.5): fetch a release,
  verify, probe, swap, roll back (the rest of M6).
- The supervisor probes `caelza-body probe` alongside the loop's probe, and
  self-modification commits that break the server roll back the same way.
- Shizuku as an alternative to ADB for `device_*` on the phone itself (§3.3).
