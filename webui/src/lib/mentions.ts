/**
 * Turning a raw Discord mention into a name the app already knows.
 *
 * A message stored or previewed anywhere carries mentions as `<@123…>` - the
 * id, not the name - because that is what Discord sends. Shown as-is it is an
 * 18-digit number nobody can read. This resolves an id to the person's name
 * from what the panel has locally (the same profile/memory data a UserChip
 * opens), caches it so a name is looked up once however many messages mention
 * them, and hands it to <MentionText> to draw as a clickable chip.
 */
import { get, writable } from "svelte/store";
import { api } from "./api";

/** id -> resolved display name, "" while unknown/loading, filled once known. */
export const mentionNames = writable<Record<string, string>>({});

const inflight = new Set<string>();

/** Any Discord user mention: <@123>, <@!123> (nickname form). */
export const MENTION_RE = /<@!?(\d+)>/g;

/** Kick off a lookup for an id if it is not known yet. Safe to call often. */
export function resolveMention(id: string): void {
  if (!id) return;
  const known = get(mentionNames);
  if (id in known || inflight.has(id)) return;
  inflight.add(id);
  api
    .person(id)
    .then((p: any) => {
      const name = p?.display_name || p?.username || p?.name || "";
      mentionNames.update((m) => ({ ...m, [id]: name }));
    })
    .catch(() => {
      // Nobody the bot has met, or the lookup failed: remember the miss so the
      // chip settles on a stable "@user" instead of retrying every render.
      mentionNames.update((m) => ({ ...m, [id]: "" }));
    })
    .finally(() => inflight.delete(id));
}

export type Segment =
  | { kind: "text"; text: string }
  | { kind: "mention"; id: string };

/** Split a message into plain text and the user mentions inside it. */
export function segments(text: string): Segment[] {
  if (!text) return [];
  const out: Segment[] = [];
  let last = 0;
  for (const m of text.matchAll(MENTION_RE)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ kind: "text", text: text.slice(last, at) });
    out.push({ kind: "mention", id: m[1] });
    last = at + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

/** Whether a string has anything worth running through <MentionText>. */
export function hasMention(text: string): boolean {
  // Not MENTION_RE.test(): a /g regex keeps its lastIndex between calls, so
  // asking twice about the same message would answer true, then false.
  return !!text && /<@!?\d+>/.test(text);
}
