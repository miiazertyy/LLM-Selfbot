/**
 * How the small things feel in the hand, for the whole app, installed once.
 *
 *   - A chip (app.css .chip) answers a click with a jelly pop: bigger as it is
 *     picked, a small one as it is let go, and its mark (a status dot, an
 *     icon) jumping with it.
 *
 * Only on the elements' own styles, nothing re-rendered, and not with the
 * app's Animations switch off.
 *
 * Fields used to spring out wider when clicked into, and back when left. That
 * is gone: a click is not typing, and setting the width back on leaving undid
 * the width a value box had for its words. A value box is now as wide as what
 * is typed in it, growing as you type (lib/autowidth.ts).
 */
import { get } from "svelte/store";
import { motionEnabled } from "./stores";
import { play } from "./uisound";

const JELLY = "cubic-bezier(0.3, 1.45, 0.45, 1)";

function chipPop(chip: HTMLElement) {
  const on = chip.getAttribute("aria-pressed") === "true" || chip.classList.contains("is-active");
  chip.animate(
    on
      ? [{ transform: "scale(0.9, 0.86)" }, { transform: "scale(1.09, 1.06)", offset: 0.4 },
         { transform: "scale(0.97, 1)", offset: 0.7 }, { transform: "none" }]
      : [{ transform: "scale(0.94)" }, { transform: "scale(1.03)", offset: 0.5 }, { transform: "none" }],
    { duration: on ? 520 : 360, easing: "ease-out" },
  );
  chip.querySelector(".chip-mark")?.animate(
    on
      ? [{ transform: "scale(0.6) rotate(-20deg)" }, { transform: "scale(1.45) rotate(8deg)", offset: 0.45 },
         { transform: "scale(0.92)", offset: 0.75 }, { transform: "none" }]
      : [{ transform: "scale(0.8)" }, { transform: "none" }],
    { duration: on ? 560 : 300, easing: JELLY },
  );
}

let installed = false;

export function installFeel(): void {
  if (installed || typeof document === "undefined") return;
  installed = true;
  const moving = () => get(motionEnabled) && document.documentElement.dataset.motion !== "off";

  document.addEventListener("click", (e) => {
    const chip = (e.target as Element | null)?.closest?.(".chip");
    if (!(chip instanceof HTMLElement) || (chip as HTMLButtonElement).disabled) return;
    // After the click has been answered: picked or not is then on the chip.
    requestAnimationFrame(() => {
      const on = chip.getAttribute("aria-pressed") === "true" || chip.classList.contains("is-active");
      // Chips that make their own sound (a row of them marked data-sound="self") make it with the pop.
      if (chip.closest("[data-sound='self']")) play(on ? "select" : "off");
      if (moving()) chipPop(chip);
    });
  }, { passive: true });

}
