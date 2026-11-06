<script lang="ts">
  /**
   * The right of the Now page: which model is doing the work, and what just happened.
   *
   * Nothing here turns over by itself: the list moves when something happens, and
   * that is all. The model is the one on the conversation on stage, or the last to
   * answer anywhere, with how much it has left; pressing it opens Today, where the
   * rest of the models are. Anything in the list about someone opens that
   * conversation. A thought from a model that thinks out loud goes in the
   * conversation it is for; one that is not for the conversation on stage is said here.
   */
  import { flip } from "svelte/animate";
  import { cubicOut } from "svelte/easing";
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import PlatformMark from "../components/PlatformMark.svelte";
  import ProviderTile from "../components/ProviderTile.svelte";
  import { glide } from "../glide";
  import { shortModel, type Plan } from "../providers";
  import { sourceInfo } from "../logrows";
  import { chatAccounts } from "../chats";
  import { play as uiPlay } from "../uisound";
  import type { ModelUsage } from "../modelusage";
  import type { Thought } from "../thoughts";
  import { focusable } from "./focus";
  import { slideIn, slideOut } from "./motion";
  import { ago, agoShort } from "./scenes";
  import type { Active, FeedItem, LogLite } from "./types";

  let {
    active = null,
    forName = "",
    writing = false,
    pulse = 0,
    helper = null,
    plan = null,
    models = [],
    feed = [],
    logs = [],
    thought = null,
    now = 0,
    onmodel,
    onopen,
  }: {
    active?: Active | null;
    /** Whose conversation this model is the one for, when it is the one on stage. */
    forName?: string;
    /** A reply is being written right now. */
    writing?: boolean;
    pulse?: number;
    helper?: { model: string; job: string; at: number } | null;
    plan?: Plan | null;
    models?: ModelUsage[];
    feed?: FeedItem[];
    logs?: LogLite[];
    thought?: Thought | null;
    now?: number;
    onmodel?: () => void;
    onopen?: (target: string, uid: string) => void;
  } = $props();

  const JOB: Record<string, string> = { small: "background work", vision: "reading a picture", stt: "hearing a voice note", tts: "speaking" };
  const WINDOW: Record<string, string> = { day: "today", minute: "this minute", hour: "this hour", month: "this month", second: "now" };

  const cur = $derived(active ?? (plan?.replies?.[0] ? { ...plan.replies[0], at: 0, ms: 0, ok: true } : null));
  const u = $derived(cur ? models.find((m) => m.provider === cur.provider && m.model === cur.model) : undefined);
  const avg = $derived(u && u.today.requests ? `${(u.today.ms / u.today.requests / 1000).toFixed(1)}s` : "");
  /** The limit it is closest to: the one worth a glance. */
  const tightest = $derived.by(() => {
    const list = (u?.limits ?? []).filter((g) => g.limit > 0);
    if (!list.length) return null;
    return list.reduce((a, b) => (b.remaining / b.limit < a.remaining / a.limit ? b : a));
  });
  const fmt = (n: number) => (n >= 10000 ? `${Math.round(n / 1000)}k` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
  const stateWord = $derived(writing
    ? (forName ? `Writing to ${forName}` : "Writing")
    : forName ? `Last wrote to ${forName}`
    : active ? `Answered ${ago(active.at, now)}` : "First choice");

  let list = $state<"feed" | "log">("feed");
  function turnTo(l: "feed" | "log") {
    if (l === list) return;
    list = l;
    uiPlay("select");
  }
  const ICON: Record<FeedItem["kind"], string> = {
    arrive: "chats", write: "sparkle", sent: "check", model: "sparkle", limit: "alert", friend: "userPlus", picture: "pictures",
  };
  const lines = $derived(logs.slice(-14).reverse());
  const items = $derived(feed.slice(0, 14));
</script>

<section class="bpr">
  {#if cur}
    <button class="bp-row bpr-model" use:focusable={{ id: "rail:model" }} onclick={onmodel} title="Every model, on Today">
      <span class="bpr-tile">
        {#key pulse}<span class="bpr-pulse" aria-hidden="true"></span>{/key}
        <ProviderTile id={cur.provider} size={46} />
      </span>
      <span class="bpr-who">
        <span class="bpr-name" title={cur.model}>{shortModel(cur.model)}</span>
        <span class="bpr-state" class:is-on={writing}>{stateWord}</span>
        <span class="bpr-today">{u?.today.requests ?? 0} today{avg ? ` · ${avg} each` : ""}</span>
      </span>
    </button>
    {#if tightest}
      {@const f = tightest.remaining / tightest.limit}
      <div class="bpr-limit" data-tone={f < 0.1 ? "bad" : f < 0.3 ? "warn" : "ok"}>
        <span class="bpr-bar"><i style="--f: {f}"></i></span>
        <span>{fmt(tightest.remaining)} {tightest.what} left {WINDOW[tightest.window] ?? ""}</span>
      </div>
    {/if}
    {#if helper && now - helper.at < 15}
      <div class="bpr-helper">Also <b>{shortModel(helper.model)}</b>, {JOB[helper.job] ?? helper.job}</div>
    {/if}
  {/if}

  {#if thought}
    <div class="bpr-thought" data-private="soft">
      <div class="bp-label">
        Thinking
        {#if thought.source}<span class="bpr-for">{sourceInfo(thought.source, $chatAccounts).name}</span>{/if}
      </div>
      <p>{thought.text}</p>
    </div>
  {/if}

  <div class="bpr-tabs" use:glide={list}>
    <span class="glide-mark" aria-hidden="true"></span>
    <button class:is-active={list === "feed"} onclick={() => turnTo("feed")} data-sound="self">Just now</button>
    <button class:is-active={list === "log"} onclick={() => turnTo("log")} data-sound="self">Log</button>
  </div>

  <div class="bpr-list bp-scrolls" aria-live="polite">
    {#if list === "feed"}
      {#each items as it (it.id)}
        {@const opens = !!(it.target && it.uid)}
        <div in:slideIn out:slideOut animate:flip={{ duration: 360, easing: cubicOut }}>
          <svelte:element this={opens ? "button" : "div"} class="bp-row bpr-item" data-kind={it.kind}
                          use:focusable={{ id: `feed:${it.id}`, skip: !opens }} onclick={opens ? () => onopen?.(it.target!, it.uid!) : undefined}
                          role={opens ? undefined : "presentation"}>
            <span class="bp-face">
              {#if it.avatar || it.name}
                <Avatar src={it.avatar} name={it.name ?? ""} size={26} zoom={false} />
              {:else}
                <span class="bpr-ico"><Icon name={ICON[it.kind]} size={13} /></span>
              {/if}
              {#if it.platform && (it.avatar || it.name)}<span class="bp-mark"><PlatformMark platform={it.platform} size={13} /></span>{/if}
            </span>
            <span class="bpr-text" data-private={it.kind === "arrive" ? "soft" : undefined}>{it.text}</span>
            <span class="bpr-when">{agoShort(it.at, now)}</span>
          </svelte:element>
        </div>
      {:else}
        <p class="bpr-none">Nothing yet.</p>
      {/each}
    {:else}
      {#each lines as l (l.id)}
        <div class="bpr-log" data-level={l.level}>
          {#if l.avatar}
            <Avatar src={l.avatar} name={l.who} size={18} zoom={false} />
          {:else}
            <span class="bpr-src" title={l.who}><Icon name={l.icon} size={11} /></span>
          {/if}
          <span class="bpr-text" title="{l.who}: {l.text}" data-private="soft">{l.text}</span>
          <span class="bpr-when">{agoShort(l.at, now)}</span>
        </div>
      {:else}
        <p class="bpr-none">Nothing written yet.</p>
      {/each}
    {/if}
  </div>
</section>

<style>
  .bpr { display: flex; height: 100%; min-height: 0; flex-direction: column; gap: 10px; }
  .bpr-model { flex-shrink: 0; gap: 14px; padding: 10px; }
  .bpr-tile { position: relative; display: grid; flex-shrink: 0; place-items: center; }
  /* A small beat each time it answers. Transform and opacity, on the graphics card. */
  .bpr-pulse {
    position: absolute;
    inset: -3px;
    border-radius: 16px;
    pointer-events: none;
    background: color-mix(in srgb, var(--color-accent) 40%, transparent);
    animation: bpr-pulse 1.1s ease-out forwards;
  }
  @keyframes bpr-pulse { from { opacity: 0.8; transform: scale(0.92); } to { opacity: 0; transform: scale(1.5); } }
  .bpr-who { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 1px; }
  .bpr-name { overflow: hidden; font-size: clamp(16px, 1.2vw, 22px); font-weight: 700; letter-spacing: -0.015em; text-overflow: ellipsis; white-space: nowrap; }
  .bpr-state { overflow: hidden; font-size: 13px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; color: var(--bp-muted); }
  .bpr-state.is-on { color: var(--bp-lit); }
  .bpr-today { font-size: 12.5px; color: var(--bp-faint); }
  .bpr-limit { display: flex; flex-shrink: 0; flex-direction: column; gap: 5px; padding: 0 12px; font-size: 12px; color: var(--bp-faint); }
  .bpr-bar { display: block; height: 4px; overflow: hidden; border-radius: 999px; background: var(--bp-line); }
  .bpr-bar i { display: block; height: 100%; border-radius: 999px; background: var(--bp-lit); transform: scaleX(var(--f)); transform-origin: left; transition: transform 0.8s var(--swift); }
  .bpr-limit[data-tone="warn"] .bpr-bar i { background: var(--color-warn); }
  .bpr-limit[data-tone="bad"] .bpr-bar i { background: var(--color-bad); }
  .bpr-helper { flex-shrink: 0; padding: 0 12px; font-size: 12px; color: var(--bp-faint); }
  .bpr-helper b { font-weight: 600; color: var(--bp-muted); }

  .bpr-thought { display: flex; flex-shrink: 0; flex-direction: column; gap: 4px; padding: 6px 12px; }
  .bpr-for { font-weight: 500; }
  .bpr-thought p {
    display: -webkit-box;
    overflow: hidden;
    font-size: 13px;
    line-height: 1.45;
    color: var(--bp-muted);
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }

  .bpr-tabs { position: relative; display: flex; flex-shrink: 0; align-self: flex-start; gap: 2px; margin: 8px 0 0 6px; }
  .bpr-tabs :global(.glide-mark) {
    position: absolute;
    left: 0;
    top: 0;
    width: var(--gw, 0);
    height: var(--gh, 0);
    border-radius: 999px;
    background: var(--bp-fill);
    transform: translate3d(var(--gx, 0), var(--gy, 0), 0);
    transition: transform 0.42s var(--spring), width 0.42s var(--spring);
  }
  .bpr-tabs :global(.glide-mark.is-snap) { transition: none; }
  .bpr-tabs button { position: relative; height: 30px; padding: 0 12px; border-radius: 999px; font-size: 13px; font-weight: 600; color: var(--bp-faint); transition: color 0.2s ease; }
  .bpr-tabs button.is-active { color: var(--color-ink); }

  .bpr-list { display: flex; min-height: 0; flex: 1 1 0; flex-direction: column; gap: 1px; overflow-y: auto; }
  .bpr-list > div { flex-shrink: 0; }
  :global(.bpr-item) { gap: 10px; padding: 6px 10px; font-size: 13px; }
  .bpr-ico { display: grid; width: 26px; height: 26px; place-items: center; border-radius: 999px; color: var(--bp-muted); background: var(--bp-fill); }
  :global(.bpr-item[data-kind="sent"]) .bpr-ico { color: var(--color-good); }
  :global(.bpr-item[data-kind="limit"]) .bpr-ico { color: var(--color-warn); }
  .bpr-text { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bpr-when { flex-shrink: 0; font-size: 11.5px; color: var(--bp-faint); font-variant-numeric: tabular-nums; }
  .bpr-none { padding: 6px 12px; font-size: 13px; color: var(--bp-faint); }
  .bpr-log { display: flex; flex-shrink: 0; min-width: 0; align-items: center; gap: 8px; padding: 5px 10px; font-size: 12.5px; color: var(--bp-muted); }
  .bpr-src { display: grid; width: 18px; height: 18px; flex-shrink: 0; place-items: center; border-radius: 999px; color: var(--bp-faint); background: var(--bp-fill); }
  .bpr-log[data-level="error"] .bpr-text { color: var(--color-bad); }
  .bpr-log[data-level="warn"] .bpr-text { color: var(--color-warn); }
  .bpr-log[data-level="reply"] .bpr-text { color: var(--color-ink); }
  :global(:root[data-motion="off"]) .bpr-pulse { animation-duration: 0.01s; }
</style>
