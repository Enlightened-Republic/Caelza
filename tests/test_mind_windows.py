"""The Mind on Windows: mind/windows-install.ps1, the installer's twin for a PC.

It mirrors mind/install.sh step for step (the release's tarball against its
.sha256, the tar listing check, `npm install --omit=dev`, the launcher), adds
what a PC needs (the tokens minted, the Runtime pointed at the service, a
Startup-folder shortcut), and the Start menu's launcher starts the Mind before
the Runtime once the launcher is there. With `pwsh` on PATH the installer runs
here against the packed tarball; CI has no pwsh and skips that one.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PS1 = (REPO_ROOT / "mind" / "windows-install.ps1").read_text(encoding="utf-8")
SH = (REPO_ROOT / "mind" / "install.sh").read_text(encoding="utf-8")
LAUNCH = (REPO_ROOT / "runtime" / "windows" / "caelza-launch.cmd").read_text(encoding="utf-8")
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
FAQ = (REPO_ROOT / "guide" / "FAQ.md").read_text(encoding="utf-8")
MIND_README = (REPO_ROOT / "mind" / "README.md").read_text(encoding="utf-8")


def test_the_windows_installer_mirrors_the_linux_one():
    for needle in (
        "$repo = 'Enlightened-Republic/Caelza'",
        "'^caelza-mind-.+\\.tgz$'",
        "'^caelza-mind-.+\\.tgz\\.sha256$'",
        "(Get-FileHash $archive -Algorithm SHA256).Hash.ToLower()",
        "$listing -notcontains 'package/dist/cli.js'",
        "install --omit=dev --no-save --no-audit --no-fund --loglevel=error ./caelza-mind.tgz",
        "[IO.Path]::Combine($mindDir, 'node_modules', 'xanima-server', 'dist', 'cli.js')",
        "Join-Path $binDir 'caelza-mind.cmd'",
        # The release asset with no .sha256 beside it is refused, as install.sh refuses it.
        "refusing to install it unverified (set CAELZA_SKIP_CHECKSUM=1 to override)",
        "$env:CAELZA_SKIP_CHECKSUM -eq '1'",
        # Node 22+, as the service's engines field and install.sh say.
        "if ($major -lt 22)",
        "winget install OpenJS.NodeJS.LTS",
        "$ErrorActionPreference = 'Stop'",
    ):
        assert needle in PS1, needle
    # The two agree on the tarball's name, the inner check and the npm line.
    assert "/^caelza-mind-.+\\.tgz$/" in SH and "grep -x 'package/dist/cli.js'" in SH
    assert "npm install --omit=dev --no-save --no-audit --no-fund --loglevel=error ./caelza-mind.tgz" in SH
    # PowerShell 5.1 (Windows' own) runs it: none of 7's shorthand.
    assert " ?? " not in PS1 and "$IsWindows" not in PS1
    assert "$env:OS -eq 'Windows_NT'" in PS1


def test_the_launcher_finds_node_at_run_time_and_the_tokens_are_minted_once():
    assert "where node >nul 2>&1 && set \"NODE=node\"" in PS1, "node from PATH at run time (a version manager moves it)"
    assert "`\"%NODE%`\" `\"$cli`\" %*" in PS1
    # main read,write; Cael read; a provision token for agents made later; each file kept when it exists.
    assert "@('main', 'read,write'), @('cael', 'read'), @('provision', 'provision')" in PS1
    assert "if (Test-Path $file) { continue }" in PS1
    assert "token mint --agent $agent --scopes $t[1] --json" in PS1
    assert "($json | ConvertFrom-Json).token" in PS1, "ConvertFrom-Json where install.sh needs jq"
    assert "Join-Path $xanimaHome 'tokens'" in PS1 and "Join-Path $HOME '.xanima'" in PS1
    # The Runtime is pointed at the service only when caelza is on PATH and not answering on its port.
    assert "Invoke-RestMethod -Uri 'http://127.0.0.1:42617/health' -TimeoutSec 2" in PS1
    assert "config set memory.backend xanima" in PS1
    # The Startup-folder shortcut needs no admin; on anything but Windows it is only a note.
    assert "[Environment]::GetFolderPath('Startup')" in PS1 and "'Caelza Mind.lnk'" in PS1
    assert "New-Object -ComObject WScript.Shell" in PS1 and "if ($onWindows) {" in PS1


def test_the_start_menu_launcher_starts_the_mind_before_the_runtime():
    block = LAUNCH.split('if exist "%HERE%caelza-mind.cmd"', 1)[1].split(")", 1)[0]
    assert 'curl.exe -s -f -o nul "http://127.0.0.1:18790/health"' in block, "not started twice"
    assert 'start "Caelza Mind" /min "%HERE%caelza-mind.cmd" serve' in block
    assert LAUNCH.index('if exist "%HERE%caelza-mind.cmd"') < LAUNCH.index('curl.exe -s -f -o nul "%URL%/health" >nul 2>&1 && goto open')


def test_the_docs_say_so():
    assert "mind/windows-install.ps1 | iex" in README
    assert "mind/windows-install.ps1" in FAQ.split("## Can I use Caelza on a Windows PC?", 1)[1].split("\n## ", 1)[0]
    assert "mind/windows-install.ps1" in FAQ.split("## What is the Mind?", 1)[1].split("\n## ", 1)[0]
    assert "mind/windows-install.ps1" in MIND_README and "caelza-mind.cmd" in MIND_README


def _tarball() -> Path:
    tarball = Path(os.environ.get("CAELZA_MIND_TARBALL", "/home/user/scratch/mind-pack/caelza-mind-0.2.0-test.tgz"))
    if not tarball.is_file():
        pytest.skip("no packed Mind tarball at CAELZA_MIND_TARBALL (mind/pack.sh makes one)")
    return tarball


def _run_installer(tmp_path: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = dict(os.environ, HOME=str(home), CAELZA_MIND_DIR=str(tmp_path / "mind"), CAELZA_BIN_DIR=str(tmp_path / "bin"), NO_PROXY="127.0.0.1", no_proxy="127.0.0.1", **extra)
    return subprocess.run(
        ["pwsh", "-NoLogo", "-NonInteractive", "-File", str(REPO_ROOT / "mind" / "windows-install.ps1")],
        env=env, capture_output=True, text=True, timeout=900,
    )


def _check_install(tmp_path: Path) -> None:
    assert (tmp_path / "mind" / "node_modules" / "xanima-server" / "dist" / "cli.js").is_file()
    assert (tmp_path / "mind" / "caelza-mind.tgz").is_file(), "the tarball stays beside the install as the record of what is installed"
    launcher = (tmp_path / "bin" / "caelza-mind.cmd").read_text(newline="")
    assert launcher.startswith("@echo off\r\n") and "dist/cli.js" in launcher and launcher.endswith("%*\r\n")
    for name in ("main", "cael", "provision"):
        token = (tmp_path / "home" / ".xanima" / "tokens" / f"{name}.token").read_text()
        assert token.startswith("swt_") and "\n" not in token


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="needs PowerShell 7 (pwsh) to run the installer here")
def test_the_installer_runs_against_the_packed_tarball(tmp_path):
    out = _run_installer(tmp_path, CAELZA_ARCHIVE=str(_tarball()))
    assert out.returncode == 0, out.stdout + out.stderr
    _check_install(tmp_path)
    # A second run keeps the tokens it finds and still ends well.
    before = {n: (tmp_path / "home" / ".xanima" / "tokens" / f"{n}.token").read_text() for n in ("main", "cael", "provision")}
    again = _run_installer(tmp_path, CAELZA_ARCHIVE=str(_tarball()))
    assert again.returncode == 0, again.stdout + again.stderr
    assert "tokens already in" in again.stdout
    assert before == {n: (tmp_path / "home" / ".xanima" / "tokens" / f"{n}.token").read_text() for n in ("main", "cael", "provision")}


class _Release(BaseHTTPRequestHandler):
    """A stand-in for the GitHub release API and its asset downloads."""

    tarball: bytes = b""
    with_sum = True
    name = "caelza-mind-0.2.0.tgz"

    def log_message(self, *args):  # noqa: D102 - quiet
        pass

    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server's name
        base = f"http://127.0.0.1:{self.server.server_address[1]}"
        if "/releases/" in self.path:
            assets = [
                {"name": "caelza-0.2.0-x86_64-pc-windows-msvc.zip", "browser_download_url": f"{base}/download/zip"},
                {"name": self.name, "browser_download_url": f"{base}/download/{self.name}"},
            ]
            if self.with_sum:
                assets.append({"name": f"{self.name}.sha256", "browser_download_url": f"{base}/download/{self.name}.sha256"})
            self._send(json.dumps({"tag_name": "v0.2.0", "assets": assets}).encode(), "application/json")
        elif self.path == f"/download/{self.name}":
            self._send(self.tarball, "application/octet-stream")
        elif self.path == f"/download/{self.name}.sha256":
            self._send(f"{hashlib.sha256(self.tarball).hexdigest()}  {self.name}\n".encode(), "text/plain")
        else:
            self.send_response(404)
            self.end_headers()


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="needs PowerShell 7 (pwsh) to run the installer here")
def test_the_installer_takes_the_release_asset_and_refuses_one_without_a_checksum(tmp_path):
    _Release.tarball = _tarball().read_bytes()
    _Release.with_sum = True
    server = HTTPServer(("127.0.0.1", 0), _Release)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        out = _run_installer(tmp_path, CAELZA_API_BASE=base)
        assert out.returncode == 0, out.stdout + out.stderr
        assert "checksum ok" in out.stdout and "Installed the Caelza Mind v0.2.0" in out.stdout
        _check_install(tmp_path)
        # No .sha256 beside the asset: refused, nothing installed.
        _Release.with_sum = False
        bare = tmp_path / "bare"
        bare.mkdir()
        refused = _run_installer(bare, CAELZA_API_BASE=base)
        assert refused.returncode != 0
        assert "refusing to install it unverified" in refused.stdout + refused.stderr
        assert not (bare / "mind").exists()
    finally:
        server.shutdown()
