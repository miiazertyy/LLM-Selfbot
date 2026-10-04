<script lang="ts">
  /**
   * A persona's colour, picked from a row of dots: it tints the page, its card
   * and its ring. The one picked pops, with a bright glint.
   */
  import { play } from "../uisound";

  let {
    palette,
    value,
    onpick,
  }: { palette: { id: string; name: string; hex: string }[]; value: string; onpick: (hex: string) => void } = $props();

  let popped = $state("");
  function pick(hex: string) {
    if (hex === value) return;
    popped = hex;
    play("glint", { strong: true });
    onpick(hex);
  }
</script>

<div class="cd" role="radiogroup" aria-label="Colour">
  {#each palette as c (c.id)}
    {@const on = c.hex.toLowerCase() === (value || "").toLowerCase()}
    <button type="button" role="radio" aria-checked={on} class="cd-dot" class:is-on={on} class:is-pop={popped === c.hex}
            style="--c: {c.hex}" title={c.name} aria-label={c.name} data-sound="self" onclick={() => pick(c.hex)}
            onanimationend={() => (popped = "")}></button>
  {/each}
</div>

<style>
  .cd { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }
  .cd-dot {
    position: relative;
    width: 18px;
    height: 18px;
    border-radius: 999px;
    background: radial-gradient(circle at 35% 30%, color-mix(in srgb, var(--c) 55%, white), var(--c) 70%);
    box-shadow: 0 0 0 1px rgb(0 0 0 / 0.25), 0 2px 6px -2px var(--c);
    transition: transform 0.35s var(--jelly), box-shadow 0.25s var(--swift);
  }
  .cd-dot:hover { transform: scale(1.18); }
  .cd-dot.is-on { box-shadow: 0 0 0 2px var(--color-card), 0 0 0 4px var(--c), 0 0 14px -2px var(--c); }
  .cd-dot.is-pop { animation: cd-pop 0.5s var(--jelly); }
  @keyframes cd-pop { 40% { transform: scale(1.45); } }
  .cd-dot:focus-visible { outline: 2px solid var(--c); outline-offset: 3px; }
  :global(:root[data-motion="off"]) .cd-dot { transition: none; animation: none; }
</style>
