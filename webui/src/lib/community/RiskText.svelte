<script lang="ts">
  /**
   * A profile's text, as text, with anything risky lit (a link, an email, a handle, one of your usernames), each
   * named on hover. Long ones open to their full length on a press.
   */
  import { riskLabel } from "./logic";
  import { play } from "../uisound";

  let { segments = [], collapsed = true }: {
    segments?: { text: string; kind?: string }[];
    collapsed?: boolean;
  } = $props();

  let open = $state(false);
  const long = $derived(segments.reduce((n, s) => n + s.text.length, 0) > 900);
</script>

<div class="rt" class:is-short={collapsed && long && !open}>
  <p class="rt-text">{#each segments as s, i (i)}{#if s.kind}<mark class="rt-mark is-{s.kind}" title={riskLabel(s.kind)}>{s.text}</mark>{:else}{s.text}{/if}{/each}</p>
  {#if collapsed && long}
    <button type="button" class="rt-more" data-sound="self" onclick={() => { open = !open; play(open ? "open" : "slide", { level: 0.5 }); }}>
      {open ? "Show less" : "Show all of it"}
    </button>
  {/if}
</div>

<style>
  .rt { position: relative; }
  .rt-text {
    margin: 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-size: 12.5px;
    line-height: 1.6;
    color: var(--color-muted);
  }
  .rt.is-short .rt-text {
    max-height: 15.5em;
    overflow: hidden;
    -webkit-mask-image: linear-gradient(to bottom, #000 70%, transparent);
    mask-image: linear-gradient(to bottom, #000 70%, transparent);
  }
  .rt-mark {
    padding: 0 3px;
    border-radius: 5px;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-warn) 22%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-warn) 45%, transparent);
  }
  .rt-mark.is-handle, .rt-mark.is-yours {
    background: color-mix(in srgb, var(--color-accent) 18%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 40%, transparent);
  }
  .rt-more {
    margin-top: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 11.5px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 10%, transparent);
    transition: background-color 0.15s ease;
  }
  .rt-more:hover { background: color-mix(in srgb, var(--color-accent) 18%, transparent); }
  :global(:root[data-motion="off"]) .rt-more { transition: none; }
</style>
