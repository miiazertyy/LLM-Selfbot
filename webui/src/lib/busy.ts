/**
 * Work still running on a page you have left.
 *
 * Pages load and act asynchronously, and navigating away does not stop them:
 * a reply-to-all keeps sending, a summary keeps writing, a model keeps
 * downloading. Nothing said so, so it looked finished, or lost. Pages report
 * their slow work here, and the sidebar puts a spinner beside that page for as
 * long as it runs - then a tick for a moment when it is done.
 *
 * Two rules keep it from being noise:
 *
 *   - Nothing shows before SHOW_AFTER. Most requests finish well inside that,
 *     and a spinner that flashes on every click is a flicker, not information.
 *   - Once shown, it stays at least MIN_VISIBLE, so a job that ends just after
 *     appearing does not blink.
 *
 * App-initiated background work (the startup warm-up, the Chats prefetch loop,
 * routine polling) is deliberately not reported: nobody asked for it, and the
 * sidebar would spin on half the pages for no reason anyone could act on.
 *
 * Progress is shown only where it is real. Work that knows how far along it is
 * - replying to 8 people, describing 40 pictures, a download reporting bytes -
 * calls job.progress(done, total), and the indicator fills to exactly that:
 * eight steps move it eight times, 27% fills 27/100 of it. Work that cannot
 * know (one request that is either done or not) keeps the spinner. A made-up
 * percentage on those would look more precise and be less true.
 */
import { get, writable } from "svelte/store";

const SHOW_AFTER = 300;
const MIN_VISIBLE = 600;
/** How long the tick stays after background work finishes. */
const DONE_FOR = 1600;

type Job = {
  route: string;
  label: string;
  since: number;
  /** Known progress, or null while it is not known. */
  done: number | null;
  total: number | null;
};

/** What the sidebar and header draw for one page. */
export type BusyInfo = {
  labels: string[];
  /** null = no real progress, so spin. Otherwise how far along, exactly. */
  done: number | null;
  total: number | null;
};

/** A running job: call it to end it, or .progress(done, total) to move it. */
export type JobHandle = (() => void) & { progress(done: number, total: number): void };

const jobs = new Map<number, Job>();
let nextId = 1;

/** Pages with work showing: route -> what is running and how far along. */
export const busyRoutes = writable<Record<string, BusyInfo>>({});
/** Pages whose shown work finished a moment ago: route -> when. */
export const doneRoutes = writable<Record<string, number>>({});

const shownAt: Record<string, number> = {};
let timer: ReturnType<typeof setTimeout> | null = null;

function reconcile() {
  const now = Date.now();
  const byRoute: Record<string, Job[]> = {};
  for (const j of jobs.values()) (byRoute[j.route] ??= []).push(j);

  const prev = get(busyRoutes);
  const next: Record<string, BusyInfo> = {};
  let wake = Infinity;

  for (const [route, list] of Object.entries(byRoute)) {
    const oldest = Math.min(...list.map((j) => j.since));
    if (route in shownAt || now - oldest >= SHOW_AFTER) {
      shownAt[route] ??= now;
      next[route] = { labels: [...new Set(list.map((j) => j.label).filter(Boolean))],
                      ...combined(list) };
    } else {
      wake = Math.min(wake, oldest + SHOW_AFTER);
    }
  }

  // Shown, now idle: hold for the minimum, then let it go with a tick.
  const finished: string[] = [];
  for (const route of Object.keys(shownAt)) {
    if (byRoute[route]) continue;
    if (now - shownAt[route] < MIN_VISIBLE) {
      // Held a moment after finishing. Anything that had real progress is,
      // by definition, done - show it full rather than frozen where it was.
      const held = prev[route] ?? { labels: [], done: null, total: null };
      next[route] = held.total ? { ...held, done: held.total } : held;
      wake = Math.min(wake, shownAt[route] + MIN_VISIBLE);
    } else {
      delete shownAt[route];
      finished.push(route);
    }
  }

  busyRoutes.set(next);
  if (finished.length) {
    doneRoutes.update((d) => {
      const out = { ...d };
      for (const r of finished) out[r] = now;
      return out;
    });
    wake = Math.min(wake, now + DONE_FOR);
  }
  // Drop ticks that have had their moment.
  const done = get(doneRoutes);
  const fresh = Object.fromEntries(Object.entries(done).filter(([, t]) => now - t < DONE_FOR));
  if (Object.keys(fresh).length !== Object.keys(done).length) doneRoutes.set(fresh);
  for (const t of Object.values(fresh)) wake = Math.min(wake, t + DONE_FOR);

  if (timer) clearTimeout(timer);
  timer = Number.isFinite(wake) ? setTimeout(reconcile, Math.max(16, wake - now)) : null;
}

