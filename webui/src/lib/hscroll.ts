/**
 * A horizontal strip you can actually scroll, with a bar that stays out of the
 * way until you need it.
 *
 * Two problems this fixes, both of them on the Settings tabs.
 *
 * The native bar. Below 1024px the tab rail showed a real 3px scrollbar, which
 * sat in the layout permanently and pushed the subtabs down for the sake of
 * something you look at once. Scrollbar pseudo-elements cannot be animated
 * either, so it could not fade or grow: it was either there or it was not. The
 * bar here is an ordinary element, positioned out of the flow so it costs no
 * space at all, and it can therefore be animated like anything else. It shows
 * while you are pointing at the strip or scrolling it, and fades out after.
 *
 * No way to scroll. The subtab strip overflowed with no visible bar, no drag
 * and no wheel handling, so on a desktop with a mouse the tabs past the right
 * edge were simply unreachable. There are three ways to move it now: drag it,
 * roll the wheel over it, or drag the bar itself.
 *
 * Everything is done by writing to the DOM directly. An earlier version of the
 * slider animation kept its state in a Svelte rune that was read inside an
 * {#each}, which invalidated every row on every frame and made the whole app
 * crawl. A scroll handler runs far more often than that, so it never touches
 * framework state.
 *
 * Markup contract: the node must sit inside an element with class "hscroll",
 * which is what the bar is positioned against.
 */

type Options = {
  /** How long the bar stays up after the last scroll, in ms. */
  linger?: number;
};

