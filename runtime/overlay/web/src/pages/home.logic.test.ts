import assert from 'node:assert/strict';
import test from 'node:test';
import {
  bodyTile,
  commitmentTone,
  dueLabel,
  formatUptime,
  mindTile,
  partitionRuns,
  recentSessions,
  runtimeTile,
  sessionLabel,
  sleepLine,
} from './home.logic.ts';

const NOW = Date.parse('2026-10-21T12:00:00Z');

test('the Runtime tile reads health first', () => {
  assert.equal(formatUptime(59), '0m');
  assert.equal(formatUptime(3 * 3600 + 5 * 60), '3h 5m');
  assert.equal(formatUptime(2 * 86400 + 3600), '2d 1h');
  const base = { version: '0.8.6', uptime_seconds: 7200, model: 'deepseek-r1:7b', model_provider: 'llamacpp.local', memory_backend: 'xanima' };
  const alive = runtimeTile({ ...base, health: { components: { gateway: { status: 'ok' }, cron: { status: 'ok' } } } });
  assert.equal(alive.value, 'Alive');
  assert.equal(alive.tone, 'ok');
  assert.equal(alive.sublabel, 'v0.8.6 · up 2h 0m · llamacpp.local / deepseek-r1:7b');
  assert.equal(alive.to, '/dashboard');
  const failing = runtimeTile({ ...base, health: { components: { gateway: { status: 'ok' }, 'channel:telegram': { status: 'Error' } } } });
  assert.equal(failing.value, '1 component failing');
  assert.equal(failing.tone, 'error');
  assert.ok(failing.sublabel.startsWith('channel:telegram · '));
  const starting = runtimeTile({ ...base, health: { components: { memory: { status: 'starting' } } } });
  assert.equal(starting.value, 'Starting');
  assert.equal(starting.tone, 'warn');
  assert.equal(runtimeTile(null).value, '…');
  assert.equal(runtimeTile(null, 'API 502').tone, 'error');
});

test('the Mind tile says what is wrong first', () => {
  assert.deepEqual(mindTile({ enabled: false, backend: 'sqlite' }), {
    label: 'Mind',
    value: 'Not active',
    sublabel: 'memory.backend = sqlite',
    tone: 'neutral',
    to: '/memory',
  });
  assert.equal(mindTile({ enabled: true, healthy: false, url: 'http://127.0.0.1:18790' }).value, 'Not answering');
  assert.equal(mindTile({ enabled: true, healthy: true, has_token: false, agent: 'main' }).tone, 'warn');
  const fine = mindTile({
    enabled: true,
    healthy: true,
    has_token: true,
    stats: {
      agentId: 'main',
      brains: [
        { brain: 'private', nodes: 120, nodesByType: {}, activeEdges: 0, episodes: 0, embedded: 0, writers: {}, lastConsolidation: null },
        { brain: 'shared', nodes: 5, nodesByType: {}, activeEdges: 0, episodes: 0, embedded: 0, writers: {}, lastConsolidation: null },
      ],
    },
    status: { agentId: 'main', brains: [{ brain: 'private', reviews: { pending: 2, byKind: {}, flagged: 0 }, lastSleep: { at: 1, ago: '3 hours ago', summary: null } }] },
  });
  assert.equal(fine.value, '125 beliefs');
  assert.equal(fine.sublabel, '2 brains · 2 awaiting review · slept 3 hours ago');
  assert.equal(fine.tone, 'warn');
  assert.equal(mindTile(null).value, '…');
});

test('the Body tile counts reachable phones', () => {
  assert.equal(bodyTile({ enabled: false, reason: 'no entry', servers: [] }, null).value, 'Not configured');
  const server = { name: 'body', transport: 'stdio', command: 'caelza-body', args: ['serve'] };
  assert.equal(bodyTile({ enabled: true, connected: false, servers: ['body'], server }, null).tone, 'error');
  const connected = bodyTile({ enabled: true, connected: true, servers: ['body'], server, tools: ['a', 'b'] }, null);
  assert.equal(connected.value, 'Connected');
  assert.equal(connected.sublabel, 'body · 2 tools');
  const devices = [
    { name: 'self', self: true, host: null, last_seen: null, reachable: true },
    { name: 'pixel', self: false, host: '10.0.0.5:5555', last_seen: null, reachable: false },
  ];
  const some = bodyTile({ enabled: true, connected: true, servers: ['body'], server }, devices);
  assert.equal(some.value, '1 of 2 reachable');
  assert.equal(some.sublabel, 'body · this phone + 1 paired');
  assert.equal(some.tone, 'warn');
  assert.equal(bodyTile({ enabled: true, connected: true, servers: ['body'], server }, [devices[0]!]).tone, 'ok');
  assert.equal(bodyTile(null, null, 'boom').value, 'Unreachable');
});

