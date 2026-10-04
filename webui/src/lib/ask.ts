/**
 * Asking before doing something that cannot be undone, in the app's own words.
 *
 * `confirm()` was used for this, which is the operating system's box: a plain
 * white dialog in a dark app on Windows, and in the Android app nothing at all
 * (its web view has no dialogs, so `confirm()` answers "no" without asking,
 * and restarting or forgetting someone could never be done there). `ask()`
 * shows the question in the app's own dialog (AskHost.svelte, mounted once in
 * App.svelte) and answers true or false the same way.
 */
import { writable } from "svelte/store";

export type Question = {
  id: number;
  text: string;
  /** A line under the question, saying what happens. */
  detail: string;
  yes: string;
  no: string;
  /** The yes is destructive: drawn in red, and the safe answer has the focus. */
  danger: boolean;
  resolve: (answer: boolean) => void;
};

export const asking = writable<Question | null>(null);
let n = 0;

export function ask(
  text: string,
  opts: { yes?: string; no?: string; danger?: boolean; detail?: string } = {},
): Promise<boolean> {
  return new Promise((resolve) => {
    asking.update((cur) => {
      cur?.resolve(false);        // a new question means the old one was not answered
      return { id: ++n, text, detail: opts.detail ?? "", yes: opts.yes ?? "Yes", no: opts.no ?? "Cancel",
               danger: !!opts.danger, resolve };
    });
  });
}

export function answer(yes: boolean): void {
  asking.update((cur) => {
    cur?.resolve(yes);
    return null;
  });
}
