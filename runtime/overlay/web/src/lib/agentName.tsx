// One place the dashboard asks what an agent is called: a small cache over the
// identity file, a hook for pages, and a text component for lists.
import { useEffect, useState } from "react";

import { fetchAgentName } from "./identity";
import { displayName } from "./identity.logic";

const names = new Map<string, string>();
const pending = new Map<string, Promise<string>>();
const listeners = new Set<() => void>();

// When Cael, the guide, replies, a name may have just changed (he gives the
// owner's agent its name when they meet): ask the files again. Only on a real
// window: a node test renders the chat with a stub that has no listeners.
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("caelza-agent-reply", (e: Event) => {
    const detail = (e as CustomEvent<{ alias?: string }>).detail;
    if (detail?.alias !== "cael") return;
    names.clear();
    pending.clear();
    notify();
  });
}

function notify(): void {
  for (const l of listeners) l();
}

/** After a rename: every page shows the new name at once. */
export function rememberAgentName(alias: string, name: string): void {
  names.set(alias, name);
  pending.delete(alias);
  notify();
}

export function forgetAgentName(alias: string): void {
  names.delete(alias);
  pending.delete(alias);
  notify();
}

export function loadAgentName(alias: string): Promise<string> {
  const known = names.get(alias);
  if (known !== undefined) return Promise.resolve(known);
  const inFlight = pending.get(alias);
  if (inFlight) return inFlight;
  const p = fetchAgentName(alias).then((name) => {
    names.set(alias, name);
    pending.delete(alias);
    notify();
    return name;
  });
  pending.set(alias, p);
  return p;
}

/** The agent's name, the alias until the file has answered; "" for no agent (""). */
export function useAgentName(alias: string): string {
  const [, tick] = useState(0);
  useEffect(() => {
    const l = () => tick((n) => n + 1);
    listeners.add(l);
    if (alias && !names.has(alias)) void loadAgentName(alias);
    return () => {
      listeners.delete(l);
    };
  }, [alias]);
  if (!alias) return "";
  return names.get(alias) ?? displayName(null, alias);
}

/** For lists, where a hook cannot go in the map. */
export function AgentNameText({ alias }: { alias: string }) {
  return <>{useAgentName(alias)}</>;
}
