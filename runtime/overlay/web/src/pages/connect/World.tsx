// The Ether Hollow card on the Connect page: the agent as a resident of the
// town. Register once (the gateway keeps the key; the page never sees it),
// then send the agent to town for a while and bring it back; the spending
// switch is the one config write the card makes itself. The town's own API
// is the `ether_hollow` tool's; the card only talks to /api/world.
import { useEffect, useState } from "react";
import { ExternalLink, Globe } from "lucide-react";

import { Badge, Button } from "@/components/ui";
import { getLook, getProp, patchConfig } from "@/lib/api";
import { t } from "@/lib/i18n";
import { enterWorld, getWorld, leaveWorld, registerWorld, wakeWorld, type WorldState, type WorldTagColor } from "@/lib/world";
import type { Slot } from "@/looks/looks.logic";
import { fill } from "../setup/setup.logic";
import {
  TAG_COLORS,
  VISITS,
  bioOk,
  clock,
  lookFor,
  minutesLeft,
  nameOk,
  rcText,
  spendOps,
  tagFor,
  townSite,
  wakeLine,
  wakeOps,
  type Visit,
} from "./world.logic";

const MUTED = { color: "var(--pc-text-muted)" } as const;
/** The page re-reads the presence while the agent is in town. */
const POLL_MS = 15_000;

function reason(e: unknown): string {
  const envelope = (e as { envelope?: { message?: unknown } } | null)?.envelope;
  if (envelope && typeof envelope.message === "string") return envelope.message;
  const text = e instanceof Error ? e.message : String(e);
  const wrapped = /^API \d+: (\{[\s\S]*\})$/.exec(text);
  if (wrapped) {
    try {
      const body = JSON.parse(wrapped[1]!) as { error?: unknown };
      if (typeof body.error === "string") return body.error;
    } catch {
      /* not JSON */
    }
  }
  return text;
}

