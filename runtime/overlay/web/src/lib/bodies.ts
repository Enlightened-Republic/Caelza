// The Body (caelza-body, the device layer served over MCP) as the dashboard
// sees it: `/api/bodies/*`, proxied by the gateway, which owns the connection
// to the Body's MCP server and makes the tool calls itself.
import { apiFetch } from './api';

export interface BodyServerInfo {
  name: string;
  transport: string;
  command: string;
  args: string[];
  url?: string | null;
  tool_timeout_secs?: number | null;
}

export interface BodiesStatus {
  enabled: boolean;
  /** Why there is no Body (when `enabled` is false). */
  reason?: string;
  hint?: string;
  mcp_enabled?: boolean;
  /** The `[[mcp.servers]]` entries that are Bodies, by name. */
  servers: string[];
  server?: BodyServerInfo;
  connected?: boolean;
  error?: string | null;
  /** Tool names the Body advertises. */
  tools?: string[];
  /** Tools per group: device, sensors, shell, selfmod, web. */
  groups?: Record<string, number>;
  /** Tools per safety class: read-only, destructive, neutral. */
  classes?: Record<string, number>;
}

export interface BodyDevice {
  name: string;
  /** True for the phone the Body runs on. */
  self: boolean;
  host: string | null;
  last_seen: string | null;
  reachable: boolean;
}

export type BodySensorKind = 'battery' | 'location' | 'notifications';

export interface BodySensorReading {
  server: string;
  kind: BodySensorKind;
  /** The tool's JSON when it answered with JSON, else `{ text }`. */
  data: unknown;
  text: string;
}

export interface BodyPackage {
  name: string;
  path: string | null;
}

export interface BodyPackages {
  server: string;
  device: string;
  flags: string;
  count: number;
  packages: BodyPackage[];
}

export type BodyCaptureKind = 'screen' | 'camera';

export interface BodyCapture {
  server: string;
  kind: BodyCaptureKind;
  device: string;
  facing: string | null;
  mime: string;
  /** base64 */
  data: string;
  text: string;
}

export interface BodyPairResult {
  status: 'ok' | 'failed';
  server: string;
  name: string;
  host?: string;
  text: string;
}

function qs(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : '';
}

export function getBodiesStatus(server?: string): Promise<BodiesStatus> {
  return apiFetch<BodiesStatus>(`/api/bodies/status${qs({ server })}`);
}

export function getBodyDevices(
  server?: string,
): Promise<{ server: string; devices: BodyDevice[]; text: string }> {
  return apiFetch(`/api/bodies/devices${qs({ server })}`);
}

export function getBodySensor(kind: BodySensorKind, server?: string): Promise<BodySensorReading> {
  return apiFetch<BodySensorReading>(`/api/bodies/sensors${qs({ kind, server })}`);
}

/** `flags` are `pm list packages` switches (`-3`, `-s`, `-f`) or `all` for every package. */
export function getBodyPackages(device = 'self', flags = '-3', server?: string): Promise<BodyPackages> {
  return apiFetch<BodyPackages>(`/api/bodies/packages${qs({ device, flags, server })}`);
}

export function captureBody(
  kind: BodyCaptureKind,
  opts: { device?: string; facing?: 'back' | 'front' } = {},
  server?: string,
): Promise<BodyCapture> {
  return apiFetch<BodyCapture>(`/api/bodies/capture${qs({ kind, device: opts.device, facing: opts.facing, server })}`);
}

export function captureDataUrl(capture: Pick<BodyCapture, 'mime' | 'data'>): string {
  return `data:${capture.mime};base64,${capture.data}`;
}

export function pairBodyDevice(
  request: { name: string; host: string; code: string; notes?: string },
  server?: string,
): Promise<BodyPairResult> {
  return apiFetch<BodyPairResult>('/api/bodies/pair', {
    method: 'POST',
    body: JSON.stringify({ ...request, server }),
  });
}

export function unpairBodyDevice(
  name: string,
  server?: string,
): Promise<{ status: string; server: string; name: string; text: string }> {
  return apiFetch('/api/bodies/pair', {
    method: 'DELETE',
    body: JSON.stringify({ name, server }),
  });
}
