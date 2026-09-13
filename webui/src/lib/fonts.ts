/**
 * The typefaces the panel can be set in.
 *
 * Mikhak is bundled with the app, so it looks the same on every machine and
 * works with no network. The rest are stacks of faces Windows and macOS
 * already have: shipping four more families would add megabytes to the build
 * for something most people set once.
 */
import mikhakRegular from "../assets/fonts/Mikhak-Regular.ttf";
import mikhakMedium from "../assets/fonts/Mikhak-Medium.ttf";
import mikhakSemiBold from "../assets/fonts/Mikhak-SemiBold.ttf";
import mikhakBold from "../assets/fonts/Mikhak-Bold.ttf";

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

/**
 * The bundled family, declared once at module load.
 *
 * A stylesheet cannot reference a bundled asset by name, so the URLs come from
 * the bundler and the rule is built here.
 */
let injected = false;

function injectMikhak() {
  if (injected || typeof document === "undefined") return;
  injected = true;
  const faces: [string, number][] = [
    [mikhakRegular, 400],
    [mikhakMedium, 500],
    [mikhakSemiBold, 600],
    [mikhakBold, 700],
  ];
  const css = faces
    .map(
      ([url, weight]) => `@font-face{font-family:"Mikhak";src:url(${url}) format("truetype");`
        + `font-weight:${weight};font-style:normal;font-display:swap;}`,
    )
    .join("");
  const style = document.createElement("style");
  style.id = "mikhak-faces";
  style.textContent = css;
  document.head.appendChild(style);
}

export function applyFont(id: string) {
  injectMikhak();
  const choice = FONTS.find((f) => f.id === id) ?? FONTS[0];
  document.documentElement.style.setProperty("--font-sans", choice.stack);
  document.documentElement.dataset.font = choice.id;
}
