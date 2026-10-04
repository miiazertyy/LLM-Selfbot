<script lang="ts">
  import Icon from "./Icon.svelte";
  /** Shown when a page's data fails to load, so the failure reads as an error
      rather than an empty box that never fills in. Drawn like the notices in
      IssueList, so the app has one way of saying something went wrong. */
  let { text = "", onretry } = $props<{ text?: string; onretry?: () => void }>();
</script>

{#if text}
  <div class="err pop" role="alert">
    <span class="err-icon"><Icon name="alertCircle" size={16} /></span>
    <div class="min-w-0 flex-1">
      <div class="text-[13.5px] font-semibold text-ink">Could not load this</div>
      <p class="mt-0.5 break-words text-[12px] leading-relaxed text-muted">{text}</p>
    </div>
    {#if onretry}
      <button class="err-btn" onclick={onretry}>
        <Icon name="refresh" size={12} />Try again
      </button>
    {/if}
  </div>
{/if}

<style>
  .err {
    position: relative;
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    padding: 12px 14px 12px 16px;
    border-radius: 16px;
    background:
      linear-gradient(90deg, color-mix(in srgb, var(--color-bad) 10%, transparent), transparent 70%),
      color-mix(in srgb, var(--color-card) 55%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-bad) 30%, var(--color-edge));
  }
  .err::before {
    content: "";
    position: absolute;
    left: 0;
    top: 10px;
    bottom: 10px;
    width: 3px;
    border-radius: 0 3px 3px 0;
    background: var(--color-bad);
  }
  .err-icon {
    display: grid;
    width: 32px;
    height: 32px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 10px;
    color: var(--color-bad);
    background: color-mix(in srgb, var(--color-bad) 15%, transparent);
  }
  .err-btn {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 5px;
    padding: 6px 12px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 600;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-bad) 16%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-bad) 35%, transparent);
    transition: background-color 0.15s ease;
  }
  .err-btn:hover { background: color-mix(in srgb, var(--color-bad) 26%, transparent); }
</style>
