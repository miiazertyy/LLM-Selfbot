/**
 * Big Picture Mode's director: which page is up, who is on stage, and when it moves on.
 *
 * Big Picture is a set of pages (Now, People, Accounts, Today, ...), and left
 * alone it walks through them by itself, the same pages anyone can walk into
 * and use. Nobody has to drive it: this decides, from the live queue and the
 * clock alone.
 *
 *   1. Someone whose reply the AI is writing or typing goes on stage, on Now.
 *      That is the part worth watching.
 *   2. Else someone whose message has only just arrived, for long enough to see
 *      it land.
 *   3. Else nobody: a reply that is only waiting, for its timer or its pace, is
 *      no reason to hold the screen, so the tour plays meanwhile and the queue
 *      says who is waiting.
 *
 * A spotlight is never taken away while its reply is written or typed, and
 * never within a few seconds of arriving, so the stage does not flicker. When
 * its reply goes out and the row leaves the queue, it stays up a moment longer
 * so the sent message is seen.
 *
 * The page on show is fixed when it starts. The tour can change under it,
 * because a friend request arrived or the summaries finished loading, and the
 * page you are looking at does not swap for another: the new list only decides
 * what comes next.
 *
 * Nothing is taken from under anyone. Anything done by hand holds the screen: a
 * press, a key, the pointer moving. A page's clock stops while it is held, so
 * letting go never lands on one already out of time, and the Now tab says
 * someone is being answered rather than the screen going to them. Space stays
 * put until it is pressed again. autoState says which of those it is, for the
 * button that shows it.
 *
 * Pure functions of plain data, no DOM and no stores, so it runs under Node in
 * tests/bigpicture_director.mjs.
 */

/** One conversation in the queue, as the director needs to see it. */
export type Row = {
  /** Unique across accounts: "target:rowId". */
  key: string;
  phase: "live" | "needs" | "off";
  /** 1 waiting, 2 writing, 3 pacing, 4 queued or typing; 0 when not being answered. */
  step: number;
  /** When a waiting or pacing reply fires, unix seconds. */
  eta?: number | null;
  /** When their latest message arrived, unix seconds. */
  ts?: number;
};

export type Page = "now" | "people" | "accounts" | "today" | "persona" | "pictures" | "minecraft" | "inbox";

/**
 * The page on show when nobody is on stage. `scene` numbers every showing this
 * visit, never reused, so the screen can key its change on it; `pos` is its
 * place in the tour, `name` what it is, `at` when the director last looked at it.
 */
export type Idle = { scene: number; since: number; pos: number; name: Page; at: number };

export type DirectorState = {
  spotlight: string | null;
  /** When the spotlight was chosen. */
  since: number;
  /** When the spotlight was last seen in the queue: it leaves the queue once answered. */
  lastSeen: number;
  /** Space: stay here, whatever happens elsewhere, until it is pressed again. */
  pinned: boolean;
  /** Something done by hand holds the screen until this moment, then the director takes over again. */
  manualUntil: number;
  /** How long that hold was for: how far round the ring has to run. */
  holdFor: number;
  /** With nobody on stage, the page on show: which one, and since when. */
  idle: Idle | null;
  /** How many pages have been shown this visit. */
  shown: number;
};

/** Seconds a spotlight stays at least, so the stage never flickers between two people. */
export const HOLD_MIN = 8;
/** Seconds an answered conversation stays up, so the reply that went out is seen. */
export const AFTER_DONE = 6;
/** Seconds after the last thing done by hand before Auto comes back. */
export const MANUAL_HOLD = 45;
/** Seconds the pointer moving holds the screen, when nothing has been pressed: nothing slides away from under a click. */
export const HOVER_HOLD = 8;
/** Seconds a message that has just arrived is news: long enough to see it land, then the tour again. */
export const FRESH = 12;
/** How recent an arrival nobody is answering still ranks high in the queue, in seconds. */
export const RECENT = 15 * 60;

/** Seconds each page stays up on the tour: a summary and the last few messages take longer to read than a number. */
export const PAGE_TIME: Record<Page, number> = {
  now: 10, people: 13, today: 10, accounts: 10, persona: 12, pictures: 12, inbox: 10,
  // Watching it play: it takes a few seconds to draw the world, and then it is the best thing on the screen.
  minecraft: 24,
};

/** The tabs, in their order along the top. The last two only while there is something to show in them. */
export const TABS: readonly Page[] = ["now", "people", "accounts", "today", "persona", "pictures", "minecraft", "inbox"];

/** The tabs there are right now: `have` says whether Minecraft has a world to show and whether anything needs you. */
export function tabsFor(have: { minecraft?: boolean; inbox?: boolean }): Page[] {
  return TABS.filter((p) => (p === "minecraft" ? have.minecraft : p === "inbox" ? have.inbox : true));
}

/**
 * The tour, from what there is to show. It starts at home, Now, and anything
 * that needs you comes next. Today is always there, since the numbers always
 * exist. A person comes round between the others: every other page while the
 * list is short, every third once it is long, so the rest still get their turn.
 */
