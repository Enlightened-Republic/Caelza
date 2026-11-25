// The Ether Hollow card's pure part: what a resident's name may be, how the
// agent's pixel look becomes the town's four swatches and a name-tag color,
// the config write for the spending switch, and the words for a visit. The
// day plan (M10 slice 5b): the owner's weekly grid as the card edits it, the
// config writes for it and the budget, and the agent's plan as lines.
import type { Slot } from "@/looks/looks.logic";
import type { WorldLook, WorldPlanNow, WorldPresence, WorldSlot, WorldTagColor } from "@/lib/world";
import type { PatchOp } from "./connect.logic";

/** The town, as the Runtime's default names it. */
export const TOWN_URL = "https://etherhollow.enlightenedrepublic.online";
/** The town's rule for a resident's name (Register.name in its OpenAPI). */
export const NAME_RULE = /^[A-Za-z0-9 _-]{3,24}$/;
export const BIO_MAX = 140;
/** The visits the card offers, in minutes. */
export const VISITS = [15, 60, 240] as const;
export type Visit = (typeof VISITS)[number];
export const TAG_COLORS: readonly WorldTagColor[] = ["cyan", "gold", "magenta", "lime", "orange", "violet"];
/** Each tag color's hue, so the agent's accent picks the nearest. */
const TAG_HUES: Record<WorldTagColor, number> = { orange: 30, gold: 48, lime: 95, cyan: 185, violet: 270, magenta: 310 };

export function nameOk(name: string): boolean {
  return NAME_RULE.test(name.trim());
}

/** Plain words, no links: the town's rule for a bio. */
export function bioOk(bio: string): boolean {
  const b = bio.trim();
  if (b.length > BIO_MAX) return false;
  return !/https?:\/\/|www\.|[a-z0-9-]+\.(com|net|org|io|ai|app|online|tech)\b/i.test(b);
}

/** Hue (0-360), saturation and lightness (0-1) of a `#rrggbb`; null when it is not one. */
export function hsl(hex: string): { h: number; s: number; l: number } | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1]!, 16);
  const r = ((n >> 16) & 255) / 255;
  const g = ((n >> 8) & 255) / 255;
  const b = (n & 255) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return { h: 0, s: 0, l };
  const s = d / (1 - Math.abs(2 * l - 1));
  let h: number;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  h = Math.round(h * 60);
  if (h < 0) h += 360;
  return { h, s, l };
}

function bucket(hue: number, buckets: number): number {
  return Math.min(buckets - 1, Math.floor((((hue % 360) + 360) % 360) / (360 / buckets)));
}

/**
 * The town draws residents in its own pixel style from four swatches. The
 * agent's look picks them: hair hue → cap, accent hue → backpack, skin
 * lightness → skin, outfit hue → pants. No look → the town's defaults.
 */
export function lookFor(colors: Partial<Record<Slot, string>> | null | undefined): WorldLook | undefined {
  if (!colors) return undefined;
  const look: WorldLook = {};
  const hair = colors.hair ? hsl(colors.hair) : null;
  const accent = colors.accent ? hsl(colors.accent) : null;
  const skin = colors.skin ? hsl(colors.skin) : null;
  const outfit = colors.outfit ? hsl(colors.outfit) : null;
  if (hair) look.cap = bucket(hair.h, 10);
  if (accent) look.backpack = bucket(accent.h, 10);
  if (skin) look.skin = Math.max(0, Math.min(7, Math.round((1 - skin.l) * 7)));
  if (outfit) look.pants = bucket(outfit.h, 8);
  return Object.keys(look).length ? look : undefined;
}

/** The name-tag color nearest the agent's accent; cyan when there is none. */
export function tagFor(colors: Partial<Record<Slot, string>> | null | undefined): WorldTagColor {
  const accent = colors?.accent ? hsl(colors.accent) : null;
  if (!accent || accent.s < 0.15) return "cyan";
  let best: WorldTagColor = "cyan";
  let bestGap = 361;
  for (const tag of TAG_COLORS) {
    const gap = Math.min(Math.abs(TAG_HUES[tag] - accent.h), 360 - Math.abs(TAG_HUES[tag] - accent.h));
    if (gap < bestGap) {
      bestGap = gap;
      best = tag;
    }
  }
  return best;
}

/**
 * The config writes the card makes itself: the spending switch (under the
 * resident's own table: `/ether_hollow` for the first resident,
 * `/ether_hollow/residents/<alias>` for the others) and the wake switch.
 */
export function spendOps(on: boolean, path = "/ether_hollow"): PatchOp[] {
  const table = path.trim().replace(/\/+$/, "") || "/ether_hollow";
  return [{ op: "add", path: `${table}/spend`, value: on }];
}

/** The agents the card may pick as residents: every agent but Cael, the guide, in config order. */
export function residentCandidates(agents: readonly string[]): string[] {
  const seen = new Set<string>();
  return agents.map((a) => a.trim()).filter((a) => a && a !== "cael" && !seen.has(a) && seen.add(a));
}

