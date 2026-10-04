/**
 * What Big Picture's scenes about the rest of the app need worked out, as
 * plain functions of plain data so they run under Node in
 * tests/bigpicture_director.mjs.
 *
 *   personaLines   who the bot is, from the opening of its instructions
 *   personaName    the name it is told it has, when the persona says one
 *   sentPictures   which of its own pictures a sent message carried
 *   untilText      "in 4 min" for a friend request the account will take by itself
 *   chapterOrder   the chapters for the rail under the stage, each once
 */
import type { Scene } from "./director";

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
 * placeholders has nothing to show, and the scene does not come round.
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

/** The chapters on the rail: every scene in the cycle once, in the order it first comes round. */
export function chapterOrder(cycle: readonly Scene[]): Scene[] {
  const out: Scene[] = [];
  for (const s of cycle) if (!out.includes(s)) out.push(s);
  return out;
}

/** What each chapter is called on the rail, and its icon. */
export const CHAPTER: Record<Scene, { label: string; icon: string }> = {
  memory: { label: "Memory", icon: "memory" },
  today: { label: "Today", icon: "stats" },
  accounts: { label: "Accounts", icon: "accounts" },
  recent: { label: "Recent", icon: "inbox" },
  pictures: { label: "Pictures", icon: "pictures" },
  people: { label: "Talked to most", icon: "sparkle" },
  persona: { label: "Persona", icon: "persona" },
  friends: { label: "Friend requests", icon: "userPlus" },
  health: { label: "Needs attention", icon: "alert" },
};
