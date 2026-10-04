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
import { begin, type JobHandle } from "./busy";
import { get, writable } from "svelte/store";
import { api } from "./api";
import { toast } from "./stores";
import { play } from "./uisound";

// ── Adding pictures from this computer ────────────────────────────────────────
// The files go up one at a time from the page, and that loop carries on when the page is left; its count used to
// be the page's own, so coming back showed an idle drop zone while pictures were still going in. The loop and its
// count live here instead, and pictures dropped while it runs join the queue.

/** A video going in: made an MP4 first (`percent` of the way), then watched to describe it. */
export type VideoStep = { step: "convert" | "describe"; percent: number };
export type AddState = { done: number; total: number; name: string; video?: VideoStep | null };
/** Pictures going up now, or null. */
export const addState = writable<AddState | null>(null);

/** Every kind of video the server takes (VIDEO_EXTS in app/utils/videos.py); each becomes an MP4. */
export const VIDEO_EXTS = [
  ".mp4", ".m4v", ".mov", ".qt", ".webm", ".mkv", ".avi", ".wmv", ".asf", ".flv", ".f4v", ".3gp", ".3g2",
  ".mpg", ".mpeg", ".mpe", ".m2v", ".ts", ".mts", ".m2ts", ".vob", ".ogv", ".dv", ".mxf", ".rm", ".rmvb",
  ".divx", ".xvid", ".hevc", ".h264", ".h265", ".264", ".265", ".y4m", ".nut", ".gifv",
];
export const isVideoFile = (f: { name: string; type?: string }) =>
  !!f.type?.startsWith("video/") || VIDEO_EXTS.some((e) => f.name.toLowerCase().endsWith(e));

