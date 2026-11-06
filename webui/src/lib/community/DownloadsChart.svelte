<script lang="ts">
  /**
   * Downloads a day, as bars that grow up in turn when the chart comes into view, the busiest day lit. Each bar says
   * its day and count on hover.
   */
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { motionEnabled } from "../stores";
  import { play } from "../uisound";
  import { compact, lastDays } from "./logic";

  let { daily = [], days = [], n = 30, color = "var(--color-accent)" }: {
    daily?: number[]; days?: string[]; n?: number; color?: string;
  } = $props();

  const bars = $derived(lastDays(daily, days, n));
  const top = $derived(Math.max(1, ...bars.map((b) => b.v)));
  const total = $derived(bars.reduce((s, b) => s + b.v, 0));
  let grown = $state(false);
  let host: HTMLElement | null = $state(null);

  onMount(() => {
    if (!get(motionEnabled) || !host) {
      grown = true;
      return;
    }
    const io = new IntersectionObserver((seen) => {
      if (!seen.some((e) => e.isIntersecting)) return;
      io.disconnect();
      grown = true;
      if (bars.length) play("grow", { level: 0.4 });
    }, { threshold: 0.4 });
    io.observe(host);
    return () => io.disconnect();
  });
</script>

<div class="dc" bind:this={host} style="--c: {color}; --n: {Math.max(1, bars.length)}">
  {#if bars.length}
    <div class="dc-bars" class:is-grown={grown} role="img" aria-label="{compact(total)} downloads in the last {bars.length} days">
      {#each bars as b, i (i)}
        <span class="dc-bar" class:is-top={b.v === top && b.v > 0} style="--h: {Math.max(4, (b.v / top) * 100)}%; --i: {i}"
              title="{b.day}: {b.v}"></span>
      {/each}
    </div>
    <div class="dc-foot"><span>{bars[0]?.day ?? ""}</span><span>{compact(total)} in {bars.length} days</span><span>today</span></div>
  {:else}
    <p class="dc-none">No downloads counted yet.</p>
  {/if}
</div>

<style>
  .dc-bars {
    display: grid;
    grid-template-columns: repeat(var(--n), minmax(0, 1fr));
    align-items: end;
    gap: 3px;
    height: 74px;
    padding: 4px 2px 0;
  }
  .dc-bar {
    height: var(--h);
    min-height: 3px;
    border-radius: 3px 3px 1px 1px;
    background: linear-gradient(to top, color-mix(in srgb, var(--c) 35%, transparent), color-mix(in srgb, var(--c) 80%, transparent));
    transform: scaleY(0.02);
    transform-origin: bottom;
    transition: transform 0.55s var(--spring);
    transition-delay: calc(var(--i) * 14ms);
  }
  .dc-bars.is-grown .dc-bar { transform: none; }
  .dc-bar.is-top { background: linear-gradient(to top, color-mix(in srgb, var(--c) 55%, transparent), var(--c));
                   box-shadow: 0 0 12px -2px color-mix(in srgb, var(--c) 70%, transparent); }
  .dc-foot { display: flex; justify-content: space-between; margin-top: 6px; font-size: 10.5px; color: var(--color-faint); }
  .dc-none { margin: 0; font-size: 12.5px; color: var(--color-faint); }
  :global(:root[data-motion="off"]) .dc-bar { transform: none; transition: none; }
</style>
