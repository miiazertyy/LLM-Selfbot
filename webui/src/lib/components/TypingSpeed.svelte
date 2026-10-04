<script lang="ts">
  /**
   * How fast it types: a dial for the slowest and fastest words per minute,
   * beside a little keyboard typing real messages at those speeds, so "30"
   * and "72" are something you watch rather than numbers you trust.
   *
   * Each message is typed at a speed picked between the two, as the runner
   * does: one at the slowest, one at the fastest, one anywhere between, and
   * round again. Every key lights as it is pressed, the words appear in the
   * message box above it with a caret, and the finished message is sent off.
   * It follows the dial as it is dragged. It only types while it is on
   * screen, and not at all with the app's motion switched off.
   */
  import { onMount } from "svelte";
  import { motionEnabled } from "../stores";
  import Dial from "./Dial.svelte";
  import { wpmScale } from "../dialscale";
  import { play } from "../uisound";

  let { slow, fast, min, max, onchange }: {
    slow: number;
    fast: number;
    /** The setting's own bounds. */
    min?: number;
    max?: number;
    onchange: (v: number[]) => void;
  } = $props();

  const LINES = [
    "omg sorry just saw this",
    "wait what did he say",
    "ok im on my way",
    "lol thats so true",
    "brb getting food",
    "nah its fine dont worry",
  ];
  const ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"];

  let text = $state(LINES[0]);
  let lit = $state<string | null>(null);
  let pace = $state<"slowest" | "fastest" | "between">("slowest");
  let between = $state(0);
  let sent = $state<{ text: string; n: number } | null>(null);
  let typing = $state(false);
  let root: HTMLElement | null = $state(null);
  let seen = $state(false);

  const lo = $derived(Math.min(Number(slow) || 0, Number(fast) || 0));
  const hiSpeed = $derived(Math.max(Number(slow) || 0, Number(fast) || 0));
  /** The speed the message on screen is typed at, following the dial while it moves. */
  const speed = $derived(pace === "slowest" ? lo : pace === "fastest" ? hiSpeed : between);

  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
  let run = 0;

  /** Wait while it is off screen, hidden, or motion is off; false once it should stop altogether. */
  async function allowed(id: number): Promise<boolean> {
    while (id === run && (!seen || document.hidden || !$motionEnabled)) await sleep(400);
    return id === run;
  }

  async function loop(id: number) {
    let n = 0;
    // Not while the tab is still opening: the keys start once the row has landed.
    await sleep(750);
    while (id === run) {
      const line = LINES[n % LINES.length];
      pace = (["slowest", "fastest", "between"] as const)[n % 3];
      between = Math.round(lo + Math.random() * (hiSpeed - lo));
      text = "";
      typing = true;
      for (const ch of line) {
        if (!(await allowed(id))) return;
        // Five characters to a word, as words per minute are counted, give or
        // take a little the way a person's keystrokes are never even.
        const cps = (Math.max(1, speed) * 5) / 60;
        let ms = (1000 / cps) * (0.7 + Math.random() * 0.6);
        if (ch === " ") ms *= 1.2;
        await sleep(ms);
        if (id !== run) return;
        text += ch;
        press(ch === " " ? "space" : ch, Math.min(150, ms * 0.7));
      }
      typing = false;
      await sleep(1100);
      if (!(await allowed(id))) return;
      sent = { text: line, n };
      // Sent off, softly: it goes on for as long as it is on screen.
      play("send", { level: 0.4 });
      text = "";
      await sleep(900);
      n++;
    }
  }

  let unlight = 0;
  function press(key: string, ms: number) {
    lit = key;
    // Each key heard as it lights, softly (the space bar a little lower and heavier), at the speed it types.
    play("key", { strong: key === "space", level: 0.8 });
    clearTimeout(unlight);
    unlight = window.setTimeout(() => (lit = null), ms);
  }

  onMount(() => {
    const io = new IntersectionObserver((es) => (seen = es.some((e) => e.isIntersecting)));
    if (root) io.observe(root);
    const id = ++run;
    loop(id);
    return () => {
      run++;
      io.disconnect();
      clearTimeout(unlight);
    };
  });
</script>

