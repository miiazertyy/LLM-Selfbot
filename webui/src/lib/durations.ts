/**
 * The arithmetic behind the time dials in Settings (TimeDial.svelte).
 *
 * Settings keep amounts of time in whatever unit suits them: milliseconds for
 * Snapchat's pacing, seconds for most delays, minutes, hours, days. The dial
 * shows them all the same way: said in words ("2 min 30 s"), placed round a
 * gauge that gives more room to the small amounts, where a second matters,
 * than to the large, where it does not, and snapped to round numbers as it
 * is dragged, so a drag lands on 2 min 30 s rather than 2 min 27 s.
 *
 * Plain functions of plain data, so they run under Node in tests/durations_logic.mjs.
 */

export type Unit = "ms" | "s" | "min" | "h" | "days";

/** Seconds in one of each unit. */
export const SECONDS: Record<Unit, number> = { ms: 0.001, s: 1, min: 60, h: 3600, days: 86400 };

export const isTimeUnit = (u: string): u is Unit => u in SECONDS;
export const toSeconds = (v: number, u: Unit) => v * SECONDS[u];
export const fromSeconds = (s: number, u: Unit) => s / SECONDS[u];

const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
/** Rid a float of binary noise: 0.30000000000000004 is 0.3. */
const tidy = (x: number) => Math.round(x * 1e6) / 1e6;

/**
 * An amount as a person says it, in at most two parts: "45 s", "2 min 30 s",
 * "1 h 5 min", "3 days", "2.5 s", "800 ms".
 */
