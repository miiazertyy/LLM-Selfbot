/**
 * The arithmetic behind the clocks in Settings: the night-hours dial
 * (HourRange) and the timezone picker (TimezonePicker).
 *
 * Night hours are stored the way the runner reads them (app/utils/behavior.py
 * _parse_hours and night_window_state): "start-end" in whole hours, 0 to 23,
 * local to the persona's timezone, wrapping past midnight ("23-7"), and a start
 * equal to its end meaning no night at all. This mirrors those rules, so the
 * dial never says asleep when the account would not be.
 *
 * Plain functions of plain data (Intl aside), so they run under Node in
 * tests/clock_logic.mjs.
 */

// With its extension: the tests load this file straight into Node, which does not guess one.
import { ZONE_COUNTRY } from "./zonecountries.ts";

export type Hours = { start: number; end: number };

/** "2-8" into hours, or null when it is not a range the runner would accept. */
export function parseHours(spec: unknown): Hours | null {
  const m = /^\s*(\d{1,2})\s*-\s*(\d{1,2})\s*$/.exec(String(spec ?? ""));
  if (!m) return null;
  const start = Number(m[1]);
  const end = Number(m[2]);
  return start <= 23 && end <= 23 ? { start, end } : null;
}

export const formatHours = (h: Hours) => `${h.start}-${h.end}`;

/** Any whole number of hours onto the clock, 0 to 23. */
export const wrap = (h: number) => ((Math.round(h) % 24) + 24) % 24;

/** How long the night lasts, in hours: 0 when it starts where it ends. */
export const span = (h: Hours) => (h.end - h.start + 24) % 24;

/** Whether `hour` is inside the night, as the runner decides it. */
export function isNight(h: Hours, hour: number): boolean {
  if (h.start === h.end) return false;
  return h.start > h.end ? hour >= h.start || hour < h.end : h.start <= hour && hour < h.end;
}

/** Minutes until the account next goes to sleep or wakes, at `hour`:`minute`. Null with no night. */
export function untilChange(h: Hours, hour: number, minute: number): number | null {
  if (h.start === h.end) return null;
  const next = isNight(h, hour) ? h.end : h.start;
  let away = (next - hour + 24) % 24;
  if (away === 0) away = 24;
  return away * 60 - minute;
}

/** The angle of an hour on a 24-hour dial, in radians, clockwise from midnight at the top. */
export const angleOf = (hour: number) => (hour / 24) * Math.PI * 2;

/** The hour nearest to a point on the dial, from its offset to the centre (y pointing down). */
export function hourAt(dx: number, dy: number): number {
  const a = Math.atan2(dx, -dy);
  return wrap((((a + Math.PI * 2) % (Math.PI * 2)) / (Math.PI * 2)) * 24);
}

/** Hours between two points of the clock, the short way round. */
export const apart = (a: number, b: number) => Math.min((a - b + 24) % 24, (b - a + 24) % 24);

/** Which end of the night is nearer to `hour`: the one a click on the ring should move. */
export const nearer = (h: Hours, hour: number): "start" | "end" =>
  apart(hour, h.start) <= apart(hour, h.end) ? "start" : "end";

/** "2 h 20 min", "45 min": a stretch of minutes, readable. */
export function duration(mins: number): string {
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  if (!h) return `${m} min`;
  return m ? `${h} h ${m} min` : `${h} h`;
}

/** "02:00", "23:00". */
export const hh = (hour: number) => `${String(wrap(hour)).padStart(2, "0")}:00`;

/**
 * An hour typed by hand: "7", "07", "7:00", "19h", "7pm", "12am". Minutes are
 * dropped, since the runner reads whole hours, and 24 is midnight. Null for
 * anything that is not an hour.
 */
export function readHour(text: string): number | null {
  const m = String(text).trim().toLowerCase().match(/^(\d{1,2})(?:[:h.](\d{2})?)?\s*(am|pm|h)?$/);
  if (!m) return null;
  let h = Number(m[1]);
  if (m[3] === "pm" && h < 12) h += 12;
  else if (m[3] === "am" && h === 12) h = 0;
  if (h === 24) h = 0;
  return h >= 0 && h <= 23 ? h : null;
}

// ── Timezones ────────────────────────────────────────────────────────────────

const formats = new Map<string, Intl.DateTimeFormat>();
function fmt(tz: string, opts: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `${tz}|${JSON.stringify(opts)}`;
  let f = formats.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat("en-GB", { timeZone: tz, ...opts });
    formats.set(key, f);
  }
  return f;
}