<div class="ts" bind:this={root}>
  <div class="ts-pad" aria-hidden="true">
    <!-- The message being written, and the last one sent floating off above it. -->
    <div class="ts-box">
      {#if sent}
        {#key sent.n}<span class="ts-sent">{sent.text}</span>{/key}
      {/if}
      <span class="ts-text">{$motionEnabled ? text : LINES[0]}</span><i class="ts-caret" class:is-typing={typing}></i>
    </div>
    <div class="ts-keys">
      {#each ROWS as row, r (row)}
        <div class="ts-row" style="padding-left: {r * 9}px">
          {#each row as k (k)}
            <span class="ts-key" class:is-lit={lit === k}>{k}</span>
          {/each}
        </div>
      {/each}
      <div class="ts-row"><span class="ts-key is-space" class:is-lit={lit === "space"}></span></div>
    </div>
    <p class="ts-speed">
      <i class="is-{pace}"></i>
      {Math.round(speed)} wpm <span>· {pace === "between" ? "in between" : pace}</span>
    </p>
  </div>

  <Dial values={[Number(slow) || 0, Number(fast) || 0]} scale={wpmScale({ min, max })} names={["Slowest", "Fastest"]}
        hint="words a minute" tone="is-speed" {onchange} />
</div>

<style>
  .ts { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 14px; }
  /* No panel round it: the message line, the keys and the speed sit straight
     on the row. The box they were in took more room than they did. */
  .ts-pad {
    display: flex;
    width: 204px;
    flex-direction: column;
    gap: 6px;
  }

  /* The message box, like the one at the bottom of a chat. */
  .ts-box {
    position: relative;
    display: flex;
    height: 28px;
    align-items: center;
    padding: 0 9px;
    border-radius: 9px;
    background: rgb(0 0 0 / 0.28);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.05);
    font-size: 12px;
    color: var(--color-ink);
    white-space: nowrap;
  }
  .ts-text { overflow: hidden; text-overflow: clip; }
  .ts-caret {
    width: 1.5px;
    height: 14px;
    margin-left: 1px;
    flex-shrink: 0;
    border-radius: 1px;
    background: #ff8a5c;
    animation: ts-blink 1s steps(1) infinite;
  }
  .ts-caret.is-typing { animation: none; }
  @keyframes ts-blink { 50% { opacity: 0; } }
  /* Sent: it lifts off the box as a bubble and fades. */
  .ts-sent {
    position: absolute;
    right: 6px;
    bottom: 100%;
    max-width: 92%;
    overflow: hidden;
    padding: 3px 8px;
    border-radius: 10px 10px 3px 10px;
    font-size: 11px;
    text-overflow: ellipsis;
    color: #fff;
    background: linear-gradient(135deg, var(--color-accent), color-mix(in srgb, var(--color-accent) 60%, #ff8a5c));
    pointer-events: none;
    animation: ts-send 1.5s var(--swift) both;
  }
  @keyframes ts-send {
    0% { opacity: 0; transform: translateY(14px) scale(0.85); }
    18% { opacity: 1; transform: translateY(-2px) scale(1); }
    70% { opacity: 1; transform: translateY(-6px); }
    100% { opacity: 0; transform: translateY(-16px); }
  }

  .ts-keys { display: flex; flex-direction: column; gap: 3px; }
  .ts-row { display: flex; gap: 3px; }
  .ts-key {
    display: grid;
    width: 17.6px;
    height: 19px;
    place-items: center;
    border-radius: 5px;
    font-size: 8.5px;
    font-weight: 650;
    text-transform: uppercase;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 0 -1.5px 0 rgb(0 0 0 / 0.35), inset 0 0 0 1px rgb(255 255 255 / 0.05);
    transition:
      background-color 0.4s var(--swift),
      color 0.4s var(--swift),
      box-shadow 0.4s var(--swift),
      transform 0.4s var(--jelly);
  }
  .ts-key.is-space { width: 110px; margin-left: 38px; }
  /* Pressed: lit at once, in the colour of the speed it is typing at, then cooling. */
  .ts-key.is-lit {
    color: #fff;
    background: color-mix(in srgb, #ff8a5c 75%, var(--color-accent));
    box-shadow: 0 0 12px color-mix(in srgb, #ff8a5c 55%, transparent), inset 0 1px 0 rgb(255 255 255 / 0.3);
    transform: translateY(1.5px) scale(0.92);
    transition-duration: 0.03s;
  }

  .ts-speed { display: flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 650; color: var(--color-ink); font-variant-numeric: tabular-nums; }
  .ts-speed span { font-weight: 500; color: var(--color-muted); }
  .ts-speed i { width: 7px; height: 7px; border-radius: 999px; transition: background-color 0.3s ease; }
  .ts-speed i.is-slowest { background: #4ecdc4; }
  .ts-speed i.is-fastest { background: #ff8a5c; }
  .ts-speed i.is-between { background: linear-gradient(90deg, #4ecdc4, #ff8a5c); }

  :global(:root[data-motion="off"]) .ts-caret,
  :global(:root[data-motion="off"]) .ts-sent { animation: none; }
  :global(:root[data-motion="off"]) .ts-key { transition: none; }
</style>
