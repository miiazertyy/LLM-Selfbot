/**
 * The typefaces the panel can be set in.
 *
 * Mikhak is bundled with the app, so it looks the same on every machine and
 * works with no network. The rest are stacks of faces Windows and macOS
 * already have: shipping four more families would add megabytes to the build
 * for something most people set once.
 */
export type FontChoice = {
  id: string;
  name: string;
  note: string;
  stack: string;
};

export const FONTS: FontChoice[] = [
  {
    id: "mikhak",
    name: "Mikhak",
    note: "Bundled with the app. Soft and geometric.",
    stack: '"Mikhak", ui-sans-serif, system-ui, sans-serif',
  },
  {
    id: "inter",
    name: "Inter",
    note: "What the panel used before. Neutral and dense.",
    stack: '"Inter", ui-sans-serif, system-ui, -apple-system, sans-serif',
  },
  {
    id: "system",
    name: "System",
    note: "Whatever your operating system uses. Sharpest at small sizes.",
    stack: 'system-ui, "Segoe UI Variable Display", "Segoe UI", -apple-system, sans-serif',
  },
  {
    id: "mono",
    name: "Monospace",
    note: "Every character the same width. Good for reading ids and logs.",
    stack: '"Cascadia Code", "JetBrains Mono", "SF Mono", Consolas, ui-monospace, monospace',
  },
];

/* The @font-face rules for the bundled family live in app.css, so the browser
   finds them while parsing the stylesheet instead of waiting for this module
   to run. Nothing to inject here any more. */

export function applyFont(id: string) {
  const choice = FONTS.find((f) => f.id === id) ?? FONTS[0];
  document.documentElement.style.setProperty("--font-sans", choice.stack);
  document.documentElement.dataset.font = choice.id;
}
