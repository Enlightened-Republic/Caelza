// The Bodies page: the phone the agent lives in and the phones paired to it,
// as the Body reports them: reachability, battery and whereabouts, the screen
// and the camera, installed packages, and pairing a new phone. Phone-first:
// one column at 390 px, cards stack. Everything goes through the gateway
// (`/api/bodies/*`), which owns the connection to the Body's MCP server.
import { useCallback, useEffect, useState } from 'react';
import { BatteryMedium, Bell, Camera, Download, Link2, MapPin, Monitor, Package, RefreshCw, Smartphone, Unlink } from 'lucide-react';

import { Badge, Button, Card, ConfirmDialog, PageHeader, Select, StatCard } from '@/components/ui';
import {
  captureBody,
  captureDataUrl,
  getBodiesStatus,
  getBodyDevices,
  getBodyPackages,
  getBodySensor,
  pairBodyDevice,
  unpairBodyDevice,
  type BodiesStatus,
  type BodyCapture,
  type BodyDevice,
  type BodyPackage,
  type BodySensorKind,
} from '@/lib/bodies';
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
} from './bodies.logic';

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

function ErrorBox({ children }: { children: React.ReactNode }) {
  return (
    <div role="alert" className="mt-3 rounded-[var(--radius-md)] border border-status-error/25 bg-status-error/10 p-3 text-xs text-status-error">
      {children}
    </div>
  );
}

