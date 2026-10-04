<script lang="ts">
  /**
   * A dropdown that matches the rest of the app.
   *
   * The native <select> draws its closed box with the app's field styling, but
   * the open list is the operating system's own - a bright white menu with
   * system fonts in a dark app. This is the same control drawn all the way
   * down: the trigger, the popup, the options and the tick. It keeps a real
   * keyboard model (arrows, Home/End, type-to-jump, Enter, Escape) so it is no
   * worse to use than the native one, and closes on an outside click or scroll.
   *
   * An option can say more than its name: an icon, a flag, or a badge with its
   * initial (a voice, a person), and a line underneath saying what it means.
   * The chosen one's mark shows on the closed box too. The list springs open
   * from the box, its rows settling in one after another, and one highlight
   * glides from row to row under the pointer or the arrow keys rather than
   * rows lighting up on their own. A long list gets a box to search it.
   *
   * When its tab opens, the value types itself in as its row drops into place
   * (cascade.ts's whenShown), the way a person types it: each letter there at
   * once, the text cursor right against the last one, at an uneven pace, a
   * burst of two now and then and a beat between words. The cursor stays a
   * moment after the last letter, as it would, then goes. Nothing blinks and
   * nothing is left behind. Opening it, or the value changing, ends it at once.
   */
  import { onMount, tick } from "svelte";
  import { get } from "svelte/store";
  import Icon from "./Icon.svelte";
  import { play } from "../uisound";
  import { motionEnabled } from "../stores";
  import { onScreen, whenShown } from "../cascade";
  import { focusStill, showInList } from "../inlist";

  type Option = {
    value: string | number;
    label: string;
    /** A line under the name, saying what picking it does. */
    hint?: string;
    /** One of Icon's names, drawn in a small tile. */
    icon?: string;
    /** A character or two in place of an icon: a flag, an emoji. */
    mark?: string;
    /** A round badge with the name's initial, coloured by the name: for voices and people. */
    badge?: boolean;
  };

  let {
    value = $bindable(),
    options = [],
    onchange,
    placeholder = "Choose",
    width = "",
    size = "md",
  }: {
    value?: string | number;
    options?: Option[];
    onchange?: (v: string | number) => void;
    placeholder?: string;
    /** Extra classes for the trigger, e.g. a fixed width. */
    width?: string;
    size?: "sm" | "md";
  } = $props();

  let open = $state(false);
  let active = $state(0);
  let root: HTMLElement | null = $state(null);
  let menuEl: HTMLElement | null = $state(null);
  /** Where the list goes, worked out from the box as it opens: the list itself lives at the end of <body>. */
  let pos = $state({ left: 0, top: 0, bottom: 0, width: 0 });

  /**
   * The list, drawn at the end of <body>. Left where it was, inside its row, a
   * row's own layer (its arrival animation makes one) painted the rows after
   * it over the open list, chips and all, which read as a list you could see
   * straight through.
   */
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }
  let list: HTMLElement | null = $state(null);
  let searchBox: HTMLInputElement | null = $state(null);
  let up = $state(false);          // opens upward when there is no room below
  let room = $state(300);          // how tall the list may be, to stay on screen
  let query = $state("");

  const selected = $derived(options.find((o) => o.value === value));
  /** Enough options to be worth searching. */
  const searchable = $derived(options.length > 8);
  const shown = $derived.by(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => o.label.toLowerCase().includes(q) || (o.hint ?? "").toLowerCase().includes(q));
  });

  /** A name's own colour, the same every time: its letters, turned into a hue. */
  function hueOf(text: string): number {
    let h = 0;
    for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) % 360;
    return h;
  }

  // ── Typing the value in as the tab opens ───────────────────────────────────
  /** How many letters of the value are showing while it types itself in; null once it has. */
  let typing = $state<number | null>(null);
  const label = $derived(selected?.label ?? "");
  onMount(() => {
    if (!root || !label || !get(motionEnabled)) return;
    typing = 0;
    let alive = true;
    let timer = 0;
    /** Typed where it is seen: each letter a soft key (see uisound's "key"). */
    let heard = false;
    // The whole word in about half a second, however long it is.
    const each = Math.max(28, Math.min(70, 520 / label.length));
    const step = () => {
      if (!alive || typing === null) return;
      if (typing >= label.length) {
        typing = null;          // done: the plain label, no cursor
        return;
      }
      typing += 1;
      if (heard && label[typing - 1] !== " ") play("key");
      if (typing >= label.length) {
        // The last letter: the cursor rests a moment, then the field lets go.
        timer = window.setTimeout(step, 240);
        return;
      }
      // A person's pace, not a metronome's: uneven, now and then two letters
      // in a quick burst, and a small beat after a space.
      let wait = each * (0.6 + Math.random() * 0.8);
      if (Math.random() < 0.25) wait *= 0.35;
      if (label[typing - 1] === " ") wait *= 1.7;
      timer = window.setTimeout(step, wait);
    };
    const el = root;
    whenShown(el).then(() => {
      // A beat before the first letter, as a hand finds the keys.
      if (alive) timer = window.setTimeout(step, 90);
      onScreen(el).then((seen) => (heard = seen));
    });
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  });
  // A value that changes while it is typing (picked, or loaded) just shows.
  let typedFor: string | number | undefined = value;
  $effect(() => {
    if (value !== typedFor) {
      typedFor = value;
      typing = null;
    }
  });

  // ── The highlight that glides ──────────────────────────────────────────────
  let glide = $state({ y: 0, h: 0, on: false, snap: true });
  async function placeGlide() {
    await tick();
    const el = list?.querySelector<HTMLElement>('[data-active="true"]');
    if (!el) {
      glide = { ...glide, on: false };
      return;
    }
    glide = { y: el.offsetTop, h: el.offsetHeight, on: true, snap: !glide.on };
  }
  $effect(() => {
    // Follows the active row, and the list as a search narrows it.
    void active;
    void shown;
    if (open) placeGlide();
  });

  let typed = "";
  let typedAt = 0;

  async function openMenu() {
    play("open");
    typing = null;
    query = "";
    active = Math.max(0, options.findIndex((o) => o.value === value));
    // Enough room below? Otherwise drop upward, and either way never taller
    // than the room there is: rows with a line under the name are taller, and
    // a list sized for plain rows ran off the bottom of the window.
    const r = root?.getBoundingClientRect();
    const rowH = options.some((o) => o.hint) ? 52 : 38;
    const extra = 12 + (options.length > 8 ? 46 : 0);
    const tall = Math.min(300, options.length * rowH) + extra;
    const below = r ? window.innerHeight - r.bottom - 14 : tall;
    const aboveRoom = r ? r.top - 14 : 0;
    up = !!r && below < tall && aboveRoom > below;
    room = Math.max(120, Math.min(300, (up ? aboveRoom : below) - extra));
    if (r) {
      const width = Math.max(r.width, 192);
      pos = { left: Math.max(8, Math.min(r.left, window.innerWidth - width - 8)), width,
              top: r.bottom + 6, bottom: window.innerHeight - r.top + 6 };
    }
    glide = { y: 0, h: 0, on: false, snap: true };
    open = true;
    await tick();
    // The list scrolls to the choice, the page stays where it is (lib/inlist.ts).
    showInList(list, list?.querySelector<HTMLElement>('[data-active="true"]'));
    focusStill(searchBox);
  }

  function close() {
    open = false;
    glide = { ...glide, on: false };
  }

  function choose(o: Option) {
    play("select");
    close();
    if (o.value !== value) {
      value = o.value;
      onchange?.(o.value);
    }
    focusStill(root?.querySelector("button"));
  }

  function onKey(e: KeyboardEvent) {
    if (!open) {
      if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") {
        e.preventDefault();
        openMenu();
      }
      return;
    }
    if (e.key === "Escape") { close(); e.stopPropagation(); focusStill(root?.querySelector("button")); return; }
    if (e.key === "Enter" || (e.key === " " && !searchable)) {
      e.preventDefault();
      if (shown[active]) choose(shown[active]);
      return;
    }
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(shown.length - 1, active + 1); scrollTo(); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); scrollTo(); return; }
    if (e.key === "Home" && !searchable) { e.preventDefault(); active = 0; scrollTo(); return; }
    if (e.key === "End" && !searchable) { e.preventDefault(); active = shown.length - 1; scrollTo(); return; }
    // With a search box, letters go into it; without one, they jump to a name.
    if (!searchable && e.key.length === 1) {
      const now = Date.now();
      typed = now - typedAt > 800 ? e.key : typed + e.key;
      typedAt = now;
      const i = shown.findIndex((o) => o.label.toLowerCase().startsWith(typed.toLowerCase()));
      if (i >= 0) { active = i; scrollTo(); }
    }
  }

  async function scrollTo() {
    await tick();
    showInList(list, list?.querySelector<HTMLElement>('[data-active="true"]'));
  }

  $effect(() => {
    if (!open) return;
    // The list is not inside root any more (it lives at the end of <body>): a click in it is still a click in here.
    const off = (e: MouseEvent) => {
      const t = e.target as Node;
      if (root && !root.contains(t) && !(menuEl && menuEl.contains(t))) close();
    };
    const resize = () => close();
    window.addEventListener("resize", resize);
    const scroll = (e: Event) => { if (list && !list.contains(e.target as Node)) close(); };
    const t = setTimeout(() => {
      window.addEventListener("click", off);
      window.addEventListener("scroll", scroll, true);
    }, 0);
    return () => {
      clearTimeout(t);
      window.removeEventListener("click", off);
      window.removeEventListener("scroll", scroll, true);
      window.removeEventListener("resize", resize);
    };
  });
