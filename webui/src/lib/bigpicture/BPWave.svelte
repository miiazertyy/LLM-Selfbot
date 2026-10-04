<script lang="ts">
  /**
   * The last day's activity as one glowing wave: a point per hour, the current
   * hour pulsing at the right end. Drawn in when it appears.
   */
  let { values = [], height = 70, label = "" }: { values?: number[]; height?: number; label?: string } = $props();

  const W = 600;
  /** Room kept clear above and below the curve, so neither the line nor its glow
      ever touches an edge: it used to sit flat on the bottom and read as cut off. */
  const PAD_TOP = 10;
  /** Generous, because a quiet day is a flat line and one sitting on the very
      bottom edge reads as a chart that has been cut off rather than a quiet day. */
  const PAD_BOTTOM = 18;
  const pts = $derived.by(() => {
    const v = values.length ? values : Array(24).fill(0);
    const max = Math.max(1, ...v);
    const step = W / Math.max(1, v.length - 1);
    const span = Math.max(1, height - PAD_TOP - PAD_BOTTOM);
    return v.map((n, i) => [i * step, height - PAD_BOTTOM - (n / max) * span] as [number, number]);
  });

  /** A smooth line through the points (Catmull-Rom as cubic Béziers). */
  const line = $derived.by(() => {
    const p = pts;
    if (p.length < 2) return "";
    let d = `M${p[0][0]},${p[0][1]}`;
    for (let i = 0; i < p.length - 1; i++) {
      const p0 = p[i - 1] ?? p[i], p1 = p[i], p2 = p[i + 1], p3 = p[i + 2] ?? p2;
      const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
      const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
      d += ` C${c1[0]},${c1[1]} ${c2[0]},${c2[1]} ${p2[0]},${p2[1]}`;
    }
    return d;
  });
  /** The fill stops short of the bottom and fades out into it, rather than ending on a hard edge. */
  const floor = $derived(height - PAD_BOTTOM * 0.35);
  const area = $derived(line ? `${line} L${W},${floor} L0,${floor} Z` : "");
  const last = $derived(pts[pts.length - 1] ?? [W, height]);
  const peak = $derived(Math.max(0, ...(values.length ? values : [0])));
  const uid = `bpw${Math.random().toString(36).slice(2, 8)}`;
</script>

<div class="bpw" style="height: {height}px">
  <svg viewBox="0 0 {W} {height}" preserveAspectRatio="none" role="img"
       aria-label="{label || 'Activity'}: {values.join(', ')} per hour, busiest {peak}">
    <defs>
      <linearGradient id="{uid}-fill" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="var(--color-accent)" stop-opacity="0.42" />
        <stop offset="55%" stop-color="var(--color-accent)" stop-opacity="0.14" />
        <stop offset="100%" stop-color="var(--color-accent)" stop-opacity="0" />
      </linearGradient>
      <!-- The fill dissolves into the bar instead of stopping on a straight line. -->
      <linearGradient id="{uid}-soft" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#fff" stop-opacity="1" />
        <stop offset="78%" stop-color="#fff" stop-opacity="1" />
        <stop offset="100%" stop-color="#fff" stop-opacity="0" />
      </linearGradient>
      <mask id="{uid}-mask">
        <rect x="0" y="0" width={W} height={height} fill="url(#{uid}-soft)" />
      </mask>
    </defs>
    <!-- Where nothing happened, so a flat line reads as a quiet day against a baseline. -->
    <line class="bpw-base" x1="0" y1={height - PAD_BOTTOM} x2={W} y2={height - PAD_BOTTOM} />
    <path d={area} fill="url(#{uid}-fill)" mask="url(#{uid}-mask)" />
    <path class="bpw-line" d={line} fill="none" pathLength="1" />
  </svg>
  <span class="bpw-now" style="left: {(last[0] / W) * 100}%; top: {(last[1] / height) * 100}%"></span>
</div>

<style>
  .bpw { position: relative; width: 100%; }
  .bpw-base { stroke: rgb(255 255 255 / 0.1); stroke-width: 1; }
  svg { display: block; width: 100%; height: 100%; overflow: visible; }
  .bpw-line {
    stroke: color-mix(in srgb, var(--color-accent) 85%, white);
    stroke-width: 2.5;
    filter: drop-shadow(0 0 6px color-mix(in srgb, var(--color-accent) 70%, transparent));
    stroke-dasharray: 1;
    animation: bpw-draw 1.6s var(--swift) both;
  }
  @keyframes bpw-draw { from { stroke-dashoffset: 1; } to { stroke-dashoffset: 0; } }
  .bpw-now {
    position: absolute;
    width: 10px;
    height: 10px;
    margin: -5px 0 0 -5px;
    border-radius: 999px;
    background: #fff;
    box-shadow: 0 0 29px color-mix(in srgb, var(--color-accent) 42%, transparent);
  }
  /* The beat is a ring that swells and fades: transform and opacity, which the
     graphics card animates by itself. It was the ring's box-shadow growing,
     which had the page repaint it every frame for as long as Big Picture was open. */
  .bpw-now::after {
    content: "";
    position: absolute;
    inset: -4px;
    border-radius: 999px;
    border: 4px solid color-mix(in srgb, var(--color-accent) 45%, transparent);
    animation: bpw-beat 1.6s ease-in-out infinite;
  }
  @keyframes bpw-beat { 50% { transform: scale(1.45); opacity: 0.3; } }
  :global(:root[data-motion="off"]) .bpw-line,
  :global(:root[data-motion="off"]) .bpw-now::after { animation: none; }
</style>
