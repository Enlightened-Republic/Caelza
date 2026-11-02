// The looks (vision M8) with nothing React in it: the catalog's shape
// (looks/catalog.json, copied beside this file by runtime/build.sh), the
// renderer's maths (the key palette, the colour ramps, the outline), the
// default every agent wears before it is dressed (the same deal as
// looks/parts.py, so the Python previews and the dashboard agree), the
// wardrobe, and what a saved look must look like. `node
// --experimental-strip-types --test looks.logic.test.ts` runs the tests, so
// this file stays plain TypeScript with no path aliases.

export type Layer = "backdrop" | "body" | "outfit" | "hair" | "hat" | "face" | "accessory";
export type Stage = "backdrop" | "silhouette" | "detail";
export type Slot = "skin" | "hair" | "outfit" | "accent" | "eyes";
export type Frame = "closed" | "open" | "blink";

/** Draw order; the silhouette layers get one outline around their union. */
export const LAYERS: readonly Layer[] = ["backdrop", "body", "outfit", "hair", "hat", "face", "accessory"];
export const STAGES: Record<Layer, Stage> = {
  backdrop: "backdrop",
  body: "silhouette",
  outfit: "silhouette",
  hair: "silhouette",
  hat: "silhouette",
  face: "detail",
  accessory: "detail",
};
export const SLOTS: readonly Slot[] = ["skin", "hair", "outfit", "accent", "eyes"];
export const FRAMES: readonly Frame[] = ["closed", "open", "blink"];
export const GRID = { width: 40, height: 44 } as const;

/** The key colours the exported PNGs hold, per slot and tone (looks/parts.py KEYS). */
export const KEYS: Record<Slot, Partial<Record<"d" | "m" | "l", [number, number, number]>>> = {
  skin: { d: [200, 1, 1], m: [250, 1, 1], l: [255, 120, 120] },
  hair: { d: [1, 200, 1], m: [1, 250, 1], l: [120, 255, 120] },
  outfit: { d: [1, 1, 200], m: [1, 1, 250], l: [120, 120, 255] },
  accent: { d: [200, 1, 200], m: [250, 1, 250], l: [255, 120, 255] },
  eyes: { m: [1, 250, 250] },
};
/** The outline: near-black tinted to the palette. */
export const OUTLINE: [number, number, number] = [13, 8, 32];

export interface CatalogPart {
  id: string;
  layer: Layer;
  name: string;
  pack: string;
  slots: Slot[];
}
export interface CatalogPack {
  id: string;
  name: string;
  blurb: string;
  price: "free" | { usd: number };
  status: "available" | "soon";
  /** How a priced pack unlocks: `code`, an unlock code from the owner's shop (scripts/unlock_codes.py). */
  unlock?: string;
  /** Where a code is sold, once the owner has a storefront. */
  buy?: string;
}
export interface Catalog {
  version: number;
  updated: string;
  layers: Layer[];
  frames: Frame[];
  slots: Slot[];
  colors: Record<Slot, string[]>;
  /** The public key the Runtime checks unlock codes against (api_looks.rs carries the same hex). */
  unlock?: { scheme: string; public_key: string };
  packs: CatalogPack[];
  parts: CatalogPart[];
  cael: { parts: Record<Layer, string>; colors: Record<Slot, string> };
}

export interface Look {
  version: 1;
  parts: Record<Layer, string>;
  colors: Record<Slot, string>;
}
export interface Wardrobe {
  version: 1;
  packs: string[];
  /** Pack id → the id of the code that opened it; the Runtime keeps these, only a code adds one. */
  unlocks?: Record<string, string>;
}

/** The pack every wardrobe holds. */
export const STARTER = "starter";

const HEX = /^#[0-9a-f]{6}$/i;

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

function mix(a: [number, number, number], b: [number, number, number], t: number): [number, number, number] {
  // floor(x + 0.5) on both sides: Python's round() is banker's and would differ on .5.
  return [Math.floor(a[0] + (b[0] - a[0]) * t + 0.5), Math.floor(a[1] + (b[1] - a[1]) * t + 0.5), Math.floor(a[2] + (b[2] - a[2]) * t + 0.5)];
}

/** The three tones of a chosen colour: the colour, 40 % toward the outline, 38 % toward white (parts.py `ramp`). */
export function ramp(hex: string): { m: [number, number, number]; d: [number, number, number]; l: [number, number, number] } {
  const m = hexToRgb(hex);
  return { m, d: mix(m, OUTLINE, 0.4), l: mix(m, [255, 255, 255], 0.38) };
}

export function packRgb(r: number, g: number, b: number): number {
  return (r << 16) | (g << 8) | b;
}

