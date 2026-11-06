<script lang="ts">
  /**
   * The top of Big Picture: every page by name, and who has the screen.
   *
   * The pages are words, not mystery icons, and a pill glides to the one on show,
   * with a line in it that fills as its time on the tour runs. The Now tab says who
   * is being answered, in faces, so nothing has to take the screen to say so. Past
   * them, the accounts at a glance, the time, and the buttons: Auto says whether
   * the view is walking round by itself, for how long it is held if someone has
   * their hands on it, or that it is staying where it is.
   *
   * The bar stays when the pointer goes still: the time and how the accounts are
   * doing are worth a glance from across the room, and having them vanish read as
   * the panel breaking. Only the buttons, which are chrome, sit back.
   */
  import { fade } from "svelte/transition";
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import { glide } from "../glide";
  import { focusable } from "./focus";
  import type { AutoState, Page } from "./director";
  import { popIn } from "./motion";
  import { PAGE } from "./scenes";
  import type { BPAccount, QRow } from "./types";

  let {
    tabs = [],
    page = "now",
    progress = 0,
    sceneKey = 0,
    auto,
    live = [],
    arrivals = 0,
    inboxCount = 0,
    inboxBad = false,
    accounts = [],
    clock = "",
    showClock = true,
    awake = true,
    sound = false,
    hidden = false,
    ongo,
    onauto,
    onsound,
    onhide,
    onleave,
  }: {
    tabs?: Page[];
    page?: Page;
    /** How far through its time the page on show is, 0 to 1. */
    progress?: number;
    /** Changes with every page shown, so the line starts again even when the same one comes round. */
    sceneKey?: number;
    auto: AutoState;
    /** Who is being answered right now. */
    live?: QRow[];
    arrivals?: number;
    inboxCount?: number;
    inboxBad?: boolean;
    accounts?: BPAccount[];
    clock?: string;
    showClock?: boolean;
    awake?: boolean;
    sound?: boolean;
    hidden?: boolean;
    ongo?: (p: Page) => void;
    onauto?: () => void;
    onsound?: () => void;
    onhide?: () => void;
    onleave?: () => void;
  } = $props();

  const running = $derived(accounts.filter((a) => a.state === "running").length);
  /** How the ring on Auto reads: the tour's progress, or how much of a hold is left. */
  const C = 2 * Math.PI * 7;
  const ring = $derived(auto.mode === "held" ? auto.left / Math.max(1, auto.of) : auto.mode === "pinned" ? 1 : progress);
  const autoWord = $derived(auto.mode === "pinned" ? "Staying" : auto.mode === "held" ? `${Math.ceil(auto.left)}s` : "Auto");
  const autoTip = $derived(auto.mode === "pinned" ? "Staying here. Let it walk round again (Space)"
    : auto.mode === "held" ? "Walking round again soon. Stay here (Space)" : "Walking round by itself. Stay here (Space)");

  const stateOf = (a: BPAccount) => (a.state === "running" && a.paused ? "paused" : a.state);
  const faces = $derived(live.slice(0, 3));

  // A wide row of tabs on a narrow screen scrolls, and the one on show is kept in view.
  let list: HTMLElement | null = $state(null);
  $effect(() => {
    void page;
    const box = list;
    if (!box) return;
    const t = setTimeout(() => {
      const el = box.querySelector<HTMLElement>(".bpn-tab.is-active");
      if (!el || box.scrollWidth <= box.clientWidth) return;
      const b = box.getBoundingClientRect(), r = el.getBoundingClientRect();
      box.scrollBy({ left: r.left + r.width / 2 - (b.left + b.width / 2), behavior: "smooth" });
    }, 120);
    return () => clearTimeout(t);
  });
</script>

