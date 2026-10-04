<script module lang="ts">
  /** Each dial's gradient needs an id of its own: a page of dials shares one document. */
  let made = 0;
</script>

<script lang="ts">
  /**
   * A number on a dial you drag, instead of in a box, or a range of it with a
   * hand for each end: amounts of time in Settings, and typing speeds.
   *
   * A gauge like a stopwatch's, open at the bottom: the smallest amount at
   * the left of the opening, the largest at the right, and round amounts
   * marked on the rim. The arc is the amount; drag its hands round the dial,
   * press the ring to bring the nearer hand there, or drag the arc between
   * two hands to move the whole range. What the numbers are is the scale's
   * business (dialscale.ts): for time, more of the dial goes to the small
   * amounts, where a second is a big difference, and drags land on round
   * numbers. The middle says it in words ("2 min 30 s"), and a click there
   * types an exact amount instead.
   *
   * The marks round the rim reach out after a hand as it goes past them
   * (lib/pluck.ts), so a drag leaves a little wave behind it and the dial
   * ripples round to its value as it opens. The words in the middle keep
   * their size while it turns: they used to pop smaller and back at every
   * step of a drag, and jump to a smaller size past nine letters, which made
   * the whole dial look as if it was breathing.
   *
   * The dial is as big as the value needs, not as big as the setting allows:
   * a think of 2 to 8 seconds on a dial to two minutes would be a sliver.
   * Pushing a hand all the way to the end makes room for more, up to the
   * setting's own maximum.
   *
   * The hands are real sliders, so the arrow keys move them too.
   */
  import { tick, untrack } from "svelte";
  import { Tween } from "svelte/motion";
  import { quintOut } from "svelte/easing";
  import { motionEnabled } from "../stores";
  import { onScreen, whenShown } from "../cascade";
  import { marksPath, passed, pluck } from "../pluck";
  import { play } from "../uisound";
  import type { DialScale } from "../dialscale";

  let {
    values,
    scale,
    top: base,
    names = ["At least", "At most"],
    zero = "",
    hint = "",
    tone = "",
    onchange,
  }: {
    /** One value, or the two ends of a range, in the scale's unit. */
    values: number[];
    /** What the numbers are: how they sit round the dial, snap and are said. */
    scale: DialScale;
    /** The least the dial should reach, where fitting it to the value would make it too small. */
    top?: number;
    /** What the two hands are, for screen readers and the typed editor. */
    names?: [string, string];
    /** What 0 means where it means something ("Off"). */
    zero?: string;
    /** Said under the value: what happens between the ends of a range, or what a count is of. */
    hint?: string;
    /** A class for the dial's colours ("is-speed"), where it is not the default. */
    tone?: string;
    onchange: (values: number[]) => void;
  } = $props();

  const uid = `td${++made}`;
  const W = 164;
  const C = W / 2;
  const R = 56;
  const H = Math.ceil(C + R * Math.cos(Math.PI / 6) + 24);
  /** Degrees clockwise from twelve: the gauge opens at the bottom, between these. */
  const A0 = -150;
  const A1 = 150;

  const lo = $derived(scale.min);
  const nums = $derived(values.map((v) => (isFinite(Number(v)) ? Number(v) : lo)));
  const range = $derived(nums.length > 1);
  const peakOf = (xs: number[]) => Math.max(0, ...xs);

  /** The dial's far end: as far as its value needs, never past the setting's maximum. */
  let hi = $state(untrack(() => Math.min(scale.max, Math.max(base ?? 0, scale.fit(peakOf(nums))))));
  let dragging = $state<"a" | "b" | "both" | null>(null);
  // Pushed to the end (or typed past it): room for more, once the hand is let go.
  $effect(() => {
    const peak = peakOf(nums);
    if (dragging || hi >= scale.max) return;
    if (peak >= hi * 0.98) hi = Math.max(hi, Math.min(scale.max, scale.fit(peak)));
  });

  // ── Where the hands are ────────────────────────────────────────────────────
  const fr = $derived(nums.map((v) => scale.fracOf(v, lo, hi)));
  // Tweened, so the hands glide where they are set, and sweep in on arrival:
  // quick off the mark with a long, soft finish (quintOut). cubicOut over 0.4s
  // read as a dash and a sudden stop. The first sweep starts as the dial's
  // block drops in with the tab's opening, so the two move together.
  const tA = new Tween(0, { duration: 900, easing: quintOut });
  const tB = new Tween(0, { duration: 900, easing: quintOut });
  let shown = $state(false);
  let swept = false;
  /** Past its sweep in: from then on the marks a hand passes are plucked (not during it, when a page of dials sweeping at once made opening the tab stutter). */
  let plucking = false;
  /** Off screen as its tab opened: the first setting is not swept to. */
  let instant = false;
  /** Sweeping in where it is seen: the marks it passes are heard, softly, though not plucked. */
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
    const a = range ? fr[0] : 0;
    const b = range ? fr[1] : fr[0];
    if (!shown) return;
    const d = !$motionEnabled || instant ? 0 : dragging ? 110 : swept ? 800 : 1100;
    instant = false;
    swept = true;
    tA.set(a, { duration: d });
    tB.set(b, { duration: d });
  });

  const deg = (f: number) => A0 + (A1 - A0) * f;
  const pt = (d: number, r: number) => {
    const a = (d * Math.PI) / 180;
    return { x: C + r * Math.sin(a), y: C - r * Math.cos(a) };
  };
  function arcPath(f0: number, f1: number, r: number): string {
    if (f1 - f0 < 0.003) return "";
    const a = pt(deg(f0), r);
    const b = pt(deg(f1), r);
    return `M ${a.x.toFixed(2)} ${a.y.toFixed(2)} A ${r} ${r} 0 ${deg(f1) - deg(f0) > 180 ? 1 : 0} 1 ${b.x.toFixed(2)} ${b.y.toFixed(2)}`;
  }
  const track = arcPath(0, 1, R);
  const arc = $derived(arcPath(tA.current, tB.current, R));
  const hA = $derived(pt(deg(tA.current), R));
  const hB = $derived(pt(deg(tB.current), R));
  /**
   * The rim's fifty-one marks, each from its inner end `a` to its outer `b`,
   * every fifth a longer one. Drawn as four paths (the short and the long
   * ones, and those of each inside the arc), not as fifty-one elements that
   * each redrew as a hand crossed any of them: a page of dials was hundreds
   * of them, and opening one stuttered.
   */
  const MARKS = Array.from({ length: 51 }, (_, i) => ({
    a: pt(deg(i / 50), R + 9),
    b: pt(deg(i / 50), R + (i % 5 === 0 ? 15 : 12)),
    major: i % 5 === 0,
  }));
  const MINOR = marksPath(MARKS.filter((m) => !m.major));
  const MAJOR = marksPath(MARKS.filter((m) => m.major));
  /** The first and last marks inside the arc: they only change as a hand crosses a mark, not every frame of a sweep. */
  const inFrom = $derived(Math.ceil(tA.current * 50 - 0.05));
  const inTo = $derived(Math.floor(tB.current * 50 + 0.05));
  const inside = $derived(MARKS.slice(Math.max(0, inFrom), Math.max(0, inTo + 1)));
  const inMinor = $derived(marksPath(inside.filter((m) => !m.major)));
  const inMajor = $derived(marksPath(inside.filter((m) => m.major)));
  /** Where a pluck draws its line, over the marks. */
  let plucks: SVGGElement | null = $state(null);
  let wasA = 0;
  let wasB = 0;
  $effect(() => {
    const a = tA.current;
    const b = tB.current;
    untrack(() => {
      if (!plucking) {
        // Winding round to its value as the tab opens: each mark it passes, a soft detent, rising as it goes,
        // quick at first and slower as it settles.
        if (winding) {
          const hear = (from: number, to: number) => {
            for (const k of passed(from, to, 1 / 50)) {
              if (k >= 0 && k <= 50) play("wind", { p: k / 50, strong: MARKS[k].major });
            }
          };
          if (range) hear(wasA, a);
          hear(wasB, b);
        }
        wasA = a;
        wasB = b;
        return;
      }
      const go = (from: number, to: number) => {
        for (const k of passed(from, to, 1 / 50)) {
          if (k >= 0 && k <= 50) {
            pluck(plucks, MARKS[k].a, MARKS[k].b, MARKS[k].major ? 1.5 : 1, MARKS[k].major ? 1.55 : 2.1);
            // The sound of it, rising as the hand goes round: heard with Animations off too.
            play("tick", { p: k / 50, strong: MARKS[k].major });
          }
        }
      };
      if (range) go(wasA, a);
      go(wasB, b);
      wasA = a;
      wasB = b;
    });
  });
  // A mark under a hand would be hidden by it, and read as the hand's own label;
  // one level with the words in the middle, or the line under them, would run into them.
  const clear = (f: number) => {
    const c = Math.cos((deg(f) * Math.PI) / 180);
    return c > 0.3 || c < -0.62;
  };
  const rim = $derived(
    scale.marks(lo, hi).filter((m) => fr.every((f) => Math.abs(f - m.frac) > 0.06) && clear(m.frac)),
  );

  // ── The words in the middle ────────────────────────────────────────────────
  const said = $derived(
    range ? scale.sayRange(nums[0], nums[1]) : zero && nums[0] === 0 ? zero : scale.say(nums[0]),
  );
  /**
   * The words as lines: a range whose ends are in different units ("1 min –
   * 2 min 30 s") is two, the second led by "to"; anything else is one.
   */
  const lines = $derived.by(() => {
    const cut = said.indexOf(" – ");
    return cut > 0 ? [said.slice(0, cut), said.slice(cut + 3)] : [said];
  });

  /**
   * A line wider than the middle (96px, less a margin) is drawn smaller to
   * fit, smoothly, and only as much as it needs. Its width comes from a
   * ResizeObserver, after layout, rather than read while the page is being
   * built, which made the browser lay the page out there and then; and the
   * scale does not change the width it reports, so it never feeds on itself.
   */
  function fit(node: HTMLElement, _text: string) {
    const ro = new ResizeObserver(([e]) => {
      const w = e.borderBoxSize?.[0]?.inlineSize ?? e.contentRect.width;
      node.style.setProperty("--fit", w > 88 ? String(88 / w) : "1");
    });
    ro.observe(node);
    return { destroy: () => ro.disconnect() };
  }
  /** The amount as stored, where the words do not already say it: "8 s" is 8000 ms. */
  const raw = $derived.by(() => {
    const plain = range ? `${nums[0]}–${nums[1]} ${scale.unit}` : `${nums[0]} ${scale.unit}`;
    return said.replace(/[–\s]/g, "") === plain.replace(/[–\s]/g, "") ? "" : plain;
  });

  // ── Dragging ───────────────────────────────────────────────────────────────
  let svg: SVGSVGElement | null = $state(null);
  let grabV = 0;
  let grabbed: number[] = [];

  /** How far round the dial the pointer is; in the opening, the end it was nearer. */
  function fracAt(e: PointerEvent, prev: number): number {
    const r = svg!.getBoundingClientRect();
    const k = W / r.width;
    const dx = (e.clientX - r.left) * k - C;
    const dy = (e.clientY - r.top) * k - C;
    const d = (Math.atan2(dx, -dy) * 180) / Math.PI;
    if (d > A1 || d < A0) return prev >= 0.5 ? 1 : 0;
    return (d - A0) / (A1 - A0);
  }
  const tidy = (v: number, cap = hi) => scale.snap(v, lo, cap);

  function put(next: number[]) {
    if (next.some((v, i) => v !== nums[i])) onchange(next);
  }
  /** One hand to an amount, never past the other one. */
  function setHand(i: number, v: number, cap = hi) {
    let x = tidy(v, cap);
    if (range) x = i === 0 ? Math.min(x, nums[1]) : Math.max(x, nums[0]);
    put(nums.map((n, j) => (j === i ? x : n)));
  }

  function grab(what: "a" | "b" | "both", e: PointerEvent) {
    if (!svg || e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    svg.setPointerCapture(e.pointerId);
    if (!dragging) play("grab");
    dragging = what;
    grabV = scale.valueAt(fracAt(e, 0.5), lo, hi);
    grabbed = [...nums];
  }
  /** A press on the ring: the nearer hand jumps there, and keeps following the pointer. */
  function pressRing(e: PointerEvent) {
    if (!svg || e.button !== 0) return;
    const f = fracAt(e, range ? fr[1] : fr[0]);
    const which = range && Math.abs(f - fr[0]) < Math.abs(f - fr[1]) ? "a" : "b";
    setHand(which === "a" ? 0 : range ? 1 : 0, scale.valueAt(f, lo, hi));
    grab(which, e);
  }
  function move(e: PointerEvent) {
    if (!dragging) return;
    if (dragging === "both") {
      const dv = scale.valueAt(fracAt(e, scale.fracOf(grabV, lo, hi)), lo, hi) - grabV;
      const shift = Math.max(lo - grabbed[0], Math.min(hi - grabbed[1], dv));
      put([tidy(grabbed[0] + shift), tidy(grabbed[1] + shift)]);
      return;
    }
    const i = dragging === "a" ? 0 : range ? 1 : 0;
    setHand(i, scale.valueAt(fracAt(e, fr[i]), lo, hi));
  }
  function release(e: PointerEvent) {
    if (!dragging) return;
    dragging = null;
    play("release");
    svg?.releasePointerCapture?.(e.pointerId);
  }
  function key(i: number, e: KeyboardEvent) {
    const v = nums[i];
    const st = scale.step(v);
    const by: Record<string, number> = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 10, PageDown: -10 };
    let next: number;
    if (e.key === "Home") next = lo;
    else if (e.key === "End") next = hi;
    else if (e.key in by) next = v + by[e.key] * st;
    else return;
    e.preventDefault();
    setHand(i, next, Math.min(scale.max, e.key === "End" ? hi : Math.max(hi, next)));
  }

  /** Pointer presses on the ring and the arc, which are shortcuts beside the sliders rather than controls. */
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

  // ── Typing an exact amount ─────────────────────────────────────────────────
  let editing = $state(false);
  let draft = $state<string[]>([]);
  let form: HTMLFormElement | null = $state(null);
  async function openEditor() {
    draft = nums.map(String);
    editing = true;
    await tick();
    form?.querySelector("input")?.select();
  }
  function applyEditor() {
    const typed = draft.map((d, i) => scale.read(String(d)) ?? nums[i]);
    let next = typed.map((v) => scale.exact(Math.max(lo, Math.min(scale.max, v))));
    if (range && next[0] > next[1]) next = [next[1], next[0]];
    editing = false;
    put(next);
  }
  function editorKey(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      editing = false;
    }
  }
  function editorBlur(e: FocusEvent) {
    if (form && !form.contains(e.relatedTarget as Node)) applyEditor();
  }