export function tourFor(have: Partial<Record<Page, boolean>>): Page[] {
  const others = (["now", "inbox", "today", "accounts", "minecraft", "pictures", "persona"] as Page[])
    .filter((p) => p === "now" || p === "today" || have[p]);
  if (!have.people) return others;
  const every = others.length > 4 ? 2 : 1;
  const out: Page[] = [];
  others.forEach((p, i) => {
    out.push(p);
    if (i % every === every - 1) out.push("people");
  });
  return out;
}

export function initial(now: number): DirectorState {
  return { spotlight: null, since: now, lastSeen: now, pinned: false, manualUntil: 0, holdFor: 0, idle: null, shown: 0 };
}

/** A reply being written or typed out: the AI answering, the thing worth the stage. */
export const answering = (r: Row) => r.phase === "live" && (r.step === 2 || r.step >= 4);

/** How much a conversation deserves the stage right now. 0 or less: not at all. */
export function score(r: Row, now: number): number {
  if (r.phase === "off") return -1;
  if (r.phase === "live" && r.step >= 4) return 100;   // typing, or next to send
  if (r.phase === "live" && r.step === 2) return 95;   // being written
  // Only just arrived: news, for a few seconds. A reply that is only waiting,
  // for its timer (1) or its pace (3), is not; the tour plays meanwhile.
  const age = r.ts ? now - r.ts : Infinity;
  if (age < FRESH) return (r.phase === "live" ? 60 : 40) + 10 * (1 - Math.max(0, age) / FRESH);
  return 0;
}

/**
 * How far along a conversation is, for the order of the queue: after what is
 * on stage, the reply that fires soonest, then the newest arrival.
 */
function interest(r: Row, now: number): number {
  if (r.phase === "off") return -1;
  if (r.phase === "live") {
    if (r.step >= 4) return 100;
    if (r.step === 2) return 95;
    if (r.step === 3) return 80;
    const left = r.eta ? Math.max(0, r.eta - now) : 120;
    return 60 + 20 * (1 - Math.min(1, left / 120));
  }
  if (r.ts && now - r.ts < RECENT) return 30 + 10 * (1 - (now - r.ts) / RECENT);
  return 0;
}

/** The queue in the order the director ranks it. */
export function ranked<T extends Row>(rows: T[], now: number): T[] {
  return rows
    .filter((r) => r.phase !== "off")
    .slice()
    .sort((a, b) => score(b, now) - score(a, now) || interest(b, now) - interest(a, now) || (b.ts ?? 0) - (a.ts ?? 0));
}

export type QueueGroups<T extends Row> = {
  /** Being written or typed right now. */
  answering: T[];
  /** Will be answered by itself, the soonest first. */
  next: T[];
  /** Will not be, unless someone says so: what came in while it was off, what failed or was skipped. Newest first. */
  waiting: T[];
};

/** The queue as it is read down the left: who is being answered, who is next, and who is waiting on you. */
export function groupQueue<T extends Row>(rows: T[], now: number): QueueGroups<T> {
  const live = ranked(rows, now);
  return {
    answering: live.filter(answering),
    next: live.filter((r) => r.phase === "live" && !answering(r)),
    waiting: live.filter((r) => r.phase === "needs").sort((a, b) => (b.ts ?? 0) - (a.ts ?? 0)),
  };
}

function spotlightOn(state: DirectorState, key: string, now: number): DirectorState {
  return { ...state, spotlight: key, since: now, lastSeen: now, idle: null };
}

/** A page by its place in the tour, as a new showing: counted, and its clock started. */
function pageAt(state: DirectorState, pos: number, tour: readonly Page[], now: number): DirectorState {
  const len = Math.max(1, tour.length);
  const at = ((pos % len) + len) % len;
  const n = (state.shown ?? 0) + 1;
  return {
    ...state,
    spotlight: null,
    shown: n,
    idle: { scene: n, since: now, pos: at, name: tour[at] ?? "now", at: now },
  };
}

/**
 * Where the page on show sits in the tour as it is now. Usually where it
 * started; if the tour changed under it, wherever that page is now; and if it
 * has left the tour (the last friend request answered), `there` is false and
 * `at` is the place it had, which the page after it has moved up into.
 */
function placeOf(idle: Idle, tour: readonly Page[]): { at: number; there: boolean } {
  const len = Math.max(1, tour.length);
  if (tour[((idle.pos % len) + len) % len] === idle.name) return { at: idle.pos, there: true };
  const i = tour.indexOf(idle.name);
  return i >= 0 ? { at: i, there: true } : { at: idle.pos, there: false };
}

/** The page after the one on show, in the tour as it is now. */
function nextPos(idle: Idle, tour: readonly Page[]): number {
  const p = placeOf(idle, tour);
  return p.there ? p.at + 1 : p.at;
}

