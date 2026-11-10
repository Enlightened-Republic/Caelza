// Ollama from the browser: the "free and local" door on a PC (vision M4 phase
// 4a, the PC leg). The dashboard runs on 127.0.0.1:42617 and Ollama on
// 127.0.0.1:11434; Ollama's default CORS list allows every localhost origin, so
// the page asks it directly: GET /api/tags for what is pulled, POST /api/pull
// (streamed NDJSON) for the download, no gateway route in between. Nothing
// React here; `node --experimental-strip-types --test ollama.logic.test.ts`
// runs the tests, so this file stays plain TypeScript with no path aliases.

export const OLLAMA_URL = "http://127.0.0.1:11434";
export const OLLAMA_DOWNLOAD_PAGE = "https://ollama.com/download";

/** Only a page open on the computer itself can see that computer's Ollama, and
 * only from the two origins Ollama's default CORS list allows (`localhost` and
 * `127.0.0.1` on any port; not `[::1]`, not `*.localhost`). Elsewhere the page
 * says to open http://127.0.0.1:42617 instead of probing into a refusal. */
export function onThisComputer(hostname: string): boolean {
  const h = hostname.toLowerCase();
  return h === "localhost" || h === "127.0.0.1";
}

/** The names /api/tags lists: `{ models: [{ name: "deepseek-r1:1.5b", … }] }`. */
export function tagNames(body: unknown): string[] {
  if (typeof body !== "object" || body === null) return [];
  const models = (body as { models?: unknown }).models;
  if (!Array.isArray(models)) return [];
  const out: string[] = [];
  for (const m of models) {
    const name = typeof m === "object" && m !== null ? (m as { name?: unknown }).name : undefined;
    if (typeof name === "string" && name !== "") out.push(name);
  }
  return out;
}

function withTag(name: string): string {
  return name.includes(":") ? name : `${name}:latest`;
}

/** `deepseek-r1:1.5b` is pulled when the list has it; a bare `llama3` means `llama3:latest`. */
export function hasModel(names: readonly string[], model: string): boolean {
  const want = withTag(model.trim());
  return names.some((n) => withTag(n) === want);
}

/** The models the pick needs that Ollama has not got, each once, the agent's first. */
export function missingModels(names: readonly string[], wanted: readonly string[]): string[] {
  const out: string[] = [];
  for (const w of wanted) if (!hasModel(names, w) && !out.includes(w)) out.push(w);
  return out;
}

/** About how big each ladder tag is to download, from Ollama's library pages (GB). */
export const APPROX_GB: Readonly<Record<string, number>> = {
  "deepseek-r1:1.5b": 1.1,
  "deepseek-r1:7b": 4.7,
  "deepseek-r1:8b": 4.9,
  "deepseek-r1:14b": 9.0,
};

/** The download these models add up to, one decimal; null when one is not in the table. */
export function approxGb(models: readonly string[]): number | null {
  let sum = 0;
  for (const m of models) {
    const gb = APPROX_GB[m];
    if (gb === undefined) return null;
    sum += gb;
  }
  return Math.round(sum * 10) / 10;
}

/** Bytes as the owner reads them: "0.4 GB", "4.7 GB". */
export function gbOf(bytes: number): string {
  return `${(Math.max(0, bytes) / 1e9).toFixed(1)} GB`;
}

/** One line of /api/pull's stream. */
export interface PullEvent {
  status: string;
  digest?: string;
  total?: number;
  completed?: number;
  error?: string;
}

function toEvent(v: Record<string, unknown>): PullEvent {
  const e: PullEvent = { status: typeof v.status === "string" ? v.status : "" };
  if (typeof v.digest === "string") e.digest = v.digest;
  if (typeof v.total === "number") e.total = v.total;
  if (typeof v.completed === "number") e.completed = v.completed;
  if (typeof v.error === "string" && v.error !== "") e.error = v.error;
  return e;
}

/** NDJSON as it arrives: whole lines become events, the unfinished tail is kept for the next chunk. */
export function parsePullChunk(buffer: string): { events: PullEvent[]; rest: string } {
  const lines = buffer.split("\n");
  const rest = lines.pop() ?? "";
  const events: PullEvent[] = [];
  for (const line of lines) {
    const s = line.trim();
    if (s === "") continue;
    try {
      const v: unknown = JSON.parse(s);
      if (typeof v === "object" && v !== null && !Array.isArray(v)) events.push(toEvent(v as Record<string, unknown>));
    } catch {
      // A torn line is not an event.
    }
  }
  return { events, rest };
}

/** 0 to 100 while a layer downloads; null while Ollama is still starting, verifying or writing. */
export function percent(e: PullEvent | null): number | null {
  if (!e || typeof e.total !== "number" || e.total <= 0 || typeof e.completed !== "number") return null;
  return Math.max(0, Math.min(100, Math.floor((e.completed / e.total) * 100)));
}

export type PullStage = "starting" | "downloading" | "checking" | "finishing" | "done";

/** Ollama's status lines ("pulling manifest", "pulling 6340a3d7…", "verifying sha256 digest",
 * "writing manifest", "success") as the five words the page shows. */
export function stage(e: PullEvent | null): PullStage {
  if (!e) return "starting";
  if (e.status === "success") return "done";
  if (e.status.startsWith("verifying")) return "checking";
  if (e.status.startsWith("writing") || e.status.startsWith("removing")) return "finishing";
  if (e.status.startsWith("pulling") && percent(e) !== null) return "downloading";
  return "starting";
}

/** What Ollama has pulled, or null when nothing answers at its port (not installed, not running). */
export async function listModels(timeoutMs = 3000, base = OLLAMA_URL): Promise<string[] | null> {
  try {
    const res = await fetch(`${base}/api/tags`, { signal: AbortSignal.timeout(timeoutMs) });
    if (!res.ok) return null;
    return tagNames(await res.json());
  } catch {
    return null;
  }
}

/** Pull one model, reporting every event; resolves on Ollama's `success`, rejects on its
 * error line, a bad status, a stream that ends early, or the signal's abort. */
export async function pullModel(
  name: string,
  onEvent: (e: PullEvent) => void,
  signal?: AbortSignal,
  base = OLLAMA_URL,
): Promise<void> {
  const res = await fetch(`${base}/api/pull`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, stream: true }),
    signal,
  });
  if (!res.ok || !res.body) {
    await res.body?.cancel().catch(() => {});
    throw new Error(`Ollama answered ${res.status} to the download of ${name}.`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let done = false;
  for (;;) {
    const { value, done: end } = await reader.read();
    buffer += decoder.decode(value, { stream: !end });
    const parsed = parsePullChunk(end ? `${buffer}\n` : buffer);
    buffer = parsed.rest;
    for (const e of parsed.events) {
      if (e.error) {
        // Ollama's own refusal ends the pull: the stream is let go, not left open.
        await reader.cancel().catch(() => {});
        throw new Error(e.error);
      }
      onEvent(e);
      if (e.status === "success") done = true;
    }
    if (end) break;
  }
  if (!done) throw new Error(`The download of ${name} stopped before Ollama said it was complete.`);
}
