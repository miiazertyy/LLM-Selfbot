import { writable } from "svelte/store";

// "info" is not a problem: an available update, and anything else worth a
// quiet mark rather than a warning.
export type Issue = {
  route: string;
  level: "error" | "warn" | "info";
  title: string;
  detail: string;
  where?: string;
  /** Settings category holding the control, so the link can open it. */
  section?: string;
};

/** Populated by a poll in App.svelte; drives the nav dots and the Dashboard list. */
export const health = writable<{ issues: Issue[]; routes: Record<string, string> }>({
  issues: [],
  routes: {},
});

/**
 * Which Settings category to open on arrival.
 *
 * The dependency doctor sends you to the exact place that fixes a red row, and
 * "Settings, then find it yourself" is not that. Settings consumes and clears
 * this on mount.
 */
export const settingsSection = writable<string>("");

export const toasts = writable<{ id: number; text: string; kind: "ok" | "err" | "info" }[]>([]);

let toastId = 0;

export function toast(text: string, kind: "ok" | "err" | "info" = "info") {
  const id = ++toastId;
  toasts.update((t) => [...t, { id, text, kind }]);
  setTimeout(() => {
    toasts.update((t) => t.filter((x) => x.id !== id));
  }, 4000);
}

/**
 * Panel preferences, stored on the server as well as in the browser.
 *
 * localStorage alone lost them in two ordinary situations. The desktop shell
 * ran the webview in private mode, so it was wiped on exit; and localStorage is
 * keyed on the origin, so taking port 8788 because 8787 was still busy gave a
 * brand new empty store. Either way the theme, the font and the dashboard
 * layout reset on relaunch.
 *
 * The server copy is the real one. localStorage stays as an instant read on
 * load, so nothing flashes while the fetch is in flight.
 */
const remoteKeys = new Set<string>();
let remoteLoaded = false;

async function pushRemote(key: string, value: unknown) {
  if (!remoteKeys.has(key) || !remoteLoaded) return;
  try {
    await fetch("/api/prefs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ prefs: { [key]: value } }),
    });
  } catch {
    /* the browser copy still holds it */
  }
}

const stores = new Map<string, { set: (v: any) => void }>();

/** Called once at startup: the stored answer wins over the local one. */
export async function loadPrefs() {
  try {
    const data = await fetch("/api/prefs").then((r) => r.json());
    for (const [key, value] of Object.entries(data?.prefs ?? {})) {
      stores.get(key)?.set(value);
    }
  } catch {
    /* offline or an older build: localStorage carries on alone */
  } finally {
    // Only now, or loading the stored values would immediately write them
    // back, and a failed fetch would overwrite good values with defaults.
    remoteLoaded = true;
  }
}

function persisted<T>(key: string, initial: T, remote = false) {
  const store = writable<T>(initial);
  if (remote) remoteKeys.add(key);
  if (typeof localStorage !== "undefined") {
    const raw = localStorage.getItem(key);
    if (raw !== null) {
      try {
        store.set(JSON.parse(raw) as T);
      } catch {}
    }
    store.subscribe((v) => {
      try {
        localStorage.setItem(key, JSON.stringify(v));
      } catch {}
      pushRemote(key, v);
    });
  }
  stores.set(key, store);
  return store;
}

/**
 * Show every setting, everywhere, instead of the common ones with the rest
 * behind a disclosure.
 *
 * Persisted, because someone who wants the full list wants it on every page
 * and every launch, not once per visit.
 */
/**
 * Which Settings subtab you were last on, as "tab/sub".
 *
 * Leaving Settings and coming back used to drop you on the first tab, so a
 * session of fiddling with one thing meant re-navigating to it every time.
 */
export const settingsPath = persisted<string>("settingsPath", "discord/replies");

/**
 * The mark in the corner opens the page the app is named after.
 *
 * Counted so it can offer to stop after the second time: the first is a nice
 * surprise, the third would be a trap, and an easter egg you cannot turn off is
 * just a misclick that keeps happening.
 */
export const logoOpens = persisted<number>("logoOpens", 0);
export const logoLinkOff = persisted<boolean>("logoLinkOff", false);

export const snowEnabled = persisted<boolean>("snow", true, true);

/**
 * Order of the Dashboard sections, top to bottom.
 *
 * Stored as ids rather than an index, so adding a section later appends it
 * instead of scrambling everyone's saved layout. Dashboard.svelte reconciles
 * this against the sections that actually exist on every load.
 */
export const dashOrder = persisted<string[]>("dashOrder", [
  "figures",
  "activity",
  "accounts",
  "people",
  "log",
], true);

/**
 * Animations are a product feature here, not decoration, so the OS
 * prefers-reduced-motion setting picks the DEFAULT rather than overriding the
 * user. Windows reports "reduce" whenever "Animation effects" is off, which was
 * silently disabling the whole jello UI and the snow.
 */
export const motionEnabled = persisted<boolean>("motion", true, true);

/** Colour theme id, see lib/themes.ts. */
export const fontId = persisted<string>("font", "mikhak", true);

export const themeId = persisted<string>("theme", "midnight", true);

/**
 * A background image and a typeface of the user's own.
 *
 * The files themselves live on the server (see app/web/routes/appearance_routes.py):
 * localStorage is per-origin and gets wiped by the desktop webview, which is
 * the same reason the other preferences are mirrored server-side, and a font
 * is far too big for it anyway. What is kept here is only the choice to use
 * them and how far the image is dimmed.
 *
 * `appearance` is the server's answer about what is actually uploaded. It is
 * deliberately not persisted: it describes files, not a preference, and a
 * stale copy would mean rendering a background that is no longer there.
 */
/**
 * How solid the cards are: "solid", "glass" or "frost".
 *
 * Glass costs more than it looks: every translucent panel makes the compositor
 * re-blur what is behind it. Solid stays the escape hatch, and the picker says
 * so rather than leaving someone to work out why a busy page felt heavy.
 */
export const surfaceId = persisted<string>("surface", "glass", true);

/** Which living background is drawn behind the app. See lib/backdrops.ts. */
export const backdropId = persisted<string>("backdrop", "aurora", true);

export const customBgOn = persisted<boolean>("customBgOn", false, true);
export const customBgDim = persisted<number>("customBgDim", 0.72, true);

export type AppearanceInfo = {
  background: { present: boolean; name?: string; size?: number };
  font: { present: boolean; name?: string; size?: number; format?: string };
};

export const appearance = writable<AppearanceInfo>({
  background: { present: false },
  font: { present: false },
});

/** Bumped on every upload, so cached copies of the old file are not reused. */
export const appearanceVersion = writable<number>(Date.now());

/** Ask the server what is uploaded. Safe to call whenever. */
export async function loadAppearance() {
  try {
    const data = await fetch("/api/appearance").then((r) => r.json());
    if (data && data.background && data.font) appearance.set(data);
  } catch {
    /* an older build, or offline: the panel just shows nothing uploaded */
  }
}

// The Mica/Acrylic themes were removed; anyone still holding one of those ids
// in localStorage is moved to the default rather than left on a dead value.
themeId.update((id) => (id === "mica" || id === "acrylic" ? "midnight" : id));

export type ChildState = {
  id: string;
  role: string;
  account: number | null;
  label: string;
  state: string;
  pid: number | null;
  restarts: number;
  uptime: number;
};
