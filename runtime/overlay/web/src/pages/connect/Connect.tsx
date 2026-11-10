// The Connect page (vision §3.4, the Guide everywhere): your apps through
// Maton, your home through Home Assistant, a 3D printer on your Wi-Fi, each
// from one box or two, with Cael's words beside each. No shell: the page
// writes what scripts/maton-connect.sh, scripts/home-connect.sh and
// runtime/caelza.printer.example.toml write, through the gateway's config
// API (connect.logic.ts says how), and asks the Runtime to put the bundled
// printer skill on disk (/api/connect/skills). Keys never show again: the
// list only says whether one is set.
import { useEffect, useState } from "react";
import { Check, ExternalLink, Eye, EyeOff, House, Printer, Sparkles } from "lucide-react";

import { Badge, Button, PageHeader } from "@/components/ui";
import {
  createMapKey,
  getConnectSkills,
  getProp,
  getQuickstartState,
  installConnectSkill,
  listProps,
  patchConfig,
} from "@/lib/api";
import { t } from "@/lib/i18n";
import { fill } from "../setup/setup.logic";
import {
  HOME_ASSISTANT,
  MATON,
  PRINTER_KINDS,
  PRINTER_SKILL,
  agentFor,
  bearer,
  homeAssistantAddress,
  homeAssistantUrl,
  printerHost,
  printerOps,
  secretOk,
  serverConnected,
  serverOps,
  serverUrl,
  stringArray,
  type ListedProp,
  type PrinterKind,
} from "./connect.logic";

const MUTED = { color: "var(--pc-text-muted)" } as const;

type Which = "maton" | "homeassistant" | "printer";

/** The gateway's reason when it gave one, else the error's own words. */
function errorText(e: unknown): string {
  const envelope = (e as { envelope?: { message?: unknown } } | null)?.envelope;
  if (envelope && typeof envelope.message === "string") return envelope.message;
  const text = e instanceof Error ? e.message : String(e);
  const wrapped = /^API \d+: (\{[\s\S]*\})$/.exec(text);
  if (wrapped) {
    try {
      const body = JSON.parse(wrapped[1]!) as { error?: unknown; message?: unknown };
      if (typeof body.error === "string") return body.error;
      if (typeof body.message === "string") return body.message;
    } catch {
      /* not JSON after all */
    }
  }
  return text;
}

/** What the Runtime says is connected, read once and after every change. */
interface Known {
  agent: string;
  servers: ListedProp[];
  bundles: string[];
  hosts: string[];
  skillInstalled: boolean;
}

async function readKnown(): Promise<Known> {
  const state = await getQuickstartState();
  const agent = agentFor(state.agents);
  const [servers, bundles, hosts, skills] = await Promise.all([
    listProps("mcp.servers").then((r) => r.entries as ListedProp[]).catch(() => [] as ListedProp[]),
    getProp(`agents.${agent}.mcp_bundles`).then((r) => stringArray(r.value)).catch(() => [] as string[]),
    getProp("http_request.allowed_private_hosts").then((r) => stringArray(r.value)).catch(() => [] as string[]),
    getConnectSkills(agent).catch(() => null),
  ]);
  return { agent, servers, bundles, hosts, skillInstalled: skills?.skills[PRINTER_SKILL]?.installed === true };
}

function SecretBox({
  id,
  label,
  value,
  onChange,
  onEnter,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  onEnter: () => void;
  placeholder?: string;
}) {
  const [shown, setShown] = useState(false);
  return (
    <label className="block" htmlFor={id}>
      <div className="cz-kicker">{label}</div>
      <div className="cz-input-row">
        <input
          id={id}
          className="cz-input"
          type={shown ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              onEnter();
            }
          }}
          placeholder={placeholder}
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          autoComplete="off"
        />
        <button
          type="button"
          className="cz-icon-btn"
          aria-label={t(shown ? "setup.key_hide" : "setup.key_show")}
          onClick={() => setShown((v) => !v)}
        >
          {shown ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
        </button>
      </div>
    </label>
  );
}

function Status({ on }: { on: boolean }) {
  return <Badge tone={on ? "ok" : "neutral"}>{t(on ? "connect.connected" : "connect.not_connected")}</Badge>;
}

