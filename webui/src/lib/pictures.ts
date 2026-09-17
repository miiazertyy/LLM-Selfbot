/**
 * Progress of the background pass that describes imported pictures.
 *
 * The work runs on the server and outlives any page, so the progress has to as
 * well. It used to be component state driven by an interval started in the
 * page: leaving the tab destroyed the state, leaked the interval, and coming
 * back showed nothing at all even though the server was still working.
 *
 * The poll lives here instead, runs only while there is something to watch,
 * and any page that cares can subscribe.
 */
import { get, writable } from "svelte/store";
import { api } from "./api";

export type DescribeState = {
  running: boolean;
  total: number;
  done: number;
  failed: number;
  reason?: string;
  /** How many Groq keys the pass is using at once, one picture each. */
  workers?: number;
};

/** null when nothing is happening, so a page can simply not render. */
export const describeState = writable<DescribeState | null>(null);

/** Bumped whenever a description lands, so a list can refresh itself. */
export const describeTick = writable(0);

let timer: number | null = null;
let lastDone = -1;

function stop() {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
}

async function poll() {
  let s: DescribeState;
  try {
    s = await api.pictureStatus();
  } catch {
    // The server going away is not worth a stuck bar on screen.
    stop();
    describeState.set(null);
    return;
  }

  if (lastDone === -1) {
    // First look. Nothing has changed, it is simply the first time we asked,
    // and announcing it made every page that listens reload for no reason.
    lastDone = s.done;
  } else if (s.done !== lastDone) {
    lastDone = s.done;
    describeTick.update((n) => n + 1);
  }

  if (s.running) {
    describeState.set(s);
    return;
  }

  // Finished. Hold the final count on screen briefly when something failed,
  // so the reason is readable rather than vanishing with the bar.
  stop();
  const wasRunning = get(describeState)?.running === true;
  if (s.failed) {
    describeState.set({ ...s, running: false });
    setTimeout(() => {
      const cur = get(describeState);
      if (cur && !cur.running) describeState.set(null);
    }, 8000);
  } else {
    describeState.set(null);
  }
  // Only when a run actually just ended. Announcing it on every poll, including
  // the idle check a page makes when it opens, made every listener reload.
  if (wasRunning) describeTick.update((n) => n + 1);
}

/**
 * Start watching, or do nothing if already watching.
 *
 * Safe to call on every page mount: it checks once immediately, so a run that
 * started before this page existed is picked up straight away.
 */
export function watchDescribe(intervalMs = 2000) {
  poll();
  if (timer !== null) return;
  timer = window.setInterval(poll, intervalMs);
}

/** One check with no polling, for app start. */
export async function checkDescribeOnce() {
  try {
    const s = await api.pictureStatus();
    if (s.running) {
      describeState.set(s);
      watchDescribe();
    }
  } catch {
    /* nothing to report */
  }
}
