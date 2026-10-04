/**
 * Settings > Appearance opening its own way, faster than the other tabs and
 * unlike them: the colours flood in.
 *
 * Everywhere else a tab drops into place and then its lists pop up one after
 * another, a marimba note each (cascade.ts, domino.ts). This page is about
 * colour and light, so it opens as one: the cards come up out of grey in a
 * quick diagonal wave from the top left, the way a theme change spreads out
 * from where you click; a glint of light crosses each; a theme's colour dots
 * spill out one after another, a background's preview develops like a photo,
 * a panel's colours bloom and its glass settles on them, a typeface inks
 * itself in; and the chosen one's tick pops last. Heard as a run of glassy
 * glints up the scale with the dots, after a breath of air as the wave sets
 * off, all of it over in about half a second. It starts at once rather than
 * waiting for a drop to land: the sections are left out of the tab's opening
 * wave, this being their way in.
 *
 * Put on each section: `<section class="ap-sec" use:colorwave>`; its grid's
 * cards are the `.ap-grid` children. The pace is the CSS's (Appearance.svelte),
 * from the `--wave-at` and `--d` set here, and the sounds are booked on the
 * sound card's clock to match.
 */
import { get } from "svelte/store";
import { motionEnabled } from "./stores";
import { play } from "./uisound";

/** ms from one diagonal of cards to the next. */
const STEP = 26;
/** After its card starts: when its colour dots start to spill, the gap between two, and when a chosen one's tick pops. */
const DOTS_AT = 60;
const DOT = 22;
const TICK_AT = 260;
/** A section lower down starts a little later, as if the wave were coming down the page. */
const PER_PX = 0.25;
const MAX_WAIT = 260;
/** From the frame the sounds are booked in to the one the animations truly start in: a frame and a half, measured. */
const LAG = 20;

function scroller(el: HTMLElement): HTMLElement | null {
  for (let p = el.parentElement; p; p = p.parentElement) {
    const oy = getComputedStyle(p).overflowY;
    if ((oy === "auto" || oy === "scroll") && p.scrollHeight > p.clientHeight) return p;
  }
  return null;
}

export function colorwave(node: HTMLElement) {
  // Not dropped by the tab's opening wave: this is its own way in, and it starts at once.
  node.dataset.noRise = "";
  if (!get(motionEnabled)) {
    node.classList.add("is-in");
    return {};
  }
  let gone = false;
  let done = 0;
  let frame = 0;
  // Set going at once: the section and its cards are in the page as this runs, and waiting a frame or two to
  // start, while the rest of Settings was still being put together, left them empty for a third of a second.
  const r = node.getBoundingClientRect();
  const box = scroller(node);
  const down = r.top - (box ? box.getBoundingClientRect().top : 0);
  const at = Math.round(Math.max(0, Math.min(MAX_WAIT, down * PER_PX)));
  node.style.setProperty("--wave-at", `${at}ms`);
  const seen = r.width > 0 && r.bottom > 0 && r.top < innerHeight;
  // Each card's diagonal: its column plus its row, read off where it is, however the grid wraps.
  const cards = Array.from(node.querySelector(".ap-grid")?.children ?? []) as HTMLElement[];
  const cols = [...new Set(cards.map((c) => Math.round(c.offsetLeft)))].sort((a, b) => a - b);
  const rows = [...new Set(cards.map((c) => Math.round(c.offsetTop)))].sort((a, b) => a - b);
  const notes: { t: number; chosen?: boolean }[] = [];
  for (const c of cards) {
    const d = cols.indexOf(Math.round(c.offsetLeft)) + rows.indexOf(Math.round(c.offsetTop));
    c.style.setProperty("--d", String(d));
    const cr = c.getBoundingClientRect();
    if (!seen || cr.top > innerHeight || cr.bottom < 0) continue;
    const start = at + d * STEP;
    const dots = c.querySelectorAll(".ap-swatches i").length;
    for (let i = 0; i < Math.max(1, dots); i++) notes.push({ t: start + DOTS_AT + i * DOT });
    if (c.getAttribute("aria-pressed") === "true") notes.push({ t: start + TICK_AT, chosen: true });
  }
  node.classList.add("is-in", "is-waving");
  // The opening's own timings (the chosen tick's late pop) only for the opening: a tick that comes later is quick.
  done = window.setTimeout(() => node.classList.remove("is-waving"), at + 1200);
  if (seen && notes.length) {
    // Heard from the frame the wave is first drawn in, which is when its animations start: the page can still be
    // busy for a moment after the section is put in, and sounds booked from now would run ahead of it.
    frame = requestAnimationFrame(() => {
      if (gone) return;
      if (at < 80) play("zip", { delay: at + LAG, level: 0.7 });
      notes.sort((a, b) => a.t - b.t);
      const run = notes.filter((x) => !x.chosen).length;
      let i = 0;
      for (const x of notes) {
        if (x.chosen) play("glint", { p: 1, strong: true, delay: x.t + LAG });
        else play("glint", { p: run > 1 ? i++ / (run - 1) : 0.5, delay: x.t + LAG, level: run > 10 ? 0.75 : 0.9 });
      }
    });
  }
  return {
    destroy() {
      gone = true;
      cancelAnimationFrame(frame);
      clearTimeout(done);
    },
  };
}
