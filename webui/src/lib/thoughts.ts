/**
 * What the accounts are thinking, as they think it, for whatever wants to show it (LiveThought.svelte).
 *
 * Thoughts come down the log as lines of their own kind (app/web/supervisor.py), from a model that reasons before it
 * answers, and from a Minecraft account deciding what to do next (app/platforms/minecraft/brain.py). The log's socket
 * is shared, and only open while something wants it, so the first to look also reads what was thought before it looked.
 */
import { writable } from "svelte/store";
import { api } from "./api";
import { subscribeLogs, type LogEntry } from "./logsocket";

export type Thought = { source: string; model: string; text: string; at: number };

const KEEP = 40;

export const thoughts = writable<Thought[]>([]);

/** A log line as a thought, or null if it is not one: "Thinking (its model)", then what it thought. */
export function thoughtOf(e: LogEntry): Thought | null {
  if (e.level !== "think" || !e.text) return null;
  const [head, ...rest] = e.text.split("\n");
  const text = rest.join("\n").trim();
  if (!text) return null;
  return { source: e.source ?? "", model: /\((.*)\)/.exec(head)?.[1] ?? "", text, at: e.ts || Date.now() / 1000 };
}

function take(list: LogEntry[]) {
  const fresh = list.map(thoughtOf).filter((t): t is Thought => !!t);
  if (!fresh.length) return;
  thoughts.update((held) => {
    // The socket says its last lines again each time it connects.
    const known = new Set(held.map((t) => `${t.source}|${t.at}|${t.text.length}`));
    const added = fresh.filter((t) => !known.has(`${t.source}|${t.at}|${t.text.length}`));
    return added.length ? [...held, ...added].sort((a, b) => a.at - b.at).slice(-KEEP) : held;
  });
}

let users = 0;
let stop: (() => void) | null = null;
let readBack = false;

/** Keep the store up to date for as long as the function it gives back has not been called. */
export function useThoughts(): () => void {
  if (users++ === 0) stop = subscribeLogs((e) => take([e]));
  if (!readBack) {
    readBack = true;
    api.logs(400).then((d: any) => take(d?.lines ?? [])).catch(() => (readBack = false));
  }
  return () => {
    if (--users === 0) {
      stop?.();
      stop = null;
    }
  };
}
