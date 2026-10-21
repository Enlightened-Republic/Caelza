// The Memory page: the Mind (xanima brain service) at a glance, recall by
// query, forget by node, and the review queue. Phone-first: one column at
// 390 px, cards stack. Everything goes through the gateway (`/api/mind/*`),
// which holds the per-agent tokens.
import { useCallback, useEffect, useState } from 'react';
import { Brain, RefreshCw, Search, Trash2 } from 'lucide-react';

import { Badge, Button, Card, ConfirmDialog, PageHeader, Select, StatCard } from '@/components/ui';
import {
  decideMindReview,
  getMindReview,
  getMindStatus,
  mindForget,
  mindRecall,
  type MindRecallHit,
  type MindReviewItem,
  type MindStatus,
} from '@/lib/mind';
import { brainTone, brainTotals, preview, scoreLabel, serviceLine, statusHighlights } from './mind.logic';

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
        <NotEnabled status={status} />
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
        </>
      )}
    </div>
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
          <p className="text-pc-text-muted">{status.hint}</p>
          <p className="text-pc-text-muted">
            Local notes stored by the Runtime itself are on the dashboard under <em>Memories</em>.
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
