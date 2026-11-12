import assert from 'node:assert/strict';
import test from 'node:test';
import {
  FALLBACK_BACKEND,
  candidateLabel,
  cleanCode,
  devicesRole,
  hostOf,
  isListening,
  isLoopbackUrl,
  joinOps,
  leaveBackendOps,
  listenerOf,
  preferredCandidate,
  restartNote,
} from './mind.share.logic.ts';

test('the host of a service url, with and without brackets', () => {
  assert.equal(hostOf('http://192.168.1.5:18790'), '192.168.1.5');
  assert.equal(hostOf('http://[fd12::1]:18790/x'), 'fd12::1');
  assert.equal(hostOf('https://localhost'), 'localhost');
  assert.equal(hostOf('  http://127.0.0.1:18790/ '), '127.0.0.1');
});

test('loopback urls are this machine, anything else is another device', () => {
  assert.equal(isLoopbackUrl('http://127.0.0.1:18790'), true);
  assert.equal(isLoopbackUrl('http://localhost:18790'), true);
  assert.equal(isLoopbackUrl('http://[::1]:18790'), true);
  assert.equal(isLoopbackUrl('http://192.168.1.5:18790'), false);
  assert.equal(isLoopbackUrl('http://127.0.0.2:18790'), false, 'a shared loopback-range address is another device');
  assert.equal(isLoopbackUrl(undefined), false);
  assert.equal(isLoopbackUrl(''), false);
});

test('the devices card follows where the Mind is', () => {
  assert.equal(devicesRole({ enabled: false }), 'alone');
  assert.equal(devicesRole({ enabled: true, url: 'http://127.0.0.1:18790' }), 'host');
  assert.equal(devicesRole({ enabled: true, url: 'http://192.168.1.5:18790' }), 'joined');
});

test('addresses are labelled by network and Tailscale is offered first', () => {
  const lan = { host: '192.168.1.5', kind: 'lan' as const };
  const tail = { host: '100.101.102.103', kind: 'tailnet' as const };
  assert.equal(candidateLabel(lan), 'Home network · 192.168.1.5');
  assert.equal(candidateLabel(tail), 'Tailscale · 100.101.102.103');
  assert.deepEqual(preferredCandidate([lan, tail]), tail);
  assert.deepEqual(preferredCandidate([lan]), lan);
  assert.equal(preferredCandidate([]), null);
  assert.equal(preferredCandidate(undefined), null);
});

test('a listener is matched the way the service prints it', () => {
  assert.equal(listenerOf('192.168.1.5', 18790), '192.168.1.5:18790');
  assert.equal(listenerOf('fd12::1', 18790), '[fd12::1]:18790');
  assert.equal(isListening(['127.0.0.1:18790', '192.168.1.5:18790'], '192.168.1.5', 18790), true);
  assert.equal(isListening(['127.0.0.1:18790'], '192.168.1.5', 18790), false);
  assert.equal(isListening(undefined, '192.168.1.5', 18790), false);
});

test('joining writes the row, the encrypted token, the agent, no provisioning, then the backend', () => {
  const ops = joinOps('http://192.168.1.5:18790/', 'swt_abc');
  assert.deepEqual(ops, [
    { op: 'add', path: '/storage/xanima/default/url', value: 'http://192.168.1.5:18790' },
    { op: 'add', path: '/storage/xanima/default/token', value: 'swt_abc' },
    { op: 'add', path: '/storage/xanima/default/agent', value: 'main' },
    { op: 'add', path: '/storage/xanima/default/provision_token_file', value: '' },
    { op: 'add', path: '/memory/backend', value: 'xanima' },
  ]);
  assert.equal(ops[ops.length - 1]?.path, '/memory/backend', 'the backend flips last, once the row is whole');
});

test('leaving goes back to the local Mind when one answers, else to sqlite', () => {
  assert.deepEqual(leaveBackendOps(true), [{ op: 'add', path: '/memory/backend', value: 'xanima' }]);
  assert.deepEqual(leaveBackendOps(false), [{ op: 'add', path: '/memory/backend', value: FALLBACK_BACKEND }]);
});

test('a pasted code loses the whitespace a messenger adds', () => {
  assert.equal(cleanCode(' caelza-mind:abc\ndef  ghi '), 'caelza-mind:abcdefghi');
});

test('the restart note names the step for each side', () => {
  assert.match(restartNote('host'), /Restart the Mind once/);
  assert.match(restartNote('host'), /Node\.js/);
  assert.match(restartNote('joined'), /Reload daemon/);
  assert.match(restartNote('joined'), /Stop, then Start/);
});
