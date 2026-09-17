<script lang="ts">
  /**
   * Browse and pick emoji, instead of pasting them in.
   *
   * Rendered as a plain grid rather than a virtualised list: ~1900 spans of
   * text is well within what the browser handles, and only one category is on
   * screen at a time, so the most it ever draws at once is a few hundred.
   * Search is the exception - it can match across every group - so that path
   * is capped.
   */
  import { EMOJI_GROUPS, EMOJI_ALL, type EmojiEntry } from "../emoji";
  import Icon from "./Icon.svelte";

  let { chosen = [], full = false, onpick } = $props<{
    /** Already-picked emoji, shown ticked so the grid reflects the set. */
    chosen?: string[];
    /** True when no more will be accepted; picking an existing one still works. */
    full?: boolean;
    onpick: (emoji: string) => void;
  }>();

  let group = $state(EMOJI_GROUPS[0]?.name ?? "");
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
    return EMOJI_GROUPS.find((g) => g.name === group)?.items ?? [];
  });

  const has = (e: string) => chosen.includes(e);
</script>

<div class="rounded-xl border border-edge bg-black/20">
  <div class="flex flex-wrap items-center gap-1.5 border-b border-edge/70 p-2">
    <label class="relative min-w-[150px] flex-1">
      <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
        <Icon name="search" size={13} />
      </span>
      <input
        bind:value={query}
        placeholder="Search {EMOJI_ALL.length} emoji"
        class="field w-full py-1.5 pl-8 pr-3 text-[12px]"
      />
    </label>
    {#if query}
      <button class="jelly rounded-lg px-2 py-1 text-[11px] text-muted hover:bg-white/[0.06]"
              onclick={() => (query = "")}>Clear</button>
    {/if}
  </div>

  {#if !q}
    <div class="flex flex-wrap gap-1 border-b border-edge/70 p-2">
      {#each EMOJI_GROUPS as g}
        <button
          onclick={() => (group = g.name)}
          aria-pressed={group === g.name}
          class="jelly rounded-lg px-2 py-1 text-[11px]
            {group === g.name
              ? 'bg-accent/15 text-ink'
              : 'text-muted hover:bg-white/[0.05]'}"
        >
          {g.name}
        </button>
      {/each}
    </div>
  {/if}

  <div class="max-h-52 overflow-y-auto p-2">
    {#if shown.length === 0}
      <p class="px-1 py-6 text-center text-[12px] text-faint">Nothing matches that.</p>
    {:else}
      <div class="grid grid-cols-[repeat(auto-fill,minmax(34px,1fr))] gap-1">
        {#each shown as [ch, name] (ch)}
          <button
            type="button"
            title={name}
            aria-label={name}
            aria-pressed={has(ch)}
            disabled={full && !has(ch)}
            onclick={() => onpick(ch)}
            class="flex h-8 items-center justify-center rounded-lg text-[18px] leading-none
                   transition-colors disabled:cursor-not-allowed disabled:opacity-30
                   {has(ch) ? 'bg-accent/20 ring-1 ring-accent/50' : 'hover:bg-white/[0.07]'}"
          >{ch}</button>
        {/each}
      </div>
      {#if q && shown.length >= SEARCH_LIMIT}
        <p class="px-1 pt-2 text-[10px] text-faint">
          Showing the first {SEARCH_LIMIT}. Keep typing to narrow it.
        </p>
      {/if}
    {/if}
  </div>
</div>
