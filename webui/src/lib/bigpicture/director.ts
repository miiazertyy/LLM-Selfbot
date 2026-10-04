/**
 * Big Picture Mode's director: what the centre stage shows, and when it moves on.
 *
 * Nobody drives Big Picture; it follows the bots. This decides, from the live
 * queue and the clock alone, which conversation is in the spotlight:
 *
 *   1. one whose reply the AI is writing or typing out (the part worth watching),
 *   2. else one whose message has only just arrived, for long enough to see it land,
 *   3. else none: a reply that is only waiting, for its timer or its pace, is
 *      no reason to hold the stage, so the scenes play meanwhile and the queue
 *      down the left says who is waiting.
 *
 * A spotlight is never taken away while its reply is written or typed, and
 * never within a few seconds of arriving, so the stage does not flicker. When
 * its reply goes out and the row leaves the queue, it stays up a moment longer
 * so the sent message is seen. The rest of the time the stage cycles through
 * the scenes: the caller says which (cycleFor builds the list from what there
 * is to show), and each stays up for its own SCENE_TIME.
 *
 * The scene on show is fixed when it starts. The list can change under it,
 * because a friend request arrived or the summaries finished loading, and the
 * scene you are looking at does not swap for another mid-sentence: the new
 * list only decides what comes next.
 *
 * Anything done by hand holds the stage: a click on a card, a chapter picked,
 * the pointer moving over the stage, Space. A held idle scene's clock stops
 * while it is held, so letting go never lands on a scene already out of time.
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

/**
 * The idle scene on show. `scene` numbers every showing this visit, never
 * reused, so the stage can key its change on it; `pos` is its place in the
 * list, `name` what it is, `at` when the director last looked at it.
 */
export type Idle = { scene: number; since: number; pos: number; name: Scene; at: number };

export type DirectorState = {
  spotlight: string | null;
  /** When the spotlight was chosen. */
  since: number;
  /** When the spotlight was last seen in the queue: it leaves the queue once answered. */
  lastSeen: number;
  /** Space: hold the stage on the current conversation or scene, whatever happens elsewhere. */
  pinned: boolean;
  /** A click, an arrow key or the pointer moving holds the stage for a while too, then the director takes over again. */
  manualUntil: number;
  /** With nothing to show, the idle scene cycle: which one, and since when. */
  idle: Idle | null;
  /** How many scenes have been shown this visit. */
  shown: number;
};

/** Seconds a spotlight stays at least, so the stage never flickers between two people. */
export const HOLD_MIN = 8;
/** Seconds an answered conversation stays up, so the reply that went out is seen. */
export const AFTER_DONE = 6;
/** Seconds a click or an arrow key holds the stage before the director takes over again. */
export const MANUAL_HOLD = 25;
/** Seconds the pointer moving over the stage holds it, after the last movement. */
export const HOVER_HOLD = 8;
/** Seconds each idle scene stays up. */
export const IDLE_SCENE = 8;
/** Seconds a message that has just arrived is news: long enough to see it land, then the scenes again. */
export const FRESH = 12;
/** How recent an arrival nobody is answering still ranks high in the queue, in seconds. */
export const RECENT = 15 * 60;

export type Scene =
  | "recent" | "today" | "people" | "memory"
  | "accounts" | "pictures" | "friends" | "persona" | "health";
/** The idle scenes when there is nothing to show but the day's own. */
export const SCENES: readonly Scene[] = ["recent", "today", "people"];
/** With summaries of people to show (from Memory), one of them comes round every other scene, first. */
export const MEMORY_CYCLE: readonly Scene[] = ["memory", "today", "memory", "recent", "memory", "people"];
/** Seconds each scene stays up: a summary and the last few messages take longer to read than a number. */
export const SCENE_TIME: Record<Scene, number> = {
  recent: IDLE_SCENE, today: IDLE_SCENE, people: IDLE_SCENE, memory: 13,
  accounts: 10, pictures: 12, friends: 10, persona: 12, health: 9,
};

