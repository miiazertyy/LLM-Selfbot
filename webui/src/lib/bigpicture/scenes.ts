/**
 * What Big Picture's pages need worked out, as plain functions of plain data so
 * they run under Node in tests/bigpicture_director.mjs.
 *
 *   PAGE           what each tab is called, and its icon
 *   personaLines   who the bot is, from the opening of its instructions
 *   personaName    the name it is told it has, when the persona says one
 *   sentPictures   which of its own pictures a sent message carried
 *   untilText      "in 4 min" for a friend request the account will take by itself
 *   ago, agoShort  how long since something, for a sentence or for a tight row
 *   lastDay        the last 24 hours in the order they happened, this hour last
 *   trend          "+20%" against the same stretch before it
 *   mergePeople    everyone every account talks to, once each
 *   runsOf         where a run of messages from one side ends
 *   compact        a big number short: "12k", "1.2M"
 */
import type { Page } from "./director";

/** What each tab is called, and its icon. */
export const PAGE: Record<Page, { label: string; icon: string }> = {
  now: { label: "Now", icon: "bigpicture" },
  people: { label: "People", icon: "memory" },
  accounts: { label: "Accounts", icon: "accounts" },
  today: { label: "Today", icon: "stats" },
  persona: { label: "Persona", icon: "persona" },
  pictures: { label: "Pictures", icon: "pictures" },
  minecraft: { label: "Minecraft", icon: "minecraft" },
  inbox: { label: "Needs you", icon: "alert" },
};

