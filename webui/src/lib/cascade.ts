/**
 * Opening a tab: what is in it drops into place from the top down.
 *
 * Put on the element a page is drawn in (`use:cascade={route}`). When it
 * mounts, or the key changes, the blocks on screen - cards, rows, tiles,
 * headings - each come in from a little above with a small spring, each a
 * little after the one above it, so the page fills in as one wave rather than
 * appearing all at once.
 *
 * Which blocks: the page's children, and the children of any plain wrapper
 * among them, three levels down. A plain wrapper (no background, border or
 * shadow of its own) is only layout, so it is opened up and what is in it
 * moves on its own; a card is kept whole, or its frame would sit there empty
 * while its contents arrived.
 *
 * Pages load lazily, and draw a skeleton before their data, so for a moment
 * after opening, anything that appears joins the wave where it stands rather
 * than popping in after it.
 *
 * Transform and opacity only, on the compositor. Nothing below the fold is
 * animated, nothing is left behind afterwards (no fill), and with the app's
 * Animations switch off it does nothing.
 */
import { get } from "svelte/store";
import { motionEnabled } from "./stores";
import { play } from "./uisound";

/** How long after opening new blocks still come in with the wave. */
const WINDOW_MS = 900;
/** Delay per pixel down the page: the wave's speed. */
const PER_PX = 0.42;
const MAX_DELAY = 380;
const DURATION = 520;
/** A page that is a tool, opened to be read at once (data-cascade="quick": Settings' Models tabs): the same wave,
 * in under half the time, so what is on it is there before you have to wait for it. */
const QUICK = { perPx: 0.16, maxDelay: 140, duration: 340 };
const MAX_BLOCKS = 48;
const DEPTH = 3;
/** Entrances of their own that the wave replaces: Card's rise, a staggered list's, a pop. */
const DOUBLES = ".card-enter, .stagger > *, .pop";

/** When each block the wave moves starts to come in, after its place in the wave. */
const showing = new WeakMap<Element, Promise<void>>();

/**
 * Resolves as the block this element is in starts to drop into place,
 * straight away when it is in none. The clocks sweep in from here: with the
 * tab's opening, not after it, and not while their block is still hidden
 * waiting its turn, where the sweep would be half over before it was seen.
 */
export function whenShown(node: Element | null): Promise<void> {
  return new Promise((resolve) => {
    // The wave marks what it moves on the frame after a page mounts: look after that.
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        const block = node?.closest("[data-arriving]");
        const shown = block ? showing.get(block) : undefined;
        (shown ?? Promise.resolve()).then(() => resolve());
      }),
    );
  });
}

/**
 * Runs `fn` once the block this element is in has landed (straight away when
 * it is in none). What a block animates is held until it lands (app.css), and
 * a sound that goes with one of those animations waits with it: an animation
 * with no delay can say it has started while it is still held.
 */
export function afterLanding(node: Element | null, fn: () => void): void {
  const block = node?.closest("[data-arriving]");
  if (!block) return fn();
  const t0 = performance.now();
  const wait = () => {
    if (!block.hasAttribute("data-arriving") || performance.now() - t0 > 1500) fn();
    else requestAnimationFrame(wait);
  };
  requestAnimationFrame(wait);
}

/**
 * Whether an element is on screen, asked once, after layout rather than by
 * measuring it there and then. A dial further down a tab than the window
 * reaches has nobody to sweep in for: it goes straight to its value.
 */
export function onScreen(node: Element | null): Promise<boolean> {
  return new Promise((resolve) => {
    if (!node) return resolve(false);
    const io = new IntersectionObserver(([e]) => {
      io.disconnect();
      resolve(!!e?.isIntersecting);
    });
    io.observe(node);
  });
}

function plain(el: HTMLElement): boolean {
  const cs = getComputedStyle(el);
  return (
    (cs.backgroundColor === "rgba(0, 0, 0, 0)" || cs.backgroundColor === "transparent") &&
    cs.backgroundImage === "none" &&
    cs.boxShadow === "none" &&
    parseFloat(cs.borderTopWidth) === 0 &&
    parseFloat(cs.borderLeftWidth) === 0
  );
}

