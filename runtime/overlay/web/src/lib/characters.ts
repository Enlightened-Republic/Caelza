// The drawn characters on the Runtime (api_looks.rs `/api/looks/characters`):
// the PNGtubers the owner imported, wearable by any agent. A frame is a PNG
// fetched with the dashboard's token (an <img> cannot send it), turned into an
// image once per page and shared by every Look that draws it.
import { apiFetch } from "./api";
import { getToken } from "./auth";
import { apiOrigin, basePath } from "./basePath";
import { characterId, characterName, fitSizes, frameUrl, MAX_FRAME_BYTES, pickFrames, pngsInZip, type Character, type NamedFile } from "@/looks/characters.logic";
import type { Frame } from "@/looks/looks.logic";

export function listCharacters(): Promise<{ characters: Character[] }> {
  return apiFetch<{ characters: Character[] }>("/api/looks/characters");
}

export function putCharacter(id: string, name: string): Promise<{ id: string; name: string }> {
  return apiFetch(`/api/looks/characters/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function putCharacterFrame(id: string, frame: Frame, png: Blob): Promise<unknown> {
  return apiFetch(frameUrl(id, frame), { method: "PUT", headers: { "Content-Type": "image/png" }, body: png });
}

export function deleteCharacter(id: string): Promise<unknown> {
  return apiFetch(`/api/looks/characters/${encodeURIComponent(id)}`, { method: "DELETE" });
}

// ---- the frames as images, once per page ----------------------------------------

const images = new Map<string, Promise<HTMLImageElement>>();
const EVENT = "caelza-characters-changed";

/** A character's frame as an image; a failure is forgotten so the next draw asks again. */
export function characterImage(id: string, frame: Frame): Promise<HTMLImageElement> {
  const key = `${id}\n${frame}`;
  let p = images.get(key);
  if (!p) {
    p = (async () => {
      const headers = new Headers();
      const token = getToken();
      if (token) headers.set("Authorization", `Bearer ${token}`);
      const r = await fetch(`${apiOrigin}${basePath}${frameUrl(id, frame)}`, { headers });
      if (r.status === 404) throw Object.assign(new Error(`${id} has no ${frame} frame`), { missing: true });
      if (!r.ok) throw new Error(`the ${frame} frame of ${id} did not load (${r.status})`);
      const url = URL.createObjectURL(await r.blob());
      return await new Promise<HTMLImageElement>((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error(`the ${frame} frame of ${id} is not an image`));
        img.src = url;
      });
    })();
    // A frame that is not there stays known as missing (a blink every few
    // seconds must not ask again); any other failure is tried again next draw.
    p.catch((e: unknown) => {
      if (!(e as { missing?: boolean }).missing) images.delete(key);
    });
    images.set(key, p);
  }
  return p;
}

/** After an import or a removal: drop the cached frames and tell every Look. */
export function charactersChanged(id?: string): void {
  for (const key of [...images.keys()]) if (!id || key.startsWith(`${id}\n`)) images.delete(key);
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new CustomEvent(EVENT, { detail: id ?? null }));
  }
}

export const CHARACTERS_EVENT = EVENT;

// ---- importing a downloaded PNGtuber --------------------------------------------

/** The PNGs the owner picked: a zip's, or the PNG files themselves. */
export async function pngsFromFiles(files: File[]): Promise<NamedFile[]> {
  const out: NamedFile[] = [];
  for (const f of files) {
    const data = new Uint8Array(await f.arrayBuffer());
    if (/\.zip$/i.test(f.name) || (data[0] === 0x50 && data[1] === 0x4b)) out.push(...(await pngsInZip(data)));
    else if (/\.png$/i.test(f.name)) out.push({ name: f.name, data });
  }
  return out;
}

async function decode(data: Uint8Array): Promise<ImageBitmap> {
  return createImageBitmap(new Blob([data], { type: "image/png" }));
}

/** The frame as a PNG under the body limit: as it is when small enough, else scaled down crisply. */
export async function fitFrame(data: Uint8Array): Promise<Blob> {
  const original = new Blob([data], { type: "image/png" });
  const bmp = await decode(data);
  try {
    const sizes = fitSizes(bmp.width, bmp.height);
    const fitsAsIs = sizes[0]!.width === bmp.width && sizes[0]!.height === bmp.height;
    if (fitsAsIs && original.size <= MAX_FRAME_BYTES) return original;
    for (const s of sizes) {
      const canvas = document.createElement("canvas");
      canvas.width = s.width;
      canvas.height = s.height;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("no 2d context");
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(bmp, 0, 0, s.width, s.height);
      const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, "image/png"));
      if (blob && blob.size <= MAX_FRAME_BYTES) return blob;
    }
    throw new Error("that image is too detailed to fit, even scaled down");
  } finally {
    bmp.close();
  }
}

export interface ImportResult {
  character: Character;
  /** Frames that were not found by name (the closed one then is the first image). */
  guessed: boolean;
}

/**
 * A downloaded PNGtuber made a character on the Runtime: its closed, open
 * and blink frames picked by name, each fitted under the body limit and sent.
 */
export async function importCharacter(files: File[], taken: string[]): Promise<ImportResult> {
  const pngs = await pngsFromFiles(files);
  if (!pngs.length) throw new Error("No PNG images in that. A PNGtuber is a .zip of PNGs, or the PNGs themselves.");
  const picked = pickFrames(pngs.map((p) => p.name));
  if (!picked.closed) throw new Error("No image to use as the face.");
  const source = files.length === 1 ? files[0]!.name : (pngs[0]!.name.split(/[\\/]/).slice(-2, -1)[0] ?? "Character");
  const name = characterName(source);
  const id = characterId(name, taken);
  await putCharacter(id, name);
  const frames: Frame[] = [];
  for (const frame of ["closed", "open", "blink"] as const) {
    const file = picked[frame];
    if (!file) continue;
    const data = pngs.find((p) => p.name === file)!.data;
    await putCharacterFrame(id, frame, await fitFrame(data));
    frames.push(frame);
  }
  charactersChanged(id);
  return { character: { id, name, frames }, guessed: !picked.open && !picked.blink };
}
