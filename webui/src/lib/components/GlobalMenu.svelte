<script lang="ts">
  /**
   * The one right-click menu. lib/contextmenu.ts says how its items are
   * gathered; this listens for the right-click, draws the menu and runs what
   * is picked.
   *
   * It opens from the pointer with a small spring and the items settle in one
   * after another, and closes with a quick fade: it stays drawn for the length
   * of that fade after it has been closed. Near an edge it opens the other
   * way, left of the pointer or above it, and grows from that corner, so it is
   * never cut off and never jumps. It is compact: the rows are 30px, the text
   * 12.5px, with the shortcut in faint type on the right.
   *
   * Keyboard: the Menu key or Shift+F10 opens it on whatever has the focus,
   * the arrows move, Enter picks, Escape closes, and a letter jumps to the
   * next item starting with it. Picking something in a text box acts on that
   * box: the menu never takes the focus from it when opened with the mouse.
   *
   * No full-screen layer behind it: a click elsewhere closes it and still
   * reaches what was clicked, and a right-click elsewhere opens a new menu
   * there instead of just closing this one.
   */
  import { onMount, tick } from "svelte";
  import Icon from "./Icon.svelte";
  import { play } from "../uisound";
  import {
    menuState, closeMenu, openMenu, provided, tidy, isAction, isTitle, copyText, readClipboard, searchFor,
    type MenuAction, type MenuEntry, type MenuState,
  } from "../contextmenu";
  import { bigPicture, motionEnabled, setBigPicture, toast } from "../stores";
  import { copyImageFrom } from "../imagecopy";
  import { saveUrlAs } from "../window";

  /** What is drawn. Kept through the closing fade after the menu itself is closed. */
  let shown = $state<MenuState | null>(null);
  let leaving = $state(false);
  let el = $state<HTMLDivElement | null>(null);
  let pos = $state({ left: 0, top: 0, ox: "left", oy: "top", ready: false });
  let active = $state(-1);
  let leaveTimer: ReturnType<typeof setTimeout> | null = null;
  /** Where the focus was before a keyboard-opened menu took it, to give it back. */
  let returnTo: HTMLElement | null = null;

  const LEAVE_MS = 120;

  /** Show what the store says: a new menu straight away, a closed one after its fade. */
  function follow(s: MenuState | null) {
    if (leaveTimer) clearTimeout(leaveTimer);
    leaveTimer = null;
    if (s) {
      leaving = false;
      shown = s;
      pos = { ...pos, ready: false };
      active = s.keyboard ? step(-1, 1) : -1;
      place();
    } else if (shown) {
      leaving = true;
      leaveTimer = setTimeout(() => {
        shown = null;
        leaving = false;
      }, $motionEnabled ? LEAVE_MS : 0);
      if (returnTo) {
        returnTo.focus?.({ preventScroll: true });
        returnTo = null;
      }
    }
  }

  /** Put it by the pointer, the other way round where it would run off the window. */
  async function place() {
    await tick();
    if (!el || !shown) return;
    const m = 8;
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    let { x, y } = shown;
    let ox = "left";
    let oy = "top";
    if (x + w > innerWidth - m) {
      x = Math.max(m, x - w);
      ox = "right";
    }
    if (y + h > innerHeight - m) {
      y = Math.max(m, y - h);
      oy = "bottom";
    }
    pos = { left: Math.round(x), top: Math.round(y), ox, oy, ready: true };
    if (shown.keyboard) el.focus({ preventScroll: true });
  }

  // ── Moving through it ────────────────────────────────────────────────────
  const entries = $derived(shown?.entries ?? []);
  const usable = (i: number) => {
    const e = entries[i];
    return isAction(e) && !e.disabled;
  };

  /** The next usable item from `from`, going `dir`, wrapping round. */
  function step(from: number, dir: 1 | -1): number {
    const n = shown?.entries.length ?? 0;
    const list = shown?.entries ?? [];
    for (let k = 1; k <= n; k++) {
      const i = (((from + dir * k) % n) + n) % n;
      const e = list[i];
      if (isAction(e) && !e.disabled) return i;
    }
    return -1;
  }

  /** The order an item animates in: actions only, capped so a long menu does not crawl. */
  function order(i: number): number {
    let k = 0;
    for (let j = 0; j < i; j++) if (entries[j] !== "sep") k++;
    return Math.min(k, 10);
  }

  async function run(entry: MenuAction) {
    if (entry.disabled) return;
    play("select");
    const field = shown?.field;
    closeMenu();
    // Back to the box it was opened on, with its selection, before an edit acts on it.
    if (field && document.activeElement !== field) field.focus({ preventScroll: true });
    try {
      await entry.run();
    } catch (e: any) {
      toast(e?.message || "That did not work", "err");
    }
  }

  function onKey(e: KeyboardEvent) {
    if (!shown || leaving) return;
    const k = e.key;
    if (k === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      closeMenu();
    } else if (k === "ArrowDown" || k === "ArrowUp") {
      e.preventDefault();
      e.stopPropagation();
      active = step(active < 0 && k === "ArrowUp" ? 0 : active, k === "ArrowDown" ? 1 : -1);
    } else if (k === "Home" || k === "End") {
      e.preventDefault();
      e.stopPropagation();
      active = k === "Home" ? step(-1, 1) : step(0, -1);
    } else if (k === "Enter" || (k === " " && active >= 0)) {
      if (active < 0) return;
      e.preventDefault();
      e.stopPropagation();
      const entry = entries[active];
      if (isAction(entry)) run(entry);
    } else if (k === "Tab") {
      closeMenu();
    } else if (k.length === 1 && /\S/.test(k) && !e.ctrlKey && !e.metaKey && !e.altKey) {
      // A letter jumps to the next item that starts with it.
      const n = entries.length;
      for (let j = 1; j <= n; j++) {
        const i = (active + j + n) % n;
        const entry = entries[i];
        if (isAction(entry) && !entry.disabled && entry.label.toLowerCase().startsWith(k.toLowerCase())) {
          e.preventDefault();
          e.stopPropagation();
          active = i;
          break;
        }
      }
    }
  }

  // ── What was clicked ─────────────────────────────────────────────────────
  const TEXT_TYPES = new Set(["text", "search", "url", "email", "tel", "password", "number"]);

  function fieldOf(t: Element): HTMLInputElement | HTMLTextAreaElement | HTMLElement | null {
    const f = t.closest("input, textarea, [contenteditable]");
    if (f instanceof HTMLInputElement) return TEXT_TYPES.has(f.type) ? f : null;
    if (f instanceof HTMLTextAreaElement) return f;
    if (f instanceof HTMLElement && f.isContentEditable) return f;
    return null;
  }

  function hasSelection(f: HTMLElement): boolean {
    if (f instanceof HTMLInputElement || f instanceof HTMLTextAreaElement) {
      try {
        return f.selectionStart !== null && f.selectionStart !== f.selectionEnd;
      } catch {
        return true;
      }
    }
    return !!window.getSelection()?.toString();
  }

  /** A text box: the usual edits, acting on the box itself. */
  function editItems(f: HTMLInputElement | HTMLTextAreaElement | HTMLElement): MenuEntry[] {
    const locked = (f as HTMLInputElement).readOnly || (f as HTMLInputElement).disabled;
    const secret = f instanceof HTMLInputElement && f.type === "password";
    const sel = hasSelection(f);
    return [
      { label: "Undo", icon: "undo", keys: "Ctrl Z", disabled: locked, run: () => document.execCommand("undo") },
      "sep",
      { label: "Cut", icon: "cut", keys: "Ctrl X", disabled: locked || secret || !sel, run: () => document.execCommand("cut") },
      { label: "Copy", icon: "copy", keys: "Ctrl C", disabled: secret || !sel, run: () => document.execCommand("copy") },
      {
        label: "Paste", icon: "clipboard", keys: "Ctrl V", disabled: locked,
        run: async () => {
          const text = await readClipboard();
          if (text === null) return toast("Press Ctrl+V to paste here.", "info");
          if (!text) return toast("There is no text to paste.", "info");
          f.focus({ preventScroll: true });
          document.execCommand("insertText", false, text);
        },
      },
      "sep",
      {
        label: "Select all", icon: "selectall", keys: "Ctrl A",
        run: () => (f instanceof HTMLInputElement || f instanceof HTMLTextAreaElement ? f.select() : document.execCommand("selectAll")),
      },
    ];
  }

  function short(text: string, n = 22): string {
    const t = text.replace(/\s+/g, " ").trim();
    return t.length > n ? t.slice(0, n - 1).trimEnd() + "…" : t;
  }

  /** Text selected where the pointer is: what was being done, so it comes first. */
  function selectionItems(t: Element): MenuEntry[] {
    const sel = window.getSelection();
    const text = sel && !sel.isCollapsed && sel.containsNode(t, true) ? sel.toString().trim() : "";
    if (!text) return [];
    return [
      { label: "Copy", icon: "copy", keys: "Ctrl C", run: () => copyText(text) },
      { label: `Search for “${short(text)}”`, icon: "search", run: () => searchFor(text.slice(0, 120)) },
    ];
  }

  /** What the thing under the pointer is: a link, a picture. */
  function thingItems(t: Element): MenuEntry[] {
    const out: MenuEntry[] = [];
    const link = t.closest("a[href]");
    if (link instanceof HTMLAnchorElement && !link.hasAttribute("download")) {
      const href = link.href;
      out.push(
        { label: "Open link", icon: "external", run: () => link.click() },
        /^https?:/.test(href) && { label: "Copy link", icon: "link", run: () => copyText(href, "Copied the link.") },
        "sep",
      );
    }
    const img = t.closest("img");
    // Pictures, not the little marks: a logo or an icon has nothing worth copying.
    if (img instanceof HTMLImageElement && img.currentSrc && img.width >= 40 && img.height >= 40) {
      const src = img.currentSrc;
      const name = (img.alt || src.split("/").pop()?.split("?")[0] || "picture").replace(/\.\w{2,5}$/, "");
      out.push(
        { label: "Copy image", icon: "copy", run: () => copyImageFrom(src).then(() => toast("Copied the picture.", "ok")) },
        { label: "Save image as…", icon: "download", run: () => saveUrlAs(src, name).then((w) => w && toast("Saved.", "ok")) },
        "sep",
      );
    }
    return out;
  }

  /** On bare background: what the app can always do. */
  function appItems(): MenuEntry[] {
    const inBig = $bigPicture;
    return [
      { label: "Search", icon: "search", keys: "Ctrl K", run: () => searchFor("") },
      inBig
        ? { label: "Leave Big Picture", icon: "collapse", keys: "Esc", run: () => setBigPicture(false) }
        : { label: "Big Picture Mode", icon: "bigpicture", keys: "Ctrl Shift B", run: () => setBigPicture(true) },
      "sep",
      { label: "Reload", icon: "refresh", keys: "Ctrl R", warn: true, run: () => location.reload() },
    ];
  }

  /** The same item from two places (a picture that is also a page's avatar) once, the page's. */
  function dedupe(first: MenuEntry[], then: MenuEntry[]): MenuEntry[] {
    const taken = new Set(first.filter(isAction).map((a) => a.label));
    return then.filter((e) => !isAction(e) || !taken.has(e.label));
  }

  function onContext(e: MouseEvent) {
    // A page that opened its own menu for this click, and Shift for the browser's.
    if (e.defaultPrevented || e.shiftKey) return;
    const t = e.target instanceof Element ? e.target : null;
    if (!t || t.closest("[data-native-menu]")) return;
    // The Menu key and Shift+F10 fire this too, at the focused element and with no pointer.
    const keyboard = (e as PointerEvent).pointerType === "" || (e.clientX === 0 && e.clientY === 0 && e.detail === 0);
    let x = e.clientX;
    let y = e.clientY;
    if (keyboard) {
      const r = (document.activeElement instanceof Element ? document.activeElement : t).getBoundingClientRect();
      x = r.left + Math.min(24, r.width / 2);
      y = r.bottom + 4;
    }

    const field = fieldOf(t);
    let entries: MenuEntry[];
    if (field) {
      entries = editItems(field);
    } else {
      const picked = selectionItems(t);
      const own = dedupe(picked, tidy(provided(t, e)));
      entries = [...picked, "sep", ...own, "sep", ...dedupe([...picked, ...own], thingItems(t))];
      if (!tidy(entries).length) entries = appItems();
    }
    e.preventDefault();
    if (keyboard && document.activeElement instanceof HTMLElement) returnTo = document.activeElement;
    openMenu(x, y, entries, { keyboard, field });
  }

  function away(e: PointerEvent) {
    if (shown && !leaving && el && !el.contains(e.target as Node)) closeMenu();
  }
  const quietly = () => shown && !leaving && closeMenu();

  onMount(() => {
    // Subscribed here, not in an effect: an effect would track `shown`, which this sets.
    const stop = menuState.subscribe(follow);
    window.addEventListener("contextmenu", onContext);
    window.addEventListener("pointerdown", away, true);
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("wheel", quietly, { capture: true, passive: true });
    window.addEventListener("resize", quietly);
    window.addEventListener("blur", quietly);
    window.addEventListener("hashchange", quietly);
    return () => {
      stop();
      window.removeEventListener("contextmenu", onContext);
      window.removeEventListener("pointerdown", away, true);
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("wheel", quietly, { capture: true });
      window.removeEventListener("resize", quietly);
      window.removeEventListener("blur", quietly);
      window.removeEventListener("hashchange", quietly);
      if (leaveTimer) clearTimeout(leaveTimer);
    };
  });
