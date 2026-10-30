# Caelza for Android

The native companion (vision §3.3, milestone M7): the app people install
instead of a Termux session. It hosts the Runtime binary as a foreground
service, shows the Runtime's own dashboard in a WebView shell, and will own
the Body (the phone's sensors and device tools, over Shizuku). This is the
first slice, the shell; [`../docs/design/android-app.md`](../docs/design/android-app.md)
has the architecture and the slices that follow.

```
android/
├── settings.gradle.kts, build.gradle.kts, gradle/libs.versions.toml   Gradle 8.14 + AGP 8.13 + Kotlin 2.2, versions pinned
├── gradlew                                                            the wrapper (JDK 17+; the sandbox and CI use 21)
└── app/
    ├── build.gradle.kts            applicationId tech.enlightenedrepublic.caelza; minSdk 28, targetSdk 28 (see below), compileSdk 36
    └── src/main/java/tech/enlightenedrepublic/caelza/
        ├── MainActivity.kt         the shell: status strip + the dashboard WebView over the gateway on loopback
        ├── RuntimeService.kt       `caelza daemon` as a foreground service with the supervisor's ladder
        ├── BootReceiver.kt         start the Runtime again after a reboot
        ├── runtime/RuntimeStore.kt  runtime/<version>/caelza, current, last-good, the config and the web dist
        ├── runtime/ReleaseInstaller.kt  the guard's pipeline: release → download → sha256 → unpack → probe → install
        ├── runtime/CrashLoop.kt, runtime/Gateway.kt
        └── shizuku/ShizukuStatus.kt  where Shizuku stands (not running / permission needed / ready)
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
gateway port.

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
   the gateway on loopback and pairing off on first start), logs to
   `files/logs/daemon.log`, restarts it when it exits, rolls `current` back to
   `last-good` on a crash loop, and halts with a notification when last-good
   itself loops or when another Runtime already holds the gateway port. A
   boot receiver starts it again after a reboot.
3. **Show the dashboard**: the WebView loads `http://127.0.0.1:42617/` as soon
   as `/health` answers and drops back to the shell when it stops.
4. **Shizuku**: the status strip says where it stands and asks for the
   permission through Shizuku's own prompt. The device tools come with the
   Body port (next slice).

## targetSdk 28, on purpose

From API 29 on, Android refuses to execute a binary the app wrote into its own
files dir (W^X). The whole point of the guard is pulling a new Runtime release
without shipping a new APK, so the app targets 28, as Termux does. The
alternatives (the binary as a `jniLibs` payload updated only with the APK, or
the `linker64` exec trick) are weighed in the design doc; the choice is
revisited once the first builds run on the REVVL.
