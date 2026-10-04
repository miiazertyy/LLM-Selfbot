/**
 * The app's sounds, made on the spot with WebAudio: no files to ship.
 *
 *   tap      a soft click: any button pressed
 *   up       and let go: the click back up, lighter and higher, as a real button's spring returns
 *   tick     a crisp detent: each step of a clock, a slider, a number tape
 *   on, off  a switch flipping, the pitch going up or down
 *   select   a glassy click: a choice picked from a list or a row of options
 *   open     a little lift: a list opening
 *   menu     a soft, airy pop: the right-click menu appearing
 *   ok       a two-note chime: something worked (a notification)
 *   info     one soft bell: something to know
 *   err      a muted fall: something went wrong
 *   send     a swish: a message went out
 *   receive  a soft bloop: a message came in
 *   delete   a soft drop: something removed, undo still possible
 *   undo     the drop, rising: brought back
 *
 * As a tab opens, what moves into place makes its own small sound, quieter
 * than a hand on a control:
 *   wind     a dry little detent: a dial, a slider or a tape sweeping in
 *   slide    a switch pulled across, and its knob landing; a run of them climbs a note each
 *   rise     something growing up into place (a bar filling, a stem), a step higher each time
 *   done     a soft bell: everything in place (the Snapchat setup, all four)
 *   key      a key pressed: a dropdown's value typing itself in, the typing speed's keyboard
 *   land     something set down with a bounce: a language's flag arriving
 *   pluck    a bar of a chart growing up, pitched by how tall it is: a chart plays its shape
 *   zip      a slider's knob setting off on its way in
 *   seat     a knob settling where it belongs (strong: knocking against the end of its track)
 *   medal    a medal's shine: bronze, silver, gold, a note higher each
 *   settle   a widget of the Dashboard set down in its place
 *   glint    a glint of light: Appearance's colours flooding in, a run of them up the scale (strong: the chosen one)
 *   grow     a bar growing up with its note rising alongside, higher the taller it gets, landing as it lands
 *
 * Dragging:
 *   lift     taken hold of, to be moved (a row of a list)
 *   slot     passing a place it could go
 *   drop     put down where it goes
 *   grab     a knob or a handle taken hold of
 *   release  and let go
 *   hover    something dragged in from outside (a file), over where it can be dropped
 *
 * Clicks are noise through a tight band filter, so they are short and crisp
 * the way a physical switch is, not a beep; chimes are sines with a faint
 * bell partial and a slightly detuned twin, so they shimmer. All of it goes
 * through a soft, dark room (a reverb made from noise that dies away) for the
 * dreamy feel the rest of the app has, the clicks only a touch of it.
 *
 * uiSound (the speaker at the top right) turns all of it off, Big Picture's
 * own sounds included, and nothing is even created until it is on and
 * something has been pressed: browsers only play after a gesture.
 */
import { get } from "svelte/store";
import { uiSound, uiVolume, toasts } from "./stores";

/** The master level at the speakers: as made (0.6) times the speaker's slider, 0 to 2. Measured renders keep 0.6. */
const MASTER = 0.6;
const masterFor = (v: number) => MASTER * Math.max(0, Math.min(2, Number.isFinite(v) ? v : 1));

export type UISound =
  | "tap" | "up" | "tick" | "on" | "off" | "select" | "open" | "menu"
  | "ok" | "info" | "err" | "send" | "receive" | "delete" | "undo"
  | "wind" | "slide" | "rise" | "done" | "key" | "land" | "pluck" | "zip" | "seat" | "medal" | "settle" | "glint" | "grow"
  | "lift" | "slot" | "drop" | "grab" | "release" | "hover";

/** Where a sound is made: the master out, the room, and a second of noise to cut clicks from. */
type Graph = { a: BaseAudioContext; out: GainNode; room: GainNode; noise: AudioBuffer };

