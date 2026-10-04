<script lang="ts">
  /**
   * A trend beside a figure: a few thin bars, the latest in full colour.
   *
   * Deliberately bare - no axis, no labels - because it sits next to the number
   * it explains and only has to show the shape: rising, falling, a spike.
   * The past is the softer step of the accent and the current period the full
   * one, so the eye lands on "now" and reads the rest as context. A zero is a
   * stub on the baseline rather than nothing, so a quiet day does not read as
   * a gap in the data.
   */
  import { onMount } from "svelte";
  import { growIn, staggerFor } from "../growin";

  let {
    values = [],
    height = 26,
    label = "",
    /** Per-bar text for the hover title, e.g. "Mon: 12 replies". */
    titles = [],
  }: { values?: number[]; height?: number; label?: string; titles?: string[] } = $props();

  const max = $derived(Math.max(1, ...values));

  // Grown up into place as the Dashboard opens, a bar after the bar before,
  // each with a note rising alongside it, as far as it goes (lib/growin.ts,
  // uisound "grow"); there at once after.
  let el: HTMLElement | null = $state(null);
  let grown = $state(false);
  let growing = $state(false);
  const stagger = $derived(staggerFor(values.length, 40, 480));
  onMount(() => {
    let t = 0;
    growIn(el, () => values, (moving) => {
      growing = moving;
      grown = true;
      t = window.setTimeout(() => (growing = false), values.length * stagger + 700);
    }, stagger, 0.55, "grow");
    return () => clearTimeout(t);
  });
</script>

<div class="spark" class:is-grown={grown} style="height:{height}px" role="img" aria-label={label} bind:this={el}>
  {#each values as v, i}
    <span
      class="spark-bar"
      class:is-now={i === values.length - 1}
      class:is-zero={!v}
      style="height:{v ? Math.max(10, (v / max) * 100) : 0}%; transition-delay:{growing ? i * stagger : 0}ms"
      title={titles[i] ?? String(v)}
    ></span>
  {/each}
</div>

<style>
  .spark {
    display: flex;
    align-items: flex-end;
    gap: 2px;
    overflow: hidden;
  }
  .spark-bar {
    flex: 1 1 0;
    /* No minimum: 24 hourly bars in a narrow figure must shrink to fit rather
       than spill out the side of the tile. */
    min-width: 0;
    max-width: 12px;
    border-radius: 2px 2px 0 0;
    background: color-mix(in srgb, var(--color-accent) 45%, transparent);
    transform: scaleY(0);
    transform-origin: bottom;
    transition: height 0.5s var(--spring), transform 0.5s var(--spring);
  }
  .spark.is-grown .spark-bar {
    transform: none;
  }
  .spark-bar.is-now {
    background: var(--color-accent);
  }
  .spark-bar.is-zero {
    height: 2px !important;
    border-radius: 1px;
    background: color-mix(in srgb, var(--color-edge) 90%, transparent);
  }
  :global(:root[data-motion="off"]) .spark-bar {
    transition: none;
    transform: none;
  }
</style>
