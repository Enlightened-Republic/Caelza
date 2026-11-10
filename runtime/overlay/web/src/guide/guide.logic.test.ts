import assert from "node:assert/strict";
import test from "node:test";

import {
  EMPTY_REPLY,
  GUIDE_SESSION_STORAGE,
  caelReady,
  foldReply,
  guideSessionId,
  nextRoute,
  question,
  questionOk,
  screenKeys,
  screenOf,
} from "./guide.logic.ts";

test("every route is a screen Cael can explain", () => {
  assert.equal(screenOf("/"), "home");
  assert.equal(screenOf("/agents"), "agents");
  assert.equal(screenOf("/agent/main"), "agent");
  assert.equal(screenOf("/agent/main/workspace"), "agent");
  assert.equal(screenOf("/looks/cael"), "looks");
  assert.equal(screenOf("/connect"), "connect");
  assert.equal(screenOf("/setup"), "setup");
  assert.equal(screenOf("/setup/providers"), "config", "the config explorer's deep link");
  assert.equal(screenOf("/config/agents/main"), "config");
  assert.equal(screenOf("/acp-console"), "acp");
  assert.equal(screenOf("/ACP-Console"), "acp");
  assert.equal(screenOf("/sops/new"), "sops");
  assert.equal(screenOf("/nope"), "other");
  assert.deepEqual(screenKeys("bodies"), { text: "guide.screen_bodies", next: "guide.next_bodies" });
  for (const s of ["home", "bodies", "memory", "procedures", "agents", "agent", "looks", "shop", "connect", "setup", "quickstart", "config", "tools", "skills", "sops", "runs", "integrations", "plugins", "cron", "dashboard", "logs", "pairing", "doctor", "canvas", "acp", "other"] as const) {
    assert.ok(nextRoute(s)?.startsWith("/"), s);
  }
});

test("the guide conversation is one per browser, minted once", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
  const first = guideSessionId(storage);
  assert.match(first, /^guide-[0-9a-f]+$/);
  assert.equal(guideSessionId(storage), first);
  assert.equal(store.get(GUIDE_SESSION_STORAGE), first);
  assert.match(guideSessionId(null), /^guide-/);
});

test("a question carries where the owner is", () => {
  const q = question("Bodies", "/bodies", "  what is a paired phone? ");
  assert.ok(q.startsWith('[The owner is looking at the "Bodies" screen of the Caelza dashboard (/bodies).'));
  assert.ok(q.endsWith("\nwhat is a paired phone?"));
  assert.ok(questionOk("hi") && !questionOk("   ") && !questionOk("x".repeat(2001)));
  assert.ok(caelReady(["main", "cael"]) && !caelReady(["main"]));
});

test("the stream folds: chunks append, a reset clears, done is final, an error ends it", () => {
  let r = foldReply(EMPTY_REPLY, { type: "chunk", content: "Hel" });
  r = foldReply(r, { type: "chunk", content: "lo" });
  assert.deepEqual(r, { text: "Hello", done: false, error: null });
  r = foldReply(r, { type: "thinking", content: "…" });
  assert.equal(r.text, "Hello");
  r = foldReply(r, { type: "chunk_reset" });
  assert.equal(r.text, "");
  r = foldReply(r, { type: "done", full_response: " Hello, owner. " });
  assert.deepEqual(r, { text: "Hello, owner.", done: true, error: null });
  assert.deepEqual(foldReply({ text: "partial", done: false, error: null }, { type: "done" }), { text: "partial", done: true, error: null });
  assert.deepEqual(foldReply(EMPTY_REPLY, { type: "error", message: "no model" }), { text: "", done: true, error: "no model" });
  assert.deepEqual(foldReply({ text: "some", done: false, error: null }, { type: "aborted" }), { text: "some", done: true, error: null });
  assert.equal(foldReply(EMPTY_REPLY, { type: "aborted" }).error, "the answer was stopped");
});
