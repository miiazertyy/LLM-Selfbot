<script lang="ts">
  /** A number that rolls up to its new value instead of jumping, like a scoreboard. */
  import { Tween } from "svelte/motion";
  import { cubicOut } from "svelte/easing";
  import { motionEnabled } from "../stores";

  let { value = 0, compact = true }: { value?: number; compact?: boolean } = $props();

  const t = new Tween(0, { duration: 1200, easing: cubicOut });
  $effect(() => {
    t.set(value || 0, { duration: $motionEnabled ? 1200 : 0 });
  });

  function fmt(n: number): string {
    const a = Math.abs(n);
    if (compact && a >= 1e6) return `${(n / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(/\.0$/, "")}M`;
    if (compact && a >= 1e4) return `${Math.round(n / 1e3)}k`;
    if (compact && a >= 1e3) return `${(n / 1e3).toFixed(1).replace(/\.0$/, "")}k`;
    return Math.round(n).toLocaleString();
  }
</script>

<span class="tabular-nums">{fmt(t.current)}</span>
