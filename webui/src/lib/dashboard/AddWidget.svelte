<script lang="ts">
  /**
   * Everything that can go on the Dashboard, to pick from - each one shown as
   * it will actually look.
   *
   * The gallery was a name, an icon and a sentence, which asks you to imagine
   * the widget. Each card now carries the real thing: the same WidgetBody the
   * Dashboard draws, fed the same live data, laid out at the width it will
   * have and scaled down to fit. A mock-up would drift from the widget the
   * first time either changed; this cannot, and it shows your own numbers.
   *
   * The previews are inert - looking, not using - so nothing in them can be
   * clicked by accident while choosing.
   *
   * A widget that only makes sense once (the accounts, the headline figures)
   * says so when it is already there, rather than quietly adding a duplicate.
   * The ones that take a time window can be added again, set to another one.
   */
  import Modal from "../components/Modal.svelte";
  import Icon from "../components/Icon.svelte";
  import type { WidgetInstance } from "../stores";
  import WidgetBody from "./WidgetBody.svelte";
  import { WIDGETS, makeInstance } from "./widgets";

  let {
    open = $bindable(false),
    layout,
    ctx,
    onadd,
  }: { open?: boolean; layout: WidgetInstance[]; ctx: any; onadd: (type: string) => void } = $props();

  const placed = $derived(new Set(layout.map((w) => w.type)));

  // One sample placement per type, made once, so previews keep their state
  // while the gallery is open rather than being rebuilt on every refresh.
  const samples = Object.fromEntries(Object.keys(WIDGETS).map((t) => [t, makeInstance(t)]));

  // The width each lays itself out at before being scaled: what it gets on
  // the Dashboard at half or full width, near enough.
  const NATURAL = { half: 440, full: 760 } as const;

  let widths = $state<Record<string, number>>({});
  // clientWidth includes the preview's 12px padding on each side; the widget
  // has to fit inside it, not the whole box, or it is cut off on the right.
  const PAD = 24;
  const scaleFor = (type: string, natural: number) =>
    Math.min(1, Math.max(0.1, ((widths[type] ?? 0) - PAD) / natural));
</script>

<Modal bind:open title="Add a widget" wide onclose={() => (open = false)}>
  <p class="-mt-1 mb-4 text-[12px] text-faint">Previews use your own data, as it is right now.</p>
  <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
    {#each Object.values(WIDGETS) as w (w.type)}
      {@const taken = placed.has(w.type) && !w.multiple}
      {@const natural = NATURAL[w.size]}
      <!-- Not a <button> itself: the preview holds the widget's own buttons,
           and a button inside a button is invalid. One transparent button
           over the whole card does the clicking instead. -->
      <div class="add-card text-left" class:is-taken={taken}>
        <!-- The widget itself, laid out at its real width and shrunk to fit. -->
        <span class="add-preview" bind:clientWidth={widths[w.type]} aria-hidden="true">
          {#if open && widths[w.type]}
            <span
              class="add-stage @container"
              style="width:{natural}px; transform:scale({scaleFor(w.type, natural)})"
              inert
            >
              <WidgetBody inst={samples[w.type]} {ctx} />
            </span>
          {/if}
          {#if taken}
            <span class="add-flag">Already on your Dashboard</span>
          {/if}
        </span>

        <span class="flex items-start gap-3 px-3.5 pb-3.5 pt-3">
          <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent/12 text-accent">
            <Icon name={w.icon} size={15} />
          </span>
          <span class="min-w-0 flex-1">
            <span class="flex items-center gap-2">
              <span class="text-[13px] font-semibold text-ink">{w.title}</span>
              <span class="rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-faint">
                {w.size === "full" ? "full width" : "half width"}
              </span>
              {#if placed.has(w.type) && !taken}
                <span class="text-[10px] text-faint">add another</span>
              {/if}
            </span>
            <span class="mt-0.5 block text-[11.5px] leading-relaxed text-muted">{w.blurb}</span>
          </span>
          {#if !taken}
            <span class="add-plus mt-0.5 shrink-0"><Icon name="plus" size={14} /></span>
          {/if}
        </span>
        <button
          class="add-hit"
          disabled={taken}
          aria-label={taken ? `${w.title} is already on your Dashboard` : `Add ${w.title}`}
          onclick={() => { onadd(w.type); open = false; }}
        ></button>
      </div>
    {/each}
  </div>
</Modal>

<style>
  .add-card {
    position: relative;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border-radius: 16px;
    background: rgb(255 255 255 / 0.02);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    transition: box-shadow 0.2s ease, background-color 0.2s ease, transform 0.3s var(--spring);
  }
  .add-card:not(.is-taken):hover {
    background: color-mix(in srgb, var(--color-accent) 5%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 50%, transparent),
                0 10px 30px -18px color-mix(in srgb, var(--color-accent) 70%, transparent);
    transform: translateY(-2px);
  }
  .add-card.is-taken {
    cursor: default;
  }
  .add-card.is-taken .add-preview {
    filter: grayscale(0.6);
    opacity: 0.55;
  }

  /* The window onto the preview: fixed height, the widget scaled into it from
     the top left, fading out at the bottom so a cut-off widget reads as
     "there is more" rather than as broken. */
  .add-preview {
    position: relative;
    display: block;
    height: 158px;
    overflow: hidden;
    padding: 12px 12px 0;
    background:
      radial-gradient(120% 90% at 0% 0%, color-mix(in srgb, var(--color-accent) 9%, transparent), transparent 60%),
      rgb(0 0 0 / 0.18);
    border-bottom: 1px solid color-mix(in srgb, var(--color-edge) 70%, transparent);
    -webkit-mask-image: linear-gradient(to bottom, #000 72%, transparent);
    mask-image: linear-gradient(to bottom, #000 72%, transparent);
    pointer-events: none;
  }
  .add-stage {
    position: absolute;
    top: 12px;
    left: 12px;
    display: block;
    transform-origin: top left;
    transition: transform 0.35s var(--spring);
  }
  .add-card:not(.is-taken):hover .add-stage {
    /* A small push in on hover: the preview is the thing you are choosing. */
    filter: brightness(1.08);
  }
  .add-flag {
    position: absolute;
    top: 10px;
    right: 10px;
    padding: 3px 8px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 600;
    color: var(--color-ink);
    background: rgb(0 0 0 / 0.55);
  }

  .add-hit {
    position: absolute;
    inset: 0;
    border-radius: inherit;
    cursor: pointer;
  }
  .add-hit:disabled {
    cursor: default;
  }
  .add-hit:focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 2px;
  }
  .add-card:active:not(.is-taken) {
    transform: scale(0.99);
  }

  .add-plus {
    display: flex;
    width: 26px;
    height: 26px;
    align-items: center;
    justify-content: center;
    border-radius: 9px;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.05);
    transition: transform 0.25s var(--spring), color 0.15s ease, background-color 0.15s ease;
  }
  .add-card:hover .add-plus {
    color: var(--color-bg);
    background: var(--color-accent);
    transform: rotate(90deg);
  }
</style>
