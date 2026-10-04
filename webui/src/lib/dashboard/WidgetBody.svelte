<script lang="ts">
  /**
   * What each Dashboard widget draws.
   *
   * One component switching on type, with the one big widget (Accounts) in a
   * file of its own. The Dashboard already polls the accounts, the overview
   * stats and the log, and hands them down as `ctx`. Widgets that need a window
   * of their own (30 or 90 days) read the stats detail for it, shared through
   * resource() so two widgets on the same window cost one request.
   *
   * Every widget lays itself out by its own width (the frame is a CSS
   * container), not the window's. They used the window's breakpoints, so a
   * half-width widget still split into two columns and left half of itself
   * empty, and making one full width changed nothing inside it.
   *
   * And each one says what it means, not just what it counted: the busiest
   * hour rather than 24 bars to squint at, how long someone has been waiting,
   * whether this week is up on the last.
   */
  import { api } from "../api";
  import { toast, health } from "../stores";
  import type { WidgetInstance } from "../stores";
  import { resource } from "../resource";
  import { visiblePoll } from "../poll";
  import { chatCache, chatAccounts, replying, sendReply } from "../chats";
  import Badge from "../components/Badge.svelte";
  import Icon from "../components/Icon.svelte";
  import { DAY_MONTH, fmtDate } from "../fmt";
  import StatChart from "../components/StatChart.svelte";
  import UserChip from "../components/UserChip.svelte";
  import Avatar from "../components/Avatar.svelte";
  import MentionText from "../components/MentionText.svelte";
  import RankBadge from "../components/RankBadge.svelte";
  import { arriving } from "../growin";
  import Spark from "./Spark.svelte";
  import Num from "./Num.svelte";
  import AccountsWidget from "./AccountsWidget.svelte";
  import LogWidget from "./LogWidget.svelte";

  let { inst, ctx }: { inst: WidgetInstance; ctx: any } = $props();

  const opt = (k: string) => inst.options?.[k];
  const days = $derived(Number(opt("days") ?? 30));

  // ── A window of its own, for the widgets that have one ─────────────────────
  const WANTS_DETAIL = ["activity", "people", "hours", "weekdays", "platforms"];
  let det = $state<any>(null);
  $effect(() => {
    if (!WANTS_DETAIL.includes(inst.type)) return;
    const r = resource<any>(`dashDetail${days}`, () => api.statsDetail(days), null);
    const off = r.subscribe((s) => (det = s.data));
    r.refresh({ maxAge: 60_000 });
    const stop = visiblePoll(() => r.refresh({ maxAge: 55_000 }), 60_000);
    return () => {
      off();
      stop();
    };
  });

  const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const DOW_LONG = ["Sundays", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays"];
  const fmtDay = (d: number) => fmtDate(d * 86400000, DAY_MONTH);
  const hh = (h: number) => `${String(h).padStart(2, "0")}:00`;
  const n = (v: number) => Number(v || 0).toLocaleString();
  const argmax = (a: number[]) => (a.length ? a.indexOf(Math.max(...a)) : -1);
  const argmin = (a: number[]) => (a.length ? a.indexOf(Math.min(...a)) : -1);

  const series = $derived<any[]>(det?.series ?? []);
  const perDay = $derived(series.map((d) => d.discord + d.snapchat));
  const perDayLabels = $derived(series.map((d) => fmtDay(d.day)));
  const hours = $derived<number[]>((det?.hourly ?? []).map((h: any) => h.count));
  const hourLabels = $derived<string[]>((det?.hourly ?? []).map((h: any) => hh(h.hour)));
  const weekdays = $derived<number[]>((det?.weekday ?? []).map((w: any) => w.count));
  const weekdayLabels = $derived<string[]>((det?.weekday ?? []).map((w: any) => DOW[w.day] ?? ""));

  /** "+12%", "−30%", "new", or "" when there is nothing to compare. */
  function change(now: number, before: number): { text: string; up: boolean } | null {
    if (!now && !before) return null;
    if (!before) return { text: "new", up: true };
    const pct = Math.round(((now - before) / before) * 100);
    return { text: `${pct >= 0 ? "+" : "−"}${Math.abs(pct)}%`, up: pct >= 0 };
  }

  // ── Headline figures ───────────────────────────────────────────────────────
  // The workers the figures are about. Telegram is a controller, not an
  // account, and counting it made "2 of 3 up" out of two accounts.
  const workers = $derived((ctx.children ?? []).filter((c: any) => c.role !== "telegram"));
  const upCount = $derived(workers.filter((c: any) => c.state === "running").length);
  const upLine = $derived.by(() => {
    const crashing = workers.filter((c: any) => c.state === "crashing").length;
    const stopped = workers.filter((c: any) => c.state === "stopped").length;
    if (!workers.length) return "none added yet";
    if (crashing) return `${crashing} crashing`;
    if (stopped) return `${stopped} stopped`;
    return upCount === workers.length ? "all running" : "starting";
  });
  const stateDot = (s: string) =>
    s === "running" ? "bg-good" : s === "crashing" ? "bg-bad" : s === "starting" ? "bg-warn" : "bg-white/20";
  const nameOf = (c: any) => {
    const a = (ctx.accounts ?? []).find((x: any) => x.id === c.id);
    return a?.display_name || a?.username || c.label;
  };

  // ── Waiting for a reply, across every account ──────────────────────────────
  const waiting = $derived.by(() => {
    const out: any[] = [];
    for (const [target, entry] of Object.entries($chatCache)) {
      const acct = $chatAccounts.find((a) => a.id === target);
      for (const u of (entry as any).users ?? []) out.push({ ...u, target, account: acct });
    }
    // Longest wait first; a ts of 0 means it arrived this session.
    return out.sort((a, b) => (a.ts || Infinity) - (b.ts || Infinity));
  });
  let now = $state(Date.now() / 1000);
  $effect(() => {
    if (inst.type !== "waiting") return;
    const t = setInterval(() => (now = Date.now() / 1000), 30_000);
    return () => clearInterval(t);
  });
  function waited(ts: number): string {
    if (!ts) return "just now";
    const s = Math.max(0, now - ts);
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
    if (s < 86400) return `${Math.round(s / 3600)} h`;
    return `${Math.round(s / 86400)} d`;
  }
  async function reply(u: any) {
    try {
      const res: any = await sendReply(u.target, String(u.id));
      if (res && res.ok === false) toast(res.reason || `Could not reply to ${u.name}`, "err");
      else if (res) toast(`Replied to ${u.name}`, "ok");
    } catch (e: any) {
      toast(e?.message || `Could not reply to ${u.name}`, "err");
    }
  }

  function go(route: string) {
    window.location.hash = `/${route}`;
  }

  // ── Quick actions, with what is behind each ────────────────────────────────
  const memory = resource<any>("memory", () => api.memory(), { users: [] });
  const logErrors = $derived((ctx.logs ?? []).filter((l: any) => l.level === "error").length);
  const settingsIssues = $derived(($health.issues ?? []).filter((i) => i.route === "settings").length);

  async function pauseToggle() {
    try {
      await api.serviceAction("kill_switch", "stop");
      toast("Paused or resumed every account.", "ok");
    } catch (e: any) {
      toast(e.message, "err");
    }
  }
</script>

<!-- ── Headline figures ─────────────────────────────────────────────────── -->
{#if inst.type === "figures"}
  {@const hourly = (ctx.hourly ?? []) as number[]}
  {@const week7 = ((ctx.daily ?? []) as number[]).slice(-7)}
  <div class="figs grid grid-cols-2 @2xl:grid-cols-4">
    <button class="fig" onclick={() => go("accounts")} title="Open Accounts">
      <span class="fig-l">Accounts up <span class="fig-go"><Icon name="chevron" size={11} /></span></span>
      <span class="fig-row">
        <span class="fig-n"><Num value={upCount} /><span class="fig-of">/{workers.length}</span></span>
        <span class="flex flex-wrap justify-end gap-1">
          {#each workers as c (c.id)}
            <span class="h-2 w-2 rounded-full {stateDot(c.state)}" title="{nameOf(c)}: {c.state}"></span>
          {/each}
        </span>
      </span>
      <span class="fig-sub {upLine.includes('crashing') ? 'text-bad' : ''}">{upLine}</span>
    </button>
    <button class="fig" onclick={() => ctx.openDetail("replies")} title="What today is made of">
      <span class="fig-l">Replies today <span class="fig-go"><Icon name="chevron" size={11} /></span></span>
      <span class="fig-row">
        <span class="fig-n"><Num value={ctx.today} /></span>
        <span class="w-20 shrink-0"><Spark values={hourly} height={26} label="Replies each hour, last 24 hours" /></span>
      </span>
      <span class="fig-sub">in the last 24 hours</span>
    </button>
    <button class="fig" onclick={() => ctx.openDetail("replies")} title="What this week is made of">
      <span class="fig-l">This week <span class="fig-go"><Icon name="chevron" size={11} /></span></span>
      <span class="fig-row">
        <span class="fig-n"><Num value={ctx.week} /></span>
        <span class="w-16 shrink-0"><Spark values={week7} height={26} label="Replies each day, last 7 days" /></span>
      </span>
      <span class="fig-sub">
        {#if ctx.trend}
          <span class={ctx.trend.up ? "text-good" : "text-warn"}>{ctx.trend.up ? "+" : "−"}{ctx.trend.pct}%</span>
          on the week before
        {:else}
          the last 7 days
        {/if}
      </span>
    </button>
    <button class="fig" onclick={() => ctx.openDetail("people")} title="Who they were">
      <span class="fig-l">People this week <span class="fig-go"><Icon name="chevron" size={11} /></span></span>
      <span class="fig-row">
        <span class="fig-n"><Num value={ctx.stats?.people_7d ?? 0} /></span>
      </span>
      <span class="fig-sub truncate">
        {#if ctx.stats?.top?.[0]}{ctx.stats.top[0].username} the most · {/if}{n(ctx.stats?.people ?? 0)} in total
      </span>
    </button>
  </div>

<!-- ── Replies over time ────────────────────────────────────────────────── -->
{:else if inst.type === "activity"}
  {@const peak = argmax(perDay)}
  {@const delta = change(det?.total ?? 0, det?.previous ?? 0)}
  <div class="mb-4 grid grid-cols-2 gap-3 @xl:grid-cols-4">
    <div><div class="mini-n"><Num value={det?.total ?? 0} /></div><div class="mini-l">replies in {days} days</div></div>
    <div><div class="mini-n"><Num value={(det?.total ?? 0) / days} decimals={1} /></div><div class="mini-l">a day on average</div></div>
    <div>
      <div class="mini-n">{peak >= 0 ? n(perDay[peak]) : "–"}</div>
      <div class="mini-l">busiest day{peak >= 0 && perDay[peak] ? `, ${perDayLabels[peak]}` : ""}</div>
    </div>
    <div>
      <div class="mini-n {delta ? (delta.up ? 'text-good' : 'text-warn') : ''}">{delta?.text ?? "–"}</div>
      <div class="mini-l">on the {days} days before</div>
    </div>
  </div>
  <div class="grid grid-cols-1 gap-5 @3xl:grid-cols-3">
    <div class="@3xl:col-span-2">
      <div class="mb-1.5 text-[11px] text-faint">Per day</div>
      <StatChart values={perDay} labels={perDayLabels} kind="area" height={130} unit="replies" />
    </div>
    <div>
      <div class="mb-1.5 text-[11px] text-faint">Last 24 hours, by hour</div>
      <StatChart values={ctx.hourly} labels={ctx.hourlyLabels} kind="bars" height={130} unit="replies" />
    </div>
  </div>

<!-- ── Accounts ─────────────────────────────────────────────────────────── -->
{:else if inst.type === "accounts"}
  <AccountsWidget view={String(opt("view") ?? "cards")} />

<!-- ── Most active people ───────────────────────────────────────────────── -->
{:else if inst.type === "people"}
  {@const top = (det?.top ?? []).slice(0, Number(opt("count") ?? 5))}
  {@const most = Math.max(1, ...top.map((t: any) => t.count))}
  {@const shown = top.reduce((a: number, t: any) => a + t.count, 0)}
  {#if top.length}
    <!-- A leaderboard: medals for the top three, each face with its platform on it, a bar that glows for how much.
         As it arrives the rows slide in one after another, each a note, higher the more replies, so the list
         plays downhill before the medals shine (lib/growin.ts). -->
    <div class="ap-list @2xl:grid-cols-2" use:arriving={{ heights: () => top.map((x: any) => x.count), stagger: 50, level: 0.7 }}>
      {#each top as t, i (t.platform + t.id)}
        {@const snap = t.platform === "snapchat"}
        <div class="ap-row" style="--i: {i}" data-rank={i < 3 ? i + 1 : undefined}>
          <RankBadge n={i + 1} delay={450} />
          <span class="ap-av">
            {#if t.avatar || snap}
              <Avatar src={t.avatar ?? ""} name={t.name} size={34} zoom={false} silhouette={snap} />
            {:else}
              <span class="ap-initial" style="--h: {[...(t.name || "?")].reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) % 360, 11)}">
                {(t.name || "?").slice(0, 1).toUpperCase()}
              </span>
            {/if}
            <span class="ap-platform" class:is-snap={snap} title={snap ? "Snapchat" : "Discord"}>
              <Icon name={snap ? "snapchat" : "discord"} size={9} />
            </span>
          </span>
          <div class="ap-main">
            <div class="ap-top">
              <span class="ap-name">
                <UserChip id={t.id} name={t.name} />
              </span>
              <span class="ap-count">{t.count}</span>
            </div>
            <div class="ap-bar"><i class="grow-bar" style="width: {Math.max(4, Math.round((t.count / most) * 100))}%"></i></div>
          </div>
        </div>
      {/each}
    </div>
    {#if det?.total}
      {@const share = Math.round((shown / det.total) * 100)}
      <div class="ap-share">
        <span class="ap-share-bar"><i style="width: {share}%"></i></span>
        <span><b>{share}%</b> of the {n(det.total)} replies in {days} days went to these {top.length}</span>
      </div>
    {/if}
  {:else}
    <p class="py-4 text-center text-[12px] text-faint">No conversations in the last {days} days.</p>
  {/if}

<!-- ── Live log ─────────────────────────────────────────────────────────── -->
{:else if inst.type === "log"}
  <!-- The same rows as the Logs page, not the console's text. -->
  <LogWidget lines={ctx.logs ?? []} filter={String(opt("filter") ?? "all")} tall={opt("height") === "tall"} />
  <button class="mt-2 text-[11px] text-faint hover:text-accent" onclick={() => go("logs")}>Open the full log →</button>

<!-- ── Time of day / day of week ────────────────────────────────────────── -->
{:else if inst.type === "hours"}
  {@const busy = argmax(hours)}
  {@const quiet = argmin(hours)}
  {@const total = hours.reduce((a, b) => a + b, 0)}
  {#if total}
    <p class="takeaway">
      Busiest around <b>{hh(busy)}</b>, quietest around <b>{hh(quiet)}</b>.
      {Math.round((hours[busy] / total) * 100)}% of replies go out in that one hour.
    </p>
  {/if}
  <StatChart values={hours} labels={hourLabels} kind="bars" height={130} unit="replies" />
{:else if inst.type === "weekdays"}
  {@const busy = argmax(weekdays)}
  {@const quiet = argmin(weekdays)}
  {@const total = weekdays.reduce((a, b) => a + b, 0)}
  {#if total}
    {@const bd = det?.weekday?.[busy]?.day ?? busy}
    {@const qd = det?.weekday?.[quiet]?.day ?? quiet}
    <p class="takeaway">
      Busiest on <b>{DOW_LONG[bd]}</b> ({Math.round((weekdays[busy] / total) * 100)}% of the week),
      quietest on <b>{DOW_LONG[qd]}</b>.
    </p>
  {/if}
  <StatChart values={weekdays} labels={weekdayLabels} kind="bars" height={130} unit="replies" />

<!-- ── Discord and Snapchat ─────────────────────────────────────────────── -->
{:else if inst.type === "platforms"}
  {@const d = det?.platform?.discord ?? 0}
  {@const s = det?.platform?.snapchat ?? 0}
  {@const sum = Math.max(1, d + s)}
  {@const delta = change(det?.total ?? 0, det?.previous ?? 0)}
  <!-- One hue, named by label rather than colour, and each platform's own
       trend beside it: the theme's two accents are too close together to tell
       apart on most themes, so a second colour would not have worked. -->
  <div class="pf-list space-y-4" use:arriving={{ heights: () => [d, s], stagger: 120 }}>
    {#each [["Discord", "discord", d, series.map((x) => x.discord)], ["Snapchat", "snapchat", s, series.map((x) => x.snapchat)]] as [name, icon, count, trend], k}
      <div class="flex items-center gap-3">
        <span class="bubble"><Icon name={String(icon)} size={16} /></span>
        <div class="min-w-0 flex-1">
          <div class="mb-1 flex items-baseline justify-between gap-2 text-[12px]">
            <span class="text-ink">{name}</span>
            <span class="tabular-nums text-muted">{n(Number(count))} · {Math.round((Number(count) / sum) * 100)}%</span>
          </div>
          <div class="h-2 overflow-hidden rounded-full bg-white/[0.06]">
            <div class="grow-bar pf-bar h-full rounded-full bg-accent" style="width: {(Number(count) / sum) * 100}%; --i: {k}"></div>
          </div>
        </div>
        <span class="hidden w-24 shrink-0 @md:block">
          <Spark values={(trend as number[]).slice(-14)} height={28} label="{name}, replies per day" />
        </span>
      </div>
    {/each}
    <p class="text-[11px] text-faint">
      {n(det?.total ?? 0)} replies in {days} days{#if delta}, <span class={delta.up ? "text-good" : "text-warn"}>{delta.text}</span> on the {days} before{/if}.
    </p>
  </div>

<!-- ── Waiting for a reply ──────────────────────────────────────────────── -->
{:else if inst.type === "waiting"}
  {#if waiting.length}
    <div class="mb-3 flex items-baseline gap-2">
      <span class="text-2xl font-semibold tabular-nums text-ink">{waiting.length}</span>
      <span class="text-[12px] text-muted">{waiting.length === 1 ? "person is" : "people are"} waiting</span>
      {#if waiting[0]?.ts}
        <span class="ml-auto text-[11px] text-faint">longest {waited(waiting[0].ts)}</span>
      {/if}
    </div>
    <div class="grid gap-1.5 @3xl:grid-cols-2 @3xl:gap-x-4">
      {#each waiting.slice(0, Number(opt("count") ?? 6)) as u (u.id + u.target)}
        <div class="wait-row">
          <Avatar src={u.avatar} name={u.name} size={30} zoom={false} />
          <div class="min-w-0 flex-1">
            <div class="flex min-w-0 items-center gap-1.5">
              <span class="truncate text-[12.5px] font-medium text-ink">{u.name}</span>
              {#if u.count > 1}<Badge tone="accent">{u.count}</Badge>{/if}
            </div>
            <div class="truncate text-[11.5px] text-faint"><MentionText text={u.snippet} /></div>
          </div>
          <span class="shrink-0 text-right">
            <span class="block text-[11px] tabular-nums {u.ts && now - u.ts > 3600 ? 'text-warn' : 'text-muted'}">{waited(u.ts)}</span>
            {#if u.account}
              <span class="block max-w-[6rem] truncate text-[10px] text-faint">
                {u.account.display_name || u.account.username || (u.account.platform === "snapchat" ? "Snapchat" : "Discord")}
              </span>
            {/if}
          </span>
          <button class="reply-btn" onclick={() => reply(u)} disabled={!!$replying[String(u.id)]}
                  title="Have the bot answer {u.name} now">
            {#if $replying[String(u.id)]}<span class="spin"></span>{:else}<Icon name="chats" size={13} />{/if}
            <span class="hidden @sm:inline">Reply</span>
          </button>
        </div>
      {/each}
    </div>
    <button class="mt-2.5 text-[11px] text-faint hover:text-accent" onclick={() => go("chats")}>Open Chats →</button>
  {:else}
    <div class="all-clear"><Icon name="check" size={15} /> Nobody is waiting for a reply.</div>
  {/if}

<!-- ── Needs attention ──────────────────────────────────────────────────── -->
{:else if inst.type === "health"}
  {@const issues = ($health.issues ?? []).filter((i) => i.level !== "info")}
  {#if issues.length}
    <div class="space-y-1.5">
      {#each issues as issue}
        <button class="jelly issue {issue.level === 'error' ? 'is-bad' : ''}" onclick={() => go(issue.route)}>
          <span class="mt-0.5 shrink-0"><Icon name="alert" size={14} /></span>
          <span class="min-w-0 flex-1">
            <span class="block text-[12.5px] font-medium text-ink">{issue.title}</span>
            <span class="block truncate text-[11px] text-faint">{issue.detail}</span>
          </span>
          <span class="shrink-0 self-center text-[11px] text-faint">Fix →</span>
        </button>
      {/each}
    </div>
  {:else}
    <div class="all-clear"><Icon name="check" size={15} /> Nothing needs attention.</div>
  {/if}

<!-- ── Quick actions ────────────────────────────────────────────────────── -->
{:else if inst.type === "actions"}
  {@const people = ($memory.data?.users ?? []).length}
  <div class="grid grid-cols-2 gap-2 @xl:grid-cols-3">
    {#each [
      { icon: "chats", label: "Chats", sub: waiting.length ? `${waiting.length} waiting` : "nobody waiting", hot: waiting.length > 0, run: () => go("chats") },
      { icon: "memory", label: "Memory", sub: people ? `${people} people` : "what it remembers", hot: false, run: () => go("memory") },
      { icon: "logs", label: "Logs", sub: logErrors ? `${logErrors} recent error${logErrors === 1 ? "" : "s"}` : "no recent errors", hot: logErrors > 0, run: () => go("logs") },
      { icon: "settings", label: "Settings", sub: settingsIssues ? `${settingsIssues} to fix` : "everything else", hot: settingsIssues > 0, run: () => go("settings") },
      { icon: "search", label: "Search", sub: "Ctrl K, anywhere", hot: false, run: () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true })) },
      { icon: "pause", label: "Pause all", sub: "or resume them", hot: false, run: pauseToggle },
    ] as a}
      <button class="jelly action" onclick={a.run}>
        <span class="bubble"><Icon name={a.icon} size={15} /></span>
        <span class="min-w-0">
          <span class="block text-[12.5px] font-medium text-ink">{a.label}</span>
          <span class="block truncate text-[11px] {a.hot ? 'text-warn' : 'text-faint'}">{a.sub}</span>
        </span>
      </button>
    {/each}
  </div>
{/if}

<style>
  /* Bars grow in from the left when they first appear or change. */
  .grow-bar {
    transition: width 0.6s var(--spring);
  }
  /* Discord's and Snapchat's shares, grown out as the widget arrives, one after the other (lib/growin.ts). */
  .pf-bar { transform-origin: left center; }
  .pf-list:not(:global(.is-in)) .pf-bar { transform: scaleX(0); }
  .pf-list:global(.is-in) .pf-bar {
    animation: pf-in 0.7s var(--spring) both;
    animation-delay: calc(var(--i, 0) * 120ms);
  }
  @keyframes pf-in { from { transform: scaleX(0); } }
  :global(:root[data-motion="off"]) .pf-bar { animation: none; transform: none; }

  /* Four figures on the surface itself, a seam between each, not four boxes.
     Pointed at, one lights from underneath and its number lifts. */
  .fig {
    position: relative;
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 6px;
    padding: 10px 16px 12px;
    border-radius: 14px;
    text-align: left;
    transition: background-color 0.25s var(--swift), transform 0.3s var(--jelly);
  }
  .fig + .fig::before {
    content: "";
    position: absolute;
    top: 14px;
    bottom: 14px;
    left: 0;
    width: 1px;
    background: linear-gradient(180deg, transparent, rgb(255 255 255 / 0.08), transparent);
  }
  /* Two to a row when narrow: the third starts a row and has no seam beside it. */
  .figs > .fig:nth-child(3)::before { display: none; }
  @container (min-width: 42rem) {
    .figs > .fig:nth-child(3)::before { display: block; }
  }
  .fig:hover {
    background: radial-gradient(120% 90% at 50% 100%, color-mix(in srgb, var(--color-accent) 12%, transparent), transparent 70%);
  }
  .fig:active { transform: scale(0.98); }
  .fig-n { transition: transform 0.35s var(--jelly); transform-origin: left bottom; }
  .fig:hover .fig-n { transform: translateY(-2px) scale(1.04); }
  .fig-l {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--color-faint);
  }
  .fig-go {
    opacity: 0;
    transition: opacity 0.15s ease, transform 0.2s var(--spring);
  }
  .fig:hover .fig-go { opacity: 1; transform: translateX(2px); }
  .fig-row {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 10px;
  }
  .fig-n {
    font-size: 28px;
    font-weight: 650;
    line-height: 1;
    letter-spacing: -0.01em;
    color: var(--color-ink);
  }
  .fig-of {
    font-size: 15px;
    font-weight: 500;
    color: var(--color-muted);
  }
  .fig-sub {
    font-size: 11.5px;
    color: var(--color-muted);
  }

  .mini-n {
    font-size: 18px;
    font-weight: 600;
    line-height: 1.2;
    color: var(--color-ink);
  }
  .mini-l {
    margin-top: 1px;
    font-size: 11px;
    color: var(--color-faint);
  }

  .takeaway {
    margin-bottom: 12px;
    font-size: 12.5px;
    line-height: 1.5;
    color: var(--color-muted);
  }
  .takeaway b {
    font-weight: 600;
    color: var(--color-ink);
  }

  /* ── Most active people ── */
  .ap-list { display: grid; gap: 2px 18px; }
  .ap-row {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 11px;
    margin: 0 -8px;
    padding: 6px 8px;
    border-radius: 12px;
    transition: background-color 0.15s ease;
  }
  /* Waiting for the list's moment (lib/growin.ts adds is-in), then one after another. */
  .ap-list:not(:global(.is-in)) .ap-row { opacity: 0; }
  .ap-list:global(.is-in) .ap-row {
    animation: ap-in 0.45s var(--swift) both;
    animation-delay: calc(var(--i, 0) * 50ms);
  }
  .ap-row:hover { background: rgb(255 255 255 / 0.035); }
  .ap-av { position: relative; display: inline-flex; flex-shrink: 0; border-radius: 999px; }
  .ap-row[data-rank="1"] .ap-av { box-shadow: 0 0 0 2px #f0b63f, 0 4px 14px -4px #f0b63f; }
  .ap-initial {
    display: grid;
    width: 34px;
    height: 34px;
    place-items: center;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 700;
    color: hsl(var(--h) 75% 82%);
    background: hsl(var(--h) 40% 30% / 0.55);
  }
  .ap-platform {
    position: absolute;
    right: -3px;
    bottom: -3px;
    display: grid;
    width: 15px;
    height: 15px;
    place-items: center;
    border-radius: 999px;
    color: #fff;
    background: #5865f2;
    box-shadow: 0 0 0 2px var(--color-card);
  }
  .ap-platform.is-snap { color: #141414; background: #fffc00; }
  .ap-main { min-width: 0; flex: 1; }
  .ap-top { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
  .ap-name { min-width: 0; overflow: hidden; font-size: 13px; font-weight: 600; color: var(--color-ink); white-space: nowrap; text-overflow: ellipsis; }
  .ap-count { flex-shrink: 0; font-size: 12.5px; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--color-ink); }
  .ap-bar { height: 6px; margin-top: 6px; overflow: hidden; border-radius: 999px; background: rgb(255 255 255 / 0.06); }
  .ap-bar i {
    display: block;
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, color-mix(in srgb, var(--color-accent) 60%, transparent), var(--color-accent));
    box-shadow: 0 0 12px -2px color-mix(in srgb, var(--color-accent) 65%, transparent);
    transform-origin: left center;
  }
  /* Growing out with its row as the list arrives, a moment behind it. */
  .ap-list:global(.is-in) .ap-bar i {
    animation: ap-bar-in 0.7s var(--spring) both;
    animation-delay: calc(var(--i, 0) * 50ms + 120ms);
  }
  @keyframes ap-bar-in { from { transform: scaleX(0); } }
  .ap-row[data-rank="1"] .ap-bar i {
    background: linear-gradient(90deg, color-mix(in srgb, var(--color-accent) 60%, transparent), var(--color-accent),
                                       color-mix(in srgb, var(--color-accent) 65%, #fff));
  }
  .ap-share { display: flex; align-items: center; gap: 10px; margin-top: 12px; font-size: 11px; color: var(--color-faint); }
  .ap-share-bar { display: block; width: 60px; height: 5px; flex-shrink: 0; overflow: hidden; border-radius: 999px; background: rgb(255 255 255 / 0.07); }
  .ap-share-bar i { display: block; height: 100%; border-radius: 999px; background: var(--color-accent); }
  .ap-share b { font-weight: 700; color: var(--color-muted); }
  @keyframes ap-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: none; } }
  :global(:root[data-motion="off"]) .ap-row,
  :global(:root[data-motion="off"]) .ap-bar i { animation: none; opacity: 1; }

  .initial,
  .bubble {
    display: flex;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .initial {
    width: 28px;
    height: 28px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 700;
  }
  .bubble {
    width: 32px;
    height: 32px;
    border-radius: 10px;
  }

  .wait-row {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 10px;
    padding: 6px 6px 6px 4px;
    border-radius: 11px;
    transition: background-color 0.15s ease;
  }
  .wait-row:hover { background: rgb(255 255 255 / 0.035); }
  .reply-btn {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 5px;
    padding: 5px 9px;
    border-radius: 9px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 16%, transparent);
    transition: background-color 0.15s ease, transform 0.15s var(--spring);
  }
  .reply-btn:hover { background: color-mix(in srgb, var(--color-accent) 28%, transparent); }
  .reply-btn:active { transform: scale(0.95); }
  .reply-btn:disabled { opacity: 0.7; cursor: default; }
  .spin {
    width: 12px;
    height: 12px;
    border-radius: 999px;
    border: 1.5px solid currentColor;
    border-top-color: transparent;
    animation: wb-turn 0.9s linear infinite;
  }
  @keyframes wb-turn { to { transform: rotate(360deg); } }

  .all-clear {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 0;
    font-size: 12.5px;
    color: var(--color-muted);
  }
  .all-clear :global(svg) { color: var(--color-good); }

  .issue {
    display: flex;
    width: 100%;
    align-items: flex-start;
    gap: 10px;
    padding: 8px 10px;
    border-radius: 11px;
    text-align: left;
    color: var(--color-warn);
    background: color-mix(in srgb, var(--color-warn) 6%, transparent);
  }
  .issue.is-bad {
    color: var(--color-bad);
    background: color-mix(in srgb, var(--color-bad) 7%, transparent);
  }
  .issue:hover { filter: brightness(1.15); }

  .action {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 10px;
    padding: 10px;
    border-radius: 13px;
    text-align: left;
    background: rgb(255 255 255 / 0.035);
    transition: background-color 0.15s ease;
  }
  .action:hover { background: rgb(255 255 255 / 0.07); }

  :global(:root[data-motion="off"]) .spin { animation: none; }
</style>
