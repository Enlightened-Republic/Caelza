// "Explain this screen" (vision §3.4, the Guide everywhere) with nothing
// React in it: which screen a route is, the strings that explain it, the
// one guide conversation the dashboard keeps with Cael, the message sent
// for a question and how his streamed reply folds. `node
// --experimental-strip-types --test guide.logic.test.ts` runs the tests,
// so this file stays plain TypeScript with no path aliases.

export type Screen =
  | "home"
  | "bodies"
  | "memory"
  | "procedures"
  | "agents"
  | "agent"
  | "looks"
  | "shop"
  | "connect"
  | "setup"
  | "quickstart"
  | "config"
  | "tools"
  | "skills"
  | "sops"
  | "runs"
  | "integrations"
  | "plugins"
  | "cron"
  | "dashboard"
  | "logs"
  | "pairing"
  | "doctor"
  | "canvas"
  | "acp"
  | "other";

const BY_SEGMENT: Record<string, Screen> = {
  bodies: "bodies",
  memory: "memory",
  procedures: "procedures",
  agents: "agents",
  agent: "agent",
  looks: "looks",
  shop: "shop",
  connect: "connect",
  setup: "setup",
  quickstart: "quickstart",
  config: "config",
  tools: "tools",
  skills: "skills",
  sops: "sops",
  runs: "runs",
  integrations: "integrations",
  plugins: "plugins",
  cron: "cron",
  dashboard: "dashboard",
  logs: "logs",
  pairing: "pairing",
  doctor: "doctor",
  canvas: "canvas",
  "acp-console": "acp",
};

/** The screen a route shows: `/` is Home, `/setup/<section>` is the Config explorer, `/agent/<alias>` the chat. */
export function screenOf(pathname: string): Screen {
  const segments = pathname.split("/").filter(Boolean);
  const first = segments[0];
  if (!first) return "home";
  if (first === "setup" && segments.length > 1) return "config";
  return BY_SEGMENT[first.toLowerCase()] ?? "other";
}

/** The string keys for a screen: what it is, and the next step. */
export function screenKeys(screen: Screen): { text: string; next: string } {
  return { text: `guide.screen_${screen}`, next: `guide.next_${screen}` };
}

/** Where the next step goes; null when it stays on this screen. */
export function nextRoute(screen: Screen): string | null {
  const routes: Partial<Record<Screen, string>> = {
    home: "/agents",
    bodies: "/procedures",
    memory: "/agents",
    procedures: "/sops",
    agents: "/looks",
    agent: "/looks",
    looks: "/shop",
    shop: "/looks",
    connect: "/agents",
    setup: "/quickstart",
    quickstart: "/setup",
    config: "/setup",
    tools: "/config",
    skills: "/agents",
    sops: "/procedures",
    runs: "/procedures",
    integrations: "/config",
    plugins: "/skills",
    cron: "/procedures",
    dashboard: "/",
    logs: "/doctor",
    pairing: "/",
    doctor: "/logs",
    canvas: "/agents",
    acp: "/agents",
    other: "/",
  };
  return routes[screen] ?? null;
}

/** The one guide conversation the dashboard keeps with Cael (resumed on every question). */
export const GUIDE_SESSION_STORAGE = "caelza_guide_session";

export function guideSessionId(storage: { getItem(k: string): string | null; setItem(k: string, v: string): void } | null): string {
  const known = storage?.getItem(GUIDE_SESSION_STORAGE);
  if (known) return known;
  const id = `guide-${Math.random().toString(16).slice(2, 10)}${Date.now().toString(16)}`;
  storage?.setItem(GUIDE_SESSION_STORAGE, id);
  return id;
}

/** The message a question becomes: where the owner is, then what they asked. */
export function question(screenTitle: string, pathname: string, text: string): string {
  return `[The owner is looking at the "${screenTitle}" screen of the Caelza dashboard (${pathname}). Answer for that screen, briefly, in your own voice.]\n${text.trim()}`;
}

/** Cael answers only when he is one of the configured agents. */
export function caelReady(agents: ReadonlyArray<string>): boolean {
  return agents.includes("cael");
}

export interface Reply {
  text: string;
  done: boolean;
  error: string | null;
}

export const EMPTY_REPLY: Reply = { text: "", done: false, error: null };

interface WsLike {
  type: string;
  content?: string;
  full_response?: string;
  message?: string;
}

/** How the gateway's stream folds into one reply: chunks append, a reset clears, done is final, an error ends it. */
export function foldReply(reply: Reply, msg: WsLike): Reply {
  switch (msg.type) {
    case "chunk":
      return { ...reply, text: reply.text + (msg.content ?? "") };
    case "chunk_reset":
      return { ...reply, text: "" };
    case "done":
      return { text: (msg.full_response ?? msg.content ?? reply.text).trim(), done: true, error: null };
    case "error":
      return { ...reply, done: true, error: msg.message ?? msg.content ?? "something went wrong" };
    case "aborted":
      return { ...reply, done: true, error: reply.text ? null : "the answer was stopped" };
    default:
      return reply;
  }
}

/** A question is a line of text; blank or absurdly long ones are not sent. */
export function questionOk(text: string): boolean {
  const t = text.trim();
  return t.length > 0 && t.length <= 2000;
}
