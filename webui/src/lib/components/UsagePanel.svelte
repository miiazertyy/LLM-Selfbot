<script lang="ts">
  /**
   * What is left with each provider, and what each model has done today.
   *
   * What is left comes from the provider itself, asked as this page opens and at most every five minutes
   * (app/utils/whatsleft.py): an account's balance where a key may ask for it, otherwise the limits an answer carries.
   * What was done is counted by the runners from every answer (app/utils/usage.py), and moves live: an answer bumps its
   * model's numbers and makes its row blink (lib/modelusage.ts).
   */
  import { onDestroy, onMount } from "svelte";
  import { api } from "../api";
  import { toast } from "../stores";
  import { JOB_NAMES, loadProviders, providerById, shortModel } from "../providers";
  import { fmtDate } from "../fmt";
  import { lastUse, loadUsage, startUsageLive, usage, usageKey, type Limit, type ModelUsage } from "../modelusage";
  import { play } from "../uisound";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import FootNote from "./FootNote.svelte";
  import ProviderTile from "./ProviderTile.svelte";
  import { domino } from "../domino";

  type Money = { currency: string; left: number | null; limit?: number | null; today?: number | null; month?: number | null };
  type Left = { id: string; at: number; keys: number; plan: string; money: Money | null; meters: Limit[];
                models: { model: string; limits: Limit[] }[]; why: string; link: string };

  let left = $state<Left[]>([]);
  let asked = $state(0);
  let asking = $state(true);
  let loading = $state(true);
  let now = $state(Date.now() / 1000);
  let clock: ReturnType<typeof setInterval> | null = null;

  onMount(async () => {
    startUsageLive();
    clock = setInterval(() => (now = Date.now() / 1000), 1000);
    loadProviders().catch(() => {});
    loadUsage().catch((e: any) => toast(e?.message || "Could not read the usage", "err")).finally(() => (loading = false));
    await askThem(false);
  });
  onDestroy(() => clock && clearInterval(clock));

  async function askThem(again: boolean) {
    asking = true;
    try {
      const r: any = await api.modelsLeft(again);
      left = r.providers ?? [];
      asked = r.at ?? 0;
      if (again) play("ok");
    } catch {
      /* the counts do not depend on it */
    }
    asking = false;
    if (again) loadUsage().catch(() => {});
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
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
    return `${Math.floor(s / 86400)} days`;
  }
  const money = (v: number | null | undefined, currency = "USD") =>
    v === null || v === undefined ? "" : currency === "USD" ? `$${v.toFixed(2)}` : `${v.toFixed(2)} ${currency}`;

  const JOB_TITLE: Record<string, string> = {
    replies: "Replies", other: "Other",
    ...Object.fromEntries(Object.entries(JOB_NAMES).map(([k, v]) => [k, v.title])),
  };
  const WHAT: Record<string, string> = { requests: "Requests", tokens: "Tokens", characters: "Characters", "free-requests": "Free requests",
                                         "input-tokens": "Tokens read", "output-tokens": "Tokens written" };
  const WINDOW: Record<string, string> = { day: "today", minute: "a minute", hour: "an hour", month: "this month", second: "a second" };
  const limitLabel = (g: Limit) => `${WHAT[g.what] ?? g.what} ${WINDOW[g.window] ?? ""}`.trim();
  function tone(g: Limit): string {
    const f = g.limit ? g.remaining / g.limit : 1;
    return f < 0.1 ? "bad" : f < 0.3 ? "warn" : "ok";
  }
  const nameOf = (pid: string) => providerById(pid)?.name ?? pid;
  const WEEKDAY: Intl.DateTimeFormatOptions = { weekday: "short" };
  const dayName = (d: string, i: number, n: number) => (i === n - 1 ? "Today" : fmtDate(new Date(d + "T12:00:00"), WEEKDAY));
  const models = $derived($usage.models);
  const avgSeconds = (m: ModelUsage) => (m.today.requests ? `${(m.today.ms / m.today.requests / 1000).toFixed(1)}s` : "–");
  function jobsLine(m: ModelUsage): string {
    return Object.entries(m.jobs)
      .filter(([, n]) => n > 0)
      .sort((a, b) => b[1] - a[1])
      .map(([k, n]) => `${JOB_TITLE[k] ?? k} ${fmt(n)}`)
      .join(" · ");
  }
