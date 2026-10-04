/**
 * One WebSocket to /api/ws for the whole app.
 *
 * Dashboard, Logs, System and SnapchatSetup each opened their own, so a single
 * tab could hold four connections and the server pushed every log line down all
 * of them. They all want the same stream and differ only in how they filter it,
 * so the connection is shared and each caller takes a subscription instead.
 *
 * The same socket carries live events (source "_event"): the Chats tab's
 * updates, pushed by the runners the moment something happens. Those never go
 * to log subscribers, and log lines never go to event subscribers.
 *
 * The socket opens on the first subscriber of either kind and closes when the
 * last one leaves, so a session that needs neither never opens one at all.
 */

export type LogEntry = {
  ts?: number;
  time?: string;
  source?: string;
  level?: string;
  text?: string;
};

type Sub = (entry: LogEntry) => void;
/** An event's payload, or null when the socket has just (re)connected. */
type EventSub = (payload: Record<string, any> | null) => void;

const subscribers = new Set<Sub>();
const eventSubs = new Map<string, Set<EventSub>>();
let socket: WebSocket | null = null;
let retry = 0;
let retryTimer: ReturnType<typeof setTimeout> | null = null;

function wanted(): boolean {
  if (subscribers.size) return true;
  for (const s of eventSubs.values()) if (s.size) return true;
  return false;
}

function deliver<T>(fns: Iterable<(x: T) => void>, value: T) {
  // Iterate a copy: a handler may unsubscribe while we are delivering.
  for (const fn of [...fns]) {
    try {
      fn(value);
    } catch {
      /* one bad consumer must not stop the rest of them getting it */
    }
  }
}

function open() {
  if (socket || !wanted()) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let ws: WebSocket;
  try {
    ws = new WebSocket(`${proto}://${location.host}/api/ws`);
  } catch {
    schedule();
    return;
  }
  socket = ws;

  ws.onopen = () => {
    retry = 0;
    // Events are not replayed, so anything that happened while the socket was
    // down is lost; tell event subscribers so they can catch up once.
    for (const subs of eventSubs.values()) deliver(subs, null);
  };

  ws.onmessage = (e) => {
    let entry: LogEntry & { kind?: string; event?: Record<string, any> };
    try {
      entry = JSON.parse(e.data);
    } catch {
      return;
    }
    if (entry.source === "_event") {
      const subs = eventSubs.get(entry.kind || "");
      if (subs && entry.event) deliver(subs, entry.event);
      return;
    }
    deliver(subscribers, entry);
  };

  ws.onclose = () => {
    if (socket === ws) socket = null;
    schedule();
  };

  ws.onerror = () => {
    try {
      ws.close();
    } catch {
      /* onclose still runs and schedules the retry */
    }
  };
}

/** Reconnect with backoff, but only while something still wants the stream. */
function schedule() {
  if (retryTimer || !wanted()) return;
  const wait = Math.min(1000 * 2 ** retry, 15000);
  retry++;
  retryTimer = setTimeout(() => {
    retryTimer = null;
    open();
  }, wait);
}

/** Close the socket once nothing is listening any more. */
function release() {
  if (wanted()) return;
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
  retry = 0;
  const ws = socket;
  socket = null;
  if (ws) {
    ws.onclose = null; // deliberate: this close must not schedule a reconnect
    try {
      ws.close();
    } catch {
      /* already gone */
    }
  }
}

/** Subscribe to the live log stream. Returns an unsubscribe function. */
export function subscribeLogs(fn: Sub): () => void {
  subscribers.add(fn);
  open();
  return () => {
    subscribers.delete(fn);
    release();
  };
}

/**
 * Subscribe to one kind of live event. The handler gets each event's payload,
 * and null whenever the socket (re)connects, which is the cue to refetch.
 */
export function subscribeEvents(kind: string, fn: EventSub): () => void {
  let subs = eventSubs.get(kind);
  if (!subs) eventSubs.set(kind, (subs = new Set()));
  subs.add(fn);
  open();
  return () => {
    subs!.delete(fn);
    release();
  };
}
