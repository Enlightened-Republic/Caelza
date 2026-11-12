// One Mind for every device: the pure part of the Memory page's devices
// cards. The gateway does the probing, the config.json and tokens.json
// writes; this file decides what the page shows and what the joining
// device writes through the config API.
import type { PatchOp } from '@/lib/api';
import type { MindShareCandidate, MindStatus } from '@/lib/mind';

/** Where the joining device's config points: `[storage.xanima.default]`. */
export const STORAGE_PATH = 'storage.xanima';
export const STORAGE_KEY = 'default';
/** The service's default loopback URL. */
export const LOCAL_MIND_URL = 'http://127.0.0.1:18790';
/** The memory backend the Runtime falls back to when no Mind is in reach. */
export const FALLBACK_BACKEND = 'sqlite';

const PREFIX = `/storage/xanima/${STORAGE_KEY}`;

/** The host part of a service URL (IPv6 without its brackets). */
export function hostOf(url: string): string {
  const rest = url.trim().replace(/^https?:\/\//i, '').split('/')[0] ?? '';
  if (rest.startsWith('[')) {
    const end = rest.indexOf(']');
    return end > 0 ? rest.slice(1, end) : rest;
  }
  const colon = rest.lastIndexOf(':');
  return colon > 0 ? rest.slice(0, colon) : rest;
}

/**
 * Whether the service URL is the service's own listener on this machine
 * (127.0.0.1, localhost or ::1, the one address it always binds). Any other
 * address, another loopback one included, is a shared address.
 */
export function isLoopbackUrl(url: string | undefined | null): boolean {
  if (!url) return false;
  const host = hostOf(url).toLowerCase();
  return host === 'localhost' || host === '127.0.0.1' || host === '::1';
}

/** Which devices card the page shows for this device. */
export type DevicesRole =
  /** The Mind runs here: offer to share it. */
  | 'host'
  /** This device already uses another device's Mind. */
  | 'joined'
  /** No Mind here: offer to join one. */
  | 'alone';

export function devicesRole(status: Pick<MindStatus, 'enabled' | 'url'>): DevicesRole {
  if (!status.enabled) return 'alone';
  return isLoopbackUrl(status.url) ? 'host' : 'joined';
}

/** The label for a shareable address: what network it is on. */
export function candidateLabel(c: MindShareCandidate): string {
  return c.kind === 'tailnet' ? `Tailscale · ${c.host}` : `Home network · ${c.host}`;
}

/** The best address to offer first: Tailscale when it is there, else the home network. */
export function preferredCandidate(list: readonly MindShareCandidate[] | undefined): MindShareCandidate | null {
  if (!list || list.length === 0) return null;
  return list.find((c) => c.kind === 'tailnet') ?? list[0] ?? null;
}

/** `host:port` with IPv6 in brackets (the URL form). */
export function listenerOf(host: string, port: number): string {
  return host.includes(':') ? `[${host}]:${port}` : `${host}:${port}`;
}

/**
 * One of the service's listener entries taken apart: `127.0.0.1:18790`,
 * `[fd12::1]:18790`, or the raw `fd12::1:18790` it prints for IPv6.
 */
export function parseListener(entry: string): { host: string; port: number } | null {
  const s = entry.trim();
  const colon = s.lastIndexOf(':');
  if (colon <= 0) return null;
  const port = Number(s.slice(colon + 1));
  if (!Number.isInteger(port) || port <= 0) return null;
  const host = s.slice(0, colon).replace(/^\[|\]$/g, '').toLowerCase();
  return host ? { host, port } : null;
}

/** Whether the service already listens on `host` (so no restart is needed). */
export function isListening(listening: readonly string[] | undefined, host: string, port: number): boolean {
  const want = host.replace(/^\[|\]$/g, '').toLowerCase();
  return (listening ?? []).some((entry) => {
    const got = parseListener(entry);
    return got !== null && got.host === want && got.port === port;
  });
}

/**
 * The config writes that make this device use the Mind at `url` with `token`:
 * the row's fields, then the backend. The row (`storage.xanima.default`) is
 * created first through the map-key endpoint; these ops fill it. `add` on an
 * existing field is a replace for the config API.
 */
export function joinOps(url: string, token: string, agent = 'main'): PatchOp[] {
  return [
    { op: 'add', path: `${PREFIX}/url`, value: url.replace(/\/+$/, '') },
    { op: 'add', path: `${PREFIX}/token`, value: token },
    { op: 'add', path: `${PREFIX}/agent`, value: agent },
    // Never provision from a joined device; the service refuses it off loopback anyway.
    { op: 'add', path: `${PREFIX}/provision_token_file`, value: '' },
    { op: 'add', path: '/memory/backend', value: 'xanima' },
  ];
}

/**
 * Leaving deletes the `storage.xanima.default` row (the map-key endpoint,
 * so the shared token is gone from the config, not blanked) and then writes
 * the backend: this device's own Mind when one answers on loopback
 * (`localMindUp`, the row's defaults point there), else the Runtime's own
 * sqlite store.
 */
export function leaveBackendOps(localMindUp: boolean): PatchOp[] {
  return [{ op: 'add', path: '/memory/backend', value: localMindUp ? 'xanima' : FALLBACK_BACKEND }];
}

/** A join code with the spaces and line breaks a messenger adds taken out. */
export function cleanCode(raw: string): string {
  return raw.replace(/\s+/g, '');
}

/** What the restart note says for the role that needs it. */
export function restartNote(role: 'host' | 'joined'): string {
  return role === 'host'
    ? 'Restart the Mind once so it listens there: on Windows close the Caelza Mind window and open Caelza from the Start menu again; on a hub run caelza-mind serve again. If Windows asks whether Node.js may use your private network, say yes.'
    : 'This page already shows it. For the agent to use it on its next turn, tap Reload daemon in the yellow bar at the top of the dashboard, or restart Caelza once (on the phone tap Stop, then Start; on a PC close Caelza and open it from the Start menu again).';
}
