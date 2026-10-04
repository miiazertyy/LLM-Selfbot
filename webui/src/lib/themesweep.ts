/**
 * Changing theme as a visible event, rather than the whole app blinking.
 *
 * The new theme spreads out from where you clicked, as a blob with a living,
 * slightly wobbly edge, like paint poured on the page rather than a ruled
 * circle: fast out of the gate, easing as it reaches the corners. The page
 * gives a small thump as it lands (a touch too big, a touch too small, then
 * still), and a few stars pop as the edge passes them.
 *
 * It is the browser's own view transition. The page is photographed as it
 * is, the new colours are applied once behind that photograph, and the two
 * are blended on the graphics card. The old way swapped every colour on the
 * page in the middle of a full-screen wipe, which made the browser restyle
 * and repaint everything at the worst moment (one frame of up to 0.8s on a
 * slow machine), and then faded every panel's colours for another 350ms on
 * top. While the reveal plays, nothing on the page animates its colours: the
 * new theme is simply there, inside the blob.
 *
 * Where the browser has no view transitions, a lighter version of the old
 * wipe is the fallback. With Animations off the theme simply changes. And if
 * anything at all goes wrong the theme is still applied, because that is the
 * part that matters.
 */
import { tick } from "svelte";
import { get } from "svelte/store";
import { motionEnabled, themeId } from "./stores";
import { applyTheme } from "./themes";
import { play } from "./uisound";

const DURATION = 860;
const STARS = 16;

/** The fallback's bar is across the screen: a second change meanwhile simply happens. */
let wiping = false;
/** The reveal under way, if one is. */
let current: { skipTransition(): void } | null = null;
/** Which reveal is the latest: one a newer one took over from leaves the tidying up to it. */
let latest = 0;

// Where the pointer last went down: the swatch that was clicked, so the new
// theme spreads out from it. Keyboard (the command palette) has none, and the
// top of the screen is used.
let lastX = -1;
let lastY = -1;
/** What was under the pointer when a press ended a reveal: its click is handed on to it. */
let pressedThrough: Element | null = null;

if (typeof window !== "undefined") {
  window.addEventListener("pointerdown", (e) => {
    lastX = e.clientX;
    lastY = e.clientY;
    if (!current) return;
    endReveal();
    // Gone now, so what is really there can be asked for.
    const under = document.elementFromPoint(e.clientX, e.clientY);
    pressedThrough = under && under !== document.documentElement ? under : null;
  }, { capture: true, passive: true });
  // The press was taken by the picture (the browser sends it to the page's root while a transition plays,
  // whatever the CSS says), so its click lands there too: handed on to what was under it.
  window.addEventListener("click", (e) => {
    const el = pressedThrough;
    pressedThrough = null;
    if (!el || e.target !== document.documentElement || !el.isConnected) return;
    e.stopPropagation();
    (el as HTMLElement).focus?.({ preventScroll: true });
    (el as HTMLElement).click?.();
  }, { capture: true });
  window.addEventListener("keydown", endReveal, { capture: true, passive: true });
  window.addEventListener("wheel", endReveal, { capture: true, passive: true });
}

/**
 * Never a wait. The reveal is a picture of the page laid over it, and a click
 * on it went nowhere until it was over. A hand on anything while it plays (a
 * press, a key, the wheel) ends it there and then, so the page is all there
 * and live, and a press goes on to what is under it (above). Another look
 * picked meanwhile gets a reveal of its own, from where it was clicked.
 */
function endReveal() {
  const t = current;
  current = null;
  try {
    t?.skipTransition();
  } catch {
    /* already over */
  }
}

export function sweepTo(id: string) {
  if (id === get(themeId)) return;
  revealChange(() => {
    applyTheme(id);
    themeId.set(id);
  });
}

/**
 * Any change to how the whole app looks, revealed the way a theme is: the
 * background, the panels, the typeface spread out from where you clicked too,
 * rather than the page simply switching. `apply` makes the change (a store
 * set is fine: the page is redrawn before the new look is taken); `ready`, if
 * given, is waited for a moment first, for a typeface's file to load, so the
 * new look is not taken in the fallback font.
 */
export function revealChange(apply: () => void, ready?: () => Promise<unknown>) {
  // Someone who turned motion off does not want anything across their screen.
  if (typeof document === "undefined" || !get(motionEnabled)) {
    apply();
    return;
  }
  try {
    // A reveal under way gives way to this one (the browser ends it as this starts).
    if (typeof (document as any).startViewTransition === "function") reveal(apply, ready);
    else if (wiping) apply();
    else wipe(apply);
  } catch {
    apply();
  }
}

/**
 * A blob's outline as a polygon, round a point: `wobble` is how far its edge
 * wanders in and out, `turn` moves the waves along it between frames, so the
 * edge ripples as it grows rather than keeping one shape.
 */
function blob(x: number, y: number, r: number, wobble: number, turn: number, waves: number[]): string {
  const N = 48;
  const pts: string[] = [];
  for (let i = 0; i < N; i++) {
    const a = (i / N) * Math.PI * 2;
    const w = 1 + wobble * (0.6 * Math.sin(waves[0] * a + waves[2] + turn) + 0.4 * Math.sin(waves[1] * a + waves[3] - turn * 1.4));
    const rr = Math.max(0, r * w);
    pts.push(`${(x + rr * Math.cos(a)).toFixed(1)}px ${(y + rr * Math.sin(a)).toFixed(1)}px`);
  }
  return `polygon(${pts.join(",")})`;
}

