/**
 * Global search (Ctrl+K).
 *
 * The palette used to match page titles only, so typing "token" or "typo
 * chance" found nothing. This indexes real content, settings fields, secrets,
 * accounts, memory keys, personas, pictures, log lines - and matches every word
 * in the query against it.
 *
 * Each hit carries enough to be shown properly, not just named: what kind of
 * thing it is, an icon or a picture, where it lives in the panel, and the
 * details the palette's preview shows (a setting's description and value, a
 * person's facts, a log line in full).
 */
import { api } from "./api";
import { PATHS, homeOf, restHomeOf } from "./settingsmap";

export type Kind = "page" | "action" | "setting" | "secret" | "account" | "person" | "persona" | "picture" | "log";

export type Hit = {
  route: string;        // page to open
  title: string;        // primary line
  subtitle?: string;    // secondary line
  group: string;        // which tab of the palette it is under
  score: number;
  kind: Kind;
  icon?: string;        // an icon name, where there is no picture
  image?: string;       // a face or a thumbnail
  where?: string;       // where it lives: "AI behaviour · Typing"
  detail?: string;      // a sentence about it, for the preview
  value?: string;       // a setting's current value, in words
  facts?: [string, string][];
  level?: string;       // a log line's level
  time?: string;        // a log line's time
  action?: () => void;  // optional: run instead of navigating
  section?: string;     // where in Settings to land, for a settings hit; which persona, for a persona
};

/** Something the palette can do rather than open, given by the palette itself. */
export type PaletteAction = { title: string; subtitle?: string; icon: string; words?: string; run: () => void };

type Doc = Omit<Hit, "score"> & { hay: string; titleHay: string };

/** The words a page answers to beyond its name: logins are looked for as "token" or "proxy". */
const PAGE_WORDS: Record<string, string> = {
  accounts: "tokens token proxies proxy logins login passwords password discord snapchat add account",
  profiles: "profiles profile instances instance personas bots running new profile",
  persona: "trigger triggers names name nicknames answers to moods reactions openers instructions",
};

/** What each page is for, in a line, for the preview. */
const PAGE_BLURB: Record<string, string> = {
  dashboard: "Replies today, charts and the live log.",
  accounts: "Add, start and stop the Discord and Snapchat accounts.",
  profiles: "Each profile is its own bot: which are running, on which accounts.",
  chats: "Who is waiting on a reply, and answering them.",
  persona: "Who the bot is, its moods and how it reacts.",
  memory: "What it remembers about each person.",
  pictures: "The pictures it can send, and what they show.",
  logs: "Everything that happened, live.",
  settings: "Every option, by subject.",
  system: "Updates, backups and the dependency doctor.",
  bigpicture: "Everything live, on one screen.",
};

/** A login, kept per account and edited on the Accounts page rather than in Settings. */
const ACCOUNT_KEY = /^(DISCORD_(TOKEN|PROXY)|SNAP_(USERNAME|PASSWORD))(_\d+)?$/;

let docs: Doc[] = [];
let built = 0;

const norm = (s: unknown) => String(s ?? "").toLowerCase();

/** How many of each group browsing offers before you have to type. */
const BROWSE_PER_GROUP = 24;

/* Regex-escaping for user-typed query words, shared by search() and
   highlight() so neither rebuilds the pattern per call. */
const ESCAPE_RE = /[.*+?^${}()|[\]\\]/g;
const ESCAPE_TO = "\\$&";
const BOUND_PREFIX = "\\b";

function add(list: Doc[], d: Omit<Doc, "hay" | "titleHay">, ...extra: unknown[]) {
  list.push({
    ...d,
    hay: norm([d.title, d.subtitle, d.group, ...extra].join(" ")),
    titleHay: norm(d.title),
  });
}

/** "AI behaviour · Typing" for a setting's key. */
function whereIs(key: string): string {
  const p = homeOf(key) ?? restHomeOf(key);
  const hit = PATHS.find((x) => x.path === p);
  return hit ? `${hit.tab.name} · ${hit.sub.name}` : "";
}

/** A setting's value, short enough for a line. */
function valueOf(v: unknown): string {
  if (v === null || v === undefined || v === "") return "Not set";
  if (typeof v === "boolean") return v ? "On" : "Off";
  if (Array.isArray(v)) return v.length === 1 ? "1 item" : `${v.length} items`;
  if (typeof v === "object") return `${Object.keys(v as object).length} entries`;
  const s = String(v);
  return s.length > 48 ? `${s.slice(0, 47)}…` : s;
}

