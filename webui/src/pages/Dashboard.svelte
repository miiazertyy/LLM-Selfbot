<script lang="ts">
  import { onMount, tick } from "svelte";
  import { get } from "svelte/store";
  import { flip } from "svelte/animate";
  import { scale } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { api } from "../lib/api";
  import { DAY_MONTH, HOUR_MINUTE, fmtDate } from "../lib/fmt";
  import { subscribeLogs } from "../lib/logsocket";
  import { visiblePoll } from "../lib/poll";
  import { toast, health, dashLayout, motionEnabled } from "../lib/stores";
  import type { ChildState, WidgetInstance } from "../lib/stores";
  import { play } from "../lib/uisound";
  import Button from "../lib/components/Button.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import UndoBar from "../lib/components/UndoBar.svelte";
  import StatDetail from "../lib/components/StatDetail.svelte";
  import IssueList from "../lib/components/IssueList.svelte";
  import WidgetFrame from "../lib/dashboard/WidgetFrame.svelte";
  import WidgetBody from "../lib/dashboard/WidgetBody.svelte";
  import AddWidget from "../lib/dashboard/AddWidget.svelte";
  import { DEFAULT_TYPES, WIDGETS, initialLayout, makeInstance, normalise, placeOnSheet } from "../lib/dashboard/widgets";

  type Account = {
    id: string;
    platform?: string;
    username?: string;
    display_name?: string;
    avatar?: string;
  };

  let children = $state<ChildState[]>([]);
  let accounts = $state<Account[]>([]);
  // Numbered and timed like the Logs page's, so the widget can fold them into the same rows.
  let logs = $state<{ time: string; source: string; text: string; level: string; ts: number; id: number }[]>([]);
  let logSeq = 0;
  /** A few more lines than rows shown: the message under a line folds into it. */
  const LOG_LINES = 60;
  let loading = $state(true);
  let loadError = $state("");
  let stats = $state<any>(null);

  onMount(() => {
    load();
    // The socket only replays a backlog to whoever opens it, and it is shared
    // now, so seed the panel once here rather than refetching it every poll.
    fillLogs();
    const stopPoll = visiblePoll(load, 5000);
    const offLogs = subscribeLogs((entry) => {
      // A model's thinking is paragraphs long; the Logs page folds it, this strip has no room.
      if (entry.text && entry.level !== "think") {
        logs = [...logs.slice(-(LOG_LINES - 1)),
                { time: entry.time ?? "", source: entry.source ?? "", text: entry.text, level: entry.level ?? "info",
                  ts: entry.ts || Date.now() / 1000, id: logSeq++ }];
      }
      // A message in or a reply out ripples through the surface.
      if (entry.level === "reply" || entry.level === "recv") pulse(entry.level);
    });
    return () => {
      stopPoll();
      offLogs();
    };
  });

  async function load() {
    try {
      const [s, o, a] = await Promise.all([
        api.status(), api.statsOverview(), api.accounts(),
      ]);
      children = s.children || [];
      stats = o;
      accounts = a.accounts || [];
    } catch (e: any) {
      loadError = e?.message || "Could not load";
    } finally {
      loading = false;
    }
  }

  async function fillLogs() {
    try {
      logs = ((await api.logs(LOG_LINES)).lines || [])
        .filter((l: any) => l.level !== "think")
        .map((l: any) => ({ ...l, ts: l.ts || Date.now() / 1000, id: logSeq++ }));
    } catch {
      /* the live stream still fills this in; an empty panel is not an error */
    }
  }

  const tone = (s: string) =>
    s === "running" ? "good" : s === "crashing" ? "bad" : s === "starting" ? "warn" : "muted";

  async function action(id: string, act: string) {
    try {
      await api.accountAction(id, act);
      toast(`${act} ${id}`, "ok");
      setTimeout(load, 500);
    } catch (e: any) {
      toast(e.message || "Action failed", "err");
    }
  }

  function uptime(s: number) {
    if (!s) return ", ";
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (d) return `${d}d ${h}h`;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }

  // ── Derived figures for the tiles and charts ──────────────────────────────
  const running = $derived(children.filter((c) => c.state === "running").length);
  const replies = $derived((stats?.total ?? 0) + (stats?.total_snapchat ?? 0));
  const today = $derived(stats?.windows?.today ?? 0);
  const week = $derived(stats?.windows?.["7d"] ?? 0);

  /**
   * Hand the charts the SAME array back when the numbers have not moved.
   *
   * These rebuild on every poll, so a new identity landed on Chart's `data`
   * prop every 5 seconds forever, rebuilding its <path d> and rewriting every
   * <rect> over values that were usually unchanged.
   */
  function stable(prev: number[], next: number[]): number[] {
    if (prev.length === next.length && prev.every((v, i) => v === next[i])) return prev;
    return next;
  }
  let dailyPrev: number[] = [];
  let hourlyPrev: number[] = [];

  /** 14 days of replies, gaps filled so a quiet day reads as zero. */
  const daily = $derived.by(() => {
    const series: { day: number; count: number }[] = stats?.series ?? [];
    const today0 = Math.floor(Date.now() / 86400000);
    const counts = new Map(series.map((s) => [s.day, s.count]));
    const next = Array.from({ length: 14 }, (_, i) => counts.get(today0 - 13 + i) ?? 0);
    return (dailyPrev = stable(dailyPrev, next));
  });
  const hourly = $derived.by(() => {
    const next = (stats?.hourly ?? []).map((h: any) => h.count);
    return (hourlyPrev = stable(hourlyPrev, next));
  });
  const top = $derived(stats?.top ?? []);

  // Which figure is open in the drill-down, if any. A tile is one number; the
  // panel is what that number is made of.
  let detail = $state<"replies" | "people" | null>(null);

  const dayLabels = $derived.by(() => {
    const fmt = (d: Date) => fmtDate(d, DAY_MONTH);
    const now = Date.now();
    const back = (n: number) => new Date(now - n * 86400000);
    return [fmt(back(13)), fmt(back(7)), fmt(back(0))];
  });

  /** This week against last week, as a direction for the headline number. */
  const trend = $derived.by(() => {
    if (daily.length < 14) return null;
    const recent = daily.slice(-7).reduce((a, b) => a + b, 0);
    const prior = daily.slice(0, 7).reduce((a, b) => a + b, 0);
    if (!prior && !recent) return null;
    if (!prior) return { up: true, pct: 100 };
    const pct = Math.round(((recent - prior) / prior) * 100);
    return { up: pct >= 0, pct: Math.abs(pct) };
  });

  /** Same colouring as the Logs page, so a line reads the same in both. */
  const logColor = (level: string) =>
    level === "error" ? "text-bad"
    : level === "warn" ? "text-warn"
    : level === "reply" ? "text-good"
    : level === "recv" ? "text-accent-2"
    : "text-ink/80";

  // An update is a dot on System, not a banner across the Dashboard: nothing
  // is wrong, and a permanent card at the top of the page reads as an alert.
  const issues = $derived(
    ($health.issues ?? []).filter((i) => i.route !== "dashboard" && i.level !== "info"),
  );

  // ── The widgets ──────────────────────────────────────────────────────────
  /** Last 24 hours, one label per bar, for the tooltip. */
  const hourlyLabels = $derived(
    (stats?.hourly ?? []).map((h: any) =>
      fmtDate(h.hour * 3600000, HOUR_MINUTE)),
  );

  /** Everything the widgets draw from, loaded once here and handed down. */
  const ctx = $derived({
    children, accounts, stats, logs, running, today, week, trend,
    daily, hourly, hourlyLabels, uptime, tone, action,
    openDetail: (m: "replies" | "people") => (detail = m),
  });

  const layout = $derived(normalise($dashLayout));

  // ── One surface ──────────────────────────────────────────────────────────
  // The widgets sit on one sheet, divided by seams, not as separate cards with
  // gaps between them: a Dashboard, not a phone's home screen.
  const placed = $derived(placeOnSheet(layout));

  // ── The highlight that flows ─────────────────────────────────────────────
  // One soft shape under the widgets, following the pointer from one to the
  // next on a spring, taking each one's size as it goes, and a faint light
  // under the pointer itself. Moved with transforms and custom properties
  // written straight onto the element, not re-rendered on every move.
  let poolEl = $state<HTMLElement | null>(null);
  let flow = $state({ on: false, snap: true, x: 0, y: 0, w: 0, h: 0 });
  let hovered: HTMLElement | null = null;

  function measure(cell: HTMLElement) {
    flow = { on: true, snap: !flow.on, x: cell.offsetLeft, y: cell.offsetTop, w: cell.offsetWidth, h: cell.offsetHeight };
  }
  function track(e: PointerEvent) {
    const pool = poolEl;
    if (!pool) return;
    const r = pool.getBoundingClientRect();
    pool.style.setProperty("--mx", `${Math.round(e.clientX - r.left)}px`);
    pool.style.setProperty("--my", `${Math.round(e.clientY - r.top)}px`);
    if (arranging) {
      hovered = null;
      if (flow.on) flow = { ...flow, on: false };
      return;
    }
    const cell = (e.target as Element | null)?.closest?.(".pool-cell") as HTMLElement | null;
    if (!cell || cell === hovered || !pool.contains(cell)) return;
    hovered = cell;
    measure(cell);
  }
  function leave() {
    hovered = null;
    if (flow.on) flow = { ...flow, on: false };
  }
  // A widget folding or growing under the pointer takes the highlight with it.
  $effect(() => {
    const grid = poolEl?.querySelector(".pool-grid");
    if (!grid) return;
    const ro = new ResizeObserver(() => {
      if (hovered?.isConnected) measure(hovered);
    });
    ro.observe(grid);
    return () => ro.disconnect();
  });

  // ── Alive ────────────────────────────────────────────────────────────────
  // A message in or a reply out sends a ripple through the surface from the
  // widget it concerns, and the colour under everything brightens for a moment.
  let ripples = $state<{ id: number; x: number; y: number; kind: string }[]>([]);
  let rippleId = 0;
  let lastPulse = 0;
  let alive = $state("");
  let aliveTimer: ReturnType<typeof setTimeout> | null = null;

  function pulse(kind: "reply" | "recv") {
    const pool = poolEl;
    if (!pool || !get(motionEnabled)) return;
    const now = performance.now();
    if (now - lastPulse < 1200) return;
    lastPulse = now;
    const from = kind === "reply" ? ["figures", "activity", "accounts"] : ["waiting", "accounts", "log", "figures"];
    let cell: HTMLElement | null = null;
    for (const t of from) {
      cell = pool.querySelector<HTMLElement>(`.pool-cell[data-type="${t}"]`);
      if (cell) break;
    }
    const r = {
      id: ++rippleId,
      x: cell ? cell.offsetLeft + cell.offsetWidth / 2 : pool.offsetWidth / 2,
      y: cell ? cell.offsetTop + Math.min(cell.offsetHeight / 2, 110) : 90,
      kind,
    };
    ripples = [...ripples.slice(-2), r];
    setTimeout(() => (ripples = ripples.filter((q) => q.id !== r.id)), 1900);
    alive = kind;
    if (aliveTimer) clearTimeout(aliveTimer);
    aliveTimer = setTimeout(() => (alive = ""), 1500);
  }

  onMount(() => {
    // First visit since widgets existed: build it, from the old order if any.
    if (!Array.isArray(get(dashLayout))) dashLayout.set(initialLayout());
  });

  let arranging = $state(false);
  let adding = $state(false);
  let dragId = $state<string | null>(null);
  let overId = $state<string | null>(null);
  /** The one just added, briefly, so it glows as it lands. */
  let justAdded = $state<string | null>(null);

  const motion = (ms: number) => ($motionEnabled ? ms : 0);

  async function add(type: string) {
    const w = makeInstance(type);
    dashLayout.set([...layout, w]);
    justAdded = w.id;
    await tick();
    document.getElementById(`widget-${w.id}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setTimeout(() => { if (justAdded === w.id) justAdded = null; }, 1600);
  }

  // Taking one off keeps it for a few seconds, so a misclick is one click back.
  let removed = $state<{ w: WidgetInstance; index: number } | null>(null);
  let removedTimer: ReturnType<typeof setTimeout> | null = null;

  function remove(id: string) {
    const index = layout.findIndex((w) => w.id === id);
    if (index < 0) return;
    removed = { w: layout[index], index };
    dashLayout.set(layout.filter((w) => w.id !== id));
    if (removedTimer) clearTimeout(removedTimer);
    removedTimer = setTimeout(() => (removed = null), 7000);
  }

  function undo() {
    if (!removed) return;
    const next = [...layout];
    next.splice(Math.min(removed.index, next.length), 0, removed.w);
    dashLayout.set(next);
    removed = null;
  }

  function resetLayout() {
    dashLayout.set(DEFAULT_TYPES.map(makeInstance));
  }

  // Heard as a widget is moved: lifted, a click over each place it could go
  // (further down the sheet a little lower), and put down.
  const placeP = (id: string) => {
    const i = layout.findIndex((w) => w.id === id);
    return layout.length > 1 && i >= 0 ? i / (layout.length - 1) : 0.5;
  };
  function overCell(id: string) {
    if (overId !== id && id !== dragId) play("slot", { p: placeP(id) });
    overId = id;
  }

  function drop(targetId: string) {
    const from = dragId;
    dragId = null;
    overId = null;
    if (from) play("drop");
    if (!from || from === targetId) return;
    const moving = layout.find((w) => w.id === from);
    if (!moving) return;
    const next = layout.filter((w) => w.id !== from);
    next.splice(next.findIndex((w) => w.id === targetId), 0, moving);
    dashLayout.set(next);
  }

  /** Keyboard equivalent, so the layout is not mouse-only. */
  function move(id: string, delta: number) {
    const next = [...layout];
    const i = next.findIndex((w) => w.id === id);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    play("slot", { p: next.length > 1 ? j / (next.length - 1) : 0.5 });
    dashLayout.set(next);
  }

  /**
   * Scrolling while dragging.
   *
   * HTML drag and drop suppresses the page's own wheel scrolling for the whole
   * drag, so a widget could only ever be dropped somewhere already on screen.
   * Handling the wheel here scrolls the page under the drag.
   */
  function dragWheel(e: WheelEvent) {
    if (!dragId) return;
    e.preventDefault();
    const scroller = document.scrollingElement || document.documentElement;
    const main = document.querySelector("main");
    (main && main.scrollHeight > main.clientHeight ? main : scroller)
      .scrollBy({ top: e.deltaY, behavior: "auto" });
  }
</script>

<ErrorNote text={loadError} onretry={() => { loadError = ""; loading = true; load(); }} />

{#if loading}
  <div class="space-y-4">
    <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {#each [1, 2, 3, 4] as _}<div class="glass h-20 animate-pulse"></div>{/each}
    </div>
    <div class="glass h-48 animate-pulse"></div>
  </div>
{:else}
  <IssueList {issues} here="dashboard" />
  <!-- ── Customising ──────────────────────────────────────────────────── -->
  <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
    <p class="text-[11px] text-faint">
      {arranging ? "Drag a widget by its handle to move it, or use the arrows. The cross takes it off." : ""}
    </p>
    <div class="flex items-center gap-2">
      {#if arranging}
        <button class="text-[11px] text-faint hover:text-ink" onclick={resetLayout}>Reset layout</button>
      {/if}
      <Button size="sm" kind="ghost" onclick={() => (adding = true)}>
        <span class="inline-flex items-center gap-1.5"><Icon name="plus" size={13} />Add widget</span>
      </Button>
      <Button size="sm" kind={arranging ? "primary" : "ghost"} onclick={() => (arranging = !arranging)}>
        {arranging ? "Done" : "Customize"}
      </Button>
    </div>
  </div>

  <!-- One surface: the widgets sit on one sheet, divided by seams, with the
       colour under it drifting and a highlight flowing to whichever widget is
       pointed at. A full-width widget spans both columns, two half-width ones
       pair up, and a half-width one on its own fills its row. -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="pool" class:is-arranging={arranging} class:is-alive-reply={alive === "reply"}
       class:is-alive-recv={alive === "recv"} bind:this={poolEl} onpointermove={track} onpointerleave={leave}>
    <div class="pool-bg glass" aria-hidden="true">
      <span class="pool-blob is-a"></span>
      <span class="pool-blob is-b"></span>
      <span class="pool-blob is-c"></span>
      <span class="pool-light"></span>
      {#each ripples as r (r.id)}
        <span class="pool-ripple is-{r.kind}" style="left: {r.x}px; top: {r.y}px"></span>
      {/each}
    </div>
    <div class="pool-drop" class:is-on={flow.on && !arranging} class:is-snap={flow.snap} aria-hidden="true"
         style="transform: translate3d({flow.x}px, {flow.y}px, 0); width: {flow.w}px; height: {flow.h}px"></div>
  <div class="pool-grid grid grid-cols-1 lg:grid-cols-2">
    {#each placed as { w, wide, right, row } (w.id)}
      <!-- Each widget drops in whole as the tab opens, and is heard as it lands (cascade.ts). -->
      <div
        id="widget-{w.id}"
        data-type={w.type}
        data-rise
        data-land-sound
        class:is-top={row === 0}
        class:is-right={right}
        class="dash-cell pool-cell {wide ? 'lg:col-span-2' : ''}
          {dragId === w.id ? 'is-dragging' : ''}
          {arranging && overId === w.id && dragId !== w.id ? 'is-drop-target' : ''}
          {justAdded === w.id ? 'is-new' : ''}"
        animate:flip={{ duration: motion(380), easing: cubicOut }}
        in:scale={{ start: 0.92, opacity: 0, duration: motion(320), easing: cubicOut }}
        out:scale={{ start: 0.92, opacity: 0, duration: motion(200) }}
        role={arranging ? "listitem" : undefined}
        draggable={arranging}
        ondragstart={() => { dragId = w.id; play("lift"); }}
        ondragend={() => { if (dragId) play("release"); dragId = null; overId = null; }}
        ondragover={(e) => {
          if (!arranging || !dragId) return;
          e.preventDefault();
          overCell(w.id);
        }}
        onwheel={dragWheel}
        ondrop={(e) => { e.preventDefault(); drop(w.id); }}
      >
        {#if arranging}
          <div class="mb-1 flex justify-end gap-1 px-1">
            <button class="rounded px-1.5 py-0.5 text-[11px] text-faint hover:bg-white/5 hover:text-ink"
                    onclick={() => move(w.id, -1)} aria-label="Move {WIDGETS[w.type]?.title} up">Up</button>
            <button class="rounded px-1.5 py-0.5 text-[11px] text-faint hover:bg-white/5 hover:text-ink"
                    onclick={() => move(w.id, 1)} aria-label="Move {WIDGETS[w.type]?.title} down">Down</button>
          </div>
        {/if}
        <WidgetFrame inst={w} {arranging} onremove={() => remove(w.id)}>
          <WidgetBody inst={w} {ctx} />
        </WidgetFrame>
      </div>
    {/each}

    {#if !layout.length}
      <div class="flex flex-col items-center gap-3 px-6 py-12 text-center lg:col-span-2">
        <span class="text-faint"><Icon name="dashboard" size={22} /></span>
        <p class="text-[13px] text-muted">The Dashboard is empty.</p>
        <div class="flex gap-2">
          <Button size="sm" onclick={() => (adding = true)}>Add a widget</Button>
          <Button size="sm" kind="ghost" onclick={resetLayout}>Bring back the defaults</Button>
        </div>
      </div>
    {/if}
  </div>
  </div>
{/if}

<!-- A misclick is one click back: centred along the bottom, the time left
     running down around the undo arrow. -->
<UndoBar what={removed ? (WIDGETS[removed.w.type]?.title ?? "") : ""} key={removed?.w.id ?? ""}
         ms={7000} onundo={undo} />

<AddWidget bind:open={adding} {layout} {ctx} onadd={add} />

{#if detail}
  <StatDetail metric={detail} onclose={() => (detail = null)} />
{/if}

<style>
  /* ── The surface ─────────────────────────────────────────────────────────
     One sheet for every widget. Its look (the glass, the colour drifting in
     it, the ripples) lives in a layer of its own, clipped to the sheet's
     rounded shape; the widgets are not clipped, so a widget's settings menu
     can hang past the edge. */
  .pool {
    position: relative;
    border-radius: 22px;
    isolation: isolate;
  }
  .pool-bg {
    position: absolute;
    inset: 0;
    z-index: -1;
    overflow: hidden;
    border-radius: 22px;
  }

  /* The colour under everything: three soft washes of the theme's colours,
     drifting slowly and never in step, so the sheet is never quite still. */
  .pool-blob {
    position: absolute;
    width: 62%;
    aspect-ratio: 1;
    border-radius: 999px;
    filter: blur(70px);
    opacity: 0.16;
    will-change: transform;
    transition: opacity 1.2s var(--swift);
  }
  .pool-blob.is-a {
    left: -16%;
    top: -18%;
    background: var(--color-accent);
    animation: pool-drift-a 28s ease-in-out infinite alternate;
  }
  .pool-blob.is-b {
    right: -22%;
    top: 18%;
    background: var(--color-accent-2);
    opacity: 0.13;
    animation: pool-drift-b 34s ease-in-out infinite alternate;
  }
  .pool-blob.is-c {
    left: 18%;
    bottom: -26%;
    background: var(--color-good);
    opacity: 0.07;
    animation: pool-drift-c 40s ease-in-out infinite alternate;
  }
  @keyframes pool-drift-a {
    50% { transform: translate3d(38%, 22%, 0) scale(1.22); }
    100% { transform: translate3d(12%, 48%, 0) scale(0.92); }
  }
  @keyframes pool-drift-b {
    50% { transform: translate3d(-30%, 30%, 0) scale(0.9); }
    100% { transform: translate3d(-12%, -20%, 0) scale(1.18); }
  }
  @keyframes pool-drift-c {
    50% { transform: translate3d(30%, -24%, 0) scale(1.15); }
    100% { transform: translate3d(-24%, -8%, 0) scale(1); }
  }
  /* A reply going out warms the sheet; a message coming in cools it. */
  .pool.is-alive-reply .pool-blob.is-c { opacity: 0.2; }
  .pool.is-alive-reply .pool-blob.is-a { opacity: 0.24; }
  .pool.is-alive-recv .pool-blob.is-b { opacity: 0.26; }

  /* A faint light under the pointer, moved by a transform only. */
  .pool-light {
    position: absolute;
    left: -380px;
    top: -380px;
    width: 760px;
    height: 760px;
    border-radius: 999px;
    background: radial-gradient(circle, color-mix(in srgb, var(--color-accent) 11%, transparent), transparent 62%);
    transform: translate3d(var(--mx, -2000px), var(--my, -2000px), 0);
    opacity: 0;
    transition: opacity 0.5s var(--swift);
    will-change: transform;
  }
  .pool:hover .pool-light { opacity: 1; }

  /* The ripple: a ring spreading from the widget the message was about. */
  .pool-ripple {
    position: absolute;
    width: 60px;
    height: 60px;
    margin: -30px 0 0 -30px;
    border-radius: 999px;
    border: 2px solid var(--color-accent);
    opacity: 0;
    animation: pool-ripple 1.8s cubic-bezier(0.1, 0.7, 0.3, 1) both;
  }
  .pool-ripple.is-reply { border-color: var(--color-good); }
  .pool-ripple.is-recv { border-color: var(--color-accent-2); }
  @keyframes pool-ripple {
    0% { opacity: 0.55; transform: scale(0.2); }
    100% { opacity: 0; transform: scale(16); }
  }

  /* The highlight that flows: it travels on a spring, and its size catches up
     a little faster than its place, so moving between widgets of different
     sizes it stretches and settles like a drop. Appearing, it fades in where
     it is, rather than flying in from wherever it last was. */
  .pool-drop {
    position: absolute;
    left: 0;
    top: 0;
    z-index: 0;
    border-radius: 18px;
    background: radial-gradient(120% 100% at 50% 0%,
      color-mix(in srgb, var(--color-accent) 9%, transparent),
      color-mix(in srgb, var(--color-accent) 2.5%, transparent));
    box-shadow:
      inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 20%, transparent),
      0 14px 44px -20px color-mix(in srgb, var(--color-accent) 55%, transparent);
    opacity: 0;
    pointer-events: none;
    transition:
      transform 0.62s cubic-bezier(0.2, 1.3, 0.35, 1),
      width 0.5s cubic-bezier(0.2, 1.22, 0.35, 1),
      height 0.5s cubic-bezier(0.2, 1.22, 0.35, 1),
      opacity 0.3s var(--swift);
  }
  .pool-drop.is-on { opacity: 1; }
  .pool-drop.is-snap { transition: opacity 0.3s var(--swift); }

  .pool-grid {
    position: relative;
    z-index: 1;
  }

  /* ── Seams ───────────────────────────────────────────────────────────────
     Where one widget meets the next: a hairline that fades out at both ends,
     so the widgets read as parts of one thing rather than boxes side by side. */
  .pool-cell { position: relative; }
  .pool-cell::before {
    content: "";
    position: absolute;
    top: 0;
    left: 20px;
    right: 20px;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgb(255 255 255 / 0.08) 14%, rgb(255 255 255 / 0.08) 86%, transparent);
    pointer-events: none;
  }
  .pool-cell:first-child::before { display: none; }
  @media (min-width: 1024px) {
    .pool-cell.is-top::before { display: none; }
    .pool-cell.is-right::after {
      content: "";
      position: absolute;
      top: 20px;
      bottom: 20px;
      left: 0;
      width: 1px;
      background: linear-gradient(180deg, transparent, rgb(255 255 255 / 0.08) 14%, rgb(255 255 255 / 0.08) 86%, transparent);
      pointer-events: none;
    }
  }

  /* Customising: each widget outlined, so where one ends and a drop lands is plain. */
  .pool.is-arranging .pool-cell {
    outline: 1px dashed rgb(255 255 255 / 0.14);
    outline-offset: -6px;
    border-radius: 18px;
  }

  :global(:root[data-motion="off"]) .pool-blob,
  :global(:root[data-motion="off"]) .pool-ripple { animation: none; }
  :global(:root[data-motion="off"]) .pool-drop,
  :global(:root[data-motion="off"]) .pool-light { transition: none; }
</style>
