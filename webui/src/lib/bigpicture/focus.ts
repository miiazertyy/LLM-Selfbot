/**
 * What has the focus in Big Picture, and the plate that glides under it.
 *
 * There is one highlight for the whole view, whatever is moving it: the pointer
 * passing over something, the arrow keys, or a gamepad. It is one soft plate of
 * the room's colour, on a spring, sliding from row to row and tile to tile with
 * a tick for each. Rows have no fill of their own, so the plate is what you see
 * move. It is told where to go rather than being a hover style on each thing,
 * which could only ever light up and go out.
 *
 * Put `use:focusable` on anything that can be pressed, and `use:focusPlate` on
 * the plate. The sum for where an arrow key lands is spatial.ts.
 *
 * It springs by transform alone (a FLIP: put where it goes, then animated from where
 * it was seen), on an element of its own, and the page is only read while something
 * is moving: it follows for a moment after each change, then rests.
 */
import { get, writable } from "svelte/store";
import { motionEnabled } from "../stores";
import { play } from "../uisound";
import { nextFocus, type Box, type Dir } from "./spatial";

export type { Dir } from "./spatial";
export type FocusOpts = {
  /** Who this is, so coming back to the page finds them again. */
  id?: string;
  /** The focus landed here: a shelf whose card follows its tile. */
  onfocus?: () => void;
  /** What the focus starts on when a page is opened from the keys. */
  first?: boolean;
  /** It has a sound of its own for this (an hour of the day has its note). */
  quiet?: boolean;
  /** There is nothing here to press: no focus, though it sits in a list of things that can be. */
  skip?: boolean;
};

const items = new Map<HTMLElement, FocusOpts>();
let current: HTMLElement | null = null;
let plate: HTMLElement | null = null;
let frame = 0;
let followUntil = 0;
let scrollingUntil = 0;
let leaving: ReturnType<typeof setTimeout> | null = null;
let lastBox: DOMRect | null = null;
/** The id it was last on, per page. */
const remembered = new Map<string, string>();

/** Which hand is on it: the hints say the keys for the keyboard and the buttons for a pad. */
export const inputMode = writable<"pointer" | "keys" | "pad">("pointer");
/** Where the focus is, as a share of the screen: the room's light drifts behind it. */
export const focusAt = writable<{ x: number; y: number } | null>(null);

const moving = () => get(motionEnabled);

/** A box cut to the scrolling list it is in, so the plate never shows past the list's edge. */
function boxOf(el: HTMLElement): { x: number; y: number; w: number; h: number } | null {
  const r = el.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  const list = el.closest<HTMLElement>(".bp-scrolls");
  let { left, top, right, bottom } = r;
  if (list) {
    const b = list.getBoundingClientRect();
    left = Math.max(left, b.left);
    top = Math.max(top, b.top);
    right = Math.min(right, b.right);
    bottom = Math.min(bottom, b.bottom);
    if (right - left < 2 || bottom - top < 2) return null;
  }
  return { x: left, y: top, w: right - left, h: bottom - top };
}

let shownX = NaN, shownY = NaN, shownW = NaN, shownH = NaN;
/** What the plate last went to: a new one is sprung to, the same one moving (a list scrolling) is followed exactly. */
let placedFor: HTMLElement | null = null;
let spring: Animation | null = null;
const springy = () => getComputedStyle(document.documentElement).getPropertyValue("--spring").trim() || "cubic-bezier(0.2, 0.9, 0.25, 1)";

