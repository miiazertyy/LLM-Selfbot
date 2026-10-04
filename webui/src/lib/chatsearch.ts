/**
 * Searching a conversation the way Discord does.
 *
 * Words, and filters typed in the same box: from:, has:, before:, after:,
 * during:. A filter turns into a chip as soon as it is complete (a space after
 * it, or Enter), the way Discord turns one into a pill, and the box keeps only
 * the words. Words in quotes are kept together.
 *
 * Matching folds case and accents the way the server does (fold() in
 * app/utils/chatlog.py), so "cafe" finds "Café" and what is highlighted is
 * exactly what was found.
 */
import { fmtDate } from "./fmt";

export type HasKind = "link" | "image" | "video" | "file" | "sound" | "sticker" | "embed";
export type Who = "me" | "them";
export type DateKind = "before" | "after" | "during";
/** A stretch of time a date filter names: a day, a month or a year, in Unix seconds, `end` exclusive. */
export type Span = { start: number; end: number; label: string };
export type DateFilter = { kind: DateKind } & Span;
export type Filters = { from: Who | null; has: HasKind[]; dates: DateFilter[] };
export type Sort = "newest" | "oldest" | "relevant";
/** What the server's search routes take. */
export type Query = { words: string[]; mine: boolean | null; has: HasKind[]; before: number | null; after: number | null };

export const noFilters = (): Filters => ({ from: null, has: [], dates: [] });

export const HAS: { id: HasKind; label: string; icon: string; words: string[] }[] = [
  { id: "image", label: "Picture", icon: "pictures", words: ["image", "picture", "photo", "pic", "gif", "img"] },
  { id: "video", label: "Video", icon: "play", words: ["video", "clip", "movie"] },
  { id: "link", label: "Link", icon: "link", words: ["link", "url"] },
  { id: "file", label: "File", icon: "clipboard", words: ["file", "attachment", "document"] },
  { id: "sound", label: "Voice", icon: "mic", words: ["sound", "voice", "audio", "vocal"] },
  { id: "sticker", label: "Sticker", icon: "sparkle", words: ["sticker"] },
  { id: "embed", label: "Embed", icon: "external", words: ["embed", "preview"] },
];
export const hasInfo = (id: HasKind) => HAS.find((h) => h.id === id)!;

export const KEYS = ["from", "has", "before", "after", "during"] as const;
export type Key = (typeof KEYS)[number];
export const KEY_HINT: Record<Key, string> = {
  from: "who sent it",
  has: "a picture, a link, a file",
  before: "before a day",
  after: "after a day",
  during: "on a day",
};

// ── Folding ────────────────────────────────────────────────────────────────

const MARKS = /\p{Mn}/gu;

/** Lower case, accents gone: what both sides compare. */
export function fold(s: string): string {
  return (s || "").normalize("NFKD").replace(MARKS, "").toLowerCase().replace(/ß/g, "ss");
}

/** The words of a search: split on spaces, except inside quotes. */
export function splitWords(text: string): string[] {
  const out: string[] = [];
  for (const m of (text || "").matchAll(/"([^"]*)"?|(\S+)/g)) {
    const w = (m[1] ?? m[2] ?? "").trim();
    if (w) out.push(w);
  }
  return out;
}

/** Custom emoji and mentions are drawn as pictures and names: nothing inside them is highlighted. */
const PROTECTED = /<a?:\w+:\d+>|<[@#][!&]?\d+>/g;

/** Where the words are in a text, as [start, end) pairs, merged and in order. */
export function matchRanges(text: string, words: string[]): [number, number][] {
  const want = [...new Set(words.map(fold).filter(Boolean))];
  if (!want.length || !text) return [];
  // The folded text, and for each of its characters the original one it came from.
  let f = "";
  const at: number[] = [];
  const chars: { i: number; len: number }[] = [];
  let i = 0;
  for (const ch of text) {
    const x = fold(ch);
    for (let k = 0; k < x.length; k++) at.push(chars.length);
    f += x;
    chars.push({ i, len: ch.length });
    i += ch.length;
  }
  const skip = [...text.matchAll(PROTECTED)].map((m) => [m.index!, m.index! + m[0].length]);
  const found: [number, number][] = [];
  for (const w of want) {
    for (let from = 0; ; ) {
      const j = f.indexOf(w, from);
      if (j < 0) break;
      from = j + 1;
      let first = at[j];
      let last = at[j + w.length - 1];
      // A mark that folded to nothing right after the match belongs to it ("e" + a combining accent).
      while (last + 1 < chars.length && !fold(text.slice(chars[last + 1].i, chars[last + 1].i + chars[last + 1].len))) last++;
      const r: [number, number] = [chars[first].i, chars[last].i + chars[last].len];
      if (!skip.some(([a, b]) => r[0] < b && r[1] > a)) found.push(r);
    }
  }
  found.sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const r of found) {
    const prev = merged[merged.length - 1];
    if (prev && r[0] <= prev[1]) prev[1] = Math.max(prev[1], r[1]);
    else merged.push([...r]);
  }
  return merged;
}

