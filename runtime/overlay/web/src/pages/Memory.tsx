// The Memory page: the Mind (xanima brain service) at a glance, recall by
// query, forget by node, and the review queue. Phone-first: one column at
// 390 px, cards stack. Everything goes through the gateway (`/api/mind/*`),
// which holds the per-agent tokens.
import { useCallback, useEffect, useState } from 'react';
import { Brain, Check, Copy, Download, Link2, RefreshCw, Search, Smartphone, Trash2 } from 'lucide-react';

import { Badge, Button, Card, ConfirmDialog, PageHeader, Select, StatCard } from '@/components/ui';
import { createMapKey, deleteMapKey, patchConfig } from '@/lib/api';
import {
  decideMindReview,
  getMindInstall,
  getMindReview,
  getMindShare,
  getMindStatus,
  mindForget,
  mindRecall,
  probeMindCode,
  startMindInstall,
  startMindShare,
  stopMindShare,
  type MindInstall,
  type MindRecallHit,
  type MindReviewItem,
  type MindShareResult,
  type MindShareState,
  type MindStatus,
} from '@/lib/mind';
import { brainTone, brainTotals, preview, scoreLabel, serviceLine, statusHighlights } from './mind.logic';
import { POLL_MS, installBackendOps, megabytes, percent, stageLabel } from './mind.install.logic';
import {
  STORAGE_KEY,
  STORAGE_PATH,
  candidateLabel,
  cleanCode,
  devicesRole,
  isListening,
  joinOps,
  leaveBackendOps,
  preferredCandidate,
  restartNote,
} from './mind.share.logic';

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

