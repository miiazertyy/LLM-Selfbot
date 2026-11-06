/**
 * The practice LIVE's crowd (Settings, TikTok, LIVE): made-up viewers who join, chat, tap hearts, follow, share and
 * send gifts, at a pace that can be set, for the persona to co-host (LiveDemo.svelte). Pure: every choice comes from
 * the random function handed in, so a test can play it back.
 */

export type LiveKind = "comment" | "gift" | "follow" | "join" | "share" | "like";
export type Gift = { name: string; emoji: string; coins: number };
export type CrowdEvent = { event: LiveKind; name: string; text: string; gift?: Gift; count?: number };
export type Level = "quiet" | "lively" | "busy";

/** TikTok's commoner gifts, cheapest first, with what each costs in coins. */
export const GIFTS: Gift[] = [
  { name: "Rose", emoji: "🌹", coins: 1 },
  { name: "TikTok", emoji: "🎵", coins: 1 },
  { name: "Finger Heart", emoji: "🫰", coins: 5 },
  { name: "Perfume", emoji: "🧴", coins: 20 },
  { name: "Doughnut", emoji: "🍩", coins: 30 },
  { name: "Hand Hearts", emoji: "🫶", coins: 100 },
  { name: "Corgi", emoji: "🐶", coins: 299 },
  { name: "Galaxy", emoji: "🌌", coins: 1000 },
];

export const VIEWERS = [
  "mara.k", "noah_films", "sunny.daze", "kit.tok", "eli.moss", "rosa.draws", "lea.frames", "sami_ok", "theo.wav",
  "ines.lol", "jules_22", "nina.mp4", "oskar.b", "zoe.lin", "max_irl", "ava.cxs", "leo.fm", "mila.png", "yuki.jpg",
  "dani.exe",
];

/** What people say in a LIVE's chat: hellos, questions, asks, praise, and the odd line of emoji. */
export const COMMENTS = [
  "hiii", "omg hi!!", "first time catching you live", "where are you from?", "what are you up to today?",
  "your vibe is unreal", "can you say hi to my sister?", "what music is this", "love your videos",
  "who else is here from fyp", "hi from france 🇫🇷", "are you a student?", "what's your fav song rn",
  "you're so funny", "do a q&a!!", "😂😂😂", "🔥🔥🔥", "this is my comfort stream", "what's your name?",
  "did you dye your hair?", "drop your playlist", "notice me pls", "good morning from japan",
  "what's for dinner", "can you do a dance", "how's your day going?", "your room looks so cozy",
  "rate my username", "i just got here what did i miss", "what camera do you use?",
];

/** What people say to the host by name ({host}), so answering only when it is named has something to answer. */
export const TO_HOST = [
  "{host} hiii", "hi {host}!!", "{host} can you say hi to me", "{host} what's your fav food?", "love you {host}",
  "{host} where do you live?", "{host} you're the best", "{host} what are you doing later?",
];

/** How busy the crowd is: the wait between two things happening, and how many are watching. */
export const LEVELS: Record<Level, { gap: [number, number]; viewers: [number, number] }> = {
  quiet: { gap: [4200, 9000], viewers: [8, 40] },
  lively: { gap: [1600, 4200], viewers: [60, 260] },
  busy: { gap: [500, 1600], viewers: [400, 2400] },
};

/** How often each kind of thing happens, out of a hundred. */
export const WEIGHTS: [LiveKind, number][] = [
  ["comment", 46], ["like", 24], ["join", 14], ["gift", 7], ["follow", 7], ["share", 2],
];

type Rnd = () => number;

export function pick<T>(list: readonly T[], rnd: Rnd = Math.random): T {
  return list[Math.min(list.length - 1, Math.floor(rnd() * list.length))];
}

