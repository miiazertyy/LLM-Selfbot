<script lang="ts">
  /**
   * Small area/bar chart drawn as inline SVG.
   *
   * No charting library on purpose: the app is served from a local FastAPI
   * process with no CDN access, and a dependency for one curve is not worth
   * the bundle. Everything here is plain path maths.
   */
  let {
    data = [],
    kind = "area",
    height = 96,
    accent = "var(--color-accent)",
    labels = [],
  } = $props<{
    data?: number[];
    kind?: "area" | "bars";
    height?: number;
    accent?: string;
    labels?: string[];
  }>();

  const W = 300;                      // viewBox units; the SVG scales to fit
  const PAD = 4;

  const max = $derived(Math.max(1, ...data));
  const stepX = $derived(data.length > 1 ? (W - PAD * 2) / (data.length - 1) : 0);
  const y = (v: number) => height - PAD - (v / max) * (height - PAD * 2);

  // A smooth-ish line: midpoint curves, which avoids the overshoot a naive
  // cubic spline gives on spiky data.
  const line = $derived.by(() => {
    if (!data.length) return "";
    if (data.length === 1) return `M${PAD} ${y(data[0])} L${W - PAD} ${y(data[0])}`;
    let d = `M${PAD} ${y(data[0])}`;
    for (let i = 1; i < data.length; i++) {
      const x0 = PAD + (i - 1) * stepX;
      const x1 = PAD + i * stepX;
      const xm = (x0 + x1) / 2;
      d += ` C${xm} ${y(data[i - 1])} ${xm} ${y(data[i])} ${x1} ${y(data[i])}`;
    }
    return d;
  });

  const area = $derived(line ? `${line} L${W - PAD} ${height} L${PAD} ${height} Z` : "");
  const barW = $derived(data.length ? (W - PAD * 2) / data.length - 2 : 0);
  const uid = `g${Math.random().toString(36).slice(2, 8)}`;
</script>

{#if data.length === 0 || max <= 0}
  <div class="flex items-center justify-center text-[11px] text-faint" style="height: {height}px">
    Nothing recorded yet
  </div>
{:else}
  <svg
    viewBox="0 0 {W} {height}"
    preserveAspectRatio="none"
    class="w-full"
    style="height: {height}px"
    role="img"
    aria-label="activity chart"
  >
    <defs>
      <linearGradient id={uid} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color={accent} stop-opacity="0.35" />
        <stop offset="100%" stop-color={accent} stop-opacity="0" />
      </linearGradient>
    </defs>

    {#if kind === "bars"}
      {#each data as v, i}
        <rect
          x={PAD + i * ((W - PAD * 2) / data.length) + 1}
          y={y(v)}
          width={Math.max(1, barW)}
          height={Math.max(1, height - PAD - y(v))}
          rx="1.5"
          fill={accent}
          opacity={v ? 0.85 : 0.18}
        />
      {/each}
    {:else}
      <path d={area} fill="url(#{uid})" />
      <path d={line} fill="none" stroke={accent} stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round"
            vector-effect="non-scaling-stroke" />
    {/if}
  </svg>
  {#if labels.length}
    <div class="mt-1 flex justify-between text-[10px] text-faint">
      {#each labels as l}<span>{l}</span>{/each}
    </div>
  {/if}
{/if}