export default function WorldCard({ agent, disabled }: { agent: string; disabled: boolean }) {
  const [state, setState] = useState<WorldState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"register" | "enter" | "leave" | "spend" | "wake" | "wake_now" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [bio, setBio] = useState("");
  const [colors, setColors] = useState<Partial<Record<Slot, string>> | null>(null);
  const [tag, setTag] = useState<WorldTagColor | null>(null);
  const [visit, setVisit] = useState<Visit>(60);
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));

  const load = async () => {
    try {
      const s = await getWorld();
      setState(s);
      setLoadError(null);
      setName((n) => (n === "" ? s.name : n));
    } catch (e) {
      setLoadError(reason(e));
    }
  };

  useEffect(() => {
    void load();
    // The look is the agent's; the town's swatches follow from its colors.
    getLook(agent)
      .then((r) => setColors(r.look?.colors ?? null))
      .catch(() => setColors(null));
  }, [agent]);

  useEffect(() => {
    if (!state?.presence.in_town) return;
    const id = window.setInterval(() => {
      setNow(Math.floor(Date.now() / 1000));
      void load();
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [state?.presence.in_town]);

  const chosenTag: WorldTagColor = tag ?? tagFor(colors);
  const registered = state?.registered === true;
  const inTown = state?.presence.in_town === true;
  const ready = state !== null && busy === null && !disabled;

  const register = async () => {
    if (!ready || registered) return;
    setError(null);
    setNotice(null);
    if (!nameOk(name)) {
      setError(t("world.bad_name"));
      return;
    }
    if (!bioOk(bio)) {
      setError(t("world.bad_bio"));
      return;
    }
    setBusy("register");
    try {
      const look = lookFor(colors);
      const r = await registerWorld({ name: name.trim(), bio: bio.trim() || undefined, look, color: chosenTag });
      if (!r.saved) {
        // The town registered the resident but the config write failed: the
        // gateway's answer carries the reason (and the key, once).
        setError(r.error ?? t("world.failed"));
      } else {
        setNotice(fill(t("world.registered"), { name: r.name }));
      }
      await load();
    } catch (e) {
      setError(`${t("world.failed")} ${reason(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const enter = async () => {
    if (!ready || !registered) return;
    setError(null);
    setNotice(null);
    setBusy("enter");
    try {
      await enterWorld(visit);
      setNow(Math.floor(Date.now() / 1000));
      await load();
    } catch (e) {
      setError(`${t("world.failed")} ${reason(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const leave = async () => {
    if (!ready) return;
    setError(null);
    setNotice(null);
    setBusy("leave");
    try {
      await leaveWorld();
      await load();
    } catch (e) {
      setError(`${t("world.failed")} ${reason(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const setSpend = async (on: boolean) => {
    if (!ready || !state || state.spend === on) return;
    setError(null);
    setNotice(null);
    setBusy("spend");
    try {
      await patchConfig(spendOps(on));
      setNotice(t(on ? "world.spend_on_saved" : "world.spend_off_saved"));
      await load();
    } catch (e) {
      setError(`${t("world.failed")} ${reason(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const setWake = async (on: boolean) => {
    if (!ready || !state || state.wake_on === on) return;
    setError(null);
    setNotice(null);
    setBusy("wake");
    try {
      // A wake runs with no one to answer a prompt: the resident agent's risk
      // profile must let the town tool through. Read the profile and its list;
      // without them the switch alone is written and the note says why.
      let profile: string | null = null;
      let autoApprove: string[] | null = null;
      if (on) {
        try {
          const p = await getProp(`agents.${state.agent}.risk_profile`);
          profile = typeof p.value === "string" && p.value.trim() ? p.value.trim() : null;
          if (profile) {
            const a = await getProp(`risk_profiles.${profile}.auto_approve`);
            autoApprove = Array.isArray(a.value) ? a.value.filter((x): x is string => typeof x === "string") : [];
          }
        } catch {
          profile = null;
        }
      }
      await patchConfig(wakeOps(on, profile, autoApprove));
      setNotice(t(on ? "world.wake_on_saved" : "world.wake_off_saved"));
      await load();
    } catch (e) {
      setError(`${t("world.failed")} ${reason(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const wakeNow = async () => {
    if (!ready || !registered) return;
    setError(null);
    setNotice(null);
    setBusy("wake_now");
    try {
      const r = await wakeWorld();
      setNotice(r.run.success ? t("world.woke") : fill(t("world.wake_failed"), { reason: r.run.output ?? r.run.status ?? "" }));
      await load();
    } catch (e) {
      setError(`${t("world.failed")} ${reason(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const site = townSite(state?.url ?? "");
  const me = state?.me ?? null;
  const rc = me?.passport?.rc;
  const place = me?.agent?.place;

  return (
    <section className="card cz-connect" data-connect="world" data-world={registered ? (inTown ? "in-town" : "resident") : "none"}>
      <div className="flex items-center gap-2 flex-wrap">
        <Globe className="h-5 w-5" aria-hidden="true" />
        <h2 className="text-base font-semibold text-pc-text">{t("world.title")}</h2>
        <Badge tone={registered ? "ok" : "neutral"}>{t(registered ? "world.status_resident" : "world.status_none")}</Badge>
        {state && state.open === false ? <Badge tone="neutral">{t("world.closed")}</Badge> : null}
      </div>
      <p className="text-sm" style={MUTED}>
        {t("world.body")}
      </p>
      <p className="cz-note">{t("world.unverified")}</p>
      <a className="cz-link" href={site} target="_blank" rel="noreferrer">
        {t("world.open_town")} <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
      </a>

      {loadError ? (
        <p className="text-sm" role="alert" style={{ color: "var(--color-status-error)" }}>
          {t("world.load_failed")} {loadError}
        </p>
      ) : null}

      {state && !registered ? (
        <>
          <label className="block" htmlFor="world-name">
            <div className="cz-kicker">{t("world.name")}</div>
            <input
              id="world-name"
              className="cz-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={24}
              autoCapitalize="words"
              autoCorrect="off"
              spellCheck={false}
            />
          </label>
          <p className="cz-note">{t("world.name_hint")}</p>
          <label className="block" htmlFor="world-bio">
            <div className="cz-kicker">{t("world.bio")}</div>
            <input id="world-bio" className="cz-input" value={bio} onChange={(e) => setBio(e.target.value)} maxLength={140} placeholder={t("world.bio_hint")} />
          </label>
          <div className="cz-kicker">{t("world.tag_color")}</div>
          <div className="cz-chip-row" role="radiogroup" aria-label={t("world.tag_color")}>
            {TAG_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                role="radio"
                aria-checked={chosenTag === c}
                className={`cz-chip${chosenTag === c ? " is-on" : ""}`}
                data-tag={c}
                onClick={() => setTag(c)}
              >
                {t(`world.color_${c}`)}
              </button>
            ))}
          </div>
          <p className="cz-note">{t("world.sprite_note")}</p>
          <div className="flex items-center gap-3 flex-wrap">
            <Button variant="primary" size="md" disabled={!ready || !nameOk(name)} onClick={() => void register()} data-world-action="register">
              {busy === "register" ? t("world.registering") : t("world.register")}
            </Button>
            <span className="text-xs" style={MUTED}>
              {t("world.register_try")}
            </span>
          </div>
        </>
      ) : null}

      {state && registered ? (
        <>
          <p className="text-sm" data-world-passport>
            {me
              ? fill(t("world.passport"), {
                  name: me.agent?.name ?? state.name,
                  rc: rcText(rc) || t("world.rc_unknown"),
                  place: place ? fill(t("world.at_place"), { place }) : t("world.place_unknown"),
                })
              : fill(t("world.passport_unavailable"), { reason: state.me_error ?? "" })}
            {me?.lease ? ` ${fill(t("world.lease"), { lot: me.lease.lot ?? "", due: me.lease.next_due ?? "" })}` : ""}
            {me?.timeout ? ` ${t("world.in_timeout")}` : ""}
          </p>

          {inTown ? (
            <>
              <p className="text-sm" data-world-presence>
                {fill(t("world.in_town"), { until: clock(state.presence.until), left: String(minutesLeft(state.presence, now)), beats: String(state.presence.beats) })}
              </p>
              <div className="flex items-center gap-3 flex-wrap">
                <Button variant="primary" size="md" disabled={!ready} onClick={() => void leave()} data-world-action="leave">
                  {busy === "leave" ? t("world.leaving") : t("world.leave")}
                </Button>
              </div>
            </>
          ) : (
            <>
              {state.presence.last_error ? <p className="cz-note">{fill(t("world.last_visit_ended"), { reason: state.presence.last_error })}</p> : null}
              <div className="cz-kicker">{t("world.visit_length")}</div>
              <div className="cz-chip-row" role="radiogroup" aria-label={t("world.visit_length")}>
                {VISITS.map((m) => (
                  <button key={m} type="button" role="radio" aria-checked={visit === m} className={`cz-chip${visit === m ? " is-on" : ""}`} onClick={() => setVisit(m)}>
                    {t(`world.visit_${m}`)}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-3 flex-wrap">
                <Button variant="primary" size="md" disabled={!ready} onClick={() => void enter()} data-world-action="enter">
                  {busy === "enter" ? t("world.sending") : t("world.send")}
                </Button>
                <span className="text-xs" style={MUTED}>
                  {t("world.send_try")}
                </span>
              </div>
            </>
          )}

          <div className="cz-kicker">{t("world.spend")}</div>
          <div className="cz-chip-row" role="radiogroup" aria-label={t("world.spend")}>
            {[false, true].map((on) => (
              <button
                key={String(on)}
                type="button"
                role="radio"
                aria-checked={state.spend === on}
                className={`cz-chip${state.spend === on ? " is-on" : ""}`}
                data-world-spend={String(on)}
                disabled={!ready}
                onClick={() => void setSpend(on)}
              >
                {t(on ? "world.spend_on" : "world.spend_off")}
              </button>
            ))}
          </div>
          <p className="cz-note">{t("world.spend_note")}</p>

          <div className="cz-kicker">{t("world.wake")}</div>
          <div className="cz-chip-row" role="radiogroup" aria-label={t("world.wake")}>
            {[false, true].map((on) => (
              <button
                key={String(on)}
                type="button"
                role="radio"
                aria-checked={state.wake_on === on}
                className={`cz-chip${state.wake_on === on ? " is-on" : ""}`}
                data-world-wake={String(on)}
                disabled={!ready}
                onClick={() => void setWake(on)}
              >
                {t(on ? "world.wake_on" : "world.wake_off")}
              </button>
            ))}
          </div>
          <p className="cz-note">{t("world.wake_note")}</p>
          <p className="text-sm" data-world-wake-line>
            {wakeLine(state.wake, { never: t("world.wake_never"), quiet: t("world.wake_quiet"), failed: t("world.wake_failed_short") })}
            {state.wake.last_error ? ` ${fill(t("world.wake_read_error"), { reason: state.wake.last_error })}` : ""}
          </p>
          <div className="flex items-center gap-3 flex-wrap">
            <button type="button" className="cz-btn-text" disabled={!ready} onClick={() => void wakeNow()} data-world-action="wake">
              {busy === "wake_now" ? t("world.waking") : t("world.wake_now")}
            </button>
            <span className="text-xs" style={MUTED}>
              {t("world.wake_now_hint")}
            </span>
          </div>
        </>
      ) : null}

      {error ? (
        <p className="text-sm" role="alert" style={{ color: "var(--color-status-error)" }}>
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="text-sm" role="status" style={{ color: "var(--color-status-success)" }}>
          {notice}
        </p>
      ) : null}
    </section>
  );
}
