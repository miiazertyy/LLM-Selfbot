/**
 * The little examples beside the switches in Settings: what a switch does,
 * played out, on and off (SwitchDemo.svelte draws them).
 *
 * Most switches change how it chats, so most examples are a few lines of a
 * chat that play out on a loop: a message comes in, it types, it answers, or
 * does not. Each line has the moment in the loop it appears. A few switches
 * are not about chatting (a status that cycles, the night, what runs, a
 * hidden browser) and have a scene of their own, named by `scene`.
 *
 * Kept as data so the words can be read, and tested, in one place. The chat
 * lines are what people type, lower case and all; everything else is plain.
 */

export type Line = {
  /** Milliseconds into the loop when it appears. */
  at: number;
  who: "them" | "me" | "note";
  text?: string;
  /** Typing dots (gone at `until`), a voice note, a picture, a reply with its quote, a request, an alert, a bio card, a summary. */
  kind?: "typing" | "voice" | "image" | "reply" | "request" | "alert" | "bio" | "summary";
  /** When it is gone again (the typing dots). */
  until?: number;
  /** What it becomes, and when: a refusal swapped, a request accepted. */
  then?: string;
  thenAt?: number;
  /** Lit up from `glowAt` on (what goes into a summary). */
  glow?: boolean;
  /** Faded: a line that is not taken into account. */
  dim?: boolean;
  /** Who "them" is: an initial, and a colour. */
  from?: string;
  /** A small mark on a note: dice, clock, zzz, cross, check, bell, bellOff, warn. */
  mark?: string;
};

export type Chat = { lines: Line[]; glowAt?: number };
export type Demo = {
  /** How long one loop is, in ms. */
  loop?: number;
  on: Chat | { scene: string };
  off: Chat | { scene: string };
};

const typed = (at: number, until: number): Line => ({ at, who: "me", kind: "typing", until });

