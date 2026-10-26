// Pure helpers for the Bodies page; tested under node, no React.
import type { BodiesStatus, BodyDevice } from '@/lib/bodies';

export type Tone = 'ok' | 'warn' | 'error' | 'neutral';

/** One line for the page header: what is wrong first, else where the Body is. */
export function serviceLine(
  status: Pick<BodiesStatus, 'enabled' | 'connected' | 'server' | 'reason'>,
): { tone: Tone; text: string } {
  if (!status.enabled) {
    return {
      tone: 'neutral',
      text: status.reason ? `Not configured (${status.reason})` : 'Not configured',
    };
  }
  const name = status.server?.name ?? 'body';
  if (!status.connected) return { tone: 'error', text: `${name} · not answering` };
  const command = [status.server?.command ?? '', ...(status.server?.args ?? [])]
    .filter((part) => part.length > 0)
    .join(' ');
  return {
    tone: 'ok',
    text: [name, status.server?.transport ?? '', command].filter((part) => part.length > 0).join(' · '),
  };
}

/** How a device is reached, in two words. */
export function deviceKindLabel(device: Pick<BodyDevice, 'self' | 'kind' | 'url' | 'host'>): string {
  const kind = device.kind ?? (device.self ? 'self' : device.url ? 'http' : 'adb');
  if (kind === 'self') return 'this phone';
  if (kind === 'http') return 'Body over HTTP';
  return 'over ADB';
}

/** The device's groups, deduplicated and trimmed, for chips. */
export function deviceGroups(device: Pick<BodyDevice, 'groups'>): string[] {
  const out: string[] = [];
  for (const g of device.groups ?? []) {
    const t = g.trim();
    if (t && !out.includes(t)) out.push(t);
  }
  return out;
}

export function deviceLabel(device: Pick<BodyDevice, 'name' | 'self'>): string {
  return device.self ? 'This phone' : device.name;
}

export const GROUP_LABELS: Record<string, string> = {
  device: 'device control',
  sensors: 'sensors',
  shell: 'shell',
  selfmod: 'self-modification',
  web: 'web',
};

export function groupLabel(group: string): string {
  return GROUP_LABELS[group] ?? group;
}

export interface BatterySummary {
  percent: number | null;
  /** charging | on battery | full | not charging | unknown */
  status: string;
  plugged: boolean;
  temperature: number | null;
  health: string | null;
  tone: Tone;
}

const BATTERY_STATUS: Record<string, string> = {
  CHARGING: 'charging',
  DISCHARGING: 'on battery',
  FULL: 'full',
  NOT_CHARGING: 'not charging',
  UNKNOWN: 'unknown',
};

/** `termux-battery-status`: `{health, percentage, plugged, status, temperature, current}`. */
export function batterySummary(data: unknown): BatterySummary | null {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null;
  const d = data as Record<string, unknown>;
  const percent = typeof d.percentage === 'number' ? d.percentage : null;
  const rawStatus = typeof d.status === 'string' ? d.status : 'UNKNOWN';
  const status = BATTERY_STATUS[rawStatus] ?? rawStatus.toLowerCase().replace(/_/g, ' ');
  const plugged = typeof d.plugged === 'string' && d.plugged !== 'UNPLUGGED';
  const temperature = typeof d.temperature === 'number' ? d.temperature : null;
  const health = typeof d.health === 'string' ? d.health.toLowerCase() : null;
  let tone: Tone = 'neutral';
  if (percent !== null) {
    tone = !plugged && percent <= 15 ? 'error' : !plugged && percent <= 30 ? 'warn' : 'ok';
  }
  return { percent, status, plugged, temperature, health, tone };
}

export interface LocationSummary {
  wifi: string | null;
  /** City, region, country from the public IP (quick mode). */
  place: string | null;
  /** `lat, lon ±acc m` when the reading has coordinates (gps / network mode). */
  coords: string | null;
  isp: string | null;
}

/** `sensors_location` quick: `{wifi: {ssid, ...}, approx: {city, region, country, isp, ...}, note}`;
 *  gps / network: termux-location's `{latitude, longitude, accuracy, ...}`. */
export function locationSummary(data: unknown): LocationSummary {
  const out: LocationSummary = { wifi: null, place: null, coords: null, isp: null };
  if (!data || typeof data !== 'object' || Array.isArray(data)) return out;
  const d = data as Record<string, unknown>;
  const wifi = d.wifi;
  if (wifi && typeof wifi === 'object') {
    const ssid = (wifi as Record<string, unknown>).ssid;
    if (typeof ssid === 'string') {
      const clean = ssid.replace(/^"|"$/g, '');
      if (clean && clean !== '<unknown ssid>') out.wifi = clean;
    }
  }
  const approx = d.approx;
  if (approx && typeof approx === 'object') {
    const a = approx as Record<string, unknown>;
    const parts = ['city', 'region', 'country']
      .map((key) => a[key])
      .filter((value): value is string => typeof value === 'string' && value.length > 0);
    if (parts.length > 0) out.place = parts.join(', ');
    if (typeof a.isp === 'string' && a.isp) out.isp = a.isp;
  }
  if (typeof d.latitude === 'number' && typeof d.longitude === 'number') {
    const accuracy = typeof d.accuracy === 'number' ? ` ±${Math.round(d.accuracy)} m` : '';
    out.coords = `${d.latitude.toFixed(5)}, ${d.longitude.toFixed(5)}${accuracy}`;
  }
  return out;
}

export interface NotificationItem {
  app: string;
  title: string;
  content: string;
  when: string | null;
}

/** `termux-notification-list`: `[{id, tag, key, group, packageName, title, content, when}]`. */
export function notificationItems(data: unknown, limit = 20): NotificationItem[] {
  if (!Array.isArray(data)) return [];
  const items: NotificationItem[] = [];
  for (const raw of data) {
    if (!raw || typeof raw !== 'object') continue;
    const n = raw as Record<string, unknown>;
    const title = typeof n.title === 'string' ? n.title : '';
    const content = typeof n.content === 'string' ? n.content : '';
    if (!title && !content) continue;
    items.push({
      app: typeof n.packageName === 'string' ? n.packageName : '',
      title,
      content,
      when: typeof n.when === 'string' ? n.when : null,
    });
    if (items.length >= limit) break;
  }
  return items;
}

export function filterPackages<T extends { name: string }>(packages: T[], query: string): T[] {
  const q = query.trim().toLowerCase();
  if (!q) return packages;
  return packages.filter((p) => p.name.toLowerCase().includes(q));
}

/** `host:port`, what Android's Wireless debugging screen shows. */
export function pairHostLooksRight(host: string): boolean {
  return /^[^\s:/]+:\d{1,5}$/.test(host.trim());
}

/** The six-digit Wi-Fi pairing code. */
export function pairCodeLooksRight(code: string): boolean {
  return /^\d{6}$/.test(code.trim());
}

/** `3 min ago`, `2 h ago`, `5 d ago`; `just now` under a minute; null when unknown. */
export function relativeAge(iso: string | null | undefined, now = Date.now()): string | null {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  if (seconds < 60) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}