const OPEN = "";
const CLOSE = "";

/**
 * A message's text, drawn by `render` (Discord's markdown), with the words
 * found in it marked. Markers go into the text first and become <mark> after
 * it is drawn, so bold, links and code still work around them; a marker that
 * landed inside a tag (a link's address) is dropped, and a mark never spans a
 * tag, so the HTML stays well formed.
 */
export function highlighted(text: string, words: string[], render: (s: string) => string): string {
  const ranges = matchRanges(text, words);
  if (!ranges.length) return render(text);
  let marked = "";
  let pos = 0;
  for (const [a, b] of ranges) {
    marked += text.slice(pos, a) + OPEN + text.slice(a, b) + CLOSE;
    pos = b;
  }
  marked += text.slice(pos);
  let inside = false;
  return render(marked)
    .split(/(<[^>]*>)/)
    .map((part, n) => {
      if (n % 2) return part.replace(/[]/g, "");
      if (!part) return part;
      let out = inside ? "<mark>" : "";
      for (const ch of part) {
        if (ch === OPEN) {
          if (!inside) out += "<mark>";
          inside = true;
        } else if (ch === CLOSE) {
          if (inside) out += "</mark>";
          inside = false;
        } else out += ch;
      }
      return inside ? `${out}</mark>` : out;
    })
    .join("")
    .replace(/<mark><\/mark>/g, "");
}

// ── Dates ──────────────────────────────────────────────────────────────────

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const DAY_LABEL: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", year: "numeric" };
const MONTH_LABEL: Intl.DateTimeFormatOptions = { month: "short", year: "numeric" };
const secs = (d: Date) => Math.floor(d.getTime() / 1000);

/** Whether this browser writes the day before the month (30/09) or after it (09/30). */
let dayFirst: boolean | null = null;
function isDayFirst(): boolean {
  if (dayFirst === null) {
    try {
      const parts = new Intl.DateTimeFormat().formatToParts(new Date(2000, 10, 22));
      dayFirst = parts.findIndex((p) => p.type === "day") < parts.findIndex((p) => p.type === "month");
    } catch {
      dayFirst = true;
    }
  }
  return dayFirst;
}

function daySpan(y: number, m: number, d: number): Span | null {
  const start = new Date(y, m - 1, d);
  if (start.getFullYear() !== y || start.getMonth() !== m - 1 || start.getDate() !== d) return null;
  const end = new Date(y, m - 1, d + 1);
  return { start: secs(start), end: secs(end), label: fmtDate(start, DAY_LABEL) };
}

function monthSpan(y: number, m: number): Span | null {
  if (m < 1 || m > 12) return null;
  const start = new Date(y, m - 1, 1);
  return { start: secs(start), end: secs(new Date(y, m, 1)), label: fmtDate(start, MONTH_LABEL) };
}

function monthOf(word: string): number {
  const i = MONTHS.indexOf(fold(word).slice(0, 3));
  return i < 0 ? 0 : i + 1;
}

/**
 * A day, a month or a year, as typed: today, yesterday, 2026-09-30,
 * 30/09/2026 (or 09/30, as this browser writes dates), 30/09, sep 30,
 * 30 sep 2026, 2026-09, sep 2026, 2025. Null for anything else.
 */
