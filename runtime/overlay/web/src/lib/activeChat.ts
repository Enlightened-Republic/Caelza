// Which agent the chat is showing right now. The chat workspace keeps several
// agents open as tabs and mirrors the active one to the address bar with
// history.replaceState (a router navigation would remount every chat), so the
// router's location can name an agent the owner already switched away from.
// The workspace reports the active tab here; the top bar and the browser tab
// title read it, so they always name the agent the owner is talking to.
import { useSyncExternalStore } from "react";

let current: string | null = null;
const listeners = new Set<() => void>();

/** The workspace: this agent's chat is in front now (null when the chat closes). */
export function setActiveChatAgent(alias: string | null): void {
  if (alias === current) return;
  current = alias;
  for (const l of listeners) l();
}

export function activeChatAgent(): string | null {
  return current;
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

/** The agent in front of the chat, or null when no chat is open. */
export function useActiveChatAgent(): string | null {
  return useSyncExternalStore(subscribe, activeChatAgent, activeChatAgent);
}
