// The simplified setup (vision M4 phase 4a) with nothing React in it: the
// curated catalog's shape (bundle/models.json, copied beside this file by
// runtime/build.sh), what the two wheels show, how a key is judged, what gets
// staged in upstream's quickstart shape and the whole submission with our
// defaults. `node --experimental-strip-types --test setup.logic.test.ts` runs
// the tests, so this file stays plain TypeScript with no path aliases.

export type Tag = "best" | "fast" | "strong" | "free";

/** The tags in the order the wheel shows them (scripts/model_catalog.py TAGS). */
export const TAGS: readonly Tag[] = ["best", "fast", "strong", "free"];

export interface CatalogModel {
  id: string;
  label: string;
  tag?: Tag;
}

export interface CatalogProvider {
  /** The Runtime's provider kind (the key under providers.models). */
  id: string;
  label: string;
  /** The models.dev key when it differs from the kind (gemini → google). */
  models_dev?: string;
  /** How this provider's keys start; empty when they have no fixed start. */
  key_prefix: string;
  /** Where a key comes from. */
  key_page: string;
  models: CatalogModel[];
}

export interface Catalog {
  version: number;
  updated: string;
  providers: CatalogProvider[];
}

/** The screens, one decision each. */
export type Screen = "doors" | "local" | "provider" | "model" | "key" | "done";

/** The alias the key door writes: `<provider>.default`, the same one the app's first run writes. */
export const KEY_ALIAS = "default";

/** The agent the setup creates; the app's first run and model-setup.sh point `agents.main` too. */
export const AGENT_NAME = "main";

export interface ProviderRow {
  id: string;
  label: string;
  /** From the curated catalog (with picks) rather than only from the Runtime's list. */
  curated: boolean;
}

interface RuntimeType {
  kind: string;
  display_name: string;
  local: boolean;
}

/**
 * The provider wheel: the curated providers the Runtime lists (all of them
 * when the Runtime's list is not known yet), then, under "more", every other
 * key provider the Runtime knows, by name. Local runners are the other door.
 */
export function providerRows(
  catalog: Catalog,
  runtimeTypes: ReadonlyArray<RuntimeType> | null,
  more: boolean,
): ProviderRow[] {
  const known = runtimeTypes === null ? null : new Map(runtimeTypes.map((t) => [t.kind, t]));
  const rows: ProviderRow[] = [];
  for (const p of catalog.providers) {
    if (known !== null && !known.has(p.id)) continue;
    rows.push({ id: p.id, label: p.label, curated: true });
  }
  if (more && runtimeTypes !== null) {
    const curated = new Set(catalog.providers.map((p) => p.id));
    const rest = runtimeTypes
      .filter((t) => !t.local && !curated.has(t.kind))
      .sort((a, b) => a.display_name.localeCompare(b.display_name));
    for (const t of rest) rows.push({ id: t.kind, label: t.display_name, curated: false });
  }
  return rows;
}

export interface ModelRow {
  id: string;
  label: string;
  tag?: Tag;
  curated: boolean;
}

const tagRank = (tag?: Tag) => (tag ? TAGS.indexOf(tag) : TAGS.length);

/**
 * The model wheel: the curated picks first (tagged ones in tag order, then
 * the rest as listed), then everything the Runtime's live catalog offers
 * that is not already there, in the catalog's order. A provider with no
 * curated entry shows the live list alone.
 */
export function modelRows(provider: CatalogProvider | null, live: ReadonlyArray<string> | null): ModelRow[] {
  const rows: ModelRow[] = [];
  const seen = new Set<string>();
  if (provider) {
    const picks = provider.models
      .map((m, i) => ({ m, i }))
      .sort((a, b) => tagRank(a.m.tag) - tagRank(b.m.tag) || a.i - b.i);
    for (const { m } of picks) {
      if (seen.has(m.id)) continue;
      seen.add(m.id);
      rows.push({ id: m.id, label: m.label, tag: m.tag, curated: true });
    }
  }
  for (const id of live ?? []) {
    if (seen.has(id)) continue;
    seen.add(id);
    rows.push({ id, label: id, curated: false });
  }
  return rows;
}

/** Where the model wheel rests: the `best` pick, else the first row. */
export function defaultModel(rows: ReadonlyArray<ModelRow>): string {
  return (rows.find((r) => r.tag === "best") ?? rows[0])?.id ?? "";
}

export function providerById(catalog: Catalog, id: string): CatalogProvider | null {
  return catalog.providers.find((p) => p.id === id) ?? null;
}

