<script lang="ts" module>
  /**
   * Switches that arrive together go on one after another, top to bottom, like dominoes: very fast, a few
   * hundredths of a second apart, each one's click a note higher. A card of them used to land and go on
   * all at once.
   */
  const STEP = 40;
  let queue: { el: Element; go: (k: number, wait: number) => void }[] = [];
  let frame = 0;
  /** When the last one goes, and how far along the run it is. */
  let lastAt = -1e9;
  let run = 0;

  function domino(el: Element, go: (k: number, wait: number) => void) {
    queue.push({ el, go });
    if (!frame) frame = requestAnimationFrame(fall);
  }

  /**
   * Each is set going at once with how long to wait (its knob's animation
   * delay, and its sound booked as far ahead): the browser's clock keeps the
   * gaps. Timers fired one at a time bunched up while the tab was busy
   * opening, two going in the same instant.
   */
  function fall() {
    frame = 0;
    const now = performance.now();
    // In reading order, whatever order they asked in.
    const batch = queue
      .map((w) => ({ w, r: w.el.getBoundingClientRect() }))
      .sort((a, b) => a.r.top - b.r.top || a.r.left - b.r.left);
    queue = [];
    // A run carries on while its last one is still going; after a pause a new one starts from the bottom note.
    if (now - lastAt > 250) run = 0;
    let at = Math.max(now, lastAt + STEP);
    for (const { w } of batch) {
      w.go(run++, Math.round(at - now));
      lastAt = at;
      at += STEP;
    }
  }
</script>

<script lang="ts">
  /**
   * An on-off switch, kept quiet.
   *
   * A plain track and a round knob. Off, the track is a faint groove and the
   * knob is grey. On, the track takes a muted shade of the accent and the knob
   * turns white. The last version filled with the accent gradient, glowed and
   * wrote ON inside itself, which was loud in a page full of them. The knob
   * stretches a little while it is held, and settles when it lands.
   */
  let {
    checked = $bindable(false),
    disabled = false,
    label = "",
    name = "",
    size = "md",
    onchange,
  } = $props<{
    checked?: boolean;
    disabled?: boolean;
    /** Written beside the switch. */
    label?: string;
    /** What it switches, for screen readers, where nothing is written beside it. */
    name?: string;
    size?: "md" | "sm";
    onchange?: (v: boolean) => void;
  }>();

  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { afterLanding, onScreen, whenShown } from "../cascade";
  import { motionEnabled } from "../stores";
  import { play } from "../uisound";

  let pressed = $state(false);
  let btn: HTMLButtonElement | null = $state(null);
  /** Arrived: until its row drops in, an on switch sits off, then slides on. */
  let arrived = $state(false);
  /**
   * Arriving: the slide on as the tab opens is its own, a snap into place
   * that is seen. It used the click's quick one, which played out while the
   * row was still dropping in and was over before anyone saw it. A click,
   * after, is quick again.
   */
  let arriving = $state(false);
  /** Whether it was on screen as its tab opened: only then is its arrival heard. */
  let heardIn = false;
  /** How long its knob waits for its turn in a run of switches going on (see the domino above). */
  let wait = $state(0);
  let done = 0;
  onMount(() => {
    let alive = true;
    if (btn) {
      const el = btn;
      whenShown(el).then(() => {
        if (!alive) return;
        // Off, or with Animations off, it is simply as it is: only a switch going on is a show.
        if (!get(motionEnabled) || !checked) {
          arrived = true;
          return;
        }
        // The slow timing is in place first, the switch still drawn off; it goes on under it at its turn.
        arriving = true;
        afterLanding(el, () =>
          onScreen(el).then((seen) => {
            if (!alive) return;
            // Below what the window shows, or a click came first: on at once, no show.
            if (!seen || !arriving) {
              arriving = false;
              arrived = true;
              return;
            }
            heardIn = seen;
            domino(el, (k, ms) => {
              if (!alive) return;
              if (!arriving) {
                arrived = true;
                return;
              }
              wait = ms;
              arrived = true;
              // Heard as its knob sets off (the next frame, and the animation's own 30ms): a click as
              // it hits the end, a note higher for each switch before it in the run, an octave at most.
              if (heardIn) play("slide", { p: Math.min(k, 7) / 7, delay: ms + 30 });
              // Lets go once the slide has been seen through (knobArrives starts it again when it truly starts).
              clearTimeout(done);
              done = window.setTimeout(() => (arriving = false), 900 + ms);
            });
          }),
        );
      });
    }
    return () => {
      alive = false;
      clearTimeout(done);
    };
  });

  /**
   * The slide is let finish from when the knob's pull across truly starts: it
   * could be cut off before its bounce. (Its sound is booked with its turn, as
   * the domino sets it going; its row has landed by then, so nothing holds it.)
   */
  function knobArrives(e: AnimationEvent) {
    if (!e.animationName.endsWith("tg-arrive")) return;
    clearTimeout(done);
    done = window.setTimeout(() => (arriving = false), 620);
  }

  function toggle() {
    if (disabled) return;
    // A click during the arrival ends it, or before its turn comes: the
    // click's slide takes over from wherever the knob is.
    arriving = false;
    arrived = true;
    checked = !checked;
    play(checked ? "on" : "off");
    onchange?.(checked);
  }
</script>

<button
  type="button"
  role="switch"
  data-sound="self"
  aria-checked={checked}
  aria-label={label || name || "Toggle"}
  {disabled}
  class="tg is-{size}"
  bind:this={btn}
  class:is-on={checked}
  class:is-arrived={arrived}
  class:is-arriving={arriving}
  class:is-pressed={pressed}
  style="--tg-wait: {wait}ms"
  onclick={toggle}
  onpointerdown={() => (pressed = true)}
  onpointerup={() => (pressed = false)}
  onpointerleave={() => (pressed = false)}
