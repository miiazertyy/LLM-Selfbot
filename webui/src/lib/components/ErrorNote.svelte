<script lang="ts">
  import Icon from "./Icon.svelte";
  /** Shown when a page's data fails to load, so the failure reads as an error
      rather than an empty box that never fills in. */
  let { text = "", onretry } = $props<{ text?: string; onretry?: () => void }>();
</script>

{#if text}
  <div class="pop mb-4 flex items-center gap-3 rounded-xl border border-bad/30 bg-bad/[0.07] px-4 py-3">
    <Icon name="alert" size={16} class="shrink-0 text-bad" />
    <span class="min-w-0 flex-1 text-[12px] text-bad">{text}</span>
    {#if onretry}
      <button class="jelly rounded-lg px-2 py-1 text-[11px] text-bad hover:bg-bad/15" onclick={onretry}>
        Retry
      </button>
    {/if}
  </div>
{/if}
