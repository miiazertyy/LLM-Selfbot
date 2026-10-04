/**
 * Bringing a row of a dropdown's list into view without moving the page.
 *
 * scrollIntoView scrolls every scrolling box around the row, the page among
 * them, and focusing the list's search box does the same: a dropdown opened
 * low on a page sent the page jumping up to it and back, as if teleported
 * behind it. Only the list itself scrolls here, and focusing never scrolls.
 */

/** The box that scrolls the row: the nearest one around it, no further out than `within`. */
function scroller(item: HTMLElement, within: HTMLElement): HTMLElement | null {
  for (let el = item.parentElement; el; el = el.parentElement) {
    const oy = getComputedStyle(el).overflowY;
    if ((oy === "auto" || oy === "scroll") && el.scrollHeight > el.clientHeight) return el;
    if (el === within) break;
  }
  return null;
}

/** Scrolls `list` so that `item` shows: in the middle ("center"), or just enough ("nearest"). */
export function showInList(list: HTMLElement | null | undefined, item: HTMLElement | null | undefined,
                           how: "center" | "nearest" = "nearest"): void {
  if (!list || !item) return;
  const box = scroller(item, list);
  if (!box) return;
  const b = box.getBoundingClientRect();
  const i = item.getBoundingClientRect();
  if (how === "center") box.scrollTop += i.top - b.top - (b.height - i.height) / 2;
  else if (i.top < b.top) box.scrollTop += i.top - b.top;
  else if (i.bottom > b.bottom) box.scrollTop += i.bottom - b.bottom;
}

/** Focus, without the page scrolling to whatever took it. */
export function focusStill(el: HTMLElement | null | undefined): void {
  el?.focus({ preventScroll: true });
}