export function say(v: number, u: Unit): string {
  if (!isFinite(v)) return "";
  const secs = Math.abs(toSeconds(v, u));
  if (secs === 0) return "0 s";
  if (secs < 1) return `${Math.round(secs * 1000)} ms`;
  if (secs < 60) return `${tidy(Math.round(secs * 10) / 10)} s`;
  const total = Math.round(secs);
  const d = Math.floor(total / 86400);
  const h = Math.floor((total % 86400) / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const parts = [
    d && `${d} day${d === 1 ? "" : "s"}`,
    h && `${h} h`,
    m && `${m} min`,
    s && `${s} s`,
  ].filter(Boolean) as string[];
  // The first two parts that are there, and only next to each other: "1 day 3 h", not "1 day 20 s".
  const first = [d, h, m, s].findIndex((x) => x > 0);
  const next = [d, h, m, s][first + 1];
  return next ? parts.slice(0, 2).join(" ") : parts[0];
}

/** The words a typed amount may end in, and the seconds in each. */
const UNIT_WORDS: [RegExp, number][] = [
  [/^(ms|msecs?|millis(econds?)?)$/, 0.001],
  [/^(s|secs?|seconds?)$/, 1],
  [/^(m|mins?|minutes?)$/, 60],
  [/^(h|hrs?|hours?)$/, 3600],
  [/^(d|days?)$/, 86400],
];

/**
 * An amount typed by hand into a setting kept in `unit`. A plain number is in
 * that unit ("8000" for a setting in milliseconds); anything else says its
 * own: "2m", "1h 30m", "45 s", "1.5 min". Null for anything that is not an
 * amount of time.
 */
export function readTime(text: string, unit: Unit): number | null {
  const s = String(text).trim().toLowerCase().replace(/,/g, ".");
  if (!s) return null;
  if (/^\d+(\.\d+)?$/.test(s)) return Number(s);
  let secs = 0;
  let rest = s;
  let found = false;
  for (const m of s.matchAll(/(\d+(?:\.\d+)?)\s*([a-z]+)/g)) {
    const each = UNIT_WORDS.find(([rx]) => rx.test(m[2]))?.[1];
    if (each == null) return null;
    secs += Number(m[1]) * each;
    rest = rest.replace(m[0], "");
    found = true;
  }
  if (!found || rest.trim()) return null;
  return tidy(fromSeconds(secs, unit));
}

/** Seconds as a label under a mark on a scale: "20s", "1m10s", "5m", "1h30m", "2d". */
export function compact(secs: number): string {
  const t = Math.round(secs);
  if (t < 60) return `${t}s`;
  if (t < 3600) return `${Math.floor(t / 60)}m${t % 60 ? `${t % 60}s` : ""}`;
  if (t < 86400) return `${Math.floor(t / 3600)}h${Math.floor((t % 3600) / 60) ? `${Math.floor((t % 3600) / 60)}m` : ""}`;
  return `${Math.round(t / 86400)}d`;
}

/** A short label for a mark round the dial: "30s", "5m", "1h", "2d", "500ms". */
export function short(v: number, u: Unit): string {
  const secs = toSeconds(v, u);
  if (secs === 0) return "0";
  if (secs < 1) return `${Math.round(secs * 1000)}ms`;
  if (secs < 60) return `${tidy(secs)}s`;
  if (secs < 3600) return `${tidy(secs / 60)}m`;
  if (secs < 86400) return `${tidy(secs / 3600)}h`;
  return `${tidy(secs / 86400)}d`;
}

/** How far round the dial the small amounts are stretched: 1 would be even, above 1 favours the small. */
export const CURVE = 1.6;

/** The amount a fraction of the way round the dial stands for. */
export const valueAt = (frac: number, lo: number, hi: number) => lo + (hi - lo) * Math.pow(clamp01(frac), CURVE);

/** How far round the dial an amount sits, 0 to 1. */
export const fracOf = (v: number, lo: number, hi: number) =>
  hi <= lo ? 0 : Math.pow(clamp01((v - lo) / (hi - lo)), 1 / CURVE);

/**
 * The round number to snap to near an amount: half seconds under ten
 * seconds, seconds under a minute, five seconds under ten minutes, and so on
 * up to whole days. Never finer than `least`, the setting's own step.
 */
export function stepFor(v: number, u: Unit, least = 0): number {
  const secs = Math.abs(toSeconds(v, u));
  const s =
    secs < 10 ? 0.5 :
    secs < 60 ? 1 :
    secs < 600 ? 5 :
    secs < 1800 ? 15 :
    secs < 3600 ? 30 :
    secs < 6 * 3600 ? 60 :
    secs < 86400 ? 300 :
    secs < 7 * 86400 ? 3600 : 86400;
  return Math.max(fromSeconds(s, u), least);
}

/** An amount snapped to its round number, whole where the setting is a whole number, inside its bounds. */
export function snap(v: number, u: Unit, opts: { least?: number; integer?: boolean; lo?: number; hi?: number } = {}): number {
  const st = stepFor(v, u, opts.least ?? 0);
  let out = Math.round(v / st) * st;
  if (opts.integer) out = Math.round(out);
  if (opts.lo != null) out = Math.max(opts.lo, out);
  if (opts.hi != null) out = Math.min(opts.hi, out);
  return tidy(out);
}

/** Round amounts a dial can end on, in seconds. */
const TOPS = [10, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 172800, 604800, 1209600, 2592000];

/**
 * The top of a dial for a setting with no maximum of its own: the next round
 * amount comfortably past what it holds (twice it), so there is room to turn
 * it up, and at least four times its minimum.
 */
export function niceTop(v: number, u: Unit, lo = 0): number {
  const want = Math.max(toSeconds(Math.abs(v) || 0, u) * 2, toSeconds(lo, u) * 4, 10);
  const top = TOPS.find((t) => t >= want) ?? Math.ceil(want / 2592000) * 2592000;
  return fromSeconds(top, u);
}

/** Candidate marks round a dial, in seconds. */
const MARKS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400,
  172800, 259200, 604800, 1209600, 2592000];

/**
 * The round amounts marked round a dial between its ends, spaced so they do
 * not crowd: at least `gap` of the way round apart, and clear of the ends,
 * which are labelled on their own.
 */
export function marks(lo: number, hi: number, u: Unit, gap = 0.2): { v: number; frac: number; text: string }[] {
  const out: { v: number; frac: number; text: string }[] = [];
  let last = 0;
  for (const s of MARKS) {
    const v = fromSeconds(s, u);
    if (v <= lo || v >= hi) continue;
    const frac = fracOf(v, lo, hi);
    if (frac - last < gap || 1 - frac < gap) continue;
    out.push({ v, frac, text: short(v, u) });
    last = frac;
  }
  return out;
}

/**
 * Two amounts said as one range: "2–10 min" when they end in the same unit,
 * "45 s – 2 min" when they do not, and just the one when they are equal.
 */
export function sayRange(a: number, b: number, u: Unit): string {
  const x = say(a, u), y = say(b, u);
  if (x === y) return x;
  const mx = x.match(/^(\d+(?:\.\d+)?) ([a-z]+)$/), my = y.match(/^(\d+(?:\.\d+)?) ([a-z]+)$/);
  if (mx && my && mx[2] === my[2]) return `${mx[1]}–${my[1]} ${my[2]}`;
  return `${x} – ${y}`;
}
