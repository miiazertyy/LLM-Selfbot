<script lang="ts">
  /**
   * What each model has done today, and what is left of its limits.
   *
   * No provider lets an ordinary key ask for its usage (Groq's API has no such
   * endpoint), so the runners count every answer themselves and keep the rate
   * limit headers that came with the latest one: app/utils/usage.py. Balances
   * are shown where a provider will tell: OpenRouter's credits, DeepSeek's
   * balance. Everything moves live: an answer bumps its model's numbers and
   * makes its card blink (lib/modelusage.ts).
   */
  import { onDestroy, onMount } from "svelte";
  import { api } from "../api";
  import { toast } from "../stores";
  import { JOB_NAMES, loadProviders, providerById, shortModel } from "../providers";
  import { fmtDate } from "../fmt";
  import { lastUse, loadUsage, startUsageLive, usage, usageKey, type Limit, type ModelUsage } from "../modelusage";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import FootNote from "./FootNote.svelte";
  import ProviderTile from "./ProviderTile.svelte";
  import Num from "../dashboard/Num.svelte";
  import { domino } from "../domino";

  let balances = $state<Record<string, any>>({});
  let loading = $state(true);
  let refreshing = $state(false);
  let now = $state(Date.now() / 1000);
  let clock: ReturnType<typeof setInterval> | null = null;

  onMount(async () => {
    startUsageLive();
    clock = setInterval(() => (now = Date.now() / 1000), 1000);
    loadProviders().catch(() => {});
    await Promise.all([
      loadUsage().catch((e: any) => toast(e?.message || "Could not read the usage", "err")),
      loadBalances(false),
    ]);
    loading = false;
  });
  onDestroy(() => clock && clearInterval(clock));

  async function loadBalances(refresh: boolean) {
    try {
      balances = (await api.modelsBalances(refresh)).balances ?? {};
    } catch {
      /* the counts do not depend on it */
    }
  }

  async function refresh() {
    refreshing = true;
    await Promise.all([loadUsage().catch(() => {}), loadBalances(true)]);
    refreshing = false;
  }

  // ── Numbers people read ──────────────────────────────────────────────────
  function fmt(n: number): string {
    const a = Math.abs(n || 0);
    const trim = (x: string) => x.replace(/\.0$/, "");
    if (a >= 1e6) return trim((n / 1e6).toFixed(a >= 1e7 ? 0 : 1)) + "M";
    if (a >= 1e4) return Math.round(n / 1e3) + "k";
    if (a >= 1e3) return trim((n / 1e3).toFixed(1)) + "k";
    return String(Math.round(n || 0));
  }
  function ago(ts: number): string {
    const s = Math.max(0, now - ts);
    if (s < 5) return "just now";
    if (s < 60) return `${Math.floor(s)}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  }
  function inTime(ts: number | null): string {
    if (!ts) return "";
    const s = Math.max(0, ts - now);
    if (s < 60) return `${Math.ceil(s)}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m ${Math.floor(s % 60)}s`;
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  }
  const JOB_TITLE: Record<string, string> = {
    replies: "Replies", other: "Other",
    ...Object.fromEntries(Object.entries(JOB_NAMES).map(([k, v]) => [k, v.title])),
  };
  const WINDOW: Record<string, string> = {
    day: "today", minute: "this minute", hour: "this hour", month: "this month", second: "right now",
  };
  function limitLabel(g: Limit): string {
    const what = g.what === "requests" ? "Requests" : g.what === "tokens" ? "Tokens"
      : g.what.replace("-", " ").replace(/^./, (c) => c.toUpperCase());
    return `${what} ${WINDOW[g.window] ?? "left"}`;
  }
  function tone(g: Limit): string {
    const f = g.limit ? g.remaining / g.limit : 1;
    return f < 0.1 ? "bad" : f < 0.3 ? "warn" : "ok";
  }
  const WEEKDAY: Intl.DateTimeFormatOptions = { weekday: "short" };
  const dayName = (d: string, i: number, n: number) =>
    i === n - 1 ? "Today" : fmtDate(new Date(d + "T12:00:00"), WEEKDAY);

  // ── The page ─────────────────────────────────────────────────────────────
  const models = $derived($usage.models);
  const totals = $derived(models.reduce(
    (t, m) => ({
      requests: t.requests + m.today.requests,
      in: t.in + m.today.in,
      out: t.out + m.today.out,
      trouble: t.trouble + m.today.limited + m.today.errors,
    }),
    { requests: 0, in: 0, out: 0, trouble: 0 },
  ));
  const busiest = $derived(models.length && models[0].today.requests ? models[0] : null);

  /** By provider, busiest first; within one, the order the server sent (busiest, then most recent). */
  const groups = $derived.by(() => {
    const by = new Map<string, ModelUsage[]>();
    for (const m of models) by.set(m.provider, [...(by.get(m.provider) ?? []), m]);
    return [...by.entries()]
      .map(([pid, ms]) => ({ pid, models: ms, today: ms.reduce((n, m) => n + m.today.requests, 0) }))
      .sort((a, b) => b.today - a.today);
  });

  function balanceText(pid: string): string {
    const b = balances[pid];
    if (!b || b.kind === "error") return "";
    const usd = (v: any) => (v === null || v === undefined || v === "" ? "" : `$${Number(v).toFixed(2)}`);
    if (b.kind === "credits") {
      const parts = [];
      if (b.remaining !== null && b.remaining !== undefined) parts.push(`${usd(b.remaining)} left`);
      if (b.used_today) parts.push(`${usd(b.used_today)} today`);
      if (b.free_requests?.remaining !== null && b.free_requests?.remaining !== undefined) {
        parts.push(`${fmt(b.free_requests.remaining)} free requests left today`);
      }
      return parts.join(" · ") || (b.free_tier ? "Free tier" : "");
    }
    if (b.kind === "balance") {
      return (b.balances || []).map((x: any) => `${Number(x.total).toFixed(2)} ${x.currency}`).join(" · ")
        || (b.available ? "" : "No balance");
    }
    return "";
  }
  function avgSeconds(m: ModelUsage): string {
    return m.today.requests ? `${(m.today.ms / m.today.requests / 1000).toFixed(1)}s` : "–";
  }
  function jobsLine(m: ModelUsage): string {
    return Object.entries(m.jobs)
      .filter(([, n]) => n > 0)
      .sort((a, b) => b[1] - a[1])
      .map(([k, n]) => `${JOB_TITLE[k] ?? k} ${fmt(n)}`)
      .join(" · ");
  }
</script>

{#if loading && !$usage.loaded}
  <div class="grid gap-2 sm:grid-cols-3">
    {#each Array(3) as _}<div class="h-[86px] animate-pulse rounded-2xl bg-white/[0.03]"></div>{/each}
  </div>
  <div class="mt-3 h-64 animate-pulse rounded-2xl bg-white/[0.03]"></div>
{:else}
  <!-- ── Today, all together ───────────────────────────────────────────────── -->
  <!-- The tiles come in one after another, a soft note each, the count rolling up (lib/domino.ts, Num). -->
  <div class="us-tiles domino" use:domino={{ step: 38, sound: "pluck", level: 0.5, once: true }}>
    <div class="us-tile">
      <span class="us-tile-label">Requests today</span>
      <span class="us-tile-num"><Num value={totals.requests} /></span>
      <span class="us-tile-sub" class:is-warn={totals.trouble > 0}>
        {totals.trouble ? `${fmt(totals.trouble)} refused or failed` : "none refused"}
      </span>
    </div>
    <div class="us-tile">
      <span class="us-tile-label">Tokens today</span>
      <span class="us-tile-num">{fmt(totals.in + totals.out)}</span>
      <span class="us-tile-sub">{fmt(totals.in)} read · {fmt(totals.out)} written</span>
    </div>
    <div class="us-tile">
      <span class="us-tile-label">Busiest</span>
      {#if busiest}
        <span class="us-tile-num is-name" title={busiest.model}>{shortModel(busiest.model)}</span>
        <span class="us-tile-sub">
          {Math.round((busiest.today.requests / Math.max(1, totals.requests)) * 100)}% of today's requests
        </span>
      {:else}
        <span class="us-tile-num is-name text-faint">None yet</span>
        <span class="us-tile-sub">Nothing answered today</span>
      {/if}
    </div>
  </div>

  <div class="mb-3 mt-6 flex items-center justify-between gap-3">
    <h3 class="text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">Each model</h3>
    <Button kind="ghost" size="sm" onclick={refresh} loading={refreshing}>
      {#if !refreshing}<Icon name="refresh" size={12} />{/if}Refresh
    </Button>
  </div>

  {#if !models.length}
    <div class="us-empty">
      <span class="us-empty-mark"><Icon name="stats" size={22} /></span>
      <div class="text-[14px] font-medium text-ink">Nothing counted yet</div>
      <p class="max-w-sm text-[12px] leading-relaxed text-muted">
        Every answer a model gives from now on is counted here: requests, tokens, and what is left of its limits.
      </p>
    </div>
  {:else}
    {#each groups as g (g.pid)}
      {@const bal = balanceText(g.pid)}
      <section class="us-group">
        <header class="us-group-head">
          <ProviderTile id={g.pid} size={26} />
          <span class="text-[13px] font-semibold text-ink">{providerById(g.pid)?.name ?? g.pid}</span>
          <span class="text-[11.5px] text-faint">{fmt(g.today)} request{g.today === 1 ? "" : "s"} today</span>
          {#if bal}<span class="us-balance" title="From {providerById(g.pid)?.name ?? g.pid} itself">{bal}</span>{/if}
        </header>

        <div class="us-grid domino" use:domino={{ step: 32, sound: "wind", level: 0.45, once: true }}>
          {#each g.models as m (m.provider + "|" + m.model)}
            {@const used = $lastUse[usageKey(m.provider, m.model)]}
            {@const peak = Math.max(1, ...m.days.map((d) => d.requests))}
            <article class="us-card">
              {#if used}{#key used}<span class="us-blink" aria-hidden="true"></span>{/key}{/if}
              <div class="us-card-head">
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-[14px] font-semibold tracking-tight text-ink" title={m.model}>
                    {shortModel(m.model)}
                  </span>
                  <span class="block truncate text-[11px] text-faint">{jobsLine(m) || "Not used today"}</span>
                </span>
                {#if m.last_at}
                  <span class="us-last" class:is-recent={now - m.last_at < 60}>
                    <i></i>{ago(m.last_at)}
                  </span>
                {/if}
              </div>

              <div class="us-stats">
                <div><b>{fmt(m.today.requests)}</b><span>requests</span></div>
                <!-- A voice note or speech is counted in audio, not tokens: a dash, not "0 / 0". -->
                {#if m.today.in || m.today.out}
                  <div><b>{fmt(m.today.in)}<em>/</em>{fmt(m.today.out)}</b><span>tokens read / written</span></div>
                {:else}
                  <div><b class="text-faint">–</b><span>{m.today.requests ? "audio, not tokens" : "tokens read / written"}</span></div>
                {/if}
                <div><b>{avgSeconds(m)}</b><span>per answer</span></div>
              </div>

              <!-- The last seven days, one bar each: requests, with the tokens on hover. -->
              <div class="us-week" role="img"
                   aria-label="Requests over the last {m.days.length} days: {m.days.map((d) => d.requests).join(', ')}">
                {#each m.days as d, i (d.day)}
                  <div class="us-day" class:is-today={i === m.days.length - 1}
                       data-tip="{dayName(d.day, i, m.days.length)} · {d.requests.toLocaleString()} request{d.requests === 1 ? '' : 's'} · {fmt(d.tokens)} tokens">
                    <span class="us-bar"><i style="height: {d.requests ? Math.max(6, (d.requests / peak) * 100) : 0}%"></i></span>
                    <span class="us-day-name">{dayName(d.day, i, m.days.length)}</span>
                  </div>
                {/each}
              </div>

              {#if m.limits.length}
                <div class="us-limits">
                  {#each m.limits as lim (lim.what + lim.window)}
                    <div class="us-gauge" data-tone={tone(lim)}>
                      <div class="us-gauge-top">
                        <span>{limitLabel(lim)}{lim.keys > 1 ? `, ${lim.keys} keys` : ""}</span>
                        <span class="text-ink/85">
                          {fmt(lim.remaining)} <span class="text-faint">left of {fmt(lim.limit)}</span>
                        </span>
                      </div>
                      <div class="us-gauge-bar"><i style="width: {Math.min(100, (lim.remaining / Math.max(1, lim.limit)) * 100)}%"></i></div>
                      {#if lim.reset_at && lim.remaining < lim.limit}
                        <div class="us-gauge-reset">full again in {inTime(lim.reset_at)}</div>
                      {/if}
                    </div>
                  {/each}
                </div>
              {/if}

              {#if m.today.limited || m.today.errors}
                <p class="us-trouble">
                  <Icon name="alert" size={11} />
                  {[m.today.limited ? `${m.today.limited} rate limited` : "", m.today.errors ? `${m.today.errors} failed` : ""]
                    .filter(Boolean).join(", ")} today
                </p>
              {/if}
            </article>
          {/each}
        </div>
      </section>
    {/each}
  {/if}

  <FootNote class="mt-5" icon="stats">
    Counted by the app from every answer, across all your accounts. Providers do not let an ordinary key ask for
    its usage, so the counts start from this version. What is left comes from the latest answer's own headers, per
    model; with several keys they are added up, since the app moves to the next when one runs out.
  </FootNote>
{/if}

<style>
  .us-tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 8px;
  }
  .us-tile {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 2px;
    padding: 14px 16px;
    border-radius: 16px;
    background:
      radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, var(--color-accent) 10%, transparent), transparent 60%),
      rgb(255 255 255 / 0.025);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
  }
  .us-tile-label { font-size: 11px; color: var(--color-faint); }
  .us-tile-num {
    font-size: 26px;
    font-weight: 700;
    line-height: 1.15;
    letter-spacing: -0.02em;
    color: var(--color-ink);
    font-variant-numeric: tabular-nums;
  }
  .us-tile-num.is-name {
    overflow: hidden;
    font-size: 17px;
    line-height: 1.6;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .us-tile-sub { font-size: 11px; color: var(--color-muted); }
  .us-tile-sub.is-warn { color: var(--color-warn); }

  .us-group + .us-group { margin-top: 18px; }
  .us-group-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 10px;
    margin-bottom: 8px;
  }
  .us-balance {
    margin-left: auto;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 11px;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 12%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 25%, transparent);
  }
  .us-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
    gap: 8px;
  }
  .us-card {
    position: relative;
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 12px;
    padding: 14px;
    border-radius: 16px;
    background: rgb(255 255 255 / 0.025);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
  }
  .us-card-head { display: flex; align-items: flex-start; gap: 10px; }
  .us-last {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: var(--color-faint);
    font-variant-numeric: tabular-nums;
  }
  .us-last i { width: 6px; height: 6px; border-radius: 999px; background: var(--color-faint); }
  .us-last.is-recent { color: var(--color-good); }
  .us-last.is-recent i { background: var(--color-good); box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-good) 18%, transparent); }

  .us-stats { display: grid; grid-template-columns: 0.8fr 1.4fr 0.8fr; gap: 6px; }
  .us-stats div {
    display: flex;
    min-width: 0;
    flex-direction: column;
    padding: 8px 10px;
    border-radius: 11px;
    background: rgb(0 0 0 / 0.16);
  }
  .us-stats b {
    overflow: hidden;
    font-size: 15px;
    font-weight: 650;
    color: var(--color-ink);
    text-overflow: ellipsis;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .us-stats em { margin: 0 3px; font-style: normal; color: var(--color-faint); }
  .us-stats span { font-size: 10.5px; color: var(--color-faint); }

  .us-week { display: flex; align-items: flex-end; gap: 4px; height: 64px; }
  .us-day {
    position: relative;
    display: flex;
    height: 100%;
    min-width: 0;
    flex: 1;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }
  .us-bar { display: flex; width: 100%; flex: 1; align-items: flex-end; justify-content: center; }
  .us-bar i {
    display: block;
    width: min(100%, 22px);
    border-radius: 4px 4px 2px 2px;
    background: color-mix(in srgb, var(--color-accent) 42%, transparent);
    transition: height 0.4s var(--swift), background-color 0.15s ease;
  }
  .us-day.is-today .us-bar i { background: var(--color-accent); }
  .us-day:hover .us-bar i { background: color-mix(in srgb, var(--color-accent) 80%, white); }
  .us-day-name { font-size: 9.5px; color: var(--color-faint); }
  .us-day.is-today .us-day-name { color: var(--color-ink); }
  /* The hover layer: which day, and its numbers. */
  .us-day::after {
    content: attr(data-tip);
    position: absolute;
    bottom: calc(100% + 6px);
    left: 50%;
    z-index: 5;
    padding: 5px 9px;
    border-radius: 8px;
    font-size: 11px;
    white-space: nowrap;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-card) 92%, black);
    box-shadow: 0 8px 24px -8px rgb(0 0 0 / 0.7), inset 0 0 0 1px var(--color-edge);
    opacity: 0;
    pointer-events: none;
    transform: translate(-50%, 3px);
    transition: opacity 0.12s ease, transform 0.12s ease;
  }
  .us-day:first-child::after { left: 0; transform: translate(0, 3px); }
  .us-day:last-child::after { left: auto; right: 0; transform: translate(0, 3px); }
  .us-day:hover::after { opacity: 1; transform: translate(-50%, 0); }
  .us-day:first-child:hover::after, .us-day:last-child:hover::after { transform: none; }

  .us-limits { display: flex; flex-direction: column; gap: 9px; }
  .us-gauge-top { display: flex; justify-content: space-between; gap: 8px; font-size: 11px; color: var(--color-muted); }
  .us-gauge-bar {
    height: 6px;
    margin-top: 5px;
    overflow: hidden;
    border-radius: 999px;
    background: rgb(255 255 255 / 0.06);
  }
  .us-gauge-bar i {
    display: block;
    height: 100%;
    border-radius: 999px;
    background: var(--color-accent);
    transition: width 0.5s var(--swift);
  }
  .us-gauge[data-tone="warn"] .us-gauge-bar i { background: var(--color-warn); }
  .us-gauge[data-tone="bad"] .us-gauge-bar i { background: var(--color-bad); }
  .us-gauge-reset { margin-top: 3px; font-size: 10.5px; color: var(--color-faint); font-variant-numeric: tabular-nums; }
  .us-trouble { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--color-warn); }

  .us-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 36px 20px;
    border-radius: 18px;
    text-align: center;
    background: rgb(255 255 255 / 0.02);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 60%, transparent);
  }
  .us-empty-mark {
    display: grid;
    width: 46px;
    height: 46px;
    margin-bottom: 4px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  }

  /* An answer just came from this model. */
  .us-blink {
    position: absolute;
    inset: 0;
    border-radius: inherit;
    pointer-events: none;
    box-shadow:
      inset 0 0 0 1.5px color-mix(in srgb, var(--color-accent) 75%, transparent),
      0 0 22px -4px color-mix(in srgb, var(--color-accent) 50%, transparent);
    animation: us-blink 1.7s ease-out forwards;
  }
  @keyframes us-blink {
    0% { opacity: 0; }
    10% { opacity: 1; }
    32% { opacity: 0.2; }
    52% { opacity: 1; }
    100% { opacity: 0; }
  }
  :global(:root[data-motion="off"]) .us-blink { animation: none; opacity: 0; }
  :global(:root[data-motion="off"]) .us-day::after { transition: none; }
</style>
