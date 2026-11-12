// The Mind turned on from the Memory page: the pure part of the install card.
import type { PatchOp } from '@/lib/api';

/** What the page says for each stage of the gateway's job. */
export function stageLabel(stage: string): string {
  switch (stage) {
    case 'release':
      return 'Getting the Mind';
    case 'node':
      return 'Getting the small Node runtime it runs on';
    case 'install':
      return 'Installing (this is the slow part)';
    case 'launcher':
      return 'Writing the launcher';
    case 'tokens':
      return "Minting the agent's keys";
    case 'start':
      return 'Starting the Mind';
    case 'startup':
      return 'Setting it to start with the PC';
    case 'done':
      return 'Done';
    default:
      return stage ? stage[0]!.toUpperCase() + stage.slice(1) : 'Working';
  }
}

/** Download progress as a whole percentage, or null when the size is unknown. */
export function percent(done: number, total: number): number | null {
  if (!total || total <= 0) return null;
  return Math.max(0, Math.min(100, Math.round((done / total) * 100)));
}

/** Bytes as "12 MB" (one decimal under 10 MB). */
export function megabytes(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return mb >= 10 ? `${Math.round(mb)} MB` : `${mb.toFixed(1)} MB`;
}

/** The one config write once the Mind runs: the Runtime's memory is the Mind. */
export function installBackendOps(): PatchOp[] {
  return [{ op: 'add', path: '/memory/backend', value: 'xanima' }];
}

/** The poll interval while the job runs. */
export const POLL_MS = 1500;