</script>

<div class="td {tone}" class:is-dragging={!!dragging} style="--w: {W}px; --h: {H}px">
  <svg bind:this={svg} viewBox="0 0 {W} {H}" width={W} height={H} role="group"
       aria-label={range ? `${names[0]} ${scale.say(nums[0])}, ${names[1]} ${scale.say(nums[1])}` : scale.say(nums[0])}
       onpointermove={move} onpointerup={release} onpointercancel={release}>
    <defs>
      <linearGradient id="{uid}-arc" gradientUnits="userSpaceOnUse" x1={range ? hA.x : pt(A0, R).x} y1={range ? hA.y : pt(A0, R).y}
                      x2={hB.x} y2={hB.y}>
        <stop offset="0" stop-color="var(--td-from)" />
        <stop offset="1" stop-color="var(--td-to)" />
      </linearGradient>
      <radialGradient id="td-face" cx="0.5" cy="0.4" r="0.7">
        <stop offset="0" stop-color="rgb(255 255 255 / 0.065)" />
        <stop offset="1" stop-color="rgb(255 255 255 / 0.01)" />
      </radialGradient>
    </defs>

    <!-- The face, its minute marks, and the round amounts on the rim. -->
    <circle cx={C} cy={C} r={R + 20} fill="url(#td-face)" class="td-face" />
    <path d={MINOR} class="td-tick" />
    <path d={MAJOR} class="td-tick is-major" />
    {#if inMinor}<path d={inMinor} class="td-tick is-in" />{/if}
    {#if inMajor}<path d={inMajor} class="td-tick is-major is-in" />{/if}
    <g bind:this={plucks} class="td-plucks"></g>
    {#each rim as m (m.v)}
      {@const p = pt(deg(m.frac), R - 15)}
      <text x={p.x} y={p.y} class="td-mark">{m.text}</text>
    {/each}
    <text x={pt(A0, R).x - 2} y={pt(A0, R).y + 17} class="td-end">{scale.short(lo)}</text>
    <text x={pt(A1, R).x + 2} y={pt(A1, R).y + 17} class="td-end">{scale.short(hi)}</text>

    <!-- The ring, wide and invisible under the arc: a press brings the nearer hand there. -->
    <path d={track} class="td-track" />
    <path d={track} class="td-hit" use:press={pressRing} />

    {#if arc}
      <!-- The glow: two wide, faint strokes rather than a blur, which had to be
           worked out again every frame the arc moved. -->
      <path d={arc} class="td-glow is-wide" stroke="url(#{uid}-arc)" />
      <path d={arc} class="td-glow" stroke="url(#{uid}-arc)" />
      <path d={arc} class="td-arc" class:is-movable={range} stroke="url(#{uid}-arc)"
            use:press={(e) => (range ? grab("both", e) : pressRing(e))}>
        {#if range}<title>Drag to move the whole range</title>{/if}
      </path>
    {/if}

    {#if range}
      <g class="td-hand is-a" class:is-grabbed={dragging === "a"} transform="translate({hA.x} {hA.y})"
         role="slider" tabindex="0" aria-label={names[0]} aria-valuemin={lo} aria-valuemax={hi}
         aria-valuenow={nums[0]} aria-valuetext={scale.say(nums[0])}
         onpointerdown={(e) => grab("a", e)} onkeydown={(e) => key(0, e)}>
        <circle r="9.5" class="td-knob" />
        <circle r="3" class="td-dot" />
      </g>
    {/if}
    <g class="td-hand is-b" class:is-grabbed={dragging === "b"} transform="translate({hB.x} {hB.y})"
       role="slider" tabindex="0" aria-label={range ? names[1] : "Amount"} aria-valuemin={lo} aria-valuemax={hi}
       aria-valuenow={nums[range ? 1 : 0]} aria-valuetext={scale.say(nums[range ? 1 : 0])}
       onpointerdown={(e) => grab("b", e)} onkeydown={(e) => key(range ? 1 : 0, e)}>
      <circle r="9.5" class="td-knob" />
      <circle r="3" class="td-dot" />
    </g>
  </svg>

  <!-- The middle: the time in words. A click types an exact amount. -->
  <button type="button" class="td-mid" onclick={openEditor} title="Click to type an exact amount">
    <b class="td-big" class:is-two={lines.length > 1}>
      <span class="td-line" use:fit={lines[0]}>{lines[0]}</span>
      {#if lines.length > 1}<span class="td-line" use:fit={lines[1]}><i>to</i> {lines[1]}</span>{/if}
    </b>
    {#if hint}<span class="td-sub">{hint}</span>{:else if raw}<span class="td-sub">{raw}</span>{/if}
  </button>

  {#if editing}
    <form class="td-edit" bind:this={form} onsubmit={(e) => { e.preventDefault(); applyEditor(); }}
          onfocusout={editorBlur}>
      {#each draft as _, i (i)}
        <label>
          <span>{range ? names[i] : "Exactly"}</span>
          <input type="text" inputmode="decimal" bind:value={draft[i]} onkeydown={editorKey} aria-label="{range ? names[i] : 'Amount'} in {scale.unit}" />
          <i>{scale.unit}</i>
        </label>
      {/each}
      <button type="submit">Set</button>
      {#if scale.example}<p class="td-eg">Like {scale.example}</p>{/if}
    </form>
  {/if}
</div>

<style>
  .td {
    --td-from: var(--color-accent-2);
    --td-to: var(--color-accent);
    position: relative;
    width: var(--w);
    height: var(--h);
    flex-shrink: 0;
    /* A fixed size, laid out on its own: a sweep redrawing the dial every
       frame used to set the whole page laying itself out again with it. */
    contain: layout style;
    touch-action: none;
    user-select: none;
  }
  /* A speed: cool when slow, hot when fast, like a speedometer. */
  .td.is-speed { --td-from: #4ecdc4; --td-to: #ff8a5c; }
  .td svg { display: block; overflow: visible; }
  .td-face { stroke: rgb(255 255 255 / 0.05); stroke-width: 1; }
  .td-tick {
    fill: none;
    stroke: rgb(255 255 255 / 0.13);
    stroke-width: 1;
    stroke-linecap: round;
  }
  .td-tick.is-major { stroke: rgb(255 255 255 / 0.28); stroke-width: 1.5; }
  .td-tick.is-in { stroke: color-mix(in srgb, var(--td-to) 70%, white); }
  .td-mark { font-size: 8.5px; font-weight: 650; fill: var(--color-faint); text-anchor: middle; dominant-baseline: central; }
  .td-end { font-size: 9px; font-weight: 650; fill: var(--color-muted); text-anchor: middle; dominant-baseline: central; }
  .td-track { fill: none; stroke: rgb(255 255 255 / 0.07); stroke-width: 10; stroke-linecap: round; pointer-events: none; }
  .td-hit { fill: none; stroke: transparent; stroke-width: 28; stroke-linecap: round; cursor: pointer; }
  .td-glow { fill: none; stroke-width: 15; stroke-linecap: round; opacity: 0.16; pointer-events: none; }
  .td-glow.is-wide { stroke-width: 23; opacity: 0.07; }
  .td-arc { fill: none; stroke-width: 10; stroke-linecap: round; cursor: pointer; transition: stroke-width 0.25s var(--spring); }
  .td-arc.is-movable { cursor: grab; }
  .td-arc:hover { stroke-width: 12; }
  .td.is-dragging .td-arc.is-movable { cursor: grabbing; }

  .td-hand { cursor: grab; outline: none; }
  .td.is-dragging .td-hand { cursor: grabbing; }
  .td-knob {
    fill: rgb(20 22 34);
    stroke-width: 2.5;
    transition: transform 0.35s var(--spring), stroke-width 0.2s ease;
    transform-box: fill-box;
    transform-origin: center;
  }
  .td-hand.is-a .td-knob { stroke: var(--td-from); }
  .td-hand.is-b .td-knob { stroke: var(--td-to); }
  .td-dot { pointer-events: none; }
  .td-hand.is-a .td-dot { fill: var(--td-from); }
  .td-hand.is-b .td-dot { fill: var(--td-to); }
  .td-hand:hover .td-knob, .td-hand:focus-visible .td-knob { transform: scale(1.14); }
  .td-hand.is-grabbed .td-knob { transform: scale(1.25); stroke-width: 3; }
  .td-hand:focus-visible .td-knob { stroke-width: 3.5; }

  .td-mid {
    position: absolute;
    left: 50%;
    top: calc(var(--w) / 2);
    display: flex;
    width: 96px;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    padding: 4px 2px;
    border-radius: 12px;
    transform: translate(-50%, -50%);
    text-align: center;
    transition: background-color 0.18s var(--swift);
  }
  .td-mid:hover { background: rgb(255 255 255 / 0.05); }
  .td-mid:focus-visible { outline: none; box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-accent) 40%, transparent); }
  .td-big {
    display: flex;
    max-width: 100%;
    flex-direction: column;
    align-items: center;
    font-size: 15px;
    font-weight: 750;
    line-height: 1.15;
    letter-spacing: -0.02em;
    color: var(--color-ink);
    font-variant-numeric: tabular-nums;
  }
  /* Two lines, a little smaller, so both fit inside the ring. */
  .td-big.is-two { font-size: 13px; }
  .td-line {
    display: inline-block;
    white-space: nowrap;
    transform: scale(var(--fit, 1));
    transition: transform 0.25s var(--swift);
  }
  .td-line i { font-style: normal; font-size: 0.8em; font-weight: 600; color: var(--color-faint); }
  .td-sub { font-size: 9.5px; line-height: 1.2; color: var(--color-faint); font-variant-numeric: tabular-nums; }

  .td-edit {
    position: absolute;
    left: 50%;
    top: calc(var(--w) / 2);
    z-index: 30;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 9px;
    border-radius: 12px;
    border: 1px solid var(--color-edge);
    background: var(--color-surface);
    box-shadow: 0 18px 40px -16px rgb(0 0 0 / 0.7);
    transform: translate(-50%, -50%);
    animation: td-in 0.16s var(--swift) both;
  }
  @keyframes td-in { from { opacity: 0; transform: translate(-50%, -50%) scale(0.94); } }
  .td-edit label { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--color-muted); }
  .td-edit label span { width: 52px; }
  .td-edit input {
    width: 76px;
    padding: 4px 7px;
    border-radius: 7px;
    border: 1px solid var(--color-edge);
    background: rgb(0 0 0 / 0.25);
    font-family: ui-monospace, monospace;
    font-size: 12px;
    color: var(--color-ink);
    text-align: right;
    outline: none;
  }
  .td-edit input:focus { border-color: color-mix(in srgb, var(--color-accent) 60%, transparent); }
  .td-edit i { font-style: normal; font-size: 10.5px; color: var(--color-faint); }
  .td-edit button {
    padding: 4px 8px;
    border-radius: 7px;
    font-size: 11.5px;
    font-weight: 650;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .td-edit button:hover { background: color-mix(in srgb, var(--color-accent) 22%, transparent); }
  .td-eg { font-size: 10px; color: var(--color-faint); text-align: center; }

  :global(:root[data-motion="off"]) .td-edit { animation: none; }
  :global(:root[data-motion="off"]) .td-line { transition: none; }
  :global(:root[data-motion="off"]) .td-knob { transition: none; }
</style>
