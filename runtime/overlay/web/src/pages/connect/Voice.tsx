// The ElevenLabs card on the Connect page (vision M10 §10, slice P2b): one key
// and the agent can speak in a voice that sounds like a person, on every
// device. The key goes into upstream's own `[providers.tts.elevenlabs.default]`
// (encrypted at rest like every secret); the voices come back through the
// Runtime (GET /api/voice/elevenlabs), so the agent's `voice` tool and the
// Looks page see the same list.
import { useEffect, useState } from "react";
import { AudioLines, ExternalLink, Eye, EyeOff } from "lucide-react";

import { Badge, Button } from "@/components/ui";
import { createMapKey, getProp, patchConfig } from "@/lib/api";
import { t } from "@/lib/i18n";
import { getElevenLabsVoices } from "@/lib/voice";
import { ELEVEN_MODEL, ELEVEN_PATH, ELEVEN_SECTION, elevenOps, keyOk } from "@/lib/voice.logic";
import { fill } from "../setup/setup.logic";

const MUTED = { color: "var(--pc-text-muted)" } as const;
const SITE = "https://elevenlabs.io/app/settings/api-keys";

export default function VoiceCard({ disabled }: { disabled: boolean }) {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [count, setCount] = useState<number | null>(null);
  const [key, setKey] = useState("");
  const [shown, setShown] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    getProp(`${ELEVEN_SECTION}.default.api_key`)
      .then((p) => {
        if (!cancelled) setConfigured(p.populated === true);
      })
      .catch(() => {
        if (!cancelled) setConfigured(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!configured) return;
    let cancelled = false;
    getElevenLabsVoices()
      .then((r) => {
        if (!cancelled) setCount(r.voices.length);
      })
      .catch(() => {
        if (!cancelled) setCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [configured]);

  const save = async () => {
    const k = key.trim();
    if (busy || disabled || !keyOk(k)) return;
    setBusy(true);
    setNote(null);
    try {
      // The entry first (a no-op when it exists), then its key and model.
      await createMapKey(ELEVEN_SECTION, "default").catch(() => undefined);
      try {
        await patchConfig(elevenOps(k));
      } catch {
        await patchConfig([{ op: "add", path: ELEVEN_PATH, value: { api_key: k, model: ELEVEN_MODEL } }]);
      }
      setKey("");
      const r = await getElevenLabsVoices();
      setCount(r.voices.length);
      setConfigured(true);
      setNote({ tone: "ok", text: fill(t("voice.eleven_saved"), { n: String(r.voices.length) }) });
    } catch (e) {
      setNote({ tone: "error", text: `${t("voice.eleven_failed")} ${e instanceof Error ? e.message : String(e)}` });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card cz-connect" data-connect="voice" data-voice={configured ? "on" : "off"}>
      <div className="flex items-center gap-2 flex-wrap">
        <AudioLines className="h-5 w-5" aria-hidden="true" />
        <h2 className="text-base font-semibold text-pc-text">{t("voice.eleven_title")}</h2>
        <Badge tone={configured ? "ok" : "neutral"}>{t(configured ? "voice.eleven_on" : "voice.eleven_off")}</Badge>
        {configured && count !== null ? <Badge tone="neutral">{fill(t("voice.eleven_voices"), { n: String(count) })}</Badge> : null}
      </div>
      <p className="text-sm" style={MUTED}>
        {t("voice.eleven_body")}
      </p>
      <a className="cz-link" href={SITE} target="_blank" rel="noreferrer">
        {t("voice.eleven_link")} <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
      </a>
      <div className="space-y-1">
        <label className="cz-kicker" htmlFor="eleven-key">
          {t("voice.eleven_key")}
        </label>
        <div className="flex items-center gap-2">
          <input
            id="eleven-key"
            className="cz-input"
            type={shown ? "text" : "password"}
            value={key}
            onChange={(e) => setKey(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void save();
              }
            }}
            autoComplete="off"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            placeholder="sk_…"
            data-eleven-key
          />
          <Button variant="ghost" size="sm" onClick={() => setShown((v) => !v)} aria-label={shown ? "Hide" : "Show"} aria-pressed={shown}>
            {shown ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
          </Button>
        </div>
        {key.trim() !== "" && !keyOk(key) ? (
          <p className="cz-note">{t("voice.eleven_rule")}</p>
        ) : null}
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        <Button variant="primary" size="md" disabled={disabled || busy || !keyOk(key)} onClick={() => void save()} data-eleven-save>
          {busy ? t("voice.eleven_working") : t(configured ? "voice.eleven_update" : "voice.eleven_connect")}
        </Button>
      </div>
      {note ? (
        <p className="text-sm" role={note.tone === "error" ? "alert" : "status"} style={note.tone === "error" ? { color: "var(--color-status-error)" } : MUTED}>
          {note.text}
        </p>
      ) : null}
    </section>
  );
}
