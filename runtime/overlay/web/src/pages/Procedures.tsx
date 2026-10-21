// Procedures: the SOP engine as the owner sees it. What waits on them, what is
// running, the library of procedures, what finished lately. The deeper views
// (the editor, the canvas, the full runs table) stay where upstream put them;
// this page is the front door.
import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { ClipboardList, ExternalLink, Loader2, Pencil, Plus, RefreshCw, Square } from 'lucide-react';

import ApprovalQueue from '@/components/ApprovalQueue';
import { Badge, Button, Card, PageHeader } from '@/components/ui';
import { formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import { cancelSop, listRuns, listSops, runStatusBadge, type SopRunSummary, type SopSummary } from '@/lib/sops';
import { usePolling } from '@/hooks/usePolling';
import { partitionRuns, sopEngineOff, SOP_OFF_TEXT } from './home.logic';

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

export default function Procedures() {
  const [sops, setSops] = useState<SopSummary[] | null>(null);
  const [runs, setRuns] = useState<SopRunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
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
              {SOP_OFF_TEXT} Add a <code className="font-mono">[sop]</code> block to the config to turn it on.
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

      <Library sops={sops} />

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

function Library({ sops }: { sops: SopSummary[] | null }) {
  return (
    <Card>
      <div className="mb-1 flex items-center justify-between">
        <div className="cz-eyebrow">Library</div>
        {sops && <Badge tone="neutral">{sops.length}</Badge>}
      </div>
      <p className="mb-3 text-xs text-pc-text-faint">
        Standard operating procedures the agent follows: event-triggered, step by step, with approval gates where you want a say.
      </p>
      {sops === null ? (
        <p className="text-sm text-pc-text-muted">Reading…</p>
      ) : sops.length === 0 ? (
        <div className="flex items-start gap-3 text-sm">
          <ClipboardList className="mt-0.5 h-5 w-5 shrink-0 text-pc-accent" aria-hidden="true" />
          <p className="text-pc-text-muted">
            No procedures yet. Write one with <Link to="/sops/new" className="text-pc-accent hover:underline">New procedure</Link>; the phone playbooks
            (debloat, malware removal, new-phone setup, diagnostics) arrive as procedures in a later milestone.
          </p>
        </div>
      ) : (
        <ul className="grid gap-2 md:grid-cols-2">
          {sops.map((s) => (
            <li key={s.name} className="rounded-[var(--radius-md)] border border-pc-border bg-pc-elevated p-3">
              <div className="flex items-center gap-2">
                <Link to={`/sops/${encodeURIComponent(s.name)}`} className="text-sm font-medium text-pc-text hover:underline">
                  {s.name}
                </Link>
                {s.version && <span className="font-mono text-xs text-pc-text-faint">v{s.version}</span>}
                <Link to={`/sops/${encodeURIComponent(s.name)}/edit`} className="ml-auto inline-flex items-center gap-1 text-xs text-pc-accent hover:underline">
                  <Pencil size={12} aria-hidden="true" /> Edit
                </Link>
              </div>
              {s.description && <p className="mt-1 text-xs text-pc-text-secondary">{s.description}</p>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
