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
`./runtime/build.sh --no-build` stages it). A chunk the Runtime's memory write
scanner would refuse (a URL and "token" on one line reads as exfiltration to
it) is left out at build time; `load` also skips what a gateway refuses that
way. Nothing here needs the gateway except `load`;
tests/test_cael_corpus_e2e.py runs the whole path against a real binary
(CAELZA_BIN) and a fake provider, and checks the recalled chunks reach Cael.
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

#: The Runtime's memory write scanner (crates/caelza-memory/src/threat.rs), ported
#: rule for rule: a chunk that matches is refused by `POST /api/memory` ("memory
#: write blocked by content scan"), so `build` leaves such chunks out and says so,
#: and `tests/test_cael_corpus.py` compares these patterns with the staged Rust.
#: Docs pages legitimately put a URL and the word "token" on one line; the
#: scanner cannot tell that from an exfiltration instruction, and losing a few
#: chunks is better than a corpus the gateway will not take.
#: Each rule is (kind, scope, pattern): `on` rules run at the default
#: `memory.policy.threat_scan = "on"`, `strict` ones only when a config asks for
#: strict. The build filters for the default; a strict gateway refuses a few more
#: at load time, and the loaders count those as left out rather than failed.
THREAT_PATTERNS = (
    ("exfil_curl", "on", r"(?i)\bcurl\b[^\n]*(?:\$[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)[A-Z_]*)"),
    ("exfil_wget", "on", r"(?i)\bwget\b[^\n]*(?:\$[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)[A-Z_]*)"),
    ("read_secrets", "on", r"(?i)\b(?:cat|less|more|tail|head)\b[^\n]*(?:\.env|\.netrc|\.pgpass|\.npmrc|id_rsa|id_ed25519)"),
    ("send_to_url", "on", r"(?i)https?://[^\s'\"]+[^\n]*(?:api[_-]?key|secret|token|password|credential)"),
    ("ssh_backdoor", "strict", r"(?i)authorized_keys"),
    ("ssh_access", "strict", r"(?i)(?:\$HOME|~|/home/[^/\s]+|/root)/\.ssh"),
    ("agent_config_mod", "on", r"(?i)\b(?:write|append|modify|edit|overwrite|replace)\b.{0,80}\b(?:AGENTS\.md|CLAUDE\.md)\b"),
    ("hardcoded_secret", "on", r"(?i)\b(?:api[_-]?key|secret|token|password|credential)\s*[:=]\s*['\"][A-Za-z0-9_./+=-]{16,}['\"]"),
    ("private_key", "on", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
THREATS = tuple((kind, scope, re.compile(pattern)) for kind, scope, pattern in THREAT_PATTERNS)
SCAN_SCOPE = "on"
SCAN_BLOCKED = "blocked by content scan"

#: mdbook directives: `{{#kind arg}}`; the kinds are hyphenated (`config-where`,
#: `env-var-name`), so `\w+` alone would stop at the hyphen and leave `-where …`.
MACRO = re.compile(r"\{\{#([\w-]+)\s*([^}]*)\}\}")
INCLUDE = re.compile(r"\{\{#include\s+([^}\s]+)\s*\}\}")
HEADING = re.compile(r"^(#{1,4})\s+(.*?)\s*#*\s*$")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
#: The book's per-surface tabs (`<div class="os-tabs-src">` with a `#### sh` /
#: `#### Windows` heading per tab, also what `config-where` and `secret-config`
#: render to). Their headings are tab labels, not sections.
OS_TABS = re.compile(r'^[ \t]*<div class="os-tabs-src">[ \t]*\n(.*?)^[ \t]*</div>[ \t]*$', re.S | re.M)
TAB_LABEL = re.compile(r"^([ \t]*)#{1,6}\s+(.*?)\s*$", re.M)
#: Directives that render a generated reference table in the book.
TABLE_MACROS = frozenset({"env-var-table", "env-var-bridge", "sop-trigger-index", "model-provider-fields",
                          "model-provider-catalog-table", "channel-streaming-matrix"})


class CorpusError(Exception):
    pass


# --- markdown -> chunks --------------------------------------------------------

def resolve_includes(text: str, page: Path, depth: int = 0, missing: list[tuple[str, str]] | None = None) -> str:
    """mdbook `{{#include ../_snippets/x.md}}`, inlined relative to the page. A target
    that is not there is dropped and, when `missing` is given, named in it as
    `(page, target)` so the build can say so instead of quietly losing the text."""
    def sub(m: re.Match) -> str:
        target = (page.parent / m.group(1)).resolve()
        if depth >= 4 or not target.is_file():
            if missing is not None:
                missing.append((page.name, m.group(1)))
            return ""
        return resolve_includes(target.read_text(encoding="utf-8"), target, depth + 1, missing)
    return INCLUDE.sub(sub, text)


def env_var_name(path: str) -> str:
    """`gateway.web_dist_dir` → `CAELZA_GATEWAY__WEB_DIST_DIR` (xtask's `env_form`)."""
    return "CAELZA_" + path.replace(".", "__").upper()


def render_macros(text: str) -> str:
    """The book's preprocessor directives, as the prose a reader of the rendered book
    sees (xtask/src/cmd/mdbook/peer_groups.rs): where a setting lives, what sets it,
    an env var's name; a directive that renders a generated table becomes a pointer
    to the docs, since the table itself is not corpus material."""
    def sub(m: re.Match) -> str:
        kind, arg = m.group(1), m.group(2).strip()
        pairs = dict(re.findall(r'(\w+)="([^"]*)"', arg))
        if kind == "include":
            return ""
        if kind == "config-where":
            # Always on a line of its own after "set it through any surface:", so a sentence.
            route = "/".join(arg.split())
            return (f"The dashboard's `/config/{route}` page, or caelcode's Config pane under `{arg.split()[0]}`."
                    if route else "The dashboard's Config pages.")
        if kind == "config-fields":
            return f"The `[{arg}]` fields are tabled in the Runtime docs."
        if kind == "config-set":
            return f"`caelza config set {arg} <value>` (or the same field on the dashboard's Config page)"
        if kind == "secret-config":
            return (f"`{arg}` is a secret: stored encrypted, never in plain `config.toml`. Set it with "
                    f"`caelza config set {arg}` (masked input) or on the dashboard's Config page, which encrypt on write.")
        if kind == "env-var-name":
            return f"`{env_var_name(arg)}`"
        if kind == "env-var":
            return f"(the `{arg}` environment variables are tabled in the Runtime docs)"
        if kind in TABLE_MACROS:
            return "(a generated table; see the Runtime docs)"
        if kind == "sop-trigger":
            return f"the `{arg}` trigger's fields (tabled in the Runtime docs)"
        if kind == "peer-group-example":
            return f"an example `{arg}` peer group"
        if kind == "thread-context":
            channel, prop = pairs.get("channel", arg), pairs.get("prop")
            return (f"On {channel}, threads are controlled by `{prop}`: on, each thread is its own conversation; "
                    f"off, replies post at the channel root." if prop
                    else f"On {channel}, threads are native, so each thread is already its own conversation.")
        if pairs:
            arg = ", ".join(f"{k} {v}" for k, v in pairs.items())
        return f"`{arg}`" if arg else ""
    return MACRO.sub(sub, text)


def flatten_tabs(text: str) -> str:
    """The book's per-surface tab blocks: the `<div>` goes, each tab's heading becomes a
    bold label line, so neither ends up as a section of its own."""
    def sub(m: re.Match) -> str:
        inner = TAB_LABEL.sub(lambda h: f"{h.group(1)}**{h.group(2)}**", m.group(1))
        return inner.strip("\n") + "\n"
    return OS_TABS.sub(sub, text)


def clean(text: str) -> str:
    text = HTML_COMMENT.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = flatten_tabs(render_macros(text))
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
    """Greedy: blocks into pieces of at most `limit` characters. A block over the
    limit on its own goes in line by line: its first lines still ride with what came
    before, its last lines stay open for what follows (so no piece is a stranded
    tail), and a fenced code block that has to be cut is closed and reopened, so
    every piece is whole markdown."""
    pieces: list[str] = []
    cur = ""
    for block in blocks:
        if len(block) <= limit:
            if cur and len(cur) + 2 + len(block) > limit:
                pieces.append(cur)
                cur = ""
            cur = f"{cur}\n\n{block}" if cur else block
            continue
        fence = ""      # the opening fence line while inside a code block
        first = True
        for ln in block.split("\n"):
            ln = ln[: limit - 16]        # room for a separator and a closing fence
            closes = bool(fence) and ln.startswith(fence[:3])
            sep = "\n\n" if first else "\n"
            tail = "" if closes or not fence else "\n```"
            if cur and len(cur) + len(sep) + len(ln) + len(tail) > limit:
                pieces.append(cur + ("\n```" if fence else ""))
                if closes:          # the cut closed the block already; the fence line is spent
                    cur, fence, first = "", "", False
                    continue
                cur = fence
                sep = "\n"
            cur = f"{cur}{sep}{ln}" if cur else ln
            first = False
            if ln.startswith(("```", "~~~")):
                fence = "" if fence else ln
    if cur:
        pieces.append(cur)
    return pieces


def findings(content: str, scope: str = SCAN_SCOPE) -> list[str]:
    """The scanner's kinds that match `content` under `scope` ("on", the default, or
    "strict", which adds the strict-only rules); empty when the gateway will store it."""
    active = {"on"} if scope == "on" else {"on", "strict"}
    return [kind for kind, rule_scope, rx in THREATS if rule_scope in active and rx.search(content)]


def chunk_page(text: str, root: str, slug: str, source: str, *, limit: int = CHUNK_CHARS,
               left_out: list[dict] | None = None) -> list[dict]:
    """One page into records: `{key, title, source, content}`, the content opened by
    its breadcrumb line `[root › H1 › H2]`. A chunk the write scanner would refuse
    is left out (and listed in `left_out` when given); the keys stay dense."""
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
            # A tiny piece rides with the chunk before it when that still fits: a tiny
            # section under its own breadcrumb, a tail of the same section as plain text.
            if records and len(piece) < MIN_CHUNK_CHARS and records[-1]["source"] == source:
                addition = f"\n\n{piece}" if records[-1]["title"] == title else f"\n\n{content}"
                if len(records[-1]["content"]) + len(addition) <= limit:
                    records[-1]["content"] += addition
                    continue
            records.append({"key": "", "title": title, "source": source, "content": content})
    kept: list[dict] = []
    for rec in records:
        hits = findings(rec["content"])
        if hits:
            if left_out is not None:
                left_out.append({"title": rec["title"], "source": source, "kinds": hits})
            continue
        kept.append(rec)
    for i, rec in enumerate(kept, 1):
        rec["key"] = f"{KEY_PREFIX}{slug}#{i}"
    return kept


# --- build ---------------------------------------------------------------------

def build(book: Path = STAGED_BOOK, repo: Path = REPO, left_out: list[dict] | None = None,
          missing: list[tuple[str, str]] | None = None) -> list[dict]:
    records: list[dict] = []
    for rel, root, slug in REPO_SOURCES:
        page = repo / rel
        if not page.is_file():
            raise CorpusError(f"{rel} is missing")
        records += chunk_page(page.read_text(encoding="utf-8"), root, slug, rel, left_out=left_out)
    if not book.is_dir():
        raise CorpusError(f"the Runtime's book is not staged at {book}: run ./runtime/build.sh --no-build first")
    for rel in BOOK_PAGES:
        page = book / rel
        if not page.is_file():
            raise CorpusError(f"{rel} is not in the staged book (the pin moved? update BOOK_PAGES)")
        text = resolve_includes(page.read_text(encoding="utf-8"), page, missing=missing)
        slug = "book/" + rel[: -len(".md")]
        records += chunk_page(text, BOOK_ROOT, slug, f"runtime docs/book/src/{rel}", left_out=left_out)
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
    failed = skipped = attempted = 0
    for rec in records:
        body = {"key": rec["key"], "content": rec["content"], "category": CATEGORY, "agent": agent}
        attempted += 1
        try:
            gateway.call("POST", "/api/memory", body)
        except urllib.error.HTTPError as e:
            detail = e.read()[:200].decode("utf-8", "replace")
            if SCAN_BLOCKED in detail:
                # The gateway's write scanner (a newer pin than the one `build` was checked
                # against): the chunk stays out, the rest goes in.
                skipped += 1
                say(f"  {rec['key']}: left out by the gateway's content scan")
                continue
            failed += 1
            say(f"  {rec['key']}: HTTP {e.code} {detail}")
            if e.code in (401, 403):
                say("  the gateway wants the paired token: --token, CAELZA_TOKEN, or --config-dir with gateway.paired_tokens")
                break
        except (urllib.error.URLError, OSError) as e:
            # The gateway went away mid-load: the rest would fail the same way.
            failed += 1
            say(f"  {rec['key']}: the gateway stopped answering ({e})")
            break
    not_tried = len(records) - attempted
    say(f"loaded {attempted - failed - skipped} of {len(records)} chunks"
        + (f", {skipped} left out by the content scan" if skipped else "")
        + (f", {failed} failed" if failed else "")
        + (f", {not_tried} not attempted" if not_tried else ""))
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
            left_out: list[dict] = []
            missing: list[tuple[str, str]] = []
            records = build(a.book, left_out=left_out, missing=missing)
            text = dumps(records)
            note = (f"; {len(left_out)} left out by the write scanner ({', '.join(sorted({k for d in left_out for k in d['kinds']}))})" if left_out else "") \
                + (f"; {len(missing)} includes missing from the staged book" if missing else "")
            if a.check:
                current = a.out.read_text(encoding="utf-8") if a.out.is_file() else ""
                if current != text:
                    print(f"{a.out} is stale: run `python3 scripts/cael_corpus.py build` and commit the result ({stats(records)}{note})")
                    return 1
                print(f"{a.out} is current: {stats(records)}{note}")
                return 0
            a.out.write_text(text, encoding="utf-8")
            print(f"{a.out}: {stats(records)}{note}")
            for d in left_out:
                print(f"  left out: {d['title']} ({d['source']}): {', '.join(d['kinds'])}")
            for page, target in missing:
                print(f"  missing include: {page} -> {target} (upstream's omission; the text is simply not there)")
            return 0
        records = loads(a.corpus.read_text(encoding="utf-8"))
        token = a.token or default_token(a.config_dir)
        return load(records, Gateway(a.gateway, token), agent=a.agent, prune=a.prune, dry_run=a.dry_run)
    except CorpusError as e:
        print(f"cael_corpus: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