export default function Connect() {
  const [known, setKnown] = useState<Known | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState<Which | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [matonKey, setMatonKey] = useState("");
  const [haAddress, setHaAddress] = useState<string>(HOME_ASSISTANT.defaultAddress);
  const [haToken, setHaToken] = useState("");
  const [printerAddress, setPrinterAddress] = useState("");
  const [printerKind, setPrinterKind] = useState<PrinterKind>("moonraker");
  const [octoKey, setOctoKey] = useState("");

  useEffect(() => {
    let cancelled = false;
    readKnown()
      .then((k) => {
        if (cancelled) return;
        setKnown(k);
        const ha = serverUrl(k.servers, HOME_ASSISTANT.name);
        if (ha) setHaAddress(homeAssistantAddress(ha));
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(errorText(e));
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const agent = known?.agent ?? "main";
  const matonOn = known ? serverConnected(known.servers, MATON.name) && known.bundles.includes(MATON.name) : false;
  const haOn = known ? serverConnected(known.servers, HOME_ASSISTANT.name) && known.bundles.includes(HOME_ASSISTANT.name) : false;
  const printerOn = known ? known.skillInstalled && known.hosts.length > 0 : false;

  const finish = async (which: Which) => {
    setNotice(fill(t("connect.done"), { agent }));
    setKnown(await readKnown());
    if (which === "maton") setMatonKey("");
    if (which === "homeassistant") setHaToken("");
    if (which === "printer") setOctoKey("");
  };

  // A row in `[[mcp.servers]]` is a keyed list entry: made by name first (a
  // second make of the same name is a no-op or a refusal; either way the row is
  // there), then filled, bundled and granted in one patch the Runtime
  // validates as a whole.
  const connectServer = async (which: "maton" | "homeassistant") => {
    if (busy || !known) return;
    const spec =
      which === "maton"
        ? { name: MATON.name, url: MATON.url as string | null, timeout: MATON.timeout, secret: matonKey, example: MATON.url }
        : {
            name: HOME_ASSISTANT.name,
            url: homeAssistantUrl(haAddress),
            timeout: HOME_ASSISTANT.timeout,
            secret: haToken,
            example: HOME_ASSISTANT.defaultAddress,
          };
    setError(null);
    setNotice(null);
    if (!spec.url) {
      setError(fill(t("connect.bad_address"), { example: spec.example }));
      return;
    }
    if (!secretOk(spec.secret)) {
      setError(t("connect.bad_key"));
      return;
    }
    setBusy(which);
    try {
      try {
        await createMapKey("mcp.servers", spec.name);
      } catch (e) {
        if (!serverUrl(known.servers, spec.name)) throw e;
      }
      await patchConfig(serverOps(spec.name, spec.url, spec.timeout, bearer(spec.secret), agent, known.bundles));
      await finish(which);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  };

  const connectPrinter = async () => {
    if (busy || !known) return;
    setError(null);
    setNotice(null);
    const host = printerHost(printerAddress);
    if (!host) {
      setError(fill(t("connect.bad_address"), { example: "192.168.1.40" }));
      return;
    }
    if (printerKind === "octoprint" && !secretOk(octoKey)) {
      setError(t("connect.bad_key"));
      return;
    }
    setBusy("printer");
    try {
      await patchConfig(printerOps(host, printerKind, octoKey, known.hosts));
      await installConnectSkill(PRINTER_SKILL, agent);
      await finish("printer");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  };

  const ready = known !== null && busy === null;

  return (
    <div className="p-6 space-y-4">
      <PageHeader title={t("connect.title")} description={t("connect.description")} />

      <section className="cz-bubble" aria-label={t("setup.cael_says")}>
        <div className="cz-kicker cz-kicker-violet">{t("setup.cael_says")}</div>
        <div className="cz-bubble-text">
          <p>{t("connect.cael")}</p>
          <p className="cz-note">{known ? fill(t("connect.for_agent"), { agent }) : t("connect.loading")}</p>
        </div>
      </section>

      {error ? (
        <div className="text-sm flex items-center gap-3 flex-wrap" role="alert" style={{ color: "var(--color-status-error)" }}>
          <span>
            {t("connect.failed")} {error}
          </span>
          {known === null ? (
            <button
              type="button"
              className="cz-btn-text"
              onClick={() => {
                setError(null);
                setAttempt((n) => n + 1);
              }}
            >
              {t("connect.retry")}
            </button>
          ) : null}
        </div>
      ) : null}
      {notice ? (
        <div className="text-sm" role="status" style={{ color: "var(--color-status-success)" }}>
          {notice}
        </div>
      ) : null}

      <div className="space-y-4">
        {/* Your apps, through Maton. */}
        <section className="card cz-connect" data-connect="maton">
          <div className="flex items-center gap-2 flex-wrap">
            <Sparkles className="h-5 w-5" aria-hidden="true" />
            <h2 className="text-base font-semibold text-pc-text">{t("connect.apps_title")}</h2>
            <Status on={matonOn} />
          </div>
          <p className="text-sm" style={MUTED}>
            {t("connect.apps_body")}
          </p>
          <a className="cz-link" href={MATON.site} target="_blank" rel="noreferrer">
            {t("connect.apps_link")} <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
          <SecretBox
            id="maton-key"
            label={t("connect.apps_key")}
            value={matonKey}
            onChange={setMatonKey}
            onEnter={() => void connectServer("maton")}
          />
          <div className="flex items-center gap-3 flex-wrap">
            <Button variant="primary" size="md" disabled={!ready || matonKey.trim() === ""} onClick={() => void connectServer("maton")}>
              {busy === "maton" ? t("connect.working") : matonOn ? t("connect.update_key") : t("connect.connect")}
            </Button>
            <span className="text-xs" style={MUTED}>
              {t("connect.apps_try")}
            </span>
          </div>
        </section>

        {/* The smart home, through Home Assistant. */}
        <section className="card cz-connect" data-connect="homeassistant">
          <div className="flex items-center gap-2 flex-wrap">
            <House className="h-5 w-5" aria-hidden="true" />
            <h2 className="text-base font-semibold text-pc-text">{t("connect.home_title")}</h2>
            <Status on={haOn} />
          </div>
          <p className="text-sm" style={MUTED}>
            {t("connect.home_body")}
          </p>
          <p className="cz-note">{t("connect.home_unverified")}</p>
          <label className="block" htmlFor="ha-address">
            <div className="cz-kicker">{t("connect.home_address")}</div>
            <input
              id="ha-address"
              className="cz-input"
              value={haAddress}
              onChange={(e) => setHaAddress(e.target.value)}
              placeholder={HOME_ASSISTANT.defaultAddress}
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              inputMode="url"
            />
          </label>
          <SecretBox
            id="ha-token"
            label={t("connect.home_token")}
            value={haToken}
            onChange={setHaToken}
            onEnter={() => void connectServer("homeassistant")}
          />
          <div className="flex items-center gap-3 flex-wrap">
            <Button
              variant="primary"
              size="md"
              disabled={!ready || haToken.trim() === "" || haAddress.trim() === ""}
              onClick={() => void connectServer("homeassistant")}
            >
              {busy === "homeassistant" ? t("connect.working") : haOn ? t("connect.update_key") : t("connect.connect")}
            </Button>
            <span className="text-xs" style={MUTED}>
              {t("connect.home_try")}
            </span>
          </div>
        </section>

        {/* A 3D printer on the Wi-Fi. */}
        <section className="card cz-connect" data-connect="printer">
          <div className="flex items-center gap-2 flex-wrap">
            <Printer className="h-5 w-5" aria-hidden="true" />
            <h2 className="text-base font-semibold text-pc-text">{t("connect.printer_title")}</h2>
            <Status on={printerOn} />
          </div>
          <p className="text-sm" style={MUTED}>
            {t("connect.printer_body")}
          </p>
          <p className="cz-note">{t("connect.printer_unverified")}</p>
          {known && known.hosts.length ? (
            <p className="cz-note">
              <Check className="inline h-3.5 w-3.5" aria-hidden="true" /> {fill(t("connect.printer_allowed"), { hosts: known.hosts.join(", ") })}
              {known.skillInstalled ? ` ${fill(t("connect.printer_skill_installed"), { agent })}` : ""}
            </p>
          ) : null}
          <label className="block" htmlFor="printer-address">
            <div className="cz-kicker">{t("connect.printer_address")}</div>
            <input
              id="printer-address"
              className="cz-input"
              value={printerAddress}
              onChange={(e) => setPrinterAddress(e.target.value)}
              placeholder="192.168.1.40"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              inputMode="url"
            />
          </label>
          <div className="cz-kicker">{t("connect.printer_kind")}</div>
          <div className="cz-chip-row" role="radiogroup" aria-label={t("connect.printer_kind")}>
            {PRINTER_KINDS.map((k) => (
              <button
                key={k}
                type="button"
                role="radio"
                aria-checked={printerKind === k}
                className={`cz-chip${printerKind === k ? " is-on" : ""}`}
                onClick={() => setPrinterKind(k)}
              >
                {t(k === "moonraker" ? "connect.printer_moonraker" : "connect.printer_octoprint")}
              </button>
            ))}
          </div>
          {printerKind === "octoprint" ? (
            <SecretBox id="octoprint-key" label={t("connect.printer_key")} value={octoKey} onChange={setOctoKey} onEnter={() => void connectPrinter()} />
          ) : null}
          <div className="flex items-center gap-3 flex-wrap">
            <Button
              variant="primary"
              size="md"
              disabled={!ready || printerAddress.trim() === "" || (printerKind === "octoprint" && octoKey.trim() === "")}
              onClick={() => void connectPrinter()}
            >
              {busy === "printer" ? t("connect.working") : t("connect.connect")}
            </Button>
            <span className="text-xs" style={MUTED}>
              {t("connect.printer_try")}
            </span>
          </div>
        </section>
      </div>
    </div>
  );
}
