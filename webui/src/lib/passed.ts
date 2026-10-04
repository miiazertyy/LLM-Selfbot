/**
 * Which marks round a dial a hand went past (lib/pluck.ts plucks them). Apart
 * from pluck.ts, which needs the page, so it can be tested on its own.
 */

/**
 * The marks a hand went past moving from `from` to `to`, as whole numbers k
 * for the marks at k * every. Each is counted once: a mark is passed when the
 * hand lands on it or goes beyond, not again when the hand leaves it.
 */
export function passed(from: number, to: number, every = 1): number[] {
  if (!isFinite(from) || !isFinite(to) || from === to || every <= 0) return [];
  const e = 1e-9;
  const out: number[] = [];
  if (to > from) {
    for (let k = Math.floor(from / every + e) + 1; k <= Math.floor(to / every + e); k++) out.push(k);
  } else {
    for (let k = Math.ceil(from / every - e) - 1; k >= Math.ceil(to / every - e); k--) out.push(k);
  }
  // A jump across the whole dial (typed, or a slow machine) plucks the nearest marks, not all of them at once.
  return out.length > 24 ? out.slice(-24) : out;
}
