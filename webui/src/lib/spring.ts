/**
 * The little spring on a slider's value, done without framework state.
 *
 * This was a `$state` record keyed by field, read inside the row template. A
 * range input fires `input` about sixty times a second while you drag, and
 * every one of those wrote to that shared record, which invalidated every row
 * that read it: with the full settings list open that is eighty rows
 * re-rendering sixty times a second, and the whole app crawled.
 *
 * A class on one DOM node costs nothing and cannot invalidate anything, so the
 * animation is the same and the cost is gone.
 */

type Options = { ms?: number; target?: string };

export function springValue(node: HTMLElement, options: Options = {}) {
  const ms = options.ms ?? 180;
  const selector = options.target ?? ".slider-value";
  let timer: number | null = null;

  function find(): HTMLElement | null {
    // The readout is a sibling, or a sibling of an ancestor when the row wraps.
    return (node.parentElement?.querySelector(selector) as HTMLElement | null)
      ?? (node.closest("[data-slider-row]")?.querySelector(selector) as HTMLElement | null);
  }

  function bump() {
    const el = find();
    if (!el) return;
    el.classList.add("is-bumped");
    if (timer !== null) clearTimeout(timer);
    timer = window.setTimeout(() => el.classList.remove("is-bumped"), ms);
  }

  node.addEventListener("input", bump);
  return {
    destroy() {
      node.removeEventListener("input", bump);
      if (timer !== null) clearTimeout(timer);
    },
  };
}
