import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import test from "node:test";

import {
  APPROX_GB,
  OLLAMA_DOWNLOAD_PAGE,
  OLLAMA_URL,
  approxGb,
  gbOf,
  hasModel,
  listModels,
  missingModels,
  onThisComputer,
  parsePullChunk,
  percent,
  pullModel,
  stage,
  tagNames,
  type PullEvent,
} from "./ollama.logic.ts";
import { LADDER } from "../quickstart/doors.logic.ts";

test("only a page open on the computer itself, at an origin Ollama's CORS allows, probes its Ollama", () => {
  for (const h of ["127.0.0.1", "localhost", "LOCALHOST"]) assert.ok(onThisComputer(h), h);
  // Ollama's default origins are localhost and 127.0.0.1 only: [::1] and *.localhost would probe into a refusal.
  for (const h of ["::1", "[::1]", "caelza.localhost", "192.168.1.20", "hub.local", "caelza.example.com", "127.0.0.1.nip.io", ""]) assert.ok(!onThisComputer(h), h);
  assert.equal(OLLAMA_URL, "http://127.0.0.1:11434");
  assert.equal(OLLAMA_DOWNLOAD_PAGE, "https://ollama.com/download");
});

test("/api/tags: the names, and a bare name means :latest", () => {
  const body = { models: [{ name: "deepseek-r1:1.5b", size: 1 }, { name: "llama3" }, { nope: true }, "x", null] };
  assert.deepEqual(tagNames(body), ["deepseek-r1:1.5b", "llama3"]);
  assert.deepEqual(tagNames({ models: "no" }), []);
  assert.deepEqual(tagNames(null), []);
  assert.deepEqual(tagNames("[]"), []);
  const names = tagNames(body);
  assert.ok(hasModel(names, "deepseek-r1:1.5b"));
  assert.ok(hasModel(names, " deepseek-r1:1.5b "));
  assert.ok(hasModel(names, "llama3:latest"));
  assert.ok(hasModel(["llama3:latest"], "llama3"));
  assert.ok(!hasModel(names, "deepseek-r1:7b"));
  assert.ok(!hasModel(names, "deepseek-r1"));
});

test("what is missing: the agent's model first, Cael's once, nothing twice", () => {
  assert.deepEqual(missingModels([], ["deepseek-r1:8b", "deepseek-r1:1.5b"]), ["deepseek-r1:8b", "deepseek-r1:1.5b"]);
  assert.deepEqual(missingModels(["deepseek-r1:1.5b"], ["deepseek-r1:8b", "deepseek-r1:1.5b"]), ["deepseek-r1:8b"]);
  assert.deepEqual(missingModels([], ["deepseek-r1:1.5b", "deepseek-r1:1.5b"]), ["deepseek-r1:1.5b"]);
  assert.deepEqual(missingModels(["deepseek-r1:8b", "deepseek-r1:1.5b"], ["deepseek-r1:8b", "deepseek-r1:1.5b"]), []);
});

test("every Ollama tag on the ladder has an honest size, and the sum is one decimal", () => {
  for (const tag of Object.values(LADDER.ollama)) assert.ok(APPROX_GB[tag] !== undefined, tag);
  assert.equal(approxGb(["deepseek-r1:1.5b"]), 1.1);
  assert.equal(approxGb(["deepseek-r1:8b", "deepseek-r1:1.5b"]), 6);
  assert.equal(approxGb(["deepseek-r1:14b", "deepseek-r1:1.5b"]), 10.1);
  assert.equal(approxGb([]), 0);
  assert.equal(approxGb(["mystery:7b"]), null);
  assert.equal(gbOf(4_683_073_504), "4.7 GB");
  assert.equal(gbOf(0), "0.0 GB");
  assert.equal(gbOf(-5), "0.0 GB");
});

test("the pull stream: whole lines are events, the torn tail waits, junk is skipped", () => {
  const chunk = '{"status":"pulling manifest"}\n{"status":"pulling 6340a3d7f8f5","digest":"sha256:6340","total":1000,"completed":250}\nnot json\n{"status":"pul';
  const { events, rest } = parsePullChunk(chunk);
  assert.deepEqual(events, [
    { status: "pulling manifest" },
    { status: "pulling 6340a3d7f8f5", digest: "sha256:6340", total: 1000, completed: 250 },
  ]);
  assert.equal(rest, '{"status":"pul');
  const tail = parsePullChunk(`${rest}ling x","total":4,"completed":4}\n{"error":"pull model manifest: file does not exist"}\n`);
  assert.deepEqual(tail.events, [
    { status: "pulling x", total: 4, completed: 4 },
    { status: "", error: "pull model manifest: file does not exist" },
  ]);
  assert.equal(tail.rest, "");
  assert.deepEqual(parsePullChunk(""), { events: [], rest: "" });
  assert.deepEqual(parsePullChunk("\n\n[1]\n"), { events: [], rest: "" });
});

