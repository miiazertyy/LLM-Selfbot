<script lang="ts">
  /**
   * Picking a reaction for a message, the way the app it is on offers them.
   *
   * Snapchat has eight, and one per person on a message: a row of them, the
   * account's own lit, and pressing it again takes it back; another replaces
   * it. Discord takes any emoji: a row of the usual ones, and every emoji
   * there is one press away.
   *
   * Drawn at the end of <body>, like the dropdowns, so nothing in the
   * conversation paints over it; above the button that opened it when there is
   * room, below it when not. A press outside, Escape or the conversation
   * scrolling closes it.
   */
  import { onMount, tick } from "svelte";
  import { get } from "svelte/store";
  import EmojiPicker from "./EmojiPicker.svelte";
  import Icon from "./Icon.svelte";
  import { play } from "../uisound";
  import { burst } from "../burst";
  import { motionEnabled } from "../stores";
  import { DISCORD_REACTIONS, SNAP_REACTIONS } from "../chats";

  let { anchor, snap = false, mine = [], onpick, onclose }: {
    anchor: HTMLElement;
    /** Snapchat's eight, rather than Discord's any. */
    snap?: boolean;
    /** The account's own reactions on the message: lit, and a press takes one back. */
    mine?: string[];
    onpick: (emoji: string, add: boolean) => void;
    onclose: () => void;
  } = $props();

  const quick = $derived(snap ? SNAP_REACTIONS : DISCORD_REACTIONS);
  let more = $state(false);
  let box: HTMLElement | null = $state(null);
  let pos = $state({ left: 0, top: 0, up: true });

  /** Beside the button: centred over it, above when it fits, kept inside the window. */
  function place() {
    const r = anchor.getBoundingClientRect();
    const w = box?.offsetWidth ?? 340;
    const h = box?.offsetHeight ?? 52;
    const up = r.top - h - 8 >= 8;
    const top = up ? r.top - h - 8 : Math.min(r.bottom + 8, innerHeight - h - 8);
    pos = { left: Math.max(8, Math.min(r.left + r.width / 2 - w / 2, innerWidth - w - 8)), top: Math.max(8, top), up };
  }

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  onMount(() => {
    place();
    play("open");
    const outside = (e: PointerEvent) => {
      const t = e.target as Node;
      if (box && !box.contains(t) && !anchor.contains(t)) onclose();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onclose();
    };
    // The conversation scrolling takes the message away from it; its own grid scrolling does not.
    const scrolled = (e: Event) => {
      if (!(box && e.target instanceof Node && box.contains(e.target))) onclose();
    };
    const resized = () => onclose();
    // The press that opened it is still on its way: outside presses count from the next one.
    const t = setTimeout(() => window.addEventListener("pointerdown", outside, true), 0);
    window.addEventListener("keydown", key, true);
    window.addEventListener("scroll", scrolled, true);
    window.addEventListener("resize", resized);
    return () => {
      clearTimeout(t);
      window.removeEventListener("pointerdown", outside, true);
      window.removeEventListener("keydown", key, true);
      window.removeEventListener("scroll", scrolled, true);
      window.removeEventListener("resize", resized);
    };
  });

  function pick(e: string, from?: Element | null) {
    const add = !mine.includes(e);
    play(add ? "select" : "off");
    // It pops up and floats off from where it was pressed, the picker already gone.
    if (add && from) burst(e, from);
    onpick(e, add);
    onclose();
  }

  /** Every emoji: the round row opens out into the full picker, growing to its size rather than jumping to it. */
  async function showAll() {
    play("open");
    const from = box?.getBoundingClientRect();
    more = true;
    await tick();
    place();
    if (!box || !from || !get(motionEnabled)) return;
    const to = box.getBoundingClientRect();
    box.animate([
      { width: `${from.width}px`, height: `${from.height}px`, borderRadius: "999px" },
      { width: `${to.width}px`, height: `${to.height}px`, borderRadius: "18px" },
    ], { duration: 420, easing: "cubic-bezier(0.22, 1.18, 0.36, 1)" });
  }
</script>

<div class="rp glass floating" class:is-up={pos.up} class:is-all={more} bind:this={box} use:portal data-sound="self"
     style="left: {pos.left}px; top: {pos.top}px" role="dialog" aria-label="React to the message">
  <div class="rp-row">
    {#each quick as e, i (e)}
      <button type="button" class="rp-e" class:is-mine={mine.includes(e)} style="--i: {i}" onclick={(ev) => pick(e, ev.currentTarget)}
              title={mine.includes(e) ? "Take it back" : "React"} aria-pressed={mine.includes(e)}>{e}</button>
    {/each}
    {#if !snap && !more}
      <button type="button" class="rp-all-btn" style="--i: {quick.length}" onclick={showAll}
              title="Every emoji" aria-label="Every emoji"><Icon name="plus" size={15} /></button>
    {/if}
  </div>
  {#if more}
    <!-- EmojiPicker makes its own pop where the emoji was pressed. -->
    <div class="rp-grid"><EmojiPicker chosen={mine} onpick={(e) => pick(e)} /></div>
  {/if}
</div>

<style>
  .rp {
    position: fixed;
    z-index: 1000;
    padding: 5px;
    border-radius: 999px;
    transform-origin: bottom center;
    animation: rp-in 0.3s var(--spring) both;
  }
  .rp:not(.is-up) { transform-origin: top center; animation-name: rp-in-below; }
  .rp.is-all { width: min(380px, calc(100vw - 16px)); border-radius: 18px; }
  .rp-row { display: flex; align-items: center; gap: 1px; }
  .rp.is-all .rp-row { justify-content: space-between; }
  .rp-e, .rp-all-btn {
    display: grid;
    width: 38px;
    height: 38px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    /* Backwards only: held after it ends, the pop would keep the hover's lift from showing. */
    animation: rp-pop 0.34s var(--spring) backwards;
    animation-delay: calc(var(--i) * 18ms);
    transition: transform 0.28s var(--spring), background-color 0.15s ease, box-shadow 0.15s ease;
  }
  .rp-e { font-size: 23px; line-height: 1; }
  .rp-e:hover, .rp-e:focus-visible { transform: scale(1.24) translateY(-3px); background: rgb(255 255 255 / 0.07); outline: none; }
  .rp-e:active { transform: scale(0.9); }
  /* The account's own: lit, and a press takes it back. */
  .rp-e.is-mine {
    background: color-mix(in srgb, var(--color-accent) 22%, transparent);
    box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--color-accent) 60%, transparent);
  }
  .rp-all-btn { width: 34px; height: 34px; margin-left: 2px; color: var(--color-muted); background: rgb(255 255 255 / 0.06); }
  .rp-all-btn:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.1); transform: rotate(90deg); }
  /* The picker scrolls its own grid, so this does not as well. */
  .rp-grid { margin-top: 6px; animation: rp-grid-in 0.35s 0.08s var(--spring) both; }
  @keyframes rp-grid-in { from { opacity: 0; transform: translateY(6px); } }
  :global(:root[data-motion="off"]) .rp-grid { animation: none; }
  .rp.is-all { overflow: hidden; }
  @keyframes rp-in { from { opacity: 0; transform: translateY(8px) scale(0.9); } }
  @keyframes rp-in-below { from { opacity: 0; transform: translateY(-8px) scale(0.9); } }
  @keyframes rp-pop { from { opacity: 0; transform: translateY(6px) scale(0.6); } }
  :global(:root[data-motion="off"]) .rp,
  :global(:root[data-motion="off"]) .rp-e,
  :global(:root[data-motion="off"]) .rp-all-btn { animation: none; transition: none; }
</style>
