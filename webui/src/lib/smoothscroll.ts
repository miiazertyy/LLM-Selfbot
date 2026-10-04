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
 * It has its own switch (Settings, Appearance, Interface: "Smooth scrolling"),
 * apart from Animations: off, the wheel is the browser's own.
 */
import { get } from "svelte/store";
import { smoothScroll } from "./stores";

/** How quickly a glide catches up with where the wheel has sent it: about this many seconds to close two thirds. */
const TAU = 0.09;
/** What one line of a line-based wheel is worth, in pixels. */
const LINE = 40;

type Glide = { el: HTMLElement; target: number; pos: number; held: number; last: number; raf: number };
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

/** The box the wheel should move: the nearest one under the pointer that can still go that way. */
function scrollerFor(target: EventTarget | null, dy: number): HTMLElement | null {
  for (let el = target instanceof Element ? target : null; el; el = el.parentElement) {
    if (!(el instanceof HTMLElement)) continue;
    const root = el === document.scrollingElement;
    if (!root && !canScrollY(el)) continue;
    if (root && el.scrollHeight <= el.clientHeight + 1) continue;
    const max = el.scrollHeight - el.clientHeight;
    const at = aim(el);
    if ((dy > 0 && at < max - 0.5) || (dy < 0 && at > 0.5)) return el;
    // At its end that way, and keeping its scroll to itself: nothing behind it moves.
    if (!root && getComputedStyle(el).overscrollBehaviorY !== "auto") return null;
  }
  return null;
}

function step(g: Glide, now: number) {
  // Moved by something else since the last frame (its scrollbar, a key, the page going back to the top): that wins.
  if (Math.abs(g.el.scrollTop - g.held) > 1.5) {
    g.raf = 0;
    return;
  }
  const dt = Math.min(0.064, (now - g.last) / 1000);
  g.last = now;
  g.pos += (g.target - g.pos) * (1 - Math.exp(-dt / TAU));
  if (Math.abs(g.target - g.pos) < 0.5) g.pos = g.target;
  g.el.scrollTop = g.pos;
  // What the box holds after rounding to its pixels, to tell our own moves from anyone else's.
  g.held = g.el.scrollTop;
  g.raf = g.pos === g.target ? 0 : requestAnimationFrame((t) => step(g, t));
}

function glide(el: HTMLElement, dy: number) {
  let g = glides.get(el);
  if (!g || !g.raf) {
    g = { el, target: el.scrollTop, pos: el.scrollTop, held: el.scrollTop, last: performance.now(), raf: 0 };
    glides.set(el, g);
  }
  const max = el.scrollHeight - el.clientHeight;
  g.target = Math.max(0, Math.min(max, g.target + dy));
  if (!g.raf) {
    g.last = performance.now();
    g.raf = requestAnimationFrame((t) => step(g!, t));
  }
}

function onWheel(e: WheelEvent) {
  if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.shiftKey || !e.deltaY) return;
  if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
  if (!wanted() || !notched(e)) return;
  const dy = e.deltaMode === 1 ? e.deltaY * LINE : e.deltaMode === 2 ? e.deltaY * innerHeight * 0.9 : e.deltaY;
  const el = scrollerFor(e.target, dy);
  if (!el) return;
  e.preventDefault();
  glide(el, dy);
}

let installed = false;

export function installSmoothScroll(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  // Last in line (the window, bubbling), so whatever answers the wheel itself has had it first.
  window.addEventListener("wheel", onWheel, { passive: false });
}
