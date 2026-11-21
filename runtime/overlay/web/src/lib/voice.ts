// The voice, as the dashboard talks to the gateway about it (api_voice.rs):
// the agent's choice, what this device offers, the owner's ElevenLabs voices,
// and a reply as audio. `apiFetch` cannot return bytes, so `speakAudio` makes
// the one call by hand the way api.ts's personality PUT does.
import { apiFetch } from "./api";
import { clearToken, getToken } from "./auth";
import { apiOrigin, basePath } from "./basePath";
import type { Engine, OfferedVoice, VoiceChoice } from "./voice.logic";

export interface Offered {
  version: number;
  engines: Partial<Record<Engine, { voices: OfferedVoice[]; offered_at?: number; by?: string }>>;
}

export interface VoiceResponse {
  alias: string;
  voice: VoiceChoice | null;
}

export function getVoice(alias: string): Promise<VoiceResponse> {
  return apiFetch<VoiceResponse>(`/api/voice/${encodeURIComponent(alias)}`);
}

export function putVoice(alias: string, choice: VoiceChoice): Promise<VoiceResponse> {
  return apiFetch<VoiceResponse>(`/api/voice/${encodeURIComponent(alias)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(choice),
  });
}

export function deleteVoice(alias: string): Promise<VoiceResponse> {
  return apiFetch<VoiceResponse>(`/api/voice/${encodeURIComponent(alias)}`, { method: "DELETE" });
}

export function getOffered(): Promise<Offered> {
  return apiFetch<Offered>("/api/voice/offer");
}

/** What this device can speak with; the gateway keeps one list per engine. */
export function offerVoices(engine: "browser" | "phone", voices: OfferedVoice[], by: string): Promise<{ engine: string; count: number }> {
  return apiFetch<{ engine: string; count: number }>("/api/voice/offer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ engine, voices, by }),
  });
}

/** The owner's ElevenLabs voices (`configured: false` and an empty list without a key). */
export function getElevenLabsVoices(): Promise<{ configured: boolean; voices: OfferedVoice[] }> {
  return apiFetch<{ configured: boolean; voices: OfferedVoice[] }>("/api/voice/elevenlabs");
}

/** `text` in the agent's ElevenLabs voice (or `voice`), as an MP3 blob. */
export async function speakAudio(alias: string, text: string, voice?: string): Promise<Blob> {
  const token = getToken();
  const headers = new Headers({ "Content-Type": "application/json", Accept: "audio/mpeg" });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${apiOrigin}${basePath}/api/voice/${encodeURIComponent(alias)}/speak`, {
    method: "POST",
    headers,
    body: JSON.stringify(voice ? { text, voice } : { text }),
  });
  if (response.status === 401) {
    clearToken();
    window.dispatchEvent(new Event("caelza-unauthorized"));
    throw new Error("API 401: not signed in");
  }
  if (!response.ok) {
    let message = "";
    try {
      const body = (await response.json()) as { error?: string };
      message = body.error ?? "";
    } catch {
      message = await response.text().catch(() => "");
    }
    throw new Error(`API ${response.status}: ${message || response.statusText}`);
  }
  return response.blob();
}
