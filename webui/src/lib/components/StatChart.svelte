<script lang="ts">
  /**
   * The drill-down's chart: one series, drawn as inline SVG, with a hover
   * layer.
   *
   * Separate from Chart.svelte on purpose. That one is a sparkline inside a
   * dashboard card - no axes, no interaction, and deliberately tiny. This one
   * is the thing you opened on purpose, so it carries a crosshair, a tooltip,
   * a baseline and value labels.
   *
   * One series, one hue, always the theme accent. The app's second accent
   * cannot be used as a categorical partner: measured against each theme's own
   * surface, accent and accent-2 fall below the normal-vision separation floor
   * in four of the six themes (slate is the worst at dE 8.8, where 15 is the
   * floor), so two-series colour would be unreadable for some people on most
   * themes. Anything that needs a second series is drawn as a second chart.
   */
  let {
    values = [],
    labels = [],
    kind = "area",
    height = 150,
    /** Shown in the tooltip after the number, e.g. "replies". */
    unit = "",
    /** Highlight the largest bar/point. */
    markPeak = true,
  }: {
    values?: number[];
    labels?: string[];
    kind?: "area" | "bars";
    height?: number;
    unit?: string;
    markPeak?: boolean;
  } = $props();

  const W = 600;
  const PAD_X = 6;
  const PAD_T = 14;          // headroom so the peak label is not clipped
  const PAD_B = 2;

  const max = $derived(Math.max(1, ...values));
  const peak = $derived(values.indexOf(max));
  const plotH = $derived(height - PAD_T - PAD_B);
  const y = (v: number) => PAD_T + plotH - (v / max) * plotH;
  const stepX = $derived(values.length > 1 ? (W - PAD_X * 2) / (values.length - 1) : 0);
  const slotW = $derived(values.length ? (W - PAD_X * 2) / values.length : 0);

  const line = $derived.by(() => {
    if (!values.length) return "";
    if (values.length === 1) return `M${PAD_X} ${y(values[0])} L${W - PAD_X} ${y(values[0])}`;
    let d = `M${PAD_X} ${y(values[0])}`;
    for (let i = 1; i < values.length; i++) {
      const x0 = PAD_X + (i - 1) * stepX;
      const x1 = PAD_X + i * stepX;
      const xm = (x0 + x1) / 2;
      d += ` C${xm} ${y(values[i - 1])} ${xm} ${y(values[i])} ${x1} ${y(values[i])}`;
    }
    return d;
  });
  const area = $derived(line ? `${line} L${W - PAD_X} ${height - PAD_B} L${PAD_X} ${height - PAD_B} Z` : "");

  const uid = `sc${Math.random().toString(36).slice(2, 8)}`;
  const total = $derived(values.reduce((a, b) => a + b, 0));

  let hover = $state(-1);
  let svgEl: SVGSVGElement | null = $state(null);

  /**
   * Nearest point to the pointer, in viewBox units.
   *
   * The hit target is the whole chart height for a given column, not the mark
   * itself: a 2px line is not something anyone can point at.
   */
  function onMove(e: PointerEvent) {
    if (!svgEl || !values.length) return;
    const r = svgEl.getBoundingClientRect();
    if (!r.width) return;
    const x = ((e.clientX - r.left) / r.width) * W;
    const i = kind === "bars"
      ? Math.floor((x - PAD_X) / (slotW || 1))
      : Math.round((x - PAD_X) / (stepX || 1));
    hover = Math.max(0, Math.min(values.length - 1, i));
  }

  const hoverX = $derived(
    hover < 0 ? 0
      : kind === "bars"
        ? PAD_X + hover * slotW + slotW / 2
        : PAD_X + hover * stepX,
  );
  /** Keep the tooltip inside the box at both ends. */
  const tipPct = $derived(Math.max(6, Math.min(94, (hoverX / W) * 100)));

  /** Where the peak actually sits, as a percentage of the plot width. */
  const peakPct = $derived.by(() => {
    if (peak < 0 || !values.length) return 50;
    const x = kind === "bars"
      ? PAD_X + peak * slotW + slotW / 2
      : PAD_X + peak * stepX;
    return (x / W) * 100;
  });
  /**
   * Hidden when it would collide with an end label, rather than drawn on top
   * of one. Roughly: a label is ~13% of the width, so anything inside that of
   * either end overlaps.
   */
  const showPeakLabel = $derived(
    peak > 0 && peak < values.length - 1 && peakPct > 16 && peakPct < 84,
  );
