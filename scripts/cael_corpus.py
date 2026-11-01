#!/usr/bin/env python3
"""Cael's docs corpus: the manual the guide answers from (vision §3.4, guide/CAEL.md).

    python3 scripts/cael_corpus.py build            # -> guide/corpus.jsonl from the sources below
    python3 scripts/cael_corpus.py build --check    # the committed corpus is current (CI)
    python3 scripts/cael_corpus.py load             # into Cael's memory through the running gateway
    python3 scripts/cael_corpus.py load --prune     # ... and drop chunks an older corpus left behind

Cael has no tools (risk profile `guide`: readonly, deny_all_tools), so the
corpus reaches him the way every agent's memory does: as entries in his own
memory, recalled on every turn by the Runtime (FTS5 keyword search in the
sqlite backend, `brain_query` under the Mind) and injected into his context,
which his SOUL.md already expects ("matching passages from the docs").

`build` chunks the sources by heading into pieces a small model can take
beside its prompt (CHUNK_CHARS), each opened by a breadcrumb line so he can say
where an answer comes from. `load` POSTs every chunk to the gateway's
`/api/memory` for agent `cael`, category `core`, keyed `docs/<page>#<n>`: the
Runtime upserts by (agent, key), so a reload replaces what it wrote. The
Android app loads the same file from its assets once the gateway answers.

Sources: this repo's README, guide/FAQ.md, mind/README.md, body/README.md,
and the owner-facing pages of the Runtime's book from the staged tree
(runtime/.build/src/docs/book/src, so the text is the rebranded one;
`./runtime/build.sh --no-build` stages it). Nothing here needs the gateway
except `load`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAGED_BOOK = REPO / "runtime" / ".build" / "src" / "docs" / "book" / "src"
CORPUS = REPO / "guide" / "corpus.jsonl"

#: Characters per chunk. Five recalled chunks (the Runtime's default limit)
#: stay under ~1.2k tokens beside SOUL.md on a phone's 4096-token context.
CHUNK_CHARS = 900
#: A section shorter than this joins the chunk before it when that still fits.
MIN_CHUNK_CHARS = 160
AGENT = "cael"
CATEGORY = "core"
KEY_PREFIX = "docs/"
GATEWAY = "http://127.0.0.1:42617"
GATEWAY_PORT = 42617

#: (path in this repo, breadcrumb root, key slug)
REPO_SOURCES = (
    ("guide/FAQ.md", "FAQ", "faq"),
    ("README.md", "Caelza", "readme"),
    ("mind/README.md", "The Mind", "mind"),
    ("body/README.md", "The Body", "body"),
)
#: The Runtime's book, the pages an owner asks about (not the developer's).
BOOK_ROOT = "Runtime docs"
BOOK_PAGES = (
    "introduction.md",
    "getting-started/concepts.md",
    "getting-started/quickstart.md",
    "getting-started/multi-model-setup.md",
    "getting-started/yolo.md",
    "providers/overview.md",
    "providers/routing.md",
    "security/overview.md",
    "security/model.md",
    "security/autonomy.md",
    "tools/overview.md",
    "agents/overview.md",
    "agents/anatomy.md",
    "agents/operating.md",
    "agents/filesystem.md",
    "channels/overview.md",
    "channels/telegram.md",
    "channels/peer-groups.md",
    "gateway/web-dashboard.md",
    "sop/index.md",
    "sop/how-it-works.md",
)

MACRO = re.compile(r"\{\{#(\w+)\s*([^}]*)\}\}")
INCLUDE = re.compile(r"\{\{#include\s+([^}\s]+)\s*\}\}")
HEADING = re.compile(r"^(#{1,4})\s+(.*?)\s*#*\s*$")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")


class CorpusError(Exception):
    pass


# --- markdown -> chunks --------------------------------------------------------

def resolve_includes(text: str, page: Path, depth: int = 0) -> str:
    """mdbook `{{#include ../_snippets/x.md}}`, inlined relative to the page."""
    def sub(m: re.Match) -> str:
        target = (page.parent / m.group(1)).resolve()
        if depth >= 4 or not target.is_file():
            return ""
        return resolve_includes(target.read_text(encoding="utf-8"), target, depth + 1)
    return INCLUDE.sub(sub, text)


def render_macros(text: str) -> str:
    """mdbook preprocessor macros ({{#config path}}, {{#env VAR}}, {{#secret …}}, {{#streaming
    channel="…" …}}) become the thing they name, in backticks."""
    def sub(m: re.Match) -> str:
        kind, arg = m.group(1), m.group(2).strip()
        if kind == "include":
            return ""
        pairs = re.findall(r'(\w+)="([^"]*)"', arg)
        if pairs:
            arg = ", ".join(f"{k} {v}" for k, v in pairs)
        return f"`{arg}`" if arg else ""
    return MACRO.sub(sub, text)


def clean(text: str) -> str:
    text = HTML_COMMENT.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = render_macros(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def plain_title(title: str) -> str:
    title = LINK.sub(r"\1", title)
    return re.sub(r"[`*_]", "", title).strip()


def sections(text: str) -> list[tuple[list[str], str]]:
    """(heading path, body) per heading in order; text before the first heading has an empty path."""
    out: list[tuple[list[str], str]] = []
    stack: list[str] = []
    body: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if line.startswith("```") or line.startswith("~~~"):
            in_fence = not in_fence
        m = None if in_fence else HEADING.match(line)
        if m:
            out.append((list(stack), "\n".join(body)))
            level = len(m.group(1))
            stack = stack[: level - 1] + [plain_title(m.group(2))]
            body = []
        else:
            body.append(line)
    out.append((list(stack), "\n".join(body)))
    return [(path, b.strip()) for path, b in out if b.strip()]


def paragraphs(body: str) -> list[str]:
    """Blank-line separated blocks; a fenced code block is one block."""
    blocks: list[str] = []
    cur: list[str] = []
    in_fence = False
    for line in body.split("\n"):
        if line.startswith("```") or line.startswith("~~~"):
            in_fence = not in_fence
            cur.append(line)
            if not in_fence:
                blocks.append("\n".join(cur))
                cur = []
            continue
        if not in_fence and not line.strip():
            if cur:
                blocks.append("\n".join(cur))
                cur = []
            continue
        cur.append(line)
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def pack(blocks: list[str], limit: int) -> list[str]:
    """Greedy: blocks into pieces of at most `limit` characters; a block over the
    limit on its own is split by lines."""
    pieces: list[str] = []
    cur = ""
    for block in blocks:
        if len(block) > limit:
            if cur:
                pieces.append(cur)
                cur = ""
            part = ""
            for ln in block.split("\n"):
                if part and len(part) + 1 + len(ln) > limit:
                    pieces.append(part)
                    part = ""
                part = f"{part}\n{ln}" if part else ln[:limit]
            if part:
                pieces.append(part)
            continue
        if cur and len(cur) + 2 + len(block) > limit:
            pieces.append(cur)
            cur = block
        else:
            cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        pieces.append(cur)
    return pieces


def chunk_page(text: str, root: str, slug: str, source: str, *, limit: int = CHUNK_CHARS) -> list[dict]:
    """One page into records: `{key, title, source, content}`, the content opened by
    its breadcrumb line `[root › H1 › H2]`."""
    records: list[dict] = []
    for path, body in sections(clean(text)):
        # The page's own H1 stands in for the root when it already names it
        # ("Caelza FAQ" under root "FAQ"), so the breadcrumb does not stutter.
        parts = path if path and root.lower() in path[0].lower() else [root, *path]
        title = " › ".join(parts)
        head = f"[{title}]"
        pieces = pack(paragraphs(body), max(limit - len(head) - 1, 80))
        for piece in pieces:
            content = f"{head}\n{piece}"
            # A tiny section rides with the chunk before it when that still fits.
            if records and len(piece) < MIN_CHUNK_CHARS and records[-1]["source"] == source \
                    and len(records[-1]["content"]) + 2 + len(content) <= limit:
                records[-1]["content"] += f"\n\n{content}"
                continue
            records.append({"key": "", "title": title, "source": source, "content": content})
    for i, rec in enumerate(records, 1):
        rec["key"] = f"{KEY_PREFIX}{slug}#{i}"
    return records


# --- build ---------------------------------------------------------------------

def build(book: Path = STAGED_BOOK, repo: Path = REPO) -> list[dict]:
    records: list[dict] = []
    for rel, root, slug in REPO_SOURCES:
        page = repo / rel
        if not page.is_file():
            raise CorpusError(f"{rel} is missing")
        records += chunk_page(page.read_text(encoding="utf-8"), root, slug, rel)
    if not book.is_dir():
        raise CorpusError(f"the Runtime's book is not staged at {book}: run ./runtime/build.sh --no-build first")
    for rel in BOOK_PAGES:
        page = book / rel
        if not page.is_file():
            raise CorpusError(f"{rel} is not in the staged book (the pin moved? update BOOK_PAGES)")
        text = resolve_includes(page.read_text(encoding="utf-8"), page)
        slug = "book/" + rel[: -len(".md")]
        records += chunk_page(text, BOOK_ROOT, slug, f"runtime docs/book/src/{rel}")
    keys = [r["key"] for r in records]
    if len(set(keys)) != len(keys):
        raise CorpusError("duplicate keys in the corpus")
    return records


def dumps(records: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)


def loads(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def stats(records: list[dict]) -> str:
    pages = len({r["source"] for r in records})
    total = sum(len(r["content"]) for r in records)
    longest = max((len(r["content"]) for r in records), default=0)
    return f"{len(records)} chunks from {pages} pages, {total:,} characters, longest chunk {longest}"


# --- load ----------------------------------------------------------------------

def default_token(config_dir: Path) -> str | None:
    """The gateway's first paired token from config.toml, for a loader on the
    same box; the dashboard's token works too (CAELZA_TOKEN or --token)."""
    cfg = config_dir / "config.toml"
    try:
        gateway = tomllib.loads(cfg.read_text(encoding="utf-8")).get("gateway", {})
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if not gateway.get("require_pairing", True):
        return None
    tokens = gateway.get("paired_tokens") or []
    return str(tokens[0]) if tokens else None


