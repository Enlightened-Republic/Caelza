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
│ BodyServer (M7b): the device tools over Shizuku as the Body's MCP     │
│   server on http://127.0.0.1:42618/mcp, the Runtime's `body` server   │
│ (M7c) sensors, accessibility + notification listener, camera / mic    │
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

## 3. The Body in the app (M7b, shipped)

The Body's `device` group runs in the app over Shizuku, and the Body stays an
MCP server: `RuntimeService` serves it on loopback over Streamable HTTP
(`body/BodyServer.kt`), exactly as `caelza-body serve --http` does, behind
the same bearer token file (`files/.caelza-body/run/http-token`, created
once, 0600), with `/health` open and `/mcp` locked, the Host header checked.
The Runtime's config gets a `[[mcp.servers]] name = "body"` entry with
`transport = "http"`, `url = "http://127.0.0.1:42618/mcp"` and the token in
`headers.Authorization`, plus `[mcp_bundles.body]`, an `[agents.main]` that
carries it and the `phone` risk profile, appended on first start to whatever
the config lacks (`RuntimeStore.ensureBodyWiring`); a config the dashboard
already shaped keeps its own agent. The risk profile, the playbooks and the
dashboard do not change.

**The contract** is the Python Body's, pinned from both sides. The tool
names, descriptions, argument schemas and safety classes (read-only /
destructive / neutral) are compared against `caelza-body list-tools` in
`android/app/src/test/fixtures/body-tools.json` (written by
`scripts/android_body_fixtures.py`, checked current by
`tests/test_android_body.py`, checked matched by `BodyToolsTest`); every
destructive call needs its `reason`, written to
`.caelza-body/logs/device-actions.log` in the same tab-separated line; a
removal snapshots the full package list into `.caelza-body/snapshots/` first
and refuses when the list came back empty; screenshots land in
`.caelza-body/tmp/` and come back as image content. The playbook reads
(`device_debloat_plan`, `device_suspects`, `device_foreground`,
`device_health`) are `caelza_body/agent/playbooks.py` in Kotlin
(`body/Playbooks.kt`), with its tables exported to `debloat-tables.json` so
the two lists cannot drift, and `PlaybooksTest` / `BodyToolsTest` replay the
same recorded phone (`tests/fixtures/playbooks`, the REVVL snapshot) that
`tests/test_playbook_evals.py` does.

**The transport.** Everything runs as shell commands in Shizuku's process
(`Shizuku.newProcess`, reached by reflection since the library keeps it
private), which holds adb's uid: `pm`, `settings`, `appops`, `input`,
`screencap`, `uiautomator`, `dumpsys`, `logcat` answer exactly as they do
over `adb shell` from Termux, so the parsers and the recordings hold. The
binder path (`IPackageManager`, `IAppOpsService` straight over Shizuku) is a
later refinement, not a contract change. Shizuku not running, or the
permission not granted, is a degraded Body: the tool answers `needs Shizuku:
<what to do>` (exit 127, as a missing `adb` reads on Termux), `device_list`
shows `self` unreachable, nothing crashes.

**Not in the app's Body:** the fleet tools (`device_pair`, `device_unpair`,
`device_join`, `device_tag`) need `adb` and the registry and stay with the
Python Body; a phone can run both (the app's Body yields the port to a Termux
Body already serving on 42618, and says so in the strip). The sensors come
with M7c. `body.privilege = "shizuku"` in the vision is this Body.

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
  a token header the WebView injects. (The Body on 42618 is behind its token.)
- **The Body's binder path.** `IPackageManager` / `IAppOpsService` over the
  Shizuku binder instead of `pm` / `appops` in a shell; faster, no parsing,
  but hidden-API stubs to carry. Measure first.
- **Signing and distribution.** A release keystore in CI secrets, an own
  F-Droid-style repo or GitHub releases for the APK; Play needs targetSdk 34.
- **Foreground service type.** With targetSdk 28 none is required; the move
  to 34 needs `FOREGROUND_SERVICE_SPECIAL_USE` and its declaration.
- **Logs in the app.** A log viewer for `daemon.log` and the installer's
  output, and a share button for a bug report.
- **Tests on a device.** Instrumented tests (`connectedDebugAndroidTest`) for
  the service and the WebView on an emulator in CI; the JVM tests cover the
  pipeline and the store today.
