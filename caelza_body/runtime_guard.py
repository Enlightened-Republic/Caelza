"""The Runtime binary under the supervisor's guard (vision §3.5, M6).

Stdlib only, like the supervisor that imports it, and deny-listed from
self-modification with it. The agent never holds the compiler: CI builds the
`caelza` binary from this repo (`.github/workflows/release.yml`), and this
module pulls a release onto the phone the way the Body's own code is
promoted: fetch, verify, probe, snapshot the config, swap, keep the last
good one, roll back when the new one does not hold.

Layout under the Body's state dir (``~/.caelza-body``)::

    runtime/
      0.1.0/            caelza + web/dist + the notices, from one release archive
      0.1.1/
      current  -> 0.1.1 the binary the supervisor runs (`caelza daemon`)
      last-good -> 0.1.0 what a crash loop falls back to
    snapshots/caelza-config-<stamp>.tar.gz   ~/.caelza before each swap
    run/runtime-restart                       asks the supervisor to restart the Runtime child

`caelza-body runtime update` runs the pipeline (`update`); the supervisor
only reads the restart request, runs the child, and rolls `current` back to
`last-good` on a crash loop (`caelza_body/supervisor.py`).
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REPO = "Enlightened-Republic/caelza"
RELEASES_API = "https://api.github.com/repos/{repo}/releases"
RUNTIME_DIR = "runtime"
CURRENT = "current"
LAST_GOOD = "last-good"
RESTART_REQUEST = "runtime-restart"
PROBE_PORT = 42619
PROBE_TIMEOUT = 60.0
CONFIG_SNAPSHOTS = "snapshots"
KEEP_CONFIG_SNAPSHOTS = 10
#: What a config snapshot carries from ~/.caelza: the config and what the
#: agent may change through its tools. Data (sessions, memory, run state) stays out.
CONFIG_SNAPSHOT_PATHS = ("config.toml", "agents", "shared")

_VERSION = re.compile(r"^caelza\s+(\d+\.\d+\.\d+\S*)")


# ---------------------------------------------------------------------------
# Where things are
# ---------------------------------------------------------------------------

def default_target() -> str:
    """The release target for this machine: Termux is Android."""
    machine = platform.machine().lower()
    if "com.termux" in os.environ.get("PREFIX", ""):
        return "aarch64-linux-android"
    if machine in ("aarch64", "arm64"):
        return "aarch64-unknown-linux-gnu"
    return "x86_64-unknown-linux-gnu"


def runtime_root(home: Path | str) -> Path:
    return Path(home) / RUNTIME_DIR


def _link_target(link: Path) -> str | None:
    try:
        return os.readlink(link)
    except OSError:
        return None


def current_version(home: Path | str) -> str | None:
    return _link_target(runtime_root(home) / CURRENT)


def last_good_version(home: Path | str) -> str | None:
    return _link_target(runtime_root(home) / LAST_GOOD)


def version_dir(home: Path | str, version: str) -> Path:
    return runtime_root(home) / version


def current_binary(home: Path | str) -> Path | None:
    """The `caelza` the supervisor should run, or None when none is installed."""
    version = current_version(home)
    if not version:
        return None
    binary = version_dir(home, version) / "caelza"
    return binary if binary.is_file() else None


def installed_versions(home: Path | str) -> list[str]:
    root = runtime_root(home)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.is_symlink() and (p / "caelza").is_file())


def version_of(binary: Path | str, run=subprocess.run) -> str | None:
    """`caelza --version` → `0.8.6`; None when the binary does not answer."""
    try:
        out = run([str(binary), "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    m = _VERSION.match((out.stdout or "").strip())
    return m.group(1) if m else None


def status(home: Path | str) -> dict:
    binary = current_binary(home)
    return {
        "root": str(runtime_root(home)),
        "current": current_version(home),
        "last_good": last_good_version(home),
        "installed": installed_versions(home),
        "binary": str(binary) if binary else None,
        "restart_requested": read_restart_request(home),
    }


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Release:
    tag: str
    version: str
    name: str
    asset_url: str
    sha_url: str | None


def _headers(token: str | None, accept: str) -> dict[str, str]:
    h = {"Accept": accept, "User-Agent": "caelza-body runtime guard"}
    if token:
        h["Authorization"] = f"token {token}"
    return h


def http_get(url: str, headers: dict[str, str] | None = None, timeout: float = 120.0) -> bytes:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https URLs from the release API
        return resp.read()


def parse_release(data: dict, target: str) -> Release:
    """The archive and checksum assets for `target` in one release's JSON."""
    tag = str(data.get("tag_name") or "")
    suffix = f"-{target}.tar.gz"
    assets = {a.get("name", ""): a for a in data.get("assets", []) if isinstance(a, dict)}
    archive = next((a for n, a in assets.items() if n.endswith(suffix)), None)
    if archive is None:
        raise LookupError(f"release {tag or '?'} has no {suffix} asset (the Android build is marked experimental and may have been skipped)")
    name = archive["name"]
    version = name[len("caelza-"):-len(suffix)] if name.startswith("caelza-") else tag.lstrip("v")
    sha = assets.get(name + ".sha256")
    return Release(tag=tag, version=version, name=name, asset_url=archive["url"],
                   sha_url=sha["url"] if sha else None)