/** One word for a resident chip: in town, a resident, or not one yet. */
export function residentStatus(
  residents: readonly { agent: string; registered: boolean; in_town: boolean }[] | undefined,
  alias: string,
): "in_town" | "resident" | "none" {
  const r = residents?.find((x) => x.agent === alias);
  if (!r || !r.registered) return "none";
  return r.in_town ? "in_town" : "resident";
}

/** The tools a woken agent gets; nobody is there to tap, so its profile must let them through. */
export const WAKE_TOOLS = ["ether_hollow", "memory_recall", "memory_store"] as const;

/**
 * The wake switch, and, when it goes on, the resident agent's risk profile
 * letting the woken agent use the town and its memory without a prompt: a
 * wake runs with no one to answer one, and a supervised profile denies what
 * it cannot ask about. Spending stays the tool's own switch. Without a
 * profile to write, the switch alone is written.
 */
export function wakeOps(on: boolean, profile?: string | null, autoApprove?: readonly string[] | null): PatchOp[] {
  const ops: PatchOp[] = [{ op: "add", path: "/ether_hollow/wake", value: on }];
  if (on && profile) {
    const current = autoApprove ?? [];
    const missing = WAKE_TOOLS.filter((t) => !current.includes(t));
    if (missing.length) ops.push({ op: "add", path: `/risk_profiles/${profile}/auto_approve`, value: [...current, ...missing] });
  }
  return ops;
}

/** The last wake, as one line: when, why, and whether the agent had anything to say. */
export function wakeLine(
  wake: { last_at: number | null; last_reason: string | null; last_ok: boolean | null; last_output: string | null },
  words: { never: string; quiet: string; failed: string },
  locale?: string,
): string {
  if (wake.last_at === null) return words.never;
  const when = clock(wake.last_at, locale);
  const reason = wake.last_reason ?? "";
  const output = (wake.last_output ?? "").trim();
  const quiet = /^no_reply\b/i.test(output);
  const said = wake.last_ok === false ? words.failed : quiet || output === "" ? words.quiet : output;
  return `${when} · ${reason} · ${said}`;
}

/** `rc` as the owner reads it: the coin and what it is worth (100 RC = $1). */
export function rcText(rc: number | undefined): string {
  if (rc === undefined || !Number.isFinite(rc)) return "";
  return `${rc} RC (about $${(rc / 100).toFixed(2)})`;
}

/** Minutes left in a visit; 0 when it is over or there is none. */
export function minutesLeft(presence: WorldPresence, nowSecs: number): number {
  if (!presence.in_town || presence.until === null) return 0;
  return Math.max(0, Math.ceil((presence.until - nowSecs) / 60));
}

/** `HH:MM` in the viewer's clock for a unix time; "" for none. */
export function clock(secs: number | null, locale?: string): string {
  if (secs === null) return "";
  return new Date(secs * 1000).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
}

/** An RC pack code's shape: the Shop's code with the pack `RC<amount>`. */
export const RC_CODE_RULE = /^RC(\d{1,7})-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{8}-[A-Za-z0-9_-]{86}$/i;

/** The RC an RC pack code names, from its shape alone (the Runtime checks the signature); null when it is not one. */
export function rcCodeAmount(code: string): number | null {
  const m = RC_CODE_RULE.exec(code.replace(/\s+/g, ""));
  if (!m) return null;
  const n = parseInt(m[1]!, 10);
  return n > 0 ? n : null;
}

/** A lot as the card lists it: its name and the monthly rent. */
export function lotLabel(lot: { name: string; rent_rc_month: number | null }, perMonth: string): string {
  return lot.rent_rc_month ? `${lot.name} · ${lot.rent_rc_month} RC ${perMonth}` : lot.name;
}

/**
 * The lease as one line for the card. `words` carries the phrases; the
 * numbers and dates are the town's. Missed payments and the repossession
 * date come first when they exist, since they are what the owner must act on.
 */
export function leaseLine(
  lease: {
    lot?: string;
    place?: string;
    rent_rc_month?: number;
    paid_through?: string;
    next_due?: string;
    due_by?: string;
    owing?: boolean;
    missed?: number;
    repossess_on?: string;
  },
  words: { renting: string; next: string; owing: string; missed: string; repossess: string },
): string {
  const parts: string[] = [];
  parts.push(words.renting.replace("{place}", lease.place ?? lease.lot ?? "").replace("{rent}", String(lease.rent_rc_month ?? "")));
  if ((lease.missed ?? 0) > 0) {
    parts.push(words.missed.replace("{missed}", String(lease.missed)));
    if (lease.repossess_on) parts.push(words.repossess.replace("{date}", lease.repossess_on));
  } else if (lease.owing) {
    parts.push(words.owing);
  }
  const due = lease.next_due ?? lease.due_by;
  if (due && !((lease.missed ?? 0) > 0)) parts.push(words.next.replace("{date}", due));
  return parts.join(" · ");
}

/** The week as the config's `hours` lines name it. */
export const PLAN_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type PlanDay = (typeof PLAN_DAYS)[number];

