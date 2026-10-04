<script lang="ts">
  /**
   * A count with no top, on a tape you pull: "Stale after 10 newer
   * messages", "200 messages kept in memory".
   *
   * These were bare number boxes. A slider needs two ends and these have
   * one, so the count sits on a strip of marks that goes on for as long as
   * you pull it: drag it (and let go with a flick, it coasts), use the arrow
   * keys, the wheel sideways, or press - and + (held, they repeat and speed
   * up). The marks swell as they pass under the pointer in the middle, like
   * the marks round the clocks, and the digits roll to the new count. Click
   * the number to type one.
   *
   * The notches grow with the count (stepFor), so ten is set one by one and
   * a few hundred by tens without a mile of dragging. Past the bottom the
   * tape resists and springs back. It sweeps in from the bottom as its tab
   * opens, as the dials do.
   */
  import { tick, untrack } from "svelte";
  import { get } from "svelte/store";
  import { motionEnabled } from "../stores";
  import { onScreen, whenShown } from "../cascade";
  import Odometer from "./Odometer.svelte";
  import { stepFor } from "../counts";
  import { play } from "../uisound";

  let { value, min = 0, max, words = { one: "", many: "" }, name = "Count", onchange }: {
    value: number;
    min?: number;
    max?: number | null;
    /** What is counted, one and many: "newer message", "newer messages". */
    words?: { one: string; many: string };
    /** What it is, for screen readers. */
    name?: string;
    onchange: (v: number) => void;
  } = $props();

  const W = 236;
  const H = 36;
  const MID = W / 2;
  /** Pixels between two notches. */
  const PX = 9;

  const lo = $derived(Number.isFinite(Number(min)) ? Number(min) : 0);
  const hi = $derived(max != null && Number.isFinite(Number(max)) ? Number(max) : Infinity);
  const clamp = (v: number) => Math.max(lo, Math.min(hi, v));
  const n = $derived(clamp(Math.round(Number(value) || 0)));

  let step = $state(untrack(() => stepFor(Number(value) || 0)));
  const snap = (v: number) => clamp(Math.round(v / step) * step);

  /** Where the tape is drawn, in the count's units, and where it is heading. */
  let at = $state(untrack(() => lo));
  let target = untrack(() => lo);
  let busy = $state<"drag" | "coast" | null>(null);
  let arriving = $state(true);
  /** Off screen as its tab opened: the first count is not swept to. */
  let instant = false;
  let lastSent = untrack(() => n);
  const moving = () => get(motionEnabled) && document.documentElement.dataset.motion !== "off";

  function emit(v: number) {
    if (v !== lastSent) {
      lastSent = v;
      play("tick");
      onchange(v);
    }
  }

  // ── Following the tape ─────────────────────────────────────────────────────
  let raf = 0;
  let last = 0;
  let vel = 0;
  function run() {
    if (!raf) {
      last = performance.now();
      raf = requestAnimationFrame(frame);
    }
  }
  function frame(now: number) {
    raf = 0;
    const dt = Math.min(48, now - last);
    last = now;
    if (busy === "coast") {
      target += vel * dt;
      vel *= Math.pow(0.93, dt / 16.7);
      if (target <= lo || target >= hi) {
        target = clamp(target);
        vel = 0;
      }
      emit(snap(target));
      at = target;
      if (Math.abs(vel) * 16.7 < step * 0.04) {
        busy = null;
        target = snap(target);
        emit(target);
        // Settled: the notches suit the new count, for the next pull.
        step = stepFor(target);
      }
      raf = requestAnimationFrame(frame);
      return;
    }
    const d = target - at;
    if (Math.abs(d) < step * 0.003) {
      at = target;
      arriving = false;
      winding = false;
      return;
    }
    const was = at;
    at += d * (1 - Math.pow(0.8, dt / 16.7));
    // Gliding in to its count as the tab opens: each notch it passes, a soft detent, rising as it goes.
    if (winding && arriving && Math.floor(was / step) !== Math.floor(at / step)) {
      const k = Math.floor(at / step);
      play("wind", { p: Math.min(1, Math.max(0, (at - lo) / (target - lo || 1))), strong: k % 5 === 0 });
    }
    raf = requestAnimationFrame(frame);
  }
  $effect(() => () => cancelAnimationFrame(raf));

  // The count from outside (undo, a typed value, the tab opening): the tape glides there.
  let root: HTMLDivElement | null = $state(null);
  let shown = $state(false);
  /** Sweeping in where it is seen: the notches it passes are heard. */
  let winding = false;
  $effect(() => {
    const el = root;
    // Below what the window shows as the tab opens: no sweep in, just its count.
    if (el) whenShown(el).then(() => onScreen(el)).then((seen) => {
      instant = !seen;
      winding = seen;
      shown = true;
    });
  });
  $effect(() => {
    const v = n;
    if (!shown) return;
    untrack(() => {
      if (busy) return;
      lastSent = v;
      step = stepFor(v);
      target = v;
      if (!moving() || instant) {
        at = v;
        arriving = false;
        instant = false;
      } else run();
    });
  });

  /** The count shown: while the tape sweeps in, the one under the middle; after, the setting. */
  const showing = $derived(arriving && busy == null ? clamp(Math.round(at / step) * step) : n);
  const unit = $derived(showing === 1 ? words.one : words.many);

  // ── The marks ──────────────────────────────────────────────────────────────
  const marks = $derived.by(() => {
    const span = (MID / PX + 2) * step;
    const out: { v: number; x: number; major: boolean; len: number; near: number }[] = [];
    for (let k = Math.ceil((at - span) / step); k <= Math.floor((at + span) / step); k++) {
      const v = k * step;
      if (v < lo || v > hi) continue;
      const x = MID + ((v - at) / step) * PX;
      const near = Math.exp(-((x - MID) ** 2) / (2 * 13 * 13));
      const major = k % 5 === 0;
      out.push({ v, x, major, len: (major ? 9 : 5) + 7 * near, near });
    }
    return out;
  });

  // ── Pulling it ─────────────────────────────────────────────────────────────
  let tape: HTMLDivElement | null = $state(null);
  let x0 = 0;
  let at0 = 0;
  let scale = 1;
  let samples: [number, number][] = [];
  /** Past an end, the tape gives a little and no more: two notches at most. */
  const give = (d: number) => (d * step * 2) / (d + step * 2);

  function down(e: PointerEvent) {
    if (e.button !== 0 || !tape) return;
    e.preventDefault();
    tape.setPointerCapture(e.pointerId);
    tape.focus({ preventScroll: true });
    const r = tape.getBoundingClientRect();
    scale = W / (r.width || W);
    play("grab");
    busy = "drag";
    arriving = false;
    vel = 0;
    x0 = e.clientX;
    at0 = at;
    samples = [[performance.now(), e.clientX]];
  }
  function move(e: PointerEvent) {
    if (busy !== "drag") return;
    let raw = at0 - (((e.clientX - x0) * scale) / PX) * step;
    if (raw < lo) raw = lo - give(lo - raw);
    if (raw > hi) raw = hi + give(raw - hi);
    at = target = raw;
    const now = performance.now();
    samples.push([now, e.clientX]);
    samples = samples.filter(([t]) => now - t < 120);
    emit(snap(raw));
  }
  function up(e: PointerEvent) {
    if (busy !== "drag") return;
    play("release");
    if (tape?.hasPointerCapture(e.pointerId)) tape.releasePointerCapture(e.pointerId);
    const now = performance.now();
    const recent = samples.filter(([t]) => now - t < 90);
    let v = 0;
    if (recent.length >= 2) {
      const [ta, xa] = recent[0];
      const [tb, xb] = recent[recent.length - 1];
      if (tb > ta) v = -((((xb - xa) * scale) / (tb - ta)) / PX) * step;
    }
    // A flick coasts on; a drag that stopped settles on the nearest notch.
    if (moving() && Math.abs(v) * 16.7 > step * 0.5 && at >= lo && at <= hi) {
      busy = "coast";
      vel = v;
      target = at;
    } else {
      busy = null;
      target = snap(at);
      emit(target);
      step = stepFor(target);
    }
    run();
  }

  /** One notch, or several, from the count as it stands. */
  function nudge(by: number) {
    arriving = false;
    busy = null;
    vel = 0;
    const next = snap(n + by * step);
    emit(next);
    target = next;
    if (moving()) run();
    else at = next;
  }
  function key(e: KeyboardEvent) {
    const by: Record<string, number> = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 5, PageDown: -5 };
    if (e.key in by) nudge(by[e.key]);
    else if (e.key === "Home") nudge((lo - n) / step);
    else if (e.key === "End" && hi < Infinity) nudge((hi - n) / step);
    else return;
    e.preventDefault();
  }
  // The wheel sideways only (a trackpad swipe, or Shift and the wheel): a plain
  // scroll over it is someone scrolling the page.
  let wheelAcc = 0;
  function wheel(e: WheelEvent) {
    const d = e.shiftKey && !e.deltaX ? e.deltaY : Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : 0;
    if (!d) return;
    e.preventDefault();
    wheelAcc += d;
    while (Math.abs(wheelAcc) >= 26) {
      nudge(Math.sign(wheelAcc));
      wheelAcc -= Math.sign(wheelAcc) * 26;
    }
  }

  // - and +, held: again after a moment, then faster and faster.
  let hold = 0;
  function press(by: number, e: PointerEvent) {
    if (e.button !== 0) return;
    nudge(by);
    let gap = 380;
    const again = () => {
      nudge(by);
      gap = Math.max(45, gap * 0.8);
      hold = window.setTimeout(again, gap);
    };
    hold = window.setTimeout(again, gap);
  }
  const letGo = () => clearTimeout(hold);
  $effect(() => () => clearTimeout(hold));

  // ── Typing it ──────────────────────────────────────────────────────────────
  let typing = $state(false);
  let draft = $state("");
  let box: HTMLInputElement | null = $state(null);
  async function type() {
    draft = String(n);
    typing = true;
    await tick();
    box?.select();
  }
  function typed() {
    if (!typing) return;
    typing = false;
    const v = Math.round(Number(String(draft).replace(/[\s,]/g, "")));
    if (!Number.isFinite(v)) return;
    const next = clamp(v);
    arriving = false;
    step = stepFor(next);
    emit(next);
    target = next;
    if (moving()) run();
    else at = next;
  }
  function typingKey(e: KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      typed();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      typing = false;
    }
  }
