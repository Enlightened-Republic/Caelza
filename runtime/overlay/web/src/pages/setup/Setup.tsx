// The simplified setup (vision M4 phase 4a): Cael leads, one screen at a
// time, in our colours. The two doors of §3.4 first; behind "bring your own
// key" a wheel of providers, a wheel of that provider's models with Cael's
// picks pinned on top, one box for the key, then "Try it". Behind "free and
// local" the ladder's pick for this device. Everything the owner is not
// asked (risk, runtime, memory, the agent's name) takes a default, and the
// whole thing goes through upstream's /api/quickstart/apply, so the result
// is exactly what the full wizard (still at /quickstart, "Advanced setup")
// would have written. Phone-first: one column, 52 px buttons, 390 px wide.
// On a PC the local door goes all the way: the page asks the computer's own
// Ollama what it has (ollama.logic), offers its download page when it is not
// there, pulls the missing model with a progress bar, then applies.
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Download, Eye, EyeOff, ExternalLink, KeyRound, Sparkles } from "lucide-react";

import {
  getCatalogModels,
  getQuickstartState,
  quickstartApply,
  quickstartFields,
  type ModelsResponse,
  type QuickstartFieldDescriptor,
  type QuickstartState,
} from "@/lib/api";
import { basePath } from "@/lib/basePath";
import { t } from "@/lib/i18n";
import { Eyebrow, Mark, Wordmark } from "@/components/brand/CaelzaLockup";
import {
  LOCAL_ALIAS,
  RAM_BANDS,
  bandMb,
  guessDefaults,
  localPick,
  nonEmptyFields,
  seedFieldValues,
  stagedLocalProvider,
  type RamBand,
  type Runner,
} from "../quickstart/doors.logic";
import {
  defaultModel,
  errorLines,
  extraRequiredFields,
  fill,
  judgeKey,
  keyPageName,
  modelRows,
  providerAlias,
  providerById,
  providerRows,
  secretField,
  stagedKeyProvider,
  submission,
  type Catalog,
  type Screen,
  type StagedProvider,
  type Tag,
} from "./setup.logic";
import {
  OLLAMA_DOWNLOAD_PAGE,
  approxGb,
  gbOf,
  listModels,
  missingModels,
  onThisComputer,
  percent,
  pullModel,
  stage,
  type PullEvent,
  type PullStage,
} from "./ollama.logic";
import { WheelPicker } from "./WheelPicker";
import catalogJson from "./models.json";

const catalog = catalogJson as unknown as Catalog;

const TAG_KEYS: Record<Tag, string> = {
  best: "setup.tag_best",
  fast: "setup.tag_fast",
  strong: "setup.tag_strong",
  free: "setup.tag_free",
};
const BAND_KEYS: Record<RamBand, string> = {
  small: "quickstart.door_ram_small",
  phone: "quickstart.door_ram_phone",
  medium: "quickstart.door_ram_medium",
  large: "quickstart.door_ram_large",
};
const STAGE_KEYS: Record<PullStage, string> = {
  starting: "setup.ollama_stage_starting",
  downloading: "setup.ollama_stage_downloading",
  checking: "setup.ollama_stage_checking",
  finishing: "setup.ollama_stage_finishing",
  done: "setup.ollama_stage_done",
};

/** What the page knows about the computer's Ollama: not asked yet, asking, nothing at its port, or what it has. */
type OllamaProbe = "idle" | "checking" | "missing" | "ready";

/** One model's download, as the progress bar shows it. */
interface Pull {
  name: string;
  n: number;
  total: number;
  event: PullEvent | null;
}

/** What the daemon would answer before it has: enough for the defaults. */
const EMPTY_STATE = {
  agents: [] as string[],
  default_runtime_profile: null,
  model_provider_types: [] as QuickstartState["model_provider_types"],
  risk_presets: [] as QuickstartState["risk_presets"],
  runtime_presets: [] as QuickstartState["runtime_presets"],
  memory_kinds: [] as string[],
};

interface Done {
  agent: string;
  provider: StagedProvider;
  guide?: string;
}

