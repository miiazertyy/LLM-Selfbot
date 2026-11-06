/**
 * Smooth scrolling for the whole app, installed once: a mouse wheel's notch
 * glides the box under the pointer to where it goes, easing in, rather than
 * jumping there in one step. Several notches in a row add up into one longer
 * glide that never stops between them.
 *
 * Only a notched wheel: a touchpad (and a free-spinning wheel) already moves
 * in small, smooth steps of its own, and easing those again would feel late.
 * Ctrl+wheel (zoom), sideways scrolling, and anything that answers the wheel
 * itself (a dial, the face crop, a strip that scrolls sideways: each of those
 * takes the event first and marks it) are left as they are. So is a box that
 * keeps its scroll to itself (overscroll-behavior) once it has reached its end.
 * Grabbing the scrollbar or pressing a key mid-glide hands straight back.
 *
 * At either end a box keeps the wheel while it is still gliding there and for
 * a moment after, as the browser keeps a scroll with the box it began in. The
 * notches past the end used to go to the browser, which moved the box the
 * rest of the way in one jump (it was still gliding, with room left), or
 * started the page behind it moving.
 *
 * It has its own switch (Settings, Appearance, Interface: "Smooth scrolling"),
 * apart from Animations: off, the wheel is the browser's own.
 *
 * glideInto brings something into view the same way. The browser's own
 * scrollIntoView({ behavior: "smooth" }) is one jump in a single frame when
 * Windows' "Animation effects" are off, which is a setting plenty of PCs have.
 */
import { get } from "svelte/store";
import { motionEnabled, smoothScroll } from "./stores";

/** How quickly a glide catches up with where the wheel has sent it: about this many seconds to close two thirds. */
const TAU = 0.09;
/** What one line of a line-based wheel is worth, in pixels. */
const LINE = 40;
/** How long after a glide stops its box still keeps the wheel at an end (the browser's own latch is about this). */
const LATCH_MS = 450;

type Glide = { el: HTMLElement; target: number; pos: number; held: number; last: number; raf: number; ended: number };
const glides = new WeakMap<HTMLElement, Glide>();

const wanted = () => get(smoothScroll);

/** A wheel with notches: Chromium says each notch is 120 (wheelDeltaY). A touchpad's steps are anything. */
function notched(e: WheelEvent): boolean {
  const raw = (e as WheelEvent & { wheelDeltaY?: number }).wheelDeltaY;
  if (e.deltaMode !== 0) return true;
  if (typeof raw === "number" && raw !== 0) return raw % 120 === 0;
  return Math.abs(e.deltaY) >= 50 && Number.isInteger(e.deltaY);
}

function canScrollY(el: HTMLElement): boolean {
  if (el.scrollHeight <= el.clientHeight + 1) return false;
  const oy = getComputedStyle(el).overflowY;
  return oy === "auto" || oy === "scroll" || oy === "overlay";
}

/** Where a glide has got to, or is going: a notch during one carries on from its end, not from where it is now. */
const aim = (el: HTMLElement) => glides.get(el)?.raf ? glides.get(el)!.target : el.scrollTop;

/**
 * The box the wheel should move: the nearest one under the pointer that can still go that way. "hold" when the
 * nearest is at its end that way but still gliding there, or only just stopped: the wheel is still its own, and
 * nothing moves (not the rest of the way in one jump, not the page behind it).
 */
function scrollerFor(target: EventTarget | null, dy: number): HTMLElement | "hold" | null {
  for (let el = target instanceof Element ? target : null; el; el = el.parentElement) {
    if (!(el instanceof HTMLElement)) continue;
    const root = el === document.scrollingElement;
    if (!root && !canScrollY(el)) continue;
    if (root && el.scrollHeight <= el.clientHeight + 1) continue;
    const max = el.scrollHeight - el.clientHeight;
    const at = aim(el);
    if ((dy > 0 && at < max - 0.5) || (dy < 0 && at > 0.5)) return el;
    const g = glides.get(el);
    if (g && (g.raf || performance.now() - g.ended < LATCH_MS)) return "hold";
    // At its end that way, and keeping its scroll to itself: nothing behind it moves.
    if (!root && getComputedStyle(el).overscrollBehaviorY !== "auto") return null;
  }
  return null;
}

function step(g: Glide, now: number) {
  // Moved by something else since the last frame (its scrollbar, a key, the page going back to the top): that wins.
  if (Math.abs(g.el.scrollTop - g.held) > 1.5) {
    g.raf = 0;
    g.ended = now;
    return;
  }
  const dt = Math.min(0.064, (now - g.last) / 1000);
  g.last = now;
  g.pos += (g.target - g.pos) * (1 - Math.exp(-dt / TAU));
  if (Math.abs(g.target - g.pos) < 0.5) g.pos = g.target;
  g.el.scrollTop = g.pos;
  // What the box holds after rounding to its pixels, to tell our own moves from anyone else's.
  g.held = g.el.scrollTop;
  if (g.pos === g.target) {
    g.raf = 0;
    g.ended = now;
  } else {
    g.raf = requestAnimationFrame((t) => step(g, t));
  }
}

function glide(el: HTMLElement, dy: number) {
  into.delete(el); // the wheel wins over a glide into view that is still going
  let g = glides.get(el);
  if (!g || !g.raf) {
    g = { el, target: el.scrollTop, pos: el.scrollTop, held: el.scrollTop, last: performance.now(), raf: 0, ended: 0 };
    glides.set(el, g);
  }
  const max = el.scrollHeight - el.clientHeight;
  g.target = Math.max(0, Math.min(max, g.target + dy));
  if (!g.raf) {
    g.last = performance.now();
    g.raf = requestAnimationFrame((t) => step(g!, t));
  }
}