export default function Memory() {
  const [agent, setAgent] = useState<string | undefined>(undefined);
  const [status, setStatus] = useState<MindStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setStatusError(null);
    getMindStatus(agent)
      .then((s) => {
        if (!cancelled) setStatus(s);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setStatusError(errorText(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [agent, reload]);

  const refresh = useCallback(() => setReload((n) => n + 1), []);
  // What the last devices action said (joined, left); kept here because the
  // card that said it is replaced the moment the status re-reads.
  const [devicesNote, setDevicesNote] = useState<string | null>(null);

  if (statusError) {
    return (
      <div className="p-6">
        <div
          role="alert"
          className="space-y-3 rounded-[var(--radius-md)] border border-status-error/25 bg-status-error/10 p-4 text-sm text-status-error"
        >
          <p>The Mind could not be read: {statusError}</p>
          <Button variant="ghost" size="sm" onClick={refresh}>
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (!status) {
    return (
      <div role="status" aria-live="polite" className="flex h-64 items-center justify-center gap-3 text-sm text-pc-text-muted">
        <span
          aria-hidden="true"
          className="h-8 w-8 animate-spin rounded-full border-2 border-pc-border"
          style={{ borderTopColor: 'var(--pc-accent)' }}
        />
        <span>Reading the Mind…</span>
      </div>
    );
  }

  const line = serviceLine(status);
  const agentOptions = (status.agents ?? []).map((a) => ({ value: a, label: a }));
  const currentAgent = status.agent ?? agent ?? '';

  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Memory"
        description="The Mind: what the agent remembers, how sure it is, and what is waiting on you."
        actions={
          <div className="flex items-center gap-2">
            <Badge tone={line.tone}>{line.text}</Badge>
            <Button variant="ghost" size="sm" onClick={refresh} aria-label="Refresh">
              <RefreshCw size={14} aria-hidden="true" />
            </Button>
          </div>
        }
      />

      {!status.enabled ? (
        <>
          <NotEnabled status={status} />
          <InstallCard onNote={setDevicesNote} onChanged={refresh} />
          <Devices status={status} note={devicesNote} onNote={setDevicesNote} onChanged={refresh} />
        </>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <span className="cz-eyebrow">Agent</span>
            {agentOptions.length > 0 ? (
              <Select
                value={currentAgent}
                onChange={(v) => setAgent(v)}
                options={agentOptions}
                className="min-w-40"
              />
            ) : (
              <span className="text-sm text-pc-text-secondary">{currentAgent}</span>
            )}
            {!status.has_token && (
              <span className="text-xs text-status-warning">
                No token at <code className="font-mono">{status.token_file}</code>. Mint one:{' '}
                <code className="font-mono">xanima-server token mint --agent {currentAgent} --scopes read,write</code>
              </span>
            )}
          </div>

          {status.errors && status.errors.length > 0 && (
            <div role="alert" className="rounded-[var(--radius-md)] border border-status-warning/25 bg-status-warning/10 p-3 text-xs text-status-warning">
              {status.errors.map((e) => (
                <div key={e}>{e}</div>
              ))}
            </div>
          )}

          <BrainOverview status={status} />

          {status.healthy && status.has_token && (
            <>
              <Recall agent={currentAgent} />
              <ReviewQueue agent={currentAgent} key={`${currentAgent}:${reload}`} />
            </>
          )}

          <Devices status={status} note={devicesNote} onNote={setDevicesNote} onChanged={refresh} />
        </>
      )}
    </div>
  );
}

// --- the Mind turned on from here -----------------------------------------------------

/** No Mind yet on a PC or hub: install it with one tap (the gateway's job), then point the Runtime at it. */
function InstallCard({ onNote, onChanged }: { onNote: (note: string | null) => void; onChanged: () => void }) {
  const [info, setInfo] = useState<MindInstall | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [wiring, setWiring] = useState(false);

  const load = useCallback(
    () =>
      getMindInstall()
        .then(setInfo)
        .catch((reason: unknown) => setError(errorText(reason))),
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!info?.running) return;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [info?.running, load]);

  const useIt = useCallback(async () => {
    setWiring(true);
    setError(null);
    try {
      await patchConfig(installBackendOps());
      onNote(`Memory is on: the Mind runs on this device. ${restartNote('joined')}`);
      onChanged();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setWiring(false);
      setBusy(false);
    }
  }, [onChanged, onNote]);

  // The job this page started finished well: point the Runtime at the Mind.
  useEffect(() => {
    if (busy && info?.finished && info.ok && !wiring) void useIt();
  }, [busy, info?.finished, info?.ok, wiring, useIt]);

  const start = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setInfo(await startMindInstall());
    } catch (reason) {
      setError(errorText(reason));
      setBusy(false);
    }
  }, []);

  if (!info) return null;
  if (!info.can_install) {
    return <p className="text-xs text-pc-text-muted" data-mind-install="no">{info.reason}</p>;
  }
  const pct = percent(info.done, info.total);
  const ready = info.installed && info.healthy === true && !info.running;

  return (
    <Card data-mind-install={info.running ? 'running' : ready ? 'ready' : 'offer'}>
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="cz-eyebrow">Long-term memory</div>
        {info.running && <Badge tone="neutral">{stageLabel(info.stage)}</Badge>}
        {ready && <Badge tone="ok">installed · running</Badge>}
      </div>
      <div className="flex items-start gap-3">
        <Download className="mt-0.5 h-5 w-5 shrink-0 text-pc-accent" aria-hidden="true" />
        <div className="space-y-2 text-sm">
          {ready ? (
            <p className="text-pc-text">
              The Mind is installed and running on this device. Use it as Cael's memory here.
            </p>
          ) : (
            <p className="text-pc-text">
              Cael keeps a long-term memory, the Mind, that lasts across sessions and sleeps to tidy itself. Turn it on and
              it is set up on this device: the Mind and a small Node runtime it runs on, about 60 MB once. No account, and
              nothing leaves this device.
            </p>
          )}
        </div>
      </div>

      {!info.running && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {ready ? (
            <Button size="sm" disabled={wiring} onClick={() => void useIt()} data-mind-install="use">
              {wiring ? 'Turning on…' : 'Use it'}
            </Button>
          ) : (
            <Button size="sm" disabled={busy} onClick={() => void start()} data-mind-install="start">
              <Download size={14} aria-hidden="true" />
              <span className="ml-1.5">{info.finished && info.error ? 'Try again' : 'Turn on memory'}</span>
            </Button>
          )}
        </div>
      )}

      {info.running && (
        <div className="mt-3 space-y-2" data-mind-install="progress">
          <p className="text-sm text-pc-text">{info.detail}</p>
          {info.total > 0 && (
            <div className="cz-progress" role="progressbar" aria-valuenow={pct ?? 0} aria-valuemin={0} aria-valuemax={100}>
              <span style={{ width: `${pct ?? 0}%` }} />
            </div>
          )}
          {info.total > 0 && (
            <p className="text-xs text-pc-text-faint">
              {megabytes(info.done)} of {megabytes(info.total)}
            </p>
          )}
          {info.log.length > 0 && <p className="truncate font-mono text-xs text-pc-text-faint">{info.log[info.log.length - 1]}</p>}
        </div>
      )}

      {error && <Notice tone="error">{error}</Notice>}
      {!info.running && info.finished && info.error && (
        <Notice tone="error">
          <div>{info.error}</div>
          {info.log.length > 0 && (
            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] opacity-80">
              {info.log.slice(-8).join('\n')}
            </pre>
          )}
        </Notice>
      )}
    </Card>
  );
}

