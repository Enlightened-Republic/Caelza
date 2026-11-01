"""Cael's docs corpus (vision §3.4, guide/CAEL.md): the manual the guide answers from.

scripts/cael_corpus.py chunks the repo's owner-facing docs and the staged
Runtime book into guide/corpus.jsonl and loads them into Cael's memory
through the gateway's /api/memory, where the Runtime's per-turn recall finds
them (no tools: Cael's risk profile denies them all). These tests pin the
chunker, the committed corpus, the loader against a fake gateway, the FAQ's
facts against the rest of the repo, and the wiring.
"""
from __future__ import annotations

import io
import json
import re
import sys
import threading
import tomllib
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import cael_corpus as cc  # noqa: E402

CORPUS = REPO_ROOT / "guide" / "corpus.jsonl"
RECORDS = cc.loads(CORPUS.read_text(encoding="utf-8"))
FAQ = (REPO_ROOT / "guide" / "FAQ.md").read_text(encoding="utf-8")
REGENERATE = "stale corpus: run `python3 scripts/cael_corpus.py build` (after ./runtime/build.sh --no-build) and commit the result"


# --- the chunker -----------------------------------------------------------------

PAGE = """# Keys

Intro paragraph about keys.

{{#include ../_snippets/missing.md}}

## Where a key goes

Set it with {{#config providers.models.anthropic.default.api_key}} and read {{#env CAELZA_HOME}}.

```sh
caelza config set providers.models.anthropic.default.api_key
caelza config set agents.main.model_provider anthropic.default
```

<!-- an editor's note -->

## A long section

""" + "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(12)) + """

### Tiny

One line.
"""


def test_the_chunker_splits_on_headings_keeps_code_whole_and_stays_under_the_limit():
    recs = cc.chunk_page(PAGE, "Runtime docs", "book/keys", "runtime docs/book/src/keys.md", limit=600)
    assert [r["key"] for r in recs] == [f"docs/book/keys#{i}" for i in range(1, len(recs) + 1)]
    assert all(len(r["content"]) <= 600 for r in recs)
    assert all(r["content"].startswith("[Runtime docs › Keys") for r in recs)
    assert all(r["source"] == "runtime docs/book/src/keys.md" for r in recs)
    where = next(r for r in recs if r["title"] == "Runtime docs › Keys › Where a key goes")
    assert "`providers.models.anthropic.default.api_key`" in where["content"], "macros become the thing they name"
    assert "`CAELZA_HOME`" in where["content"] and "{{#" not in where["content"]
    assert "editor's note" not in where["content"], "HTML comments are dropped"
    assert "```sh\ncaelza config set providers.models.anthropic.default.api_key\ncaelza config set agents.main.model_provider anthropic.default\n```" in where["content"], \
        "a code block is one block"
    long = [r for r in recs if r["title"].endswith("A long section")]
    assert len(long) >= 3, "a long section is packed into several chunks"
    assert all(r["content"].startswith("[Runtime docs › Keys › A long section]\n") for r in long)
    tiny = [r for r in recs if "Tiny" in r["content"]]
    assert len(tiny) == 1 and "One line." in tiny[0]["content"]


def test_a_block_longer_than_the_limit_is_split_by_lines_and_a_tiny_section_rides_along():
    pieces = cc.pack(["x" * 50, "\n".join(["line"] * 100), "y" * 20], 120)
    assert all(len(p) <= 120 for p in pieces)
    assert pieces[0] == "x" * 50 and pieces[-1] == "y" * 20
    page = "# T\n\nbody " * 1 + "\n\n## Small\n\nshort.\n"
    recs = cc.chunk_page(page, "Root", "s", "s.md", limit=900)
    assert len(recs) == 1 and "[Root › T › Small]\nshort." in recs[0]["content"]


def test_includes_resolve_relative_to_the_page(tmp_path):
    (tmp_path / "_snippets").mkdir()
    (tmp_path / "_snippets" / "a.md").write_text("From the snippet.\n")
    page = tmp_path / "page.md"
    page.write_text("# P\n\n{{#include _snippets/a.md}}\n\n{{#include _snippets/nope.md}}\n")
    text = cc.resolve_includes(page.read_text(), page)
    assert "From the snippet." in text and "nope" not in text
    assert "{{#include" not in cc.clean(text)


def test_breadcrumbs_do_not_stutter_when_the_page_names_its_root():
    recs = cc.chunk_page("# Caelza FAQ\n\n## Q\n\nA.\n", "FAQ", "faq", "guide/FAQ.md")
    assert recs[0]["title"] == "Caelza FAQ › Q"
    recs = cc.chunk_page("# Concepts\n\nText.\n", "Runtime docs", "book/c", "c.md")
    assert recs[0]["title"] == "Runtime docs › Concepts"


# --- the committed corpus --------------------------------------------------------

def test_the_committed_corpus_is_well_formed_and_sized_for_a_phone():
    keys = [r["key"] for r in RECORDS]
    assert len(keys) == len(set(keys)) and all(k.startswith(cc.KEY_PREFIX) for k in keys)
    assert all(set(r) == {"key", "title", "source", "content"} for r in RECORDS)
    assert all(len(r["content"]) <= cc.CHUNK_CHARS for r in RECORDS), "five recalled chunks must fit beside SOUL.md on a 4096-token context"
    assert all(r["content"].startswith("[") and "]\n" in r["content"] for r in RECORDS), "every chunk opens with its breadcrumb"
    assert not any("{{#" in r["content"] for r in RECORDS), "mdbook macros are rendered"
    sources = {r["source"] for r in RECORDS}
    assert {s for s, _, _ in cc.REPO_SOURCES} <= sources
    assert {f"runtime docs/book/src/{p}" for p in cc.BOOK_PAGES} == {s for s in sources if s.startswith("runtime docs/")}
    assert any(r["key"].startswith("docs/faq#") for r in RECORDS)
    assert any("DeepSeek-R1-Distill-Qwen-7B" in r["content"] for r in RECORDS if r["key"].startswith("docs/faq#"))
    assert 200 <= len(RECORDS) <= 800, len(RECORDS)
    assert CORPUS.stat().st_size < 400_000, "keep the corpus small enough to bundle in the app"


def test_the_committed_corpus_is_current_with_the_sources():
    """Needs the staged Runtime book (./runtime/build.sh --no-build); CI's runtime job runs `build --check` after staging."""
    if not cc.STAGED_BOOK.is_dir():
        pytest.skip("the Runtime book is not staged here")
    assert cc.dumps(cc.build()) == CORPUS.read_text(encoding="utf-8"), REGENERATE