export default function Setup() {
  const navigate = useNavigate();
  const [state, setState] = useState<QuickstartState | null>(null);
  const [stateFailed, setStateFailed] = useState(false);
  const [screen, setScreen] = useState<Screen>("doors");
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [done, setDone] = useState<Done | null>(null);

  // The key door.
  const [more, setMore] = useState(false);
  const [providerId, setProviderId] = useState(catalog.providers[0]?.id ?? "");
  const [live, setLive] = useState<ModelsResponse | null>(null);
  const [descriptors, setDescriptors] = useState<QuickstartFieldDescriptor[]>([]);
  const [fieldSeed, setFieldSeed] = useState<Record<string, string>>({});
  const [model, setModel] = useState("");
  const [typed, setTyped] = useState(false);
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [extra, setExtra] = useState<Record<string, string>>({});

  // The local door.
  const guess = useMemo(() => {
    if (typeof navigator === "undefined") return guessDefaults("");
    const nav = navigator as Navigator & { deviceMemory?: number };
    return guessDefaults(nav.userAgent, nav.deviceMemory ?? null);
  }, []);
  const [runner, setRunner] = useState<Runner>(guess.runner);
  const [band, setBand] = useState<RamBand>(guess.band);
  const [localSeed, setLocalSeed] = useState<Record<string, string>>({});
  const pick = useMemo(() => localPick(runner, bandMb(band)), [runner, band]);

  // Ollama, asked directly when this page is open on the computer itself.
  const here = useMemo(() => typeof window !== "undefined" && onThisComputer(window.location.hostname), []);
  const [ollama, setOllama] = useState<OllamaProbe>("idle");
  const [pulled, setPulled] = useState<string[]>([]);
  const [probe, setProbe] = useState(0);
  const [pull, setPull] = useState<Pull | null>(null);
  const pullAbort = useRef<AbortController | null>(null);
  const asksOllama = here && runner === "ollama";
  const wanted = useMemo(() => (pick.model === pick.guide ? [pick.model] : [pick.model, pick.guide]), [pick]);
  const missing = useMemo(() => missingModels(pulled, wanted), [pulled, wanted]);
  const missingGb = useMemo(() => approxGb(missing), [missing]);

  useEffect(() => {
    if (!asksOllama || screen !== "local") return;
    let cancelled = false;
    setOllama("checking");
    void listModels().then((names) => {
      if (cancelled) return;
      setPulled(names ?? []);
      setOllama(names === null ? "missing" : "ready");
    });
    return () => {
      cancelled = true;
    };
  }, [asksOllama, screen, probe]);

  // Leaving the page stops a download; Ollama keeps the layers it got and resumes next time.
  useEffect(() => () => pullAbort.current?.abort(), []);

  useEffect(() => {
    let cancelled = false;
    getQuickstartState()
      .then((s) => {
        if (!cancelled) setState(s);
      })
      .catch(() => {
        if (!cancelled) setStateFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // The chosen provider's fields (which one is the key, what else it needs)
  // and its live model list, which needs a key to be live for most providers.
  useEffect(() => {
    if (!providerId) return;
    let cancelled = false;
    setLive(null);
    setTyped(false);
    setExtra({});
    // A key pasted for one provider never rides along to the next one.
    setKey("");
    setShowKey(false);
    void (async () => {
      try {
        const f = await quickstartFields({ section: "model_provider", type_key: providerId });
        if (!cancelled) {
          setDescriptors(f.fields);
          setFieldSeed(seedFieldValues(f.fields));
        }
      } catch {
        if (!cancelled) {
          setDescriptors([]);
          setFieldSeed({});
        }
      }
      try {
        const r = await getCatalogModels(providerId);
        if (!cancelled) setLive(r);
      } catch {
        if (!cancelled) setLive(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [providerId]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const f = await quickstartFields({ section: "model_provider", type_key: runner });
        if (!cancelled) setLocalSeed(seedFieldValues(f.fields));
      } catch {
        if (!cancelled) setLocalSeed({});
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runner]);

  const provider = providerById(catalog, providerId);
  const providerLabel =
    provider?.label ?? state?.model_provider_types.find((p) => p.kind === providerId)?.display_name ?? providerId;
  const pRows = useMemo(() => providerRows(catalog, state?.model_provider_types ?? null, more), [state, more]);
  const mRows = useMemo(() => modelRows(provider, live?.live ? live.models : null), [provider, live]);

  // The model wheel rests on the pick when the provider changes. The live list
  // lands seconds later (the Runtime asks the provider, then models.dev): it
  // adds rows under the owner's choice without moving the wheel off it.
  useEffect(() => {
    if (typed) return;
    if (model === "" || !mRows.some((r) => r.id === model)) setModel(defaultModel(mRows));
  }, [mRows, typed, model]);

  // A provider the Runtime can list nothing for (no curated picks, an empty or
  // keyless answer) goes straight to the typed box instead of a wheel that
  // says "asking" forever.
  useEffect(() => {
    if (live !== null && mRows.length === 0) setTyped(true);
  }, [live, mRows]);

  // A provider that fell off the wheel (the Runtime does not list it, or "more" closed) gives way to the first row.
  useEffect(() => {
    if (pRows.length && !pRows.some((r) => r.id === providerId)) setProviderId(pRows[0]!.id);
  }, [pRows, providerId]);

  const secret = secretField(descriptors);
  // The daemon names the key's field; when it could not be asked, `api_key`
  // (every curated provider's) so the box still shows and the save decides.
  const secretKey = secret?.key ?? (descriptors.length === 0 ? "api_key" : null);
  const secretLabel = secret?.label || t("setup.key_label");
  const extras = extraRequiredFields(descriptors);
  const verdict = judgeKey(key, provider?.key_prefix ?? "");
  const extrasFilled = extras.every((d) => (extra[d.key] ?? "").trim() !== "");
  const canTry = model.trim() !== "" && (verdict.ok || secretKey === null) && extrasFilled && !busy;
  // `<kind>.<alias>` for every provider the config holds: the next free alias, so a second setup never fails on the first's.
  const aliases = state?.model_providers ?? [];

  // The phone keyboard's Go key (Enter) does what the primary button does.
  const onEnter = (fn: () => void) => (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      fn();
    }
  };

  const apply = async (staged: StagedProvider, guide?: string) => {
    setBusy(true);
    setErrors([]);
    try {
      const res = await quickstartApply(submission(state ?? EMPTY_STATE, staged));
      if (res.kind === "errors") {
        setErrors(errorLines(res.errors));
        return;
      }
      setDone({ agent: res.agent.alias, provider: staged, guide });
      setScreen("done");
    } catch (e) {
      setErrors([e instanceof Error ? e.message : String(e)]);
    } finally {
      setBusy(false);
    }
  };

  const tryKey = () => {
    if (!canTry) return;
    void apply(
      stagedKeyProvider(providerId, model, secretKey, key, { ...nonEmptyFields(fieldSeed), ...extra }, providerAlias(aliases, providerId)),
    );
  };

  const stagedLocal = () =>
    stagedLocalProvider(runner, pick.model, nonEmptyFields(localSeed), providerAlias(aliases, runner, LOCAL_ALIAS));

  const useLocal = () => {
    if (busy) return;
    void apply(stagedLocal(), pick.guide);
  };

  // One press on a PC: pull what Ollama lacks (the agent's model, then Cael's),
  // each with its own bar, then set everything up as "Use this" would have.
  const downloadAndUse = async () => {
    if (busy || pull !== null || missing.length === 0) return;
    setErrors([]);
    const ctl = new AbortController();
    pullAbort.current = ctl;
    try {
      for (const [i, name] of missing.entries()) {
        const at = (event: PullEvent | null): Pull => ({ name, n: i + 1, total: missing.length, event });
        setPull(at(null));
        await pullModel(name, (e) => setPull(at(e)), ctl.signal);
        // Each one counts as soon as it is in: a failure on the second leaves the first pulled.
        setPulled((prev) => (prev.includes(name) ? prev : [...prev, name]));
      }
      setPull(null);
      await apply(stagedLocal(), pick.guide);
    } catch (e) {
      setPull(null);
      if (!ctl.signal.aborted) setErrors([e instanceof Error ? e.message : String(e)]);
    } finally {
      pullAbort.current = null;
    }
  };

  const stopPull = () => pullAbort.current?.abort();

  const go = (next: Screen) => {
    stopPull();
    setErrors([]);
    setScreen(next);
  };
  const back: Partial<Record<Screen, Screen>> = { local: "doors", provider: "doors", model: "provider", key: "model" };
  const steps: Record<Screen, [number, number]> = {
    doors: [1, 2],
    local: [2, 2],
    provider: [2, 4],
    model: [3, 4],
    key: [4, 4],
    done: [0, 0],
  };

  const tag = (x?: Tag) => (x ? <span className={`cz-tag cz-tag-${x}`}>{t(TAG_KEYS[x])}</span> : null);

  let title = "";
  let body: ReactNode = null;
  let control: ReactNode = null;
  let actions: ReactNode = null;

  switch (screen) {
    case "doors":
      title = t("setup.title_doors");
      body = t("setup.body_doors");
      actions = (
        <>
          <button type="button" className="cz-btn cz-btn-primary" onClick={() => go("local")}>
            <Sparkles className="h-5 w-5" aria-hidden="true" />
            {t("setup.door_local")}
          </button>
          <button type="button" className="cz-btn cz-btn-secondary" onClick={() => go("provider")}>
            <KeyRound className="h-5 w-5" aria-hidden="true" />
            {t("setup.door_key")}
          </button>
        </>
      );
      break;

    case "local": {
      const listed = (kind: Runner) => state === null || state.model_provider_types.some((p) => p.kind === kind);
      title = t("setup.title_local");
      // What happens after "Use this": on a phone the app or the script fetched the
      // model already; on a PC this page asks Ollama itself, so Cael says what he found.
      let then: ReactNode;
      if (runner !== "ollama") {
        then = <p className="cz-note">{t("setup.local_then")}</p>;
      } else if (!here) {
        then = <p className="cz-note">{fill(t("setup.ollama_remote"), { model: pick.model })}</p>;
      } else if (ollama === "missing") {
        then = (
          <>
            <p className="cz-note">{t("setup.ollama_missing")}</p>
            <a className="cz-link" href={OLLAMA_DOWNLOAD_PAGE} target="_blank" rel="noreferrer">
              {t("setup.ollama_get")} <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
            </a>
          </>
        );
      } else if (ollama === "ready") {
        const sized = missingGb === null ? "" : fill(t("setup.ollama_about"), { gb: missingGb });
        then = (
          <p className="cz-note">
            {missing.length === 0
              ? fill(t("setup.ollama_ready"), { model: pick.model })
              : missing.length === 1
                ? fill(t("setup.ollama_need_one"), { model: missing[0]!, about: sized })
                : fill(t("setup.ollama_need_two"), { model: pick.model, guide: pick.guide, about: sized })}
          </p>
        );
      } else {
        then = <p className="cz-note">{t("setup.ollama_checking")}</p>;
      }
      body = (
        <>
          <p>{fill(t("setup.body_local"), { model: pick.model, guide: pick.guide })}</p>
          {pick.notes.map((n) => (
            <p key={n} className="cz-note">
              {n}
            </p>
          ))}
          {then}
        </>
      );
      if (pull !== null) {
        const pct = percent(pull.event);
        const stageText = t(STAGE_KEYS[stage(pull.event)]);
        control = (
          <>
            {pull.total > 1 ? <div className="cz-kicker">{fill(t("setup.ollama_model_n"), { n: pull.n, total: pull.total })}</div> : null}
            <div className="cz-mono">{pull.name}</div>
            <div
              className="cz-progress"
              role="progressbar"
              aria-label={pull.name}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={pct ?? undefined}
              aria-valuetext={stageText}
            >
              <span className={pct === null ? "is-busy" : undefined} style={pct === null ? undefined : { width: `${pct}%` }} />
            </div>
            <p className="cz-note cz-progress-line">
              {pct === null || pull.event?.total === undefined
                ? stageText
                : fill(t("setup.ollama_progress"), { pct, done: gbOf(pull.event.completed ?? 0), total: gbOf(pull.event.total) })}
            </p>
          </>
        );
      } else {
        control = (
          <>
            <div className="cz-kicker">{t("setup.where")}</div>
            <div className="cz-chip-row" role="radiogroup" aria-label={t("setup.where")}>
              {(["llamacpp", "ollama"] as Runner[]).map((r) => (
                <button
                  key={r}
                  type="button"
                  role="radio"
                  aria-checked={runner === r}
                  disabled={!listed(r)}
                  className={`cz-chip${runner === r ? " is-on" : ""}`}
                  onClick={() => setRunner(r)}
                >
                  {t(r === "llamacpp" ? "setup.where_phone" : "setup.where_hub")}
                </button>
              ))}
            </div>
            <div className="cz-kicker">{t("setup.ram")}</div>
            <WheelPicker
              id="ram"
              label={t("setup.ram")}
              visible={3}
              rows={RAM_BANDS.map((b) => ({ id: b.id, label: t(BAND_KEYS[b.id]) }))}
              value={band}
              onChange={(v) => setBand(v as RamBand)}
            />
          </>
        );
      }
      if (pull !== null) {
        actions = (
          <>
            <button type="button" className="cz-btn cz-btn-primary" disabled>
              {t("setup.ollama_pulling")}
            </button>
            <button type="button" className="cz-btn-text" onClick={stopPull}>
              {t("setup.ollama_stop")}
            </button>
          </>
        );
      } else if (asksOllama && ollama === "missing") {
        actions = (
          <>
            <button type="button" className="cz-btn cz-btn-primary" onClick={() => setProbe((p) => p + 1)}>
              {t("setup.ollama_check_again")}
            </button>
            <button type="button" className="cz-btn-text" disabled={busy || !listed(runner)} onClick={useLocal}>
              {busy ? t("setup.working") : t("setup.ollama_anyway")}
            </button>
          </>
        );
      } else if (asksOllama && ollama === "ready" && missing.length > 0) {
        actions = (
          <button type="button" className="cz-btn cz-btn-primary" disabled={busy || !listed(runner)} onClick={() => void downloadAndUse()}>
            <Download className="h-5 w-5" aria-hidden="true" />
            {missingGb === null ? t("setup.ollama_download_unsized") : fill(t("setup.ollama_download"), { gb: missingGb })}
          </button>
        );
      } else {
        actions = (
          <button
            type="button"
            className="cz-btn cz-btn-primary"
            disabled={busy || !listed(runner) || (asksOllama && ollama === "checking")}
            onClick={useLocal}
          >
            {busy ? t("setup.working") : t("setup.use_this")}
          </button>
        );
      }
      break;
    }

    case "provider":
      title = t("setup.title_provider");
      body = (
        <>
          <p>{t("setup.body_provider")}</p>
          {state !== null && pRows.length === 0 ? <p className="cz-note">{t("setup.no_providers")}</p> : null}
          {stateFailed ? <p className="cz-note">{t("setup.runtime_unreachable")}</p> : null}
        </>
      );
      control = (
        <>
          <WheelPicker
            id="provider"
            label={t("setup.title_provider")}
            rows={pRows.map((r) => ({ id: r.id, label: r.label }))}
            value={providerId}
            onChange={setProviderId}
          />
          {state !== null ? (
            <button type="button" className="cz-btn-text" onClick={() => setMore((m) => !m)}>
              {t(more ? "setup.fewer_providers" : "setup.more_providers")}
            </button>
          ) : null}
        </>
      );
      actions = (
        <button type="button" className="cz-btn cz-btn-primary" disabled={!providerId} onClick={() => go("model")}>
          {t("setup.next")}
        </button>
      );
      break;

    case "model": {
      const bodyKey =
        provider === null ? "setup.body_model_live_only" : live?.live ? "setup.body_model" : "setup.body_model_offline";
      title = t("setup.title_model");
      body = fill(t(bodyKey), { provider: providerLabel });
      control = typed ? (
        <label className="block">
          <div className="cz-kicker">{t("setup.model_name")}</div>
          <input
            className="cz-input"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            onKeyDown={onEnter(() => {
              if (model.trim() !== "") go("key");
            })}
            placeholder={defaultModel(mRows)}
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            autoFocus
          />
        </label>
      ) : (
        <>
          <WheelPicker
            id="model"
            label={t("setup.title_model")}
            rows={mRows.map((r) => ({ id: r.id, label: r.label, hint: tag(r.tag) }))}
            value={model}
            onChange={setModel}
          />
          {live === null && mRows.length === 0 ? <p className="cz-note">{t("setup.loading")}</p> : null}
          <div className="cz-mono">{model}</div>
        </>
      );
      actions = (
        <>
          <button type="button" className="cz-btn cz-btn-primary" disabled={model.trim() === ""} onClick={() => go("key")}>
            {t("setup.next")}
          </button>
          <button
            type="button"
            className="cz-btn-text"
            onClick={() => {
              if (typed) setModel(defaultModel(mRows));
              setTyped((v) => !v);
            }}
          >
            {t(typed ? "setup.back_to_wheel" : "setup.type_model")}
          </button>
        </>
      );
      break;
    }

    case "key": {
      const page = provider?.key_page ?? "";
      title = t("setup.title_key");
      body = (
        <>
          <p>
            {fill(t("setup.body_key"), { provider: providerLabel, page: page ? keyPageName(page) : providerLabel })}
          </p>
          {page ? (
            <a className="cz-link" href={page} target="_blank" rel="noreferrer">
              {t("setup.get_key")} <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
            </a>
          ) : null}
        </>
      );
      control = (
        <>
          {secretKey !== null ? (
            <label className="block">
              <div className="cz-kicker">{secretLabel}</div>
              <div className="cz-input-row">
                <input
                  className="cz-input"
                  type={showKey ? "text" : "password"}
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  onKeyDown={onEnter(tryKey)}
                  placeholder={fill(t("setup.key_hint"), { prefix: provider?.key_prefix ?? "" })}
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  autoComplete="off"
                  autoFocus
                />
                <button
                  type="button"
                  className="cz-icon-btn"
                  aria-label={t(showKey ? "setup.key_hide" : "setup.key_show")}
                  onClick={() => setShowKey((v) => !v)}
                >
                  {showKey ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                </button>
              </div>
            </label>
          ) : null}
          {extras.map((d) => (
            <label key={d.key} className="block">
              <div className="cz-kicker">{d.label || d.key}</div>
              <input
                className="cz-input"
                value={extra[d.key] ?? ""}
                placeholder={d.default ?? ""}
                onChange={(e) => setExtra((prev) => ({ ...prev, [d.key]: e.target.value }))}
                onKeyDown={onEnter(tryKey)}
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
              />
            </label>
          ))}
          {key.trim() !== "" && !verdict.ok ? (
            <p className="cz-note">{t(verdict.reason === "spaces" ? "setup.key_spaces" : "setup.key_short")}</p>
          ) : null}
          {verdict.ok && verdict.warning === "prefix" ? (
            <p className="cz-note">
              {fill(t("setup.key_prefix_warning"), { provider: providerLabel, prefix: provider?.key_prefix ?? "" })}
            </p>
          ) : null}
          <div className="cz-mono">
            {providerLabel} · {model}
          </div>
        </>
      );
      actions = (
        <button type="button" className="cz-btn cz-btn-primary" disabled={!canTry} onClick={tryKey}>
          {busy ? t("setup.working") : t("setup.try_it")}
        </button>
      );
      break;
    }

    case "done":
      title = t("setup.title_done");
      body = done
        ? done.guide
          ? fill(t("setup.body_done_local"), { agent: done.agent, model: done.provider.model, guide: done.guide })
          : fill(t("setup.body_done"), { agent: done.agent, model: done.provider.model, provider: providerLabel })
        : null;
      actions = (
        <button
          type="button"
          className="cz-btn cz-btn-primary"
          onClick={() => navigate(`/agent/${encodeURIComponent(done?.agent ?? "main")}`)}
        >
          {t("setup.open_chat")}
        </button>
      );
      break;
  }

  const [n, total] = steps[screen];
  const prev = back[screen];

  return (
    <div className="cz-setup">
      <div className="cz-setup-col">
        <header className="cz-setup-head">
          <Eyebrow />
          <div className="flex items-center gap-2">
            <Mark src={`${basePath}/_app/logo.png`} size={28} />
            <Wordmark size="sm" />
          </div>
        </header>

        <div className="cz-setup-step">
          {prev ? (
            <button type="button" className="cz-btn-text" onClick={() => go(prev)} disabled={busy}>
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
              {t("setup.back")}
            </button>
          ) : (
            <span />
          )}
          {total > 0 ? <span className="cz-kicker">{fill(t("setup.step"), { n, total })}</span> : null}
        </div>

        <h1 className="cz-title">{title}</h1>

        <section className="cz-bubble" aria-label={t("setup.cael_says")}>
          <div className="cz-kicker cz-kicker-violet">{t("setup.cael_says")}</div>
          <div className="cz-bubble-text">{body}</div>
        </section>

        {control ? <div className="cz-setup-control">{control}</div> : null}

        {errors.length ? (
          <div className="cz-error" role="alert">
            {fill(t("setup.failed"), { reason: "" }).trim()}
            <ul>
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="cz-setup-actions">{actions}</div>

        <footer className="cz-setup-foot">
          <Link to="/quickstart">{t("setup.advanced")}</Link>
          <Link to="/">{t("setup.skip")}</Link>
        </footer>
      </div>
    </div>
  );
}
