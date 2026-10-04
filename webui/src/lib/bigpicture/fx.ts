/**
 * Big Picture Mode's little rewards: sparks thrown from the thing that just
 * happened, and a ripple where a card was pressed.
 *
 * A reply going out, a friend accepted, a mood switched: each is a moment worth
 * a small flourish, so doing something here feels like it landed. Plain
 * elements animated with the Web Animations API, transform and opacity only,
 * so it all composites; each removes itself when it lands. Nothing at all with
 * the motion setting off, or while Big Picture is closing.
 */
import { get } from "svelte/store";
import { bigPictureExit, motionEnabled } from "../stores";

export type BurstOpts = {
  /** How many sparks. */
  count?: number;
  /** How far they fly, in px. */
  spread?: number;
  /** CSS colours, taken in turn. */
  colors?: string[];
  /** Spark size in px. */
  size?: number;
};

const still = () => typeof document === "undefined" || !get(motionEnabled) || bigPictureExit.on;

/** Sparks from a point on the screen. */
export function burst(x: number, y: number, opts: BurstOpts = {}): void {
  if (still()) return;
  const {
    count = 18,
    spread = 120,
    colors = ["var(--color-accent)", "var(--color-good)", "#fff", "color-mix(in srgb, var(--color-accent) 50%, #fbbf24)"],
    size = 7,
  } = opts;
  // Over Big Picture (z-index 200), never catching the pointer.
  const layer = document.createElement("div");
  layer.setAttribute("aria-hidden", "true");
  layer.style.cssText = `position:fixed;left:${x}px;top:${y}px;width:0;height:0;pointer-events:none;z-index:260;`;
  document.body.appendChild(layer);
  let longest = 0;
  for (let i = 0; i < count; i++) {
    const p = document.createElement("i");
    const angle = (Math.PI * 2 * i) / count + (Math.random() - 0.5) * 0.7;
    const far = spread * (0.45 + Math.random() * 0.55);
    const s = size * (0.6 + Math.random() * 0.8);
    // Mostly dots, some slivers of confetti that tumble.
    const dot = Math.random() < 0.6;
    const w = s, h = dot ? s : s * 0.42;
    p.style.cssText = `position:absolute;left:${-w / 2}px;top:${-h / 2}px;width:${w}px;height:${h}px;`
      + `border-radius:${dot ? 999 : 2}px;background:${colors[i % colors.length]};will-change:transform,opacity;`;
    layer.appendChild(p);
    const dx = Math.cos(angle) * far, dy = Math.sin(angle) * far;
    const spin = (Math.random() - 0.5) * 540;
    const dur = 650 + Math.random() * 450;
    longest = Math.max(longest, dur);
    p.animate(
      [
        { transform: "translate(0px, 0px) scale(0.3) rotate(0deg)", opacity: 1 },
        { transform: `translate(${dx * 0.82}px, ${dy * 0.82}px) scale(1) rotate(${spin * 0.6}deg)`, opacity: 1, offset: 0.55 },
        // then gravity: a little fall as they fade
        { transform: `translate(${dx}px, ${dy + 36}px) scale(0.55) rotate(${spin}deg)`, opacity: 0 },
      ],
      { duration: dur, easing: "cubic-bezier(.15,.75,.3,1)", fill: "forwards" },
    );
  }
  setTimeout(() => layer.remove(), longest + 80);
}

/** Sparks from the middle of an element. */
export function burstFrom(el: Element | null | undefined, opts?: BurstOpts): void {
  if (!el) return;
  const r = el.getBoundingClientRect();
  burst(r.left + r.width / 2, r.top + r.height / 2, opts);
}

/** An action: sparks the moment the element appears, like the check when a reply has gone. */
export function sparkOnMount(node: HTMLElement, opts: BurstOpts = {}) {
  const id = requestAnimationFrame(() => burstFrom(node, opts));
  return { destroy: () => cancelAnimationFrame(id) };
}

/**
 * An action: a ripple from wherever the element is pressed. The element needs
 * `position: relative` and `overflow: hidden` for it to stay inside.
 */
export function ripple(node: HTMLElement, color = "color-mix(in srgb, var(--color-accent) 55%, white)") {
  function down(e: PointerEvent) {
    if (still()) return;
    const r = node.getBoundingClientRect();
    const dot = document.createElement("span");
    dot.setAttribute("aria-hidden", "true");
    dot.style.cssText = `position:absolute;left:${e.clientX - r.left - 12}px;top:${e.clientY - r.top - 12}px;`
      + `width:24px;height:24px;border-radius:999px;pointer-events:none;background:${color};`;
    node.appendChild(dot);
    dot
      .animate([{ transform: "scale(0)", opacity: 0.5 }, { transform: "scale(16)", opacity: 0 }],
               { duration: 700, easing: "ease-out", fill: "forwards" })
      .finished.then(() => dot.remove(), () => dot.remove());
  }
  node.addEventListener("pointerdown", down);
  return { destroy: () => node.removeEventListener("pointerdown", down) };
}

/**
 * An action: `fn` on every movement or press of the pointer over the element.
 * Listening only, the element does not become something to click, which is
 * why this is an action rather than handlers on a plain section.
 */
export function pointerActivity(node: HTMLElement, fn: () => void) {
  let call = fn;
  const on = () => call();
  node.addEventListener("pointermove", on);
  node.addEventListener("pointerdown", on);
  return {
    update(next: () => void) {
      call = next;
    },
    destroy() {
      node.removeEventListener("pointermove", on);
      node.removeEventListener("pointerdown", on);
    },
  };
}

/**
 * An action: the card leans towards the pointer, a few degrees, and a light
 * follows it across. Settles back flat when the pointer leaves. Off with the
 * motion setting.
 */
export function tilt(node: HTMLElement, max = 5) {
  let frame = 0;
  let ev: PointerEvent | null = null;
  function apply() {
    frame = 0;
    if (!ev) return;
    const r = node.getBoundingClientRect();
    const x = (ev.clientX - r.left) / r.width - 0.5;
    const y = (ev.clientY - r.top) / r.height - 0.5;
    node.style.setProperty("--tx", `${(-y * max).toFixed(2)}deg`);
    node.style.setProperty("--ty", `${(x * max).toFixed(2)}deg`);
    node.style.setProperty("--lx", `${((x + 0.5) * 100).toFixed(1)}%`);
    node.style.setProperty("--ly", `${((y + 0.5) * 100).toFixed(1)}%`);
  }
  function move(e: PointerEvent) {
    if (still()) return;
    ev = e;
    if (!frame) frame = requestAnimationFrame(apply);
  }
  function leave() {
    ev = null;
    node.style.setProperty("--tx", "0deg");
    node.style.setProperty("--ty", "0deg");
  }
  node.addEventListener("pointermove", move);
  node.addEventListener("pointerleave", leave);
  return {
    destroy() {
      node.removeEventListener("pointermove", move);
      node.removeEventListener("pointerleave", leave);
      if (frame) cancelAnimationFrame(frame);
    },
  };
}