/** A placeholder left in the persona template: [NAME], [AGE], [CITY, COUNTRY]. */
const PLACEHOLDER = /\[[A-Z][A-Z0-9 ,/&'()+-]{1,60}\]/;

/**
 * The persona's opening: who the bot is, in the words it is given.
 *
 * The instructions are one long document, most of it rules about how to write.
 * What is worth putting on a screen is the part that says who: its first
 * paragraph, before the rules start. Comment lines (#) are skipped, and so is
 * a bracketed note to whoever fills it in. A line still holding a placeholder
 * ([NAME]) has not been written yet and is left out; a persona that is all
 * placeholders has nothing to show, and the page says so.
 */
export function personaLines(text: string, max = 7, chars = 460): string[] {
  const out: string[] = [];
  let used = 0;
  let note = false;
  /** Inside the first paragraph: the blank line after it ends the search, even if all of it was placeholders. */
  let started = false;
  for (const raw of (text || "").split(/\r?\n/)) {
    const line = raw.trim();
    if (line.startsWith("#")) continue;
    // A bracketed note runs over several lines: [If anything above ... ]
    if (note) {
      if (line.endsWith("]")) note = false;
      continue;
    }
    if (line.startsWith("[") && !PLACEHOLDER.test(line.slice(0, line.indexOf("]") + 1))) {
      note = !line.endsWith("]");
      continue;
    }
    if (!line) {
      // The first paragraph only: past it the rules begin, which are not who it is.
      if (started) break;
      continue;
    }
    started = true;
    if (PLACEHOLDER.test(line)) continue;
    const cut = line.length > 170 ? `${line.slice(0, 168).trimEnd()}…` : line;
    if (used + cut.length > chars && out.length) break;
    out.push(cut);
    used += cut.length;
    if (out.length >= max) break;
  }
  return out;
}

/** "Your name is Max and you are 19" -> "Max". Empty when the persona does not say. */
export function personaName(lines: string[]): string {
  for (const l of lines) {
    const m = /\b(?:your name is|you are called|you're called|call yourself)\s+([^,.;:!?\n]+?)(?:\s+and\b|[,.;:!?]|$)/i.exec(l);
    if (m) {
      const name = m[1].trim().replace(/^["'“]|["'”]$/g, "");
      if (name && name.length <= 32 && !PLACEHOLDER.test(name)) return name;
    }
  }
  return "";
}

/**
 * The bot's own pictures a sent message carried, by file name. The runner
 * sends a picture as the file itself, so the attachment keeps its name
 * (IMG_3.jpg), which is how the gallery knows which one just went out.
 */
export function sentPictures(attachments: { name?: string }[] | undefined, gallery: string[]): string[] {
  if (!attachments?.length || !gallery.length) return [];
  const have = new Map(gallery.map((g) => [g.toLowerCase(), g]));
  const out: string[] = [];
  for (const a of attachments) {
    const hit = have.get(String(a?.name ?? "").toLowerCase());
    if (hit && !out.includes(hit)) out.push(hit);
  }
  return out;
}

/** How long until something scheduled, said plainly: "in 40 s", "in 4 min", "in 2 h". */
export function untilText(at: number | null | undefined, now: number): string {
  if (!at) return "";
  const s = Math.round(at - now);
  if (s <= 5) return "any moment";
  if (s < 60) return `in ${s} s`;
  if (s < 3600) return `in ${Math.round(s / 60)} min`;
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return m && h < 10 ? `in ${h} h ${m} min` : `in ${h} h`;
}

/** How long since something, for a sentence: "just now", "4 min ago", "2 h ago", "3 d ago". */
export function ago(ts: number | null | undefined, now: number): string {
  if (!ts) return "";
  const s = Math.max(0, now - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

/** The same for a tight row: "now", "12s", "4m", "2h", "3d". */
export function agoShort(ts: number | null | undefined, now: number): string {
  if (!ts) return "";
  const s = Math.max(0, now - ts);
  if (s < 10) return "now";
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

/**
 * The last 24 hours in the order they happened, this hour last. The stats give
 * them by the hour of the day (0 to 23), as a window of one day only has one of each.
 */
export function lastDay(hourly: { hour: number; count: number }[], hourNow: number): { hour: number; count: number }[] {
  const by = new Map(hourly.map((h) => [h.hour, h.count]));
  return Array.from({ length: 24 }, (_, i) => {
    const hour = (hourNow + 1 + i) % 24;
    return { hour, count: by.get(hour) ?? 0 };
  });
}

/** Against the same stretch before it: "+20%", "-5%", or nothing when there is nothing to hold it against. */
export function trend(value: number, before: number): string {
  if (!before) return "";
  const p = Math.round(((value - before) / before) * 100);
  if (!p) return "";
  return `${p > 0 ? "+" : ""}${p}%`;
}

export type PersonLike = { id: string; target: string; name: string; last_ts?: number; messages: number };

/**
 * Everyone every account talks to, once each. Someone two accounts both talk to
 * goes with the one that spoke to them last, which is the conversation that
 * opens. The most recent first.
 */
export function mergePeople<T extends PersonLike>(lists: T[][]): T[] {
  const by = new Map<string, T>();
  for (const list of lists) {
    for (const p of list) {
      const was = by.get(p.id);
      if (!was || (p.last_ts ?? 0) > (was.last_ts ?? 0)) by.set(p.id, p);
    }
  }
  return [...by.values()].sort((a, b) => (b.last_ts ?? 0) - (a.last_ts ?? 0));
}

/**
 * For each message, whether it is the last of a run from one side: the run's
 * one face and one time go there. A long gap starts a new run, even from the
 * same side, as anyone reading them would take it.
 */
export function runsOf(messages: { mine?: boolean; ts?: number }[], gap = 300): boolean[] {
  return messages.map((m, i) => {
    const next = messages[i + 1];
    if (!next) return true;
    return !!next.mine !== !!m.mine || (next.ts ?? 0) - (m.ts ?? 0) > gap;
  });
}

/** A number that has to fit: "12k", "1.2M". The wheels are for what changes, not for six digits. */
export function compact(n: number): string {
  const a = Math.abs(n);
  if (a >= 1e6) return `${(n / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(/\.0$/, "")}M`;
  if (a >= 1e4) return `${Math.round(n / 1e3)}k`;
  return String(Math.round(n));
}
