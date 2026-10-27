"""M6: the Runtime binary under the supervisor's guard.

A fake release (JSON + a tarball holding a fake `caelza` that answers
`--version` and serves `/health`) drives the whole pipeline: find, download,
verify, unpack, probe, snapshot the config, promote, request a restart; the
failure paths (bad checksum, unsafe archive, a binary that lies about its
version, a gateway that exits or never answers) leave the current one
alone. The supervisor's Runtime tick is driven with fake children: start,
restart on request, crash loop → roll back to last-good, halt when last-good
loops. With `CAELZA_BIN` set, the probe also runs against the real binary.
"""
from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import re
import shutil
import signal
import socket
import stat
import tarfile
import time
from pathlib import Path

import pytest

from caelza_body import mcp_server as srv
from caelza_body import runtime_guard as rg
from caelza_body import supervisor
from caelza_body.agent import tools

TARGET = "x86_64-unknown-linux-gnu"

FAKE_CAELZA = '''#!/usr/bin/env python3
import http.server, os, socketserver, sys, time
mode = os.environ.get("FAKE_CAELZA_MODE", "ok")
if sys.argv[1:2] == ["--version"]:
    print("caelza 1.0.0 (v1.0.0+fake)" if mode == "bad-version" else "caelza %s (v%s+fake)" % (VERSION, VERSION))
    sys.exit(0)
if sys.argv[1:3] == ["gateway", "start"]:
    if mode == "crash":
        print("boom"); sys.exit(3)
    if mode == "hang":
        time.sleep(3600)
    port = int(sys.argv[sys.argv.index("-p") + 1])
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == "/health" else 404); self.end_headers(); self.wfile.write(b"ok")
        def log_message(self, *a): pass
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), H) as s:
        s.serve_forever()
if sys.argv[1:2] == ["daemon"]:
    time.sleep(3600)
'''


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_archive(tmp_path: Path, version: str, *, broken=False) -> tuple[Path, str]:
    """A release tarball the way release.yml packs one, and its sha256 line."""
    name = f"caelza-{version}-{TARGET}"
    stage = tmp_path / "stage" / name
    (stage / "web" / "dist").mkdir(parents=True)
    (stage / "caelza").write_text(FAKE_CAELZA.replace("VERSION", repr(version)))
    (stage / "caelza").chmod(0o755)
    (stage / "web" / "dist" / "index.html").write_text("<html>caelza</html>")
    (stage / "NOTICE").write_text("notices\n")
    archive = tmp_path / f"{name}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(stage, arcname=name)
        if broken:
            info = tarfile.TarInfo(name=f"{name}/../../escape")
            data = b"x"
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    sha = f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n"
    return archive, sha


def release_json(version: str, with_sha=True) -> dict:
    name = f"caelza-{version}-{TARGET}.tar.gz"
    assets = [{"name": name, "url": f"api://asset/{name}"}]
    if with_sha:
        assets.append({"name": name + ".sha256", "url": f"api://asset/{name}.sha256"})
    assets.append({"name": f"caelza-{version}-aarch64-linux-android.tar.gz", "url": "api://asset/android"})
    return {"tag_name": f"v{version}", "assets": assets}


class Fetch:
    """A canned GitHub: the release JSON and its assets by URL; anything on
    127.0.0.1 goes to the real HTTP client (the probe's /health)."""

    def __init__(self, version: str, archive: Path, sha: str, with_sha=True, tag_only=False):
        name = archive.name
        self.calls: list[tuple[str, dict]] = []
        self.urls = {
            f"https://api.github.com/repos/{rg.DEFAULT_REPO}/releases/latest": json.dumps(release_json(version, with_sha)).encode(),
            f"https://api.github.com/repos/{rg.DEFAULT_REPO}/releases/tags/v{version}": json.dumps(release_json(version, with_sha)).encode(),
            f"api://asset/{name}": archive.read_bytes(),
            f"api://asset/{name}.sha256": sha.encode(),
        }
        if tag_only:
            del self.urls[f"https://api.github.com/repos/{rg.DEFAULT_REPO}/releases/latest"]

    def __call__(self, url, headers=None, timeout=120.0):
        if url.startswith("http://127.0.0.1"):
            return rg.http_get(url, headers, timeout)
        self.calls.append((url, dict(headers or {})))
        if url not in self.urls:
            raise rg.urllib.error.HTTPError(url, 404, "not found", {}, None)
        return self.urls[url]


# --- where things are ---------------------------------------------------------

