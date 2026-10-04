/**
 * Right-click menus, for the whole app.
 *
 * One menu, mounted once (components/GlobalMenu.svelte), instead of a menu
 * component each page placed and positioned for itself. A right-click
 * anywhere builds the menu from what was clicked, most particular first:
 *
 *   1. what you were doing: selected text (Copy, Search for it), a text box
 *      (Undo, Cut, Copy, Paste, Select all), a link, a picture;
 *   2. what the nearest element that asked for a menu offers: a page puts
 *      `use:menu={() => items}` on a row, a card, a message;
 *   3. and on bare background, the few things the app can always do.
 *
 * The items are asked for at the moment of the click, so they say what is true
 * right then: Start on a stopped account, Stop on a running one.
 *
 * Shift with the right-click still gets the browser's own menu, for anyone
 * inspecting the page.
 */
import { play } from "./uisound";
import { writable } from "svelte/store";
import { toast } from "./stores";

export type MenuAction = {
  label: string;
  icon?: string;
  /** A shortcut shown on the right, e.g. "Ctrl C". Shown only; the menu does not bind it. */
  keys?: string;
  danger?: boolean;
  /** Yellow, for something that is not harmful but takes things away for a moment (Reload). */
  warn?: boolean;
  disabled?: boolean;
  run: () => unknown;
};
/** "sep" draws a line; { title } a small heading; anything falsy is skipped, for `cond && item`. */
export type MenuEntry = MenuAction | "sep" | { title: string } | false | null | undefined | "" | 0;
export type MenuProvider = (e: MouseEvent) => MenuEntry[];

export type MenuState = {
  x: number;
  y: number;
  entries: MenuEntry[];
  /** Opened from the keyboard (the Menu key, Shift+F10): the first item takes the focus. */
  keyboard: boolean;
  /** The text box it was opened on, to give the focus back to before an edit runs. */
  field?: HTMLInputElement | HTMLTextAreaElement | HTMLElement | null;
  n: number;
};

export const menuState = writable<MenuState | null>(null);

let opened = 0;

/** Open the menu at a point, with these entries. For a page that builds its own. */
export function openMenu(x: number, y: number, entries: MenuEntry[], extra: Partial<MenuState> = {}) {
  const shown = tidy(entries);
  if (!shown.length) return;
  menuState.set({ x, y, entries: shown, keyboard: false, ...extra, n: ++opened });
  // A soft pop as it appears (lib/uisound.ts); a right-click with no menu of ours makes none.
  play("menu");
}

/** Open it for a click event, where the click was. The event's own menu is cancelled. */
export function openMenuAt(e: MouseEvent, entries: MenuEntry[]) {
  e.preventDefault();
  e.stopPropagation();
  openMenu(e.clientX, e.clientY, entries);
}

export function closeMenu() {
  menuState.set(null);
}

/**
 * Drop the empty entries, and the lines that would sit at an end, next to
 * another line or under a heading: whatever a page left out, the menu stays
 * tidy without every caller counting separators.
 */
export function tidy(entries: MenuEntry[]): MenuEntry[] {
  const out: MenuEntry[] = [];
  for (const e of entries) {
    if (!e) continue;
    if (e === "sep" && (!out.length || out[out.length - 1] === "sep" || isTitle(out[out.length - 1]))) continue;
    out.push(e);
  }
  while (out.length && (out[out.length - 1] === "sep" || isTitle(out[out.length - 1]))) out.pop();
  return out;
}

export const isAction = (e: MenuEntry): e is MenuAction => !!e && typeof e === "object" && "run" in e;
export const isTitle = (e: MenuEntry): e is { title: string } => !!e && typeof e === "object" && "title" in e;

// ── Asking the page ─────────────────────────────────────────────────────────

const providers = new WeakMap<Element, MenuProvider>();

/**
 * Offer items when this element, or anything inside it, is right-clicked.
 *
 *   <div use:menu={() => [{ label: "Copy", icon: "clipboard", run: copy }]}>
 *
 * Only the nearest element with a menu is asked: a message inside a
 * conversation offers the message's items, not the conversation's as well.
 */
export function menu(node: HTMLElement, provider: MenuProvider) {
  providers.set(node, provider);
  return {
    update(next: MenuProvider) {
      providers.set(node, next);
    },
    destroy() {
      providers.delete(node);
    },
  };
}

/** What the nearest element that offers a menu gives, for this click. */
export function provided(target: Element | null, e: MouseEvent): MenuEntry[] {
  for (let el: Element | null = target; el; el = el.parentElement) {
    const p = providers.get(el);
    if (p) {
      try {
        return p(e);
      } catch {
        return [];
      }
    }
  }
  return [];
}

// ── The clipboard ───────────────────────────────────────────────────────────

/** Copy text, and say so. */
export async function copyText(text: string, said = "Copied.") {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // An older engine, or a page not allowed the clipboard: the old way still works inside a click.
    const t = document.createElement("textarea");
    t.value = text;
    t.style.cssText = "position:fixed;opacity:0;pointer-events:none";
    document.body.appendChild(t);
    t.select();
    const ok = document.execCommand("copy");
    t.remove();
    if (!ok) {
      toast("Could not copy that.", "err");
      return;
    }
  }
  if (said) toast(said, "ok");
}

/**
 * Text from the clipboard. The desktop app reads it through its own window,
 * because the embedded browser asks the person for permission first, in a
 * box that looks like nothing else in the app; a browser asks the way it
 * always does.
 */
export async function readClipboard(): Promise<string | null> {
  const bridge = (window as any).pywebview?.api;
  if (bridge?.read_clipboard_text) {
    try {
      const text = await bridge.read_clipboard_text();
      if (typeof text === "string") return text;
    } catch {
      /* fall through to the page's own clipboard */
    }
  }
  try {
    return await navigator.clipboard.readText();
  } catch {
    return null;
  }
}

// ── Searching for what was selected ─────────────────────────────────────────

/** Ask the search (Ctrl+K) to open, already searching for this. App.svelte listens. */
export const paletteRequest = writable<{ q: string; n: number } | null>(null);
let asked = 0;

export function searchFor(q: string) {
  paletteRequest.set({ q, n: ++asked });
}
