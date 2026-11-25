<script lang="ts">
  /**
   * A choice of two or three, as one control with a pill that slides to the
   * one picked. The pill is one element moving, not a background appearing on
   * one button and vanishing from the other, so the eye follows it across.
   * Each choice can bring its own colour (a platform's), which the pill takes
   * on as it arrives, and its own face (a profile's) in place of an icon.
   *
   * "sm" is the one for a bar of buttons: as tall as they are (36px), and flat
   * like them, a tint with no ring round the track or the pill.
   */
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";
  import { play } from "../uisound";

  type Option = { id: string; label: string; icon?: string; tone?: string; face?: Snippet };

  let {
    options,
    value = $bindable(""),
    label,
    size = "md",
    onchange,
  }: {
    options: Option[];
    value?: string;
    /** What the choice is, for screen readers. */
    label: string;
    size?: "md" | "sm";
    onchange?: (id: string) => void;
  } = $props();

  const at = $derived(Math.max(0, options.findIndex((o) => o.id === value)));
  /** Five or six, each with its icon (the platforms): in a narrow window only the icons fit, each still named. */
  const many = $derived(options.length >= 5 && options.every((o) => !!o.icon));
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

<div class="sg" class:is-many={many} class:is-sm={size === "sm"} data-sound="self" role="radiogroup" aria-label={label}
     tabindex="-1" onkeydown={key} style="--n: {options.length}; --at: {at}; --tone: {tone}">
  <span class="sg-pill" aria-hidden="true"></span>
  {#each options as o (o.id)}
    <button type="button" role="radio" aria-checked={value === o.id} tabindex={value === o.id ? 0 : -1}
            class="sg-btn" class:is-on={value === o.id} onclick={() => pick(o.id)}
            aria-label={many ? o.label : undefined} title={many ? o.label : undefined}>
      {#if o.face}<span class="sg-face">{@render o.face()}</span>{:else if o.icon}<Icon name={o.icon} size={15} />{/if}<span
        class="sg-label">{o.label}</span>
    </button>
  {/each}
</div>

<style>
  .sg {
    --sg-pad: 4px;
    position: relative;
    display: grid;
    grid-template-columns: repeat(var(--n), 1fr);
    padding: var(--sg-pad);
    border-radius: 13px;
    background: rgb(0 0 0 / 0.22);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    outline: none;
  }
  .sg-pill {
    position: absolute;
    top: var(--sg-pad);
    bottom: var(--sg-pad);
    left: var(--sg-pad);
    width: calc((100% - 2 * var(--sg-pad)) / var(--n));
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
  /* Room either side of the words: a switch as wide as its words had them touching the pill's edges. Where it is
     narrower than that, the words keep one line and spread into the room, centred. */
  .sg-btn {
    position: relative;
    display: inline-flex;
    height: 36px;
    min-width: 0;
    align-items: center;
    justify-content: center;
    gap: 7px;
    padding: 0 12px;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 600;
    color: var(--color-muted);
    transition: color 0.25s ease, transform 0.35s var(--jelly);
  }
  .sg-label { white-space: nowrap; }
  .sg-btn :global(svg) { transition: transform 0.45s var(--jelly), color 0.25s ease; }
  .sg-btn:hover { color: var(--color-ink); }
  .sg-btn:active { transform: scale(0.96); }
  .sg-btn.is-on { color: var(--color-ink); }
  .sg-btn.is-on :global(svg) { color: var(--tone); transform: scale(1.12); }
  .sg-btn:focus-visible { outline: none; box-shadow: 0 0 0 2px color-mix(in srgb, var(--tone) 60%, transparent); }
  /* A face (a profile's), quieter until picked, like an icon. */
  .sg-face {
    display: inline-grid;
    flex-shrink: 0;
    opacity: 0.7;
    transition: opacity 0.25s ease, transform 0.45s var(--jelly);
  }
  .sg-btn:hover .sg-face { opacity: 0.9; }
  .sg-btn.is-on .sg-face { opacity: 1; transform: scale(1.08); }
  /* Five or six platforms: their names fit no dialog at any width - on a computer "Minecraft" ran under the button
     beside it, on a phone the row ran off the screen - so each is its mark alone, named aloud, on hover, and in the
     card above as it is picked. Plain CSS, no query: an older phone web view draws it the same. */
  .sg.is-many .sg-btn { gap: 0; padding: 0; }
  .sg.is-many .sg-label { display: none; }
  .sg.is-many .sg-btn :global(svg) { width: 18px; height: 18px; }

  /* In a bar of buttons: their height, and flat like them. The track is tinted as they are, the pill a deeper tint
     of the choice's colour, with no ring round either. A long name ends in "…" rather than running out. */
  .sg.is-sm {
    --sg-pad: 3px;
    border-radius: 12px;
    background: color-mix(in srgb, var(--color-accent) 7%, rgb(255 255 255 / 0.03));
    box-shadow: none;
  }
  .sg.is-sm .sg-pill {
    border-radius: 9px;
    background: color-mix(in srgb, var(--tone) 24%, transparent);
    box-shadow: 0 6px 16px -10px color-mix(in srgb, var(--tone) 80%, transparent);
  }
  .sg.is-sm .sg-btn { height: 30px; padding: 0 10px; border-radius: 9px; font-size: 12.5px; }
  .sg.is-sm .sg-label { min-width: 0; max-width: 12em; overflow: hidden; text-overflow: ellipsis; }

  :global(:root[data-motion="off"]) .sg-pill,
  :global(:root[data-motion="off"]) .sg-btn,
  :global(:root[data-motion="off"]) .sg-face,
  :global(:root[data-motion="off"]) .sg-btn :global(svg) { transition: none; }
</style>
