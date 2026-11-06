<script lang="ts">
  /**
   * Today: how it is going, the one place the numbers live.
   *
   * The day's four figures on their wheels, the last 24 hours as bars you can sweep
   * across (the day plays its shape, a note to a bar, with that hour's count over
   * it), where the replies went, and every model that can write one, with what each
   * has done today and how much it has left. All of it counts every platform.
   */
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import Icon from "../components/Icon.svelte";
  import PlatformMark from "../components/PlatformMark.svelte";
  import ProviderTile from "../components/ProviderTile.svelte";
  import { fmtDate } from "../fmt";
  import { growIn } from "../growin";
  import type { ModelUsage } from "../modelusage";
  import { PLATFORMS, type PlatformId } from "../platforms";
  import { providerById, shortModel, type Plan } from "../providers";
  import { motionEnabled } from "../stores";
  import { play as uiPlay } from "../uisound";
  import { focusable } from "./focus";
  import { popIn } from "./motion";
  import Rolling from "./Rolling.svelte";
  import { compact, trend } from "./scenes";
  import type { PageActions } from "./types";
  import type { World } from "./world.svelte";

  let {
    world,
    act,
    tokens = 0,
    requests = 0,
    models = [],
    plan = null,
    working = null,
    driven = false,
  }: {
    world: World;
    act: PageActions;
    tokens?: number;
    requests?: number;
    models?: ModelUsage[];
    plan?: Plan | null;
    /** The model writing a reply right now: provider|model. */
    working?: string | null;
    /** Opened by hand, so its arrival is heard. On the tour it arrives quietly. */
    driven?: boolean;
  } = $props();

  const day = $derived(world.day);
  const hours = $derived(day.hourly);
  const peak = $derived(Math.max(1, ...hours.map((h) => h.count)));

  // ── The bars ─────────────────────────────────────────────────────────────
  let barsEl: HTMLElement | null = $state(null);
  /** Which hour is under the pointer or the keys. */
  let at = $state<number | null>(null);
  const hourWord = (h: number) => fmtDate(new Date(2020, 0, 1, h), { hour: "numeric" });
  function pointTo(i: number | null) {
    if (i === at) return;
    at = i;
    if (i != null && hours[i]) uiPlay("pluck", { p: hours[i].count / peak, level: hours[i].count ? 0.8 : 0.3 });
  }
  function fromPointer(e: PointerEvent) {
    const box = barsEl;
    if (!box || !hours.length) return;
    const r = box.getBoundingClientRect();
    pointTo(Math.max(0, Math.min(hours.length - 1, Math.floor(((e.clientX - r.left) / r.width) * hours.length))));
  }

  /** Grown in together, each note booked on the sound card's clock as the bars are set going. */
  let grown = $state(false);
  onMount(() => {
    const moving = get(motionEnabled);
    // The wheels (Rolling) heard as they land, when it was opened by hand.
    if (moving && driven) for (let i = 0; i < 4; i++) uiPlay("wind", { p: i / 3, delay: 440 + i * 70, level: 0.7 });
    if (!moving || !driven) {
      grown = true;
      return;
    }
    growIn(barsEl, () => hours.map((h) => h.count), () => (grown = true), 26, 0.7);
  });

  // ── Where the replies went ───────────────────────────────────────────────
  const where = $derived.by(() => {
    const rows = Object.entries(day.platform).filter(([p, n]) => n > 0 && PLATFORMS[p as PlatformId]);
    const most = Math.max(1, ...rows.map(([, n]) => n));
    return rows.sort((a, b) => b[1] - a[1]).map(([id, n]) => ({ id, n, f: n / most }));
  });
  function toPlatform(id: string) {
    world.platformFilter = id;
    act.go("accounts");
  }

  // ── The models ───────────────────────────────────────────────────────────
  // Every one that can write a reply, in the order they take over, and anything else that worked today.
  const rows = $derived.by(() => {
    const chain = plan?.replies ?? [];
    const seen = new Set(chain.map((e) => `${e.provider}|${e.model}`));
    const others = models.filter((m) => !seen.has(`${m.provider}|${m.model}`) && m.today.requests > 0);
    return [...chain.map((e, i) => ({ provider: e.provider, model: e.model, order: i + 1 })),
            ...others.map((m) => ({ provider: m.provider, model: m.model, order: 0 }))]
      .map((e) => {
        const u = models.find((m) => m.provider === e.provider && m.model === e.model);
        const limits = (u?.limits ?? []).filter((g) => g.limit > 0);
        const tight = limits.length ? limits.reduce((a, b) => (b.remaining / b.limit < a.remaining / a.limit ? b : a)) : null;
        return { ...e, u, tight, key: `${e.provider}|${e.model}` };
      });
  });
  const WINDOW: Record<string, string> = { day: "today", minute: "this minute", hour: "this hour", month: "this month", second: "now" };
  const avg = (u?: ModelUsage) => (u && u.today.requests ? `${(u.today.ms / u.today.requests / 1000).toFixed(1)}s` : "");