/** Key colour (packed) → chosen tone, for the colours given. */
export function recolorTable(colors: Partial<Record<Slot, string>>): Map<number, [number, number, number]> {
  const table = new Map<number, [number, number, number]>();
  for (const slot of SLOTS) {
    const chosen = colors[slot];
    if (!chosen || !HEX.test(chosen)) continue;
    const tones = ramp(chosen);
    for (const [tone, key] of Object.entries(KEYS[slot]) as Array<["d" | "m" | "l", [number, number, number]]>) {
      table.set(packRgb(key[0], key[1], key[2]), tones[tone]);
    }
  }
  return table;
}

/**
 * The renderer's pixel pass, in place: the silhouette's outline (one pixel on
 * transparent neighbours of the silhouette, the detail layers excluded), then
 * every key colour swapped for its tone. `sil` marks which pixels belong to
 * the silhouette stage; `data` is the RGBA of the composed character.
 */
export function finishPixels(data: Uint8ClampedArray, sil: Uint8Array, width: number, height: number, table: Map<number, [number, number, number]>): void {
  const n = width * height;
  const outlinePts: number[] = [];
  for (let i = 0; i < n; i++) {
    if (data[i * 4 + 3] !== 0) continue;
    const x = i % width;
    const y = (i - x) / width;
    if (
      (x + 1 < width && sil[i + 1]) ||
      (x > 0 && sil[i - 1]) ||
      (y + 1 < height && sil[i + width]) ||
      (y > 0 && sil[i - width])
    ) {
      outlinePts.push(i);
    }
  }
  for (const i of outlinePts) {
    data[i * 4] = OUTLINE[0];
    data[i * 4 + 1] = OUTLINE[1];
    data[i * 4 + 2] = OUTLINE[2];
    data[i * 4 + 3] = 255;
  }
  for (let i = 0; i < n; i++) {
    if (data[i * 4 + 3] === 0) continue;
    const rgb = table.get(packRgb(data[i * 4]!, data[i * 4 + 1]!, data[i * 4 + 2]!));
    if (rgb) {
      data[i * 4] = rgb[0];
      data[i * 4 + 1] = rgb[1];
      data[i * 4 + 2] = rgb[2];
    }
  }
}

/** Where a part's PNG is served: `${base}/_app/looks/parts/<layer>/<name>[.<frame>].png`. */
export function partUrl(base: string, id: string, frame: Frame = "closed"): string {
  const [layer, name] = id.split(".", 2) as [Layer, string];
  return `${base}/_app/looks/parts/${layer}/${name}${layer === "face" ? `.${frame}` : ""}.png`;
}

export function sheetUrl(base: string, pack: string): string {
  return `${base}/_app/looks/sheets/${pack}.png`;
}