test("percent and stage read Ollama's status lines the way the page shows them", () => {
  const dl: PullEvent = { status: "pulling 6340a3d7f8f5", total: 4_683_073_504, completed: 1_170_768_376 };
  assert.equal(percent(dl), 25);
  assert.equal(stage(dl), "downloading");
  assert.equal(percent({ status: "pulling 6340a3d7f8f5", total: 10, completed: 10 }), 100);
  assert.equal(percent({ status: "pulling 6340a3d7f8f5", total: 10, completed: 11 }), 100);
  assert.equal(percent({ status: "pulling 6340a3d7f8f5", total: 0, completed: 0 }), null);
  assert.equal(percent({ status: "pulling manifest" }), null);
  assert.equal(percent(null), null);
  assert.equal(stage(null), "starting");
  assert.equal(stage({ status: "pulling manifest" }), "starting");
  assert.equal(stage({ status: "pulling 6340a3d7f8f5", digest: "sha256:6340" }), "starting");
  assert.equal(stage({ status: "verifying sha256 digest" }), "checking");
  assert.equal(stage({ status: "writing manifest" }), "finishing");
  assert.equal(stage({ status: "removing any unused layers" }), "finishing");
  assert.equal(stage({ status: "success" }), "done");
});

// A stand-in for Ollama on an ephemeral port: /api/tags answers a list, /api/pull
// streams the lines a real pull writes, one per write, as NDJSON.
function fakeOllama(lines: string[], tags: unknown = { models: [{ name: "deepseek-r1:1.5b" }] }) {
  const seen: { method: string; url: string; body: string }[] = [];
  const server = createServer((req: IncomingMessage, res: ServerResponse) => {
    let body = "";
    req.on("data", (c: Buffer) => {
      body += c.toString();
    });
    req.on("end", () => {
      seen.push({ method: req.method ?? "", url: req.url ?? "", body });
      if (req.url === "/api/tags") {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify(tags));
        return;
      }
      if (req.url === "/api/pull") {
        res.writeHead(200, { "Content-Type": "application/x-ndjson" });
        let i = 0;
        const tick = () => {
          if (i >= lines.length) {
            res.end();
            return;
          }
          res.write(lines[i++]);
          setTimeout(tick, 2);
        };
        tick();
        return;
      }
      res.writeHead(404);
      res.end();
    });
  });
  return new Promise<{ base: string; seen: typeof seen; close: () => Promise<void> }>((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address() as AddressInfo;
      resolve({
        base: `http://127.0.0.1:${port}`,
        seen,
        close: () => new Promise((r) => server.close(() => r())),
      });
    });
  });
}

test("listModels: the names when Ollama answers, null when nothing listens", async () => {
  const srv = await fakeOllama([]);
  try {
    assert.deepEqual(await listModels(1000, srv.base), ["deepseek-r1:1.5b"]);
  } finally {
    await srv.close();
  }
  // The port is closed now: a refused connection is "not there", not a thrown error.
  assert.equal(await listModels(1000, srv.base), null);
});

test("pullModel: asks for a stream, reports each event across torn chunks, resolves on success", async () => {
  const srv = await fakeOllama([
    '{"status":"pulling manifest"}\n{"status":"pulling 6340","digest":"sha256:6340","total":1000,"completed":0}\n',
    '{"status":"pulling 6340","digest":"sha256:6340","total":1000,"comp',
    'leted":500}\n{"status":"pulling 6340","digest":"sha256:6340","total":1000,"completed":1000}\n',
    '{"status":"verifying sha256 digest"}\n{"status":"writing manifest"}\n',
    '{"status":"success"}', // no trailing newline: the end of the body closes the last line
  ]);
  try {
    const got: PullEvent[] = [];
    await pullModel("deepseek-r1:1.5b", (e) => got.push(e), undefined, srv.base);
    assert.deepEqual(
      got.map((e) => [stage(e), percent(e)]),
      [["starting", null], ["downloading", 0], ["downloading", 50], ["downloading", 100], ["checking", null], ["finishing", null], ["done", null]],
    );
    const pull = srv.seen.find((r) => r.url === "/api/pull");
    assert.ok(pull);
    assert.equal(pull.method, "POST");
    assert.deepEqual(JSON.parse(pull.body), { name: "deepseek-r1:1.5b", stream: true });
  } finally {
    await srv.close();
  }
});

test("pullModel: Ollama's error line, a stream that ends early, and an abort each reject", async () => {
  const failing = await fakeOllama(['{"status":"pulling manifest"}\n', '{"error":"pull model manifest: file does not exist"}\n']);
  try {
    await assert.rejects(pullModel("nope:1b", () => {}, undefined, failing.base), /file does not exist/);
  } finally {
    await failing.close();
  }
  const early = await fakeOllama(['{"status":"pulling manifest"}\n', '{"status":"pulling 1","total":10,"completed":2}\n']);
  try {
    await assert.rejects(pullModel("deepseek-r1:1.5b", () => {}, undefined, early.base), /stopped before Ollama said it was complete/);
  } finally {
    await early.close();
  }
  const slow = await fakeOllama(Array.from({ length: 200 }, () => '{"status":"pulling 1","total":10,"completed":2}\n'));
  try {
    const ctl = new AbortController();
    let n = 0;
    await assert.rejects(
      pullModel(
        "deepseek-r1:1.5b",
        () => {
          if (++n === 3) ctl.abort();
        },
        ctl.signal,
        slow.base,
      ),
      (e: unknown) => e instanceof Error && e.name === "AbortError",
    );
    assert.ok(n < 200, "the abort stopped the stream");
  } finally {
    await slow.close();
  }
});
