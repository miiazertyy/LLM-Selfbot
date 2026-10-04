<script lang="ts">
  /**
   * "Deleted IMG_1.jpg · Undo", centred along the bottom of the page.
   *
   * Moved to <body>, so no page wrapper with a transform or a backdrop filter
   * becomes what "fixed" is fixed to, and centred by a row rather than by a
   * translate. It used to be a translate, which the entrance animation's own
   * translate added to, so the bar sat a whole width to the left of the
   * middle. The row spans the page, not the window: spanning the window put
   * the bar in the middle of the window, which with the sidebar on the left
   * is well left of the middle of the page it is about.
   *
   * What went is shown when it can be: the picture itself, or a small pile of
   * them, rather than a red bin that looked like an error. The time left runs
   * out around the bar's own edge, and Ctrl+Z undoes it while it shows.
   */
  import { fly } from "svelte/transition";
  import { backOut, cubicIn } from "svelte/easing";
  import Icon from "./Icon.svelte";
  import { play } from "../uisound";

  let {
    what = "",
    verb = "Removed",
    icon = "trash",
    images = [],
    veil = false,
    ms = 7000,
    key = "",
    onundo,
  }: {
    /** What went; nothing shows while it is empty. */
    what?: string;
    verb?: string;
    /** Shown when there is no picture of what went. */
    icon?: string;
    /** Pictures of what went: the last three show as a little pile. */
    images?: string[];
    /** Blurred until hovered, where the page itself is hiding its pictures. */
    veil?: boolean;
    /** How long it stays, for the edge running out. */
    ms?: number;
    /** Changes when something else goes, to start the edge again. */
    key?: string;
    onundo?: () => void;
  } = $props();

  const pile = $derived(images.slice(-3));
  /** The newest lies straight on top; the ones under it lean out either side. */
  const TILTS = [0, -11, 9];
  let w = $state(0);
  let h = $state(0);

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  /** Over the page, not the window: the row follows <main> as the sidebar opens and closes. */
  function overPage(node: HTMLElement) {
    const main = document.querySelector("main");
    if (!main) return;
    const place = () => {
      const r = main.getBoundingClientRect();
      node.style.left = `${r.left}px`;
      node.style.width = `${r.width}px`;
    };
    place();
    const ro = new ResizeObserver(place);
    ro.observe(main);
    return { destroy: () => ro.disconnect() };
  }

  /** The bar's outline from the top middle, round clockwise: the time left, drawn along it. */
  function edge(width: number, height: number) {
    if (!width || !height) return "";
    const s = 0.75;
    const r = height / 2 - s;
    return `M ${width / 2} ${s} H ${width - s - r} A ${r} ${r} 0 0 1 ${width - s - r} ${height - s}`
      + ` H ${s + r} A ${r} ${r} 0 0 1 ${s + r} ${s} Z`;
  }

  /** Up from below, a little small, landing with a bounce. */
  function rise(_: Element) {
    return {
      duration: 460,
      css: (t: number) => {
        const e = backOut(t);
        return `transform: translateY(${(1 - e) * 20}px) scale(${0.94 + 0.06 * e}); opacity: ${Math.min(1, t * 2.5)}`;
      },
    };
  }

  // Something went: a soft drop, once per thing that goes.
  let heard = "";
  $effect(() => {
    if (!what) {
      heard = "";
      return;
    }
    if (key !== heard) {
      heard = key;
      play("delete");
    }
  });
  function undoIt() {
    play("undo");
    onundo?.();
  }

  function onKey(e: KeyboardEvent) {
    if (!what || !(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "z" || e.shiftKey) return;
    const t = e.target as HTMLElement | null;
    // A text box's own undo comes first.
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    e.preventDefault();
    undoIt();
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="ub-row" use:portal use:overPage>
  {#if what}
    <div class="ub" role="status" bind:clientWidth={w} bind:clientHeight={h}
         in:rise out:fly={{ y: 12, duration: 170, easing: cubicIn }}>
      <svg class="ub-edge" width={w} height={h} aria-hidden="true">
        <path d={edge(w, h)} class="ub-track" />
        {#key key}
          <path d={edge(w, h)} class="ub-left" pathLength="100" style="animation-duration: {ms}ms" />
        {/key}
      </svg>

      {#if pile.length}
        <span class="ub-pile" class:is-veiled={veil} aria-hidden="true">
          {#each pile as src, i (src)}
            <img {src} alt="" class="ub-pic" style="--tilt: {TILTS[pile.length - 1 - i]}deg" />
          {/each}
        </span>
      {:else}
        <span class="ub-icon"><Icon name={icon} size={14} /></span>
      {/if}

      <span class="ub-text">{verb} <b>{what}</b></span>
      <span class="ub-sep" aria-hidden="true"></span>
      <button type="button" class="ub-undo" data-sound="self" onclick={undoIt} title="Undo (Ctrl+Z)">
        <span class="ub-arrow"><Icon name="undo" size={13} /></span>
        Undo
      </button>
    </div>
  {/if}
</div>

<style>
  .ub-row {
    position: fixed;
    left: 0;
    width: 100%;
    bottom: 22px;
    z-index: 60;
    display: flex;
    justify-content: center;
    padding: 0 16px;
    pointer-events: none;
  }
  .ub {
    position: relative;
    display: flex;
    height: 44px;
    max-width: 100%;
    align-items: center;
    gap: 10px;
    padding: 0 6px 0 7px;
    border-radius: 999px;
    font-size: 12.5px;
    pointer-events: auto;
    background:
      linear-gradient(180deg, rgb(255 255 255 / 0.06), rgb(255 255 255 / 0.015)),
      var(--color-card);
    box-shadow:
      0 16px 36px -12px rgb(0 0 0 / 0.7),
      0 2px 8px -2px rgb(0 0 0 / 0.35);
  }

  /* The edge: a faint line all round, and over it the time left in the
     accent, running out clockwise from the top middle. */
  .ub-edge {
    position: absolute;
    inset: 0;
    overflow: visible;
    pointer-events: none;
  }
  .ub-edge path {
    fill: none;
    stroke-width: 1.5;
  }
  .ub-track { stroke: var(--color-edge); }
  .ub-left {
    stroke: color-mix(in srgb, var(--color-accent) 80%, transparent);
    stroke-linecap: round;
    stroke-dasharray: 100 100;
    stroke-dashoffset: 0;
    animation: ub-run linear both;
  }
  @keyframes ub-run {
    to { stroke-dashoffset: -100; }
  }

  /* What went: the picture, or up to three in a loose pile, the newest on top. */
  .ub-pile {
    position: relative;
    width: 30px;
    height: 30px;
    flex-shrink: 0;
  }
  .ub-pic {
    position: absolute;
    inset: 0;
    width: 30px;
    height: 30px;
    border-radius: 8px;
    object-fit: cover;
    background: var(--color-surface);
    box-shadow: 0 0 0 2px var(--color-card), 0 2px 6px rgb(0 0 0 / 0.4);
    transform: rotate(var(--tilt));
    transform-origin: 50% 85%;
    transition: transform 0.45s var(--jelly), filter 0.25s ease;
    animation: ub-pop 0.42s var(--jelly) backwards;
  }
  @keyframes ub-pop {
    from { transform: translateY(-10px) scale(0.6) rotate(14deg); opacity: 0; }
  }
  .ub-pile.is-veiled .ub-pic { filter: blur(3px) saturate(0.7); }
  .ub:hover .ub-pile.is-veiled .ub-pic { filter: none; }
  .ub-icon {
    display: grid;
    width: 30px;
    height: 30px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    color: var(--color-muted);
    background: color-mix(in srgb, var(--color-ink) 7%, transparent);
  }

  .ub-text {
    min-width: 0;
    max-width: 22rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--color-muted);
  }
  .ub-text b {
    font-weight: 600;
    color: var(--color-ink);
  }
  .ub-sep {
    width: 1px;
    height: 18px;
    flex-shrink: 0;
    background: var(--color-edge);
  }

  .ub-undo {
    display: inline-flex;
    height: 32px;
    flex-shrink: 0;
    align-items: center;
    gap: 6px;
    padding: 0 13px 0 10px;
    border-radius: 999px;
    font-weight: 600;
    color: var(--color-accent);
    transition: background-color 0.15s ease, transform 0.3s var(--jelly);
  }
  .ub-undo:hover { background: color-mix(in srgb, var(--color-accent) 14%, transparent); }
  .ub-undo:active { transform: scale(0.94); }
  .ub-arrow {
    display: grid;
    transition: transform 0.45s var(--jelly);
  }
  .ub-undo:hover .ub-arrow { transform: rotate(-35deg); }

  :global(:root[data-motion="off"]) .ub-left,
  :global(:root[data-motion="off"]) .ub-pic { animation: none; }
</style>
