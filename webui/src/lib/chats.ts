/**
 * Conversations, kept warm outside the page that shows them.
 *
 * Asking an account who is waiting on a reply is not a database read: it is an
 * IPC round trip to the running bot, which sweeps its channels and answers
 * when it is ready. That takes long enough to notice.
 *
 * The Chats page is torn down and rebuilt on every navigation, so fetching on
 * mount meant staring at a skeleton every single time you opened the tab, even
 * though the answer from ten seconds ago was sitting right there. This module
 * holds the answers instead, so the page renders instantly from cache and the
 * refresh happens behind it.
 *
 * Every account is kept, not just the one on screen, so switching accounts is
 * instant too.
 */
import { get, writable } from "svelte/store";
import { mentionNames } from "./mentions";
import { api } from "./api";
import { begin } from "./busy";
import { subscribeEvents } from "./logsocket";

export type ChatUser = {
  id: string;
  name: string;
  snippet: string;
  count: number;
  ts?: number;
  /** From the local profile cache, filled in by the server. May be empty. */
  avatar?: string;
  username?: string;
  /** Unix seconds when the bot's batch timer fires for this one, if running. */
  reply_at?: number | null;
  /**
   * Where the bot is with this person's latest message, reported by the
   * runner: waiting (eta), writing, cooldown (eta), queued, sending, skipped
   * (reason) or failed (reason). Absent when the bot has not picked it up.
   */
  state?: { state: string; since: number; eta?: number | null; reason?: string } | null;
  /** The bot is turned off for this person (they are on the ignore list). */
  ignored?: boolean;
  /**
   * A server conversation rather than a DM: the row is the channel ("ch<id>"),
   * `author_id` who is asking in it, `where` "#channel · Server".
   */
  kind?: "server";
  channel_id?: string;
  author_id?: string;
  where?: string;
  /** Their latest message in full, and what came with it. */
  text?: string;
  mid?: string;
  attachments?: { url: string; name: string; type?: string; w?: number | null; h?: number | null; size?: number }[];
  /** A Lottie sticker (`format` "lottie") has no url; the panel plays it from its id. */
  stickers?: { name: string; url?: string; id?: string; format?: string }[];
  embeds?: { title?: string; url?: string; image?: string; provider?: string }[];
};

/** A live update pushed by a runner (see emit_chat_event in the runner). */
export type ChatEvent = { t: string; target: string; uid?: string; [k: string]: any };

export type ChatEntry = {
  users: ChatUser[];
  /** When this answer arrived, in ms. 0 means we have never had one. */
  fetched: number;
  loading: boolean;
  error: string;
  /** Why nothing has been sent yet, straight from the runner. */
  paused?: boolean;
  /** Unix seconds when the next reply may go out, 0 when free to send. */
  cooldownUntil?: number;
  cooldownRange?: [number, number] | null;
};

export type ChatAccount = {
  id: string;
  platform: string;
  account: number | null;
  /** The account's own Discord id. */
  user_id?: string;
  username?: string;
  display_name?: string;
  avatar?: string;
  state?: string;
};

const EMPTY: ChatEntry = { users: [], fetched: 0, loading: false, error: "" };

export const chatCache = writable<Record<string, ChatEntry>>({});
export const chatAccounts = writable<ChatAccount[]>([]);

/**
 * An account another page asked to be shown, e.g. "Its chats" on an account
 * card. Chats picks it up when it opens and clears it.
 */
export const chatsFocus = writable<string>("");

/**
 * Set while a reply is being sent.
 *
 * A refresh landing mid send reorders the list under the buttons, so the
 * background pass holds off rather than yanking rows around while someone is
 * clicking them.
 */
export const chatBusy = writable(false);

/**
 * Replies in flight, by user id, and whether a Reply to all is running.
 *
 * A reply takes up to two minutes: the bot reads, thinks, types and sends. The
 * spinner used to be component state, so leaving the tab and coming back lost
 * it, and the page looked idle while the work was still going. Keeping it here
 * means the button is still spinning when you return, and the result still
 * lands whichever page you are on.
 */
export const replying = writable<Record<string, boolean>>({});
export const replyingAll = writable<Record<string, boolean>>({});
/** How far a "reply to all" has got, so the button can say so; `stopping` once Stop is pressed, until it has. */
export const replyAllProgress =
  writable<Record<string, { done: number; total: number; stopping?: boolean }>>({});

/**
 * A Reply to all as it runs, by account: whether Stop was pressed, and what it
 * asked for that may still go out, which Stop takes back. That is the reply
 * being written, one the account is still writing after the panel stopped
 * waiting for it, and on Snapchat the answers written and waiting their turn
 * to be sent (Snapchat writes them quickly and sends them one by one after).
 */
