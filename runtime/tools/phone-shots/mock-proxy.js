// A thin proxy in front of a running Caelza gateway: answers the Mind and
// Body routes (which the M3-era binary does not have) with canned JSON so the
// Home, Memory and Bodies pages render their full state, and forwards every
// other request (HTTP and WebSocket upgrades) to the gateway untouched.
//
//   node mock-proxy.js <listen-port> <gateway-port>
const http = require('node:http');
const net = require('node:net');

const [listenPort, gatewayPort] = [Number(process.argv[2] || 42700), Number(process.argv[3] || 42617)];
const now = Date.now();
const ago = (ms) => new Date(now - ms).toISOString();

const brainStatus = {
  brain: 'private',
  nodes: { total: 184, active: 171, retracted: 6, superseded: 5, archived: 2 },
  episodes: 412,
  beliefs: { lowConfidence: 7, contradicted: 1, flaggedForReview: 2 },
  decisions: { total: 9, pending: 1, resolved: 8 },
  goals: { active: 2, tracked: 2, paused: 0, done: 3, drifting: [{ id: 'g1', title: 'Keep the phone under 60% storage', reason: 'no progress in 9 days' }] },
  reviews: { pending: 2, byKind: { quarantine: 1, identity_change: 1 }, flagged: 1 },
  quarantine: { mode: 'enforce', held: 1, logged: 0, accepted: 4, rejected: 1 },
  focus: 'the new-phone setup for Grandma',
  lastSleep: { at: now - 3 * 3600e3, ago: '3 hours ago', summary: { nodesBefore: 188, nodesAfter: 184, edgesBefore: 402, edgesAfter: 399, pruned: 4, newContradictions: 1, flaggedForReview: 2 } },
  attention: ['1 belief disputed: "Ana prefers calls to texts" vs a newer note', '2 memory changes await your review', 'goal "Keep the phone under 60% storage" is drifting'],
};

const mind = {
  '/api/mind/status': {
    enabled: true, healthy: true, url: 'http://127.0.0.1:18790', scope: 'all', agent: 'main', default_agent: 'main', agents: ['cael', 'main'],
    has_token: true, token_file: '/home/user/.xanima/tokens/main.token',
    stats: { agentId: 'main', brains: [
      { brain: 'private', nodes: 184, nodesByType: { semantic: 96, episodic: 41, pattern: 14, skill: 9, goal: 5, identity: 7, decision: 9, commitment: 3 }, activeEdges: 399, episodes: 412, embedded: 180, writers: { main: 184 }, lastConsolidation: '3 hours ago' },
      { brain: 'shared', nodes: 23, nodesByType: { semantic: 20, pattern: 3 }, activeEdges: 31, episodes: 0, embedded: 23, writers: { main: 19, cael: 4 }, lastConsolidation: '1 day ago' },
    ] },
    status: { agentId: 'main', brains: [brainStatus] },
    errors: [],
  },
  '/api/mind/digest': {
    agent: 'main', attention: brainStatus.attention, focus: brainStatus.focus, last_sleep: brainStatus.lastSleep,
    commitments: [
      { node_id: 'c1', title: 'Send Ana the photos from Sunday', owner: 'main', counterparty: 'Ana', status: 'open', due_at: now - 2 * 3600e3, note: null, created_at: now - 2 * 86400e3, updated_at: now - 3600e3, done_at: null, last_nudged_at: null, blockers: [], overdue: true, blocked: false },
      { node_id: 'c2', title: 'Re-check the storage after the cleanup', owner: 'main', counterparty: 'self', status: 'open', due_at: now + 2 * 86400e3, note: null, created_at: now - 86400e3, updated_at: now - 86400e3, done_at: null, last_nudged_at: null, blockers: [], overdue: false, blocked: false },
    ],
    open_items: [
      { node_id: 'o1', kind: 'question', text: 'Does the popup come from the weather app or the launcher?', status: 'open', load_bearing: 1, contradicted_at: null, confidence: 'low', created_at: now - 86400e3, updated_at: now - 3600e3, links: [] },
      { node_id: 'o2', kind: 'hypothesis', text: 'Battery drain correlates with the background sync of the gallery app', status: 'supported', load_bearing: 0, contradicted_at: null, confidence: 'medium', created_at: now - 4 * 86400e3, updated_at: now - 86400e3, links: [] },
    ],
    errors: [],
  },
  '/api/mind/review': {
    agent: 'main', status: 'pending', raw: '',
    items: [
      { id: 'rev_1a2b', status: 'pending', kind: 'quarantine', section: 'identity', label: 'New name for me', flags: ['untrusted', 'tool-output'], reason: 'identity write from tool output', raw: '' },
      { id: 'rev_3c4d', status: 'pending', kind: 'identity_change', section: 'values', label: 'I value speed over care', flags: [], reason: 'proposed by main', raw: '' },
    ],
  },
  '/api/mind/recall': {
    agent: 'main', query: 'phone', results: [
      { brain: 'private', id: 'n1', type: 'semantic', label: 'Grandma\'s phone is a Samsung A14', content: 'The phone that keeps showing the popup is Grandma\'s Samsung Galaxy A14, Android 14, 64 GB with 58 GB used.', score: 0.82, confidence: 'high', writer: 'main', ago: '2 days ago', created_at: now - 2 * 86400e3 },
      { brain: 'shared', id: 'n2', type: 'pattern', label: 'Popups after sideloads', content: 'Three times now a full-screen popup appeared within a day of a sideloaded "cleaner" app.', score: 0.61, confidence: 'medium', writer: 'cael', ago: '9 days ago', created_at: now - 9 * 86400e3, contradicted_at: null },
    ],
  },
};

