import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  ATTRIBUTION,
  Attribution,
  type AttributionProps,
  EYEBROW,
  Lockup,
  type LockupProps,
  TAGLINE,
  Wordmark,
  type WordmarkProps,
} from './CaelzaLockup.tsx';

test('the lockup reads ENLIGHTENED REPUBLIC™ PRESENTS over the Orbitron wordmark', () => {
  const html = renderToStaticMarkup(createElement<LockupProps>(Lockup, { markSrc: '/_app/logo.png' }));
  assert.equal(EYEBROW, 'ENLIGHTENED REPUBLIC™ PRESENTS');
  assert.ok(html.includes(`class="cz-eyebrow">${EYEBROW}<`), html);
  assert.ok(html.includes('<h1 class="cz-wordmark"'), 'the wordmark is the page heading');
  assert.ok(html.includes('>CAELZA</h1>'), html);
  assert.ok(html.includes(TAGLINE));
  // The mark is decorative beside the wordmark: hidden from assistive tech.
  assert.ok(html.includes('aria-hidden="true"') && html.includes('src="/_app/logo.png"'), html);
});

test('the lockup renders without a mark or tagline when asked', () => {
  const html = renderToStaticMarkup(createElement<LockupProps>(Lockup, { tagline: false }));
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes(TAGLINE));
  assert.ok(html.includes('>CAELZA</h1>'));
});

test('the wordmark can render inline without the heading role', () => {
  const html = renderToStaticMarkup(createElement<WordmarkProps>(Wordmark, { size: 'sm' }));
  assert.ok(html.startsWith('<span class="cz-wordmark"'), html);
  assert.ok(html.includes('font-size:14px'), html);
});

test('the attribution carries the trademark in both forms', () => {
  assert.equal(ATTRIBUTION, 'ENLIGHTENED REPUBLIC™ · EST. 2026');
  assert.ok(renderToStaticMarkup(createElement<AttributionProps>(Attribution, {})).includes(ATTRIBUTION));
  const compact = renderToStaticMarkup(createElement<AttributionProps>(Attribution, { compact: true }));
  assert.ok(compact.includes('>ER™<'), compact);
  assert.ok(compact.includes(`aria-label="${ATTRIBUTION}"`), 'the short form keeps the full name for readers');
});
