/**
 * A menu unrolling out of the button it hangs from, rather than popping in.
 *
 * Put `use:unroll` on a menu with the class `unroll` (app.css draws it), and `is-up` as well when it opens upwards
 * from a button under it. The menu grows from the end nearest its button to its whole size, its corners round all
 * the way, and then its shadow spreads out from under it. Each row (each child, or each match of `rows`) fades in as
 * the edge reaches it: its turn is worked out here from where it sits, on the curve app.css gives the edge, so no
 * row shows before the menu is there behind it, and a row that is not there leaves no pause. Nothing overshoots:
 * these menus used to jelly-pop in like a dialog, which read as a pop, not a menu opening.
 */

/** How the edge moves (app.css, @keyframes unroll-down and unroll-up): from the first 40px to the whole menu in
    240ms, on an ease-out cubic. Change one, change both. */
export const UNROLL = { from: 40, ms: 240 };

export function unroll(node: HTMLElement, rows = ":scope > *") {
  const up = node.classList.contains("is-up");
  // Measured where they are on the screen, not by offsetTop: a row can sit in a list inside the menu (Select's,
  // which scrolls), where offsetTop counts from the list.
  const box = node.getBoundingClientRect();
  const span = Math.max(1, box.height + 1 - UNROLL.from);
  // The clip follows the menu's own corners, a pixel out to take in its ring.
  node.style.setProperty("--unroll-r", `${(parseFloat(getComputedStyle(node).borderTopLeftRadius) || 0) + 1}px`);
  for (const row of node.querySelectorAll<HTMLElement>(rows)) {
    const r = row.getBoundingClientRect();
    // How far the edge has to come for the row to start showing, and when the curve gets it there.
    const far = up ? box.bottom - r.bottom : r.top - box.top;
    const at = Math.min(1, Math.max(0, (far + r.height * 0.3 - UNROLL.from) / span));
    row.style.setProperty("--d", `${Math.round(UNROLL.ms * (1 - Math.cbrt(1 - at)))}ms`);
    row.dataset.unroll = "";
  }
}
