<script lang="ts">
  /**
   * A persona's colour, picked from dots, in the order of the rainbow: it tints the page, its card and its ring. The one
   * picked pops, with a bright glint. With `themes` too, the themes of two colours follow, each dot running from one to
   * the other.
   */
  import { play } from "../uisound";
  import { byHue, type PersonaTheme } from "./logic";

  let {
    palette,
    value,
    second = "",
    themes = [],
    size = 18,
    columns = 0,
    onpick,
  }: {
    palette: { id: string; name: string; hex: string }[];
    value: string;
    /** Its second colour, when it has a theme. */
    second?: string;
    themes?: PersonaTheme[];
    size?: number;
    /** In even rows of this many, across the whole width, rather than as many as fit. */
    columns?: number;
    onpick: (hex: string, second: string) => void;
  } = $props();

  const dots = $derived(byHue(palette));
  const same = (a: string, b: string) => a.toLowerCase() === (b || "").toLowerCase();

  let popped = $state("");
  function pick(id: string, hex: string, other = "") {
    if (same(hex, value) && same(other, second)) return;
    popped = id;
    play("glint", { strong: true });
    onpick(hex, other);
  }
</script>

<div class="cd" class:is-rows={columns > 0} role="radiogroup" aria-label="Colour" style="--cd-size: {size}px; --cd-columns: {columns}">
  {#each dots as c (c.id)}
    {@const on = same(c.hex, value) && !second}
    <button type="button" role="radio" aria-checked={on} class="cd-dot" class:is-on={on} class:is-pop={popped === c.id}
            style="--c: {c.hex}" title={c.name} aria-label={c.name} data-sound="self" onclick={() => pick(c.id, c.hex)}
            onanimationend={() => (popped = "")}></button>
  {/each}
  {#each themes as t, i (t.id)}
    {@const on = same(t.a, value) && same(t.b, second)}
    <button type="button" role="radio" aria-checked={on} class="cd-dot is-theme" class:is-first={i === 0} class:is-on={on}
            class:is-pop={popped === `theme:${t.id}`} style="--c: {t.a}; --c2: {t.b}" title={t.name} aria-label={t.name} data-sound="self"
            onclick={() => pick(`theme:${t.id}`, t.a, t.b)} onanimationend={() => (popped = "")}></button>
  {/each}
</div>

<style>
  .cd { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }
  @media (min-width: 620px) {
    .cd.is-rows { display: grid; grid-template-columns: repeat(var(--cd-columns), var(--cd-size)); justify-content: space-between; row-gap: 9px; }
  }
  .cd-dot {
    position: relative;
    width: var(--cd-size, 18px);
    height: var(--cd-size, 18px);
    border-radius: 999px;
    background: radial-gradient(circle at 35% 30%, color-mix(in srgb, var(--c) 55%, white), var(--c) 70%);
    box-shadow: 0 0 0 1px rgb(0 0 0 / 0.25), 0 2px 6px -2px var(--c);
    transition: transform 0.35s var(--jelly), box-shadow 0.25s var(--swift);
  }
  .cd-dot.is-theme { background: linear-gradient(135deg, var(--c), var(--c2)); }
  .cd-dot:hover { transform: scale(1.18); }
  .cd-dot.is-on { box-shadow: 0 0 0 2px var(--color-card), 0 0 0 4px var(--c), 0 0 14px -2px var(--c); }
  .cd-dot.is-pop { animation: cd-pop 0.5s var(--jelly); }
  @keyframes cd-pop { 40% { transform: scale(1.45); } }
  .cd-dot:focus-visible { outline: 2px solid var(--c); outline-offset: 3px; }
  :global(:root[data-motion="off"]) .cd-dot { transition: none; animation: none; }
</style>