let live: AudioContext | null = null;
let liveGraph: Graph | null = null;
/** The graph the voices below build into: the speakers, or an offline one being measured. */
let g: Graph | null = null;
/** How loud the voice being made is, of its full self: arrivals in a crowd are made quieter (see play). */
let level = 1;
/**
 * Where a voice starts, after now: 0 at the speakers. Measured offline it can
 * start a little in (renderSound's `settled`), once the compressor has
 * settled: at the very first moment of a render it holds everything down by
 * about ten dB, which the speakers, running all along, never do. A click at
 * the start of a render read ten dB quieter than the same click a moment in,
 * and that is how the sounds heard are compared (the older measures, from the
 * start, are kept as they were).
 */
let lead = 0;

function audio(): boolean {
  if (!get(uiSound)) return false;
  try {
    if (!live) {
      live = new AudioContext({ latencyHint: "interactive" });
      liveGraph = graph(live);
      liveGraph.out.gain.value = masterFor(get(uiVolume));
      // The speaker's slider, followed at once, eased over a few milliseconds so a drag has no clicks in it.
      uiVolume.subscribe((v) => {
        if (liveGraph && live) liveGraph.out.gain.setTargetAtTime(masterFor(v), live.currentTime, 0.015);
      });
    }
    if (live.state === "suspended") void live.resume();
    g = liveGraph;
    return true;
  } catch {
    return false;
  }
}

function graph(a: BaseAudioContext): Graph {
  // Gentle glue on top, so a chime over a click never jumps out.
  const comp = a.createDynamicsCompressor();
  comp.threshold.value = -20;
  comp.knee.value = 14;
  comp.ratio.value = 3;
  comp.attack.value = 0.002;
  comp.release.value = 0.2;
  const out = a.createGain();
  out.gain.value = 0.6;
  out.connect(comp).connect(a.destination);
  // The room: two seconds and a half of noise dying away, darkened.
  const verb = a.createConvolver();
  verb.buffer = impulse(a, 2.6, 3.2);
  const dark = a.createBiquadFilter();
  dark.type = "lowpass";
  dark.frequency.value = 4800;
  const room = a.createGain();
  room.gain.value = 0.9;
  room.connect(verb).connect(dark).connect(out);
  const noise = a.createBuffer(1, Math.floor(a.sampleRate * 0.4), a.sampleRate);
  const d = noise.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  return { a, out, room, noise };
}

function impulse(a: BaseAudioContext, seconds: number, decay: number): AudioBuffer {
  const len = Math.floor(a.sampleRate * seconds);
  const buf = a.createBuffer(2, len, a.sampleRate);
  for (let ch = 0; ch < 2; ch++) {
    const d = buf.getChannelData(ch);
    for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, decay);
  }
  return buf;
}

/** Where a sound goes: straight out, and some of it into the room. */
function send(node: AudioNode, wet: number) {
  node.connect(g!.out);
  if (wet > 0) {
    const w = g!.a.createGain();
    w.gain.value = wet;
    node.connect(w).connect(g!.room);
  }
}

/** A click: a burst of noise through a narrow band, gone in a few milliseconds. */
function click(at: number, freq: number, dur: number, peak: number, q = 2, wet = 0.04) {
  const a = g!.a;
  const t = a.currentTime + lead + at;
  const src = a.createBufferSource();
  src.buffer = g!.noise;
  src.playbackRate.value = 0.9 + Math.random() * 0.2;
  const band = a.createBiquadFilter();
  band.type = "bandpass";
  band.frequency.value = freq * (0.97 + Math.random() * 0.06);
  band.Q.value = q;
  const env = a.createGain();
  env.gain.setValueAtTime(0.0001, t);
  env.gain.exponentialRampToValueAtTime(peak * level, t + 0.0012);
  env.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  src.connect(band).connect(env);
  send(env, wet);
  src.start(t, Math.random() * 0.3);
  src.stop(t + dur + 0.02);
}