export function parseSpan(raw: string, now = new Date()): Span | null {
  const v = fold(raw).replace(/[,_]/g, " ").replace(/\s+/g, " ").trim();
  if (!v) return null;
  const y0 = now.getFullYear();
  if (v === "today") return daySpan(y0, now.getMonth() + 1, now.getDate());
  if (v === "yesterday") {
    const d = new Date(y0, now.getMonth(), now.getDate() - 1);
    return daySpan(d.getFullYear(), d.getMonth() + 1, d.getDate());
  }
  let m = v.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (m) return daySpan(+m[1], +m[2], +m[3]);
  m = v.match(/^(\d{4})-(\d{1,2})$/);
  if (m) return monthSpan(+m[1], +m[2]);
  m = v.match(/^(\d{4})$/);
  if (m) {
    const y = +m[1];
    if (y < 2000 || y > 2100) return null;
    return { start: secs(new Date(y, 0, 1)), end: secs(new Date(y + 1, 0, 1)), label: String(y) };
  }
  m = v.match(/^(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2}|\d{4}))?$/);
  if (m) {
    const [a, b] = [+m[1], +m[2]];
    let y = m[3] ? +m[3] : y0;
    if (y < 100) y += 2000;
    const [d, mo] = isDayFirst() ? (b > 12 && a <= 12 ? [b, a] : [a, b]) : (a > 12 && b <= 12 ? [a, b] : [b, a]);
    return daySpan(y, mo, d);
  }
  // Words: "sep 30", "30 sep", "30 september 2026", "sep 2026".
  const parts = v.split(" ");
  const mi = parts.findIndex((p) => /^[a-z]{3,}$/.test(p) && monthOf(p));
  if (mi >= 0) {
    const mo = monthOf(parts[mi]);
    const nums = parts.filter((_, i) => i !== mi).map((p) => p.replace(/(st|nd|rd|th)$/, ""));
    if (!nums.every((p) => /^\d+$/.test(p))) return null;
    const year = nums.find((p) => p.length === 4);
    const day = nums.find((p) => p.length <= 2);
    if (day) return daySpan(year ? +year : y0, mo, +day);
    if (year) return monthSpan(+year, mo);
    return monthSpan(y0, mo);
  }
  return null;
}

/** The quick picks a date filter offers before anything is typed. */
export function quickSpans(now = new Date()): Span[] {
  const out: Span[] = [];
  const add = (s: Span | null, label?: string) => s && out.push(label ? { ...s, label } : s);
  add(parseSpan("today", now), "Today");
  add(parseSpan("yesterday", now), "Yesterday");
  const week = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 7);
  add(daySpan(week.getFullYear(), week.getMonth() + 1, week.getDate()), "A week ago");
  const month = new Date(now.getFullYear(), now.getMonth() - 1, now.getDate());
  add(daySpan(month.getFullYear(), month.getMonth() + 1, month.getDate()), "A month ago");
  add(monthSpan(now.getFullYear(), now.getMonth() + 1));
  return out;
}

// ── Filters in the box ─────────────────────────────────────────────────────

export type Person = { name: string; username?: string };

/** "me" for the account's own messages, "them" for the other person's, null for a name that is neither. */
export function whoFrom(value: string, them: Person): Who | null {
  const v = fold(value).replace(/^@/, "");
  if (!v) return null;
  if (["me", "you", "i", "mine", "myself", "moi"].includes(v)) return "me";
  if (["them", "they", "him", "her", "other"].includes(v)) return "them";
  const names = [them.name, them.username ?? ""].map(fold).filter(Boolean);
  return names.some((n) => n.startsWith(v) || n.replace(/\s+/g, "").startsWith(v)) ? "them" : null;
}

export function hasFrom(value: string): HasKind | null {
  const v = fold(value).replace(/s$/, "");
  if (!v) return null;
  const hit = HAS.find((h) => h.id === v || h.words.some((w) => w === v || (v.length >= 3 && w.startsWith(v))));
  return hit?.id ?? null;
}

/** One complete filter, applied; null when the value does not make sense for its key. */
export function applyToken(f: Filters, key: string, value: string, them: Person): Filters | null {
  const k = key.toLowerCase() === "on" ? "during" : key.toLowerCase();
  if (k === "from") {
    const who = whoFrom(value, them);
    return who ? { ...f, from: who } : null;
  }
  if (k === "has") {
    const h = hasFrom(value);
    return h ? { ...f, has: f.has.includes(h) ? f.has : [...f.has, h] } : null;
  }
  if (k === "before" || k === "after" || k === "during") {
    const span = parseSpan(value.replace(/^"|"$/g, ""));
    if (!span) return null;
    return { ...f, dates: [...f.dates.filter((d) => d.kind !== k), { kind: k, ...span }] };
  }
  return null;
}