</script>

{#snippet markOf(o: Option, small: boolean)}
  {#if o.icon}
    <span class="sel-mark is-icon" class:is-small={small}><Icon name={o.icon} size={small ? 12 : 14} /></span>
  {:else if o.mark}
    <span class="sel-mark is-glyph" class:is-small={small}>{o.mark}</span>
  {:else if o.badge}
    <span class="sel-mark is-badge" class:is-small={small} style="--hue: {hueOf(o.label)}">{o.label.charAt(0).toUpperCase()}</span>
  {/if}
{/snippet}

<div class="sel {width}" data-sound="self" bind:this={root}>
  <button
    type="button"
    class="sel-trigger {size === 'sm' ? 'is-sm' : ''}"
    class:is-open={open}
    aria-haspopup="listbox"
    aria-expanded={open}
    onclick={() => (open ? close() : openMenu())}
    onkeydown={onKey}
  >
    {#if selected}{@render markOf(selected, true)}{/if}
    <span class="min-w-0 flex-1 truncate text-left {selected ? '' : 'text-faint'}">
      {#if typing !== null}
        <!-- The letters so far, the newest one fading in, and the cursor after
             them. Screen readers get the whole value, not the animation. -->
        <span class="sr-only">{label}</span>
        <span aria-hidden="true" class="sel-typed">{label.slice(0, typing)}<span class="sel-cursor"></span></span>
      {:else}{selected?.label ?? placeholder}{/if}
    </span>
    <span class="sel-caret" class:is-open={open}><Icon name="chevron" size={13} /></span>
  </button>

  {#if open}
    <div class="sel-menu glass floating" class:is-up={up} bind:this={menuEl} use:portal data-sound="self"
         style="left: {pos.left}px; width: {pos.width}px; {up ? `bottom: ${pos.bottom}px` : `top: ${pos.top}px`}">
      {#if searchable}
        <label class="sel-search">
          <Icon name="search" size={13} />
          <input bind:this={searchBox} bind:value={query} placeholder="Search" aria-label="Search the options"
                 onkeydown={onKey} oninput={() => (active = 0)} />
        </label>
      {/if}
      <div class="sel-list" data-sound="self" role="listbox" bind:this={list} tabindex="-1" style="max-height: {room}px">
        <span class="sel-glide" class:is-on={glide.on} class:is-snap={glide.snap} aria-hidden="true"
              style="transform: translateY({glide.y}px); height: {glide.h}px"></span>
        {#each shown as o, i (o.value)}
          <button
            type="button"
            role="option"
            aria-selected={o.value === value}
            data-active={i === active}
            class="sel-opt"
            class:is-active={i === active}
            class:is-picked={o.value === value}
            style="--i: {Math.min(i, 10)}"
            onmouseenter={() => (active = i)}
            onclick={() => choose(o)}
          >
            {@render markOf(o, false)}
            <span class="min-w-0 flex-1">
              <span class="sel-opt-label">{o.label}</span>
              {#if o.hint}<span class="sel-opt-hint">{o.hint}</span>{/if}
            </span>
            {#if o.value === value}<span class="sel-tick"><Icon name="check" size={13} /></span>{/if}
          </button>
        {:else}
          <p class="sel-none">Nothing matches.</p>
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  .sel {
    position: relative;
    display: inline-block;
  }
  .sel-trigger {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 8px;
    padding: 7px 10px 7px 12px;
    border-radius: 11px;
    border: 1px solid var(--color-edge);
    background:
      linear-gradient(180deg, rgb(255 255 255 / 0.035), transparent 70%),
      rgb(0 0 0 / 0.22);
    font-size: 13px;
    color: var(--color-ink);
    transition: border-color 0.16s var(--swift), box-shadow 0.16s var(--swift), background-color 0.16s var(--swift);
  }
  .sel-trigger.is-sm { padding: 5px 8px 5px 10px; font-size: 12px; }
  .sel-trigger:has(.sel-mark) { padding-left: 7px; }
  .sel-trigger:hover { border-color: color-mix(in srgb, var(--color-accent) 40%, var(--color-edge)); }
  .sel-trigger.is-open,
  .sel-trigger:focus-visible {
    outline: none;
    border-color: color-mix(in srgb, var(--color-accent) 60%, transparent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 14%, transparent);
  }

  /* Typing the value in: letters appear whole, as typed ones do, and a text
     cursor sits right against the last one, thin and in the text's colour,
     the way a real one looks. A letter that faded in took its room while it
     was still invisible, which left a gap before the cursor. Its own class
     names: the chevron's is .sel-caret, and sharing it once turned the
     chevron into a blinking bar. */
  .sel-typed { white-space: pre; }
  .sel-cursor {
    display: inline-block;
    width: 1.5px;
    height: 1.15em;
    margin-left: 0.5px;
    vertical-align: -0.22em;
    border-radius: 1px;
    background: var(--color-ink);
  }

  /* The chevron is a right-pointing arrow; a quarter turn makes it point down
     when closed and up when open, the way a dropdown caret should. */
  .sel-caret {
    display: inline-flex;
    flex-shrink: 0;
    color: var(--color-faint);
    transform: rotate(90deg);
    transition: transform 0.2s var(--spring), color 0.16s ease;
  }
  .sel-caret.is-open { transform: rotate(-90deg); color: var(--color-accent); }

  /* ── An option's mark: an icon tile, a flag, or a name's badge ───────────── */
  .sel-mark {
    display: inline-grid;
    width: 26px;
    height: 26px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 8px;
    font-size: 13px;
    line-height: 1;
  }
  .sel-mark.is-small { width: 20px; height: 20px; border-radius: 6px; font-size: 11.5px; }
  .sel-mark.is-icon {
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 13%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 18%, transparent);
  }
  .sel-mark.is-glyph {
    font-family: "Twemoji Country Flags", var(--font-sans, inherit);
    font-size: 16px;
    background: rgb(255 255 255 / 0.05);
  }
  .sel-mark.is-glyph.is-small { font-size: 13px; }
  .sel-mark.is-badge {
    border-radius: 999px;
    font-weight: 700;
    color: hsl(var(--hue) 80% 86%);
    background: linear-gradient(145deg, hsl(var(--hue) 62% 46%), hsl(calc(var(--hue) + 40) 58% 32%));
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 0.18), 0 2px 6px -2px hsl(var(--hue) 70% 30% / 0.8);
  }

  /* ── The list ───────────────────────────────────────────────────────────── */
  .sel-menu {
    position: fixed;
    min-width: 12rem;
    z-index: 1000;
    padding: 5px;
    border-radius: 14px;
    box-shadow: 0 22px 50px -20px rgb(0 0 0 / 0.75), inset 0 0 0 1px rgb(255 255 255 / 0.05);
    transform-origin: top;
    animation: sel-in 0.24s var(--spring) both;
  }
  .sel-menu.is-up {
    transform-origin: bottom;
    animation-name: sel-in-up;
  }
  @keyframes sel-in {
    from { opacity: 0; transform: translateY(-6px) scale(0.96); }
    to { opacity: 1; transform: none; }
  }
  @keyframes sel-in-up {
    from { opacity: 0; transform: translateY(6px) scale(0.96); }
    to { opacity: 1; transform: none; }
  }

  .sel-search {
    display: flex;
    align-items: center;
    gap: 7px;
    margin: 1px 1px 5px;
    padding: 7px 10px;
    border-radius: 10px;
    color: var(--color-faint);
    background: rgb(0 0 0 / 0.22);
    box-shadow: inset 0 0 0 1px var(--color-edge);
  }
  .sel-search:focus-within { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 55%, transparent); }
  .sel-search input {
    min-width: 0;
    flex: 1;
    background: transparent;
    font-size: 12.5px;
    color: var(--color-ink);
    outline: none;
  }

  .sel-list {
    position: relative;
    max-height: min(300px, 60vh);
    overflow-y: auto;
    overscroll-behavior: contain;
  }
  /* One highlight for the whole list, gliding to whichever row is active. */
  .sel-glide {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    border-radius: 10px;
    pointer-events: none;
    opacity: 0;
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 20%, transparent);
    transition: transform 0.26s var(--spring), height 0.2s var(--swift), opacity 0.15s ease;
  }
  .sel-glide.is-on { opacity: 1; }
  .sel-glide.is-snap { transition: opacity 0.15s ease; }

  .sel-opt {
    position: relative;
    display: flex;
    width: 100%;
    align-items: center;
    gap: 10px;
    padding: 7px 9px;
    border-radius: 10px;
    font-size: 13px;
    color: var(--color-ink);
    text-align: left;
    animation: sel-row 0.26s var(--swift) calc(var(--i, 0) * 18ms) both;
  }
  @keyframes sel-row {
    from { opacity: 0; transform: translateY(-4px); }
    to { opacity: 1; transform: none; }
  }
  .sel-opt-label {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 500;
    transition: transform 0.2s var(--spring);
  }
  .sel-opt.is-active .sel-opt-label { transform: translateX(2px); }
  .sel-opt-hint {
    display: block;
    margin-top: 1px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 11px;
    color: var(--color-faint);
  }
  .sel-opt.is-picked .sel-opt-label { color: var(--color-accent); }
  .sel-tick {
    display: inline-flex;
    flex-shrink: 0;
    color: var(--color-accent);
    animation: sel-tick 0.3s var(--jelly) both;
  }
  @keyframes sel-tick {
    from { opacity: 0; transform: scale(0.4); }
    to { opacity: 1; transform: none; }
  }
  .sel-none {
    padding: 14px 10px;
    text-align: center;
    font-size: 12px;
    color: var(--color-faint);
  }

  :global(:root[data-motion="off"]) .sel-menu,
  :global(:root[data-motion="off"]) .sel-opt,
  :global(:root[data-motion="off"]) .sel-tick { animation: none; }
  :global(:root[data-motion="off"]) .sel-caret,
  :global(:root[data-motion="off"]) .sel-glide,
  :global(:root[data-motion="off"]) .sel-opt-label { transition: none; }
</style>
