// The Mind (xanima brain service) as the dashboard sees it: `/api/mind/*`,
// proxied by the gateway so the per-agent bearer tokens stay on the host.
import { apiFetch } from './api';

export interface MindBrainStats {
  brain: string;
  nodes: number;
  nodesByType: Record<string, number>;
  activeEdges: number;
  episodes: number;
  embedded: number;
  writers: Record<string, number>;
  lastConsolidation: string | null;
}

/** `brain_status` per brain (xanima-core `BrainStatus`), the fields the page reads. */
export interface MindBrainStatus {
  brain: string;
  nodes?: { total: number; active: number; retracted: number; superseded: number; archived: number };
  episodes?: number;
  beliefs?: { lowConfidence: number; contradicted: number; flaggedForReview: number };
  hotConflicts?: Array<{ a: { id: string; label: string }; b: { id: string; label: string }; since: number }>;
  decisions?: { total: number; pending: number; resolved: number };
  goals?: { active: number; tracked: number; paused: number; done: number; drifting: Array<{ id: string; title: string; reason: string }> };
  reviews?: { pending: number; byKind: Record<string, number>; flagged: number };
  quarantine?: { mode: 'off' | 'log' | 'enforce'; held: number; logged: number; accepted: number; rejected: number };
  focus?: string | null;
  lastSleep?: { at: number | null; ago: string; summary: unknown };
  attention?: string[];
}

export interface MindStatus {
  enabled: boolean;
  backend?: string;
  hint?: string;
  healthy?: boolean;
  url?: string;
  scope?: string;
  agent?: string;
  default_agent?: string;
  agents?: string[];
  has_token?: boolean;
  token_file?: string;
  stats?: { agentId: string; brains: MindBrainStats[] } | null;
  status?: { agentId: string; brains: MindBrainStatus[] } | null;
  errors?: string[];
}

export interface MindRecallHit {
  brain: string;
  id: string;
  type: string;
  label: string;
  content: string;
  score?: number;
  retrievability?: number;
  importance?: number;
  writer?: string | null;
  source?: string | null;
  confidence?: string;
  source_type?: string;
  status?: string;
  created_at?: number;
  ago?: string;
  contradicted_at?: number | null;
  sensitivity?: string;
  room?: string;
}

export interface MindReviewItem {
  id: string;
  status: string;
  kind: string;
  section: string;
  label: string;
  flags: string[];
  reason: string | null;
  raw: string;
}

/** A commitment the agent made (xanima `CommitmentView`), from `brain_commitments`. */
export interface MindDigestCommitment {
  node_id: string;
  title: string;
  owner: string;
  counterparty: string;
  status: string;
  due_at: number | null;
  note: string | null;
  created_at: number;
  updated_at: number;
  done_at: number | null;
  blockers: Array<{ id: string; label: string; done: boolean }>;
  overdue: boolean;
  blocked: boolean;
}

/** An open hypothesis, question or assumption (xanima `OpenItemView`), from `brain_list_open`. */
export interface MindDigestOpenItem {
  node_id: string;
  kind: 'hypothesis' | 'question' | 'assumption';
  text: string;
  status: string;
  load_bearing: number;
  contradicted_at: number | null;
  confidence: string;
  created_at: number;
  updated_at: number;
  links: Array<{ id: string; type: string; label: string }>;
}

/** `GET /api/mind/digest`: what the Mind would tell you first. */
export interface MindDigest {
  agent: string;
  attention: string[];
  focus: string | null;
  last_sleep: { at: number | null; ago: string; summary: unknown } | null;
  commitments: MindDigestCommitment[];
  open_items: MindDigestOpenItem[];
  errors: string[];
}

function qs(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : '';
}

export function getMindStatus(agent?: string): Promise<MindStatus> {
  return apiFetch<MindStatus>(`/api/mind/status${qs({ agent })}`);
}

export function getMindDigest(agent?: string): Promise<MindDigest> {
  return apiFetch<MindDigest>(`/api/mind/digest${qs({ agent })}`);
}