/** Whether the runtime knows a timezone by this name. */
export function validZone(tz: string): boolean {
  if (!tz) return false;
  try {
    fmt(tz, { hour: "2-digit" });
    return true;
  } catch {
    return false;
  }
}

/** The time on a clock in `tz`: hour, minute, second. Null for a zone that does not exist. */
export function zoneNow(tz: string, at: Date = new Date()): { hour: number; minute: number; second: number } | null {
  try {
    const parts = fmt(tz, { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).formatToParts(at);
    const get = (t: string) => Number(parts.find((p) => p.type === t)?.value ?? 0);
    return { hour: get("hour") % 24, minute: get("minute"), second: get("second") };
  } catch {
    return null;
  }
}

/** "UTC+2", "UTC-3:30", "UTC" for a zone right now. Empty for one that does not exist. */
export function zoneOffset(tz: string, at: Date = new Date()): string {
  try {
    const name = fmt(tz, { timeZoneName: "shortOffset" }).formatToParts(at).find((p) => p.type === "timeZoneName")?.value ?? "";
    return name.replace(/^GMT/, "UTC");
  } catch {
    return "";
  }
}

/** "America/Argentina/Buenos_Aires" as a city and where it is: "Buenos Aires", "America · Argentina". */
export function zoneLabel(tz: string): { city: string; region: string } {
  const bits = tz.split("/");
  const city = (bits.pop() ?? tz).replace(/_/g, " ");
  return { city, region: bits.join(" · ").replace(/_/g, " ") };
}

/** The two-letter country a zone is in ("FR" for Europe/Paris); empty for UTC and the like. */
export const countryOf = (tz: string) => ZONE_COUNTRY[tz] ?? "";

/**
 * A country's flag: the emoji made of its two regional indicator letters. Also
 * England, Scotland and Wales ("GB-ENG", "GB-SCT", "GB-WLS"), which are a black
 * flag followed by tag letters spelling the region. Empty for anything else.
 */
export function flagOf(cc: string): string {
  if (/^[A-Za-z]{2}$/.test(cc)) return String.fromCodePoint(...[...cc.toUpperCase()].map((c) => 0x1f1a5 + c.charCodeAt(0)));
  if (/^GB-(ENG|SCT|WLS)$/i.test(cc)) {
    const tags = [...cc.replace("-", "").toLowerCase()].map((c) => 0xe0000 + c.charCodeAt(0));
    return String.fromCodePoint(0x1f3f4, ...tags, 0xe007f);
  }
  return "";
}

let regions: Intl.DisplayNames | null | undefined;
/** "France" for "FR", in English like the rest of the app; the code itself if the runtime has no name for it. */
export function countryName(cc: string): string {
  if (!cc) return "";
  if (regions === undefined) {
    try {
      regions = new Intl.DisplayNames(["en"], { type: "region" });
    } catch {
      regions = null;
    }
  }
  try {
    return regions?.of(cc.toUpperCase()) ?? cc;
  } catch {
    return cc;
  }
}

/** Every timezone the runtime knows, UTC included. */
export function allZones(): string[] {
  const list = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
  return list.includes("UTC") ? list : ["UTC", ...list];
}

/** This computer's own timezone. */
let zone = "";
/** This computer's timezone, asked once: it was worked out again on every redraw of the rows that show it. */
export const localZone = () => (zone ||= Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");

/** Zones matching what was typed, by city, country, region or offset, closest first. */
export function searchZones(zones: string[], q: string, at: Date = new Date()): string[] {
  const s = q.trim().toLowerCase().replace(/\s+/g, " ");
  if (!s) return zones;
  const scored: [string, number][] = [];
  for (const z of zones) {
    const { city, region } = zoneLabel(z);
    const c = city.toLowerCase();
    const nation = countryName(countryOf(z)).toLowerCase();
    const full = `${c} ${region.toLowerCase()} ${z.toLowerCase()} ${nation}`;
    let score = -1;
    if (c === s) score = 0;
    else if (c.startsWith(s)) score = 1;
    else if (nation && nation.startsWith(s)) score = 2;
    else if (full.includes(s)) score = 3;
    else if (/^(utc|gmt)?\s*[+-]/.test(s) && zoneOffset(z, at).toLowerCase().replace("utc", "").includes(s.replace(/^(utc|gmt)\s*/, ""))) score = 4;
    if (score >= 0) scored.push([z, score]);
  }
  return scored.sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0])).map(([z]) => z);
}
