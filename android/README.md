# Caelza for Android

The native companion (vision §3.3, milestone M7): the app people install
instead of a Termux session. It hosts the Runtime binary as a foreground
service, shows the Runtime's own dashboard in a WebView shell, serves the
Body (the phone's device tools over Shizuku, its sensors through the Android
APIs) to the Runtime as an MCP server on loopback, runs the free local model
beside the Runtime, and lets Cael lead the first run. Four slices: the shell
(M7a), the device tools (M7b), the sensors (M7c), the first run and the local
model (M7d); [`../docs/design/android-app.md`](../docs/design/android-app.md)
has the architecture and what is still open.

```
android/
├── settings.gradle.kts, build.gradle.kts, gradle/libs.versions.toml   Gradle 8.14 + AGP 8.13 + Kotlin 2.2, versions pinned
├── gradlew                                                            the wrapper (JDK 17+; the sandbox and CI use 21)
└── app/
    ├── build.gradle.kts            applicationId tech.enlightenedrepublic.caelza; minSdk 28, targetSdk 28 (see below), compileSdk 36
    └── src/main/java/tech/enlightenedrepublic/caelza/
        ├── MainActivity.kt         the shell: status strip + the dashboard WebView over the gateway on loopback
        ├── logs/LogsActivity.kt    the logs on the phone: one chip per log, the end of it, Refresh, Share (a bug report through a FileProvider)
        ├── logs/BugReport.kt       the sources, tails at a line boundary, secrets blanked, the report's text
        ├── RuntimeService.kt       `caelza daemon` as a foreground service with the supervisor's ladder
        ├── BootReceiver.kt         start the Runtime again after a reboot
        ├── runtime/RuntimeStore.kt  runtime/<version>/caelza, current, last-good, the config and the web dist
        ├── runtime/ReleaseInstaller.kt  the guard's pipeline: release → download → sha256 → unpack → probe → install
        ├── runtime/CrashLoop.kt, runtime/Gateway.kt
        ├── shizuku/ShizukuStatus.kt  where Shizuku stands (not running / permission needed / ready)
        ├── body/BodyServer.kt      the Body as an MCP server on 127.0.0.1:42618 (/mcp behind the token, /health open)
        ├── body/BodyTools.kt       the device tools: names, schemas, classes and behaviour of the Python Body's
        ├── body/Playbooks.kt       the playbook parsers and the debloat tables (caelza_body/agent/playbooks.py in Kotlin)
        ├── body/Shell.kt, body/ShizukuShell.kt  the shell user through Shizuku, shaped as adb.run shapes it
        ├── body/Sensors.kt, body/AndroidSensors.kt  the sensors_* tools' phone: battery, notifications, clipboard, location, camera, mic, TTS, torch
        ├── body/CaelzaNotificationListener.kt, body/SensorPermissions.kt  the status-bar listener; what is granted and how to ask
        ├── body/BodyHome.kt        files/.caelza-body: run/http-token, logs/device-actions.log, snapshots/, tmp/
        ├── firstrun/FirstRunActivity.kt, firstrun/FirstRun.kt  Cael's first run: the steps, the two doors, what each writes
        ├── model/ModelLadder.kt    scripts/model_ladder.py's phone branch: the DeepSeek R1 GGUF pins by RAM
        ├── model/ModelStore.kt     files/.caelza/models: resumable, verified downloads; serve.json
        ├── model/LlamaRuntime.kt   llama.cpp's Android build, pinned by tag + sha256, under files/runtime/llama/<tag>/
        └── runtime/CaelzaCli.kt    `caelza config set --no-interactive` through the installed Runtime; Cael's workspace
```

## Build

```sh
cd android
./gradlew assembleDebug testDebugUnitTest      # needs ANDROID_HOME (or local.properties: sdk.dir=…) with platform 36 + build-tools 35.0.0
adb install app/build/outputs/apk/debug/app-debug.apk
```

CI builds the same ([`.github/workflows/android.yml`](../.github/workflows/android.yml))
and keeps the APK as an artifact. The unit tests run on the JVM: the release
installer against a fake release (a tarball with a shell-script `caelza` that
answers `--version` and serves `/health` through python3, or crashes, or lies
about its version), the store's pointers and pruning, the crash loop, the
gateway port; and the Body over a recorded phone (`tests/fixtures/playbooks`,
the REVVL package snapshot, the same recordings `tests/test_playbook_evals.py`
replays): the four playbook reads end to end, the audit lines and snapshots
of the destructive tools, the sensors over a fake phone, the MCP server over
real HTTP, the model ladder against the Python ladder's export, the model
store over a fake server (resume, a server that ignores `Range`, tampered
bytes, a dead connection), llama.cpp's archive laid out from a fake tarball,
`caelza config set` through a fake `caelza`, the first run's steps and
doors, and the contract against the Python server's `list-tools`
(`app/src/test/fixtures/`, written by `../scripts/android_body_fixtures.py`).

