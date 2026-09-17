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
import { api } from "./api";

export type ChatUser = {
  id: string;
  name: string;
  snippet: string;
  count: number;
  ts?: number;
};

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
  username?: string;
  display_name?: string;
  avatar?: string;
  state?: string;
};

const EMPTY: ChatEntry = { users: [], fetched: 0, loading: false, error: "" };

export const chatCache = writable<Record<string, ChatEntry>>({});
export const chatAccounts = writable<ChatAccount[]>([]);

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
  try {
    const result = await api.reply(userId, target);
    forget(target, userId);
    return result;
  } finally {
    mark(replying, userId, false);
    if (!Object.keys(get(replying)).length && !Object.keys(get(replyingAll)).length) {
      chatBusy.set(false);
    }
    refreshChats(target, { force: true });
  }
}

export async function sendReplyAll(target: string) {
  if (get(replyingAll)[target]) return null;
  mark(replyingAll, target, true);
  chatBusy.set(true);
  try {
    const result = await api.replyAll(target);
    clearChats(target);
    return result;
  } finally {
    mark(replyingAll, target, false);
    if (!Object.keys(get(replying)).length && !Object.keys(get(replyingAll)).length) {
      chatBusy.set(false);
    }
    refreshChats(target, { force: true });
  }
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
  { maxAge = 0, force = false }: { maxAge?: number; force?: boolean } = {},
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
  const run = (async () => {
    try {
      const data = await api.chats(target);
      patch(target, {
        users: data.users || [],
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
    }
  })();

  inflight.set(target, run);
  return run;
}

/** Drop someone from the cached list, after they have been replied to. */
export function forget(target: string, userId: string) {
  const current = entry(target);
  patch(target, { users: current.users.filter((u) => u.id !== userId) });
}

export function clearChats(target: string) {
  patch(target, { users: [], fetched: Date.now() });
}

export async function loadChatAccounts(): Promise<ChatAccount[]> {
  const data = await api.accounts();
  const list = (data.accounts || []).filter((a: ChatAccount) => a.platform !== "telegram");
  chatAccounts.set(list);
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
      await refreshChats(a.id, { maxAge: intervalMs / 2 });
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