/** Pull everything searchable. Cheap enough to refresh whenever the palette opens. */
export async function buildIndex(
  routes: Record<string, { title: string; section: string; icon?: string }>,
  actions: PaletteAction[] = [],
): Promise<void> {
  const list: Doc[] = [];

  for (const [key, r] of Object.entries(routes)) {
    add(list, { route: key, title: r.title, subtitle: r.section, group: "Pages", kind: "page", icon: r.icon ?? "command",
                detail: PAGE_BLURB[key] }, r.section, PAGE_WORDS[key] ?? "");
  }
  // Not a page: the whole-screen view, opened from the palette like one.
  add(list, { route: "bigpicture", title: "Big Picture Mode", subtitle: "Full screen", group: "Pages", kind: "page",
              icon: "bigpicture", detail: PAGE_BLURB.bigpicture },
    "cinematic fullscreen jarvis live watch big picture tv mode");

  for (const a of actions) {
    add(list, { route: "", title: a.title, subtitle: a.subtitle, group: "Actions", kind: "action", icon: a.icon,
                action: a.run, detail: a.subtitle }, a.words ?? "");
  }

  const settle = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null);
  const [schema, secrets, accounts, memory, pictures, logs, personas] = await Promise.all([
    settle(api.schema()),
    settle(api.secrets()),
    settle(api.accounts()),
    settle(api.memory()),
    settle(api.pictures()),
    settle(api.logs(400)),
    settle(api.personas()),
  ]);

  // The profiles: opened on Profiles, and picked there for Persona, Memory and Pictures.
  for (const p of (personas as any)?.personas ?? []) {
    const n = p.accounts?.length ?? 0;
    add(
      list,
      { route: "profiles", title: p.name, subtitle: p.line || (p.is_default ? "Default profile" : "Profile"),
        group: "Profiles", kind: "persona", image: p.avatar || undefined, icon: "layers", where: "Profiles", section: p.id,
        detail: n ? `On ${n} account${n === 1 ? "" : "s"}.` : "No accounts yet." },
      p.id, p.line, "profile persona instance character who",
    );
  }

  for (const f of (schema as any)?.fields ?? []) {
    add(
      list,
      {
        route: "settings",
        title: f.label ?? f.key,
        subtitle: f.description || f.key,
        group: "Settings",
        kind: "setting",
        icon: "settings",
        section: f.key,
        where: whereIs(f.key),
        detail: f.description,
        value: valueOf(f.current),
      },
      f.key, f.section, f.current,
    );
  }

  for (const key of Object.keys((secrets as any)?.secrets ?? {})) {
    add(list, ACCOUNT_KEY.test(key)
      ? { route: "accounts", title: key, subtitle: "Account login, on Accounts", group: "Secrets", kind: "secret", icon: "accounts",
          where: "Accounts", detail: "A login, kept with its account on the Accounts page." }
      : { route: "settings", title: key, subtitle: "Secret / .env", group: "Secrets", kind: "secret", icon: "system",
          section: "app/env", where: "App · Keys and secrets", detail: "Kept in the .env file, never shown in full." });
  }

  for (const a of (accounts as any)?.accounts ?? []) {
    const name = a.display_name || a.username || a.label || a.id;
    const platform = a.platform === "snapchat" ? "Snapchat" : "Discord";
    add(
      list,
      { route: "accounts", title: name, subtitle: `${platform} #${a.account ?? ""} · ${a.state ?? ""}`.replace(/ · $/, ""),
        group: "Accounts", kind: "account", image: a.avatar || undefined, icon: a.platform === "snapchat" ? "snapchat" : "discord",
        where: "Accounts", detail: a.username ? `@${a.username}` : undefined },
      a.id, a.pid, a.username, a.label,
    );
  }

  const mem = (memory as any)?.users ?? (memory as any)?.memory ?? [];
  for (const u of Array.isArray(mem) ? mem : []) {
    const facts: Record<string, string> = u.facts ?? u.memory ?? {};
    const name = u.display_name || u.name || u.username || String(u.id ?? u.user_id);
    const n = Object.keys(facts).length;
    add(
      list,
      { route: "memory", title: name, subtitle: n ? `${n} thing${n === 1 ? "" : "s"} remembered` : "Nothing remembered yet",
        group: "People", kind: "person", image: u.avatar || undefined, icon: "memory", where: "Memory",
        facts: Object.entries(facts).slice(0, 8).map(([k, v]) => [k.replace(/_/g, " "), String(v)] as [string, string]),
        detail: u.messages ? `${u.messages} messages` : undefined },
      u.id, u.user_id, u.username, JSON.stringify(facts),
    );
  }

  for (const p of (pictures as any)?.pictures ?? []) {
    add(list, { route: "pictures", title: p.name, subtitle: p.description || "No description yet", group: "Pictures",
                kind: "picture", image: api.pictureThumb({ name: String(p.name), id: String(p.id ?? ""), video: !!p.video }),
                icon: "pictures", where: "Pictures",
                detail: p.description || "No description yet." }, p.description);
  }

  const lines = (logs as any)?.lines ?? (logs as any)?.logs ?? [];
  for (const l of Array.isArray(lines) ? lines.slice(-250).reverse() : []) {
    const level = String(l.level || "info");
    add(
      list,
      { route: "logs", title: l.text ?? "", subtitle: `${l.time ?? ""} · ${l.source ?? ""}`.replace(/^ · | · $/g, ""),
        group: "Logs", kind: "log", icon: level === "error" ? "alertCircle" : level === "warn" ? "alert" : "logs",
        where: "Logs", level, time: l.time, detail: l.text },
      l.source, l.level,
    );
  }

  docs = list;
  built = Date.now();
}

