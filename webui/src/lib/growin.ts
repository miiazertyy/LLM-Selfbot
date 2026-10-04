/**
 * A chart arriving as its tab opens: its bars grow up into place one after
 * another, each with a soft marimba note pitched by how tall it is, so a week
 * of them plays the week's shape. They were silent, or simply there.
 *
 * The growing waits for the block the chart is in to land (cascade.ts), the
 * way everything inside a block does, and then for its place in a second,
 * smaller wave down the block: a sheet of widgets landing as one block used to
 * set everything in it going in the same instant. Not seen (below the window)
 * or with Animations off, the bars are simply there and nothing is heard.
 */
import { get } from "svelte/store";
import { motionEnabled } from "./stores";
import { afterLanding, onScreen, whenShown } from "./cascade";
import { play } from "./uisound";

/** The second wave's speed down a landed block, and how long it can take at most. */
const PER_PX = 0.35;
const MAX_WAIT = 350;

/**
 * Calls `start(true)` once the chart may grow (and is seen), then plays a note
 * for each bar, `stagger` ms apart, as the chart's own CSS starts each bar
 * that far after the one before. `start(false)`: be there at once.
 * `heights` is read then, not now: the numbers may still be on their way.
 */
export function growIn(node: Element | null, heights: () => number[], start: (moving: boolean) => void,
                       stagger = 45, level = 1, sound: "pluck" | "wind" | "grow" = "pluck"): void {
  if (!node || !get(motionEnabled)) return start(false);
  const el = node;
  whenShown(el).then(() => {
    const block = el.closest("[data-arriving]");
    const down = block ? el.getBoundingClientRect().top - block.getBoundingClientRect().top : 0;
    const wait = Math.max(0, Math.min(MAX_WAIT, down * PER_PX));
    afterLanding(el, () => onScreen(el).then((seen) => {
      if (!seen || !get(motionEnabled)) return start(false);
      setTimeout(() => {
        start(true);
        const hs = heights();
        const max = Math.max(1, ...hs);
        // A long row of bars plays softer: it is many notes. Each note is booked on the sound card's clock
        // as the bars are set going (their CSS delays are the browser's): timers one at a time bunched up.
        const soft = level * (hs.length > 10 ? 0.55 : 1);
        hs.forEach((h, i) => {
          if (h > 0) play(sound, { p: h / max, level: soft, delay: i * stagger + 16 });
        });
      }, wait);
    }));
  });
}

/**
 * The same as an action, for a list whose rows' own CSS does the moving:
 * `use:arriving={{ heights, stagger }}` adds `is-in` to the list at its moment,
 * the rows' animations waiting for it (their delays then count from there; held
 * inside a block that was still dropping in, they were spent and the rows all
 * went at once), and the notes are booked to go with them.
 */
export function arriving(node: HTMLElement, o: { heights: () => number[]; stagger?: number; level?: number;
                                                  sound?: "pluck" | "wind" }) {
  growIn(node, o.heights, () => node.classList.add("is-in"), o.stagger ?? 45, o.level ?? 1, o.sound ?? "pluck");
}

/** The gap between bars that keeps a chart's whole run under `total` ms. */
export const staggerFor = (n: number, most = 55, total = 520) => Math.max(14, Math.min(most, total / Math.max(1, n)));