/** A tone: one oscillator, a quick attack, a long soft tail, maybe a glide. */
function tone(at: number, freq: number, dur: number, peak: number,
              { type = "sine" as OscillatorType, wet = 0.2, glide = 0, attack = 0.006, detune = 0 } = {}) {
  const a = g!.a;
  const t = a.currentTime + lead + at;
  const o = a.createOscillator();
  o.type = type;
  o.frequency.setValueAtTime(freq, t);
  if (glide) o.frequency.exponentialRampToValueAtTime(glide, t + dur * 0.7);
  o.detune.value = detune;
  const env = a.createGain();
  env.gain.setValueAtTime(0.0001, t);
  env.gain.exponentialRampToValueAtTime(peak * level, t + attack);
  env.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(env);
  send(env, wet);
  o.start(t);
  o.stop(t + dur + 0.05);
}

/** A bell: the note, a faint inharmonic partial for the glass, and a twin a hair out of tune so it shimmers. */
function bell(at: number, freq: number, dur: number, peak: number, wet = 0.38) {
  tone(at, freq, dur, peak, { wet });
  tone(at, freq, dur * 0.9, peak * 0.45, { wet, detune: 7 });
  tone(at, freq * 2.76, dur * 0.3, peak * 0.12, { wet });
}

/** A swish: noise swept up through a band, for a message going out. */
function swish(at: number, from: number, to: number, dur: number, peak: number) {
  const a = g!.a;
  const t = a.currentTime + lead + at;
  const src = a.createBufferSource();
  src.buffer = g!.noise;
  const band = a.createBiquadFilter();
  band.type = "bandpass";
  band.Q.value = 1.4;
  band.frequency.setValueAtTime(from, t);
  band.frequency.exponentialRampToValueAtTime(to, t + dur);
  const env = a.createGain();
  env.gain.setValueAtTime(0.0001, t);
  env.gain.exponentialRampToValueAtTime(peak * level, t + dur * 0.35);
  env.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  src.connect(band).connect(env);
  send(env, 0.25);
  src.start(t);
  src.stop(t + dur + 0.02);
}

// Never a burst: a fast drag is a run of ticks, not a buzz, and a page that
// shows ten notices at once chimes once.
const GAP: Record<UISound, number> = {
  tap: 35, up: 35, tick: 24, on: 60, off: 60, select: 60, open: 80, menu: 120,
  ok: 300, info: 300, err: 300, send: 200, receive: 400, delete: 120, undo: 120,
  // slide under the switches' domino step (Toggle.svelte), or a run of them would lose every other one
  wind: 26, slide: 30, rise: 45, done: 500, key: 22, land: 60,
  pluck: 28, zip: 60, seat: 50, medal: 60, settle: 45, glint: 12, grow: 28,
  lift: 120, slot: 35, drop: 120, grab: 60, release: 60, hover: 400,
};
/** When each sound was last made, or is booked to be (play's `delay`): a few seconds of them. */
const booked: Partial<Record<UISound, number[]>> = {};

/**
 * What a tab opening sets off by itself, many at once: each is a little
 * quieter than the one before it in the same moment, down to two fifths, so
 * a page of switches and dials arriving together is a ripple, never louder
 * than one hand on one control.
 */
const ARRIVING = new Set<UISound>(["wind", "slide", "rise", "done", "key", "land", "pluck", "zip", "seat", "medal", "settle", "glint",
  "grow"]);

/** A major pentatonic, in semitones: any run of notes picked from it sounds like a tune, never a clash. */
const PENTA = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21, 24];
let arrivals: number[] = [];

let asked = 0;
/**
 * When the run of sounds this one is in was asked for: a loop booking a
 * domino's notes counts every delay from the same moment. The first sound of
 * all wakes the sound card, which can take a quarter of a second, and the rest
 * of the run would have come that much late, into the next list's notes.
 */
function askedAt(): number {
  if (!asked) {
    asked = performance.now();
    queueMicrotask(() => (asked = 0));
  }
  return asked;
}

