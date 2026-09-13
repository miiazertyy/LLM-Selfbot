/**
 * A page's data, kept alive between visits.
 *
 * Every page is torn down and rebuilt when you navigate, because the router
 * keys on the route. So a page that fetched on mount threw its contents away
 * every time you left it, and showed a skeleton every time you came back, even
 * when the answer from ten seconds ago was still perfectly good. On anything
 * that goes to the bot over IPC that is a multi-second wait to be shown what
 * you were already looking at.
 *
 * A resource holds the last answer outside the component, so the page renders
 * it immediately and refreshes behind it. The only thing you ever see is the
 * data, occasionally with a quiet "checking" beside it.
 *
 *     const pics = resource("pictures", () => api.pictures(), { pictures: [] });
 *     onMount(() => pics.refresh({ maxAge: 10_000 }));
 *     const list = $derived($pics.data.pictures);
 *
 * `loading` is only true on a genuinely cold start. A refresh over existing
 * data sets `refreshing`, which is a hint, not a wall.
 */
import { get, writable, type Readable } from "svelte/store";

export type ResourceState<T> = {
  data: T;
  /** ms epoch of the last successful load. 0 means never. */
  fetched: number;
  /** Nothing to show yet and a request is out. */
  loading: boolean;
  /** Showing something, and checking for newer. */
  refreshing: boolean;
  error: string;
};

export type Resource<T> = Readable<ResourceState<T>> & {
  refresh(options?: { maxAge?: number; force?: boolean }): Promise<T | null>;
  /** Change the held value without a round trip, after an edit. */
  set(data: T): void;
  update(fn: (data: T) => T): void;
};

const registry = new Map<string, Resource<any>>();

export function resource<T>(
  key: string,
  fetcher: () => Promise<T>,
  initial: T,
): Resource<T> {
  const existing = registry.get(key);
  if (existing) return existing as Resource<T>;

  const store = writable<ResourceState<T>>({
    data: initial,
    fetched: 0,
    loading: false,
    refreshing: false,
    error: "",
  });

  // One request at a time, however many callers ask: a page mounting while the
  // background pass is mid-flight should join it, not start a second.
  let inflight: Promise<T | null> | null = null;

  async function refresh(options: { maxAge?: number; force?: boolean } = {}) {
    const { maxAge = 0, force = false } = options;
    const current = get(store);

    if (inflight) return inflight;
    if (!force && maxAge > 0 && current.fetched && Date.now() - current.fetched < maxAge) {
      return current.data;
    }

    const cold = current.fetched === 0;
    store.update((s) => ({ ...s, loading: cold, refreshing: !cold }));

    inflight = (async () => {
      try {
        const data = await fetcher();
        store.set({
          data,
          fetched: Date.now(),
          loading: false,
          refreshing: false,
          error: "",
        });
        return data;
      } catch (e: any) {
        // Keep whatever is on screen. A failed refresh should not blank a page
        // that was showing something perfectly readable a moment ago.
        store.update((s) => ({
          ...s,
          loading: false,
          refreshing: false,
          error: e?.message || "Could not load",
        }));
        return null;
      } finally {
        inflight = null;
      }
    })();

    return inflight;
  }

  const res: Resource<T> = {
    subscribe: store.subscribe,
    refresh,
    set: (data: T) => store.update((s) => ({ ...s, data })),
    update: (fn) => store.update((s) => ({ ...s, data: fn(s.data) })),
  };
  registry.set(key, res);
  return res;
}

/** Forget everything, for a hard reload. */
export function clearResources() {
  registry.clear();
}
