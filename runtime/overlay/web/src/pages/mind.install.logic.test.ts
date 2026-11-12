import assert from 'node:assert/strict';
import test from 'node:test';
import { POLL_MS, installBackendOps, megabytes, percent, stageLabel } from './mind.install.logic.ts';

test('every stage has words of its own', () => {
  for (const stage of ['release', 'node', 'install', 'launcher', 'tokens', 'start', 'startup', 'done']) {
    const label = stageLabel(stage);
    assert.ok(label.length > 2 && label !== stage, stage);
  }
  assert.equal(stageLabel('odd'), 'Odd');
  assert.equal(stageLabel(''), 'Working');
});

test('progress is a bounded percentage, or unknown', () => {
  assert.equal(percent(50, 200), 25);
  assert.equal(percent(300, 200), 100);
  assert.equal(percent(0, 0), null);
  assert.equal(percent(10, -1), null);
});

test('sizes read like a download dialog', () => {
  assert.equal(megabytes(31 * 1024 * 1024), '31 MB');
  assert.equal(megabytes(1.26 * 1024 * 1024), '1.3 MB');
});

test('the backend flips to the Mind in one write', () => {
  assert.deepEqual(installBackendOps(), [{ op: 'add', path: '/memory/backend', value: 'xanima' }]);
  assert.ok(POLL_MS >= 1000);
});