/**
 * Worth seeing before anything else when there is one: somebody asking to be a
 * friend, something broken. The rest take turns, a number between two pictures.
 */
const URGENT: readonly Scene[] = ["friends", "health"];
const ROUND: readonly Scene[] = ["today", "accounts", "recent", "pictures", "people", "persona"];

/**
 * The idle cycle from what there is to show. `today` is always there, since
 * the numbers always exist. A person from Memory comes round between the
 * others: every other scene while the list is short, every third once it is
 * long, so the rest still get their turn.
 */
export function cycleFor(have: Partial<Record<Scene, boolean>>): Scene[] {
  const others = [...URGENT, ...ROUND].filter((s) => s === "today" || have[s]);
  if (!have.memory) return others;
  const every = others.length > 4 ? 2 : 1;
  const out: Scene[] = [];
  others.forEach((s, i) => {
    if (i % every === 0) out.push("memory");
    out.push(s);
  });
  return out;
}

export function initial(now: number): DirectorState {
  return { spotlight: null, since: now, lastSeen: now, pinned: false, manualUntil: 0, idle: null, shown: 0 };
}

/** A reply being written or typed out: the AI answering, the thing worth the stage. */
const answering = (r: Row) => r.phase === "live" && (r.step === 2 || r.step >= 4);

/** How much a conversation deserves the stage right now. 0 or less: not at all. */
export function score(r: Row, now: number): number {
  if (r.phase === "off") return -1;
  if (r.phase === "live" && r.step >= 4) return 100;   // typing, or next to send
  if (r.phase === "live" && r.step === 2) return 95;   // being written
  // Only just arrived: news, for a few seconds. A reply that is only waiting,
  // for its timer (1) or its pace (3), is not; the scenes play meanwhile.
  const age = r.ts ? now - r.ts : Infinity;
  if (age < FRESH) return (r.phase === "live" ? 60 : 40) + 10 * (1 - Math.max(0, age) / FRESH);
  return 0;
}

/**
 * How far along a conversation is, for the order of the queue: after what is
 * on stage, the reply that fires soonest, then the newest arrival. The order
 * the rail is drawn in and ←/→ step through.
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

/** The queue in the order the director ranks it: the order ←/→ step through. */
export function ranked(rows: Row[], now: number): Row[] {
  return rows
    .filter((r) => r.phase !== "off")
    .slice()
    .sort((a, b) => score(b, now) - score(a, now) || interest(b, now) - interest(a, now) || (b.ts ?? 0) - (a.ts ?? 0));
}

function spotlightOn(state: DirectorState, key: string, now: number): DirectorState {
  return { ...state, spotlight: key, since: now, lastSeen: now, idle: null };
}

/** A scene by its place in the list, as a new showing: counted, and its clock started. */
function sceneAt(state: DirectorState, pos: number, cycle: readonly Scene[], now: number): DirectorState {
  const len = Math.max(1, cycle.length);
  const at = ((pos % len) + len) % len;
  const n = (state.shown ?? 0) + 1;
  return {
    ...state,
    spotlight: null,
    shown: n,
    idle: { scene: n, since: now, pos: at, name: cycle[at] ?? "today", at: now },
  };
}

/**
 * Where the scene on show sits in the list as it is now. Usually where it
 * started; if the list changed under it, wherever that scene is now; and if it
 * has left the list (the last friend request answered), `there` is false and
 * `at` is the place it had, which the scene after it has moved up into.
 */
function placeOf(idle: Idle, cycle: readonly Scene[]): { at: number; there: boolean } {
  const len = Math.max(1, cycle.length);
  if (cycle[((idle.pos % len) + len) % len] === idle.name) return { at: idle.pos, there: true };
  const i = cycle.indexOf(idle.name);
  return i >= 0 ? { at: i, there: true } : { at: idle.pos, there: false };
}

/** The scene after the one on show, in the list as it is now. */
function nextPos(idle: Idle, cycle: readonly Scene[]): number {
  const p = placeOf(idle, cycle);
  return p.there ? p.at + 1 : p.at;
}

