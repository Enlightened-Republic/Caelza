# REVVL 7 debloat log

**Date:** 2026-08-29
**Device:** T-Mobile REVVL 7 5G (`TMRV075G`), Android 16
**Method:** `adb shell pm uninstall --user 0` / `pm disable-user --user 0` (non-root, no bootloader unlock)
**Restore reference:** `docs/examples/revvl-7-debloat/packages-snapshot.txt` (full `pm list packages -f` of all 297 packages before changes)

## Result

`MemAvailable` 2.40 GB → 2.93 GB immediately (expected ~3.3–3.6 GB steady-state after a reboot).
`MemFree` 255 MB → 607 MB.

## Uninstalled (recoverable via `pm install-existing <pkg>` or factory reset)

| Package | What it was |
|---|---|
| `com.metro.minus1` | Metro "-1 screen" launcher feed (363 MB live) |
| `com.metropcs.metrozone` | MetroZone (237 MB live) |
| `com.ironsrc.aura.tmo` | ironSource Aura — carrier app-push / adware (140 MB live) |
| `com.google.android.youtube` | YouTube (237 MB) |
| `com.google.android.apps.youtube.music` | YouTube Music (184 MB) |
| `com.nuance.nmc.sihome.metropcs` | Nuance SiHome (Metro) |
| `com.vitastudio.mahjong` | preloaded game |
| `in.playsimple.newwordsearch` | preloaded game |
| `in.playsimple.triple.tile.matchgame.pair.three.puzzle.object.royale` | preloaded game |
| `com.amazon.storm.lightning.client.aosp` | Amazon Lightning client |
| `com.tmobile.pr.adapt` | T-Mobile PR adapt |
| `com.tmobile.rsuadapter.qualcomm` | T-Mobile remote SIM unlock |
| `com.tmobile.rsuapp` | T-Mobile remote SIM unlock |
| `com.tmobile.rsusrv` | T-Mobile remote SIM unlock |
| `com.google.android.safetycore` | Google on-device content scanning |
| `com.govee.home` | Govee smart-lights app |

## Disabled (reversible with `pm enable <pkg>`)

| Package | What it was |
|---|---|
| `com.google.android.googlequicksearchbox` | Google app / Assistant / Discover feed (~400 MB live) |
| `com.google.android.apps.chromecast.app` | Google Home (165 MB) |
| `com.tmobile.echolocate` | T-Mobile network telemetry (157 MB) |
| `com.tmobile.echolocate.system` | T-Mobile network telemetry (76 MB) |
| `com.tmobile.dm.cm` | T-Mobile device management |
| `com.tmobile.dm.ms.services` | T-Mobile device management |
| `com.google.android.apps.messaging` | Google Messages (no SIM; 220 MB live) |
| `com.wingos.wingcamera` | Wingtech camera app (termux-api uses camera2 directly) |
| `com.google.android.apps.googleassistant` | Google Assistant |
| `com.android.chrome` | Chrome (~750 MB with sandboxes; WebView retained) |

## Kept

Play Services, Android System Intelligence (`com.google.android.as`), SystemUI, launcher3,
Play Store, permissioncontroller, setupwizard, euicc, Tailscale, all Qualcomm/QTI radio
components, dialer, carrier-config.
