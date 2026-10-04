<script lang="ts">
  /**
   * Browse and pick emoji, instead of pasting them in.
   *
   * The categories are a row of their own emoji with a pill gliding under the
   * one open, rather than nine words that wrapped onto a second line; the ones
   * used lately come first. Opening one, its emoji pop in one after another,
   * quickly, a dry tick each (lib/domino.ts); the one under the pointer is shown
   * big at the foot with its name. Rendered as a plain grid rather than a
   * virtualised list: only one category is on screen at a time, a few hundred
   * at most. Search can match across every group, so that path is capped.
   */
  import { EMOJI_GROUPS, EMOJI_ALL, type EmojiEntry } from "../emoji";
  import { domino } from "../domino";
  import { burst } from "../burst";
  import { play } from "../uisound";
  import Icon from "./Icon.svelte";

  let { chosen = [], full = false, onpick } = $props<{
    /** Already-picked emoji, shown ticked so the grid reflects the set. */
    chosen?: string[];
    /** True when no more will be accepted; picking an existing one still works. */
    full?: boolean;
    onpick: (emoji: string) => void;
  }>();

  /** Each category as its own emoji, for the row along the top. */
  const MARK: Record<string, string> = {
    Recent: "🕘", Smileys: "😀", People: "👋", Nature: "🌿", Food: "🍔", Activity: "⚽", Travel: "✈️",
    Objects: "💡", Symbols: "💜", Flags: "🏁",
  };
  const NAMES = new Map(EMOJI_ALL);

  // ── Used lately, kept on this computer ──────────────────────────────────
  const RECENT_KEY = "emoji.recent";
  function readRecent(): string[] {
    try {
      const v = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
      return Array.isArray(v) ? v.filter((x) => typeof x === "string").slice(0, 27) : [];
    } catch {
      return [];
    }
  }
  let recent = $state<string[]>(readRecent());
  function remember(ch: string) {
    recent = [ch, ...recent.filter((x) => x !== ch)].slice(0, 27);
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(recent)); } catch { /* private window */ }
  }

  const groups = $derived([
    ...(recent.length ? [{ name: "Recent", items: recent.map((ch): EmojiEntry => [ch, NAMES.get(ch) ?? ""]) }] : []),
    ...EMOJI_GROUPS,
  ]);
  let group = $state(readRecent().length ? "Recent" : (EMOJI_GROUPS[0]?.name ?? ""));
  let query = $state("");
  /** One beat behind: matching runs over every emoji there is. */
  let q = $state("");
  $effect(() => {
    const v = query;
    const t = setTimeout(() => { q = v.trim().toLowerCase(); }, 120);
    return () => clearTimeout(t);
  });

  const SEARCH_LIMIT = 240;

  const shown = $derived.by((): EmojiEntry[] => {
    if (q) {
      const out: EmojiEntry[] = [];
      for (const [ch, name] of EMOJI_ALL) {
        if (name.includes(q)) {
          out.push([ch, name]);
          if (out.length >= SEARCH_LIMIT) break;
        }
      }
      return out;
    }
    return groups.find((g) => g.name === group)?.items ?? [];
  });

  const has = (e: string) => chosen.includes(e);

  // ── The category row and its gliding pill ────────────────────────────────
  let tabs: HTMLElement | null = $state(null);
  let pill = $state({ left: 0, width: 0, ready: false });
  /** Which way the grid comes in: from the right going forward along the row, from the left going back. */
  let dir = $state(1);
  function place() {
    const b = tabs?.querySelector<HTMLElement>(".ep-tab.is-on");
    if (b) pill = { left: b.offsetLeft, width: b.offsetWidth, ready: true };
  }
  $effect(() => {
    group;
    groups.length;
    requestAnimationFrame(place);
  });
  function choose(name: string) {
    if (name === group) return;
    const at = (n: string) => groups.findIndex((g) => g.name === n);
    dir = at(name) > at(group) ? 1 : -1;
    play("tick", { p: Math.max(0, at(name)) / Math.max(1, groups.length - 1) });
    group = name;
  }

  let hovered = $state<EmojiEntry | null>(null);

  function pick(ch: string, e: MouseEvent) {
    remember(ch);
    burst(ch, e.currentTarget as Element);
    onpick(ch);
  }
</script>

