<script lang="ts">
  /**
   * The bottom of the right column, which changes by itself.
   *
   * The panels up there used to be the same three things for as long as you
   * watched. This one turns over: what just happened, the day so far, who
   * the account has been talking to, and the log as it is written. It holds on
   * the feed while something is actually arriving, because live beats a
   * summary, and only moves on once things have gone quiet for a moment. A
   * click on its dots turns it to that face.
   */
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import RankBadge from "../components/RankBadge.svelte";
  import BPFeed from "./BPFeed.svelte";
  import Counter from "./Counter.svelte";
  import { popIn } from "./motion";
  import type { FeedItem, LogLite } from "./types";

  let {
    items = [],
    now = 0,
    hideText = false,
    today = { replies: 0, people: 0, tokens: 0, requests: 0 },
    top = [],
    accounts = [],
    logs = [],
  }: {
    items?: FeedItem[];
    now?: number;
    hideText?: boolean;
    today?: { replies: number; people: number; tokens: number; requests: number };
    top?: { user_id: string; username: string; count: number; avatar?: string }[];
    accounts?: { id: string; name: string; avatar?: string; state: string; ping?: number | null; mood?: string }[];
    logs?: LogLite[];
  } = $props();

  const FACES = ["feed", "today", "people", "log"] as const;
  type Face = (typeof FACES)[number];
  /** Seconds each one stays up. */
  const HOLD = 10;
  /** How far back the feed face looks. Half a minute left it an empty box
      whenever the bot had been quiet, which is most of the time. */
  const FEED_WINDOW = 15 * 60;

  /** Only the faces that have something on them: an empty panel with a heading
      and nothing under it is worse than not showing that face at all. */
  const usable = $derived.by<Face[]>(() => {
    const out: Face[] = [];
    if (items.some((i) => now - i.at < FEED_WINDOW)) out.push("feed");
    out.push("today");                      // the numbers always exist
    if (top.length) out.push("people");
    if (logs.some((l) => now - l.at < FEED_WINDOW)) out.push("log");
    return out;
  });

  let at = $state(0);
  let since = $state(0);
  /** Something arrived in the last few seconds: stay on the feed for it. */
  const live = $derived(items.some((i) => now - i.at < 6));

  $effect(() => {
    if (!since) since = now;
    if (live) return;                       // live beats a summary
    if (now - since < HOLD) return;
    since = now;
    at = (at + 1) % Math.max(1, usable.length);
  });

  const face = $derived<Face>(
    live && usable.includes("feed") ? "feed" : usable[at % usable.length] ?? "today",
  );
  const LABEL: Record<Face, string> = { feed: "Just now", today: "The day so far", people: "Talked to most", log: "The log" };
  /** A dot clicked: that face, with its full time on the clock. */
  function turnTo(f: Face) {
    const i = usable.indexOf(f);
    if (i < 0) return;
    at = i;
    since = now;
  }
  const lines = $derived(logs.filter((l) => now - l.at < FEED_WINDOW).slice(-7).reverse());
  function ago(t: number): string {
    const s = Math.max(0, now - t);
    if (s < 10) return "now";
    if (s < 60) return `${Math.floor(s)}s`;
    return `${Math.floor(s / 60)}m`;
  }
</script>

