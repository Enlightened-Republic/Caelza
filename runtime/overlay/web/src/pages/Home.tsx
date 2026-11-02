// Home: status before chat. Is it alive (Runtime), is it remembering (Mind),
// does it have a body (Body); what waits on the owner; what happened while
// they were away. Phone-first: one column at 390 px. The upstream dashboard
// (uptime, sessions, channels, health, cost) lives on at /dashboard, and the
// old `/?tab=` deep links are forwarded there.
import { useCallback, useState } from 'react';
import { Link, Navigate, useLocation, useSearchParams } from 'react-router-dom';
import {
  Activity,
  Brain,
  ClipboardList,
  LayoutDashboard,
  MessageSquare,
  Moon,
  RefreshCw,
  Smartphone,
  TabletSmartphone,
} from 'lucide-react';

import ApprovalQueue from '@/components/ApprovalQueue';
import { Badge, Button, Card, PageHeader, StatCard } from '@/components/ui';
import { getMapKeys, getSessions, getStatus } from '@/lib/api';
import { getBodiesStatus, getBodyDevices, type BodiesStatus, type BodyDevice } from '@/lib/bodies';
import { formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import { getMindDigest, getMindStatus, type MindDigest, type MindStatus } from '@/lib/mind';
import { listRuns, runStatusBadge, type SopRunSummary } from '@/lib/sops';
import { AgentLook } from '@/looks/Look';
import type { Session, StatusResponse } from '@/types/api';
import { usePolling } from '@/hooks/usePolling';
import {
  agentTiles,
  bodyTile,
  commitmentTone,
  dueLabel,
  mindTile,
  partitionRuns,
  recentSessions,
  runtimeTile,
  sessionLabel,
  sleepLine,
  sopEngineOff,
  SOP_OFF_TEXT,
  type AgentTile as AgentTileData,
  type Tile,
} from './home.logic';

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

interface Loaded<T> {
  data: T | null;
  error: string | null;
}

function settle<T>(result: PromiseSettledResult<T>): Loaded<T> {
  return result.status === 'fulfilled' ? { data: result.value, error: null } : { data: null, error: errorText(result.reason) };
}

const EMPTY: Loaded<never> = { data: null, error: null };

export default function Home() {
  const [params] = useSearchParams();
  const location = useLocation();
  const [runtime, setRuntime] = useState<Loaded<StatusResponse>>(EMPTY);
  const [mind, setMind] = useState<Loaded<MindStatus>>(EMPTY);
  const [digest, setDigest] = useState<Loaded<MindDigest>>(EMPTY);
  const [bodies, setBodies] = useState<Loaded<BodiesStatus>>(EMPTY);
  const [devices, setDevices] = useState<BodyDevice[] | null>(null);
  const [runs, setRuns] = useState<Loaded<SopRunSummary[]>>(EMPTY);
  const [sessions, setSessions] = useState<Loaded<Session[]>>(EMPTY);
  const [agents, setAgents] = useState<Loaded<string[]>>(EMPTY);
  const [reload, setReload] = useState(0);
  const refresh = useCallback(() => setReload((n) => n + 1), []);

  usePolling(
    async (isStale) => {
      const [s, m, b, r, se, ag] = await Promise.allSettled([getStatus(), getMindStatus(), getBodiesStatus(), listRuns(), getSessions(), getMapKeys('agents')]);
      if (isStale()) return;
      setRuntime(settle(s));
      setMind(settle(m));
      setBodies(settle(b));
      setRuns(settle(r));
      setSessions(settle(se));
      setAgents(ag.status === 'fulfilled' ? { data: ag.value.keys, error: null } : { data: null, error: errorText(ag.reason) });
      const mindStatus = m.status === 'fulfilled' ? m.value : null;
      const bodyStatus = b.status === 'fulfilled' ? b.value : null;
      const wantDigest = !!(mindStatus?.enabled && mindStatus.healthy && mindStatus.has_token);
      const wantDevices = !!(bodyStatus?.enabled && bodyStatus.connected && (bodyStatus.tools ?? []).includes('device_list'));
      const [d, dv] = await Promise.allSettled([
        wantDigest ? getMindDigest() : Promise.resolve(null),
        wantDevices ? getBodyDevices() : Promise.resolve(null),
      ]);
      if (isStale()) return;
      setDigest(d.status === 'fulfilled' ? { data: d.value, error: null } : { data: null, error: errorText(d.reason) });
      setDevices(dv.status === 'fulfilled' && dv.value ? dv.value.devices : null);
    },
    15000,
    [reload],
  );

  // The upstream dashboard's tabs were deep-linked as `/?tab=…`; keep them working.
  if (params.get('tab')) {
    return <Navigate to={{ pathname: '/dashboard', search: location.search }} replace />;
  }

  const tiles: Array<Tile & { icon: React.ReactNode }> = [
    { ...runtimeTile(runtime.data, runtime.error), icon: <Activity size={18} /> },
    { ...mindTile(mind.data, mind.error), icon: <Brain size={18} /> },
    { ...bodyTile(bodies.data, devices, bodies.error), icon: <Smartphone size={18} /> },
  ];

  const buckets = partitionRuns(runs.data ?? []);
  const privateBrain = mind.data?.status?.brains?.find((b) => b.brain === 'private') ?? mind.data?.status?.brains?.[0];
  const reviewPending = (privateBrain?.reviews?.pending ?? 0) + (privateBrain?.quarantine?.held ?? 0);
  const waitingCount = buckets.waiting.length + reviewPending;
  const recent = recentSessions(sessions.data ?? []);
  const crew = agentTiles(agents.data ?? [], sessions.data ?? []);

  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Home"
        description="Is it alive, is it remembering, what did it do while you were away."
        actions={
          <Button variant="ghost" size="sm" onClick={refresh} aria-label="Refresh">
            <RefreshCw size={14} aria-hidden="true" />
          </Button>
        }
      />

      <div className="grid gap-3 md:grid-cols-3">
        {tiles.map((tile) => (
          <Link key={tile.label} to={tile.to} className="block rounded-[var(--radius-md)] focus:outline-none focus-visible:ring-2 focus-visible:ring-pc-accent">
            <StatCard label={tile.label} value={tile.value} sublabel={tile.sublabel} tone={tile.tone} icon={tile.icon} className="h-full" />
          </Link>
        ))}
      </div>

      {/* The agents, each with its look (vision M8): the ones you talked to last come first; a tap opens the chat. */}
      <Card>
        <div className="mb-1 flex items-center justify-between gap-2">
          <div className="cz-eyebrow">Your agents</div>
          <Link to="/looks" className="text-xs text-pc-accent hover:underline">
            Change their looks
          </Link>
        </div>
        <p className="mb-3 text-xs text-pc-text-faint">Tap one to talk to it.</p>
        {agents.error ? (
          <p className="text-xs text-status-error">The agents could not be read: {agents.error}</p>
        ) : agents.data === null ? (
          <p className="text-sm text-pc-text-muted">…</p>
        ) : crew.tiles.length === 0 ? (
          <p className="text-sm text-pc-text-muted">
            No agent yet.{' '}
            <Link to="/setup" className="text-pc-accent hover:underline">
              Set one up
            </Link>
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4" data-testid="home-agents">
            {crew.tiles.map((tile) => (
              <AgentTile key={tile.alias} tile={tile} />
            ))}
            {crew.more > 0 && (
              <Link to="/agents" className="flex items-center justify-center rounded-[var(--radius-md)] border border-dashed border-pc-border p-3 text-sm text-pc-text-secondary hover:border-pc-accent/50">
                and {crew.more} more
              </Link>
            )}
          </div>
        )}
      </Card>

      <Card>
        <div className="mb-1 flex items-center justify-between">
          <div className="cz-eyebrow">Waiting on you</div>
          <Badge tone={waitingCount > 0 ? 'warn' : 'ok'}>{waitingCount}</Badge>
        </div>
        <p className="mb-3 text-xs text-pc-text-faint">Procedures held at an approval gate, and memories the Mind would not take without you.</p>
        {runs.error && sopEngineOff(runs.error) ? (
          <p className="text-sm text-pc-text-muted">{SOP_OFF_TEXT}</p>
        ) : (
          <>
            {runs.error && <p className="mb-2 text-xs text-status-error">Runs could not be read: {runs.error}</p>}
            <ApprovalQueue runs={buckets.waiting} onDecided={refresh} emptyText="No procedure is waiting for a decision." />
          </>
        )}
        {reviewPending > 0 && (
          <p className="mt-3 text-sm text-pc-text-secondary">
            {reviewPending} memory change{reviewPending === 1 ? '' : 's'} await your review.{' '}
            <Link to="/memory" className="text-pc-accent hover:underline">
              Open the review queue
            </Link>
          </p>
        )}
      </Card>

      <Card>
        <div className="mb-1 cz-eyebrow">Since you were away</div>
        <p className="mb-3 text-xs text-pc-text-faint">The Mind's attention, what it dreamt, what it committed to; and what the Runtime ran in the last day.</p>
        <Digest mind={mind.data} digest={digest} runs={buckets.finished} sessions={recent} />
      </Card>

      <Card>
        <div className="mb-3 cz-eyebrow">Go to</div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          <GoLink to="/agents" icon={<MessageSquare size={16} />} label={t('nav.agents')} hint="talk to the agent" />
          <GoLink to="/bodies" icon={<TabletSmartphone size={16} />} label="Bodies" hint="phones and sensors" />
          <GoLink to="/memory" icon={<Brain size={16} />} label="Memory" hint="what it remembers" />
          <GoLink to="/procedures" icon={<ClipboardList size={16} />} label="Procedures" hint="what it follows" />
          <GoLink to="/dashboard" icon={<LayoutDashboard size={16} />} label={t('nav.dashboard')} hint="runtime details" />
        </div>
      </Card>
    </div>
  );
}