function idleOn(state: DirectorState, now: number, tour: readonly Page[]): DirectorState {
  const idle = state.idle;
  if (!idle) return pageAt(state, 0, tour, now);
  if (now - idle.since >= PAGE_TIME[idle.name]) return pageAt(state, nextPos(idle, tour), tour, now);
  return { ...state, spotlight: null, idle: { ...idle, at: now } };
}

/** Held: the page's clock stands still, so it has the same time left when let go. */
function frozen(state: DirectorState, now: number): DirectorState {
  const idle = state.idle;
  if (!idle) return state;
  return { ...state, idle: { ...idle, since: idle.since + Math.max(0, now - idle.at), at: now } };
}

/** One tick: the queue as it is now, and the state it leaves the screen in. */
export function tick(state: DirectorState, rows: Row[], now: number, tour: readonly Page[] = ["now", "today"]): DirectorState {
  const byKey = new Map(rows.map((r) => [r.key, r]));
  const cur = state.spotlight ? byKey.get(state.spotlight) : undefined;
  const s = cur ? { ...state, lastSeen: now } : state;
  const held = s.pinned || now < s.manualUntil;

  // Held by hand: stays put, even once it is answered.
  if (s.spotlight && held) return s;
  // A page held by hand stays too, with its clock stopped, even with someone being answered.
  if (!s.spotlight && s.idle && held) return frozen(s, now);

  const best = ranked(rows, now).find((r) => score(r, now) > 0);

  if (s.spotlight) {
    if (cur) {
      // never taken away while its reply is written or typed, nor straight after it arrived
      if (answering(cur)) return s;
      if (now - s.since < HOLD_MIN) return s;
      if (best && best.key !== cur.key && score(best, now) > score(cur, now) + 5) return spotlightOn(s, best.key, now);
      if (score(cur, now) > 0) return s;
    } else if (now - s.lastSeen < AFTER_DONE) {
      // answered: the reply that went out stays up a moment
      return s;
    }
  }
  if (best) return spotlightOn(s, best.key, now);
  return idleOn(s, now, tour);
}

/** Someone chosen by hand: them, on stage, held for a while. */
export function pick(state: DirectorState, key: string, now: number): DirectorState {
  return { ...spotlightOn(state, key, now), manualUntil: now + MANUAL_HOLD, holdFor: MANUAL_HOLD };
}

/**
 * A page chosen by hand: that one, now, even over a conversation, held for a
 * while before the director takes over again. Where it comes round more than
 * once (People), the first place it has in the tour; a page the tour does not
 * visit (nothing in it yet) still opens.
 */
export function showPage(state: DirectorState, name: Page, tour: readonly Page[], now: number): DirectorState {
  const pos = tour.indexOf(name);
  const s = pageAt(state, pos < 0 ? 0 : pos, pos < 0 ? [name] : tour, now);
  return { ...s, manualUntil: now + MANUAL_HOLD, holdFor: MANUAL_HOLD };
}

/** Back to what is happening: the hold is let go, and the next tick puts up the liveliest conversation. */
export function live(state: DirectorState): DirectorState {
  return { ...state, pinned: false, manualUntil: 0, holdFor: 0 };
}

/**
 * A sign of someone being there: nothing changes for a few seconds. Someone who
 * has already pressed something is driving, and stays driving for as long as
 * they keep doing anything at all.
 */
export function hold(state: DirectorState, now: number, secs = HOVER_HOLD): DirectorState {
  const len = now < state.manualUntil ? Math.max(secs, state.holdFor) : secs;
  const until = now + len;
  return until > state.manualUntil ? { ...state, manualUntil: until, holdFor: len } : state;
}

/** Space: stay here, or let go. Letting go hands the screen straight back to the director. */
export function togglePin(state: DirectorState): DirectorState {
  return { ...state, pinned: !state.pinned, manualUntil: 0, holdFor: 0 };
}

/** The page on show. */
export function pageOf(state: DirectorState): Page {
  return state.spotlight ? "now" : state.idle?.name ?? "now";
}

/** How far through its time the page on show is, 0 to 1. */
export function pageProgress(state: DirectorState, now: number): number {
  const idle = state.idle;
  if (!idle) return 0;
  return Math.max(0, Math.min(1, (now - idle.since) / PAGE_TIME[idle.name]));
}

export type AutoState =
  /** The director has the screen. */
  | { mode: "auto"; left: 0; of: 0 }
  /** Someone has: Auto comes back in `left` seconds of the `of` it was given. */
  | { mode: "held"; left: number; of: number }
  /** Space: staying here until it is pressed again. */
  | { mode: "pinned"; left: 0; of: 0 };

/** Who has the screen, for the button that says so. */
export function autoState(state: DirectorState, now: number): AutoState {
  if (state.pinned) return { mode: "pinned", left: 0, of: 0 };
  if (now < state.manualUntil) return { mode: "held", left: state.manualUntil - now, of: state.holdFor || MANUAL_HOLD };
  return { mode: "auto", left: 0, of: 0 };
}
