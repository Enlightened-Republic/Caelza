import assert from "node:assert/strict";
import test from "node:test";

import {
  HOME_ASSISTANT,
  MATON,
  OCTOPRINT_SECRET,
  PRINTER_KINDS,
  PRINTER_SKILL,
  agentFor,
  bearer,
  homeAssistantAddress,
  homeAssistantUrl,
  printerHost,
  printerOps,
  secretOk,
  serverConnected,
  serverOps,
  serverUrl,
  stringArray,
  withBundle,
  withHost,
} from "./connect.logic.ts";

test("the agent is main when there is one, else the first, else main anyway", () => {
  assert.equal(agentFor(["cael", "main"]), "main");
  assert.equal(agentFor(["helper", "cael"]), "helper");
  assert.equal(agentFor([]), "main");
});

test("a key becomes one Bearer header however it was pasted, and a mispaste is caught", () => {
  assert.equal(bearer("sk-maton-abcdef"), "Bearer sk-maton-abcdef");
  assert.equal(bearer("  Bearer sk-maton-abcdef "), "Bearer sk-maton-abcdef");
  assert.equal(bearer("bearer   tok"), "Bearer tok");
  assert.ok(secretOk("sk-maton-abcdef"));
  assert.ok(secretOk("Bearer eyJhbGciOiJIUzI1NiJ9.x.y"));
  assert.ok(!secretOk("short"));
  assert.ok(!secretOk("two words here"));
  assert.ok(!secretOk("   "));
});

test("Home Assistant's address becomes its MCP endpoint, the port and scheme filled in", () => {
  assert.equal(homeAssistantUrl("http://homeassistant.local:8123"), "http://homeassistant.local:8123/api/mcp/assist");
  assert.equal(homeAssistantUrl("http://homeassistant.local:8123/"), "http://homeassistant.local:8123/api/mcp/assist");
  assert.equal(homeAssistantUrl("homeassistant.local"), "http://homeassistant.local:8123/api/mcp/assist");
  assert.equal(homeAssistantUrl("192.168.1.5"), "http://192.168.1.5:8123/api/mcp/assist");
  assert.equal(homeAssistantUrl("https://ha.example.com"), "https://ha.example.com/api/mcp/assist");
  assert.equal(homeAssistantUrl("https://ha.example.com/ha/"), "https://ha.example.com/ha/api/mcp/assist");
  assert.equal(homeAssistantUrl(HOME_ASSISTANT.defaultAddress), "http://homeassistant.local:8123/api/mcp/assist");
  for (const bad of ["", "   ", "not an address", "ftp://x", "http://user:pw@host", "http://"]) assert.equal(homeAssistantUrl(bad), null, bad);
  assert.equal(homeAssistantAddress("http://homeassistant.local:8123/api/mcp/assist"), "http://homeassistant.local:8123");
  assert.equal(homeAssistantAddress("http://x"), "http://x");
});

test("the printer's address is reduced to the one host the allowlist takes", () => {
  assert.equal(printerHost("192.168.1.40"), "192.168.1.40");
  assert.equal(printerHost(" http://voron.local:7125/ "), "voron.local");
  assert.equal(printerHost("Voron.Local:80"), "voron.local");
  assert.equal(printerHost("octopi.local/api/job"), "octopi.local");
  for (const bad of ["", "no host!", "a b", "http://", "http://user:pw@host"]) assert.equal(printerHost(bad), null, bad);
  assert.deepEqual(withHost([], "192.168.1.40"), ["192.168.1.40"]);
  assert.deepEqual(withHost(["192.168.1.40"], "192.168.1.40"), ["192.168.1.40"]);
  assert.deepEqual(withHost(["a"], "b"), ["a", "b"]);
});

test("the server patch fills the row, bundles it, and grants the bundle without dropping the agent's others", () => {
  const ops = serverOps(MATON.name, MATON.url, MATON.timeout, bearer("sk-maton-abcdef"), "main", ["mind", "body"]);
  assert.deepEqual(ops, [
    { op: "add", path: "/mcp/servers/maton/url", value: "https://mcp.maton.ai" },
    { op: "add", path: "/mcp/servers/maton/transport", value: "http" },
    { op: "add", path: "/mcp/servers/maton/tool_timeout_secs", value: 60 },
    { op: "add", path: "/mcp/servers/maton/headers/Authorization", value: "Bearer sk-maton-abcdef" },
    { op: "add", path: "/mcp_bundles/maton/servers", value: ["maton"] },
    { op: "add", path: "/agents/main/mcp_bundles", value: ["mind", "body", "maton"] },
  ]);
  // Connecting twice does not list the bundle twice.
  assert.deepEqual(withBundle(["maton"], "maton"), ["maton"]);
  assert.deepEqual(withBundle([], "homeassistant"), ["homeassistant"]);
  const ha = serverOps(HOME_ASSISTANT.name, homeAssistantUrl("homeassistant.local")!, HOME_ASSISTANT.timeout, bearer("tok-abcdefgh"), "cael", []);
  assert.equal(ha[0]!.value, "http://homeassistant.local:8123/api/mcp/assist");
  assert.equal(ha[2]!.value, 30);
  assert.deepEqual(ha[5], { op: "add", path: "/agents/cael/mcp_bundles", value: ["homeassistant"] });
});

test("the printer patch allows its one address and keeps the OctoPrint key as the skill's secret", () => {
  assert.deepEqual(printerOps("192.168.1.40", "moonraker", "", []), [
    { op: "add", path: "/http_request/allowed_private_hosts", value: ["192.168.1.40"] },
  ]);
  assert.deepEqual(printerOps("octopi.local", "octoprint", "ABCDEF0123456789", ["192.168.1.40"]), [
    { op: "add", path: "/http_request/allowed_private_hosts", value: ["192.168.1.40", "octopi.local"] },
    { op: "add", path: `/http_request/secrets/${OCTOPRINT_SECRET}`, value: "Bearer ABCDEF0123456789" },
  ]);
  assert.equal(PRINTER_SKILL, "3d-printer");
  assert.deepEqual([...PRINTER_KINDS], ["moonraker", "octoprint"]);
});

test("what the config list says: connected means a url and a populated header; arrays come as arrays or text", () => {
  const entries = [
    { path: "mcp.servers.maton.url", value: "https://mcp.maton.ai", populated: true },
    { path: "mcp.servers.maton.headers.Authorization", value: null, populated: true },
    { path: "mcp.servers.homeassistant.url", value: "<unset>", populated: false },
    { path: "mcp.servers.homeassistant.headers.Authorization", value: null, populated: false },
  ];
  assert.ok(serverConnected(entries, "maton"));
  assert.ok(!serverConnected(entries, "homeassistant"));
  assert.ok(!serverConnected([], "maton"));
  assert.ok(!serverConnected([{ path: "mcp.servers.maton.url", value: "https://mcp.maton.ai" }], "maton"), "a url with no key is not connected");
  assert.equal(serverUrl(entries, "maton"), "https://mcp.maton.ai");
  assert.equal(serverUrl(entries, "homeassistant"), null);
  assert.deepEqual(stringArray(["mind", "body"]), ["mind", "body"]);
  assert.deepEqual(stringArray('["mind", "body"]'), ["mind", "body"]);
  assert.deepEqual(stringArray("<unset>"), []);
  assert.deepEqual(stringArray(undefined), []);
  assert.deepEqual(stringArray("[not json"), []);
  assert.deepEqual(stringArray([1, "x", null]), ["x"]);
});
