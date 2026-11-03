"""The release's Android leg (android-app.md §2 "Release").

A `v*` tag builds the app as `caelza-app-<version>.apk` beside the Runtime
tarballs: `scripts/app_version.py` turns the tag into versionName, versionCode
and the build id, `android/app/build.gradle.kts` reads them as `-P` properties
and signs with the release keystore the environment names (the debug key
otherwise), `release.yml`'s `app` job wires it. These tests pin the rule, the
wiring, and that the installers keep picking their tarball with the APK beside it.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from caelza_body import runtime_guard as rg

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "app_version.py"
GRADLE = (REPO_ROOT / "android" / "app" / "build.gradle.kts").read_text()
RELEASE = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text()
ANDROID_CI = (REPO_ROOT / ".github" / "workflows" / "android.yml").read_text()
KT = REPO_ROOT / "android" / "app" / "src" / "main" / "java" / "tech" / "enlightenedrepublic" / "caelza"
TARGET = "aarch64-linux-android"


def _load():
    spec = importlib.util.spec_from_file_location("app_version", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


av = _load()


# --- the rule --------------------------------------------------------------------

@pytest.mark.parametrize("ref, version, code, build_id, release", [
    ("v0.1.0", "0.1.0", 1000, "v0.1.0", True),
    ("v12.3.4", "12.3.4", 12_003_004, "v12.3.4", True),
    ("v0.1.0-rc.1", "0.1.0-rc.1", 1000, "v0.1.0-rc.1", True),      # a pre-release shares its final's code
    ("v2.0.0", "2.0.0", 2_000_000, "v2.0.0", True),
    (" v0.1.0\n", "0.1.0", 1000, "v0.1.0", True),
    ("dev", "dev-abcdef12", 1, "dev-abcdef12", False),                 # release.yml's workflow_dispatch run
    ("main", "dev-abcdef12", 1, "dev-abcdef12", False),
    ("0.1.0", "dev-abcdef12", 1, "dev-abcdef12", False),               # no leading v: not a release tag
    ("v0.1", "dev-abcdef12", 1, "dev-abcdef12", False),
    ("", "dev-abcdef12", 1, "dev-abcdef12", False),
])
def test_the_tag_names_the_apps_version_and_code(ref, version, code, build_id, release):
    assert av.app_version(ref, "abcdef1234567890") == {"version": version, "code": code, "build_id": build_id, "release": release}


def test_the_code_scheme_orders_every_tag_and_stays_inside_androids_range():
    codes = [av.app_version(f"v{v}")["code"] for v in ("0.0.1", "0.1.0", "0.1.1", "0.2.0", "0.10.0", "1.0.0", "1.0.0-rc.1", "10.0.0")]
    assert codes == sorted(codes) and codes[5] == codes[6], "0.10.0 after 0.2.0; a pre-release at its final's code"
    assert av.app_version("v0.1.0")["code"] > av.DEV_CODE, "a tagged APK upgrades a dev build"
    assert av.version_code(2099, 999, 999) <= av.MAX_CODE
    with pytest.raises(av.VersionError, match="below 1000"):
        av.version_code(0, 1000, 0)
    with pytest.raises(av.VersionError, match="past Android"):
        av.version_code(2101, 0, 0)
    assert av.app_version("x", "")["version"] == "dev-local"


def test_the_cli_speaks_gradle_and_github_output():
    def run(*args):
        return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True)

    assert run("v0.1.0", "--gradle").stdout.strip() == "-PcaelzaVersion=0.1.0 -PcaelzaVersionCode=1000 -PcaelzaBuildId=v0.1.0"
    out = run("dev", "--sha", "abcdef1234567890", "--github")
    assert out.returncode == 0
    assert dict(line.split("=", 1) for line in out.stdout.strip().splitlines()) == {
        "version": "dev-abcdef12", "code": "1", "build_id": "dev-abcdef12", "release": "false",
        "gradle": "-PcaelzaVersion=dev-abcdef12 -PcaelzaVersionCode=1 -PcaelzaBuildId=dev-abcdef12",
    }
    assert run("v0.1.0").stdout.strip() == "release: versionName 0.1.0, versionCode 1000, build id v0.1.0"
    bad = run("v0.1000.0")
    assert bad.returncode == 1 and "below 1000" in bad.stderr


# --- the wiring ------------------------------------------------------------------

def test_gradle_reads_the_properties_and_signs_with_the_keystore_the_environment_names():
    assert 'findProperty("caelzaVersion") as String?' in GRADLE and '?: "0.0.0-dev"' in GRADLE
    assert 'findProperty("caelzaVersionCode") as String?)?.toIntOrNull() ?: 1' in GRADLE
    assert 'findProperty("caelzaBuildId") as String?' in GRADLE and '?: "dev"' in GRADLE
    assert "versionCode = caelzaVersionCode" in GRADLE and "versionName = caelzaVersion" in GRADLE
    assert 'buildConfigField("String", "BUILD_ID", "\\"$caelzaBuildId\\"")' in GRADLE
    assert 'System.getenv("CAELZA_KEYSTORE")' in GRADLE
    for env in ("CAELZA_KEYSTORE_PASSWORD", "CAELZA_KEY_ALIAS", "CAELZA_KEY_PASSWORD"):
        assert f'System.getenv("{env}")' in GRADLE, env
    assert 'signingConfig = if (releaseKeystore != null) signingConfigs.getByName("release") else signingConfigs.getByName("debug")' in GRADLE
    assert "versionName = \"0.1.0\"" not in GRADLE, "the version is the tag's, not a constant"
    logs = (KT / "logs" / "LogsActivity.kt").read_text()
    assert "build ${BuildConfig.BUILD_ID}" in logs, "the bug report's header shows the build id"


def test_release_yml_builds_the_app_for_the_tag_and_attaches_it():
    assert "\n  app:\n" in RELEASE
    job = RELEASE[RELEASE.index("\n  app:\n"):RELEASE.index("\n  release:\n")]
    assert "continue-on-error: true" in job, "a broken app build never holds the Runtime's release back"
    assert 'if [ "$GITHUB_REF_TYPE" = tag ]; then ref="$GITHUB_REF_NAME"; else ref=dev; fi' in job
    assert 'out=$(python3 scripts/app_version.py "$ref" --sha "$GITHUB_SHA" --github)' in job
    assert 'echo "$out" | tee -a "$GITHUB_OUTPUT"' in job
    assert "grep -qx 'release=true' <<<\"$out\"" in job, "a tag that names no release version does not get a dev APK"
    assert "secrets.ANDROID_KEYSTORE_BASE64" in job
    for secret in ("ANDROID_KEYSTORE_PASSWORD", "ANDROID_KEY_ALIAS", "ANDROID_KEY_PASSWORD"):
        assert f"CAELZA_{secret.removeprefix('ANDROID_')}: ${{{{ secrets.{secret} }}}}" in job, secret
    assert 'echo "CAELZA_KEYSTORE=$RUNNER_TEMP/release.keystore" >> "$GITHUB_ENV"' in job
    assert "assembleRelease testDebugUnitTest ${{ steps.version.outputs.gradle }}" in job
    assert 'suffix=""; [ "${{ steps.keystore.outputs.signed }}" = release ] || suffix="-debug-signed"' in job
    assert 'name="caelza-app-${ver}${suffix}.apk"' in job and 'sha256sum "$name" > "$name.sha256"' in job
    assert "apksigner" in job, "the signature is printed in the log"
    assert "name: caelza-app\n" in job, "the artifact matches the release job's caelza-* pattern"
    release_job = RELEASE[RELEASE.index("\n  release:\n"):]
    assert "needs: [build, app, mind]" in release_job and "pattern: caelza-*" in release_job
    assert "caelza-app-<version>.apk" in release_job
    assert "assembleDebug assembleRelease testDebugUnitTest" in ANDROID_CI, "CI takes the release build's path too"


def test_the_installers_pick_their_tarball_with_the_apk_beside_it():
    ver = "0.1.0"
    assets = [
        {"name": f"caelza-app-{ver}.apk", "url": "api://apk"},
        {"name": f"caelza-app-{ver}.apk.sha256", "url": "api://apk-sum"},
        {"name": f"caelza-{ver}-{TARGET}.tar.gz", "url": "api://tar"},
        {"name": f"caelza-{ver}-{TARGET}.tar.gz.sha256", "url": "api://tar-sum"},
        {"name": f"caelza-{ver}-x86_64-unknown-linux-gnu.tar.gz", "url": "api://other"},
    ]
    release = rg.parse_release({"tag_name": f"v{ver}", "assets": assets}, TARGET)
    assert (release.name, release.asset_url, release.sha_url) == (f"caelza-{ver}-{TARGET}.tar.gz", "api://tar", "api://tar-sum")
    # The same suffix rule in the Termux installer's inline Python and the app's installer.
    termux = (REPO_ROOT / "runtime" / "termux-install.sh").read_text()
    assert 'suffix = f"-{sys.argv[2]}.tar.gz"' in termux and "n.endswith(suffix)" in termux
    kt = (KT / "runtime" / "ReleaseInstaller.kt").read_text()
    assert 'val suffix = "-$target.tar.gz"' in kt
    guard = (REPO_ROOT / "caelza_body" / "runtime_guard.py").read_text()
    assert 'suffix = f"-{target}.tar.gz"' in guard


def test_the_docs_and_the_manifest_say_so():
    data = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
    app = data["android"]
    assert app["app_release_asset"] == "caelza-app-<version>.apk"
    assert (REPO_ROOT / app["app_version"]).samefile(SCRIPT)
    assert av.app_version(f"v{data['caelza']['version']}")["release"], "the manifest's version tags as a release"
    for doc, needle in (
        ("android/README.md", "python3 ../scripts/app_version.py v0.1.0 --gradle"),
        ("android/README.md", "ANDROID_KEYSTORE_BASE64"),
        ("runtime/README.md", "caelza-app-0.1.0.apk"),
        ("docs/design/android-app.md", "**Release.**"),
        ("docs/design/caelza-vision.md", "the release's Android leg"),
    ):
        assert needle in (REPO_ROOT / doc).read_text(), f"{doc}: {needle}"
    open_items = (REPO_ROOT / "docs/design/android-app.md").read_text().split("## 6. Open items")[1]
    assert "Signing and distribution" not in open_items and "release keystore still has to be made" in open_items
