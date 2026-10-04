<script lang="ts">
  /**
   * A language, picked from the real list rather than typed as a code.
   *
   * "en-US" and "en" were free text boxes: the right code had to be known, and
   * a wrong one ("english", "fr-fr" where Discord wants "fr") was accepted and
   * quietly never worked. The button shows the language by name, in English
   * and in itself, with its flag. Opened, it is the whole list,
   * found by typing its name in either language or its code ("francais",
   * "日本", "pt"), with the most used ones first.
   *
   * A stored value that is not in the list is kept and said, not replaced.
   */
  import { tick } from "svelte";
  import Icon from "./Icon.svelte";
  import { flagOf } from "../clock";
  import { searchLanguages, type Lang } from "../languages";
  import { afterLanding, onScreen } from "../cascade";
  import { focusStill, showInList } from "../inlist";
  import { play } from "../uisound";

  /**
   * The flag landing as the tab opens, heard: its first landing only (a
   * language picked after makes its own sound), when its row has landed and
   * where it can be seen.
   */
  let arrivalHeard = false;
  function flagLands(e: AnimationEvent) {
    if (arrivalHeard || !e.animationName.endsWith("lp-land")) return;
    arrivalHeard = true;
    const el = e.currentTarget as HTMLElement;
    afterLanding(el, () => onScreen(el).then((seen) => { if (seen) play("land"); }));
  }

  let {
    value = "",
    options,
    onchange,
    common = [],
    unknown = "Not in the list",
  }: {
    value?: string;
    options: Lang[];
    onchange?: (v: string) => void;
    /** Codes shown first, under "Most used", until something is typed. */
    common?: string[];
    /** Said under a stored value that is not one of the options. */
    unknown?: string;
  } = $props();

  let open = $state(false);
  let q = $state("");
  let active = $state(0);
  let up = $state(false);
  let root: HTMLElement | null = $state(null);
  let list: HTMLElement | null = $state(null);
  let input: HTMLInputElement | null = $state(null);

  const current = $derived(options.find((o) => o.code === value) ?? null);

  /** What the list shows: the most used first while nothing is typed, then everything else. */
  const shown = $derived.by(() => {
    if (q.trim()) return searchLanguages(options, q).map((l) => ({ l, head: "" }));
    const top = common.map((c) => options.find((o) => o.code === c)).filter((o): o is Lang => !!o);
    if (!top.length) return options.map((l) => ({ l, head: "" }));
    const rest = options.filter((o) => !common.includes(o.code));
    return [
      ...top.map((l, i) => ({ l, head: i === 0 ? "Most used" : "" })),
      ...rest.map((l, i) => ({ l, head: i === 0 ? "Every language" : "" })),
    ];
  });

  async function openList() {
    const r = root?.getBoundingClientRect();
    up = !!r && window.innerHeight - r.bottom < 380 && r.top > window.innerHeight - r.bottom;
    q = "";
    open = true;
    await tick();
    active = Math.max(0, shown.findIndex((x) => x.l.code === value));
    // The list scrolls to the language, the page stays where it is (lib/inlist.ts).
    focusStill(input);
    showInList(list, list?.querySelector<HTMLElement>('[data-active="true"]'), "center");
  }
  function choose(code: string) {
    open = false;
    if (code !== value) onchange?.(code);
    focusStill(root?.querySelector<HTMLButtonElement>(".lp-trigger"));
  }
  async function move(by: number) {
    active = Math.max(0, Math.min(shown.length - 1, active + by));
    await tick();
    showInList(list, list?.querySelector<HTMLElement>('[data-active="true"]'));
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); open = false; return; }
    if (e.key === "ArrowDown") { e.preventDefault(); move(1); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); move(-1); return; }
    if (e.key === "PageDown") { e.preventDefault(); move(8); return; }
    if (e.key === "PageUp") { e.preventDefault(); move(-8); return; }
    if (e.key === "Enter") { e.preventDefault(); const x = shown[active]; if (x) choose(x.l.code); }
  }
  $effect(() => {
    void q;
    active = 0;
  });
  /** A click anywhere else closes it. */
  function outside(e: PointerEvent) {
    if (open && root && !root.contains(e.target as Node)) open = false;
  }
