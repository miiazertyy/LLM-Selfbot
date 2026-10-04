/**
 * Drag a number to change it, as in a design tool: press on the field and
 * pull sideways, right for more and left for less, faster the further you go.
 * A click without a drag still puts the cursor in the box to type.
 *
 * For the settings that are amounts, times above all ("Global cooldown min
 * (s)", "Mood shift max (s)"): working one out digit by digit in a box was
 * the slow way to set "about ten minutes".
 */
export type ScrubOptions = {
  get: () => number;
  set: (v: number) => void;
  min?: number;
  max?: number;
  /** How much one notch is worth; or, for an amount of time, worked out from where it starts. */
  step?: number | ((from: number) => number);
  /** False for a number that is not an amount (an id, a build number): no dragging it by accident. */
  enabled?: boolean;
};

/**
 * Notches worth having for an amount of time, by how big it already is:
 * seconds near a minute, half minutes near an hour, whole minutes past it.
 */
export function timeStep(unit: string, from: number): number {
  const v = Math.abs(from);
  if (unit === "s") return v < 60 ? 1 : v < 600 ? 5 : v < 3600 ? 30 : v < 86400 ? 60 : 300;
  if (unit === "min") return v < 60 ? 1 : v < 600 ? 5 : 15;
  if (unit === "ms") return v < 1000 ? 25 : v < 10000 ? 100 : 500;
  if (unit === "h") return 1;
  return 1;
}

import { play } from "./uisound";

/** Pixels of drag before a press counts as one: a click with a shaky hand is still a click. */
const SLOP = 4;

export function scrub(node: HTMLElement, options: ScrubOptions) {
  let opts = options;
  let id = -1;
  let x0 = 0;
  let v0 = 0;
  let moved = false;

  function down(e: PointerEvent) {
    if (e.button !== 0 || opts.enabled === false) return;
    id = e.pointerId;
    x0 = e.clientX;
    v0 = Number(opts.get()) || 0;
    moved = false;
  }
  function move(e: PointerEvent) {
    if (e.pointerId !== id) return;
    const dx = e.clientX - x0;
    if (!moved) {
      if (Math.abs(dx) < SLOP) return;
      moved = true;
      node.setPointerCapture(id);
      node.classList.add("is-scrubbing");
      (document.activeElement as HTMLElement | null)?.blur?.();
      window.getSelection()?.removeAllRanges();
      play("grab");
    }
    e.preventDefault();
    // Gentle near where it started, quicker further out: small changes and big ones both in one drag.
    const notches = Math.sign(dx) * Math.round(Math.pow(Math.abs(dx) / 7, 1.4));
    const step = typeof opts.step === "function" ? opts.step(v0) : opts.step ?? 1;
    let v = v0 + notches * step;
    if (opts.min != null) v = Math.max(opts.min, v);
    if (opts.max != null) v = Math.min(opts.max, v);
    v = Math.round(v / step) * step;
    if (v !== Number(opts.get())) {
      opts.set(v);
      // A detent for each new value: higher as it is pulled up, lower as it is pulled down.
      play("tick", { p: Math.max(0, Math.min(1, 0.5 + dx / 400)) });
    }
  }
  function up(e: PointerEvent) {
    if (e.pointerId !== id) return;
    id = -1;
    if (moved) {
      play("release");
      node.classList.remove("is-scrubbing");
      if (node.hasPointerCapture(e.pointerId)) node.releasePointerCapture(e.pointerId);
      e.preventDefault();
    }
  }
  /** The click that ends a drag is not a click on the box. */
  function click(e: MouseEvent) {
    if (moved) {
      e.preventDefault();
      e.stopPropagation();
      moved = false;
    }
  }

  node.addEventListener("pointerdown", down);
  node.addEventListener("pointermove", move);
  node.addEventListener("pointerup", up);
  node.addEventListener("pointercancel", up);
  node.addEventListener("click", click, true);
  return {
    update(next: ScrubOptions) {
      opts = next;
    },
    destroy() {
      node.removeEventListener("pointerdown", down);
      node.removeEventListener("pointermove", move);
      node.removeEventListener("pointerup", up);
      node.removeEventListener("pointercancel", up);
      node.removeEventListener("click", click, true);
    },
  };
}
