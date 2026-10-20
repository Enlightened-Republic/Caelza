// The Caelza lockup (brand/BRAND.md): the parent's eyebrow, the mark, the
// Orbitron wordmark, the tagline; and the attribution every Enlightened
// Republic product signs its footer with. Styles live in src/caelza-brand.css.
//
// Written with createElement rather than JSX, and with no module-level
// dependency on the browser (callers pass the mark's URL,
// `${basePath}/_app/logo.png`), so the same file renders in Node for the
// jiti test next to it.
import { createElement, type CSSProperties, type ReactElement, type SyntheticEvent } from 'react';

/** The parent, as the brand guide writes it in UI chrome: caps, with the ™. */
export const PARENT = 'ENLIGHTENED REPUBLIC™';
export const EYEBROW = `${PARENT} PRESENTS`;
export const WORDMARK = 'CAELZA';
export const TAGLINE = 'The embodied agent runtime.';
export const ATTRIBUTION = `${PARENT} · EST. 2026`;

const wordmarkSize: Record<'sm' | 'md' | 'lg', string> = {
  sm: '14px',
  md: '18px',
  lg: '28px',
};

function classes(...names: Array<string | undefined>): string {
  return names.filter(Boolean).join(' ');
}

export interface EyebrowProps {
  className?: string;
}

export function Eyebrow({ className }: EyebrowProps): ReactElement {
  return createElement('div', { className: classes('cz-eyebrow', className) }, EYEBROW);
}

export interface WordmarkProps {
  size?: 'sm' | 'md' | 'lg';
  as?: 'span' | 'h1' | 'div';
  className?: string;
}

export function Wordmark({ size = 'md', as = 'span', className }: WordmarkProps): ReactElement {
  const style: CSSProperties = { fontSize: wordmarkSize[size], lineHeight: 1.1, margin: 0 };
  return createElement(
    as,
    { className: classes('cz-wordmark', className), style, 'aria-label': 'Caelza' },
    WORDMARK,
  );
}

export interface MarkProps {
  src: string;
  size?: number;
  className?: string;
}

/** The mark alone (the constellation Caelum drawn as a bolt). Decorative. */
export function Mark({ src, size = 36, className }: MarkProps): ReactElement {
  return createElement('img', {
    src,
    alt: '',
    'aria-hidden': 'true',
    width: size,
    height: size,
    className: classes('rounded-xl object-cover shrink-0', className),
    style: { width: size, height: size },
    onError: (e: SyntheticEvent<HTMLImageElement>) => {
      e.currentTarget.style.display = 'none';
    },
  });
}

export interface LockupProps {
  /** `${basePath}/_app/logo.png`; omitted, the lockup is text only. */
  markSrc?: string;
  tagline?: boolean;
}

/** The full lockup for hero surfaces: the pairing (login) screen. */
export function Lockup({ markSrc, tagline = true }: LockupProps): ReactElement {
  return createElement(
    'div',
    { className: 'flex flex-col items-center text-center gap-2' },
    createElement<EyebrowProps>(Eyebrow, {}),
    createElement(
      'div',
      { className: 'flex items-center justify-center gap-3' },
      markSrc
        ? createElement<MarkProps>(Mark, { src: markSrc, size: 56, className: 'animate-float' })
        : null,
      createElement<WordmarkProps>(Wordmark, { size: 'lg', as: 'h1' }),
    ),
    tagline
      ? createElement(
          'p',
          { className: 'text-sm', style: { color: 'var(--pc-text-muted)', margin: 0 } },
          TAGLINE,
        )
      : null,
  );
}

export interface AttributionProps {
  /** The two-letter form for the 56 px rail; the full line stays as tooltip and name. */
  compact?: boolean;
}

/** Footer attribution: the parent signs every Enlightened Republic product. */
export function Attribution({ compact = false }: AttributionProps): ReactElement {
  if (compact) {
    return createElement(
      'span',
      { className: 'cz-attribution', title: `${PARENT} presents Caelza`, 'aria-label': ATTRIBUTION },
      'ER™',
    );
  }
  return createElement('div', { className: 'cz-attribution' }, ATTRIBUTION);
}