test('runs are bucketed by what the owner must do', () => {
  const run = (id: string, status: string, started: string, completed: string | null = null) =>
    ({ run_id: id, sop_name: `sop-${id}`, status, current_step: 1, total_steps: 3, started_at: started, completed_at: completed, trigger_source: 'manual', active: completed === null }) as never;
  const runs = [
    run('a', 'running', '2026-10-21T11:00:00Z'),
    run('b', 'waiting_approval', '2026-10-21T10:00:00Z'),
    run('c', 'completed', '2026-10-21T08:00:00Z', '2026-10-21T08:30:00Z'),
    run('d', 'failed', '2026-10-19T08:00:00Z', '2026-10-19T08:30:00Z'),
    run('e', 'paused_checkpoint', '2026-10-21T09:00:00Z'),
    run('f', 'cancel_requested', '2026-10-21T11:30:00Z'),
  ];
  const buckets = partitionRuns(runs, NOW);
  assert.deepEqual(buckets.waiting.map((r) => r.run_id), ['e', 'b']);
  assert.deepEqual(buckets.running.map((r) => r.run_id), ['f', 'a']);
  assert.deepEqual(buckets.finished.map((r) => r.run_id), ['c']);
  assert.deepEqual(partitionRuns([], NOW), { waiting: [], running: [], finished: [] });
});

test('sessions, due dates and sleep read tidily', () => {
  const sessions = [
    { session_id: 'old', session_key: 'k1', last_activity: '2026-10-19T12:00:00Z', message_count: 4, agent_alias: 'main', channel_id: null },
    { session_id: 'new', session_key: 'k2', last_activity: '2026-10-21T11:00:00Z', message_count: 9, agent_alias: 'main', channel_id: 'telegram.home' },
    { session_id: 'named', session_key: 'k3', last_activity: '2026-10-21T09:00:00Z', message_count: 1, name: 'Grandma', agent_alias: null, channel_id: null },
  ];
  assert.deepEqual(recentSessions(sessions, NOW).map((s) => s.session_id), ['new', 'named']);
  assert.equal(recentSessions(sessions, NOW, undefined, 1).length, 1);
  assert.equal(sessionLabel(sessions[1]!), 'main on telegram.home');
  assert.equal(sessionLabel(sessions[2]!), 'Grandma');
  assert.equal(sessionLabel({ ...sessions[0]!, agent_alias: null }), 'agent');
  assert.equal(dueLabel(null, NOW), null);
  assert.equal(dueLabel(NOW - 2 * 3600 * 1000, NOW), 'overdue by 2 h');
  assert.equal(dueLabel(NOW + 30 * 1000, NOW), 'due now');
  assert.equal(dueLabel(NOW + 3 * 86400 * 1000, NOW), 'due in 3 d');
  assert.equal(dueLabel(NOW + 20 * 60 * 1000, NOW), 'due in 20 min');
  assert.equal(commitmentTone({ overdue: true, blocked: false }), 'error');
  assert.equal(commitmentTone({ overdue: false, blocked: true }), 'warn');
  assert.equal(commitmentTone({ overdue: false, blocked: false }), 'neutral');
  assert.equal(sleepLine(null), null);
  assert.equal(sleepLine({ at: null, ago: 'never', summary: null }), null);
  assert.equal(sleepLine({ at: 1, ago: '3 hours ago', summary: null }), 'slept 3 hours ago');
  assert.equal(
    sleepLine({ at: 1, ago: '3 hours ago', summary: { nodesBefore: 120, nodesAfter: 118, pruned: 4, newContradictions: 1, flaggedForReview: 2 } }),
    'slept 3 hours ago: 120 → 118 nodes, 4 pruned, 1 new contradiction, 2 flagged for review',
  );
});
