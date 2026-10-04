/**
 * The colours of Big Picture's room, taken from whoever is on stage.
 *
 * Each person's picture gives the moving background its colours, so every
 * conversation lights the room its own way. The picture is shrunk to a few
 * hundred pixels, its vivid colours are grouped by hue and the strongest few
 * kept, then evened out: saturated enough to glow, never light enough to wash
 * the room out behind white text on glass. A picture that is all greys, or one
 * the page may not read, gets colours made from the person's id instead, so
 * the same person always brings the same ones.
 *
 * The maths is plain functions of plain data, so it runs under Node in
 * tests/bigpicture_director.mjs; only loadPalette and themePalette touch the page.
 */

/** A colour, each channel 0 to 1. */
export type RGB = [number, number, number];

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Hue in degrees, saturation and lightness 0 to 1. */
export function hsl2rgb(h: number, s: number, l: number): RGB {
  const hue = ((h % 360) + 360) % 360;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((hue / 60) % 2) - 1));
  const m = l - c / 2;
  const [r, g, b] =
    hue < 60 ? [c, x, 0] : hue < 120 ? [x, c, 0] : hue < 180 ? [0, c, x]
      : hue < 240 ? [0, x, c] : hue < 300 ? [x, 0, c] : [c, 0, x];
  return [r + m, g + m, b + m];
}

export function rgb2hsl([r, g, b]: RGB): [number, number, number] {
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? ((g - b) / d + (g < b ? 6 : 0)) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, s, l];
}

/** A small, stable hash of a string, 0 to 1: the same seed, the same colours. */
export function hash(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0) / 4294967296;
}

/** Saturated enough to glow, never light enough to wash the room out. */
export function tame(c: RGB): RGB {
  const [h, s, l] = rgb2hsl(c);
  // Yellow, darkened as the room darkens everything, turns olive: lean it to gold instead.
  const hue = h > 44 && h < 72 ? h - (h - 38) * 0.65 : h;
  return hsl2rgb(hue, clamp(s * 1.2, 0.5, 0.92), clamp(l, 0.42, 0.6));
}

/** The same colour turned round the hue wheel, evened out. */
export function turn(c: RGB, degrees: number): RGB {
  const [h, s, l] = rgb2hsl(c);
  return tame(hsl2rgb(h + degrees, s, l));
}

/** Colours for someone with no usable picture: a hue from their id, and three that sit well with it. */
export function paletteFromSeed(seed: string): RGB[] {
  const h = hash(seed) * 360;
  const shift = 25 + hash(`${seed}~`) * 30;
  return [
    hsl2rgb(h, 0.78, 0.55),
    hsl2rgb(h + shift, 0.72, 0.5),
    hsl2rgb(h - shift * 1.4, 0.8, 0.58),
    hsl2rgb(h + 180 + shift * 0.5, 0.65, 0.52),
  ];
}

/** Colours built round one: itself, two neighbours, and one across the wheel for contrast. */
export function paletteAround(c: RGB): RGB[] {
  const base = tame(c);
  return [base, turn(base, 32), turn(base, -38), turn(base, 165)];
}

/**
 * The strongest colours of an image, from its RGBA pixels, four of them. Null
 * when it has no real colour at all (a grey, or black and white, picture).
 */
export function paletteFromPixels(data: ArrayLike<number>): RGB[] | null {
  const BINS = 24;
  const w = new Array<number>(BINS).fill(0);
  const sum = Array.from({ length: BINS }, () => [0, 0, 0]);
  for (let i = 0; i + 3 < data.length; i += 4) {
    if (data[i + 3] < 128) continue;                        // see-through: not part of the picture
    const c: RGB = [data[i] / 255, data[i + 1] / 255, data[i + 2] / 255];
    const [h, s, l] = rgb2hsl(c);
    // How much colour there really is: none at black, none at white.
    const vivid = s * (1 - Math.abs(2 * l - 1));
    if (vivid < 0.08) continue;
    const bin = Math.floor(h / (360 / BINS)) % BINS;
    const weight = vivid * vivid;
    w[bin] += weight;
    sum[bin][0] += c[0] * weight;
    sum[bin][1] += c[1] * weight;
    sum[bin][2] += c[2] * weight;
  }
  const total = w.reduce((a, b) => a + b, 0);
  if (!total) return null;
  const order = w.map((_, i) => i).filter((i) => w[i] > 0).sort((a, b) => w[b] - w[a]);
  const apart = (a: number, b: number) => Math.min(Math.abs(a - b), BINS - Math.abs(a - b));
  const picked: number[] = [];
  for (const i of order) {
    if (picked.length >= 4 || w[i] < total * 0.03) break;  // a speck of colour is noise, not the picture
    if (picked.some((j) => apart(i, j) < 2)) continue;      // at least 30° from the others, so they differ
    picked.push(i);
  }
  const colour = (i: number): RGB => [sum[i][0] / w[i], sum[i][1] / w[i], sum[i][2] / w[i]];
  if (picked.length === 1) return paletteAround(colour(picked[0]));
  const out = picked.map((i) => tame(colour(i)));
  // Fewer than four: the missing ones are neighbours of the strongest.
  while (out.length < 4) out.push(turn(out[0], out.length === 2 ? 34 : -40));
  return out;
}