/**
 * Play one. `p` (0 to 1) moves a tick's pitch with where the step is, so a
 * dial sweeping round rises as it goes; `strong` is a major mark; `level` (0
 * to 1) plays it softer, for something that goes on by itself (the typing
 * speed's keyboard, typing for as long as it is on screen).
 *
 * `delay` (ms) books it that far ahead on the sound card's own clock, for a
 * run of them that goes with a run of animations started at once (switches
 * falling like dominoes, a chart's bars): timers fired one at a time bunched
 * up while a tab was busy opening, two in the same instant, and the second was
 * lost. The least gap is kept between the times they are heard, not asked for.
 */
export function play(name: UISound, opts: { p?: number; strong?: boolean; level?: number; delay?: number } = {}): void {
  const now = askedAt();
  const when = now + Math.max(0, opts.delay ?? 0);
  const times = (booked[name] ?? []).filter((t) => t > now - 3000);
  if (times.some((t) => Math.abs(t - when) < GAP[name])) return;
  if (!audio()) return;
  times.push(when);
  booked[name] = times;
  if (ARRIVING.has(name)) {
    arrivals = arrivals.filter((t) => now - t < 900);
    level = Math.max(0.4, 1 / (1 + 0.08 * arrivals.length));
    arrivals.push(now);
  }
  level *= Math.max(0.05, Math.min(1, opts.level ?? 1));
  // From the moment it is made, not asked for: waking the sound card took the first one of all a good while.
  lead = Math.max(0, when - performance.now()) / 1000;
  try {
    voices(name, opts);
  } catch {
    /* a sound is never worth an error */
  } finally {
    level = 1;
    lead = 0;
  }
}

/**
 * One sound, made offline and handed back rather than played: how the tests
 * measure each one (how loud, how long, never clipping) without a speaker.
 */
export async function renderSound(name: UISound, opts: { p?: number; strong?: boolean } = {}, seconds = 2.5,
                                  settled = false): Promise<AudioBuffer> {
  const off = new OfflineAudioContext(2, Math.ceil(44100 * (seconds + (settled ? RENDER_LEAD : 0))), 44100);
  const was = g;
  g = graph(off);
  lead = settled ? RENDER_LEAD : 0;
  try {
    voices(name, opts);
  } finally {
    g = was;
    lead = 0;
  }
  return off.startRendering();
}

/** Seconds of quiet a sound measured `settled` starts after: the compressor settled, as it is at the speakers. */
export const RENDER_LEAD = 0.3;

