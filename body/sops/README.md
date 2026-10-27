# The phone playbooks (`body/sops`)

Four standard operating procedures for the Runtime's SOP engine, the Airframe
"capability playbooks" (agent-design §14.2) as procedures the agent follows
step by step with approval gates, not markdown it hopefully remembers (vision
§5, milestone M5). Each is a directory the Runtime loads as-is: `SOP.toml`
(identity, trigger, execution knobs) and `SOP.md` (the steps).

| Procedure | What it does | Gate | Changes the phone with |
|---|---|---|---|
| `phone-debloat` | the Body's curated list sorts every package into remove / disable / optional / keep / review; the owner reads the plan; the approved packages go | step 2 | `device_uninstall`, `device_disable` |
| `phone-malware-removal` | what is on screen and who installed it, the sideloaded apps with the permissions malware wants, a containment plan; the culprit is disabled and loses its overlay | step 3 | `device_disable`, `device_appops` |
| `phone-new-setup` | identity, patch level and the setup checklist; Termux exempt from battery optimisation, Termux:API permissions, stay awake while charging | step 2 | `device_shell` (the listed commands only), `device_settings_put` |
| `phone-diagnostics` | battery, storage, memory, uptime, heat, CPU, crashes, network, patch level, checklist, in plain words | none | nothing |

## How they run

The reads are the Body's own: four read-only tools added for the playbooks
(`caelza_body/agent/tools/playbook.py`) so the deterministic part is code the
evals cover, not judgment the model has to get right every time.

| Tool | Returns |
|---|---|
| `device_debloat_plan(device, keep)` | every installed package classified from the curated table in `caelza_body/agent/playbooks.py` (exact names, then patterns; the REVVL 7 log in `docs/examples/revvl-7-debloat` and the Universal Android Debloater lists are the sources), with a reason per package and the already-disabled ones set aside |
| `device_suspects(device, days)` | the third-party packages that did not come from a store, each with installer, install dates and risk flags (`sideloaded`, `overlay`, `accessibility`, `device_admin`, `notification_listener`, `install_packages`, `sms`, `calls`, `recent`, …) scored low / medium / high; plus the enabled accessibility services, device admins and notification listeners |
| `device_foreground(device)` | the package and activity on screen, who installed it, system or sideloaded, its risk flags |
| `device_health(device)` | one adb call: identity and patch level, battery, storage, memory, uptime, thermal status, top CPU users, crash-log entries, network addresses, the setup checklist, and an `attention` list in plain words |

Execution mode is `auto` for all four: the read steps run without a prompt
(they are in the risk profile's `auto_approve`), and the one step per
procedure that changes the phone carries `requires_confirmation: true`, so the
run parks there as `waiting_approval` until the owner approves it on the
Procedures page, Home's "waiting on you", `caelza sop approve`, or the channel
the approval policy routes to. The plan the owner approves is the previous
step's output, written for them in plain words with exact package names.
Approval is for the plan as written; deny ends the run with nothing changed.

A second gate stands behind the first: every destructive Body tool is in the
risk profile's `always_ask` (`body/caelza-body.example.toml`), so the agent's
calls inside the approved step still ask the owner, one per package. An owner
who finds that too much can move `body__device_disable` and
`body__device_uninstall` out of `always_ask` for the agent that runs
playbooks; the procedure's own gate remains.

Every step also lists `allow-tools`: the reads a read step may make, and for
the gated step only what it applies. With `[sop] step_scope_enforce = true`
(set in `runtime/caelza.phone.example.toml` and the hub example) the engine
binds the agent to that list for the step, so a destructive tool cannot be
called from a read step at all; off (the upstream default) the lists are
advisory and the risk profile is the only gate on the tool.

The Procedures page fans a group out as one run per phone, so every playbook
admits runs in `parallel` (up to `max_concurrent = 8`), each parked at its
own gate. `hold` would defer every phone after the first and `coalesce` would
answer the second phone with the first phone's run.

The Body's safety semantics hold underneath both: a `reason` on every
destructive call, the audit log at `~/.caelza-body/logs/device-actions.log`,
a package snapshot before every removal or disable (the call is refused when
the snapshot comes back empty). Nothing a playbook does is irreversible:
`pm install-existing`, `pm enable`, `appops set … allow`,
`dumpsys deviceidle whitelist -<pkg>`, `pm revoke`.

Every tool a step names is prefixed `body__`, the name the Runtime gives the
tools of the `[[mcp.servers]]` entry named `body`. A Body wired under another
server name needs the prefix changed in the `SOP.md` files.

## Install

```sh
caelza-body playbooks                 # list them: steps, gates, tools
caelza-body playbooks --install       # copy into ~/.caelza/shared/sops
caelza sop validate                   # the Runtime's own check
```

`--install DIR` targets another `sops_dir`; a copy you have edited is kept
unless `--force`. `install.sh` runs the install on a Termux phone. The Runtime
loads them once `[sop] sops_dir = "shared/sops"` is set
(`runtime/caelza.phone.example.toml` carries the block); then they appear in
the dashboard's Procedures library with a **Run** button that asks which
phone, and the agent can start them from a chat with `sop_execute`.

The trigger payload is `{"device": "<name>"}` (`self`, a phone paired over
ADB, or a phone's own Body joined over HTTP, see `body/README.md` "Fleet")
and, for the debloat, an optional `keep` list. The Run button sends it; a
chat start gets it from the agent. Choosing a group in the Run dialog starts
one run per phone in it, each with its own gate.

## Evals

`tests/test_playbooks.py` keeps the definitions sound: every tool a step
names is one the Body serves, every destructive tool sits in a step that
requires confirmation, read steps never do, every procedure has an owning
agent and a manual trigger, and the SOP.md steps parse the way the Runtime
parses them. When a `caelza` binary is on `PATH` (or named by `CAELZA_BIN`),
the test also runs `caelza sop validate` on the set.

`tests/test_playbook_evals.py` runs the playbooks' deterministic half over
recorded phone output: the debloat classifier over the 297-package REVVL 7
snapshot (the log's carrier junk lands in remove and disable, its Google apps
in optional, its keeps in keep, nothing the platform needs is ever offered),
the foreground parser over both `dumpsys` shapes, the risk scorer over a
sideloaded overlay app and over a Play-installed one, the health parser over
a full recording. With `CAELZA_EVAL_SERIAL=<adb serial>` (an emulator's
`emulator-5554`, or a phone), the live evals also run the four tools against
that device and check their shape.
