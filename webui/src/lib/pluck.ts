/**
 * The marks round a clock stretch as a hand goes past them, and spring back.
 *
 * A hand sweeping round a dial used to slide over its marks as if they were
 * printed on. Now each one it passes reaches out after it for a moment, the
 * way the teeth of a comb flick as a finger runs along them: dragging makes a
 * little wave that follows the hand.
 *
 * The marks themselves are drawn as a few paths (all the small ones, all the
 * big ones), not one element each: a page of dials was hundreds of elements,
 * each redrawn as a hand crossed any of them, and opening such a page
 * stuttered. So a pluck draws a line of its own over the mark, stretches it
 * out and lets it go, and takes it away again.
 *
 * `passed` (lib/passed.ts) works out which marks a move went over.
 */
import { get } from "svelte/store";
import { motionEnabled } from "./stores";

export { passed } from "./passed";

let accent = "";
let watching = false;
/**
 * The accent, read once and kept until the theme changes it. Reading it for
 * every mark made the browser work out every style on the page again, dozens
 * of times a frame.
 */
function accentNow(): string {
  if (!accent) {
    accent = getComputedStyle(document.documentElement).getPropertyValue("--color-accent").trim() || "#fff";
    if (!watching) {
      watching = true;
      // A theme sets its colours on the root's style: forget the one kept.
      new MutationObserver(() => (accent = "")).observe(document.documentElement, { attributes: true, attributeFilter: ["style", "data-theme"] });
    }
  }
  return accent;
}

type Pt = { x: number; y: number };
const SVG = "http://www.w3.org/2000/svg";

/**
 * Pluck the mark from `a` (its inner end) to `b`: a line of its own over it,
 * lit, stretched out from its inner end and let go, then taken away. It
 * fades in and out, so it never shows a colour the mark under it does not.
 */
export function pluck(group: SVGGElement | null | undefined, a: Pt, b: Pt, width = 1, stretch = 1.9) {
  if (!group || !get(motionEnabled) || document.documentElement.dataset.motion === "off") return;
  const line = document.createElementNS(SVG, "line");
  line.setAttribute("x1", a.x.toFixed(2));
  line.setAttribute("y1", a.y.toFixed(2));
  line.setAttribute("x2", b.x.toFixed(2));
  line.setAttribute("y2", b.y.toFixed(2));
  line.setAttribute("stroke-width", String(width));
  line.setAttribute("stroke-linecap", "round");
  line.setAttribute("vector-effect", "non-scaling-stroke");
  // Lit like the marks inside a range are: the accent, whitened.
  line.style.stroke = `color-mix(in srgb, ${accentNow()} 65%, white)`;
  line.style.pointerEvents = "none";
  line.style.transformBox = "view-box";
  line.style.transformOrigin = `${a.x.toFixed(2)}px ${a.y.toFixed(2)}px`;
  group.appendChild(line);
  const anim = line.animate(
    [
      { transform: "scale(1)", opacity: 0 },
      { transform: `scale(${stretch})`, opacity: 1, offset: 0.26 },
      { transform: "scale(1)", opacity: 0 },
    ],
    { duration: 480, easing: "cubic-bezier(0.25, 0.8, 0.35, 1)" },
  );
  anim.onfinish = anim.oncancel = () => line.remove();
}

/** A set of marks as one path: "M x1 y1 L x2 y2" for each. */
export function marksPath(marks: { a: Pt; b: Pt }[]): string {
  let d = "";
  for (const m of marks) d += `M${m.a.x.toFixed(2)} ${m.a.y.toFixed(2)}L${m.b.x.toFixed(2)} ${m.b.y.toFixed(2)}`;
  return d;
}
