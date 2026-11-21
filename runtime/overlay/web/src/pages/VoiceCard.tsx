// The Voice card on the Looks page (vision M10 §10, slice P2b): what the agent
// sounds like when replies are read aloud, the agent's own reason when it chose,
// and the owner's hand on it: this device's voices and the owner's ElevenLabs
// voices in one select, Hear it before saving, Save. Cael has no card: his
// voice, like his look, is his own.
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui";
import { useAgentName } from "@/lib/agentName";
import { t } from "@/lib/i18n";
import { localVoices, rememberVoice, speak, useSpeech } from "@/lib/speech";
import { deleteVoice, getElevenLabsVoices, putVoice } from "@/lib/voice";
import { type Engine, type OfferedVoice, type VoiceChoice, choiceFromPick, pickValue, voiceLine } from "@/lib/voice.logic";
import { fill } from "./setup/setup.logic";

const MUTED = { color: "var(--pc-text-muted)" } as const;

type Note = { tone: "ok" | "error"; text: string } | null;

export default function VoiceCard({ alias, onNote }: { alias: string; onNote: (note: Note) => void }) {
  const speech = useSpeech(alias);
  const shown = useAgentName(alias);
  const [local, setLocal] = useState<{ engine: "browser" | "phone"; voices: OfferedVoice[] } | null>(null);
  const [eleven, setEleven] = useState<OfferedVoice[]>([]);
  const [pick, setPick] = useState<string>("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void localVoices().then((l) => {
      if (!cancelled) setLocal(l);
    });
    getElevenLabsVoices()
      .then((r) => {
        if (!cancelled) setEleven(r.configured ? r.voices : []);
      })
      .catch(() => {
        if (!cancelled) setEleven([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // The select follows the saved choice until the owner touches it.
  useEffect(() => setPick(pickValue(speech.choice)), [speech.choice]);

  const offered = useMemo(() => {
    const groups: Array<{ engine: Engine; voices: OfferedVoice[] }> = [];
    if (local) groups.push(local);
    if (eleven.length) groups.push({ engine: "elevenlabs", voices: eleven });
    return groups;
  }, [local, eleven]);

  const picked: VoiceChoice | null = choiceFromPick(pick, offered);
  const dirty = pick !== pickValue(speech.choice);
  const words = {
    none: t("voice.none"),
    browser: t("voice.engine_browser"),
    phone: t("voice.engine_phone"),
    elevenlabs: t("voice.engine_elevenlabs"),
  };

  const hear = async () => {
    if (busy) return;
    setBusy(true);
    onNote(null);
    try {
      await speak(alias, fill(t("voice.sample"), { agent: shown }), picked);
    } catch (e) {
      onNote({ tone: "error", text: `${t("voice.failed")} ${e instanceof Error ? e.message : String(e)}` });
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (busy || !dirty) return;
    setBusy(true);
    onNote(null);
    try {
      if (picked) {
        const r = await putVoice(alias, picked);
        rememberVoice(alias, r.voice);
      } else {
        await deleteVoice(alias);
        rememberVoice(alias, null);
      }
      onNote({ tone: "ok", text: t("voice.saved") });
    } catch (e) {
      onNote({ tone: "error", text: `${t("voice.failed")} ${e instanceof Error ? e.message : String(e)}` });
    } finally {
      setBusy(false);
    }
  };

  const noVoicesHere = local !== null && local.voices.length === 0 && eleven.length === 0;

  return (
    <div className="card p-4 space-y-2" data-voice-card>
      <div className="cz-kicker">{t("voice.card_title")}</div>
      <p className="text-xs" style={MUTED}>
        {t("voice.card_help")}
      </p>
      <p className="text-sm" data-voice-line>
        {voiceLine(speech.choice, words)}
      </p>
      {speech.choice?.why ? (
        <p className="text-xs italic" style={MUTED} data-voice-why>
          “{speech.choice.why}”
        </p>
      ) : null}
      <div className="flex items-center gap-2 flex-wrap">
        <select className="cz-input" value={pick} onChange={(e) => setPick(e.target.value)} aria-label={t("voice.pick")} data-voice-select>
          <option value="">{t("voice.device_default")}</option>
          {local && local.voices.length ? (
            <optgroup label={t(local.engine === "phone" ? "voice.group_phone" : "voice.group_browser")}>
              {local.voices.map((v) => (
                <option key={`${local.engine}:${v.id}`} value={`${local.engine}:${v.id}`}>
                  {v.name}
                  {v.lang ? ` (${v.lang})` : ""}
                </option>
              ))}
            </optgroup>
          ) : null}
          {eleven.length ? (
            <optgroup label={t("voice.group_elevenlabs")}>
              {eleven.map((v) => {
                const tags = [v.accent, v.gender].filter(Boolean).join(", ");
                return (
                  <option key={`elevenlabs:${v.id}`} value={`elevenlabs:${v.id}`}>
                    {v.name}
                    {tags ? ` (${tags})` : ""}
                  </option>
                );
              })}
            </optgroup>
          ) : null}
        </select>
        <Button variant="ghost" size="sm" disabled={busy || speech.speaking || (!picked && !speech.available)} onClick={() => void hear()} data-voice-hear>
          {t("voice.hear")}
        </Button>
        <Button variant="primary" size="sm" disabled={busy || !dirty} onClick={() => void save()} data-voice-save>
          {busy ? t("voice.saving") : t("voice.save")}
        </Button>
      </div>
      <p className="text-xs" style={MUTED}>
        {noVoicesHere ? t("voice.no_voices_here") : t("voice.read_hint")}
      </p>
    </div>
  );
}
