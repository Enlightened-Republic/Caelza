# Installs the Caelza Runtime on Windows 10/11 (x86_64) from the latest GitHub release.
#
#   irm https://raw.githubusercontent.com/Enlightened-Republic/Caelza/main/runtime/windows-install.ps1 | iex
#
# EXPERIMENTAL: the Windows build is new and has not had a real-world run yet.
# It installs to %LOCALAPPDATA%\Caelza, verifies the download against its
# published SHA-256, and adds that folder to your user PATH (no admin needed).
# Config lives in %USERPROFILE%\.caelza. Set $env:CAELZA_VERSION (e.g. "0.1.1")
# to pick a release instead of the latest.

$ErrorActionPreference = 'Stop'
$repo   = 'Enlightened-Republic/Caelza'
$target = 'x86_64-pc-windows-msvc'
$dest   = Join-Path $env:LOCALAPPDATA 'Caelza'

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$api = if ($env:CAELZA_VERSION) { "https://api.github.com/repos/$repo/releases/tags/v$($env:CAELZA_VERSION.TrimStart('v'))" }
       else { "https://api.github.com/repos/$repo/releases/latest" }
$rel = Invoke-RestMethod -Uri $api -Headers @{ 'User-Agent' = 'caelza-installer' }
$asset = $rel.assets | Where-Object { $_.name -like "caelza-*-$target.zip" } | Select-Object -First 1
$sum   = $rel.assets | Where-Object { $_.name -like "caelza-*-$target.zip.sha256" } | Select-Object -First 1
if (-not $asset -or -not $sum) {
    throw "Release $($rel.tag_name) has no Windows build ($target). It is experimental; check https://github.com/$repo/releases for one."
}

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("caelza-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    $zip = Join-Path $tmp $asset.name
    Write-Host "Downloading $($asset.name) ..."
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
    $want = ((Invoke-RestMethod -Uri $sum.browser_download_url -UseBasicParsing) -split '\s+')[0].ToLower()
    $got  = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    if ($want -ne $got) { throw "Checksum mismatch for $($asset.name): expected $want, got $got. Not installing." }

    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $inner = Get-ChildItem $tmp -Directory | Where-Object { $_.Name -like 'caelza-*' } | Select-Object -First 1
    if (-not $inner -or -not (Test-Path (Join-Path $inner.FullName 'caelza.exe'))) { throw 'The archive has no caelza.exe.' }

    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Copy-Item -Path (Join-Path $inner.FullName '*') -Destination $dest -Recurse -Force
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (($userPath -split ';') -notcontains $dest) {
    [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $dest), 'User')
    Write-Host "Added $dest to your PATH. Open a new terminal to use it."
}

Write-Host ""
Write-Host "Installed Caelza $($rel.tag_name) to $dest"
Write-Host "Next (in a new terminal):  caelza daemon"
Write-Host "Then open:                 http://127.0.0.1:42617   (Cael walks you through setup; click Pair on the first screen)"
Write-Host "Prefer a Start menu entry? Caelza-Setup.exe on the same release does all of this with one click."