<div class="ep">
  <label class="ep-search">
    <Icon name="search" size={13} />
    <input bind:value={query} placeholder="Search {EMOJI_ALL.length} emoji" spellcheck="false" />
    {#if query}
      <button type="button" class="ep-clear" onclick={() => (query = "")} aria-label="Clear the search">
        <Icon name="close" size={11} />
      </button>
    {/if}
  </label>

  {#if !q}
    <div class="ep-tabs" bind:this={tabs} role="tablist" aria-label="Kinds of emoji">
      <span class="ep-pill" class:is-ready={pill.ready} style="transform: translateX({pill.left}px); width: {pill.width}px"></span>
      {#each groups as g (g.name)}
        <button type="button" class="ep-tab" class:is-on={g.name === group} role="tab" aria-selected={g.name === group}
                title={g.name} aria-label={g.name} data-sound="self" onclick={() => choose(g.name)}>
          {MARK[g.name] ?? "✨"}
        </button>
      {/each}
    </div>
  {/if}

  <div class="ep-head">
    {#if q}{shown.length >= SEARCH_LIMIT ? `The first ${SEARCH_LIMIT}` : `${shown.length} found`}{:else}{group}{/if}
  </div>

  <div class="ep-scroll">
    {#if shown.length === 0}
      <p class="ep-none"><span>🤷</span>Nothing matches that.</p>
    {:else}
      {#key `${group}|${q}`}
        <div class="ep-grid domino" style="--ep-from: {dir * 10}px"
             use:domino={{ step: 7, max: 48, sound: "wind", level: 0.35, once: true }}>
          {#each shown as [ch, name] (ch)}
            <button
              type="button"
              class="ep-e"
              class:is-on={has(ch)}
              title={name}
              aria-label={name}
              aria-pressed={has(ch)}
              disabled={full && !has(ch)}
              onpointerenter={() => (hovered = [ch, name])}
              onfocus={() => (hovered = [ch, name])}
              onclick={(e) => pick(ch, e)}
            >{ch}</button>
          {/each}
        </div>
      {/key}
    {/if}
  </div>

  <div class="ep-foot" aria-live="polite">
    {#if hovered}
      {#key hovered[0]}<span class="ep-big">{hovered[0]}</span>{/key}
      <span class="ep-name">{hovered[1]}</span>
    {:else}
      <span class="ep-name is-hint">Hover one to see its name</span>
    {/if}
  </div>
</div>

<style>
  .ep {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border-radius: 16px;
    background: rgb(0 0 0 / 0.22);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
  }
  .ep-search {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 8px 8px 0;
    padding: 0 6px 0 11px;
    height: 34px;
    border-radius: 11px;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    transition: box-shadow 0.15s ease, color 0.15s ease;
  }
  .ep-search:focus-within {
    color: var(--color-accent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, transparent),
                0 0 0 3px color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .ep-search input {
    flex: 1;
    min-width: 0;
    font-size: 12.5px;
    color: var(--color-ink);
    background: transparent;
    outline: none;
  }
  .ep-search input::placeholder { color: var(--color-faint); }
  .ep-clear {
    display: grid;
    place-items: center;
    width: 22px;
    height: 22px;
    border-radius: 999px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.06);
    animation: ep-pop 0.3s var(--jelly);
  }
  .ep-clear:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.12); }

  /* The categories: their own emoji in one row, a pill gliding under the open one. */
  .ep-tabs {
    position: relative;
    display: flex;
    justify-content: space-between;
    margin: 8px 8px 0;
    padding: 3px;
    border-radius: 12px;
    background: rgb(255 255 255 / 0.03);
  }
  .ep-pill {
    position: absolute;
    top: 3px;
    bottom: 3px;
    left: 0;
    border-radius: 9px;
    background: color-mix(in srgb, var(--color-accent) 22%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 45%, transparent),
                0 4px 14px -6px var(--color-accent);
    opacity: 0;
  }
  .ep-pill.is-ready { opacity: 1; transition: transform 0.42s var(--jelly), width 0.42s var(--jelly); }
  .ep-tab {
    position: relative;
    display: grid;
    place-items: center;
    flex: 1;
    height: 30px;
    font-size: 17px;
    line-height: 1;
    filter: grayscale(0.85) opacity(0.6);
    transition: filter 0.2s ease, transform 0.35s var(--jelly);
  }
  .ep-tab:hover { filter: none; transform: translateY(-1px) scale(1.12); }
  .ep-tab.is-on { filter: none; transform: scale(1.12); }
  .ep-tab:active { transform: scale(0.9); }

  .ep-head {
    margin: 8px 12px 2px;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--color-faint);
  }
  .ep-scroll { max-height: 220px; overflow-y: auto; padding: 2px 8px 6px; }
  .ep-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(38px, 1fr));
    gap: 2px;
  }
  /* Each pops in from the side the category is, a little, rather than straight up. */
  .ep-grid:global(.domino.is-in) > :not([data-there]) { animation-name: ep-in; animation-duration: 0.42s; }
  @keyframes ep-in {
    from { opacity: 0; transform: translateX(var(--ep-from, 10px)) scale(0.4); }
    60% { opacity: 1; }
  }
  .ep-e {
    display: grid;
    place-items: center;
    height: 38px;
    border-radius: 11px;
    font-size: 23px;
    line-height: 1;
    transition: transform 0.3s var(--jelly), background-color 0.15s ease;
  }
  .ep-e:hover:not(:disabled), .ep-e:focus-visible {
    outline: none;
    background: rgb(255 255 255 / 0.08);
    transform: translateY(-2px) scale(1.22);
  }
  .ep-e:active:not(:disabled) { transform: scale(0.88); }
  .ep-e.is-on {
    background: color-mix(in srgb, var(--color-accent) 22%, transparent);
    box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--color-accent) 60%, transparent);
  }
  .ep-e:disabled { cursor: not-allowed; opacity: 0.3; }
  .ep-none { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 26px 0; font-size: 12px;
    color: var(--color-faint); }
  .ep-none span { font-size: 26px; animation: ep-pop 0.45s var(--jelly); }

  /* The one under the pointer, big, with its name. */
  .ep-foot {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 44px;
    padding: 6px 12px;
    border-top: 1px solid color-mix(in srgb, var(--color-edge) 70%, transparent);
    background: rgb(255 255 255 / 0.02);
  }
  .ep-big { font-size: 26px; line-height: 1; animation: ep-pop 0.35s var(--jelly); }
  .ep-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px;
    color: var(--color-muted); text-transform: capitalize; }
  .ep-name.is-hint { text-transform: none; color: var(--color-faint); }
  @keyframes ep-pop { from { transform: scale(0.4) rotate(-12deg); opacity: 0; } }

  :global(:root[data-motion="off"]) .ep-pill,
  :global(:root[data-motion="off"]) .ep-tab,
  :global(:root[data-motion="off"]) .ep-e { transition: none; }
  :global(:root[data-motion="off"]) .ep-big,
  :global(:root[data-motion="off"]) .ep-clear,
  :global(:root[data-motion="off"]) .ep-none span { animation: none; }
</style>
