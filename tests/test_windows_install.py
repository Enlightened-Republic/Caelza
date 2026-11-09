"""The Windows installer and the release workflow must agree on the asset name."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = "x86_64-pc-windows-msvc"


def test_installer_and_release_agree():
    ps1 = (ROOT / "runtime" / "windows-install.ps1").read_text(encoding="utf-8")
    yml = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert f"$target = '{TARGET}'" in ps1
    assert "-$target.zip" in ps1
    assert f'name="caelza-$ver-{TARGET}"' in yml or f'$name = "caelza-$ver-{TARGET}"' in yml
    assert re.search(r"Compress-Archive .*\$zip", yml)
    assert "windows" in re.search(r"needs: \[(.*)\]\n\s+runs-on: ubuntu-latest\n\s+steps:\n\s+- uses: actions/download-artifact", yml).group(1)


def test_installer_verifies_checksum_and_needs_no_admin():
    ps1 = (ROOT / "runtime" / "windows-install.ps1").read_text(encoding="utf-8")
    assert "Get-FileHash" in ps1 and "Checksum mismatch" in ps1
    assert "'User'" in ps1 and "'Machine'" not in ps1


def test_the_launcher_opens_caels_setup_in_the_browser_not_the_console_wizard():
    # The PC's first run is the same simplified setup the phone gets: the dashboard lands on
    # /setup until an agent exists, and the pairing screen fills its own code in on loopback.
    cmd = (ROOT / "runtime" / "windows" / "caelza-launch.cmd").read_text(encoding="utf-8")
    assert "quickstart" not in cmd, "no console wizard on a PC"
    assert 'start "Caelza agent" /min "%HERE%caelza.exe" daemon' in cmd
    assert '"%URL%/health"' in cmd and "goto open" in cmd, "waits for the gateway before opening the browser"
    assert 'set "URL=http://127.0.0.1:42617"' in cmd and 'start "" "%URL%/"' in cmd
    assert "if %tries% geq 30 goto slow" in cmd, "a slow start is explained, not hung on"
    ps1 = (ROOT / "runtime" / "windows-install.ps1").read_text(encoding="utf-8")
    assert "caelza quickstart" not in ps1 and "caelza daemon" in ps1 and "127.0.0.1:42617" in ps1
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Caelza-Setup.exe" in readme and "caelza daemon" in readme
    assert "caelza quickstart\n```" not in readme.split("On Windows 10/11")[1].split("On the phone")[0]
