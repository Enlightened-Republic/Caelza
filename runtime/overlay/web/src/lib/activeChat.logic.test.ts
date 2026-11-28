import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { chatAgentFor, chatDocumentTitle, emptyChatLine, withAgentName } from "./activeChat.logic.ts";

test("a chat route is about the tab in front, falling back to the alias in the address", () => {
  assert.equal(chatAgentFor("/agent/nova", null), "nova");
  // The workspace mirrors tabs with replaceState, so the router can still say "main".
  assert.equal(chatAgentFor("/agent/main", "nova"), "nova");
  assert.equal(chatAgentFor("/agent/my%20bot", null), "my bot");
  assert.equal(chatAgentFor("/agent/%E0%A4%A", null), "%E0%A4%A");
});

test("an agent's file workspace is about that agent, whatever tab is in front", () => {
  assert.equal(chatAgentFor("/agent/nova/workspace", "main"), "nova");
});

test("off the chat routes there is no chat agent", () => {
  assert.equal(chatAgentFor("/", "nova"), null);
  assert.equal(chatAgentFor("/agents", "nova"), null);
  assert.equal(chatAgentFor("/agent", "nova"), null);
  assert.equal(chatAgentFor("/looks/nova", "nova"), null);
});

test("the agent's name fills every {name}", () => {
  assert.equal(withAgentName("Chat with {name}", "Nova"), "Chat with Nova");
  assert.equal(withAgentName("{name} and {name}", "Rae"), "Rae and Rae");
  assert.equal(withAgentName("no slot", "Rae"), "no slot");
});

test("Cael's empty chat says he is the guide; any other agent's says it is yours", () => {
  const strings = { own: "own", guide: "guide" };
  assert.equal(emptyChatLine("cael", strings), "guide");
  assert.equal(emptyChatLine("nova", strings), "own");
  assert.equal(emptyChatLine("main", strings), "own");
});

test("the browser tab names the agent first", () => {
  assert.equal(chatDocumentTitle("Nova", "Chat", "Caelza"), "Nova · Chat — Caelza");
});

// The strings the chat shows: none names the product where the agent's name belongs.
test("the chat's strings put the agent's name where 'Caelza Agent' used to be", () => {
  const i18n = readFileSync(new URL("./i18n.ts", import.meta.url), "utf8");
  const en = i18n.slice(i18n.indexOf("\n  en: {"), i18n.indexOf("\n  tr: {"));
  assert.doesNotMatch(en, /'agentchat\.empty_title': "Caelza Agent"/);
  for (const key of ["agentchat.empty_title", "agentchat.empty_own", "agentchat.empty_guide", "agentchat.header_title"]) {
    assert.match(en, new RegExp(`'${key.replace(".", "\\.")}': "[^"]*"`), key);
  }
  assert.match(en, /'agentchat\.empty_title': "[^"]*\{name\}[^"]*"/);
  assert.match(en, /'agentchat\.header_title': "[^"]*\{name\}[^"]*"/);
});
