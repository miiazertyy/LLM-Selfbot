/**
 * A one-line heading that shrinks until it fits its box.
 *
 * The CSS decides how big the heading may be; this only makes it smaller, down
 * to `min` pixels, when the text is wider than the room it has. Past that the
 * ellipsis in the CSS takes over. One line of text grows in proportion to its
 * font size, so one measurement gives the size that fits, and a pixel or two
 * off is trimmed after.
 *
 * The box it sits in must not take its width from the text (a stretched block,
 * or a flex item with a basis of 0), or a smaller font would give it less room.
 */
export function fitText(node: HTMLElement, opts: { min?: number; text?: string } = {}) {
  let min = opts.min ?? 26;
  let frame = 0;

  function fit() {
    frame = 0;
    node.style.fontSize = "";
    const max = parseFloat(getComputedStyle(node).fontSize) || 0;
    const room = node.clientWidth;
    if (!max || room <= 0 || node.scrollWidth <= room) return;
    let size = Math.max(min, Math.floor((max * room) / node.scrollWidth));
    node.style.fontSize = `${size}px`;
    for (let i = 0; i < 6 && size > min && node.scrollWidth > node.clientWidth; i++) {
      size -= 1;
      node.style.fontSize = `${size}px`;
    }
  }
  // Measured on the next frame, never inside the observer's own callback:
  // resizing what it watches from there is what makes it report a loop.
  const later = () => {
    if (!frame) frame = requestAnimationFrame(fit);
  };
  const watch = new ResizeObserver(later);
  watch.observe(node);
  fit();

  return {
    update(next: { min?: number; text?: string } = {}) {
      min = next.min ?? 26;
      later();
    },
    destroy() {
      watch.disconnect();
      if (frame) cancelAnimationFrame(frame);
    },
  };
}
