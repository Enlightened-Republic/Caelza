// The chat's own words about who is in it, with nothing React in it.
// `node --experimental-strip-types --test src/lib/activeChat.logic.test.ts`.

/**
 * The agent a route is about: the chat tab in front when the workspace has
 * said, else the alias in `/agent/<alias>`; the agent's file workspace
 * (`/agent/<alias>/workspace`) is about that agent whatever tab is in front.
 * Null off the chat routes.
 */
export function chatAgentFor(pathname: string, active: string | null): string | null {
  const seg = pathname.split("/").filter(Boolean);
  if (seg[0] !== "agent" || !seg[1]) return null;
  if (seg.length > 2) return safeDecode(seg[1]);
  return active ?? safeDecode(seg[1]);
}

function safeDecode(s: string): string {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

/**
 * Fill a string's `{name}` with the agent's name. Every place the chat says
 * who the owner is talking to goes through this, so no screen falls back to
 * the product's name ("Caelza Agent") where the agent's own belongs.
 */
export function withAgentName(template: string, name: string): string {
  return template.split("{name}").join(name);
}

/**
 * The line under the empty chat: whose chat this is. Cael's own chat says he
 * is the guide; any other agent's says it is the owner's own agent and where
 * the guide is, so the two are never mistaken for each other.
 */
export function emptyChatLine(alias: string, strings: { own: string; guide: string }): string {
  return alias === "cael" ? strings.guide : strings.own;
}

/** The browser tab's title on a chat route: the agent's name first. */
export function chatDocumentTitle(name: string, chatWord: string, product: string): string {
  return `${name} · ${chatWord} — ${product}`;
}
