/**
 * A box gliding to its new height when what is in it changes, instead of jumping there and taking everything under it
 * with it. Put it on the box, whose one child is what changes: the child is measured and the box moved to fit, with
 * nothing else to think about. With the app's Animations off, it simply is the new height.
 *
 * The box's height is animated for as long as it moves, which lays out what is under it each frame: this is for
 * a change now and then, not for something that never stops. A change arriving part way goes on from where it is.
 */
import { get } from "svelte/store";
import { motionEnabled } from "./stores";

export function smoothHeight(node: HTMLElement, opts: { duration?: number } = {}) {
  const inner = node.firstElementChild as HTMLElement | null;
  if (!inner || typeof ResizeObserver === "undefined") return;
  // What the box has round its child: padding, and an edge if it has one.
  const around = node.offsetHeight - inner.offsetHeight;
  let height = node.offsetHeight;
  let moving: Animation | null = null;

  const seen = new ResizeObserver(() => {
    const to = inner.offsetHeight + around;
    if (to === height) return;
    const from = moving ? node.getBoundingClientRect().height : height;
    height = to;
    moving?.cancel();
    moving = null;
    if (!get(motionEnabled)) return;
    const now = node.animate([{ height: `${from}px` }, { height: `${to}px` }], {
      duration: opts.duration ?? 360,
      easing: "cubic-bezier(0.22, 0.8, 0.3, 1)",
    });
    moving = now;
    now.onfinish = () => {
      if (moving === now) moving = null;
    };
  });
  seen.observe(inner);
  return {
    destroy() {
      seen.disconnect();
      moving?.cancel();
    },
  };
}