<header class="bpn">
  <nav class="bpn-tabs" aria-label="Pages" bind:this={list} use:glide={`${page}:${tabs.length}:${faces.length}:${inboxCount}`}>
    <span class="glide-mark" aria-hidden="true">
      {#if auto.mode === "auto" && page !== "now"}
        {#key sceneKey}<i class="bpn-fill" style="--p: {progress}"></i>{/key}
      {/if}
    </span>
    {#each tabs as t, i (t)}
      <button class="bpn-tab" class:is-active={t === page} use:focusable={{ id: `tab:${t}` }} onclick={() => ongo?.(t)}
              title="{PAGE[t].label}{i < 9 ? ` (${i + 1})` : ''}" aria-current={t === page ? "page" : undefined}
              data-tab={t} data-sound="self" in:popIn|global={{ delay: 40 + i * 36, from: 0.88 }}>
        {#if t === "now" && faces.length}
          <!-- Who is being answered. A message coming in gives them a little bounce. -->
          {#key arrivals}
            <span class="bpn-faces">
              {#each faces as r (r.key)}
                <span class="bpn-face"><Avatar src={r.u.avatar} name={r.u.name} size={22} zoom={false} /></span>
              {/each}
            </span>
          {/key}
        {/if}
        <span>{PAGE[t].label}</span>
        {#if t === "inbox"}<b class="bpn-n" data-tone={inboxBad ? "bad" : "warn"}>{inboxCount}</b>{/if}
      </button>
    {/each}
  </nav>

  <div class="bpn-right">
    <button class="bpn-accts" onclick={() => ongo?.("accounts")} title="{running} of {accounts.length} running" aria-label="Accounts">
      {#each accounts.slice(0, 8) as a (a.id)}
        <span class="bpn-acct" data-state={stateOf(a)}><Avatar src={a.avatar} name={a.name} size={24} zoom={false} /><i></i></span>
      {/each}
    </button>
    {#if showClock}<div class="bpn-clock" transition:fade={{ duration: 260 }}>{clock}</div>{/if}
    <div class="bpn-ctrls" class:is-back={!awake}>
      <button class="bp-btn is-small bpn-auto" data-mode={auto.mode} onclick={onauto} title={autoTip} aria-label={autoTip}>
        <svg viewBox="0 0 18 18" aria-hidden="true">
          <circle cx="9" cy="9" r="7" class="track" />
          <circle cx="9" cy="9" r="7" class="fill" style="stroke-dasharray: {C}; stroke-dashoffset: {C * (1 - ring)}" />
        </svg>
        <span class="bpn-auto-word">{autoWord}</span>
      </button>
      <button class="bp-btn is-small is-round" class:is-lit={sound} onclick={onsound} title="Sound (M)" aria-label="Sound" aria-pressed={sound}>
        <Icon name={sound ? "speaker" : "speakerOff"} size={16} />
      </button>
      <button class="bp-btn is-small is-round" class:is-on={hidden} onclick={onhide} title="Hide what is written and the pictures (H)"
              aria-label="Hide text" aria-pressed={hidden}>
        <Icon name={hidden ? "eyeOff" : "eye"} size={16} />
      </button>
      <button class="bp-btn is-small is-round bpn-leave" onclick={onleave} title="Leave Big Picture (Esc)" aria-label="Leave Big Picture">
        <Icon name="close" size={16} />
      </button>
    </div>
  </div>
</header>

<style>
  .bpn {
    position: relative;
    z-index: 2;
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 16px;
    padding: clamp(10px, 1.8vh, 20px) var(--bp-side) clamp(6px, 1vh, 12px);
  }
  .bpn-tabs {
    position: relative;
    display: flex;
    min-width: 0;
    flex: 1 1 auto;
    align-items: center;
    gap: 2px;
    overflow-x: auto;
    scrollbar-width: none;
  }
  .bpn-tabs::-webkit-scrollbar { display: none; }
  /* Under the tab on show, and carried to the next on a spring (lib/glide.ts). */
  .bpn-tabs :global(.glide-mark) {
    position: absolute;
    left: 0;
    top: 0;
    width: var(--gw, 0);
    height: var(--gh, 0);
    overflow: hidden;
    border-radius: 999px;
    pointer-events: none;
    background: var(--bp-fill-hi);
    transform: translate3d(var(--gx, 0), var(--gy, 0), 0);
    transition: transform 0.46s var(--spring), width 0.46s var(--spring), opacity 0.2s ease;
  }
  .bpn-tabs :global(.glide-mark.is-snap) { transition: none; }
  /* How long the page has left on the tour: scaled, not resized, so it composites. */
  .bpn-fill {
    position: absolute;
    left: 14px;
    right: 14px;
    bottom: 4px;
    height: 2px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--bp-lit) 75%, transparent);
    transform: scaleX(var(--p));
    transform-origin: left;
    transition: transform 1s linear;
  }
  .bpn-tab {
    position: relative;
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 8px;
    height: clamp(38px, 4.6vh, 46px);
    padding: 0 clamp(12px, 1.1vw, 20px);
    border-radius: 999px;
    font-size: clamp(14px, 1.02vw, 18px);
    font-weight: 650;
    white-space: nowrap;
    color: var(--bp-faint);
    transition: color 0.25s ease, transform 0.45s var(--jelly);
  }
  .bpn-tab:hover, .bpn-tab:global(.is-focus) { color: var(--color-ink); }
  .bpn-tab.is-active { color: var(--color-ink); }
  .bpn-tab:active { transform: scale(0.94); transition-duration: 0.09s; }
  .bpn-faces { display: inline-flex; animation: bpn-bounce 0.6s var(--jelly); }
  .bpn-face { display: grid; margin-left: -7px; border-radius: 999px; }
  .bpn-face:first-child { margin-left: 0; }
  @keyframes bpn-bounce { from { transform: scale(0.8); } }
  .bpn-n {
    min-width: 20px;
    padding: 0 6px;
    border-radius: 999px;
    font-size: 11.5px;
    line-height: 20px;
    text-align: center;
    color: var(--color-bg);
    background: var(--color-warn);
  }
  .bpn-n[data-tone="bad"] { color: #fff; background: var(--color-bad); }

  .bpn-right { display: flex; flex-shrink: 0; align-items: center; gap: clamp(10px, 1vw, 18px); }
  .bpn-accts { display: flex; padding: 4px; border-radius: 999px; transition: transform 0.45s var(--jelly); }
  .bpn-accts:active { transform: scale(0.95); }
  .bpn-acct { position: relative; display: grid; margin-left: -5px; border-radius: 999px; }
  .bpn-acct:first-child { margin-left: 0; }
  .bpn-acct i { position: absolute; right: -1px; bottom: -1px; width: 8px; height: 8px; border-radius: 999px; background: var(--bp-faint); }
  .bpn-acct[data-state="running"] i { background: var(--color-good); }
  .bpn-acct[data-state="paused"] i { background: var(--color-warn); }
  .bpn-acct[data-state="crashing"] i { background: var(--color-bad); }
  .bpn-acct[data-state="starting"] i { background: var(--color-accent); }
  .bpn-acct[data-state="stopped"] { opacity: 0.55; }
  .bpn-clock { font-size: clamp(14px, 1.02vw, 18px); font-weight: 600; color: var(--bp-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .bpn-ctrls { display: flex; align-items: center; gap: 6px; transition: opacity 0.6s ease; }
  .bpn-ctrls.is-back { opacity: 0.3; }
  .bpn-ctrls:hover, .bpn-ctrls:focus-within { opacity: 1; }
  .bpn-auto { gap: 7px; padding: 0 12px 0 9px; font-variant-numeric: tabular-nums; }
  .bpn-auto svg { width: 18px; height: 18px; transform: rotate(-90deg); }
  .bpn-auto circle { fill: none; stroke-width: 2.2; }
  .bpn-auto .track { stroke: var(--bp-line); }
  /* A ring is drawn on the page's own thread, every frame its arc moves: a smooth second's worth of it, begun again
     every second, was a style pass at the screen's 143 a second for as long as the view was open, and most of what it
     cost sitting still. Four steps a second look the same on a ring this size. */
  .bpn-auto .fill { stroke: var(--bp-lit); stroke-linecap: round; transition: stroke-dashoffset 1s steps(4, jump-none); }
  /* As wide whatever it says, so nothing beside it moves as it counts down. */
  .bpn-auto-word { min-width: 3.1em; text-align: left; }
  .bpn-auto[data-mode="pinned"] { color: var(--bp-on); background: var(--color-accent); }
  .bpn-auto[data-mode="pinned"] .track { stroke: transparent; }
  .bpn-auto[data-mode="pinned"] .fill { stroke: currentColor; }
  .bpn-leave:hover :global(svg) { color: var(--color-bad); }
  @media (max-width: 1100px) {
    .bpn-accts { display: none; }
  }
  /* A phone: the tabs get a row of their own under the buttons. */
  @media (max-width: 720px) {
    .bpn { flex-wrap: wrap; gap: 8px; }
    .bpn-tabs { order: 2; flex-basis: 100%; }
    .bpn-right { width: 100%; justify-content: space-between; }
  }
  :global(:root[data-motion="off"]) .bpn-faces { animation: none; }
  :global(:root[data-motion="off"]) .bpn-tabs :global(.glide-mark),
  :global(:root[data-motion="off"]) .bpn-fill,
  :global(:root[data-motion="off"]) .bpn-auto .fill { transition: none; }
</style>