def test_default_target_follows_the_machine(monkeypatch):
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    monkeypatch.setattr(rg.platform, "machine", lambda: "aarch64")
    assert rg.default_target() == "aarch64-linux-android"
    monkeypatch.setattr(rg.platform, "machine", lambda: "x86_64")
    assert rg.default_target() == "x86_64-linux-android", "an emulator asks for what the release does not build, and is told so"
    monkeypatch.delenv("PREFIX")
    monkeypatch.setattr(rg.platform, "machine", lambda: "aarch64")
    assert rg.default_target() == "aarch64-unknown-linux-gnu"
    monkeypatch.setattr(rg.platform, "machine", lambda: "x86_64")
    assert rg.default_target() == "x86_64-unknown-linux-gnu"
    assert sorted(["0.10.0", "0.9.0", "0.1.0", "1.0.0-rc1"], key=rg.version_key) == ["0.1.0", "0.9.0", "0.10.0", "1.0.0-rc1"]


def test_release_parsing_picks_the_target_s_archive_and_checksum():
    rel = rg.parse_release(release_json("0.1.0"), TARGET)
    assert (rel.tag, rel.version, rel.name) == ("v0.1.0", "0.1.0", f"caelza-0.1.0-{TARGET}.tar.gz")
    assert rel.asset_url.endswith(TARGET + ".tar.gz") and rel.sha_url.endswith(".sha256")
    assert rg.parse_release(release_json("0.1.0", with_sha=False), TARGET).sha_url is None
    with pytest.raises(LookupError, match="no -riscv64-unknown-linux-gnu.tar.gz asset"):
        rg.parse_release(release_json("0.1.0"), "riscv64-unknown-linux-gnu")


def test_find_release_asks_github_with_the_token_and_the_right_accept(tmp_path):
    archive, sha = make_archive(tmp_path, "0.1.0")
    fetch = Fetch("0.1.0", archive, sha)
    rel = rg.find_release(target=TARGET, token="ghp_x", fetch=fetch)
    assert rel.version == "0.1.0"
    url, headers = fetch.calls[-1]
    assert url.endswith("/releases/latest") and headers["Authorization"] == "token ghp_x"
    assert headers["Accept"] == "application/vnd.github+json"
    rel = rg.find_release(target=TARGET, tag="v0.1.0", fetch=fetch)
    assert fetch.calls[-1][0].endswith("/releases/tags/v0.1.0") and rel.tag == "v0.1.0"
    with pytest.raises(rg.urllib.error.HTTPError):
        rg.find_release(target=TARGET, tag="v9.9.9", fetch=fetch)


def test_download_and_checksum(tmp_path):
    archive, sha = make_archive(tmp_path, "0.1.0")
    fetch = Fetch("0.1.0", archive, sha)
    got = rg.download(f"api://asset/{archive.name}", tmp_path / "dl" / archive.name, token="t", fetch=fetch)
    assert got.read_bytes() == archive.read_bytes()
    assert fetch.calls[-1][1]["Accept"] == "application/octet-stream"
    assert rg.verify_sha256(got, sha) == hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="checksum mismatch"):
        rg.verify_sha256(got, "0" * 64 + "  x.tar.gz\n")
    with pytest.raises(ValueError, match="not a sha256"):
        rg.verify_sha256(got, "not a checksum")


def test_unpack_finds_the_binary_and_refuses_an_escaping_member(tmp_path):
    archive, _ = make_archive(tmp_path, "0.1.0")
    top = rg.unpack(archive, tmp_path / "x")
    assert (top / "caelza").is_file() and (top / "web" / "dist" / "index.html").is_file()
    bad, _ = make_archive(tmp_path / "bad", "0.1.0", broken=True)
    with pytest.raises(ValueError, match="archive member refused"):
        rg.unpack(bad, tmp_path / "y")
    empty = tmp_path / "empty.tar.gz"
    with tarfile.open(empty, "w:gz") as tar:
        tar.add(tmp_path / "x" / f"caelza-0.1.0-{TARGET}" / "NOTICE", arcname="only/NOTICE")
    with pytest.raises(ValueError, match="no caelza binary"):
        rg.unpack(empty, tmp_path / "z")