// --- one Mind for every device -------------------------------------------------------

/** The devices card for this device's role: share the Mind it hosts, show the one it joined, or join one. */
function Devices({
  status,
  note,
  onNote,
  onChanged,
}: {
  status: MindStatus;
  note: string | null;
  onNote: (note: string | null) => void;
  onChanged: () => void;
}) {
  const role = devicesRole(status);
  const card =
    role === 'host' ? (
      <ShareCard onAction={() => onNote(null)} />
    ) : role === 'joined' ? (
      <JoinedCard url={status.url ?? ''} onNote={onNote} onChanged={onChanged} />
    ) : (
      <JoinCard onNote={onNote} onChanged={onChanged} />
    );
  return (
    <div className="space-y-3" data-mind-devices={role}>
      {note && (
        <Notice tone="ok">
          <span data-mind-share="note">{note}</span>
        </Notice>
      )}
      {card}
    </div>
  );
}

function Notice({ tone, children }: { tone: 'ok' | 'warn' | 'error'; children: React.ReactNode }) {
  const cls =
    tone === 'error'
      ? 'border-status-error/25 bg-status-error/10 text-status-error'
      : tone === 'warn'
        ? 'border-status-warning/25 bg-status-warning/10 text-status-warning'
        : 'border-status-success/25 bg-status-success/10 text-status-success';
  return (
    <div role={tone === 'ok' ? 'status' : 'alert'} className={`mt-3 rounded-[var(--radius-md)] border p-3 text-xs ${cls}`}>
      {children}
    </div>
  );
}

/** A join code with a copy button; the owner pastes it on the other device. */
function CodeBox({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }, [code]);
  return (
    <div className="mt-3">
      <textarea
        readOnly
        value={code}
        rows={3}
        aria-label="Join code"
        data-mind-share="code"
        className="input-electric w-full break-all font-mono text-xs"
        onFocus={(e) => e.currentTarget.select()}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => void copy()} data-mind-share="copy">
          {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
          <span className="ml-1.5">{copied ? 'Copied' : 'Copy the code'}</span>
        </Button>
        <span className="text-xs text-pc-text-faint">
          On the other device, open Memory and paste it under <em>Join a Mind on another device</em>. Every code is new; devices
          already joined keep theirs.
        </span>
      </div>
    </div>
  );
}