/** The blocks that move, in document order. One that has already moved is left whole, children and all. */
function blocks(root: Element, depth: number, seen: WeakSet<Element>, out: HTMLElement[]) {
  for (const el of Array.from(root.children)) {
    if (!(el instanceof HTMLElement) || "noRise" in el.dataset || seen.has(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    const opened =
      depth < DEPTH &&
      el.children.length >= 2 &&
      !("rise" in el.dataset) &&
      (r.height > innerHeight * 0.4 || el.children.length >= 4) &&
      plain(el);
    if (opened) blocks(el, depth + 1, seen, out);
    else out.push(el);
  }
}

export function cascade(node: HTMLElement, key?: unknown) {
  let seen = new WeakSet<Element>();
  let started = 0;
  let count = 0;
  let frame = 0;
  let observer: MutationObserver | null = null;
  let stopTimer: ReturnType<typeof setTimeout> | null = null;
  let easing = "cubic-bezier(0.2, 0.9, 0.25, 1)";

  // The app's own Animations switch decides, like everywhere else in it. Not the
  // system's "reduce motion": Windows with its animation effects off reports
  // that, and the whole app ignores it in favour of the switch, so this would
  // have been the one thing that never moved.
  const off = () => !get(motionEnabled) || document.documentElement.dataset.motion === "off";

  function wave() {
    frame = 0;
    const box = node.getBoundingClientRect();
    const found: HTMLElement[] = [];
    blocks(node, 0, seen, found);
    const fresh = found
      .map((el) => ({ el, r: el.getBoundingClientRect() }))
      .filter(({ r }) => r.top < innerHeight && r.bottom > 0)
      // Top to bottom, and left to right along a row.
      .sort((a, b) => a.r.top - b.r.top || a.r.left - b.r.left);
    // Something arriving later starts where the wave has got to by now.
    const late = performance.now() - started;
    const quick = node.dataset.cascade === "quick";
    const perPx = quick ? QUICK.perPx : PER_PX;
    const maxDelay = quick ? QUICK.maxDelay : MAX_DELAY;
    const duration = quick ? QUICK.duration : DURATION;
    for (const { el, r } of fresh) {
      seen.add(el);
      if (count >= MAX_BLOCKS) continue;
      count++;
      const along = Math.max(0, r.top - box.top) * perPx + Math.min(Math.max(0, r.left - box.left), 600) * (quick ? 0.02 : 0.06);
      const delay = Math.max(0, Math.min(maxDelay, along) - late * 0.5);
      // Its own way in, where it has one, would be a second entrance on top
      // of this one: a card rising from below while this drops it from above.
      for (const x of [el, ...el.querySelectorAll<HTMLElement>(DOUBLES)]) {
        if (x.matches(DOUBLES)) x.style.animation = "none";
      }
      // Everything else it animates waits for it to land (app.css pauses the
      // animations inside [data-arriving]), so the tab opens first and what
      // is in it moves after, not both at once. The clocks are the exception:
      // they sweep in with it (whenShown).
      el.dataset.arriving = "";
      const anim = el.animate(
        [
          { opacity: 0, transform: "translate3d(0, -12px, 0) scale(0.975)" },
          { opacity: 1, transform: "none" },
        ],
        { duration, delay, easing, fill: "backwards" },
      );
      showing.set(el, new Promise((r) => setTimeout(r, delay)));
      // A block that asks to be heard (data-land-sound: the Dashboard's widgets) is set down with a soft
      // thup as it lands, so a page of them is a patter down the page. Not one taken away mid drop.
      const heard = "landSound" in el.dataset;
      anim.finished.then(
        () => heard,
        () => false,
      ).then((landed) => {
        delete el.dataset.arriving;
        if (landed) play("settle");
      });
    }
  }

  /** Whether an element is in a block the wave has already moved. */
  const inside = (el: HTMLElement) => {
    for (let p: HTMLElement | null = el; p && p !== node; p = p.parentElement) if (seen.has(p)) return true;
    return false;
  };

  const soon = () => {
    if (!frame) frame = requestAnimationFrame(wave);
  };

  function stop() {
    observer?.disconnect();
    observer = null;
    if (stopTimer) clearTimeout(stopTimer);
    stopTimer = null;
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
  }

  function start() {
    stop();
    if (off()) return;
    seen = new WeakSet();
    count = 0;
    started = performance.now();
    // The app's own springy curve, where the engine takes one.
    const spring = getComputedStyle(document.documentElement).getPropertyValue("--spring").trim();
    if (spring && CSS.supports("animation-timing-function", spring)) easing = spring;
    soon();
    // Only elements appearing outside the blocks already moved start another
    // look: what changes inside them (a dropdown typing its value, a dial's
    // marks) used to set off a full measure of every block, every frame.
    observer = new MutationObserver((records) => {
      for (const r of records) {
        for (const n of Array.from(r.addedNodes)) {
          if (n instanceof HTMLElement && !inside(n)) {
            soon();
            return;
          }
        }
      }
    });
    observer.observe(node, { childList: true, subtree: true });
    stopTimer = setTimeout(stop, WINDOW_MS);
  }

  start();
  return {
    update(next: unknown) {
      if (next !== key) {
        key = next;
        start();
      }
    },
    destroy: stop,
  };
}