class Gateway:
    def __init__(self, base: str, token: str | None, opener=urllib.request.urlopen):
        self.base = base.rstrip("/")
        self.headers = {"Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.opener = opener

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=self.headers, method=method)
        with self.opener(req, timeout=30) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else {}


def load(records: list[dict], gateway: Gateway, *, agent: str = AGENT, prune: bool = False,
         dry_run: bool = False, say=print) -> int:
    """Every chunk into `agent`'s memory; the count of failures."""
    try:
        gateway.call("GET", "/health")
    except (urllib.error.URLError, OSError) as e:
        say(f"the gateway at {gateway.base} does not answer /health ({e}); start `caelza daemon` first")
        return 1
    say(f"{stats(records)} -> {gateway.base}/api/memory agent={agent} category={CATEGORY}" + (" (dry run)" if dry_run else ""))
    if dry_run:
        return 0
    failed = 0
    for rec in records:
        body = {"key": rec["key"], "content": rec["content"], "category": CATEGORY, "agent": agent}
        try:
            gateway.call("POST", "/api/memory", body)
        except urllib.error.HTTPError as e:
            failed += 1
            detail = e.read()[:200].decode("utf-8", "replace")
            say(f"  {rec['key']}: HTTP {e.code} {detail}")
            if e.code in (401, 403):
                say("  the gateway wants the paired token: --token, CAELZA_TOKEN, or --config-dir with gateway.paired_tokens")
                break
    say(f"loaded {len(records) - failed} of {len(records)} chunks" + (f", {failed} failed" if failed else ""))
    if prune and not failed:
        have = gateway.call("GET", f"/api/memory?agent={urllib.parse.quote(agent)}&category={CATEGORY}")
        entries = have.get("entries", []) if isinstance(have, dict) else have
        keep = {r["key"] for r in records}
        stale = sorted(str(e.get("key", "")) for e in entries
                       if str(e.get("key", "")).startswith(KEY_PREFIX) and e.get("key") not in keep)
        for key in stale:
            gateway.call("DELETE", f"/api/memory/{urllib.parse.quote(key, safe='')}?agent={urllib.parse.quote(agent)}")
        say(f"pruned {len(stale)} chunks an older corpus left behind")
    return 1 if failed else 0


