<script lang="ts">
  /**
   * A persona's face: its avatar, or its initials on a glow of its colour, in
   * a ring of that colour. The ring turns only on the one picked, so a row of
   * them is calm and the chosen one is alive.
   */
  import { colorOf, monogram, type Persona } from "./logic";

  let {
    p,
    size = 48,
    spin = false,
    ring = true,
  }: { p?: Pick<Persona, "name" | "color" | "avatar"> | null; size?: number; spin?: boolean; ring?: boolean } = $props();

  const color = $derived(colorOf(p));
  let broken = $state(false);
  $effect(() => {
    void p?.avatar;
    broken = false;
  });
</script>

<span class="po" class:is-spin={spin} style="--po-size: {size}px; --po-c: {color}" aria-hidden="true">
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
    background: conic-gradient(from 0deg, var(--po-c), color-mix(in srgb, var(--po-c) 30%, transparent) 40%,
      transparent 60%, var(--po-c));
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
    background:
      radial-gradient(circle at 32% 28%, color-mix(in srgb, var(--po-c) 55%, transparent), transparent 70%),
      color-mix(in srgb, var(--po-c) 16%, var(--color-card));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--po-c) 30%, transparent);
  }
  .po-face img { width: 100%; height: 100%; object-fit: cover; }
  .po-mono {
    font-weight: 750;
    letter-spacing: -0.02em;
    color: color-mix(in srgb, var(--po-c) 30%, white);
    text-shadow: 0 1px 8px color-mix(in srgb, var(--po-c) 60%, transparent);
  }
  :global(:root[data-motion="off"]) .po.is-spin .po-ring { animation: none; }
</style>
