import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import {
  AGENT_NAME,
  KEY_ALIAS,
  TAGS,
  agentName,
  defaultModel,
  errorLines,
  extraRequiredFields,
  fill,
  judgeKey,
  keyPageName,
  modelRows,
  pickMemory,
  pickPreset,
  pickRuntime,
  providerById,
  providerRows,
  secretField,
  stagedKeyProvider,
  submission,
  type Catalog,
} from "./setup.logic.ts";

// The catalog beside this file in the staged tree (runtime/build.sh copies
// bundle/models.json here); from the overlay directory, the bundle's own.
const here = new URL(".", import.meta.url);
const candidates = [new URL("./models.json", here), new URL("../../../../../../bundle/models.json", here)];
const catalogPath = candidates.find((u) => existsSync(u));
assert.ok(catalogPath, "bundle/models.json is reachable from the test");
const catalog = JSON.parse(readFileSync(catalogPath, "utf8")) as Catalog;

const runtimeTypes = [
  { kind: "openrouter", display_name: "OpenRouter", local: false },
  { kind: "anthropic", display_name: "Anthropic", local: false },
  { kind: "openai", display_name: "OpenAI", local: false },
  { kind: "ollama", display_name: "Ollama", local: true },
  { kind: "gemini", display_name: "Google Gemini", local: false },
  { kind: "together", display_name: "Together AI", local: false },
  { kind: "azure", display_name: "Azure OpenAI", local: false },
  { kind: "llamacpp", display_name: "llama.cpp server", local: true },
];

test("the catalog has the eight providers, each resting on its best pick", () => {
  assert.equal(catalog.version, 1);
  assert.deepEqual(
    catalog.providers.map((p) => p.id),
    ["anthropic", "openai", "gemini", "openrouter", "groq", "deepseek", "mistral", "xai"],
  );
  for (const p of catalog.providers) {
    assert.equal(p.models.filter((m) => m.tag === "best").length, 1, p.id);
    assert.equal(p.models[0]?.tag, "best", `${p.id} rests on its best pick`);
    assert.ok(p.key_page.startsWith("https://"), p.id);
    for (const m of p.models) assert.ok(!m.tag || TAGS.includes(m.tag), `${p.id} ${m.id} ${m.tag}`);
  }
  assert.equal(providerById(catalog, "gemini")?.models_dev, "google");
  assert.equal(providerById(catalog, "nope"), null);
});

test("the provider wheel shows the curated ones the Runtime lists, then the rest under more", () => {
  const short = providerRows(catalog, runtimeTypes, false);
  assert.deepEqual(short.map((r) => r.id), ["anthropic", "openai", "gemini", "openrouter"]);
  assert.ok(short.every((r) => r.curated));
  const more = providerRows(catalog, runtimeTypes, true);
  assert.deepEqual(more.map((r) => r.id), ["anthropic", "openai", "gemini", "openrouter", "azure", "together"]);
  assert.deepEqual(more.slice(4).map((r) => r.curated), [false, false]);
  // Before the Runtime answers, every curated provider shows and "more" adds nothing.
  assert.equal(providerRows(catalog, null, true).length, catalog.providers.length);
});

test("the model wheel: picks in tag order, then the live catalog without repeats", () => {
  const anthropic = providerById(catalog, "anthropic")!;
  const rows = modelRows(anthropic, ["claude-haiku-5-5", "claude-opus-4-5", "claude-sonnet-5-5", "claude-opus-4-6"]);
  assert.deepEqual(rows.map((r) => r.tag ?? "-").slice(0, 3), ["best", "fast", "strong"]);
  assert.deepEqual(
    rows.map((r) => r.id),
    ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5", "claude-opus-4-5", "claude-opus-4-6"],
  );
  assert.deepEqual(rows.slice(5).map((r) => r.curated), [false, false]);
  assert.equal(defaultModel(rows), "claude-sonnet-5-5");
  // A provider from "more" has no picks: the live list alone, resting on its first row.
  const live = modelRows(null, ["b", "a"]);
  assert.deepEqual(live.map((r) => r.id), ["b", "a"]);
  assert.equal(defaultModel(live), "b");
  assert.equal(defaultModel([]), "");
  // A live list that is not there yet still shows the picks.
  assert.equal(modelRows(anthropic, null).length, anthropic.models.length);
});

test("the daemon's fields: the key field, and the other required ones", () => {
  const fields = [
    { key: "model", label: "Model", is_secret: false, required: true },
    { key: "api_key", label: "API key", is_secret: true, required: true },
    { key: "base_url", label: "Base URL", is_secret: false, required: true },
    { key: "wire", is_secret: false, required: true, enum_variants: ["chat", "responses"] },
    { key: "org", is_secret: false, required: false },
  ];
  assert.equal(secretField(fields)?.key, "api_key");
  assert.deepEqual(extraRequiredFields(fields).map((f) => f.key), ["base_url"]);
  assert.equal(secretField([{ key: "token", is_secret: true, required: true }])?.key, "token");
  assert.equal(secretField([{ key: "model", is_secret: false, required: true }]), null);
});