</script>

<div class="bpd bp-scrolls">
  <div class="bpd-nums">
    <button class="bpd-num" use:focusable={{ id: "today:replies" }} in:popIn|global={{ delay: 40 }} onclick={() => act.go("now")} title="Back to what is happening">
      <span class="bp-num"><Rolling value={day.replies} delay={160} /></span>
      <span class="bpd-label">replies{#if trend(day.replies, day.repliesBefore)}<em>{trend(day.replies, day.repliesBefore)}</em>{/if}</span>
    </button>
    <button class="bpd-num" use:focusable={{ id: "today:people" }} in:popIn|global={{ delay: 100 }} onclick={() => act.go("people")} title="Everyone it talks to">
      <span class="bp-num"><Rolling value={day.people} delay={160} /></span>
      <span class="bpd-label">people{#if trend(day.people, day.peopleBefore)}<em>{trend(day.people, day.peopleBefore)}</em>{/if}</span>
    </button>
    <div class="bpd-num" in:popIn|global={{ delay: 160 }}>
      <span class="bp-num"><Rolling value={tokens} delay={160} /></span>
      <span class="bpd-label">tokens</span>
    </div>
    <div class="bpd-num" in:popIn|global={{ delay: 220 }}>
      <span class="bp-num"><Rolling value={requests} delay={160} /></span>
      <span class="bpd-label">AI requests</span>
    </div>
  </div>

  <div class="bpd-day" in:popIn|global={{ delay: 240, from: 0.98 }}>
    <div class="bpd-bars" class:is-in={grown} bind:this={barsEl} role="img" aria-label="Replies per hour, the last 24 hours"
         onpointermove={fromPointer} onpointerleave={() => pointTo(null)}>
      {#each hours as h, i (h.hour)}
        <span class="bpd-barcell" class:is-at={at === i} class:is-now={i === hours.length - 1}
              use:focusable={{ id: `hour:${i}`, quiet: true, onfocus: () => pointTo(i) }}>
          {#if at === i}
            <span class="bpd-tip" data-edge={i < 2 ? "left" : i > hours.length - 3 ? "right" : undefined}><b>{h.count}</b> repl{h.count === 1 ? "y" : "ies"}, {hourWord(h.hour)}</span>
          {/if}
          <i style="--f: {h.count / peak}; --i: {i}"></i>
        </span>
      {/each}
    </div>
    <div class="bpd-axis">
      {#each hours as h, i (h.hour)}
        <span>{i % 6 === 5 || i === hours.length - 1 ? hourWord(h.hour) : ""}</span>
      {/each}
    </div>
  </div>

  <div class="bpd-low">
    {#if where.length}
      <section class="bpd-where" in:popIn|global={{ delay: 320, from: 0.98 }}>
        <div class="bp-label">Where it went</div>
        {#each where as p (p.id)}
          <button class="bp-row bpd-place" use:focusable={{ id: `where:${p.id}` }} onclick={() => toPlatform(p.id)} title="{PLATFORMS[p.id as PlatformId].name} accounts">
            <PlatformMark platform={p.id} size={26} />
            <span class="bpd-pname">{PLATFORMS[p.id as PlatformId].name}</span>
            <span class="bpd-pbar"><i style="--f: {p.f}"></i></span>
            <b>{p.n}</b>
          </button>
        {/each}
      </section>
    {/if}
    {#if rows.length}
      <section class="bpd-models" in:popIn|global={{ delay: 380, from: 0.98 }}>
        <div class="bp-label">Models</div>
        {#each rows as e (e.key)}
          <button class="bp-row bpd-model" class:is-idle={!e.u?.today.requests} class:is-working={working === e.key}
                  use:focusable={{ id: `model:${e.key}` }} onclick={() => act.leaveTo("settings")} title="Which model does what, in Settings">
            <ProviderTile id={e.provider} size={34} />
            <span class="bpd-mname">
              <span title={e.model}>{shortModel(e.model)}</span>
              <small>{providerById(e.provider)?.name ?? e.provider}{e.order ? ` · ${e.order === 1 ? "first choice" : `takes over ${e.order - 1 === 1 ? "next" : `after ${e.order - 1}`}`}` : ""}</small>
            </span>
            <span class="bpd-mnum"><b>{e.u?.today.requests ?? 0}</b><small>today</small></span>
            <span class="bpd-mnum"><b>{compact((e.u?.today.in ?? 0) + (e.u?.today.out ?? 0))}</b><small>tokens</small></span>
            <span class="bpd-mnum"><b>{avg(e.u) || "–"}</b><small>each</small></span>
            {#if e.tight}
              {@const f = e.tight.remaining / e.tight.limit}
              <span class="bpd-mleft" data-tone={f < 0.1 ? "bad" : f < 0.3 ? "warn" : "ok"} title="{e.tight.remaining} {e.tight.what} left {WINDOW[e.tight.window] ?? ''}">
                <span class="bpd-pbar"><i style="--f: {f}"></i></span>
                <small>{compact(e.tight.remaining)} {e.tight.what} left</small>
              </span>
            {:else}
              <span class="bpd-mleft"></span>
            {/if}
          </button>
        {/each}
      </section>
    {/if}
  </div>
</div>

<style>
  .bpd { display: flex; height: 100%; min-height: 0; flex-direction: column; gap: clamp(10px, 2vh, 26px); width: min(100%, 1820px); margin-inline: auto; padding-bottom: 8px; }
  /* Across the whole width, a quarter each, so they stand over the day under them. */
  .bpd-nums { display: grid; flex-shrink: 0; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 4px clamp(8px, 1vw, 20px); }
  .bpd-num { display: flex; flex-direction: column; padding: 4px 14px 8px; border-radius: var(--bp-r); text-align: left; color: var(--color-ink); transition: transform 0.45s var(--jelly); }
  button.bpd-num:active { transform: scale(0.97); transition-duration: 0.09s; }
  .bpd-label { display: inline-flex; align-items: baseline; gap: 9px; font-size: clamp(14px, 1vw, 18px); font-weight: 600; color: var(--bp-muted); }
  .bpd-label em { font-size: 0.86em; font-style: normal; font-weight: 700; color: var(--bp-lit); }

  /* Everything the rest leaves: a day is the thing worth a big picture of. */
  .bpd-day { display: flex; min-height: clamp(110px, 20vh, 200px); flex: 1 1 0; flex-direction: column; }
  .bpd-bars {
    display: grid;
    min-height: 0;
    flex: 1 1 0;
    grid-template-columns: repeat(24, minmax(0, 1fr));
    align-items: stretch;
    cursor: crosshair;
    touch-action: none;
  }
  .bpd-barcell { position: relative; display: flex; align-items: flex-end; justify-content: center; padding: 0 clamp(1px, 0.2vw, 4px); border-radius: 10px; }
  .bpd-barcell i {
    display: block;
    width: 100%;
    height: calc(4px + var(--f) * (100% - 4px));
    border-radius: clamp(4px, 0.5vw, 9px) clamp(4px, 0.5vw, 9px) 3px 3px;
    background: color-mix(in srgb, var(--color-accent) 42%, rgb(255 255 255 / 0.08));
    transform-origin: bottom;
    transition: background-color 0.18s ease;
  }
  .bpd-bars:not(.is-in) .bpd-barcell i { transform: scaleY(0); }
  .bpd-bars.is-in .bpd-barcell i { animation: bpd-grow 0.72s var(--spring) backwards; animation-delay: calc(var(--i) * 26ms); }
  @keyframes bpd-grow { from { transform: scaleY(0); } }
  .bpd-barcell.is-now i { background: var(--bp-lit); }
  .bpd-barcell.is-at i { background: var(--color-ink); }
  .bpd-tip {
    position: absolute;
    bottom: calc(100% + 2px);
    left: 50%;
    z-index: 3;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 12.5px;
    font-weight: 600;
    white-space: nowrap;
    color: var(--bp-muted);
    background: color-mix(in srgb, var(--color-accent) 20%, #0e0f18);
    pointer-events: none;
    transform: translateX(-50%);
  }
  .bpd-tip[data-edge="left"] { left: 0; transform: none; }
  .bpd-tip[data-edge="right"] { left: auto; right: 0; transform: none; }
  .bpd-tip b { color: var(--color-ink); font-weight: 750; }
  .bpd-axis { display: grid; grid-template-columns: repeat(24, minmax(0, 1fr)); margin-top: 5px; font-size: 12px; color: var(--bp-faint); }
  .bpd-axis span { overflow: visible; text-align: center; white-space: nowrap; }

  .bpd-low { display: grid; flex-shrink: 0; grid-template-columns: minmax(0, 1fr); gap: clamp(14px, 2.4vw, 48px); align-items: start; }
  @media (min-width: 1000px) {
    .bpd-low { grid-template-columns: minmax(260px, 0.7fr) minmax(0, 1.8fr); }
  }
  .bpd-where, .bpd-models { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
  .bpd-where .bp-label, .bpd-models .bp-label { margin: 0 0 4px 10px; }
  :global(.bpd-place) { gap: 10px; padding: 6px 10px; }
  .bpd-pname { width: 92px; flex-shrink: 0; overflow: hidden; font-size: 14px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
  .bpd-pbar { display: block; min-width: 30px; height: 5px; flex: 1; overflow: hidden; border-radius: 999px; background: var(--bp-line); }
  .bpd-pbar i { display: block; height: 100%; border-radius: 999px; background: var(--bp-lit); transform: scaleX(var(--f)); transform-origin: left; transition: transform 0.8s var(--swift); }
  :global(.bpd-place) b { min-width: 2ch; font-size: 15px; font-weight: 700; text-align: right; font-variant-numeric: tabular-nums; }

  :global(.bpd-model) { gap: clamp(10px, 1vw, 18px); padding: 6px 10px; }
  :global(.bpd-model.is-idle) { opacity: 0.62; }
  .bpd-mname { display: flex; min-width: 0; flex: 1 1 0; flex-direction: column; }
  .bpd-mname > span { overflow: hidden; font-size: clamp(14px, 1vw, 17px); font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
  :global(.bpd-model.is-working) .bpd-mname > span { color: var(--bp-lit); }
  small { font-size: 12px; font-weight: 500; color: var(--bp-faint); }
  .bpd-mname small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bpd-mnum { display: flex; width: clamp(48px, 4.2vw, 76px); flex-shrink: 0; flex-direction: column; align-items: flex-end; }
  .bpd-mnum b { font-size: clamp(14px, 1vw, 18px); font-weight: 700; font-variant-numeric: tabular-nums; }
  .bpd-mleft { display: flex; width: clamp(90px, 10vw, 170px); flex-shrink: 0; flex-direction: column; gap: 4px; }
  .bpd-mleft[data-tone="warn"] .bpd-pbar i { background: var(--color-warn); }
  .bpd-mleft[data-tone="bad"] .bpd-pbar i { background: var(--color-bad); }
  .bpd-mleft .bpd-pbar { flex: none; width: 100%; }
  .bpd-mleft small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  @media (max-width: 720px) {
    .bpd { height: auto; }
    .bpd-mleft { display: none; }
    .bpd-axis { font-size: 10px; }
  }
  :global(:root[data-motion="off"]) .bpd-barcell i { animation: none; transform: none; }
</style>