def find_release(repo: str = DEFAULT_REPO, target: str | None = None, tag: str | None = None,
                 token: str | None = None, fetch=http_get) -> Release:
    """The latest release (or `tag`) and its asset for `target`."""
    base = RELEASES_API.format(repo=repo)
    url = f"{base}/tags/{tag}" if tag else f"{base}/latest"
    raw = fetch(url, _headers(token, "application/vnd.github+json"))
    data = json.loads(raw)
    return parse_release(data, target or default_target())


def download(url: str, dest: Path | str, token: str | None = None, fetch=http_get) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(fetch(url, _headers(token, "application/octet-stream")))
    return dest


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sha256(archive: Path | str, sha_text: str) -> str:
    """`sha256sum` output (`<hex>  <name>`) against the archive; the hex on success."""
    expected = sha_text.strip().split()[0].lower() if sha_text.strip() else ""
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError(f"checksum file is not a sha256: {sha_text[:80]!r}")
    actual = sha256_file(archive)
    if actual != expected:
        raise ValueError(f"checksum mismatch for {Path(archive).name}: expected {expected[:12]}…, got {actual[:12]}…")
    return actual


def _safe_member(member: tarfile.TarInfo) -> bool:
    name = member.name
    if name.startswith("/") or name.startswith("\\"):
        return False
    parts = Path(name).parts
    if ".." in parts:
        return False
    if member.issym() or member.islnk():
        link = member.linkname
        if link.startswith("/") or ".." in Path(link).parts:
            return False
    if member.isdev():
        return False
    return True


def unpack(archive: Path | str, into: Path | str) -> Path:
    """Extract a release archive into `into`; the directory holding `caelza`."""
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not _safe_member(member):
                raise ValueError(f"archive member refused: {member.name}")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(into, filter="data")
        else:  # pragma: no cover - 3.11 without the filter
            tar.extractall(into)
    for candidate in sorted(into.rglob("caelza")):
        if candidate.is_file():
            return candidate.parent
    raise ValueError("archive has no caelza binary")


def install_version(home: Path | str, version: str, extracted: Path | str) -> Path:
    """Move an extracted release into `<home>/runtime/<version>`, replacing a
    half-installed one; the binary is made executable."""
    dest = version_dir(home, version)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(extracted), str(dest))
    binary = dest / "caelza"
    binary.chmod(binary.stat().st_mode | 0o755)
    return dest


# ---------------------------------------------------------------------------
# Probing a binary before it is trusted
# ---------------------------------------------------------------------------

def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, OSError, AttributeError):
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError, AttributeError):
            proc.kill()
        proc.wait(timeout=5)


