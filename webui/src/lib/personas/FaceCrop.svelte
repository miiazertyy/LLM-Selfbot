<script lang="ts">
  /**
   * Choosing the part of a picture a profile's face shows. The picture sits
   * behind a round window in the profile's colour: drag it to move it, and
   * zoom with the wheel, the slider, a pinch or the + and - keys, with the
   * face as it will look beside it, large and small.
   *
   * The square kept is held in the picture's own pixels (its middle and its
   * side), so the stage, the two faces and the cut all read the same numbers.
   * Pulled past an edge it gives a little and springs back. "Use this" cuts
   * that square out at 512px on a canvas, here, and hands it on as a file; the
   * server keeps it at 256px (app/utils/personas.py set_avatar).
   *
   * A picture the browser cannot open (a HEIC on some machines) calls `onfail`,
   * and the page sends it as it is.
   */
  import { onDestroy, onMount } from "svelte";
  import { play } from "../uisound";
  import Button from "../components/Button.svelte";
  import Icon from "../components/Icon.svelte";

  let { src, color = "var(--color-accent)", busy = false, onuse, onback, onfail }: {
    src: string;
    color?: string;
    busy?: boolean;
    onuse: (file: File) => void;
    onback: () => void;
    onfail?: () => void;
  } = $props();

  /** The round window's share of the stage, and how far in it goes. */
  const WINDOW = 0.84;
  const MAX_ZOOM = 5;
  /** How big the cut is, in px. */
  const OUT = 512;
  /** How much of a pull past the edge shows before it springs back. */
  const GIVE = 0.3;

  let stage = $state(300);
  let w = $state(0);
  let h = $state(0);
  /** The square kept, in the picture's pixels: its middle and its side. */
  let cx = $state(0);
  let cy = $state(0);
  let side = $state(0);
  /** A pull past the edge, in the picture's pixels, shown with some give. */
  let pullX = $state(0);
  let pullY = $state(0);
  let dragging = $state(false);
  /** Zoomed by the wheel or a key: a short ease rather than the spring. */
  let quick = $state(false);
  let ready = $state(false);
  let box: HTMLDivElement | null = $state(null);
  let picture: HTMLImageElement | null = null;

  const shortest = $derived(Math.min(w, h) || 1);
  const zoom = $derived(side ? shortest / side : 1);
  const win = $derived(stage * WINDOW);
  /** Screen pixels to one of the picture's, on the stage. */
  const k = $derived(side ? win / side : 1);

  const clampSide = (s: number) => Math.max(shortest / MAX_ZOOM, Math.min(shortest, s));
  const clampX = (x: number, s = side) => Math.max(s / 2, Math.min(w - s / 2, x));
  const clampY = (y: number, s = side) => Math.max(s / 2, Math.min(h - s / 2, y));

  /** The picture placed so the kept square fills a box `size` across, round its middle. */
  function place(size: number, fill: number) {
    const sc = fill / (side || 1);
    const x = size / 2 - (cx + pullX * GIVE) * sc;
    const y = size / 2 - (cy + pullY * GIVE) * sc;
    return `width:${w}px;height:${h}px;transform:translate(${x}px, ${y}px) scale(${sc})`;
  }

  /** Where it starts: as much of it as fits, a little above the middle on a tall one, where a face usually is. */
  function start() {
    side = shortest;
    cx = w / 2;
    cy = h > w ? side / 2 + (h - side) * 0.22 : h / 2;
    pullX = pullY = 0;
  }

  onMount(() => {
    const im = new Image();
    im.decoding = "async";
    im.onload = () => {
      picture = im;
      w = im.naturalWidth;
      h = im.naturalHeight;
      if (!w || !h) return onfail?.();
      start();
      ready = true;
    };
    im.onerror = () => onfail?.();
    im.src = src;
  });

  // ── Zooming ─────────────────────────────────────────────────────────────────
  /** A tick for each quarter step of zoom, a note higher as it goes in. */
  let lastNotch = 0;
  function notch() {
    const n = Math.round(zoom * 4);
    if (n !== lastNotch) {
      play("tick", { level: 0.28, p: (zoom - 1) / (MAX_ZOOM - 1) });
      lastNotch = n;
    }
  }
  /** Zoom to a side, keeping the point under (px, py) on the stage where it is. */
  function zoomTo(nextSide: number, px = stage / 2, py = stage / 2) {
    if (!side) return;
    const ix = cx + (px - stage / 2) / k;
    const iy = cy + (py - stage / 2) / k;
    const s = clampSide(nextSide);
    const k2 = win / s;
    side = s;
    cx = clampX(ix - (px - stage / 2) / k2, s);
    cy = clampY(iy - (py - stage / 2) / k2, s);
    notch();
  }
  let quickTimer = 0;
  function eased() {
    quick = true;
    clearTimeout(quickTimer);
    quickTimer = window.setTimeout(() => (quick = false), 160);
  }
  function onWheel(e: WheelEvent) {
    if (!ready) return;
    e.preventDefault();
    const r = box!.getBoundingClientRect();
    eased();
    zoomTo(side * Math.exp(e.deltaY * 0.0016), e.clientX - r.left, e.clientY - r.top);
  }
  onMount(() => {
    // Not passive: the page must not scroll under it.
    const node = box;
    node?.addEventListener("wheel", onWheel, { passive: false });
    return () => node?.removeEventListener("wheel", onWheel);
  });
  onDestroy(() => clearTimeout(quickTimer));

  // ── Moving it, with a finger or two ─────────────────────────────────────────
  const pointers = new Map<number, { x: number; y: number }>();
  let from = { x: 0, y: 0, cx: 0, cy: 0 };
  let pinch = { d: 0, side: 0 };
  function onDown(e: PointerEvent) {
    if (!ready) return;
    box?.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 1) {
      from = { x: e.clientX, y: e.clientY, cx, cy };
      dragging = true;
      play("grab", { level: 0.5 });
    } else if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, side };
    }
  }
  function onMove(e: PointerEvent) {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size >= 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      const r = box!.getBoundingClientRect();
      zoomTo(pinch.side * (pinch.d / d), (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top);
      return;
    }
    const rawX = from.cx - (e.clientX - from.x) / k;
    const rawY = from.cy - (e.clientY - from.y) / k;
    cx = clampX(rawX);
    cy = clampY(rawY);
    pullX = rawX - cx;
    pullY = rawY - cy;
  }
  function onUp(e: PointerEvent) {
    if (!pointers.delete(e.pointerId)) return;
    if (pointers.size === 1) {
      // One finger left of a pinch: it carries on moving from where it is now.
      const [p] = [...pointers.values()];
      from = { x: p.x, y: p.y, cx, cy };
      return;
    }
    if (pointers.size) return;
    dragging = false;
    const pulled = Math.abs(pullX) + Math.abs(pullY) > 1;
    pullX = pullY = 0;
    // Let go: a soft release, and past the edge a settle as it springs back.
    play(pulled ? "settle" : "release", { level: 0.5 });
  }

  // ── The keyboard ────────────────────────────────────────────────────────────
  function onKey(e: KeyboardEvent) {
    if (!ready) return;
    const step = side * (e.shiftKey ? 0.12 : 0.03);
    const moves: Record<string, [number, number]> = {
      ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step],
    };
    if (e.key in moves) {
      e.preventDefault();
      const [dx, dy] = moves[e.key];
      cx = clampX(cx + dx);
      cy = clampY(cy + dy);
      play("tick", { level: 0.22 });
    } else if (e.key === "+" || e.key === "=") {
      e.preventDefault();
      eased();
      zoomTo(side / 1.15);
    } else if (e.key === "-" || e.key === "_") {
      e.preventDefault();
      eased();
      zoomTo(side * 1.15);
    } else if (e.key === "0") {
      e.preventDefault();
      reset();
    }
  }

  function reset() {
    play("undo", { level: 0.5 });
    start();
    lastNotch = 4;
  }

  /** The kept square, cut out at 512px. */
  async function use() {
    if (!picture || !side) return;
    const c = document.createElement("canvas");
    c.width = c.height = OUT;
    const g = c.getContext("2d");
    if (!g) return onfail?.();
    g.imageSmoothingEnabled = true;
    g.imageSmoothingQuality = "high";
    g.drawImage(picture, cx - side / 2, cy - side / 2, side, side, 0, 0, OUT, OUT);
    const blob = await new Promise<Blob | null>((r) => c.toBlob(r, "image/jpeg", 0.92));
    if (!blob) return onfail?.();
    onuse(new File([blob], "face.jpg", { type: "image/jpeg" }));
  }

  const fill = $derived(`${Math.round(((zoom - 1) / (MAX_ZOOM - 1)) * 100)}%`);
