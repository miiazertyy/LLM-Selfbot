/**
 * Text typing itself in, fast, a caret running ahead of it and a soft key heard
 * every few letters: a Memory summary as it arrives.
 *
 * Every letter is there from the start, only not yet shown (the untyped rest of
 * each line is kept in place, invisible), so the card has its full size at once
 * and nothing below it moves while it types. Works on whatever is inside,
 * bold and code included: only the text is walked, never the markup. The
 * speed fits the length, so a long summary is not slower to read than a short
 * one: about a second and a half for the whole of it. With the app's
 * Animations off, it is simply there.
 */
import { get } from "svelte/store";
import { motionEnabled } from "./stores";
import { play } from "./uisound";

type Opts = { seconds?: number; sound?: boolean };

export function typewrite(node: HTMLElement, opts: Opts = {}) {
  if (!get(motionEnabled)) return;
  const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => ((n.textContent ?? "").length ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
  });
  const parts: { typed: Text; rest: HTMLElement; full: string }[] = [];
  const found: Text[] = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) found.push(n as Text);
  for (const t of found) {
    const full = t.data;
    const rest = document.createElement("span");
    rest.className = "tw-rest";
    rest.textContent = full;
    t.data = "";
    t.after(rest);
    parts.push({ typed: t, rest, full });
  }
  const total = parts.reduce((s, p) => s + p.full.length, 0);
  if (!total) return;
  node.classList.add("is-typing");
  const caret = document.createElement("span");
  caret.className = "tw-caret";
  caret.setAttribute("aria-hidden", "true");

  const perSecond = Math.max(70, total / (opts.seconds ?? 1.5));
  let i = 0;
  let c = 0;
  let shown = 0;
  let last = performance.now();
  /** Letters owed, carried from frame to frame: dropped each frame, a screen drawing 144 times a second or more owed
   * less than one a frame, and the typing all but stopped. */
  let owed = 0;
  let frame = 0;
  let gone = false;

  function finish() {
    for (const p of parts) {
      p.typed.data = p.full;
      p.rest.remove();
    }
    caret.remove();
    node.classList.remove("is-typing");
  }

  function step(now: number) {
    if (gone) return;
    owed += ((now - last) / 1000) * perSecond;
    last = now;
    while (owed >= 1 && i < parts.length) {
      const p = parts[i];
      const take = Math.min(Math.floor(owed), p.full.length - c);
      const before = c;
      c += take;
      owed -= take;
      shown += take;
      p.typed.data = p.full.slice(0, c);
      p.rest.textContent = p.full.slice(c);
      p.rest.before(caret);
      // A key every few letters, a firmer one on a space: typing, not a buzz.
      if (opts.sound !== false) {
        const typed = p.full.slice(before, c);
        if (Math.floor(shown / 4) !== Math.floor((shown - take) / 4)) {
          play("key", { strong: typed.includes(" ") && Math.random() < 0.4, level: 0.32 });
        }
      }
      if (c >= p.full.length) {
        i++;
        c = 0;
      }
    }
    if (i >= parts.length) {
      // The caret stays a moment at the end, blinking, then goes.
      node.classList.add("is-typed");
      window.setTimeout(() => !gone && finish(), 650);
      return;
    }
    frame = requestAnimationFrame(step);
  }
  frame = requestAnimationFrame((t) => {
    last = t;
    frame = requestAnimationFrame(step);
  });

  return {
    destroy() {
      gone = true;
      cancelAnimationFrame(frame);
    },
  };
}
