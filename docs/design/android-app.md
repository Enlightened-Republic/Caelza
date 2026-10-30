# The Caelza Android app

Vision §3.3 and §9 (M7): the product people install is an app, not a Termux
session. Two surfaces, one Runtime: the web app (the Runtime's dashboard,
phone-first, a PWA) and a native companion that owns the Body. This document
is the app's architecture and the slices it ships in. `android/` is the code;
`android/README.md` the build.

## 1. What the app is

```
┌───────────────────────── Caelza (Android) ─────────────────────────┐
│ MainActivity: status strip (Runtime · Shizuku · Start/Stop · Update)│
│               WebView ──────────────▶ http://127.0.0.1:42617 (dashboard)
│ RuntimeService (foreground):  caelza daemon  ◀── runtime/current     │
│    the supervisor's ladder: restart, roll back to last-good, halt     │
│ ReleaseInstaller: GitHub release ─▶ sha256 ─▶ unpack ─▶ probe ─▶ install
│ BootReceiver: start again after a reboot                             │
│ (M7b) Body: device tools over Shizuku, sensors, as an MCP server     │
│ (M7c) accessibility + notification listener, camera / mic / location  │
│ (M7d) Cael-led first run, the local model runner                     │
└───────────────────────────────────────────────────────────────────────┘
```

The Runtime is the same `aarch64-linux-android` binary the Termux install
uses, built by `release.yml`; the app does not fork it. What the app replaces
is the bring-up: Termux:Boot becomes a foreground service and a boot
receiver, the loopback-ADB pairing becomes Shizuku, `termux-api` becomes the
normal Android APIs, and the install script becomes a button.

## 2. The Runtime inside the app (M7a, shipped)

**Layout.** `RuntimeStore` keeps the guard's layout under the app's files
dir, the way `caelza_body/runtime_guard.py` keeps it under `~/.caelza-body`:

```
files/runtime/<version>/caelza     one release, unpacked
files/runtime/current              the version the service runs (a pointer file)
files/runtime/last-good            what a crash loop falls back to
files/.caelza/config.toml          the Runtime's config: HOME is files/
files/.local/share/caelza/web/dist the dashboard, where the gateway looks
files/logs/daemon.log              the Runtime's output (rotated at 5 MB)
```

**Install.** `ReleaseInstaller.update()` is the guard's pipeline in Kotlin:
find the release (latest, or a tag; `0.1.0` means `v0.1.0`), pick the
`-aarch64-linux-android.tar.gz` asset and its `.sha256`, download, verify,
unpack into a work dir refusing any member that escapes it, **probe** the
binary there (`--version` must answer with the release's version;
`gateway start -p 42619` on a copy of the config must serve `/health` within
a minute and still be running; a port something else answers on is refused),
then install, move `current`, keep `last-good` on the version that was
running (the first install, or nothing else holding, promotes both), copy the
dashboard, prune to three versions never touching current, last-good or the
one still running. A binary that does not hold is never installed. The same
rules the Body's guard follows, with the same tests (`ReleaseInstallerTest`
drives it with a fake release whose `caelza` can crash or lie).