</script>

<div class="fc" style="--fc: {color}">
  <div class="fc-main">
    <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
    <div class="fc-stage" class:is-ready={ready} class:is-drag={dragging} class:is-quick={quick}
         bind:this={box} bind:clientWidth={stage}
         role="application" aria-roledescription="crop" tabindex="0"
         aria-label="The part of the picture its face shows. Drag or use the arrow keys to move it, scroll or + and - to zoom."
         onpointerdown={onDown} onpointermove={onMove} onpointerup={onUp} onpointercancel={onUp}
         onkeydown={onKey}>
      {#if ready}
        <img class="fc-pic" {src} alt="" draggable="false" style={place(stage, win)} />
      {/if}
      <!-- The round window: the rest dimmed, a ring in its colour, and thirds while it moves. -->
      <span class="fc-window" aria-hidden="true">
        <span class="fc-thirds"></span>
      </span>
      {#if !ready}<span class="fc-wait" aria-hidden="true"></span>{/if}
    </div>

    <div class="fc-side">
      <!-- As it will look: on its card, and small in a list. -->
      <span class="fc-face is-big" aria-hidden="true">
        {#if ready}<img {src} alt="" style={place(88, 88)} />{/if}
      </span>
      <span class="fc-face is-small" aria-hidden="true">
        {#if ready}<img {src} alt="" style={place(34, 34)} />{/if}
      </span>
      <span class="fc-side-note">How it shows</span>
    </div>
  </div>

  <div class="fc-zoom">
    <button type="button" class="fc-z" onclick={() => { eased(); zoomTo(side * 1.25); }} disabled={!ready || zoom <= 1.001}
            aria-label="Zoom out"><Icon name="minus" size={13} /></button>
    <input type="range" class="slider" min="1" max={MAX_ZOOM} step="0.01" value={zoom} style="--fill: {fill}"
           aria-label="Zoom" disabled={!ready}
           oninput={(e) => zoomTo(shortest / parseFloat((e.target as HTMLInputElement).value))} />
    <button type="button" class="fc-z" onclick={() => { eased(); zoomTo(side / 1.25); }} disabled={!ready || zoom >= MAX_ZOOM - 0.001}
            aria-label="Zoom in"><Icon name="plus" size={13} /></button>
    <button type="button" class="fc-z" onclick={reset} disabled={!ready} title="Start again" aria-label="Start again">
      <Icon name="refresh" size={13} />
    </button>
  </div>

  <p class="fc-hint">Drag to move it. Scroll or slide to zoom.</p>

  <div class="fc-actions">
    <Button kind="ghost" size="sm" onclick={onback}><Icon name="chevron" size={11} class="fc-back" /> Back</Button>
    <Button size="sm" onclick={use} loading={busy} disabled={!ready}>Use this</Button>
  </div>
</div>

<style>
  .fc { display: flex; flex-direction: column; gap: 12px; animation: fc-in 0.42s var(--jelly) both; }
  @keyframes fc-in { from { opacity: 0; transform: scale(0.96) translateY(6px); } }
  .fc-main { display: flex; align-items: center; justify-content: center; gap: 22px; }

  /* The stage: the picture, and the window over it. */
  .fc-stage {
    position: relative;
    width: min(300px, 100%);
    aspect-ratio: 1;
    flex-shrink: 1;
    overflow: hidden;
    border-radius: 22px;
    background:
      repeating-conic-gradient(rgb(255 255 255 / 0.035) 0 25%, transparent 0 50%) 0 0 / 18px 18px,
      rgb(0 0 0 / 0.35);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    cursor: grab;
    touch-action: none;
    user-select: none;
    outline: none;
  }
  .fc-stage.is-drag { cursor: grabbing; }
  .fc-stage:focus-visible { box-shadow: inset 0 0 0 2px var(--fc); }
  .fc-pic {
    position: absolute;
    left: 0;
    top: 0;
    max-width: none;
    transform-origin: 0 0;
    pointer-events: none;
    animation: fc-pic-in 0.5s ease both;
    transition: transform 0.5s var(--jelly);
  }
  @keyframes fc-pic-in { from { opacity: 0; } }
  .fc-stage.is-drag .fc-pic { transition: none; }
  .fc-stage.is-quick .fc-pic { transition: transform 0.14s ease-out; }

  .fc-window {
    position: absolute;
    inset: 8%;
    border-radius: 999px;
    pointer-events: none;
    box-shadow:
      0 0 0 9999px rgb(6 6 14 / 0.62),
      0 0 0 2px var(--fc),
      0 0 22px 2px color-mix(in srgb, var(--fc) 45%, transparent);
    transition: box-shadow 0.25s ease;
  }
  .fc-stage.is-drag .fc-window {
    box-shadow:
      0 0 0 9999px rgb(6 6 14 / 0.5),
      0 0 0 2.5px var(--fc),
      0 0 30px 4px color-mix(in srgb, var(--fc) 60%, transparent);
  }
  /* Thirds, to line a face up by, only while it moves. */
  .fc-thirds {
    position: absolute;
    inset: 0;
    border-radius: inherit;
    opacity: 0;
    background:
      linear-gradient(90deg, transparent calc(33.33% - 0.5px), rgb(255 255 255 / 0.35) calc(33.33% - 0.5px) calc(33.33% + 0.5px),
        transparent calc(33.33% + 0.5px) calc(66.66% - 0.5px), rgb(255 255 255 / 0.35) calc(66.66% - 0.5px) calc(66.66% + 0.5px),
        transparent calc(66.66% + 0.5px)),
      linear-gradient(180deg, transparent calc(33.33% - 0.5px), rgb(255 255 255 / 0.35) calc(33.33% - 0.5px) calc(33.33% + 0.5px),
        transparent calc(33.33% + 0.5px) calc(66.66% - 0.5px), rgb(255 255 255 / 0.35) calc(66.66% - 0.5px) calc(66.66% + 0.5px),
        transparent calc(66.66% + 0.5px));
    transition: opacity 0.25s ease;
  }
  .fc-stage.is-drag .fc-thirds { opacity: 1; }
  .fc-wait {
    position: absolute;
    left: 50%;
    top: 50%;
    width: 22px;
    height: 22px;
    margin: -11px 0 0 -11px;
    border-radius: 999px;
    border: 2px solid color-mix(in srgb, var(--fc) 30%, transparent);
    border-top-color: var(--fc);
    animation: fc-spin 0.8s linear infinite;
  }
  @keyframes fc-spin { to { transform: rotate(360deg); } }

  /* The face as it will be, in a ring of its colour. */
  .fc-side { display: flex; flex-direction: column; align-items: center; gap: 12px; }
  .fc-face {
    position: relative;
    display: block;
    overflow: hidden;
    border-radius: 999px;
    background: rgb(0 0 0 / 0.3);
    box-shadow: 0 0 0 2px var(--fc), 0 0 0 5px color-mix(in srgb, var(--fc) 18%, transparent),
                0 12px 26px -12px color-mix(in srgb, var(--fc) 80%, transparent);
  }
  .fc-face.is-big { width: 88px; height: 88px; }
  .fc-face.is-small { width: 34px; height: 34px; box-shadow: 0 0 0 1.5px var(--fc); }
  .fc-face img {
    position: absolute;
    left: 0;
    top: 0;
    max-width: none;
    transform-origin: 0 0;
    transition: transform 0.5s var(--jelly);
  }
  .fc-stage.is-drag ~ .fc-side .fc-face img { transition: none; }
  .fc-side-note { font-size: 11px; color: var(--color-faint); }

  .fc-zoom {
    --color-accent: var(--fc);
    --color-accent-2: color-mix(in srgb, var(--fc) 55%, #fff);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .fc-zoom .slider { flex: 1; min-width: 0; }
  .fc-z {
    display: grid;
    width: 30px;
    height: 30px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 10px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 85%, transparent);
    transition: color 0.15s ease, background-color 0.15s ease, transform 0.3s var(--jelly);
  }
  .fc-z:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.1); }
  .fc-z:active:not(:disabled) { transform: scale(0.9); }
  .fc-z:disabled { opacity: 0.4; }
  .fc-hint { font-size: 12px; color: var(--color-muted); text-align: center; }
  .fc-actions { display: flex; justify-content: flex-end; gap: 8px; }
  .fc-actions :global(.fc-back) { transform: rotate(180deg); }

  @media (max-width: 460px) {
    .fc-main { flex-direction: column; gap: 14px; }
    .fc-side { flex-direction: row; }
  }

  :global(:root[data-motion="off"]) .fc,
  :global(:root[data-motion="off"]) .fc-pic,
  :global(:root[data-motion="off"]) .fc-wait { animation: none; }
  :global(:root[data-motion="off"]) .fc-pic,
  :global(:root[data-motion="off"]) .fc-face img,
  :global(:root[data-motion="off"]) .fc-window,
  :global(:root[data-motion="off"]) .fc-thirds,
  :global(:root[data-motion="off"]) .fc-z { transition: none; }
</style>
