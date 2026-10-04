<script lang="ts">
  /**
   * The Dashboard's Accounts widget.
   *
   * It showed each account's process: uptime, a pid and a restart count, three
   * buttons, and a name cut to "! Alici...". None of that says whether the
   * account is doing its job. It now says what the Accounts page says - the
   * state in words, from the same condition() - with what each account did
   * today and this week, who is waiting on it, and a week of replies at a
   * glance.
   *
   * Laid out by the widget's own width, not the window's: a single account
   * fills the widget instead of sitting in one cell of a two-column grid, and
   * a wide card spreads out into a row.
   */
  import { onMount } from "svelte";
  import { visiblePoll } from "../poll";
  import { chatCache } from "../chats";
  import Avatar from "../components/Avatar.svelte";
  import Badge from "../components/Badge.svelte";
  import Button from "../components/Button.svelte";
  import Empty from "../components/Empty.svelte";
  import Icon from "../components/Icon.svelte";
  import StatusDot from "../components/StatusDot.svelte";
  import { menu as contextMenu, copyText, type MenuEntry } from "../contextmenu";
  import Spark from "./Spark.svelte";
  import {
    condition, platformName, presenceOf, uptime, type Runtime, type Slot,
  } from "../accounts/condition";
  import {
    accountDetails, accountsRes, activityRes, refreshDetails, runAccountAction, slotsRes,
  } from "../accounts/state";
  import { fmtDate } from "../fmt";

  let { view = "cards" }: { view?: string } = $props();

  const runtime = $derived(($accountsRes.data.accounts ?? []) as Runtime[]);
  const slots = $derived(($slotsRes.data.slots ?? []) as Slot[]);
  const dates = $derived<string[]>($activityRes.data.dates ?? []);
  let acting = $state("");

  /** Right-click on an account: its name and @username, to copy. */
  function accountMenu(r: { name: string; rt?: { username?: string } | null }): MenuEntry[] {
    return [
      { title: r.name },
      { label: "Copy name", icon: "copy", run: () => copyText(r.name, "Copied the name.") },
      r.rt?.username && r.rt.username !== r.name
        && { label: `Copy @${r.rt.username}`, icon: "copy", run: () => copyText(r.rt?.username ?? "", "Copied the username.") },
    ];
  }

  const rows = $derived(slots.map((s) => {
    const rt = runtime.find((r) => r.platform === s.platform && r.account === s.index);
    const d = $accountDetails[s.id];
    const cache = $chatCache[s.id];
    const act = $activityRes.data.accounts?.[s.id];
    return {
      slot: s, rt, d, act,
      cond: condition(s, rt, d),
      presence: presenceOf(s, rt, d),
      name: rt?.display_name || rt?.username || s.username || `${platformName(s.platform)} #${s.index}`,
      waiting: cache?.fetched ? cache.users.length : null,
      week: (act?.series ?? []).slice(-7),
    };
  }));

  const dayTitles = $derived(dates.slice(-7).map((iso: string) => {
    const [y, m, d] = iso.split("-").map(Number);
    return fmtDate(new Date(y, m - 1, d), { weekday: "short", day: "numeric", month: "short" });
  }));

  onMount(() => {
    slotsRes.refresh({ maxAge: 30_000 });
    accountsRes.refresh({ maxAge: 4_000 }).then(details);
    activityRes.refresh({ maxAge: 60_000 });
    const fast = visiblePoll(() => accountsRes.refresh({ maxAge: 4_000, quiet: true }).then(details), 8_000);
    const slow = visiblePoll(() => activityRes.refresh({ maxAge: 55_000, quiet: true }), 60_000);
    return () => {
      fast();
      slow();
    };
  });

  async function details() {
    await Promise.all(runtime.filter((r) => r.state === "running").map((r) => refreshDetails(r.id)));
  }

  async function act(r: (typeof rows)[number], what: "start" | "stop" | "restart") {
    if (!r.rt) return;
    acting = `${r.slot.id}:${what}`;
    await runAccountAction(r.rt.id, what, r.name, "dashboard");
    acting = "";
  }

  const open = () => (window.location.hash = "/accounts");