export const DEMOS: Record<string, Demo> = {
  "bot.allow_dm": {
    on: { lines: [{ at: 300, who: "them", text: "hey!! you up?" }, typed(1100, 2100), { at: 2100, who: "me", text: "yeah whats up" }] },
    off: { lines: [{ at: 300, who: "them", text: "hey!! you up?" }, { at: 1700, who: "note", text: "No reply in DMs", mark: "cross" }] },
  },
  "bot.allow_gc": {
    on: { lines: [{ at: 300, who: "them", from: "G", text: "who's coming tonight" }, typed(1100, 2000), { at: 2000, who: "me", text: "me!!" }] },
    off: { lines: [{ at: 300, who: "them", from: "G", text: "who's coming tonight" }, { at: 1700, who: "note", text: "Quiet in group chats", mark: "cross" }] },
  },
  "bot.allow_server": {
    on: { lines: [{ at: 300, who: "them", from: "#", text: "[@juni] thoughts?" }, typed(1100, 2100), { at: 2100, who: "me", text: "honestly yes" }] },
    off: { lines: [{ at: 300, who: "them", from: "#", text: "[@juni] thoughts?" }, { at: 1700, who: "note", text: "Mentions go unanswered", mark: "cross" }] },
  },
  "bot.hold_conversation": {
    loop: 6200,
    on: { lines: [{ at: 200, who: "them", text: "[@juni] hii" }, { at: 1100, who: "me", text: "heyy" },
                  { at: 2200, who: "them", text: "how was it" }, { at: 3300, who: "me", text: "so good omg" }] },
    off: { lines: [{ at: 200, who: "them", text: "[@juni] hii" }, { at: 1100, who: "me", text: "heyy" },
                   { at: 2200, who: "them", text: "how was it" }, { at: 3300, who: "note", text: "Waits for another mention", mark: "cross" }] },
  },
  "bot.reply_ping": {
    on: { lines: [{ at: 300, who: "them", text: "did u see it" }, { at: 1500, who: "me", kind: "reply", text: "yes!!", then: "Mara" }] },
    off: { lines: [{ at: 300, who: "them", text: "did u see it" }, { at: 1500, who: "me", text: "yes!!" }] },
  },
  "bot.disable_mentions": {
    on: { lines: [{ at: 300, who: "them", text: "u coming?" }, { at: 1500, who: "me", text: "yes Mara wait for me" }] },
    off: { lines: [{ at: 300, who: "them", text: "u coming?" }, { at: 1500, who: "me", text: "yes [@Mara] wait for me" }] },
  },
  "bot.read_bios": {
    on: { lines: [{ at: 200, who: "them", kind: "bio", text: "loves cats · paris" }, { at: 1600, who: "me", text: "wait u like cats??" }] },
    off: { lines: [{ at: 200, who: "them", kind: "bio", text: "loves cats · paris", dim: true }, { at: 1600, who: "me", text: "hey whats up" }] },
  },
  "bot.trigger_bypasses_ignore": {
    on: { lines: [{ at: 200, who: "them", text: "[juni] u there" }, { at: 1000, who: "note", text: "Rolled a skip", mark: "dice" },
                  { at: 2000, who: "me", text: "yeah here" }] },
    off: { lines: [{ at: 200, who: "them", text: "[juni] u there" }, { at: 1000, who: "note", text: "Rolled a skip", mark: "dice" },
                   { at: 2000, who: "note", text: "Skipped", mark: "cross" }] },
  },
  "bot.mention_bypasses_ignore": {
    on: { lines: [{ at: 200, who: "them", text: "[@juni] look" }, { at: 1000, who: "note", text: "Rolled a skip", mark: "dice" },
                  { at: 2000, who: "me", text: "omg" }] },
    off: { lines: [{ at: 200, who: "them", text: "[@juni] look" }, { at: 1000, who: "note", text: "Rolled a skip", mark: "dice" },
                   { at: 2000, who: "note", text: "Skipped", mark: "cross" }] },
  },
  "bot.realistic_typing": {
    on: { lines: [{ at: 200, who: "them", text: "tell me everything" }, typed(800, 2600), { at: 2600, who: "me", text: "ok so basically" }] },
    off: { lines: [{ at: 200, who: "them", text: "tell me everything" }, { at: 800, who: "me", text: "ok so basically" }] },
  },
  "bot.batch_messages": {
    loop: 6000,
    on: { lines: [{ at: 200, who: "them", text: "wait" }, { at: 700, who: "them", text: "one sec" }, { at: 1200, who: "them", text: "ok so" },
                  typed(2000, 2900), { at: 2900, who: "me", text: "take ur time lol" }] },
    off: { lines: [{ at: 200, who: "them", text: "wait" }, { at: 800, who: "me", text: "?" }, { at: 1400, who: "them", text: "one sec" },
                   { at: 2000, who: "me", text: "ok" }, { at: 2600, who: "them", text: "ok so" }, { at: 3200, who: "me", text: "yes??" }] },
  },
  "bot.global_cooldown_enabled": {
    on: { lines: [{ at: 300, who: "me", text: "Mara: sure" }, { at: 1100, who: "note", text: "A pause", mark: "clock" },
                  { at: 2500, who: "me", text: "Theo: yep" }] },
    off: { lines: [{ at: 300, who: "me", text: "Mara: sure" }, { at: 700, who: "me", text: "Theo: yep" }] },
  },
  "bot.pictures.enabled": {
    on: { lines: [{ at: 300, who: "them", text: "send a pic" }, typed(1000, 1800), { at: 1800, who: "me", kind: "image" }] },
    off: { lines: [{ at: 300, who: "them", text: "send a pic" }, { at: 1500, who: "me", text: "cant rn" }] },
  },
  "bot.tts.enabled": {
    on: { lines: [{ at: 300, who: "them", text: "say it out loud" }, { at: 1500, who: "me", kind: "voice" }] },
    off: { lines: [{ at: 300, who: "them", text: "say it out loud" }, { at: 1500, who: "me", text: "no way lol" }] },
  },
  "bot.memory_summary.enabled": {
    on: { lines: [{ at: 300, who: "note", kind: "summary", text: "Mara" }] },
    off: { lines: [{ at: 300, who: "note", text: "No summary", mark: "cross" }] },
  },
  "bot.memory_summary.include_my_messages": {
    on: { glowAt: 1500, lines: [{ at: 200, who: "them", text: "i got the job", glow: true }, { at: 800, who: "me", text: "no wayyy", glow: true }] },
    off: { glowAt: 1500, lines: [{ at: 200, who: "them", text: "i got the job", glow: true }, { at: 800, who: "me", text: "no wayyy", dim: true }] },
  },
  "bot.refusal.enabled": {
    on: { lines: [{ at: 200, who: "them", text: "are you a bot" }, { at: 1200, who: "me", text: "As an AI, I can't", then: "what?? no lol", thenAt: 2300 }] },
    off: { lines: [{ at: 200, who: "them", text: "are you a bot" }, { at: 1200, who: "me", text: "As an AI, I can't" }] },
  },
  "bot.late_reply.enabled": {
    on: { lines: [{ at: 200, who: "them", text: "u free saturday?" }, { at: 1000, who: "note", text: "3 hours later", mark: "clock" },
                  { at: 2000, who: "me", text: "sorry just saw this, yes!" }] },
    off: { lines: [{ at: 200, who: "them", text: "u free saturday?" }, { at: 1000, who: "note", text: "3 hours later", mark: "clock" },
                   { at: 2000, who: "me", text: "yes!" }] },
  },
  "bot.stale_reply.enabled": {
    on: { lines: [{ at: 200, who: "them", text: "anyone up for a game", dim: true }, { at: 1000, who: "note", text: "10 newer messages", mark: "chats" },
                  { at: 2000, who: "note", text: "Left alone", mark: "check" }] },
    off: { lines: [{ at: 200, who: "them", text: "anyone up for a game" }, { at: 1000, who: "note", text: "10 newer messages", mark: "chats" },
                   { at: 2000, who: "me", kind: "reply", text: "i am!", then: "game?" }] },
  },
  "bot.nudge.enabled": {
    on: { lines: [{ at: 200, who: "me", text: "talk later!" }, { at: 1000, who: "note", text: "2 days quiet", mark: "zzz" },
                  { at: 2100, who: "me", text: "hey you alive? lol" }] },
    off: { lines: [{ at: 200, who: "me", text: "talk later!" }, { at: 1000, who: "note", text: "2 days quiet", mark: "zzz" }] },
  },
  "bot.friend_requests.enabled": {
    on: { lines: [{ at: 300, who: "them", kind: "request", text: "Mara", then: "Friends", thenAt: 1900 }] },
    off: { lines: [{ at: 300, who: "them", kind: "request", text: "Mara" }] },
  },
  "snapchat.auto_add_friends": {
    on: { lines: [{ at: 300, who: "them", kind: "request", from: "S", text: "Kit", then: "Added back", thenAt: 1900 }] },
    off: { lines: [{ at: 300, who: "them", kind: "request", from: "S", text: "Kit" }] },
  },
  "notifications.telegram_error_notifications": {
    on: { lines: [{ at: 300, who: "note", text: "Something broke", mark: "warn" }, { at: 1300, who: "note", kind: "alert", text: "Error in Discord #1" }] },
    off: { lines: [{ at: 300, who: "note", text: "Something broke", mark: "warn" }, { at: 1500, who: "note", text: "Only in the logs", mark: "cross" }] },
  },
  "notifications.telegram_crash_alerts": {
    on: { lines: [{ at: 300, who: "note", text: "Discord #1 stopped", mark: "warn" }, { at: 1300, who: "note", kind: "alert", text: "Discord #1 stopped" }] },
    off: { lines: [{ at: 300, who: "note", text: "Discord #1 stopped", mark: "warn" }, { at: 1500, who: "note", text: "Only in the logs", mark: "cross" }] },
  },
  "notifications.telegram_quiet": {
    on: { lines: [{ at: 400, who: "note", kind: "alert", text: "Error in Discord #1", mark: "bellOff" }] },
    off: { lines: [{ at: 400, who: "note", kind: "alert", text: "Error in Discord #1", mark: "bell" }] },
  },
  "notifications.ratelimit_notifications": {
    on: { lines: [{ at: 300, who: "note", text: "Rate limited", mark: "clock" }, { at: 1300, who: "note", kind: "alert", text: "Discord #1 was rate limited", mark: "hook" }] },
    off: { lines: [{ at: 300, who: "note", text: "Rate limited", mark: "clock" }, { at: 1500, who: "note", text: "No notice", mark: "cross" }] },
  },
  "bot.night_invisible.enabled": { loop: 5600, on: { scene: "night" }, off: { scene: "night" } },
  "bot.status.enabled": { loop: 5200, on: { scene: "status" }, off: { scene: "status" } },
  "bot.profile_cache.enabled": { on: { scene: "profile" }, off: { scene: "profile" } },
  "snapchat.headless": { on: { scene: "browser" }, off: { scene: "browser" } },
  "services.discord.enabled": { on: { scene: "run-discord" }, off: { scene: "run-discord" } },
  "services.snapchat.enabled": { on: { scene: "run-snapchat" }, off: { scene: "run-snapchat" } },
  "services.telegram.enabled": { on: { scene: "run-telegram" }, off: { scene: "run-telegram" } },
  "services.webui.enabled": { on: { scene: "run-webui" }, off: { scene: "run-webui" } },
};

export const hasDemo = (key: string) => key in DEMOS;

/** Splits "[@juni] thoughts?" into plain text and the highlighted bits (mentions, triggers). */
export function parts(text: string): { text: string; lit: boolean }[] {
  const out: { text: string; lit: boolean }[] = [];
  const re = /\[([^\]]+)\]/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push({ text: text.slice(last, m.index), lit: false });
    out.push({ text: m[1], lit: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), lit: false });
  return out;
}

/** The lines on show at a moment in the loop: those that have come, less any gone. */
export function linesAt(chat: Chat, t: number): Line[] {
  return chat.lines.filter((l) => l.at <= t && (l.until == null || t < l.until));
}