</script>

<div class="tp" bind:this={root}>
  <div class="tp-top">
    <button type="button" class="tp-btn" aria-label="Less" title="Less (hold to keep going)" disabled={n <= lo}
            onpointerdown={(e) => press(-1, e)} onpointerup={letGo} onpointerleave={letGo} onpointercancel={letGo}
            onkeydown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); nudge(-1); } }}>
      <svg viewBox="0 0 12 12" aria-hidden="true"><line x1="2.5" y1="6" x2="9.5" y2="6" /></svg>
    </button>
    {#if typing}
      <input bind:this={box} bind:value={draft} class="tp-type" inputmode="numeric" spellcheck="false"
             aria-label="{name}, exactly" onkeydown={typingKey} onblur={typed} />
    {:else}
      <button type="button" class="tp-num" onclick={type} title="Click to type a number">
        <b><Odometer value={showing} /></b>
        {#if unit}<span class="tp-unit">{unit}</span>{/if}
      </button>
    {/if}
    <button type="button" class="tp-btn" aria-label="More" title="More (hold to keep going)" disabled={n >= hi}
            onpointerdown={(e) => press(1, e)} onpointerup={letGo} onpointerleave={letGo} onpointercancel={letGo}
            onkeydown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); nudge(1); } }}>
      <svg viewBox="0 0 12 12" aria-hidden="true"><line x1="2.5" y1="6" x2="9.5" y2="6" /><line x1="6" y1="2.5" x2="6" y2="9.5" /></svg>
    </button>
  </div>

  <div class="tp-tape" class:is-dragging={busy === "drag"} bind:this={tape} role="slider" tabindex="0"
       aria-label={name} aria-valuemin={lo} aria-valuemax={hi < Infinity ? hi : undefined} aria-valuenow={n}
       aria-valuetext="{n} {n === 1 ? words.one : words.many}"
       onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up} onkeydown={key} onwheel={wheel}>
    <svg viewBox="0 0 {W} {H}" width={W} height={H} aria-hidden="true">
      {#each marks as m (m.v)}
        <line x1={m.x} x2={m.x} y1="3" y2={3 + m.len} class="tp-mark" class:is-major={m.major}
              style="opacity: {0.35 + 0.65 * m.near}" />
        {#if m.major}
          <text x={m.x} y={H - 4} class="tp-label" style="opacity: {0.45 + 0.55 * m.near}">{m.v}</text>
        {/if}
      {/each}
      <line x1={MID} x2={MID} y1="0" y2="21" class="tp-glow" />
      <line x1={MID} x2={MID} y1="0" y2="21" class="tp-needle" />
    </svg>
  </div>
</div>

<style>
  .tp { display: flex; width: 236px; max-width: 100%; flex-direction: column; gap: 2px; user-select: none; }
  .tp-top { display: flex; align-items: center; gap: 6px; }
  .tp-btn {
    display: grid;
    width: 26px;
    height: 26px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06);
    transition: background-color 0.15s var(--swift), color 0.15s var(--swift), transform 0.3s var(--jelly);
  }
  .tp-btn svg { width: 11px; height: 11px; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; }
  .tp-btn:hover:not(:disabled) { color: var(--color-ink); background: color-mix(in srgb, var(--color-accent) 16%, transparent); }
  .tp-btn:active:not(:disabled) { transform: scale(0.88); }
  .tp-btn:disabled { opacity: 0.35; cursor: default; }
  .tp-num {
    display: flex;
    min-width: 0;
    flex: 1;
    align-items: baseline;
    justify-content: center;
    gap: 5px;
    padding: 2px 6px;
    border-radius: 8px;
    cursor: text;
    transition: background-color 0.15s var(--swift);
  }
  .tp-num:hover { background: rgb(255 255 255 / 0.05); }
  .tp-num b { font-size: 19px; font-weight: 750; letter-spacing: -0.02em; color: var(--color-ink); }
  .tp-unit { overflow: hidden; font-size: 11.5px; color: var(--color-muted); text-overflow: ellipsis; white-space: nowrap; }
  .tp-type {
    min-width: 0;
    flex: 1;
    padding: 3px 8px;
    border-radius: 8px;
    border: 1px solid color-mix(in srgb, var(--color-accent) 60%, transparent);
    background: rgb(0 0 0 / 0.3);
    font-size: 15px;
    font-weight: 700;
    text-align: center;
    color: var(--color-ink);
    outline: none;
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 16%, transparent);
  }
  .tp-tape {
    position: relative;
    /* Laid out on its own: the marks moving every frame stay inside it. */
    contain: layout style;
    border-radius: 10px;
    cursor: grab;
    touch-action: pan-y;
    outline: none;
  }
  .tp-tape.is-dragging { cursor: grabbing; }
  .tp-tape:focus-visible { box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-accent) 40%, transparent); }
  .tp-tape svg {
    display: block;
    width: 100%;
    height: auto;
    overflow: visible;
    /* The tape goes on past both edges; it fades rather than stopping. */
    mask-image: linear-gradient(90deg, transparent, #000 20%, #000 80%, transparent);
  }
  .tp-mark { stroke: rgb(255 255 255 / 0.5); stroke-width: 1; stroke-linecap: round; }
  .tp-mark.is-major { stroke: rgb(255 255 255 / 0.8); stroke-width: 1.5; }
  .tp-label { font-size: 9px; font-weight: 650; fill: var(--color-muted); text-anchor: middle; font-variant-numeric: tabular-nums; }
  .tp-needle { stroke: var(--color-accent); stroke-width: 2; stroke-linecap: round; }
  .tp-glow { stroke: var(--color-accent); stroke-width: 7; stroke-linecap: round; opacity: 0.25; filter: blur(3px); }
</style>