/** How long a video is, as a player says it: 0:07, 1:24, 1:02:10. */
export function clock(seconds?: number): string {
  const s = Math.max(0, Math.round(seconds ?? 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/** While a video goes in, how far the server has got with it, every 600ms; stops with the upload. */
function watchVideo(persona: string): () => void {
  let on = true;
  const tick = async () => {
    if (!on) return;
    try {
      const s: any = await api.pictureStatus(persona);
      const v = s?.video;
      if (on && v?.active) {
        addState.update((a) => a && { ...a, video: { step: v.step === "describe" ? "describe" : "convert", percent: Number(v.percent) || 0 } });
      }
    } catch {
      /* the upload itself says how it went */
    }
    if (on) setTimeout(tick, 600);
  };
  setTimeout(tick, 300);
  return () => { on = false; };
}
/** Each with the persona it was dropped for ("" for Default): switching persona while they go up does not move them. */
const queue: { file: File; persona: string }[] = [];
let adding = false;

/** Adds them, after any already going up. `after` runs once the queue is empty (the list refreshed). */
export function addPictures(files: File[], after: () => void, persona = ""): void {
  if (!files.length) return;
  queue.push(...files.map((file) => ({ file, persona })));
  addState.update((s) => ({ done: s?.done ?? 0, total: (s?.total ?? 0) + files.length, name: s?.name || files[0].name }));
  if (!adding) void addAll(after);
}

async function addAll(after: () => void) {
  adding = true;
  const total0 = get(addState)?.total ?? queue.length;
  const job = begin("pictures", total0 > 1 ? `Adding ${total0} pictures`
    : queue[0] && isVideoFile(queue[0].file) ? "Adding a video" : "Adding a picture");
  let describing = false;
  let added = 0;
  const failed: string[] = [];
  while (queue.length) {
    const { file, persona } = queue.shift()!;
    const video = isVideoFile(file);
    addState.update((s) => s && { ...s, name: file.name, video: video ? { step: "convert", percent: 0 } : null });
    const many = (get(addState)?.total ?? 1) > 1;
    // A video converts for a while, and a zip may hold some: how far it has got, on the drop zone.
    const unwatch = video || /\.zip$/i.test(file.name) ? watchVideo(persona) : null;
    try {
      const r = await api.uploadPicture(file, persona);
      // Made an MP4 and watched: a glint as it lands.
      if (r.video) play("glint", { level: 0.6 });
      if (r.zip) {
        // A folder of pictures arrives as one archive, so the summary is per archive rather than per file.
        const parts = [`Added ${r.added.length} picture${r.added.length === 1 ? "" : "s"}`];
        if (r.skipped?.length) parts.push(`skipped ${r.skipped.length}`);
        toast(parts.join(", ") + ".", r.added.length ? "ok" : "err");
        for (const s of (r.skipped || []).slice(0, 3)) toast(`${s.name}: ${s.reason}`, "info");
        if (r.describing) describing = true;
      } else if (!many) {
        // A video made smaller to send says so.
        const smaller = r.smaller ? `, made smaller to ${(Number(r.size) / 1e6).toFixed(1)} MB,` : "";
        toast(r.description ? `Added ${r.name}${smaller} and described it.`
              : r.reason ? `Added ${r.name}${smaller.replace(/,$/, "")}. ${r.reason}` : `Added ${r.name}${smaller.replace(/,$/, "")}.`,
              r.description ? "ok" : "info");
      }
      added++;
    } catch (e: any) {
      failed.push(file.name);
      toast(`${file.name}: ${e.message}`, "err");
    } finally {
      unwatch?.();
    }
    const s = get(addState);
    if (s) {
      const next = { ...s, done: s.done + 1, video: null };
      addState.set(next);
      job.progress(next.done, next.total);
      // Heard filling up: a note a step higher with each one in, so a big batch climbs as it goes.
      if (next.total > 1) play("rise", { p: next.done / next.total, level: 0.55 });
    }
  }
  const s = get(addState);
  job();
  adding = false;
  // Many at once: said once at the end rather than a notice for every one of them.
  if (s && s.total > 1) {
    toast(failed.length ? `Added ${added} of ${s.total} pictures. ${failed.length} could not be added.`
                        : `Added ${added} pictures.`, failed.length ? "info" : "ok");
  }
  // The full count on screen for a moment, then the drop zone again.
  setTimeout(() => { if (!adding) addState.set(null); }, 900);
  after();
  if (describing) watchDescribe();
}

export type DescribeState = {
  running: boolean;
  total: number;
  done: number;
  failed: number;
  reason?: string;
  /** How many Groq keys the pass is using at once, one picture each. */
  workers?: number;
  /** Looks being put on every picture at once (Settings, Pictures), alongside. */
  looks?: LookJob;
};

export type LookJob = { running: boolean; total: number; done: number };

/** null when nothing is happening, so a page can simply not render. */
export const describeState = writable<DescribeState | null>(null);

/** Looks being put on every picture at once, or null. */
export const lookState = writable<LookJob | null>(null);

let endLooks: JobHandle | null = null;
lookState.subscribe((s) => {
  if (s?.running && !endLooks) endLooks = begin("pictures", "Adding filters to pictures");
  if (s?.running && endLooks && s.total > 0) endLooks.progress(s.done, s.total);
  else if (!s?.running && endLooks) {
    endLooks();
    endLooks = null;
  }
});

// A describe pass runs for minutes and carries on whatever page is open.
let endDescribe: JobHandle | null = null;
describeState.subscribe((s) => {
  if (s?.running && !endDescribe) {
    endDescribe = begin("pictures", "Describing pictures");
  }
  if (s?.running && endDescribe && s.total > 0) {
    endDescribe.progress(s.done, s.total);
  } else if (!s?.running && endDescribe) {
    endDescribe();
    endDescribe = null;
  }
});

/** Bumped whenever a description lands, so a list can refresh itself. */
export const describeTick = writable(0);

let timer: number | null = null;
let lastDone = -1;
let lastLooks = -1;

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
    lookState.set(null);
    return;
  }

  // Looks going on: each one changes a picture, so the list follows; and once more when they are all done.
  const looks = s.looks?.running ? s.looks : null;
  const lookDone = s.looks?.done ?? 0;
  if (lastLooks !== -1 && lookDone !== lastLooks) describeTick.update((n) => n + 1);
  lastLooks = lookDone;
  const hadLooks = get(lookState) !== null;
  lookState.set(looks);
  if (hadLooks && !looks) describeTick.update((n) => n + 1);

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
  // so the reason is readable rather than vanishing with the bar. Looks still
  // going keep the watch on.
  if (!looks) stop();
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
    if (s.running || s.looks?.running) {
      if (s.running) describeState.set(s);
      watchDescribe();
    }
  } catch {
    /* nothing to report */
  }
}
