---
name: 3d-printer
description: Check on a 3D printer on the home network (Moonraker/Klipper or OctoPrint): status, progress, temperatures, a camera snapshot, and pause or cancel after the owner agrees.
version: 0.1.0
author: caelza
tags: [printer, 3d-printing, home]
---

# 3D printer

You can look after a 3D printer on the owner's own Wi-Fi with the `http_request`
tool. Two kinds are supported: **Moonraker** (Klipper printers; Mainsail and
Fluidd run on top of it) and **OctoPrint**. Bambu Lab printers are not supported
yet: say so plainly if asked.

## Before the first request

Ask the owner, in plain words, for: the printer's address (an IP like
`192.168.1.40`, or a name like `voron.local`) and which software it runs
(Moonraker/Klipper/Mainsail/Fluidd, or OctoPrint). Do not guess an address.
If a request is refused as a private host, the owner has not allowed that address
yet: show them `runtime/caelza.printer.example.toml` (`allowed_private_hosts`) and
help them add just that one address. Never ask them to allow every private host.

OctoPrint needs an API key (OctoPrint: Settings > API). The owner stores it with
`caelza config set http_request.secrets.octoprint` and you pass `auth_secret:
"octoprint"` on every OctoPrint request. Never ask them to paste the key into the
chat and never repeat it. Moonraker on a home network normally needs none.

## Moonraker (default port 7125; use http://ADDRESS:7125)

- Status, progress, temperatures, one request:
  `GET /printer/objects/query?print_stats&display_status&extruder&heater_bed`
  `print_stats.state` is standby / printing / paused / complete / cancelled / error;
  `print_stats.filename` is the file; `display_status.progress` runs 0 to 1;
  temperatures are in `extruder.temperature` and `heater_bed.temperature`.
- Camera: `GET /server/webcams/list`, then fetch the `snapshot_url` of the first
  webcam (relative to the printer's address).
- Pause: `POST /printer/print/pause`. Resume: `POST /printer/print/resume`.
  Cancel: `POST /printer/print/cancel`.

## OctoPrint (default port 80 or 5000)

- Job and progress: `GET /api/job` (`state`, `progress.completion` as a percent,
  `progress.printTimeLeft` in seconds, `job.file.name`).
- Temperatures: `GET /api/printer` (`temperature.tool0`, `temperature.bed`).
- Pause: `POST /api/job` with JSON `{"command":"pause","action":"pause"}`.
  Resume: `{"command":"pause","action":"resume"}`. Cancel: `{"command":"cancel"}`.

## Rules

- Reading is always fine: status, progress, temperatures, a snapshot.
- **Pause and cancel change a real print. Ask the owner first, say which file and
  how far along it is, and wait for a clear yes.** Cancelling wastes the print and
  cannot be undone. Offer pause before cancel when the owner only wants to look.
- Never send G-code, start a print, change temperatures, move axes, or call the
  emergency stop. Those are not part of this skill; tell the owner to do them on
  the printer or in its own app.
- Report results in plain language ("Printing benchy.gcode, 63% done, about 40
  minutes left, nozzle 215 C"), not raw JSON. If the printer is unreachable, say
  it may be off, asleep, or on a different network than this device.
