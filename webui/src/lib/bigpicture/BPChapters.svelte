<script lang="ts">
  /**
   * The chapters, under the stage: Live, then every scene there is to see.
   *
   * The idle scenes used to come and go with nothing saying what was on, what
   * came next, or how to get back to one. This names them: the one on show
   * opens out with its name and a line that fills as its time runs, so you can
   * see how long it has. A click, or its number key, goes straight to one;
   * Live (or L) goes back to whoever is being answered. A scene with something
   * waiting in it (friend requests, a problem) carries a count.
   */
  import Icon from "../components/Icon.svelte";
  import type { Scene } from "./director";
  import { CHAPTER } from "./scenes";

  let {
    chapters = [],
    current = null,
    live = false,
    waiting = 0,
    progress = 0,
    sceneKey = 0,
    held = false,
    pinned = false,
    badges = {},
    tones = {},
    ongo,
    onlive,
    onpin,
  }: {
    chapters?: Scene[];
    /** The idle scene on show, or null while a conversation is. */
    current?: Scene | null;
    /** A conversation is on stage. */
    live?: boolean;
    /** How many are in the queue. */
    waiting?: number;
    /** How far through its time the scene on show is, 0 to 1. */
    progress?: number;
    /** Changes with every scene shown, so the line starts again even when the same one comes round. */
    sceneKey?: number;
    /** Held by hand: the line stands still. */
    held?: boolean;
    pinned?: boolean;
    badges?: Partial<Record<Scene, number>>;
    /** What a count means: something wrong is red or amber, anything else the accent. */
    tones?: Partial<Record<Scene, "bad" | "warn" | "accent">>;
    ongo?: (s: Scene) => void;
    onlive?: () => void;
    onpin?: () => void;
  } = $props();

  // A narrow stage cannot show every chapter with the current one's name open:
  // the list scrolls, and the one on show is kept in view, once its name has
  // opened out.
  let list: HTMLDivElement | null = $state(null);
  $effect(() => {
    const c = current;
    const box = list;
    if (!c || !box) return;
    const t = setTimeout(() => {
      const el = box.querySelector<HTMLElement>(".bpc-ch.is-on");
      if (!el || box.scrollWidth <= box.clientWidth) return;
      const b = box.getBoundingClientRect(), r = el.getBoundingClientRect();
      if (r.left < b.left) box.scrollBy({ left: r.left - b.left - 12, behavior: "smooth" });
      else if (r.right > b.right) box.scrollBy({ left: r.right - b.right + 12, behavior: "smooth" });
    }, 520);
    return () => clearTimeout(t);
  });
</script>