/** One agent on Home: its look (alive, like in the agents list), its name, when you last talked. */
function AgentTile({ tile }: { tile: AgentTileData }) {
  return (
    <Link to={tile.to} title={tile.detail} className="flex items-center gap-3 rounded-[var(--radius-md)] border border-pc-border bg-pc-elevated p-3 text-sm hover:border-pc-accent/50">
      <span className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-[var(--radius-md)] bg-pc-accent/10">
        <AgentLook alias={tile.alias} size={40} decorative />
      </span>
      <span className="min-w-0">
        <span className="block truncate font-medium text-pc-text">{tile.alias}</span>
        <span className="block text-xs text-pc-text-faint">{tile.line}</span>
      </span>
    </Link>
  );
}

function GoLink({ to, icon, label, hint }: { to: string; icon: React.ReactNode; label: string; hint: string }) {
  return (
    <Link to={to} className="flex items-center gap-3 rounded-[var(--radius-md)] border border-pc-border bg-pc-elevated p-3 text-sm hover:border-pc-accent/50">
      <span className="text-pc-accent" aria-hidden="true">
        {icon}
      </span>
      <span>
        <span className="block font-medium text-pc-text">{label}</span>
        <span className="block text-xs text-pc-text-faint">{hint}</span>
      </span>
    </Link>
  );
}

