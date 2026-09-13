/**
 * Global search.
 *
 * The palette used to match page titles only, so typing "token" or "typo
 * chance" found nothing. This indexes real content, settings fields, secrets,
 * accounts, memory keys, personas, pictures, log lines - and matches every word
 * in the query against it.
 */
import { api } from "./api";

export type Hit = {
  route: string;        // page to open
  title: string;        // primary line
  subtitle?: string;    // secondary line
  group: string;        // section heading in the palette
  score: number;
  action?: () => void;  // optional: run instead of navigating
};

type Doc = { route: string; title: string; subtitle?: string; group: string; hay: string };

let docs: Doc[] = [];
let built = 0;

const norm = (s: unknown) => String(s ?? "").toLowerCase();

function add(list: Doc[], d: Omit<Doc, "hay">, ...extra: unknown[]) {
  list.push({ ...d, hay: norm([d.title, d.subtitle, d.group, ...extra].join(" ")) });
}

/** Pull everything searchable. Cheap enough to refresh whenever the palette opens. */
export async function buildIndex(routes: Record<string, { title: string; section: string }>): Promise<void> {
  const list: Doc[] = [];

  for (const [key, r] of Object.entries(routes)) {
    add(list, { route: key, title: r.title, subtitle: "Page", group: "Pages" }, r.section);
  }

  const settle = <T,>(p: Promise<T>): Promise<T | null> => p.catch(() => null);
  const [schema, secrets, accounts, memory, pictures, logs] = await Promise.all([
    settle(api.schema()),
    settle(api.secrets()),
    settle(api.accounts()),
    settle(api.memory()),
    settle(api.pictures()),
    settle(api.logs(400)),
  ]);

  for (const f of (schema as any)?.fields ?? []) {
    add(
      list,
      {
        route: "settings",
        title: f.label ?? f.key,
        subtitle: `${f.key}${f.current !== undefined ? `, ${f.current}` : ""}`,
        group: "Settings",
      },
      f.key, f.section, f.help, f.current,
    );
  }

  for (const key of Object.keys((secrets as any)?.secrets ?? {})) {
    add(list, { route: "settings", title: key, subtitle: "Secret / .env", group: "Secrets" });
  }

  for (const a of (accounts as any)?.accounts ?? []) {
    add(
      list,
      { route: "accounts", title: a.label ?? a.id, subtitle: `${a.role ?? ""} ${a.state ?? ""}`.trim(), group: "Accounts" },
      a.id, a.pid,
    );
  }

  const mem = (memory as any)?.users ?? (memory as any)?.memory ?? [];
  for (const u of Array.isArray(mem) ? mem : []) {
    const facts = u.facts ?? u.memory ?? {};
    add(
      list,
      { route: "memory", title: u.name ?? String(u.id ?? u.user_id), subtitle: "Remembered facts", group: "Memory" },
      u.id, u.user_id, JSON.stringify(facts),
    );
  }

  for (const p of (pictures as any)?.pictures ?? []) {
    add(list, { route: "pictures", title: p.name, subtitle: p.description || "no description", group: "Pictures" }, p.description);
  }

  const lines = (logs as any)?.lines ?? (logs as any)?.logs ?? [];
  for (const l of Array.isArray(lines) ? lines.slice(-250) : []) {
    add(
      list,
      { route: "logs", title: l.text ?? "", subtitle: `${l.time ?? ""} ${l.source ?? ""}`.trim(), group: "Logs" },
      l.source, l.level,
    );
  }

  docs = list;
  built = Date.now();
}

export function indexAge(): number {
  return built ? Date.now() - built : Infinity;
}

/** Every word in the query must appear somewhere in the document. */
export function search(query: string, limit = 40): Hit[] {
  const words = norm(query).split(/\s+/).filter(Boolean);
  if (!words.length) {
    return docs
      .filter((d) => d.group === "Pages")
      .map((d) => ({ ...d, score: 0 }));
  }

  const hits: Hit[] = [];
  for (const d of docs) {
    let score = 0;
    let all = true;
    for (const w of words) {
      const at = d.hay.indexOf(w);
      if (at === -1) {
        all = false;
        break;
      }
      // Earlier and word-boundary matches rank higher; title beats body.
      score += 100 - Math.min(60, at);
      if (norm(d.title).includes(w)) score += 60;
      if (new RegExp(`\\b${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(d.hay)) score += 25;
    }
    if (!all) continue;
    if (d.group === "Pages") score += 40;      // navigating is the common case
    hits.push({ route: d.route, title: d.title, subtitle: d.subtitle, group: d.group, score });
  }

  return hits.sort((a, b) => b.score - a.score).slice(0, limit);
}

/** Wrap matched words in <mark> for display. Escapes the input first. */
export function highlight(text: string, query: string): string {
  const esc = String(text ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
  const words = norm(query).split(/\s+/).filter(Boolean);
  if (!words.length) return esc;
  const pattern = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  return esc.replace(new RegExp(`(${pattern})`, "gi"), "<mark>$1</mark>");
}
