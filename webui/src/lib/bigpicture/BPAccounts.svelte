<script lang="ts">
  /**
   * Accounts: every one as a card with its banner, its face lit by how it is doing,
   * what it has done this week. Every platform it talks on along the top, with how
   * many replies went out there this week: pressing one shows only that platform's.
   *
   * Pressing a card grows it where it stands, with the page still there around it:
   * it rises to the top of the page across the whole width and the others make room,
   * and Esc puts it back. Grown, it has what can be done from here: pause it, put it
   * in a mood, see who it talks to most, and, for a Minecraft account in a world,
   * watch what it sees. Starting and stopping stay on the Accounts page, where the
   * reasons live.
   */
  import { onDestroy, tick } from "svelte";
  import { get } from "svelte/store";
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import PlatformMark from "../components/PlatformMark.svelte";
  import { presenceName, platformName } from "../accounts/condition";
  import { fmtDate } from "../fmt";
  import { PLATFORMS, type PlatformId } from "../platforms";
  import { personasRes } from "../personas/store";
  import { motionEnabled } from "../stores";
  import { play as uiPlay } from "../uisound";
  import BPMinecraft from "./BPMinecraft.svelte";
  import { fitText } from "./fit";
  import { focusable, follow } from "./focus";
  import { burstFrom, tilt } from "./fx";
  import { popIn } from "./motion";
  import Rolling from "./Rolling.svelte";
  import { ago } from "./scenes";
  import type { BPAccount, PageActions } from "./types";
  import type { World } from "./world.svelte";

  let { world, act, now = 0, moodsOf }: { world: World; act: PageActions; now?: number; moodsOf: (id: string) => string[] } = $props();

  let openId = $state<string | null>(null);
  const accounts = $derived(world.accounts);
  const platforms = $derived.by(() => {
    const ids = [...new Set(accounts.map((a) => a.platform))];
    return ids.filter((p) => PLATFORMS[p as PlatformId])
      .map((p) => ({ id: p, n: world.weekPlatform[p] ?? 0, on: accounts.some((a) => a.platform === p && a.state === "running") }))
      .sort((a, b) => b.n - a.n || Number(b.on) - Number(a.on));
  });
  const filter = $derived(world.platformFilter);
  /** The grown one first, and only the platform asked for. */
  const shown = $derived.by(() => {
    const list = filter ? accounts.filter((a) => a.platform === filter) : accounts;
    return openId ? [...list.filter((a) => a.id === openId), ...list.filter((a) => a.id !== openId)] : list;
  });
  const running = $derived(accounts.filter((a) => a.state === "running").length);
  /**
   * How many across: as few as still shows them all on the screen, so a card is as
   * large as it can be from across the room. auto-fill left six small cards in a
   * strip along the top and the rest of the page empty.
   */
  let gridW = $state(1600);
  let gridH = $state(800);
  const cols = $derived.by(() => {
    const n = Math.max(1, shown.length - (openId ? 1 : 0));
    const most = Math.max(1, Math.floor(gridW / 320));
    let best = 1;
    for (let c = 1; c <= most; c++) {
      best = c;
      if (Math.ceil(n / c) * 300 <= gridH && gridW / c <= 640) break;
    }
    return Math.min(best, Math.max(1, n));
  });

  /** A card a good size across has a face to match. */
  const faceSize = $derived(gridW / cols > 480 ? 88 : 68);

  /** What the dot and the words say: the worker's own word when it answered, else the supervisor's. */
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
  /** Local dates, read as local: new Date("2026-09-26") would be UTC midnight, the day before for anyone west of Greenwich. */
  function dayLetter(iso: string): string {
    const [y, m, d] = (iso || "").split("-").map(Number);
    if (!y) return "";
    return fmtDate(new Date(y, (m || 1) - 1, d || 1), { weekday: "narrow" });
  }
  const week = (a: BPAccount) => (world.activity[a.id]?.series ?? []).slice(-7);
  const weekDates = $derived(world.dates.slice(-7));
  const slot = (a: BPAccount) => `${platformName(a.platform)}${a.account ? ` #${a.account}` : ""}`;
  const reachable = (a: BPAccount) => a.state === "running" && a.live;
  const persona = (a: BPAccount) => $personasRes.data.accounts[a.id] || "default";
  const personaName = (a: BPAccount) => {
    const p = $personasRes.data.personas.find((x) => x.id === persona(a));
    return p && !(p.is_default && p.name === "Default") ? p.name : "";
  };

  // ── Growing where it stands ──────────────────────────────────────────────
  // Every card told where it was and left to spring from there to where it is now.
  // The one growing, or going back, springs from the size it was too, and what is in
  // it fades up as it lands, so it is not seen stretched. Transform and opacity only,
  // on the graphics card: uncovering it with a clip-path looked the same and had the
  // card painted again every frame, which on the laptop's iGPU lost half of them.
  let gridEl: HTMLElement | null = $state(null);
  const springy = () => getComputedStyle(document.documentElement).getPropertyValue("--spring").trim() || "cubic-bezier(0.2, 0.9, 0.25, 1)";

  async function rearrange(change: () => void, growing: string | null, shrinking: string | null) {
    const grid = gridEl;
    if (!grid || !get(motionEnabled)) {
      change();
      return;
    }
    const before = new Map<string, DOMRect>();
    for (const c of grid.querySelectorAll<HTMLElement>("[data-card]")) before.set(c.dataset.card ?? "", c.getBoundingClientRect());
    change();
    await tick();
    const easing = springy();
    for (const c of grid.querySelectorAll<HTMLElement>("[data-card]")) {
      const id = c.dataset.card ?? "";
      const a = before.get(id);
      if (!a) continue;
      const b = c.getBoundingClientRect();
      const dx = a.left - b.left, dy = a.top - b.top;
      if (id === growing || id === shrinking) {
        const duration = id === growing ? 600 : 480;
        c.animate([{ transform: `translate(${dx}px, ${dy}px) scale(${a.width / b.width}, ${a.height / b.height})`, transformOrigin: "0 0" },
                   { transform: "none", transformOrigin: "0 0" }], { duration, easing });
        for (const part of Array.from(c.children)) {
          part.animate([{ opacity: 0 }, { opacity: 0, offset: 0.3 }, { opacity: 1 }], { duration, easing: "ease-out" });
        }
      } else if (dx || dy) {
        c.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }], { duration: 560, easing });
      }
    }
    follow(800);
  }

  function close() {
    const was = openId;
    if (!was) return;
    uiPlay("release");
    rearrange(() => (openId = null), null, was);
    act.onBack(null);
  }
  function toggle(a: BPAccount) {
    act.hold();
    if (openId === a.id) return close();
    const was = openId;
    uiPlay("open");
    uiPlay("land", { delay: 460, level: 0.7 });
    rearrange(() => (openId = a.id), a.id, was);
    gridEl?.scrollTo({ top: 0, behavior: get(motionEnabled) ? "smooth" : "auto" });
    act.onBack(close);
  }
  onDestroy(() => act.onBack(null));

  function setFilter(p: string | null) {
    act.hold();
    uiPlay(p ? "select" : "off");
    rearrange(() => {
      world.platformFilter = world.platformFilter === p ? null : p;
      openId = null;
    }, null, null);
    act.onBack(null);
  }

  async function pause(a: BPAccount, el: HTMLElement) {
    const paused = await world.togglePause(a);
    if (paused === undefined) return;
    uiPlay(paused ? "off" : "on");
    if (!paused) burstFrom(el, { count: 12, spread: 70 });
  }

  // The room lit by the one grown, or the first to have a picture.
  $effect(() => {
    const a = accounts.find((x) => x.id === openId);
    if (a) act.light("accounts", { seed: `accounts:${a.id}`, art: a.banner || a.avatar });
    else act.light("accounts", null);
  });
  onDestroy(() => act.light("accounts", null));
