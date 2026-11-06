/**
 * Community profiles, the parts with no page in them: sorting and searching the catalog, counts as people say them,
 * which of yours has a newer version, and short names made the way the Python side makes them. Pure, so
 * tests/community_logic.mjs runs it under Node.
 */

export type CommunityProfile = {
  slug: string;
  name: string;
  tagline: string;
  description?: string;
  tags: string[];
  color: string;
  author: string;
  adult: boolean;
  language?: string;
  version: number;
  /** The app version it was sent from ("" when unknown). */
  app?: string;
  created?: string;
  updated?: string;
  words?: number;
  settings?: number;
  pictures?: number;
  videos?: number;
  downloads: number;
  week: number;
  avatar: string;
  thumbs?: string[];
};

export type Installed = Record<string, { pid: string; version: number }>;

export type CommunityHome = {
  state: "ok" | "offline" | "closed" | string;
  fetched: number;
  index: { profiles: CommunityProfile[]; totals: { profiles: number; downloads: number; week: number } };
  meta: { tags?: string[]; submissions_open?: boolean; settings?: string[] };
  me: { signed_in: boolean; login: string; id: number; avatar: string };
  moderator: boolean;
  installed: Installed;
  shared: Installed;
  sharing: boolean;
  repo: string;
  /** Your app's version ("" for a development build). */
  app?: string;
};

export const EMPTY_HOME: CommunityHome = {
  state: "ok", fetched: 0, index: { profiles: [], totals: { profiles: 0, downloads: 0, week: 0 } }, meta: {},
  me: { signed_in: false, login: "", id: 0, avatar: "" }, moderator: false, installed: {}, shared: {}, sharing: false,
  repo: "", app: "",
};

export type AppFit = "same" | "older" | "newer" | "";

/** Whether a profile was made for the app you have, by major and minor version (a fix release adds no settings).
 *  "" when either isn't known: a development build, or a profile from before the app version was kept. */
export function appFit(made: string | undefined, yours: string | undefined): AppFit {
  const parts = (v?: string) => {
    const m = /^v?(\d+)\.(\d+)/.exec(String(v ?? "").trim());
    return m ? [Number(m[1]), Number(m[2])] : null;
  };
  const a = parts(made);
  const b = parts(yours);
  if (!a || !b) return "";
  const d = a[0] - b[0] || a[1] - b[1];
  return d === 0 ? "same" : d < 0 ? "older" : "newer";
}

/** What's said beside a profile's version: a word or two on its card, a sentence where you look inside it. */
export function appWords(made: string | undefined, yours: string | undefined):
    { short: string; long: string; tone: "good" | "warn" | "info" | "" } {
  const fit = appFit(made, yours);
  if (fit === "same") return { short: "up to date", long: `Made for your app (${made}).`, tone: "good" };
  if (fit === "older") {
    return { short: "older app", tone: "warn",
             long: `Made with app ${made}, older than yours (${yours}). Settings added since aren't in it.` };
  }
  if (fit === "newer") {
    return { short: "newer app", tone: "info",
             long: `Made with app ${made}, newer than yours (${yours}). Update yours to get all of it.` };
  }
  return { short: "", long: made ? `Made with app ${made}.` : "", tone: "" };
}

export type Sort = "popular" | "new" | "trending";

/** Most downloaded, newest, or most downloaded this week; ties by name. */
export function sortProfiles(list: CommunityProfile[], sort: Sort): CommunityProfile[] {
  const byName = (a: CommunityProfile, b: CommunityProfile) => a.name.localeCompare(b.name);
  const out = [...list];
  if (sort === "new") out.sort((a, b) => String(b.created ?? "").localeCompare(String(a.created ?? "")) || byName(a, b));
  else if (sort === "trending") out.sort((a, b) => b.week - a.week || b.downloads - a.downloads || byName(a, b));
  else out.sort((a, b) => b.downloads - a.downloads || b.week - a.week || byName(a, b));
  return out;
}

/** Without accents, lower case: "Héloïse" finds "heloise". */
export function fold(s: string): string {
  return String(s ?? "").normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
}

export function matches(p: CommunityProfile, q: string): boolean {
  const words = fold(q).split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const hay = fold([p.name, p.tagline, p.author, p.description ?? "", ...(p.tags ?? [])].join(" "));
  return words.every((w) => hay.includes(w));
}