type ReplyRun = { stop: Promise<void> | null; open: Set<string>; takenBack: Set<string> };
const replyRuns = new Map<string, ReplyRun>();

/** One request per target at a time, however many callers ask for it. */
const inflight = new Map<string, Promise<void>>();

function mark(store: typeof replying, key: string, on: boolean) {
  store.update((m) => {
    const next = { ...m };
    if (on) next[key] = true;
    else delete next[key];
    return next;
  });
}

/**
 * Send one reply, tracked centrally so the work outlives the page.
 *
 * Returns the runner's answer. `dropped` means the conversation could never be
 * answered and has been taken off the waiting list, so it should not come back.
 */
export async function sendReply(target: string, userId: string) {
  if (get(replying)[userId]) return null;
  mark(replying, userId, true);
  chatBusy.set(true);
  // A reply can take a couple of minutes with the human pauses in it.
  const done = begin("chats", "Sending a reply");
  try {
    const result = await api.reply(userId, target);
    forget(target, userId);
    return result;
  } finally {
    done();
    mark(replying, userId, false);
    if (!Object.keys(get(replying)).length && !Object.keys(get(replyingAll)).length) {
      chatBusy.set(false);
    }
    refreshChats(target, { force: true });
  }
}

/**
 * Answer everyone waiting, one at a time, clearing each row as it is done.
 *
 * This used to be a single /api/chats/reply-all call: one request that took as
 * long as every reply put together - minutes, with the deliberate human pauses
 * between sends - showing a spinner the whole time and then emptying the list
 * in one go at the very end. There was no way to tell it apart from a hang.
 *
 * The runner finds who to answer exactly the way reply_check does, so the list
 * on screen is already the same set. Walking it here costs nothing extra and
 * means a row disappears the moment that person has been answered.
 *
 * Only a reply that actually went out removes a row. A failure that can never
 * succeed is reported as `dropped` and comes off too, since it will not be back
 * on the next refresh; anything else stays, so what is left is really what is
 * left. Calling it again while it runs is Stop (stopReplyAll).
 */
export async function sendReplyAll(target: string) {
  if (replyRuns.has(target)) {
    await stopReplyAll(target);
    return null;
  }
  const queue = entry(target).users.map((u) => u.id);
  const run: ReplyRun = { stop: null, open: new Set(), takenBack: new Set() };
  replyRuns.set(target, run);
  mark(replyingAll, target, true);
  replyAllProgress.update((p) => ({ ...p, [target]: { done: 0, total: queue.length } }));
  chatBusy.set(true);
  const results: any[] = [];
  // The longest thing in the app: every reply waits out its human pause, so
  // it runs for minutes - and it is exactly what people leave the tab during.
  const job = begin("chats", `Replying to ${queue.length} ${queue.length === 1 ? "person" : "people"}`);
  job.progress(0, queue.length);
  try {
    for (const id of queue) {
      if (run.stop) break;
      mark(replying, id, true);
      run.open.add(id);
      try {
        const r = await api.reply(id, target);
        results.push({ id, ...(r || {}) });
        // Sent, refused or cancelled, nothing of it is left to take back; written and
        // waiting its turn to be sent (Snapchat's `queued`), it is until it goes.
        if (!(r?.success && r?.queued)) run.open.delete(id);
        if (r?.success || r?.dropped) forget(target, id);
      } catch (e: any) {
        // The panel stopped waiting (after two minutes), not the account: it may still
        // be writing it, so it stays one for Stop to take back.
        results.push({ id, success: false, reason: e?.message || "failed" });
      } finally {
        mark(replying, id, false);
        replyAllProgress.update((p) => ({
          ...p,
          [target]: { done: results.length, total: queue.length },
        }));
        // One step per person answered, so eight people move it eight times.
        job.progress(results.length, queue.length);
      }
    }
    // Stopped: once the account has answered every cancel, what was written and queued
    // and taken back before it went is known, and it was not answered after all.
    if (run.stop) await run.stop;
    for (const r of results) {
      if (run.takenBack.has(String(r.id))) Object.assign(r, { success: false, cancelled: true });
    }
    return { total: results.length, of: queue.length, results, stopped: !!run.stop };
  } finally {
    replyRuns.delete(target);
    job();
    mark(replyingAll, target, false);
    replyAllProgress.update((p) => {
      const next = { ...p };
      delete next[target];
      return next;
    });
    if (!Object.keys(get(replying)).length && !Object.keys(get(replyingAll)).length) {
      chatBusy.set(false);
    }
    refreshChats(target, { force: true });
  }
}

