/**
 * Colour themes.
 *
 * Each theme is just a set of CSS custom properties written onto <html>, so
 * every component picks them up without knowing themes exist.
 *
 * Every theme is fully opaque. The window used to offer Windows Mica/Acrylic
 * backdrops, but DWM tints them toward the wallpaper, so they came back bright
 * and inconsistent no matter how the tint was pinned, they are gone, and the
 * app paints its own background.
 */

export type Theme = {
  id: string;
  name: string;
  hint: string;
  vars: Record<string, string>;
};

export const THEMES: Theme[] = [
  {
    id: "midnight",
    name: "Midnight",
    hint: "The original deep indigo",
    vars: {
      "--color-bg": "#0a0a11",
      "--color-surface": "#101019",
      "--color-card": "#16161f",
      "--color-edge": "#23232f",
      "--color-edge-soft": "#1b1b26",
      "--color-ink": "#ececf5",
      "--color-muted": "#8e8ea8",
      "--color-faint": "#5c5c74",
      "--color-accent": "#7c8cff",
      "--color-accent-2": "#4ecdc4",
      "--color-good": "#4ade80",
      "--color-bad": "#f87171",
      "--color-warn": "#fbbf24",
    },
  },
  {
    id: "pastel",
    name: "Dark pastel",
    hint: "Soft muted colour on charcoal",
    vars: {
      "--color-bg": "#16141c",
      "--color-surface": "#1e1b26",
      "--color-card": "#252131",
      "--color-edge": "#332d42",
      "--color-edge-soft": "#2a2537",
      "--color-ink": "#ece7f5",
      "--color-muted": "#a396bb",
      "--color-faint": "#6f6489",
      "--color-accent": "#c3a6ff",
      "--color-accent-2": "#9ee6d4",
      "--color-good": "#a8e6a3",
      "--color-bad": "#ffa8b4",
      "--color-warn": "#ffd9a0",
    },
  },
  {
    id: "moss",
    name: "Moss",
    hint: "Muted green, easy on the eyes",
    vars: {
      "--color-bg": "#0f1412",
      "--color-surface": "#151d19",
      "--color-card": "#1b2620",
      "--color-edge": "#28352d",
      "--color-edge-soft": "#1f2b24",
      "--color-ink": "#e6f0e9",
      "--color-muted": "#93ab9d",
      "--color-faint": "#5f7568",
      "--color-accent": "#7fd7a4",
      "--color-accent-2": "#a8d8ff",
      "--color-good": "#8fe3a8",
      "--color-bad": "#ff9f9f",
      "--color-warn": "#ffd48a",
    },
  },
  {
    id: "ember",
    name: "Ember",
    hint: "Warm charcoal and amber",
    vars: {
      "--color-bg": "#141010",
      "--color-surface": "#1c1615",
      "--color-card": "#241c1a",
      "--color-edge": "#372a27",
      "--color-edge-soft": "#2a211f",
      "--color-ink": "#f4eae6",
      "--color-muted": "#b39a92",
      "--color-faint": "#7a655e",
      "--color-accent": "#ffab7a",
      "--color-accent-2": "#ffd9a0",
      "--color-good": "#a8dda0",
      "--color-bad": "#ff9a8f",
      "--color-warn": "#ffc978",
    },
  },
  {
    id: "sakura",
    name: "Sakura",
    hint: "Dusky plum with warm blossom pink",
    vars: {
      "--color-bg": "#141018",
      "--color-surface": "#1c1622",
      "--color-card": "#241d2c",
      "--color-edge": "#372c42",
      "--color-edge-soft": "#2b2235",
      "--color-ink": "#f3e9f2",
      "--color-muted": "#b298b6",
      "--color-faint": "#7d6683",
      "--color-accent": "#ff9ec4",
      "--color-accent-2": "#c8a6ff",
      "--color-good": "#9fe0c0",
      "--color-bad": "#ff8fa8",
      "--color-warn": "#ffcf94",
    },
  },
  {
    id: "slate",
    name: "Slate",
    hint: "Neutral grey, minimal colour",
    vars: {
      "--color-bg": "#111214",
      "--color-surface": "#191b1e",
      "--color-card": "#202327",
      "--color-edge": "#2e3237",
      "--color-edge-soft": "#24272b",
      "--color-ink": "#e8eaed",
      "--color-muted": "#9aa1a9",
      "--color-faint": "#666e77",
      "--color-accent": "#9ab6d9",
      "--color-accent-2": "#8fd4d0",
      "--color-good": "#84cc9a",
      "--color-bad": "#e28d8d",
      "--color-warn": "#dcb87a",
    },
  },
];

export const DEFAULT_THEME = "midnight";

export function byId(id: string): Theme {
  return THEMES.find((t) => t.id === id) ?? THEMES.find((t) => t.id === DEFAULT_THEME)!;
}

/** Write a theme's variables onto <html>. */
export function applyTheme(id: string): Theme {
  const theme = byId(id);
  const root = document.documentElement;
  for (const [k, v] of Object.entries(theme.vars)) root.style.setProperty(k, v);
  root.dataset.theme = theme.id;
  // Clears any backdrop a previous build left on the window; harmless in a
  // browser, where there is no bridge.
  (window as any).pywebview?.api?.set_backdrop?.("none")?.catch?.(() => {});
  return theme;
}
