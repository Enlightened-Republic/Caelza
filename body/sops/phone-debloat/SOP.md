# Phone debloat

Take the carrier's and the OEM's junk off a phone without touching anything
the phone needs. The list of what is junk is code, not judgment: the Body's
`device_debloat_plan` sorts every installed package into remove, disable,
optional, keep and review from a curated table (`caelza_body/agent/playbooks.py`,
derived from the REVVL 7 debloat in `docs/examples/revvl-7-debloat` and the
Universal Android Debloater lists). The model's job is to show the owner the
plan, carry out exactly what was approved, and report.

The trigger payload names the phone as `device` (`self` is the phone the Body
runs on; a paired phone goes by its registered name) and may carry `keep`, a
comma-separated list of packages to leave alone whatever the table says. With
no payload, the device is `self`.

## Safety

Two gates stand in front of every change: this procedure parks at the Apply
step until the owner approves it, and the Runtime's risk profile asks again on
each `device_uninstall` / `device_disable` call. The Body writes a full package
snapshot to `~/.caelza-body/snapshots/` before each removal and refuses to
remove anything when the snapshot comes back empty. Everything is reversible:
`pm install-existing <pkg>` brings a removed system package back, Play
reinstalls a third-party one, `pm enable <pkg>` re-enables a disabled one.

## Steps

1. **Take stock and write the plan** — Call `body__device_debloat_plan` for the
   device named in the trigger payload (default `self`), passing its `keep`
   list if it has one, then `body__device_health` for the free storage and
   memory before anything changes. Write the plan for the owner, grouped the
   way the tool answers: remove (each package with its why), disable (each
   with its why), optional (heavy first-party and carrier apps the owner may
   want gone; ask which, if any), review (their own apps the list does not
   know; name them, touch none unless the owner says so). Say what remove and
   disable mean and that both are reversible. Use exact package names. Do not
   change anything in this step.
   - tools: body__device_debloat_plan, body__device_health
   - allow-tools: body__device_debloat_plan, body__device_health

2. **Apply what was approved** — Approval of this step is the owner's go-ahead
   for the plan as written in the previous step, plus any optional or review
   packages they named. For each package in the remove list call
   `body__device_uninstall(pkg, reason)` with the plan's reason; for each in
   the disable list call `body__device_disable(pkg, reason)`. One package per
   call, in order. A result that says the package is not installed for user 0
   or is already disabled is fine; any other failure is reported and the
   package is left as it is. Never touch a package outside the approved list,
   and never uninstall a package the plan said to disable.
   - tools: body__device_uninstall, body__device_disable
   - allow-tools: body__device_uninstall, body__device_disable, body__device_packages
   - requires_confirmation: true

3. **Check and report** — Call `body__device_debloat_plan` again to confirm
   the approved packages are gone or disabled, and `body__device_health` for
   the storage and memory after. Report in plain words: what was removed,
   what was disabled, what failed and why, memory and storage before and
   after, and how to undo each kind of change. The snapshot path is in the
   Body's audit log (`~/.caelza-body/logs/device-actions.log`).
   - tools: body__device_debloat_plan, body__device_health
   - allow-tools: body__device_debloat_plan, body__device_health
