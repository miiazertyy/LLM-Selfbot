<script lang="ts">
  /**
   * A small ring that says how far along something is - or, when that is not
   * known, that it is still going.
   *
   * With `total`, the ring is filled to exactly done/total: a job of eight
   * steps moves it eight times, 27 out of 100 fills 27% of it. Each move glides
   * rather than jumps, so a step reads as progress instead of a flicker.
   * Without it, an arc turns. The two are deliberately different shapes, so a
   * spinner is never mistaken for a ring stuck at some percentage.
   *
   * Colour comes from `currentColor`, so the caller decides: accent while
   * working, amber when it is taking too long.
   */
  let {
    done = null,
    total = null,
    size = 13,
  }: { done?: number | null; total?: number | null; size?: number } = $props();

  const R = 6;
  const C = 2 * Math.PI * R;
  const frac = $derived(
    total !== null && total > 0 && done !== null
      ? Math.max(0, Math.min(1, done / total))
      : null,
  );
</script>

<svg class="pring" class:spin={frac === null} viewBox="0 0 16 16" width={size} height={size}
     aria-hidden="true">
  <circle class="track" cx="8" cy="8" r={R} />
  {#if frac === null}
    <path class="arc" d="M8 2 a6 6 0 0 1 6 6" />
  {:else}
    <!-- Starts at twelve o'clock and fills clockwise, like a clock hand. -->
    <circle class="fill" cx="8" cy="8" r={R} transform="rotate(-90 8 8)"
            stroke-dasharray={C} stroke-dashoffset={C * (1 - frac)} />
  {/if}
</svg>

<style>
  .pring {
    display: block;
    flex: 0 0 auto;
    overflow: visible;
  }
  .track,
  .arc,
  .fill {
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
  }
  .track {
    opacity: 0.18;
  }
  .arc,
  .fill {
    stroke-linecap: round;
  }
  .fill {
    /* A slight overshoot, so each step lands rather than slides. */
    transition: stroke-dashoffset 0.45s cubic-bezier(0.34, 1.3, 0.64, 1);
  }
  .spin {
    animation: pring-turn 0.85s linear infinite;
  }
  @keyframes pring-turn {
    to {
      transform: rotate(360deg);
    }
  }
  /* The app's Motion switch decides, not Windows' animation effects: those are
     off on plenty of PCs, and a ring that stops turning reads as stuck (stores.ts). */
  :global(:root[data-motion="off"]) .spin {
    animation: none;
  }
  :global(:root[data-motion="off"]) .fill {
    transition: none;
  }
</style>