</script>

<div class="bpa">
  {#if accounts.length}
    <div class="bpa-top">
      <div class="bp-label bpa-count">{running} of {accounts.length} running</div>
      {#if platforms.length > 1}
        <div class="bpa-filter" data-sound="self">
          {#each platforms as p, i (p.id)}
            <button class="bp-chip" class:is-on={filter === p.id} use:focusable={{ id: `platform:${p.id}` }} onclick={() => setFilter(p.id)}
                    in:popIn|global={{ delay: 40 + i * 40, from: 0.9 }} title="{PLATFORMS[p.id as PlatformId].name}: {p.n} replies this week">
              <PlatformMark platform={p.id} size={20} />{PLATFORMS[p.id as PlatformId].name}<b><Rolling value={p.n} delay={60 + i * 40} /></b>
            </button>
          {/each}
        </div>
      {/if}
    </div>

    <div class="bpa-grid bp-scrolls" class:is-fill={!openId && Math.ceil(shown.length / cols) * 300 <= gridH} bind:this={gridEl}
         bind:clientWidth={gridW} bind:clientHeight={gridH} style="--cols: {cols}">
      {#each shown as a, i (a.id)}
        {@const act7 = world.activity[a.id]}
        {@const t = tone(a)}
        {@const w = week(a)}
        {@const peak = Math.max(1, ...w)}
        {@const grown = openId === a.id}
        <article class="bp-tile bpa-card" class:is-open={grown} data-tone={t} data-state={a.state} data-card={a.id}
                 use:tilt={grown ? 0 : 4} in:popIn|global={{ delay: 60 + Math.min(i, 8) * 70, from: 0.92 }}>
          <button class="bpa-main" use:focusable={{ id: `card:${a.id}` }} onclick={() => toggle(a)} aria-expanded={grown}
                  title={grown ? "Put it back (Esc)" : `More about ${a.name}`}>
            <div class="bpa-banner" style="--acc: {a.accent || 'var(--color-accent)'}">
              {#if a.banner}<img src={a.banner} alt="" referrerpolicy="no-referrer" draggable="false" decoding="async" />{/if}
            </div>
            <div class="bpa-head">
              <span class="bp-face bpa-face">
                <Avatar src={a.avatar} name={a.name} size={grown ? 96 : faceSize} zoom={false} />
                <i class="bpa-dot" title={status(a)}></i>
              </span>
              <!-- Which login it is, unless that is already its name. -->
              {#if slot(a) !== a.name}<span class="bpa-tag"><PlatformMark platform={a.platform} size={16} />{slot(a)}</span>
              {:else}<span class="bpa-tag"><PlatformMark platform={a.platform} size={16} /></span>{/if}
            </div>
            <div class="bpa-body">
              <div class="bpa-name" use:fitText={{ min: 18, text: a.name }}>{a.name}</div>
              <div class="bpa-line">
                <b>{status(a)}</b>{#if a.state === "running" && a.ping != null}{" · "}{a.ping} ms{/if}{#if a.state === "running" && a.uptime}{" · "}{uptime(a.uptime)}{/if}{#if a.mood}{" · "}<span class="bpa-mood">{a.mood}</span>{/if}
              </div>
              <div class="bpa-nums">
                <div><b><Rolling value={act7?.today ?? 0} /></b><span>today</span></div>
                <div><b><Rolling value={act7?.week ?? 0} /></b><span>this week</span></div>
                <div><b><Rolling value={act7?.people_week ?? 0} /></b><span>people</span></div>
                {#if w.length}
                  <div class="bpa-week" role="img" aria-label="Replies per day this week: {w.join(', ')}">
                    {#each w as v, d}
                      <span class="bpa-col" class:is-today={d === w.length - 1}>
                        <i style="--f: {v / peak}; --d: {d}"></i>
                        <em>{dayLetter(weekDates[d] ?? "")}</em>
                      </span>
                    {/each}
                  </div>
                {/if}
              </div>
            </div>
          </button>

          {#if grown}
            <div class="bpa-more">
              {#if a.platform === "minecraft" && world.minecraft?.id === a.id}
                <div class="bpa-view"><BPMinecraft account={a} inset /></div>
              {/if}
              <div class="bpa-side">
                {#if reachable(a)}
                  <div class="bpa-do">
                    <button class="bp-btn" class:is-go={a.paused} use:focusable={{ id: `pause:${a.id}` }} disabled={!!world.busy[a.id]} onclick={(e) => pause(a, e.currentTarget)}
                            title={a.paused ? "Let it answer again" : "Stop it replying for now; it stays online"} data-sound="self">
                      <Icon name={a.paused ? "play" : "pause"} size={14} />{a.paused ? "Resume" : "Pause"}
                    </button>
                  </div>
                  {#if moodsOf(a.id).length}
                    <div class="bp-label">Mood</div>
                    <div class="bpa-moods" data-sound="self">
                      {#each moodsOf(a.id) as m (m)}
                        <button class="bp-chip bpa-moodchip" class:is-on={a.mood === m} use:focusable={{ id: `mood:${a.id}:${m}` }}
                                disabled={!!world.busy[a.id] || a.mood === m} onclick={(e) => world.setMood(a, m, e.currentTarget)}
                                title={a.mood === m ? `${a.name} is ${m}` : `Put ${a.name} in a ${m} mood`}>{m}</button>
                      {/each}
                    </div>
                  {/if}
                {/if}
                <div class="bpa-facts">
                  {#if personaName(a)}<span>Speaks as {personaName(a)}</span>{/if}
                  {#if a.guilds != null && a.live}<span>{a.guilds} server{a.guilds === 1 ? "" : "s"}</span>{/if}
                  {#if a.friends != null && a.live}<span>{a.friends} friend{a.friends === 1 ? "" : "s"}</span>{/if}
                  {#if a.night}<span>Night hours</span>{/if}
                </div>
                <button class="bp-btn is-small bpa-page" use:focusable={{ id: `page:${a.id}` }} onclick={() => act.leaveTo("accounts")}>
                  Open Accounts<Icon name="chevron" size={13} />
                </button>
              </div>
              <div class="bpa-side">
                {#if act7?.top?.length}
                  <div class="bp-label">Talks to most</div>
                  <div class="bpa-people">
                    {#each act7.top.slice(0, 5) as p (p.id)}
                      <button class="bp-row bpa-person" use:focusable={{ id: `top:${a.id}:${p.id}` }} onclick={() => act.open(a.id, String(p.id), { name: p.name, avatar: p.avatar })} title="Open {p.name}">
                        <Avatar src={p.avatar} name={p.name} size={28} zoom={false} /><span>{p.name}</span><b>{p.count}</b>
                      </button>
                    {/each}
                  </div>
                  {#if act7.last}<div class="bpa-last">Last reply {ago(act7.last.ts, now)}, to {act7.last.name}</div>{/if}
                {/if}
              </div>
            </div>
          {/if}
        </article>
      {/each}
    </div>
  {:else}
    <div class="bp-empty">
      <b>No accounts yet</b>
      <button class="bp-btn is-go" use:focusable={{ id: "accounts:add", first: true }} onclick={() => act.leaveTo("accounts")}><Icon name="plus" size={15} />Add one</button>
    </div>
  {/if}
</div>

<style>
  .bpa { display: flex; height: 100%; min-height: 0; flex-direction: column; gap: clamp(8px, 1.4vh, 14px); }
  .bpa-top { display: flex; flex-shrink: 0; min-width: 0; flex-wrap: wrap; align-items: center; gap: 8px 14px; }
  .bpa-count { font-size: 14px; }
  .bpa-filter { display: flex; min-width: 0; flex-wrap: wrap; gap: 4px; }
  .bpa-filter b { font-weight: 700; color: var(--color-ink); }
  .bpa-filter .bp-chip.is-on b { color: inherit; }
  .bpa-filter .bp-chip { padding: 0 12px 0 7px; }

  .bpa-grid {
    display: grid;
    min-height: 0;
    flex: 1 1 0;
    grid-template-columns: repeat(var(--cols, 3), minmax(0, 1fr));
    /* As tall as what is on them, when they do not all fit and the page scrolls. A card clips its corners, so left
       to itself its row would shrink to share out the height there is, and cut the bottom off every one. */
    grid-auto-rows: max-content;
    align-content: start;
    gap: clamp(10px, 1.2vw, 20px);
    padding: 3px 3px 12px;
  }
  /* They fit: the cards share the height there is, up to a size that still looks like a card. */
  .bpa-grid.is-fill { grid-auto-rows: minmax(0, 460px); align-content: center; }
  .bpa-card {
    --tx: 0deg;
    --ty: 0deg;
    position: relative;
    min-width: 0;
    flex-direction: column;
    overflow: hidden;
    transform: perspective(900px) rotateX(var(--tx)) rotateY(var(--ty));
    transition: transform 0.5s var(--spring);
  }
  .bpa-card:global(.is-focus) { transform: perspective(900px) rotateX(var(--tx)) rotateY(var(--ty)); }
  .bpa-card.is-open { grid-column: 1 / -1; flex-direction: row; flex-wrap: wrap; transform: none; }
  .bpa-card.is-open .bpa-main { flex: 1 1 420px; }
  /* border-radius: the plate takes its corners from what has the focus, and this is what has it. */
  .bpa-main { display: flex; min-width: 0; height: 100%; flex: 1 1 auto; flex-direction: column; border-radius: inherit; text-align: left; }
  .bpa-card:active { transform: scale(0.99); }

  /* The banner melts into the card instead of ending on a line, whatever is behind the card. */
  .bpa-banner {
    position: relative;
    height: clamp(64px, 13vh, 150px);
    flex-shrink: 0;
    overflow: hidden;
    background: linear-gradient(135deg, color-mix(in srgb, var(--acc) 60%, #000), color-mix(in srgb, var(--acc) 28%, #05060c));
    -webkit-mask-image: linear-gradient(to bottom, #000 35%, transparent);
    mask-image: linear-gradient(to bottom, #000 35%, transparent);
  }
  .bpa-banner img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
  .bpa-card[data-state="stopped"] .bpa-banner,
  .bpa-card[data-state="stopped"] .bpa-face { filter: grayscale(0.85) brightness(0.8); }

  .bpa-head { position: relative; z-index: 1; display: flex; align-items: flex-end; justify-content: space-between; margin-top: calc(-1 * clamp(36px, 7vh, 72px)); padding: 0 clamp(14px, 1.2vw, 22px); }
  .bpa-dot { position: absolute; right: 1px; bottom: 1px; width: 16px; height: 16px; border-radius: 999px; background: var(--bp-faint); box-shadow: 0 0 0 3px #0e0f18; }
  .bpa-card[data-tone="good"] .bpa-dot { background: var(--color-good); }
  .bpa-card[data-tone="warn"] .bpa-dot { background: var(--color-warn); }
  .bpa-card[data-tone="bad"] .bpa-dot { background: var(--color-bad); }
  .bpa-card[data-tone="accent"] .bpa-dot { background: var(--color-accent); animation: bpa-wait 1.6s ease-in-out infinite; }
  @keyframes bpa-wait { 50% { opacity: 0.45; } }
  .bpa-tag { display: inline-flex; align-items: center; gap: 6px; margin-bottom: 3px; font-size: 12px; font-weight: 600; color: var(--bp-faint); }

  .bpa-body { position: relative; z-index: 1; display: flex; min-width: 0; flex: 1 1 auto; flex-direction: column; gap: 4px; padding: 8px clamp(14px, 1.2vw, 22px) clamp(12px, 1.2vw, 20px); }
  .bpa-name { overflow: hidden; font-size: clamp(20px, min(2vw, 3.6vh), 38px); font-weight: 750; line-height: 1.16; letter-spacing: -0.025em; text-overflow: ellipsis; white-space: nowrap; padding-block: 0.1em; margin-block: -0.1em; }
  .bpa-card.is-open .bpa-name { font-size: clamp(26px, 2.6vw, 46px); }
  .bpa-line { font-size: clamp(13px, 0.86vw, 15.5px); color: var(--bp-muted); }
  .bpa-line b { font-weight: 650; color: var(--color-ink); }
  .bpa-card[data-tone="good"] .bpa-line b { color: var(--color-good); }
  .bpa-card[data-tone="warn"] .bpa-line b { color: var(--color-warn); }
  .bpa-card[data-tone="bad"] .bpa-line b { color: var(--color-bad); }
  .bpa-mood { text-transform: capitalize; color: var(--bp-lit); }

  /* At the foot of the card, however tall it has been given. */
  .bpa-nums { display: flex; align-items: flex-end; gap: clamp(12px, 1.2vw, 24px); margin-top: auto; padding-top: 10px; }
  .bpa-nums > div:not(.bpa-week) { display: flex; flex-direction: column; }
  .bpa-nums b { font-size: clamp(20px, min(1.9vw, 3.4vh), 36px); font-weight: 750; line-height: 1.1; letter-spacing: -0.02em; }
  .bpa-nums > div > span { font-size: 12px; color: var(--bp-faint); }

  /* The week, a column a day, today lit. Grows in from the baseline one after another. */
  .bpa-week { display: grid; flex: 1 1 0; min-width: 84px; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; height: clamp(44px, 6.4vh, 72px); margin-left: auto; max-width: 240px; }
  .bpa-col { display: flex; height: 100%; min-height: 0; flex-direction: column; align-items: center; justify-content: flex-end; gap: 3px; }
  .bpa-col i {
    display: block;
    width: 100%;
    height: calc(3px + var(--f) * (100% - 14px));
    border-radius: 4px;
    background: var(--bp-line);
    transform-origin: bottom;
    animation: bpa-grow 0.8s var(--spring) both;
    animation-delay: calc(240ms + var(--d) * 50ms);
  }
  .bpa-col.is-today i { background: var(--bp-lit); }
  .bpa-col em { font-style: normal; font-size: 10px; line-height: 1; color: var(--bp-faint); }
  .bpa-col.is-today em { color: var(--bp-lit); }
  @keyframes bpa-grow { from { transform: scaleY(0); } }

  /* Grown: what can be done from here, beside it. */
  .bpa-more { display: flex; min-width: 0; flex: 2 1 480px; flex-wrap: wrap; gap: clamp(14px, 1.6vw, 28px); padding: 16px; }
  .bpa-view { min-width: 0; flex: 1.5 1 420px; }
  .bpa-side { display: flex; min-width: 240px; flex: 1 1 280px; flex-direction: column; align-items: flex-start; gap: 8px; }
  .bpa-do { display: flex; gap: 8px; margin-bottom: 4px; }
  .bpa-moods { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 6px; }
  :global(.bpa-moodchip) { text-transform: capitalize; }
  .bpa-people { display: flex; width: 100%; max-width: 380px; flex-direction: column; gap: 1px; }
  :global(.bpa-person) { gap: 10px; padding: 5px 8px; font-size: 14px; font-weight: 600; }
  :global(.bpa-person) span { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  :global(.bpa-person) b { font-weight: 600; color: var(--bp-faint); font-variant-numeric: tabular-nums; }
  .bpa-last { font-size: 12.5px; color: var(--bp-faint); }
  .bpa-facts { display: flex; flex-wrap: wrap; gap: 3px 12px; margin-top: 4px; font-size: 12.5px; color: var(--bp-faint); }
  .bpa-page { margin-top: auto; }

  @media (max-width: 720px) {
    .bpa { height: auto; }
    .bpa-grid { flex: none; overflow: visible; }
  }
  :global(:root[data-motion="off"]) .bpa-col i,
  :global(:root[data-motion="off"]) .bpa-dot { animation: none; }
  :global(:root[data-motion="off"]) .bpa-card { transform: none; }
</style>
