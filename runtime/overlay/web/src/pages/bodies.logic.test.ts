import assert from 'node:assert/strict';
import test from 'node:test';
import {
  batterySummary,
  deviceLabel,
  filterPackages,
  groupLabel,
  locationSummary,
  notificationItems,
  pairCodeLooksRight,
  pairHostLooksRight,
  relativeAge,
  serviceLine,
} from './bodies.logic.ts';

test('the service line says what is wrong first', () => {
  assert.deepEqual(serviceLine({ enabled: false, reason: 'no [[mcp.servers]] entry named "body"' }), {
    tone: 'neutral',
    text: 'Not configured (no [[mcp.servers]] entry named "body")',
  });
  assert.equal(serviceLine({ enabled: false }).text, 'Not configured');
  const server = { name: 'body', transport: 'stdio', command: 'caelza-body', args: ['serve'] };
  assert.deepEqual(serviceLine({ enabled: true, connected: false, server }), { tone: 'error', text: 'body · not answering' });
  assert.deepEqual(serviceLine({ enabled: true, connected: true, server }), {
    tone: 'ok',
    text: 'body · stdio · caelza-body serve',
  });
  assert.equal(deviceLabel({ name: 'self', self: true }), 'This phone');
  assert.equal(deviceLabel({ name: 'pixel', self: false }), 'pixel');
  assert.equal(groupLabel('selfmod'), 'self-modification');
  assert.equal(groupLabel('odd'), 'odd');
});

test('battery reads termux-battery-status and colours the level', () => {
  const low = batterySummary({ health: 'GOOD', percentage: 12, plugged: 'UNPLUGGED', status: 'DISCHARGING', temperature: 28.3 });
  assert.ok(low);
  assert.equal(low.percent, 12);
  assert.equal(low.status, 'on battery');
  assert.equal(low.plugged, false);
  assert.equal(low.temperature, 28.3);
  assert.equal(low.health, 'good');
  assert.equal(low.tone, 'error');
  assert.equal(batterySummary({ percentage: 25, plugged: 'UNPLUGGED', status: 'DISCHARGING' })?.tone, 'warn');
  const charging = batterySummary({ percentage: 12, plugged: 'PLUGGED_AC', status: 'CHARGING' });
  assert.equal(charging?.tone, 'ok');
  assert.equal(charging?.status, 'charging');
  assert.equal(charging?.plugged, true);
  assert.equal(batterySummary({ status: 'NOT_CHARGING' })?.status, 'not charging');
  assert.equal(batterySummary({ status: 'NOT_CHARGING' })?.tone, 'neutral');
  assert.equal(batterySummary('error: termux-battery-status not found'), null);
  assert.equal(batterySummary([1]), null);
});

test('location reads the quick reading and a gps fix', () => {
  const quick = locationSummary({
    wifi: { ssid: '"Lab-5G"', bssid: 'aa:bb' },
    approx: { city: 'Zagreb', region: 'City of Zagreb', country: 'Croatia', isp: 'Hrvatski Telekom', latitude: 45.8 },
    note: 'approx is city-level',
  });
  assert.deepEqual(quick, { wifi: 'Lab-5G', place: 'Zagreb, City of Zagreb, Croatia', coords: null, isp: 'Hrvatski Telekom' });
  const gps = locationSummary({ latitude: 45.815011, longitude: 15.981919, accuracy: 12.4, provider: 'gps' });
  assert.equal(gps.coords, '45.81501, 15.98192 ±12 m');
  assert.equal(gps.place, null);
  assert.equal(locationSummary({ wifi: { ssid: '<unknown ssid>' }, approx: {} }).wifi, null);
  assert.deepEqual(locationSummary({ text: 'error: timed out' }), { wifi: null, place: null, coords: null, isp: null });
  assert.deepEqual(locationSummary(null), { wifi: null, place: null, coords: null, isp: null });
});

test('notifications become tidy rows, capped', () => {
  const raw = [
    { id: 1, packageName: 'com.whatsapp', title: 'Ana', content: 'See you at 7', when: '2026-10-21 12:00:00' },
    { id: 2, packageName: 'com.android.systemui', title: '', content: '' },
    { id: 3, packageName: 'com.termux', title: 'Termux', content: 'caelza daemon running' },
    'junk',
  ];
  const items = notificationItems(raw);
  assert.equal(items.length, 2);
  assert.deepEqual(items[0], { app: 'com.whatsapp', title: 'Ana', content: 'See you at 7', when: '2026-10-21 12:00:00' });
  assert.equal(items[1]?.when, null);
  assert.equal(notificationItems(raw, 1).length, 1);
  assert.deepEqual(notificationItems({ text: 'error: not found' }), []);
});

test('package filter, pairing input checks and ages', () => {
  const packages = [{ name: 'com.whatsapp' }, { name: 'org.telegram.messenger' }, { name: 'com.termux' }];
  assert.deepEqual(filterPackages(packages, ' TELEGRAM '), [{ name: 'org.telegram.messenger' }]);
  assert.equal(filterPackages(packages, '').length, 3);
  assert.ok(pairHostLooksRight('10.0.0.5:37123'));
  assert.ok(pairHostLooksRight(' pixel.local:40001 '));
  assert.ok(!pairHostLooksRight('10.0.0.5'));
  assert.ok(!pairHostLooksRight('http://10.0.0.5:5555'));
  assert.ok(!pairHostLooksRight('10.0.0.5:5555 extra'));
  assert.ok(pairCodeLooksRight('123456'));
  assert.ok(!pairCodeLooksRight('12345'));
  assert.ok(!pairCodeLooksRight('12a456'));
  const now = Date.parse('2026-10-21T12:00:00Z');
  assert.equal(relativeAge('2026-10-21T11:59:30Z', now), 'just now');
  assert.equal(relativeAge('2026-10-21T11:57:00Z', now), '3 min ago');
  assert.equal(relativeAge('2026-10-21T09:00:00Z', now), '3 h ago');
  assert.equal(relativeAge('2026-10-16T12:00:00Z', now), '5 d ago');
  assert.equal(relativeAge(null, now), null);
  assert.equal(relativeAge('yesterday-ish', now), null);
});