/** This device hosts the Mind: share it with the owner's other devices. */
function ShareCard({ onAction }: { onAction: () => void }) {
  const [share, setShare] = useState<MindShareState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<MindShareResult | null>(null);
  const [stopped, setStopped] = useState<{ revoked: number; restart: boolean } | null>(null);

  const load = useCallback(() => {
    setError(null);
    getMindShare()
      .then(setShare)
      .catch((reason: unknown) => setError(errorText(reason)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const start = useCallback(
    async (host: string) => {
      setBusy(true);
      setError(null);
      setStopped(null);
      onAction();
      try {
        const r = await startMindShare(host);
        setResult(r);
        setShare(r);
      } catch (reason) {
        setError(errorText(reason));
      } finally {
        setBusy(false);
      }
    },
    [onAction],
  );

  const stop = useCallback(async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    onAction();
    try {
      const r = await stopMindShare();
      setShare(r);
      setStopped({ revoked: r.revoked, restart: r.restart_needed });
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }, [onAction]);

  const candidates = share?.candidates ?? [];
  const preferred = preferredCandidate(candidates);
  const configured = share?.configured ?? [];
  const port = share?.port ?? 18790;

  return (
    <Card data-mind-share="host">
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="cz-eyebrow">Your other devices</div>
        {share?.sharing && <Badge tone={share.reachable ? 'ok' : 'warn'}>{share.reachable ? 'shared' : 'shared · restart the Mind'}</Badge>}
      </div>
      <div className="flex items-start gap-3">
        <Smartphone className="mt-0.5 h-5 w-5 shrink-0 text-pc-accent" aria-hidden="true" />
        <div className="space-y-2 text-sm">
          <p className="text-pc-text">
            Cael can remember on your phone too, the same memory as here. Share this Mind, then paste the code into the other
            device's Memory page. Only devices with a code can use it. On home Wi-Fi the link is not encrypted, so share only
            on a network you trust; Tailscale encrypts it.
          </p>
          {share?.config_error && <p className="text-status-warning">{share.config_error}</p>}
        </div>
      </div>

      {error && <Notice tone="error">{error}</Notice>}

      {share && !share.sharing && (share.share_tokens ?? 0) > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-pc-text-secondary">
          <span>
            {share.share_tokens} device code{share.share_tokens === 1 ? '' : 's'} still live from before.
          </span>
          <Button size="sm" variant="danger" disabled={busy} onClick={() => void stop()} data-mind-share="revoke">
            Revoke all codes
          </Button>
        </div>
      )}

      {share && !share.sharing && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {candidates.length === 0 ? (
            <span className="text-xs text-pc-text-muted">
              No network address found on this machine. Connect it to Wi-Fi or Ethernet (or start Tailscale), then refresh.
            </span>
          ) : (
            candidates.map((c) => (
              <Button
                key={c.host}
                size="sm"
                variant={c.host === preferred?.host ? 'primary' : 'ghost'}
                disabled={busy}
                onClick={() => void start(c.host)}
                data-mind-share={`share:${c.kind}`}
              >
                <Link2 size={14} aria-hidden="true" />
                <span className="ml-1.5">Share on {candidateLabel(c)}</span>
              </Button>
            ))
          )}
          <Button variant="ghost" size="sm" onClick={load} aria-label="Refresh addresses">
            <RefreshCw size={14} aria-hidden="true" />
          </Button>
        </div>
      )}

      {share?.sharing && (
        <div className="mt-3 space-y-2 text-sm">
          <p className="text-pc-text-secondary">
            Shared on{' '}
            {configured.map((h) => (
              <code key={h} className="font-mono text-pc-text">
                {h}:{port}{' '}
              </code>
            ))}
            {share.share_tokens !== undefined && (
              <span className="text-pc-text-faint">
                · {share.share_tokens} device code{share.share_tokens === 1 ? '' : 's'} live
              </span>
            )}
          </p>
          {!share.reachable && (
            <Notice tone="warn">
              {restartNote('host')}
              {share.unbound && share.unbound.length > 0 ? ` Not listening yet on ${share.unbound.join(', ')}.` : ''}
            </Notice>
          )}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" disabled={busy} onClick={() => void start(configured[0] ?? preferred?.host ?? '')} data-mind-share="new-code">
              New code
            </Button>
            <Button size="sm" variant="danger" disabled={busy} onClick={() => void stop()} data-mind-share="stop">
              Stop sharing{(share.share_tokens ?? 0) > 0 ? ` · revoke ${share.share_tokens} code${share.share_tokens === 1 ? '' : 's'}` : ''}
            </Button>
          </div>
        </div>
      )}

      {result && (
        <>
          <Notice tone="ok">
            Shared on {result.share_url}. {result.restart_needed || !isListening(result.listening, result.host, port) ? '' : 'The Mind already listens there.'}
          </Notice>
          <CodeBox code={result.code} />
        </>
      )}

      {stopped && (
        <Notice tone="ok">
          {stopped.revoked} device code{stopped.revoked === 1 ? '' : 's'} revoked; joined devices lose the Mind on their next turn.
          {stopped.restart ? ' The address stays open until the Mind restarts; nothing can use it without a code.' : ''}
        </Notice>
      )}
    </Card>
  );
}

/** This device has no Mind: join one on another device with its code. */
function JoinCard({ onNote, onChanged }: { onNote: (note: string | null) => void; onChanged: () => void }) {
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const join = useCallback(async () => {
    const clean = cleanCode(code);
    if (!clean) return;
    setBusy(true);
    setError(null);
    try {
      const probe = await probeMindCode(clean);
      await createMapKey(STORAGE_PATH, STORAGE_KEY);
      await patchConfig(joinOps(probe.url, probe.token, probe.agent));
      setCode('');
      onNote(`Joined the Mind at ${probe.url}${probe.version ? ` (xanima ${probe.version})` : ''}. ${restartNote('joined')}`);
      onChanged();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }, [code, onChanged, onNote]);

  return (
    <Card data-mind-share="join">
      <div className="mb-1 cz-eyebrow">Join a Mind on another device</div>
      <div className="flex items-start gap-3">
        <Smartphone className="mt-0.5 h-5 w-5 shrink-0 text-pc-accent" aria-hidden="true" />
        <p className="text-sm text-pc-text">
          Is Caelza on your PC already? Open its Memory page, tap <em>Share</em> under <em>Your other devices</em>, and paste the code
          here. Cael then remembers the same things on both. The two devices need to be on the same network (or both on Tailscale).
        </p>
      </div>
      <form
        className="mt-3 flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          void join();
        }}
      >
        <input
          className="input-electric flex-1 font-mono text-xs"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="caelza-mind:…"
          aria-label="Join code"
          autoComplete="off"
          spellCheck={false}
          data-mind-share="code-input"
        />
        <Button type="submit" disabled={busy || !cleanCode(code)} data-mind-share="join-button">
          <Link2 size={14} aria-hidden="true" />
          <span className="ml-1.5">{busy ? 'Checking…' : 'Join'}</span>
        </Button>
      </form>
      {error && <Notice tone="error">{error}</Notice>}
    </Card>
  );
}

/** This device uses another device's Mind. */
function JoinedCard({
  url,
  onNote,
  onChanged,
}: {
  url: string;
  onNote: (note: string | null) => void;
  onChanged: () => void;
}) {
  const [share, setShare] = useState<MindShareState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMindShare()
      .then(setShare)
      .catch(() => setShare(null));
  }, [url]);

  const leave = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const localMind = share?.local_mind === true;
      // The backend first: if the row's delete then fails, the device is already
      // off the shared Mind (the row just holds a token nothing uses).
      await patchConfig(leaveBackendOps(localMind));
      await deleteMapKey(STORAGE_PATH, STORAGE_KEY);
      onNote(
        `${localMind ? "Back to this device's own Mind." : "Back to this device's own memory (the Runtime's store)."} ${restartNote('joined')}`,
      );
      onChanged();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }, [onChanged, onNote, share]);

  return (
    <Card data-mind-share="joined">
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="cz-eyebrow">Your other devices</div>
        <Badge tone={share?.healthy === false ? 'warn' : 'ok'}>{share?.healthy === false ? 'not answering' : 'joined'}</Badge>
      </div>
      <div className="flex items-start gap-3">
        <Smartphone className="mt-0.5 h-5 w-5 shrink-0 text-pc-accent" aria-hidden="true" />
        <div className="space-y-2 text-sm">
          <p className="text-pc-text">
            This device uses the Mind at <code className="font-mono">{url}</code>
            {share?.version ? ` (xanima ${share.version})` : ''}. What Cael learns here, he knows there too.
          </p>
          {share?.healthy === false && (
            <p className="text-status-warning">
              It is not answering right now: is the other device on and on the same network? Cael keeps going without memory until
              it is back.
            </p>
          )}
        </div>
      </div>
      <div className="mt-3">
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void leave()} data-mind-share="leave">
          Use this device's own memory
        </Button>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
    </Card>
  );
}

