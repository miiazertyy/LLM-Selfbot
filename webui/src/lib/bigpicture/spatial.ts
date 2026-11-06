/**
 * Which thing an arrow key lands on: the nearest one that way, on the screen as it is drawn.
 *
 * The same sum a console's home screen does. Whatever lies that way counts, and
 * the one straight ahead beats a nearer one off to the side, so going down a
 * column stays in the column and going across a shelf stays on the shelf.
 *
 * A plain function of plain boxes, so it runs under Node in tests/bigpicture_director.mjs.
 */
export type Dir = "up" | "down" | "left" | "right";
export type Box = { id: string; x: number; y: number; w: number; h: number };

/** How much being off to the side counts against one, next to being further ahead. */
const SIDEWAYS = 4;

/** The gap between two spans, 0 when they overlap. */
const gap = (a0: number, a1: number, b0: number, b1: number) => Math.max(0, Math.max(a0, b0) - Math.min(a1, b1));

/** The one to go to from `from` in that direction, or null when there is nothing that way. */
export function nextFocus(boxes: Box[], from: string | null, dir: Dir): string | null {
  const a = boxes.find((b) => b.id === from);
  // Nothing has the focus yet: the first thing there is, reading from the top left.
  if (!a) return boxes.slice().sort((p, q) => p.y - q.y || p.x - q.x)[0]?.id ?? null;
  const across = dir === "left" || dir === "right";
  const sign = dir === "right" || dir === "down" ? 1 : -1;
  let best: string | null = null;
  let bestCost = Infinity;
  for (const b of boxes) {
    if (b.id === a.id) continue;
    // Past where this one stands, by its middle: something merely overlapping it is not "that way".
    const passed = across ? b.x + b.w / 2 - (a.x + a.w / 2) : b.y + b.h / 2 - (a.y + a.h / 2);
    if (passed * sign <= 1) continue;
    const ahead = across
      ? (sign > 0 ? b.x - (a.x + a.w) : a.x - (b.x + b.w))
      : (sign > 0 ? b.y - (a.y + a.h) : a.y - (b.y + b.h));
    const off = across ? gap(a.y, a.y + a.h, b.y, b.y + b.h) : gap(a.x, a.x + a.w, b.x, b.x + b.w);
    // Between two straight ahead, the one more nearly in line.
    const drift = across ? Math.abs(a.y + a.h / 2 - (b.y + b.h / 2)) : Math.abs(a.x + a.w / 2 - (b.x + b.w / 2));
    const cost = Math.max(0, ahead) + off * SIDEWAYS + drift * 0.1;
    if (cost < bestCost) {
      bestCost = cost;
      best = b.id;
    }
  }
  return best;
}
