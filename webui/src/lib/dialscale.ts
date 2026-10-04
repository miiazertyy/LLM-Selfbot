/**
 * What a dial in Settings measures (Dial.svelte): how its values sit round
 * it, how they snap as it is dragged, and how they are said.
 *
 * A dial draws and drags; a scale knows the numbers. Amounts of time use the
 * arithmetic in durations.ts; typing speeds are words per minute on an even
 * scale. Plain functions of plain data, so they run under Node in tests.
 */
import { fracOf as timeFrac, marks as timeMarks, niceTop, readTime, say, sayRange, short, snap as timeSnap, stepFor,
         valueAt as timeValue, type Unit } from "./durations.ts";

export type Mark = { v: number; frac: number; text: string };

export type DialScale = {
  /** The unit values are stored in, for the typed editor and the stored-value line. */
  unit: string;
  /** The least and most a value may be: the setting's own bounds. */
  min: number;
  max: number;
  /** How far round the dial a value sits, 0 to 1, on a dial from lo to hi. */
  fracOf(v: number, lo: number, hi: number): number;
  /** The value a fraction of the way round stands for. */
  valueAt(f: number, lo: number, hi: number): number;
  /** A dragged value, snapped to a round number and kept inside lo..cap. */
  snap(v: number, lo: number, cap: number): number;
  /** A typed value, kept to the setting's own precision and no rounder. */
  exact(v: number): number;
  /** What was typed, as a value; null when it is not one. */
  read(text: string): number | null;
  /** An example of what can be typed, for the box. */
  example: string;
  /** How far one press of an arrow key moves a value. */
  step(v: number): number;
  /** A value in words, and two as a range. */
  say(v: number): string;
  sayRange(a: number, b: number): string;
  /** A short label for an end of the dial. */
  short(v: number): string;
  /** Round values marked round the rim. */
  marks(lo: number, hi: number): Mark[];
  /** Where the dial should end to show this value with room to spare. */
  fit(peak: number): number;
};

/** A number as typed, with a comma for a point allowed. */
function plainNumber(t: string): number | null {
  const s = String(t).trim().replace(",", ".");
  return s && isFinite(Number(s)) ? Number(s) : null;
}

/** Amounts of time, kept in `unit`. */
export function timeScale(unit: Unit, o: { min?: number; max?: number; least?: number; integer?: boolean } = {}): DialScale {
  const least = o.least || (o.integer ? 1 : 0);
  return {
    unit,
    min: o.min ?? 0,
    max: o.max ?? Infinity,
    fracOf: timeFrac,
    valueAt: timeValue,
    snap: (v, lo, cap) => timeSnap(v, unit, { least, integer: o.integer, lo, hi: cap }),
    exact: (v) => {
      const x = o.integer ? Math.round(v) : least ? Math.round(v / least) * least : v;
      return Math.round(x * 1e6) / 1e6;
    },
    read: (t) => readTime(t, unit),
    example: "90, 2m, 1h 30m",
    step: (v) => stepFor(v, unit, least),
    say: (v) => say(v, unit),
    sayRange: (a, b) => sayRange(a, b, unit),
    short: (v) => short(v, unit),
    marks: (lo, hi) => timeMarks(lo, hi, unit),
    fit: (peak) => niceTop(peak, unit, o.min ?? 0),
  };
}

/** Round counts a dial can end on. */
const COUNT_TOPS = [5, 10, 20, 30, 50, 75, 100, 150, 200, 300, 500, 1000];

/** A count of things ("20 chats"), on an even scale, in whole numbers. */
export function countScale(o: { min?: number; max?: number; one: string; many: string }): DialScale {
  const min = o.min ?? 0;
  const max = o.max ?? Infinity;
  const even = (v: number, lo: number, hi: number) => (hi <= lo ? 0 : Math.max(0, Math.min(1, (v - lo) / (hi - lo))));
  const of = (v: number) => `${Math.round(v)} ${Math.round(v) === 1 ? o.one : o.many}`;
  return {
    unit: o.many,
    min,
    max,
    fracOf: even,
    valueAt: (f, lo, hi) => lo + (hi - lo) * Math.max(0, Math.min(1, f)),
    snap: (v, lo, cap) => Math.max(lo, Math.min(cap, Math.round(v))),
    exact: (v) => Math.round(v),
    read: plainNumber,
    example: "",
    step: () => 1,
    say: of,
    sayRange: (a, b) => (Math.round(a) === Math.round(b) ? of(a) : `${Math.round(a)}–${Math.round(b)} ${o.many}`),
    short: (v) => String(Math.round(v)),
    marks: (lo, hi) => {
      const out: Mark[] = [];
      const every = [1, 2, 5, 10, 20, 25, 50, 100, 250].find((s) => (hi - lo) / s <= 5) ?? 500;
      for (let v = Math.ceil((lo + 1) / every) * every; v < hi; v += every) {
        const frac = even(v, lo, hi);
        if (frac > 0.12 && frac < 0.88) out.push({ v, frac, text: String(v) });
      }
      return out;
    },
    fit: (peak) => Math.min(max, COUNT_TOPS.find((t) => t >= Math.max(peak * 1.5, min + 1)) ?? max),
  };
}

/** Round speeds a typing dial can end on, in words per minute. */
const WPM_TOPS = [60, 90, 120, 150, 200, 250, 300];

/** Typing speeds, in words per minute, on an even scale. */
export function wpmScale(o: { min?: number; max?: number } = {}): DialScale {
  const min = o.min ?? 5;
  const max = o.max ?? 300;
  const even = (v: number, lo: number, hi: number) => (hi <= lo ? 0 : Math.max(0, Math.min(1, (v - lo) / (hi - lo))));
  return {
    unit: "wpm",
    min,
    max,
    fracOf: even,
    valueAt: (f, lo, hi) => lo + (hi - lo) * Math.max(0, Math.min(1, f)),
    snap: (v, lo, cap) => Math.max(lo, Math.min(cap, Math.round(v))),
    exact: (v) => Math.round(v),
    read: plainNumber,
    example: "",
    step: () => 1,
    say: (v) => `${Math.round(v)} wpm`,
    sayRange: (a, b) => (Math.round(a) === Math.round(b) ? `${Math.round(a)} wpm` : `${Math.round(a)}–${Math.round(b)}`),
    short: (v) => String(Math.round(v)),
    marks: (lo, hi) => {
      const out: Mark[] = [];
      const every = hi - lo > 150 ? 50 : 30;
      for (let v = Math.ceil((lo + 1) / every) * every; v < hi; v += every) {
        const frac = even(v, lo, hi);
        if (frac > 0.12 && frac < 0.88) out.push({ v, frac, text: String(v) });
      }
      return out;
    },
    fit: (peak) => Math.min(max, WPM_TOPS.find((t) => t >= peak * 1.5) ?? max),
  };
}