</script>

{#if !values.length || total === 0}
  <div class="flex items-center justify-center rounded-lg bg-white/[0.02] text-[12px] text-faint"
       style="height: {height}px">
    Nothing recorded in this window
  </div>
{:else}
  <div class="relative">
    <svg
      bind:this={svgEl}
      viewBox="0 0 {W} {height}"
      preserveAspectRatio="none"
      class="w-full touch-none"
      style="height: {height}px"
      role="img"
      aria-label="{total} {unit || 'items'} over {values.length} points"
      onpointermove={onMove}
      onpointerleave={() => (hover = -1)}
    >
      <defs>
        <linearGradient id={uid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--color-accent)" stop-opacity="0.30" />
          <stop offset="100%" stop-color="var(--color-accent)" stop-opacity="0" />
        </linearGradient>
      </defs>

      <!-- Recessive baseline: the zero line is worth seeing, the rest is not. -->
      <line x1={PAD_X} x2={W - PAD_X} y1={height - PAD_B} y2={height - PAD_B}
            stroke="var(--color-edge)" stroke-width="1" vector-effect="non-scaling-stroke" />

      {#if kind === "bars"}
        {#each values as v, i}
          <!-- 2px gap between fills, and the radius is capped at half the bar
               height so a one-message day is not drawn as a lozenge. -->
          {@const bw = Math.max(1, slotW - 2)}
          {@const bh = Math.max(v ? 2 : 0, height - PAD_B - y(v))}
          <rect
            x={PAD_X + i * slotW + 1}
            y={y(v)}
            width={bw}
            height={bh}
            rx={Math.min(4, bw / 2, bh / 2)}
            fill="var(--color-accent)"
            opacity={hover === i ? 1 : v ? (markPeak && i === peak ? 0.95 : 0.7) : 0.12}
          />
        {/each}
      {:else}
        <path d={area} fill="url(#{uid})" />
        <path d={line} fill="none" stroke="var(--color-accent)" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round"
              vector-effect="non-scaling-stroke" />
      {/if}

      {#if hover >= 0}
        <line x1={hoverX} x2={hoverX} y1={PAD_T - 6} y2={height - PAD_B}
              stroke="var(--color-accent)" stroke-opacity="0.35" stroke-width="1"
              vector-effect="non-scaling-stroke" />
        {#if kind !== "bars"}
          <!-- 2px surface ring, so the marker reads on top of the fill. -->
          <circle cx={hoverX} cy={y(values[hover])} r="5"
                  fill="var(--color-accent)" stroke="var(--color-card)" stroke-width="2"
                  vector-effect="non-scaling-stroke" />
        {/if}
      {/if}
    </svg>

    {#if hover >= 0}
      <div
        class="pointer-events-none absolute -top-1 z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap
               rounded-lg border border-edge bg-card px-2 py-1 text-[11px] shadow-lg"
        style="left: {tipPct}%"
      >
        <span class="font-semibold text-ink">{values[hover].toLocaleString()}</span>
        {#if unit}<span class="text-muted"> {unit}</span>{/if}
        {#if labels[hover]}<span class="text-faint"> · {labels[hover]}</span>{/if}
      </div>
    {/if}
  </div>

  {#if labels.length}
    <!-- Only the ends and the peak get a label. A number under every point is
         noise at this width, and the tooltip carries the rest.
         The peak label is positioned at the peak, not spaced evenly between
         the ends: laid out with justify-between it always landed in the middle
         of the axis, which read as labelling whatever was at the middle. -->
    <div class="relative mt-1.5 h-4 text-[10px] text-faint">
      <span class="absolute left-0 top-0">{labels[0]}</span>
      {#if markPeak && showPeakLabel}
        <span
          class="absolute top-0 -translate-x-1/2 whitespace-nowrap text-muted"
          style="left: {peakPct}%"
        >{labels[peak]} · {max.toLocaleString()}</span>
      {/if}
      <span class="absolute right-0 top-0">{labels[labels.length - 1]}</span>
    </div>
  {/if}
{/if}
