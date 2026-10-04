/**
 * Settings that were just used, for the glow on their rows in Settings.
 *
 * The runner announces a command run with the command prefix, a message
 * carrying the priority prefix and a trigger word that woke it
 * (discord_runner.emit_use); the panel passes each on over the shared socket
 * as a "use" event. The row lights the way a model's row in Models does when
 * it answers, and says what was used ("!ping").
 */
import { writable } from "svelte/store";
import { subscribeEvents } from "./logsocket";

export type Use = { at: number; detail: string; n: number };

/** Setting key to its last use, kept for a few seconds: long enough to be seen. */
export const lastUsed = writable<Record<string, Use>>({});

let started = false;
let n = 0;

/** Once for the whole app: the socket is shared. */
export function startUseLive(): void {
  if (started) return;
  started = true;
  subscribeEvents("use", (evt) => {
    const key = String(evt?.key ?? "");
    if (!key) return;
    const use: Use = { at: Date.now(), detail: String(evt?.detail ?? ""), n: ++n };
    lastUsed.update((m) => ({ ...m, [key]: use }));
    setTimeout(() => {
      lastUsed.update((m) => {
        if (m[key]?.n !== use.n) return m;
        const next = { ...m };
        delete next[key];
        return next;
      });
    }, 4200);
  });
}
