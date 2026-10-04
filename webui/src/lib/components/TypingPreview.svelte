<script lang="ts">
  /**
   * What the typing settings add up to, for one ordinary DM reply.
   *
   * Words per minute and seconds of thinking are easy to set and hard to
   * picture. This lays the three waits end to end - reading, thinking, typing -
   * for a real-looking message, with the range each one can land in, and moves
   * as the numbers are edited, before anything is saved.
   */
  let { get }: { get: (key: string) => any } = $props();

  const SAMPLE = "haha no way, what did she say after that??";

  const n = (k: string, d: number) => {
    const v = Number(get(k));
    return isFinite(v) && get(k) !== undefined && get(k) !== "" ? v : d;
  };

  const on = $derived(get("bot.realistic_typing") !== false);
  const readLo = $derived(n("bot.read_delay_dm_min", 2.5));
  const readHi = $derived(Math.max(readLo, n("bot.read_delay_dm_max", 8)));
  const thinkLo = $derived(n("bot.typing.think_min", 2));
  const thinkHi = $derived(Math.max(thinkLo, n("bot.typing.think_max", 8)));
  const wpmLo = $derived(Math.max(5, Math.min(n("bot.typing.wpm_min", 30), n("bot.typing.wpm_max", 72))));
  const wpmHi = $derived(Math.max(5, Math.max(n("bot.typing.wpm_min", 30), n("bot.typing.wpm_max", 72))));
  const cap = $derived(n("bot.typing.max_seconds", 45));
  // A word is five characters, so chars/sec = wpm * 5 / 60.
  const typeLo = $derived(Math.min(cap, SAMPLE.length / ((wpmHi * 5) / 60)));
  const typeHi = $derived(Math.min(cap, SAMPLE.length / ((wpmLo * 5) / 60)));

  const mid = (a: number, b: number) => (a + b) / 2;
  const parts = $derived([
    { label: "Reading", lo: readLo, hi: readHi, cls: "is-read" },
    { label: "Thinking", lo: thinkLo, hi: thinkHi, cls: "is-think" },
    { label: "Typing", lo: typeLo, hi: typeHi, cls: "is-type" },
  ]);
  const total = $derived(parts.reduce((s, p) => s + mid(p.lo, p.hi), 0) || 1);
  const fmt = (s: number) => (s >= 10 ? `${Math.round(s)}` : `${+s.toFixed(1)}`);
</script>

<div class="tp">
  <div class="flex flex-wrap items-baseline justify-between gap-2">
    <span class="text-[12.5px] font-medium text-ink">What a DM reply looks like</span>
    {#if on}
      <span class="text-[11.5px] text-muted">
        about <b class="text-ink">{fmt(parts.reduce((s, p) => s + p.lo, 0))}–{fmt(parts.reduce((s, p) => s + p.hi, 0))} s</b> from their message to yours
      </span>
    {/if}
  </div>
  <div class="tp-msg">“{SAMPLE}”</div>
  {#if on}
    <div class="tp-bar" role="img" aria-label="Reading, thinking and typing times">
      {#each parts as p}
        <span class="tp-seg {p.cls}" style="flex-grow:{mid(p.lo, p.hi) / total}"></span>
      {/each}
    </div>
    <div class="tp-legend">
      {#each parts as p}
        <span class="tp-key">
          <span class="tp-dot {p.cls}"></span>
          {p.label} <b>{fmt(p.lo)}–{fmt(p.hi)} s</b>
        </span>
      {/each}
      <span class="tp-key text-faint">at {Math.round(wpmLo)}–{Math.round(wpmHi)} words a minute</span>
    </div>
  {:else}
    <p class="mt-2 text-[12px] text-muted">
      Realistic typing is off, so replies go out as soon as they are written: no read delay, no typing indicator.
    </p>
  {/if}
</div>

<style>
  .tp {
    margin-top: 14px;
    padding: 14px 16px;
    border-radius: 16px;
    background: rgb(255 255 255 / 0.022);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
  }
  .tp-msg {
    margin-top: 8px;
    font-size: 12.5px;
    font-style: italic;
    color: var(--color-muted);
  }
  .tp-bar {
    display: flex;
    gap: 2px;
    height: 10px;
    margin-top: 10px;
    overflow: hidden;
    border-radius: 999px;
  }
  .tp-seg {
    min-width: 6px;
    flex-basis: 0;
    transition: flex-grow 0.35s var(--spring);
  }
  /* One hue, three steps: they are stages of one thing, not three things. */
  .is-read { background: color-mix(in srgb, var(--color-accent) 35%, transparent); }
  .is-think { background: color-mix(in srgb, var(--color-accent) 62%, transparent); }
  .is-type { background: var(--color-accent); }
  .tp-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 16px;
    margin-top: 9px;
    font-size: 11.5px;
    color: var(--color-muted);
  }
  .tp-legend b { font-weight: 600; color: var(--color-ink); font-variant-numeric: tabular-nums; }
  .tp-key { display: inline-flex; align-items: center; gap: 6px; }
  .tp-dot { width: 8px; height: 8px; border-radius: 3px; }
  :global(:root[data-motion="off"]) .tp-seg { transition: none; }
</style>
