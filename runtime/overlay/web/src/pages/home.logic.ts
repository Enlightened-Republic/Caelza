// Pure helpers for the Home and Procedures pages; tested under node, no React.
import type { BodiesStatus, BodyDevice } from '@/lib/bodies';
import type { MindDigestCommitment, MindStatus } from '@/lib/mind';
import type { SopRunSummary } from '@/lib/sops';

export type Tone = 'ok' | 'warn' | 'error' | 'neutral';

/** One status tile on Home: what it says, how loud, and where it leads. */
export interface Tile {
  label: string;
  value: string;
  sublabel: string;
  tone: Tone;
  to: string;
}

/** The slice of the gateway's `StatusResponse` the Runtime tile reads. */
export interface RuntimeStatusSlice {
  version: string;
  uptime_seconds: number;
  model: string;
  model_provider?: string | null;
  memory_backend: string;
  health?: { components?: Record<string, { status: string }> } | null;
}

export function formatUptime(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

/** Component health states that mean "not fine"; anything else but `starting` counts as healthy. */
const FAILING = new Set(['error', 'failed', 'failing', 'unhealthy', 'down', 'crashed', 'degraded']);

export function runtimeTile(status: RuntimeStatusSlice | null, error?: string | null): Tile {
  const to = '/dashboard';
  if (error) return { label: 'Runtime', value: 'Unreachable', sublabel: error, tone: 'error', to };
  if (!status) return { label: 'Runtime', value: '…', sublabel: 'reading', tone: 'neutral', to };
  const components = Object.entries(status.health?.components ?? {});
  const failing = components.filter(([, c]) => FAILING.has(c.status.toLowerCase())).map(([name]) => name);
  const starting = components.filter(([, c]) => c.status.toLowerCase() === 'starting').map(([name]) => name);
  const model = [status.model_provider, status.model].filter((p): p is string => !!p).join(' / ');
  const sublabel = [`v${status.version}`, `up ${formatUptime(status.uptime_seconds)}`, model].filter(Boolean).join(' · ');
  if (failing.length > 0) {
    return {
      label: 'Runtime',
      value: `${failing.length} component${failing.length === 1 ? '' : 's'} failing`,
      sublabel: `${failing.join(', ')} · ${sublabel}`,
      tone: 'error',
      to,
    };
  }
  if (starting.length > 0) {
    return { label: 'Runtime', value: 'Starting', sublabel: `${starting.join(', ')} · ${sublabel}`, tone: 'warn', to };
  }
  return { label: 'Runtime', value: 'Alive', sublabel, tone: 'ok', to };
}

export function mindTile(mind: MindStatus | null, error?: string | null): Tile {
  const to = '/memory';
  if (error) return { label: 'Mind', value: 'Unreachable', sublabel: error, tone: 'error', to };
  if (!mind) return { label: 'Mind', value: '…', sublabel: 'reading', tone: 'neutral', to };
  if (!mind.enabled) {
    return { label: 'Mind', value: 'Not active', sublabel: `memory.backend = ${mind.backend ?? '?'}`, tone: 'neutral', to };
  }
  if (!mind.healthy) return { label: 'Mind', value: 'Not answering', sublabel: mind.url ?? '', tone: 'error', to };
  if (!mind.has_token) return { label: 'Mind', value: 'No token', sublabel: `for agent ${mind.agent ?? ''}`.trim(), tone: 'warn', to };
  const brains = mind.stats?.brains ?? [];
  const nodes = brains.reduce((n, b) => n + (b.nodes ?? 0), 0);
  const brain = mind.status?.brains?.find((b) => b.brain === 'private') ?? mind.status?.brains?.[0];
  const pending = (brain?.reviews?.pending ?? 0) + (brain?.quarantine?.held ?? 0);
  const parts = [`${brains.length} brain${brains.length === 1 ? '' : 's'}`];
  if (pending > 0) parts.push(`${pending} awaiting review`);
  if (brain?.lastSleep?.ago) parts.push(`slept ${brain.lastSleep.ago}`);
  return {
    label: 'Mind',
    value: `${nodes} belief${nodes === 1 ? '' : 's'}`,
    sublabel: parts.join(' · '),
    tone: pending > 0 ? 'warn' : 'ok',
    to,
  };
}

export function bodyTile(body: BodiesStatus | null, devices: BodyDevice[] | null, error?: string | null): Tile {
  const to = '/bodies';
  if (error) return { label: 'Body', value: 'Unreachable', sublabel: error, tone: 'error', to };
  if (!body) return { label: 'Body', value: '…', sublabel: 'reading', tone: 'neutral', to };
  if (!body.enabled) return { label: 'Body', value: 'Not configured', sublabel: body.reason ?? '', tone: 'neutral', to };
  const name = body.server?.name ?? 'body';
  if (!body.connected) return { label: 'Body', value: 'Not answering', sublabel: name, tone: 'error', to };
  if (!devices) {
    return { label: 'Body', value: 'Connected', sublabel: `${name} · ${(body.tools ?? []).length} tools`, tone: 'ok', to };
  }
  const reachable = devices.filter((d) => d.reachable).length;
  const paired = devices.filter((d) => !d.self).length;
  const tone: Tone = reachable === devices.length ? 'ok' : reachable === 0 ? 'error' : 'warn';
  return {
    label: 'Body',
    value: `${reachable} of ${devices.length} reachable`,
    sublabel: `${name} · this phone${paired > 0 ? ` + ${paired} paired` : ''}`,
    tone,
    to,
  };
}

export interface RunBuckets {
  /** Held for a decision, oldest first. */
  waiting: SopRunSummary[];
  /** Live and not waiting, newest first. */
  running: SopRunSummary[];
  /** Ended inside the window, newest first. */
  finished: SopRunSummary[];
}

const DAY_MS = 24 * 3600 * 1000;

export function partitionRuns(runs: SopRunSummary[], now = Date.now(), windowMs = DAY_MS): RunBuckets {
  const waiting: SopRunSummary[] = [];
  const running: SopRunSummary[] = [];
  const finished: SopRunSummary[] = [];
  for (const run of runs) {
    switch (run.status) {
      case 'waiting_approval':
      case 'paused_checkpoint':
        waiting.push(run);
        break;
      case 'pending':
      case 'running':
      case 'cancel_requested':
        running.push(run);
        break;
      default: {
        const ended = Date.parse(run.completed_at ?? run.started_at);
        if (!Number.isNaN(ended) && now - ended <= windowMs) finished.push(run);
      }
    }
  }
  waiting.sort((a, b) => a.started_at.localeCompare(b.started_at));
  running.sort((a, b) => b.started_at.localeCompare(a.started_at));
  finished.sort((a, b) => (b.completed_at ?? b.started_at).localeCompare(a.completed_at ?? a.started_at));
  return { waiting, running, finished };
}

export interface SessionSlice {
  session_id: string;
  session_key: string;
  last_activity: string;
  message_count: number;
  name?: string;
  agent_alias: string | null;
  channel_id: string | null;
}

/** Sessions that moved inside the window, most recent first. */
export function recentSessions<T extends SessionSlice>(sessions: T[], now = Date.now(), windowMs = DAY_MS, limit = 6): T[] {
  return sessions
    .filter((s) => {
      const at = Date.parse(s.last_activity);
      return !Number.isNaN(at) && now - at <= windowMs;
    })
    .sort((a, b) => b.last_activity.localeCompare(a.last_activity))
    .slice(0, limit);
}

export function sessionLabel(session: SessionSlice): string {
  if (session.name) return session.name;
  const who = session.agent_alias ?? 'agent';
  const where = session.channel_id ? ` on ${session.channel_id}` : '';
  return `${who}${where}`;
}

/** `just now`, `45 min ago`, `6 h ago`, `3 d ago`; null for a time that does not read. */
export function agoLabel(iso: string | null | undefined, now = Date.now()): string | null {
  if (!iso) return null;
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return null;
  const diff = Math.max(0, now - at);
  if (diff < 60 * 1000) return 'just now';
  if (diff < 3600 * 1000) return `${Math.round(diff / 60000)} min ago`;
  if (diff < DAY_MS * 2) return `${Math.round(diff / (3600 * 1000))} h ago`;
  return `${Math.round(diff / DAY_MS)} d ago`;
}

/** One agent on Home: its look is drawn beside this, the tile opens its chat. */
export interface AgentTile {
  alias: string;
  to: string;
  /** Short enough for half a phone's width: `3 h ago`, or `no chat yet`. */
  line: string;
  /** The whole of it, for the tile's tooltip: `talked 3 h ago · 12 messages`, or `no conversation yet`. */
  detail: string;
  lastActivity: string | null;
}

/** The agents on Home (vision M8): the ones talked to most recently first,
 *  then the rest in config order; blanks and repeats dropped; at most `limit`
 *  shown, the overflow counted for an "and N more" link. */
export function agentTiles(aliases: string[], sessions: SessionSlice[], now = Date.now(), limit = 8): { tiles: AgentTile[]; more: number } {
  const latest = new Map<string, { at: string; messages: number }>();
  for (const s of sessions) {
    if (!s.agent_alias) continue;
    const cur = latest.get(s.agent_alias);
    latest.set(s.agent_alias, {
      at: cur && cur.at.localeCompare(s.last_activity) >= 0 ? cur.at : s.last_activity,
      messages: (cur?.messages ?? 0) + s.message_count,
    });
  }
  const seen = new Set<string>();
  const ordered = aliases
    .map((a) => a.trim())
    .filter((a) => {
      if (!a || seen.has(a)) return false;
      seen.add(a);
      return true;
    })
    .map((alias, i) => ({ alias, i, last: latest.get(alias) ?? null }))
    .sort((a, b) => {
      if (a.last && b.last) return b.last.at.localeCompare(a.last.at) || a.i - b.i;
      if (a.last) return -1;
      if (b.last) return 1;
      return a.i - b.i;
    });
  const tiles = ordered.slice(0, limit).map(({ alias, last }) => {
    const ago = last ? agoLabel(last.at, now) : null;
    const talked = last && ago;
    return {
      alias,
      to: `/agent/${encodeURIComponent(alias)}`,
      line: talked ? ago : 'no chat yet',
      detail: talked ? `talked ${ago} · ${last.messages} message${last.messages === 1 ? '' : 's'}` : 'no conversation yet',
      lastActivity: last?.at ?? null,
    };
  });
  return { tiles, more: Math.max(0, ordered.length - limit) };
}

/** `overdue by 2 h`, `due in 3 d`, `due today`; null without a due date. */
export function dueLabel(dueAt: number | null | undefined, now = Date.now()): string | null {
  if (dueAt === null || dueAt === undefined) return null;
  const diff = dueAt - now;
  const span = (ms: number): string => {
    const abs = Math.abs(ms);
    if (abs < 3600 * 1000) return `${Math.max(1, Math.round(abs / 60000))} min`;
    if (abs < DAY_MS * 2) return `${Math.round(abs / (3600 * 1000))} h`;
    return `${Math.round(abs / DAY_MS)} d`;
  };
  if (diff < -60 * 1000) return `overdue by ${span(diff)}`;
  if (diff < 60 * 1000) return 'due now';
  return `due in ${span(diff)}`;
}

export function commitmentTone(c: Pick<MindDigestCommitment, 'overdue' | 'blocked'>): Tone {
  if (c.overdue) return 'error';
  if (c.blocked) return 'warn';
  return 'neutral';
}

/** The SOP engine answers 503 "SOP subsystem not enabled" when the config has
 *  no `[sop]` block; that is a state to explain, not an error to shout. */
export function sopEngineOff(errorMessage: string | null | undefined): boolean {
  if (!errorMessage) return false;
  return errorMessage.includes('SOP subsystem not enabled') || /^API 503\b/.test(errorMessage);
}

export const SOP_OFF_TEXT = 'Procedures are off in this config: the SOP engine is not enabled, so nothing can run or wait here.';

/** The library lists procedures from disk, but the runs route answers 503: the engine is built by `caelza daemon`, not by a standalone gateway. */
export const SOP_ENGINE_NOT_RUNNING_TEXT =
  'The SOP engine is not running in this process: the procedures are listed from disk, but nothing can run or wait here. `caelza gateway start` serves the dashboard alone; start the Runtime with `caelza daemon`.';

/** What to say when the runs route reports the engine off, given whether the library found any procedures. */
export function sopOffText(listed: boolean): string {
  return listed ? SOP_ENGINE_NOT_RUNNING_TEXT : SOP_OFF_TEXT;
}

/** The phone playbooks (body/sops) ship under this prefix; the library gives them a Run that asks which phone. */
export const PLAYBOOK_PREFIX = 'phone-';

export function isPlaybook(name: string): boolean {
  return name.startsWith(PLAYBOOK_PREFIX);
}

/** The trigger payload a playbook reads: which phone (`self` is the one the Body runs on), and for the debloat an optional keep list. */
export function playbookPayload(device: string, keep?: string): string {
  const payload: Record<string, string> = { device: device.trim() || 'self' };
  const pinned = (keep ?? '').trim();
  if (pinned) payload.keep = pinned;
  return JSON.stringify(payload);
}

/** One line a device picker can show for a Body device. */
export function deviceOptionLabel(d: BodyDevice): string {
  const how = d.kind === 'http' ? ' · over HTTP' : '';
  return `${d.name}${d.self ? ' (this phone)' : how}${d.reachable ? '' : ' · unreachable'}`;
}

/** A Run target: one device, or every device in a group (`group:<name>`). */
export interface RunTarget {
  value: string;
  label: string;
}

export const GROUP_TARGET_PREFIX = 'group:';

/** The devices first (this phone leading), then each group with its member count. */
export function runTargets(devices: BodyDevice[]): RunTarget[] {
  const targets: RunTarget[] = devices.map((d) => ({ value: d.name, label: deviceOptionLabel(d) }));
  const groups = new Map<string, number>();
  for (const d of devices) {
    for (const g of d.groups ?? []) {
      const t = g.trim();
      if (t) groups.set(t, (groups.get(t) ?? 0) + 1);
    }
  }
  for (const [g, n] of [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    targets.push({ value: `${GROUP_TARGET_PREFIX}${g}`, label: `every phone in ${g} (${n})` });
  }
  if (targets.length === 0) targets.push({ value: 'self', label: 'self (this phone)' });
  return targets;
}

/** The device names a target stands for: the device itself, or a group's members in name order. */
export function expandTarget(devices: BodyDevice[], target: string): string[] {
  if (target.startsWith(GROUP_TARGET_PREFIX)) {
    const g = target.slice(GROUP_TARGET_PREFIX.length);
    return devices
      .filter((d) => (d.groups ?? []).some((x) => x.trim() === g))
      .map((d) => d.name)
      .sort();
  }
  return [target.trim() || 'self'];
}

/** The run endpoint's refusals in plain words; anything unknown passes through. */
export function runRefusal(message: string, listed = true): string {
  // Admission before "engine off": the engine answers a held or deferred run with 503 as well.
  if (/^API 409\b/.test(message) || /held \(|already (running|in flight)|execution slots|admission|deferred|cooldown/i.test(message)) {
    return 'A run of this procedure is already in flight. Wait for it, or stop it first.';
  }
  if (sopEngineOff(message)) return sopOffText(listed);
  if (/no owning agent|cannot be started here|unowned/i.test(message)) {
    return 'This procedure has no owning agent, so it cannot start from the dashboard. Set `agent` in its SOP.toml, or start it from a chat.';
  }
  if (/^API 404\b/.test(message)) return 'The procedure is not loaded. Install or save it, then refresh.';
  if (/^API 400\b/.test(message) && /payload/i.test(message)) return 'The payload was refused: it must be JSON, like {"device": "self"}.';
  return message;
}

export interface SleepSummarySlice {
  nodesBefore?: number;
  nodesAfter?: number;
  pruned?: number;
  newContradictions?: number;
  flaggedForReview?: number;
}

/** `slept 3 hours ago: 120 → 118 nodes, 4 pruned, 1 flagged for review`; null when it never slept. */
export function sleepLine(lastSleep: { at: number | null; ago: string; summary: unknown } | null | undefined): string | null {
  if (!lastSleep || lastSleep.at === null) return null;
  const parts: string[] = [];
  const s = (lastSleep.summary ?? null) as SleepSummarySlice | null;
  if (s && typeof s === 'object') {
    if (typeof s.nodesBefore === 'number' && typeof s.nodesAfter === 'number') parts.push(`${s.nodesBefore} → ${s.nodesAfter} nodes`);
    if (s.pruned) parts.push(`${s.pruned} pruned`);
    if (s.newContradictions) parts.push(`${s.newContradictions} new contradiction${s.newContradictions === 1 ? '' : 's'}`);
    if (s.flaggedForReview) parts.push(`${s.flaggedForReview} flagged for review`);
  }
  return `slept ${lastSleep.ago}${parts.length ? `: ${parts.join(', ')}` : ''}`;
}
