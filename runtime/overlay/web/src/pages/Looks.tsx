// The Looks (vision M8): `/looks` is every agent as its pixel character,
// `/looks/:alias` the customizer: one tab per layer, the pieces of the packs
// in the wardrobe, a colour row per slot the chosen pieces recolour, a
// preview that blinks and can be made to talk. Saved on the Runtime through
// /api/looks, so the phone and the desktop see the same character.
// Phone-first: one column at 390 px, 56 px cells, 36 px controls.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Download, Lock, RotateCcw, Save, ShoppingBag, Sparkles, Trash2, Undo2, Upload, Volume2, VolumeX } from "lucide-react";

import { Button, PageHeader } from "@/components/ui";
import { loadAgentSummaries, type AgentSummary } from "@/lib/agents";
import { basePath } from "@/lib/basePath";
import { AgentNameText, rememberAgentName, useAgentName } from "@/lib/agentName";
import { deleteLook, getLook, getProp, getWardrobe, patchConfig, putLook } from "@/lib/api";
import { t } from "@/lib/i18n";
import { getIdentity, putIdentity, setAgentName } from "@/lib/identity";
import { NAME_MAX, nameOk } from "@/lib/identity.logic";
import { describeLook, withLookSection } from "@/lib/buddy.logic";
import { freeOps } from "@/lib/persona.logic";
import VoiceCard from "@/pages/VoiceCard";
import { charactersChanged, deleteCharacter, importCharacter, listCharacters } from "@/lib/characters";
import { AgentLook, Look, avatarPng, catalog, rememberLook, forgetLook, saveBlob } from "@/looks/Look";
import type { Character } from "@/looks/characters.logic";
import {
  LAYERS,
  addedPacks,
  packLayers,
  sheetUrl,
  wearCharacter,
  wearPack,
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
  // What the owner added in the Shop or imported, named here so it is plain
  // where it went: into every agent's customizer, one tap below.
  const [added, setAdded] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    loadAgentSummaries()
      .then((a) => {
        if (!cancelled) setAgents(a);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    Promise.all([getWardrobe().catch(() => null), listCharacters().catch(() => ({ characters: [] as Character[] }))]).then(([w, c]) => {
      if (cancelled) return;
      setAdded([...addedPacks(catalog, ownedPacks(catalog, w)).map((p) => p.name), ...c.characters.map((ch) => ch.name)]);
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
      {added.length && agents?.length ? (
        <div className="card p-4 text-sm flex items-center gap-2" data-looks-added>
          <Sparkles className="h-4 w-4 shrink-0" style={{ color: "var(--pc-accent)" }} aria-hidden="true" />
          <span>{t("looks.gallery_added").replace("{items}", added.join(", "))}</span>
        </div>
      ) : null}
      <div className="cz-look-gallery">
        {(agents ?? []).map((a) => (
          <Link key={a.alias} to={`/looks/${encodeURIComponent(a.alias)}`} className="card cz-look-agent">
            <AgentLook alias={a.alias} size={104} />
            <div className="font-semibold text-sm text-pc-text truncate">
              <AgentNameText alias={a.alias} />
            </div>
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

  // The name: the Name line of the agent's IDENTITY.md, which the Runtime reads
  // into every prompt, so a rename reaches the agent with its next reply.
  const shown = useAgentName(alias);
  const [nameDraft, setNameDraft] = useState("");
  const [nameBusy, setNameBusy] = useState(false);
  useEffect(() => setNameDraft(shown), [shown]);
  const nameDirty = nameDraft.trim() !== shown;
  const saveName = async () => {
    const next = nameDraft.trim();
    if (nameBusy || !nameDirty || !nameOk(next)) return;
    setNameBusy(true);
    setNote(null);
    try {
      await setAgentName(alias, next);
      rememberAgentName(alias, next);
      setNote({ tone: "ok", text: t("name.saved") });
    } catch (e) {
      setNote({ tone: "error", text: `${t("name.failed")} ${e instanceof Error ? e.message : String(e)}` });
    } finally {
      setNameBusy(false);
    }
  };

  // The owner's one yes (vision M10 §10): `[persona] free` lets the agent use
  // its `look` and `identity` tools without asking. The tools read the switch
  // from the config file at each call, so it reaches the agent at once.
  const [free, setFree] = useState<boolean | null>(null);
  const [freeBusy, setFreeBusy] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getProp("persona.free")
      .then((p) => {
        if (!cancelled) setFree(p.value === true);
      })
      .catch(() => {
        if (!cancelled) setFree(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const saveFree = async (on: boolean) => {
    if (freeBusy || free === on) return;
    setFreeBusy(true);
    setNote(null);
    try {
      // The tools act with no one to answer a prompt: the agent's risk profile
      // must let them through. Read the profile and its list; without them the
      // switch alone is written (the same shape as the town's wake).
      let profile: string | null = null;
      let autoApprove: string[] | null = null;
      if (on) {
        try {
          const p = await getProp(`agents.${alias}.risk_profile`);
          profile = typeof p.value === "string" && p.value.trim() ? p.value.trim() : null;
          if (profile) {
            const a = await getProp(`risk_profiles.${profile}.auto_approve`);
            autoApprove = Array.isArray(a.value) ? a.value.filter((x): x is string => typeof x === "string") : [];
          }
        } catch {
          profile = null;
        }
      }
      await patchConfig(freeOps(on, profile, autoApprove));
      setFree(on);
      setNote({ tone: "ok", text: t(on ? "persona.on_saved" : "persona.off_saved") });
    } catch (e) {
      setNote({ tone: "error", text: `${t("persona.failed")} ${e instanceof Error ? e.message : String(e)}` });
    } finally {
      setFreeBusy(false);
    }
  };

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

  // The look in words into the agent's IDENTITY.md ("How I look"): the Runtime
  // reads that file into every prompt and never look.json, so this is how the
  // look the owner picked reaches the agent. Cael's files are his own.
  const tellAgent = async (l: LookData): Promise<boolean> => {
    if (alias === "cael") return true;
    try {
      const current = await getIdentity(alias);
      await putIdentity(alias, withLookSection(current.content, describeLook(l, catalog)));
      return true;
    } catch {
      return false;
    }
  };

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
      const told = await tellAgent(l);
      setNote(told ? { tone: "ok", text: alias === "cael" ? t("looks.saved") : t("buddy.look_told") } : { tone: "error", text: t("buddy.look_untold") });
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
      const told = await tellAgent(l);
      setNote(told ? { tone: "ok", text: t("looks.reset_done") } : { tone: "error", text: t("buddy.look_untold") });
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
        title={shown}
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

      {alias !== "cael" ? (
        <div className="card p-4 space-y-2" data-name-card>
          <div className="cz-kicker">{t("name.card_title")}</div>
          <p className="text-xs" style={MUTED}>
            {t("name.card_help")}
          </p>
          <div className="flex items-center gap-2">
            <input
              className="cz-input"
              value={nameDraft}
              maxLength={NAME_MAX}
              onChange={(e) => setNameDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void saveName();
                }
              }}
              aria-label={t("name.label")}
              autoCapitalize="words"
              autoCorrect="off"
              spellCheck={false}
              data-name-input
            />
            <Button variant="primary" size="sm" disabled={nameBusy || !nameDirty || !nameOk(nameDraft)} onClick={() => void saveName()} data-name-save>
              {nameBusy ? t("name.saving") : t("name.save")}
            </Button>
          </div>
          {nameDraft.trim() !== "" && !nameOk(nameDraft) ? (
            <p className="text-xs" style={MUTED}>
              {t("name.rule")}
            </p>
          ) : null}
        </div>
      ) : null}

      {alias !== "cael" ? (
        <div className="card p-4 space-y-2" data-free-card>
          <div className="cz-kicker">{t("persona.card_title")}</div>
          <p className="text-xs" style={MUTED}>
            {t("persona.card_help")}
          </p>
          <label className="flex items-center gap-3 min-h-9">
            <input
              type="checkbox"
              checked={free === true}
              disabled={free === null || freeBusy}
              onChange={(e) => void saveFree(e.target.checked)}
              aria-label={t("persona.switch")}
              data-free-switch
            />
            <span className="text-sm">{free === null ? t("persona.loading") : free ? t("persona.on") : t("persona.off")}</span>
          </label>
        </div>
      ) : null}

      {/* The voice (P2b): what it sounds like when replies are read aloud; Cael's is his own. */}
      {alias !== "cael" ? <VoiceCard alias={alias} onNote={setNote} /> : null}

      <div className="card cz-look-preview">
        <Look look={look} size={200} talking={talk} title={shown} />
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

      <CharactersCard
        look={look}
        onWear={(id) => setLook((l) => wearCharacter(l, id))}
        onNote={setNote}
        onRemoved={(id) => {
          if (look.character === id) setLook((l) => wearCharacter(l, null));
        }}
      />

      {addedPacks(catalog, owned).length ? (
        <div className="card p-4 space-y-3" data-packs-card>
          <div className="cz-kicker">{t("looks.packs_title")}</div>
          <p className="text-xs" style={MUTED}>
            {t("looks.packs_help")}
          </p>
          <div className="flex flex-wrap gap-3">
            {addedPacks(catalog, owned).map((pack) => (
              <div key={pack.id} className="flex items-center gap-3 min-w-0" data-pack={pack.id}>
                <img src={sheetUrl(basePath, pack.id)} alt="" className="cz-look h-14 w-auto rounded" loading="lazy" />
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-pc-text truncate">{pack.name}</div>
                  <div className="text-xs" style={MUTED}>
                    {packLayers(catalog, pack.id).map((l) => t(`looks.layer_${l}`)).join(" · ")}
                  </div>
                </div>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => {
                    setLook((l) => wearPack(l, catalog, pack.id));
                    const first = packLayers(catalog, pack.id)[0];
                    if (first) setLayer(first);
                    setNote({ tone: "ok", text: t("looks.pack_worn").replace("{pack}", pack.name) });
                  }}
                  data-pack-wear
                >
                  {t("looks.pack_wear")}
                </Button>
              </div>
            ))}
          </div>
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

/**
 * The drawn characters: a PNGtuber the owner downloaded (a .zip, or its PNGs)
 * imported once onto the Runtime, then worn by any agent. Wearing one is a
 * change to the look like any other, saved with Save look; the pieces below
 * stay as what the look falls back to.
 */
function CharactersCard({
  look,
  onWear,
  onNote,
  onRemoved,
}: {
  look: LookData;
  onWear: (id: string | null) => void;
  onNote: (n: { tone: "ok" | "error"; text: string } | null) => void;
  onRemoved: (id: string) => void;
}) {
  const [characters, setCharacters] = useState<Character[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const reload = () =>
    listCharacters()
      .then((r) => setCharacters(r.characters))
      .catch(() => setCharacters([]));
  useEffect(() => {
    void reload();
  }, []);

  const onFiles = async (list: FileList | null) => {
    const files = list ? Array.from(list) : [];
    if (!files.length || busy) return;
    setBusy("import");
    onNote(null);
    try {
      const r = await importCharacter(files, (characters ?? []).map((c) => c.id));
      await reload();
      onWear(r.character.id);
      onNote({
        tone: "ok",
        text: t(r.guessed ? "looks.character_guessed" : "looks.character_imported").replace("{name}", r.character.name),
      });
    } catch (e) {
      onNote({ tone: "error", text: `${t("looks.character_failed")} ${e instanceof Error ? e.message : String(e)}` });
    } finally {
      setBusy(null);
    }
  };

  const remove = async (c: Character) => {
    if (busy || !window.confirm(t("looks.character_remove_confirm").replace("{name}", c.name))) return;
    setBusy(c.id);
    onNote(null);
    try {
      await deleteCharacter(c.id);
      charactersChanged(c.id);
      onRemoved(c.id);
      await reload();
      onNote({ tone: "ok", text: t("looks.character_removed").replace("{name}", c.name) });
    } catch (e) {
      onNote({ tone: "error", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="card p-4 space-y-3" data-characters-card>
      <div className="cz-kicker">{t("looks.characters_title")}</div>
      <p className="text-xs" style={MUTED}>
        {t("looks.characters_help")}
      </p>
      {characters && characters.length ? (
        <div className="cz-look-grid" role="listbox" aria-label={t("looks.characters_title")}>
          {characters.map((c) => {
            const worn = look.character === c.id;
            return (
              <div key={c.id} className="flex flex-col items-center gap-1" data-character={c.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={worn}
                  className={`cz-look-cell${worn ? " is-selected" : ""}`}
                  title={worn ? t("looks.character_off") : t("looks.character_wear")}
                  onClick={() => onWear(worn ? null : c.id)}
                >
                  <Look look={wearCharacter(look, c.id)} size={56} frame="closed" />
                  <span className="cz-look-cell-name">{c.name}</span>
                </button>
                <button
                  type="button"
                  className="cz-btn-text text-xs inline-flex items-center gap-1"
                  disabled={busy !== null}
                  onClick={() => void remove(c)}
                  aria-label={`${t("looks.character_remove")} ${c.name}`}
                >
                  <Trash2 className="h-3 w-3" aria-hidden="true" />
                  {t("looks.character_remove")}
                </button>
              </div>
            );
          })}
        </div>
      ) : characters ? (
        <p className="text-xs" style={MUTED}>
          {t("looks.characters_empty")}
        </p>
      ) : null}
      {look.character ? (
        <p className="text-xs" style={MUTED} data-character-worn>
          {t("looks.character_worn_note")}
        </p>
      ) : null}
      <input
        ref={input}
        type="file"
        accept=".zip,.png,image/png,application/zip,application/x-zip-compressed"
        multiple
        hidden
        onChange={(e) => {
          void onFiles(e.target.files);
          e.target.value = "";
        }}
        data-character-import
      />
      <Button variant="ghost" size="sm" disabled={busy !== null} onClick={() => input.current?.click()}>
        <Upload className="h-4 w-4" />
        {busy === "import" ? t("looks.character_importing") : t("looks.character_import")}
      </Button>
    </div>
  );
}
