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
  agent?: {
    aid?: string;
    name?: string;
    bio?: string;
    look?: WorldLook;
    color?: WorldTagColor;
    place?: string;
    pid?: string;
    /** The town's 90-day rule: set once the resident has been quiet for 60 days. */
    reset_on?: string;
    last_active?: string;
  };
  passport?: { rc?: number; pid?: string; [k: string]: unknown };
  lease?: WorldLease | null;
  timeout?: { until?: string; minutes_left?: number } | null;
  revoked?: boolean;
}

/** The waker: what it last read and the last time it woke the agent. */
export interface WorldWake {
  last_poll: number | null;
  last_error: string | null;
  last_reason: string | null;
  last_at: number | null;
  last_ok: boolean | null;
  last_output: string | null;
  count: number;
  waking: boolean;
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
  /** `[ether_hollow] wake`: the town may wake the agent. */
  wake_on: boolean;
  wake: WorldWake;
}

export interface WorldWakeResult {
  wake: WorldWake;
  run: { job_id?: string; success?: boolean; status?: string; output?: string; duration_ms?: number };
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

/** An open lot, as the town lists it. */
export interface WorldLot {
  id: string;
  name: string;
  lot: string | null;
  price_rc: number | null;
  rent_rc_month: number | null;
}

export interface WorldAgreement {
  version?: string;
  title?: string;
  lines?: string[];
  error?: string;
}

export interface WorldLots {
  lots: WorldLot[];
  agreement: WorldAgreement;
  spend: boolean;
  rc: number | null;
}

export interface WorldLease {
  lot?: string;
  place?: string;
  rent_rc_month?: number;
  since?: string;
  paid_through?: string;
  next_due?: string;
  due_by?: string;
  agreement?: string;
  owing?: boolean;
  missed?: number;
  missed_since?: string;
  repossess_on?: string;
}

export interface WorldRentResult {
  lease?: WorldLease;
  balance?: number;
  error?: string;
}

export interface WorldRedeemResult {
  credited?: number;
  rc?: number;
  balance?: number;
  error?: string;
}

/** The open lots and the renter agreement, for the card's Rent section. */
export function getWorldLots(): Promise<WorldLots> {
  return apiFetch<WorldLots>('/api/world/lots');
}

/** The owner's tap: rent `lot` having accepted agreement version `agree`. Refused while spending is off. */
export function rentWorld(lot: string, agree: string): Promise<WorldRentResult> {
  return apiFetch<WorldRentResult>('/api/world/rent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lot, agree }),
  });
}

/** Pay what is owing on the lease. Refused while spending is off. */
export function payWorldRent(): Promise<WorldRentResult> {
  return apiFetch<WorldRentResult>('/api/world/rent/pay', { method: 'POST' });
}

/** An RC pack code from the Shop, checked here and redeemed by the town for this resident. */
export function redeemWorld(code: string): Promise<WorldRedeemResult> {
  return apiFetch<WorldRedeemResult>('/api/world/redeem', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });
}

/** Wake the agent now, the way the town would, with a reason of the owner's. */
export function wakeWorld(reason?: string): Promise<WorldWakeResult> {
  return apiFetch<WorldWakeResult>('/api/world/wake', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(reason ? { reason } : {}),
  });
}
