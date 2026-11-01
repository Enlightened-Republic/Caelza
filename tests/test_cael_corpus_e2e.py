"""Cael's corpus against the real Runtime (set CAELZA_BIN; skipped otherwise).

A gateway from the real binary, `agents.cael` on a fake OpenAI-compatible
provider that logs every request it gets, the corpus loaded through the real
`POST /api/memory` for `cael`, then one turn with Cael: the Runtime's own
recall must put the matching chunks in front of the model. This is the
assumption guide/CAEL.md rests on; everything else in tests/test_cael_corpus.py
runs against fakes.

    CAELZA_BIN=runtime/dist/caelza python3 -m pytest tests/test_cael_corpus_e2e.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import cael_corpus as cc  # noqa: E402

BIN = os.environ.get("CAELZA_BIN")
pytestmark = pytest.mark.skipif(not BIN, reason="set CAELZA_BIN to run Cael's corpus against the real Runtime")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeProvider:
    """OpenAI-compatible: GET /v1/models for the warmup, POST /v1/chat/completions logged and answered."""

    def __init__(self):
        self.requests: list[dict] = []
        provider = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._send(200, {"object": "list", "data": [{"id": "fake-model", "object": "model"}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                provider.requests.append({"path": self.path, "body": body})
                self._send(200, {"id": "fake", "object": "chat.completion", "created": int(time.time()), "model": "fake-model",
                                 "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello! I'm Cael."}, "finish_reason": "stop"}],
                                 "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def caelza(config_dir: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    env = dict(os.environ, HOME=str(config_dir.parent), TERM="dumb")
    return subprocess.run([BIN, "--config-dir", str(config_dir), *args], capture_output=True, text=True, timeout=timeout, env=env)


def cset(config_dir: Path, path: str, value: str) -> None:
    out = caelza(config_dir, "config", "set", "--no-interactive", path, value)
    assert out.returncode == 0, f"config set {path}: {out.stdout}\n{out.stderr}"


def wait_health(port: int, seconds: int = 60) -> None:
    for _ in range(seconds * 2):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise AssertionError("the gateway never answered /health")


def test_the_corpus_goes_in_through_the_real_gateway_and_the_runtime_recalls_it_for_cael(tmp_path):
    provider = FakeProvider()
    config_dir = tmp_path / "home" / ".caelza"
    config_dir.mkdir(parents=True)
    gateway_port = free_port()
    gateway = None
    try:
        # The config model-setup.sh writes, with a fake provider as Cael's brain.
        cset(config_dir, "providers.models.custom.fake.uri", f"http://127.0.0.1:{provider.port}/v1")
        cset(config_dir, "providers.models.custom.fake.model", "fake-model")
        cset(config_dir, "providers.models.custom.fake.api_key", "not-needed")
        cset(config_dir, "agents.cael.model_provider", "custom.fake")
        cset(config_dir, "agents.cael.risk_profile", "guide")
        cset(config_dir, "risk_profiles.guide.level", "readonly")
        cset(config_dir, "risk_profiles.guide.deny_all_tools", "true")
        cset(config_dir, "gateway.require_pairing", "false")
        ws = config_dir / "agents" / "cael" / "workspace"
        ws.mkdir(parents=True)
        (ws / "SOUL.md").write_text((REPO_ROOT / "guide" / "cael.system.md").read_text())

        gateway = subprocess.Popen([BIN, "--config-dir", str(config_dir), "gateway", "start", "-p", str(gateway_port)],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   env=dict(os.environ, HOME=str(tmp_path / "home"), TERM="dumb"))
        wait_health(gateway_port)

        # The corpus through the real API, every chunk accepted (the build left out what the scanner refuses).
        records = cc.loads((REPO_ROOT / "guide" / "corpus.jsonl").read_text(encoding="utf-8"))
        said: list[str] = []
        rc = cc.load(records, cc.Gateway(f"http://127.0.0.1:{gateway_port}", None), prune=True, say=said.append)
        assert rc == 0, said
        assert f"loaded {len(records)} of {len(records)} chunks" in said[-2], said
        with urllib.request.urlopen(f"http://127.0.0.1:{gateway_port}/api/memory?agent=cael&category=core", timeout=10) as r:
            entries = json.loads(r.read()).get("entries", [])
        assert len(entries) == len(records), "every chunk is in Cael's memory, scoped to him"
        assert {e["key"] for e in entries} == {r["key"] for r in records}

        # One turn with Cael: the CLI runs the same agent loop over the same store, once the daemon has let go.
        gateway.terminate()
        gateway.wait(timeout=30)
        gateway = None
        out = caelza(config_dir, "agent", "-a", "cael", "-m", "What is an API key?")
        assert out.returncode == 0, out.stdout + out.stderr
        assert "Hello! I'm Cael." in out.stdout
    finally:
        if gateway is not None:
            gateway.terminate()
            gateway.wait(timeout=30)
        provider.close()

    chats = [r for r in provider.requests if "chat/completions" in r["path"]]
    assert chats, "the turn reached the provider"
    messages = chats[-1]["body"]["messages"]
    blob = "\n".join(str(m.get("content")) for m in messages)
    assert "You are Cael, the guide inside Caelza" in blob, "SOUL.md is in the system prompt"
    assert "[Memory context]" in blob, "the Runtime recalled from Cael's memory"
    assert "[Caelza FAQ › What is an API key?]" in blob, "the chunk that answers the question was recalled"
    assert "password for a model provider" in blob
