// The pixel character on screen (vision M8): one part per layer composed on
// a 40 x 44 canvas from the exported PNGs, outlined and recoloured with the
// maths in looks.logic.ts, drawn crisp at any size. It blinks, and it talks
// while `talking` is true; with a fixed `frame` it holds still (a thumbnail,
// a bubble in the transcript). `useAgentLook` is the per-agent look from the
// Runtime (/api/looks/<alias>), the default until one is saved, shared
// across every place the agent is drawn and refreshed when the customizer
// saves. Composed frames are cached once per look and frame for the whole
// page, so forty bubbles of one agent cost one composition.
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import { getLook } from "@/lib/api";
import { basePath } from "@/lib/basePath";
import catalogJson from "./catalog.json";
import {
  AVATAR_SIZE,
  GRID,
  LAYERS,
  STAGES,
  avatarGeometry,
  avatarLook,
  defaultLook,
  finishPixels,
  normalizeLook,
  partUrl,
  recolorTable,
  sampleAvatar,
  type Catalog,
  type Frame,
  type Look as LookData,
} from "./looks.logic";

export const catalog = catalogJson as unknown as Catalog;

// ---- images ------------------------------------------------------------------

const images = new Map<string, Promise<HTMLImageElement>>();

/** A part's PNG, fetched once; a failed fetch is forgotten so the next draw tries again. */
function loadImage(url: string): Promise<HTMLImageElement> {
  let p = images.get(url);
  if (!p) {
    p = new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => {
        images.delete(url);
        reject(new Error(`could not load ${url}`));
      };
      img.src = url;
    });
    images.set(url, p);
  }
  return p;
}

/** A composed frame; `complete` is false when a part's PNG did not load (drawn without it, not cached). */
interface Composed {
  data: ImageData;
  complete: boolean;
}

/** The composed character for one frame, ready to draw. */
async function compose(look: LookData, frame: Frame): Promise<Composed> {
  const { width, height } = GRID;
  const sil = new Uint8Array(width * height);
  const det = new Uint8Array(width * height);
  const out = document.createElement("canvas");
  out.width = width;
  out.height = height;
  const ctx = out.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new Error("no 2d context");
  const silCanvas = document.createElement("canvas");
  silCanvas.width = width;
  silCanvas.height = height;
  const sctx = silCanvas.getContext("2d", { willReadFrequently: true })!;
  const detCanvas = document.createElement("canvas");
  detCanvas.width = width;
  detCanvas.height = height;
  const dctx = detCanvas.getContext("2d", { willReadFrequently: true })!;
  const loaded = await Promise.all(LAYERS.map((layer) => loadImage(partUrl(basePath, look.parts[layer], frame)).catch(() => null)));
  LAYERS.forEach((layer, i) => {
    const img = loaded[i];
    if (!img) return;
    const target = STAGES[layer] === "backdrop" ? ctx : STAGES[layer] === "silhouette" ? sctx : dctx;
    target.drawImage(img, 0, 0);
  });
  const silData = sctx.getImageData(0, 0, width, height).data;
  const detData = dctx.getImageData(0, 0, width, height).data;
  for (let i = 0; i < width * height; i++) {
    sil[i] = silData[i * 4 + 3]! > 0 ? 1 : 0;
    det[i] = detData[i * 4 + 3]! > 0 ? 1 : 0;
  }
  ctx.drawImage(silCanvas, 0, 0);
  ctx.drawImage(detCanvas, 0, 0);
  const data = ctx.getImageData(0, 0, width, height);
  finishPixels(data.data, sil, width, height, recolorTable(look.colors), det);
  return { data, complete: loaded.every((img) => img !== null) };
}

/** Composed frames for the page, by look and frame. The customizer makes a new
 *  key per tweak, so the cache is emptied when it grows past a few hundred. A
 *  frame missing a part (its PNG did not load) is drawn but not kept. */
const composed = new Map<string, Promise<Composed>>();
const COMPOSED_LIMIT = 240;

function composedFrame(key: string, look: LookData, frame: Frame): Promise<Composed> {
  const id = `${key}\n${frame}`;
  let p = composed.get(id);
  if (!p) {
    if (composed.size >= COMPOSED_LIMIT) composed.clear();
    p = compose(look, frame);
    const mine = p;
    p.then(
      (c) => {
        if (!c.complete && composed.get(id) === mine) composed.delete(id);
      },
      () => {
        if (composed.get(id) === mine) composed.delete(id);
      },
    );
    composed.set(id, p);
  }
  return p;
}

// ---- the avatar ------------------------------------------------------------------

/** The look as a square PNG for a profile picture (vision M8): the closed
 *  frame at the largest whole scale that fits, Space behind it when it has
 *  no backdrop; `scripts/looks.py avatar` writes the same file. */
export async function avatarPng(look: LookData, size = AVATAR_SIZE): Promise<Blob> {
  const { data, complete } = await compose(avatarLook(look), "closed");
  if (!complete) throw new Error("a piece of the look did not load; try again");
  const g = avatarGeometry(size);
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no 2d context");
  ctx.putImageData(new ImageData(sampleAvatar(data.data, GRID.width, GRID.height, g), size, size), 0, 0);
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("could not encode the avatar"))), "image/png");
  });
}

/** Hand a file to the browser's downloads, named. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

// ---- the component ---------------------------------------------------------------

export interface LookProps {
  look: LookData;
  /** Height in CSS pixels; the width follows the 40 : 44 grid. */
  size?: number;
  /** The mouth moves while true (the agent is answering). */
  talking?: boolean;
  /** A fixed frame, no blinking (thumbnails, the bubbles of a transcript). */
  frame?: Frame;
  /** Hidden from assistive tech: the text beside it already names the agent. */
  decorative?: boolean;
  className?: string;
  title?: string;
  style?: CSSProperties;
}

