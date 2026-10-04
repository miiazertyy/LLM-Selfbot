<script lang="ts">
  /**
   * Night hours on a 24-hour clock you drag, instead of "2-8" in a box.
   *
   * Midnight at the top, noon at the bottom. The night is the arc between the
   * moon (when it goes to sleep) and the sun (when it wakes), glowing from
   * night into dawn, with a few stars in it. Drag either end round the dial,
   * drag the night itself to move the whole of it, or click the ring to bring
   * the nearer end there. Or click either time in the middle and type it. The
   * line under the clock says whether the account is asleep or awake, on the
   * persona's clock, and how long until that changes. (A hand for the time
   * now used to point in from the rim too; the line already says it, and the
   * hand read as a stray mark.)
   *
   * The two times sit one over the other in the middle, each with the moon or
   * the sun of the end it is: on one line they were wider than the space
   * inside the hour numbers and ran over "18" and "06". Nothing round the
   * clock changes its size as it is dragged: the times are not re-popped at
   * every step, and the line under it wraps inside a width of its own rather
   * than widening the row. The hour marks reach out after an end as it goes
   * past them (lib/pluck.ts).
   *
   * The same size as the other dials in Settings (Dial.svelte), so a page of
   * them reads as one set of instruments.
   *
   * Whole hours, because that is what the runner reads ("2-8", or "23-7" past
   * midnight; the same hour at both ends is no night at all; see clock.ts).
   * The handles are real sliders, so the arrow keys move them too.
   */
  import { onMount, tick, untrack } from "svelte";
  import { Tween } from "svelte/motion";
  import { quintOut } from "svelte/easing";
  import { motionEnabled } from "../stores";
  import { onScreen, whenShown } from "../cascade";
  import { marksPath, passed, pluck } from "../pluck";
  import { play } from "../uisound";
  import { angleOf, duration, formatHours, hh, hourAt, isNight, nearer, parseHours, readHour, span, untilChange,
           wrap, zoneNow, type Hours } from "../clock";

  /** What the clock is of, in words: the night by default, or Snapchat's quiet hours. */
  type Words = {
    label: string; what: string; none: string; on: string; off: string;
    goesOn: string; goesOff: string; starts: string; ends: string; moves: string;
  };
  const NIGHT: Words = {
    label: "Night hours", what: "of night", none: "No night", on: "Asleep", off: "Awake",
    goesOn: "sleeps", goesOff: "wakes", starts: "Night starts", ends: "Night ends",
    moves: "Drag to move the whole night",
  };

  let { value = "", timezone = "", words = NIGHT, onchange }: {
    /** The setting as stored: "2-8". */
    value?: string;
    /** Whose clock the "now" hand reads: the night timezone. */
    timezone?: string;
    words?: Words;
    onchange?: (v: string) => void;
  } = $props();

  const SIZE = 164;
  const C = SIZE / 2;
  /** The ring the night is drawn on. */
  const R = 58;

  const parsed = $derived(parseHours(value));
  const hours = $derived<Hours>(parsed ?? { start: 2, end: 8 });
  const off = $derived(hours.start === hours.end);

  /** The same hour as the value nearest `cur`: 23 to 0 turns one step on, not back round the whole dial. */
  const near = (cur: number, h: number) => h + 24 * Math.round((cur - h) / 24);

  // The ends glide to where they are set; on arrival the night sweeps in from
  // midnight, as the clock drops in with the tab's opening. Quick off the mark
  // and a long, soft finish (quintOut), not a dash and a sudden stop.
  const tStart = new Tween(0, { duration: 900, easing: quintOut });
  const tEnd = new Tween(0, { duration: 900, easing: quintOut });
  let dragging = $state<"start" | "end" | "both" | null>(null);
  let shown = $state(false);
  let swept = false;
  /** Past its sweep in: from then on the hour marks an end passes are plucked. */
  let plucking = false;
  /** Off screen as its tab opened: the first setting is not swept to. */
  let instant = false;
  /** Sweeping in where it is seen: the hours it passes are heard, softly, though not plucked. */
  let winding = false;
  $effect(() => {
    const el = svg;
    if (el) whenShown(el).then(() => onScreen(el)).then((seen) => {
      // Below what the window shows: straight to its value, no sweep nobody would see.
      instant = !seen;
      winding = seen && $motionEnabled;
      shown = true;
      setTimeout(() => {
        plucking = true;
        winding = false;
      }, seen ? 1200 : 0);
    });
  });
  $effect(() => {
    const h = hours;
    if (!shown) return;
    const d = !$motionEnabled || instant ? 0 : dragging ? 110 : swept ? 800 : 1100;
    instant = false;
    swept = true;
    tStart.set(near(tStart.target, h.start), { duration: d });
    tEnd.set(near(tEnd.target, h.end), { duration: d });
  });

  const pt = (hour: number, r: number) => {
    const a = angleOf(hour);
    return { x: C + r * Math.sin(a), y: C - r * Math.cos(a) };
  };
  const s = $derived(tStart.current);
  const lengthNow = $derived(Math.min(23.98, (((tEnd.current - s) % 24) + 24) % 24));
  const arc = $derived.by(() => {
    if (lengthNow < 0.02) return "";
    const a = pt(s, R);
    const b = pt(s + lengthNow, R);
    return `M ${a.x.toFixed(2)} ${a.y.toFixed(2)} A ${R} ${R} 0 ${lengthNow > 12 ? 1 : 0} 1 ${b.x.toFixed(2)} ${b.y.toFixed(2)}`;
  });
  const moon = $derived(pt(s, R));
  const sun = $derived(pt(s + lengthNow, R));
  /** A few stars sparkling in the band of the night itself, moving with it, and never over the words. */
  const stars = $derived.by(() => {
    if (lengthNow < 1.5) return [];
    const n = Math.min(7, Math.ceil(lengthNow / 1.5));
    return Array.from({ length: n }, (_, i) => ({ ...pt(s + (lengthNow * (i + 0.5)) / n, R + ((i % 3) - 1) * 2.6), i }));
  });

  // Now, in the persona's timezone: ticked every twenty seconds, which a minute hand needs.
  let clock = $state(new Date());
  onMount(() => {
    const id = setInterval(() => (clock = new Date()), 20_000);
    return () => clearInterval(id);
  });
  const now = $derived(zoneNow(timezone || Intl.DateTimeFormat().resolvedOptions().timeZone, clock));
  const asleep = $derived(now ? isNight(hours, now.hour) : false);
  const next = $derived(now ? untilChange(hours, now.hour, now.minute) : null);

  // ── Dragging ───────────────────────────────────────────────────────────────
  let svg: SVGSVGElement | null = $state(null);
  let grabbedAt = 0;
  let grabbed: Hours = { start: 0, end: 0 };

  function hourOf(e: PointerEvent): number {
    const r = svg!.getBoundingClientRect();
    const k = SIZE / r.width;
    return hourAt((e.clientX - r.left) * k - C, (e.clientY - r.top) * k - C);
  }
  function put(h: Hours) {
    if (formatHours(h) !== value) onchange?.(formatHours(h));
  }
  function grab(what: "start" | "end" | "both", e: PointerEvent) {
    if (!svg || e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    svg.setPointerCapture(e.pointerId);
    if (!dragging) play("grab");
    dragging = what;
    grabbedAt = hourOf(e);
    grabbed = { ...hours };
  }
  /** A press on the ring: the nearer end jumps there, and keeps following the pointer. */
  function pressRing(e: PointerEvent) {
    if (!svg || e.button !== 0) return;
    const h = hourOf(e);
    const which = nearer(hours, h);
    put({ ...hours, [which]: h });
    grab(which, e);
  }
  function move(e: PointerEvent) {
    if (!dragging) return;
    const h = hourOf(e);
    if (dragging === "both") {
      const d = h - grabbedAt;
      put({ start: wrap(grabbed.start + d), end: wrap(grabbed.end + d) });
    } else {
      put({ ...hours, [dragging]: h });
    }
  }
  function release(e: PointerEvent) {
    if (!dragging) return;
    dragging = null;
    play("release");
    svg?.releasePointerCapture?.(e.pointerId);
  }
  function key(which: "start" | "end", e: KeyboardEvent) {
    const by: Record<string, number> = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 3, PageDown: -3 };
    if (!(e.key in by)) return;
    e.preventDefault();
    put({ ...hours, [which]: wrap(hours[which] + by[e.key]) });
  }

  // ── Typing a time ──────────────────────────────────────────────────────────
  // Click either time in the middle and it becomes a box: "23", "7am", "19:00".
  let typing = $state<"start" | "end" | null>(null);
  let draft = $state("");
  let box: HTMLInputElement | null = $state(null);
  async function type(which: "start" | "end") {
    typing = which;
    draft = String(hours[which]).padStart(2, "0");
    await tick();
    box?.select();
  }
  function typed() {
    if (!typing) return;
    const which = typing;
    typing = null;
    const h = readHour(draft);
    if (h != null) put({ ...hours, [which]: h });
  }
  function typingKey(e: KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      typed();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      typing = null;
    }
  }

  /**
   * The hour marks, each from its inner end `a` to its outer `b`, every sixth
   * a longer one. Drawn as a few paths, not one element each (see
   * lib/pluck.ts), with the night's own ones in its colour.
   */
  const MARKS = Array.from({ length: 24 }, (_, h) => ({
    a: pt(h, R + 9), b: pt(h, R + (h % 6 === 0 ? 15 : 12)), major: h % 6 === 0, h,
  }));
  const MINOR = marksPath(MARKS.filter((m) => !m.major));
  const MAJOR = marksPath(MARKS.filter((m) => m.major));
  const lit = $derived(off ? [] : MARKS.filter((m) => isNight(hours, m.h)));
  const litMinor = $derived(marksPath(lit.filter((m) => !m.major)));
  const litMajor = $derived(marksPath(lit.filter((m) => m.major)));
  /** Where a pluck draws its line, over the marks. */
  let plucks: SVGGElement | null = $state(null);
  let wasStart = 0;
  let wasEnd = 0;
  $effect(() => {
    const a = tStart.current;
    const b = tEnd.current;
    untrack(() => {
      if (!plucking) {
        // The night sweeping in from midnight as the tab opens: each hour it passes, a soft detent.
        if (winding) {
          for (const k of [...passed(wasStart, a, 1), ...passed(wasEnd, b, 1)]) {
            const h = ((k % 24) + 24) % 24;
            play("wind", { p: h / 24, strong: MARKS[h].major });
          }
        }
        wasStart = a;
        wasEnd = b;
        return;
      }
      const go = (from: number, to: number) => {
        for (const k of passed(from, to, 1)) {
          const h = ((k % 24) + 24) % 24;
          pluck(plucks, MARKS[h].a, MARKS[h].b, MARKS[h].major ? 1.5 : 1, MARKS[h].major ? 1.55 : 2.1);
          // The sound of it, an hour at a time: heard with Animations off too.
          play("tick", { p: h / 24, strong: MARKS[h].major });
        }
      };
      go(wasStart, a);
      go(wasEnd, b);
      wasStart = a;
      wasEnd = b;
    });
  });

  /**
   * A press on the arc or the ring, for the pointer only: the handles are the
   * sliders a keyboard moves, and these are shortcuts beside them, so they are
   * listened to rather than made into controls of their own.
   */
  function press(node: SVGElement, fn: (e: PointerEvent) => void) {
    let call = fn;
    const on = (e: PointerEvent) => call(e);
    node.addEventListener("pointerdown", on);
    return {
      update(next: (e: PointerEvent) => void) {
        call = next;
      },
      destroy() {
        node.removeEventListener("pointerdown", on);
      },
    };
  }
