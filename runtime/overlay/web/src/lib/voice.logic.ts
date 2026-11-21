// The agent's voice (vision M10 §10, slice P2b): the pure part. Which voice
// a device uses, what the dashboard offers the gateway, what a reply sounds
// like once the Markdown is gone, and the config ops for an ElevenLabs key.
// Pure, so the test runner can import it without React or the API client.
import type { PatchOp } from "@/lib/api";

export const ENGINES = ["browser", "phone", "elevenlabs"] as const;
export type Engine = (typeof ENGINES)[number];

/** `agents/<alias>/voice.json`, as the Runtime keeps it (caelza-tools voice.rs validates the same shape). */
export interface VoiceChoice {
  version: 1;
  engine: Engine;
  voice: string;
  name?: string;
  rate?: number;
  pitch?: number;
  /** The agent's own sentence on why this one, when it chose. */
  why?: string;
}

/** One voice a device or ElevenLabs offers (`POST /api/voice/offer`). */
export interface OfferedVoice {
  id: string;
  name: string;
  lang?: string;
  gender?: string;
  accent?: string;
  age?: string;
  description?: string;
}

/** What this device can do: speech synthesis (a PC browser), the app's bridge (the phone), the Runtime's ElevenLabs. */
export interface Here {
  browser: boolean;
  phone: boolean;
  elevenlabs: boolean;
}

/** The ElevenLabs model written beside the key: their documented default, every language. */
export const ELEVEN_MODEL = "eleven_multilingual_v2";
/** The config entry the Connect page writes (upstream's `[providers.tts.elevenlabs.<alias>]`). */
export const ELEVEN_PATH = "/providers/tts/elevenlabs/default";
export const ELEVEN_SECTION = "providers.tts.elevenlabs";
/** A reply longer than this is read up to its last sentence inside the cap (ElevenLabs bills by character). */
export const MAX_SPEAK_CHARS = 2000;
export const MAX_OFFERED = 200;

export function speakKey(alias: string): string {
  return `caelza:speak:${alias}`;
}

/** The browser's voices as the offer: ids are the voiceURI (stable per machine), local voices first, then the default. */
export function offerFromBrowser(
  voices: ReadonlyArray<{ name: string; lang: string; voiceURI: string; localService?: boolean; default?: boolean }>,
): OfferedVoice[] {
  const seen = new Set<string>();
  const out: OfferedVoice[] = [];
  const ordered = [...voices].sort((a, b) => {
    const local = Number(b.localService ?? true) - Number(a.localService ?? true);
    if (local) return local;
    return Number(b.default ?? false) - Number(a.default ?? false);
  });
  for (const v of ordered) {
    const id = (v.voiceURI || v.name).trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push({ id, name: v.name.trim() || id, lang: v.lang || undefined });
    if (out.length >= MAX_OFFERED) break;
  }
  return out;
}

/** The browser voice the choice names: by voiceURI, else by name; nothing when the choice is not a browser voice. */
export function pickBrowserVoice<T extends { name: string; voiceURI: string; lang: string }>(
  voices: readonly T[],
  choice: VoiceChoice | null | undefined,
): T | undefined {
  if (!choice || choice.engine !== "browser") return undefined;
  return (
    voices.find((v) => v.voiceURI === choice.voice) ??
    voices.find((v) => v.name === choice.voice) ??
    (choice.name ? voices.find((v) => v.name === choice.name) : undefined)
  );
}

/**
 * The engine this device reads aloud with: the chosen one where it works, else
 * the device's own (browser, then phone) in its default voice. Never ElevenLabs
 * unless the agent or owner chose it: that one costs.
 */
export function engineHere(choice: VoiceChoice | null | undefined, here: Here): Engine | null {
  if (choice && here[choice.engine]) return choice.engine;
  if (here.browser) return "browser";
  if (here.phone) return "phone";
  return null;
}

/** A reply as words: code, links, pictures and Markdown marks gone, capped at a sentence. */
export function speakable(markdown: string): string {
  let s = markdown.replace(/\r/g, "");
  s = s.replace(/```[\s\S]*?```/g, " (code) ");
  s = s.replace(/`([^`\n]*)`/g, "$1");
  s = s.replace(/!\[[^\]]*\]\([^)]*\)/g, " ");
  s = s.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
  s = s.replace(/https?:\/\/\S+/g, " (link) ");
  s = s.replace(/^\s{0,3}#{1,6}\s+/gm, "");
  s = s.replace(/^\s*>\s?/gm, "");
  s = s.replace(/^\s*[-*+]\s+/gm, "");
  s = s.replace(/^\s*\d+\.\s+/gm, "");
  s = s.replace(/^\s*[-:| ]+$/gm, "");
  s = s.replace(/\|/g, " ");
  s = s.replace(/(\*\*|__|~~|\*|_)/g, "");
  s = s
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trim())
    .filter((line) => line !== "")
    .join("\n");
  if (s.length > MAX_SPEAK_CHARS) {
    const cut = s.slice(0, MAX_SPEAK_CHARS);
    const end = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("! "), cut.lastIndexOf("? "), cut.lastIndexOf(".\n"));
    s = (end > MAX_SPEAK_CHARS / 2 ? cut.slice(0, end + 1) : cut).trim();
  }
  return s;
}

/** An ElevenLabs key looks like one: a single token, long enough. */
export function keyOk(key: string): boolean {
  const k = key.trim();
  return k.length >= 16 && !/\s/.test(k);
}

/** The config ops for the key: the entry's key and the model beside it (upstream defaults to a retired one). */
export function elevenOps(key: string): PatchOp[] {
  return [
    { op: "add", path: `${ELEVEN_PATH}/api_key`, value: key.trim() },
    { op: "add", path: `${ELEVEN_PATH}/model`, value: ELEVEN_MODEL },
  ];
}

/** `"engine:id"` as the Looks card's select has it, both ways. */
export function pickValue(choice: VoiceChoice | null | undefined): string {
  return choice ? `${choice.engine}:${choice.voice}` : "";
}

export function choiceFromPick(value: string, offered: ReadonlyArray<{ engine: Engine; voices: OfferedVoice[] }>): VoiceChoice | null {
  const i = value.indexOf(":");
  if (i <= 0) return null;
  const engine = value.slice(0, i) as Engine;
  const voice = value.slice(i + 1);
  if (!ENGINES.includes(engine) || !voice) return null;
  const name = offered.find((g) => g.engine === engine)?.voices.find((v) => v.id === voice)?.name;
  return { version: 1, engine, voice, ...(name ? { name } : {}) };
}

/** One line for the owner: the voice's name and where it comes from. */
export function voiceLine(choice: VoiceChoice | null | undefined, words: { none: string; browser: string; phone: string; elevenlabs: string }): string {
  if (!choice) return words.none;
  return `${choice.name ?? choice.voice} · ${words[choice.engine]}`;
}
