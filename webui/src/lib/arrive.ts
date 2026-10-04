/**
 * Controls that arrive: when a tab opens, a setting's control shows its value
 * by moving to it, the way the dials sweep in, rather than simply being there.
 * Each starts as its row starts to drop in (cascade.ts's whenShown), so it
 * moves with the tab's opening, not after it.
 *
 * Only ever on the page's own elements, never through the app's state: a
 * setting is not changed by being animated, and nothing re-renders for it.
 * Any hand on a control (a press, a key) ends its show at once.
 */
import { get } from "svelte/store";
import { motionEnabled } from "./stores";
import { onScreen, whenShown } from "./cascade";
import { play } from "./uisound";

/** The clocks' curve: quick off the mark, a long soft finish. */
const quintOut = (t: number) => 1 - Math.pow(1 - t, 5);

/**
 * A slider sweeps from its start to its value: the knob travels and the fill
 * follows it. One either side of zero sweeps out from zero. A slider left
 * blank (the provider's default) has no value to show and stays put.
 *
 * The knob glides rather than stepping: a range input snaps whatever it is
 * given to its step, so a short slider in tenths (-2 to 2) had only a handful
 * of places to be and moved in visible jumps, as if at a lower frame rate. Its
 * step is lifted for the sweep ("any") and put back when it lands.
 */
export function sweep(node: HTMLInputElement) {
  let frame = 0;
  let over = false;
  const min = Number(node.min) || 0;
  const max = Number(node.max) || 1;
  const target = Number(node.value);
  const step = node.getAttribute("step");
  const fill = node.style.getPropertyValue("--fill");
  const from = node.style.getPropertyValue("--from");
  const pctOf = (v: number) => ((v - min) / (max - min || 1)) * 100;
  const zero = min < 0 && max > 0 ? pctOf(0) : 0;
  const start = min < 0 && max > 0 ? 0 : min;

  function paint(v: number) {
    node.value = String(v);
    const p = pctOf(v);
    node.style.setProperty("--from", `${Math.min(zero, p)}%`);
    node.style.setProperty("--fill", `${Math.max(zero, p)}%`);
  }
  function done() {
    if (over) return;
    over = true;
    if (frame) cancelAnimationFrame(frame);
    if (step === null) node.removeAttribute("step");
    else node.setAttribute("step", step);
    node.value = String(target);
    node.style.setProperty("--fill", fill);
    node.style.setProperty("--from", from);
  }
  function stop() {
    done();
    node.removeEventListener("pointerdown", stop);
    node.removeEventListener("keydown", stop);
  }

  if (!get(motionEnabled) || node.classList.contains("is-blank") || !isFinite(target) || target === start) {
    return {};
  }
  node.addEventListener("pointerdown", stop);
  node.addEventListener("keydown", stop);
  node.setAttribute("step", "any");
  paint(start);
  whenShown(node).then(() => onScreen(node)).then((seen) => {
    if (over) return;
    // Below what the window shows: at its value at once, no sweep nobody would see.
    if (!seen) return stop();
    // Timed from the first frame actually drawn, not from when it was asked
    // for: the tab's first frames are its busiest, and a clock started before
    // them spent the fast start of the curve on frames nobody saw, so the knob
    // sat still and then leapt.
    let t0 = 0;
    // Heard as it goes: a breath of air as it sets off, a soft detent every twentieth of the way along,
    // rising with where the knob is, and a tock as it settles at its value. Settled is when it has
    // stopped moving to the eye, a hundredth of the track from it, not when the curve's long tail ends.
    let notch = Math.floor(pctOf(start) / 5);
    let seated = false;
    const step = (now: number) => {
      if (over) return;
      if (!t0) {
        t0 = now;
        play("zip", { p: pctOf(target) / 100 });
      }
      const t = Math.min(1, (now - t0) / 1000);
      const v = start + (target - start) * quintOut(t);
      paint(v);
      const k = Math.floor(pctOf(v) / 5);
      if (k !== notch) {
        notch = k;
        play("wind", { p: pctOf(v) / 100, strong: k % 5 === 0 });
      }
      if (!seated && Math.abs(pctOf(target) - pctOf(v)) < 1) {
        seated = true;
        play("seat", { p: pctOf(target) / 100 });
      }
      if (t < 1) frame = requestAnimationFrame(step);
      else stop();
    };
    frame = requestAnimationFrame(step);
  });
  return { destroy: stop };
}
