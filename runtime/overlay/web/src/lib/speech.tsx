// The agent speaks (vision M10 §10, slice P2b): the dashboard reads replies
// aloud in the agent's voice. Three ways to make sound, picked per device by
// voice.logic's `engineHere`: the browser's own speech synthesis (a PC), the
// Caelza app's bridge to the phone's text-to-speech (`window.caelzaVoice`;
// Android's WebView has no speechSynthesis), or an MP3 from the Runtime in an
// ElevenLabs voice. One state per agent (on or off, speaking or not, the
// choice) lives here so the chat header's toggle and the look's mouth agree.
import { useEffect, useState } from "react";
import { Volume2, VolumeX } from "lucide-react";

import { t } from "@/lib/i18n";
import { getVoice, offerVoices, speakAudio } from "@/lib/voice";
import {
  type Engine,
  type Here,
  type OfferedVoice,
  type VoiceChoice,
  engineHere,
  offerFromBrowser,
  pickBrowserVoice,
  speakKey,
  speakable,
} from "@/lib/voice.logic";

declare global {
  interface Window {
    /** The Caelza app's bridge to the phone's text-to-speech (android VoiceBridge.kt). */
    caelzaVoice?: {
      voices(): string;
      speak(text: string, voice: string, rate: number, pitch: number): boolean;
      stop(): void;
    };
  }
}

interface State {
  enabled: boolean;
  speaking: boolean;
  choice: VoiceChoice | null;
  loaded: boolean;
}

const states = new Map<string, State>();
const listeners = new Set<() => void>();

function readEnabled(alias: string): boolean {
  try {
    return localStorage.getItem(speakKey(alias)) === "1";
  } catch {
    return false;
  }
}

function get(alias: string): State {
  let s = states.get(alias);
  if (!s) {
    s = { enabled: readEnabled(alias), speaking: false, choice: null, loaded: false };
    states.set(alias, s);
  }
  return s;
}

function patch(alias: string, p: Partial<State>): void {
  states.set(alias, { ...get(alias), ...p });
  for (const l of listeners) l();
}

/** What this device can do. ElevenLabs is the Runtime's: the gateway says no when there is no key. */
export function here(): Here {
  const w = typeof window === "undefined" ? undefined : window;
  return {
    browser: !!w && "speechSynthesis" in w && typeof w.SpeechSynthesisUtterance === "function",
    phone: typeof w?.caelzaVoice?.speak === "function",
    elevenlabs: true,
  };
}

/** The browser's voices, waiting once for `voiceschanged` (Chrome fills the list late). */
export function browserVoices(): Promise<SpeechSynthesisVoice[]> {
  if (!here().browser) return Promise.resolve([]);
  const now = speechSynthesis.getVoices();
  if (now.length) return Promise.resolve(now);
  return new Promise((resolve) => {
    const done = () => {
      speechSynthesis.removeEventListener("voiceschanged", done);
      resolve(speechSynthesis.getVoices());
    };
    speechSynthesis.addEventListener("voiceschanged", done);
    setTimeout(done, 1500);
  });
}

/** The phone's voices from the app's bridge, as the offer. */
export function phoneVoices(): OfferedVoice[] {
  const bridge = window.caelzaVoice;
  if (!bridge) return [];
  try {
    const list = JSON.parse(bridge.voices()) as unknown;
    return Array.isArray(list)
      ? list.filter((v): v is OfferedVoice => !!v && typeof v === "object" && typeof (v as OfferedVoice).id === "string")
      : [];
  } catch {
    return [];
  }
}

/** This device's own voices, with the engine they belong to; null when it has none. */
export async function localVoices(): Promise<{ engine: "browser" | "phone"; voices: OfferedVoice[] } | null> {
  const h = here();
  if (h.phone) return { engine: "phone", voices: phoneVoices() };
  if (h.browser) return { engine: "browser", voices: offerFromBrowser(await browserVoices()) };
  return null;
}

let offered = false;
/** Tell the gateway what this device can speak with, once per page load, so the agent's `voice` tool can list it. */
export async function offerOnce(): Promise<void> {
  if (offered) return;
  offered = true;
  try {
    const local = await localVoices();
    if (local && local.voices.length) await offerVoices(local.engine, local.voices, local.engine === "phone" ? "app" : "dashboard");
  } catch {
    offered = false;
  }
}

async function loadChoice(alias: string): Promise<void> {
  if (get(alias).loaded) return;
  try {
    const r = await getVoice(alias);
    patch(alias, { choice: r.voice, loaded: true });
  } catch {
    patch(alias, { loaded: true });
  }
}

/** The Looks page saved a voice: every speaker uses it from now. */
export function rememberVoice(alias: string, choice: VoiceChoice | null): void {
  patch(alias, { choice, loaded: true });
}

/** The sound being made right now, if any; `token` tells a stale utterance's callbacks from the live one's. */
let active: { alias: string; token: object; cancel(): void } | null = null;

/** Stop whatever is being said. */
export function stop(): void {
  const a = active;
  active = null;
  if (!a) return;
  a.cancel();
  patch(a.alias, { speaking: false });
}

/**
 * Say `text` for `alias`: in the saved choice, or in `override` (the Looks
 * page's "Hear it" before saving). Resolves when the device starts or refuses;
 * `speaking` in the state follows the sound.
 */
