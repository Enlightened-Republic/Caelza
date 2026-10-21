// Runs the SOP engine is holding for the owner: a step waiting on approval or
// a paused checkpoint. Approve resumes the run, Deny stops it. Shared by the
// Home page ("Waiting on you") and the Procedures page.
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Check, ExternalLink, X } from 'lucide-react';

import { Badge, Button } from '@/components/ui';
import { formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import { decideSop, runStatusBadge, type SopRunSummary } from '@/lib/sops';

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

export interface ApprovalQueueProps {
  /** Runs in `waiting_approval` or `paused_checkpoint`. */
  runs: SopRunSummary[];
  /** Called after a decision went through so the caller refreshes its list. */
  onDecided: () => void;
  emptyText?: string;
}

export default function ApprovalQueue({ runs, onDecided, emptyText }: ApprovalQueueProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const decide = async (run: SopRunSummary, decision: 'approve' | 'deny') => {
    setBusy(run.run_id);
    setError(null);
    try {
      await decideSop(run.sop_name, run.run_id, decision === 'approve' ? 'approve' : { deny: {} });
      onDecided();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(null);
    }
  };

  if (runs.length === 0) {
    return <p className="text-sm text-pc-text-muted">{emptyText ?? 'Nothing is waiting on you.'}</p>;
  }

  return (
    <div>
      {error && (
        <div role="alert" className="mb-3 rounded-[var(--radius-md)] border border-status-error/25 bg-status-error/10 p-3 text-xs text-status-error">
          {error}
        </div>
      )}
      <ul className="space-y-2">
        {runs.map((run) => (
          <li key={run.run_id} className="rounded-[var(--radius-md)] border border-status-warning/25 bg-pc-elevated p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-sm font-medium text-pc-text">{run.sop_name}</span>
              <Badge tone={runStatusBadge(run.status)}>{t(`sops.run_status.${run.status}`)}</Badge>
              <span className="text-pc-text-faint">
                step {run.current_step} of {run.total_steps}
              </span>
              <span className="text-pc-text-faint">· {run.trigger_source}</span>
              <span className="ml-auto text-pc-text-faint">{formatRelative(run.started_at)}</span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button size="sm" onClick={() => void decide(run, 'approve')} disabled={busy !== null}>
                <Check size={14} aria-hidden="true" />
                <span className="ml-1.5">{busy === run.run_id ? 'Deciding…' : 'Approve'}</span>
              </Button>
              <Button size="sm" variant="danger" onClick={() => void decide(run, 'deny')} disabled={busy !== null}>
                <X size={14} aria-hidden="true" />
                <span className="ml-1.5">Deny</span>
              </Button>
              <Link
                to={`/runs/${encodeURIComponent(run.sop_name)}/${encodeURIComponent(run.run_id)}`}
                className="ml-auto inline-flex items-center gap-1 text-xs text-pc-accent hover:underline"
              >
                Open <ExternalLink size={12} aria-hidden="true" />
              </Link>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