function place() {
  frame = 0;
  const p = plate;
  if (!p) return;
  const box = current?.isConnected ? boxOf(current) : null;
  if (!box) {
    p.classList.remove("is-on");
    placedFor = null;
    focusAt.set(null);
  } else if (box.x !== shownX || box.y !== shownY || box.w !== shownW || box.h !== shownH || placedFor !== current) {
    const wasOff = !p.classList.contains("is-on");
    const springs = !wasOff && placedFor !== current && moving() && performance.now() >= scrollingUntil;
    // Where it is seen now, mid-flight too, read before that flight is stopped.
    const from = springs ? p.getBoundingClientRect() : null;
    spring?.cancel();
    spring = null;
    shownX = box.x;
    shownY = box.y;
    shownW = box.w;
    shownH = box.h;
    p.style.transform = `translate3d(${box.x}px, ${box.y}px, 0)`;
    p.style.width = `${box.w}px`;
    p.style.height = `${box.h}px`;
    p.style.borderRadius = getComputedStyle(current!).borderRadius;
    if (from && from.width > 1 && from.height > 1) {
      spring = p.animate([
        { transform: `translate3d(${from.left}px, ${from.top}px, 0) scale(${from.width / box.w}, ${from.height / box.h})` },
        { transform: `translate3d(${box.x}px, ${box.y}px, 0)` },
      ], { duration: 420, easing: springy() });
    }
    placedFor = current;
    if (typeof innerWidth === "number") focusAt.set({ x: (box.x + box.w / 2) / innerWidth, y: (box.y + box.h / 2) / innerHeight });
    if (wasOff) {
      void p.offsetWidth;
      p.classList.add("is-on");
    }
  }
  if (performance.now() < followUntil) frame = requestAnimationFrame(place);
}

/** Something may have moved under it: follow for a moment. */
export function follow(ms = 900) {
  followUntil = Math.max(followUntil, performance.now() + ms);
  if (!frame) frame = requestAnimationFrame(place);
}

/** Higher to the right and up the screen, so walking round plays a little tune of ticks. */
function pitch(el: HTMLElement): number {
  const r = el.getBoundingClientRect();
  return Math.max(0, Math.min(1, ((r.left + r.width / 2) / innerWidth + (1 - (r.top + r.height / 2) / innerHeight)) / 2));
}

/** The page something is on, for remembering where the focus was on it. */
const pageOf = (el: HTMLElement) => el.closest<HTMLElement>("[data-page]")?.dataset.page ?? "";

export function setFocus(el: HTMLElement | null, via: "pointer" | "keys" | "pad" = "keys", quiet = false) {
  if (leaving) {
    clearTimeout(leaving);
    leaving = null;
  }
  if (el === current) {
    if (el) follow();
    return;
  }
  current?.classList.remove("is-focus");
  current = el;
  if (el) {
    el.classList.add("is-focus");
    lastBox = el.getBoundingClientRect();
    const opts = items.get(el);
    const page = pageOf(el);
    if (opts?.id && page) remembered.set(page, opts.id);
    if (via !== "pointer") {
      el.scrollIntoView({ block: "nearest", inline: "nearest", behavior: moving() ? "smooth" : "auto" });
      scrollingUntil = 0;
    }
    if (!quiet && !opts?.quiet) play("tick", { p: pitch(el), level: via === "pointer" ? 0.4 : 1 });
    opts?.onfocus?.();
  }
  follow();
}

/** Nothing has it: the plate fades, and the arrow keys start from where it was. */
export function clearFocus() {
  setFocus(null);
  focusAt.set(null);
}

/** The ones that can be got to now, drawn and not on a page on its way out. */
function candidates(): HTMLElement[] {
  return [...items.keys()].filter((el) => !items.get(el)?.skip && el.isConnected && !el.closest("[data-leaving]") && el.getClientRects().length > 0);
}

/** An arrow key, or a pad's direction. At the edge of what there is, the plate bumps against it. */
export function moveFocus(dir: Dir, via: "keys" | "pad" = "keys") {
  inputMode.set(via);
  const els = candidates();
  if (!current?.isConnected) {
    const start = startOf(els);
    if (start) setFocus(start, via);
    return;
  }
  const boxes: Box[] = els.map((el, i) => {
    const r = el.getBoundingClientRect();
    return { id: String(i), x: r.left, y: r.top, w: r.width, h: r.height };
  });
  const next = nextFocus(boxes, String(els.indexOf(current)), dir);
  if (next != null) setFocus(els[Number(next)], via);
  else bump(dir);
}

function bump(dir: Dir) {
  play("seat", { strong: true, level: 0.6 });
  if (!plate || !moving() || !shownW) return;
  const dx = dir === "left" ? -9 : dir === "right" ? 9 : 0;
  const dy = dir === "up" ? -9 : dir === "down" ? 9 : 0;
  const at = `translate3d(${shownX}px, ${shownY}px, 0)`;
  plate.animate([{ transform: at }, { transform: `translate3d(${shownX + dx}px, ${shownY + dy}px, 0)`, offset: 0.35 }, { transform: at }],
                { duration: 260, easing: "cubic-bezier(0.3, 1.3, 0.5, 1)" });
}

