/* Caelza dashboard service worker.
 *
 * The app shell (index.html, the hashed bundles under /_app/assets, the fonts,
 * the icons) works offline; the gateway API, sockets, auth and pairing are
 * never answered from cache. Bundles are content-hashed, so they are cached
 * first-hit and kept; the shell itself is network-first with the cache as the
 * offline fallback, so a new release is picked up on the next online load.
 * Registered by src/pwa.ts with the dashboard root as scope; the gateway sends
 * Service-Worker-Allowed for this file so that scope is permitted. */

const SHELL = 'caelza-shell-v1';
const ASSETS = 'caelza-assets-v1';
const KEEP = new Set([SHELL, ASSETS]);

/* Paths the gateway owns. Matched after any path prefix, so `/x/api/...` too. */
const LIVE = /\/(api|ws|acp|admin|health|metrics|pair|webhook|hooks|whatsapp|linq|nextcloud-talk)(\/|$|\?)/;

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k.startsWith('caelza-') && !KEEP.has(k)).map((k) => caches.delete(k))),
      )
      .then(() => self.clients.claim()),
  );
});

async function cacheFirst(request) {
  const cache = await caches.open(ASSETS);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
  return response;
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const copy = response.clone();
      caches.open(SHELL).then((cache) => cache.put(request, copy));
    }
    return response;
  } catch (err) {
    const hit = await caches.match(request);
    if (hit) return hit;
    if (request.mode === 'navigate') {
      // Any route of the SPA is served by the shell: fall back to the scope root.
      const shell = await caches.match(new Request(self.registration.scope));
      if (shell) return shell;
    }
    throw err;
  }
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (LIVE.test(url.pathname)) return;
  if (url.pathname.includes('/_app/assets/')) {
    event.respondWith(cacheFirst(request));
    return;
  }
  if (request.mode === 'navigate' || url.pathname.includes('/_app/')) {
    event.respondWith(networkFirst(request));
  }
});
