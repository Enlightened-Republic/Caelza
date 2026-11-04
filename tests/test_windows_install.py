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
