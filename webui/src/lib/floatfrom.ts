/**
 * A picker's open list, lifted out to the end of <body> and placed against its box: fixed, right edges lined up,
 * under the box or over it (`up`). Left where it was, inside its Settings row, it was drawn under whatever came
 * after it in the page: a row is a stacking context of its own (container-type), so no z-index of the list's could
 * lift it over the subtabs strip, whose words showed through the list. Like Select's list, which lives at the end of
 * <body> too, it closes when the page scrolls under it or the window changes size, rather than hang where the box
 * was. A click in it is not a click outside its box: ask `node.contains` as well as the box's.
 */
export function floatFrom(
  node: HTMLElement,
  opts: { anchor: HTMLElement | null; up: boolean; onaway: () => void; align?: "left" | "right" },
) {
  const { anchor, up, onaway, align = "right" } = opts;
  document.body.appendChild(node);
  const r = anchor?.getBoundingClientRect();
  if (r) {
    node.style.position = "fixed";
    // Lined up with its box's right edge, or (a button at the start of a line, Memory's "Link an account") its left.
    if (align === "left") node.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - node.offsetWidth - 8))}px`;
    else node.style.right = `${Math.max(8, window.innerWidth - r.right)}px`;
    if (up) node.style.bottom = `${window.innerHeight - r.top + 6}px`;
    else node.style.top = `${r.bottom + 6}px`;
  }
  // Its own list scrolling is not the page scrolling.
  const scroll = (e: Event) => {
    if (!node.contains(e.target as Node)) onaway();
  };
  const resize = () => onaway();
  // After the scrolls opening it makes (the list brought to the chosen one).
  const t = setTimeout(() => window.addEventListener("scroll", scroll, true), 0);
  window.addEventListener("resize", resize);
  return {
    destroy() {
      clearTimeout(t);
      window.removeEventListener("scroll", scroll, true);
      window.removeEventListener("resize", resize);
      node.remove();
    },
  };
}
