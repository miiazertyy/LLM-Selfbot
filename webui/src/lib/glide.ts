/**
 * A highlight that glides to the chosen one of a row of tabs, rather than each
 * tab lighting up on its own: the way the sidebar's does, and a dropdown's.
 *
 * Put on the row (`use:glide={key}`, the key being whatever says which is
 * chosen); the row holds an element with the class `glide-mark`, which is
 * moved and sized to the child marked `.is-active`. It goes there at once the
 * first time, and springs there after (the transition is the CSS's). The row
 * can wrap onto a second line: it moves across and down. It follows the row's
 * own size changing too (a window narrower, a count appearing).
 */
export function glide(node: HTMLElement, _key?: unknown) {
  let frame = 0;
  let placed = false;

  function place() {
    frame = 0;
    const mark = node.querySelector<HTMLElement>(":scope > .glide-mark");
    const active = node.querySelector<HTMLElement>(":scope > .is-active");
    if (!mark) return;
    if (!active) {
      mark.style.opacity = "0";
      return;
    }
    // Offsets inside the row, which is what the mark is positioned against: a scrolled row carries both along.
    mark.style.setProperty("--gx", `${active.offsetLeft}px`);
    mark.style.setProperty("--gy", `${active.offsetTop}px`);
    mark.style.setProperty("--gw", `${active.offsetWidth}px`);
    mark.style.setProperty("--gh", `${active.offsetHeight}px`);
    mark.style.opacity = "1";
    if (!placed) {
      // The first time: there, not travelling in from the corner.
      mark.classList.add("is-snap");
      void mark.offsetWidth;
      requestAnimationFrame(() => mark.classList.remove("is-snap"));
      placed = true;
    }
  }
  const soon = () => {
    if (!frame) frame = requestAnimationFrame(place);
  };

  const ro = new ResizeObserver(soon);
  ro.observe(node);
  soon();
  return {
    update() {
      soon();
    },
    destroy() {
      ro.disconnect();
      cancelAnimationFrame(frame);
    },
  };
}
