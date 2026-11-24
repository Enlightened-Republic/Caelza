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
  /** The day plan's slot this visit is, when the agent's own plan sent it (M10 slice 5b). */
  plan?: WorldPlanNow | null;
}

/** The slot running now: `end` is the device's local `HH:MM`. */
export interface WorldPlanNow {
  at: string;
  end: string;
  place: string;
  doing: string;
}

/** One stop of the agent's day, as it planned it. */
export interface WorldSlot {
  at: string;
  minutes: number;
  place: string;
  doing: string;
}

export interface WorldDayPlan {
  day: string;
  slots: WorldSlot[];
  set_at: number;
}

/**
 * The day plan as the gateway reports it: the owner's grid (`lines`, the
 * config's `hours`) and budget (`budget.visits_month`, planned visits a month),
 * what is used, today's and tomorrow's plan as the agent wrote them.
 */
export interface WorldPlan {
  now: string;
  today: string;
  hours_today: string;
  hours_tomorrow: string;
  hours: string[];
  lines: string[];
  hours_error: string | null;
  budget: { unit: string; month: string; visits_month: number; used: number; left: number };
  plan: WorldDayPlan | null;
  tomorrow: WorldDayPlan | null;
  /** The slots of today that already ran, `YYYY-MM-DD HH:MM`. */
  ran: string[];
  /** The planner runs: the town may wake the agent, it holds a key, and it has hours and a budget. */
  runs: boolean;
  planner: { last_tick: number | null; last_error: string | null; last_started: string | null; out_of_budget: boolean };
  /** The resident's own table, for the grid's writes. */
  path: string;
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

/** One of the agents that live in the town, or may (P6): the card lists them. */
export interface WorldResident {
  agent: string;
  name: string;
  registered: boolean;
  in_town: boolean;
  spend: boolean;
  /** Where its settings live, as a JSON pointer: `/ether_hollow` for the first, `/ether_hollow/residents/<alias>` for the others. */
  path: string;
}

export interface WorldState {
  enabled: boolean;
  url: string;
  name: string;
  agent: string;
  spend: boolean;
  /** The resident's own table, for the spending switch's write. */
  spend_path: string;
  registered: boolean;
  /** null when the town could not be asked. */
  open: boolean | null;
  presence: WorldPresence;
  me: WorldMe | null;
  me_error: string | null;
  /** `[ether_hollow] wake`: the town may wake the agent. */
  wake_on: boolean;
  wake: WorldWake;
  residents: WorldResident[];
  /** The day plan (M10 slice 5b); absent from an older gateway. */
  plan?: WorldPlan;
}

/** `?agent=<alias>`: which resident a call is about; none means the gateway's default. */
function q(agent?: string): string {
  return agent ? `?agent=${encodeURIComponent(agent)}` : '';
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

export function getWorld(agent?: string): Promise<WorldState> {
  return apiFetch<WorldState>('/api/world' + q(agent));
}

export function registerWorld(body: WorldRegisterBody, agent?: string): Promise<WorldRegisterResult> {
  return apiFetch<WorldRegisterResult>('/api/world/register' + q(agent), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function enterWorld(minutes: number, agent?: string): Promise<WorldEnterResult> {
  return apiFetch<WorldEnterResult>('/api/world/enter' + q(agent), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ minutes }),
  });
}

export function leaveWorld(agent?: string): Promise<WorldLeaveResult> {
  return apiFetch<WorldLeaveResult>('/api/world/leave' + q(agent), { method: 'POST' });
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
export function getWorldLots(agent?: string): Promise<WorldLots> {
  return apiFetch<WorldLots>('/api/world/lots' + q(agent));
}

/** The owner's tap: rent `lot` having accepted agreement version `agree`. Refused while spending is off. */
export function rentWorld(lot: string, agree: string, agent?: string): Promise<WorldRentResult> {
  return apiFetch<WorldRentResult>('/api/world/rent' + q(agent), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lot, agree }),
  });
}

/** Pay what is owing on the lease. Refused while spending is off. */
export function payWorldRent(agent?: string): Promise<WorldRentResult> {
  return apiFetch<WorldRentResult>('/api/world/rent/pay' + q(agent), { method: 'POST' });
}

/** An RC pack code from the Shop, checked here and redeemed by the town for this resident. */
export function redeemWorld(code: string, agent?: string): Promise<WorldRedeemResult> {
  return apiFetch<WorldRedeemResult>('/api/world/redeem' + q(agent), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });
}

/**
 * Home's glance at the town (`GET /api/world/home`): the settings without the
 * key, the presence, the last wake, and the passport the gateway last read
 * (`me_at` says when; the gateway asks the town again only past five minutes).
 */
export interface WorldHomeResident {
  agent: string;
  name: string;
  registered: boolean;
  spend: boolean;
  presence: WorldPresence;
  wake: WorldWake;
  me: WorldMe | null;
  me_at: number | null;
  me_error: string | null;
}

/** The default resident's glance at the top, and every resident's under `residents` (P6). */
export interface WorldHome extends WorldHomeResident {
  enabled: boolean;
  wake_on: boolean;
  residents: WorldHomeResident[];
}

export function getWorldHome(): Promise<WorldHome> {
  return apiFetch<WorldHome>('/api/world/home');
}

/** Wake the agent now, the way the town would, with a reason of the owner's. */
export function wakeWorld(reason?: string, agent?: string): Promise<WorldWakeResult> {
  return apiFetch<WorldWakeResult>('/api/world/wake' + q(agent), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(reason ? { reason } : {}),
  });
}
