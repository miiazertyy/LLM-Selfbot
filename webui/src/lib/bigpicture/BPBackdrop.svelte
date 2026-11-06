<script lang="ts">
  /**
   * The room Big Picture plays in, which belongs to whoever is on stage.
   *
   * A moving background drawn by the graphics card (sky.ts): light flowing and
   * folding across a dark room, in the colours of the person on stage (read
   * from their picture, palette.ts) and moving the way they do (their look,
   * looks.ts). Each person always brings the same colours and the same kind of
   * weather; each scene has its own. When the stage changes, the room does not
   * cut: its colours and its movement melt into the next over a second or two.
   * It quickens while a reply is written and typed, and when one goes out a
   * ring of light spreads from the stage.
   *
   * A dark room first, always: every panel in front of it is glass and every
   * accent on them glows, and neither reads on a pale ground. Over the light, a
   * vignette that pulls the eye to the middle.
   *
   * Where WebGL is not to be had, or the graphics card takes it back, the old
   * room stands in: blurred colour drifting in CSS, in the same colours.
   * Motion follows the app's own switch, not Windows' animation setting (see
   * stores.ts): with it off the room is one still frame. The light behind the
   * stage drifts to whatever has the focus, slowly, like everything else here.
   */
  import { onDestroy, onMount } from "svelte";
  import { get } from "svelte/store";
  import { fade } from "svelte/transition";
  import { motionEnabled } from "../stores";
  import { Sky } from "./sky";
  import { LOOKS, type LookName } from "./looks";
  import { loadPalette, paletteFromSeed, type RGB } from "./palette";

  let {
    art = "",
    seed = "room",
    look = "silk",
    energy = 0.2,
    pulse = 0,
    palette = null,
    focus = 0.5,
    focusY = 0.42,
    oncolours,
  }: {
    /** A picture to take the colours from: whoever is on stage. */
    art?: string;
    /** Who or what the room is for: its colours come from this when no picture gives any. */
    seed?: string;
    look?: LookName;
    /** 0 calm, 1 lively. */
    energy?: number;
    /** Counts up; each step sends a ring of light out from the stage. */
    pulse?: number;
    /** Colours given outright (the theme's, the warning ones) instead of from a picture. */
    palette?: RGB[] | null;
    /** Where across the screen the light gathers, 0 to 1. */
    focus?: number;
    /** And where down it, 0 at the top. */
    focusY?: number;
    /** The colours it has gone to: the view takes its accent from them. */
    oncolours?: (c: RGB[]) => void;
  } = $props();

  let canvas: HTMLCanvasElement | null = $state(null);
  /** The room: drawn in a worker where the browser allows it, else here. The same few calls either way. */
  type SkyLike = Pick<Sky, "set" | "pulse" | "pointer" | "setStill" | "resize" | "destroy">;
  let sky: SkyLike | null = null;
  /** No WebGL, or it was taken back: the CSS room stands in. */
  let flat = $state(false);
  /** The first frame is drawn: fade the canvas in, rather than flash a black one. */
  let shown = $state(false);
  let colours = $state<RGB[]>(paletteFromSeed("room"));

  // The colours: from the picture when it gives some, else from who it is. A
  // moment's wait for the picture, so the room goes straight to its colours
  // rather than to the id's first and the picture's a beat later.
  $effect(() => {
    const s = seed;
    const a = art;
    const fixed = palette;
    if (fixed) {
      colours = fixed;
      return;
    }
    let live = true;
    const fallback = setTimeout(() => {
      if (live) colours = paletteFromSeed(s);
    }, a ? 450 : 0);
    if (a) {
      loadPalette(a).then((p) => {
        if (!live) return;
        clearTimeout(fallback);
        colours = p ?? paletteFromSeed(s);
      });
    }
    return () => {
      live = false;
      clearTimeout(fallback);
    };
  });

  $effect(() => {
    const target = { palette: colours, look: LOOKS[look] ?? LOOKS.silk, energy, focus, focusY: 1 - focusY };
    sky?.set(target);
  });

  $effect(() => {
    oncolours?.(colours);
  });

  /** The pulse count last seen: a change is a reply gone out. */
  let seen = -1;
  $effect(() => {
    const p = pulse;
    if (seen >= 0 && p !== seen) sky?.pulse();
    seen = p;
  });

  $effect(() => {
    sky?.setStill(!$motionEnabled);
  });

  const onMove = (e: PointerEvent) => sky?.pointer(e.clientX / innerWidth, e.clientY / innerHeight);

  /** The first frame is on screen: fade the canvas up into the dark room. */
  const lit = () => requestAnimationFrame(() => requestAnimationFrame(() => (shown = true)));
  const target = () => $state.snapshot({ palette: colours, look: LOOKS[look] ?? LOOKS.silk, energy, focus, focusY: 1 - focusY });

  /**
   * The room drawn in a worker (sky.worker.ts): the canvas is handed over, and
   * the graphics context, the shader and every frame are made off this
   * thread. Null where the browser cannot hand a canvas to a worker.
   */
  function inWorker(c: HTMLCanvasElement): SkyLike | null {
    if (typeof c.transferControlToOffscreen !== "function" || typeof Worker === "undefined") return null;
    let worker: Worker;
    try {
      worker = new Worker(new URL("./sky.worker.ts", import.meta.url), { type: "module" });
    } catch {
      return null;
    }
    const giveUp = () => {
      sky = null;
      flat = true;
      worker.terminate();
    };
    worker.onmessage = (e) => {
      if (e.data?.type === "ready") lit();
      else if (e.data?.type === "failed" || e.data?.type === "lost") giveUp();
    };
    worker.onerror = giveUp;
    const off = c.transferControlToOffscreen();
    const r = c.getBoundingClientRect();
    worker.postMessage({ type: "init", canvas: off, scale: 1 / 2, w: r.width, h: r.height,
                         still: !get(motionEnabled), target: target() }, [off]);
    // The pointer moves far more often than frames are drawn: once a frame is plenty.
    let px = 0.5;
    let py = 0.5;
    let queued = false;
    return {
      set: (t, now = false) => worker.postMessage({ type: "set", target: $state.snapshot(t), now }),
      pulse: () => worker.postMessage({ type: "pulse" }),
      pointer: (x, y) => {
        px = x;
        py = y;
        if (queued) return;
        queued = true;
        requestAnimationFrame(() => {
          queued = false;
          worker.postMessage({ type: "pointer", x: px, y: py });
        });
      },
      setStill: (still) => worker.postMessage({ type: "still", still }),
      resize: (w, h) => worker.postMessage({ type: "resize", w, h }),
      destroy: () => {
        worker.postMessage({ type: "destroy" });
        setTimeout(() => worker.terminate(), 250);
      },
    };
  }

  // Where it cannot be handed to a worker, the room is made here, and lit once
  // the view has arrived rather than while it arrives: a graphics context and
  // its shader made in the same frame as everything else were most of the
  // stutter on opening. Until then it is the dark room, and the light fades up.
  let dead = false;
  let lightUp: ReturnType<typeof setTimeout> | null = null;
  onMount(() => {
    const c = canvas;
    if (!c) return;
    const sizes = new ResizeObserver(([e]) => sky?.resize(e.contentRect.width, e.contentRect.height));
    sizes.observe(c);
    sky = inWorker(c);
    if (sky) {
      window.addEventListener("pointermove", onMove, { passive: true });
      return () => sizes.disconnect();
    }
    lightUp = setTimeout(async () => {
      if (dead) return;
      const made = await Sky.create(canvas ?? c);
      if (dead) {
        made?.destroy();
        return;
      }
      if (!made) {
        flat = true;
        return;
      }
      made.onLost = () => {
        sky = null;
        flat = true;
      };
      made.resize(c.clientWidth, c.clientHeight);
      made.setStill(!get(motionEnabled));
      made.set(target(), true);
      made.start();
      sky = made;
      lit();
      window.addEventListener("pointermove", onMove, { passive: true });
    }, 450);
    return () => sizes.disconnect();
  });
  onDestroy(() => {
    dead = true;
    if (lightUp) clearTimeout(lightUp);
    window.removeEventListener("pointermove", onMove);
    sky?.destroy();
    sky = null;
  });

  const css = (c: RGB | undefined) => (c ? `rgb(${Math.round(c[0] * 255)} ${Math.round(c[1] * 255)} ${Math.round(c[2] * 255)})` : "var(--color-accent)");
