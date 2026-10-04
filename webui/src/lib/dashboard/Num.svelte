<script lang="ts" module>
  /** One formatter per number of decimals, made once: a new Intl formatter every frame of a count is not free. */
  const formats = new Map<number, Intl.NumberFormat>();
  function fmt(decimals: number): Intl.NumberFormat {
    let f = formats.get(decimals);
    if (!f) {
      f = new Intl.NumberFormat(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
      formats.set(decimals, f);
    }
    return f;
  }
</script>

<script lang="ts">
  /**
   * A figure on the Dashboard that is alive: it counts up from nothing when the
   * page opens, glides to its new value when one arrives, and glows for a
   * moment as it does, so a reply going out shows as the number ticking over
   * rather than a digit silently swapped.
   */
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { Tween } from "svelte/motion";
  import { quintOut } from "svelte/easing";
  import { motionEnabled } from "../stores";
  import { onScreen, whenShown } from "../cascade";
  import { play } from "../uisound";

  let { value = 0, decimals = 0 }: { value?: number; decimals?: number } = $props();

  const shown = new Tween(0, { duration: 1100, easing: quintOut });
  let bumped = $state(false);
  let first = true;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let el: HTMLElement | null = $state(null);
  /** Its block has started to drop in (cascade.ts): the count starts with it, not before it is seen. */
  let ready = $state(false);
  /** The first count up from nothing, heard, while it can be seen. */
  let heard = false;

  onMount(() => {
    if (!get(motionEnabled)) return void (ready = true);
    whenShown(el).then(() => onScreen(el)).then((seen) => {
      heard = seen;
      ready = true;
    });
  });

  $effect(() => {
    const v = Number(value) || 0;
    const moving = $motionEnabled;
    if (!ready) return;
    if (!first && v !== shown.target && moving) {
      bumped = true;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => (bumped = false), 900);
    }
    shown.set(v, { duration: !moving ? 0 : first ? 1100 : 700 });
    if (!first || !v || !moving) heard = false;
    first = false;
  });

  /*
   * The first count heard as an odometer winding up: a dry detent every
   * tenth of the way, quick at first and slower as the count slows, and a soft
   * tock as it settles, once it has stopped moving to the eye.
   */
  let notch = 0;
  $effect(() => {
    const c = shown.current;
    if (!heard) return;
    const target = shown.target || 1;
    const k = Math.floor((c / target) * 10);
    if (k !== notch && k < 10) {
      notch = k;
      play("wind", { p: c / target, level: 0.8 });
    }
    if (Math.abs(target - c) <= Math.max(0.5, Math.abs(target) * 0.01)) {
      heard = false;
      play("seat", { p: 0.6, level: 0.7 });
    }
  });

  $effect(() => () => {
    if (timer) clearTimeout(timer);
  });
</script>

<span class="num" class:is-bumped={bumped} bind:this={el}>{fmt(decimals).format(shown.current)}</span>

<style>
  .num {
    display: inline-block;
    font-variant-numeric: tabular-nums;
    transition: color 0.35s var(--swift), transform 0.45s var(--jelly), text-shadow 0.35s var(--swift);
  }
  .num.is-bumped {
    color: var(--color-accent);
    transform: translateY(-1px) scale(1.06);
    text-shadow: 0 0 18px color-mix(in srgb, var(--color-accent) 55%, transparent);
  }
  :global(:root[data-motion="off"]) .num { transition: none; }
</style>
