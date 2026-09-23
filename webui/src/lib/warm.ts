/**
 * Every page's data, fetched before anybody opens that page.
 *
 * A page holds its answers in a `resource()`, which survives navigation - so
 * the second visit to a tab is instant and the first one is not. The first one
 * is the slow, visible wait: a cold Settings rebuilds a 61-field schema, a cold
 * System asks about disks, ffmpeg and updates, a cold Memory reads the whole
 * table. All of it happening while you look at an empty page.
 *
 * `resource()` keys its registry globally and hands back the existing entry for
 * a key that is already registered, so warming one here is the same object the
 * page picks up when it mounts. The page still calls refresh() with its own
 * maxAge; it simply finds the answer already there.
 *
 * Ordered by how likely a tab is to be opened, and spaced out, because the
 * point is to use the time nobody is waiting on. Chats is missing on purpose:
 * it has its own prefetch loop (chats.ts) that keeps running, and the server
 * warms the expensive half of it at startup.
 *
 * Adding a resource to a page means adding it here. tests/test_web.py checks
 * the two lists have not drifted apart.
 */
import { api } from "./api";
import { resource } from "./resource";

// `initial` has to match what the page passes for the same key. Whoever
// registers first owns the entry, and that is this module - so getting it wrong
// would hand the page a shape it does not expect the moment a warm-up fails and
// the data stays at its initial value.
type Warm = { key: string; run: () => Promise<unknown>; initial: unknown };

const WARM: Warm[] = [
  // Cheap and almost always looked at.
  { key: "instructions", run: () => api.instructions(), initial: { text: "" } },
  { key: "memory", run: () => api.memory(), initial: { users: [] } },
  { key: "pictures", run: () => api.pictures(), initial: { pictures: [] } },
  { key: "chatArchive", run: () => api.chatArchive(40), initial: { conversations: [] } },
  // The settings tree: the single slowest page to open cold.
  { key: "settingsSchema", run: () => api.schema(), initial: { fields: [] } },
  // System asks four separate questions, none of them fast.
  { key: "systemInfo", run: () => api.sysInfo(), initial: null },
  { key: "systemDoctor", run: () => api.doctor(), initial: { checks: [] } },
  { key: "systemNetwork", run: () => api.network(), initial: null },
  { key: "systemUpdate", run: () => api.updateCheck(), initial: null },
  // Local AI probes a server that is usually not there, so it waits out a
  // timeout. Last, and only because that wait is the whole problem.
  { key: "localStatus", run: () => api.localStatus(), initial: null },
  { key: "localDetect", run: () => api.localDetect(), initial: null },
];

/** The keys warmed here, for the drift test. */
export const WARM_KEYS = WARM.map((w) => w.key);

/**
 * Warm everything, one at a time, in the background.
 *
 * Returns a stop function. Serialised rather than fired in parallel: several
 * of these reach the bot or the disk, and a burst of eleven at startup would
 * slow down the page the user is actually on, which defeats the point.
 */
export function warmPages(gapMs = 400): () => void {
  let stopped = false;
  const queue = [...WARM];

  const next = () => {
    if (stopped) return;
    const item = queue.shift();
    if (!item) return;
    // Registering with the same key the page uses is what makes this count:
    // resource() returns the entry that already exists rather than a new one.
    const res = resource<any>(item.key, item.run, item.initial);
    res
      .refresh({ maxAge: 0 })
      .catch(() => {})       // a warm-up that fails is not worth reporting
      .finally(() => {
        if (stopped) return;
        setTimeout(next, gapMs);
      });
  };

  // Let the first paint finish before any of this starts.
  const first = setTimeout(next, 1200);
  return () => {
    stopped = true;
    clearTimeout(first);
  };
}