function reveal(apply: () => void, ready?: () => Promise<unknown>) {
  const mine = ++latest;
  const root = document.documentElement;
  const w = innerWidth;
  const h = innerHeight;
  const x = lastX >= 0 ? lastX : w / 2;
  const y = lastY >= 0 ? lastY : h * 0.2;
  // Far enough to cover the farthest corner, even where the edge dips in.
  const R = Math.hypot(Math.max(x, w - x), Math.max(y, h - y)) * 1.12;
  const waves = [3 + Math.floor(Math.random() * 2), 6 + Math.floor(Math.random() * 3), Math.random() * 6.3, Math.random() * 6.3];

  const t = (document as any).startViewTransition(async () => {
    // No colour transitions anywhere while it plays: inside the blob the new
    // look is simply there (and taken off once it is over, see below).
    root.classList.add("theme-switching");
    apply();
    // A change made through a store is drawn on the next tick; a typeface waits a moment for its file.
    await tick();
    if (ready) await Promise.race([ready().catch(() => undefined), new Promise((r) => setTimeout(r, 450))]);
  });
  current = t;

  t.ready.then(() => {
    // Heard as it spreads: an airy rise, the reveal's own.
    play("hover", { level: 0.85 });
    // Out of the gate fast, easing into the corners; the edge wobbles most
    // while it is small and settles as it grows.
    const steps: [number, number, number][] = [
      [0, 0, 0],
      [0.1, 0.16, 0.2],
      [0.26, 0.42, 0.16],
      [0.48, 0.7, 0.11],
      [0.72, 0.9, 0.06],
      [1, 1, 0],
    ];
    root.animate(
      steps.map(([offset, r, wobble], n) => ({ offset, clipPath: blob(x, y, R * r, wobble, n * 0.9, waves) })),
      { duration: DURATION, easing: "linear", fill: "both", pseudoElement: "::view-transition-new(root)" },
    );
    // The thump: the new theme lands a touch too big, dips a touch too small, and is still.
    root.animate(
      [{ transform: "scale(1.025)" }, { transform: "scale(0.991)", offset: 0.7 }, { transform: "scale(1)" }],
      { duration: DURATION, easing: "cubic-bezier(0.22, 0.9, 0.3, 1)", pseudoElement: "::view-transition-new(root)" },
    );
    // The old one sinks back a little as it is covered.
    root.animate(
      [{ transform: "scale(1)", opacity: 1 }, { transform: "scale(0.982)", opacity: 0.82 }],
      { duration: DURATION, easing: "cubic-bezier(0.4, 0, 0.2, 1)", fill: "both", pseudoElement: "::view-transition-old(root)" },
    );
    stars(x, y, R);
  }).catch(() => {});

  // A transition the browser skips (a tab in the background, say, or a click
  // that ended it) still ends here.
  const tidy = () => {
    if (current === t) current = null;
    if (mine === latest) root.classList.remove("theme-switching");
  };
  t.finished.catch(() => {}).finally(tidy);
  setTimeout(tidy, DURATION + 1500);
}

/**
 * Stars that pop in the new theme as the edge reaches them. They are on the
 * page, so they only show inside the blob, which is what makes them look
 * thrown up by its edge. Glowing with a gradient of their own: a drop shadow
 * on each would be a filter to work out every frame.
 */
function stars(x: number, y: number, R: number) {
  const layer = document.createElement("div");
  layer.className = "theme-sweep is-stars";
  layer.setAttribute("aria-hidden", "true");
  for (let i = 0; i < STARS; i++) {
    const a = Math.random() * Math.PI * 2;
    const d = R * (0.12 + Math.random() * 0.62);
    const sx = x + d * Math.cos(a);
    const sy = y + d * Math.sin(a);
    if (sx < 0 || sy < 0 || sx > innerWidth || sy > innerHeight) continue;
    const star = document.createElement("span");
    star.className = "theme-sweep-star";
    star.style.left = `${sx}px`;
    star.style.top = `${sy}px`;
    star.style.setProperty("--size", `${7 + Math.random() * 11}px`);
    star.style.setProperty("--life", `${460 + Math.random() * 240}ms`);
    // When the edge gets there: the blob is at about d/R of its size a matching share of the way in.
    star.style.setProperty("--delay", `${Math.round(Math.pow(d / R, 1.3) * DURATION * 0.7)}ms`);
    layer.appendChild(star);
  }
  document.body.appendChild(layer);
  setTimeout(() => layer.remove(), DURATION + 900);
}

/** The fallback, where there are no view transitions: a bar across the screen, the colours changing behind it. */
function wipe(apply: () => void) {
  wiping = true;
  const layer = document.createElement("div");
  layer.className = "theme-sweep";
  layer.setAttribute("aria-hidden", "true");
  const bar = document.createElement("div");
  bar.className = "theme-sweep-bar";
  layer.appendChild(bar);
  document.body.appendChild(layer);
  const done = () => {
    layer.remove();
    document.documentElement.classList.remove("theme-switching");
    wiping = false;
  };
  const anim = layer.animate(
    [{ transform: "translateX(-110%)" }, { transform: "translateX(110%)" }],
    { duration: 620, easing: "cubic-bezier(0.65, 0, 0.35, 1)", fill: "forwards" },
  );
  // The swap behind the bar, all at once rather than every panel fading its colours after.
  let applied = false;
  const swap = () => {
    if (applied) return;
    applied = true;
    apply();
  };
  setTimeout(() => {
    document.documentElement.classList.add("theme-switching");
    swap();
  }, 620 * 0.42);
  anim.onfinish = done;
  anim.oncancel = done;
  // A tab in the background does not run animations: never leave the overlay up.
  setTimeout(() => {
    if (wiping) {
      swap();
      done();
    }
  }, 620 + 400);
}
