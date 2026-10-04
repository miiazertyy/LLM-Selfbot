/**
 * Which persona the editors below a page work on: the Personas page passes
 * the one picked, Settings the one it is scoped to ("" for everyone's).
 *
 * Read once, as a component starts, and handed with every read and save it
 * makes: a page switching persona remakes them ({#key}), so a save that takes
 * a few steps (the moods, four settings in a row) all goes to the persona it
 * started on. A store every component read at save time would have sent the
 * rest of such a save to whichever persona was picked meanwhile.
 */
import { getContext, setContext } from "svelte";

const KEY = Symbol("persona");

/** For the components below: the persona they edit, "" for everyone's settings. */
export function providePersona(get: () => string): void {
  setContext(KEY, get);
}

/** The persona this component edits ("" for everyone's), as it started. */
export function usePersona(): string {
  const get = getContext<(() => string) | undefined>(KEY);
  return get ? get() || "" : "";
}
