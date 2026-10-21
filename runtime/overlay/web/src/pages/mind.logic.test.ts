import assert from 'node:assert/strict';
import test from 'node:test';
import { brainTotals, brainTone, preview, scoreLabel, serviceLine, statusHighlights } from './mind.logic.ts';

test('brain totals sum every brain the service reports', () => {
  const totals = brainTotals([
    { brain: 'private', nodes: 12, nodesByType: { semantic: 9 }, activeEdges: 4, episodes: 30, embedded: 10, writers: {}, lastConsolidation: null },
    { brain: 'shared', nodes: 3, nodesByType: {}, activeEdges: 1, episodes: 0, embedded: 3, writers: {}, lastConsolidation: null },
  ]);
  assert.deepEqual(totals, { brains: 2, nodes: 15, edges: 5, episodes: 30, embedded: 13 });
  assert.deepEqual(brainTotals(undefined).brains, 0);
});

test('status highlights read the counts that matter and colour them', () => {
  const highlights = statusHighlights({
    brain: 'private',
    nodes: { total: 20, active: 18, retracted: 1, superseded: 1, archived: 0 },
    beliefs: { lowConfidence: 2, contradicted: 0, flaggedForReview: 0 },
    quarantine: { mode: 'enforce', held: 1, logged: 0, accepted: 0, rejected: 0 },
    reviews: { pending: 0, byKind: {}, flagged: 0 },
    goals: { active: 3, tracked: 3, paused: 0, done: 1, drifting: [{ id: 'g1', title: 'ship', reason: 'stale' }] },
    decisions: { total: 4, pending: 0, resolved: 4 },
    lastSleep: { at: 1_760_000_000_000, ago: '3 hours ago', summary: null },
  });
  const byLabel = (label: string) => {
    const hit = highlights.find((h) => h.label === label);
    assert.ok(hit, `highlight ${label}`);
    return hit;
  };
  assert.equal(byLabel('Active beliefs').value, '18');
  assert.equal(byLabel('Low confidence').tone, 'warn');
  assert.equal(byLabel('Disputed').tone, 'ok');
  assert.equal(byLabel('Awaiting review').value, '1');
  assert.equal(byLabel('Goals active').value, '3 (1 drifting)');
  assert.equal(byLabel('Decisions pending').tone, 'ok');
  assert.equal(byLabel('Last sleep').value, '3 hours ago');
  assert.deepEqual(statusHighlights(null), []);
  const neverSlept = statusHighlights({ brain: 'x', lastSleep: { at: null, ago: 'never', summary: null } });
  assert.equal(neverSlept[0]?.value, 'never');
});

test('the service line says what is wrong first', () => {
  assert.equal(serviceLine({ enabled: false, backend: 'sqlite' }).text, 'Not active (memory.backend = sqlite)');
  assert.equal(serviceLine({ enabled: true, healthy: false, url: 'http://127.0.0.1:18790' }).tone, 'error');
  assert.equal(serviceLine({ enabled: true, healthy: true, has_token: false, agent: 'main' }).tone, 'warn');
  const ok = serviceLine({ enabled: true, healthy: true, has_token: true, url: 'http://127.0.0.1:18790', agent: 'main', scope: 'all' });
  assert.equal(ok.tone, 'ok');
  assert.equal(ok.text, 'http://127.0.0.1:18790 · main · all');
});

test('labels and previews are tidy', () => {
  assert.equal(scoreLabel({ score: 0.524 }), '52%');
  assert.equal(scoreLabel({ score: 1.7 }), '100%');
  assert.equal(scoreLabel({}), '');
  assert.equal(brainTone('private'), 'ok');
  assert.equal(brainTone('shared'), 'warn');
  assert.deepEqual(preview('short note'), { text: 'short note', truncated: false });
  const long = preview(`${'word '.repeat(80)}\n\nsecond paragraph`);
  assert.ok(long.truncated);
  assert.ok(long.text.endsWith('…'));
  assert.ok(long.text.length <= 282);
  assert.ok(!long.text.includes('second paragraph'));
});