</script>

{#if !slots.length && $slotsRes.fetched}
  <Empty text="No accounts yet. Add one on the Accounts page." icon="accounts" />
{:else if view === "list"}
  <div class="divide-y divide-edge/50">
    {#each rows as r (r.slot.id)}
      <div class="flex items-center gap-3 py-2.5" use:contextMenu={() => accountMenu(r)}>
        <span class="aw-av">
          <Avatar src={r.rt?.avatar} name={r.name} size={30} zoom={false} silhouette={r.slot.platform === "snapchat" && !!r.rt?.username} />
          <span class="aw-dot aw-dot-sm"><StatusDot status={r.presence} size={10} /></span>
        </span>
        <div class="min-w-0 flex-1">
          <div class="selectable truncate text-[13px] font-medium text-ink">{r.name}</div>
          <div class="truncate text-[11px] text-faint">{r.cond.line}</div>
        </div>
        <span class="hidden text-right @sm:block">
          <span class="block text-[13px] font-semibold tabular-nums text-ink">{r.act?.today ?? 0}</span>
          <span class="block text-[10px] text-faint">today</span>
        </span>
        <Badge tone={r.cond.tone} dot>{r.cond.label}</Badge>
      </div>
    {/each}
  </div>
{:else}
  <div class="aw-grid">
    {#each rows as r (r.slot.id)}
      <div class="@container">
        <div class="aw-card" class:is-bad={r.cond.tone === "bad"} class:is-live={r.cond.live} use:contextMenu={() => accountMenu(r)}>
          <div class="grid gap-3 @xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1.4fr)_auto] @xl:items-center @xl:gap-5">
            <!-- Who, and what it is doing -->
            <div class="flex min-w-0 items-center gap-3">
              <span class="aw-av">
                <Avatar src={r.rt?.avatar} name={r.name} size={44} silhouette={r.slot.platform === "snapchat" && !!r.rt?.username} />
                <span class="aw-dot"><StatusDot status={r.presence} size={12} /></span>
              </span>
              <div class="min-w-0 flex-1">
                <div class="flex min-w-0 items-center gap-2">
                  <span class="selectable min-w-0 truncate text-[14px] font-semibold text-ink" title={r.name}>{r.name}</span>
                  <span class="shrink-0 text-faint" title={platformName(r.slot.platform)}>
                    <Icon name={r.slot.platform === "snapchat" ? "snapchat" : "discord"} size={12} />
                  </span>
                </div>
                <div class="mt-0.5 flex min-w-0 items-center gap-1.5">
                  <span class="shrink-0 whitespace-nowrap"><Badge tone={r.cond.tone} dot>{r.cond.label}</Badge></span>
                  <span class="min-w-0 truncate text-[11px] text-faint">{r.cond.line}</span>
                </div>
              </div>
            </div>

            <!-- What it has done -->
            <div class="grid grid-cols-[repeat(3,minmax(0,1fr))_minmax(0,1.3fr)] items-end gap-3">
              <div class="min-w-0">
                <div class="aw-n">{r.act?.today ?? 0}</div>
                <div class="aw-l">today</div>
              </div>
              <div class="min-w-0">
                <div class="aw-n">{r.act?.week ?? 0}</div>
                <div class="aw-l">this week</div>
              </div>
              <div class="min-w-0">
                <div class="aw-n {r.waiting ? 'text-warn' : ''}">{r.waiting ?? "–"}</div>
                <div class="aw-l">waiting</div>
              </div>
              <div class="min-w-0">
                <Spark values={r.week} height={24} titles={r.week.map((v: number, i: number) => `${dayTitles[i] ?? ""}: ${v}`)}
                       label="Replies each day this week" />
                <div class="aw-l">last 7 days</div>
              </div>
            </div>

            <!-- One control, and the way to the rest -->
            <div class="flex items-center gap-1.5 @xl:justify-end">
              {#if r.cond.alert}
                <span class="mr-auto min-w-0 truncate text-[11px] {r.cond.alert.tone === 'bad' ? 'text-bad' : 'text-warn'} @xl:hidden"
                      title={r.cond.alert.text}>
                  {r.cond.alert.title}
                </span>
              {:else if r.cond.running && r.rt?.uptime}
                <span class="mr-auto text-[11px] text-faint @xl:hidden">up {uptime(r.rt.uptime)}</span>
              {/if}
              {#if r.cond.running}
                <Button size="sm" kind="ghost" loading={acting === `${r.slot.id}:restart`} onclick={() => act(r, "restart")}>
                  {#if acting !== `${r.slot.id}:restart`}<Icon name="refresh" size={12} />{/if}Restart
                </Button>
                <Button size="sm" kind="ghost" loading={acting === `${r.slot.id}:stop`} onclick={() => act(r, "stop")}>
                  {#if acting !== `${r.slot.id}:stop`}<Icon name="stop" size={11} />{/if}Stop
                </Button>
              {:else}
                <Button size="sm" loading={acting === `${r.slot.id}:start`} disabled={!r.cond.canStart}
                        onclick={() => act(r, "start")}>
                  {#if acting !== `${r.slot.id}:start`}<Icon name="play" size={11} />{/if}Start
                </Button>
              {/if}
              <button class="aw-more" onclick={open} title="Open on the Accounts page" aria-label="Open on the Accounts page">
                <Icon name="chevron" size={14} />
              </button>
            </div>
          </div>
          {#if r.cond.alert}
            <!-- Wide cards have room to say it properly. -->
            <div class="mt-3 hidden truncate text-[11.5px] @xl:block {r.cond.alert.tone === 'bad' ? 'text-bad' : 'text-warn'}"
                 title={r.cond.alert.text}>
              <span class="font-semibold">{r.cond.alert.title}.</span> {r.cond.alert.text}
            </div>
          {/if}
        </div>
      </div>
    {/each}
  </div>
{/if}

<style>
  /* Wrapping flex rather than a grid: every card grows to fill its row, so one
     account takes the whole widget, and the odd one out on the last row
     stretches across it instead of leaving an empty cell beside it. */
  .aw-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }
  .aw-grid > :global(*) {
    flex: 1 1 320px;
    min-width: 0;
  }
  /* No box of its own: the Dashboard is one surface. An account is set apart
     by its space and, while it is replying, a soft light under it; one that
     is failing has a line of its colour down its side. */
  .aw-card {
    position: relative;
    height: 100%;
    padding: 12px 14px;
    border-radius: 14px;
    transition: background-color 0.3s var(--swift), box-shadow 0.3s var(--swift);
  }
  .aw-card:hover { background: rgb(255 255 255 / 0.025); }
  /* A pool of light under it, fading out well inside its edges, so it glows
     rather than showing as a box. */
  .aw-card.is-live {
    background: radial-gradient(closest-side at 22% 45%, color-mix(in srgb, var(--color-accent) 11%, transparent), transparent);
  }
  .aw-card.is-bad {
    box-shadow: inset 2px 0 0 color-mix(in srgb, var(--color-bad) 70%, transparent);
  }
  .aw-av {
    position: relative;
    display: grid;
    flex-shrink: 0;
    line-height: 0;
  }
  .aw-dot {
    position: absolute;
    right: -2px;
    bottom: -2px;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 999px;
    background: var(--color-card);
  }
  .aw-dot-sm {
    width: 14px;
    height: 14px;
    right: -3px;
    bottom: -3px;
  }
  .aw-n {
    font-size: 16px;
    font-weight: 600;
    line-height: 1.2;
    color: var(--color-ink);
  }
  .aw-l {
    margin-top: 2px;
    font-size: 10.5px;
    color: var(--color-faint);
    white-space: nowrap;
  }
  .aw-more {
    display: inline-flex;
    width: 28px;
    height: 28px;
    align-items: center;
    justify-content: center;
    border-radius: 8px;
    color: var(--color-faint);
    transition: background-color 0.15s ease, color 0.15s ease;
  }
  .aw-more:hover {
    background: rgb(255 255 255 / 0.07);
    color: var(--color-ink);
  }
</style>