/** One day of the owner's grid as the card edits it: on or off, from and to (local `HH:MM`). */
export interface DayHours {
  day: PlanDay;
  on: boolean;
  from: string;
  to: string;
}

/** A new day's hours when the owner turns it on. */
export const DAY_DEFAULT = { from: "09:00", to: "17:00" } as const;

/** `HH:MM` (or `H:MM`) as minutes; null when it is not a time. `24:00` is an end. */
export function minutesOf(text: string): number | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(text.trim());
  if (!m) return null;
  const h = parseInt(m[1]!, 10);
  const min = parseInt(m[2]!, 10);
  if (min > 59 || h > 24 || (h === 24 && min !== 0)) return null;
  return h * 60 + min;
}

export function hhmm(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

/**
 * The config's `hours` lines as the card's simple grid: per day on or off,
 * from the first span's start to the last span's end (the card edits one span
 * a day; the Runtime reads several, comma-separated, when written by hand).
 */
export function gridFromLines(lines: readonly string[] | undefined): DayHours[] {
  const spans = new Map<PlanDay, { from: number; to: number }>();
  for (const raw of lines ?? []) {
    const line = raw.trim();
    const [head, ...rest] = line.split(/\s+/);
    const day = PLAN_DAYS.find((d) => (head ?? "").toLowerCase().startsWith(d));
    if (!day) continue;
    for (const span of rest.join(" ").split(",")) {
      const [a, b] = span.split("-");
      const from = minutesOf(a ?? "");
      const to = minutesOf(b ?? "");
      if (from === null || to === null || to <= from) continue;
      const had = spans.get(day);
      spans.set(day, had ? { from: Math.min(had.from, from), to: Math.max(had.to, to) } : { from, to });
    }
  }
  return PLAN_DAYS.map((day) => {
    const s = spans.get(day);
    return s ? { day, on: true, from: hhmm(s.from), to: hhmm(s.to) } : { day, on: false, from: DAY_DEFAULT.from, to: DAY_DEFAULT.to };
  });
}

/** The grid as the config's lines: one per day that is on. */
export function linesFromGrid(grid: readonly DayHours[]): string[] {
  return grid.filter((d) => d.on).map((d) => `${d.day} ${hhmm(minutesOf(d.from) ?? 0)}-${hhmm(minutesOf(d.to) ?? 0)}`);
}

/** The first day that is on and does not read (not a time, or it ends before it starts); null when all read. */
export function gridProblem(grid: readonly DayHours[]): PlanDay | null {
  for (const d of grid) {
    if (!d.on) continue;
    const from = minutesOf(d.from);
    const to = minutesOf(d.to);
    if (from === null || to === null || from >= 24 * 60 || to <= from) return d.day;
  }
  return null;
}

/** A budget the owner typed: a whole number of visits from 0 to 1000; null when it is not one. */
export function budgetOf(text: string): number | null {
  const t = text.trim();
  if (!/^\d{1,4}$/.test(t)) return null;
  const n = parseInt(t, 10);
  return n <= 1000 ? n : null;
}

/** The config writes for the owner's grid and the monthly budget, under the resident's own table. */
export function planOps(lines: readonly string[], visitsMonth: number, path = "/ether_hollow"): PatchOp[] {
  const table = path.trim().replace(/\/+$/, "") || "/ether_hollow";
  return [
    { op: "add", path: `${table}/hours`, value: [...lines] },
    { op: "add", path: `${table}/visits_month`, value: Math.max(0, Math.floor(visitsMonth)) },
  ];
}

/** A slot's end as `HH:MM`. */
export function slotEnd(slot: Pick<WorldSlot, "at" | "minutes">): string {
  const start = minutesOf(slot.at);
  return start === null ? "" : hhmm(Math.min(24 * 60, start + slot.minutes));
}

/** One stop of the agent's day as the card lists it: `09:00-10:00 · the bank · open the shop`. */
export function slotLine(slot: WorldSlot): string {
  return `${slot.at}-${slotEnd(slot)} · ${slot.place} · ${slot.doing}`;
}

/** Whether a slot of today ran already, runs now, or is still to come. `now` is the gateway's `YYYY-MM-DD HH:MM`. */
export function slotState(day: string, slot: WorldSlot, ran: readonly string[], now: string): "done" | "now" | "later" {
  const [today, time] = now.split(" ");
  const at = minutesOf(time ?? "");
  const start = minutesOf(slot.at);
  const end = start === null ? null : start + slot.minutes;
  const started = ran.includes(`${day} ${slot.at}`);
  if (today === day && at !== null && start !== null && end !== null && start <= at && at < end && started) return "now";
  if (started || (today === day && at !== null && end !== null && end <= at)) return "done";
  return "later";
}

/** The slot running now, as Home and the card say it: `at the bank: opening the shop, until 10:00`. */
export function planNowLine(now: WorldPlanNow): string {
  return `at ${now.place}: ${now.doing}, until ${now.end}`;
}

/** Where the owner opens the town itself, to watch the ghost. */
export function townSite(url: string): string {
  const u = url.trim().replace(/\/+$/, "");
  return u || TOWN_URL;
}
