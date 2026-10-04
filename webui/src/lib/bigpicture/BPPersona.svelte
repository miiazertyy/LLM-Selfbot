<script lang="ts">
  /**
   * The idle scene about who the bot is: its face, the name it is told it has,
   * and the opening of its persona, written in a line at a time, the words
   * every reply starts from (scenes.ts picks them out of the instructions).
   *
   * Under it, the mood each account is in, and every mood it can be put in: a
   * click switches it, the way the Accounts page does, so how it talks can be
   * changed without leaving the big screen.
   */
  import { cubicOut } from "svelte/easing";
  import { get } from "svelte/store";
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import { bigPictureExit, motionEnabled } from "../stores";
  import { fitText } from "./fit";
  import { popIn } from "./motion";
  import { ripple } from "./fx";
  import type { BPAccount } from "./types";

  let {
    lines = [],
    name = "",
    face = null,
    accounts = [],
    moods = [],
    hideText = false,
    busy = {},
    onmood,
  }: {
    lines?: string[];
    /** The name the persona gives it, or the account's own. */
    name?: string;
    /** Whose picture: the account that is running, if one is. */
    face?: BPAccount | null;
    accounts?: BPAccount[];
    /** Every mood it can be put in, as configured. */
    moods?: string[];
    hideText?: boolean;
    busy?: Record<string, boolean>;
    onmood?: (a: BPAccount, mood: string, el: HTMLElement) => void;
  } = $props();

  /** Only an account that answers can be put in a mood. */
  const reachable = $derived(accounts.filter((a) => a.state === "running" && a.live));

  /**
   * Tight: the stage made narrow by the queue, or a short screen. The face
   * then sits beside the name instead of above it, and the persona gives its
   * first few lines rather than all of them, so the moods still fit below.
   */
  let width = $state(0);
  let tall = $state(1080);
  const tight = $derived(width < 760 || tall < 820);
  const shown = $derived(tight ? lines.slice(0, 5) : lines);

  /** A line writing itself out, left to right. */
  function write(_node: Element, { delay = 0 }: { delay?: number } = {}) {
    if (bigPictureExit.on) return { duration: 0 };
    if (!get(motionEnabled)) return { delay, duration: 200, css: (t: number) => `opacity:${t}` };
    return {
      delay,
      duration: 900,
      easing: cubicOut,
      css: (t: number) => `clip-path: inset(-10% ${((1 - t) * 100).toFixed(1)}% -10% 0); opacity: ${Math.min(1, t * 3)}`,
    };
  }
</script>

<svelte:window bind:innerHeight={tall} />