/**
 * One page's progress, from its jobs that know theirs.
 *
 * A single job keeps its own units, so 3 of 8 stays 3 of 8. Several at once are
 * averaged into a percentage, each counting equally, because adding "3 of 8
 * replies" to "40% of a download" gives a number that means nothing. Jobs that
 * do not know their progress are left out rather than counted as zero - one
 * quick request should not drag a real 90% back to 45%.
 */
function combined(list: Job[]): { done: number | null; total: number | null } {
  const known = list.filter((j) => j.total !== null && j.total > 0 && j.done !== null);
  if (!known.length) return { done: null, total: null };
  if (known.length === 1) return { done: known[0].done, total: known[0].total };
  const avg = known.reduce((s, j) => s + (j.done as number) / (j.total as number), 0) / known.length;
  return { done: Math.round(avg * 100), total: 100 };
}

/**
 * Mark work as started on a page. Returns a handle: call it to end the work
 * (more than once is harmless, so it can sit in a finally), or call
 * .progress(done, total) whenever the work knows how far along it is.
 */
export function begin(route: string, label = ""): JobHandle {
  const id = nextId++;
  jobs.set(id, { route, label, since: Date.now(), done: null, total: null });
  // A new job cancels a pending tick for the same page: it is busy again.
  if (get(doneRoutes)[route]) {
    doneRoutes.update((d) => {
      const out = { ...d };
      delete out[route];
      return out;
    });
  }
  reconcile();
  let ended = false;
  const handle = (() => {
    if (ended) return;
    ended = true;
    jobs.delete(id);
    reconcile();
  }) as JobHandle;
  handle.progress = (done: number, total: number) => {
    const job = jobs.get(id);
    if (!job || !(total > 0)) return;
    const d = Math.max(0, Math.min(total, done));
    if (job.done === d && job.total === total) return;   // nothing moved
    job.done = d;
    job.total = total;
    reconcile();
  };
  return handle;
}

/** Report a promise as work on a page; resolves exactly as the promise does. */
export function track<T>(route: string, work: Promise<T>, label = ""): Promise<T> {
  const end = begin(route, label);
  return work.finally(end);
}

/**
 * Report work that is running somewhere else - a download on the server, an
 * install - until `isDone` says it has finished.
 *
 * For jobs whose own progress polling lives in a component: that polling stops
 * when you leave the page, which is exactly when this needs to keep watching.
 * Gives up after `maxMs`, so a server that never answers cannot leave a
 * spinner on forever.
 */
export function trackUntil(
  route: string,
  label: string,
  isDone: (report: (done: number, total: number) => void) => Promise<boolean>,
  everyMs = 3000,
  maxMs = 2 * 60 * 60 * 1000,
): () => void {
  const end = begin(route, label);
  const started = Date.now();
  let stopped = false;
  const tick = async () => {
    if (stopped) return;
    let done = false;
    try {
      // The check can report how far along it is as it goes.
      done = await isDone((d, t) => end.progress(d, t));
    } catch {
      done = false;           // a blip in the connection is not "finished"
    }
    if (done || Date.now() - started > maxMs) {
      stopped = true;
      end();
      return;
    }
    setTimeout(tick, everyMs);
  };
  setTimeout(tick, everyMs);
  return () => {
    stopped = true;
    end();
  };
}

/**
 * Which page a cached page resource belongs to, by its key in resource.ts.
 * Loading one of these is loading that page.
 */
export const RESOURCE_ROUTES: Record<string, string> = {
  accounts: "accounts",
  accountSlots: "accounts",
  accountActivity: "accounts",
  instructions: "persona",
  personas: "profiles",
  memory: "memory",
  pictures: "pictures",
  chatArchive: "chats",
  settingsSchema: "settings",
  localStatus: "settings",
  localDetect: "settings",
  systemInfo: "system",
  systemDoctor: "system",
  systemNetwork: "system",
  systemUpdate: "system",
};

/**
 * How far along, in the units that read naturally: "3/8" for a handful of
 * steps, "27%" for anything counted in bytes or out of a hundred. "" when
 * the progress is not known.
 */
export function progressText(info: { done: number | null; total: number | null } | undefined): string {
  if (!info || info.total === null || info.done === null || !(info.total > 0)) return "";
  if (info.total === 100) return `${Math.round(info.done)}%`;
  if (info.total <= 50) return `${Math.round(info.done)}/${info.total}`;
  return `${Math.round((info.done / info.total) * 100)}%`;
}

/** For tests: the jobs currently registered, by page. */
export function _activeJobs(): Record<string, number> {
  const out: Record<string, number> = {};
  for (const j of jobs.values()) out[j.route] = (out[j.route] ?? 0) + 1;
  return out;
}