</script>

{#if shown}
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div
    bind:this={el}
    class="gm float-surface"
    data-sound="self"
    class:is-ready={pos.ready}
    class:is-leaving={leaving}
    class:is-up={pos.oy === "bottom"}
    style="left: {pos.left}px; top: {pos.top}px; transform-origin: {pos.ox} {pos.oy};"
    role="menu"
    tabindex="-1"
    aria-orientation="vertical"
    aria-activedescendant={active >= 0 ? `gm-${shown.n}-${active}` : undefined}
    onmousedown={(e) => e.preventDefault()}
    oncontextmenu={(e) => e.preventDefault()}
  >
    {#each entries as entry, i (i)}
      {#if entry === "sep"}
        <div class="gm-sep" role="separator"></div>
      {:else if isTitle(entry)}
        <div class="gm-title" role="presentation">{entry.title}</div>
      {:else if isAction(entry)}
        <button
          id="gm-{shown.n}-{i}"
          class="gm-item"
          class:is-active={active === i}
          class:is-danger={entry.danger}
          class:is-warn={entry.warn && !entry.danger}
          role="menuitem"
          tabindex="-1"
          disabled={entry.disabled}
          aria-disabled={entry.disabled || undefined}
          style="--i: {order(i)}"
          onpointermove={() => { if (usable(i) && active !== i) active = i; }}
          onpointerleave={() => { if (active === i) active = -1; }}
          onclick={() => run(entry)}
        >
          <span class="gm-icon" aria-hidden="true">{#if entry.icon}<Icon name={entry.icon} size={14} />{/if}</span>
          <span class="gm-label">{entry.label}</span>
          {#if entry.keys}<span class="gm-keys" aria-hidden="true">{entry.keys}</span>{/if}
        </button>
      {/if}
    {/each}
  </div>
{/if}

<style>
  .gm {
    position: fixed;
    z-index: 300;
    display: flex;
    min-width: 188px;
    max-width: 290px;
    flex-direction: column;
    padding: 4px;
    border-radius: 12px;
    background: color-mix(in srgb, var(--color-card) 90%, transparent);
    -webkit-backdrop-filter: blur(20px) saturate(1.4);
    backdrop-filter: blur(20px) saturate(1.4);
    box-shadow:
      0 0 0 1px color-mix(in srgb, var(--color-edge) 85%, transparent),
      inset 0 1px 0 rgb(255 255 255 / 0.05),
      0 14px 34px -10px rgb(0 0 0 / 0.6),
      0 3px 8px rgb(0 0 0 / 0.22);
    outline: none;
    user-select: none;
    /* Measured before it shows, so it never flashes up in the wrong place. */
    visibility: hidden;
  }
  .gm.is-ready {
    visibility: visible;
    animation: gm-in 0.24s var(--jelly) both;
  }
  .gm.is-leaving {
    pointer-events: none;
    animation: gm-out 0.12s var(--swift) both;
  }
  @keyframes gm-in {
    from { opacity: 0; transform: translateY(-5px) scale(0.9); }
  }
  .gm.is-up.is-ready { animation-name: gm-in-up; }
  @keyframes gm-in-up {
    from { opacity: 0; transform: translateY(5px) scale(0.9); }
  }
  @keyframes gm-out {
    to { opacity: 0; transform: scale(0.96); }
  }

  .gm-item {
    display: flex;
    width: 100%;
    height: 30px;
    flex-shrink: 0;
    align-items: center;
    gap: 9px;
    padding: 0 10px 0 8px;
    border-radius: 8px;
    font-size: 12.5px;
    text-align: left;
    color: var(--color-ink);
    white-space: nowrap;
    transition: background-color 0.12s ease, color 0.12s ease;
  }
  .gm.is-ready .gm-item {
    animation: gm-item-in 0.26s var(--swift) both;
    animation-delay: calc(var(--i) * 16ms + 30ms);
  }
  @keyframes gm-item-in {
    from { opacity: 0; transform: translateX(-4px); }
  }
  .gm-icon {
    display: grid;
    width: 16px;
    flex-shrink: 0;
    place-items: center;
    color: var(--color-muted);
    transition: color 0.12s ease, transform 0.3s var(--jelly);
  }
  .gm-label { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; }
  .gm-keys {
    flex-shrink: 0;
    padding-left: 16px;
    font-size: 10.5px;
    letter-spacing: 0.02em;
    color: var(--color-faint);
  }
  .gm-item.is-active {
    background: color-mix(in srgb, var(--color-accent) 16%, transparent);
  }
  .gm-item.is-active .gm-icon { color: var(--color-accent); transform: scale(1.1); }
  .gm-item.is-danger,
  .gm-item.is-danger .gm-icon { color: var(--color-bad); }
  .gm-item.is-danger.is-active { background: color-mix(in srgb, var(--color-bad) 15%, transparent); }
  .gm-item.is-warn,
  .gm-item.is-warn .gm-icon { color: var(--color-warn); }
  .gm-item.is-warn.is-active { background: color-mix(in srgb, var(--color-warn) 15%, transparent); }
  .gm-item:disabled { cursor: default; opacity: 0.38; }
  .gm-item:active:not(:disabled) { transform: scale(0.98); }

  .gm-sep {
    height: 1px;
    flex-shrink: 0;
    margin: 4px 8px;
    background: color-mix(in srgb, var(--color-edge) 80%, transparent);
  }
  .gm-title {
    overflow: hidden;
    padding: 6px 10px 3px;
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-overflow: ellipsis;
    text-transform: uppercase;
    white-space: nowrap;
    color: var(--color-faint);
  }

  :global(:root[data-motion="off"]) .gm,
  :global(:root[data-motion="off"]) .gm-item,
  :global(:root[data-motion="off"]) .gm-icon { animation: none !important; transition: none; }
</style>