</script>

<!-- One time in the middle: a button that turns into a box to type it. -->
{#snippet time(which: "start" | "end")}
  {#if typing === which}
    <input bind:this={box} bind:value={draft} class="hr-type" inputmode="numeric" maxlength="7" spellcheck="false"
           aria-label="{which === 'start' ? words.starts : words.ends}, as an hour" onkeydown={typingKey} onblur={typed} />
  {:else}
    <button type="button" class="hr-time" onclick={() => type(which)} title="Click to type an hour">{hh(hours[which])}</button>
  {/if}
{/snippet}

<div class="hr-wrap">
  <div class="hr" class:is-dragging={!!dragging} class:is-off={off}>
    <svg bind:this={svg} viewBox="0 0 {SIZE} {SIZE}" width={SIZE} height={SIZE} role="group"
         aria-label="{words.label}: {hh(hours.start)} to {hh(hours.end)}"
         onpointermove={move} onpointerup={release} onpointercancel={release}>
      <defs>
        <!-- Night into dawn: from the moon's end of the arc to the sun's. -->
        <linearGradient id="hr-night" gradientUnits="userSpaceOnUse" x1={moon.x} y1={moon.y} x2={sun.x} y2={sun.y}>
          <stop offset="0" stop-color="#6d5dfc" />
          <stop offset="0.55" stop-color="color-mix(in srgb, var(--color-accent) 80%, #6d5dfc)" />
          <stop offset="1" stop-color="#ffb46b" />
        </linearGradient>
        <radialGradient id="hr-face" cx="0.5" cy="0.4" r="0.7">
          <stop offset="0" stop-color="rgb(255 255 255 / 0.065)" />
          <stop offset="1" stop-color="rgb(255 255 255 / 0.01)" />
        </radialGradient>
      </defs>

      <!-- The face, and the day around the night. -->
      <circle cx={C} cy={C} r={R + 20} class="hr-face" fill="url(#hr-face)" />
      <circle cx={C} cy={C} r={R} class="hr-track" />
      <path d={MINOR} class="hr-tick" />
      <path d={MAJOR} class="hr-tick is-major" />
      {#if litMinor}<path d={litMinor} class="hr-tick is-in" />{/if}
      {#if litMajor}<path d={litMajor} class="hr-tick is-major is-in" />{/if}
      <g bind:this={plucks} class="hr-plucks"></g>
      {#each [0, 6, 12, 18] as h (h)}
        {@const p = pt(h, R - 14)}
        <text x={p.x} y={p.y} class="hr-num">{String(h).padStart(2, "0")}</text>
      {/each}

      <!-- The ring itself, wide and invisible, under the night: a press on the ring brings the
           nearer end there, a press on the night (drawn over it) takes the whole night. -->
      <circle cx={C} cy={C} r={R} class="hr-hit" use:press={pressRing} />

      <!-- The night: a soft glow under it, the arc, stars in it. Dragging it moves the whole night. -->
      {#if arc}
        <!-- The glow: two wide, faint strokes rather than a blur, which had to be worked out again every frame. -->
        <path d={arc} class="hr-glow is-wide" stroke="url(#hr-night)" />
        <path d={arc} class="hr-glow" stroke="url(#hr-night)" />
        <path d={arc} class="hr-arc" stroke="url(#hr-night)" use:press={(e) => grab("both", e)}>
          <title>{words.moves}</title>
        </path>
        {#each stars as st (st.i)}
          <circle cx={st.x} cy={st.y} r={st.i % 3 === 0 ? 1.1 : 0.8} class="hr-star" style="animation-delay: {-st.i * 0.47}s" />
        {/each}
      {/if}

      <!-- The two ends: the moon (it goes to sleep) and the sun (it wakes). -->
      <g class="hr-handle is-moon" class:is-grabbed={dragging === "start"} transform="translate({moon.x} {moon.y})"
         role="slider" tabindex="0" aria-label={words.starts} aria-valuemin="0" aria-valuemax="23"
         aria-valuenow={hours.start} aria-valuetext={hh(hours.start)}
         onpointerdown={(e) => grab("start", e)} onkeydown={(e) => key("start", e)}>
        <circle r="10.5" class="hr-knob" />
        <path d="M3.2 -4.6 A6 6 0 1 0 4.6 3.4 A4.8 4.8 0 1 1 3.2 -4.6 Z" class="hr-glyph" transform="scale(0.7)" />
      </g>
      <g class="hr-handle is-sun" class:is-grabbed={dragging === "end"} transform="translate({sun.x} {sun.y})"
         role="slider" tabindex="0" aria-label={words.ends} aria-valuemin="0" aria-valuemax="23"
         aria-valuenow={hours.end} aria-valuetext={hh(hours.end)}
         onpointerdown={(e) => grab("end", e)} onkeydown={(e) => key("end", e)}>
        <circle r="10.5" class="hr-knob" />
        <circle r="2.5" class="hr-glyph" />
        {#each [0, 45, 90, 135, 180, 225, 270, 315] as deg (deg)}
          <line x1="0" y1="-4.2" x2="0" y2="-5.9" transform="rotate({deg})" class="hr-ray" />
        {/each}
      </g>
    </svg>

    <!-- The middle of the clock: the night in words. Either time can be clicked and typed. -->
    <div class="hr-mid">
      {#if off && !typing}
        <button type="button" class="hr-time is-none" onclick={() => type("end")} title="Click to type when it ends">
          {words.none}
        </button>
        <span class="hr-sub">both ends at {hh(hours.start)}</span>
      {:else}
        <!-- One over the other, each by the glyph of its end, so they fit inside the hour numbers. -->
        <b class="hr-big">
          <span class="hr-row is-moon"><svg viewBox="-6 -6 12 12" aria-hidden="true"><path d="M3.2 -4.6 A6 6 0 1 0 4.6 3.4 A4.8 4.8 0 1 1 3.2 -4.6 Z" /></svg>{@render time("start")}</span>
          <span class="hr-row is-sun"><svg viewBox="-6 -6 12 12" aria-hidden="true"><circle r="2.6" />{#each [0, 45, 90, 135, 180, 225, 270, 315] as deg (deg)}<line x1="0" y1="-4" x2="0" y2="-5.6" transform="rotate({deg})" />{/each}</svg>{@render time("end")}</span>
        </b>
        <span class="hr-sub">{span(hours)} h {words.what}</span>
      {/if}
    </div>
  </div>

  <!-- How the account is right now, under the clock rather than squeezed into it. -->
  <p class="hr-state" class:is-asleep={asleep} class:is-bad={!now} aria-live="polite">
    {#if !parsed && value}
      <span class="hr-warn">"{value}" is not a range; dragging writes one</span>
    {:else if off}
      <i></i>{words.none}
    {:else if now}
      <i></i>{asleep ? words.on : words.off}{#if next != null} · {asleep ? words.goesOff : words.goesOn} in {duration(next)}{/if}
    {:else}
      <i></i>Unknown timezone
    {/if}
  </p>
</div>

<style>
  /* A width of its own: the line under the clock wraps inside it, rather than
     widening the row as it changes while the clock is dragged. */
  .hr-wrap { display: flex; width: 200px; flex-shrink: 0; flex-direction: column; align-items: center; gap: 4px; }
  /* A fixed size, laid out on its own: its ends gliding every frame stay inside it. */
  .hr { position: relative; display: grid; width: 164px; height: 164px; flex-shrink: 0; touch-action: none; user-select: none; contain: layout style; }
  .hr svg { display: block; overflow: visible; }
  .hr-face { stroke: rgb(255 255 255 / 0.05); stroke-width: 1; }
  .hr-track { fill: none; stroke: rgb(255 255 255 / 0.07); stroke-width: 10; }
  .hr-tick {
    fill: none;
    stroke: rgb(255 255 255 / 0.13);
    stroke-width: 1;
    stroke-linecap: round;
  }
  .hr-tick.is-major { stroke: rgb(255 255 255 / 0.28); stroke-width: 1.5; }
  .hr-tick.is-in { stroke: color-mix(in srgb, var(--color-accent) 75%, white); }
  .hr-num { font-size: 8.5px; font-weight: 650; fill: var(--color-faint); text-anchor: middle; dominant-baseline: central; }
  .hr-glow { fill: none; stroke-width: 15; stroke-linecap: round; opacity: 0.14; pointer-events: none; }
  .hr-glow.is-wide { stroke-width: 22; opacity: 0.06; }
  .hr-arc { fill: none; stroke-width: 10; stroke-linecap: round; cursor: grab; transition: stroke-width 0.25s var(--spring); }
  .hr-arc:hover { stroke-width: 12; }
  .hr.is-dragging .hr-arc { cursor: grabbing; }
  .hr-hit { fill: none; stroke: transparent; stroke-width: 26; cursor: pointer; }
  .hr-star { fill: #fff; opacity: 0.8; animation: hr-twinkle 2.6s ease-in-out infinite; pointer-events: none; }
  @keyframes hr-twinkle { 50% { opacity: 0.15; } }

  .hr-handle { cursor: grab; outline: none; }
  .hr.is-dragging .hr-handle { cursor: grabbing; }
  .hr-knob {
    fill: rgb(20 22 34);
    stroke-width: 2.5;
    transition: transform 0.35s var(--spring), stroke-width 0.2s ease;
    transform-box: fill-box;
    transform-origin: center;
  }
  .hr-handle.is-moon .hr-knob { stroke: #8f80ff; }
  .hr-handle.is-sun .hr-knob { stroke: #ffb46b; }
  .hr-handle:hover .hr-knob, .hr-handle:focus-visible .hr-knob { transform: scale(1.14); }
  .hr-handle.is-grabbed .hr-knob { transform: scale(1.25); stroke-width: 3; }
  .hr-handle:focus-visible .hr-knob { stroke-width: 3.5; }
  .hr-handle.is-moon .hr-glyph { fill: #c9c1ff; pointer-events: none; }
  .hr-handle.is-sun .hr-glyph { fill: #ffcf8a; pointer-events: none; }
  .hr-ray { stroke: #ffcf8a; stroke-width: 1.3; stroke-linecap: round; pointer-events: none; }

  .hr-mid {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    text-align: center;
    pointer-events: none;
  }
  .hr-big { display: flex; flex-direction: column; align-items: center; gap: 0; font-size: 14.5px; font-weight: 750; line-height: 1.2; letter-spacing: -0.02em; color: var(--color-ink); font-variant-numeric: tabular-nums; }
  /* Each time with the glyph of its end, nudged left so the time itself sits in the middle. */
  .hr-row { display: inline-flex; align-items: center; gap: 3px; margin-left: -12px; }
  .hr-row svg { width: 9px; height: 9px; flex-shrink: 0; overflow: visible; }
  .hr-row.is-moon svg path { fill: #b3a8ff; }
  .hr-row.is-sun svg circle { fill: #ffcf8a; }
  .hr-row.is-sun svg line { stroke: #ffcf8a; stroke-width: 1.2; stroke-linecap: round; }
  /* A time you can click to type: it says so on hover. */
  .hr-time {
    padding: 1px 3px;
    border-radius: 6px;
    font: inherit;
    color: inherit;
    cursor: text;
    pointer-events: auto;
    transition: background-color 0.18s var(--swift), color 0.18s var(--swift);
  }
  .hr-time:hover { background: rgb(255 255 255 / 0.08); color: var(--color-accent); }
  .hr-time:focus-visible { outline: none; box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-accent) 45%, transparent); }
  .hr-time.is-none { font-size: 14px; font-weight: 750; color: var(--color-ink); }
  .hr-type {
    width: 3.4ch;
    padding: 0 2px;
    border-radius: 6px;
    border: 1px solid color-mix(in srgb, var(--color-accent) 60%, transparent);
    background: rgb(0 0 0 / 0.35);
    font: inherit;
    text-align: center;
    color: var(--color-ink);
    outline: none;
    pointer-events: auto;
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 16%, transparent);
  }
  .hr-sub { font-size: 9.5px; color: var(--color-muted); }

  .hr-state { display: inline-flex; align-items: center; justify-content: center; gap: 5px; width: 100%; min-height: 28px; font-size: 10.5px; line-height: 1.3; text-align: center; color: #ffcf8a; }
  .hr-state i { width: 6px; height: 6px; flex-shrink: 0; border-radius: 999px; background: currentColor; }
  .hr-state.is-asleep { color: #b3a8ff; }
  .hr-state.is-bad { color: var(--color-warn); }
  .hr-warn { color: var(--color-warn); }
  :global(:root[data-motion="off"]) .hr-star { animation: none; }
</style>
