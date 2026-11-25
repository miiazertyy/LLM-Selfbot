<script lang="ts">
  /**
   * A persona's face: its avatar, or its initial on the app theme's colours, in a ring of the persona's own colour.
   * The ring turns only on the one picked, so a row of them is calm and the chosen one is alive.
   *
   * Without a picture the face was a disc of the persona's colour, which matched no theme (Nora's slate in a purple
   * one, 2026-11-11), so the disc is the theme's now, deeper at the top than the foot, its initial pale. The persona's
   * colour stays in the ring, shown on the large faces only (Profiles, New profile, Persona), where picking a colour
   * has to show; the small ones (sidebar, lists, chips) are the theme's alone.
   */
  import { colorOf, monogram, type Persona } from "./logic";

  let {
    p,
    size = 48,
    spin = false,
    ring = true,
  }: { p?: Pick<Persona, "name" | "color" | "color2" | "avatar"> | null; size?: number; spin?: boolean; ring?: boolean } = $props();

  const color = $derived(colorOf(p));
  /** With a theme of two colours, the ring runs into the second. */
  const rim = $derived(p?.color2 || `color-mix(in srgb, ${color} 30%, transparent)`);
  let broken = $state(false);
  $effect(() => {
    void p?.avatar;
    broken = false;
  });
</script>

<span class="po" class:is-spin={spin} style="--po-size: {size}px; --po-c: {color}; --po-rim: {rim}" aria-hidden="true">
  {#if ring}<span class="po-ring"></span>{/if}
  <span class="po-face">
    {#if p?.avatar && !broken}
      <img src={p.avatar} alt="" draggable="false" onerror={() => (broken = true)} />
    {:else}
      <span class="po-mono" style="font-size: {Math.round(size * 0.36)}px">{monogram(p?.name ?? "")}</span>
    {/if}
  </span>
</span>

<style>
  .po {
    position: relative;
    display: inline-grid;
    width: var(--po-size);
    height: var(--po-size);
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
  }
  .po-ring {
    position: absolute;
    inset: -3px;
    border-radius: 999px;
    background: conic-gradient(from 0deg, var(--po-c), var(--po-rim) 40%, transparent 60%, var(--po-c));
    -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2px));
    mask: radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2px));
    opacity: 0.55;
    transition: opacity 0.4s var(--swift);
  }
  .po.is-spin .po-ring { opacity: 1; animation: po-turn 5s linear infinite; }
  @keyframes po-turn { to { transform: rotate(360deg); } }
  .po-face {
    position: relative;
    display: grid;
    width: 100%;
    height: 100%;
    overflow: hidden;
    place-items: center;
    border-radius: 999px;
    background: linear-gradient(160deg, color-mix(in srgb, var(--color-accent) 46%, var(--color-card)),
                                color-mix(in srgb, var(--color-accent-2, var(--color-accent)) 20%, var(--color-card)));
  }
  .po-face img { width: 100%; height: 100%; object-fit: cover; }
  .po-mono {
    font-weight: 650;
    letter-spacing: -0.02em;
    color: color-mix(in srgb, var(--color-accent) 25%, white);
  }
  :global(:root[data-motion="off"]) .po.is-spin .po-ring { animation: none; }
</style>
