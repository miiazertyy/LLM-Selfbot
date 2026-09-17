<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "./lib/api";
  import { visiblePoll } from "./lib/poll";
  import { appearance, appearanceVersion, customBgOn, customBgDim, loadAppearance } from "./lib/stores";
  import { applyCustomFace } from "./lib/fonts";
  import { toasts, snowEnabled, motionEnabled, themeId, fontId, health, loadPrefs,
           logoOpens, logoLinkOff } from "./lib/stores";
  import { applyTheme } from "./lib/themes";
  import { applyFont } from "./lib/fonts";
  import logo from "./assets/icon.png";
  import { startChatPrefetch } from "./lib/chats";
  import { checkDescribeOnce } from "./lib/pictures";
  import { waitForBridge, isDesktop, minimize, closeWindow, startResize, setSize,
           openExternal } from "./lib/window";
  import CommandPalette from "./lib/components/CommandPalette.svelte";
  import Icon from "./lib/components/Icon.svelte";
  import Snow from "./lib/components/Snow.svelte";
  import PageIssues from "./lib/components/PageIssues.svelte";
  import LoadingBadge from "./lib/components/LoadingBadge.svelte";
  import Modal from "./lib/components/Modal.svelte";
  import Button from "./lib/components/Button.svelte";

  // Grouped by what you're actually doing, not by an arbitrary split.
  // Pages load on demand. Importing all nine statically put every page in one
  // chunk, so opening the Dashboard paid to download, parse and compile
  // Settings, System and Chats as well.
  const routes: Record<string, { title: string; icon: string; load: () => Promise<any>; section: string }> = {
    dashboard: { title: "Dashboard", icon: "dashboard", load: () => import("./pages/Dashboard.svelte"), section: "Run" },
    accounts:  { title: "Accounts",  icon: "accounts",  load: () => import("./pages/Accounts.svelte"),  section: "Run" },
    chats:     { title: "Chats",     icon: "chats",     load: () => import("./pages/Chats.svelte"),     section: "Run" },
    persona:   { title: "Persona",   icon: "persona",   load: () => import("./pages/Persona.svelte"),   section: "Brain" },
    memory:    { title: "Memory",    icon: "memory",    load: () => import("./pages/Memory.svelte"),    section: "Brain" },
    pictures:  { title: "Pictures",  icon: "pictures",  load: () => import("./pages/Pictures.svelte"),  section: "Brain" },
    logs:      { title: "Logs",      icon: "logs",      load: () => import("./pages/Logs.svelte"),      section: "Insight" },
    settings:  { title: "Settings",  icon: "settings",  load: () => import("./pages/Settings.svelte"),  section: "Setup" },
    system:    { title: "System",    icon: "system",    load: () => import("./pages/System.svelte"),    section: "Setup" },
  };

  // Resolved page components, so revisiting a tab is synchronous and never
  // flashes an empty frame the way re-awaiting the import would.
  const pageCache = new Map<string, any>();
  let page = $state<{ key: string; comp: any } | null>(null);
  const SECTIONS = ["Run", "Brain", "Insight", "Setup"] as const;

  let route = $state("dashboard");

  $effect(() => {
    const key = route;
    const hit = pageCache.get(key);
    if (hit) {
      page = { key, comp: hit };
      return;
    }
    routes[key].load().then((m) => {
      pageCache.set(key, m.default);
      // Ignore a load that finished after the user already moved on.
      if (route === key) page = { key, comp: m.default };
    });
  });
  let paletteOpen = $state(false);
  let desktop = $state(false);

  // ── Pocket mode ─────────────────────────────────────────────────────────
  // The window opens small. Below RAIL_AT the sidebar collapses to an icon
  // rail so the whole panel still works at ~400px wide; the expand button
  // grows the window to desk size when you need room.
  const RAIL_AT = 720;
  const POCKET = { w: 430, h: 620 };
  const DESK = { w: 1180, h: 780 };

  let winW = $state(typeof window === "undefined" ? 1200 : window.innerWidth);
  let pinned = $state(false);           // user forced the sidebar open
  const rail = $derived(winW < RAIL_AT && !pinned);
  const pocket = $derived(winW < RAIL_AT);

  function toggleSize() {
    const t = pocket ? DESK : POCKET;
    setSize(t.w, t.h);
  }

  // ── Travelling active indicator ─────────────────────────────────────────
  // One pill + one bar that SLIDE to the selected item, rather than a marker
  // that disappears here and reappears there. Measured from the real DOM so it
  // tracks the rail/expanded widths and the section headings automatically.
  let navEl: HTMLElement | null = $state(null);
  let mark = $state({ y: 0, h: 0, ready: false });

  function measure() {
    const el = navEl?.querySelector('[data-active="true"]') as HTMLElement | null;
    if (!el) return;
    const y = el.offsetTop;
    const h = el.offsetHeight;
    // Idempotent: nothing to do if the selection has not actually moved. This
    // is what stops a measure -> state write -> DOM change -> measure loop,
    // which Svelte aborts with effect_update_depth_exceeded, and that error
    // tears down the effect tree, freezing the indicator for good.
    if (mark.ready && y === mark.y && h === mark.h) return;
    mark = { y, h, ready: true };
  }

  /**
   * Watch the DOM for the selection actually moving, rather than trying to
   * re-run on a state change.
   *
   * This was an effect that read `route` and `rail` to re-measure on either.
   * It ran exactly once, at mount, and never again - so the pill and bar sat
   * wherever they first rendered and never followed the selection. Reading the
   * state in the effect body did not re-trigger it, whether the reads were
   * bare statements or passed as call arguments.
   *
   * A MutationObserver removes the question entirely: the browser tells us the
   * moment `data-active` moves to another button, which is exactly the event
   * the indicator cares about. It fires for every route change no matter what
   * caused it, a click, the hash, or the command palette. Only `data-active`
   * is watched: the pill and bar live inside the nav too, so watching `class`
   * or `style` would let their own updates retrigger the observer forever.
   * Rail changes come through the resize handler instead.
   */
  $effect(() => {
    if (!navEl) return;
    const observer = new MutationObserver(() => measure());
    observer.observe(navEl, {
      attributes: true,
      attributeFilter: ["data-active"],
      subtree: true,
    });

    // Collapsing to the rail moves every item, but it only changes classes,
    // not `data-active`, so the observer above never saw it and the indicator
    // stayed put until the next click. The sidebar animates between 212px and
    // 52px, so watching the nav's own size catches it - and the window resize
    // and late font loads at the same time. Sizes are unaffected by the
    // indicator itself, so this cannot feed back into a loop.
    const resize = new ResizeObserver(() => measure());
    resize.observe(navEl);

    measure();
    return () => {
      observer.disconnect();
      resize.disconnect();
    };
  });

  onMount(() => {
    waitForBridge().then(() => (desktop = isDesktop()));
    parseHash();

    // The stored preferences win over whatever this browser happens to hold,
    // so the panel looks the same after a relaunch, on a different port, or
    // opened from a phone.
    loadPrefs();

    const onResize = () => {
      winW = window.innerWidth;
      requestAnimationFrame(measure);
    };
    window.addEventListener("resize", onResize);
    onResize();

    // Attention dots: what is broken, and which page fixes it.
    const pollHealth = async () => {
      try {
        const h = await api.health();
        // Only accept a well-formed answer. A proxy error page or the SPA
        // fallback can return 200 with HTML, and storing that would leave
        // `issues` undefined and take the whole sidebar down with it.
        if (h && Array.isArray(h.issues) && h.routes) health.set(h);
      } catch {
        /* the panel keeps working if this one call fails */
      }
    };
    pollHealth();
    const stopHealthPoll = visiblePoll(pollHealth, 15000);

    // Asking an account who is waiting is an IPC round trip to the bot, slow
    // enough that fetching it when the Chats tab opens meant a skeleton every
    // time. Keeping every account warm from app start makes the tab instant.
    const stopChatPrefetch = startChatPrefetch();

    // A describe pass survives a page reload, so pick it up rather than
    // leaving the bar hidden until someone opens Pictures.
    checkDescribeOnce();

    // Whether a backdrop and a typeface have been uploaded. Needed at startup,
    // not just when the Appearance tab is opened, because both apply app-wide.
    loadAppearance();

    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        paletteOpen = !paletteOpen;
      }
    };
    window.addEventListener("hashchange", parseHash);
    window.addEventListener("keydown", onKey);

    return () => {
      stopHealthPoll();
      stopChatPrefetch();
      window.removeEventListener("resize", onResize);
      window.removeEventListener("hashchange", parseHash);
      window.removeEventListener("keydown", onKey);
    };
  });

  $effect(() => {
    document.documentElement.dataset.motion = $motionEnabled ? "full" : "off";
  });

  // Register the uploaded typeface whenever it changes, so picking "Yours" in
  // the Typeface panel has a face to resolve to.
  $effect(() => {
    applyCustomFace($appearance.font.present ? ($appearance.font.format || "") : "", $appearanceVersion);
  });

  /**
   * The uploaded image, painted as two background layers on <body>.
   *
   * A fixed element behind the app would have meant relying on how negative
   * z-index interacts with the root background propagating to the canvas,
   * which is exactly the sort of thing that renders differently in a webview.
   * Two background layers on one element have no such ambiguity, and because
   * the scrim is written in terms of var(--color-bg) it re-tints itself when
   * the theme changes rather than needing to be recomputed.
   */
  $effect(() => {
    const root = document.documentElement;
    const on = $customBgOn && $appearance.background.present;
    if (!on) {
      root.style.removeProperty("--app-backdrop");
      root.style.removeProperty("--app-backdrop-scrim");
      return;
    }
    const pct = Math.round(Math.min(1, Math.max(0, $customBgDim)) * 100);
    const scrim = `color-mix(in srgb, var(--color-bg) ${pct}%, transparent)`;
    root.style.setProperty(
      "--app-backdrop",
      `url("/api/appearance/background?v=${$appearanceVersion}")`,
    );
    root.style.setProperty("--app-backdrop-scrim", `linear-gradient(${scrim}, ${scrim})`);
  });

  $effect(() => {
    applyTheme($themeId);
  });

  $effect(() => {
    applyFont($fontId);
  });

  function parseHash() {
    const h = window.location.hash.replace(/^#\/?/, "");
    if (h && routes[h]) route = h;
  }

  function navigate(r: string) {
    route = r;
    window.location.hash = `/${r}`;
  }


  // ── The mark in the corner ────────────────────────────────────────────────
  // It opens the page the app is named after. Offered as something you can
  // turn off from the second time, because an easter egg with no way out is
  // just a misclick that keeps happening.
  const LIS = "https://en.wikipedia.org/wiki/Life_Is_Strange";
  let askStop = $state(false);

  function tapLogo() {
    if ($logoLinkOff) return;
    openExternal("lifeisstrange", LIS);
    const times = $logoOpens + 1;
    logoOpens.set(times);
    // Asked once, on the second time, and then never again either way: a
    // question that comes back every time is the same nuisance in a new hat.
    if (times === 2) askStop = true;
  }
</script>

<Modal open={askStop} title="Opening that page" onclose={() => (askStop = false)}>
  <p class="text-[13px] leading-relaxed text-muted">
    The mark in the corner opens the Life Is Strange page, which is where the
    bot's face comes from. That is twice now, so: keep it, or stop?
  </p>
  <div class="mt-4 flex justify-end gap-2">
    <Button kind="ghost" onclick={() => { logoLinkOff.set(true); askStop = false; }}>
      Stop opening it
    </Button>
    <Button onclick={() => (askStop = false)}>Keep it</Button>
  </div>
</Modal>

<!-- ── Window chrome ─────────────────────────────────────────────────────────
     Frameless: no OS title bar, the app fills the window. This strip is the
     drag handle and carries the only two controls. -->
{#if desktop}
  <div class="fixed right-2 top-1.5 z-50 flex items-center gap-1">
    <button
      onclick={toggleSize}
      class="jelly flex h-7 w-7 items-center justify-center rounded-lg text-muted hover:bg-white/10 hover:text-ink"
      title={pocket ? "Expand" : "Shrink to pocket"}
      aria-label={pocket ? "Expand window" : "Shrink window"}
    >
      <Icon name={pocket ? "expand" : "collapse"} size={14} />
    </button>
    <button
      onclick={minimize}
      class="jelly flex h-7 w-7 items-center justify-center rounded-lg text-muted hover:bg-white/10 hover:text-ink"
      title="Minimise"
      aria-label="Minimise"
    >
      <Icon name="minimize" size={15} />
    </button>
    <button
      onclick={closeWindow}
      class="jelly flex h-7 w-7 items-center justify-center rounded-lg text-muted hover:bg-bad/20 hover:text-bad"
      title="Close"
      aria-label="Close"
    >
      <Icon name="close" size={15} />
    </button>
  </div>
{/if}

<div class="flex h-screen overflow-hidden">
  <!-- ── Sidebar ─────────────────────────────────────────────────────── -->
  <aside
    class="z-20 flex shrink-0 flex-col border-r border-edge bg-surface/70
           {rail ? 'w-[52px]' : 'w-[212px]'}"
    style="transition: width 0.42s var(--spring)"
  >
    <!-- The strip is the window drag handle, and it was empty. The mark sits
         in it: the same height as the header beside it, so the two line up,
         and the name appears only when there is width for it. -->
    <!-- Centred in the rail, like every nav item below it. Keeping the
         expanded padding here put the mark 5px left of the icon column, which
         is exactly far enough to look like a mistake. -->
    <div class="pywebview-drag-region flex h-9 shrink-0 items-center gap-2
                {rail ? 'justify-center px-0' : 'px-3'}">
      <button
        onclick={tapLogo}
        class="no-drag shrink-0 rounded transition-transform {$logoLinkOff
          ? 'cursor-default'
          : 'hover:scale-110 active:scale-95'}"
        title={$logoLinkOff ? "LLMSelfbot" : "Life Is Strange"}
        aria-label={$logoLinkOff ? "LLMSelfbot" : "Open the Life Is Strange page"}
      >
        <img
          src={logo}
          alt=""
          class="h-[18px] w-[18px] shrink-0 select-none opacity-90"
          draggable="false"
        />
      </button>
      {#if !rail}
        <span class="truncate text-[12px] font-medium tracking-wide text-ink/80">LLMSelfbot</span>
      {/if}
    </div>

    <nav bind:this={navEl} class="relative flex-1 overflow-y-auto overflow-x-hidden px-2 pb-2">
      <!-- Sliding highlight: travels between items with a spring, squashing
           slightly while in motion. -->
      {#if mark.ready}
        <!-- Keyed on the route so it is torn down and rebuilt at the new
             position: that is the teleport, and it replays the land animation.
             The bar is NOT keyed, so it persists and slides across. -->
        {#key route}
          <div class="nav-pill" style="transform: translateY({mark.y}px); height: {mark.h}px;"></div>
        {/key}
        <div class="nav-bar" style="transform: translateY({mark.y}px); height: {mark.h}px;"></div>
      {/if}
      {#each SECTIONS as section, si}
        <!-- No separator above the FIRST group: it only added dead space at
             the top of the rail. Dividers/headings go between groups. -->
        {#if rail}
          {#if si > 0}<div class="mx-2 my-1.5 h-px bg-edge/70"></div>{/if}
        {:else}
          <div
            class="px-2.5 pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-faint
              {si === 0 ? 'pt-0.5' : 'pt-3'}"
          >
            {section}
          </div>
        {/if}
        {#each Object.entries(routes).filter(([, r]) => r.section === section) as [key, r]}
          <button
            onclick={() => navigate(key)}
            data-active={route === key}
            title={rail ? r.title : ""}
            class="nav-item relative z-10 flex w-full items-center gap-2.5 rounded-[10px] py-[7px] text-left text-[13px]
              {rail ? 'justify-center px-0' : 'px-2.5'}
              {route === key ? 'font-medium text-ink' : 'text-muted hover:bg-white/[0.05] hover:text-ink'}"
          >
            <span class="nav-icon relative shrink-0 {route === key ? 'is-active text-accent' : ''}">
              <Icon name={r.icon} size={16} />
              {#if ($health.routes ?? {})[key]}
                <!-- Something on this page needs attention. The dot rides on
                     the icon so it stays visible in the collapsed rail. -->
                <span
                  class="attention-dot {$health.routes[key] === 'error'
                    ? 'is-error'
                    : $health.routes[key] === 'info'
                      ? 'is-info'
                      : 'is-warn'}"
                  title={($health.issues ?? []).filter((i) => i.route === key).map((i) => i.title).join(" · ")}
                ></span>
              {/if}
            </span>
            {#if !rail}<span class="truncate">{r.title}</span>{/if}
          </button>
        {/each}
      {/each}
    </nav>

    <div class="space-y-0.5 border-t border-edge p-2">
      <button
        onclick={() => (paletteOpen = true)}
        title={rail ? "Search (Ctrl K)" : ""}
        class="nav-item flex w-full items-center gap-2.5 rounded-[10px] py-[7px] text-left text-[12px] text-muted hover:bg-white/[0.06] hover:text-ink
          {rail ? 'justify-center px-0' : 'px-2.5'}"
      >
        <Icon name="search" size={15} class="shrink-0" />
        {#if !rail}
          <span>Search</span>
          <kbd class="ml-auto rounded border border-edge px-1.5 py-px text-[10px] text-faint">Ctrl K</kbd>
        {/if}
      </button>
      {#if pocket}
        <button
          onclick={() => (pinned = !pinned)}
          title={pinned ? "Collapse menu" : "Expand menu"}
          class="nav-item flex w-full items-center gap-2.5 rounded-[10px] py-[7px] text-left text-[12px] text-muted hover:bg-white/[0.06] hover:text-ink
            {rail ? 'justify-center px-0' : 'px-2.5'}"
        >
          <Icon name={pinned ? "collapse" : "rail"} size={15} class="shrink-0" />
          {#if !rail}<span>Collapse menu</span>{/if}
        </button>
      {/if}
    </div>
  </aside>

  <!-- ── Main ────────────────────────────────────────────────────────── -->
  <main class="flex min-w-0 flex-1 flex-col">
    <!-- The window controls are a fixed overlay pinned to the top right corner,
         not part of this row, so anything laid out here runs straight underneath
         them. The padding keeps that corner clear. -->
    <header
      class="pywebview-drag-region flex h-9 shrink-0 items-center gap-2 border-b border-edge bg-surface/70 px-4
        {desktop ? 'pr-[104px]' : ''}"
    >
      <h1 class="text-[13px] font-medium text-ink">{routes[route]?.title ?? ""}</h1>
      <div class="pywebview-drag-region h-full flex-1"></div>
      <!-- In the header rather than floating over the page: it never collides
           with a toast, it never moves the content, and it is in the same place
           whichever tab you are on. -->
      <LoadingBadge />
    </header>

    <div class="min-h-0 flex-1 overflow-y-auto">
      {#if routes[route]}
        {#key route}
          <div class="page-enter pb-16 {pocket ? 'p-3' : 'p-6'}">
            <!-- Whatever is wrong on THIS page, named precisely. The sidebar
                 dot points at the tab; this points at the control. -->
            <PageIssues {route} />
            {#if page && page.key === route}
              {@const Page = page.comp}
              <Page />
            {/if}
          </div>
        {/key}
      {/if}
    </div>
  </main>
</div>

<CommandPalette
  open={paletteOpen}
  onclose={() => (paletteOpen = false)}
  {routes}
  onpick={(id) => navigate(id)}
/>

<!-- Corner resize grip, frameless windows have no native resize border. -->
{#if desktop}
  <div
    class="resize-grip no-drag"
    role="separator"
    aria-label="Resize window"
    onpointerdown={startResize}
  ></div>
{/if}

<Snow enabled={$snowEnabled} />

<div class="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col items-end gap-2">
  {#each $toasts as t}
    <div
      class="toast-in glass max-w-xs px-4 py-3 text-sm shadow-xl {t.kind === 'err'
        ? 'border-bad/40 text-bad'
        : t.kind === 'ok'
          ? 'border-good/40 text-good'
          : 'text-ink'}"
    >
      {t.text}
    </div>
  {/each}
</div>
