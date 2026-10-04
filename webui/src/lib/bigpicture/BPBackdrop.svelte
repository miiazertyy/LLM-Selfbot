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
   * faint HUD grid and a vignette that pulls the eye to the middle.
   *
   * Where WebGL is not to be had, or the graphics card takes it back, the old
   * room stands in: blurred colour drifting in CSS, in the same colours.
   * Motion follows the app's own switch, not Windows' animation setting (see
   * stores.ts): with it off the room is one still frame.
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
    focus = 0.45,
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
    /** Where across the screen the stage is, 0 to 1. */
    focus?: number;
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
    const target = { palette: colours, look: LOOKS[look] ?? LOOKS.silk, energy, focus };
    sky?.set(target);
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
  const target = () => $state.snapshot({ palette: colours, look: LOOKS[look] ?? LOOKS.silk, energy, focus });

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
  <div class="bpb-grid"></div>
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
    animation: bpb-breathe 26s ease-in-out infinite alternate;
  }
  @keyframes bpb-breathe {
    from { transform: scale(1) rotate(0deg) translate3d(0, 0, 0); }
    to { transform: scale(1.12) rotate(2.5deg) translate3d(2%, -1.5%, 0); }
  }
  /* Screen blending: these only ever add light, so they stay colour rather than turning the dark ground grey. */
  .bpb-aurora { position: absolute; inset: -10%; }
  .bpb-aurora i {
    position: absolute;
    display: block;
    width: 62vmax;
    height: 62vmax;
    border-radius: 50%;
    filter: blur(90px);
    mix-blend-mode: screen;
    will-change: transform;
    transition: background 1.6s ease;
  }
  .bpb-aurora .a1 { left: -16vmax; top: -22vmax; background: radial-gradient(circle, var(--c0), transparent 68%); opacity: 0.5; animation: bpb-d1 34s ease-in-out infinite alternate; }
  .bpb-aurora .a2 { right: -20vmax; top: 4vmax; background: radial-gradient(circle, var(--c1), transparent 68%); opacity: 0.38; animation: bpb-d2 42s ease-in-out infinite alternate; }
  .bpb-aurora .a3 { left: 18vmax; bottom: -34vmax; background: radial-gradient(circle, var(--c2), transparent 68%); opacity: 0.34; animation: bpb-d3 50s ease-in-out infinite alternate; }
  .bpb-aurora .a4 { right: 8vmax; bottom: -28vmax; width: 46vmax; height: 46vmax; background: radial-gradient(circle, var(--c3), transparent 70%); opacity: 0.3; animation: bpb-d4 38s ease-in-out infinite alternate; }
  @keyframes bpb-d1 { to { transform: translate3d(22vmax, 13vmax, 0) scale(1.2); } }
  @keyframes bpb-d2 { to { transform: translate3d(-20vmax, 17vmax, 0) scale(0.85); } }
  @keyframes bpb-d3 { to { transform: translate3d(-15vmax, -16vmax, 0) scale(1.25); } }
  @keyframes bpb-d4 { to { transform: translate3d(-11vmax, -13vmax, 0) scale(1.15); } }

  /* The HUD: a faint grid, fading out towards the edges. */
  .bpb-grid {
    position: absolute;
    inset: 0;
    background-image:
      linear-gradient(rgb(255 255 255 / 0.025) 1px, transparent 1px),
      linear-gradient(90deg, rgb(255 255 255 / 0.025) 1px, transparent 1px);
    background-size: 58px 58px;
    -webkit-mask-image: radial-gradient(ellipse 70% 60% at 50% 45%, #000 15%, transparent 78%);
    mask-image: radial-gradient(ellipse 70% 60% at 50% 45%, #000 15%, transparent 78%);
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
