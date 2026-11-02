// Cael in the top bar of every page (vision §3.4: "explain this screen",
// answered by the Guide). The button is his look, blinking. The panel says
// what the screen is and the next step, in his words, with no model needed;
// below that the owner can ask him anything about it, and the answer streams
// from the `cael` agent over the gateway's chat socket in one guide
// conversation the browser keeps. Without Cael set up, the panel still
// explains the screen and points at the setup.
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useLocation } from "react-router-dom";
import { Send, X } from "lucide-react";

import { getQuickstartState } from "@/lib/api";
import { t } from "@/lib/i18n";
import { WebSocketClient } from "@/lib/ws";
import { AgentLook } from "@/looks/Look";
import {
  EMPTY_REPLY,
  caelReady,
  foldReply,
  guideSessionId,
  nextRoute,
  question,
  questionOk,
  screenKeys,
  screenOf,
  type Reply,
} from "./guide.logic";

/** The page's title string key per screen (the top bar's own table, by screen). */
const TITLE_KEYS: Record<ReturnType<typeof screenOf>, string> = {
  home: "nav.home",
  bodies: "nav.bodies",
  memory: "nav.memory",
  procedures: "nav.procedures",
  agents: "nav.agents",
  agent: "nav.agent",
  looks: "nav.looks",
  shop: "nav.shop",
  setup: "nav.setup",
  quickstart: "nav.quickstart",
  config: "nav.config",
  tools: "nav.tools",
  skills: "nav.skills",
  sops: "nav.sops",
  runs: "nav.runs",
  integrations: "nav.integrations",
  plugins: "nav.plugins",
  cron: "nav.cron",
  dashboard: "nav.dashboard",
  logs: "nav.logs",
  pairing: "nav.pairing",
  doctor: "nav.doctor",
  canvas: "nav.canvas",
  acp: "nav.acp",
  other: "sidebar.brand",
};

/** How long a question may wait for the whole answer. */
const ANSWER_TIMEOUT_MS = 90_000;

export function CaelButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="cz-cael-btn"
        aria-label={t("guide.open")}
        title={t("guide.open")}
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <AgentLook alias="cael" size={30} />
      </button>
      {/* Into the body: the top bar's backdrop blur would otherwise be the
          containing block of this fixed panel and clip it to 56 px. */}
      {open && typeof document !== "undefined" ? createPortal(<GuidePanel onClose={() => setOpen(false)} />, document.body) : null}
    </>
  );
}

function GuidePanel({ onClose }: { onClose: () => void }) {
  const { pathname } = useLocation();
  const screen = screenOf(pathname);
  const keys = screenKeys(screen);
  const title = t(TITLE_KEYS[screen]);
  const next = nextRoute(screen);
  const [agents, setAgents] = useState<string[] | null>(null);
  const [text, setText] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [reply, setReply] = useState<Reply | null>(null);
  const [busy, setBusy] = useState(false);
  const client = useRef<WebSocketClient | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    getQuickstartState()
      .then((s) => {
        if (!cancelled) setAgents(s.agents);
      })
      .catch(() => {
        if (!cancelled) setAgents([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Escape closes; the socket and the timer go with the panel.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    panel.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      client.current?.disconnect();
      client.current = null;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [onClose]);

  const finish = () => {
    setBusy(false);
    client.current?.disconnect();
    client.current = null;
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  };

  const ask = () => {
    if (busy || !questionOk(text)) return;
    const q = text.trim();
    setAsked(q);
    setText("");
    setReply(EMPTY_REPLY);
    setBusy(true);
    let storage: Storage | null = null;
    try {
      storage = window.localStorage;
    } catch {
      storage = null;
    }
    const ws = new WebSocketClient({ agentAlias: "cael", sessionId: guideSessionId(storage), autoReconnect: false });
    client.current = ws;
    let current: Reply = EMPTY_REPLY;
    ws.onMessage = (msg) => {
      // Session bookkeeping messages carry no text; the fold ignores them.
      current = foldReply(current, msg);
      setReply(current);
      if (current.done) finish();
    };
    ws.onOpen = () => {
      try {
        ws.sendMessage(question(title, pathname, q));
      } catch (e) {
        current = { ...current, done: true, error: e instanceof Error ? e.message : String(e) };
        setReply(current);
        finish();
      }
    };
    ws.onClose = () => {
      if (!current.done) {
        current = { ...current, done: true, error: current.text ? null : t("guide.closed") };
        setReply(current);
        finish();
      }
    };
    ws.onError = () => {
      if (!current.done) {
        current = { ...current, done: true, error: t("guide.closed") };
        setReply(current);
        finish();
      }
    };
    timer.current = setTimeout(() => {
      if (!current.done) {
        current = { ...current, done: true, error: current.text ? null : t("guide.timeout") };
        setReply(current);
        finish();
      }
    }, ANSWER_TIMEOUT_MS);
    ws.connect();
  };

  const ready = agents === null ? null : caelReady(agents);

  return (
    <div className="cz-guide-backdrop" onClick={onClose} role="presentation">
      <div
        ref={panel}
        className="cz-guide-panel"
        role="dialog"
        aria-modal="true"
        aria-label={t("guide.title")}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cz-guide-head">
          <AgentLook alias="cael" size={56} talking={busy} />
          <div className="min-w-0 flex-1">
            <div className="cz-kicker cz-kicker-violet">{t("guide.title")}</div>
            <div className="text-sm font-semibold text-pc-text truncate">{t("guide.this_screen")} {title}</div>
          </div>
          <button type="button" className="cz-icon-btn cz-guide-close" aria-label={t("guide.close")} onClick={onClose}>
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="cz-bubble cz-guide-bubble">
          <div className="cz-bubble-text">
            <p>{t(keys.text)}</p>
            <p className="cz-note">
              {t(keys.next)}{" "}
              {next ? (
                <Link to={next} className="underline" onClick={onClose}>
                  {t("guide.go")}
                </Link>
              ) : null}
            </p>
          </div>
        </div>

        {asked ? (
          <div className="cz-guide-thread" aria-live="polite">
            <div className="cz-guide-q">{asked}</div>
            <div className="cz-guide-a">
              {reply?.text ? reply.text : busy ? t("guide.thinking") : null}
              {reply?.error ? <div className="cz-guide-err">{reply.error}</div> : null}
            </div>
          </div>
        ) : null}

        {ready === false ? (
          <p className="cz-note">
            {t("guide.not_set_up")}{" "}
            <Link to="/setup" className="underline" onClick={onClose}>
              {t("guide.set_up")}
            </Link>
          </p>
        ) : (
          <form
            className="cz-guide-ask"
            onSubmit={(e) => {
              e.preventDefault();
              ask();
            }}
          >
            <input
              className="cz-input"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={t("guide.ask_placeholder")}
              aria-label={t("guide.ask_placeholder")}
              disabled={busy || ready === null}
              maxLength={2000}
              autoFocus
            />
            <button type="submit" className="cz-btn cz-btn-primary cz-guide-send" disabled={busy || ready !== true || !questionOk(text)} aria-label={t("guide.send")}>
              <Send className="h-4 w-4" aria-hidden="true" />
              <span>{t("guide.send")}</span>
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