<div class="bpe" class:is-tight={tight} bind:clientWidth={width}>
  <div class="bpe-grid">
    <div class="bpe-who">
      <span class="bpe-halo" in:popIn|global={{ delay: 80, from: 0.8 }}>
        <Avatar src={face?.avatar} name={name || face?.name || "?"} size={tight ? 84 : 148} zoom={false} />
      </span>
      <div class="bpe-id">
        <div class="bp-kicker" in:popIn|global={{ delay: 160, from: 0.96 }}>Persona · who it is told it is</div>
        <div class="bpe-name" use:fitText={{ min: 26, text: name }} in:popIn|global={{ delay: 220, from: 0.96 }}>{name || face?.name || "The bot"}</div>
        {#if face?.mood}
          <div class="bpe-now" in:popIn|global={{ delay: 300, from: 0.96 }}><Icon name="sparkle" size={13} />Feeling {face.mood} right now</div>
        {/if}
      </div>
    </div>

    <blockquote class="bpe-quote" class:is-hidden={hideText}>
      {#each shown as l, i (i)}
        <p in:write|global={{ delay: 380 + i * 420 }}>{l}</p>
      {/each}
    </blockquote>
  </div>

  {#if reachable.length && moods.length}
    <div class="bpe-moods" in:popIn|global={{ delay: 500 + shown.length * 200, from: 0.96 }}>
      {#each reachable as a (a.id)}
        <div class="bpe-row">
          {#if reachable.length > 1}
            <span class="bpe-acct" title={a.name}><Avatar src={a.avatar} name={a.name} size={24} zoom={false} /></span>
          {:else}
            <span class="bpe-label">Mood</span>
          {/if}
          {#each moods as m (m)}
            <button class="bpe-chip" class:is-on={a.mood === m} disabled={!!busy[a.id] || a.mood === m}
                    use:ripple onclick={(e) => onmood?.(a, m, e.currentTarget)}
                    title={a.mood === m ? `${a.name} is ${m}` : `Put ${a.name} in a ${m} mood`}>
              {m}
            </button>
          {/each}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .bpe { display: flex; height: 100%; min-width: 0; flex-direction: column; justify-content: safe center; gap: 22px; padding: 10px 6px; container-type: inline-size; }
  .bpe-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 22px; align-items: center; }
  @container (min-width: 760px) {
    .bpe-grid { grid-template-columns: minmax(0, 0.8fr) minmax(0, 1.2fr); gap: clamp(28px, 3.4vw, 60px); }
  }
  .bpe-who { display: flex; min-width: 0; flex-direction: column; align-items: flex-start; gap: 8px; }
  .bpe-id { display: flex; width: 100%; min-width: 0; flex-direction: column; gap: 8px; }
  /* Tight: the face beside the name, and everything a size smaller. */
  .bpe.is-tight { gap: 14px; }
  .bpe.is-tight .bpe-grid { gap: 16px; }
  .bpe.is-tight .bpe-who { flex-direction: row; align-items: center; gap: 20px; }
  .bpe.is-tight .bpe-id { flex: 1 1 0; gap: 4px; }
  .bpe.is-tight .bpe-halo { margin-bottom: 0; animation: none; }
  .bpe.is-tight .bpe-name { font-size: clamp(32px, 3.4vw, 50px); }
  .bpe.is-tight .bpe-quote { gap: 5px; padding: 18px 22px; }
  .bpe.is-tight .bpe-quote::before { top: -26px; font-size: 110px; }
  .bpe.is-tight .bpe-quote p { font-size: clamp(15px, 1.3vw, 19px); }
  .bpe.is-tight .bpe-quote p:first-child { font-size: clamp(17px, 1.5vw, 22px); }
  .bpe-halo {
    display: grid;
    margin-bottom: 8px;
    border-radius: 999px;
    box-shadow: 0 0 0 6px rgb(10 11 18), 0 0 0 8px color-mix(in srgb, var(--color-accent) 55%, transparent),
                0 0 90px color-mix(in srgb, var(--color-accent) 34%, transparent);
    animation: bpe-float 7s ease-in-out infinite;
  }
  @keyframes bpe-float { 50% { transform: translate3d(0, -8px, 0); } }
  .bpe-name {
    width: 100%;
    overflow: hidden;
    font-size: clamp(40px, 4.8vw, 76px);
    font-weight: 800;
    line-height: 1.16;
    letter-spacing: -0.04em;
    color: #fff;
    text-overflow: ellipsis;
    white-space: nowrap;
    /* Room above and below for an emoji, which stands taller than the letters:
       at a line height of 1 the box it is cut to sliced them flat. The margin
       takes the room back, so the layout is where it was. */
    padding-block: 0.1em;
    margin-block: -0.1em;
  }
  .bpe-now { display: inline-flex; align-items: center; gap: 6px; font-size: 15px; color: color-mix(in srgb, var(--color-accent) 70%, white); }

  .bpe-quote {
    position: relative;
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 8px;
    margin: 0;
    padding: clamp(20px, 2.4vw, 34px) clamp(22px, 2.6vw, 38px);
    border-radius: 28px;
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08), 0 30px 80px -40px rgb(0 0 0 / 0.8);
    backdrop-filter: blur(22px);
  }
  /* A large opening quote mark, sitting back behind the words. */
  /* In a serif of its own: the app's rounded typeface draws its quote mark as two little hooks. */
  .bpe-quote::before {
    content: "“";
    position: absolute;
    top: -30px;
    left: 16px;
    font-family: Georgia, "Times New Roman", serif;
    font-size: 140px;
    font-weight: 700;
    line-height: 1;
    color: color-mix(in srgb, var(--color-accent) 50%, transparent);
    pointer-events: none;
  }
  .bpe-quote p { font-size: clamp(17px, 1.55vw, 24px); line-height: 1.45; color: #fff; }
  .bpe-quote p:first-child { font-size: clamp(20px, 1.9vw, 30px); font-weight: 650; letter-spacing: -0.01em; }
  .bpe-quote.is-hidden p { filter: blur(9px); }

  .bpe-moods { display: flex; flex-direction: column; gap: 8px; }
  .bpe-row { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; gap: 7px; }
  .bpe-label { margin-right: 4px; font-size: 11.5px; font-weight: 700; letter-spacing: 0.2em; text-transform: uppercase; color: var(--bp-faint); }
  .bpe-acct { display: grid; margin-right: 2px; }
  .bpe-chip {
    position: relative;
    height: 34px;
    padding: 0 15px;
    overflow: hidden;
    border-radius: 999px;
    font-size: 13.5px;
    font-weight: 600;
    text-transform: capitalize;
    color: var(--bp-muted);
    background: rgb(255 255 255 / 0.06);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08);
    transition: transform 0.25s var(--spring), background-color 0.2s ease, color 0.2s ease;
  }
  .bpe-chip:hover:not(:disabled) { transform: translateY(-1px); color: #fff; background: rgb(255 255 255 / 0.12); }
  .bpe-chip:active:not(:disabled) { transform: scale(0.94); }
  .bpe-chip.is-on {
    color: var(--color-bg);
    background: var(--color-accent);
    box-shadow: 0 10px 28px -10px color-mix(in srgb, var(--color-accent) 70%, transparent);
  }
  .bpe-chip:disabled:not(.is-on) { opacity: 0.45; }
  :global(:root[data-motion="off"]) .bpe-halo { animation: none; }
</style>
