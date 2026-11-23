// The Ether Hollow card on the Connect page: the agent as a resident of the
// town. Register once (the gateway keeps the key; the page never sees it),
// then send the agent to town for a while and bring it back; the spending
// switch is the one config write the card makes itself. The town's own API
// is the `ether_hollow` tool's; the card only talks to /api/world. With
// several agents (P6) a chip row picks which one the card is about; every
// call carries that alias, and the gateway keeps one resident per agent.
import { useEffect, useState } from "react";
import { ExternalLink, Globe } from "lucide-react";

import { Badge, Button } from "@/components/ui";
import { useAgentName } from "@/lib/agentName";
import { getLook, getProp, patchConfig } from "@/lib/api";
import { t } from "@/lib/i18n";
import {
  enterWorld,
  getWorld,
  getWorldLots,
  leaveWorld,
  payWorldRent,
  registerWorld,
  rentWorld,
  wakeWorld,
  type WorldLots,
  type WorldState,
  type WorldTagColor,
} from "@/lib/world";
import type { Slot } from "@/looks/looks.logic";
import { fill } from "../setup/setup.logic";
import {
  TAG_COLORS,
  VISITS,
  bioOk,
  clock,
  leaseLine,
  lookFor,
  lotLabel,
  minutesLeft,
  nameOk,
  rcText,
  residentCandidates,
  residentStatus,
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

/** One agent in the card's resident row: its name, and whether it lives in town. */
function ResidentChip({ alias, on, status, disabled, onPick }: { alias: string; on: boolean; status: "in_town" | "resident" | "none"; disabled: boolean; onPick: () => void }) {
  const label = useAgentName(alias);
  const word = t(status === "in_town" ? "world.resident_in_town" : status === "resident" ? "world.resident_is_resident" : "world.resident_not_yet");
  return (
    <button type="button" role="radio" aria-checked={on} className={`cz-chip${on ? " is-on" : ""}`} data-world-resident={alias} data-world-resident-status={status} disabled={disabled} onClick={onPick}>
      {label} · {word}
    </button>
  );
}

export default function WorldCard({ agent, agents, disabled }: { agent: string; agents: readonly string[]; disabled: boolean }) {
  // The agent the card is about: the page's, until the owner picks another in the resident row.
  const [picked, setPicked] = useState(agent);
  const [state, setState] = useState<WorldState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"register" | "enter" | "leave" | "spend" | "wake" | "wake_now" | "lots" | "rent" | "pay" | null>(null);
  const [lots, setLots] = useState<WorldLots | null>(null);
  const [lot, setLot] = useState<string | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [bio, setBio] = useState("");
  const [colors, setColors] = useState<Partial<Record<Slot, string>> | null>(null);
  const [tag, setTag] = useState<WorldTagColor | null>(null);
  const [visit, setVisit] = useState<Visit>(60);
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  const agentLabel = useAgentName(picked);
  const candidates = residentCandidates(agents.length ? agents : [agent]);

  useEffect(() => {
    setPicked(agent);
  }, [agent]);

  // The resident starts with the agent's own name (the town's rule is the same one), until the owner types another.
  useEffect(() => {
    if (agentLabel !== picked && nameOk(agentLabel)) setName((n) => (n === "" ? agentLabel : n));
  }, [agentLabel, picked]);

  const load = async () => {
    try {
      const s = await getWorld(picked);
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
    getLook(picked)
      .then((r) => setColors(r.look?.colors ?? null))
      .catch(() => setColors(null));
  }, [picked]);

  /** Another agent in the resident row: the card starts over for it. */
  const pick = (alias: string) => {
    if (alias === picked) return;
    setPicked(alias);
    setState(null);
    setLots(null);
    setLot(null);
    setAgreed(false);
    setName("");
    setBio("");
    setTag(null);
    setError(null);
    setNotice(null);
  };

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
      const r = await registerWorld({ name: name.trim(), bio: bio.trim() || undefined, look, color: chosenTag }, picked);
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
      await enterWorld(visit, picked);
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
      await leaveWorld(picked);
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
      await patchConfig(spendOps(on, state.spend_path));
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
      const r = await wakeWorld(undefined, picked);
      setNotice(r.run.success ? t("world.woke") : fill(t("world.wake_failed"), { reason: r.run.output ?? r.run.status ?? "" }));
      await load();
    } catch (e) {
      setError(`${t("world.failed")} ${reason(e)}`);
    } finally {
      setBusy(null);
    }
  };

  // The Rent section: the open lots and the agreement, read when the owner opens it.
  const openLots = async () => {
    if (!ready || !registered) return;
    setError(null);
    setBusy("lots");
    try {
      setLots(await getWorldLots(picked));
    } catch (e) {
      setError(`${t("world.failed")} ${reason(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const rent = async () => {
    if (!ready || !state || !lots || !lot || !agreed || !state.spend) return;
    const version = lots.agreement.version ?? "";
    if (!version) return;
    setError(null);
    setNotice(null);
    setBusy("rent");
    try {
      const r = await rentWorld(lot, version, picked);
      setNotice(fill(t("world.rented"), { place: r.lease?.place ?? lot, balance: String(r.balance ?? "") }));
      setLots(null);
      setLot(null);
      setAgreed(false);
      await load();
    } catch (e) {
      setError(`${t("world.failed")} ${reason(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const pay = async () => {
    if (!ready || !state?.spend) return;
    setError(null);
    setNotice(null);
    setBusy("pay");
    try {
      const r = await payWorldRent(picked);
      setNotice(fill(t("world.paid"), { balance: String(r.balance ?? "") }));
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
  const lease = me?.lease ?? null;
  const resetOn = me?.agent?.reset_on;

  return (
    <section className="card cz-connect" data-connect="world" data-world={registered ? (inTown ? "in-town" : "resident") : "none"} data-world-agent={picked}>
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

      {candidates.length > 1 ? (
        <>
          <div className="cz-kicker">{t("world.residents")}</div>
          <div className="cz-chip-row" role="radiogroup" aria-label={t("world.residents")} data-world-residents>
            {candidates.map((a) => (
              <ResidentChip key={a} alias={a} on={picked === a} status={residentStatus(state?.residents, a)} disabled={disabled} onPick={() => pick(a)} />
            ))}
          </div>
          <p className="cz-note">{t("world.residents_hint")}</p>
        </>
      ) : null}

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
            {me?.timeout ? ` ${t("world.in_timeout")}` : ""}
          </p>
          {resetOn ? (
            <p className="cz-note" role="alert" data-world-reset>
              {fill(t("world.reset_warning"), { date: resetOn })}
            </p>
          ) : null}

          {/* The lot: renting behind the spending switch, the lease with its clocks. */}
          <div className="cz-kicker">{t("world.lot")}</div>
          {lease ? (
            <>
              <p className="text-sm" data-world-lease>
                {leaseLine(lease, {
                  renting: t("world.lease_renting"),
                  next: t("world.lease_next"),
                  owing: t("world.lease_owing"),
                  missed: t("world.lease_missed"),
                  repossess: t("world.lease_repossess"),
                })}
              </p>
              <p className="cz-note">{t("world.lease_note")}</p>
              {lease.owing || (lease.missed ?? 0) > 0 ? (
                <div className="flex items-center gap-3 flex-wrap">
                  <Button variant="primary" size="md" disabled={!ready || !state.spend} onClick={() => void pay()} data-world-action="pay">
                    {busy === "pay" ? t("world.paying") : t("world.pay")}
                  </Button>
                  {!state.spend ? (
                    <span className="text-xs" style={MUTED}>
                      {t("world.spend_first")}
                    </span>
                  ) : null}
                </div>
              ) : null}
            </>
          ) : lots ? (
            <>
              {lots.lots.length === 0 ? <p className="cz-note">{t("world.no_lots")}</p> : null}
              {lots.lots.length ? (
                <div className="cz-chip-row" role="radiogroup" aria-label={t("world.lot")}>
                  {lots.lots.map((l) => (
                    <button key={l.id} type="button" role="radio" aria-checked={lot === l.id} className={`cz-chip${lot === l.id ? " is-on" : ""}`} data-world-lot={l.id} onClick={() => setLot(l.id)}>
                      {lotLabel(l, t("world.per_month"))}
                    </button>
                  ))}
                </div>
              ) : null}
              {lots.agreement.lines?.length ? (
                <div className="cz-bubble" data-world-agreement>
                  <div className="cz-kicker">{lots.agreement.title ?? t("world.agreement")}</div>
                  <ul className="cz-bubble-text text-sm" style={{ paddingLeft: "1.1em", listStyle: "disc" }}>
                    {lots.agreement.lines.map((line, i) => (
                      <li key={i}>{line}</li>
                    ))}
                  </ul>
                </div>
              ) : lots.agreement.error ? (
                <p className="cz-note">{fill(t("world.agreement_unavailable"), { reason: lots.agreement.error })}</p>
              ) : null}
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} data-world-agree />
                {fill(t("world.agree"), { version: lots.agreement.version ?? "" })}
              </label>
              <div className="flex items-center gap-3 flex-wrap">
                <Button
                  variant="primary"
                  size="md"
                  disabled={!ready || !lot || !agreed || !state.spend || !lots.agreement.version}
                  onClick={() => void rent()}
                  data-world-action="rent"
                >
                  {busy === "rent" ? t("world.renting") : t("world.rent")}
                </Button>
                <span className="text-xs" style={MUTED}>
                  {state.spend ? t("world.rent_hint") : t("world.spend_first")}
                </span>
              </div>
            </>
          ) : (
            <div className="flex items-center gap-3 flex-wrap">
              <button type="button" className="cz-btn-text" disabled={!ready} onClick={() => void openLots()} data-world-action="lots">
                {busy === "lots" ? t("world.lots_loading") : t("world.rent_a_lot")}
              </button>
              <span className="text-xs" style={MUTED}>
                {t("world.rent_a_lot_hint")}
              </span>
            </div>
          )}

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
