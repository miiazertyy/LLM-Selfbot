<script lang="ts">
  /**
   * One row of the log (lib/logrows.ts): when, an icon for what kind of thing
   * it was, who it came from by name and picture, and what it said, with a
   * message that came in or went out quoted under it and a model's thinking
   * folded until it is opened. The Logs page and the Dashboard's log widget
   * draw the same rows, so the two look alike.
   */
  import Icon from "./Icon.svelte";
  import { highlight } from "../search";
  import { ICON, type LogRow } from "../logrows";

  let {
    row,
    who,
    q = "",
    open = false,
    fresh = false,
    compact = false,
    ontoggle,
    onmenu,
  }: {
    row: LogRow;
    who: { name: string; avatar?: string };
    /** A search: its words are marked in the text. */
    q?: string;
    open?: boolean;
    /** Slides in: only a line that just arrived, never the whole list again after a filter. */
    fresh?: boolean;
    /** One line per entry. */
    compact?: boolean;
    ontoggle?: () => void;
    /** Right-click on the row: where it was clicked. Without it, no menu. */
    onmenu?: (e: MouseEvent) => void;
  } = $props();
</script>

<div class="lg-row" data-kind={row.level} class:is-open={open} class:is-new={fresh} class:is-compact={compact}
     onclick={() => ontoggle?.()} oncontextmenu={(e) => onmenu?.(e)} role="button" tabindex="0"
     onkeydown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), ontoggle?.())}>
  <span class="lg-time">{row.time}</span>
  <span class="lg-icon"><Icon name={ICON[row.level] ?? "logs"} size={12} /></span>
  <span class="lg-body">
    <span class="lg-line">
      <span class="lg-who">{#if who.avatar}<img src={who.avatar} alt="" />{/if}{who.name}</span>
      <span class="lg-text">{#if q}{@html highlight(row.text, q)}{:else}{row.text}{/if}</span>
    </span>
    {#if row.more.length}
      <span class="lg-quote">
        {#each row.more as m}<span class="block">{#if q}{@html highlight(m, q)}{:else}{m}{/if}</span>{/each}
      </span>
    {/if}
    {#if row.think}
      {#if open}
        <span class="lg-think">{row.think.body}</span>
      {:else if row.think.body}
        <span class="lg-think-peek">{row.think.body.split("\n")[0]} <em>· click to read</em></span>
      {/if}
    {/if}
  </span>
</div>

<style>
  [data-kind="error"] { --k: var(--color-bad); }
  [data-kind="warn"] { --k: var(--color-warn); }
  [data-kind="recv"] { --k: var(--color-accent-2); }
  [data-kind="reply"] { --k: var(--color-good); }
  [data-kind="think"] { --k: color-mix(in srgb, var(--color-accent) 50%, #e879f9); }
  [data-kind="system"] { --k: var(--color-accent); }
  [data-kind="info"] { --k: var(--color-faint); }

  .lg-row {
    position: relative;
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 7px 10px 7px 12px;
    border-radius: 11px;
    cursor: pointer;
    transition: background-color 0.12s ease;
    contain: layout paint;
  }
  .lg-row:hover { background: rgb(255 255 255 / 0.035); }
  .lg-row.is-open { background: rgb(255 255 255 / 0.05); }
  .lg-row.is-new { animation: lg-in 0.35s var(--spring) both; }
  /* Problems are the thing to spot at a glance: a tinted row, not only a colour dot. */
  .lg-row[data-kind="error"] { background: color-mix(in srgb, var(--color-bad) 7%, transparent); }
  .lg-row[data-kind="warn"] { background: color-mix(in srgb, var(--color-warn) 5%, transparent); }
  .lg-row[data-kind="error"]::before, .lg-row[data-kind="warn"]::before {
    content: "";
    position: absolute;
    left: 2px;
    top: 8px;
    bottom: 8px;
    width: 2.5px;
    border-radius: 999px;
    background: var(--k);
  }
  .lg-time {
    flex-shrink: 0;
    padding-top: 2px;
    font-family: ui-monospace, monospace;
    font-size: 11px;
    color: var(--color-faint);
    font-variant-numeric: tabular-nums;
  }
  .lg-icon {
    display: grid;
    width: 22px;
    height: 22px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 7px;
    color: var(--k);
    background: color-mix(in srgb, var(--k) 14%, transparent);
  }
  .lg-body { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 3px; padding-top: 1px; }
  .lg-line { display: flex; min-width: 0; align-items: baseline; gap: 8px; }
  .lg-who {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 5px;
    max-width: 140px;
    overflow: hidden;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--color-muted);
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .lg-who img { width: 14px; height: 14px; border-radius: 999px; object-fit: cover; }
  .lg-text {
    min-width: 0;
    font-size: 13px;
    line-height: 1.45;
    color: color-mix(in srgb, var(--color-ink) 90%, transparent);
    word-break: break-word;
  }
  .lg-row[data-kind="error"] .lg-text { color: color-mix(in srgb, var(--color-bad) 70%, var(--color-ink)); }
  .lg-row[data-kind="warn"] .lg-text { color: color-mix(in srgb, var(--color-warn) 65%, var(--color-ink)); }
  .lg-row[data-kind="info"] .lg-text { color: var(--color-muted); }
  .lg-quote {
    padding: 5px 10px;
    border-left: 2px solid color-mix(in srgb, var(--k) 60%, transparent);
    border-radius: 0 9px 9px 0;
    font-size: 12.5px;
    line-height: 1.45;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.03);
    word-break: break-word;
  }
  .lg-think-peek { overflow: hidden; font-size: 12px; font-style: italic; color: var(--color-faint); white-space: nowrap; text-overflow: ellipsis; }
  .lg-think-peek em { color: color-mix(in srgb, var(--color-accent) 60%, #e879f9); }
  .lg-think {
    padding: 8px 11px;
    border-left: 2px solid var(--k);
    border-radius: 0 9px 9px 0;
    font-size: 12.5px;
    font-style: italic;
    line-height: 1.55;
    white-space: pre-wrap;
    color: color-mix(in srgb, var(--color-ink) 80%, transparent);
    background: color-mix(in srgb, var(--k) 7%, transparent);
    animation: lg-in 0.25s ease both;
  }
  .lg-row.is-compact { padding-top: 4px; padding-bottom: 4px; }
  .lg-row.is-compact .lg-text { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .lg-row.is-compact .lg-quote { overflow: hidden; padding-top: 2px; padding-bottom: 2px; white-space: nowrap; text-overflow: ellipsis; }
  .lg-row.is-compact.is-open .lg-text, .lg-row.is-compact.is-open .lg-quote { white-space: normal; }
  .lg-row :global(mark) { border-radius: 3px; color: var(--color-bg); background: var(--color-accent); }

  @keyframes lg-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  :global(:root[data-motion="off"]) .lg-row.is-new,
  :global(:root[data-motion="off"]) .lg-think { animation: none; }
  @media (max-width: 640px) {
    .lg-time { display: none; }
    .lg-who { max-width: 90px; }
  }
  /* In a narrow box (a half-width Dashboard widget): the time gives way first, then the name gets shorter. */
  @container (max-width: 460px) {
    .lg-time { display: none; }
  }
  @container (max-width: 340px) {
    .lg-who { max-width: 84px; }
  }
</style>
