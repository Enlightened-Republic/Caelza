// Ether Hollow as the dashboard sees it: `/api/world`, served by the gateway
// (api_world.rs) so the resident key never reaches the browser. The town's
// own API is the `ether_hollow` tool's; the page only registers, sends the
// agent to town for a while, brings it back, and reads the passport.
import { apiFetch } from './api';

/** The town's sprite: swatch indexes (cap and backpack 0-9, skin and pants 0-7). */
export interface WorldLook {
  cap?: number;
  backpack?: number;
  skin?: number;
  pants?: number;
}

/** The color of the name tag over the resident's head. */
export type WorldTagColor = 'cyan' | 'gold' | 'magenta' | 'lime' | 'orange' | 'violet';

export interface WorldPresence {
  in_town: boolean;
  since: number | null;
  until: number | null;
  beats: number;
  last_ok: number | null;
  last_error: string | null;
}

/** The town's `me`, scrubbed of anything key-shaped by the gateway. */
export interface WorldMe {
  agent?: { aid?: string; name?: string; bio?: string; look?: WorldLook; color?: WorldTagColor; place?: string; pid?: string };
  passport?: { rc?: number; pid?: string; [k: string]: unknown };
  lease?: { lot?: string; place?: string; rent_rc_month?: number; next_due?: string; owing?: boolean } | null;
  timeout?: { until?: string; minutes_left?: number } | null;
  revoked?: boolean;
}

export interface WorldState {
  enabled: boolean;
  url: string;
  name: string;
  agent: string;
  spend: boolean;
  registered: boolean;
  /** null when the town could not be asked. */
  open: boolean | null;
  presence: WorldPresence;
  me: WorldMe | null;
  me_error: string | null;
}

export interface WorldRegisterBody {
  name: string;
  bio?: string;
  look?: WorldLook;
  color?: WorldTagColor;
  replace?: boolean;
}

export interface WorldRegisterResult {
  registered: boolean;
  saved: boolean;
  name: string;
  agent: WorldMe['agent'] | null;
  where: unknown;
  note: string | null;
  restart_needed: boolean;
  /** Only when the config write failed: the town shows a key once. */
  key?: string;
  error?: string;
}

export interface WorldEnterResult {
  presence: WorldPresence;
  minutes: number;
}

export interface WorldLeaveResult {
  presence: WorldPresence;
  was_in_town: boolean;
  told_town: boolean;
}

export function getWorld(): Promise<WorldState> {
  return apiFetch<WorldState>('/api/world');
}

export function registerWorld(body: WorldRegisterBody): Promise<WorldRegisterResult> {
  return apiFetch<WorldRegisterResult>('/api/world/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function enterWorld(minutes: number): Promise<WorldEnterResult> {
  return apiFetch<WorldEnterResult>('/api/world/enter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ minutes }),
  });
}

export function leaveWorld(): Promise<WorldLeaveResult> {
  return apiFetch<WorldLeaveResult>('/api/world/leave', { method: 'POST' });
}