<nav class="bpc" class:is-held={held} aria-label="Chapters">
  <button class="bpc-live" class:is-on={live} disabled={!waiting && !live} onclick={() => onlive?.()}
          title={waiting ? "Back to the conversations (L)" : "Nobody is waiting"}>
    <i class="bpc-rec" aria-hidden="true"></i><span>Live</span>{#if waiting}<b class="bpc-count">{waiting}</b>{/if}
  </button>
  <span class="bpc-sep" aria-hidden="true"></span>
  <div class="bpc-list" bind:this={list}>
    {#each chapters as c, i (c)}
      <button class="bpc-ch" class:is-on={current === c} onclick={() => ongo?.(c)}
              title="{CHAPTER[c].label}{i < 9 ? ` (${i + 1})` : ''}" aria-label={CHAPTER[c].label}
              aria-current={current === c ? "true" : undefined}>
        <Icon name={CHAPTER[c].icon} size={15} />
        <span class="bpc-label">{CHAPTER[c].label}</span>
        {#if badges[c]}<b class="bpc-badge" data-tone={tones[c] ?? "accent"}>{badges[c]}</b>{/if}
        {#if current === c}
          {#key sceneKey}
            <i class="bpc-fill" style="--p: {progress}" aria-hidden="true"></i>
          {/key}
        {/if}
      </button>
    {/each}
  </div>
  <!-- Only a hold made with Space: the pointer's own hold renews itself on every
       movement, so a button to let it go would be caught by the reach for it. -->
  {#if pinned}
    <button class="bpc-held" onclick={() => onpin?.()} title="Let it move on (Space)">
      <Icon name="pause" size={12} />Held
    </button>
  {/if}
</nav>

<style>
  .bpc {
    display: flex;
    min-width: 0;
    max-width: 100%;
    align-items: center;
    gap: 6px;
    align-self: center;
    padding: 5px;
    border-radius: 999px;
    background: rgb(255 255 255 / 0.045);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.07);
    backdrop-filter: blur(18px);
  }
  .bpc-list { display: flex; min-width: 0; gap: 2px; overflow-x: auto; scrollbar-width: none; }
  .bpc-list::-webkit-scrollbar { display: none; }
  .bpc-sep { width: 1px; height: 20px; flex-shrink: 0; background: rgb(255 255 255 / 0.1); }
  .bpc-live, .bpc-ch, .bpc-held {
    position: relative;
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 7px;
    height: 34px;
    padding: 0 11px;
    overflow: hidden;
    border-radius: 999px;
    font-size: 12.5px;
    font-weight: 650;
    white-space: nowrap;
    color: var(--bp-muted);
    transition: color 0.25s ease, background-color 0.25s ease, transform 0.3s var(--spring);
  }
  .bpc-live:hover:not(:disabled), .bpc-ch:hover, .bpc-held:hover { color: #fff; background: rgb(255 255 255 / 0.08); }
  .bpc-live:active:not(:disabled), .bpc-ch:active, .bpc-held:active { transform: scale(0.93); }
  .bpc-live:disabled { opacity: 0.4; }
  .bpc-rec { width: 8px; height: 8px; border-radius: 999px; background: var(--bp-faint); }
  .bpc-live.is-on { color: #fff; background: color-mix(in srgb, var(--color-bad) 26%, transparent); }
  .bpc-live.is-on .bpc-rec { background: var(--color-bad); animation: bpc-rec 1.6s ease-in-out infinite; }
  @keyframes bpc-rec { 50% { opacity: 0.35; } }
  .bpc-count {
    min-width: 18px;
    padding: 0 5px;
    border-radius: 999px;
    font-size: 10.5px;
    text-align: center;
    color: #fff;
    background: color-mix(in srgb, var(--color-accent) 50%, transparent);
  }
  /* The name opens out on the one on show only; the rest are their icons,
     centred in a round button. No gap: a hidden name used to keep one of its
     own beside the icon, which pushed every icon off centre. */
  .bpc-ch { gap: 0; padding: 0 9.5px; }
  .bpc-label { max-width: 0; margin-left: 0; overflow: hidden; opacity: 0;
               transition: max-width 0.5s var(--swift), margin-left 0.5s var(--swift), opacity 0.3s ease; }
  .bpc-ch.is-on { padding: 0 12px 0 11px; color: #fff; background: rgb(255 255 255 / 0.1); }
  .bpc-ch.is-on .bpc-label { max-width: 170px; margin-left: 7px; opacity: 1; }
  .bpc-ch.is-on :global(svg) { color: var(--color-accent); }
  .bpc-badge {
    position: absolute;
    top: 3px;
    right: 3px;
    min-width: 15px;
    height: 15px;
    padding: 0 4px;
    border-radius: 999px;
    font-size: 9.5px;
    line-height: 15px;
    text-align: center;
    color: #fff;
    background: var(--color-accent);
    box-shadow: 0 0 0 2px rgb(10 11 18);
  }
  .bpc-badge[data-tone="bad"] { background: var(--color-bad); }
  .bpc-badge[data-tone="warn"] { color: rgb(10 11 18); background: var(--color-warn); }
  .bpc-ch.is-on .bpc-badge { position: static; margin-left: 6px; }
  /* How long the scene has left: scaled, not resized, so it composites. */
  .bpc-fill {
    position: absolute;
    left: 10px;
    right: 10px;
    bottom: 3px;
    height: 2px;
    border-radius: 999px;
    background: var(--color-accent);
    transform: scaleX(var(--p));
    transform-origin: left;
    transition: transform 1s linear;
  }
  .bpc.is-held .bpc-fill { opacity: 0.45; }
  .bpc-held { gap: 5px; height: 28px; padding: 0 10px; font-size: 11.5px; color: #fff; background: color-mix(in srgb, var(--color-accent) 38%, transparent); }
  :global(:root[data-motion="off"]) .bpc-live.is-on .bpc-rec { animation: none; }
  :global(:root[data-motion="off"]) .bpc-fill { transition: none; }
</style>