# --- the loader ------------------------------------------------------------------

class FakeGateway:
    """The gateway's memory API: /health, POST /api/memory (upsert by key), GET /api/memory?agent=, DELETE."""

    def __init__(self, *, require_token: str | None = None, fail_key: str | None = None):
        self.entries: dict[str, dict] = {"docs/old#1": {"key": "docs/old#1", "content": "stale", "category": "core"},
                                         "note": {"key": "note", "content": "the owner's", "category": "core"}}
        self.posts: list[dict] = []
        self.deleted: list[str] = []
        self.require_token = require_token
        self.fail_key = fail_key
        gw = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authed(self):
                if gw.require_token is None:
                    return True
                return self.headers.get("Authorization") == f"Bearer {gw.require_token}"

            def do_GET(self):
                if self.path == "/health":
                    return self._send(200, {"status": "ok"})
                if not self._authed():
                    return self._send(401, {"error": "Unauthorized"})
                if self.path.startswith("/api/memory"):
                    return self._send(200, {"entries": list(gw.entries.values())})
                self._send(404, {})

            def do_POST(self):
                if not self._authed():
                    return self._send(401, {"error": "Unauthorized"})
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                gw.posts.append(body)
                if body.get("key") == gw.fail_key:
                    return self._send(500, {"error": "Memory store failed: boom"})
                gw.entries[body["key"]] = body
                self._send(200, {"status": "ok"})

            def do_DELETE(self):
                if not self._authed():
                    return self._send(401, {"error": "Unauthorized"})
                key = urllib.request.unquote(self.path.split("/api/memory/", 1)[1].split("?", 1)[0])
                gw.deleted.append(key)
                gw.entries.pop(key, None)
                self._send(200, {"status": "ok", "deleted": True})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