function idleOn(state: DirectorState, now: number, cycle: readonly Scene[]): DirectorState {
  const idle = state.idle;
  if (!idle) return sceneAt(state, 0, cycle, now);
  if (now - idle.since >= SCENE_TIME[idle.name]) return sceneAt(state, nextPos(idle, cycle), cycle, now);
  const next = { ...idle, at: now };
  return { ...state, spotlight: null, idle: next };
}

/** Held: the scene's clock stands still, so it has the same time left when let go. */
function frozen(state: DirectorState, now: number): DirectorState {
  const idle = state.idle;
  if (!idle) return state;
  return { ...state, idle: { ...idle, since: idle.since + Math.max(0, now - idle.at), at: now } };
}

/** One tick: the queue as it is now, and the state it leaves the stage in. */
export function tick(state: DirectorState, rows: Row[], now: number, cycle: readonly Scene[] = SCENES): DirectorState {
  const byKey = new Map(rows.map((r) => [r.key, r]));
  const cur = state.spotlight ? byKey.get(state.spotlight) : undefined;
  let s = cur ? { ...state, lastSeen: now } : state;
  const held = s.pinned || now < s.manualUntil;

  // Held by hand: stays put, even once it is answered.
  if (s.spotlight && held) return s;
  // A scene held by hand stays too, with its clock stopped, even with someone waiting.
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
  return idleOn(s, now, cycle);
}

/** A click on a queue card: that one, held for a while. */
export function pick(state: DirectorState, key: string, now: number): DirectorState {
  return { ...spotlightOn(state, key, now), manualUntil: now + MANUAL_HOLD };
}

/** ←/→: the next or previous conversation in rank order, or the next idle scene when there are none. */
export function step(state: DirectorState, rows: Row[], dir: 1 | -1, now: number, cycle: readonly Scene[] = SCENES): DirectorState {
  const order = ranked(rows, now);
  if (!order.length) {
    const idle = state.idle;
    if (!idle) return sceneAt(state, 0, cycle, now);
    return sceneAt(state, dir === 1 ? nextPos(idle, cycle) : placeOf(idle, cycle).at - 1, cycle, now);
  }
  const at = order.findIndex((r) => r.key === state.spotlight);
  const next = order[(at + dir + order.length) % order.length] ?? order[0];
  return { ...spotlightOn(state, next.key, now), manualUntil: now + MANUAL_HOLD };
}

/**
 * A chapter picked by hand: that scene, now, even over a conversation, held for
 * a while before the director takes over again. Where a scene comes round more
 * than once (a memory), the first place it has in the list.
 */
export function showScene(state: DirectorState, name: Scene, cycle: readonly Scene[], now: number): DirectorState {
  const pos = cycle.indexOf(name);
  const s = sceneAt(state, pos < 0 ? 0 : pos, pos < 0 ? [name] : cycle, now);
  return { ...s, manualUntil: now + MANUAL_HOLD };
}

/** Back to what is happening: the hold is let go, and the next tick puts the liveliest conversation up. */
export function live(state: DirectorState): DirectorState {
  return { ...state, pinned: false, manualUntil: 0 };
}

/** The pointer moving over the stage, or a button pressed on it: nothing changes under it for a few seconds. */
export function hold(state: DirectorState, now: number, secs = HOVER_HOLD): DirectorState {
  const until = now + secs;
  return until > state.manualUntil ? { ...state, manualUntil: until } : state;
}

/** Space: hold or let go. Letting go hands the stage straight back to the director. */
export function togglePin(state: DirectorState): DirectorState {
  return { ...state, pinned: !state.pinned, manualUntil: 0 };
}

/** The idle scene on show, by name. */
export function sceneOf(state: DirectorState, _cycle: readonly Scene[] = SCENES): Scene | null {
  return state.idle?.name ?? null;
}

/** How far through its time the idle scene on show is, 0 to 1. */
export function sceneProgress(state: DirectorState, now: number): number {
  const idle = state.idle;
  if (!idle) return 0;
  return Math.max(0, Math.min(1, (now - idle.since) / SCENE_TIME[idle.name]));
}