def test_install_switch_promote_rollback_and_prune(tmp_path):
    home = tmp_path / "home"
    for v in ("0.1.0", "0.1.1", "0.1.2"):
        archive, _ = make_archive(tmp_path / v, v)
        installed = rg.install_version(home, v, rg.unpack(archive, tmp_path / v / "x"))
        assert installed == rg.version_dir(home, v) and os.access(installed / "caelza", os.X_OK)
    assert rg.installed_versions(home) == ["0.1.0", "0.1.1", "0.1.2"]
    assert rg.current_version(home) is None and rg.current_binary(home) is None
    rg.promote(home, "0.1.0")
    assert rg.current_version(home) == rg.last_good_version(home) == "0.1.0"
    assert rg.current_binary(home) == rg.version_dir(home, "0.1.0") / "caelza"
    rg.switch(home, "0.1.1")
    assert rg.current_version(home) == "0.1.1" and rg.last_good_version(home) == "0.1.0"
    assert rg.rollback(home) == "0.1.0" and rg.current_version(home) == "0.1.0"
    assert rg.rollback(home) is None, "already on last-good"
    with pytest.raises(FileNotFoundError):
        rg.switch(home, "9.9.9")
    rg.promote(home, "0.1.2")
    rg.switch(home, "0.1.1")  # current 0.1.1, last-good 0.1.2, 0.1.0 unpinned
    assert rg.prune(home, keep=2) == ["0.1.0"]
    assert rg.installed_versions(home) == ["0.1.1", "0.1.2"]
    assert rg.version_of(rg.current_binary(home)) == "0.1.1"
    assert rg.version_of(tmp_path / "missing") is None
    s = rg.status(home)
    assert s["current"] == "0.1.1" and s["last_good"] == "0.1.2" and s["binary"].endswith("0.1.1/caelza")
    # A last-good whose binary is gone is nothing to fall back to, not an exception.
    shutil.rmtree(rg.version_dir(home, "0.1.2"))
    assert rg.last_good_version(home) == "0.1.2" and rg.rollback(home) is None


def test_prune_orders_versions_numerically_and_pins_the_one_still_running(tmp_path):
    home = tmp_path / "home"
    for v in ("0.8.0", "0.9.0", "0.10.0", "0.11.0"):
        d = rg.version_dir(home, v)
        d.mkdir(parents=True)
        (d / "caelza").write_text("#!/bin/sh\n")
    assert rg.installed_versions(home) == ["0.8.0", "0.9.0", "0.10.0", "0.11.0"]
    rg.promote(home, "0.9.0")   # last-good
    rg.switch(home, "0.11.0")   # current; 0.10.0 still runs until the supervisor restarts
    assert rg.prune(home, keep=2, pin=("0.10.0",)) == ["0.8.0"]
    assert rg.installed_versions(home) == ["0.9.0", "0.10.0", "0.11.0"]


def test_install_version_swaps_a_previous_copy_whole(tmp_path):
    home = tmp_path / "home"
    a, _ = make_archive(tmp_path / "a", "0.1.0")
    rg.install_version(home, "0.1.0", rg.unpack(a, tmp_path / "a" / "x"))
    rg.promote(home, "0.1.0")
    (rg.version_dir(home, "0.1.0") / "stale").write_text("old")
    b, _ = make_archive(tmp_path / "b", "0.1.0")
    rg.install_version(home, "0.1.0", rg.unpack(b, tmp_path / "b" / "x"))
    assert rg.current_binary(home) is not None and not (rg.version_dir(home, "0.1.0") / "stale").exists()
    assert not (rg.runtime_root(home) / "0.1.0.old").exists()


def test_probe_accepts_a_binary_that_answers_and_refuses_the_others(tmp_path, monkeypatch):
    archive, _ = make_archive(tmp_path, "0.1.0")
    binary = rg.unpack(archive, tmp_path / "x") / "caelza"
    ok, detail = rg.probe(binary, port=free_port(), timeout=20, expect_version="0.1.0")
    assert ok, detail
    assert "answered /health" in detail
    ok, detail = rg.probe(binary, port=free_port(), timeout=20, expect_version="0.2.0")
    assert not ok and "binary says 0.1.0, release says 0.2.0" == detail
    monkeypatch.setenv("FAKE_CAELZA_MODE", "crash")
    ok, detail = rg.probe(binary, port=free_port(), timeout=20)
    assert not ok and "exited 3 before answering /health" in detail and "boom" in detail
    monkeypatch.setenv("FAKE_CAELZA_MODE", "hang")
    ok, detail = rg.probe(binary, port=free_port(), timeout=2)
    assert not ok and detail.startswith("gateway never answered /health")
    assert rg.probe(tmp_path / "nope", port=free_port(), timeout=1) == (False, "caelza --version did not answer")


def test_probe_refuses_a_busy_port_and_a_gateway_that_dies_right_after_answering(tmp_path):
    archive, _ = make_archive(tmp_path, "0.1.0")
    binary = rg.unpack(archive, tmp_path / "x") / "caelza"
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        port = taken.getsockname()[1]
        ok, detail = rg.probe(binary, port=port, timeout=5)
    assert not ok and detail.startswith(f"probe port {port} is in use"), "a stale listener must not vouch for the new binary"

    class Dying:  # answers /health once, then is gone
        pid = 0
        returncode = 0

        def __init__(self):
            self.polls = 0

        def poll(self):
            self.polls += 1
            return None if self.polls == 1 else 0

    ok, detail = rg.probe(binary, port=free_port(), timeout=5, popen=lambda *a, **k: Dying(),
                          fetch=lambda url, headers=None, timeout=0: b"ok")
    assert not ok and "right after answering /health" in detail