def probe(binary: Path | str, *, config_dir: Path | str | None = None, port: int = PROBE_PORT,
          timeout: float = PROBE_TIMEOUT, expect_version: str | None = None,
          run=subprocess.run, popen=subprocess.Popen, fetch=http_get, sleep=time.sleep) -> tuple[bool, str]:
    """Does this binary hold? `caelza --version` must answer (and match
    `expect_version` when given), then `caelza gateway start -p <port>` must
    serve `/health` within `timeout`. The gateway is stopped afterwards."""
    version = version_of(binary, run=run)
    if version is None:
        return False, "caelza --version did not answer"
    if expect_version and version.split("+")[0] != expect_version.split("+")[0]:
        return False, f"binary says {version}, release says {expect_version}"
    argv = [str(binary), "gateway", "start", "-p", str(port)]
    if config_dir:
        argv += ["--config-dir", str(config_dir)]
    log = Path(str(binary)).parent / "probe.log"
    with open(log, "w") as fh:
        try:
            proc = popen(argv, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            return False, f"could not start the gateway: {e}"
        deadline = time.monotonic() + timeout
        healthy = False
        detail = "gateway never answered /health"
        try:
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    detail = f"gateway exited {proc.returncode} before answering /health"
                    break
                try:
                    fetch(f"http://127.0.0.1:{port}/health", {}, 5.0)
                    healthy = True
                    break
                except (urllib.error.URLError, OSError, ValueError):
                    sleep(0.5)
        finally:
            if proc.poll() is None:
                _kill_group(proc)
    if not healthy:
        tail = ""
        try:
            tail = "\n".join(log.read_text(errors="replace").splitlines()[-20:])
        except OSError:
            pass
        return False, f"{detail}\n{tail}".strip()
    return True, f"caelza {version} answered /health on port {port}"


# ---------------------------------------------------------------------------
# Swapping, keeping the last good one, rolling back
# ---------------------------------------------------------------------------

def _point(link: Path, version: str) -> None:
    """Repoint a symlink atomically (a temp link renamed over the old one)."""
    tmp = link.parent / f".{link.name}.tmp"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(version)
    os.replace(tmp, link)


def switch(home: Path | str, version: str) -> None:
    if not (version_dir(home, version) / "caelza").is_file():
        raise FileNotFoundError(f"no installed runtime {version!r} under {runtime_root(home)}")
    _point(runtime_root(home) / CURRENT, version)


def promote(home: Path | str, version: str) -> None:
    """Make `version` current and the last good one."""
    switch(home, version)
    _point(runtime_root(home) / LAST_GOOD, version)


def rollback(home: Path | str) -> str | None:
    """Point `current` back at `last-good`; the version, or None when there
    is no last-good to fall back to (or it is already current)."""
    good = last_good_version(home)
    if not good or good == current_version(home):
        return None
    switch(home, good)
    return good


def prune(home: Path | str, keep: int = 3) -> list[str]:
    """Drop installed versions beyond the newest `keep`, never current or last-good."""
    pinned = {current_version(home), last_good_version(home)}
    versions = installed_versions(home)
    removable = [v for v in versions if v not in pinned]
    removed: list[str] = []
    while len(versions) - len(removed) > keep and removable:
        v = removable.pop(0)
        shutil.rmtree(version_dir(home, v), ignore_errors=True)
        removed.append(v)
    return removed


# ---------------------------------------------------------------------------
# The config snapshot and the restart request
# ---------------------------------------------------------------------------

def snapshot_config(config_dir: Path | str, home: Path | str, keep: int = KEEP_CONFIG_SNAPSHOTS,
                    stamp: str | None = None) -> Path | None:
    """`~/.caelza`'s config, agents and shared files into one tar.gz under
    `<home>/snapshots`, pruned to `keep`. None when there is nothing to snapshot."""
    config_dir = Path(config_dir)
    present = [p for p in CONFIG_SNAPSHOT_PATHS if (config_dir / p).exists()]
    if not present:
        return None
    snaps = Path(home) / CONFIG_SNAPSHOTS
    snaps.mkdir(parents=True, exist_ok=True)
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    out = snaps / f"caelza-config-{stamp}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        for p in present:
            tar.add(config_dir / p, arcname=p)
    old = sorted(snaps.glob("caelza-config-*.tar.gz"))
    for stale in old[:-keep] if keep > 0 else []:
        stale.unlink(missing_ok=True)
    return out


def _run_dir(home: Path | str) -> Path:
    d = Path(home) / "run"
    d.mkdir(parents=True, exist_ok=True)
    return d


def request_restart(home: Path | str, reason: str, version: str | None) -> None:
    (_run_dir(home) / RESTART_REQUEST).write_text(json.dumps({"reason": reason, "version": version}))


def read_restart_request(home: Path | str) -> dict | None:
    f = Path(home) / "run" / RESTART_REQUEST
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) and "reason" in data else None


