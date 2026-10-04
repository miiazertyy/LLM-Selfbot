/**
 * Big Picture Mode's movement: the stage pulling up, bubbles popping in with a
 * little jelly wobble, and the avatar flying between a queue card and the stage.
 *
 * Every one of them falls back to a plain fade when the app's motion setting is
 * off, which is the same switch the rest of the app obeys.
 */
import { crossfade } from "svelte/transition";
import { backOut, cubicIn, cubicOut } from "svelte/easing";
import { get } from "svelte/store";
import { bigPictureExit, motionEnabled } from "../stores";

const moving = () => get(motionEnabled);
const fade = (duration = 180) => ({ duration: bigPictureExit.on ? 0 : duration, css: (t: number) => `opacity:${t}` });
/** Closing: nothing inside waits to finish, so the view goes in one short fade. */
const instant = { duration: 0 };

/** A damped wobble that settles on 1: the jello. */
export const jelly = (t: number) => 1 - Math.cos(t * Math.PI * 3) * Math.exp(-t * 5.2);

/** The avatar on a queue card and the one on the stage are the same object, flying between the two. */
export const [sendAvatar, receiveAvatar] = crossfade({
  duration: (d) => (bigPictureExit.on ? 0 : Math.min(900, Math.max(420, Math.sqrt(d) * 26))),
  easing: cubicOut,
  fallback: (node) => (bigPictureExit.on ? instant : moving() ? popIn(node) : fade()),
});

/**
 * The key a face flies under, fixed when it appears (an action).
 *
 * A transition's parameters are read when it starts, and a face on the stage
 * starts leaving once the stage has already moved on: `{ key: spot.key }` read
 * then was the next person's key, or nothing at all when the stage went to a
 * scene, which threw. The face keeps the key it arrived with instead.
 */
export function flightKey(node: HTMLElement, key: string) {
  node.dataset.flight = key;
}

/** A face leaving for its card, under the key it arrived with (see flightKey). */
export function sendFace(node: Element) {
  return sendAvatar(node, { key: (node as HTMLElement).dataset.flight ?? "" });
}

/** The stage arriving: up from below, overshooting a touch.
 *
 * Transform and opacity only. These two used to animate `filter: blur()` as
 * well, and a blur that changes every frame cannot be composited: the whole
 * stage - avatar, tracker, every bubble - was repainted 60 times a second, which
 * is what made picking a conversation stutter. The movement reads the same
 * without it. */
export function riseIn(_node: Element, { delay = 0 }: { delay?: number } = {}) {
  if (bigPictureExit.on) return instant;
  if (!moving()) return fade(260);
  return {
    delay,
    duration: 700,
    css: (t: number) => {
      const e = backOut(t);
      return `transform: translate3d(0, ${(1 - e) * 84}px, 0) scale(${0.94 + 0.06 * e});`
        + `opacity: ${Math.min(1, t * 2.4)}`;
    },
  };
}

/** The stage leaving: lifted up and away, as the next one pulls up under it. */
export function liftOut(_node: Element) {
  if (bigPictureExit.on) return instant;
  if (!moving()) return fade(160);
  return {
    duration: 340,
    easing: cubicIn,
    css: (t: number, u: number) =>
      `transform: translate3d(0, ${-64 * u}px, 0) scale(${1 - 0.045 * u}); opacity: ${t}`,
  };
}

/** A bubble, a card or a number arriving: pops up and wobbles into place. */
export function popIn(_node: Element, { delay = 0, from = 0.82 }: { delay?: number; from?: number } = {}) {
  if (bigPictureExit.on) return instant;
  if (!moving()) return fade(200);
  return {
    delay,
    duration: 700,
    css: (t: number) => {
      const s = from + (1 - from) * jelly(t);
      return `transform: translateY(${(1 - Math.min(1, t * 1.8)) * 24}px) scale(${s}); opacity: ${Math.min(1, t * 2.5)}`;
    },
  };
}

/** A feed item arriving from the right edge, opening its own room as it comes, so the panel above gives way smoothly. */
export function slideIn(node: Element, { delay = 0 }: { delay?: number } = {}) {
  if (bigPictureExit.on) return instant;
  if (!moving()) return fade(200);
  const h = (node as HTMLElement).offsetHeight;
  return {
    delay,
    duration: 560,
    css: (t: number) => {
      const e = backOut(t);
      const g = cubicOut(Math.min(1, t * 1.7));
      return `transform: translateX(${(1 - e) * 60}px); opacity: ${Math.min(1, t * 2)}; height: ${g * h}px; overflow: hidden`;
    },
  };
}

/** A feed item going: it fades, and gives its room back instead of leaving a jump. */
export function slideOut(node: Element) {
  if (bigPictureExit.on) return instant;
  if (!moving()) return fade(160);
  const h = (node as HTMLElement).offsetHeight;
  return {
    duration: 420,
    easing: cubicIn,
    css: (t: number) => `transform: translateX(${(1 - t) * 24}px); opacity: ${t}; height: ${t * h}px; overflow: hidden`,
  };
}