export function mindRecall(
  q: string,
  limit = 12,
  agent?: string,
): Promise<{ agent: string; query: string; results: MindRecallHit[] }> {
  return apiFetch(`/api/mind/recall${qs({ q, limit, agent })}`);
}

export function mindForget(
  nodeId: string,
  agent?: string,
  visibility?: 'private' | 'shared',
): Promise<{ status: string; text: string }> {
  return apiFetch('/api/mind/forget', {
    method: 'POST',
    body: JSON.stringify({ node_id: nodeId, agent, visibility }),
  });
}

export function getMindReview(
  agent?: string,
  status: 'pending' | 'accepted' | 'rejected' | 'logged' | 'all' = 'pending',
): Promise<{ agent: string; status: string; items: MindReviewItem[]; raw: string }> {
  return apiFetch(`/api/mind/review${qs({ agent, status })}`);
}

export function decideMindReview(
  id: string,
  action: 'accept' | 'reject',
  reason?: string,
  agent?: string,
): Promise<{ status: string; text: string }> {
  return apiFetch('/api/mind/review', {
    method: 'POST',
    body: JSON.stringify({ id, action, reason, agent }),
  });
}

// --- one Mind for every device (`/api/mind/share`, `/api/mind/probe`) ----------------

/** An address this device could share, and the network it is on. */
export interface MindShareCandidate {
  host: string;
  kind: 'lan' | 'tailnet';
}

/** `GET /api/mind/share` on the device that hosts the Mind. */
export interface MindShareState {
  enabled: boolean;
  hosted_here: boolean;
  url?: string;
  agent?: string;
  port?: number;
  config_path?: string;
  config_error?: string | null;
  /** Addresses in the service's config.json (`tailnetHosts`). */
  configured?: string[];
  sharing?: boolean;
  /** Every configured address is one the service currently listens on. */
  reachable?: boolean;
  /** The configured addresses the service does not list yet (a restart away). */
  unbound?: string[];
  tokens_path?: string;
  /** A Mind is set up at the service root (sharing never creates one). */
  installed?: boolean;
  healthy?: boolean;
  version?: string | null;
  /** `host:port` for every listener the service reports. */
  listening?: string[];
  candidates?: MindShareCandidate[];
  share_tokens?: number;
  /** Not hosting: the memory backend when the Mind is off (`enabled: false`). */
  backend?: string;
  /** Not hosting: whether a Mind answers on this device's own loopback. */
  local_mind?: boolean;
  error?: string;
}

/** `POST /api/mind/share`: the state plus the fresh join code. */
export interface MindShareResult extends MindShareState {
  host: string;
  kind: string;
  share_url: string;
  code: string;
  token_id: string;
  restart_needed: boolean;
  added: boolean;
}

/** `DELETE /api/mind/share`. */
export interface MindUnshareResult extends MindShareState {
  removed: string[];
  revoked: number;
  restart_needed: boolean;
}

/** `POST /api/mind/probe`: the other device's Mind, checked with the code. */
export interface MindProbeResult {
  ok: boolean;
  url: string;
  agent: string;
  /** The code's token, back from the gateway for the config write. */
  token: string;
  version: string | null;
  addresses: string[];
  stats: unknown;
}

export function getMindShare(): Promise<MindShareState> {
  return apiFetch<MindShareState>('/api/mind/share');
}

export function startMindShare(host: string): Promise<MindShareResult> {
  return apiFetch<MindShareResult>('/api/mind/share', { method: 'POST', body: JSON.stringify({ host }) });
}

export function stopMindShare(): Promise<MindUnshareResult> {
  return apiFetch<MindUnshareResult>('/api/mind/share', { method: 'DELETE' });
}

export function probeMindCode(code: string): Promise<MindProbeResult> {
  return apiFetch<MindProbeResult>('/api/mind/probe', { method: 'POST', body: JSON.stringify({ code }) });
}
