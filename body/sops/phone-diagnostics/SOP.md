# Phone diagnostics

How is the phone doing? One read of everything that tells, in plain words,
with what needs attention first. `device_health` gathers it in a single adb
call; this procedure adds the Body's own battery view and the recent error
log, then explains.

The trigger payload names the phone as `device` (`self` or a paired phone's
registered name); default `self`. Nothing in this procedure changes the phone.

## Steps

1. **Measure** — Call `body__device_health` for the device named in the
   trigger payload (default `self`). When the device is `self`, also call
   `body__sensors_battery` (the Termux:API view: current, temperature, health
   as Android reports it) and `body__device_logcat` with filter `*:E` and 100
   lines for the recent errors. Keep the raw numbers for the next step; do
   not explain yet.
   - tools: body__device_health, body__sensors_battery, body__device_logcat
   - allow-tools: body__device_health, body__sensors_battery, body__device_logcat

2. **Report** — Explain the readings to the owner in plain words, starting with
   the `attention` list the health tool returned, then battery (level,
   charging, temperature, health), storage and memory (how much is free, is it
   tight), uptime, heat, who is using the CPU, crashes in the crash log and
   which apps, network addresses, Android version and security patch (say if
   the patch is more than three months old), and the setup checklist. For
   each thing that needs attention say what the owner can do. Suggest
   phone-debloat when storage or memory is tight and the carrier's apps are
   present, phone-malware-removal when an unknown app is crashing or posting,
   phone-new-setup when checklist items are missing. End with one plain
   sentence summing up the phone's state so it is remembered.