/**
 * Stop a Reply to all: nobody else is asked for, and what it asked for that
 * has not gone out is cancelled, the reply being written included. It used to
 * stop only before the next person, so the reply being written still went
 * out, and on Snapchat so did every answer already written and waiting to be
 * sent, which could be everyone. The run itself ends as the reply in flight
 * comes back cancelled, and says what it did.
 */
export function stopReplyAll(target: string): Promise<void> {
  const run = replyRuns.get(target);
  if (!run) return Promise.resolve();
  if (run.stop) return run.stop;
  replyAllProgress.update((p) => (p[target] ? { ...p, [target]: { ...p[target], stopping: true } } : p));
  run.stop = Promise.all([...run.open].map(async (id) => {
    try {
      const r = await cancelReply(target, id);
      if (r?.stopped) run.takenBack.add(id);
    } catch {
      /* the account did not answer in time: nothing more can be done from here */
    }
  })).then(() => undefined);
  return run.stop;
}

export function entry(target: string): ChatEntry {
  return get(chatCache)[target] ?? EMPTY;
}

function patch(target: string, changes: Partial<ChatEntry>) {
  chatCache.update((c) => ({ ...c, [target]: { ...(c[target] ?? EMPTY), ...changes } }));
}

/**
 * Fetch one account's waiting conversations into the cache.
 *
 * `maxAge` lets a caller say "only if it is stale", which is what makes
 * opening the tab free when the background pass has already been through.
 */
export function refreshChats(
  target: string,
  { maxAge = 0, force = false, quiet = false }:
    { maxAge?: number; force?: boolean; quiet?: boolean } = {},
): Promise<void> {
  if (!target) return Promise.resolve();
  if (!force && get(chatBusy)) return Promise.resolve();

  const existing = inflight.get(target);
  if (existing) return existing;

  const current = entry(target);
  if (!force && maxAge > 0 && current.fetched && Date.now() - current.fetched < maxAge) {
    return Promise.resolve();
  }

  patch(target, { loading: true });
  // The prefetch loop passes quiet: it runs every minute from app start, and a
  // spinner that comes back every minute on its own means nothing.
  const done = quiet ? null : begin("chats", "Loading chats");
  const started = Date.now();
  const run = (async () => {
    try {
      const data = await api.chats(target, force);
      // Events that arrived while this was in flight are newer than the
      // answer; put them back over it, or a reply sent a second ago reappears.
      let users: ChatUser[] = data.users || [];
      for (const r of recent.get(target) ?? []) {
        if (r.at >= started) users = applyToUsers(users, r.evt);
      }
      patch(target, {
        users,
        fetched: Date.now(),
        loading: false,
        error: "",
        paused: !!data.paused,
        cooldownUntil: data.cooldown_until || 0,
        cooldownRange: data.cooldown_range ?? null,
      });
    } catch (e: any) {
      // A stopped or busy account answers 504. That is not an error worth
      // shouting about, and the last known list is still the best thing to
      // show, so it is kept.
      patch(target, {
        loading: false,
        error: e?.status === 504 ? "" : e?.message || "Could not load",
        fetched: e?.status === 504 ? Date.now() : current.fetched,
        users: e?.status === 504 ? [] : current.users,
      });
    } finally {
      inflight.delete(target);
      done?.();
    }
  })();

  inflight.set(target, run);
  return run;
}

/** The last few events per account, so a refresh in flight can replay them. */
const recent = new Map<string, { at: number; evt: ChatEvent }[]>();

const MSG_KEYS = ["text", "mid", "attachments", "stickers", "embeds"] as const;

/**
 * One event applied to a waiting list, returning a new list. Mirrors
 * apply_event in chat_routes.py, so the page and the server's cache agree.
 */
