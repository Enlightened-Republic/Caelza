from __future__ import annotations

from pathlib import Path


class Memory:
    def __init__(self, call_tool):
        self._call = call_tool
        self._pending: list[str] = []

    def remember(self, text, links=None):
        try:
            res = self._call("brain_write", {"text": text, "links": links or []})
            return res.get("id", "")
        except Exception:
            self._pending.append(text)
            return ""

    def flush_pending(self) -> int:
        done = 0
        still: list[str] = []
        for text in self._pending:
            try:
                self._call("brain_write", {"text": text, "links": []})
                done += 1
            except Exception:
                still.append(text)
        self._pending = still
        return done

    def recall(self, query, k=8):
        try:
            res = self._call("brain_query", {"query": query, "k": k})
            return res.get("results", [])
        except Exception:
            return []

    def link(self, a, b, rel):
        self._call("brain_link", {"from": a, "to": b, "type": rel})

    def supersede(self, node_id, text):
        self._call("brain_supersede", {"id": node_id, "text": text})


def spawn_sharpwave_session(db_path: Path):  # pragma: no cover
    """Start the `sharpwave` MCP stdio server in a background thread.

    Returns (call_tool, close). Implemented with the `mcp` package's stdio
    client running in a dedicated event-loop thread.

    The returned ``call_tool`` is an ADAPTER: ``Memory`` speaks a normalised
    dict protocol (``brain_write {text, links}`` -> ``{"id": ...}``,
    ``brain_query {query, k}`` -> ``{"results": [...]}``, etc.), and this
    closure translates that to the real SharpWave MCP API and parses its
    plain-text responses back into those dicts.

    Verified against **sharpwave 0.2.1** (tools listed
    live) on 2026-08-29. Re-confirm against the SharpWave repo / a newer
    release before trusting these mappings:
      - brain_write requires {type,label,content}; replies
        `Written: node <uuid> (<type>) "<label>"`. No `links` arg (auto-links).
      - brain_query takes {query,type?,limit?}; replies a plain-text listing,
        one result per block:
            [<id8>] (<type>) <label>
              <content text>
              R=<retrievability> sal=<salience> imp=<importance>
        blocks separated by a blank line; `No matching nodes found.` when empty.
      - brain_link takes {from_id,to_id,edge_type} (enum; see _VALID_EDGE_TYPES).
      - brain_supersede takes {old_node_id,new_content,new_label?}.
    """
    import asyncio
    import atexit
    import os
    import re
    import signal
    import threading
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    def _kill_our_sharpwave():
        """SIGKILL any sharpwave/node process that is a direct child of THIS
        process. Registered as an atexit hook (and called from close()) so a
        stopped agent — including the SIGTERM -> sys.exit path, and a SIGTERM
        that lands mid-startup before close() is even wired — never orphans its
        MCP child onto the brain.db lock. Repeated orphans wedge SharpWave."""
        try:
            me = os.getpid()
            proc = Path("/proc")
            if not proc.is_dir():
                return  # not Linux (dev box) — nothing to reap
            for d in proc.iterdir():
                if not d.name.isdigit():
                    continue
                try:
                    after = (d / "stat").read_text().rsplit(")", 1)[1].split()
                    ppid = int(after[1])
                    cmd = (d / "cmdline").read_bytes().decode("utf-8", "replace")
                except (OSError, ValueError, IndexError):
                    continue
                if ppid == me and "sharpwave" in cmd:
                    try:
                        os.kill(int(d.name), signal.SIGKILL)
                    except OSError:
                        pass
        except Exception:  # noqa: BLE001 - a reaper must never raise
            pass

    atexit.register(_kill_our_sharpwave)

    _VALID_EDGE_TYPES = {
        "caused_by", "associates", "supports", "instance_of", "goal_of",
        "before", "after", "inhibits", "summarizes", "attaches_to",
        "contradicts", "supersedes", "coreference_of", "drives",
    }
    _WRITE_RE = re.compile(r"node\s+([0-9a-fA-F][0-9a-fA-F-]{7,})")
    _HEAD_RE = re.compile(r"^\[([0-9a-fA-F]+)\]\s*\((\w+)\)\s*(.*)$")
    _R_RE = re.compile(r"^R=([0-9.]+)")

    Path(db_path).mkdir(parents=True, exist_ok=True)
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    state = {}

    async def _main():
        state["stop"] = asyncio.Event()
        try:
            # `sharpwave` must be installed (npm i -g --allow-scripts=better-sqlite3
            # sharpwave); `npx -y` breaks on Termux (no /usr/bin/env for the shebang).
            params = StdioServerParameters(
                command="sharpwave", args=[],
                env={**os.environ, "SHARPWAVE_DB": str(db_path)},
            )
            async with stdio_client(params) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    state["session"] = session
                    ready.set()
                    await state["stop"].wait()
        except Exception as e:  # noqa: BLE001 - surface startup failure to the caller
            state["error"] = e
        finally:
            ready.set()

    def _run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_main())

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    ready.wait(timeout=120)  # first sharpwave start can be slow
    if "error" in state or "session" not in state:
        raise RuntimeError(f"sharpwave did not start: {state.get('error', 'timeout')}")

    def _invoke(name, args):
        """Call a raw SharpWave MCP tool; return its concatenated text output."""
        fut = asyncio.run_coroutine_threadsafe(
            state["session"].call_tool(name, args), loop
        )
        result = fut.result(timeout=30)
        return "".join(
            p.text for p in result.content if getattr(p, "type", None) == "text"
        )

    def _parse_query(text):
        text = (text or "").strip()
        if not text or text.lower().startswith("no matching nodes"):
            return []
        results = []
        cur = None
        for line in text.splitlines():
            s = line.strip()
            head = _HEAD_RE.match(s)
            if head:
                if cur:
                    results.append(cur)
                cur = {"id": head.group(1), "text": "", "score": 0.0}
                continue
            if cur is None or not s:
                continue
            rm = _R_RE.match(s)
            if rm:
                cur["score"] = float(rm.group(1))
            else:
                cur["text"] = (cur["text"] + " " + s).strip() if cur["text"] else s
        if cur:
            results.append(cur)
        # Graceful degradation: header parsing failed -> keep raw lines as hits.
        if not results:
            results = [{"text": ln.strip()} for ln in text.splitlines() if ln.strip()]
        return results

    def call_tool(name, args):
        if name == "brain_write":
            content = args.get("text", "") or ""
            label = content.strip()[:60] or "note"
            out = _invoke("brain_write", {
                "type": "semantic", "label": label, "content": content,
            })
            m = _WRITE_RE.search(out)
            return {"id": m.group(1) if m else ""}

        if name == "brain_query":
            out = _invoke("brain_query", {
                "query": args.get("query", ""), "limit": args.get("k", 8),
            })
            return {"results": _parse_query(out)}

        if name == "brain_link":
            rel = args.get("type", "")
            if rel not in _VALID_EDGE_TYPES:
                rel = "associates"
            _invoke("brain_link", {
                "from_id": args.get("from"), "to_id": args.get("to"),
                "edge_type": rel,
            })
            return {}

        if name == "brain_supersede":
            _invoke("brain_supersede", {
                "old_node_id": args.get("id"), "new_content": args.get("text", ""),
            })
            return {}

        return {"raw": _invoke(name, args)}

    def close():
        stop = state.get("stop")
        if stop is not None:
            loop.call_soon_threadsafe(stop.set)
        else:  # never got far enough to create the event
            loop.call_soon_threadsafe(loop.stop)
        # stdio_client's own teardown can be slow / miss on an abrupt stop;
        # make sure the node process is gone.
        _kill_our_sharpwave()

    return call_tool, close