export function kindOf(rnd: Rnd = Math.random): LiveKind {
  let n = rnd() * WEIGHTS.reduce((a, [, w]) => a + w, 0);
  for (const [kind, w] of WEIGHTS) {
    if ((n -= w) < 0) return kind;
  }
  return "comment";
}

/** A gift, the cheap ones far more often, and how many at once (a combo of roses, one galaxy). */
export function giftOf(rnd: Rnd = Math.random): { gift: Gift; count: number } {
  const r = rnd();
  const gift = r < 0.65 ? GIFTS[r < 0.4 ? 0 : 1] : r < 0.88 ? GIFTS[2 + Math.floor(rnd() * 3)]
    : r < 0.975 ? GIFTS[5] : GIFTS[6 + Math.floor(rnd() * 2)];
  const count = gift.coins <= 5 ? 1 + Math.floor(rnd() * 10) : 1;
  return { gift, count };
}

/** What a gift is called in the chat, and to the persona: "Rose x5". */
export function giftText(gift: Gift, count = 1): string {
  return count > 1 ? `${gift.name} x${count}` : gift.name;
}

/**
 * The next thing in the crowd. `recent` is the comments said lately, not said again straight away; `here` is who is
 * in, so someone who joined can chat, and someone new can join; `host`, what the host is called, for the odd comment
 * to them by name.
 */
export function crowdEvent(rnd: Rnd = Math.random, recent: string[] = [], here: string[] = [], host = ""): CrowdEvent {
  const kind = kindOf(rnd);
  const newcomer = VIEWERS.filter((v) => !here.includes(v));
  if (kind === "join" && newcomer.length) return { event: "join", name: pick(newcomer, rnd), text: "" };
  const name = here.length && rnd() < 0.8 ? pick(here, rnd) : pick(VIEWERS, rnd);
  if (kind === "gift") {
    const { gift, count } = giftOf(rnd);
    return { event: "gift", name, text: giftText(gift, count), gift, count };
  }
  if (kind === "comment" || kind === "join") {
    if (host && rnd() < 0.18) {
      const named = TO_HOST.map((t) => t.replace("{host}", host)).filter((c) => !recent.includes(c));
      if (named.length) return { event: "comment", name, text: pick(named, rnd) };
    }
    const fresh = COMMENTS.filter((c) => !recent.includes(c));
    return { event: "comment", name, text: pick(fresh.length ? fresh : COMMENTS, rnd) };
  }
  return { event: kind, name, text: "" };
}

/** A viewer's level on TikTok (the badge before their name), the same every time for the same name. */
export function levelOf(name: string): number {
  let h = 3;
  for (const ch of name) h = (h * 17 + ch.charCodeAt(0)) % 997;
  return 1 + (h % 42);
}

/** The colour of a level's badge, by tens, as TikTok tiers them: blue, green, violet, pink, gold. */
export function levelHue(level: number): number {
  return [212, 152, 268, 330, 42][Math.min(4, Math.floor((level - 1) / 10))];
}

/** The wait before the next thing, in ms, for this crowd. */
export function nextDelay(level: Level, rnd: Rnd = Math.random): number {
  const [lo, hi] = LEVELS[level].gap;
  return Math.round(lo + rnd() * (hi - lo));
}

/** How many are watching a moment later: a drift towards the crowd's size, never below one. */
export function driftViewers(now: number, level: Level, rnd: Rnd = Math.random): number {
  const [lo, hi] = LEVELS[level].viewers;
  const aim = lo + (hi - lo) * 0.6;
  const step = (aim - now) * 0.12 + (rnd() - 0.5) * Math.max(2, now * 0.06);
  return Math.max(1, Math.round(now + step));
}

/** "1.2K", as TikTok writes a count. */
export function compactCount(n: number): string {
  if (n < 1000) return String(n);
  if (n < 10000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}K`;
  return `${Math.round(n / 1000)}K`;
}

/** A viewer's colour, the same every time for the same name. */
export function hueOf(name: string): number {
  let h = 7;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}
