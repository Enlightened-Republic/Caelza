// A scroll wheel for a phone: one column of rows that snaps to the centre
// band, the chosen row bright and the rest fading out, flickable with a
// thumb, tappable, and a listbox for the keyboard (arrows, Home, End). CSS
// scroll-snap does the physics; the only script is working out which row
// came to rest in the band. Styles in src/caelza-brand.css (.cz-wheel*).
import { useEffect, useLayoutEffect, useRef, type KeyboardEvent, type ReactNode } from "react";

export interface WheelRow {
  id: string;
  label: string;
  /** A badge or note at the row's right edge (the pick's tag). */
  hint?: ReactNode;
}

/** Every row is this tall; the band and the padding are multiples of it. */
export const ROW_HEIGHT = 44;

/** How long after the last scroll event the wheel is taken to have come to rest. */
const SETTLE_MS = 140;

export function WheelPicker({
  id,
  rows,
  value,
  onChange,
  label,
  visible = 5,
}: {
  /** A DOM id prefix for the options (aria-activedescendant). */
  id: string;
  rows: ReadonlyArray<WheelRow>;
  value: string;
  onChange: (id: string) => void;
  /** The accessible name of the wheel. */
  label: string;
  /** Rows shown at once; odd, so one sits in the band. */
  visible?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const timer = useRef<number | null>(null);
  const settled = useRef(false);
  const idx = Math.max(0, rows.findIndex((r) => r.id === value));
  const pad = ((visible - 1) / 2) * ROW_HEIGHT;

  // Keep the chosen row in the band when the value or the rows change from
  // outside: instantly the first time, smoothly after (unless the owner asked
  // for less motion).
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const top = idx * ROW_HEIGHT;
    if (Math.abs(el.scrollTop - top) >= 1) {
      const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
      el.scrollTo({ top, behavior: settled.current && !reduce ? "smooth" : "auto" });
    }
    settled.current = true;
  }, [idx, rows.length]);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const settle = () => {
    const el = ref.current;
    if (!el) return;
    const i = Math.min(rows.length - 1, Math.max(0, Math.round(el.scrollTop / ROW_HEIGHT)));
    const row = rows[i];
    if (row && row.id !== value) onChange(row.id);
  };

  const onScroll = () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(settle, SETTLE_MS);
  };

  const select = (i: number) => {
    const row = rows[Math.min(rows.length - 1, Math.max(0, i))];
    if (!row) return;
    if (row.id !== value) onChange(row.id);
    else ref.current?.scrollTo({ top: i * ROW_HEIGHT, behavior: "smooth" });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const jump: Record<string, number | undefined> = {
      ArrowDown: idx + 1,
      ArrowUp: idx - 1,
      PageDown: idx + visible,
      PageUp: idx - visible,
      Home: 0,
      End: rows.length - 1,
    };
    const to = jump[e.key];
    if (to === undefined) return;
    e.preventDefault();
    select(to);
  };

  return (
    <div className="cz-wheel-wrap" style={{ height: visible * ROW_HEIGHT }}>
      <div className="cz-wheel-band" aria-hidden="true" />
      <div
        ref={ref}
        className="cz-wheel"
        role="listbox"
        aria-label={label}
        aria-activedescendant={rows.length ? `${id}-${idx}` : undefined}
        tabIndex={0}
        onScroll={onScroll}
        onKeyDown={onKeyDown}
      >
        <div style={{ height: pad }} aria-hidden="true" />
        {rows.map((r, i) => (
          <div
            key={r.id}
            id={`${id}-${i}`}
            role="option"
            aria-selected={i === idx}
            className={`cz-wheel-row${i === idx ? " is-selected" : ""}`}
            data-dist={Math.min(3, Math.abs(i - idx))}
            onClick={() => select(i)}
          >
            <span className="cz-wheel-label">{r.label}</span>
            {r.hint ? <span className="cz-wheel-hint">{r.hint}</span> : null}
          </div>
        ))}
        <div style={{ height: pad }} aria-hidden="true" />
      </div>
    </div>
  );
}
