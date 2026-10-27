// Procedures: the SOP engine as the owner sees it. What waits on them, what is
// running, the library of procedures, what finished lately. The deeper views
// (the editor, the canvas, the full runs table) stay where upstream put them;
// this page is the front door. The phone playbooks (body/sops) get a Run that
// asks which phone and sends it as the trigger payload.
import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ClipboardList, ExternalLink, Loader2, Pencil, Play, Plus, RefreshCw, Smartphone, Square } from 'lucide-react';

import ApprovalQueue from '@/components/ApprovalQueue';
import { Badge, Button, Card, ConfirmDialog, PageHeader, Select } from '@/components/ui';
import { getBodyDevices, type BodyDevice } from '@/lib/bodies';
import { formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import { cancelSop, listRuns, listSops, runSop, runStatusBadge, type SopRunSummary, type SopSummary } from '@/lib/sops';
import { usePolling } from '@/hooks/usePolling';
import { expandTarget, isPlaybook, partitionRuns, playbookPayload, runRefusal, runTargets, sopEngineOff, sopOffText } from './home.logic';

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

export default function Procedures() {
  const [sops, setSops] = useState<SopSummary[] | null>(null);
  const [runs, setRuns] = useState<SopRunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [starting, setStarting] = useState<SopSummary | null>(null);
  const refresh = useCallback(() => setReload((n) => n + 1), []);

  usePolling(
    async (isStale) => {
      const [s, r] = await Promise.allSettled([listSops(), listRuns()]);
      if (isStale()) return;
      if (s.status === 'fulfilled') setSops(s.value);
      if (r.status === 'fulfilled') setRuns(r.value);
      const failed = [s, r].find((x): x is PromiseRejectedResult => x.status === 'rejected');
      setError(failed ? errorText(failed.reason) : null);
    },
    5000,
    [reload],
  );

  const buckets = partitionRuns(runs ?? [], Date.now(), 7 * 24 * 3600 * 1000);
  const summary = [
    sops ? `${sops.length} procedure${sops.length === 1 ? '' : 's'}` : null,
    runs ? `${buckets.running.length} running` : null,
    runs && buckets.waiting.length > 0 ? `${buckets.waiting.length} waiting` : null,
  ].filter((p): p is string => p !== null);

  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Procedures"
        description="What the agent follows step by step, what is running, and what waits on you."
        actions={
          <div className="flex items-center gap-2">
            {summary.length > 0 && <Badge tone={buckets.waiting.length > 0 ? 'warn' : 'neutral'}>{summary.join(' · ')}</Badge>}
            <Button variant="ghost" size="sm" onClick={refresh} aria-label="Refresh">
              <RefreshCw size={14} aria-hidden="true" />
            </Button>
            <Link to="/sops/new" className="inline-flex items-center gap-1.5 rounded-[var(--radius-md)] bg-pc-accent px-3 py-1.5 text-sm font-medium text-pc-bg hover:opacity-90">
              <Plus size={14} aria-hidden="true" /> New procedure
            </Link>
          </div>
        }
      />

      {error && sopEngineOff(error) ? (
        <Card>
          <div className="flex items-start gap-3 text-sm">
            <ClipboardList className="mt-0.5 h-5 w-5 shrink-0 text-pc-accent" aria-hidden="true" />
            <p className="text-pc-text-muted">
              {sopOffText((sops?.length ?? 0) > 0)}
              {(sops?.length ?? 0) === 0 && (
                <>
                  {' '}
                  Add a <code className="font-mono">[sop]</code> block with <code className="font-mono">sops_dir = "shared/sops"</code> to the config to turn it on.
                </>
              )}
            </p>
          </div>
        </Card>
      ) : error ? (
        <div role="alert" className="rounded-[var(--radius-md)] border border-status-error/25 bg-status-error/10 p-3 text-xs text-status-error">
          {error}
        </div>
      ) : null}

      <Card>
        <div className="mb-1 flex items-center justify-between">
          <div className="cz-eyebrow">Waiting on you</div>
          <Badge tone={buckets.waiting.length > 0 ? 'warn' : 'ok'}>{buckets.waiting.length}</Badge>
        </div>
        <p className="mb-3 text-xs text-pc-text-faint">Runs held at an approval gate or a paused checkpoint. Approve resumes the run where it stopped; Deny ends it.</p>
        <ApprovalQueue runs={buckets.waiting} onDecided={refresh} />
      </Card>

      <RunningNow runs={buckets.running} onChanged={refresh} loaded={runs !== null} />

      <Library sops={sops} onRun={setStarting} />

      <Card>
        <div className="mb-1 flex items-center justify-between">
          <div className="cz-eyebrow">Finished this week</div>
          <Link to="/runs" className="inline-flex items-center gap-1 text-xs text-pc-accent hover:underline">
            {t('runs.title')} <ExternalLink size={12} aria-hidden="true" />
          </Link>
        </div>
        {runs === null ? (
          <p className="text-sm text-pc-text-muted">Reading…</p>
        ) : buckets.finished.length === 0 ? (
          <p className="text-sm text-pc-text-muted">Nothing finished in the last seven days.</p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {buckets.finished.slice(0, 10).map((r) => (
              <li key={r.run_id} className="flex flex-wrap items-center gap-2 text-sm">
                <Link to={`/runs/${encodeURIComponent(r.sop_name)}/${encodeURIComponent(r.run_id)}`} className="text-pc-text hover:underline">
                  {r.sop_name}
                </Link>
                <Badge tone={runStatusBadge(r.status)}>{t(`sops.run_status.${r.status}`)}</Badge>
                <span className="text-xs text-pc-text-faint">
                  {r.current_step}/{r.total_steps} steps · {r.trigger_source} · {formatRelative(r.completed_at ?? r.started_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <RunDialog sop={starting} onClose={() => setStarting(null)} onStarted={refresh} />
    </div>
  );
}

function RunningNow({ runs, onChanged, loaded }: { runs: SopRunSummary[]; onChanged: () => void; loaded: boolean }) {
  const [stopping, setStopping] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const stop = async (run: SopRunSummary) => {
    setStopping(run.run_id);
    setError(null);
    try {
      await cancelSop(run.sop_name, run.run_id);
      onChanged();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setStopping(null);
    }
  };

  return (
    <Card>
      <div className="mb-1 flex items-center justify-between">
        <div className="cz-eyebrow">Running now</div>
        <Badge tone="neutral">{runs.length}</Badge>
      </div>
      {error && <p className="mb-2 text-xs text-status-error">{error}</p>}
      {!loaded ? (
        <p className="text-sm text-pc-text-muted">Reading…</p>
      ) : runs.length === 0 ? (
        <p className="text-sm text-pc-text-muted">Nothing is running.</p>
      ) : (
        <ul className="space-y-2">
          {runs.map((r) => {
            const pct = r.total_steps > 0 ? Math.min(100, Math.round((r.current_step / r.total_steps) * 100)) : 0;
            const stoppingThis = stopping === r.run_id || r.status === 'cancel_requested';
            return (
              <li key={r.run_id} className="rounded-[var(--radius-md)] border border-pc-border bg-pc-elevated p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="text-sm font-medium text-pc-text">{r.sop_name}</span>
                  <Badge tone={runStatusBadge(r.status)}>{t(`sops.run_status.${r.status}`)}</Badge>
                  <span className="text-pc-text-faint">
                    step {r.current_step} of {r.total_steps} · {r.trigger_source}
                  </span>
                  <span className="ml-auto text-pc-text-faint">{formatRelative(r.started_at)}</span>
                </div>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-pc-border" aria-hidden="true">
                  <div className="h-full rounded-full bg-pc-accent transition-all" style={{ width: `${pct}%` }} />
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Button size="sm" variant="danger" onClick={() => void stop(r)} disabled={stoppingThis}>
                    {stoppingThis ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Square size={14} aria-hidden="true" fill="currentColor" />}
                    <span className="ml-1.5">{stoppingThis ? t('sops.stopping') : t('sops.stop')}</span>
                  </Button>
                  <Link
                    to={`/runs/${encodeURIComponent(r.sop_name)}/${encodeURIComponent(r.run_id)}`}
                    className="ml-auto inline-flex items-center gap-1 text-xs text-pc-accent hover:underline"
                  >
                    {t('runs.open')} <ExternalLink size={12} aria-hidden="true" />
                  </Link>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function Library({ sops, onRun }: { sops: SopSummary[] | null; onRun: (sop: SopSummary) => void }) {
  const playbooks = (sops ?? []).filter((s) => isPlaybook(s.name)).length;
  return (
    <Card>
      <div className="mb-1 flex items-center justify-between">
        <div className="cz-eyebrow">Library</div>
        {sops && <Badge tone="neutral">{sops.length}</Badge>}
      </div>
      <p className="mb-3 text-xs text-pc-text-faint">
        Standard operating procedures the agent follows: event-triggered, step by step, with approval gates where you want a say.
        {playbooks > 0 && (
          <>
            {' '}
            <Smartphone className="inline h-3 w-3 align-[-1px] text-pc-accent" aria-hidden="true" /> marks a phone playbook: Run asks which phone, the
            step that changes it waits for your approval.
          </>
        )}
      </p>
      {sops === null ? (
        <p className="text-sm text-pc-text-muted">Reading…</p>
      ) : sops.length === 0 ? (
        <div className="flex items-start gap-3 text-sm">
          <ClipboardList className="mt-0.5 h-5 w-5 shrink-0 text-pc-accent" aria-hidden="true" />
          <p className="text-pc-text-muted">
            No procedures loaded. Write one with <Link to="/sops/new" className="text-pc-accent hover:underline">New procedure</Link>, or install the
            phone playbooks (debloat, malware removal, new-phone setup, diagnostics) with{' '}
            <code className="font-mono">caelza-body playbooks --install</code> and refresh.
          </p>
        </div>
      ) : (
        <ul className="grid gap-2 md:grid-cols-2">
          {sops.map((s) => (
            <li key={s.name} className="rounded-[var(--radius-md)] border border-pc-border bg-pc-elevated p-3">
              <div className="flex flex-wrap items-center gap-2">
                {isPlaybook(s.name) && <Smartphone className="h-3.5 w-3.5 shrink-0 text-pc-accent" aria-label="phone playbook" />}
                <Link to={`/sops/${encodeURIComponent(s.name)}`} className="text-sm font-medium text-pc-text hover:underline">
                  {s.name}
                </Link>
                {s.version && <span className="font-mono text-xs text-pc-text-faint">v{s.version}</span>}
                <span className="ml-auto flex items-center gap-2">
                  <Button size="sm" variant="primary" onClick={() => onRun(s)} aria-label={`Run ${s.name}`}>
                    <Play size={12} aria-hidden="true" fill="currentColor" />
                    <span className="ml-1">Run</span>
                  </Button>
                  <Link to={`/sops/${encodeURIComponent(s.name)}/edit`} className="inline-flex items-center gap-1 text-xs text-pc-accent hover:underline">
                    <Pencil size={12} aria-hidden="true" /> Edit
                  </Link>
                </span>
              </div>
              {s.description && <p className="mt-1 text-xs text-pc-text-secondary">{s.description}</p>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** Start a procedure by hand. A phone playbook asks which phone (the Body's devices) and, for the debloat, what to leave alone. */
function RunDialog({ sop, onClose, onStarted }: { sop: SopSummary | null; onClose: () => void; onStarted: () => void }) {
  const navigate = useNavigate();
  const [devices, setDevices] = useState<BodyDevice[] | null>(null);
  const [device, setDevice] = useState('self');
  const [keep, setKeep] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const playbook = sop !== null && isPlaybook(sop.name);

  useEffect(() => {
    if (!sop) return;
    setError(null);
    setBusy(false);
    setKeep('');
    setDevice('self');
    if (!isPlaybook(sop.name)) return;
    let stale = false;
    getBodyDevices()
      .then((r) => {
        if (!stale) setDevices(r.devices);
      })
      .catch(() => {
        if (!stale) setDevices([]);
      });
    return () => {
      stale = true;
    };
  }, [sop]);

  const start = async () => {
    if (!sop) return;
    setBusy(true);
    setError(null);
    try {
      if (!playbook) {
        const { run_id } = await runSop(sop.name);
        onStarted();
        onClose();
        navigate(`/runs/${encodeURIComponent(sop.name)}/${encodeURIComponent(run_id)}`);
        return;
      }
      // One run per phone: a group fans out, one procedure run each, in name order.
      const phones = expandTarget(devices ?? [], device);
      if (phones.length === 0) throw new Error('That group has no phones in it.');
      const started: string[] = [];
      let folded = 0;
      for (const phone of phones) {
        const { run_id } = await runSop(sop.name, playbookPayload(phone, sop.name === 'phone-debloat' ? keep : undefined));
        // A `coalesce` admission policy answers with a run already going instead of starting one.
        if (started.includes(run_id)) folded += 1;
        else started.push(run_id);
      }
      onStarted();
      if (folded > 0) {
        throw new Error(
          `Started ${started.length} run${started.length === 1 ? '' : 's'}; ${folded} phone${folded === 1 ? ' was' : 's were'} folded into a run that was already going (the procedure's admission policy). Wait for those runs to finish, then run the rest.`,
        );
      }
      onClose();
      const only = started.length === 1 ? started[0] : undefined;
      navigate(only ? `/runs/${encodeURIComponent(sop.name)}/${encodeURIComponent(only)}` : '/runs');
    } catch (reason) {
      setError(runRefusal(errorText(reason)));
    } finally {
      setBusy(false);
    }
  };

  const options = runTargets(devices ?? []);
  const fanOut = expandTarget(devices ?? [], device).length;

  return (
    <ConfirmDialog
      open={sop !== null}
      title={sop ? `Run ${sop.name}?` : ''}
      confirmLabel={busy ? 'Starting…' : 'Run'}
      onConfirm={() => void start()}
      onClose={onClose}
      message={
        sop ? (
          <div className="space-y-3 text-left">
            {sop.description && <p>{sop.description}</p>}
            {playbook ? (
              <>
                <label className="block text-xs text-pc-text-muted">
                  Which phone
                  <Select value={device} onChange={setDevice} options={options} className="mt-1 min-w-40" aria-label="Which phone" />
                </label>
                {fanOut > 1 && (
                  <p className="text-xs text-pc-text-faint">
                    {fanOut} runs will start, one per phone, each waiting for its own approval.
                  </p>
                )}
                {sop.name === 'phone-debloat' && (
                  <label className="block text-xs text-pc-text-muted">
                    Leave these alone (package names, comma-separated; optional)
                    <input
                      className="input-electric mt-1 w-full font-mono text-xs"
                      value={keep}
                      onChange={(e) => setKeep(e.target.value)}
                      placeholder="com.example.one, com.example.two"
                    />
                  </label>
                )}
                <p className="text-xs text-pc-text-faint">
                  The read steps run right away. The step that changes the phone waits for your approval here and on Home.
                </p>
              </>
            ) : (
              <p className="text-xs text-pc-text-faint">Starts a manual run with no payload. The procedure needs a manual trigger and an owning agent.</p>
            )}
            {error && (
              <p role="alert" className="text-xs text-status-error">
                {error}
              </p>
            )}
          </div>
        ) : undefined
      }
    />
  );
}
