<script lang="ts">
  /**
   * What is behind a dashboard figure.
   *
   * A tile is one number, which answers "how many" and nothing else - not when,
   * not who, not whether that is a lot. This opens on a click and answers those:
   * the same figure against the window before it, the shape of a day and of a
   * week, the split between platforms, and the people it is made of.
   *
   * Every chart is one series in the theme accent, faceted rather than
   * multi-coloured. The app gives each theme an accent and a second accent, and
   * measured against that theme's own surface the pair falls below the
   * normal-vision colour separation floor in four of the six themes - so
   * Discord and Snapchat get a chart each instead of two colours on one.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import Icon from "./Icon.svelte";
  import StatChart from "./StatChart.svelte";
  import UserChip from "./UserChip.svelte";

  let { metric = "replies", onclose }: {
    metric?: "replies" | "people" | "accounts";
    onclose?: () => void;
  } = $props();

  const RANGES = [
    { days: 7, label: "7 days" },
    { days: 30, label: "30 days" },
    { days: 90, label: "90 days" },
    { days: 365, label: "1 year" },
  ];

  let days = $state(30);
  let data = $state<any>(null);
  let loading = $state(true);
  let error = $state("");
  /** The numbers behind the charts, for anyone who would rather read them. */
  let showTable = $state(false);

  async function load() {
    loading = !data;
    error = "";
    try {
      data = await api.statsDetail(days);
    } catch (e: any) {
      error = e?.message || "Could not load";
    } finally {
      loading = false;
    }
  }

  onMount(load);
  $effect(() => {
    days;                                   // re-read when the range changes
    void load();
  });

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  // ── Derived shapes ─────────────────────────────────────────────────────────
  const series = $derived(data?.series ?? []);
  const dayTotals = $derived(series.map((d: any) => d.discord + d.snapchat));
  const discordDaily = $derived(series.map((d: any) => d.discord));
  const snapDaily = $derived(series.map((d: any) => d.snapchat));

  const dayLabels = $derived(
    series.map((d: any) =>
      new Date(d.day * 86400000).toLocaleDateString(undefined, { day: "numeric", month: "short" })),
  );

  const hourly = $derived((data?.hourly ?? []).map((h: any) => h.count));
  const hourLabels = $derived((data?.hourly ?? []).map((h: any) => `${String(h.hour).padStart(2, "0")}:00`));

  const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const weekday = $derived((data?.weekday ?? []).map((w: any) => w.count));
  const weekdayLabels = $derived((data?.weekday ?? []).map((w: any) => DOW[w.day] ?? ""));

  const top = $derived(data?.top ?? []);
  const topMax = $derived(Math.max(1, ...top.map((t: any) => t.count)));

  const headline = $derived(
    metric === "people" ? (data?.people?.window ?? 0) : (data?.total ?? 0),
  );
  const previous = $derived(
    metric === "people" ? (data?.people?.previous ?? 0) : (data?.previous ?? 0),
  );
  const TITLE = {
    replies: "Replies",
    people: "People talked to",
    accounts: "Activity",
  } as const;

  /**
   * Change against the window before this one.
   *
   * Growth from zero is not a percentage - it is "from nothing" - and saying
   * "up 100%" there would be arithmetic pretending to be a fact.
   */
  const delta = $derived.by(() => {
    if (!data) return null;
    if (!previous) return headline ? { kind: "new" as const } : null;
    const pct = Math.round(((headline - previous) / previous) * 100);
    if (pct === 0) return { kind: "flat" as const, pct: 0 };
    return { kind: pct > 0 ? ("up" as const) : ("down" as const), pct: Math.abs(pct) };
  });

  const busiestHour = $derived(
    data?.busiest?.hour == null ? "" : `${String(data.busiest.hour).padStart(2, "0")}:00`,
  );
  const platform = $derived(data?.platform ?? { discord: 0, snapchat: 0 });
  const bothPlatforms = $derived(platform.discord > 0 && platform.snapchat > 0);
</script>

<div
  use:portal
  class="stat-scrim fixed inset-0 z-[75] overflow-y-auto bg-black/60 p-4 backdrop-blur-sm sm:p-6"
  role="dialog"
  aria-modal="true"
  aria-label="{TITLE[metric]} in detail"
  tabindex="-1"
  onclick={(e) => e.target === e.currentTarget && onclose?.()}
  onkeydown={(e) => e.key === "Escape" && onclose?.()}