SAMPLE = [{"key": "docs/faq#1", "title": "FAQ", "source": "guide/FAQ.md", "content": "[FAQ]\nA."},
          {"key": "docs/faq#2", "title": "FAQ", "source": "guide/FAQ.md", "content": "[FAQ]\nB."}]


def test_the_loader_upserts_every_chunk_for_cael_and_prunes_only_stale_docs():
    gw = FakeGateway()
    try:
        out = io.StringIO()
        rc = cc.load(SAMPLE, cc.Gateway(gw.base, None), prune=True, say=lambda s: out.write(s + "\n"))
        assert rc == 0
        assert gw.posts == [{"key": "docs/faq#1", "content": "[FAQ]\nA.", "category": "core", "agent": "cael"},
                            {"key": "docs/faq#2", "content": "[FAQ]\nB.", "category": "core", "agent": "cael"}]
        assert gw.deleted == ["docs/old#1"], "the owner's own note is never touched"
        assert "loaded 2 of 2 chunks" in out.getvalue() and "pruned 1 chunks" in out.getvalue()
        # A second load is the same two upserts; nothing left to prune.
        rc = cc.load(SAMPLE, cc.Gateway(gw.base, None), prune=True, say=lambda s: None)
        assert rc == 0 and gw.deleted == ["docs/old#1"]
    finally:
        gw.close()


def test_the_loader_sends_the_bearer_token_and_stops_on_a_401():
    gw = FakeGateway(require_token="paired-token")
    try:
        said = []
        rc = cc.load(SAMPLE, cc.Gateway(gw.base, None), say=said.append)
        assert rc == 1 and gw.posts == [] and any("HTTP 401" in s for s in said) and any("paired token" in s for s in said)
        rc = cc.load(SAMPLE, cc.Gateway(gw.base, "paired-token"), say=said.append)
        assert rc == 0 and len(gw.posts) == 2
    finally:
        gw.close()


def test_the_loader_reports_a_failed_chunk_and_a_dead_gateway():
    gw = FakeGateway(fail_key="docs/faq#2")
    try:
        said = []
        rc = cc.load(SAMPLE, cc.Gateway(gw.base, None), prune=True, say=said.append)
        assert rc == 1 and any("docs/faq#2: HTTP 500" in s for s in said) and gw.deleted == [], "no pruning after a failure"
        assert cc.load(SAMPLE, cc.Gateway(gw.base, None), dry_run=True, say=said.append) == 0 and gw.posts[-1]["key"] == "docs/faq#2"
    finally:
        gw.close()
    said = []
    assert cc.load(SAMPLE, cc.Gateway("http://127.0.0.1:9", None), say=said.append) == 1
    assert any("does not answer /health" in s for s in said)


def test_the_default_token_is_the_gateways_paired_token_only_when_pairing_is_on(tmp_path):
    (tmp_path / "config.toml").write_text('[gateway]\nrequire_pairing = true\npaired_tokens = ["tok-1", "tok-2"]\n')
    assert cc.default_token(tmp_path) == "tok-1"
    (tmp_path / "config.toml").write_text('[gateway]\nrequire_pairing = false\npaired_tokens = ["tok-1"]\n')
    assert cc.default_token(tmp_path) is None
    assert cc.default_token(tmp_path / "nope") is None


def test_the_cli_builds_checks_and_refuses_an_unstaged_book(tmp_path, capsys):
    book = tmp_path / "book"
    (book / "getting-started").mkdir(parents=True)
    for rel in cc.BOOK_PAGES:
        p = book / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {rel}\n\nText for {rel}.\n")
    out = tmp_path / "corpus.jsonl"
    assert cc.main(["build", "--book", str(book), "--out", str(out)]) == 0
    assert cc.main(["build", "--check", "--book", str(book), "--out", str(out)]) == 0
    out.write_text(out.read_text() + '{"key": "docs/extra#1"}\n')
    assert cc.main(["build", "--check", "--book", str(book), "--out", str(out)]) == 1
    assert "stale" in capsys.readouterr().out
    assert cc.main(["build", "--book", str(tmp_path / "missing"), "--out", str(out)]) == 2
    assert "run ./runtime/build.sh --no-build first" in capsys.readouterr().err