export function applyToUsers(users: ChatUser[], evt: ChatEvent): ChatUser[] {
  const uid = String(evt.uid ?? "");
  const i = users.findIndex((u) => String(u.id) === uid);
  switch (evt.t) {
    case "done":
      return i >= 0 ? users.filter((_, j) => j !== i) : users;
    case "state":
      if (i < 0) return users;
      return users.map((u, j) => (j === i ? { ...u, state: evt.state ?? null } : u));
    case "ignored":
      // A person's server rows too: the bot is off for them wherever they ask.
      if (!users.some((u) => String(u.id) === uid || u.author_id === uid)) return users;
      return users.map((u) => (String(u.id) === uid || u.author_id === uid ? { ...u, ignored: !!evt.ignored } : u));
    case "payload": {
      // The whole message, fetched for a row that only had text. Same message, same count.
      if (i < 0) return users;
      const fresh: Partial<ChatUser> = {};
      for (const k of MSG_KEYS) if (k in evt) (fresh as any)[k] = evt[k];
      return users.map((u, j) => (j === i ? { ...u, ...fresh } : u));
    }
    case "msg": {
      const fresh: Partial<ChatUser> = { attachments: [], stickers: [], embeds: [] };
      for (const k of MSG_KEYS) if (k in evt) (fresh as any)[k] = evt[k];
      fresh.snippet = evt.snippet ?? "";
      fresh.ts = evt.ts || 0;
      fresh.ignored = !!evt.ignored;
      if (evt.kind === "server") {
        // Someone else may be the one asking in that channel now.
        for (const k of ["kind", "channel_id", "author_id", "where", "name", "avatar"]) if (k in evt) (fresh as any)[k] = evt[k];
      }
      if (i >= 0) {
        const old = users[i];
        // The same message again (a sweep that already had it) is not a second one.
        const again = !!evt.mid && old.mid === evt.mid;
        const row: ChatUser = { ...old, ...fresh, count: (old.count || 0) + (again ? 0 : 1) };
        // A new message is a new thing to answer.
        if (!again && row.state && ["skipped", "failed"].includes(row.state.state)) row.state = null;
        return users.map((u, j) => (j === i ? row : u));
      }
      return [
        ...users,
        {
          id: uid, name: evt.name || uid, username: evt.username || "", avatar: evt.avatar || "",
          count: 1, reply_at: null, snippet: "", ...fresh,
        } as ChatUser,
      ];
    }
  }
  return users;
}

// ── Conversations ────────────────────────────────────────────────────────────

/** One message in the chat view: theirs, or the account's own. */
export type ConvMessage = {
  mine: boolean;
  ts: number;
  mid?: string;
  /** Typed in the Chats tab and not confirmed yet, or refused. */
  pending?: boolean;
  failed?: boolean;
  /** Who wrote it, in a server channel, where that is not always the person the row is for. */
  author?: { id: string; name: string; avatar: string };
  text?: string;
  attachments?: ChatUser["attachments"];
  stickers?: ChatUser["stickers"];
  embeds?: ChatUser["embeds"];
  /** Reactions on the message. `url` is set for a custom emoji, `name` is the character for a normal one. */
  reactions?: { name: string; url?: string; count: number; mine?: boolean }[];
  /** When it was deleted on Discord: it is kept (app/utils/chatlog.py) and shown with a bin. */
  deleted?: number;
  /** When it was last edited. */
  edited?: number;
  /** Snapchat shows the day a message was sent, not the time: `ts` is then only good for the day. */
  approx?: boolean;
  /** What a Snapchat message was when it was not words: "snap", "image", "voice message", "call" ... */
  kind?: string;
};
/**
 * `done`: asked for earlier messages and there were none, so there is no asking again. `start`: and that is
 * because the very first message is already shown.
 */
export type Conversation = { messages: ConvMessage[]; loading: boolean; error: string; at: number; done?: boolean; start?: boolean };

/**
 * The recent messages with each person, both sides, by "target:user".
 *
 * Read from Discord when a conversation is opened (one history fetch, on the
 * manual allowance) and then kept live: a new message from them and the
 * account's own reply both arrive as events and are appended, so an open chat
 * view fills in as it happens.
 */
export const conversations = writable<Record<string, Conversation>>({});
export const convKey = (target: string, uid: string) => `${target}:${uid}`;

export async function loadConversation(target: string, uid: string, force = false) {
  if (!target || !uid) return;
  const k = convKey(target, uid);
  const cur = get(conversations)[k];
  if (cur?.loading) return;
  if (cur && !force && !cur.error && Date.now() - cur.at < 3 * 60 * 1000) return;
  conversations.update((c) => ({ ...c, [k]: { ...(cur ?? {}), messages: cur?.messages ?? [], error: "", loading: true, at: cur?.at ?? 0 } }));
  try {
    const r = await api.chatsHistory(uid, target, 25);
    const fresh: ConvMessage[] = r.messages || [];
    // Read again over a conversation scrolled back through: what came before the fresh ones stays.
    const now = get(conversations)[k];
    const firstMid = fresh.find((m) => m.mid)?.mid;
    const at = firstMid && now ? now.messages.findIndex((m) => m.mid === firstMid) : -1;
    const kept = at > 0 ? now!.messages.slice(0, at) : [];
    conversations.update((c) => ({
      ...c, [k]: { messages: [...kept, ...fresh], error: "", loading: false, at: Date.now(),
                   done: kept.length ? now?.done : false, start: kept.length ? now?.start : false },
    }));
  } catch (e: any) {
    conversations.update((c) => ({
      ...c, [k]: { messages: cur?.messages ?? [], error: e?.message || "Could not read it", loading: false, at: Date.now() },
    }));
  }
}

/** The most messages one open conversation holds: scrolling back adds to it, and nothing new pushes those out. */
const KEEP_DRAWN = 1500;