function NotEnabled({ status }: { status: MindStatus }) {
  return (
    <Card>
      <div className="flex items-start gap-3">
        <Brain className="mt-0.5 h-5 w-5 shrink-0 text-pc-accent" aria-hidden="true" />
        <div className="space-y-2 text-sm">
          <p className="text-pc-text">
            The Runtime's memory is <code className="font-mono">{status.backend}</code>, not the Mind. The agent still remembers,
            but there is no brain service to show here.
          </p>
          <p className="text-pc-text-muted">
            Local notes stored by the Runtime itself are on the dashboard under <em>Memories</em>. Turn the Mind on below, or
            join one on another device.
          </p>
        </div>
      </div>
    </Card>
  );
}

function BrainOverview({ status }: { status: MindStatus }) {
  const brains = status.stats?.brains ?? [];
  const totals = brainTotals(brains);
  const privateStatus = status.status?.brains?.find((b) => b.brain === 'private') ?? status.status?.brains?.[0];
  const highlights = statusHighlights(privateStatus);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Beliefs" value={totals.nodes} sublabel={`${totals.edges} links`} icon={<Brain size={18} />} />
        <StatCard label="Episodes" value={totals.episodes} sublabel="turns the brain has seen" />
        <StatCard
          label="Embedded"
          value={totals.nodes ? `${Math.round((totals.embedded / totals.nodes) * 100)}%` : '0%'}
          sublabel={`${totals.embedded} of ${totals.nodes}`}
          tone={totals.nodes && totals.embedded < totals.nodes ? 'warn' : 'ok'}
        />
        <StatCard label="Brains" value={totals.brains} sublabel={brains.map((b) => b.brain).join(' + ') || 'none yet'} />
      </div>

      {brains.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2">
          {brains.map((b) => (
            <Card key={b.brain}>
              <div className="flex items-center justify-between">
                <Badge tone={brainTone(b.brain)}>{b.brain}</Badge>
                <span className="text-xs text-pc-text-faint">
                  {b.lastConsolidation ? `slept ${b.lastConsolidation}` : 'has not slept yet'}
                </span>
              </div>
              <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
                <div>
                  <dt className="text-xs text-pc-text-faint">nodes</dt>
                  <dd className="text-pc-text">{b.nodes}</dd>
                </div>
                <div>
                  <dt className="text-xs text-pc-text-faint">links</dt>
                  <dd className="text-pc-text">{b.activeEdges}</dd>
                </div>
                <div>
                  <dt className="text-xs text-pc-text-faint">episodes</dt>
                  <dd className="text-pc-text">{b.episodes}</dd>
                </div>
              </dl>
              {Object.keys(b.nodesByType ?? {}).length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {Object.entries(b.nodesByType)
                    .sort((x, y) => y[1] - x[1])
                    .map(([type, n]) => (
                      <Badge key={type} tone="neutral">
                        {type} {n}
                      </Badge>
                    ))}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {highlights.length > 0 && (
        <Card>
          <div className="mb-2 cz-eyebrow">Status</div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            {highlights.map((h) => (
              <div key={h.label}>
                <div className="text-xs text-pc-text-faint">{h.label}</div>
                <div
                  className={
                    h.tone === 'warn'
                      ? 'text-status-warning'
                      : h.tone === 'error'
                        ? 'text-status-error'
                        : h.tone === 'ok'
                          ? 'text-status-success'
                          : 'text-pc-text'
                  }
                >
                  {h.value}
                </div>
              </div>
            ))}
          </div>
          {privateStatus?.attention && privateStatus.attention.length > 0 && (
            <ul className="mt-3 space-y-1 text-sm text-pc-text-secondary">
              {privateStatus.attention.map((line) => (
                <li key={line}>• {line}</li>
              ))}
            </ul>
          )}
          {privateStatus?.focus && (
            <p className="mt-3 text-sm text-pc-text-secondary">
              Focus: <span className="text-pc-text">{privateStatus.focus}</span>
            </p>
          )}
        </Card>
      )}
    </div>
  );
}

function Recall({ agent }: { agent: string }) {
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<MindRecallHit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [forgetting, setForgetting] = useState<MindRecallHit | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const run = useCallback(
    async (q: string) => {
      const trimmed = q.trim();
      if (!trimmed) return;
      setBusy(true);
      setError(null);
      try {
        const res = await mindRecall(trimmed, 12, agent);
        setHits(res.results);
      } catch (reason) {
        setError(errorText(reason));
      } finally {
        setBusy(false);
      }
    },
    [agent],
  );

  const forget = useCallback(async () => {
    if (!forgetting) return;
    const target = forgetting;
    setForgetting(null);
    try {
      await mindForget(target.id, agent, target.brain === 'shared' ? 'shared' : 'private');
      setHits((prev) => (prev ? prev.filter((h) => h.id !== target.id) : prev));
    } catch (reason) {
      setError(errorText(reason));
    }
  }, [agent, forgetting]);

  return (
    <Card>
      <div className="mb-3 cz-eyebrow">Recall</div>
      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          void run(query);
        }}
      >
        <input
          className="input-electric flex-1"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="What does the agent remember about…"
          aria-label="Recall query"
        />
        <Button type="submit" disabled={busy || !query.trim()}>
          <Search size={14} aria-hidden="true" />
          <span className="ml-1.5">{busy ? 'Recalling…' : 'Recall'}</span>
        </Button>
      </form>
      <p className="mt-2 text-xs text-pc-text-faint">
        The same search the agent runs on every turn: private and shared brains, fused by the service.
      </p>

      {error && (
        <div role="alert" className="mt-3 rounded-[var(--radius-md)] border border-status-error/25 bg-status-error/10 p-3 text-xs text-status-error">
          {error}
        </div>
      )}

      {hits && hits.length === 0 && <p className="mt-4 text-sm text-pc-text-muted">Nothing recalled for that.</p>}

      {hits && hits.length > 0 && (
        <ul className="mt-4 space-y-2">
          {hits.map((hit) => {
            const p = preview(hit.content);
            const open = expanded[hit.id] === true;
            return (
              <li key={hit.id} className="rounded-[var(--radius-md)] border border-pc-border bg-pc-elevated p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge tone={brainTone(hit.brain)}>{hit.room ? `room ${hit.room}` : hit.brain}</Badge>
                  <span className="font-mono text-pc-text-faint">{hit.type}</span>
                  {hit.confidence && <span className="text-pc-text-faint">conf {hit.confidence}</span>}
                  {hit.contradicted_at && <Badge tone="warn">disputed</Badge>}
                  {scoreLabel(hit) && <span className="ml-auto text-pc-text-faint">{scoreLabel(hit)}</span>}
                </div>
                <div className="mt-1.5 text-sm font-medium text-pc-text">{hit.label}</div>
                <p className="mt-1 whitespace-pre-wrap text-sm text-pc-text-secondary">{open ? hit.content : p.text}</p>
                <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-pc-text-faint">
                  {hit.ago && <span>{hit.ago}</span>}
                  {hit.writer && <span>by {hit.writer}</span>}
                  {p.truncated && (
                    <button
                      type="button"
                      className="text-pc-accent hover:underline"
                      onClick={() => setExpanded((prev) => ({ ...prev, [hit.id]: !open }))}
                    >
                      {open ? 'Less' : 'More'}
                    </button>
                  )}
                  <button
                    type="button"
                    className="ml-auto inline-flex items-center gap-1 text-status-error hover:underline"
                    onClick={() => setForgetting(hit)}
                  >
                    <Trash2 size={12} aria-hidden="true" /> Forget
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <ConfirmDialog
        open={forgetting !== null}
        title="Forget this memory?"
        message={
          forgetting ? (
            <span>
              <strong>{forgetting.label}</strong> leaves the {forgetting.brain} brain. The service keeps a trace for history, but the
              agent will not recall it again.
            </span>
          ) : undefined
        }
        confirmLabel="Forget"
        danger
        onConfirm={() => void forget()}
        onClose={() => setForgetting(null)}
      />
    </Card>
  );
}

function ReviewQueue({ agent }: { agent: string }) {
  const [items, setItems] = useState<MindReviewItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    getMindReview(agent, 'pending')
      .then((r) => setItems(r.items))
      .catch((reason: unknown) => setError(errorText(reason)));
  }, [agent]);

  useEffect(() => {
    load();
  }, [load]);

  const decide = useCallback(
    async (item: MindReviewItem, action: 'accept' | 'reject') => {
      setNotice(null);
      setError(null);
      try {
        const r = await decideMindReview(item.id, action, undefined, agent);
        setNotice(r.text);
        load();
      } catch (reason) {
        setError(errorText(reason));
      }
    },
    [agent, load],
  );

  return (
    <Card>
      <div className="mb-1 flex items-center justify-between">
        <div className="cz-eyebrow">Review queue</div>
        {items && <Badge tone={items.length > 0 ? 'warn' : 'ok'}>{items.length} pending</Badge>}
      </div>
      <p className="text-xs text-pc-text-faint">
        Identity, value and goal changes the brain held back for you: from untrusted sources, soul imports or merges.
        Accepting or rejecting needs an admin-scoped token on the service.
      </p>

      {error && (
        <div role="alert" className="mt-3 rounded-[var(--radius-md)] border border-status-error/25 bg-status-error/10 p-3 text-xs text-status-error">
          {error}
        </div>
      )}
      {notice && <div className="mt-3 text-xs text-status-success">{notice}</div>}

      {items && items.length === 0 && <p className="mt-3 text-sm text-pc-text-muted">Nothing waiting.</p>}

      {items && items.length > 0 && (
        <ul className="mt-3 space-y-2">
          {items.map((item) => (
            <li key={item.id} className="rounded-[var(--radius-md)] border border-pc-border bg-pc-elevated p-3">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <Badge tone="warn">{item.kind}</Badge>
                <span className="font-mono text-pc-text-faint">{item.section}</span>
                {item.flags.map((f) => (
                  <Badge key={f} tone="error">
                    {f}
                  </Badge>
                ))}
                <span className="ml-auto font-mono text-pc-text-faint">{item.id}</span>
              </div>
              <div className="mt-1.5 text-sm font-medium text-pc-text">{item.label}</div>
              {item.reason && <p className="mt-1 text-sm text-pc-text-secondary">{item.reason}</p>}
              <div className="mt-2 flex gap-2">
                <Button size="sm" onClick={() => void decide(item, 'accept')}>
                  Accept
                </Button>
                <Button size="sm" variant="danger" onClick={() => void decide(item, 'reject')}>
                  Reject
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