# --- the FAQ's facts and the wiring --------------------------------------------------

def test_the_faq_agrees_with_the_rest_of_the_repo():
    manifest = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
    android = manifest["android"]
    assert "http://127.0.0.1:42617" in FAQ and str(android["body_port"]) == "42618" and "127.0.0.1:42618" in FAQ
    assert f"127.0.0.1:{android['model_server_port']}" in FAQ
    soul = (REPO_ROOT / "guide" / "cael.system.md").read_text()
    for fact in ("no account and no API key", "encrypted on this device", "needs Shizuku", "after every reboot", "snapshot"):
        assert fact in FAQ and fact.split()[0] in soul, fact
    ladder = (REPO_ROOT / "scripts" / "model_ladder.py").read_text()
    for name in ("deepseek-r1:14b", "DeepSeek-R1-Distill-Qwen-7B"):
        assert name in FAQ and name in ladder
    body_home = (REPO_ROOT / "android/app/src/main/java/tech/enlightenedrepublic/caelza/body/BodyHome.kt").read_text()
    assert 'AUDIT_LOG = "logs/device-actions.log"' in body_home and "~/.caelza-body/logs/device-actions.log" in FAQ
    for cmd in ("caelza config set", "caelza memory stats", "caelza-body runtime update", "caelza-body fleet join", "caelza gateway get-paircode"):
        assert cmd in FAQ, cmd
    assert "guide/corpus.jsonl" in FAQ


def test_the_corpus_is_wired_in():
    setup = (REPO_ROOT / "scripts" / "model-setup.sh").read_text()
    assert "scripts/cael_corpus.py load" in setup, "model-setup's next steps load the corpus once the gateway runs"
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "python3 scripts/cael_corpus.py build --check" in ci
    assert ci.index("./runtime/build.sh --no-build") < ci.index("python3 scripts/cael_corpus.py build --check"), "after staging"
    manifest = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
    assert manifest["components"]["runtime"]["cael_corpus"] == "guide/corpus.jsonl"
    cael = (REPO_ROOT / "guide" / "CAEL.md").read_text()
    assert "corpus.jsonl" in cael and "cael_corpus.py" in cael
    assert "Cael has no corpus yet" not in cael
    vision = (REPO_ROOT / "docs" / "design" / "caelza-vision.md").read_text()
    assert "Cael's docs corpus waits on" not in vision and "cael_corpus.py" in vision
    example = (REPO_ROOT / "runtime" / "caelza.local-model.example.toml").read_text()
    assert "cael_corpus.py" in example
    assert cc.GATEWAY == f"http://127.0.0.1:{cc.GATEWAY_PORT}"
    assert str(cc.GATEWAY_PORT) in (REPO_ROOT / "android/app/src/main/java/tech/enlightenedrepublic/caelza/runtime/RuntimeStore.kt").read_text()


def test_the_app_bundles_the_same_corpus_and_loads_it_the_same_way():
    app = REPO_ROOT / "android" / "app"
    asset = app / "src" / "main" / "assets" / "cael-corpus.jsonl"
    assert asset.read_bytes() == CORPUS.read_bytes(), "copy guide/corpus.jsonl to android/app/src/main/assets/cael-corpus.jsonl"
    manifest = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
    assert manifest["android"]["cael_corpus"] == "android/app/src/main/assets/cael-corpus.jsonl"
    kt = (app / "src/main/java/tech/enlightenedrepublic/caelza/guide/CaelCorpus.kt").read_text()
    assert 'const val ASSET = "cael-corpus.jsonl"' in kt
    assert f'const val AGENT = "{cc.AGENT}"' in kt and f'const val CATEGORY = "{cc.CATEGORY}"' in kt
    assert '"http://127.0.0.1:$port/api/memory"' in kt, "the same endpoint the Python loader posts to"
    service = (app / "src/main/java/tech/enlightenedrepublic/caelza/RuntimeService.kt").read_text()
    assert "scope.launch { loadCaelCorpus() }" in service and "CaelCorpus(store.configDir).load(" in service
    assert service.index("RuntimeState(Phase.RUNNING, version)") < service.index("scope.launch { loadCaelCorpus() }")