def clear_restart_request(home: Path | str) -> None:
    (Path(home) / "run" / RESTART_REQUEST).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------

def update(home: Path | str, *, repo: str = DEFAULT_REPO, target: str | None = None, tag: str | None = None,
           token: str | None = None, archive: Path | str | None = None, config_dir: Path | str | None = None,
           port: int = PROBE_PORT, timeout: float = PROBE_TIMEOUT, fetch=http_get, run=subprocess.run,
           popen=subprocess.Popen, log=print) -> dict:
    """Fetch, verify, unpack, probe, snapshot, promote. With `archive`, a local
    release tarball (no network, no checksum unless a `.sha256` sits beside
    it). The new version is promoted only after it answers `/health`; the one
    running stays current otherwise, and nothing else is touched."""
    home = Path(home)
    target = target or default_target()
    config_dir = Path(config_dir) if config_dir else Path.home() / ".caelza"
    work = home / "tmp" / f"runtime-update-{time.time_ns()}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        if archive:
            # A local archive is installed deliberately, current or not.
            archive = Path(archive)
            name = archive.name
            version = name[len("caelza-"):-len(f"-{target}.tar.gz")] if name.startswith("caelza-") and name.endswith(f"-{target}.tar.gz") else archive.stem.replace(".tar", "")
            sha = archive.with_name(name + ".sha256")
            sha_text = sha.read_text() if sha.is_file() else None
            log(f"installing from {archive}")
        else:
            rel = find_release(repo, target, tag, token, fetch=fetch)
            version = rel.version
            if version == current_version(home):
                log(f"{rel.tag} is already current")
                return {"version": version, "promoted": False, "detail": "already current"}
            log(f"found {rel.tag}: {rel.name}")
            archive = download(rel.asset_url, work / rel.name, token, fetch=fetch)
            sha_text = fetch(rel.sha_url, _headers(token, "application/octet-stream")).decode() if rel.sha_url else None
        if sha_text:
            verify_sha256(archive, sha_text)
            log("checksum ok")
        else:
            log("no checksum published; trusting the archive")
        extracted = unpack(archive, work / "x")
        installed = install_version(home, version, extracted)
        binary = installed / "caelza"
        ok, detail = probe(binary, config_dir=config_dir if config_dir.exists() else None, port=port,
                           timeout=timeout, expect_version=version, run=run, popen=popen, fetch=fetch)
        if not ok:
            shutil.rmtree(installed, ignore_errors=True)
            log(f"probe failed; {version} discarded, {current_version(home) or 'nothing'} stays current")
            return {"version": version, "promoted": False, "detail": detail}
        snap = snapshot_config(config_dir, home)
        previous = current_version(home)
        promote(home, version)
        request_restart(home, f"runtime {version} probed ok" + (f" (was {previous})" if previous else ""), version)
        prune(home)
        log(f"promoted {version}" + (f"; config snapshot {snap.name}" if snap else ""))
        return {"version": version, "promoted": True, "detail": detail, "previous": previous,
                "snapshot": str(snap) if snap else None}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def link_into_path(home: Path | str, bindir: Path | str | None = None) -> Path | None:
    """`$PREFIX/bin/caelza` (or `bindir/caelza`) → the current binary, so the
    shell and the boot script run what the supervisor guards."""
    binary = current_binary(home)
    if binary is None:
        return None
    if bindir is None:
        prefix = os.environ.get("PREFIX")
        if not prefix:
            return None
        bindir = Path(prefix) / "bin"
    link = Path(bindir) / "caelza"
    link.parent.mkdir(parents=True, exist_ok=True)
    tmp = link.with_name(".caelza.tmp")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(runtime_root(home) / CURRENT / "caelza")
    os.replace(tmp, link)
    return link