## What the shell does

1. **Install the Runtime**: the latest release's `caelza-<version>-aarch64-linux-android.tar.gz`
   from this repo, verified against its `.sha256`, unpacked and **probed** in
   a work dir (`caelza --version` must match, `caelza gateway start` must
   serve `/health` on a free port, on a copy of the config) before it is
   installed under the app's files dir. `current` moves to it; `last-good`
   stays on the version that was running (the first install is both). The
   dashboard (`web/dist`) goes where the gateway looks for it.
2. **Run it**: `RuntimeService` starts `caelza daemon` with `HOME` set to the
   app's files dir (so the config is `files/.caelza/config.toml`, written with
   the gateway on loopback behind pairing on first start; the app pairs its
   own shell with the gateway's admin token, `runtime/GatewayPairing.kt`), logs to
   `files/logs/daemon.log`, restarts it when it exits, rolls `current` back to
   `last-good` on a crash loop, and halts with a notification when last-good
   itself loops or when another Runtime already holds the gateway port. A
   boot receiver starts it again after a reboot.
3. **Show the dashboard**: the WebView loads `http://127.0.0.1:42617/` as soon
   as `/health` answers and drops back to the shell when it stops.
4. **Serve the Body**: with the Runtime, `RuntimeService` starts the Body's
   MCP server on `127.0.0.1:42618` (`/mcp` behind the bearer token in
   `files/.caelza-body/run/http-token`, `/health` open) and makes sure the
   Runtime's config names it (`[[mcp.servers]] name = "body"`, `transport =
   "http"`, the token in `headers.Authorization`, the `body` bundle, an
   `[agents.main]` that carries it, the `phone` risk profile). The sixteen
   `device_*` tools are the Python Body's: the same names, schemas and safety
   classes, a `reason` on every destructive call written to
   `.caelza-body/logs/device-actions.log`, a package snapshot before a
   removal. They run as shell commands in Shizuku's process, which is what
   `adb shell` gives the Termux Body.
5. **Sense**: the nine `sensors_*` tools are the Android APIs behind
   `termux-api`'s answers: battery, the status bar (a notification listener
   the owner turns on in Settings), the clipboard, location (quick: wifi + a
   city from the public IP; gps / network: coordinates), a photo (camera2),
   a recording (`MediaRecorder`), text to speech, the torch. A permission not
   granted makes the tool answer `needs the camera permission: Settings › …`;
   the strip's third line lists what is missing and `Grant` asks.
6. **Shizuku**: the strip says where it stands and asks for the permission
   through Shizuku's own prompt. Without it the Body still serves; its device
   tools answer `needs Shizuku: <what to do>` instead of running.
7. **The first run, with Cael**: on the first launch (and from `Set up with
   Cael` any time) Cael walks the owner through eight steps: the Runtime
   installed, a brain chosen, Shizuku, the permissions with their reasons,
   the battery exemption, a word about hubs, start. The brain has two doors.
   *Free and local* downloads llama.cpp's prebuilt Android build (pinned by
   tag and sha256) and the DeepSeek R1 GGUF the phone's RAM allows (the 1.5B
   under 6 GB, the 7B above, Cael always on the 1.5B), verified against the
   ladder's pins, then runs `llama-server` on `127.0.0.1:8080` beside the
   Runtime, which is where the Runtime's `llamacpp` provider looks. *Bring
   your own key* takes an Anthropic, OpenAI or OpenRouter key and model. Both
   doors write the config through the installed Runtime's own `caelza config
   set`, create Cael as `agents.cael` on the guide profile and give him his
   `SOUL.md`.

## targetSdk 28, on purpose

From API 29 on, Android refuses to execute a binary the app wrote into its own
files dir (W^X). The whole point of the guard is pulling a new Runtime release
without shipping a new APK, so the app targets 28, as Termux does. The
alternatives (the binary as a `jniLibs` payload updated only with the APK, or
the `linker64` exec trick) are weighed in the design doc; the choice is
revisited once the first builds run on the REVVL.
