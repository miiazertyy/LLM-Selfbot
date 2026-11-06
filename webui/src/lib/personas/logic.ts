/**
 * Persona profiles in the panel: the plain parts, with no page or store in
 * them, so they can be checked from Node (tests/personas_logic.mjs).
 *
 * A persona is who the bot is: its text, its pictures, what it remembers and
 * its own settings on top of everyone's (app/utils/personas.py). Each account
 * is one, Default unless it is given another.
 */


export type Persona = {
  id: string;
  name: string;
  /** Its own colour, "#rrggbb", or "" for the theme's accent. */
  color: string;
  /** A second one, when it has a theme of two: its face and its card run from one to the other. */
  color2?: string;
  is_default: boolean;
  /** Its face for the app's pages, or "". Never put on the account itself. */
  avatar: string;
  /** Who it is in a line, from its text. */
  line: string;
  words: number;
  pictures: number;
  people: number;
  /** How many settings it has of its own. */
  changed: number;
  /** The accounts that speak as it, by web id ("discord_1"). */
  accounts: string[];
  /** Added from the community: which one, and which version. */
  community?: { slug: string; version: number } | null;
  /** Shared to the community by you: as which, and its version there. */
  shared?: { slug: string; version: number } | null;
};

/** Two colours that go together. */
export type PersonaTheme = { id: string; name: string; a: string; b: string };

export type PersonaList = {
  personas: Persona[];
  /** web id -> persona id, for every account set up. */
  accounts: Record<string, string>;
  palette: { id: string; name: string; hex: string }[];
  themes: PersonaTheme[];
};

export const EMPTY: PersonaList = { personas: [], accounts: {}, palette: [], themes: [] };

/** The colour a persona is drawn in: its own, else the theme's accent. */
export function colorOf(p?: { color?: string } | null): string {
  return p?.color || "var(--color-accent)";
}

/** An account as people say it: "Discord #1", "Snapchat #2", "Instagram #1". */
export function accountLabel(webId: string): string {
  const m = /^(discord|snapchat|tiktok|instagram|x|reddit|whatsapp|minecraft|imessage|telegram)_(\d+)$/.exec(webId || "");
  if (!m) return webId;
  // Named here rather than taken from platforms.ts: this file is the plain parts, and nothing else is imported.
  const NAMES: Record<string, string> = { discord: "Discord", snapchat: "Snapchat", tiktok: "TikTok",
                                          instagram: "Instagram", x: "X", reddit: "Reddit",
                                          whatsapp: "WhatsApp", minecraft: "Minecraft", imessage: "iMessage",
                                          telegram: "Telegram" };
  return `${NAMES[m[1]]} #${m[2]}`;
}

/** Accounts in the order people count them: one platform at a time, each by number (10 after 9, not after 1). */
export function byAccount(a: string, b: string): number {
  const x = /^(\w+?)_(\d+)$/.exec(a), y = /^(\w+?)_(\d+)$/.exec(b);
  if (!x || !y) return a.localeCompare(b);
  return x[1] === y[1] ? Number(x[2]) - Number(y[2]) : x[1].localeCompare(y[1]);
}

/** The list once an account is given to a persona: off the one it was on, onto this one, in order. */
export function withAccount(list: PersonaList, webId: string, pid: string): PersonaList {
  return {
    ...list,
    accounts: { ...list.accounts, [webId]: pid },
    personas: list.personas.map((p) => {
      const rest = p.accounts.filter((a) => a !== webId);
      return { ...p, accounts: p.id === pid ? [...rest, webId].sort(byAccount) : rest };
    }),
  };
}

/**
 * What a profile is doing, from its accounts: how many there are, how many are up and replying, and what one that
 * runs but is not up yet says ("Starting", "Paused", "Log in").
 */
export function runningLine(total: number, live: number, other = ""): { text: string; tone: "good" | "warn" | "muted" } {
  if (!total) return { text: "No accounts yet", tone: "muted" };
  if (live) return { text: live === total ? (total === 1 ? "Running" : `Running on all ${total}`) : `Running on ${live} of ${total}`,
                     tone: "good" };
  if (other) return { text: other, tone: "warn" };
  return { text: "Not running", tone: "muted" };
}

/** The persona an account speaks as: the one it was given, else Default. */
export function personaOf(list: PersonaList, webId: string): Persona | undefined {
  const pid = list.accounts[webId] || "default";
  return list.personas.find((p) => p.id === pid) ?? list.personas.find((p) => p.is_default);
}

/** The one to show once one is deleted: the one before it, else the first. */
export function afterDelete(list: Persona[], removed: string): string {
  const i = list.findIndex((p) => p.id === removed);
  const rest = list.filter((p) => p.id !== removed);
  return (rest[Math.max(0, i - 1)] ?? rest[0])?.id ?? "default";
}

/** Letters for a persona with no face: the first of up to two words. */
export function monogram(name: string): string {
  const words = (name || "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  const letters = words.length > 1 ? words[0][0] + words[1][0] : words[0].slice(0, 1);
  return letters.toUpperCase();
}

/** A list as it is said: "a", "a and b", "a, b and c". */
export function joinAnd(items: string[]): string {
  if (items.length < 2) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** Its own settings, said shortly. */
export function changedLine(n: number): string {
  if (!n) return "Same as everyone";
  return n === 1 ? "1 setting of its own" : `${n} settings of its own`;
}

/** The next colour no persona has yet, from the palette; the first again once all are taken. */
export function nextColor(list: Persona[], palette: { hex: string }[]): string {
  const used = new Set(list.map((p) => p.color));
  return (palette.find((c) => !used.has(c.hex)) ?? palette[list.length % Math.max(1, palette.length)])?.hex ?? "";
}

/** Colours in the order of the rainbow, the ones with next to no colour in them at the end, lightest first. */
export function byHue<T extends { hex: string }>(palette: T[]): T[] {
  const hsl = (hex: string) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
    const hi = Math.max(r, g, b), lo = Math.min(r, g, b), d = hi - lo;
    const l = (hi + lo) / 2;
    if (!d) return { h: 0, s: 0, l };
    const h = hi === r ? ((g - b) / d + 6) % 6 : hi === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return { h: h * 60, s: d / (1 - Math.abs(2 * l - 1)), l };
  };
  const pale = (c: { s: number }) => c.s < 0.33;
  return [...palette].sort((a, b) => {
    const x = hsl(a.hex), y = hsl(b.hex);
    if (pale(x) !== pale(y)) return pale(x) ? 1 : -1;
    return pale(x) ? y.l - x.l : x.h - y.h;
  });
}

/** A value for people: a list as its items, a table as its size, a switch as On or Off. */
export function shortValue(v: unknown): string {
  if (v === true) return "On";
  if (v === false) return "Off";
  if (v === null || v === undefined || v === "") return "None";
  if (Array.isArray(v)) return v.length ? v.slice(0, 3).map((x) => shortValue(x)).join(", ") + (v.length > 3 ? ` +${v.length - 3}` : "") : "None";
  if (typeof v === "object") {
    const n = Object.keys(v as object).length;
    return n === 1 ? "1 item" : `${n} items`;
  }
  const s = String(v);
  return s.length > 28 ? `${s.slice(0, 27)}…` : s;
}