def test_the_token_does_not_follow_a_redirect_to_another_host():
    handler = rg._RedirectWithoutToken()
    req = rg.urllib.request.Request("https://api.github.com/repos/x/y/releases/assets/1",
                                    headers={"Authorization": "token t", "Accept": "application/octet-stream"})
    hdrs = http.client.HTTPMessage()
    new = handler.redirect_request(req, io.BytesIO(b""), 302, "Found", hdrs, "https://objects.githubusercontent.com/a?sig=1")
    assert new.full_url.startswith("https://objects.githubusercontent.com/")
    assert not new.has_header("Authorization") and new.get_header("Accept") == "application/octet-stream"
    same = handler.redirect_request(req, io.BytesIO(b""), 302, "Found", hdrs, "https://api.github.com/elsewhere")
    assert same.get_header("Authorization") == "token t"


@pytest.mark.skipif(not os.environ.get("CAELZA_BIN"), reason="set CAELZA_BIN to probe the real binary")
def test_probe_the_real_binary(tmp_path):
    config_dir = tmp_path / "install"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('schema_version = 3\n\n[gateway]\nrequire_pairing = false\n')
    ok, detail = rg.probe(Path(os.environ["CAELZA_BIN"]), config_dir=config_dir, port=free_port(), timeout=60)
    assert ok, detail


def test_config_snapshot_takes_the_config_and_what_the_agent_may_change(tmp_path):
    cfg = tmp_path / ".caelza"
    (cfg / "agents" / "main" / "workspace").mkdir(parents=True)
    (cfg / "shared" / "sops" / "phone-debloat").mkdir(parents=True)
    (cfg / "data").mkdir()
    (cfg / "config.toml").write_text("schema_version = 3\n")
    (cfg / "agents" / "main" / "workspace" / "SOUL.md").write_text("Cael\n")
    (cfg / "shared" / "sops" / "phone-debloat" / "SOP.toml").write_text("[sop]\n")
    (cfg / "data" / "big.db").write_bytes(b"\0" * 1000)
    home = tmp_path / "home"
    out = rg.snapshot_config(cfg, home, keep=2, stamp="20261026-120000")
    with tarfile.open(out) as tar:
        names = sorted(tar.getnames())
    assert "config.toml" in names and "agents/main/workspace/SOUL.md" in names
    assert "shared/sops/phone-debloat/SOP.toml" in names and not any(n.startswith("data") for n in names)
    rg.snapshot_config(cfg, home, keep=2, stamp="20261026-120001")
    rg.snapshot_config(cfg, home, keep=2, stamp="20261026-120002")
    assert sorted(p.name for p in (home / "snapshots").iterdir()) == [
        "caelza-config-20261026-120001.tar.gz", "caelza-config-20261026-120002.tar.gz"]
    assert rg.snapshot_config(tmp_path / "nothing", home) is None


def test_restart_request_round_trip(tmp_path):
    home = tmp_path / "home"
    assert rg.read_restart_request(home) is None
    rg.request_restart(home, "probed ok", "0.1.1")
    assert rg.read_restart_request(home) == {"reason": "probed ok", "version": "0.1.1"}
    rg.clear_restart_request(home)
    assert rg.read_restart_request(home) is None
    (home / "run" / rg.RESTART_REQUEST).write_text("{not json")
    assert rg.read_restart_request(home) is None


# --- the pipeline -----------------------------------------------------------------

