<script lang="ts">
  /**
   * The idle scene about the accounts themselves: every one as a card with its
   * banner, its face lit by how it is doing, what it has done this week, and
   * who it talks to most. The Accounts page, as something to look at.
   *
   * One thing can be done from here: pausing an account, or letting it answer
   * again, which is the one switch worth having within reach while watching.
   * Starting and stopping stay on the Accounts page, where the reasons live.
   */
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import { presenceName, platformName } from "../accounts/condition";
  import { fmtDate } from "../fmt";
  import Counter from "./Counter.svelte";
  import { fitText } from "./fit";
  import { popIn } from "./motion";
  import { ripple, tilt } from "./fx";
  import type { BPAccount, BPActivity } from "./types";

  let {
    accounts = [],
    activity = {},
    dates = [],
    now = 0,
    busy = {},
    onpause,
  }: {
    accounts?: BPAccount[];
    activity?: Record<string, BPActivity>;
    /** This computer's calendar day for each entry of a series, oldest first. */
    dates?: string[];
    now?: number;
    /** Accounts with a pause or resume on its way. */
    busy?: Record<string, boolean>;
    onpause?: (a: BPAccount) => void;
  } = $props();

  /** At most four: past that the cards would be too small to read across a room. */
  const shown = $derived(accounts.slice(0, 4));
  const running = $derived(accounts.filter((a) => a.state === "running").length);

  /** What the ring and the words say: the worker's own word when it answered, else the supervisor's. */
  function tone(a: BPAccount): "good" | "warn" | "bad" | "accent" | "muted" {
    if (a.state === "running") {
      if (!a.live) return "accent";
      if (a.paused) return "warn";
      if (a.presence === "idle") return "warn";
      if (a.presence === "dnd") return "bad";
      if (a.presence === "invisible" || a.presence === "offline") return "muted";
      return "good";
    }
    if (a.state === "starting") return "accent";
    if (a.state === "crashing") return "bad";
    return "muted";
  }
  function status(a: BPAccount): string {
    if (a.state === "running") {
      if (!a.live) return "Running";
      if (a.paused) return "Paused";
      return presenceName(a.presence);
    }
    if (a.state === "starting") return "Starting";
    if (a.state === "crashing") return "Crashing";
    return a.enabled === false ? "Switched off in Settings" : "Stopped";
  }
  function uptime(s?: number): string {
    if (!s) return "";
    if (s < 3600) return `up ${Math.max(1, Math.round(s / 60))} min`;
    if (s < 86400) return `up ${Math.round(s / 3600)} h`;
    return `up ${Math.round(s / 86400)} d`;
  }
  function ago(ts?: number): string {
    if (!ts) return "";
    const s = Math.max(0, now - ts);
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 86400) return `${Math.round(s / 3600)} h ago`;
    return `${Math.round(s / 86400)} d ago`;
  }
  /** Local dates, read as local: new Date("2026-09-26") would be UTC midnight, the day before for anyone west of Greenwich. */
  function dayLetter(iso: string): string {
    const [y, m, d] = (iso || "").split("-").map(Number);
    if (!y) return "";
    return fmtDate(new Date(y, (m || 1) - 1, d || 1), { weekday: "narrow" });
  }
  const week = (a: BPAccount) => (activity[a.id]?.series ?? []).slice(-7);
  const slot = (a: BPAccount) => `${platformName(a.platform)}${a.account ? ` #${a.account}` : ""}`;
  const weekDates = $derived(dates.slice(-7));

  /**
   * Rows instead of cards when the cards would not fit: three or more in a
   * stage made narrow by the queue, two in a very narrow one, or any on a short
   * screen. A card is a tall thing; a row says the same in a line.
   */
  let width = $state(0);
  let tall = $state(1080);
  const rows = $derived(shown.length >= 2 && (width < 560 || (shown.length >= 3 && width < 900) || tall < 760));
</script>

<svelte:window bind:innerHeight={tall} />