export function hscroll(node: HTMLElement, options: Options = {}) {
  const linger = options.linger ?? 900;
  const host = node.parentElement;
  if (!host) return {};

  const bar = document.createElement("div");
  bar.className = "hscroll-bar";
  bar.setAttribute("aria-hidden", "true");
  const thumb = document.createElement("div");
  thumb.className = "hscroll-thumb";
  bar.appendChild(thumb);
  host.appendChild(bar);

  let frame = 0;
  let hideTimer: number | null = null;
  let scrollable = false;

  function measure() {
    const span = node.scrollWidth - node.clientWidth;
    scrollable = span > 2;
    // Nothing to scroll means no bar at all, rather than a full width thumb
    // that looks like a control and does nothing.
    host!.classList.toggle("can-scroll", scrollable);
    if (!scrollable) {
      // Cleared rather than left alone: a strip that stops overflowing keeps
      // whatever width it was last given, and the stale value reappears the
      // moment it overflows again, before the first frame can correct it.
      thumb.style.width = "0px";
      thumb.style.transform = "translateX(0)";
      return;
    }
    const ratio = node.clientWidth / node.scrollWidth;
    const width = Math.max(18, node.clientWidth * ratio);
    const travel = node.clientWidth - width;
    const at = span > 0 ? node.scrollLeft / span : 0;
    thumb.style.width = `${width}px`;
    thumb.style.transform = `translateX(${at * travel}px)`;
  }

  function schedule() {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      measure();
    });
  }

  /** Keep the bar up while things are moving, then let it go. */
  function flash() {
    host!.classList.add("is-scrolling");
    if (hideTimer !== null) clearTimeout(hideTimer);
    hideTimer = window.setTimeout(() => host!.classList.remove("is-scrolling"), linger);
  }

  function onScroll() {
    schedule();
    flash();
  }

  /**
   * A wheel over a horizontal strip should move it sideways.
   *
   * A mouse wheel only reports deltaY, so without this there is no way to reach
   * the far end of the strip short of dragging it. A trackpad's sideways swipe
   * arrives as deltaX and is left alone, and a wheel at either end is left to
   * the page so the whole thing does not become a scroll trap.
   */
  function onWheel(e: WheelEvent) {
    if (!scrollable || e.ctrlKey) return;
    if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
    const span = node.scrollWidth - node.clientWidth;
    const next = node.scrollLeft + e.deltaY;
    if ((e.deltaY < 0 && node.scrollLeft <= 0) || (e.deltaY > 0 && node.scrollLeft >= span)) return;
    e.preventDefault();
    node.scrollLeft = next;
  }

  // ── Dragging the strip itself ──────────────────────────────────────────────
  let dragging = false;
  let startX = 0;
  let startScroll = 0;
  let moved = false;

  function onPointerDown(e: PointerEvent) {
    if (!scrollable || e.button !== 0) return;
    dragging = true;
    moved = false;
    startX = e.clientX;
    startScroll = node.scrollLeft;
  }

  function onPointerMove(e: PointerEvent) {
    if (!dragging) return;
    const dx = e.clientX - startX;
    if (!moved && Math.abs(dx) > 3) {
      moved = true;
      node.setPointerCapture?.(e.pointerId);
      host!.classList.add("is-dragging");
    }
    if (moved) node.scrollLeft = startScroll - dx;
  }

  function onPointerUp(e: PointerEvent) {
    if (!dragging) return;
    dragging = false;
    node.releasePointerCapture?.(e.pointerId);
    host!.classList.remove("is-dragging");
  }

  /** A drag must not also count as clicking the tab under the cursor. */
  function onClickCapture(e: MouseEvent) {
    if (moved) {
      e.preventDefault();
      e.stopPropagation();
      moved = false;
    }
  }

  // ── Dragging the bar ───────────────────────────────────────────────────────
  let barDragging = false;

  function seek(clientX: number) {
    const box = bar.getBoundingClientRect();
    const width = thumb.getBoundingClientRect().width;
    const travel = Math.max(1, box.width - width);
    const at = (clientX - box.left - width / 2) / travel;
    node.scrollLeft = Math.max(0, Math.min(1, at)) * (node.scrollWidth - node.clientWidth);
  }

  function onBarDown(e: PointerEvent) {
    if (!scrollable || e.button !== 0) return;
    barDragging = true;
    bar.setPointerCapture?.(e.pointerId);
    host!.classList.add("is-dragging");
    seek(e.clientX);
    e.preventDefault();
  }

  function onBarMove(e: PointerEvent) {
    if (!barDragging) return;
    seek(e.clientX);
  }

  function onBarUp(e: PointerEvent) {
    if (!barDragging) return;
    barDragging = false;
    bar.releasePointerCapture?.(e.pointerId);
    host!.classList.remove("is-dragging");
  }

  node.addEventListener("scroll", onScroll, { passive: true });
  node.addEventListener("wheel", onWheel, { passive: false });
  node.addEventListener("pointerdown", onPointerDown);
  node.addEventListener("pointermove", onPointerMove);
  node.addEventListener("pointerup", onPointerUp);
  node.addEventListener("pointercancel", onPointerUp);
  node.addEventListener("click", onClickCapture, true);
  bar.addEventListener("pointerdown", onBarDown);
  bar.addEventListener("pointermove", onBarMove);
  bar.addEventListener("pointerup", onBarUp);
  bar.addEventListener("pointercancel", onBarUp);

  // The strip changes width when the window does, and its contents change when
  // you switch tabs, so both are watched rather than measured once.
  const ro = new ResizeObserver(schedule);
  ro.observe(node);
  for (const child of Array.from(node.children)) ro.observe(child);

  measure();

  return {
    update() {
      schedule();
    },
    destroy() {
      ro.disconnect();
      if (frame) cancelAnimationFrame(frame);
      if (hideTimer !== null) clearTimeout(hideTimer);
      node.removeEventListener("scroll", onScroll);
      node.removeEventListener("wheel", onWheel);
      node.removeEventListener("pointerdown", onPointerDown);
      node.removeEventListener("pointermove", onPointerMove);
      node.removeEventListener("pointerup", onPointerUp);
      node.removeEventListener("pointercancel", onPointerUp);
      node.removeEventListener("click", onClickCapture, true);
      bar.remove();
    },
  };
}