def test_update_promotes_a_release_that_probes_ok_and_leaves_the_rest_alone(tmp_path):
    home = tmp_path / "home"
    cfg = tmp_path / ".caelza"
    cfg.mkdir()
    (cfg / "config.toml").write_text("schema_version = 3\n")
    archive, sha = make_archive(tmp_path, "0.1.0")
    fetch = Fetch("0.1.0", archive, sha)
    lines: list[str] = []
    result = rg.update(home, target=TARGET, token="t", config_dir=cfg, port=free_port(), timeout=20, fetch=fetch, log=lines.append)
    assert result["promoted"] is True and result["version"] == "0.1.0" and result["previous"] is None
    assert rg.current_version(home) == rg.last_good_version(home) == "0.1.0"
    assert rg.read_restart_request(home)["version"] == "0.1.0"
    assert Path(result["snapshot"]).is_file() and "checksum ok" in lines
    assert not list((home / "tmp").iterdir()), "the work dir is cleaned up"
    # Asking again for the same version is a no-op.
    assert rg.update(home, target=TARGET, config_dir=cfg, port=free_port(), fetch=fetch)["detail"] == "already current"

    # A newer release whose gateway crashes is discarded; 0.1.0 stays current.
    rg.clear_restart_request(home)
    bad_archive, bad_sha = make_archive(tmp_path / "bad", "0.2.0")
    bad = Fetch("0.2.0", bad_archive, bad_sha)
    os.environ["FAKE_CAELZA_MODE"] = "crash"
    try:
        result = rg.update(home, target=TARGET, config_dir=cfg, port=free_port(), timeout=20, fetch=bad, log=lines.append)
    finally:
        del os.environ["FAKE_CAELZA_MODE"]
    assert result["promoted"] is False and "exited 3" in result["detail"]
    assert rg.current_version(home) == "0.1.0" and rg.installed_versions(home) == ["0.1.0"]
    assert rg.read_restart_request(home) is None

    # A tampered archive never reaches the probe.
    tampered = Fetch("0.2.0", bad_archive, "0" * 64 + "  x\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        rg.update(home, target=TARGET, config_dir=cfg, port=free_port(), fetch=tampered)
    assert rg.installed_versions(home) == ["0.1.0"]


def test_update_probes_on_a_copy_of_the_config_and_keeps_last_good_on_what_was_running(tmp_path, monkeypatch):
    home = tmp_path / "home"
    cfg = tmp_path / ".caelza"
    (cfg / "shared" / "sops" / "phone-debloat").mkdir(parents=True)
    (cfg / "agents" / "main" / "workspace").mkdir(parents=True)
    (cfg / "data").mkdir()
    (cfg / "config.toml").write_text("schema_version = 3\n")
    (cfg / ".secret_key").write_bytes(b"k" * 32)
    (cfg / "shared" / "sops" / "phone-debloat" / "SOP.toml").write_text("[sop]\n")
    (cfg / "agents" / "main" / "SOUL.md").write_text("Cael\n")
    (cfg / "agents" / "main" / "workspace" / "big.bin").write_bytes(b"\0" * 10)
    (cfg / "data" / "config-lifecycle.lock").write_text("")  # the running Runtime's
    seen: list[dict] = []
    real_probe = rg.probe

    def spy(binary, **kw):
        copy = kw["config_dir"]
        seen.append({"binary": Path(binary), "config_dir": copy,
                     "files": sorted(str(p.relative_to(copy)) for p in copy.rglob("*"))})
        return real_probe(binary, **kw)

    monkeypatch.setattr(rg, "probe", spy)
    first, sha1 = make_archive(tmp_path / "a", "0.1.0")
    first.with_name(first.name + ".sha256").write_text(sha1)
    out = rg.update(home, target=TARGET, archive=first, config_dir=cfg, port=free_port(), timeout=20)
    assert out["promoted"] and out["last_good"] == "0.1.0" == rg.current_version(home), "the first install is the only good one"
    probe = seen[-1]
    assert str(probe["binary"]).startswith(str(home / "tmp")), "probed in the work dir, before anything is installed"
    assert str(probe["config_dir"]).startswith(str(home / "tmp")) and probe["config_dir"] != cfg
    assert probe["files"] == [".secret_key", "agents", "agents/main", "agents/main/SOUL.md", "config.toml",
                              "shared", "shared/sops", "shared/sops/phone-debloat", "shared/sops/phone-debloat/SOP.toml"]
    assert not list((home / "tmp").iterdir())

    second, sha2 = make_archive(tmp_path / "b", "0.2.0")
    second.with_name(second.name + ".sha256").write_text(sha2)
    out = rg.update(home, target=TARGET, archive=second, config_dir=cfg, port=free_port(), timeout=20)
    assert out["promoted"] and out["previous"] == "0.1.0" and out["last_good"] == "0.1.0"
    assert rg.current_version(home) == "0.2.0" and rg.last_good_version(home) == "0.1.0", "the supervisor promotes once it holds"
    assert rg.read_restart_request(home)["version"] == "0.2.0"

    # The current version is never reinstalled over itself (that would pull the running binary away).
    out = rg.update(home, target=TARGET, archive=second, config_dir=cfg, port=free_port(), timeout=20)
    assert out["detail"] == "already current" and rg.current_binary(home).is_file()
    assert rg.installed_versions(home) == ["0.1.0", "0.2.0"]

    # A dangling current (its directory removed by hand) does not block the next update.
    shutil.rmtree(rg.version_dir(home, "0.2.0"))
    fetch = Fetch("0.2.0", second, sha2)
    out = rg.update(home, target=TARGET, config_dir=cfg, port=free_port(), timeout=20, fetch=fetch)
    assert out["promoted"] and rg.current_binary(home).is_file()
    assert rg.last_good_version(home) == "0.1.0"

    # A bare version as --tag means the v-tag.
    tagged = Fetch("0.3.0", *make_archive(tmp_path / "c", "0.3.0"), tag_only=True)
    with pytest.raises(rg.urllib.error.HTTPError):
        rg.update(home, target=TARGET, tag="9.9.9", config_dir=cfg, fetch=tagged)
    assert tagged.calls[-1][0].endswith("/releases/tags/v9.9.9")


def test_update_from_a_local_archive_needs_no_network(tmp_path):
    home = tmp_path / "home"
    archive, sha = make_archive(tmp_path, "0.3.0")
    archive.with_name(archive.name + ".sha256").write_text(sha)

    def no_network(url, headers=None, timeout=120.0):
        if url.startswith("http://127.0.0.1"):
            return rg.http_get(url, headers, timeout)
        raise AssertionError(f"network call: {url}")

    result = rg.update(home, target=TARGET, archive=archive, config_dir=tmp_path / "no-config", port=free_port(), timeout=20, fetch=no_network)
    assert result["promoted"] is True and result["snapshot"] is None
    assert rg.current_version(home) == "0.3.0"
    link = rg.link_into_path(home, tmp_path / "bin")
    assert link == tmp_path / "bin" / "caelza" and os.readlink(link).endswith("runtime/current/caelza")
    assert rg.version_of(link) == "0.3.0"


# --- the supervisor's Runtime tick -----------------------------------------------

class FakeChild:
    def __init__(self, exits_with=None):
        self.exits_with = exits_with
        self.started = False
        self.stopped = False
        self.name = "runtime"
        self.log_dir = Path(".")

    def start(self):
        self.started = True

    @property
    def running(self):
        return self.started and not self.stopped and self.exits_with is None

    @property
    def returncode(self):
        return self.exits_with

    def stop(self, timeout=5.0):
        self.stopped = True


def guarded_home(tmp_path):
    home = tmp_path / "home"
    (home / "run").mkdir(parents=True)
    for v in ("0.1.0", "0.1.1"):
        d = rg.version_dir(home, v)
        d.mkdir(parents=True)
        (d / "caelza").write_text("#!/bin/sh\n")
    rg.promote(home, "0.1.0")
    rg.switch(home, "0.1.1")
    return home


def make_supervisor(home, git_repo, spawn_runtime, clock):
    alerts: list[str] = []
    sup = supervisor.Supervisor(
        git_repo, home, alert=alerts.append,
        spawn_agent=lambda: FakeChild(), spawn_probe=lambda: FakeChild(), spawn_sidecar=lambda: None,
        spawn_runtime=spawn_runtime, clock=clock, sleep=lambda s: None)
    return sup, alerts


def test_supervisor_starts_the_runtime_and_restarts_it_on_request(tmp_path, git_repo):
    home = guarded_home(tmp_path)
    spawned: list[FakeChild] = []

    def spawn():
        spawned.append(FakeChild())
        return spawned[-1]

    sup, alerts = make_supervisor(home, git_repo, spawn, lambda: 0.0)
    sup.tick()
    assert sup.runtime is spawned[0] and sup.runtime.running
    sup.tick()
    assert len(spawned) == 1, "a running runtime is left alone"
    rg.request_restart(home, "runtime 0.1.1 probed ok", "0.1.1")
    sup.tick()
    assert spawned[0].stopped and sup.runtime is spawned[1] and sup.runtime.running
    assert rg.read_restart_request(home) is None
    assert alerts == ["runtime: restarting on 0.1.1: runtime 0.1.1 probed ok"]


def test_supervisor_rolls_the_runtime_back_on_a_crash_loop_then_halts(tmp_path, git_repo):
    home = guarded_home(tmp_path)
    t = {"now": 0.0}
    spawn = lambda: FakeChild(exits_with=1)  # noqa: E731
    sup, alerts = make_supervisor(home, git_repo, spawn, lambda: t["now"])
    for _ in range(4):
        sup.tick()
        t["now"] += 1.0
    assert rg.current_version(home) == "0.1.0", "rolled back to last-good"
    assert any("rolled back to last-good 0.1.0" in a for a in alerts)
    assert not sup._runtime_halted
    for _ in range(4):
        sup.tick()
        t["now"] += 1.0
    assert sup._runtime_halted and any("manual fix needed" in a for a in alerts)
    before = len(alerts)
    sup.tick()
    assert len(alerts) == before, "halted: no more restarts, no more alerts"
    # The agent side is untouched by all this.
    assert sup.agent.running and not sup._halted


def test_a_restart_request_revives_a_halted_runtime(tmp_path, git_repo):
    home = guarded_home(tmp_path)
    t = {"now": 0.0}
    mode = {"exits": 1}
    spawned: list[FakeChild] = []

    def spawn():
        spawned.append(FakeChild(exits_with=mode["exits"]))
        return spawned[-1]

    sup, alerts = make_supervisor(home, git_repo, spawn, lambda: t["now"])
    for _ in range(8):
        sup.tick()
        t["now"] += 1.0
    assert sup._runtime_halted
    # The operator installs a fixed release: `runtime update` asks for a restart.
    mode["exits"] = None
    rg.request_restart(home, "runtime 0.1.2 probed ok", "0.1.2")
    before = len(spawned)
    sup.tick()
    assert len(spawned) == before + 1 and sup.runtime.running and not sup._runtime_halted
    assert rg.read_restart_request(home) is None and alerts[-1].startswith("runtime: restarting on 0.1.2")


def test_a_dangling_last_good_is_no_rollback_and_the_tick_survives(tmp_path, git_repo):
    home = guarded_home(tmp_path)
    shutil.rmtree(rg.version_dir(home, "0.1.0"))  # last-good's binary is gone
    t = {"now": 0.0}
    sup, alerts = make_supervisor(home, git_repo, lambda: FakeChild(exits_with=1), lambda: t["now"])
    for _ in range(8):
        sup.tick()
        t["now"] += 1.0
    assert rg.current_version(home) == "0.1.1", "nothing to roll back to"
    assert any("no other last-good binary" in a for a in alerts) and sup._runtime_halted
    assert sup.agent.running and not sup._halted


def test_a_guard_error_is_alerted_once_and_the_agent_s_ladder_goes_on(tmp_path, git_repo, monkeypatch):
    home = guarded_home(tmp_path)
    sup, alerts = make_supervisor(home, git_repo, lambda: FakeChild(), lambda: 0.0)

    def boom(_home):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(rg, "read_restart_request", boom)
    sup.tick()
    sup.tick()
    assert [a for a in alerts if "disk on fire" in a] == [alerts[0]] and "leaving the Runtime alone" in alerts[0]
    assert sup.agent is not None and sup.agent.running
    monkeypatch.undo()
    sup.tick()
    assert sup.runtime is not None and sup.runtime.running and sup._runtime_error is None


def test_another_runtime_on_the_gateway_port_halts_without_a_rollback(tmp_path, git_repo, monkeypatch):
    home = guarded_home(tmp_path)
    monkeypatch.setattr(rg, "gateway_answering", lambda config_dir=None, fetch=None: 42617)
    t = {"now": 0.0}
    sup, alerts = make_supervisor(home, git_repo, lambda: FakeChild(exits_with=1), lambda: t["now"])
    for _ in range(4):
        sup.tick()
        t["now"] += 1.0
    assert sup._runtime_halted and rg.current_version(home) == "0.1.1", "not the binary's fault: no rollback"
    assert any("another Runtime already serves the gateway on port 42617" in a for a in alerts)


def test_gateway_port_comes_from_the_config_and_answering_means_someone_serves_it(tmp_path):
    cfg = tmp_path / ".caelza"
    cfg.mkdir()
    assert rg.gateway_port(cfg) == rg.GATEWAY_PORT
    (cfg / "config.toml").write_text('schema_version = 3\n\n[gateway]\nport = 4242\n')
    assert rg.gateway_port(cfg) == 4242
    (cfg / "config.toml").write_text("not = toml =")
    assert rg.gateway_port(cfg) == rg.GATEWAY_PORT
    (cfg / "config.toml").write_text('[gateway]\nport = 4242\n')

    def refused(url, headers=None, timeout=0):
        raise OSError("connection refused")

    assert rg.gateway_answering(cfg, fetch=refused) is None
    assert rg.gateway_answering(cfg, fetch=lambda url, headers=None, timeout=0: b"ok") == 4242


def test_a_new_version_becomes_last_good_once_it_has_held(tmp_path, git_repo):
    home = guarded_home(tmp_path)  # current 0.1.1, last-good 0.1.0
    t = {"now": 0.0}
    sup, alerts = make_supervisor(home, git_repo, lambda: FakeChild(), lambda: t["now"])
    sup.tick()
    t["now"] += supervisor.RUNTIME_STABLE_AFTER - 1
    sup.tick()
    assert rg.last_good_version(home) == "0.1.0"
    t["now"] += 2
    sup.tick()
    assert rg.last_good_version(home) == "0.1.1" and any("last-good binary now" in a for a in alerts)


def test_run_stops_every_child_on_interrupt_and_on_an_error(tmp_path, git_repo):
    home = guarded_home(tmp_path)
    for stop_with in (KeyboardInterrupt, RuntimeError):
        children: list[FakeChild] = []

        def spawn():
            children.append(FakeChild())
            return children[-1]

        sup, _ = make_supervisor(home, git_repo, spawn, lambda: 0.0)
        sup._spawn_agent = spawn
        calls = {"n": 0}

        def sleep(_s):
            calls["n"] += 1
            if calls["n"] == 2:
                raise stop_with("stop")

        sup._sleep = sleep
        if stop_with is RuntimeError:
            with pytest.raises(RuntimeError):
                sup.run()
        else:
            sup.run()
        assert len(children) >= 2 and all(c.stopped for c in children), stop_with
    with pytest.raises(KeyboardInterrupt):
        supervisor._raise_keyboard_interrupt(signal.SIGTERM, None)


def test_the_boot_script_steps_aside_once_the_guard_holds_a_runtime(tmp_path):
    boot = tmp_path / "boot" / "caelza-runtime"
    boot.parent.mkdir()
    assert rg.defer_boot_script(boot) is None
    boot.write_text("#!/bin/sh\n# Termux:Boot\ntermux-wake-lock\nexec caelza daemon >> log 2>&1\n")
    assert rg.defer_boot_script(boot) == "patched"
    lines = boot.read_text().splitlines()
    assert lines.index(rg.BOOT_GUARD.strip()) == lines.index("exec caelza daemon >> log 2>&1") - 1
    assert rg.defer_boot_script(boot) == "already"
    other = tmp_path / "boot" / "other"
    other.write_text("#!/bin/sh\nexec something-else\n")
    assert rg.defer_boot_script(other) is None and "runtime/current" not in other.read_text()
    installer = (Path(__file__).resolve().parents[1] / "runtime" / "termux-install.sh").read_text()
    assert '[ -e "$HOME/.caelza-body/runtime/current" ] && exit 0' in installer, "a fresh install ships the guard line"


def test_supervisor_without_a_runtime_installed_does_nothing_for_it(tmp_path, git_repo):
    home = tmp_path / "home"
    (home / "run").mkdir(parents=True)
    sup, alerts = make_supervisor(home, git_repo, lambda: None, lambda: 0.0)
    sup.tick()
    assert sup.runtime is None and alerts == []
    plain, _ = make_supervisor(home, git_repo, None, lambda: 0.0)
    plain.tick()
    assert plain.runtime is None


# --- the CLI and the deny list ----------------------------------------------------

def test_runtime_cli_status_update_rollback_and_link(tmp_path, capsys):
    home = tmp_path / "home"
    common = ["--home", str(home), "--repo-root", str(tmp_path), "--tools", "shell"]
    assert srv.main(["runtime", *common]) == 0
    tools.reset()
    assert json.loads(capsys.readouterr().out)["current"] is None

    archive, sha = make_archive(tmp_path, "0.4.0")
    archive.with_name(archive.name + ".sha256").write_text(sha)
    port = str(free_port())
    assert srv.main(["runtime", "update", "--archive", str(archive), "--target", TARGET, "--probe-port", port,
                     "--probe-timeout", "20", "--config-dir", str(tmp_path / "none"), *common]) == 0
    tools.reset()
    out = json.loads(capsys.readouterr().out)
    assert out["promoted"] is True and rg.current_version(home) == "0.4.0"

    assert srv.main(["runtime", "rollback", *common]) == 1
    tools.reset()
    assert "nothing to roll back" in capsys.readouterr().err
    second, sha2 = make_archive(tmp_path / "second", "0.5.0")
    second.with_name(second.name + ".sha256").write_text(sha2)
    assert srv.main(["runtime", "update", "--archive", str(second), "--target", TARGET, "--probe-port", str(free_port()),
                     "--probe-timeout", "20", "--config-dir", str(tmp_path / "none"), *common]) == 0
    tools.reset()
    capsys.readouterr()
    rg.switch(home, "0.5.0")
    rg._point(rg.runtime_root(home) / rg.LAST_GOOD, "0.4.0")
    assert srv.main(["runtime", "rollback", *common]) == 0
    tools.reset()
    assert "current -> 0.4.0" in capsys.readouterr().out and rg.read_restart_request(home)["version"] == "0.4.0"
    assert srv.main(["runtime", "link", "--bindir", str(tmp_path / "bin"), *common]) == 0
    tools.reset()
    assert (tmp_path / "bin" / "caelza").is_symlink()
    assert srv.main(["runtime", "update", "--tag", "v9", "--archive", str(second), *common]) == 2
    tools.reset()
    assert "do not go together" in capsys.readouterr().err


def test_the_guard_is_as_immutable_as_the_supervisor(tmp_path):
    from caelza_body.agent.tools import selfmod
    repo = tmp_path / "repo"
    (repo / "caelza_body" / "agent").mkdir(parents=True)
    (repo / "tests").mkdir()
    selfmod.configure(repo, tmp_path / "home")
    for path in ("caelza_body/supervisor.py", "caelza_body/runtime_guard.py", "caelza_body/./runtime_guard.py",
                 "caelza_body/RUNTIME_GUARD.py", "caelza_body/runtime_guard/__init__.py",
                 "caelza_body/supervisor/helpers.py", "caelza_body/__init__.py"):
        with pytest.raises(PermissionError, match="immutable"):
            selfmod._resolve(path)
    # The tests of those files and the agent's own code are the agent's to edit.
    assert selfmod._resolve("tests/test_runtime_guard.py") == repo / "tests" / "test_runtime_guard.py"
    assert selfmod._resolve("caelza_body/agent/supervisor_notes.py").name == "supervisor_notes.py"
    assert re.fullmatch(r"[\w., ()]+", "".join(selfmod.DENY_NAMES))
