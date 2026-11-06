<script lang="ts">
  /**
   * The bottom of Big Picture: the keys that work right now, and the day's score.
   *
   * It teaches itself, the way a console's bottom bar does: what is listed changes
   * with the page and with whether there is someone to answer, and it says a pad's
   * buttons once a pad is in use. They are buttons too. `?` unrolls the whole list
   * in place, over the bar, with the page still there around it.
   *
   * The three numbers are the only ones that stay in view, and they open Today,
   * where the rest of them are: not shown on Today itself, which says them larger.
   */
  import Odometer from "../components/Odometer.svelte";
  import { unroll } from "../unroll";
  import { focusable } from "./focus";
  import type { Page } from "./director";
  import { compact } from "./scenes";

  type Key = { keys: string; pad: string; say: string; run?: () => void };

  let {
    page = "now",
    mode = "pointer",
    canReply = false,
    canWrite = false,
    backLabel = "Leave",
    showScore = true,
    replies = 0,
    people = 0,
    tokens = 0,
    help = false,
    onreply,
    onwrite,
    onpage,
    onstay,
    onback,
    onhelp,
    onscore,
  }: {
    page?: Page;
    mode?: "pointer" | "keys" | "pad";
    canReply?: boolean;
    canWrite?: boolean;
    /** What Esc does here. */
    backLabel?: string;
    showScore?: boolean;
    replies?: number;
    people?: number;
    tokens?: number;
    help?: boolean;
    onreply?: () => void;
    onwrite?: () => void;
    onpage?: (dir: 1 | -1) => void;
    onstay?: () => void;
    onback?: () => void;
    onhelp?: () => void;
    onscore?: () => void;
  } = $props();

  const hints = $derived.by<Key[]>(() => {
    const out: Key[] = [{ keys: "← ↑ ↓ →", pad: "D-pad", say: "Move" }, { keys: "Enter", pad: "A", say: "Open" }];
    if (canReply) out.push({ keys: "R", pad: "X", say: "Reply now", run: onreply });
    if (canWrite) out.push({ keys: "W", pad: "", say: "Write", run: onwrite });
    out.push({ keys: "Q E", pad: "LB RB", say: "Page", run: () => onpage?.(1) });
    out.push({ keys: "Space", pad: "Start", say: "Stay", run: onstay });
    out.push({ keys: "Esc", pad: "B", say: backLabel, run: onback });
    out.push({ keys: "?", pad: "View", say: "Keys", run: onhelp });
    return out;
  });
  const shown = $derived(hints.filter((h) => mode !== "pad" || h.pad));

  const ALL: { keys: string; pad: string; say: string }[] = [
    { keys: "← ↑ ↓ →", pad: "D-pad", say: "Move round" },
    { keys: "Enter", pad: "A", say: "Open what is lit" },
    { keys: "Esc", pad: "B", say: "Back, then leave" },
    { keys: "Q E", pad: "LB RB", say: "The page before or after" },
    { keys: "1 to 8", pad: "", say: "Go to a page" },
    { keys: "L", pad: "", say: "Back to whoever is being answered" },
    { keys: "R", pad: "X", say: "Reply now" },
    { keys: "W", pad: "", say: "Write to them" },
    { keys: "Space", pad: "Start", say: "Stay here, or let it walk round" },
    { keys: "H", pad: "Y", say: "Hide what is written and the pictures" },
    { keys: "M", pad: "", say: "Sound on or off" },
  ];
</script>

<footer class="bph">
  <div class="bph-keys">
    {#each shown as h (h.say)}
      <button class="bph-key" onclick={h.run} disabled={!h.run} tabindex="-1">
        <kbd>{mode === "pad" ? h.pad : h.keys}</kbd>{h.say}
      </button>
    {/each}
  </div>
  {#if help}
    <!-- Up out of the bar, the way a menu comes out of its button. -->
    <div class="bph-list unroll is-up" use:unroll role="dialog" aria-label="Keys">
      {#each ALL as k (k.say)}
        {#if mode !== "pad" || k.pad}
          <div class="bph-line"><kbd>{mode === "pad" ? k.pad : k.keys}</kbd><span>{k.say}</span></div>
        {/if}
      {/each}
    </div>
  {/if}
  {#if showScore}
    <button class="bph-score" onclick={onscore} use:focusable={{ id: "score" }} title="Today" aria-label="Today: {replies} replies, {people} people, {tokens} tokens">
      <span><b><Odometer value={compact(replies)} /></b> replies</span>
      <span><b><Odometer value={compact(people)} /></b> people</span>
      <span><b><Odometer value={compact(tokens)} /></b> tokens</span>
    </button>
  {/if}
</footer>

<style>
  .bph {
    position: relative;
    z-index: 2;
    display: flex;
    min-height: 44px;
    align-items: center;
    justify-content: space-between;
    gap: 18px;
    padding: 4px var(--bp-side) clamp(8px, 1.4vh, 16px);
  }
  .bph-keys { display: flex; min-width: 0; flex-wrap: nowrap; gap: 4px; overflow: hidden; transition: opacity 0.6s ease; }
  /* Asleep, the keys sit out: nobody is about to press one. The score stays, for the room. */
  :global(.bp.is-asleep) .bph-keys { opacity: 0; }
  .bph-key {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 7px;
    height: 32px;
    padding: 0 9px 0 5px;
    border-radius: 999px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--bp-faint);
    transition: color 0.2s ease, transform 0.45s var(--jelly);
  }
  .bph-key:hover:not(:disabled) { color: var(--color-ink); }
  .bph-key:active:not(:disabled) { transform: scale(0.94); transition-duration: 0.09s; }
  kbd {
    display: inline-block;
    min-width: 22px;
    height: 22px;
    padding: 0 7px;
    border-radius: 7px;
    font-family: inherit;
    font-size: 11.5px;
    font-weight: 650;
    line-height: 22px;
    text-align: center;
    color: var(--bp-muted);
    background: var(--bp-fill);
  }
  .bph-list {
    position: absolute;
    left: var(--bp-side);
    bottom: calc(100% + 2px);
    z-index: 5;
    display: flex;
    width: min(440px, 80vw);
    flex-direction: column;
    gap: 9px;
    padding: 18px 20px;
    border-radius: var(--bp-r);
    background: color-mix(in srgb, var(--color-accent) 14%, #10111a);
    box-shadow: 0 30px 80px -30px rgb(0 0 0 / 0.8);
  }
  .bph-line { display: flex; align-items: center; gap: 12px; font-size: 14px; color: var(--color-ink); }
  .bph-line kbd { flex-shrink: 0; min-width: 78px; }
  .bph-score {
    display: flex;
    flex-shrink: 0;
    align-items: baseline;
    gap: clamp(12px, 1.3vw, 24px);
    padding: 5px 10px;
    border-radius: 12px;
    font-size: clamp(12px, 0.8vw, 14px);
    font-weight: 600;
    color: var(--bp-faint);
    transition: transform 0.45s var(--jelly);
  }
  .bph-score:active { transform: scale(0.97); transition-duration: 0.09s; }
  .bph-score b { font-size: clamp(15px, 1.15vw, 21px); font-weight: 700; color: var(--color-ink); }
  @media (max-width: 1100px) {
    .bph-keys { display: none; }
    .bph { justify-content: flex-end; }
  }
  @media (max-width: 720px) {
    .bph { justify-content: center; }
    .bph-list { display: none; }
  }
</style>
