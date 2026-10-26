# New-phone setup

A phone has just been paired (the Bodies page does the pairing) or Termux has
just been installed on it, and it should become a reliable body: reachable
over wireless debugging, Termux alive in the background, Termux:API allowed to
use the camera, microphone and location, the screen awake while it charges.
`device_health` reads the checklist; this procedure fixes what adb can fix,
after the owner approves, and names what needs a hand on the phone.

The trigger payload names the phone as `device` (`self` or a paired phone's
registered name); default `self`.

## Safety

The settings step is gated: the run parks until the owner approves it, and
the Runtime's risk profile asks again on each `device_shell` and
`device_settings_put` call. Only the commands listed in that step are run,
only for checklist items that were missing, and every one is reversible
(`dumpsys deviceidle whitelist -com.termux`, `pm revoke`,
`settings put global stay_on_while_plugged_in 0`).

## Steps

1. **Meet the phone** — Call `body__device_health` for the device named in
   the trigger payload (default `self`) and `body__device_list`. Report the
   phone: manufacturer, model, Android version and security patch, verified
   boot state, battery, free storage. Then the setup checklist, each item
   marked done or missing with what the missing ones mean: wireless debugging
   (needed for adb at all), Termux and Termux:API installed, Termux exempt
   from battery optimisation (otherwise Android kills the Body in the
   background), Termux:Boot installed (starts the Body after a reboot),
   Tailscale installed (reaches a hub), stay awake while plugged in (a body on
   a charger). Say which missing items this procedure can fix from here and
   which need the owner's hand on the phone. No changes in this step.
   - tools: body__device_health, body__device_list

2. **Make it a body** — Approval of this step is the owner's go-ahead for the
   fixes listed in the previous step. Run only these, only for items the
   checklist showed missing, one call each, the reason naming the checklist
   item. Battery optimisation exemption:
   `body__device_shell("dumpsys deviceidle whitelist +com.termux", device)`
   and the same for `com.termux.api` and `com.termux.boot` when installed.
   Termux:API permissions:
   `body__device_shell("pm grant com.termux.api android.permission.CAMERA", device)`
   and the same for `RECORD_AUDIO`, `ACCESS_FINE_LOCATION`,
   `ACCESS_COARSE_LOCATION`. Stay awake while charging:
   `body__device_settings_put("global", "stay_on_while_plugged_in", "7", reason, device)`.
   A result that says the item is already set is fine; any other failure is
   reported and the item left as it was. Nothing else is run in this step.
   - tools: body__device_shell, body__device_settings_put
   - allow-tools: body__device_shell, body__device_settings_put, body__device_health
   - requires_confirmation: true

3. **Check and hand over** — Call `body__device_health` again and report the
   checklist after: what this procedure fixed, what still needs a hand on
   the phone and exactly where to tap (Settings → System → Developer options →
   Wireless debugging; Termux:Boot and Termux:API from F-Droid; the Tailscale
   login), and what to run next: phone-debloat if the carrier's apps are
   still there, phone-diagnostics for a baseline. State the outcome in one
   plain sentence so it is remembered.
   - tools: body__device_health
