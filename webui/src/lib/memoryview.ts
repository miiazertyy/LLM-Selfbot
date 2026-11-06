/**
 * Memory's people, put in order, narrowed down and searched (pages/Memory.svelte). Apart from the page so it runs
 * under Node as it is (tests/memoryview_logic.mjs).
 *
 * The order and the filters are kept (lib/stores.ts memoryView), so the list comes back the way it was left. What is
 * typed in the search box is not: a search is for now.
 *
 * The search goes word by word, and every word has to be found somewhere: in the name, the id or a fact, so
 * "paris 17" finds whoever lives in Paris and is 17. A word with a colon looks in one kind of fact only: "city:paris",
 * or "pet:" for anyone with a pet written down. Found in a fact and not in the name, the row says which fact, so you
 * can see why someone is there.
 */
import { platformOf, platformOfUser, type PlatformId } from "./platforms";

export type Person = {
  user_id: string;
  username?: string;
  display_name?: string;
  facts: Record<string, string>;
  persona?: string;
  messages?: number;
  first_seen?: number;
  last_seen?: number;
  fact_count?: number;
  platform?: string;
  same_as?: string[];
  learned_at?: number;
};

export const SORTS = [
  { id: "recent", label: "Most recent", icon: "clock" },
  { id: "oldest", label: "Oldest", icon: "calendar" },
  { id: "facts", label: "Most remembered", icon: "memory" },
  { id: "fewest", label: "Least remembered", icon: "memory" },
  { id: "messages", label: "Most messages", icon: "chats" },
  { id: "learned", label: "Just learned", icon: "sparkle" },
  { id: "newest", label: "Newest", icon: "userPlus" },
  { id: "longest", label: "Known longest", icon: "heart" },
  { id: "name", label: "A to Z", icon: "type" },
] as const;
export type SortId = (typeof SORTS)[number]["id"];

/** When they last talked to it. One of these. */
export const TALKED = [
  { id: "any", label: "Any time" },
  { id: "today", label: "Today" },
  { id: "week", label: "This week" },
  { id: "month", label: "This month" },
  { id: "older", label: "Older" },
] as const;
export type TalkedId = (typeof TALKED)[number]["id"];

/** Narrowing it down further. Any number of these, each one more to meet. */
export const ONLY = [
  { id: "learned", label: "Learned today", icon: "sparkle" },
  { id: "several", label: "2+ facts", icon: "memory" },
  { id: "tone", label: "Own tone", icon: "persona" },
  { id: "linked", label: "Linked", icon: "link" },
] as const;
export type OnlyId = (typeof ONLY)[number]["id"];

export type View = { sort: SortId; talked: TalkedId; on: PlatformId[]; only: OnlyId[] };
export const DEFAULT_VIEW: View = { sort: "recent", talked: "any", on: [], only: [] };

const DAY = 86_400;
const isIn = <T extends { id: string }>(list: readonly T[], id: unknown): id is T["id"] =>
  typeof id === "string" && list.some((x) => x.id === id);

/** A stored view mended: what a build that knew other choices left there is dropped, and the rest kept. */
export function mend(raw: unknown): View {
  const v = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const ids = (list: unknown) => (Array.isArray(list) ? list.filter((x): x is string => typeof x === "string") : []);
  return {
    sort: isIn(SORTS, v.sort) ? v.sort : DEFAULT_VIEW.sort,
    talked: isIn(TALKED, v.talked) ? v.talked : DEFAULT_VIEW.talked,
    on: [...new Set(ids(v.on).filter((id) => platformOf(id).id === id))] as PlatformId[],
    only: [...new Set(ids(v.only).filter((id) => isIn(ONLY, id)))] as OnlyId[],
  };
}

/** Which platform someone is on: what the list says, or what their id says. */
export const platformIdOf = (p: Person): PlatformId => (p.platform ? platformOf(p.platform).id : platformOfUser(p.user_id).id);

/** How many filters are on. The order is not one: it hides nobody. */
export const filtersOn = (v: View, present: readonly string[] = []): number =>
  (v.talked !== "any" ? 1 : 0) + v.on.filter((id) => !present.length || present.includes(id)).length + v.only.length;

/** Local midnight, in seconds: "today" is the day on the clock, not the last 24 hours. */
function midnight(now: number): number {
  const d = new Date(now * 1000);
  d.setHours(0, 0, 0, 0);
  return d.getTime() / 1000;
}

function talkedFits(p: Person, talked: TalkedId, now: number): boolean {
  const at = p.last_seen ?? 0;
  if (talked === "today") return at >= midnight(now);
  if (talked === "week") return at >= now - 7 * DAY;
  if (talked === "month") return at >= now - 30 * DAY;
  // Never heard from, as far as the app knows, counts as long ago.
  if (talked === "older") return at < now - 30 * DAY;
  return true;
}

function onlyFits(p: Person, only: OnlyId, now: number): boolean {
  if (only === "learned") return (p.learned_at ?? 0) >= midnight(now);
  if (only === "several") return (p.fact_count ?? 0) >= 2;
  if (only === "tone") return !!(p.persona ?? "").trim();
  return (p.same_as ?? []).length > 0;
}

// ── The search ────────────────────────────────────────────────────────────────────────────────────────────────────

/** One word of a search: looked for anywhere, or ("city:paris") in the facts whose name has `key` in it. */
export type Term = { word: string; key?: string };