export default function Bodies() {
  const [server, setServer] = useState<string | undefined>(undefined);
  const [status, setStatus] = useState<BodiesStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [devices, setDevices] = useState<BodyDevice[] | null>(null);
  const [devicesError, setDevicesError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setStatusError(null);
    getBodiesStatus(server)
      .then((s) => {
        if (!cancelled) setStatus(s);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setStatusError(errorText(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [server, reload]);

  const refresh = useCallback(() => setReload((n) => n + 1), []);

  const serves = useCallback((tool: string) => (status?.tools ?? []).includes(tool), [status]);

  const loadDevices = useCallback(() => {
    setDevicesError(null);
    getBodyDevices(server)
      .then((r) => setDevices(r.devices))
      .catch((reason: unknown) => setDevicesError(errorText(reason)));
  }, [server]);

  useEffect(() => {
    if (status?.enabled && status.connected && (status.tools ?? []).includes('device_list')) loadDevices();
  }, [status, loadDevices]);

  if (statusError) {
    return (
      <div className="p-6">
        <div
          role="alert"
          className="space-y-3 rounded-[var(--radius-md)] border border-status-error/25 bg-status-error/10 p-4 text-sm text-status-error"
        >
          <p>The Body could not be read: {statusError}</p>
          <Button variant="ghost" size="sm" onClick={refresh}>
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (!status) {
    return (
      <div role="status" aria-live="polite" className="flex h-64 items-center justify-center gap-3 text-sm text-pc-text-muted">
        <span
          aria-hidden="true"
          className="h-8 w-8 animate-spin rounded-full border-2 border-pc-border"
          style={{ borderTopColor: 'var(--pc-accent)' }}
        />
        <span>Reaching the Body…</span>
      </div>
    );
  }

  const line = serviceLine(status);
  const serverOptions = (status.servers ?? []).map((s) => ({ value: s, label: s }));
  const currentServer = status.server?.name ?? server ?? 'body';
  const deviceList = devices ?? [{ name: 'self', self: true, host: null, last_seen: null, reachable: true }];

  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Bodies"
        description="The phone the agent lives in, the phones paired to it, and what their senses say."
        actions={
          <div className="flex items-center gap-2">
            <Badge tone={line.tone}>{line.text}</Badge>
            <Button variant="ghost" size="sm" onClick={refresh} aria-label="Refresh">
              <RefreshCw size={14} aria-hidden="true" />
            </Button>
          </div>
        }
      />

      {!status.enabled ? (
        <NotConfigured status={status} />
      ) : (
        <>
          {serverOptions.length > 1 && (
            <div className="flex flex-wrap items-center gap-3">
              <span className="cz-eyebrow">Body</span>
              <Select value={currentServer} onChange={(v) => setServer(v)} options={serverOptions} className="min-w-40" />
            </div>
          )}

          {!status.connected ? (
            <Card>
              <div className="flex items-start gap-3">
                <Smartphone className="mt-0.5 h-5 w-5 shrink-0 text-status-error" aria-hidden="true" />
                <div className="space-y-2 text-sm">
                  <p className="text-pc-text">
                    The Body <code className="font-mono">{currentServer}</code> is configured but did not answer.
                  </p>
                  {status.error && <p className="font-mono text-xs text-status-error">{status.error}</p>}
                  <p className="text-pc-text-muted">
                    The daemon starts it as <code className="font-mono">{status.server?.command} {(status.server?.args ?? []).join(' ')}</code>.
                    On the phone, <code className="font-mono">caelza-body probe</code> says whether the Body itself is sane.
                  </p>
                </div>
              </div>
            </Card>
          ) : (
            <>
              {serves('device_list') && (
                <DevicesCard
                  devices={devices}
                  error={devicesError}
                  onChanged={loadDevices}
                  server={server}
                  canPair={serves('device_pair')}
                  canUnpair={serves('device_unpair')}
                />
              )}
              {(serves('sensors_battery') || serves('sensors_location') || serves('sensors_notifications')) && (
                <SensesCard server={server} serves={serves} />
              )}
              {(serves('device_screencap') || serves('sensors_camera_photo')) && (
                <CaptureCard devices={deviceList} server={server} serves={serves} />
              )}
              {serves('device_packages') && <PackagesCard devices={deviceList} server={server} />}
              <ToolsCard status={status} />
            </>
          )}
        </>
      )}
    </div>
  );
}

function NotConfigured({ status }: { status: BodiesStatus }) {
  return (
    <Card>
      <div className="flex items-start gap-3">
        <Smartphone className="mt-0.5 h-5 w-5 shrink-0 text-pc-accent" aria-hidden="true" />
        <div className="space-y-2 text-sm">
          <p className="text-pc-text">
            No Body is wired into the Runtime{status.reason ? <> ({status.reason})</> : null}. The agent has no phone to sense or act
            through yet.
          </p>
          <p className="text-pc-text-muted">{status.hint}</p>
          {status.servers.length > 0 && (
            <p className="text-pc-text-muted">
              Bodies this config knows: {status.servers.join(', ')}. Pick one above once the entry named <code className="font-mono">body</code> exists.
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}

function DevicesCard({
  devices,
  error,
  onChanged,
  server,
  canPair,
  canUnpair,
}: {
  devices: BodyDevice[] | null;
  error: string | null;
  onChanged: () => void;
  server?: string;
  canPair: boolean;
  canUnpair: boolean;
}) {
  const [showPair, setShowPair] = useState(false);
  const [unpairing, setUnpairing] = useState<BodyDevice | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const unpair = useCallback(async () => {
    if (!unpairing) return;
    const target = unpairing;
    setUnpairing(null);
    setActionError(null);
    try {
      const r = await unpairBodyDevice(target.name, server);
      setNotice(r.text);
      onChanged();
    } catch (reason) {
      setActionError(errorText(reason));
    }
  }, [onChanged, server, unpairing]);

  const paired = devices?.filter((d) => !d.self) ?? [];

  return (
    <Card>
      <div className="mb-1 flex items-center justify-between">
        <div className="cz-eyebrow">Devices</div>
        {devices && <Badge tone="neutral">{paired.length} paired</Badge>}
      </div>
      <p className="text-xs text-pc-text-faint">
        This phone is the Body. Paired phones are reached over ADB wireless debugging; the Body remembers them in its device registry.
      </p>

      {error && <ErrorBox>{error}</ErrorBox>}
      {actionError && <ErrorBox>{actionError}</ErrorBox>}
      {notice && <div className="mt-3 text-xs text-status-success">{notice}</div>}

      {!devices && !error && <p className="mt-3 text-sm text-pc-text-muted">Asking the Body…</p>}

      {devices && (
        <ul className="mt-3 space-y-2">
          {devices.map((d) => (
            <li key={d.name} className="flex flex-wrap items-center gap-2 rounded-[var(--radius-md)] border border-pc-border bg-pc-elevated p-3 text-sm">
              <Smartphone size={16} className="shrink-0 text-pc-accent" aria-hidden="true" />
              <span className="font-medium text-pc-text">{deviceLabel(d)}</span>
              {d.host && <span className="font-mono text-xs text-pc-text-faint">{d.host}</span>}
              <Badge tone={d.reachable ? 'ok' : 'error'}>{d.reachable ? 'reachable' : 'unreachable'}</Badge>
              {relativeAge(d.last_seen) && <span className="text-xs text-pc-text-faint">seen {relativeAge(d.last_seen)}</span>}
              {!d.self && canUnpair && (
                <button
                  type="button"
                  className="ml-auto inline-flex items-center gap-1 text-xs text-status-error hover:underline"
                  onClick={() => setUnpairing(d)}
                >
                  <Unlink size={12} aria-hidden="true" /> Unpair
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {canPair && (
        <div className="mt-4">
          {showPair ? (
            <PairForm
              server={server}
              onDone={(text) => {
                setNotice(text);
                setShowPair(false);
                onChanged();
              }}
              onCancel={() => setShowPair(false)}
            />
          ) : (
            <Button variant="ghost" size="sm" onClick={() => setShowPair(true)}>
              <Link2 size={14} aria-hidden="true" />
              <span className="ml-1.5">Pair a phone</span>
            </Button>
          )}
        </div>
      )}

      <ConfirmDialog
        open={unpairing !== null}
        title="Forget this device?"
        message={
          unpairing ? (
            <span>
              <strong>{unpairing.name}</strong> leaves the Body's registry. The phone itself keeps its wireless-debugging pairing; pair it
              again to bring it back.
            </span>
          ) : undefined
        }
        confirmLabel="Unpair"
        danger
        onConfirm={() => void unpair()}
        onClose={() => setUnpairing(null)}
      />
    </Card>
  );
}

function PairForm({ server, onDone, onCancel }: { server?: string; onDone: (text: string) => void; onCancel: () => void }) {
  const [name, setName] = useState('');
  const [host, setHost] = useState('');
  const [code, setCode] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = name.trim().length > 0 && pairHostLooksRight(host) && pairCodeLooksRight(code);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await pairBodyDevice({ name: name.trim(), host: host.trim(), code: code.trim(), notes: notes.trim() || undefined }, server);
      if (r.status === 'ok') onDone(r.text);
      else setError(r.text);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="space-y-3 rounded-[var(--radius-md)] border border-pc-border bg-pc-elevated p-3"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <p className="text-xs text-pc-text-faint">
        On the other phone: Settings → Developer options → Wireless debugging → <em>Pair device with pairing code</em>. Enter the IP address
        and port it shows, and the six-digit code, while that screen stays open.
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        <input className="input-electric" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name, e.g. pixel" aria-label="Device name" />
        <input className="input-electric" value={host} onChange={(e) => setHost(e.target.value)} placeholder="IP:port, e.g. 10.0.0.5:37123" aria-label="Host and port" />
        <input className="input-electric" value={code} onChange={(e) => setCode(e.target.value)} placeholder="Pairing code" inputMode="numeric" aria-label="Pairing code" />
        <input className="input-electric" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes (optional)" aria-label="Notes" />
      </div>
      {error && <ErrorBox><pre className="whitespace-pre-wrap font-mono">{error}</pre></ErrorBox>}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={busy || !ready}>
          {busy ? 'Pairing…' : 'Pair'}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

interface Reading {
  data?: unknown;
  error?: string;
  busy: boolean;
}

function SensesCard({ server, serves }: { server?: string; serves: (tool: string) => boolean }) {
  const [readings, setReadings] = useState<Partial<Record<BodySensorKind, Reading>>>({});

  const read = useCallback(
    (kind: BodySensorKind) => {
      setReadings((prev) => ({ ...prev, [kind]: { ...prev[kind], busy: true, error: undefined } }));
      getBodySensor(kind, server)
        .then((r) => setReadings((prev) => ({ ...prev, [kind]: { data: r.data, busy: false } })))
        .catch((reason: unknown) => setReadings((prev) => ({ ...prev, [kind]: { ...prev[kind], busy: false, error: errorText(reason) } })));
    },
    [server],
  );

  useEffect(() => {
    if (serves('sensors_battery')) read('battery');
  }, [read, serves]);

  const battery = batterySummary(readings.battery?.data);
  const location = readings.location?.data === undefined ? null : locationSummary(readings.location.data);
  const notifications = readings.notifications?.data === undefined ? null : notificationItems(readings.notifications.data, 12);

  return (
    <Card>
      <div className="mb-1 cz-eyebrow">Senses</div>
      <p className="text-xs text-pc-text-faint">What this phone knows about itself right now. Each reading asks the phone when you press it.</p>

      <div className="mt-3 grid gap-3 md:grid-cols-3">
        {serves('sensors_battery') && (
          <div className="space-y-2">
            <StatCard
              label="Battery"
              value={battery?.percent !== null && battery?.percent !== undefined ? `${battery.percent}%` : readings.battery?.busy ? '…' : '—'}
              sublabel={
                battery
                  ? [battery.status, battery.temperature !== null ? `${battery.temperature} °C` : null, battery.health ? `health ${battery.health}` : null]
                      .filter(Boolean)
                      .join(' · ')
                  : readings.battery?.error ?? 'not read yet'
              }
              tone={battery?.tone === 'ok' || battery?.tone === 'warn' || battery?.tone === 'error' ? battery.tone : undefined}
              icon={<BatteryMedium size={18} />}
            />
            <Button variant="ghost" size="sm" onClick={() => read('battery')} disabled={readings.battery?.busy}>
              <RefreshCw size={12} aria-hidden="true" />
              <span className="ml-1.5">Read again</span>
            </Button>
          </div>
        )}

        {serves('sensors_location') && (
          <div className="space-y-2">
            <StatCard
              label="Whereabouts"
              value={location ? location.place ?? location.coords ?? location.wifi ?? 'unknown' : readings.location?.busy ? '…' : '—'}
              sublabel={
                location
                  ? [location.wifi ? `Wi-Fi ${location.wifi}` : null, location.isp].filter(Boolean).join(' · ') || 'from the public IP'
                  : readings.location?.error ?? 'Wi-Fi network and the city, from the public IP'
              }
              icon={<MapPin size={18} />}
            />
            <Button variant="ghost" size="sm" onClick={() => read('location')} disabled={readings.location?.busy}>
              <MapPin size={12} aria-hidden="true" />
              <span className="ml-1.5">{location ? 'Read again' : 'Where is it?'}</span>
            </Button>
          </div>
        )}

        {serves('sensors_notifications') && (
          <div className="space-y-2">
            <StatCard
              label="Notifications"
              value={notifications ? notifications.length : readings.notifications?.busy ? '…' : '—'}
              sublabel={notifications ? 'in the status bar now' : readings.notifications?.error ?? 'what is waiting in the status bar'}
              icon={<Bell size={18} />}
            />
            <Button variant="ghost" size="sm" onClick={() => read('notifications')} disabled={readings.notifications?.busy}>
              <Bell size={12} aria-hidden="true" />
              <span className="ml-1.5">{notifications ? 'Read again' : 'Read them'}</span>
            </Button>
          </div>
        )}
      </div>

      {notifications && notifications.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {notifications.map((n, i) => (
            <li key={`${n.app}:${n.title}:${i}`} className="rounded-[var(--radius-md)] border border-pc-border bg-pc-elevated p-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-pc-text">{n.title || '(no title)'}</span>
                <span className="font-mono text-xs text-pc-text-faint">{n.app}</span>
                {n.when && <span className="ml-auto text-xs text-pc-text-faint">{n.when}</span>}
              </div>
              {n.content && <p className="mt-0.5 text-xs text-pc-text-secondary">{n.content}</p>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function CaptureCard({ devices, server, serves }: { devices: BodyDevice[]; server?: string; serves: (tool: string) => boolean }) {
  const [device, setDevice] = useState('self');
  const [capture, setCapture] = useState<BodyCapture | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const take = async (kind: 'screen' | 'camera', facing?: 'back' | 'front') => {
    setBusy(`${kind}:${facing ?? ''}`);
    setError(null);
    try {
      setCapture(await captureBody(kind, { device, facing }, server));
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(null);
    }
  };

  const deviceOptions = devices.map((d) => ({ value: d.name, label: deviceLabel(d) }));
  const fileName = capture ? `${capture.kind}-${capture.device}${capture.facing ? `-${capture.facing}` : ''}.${capture.mime === 'image/jpeg' ? 'jpg' : 'png'}` : '';

  return (
    <Card>
      <div className="mb-1 cz-eyebrow">Screen & camera</div>
      <p className="text-xs text-pc-text-faint">
        A screenshot of any paired phone; a photo from this phone's camera. The Body keeps the file under its tmp dir for a day.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {serves('device_screencap') && (
          <>
            <Select value={device} onChange={setDevice} options={deviceOptions} className="min-w-40" />
            <Button size="sm" onClick={() => void take('screen')} disabled={busy !== null}>
              <Monitor size={14} aria-hidden="true" />
              <span className="ml-1.5">{busy === 'screen:' ? 'Capturing…' : 'Capture screen'}</span>
            </Button>
          </>
        )}
        {serves('sensors_camera_photo') && (
          <>
            <Button size="sm" variant="ghost" onClick={() => void take('camera', 'back')} disabled={busy !== null}>
              <Camera size={14} aria-hidden="true" />
              <span className="ml-1.5">{busy === 'camera:back' ? 'Taking…' : 'Photo, back'}</span>
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void take('camera', 'front')} disabled={busy !== null}>
              <Camera size={14} aria-hidden="true" />
              <span className="ml-1.5">{busy === 'camera:front' ? 'Taking…' : 'Photo, front'}</span>
            </Button>
          </>
        )}
      </div>

      {error && <ErrorBox>{error}</ErrorBox>}

      {capture && (
        <figure className="mt-4 space-y-2">
          <img
            src={captureDataUrl(capture)}
            alt={capture.kind === 'screen' ? `Screen of ${capture.device}` : `Photo from the ${capture.facing} camera`}
            className="max-h-[70vh] rounded-[var(--radius-md)] border border-pc-border"
          />
          <figcaption className="flex flex-wrap items-center gap-3 text-xs text-pc-text-faint">
            <span>{capture.text}</span>
            <a className="ml-auto inline-flex items-center gap-1 text-pc-accent hover:underline" href={captureDataUrl(capture)} download={fileName}>
              <Download size={12} aria-hidden="true" /> Save
            </a>
          </figcaption>
        </figure>
      )}
    </Card>
  );
}

const FLAG_OPTIONS = [
  { value: '-3', label: 'Third-party apps' },
  { value: '-s', label: 'System apps' },
  { value: 'all', label: 'Everything' },
];

function PackagesCard({ devices, server }: { devices: BodyDevice[]; server?: string }) {
  const [device, setDevice] = useState('self');
  const [flags, setFlags] = useState('-3');
  const [packages, setPackages] = useState<BodyPackage[] | null>(null);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await getBodyPackages(device, flags, server);
      setPackages(r.packages);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  };

  const shown = packages ? filterPackages(packages, query) : [];
  const limit = 400;

  return (
    <Card>
      <div className="mb-1 flex items-center justify-between">
        <div className="cz-eyebrow">Packages</div>
        {packages && <Badge tone="neutral">{packages.length}</Badge>}
      </div>
      <p className="text-xs text-pc-text-faint">
        What is installed, as <code className="font-mono">pm list packages</code> reports it. Before the agent removes or disables anything,
        the Body snapshots this list first.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Select value={device} onChange={setDevice} options={devices.map((d) => ({ value: d.name, label: deviceLabel(d) }))} className="min-w-40" />
        <Select value={flags} onChange={setFlags} options={FLAG_OPTIONS} className="min-w-40" />
        <Button size="sm" onClick={() => void load()} disabled={busy}>
          <Package size={14} aria-hidden="true" />
          <span className="ml-1.5">{busy ? 'Listing…' : 'List'}</span>
        </Button>
        {packages && (
          <input
            className="input-electric min-w-40 flex-1"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by name"
            aria-label="Filter packages"
          />
        )}
      </div>

      {error && <ErrorBox>{error}</ErrorBox>}

      {packages && packages.length === 0 && <p className="mt-3 text-sm text-pc-text-muted">Nothing listed.</p>}

      {shown.length > 0 && (
        <ul className="mt-3 max-h-96 space-y-1 overflow-y-auto font-mono text-xs">
          {shown.slice(0, limit).map((p) => (
            <li key={p.name} className="flex flex-wrap gap-2 text-pc-text-secondary">
              <span className="text-pc-text">{p.name}</span>
              {p.path && <span className="text-pc-text-faint">{p.path}</span>}
            </li>
          ))}
          {shown.length > limit && <li className="text-pc-text-faint">…and {shown.length - limit} more; narrow the filter.</li>}
        </ul>
      )}
    </Card>
  );
}

function ToolsCard({ status }: { status: BodiesStatus }) {
  const groups = Object.entries(status.groups ?? {});
  const classes = status.classes ?? {};
  return (
    <Card>
      <div className="mb-1 flex items-center justify-between">
        <div className="cz-eyebrow">What the Body can do</div>
        <Badge tone="neutral">{(status.tools ?? []).length} tools</Badge>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {groups.map(([group, n]) => (
          <Badge key={group} tone="neutral">
            {groupLabel(group)} {n}
          </Badge>
        ))}
      </div>
      <p className="mt-3 text-xs text-pc-text-faint">
        {classes['read-only'] ?? 0} read-only · {classes.destructive ?? 0} destructive · {classes.neutral ?? 0} neutral. Destructive tools need
        a reason and are audit-logged by the Body; the Runtime's risk profile asks you before the agent runs one. What you do on this page
        is your own hand on the phone.
      </p>
    </Card>
  );
}
