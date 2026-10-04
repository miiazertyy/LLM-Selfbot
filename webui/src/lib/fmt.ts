/**
 * Dates and times, formatted with formatters that are built once.
 *
 * `toLocaleDateString(undefined, { ... })` builds a new Intl formatter on every
 * call - it has to load and resolve the locale data each time - and several of
 * these sat in code that re-runs on every poll or for every row of a list. In
 * a profile of the panel that was a sixth of a second per Dashboard refresh on
 * a throttled CPU, for labels that never change. A formatter is reusable, so
 * each distinct set of options gets one and keeps it.
 */
const cache = new Map<string, Intl.DateTimeFormat>();

export function dateFormat(options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = JSON.stringify(options);
  let f = cache.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat(undefined, options);
    cache.set(key, f);
  }
  return f;
}

/** Format a Date or an epoch in milliseconds. */
export function fmtDate(when: Date | number, options: Intl.DateTimeFormatOptions): string {
  return dateFormat(options).format(when);
}

export const DAY_MONTH: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" };
export const HOUR_MINUTE: Intl.DateTimeFormatOptions = { hour: "2-digit", minute: "2-digit" };
export const WEEKDAY: Intl.DateTimeFormatOptions = { weekday: "short" };
export const FULL_WHEN: Intl.DateTimeFormatOptions = {
  weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit",
};

/**
 * When a message was sent, as short as it can be said: "14:32" today,
 * "Yesterday 14:32", "Mon 14:32" this week, "12 Sep 14:32" before that.
 * `ts` is in Unix seconds, as the runners send it.
 */
export function whenSent(ts: number, now: Date = new Date()): string {
  if (!ts) return "";
  const at = new Date(ts * 1000);
  const time = fmtDate(at, HOUR_MINUTE);
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((day(now) - day(at)) / 86400000);
  if (days <= 0) return time;
  if (days === 1) return `Yesterday ${time}`;
  if (days < 7) return `${fmtDate(at, WEEKDAY)} ${time}`;
  return `${fmtDate(at, DAY_MONTH)} ${time}`;
}
