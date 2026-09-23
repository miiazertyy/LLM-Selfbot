<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { subscribeLogs } from "../lib/logsocket";
  import { visiblePoll } from "../lib/poll";
  import { toast, health, dashOrder } from "../lib/stores";
  import type { ChildState } from "../lib/stores";
  import Card from "../lib/components/Card.svelte";
  import Badge from "../lib/components/Badge.svelte";
  import Button from "../lib/components/Button.svelte";
  import Empty from "../lib/components/Empty.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import Chart from "../lib/components/Chart.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import UserChip from "../lib/components/UserChip.svelte";
  import Avatar from "../lib/components/Avatar.svelte";

  type Account = {
    id: string;
    platform?: string;
    username?: string;
    display_name?: string;
    avatar?: string;
  };

  let children = $state<ChildState[]>([]);
  let accounts = $state<Account[]>([]);
  let logs = $state<{ time: string; source: string; text: string; level: string }[]>([]);
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
      if (entry.text) logs = [...logs.slice(-39), entry];
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
      logs = (await api.logs(40)).lines || [];
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

  const dayLabels = $derived.by(() => {
    const fmt = (d: Date) => d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
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

  // ── Rearranging the page ──────────────────────────────────────────────────
  /**
   * Which sections exist, and how wide each one wants to be. The saved order
   * is reconciled against this on every render: ids that no longer exist are
   * dropped, and new ones are appended, so a future section cannot silently
   * disappear for anyone who has already dragged things around.
   */
  const SECTIONS: Record<string, { title: string; wide: boolean }> = {
    figures: { title: "Headline figures", wide: true },
    activity: { title: "Activity", wide: true },
    accounts: { title: "Accounts", wide: true },
    people: { title: "Most active people", wide: false },
    log: { title: "Live log", wide: false },
  };

  const order = $derived.by(() => {
    const known = Object.keys(SECTIONS);
    const saved = ($dashOrder ?? []).filter((id) => known.includes(id));
    return [...saved, ...known.filter((id) => !saved.includes(id))];
  });

  let arranging = $state(false);
  let dragId = $state<string | null>(null);
  let overId = $state<string | null>(null);

  function drop(targetId: string) {
    const from = dragId;
    dragId = null;
    overId = null;
    if (!from || from === targetId) return;
    const next = order.filter((id) => id !== from);
    next.splice(next.indexOf(targetId), 0, from);
    dashOrder.set(next);
  }

  /**
   * Scrolling while dragging.
   *
   * HTML drag and drop suppresses the page's own wheel scrolling for the whole
   * drag, so a section could only ever be dropped somewhere already on screen:
   * moving the log above the figures meant dragging, giving up, scrolling, and
   * starting again. Handling the wheel here scrolls the page under the drag.
   */
  function dragWheel(e: WheelEvent) {
    if (!dragId) return;
    e.preventDefault();
    const scroller = document.scrollingElement || document.documentElement;
    // The main column scrolls, not the window, in the app shell.
    const main = document.querySelector("main");
    (main && main.scrollHeight > main.clientHeight ? main : scroller)
      .scrollBy({ top: e.deltaY, behavior: "auto" });
  }

  /** Keyboard equivalent, so the layout is not mouse-only. */
  function nudge(id: string, delta: number) {
    const next = [...order];
    const i = next.indexOf(id);
    const j = i + delta;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    dashOrder.set(next);
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
  {#if issues.length}
    <div class="mb-4 space-y-2">
      {#each issues as issue}
        <button
          onclick={() => (window.location.hash = `/${issue.route}`)}
          class="jelly flex w-full items-start gap-3 rounded-xl border px-4 py-3 text-left
            {issue.level === 'error'
              ? 'border-bad/40 bg-bad/[0.07]'
              : 'border-warn/40 bg-warn/[0.06]'}"
        >
          <span class="mt-1.5 h-2 w-2 shrink-0 rounded-full {issue.level === 'error' ? 'bg-bad' : issue.level === 'info' ? 'bg-accent' : 'bg-warn'}"></span>
          <span class="min-w-0 flex-1">
            <span class="block text-[13px] font-medium text-ink">{issue.title}</span>
            <span class="mt-0.5 block text-[11px] leading-relaxed text-muted">{issue.detail}</span>
          </span>
          <span class="mt-0.5 shrink-0 text-[11px] text-faint">Fix →</span>
        </button>
      {/each}
    </div>
  {/if}
  <!-- ── Rearranging ──────────────────────────────────────────────────── -->
  <div class="mb-3 flex items-center justify-between gap-3">
    <p class="text-[11px] text-faint">
      {arranging ? "Drag a section by its handle to move it." : ""}
    </p>
    <div class="flex items-center gap-2">
      {#if arranging}
        <button
          class="text-[11px] text-faint hover:text-ink"
          onclick={() => dashOrder.set(["figures", "activity", "accounts", "people", "log"])}
        >Reset order</button>
      {/if}
      <Button size="sm" kind="ghost" onclick={() => (arranging = !arranging)}>
        {arranging ? "Done" : "Rearrange"}
      </Button>
    </div>
  </div>

  <!-- Sections live in one grid: a wide one spans both columns, so the two
       narrow ones pair up whenever they end up next to each other, whatever
       order they are dragged into. -->
  <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
    {#each order as id (id)}
      <div
        class="transition-opacity {SECTIONS[id].wide ? 'lg:col-span-2' : ''}
          {arranging ? 'rounded-2xl border border-dashed p-2' : ''}
          {arranging && overId === id && dragId !== id ? 'border-accent bg-accent/[0.04]' : 'border-edge'}
          {dragId === id ? 'opacity-40' : ''}"
        role={arranging ? "listitem" : undefined}
        draggable={arranging}
        ondragstart={() => (dragId = id)}
        ondragend={() => {
          dragId = null;
          overId = null;
        }}
        ondragover={(e) => {
          if (!arranging || !dragId) return;
          e.preventDefault();
          overId = id;
        }}
        onwheel={dragWheel}
        ondrop={(e) => {
          e.preventDefault();
          drop(id);
        }}
      >
        {#if arranging}
          <div class="mb-2 flex items-center gap-2 px-1">
            <span class="cursor-grab text-faint active:cursor-grabbing"><Icon name="grip" size={14} /></span>
            <span class="flex-1 text-[11px] font-medium text-muted">{SECTIONS[id].title}</span>
            <button class="rounded px-1.5 py-0.5 text-[11px] text-faint hover:bg-white/5 hover:text-ink"
                    onclick={() => nudge(id, -1)} aria-label="Move up">Up</button>
            <button class="rounded px-1.5 py-0.5 text-[11px] text-faint hover:bg-white/5 hover:text-ink"
                    onclick={() => nudge(id, 1)} aria-label="Move down">Down</button>
          </div>
        {/if}

        <!-- ── Headline figures ───────────────────────────────────────── -->
        {#if id === "figures"}
          <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div class="glass p-4">
              <div class="text-[11px] uppercase tracking-[0.12em] text-faint">Accounts up</div>
              <div class="mt-1 flex items-baseline gap-1.5">
                <span class="text-2xl font-semibold text-ink">{running}</span>
                <span class="text-[12px] text-muted">of {children.length}</span>
              </div>
            </div>
            <div class="glass p-4">
              <div class="text-[11px] uppercase tracking-[0.12em] text-faint">Replies today</div>
              <div class="mt-1 flex items-baseline gap-2">
                <span class="text-2xl font-semibold text-ink">{today.toLocaleString()}</span>
                {#if trend}
                  <span class="text-[11px] {trend.up ? 'text-good' : 'text-muted'}">
                    {trend.up ? "up" : "down"} {trend.pct}%
                  </span>
                {/if}
              </div>
            </div>
            <div class="glass p-4">
              <div class="text-[11px] uppercase tracking-[0.12em] text-faint">This week</div>
              <div class="mt-1 text-2xl font-semibold text-ink">{week.toLocaleString()}</div>
            </div>
            <div class="glass p-4">
              <div class="text-[11px] uppercase tracking-[0.12em] text-faint">People talked to</div>
              <div class="mt-1 flex items-baseline gap-1.5">
                <span class="text-2xl font-semibold text-ink">{(stats?.people ?? 0).toLocaleString()}</span>
                <span class="text-[12px] text-muted">{stats?.people_7d ?? 0} this week</span>
              </div>
            </div>
          </div>

        <!-- ── Activity ───────────────────────────────────────────────── -->
        {:else if id === "activity"}
          <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div class="lg:col-span-2">
              <Card title="Replies over the last 14 days" subtitle="{replies.toLocaleString()} all time">
                <Chart data={daily} kind="area" height={130} labels={dayLabels} />
              </Card>
            </div>
            <Card title="Last 24 hours">
              <Chart data={hourly} kind="bars" height={130} accent="var(--color-accent-2)"
                     labels={["24h ago", "12h", "now"]} />
            </Card>
          </div>

        <!-- ── Accounts ───────────────────────────────────────────────── -->
        {:else if id === "accounts"}
          <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h2 class="text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">Accounts</h2>
            <Button
              kind="danger"
              size="sm"
              onclick={async () => {
                try {
                  await api.serviceAction("kill_switch", "stop");
                  toast("Paused every account.", "ok");
                } catch (e: any) {
                  toast(e.message, "err");
                }
              }}
            >
              Pause all
            </Button>
          </div>

          <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {#each children as c}
              {@const acct = accounts.find((a) => a.id === c.id)}
              <Card>
                <div class="flex items-start gap-3">
                  <!-- The real avatar once the account has connected at least once. -->
                  {#if acct?.avatar}
                    <Avatar src={acct.avatar}
                            name={acct?.display_name || acct?.username || c.label} size={40} />
                  {:else}
                    <span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-muted">
                      <Icon name={c.role === "snapchat" ? "snapchat" : c.role === "telegram" ? "chats" : "accounts"} size={17} />
                    </span>
                  {/if}
                  <div class="min-w-0 flex-1">
                    <div class="truncate text-sm font-semibold text-ink">
                      {acct?.display_name || acct?.username || c.label}
                    </div>
                    <div class="truncate text-xs text-muted">
                      {#if acct?.username}@{acct.username} &middot; {/if}{c.role === "discord" ? "Discord" : c.role === "snapchat" ? "Snapchat" : "Telegram"}
                    </div>
                  </div>
                  <Badge tone={tone(c.state)}>{c.state}</Badge>
                </div>

                <div class="mt-4 grid grid-cols-3 gap-2 text-center">
                  <div class="rounded-lg bg-white/5 py-2">
                    <div class="text-sm font-semibold">{uptime(c.uptime)}</div>
                    <div class="text-[10px] text-muted">uptime</div>
                  </div>
                  <div class="rounded-lg bg-white/5 py-2">
                    <div class="text-sm font-semibold">{c.pid ?? "none"}</div>
                    <div class="text-[10px] text-muted">pid</div>
                  </div>
                  <div class="rounded-lg bg-white/5 py-2">
                    <div class="text-sm font-semibold {c.restarts ? 'text-warn' : ''}">{c.restarts}</div>
                    <div class="text-[10px] text-muted">restarts</div>
                  </div>
                </div>

                <div class="mt-4 flex flex-wrap gap-2">
                  <Button kind="ghost" size="sm" onclick={() => action(c.id, "start")}>Start</Button>
                  <Button kind="ghost" size="sm" onclick={() => action(c.id, "stop")}>Stop</Button>
                  <Button kind="ghost" size="sm" onclick={() => action(c.id, "restart")}>Restart</Button>
                  <Button kind="ghost" size="sm" onclick={() => action(c.id, "pause")}>Pause</Button>
                </div>
              </Card>
            {:else}
              <div class="md:col-span-2 xl:col-span-3">
                <Empty text="No accounts running. Add one on the Accounts page, then start it here." icon="accounts" />
              </div>
            {/each}
          </div>

        <!-- ── Most active people ─────────────────────────────────────── -->
        {:else if id === "people"}
          <Card title="Most active people" subtitle="last 7 days">
            {#if top.length}
              <div class="space-y-2.5">
                {#each top as t, i}
                  <div class="flex items-center gap-3">
                    <span class="w-4 shrink-0 text-[11px] text-faint">{i + 1}</span>
                    <span class="min-w-0 flex-1 truncate">
                      <UserChip id={t.user_id} name={t.username} />
                    </span>
                    <!-- Bar width is relative to the busiest person, so the
                         ranking reads at a glance without comparing numbers. -->
                    <span class="h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-white/[0.06] sm:w-24">
                      <span class="block h-full rounded-full bg-accent"
                            style="width: {Math.round((t.count / Math.max(1, top[0].count)) * 100)}%"></span>
                    </span>
                    <span class="w-8 shrink-0 text-right text-[12px] font-medium text-muted">{t.count}</span>
                  </div>
                {/each}
              </div>
            {:else}
              <p class="py-4 text-center text-[12px] text-faint">No conversations recorded yet.</p>
            {/if}
          </Card>

        <!-- ── Live log ───────────────────────────────────────────────── -->
        {:else if id === "log"}
          <Card title="Live log">
            {#snippet actions()}
              <button class="text-[11px] text-faint hover:text-accent"
                      onclick={() => (window.location.hash = "/logs")}>Open logs</button>
            {/snippet}
            <div class="h-56 overflow-y-auto rounded-lg bg-black/40 p-3 font-mono text-[11px] leading-relaxed">
              {#each logs as l}
                <div class="flex gap-2">
                  <span class="shrink-0 text-muted">{l.time}</span>
                  <span class="shrink-0 text-accent">{l.source}</span>
                  <span class="break-all {logColor(l.level)}">{l.text}</span>
                </div>
              {:else}
                <span class="text-muted">Waiting for output.</span>
              {/each}
            </div>
          </Card>
        {/if}
      </div>
    {/each}
  </div>
{/if}