/**
 * Earlier messages, for scrolling back, before the first one shown: from
 * Discord while the account runs (only it has all of them, and the deleted
 * ones kept here are put back in), from what is kept when it does not, and
 * always for Snapchat. Once there are none before, it stops asking.
 */
export async function loadEarlier(target: string, uid: string) {
  const k = convKey(target, uid);
  const cur = get(conversations)[k];
  if (!cur || cur.loading || cur.done || cur.messages.length < 5) return;
  const first = cur.messages.find((m) => m.mid && !String(m.mid).startsWith("local-"));
  if (!first?.mid) return;
  conversations.update((c) => ({ ...c, [k]: { ...cur, loading: true } }));
  try {
    const r = await api.chatsWindow(uid, target, "older", String(first.mid), 50);
    const now = get(conversations)[k] ?? cur;
    const seen = new Set(now.messages.map((m) => m.mid).filter(Boolean));
    const older: ConvMessage[] = (r.messages || []).filter((m: ConvMessage) => !m.mid || !seen.has(m.mid));
    conversations.update((c) => ({
      ...c, [k]: { ...now, messages: [...older, ...now.messages].slice(-KEEP_DRAWN), loading: false,
                   done: !r.more || !older.length, start: !r.more },
    }));
  } catch {
    conversations.update((c) => ({ ...c, [k]: { ...(get(conversations)[k] ?? cur), loading: false, done: true } }));
  }
}

/**
 * Put a stretch read from elsewhere (a jump back that has come all the way
 * down to now) in front of an open conversation, as one: the messages it does
 * not have yet, in order.
 */
export function joinConversation(target: string, uid: string, before: ConvMessage[]) {
  const k = convKey(target, uid);
  conversations.update((c) => {
    const cur = c[k];
    if (!cur) return c;
    const have = new Set(cur.messages.map((m) => m.mid).filter(Boolean));
    const add = before.filter((m) => !m.mid || !have.has(m.mid));
    const messages = [...add, ...cur.messages].sort((a, b) => a.ts - b.ts).slice(-KEEP_DRAWN);
    return { ...c, [k]: { ...cur, messages, done: false } };
  });
}

// ── Drafts ───────────────────────────────────────────────────────────────────

/**
 * What you were typing to each person and had not sent, by "target:user":
 * leaving the tab, opening someone else, closing the app, it is all still
 * there when you come back, the way a messaging app keeps a draft. Kept on
 * the server as well as in the browser (the desktop window forgets its
 * storage on exit), written a moment after you stop typing rather than on
 * every key.
 */
const DRAFTS_KEY = "chatDrafts";
const MAX_DRAFT = 4000;
const MAX_DRAFTS = 80;

function readDrafts(): Record<string, string> {
  try {
    const v = JSON.parse(localStorage.getItem(DRAFTS_KEY) || "{}");
    return v && typeof v === "object" && !Array.isArray(v) ? v : {};
  } catch {
    return {};
  }
}

export const drafts = writable<Record<string, string>>(typeof localStorage === "undefined" ? {} : readDrafts());
let draftTimer: ReturnType<typeof setTimeout> | null = null;
let draftsRead: Promise<void> | null = null;
let draftsReady = false;

function pushDrafts() {
  fetch("/api/prefs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ prefs: { [DRAFTS_KEY]: get(drafts) } }),
  }).catch(() => {});
}

function keepDrafts(all: Record<string, string>) {
  try {
    localStorage.setItem(DRAFTS_KEY, JSON.stringify(all));
  } catch {
    /* the server copy still has it */
  }
  if (draftTimer) clearTimeout(draftTimer);
  draftTimer = setTimeout(() => {
    draftTimer = null;
    // Not before the server's copy has been read, or an empty browser would wipe it.
    if (draftsReady) pushDrafts();
  }, 700);
}

/** Set (or, with nothing left in it, drop) the draft for one conversation. */
export function setDraft(k: string, text: string) {
  const t = (text ?? "").slice(0, MAX_DRAFT);
  const cur = get(drafts);
  if ((cur[k] ?? "") === t || (!t.trim() && !(k in cur))) return;
  const next = { ...cur };
  if (t.trim()) {
    delete next[k];
    next[k] = t;                 // the newest last, so the oldest go first when there are too many
    const keys = Object.keys(next);
    for (const old of keys.slice(0, Math.max(0, keys.length - MAX_DRAFTS))) delete next[old];
  } else {
    delete next[k];
  }
  drafts.set(next);
  keepDrafts(next);
}

/**
 * The server's drafts, read once per session, before anything is typed: they
 * fill in what the browser lost (the desktop window wipes its storage on
 * exit). Anything only the browser had goes back up.
 */
