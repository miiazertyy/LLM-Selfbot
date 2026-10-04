/**
 * Big Picture Mode's soft sounds, made on the spot with WebAudio: no files to
 * ship, nothing loud. Off until someone turns them on (bigPictureSound), and
 * every call is a no-op while they are off.
 *
 *   arrive  a soft pluck: a message came in
 *   write   a short rising shimmer: the model started writing a reply
 *   sent    a two-note chime: a reply went out
 *   limit   a low, muted tone: a model refused (rate limited) or failed
 *   friend  a warm knock-knock: someone asked to be friends
 *   accept  a bright little arpeggio: a friend accepted, a mood switched
 *   picture a soft shutter: the bot sent one of its pictures
 *   tap     the faintest tick: a chapter picked by hand
 */
import { get } from "svelte/store";
import { bigPictureSound, uiSound } from "../stores";

let ctx: AudioContext | null = null;
let master: GainNode | null = null;

function audio(): AudioContext | null {
  if (!get(bigPictureSound) || !get(uiSound)) return null;
  try {
    if (!ctx) {
      ctx = new AudioContext();
      master = ctx.createGain();
      master.gain.value = 0.18;               // quiet: a room tone, not a notification
      master.connect(ctx.destination);
    }
    if (ctx.state === "suspended") void ctx.resume();
    return ctx;
  } catch {
    return null;
  }
}

/** One soft voice: a sine (or triangle) with a quick attack and a long, gentle tail. */
function voice(freq: number, at: number, dur: number, peak: number, type: OscillatorType = "sine", glideTo?: number) {
  const a = audio();
  if (!a || !master) return;
  const o = a.createOscillator();
  const g = a.createGain();
  o.type = type;
  o.frequency.setValueAtTime(freq, a.currentTime + at);
  if (glideTo) o.frequency.exponentialRampToValueAtTime(glideTo, a.currentTime + at + dur * 0.8);
  g.gain.setValueAtTime(0.0001, a.currentTime + at);
  g.gain.exponentialRampToValueAtTime(peak, a.currentTime + at + 0.015);
  g.gain.exponentialRampToValueAtTime(0.0001, a.currentTime + at + dur);
  o.connect(g).connect(master);
  o.start(a.currentTime + at);
  o.stop(a.currentTime + at + dur + 0.05);
}

// Never a burst: a busy minute should not sound like a slot machine.
const last: Record<string, number> = {};
function once(name: string, gap: number): boolean {
  const now = performance.now();
  if (now - (last[name] ?? 0) < gap) return false;
  last[name] = now;
  return true;
}

export type Sound = "arrive" | "write" | "sent" | "limit" | "friend" | "accept" | "picture" | "tap";

export function play(name: Sound): void {
  if (!get(bigPictureSound) || !get(uiSound)) return;
  switch (name) {
    case "friend":
      if (once(name, 1500)) { voice(659, 0, 0.3, 0.3, "triangle"); voice(988, 0.14, 0.45, 0.28, "triangle"); }
      break;
    case "accept":
      if (once(name, 600)) { voice(1047, 0, 0.4, 0.28); voice(1319, 0.07, 0.45, 0.26); voice(1568, 0.14, 0.7, 0.24); }
      break;
    case "picture":
      if (once(name, 1200)) { voice(1760, 0, 0.06, 0.16, "triangle"); voice(1175, 0.06, 0.18, 0.14, "triangle"); }
      break;
    case "tap":
      if (once(name, 120)) voice(1480, 0, 0.07, 0.1);
      break;
    case "arrive":
      if (once(name, 900)) { voice(880, 0, 0.35, 0.5, "triangle"); voice(1320, 0.02, 0.25, 0.18); }
      break;
    case "write":
      if (once(name, 1500)) voice(520, 0, 0.5, 0.22, "sine", 880);
      break;
    case "sent":
      if (once(name, 700)) { voice(784, 0, 0.45, 0.4); voice(1175, 0.11, 0.6, 0.35); }
      break;
    case "limit":
      if (once(name, 2500)) voice(196, 0, 0.6, 0.35, "triangle", 165);
      break;
  }
}

/** Turning the speaker on is itself a click, which is what a browser needs before it will play anything. */
export function primeAudio(): void {
  audio();
}
