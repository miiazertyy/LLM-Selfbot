/**
 * The ways Big Picture's room can move.
 *
 * The room is the app's own background made personal: a few big, soft blooms
 * of light drifting past each other, in the colours of whoever is on stage,
 * wobbling like the app's jelly as they go (sky.ts). A look is how they move:
 * how big they are, how fast they drift, how much they wobble, whether they
 * turn round the stage. Every person is given one by their id, so the same
 * person always brings the same room, and every scene has its own. Changing
 * look turns the dials rather than switching: one room melts into the next.
 *
 * All of them are quiet on purpose. It is a background: it sits behind glass
 * and white text, and should be felt more than watched.
 *
 * How lively it is follows the conversation: calm while a reply only waits,
 * quicker while it is written and typed.
 *
 * Plain data and plain functions, so it runs under Node in tests/bigpicture_director.mjs.
 */
import type { Scene } from "./director";
// With its extension: the tests load this file straight into Node, which does not guess one.
import { hash } from "./palette.ts";

export type Look = {
  /** How much the blooms squash and stretch as they go, like jelly: 0 to 1. */
  wobble: number;
  /** How big they are: 0 smaller pools of light, 1 broad washes. */
  size: number;
  /** How fast they drift, 0 to 1. */
  speed: number;
  /** How much they turn round the stage as they drift, 0 to 1. */
  orbit: number;
  /** How much light they are let have. */
  glow: number;
};

export const LOOKS = {
  silk: { wobble: 0.45, size: 0.65, speed: 0.35, orbit: 0.1, glow: 1.0 },
  nebula: { wobble: 0.3, size: 1.0, speed: 0.25, orbit: 0.35, glow: 0.9 },
  tide: { wobble: 0.6, size: 0.55, speed: 0.55, orbit: 0, glow: 0.95 },
  aurora: { wobble: 0.4, size: 0.8, speed: 0.45, orbit: 0.15, glow: 1.0 },
  vortex: { wobble: 0.5, size: 0.6, speed: 0.45, orbit: 1, glow: 1.0 },
  ember: { wobble: 0.8, size: 0.5, speed: 0.5, orbit: 0.2, glow: 0.95 },
} satisfies Record<string, Look>;

export type LookName = keyof typeof LOOKS;
export const LOOK_NAMES = Object.keys(LOOKS) as LookName[];

/** The look someone brings: the same for them every time, in a conversation or in a memory. */
export function lookFor(seed: string): LookName {
  return LOOK_NAMES[Math.floor(hash(`${seed}#look`) * LOOK_NAMES.length) % LOOK_NAMES.length];
}

/** Each scene's own look, for the ones about no one in particular (a person's scene uses theirs). */
export const SCENE_LOOK: Record<Scene, LookName> = {
  memory: "silk",
  today: "aurora",
  accounts: "tide",
  recent: "silk",
  pictures: "silk",
  people: "vortex",
  persona: "nebula",
  friends: "ember",
  health: "ember",
};

/**
 * How lively the room is for a conversation, 0 to 1: calm while its reply
 * only waits, quicker while it is written, most while it is typed out,
 * settling again once it has gone.
 */
export function energyFor(phase: string, step: number, answered: boolean): number {
  if (answered) return 0.3;
  if (phase !== "live") return 0.2;
  if (step >= 4) return 1;
  if (step === 2) return 0.85;
  if (step === 3) return 0.45;
  return 0.3;
}

/** The dials of a look, in the order the shader takes them. */
export function dials(l: Look): number[] {
  return [l.wobble, l.size, l.speed, l.orbit, l.glow];
}