/** Where the focus starts on the page in front: where it last was, what the page says, else the first thing on it. */
function startOf(els: HTMLElement[]): HTMLElement | null {
  const page = document.querySelector<HTMLElement>("[data-page]:not([data-leaving])");
  const onPage = page ? els.filter((el) => page.contains(el)) : els;
  const pool = onPage.length ? onPage : els;
  const id = page ? remembered.get(page.dataset.page ?? "") : undefined;
  const again = id ? pool.find((el) => items.get(el)?.id === id) : undefined;
  if (again) return again;
  const first = pool.find((el) => items.get(el)?.first);
  if (first) return first;
  return pool.slice().sort((a, b) => {
    const p = a.getBoundingClientRect(), q = b.getBoundingClientRect();
    return p.top - q.top || p.left - q.left;
  })[0] ?? null;
}

/** A page opened from the keys: the focus goes with it, so the arrows carry straight on. */
export function focusPage(via: "keys" | "pad" = "keys") {
  const start = startOf(candidates());
  if (start) setFocus(start, via, true);
}

/** Enter, or a pad's A: the same as pressing it, with the press seen and heard. */
export function pressFocus(): boolean {
  const el = current;
  if (!el?.isConnected) return false;
  if (el.matches("input, textarea")) {
    el.focus();
    return true;
  }
  if (moving()) {
    el.animate([{ transform: "scale(0.96)" }, { transform: "scale(1.012)", offset: 0.55 }, { transform: "none" }],
               { duration: 300, easing: "ease-out" });
  }
  play("tap");
  play("up", { delay: 70 });
  el.click();
  return true;
}

/** The action: this can have the focus. */
export function focusable(node: HTMLElement, opts: FocusOpts = {}) {
  items.set(node, opts);
  const enter = (e: PointerEvent) => {
    if (e.pointerType === "touch" || items.get(node)?.skip) return;
    inputMode.set("pointer");
    setFocus(node, "pointer");
  };
  const leave = (e: PointerEvent) => {
    if (e.pointerType === "touch" || get(inputMode) !== "pointer" || current !== node) return;
    // Not straight away: on its way to the next thing the pointer is over nothing for a moment.
    leaving = setTimeout(() => {
      leaving = null;
      if (current === node && get(inputMode) === "pointer") setFocus(null);
    }, 120);
  };
  node.addEventListener("pointerenter", enter);
  node.addEventListener("pointerleave", leave);
  return {
    update(next: FocusOpts = {}) {
      items.set(node, next);
    },
    destroy() {
      node.removeEventListener("pointerenter", enter);
      node.removeEventListener("pointerleave", leave);
      items.delete(node);
      if (current === node) {
        const was = lastBox;
        const mode = get(inputMode);
        current = null;
        // What it was on has gone (answered, or a card taken away): from the keys, on to whatever is nearest.
        if (mode !== "pointer" && was) {
          queueMicrotask(() => {
            if (current) return;
            const near = candidates().map((el) => ({ el, r: el.getBoundingClientRect() }))
              .sort((a, b) => Math.hypot(a.r.left - was.left, a.r.top - was.top) - Math.hypot(b.r.left - was.left, b.r.top - was.top))[0];
            if (near) setFocus(near.el, mode, true);
            else follow();
          });
        } else {
          follow();
        }
      }
    },
  };
}

/** The action for the plate: there is one, in the view. */
export function focusPlate(node: HTMLElement) {
  plate = node;
  const scrolled = () => {
    scrollingUntil = performance.now() + 120;
    follow(300);
  };
  const resized = () => follow(400);
  window.addEventListener("scroll", scrolled, { capture: true, passive: true });
  window.addEventListener("resize", resized, { passive: true });
  return {
    destroy() {
      window.removeEventListener("scroll", scrolled, { capture: true });
      window.removeEventListener("resize", resized);
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      spring = null;
      placedFor = null;
      plate = null;
      current = null;
      lastBox = null;
      items.clear();
      remembered.clear();
      shownX = shownY = shownW = shownH = NaN;
      focusAt.set(null);
      inputMode.set("pointer");
    },
  };
}