<div class="bpa" class:is-rows={rows} data-n={shown.length} bind:clientWidth={width}>
  <div class="bp-kicker" in:popIn|global={{ delay: 40, from: 0.96 }}>
    Accounts · {running} of {accounts.length} running
  </div>
  <h2 class="bp-title" in:popIn|global={{ delay: 90, from: 0.96 }}>Accounts</h2>

  <div class="bpa-grid">
    {#each shown as a, i (a.id)}
      {@const act = activity[a.id]}
      {@const t = tone(a)}
      {@const w = week(a)}
      {@const peak = Math.max(1, ...w)}
      <article class="bpa-card" class:is-row={rows} data-tone={t} data-state={a.state} use:tilt
               in:popIn|global={{ delay: 160 + i * 120, from: 0.9 }}>
        <div class="bpa-banner" style="--acc: {a.accent || 'var(--color-accent)'}">
          {#if a.banner}
            <img src={a.banner} alt="" referrerpolicy="no-referrer" draggable="false" decoding="async" />
          {/if}
        </div>
        <span class="bpa-light" aria-hidden="true"></span>

        <div class="bpa-head">
          <span class="bpa-face">
            <Avatar src={a.avatar} name={a.name} size={rows ? 52 : 84} zoom={false} />
            <i class="bpa-dot" title={status(a)}></i>
          </span>
          <!-- Which login it is, unless that is already its name. -->
          {#if !rows && slot(a) !== a.name}<span class="bpa-tag">{slot(a)}</span>{/if}
        </div>

        <div class="bpa-body">
          <div class="bpa-name" use:fitText={{ min: 18, text: a.name }}>{a.name}</div>
          <div class="bpa-line">
            <b>{status(a)}</b>{#if a.state === "running" && a.ping != null} · {a.ping} ms{/if}{#if a.state === "running" && a.uptime && !rows} · {uptime(a.uptime)}{/if}{#if rows && a.mood} · {a.mood}{/if}
          </div>

          {#if !rows}
          <div class="bpa-chips">
            {#if a.mood}<span class="bpa-chip is-mood"><Icon name="sparkle" size={12} />{a.mood}</span>{/if}
            {#if a.night}<span class="bpa-chip">Night hours</span>{/if}
            {#if a.guilds != null && a.live}<span class="bpa-chip">{a.guilds} server{a.guilds === 1 ? "" : "s"}</span>{/if}
            {#if a.friends != null && a.live}<span class="bpa-chip">{a.friends} friend{a.friends === 1 ? "" : "s"}</span>{/if}
          </div>

          <div class="bpa-nums">
            <div><b><Counter value={act?.today ?? 0} /></b><span>today</span></div>
            <div><b><Counter value={act?.week ?? 0} /></b><span>this week</span></div>
            <div><b><Counter value={act?.people_week ?? 0} /></b><span>people</span></div>
          </div>

          {#if w.length}
            <div class="bpa-week" role="img" aria-label="Replies per day this week: {w.join(', ')}">
              {#each w as v, d}
                <span class="bpa-col" class:is-today={d === w.length - 1}>
                  <i style="--f: {v / peak}; --d: {d}"></i>
                  <em>{d === w.length - 1 ? "•" : dayLetter(weekDates[d] ?? "")}</em>
                </span>
              {/each}
            </div>
          {/if}

          {#if act?.top?.length}
            <div class="bpa-top">
              <span class="bpa-faces">
                {#each act.top.slice(0, 4) as p (p.id)}
                  <span class="bpa-mini"><Avatar src={p.avatar} name={p.name} size={26} zoom={false} /></span>
                {/each}
              </span>
              <span class="bpa-top-text">
                Most with <b>{act.top[0].name}</b>{#if act.last} · last reply {ago(act.last.ts)}{/if}
              </span>
            </div>
          {/if}
          {/if}

          {#if !rows && onpause && a.state === "running" && a.live}
            <button class="bpa-btn" class:is-paused={a.paused} use:ripple onclick={() => onpause?.(a)}
                    disabled={!!busy[a.id]}
                    title={a.paused ? "Let it answer again" : "Stop it replying for now; it stays online"}>
              <Icon name={a.paused ? "play" : "pause"} size={14} />{a.paused ? "Resume" : "Pause"}
            </button>
          {/if}
        </div>

        {#if rows}
          <!-- The row's own numbers and switch, at its end. -->
          <div class="bpa-rownums">
            <div><b><Counter value={act?.today ?? 0} /></b><span>today</span></div>
            <div><b><Counter value={act?.week ?? 0} /></b><span>week</span></div>
          </div>
          {#if onpause && a.state === "running" && a.live}
            <button class="bpa-btn" class:is-paused={a.paused} use:ripple onclick={() => onpause?.(a)}
                    disabled={!!busy[a.id]} aria-label={a.paused ? "Resume" : "Pause"}
                    title={a.paused ? "Let it answer again" : "Stop it replying for now; it stays online"}>
              <Icon name={a.paused ? "play" : "pause"} size={14} />
            </button>
          {/if}
        {/if}
      </article>
    {/each}
  </div>
  {#if accounts.length > shown.length}
    <div class="bpa-more">and {accounts.length - shown.length} more on the Accounts page</div>
  {/if}
</div>

<style>
  .bpa { display: flex; height: 100%; min-width: 0; flex-direction: column; justify-content: safe center; gap: 12px; padding: 10px 6px; }
  .bpa-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 270px), 1fr));
    gap: clamp(12px, 1.6vw, 22px);
    align-items: start;
  }
  /* One account: one card, not a strip stretched across the whole stage. */
  .bpa[data-n="1"] .bpa-grid { grid-template-columns: minmax(0, 560px); justify-content: center; }
  .bpa[data-n="2"] .bpa-grid { grid-template-columns: repeat(2, minmax(0, 480px)); justify-content: center; }

  .bpa-card {
    --tx: 0deg;
    --ty: 0deg;
    position: relative;
    display: flex;
    min-width: 0;
    flex-direction: column;
    overflow: hidden;
    border-radius: 26px;
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08), 0 30px 70px -40px rgb(0 0 0 / 0.9);
    transform: perspective(900px) rotateX(var(--tx)) rotateY(var(--ty));
    transition: transform 0.5s var(--spring), box-shadow 0.3s ease;
  }
  .bpa-card[data-tone="good"] { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-good) 28%, transparent), 0 30px 70px -40px rgb(0 0 0 / 0.9); }
  /* The light the tilt carries across the card. */
  .bpa-light {
    position: absolute;
    inset: 0;
    z-index: 2;
    pointer-events: none;
    background: radial-gradient(420px circle at var(--lx, 50%) var(--ly, 0%), rgb(255 255 255 / 0.09), transparent 45%);
    opacity: 0;
    transition: opacity 0.4s ease;
  }
  .bpa-card:hover .bpa-light { opacity: 1; }

  .bpa-banner {
    position: relative;
    height: 92px;
    overflow: hidden;
    background:
      radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, var(--acc) 85%, white 10%), transparent 60%),
      linear-gradient(135deg, color-mix(in srgb, var(--acc) 70%, #000), color-mix(in srgb, var(--acc) 30%, #05060c));
  }
  .bpa-banner img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    animation: bpa-drift 22s ease-in-out infinite alternate;
    will-change: transform;
  }
  /* The banner melts into the card instead of ending on a line. */
  .bpa-banner::after { content: ""; position: absolute; inset: 0; background: linear-gradient(to bottom, transparent 35%, rgb(8 9 16 / 0.85)); }
  @keyframes bpa-drift { from { transform: scale(1.04) translate3d(0, 0, 0); } to { transform: scale(1.16) translate3d(-3%, -4%, 0); } }
  .bpa-card[data-state="stopped"] .bpa-banner,
  .bpa-card[data-state="stopped"] .bpa-face { filter: grayscale(0.85) brightness(0.8); }

  .bpa-head { position: relative; z-index: 1; display: flex; align-items: flex-end; justify-content: space-between; margin-top: -48px; padding: 0 18px; }
  .bpa-face {
    position: relative;
    display: grid;
    border-radius: 999px;
    box-shadow: 0 0 0 5px rgb(10 11 18), 0 0 0 7px rgb(255 255 255 / 0.1);
    transition: box-shadow 0.5s ease;
  }
  .bpa-card[data-tone="good"] .bpa-face { box-shadow: 0 0 0 5px rgb(10 11 18), 0 0 0 7px color-mix(in srgb, var(--color-good) 70%, transparent), 0 0 38px color-mix(in srgb, var(--color-good) 32%, transparent); animation: bpa-live 3.2s ease-in-out infinite; }
  .bpa-card[data-tone="warn"] .bpa-face { box-shadow: 0 0 0 5px rgb(10 11 18), 0 0 0 7px color-mix(in srgb, var(--color-warn) 70%, transparent); }
  .bpa-card[data-tone="bad"] .bpa-face { box-shadow: 0 0 0 5px rgb(10 11 18), 0 0 0 7px color-mix(in srgb, var(--color-bad) 70%, transparent); }
  .bpa-card[data-tone="accent"] .bpa-face { box-shadow: 0 0 0 5px rgb(10 11 18), 0 0 0 7px color-mix(in srgb, var(--color-accent) 60%, transparent); animation: bpa-wait 1.6s ease-in-out infinite; }
  @keyframes bpa-live { 50% { box-shadow: 0 0 0 5px rgb(10 11 18), 0 0 0 7px color-mix(in srgb, var(--color-good) 70%, transparent), 0 0 58px color-mix(in srgb, var(--color-good) 40%, transparent); } }
  @keyframes bpa-wait { 50% { box-shadow: 0 0 0 5px rgb(10 11 18), 0 0 0 9px color-mix(in srgb, var(--color-accent) 30%, transparent); } }
  .bpa-dot {
    position: absolute;
    right: 3px;
    bottom: 3px;
    width: 18px;
    height: 18px;
    border-radius: 999px;
    background: var(--bp-faint);
    box-shadow: 0 0 0 4px rgb(10 11 18);
  }
  .bpa-card[data-tone="good"] .bpa-dot { background: var(--color-good); }
  .bpa-card[data-tone="warn"] .bpa-dot { background: var(--color-warn); }
  .bpa-card[data-tone="bad"] .bpa-dot { background: var(--color-bad); }
  .bpa-card[data-tone="accent"] .bpa-dot { background: var(--color-accent); }
  .bpa-tag {
    margin-bottom: 6px;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 650;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--bp-muted);
    background: rgb(0 0 0 / 0.35);
  }

  .bpa-body { position: relative; z-index: 1; display: flex; min-width: 0; flex-direction: column; gap: 10px; padding: 10px 18px 18px; }
  .bpa-name {
    overflow: hidden;
    font-size: clamp(22px, 2vw, 30px);
    font-weight: 800;
    line-height: 1.16;
    letter-spacing: -0.03em;
    color: #fff;
    text-overflow: ellipsis;
    white-space: nowrap;
    /* Room above and below for an emoji, which stands taller than the letters:
       at a line height of 1 the box it is cut to sliced them flat. The margin
       takes the room back, so the layout is where it was. */
    padding-block: 0.1em;
    margin-block: -0.1em;
  }
  .bpa-line { margin-top: -6px; font-size: 13px; color: var(--bp-muted); }
  .bpa-line b { font-weight: 650; color: #fff; }
  .bpa-card[data-tone="good"] .bpa-line b { color: var(--color-good); }
  .bpa-card[data-tone="warn"] .bpa-line b { color: var(--color-warn); }
  .bpa-card[data-tone="bad"] .bpa-line b { color: var(--color-bad); }
  .bpa-chips { display: flex; min-height: 0; flex-wrap: wrap; gap: 6px; }
  .bpa-chips:empty { display: none; }
  .bpa-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 11.5px;
    color: var(--bp-muted);
    background: rgb(255 255 255 / 0.06);
  }
  .bpa-chip.is-mood { color: #fff; background: color-mix(in srgb, var(--color-accent) 30%, transparent); text-transform: capitalize; }

  .bpa-nums { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
  .bpa-nums div { display: flex; flex-direction: column; padding: 8px 11px; border-radius: 14px; background: rgb(0 0 0 / 0.22); }
  .bpa-nums b { font-size: 22px; font-weight: 800; line-height: 1.1; letter-spacing: -0.02em; color: #fff; }
  .bpa-nums span { font-size: 10.5px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--bp-faint); }

  /* The week, a column a day, today lit. Grows in from the baseline one after another. */
  .bpa-week { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 6px; height: 58px; }
  .bpa-col { display: flex; min-height: 0; flex-direction: column; align-items: center; justify-content: flex-end; gap: 4px; }
  .bpa-col i {
    display: block;
    width: 100%;
    max-width: 22px;
    height: calc(3px + var(--f) * 38px);
    border-radius: 6px 6px 3px 3px;
    background: rgb(255 255 255 / 0.16);
    transform-origin: bottom;
    animation: bpa-grow 0.9s var(--spring) both;
    animation-delay: calc(300ms + var(--d) * 70ms);
  }
  .bpa-col.is-today i { background: var(--color-accent); box-shadow: 0 0 20px color-mix(in srgb, var(--color-accent) 42%, transparent); }
  .bpa-col em { font-style: normal; font-size: 10px; line-height: 1; color: var(--bp-faint); }
  .bpa-col.is-today em { color: var(--color-accent); }
  @keyframes bpa-grow { from { transform: scaleY(0); } }

  .bpa-top { display: flex; min-width: 0; align-items: center; gap: 10px; }
  .bpa-faces { display: flex; flex-shrink: 0; }
  .bpa-mini { display: grid; margin-left: -8px; border-radius: 999px; box-shadow: 0 0 0 2px rgb(10 11 18); }
  .bpa-mini:first-child { margin-left: 0; }
  .bpa-top-text { min-width: 0; overflow: hidden; font-size: 12.5px; color: var(--bp-muted); text-overflow: ellipsis; white-space: nowrap; }
  .bpa-top-text b { font-weight: 650; color: #fff; }

  .bpa-btn {
    position: relative;
    display: inline-flex;
    align-self: flex-start;
    align-items: center;
    gap: 7px;
    height: 38px;
    padding: 0 16px;
    overflow: hidden;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 650;
    color: #fff;
    background: rgb(255 255 255 / 0.08);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.1);
    transition: transform 0.25s var(--spring), background-color 0.2s ease;
  }
  .bpa-btn:hover:not(:disabled) { transform: translateY(-1px); background: rgb(255 255 255 / 0.14); }
  .bpa-btn:active:not(:disabled) { transform: scale(0.95); }
  .bpa-btn:disabled { opacity: 0.45; }
  .bpa-btn.is-paused { background: color-mix(in srgb, var(--color-good) 32%, transparent); }
  .bpa-more { font-size: 13px; color: var(--bp-faint); text-align: center; }

  /* Rows: the same account in a line, its banner washed behind it. */
  .bpa.is-rows .bpa-grid { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .bpa-card.is-row { flex-direction: row; align-items: center; gap: 14px; padding: 12px 16px; border-radius: 22px; transform: none; }
  .bpa-card.is-row .bpa-banner { position: absolute; inset: 0; height: auto; opacity: 0.32; }
  .bpa-card.is-row .bpa-banner::after { background: linear-gradient(90deg, rgb(8 9 16 / 0.1), rgb(8 9 16 / 0.88) 55%); }
  .bpa-card.is-row .bpa-head { margin: 0; padding: 0; }
  .bpa-card.is-row .bpa-face { box-shadow: 0 0 0 3px rgb(10 11 18), 0 0 0 5px rgb(255 255 255 / 0.1); }
  .bpa-card.is-row[data-tone="good"] .bpa-face { box-shadow: 0 0 0 3px rgb(10 11 18), 0 0 0 5px color-mix(in srgb, var(--color-good) 70%, transparent); animation: none; }
  .bpa-card.is-row[data-tone="warn"] .bpa-face { box-shadow: 0 0 0 3px rgb(10 11 18), 0 0 0 5px color-mix(in srgb, var(--color-warn) 70%, transparent); }
  .bpa-card.is-row .bpa-dot { width: 13px; height: 13px; right: 0; bottom: 0; box-shadow: 0 0 0 3px rgb(10 11 18); }
  .bpa-card.is-row .bpa-body { flex: 1; gap: 2px; padding: 0; }
  .bpa-card.is-row .bpa-name { font-size: 20px; }
  .bpa-card.is-row .bpa-line { margin-top: 0; }
  .bpa-rownums { position: relative; z-index: 1; display: flex; flex-shrink: 0; gap: 14px; }
  .bpa-rownums div { display: flex; flex-direction: column; align-items: flex-end; }
  .bpa-rownums b { font-size: 20px; font-weight: 800; line-height: 1.1; color: #fff; }
  .bpa-rownums span { font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--bp-faint); }
  .bpa-card.is-row .bpa-btn { position: relative; z-index: 1; align-self: center; width: 38px; justify-content: center; padding: 0; }

  /* Three or four: smaller cards, and the week and the faces give way first. */
  .bpa[data-n="3"] .bpa-top, .bpa[data-n="4"] .bpa-top { display: none; }
  .bpa[data-n="4"] .bpa-week { display: none; }
  .bpa[data-n="4"] .bpa-banner { height: 70px; }
  @media (max-height: 820px) {
    .bpa-week, .bpa-top { display: none; }
  }
  @media (max-width: 720px) {
    .bpa[data-n="2"] .bpa-grid { grid-template-columns: minmax(0, 1fr); }
  }
  :global(:root[data-motion="off"]) .bpa-banner img,
  :global(:root[data-motion="off"]) .bpa-face,
  :global(:root[data-motion="off"]) .bpa-col i { animation: none; }
  :global(:root[data-motion="off"]) .bpa-card { transform: none; }
</style>
