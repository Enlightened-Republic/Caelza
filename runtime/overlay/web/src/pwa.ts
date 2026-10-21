// Installable dashboard: register the service worker that keeps the app shell
// available offline (public/sw.js). Production builds only, and only where the
// browser allows service workers at all (a secure context: localhost, or
// HTTPS, which is how the dashboard should be reached over a tailnet). The
// manifest (public/manifest.webmanifest) is what makes the install prompt
// appear; this is what makes the installed app open without a network.
import { basePath } from './lib/basePath';

export function registerServiceWorker(): void {
  if (!import.meta.env.PROD) return;
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return;
  if (!window.isSecureContext || !('serviceWorker' in navigator)) return;
  const register = () => {
    navigator.serviceWorker
      .register(`${basePath}/_app/sw.js`, { scope: `${basePath}/` })
      .catch((err: unknown) => {
        console.warn('[Caelza] service worker not registered:', err);
      });
  };
  if (document.readyState === 'complete') register();
  else window.addEventListener('load', register, { once: true });
}
