/**
 * Changing theme as a visible event, rather than the whole app blinking.
 *
 * A bar sweeps across the screen and the colours change behind its leading
 * edge, so the new theme arrives with the wipe instead of every surface
 * flipping at once. Sparks trail off the edge because the sweep is otherwise a
 * plain rectangle crossing the screen.
 *
 * The sweep is a plain DOM element on top of everything, drawn with the
 * Web Animations API. No library, and if anything at all goes wrong the theme
 * is still applied, because that is the part that matters.
 */
import { get } from "svelte/store";
import { motionEnabled, themeId } from "./stores";

const DURATION = 620;
const SPARKS = 26;

let running = false;

export function sweepTo(id: string) {
  if (id === get(themeId)) return;

  // Someone who turned motion off does not want a wipe across their screen,
  // and a second click mid sweep should not stack two of them.
  if (!get(motionEnabled) || running || typeof document === "undefined") {
    themeId.set(id);
    return;
  }

  running = true;
  const layer = document.createElement("div");
  layer.className = "theme-sweep";
  layer.setAttribute("aria-hidden", "true");

  const bar = document.createElement("div");
  bar.className = "theme-sweep-bar";
  layer.appendChild(bar);

  // Sparks are thrown off the trailing edge, scattered across its height so
  // they read as coming off the bar rather than from one point.
  for (let i = 0; i < SPARKS; i++) {
    const spark = document.createElement("span");
    spark.className = "theme-sweep-spark";
    spark.style.top = `${Math.random() * 100}%`;
    spark.style.setProperty("--drift", `${(Math.random() - 0.5) * 90}px`);
    spark.style.setProperty("--size", `${2 + Math.random() * 3}px`);
    spark.style.setProperty("--delay", `${Math.random() * DURATION * 0.55}ms`);
    bar.appendChild(spark);
  }

  document.body.appendChild(layer);

  const done = () => {
    layer.remove();
    running = false;
  };

  try {
    const anim = layer.animate(
      [{ transform: "translateX(-110%)" }, { transform: "translateX(110%)" }],
      { duration: DURATION, easing: "cubic-bezier(0.65, 0, 0.35, 1)", fill: "forwards" },
    );
    // Swap the palette when the leading edge is about halfway, so the change
    // happens behind the bar rather than in front of it.
    setTimeout(() => themeId.set(id), DURATION * 0.42);
    anim.onfinish = done;
    anim.oncancel = done;
    // A tab in the background does not run animations, so onfinish may never
    // arrive and the overlay would sit there for good.
    setTimeout(() => {
      if (running) {
        themeId.set(id);
        done();
      }
    }, DURATION + 400);
  } catch {
    themeId.set(id);
    done();
  }
}
