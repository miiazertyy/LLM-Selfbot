<script lang="ts">
  /**
   * The number on a row of a list.
   *
   * A ranking (kind "rank"): the first three are medals, gold, silver and
   * bronze coins with a rim, the number struck into them and a ribbon behind,
   * and as the list arrives a shine crosses each, bronze first, then silver,
   * then gold. Silently: each had a coin's ting, and the three at the end of
   * the dashboard's opening were not liked.
   * The rest are glass chips of the same size. The first three used to be flat
   * coloured dots and the rest bare faint digits.
   *
   * Where it is only there to look at (the dashboard's leaderboard) a press
   * spins it like a flicked coin, a ting as it stops and, on a medal, the shine.
   *
   * An order (kind "step", a chain of models): the first in the accent, the
   * rest the same glass chips, no medals.
   */
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { motionEnabled } from "../stores";
  import { afterLanding, onScreen, whenShown } from "../cascade";
  import { play } from "../uisound";

  let {
    n,
    size = 22,
    kind = "rank",
    /** Shines (and is heard) as it arrives: off for lists that change under the eye. */
    shine = true,
    /** How long after its block lands the shine starts (ms): after its rows have slid in. */
    delay = 0,
    /** Kept for the places that pass it (Big Picture): the shine has no ting anywhere now. */
    quiet = false,
    /** A button: a press spins it. Off everywhere else, where a row's number has nothing to do. */
    spins = false,
  }: { n: number; size?: number; kind?: "rank" | "step"; shine?: boolean; delay?: number; quiet?: boolean; spins?: boolean } = $props();

  const medal = $derived(kind === "rank" && n >= 1 && n <= 3 ? (["gold", "silver", "bronze"] as const)[n - 1] : null);

  let el: HTMLElement | null = $state(null);
  let shining = $state(false);

  let face: HTMLElement | null = $state(null);
  let glance: HTMLElement | null = $state(null);
  let whirl: Animation | undefined;
  let sheen: Animation | undefined;
  /** When a press's spin has all but stopped (ms): its ting lands there, not when the slow tail runs out. */
  const LANDS = 430;

  /** Pressed: three turns about its upright, fast then settling, a small pop as it goes. Only transform, and it ends. */
  function spin() {
    play("zip", { level: 0.6 });
    if (medal) play("medal", { delay: LANDS, p: { gold: 1, silver: 0.5, bronze: 0 }[medal] });
    else play("seat", { delay: LANDS, level: 0.6 });
    if (!get(motionEnabled)) return;
    const turned = (deg: number, s: number) => `perspective(${size * 4}px) rotateY(${deg}deg) scale(${s})`;
    // Pressed again part way: it starts over. Its own element, so the coin's wink and the row's hover are left alone.
    whirl?.cancel();
    whirl = face?.animate(
      [{ transform: turned(0, 1) }, { transform: turned(324, 1.25), offset: 0.3 }, { transform: turned(1080, 1) }],
      { duration: 720, easing: "cubic-bezier(0.2, 0.75, 0.25, 1)" },
    );
    sheen?.cancel();
    sheen = glance?.animate(
      [{ opacity: 1, transform: "translateX(-70%)" }, { opacity: 1, transform: "translateX(70%)" }],
      { duration: 600, delay: LANDS - 60, easing: "cubic-bezier(0.3, 0.1, 0.2, 1)" },
    );
  }

  onMount(() => {
    if (!medal || !shine || !get(motionEnabled)) return;
    whenShown(el).then(() => afterLanding(el, () => onScreen(el).then((seen) => {
      if (seen) shining = true;
    })));
  });
</script>

