"""The Mind from the release (vision M3's last open item).

`xanima-server`, the brain service, is a private workspace package upstream
(not on npm), so every `v*` tag packs it: `mind/pack.sh` builds the commit
`bundle/manifest.toml` pins and `npm pack`s the server workspace as
`caelza-mind-<version>.tgz`, release.yml's `mind` job attaches it beside the
Runtime tarballs and the APK, and `mind/install.sh` installs it on a hub or in
Termux as the `caelza-mind` launcher. These tests pin the wiring: the scripts
parse, the pin is one commit that the pack script reads the same way, the
installer picks its tarball with the others beside it, and the docs say so.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "bundle" / "manifest.toml"
PACK = REPO_ROOT / "mind" / "pack.sh"
INSTALL = REPO_ROOT / "mind" / "install.sh"
RELEASE = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text()
CI = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
MIND = tomllib.loads(MANIFEST.read_text())["components"]["mind"]


def test_the_scripts_parse_and_ci_parses_them_too():
    subprocess.run(["bash", "-n", str(PACK)], check=True)
    subprocess.run(["sh", "-n", str(INSTALL)], check=True)
    assert "bash -n mind/pack.sh" in CI and "sh -n mind/install.sh" in CI


def test_the_manifest_pins_one_commit_and_the_pack_script_reads_that_line():
    assert re.fullmatch(r"[0-9a-f]{40}", MIND["service_commit"])
    assert re.fullmatch(r"\d+\.\d+\.\d+", MIND["service_version"])
    assert MIND["service_asset"] == "caelza-mind-<version>.tgz"
    assert (REPO_ROOT / MIND["service_pack"]).samefile(PACK)
    assert (REPO_ROOT / MIND["service_install"]).samefile(INSTALL)
    pack = PACK.read_text()
    expr = re.search(r"sed -n -E '([^']+)' \"\$ROOT/bundle/manifest.toml\"", pack).group(1)
    found = subprocess.run(["sed", "-n", "-E", expr, str(MANIFEST)], check=True, capture_output=True, text=True).stdout.split()
    assert found == [MIND["service_commit"]], "the pack script's sed finds exactly the pinned commit"
    assert MIND["engine_repo"] in pack, "the pack script fetches the repo the manifest names"
    assert "npm pack --workspace xanima-server" in pack
    assert 'name="caelza-mind-$version.tgz"' in pack and 'sha256sum "$name" > "$name.sha256"' in pack
    check = "| grep -x 'package/dist/cli.js' >/dev/null ||"
    assert check in pack and check in INSTALL.read_text(), "both sides check the tarball is the built service"
    assert "grep -q" not in pack, "under pipefail a grep -q that quits early kills tar and fails the check"


def test_release_yml_packs_the_mind_for_the_tag_and_attaches_it():
    assert "\n  mind:\n" in RELEASE
    job = RELEASE[RELEASE.index("\n  mind:\n"):RELEASE.index("\n  release:\n")]
    assert "continue-on-error: true" in job, "a broken pack never holds the Runtime's release back"
    assert 'if [ "$GITHUB_REF_TYPE" = tag ]; then ver="${GITHUB_REF_NAME#v}"; else ver="dev-${GITHUB_SHA::8}"; fi' in job, \
        "the asset is named for the tag's version like the Runtime tarballs"
    assert './mind/pack.sh --version "${{ steps.version.outputs.ver }}"' in job
    assert "CAELZA_MIND_TOKEN: ${{ secrets.XANIMA_READ_TOKEN }}" in job, "a private xanima repo is fetched with the read token the secret holds"
    pack = PACK.read_text()
    assert 'if [ -n "${CAELZA_MIND_TOKEN:-}" ]; then' in pack and "http.extraheader=Authorization: Basic" in pack, \
        "the token travels as a header for the one fetch, never in the remote URL"
    assert "GITHUB_TOKEN" not in pack.split("set -euo pipefail", 1)[1].replace("GITHUB_TOKEN cannot read", ""), \
        "the workflow token is never tried: it cannot read another repo and a wrong header turns a public fetch into a 401"
    assert "name: caelza-mind\n" in job, "the artifact matches the release job's caelza-* pattern"
    assert "caelza-mind-*.tgz.sha256" in job
    release_job = RELEASE[RELEASE.index("\n  release:\n"):]
    assert "needs: [build, app, mind]" in release_job and "pattern: caelza-*" in release_job
    assert "caelza-mind-<version>.tgz" in release_job, "the release notes name the asset"


@pytest.mark.skipif(shutil.which("node") is None, reason="the installer's asset picker is node")
def test_the_installer_picks_the_mind_tarball_with_the_runtime_and_the_apk_beside_it(tmp_path):
    text = INSTALL.read_text()
    start = text.index("cat > \"$work/pick.js\" <<'EOF'\n") + len("cat > \"$work/pick.js\" <<'EOF'\n")
    picker = text[start:text.index("\nEOF\n", start)]
    (tmp_path / "pick.js").write_text(picker)
    ver = "0.2.0"
    assets = [
        {"name": f"caelza-{ver}-aarch64-linux-android.tar.gz", "url": "api://tar"},
        {"name": f"caelza-{ver}-aarch64-linux-android.tar.gz.sha256", "url": "api://tar-sum"},
        {"name": f"caelza-app-{ver}.apk", "url": "api://apk"},
        {"name": f"caelza-app-{ver}.apk.sha256", "url": "api://apk-sum"},
        {"name": f"caelza-mind-{ver}.tgz", "url": "api://mind"},
        {"name": f"caelza-mind-{ver}.tgz.sha256", "url": "api://mind-sum"},
    ]
    release = tmp_path / "release.json"
    release.write_text(json.dumps({"tag_name": f"v{ver}", "assets": assets}))
    out = subprocess.run(["node", str(tmp_path / "pick.js"), str(release)], check=True, capture_output=True, text=True)
    assert out.stdout.splitlines() == [f"v{ver}", f"caelza-mind-{ver}.tgz", "api://mind", "api://mind-sum"]
    # Without the Mind's asset (its pack was skipped): a clear refusal, not the Runtime's tarball.
    release.write_text(json.dumps({"tag_name": f"v{ver}", "assets": assets[:4]}))
    missing = subprocess.run(["node", str(tmp_path / "pick.js"), str(release)], capture_output=True, text=True)
    assert missing.returncode == 1 and "no caelza-mind-<version>.tgz asset" in missing.stderr
    # And the Runtime's installers never pick the Mind's tarball: their rule is the -<target>.tar.gz suffix.
    termux = (REPO_ROOT / "runtime" / "termux-install.sh").read_text()
    assert 'suffix = f"-{sys.argv[2]}.tar.gz"' in termux


def test_the_installer_lands_the_service_and_the_launcher_where_the_docs_say():
    text = INSTALL.read_text()
    for needle in (
        'DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/caelza"',
        'MIND_DIR="${CAELZA_MIND_DIR:-$DATA_DIR/mind}"',
        "process.exit(m >= 22 ? 0 : 1)",
        "sha256sum -c",
        "npm install --omit=dev --no-save --no-audit --no-fund --loglevel=error ./caelza-mind.tgz",
        'cli="$MIND_DIR/node_modules/xanima-server/dist/cli.js"',
        'cat > "$BIN_DIR/caelza-mind" <<EOF',
        'if [ "${CAELZA_SERVICE:-0}" = "1" ]; then',
        '"$HOME/.termux/boot/caelza-mind"',
        "caelza-mind.service",
        'ExecStart="$BIN_DIR/caelza-mind" serve',  # quoted: a HOME with a space
        "pkg install -y nodejs python make clang pkg-config jq",  # jq: the token lines in the next steps
        # A release asset with no .sha256 beside it is refused, not installed with a note in the scroll-back.
        'die "no .sha256 published beside $name; refusing to install it unverified (CAELZA_SKIP_CHECKSUM=1 to override)"',
        'elif [ "${CAELZA_SKIP_CHECKSUM:-0}" = "1" ]; then',
        "command -v sha256sum >/dev/null 2>&1 || die",
        # The launcher finds node on PATH at run time (a version manager moves it) and falls back to the one the install saw.
        "node=\\$(command -v node 2>/dev/null || printf '%s' \"$NODE\")",
        'exec "\\$node" "$cli" "\\$@"',
        # Termux scripts get Termux's own sh; /usr/bin/env is only there through termux-exec.
        'SHEBANG="$PREFIX/bin/sh"',
        "#!$SHEBANG",
    ):
        assert needle in text, needle
    assert 'caelza-mind" <<EOF\n#!/usr/bin/env sh' not in text, "the launcher's shebang follows the platform"
    for doc, needle in (
        ("README.md", "mind/install.sh | sh"),
        ("README.md", "caelza-mind serve"),
        ("bundle/README.md", "mind/install.sh"),
        ("bundle/README.md", "caelza-mind-<version>.tgz"),
        ("mind/README.md", "caelza-mind-<version>.tgz"),
        ("mind/README.md", "sh mind/install.sh"),
        ("mind/README.md", "caelza-mind token mint --agent main"),
        ("runtime/termux-install.sh", "mind/install.sh | sh"),
        ("docs/design/caelza-vision.md", "the Mind from the release"),
    ):
        assert needle in (REPO_ROOT / doc).read_text(), f"{doc}: {needle}"
