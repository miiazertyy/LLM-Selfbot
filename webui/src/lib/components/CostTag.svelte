<script lang="ts">
  /**
   * Free, Some free or Paid, for a provider or a model. For someone who has
   * never heard of these services, "which of these can I use without paying"
   * is the first question, and the list did not answer it.
   */
  let { cost, note = "", small = false }: { cost: string; note?: string; small?: boolean } = $props();
  const LABEL: Record<string, string> = { free: "Free", some: "Some free", paid: "Paid" };
</script>

<span class="cost" class:is-small={small} data-cost={cost} title={note || undefined}>{LABEL[cost] ?? cost}</span>

<style>
  .cost {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    padding: 1px 7px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.01em;
    line-height: 1.5;
  }
  .cost.is-small { padding: 0 6px; font-size: 10px; }
  .cost[data-cost="free"] {
    color: var(--color-good);
    background: color-mix(in srgb, var(--color-good) 14%, transparent);
  }
  .cost[data-cost="some"] {
    color: var(--color-accent-2);
    background: color-mix(in srgb, var(--color-accent-2) 14%, transparent);
  }
  .cost[data-cost="paid"] {
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.06);
  }
</style>
