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
