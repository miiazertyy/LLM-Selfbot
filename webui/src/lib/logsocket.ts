/**
 * One WebSocket to /api/ws for the whole app.
 *
 * Dashboard, Logs, System and SnapchatSetup each opened their own, so a single
 * tab could hold four connections and the server pushed every log line down all
 * of them. They all want the same stream and differ only in how they filter it,
 * so the connection is shared and each caller takes a subscription instead.
 *
 * The socket opens on the first subscriber and closes when the last one leaves,
 * so a session that never visits a log-bearing page never opens one at all.
 */

export type LogEntry = {
  ts?: number;
  time?: string;
  source?: string;
  level?: string;
  text?: string;
};

type Sub = (entry: LogEntry) => void;

const subscribers = new Set<Sub>();
let socket: WebSocket | null = null;
let retry = 0;
let retryTimer: ReturnType<typeof setTimeout> | null = null;

function open() {
  if (socket || subscribers.size === 0) return;
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
  };

  ws.onmessage = (e) => {
    let entry: LogEntry;
    try {
      entry = JSON.parse(e.data);
    } catch {
      return;
    }
    // Iterate a copy: a handler may unsubscribe while we are delivering.
    for (const fn of [...subscribers]) {
      try {
        fn(entry);
      } catch {
        /* one bad consumer must not stop the rest of them getting the line */
      }
    }
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
  if (retryTimer || subscribers.size === 0) return;
  const wait = Math.min(1000 * 2 ** retry, 15000);
  retry++;
  retryTimer = setTimeout(() => {
    retryTimer = null;
    open();
  }, wait);
}

/** Subscribe to the live log stream. Returns an unsubscribe function. */
export function subscribeLogs(fn: Sub): () => void {
  subscribers.add(fn);
  open();
  return () => {
    subscribers.delete(fn);
    if (subscribers.size > 0) return;
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
  };
}
