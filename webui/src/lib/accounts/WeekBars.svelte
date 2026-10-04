<script lang="ts">
  /**
   * One account's week: a column per day, Mon ... Today.
   *
   * It used to be the Dashboard's 14-day chart shrunk into the card: bars with
   * no day under them, a date at each end, and one "Sep 17 · 133" label that
   * read like a code. With a quiet fortnight and one busy day it was a single
   * block and some specks, and nothing said which day was which.
   *
   * Now every column is named, today is the one in full colour, and only two
   * numbers are printed - today's and the busiest day's - with the rest a hover
   * away. A day with nothing on it still has a stub on the baseline, so zero
   * reads as zero rather than as a gap where data went missing.
   */
  import { onMount } from "svelte";
  import { motionEnabled } from "../stores";
  import { fmtDate } from "../fmt";
  import { growIn } from "../growin";

  let {
    values = [],
    dates = [],
    unit = "replies",
    height = 64,
  }: { values?: number[]; dates?: string[]; unit?: string; height?: number } = $props();

  const max = $derived(Math.max(1, ...values));
  const peak = $derived(values.indexOf(Math.max(...values)));
  const last = $derived(values.length - 1);

  // Local dates, parsed as local: new Date("2026-09-26") would be UTC midnight,
  // which is the day before for anyone west of Greenwich.
  function day(iso: string) {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, (m || 1) - 1, d || 1);
  }
  const short = (iso: string) => fmtDate(day(iso), { weekday: "short" });
  const long = (iso: string) => fmtDate(day(iso), { weekday: "long", day: "numeric", month: "long" });

  let hover = $state(-1);
  let el: HTMLElement | null = $state(null);
  /** A day after the one before, as the bars grow in, each with its note (lib/growin.ts). */
  const STAGGER = 55;
  // Grow in once, when the card has landed and can be seen, and not again on every refresh.
  let grown = $state(false);
  /** While they grow in: each bar's delay is only for that, not for a hover's colour after. */
  let growing = $state(false);
  onMount(() => {
    let t = 0;
    // Each bar's note rises with it, as far as the bar goes, and rings as it lands (uisound "grow").
    growIn(el, () => values, (moving) => {
      growing = moving;
      grown = true;
      t = window.setTimeout(() => (growing = false), values.length * STAGGER + 700);
    }, STAGGER, 1, "grow");
    return () => clearTimeout(t);
  });

  const labelled = (i: number) => values[i] > 0 && (i === last || i === peak);
</script>

<div class="wk" style="--h:{height}px" role="list" aria-label="Replies per day this week" bind:this={el}>
  {#each values as v, i (dates[i] ?? i)}
    <div
      class="wk-col"
      class:is-today={i === last}
      class:is-hover={hover === i}
      role="listitem"
      aria-label="{long(dates[i] ?? '')}: {v} {unit}"
      onpointerenter={() => (hover = i)}
      onpointerleave={() => (hover = -1)}
    >
      <span class="wk-val" class:is-shown={labelled(i) || hover === i}>{v}</span>
      <span class="wk-track">
        <span
          class="wk-bar"
          class:is-zero={v === 0}
          style="height:{v === 0 ? 3 : Math.max(4, (v / max) * height)}px;
                 transform:scaleY({grown || !$motionEnabled ? 1 : 0});
                 transition-delay:{growing ? i * STAGGER : 0}ms"
        ></span>
      </span>
      <span class="wk-day">{i === last ? "Today" : short(dates[i] ?? "")}</span>
      {#if hover === i}
        <span class="wk-tip" role="tooltip">
          <span class="text-ink">{v} {v === 1 ? unit.replace(/s$/, "") : unit}</span>
          <span class="text-faint">{long(dates[i] ?? "")}</span>
        </span>
      {/if}
    </div>
  {/each}
</div>

<style>
  .wk {
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 2px;
    align-items: end;
  }
  .wk-col {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding-top: 2px;
    border-radius: 8px;
    cursor: default;
    transition: background-color 0.15s ease;
  }
  /* The whole column is the hover target: a 3px stub is nothing to aim at. */
  .wk-col.is-hover {
    background: rgb(255 255 255 / 0.035);
  }
  .wk-val {
    height: 14px;
    font-size: 10.5px;
    font-weight: 600;
    line-height: 14px;
    color: var(--color-muted);
    font-variant-numeric: tabular-nums;
    opacity: 0;
    transition: opacity 0.15s ease;
  }
  .wk-val.is-shown {
    opacity: 1;
  }
  .is-today .wk-val {
    color: var(--color-ink);
  }
  .wk-track {
    display: flex;
    align-items: flex-end;
    justify-content: center;
    width: 100%;
    height: var(--h);
    border-bottom: 1px solid color-mix(in srgb, var(--color-edge) 80%, transparent);
  }
  /* One hue. The past days are the de-emphasised step of it, today the full
     accent: the eye goes to today, the shape of the week stays readable. */
  .wk-bar {
    display: block;
    width: min(22px, 62%);
    border-radius: 4px 4px 0 0;
    background: color-mix(in srgb, var(--color-accent) 60%, transparent);
    transform-origin: bottom;
    transition: transform 0.55s var(--spring), background-color 0.15s ease, height 0.4s var(--spring);
  }
  .is-today .wk-bar {
    background: var(--color-accent);
  }
  .is-hover .wk-bar {
    background: color-mix(in srgb, var(--color-accent) 80%, transparent);
  }
  .wk-bar.is-zero {
    background: color-mix(in srgb, var(--color-edge) 90%, transparent);
    border-radius: 2px;
  }
  .wk-day {
    font-size: 10.5px;
    color: var(--color-faint);
    white-space: nowrap;
  }
  .is-today .wk-day {
    color: var(--color-ink);
    font-weight: 600;
  }
  .wk-tip {
    position: absolute;
    bottom: calc(100% + 4px);
    left: 50%;
    z-index: 5;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 5px 9px;
    border-radius: 9px;
    font-size: 11px;
    white-space: nowrap;
    background: var(--color-surface);
    box-shadow: 0 6px 20px -8px rgb(0 0 0 / 0.6), inset 0 0 0 1px var(--color-edge);
    transform: translateX(-50%);
    pointer-events: none;
  }
  :global(:root[data-motion="off"]) .wk-bar {
    transition: none;
  }
</style>
