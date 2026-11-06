/**
 * What Big Picture says about the bots as they work, for someone across the
 * room: a message in, a reply on its way and gone, a friend asking. Made by the
 * app's own sounds (lib/uisound.ts), so they share one room and one volume with
 * every button here, and the speaker at the top right silences them all. Its own
 * switch (M, bigPictureSound) is for these alone: a press still clicks with them off.
 *
 *   arrive  a message came in
 *   write   the model started writing a reply
 *   sent    a reply went out, the swish and then a little chime
 *   limit   a model refused (rate limited) or failed
 *   friend  someone asked to be friends
 *   picture the bot sent one of its pictures
 *
 * Never a burst: a busy minute should not sound like a slot machine. Each has a
 * least gap of its own on top of the one the app's sounds keep.
 */
import { get } from "svelte/store";
import { bigPictureSound, uiSound } from "../stores";
import { play as uiPlay } from "../uisound";

export type Sound = "arrive" | "write" | "sent" | "limit" | "friend" | "picture";

const GAP: Record<Sound, number> = { arrive: 900, write: 1500, sent: 700, limit: 2500, friend: 1500, picture: 1200 };
const last: Partial<Record<Sound, number>> = {};

export function play(name: Sound): void {
  if (!get(bigPictureSound) || !get(uiSound)) return;
  const now = performance.now();
  if (now - (last[name] ?? -1e9) < GAP[name]) return;
  last[name] = now;
  switch (name) {
    case "arrive":
      uiPlay("receive", { level: 0.75 });
      break;
    case "write":
      uiPlay("rise", { p: 0.3, level: 0.5 });
      break;
    case "sent":
      uiPlay("send", { level: 0.8 });
      uiPlay("ok", { delay: 180, level: 0.55 });
      break;
    case "limit":
      uiPlay("err", { level: 0.5 });
      break;
    case "friend":
      uiPlay("info", { level: 0.8 });
      break;
    case "picture":
      uiPlay("glint", { p: 0.7, strong: true, level: 0.7 });
      break;
  }
}

/**
 * A page gone to by hand landing: a soft thup for what comes down in it, booked on
 * the sound card's clock to go with the tiles' own delays. Not on the tour: a page
 * turning by itself every ten seconds, for as long as this is left open, would be
 * a clock ticking in the room.
 */
export function arrivals(n: number, first = 90, step = 62): void {
  for (let i = 0; i < n; i++) uiPlay("settle", { delay: first + i * step, level: 0.55 });
}

/** Turning the switch on is itself a press, which is what a browser needs before it will play anything. */
export function primeAudio(): void {
  uiPlay("on", { level: 0.01 });
}