export async function speak(alias: string, text: string, override?: VoiceChoice | null): Promise<void> {
  const clean = speakable(text);
  if (!clean) return;
  const choice = override === undefined ? get(alias).choice : override;
  const h = here();
  const engine: Engine | null = engineHere(choice, h);
  if (!engine) return;
  stop();
  const token = {};
  const begin = (cancel: () => void) => {
    active = { alias, token, cancel };
    patch(alias, { speaking: true });
  };
  // Only the live utterance ends the speaking state: a cancelled one's late callbacks are ignored.
  const finish = () => {
    if (active?.token !== token) return;
    active = null;
    patch(alias, { speaking: false });
  };
  if (engine === "browser") {
    const utterance = new SpeechSynthesisUtterance(clean);
    const voice = pickBrowserVoice(speechSynthesis.getVoices(), choice);
    if (voice) utterance.voice = voice;
    if (choice?.engine === "browser") {
      if (choice.rate) utterance.rate = choice.rate;
      if (choice.pitch) utterance.pitch = choice.pitch;
    }
    utterance.onend = finish;
    utterance.onerror = finish;
    begin(() => speechSynthesis.cancel());
    speechSynthesis.speak(utterance);
    return;
  }
  if (engine === "phone") {
    const bridge = window.caelzaVoice;
    if (!bridge) return;
    const onEvent = (e: Event) => {
      const detail = (e as CustomEvent<{ state?: string }>).detail;
      if (detail?.state === "done" || detail?.state === "error") {
        window.removeEventListener("caelza-voice", onEvent);
        finish();
      }
    };
    window.addEventListener("caelza-voice", onEvent);
    begin(() => {
      window.removeEventListener("caelza-voice", onEvent);
      bridge.stop();
    });
    const id = choice?.engine === "phone" ? choice.voice : "";
    if (!bridge.speak(clean, id, choice?.rate ?? 1, choice?.pitch ?? 1)) {
      window.removeEventListener("caelza-voice", onEvent);
      finish();
    }
    return;
  }
  // ElevenLabs: the Runtime makes the sound; the voice id rides along so a preview needs no save.
  let audio: HTMLAudioElement | null = null;
  let cancelled = false;
  begin(() => {
    cancelled = true;
    audio?.pause();
  });
  try {
    const blob = await speakAudio(alias, clean, choice?.engine === "elevenlabs" ? choice.voice : undefined);
    if (cancelled || active?.token !== token) return;
    const url = URL.createObjectURL(blob);
    audio = new Audio(url);
    const end = () => {
      URL.revokeObjectURL(url);
      finish();
    };
    audio.onended = end;
    audio.onerror = end;
    await audio.play();
  } catch {
    finish();
  }
}

let listening = false;
/** One listener for the replies the chat commits (AgentContext dispatches `caelza-agent-reply`). */
function ensureListener(): void {
  if (listening || typeof window === "undefined") return;
  listening = true;
  window.addEventListener("caelza-agent-reply", (e: Event) => {
    const detail = (e as CustomEvent<{ alias?: string; content?: string }>).detail;
    if (!detail?.alias || !detail.content) return;
    const alias = detail.alias;
    const content = detail.content;
    if (!get(alias).enabled) return;
    void loadChoice(alias).then(() => speak(alias, content));
  });
}

export interface Speech {
  /** Replies are read aloud for this agent (the owner's toggle, kept per device). */
  enabled: boolean;
  speaking: boolean;
  choice: VoiceChoice | null;
  /** This device can make a sound for this agent at all. */
  available: boolean;
  setEnabled(on: boolean): void;
  speak(text: string, override?: VoiceChoice | null): Promise<void>;
  stop(): void;
}

export function useSpeech(alias: string): Speech {
  const [, force] = useState(0);
  useEffect(() => {
    ensureListener();
    void offerOnce();
    void loadChoice(alias);
    const l = () => force((n) => n + 1);
    listeners.add(l);
    return () => {
      listeners.delete(l);
    };
  }, [alias]);
  const s = get(alias);
  return {
    enabled: s.enabled,
    speaking: s.speaking,
    choice: s.choice,
    available: engineHere(s.choice, here()) !== null,
    setEnabled(on: boolean) {
      try {
        localStorage.setItem(speakKey(alias), on ? "1" : "0");
      } catch {
        /* a private window: the toggle lasts the page */
      }
      patch(alias, { enabled: on });
      if (!on) stop();
    },
    speak: (text: string, override?: VoiceChoice | null) => speak(alias, text, override),
    stop,
  };
}

/** The chat header's speaker: on, replies are read aloud; shown only where this device can speak. */
export function SpeakToggle({ alias }: { alias: string }) {
  const s = useSpeech(alias);
  if (!s.available) return null;
  return (
    <button
      type="button"
      onClick={() => s.setEnabled(!s.enabled)}
      aria-pressed={s.enabled}
      title={t(s.enabled ? "voice.read_on" : "voice.read_off")}
      aria-label={t(s.enabled ? "voice.read_on" : "voice.read_off")}
      className="inline-flex items-center justify-center h-7 w-7 rounded-[var(--radius-md)] border border-pc-border bg-pc-elevated text-pc-text-secondary transition-colors hover:text-pc-text hover:border-pc-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--pc-focus)]"
      data-speak-toggle={s.enabled ? "on" : "off"}
    >
      {s.enabled ? <Volume2 className="h-3.5 w-3.5" aria-hidden="true" /> : <VolumeX className="h-3.5 w-3.5" aria-hidden="true" />}
    </button>
  );
}