function Digest({
  mind,
  digest,
  runs,
  sessions,
}: {
  mind: MindStatus | null;
  digest: Loaded<MindDigest>;
  runs: SopRunSummary[];
  sessions: Session[];
}) {
  const d = digest.data;
  const sleep = sleepLine(d?.last_sleep ?? null);
  const mindOff = mind !== null && !mind.enabled;
  const mindSilent = mind !== null && mind.enabled && (!mind.healthy || !mind.has_token);
  const nothingFromMind = d && d.attention.length === 0 && !d.focus && !sleep && d.commitments.length === 0 && d.open_items.length === 0;

  return (
    <div className="space-y-4">
      {mindOff && (
        <p className="text-sm text-pc-text-muted">
          The Mind is not the active memory backend, so there is no overnight digest.{' '}
          <Link to="/memory" className="text-pc-accent hover:underline">
            How to turn it on
          </Link>
        </p>
      )}
      {mindSilent && <p className="text-sm text-pc-text-muted">The Mind is configured but could not be read; its tile above says why.</p>}
      {digest.error && <p className="text-xs text-status-error">Digest: {digest.error}</p>}
      {d?.errors.map((e) => (
        <p key={e} className="text-xs text-status-warning">
          {e}
        </p>
      ))}

      {d && (d.attention.length > 0 || d.focus || sleep) && (
        <section>
          <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-pc-text-faint">The Mind</h3>
          {sleep && (
            <p className="flex items-center gap-2 text-sm text-pc-text-secondary">
              <Moon size={14} className="shrink-0 text-pc-accent" aria-hidden="true" /> {sleep}
            </p>
          )}
          {d.focus && (
            <p className="mt-1 text-sm text-pc-text-secondary">
              Focus: <span className="text-pc-text">{d.focus}</span>
            </p>
          )}
          {d.attention.length > 0 && (
            <ul className="mt-1 space-y-1 text-sm text-pc-text-secondary">
              {d.attention.map((line) => (
                <li key={line}>• {line}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      {d && d.commitments.length > 0 && (
        <section>
          <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-pc-text-faint">Commitments</h3>
          <ul className="space-y-1.5">
            {d.commitments.slice(0, 6).map((c) => {
              const due = dueLabel(c.due_at);
              return (
                <li key={c.node_id} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="text-pc-text">{c.title}</span>
                  {c.counterparty && c.counterparty !== 'self' && <span className="text-xs text-pc-text-faint">to {c.counterparty}</span>}
                  {due && <Badge tone={commitmentTone(c)}>{due}</Badge>}
                  {c.blocked && <Badge tone="warn">blocked</Badge>}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {d && d.open_items.length > 0 && (
        <section>
          <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-pc-text-faint">Open questions</h3>
          <ul className="space-y-1.5">
            {d.open_items.slice(0, 6).map((o) => (
              <li key={o.node_id} className="flex flex-wrap items-center gap-2 text-sm">
                <Badge tone={o.contradicted_at ? 'error' : 'neutral'}>{o.kind}</Badge>
                <span className="text-pc-text-secondary">{o.text}</span>
                {o.load_bearing ? <span className="text-xs text-pc-text-faint">load-bearing</span> : null}
              </li>
            ))}
          </ul>
        </section>
      )}

      {nothingFromMind && <p className="text-sm text-pc-text-muted">The Mind has nothing pressing: no open commitments or questions, nothing flagged.</p>}

      <section>
        <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-pc-text-faint">The Runtime, last 24 hours</h3>
        {runs.length === 0 && sessions.length === 0 && <p className="text-sm text-pc-text-muted">No procedures finished and no conversations moved.</p>}
        {runs.length > 0 && (
          <ul className="space-y-1.5">
            {runs.slice(0, 6).map((r) => (
              <li key={r.run_id} className="flex flex-wrap items-center gap-2 text-sm">
                <Link to={`/runs/${encodeURIComponent(r.sop_name)}/${encodeURIComponent(r.run_id)}`} className="text-pc-text hover:underline">
                  {r.sop_name}
                </Link>
                <Badge tone={runStatusBadge(r.status)}>{t(`sops.run_status.${r.status}`)}</Badge>
                <span className="text-xs text-pc-text-faint">{formatRelative(r.completed_at ?? r.started_at)}</span>
              </li>
            ))}
          </ul>
        )}
        {sessions.length > 0 && (
          <ul className="mt-2 space-y-1.5">
            {sessions.map((s) => (
              <li key={s.session_key} className="flex flex-wrap items-center gap-2 text-sm">
                {s.agent_alias && <AgentLook alias={s.agent_alias} size={18} frame="closed" decorative className="shrink-0" />}
                <Link to="/dashboard?tab=sessions" className="text-pc-text hover:underline">
                  {sessionLabel(s)}
                </Link>
                <span className="text-xs text-pc-text-faint">
                  {s.message_count} message{s.message_count === 1 ? '' : 's'} · {formatRelative(s.last_activity)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