export function loadDrafts(): Promise<void> {
  draftsRead ??= (async () => {
    try {
      const data = await fetch("/api/prefs").then((r) => r.json());
      const saved = data?.prefs?.[DRAFTS_KEY];
      const server = saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
      const merged = { ...server, ...get(drafts) };
      drafts.set(merged);
      try {
        localStorage.setItem(DRAFTS_KEY, JSON.stringify(merged));
      } catch {
        /* fine */
      }
      draftsReady = true;
      if (JSON.stringify(merged) !== JSON.stringify(server)) pushDrafts();
    } catch {
      draftsReady = true;
    }
  })();
  return draftsRead;
}

/**
 * Pictures and files added to a message and not sent yet, by "target:user".
 * Kept while the app is open, so leaving the tab does not lose them; not
 * across a restart, since they are the files themselves.
 */
export type StagedFile = { name: string; data: string; preview: string; type: string; size: number };
export const stagedFiles = writable<Record<string, StagedFile[]>>({});

/**
 * A message typed in the Chats tab, sent as the account.
 *
 * It shows at once, as sending. The account's own "sent" event and the
 * answer race each other; whichever comes second finds the other already
 * there, so the message is never shown twice. A refusal leaves it marked, for
 * the page to offer the text back.
 */
export async function sendOwnMessage(
  target: string,
  uid: string,
  text: string,
  files: { name: string; data: string; preview?: string; type?: string }[] = [],
): Promise<{ ok: boolean; dropped?: boolean; error?: string }> {
  const k = convKey(target, uid);
  const local = `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  conversations.update((c) => {
    const cur = c[k] ?? { messages: [], loading: false, error: "", at: Date.now() };
    const mine: ConvMessage = {
      mine: true, ts: Date.now() / 1000, mid: local, text, pending: true,
      // Shown from the local copy while it uploads, so a pasted picture appears
      // in the conversation straight away rather than after the round trip.
      attachments: files.map((f) => ({ url: f.preview ?? "", name: f.name, type: f.type ?? "image/png" })),
    };
    return { ...c, [k]: { ...cur, messages: [...cur.messages, mine].slice(-KEEP_DRAWN) } };
  });
  try {
    const r: any = await api.chatsSend(uid, text, target, files.map((f) => ({ name: f.name, data: f.data })));
    conversations.update((c) => {
      const cur = c[k];
      if (!cur) return c;
      const arrived = !!r?.mid && cur.messages.some((m) => m.mid === r.mid);
      const messages = arrived
        ? cur.messages.filter((m) => m.mid !== local)
        // The account's own copy carries the real links; the local preview was a
        // blob URL, which stops working the moment it is released.
        : cur.messages.map((m) => (m.mid === local
            ? { ...m, mid: r?.mid || local, ts: r?.ts || m.ts, pending: false,
                ...(r?.attachments ? { attachments: r.attachments } : {}) }
            : m));
      return { ...c, [k]: { ...cur, messages } };
    });
    return { ok: true, dropped: !!r?.dropped_reply };
  } catch (e: any) {
    conversations.update((c) => {
      const cur = c[k];
      if (!cur) return c;
      return { ...c, [k]: { ...cur, messages: cur.messages.map((m) => (m.mid === local ? { ...m, pending: false, failed: true } : m)) } };
    });
    return { ok: false, error: e?.message || "Could not send it" };
  }
}

/**
 * Who is typing to an account right now, by "target:user": Discord says so
 * every few seconds while someone types, and it lapses on its own after about
 * ten. Their message arriving ends it at once. The Chats tab and Big Picture
 * draw the same dots for them as for the bot.
 */
export const typingNow = writable<Record<string, true>>({});
const typingTimers = new Map<string, ReturnType<typeof setTimeout>>();
function setTyping(k: string, on: boolean) {
  clearTimeout(typingTimers.get(k));
  typingTimers.delete(k);
  if (on) typingTimers.set(k, setTimeout(() => setTyping(k, false), 10000));
  typingNow.update((t) => {
    if (on === !!t[k]) return t;
    const next = { ...t };
    if (on) next[k] = true;
    else delete next[k];
    return next;
  });
}

// ── Reactions ────────────────────────────────────────────────────────────────

export type Reaction = NonNullable<ConvMessage["reactions"]>[number];

/** Snapchat's reactions, in the order its own picker shows them: the only ones it has, one per person on a message. */
export const SNAP_REACTIONS = ["❤️", "😂", "🔥", "👍", "👎", "😰", "🤯", "❓"];
/** Offered first on Discord, before the whole picker. */
export const DISCORD_REACTIONS = ["❤️", "😂", "😭", "💀", "🔥", "👍", "😮", "🙏"];

/** What is sent for a reaction: the character, or a custom Discord emoji the way Discord writes one. */
export function reactionCode(r: { name: string; url?: string }): string {
  const m = r.url?.match(/\/emojis\/(\d+)\.(gif|webp|png)/);
  return m ? `<${m[2] === "gif" ? "a" : ""}:${r.name || "emoji"}:${m[1]}>` : r.name;
}

/**
 * A message's reactions after the account adds one, or takes its own back. On
 * Snapchat a person has one reaction on a message (`onlyOne`), so a new one
 * replaces theirs, as Snapchat itself does.
 */
export function withReaction(list: Reaction[], emoji: { name: string; url?: string }, add: boolean, onlyOne: boolean): Reaction[] {
  const key = (r: { name: string; url?: string }) => r.url || r.name;
  let out = (list ?? []).map((r) => ({ ...r }));
  if (add && onlyOne) out = out.map((r) => (r.mine && key(r) !== key(emoji) ? { ...r, count: r.count - 1, mine: false } : r));
  const hit = out.find((r) => key(r) === key(emoji));
  if (add && hit && !hit.mine) {
    hit.count += 1;
    hit.mine = true;
  } else if (add && !hit) {
    out.push({ name: emoji.name, ...(emoji.url ? { url: emoji.url } : {}), count: 1, mine: true });
  } else if (!add && hit?.mine) {
    hit.count -= 1;
    hit.mine = false;
  }
  return out.filter((r) => r.count > 0);
}

function setReactions(k: string, mid: string, reactions: Reaction[]) {
  conversations.update((c) => {
    const cur = c[k];
    if (!cur) return c;
    return { ...c, [k]: { ...cur, messages: cur.messages.map((m) => (String(m.mid) === mid ? { ...m, reactions } : m)) } };
  });
}

/**
 * React to a message as the account (`add`), or take its reaction back. It
 * shows at once, and goes back as it was if the platform says no. Discord's
 * answer arrives a moment later as its own event, like anyone's reaction;
 * Snapchat's runner reads the message again and says what is on it now.
 */
export async function reactTo(target: string, uid: string, mid: string, emoji: { name: string; url?: string },
                              add: boolean, snap: boolean): Promise<void> {
  const k = convKey(target, uid);
  const before = get(conversations)[k]?.messages.find((m) => String(m.mid) === mid)?.reactions ?? [];
  setReactions(k, mid, withReaction(before, emoji, add, snap));
  try {
    const r = await api.chatsReact(uid, mid, reactionCode(emoji), !add, target);
    if (Array.isArray(r?.reactions)) setReactions(k, mid, r.reactions);
  } catch (e) {
    setReactions(k, mid, before);
    throw e;
  }
}

/** A message that just arrived, into the open conversation it belongs to; one deleted or edited, changed there. */
function appendToConversation(target: string, evt: ChatEvent) {
  const k = convKey(target, String(evt.uid ?? ""));
  if (evt.t === "typing") return setTyping(k, true);
  if (evt.t === "msg") setTyping(k, false);
  const cur = get(conversations)[k];
  if (!cur) return;                               // never opened: nothing to keep live
  if (evt.t === "reactions") {
    // Someone reacted, or took one back (the account too): what is on the message now.
    if (evt.mid && cur.messages.some((m) => String(m.mid) === String(evt.mid))) {
      setReactions(k, String(evt.mid), Array.isArray(evt.reactions) ? evt.reactions : []);
    }
    return;
  }
  if (evt.t === "deleted" || evt.t === "edited") {
    if (!evt.mid || !cur.messages.some((m) => m.mid === evt.mid)) return;
    const change: Partial<ConvMessage> = evt.t === "deleted"
      ? { deleted: evt.at || Date.now() / 1000 }
      : { edited: evt.at || Date.now() / 1000, text: evt.text ?? "" };
    conversations.update((c) => ({
      ...c, [k]: { ...cur, messages: cur.messages.map((m) => (m.mid === evt.mid ? { ...m, ...change } : m)) },
    }));
    return;
  }
  if (evt.t !== "msg" && evt.t !== "sent") return;
  if (evt.mid && cur.messages.some((m) => m.mid === evt.mid)) return;
  const msg: ConvMessage = { mine: evt.t === "sent", ts: evt.ts || Date.now() / 1000 };
  for (const f of MSG_KEYS) if (f in evt) (msg as any)[f] = evt[f];
  conversations.update((c) => ({ ...c, [k]: { ...cur, messages: [...cur.messages, msg].slice(-KEEP_DRAWN) } }));
}

function applyEvent(evt: ChatEvent) {
  const target = evt.target;
  if (!target) return;
  const log = recent.get(target) ?? [];
  log.push({ at: Date.now(), evt });
  if (log.length > 100) log.splice(0, log.length - 100);
  recent.set(target, log);
  appendToConversation(target, evt);
  const current = get(chatCache)[target];
  // Never fetched: nothing to patch, and the first fetch brings it all anyway.
  if (!current || !current.fetched) return;
  if (evt.t === "meta") {
    patch(target, { paused: !!evt.paused, cooldownUntil: evt.cooldown_until || 0 });
    return;
  }
  const users = applyToUsers(current.users, evt);
  if (users !== current.users) patch(target, { users });
}

/**
 * Keep the cached lists live: every change the runners push is applied the
 * moment it arrives, whatever page is open. When the socket (re)connects,
 * whatever happened while it was down is fetched once.
 */
export function startChatLive(): () => void {
  return subscribeEvents("chat", (evt) => {
    if (evt) {
      applyEvent(evt as ChatEvent);
      return;
    }
    for (const t of Object.keys(get(chatCache))) refreshChats(t, { quiet: true });
  });
}

/** Fetch someone's last message in full, for a row that only says "[attachment]". */
export async function loadMessage(target: string, userId: string) {
  const r = await api.chatsMessage(userId, target);
  applyEvent({ t: "payload", target, uid: userId, ...r });
  return r;
}

/** Stop the reply the bot has lined up for someone. They stay on the list. */
export async function cancelReply(target: string, userId: string) {
  const res = await api.chatsCancel(userId, target);
  // The runner pushes the new state too; this is for a socket that is down.
  applyEvent({ t: "state", target, uid: userId,
               state: { state: "skipped", since: Date.now() / 1000, reason: "you cancelled the reply" } });
  return res;
}

/** Ignore someone, or stop ignoring them. */
export async function setIgnored(target: string, userId: string, ignored: boolean) {
  await api.chatsIgnoreSet(userId, ignored, target);
  applyEvent({ t: "ignored", target, uid: userId, ignored });
}

/** Turn the bot off (or back on) for one person. Returns whether it is now off. */
export async function toggleIgnore(target: string, userId: string): Promise<boolean> {
  const res = await api.chatsIgnore(userId, target);
  applyEvent({ t: "ignored", target, uid: userId, ignored: !!res?.ignored });
  return !!res?.ignored;
}

/** Drop someone from the cached list, after they have been replied to. */
export function forget(target: string, userId: string) {
  const current = entry(target);
  patch(target, { users: current.users.filter((u) => u.id !== userId) });
}

export async function loadChatAccounts(): Promise<ChatAccount[]> {
  const data = await api.accounts();
  const list = (data.accounts || []).filter((a: ChatAccount) => a.platform !== "telegram");
  chatAccounts.set(list);
  // A server message pinging one of your accounts says its name rather than "@user": nobody's profile is
  // stored for the account itself, so the lookup mentions do would never find it.
  const own: Record<string, string> = {};
  for (const a of list) if (a.user_id) own[a.user_id] = a.display_name || a.username || "you";
  if (Object.keys(own).length) mentionNames.update((m) => ({ ...m, ...own }));
  return list;
}

/**
 * Keep every account's conversations warm, from app start, whatever page is
 * open.
 *
 * The interval is deliberately slower than the Chats page's own refresh: each
 * pass costs the bot a channel sweep, so the background job is there to make
 * the tab open instantly, not to be the primary source of freshness. Accounts
 * are staggered so several running bots are not swept at the same moment.
 */
export function startChatPrefetch(intervalMs = 60000): () => void {
  let stopped = false;
  let timer: number | null = null;

  const pass = async () => {
    // Each pass costs every running bot a channel sweep over multi-second IPC.
    // Doing that for a window nobody is looking at is pure waste, and this ran
    // from app start on every page.
    if (stopped || document.hidden) return;
    let accounts: ChatAccount[];
    try {
      accounts = await loadChatAccounts();
    } catch {
      return;
    }
    // A stopped account cannot answer, and waiting out its timeout would hold
    // the queue up for everyone behind it.
    const live = accounts.filter((a) => !a.state || a.state === "running");
    for (const a of live) {
      // Re-checked each iteration: a pass is seconds long, so the window can
      // be hidden partway through one.
      if (stopped || document.hidden) return;
      await refreshChats(a.id, { maxAge: intervalMs / 2, quiet: true });
      await new Promise((r) => setTimeout(r, 1200));
    }
  };

  pass();
  timer = window.setInterval(pass, intervalMs);
  // Catch up as soon as the window comes back, so opening Chats after a while
  // away still finds warm data rather than a stale interval's worth.
  const onVisibility = () => {
    if (!document.hidden) pass();
  };
  document.addEventListener("visibilitychange", onVisibility);
  return () => {
    stopped = true;
    if (timer) clearInterval(timer);
    document.removeEventListener("visibilitychange", onVisibility);
  };
}
