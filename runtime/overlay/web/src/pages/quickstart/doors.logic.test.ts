import assert from "node:assert/strict";
import test from "node:test";

import {
  GUIDE_TIER,
  LADDER,
  LOCAL_ALIAS,
  RAM_BANDS,
  bandMb,
  doorOf,
  guessDefaults,
  localPick,
  nonEmptyFields,
  seedFieldValues,
  stagedLocalProvider,
} from "./doors.logic.ts";

test("the ladder on a phone: the 7B from 6 GB, the 1.5B below, Cael always the 1.5B", () => {
  const small = localPick("llamacpp", 3_500);
  assert.equal(small.model, "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M");
  assert.equal(small.guide, "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M");
  assert.deepEqual(small.notes, [
    "<= 5 GB RAM: the 1.5B is for chat and explanation; not reliable for multi-step tool calls. Bring a provider key for the agent loop",
  ]);
  const big = localPick("llamacpp", 7_600);
  assert.equal(big.model, "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M");
  assert.equal(big.guide, small.guide);
  assert.deepEqual(big.notes, [
    "7B Q4 on a phone is tight: keep context short (the server runs with -c 4096)",
    "one llama-server at a time: the agent model is served on :8080; Cael shares it unless you run a second server for the guide",
  ]);
  assert.equal(localPick("llamacpp", 6 * 1024).tier, "7b");
  assert.equal(localPick("llamacpp", 6 * 1024 - 1).tier, GUIDE_TIER);
});

test("the ladder on a hub: 14b from 16 GB, 8b from 8, 7b from 6, else the 1.5B", () => {
  assert.deepEqual(localPick("ollama", 16 * 1024), {
    runner: "ollama", tier: "14b", model: "deepseek-r1:14b", guide: "deepseek-r1:1.5b", notes: [],
  });
  const medium = localPick("ollama", 12 * 1024);
  assert.equal(medium.model, "deepseek-r1:8b");
  assert.deepEqual(medium.notes, ["8-12 GB: 8b. 14b needs 16 GB"]);
  assert.equal(localPick("ollama", 7_600).model, "deepseek-r1:7b");
  const tiny = localPick("ollama", 4 * 1024);
  assert.equal(tiny.model, "deepseek-r1:1.5b");
  assert.deepEqual(tiny.notes, ["under 8 GB on a hub: expect slow turns; a provider key is the better agent brain"]);
});

test("the bands are the ladder's thresholds", () => {
  assert.deepEqual(RAM_BANDS.map((b) => b.id), ["small", "phone", "medium", "large"]);
  assert.equal(bandMb("phone"), 6 * 1024);
  assert.equal(bandMb("large"), 16 * 1024);
  assert.equal(localPick("llamacpp", bandMb("small")).tier, GUIDE_TIER);
  assert.equal(localPick("llamacpp", bandMb("phone")).tier, "7b");
  assert.equal(localPick("ollama", bandMb("medium")).tier, "8b");
  assert.equal(localPick("ollama", bandMb("large")).tier, "14b");
  for (const runner of ["llamacpp", "ollama"] as const) {
    assert.ok(GUIDE_TIER in LADDER[runner], runner);
  }
});

test("the local door stages <runner>.local, the alias the installers write", () => {
  assert.deepEqual(stagedLocalProvider("ollama", " deepseek-r1:8b "), {
    provider_type: "ollama", alias: LOCAL_ALIAS, model: "deepseek-r1:8b", fields: {},
  });
  assert.equal(doorOf(stagedLocalProvider("llamacpp", "x")), "local");
  assert.equal(doorOf({ provider_type: "anthropic", alias: "default" }), "key");
  assert.equal(doorOf({ provider_type: "ollama", alias: "default" }), "key");
  // A second local setup writes local2 (setup.logic's providerAlias); it is still the local door.
  assert.equal(stagedLocalProvider("llamacpp", "x", {}, "local2").alias, "local2");
  assert.equal(doorOf({ provider_type: "llamacpp", alias: "local2" }), "local");
  assert.equal(doorOf({ provider_type: "llamacpp", alias: "localhost" }), "key");
});

test("the field buffer is seeded and trimmed the way upstream's form does it", () => {
  const seeded = seedFieldValues([
    { key: "model" },
    { key: "api_key", default: null },
    { key: "auth_mode", default: "api_key", enum_variants: ["api_key", "codex"] },
    { key: "wire", enum_variants: ["chat", "responses"] },
  ]);
  assert.deepEqual(seeded, { model: "", api_key: "", auth_mode: "api_key", wire: "chat" });
  assert.deepEqual(nonEmptyFields({ ...seeded, base_url: "  http://127.0.0.1:11434 " }), {
    auth_mode: "api_key", wire: "chat", base_url: "http://127.0.0.1:11434",
  });
});

test("a browser's guess: Android is a phone, deviceMemory picks the band", () => {
  assert.deepEqual(guessDefaults("Mozilla/5.0 (Linux; Android 14; REVVL 7 5G) Chrome/130"), { runner: "llamacpp", band: "small" });
  assert.deepEqual(guessDefaults("Mozilla/5.0 (X11; Linux x86_64) Firefox/130"), { runner: "ollama", band: "medium" });
  assert.deepEqual(guessDefaults("Mozilla/5.0 (Linux; Android 14)", 8), { runner: "llamacpp", band: "medium" });
  assert.deepEqual(guessDefaults("Mozilla/5.0 (Linux; Android 14)", 4), { runner: "llamacpp", band: "small" });
  assert.deepEqual(guessDefaults("Mozilla/5.0 (Macintosh)", 16), { runner: "ollama", band: "large" });
  assert.deepEqual(guessDefaults("Mozilla/5.0 (Macintosh)", 0), { runner: "ollama", band: "medium" });
});
