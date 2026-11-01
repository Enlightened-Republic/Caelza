// Quickstart's first screen (vision §3.4): two doors. "Free and local" stages
// the ladder's DeepSeek R1 for this device as `<runner>.local`, the alias
// scripts/model-setup.sh and the app's first run write, with Cael's honest
// line from the ladder; "Bring your own key" is upstream's provider form,
// handed in by the page. Phone-first: the doors stack at 390 px.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowLeft, KeyRound, Plus, Sparkles } from "lucide-react";

import { Button } from "@/components/ui";
import { quickstartFields, type QuickstartState } from "@/lib/api";
import { t } from "@/lib/i18n";
import { LabeledInput } from "./quickstart-form-controls";
import {
  LADDER,
  RAM_BANDS,
  bandMb,
  guessDefaults,
  localPick,
  nonEmptyFields,
  seedFieldValues,
  stagedLocalProvider,
  type Door,
  type RamBand,
  type Runner,
  type StagedLocalProvider,
} from "./doors.logic";

const SELECT_CLASS =
  "w-full h-9 px-3 rounded-[var(--radius-md)] border border-pc-border bg-pc-input text-sm text-pc-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pc-accent/40 focus-visible:border-pc-accent/40";
const MUTED = { color: "var(--pc-text-muted)" } as const;

const RUNNER_KEYS: Record<Runner, string> = {
  llamacpp: "quickstart.door_where_phone",
  ollama: "quickstart.door_where_hub",
};
const BAND_KEYS: Record<RamBand, string> = {
  small: "quickstart.door_ram_small",
  phone: "quickstart.door_ram_phone",
  medium: "quickstart.door_ram_medium",
  large: "quickstart.door_ram_large",
};

export default function Doors({
  state,
  onStage,
  keyDoor,
}: {
  state: QuickstartState | null;
  onStage: (p: StagedLocalProvider) => void;
  /** Upstream's provider form, already wired to the page's stage callback. */
  keyDoor: ReactNode;
}) {
  const [door, setDoor] = useState<Door | null>(null);
  if (door === null) {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <DoorCard
          icon={<Sparkles className="h-5 w-5" />}
          title={t("quickstart.door_local")}
          help={t("quickstart.door_local_help")}
          onClick={() => setDoor("local")}
        />
        <DoorCard
          icon={<KeyRound className="h-5 w-5" />}
          title={t("quickstart.door_key")}
          help={t("quickstart.door_key_help")}
          onClick={() => setDoor("key")}
        />
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={() => setDoor(null)}
        className="inline-flex items-center gap-1 text-xs text-pc-text-muted hover:text-pc-text"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        {t("quickstart.door_back")}
      </button>
      {door === "local" ? <LocalDoor state={state} onStage={onStage} /> : keyDoor}
    </div>
  );
}

function DoorCard({
  icon,
  title,
  help,
  onClick,
}: {
  icon: ReactNode;
  title: string;
  help: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-left rounded-[var(--radius-md)] border border-pc-border bg-pc-base p-4 space-y-2 transition-colors hover:bg-[var(--pc-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pc-accent/40"
    >
      <span className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] bg-pc-accent/10 text-pc-accent">
        {icon}
      </span>
      <div className="font-semibold text-pc-text">{title}</div>
      <div className="text-xs" style={MUTED}>
        {help}
      </div>
    </button>
  );
}

function LocalDoor({
  state,
  onStage,
}: {
  state: QuickstartState | null;
  onStage: (p: StagedLocalProvider) => void;
}) {
  const guess = useMemo(() => {
    if (typeof navigator === "undefined") return guessDefaults("");
    const nav = navigator as Navigator & { deviceMemory?: number };
    return guessDefaults(nav.userAgent, nav.deviceMemory ?? null);
  }, []);
  const [runner, setRunner] = useState<Runner>(guess.runner);
  const [band, setBand] = useState<RamBand>(guess.band);
  const pick = useMemo(() => localPick(runner, bandMb(band)), [runner, band]);
  const [model, setModel] = useState(pick.model);
  const [touched, setTouched] = useState(false);
  // The field buffer is what upstream's form keeps: the daemon's enum rows
  // seeded with their defaults, text rows left to the daemon's defaults.
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!touched) setModel(pick.model);
  }, [pick.model, touched]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const f = await quickstartFields({ section: "model_provider", type_key: runner });
        if (!cancelled) setFieldValues(seedFieldValues(f.fields));
      } catch {
        if (!cancelled) setFieldValues({});
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runner]);

  const listed = (kind: Runner) =>
    state === null || state.model_provider_types.some((p) => p.kind === kind);
  const canAdd = model.trim() !== "" && listed(runner);

  return (
    <div className="space-y-3">
      <label className="block">
        <div className="text-xs uppercase tracking-wider mb-1" style={MUTED}>
          {t("quickstart.door_where")}
        </div>
        <select
          className={SELECT_CLASS}
          value={runner}
          onChange={(e) => {
            setRunner(e.target.value as Runner);
            setTouched(false);
          }}
        >
          {(Object.keys(RUNNER_KEYS) as Runner[]).map((r) => (
            <option key={r} value={r} disabled={!listed(r)}>
              {t(RUNNER_KEYS[r])}
            </option>
          ))}
        </select>
      </label>

      <label className="block">
        <div className="text-xs uppercase tracking-wider mb-1" style={MUTED}>
          {t("quickstart.door_ram")}
        </div>
        <select
          className={SELECT_CLASS}
          value={band}
          onChange={(e) => setBand(e.target.value as RamBand)}
        >
          {RAM_BANDS.map((b) => (
            <option key={b.id} value={b.id}>
              {t(BAND_KEYS[b.id])}
            </option>
          ))}
        </select>
      </label>

      <LabeledInput
        label={t("quickstart.model")}
        value={model}
        onChange={(v) => {
          setTouched(true);
          setModel(v);
        }}
        placeholder={pick.model}
        help={t("quickstart.door_model_help").replace(
          "{names}",
          Object.values(LADDER[runner]).join(", "),
        )}
      />

      <div
        className="rounded-[var(--radius-md)] border border-pc-border bg-pc-base p-3 text-xs space-y-1"
        style={MUTED}
      >
        <div>{t("quickstart.door_cael").replace("{model}", pick.guide)}</div>
        {pick.notes.map((note) => (
          <div key={note}>{note}</div>
        ))}
        <div>{t("quickstart.door_then")}</div>
      </div>

      <div className="flex justify-end">
        <Button
          size="sm"
          disabled={!canAdd}
          onClick={() => onStage(stagedLocalProvider(runner, model, nonEmptyFields(fieldValues)))}
        >
          <Plus className="h-3.5 w-3.5" />
          {t("quickstart.add")}
        </Button>
      </div>
    </div>
  );
}
