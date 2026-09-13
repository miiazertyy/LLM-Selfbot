<script lang="ts">
  /**
   * Pixelated cursor snow.
   *
   * Simulated on a fine cell grid, drawn into a small offscreen buffer and
   * blown up with smoothing off, that is what makes the pixels genuinely
   * chunky rather than blurry dots.
   *
   * A moving cursor is the only source; a still cursor sheds nothing.
   *
   * One layer only, and nothing ever accumulates on the ground: a flake is
   * removed the moment it reaches the bottom. Roughly half fade out mid-air on
   * the way down (MELT), and between gravity steps a Life pass reshapes the
   * clumps, so a trail merges and morphs as it falls rather than dropping as a
   * column of identical dots.
   *
   * Flakes come in depth tiers (see TIERS) setting brightness and fall speed,
   * so they are neither uniformly opaque nor moving in lockstep, and a flake
   * on its way out dims progressively rather than blinking off.
   */
  let { enabled } = $props<{ enabled: boolean }>();

  let canvas: HTMLCanvasElement | null = $state(null);

  // ── Tuning ────────────────────────────────────────────────────────────────
  const CELL = 3;              // screen px per grid cell, chunky square pixels
  const MOVE_MIN = 1.2;        // grid px/frame before the cursor sheds anything
  const PER_MOVE = 0.30;       // cells shed per grid-px of cursor travel
  const MAX_SHED = 2;          // at most two cells per frame, a light trail
  const SPREAD = 3;            // cells around the pointer that flakes appear in

  /**
   * Depth tiers: dim flakes read as far away and fall slowly, bright ones as
   * near and fall quickly. Each flake's tier is held in its own array, because
   * its alpha changes as it fades and must not drag its speed along with it.
   *
   * The tiers are what stop the snow looking like one smooth sheet sliding
   * down. Every flake used to step on the same frame, so the whole trail moved
   * in lockstep; now each tier steps on its own cadence and they visibly fall
   * at different rates, one chunky row at a time.
   */
  const TIERS = [
    { every: 5, lo: 55, hi: 105 },    // far - dim, slow
    { every: 3, lo: 120, hi: 175 },   // mid
    { every: 2, lo: 205, hi: 255 },   // near - bright, quick
  ];
  const tierValue = (t: number) =>
    TIERS[t].lo + Math.floor(Math.random() * (TIERS[t].hi - TIERS[t].lo + 1));
  const randomTier = () => Math.floor(Math.random() * TIERS.length);

  const LIFE_EVERY = 5;        // frames between Life passes
  const BIRTH = 0.03;          // chance an eligible empty cell is actually born
  const CROWD = 6;             // more neighbours than this and a cell compacts
  // Per Life pass, so it compounds: ~12 passes/second across a fall lasting
  // 10-25s (depending on tier) means a seemingly tiny number decides how much
  // of the trail survives. Tuned so about half of it fades out on the way down.
  const MELT = 0.004;          // chance a flake STARTS fading out, per Life pass
  const FADE = 0.7;            // alpha kept per pass once it is fading
  const GONE = 3;              // below this alpha a fading flake is removed
  const MAX_LIVE = 150;        // hard ceiling so births can never run away
  const DRIFT = 0.22;          // chance a cell drifts sideways per step

  let ctx: CanvasRenderingContext2D | null = null;
  let buf: HTMLCanvasElement | null = null;
  let bctx: CanvasRenderingContext2D | null = null;
  let img: ImageData | null = null;
  let px: Uint8ClampedArray | null = null;

  let cols = 0, rows = 0, W = 0, H = 0;

  // Brightness grid (0 = empty). There is no settled layer: a flake that
  // reaches the last row is deleted rather than piling up.
  // fall = current alpha, tier = which depth band the flake belongs to.
  // They used to be the same number, but then dimming a flake would also
  // change how fast it falls, so a fading flake would visibly slow down.
  let fall: Uint8Array = new Uint8Array(0);
  let tier: Uint8Array = new Uint8Array(0);
  let scratch: Uint8Array = new Uint8Array(0);
  let scratchTier: Uint8Array = new Uint8Array(0);
  let live = 0;
  let top = 0, bot = -1;       // active row band, so we never scan the whole grid

  let raf = 0;
  let frame = 0;

  const mouse = { x: -999, y: -999, px: -999, py: -999, inside: false, moved: 0 };

  // ── Grid helpers ──────────────────────────────────────────────────────────
  function paint(c: number, r: number, v: number) {
    if (!px) return;
    const i = (r * cols + c) * 4;
    // Cool white with a faint blue lift; alpha carries brightness.
    px[i] = 226; px[i + 1] = 234; px[i + 2] = 255; px[i + 3] = v;
  }

  function seed(c: number, r: number) {
    if (c < 0 || c >= cols || r < 0 || r >= rows || live >= MAX_LIVE) return;
    const i = r * cols + c;
    if (fall[i]) return;
    const t = randomTier();
    fall[i] = tierValue(t);
    tier[i] = t;
    live++;
    if (bot < top) { top = bot = r; }
    else { if (r < top) top = r; if (r > bot) bot = r; }
  }

  function resize() {
    if (!canvas) return;
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width = W;
    canvas.height = H;
    cols = Math.max(1, Math.ceil(W / CELL));
    rows = Math.max(1, Math.ceil(H / CELL));

    ctx = canvas.getContext("2d");
    if (ctx) ctx.imageSmoothingEnabled = false;   // the whole point: hard pixels

    buf = document.createElement("canvas");
    buf.width = cols;
    buf.height = rows;
    bctx = buf.getContext("2d", { willReadFrequently: true });
    img = bctx ? bctx.createImageData(cols, rows) : null;
    px = img ? img.data : null;

    const n = cols * rows;
    fall = new Uint8Array(n);
    tier = new Uint8Array(n);
    scratch = new Uint8Array(n);
    scratchTier = new Uint8Array(n);
    live = 0;
    top = 0; bot = -1;
  }

  /** Live neighbours of (c,r). */
  function neighbours(c: number, r: number): number {
    let n = 0;
    const up = (r - 1) * cols, mid = r * cols, dn = (r + 1) * cols;
    const l = c > 0 ? c - 1 : -1;
    const rt = c < cols - 1 ? c + 1 : -1;
    if (r > 0) {
      if (l >= 0 && fall[up + l]) n++;
      if (fall[up + c]) n++;
      if (rt >= 0 && fall[up + rt]) n++;
    }
    if (l >= 0 && fall[mid + l]) n++;
    if (rt >= 0 && fall[mid + rt]) n++;
    if (r < rows - 1) {
      if (l >= 0 && fall[dn + l]) n++;
      if (fall[dn + c]) n++;
      if (rt >= 0 && fall[dn + rt]) n++;
    }
    return n;
  }

  /**
   * Everything steps down one row. Reaching the last row removes the flake, 
   * this is the only place snow leaves the screen, and why none collects on
   * the ground.
   */
  function gravity() {
    let lo = rows, hi = -1;
    for (let r = Math.min(bot, rows - 1); r >= top; r--) {
      for (let c = 0; c < cols; c++) {
        const i = r * cols + c;
        const v = fall[i];
        if (!v) continue;

        // Not this flake's frame, it holds position while quicker tiers move
        // past it. This staggering is what makes the fall read as individual
        // pixels dropping rather than one sheet gliding down.
        if (frame % TIERS[tier[i]].every !== 0) {
          if (r < lo) lo = r; if (r > hi) hi = r;
          continue;
        }
        const vt = tier[i];
        fall[i] = 0;

        // Occasional sideways drift keeps columns from marching in lockstep.
        let c2 = c;
        if (Math.random() < DRIFT) c2 = c + (Math.random() < 0.5 ? -1 : 1);
        if (c2 < 0 || c2 >= cols) c2 = c;

        const r2 = r + 1;
        if (r2 >= rows) {            // reached the ground, gone
          live--;
          continue;
        }
        const j = r2 * cols + c2;
        if (fall[j]) {               // blocked by another flake, hold a step
          fall[i] = v;
          tier[i] = vt;
          if (r < lo) lo = r; if (r > hi) hi = r;
          continue;
        }
        fall[j] = v;
        tier[j] = vt;
        if (r2 < lo) lo = r2; if (r2 > hi) hi = r2;
      }
    }
    top = lo; bot = hi;
  }

  /**
   * Life over the in-flight snow, clumps merge, split and change shape.
   *
   * A flake picked by MELT does not blink out: its alpha is multiplied down by
   * FADE on every pass, so it dims steadily over roughly a second and is only
   * removed once it is essentially invisible. A flake is recognisably "fading"
   * simply by having dropped below its tier's normal brightness, so no extra
   * bookkeeping is needed to remember which ones are on the way out.
   *
   * Births stay rarer than the losses, and MAX_LIVE caps the population, so a
   * trail cannot breed itself into ambient snowfall.
   */
  function life() {
    const lo0 = Math.max(0, top - 1);
    const hi0 = Math.min(rows - 1, bot + 1);
    if (hi0 < lo0) return;
    scratch.fill(0, lo0 * cols, (hi0 + 1) * cols);
    scratchTier.fill(0, lo0 * cols, (hi0 + 1) * cols);

    const room = live < MAX_LIVE;
    let count = 0, lo = rows, hi = -1;
    for (let r = lo0; r <= hi0; r++) {
      for (let c = 0; c < cols; c++) {
        const i = r * cols + c;
        const v = fall[i];
        const n = neighbours(c, r);
        let out = 0;
        let outTier = tier[i];
        if (v) {
          const floor = TIERS[outTier].lo;
          if (v < floor) {
            // Already on the way out, keep dimming, and drop it once the
            // alpha is low enough that it reads as gone.
            const dimmed = Math.floor(v * FADE);
            out = dimmed > GONE ? dimmed : 0;
          } else if (n > CROWD) {
            out = 0;                                  // crowded out
          } else if (Math.random() < MELT) {
            // Start fading: step just under the tier floor so the next pass
            // recognises it as fading rather than healthy.
            out = Math.max(GONE + 1, Math.floor(floor * FADE));
          } else {
            out = v;
          }
        } else if (n === 3 && room && Math.random() < BIRTH) {
          outTier = randomTier();
          out = tierValue(outTier);                   // merged into being
        }
        if (out) {
          scratch[i] = out; scratchTier[i] = outTier; count++;
          if (r < lo) lo = r; if (r > hi) hi = r;
        }
      }
    }
    // The band covers every live cell, so the copy back is complete.
    const from = lo0 * cols, to = (hi0 + 1) * cols;
    fall.set(scratch.subarray(from, to), from);
    tier.set(scratchTier.subarray(from, to), from);
    live = count;
    top = lo; bot = hi;
  }

  // ── Frame ─────────────────────────────────────────────────────────────────
  function tick() {
    if (!ctx || !bctx || !img || !px || !canvas) return;
    frame++;
    px.fill(0);

    // Shed strictly in proportion to how far the cursor actually moved this
    // frame. A still cursor moves 0, so it sheds nothing.
    if (mouse.inside && mouse.moved >= MOVE_MIN) {
      let n = Math.min(MAX_SHED, mouse.moved * PER_MOVE);
      while (n > 0) {
        if (n < 1 && Math.random() > n) break;
        seed(
          Math.round(mouse.x + (Math.random() - 0.5) * SPREAD),
          Math.round(mouse.y + (Math.random() - 0.5) * SPREAD),
        );
        n--;
      }
    }
    mouse.moved = 0;   // reset each frame; only real movement refills it

    if (live > 0) {
      // Every frame now: gravity decides per flake whether this is its step,
      // from its tier's cadence.
      gravity();
      if (live > 0 && frame % LIFE_EVERY === 0) life();

      for (let r = top; r <= bot; r++) {
        const row = r * cols;
        for (let c = 0; c < cols; c++) {
          const v = fall[row + c];
          if (v) paint(c, r, v);
        }
      }
    }

    bctx.putImageData(img, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(buf!, 0, 0, cols, rows, 0, 0, cols * CELL, rows * CELL);

    raf = requestAnimationFrame(tick);
  }

  // ── Input ─────────────────────────────────────────────────────────────────
  function onMove(e: MouseEvent) {
    const x = e.clientX / CELL;
    const y = e.clientY / CELL;
    if (mouse.inside) mouse.moved += Math.hypot(x - mouse.px, y - mouse.py);
    mouse.x = mouse.px = x;
    mouse.y = mouse.py = y;
    mouse.inside = true;
  }

  function onLeave() {
    mouse.inside = false;
    mouse.moved = 0;
  }

  function onVisibility() {
    if (document.hidden) stop();
    else if (enabled) start();
  }

  function start() {
    if (raf) return;
    if (!cols) resize();
    raf = requestAnimationFrame(tick);
  }

  function stop() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  }

  $effect(() => {
    // No prefers-reduced-motion gate: `enabled` is the user's explicit choice
    // in Settings, and Windows reports "reduce" merely for having animation
    // effects off, which silently hid the snow entirely.
    if (enabled) {
      resize();
      start();
      window.addEventListener("resize", resize);
      window.addEventListener("mousemove", onMove, { passive: true });
      document.addEventListener("mouseleave", onLeave);
      document.addEventListener("visibilitychange", onVisibility);
    } else {
      stop();
    }

    return () => {
      stop();
      window.removeEventListener("resize", resize);
      window.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseleave", onLeave);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  });
</script>

{#if enabled}
  <canvas
    bind:this={canvas}
    class="pointer-events-none fixed inset-0 z-30"
    style="image-rendering: pixelated;"
    aria-hidden="true"
  ></canvas>
{/if}
