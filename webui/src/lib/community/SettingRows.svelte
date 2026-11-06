<script lang="ts">
  /**
   * A profile's settings, each with its name, its value and yours beside it. One it may not bring says so, and why;
   * one the same as yours is quiet.
   */
  import Icon from "../components/Icon.svelte";
  import { valueText } from "./logic";

  type Row = { key: string; label: string; value: unknown; yours?: unknown; same?: boolean; ok?: boolean; why?: string };
  let { rows = [], showYours = true }: { rows?: Row[]; showYours?: boolean } = $props();
</script>

{#if rows.length}
  <ul class="sr">
    {#each rows as r (r.key)}
      <li class="sr-row" class:is-off={r.ok === false} class:is-same={r.same}>
        <span class="sr-label" title={r.key}>{r.label}</span>
        <span class="sr-value">{valueText(r.value)}</span>
        {#if r.ok === false}
          <span class="sr-note"><Icon name="close" size={10} />Left out: {r.why}</span>
        {:else if showYours && "yours" in r}
          <span class="sr-note">{r.same ? "Same as yours" : `Yours: ${valueText(r.yours)}`}</span>
        {/if}
      </li>
    {/each}
  </ul>
{:else}
  <p class="sr-none">Nothing to change. It talks with your settings.</p>
{/if}

<style>
  .sr { display: grid; gap: 2px; margin: 0; padding: 0; list-style: none; }
  .sr-row {
    display: grid;
    grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) auto;
    gap: 10px;
    align-items: baseline;
    padding: 7px 10px;
    border-radius: 10px;
    font-size: 12.5px;
    background: rgb(255 255 255 / 0.02);
  }
  .sr-label { overflow: hidden; color: var(--color-ink); text-overflow: ellipsis; white-space: nowrap; }
  .sr-value { overflow: hidden; color: var(--color-accent); text-overflow: ellipsis; white-space: nowrap; }
  .sr-note { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; color: var(--color-faint); white-space: nowrap; }
  .sr-row.is-same .sr-value { color: var(--color-muted); }
  .sr-row.is-off { opacity: 0.6; }
  .sr-row.is-off .sr-value { text-decoration: line-through; color: var(--color-faint); }
  .sr-none { margin: 0; font-size: 12.5px; color: var(--color-faint); }
  @media (max-width: 560px) {
    .sr-row { grid-template-columns: minmax(0, 1fr) auto; }
    .sr-note { grid-column: 1 / -1; }
  }
</style>