function voices(name: UISound, { p = 0.5, strong = false }: { p?: number; strong?: boolean } = {}) {
  // Levels set by measuring each one rendered (tests/test_ui_sounds.py): a
  // click peaks near -22 dB, a detent near -26, a chime near -15. Noise
  // through a narrow band carries little, so the clicks' envelopes go well
  // past 1 to get there.
  switch (name) {
    case "tap":
      click(0, 2200, 0.03, 1.3, 1.2, 0.05);
      tone(0, 300, 0.05, 0.12, { wet: 0, attack: 0.001 });
      break;
    case "up":
      // The press let go of: the same click coming back up, lighter and a little higher, as a real button's spring.
      click(0, 3100, 0.02, 0.8, 1.5, 0.05);
      tone(0, 470, 0.035, 0.06, { wet: 0, attack: 0.001 });
      break;
    case "tick":
      click(0, 3200 + 1400 * p, strong ? 0.024 : 0.018, strong ? 1.4 : 0.95, 3, 0.06);
      tone(0, 2200 + 600 * p, 0.015, strong ? 0.08 : 0.05, { wet: 0, attack: 0.0008 });
      break;
    case "on":
      click(0, 2700, 0.024, 0.7, 1.8, 0.05);
      click(0.036, 4000, 0.02, 0.55, 2.2, 0.07);
      tone(0.03, 1046.5, 0.18, 0.06, { wet: 0.35 });
      break;
    case "off":
      click(0, 3800, 0.022, 0.7, 2.2, 0.05);
      click(0.036, 2400, 0.024, 0.65, 1.8, 0.07);
      tone(0.03, 698.5, 0.16, 0.055, { wet: 0.35 });
      break;
    case "select":
      click(0, 3000, 0.022, 2.0, 2.4, 0.06);
      bell(0.008, 1318.5, 0.4, 0.07, 0.35);
      break;
    case "open":
      tone(0, 620, 0.12, 0.14, { glide: 930, wet: 0.25 });
      click(0, 2200, 0.016, 1.0, 1.6, 0.03);
      break;
    case "menu":
      // Rising, airy, a tick at its front and a shimmer far above it in the room.
      click(0, 3400, 0.014, 0.9, 2.6, 0.05);
      tone(0, 540, 0.09, 0.12, { glide: 820, wet: 0.28, attack: 0.004 });
      tone(0.018, 1620, 0.24, 0.025, { wet: 0.45 });
      break;
    case "ok":
      bell(0, 880, 1.1, 0.12);
      bell(0.095, 1318.5, 1.4, 0.1);
      break;
    case "info":
      bell(0, 1046.5, 1.0, 0.17);
      tone(0.06, 1568, 0.6, 0.03, { wet: 0.45 });
      break;
    case "err":
      tone(0, 659.3, 0.24, 0.12, { type: "triangle", glide: 622, wet: 0.18 });
      tone(0.13, 523.3, 0.38, 0.12, { type: "triangle", glide: 494, wet: 0.22 });
      break;
    case "send":
      swish(0, 500, 4200, 0.2, 0.55);
      tone(0.02, 700, 0.18, 0.06, { glide: 1400, wet: 0.25 });
      break;
    case "receive":
      bell(0, 1567.98, 0.7, 0.15, 0.32);
      tone(0, 784, 0.12, 0.08, { wet: 0.1 });
      break;
    case "delete":
      tone(0, 520, 0.16, 0.14, { glide: 250, wet: 0.12 });
      click(0, 1700, 0.022, 1.2, 1.4, 0.03);
      break;
    case "undo":
      tone(0, 300, 0.16, 0.08, { glide: 640, wet: 0.18 });
      click(0.1, 3000, 0.016, 0.35, 2.2, 0.05);
      break;
    // ── Arriving ──
    case "wind":
      // A detent, drier and softer than a hand's: the clocks winding round to where they are set.
      click(0, 2600 + 1600 * p, strong ? 0.02 : 0.014, strong ? 0.8 : 0.55, 3.2, 0.03);
      tone(0, 1900 + 700 * p, 0.012, strong ? 0.04 : 0.025, { wet: 0, attack: 0.0008 });
      break;
    case "slide": {
      // A switch arriving on: its knob pulled across (a breath of air, quickening), then, as it hits
      // the end a fifth of a second in (tg-arrive in Toggle.svelte), the switch's own "on", softer.
      // A hair different every time, so a page of them is a ripple and not one sound repeated. Switches
      // falling one after another like dominoes climb the scale, p being how far along the run one is.
      const v = 0.97 + Math.random() * 0.06;
      const note = Math.pow(2, PENTA[Math.round(Math.min(1, Math.max(0, p)) * 7)] / 12);
      swish(0, 700, 2400, 0.17, 0.07);
      click(0.19, 2700 * v, 0.024, 0.42, 1.8, 0.05);
      click(0.226, 4000 * v, 0.02, 0.33, 2.2, 0.07);
      tone(0.22, 1046.5 * note * (0.995 + Math.random() * 0.01), 0.18, 0.036, { wet: 0.35 });
      break;
    }
    case "rise": {
      // Up into place, a step higher each time (p): a bar of four fills as a little run upwards.
      const f = 440 * Math.pow(2, (Math.round(p * 7) * 2) / 12);
      tone(0, f, 0.24, 0.09, { glide: f * 1.5, wet: 0.3, attack: 0.02 });
      click(0, 2400, 0.012, 0.35, 2, 0.04);
      break;
    }
    case "done":
      bell(0, 1318.5, 0.9, 0.06);
      bell(0.075, 1760, 1.1, 0.05);
      break;
    case "key":
      // One key of a soft keyboard; the space bar (strong) lower and a touch heavier, as a long key is.
      if (strong) {
        click(0, 1700 + Math.random() * 300, 0.02, 0.3, 1.6, 0.03);
        tone(0, 210, 0.03, 0.03, { wet: 0, attack: 0.001 });
      } else {
        click(0, 3400 + Math.random() * 600, 0.012, 0.25, 3, 0.02);
      }
      break;
    case "land":
      // Set down with a bounce: a soft thump, a little rising boop, a glint after.
      click(0, 1500, 0.024, 0.5, 1.2, 0.05);
      tone(0, 330, 0.09, 0.05, { glide: 520, wet: 0.15, attack: 0.003 });
      tone(0.05, 1568, 0.25, 0.012, { wet: 0.5 });
      break;
    case "pluck": {
      // A bar of a chart growing up: a soft marimba note, higher the taller the bar, so a week of them plays
      // the week's shape. The wooden overtone four times up dies first, as a marimba's does.
      const f = 523.25 * Math.pow(2, PENTA[Math.round(Math.min(1, Math.max(0, p)) * 10)] / 12);
      tone(0, f, 0.16, 0.066, { wet: 0.22, attack: 0.002 });
      tone(0, f * 3.93, 0.045, 0.013, { wet: 0.1, attack: 0.001 });
      click(0, 2600, 0.008, 0.2, 2, 0.03);
      break;
    }
    case "zip":
      // Off on its way: a quick breath of air rising, the fast start of a slider's sweep in.
      swish(0, 900, 3600, 0.2, 0.11);
      break;
    case "seat":
      // Settled where it belongs: a soft woody tock, higher the further along; against the end of
      // the track (strong) lower and firmer, a knock.
      if (strong) {
        click(0, 900, 0.026, 0.5, 1.2, 0.04);
        tone(0, 150, 0.07, 0.05, { wet: 0.05, attack: 0.002 });
      } else {
        click(0, 1300 + 700 * p, 0.02, 0.34, 1.6, 0.04);
        tone(0, 240 + 160 * p, 0.06, 0.035, { wet: 0.08, attack: 0.002 });
      }
      break;
    case "medal": {
      // A coin's ting: the note, a metal's out-of-tune partials above it, gone before a bell's would be.
      // Bronze, silver, gold (p 0, 0.5, 1) are C, E, G: the three in turn are a chord.
      const f = 1046.5 * Math.pow(2, Math.round(Math.min(1, Math.max(0, p)) * 7) / 12);
      click(0, 6000, 0.004, 0.16, 3, 0.05);
      tone(0, f, 0.7, 0.036, { wet: 0.4, attack: 0.002 });
      tone(0, f * 2.76, 0.28, 0.012, { wet: 0.4, attack: 0.001 });
      tone(0, f * 5.4, 0.12, 0.005, { wet: 0.3, attack: 0.001 });
      break;
    }
    case "glint": {
      // A glint of light: a high glassy ping with a shimmer above it, gone in a tenth of a second, so a run of
      // them is a harp's sweep (Appearance's colours flooding in, lib/colorwave.ts). The chosen one (strong)
      // rings a fifth higher after it.
      const f = 1046.5 * Math.pow(2, PENTA[Math.round(Math.min(1, Math.max(0, p)) * 10)] / 12);
      tone(0, f, 0.11, 0.042, { wet: 0.4, attack: 0.001 });
      tone(0, f * 3.01, 0.04, 0.01, { wet: 0.3, attack: 0.001 });
      if (strong) tone(0.06, f * 1.5, 0.3, 0.03, { wet: 0.5, attack: 0.002 });
      break;
    }
    case "grow": {
      // A bar growing up (an account's week): its note rises with it from the same low start, as far as the bar goes,
      // up to an octave and a half for the tallest, and rings where it got to as the bar lands. A pluck at the start
      // said the height once, too short to hear as the bar's own; this is heard going up more or less.
      const to = 392 * Math.pow(2, PENTA[Math.round(Math.min(1, Math.max(0, p)) * 8)] / 12);
      tone(0, 370, 0.3, 0.05, { type: "triangle", glide: to, wet: 0.22, attack: 0.03 });
      tone(0.21, to, 0.2, 0.04, { wet: 0.3, attack: 0.002 });
      click(0.21, 2400, 0.008, 0.16, 2, 0.03);
      break;
    }
    case "settle":
      // A widget set down in its place: a muted thup, felt more than heard.
      tone(0, 160, 0.11, 0.06, { glide: 115, wet: 0.12, attack: 0.004 });
      click(0, 950, 0.018, 0.22, 1.1, 0.04);
      break;
    // ── Dragging ──
    case "lift":
      tone(0, 360, 0.11, 0.12, { glide: 620, wet: 0.15, attack: 0.004 });
      click(0, 2800, 0.014, 0.6, 2.2, 0.03);
      break;
    case "slot":
      // Woody: a row of the list sliding past another, lower down the list a little lower.
      click(0, 1400 + 900 * p, 0.02, 0.55, 2, 0.04);
      tone(0, 300 + 160 * p, 0.05, 0.045, { wet: 0.05, attack: 0.001 });
      break;
    case "drop":
      // Put down: a low thunk and a small settle after it.
      click(0, 900, 0.03, 1.0, 1.1, 0.05);
      tone(0, 190, 0.1, 0.1, { glide: 140, wet: 0.08, attack: 0.002 });
      click(0.06, 1600, 0.015, 0.45, 2, 0.04);
      break;
    case "grab":
      click(0, 1800, 0.018, 0.9, 1.6, 0.03);
      tone(0, 240, 0.045, 0.07, { wet: 0, attack: 0.001 });
      break;
    case "release":
      click(0, 3000, 0.014, 0.6, 2.2, 0.04);
      tone(0, 420, 0.035, 0.035, { wet: 0.1, attack: 0.001 });
      break;
    case "hover":
      swish(0, 400, 1800, 0.28, 0.32);
      tone(0.05, 660, 0.25, 0.03, { glide: 990, wet: 0.4 });
      break;
  }
}