</script>

<div class="bpb" class:is-still={!$motionEnabled} aria-hidden="true"
     style="--c0: {css(colours[0])}; --c1: {css(colours[1])}; --c2: {css(colours[2])}; --c3: {css(colours[3])}">
  {#if !flat}
    <canvas class="bpb-sky" class:is-shown={shown} bind:this={canvas}></canvas>
  {:else}
    {#key art}
      {#if art}
        <img class="bpb-art" src={art} alt="" referrerpolicy="no-referrer" draggable="false"
             in:fade={{ duration: 1400 }} out:fade={{ duration: 1400 }} />
      {/if}
    {/key}
    <div class="bpb-aurora">
      <i class="a1"></i><i class="a2"></i><i class="a3"></i><i class="a4"></i>
    </div>
  {/if}
  <div class="bpb-vignette"></div>
</div>

<style>
  .bpb {
    position: absolute;
    inset: 0;
    overflow: hidden;
    /* A dark room under everything, whatever is drawn over it. */
    background: #03040a;
  }
  /* Drawn small and stretched: the browser's smoothing is the last blur it needs. */
  .bpb-sky {
    position: absolute;
    inset: 0;
    display: block;
    width: 100%;
    height: 100%;
    opacity: 0;
    transition: opacity 1.2s ease;
  }
  .bpb-sky.is-shown { opacity: 1; }

  /* ── The stand-in room, without WebGL: the same colours, in CSS ─────────── */
  .bpb-art {
    position: absolute;
    inset: -25%;
    width: 150%;
    height: 150%;
    object-fit: cover;
    filter: blur(96px) saturate(2.2) brightness(0.42);
    opacity: 0.5;
    /* Still: a layer blurred this much and moving is redrawn, blur and all, every frame (app.css, Aurora). The
       blooms over it move instead. */
  }
  /* Screen blending: these only ever add light, so they stay colour rather than turning the dark ground grey. */
  .bpb-aurora { position: absolute; inset: -10%; }
  .bpb-aurora i {
    position: absolute;
    display: block;
    width: 62vmax;
    height: 62vmax;
    border-radius: 50%;
    mix-blend-mode: screen;
    will-change: transform;
    transition: background 1.6s ease;
  }
  /* Soft without a blur as they move (app.css, Aurora): the blur's falloff drawn into each gradient. And stepped
     about fifteen times a second, through eased frames in between, as the slow drifts there are. */
  .bpb-aurora .a1 { left: -16vmax; top: -22vmax; background: radial-gradient(circle, color-mix(in srgb, var(--c0) 88%, transparent), color-mix(in srgb, var(--c0) 62%, transparent) 25%, color-mix(in srgb, var(--c0) 28%, transparent) 50%, color-mix(in srgb, var(--c0) 7%, transparent) 68%, transparent 88%); opacity: 0.5; animation: bpb-d1 34s steps(64) infinite alternate; }
  .bpb-aurora .a2 { right: -20vmax; top: 4vmax; background: radial-gradient(circle, color-mix(in srgb, var(--c1) 88%, transparent), color-mix(in srgb, var(--c1) 62%, transparent) 25%, color-mix(in srgb, var(--c1) 28%, transparent) 50%, color-mix(in srgb, var(--c1) 7%, transparent) 68%, transparent 88%); opacity: 0.38; animation: bpb-d2 42s steps(79) infinite alternate; }
  .bpb-aurora .a3 { left: 18vmax; bottom: -34vmax; background: radial-gradient(circle, color-mix(in srgb, var(--c2) 88%, transparent), color-mix(in srgb, var(--c2) 62%, transparent) 25%, color-mix(in srgb, var(--c2) 28%, transparent) 50%, color-mix(in srgb, var(--c2) 7%, transparent) 68%, transparent 88%); opacity: 0.34; animation: bpb-d3 50s steps(94) infinite alternate; }
  .bpb-aurora .a4 { right: 8vmax; bottom: -28vmax; width: 46vmax; height: 46vmax; background: radial-gradient(circle, color-mix(in srgb, var(--c3) 88%, transparent), color-mix(in srgb, var(--c3) 62%, transparent) 25%, color-mix(in srgb, var(--c3) 28%, transparent) 50%, color-mix(in srgb, var(--c3) 7%, transparent) 70%, transparent 90%); opacity: 0.3; animation: bpb-d4 38s steps(71) infinite alternate; }
  /* Each the same path as before, ease-in-out read off every eighth of the way. */
  @keyframes bpb-d1 {
    0% { transform: translate3d(0, 0, 0) scale(1); }
    12.5% { transform: translate3d(0.68vmax, 0.4vmax, 0) scale(1.006); }
    25% { transform: translate3d(2.84vmax, 1.68vmax, 0) scale(1.026); }
    37.5% { transform: translate3d(6.44vmax, 3.81vmax, 0) scale(1.059); }
    50% { transform: translate3d(11vmax, 6.5vmax, 0) scale(1.1); }
    62.5% { transform: translate3d(15.56vmax, 9.19vmax, 0) scale(1.141); }
    75% { transform: translate3d(19.16vmax, 11.32vmax, 0) scale(1.174); }
    87.5% { transform: translate3d(21.32vmax, 12.6vmax, 0) scale(1.194); }
    100% { transform: translate3d(22vmax, 13vmax, 0) scale(1.2); }
  }
  @keyframes bpb-d2 {
    0% { transform: translate3d(0, 0, 0) scale(1); }
    12.5% { transform: translate3d(-0.62vmax, 0.53vmax, 0) scale(0.995); }
    25% { transform: translate3d(-2.58vmax, 2.2vmax, 0) scale(0.981); }
    37.5% { transform: translate3d(-5.86vmax, 4.98vmax, 0) scale(0.956); }
    50% { transform: translate3d(-10vmax, 8.5vmax, 0) scale(0.925); }
    62.5% { transform: translate3d(-14.14vmax, 12.02vmax, 0) scale(0.894); }
    75% { transform: translate3d(-17.42vmax, 14.8vmax, 0) scale(0.869); }
    87.5% { transform: translate3d(-19.38vmax, 16.47vmax, 0) scale(0.855); }
    100% { transform: translate3d(-20vmax, 17vmax, 0) scale(0.85); }
  }
  @keyframes bpb-d3 {
    0% { transform: translate3d(0, 0, 0) scale(1); }
    12.5% { transform: translate3d(-0.47vmax, -0.5vmax, 0) scale(1.008); }
    25% { transform: translate3d(-1.94vmax, -2.07vmax, 0) scale(1.032); }
    37.5% { transform: translate3d(-4.39vmax, -4.68vmax, 0) scale(1.073); }
    50% { transform: translate3d(-7.5vmax, -8vmax, 0) scale(1.125); }
    62.5% { transform: translate3d(-10.61vmax, -11.32vmax, 0) scale(1.177); }
    75% { transform: translate3d(-13.06vmax, -13.93vmax, 0) scale(1.218); }
    87.5% { transform: translate3d(-14.53vmax, -15.5vmax, 0) scale(1.242); }
    100% { transform: translate3d(-15vmax, -16vmax, 0) scale(1.25); }
  }
  @keyframes bpb-d4 {
    0% { transform: translate3d(0, 0, 0) scale(1); }
    12.5% { transform: translate3d(-0.34vmax, -0.4vmax, 0) scale(1.005); }
    25% { transform: translate3d(-1.42vmax, -1.68vmax, 0) scale(1.019); }
    37.5% { transform: translate3d(-3.22vmax, -3.81vmax, 0) scale(1.044); }
    50% { transform: translate3d(-5.5vmax, -6.5vmax, 0) scale(1.075); }
    62.5% { transform: translate3d(-7.78vmax, -9.19vmax, 0) scale(1.106); }
    75% { transform: translate3d(-9.58vmax, -11.32vmax, 0) scale(1.131); }
    87.5% { transform: translate3d(-10.66vmax, -12.6vmax, 0) scale(1.145); }
    100% { transform: translate3d(-11vmax, -13vmax, 0) scale(1.15); }
  }

  /* Darker at the edges than the middle, and under the bars top and bottom, so they read. */
  .bpb-vignette {
    position: absolute;
    inset: 0;
    background:
      radial-gradient(ellipse 90% 80% at 50% 45%, transparent 48%, rgb(0 0 0 / 0.55)),
      linear-gradient(to bottom, rgb(0 0 0 / 0.3), transparent 20%, transparent 76%, rgb(0 0 0 / 0.4));
  }

  .bpb.is-still .bpb-art,
  .bpb.is-still .bpb-aurora i { animation: none; }
</style>
