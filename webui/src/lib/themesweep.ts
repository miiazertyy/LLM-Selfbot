/**
 * Changing theme as a visible event, rather than the whole app blinking, and never a page that has stopped.
 *
 * It used to be the browser's view transition: the page photographed, and the new theme spreading across the
 * photograph. That is a frozen frame by design. For most of a second the app was a picture of itself: nothing moved,
 * hovering did nothing, a click landed on the picture. To anyone watching, the app had hung. (Measured: half of the
 * frames during a change had no page under the pointer at all.)
 *
 * So nothing is photographed. A blob pours out from where you clicked, over the page, which goes on running and
 * answering the pointer underneath it. The blob is one flat layer moved by the graphics card alone, so it keeps its
 * pace whatever the page is doing. And it covers nothing: what is under it keeps its own light and dark and takes on
 * the new theme's colour (a `color` blend), so the app is all there as the edge passes, already in the new colours.
 * (It was a blob of the new theme's background, all but solid, and every theme's background is close to black: for
 * half a second the whole window was.) Once it has reached every corner, the real colours change under it: the one
 * heavy moment, a restyle and repaint of everything, which from there is hardly a change at all. Then it fades.
 *
 * With Animations off the theme simply changes. And if anything at all goes wrong the theme is still applied, because
 * that is the part that matters.
 */
import { tick } from "svelte";
import { get } from "svelte/store";
import { motionEnabled, themeId } from "./stores";
import { applyTheme, byId } from "./themes";
import { play } from "./uisound";

const POUR = 480;
const LIFT = 300;
const STARS = 14;

/** The reveal under way, if one is: a newer change finishes it on the spot. */
let current: { finish(): void } | null = null;

// Where the pointer last went down: the swatch that was clicked, so the new theme spreads out from it. Keyboard (the
// command palette) has none, and the top of the screen is used.
let lastX = -1;
let lastY = -1;

if (typeof window !== "undefined") {
  window.addEventListener("pointerdown", (e) => {
    lastX = e.clientX;
    lastY = e.clientY;
  }, { capture: true, passive: true });
}

export function sweepTo(id: string) {
  if (id === get(themeId)) return;
  revealChange(() => {
    applyTheme(id);
    themeId.set(id);
  }, undefined, byId(id).vars);
}

/**
 * Any change to how the whole app looks, revealed the way a theme is: the background, the panels, the typeface pour
 * out from where you clicked too, rather than the page simply switching. `apply` makes the change (a store set is
 * fine: the page is redrawn before the blob fades); `ready`, if given, is waited for a moment first, for a typeface's
 * file to load, so it does not fade on the fallback font. `vars` are the new theme's colours, for the blob and its
 * stars to be in; without them it is the colours there are now.
 */
export function revealChange(apply: () => void, ready?: () => Promise<unknown>, vars?: Record<string, string>) {
  // Someone who turned motion off does not want anything across their screen.
  if (typeof document === "undefined" || !get(motionEnabled)) {
    apply();
    return;
  }
  current?.finish();
  try {
    reveal(apply, ready, vars);
  } catch {
    apply();
  }
}