test("a key is one long word; a strange start is a warning, not a refusal", () => {
  assert.deepEqual(judgeKey(" sk-ant-api03-abcdefghijklmnop ", "sk-ant-"), { ok: true, warning: null });
  assert.deepEqual(judgeKey("sk-or-v1-abcdefghijklmnop", "sk-ant-"), { ok: true, warning: "prefix" });
  assert.deepEqual(judgeKey("abcdefghijklmnopqrstuvwxyz", ""), { ok: true, warning: null });
  assert.deepEqual(judgeKey("short", "sk-"), { ok: false, reason: "short" });
  assert.deepEqual(judgeKey("sk-ant with a space inside it here", "sk-ant-"), { ok: false, reason: "spaces" });
  assert.deepEqual(judgeKey("   ", "sk-"), { ok: false, reason: "empty" });
  assert.equal(keyPageName("https://console.anthropic.com/settings/keys"), "console.anthropic.com/settings/keys");
  assert.equal(keyPageName("https://console.x.ai/"), "console.x.ai");
});

test("the key door stages <provider>.default with the key under the daemon's field", () => {
  assert.deepEqual(stagedKeyProvider("anthropic", " claude-sonnet-5-5 ", "api_key", " sk-ant-x ", { base_url: " ", org: "o" }), {
    provider_type: "anthropic",
    alias: KEY_ALIAS,
    model: "claude-sonnet-5-5",
    fields: { org: "o", api_key: "sk-ant-x" },
  });
  assert.deepEqual(stagedKeyProvider("ollama", "m", null, "").fields, {});
});

test("the submission carries our defaults for everything the owner was not asked", () => {
  const state = {
    agents: [],
    default_runtime_profile: "balanced",
    model_provider_types: [
      { kind: "anthropic" },
      { kind: "llamacpp", default_runtime_profile: "local_small" },
    ],
    risk_presets: [{ preset_name: "locked_down" }, { preset_name: "balanced" }, { preset_name: "yolo" }],
    runtime_presets: [{ preset_name: "tight" }, { preset_name: "balanced" }],
    memory_kinds: ["sqlite", "markdown", "none"],
  };
  const staged = stagedKeyProvider("anthropic", "claude-sonnet-5-5", "api_key", "sk-ant-abcdefghijklmnop");
  const s = submission(state, staged);
  assert.deepEqual(s.model_provider, { mode: "fresh", value: staged });
  assert.deepEqual(s.risk_profile, { mode: "fresh", value: "balanced" });
  assert.deepEqual(s.runtime_profile, { mode: "fresh", value: "balanced" });
  assert.deepEqual(s.memory, { mode: "fresh", value: "sqlite" });
  assert.deepEqual(s.channels, []);
  assert.deepEqual(s.peer_groups, []);
  assert.deepEqual(s.agent, { name: AGENT_NAME, system_prompt: "", personality_file: null, personality_files: [] });
  // The local runner takes the daemon's recommended runtime profile.
  assert.equal(submission(state, { provider_type: "llamacpp", alias: "local", model: "x", fields: {} }).runtime_profile.value, "local_small");
  // Defaults when the daemon lists something else.
  assert.equal(pickPreset([{ preset_name: "strict" }], "balanced"), "strict");
  assert.equal(pickPreset([], "balanced"), "balanced");
  assert.equal(pickMemory(["markdown", "none"]), "markdown");
  assert.equal(pickMemory(["none"]), "none");
  assert.equal(pickMemory([]), "sqlite");
  assert.equal(pickRuntime({ ...state, default_runtime_profile: null, runtime_presets: [{ preset_name: "tight" }] }, "anthropic"), "tight");
  // A second run of setup does not collide with the agent that exists.
  assert.equal(agentName(["cael"]), "main");
  assert.equal(agentName(["main", "cael"]), "main2");
  assert.equal(agentName(["main", "main2"]), "main3");
});

test("errors and fills read as sentences", () => {
  assert.deepEqual(
    errorLines([
      { step: "model_provider", field: "api_key", message: "is required" },
      { step: "agent", field: "-", message: "agent `main` already exists" },
    ]),
    ["api_key: is required", "agent `main` already exists"],
  );
  assert.equal(fill("Get one at {page}, {n} steps", { page: "x", n: 2 }), "Get one at x, 2 steps");
  assert.equal(fill("keep {unknown}", {}), "keep {unknown}");
});