</script>

<svelte:window onpointerdown={outside} />

<!-- Its flag, or a globe for a language that is no one country's (or not in the list at all). -->
{#snippet markOf(l: Lang | null, big: boolean)}
  {#if l?.flag}
    <span class="lp-flag flag" class:is-big={big}>{flagOf(l.flag)}</span>
  {:else}
    <span class="lp-flag is-none" class:is-big={big}><Icon name="globe" size={big ? 17 : 15} /></span>
  {/if}
{/snippet}

<div class="lp" bind:this={root}>
  <button type="button" class="lp-trigger" class:is-bad={!!value && !current}
          onclick={() => (open ? (open = false) : openList())}
          aria-haspopup="listbox" aria-expanded={open}>
    {#key value}
      <span class="lp-medal" onanimationstart={flagLands}>{@render markOf(current, true)}</span>
    {/key}
    <span class="lp-text">
      <span class="lp-name">{current ? current.name : value || "Not set"}</span>
      <span class="lp-meta">
        {#if current}{current.native !== current.name ? `${current.native} · ` : ""}{current.code}{:else if value}{unknown}{:else}Pick one{/if}
      </span>
    </span>
    <Icon name="chevron" size={13} class="lp-chev" />
  </button>

  {#if open}
    <div class="lp-pop" class:is-up={up} role="presentation" onkeydown={onKey}>
      <label class="lp-search">
        <Icon name="search" size={13} />
        <input bind:this={input} bind:value={q} placeholder="Name, in any language, or code" spellcheck="false"
               aria-label="Search languages" />
      </label>
      <div class="lp-list" role="listbox" aria-label="Languages" bind:this={list}>
        {#each shown as { l, head }, i (l.code)}
          {#if head}<p class="lp-head" role="presentation">{head}</p>{/if}
          <button type="button" role="option" aria-selected={l.code === value} data-active={i === active}
                  class="lp-row" class:is-on={l.code === value} class:is-active={i === active}
                  onpointerenter={() => (active = i)} onclick={() => choose(l.code)}>
            {@render markOf(l, false)}
            <span class="lp-row-name">
              <b>{l.name}</b>{#if l.native !== l.name}<span>{l.native}</span>{/if}
            </span>
            <span class="lp-row-code">{l.code}</span>
            {#if l.code === value}<Icon name="check" size={13} class="lp-tick" />{/if}
          </button>
        {:else}
          <p class="lp-none">No language matches "{q}".</p>
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  .lp { position: relative; width: 100%; max-width: 20rem; }
  .lp-trigger {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 11px;
    padding: 7px 10px 7px 8px;
    border-radius: 12px;
    border: 1px solid var(--color-edge);
    background: rgb(0 0 0 / 0.22);
    text-align: left;
    transition: border-color 0.18s var(--swift), box-shadow 0.18s var(--swift), transform 0.25s var(--spring);
  }
  .lp-trigger:hover { border-color: color-mix(in srgb, var(--color-accent) 45%, var(--color-edge)); }
  .lp-trigger:active { transform: scale(0.985); }
  .lp-trigger:focus-visible { outline: none; box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 22%, transparent); }
  .lp-trigger.is-bad { border-color: color-mix(in srgb, var(--color-warn) 60%, transparent); }

  /* The flag, in a soft round frame like the timezone picker's clock,
     arriving with a little bounce when the language changes. */
  /* The flag itself, big and lifted off the panel by a shadow, rather than a
     small flag inside a round frame, and landing with a little bounce when
     the language changes. */
  .lp-medal {
    display: grid;
    width: 36px;
    height: 36px;
    flex-shrink: 0;
    place-items: center;
    animation: lp-land 0.5s var(--jelly) both;
  }
  @keyframes lp-land { from { transform: scale(0.6) rotate(-14deg); opacity: 0.2; } }

  /* An emoji sits a little high in its line: pinned to a box one em square
     and nudged down, so the flag is truly in the middle. */
  .lp-flag { display: grid; width: 1em; height: 1em; place-items: center; font-size: 16px; line-height: 1; }
  .lp-flag.is-big { font-size: 31px; filter: drop-shadow(0 2px 3px rgb(0 0 0 / 0.45)); }
  .lp-flag.is-none { color: var(--color-muted); }

  .lp-text { display: flex; min-width: 0; flex: 1; flex-direction: column; }
  .lp-name { overflow: hidden; font-size: 13.5px; font-weight: 650; color: var(--color-ink); text-overflow: ellipsis; white-space: nowrap; }
  .lp-meta { overflow: hidden; font-size: 11px; color: var(--color-muted); text-overflow: ellipsis; white-space: nowrap; }
  .lp-trigger.is-bad .lp-meta { color: var(--color-warn); }
  .lp-trigger :global(.lp-chev) { flex-shrink: 0; color: var(--color-faint); transform: rotate(90deg); }

  .lp-pop {
    position: absolute;
    right: 0;
    top: calc(100% + 6px);
    z-index: 40;
    display: flex;
    width: min(22rem, 90vw);
    flex-direction: column;
    gap: 6px;
    padding: 8px;
    border-radius: 14px;
    border: 1px solid var(--color-edge);
    background: var(--color-surface);
    box-shadow: 0 24px 60px -20px rgb(0 0 0 / 0.65);
    animation: lp-in 0.16s var(--swift) both;
    transform-origin: top right;
  }
  .lp-pop.is-up { top: auto; bottom: calc(100% + 6px); transform-origin: bottom right; }
  @keyframes lp-in { from { opacity: 0; transform: scale(0.96) translateY(-4px); } }
  .lp-search {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 6px 9px;
    border-radius: 9px;
    color: var(--color-faint);
    background: rgb(0 0 0 / 0.25);
  }
  .lp-search input { min-width: 0; flex: 1; font-size: 13px; color: var(--color-ink); background: transparent; outline: none; }
  .lp-list { display: flex; max-height: 290px; flex-direction: column; overflow-y: auto; }
  .lp-head {
    padding: 8px 9px 4px;
    font-size: 10px;
    font-weight: 650;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--color-faint);
  }
  .lp-row {
    display: grid;
    grid-template-columns: 28px minmax(0, 1fr) auto 14px;
    align-items: center;
    gap: 9px;
    padding: 6px 9px;
    border-radius: 8px;
    text-align: left;
    font-size: 12.5px;
    color: var(--color-muted);
  }
  .lp-row > :first-child { justify-self: center; transition: transform 0.4s var(--jelly); }
  .lp-row.is-active { background: rgb(255 255 255 / 0.06); color: var(--color-ink); }
  .lp-row.is-active > :first-child { transform: scale(1.15) rotate(-6deg); }
  .lp-row.is-on { color: var(--color-ink); background: color-mix(in srgb, var(--color-accent) 16%, transparent); }
  .lp-row-name { display: flex; min-width: 0; align-items: baseline; gap: 7px; }
  .lp-row-name b { overflow: hidden; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
  .lp-row-name span { overflow: hidden; font-size: 11px; color: var(--color-faint); text-overflow: ellipsis; white-space: nowrap; }
  .lp-row-code { font-family: ui-monospace, monospace; font-size: 10.5px; color: var(--color-faint); }
  .lp-row :global(.lp-tick) { grid-column: 4; color: var(--color-accent); }
  .lp-none { padding: 10px; font-size: 12px; color: var(--color-faint); }

  :global(:root[data-motion="off"]) .lp-medal { animation: none; }
  :global(:root[data-motion="off"]) .lp-row > :first-child { transition: none; }
</style>
