/**
 * A list or a grid arriving as its tab opens: its items pop in one after
 * another, like dominoes, with a little jelly, each a soft note a step up the
 * scale, so a grid of them plays a run.
 *
 * Put on the element whose children are the items, with the class "domino"
 * (app.css draws the pop): `<div class="domino" use:domino>`, or
 * `use:domino={{ step: 50, sound: "wind" }}`. The run waits for the block it
 * is in to land (cascade.ts), and for its place in a second, smaller wave down
 * that block, as a chart's bars do (growin.ts). Only the items the window
 * shows take a turn: the rest are simply there when scrolled to. Items that
 * come later (a list filling in once its data arrives, a new row) pop in on
 * their own, quietly. The notes are booked on the sound card's clock with the
 * items' CSS delays, so a busy moment does not bunch them up. With the app's
 * Animations off, everything is simply there.
 */
import { get } from "svelte/store";
import { motionEnabled } from "./stores";
import { afterLanding, onScreen, whenShown } from "./cascade";
import { play, type UISound } from "./uisound";

/**
 * One thing arriving with a pop of its own (a check mark, a ring): heard as it
 * pops, which is once its block has landed (what a block animates waits for
 * it), and only where it can be seen. `use:chime={"done"}`, or with the pop's
 * own CSS delay, `use:chime={{ sound: "done", delay: 450 }}`.
 */
export function chime(node: HTMLElement, what: UISound | { sound: UISound; delay?: number } = "land") {
  if (!get(motionEnabled)) return;
  const { sound, delay = 0 } = typeof what === "string" ? { sound: what } : what;
  whenShown(node).then(() => afterLanding(node, () => {
    // Asked there and then, not of an observer a frame or two later: the pop it goes with has started.
    const r = node.getBoundingClientRect();
    if (r.width > 0 && r.bottom > 0 && r.top < innerHeight && get(motionEnabled)) play(sound, { delay });
  }));
}

type Opts = {
  /** ms between one item and the next. */
  step?: number;
  /** The note each one makes: a marimba note up the scale, a dry tick, a key pressed, a woody tock, or nothing. */
  sound?: "pluck" | "wind" | "key" | "seat" | "none";
  /** How each one comes in: popping up (the usual), or plugged in, sliding across from the left. */
  variant?: "pop" | "plug";
  /** When its note sounds after it starts (ms): as it lands, for a plug, rather than as it sets off. */
  soundAt?: number;
  level?: number;
  /** How many take a turn at most: a long list does not play for ever. */
  max?: number;
  /** Only as the tab opens: after its run the list is left to its own ways of showing what comes later. */
  once?: boolean;
};

const PER_PX = 0.35;
const MAX_WAIT = 350;

/**
 * The part of the window a list's items can be seen in: the window, cut down by every box around them that scrolls
 * or clips, the list itself included. Measured against the window alone, a list scrolled to its end (the Logs, newest
 * at the foot) gave its turns to the lines scrolled out of sight above, and the ones on screen came in with nothing.
 */
function viewOf(node: HTMLElement) {
  let top = 0, bottom = innerHeight;
  for (let el: HTMLElement | null = node; el; el = el.parentElement) {
    const s = getComputedStyle(el);
    if (/(auto|scroll|hidden|clip)/.test(s.overflowY)) {
      const r = el.getBoundingClientRect();
      top = Math.max(top, r.top);
      bottom = Math.min(bottom, r.bottom);
    }
  }
  return { top, bottom };
}

export function domino(node: HTMLElement, opts: Opts = {}) {
  let o = opts;
  let gone = false;
  let watching: MutationObserver | null = null;
  let quit = 0;

  function run(seen: boolean) {
    if (gone) return;
    const step = o.step ?? 40;
    const kids = Array.from(node.children) as HTMLElement[];
    const view = viewOf(node);
    let k = 0;
    for (const c of kids) {
      const r = c.getBoundingClientRect();
      const turn = seen && k < (o.max ?? 24) && r.bottom > view.top && r.top < view.bottom && r.width > 0;
      c.style.setProperty("--i", turn ? String(k++) : "0");
      // An attribute, not a class: the page's own class updates would take a class off again, and pop it.
      if (turn) delete c.dataset.there;
      else c.dataset.there = "";
    }
    node.style.setProperty("--domino-step", `${step}ms`);
    if (o.variant === "plug") node.classList.add("is-plug");
    node.classList.add("is-in");
    if (o.once) quit = window.setTimeout(() => node.classList.remove("domino"), k * step + 700);
    const name = o.sound ?? "pluck";
    if (!seen || name === "none" || !k) return;
    // Booked from the frame the pops start in, not from now: while a tab is busy opening that frame can come a
    // good while later, and the notes ran ahead of what they go with.
    requestAnimationFrame((frame) => {
      if (gone || !get(motionEnabled)) return;
      const base = frame - performance.now();
      // Up the scale: a run of notes, from low to bright, whatever the number of items.
      for (let i = 0; i < k; i++) {
        play(name, { p: k > 1 ? 0.1 + (0.75 * i) / (k - 1) : 0.5, level: (o.level ?? 0.65) * (k > 12 ? 0.75 : 1),
                     delay: base + i * step + (o.soundAt ?? 16) });
      }
    });
  }

  /** Nothing in it yet (its data is on the way): the run starts as the first items come, within a moment. */
  function whenFilled(seen: boolean) {
    if (node.children.length) return run(seen);
    watching = new MutationObserver(() => {
      if (!node.children.length) return;
      watching?.disconnect();
      watching = null;
      // A frame for the rest of the items to be put in with the first.
      requestAnimationFrame(() => run(seen));
    });
    watching.observe(node, { childList: true });
    quit = window.setTimeout(() => {
      watching?.disconnect();
      watching = null;
      node.classList.add("is-in");
    }, 2500);
  }

  // Kept whole by the tab's opening wave (cascade.ts): it would otherwise drop each item in itself, and an item
  // would show, vanish while it waited for its turn here, and pop in again.
  node.dataset.rise = "";
  if (!get(motionEnabled)) {
    node.classList.add("is-in");
  } else {
    whenShown(node).then(() => {
      if (gone) return;
      const block = node.closest("[data-arriving]");
      const down = block ? node.getBoundingClientRect().top - block.getBoundingClientRect().top : 0;
      // On a page opened to be read at once (data-cascade="quick"), the second wave is barely a beat behind.
      const quick = !!node.closest('[data-cascade="quick"]');
      const wait = Math.max(0, Math.min(quick ? 90 : MAX_WAIT, down * (quick ? 0.1 : PER_PX)));
      afterLanding(node, () => onScreen(node).then((seen) => {
        if (gone) return;
        if (!seen || !get(motionEnabled)) return run(false);
        window.setTimeout(() => whenFilled(true), wait);
      }));
    });
  }

  return {
    update(next: Opts = {}) {
      o = next;
    },
    destroy() {
      gone = true;
      watching?.disconnect();
      clearTimeout(quit);
    },
  };
}