**Run.** `RuntimeService` is a foreground service (a persistent notification
is the price of surviving Doze). It runs `caelza daemon` with `HOME=files/`,
`TMPDIR=cache/`, `CAELZA_SUPERVISED=1`, output appended to `daemon.log`, and
the supervisor's ladder (`caelza_body/supervisor.py`): restart on exit with a
2 s pause; three exits in five minutes roll `current` back to `last-good`
and restart; a crash loop on last-good halts with a notification that says
so; a crash loop while another Runtime already answers on the gateway port
halts without a rollback (not the binary's fault). `MainActivity` watches
`/health` and shows the dashboard the moment it answers. Start, Stop and
Update are the strip's buttons; the installer asks the service to restart
after a new version probed ok.

**First config.** With no `config.toml`, the service writes one with the
gateway on `127.0.0.1:42617` and `require_pairing = false`: only this phone's
apps can reach loopback, and the shell is the client. That is the same
exposure as the Termux install (any app on the phone can reach a loopback
gateway); §6 keeps it on the list.

**targetSdk 28.** From API 29 Android enforces W^X on app data: a binary the
app downloaded into `files/` cannot be executed. Three ways out:

| option | what it costs |
|---|---|
| **targetSdk 28** (chosen for now; Termux does the same) | no Play Store listing under current policy (sideload / F-Droid / own repo); the behaviour changes of 29+ are not applied to the app; Android 14 still installs it (it refuses only targets below 23) |
| the binary as `jniLibs/arm64-v8a/libcaelza.so`, run from `nativeLibraryDir` | updating the Runtime means a new APK: the guard's pull-a-release loop (M6) is lost, Forge's release never reaches the phone by itself |
| exec through `linker64` (`/system/bin/linker64 files/runtime/current/caelza`) | works on many devices with targetSdk 34, documented nowhere, SELinux-dependent; worth measuring on the REVVL before trusting it |

The decision is revisited after the first builds run on the test device (M7
open item); the code keeps the binary path in one place (`RuntimeStore`) so
the switch is local.

## 3. The Body in the app (M7b, next)

The Body's `device_*` tools map onto Shizuku one to one (vision §3.3's table):
`newProcess` for `device_shell`, `device_logcat`, `device_packages`;
`IPackageManager` / `IAppOpsService` / `Settings` over the Shizuku binder for
`device_uninstall`, `device_disable`, `device_appops`, `device_settings`;
`input` and `screencap` through `newProcess` until the accessibility and
MediaProjection paths land (M7c). The Body stays an MCP server: the app
serves it on loopback over Streamable HTTP, exactly as `caelza-body serve
--http` does today, behind the same bearer token file layout, so the Runtime's
`[[mcp.servers]] name = "body"` entry points at `http://127.0.0.1:42618/mcp`
and the risk profile, the playbooks and the dashboard do not change. The tool
names, argument shapes, safety classes (read-only / destructive / neutral),
the `reason` on every destructive call, the audit log and the package
snapshot before a removal are the contract (`tests/test_mcp_server.py` and
`test_bodies_page.py` pin it on the Python side; the Kotlin port gets the
same tests over the same recorded phone output in `tests/fixtures/playbooks`).
`body.privilege = "shizuku"` is the Body config that selects the transport;
a phone can run both the Termux Body and the app's.

## 4. Sensors, screen and notifications (M7c)

The Termux:API sensors (`sensors_battery`, `sensors_location`,
`sensors_notifications`, `sensors_camera_photo`, `sensors_mic_record`,
`sensors_tts_speak`, the clipboard, the torch) become the normal Android APIs
inside the app: a `NotificationListenerService` for the notification feed, an
`AccessibilityService` for `device_ui_dump` and `device_input` without
Shizuku, MediaProjection for `device_screencap` of this phone, CameraX and
`MediaRecorder` for the captures, `TextToSpeech`. Each is a runtime
permission the first-run wizard asks for in plain words, and a missing one is
a degraded Body (the tool answers "needs the notification access permission;
here is where"), never a crash.

## 5. First run, and the local model (M7d)

Cael (the Guide, `guide/CAEL.md`) leads the first run inside the app: the two
doors of §3.4 (free and local, or bring your own key), what Shizuku is and
how to start it, which permissions do what, the battery-optimisation
exemption (`ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`), Tailscale for a
hub. The local model runner is llama.cpp bundled as a native library (or the
Termux package when present), the ladder of `scripts/model_ladder.py` picking
the tier by RAM; the GGUF comes from the pinned sha256s. The dashboard's
quickstart stays the configuration surface; the app only gets the owner to
the first working turn.

## 6. Open items

- **The brand mark.** The launcher icon is a placeholder ring in the brand
  gradient; `brand/make_assets.py` should render the real mark into the
  mipmap folders (adaptive icon foreground + monochrome).
- **W^X** (§2): measure `linker64` and the native-library payload on the
  REVVL before settling the targetSdk.
- **Loopback exposure.** The gateway with pairing off is reachable by any app
  on the phone. Options: keep pairing on and let the shell read the code from
  the daemon log; a Unix domain socket once the gateway can listen on one;
  a token header the WebView injects.
- **Signing and distribution.** A release keystore in CI secrets, an own
  F-Droid-style repo or GitHub releases for the APK; Play needs targetSdk 34.
- **Foreground service type.** With targetSdk 28 none is required; the move
  to 34 needs `FOREGROUND_SERVICE_SPECIAL_USE` and its declaration.
- **Logs in the app.** A log viewer for `daemon.log` and the installer's
  output, and a share button for a bug report.
- **Tests on a device.** Instrumented tests (`connectedDebugAndroidTest`) for
  the service and the WebView on an emulator in CI; the JVM tests cover the
  pipeline and the store today.