export function Look({ look, size = 64, talking = false, frame, decorative = false, className, title, style }: LookProps) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [shown, setShown] = useState<Frame>(frame ?? "closed");
  const [mouth, setMouth] = useState<"closed" | "open">("closed");
  const [blinking, setBlinking] = useState(false);
  const key = useMemo(() => JSON.stringify(look), [look]);

  // Which frame to show: a fixed one, else the blink over the mouth.
  useEffect(() => {
    if (frame) setShown(frame);
    else setShown(blinking ? "blink" : mouth);
  }, [frame, blinking, mouth]);

  // Talking: the mouth alternates while it lasts, then closes. The timers are
  // the globals, not window's: a node test renders this with a stub window.
  useEffect(() => {
    if (frame || !talking) {
      setMouth("closed");
      return;
    }
    const id = setInterval(() => setMouth((m) => (m === "open" ? "closed" : "open")), 160);
    return () => clearInterval(id);
  }, [talking, frame]);

  // Blinking: every 2.5 to 5 seconds, for 120 ms.
  useEffect(() => {
    if (frame) return;
    let open: ReturnType<typeof setTimeout> | null = null;
    let close: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      close = setTimeout(() => {
        setBlinking(true);
        open = setTimeout(() => {
          setBlinking(false);
          schedule();
        }, 120);
      }, 2500 + Math.random() * 2500);
    };
    schedule();
    return () => {
      if (close !== null) clearTimeout(close);
      if (open !== null) clearTimeout(open);
    };
  }, [frame]);

  // Compose on demand; the frame is shared with every other Look of this look.
  useEffect(() => {
    if (typeof document === "undefined") return;
    let cancelled = false;
    void composedFrame(key, look, shown)
      .then(({ data }) => {
        const canvas = ref.current;
        if (!canvas || cancelled) return;
        canvas.getContext("2d")?.putImageData(data, 0, 0);
      })
      .catch(() => {
        /* a part that failed to load leaves the canvas as it was */
      });
    return () => {
      cancelled = true;
    };
  }, [key, shown, look]);

  const width = Math.round((size * GRID.width) / GRID.height);
  const a11y = decorative ? { "aria-hidden": true as const } : { role: "img", "aria-label": title ?? "the agent's look", title };
  return (
    <canvas
      ref={ref}
      width={GRID.width}
      height={GRID.height}
      className={`cz-look${className ? ` ${className}` : ""}`}
      style={{ width, height: size, ...style }}
      {...a11y}
    />
  );
}

// ---- the per-agent look -------------------------------------------------------------

const looks = new Map<string, LookData>();
const pending = new Map<string, Promise<LookData>>();
const EVENT = "caelza-look-changed";

/** Remember a look for an agent and tell every `useAgentLook` of it. */
/** The window when it is a real one (a node test renders with a stub). */
function realWindow(): Window | null {
  return typeof window !== "undefined" && typeof window.addEventListener === "function" ? window : null;
}

function announce(alias: string): void {
  realWindow()?.dispatchEvent(new CustomEvent(EVENT, { detail: alias }));
}

export function rememberLook(alias: string, look: LookData): void {
  looks.set(alias, look);
  announce(alias);
}

export function forgetLook(alias: string): void {
  looks.delete(alias);
  pending.delete(alias);
  announce(alias);
}

async function fetchLook(alias: string): Promise<LookData> {
  try {
    const r = await getLook(alias);
    return normalizeLook(r.look, alias, catalog);
  } catch {
    return defaultLook(alias, catalog);
  }
}

/** The agent's look: the default at once, the saved one as soon as the Runtime answers. */
export function useAgentLook(alias: string): LookData {
  const [look, setLook] = useState<LookData>(() => looks.get(alias) ?? defaultLook(alias, catalog));
  useEffect(() => {
    let cancelled = false;
    const known = looks.get(alias);
    if (known) setLook(known);
    else {
      let p = pending.get(alias);
      if (!p) {
        p = fetchLook(alias).then((l) => {
          looks.set(alias, l);
          pending.delete(alias);
          return l;
        });
        pending.set(alias, p);
      }
      void p.then((l) => {
        if (!cancelled) setLook(l);
      });
    }
    const onChange = (e: Event) => {
      if ((e as CustomEvent<string>).detail !== alias) return;
      const next = looks.get(alias);
      if (next) setLook(next);
      else void fetchLook(alias).then((l) => {
        looks.set(alias, l);
        if (!cancelled) setLook(l);
      });
    };
    const w = realWindow();
    w?.addEventListener(EVENT, onChange);
    return () => {
      cancelled = true;
      w?.removeEventListener(EVENT, onChange);
    };
  }, [alias]);
  return look;
}

/** The agent drawn wherever it appears: the list, the chat header and tabs,
 *  the bubbles, the Home tiles. `frame` holds it still; `decorative` hides it
 *  from assistive tech where the agent's name is already beside it. */
export function AgentLook({
  alias,
  size = 32,
  talking = false,
  frame,
  decorative = false,
  className,
}: {
  alias: string;
  size?: number;
  talking?: boolean;
  frame?: Frame;
  decorative?: boolean;
  className?: string;
}) {
  const look = useAgentLook(alias);
  return <Look look={look} size={size} talking={talking} frame={frame} decorative={decorative} className={className} title={decorative ? undefined : alias} />;
}
