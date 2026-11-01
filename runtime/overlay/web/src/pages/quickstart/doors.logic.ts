// The two doors of quickstart's first screen (vision §3.4): free and local, or
// bring your own key. This is the local door with nothing React in it: the
// honest ladder of scripts/model_ladder.py mirrored here (pinned by
// tests/test_quickstart_doors.py), what the door stages, and what a browser
// can guess about the device. The key door is upstream's provider form as it
// was. `node --experimental-strip-types --test doors.logic.test.ts` runs the
// tests, so this file stays plain TypeScript with no path aliases.

export type Door = "local" | "key";
export type Runner = "llamacpp" | "ollama";
export type RamBand = "small" | "phone" | "medium" | "large";

/** The DeepSeek R1 builds the ladder hands out, named as the Runtime's `model = …` takes them. */
export const LADDER: Record<Runner, Record<string, string>> = {
  llamacpp: {
    "1.5b": "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M",
    "7b": "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M",
  },
  ollama: {
    "1.5b": "deepseek-r1:1.5b",
    "7b": "deepseek-r1:7b",
    "8b": "deepseek-r1:8b",
    "14b": "deepseek-r1:14b",
  },
};

/** Cael's tier: always the 1.5B, on every device. */
export const GUIDE_TIER = "1.5b";

/** The alias the ladder writes for the agent's model (`<runner>.local`); Cael's is `<runner>.guide`. */
export const LOCAL_ALIAS = "local";

/** The RAM the door asks about, as the ladder sees it: MB at the band's floor. */
export const RAM_BANDS: ReadonlyArray<{ id: RamBand; mb: number }> = [
  { id: "small", mb: 4 * 1024 },
  { id: "phone", mb: 6 * 1024 },
  { id: "medium", mb: 8 * 1024 },
  { id: "large", mb: 16 * 1024 },
];

export interface LocalPick {
  runner: Runner;
  tier: string;
  /** The agent's model. */
  model: string;
  /** Cael's model. */
  guide: string;
  /** The ladder's honest lines, word for word. */
  notes: string[];
}

function named(runner: Runner, tier: string): string {
  return LADDER[runner][tier] ?? tier;
}

/** scripts/model_ladder.py `pick`: a phone runs llama.cpp, a hub runs Ollama. */
export function localPick(runner: Runner, ramMb: number): LocalPick {
  const notes: string[] = [];
  let tier: string;
  if (runner === "llamacpp") {
    if (ramMb >= 6 * 1024) {
      tier = "7b";
      notes.push("7B Q4 on a phone is tight: keep context short (the server runs with -c 4096)");
    } else {
      tier = GUIDE_TIER;
      notes.push(
        "<= 5 GB RAM: the 1.5B is for chat and explanation; not reliable for multi-step tool calls. Bring a provider key for the agent loop",
      );
    }
    if (tier !== GUIDE_TIER) {
      notes.push(
        "one llama-server at a time: the agent model is served on :8080; Cael shares it unless you run a second server for the guide",
      );
    }
  } else if (ramMb >= 16 * 1024) {
    tier = "14b";
  } else if (ramMb >= 8 * 1024) {
    tier = "8b";
    notes.push("8-12 GB: 8b. 14b needs 16 GB");
  } else {
    tier = ramMb >= 6 * 1024 ? "7b" : GUIDE_TIER;
    notes.push("under 8 GB on a hub: expect slow turns; a provider key is the better agent brain");
  }
  return { runner, tier, model: named(runner, tier), guide: named(runner, GUIDE_TIER), notes };
}

export function bandMb(band: RamBand): number {
  return RAM_BANDS.find((b) => b.id === band)?.mb ?? 4 * 1024;
}

/** The shape upstream's quickstart stages for a model provider. */
export interface StagedLocalProvider {
  provider_type: string;
  alias: string;
  model: string;
  fields: Record<string, string>;
}

/** What the local door stages: the alias scripts/model-setup.sh and the app's first run write. */
export function stagedLocalProvider(
  runner: Runner,
  model: string,
  fields: Record<string, string> = {},
): StagedLocalProvider {
  return { provider_type: runner, alias: LOCAL_ALIAS, model: model.trim(), fields };
}

/** Which door a staged provider came through, for the section's summary. */
export function doorOf(p: { provider_type: string; alias: string }): Door {
  return p.alias === LOCAL_ALIAS && p.provider_type in LADDER ? "local" : "key";
}

/** Upstream's provider form seeds its field buffer this way: an enum row is
 * real state the daemon expects back (its default, else the first variant), a
 * text row stays empty so the daemon's own default applies. */
export function seedFieldValues(
  descriptors: ReadonlyArray<{ key: string; default?: string | null; enum_variants?: string[] | null }>,
): Record<string, string> {
  const next: Record<string, string> = {};
  for (const d of descriptors) {
    next[d.key] =
      d.enum_variants && d.enum_variants.length > 0 ? (d.default ?? d.enum_variants[0] ?? "") : "";
  }
  return next;
}

/** Only what was set, trimmed: the shape the apply call takes. */
export function nonEmptyFields(values: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(values)) {
    const trimmed = value.trim();
    if (trimmed !== "") out[key] = trimmed;
  }
  return out;
}

/** A browser's guess, with the pickers still showing: an Android user agent is
 * a phone (llama.cpp), anything else a hub (Ollama); `navigator.deviceMemory`
 * (Chromium only, rounded down to a power of two and capped at 8) picks the
 * band when it is there, so a big machine starts at 8b and may go up. */
export function guessDefaults(
  userAgent: string,
  deviceMemoryGb?: number | null,
): { runner: Runner; band: RamBand } {
  const runner: Runner = /android/i.test(userAgent) ? "llamacpp" : "ollama";
  let band: RamBand = runner === "llamacpp" ? "small" : "medium";
  if (typeof deviceMemoryGb === "number" && deviceMemoryGb > 0) {
    band =
      deviceMemoryGb >= 16 ? "large" : deviceMemoryGb >= 8 ? "medium" : deviceMemoryGb >= 6 ? "phone" : "small";
  }
  return { runner, band };
}