/** Whichever glideInto a box belongs to now: an older one, or one the wheel took over, lets go of it. */
const into = new WeakMap<HTMLElement, object>();
/** How far short of a box's edge something stops, when it only has to come into view. */
const CLEAR = 12;

type Block = "center" | "start" | "nearest";

/** Every box around it that can scroll, nearest first, the page last. */
function boxesAround(el: Element): HTMLElement[] {
  const out: HTMLElement[] = [];
  for (let box = el.parentElement; box; box = box.parentElement) {
    const root = box === document.scrollingElement;
    if (root ? box.scrollHeight > box.clientHeight + 1 : canScrollY(box)) out.push(box);
  }
  return out;
}

/** Where a box has to be scrolled for it to sit where asked, as things stand this moment. */
function aimAt(box: HTMLElement, el: Element, block: Block): number {
  const r = el.getBoundingClientRect();
  const b = box === document.scrollingElement ? { top: 0, bottom: box.clientHeight } : box.getBoundingClientRect();
  const room = b.bottom - b.top - CLEAR * 2;
  let by = 0;
  if (block === "center") by = (r.top + r.bottom) / 2 - (b.top + b.bottom) / 2;
  else if (block === "start") by = r.top - b.top - CLEAR;
  else if (r.top < b.top + CLEAR && r.bottom > b.bottom - CLEAR) by = 0; // bigger than the box, and already filling it
  else if (r.height >= room ? r.bottom > b.bottom - CLEAR : r.top < b.top + CLEAR) by = r.top - b.top - CLEAR;
  else if (r.bottom > b.bottom - CLEAR || r.top < b.top + CLEAR) by = r.bottom - b.bottom + CLEAR;
  return Math.max(0, Math.min(box.scrollHeight - box.clientHeight, box.scrollTop + by));
}

/**
 * Brings it into view with a glide of our own, each box around it in turn, or only `within` when it is given (a row in
 * its own list, leaving the page alone). Where it goes is asked again every frame, so what loads above it meanwhile
 * doesn't leave it short. A wheel, a scrollbar or a key part way takes over. With Animations off it just goes there.
 */
export function glideInto(el: Element | null | undefined, opts: { block?: Block; within?: Element | null } = {}): void {
  if (!el) return;
  const block = opts.block ?? "center";
  const within = opts.within;
  const boxes = within === undefined ? boxesAround(el)
    : within instanceof HTMLElement && canScrollY(within) ? [within] : [];
  if (!boxes.length) return;
  if (!get(motionEnabled)) {
    for (const box of boxes) box.scrollTop = aimAt(box, el, block);
    return;
  }
  const mine = {};
  const going = boxes.map((box) => {
    const g = glides.get(box);
    if (g?.raf) {
      cancelAnimationFrame(g.raf);
      g.raf = 0;
      g.ended = performance.now();
    }
    into.set(box, mine);
    return { box, from: box.scrollTop, held: box.scrollTop };
  });
  // Longer the further it goes, and never long.
  const far = Math.max(...going.map((m) => Math.abs(aimAt(m.box, el, block) - m.from)));
  const ms = Math.min(820, 380 + far * 0.4);
  const t0 = performance.now();
  const frame = (now: number) => {
    const t = Math.min(1, (now - t0) / ms);
    const eased = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    let left = 0;
    for (const m of going) {
      if (into.get(m.box) !== mine || Math.abs(m.box.scrollTop - m.held) > 1.5) continue;
      m.box.scrollTop = m.from + (aimAt(m.box, el, block) - m.from) * eased;
      m.held = m.box.scrollTop;
      left++;
    }
    if (left && t < 1) requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

/**
 * A box glided to a place in itself (its top, say), as glideInto brings something into view: for when what would be
 * aimed at is itself moving (Memory's rows sliding to a new order are drawn where they were until they get there).
 */
export function glideTo(box: HTMLElement | null | undefined, top: number): void {
  if (!box) return;
  const aim = () => Math.max(0, Math.min(box.scrollHeight - box.clientHeight, top));
  if (Math.abs(aim() - box.scrollTop) < 1) return;
  const g = glides.get(box);
  if (g?.raf) {
    cancelAnimationFrame(g.raf);
    g.raf = 0;
    g.ended = performance.now();
  }
  if (!get(motionEnabled)) {
    box.scrollTop = aim();
    return;
  }
  const mine = {};
  into.set(box, mine);
  const from = box.scrollTop;
  let held = from;
  const ms = Math.min(820, 380 + Math.abs(aim() - from) * 0.4);
  const t0 = performance.now();
  const frame = (now: number) => {
    // A wheel, a scrollbar or a key since: that wins.
    if (into.get(box) !== mine || Math.abs(box.scrollTop - held) > 1.5) return;
    const t = Math.min(1, (now - t0) / ms);
    const eased = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    box.scrollTop = from + (aim() - from) * eased;
    held = box.scrollTop;
    if (t < 1) requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

function onWheel(e: WheelEvent) {
  if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.shiftKey || !e.deltaY) return;
  if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
  if (!wanted() || !notched(e)) return;
  const dy = e.deltaMode === 1 ? e.deltaY * LINE : e.deltaMode === 2 ? e.deltaY * innerHeight * 0.9 : e.deltaY;
  const el = scrollerFor(e.target, dy);
  if (!el) return;
  e.preventDefault();
  if (el !== "hold") glide(el, dy);
}

let installed = false;

export function installSmoothScroll(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  // Last in line (the window, bubbling), so whatever answers the wheel itself has had it first.
  window.addEventListener("wheel", onWheel, { passive: false });
}
