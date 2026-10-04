<script lang="ts">
  /**
   * A choice of two or three, as one control with a pill that slides to the
   * one picked. The pill is one element moving, not a background appearing on
   * one button and vanishing from the other, so the eye follows it across.
   * Each choice can bring its own colour (a platform's), which the pill takes
   * on as it arrives.
   */
  import Icon from "./Icon.svelte";
  import { play } from "../uisound";

  type Option = { id: string; label: string; icon?: string; tone?: string };

  let {
    options,
    value = $bindable(""),
    label,
    onchange,
  }: {
    options: Option[];
    value?: string;
    /** What the choice is, for screen readers. */
    label: string;
    onchange?: (id: string) => void;
  } = $props();

  const at = $derived(Math.max(0, options.findIndex((o) => o.id === value)));
  const tone = $derived(options[at]?.tone ?? "var(--color-accent)");

  function pick(id: string) {
    if (id === value) return;
    play("select");
    value = id;
    onchange?.(id);
  }

  /** Arrow keys move the choice, the way a radio group does. */
  function key(e: KeyboardEvent) {
    const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const next = options[(at + d + options.length) % options.length];
    pick(next.id);
    (e.currentTarget as HTMLElement).querySelectorAll<HTMLElement>("button")[options.indexOf(next)]?.focus();
  }
</script>

<div class="sg" data-sound="self" role="radiogroup" aria-label={label} tabindex="-1" onkeydown={key}
     style="--n: {options.length}; --at: {at}; --tone: {tone}">
  <span class="sg-pill" aria-hidden="true"></span>
  {#each options as o (o.id)}
    <button type="button" role="radio" aria-checked={value === o.id} tabindex={value === o.id ? 0 : -1}
            class="sg-btn" class:is-on={value === o.id} onclick={() => pick(o.id)}>
      {#if o.icon}<Icon name={o.icon} size={15} />{/if}{o.label}
    </button>
  {/each}
</div>

<style>
  .sg {
    position: relative;
    display: grid;
    grid-template-columns: repeat(var(--n), 1fr);
    padding: 4px;
    border-radius: 13px;
    background: rgb(0 0 0 / 0.22);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    outline: none;
  }
  .sg-pill {
    position: absolute;
    top: 4px;
    bottom: 4px;
    left: 4px;
    width: calc((100% - 8px) / var(--n));
    border-radius: 10px;
    background: color-mix(in srgb, var(--tone) 20%, transparent);
    box-shadow:
      inset 0 0 0 1px color-mix(in srgb, var(--tone) 50%, transparent),
      0 6px 18px -8px color-mix(in srgb, var(--tone) 70%, transparent);
    transform: translateX(calc(var(--at) * 100%));
    transition:
      transform 0.5s var(--jelly),
      background-color 0.35s var(--swift),
      box-shadow 0.35s var(--swift);
  }
  .sg-btn {
    position: relative;
    display: inline-flex;
    height: 36px;
    align-items: center;
    justify-content: center;
    gap: 7px;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 600;
    color: var(--color-muted);
    transition: color 0.25s ease, transform 0.35s var(--jelly);
  }
  .sg-btn :global(svg) { transition: transform 0.45s var(--jelly), color 0.25s ease; }
  .sg-btn:hover { color: var(--color-ink); }
  .sg-btn:active { transform: scale(0.96); }
  .sg-btn.is-on { color: var(--color-ink); }
  .sg-btn.is-on :global(svg) { color: var(--tone); transform: scale(1.12); }
  .sg-btn:focus-visible { outline: none; box-shadow: 0 0 0 2px color-mix(in srgb, var(--tone) 60%, transparent); }

  :global(:root[data-motion="off"]) .sg-pill,
  :global(:root[data-motion="off"]) .sg-btn,
  :global(:root[data-motion="off"]) .sg-btn :global(svg) { transition: none; }
</style>
