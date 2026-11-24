"""The Mind from the release (vision M3's last open item).

`xanima-server`, the brain service, is a private workspace package upstream
(not on npm), so every `v*` tag packs it: `mind/pack.sh` builds the commit
`bundle/manifest.toml` pins and `npm pack`s the server workspace as
`caelza-mind-<version>.tgz`, release.yml's `mind` job attaches it beside the
Runtime tarballs and the APK, and `mind/install.sh` installs it on a hub or in
Termux as the `caelza-mind` launcher. These tests pin the wiring: the scripts
parse, the pin is one commit that the pack script reads the same way, the
installer picks its tarball with the others beside it, the inner life is on
for the owner's agents in every install, and the docs say so.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import os
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
    assert "needs: [build, windows, app, mind]" in release_job and "pattern: caelza-*" in release_job
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


# --- the Mind at xanima 0.8.0, its inner life on -------------------------------------------

INSTALL_PS1 = REPO_ROOT / "mind" / "windows-install.ps1"
INSTALL_PAGE = REPO_ROOT / "runtime" / "overlay" / "crates" / "caelza-gateway" / "src" / "api_mind_install.rs"


def _inner_js(script: Path) -> str:
    text = script.read_text(encoding="utf-8").replace("\r\n", "\n")
    if script.suffix == ".sh":
        found = re.search(r"cat > \"\$work/inner-life\.cjs\" <<'JS'\n(.*?)\nJS\n", text, re.S)
    else:
        found = re.search(r"-Value @'\n(.*?)\n'@\n", text, re.S)
    assert found, f"{script.name} carries the inner-life lines"
    return found.group(1).strip()


def test_the_mind_is_xanima_0_8_from_source_and_the_npm_pins_wait():
    assert MIND["service_version"] == "0.8.0"
    assert MIND["service_commit"] == "af975ed9937b954ca937ea609be5073b6a6f2716", "xanima main at the v0.8.0 tag"
    assert MIND["tools"] == 43, "0.7.0's 42 plus brain_inner, for an agent token"
    # npm still has 0.7.0 (upstream's 0.8.0 publish failed): the plugin and engine pins do not move yet.
    assert MIND["version"] == "0.7.0" and MIND["engine_version"] == "0.7.0"
    text = MANIFEST.read_text(encoding="utf-8")
    assert "schema v31" in text and "npm 0.8.0 is pending" in text
    assert json.loads(MIND["inner_life"]) == {"brain": {"innerLife": {"excludeAgents": ["cael"]}}}


def test_every_install_turns_the_inner_life_on_the_same_way():
    sh, ps = _inner_js(INSTALL), _inner_js(INSTALL_PS1)
    assert sh == ps, "install.sh and windows-install.ps1 carry the same lines"
    assert sh.isascii(), "Set-Content -Encoding ascii writes it on Windows"
    assert 'excludeAgents: ["cael"]' in sh and '"innerLife" in cfg.brain' in sh
    page = INSTALL_PAGE.read_text(encoding="utf-8")
    assert 'pub const INNER_LIFE_EXCLUDED: &[&str] = &["cael"];' in page
    assert 'json!({"excludeAgents": INNER_LIFE_EXCLUDED})' in page
    # Before the service starts: it reads config.json once, when it starts.
    assert page.index('stage("tokens"') < page.index('stage("config"') < page.index('stage("start"')
    for script, mint, start in ((INSTALL, "Next:", None), (INSTALL_PS1, "# The Runtime's tokens", "if ($env:CAELZA_SERVICE -eq '1')")):
        text = script.read_text(encoding="utf-8")
        assert text.index("inner-life") < text.index(mint), f"{script.name}: before the service is used"
        if start:
            assert text.index("inner-life") < text.index(start)


@pytest.mark.skipif(shutil.which("node") is None, reason="the inner-life lines are node")
def test_the_inner_life_lines_write_the_block_and_keep_what_the_owner_set(tmp_path):
    js = tmp_path / "inner-life.cjs"
    js.write_text(_inner_js(INSTALL) + "\n")
    env = {k: v for k, v in os.environ.items() if not k.endswith("_SERVICE_ROOT")}

    def run(home: Path) -> str:
        out = subprocess.run(["node", str(js)], env={**env, "XANIMA_HOME_OVERRIDE": str(home)}, check=True, capture_output=True, text=True)
        return out.stdout

    fresh = tmp_path / "fresh"
    assert "inner life on" in run(fresh)
    cfg = fresh / ".xanima" / "service" / "config.json"
    assert json.loads(cfg.read_text()) == {"brain": {"innerLife": {"excludeAgents": ["cael"]}}}
    assert "kept" in run(fresh), "a second run changes nothing"

    shared = tmp_path / "shared"
    cfg = shared / ".xanima" / "service" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("\ufeff" + json.dumps({"tailnetHosts": ["100.64.0.2"], "brain": {"beliefMetadata": True}}), encoding="utf-8")
    run(shared)
    assert json.loads(cfg.read_text()) == {"tailnetHosts": ["100.64.0.2"], "brain": {"beliefMetadata": True, "innerLife": {"excludeAgents": ["cael"]}}}

    off = tmp_path / "off"
    cfg = off / ".xanima" / "service" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"brain": {"innerLife": False}}))
    assert "kept" in run(off)
    assert json.loads(cfg.read_text()) == {"brain": {"innerLife": False}}, "the owner turned it off; it stays off"

    # An un-migrated ~/.sharpwave: the service's own root, never a second, empty one.
    legacy = tmp_path / "legacy"
    (legacy / ".sharpwave").mkdir(parents=True)
    run(legacy)
    assert (legacy / ".sharpwave" / "service" / "config.json").is_file()
    assert not (legacy / ".xanima").exists()


def test_the_backend_says_the_inner_lines_once_and_the_docs_say_how_to_turn_it_on():
    xanima = (REPO_ROOT / "runtime" / "overlay" / "crates" / "caelza-memory" / "src" / "xanima.rs").read_text(encoding="utf-8")
    assert "&& !text_block.contains(block)" in xanima, "0.8.0 returns [inner] in text and as inner"
    readme = (REPO_ROOT / "mind" / "README.md").read_text(encoding="utf-8")
    for needle in ("### The inner life (xanima 0.8.0)", '{ "brain": { "innerLife": { "excludeAgents": ["cael"] } } }',
                   "`xanima-server` 0.8.0", "43 `brain_*` at 0.8.0", "restart the Mind"):
        assert needle in readme, needle
    assert "inner life" in (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "the Mind at xanima 0.8.0, its inner life on" in (REPO_ROOT / "docs" / "design" / "caelza-vision.md").read_text(encoding="utf-8")
    assert "Caelza's Mind has it on from xanima 0.8.0" in (REPO_ROOT / "docs" / "design" / "ether-hollow-open-world.md").read_text(encoding="utf-8")
