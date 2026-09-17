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
   to run. The uploaded face is the exception: its URL is only known at runtime,
   so it cannot sit in the stylesheet and is registered here instead. */

export const CUSTOM_FONT_ID = "custom";
const CUSTOM_FAMILY = "PanelCustom";

/**
 * Register the uploaded typeface, or drop it again.
 *
 * `version` busts the cache: the file is served with a long max-age because a
 * replacement changes nothing about its URL otherwise, and the old face would
 * go on being used until the browser felt like revalidating.
 */
export function applyCustomFace(format: string, version: number) {
  if (typeof document === "undefined") return;
  document.getElementById("custom-face")?.remove();
  if (!format) return;
  const style = document.createElement("style");
  style.id = "custom-face";
  style.textContent =
    `@font-face{font-family:"${CUSTOM_FAMILY}";`
    + `src:url("/api/appearance/font?v=${version}") format("${format}");`
    + `font-weight:100 900;font-style:normal;font-display:swap;}`;
  document.head.appendChild(style);
}

export function applyFont(id: string) {
  if (id === CUSTOM_FONT_ID) {
    // Fallbacks still matter: the file can be missing (cleared on another
    // machine) and the panel must stay readable rather than render nothing.
    document.documentElement.style.setProperty(
      "--font-sans",
      `"${CUSTOM_FAMILY}", ui-sans-serif, system-ui, sans-serif`,
    );
    return;
  }
  const choice = FONTS.find((f) => f.id === id) ?? FONTS[0];
  document.documentElement.style.setProperty("--font-sans", choice.stack);
  document.documentElement.dataset.font = choice.id;
}