>
  <div class="glass floating glow pop mx-auto w-[min(980px,100%)] overflow-hidden rounded-2xl">
    <!-- ── Header ─────────────────────────────────────────────────────── -->
    <div class="flex flex-wrap items-center gap-3 border-b border-edge px-5 py-4">
      <div class="min-w-0 flex-1">
        <h2 class="text-[15px] font-semibold tracking-tight text-ink">{TITLE[metric]}</h2>
        <p class="mt-0.5 text-[11px] text-faint">
          Last {days} days, against the {days} before them
        </p>
      </div>
      <button
        class="jelly rounded-lg p-1.5 text-faint hover:bg-white/[0.06] hover:text-ink"
        onclick={() => onclose?.()}
        aria-label="Close"
      >
        <Icon name="close" size={15} />
      </button>
    </div>

    <!-- ── Range, in one row above everything it changes ──────────────── -->
    <div class="flex flex-wrap items-center gap-1.5 border-b border-edge/60 px-5 py-2.5">
      {#each RANGES as r}
        <button
          class="jelly rounded-lg px-2.5 py-1 text-[12px] transition-colors
                 {days === r.days ? 'bg-accent/15 text-accent' : 'text-muted hover:bg-white/[0.05] hover:text-ink'}"
          onclick={() => (days = r.days)}
        >
          {r.label}
        </button>
      {/each}
      <span class="ml-auto flex items-center gap-2">
        {#if loading && data}
          <span class="text-[11px] text-faint">checking…</span>
        {/if}
        <button
          class="jelly rounded-lg px-2.5 py-1 text-[12px] text-muted hover:bg-white/[0.05] hover:text-ink"
          onclick={() => (showTable = !showTable)}
          aria-pressed={showTable}
        >
          {showTable ? "Charts" : "Numbers"}
        </button>
      </span>
    </div>

    {#if error}
      <p class="px-5 py-8 text-center text-[13px] text-bad">{error}</p>
    {:else if loading && !data}
      <div class="space-y-3 p-5">
        {#each [0, 1, 2] as i}
          <div class="h-28 animate-pulse rounded-xl bg-white/[0.03]"></div>
        {/each}
      </div>
    {:else if data}
      <div class="space-y-5 p-5">
        <!-- ── The headline, as a figure rather than a chart ───────────── -->
        <div class="flex flex-wrap items-end gap-x-6 gap-y-3">
          <div>
            <div class="text-[11px] uppercase tracking-[0.12em] text-faint">
              {metric === "people" ? "People" : "Replies"}
            </div>
            <div class="mt-0.5 flex items-baseline gap-2.5">
              <span class="text-4xl font-semibold tabular-nums text-ink">
                {headline.toLocaleString()}
              </span>
              {#if delta?.kind === "up"}
                <span class="text-[12px] font-medium text-good">up {delta.pct}%</span>
              {:else if delta?.kind === "down"}
                <span class="text-[12px] font-medium text-muted">down {delta.pct}%</span>
              {:else if delta?.kind === "flat"}
                <span class="text-[12px] text-muted">no change</span>
              {:else if delta?.kind === "new"}
                <span class="text-[12px] text-good">first activity in this window</span>
              {/if}
            </div>
            <div class="mt-1 text-[11px] text-faint">
              {previous.toLocaleString()} in the {days} days before
            </div>
          </div>

          {#if metric === "people"}
            <div class="flex gap-6">
              <div>
                <div class="text-[11px] uppercase tracking-[0.12em] text-faint">New</div>
                <div class="mt-0.5 text-2xl font-semibold tabular-nums text-ink">
                  {(data.people?.new ?? 0).toLocaleString()}
                </div>
              </div>
              <div>
                <div class="text-[11px] uppercase tracking-[0.12em] text-faint">All time</div>
                <div class="mt-0.5 text-2xl font-semibold tabular-nums text-ink">
                  {(data.people?.all_time ?? 0).toLocaleString()}
                </div>
              </div>
            </div>
          {:else if busiestHour}
            <div>
              <div class="text-[11px] uppercase tracking-[0.12em] text-faint">Busiest hour</div>
              <div class="mt-0.5 text-2xl font-semibold tabular-nums text-ink">{busiestHour}</div>
              <div class="mt-1 text-[11px] text-faint">
                {data.busiest.hour_count.toLocaleString()} in that hour
              </div>
            </div>
          {/if}
        </div>

        {#if showTable}
          <!-- ── Numbers view ─────────────────────────────────────────── -->
          <div class="max-h-[50vh] overflow-auto rounded-xl border border-edge/60">
            <table class="w-full text-left text-[12px]">
              <thead class="sticky top-0 bg-card text-[11px] uppercase tracking-wider text-faint">
                <tr>
                  <th class="px-3 py-2 font-medium">Day</th>
                  <th class="px-3 py-2 text-right font-medium">Discord</th>
                  <th class="px-3 py-2 text-right font-medium">Snapchat</th>
                  <th class="px-3 py-2 text-right font-medium">Total</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-edge/40">
                {#each series as d, i}
                  <tr class="hover:bg-white/[0.03]">
                    <td class="px-3 py-1.5 text-muted">{dayLabels[i]}</td>
                    <td class="px-3 py-1.5 text-right tabular-nums text-ink">{d.discord}</td>
                    <td class="px-3 py-1.5 text-right tabular-nums text-ink">{d.snapchat}</td>
                    <td class="px-3 py-1.5 text-right font-medium tabular-nums text-ink">
                      {d.discord + d.snapchat}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {:else}
          <!-- ── Over time ────────────────────────────────────────────── -->
          <section>
            <h3 class="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
              Per day
            </h3>
            <StatChart values={dayTotals} labels={dayLabels} kind="area" height={160} unit="replies" />
          </section>

          <!-- Two charts rather than two colours: see the note at the top. -->
          {#if bothPlatforms}
            <section class="grid gap-4 sm:grid-cols-2">
              <div>
                <h3 class="mb-2 flex items-baseline gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
                  Discord
                  <span class="font-normal tracking-normal text-muted">{platform.discord.toLocaleString()}</span>
                </h3>
                <StatChart values={discordDaily} labels={dayLabels} kind="area" height={100} unit="replies" />
              </div>
              <div>
                <h3 class="mb-2 flex items-baseline gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
                  Snapchat
                  <span class="font-normal tracking-normal text-muted">{platform.snapchat.toLocaleString()}</span>
                </h3>
                <StatChart values={snapDaily} labels={dayLabels} kind="area" height={100} unit="replies" />
              </div>
            </section>
          {/if}

          <!-- ── Shape of a day and of a week ─────────────────────────── -->
          <section class="grid gap-4 sm:grid-cols-2">
            <div>
              <h3 class="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
                Time of day
              </h3>
              <StatChart values={hourly} labels={hourLabels} kind="bars" height={120} unit="replies" />
            </div>
            <div>
              <h3 class="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
                Day of the week
              </h3>
              <StatChart values={weekday} labels={weekdayLabels} kind="bars" height={120} unit="replies" />
            </div>
          </section>

          <!-- ── Who ──────────────────────────────────────────────────── -->
          {#if top.length}
            <section>
              <h3 class="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
                Most of it was these people
              </h3>
              <div class="space-y-1">
                {#each top as t (t.platform + t.id)}
                  <div class="group flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-white/[0.03]">
                    <span class="min-w-0 flex-1 truncate text-[13px]">
                      {#if t.platform === "discord"}
                        <UserChip id={t.id} name={t.name} />
                      {:else}
                        <span class="text-ink">{t.name}</span>
                      {/if}
                    </span>
                    <!-- The bar is the magnitude; the number beside it is the
                         value. Text keeps text colours, never the series hue. -->
                    <span class="h-1.5 w-28 shrink-0 overflow-hidden rounded-full bg-white/[0.06] sm:w-48">
                      <span class="block h-full rounded-full bg-accent"
                            style="width: {Math.max(3, (t.count / topMax) * 100)}%"></span>
                    </span>
                    <span class="w-12 shrink-0 text-right text-[12px] tabular-nums text-muted">
                      {t.count.toLocaleString()}
                    </span>
                  </div>
                {/each}
              </div>
            </section>
          {/if}
        {/if}
      </div>
    {/if}
  </div>
</div>

<style>
  .stat-scrim {
    animation: stat-fade 0.18s ease-out both;
  }
  @keyframes stat-fade {
    from { opacity: 0; }
    to { opacity: 1; }
  }
</style>
