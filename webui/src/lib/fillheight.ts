/**
 * A box sized to exactly the space left below it in the window, so what is in it scrolls on its own and its bottom
 * is always on screen: Chats' inbox, Memory's people and the one opened beside them. A sticky panel taller than what
 * was left below the header had its bottom (Chats' Reply button) start off screen; a list capped at a share of the
 * window stopped well short of the bottom, with the page going on under it.
 *
 * It sets `--fill-h` on the box, in pixels; the box's CSS says where that is used, so a narrow window, where the
 * columns stack and the page scrolls, can leave it alone. Anything above it changing size (a notice, a line that
 * comes and goes), the window and the page's scrolling area are all followed.
 *
 *   <div class="inbox" use:fillHeight>   .inbox { height: var(--fill-h, calc(100dvh - 120px)); }
 */
export function fillHeight(node: HTMLElement, min = 280) {
  const scroller = node.closest<HTMLElement>(".overflow-y-auto");
  const wrap = node.parentElement;
  let floor = min;
  let raf = 0;
  const set = () => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => {
      if (!scroller) return;
      // What the page keeps under its last box is part of the 16px left below this one, not added to it.
      const pb = wrap ? parseFloat(getComputedStyle(wrap).paddingBottom) || 0 : 0;
      node.style.marginBottom = `${16 - pb}px`;
      const top = node.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
      // A low floor: the pocket window is only about 600px tall, and a floor above what is left pushed Chats' Reply
      // button off the bottom.
      node.style.setProperty("--fill-h", `${Math.floor(Math.max(floor, scroller.clientHeight - top - 16))}px`);
    });
  };
  set();
  // Again once the tab has dropped into place (cascade.ts moves its blocks with a transform for up to ~0.7s, and a
  // box measured mid-drop comes out where it was drawn, not where it sits).
  const again = [window.setTimeout(set, 800), window.setTimeout(set, 1600)];
  const ro = new ResizeObserver(set);
  if (scroller) ro.observe(scroller);
  if (wrap) ro.observe(wrap);
  window.addEventListener("resize", set);
  return {
    update(next = 280) {
      floor = next;
      set();
    },
    destroy() {
      ro.disconnect();
      window.removeEventListener("resize", set);
      cancelAnimationFrame(raf);
      again.forEach(clearTimeout);
    },
  };
}
