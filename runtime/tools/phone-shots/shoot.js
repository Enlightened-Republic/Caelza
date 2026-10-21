// Screenshot every dashboard route at phone width and report what overflows.
//
//   node shoot.js <base-url> <out-dir> [width=390] [height=844]
//
// For each route: load, wait for the network to settle, take a full-page
// screenshot, then measure: does the document scroll sideways, and which
// elements stick out past the right edge (tag, class, how far). Writes
// <out-dir>/report.json and prints one line per route.
const { chromium } = require('playwright-core');
const fs = require('node:fs');
const path = require('node:path');

const [base, outDir, widthArg, heightArg, dprArg, onlyArg] = [process.argv[2] || 'http://127.0.0.1:42700', process.argv[3] || 'shots', process.argv[4], process.argv[5], process.argv[6], process.argv[7]];
const width = Number(widthArg || 390);
const height = Number(heightArg || 844);
const dpr = Number(dprArg || 2);
// A comma-separated subset of route names, for a small documentation set.
const only = onlyArg ? new Set(onlyArg.split(',')) : null;

const ROUTES = [
  ['home', '/'],
  ['bodies', '/bodies'],
  ['memory', '/memory'],
  ['procedures', '/procedures'],
  ['agents', '/agents'],
  ['agent-chat', '/agent/main'],
  ['dashboard', '/dashboard'],
  ['dashboard-sessions', '/dashboard?tab=sessions'],
  ['dashboard-channels', '/dashboard?tab=channels'],
  ['dashboard-memories', '/dashboard?tab=memories'],
  ['dashboard-health', '/dashboard?tab=health'],
  ['dashboard-cost', '/dashboard?tab=cost'],
  ['config', '/config'],
  ['config-agents', '/config/agents'],
  ['tools', '/tools'],
  ['skills', '/skills'],
  ['sops', '/sops'],
  ['sops-new', '/sops/new'],
  ['runs', '/runs'],
  ['integrations', '/integrations'],
  ['plugins', '/plugins'],
  ['cron', '/cron'],
  ['logs', '/logs'],
  ['pairing', '/pairing'],
  ['doctor', '/doctor'],
  ['canvas', '/canvas'],
  ['acp-console', '/acp-console'],
];

const MEASURE = `(() => {
  const vw = document.documentElement.clientWidth;
  const sw = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
  const offenders = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const over = Math.round(r.right - vw);
    if (over > 2 && getComputedStyle(el).position !== 'fixed') {
      offenders.push({ tag: el.tagName.toLowerCase(), cls: (el.getAttribute('class') || '').slice(0, 90), over, width: Math.round(r.width) });
    }
  }
  offenders.sort((a, b) => b.over - a.over);
  const touch = [];
  for (const el of document.querySelectorAll('button, a[href], input, select, textarea, [role=button], [role=tab]')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.height < 32 || r.width < 32) touch.push({ tag: el.tagName.toLowerCase(), text: (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 40), w: Math.round(r.width), h: Math.round(r.height) });
  }
  return { vw, sw, sideways: sw > vw + 1, offenders: offenders.slice(0, 12), offenderCount: offenders.length, smallTargets: touch.slice(0, 12), smallTargetCount: touch.length, title: document.title, h1: (document.querySelector('h1') || {}).textContent || '' };
})()`;

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  // A Chromium that playwright-core did not download: point PLAYWRIGHT_CHROMIUM
  // at it (the cloud image keeps one under /opt/pw-browsers).
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
  const browser = await chromium.launch({ executablePath });
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: dpr, isMobile: true, hasTouch: true, colorScheme: 'dark' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  const report = [];
  for (const [name, route] of ROUTES) {
    if (only && !only.has(name)) continue;
    errors.length = 0;
    try {
      // 'load' rather than 'networkidle': the sessions and channels tabs keep
      // an SSE stream open, so the network never goes idle there.
      await page.goto(base + route, { waitUntil: 'load', timeout: 30000 });
      await page.waitForTimeout(2500);
    } catch (e) {
      report.push({ name, route, error: String(e) });
      console.log(`${name.padEnd(20)} LOAD FAILED ${String(e).slice(0, 80)}`);
      continue;
    }
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(outDir, `${name}.png`), fullPage: true });
    const m = await page.evaluate(MEASURE);
    report.push({ name, route, ...m, consoleErrors: errors.slice(0, 5) });
    const flag = m.sideways ? `SIDEWAYS ${m.sw}>${m.vw}` : 'ok';
    console.log(`${name.padEnd(20)} ${flag.padEnd(18)} offenders=${m.offenderCount} smallTargets=${m.smallTargetCount}${errors.length ? ` consoleErrors=${errors.length}` : ''}`);
  }
  // The mobile drawer: open it from Home and shoot the viewport.
  if (!only || only.has('drawer')) try {
    await page.goto(base + '/', { waitUntil: 'load', timeout: 30000 });
    await page.waitForTimeout(1500);
    const menu = page.locator('header button.md\\:hidden, button.md\\:hidden[aria-label]').first();
    await menu.click({ timeout: 5000 });
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(outDir, 'drawer.png'), fullPage: false });
    const m = await page.evaluate(MEASURE);
    report.push({ name: 'drawer', route: '/ (menu open)', ...m });
    console.log(`${'drawer'.padEnd(20)} ${(m.sideways ? 'SIDEWAYS' : 'ok').padEnd(18)} offenders=${m.offenderCount} smallTargets=${m.smallTargetCount}`);
  } catch (e) {
    console.log(`${'drawer'.padEnd(20)} SKIPPED ${String(e).slice(0, 80)}`);
  }
  fs.writeFileSync(path.join(outDir, 'report.json'), JSON.stringify(report, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
