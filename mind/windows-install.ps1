# Installs the Caelza Mind (xanima-server, the brain service: long-term memory)
# on Windows 10/11 from the latest Caelza release. The Windows twin of install.sh.
#
#   irm https://raw.githubusercontent.com/Enlightened-Republic/Caelza/main/mind/windows-install.ps1 | iex
#
# What it does, in order:
#   1. needs Node 22 or newer (https://nodejs.org, or `winget install OpenJS.NodeJS.LTS`);
#      says so and stops otherwise
#   2. finds the release (latest, or $env:CAELZA_VERSION) and its caelza-mind-<ver>.tgz
#      through the GitHub API, downloads it, checks the .sha256 beside it (a release
#      with none is refused unless $env:CAELZA_SKIP_CHECKSUM = "1")
#   3. installs it under %LOCALAPPDATA%\Caelza\mind with `npm install --omit=dev` (the
#      two native sqlite modules come prebuilt for Windows x64 on Node 22: no compiler)
#   4. writes caelza-mind.cmd beside caelza.exe (%LOCALAPPDATA%\Caelza, on your PATH
#      since the Runtime's install), mints the Runtime's tokens into %USERPROFILE%\.xanima\tokens
#      (main: read,write; cael: read; a provision token for any agent made later) when they
#      are not there yet, and with $env:CAELZA_SERVICE = "1" puts a "Caelza Mind" shortcut in
#      your Startup folder so the service starts at logon, minimised
#   5. points the Runtime at it (`caelza config set memory.backend xanima`) when caelza is on
#      PATH and not running; else prints that line for after you stop it
#
# Env:
#   CAELZA_VERSION=0.2.0       a specific release tag (default: the latest release)
#   CAELZA_ARCHIVE=C:\x.tgz    install from a tarball you already have; no network
#   CAELZA_MIND_DIR=...        where it lands (default %LOCALAPPDATA%\Caelza\mind)
#   CAELZA_BIN_DIR=...         where the launcher goes (default %LOCALAPPDATA%\Caelza)
#   CAELZA_SERVICE=1           also the Startup-folder shortcut
#   CAELZA_SKIP_CHECKSUM=1     install a release asset that has no .sha256 beside it
#   GITHUB_TOKEN=ghp_...       only needed while the repo is private
#   CAELZA_API_BASE=...        the GitHub API's address (default https://api.github.com; the tests point it at a stand-in)
#
# The Start menu's Caelza entry (caelza-launch.cmd) starts the Mind minimised before the
# Runtime once this launcher exists, so after this script "Caelza" does both. Re-running
# is safe: a newer release replaces the install in place, the brains under .xanima stay.

$ErrorActionPreference = 'Stop'
$repo = 'Enlightened-Republic/Caelza'
if ($env:CAELZA_API_BASE) { $apiBase = $env:CAELZA_API_BASE.TrimEnd('/') } else { $apiBase = 'https://api.github.com' }
$onWindows = ($env:OS -eq 'Windows_NT')
if ($env:LOCALAPPDATA) { $base = Join-Path $env:LOCALAPPDATA 'Caelza' } else { $base = Join-Path $HOME '.local/share/caelza' }
if ($env:CAELZA_MIND_DIR) { $mindDir = $env:CAELZA_MIND_DIR } else { $mindDir = Join-Path $base 'mind' }
if ($env:CAELZA_BIN_DIR) { $binDir = $env:CAELZA_BIN_DIR } else { $binDir = $base }
$xanimaHome = Join-Path $HOME '.xanima'
$tokensDir = Join-Path $xanimaHome 'tokens'

function Say($text) { Write-Host "[caelza-mind] $text" -ForegroundColor Cyan }

# 1. Node 22+ and npm.
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCmd) {
    throw "Node.js is not installed (or not on PATH). The Mind runs on Node 22 or newer: https://nodejs.org (the LTS build), or in a terminal: winget install OpenJS.NodeJS.LTS. Then open a new terminal and run this again."
}
$nodeExe = $nodeCmd.Source
$major = [int](& $nodeExe -p "process.versions.node.split('.')[0]")
if ($major -lt 22) { throw "Node $(& $nodeExe --version) is too old; the Mind needs Node 22 or newer: https://nodejs.org" }
$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npmCmd) { throw "npm is not on PATH (it comes with Node.js); open a new terminal after installing Node and run this again." }
if (-not (Get-Command tar -ErrorAction SilentlyContinue)) { throw "tar is missing (Windows 10 1803+ ships it as tar.exe)." }

