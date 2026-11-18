// The Ether Hollow card's pure part: what a resident's name may be, how the
// agent's pixel look becomes the town's four swatches and a name-tag color,
// the config write for the spending switch, and the words for a visit.
import type { Slot } from "@/looks/looks.logic";
import type { WorldLook, WorldPresence, WorldTagColor } from "@/lib/world";
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

/** The config writes the card makes itself: the spending switch and the wake switch. */
export function spendOps(on: boolean): PatchOp[] {
  return [{ op: "add", path: "/ether_hollow/spend", value: on }];
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

/** Where the owner opens the town itself, to watch the ghost. */
export function townSite(url: string): string {
  const u = url.trim().replace(/\/+$/, "");
  return u || TOWN_URL;
}