/** The theme's own colours, for the scenes about no one in particular. */
export function paletteFromTheme(accent: RGB, accent2: RGB | null): RGB[] {
  const a = tame(accent);
  const b = accent2 ? tame(accent2) : turn(a, 60);
  return [a, b, turn(a, -35), turn(b, 40)];
}

/** Warning colours, for the scene about what is broken. */
export function paletteForTrouble(errors: boolean): RGB[] {
  // Reds and oranges, no yellow: yellow darkened is olive, which reads as dirt, not warning.
  return errors
    ? [hsl2rgb(356, 0.8, 0.52), hsl2rgb(14, 0.88, 0.52), hsl2rgb(334, 0.72, 0.46), hsl2rgb(24, 0.9, 0.5)]
    : [hsl2rgb(26, 0.92, 0.52), hsl2rgb(12, 0.85, 0.5), hsl2rgb(36, 0.9, 0.5), hsl2rgb(350, 0.7, 0.48)];
}

// ── In the page ─────────────────────────────────────────────────────────────

/**
 * A smaller copy of a Discord picture: enough for its colours, and a size the
 * page shows nowhere else, so the copy asked for with CORS is never one the
 * cache holds from a plain <img> (a mix that makes the canvas unreadable).
 */
function small(url: string): string {
  try {
    const u = new URL(url, location.href);
    if (/(^|\.)discordapp\.(com|net)$/.test(u.hostname)) u.searchParams.set("size", "32");
    return u.toString();
  } catch {
    return url;
  }
}

const cache = new Map<string, Promise<RGB[] | null>>();

/** The colours of the picture at `url`, read once and kept. Null when it has none or cannot be read. */
export function loadPalette(url: string): Promise<RGB[] | null> {
  if (!url || typeof document === "undefined") return Promise.resolve(null);
  const src = small(url);
  let job = cache.get(src);
  if (!job) {
    job = new Promise<RGB[] | null>((resolve) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.referrerPolicy = "no-referrer";
      img.decoding = "async";
      img.onload = () => {
        try {
          const n = 32;
          const c = document.createElement("canvas");
          c.width = n;
          c.height = n;
          const ctx = c.getContext("2d", { willReadFrequently: true });
          if (!ctx) return resolve(null);
          ctx.drawImage(img, 0, 0, n, n);
          resolve(paletteFromPixels(ctx.getImageData(0, 0, n, n).data));
        } catch {
          resolve(null);                                    // a picture the page may not read
        }
      };
      img.onerror = () => resolve(null);
      img.src = src;
    });
    cache.set(src, job);
    if (cache.size > 300) cache.delete(cache.keys().next().value as string);
  }
  return job;
}

/** Any CSS colour (hex, rgb(), oklch()...), as the page draws it. */
function cssColour(value: string): RGB | null {
  if (!value.trim() || typeof document === "undefined") return null;
  const c = document.createElement("canvas");
  c.width = 1;
  c.height = 1;
  const ctx = c.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  ctx.fillStyle = "#000";
  ctx.fillStyle = value.trim();
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return [r / 255, g / 255, b / 255];
}

/** The colours of the theme in use, read from its accents. */
export function themePalette(): RGB[] {
  const style = typeof document === "undefined" ? null : getComputedStyle(document.documentElement);
  const a = cssColour(style?.getPropertyValue("--color-accent") ?? "") ?? hsl2rgb(232, 0.9, 0.62);
  const b = cssColour(style?.getPropertyValue("--color-accent-2") ?? "");
  return paletteFromTheme(a, b);
}
