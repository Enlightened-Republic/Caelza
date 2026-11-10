// The Connect page (vision §3.4, the Guide everywhere): your apps through
// Maton, your home through Home Assistant, a 3D printer on your Wi-Fi, each
// from one box or two, with nothing React in it. What the page writes is the
// config the connect scripts write (scripts/maton-connect.sh,
// scripts/home-connect.sh, runtime/caelza.printer.example.toml), through the
// gateway's config API: the `[[mcp.servers]]` row is made by name
// (`POST /api/config/map-key?path=mcp.servers&key=<name>`; it is a keyed
// list, which no property path can create), then one atomic
// `PATCH /api/config` fills it, bundles it and grants the bundle to the
// agent, keeping the agent's other bundles; a printer allows its one
// address, keeps the OctoPrint key as a secret, and gets the bundled skill
// through /api/connect/skills. `node --experimental-strip-types --test
// connect.logic.test.ts` runs the tests, so this file stays plain
// TypeScript with no path aliases.

export interface PatchOp {
  op: "add" | "replace" | "remove" | "test" | "comment";
  path: string;
  value?: unknown;
  comment?: string;
}

/** The shape `GET /api/config/list?prefix=…` answers with, as much of it as the page reads. */
export interface ListedProp {
  path: string;
  value?: unknown;
  populated?: boolean;
}

export const MATON = {
  name: "maton",
  url: "https://mcp.maton.ai",
  timeout: 60,
  site: "https://maton.ai",
} as const;

export const HOME_ASSISTANT = {
  name: "homeassistant",
  defaultAddress: "http://homeassistant.local:8123",
  defaultPort: 8123,
  path: "/api/mcp/assist",
  timeout: 30,
} as const;

export const PRINTER_SKILL = "3d-printer";
export const OCTOPRINT_SECRET = "octoprint";
export type PrinterKind = "moonraker" | "octoprint";
export const PRINTER_KINDS: readonly PrinterKind[] = ["moonraker", "octoprint"];

/** The agent the page connects things for: `main` when it exists, else the first one, else `main` anyway. */
export function agentFor(agents: readonly string[]): string {
  if (agents.includes("main")) return "main";
  return agents[0] ?? "main";
}

/** A key or token as the header wants it: `Bearer <key>`, once, whatever was pasted. */
export function bearer(secret: string): string {
  const s = secret.trim().replace(/^bearer\s+/i, "");
  return `Bearer ${s}`;
}

/** A pasted key is one long word; whitespace inside it or a short paste is a mispaste. */
export function secretOk(secret: string): boolean {
  const s = secret.trim().replace(/^bearer\s+/i, "");
  return s.length >= 8 && !/\s/.test(s);
}

function parseAddress(address: string): URL | null {
  const raw = address.trim();
  if (raw === "" || /\s/.test(raw)) return null;
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : `http://${raw}`;
  let url: URL;
  try {
    url = new URL(withScheme);
  } catch {
    return null;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;
  if (url.hostname === "" || url.username !== "" || url.password !== "") return null;
  return url;
}

/** Home Assistant's address as its MCP endpoint: `http://` and the 8123 port
 * added when missing, trailing slashes dropped, the path appended. Null when
 * it is not an address. */
export function homeAssistantUrl(address: string): string | null {
  const url = parseAddress(address);
  if (!url) return null;
  if (url.port === "" && url.protocol === "http:") url.port = String(HOME_ASSISTANT.defaultPort);
  const base = `${url.protocol}//${url.host}${url.pathname.replace(/\/+$/, "")}`;
  return `${base}${HOME_ASSISTANT.path}`;
}

/** The printer's host as the Runtime's allowlist takes it (no scheme, port or
 * path): an IP or a name like `voron.local`. Null when it is not one. */
export function printerHost(address: string): string | null {
  const url = parseAddress(address);
  if (!url) return null;
  const host = url.hostname.toLowerCase();
  return /^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$/.test(host) ? host : null;
}

/** The agent's bundle list with one more in it, once. */
export function withBundle(current: readonly string[], name: string): string[] {
  return current.includes(name) ? [...current] : [...current, name];
}

/** One address more on the allowlist, once. */
export function withHost(current: readonly string[], host: string): string[] {
  return current.includes(host) ? [...current] : [...current, host];
}

/** The one atomic patch that fills a `[[mcp.servers]]` row (created by name
 * beforehand), bundles it under its own name, and grants the bundle to the
 * agent, keeping the agent's other bundles. */
export function serverOps(
  name: string,
  url: string,
  timeoutSecs: number,
  authorization: string,
  agent: string,
  currentBundles: readonly string[],
): PatchOp[] {
  return [
    { op: "add", path: `/mcp/servers/${name}/url`, value: url },
    { op: "add", path: `/mcp/servers/${name}/transport`, value: "http" },
    { op: "add", path: `/mcp/servers/${name}/tool_timeout_secs`, value: timeoutSecs },
    { op: "add", path: `/mcp/servers/${name}/headers/Authorization`, value: authorization },
    { op: "add", path: `/mcp_bundles/${name}/servers`, value: [name] },
    { op: "add", path: `/agents/${agent}/mcp_bundles`, value: withBundle(currentBundles, name) },
  ];
}

/** The printer's config: its one address allowed (the Runtime blocks private
 * addresses otherwise), and for OctoPrint its key kept as the secret the skill
 * names. The skill itself goes on disk through /api/connect/skills. */
export function printerOps(host: string, kind: PrinterKind, secret: string, currentHosts: readonly string[]): PatchOp[] {
  const ops: PatchOp[] = [{ op: "add", path: "/http_request/allowed_private_hosts", value: withHost(currentHosts, host) }];
  if (kind === "octoprint") ops.push({ op: "add", path: `/http_request/secrets/${OCTOPRINT_SECRET}`, value: bearer(secret) });
  return ops;
}

/** A listed value as strings: the list API hands arrays back as arrays or as
 * their JSON text, and an unset one as `<unset>`. */
export function stringArray(value: unknown): string[] {
  let v = value;
  if (typeof v === "string") {
    const s = v.trim();
    if (!s.startsWith("[")) return [];
    try {
      v = JSON.parse(s) as unknown;
    } catch {
      return [];
    }
  }
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

export function listed(entries: ReadonlyArray<ListedProp>, path: string): ListedProp | undefined {
  return entries.find((e) => e.path === path);
}

/** A server is connected when its row has a url and its Authorization header
 * is populated (the list never shows a secret's value, only that it is set). */
export function serverConnected(entries: ReadonlyArray<ListedProp>, name: string): boolean {
  const url = listed(entries, `mcp.servers.${name}.url`);
  const auth = listed(entries, `mcp.servers.${name}.headers.Authorization`);
  const hasUrl = typeof url?.value === "string" && url.value !== "" && url.value !== "<unset>";
  return hasUrl && auth?.populated === true;
}

/** The server's url as listed, for the page to show which address it is on. */
export function serverUrl(entries: ReadonlyArray<ListedProp>, name: string): string | null {
  const url = listed(entries, `mcp.servers.${name}.url`);
  return typeof url?.value === "string" && url.value !== "" && url.value !== "<unset>" ? url.value : null;
}

/** The address the Home Assistant box shows back: the endpoint's base, without the MCP path. */
export function homeAssistantAddress(mcpUrl: string): string {
  return mcpUrl.endsWith(HOME_ASSISTANT.path) ? mcpUrl.slice(0, -HOME_ASSISTANT.path.length) : mcpUrl;
}