</script>

{#snippet gauge(lim: Limit)}
  <div class="us-gauge" data-tone={tone(lim)}>
    <div class="us-gauge-top">
      <span>{limitLabel(lim)}</span>
      <b>{fmt(lim.remaining)} <em>of {fmt(lim.limit)}</em></b>
    </div>
    <div class="us-gauge-bar"><i style="width: {Math.min(100, (lim.remaining / Math.max(1, lim.limit)) * 100)}%"></i></div>
    <!-- Nearly full, when it is full again says nothing. -->
    {#if lim.reset_at && lim.remaining < lim.limit * 0.9 && inTime(lim.reset_at)}
      <div class="us-gauge-reset">Full again in {inTime(lim.reset_at)}</div>
    {/if}
  </div>
{/snippet}

<!-- ── What is left, from each of them ──────────────────────────────────────────────── -->
<div class="us-head">
  <h3>What is left</h3>
  {#if asked && !asking}<span>Asked {ago(asked)}</span>{/if}
  <span class="us-again">
    <Button kind="ghost" size="sm" onclick={() => askThem(true)} loading={asking}>
      {#if !asking}<Icon name="refresh" size={12} />{/if}Ask again
    </Button>
  </span>
</div>

{#if asking && !left.length}
  <div class="us-providers" aria-hidden="true">
    {#each Array(2) as _}<div class="us-provider is-wait"></div>{/each}
  </div>
{:else if !left.length}
  <p class="us-none">No provider connected yet. Add one under Providers.</p>
{:else}
  <!-- The cards come in one after another, a soft note each (lib/domino.ts). -->
  <div class="us-providers domino" use:domino={{ step: 38, sound: "pluck", level: 0.5, once: true }}>
    {#each left as p (p.id)}
      <article class="us-provider">
        <header class="us-provider-head">
          <ProviderTile id={p.id} size={28} />
          <span class="us-provider-name">
            <b>{nameOf(p.id)}</b>
            <small>{[p.plan, p.keys > 1 ? `${p.keys} keys` : ""].filter(Boolean).join(" · ")}</small>
          </span>
          {#if p.money?.left !== null && p.money?.left !== undefined}
            <span class="us-money"><b>{money(p.money.left, p.money.currency)}</b><small>left</small></span>
          {/if}
        </header>

        {#if p.money?.today || p.money?.month}
          <p class="us-spent">
            {[p.money.today ? `${money(p.money.today, p.money.currency)} today` : "", p.money.month ? `${money(p.money.month, p.money.currency)} this month` : ""].filter(Boolean).join(" · ")}
          </p>
        {/if}

        {#each p.meters as lim (lim.what + lim.window)}{@render gauge(lim)}{/each}

        {#each p.models as m (m.model)}
          <div class="us-left-model">
            <span class="us-left-name" title={m.model}>{shortModel(m.model)}</span>
            <div class="us-gauges">
              {#each m.limits as lim (lim.what + lim.window)}{@render gauge(lim)}{/each}
            </div>
          </div>
        {/each}

        {#if p.why}
          <p class="us-why">
            {p.why}
            {#if p.link}<a href={p.link} target="_blank" rel="noopener noreferrer">Its page<Icon name="external" size={10} /></a>{/if}
          </p>
        {/if}
      </article>
    {/each}
  </div>
{/if}

<!-- ── What each model has done today ──────────────────────────────────────────────── -->
<div class="us-head is-second"><h3>Today</h3></div>

{#if loading && !$usage.loaded}
  <div class="us-table" aria-hidden="true">{#each Array(3) as _}<div class="us-row is-wait"></div>{/each}</div>
{:else if !models.length}
  <p class="us-none">Nothing counted yet. Every answer a model gives from now on is counted here.</p>
{:else}
  <div class="us-table domino" use:domino={{ step: 32, sound: "wind", level: 0.45, once: true }} role="table" aria-label="What each model has done today">
    <div class="us-row is-names" role="row">
      <span role="columnheader">Model</span>
      <span role="columnheader">Requests</span>
      <span role="columnheader">Tokens</span>
      <span role="columnheader">Each</span>
      <span class="us-week-name" role="columnheader">This week</span>
    </div>
    {#each models as m (m.provider + "|" + m.model)}
      {@const used = $lastUse[usageKey(m.provider, m.model)]}
      {@const peak = Math.max(1, ...m.days.map((d) => d.requests))}
      <div class="us-row" role="row" class:is-idle={!m.today.requests}>
        {#if used}{#key used}<span class="us-blink" aria-hidden="true"></span>{/key}{/if}
        <span class="us-model" role="cell">
          <ProviderTile id={m.provider} size={22} />
          <span class="us-model-text">
            <b title={m.model}>{shortModel(m.model)}</b>
            <small>
              {jobsLine(m) || (m.last_at ? `Last used ${ago(m.last_at)}` : "Not used today")}
              {#if m.today.limited || m.today.errors}
                <i>{[m.today.limited ? `${m.today.limited} rate limited` : "", m.today.errors ? `${m.today.errors} failed` : ""].filter(Boolean).join(", ")}</i>
              {/if}
            </small>
          </span>
        </span>
        <span class="us-num" role="cell">{fmt(m.today.requests)}</span>
        <!-- A voice note or speech is counted in audio, not tokens: a dash, not "0". -->
        <span class="us-num" role="cell" title="{m.today.in.toLocaleString()} read, {m.today.out.toLocaleString()} written">
          {m.today.in || m.today.out ? fmt(m.today.in + m.today.out) : "–"}
        </span>
        <span class="us-num" role="cell">{avgSeconds(m)}</span>
        <span class="us-week" role="cell" aria-label="Requests over the last {m.days.length} days: {m.days.map((d) => d.requests).join(', ')}">
          {#each m.days as d, i (d.day)}
            <span class="us-day" class:is-today={i === m.days.length - 1}
                  data-tip="{dayName(d.day, i, m.days.length)} · {d.requests.toLocaleString()} request{d.requests === 1 ? '' : 's'} · {fmt(d.tokens)} tokens">
              <i style="height: {d.requests ? Math.max(10, (d.requests / peak) * 100) : 0}%"></i>
            </span>
          {/each}
        </span>
      </div>
    {/each}
  </div>
{/if}

<FootNote class="mt-5" icon="stats">
  Asked of each provider as this page opens, at most every five minutes. Where one has no other way to say, that takes one
  tiny request, which is not counted here.
</FootNote>

<style>
  .us-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; font-size: 11.5px; color: var(--color-faint); }
  .us-head.is-second { margin-top: 18px; }
  .us-head h3 { font-size: 11px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; }
  .us-again { margin-left: auto; }
  .us-none { padding: 14px 16px; border-radius: 14px; font-size: 12.5px; color: var(--color-muted); background: rgb(255 255 255 / 0.03); }

  /* ── What is left ── */
  /* In columns rather than a grid: a provider with one line is not stretched as tall as one with six models beside it. */
  .us-providers { column-gap: 8px; column-width: 290px; }
  .us-provider {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 10px;
    margin-bottom: 8px;
    padding: 13px 14px;
    border-radius: 14px;
    break-inside: avoid;
    background: color-mix(in srgb, var(--color-accent) 5%, rgb(255 255 255 / 0.025));
  }
  .us-provider.is-wait { height: 120px; animation: us-wait 1.3s ease-in-out infinite alternate; }
  @keyframes us-wait { from { opacity: 0.45; } to { opacity: 0.9; } }
  .us-provider-head { display: flex; align-items: center; gap: 10px; }
  .us-provider-name { display: flex; min-width: 0; flex: 1; flex-direction: column; }
  .us-provider-name b { font-size: 13.5px; font-weight: 600; color: var(--color-ink); }
  .us-provider-name small { font-size: 11px; color: var(--color-faint); }
  .us-money { display: flex; flex-shrink: 0; align-items: baseline; gap: 4px; }
  .us-money b { font-size: 17px; font-weight: 650; letter-spacing: -0.01em; color: var(--color-ink); font-variant-numeric: tabular-nums; }
  .us-money small { font-size: 11px; color: var(--color-muted); }
  .us-spent { font-size: 11.5px; color: var(--color-muted); }
  .us-left-model { display: flex; flex-direction: column; gap: 5px; }
  .us-gauges { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 6px 14px; }
  .us-left-name { overflow: hidden; font-size: 12px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; color: var(--color-ink); }
  .us-gauge-top { display: flex; justify-content: space-between; gap: 8px; font-size: 11px; color: var(--color-muted); }
  .us-gauge-top b { font-weight: 600; color: var(--color-ink); font-variant-numeric: tabular-nums; }
  .us-gauge-top em { font-style: normal; font-weight: 400; color: var(--color-faint); }
  .us-gauge-bar { height: 5px; margin-top: 4px; overflow: hidden; border-radius: 999px; background: rgb(255 255 255 / 0.07); }
  .us-gauge-bar i { display: block; height: 100%; border-radius: 999px; background: var(--color-accent); transition: width 0.5s var(--swift); }
  .us-gauge[data-tone="warn"] .us-gauge-bar i { background: var(--color-warn); }
  .us-gauge[data-tone="bad"] .us-gauge-bar i { background: var(--color-bad); }
  .us-gauge-reset { margin-top: 3px; font-size: 10.5px; color: var(--color-faint); font-variant-numeric: tabular-nums; }
  .us-why { font-size: 11.5px; line-height: 1.45; color: var(--color-muted); }
  .us-why a { display: inline-flex; align-items: center; gap: 3px; margin-left: 4px; color: var(--color-accent); }
  .us-why a:hover { text-decoration: underline; }

  /* ── Today: one row a model ── */
  .us-table { display: flex; flex-direction: column; gap: 3px; }
  .us-row {
    position: relative;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 60px 60px 44px 92px;
    align-items: center;
    gap: 10px;
    min-height: 46px;
    padding: 6px 12px;
    border-radius: 11px;
    background: rgb(255 255 255 / 0.025);
  }
  .us-row.is-idle { opacity: 0.62; }
  .us-row.is-wait { animation: us-wait 1.3s ease-in-out infinite alternate; }
  .us-row.is-names { min-height: 0; padding-block: 2px; font-size: 10.5px; color: var(--color-faint); background: none; }
  .us-row.is-names span:not(:first-child) { text-align: right; }
  .us-model { display: flex; min-width: 0; align-items: center; gap: 9px; }
  .us-model-text { display: flex; min-width: 0; flex-direction: column; }
  .us-model-text b { overflow: hidden; font-size: 12.5px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; color: var(--color-ink); }
  .us-model-text small { overflow: hidden; font-size: 10.5px; text-overflow: ellipsis; white-space: nowrap; color: var(--color-faint); }
  .us-model-text i { margin-left: 4px; font-style: normal; color: var(--color-warn); }
  .us-num { font-size: 12.5px; font-weight: 600; text-align: right; color: var(--color-ink); font-variant-numeric: tabular-nums; }
  .us-week { display: flex; height: 26px; align-items: flex-end; gap: 3px; }
  .us-day { position: relative; display: flex; height: 100%; min-width: 0; flex: 1; align-items: flex-end; }
  .us-day i {
    display: block;
    width: 100%;
    border-radius: 2px;
    background: color-mix(in srgb, var(--color-accent) 40%, transparent);
    transition: height 0.4s var(--swift), background-color 0.15s ease;
  }
  .us-day.is-today i { background: var(--color-accent); }
  .us-day:hover i { background: color-mix(in srgb, var(--color-accent) 80%, white); }
  /* Which day, and its numbers, for the bar pointed at. */
  .us-day::after {
    content: attr(data-tip);
    position: absolute;
    right: 0;
    bottom: calc(100% + 6px);
    z-index: 5;
    padding: 5px 9px;
    border-radius: 8px;
    font-size: 11px;
    white-space: nowrap;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-card) 92%, black);
    opacity: 0;
    pointer-events: none;
    transform: translateY(3px);
    transition: opacity 0.12s ease, transform 0.12s ease;
  }
  .us-day:hover::after { opacity: 1; transform: none; }
  @media (max-width: 620px) {
    .us-row { grid-template-columns: minmax(0, 1fr) 52px 52px; }
    .us-row > :nth-child(n + 4):not(.us-blink), .us-week-name { display: none; }
  }

  /* An answer just came from this model. */
  .us-blink {
    position: absolute;
    inset: 0;
    border-radius: inherit;
    pointer-events: none;
    background: color-mix(in srgb, var(--color-accent) 16%, transparent);
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
  :global(:root[data-motion="off"]) .us-provider.is-wait,
  :global(:root[data-motion="off"]) .us-row.is-wait { animation: none; }
  :global(:root[data-motion="off"]) .us-day::after { transition: none; }
</style>
