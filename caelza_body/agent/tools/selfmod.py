from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from caelza_body.agent import tools

_REPO: Path | None = None
_HOME: Path | None = None
DENY_SUFFIXES = ("supervisor.py",)


def configure(repo_root, body_home):
    global _REPO, _HOME
    _REPO = Path(repo_root).resolve()
    _HOME = Path(body_home).resolve()
    _ensure_identity()


def _ensure_identity():
    """self_commit runs a bare `git commit`. A repo deployed by git fetch/reset
    has no *local* identity, and the phone has no global one either, so the
    commit aborts. Give the repo its own local identity when it lacks one — we
    check ``--local`` (not the inherited value) so the agent's self-commits are
    attributed to it on every machine, and so a host's global identity can't
    mask a repo that still needs one."""
    for key, val in (("user.name", "Niba"),
                     ("user.email", "niba@caelza.local")):
        cur = subprocess.run(["git", "config", "--local", key], cwd=_REPO,
                             capture_output=True, text=True).stdout.strip()
        if not cur:
            subprocess.run(["git", "config", "--local", key, val], cwd=_REPO,
                           capture_output=True, text=True)


def _git(*args):
    return subprocess.run(
        ["git", *args], cwd=_REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def _resolve(path: str) -> Path:
    p = (_REPO / path).resolve()
    if _REPO not in p.parents and p != _REPO:
        raise PermissionError(f"outside repo: {path}")
    if p == (_REPO / "caelza_body" / "supervisor.py"):
        raise PermissionError("immutable file: supervisor.py")
    if any(str(p).casefold().endswith(s.casefold()) for s in DENY_SUFFIXES):
        raise PermissionError(f"immutable file: {path}")
    parts = set(p.parts)
    if ".git" in parts:
        raise PermissionError("the git dir is off-limits")
    mmx = (Path.home() / ".mmx").resolve()
    if mmx == p or mmx in p.parents:
        raise PermissionError("mmx credentials are off-limits")
    if _HOME and p == (_HOME / "config.toml"):
        raise PermissionError("config is off-limits")
    return p


def register():
    @tools.tool("self_read_file", "Read a file from Niba's own repo.",
                {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]})
    def self_read_file(path):
        return _resolve(path).read_text(encoding="utf-8")

    @tools.tool("self_write_file", "Overwrite a file in Niba's own repo.",
                {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                 "required": ["path", "content"]})
    def self_write_file(path, content):
        target = _resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"written {path}"

    @tools.tool("self_list_tree", "List tracked + untracked files in Niba's repo.",
                {"type": "object", "properties": {}})
    def self_list_tree():
        return _git("ls-files", "--cached", "--others", "--exclude-standard")

    @tools.tool("self_run_tests", "Run Niba's own test suite (pytest -q).",
                {"type": "object", "properties": {}})
    def self_run_tests():
        out = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=_REPO,
                             capture_output=True, text=True)
        return (out.stdout + out.stderr)[-6000:]

    @tools.tool("self_commit", "git add -A && commit Niba's repo. Returns the short SHA.",
                {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]})
    def self_commit(message):
        _git("add", "-A")
        _git("commit", "-m", message)
        return _git("rev-parse", "--short", "HEAD")

    @tools.tool("self_request_restart",
                "Ask the supervisor to restart Niba on the current commit (it will probe first).",
                {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]})
    def self_request_restart(reason):
        head = _git("rev-parse", "HEAD")
        run = _HOME / "run"
        run.mkdir(parents=True, exist_ok=True)
        (run / "restart-request").write_text(
            json.dumps({"reason": reason, "commit": head, "ts": time.time()})
        )
        return "restart requested"
