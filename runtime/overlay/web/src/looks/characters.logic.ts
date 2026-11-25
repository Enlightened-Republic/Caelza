// Drawn characters as looks, with nothing React in it: a PNGtuber the owner
// downloaded (a .zip, or its PNGs) becomes a character the Runtime keeps
// (`/api/looks/characters`, api_looks.rs) and any agent can wear. A PNGtuber
// is a set of frames: the mouth closed, the mouth open (talking), a blink, and
// reactions; the look uses the first three, the same frames the pixel
// characters have. `node --experimental-strip-types --test
// src/looks/looks.logic.test.ts` runs these with the rest of the looks.
import type { Frame } from "./looks.logic";

/** A character's id (looks.logic.ts `CHARACTER_ID`, api_looks.rs `is_character_id`; the test keeps them equal). */
export const CHARACTER_ID = /^[a-z0-9][a-z0-9-]{0,47}$/;

export interface Character {
  id: string;
  name: string;
  /** The frames the Runtime holds for it (closed is the one it needs). */
  frames: Frame[];
}

/** Under the gateway's 64 KB request body limit (api_looks.rs `MAX_FRAME_BYTES`). */
export const MAX_FRAME_BYTES = 60 * 1024;

// ---- the files ------------------------------------------------------------------

export interface NamedFile {
  name: string;
  data: Uint8Array;
}

function u16(b: Uint8Array, at: number): number {
  return b[at]! | (b[at + 1]! << 8);
}

function u32(b: Uint8Array, at: number): number {
  return (b[at]! | (b[at + 1]! << 8) | (b[at + 2]! << 16) | (b[at + 3]! << 24)) >>> 0;
}

async function inflateRaw(data: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** The base name of a path in a zip, with either slash. */
export function baseName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] ?? path;
}

/**
 * The PNGs in a zip: read from its central directory (so entries written with
 * a data descriptor read right), stored or deflated, folders and macOS's
 * `__MACOSX` shadows skipped. Throws a plain sentence on what it cannot read.
 */
