<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { api } from "./lib/api";
  import { visiblePoll } from "./lib/poll";
  import { appearance, appearanceVersion, customBgOn, customBgDim, loadAppearance,
           backdropId, surfaceId } from "./lib/stores";
  import { RIPPLE_RINGS } from "./lib/backdrops";
  import { applyCustomFace } from "./lib/fonts";
  import { toasts, toast, snowEnabled, motionEnabled, themeId, fontId, health, loadPrefs,
           logoLinkOff, bigPicture, bigPictureArriving, bigPictureCovering, setBigPicture,
           uiSound, uiVolume, settingsPath, settingsSection } from "./lib/stores";
  import { TABS } from "./lib/settingsmap";
  import { installUISounds, play as playSound } from "./lib/uisound";
  import { installFeel } from "./lib/feel";
  import { installSmoothScroll } from "./lib/smoothscroll";
  import { applyTheme } from "./lib/themes";
  import { applyFont } from "./lib/fonts";
  import logo from "./assets/icon.png";
  import { startChatLive, startChatPrefetch } from "./lib/chats";
  import { warmPages } from "./lib/warm";
  import { busyRoutes, doneRoutes, progressText } from "./lib/busy";
  import ProgressRing from "./lib/components/ProgressRing.svelte";
  import { checkDescribeOnce } from "./lib/pictures";
  import { waitForBridge, isDesktop, minimize, closeWindow, startResize, setSize,
           openExternal, openUrl } from "./lib/window";
  import { loadDevice, inPhoneApp } from "./lib/device";
  import CommandPalette from "./lib/components/CommandPalette.svelte";
  import GlobalMenu from "./lib/components/GlobalMenu.svelte";
  import AskHost from "./lib/components/AskHost.svelte";
  import { cascade } from "./lib/cascade";
  import { paletteRequest, menu as contextMenu, type MenuEntry } from "./lib/contextmenu";
  import Icon from "./lib/components/Icon.svelte";
  import Snow from "./lib/components/Snow.svelte";
  import PageIssues from "./lib/components/PageIssues.svelte";
  import LoadingBadge from "./lib/components/LoadingBadge.svelte";

  // Big Picture Mode's code, fetched the first time it is opened, or before:
  // once the app has settled and is idle, so the first open does not wait on
  // downloading and compiling it.
  let BigPictureView = $state<any>(null);
  const loadBigPicture = () => import("./lib/bigpicture/BigPicture.svelte").then((m) => (BigPictureView = m.default));
  $effect(() => {
    if ($bigPicture && !BigPictureView) loadBigPicture();
  });
  // Clicks, ticks and chimes for the whole app (lib/uisound.ts).
  onMount(installUISounds);
  onMount(installFeel);
  // A mouse wheel's notches glide, in every box that scrolls (lib/smoothscroll.ts).
  onMount(installSmoothScroll);

  // Away from the window (another app in front, a game): the background's slow drift and the Dashboard's glow are
  // held still (app.css, :root[data-away]). They ran all day, every glass panel blurred over them afresh each frame,
  // with nobody looking. A moment after leaving, so a click on another window and straight back changes nothing.
  onMount(() => {
    let t = 0;
    const away = () => {
      clearTimeout(t);
      t = window.setTimeout(() => (document.documentElement.dataset.away = ""), 1500);
    };
    const back = () => {
      clearTimeout(t);
      delete document.documentElement.dataset.away;
    };
    window.addEventListener("blur", away);
    window.addEventListener("focus", back);
    if (!document.hasFocus()) away();
    return () => {
      clearTimeout(t);
      window.removeEventListener("blur", away);
      window.removeEventListener("focus", back);
    };
  });

  /** The speaker's slider: how loud, and moving it while muted turns the sounds back on. */
  function setVolume(v: number) {
    uiVolume.set(v);
    if (!$uiSound && v > 0) uiSound.set(true);
  }

  // The volume bar opens under the pointer, from the keyboard, and stays open through a drag that strays off it.
  // The header knows too: the window's buttons sit over its corner, so it makes room as the bar opens and what is
  // beside them (the loading mark) moves along instead of ending up under the bar.
  let volHover = $state(false);
  let volKey = $state(false);
  let volDrag = $state(false);
  const volOpen = $derived(volHover || volKey || volDrag);
  // Pulled out with a soft slide, heard as the bar opens (the level pouring in behind it, app.css): once per opening.
  let volWasOpen = false;
  $effect(() => {
    const open = volOpen;
    if (open && !volWasOpen && $motionEnabled) playSound("slide", { p: 0.62, level: 0.32 });
    volWasOpen = open;
  });
  function grabVolume() {
    volDrag = true;
    window.addEventListener("pointerup", () => (volDrag = false), { once: true });
    window.addEventListener("pointercancel", () => (volDrag = false), { once: true });
  }

  /** The speaker: off says goodbye with its own click first, on says hello with one. */
  function toggleSound() {
    if ($uiSound) {
      playSound("off");
      uiSound.set(false);
    } else {
      uiSound.set(true);
      playSound("on");
    }
  }

  onMount(() => {
    const early = setTimeout(() => {
      const idle = (window as any).requestIdleCallback ?? ((fn: () => void) => setTimeout(fn, 1));
      idle(() => BigPictureView || loadBigPicture(), { timeout: 4000 });
    }, 6000);
    return () => clearTimeout(early);
  });

  // Grouped by what you're actually doing, not by an arbitrary split.
  // Pages load on demand. Importing all nine statically put every page in one
  // chunk, so opening the Dashboard paid to download, parse and compile
  // Settings, System and Chats as well.
  const routes: Record<string, { title: string; icon: string; load: () => Promise<any>; section: string }> = {
    dashboard: { title: "Dashboard", icon: "dashboard", load: () => import("./pages/Dashboard.svelte"), section: "Run" },
    // Each profile is a bot of its own: which are running, on which accounts, and a way into each one's parts.
    profiles:  { title: "Profiles",  icon: "layers",    load: () => import("./pages/Profiles.svelte"),  section: "Run" },
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

  // Evenly staggered rather than random, so there is always one ring mid-flight
  // and they never bunch up. Negative delays start the cycle already running
  // instead of leaving the screen empty for the first pass.
  const rings = Array.from({ length: RIPPLE_RINGS }, (_, i) => ({
    life: 16,
    delay: -(i * 16) / RIPPLE_RINGS,
  }));

  let route = $state("dashboard");
  /** What the pages scroll in. It stays as the pages change, and kept the last page's place: another page opens at its top. */
  let scroller: HTMLElement | null = $state(null);

  $effect(() => {
    const key = route;
    // Before the page is put in, so one that scrolls itself to a spot (a setting it was sent to) still does.
    untrack(() => {
      if (scroller) scroller.scrollTop = 0;
    });
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

  /**
   * Fetch every other page in the background, once this one is up.
   *
   * Splitting the pages into their own chunks stopped the Dashboard paying to
   * download and compile Settings, System and Chats - but it moved that cost to
   * the first click on each tab instead, where it is far more noticeable,
   * because it is a wait you asked for and are watching.
   *
   * Doing both is better than either: the first paint still carries one page,
   * and by the time anyone clicks anything the rest are already in memory.
   * Idle time only, one at a time, so this never competes with the page that is
   * actually on screen.
   */
  function idle(fn: () => void) {
    if (typeof requestIdleCallback === "function") requestIdleCallback(() => fn(), { timeout: 3000 });
    else setTimeout(fn, 300);
  }

  function prefetchPages() {
    const pending = Object.keys(routes);
    const step = () => {
      const key = pending.shift();
      if (key === undefined) return;
      if (pageCache.has(key)) return step();
      routes[key]
        .load()
        .then((m) => pageCache.set(key, m.default))
        .catch(() => {})            // a chunk that will not load is not fatal
        .finally(() => idle(step));
    };
    idle(step);
  }
  let paletteOpen = $state(false);
  /** What the search opens already searching for: the right-click menu's "Search for" sends it. */
  let paletteSeed = $state("");
  $effect(() => {
    const r = $paletteRequest;
    if (!r) return;
    paletteSeed = r.q;
    paletteOpen = true;
  });
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

  /**
   * Coalesced to one read per frame. measure() reads offsetTop, which forces
   * the browser to lay the page out right then; called straight from the
   * observers it did so in the middle of a page being built, while the new
   * page was still being inserted - a profile put more of the UI thread in
   * this function than in anything else, because it paid for laying out every
   * freshly opened page, sometimes twice. In a frame callback the layout is
   * the one the frame needs anyway.
   */
  let measureQueued = false;
  function queueMeasure() {
    if (measureQueued) return;
    measureQueued = true;
    requestAnimationFrame(() => {
      measureQueued = false;
      measure();
    });
  }

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
    const observer = new MutationObserver(queueMeasure);
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
    const resize = new ResizeObserver(queueMeasure);
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
      queueMeasure();
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
    // Big Picture shows the health issues too, so this one keeps going under it.
    const stopHealthPoll = visiblePoll(pollHealth, 15000, { underBigPicture: true });

    // Asking an account who is waiting is an IPC round trip to the bot, slow
    // enough that fetching it when the Chats tab opens meant a skeleton every
    // time. Keeping every account warm from app start makes the tab instant.
    const stopChatPrefetch = startChatPrefetch();
    // And live from then on: the runners push every change as it happens.
    const stopChatLive = startChatLive();

    // A describe pass survives a page reload, so pick it up rather than
    // leaving the bar hidden until someone opens Pictures.
    checkDescribeOnce();

    // The other eight tabs: their code, then their data. Both were paid for on
    // the first click, which is exactly when you are watching.
    prefetchPages();
    const stopWarm = warmPages();

    // Whether a backdrop and a typeface have been uploaded. Needed at startup,
    // not just when the Appearance tab is opened, because both apply app-wide.
    loadAppearance();

    // What this device is, and what does not work on it: the pages warn
    // where those things would be used (lib/components/NotHere.svelte).
    loadDevice();

    // In the phone apps the panel is the app's own web view, and a link
    // followed inside it leaves the panel with no way back. Links to anywhere
    // else open in the phone's browser instead.
    const onLink = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || !inPhoneApp()) return;
      const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!a || !/^https?:/i.test(a.href) || new URL(a.href).origin === location.origin) return;
      e.preventDefault();
      openUrl(a.href);
    };
    document.addEventListener("click", onLink);

    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        paletteOpen = !paletteOpen;
      }
      // Big Picture Mode, like Steam's: Ctrl+Shift+B in and out.
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "b") {
        e.preventDefault();
        setBigPicture(!$bigPicture);
      }
    };
    window.addEventListener("hashchange", parseHash);
    window.addEventListener("keydown", onKey);

    return () => {
      stopHealthPoll();
      stopChatPrefetch();
      stopChatLive();
      stopWarm();
      window.removeEventListener("resize", onResize);
      window.removeEventListener("hashchange", parseHash);
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("click", onLink);
    };
  });

  $effect(() => {
    document.documentElement.dataset.motion = $motionEnabled ? "full" : "off";
  });

  $effect(() => {
    document.documentElement.dataset.surface = $surfaceId;
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
  // It opens the page the app is named after, by default. A right-click on it
  // turns that off, and on again: an easter egg with no way out is just a
  // misclick that keeps happening. (It used to ask, on the second click.)
  const LIS = "https://en.wikipedia.org/wiki/Life_Is_Strange";
  /** A little life when it is pressed: a bounce as it opens the page, a shake of the head when that is off. */
  let logoMove = $state<"" | "boing" | "nope">("");
  let logoMoveTimer = 0;
  function moveLogo(m: "boing" | "nope") {
    logoMove = "";
    clearTimeout(logoMoveTimer);
    requestAnimationFrame(() => {
      logoMove = m;
      logoMoveTimer = window.setTimeout(() => (logoMove = ""), 520);
    });
  }

  function tapLogo() {
    if ($logoLinkOff) {
      moveLogo("nope");
      return;
    }
    moveLogo("boing");
    openExternal("lifeisstrange", LIS);
  }

  function setLogoLink(on: boolean) {
    logoLinkOff.set(!on);
    playSound(on ? "on" : "off");
    toast(on ? "The logo opens the page again." : "The logo won't open the page now. Right-click it to turn it back on.", "info");
  }

  /** Its right-click menu: the page now, and whether a click opens it. */
  function logoMenu(): MenuEntry[] {
    return [
      { title: "Life Is Strange page" },
      { label: "Open it", icon: "external", run: () => openExternal("lifeisstrange", LIS) },
      $logoLinkOff
        ? { label: "Open it on click again", icon: "check", run: () => setLogoLink(true) }
        : { label: "Stop opening it on click", icon: "close", run: () => setLogoLink(false) },
    ];
  }

  // ── The page's name in the header ────────────────────────────────────────
  /** In Settings, where in it: its tab and section, the tab a click away. */
  const crumbs = $derived.by(() => {
    if (route !== "settings") return null;
    const [t, s] = ($settingsPath || "").split("/");
    const tab = TABS.find((x) => x.id === t);
    const sub = tab?.subs.find((x) => x.id === s) ?? tab?.subs[0];
    return tab && sub ? { tab, sub } : null;
  });
</script>

<!-- The speaker: every sound in the app, on or off. Beside Big Picture, top right. Under the pointer it opens out
     into a thin volume bar, a line across its middle where the sounds were made to sit (it ticks firmer crossing it). -->
{#snippet speaker()}
  <div class="vol" class:is-off={!$uiSound} class:is-open={volOpen} class:is-dragging={volDrag}
       role="group" aria-label="Sounds"
       onpointerenter={() => (volHover = true)} onpointerleave={() => (volHover = false)}
       onfocusin={(e) => (volKey = (e.target as Element).matches(":focus-visible"))}
       onfocusout={() => (volKey = false)}>
    <div class="vol-track">
      <div class="vol-bar">
        <input type="range" class="vol-slider" min="0" max="2" step="0.05" value={$uiVolume} data-default="1"
               aria-label="Volume" style="--fill: {Math.round(($uiVolume / 2) * 100)}%"
               onpointerdown={grabVolume}
               oninput={(e) => setVolume(parseFloat((e.target as HTMLInputElement).value))} />
        <span class="vol-mid" aria-hidden="true"></span>
      </div>
    </div>
    <button
      onclick={toggleSound}
      data-sound="self"
      class="tb-btn speaker flex h-7 w-7 items-center justify-center rounded-lg"
      class:is-off={!$uiSound}
      data-tip={$uiSound ? `Sounds on · ${Math.round($uiVolume * 100)}%` : "Sounds off"}
      aria-label={$uiSound ? "Mute sounds" : "Turn sounds on"}
      aria-pressed={$uiSound}
    >
      {#key $uiSound}
        <span class="speaker-icon tb-ico"><Icon name={$uiSound ? "speaker" : "speakerOff"} size={15} /></span>
      {/key}
    </button>
  </div>
{/snippet}

<!-- Big Picture: in the app beside the window's buttons, in a browser in the header. -->
{#snippet bigPictureButton()}
  <button
    onclick={() => setBigPicture(true)}
    class="tb-btn is-bp flex h-7 w-7 items-center justify-center rounded-lg"
    data-tip="Big Picture Mode (Ctrl+Shift+B)"
    aria-label="Big Picture Mode"
  >
    <span class="tb-ico"><Icon name="bigpicture" size={16} /></span>
  </button>
{/snippet}

<!-- ── Window chrome ─────────────────────────────────────────────────────────
     Frameless: no OS title bar, the app fills the window. The strips are the
     drag handles; the buttons sit in two groups, the app's own (sounds, Big
     Picture) apart from the window's, each with a word under it on hover. -->
{#if desktop}
  <div class="fixed right-2 top-1 z-50 flex items-center gap-1.5">
    <div class="tb-group">
      {@render speaker()}
      {@render bigPictureButton()}
    </div>
    <div class="tb-group">
      <button
        onclick={toggleSize}
        class="tb-btn is-size flex h-7 w-7 items-center justify-center rounded-lg"
        class:is-pocket={pocket}
        data-tip={pocket ? "Make it bigger" : "Pocket size"}
        aria-label={pocket ? "Expand window" : "Shrink window"}
      >
        <span class="tb-ico"><Icon name={pocket ? "expand" : "collapse"} size={14} /></span>
      </button>
      <button
        onclick={minimize}
        class="tb-btn is-min flex h-7 w-7 items-center justify-center rounded-lg"
        data-tip="Minimise"
        aria-label="Minimise"
      >
        <span class="tb-ico"><Icon name="minimize" size={15} /></span>
      </button>
      <button
        onclick={closeWindow}
        class="tb-btn is-close is-edge flex h-7 w-7 items-center justify-center rounded-lg"
        data-tip="Close"
        aria-label="Close"
      >
        <span class="tb-ico"><Icon name="close" size={15} /></span>
      </button>
    </div>
  </div>
{/if}

<!-- Under everything, and skipped entirely when an uploaded image is in use:
     two backgrounds fighting each other is not a look. -->
{#if $backdropId !== "none" && !($customBgOn && $appearance.background.present)}
  <div class="app-backdrop" class:is-covered={$bigPictureCovering} data-kind={$backdropId} aria-hidden="true">
    {#if $backdropId === "ripple"}
      {#each rings as r}
        <span class="ring" style="--life:{r.life}s; --delay:{r.delay}s"></span>
      {/each}
    {/if}
  </div>
{/if}

<!-- Under Big Picture it fades out, and once covered is not drawn at all: see bigPictureCovering. -->
<div class="app-shell flex h-screen overflow-hidden" class:is-under={$bigPictureArriving} class:is-covered={$bigPictureCovering}>
  <!-- ── Sidebar ─────────────────────────────────────────────────────── -->
  <aside
    class="chrome-surface z-20 flex shrink-0 flex-col border-r border-edge bg-surface/70
           {rail ? 'w-[52px]' : 'w-[212px]'}"
    style="transition: width 0.42s var(--spring)"
  >
    <!-- The strip is the window drag handle, and it was empty. The mark sits
         in it: the same height as the header beside it, so the two line up,
         and the name appears only when there is width for it. -->
    <!-- Centred in the rail, like every nav item below it. Keeping the
         expanded padding here put the mark 5px left of the icon column, which
         is exactly far enough to look like a mistake. -->
    <div class="brand pywebview-drag-region flex h-9 shrink-0 items-center gap-2
                {rail ? 'justify-center px-0' : 'px-2.5'}">
      <!-- The mark: opens the Life Is Strange page (the bot's face comes from it); a right-click turns that off. -->
      <button
        onclick={tapLogo}
        use:contextMenu={logoMenu}
        class="brand-mark no-drag shrink-0"
        class:is-off={$logoLinkOff}
        class:is-boing={logoMove === "boing"}
        class:is-nope={logoMove === "nope"}
        title={$logoLinkOff ? "LLMSelfbot. Right-click to make it open the page again" : "Life Is Strange. Right-click to turn this off"}
        aria-label={$logoLinkOff ? "LLMSelfbot" : "Open the Life Is Strange page"}
      >
        <img src={logo} alt="" class="brand-logo" draggable="false" />
      </button>
      {#if !rail}
        <span class="brand-name">LLMSelfbot</span>
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
          <!-- Work still running on a page you have left. The page you are on
               shows its own loading state, so this is for the others. -->
          {@const bg = route !== key && !!$busyRoutes[key]}
          {@const info = $busyRoutes[key]}
          {@const pct = progressText(info)}
          {@const justDone = route !== key && !bg && !!$doneRoutes[key]}
          <button
            onclick={() => navigate(key)}
            data-active={route === key}
            title={bg
              ? `${r.title}: ${(info?.labels ?? []).join(", ") || "loading"}${pct ? ` (${pct})` : ""} in the background`
              : rail ? r.title : ""}
            class="nav-item relative z-10 flex w-full items-center gap-2.5 rounded-[10px] py-[7px] text-left text-[13px]
              {rail ? 'justify-center px-0' : 'px-2.5'}
              {route === key ? 'font-medium text-ink' : 'text-muted hover:bg-white/[0.05] hover:text-ink'}"
          >
            <span class="nav-icon relative shrink-0 {route === key ? 'is-active text-accent' : ''}">
              <Icon name={r.icon} size={16} />
              {#if rail && bg}
                <!-- No room beside a label in the rail, so the ring goes around
                     the icon: filling if the progress is known, turning if not. -->
                <span class="nav-ring"><ProgressRing done={info?.done} total={info?.total} size={26} /></span>
              {:else if rail && justDone}
                <span class="nav-done-dot" aria-hidden="true"></span>
              {/if}
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
            {#if !rail && bg}
              <span class="nav-spin ml-auto" role="status"
                    aria-label="{r.title} is loading{pct ? `, ${pct}` : ''}">
                {#if pct}<span class="nav-pct">{pct}</span>{/if}
                <ProgressRing done={info?.done} total={info?.total} size={13} />
              </span>
            {:else if !rail && justDone}
              <span class="nav-done ml-auto" role="status" aria-label="{r.title} finished">
                <svg viewBox="0 0 16 16" width="13" height="13">
                  <path d="M4 8.5 l2.6 2.6 L12 5.4" fill="none" stroke="currentColor"
                        stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </span>
            {/if}
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
      class="app-header chrome-surface pywebview-drag-region flex h-9 shrink-0 items-center gap-2 border-b border-edge bg-surface/70 pl-3
        {desktop ? 'pr-[176px] has-chrome' : 'pr-4'}"
      class:vol-open={desktop && volOpen}
    >
      <!-- The page: its icon and name, in again with each page; in Settings, where in it. The words let a
           press through to the strip, which is what drags the window. -->
      {#key route}
        <div class="page-title pywebview-drag-region">
          <span class="page-title-icon"><Icon name={routes[route]?.icon ?? "dashboard"} size={13} /></span>
          <h1>{routes[route]?.title ?? ""}</h1>
        </div>
      {/key}
      {#if crumbs}
        <nav class="crumbs" aria-label="Where in Settings">
          <span class="crumb-sep" aria-hidden="true"><Icon name="chevron" size={11} /></span>
          <button type="button" class="crumb no-drag" onclick={() => settingsSection.set(crumbs.tab.id)}
                  title="Back to the start of {crumbs.tab.name}">{crumbs.tab.name}</button>
          <span class="crumb-sep" aria-hidden="true"><Icon name="chevron" size={11} /></span>
          {#key crumbs.sub.id}
            <span class="crumb is-here">{crumbs.sub.name}</span>
          {/key}
        </nav>
      {/if}
      <div class="pywebview-drag-region h-full flex-1"></div>
      <!-- In the header rather than floating over the page: it never collides
           with a toast, it never moves the content, and it is in the same place
           whichever tab you are on. -->
      <LoadingBadge {route} />
      {#if !desktop}
        <!-- In the app these sit with the window buttons, top right; a browser has none. -->
        <div class="tb-group">
          {@render speaker()}
          {@render bigPictureButton()}
        </div>
      {/if}
    </header>

    <div class="min-h-0 flex-1 overflow-y-auto" bind:this={scroller}>
      {#if routes[route]}
        {#key route}
          <!-- Opening a tab, its contents drop into place from the top down. -->
          <div class="page-enter pb-16 {pocket ? 'p-3' : 'p-6'}" use:cascade={route}>
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
  seed={paletteSeed}
  onclose={() => { paletteOpen = false; paletteSeed = ""; }}
  {routes}
  onpick={(id) => (id === "bigpicture" ? setBigPicture(true) : navigate(id))}
/>

<!-- The right-click menu, for every page: out here, past the page wrapper's
     transform, which would otherwise be what "fixed" is fixed to. -->
<GlobalMenu />
<AskHost />

<!-- Big Picture Mode: loaded the first time it is opened, so it costs nothing until then. -->
{#if $bigPicture && BigPictureView}
  <BigPictureView />
{/if}

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