<section class="bpr">
  <header class="bp-label">
    {LABEL[face]}
    <span class="bpr-dots">
      {#each usable as f (f)}
        <button class:is-on={f === face} onclick={() => turnTo(f)} title={LABEL[f]} aria-label={LABEL[f]}><i></i></button>
      {/each}
    </span>
  </header>

  {#key face}
    <div class="bpr-face" in:popIn={{ from: 0.97 }}>
      {#if face === "feed"}
        <BPFeed {items} {now} {hideText} window={FEED_WINDOW} max={6} when />
      {:else if face === "today"}
        <div class="bpr-nums">
          <div><b><Counter value={today.replies} /></b><span>replies</span></div>
          <div><b><Counter value={today.people} /></b><span>people this week</span></div>
          <div><b><Counter value={today.requests} /></b><span>AI requests</span></div>
          <div><b><Counter value={today.tokens} /></b><span>tokens</span></div>
        </div>
        {#if accounts.length}
          <div class="bpr-accts">
            {#each accounts as a (a.id)}
              <span class="bpr-acct" data-state={a.state}>
                <Avatar src={a.avatar} name={a.name} size={20} zoom={false} />
                {a.name}{#if a.ping != null}<em>{a.ping} ms</em>{/if}
              </span>
            {/each}
          </div>
        {/if}
      {:else if face === "log"}
        <ol class="bpr-log" class:is-hidden={hideText}>
          {#each lines as l, i (l.id)}
            <li data-level={l.level} in:popIn|global={{ delay: 40 + i * 50, from: 0.96 }}>
              {#if l.avatar}
                <Avatar src={l.avatar} name={l.who} size={18} zoom={false} />
              {:else}
                <span class="bpr-src" title={l.who}><Icon name={l.icon} size={11} /></span>
              {/if}
              <span class="bpr-line" title="{l.who}: {l.text}">{l.text}</span>
              <span class="bpr-when">{ago(l.at)}</span>
            </li>
          {/each}
        </ol>
      {:else}
        {#if top.length}
          <ol class="bpr-people">
            {#each top.slice(0, 5) as p, i (p.user_id)}
              <li in:popIn|global={{ delay: 60 + i * 60 }}>
                <RankBadge n={i + 1} size={18} quiet />
                <Avatar src={p.avatar} name={p.username} size={24} zoom={false} />
                <span class="bpr-name">{p.username}</span>
                <b>{p.count}</b>
              </li>
            {/each}
          </ol>
        {:else}
          <p class="bpr-empty"><Icon name="accounts" size={15} />Nobody yet this week.</p>
        {/if}
      {/if}
    </div>
  {/key}
</section>

<style>
  .bpr {
    display: flex;
    min-height: 0;
    flex-direction: column;
    gap: 10px;
    padding: 16px 18px;
    border-radius: 24px;
    background: rgb(255 255 255 / 0.045);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.07);
    backdrop-filter: blur(20px);
    /* Squeezed by a short screen, what does not fit is cut at the panel's edge, not spilled under the bar below. */
    overflow: hidden;
  }
  .bpr-dots { display: inline-flex; margin-left: auto; }
  /* A dot, with a target big enough to hit around it. */
  .bpr-dots button { display: grid; height: 16px; padding: 0 2px; place-items: center; }
  .bpr-dots i {
    display: block;
    width: 5px;
    height: 5px;
    border-radius: 999px;
    background: rgb(255 255 255 / 0.2);
    transition: background-color 0.4s ease, width 0.4s var(--swift);
  }
  .bpr-dots button:hover i { background: rgb(255 255 255 / 0.5); }
  .bpr-dots button.is-on i { width: 13px; background: var(--color-accent); }

  .bpr-log { display: flex; min-width: 0; flex-direction: column; gap: 6px; }
  .bpr-log li { display: flex; min-width: 0; align-items: center; gap: 8px; font-size: 12px; color: var(--bp-muted); }
  .bpr-src { display: grid; width: 18px; height: 18px; flex-shrink: 0; place-items: center; border-radius: 999px; color: var(--bp-faint); background: rgb(255 255 255 / 0.07); }
  .bpr-line { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bpr-log li[data-level="error"] .bpr-line { color: var(--color-bad); }
  .bpr-log li[data-level="warn"] .bpr-line { color: var(--color-warn); }
  .bpr-log li[data-level="reply"] .bpr-line { color: #fff; }
  .bpr-log.is-hidden .bpr-line { filter: blur(5px); }
  .bpr-when { flex-shrink: 0; font-size: 10.5px; color: var(--bp-faint); font-variant-numeric: tabular-nums; }
  .bpr-face { display: flex; min-height: 0; flex-direction: column; gap: 10px; }

  .bpr-nums { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
  .bpr-nums div { display: flex; flex-direction: column; padding: 9px 12px; border-radius: 14px; background: rgb(0 0 0 / 0.2); }
  .bpr-nums b { font-size: 21px; font-weight: 750; line-height: 1.1; color: #fff; }
  .bpr-nums span { font-size: 10.5px; color: var(--bp-faint); }
  .bpr-accts { display: flex; flex-wrap: wrap; gap: 6px; }
  .bpr-acct {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 10px 3px 4px;
    border-radius: 999px;
    font-size: 11.5px;
    color: var(--bp-muted);
    background: rgb(255 255 255 / 0.05);
  }
  .bpr-acct[data-state="running"] { color: #fff; }
  .bpr-acct em { font-style: normal; font-size: 10.5px; color: var(--bp-faint); }

  .bpr-people { display: flex; flex-direction: column; gap: 7px; }
  .bpr-people li { display: flex; min-width: 0; align-items: center; gap: 9px; font-size: 13px; color: #fff; }
  .bpr-name { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bpr-people b { font-weight: 650; color: var(--bp-muted); font-variant-numeric: tabular-nums; }
  .bpr-empty { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--bp-faint); }
</style>
