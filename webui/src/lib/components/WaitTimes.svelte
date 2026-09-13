<script lang="ts">
  import { springValue } from "../spring";
  /**
   * Editor for the batch wait table.
   *
   * The value is a list of {time, weight}: how long to wait before replying,
   * and how often to pick that wait. It used to be edited as raw JSON, which
   * is a poor way to ask someone how often the bot should take ten minutes to
   * answer. Each row is a slider with the odds shown as a percentage.
   */
  let { value = [], onchange } = $props<{
    value?: { time: number; weight: number }[];
    onchange?: (rows: { time: number; weight: number }[]) => void;
  }>();

  let rows = $state<{ time: number; weight: number }[]>([]);
  let lastSerialised = "";

  // Re-seed when the parent hands us a different value, but not on our own
  // edits, which would fight the user's typing.
  $effect(() => {
    const incoming = JSON.stringify(value ?? []);
    if (incoming !== lastSerialised) {
      lastSerialised = incoming;
      rows = (value ?? []).map((r) => ({ ...r }));
    }
  });

  const total = $derived(rows.reduce((n, r) => n + (Number(r.weight) || 0), 0) || 1);

  function push() {
    const next = [...rows, { time: 30, weight: 10 }];
    commit(next);
  }

  function remove(i: number) {
    commit(rows.filter((_, n) => n !== i));
  }

  function set(i: number, field: "time" | "weight", raw: number) {
    const next = rows.map((r, n) => (n === i ? { ...r, [field]: raw } : r));
    commit(next);
  }

  function commit(next: { time: number; weight: number }[]) {
    rows = next;
    const sorted = [...next].sort((a, b) => a.time - b.time);
    lastSerialised = JSON.stringify(sorted);
    onchange?.(sorted);
  }

  /** Seconds as something a person reads without counting zeroes. */
  function human(secs: number): string {
    if (secs < 60) return `${Math.round(secs)}s`;
    if (secs < 3600) {
      const m = secs / 60;
      return `${m % 1 ? m.toFixed(1) : m}m`;
    }
    const h = secs / 3600;
    return `${h % 1 ? h.toFixed(1) : h}h`;
  }
</script>

<div class="w-full space-y-2">
  {#each rows as r, i}
    <div class="flex items-center gap-2 rounded-lg bg-white/[0.03] px-2.5 py-2">
      <input
        type="number"
        min="1"
        value={r.time}
        oninput={(e) => set(i, "time", Number((e.target as HTMLInputElement).value))}
        class="bare w-16 text-right font-mono text-[12px]"
        aria-label="Wait in seconds"
      />
      <span class="w-10 shrink-0 text-[11px] text-faint">{human(r.time)}</span>

      <!-- The filled part of the track shows the weight, and the percentage
           springs when it changes, so the number reads as part of the slider
           rather than a separate readout that happens to sit beside it. -->
      <input
        type="range"
        min="0"
        max="100"
        value={r.weight}
        oninput={(e) => set(i, "weight", Number((e.target as HTMLInputElement).value))}
        style="--fill: {Math.max(0, Math.min(100, Number(r.weight) || 0))}%"
        class="slider min-w-0 flex-1"
        aria-label="How often this wait is picked"
        use:springValue
      />
      <span class="slider-value w-10 shrink-0 text-right text-[12px] font-medium text-accent">
        {Math.round(((Number(r.weight) || 0) / total) * 100)}%
      </span>

      <button
        onclick={() => remove(i)}
        aria-label="Remove this wait"
        class="jelly shrink-0 rounded px-1.5 text-faint hover:text-bad"
      >&times;</button>
    </div>
  {/each}

  <div class="flex items-center justify-between gap-2">
    <button onclick={push} class="jelly rounded-lg border border-edge px-2.5 py-1 text-[11px] text-muted hover:bg-white/[0.05] hover:text-ink">
      Add a wait
    </button>
    <span class="text-[11px] text-faint">
      Percentages are the odds of each wait being chosen.
    </span>
  </div>
</div>