/** FNV-1a over UTF-8, 32 bits (parts.py `fnv1a`). */
export function fnv1a(text: string): number {
  let h = 0x811c9dc5;
  for (const b of new TextEncoder().encode(text)) {
    h ^= b;
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

export function partsByLayer(catalog: Catalog, pack?: string): Record<Layer, CatalogPart[]> {
  const out = Object.fromEntries(LAYERS.map((l) => [l, [] as CatalogPart[]])) as Record<Layer, CatalogPart[]>;
  for (const p of catalog.parts) {
    if (pack && p.pack !== pack) continue;
    out[p.layer]?.push(p);
  }
  return out;
}

/** Every agent has a face from day one: Cael's own, or one dealt from its name (parts.py `default_look`). */
export function defaultLook(alias: string, catalog: Catalog): Look {
  if (alias === "cael") {
    return { version: 1, parts: { ...catalog.cael.parts }, colors: { ...catalog.cael.colors } };
  }
  const starter = partsByLayer(catalog, STARTER);
  const h = fnv1a(alias);
  const parts = {} as Record<Layer, string>;
  LAYERS.forEach((layer, i) => {
    const ids = starter[layer];
    parts[layer] = ids[(h >>> (i * 4)) % ids.length]!.id;
  });
  const colors = {} as Record<Slot, string>;
  SLOTS.forEach((slot, i) => {
    const palette = catalog.colors[slot];
    colors[slot] = palette[(h >>> (i * 3 + 7)) % palette.length]!;
  });
  return { version: 1, parts, colors };
}

export function partById(catalog: Catalog, id: string): CatalogPart | null {
  return catalog.parts.find((p) => p.id === id) ?? null;
}

export function isPriced(pack: CatalogPack): boolean {
  return pack.price !== "free";
}

/** A code opened this pack before (the Runtime remembers), so it goes back into the wardrobe without one. */
export function unlocked(packId: string, wardrobe: Wardrobe | null): boolean {
  return typeof wardrobe?.unlocks?.[packId] === "string";
}

/** The packs whose pieces the owner can wear: the starter, plus the available
 *  packs in the wardrobe; a priced pack only once a code opened it. */
export function ownedPacks(catalog: Catalog, wardrobe: Wardrobe | null): Set<string> {
  const owned = new Set<string>([STARTER]);
  const inWardrobe = new Set(wardrobe?.packs ?? []);
  for (const pack of catalog.packs) {
    if (pack.status !== "available" || !inWardrobe.has(pack.id)) continue;
    if (isPriced(pack) && !unlocked(pack.id, wardrobe)) continue;
    owned.add(pack.id);
  }
  return owned;
}

const CODE_ID = /^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{8}$/;
const CODE_SIGNATURE = /^[A-Za-z0-9_-]{86}$/;

/** An unlock code's shape, `<PACK>-<ID>-<signature>`, before the Runtime
 *  checks the signature: which pack it names and its id, or null when it is
 *  not shaped like one. Case and spaces do not matter. */
export function parseUnlockCode(code: string): { pack: string; id: string } | null {
  const text = code.replace(/\s+/g, "");
  const first = text.indexOf("-");
  const second = first < 0 ? -1 : text.indexOf("-", first + 1);
  if (first < 0 || second < 0) return null;
  const pack = text.slice(0, first).toLowerCase();
  const id = text.slice(first + 1, second).toUpperCase();
  const signature = text.slice(second + 1);
  if (!/^[a-z0-9_]{1,64}$/.test(pack) || !CODE_ID.test(id) || !CODE_SIGNATURE.test(signature)) return null;
  return { pack, id };
}

/** What a look must be to be saved: every layer a part of that layer, every slot a colour. */
export function validateLook(look: unknown, catalog: Catalog): string[] {
  const problems: string[] = [];
  if (!look || typeof look !== "object") return ["a look is an object"];
  const l = look as Partial<Look>;
  if (l.version !== 1) problems.push("version must be 1");
  const parts = (l.parts ?? {}) as Record<string, unknown>;
  for (const layer of LAYERS) {
    const id = parts[layer];
    if (typeof id !== "string") {
      problems.push(`${layer}: no part`);
      continue;
    }
    const part = partById(catalog, id);
    if (!part) problems.push(`${layer}: ${id} is not in the catalog`);
    else if (part.layer !== layer) problems.push(`${layer}: ${id} is a ${part.layer} part`);
  }
  const colors = (l.colors ?? {}) as Record<string, unknown>;
  for (const slot of SLOTS) {
    const c = colors[slot];
    if (typeof c !== "string" || !HEX.test(c)) problems.push(`${slot}: not a #rrggbb colour`);
  }
  return problems;
}

/** A saved look (or anything that was saved as one) made whole: broken fields fall back to the default. */
export function normalizeLook(raw: unknown, alias: string, catalog: Catalog): Look {
  const base = defaultLook(alias, catalog);
  if (!raw || typeof raw !== "object") return base;
  const r = raw as Partial<Look>;
  const parts = { ...base.parts };
  for (const layer of LAYERS) {
    const id = (r.parts as Record<string, unknown> | undefined)?.[layer];
    if (typeof id === "string" && partById(catalog, id)?.layer === layer) parts[layer] = id;
  }
  const colors = { ...base.colors };
  for (const slot of SLOTS) {
    const c = (r.colors as Record<string, unknown> | undefined)?.[slot];
    if (typeof c === "string" && HEX.test(c)) colors[slot] = c.toLowerCase();
  }
  return { version: 1, parts, colors };
}

/** The colour rows the customizer shows: the slots the chosen parts recolour, in slot order. */
export function slotsInUse(look: Look, catalog: Catalog): Slot[] {
  const used = new Set<Slot>();
  for (const id of Object.values(look.parts)) for (const s of partById(catalog, id)?.slots ?? []) used.add(s);
  return SLOTS.filter((s) => used.has(s));
}

/** Pieces a look wears from packs that are not in the wardrobe (a pack removed, or a look pasted in). */
export function lockedParts(look: Look, catalog: Catalog, owned: Set<string>): string[] {
  return Object.values(look.parts).filter((id) => {
    const p = partById(catalog, id);
    return p !== null && !owned.has(p.pack);
  });
}

export function lookEquals(a: Look, b: Look): boolean {
  return LAYERS.every((l) => a.parts[l] === b.parts[l]) && SLOTS.every((s) => a.colors[s].toLowerCase() === b.colors[s].toLowerCase());
}

/** The pack price for a sentence. */
export function priceLabel(pack: CatalogPack): string {
  return pack.price === "free" ? "Free" : `$${pack.price.usd.toFixed(2)}`;
}