>
  <span class="tg-knob" aria-hidden="true" onanimationstart={knobArrives}></span>
</button>
{#if label}<span class="text-sm text-ink">{label}</span>{/if}

<style>
  .tg {
    --w: 42px;
    --h: 24px;
    --k: 18px;
    --pad: 3px;
    /* How far the knob grows while held. */
    --stretch: 4px;
    /* How far the knob goes, off to on. */
    --travel: calc(var(--w) - var(--k) - var(--pad) * 2);
    position: relative;
    width: var(--w);
    height: var(--h);
    flex-shrink: 0;
    border-radius: 999px;
    background: rgb(255 255 255 / 0.08);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06);
    cursor: pointer;
    transition:
      background-color 0.22s var(--swift),
      box-shadow 0.22s var(--swift),
      opacity 0.2s var(--swift);
  }
  .tg.is-sm { --w: 34px; --h: 20px; --k: 14px; --stretch: 3px; }
  .tg:hover:not(:disabled) { background: rgb(255 255 255 / 0.11); }
  .tg:disabled { cursor: not-allowed; opacity: 0.4; }

  /* On: a softened shade of the accent, not the accent at full strength, and
     not so far down that it reads as dark either. */
  .tg.is-on {
    background: color-mix(in srgb, var(--color-accent) 70%, var(--color-card));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 40%, transparent);
  }
  .tg.is-on:hover:not(:disabled) { background: color-mix(in srgb, var(--color-accent) 78%, var(--color-card)); }

  .tg:focus-visible {
    outline: none;
    box-shadow:
      inset 0 0 0 1px rgb(255 255 255 / 0.06),
      0 0 0 3px color-mix(in srgb, var(--color-accent) 32%, transparent);
  }

  .tg-knob {
    position: absolute;
    top: calc((var(--h) - var(--k)) / 2);
    left: var(--pad);
    width: var(--k);
    height: var(--k);
    border-radius: 999px;
    background: color-mix(in srgb, var(--color-ink) 50%, var(--color-card));
    box-shadow: 0 1px 2px rgb(0 0 0 / 0.35);
    /* A small overshoot on the slide, and nothing that wobbles. */
    transition:
      transform 0.3s cubic-bezier(0.3, 1.3, 0.5, 1),
      width 0.18s var(--swift),
      background-color 0.22s var(--swift);
  }
  .tg.is-on .tg-knob {
    transform: translateX(var(--travel));
    background: #f3f4f8;
    box-shadow: 0 1px 3px rgb(0 0 0 / 0.3);
  }
  /* Held: the knob stretches toward where it is going. */
  .tg.is-pressed:not(:disabled) .tg-knob { width: calc(var(--k) + var(--stretch)); }
  .tg.is-on.is-pressed:not(:disabled) .tg-knob {
    transform: translateX(calc(var(--travel) - var(--stretch)));
  }

  /* Not arrived yet: an on switch is drawn off, so it can slide on as its row
     drops in. The knob takes its time, and the colour fills in behind it. */
  .tg.is-on:not(.is-arrived) {
    background: rgb(255 255 255 / 0.08);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06);
  }
  .tg.is-on:not(.is-arrived) .tg-knob {
    transform: none;
    background: color-mix(in srgb, var(--color-ink) 50%, var(--color-card));
  }

  /* Arriving: as the row lands (30ms after) the knob is pulled across,
     faster and faster, hits the end, squashes against it a little past where
     it rests and springs back, the colour filling in behind it. Only going
     past the end, it could not go far enough to be seen (the track stops it
     after 3px), the squash is what shows it. No transform transition while
     it plays: a transition would win over the keyframes. */
  /* Each a turn after the one above it when they arrive together (--tg-wait,
     the domino in the script): the knob, the colour behind it and its sound. */
  .tg.is-arriving {
    transition:
      background-color 0.5s cubic-bezier(0.45, 0, 0.2, 1) calc(0.03s + var(--tg-wait, 0ms)),
      box-shadow 0.5s cubic-bezier(0.45, 0, 0.2, 1) calc(0.03s + var(--tg-wait, 0ms));
  }
  .tg.is-arriving .tg-knob {
    transition:
      background-color 0.42s ease calc(0.09s + var(--tg-wait, 0ms)),
      box-shadow 0.42s ease calc(0.09s + var(--tg-wait, 0ms));
  }
  .tg.is-on.is-arrived.is-arriving .tg-knob { animation: tg-arrive 0.5s calc(0.03s + var(--tg-wait, 0ms)) backwards; }
  @keyframes tg-arrive {
    0% {
      transform: translateX(0) scale(1, 1);
      animation-timing-function: cubic-bezier(0.5, 0.05, 0.85, 0.55);
    }
    /* At the end, drawn out a little by the speed. */
    38% {
      transform: translateX(calc(var(--travel) + 1px)) scale(1.06, 0.97);
      animation-timing-function: cubic-bezier(0.1, 0.75, 0.4, 1);
    }
    /* Squashed against it, its right edge held where it hit. */
    48% {
      transform: translateX(calc(var(--travel) + 3px)) scale(0.84, 1.08);
      animation-timing-function: cubic-bezier(0.3, 0, 0.2, 1);
    }
    100% { transform: translateX(var(--travel)) scale(1, 1); }
  }

  :global(:root[data-motion="off"]) .tg,
  :global(:root[data-motion="off"]) .tg-knob,
  :global(:root[data-motion="off"]) .tg.is-arriving,
  :global(:root[data-motion="off"]) .tg.is-arriving .tg-knob { transition: none; animation: none; }
</style>