/** The catalog as shown: searched, by tags (all of them), 18+ only when asked for. */
export function filterProfiles(list: CommunityProfile[], o: { q?: string; tags?: string[]; adult?: boolean }): CommunityProfile[] {
  const tags = o.tags ?? [];
  return list.filter((p) => (o.adult || !p.adult) && matches(p, o.q ?? "") && tags.every((t) => (p.tags ?? []).includes(t)));
}

/** A count as people say it: 999, 1.2K, 46K, 1.3M. */
export function compact(n: number): string {
  const v = Math.max(0, Math.round(Number(n) || 0));
  if (v < 1000) return String(v);
  if (v < 10_000) return `${(v / 1000).toFixed(1).replace(/\.0$/, "")}K`;
  if (v < 1_000_000) return `${Math.round(v / 1000)}K`;
  return `${(v / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

export function plural(n: number, one: string, many: string): string {
  return `${compact(n)} ${Math.round(n) === 1 ? one : many}`;
}

/** Whether you have it, and whether there is a newer version than yours. */
export function installState(p: CommunityProfile, installed: Installed): "none" | "installed" | "update" {
  const have = installed[p.slug];
  if (!have) return "none";
  return have.version < p.version ? "update" : "installed";
}

/** A profile of yours that came from the community, and the newer version waiting for it, if any. */
export function updateFor(persona: { community?: { slug: string; version: number } | null }, profiles: CommunityProfile[]):
  { slug: string; to: number } | null {
  const c = persona.community;
  if (!c) return null;
  const p = profiles.find((x) => x.slug === c.slug);
  return p && p.version > c.version ? { slug: c.slug, to: p.version } : null;
}

/** "today", "yesterday", "3 days ago", "2 weeks ago", "in March". */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const days = Math.floor((now - t) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 14) return `${days} days ago`;
  if (days < 60) return `${Math.floor(days / 7)} weeks ago`;
  return `in ${new Date(t).toLocaleString("en", { month: "long" })}`;
}

/** A short name from a name, exactly as app/utils/community_rules.py slug_from() makes it. */
export function slugFrom(name: string): string {
  let s = String(name ?? "").normalize("NFKD").replace(/[^\x00-\x7f]/g, "").toLowerCase();
  s = s.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  s = s.slice(0, 32).replace(/^-+|-+$/g, "");
  if (s.length < 3) s = s ? `${s}-profile` : "profile";
  return s;
}

export const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** What a request you sent is at, in a few words, and its colour. */
export function requestLine(r: { state: string; version?: number; reasons?: string[]; action?: string }):
  { text: string; tone: "good" | "bad" | "muted" | "busy" } {
  if (r.state === "published") return { text: `Live, v${r.version ?? 1}`, tone: "good" };
  if (r.state === "removed") return { text: "Removed", tone: "muted" };
  if (r.state === "refused") return { text: `Refused: ${(r.reasons ?? [])[0] ?? "it didn't pass the checks"}`, tone: "bad" };
  if (r.state === "error") return { text: "Something went wrong on GitHub", tone: "bad" };
  return { text: r.action === "remove" ? "Removing" : "Checking", tone: "busy" };
}

/** File sizes as people say them. */
export function sizeText(bytes: number): string {
  const b = Math.max(0, Number(bytes) || 0);
  if (b < 1000) return `${b} B`;
  if (b < 1_000_000) return `${Math.round(b / 1000)} KB`;
  return `${(b / 1_000_000).toFixed(b < 10_000_000 ? 1 : 0)} MB`;
}

/** The last n days of a daily series, each with its date for a tooltip. */
export function lastDays(daily: number[], days: string[], n = 30): { v: number; day: string }[] {
  const d = daily.slice(-n);
  const names = days.slice(-d.length);
  return d.map((v, i) => ({ v: Math.max(0, v), day: names[i] ?? "" }));
}

/** What the scanner found, as a person would say it. */
export function riskLabel(kind: string): string {
  return ({
    invite: "An invite or social link", link: "A link", email: "An email address", money: "Payment or money",
    secret: "Passwords or codes", phone: "A phone number", id: "A long number like an account id",
    handle: "An @handle", yours: "One of your own usernames",
  } as Record<string, string>)[kind] ?? "Something to check";
}

/** A setting's value, short enough for a row. */
export function valueText(v: unknown): string {
  if (v === null || v === undefined) return "Default";
  if (typeof v === "boolean") return v ? "On" : "Off";
  if (Array.isArray(v)) return v.length ? v.map((x) => valueText(x)).join(", ") : "None";
  if (typeof v === "object") {
    const n = Object.keys(v as object).length;
    return `${n} ${n === 1 ? "entry" : "entries"}`;
  }
  return String(v);
}
