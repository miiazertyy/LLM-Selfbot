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
  /** A button that fixes it on the spot, e.g. starting Ollama. */
  fix?: { label: string; call: string; models?: string[] };
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

/**
 * The settings Settings opens on: one persona's own ("Change settings for
 * Juniper" on the Personas page), or "" for everyone's. Settings reads and
 * clears it on mount, like settingsSection.
 */
export const settingsScope = writable<string>("");

/**
 * A log source another page asked to see on its own, e.g. "Its log" on an
 * account card. Logs shows only that source when it opens, and clears this.
 */
export const logsFocus = writable<string>("");

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

/** A mouse wheel's notches glide rather than jump (lib/smoothscroll.ts). Settings, Appearance, Interface. */
export const smoothScroll = persisted<boolean>("smoothScroll", true, true);

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
 * Whether the Pictures tab opens with its pictures blurred.
 *
 * Opening the tab put the first two pictures on screen at full size straight
 * away, which is not always what you want on a shared screen or with someone
 * beside you. On by default; hovering one still shows it, and "Show pictures"
 * shows the lot until you leave the tab.
 */
export const picturesBlur = persisted<boolean>("picturesBlur", true, true);

/**
 * The persona the Personas, Pictures and Memory pages show (lib/personas): one
 * picked on any of them stays picked on the others, and across visits.
 */
export const viewPersona = persisted<string>("viewPersona", "default");

/** One widget placed on the Dashboard. See lib/dashboard/widgets.ts. */
export type WidgetInstance = {
  /** Unique per placement, so two "Time of day" widgets can differ. */
  id: string;
  type: string;
  collapsed?: boolean;
  size?: "half" | "full";
  options?: Record<string, string | number | boolean>;
};

/**
 * The Dashboard's widgets, in order, with how each is set up.
 *
 * Replaces dashOrder, which could only reorder a fixed five. null until the
 * first load, when widgets.ts builds it - from dashOrder if there is one, so a
 * layout someone already arranged comes across intact.
 */
export const dashLayout = persisted<WidgetInstance[] | null>("dashLayout", null, true);

/**
 * Animations are a product feature here, not decoration, so the OS
 * prefers-reduced-motion setting picks the DEFAULT rather than overriding the
 * user. Windows reports "reduce" whenever "Animation effects" is off, which was
 * silently disabling the whole jello UI and the snow.
 */
export const motionEnabled = persisted<boolean>("motion", true, true);

/** Big Picture Mode is open: the whole-screen, watch-it-live view (lib/bigpicture). */
export const bigPicture = writable<boolean>(false);
/**
 * Set while Big Picture is closing. Its inner animations read it and finish at
 * once, so leaving is the one quick fade: the avatar's flight between the queue
 * and the stage kept the whole view on screen for over a second after Esc.
 */
export const bigPictureExit = { on: false };
/**
 * Set while Big Picture covers the whole window: the app underneath is then
 * not drawn at all (App.svelte). It went on laying out and animating behind a
 * view that hid every pixel of it, which cost Big Picture its frames, and
 * every resize in and out of fullscreen laid out the whole app for nothing.
 */
export const bigPictureCovering = writable<boolean>(false);
/** Set while Big Picture fades in over the app, which fades out under it, before it covers it. */
export const bigPictureArriving = writable<boolean>(false);
/**
 * How Big Picture closes itself, set while it is open: out of fullscreen
 * first, while it still covers everything, and only then away, so the app is
 * laid out once at the size it ends up rather than at fullscreen and again
 * after. Every close comes through setBigPicture, so the hotkey takes the same
 * way out as Esc.
 */
export const bigPictureCloser: { fn: (() => void) | null } = { fn: null };
/** Open or close Big Picture; the only way either should happen. */
export function setBigPicture(on: boolean) {
  if (!on && bigPictureCloser.fn) {
    const close = bigPictureCloser.fn;
    bigPictureCloser.fn = null;
    close();
    return;
  }
  bigPictureExit.on = !on;
  bigPictureArriving.set(on);
  if (!on) bigPictureCovering.set(false);
  bigPicture.set(on);
}
/** Its soft sounds. Off until someone turns them on, then remembered. */
export const bigPictureSound = persisted<boolean>("bigPictureSound", false, true);
/** The app's own sounds (lib/uisound.ts): clicks, ticks and chimes. The speaker at the top right; off silences Big Picture's too. */
export const uiSound = persisted<boolean>("uiSound", true, true);
/** How loud the app's sounds are, 0 to 2: 1 is as they were made, the mark in the middle of the speaker's slider. */
export const uiVolume = persisted<number>("uiVolume", 1);

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