export async function pngsInZip(zip: Uint8Array): Promise<NamedFile[]> {
  // The end of central directory record: its signature, searched back over the comment.
  let eocd = -1;
  for (let i = zip.length - 22; i >= Math.max(0, zip.length - 22 - 0xffff); i--) {
    if (u32(zip, i) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error("That file is not a zip.");
  const count = u16(zip, eocd + 10);
  let at = u32(zip, eocd + 16);
  if (count === 0xffff || at === 0xffffffff) throw new Error("That zip is too big to read here (zip64).");
  const out: NamedFile[] = [];
  for (let n = 0; n < count; n++) {
    if (u32(zip, at) !== 0x02014b50) throw new Error("That zip is damaged.");
    const method = u16(zip, at + 10);
    const compressed = u32(zip, at + 20);
    const nameLen = u16(zip, at + 28);
    const extraLen = u16(zip, at + 30);
    const commentLen = u16(zip, at + 32);
    const local = u32(zip, at + 42);
    const name = new TextDecoder().decode(zip.subarray(at + 46, at + 46 + nameLen));
    at += 46 + nameLen + extraLen + commentLen;
    if (name.endsWith("/") || name.startsWith("__MACOSX/") || name.includes("/__MACOSX/")) continue;
    const base = baseName(name);
    if (base.startsWith(".") || !/\.png$/i.test(base)) continue;
    if (u32(zip, local) !== 0x04034b50) throw new Error("That zip is damaged.");
    const start = local + 30 + u16(zip, local + 26) + u16(zip, local + 28);
    const raw = zip.subarray(start, start + compressed);
    if (method === 0) out.push({ name, data: raw.slice() });
    else if (method === 8) out.push({ name, data: await inflateRaw(raw) });
    else throw new Error(`${base} is packed in a way this cannot read (method ${method}).`);
  }
  return out;
}

// ---- which file is which frame ----------------------------------------------------

function words(name: string): string {
  return baseName(name)
    .toLowerCase()
    .replace(/\.png$/, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

const BLINK = /\b(blink|blinking|eyes? closed)\b/;
const OPEN = /\b(open|opened|talk|talking|speak|speaking|mouth open|loud)\b/;
const CLOSED = /\b(closed|close|idle|neutral|default|rest|resting|quiet|base|mouth closed)\b/;

/**
 * The look's three frames among a PNGtuber's files: the mouth closed (idle),
 * the mouth open (talking), the blink with the mouth closed. Our store's packs
 * name them `01_closed`, `02_open`, `03_closed_blink`; other packs say idle,
 * talking, blink. Without a closed or idle frame, the first file in name
 * order is the closed one. Reactions (smile, surprise...) are not used.
 */
export function pickFrames(names: string[]): Partial<Record<Frame, string>> {
  const sorted = [...names].sort((a, b) => baseName(a).localeCompare(baseName(b), undefined, { numeric: true }));
  const w = new Map(sorted.map((n) => [n, words(n)]));
  const blinks = sorted.filter((n) => BLINK.test(w.get(n)!));
  const blink = blinks.find((n) => !OPEN.test(w.get(n)!)) ?? blinks[0];
  const open = sorted.find((n) => OPEN.test(w.get(n)!) && !BLINK.test(w.get(n)!) && !/\bmouth closed\b/.test(w.get(n)!));
  const closed =
    sorted.find((n) => CLOSED.test(w.get(n)!) && !BLINK.test(w.get(n)!) && n !== open) ??
    sorted.find((n) => n !== open && n !== blink);
  const out: Partial<Record<Frame, string>> = {};
  if (closed) out.closed = closed;
  if (open) out.open = open;
  if (blink && blink !== closed) out.blink = blink;
  return out;
}

/**
 * A name for the character from the file or folder it came in: our store's
 * zips read "Pirate Radio DJ Female - PNGTuber.zip"; the "PNGTuber" and the
 * punctuation go, the words stay.
 */
export function characterName(fileName: string): string {
  const name = baseName(fileName)
    .replace(/\.(zip|png)$/i, "")
    .replace(/[_\-.()[\]]+/g, " ")
    .replace(/\b(png ?tubers?|vtubers?|avatar|pack)\b/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
  return (name || "Character").slice(0, 48).trim();
}

/** A new id for a name, not one of `taken`: lowercase words joined with `-`. */
export function characterId(name: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  const stem =
    name
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40)
      .replace(/-+$/, "") || "character";
  let id = stem;
  for (let n = 2; used.has(id); n++) id = `${stem}-${n}`;
  if (!CHARACTER_ID.test(id)) throw new Error(`could not make an id from ${JSON.stringify(name)}`);
  return id;
}

/**
 * The sizes to try when fitting a frame under `MAX_FRAME_BYTES`, largest
 * first: no taller than 704 px (a 200 px preview on a 3x screen needs 600),
 * then down by whole halves and thirds, never under 88 px tall. The PNG is
 * re-encoded at each until one fits; nearest-neighbour keeps pixel art crisp.
 */
export function fitSizes(width: number, height: number): Array<{ width: number; height: number }> {
  const out: Array<{ width: number; height: number }> = [];
  const start = Math.min(1, 704 / height);
  for (const f of [1, 1 / 2, 1 / 3, 1 / 4, 1 / 6, 1 / 8]) {
    const s = start * f;
    const h = Math.round(height * s);
    if (h < 88 && out.length) break;
    const size = { width: Math.max(1, Math.round(width * s)), height: Math.max(1, h) };
    if (!out.some((o) => o.width === size.width && o.height === size.height)) out.push(size);
  }
  return out;
}

/** Where the dashboard asks the Runtime for a frame. */
export function frameUrl(id: string, frame: Frame): string {
  return `/api/looks/characters/${encodeURIComponent(id)}/${frame}`;
}

/** The frame to draw: a missing open or blink frame shows the closed one. */
export function frameToDraw(c: Pick<Character, "frames"> | null, frame: Frame): Frame {
  if (!c) return "closed";
  return c.frames.includes(frame) ? frame : "closed";
}