/** True while sounds are on: for a caller about to do work only to make one. */
export const soundOn = () => get(uiSound);

// ── Everything at once ───────────────────────────────────────────────────────
// Buttons click as they are pressed, a range input ticks as it moves, a
// checkbox flips on or off, and a notice chimes by its kind. A control with
// a sound of its own (a switch, a list of choices) carries data-sound="self",
// and anything that should stay quiet data-sound="none".
const PRESSABLE = "button, [role='button'], a[href], summary, [role='menuitem'], [role='tab']";
let installed = false;

export function installUISounds(): void {
  if (installed || typeof document === "undefined") return;
  installed = true;
  const quiet = (el: Element) => !!el.closest("[data-sound='self'], [data-sound='none']");

  // The sound card woken while nothing moves yet: the first sound of all took it a fifth of a second to wake,
  // the page standing still meanwhile, in the middle of the first tab's opening.
  if (get(uiSound)) {
    if ("requestIdleCallback" in window) requestIdleCallback(() => void audio(), { timeout: 300 });
    else setTimeout(() => void audio(), 0);
  }

  // Pressed, and let go: a click down, and a lighter one back up when the button is released, wherever the
  // pointer is by then (a real button springs back either way). A press that never was (cancelled) has no release.
  let pressed = false;
  document.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const el = (e.target as Element | null)?.closest?.(PRESSABLE);
    if (!el || quiet(el)) return;
    if ((el as HTMLButtonElement).disabled || el.getAttribute("aria-disabled") === "true") return;
    pressed = true;
    play("tap");
  }, { capture: true, passive: true });
  document.addEventListener("pointerup", (e) => {
    if (!pressed || e.button !== 0) return;
    pressed = false;
    play("up");
  }, { capture: true, passive: true });
  document.addEventListener("pointercancel", () => (pressed = false), { capture: true, passive: true });

  // The keyboard presses buttons too, and lets them go.
  let keyed = false;
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    if (e.repeat) return;
    const el = document.activeElement;
    if (!el || !el.matches(PRESSABLE) || quiet(el)) return;
    keyed = true;
    play("tap");
  }, { capture: true });
  document.addEventListener("keyup", (e) => {
    if (!keyed || (e.key !== "Enter" && e.key !== " ")) return;
    keyed = false;
    play("up");
  }, { capture: true });

  // A slider by hand: taken hold of and let go like a dial's knob, and a detent each time it passes a notch
  // (a twentieth of the way along, or its own step where that is coarser) rather than on every pixel, which
  // was a buzz. Firmer where it crosses zero or its default (data-default), a knock against either end. From
  // the keyboard every press is heard: each one is a step.
  const sliders = new WeakMap<HTMLInputElement, number>();
  let held: HTMLInputElement | null = null;
  const isSlider = (t: EventTarget | null): t is HTMLInputElement =>
    t instanceof HTMLInputElement && t.type === "range" && !t.disabled && !quiet(t);
  document.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || !isSlider(e.target)) return;
    held = e.target;
    sliders.set(held, Number(held.value));
    play("grab");
  }, { capture: true, passive: true });
  const letGo = () => {
    if (!held) return;
    held = null;
    play("release");
  };
  document.addEventListener("pointerup", letGo, { capture: true, passive: true });
  document.addEventListener("pointercancel", letGo, { capture: true, passive: true });
  document.addEventListener("focusin", (e) => {
    if (isSlider(e.target)) sliders.set(e.target, Number(e.target.value));
  }, { capture: true, passive: true });

  document.addEventListener("input", (e) => {
    const t = e.target as HTMLInputElement | null;
    if (!t || t.type !== "range" || quiet(t)) return;
    const lo = Number(t.min || 0);
    const hi = Number(t.max || 100);
    const v = Number(t.value);
    const was = sliders.get(t) ?? v;
    sliders.set(t, v);
    if (!(hi > lo) || v === was) return;
    const p = (v - lo) / (hi - lo);
    if (v <= lo || v >= hi) return play("seat", { p, strong: true });
    const crossed = (x: number) => Number.isFinite(x) && x > lo && x < hi && (was - x) * (v - x) <= 0;
    if (crossed(lo < 0 && hi > 0 ? 0 : NaN) || crossed(t.dataset.default ? Number(t.dataset.default) : NaN)) {
      return play("tick", { p, strong: true });
    }
    const notch = Math.max(Number(t.step) || 0, (hi - lo) / 20);
    if (held !== t || Math.floor((v - lo) / notch) !== Math.floor((was - lo) / notch)) play("tick", { p });
  }, { capture: true, passive: true });

  document.addEventListener("change", (e) => {
    const t = e.target as HTMLInputElement | null;
    if (!t || quiet(t)) return;
    if (t.type === "checkbox") play(t.checked ? "on" : "off");
    else if (t.type === "radio") play("select");
  }, { capture: true, passive: true });

  // A notice chimes by its kind, once however many arrive together.
  let seen = Math.max(0, ...get(toasts).map((t) => t.id));
  toasts.subscribe((list) => {
    const fresh = list.filter((t) => t.id > seen);
    if (!fresh.length) return;
    seen = Math.max(...fresh.map((t) => t.id));
    const kind = fresh[fresh.length - 1].kind;
    play(kind === "ok" ? "ok" : kind === "err" ? "err" : "info");
  });
}
