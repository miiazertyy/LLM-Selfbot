<script lang="ts">
  /**
   * A note at the foot of a page or a panel: what is worth knowing about what
   * is above it ("Saving applies the change straight away", "Installs into
   * ..."). These were faint 11px lines left on their own, which read as an
   * afterthought and wrapped awkwardly round anything inline. Now each sits in
   * a soft strip, a small icon at its side saying what kind of note it is, in
   * text that can be read; "warn" for a caution (a backup holds your keys).
   */
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";

  let { icon = "info", tone = "", class: cls = "", children }: {
    icon?: string;
    tone?: "" | "warn";
    class?: string;
    children: Snippet;
  } = $props();
</script>

<div class="fn {cls}" class:is-warn={tone === "warn"}>
  <span class="fn-icon" aria-hidden="true"><Icon name={icon} size={13} /></span>
  <p class="fn-text">{@render children()}</p>
</div>

<style>
  .fn {
    --fn-tone: var(--color-accent);
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 14px 10px 10px;
    border-radius: 13px;
    background:
      linear-gradient(90deg, color-mix(in srgb, var(--fn-tone) 9%, transparent), transparent 70%),
      rgb(255 255 255 / 0.018);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 60%, transparent);
  }
  .fn.is-warn { --fn-tone: var(--color-warn); }
  .fn-icon {
    display: grid;
    width: 24px;
    height: 24px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 8px;
    color: var(--fn-tone);
    background: color-mix(in srgb, var(--fn-tone) 13%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--fn-tone) 22%, transparent);
  }
  .fn-text {
    min-width: 0;
    align-self: center;
    font-size: 12px;
    line-height: 1.55;
    color: var(--color-muted);
  }
  .fn-text :global(code) {
    padding: 1px 6px;
    border-radius: 6px;
    font-size: 11px;
    word-break: break-all;
    color: var(--color-ink);
    background: rgb(0 0 0 / 0.25);
  }
  .fn-text :global(b) { font-weight: 600; color: var(--color-ink); }
</style>