function reveal(apply: () => void, ready?: () => Promise<unknown>, vars?: Record<string, string>) {
  const root = document.documentElement;
  const w = innerWidth;
  const h = innerHeight;
  const x = lastX >= 0 ? lastX : w / 2;
  const y = lastY >= 0 ? lastY : h * 0.2;
  // Far enough to cover the farthest corner, even where the uneven edge dips in.
  const R = Math.hypot(Math.max(x, w - x), Math.max(y, h - y)) * 1.14;
  const accent = vars?.["--color-accent"] || getComputedStyle(root).getPropertyValue("--color-accent").trim() || "#7c8cff";
  // Greyed down: a blend takes all of its colour's strength, and a theme's panels are only faintly tinted with its accent.
  const colour = `color-mix(in srgb, ${accent} 30%, #808080)`;

  // Nothing on these can be pressed: the page is live under them from start to finish, so there is nothing to wait for.
  // Two layers, side by side: a blend only reaches what is in its own stacking context, so the one that blends sits
  // straight on the page, and the stars, which must not, sit beside it.
  const wash = document.createElement("div");
  wash.className = "theme-sweep is-wash";
  wash.setAttribute("aria-hidden", "true");
  const blob = document.createElement("div");
  blob.className = "theme-sweep-blob";
  blob.style.cssText = `left:${x - R}px;top:${y - R}px;width:${R * 2}px;height:${R * 2}px;color:${colour}`;
  wash.appendChild(blob);
  const layer = document.createElement("div");
  layer.className = "theme-sweep";
  layer.setAttribute("aria-hidden", "true");
  for (const name of ["--color-accent", "--color-accent-2"]) if (vars?.[name]) layer.style.setProperty(name, vars[name]);
  stars(layer, x, y, R);
  document.body.append(wash, layer);

  let changed = false;
  let over = false;
  /** While it changes, nothing fades its colours: that would be a repaint of the whole page each frame. */
  const change = () => {
    if (changed) return;
    changed = true;
    root.classList.add("theme-switching");
    apply();
  };
  const tidy = () => {
    if (over) return;
    over = true;
    clearTimeout(guard);
    wash.remove();
    layer.remove();
    root.classList.remove("theme-switching");
    if (current === me) current = null;
  };
  const me = {
    finish() {
      try {
        change();
      } finally {
        tidy();
      }
    },
  };
  current = me;
  // A tab in the background runs no animations, and an overlay must never be left up.
  const guard = window.setTimeout(() => me.finish(), POUR + LIFT + 1800);

  // Heard as it spreads: an airy rise, the reveal's own.
  play("hover", { level: 0.85 });
  // Out of the gate fast, easing into the corners, turning a little so its uneven edge feels poured.
  const pour = blob.animate(
    [{ transform: "scale(0.03) rotate(-14deg)" }, { transform: "scale(1) rotate(0deg)" }],
    { duration: POUR, easing: "cubic-bezier(0.45, 0.3, 0.35, 1)", fill: "forwards" },
  );
  pour.finished.then(async () => {
    if (over) return;
    change();
    // A change made through a store is drawn on the next tick; a typeface waits a moment for its file.
    await tick();
    if (ready) await Promise.race([ready().catch(() => undefined), new Promise((r) => setTimeout(r, 450))]);
    // The heavy frame has gone by before anything moves again.
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    if (over) return;
    const lift = wash.animate([{ opacity: 1 }, { opacity: 0 }], { duration: LIFT, easing: "ease-out", fill: "forwards" });
    await lift.finished;
    tidy();
  }).catch(() => me.finish());
}

/**
 * Stars that pop in the new theme as the edge reaches them, glowing with a gradient of their own: a drop shadow on
 * each would be a filter to work out every frame.
 */
function stars(layer: HTMLElement, x: number, y: number, R: number) {
  for (let i = 0; i < STARS; i++) {
    const a = Math.random() * Math.PI * 2;
    const d = R * (0.12 + Math.random() * 0.6);
    const sx = x + d * Math.cos(a);
    const sy = y + d * Math.sin(a);
    if (sx < 0 || sy < 0 || sx > innerWidth || sy > innerHeight) continue;
    const star = document.createElement("span");
    star.className = "theme-sweep-star";
    star.style.left = `${sx}px`;
    star.style.top = `${sy}px`;
    star.style.setProperty("--size", `${7 + Math.random() * 11}px`);
    star.style.setProperty("--life", `${420 + Math.random() * 200}ms`);
    // When the edge gets there: the blob is at about d/R of its size a matching share of the way in.
    star.style.setProperty("--delay", `${Math.round(Math.pow(d / R, 1.6) * POUR * 0.8)}ms`);
    layer.appendChild(star);
  }
}
