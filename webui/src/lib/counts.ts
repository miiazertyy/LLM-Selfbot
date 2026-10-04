/**
 * How much one notch of the tape is worth for a count this size
 * (Tape.svelte): about a twelfth of it, as 1, 2 or 5 times a power of ten,
 * and never less than 1. Ten messages go one by one; a cache of two hundred
 * goes by tens.
 */
export function stepFor(v: number): number {
  const want = Math.max(1, Math.abs(v) / 12);
  const p = Math.pow(10, Math.floor(Math.log10(want)));
  const m = want / p;
  return Math.max(1, (m >= 5 ? 5 : m >= 2 ? 2 : 1) * p);
}