export function terms(query: string): Term[] {
  const out: Term[] = [];
  for (const raw of query.toLowerCase().split(/\s+/)) {
    if (!raw) continue;
    const at = raw.indexOf(":");
    // "city:paris" and "pet:" look in facts by their name. A colon at the very start is just a character.
    if (at > 0) out.push({ key: raw.slice(0, at).replace(/_/g, " "), word: raw.slice(at + 1) });
    else out.push({ word: raw });
  }
  return out;
}

/** What a search found someone by: their name or id, or which fact. */
export type Match = { fact?: { key: string; value: string } };

const factKey = (k: string) => k.toLowerCase().replace(/_/g, " ");

/** Whether every word is found somewhere about them, and if one was only in a fact, that fact. Null when not. */
export function matchOf(p: Person, name: string, words: readonly Term[]): Match | null {
  if (!words.length) return {};
  const who = `${name} ${p.username ?? ""} ${p.display_name ?? ""}`.toLowerCase();
  const facts = Object.entries(p.facts ?? {}).map(([k, v]) => [k, String(v)] as const);
  let shown: Match["fact"];
  for (const t of words) {
    if (t.key !== undefined) {
      const hit = facts.find(([k, v]) => factKey(k).includes(t.key!) && v.toLowerCase().includes(t.word));
      if (!hit) return null;
      shown ??= { key: hit[0], value: hit[1] };
      continue;
    }
    if (who.includes(t.word) || p.user_id.toLowerCase().includes(t.word)) continue;
    const hit = facts.find(([k, v]) => factKey(k).includes(t.word) || v.toLowerCase().includes(t.word));
    if (!hit) return null;
    shown ??= { key: hit[0], value: hit[1] };
  }
  return shown ? { fact: shown } : {};
}

/** A line cut where the search's words are in it, to light them: [text, lit] pieces, in order. */
export function marks(text: string, words: readonly Term[]): [string, boolean][] {
  const low = text.toLowerCase();
  const spans: [number, number][] = [];
  for (const t of words) {
    if (!t.word) continue;
    for (let i = low.indexOf(t.word); i >= 0; i = low.indexOf(t.word, i + 1)) spans.push([i, i + t.word.length]);
  }
  if (!spans.length) return [[text, false]];
  spans.sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const s of spans) {
    const last = merged[merged.length - 1];
    if (last && s[0] <= last[1]) last[1] = Math.max(last[1], s[1]);
    else merged.push([...s]);
  }
  const out: [string, boolean][] = [];
  let at = 0;
  for (const [a, b] of merged) {
    if (a > at) out.push([text.slice(at, a), false]);
    out.push([text.slice(a, b), true]);
    at = b;
  }
  if (at < text.length) out.push([text.slice(at), false]);
  return out;
}

// ── All of it ─────────────────────────────────────────────────────────────────────────────────────────────────────

const byNewest = (a?: number, b?: number) => (b ?? 0) - (a ?? 0);
/** Oldest first, with times nobody knows at the end rather than looking oldest of all. */
const byOldest = (a?: number, b?: number) => (a || Infinity) - (b || Infinity);

function compare(sort: SortId, nameOf: (p: Person) => string): (a: Person, b: Person) => number {
  switch (sort) {
    case "oldest": return (a, b) => byOldest(a.last_seen, b.last_seen);
    case "facts": return (a, b) => (b.fact_count ?? 0) - (a.fact_count ?? 0) || byNewest(a.last_seen, b.last_seen);
    case "fewest": return (a, b) => (a.fact_count ?? 0) - (b.fact_count ?? 0) || byNewest(a.last_seen, b.last_seen);
    case "messages": return (a, b) => (b.messages ?? 0) - (a.messages ?? 0) || byNewest(a.last_seen, b.last_seen);
    case "learned": return (a, b) => byNewest(a.learned_at, b.learned_at) || byNewest(a.last_seen, b.last_seen);
    case "newest": return (a, b) => byNewest(a.first_seen, b.first_seen);
    case "longest": return (a, b) => byOldest(a.first_seen, b.first_seen);
    case "name": return (a, b) => nameOf(a).localeCompare(nameOf(b), undefined, { sensitivity: "base", numeric: true });
    default: return (a, b) => byNewest(a.last_seen, b.last_seen) || (b.fact_count ?? 0) - (a.fact_count ?? 0);
  }
}

/**
 * The people to show, in order, and what the search found each by. `present` is the platforms anyone in the list is
 * on: a platform kept picked from before, with nobody on it now (or switched off), hides nobody.
 */
export function arrange<T extends Person>(
  people: readonly T[],
  view: View,
  opts: { query?: string; now: number; nameOf: (p: T) => string; present?: readonly string[] },
): { list: T[]; matches: Map<string, Match> } {
  const words = terms(opts.query ?? "");
  const on = new Set(view.on.filter((id) => !opts.present || opts.present.includes(id)));
  const matches = new Map<string, Match>();
  const list: T[] = [];
  for (const p of people) {
    if (on.size && !on.has(platformIdOf(p))) continue;
    if (!talkedFits(p, view.talked, opts.now)) continue;
    if (!view.only.every((o) => onlyFits(p, o, opts.now))) continue;
    const m = matchOf(p, opts.nameOf(p), words);
    if (!m) continue;
    matches.set(p.user_id, m);
    list.push(p);
  }
  // Sorted after narrowing, and stable: people equal in what is sorted by keep the order they came in.
  list.sort(compare(view.sort, opts.nameOf as (p: Person) => string));
  return { list, matches };
}