export function indexAge(): number {
  return built ? Date.now() - built : Infinity;
}

const strip = ({ hay: _h, titleHay: _t, ...hit }: Doc, score: number): Hit => ({ ...hit, score });

/**
 * Every word in the query must appear somewhere in the document.
 *
 * With nothing typed it is a browsable index instead: the first few of each
 * group, pages first.
 */
export function search(query: string, limit = 40): Hit[] {
  const words = norm(query).split(/\s+/).filter(Boolean);
  if (!words.length) {
    // Capped per group, since the index holds 250 log lines and every settings
    // field, and rendering all of it to sit unseen is pure waste.
    const perGroup: Record<string, number> = {};
    const out: Hit[] = [];
    for (const d of docs) {
      const n = (perGroup[d.group] = (perGroup[d.group] ?? 0) + 1);
      if (n > BROWSE_PER_GROUP) continue;
      out.push(strip(d, d.group === "Pages" ? 1 : 0));
    }
    // Pages first; it is what the palette is mostly used for.
    return out.sort((a, b) => b.score - a.score);
  }

  // Compiled once for the whole sweep. This built a RegExp per document per
  // word, and the index holds every settings field, secret, account, memory
  // user, picture and 250 log lines - so one character cost hundreds of
  // compilations.
  const bounds = words.map(
    (w) => new RegExp(BOUND_PREFIX + w.replace(ESCAPE_RE, ESCAPE_TO)),
  );

  const hits: Hit[] = [];
  for (const d of docs) {
    let score = 0;
    let all = true;
    for (let wi = 0; wi < words.length; wi++) {
      const w = words[wi];
      const at = d.hay.indexOf(w);
      if (at === -1) {
        all = false;
        break;
      }
      // Earlier and word-boundary matches rank higher; title beats body.
      score += 100 - Math.min(60, at);
      if (d.titleHay.includes(w)) score += 60;
      if (d.titleHay.startsWith(w)) score += 30;
      if (bounds[wi].test(d.hay)) score += 25;
    }
    if (!all) continue;
    if (d.group === "Pages") score += 40;      // navigating is the common case
    if (d.group === "Actions") score += 20;
    if (d.group === "Logs") score -= 30;       // the log matches everything; it goes last
    hits.push(strip(d, score));
  }

  return hits.sort((a, b) => b.score - a.score).slice(0, limit);
}

/** Wrap matched words in <mark> for display. Escapes the input first. */
export function highlight(text: string, query: string): string {
  const esc = String(text ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
  const words = norm(query).split(/\s+/).filter(Boolean);
  if (!words.length) return esc;
  const pattern = words.map((w) => w.replace(ESCAPE_RE, ESCAPE_TO)).join("|");
  return esc.replace(new RegExp(`(${pattern})`, "gi"), "<mark>$1</mark>");
}