<svelte:element
  this={spins ? "button" : "span"}
  type={spins ? "button" : undefined}
  role={spins ? "button" : undefined}
  data-sound={spins ? "self" : undefined}
  onclick={spins ? spin : undefined}
  class="rk"
  class:is-spins={spins}
  class:is-gold={medal === "gold"}
  class:is-silver={medal === "silver"}
  class:is-bronze={medal === "bronze"}
  class:is-medal={!!medal}
  class:is-first={kind === "step" && n === 1}
  class:is-shining={shining}
  style="--s: {size}px; --order: {3 - n}; --shine-at: {delay}ms"
  bind:this={el}
  aria-label={medal ? `${n}, ${medal}` : String(n)}
>
  <span class="rk-spin" bind:this={face}>
    {#if medal}<span class="rk-ribbon" aria-hidden="true"></span>{/if}
    <span class="rk-coin">
      {#key n}<b aria-hidden="true">{n}</b>{/key}
      {#if medal}<i class="rk-shine" aria-hidden="true" bind:this={glance}></i>{/if}
    </span>
  </span>
</svelte:element>

<style>
  .rk {
    position: relative;
    display: inline-grid;
    width: var(--s);
    height: var(--s);
    flex-shrink: 0;
    place-items: center;
    transition: transform 0.4s var(--jelly);
  }
  .rk:hover { transform: translateY(-1px) rotate(-6deg) scale(1.08); }
  .rk.is-spins { cursor: pointer; }
  .rk.is-spins:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; border-radius: 999px; }
  /* What a press turns: the coin and its ribbon as one, the size of the whole. */
  .rk-spin { position: relative; display: grid; width: 100%; height: 100%; place-items: center; }
  .rk-coin {
    position: relative;
    z-index: 1;
    display: grid;
    width: 100%;
    height: 100%;
    place-items: center;
    overflow: hidden;
    border-radius: 999px;
    font-size: calc(var(--s) * 0.5);
    font-weight: 800;
    line-height: 1;
    /* The rest of the list: glass chips the medals' size, not bare faint digits. */
    color: var(--color-muted);
    background: linear-gradient(180deg, rgb(255 255 255 / 0.09), rgb(255 255 255 / 0.03));
    box-shadow:
      inset 0 0 0 1px rgb(255 255 255 / 0.09),
      inset 0 1px 0 rgb(255 255 255 / 0.08),
      0 1px 2px rgb(0 0 0 / 0.3);
  }
  /* Centred on the digit itself, not on the font's line box: the app's
     typefaces sit their figures low in a tall box, so the number landed below
     the middle of the circle (and a tabular "1" off to one side of it). A new
     number (a chain reordered) pops in. */
  .rk-coin b {
    position: relative;
    z-index: 1;
    font-weight: inherit;
    text-box: trim-both cap alphabetic;
    animation: rk-num 0.4s var(--jelly);
  }
  @keyframes rk-num { from { transform: scale(0.4); opacity: 0; } }

  /* First of a chain: the accent, lit. */
  .rk.is-first .rk-coin {
    color: var(--color-bg);
    background: linear-gradient(160deg, color-mix(in srgb, var(--color-accent) 72%, white), var(--color-accent));
    box-shadow:
      inset 0 0 0 1px rgb(255 255 255 / 0.25),
      inset 0 -2px 3px color-mix(in srgb, var(--color-accent) 60%, black),
      0 3px 10px -3px var(--color-accent);
  }

  /* Medals: metal, with a light from the top left, a rim, and the number struck into it. */
  .rk.is-gold { --hi: #fff6c9; --mid: #f6c445; --lo: #b37d17; --ink: #4a2f00; --glow: #f0b63f; --band: #e0505a; }
  .rk.is-silver { --hi: #ffffff; --mid: #d3dae3; --lo: #8792a2; --ink: #283039; --glow: #b4bfcc; --band: #4f86e8; }
  .rk.is-bronze { --hi: #ffe2c6; --mid: #d79a63; --lo: #8a5022; --ink: #3a1c06; --glow: #c7854f; --band: #3fae74; }
  .rk.is-medal .rk-coin {
    color: var(--ink);
    text-shadow: 0 1px 0 color-mix(in srgb, var(--hi) 75%, transparent), 0 -1px 0 color-mix(in srgb, var(--lo) 40%, transparent);
    background:
      radial-gradient(circle at 32% 26%, color-mix(in srgb, var(--hi) 95%, transparent) 0 14%, transparent 48%),
      conic-gradient(from 210deg, var(--mid), var(--lo) 22%, var(--mid) 45%, var(--hi) 62%, var(--mid) 80%, var(--lo));
    box-shadow:
      inset 0 0 0 1.5px color-mix(in srgb, var(--hi) 70%, transparent),
      inset 0 0 0 3px color-mix(in srgb, var(--lo) 30%, transparent),
      inset 0 -2px 3px color-mix(in srgb, var(--lo) 65%, transparent),
      0 2px 8px -2px color-mix(in srgb, var(--glow) 80%, transparent);
  }
  .rk.is-gold .rk-coin {
    box-shadow:
      inset 0 0 0 1.5px color-mix(in srgb, var(--hi) 70%, transparent),
      inset 0 0 0 3px color-mix(in srgb, var(--lo) 30%, transparent),
      inset 0 -2px 3px color-mix(in srgb, var(--lo) 65%, transparent),
      0 2px 10px -1px color-mix(in srgb, var(--glow) 90%, transparent);
  }
  /* The ribbon: two tails behind the coin, cut in a V. */
  .rk-ribbon {
    position: absolute;
    left: 50%;
    bottom: calc(var(--s) * -0.26);
    width: calc(var(--s) * 0.62);
    height: calc(var(--s) * 0.56);
    transform: translateX(-50%);
  }
  .rk-ribbon::before,
  .rk-ribbon::after {
    content: "";
    position: absolute;
    bottom: 0;
    width: 46%;
    height: 100%;
    background: linear-gradient(180deg, color-mix(in srgb, var(--band) 75%, black), var(--band));
    clip-path: polygon(0 0, 100% 0, 100% 100%, 50% 74%, 0 100%);
  }
  .rk-ribbon::before { left: 0; transform: rotate(16deg); transform-origin: top right; }
  .rk-ribbon::after { right: 0; transform: rotate(-16deg); transform-origin: top left; }

  /* The shine: a soft band of light across the coin, bronze, silver, then gold, as the list arrives, and on a hover. */
  .rk-shine {
    position: absolute;
    inset: -20%;
    z-index: 2;
    opacity: 0;
    pointer-events: none;
    background: linear-gradient(115deg, transparent 32%, rgb(255 255 255 / 0.85) 48%, rgb(255 255 255 / 0.2) 56%, transparent 66%);
    transform: translateX(-70%);
    mix-blend-mode: soft-light;
  }
  .rk.is-shining .rk-shine {
    animation: rk-shine 0.7s cubic-bezier(0.3, 0.1, 0.2, 1) calc(var(--shine-at) + var(--order) * 150ms) both;
  }
  .rk.is-medal:hover .rk-shine { animation: rk-shine 0.7s cubic-bezier(0.3, 0.1, 0.2, 1) both; }
  @keyframes rk-shine {
    0% { opacity: 1; transform: translateX(-70%); }
    100% { opacity: 1; transform: translateX(70%); }
  }
  .rk.is-shining.is-medal .rk-coin { animation: rk-wink 0.7s var(--jelly) calc(var(--shine-at) + var(--order) * 150ms) both; }
  @keyframes rk-wink {
    0% { transform: scale(1); }
    35% { transform: scale(1.14) rotate(-8deg); }
    100% { transform: scale(1) rotate(0); }
  }

  :global(:root[data-motion="off"]) .rk,
  :global(:root[data-motion="off"]) .rk-shine,
  :global(:root[data-motion="off"]) .rk-coin,
  :global(:root[data-motion="off"]) .rk-coin b { transition: none; animation: none; }
</style>