/**
 * Takes the complete filters out of what was typed, into the chips. Complete
 * means a space came after it, or `all` (Enter was pressed). A filter that
 * does not make sense stays in the box as words, so nothing typed is lost.
 */
export function takeFilters(text: string, f: Filters, them: Person, all = false): { text: string; filters: Filters; took: number } {
  let filters = f;
  let took = 0;
  const re = all
    ? /(^|\s)(from|has|before|after|during|on):("[^"]*"|\S+)(?=\s|$)/gi
    : /(^|\s)(from|has|before|after|during|on):("[^"]*"|\S+)(?=\s)/gi;
  const rest = text.replace(re, (whole, lead, key, value) => {
    const next = applyToken(filters, key, value, them);
    if (!next) return whole;
    filters = next;
    took++;
    return lead;
  });
  return { text: took ? rest.replace(/\s{2,}/g, " ").replace(/^\s+/, "") : text, filters, took };
}

/** What the server's routes take, from the words and the chips. */
export function toQuery(text: string, f: Filters): Query {
  let before: number | null = null;
  let after: number | null = null;
  for (const d of f.dates) {
    const b = d.kind === "before" ? d.start : d.kind === "during" ? d.end : null;
    const a = d.kind === "after" ? d.end : d.kind === "during" ? d.start : null;
    if (b !== null) before = before === null ? b : Math.min(before, b);
    if (a !== null) after = after === null ? a : Math.max(after, a);
  }
  return { words: splitWords(text), mine: f.from === null ? null : f.from === "me", has: [...f.has], before, after };
}

export const isEmpty = (q: Query) =>
  !q.words.length && q.mine === null && !q.has.length && q.before === null && q.after === null;

/** A chip's words: "From: you", "Has: picture", "Before: 30 Sep 2026". */
export function chipLabel(kind: "from" | HasKind | DateKind, value: string): string {
  return `${kind[0].toUpperCase()}${kind.slice(1)}: ${value}`;
}

/** The token being typed at the caret: the key, and what is typed after its colon, if any. */
export function tokenAt(text: string, caret: number): { start: number; end: number; key: string; value: string | null } {
  let start = caret;
  while (start > 0 && !/\s/.test(text[start - 1])) start--;
  let end = caret;
  while (end < text.length && !/\s/.test(text[end])) end++;
  const word = text.slice(start, caret);
  const colon = word.indexOf(":");
  return colon < 0
    ? { start, end, key: word, value: null }
    : { start, end, key: word.slice(0, colon), value: word.slice(colon + 1) };
}

// ── Remembered searches ────────────────────────────────────────────────────

export type Recent = { text: string; filters: Filters; at: number };
const RECENT_KEY = "chats.recentSearches";

export function recentSearches(): Recent[] {
  try {
    const list = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(list) ? list.filter((r) => r && typeof r.text === "string" && r.filters).slice(0, 6) : [];
  } catch {
    return [];
  }
}

export function rememberSearch(text: string, filters: Filters) {
  const t = text.trim();
  if (!t && !filters.from && !filters.has.length && !filters.dates.length) return;
  const key = JSON.stringify([t, filters]);
  const list = recentSearches().filter((r) => JSON.stringify([r.text, r.filters]) !== key);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify([{ text: t, filters, at: Date.now() }, ...list].slice(0, 6)));
  } catch {
    /* only a convenience */
  }
}

export function forgetSearches() {
  try {
    localStorage.removeItem(RECENT_KEY);
  } catch {
    /* only a convenience */
  }
}

// ── Links ──────────────────────────────────────────────────────────────────

/** "youtube.com" from a link, without the www. */
export function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** A link as a person would say it: its domain and path, without the scheme or a trailing slash. */
export function prettyUrl(url: string): string {
  try {
    const u = new URL(url);
    const path = decodeURIComponent(u.pathname + u.search).replace(/\/$/, "");
    return u.hostname.replace(/^www\./, "") + (path && path !== "/" ? path : "");
  } catch {
    return url;
  }
}