# --- CLI -----------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cael_corpus", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="write guide/corpus.jsonl from the sources")
    b.add_argument("--check", action="store_true", help="compare with the committed corpus instead of writing; exit 1 on drift")
    b.add_argument("--book", type=Path, default=STAGED_BOOK, help="the staged Runtime book (default runtime/.build/src/docs/book/src)")
    b.add_argument("--out", type=Path, default=CORPUS)
    ld = sub.add_parser("load", help="load the corpus into Cael's memory through the gateway")
    ld.add_argument("--corpus", type=Path, default=CORPUS)
    ld.add_argument("--gateway", default=os.environ.get("CAELZA_GATEWAY", GATEWAY))
    ld.add_argument("--token", default=os.environ.get("CAELZA_TOKEN"), help="the paired bearer token (default: gateway.paired_tokens[0] from --config-dir)")
    ld.add_argument("--config-dir", type=Path, default=Path(os.environ.get("CAELZA_CONFIG_DIR", Path.home() / ".caelza")))
    ld.add_argument("--agent", default=AGENT)
    ld.add_argument("--prune", action="store_true", help="delete docs/* chunks the corpus no longer carries")
    ld.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.command == "build":
            records = build(a.book)
            text = dumps(records)
            if a.check:
                current = a.out.read_text(encoding="utf-8") if a.out.is_file() else ""
                if current != text:
                    print(f"{a.out} is stale: run `python3 scripts/cael_corpus.py build` and commit the result ({stats(records)})")
                    return 1
                print(f"{a.out} is current: {stats(records)}")
                return 0
            a.out.write_text(text, encoding="utf-8")
            print(f"{a.out}: {stats(records)}")
            return 0
        records = loads(a.corpus.read_text(encoding="utf-8"))
        token = a.token or default_token(a.config_dir)
        return load(records, Gateway(a.gateway, token), agent=a.agent, prune=a.prune, dry_run=a.dry_run)
    except CorpusError as e:
        print(f"cael_corpus: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
