// Pure helpers for the Memory page: totals, highlights and labels derived
// from the brain service's stats and status. No React, no fetch, so they
// run under node for the test next to them.
import type { MindBrainStats, MindBrainStatus, MindRecallHit, MindStatus } from '../lib/mind';

export interface BrainTotals {
  brains: number;
  nodes: number;
  edges: number;
  episodes: number;
  embedded: number;
}

export function brainTotals(brains: readonly MindBrainStats[] | undefined | null): BrainTotals {
  const out: BrainTotals = { brains: 0, nodes: 0, edges: 0, episodes: 0, embedded: 0 };
  for (const b of brains ?? []) {
    out.brains += 1;
    out.nodes += b.nodes ?? 0;
    out.edges += b.activeEdges ?? 0;
    out.episodes += b.episodes ?? 0;
    out.embedded += b.embedded ?? 0;
  }
  return out;
}

export type HighlightTone = 'neutral' | 'ok' | 'warn' | 'error';

export interface Highlight {
  label: string;
  value: string;
  tone: HighlightTone;
}

/** The handful of status numbers worth a glance, in reading order. */
export function statusHighlights(status: MindBrainStatus | undefined | null): Highlight[] {
  if (!status) return [];
  const out: Highlight[] = [];
  if (status.nodes) {
    out.push({ label: 'Active beliefs', value: String(status.nodes.active), tone: 'neutral' });
  }
  if (status.beliefs) {
    const { lowConfidence, contradicted } = status.beliefs;
    out.push({
      label: 'Low confidence',
      value: String(lowConfidence),
      tone: lowConfidence > 0 ? 'warn' : 'ok',
    });
    out.push({
      label: 'Disputed',
      value: String(contradicted),
      tone: contradicted > 0 ? 'warn' : 'ok',
    });
  }
  const held = status.quarantine?.held ?? 0;
  const pendingReviews = status.reviews?.pending ?? 0;
  if (status.quarantine || status.reviews) {
    const n = Math.max(held, pendingReviews);
    out.push({ label: 'Awaiting review', value: String(n), tone: n > 0 ? 'warn' : 'ok' });
  }
  if (status.goals) {
    const drifting = status.goals.drifting?.length ?? 0;
    out.push({
      label: 'Goals active',
      value: drifting > 0 ? `${status.goals.active} (${drifting} drifting)` : String(status.goals.active),
      tone: drifting > 0 ? 'warn' : 'neutral',
    });
  }
  if (status.decisions) {
    out.push({
      label: 'Decisions pending',
      value: String(status.decisions.pending),
      tone: status.decisions.pending > 0 ? 'neutral' : 'ok',
    });
  }
  if (status.lastSleep) {
    out.push({
      label: 'Last sleep',
      value: status.lastSleep.at ? status.lastSleep.ago : 'never',
      tone: status.lastSleep.at ? 'neutral' : 'warn',
    });
  }
  return out;
}

/** One line for the service row: where it is, which brain, whether it answers. */
export function serviceLine(status: MindStatus): { text: string; tone: HighlightTone } {
  if (!status.enabled) return { text: `Not active (memory.backend = ${status.backend ?? '?'})`, tone: 'neutral' };
  if (!status.healthy) return { text: `${status.url ?? 'service'} is not answering`, tone: 'error' };
  if (!status.has_token) return { text: `No token for ${status.agent ?? 'this agent'}`, tone: 'warn' };
  return { text: `${status.url} · ${status.agent} · ${status.scope}`, tone: 'ok' };
}

/** Score as a percentage label, or an empty string when the hit has none. */
export function scoreLabel(hit: Pick<MindRecallHit, 'score'>): string {
  if (typeof hit.score !== 'number' || !Number.isFinite(hit.score)) return '';
  return `${Math.round(Math.max(0, Math.min(1, hit.score)) * 100)}%`;
}

/** Brain badge tone: private is the agent's own, shared is the fleet's, room is a bus. */
export function brainTone(brain: string): HighlightTone {
  if (brain === 'shared') return 'warn';
  if (brain === 'room') return 'neutral';
  return 'ok';
}

const COLLAPSE_AT = 280;

/** Content preview: the first paragraph, cut at a word boundary. */
export function preview(content: string, limit = COLLAPSE_AT): { text: string; truncated: boolean } {
  const firstParagraph = content.trim().split(/\n\s*\n/)[0] ?? '';
  const flat = firstParagraph.replace(/\s+/g, ' ');
  if (flat.length <= limit && flat.length === content.trim().replace(/\s+/g, ' ').length) {
    return { text: flat, truncated: false };
  }
  const cut = flat.slice(0, limit);
  const atWord = cut.lastIndexOf(' ') > limit * 0.6 ? cut.slice(0, cut.lastIndexOf(' ')) : cut;
  return { text: `${atWord.trimEnd()}…`, truncated: true };
}