$headers = @{ 'User-Agent' = 'caelza-mind-installer'; 'Accept' = 'application/vnd.github+json' }
if ($env:GITHUB_TOKEN) { $headers['Authorization'] = "token $($env:GITHUB_TOKEN)" }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("caelza-mind-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    # 2. The tarball: yours, or the release's, checked against its published sum.
    $tag = ''
    if ($env:CAELZA_ARCHIVE) {
        $archive = $env:CAELZA_ARCHIVE
        if (-not (Test-Path $archive)) { throw "no such file: $archive" }
        Say "installing from $archive"
    } else {
        if ($env:CAELZA_VERSION) { $api = "$apiBase/repos/$repo/releases/tags/v$($env:CAELZA_VERSION.TrimStart('v'))" }
        else { $api = "$apiBase/repos/$repo/releases/latest" }
        Say "looking up the release ($api)"
        $rel = Invoke-RestMethod -Uri $api -Headers $headers
        $tag = $rel.tag_name
        # The Mind's tarball sits beside the Runtime's -<target> archives, the Windows zip and the APK.
        $asset = $rel.assets | Where-Object { $_.name -match '^caelza-mind-.+\.tgz$' } | Select-Object -First 1
        $sum   = $rel.assets | Where-Object { $_.name -match '^caelza-mind-.+\.tgz\.sha256$' } | Select-Object -First 1
        if (-not $asset) { throw "release $tag has no caelza-mind-<version>.tgz asset (the Mind's pack may have been skipped; see the release's workflow log)." }
        $archive = Join-Path $tmp $asset.name
        Say "downloading $($asset.name) ($tag)"
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $archive -UseBasicParsing -Headers $headers
        if ($sum) {
            $want = ((Invoke-RestMethod -Uri $sum.browser_download_url -UseBasicParsing -Headers $headers) -split '\s+')[0].ToLower()
            $got  = (Get-FileHash $archive -Algorithm SHA256).Hash.ToLower()
            if ($want -ne $got) { throw "Checksum mismatch for $($asset.name): expected $want, got $got. Not installing." }
            Say "checksum ok"
        } elseif ($env:CAELZA_SKIP_CHECKSUM -eq '1') {
            Say "no .sha256 published for $($asset.name); CAELZA_SKIP_CHECKSUM=1, installing it unverified"
        } else {
            # pack.sh always writes the sum and release.yml uploads both: a missing one is a broken or tampered release.
            throw "no .sha256 published beside $($asset.name); refusing to install it unverified (set CAELZA_SKIP_CHECKSUM=1 to override)."
        }
    }
    $listing = & tar -tzf $archive
    if ($LASTEXITCODE -ne 0 -or ($listing -notcontains 'package/dist/cli.js')) { throw "$archive is not a caelza-mind tarball (no package/dist/cli.js inside)." }

    # 3. The install: a minimal project around it, so npm has somewhere to put node_modules
    #    and the tarball stays beside it as the record of what is installed.
    New-Item -ItemType Directory -Force -Path $mindDir | Out-Null
    $pkg = Join-Path $mindDir 'package.json'
    if (-not (Test-Path $pkg)) {
        Set-Content -Path $pkg -Value "{`n  `"name`": `"caelza-mind`",`n  `"private`": true,`n  `"description`": `"the Caelza Mind: xanima-server, installed by mind/windows-install.ps1`"`n}`n" -Encoding ascii
    }
    Copy-Item -Path $archive -Destination (Join-Path $mindDir 'caelza-mind.tgz') -Force
    Say "installing into $mindDir (npm install --omit=dev; the native sqlite modules are prebuilt for Windows x64 on Node 22)"
    Push-Location $mindDir
    try {
        & $npmCmd.Source install --omit=dev --no-save --no-audit --no-fund --loglevel=error ./caelza-mind.tgz
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($code -ne 0) { throw "npm install failed (exit $code). Node 22+ on Windows x64 and a network path to registry.npmjs.org are what it needs." }
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
$cli = [IO.Path]::Combine($mindDir, 'node_modules', 'xanima-server', 'dist', 'cli.js')
if (-not (Test-Path $cli)) { throw "the install left no $cli" }

# 4. The launcher: node from PATH at run time first (a version manager moves it), else the one this install saw.
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
$launcher = Join-Path $binDir 'caelza-mind.cmd'
$cmd = @(
    '@echo off',
    "rem Caelza Mind: xanima-server, installed by mind/windows-install.ps1 into $mindDir",
    "set `"NODE=$nodeExe`"",
    'where node >nul 2>&1 && set "NODE=node"',
    "`"%NODE%`" `"$cli`" %*"
) -join "`r`n"
Set-Content -Path $launcher -Value ($cmd + "`r`n") -Encoding ascii -NoNewline
Say "launcher -> $launcher"

# The Runtime's tokens: one per agent, minted once (a re-run keeps the files it finds).
New-Item -ItemType Directory -Force -Path $tokensDir | Out-Null
$minted = @()
foreach ($t in @(@('main', 'read,write'), @('cael', 'read'), @('provision', 'provision'))) {
    $file = Join-Path $tokensDir "$($t[0]).token"
    if (Test-Path $file) { continue }
    $agent = $t[0]
    if ($agent -eq 'provision') { $agent = 'provisioner' }
    $json = & $nodeExe $cli token mint --agent $agent --scopes $t[1] --json
    if ($LASTEXITCODE -ne 0) { throw "token mint for $agent failed" }
    $token = ($json | ConvertFrom-Json).token
    if (-not $token) { throw "token mint for $agent answered no token" }
    Set-Content -Path $file -Value $token -Encoding ascii -NoNewline
    $minted += $t[0]
}
if ($minted.Count) { Say "tokens -> $tokensDir ($($minted -join ', '))" } else { Say "tokens already in $tokensDir" }

if ($env:CAELZA_SERVICE -eq '1') {
    if ($onWindows) {
        $startup = [Environment]::GetFolderPath('Startup')
        $lnk = Join-Path $startup 'Caelza Mind.lnk'
        $shell = New-Object -ComObject WScript.Shell
        $s = $shell.CreateShortcut($lnk)
        $s.TargetPath = "$env:ComSpec"
        $s.Arguments = "/c start `"Caelza Mind`" /min `"$launcher`" serve"
        $s.WorkingDirectory = $binDir
        $s.WindowStyle = 7
        $s.Description = 'Start the Caelza Mind (the brain service on 127.0.0.1:18790) at logon'
        $s.Save()
        Say "Startup shortcut -> $lnk (the Mind starts minimised when you log on)"
    } else {
        Say "CAELZA_SERVICE=1 makes a Startup-folder shortcut on Windows; here, start it yourself: caelza-mind serve"
    }
}

# 5. Point the Runtime at the Mind when that is safe: caelza on PATH and not running.
$wired = $false
$caelza = Get-Command caelza -ErrorAction SilentlyContinue
if ($caelza) {
    $running = $false
    try { Invoke-RestMethod -Uri 'http://127.0.0.1:42617/health' -TimeoutSec 2 | Out-Null; $running = $true } catch { $running = $false }
    if ($running) {
        Say "the Runtime is running, so its config is left alone; after you stop it: caelza config set memory.backend xanima"
    } else {
        & $caelza.Source config set memory.backend xanima | Out-Null
        if ($LASTEXITCODE -eq 0) { $wired = $true; Say "Runtime config: memory.backend = xanima (mind/caelza-mind.example.toml has the full block)" }
        else { Say "could not set memory.backend; run it yourself: caelza config set memory.backend xanima" }
    }
} else {
    Say "caelza is not on PATH yet; once the Runtime is installed: caelza config set memory.backend xanima"
}

Write-Host ""
if ($tag) { Write-Host "Installed the Caelza Mind $tag to $mindDir" } else { Write-Host "Installed the Caelza Mind to $mindDir" }
Write-Host "Next:"
Write-Host "  caelza-mind serve                 # the brain service on http://127.0.0.1:18790 (the Start menu's Caelza does this too, now that the launcher exists)"
if (-not $wired) { Write-Host "  caelza config set memory.backend xanima   # with the Runtime stopped: its own memory becomes the brain service" }
Write-Host "  caelza memory stats               # the smoke test, with both running"