/** `console.anthropic.com/settings/keys` for the sentence; the href keeps the URL. */
export function keyPageName(url: string): string {
  return url.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

interface FieldDescriptor {
  key: string;
  label?: string;
  is_secret: boolean;
  required: boolean;
  default?: string | null;
  enum_variants?: string[] | null;
}

/** Which of the daemon's fields holds the key: `api_key` when it is there, else the first secret. */
export function secretField<D extends FieldDescriptor>(descriptors: ReadonlyArray<D>): D | null {
  return descriptors.find((d) => d.key === "api_key") ?? descriptors.find((d) => d.is_secret) ?? null;
}

/** The other fields the daemon insists on (a custom endpoint's base URL), asked for under the key. */
export function extraRequiredFields<D extends FieldDescriptor>(descriptors: ReadonlyArray<D>): D[] {
  const secret = secretField(descriptors);
  return descriptors.filter(
    (d) => d.required && !d.is_secret && d.key !== "model" && d.key !== secret?.key && !(d.enum_variants && d.enum_variants.length > 0),
  );
}

export type KeyVerdict = { ok: true; warning: "prefix" | null } | { ok: false; reason: "empty" | "short" | "spaces" };

/**
 * A key is one long word; the provider says the rest when it is wrong. A
 * start that does not match the provider's usual one is a warning, not a
 * refusal: providers change their prefixes, owners paste the right key
 * into the wrong door, and the daemon's own check decides.
 */
export function judgeKey(key: string, prefix: string): KeyVerdict {
  const k = key.trim();
  if (k === "") return { ok: false, reason: "empty" };
  if (/\s/.test(k)) return { ok: false, reason: "spaces" };
  if (k.length < 16) return { ok: false, reason: "short" };
  return { ok: true, warning: prefix !== "" && !k.startsWith(prefix) ? "prefix" : null };
}

/** Upstream's staged shape (Quickstart.tsx `StagedProvider`). */
export interface StagedProvider {
  provider_type: string;
  alias: string;
  model: string;
  fields: Record<string, string>;
}

/** What the key door stages: `<provider>.default` on the chosen model, the key under the daemon's field. */
export function stagedKeyProvider(
  providerId: string,
  model: string,
  secretKey: string | null,
  key: string,
  extra: Record<string, string> = {},
): StagedProvider {
  const fields: Record<string, string> = {};
  for (const [k, v] of Object.entries(extra)) {
    const trimmed = v.trim();
    if (trimmed !== "") fields[k] = trimmed;
  }
  if (secretKey) fields[secretKey] = key.trim();
  return { provider_type: providerId, alias: KEY_ALIAS, model: model.trim(), fields };
}

interface Preset {
  preset_name: string;
}

interface StateForDefaults {
  agents: ReadonlyArray<string>;
  default_runtime_profile?: string | null;
  model_provider_types: ReadonlyArray<{ kind: string; default_runtime_profile?: string | null }>;
  risk_presets: ReadonlyArray<Preset>;
  runtime_presets: ReadonlyArray<Preset>;
  memory_kinds: ReadonlyArray<string>;
}

/** The preset by name when the daemon lists it, else the first listed, else the name anyway. */
export function pickPreset(presets: ReadonlyArray<Preset>, want: string): string {
  if (presets.some((p) => p.preset_name === want)) return want;
  return presets[0]?.preset_name ?? want;
}

/** sqlite when the daemon offers it (the phone default), else the first kind, never "none" while another exists. */
export function pickMemory(kinds: ReadonlyArray<string>): string {
  if (kinds.includes("sqlite")) return "sqlite";
  return kinds.find((k) => k !== "none") ?? kinds[0] ?? "sqlite";
}

/** The runtime profile the daemon recommends for the provider, else its default, else balanced. */
export function pickRuntime(state: StateForDefaults, providerType: string): string {
  const advertised = state.model_provider_types.find((t) => t.kind === providerType)?.default_runtime_profile;
  return advertised ?? state.default_runtime_profile ?? pickPreset(state.runtime_presets, "balanced");
}

/** `main`, or the first of main2, main3… that is free when main exists already. */
export function agentName(existing: ReadonlyArray<string>): string {
  if (!existing.includes(AGENT_NAME)) return AGENT_NAME;
  for (let n = 2; n < 100; n++) {
    const name = `${AGENT_NAME}${n}`;
    if (!existing.includes(name)) return name;
  }
  return `${AGENT_NAME}-${Date.now().toString(36)}`;
}

/** The whole submission, upstream's `/api/quickstart/apply` shape, with our defaults for everything the owner was not asked. */
export function submission(state: StateForDefaults, provider: StagedProvider) {
  return {
    model_provider: { mode: "fresh" as const, value: provider },
    risk_profile: { mode: "fresh" as const, value: pickPreset(state.risk_presets, "balanced") },
    runtime_profile: { mode: "fresh" as const, value: pickRuntime(state, provider.provider_type) },
    memory: { mode: "fresh" as const, value: pickMemory(state.memory_kinds) },
    channels: [] as unknown[],
    peer_groups: [] as unknown[],
    agent: {
      name: agentName(state.agents),
      system_prompt: "",
      personality_file: null,
      personality_files: [] as unknown[],
    },
  };
}

/** The daemon's errors as one line each, the field named when it helps. */
export function errorLines(errors: ReadonlyArray<{ step: string; field: string; message: string }>): string[] {
  return errors.map((e) => (e.field && e.field !== "-" ? `${e.field}: ${e.message}` : e.message));
}

/** Fill `{name}` holes in a translated string. */
export function fill(text: string, vars: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));
}