const bodies = {
  '/api/bodies/status': {
    enabled: true, server: { name: 'body', transport: 'stdio', command: 'caelza-body', args: ['serve'], url: null, tool_timeout_secs: 120 }, servers: ['body'],
    connected: true, error: null,
    tools: ['device_list', 'device_shell', 'device_screencap', 'device_ui_dump', 'device_packages', 'device_logcat', 'device_settings', 'device_pair', 'device_unpair', 'device_input', 'device_settings_put', 'device_appops', 'device_uninstall', 'device_disable',
      'sensors_camera_photo', 'sensors_mic_record', 'sensors_location', 'sensors_notifications', 'sensors_tts_speak', 'sensors_clipboard_get', 'sensors_clipboard_set', 'sensors_battery', 'sensors_torch',
      'shell_run', 'self_read_file', 'self_list_tree', 'self_write_file', 'self_commit', 'self_run_tests', 'self_request_restart', 'web_search', 'web_read', 'web_map', 'web_crawl', 'web_crawl_result'],
    groups: { device: 14, selfmod: 6, sensors: 9, shell: 1, web: 5 }, classes: { destructive: 11, neutral: 8, 'read-only': 16 },
  },
  '/api/bodies/devices': {
    server: 'body', text: '', devices: [
      { name: 'self', self: true, host: null, last_seen: null, reachable: true },
      { name: 'grandma-a14', self: false, host: '10.0.0.23:5555', last_seen: ago(40 * 60e3), reachable: true },
      { name: 'old-pixel', self: false, host: '10.0.0.9:5555', last_seen: ago(3 * 86400e3), reachable: false },
    ],
  },
  '/api/bodies/sensors': (url) => {
    const kind = url.searchParams.get('kind');
    if (kind === 'battery') return { server: 'body', kind, data: { health: 'GOOD', percentage: 67, plugged: 'UNPLUGGED', status: 'DISCHARGING', temperature: 29.4, current: -312 }, text: '' };
    if (kind === 'location') return { server: 'body', kind, data: { wifi: { ssid: '"Lab-5G"' }, approx: { city: 'Zagreb', region: 'City of Zagreb', country: 'Croatia', isp: 'Hrvatski Telekom' } }, text: '' };
    return { server: 'body', kind, data: [{ id: 1, packageName: 'com.whatsapp', title: 'Ana', content: 'See you at 7?', when: '2026-10-21 12:00:00' }, { id: 2, packageName: 'com.termux', title: 'Termux', content: 'caelza daemon running', when: '2026-10-21 08:12:00' }], text: '' };
  },
  '/api/bodies/packages': { server: 'body', device: 'self', flags: '-3', count: 3, packages: [{ name: 'com.termux', path: null }, { name: 'com.whatsapp', path: null }, { name: 'org.telegram.messenger', path: null }] },
};

function canned(url) {
  const table = url.pathname.startsWith('/api/mind/') ? mind : url.pathname.startsWith('/api/bodies/') ? bodies : null;
  if (!table) return null;
  const hit = table[url.pathname];
  if (hit === undefined) return { status: 404, body: { error: `no mock for ${url.pathname}` } };
  return { status: 200, body: typeof hit === 'function' ? hit(url) : hit };
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${listenPort}`);
  const mock = canned(url);
  if (mock) {
    res.writeHead(mock.status, { 'content-type': 'application/json' });
    res.end(JSON.stringify(mock.body));
    return;
  }
  const upstream = http.request({ host: '127.0.0.1', port: gatewayPort, method: req.method, path: req.url, headers: { ...req.headers, host: `127.0.0.1:${gatewayPort}` } }, (up) => {
    res.writeHead(up.statusCode, up.headers);
    up.pipe(res);
  });
  upstream.on('error', (e) => { res.writeHead(502); res.end(String(e)); });
  req.pipe(upstream);
});
server.on('upgrade', (req, socket, head) => {
  const target = net.connect(gatewayPort, '127.0.0.1', () => {
    const lines = [`${req.method} ${req.url} HTTP/1.1`];
    for (const [k, v] of Object.entries(req.headers)) lines.push(`${k}: ${k === 'host' ? `127.0.0.1:${gatewayPort}` : v}`);
    target.write(lines.join('\r\n') + '\r\n\r\n');
    if (head.length) target.write(head);
    socket.pipe(target).pipe(socket);
  });
  target.on('error', () => socket.destroy());
});
server.listen(listenPort, '127.0.0.1', () => console.log(`mock proxy on ${listenPort} → gateway ${gatewayPort}`));
