// The Looks (vision M8): `/looks` is every agent as its pixel character,
// `/looks/:alias` the customizer: one tab per layer, the pieces of the packs
// in the wardrobe, a colour row per slot the chosen pieces recolour, a
// preview that blinks and can be made to talk. Saved on the Runtime through
// /api/looks, so the phone and the desktop see the same character.
// Phone-first: one column at 390 px, 56 px cells, 36 px controls.
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Download, Lock, RotateCcw, Save, ShoppingBag, Undo2, Volume2, VolumeX } from "lucide-react";

import { Button, PageHeader } from "@/components/ui";
import { loadAgentSummaries, type AgentSummary } from "@/lib/agents";
import { deleteLook, getLook, getWardrobe, putLook } from "@/lib/api";
import { t } from "@/lib/i18n";
import { AgentLook, Look, avatarPng, catalog, rememberLook, forgetLook, saveBlob } from "@/looks/Look";
import {
  LAYERS,
  defaultLook,
  lockedParts,
  lookEquals,
  normalizeLook,
  ownedPacks,
  partById,
  slotsInUse,
  type Layer,
  type Look as LookData,
  type Slot,
  type Wardrobe,
} from "@/looks/looks.logic";

const MUTED = { color: "var(--pc-text-muted)" } as const;

export default function Looks() {
  const { alias } = useParams<{ alias: string }>();
  return alias ? <Customizer alias={alias} /> : <Gallery />;
}

function Gallery() {
  const [agents, setAgents] = useState<AgentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    loadAgentSummaries()
      .then((a) => {
        if (!cancelled) setAgents(a);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return (
    <div className="p-6 space-y-4">
      <PageHeader
        title={t("looks.title")}
        description={t("looks.description")}
        actions={
          <Link to="/shop">
            <Button variant="ghost" size="sm">
              <ShoppingBag className="h-4 w-4" />
              {t("nav.shop")}
            </Button>
          </Link>
        }
      />
      {error ? (
        <div className="card p-4 text-sm" style={{ color: "var(--color-status-error)" }}>
          {error}
        </div>
      ) : null}
      {agents && agents.length === 0 ? (
        <div className="card p-6 text-sm text-center" style={MUTED}>
          {t("looks.gallery_empty")}
        </div>
      ) : null}
      <div className="cz-look-gallery">
        {(agents ?? []).map((a) => (
          <Link key={a.alias} to={`/looks/${encodeURIComponent(a.alias)}`} className="card cz-look-agent">
            <AgentLook alias={a.alias} size={104} />
            <div className="font-semibold text-sm text-pc-text truncate">{a.alias}</div>
            <div className="text-xs" style={MUTED}>
              {t("looks.dress")}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

function Customizer({ alias }: { alias: string }) {
  const [saved, setSaved] = useState<LookData>(() => defaultLook(alias, catalog));
  const [look, setLook] = useState<LookData>(() => defaultLook(alias, catalog));
  const [wardrobe, setWardrobe] = useState<Wardrobe | null>(null);
  const [wardrobeUnknown, setWardrobeUnknown] = useState(false);
  const [layer, setLayer] = useState<Layer>("hair");
  const [talk, setTalk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [note, setNote] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setNote(null);
    getLook(alias)
      .then((r) => {
        if (cancelled) return;
        const l = normalizeLook(r.look, alias, catalog);
        setSaved(l);
        setLook(l);
      })
      .catch((e: unknown) => {
        if (!cancelled) setNote({ tone: "error", text: `${t("looks.load_failed")} ${e instanceof Error ? e.message : String(e)}` });
      });
    getWardrobe()
      .then((w) => {
        if (!cancelled) setWardrobe(w);
      })
      .catch((e: unknown) => {
        // Unknown, not empty: locking every piece and refusing to save a look
        // that is fine would be wrong; the note says the wardrobe did not load.
        if (!cancelled) {
          setWardrobeUnknown(true);
          setNote({ tone: "error", text: `${t("looks.wardrobe_failed")} ${e instanceof Error ? e.message : String(e)}` });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [alias]);

  const owned = useMemo(
    () => (wardrobeUnknown && wardrobe === null ? new Set(catalog.packs.filter((p) => p.status === "available").map((p) => p.id)) : ownedPacks(catalog, wardrobe)),
    [wardrobe, wardrobeUnknown],
  );
  const dirty = !lookEquals(look, saved);
  const locked = lockedParts(look, catalog, owned);
  const parts = useMemo(() => catalog.parts.filter((p) => p.layer === layer), [layer]);
  const slots = slotsInUse(look, catalog);

  const pick = (id: string) => setLook((l) => ({ ...l, parts: { ...l.parts, [layer]: id } }));
  const paint = (slot: Slot, hex: string) => setLook((l) => ({ ...l, colors: { ...l.colors, [slot]: hex.toLowerCase() } }));

  const save = async () => {
    if (busy || locked.length) return;
    setBusy(true);
    setNote(null);
    try {
      const r = await putLook(alias, look);
      const l = normalizeLook(r.look, alias, catalog);
      setSaved(l);
      setLook(l);
      rememberLook(alias, l);
      setNote({ tone: "ok", text: t("looks.saved") });
    } catch (e) {
      setNote({ tone: "error", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  // The look on screen (saved or not) as a 512 px PNG, into the downloads.
  const exportAvatar = async () => {
    if (exporting) return;
    setExporting(true);
    setNote(null);
    try {
      saveBlob(await avatarPng(look), `${alias}-avatar.png`);
      setNote({ tone: "ok", text: t("looks.avatar_saved") });
    } catch (e) {
      setNote({ tone: "error", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setExporting(false);
    }
  };

  const reset = async () => {
    if (busy) return;
    setBusy(true);
    setNote(null);
    try {
      await deleteLook(alias);
      const l = defaultLook(alias, catalog);
      setSaved(l);
      setLook(l);
      forgetLook(alias);
      setNote({ tone: "ok", text: t("looks.reset_done") });
    } catch (e) {
      setNote({ tone: "error", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-6 space-y-4">
      <Link to="/looks" className="inline-flex items-center gap-1 text-xs min-h-9" style={MUTED}>
        <ArrowLeft className="h-3.5 w-3.5" />
        {t("looks.back")}
      </Link>
      <PageHeader
        title={alias}
        description={t("looks.customize_help")}
        actions={
          <>
            <Button variant="ghost" size="sm" disabled={!dirty || busy} onClick={() => setLook(saved)}>
              <Undo2 className="h-4 w-4" />
              {t("looks.undo")}
            </Button>
            <Button variant="primary" size="sm" disabled={!dirty || busy || locked.length > 0} onClick={() => void save()}>
              <Save className="h-4 w-4" />
              {busy ? t("looks.saving") : t("looks.save")}
            </Button>
          </>
        }
      />

      <div className="card cz-look-preview">
        <Look look={look} size={200} talking={talk} title={alias} />
        <div className="flex flex-col gap-2">
          <Button variant="ghost" size="sm" onClick={() => setTalk((v) => !v)} aria-pressed={talk}>
            {talk ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
            {t(talk ? "looks.preview_stop" : "looks.preview_talk")}
          </Button>
          <div className="text-xs" style={MUTED}>
            {t("looks.blinks")}
          </div>
          <Button variant="ghost" size="sm" disabled={exporting} onClick={() => void exportAvatar()}>
            <Download className="h-4 w-4" />
            {exporting ? t("looks.avatar_saving") : t("looks.avatar")}
          </Button>
          <div className="text-xs" style={MUTED}>
            {t("looks.avatar_hint")}
          </div>
          {locked.length ? (
            <div className="text-xs" style={{ color: "var(--color-status-warning, #ffe600)" }}>
              {t("looks.locked_error")}{" "}
              <Link to="/shop" className="underline">
                {t("nav.shop")}
              </Link>
            </div>
          ) : null}
        </div>
      </div>

      {note ? (
        <div className="text-sm" role="status" style={{ color: note.tone === "ok" ? "var(--color-status-success, #39ff14)" : "var(--color-status-error)" }}>
          {note.text}
        </div>
      ) : null}

      <div className="cz-chip-row cz-chip-scroll" role="tablist" aria-label={t("looks.layers")}>
        {LAYERS.map((l) => (
          <button
            key={l}
            type="button"
            role="tab"
            aria-selected={layer === l}
            className={`cz-chip cz-chip-auto${layer === l ? " is-on" : ""}`}
            onClick={() => setLayer(l)}
          >
            {t(`looks.layer_${l}`)}
          </button>
        ))}
      </div>

      <div className="cz-look-grid" role="listbox" aria-label={t(`looks.layer_${layer}`)}>
        {parts.map((p) => {
          const isLocked = !owned.has(p.pack);
          const selected = look.parts[layer] === p.id;
          const preview: LookData = { ...look, parts: { ...look.parts, [layer]: p.id } };
          return (
            <button
              key={p.id}
              type="button"
              role="option"
              aria-selected={selected}
              className={`cz-look-cell${selected ? " is-selected" : ""}${isLocked ? " is-locked" : ""}`}
              title={isLocked ? `${t("looks.locked_title")} ${catalog.packs.find((k) => k.id === p.pack)?.name ?? p.pack}` : p.name}
              onClick={() => {
                if (!isLocked) pick(p.id);
              }}
            >
              <Look look={preview} size={56} frame="closed" />
              <span className="cz-look-cell-name">{p.name}</span>
              {isLocked ? <Lock className="cz-look-lock h-3.5 w-3.5" aria-hidden="true" /> : null}
            </button>
          );
        })}
      </div>
      {parts.some((p) => !owned.has(p.pack)) ? (
        <div className="text-xs" style={MUTED}>
          {t("looks.locked_hint")}{" "}
          <Link to="/shop" className="underline">
            {t("nav.shop")}
          </Link>
        </div>
      ) : null}

      {slots.length ? (
        <div className="space-y-3">
          <div className="cz-kicker">{t("looks.colors")}</div>
          {slots.map((slot) => (
            <div key={slot} className="cz-swatch-row">
              <div className="text-sm text-pc-text w-20 shrink-0">{t(`looks.slot_${slot}`)}</div>
              <div className="flex flex-wrap gap-2 items-center">
                {catalog.colors[slot].map((hex) => (
                  <button
                    key={hex}
                    type="button"
                    className={`cz-swatch${look.colors[slot].toLowerCase() === hex.toLowerCase() ? " is-on" : ""}`}
                    style={{ background: hex }}
                    aria-label={`${t(`looks.slot_${slot}`)} ${hex}`}
                    aria-pressed={look.colors[slot].toLowerCase() === hex.toLowerCase()}
                    onClick={() => paint(slot, hex)}
                  />
                ))}
                <label className="cz-swatch cz-swatch-custom" title={t("looks.custom_color")}>
                  <input
                    type="color"
                    value={look.colors[slot]}
                    aria-label={`${t(`looks.slot_${slot}`)} ${t("looks.custom_color")}`}
                    onChange={(e) => paint(slot, e.target.value)}
                  />
                </label>
              </div>
            </div>
          ))}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2 pt-2">
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => void reset()}>
          <RotateCcw className="h-4 w-4" />
          {t("looks.reset")}
        </Button>
        <Link to="/shop">
          <Button variant="ghost" size="sm">
            <ShoppingBag className="h-4 w-4" />
            {t("looks.shop_link")}
          </Button>
        </Link>
      </div>
      <div className="text-xs" style={MUTED}>
        {t("looks.wearing")}{" "}
        {LAYERS.map((l) => partById(catalog, look.parts[l])?.name ?? look.parts[l]).join(" · ")}
      </div>
    </div>
  );
}
