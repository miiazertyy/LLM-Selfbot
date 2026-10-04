<script lang="ts">
  /**
   * Getting Snapchat able to run.
   *
   * This used to be a whole tab of its own, which was odd for something you
   * touch once: it is setup, so it lives in Settings with the rest of the
   * setup.
   *
   * Snapchat has no API, so it drives a real browser through Puppeteer. Four
   * things have to be in place (Node.js, npm, the packages, a browser) and they
   * fail independently, so they are shown as four steps, each ticked off on
   * its own, with a line joining the ones that are done. Above them, one
   * sentence says where things stand, and what each running account is doing
   * right now: an account stuck on a verification screen and one answering
   * messages both used to read as simply "running".
   */
  import { onMount, untrack } from "svelte";
  import { get } from "svelte/store";
  import { api } from "../api";
  import { trackUntil } from "../busy";
  import { subscribeLogs } from "../logsocket";
  import { visiblePoll } from "../poll";
  import { motionEnabled, settingsSection, toast } from "../stores";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import FootNote from "./FootNote.svelte";
  import { SNAPCHAT_GHOST } from "../brands";
  import { play } from "../uisound";
  import { afterLanding, onScreen, whenShown } from "../cascade";

  type SnapStatus = {
    node: string | null;
    npm: string | null;
    modules_installed?: boolean;
    browser?: string;
    /** "Chrome" / "Edge" when the browser is one the machine already had. */
    browser_name?: string;
    deps_installed: boolean;
    installing: boolean;
    dir: string;
    runners?: Runner[];
  };
  /** What a running account is actually doing, straight from the runner. */
  type Runner = {
    account: number | null;
    state: string;
    detail: string;
    at: number;
    stale: boolean;
  };

  const TONE: Record<string, "good" | "warn" | "bad" | "muted"> = {
    ready: "good",
    starting: "muted",
    "awaiting-verification": "warn",
    "needs-login": "warn",
    "logged-out": "bad",
  };
  const SAYS: Record<string, string> = {
    ready: "Answering messages",
    starting: "Starting up",
    "awaiting-verification": "Waiting for you to verify",
    "needs-login": "Waiting for you to log in",
    "logged-out": "Logged out",
  };

  let status = $state<SnapStatus | null>(null);
  let logs = $state<{ time: string; text: string }[]>([]);

  // Every runner that has said anything. A stopped one is shown too, as what
  // it last said: "logged out" matters most right after the runner gives up,
  // which is exactly when it stops writing. Hiding stale entries hid that.
  const live = $derived(status?.runners ?? []);

  type Step = { name: string; what: string; done: boolean; working: boolean; shows: string };
  const steps = $derived.by((): Step[] => {
    const s = status;
    if (!s) return [];
    return [
      { name: "Node.js", what: "Runs the browser automation.", done: !!s.node, working: false, shows: s.node ? tail(s.node) : "Not found" },
      { name: "npm", what: "Installs the packages below.", done: !!s.npm, working: false, shows: s.npm ? tail(s.npm) : "Not found" },
      {
        name: "Node packages", what: "Puppeteer and its stealth plugins.", done: !!s.modules_installed,
        working: s.installing && !s.modules_installed,
        shows: s.modules_installed ? "Installed" : s.installing ? "Installing" : "Missing",
      },
      {
        name: "Browser", what: "Uses the Chrome or Edge you have, or downloads one.",
        done: !!s.browser, working: s.installing && !s.browser,
        shows: s.browser ? browserLabel(s) : s.installing ? "Downloading" : "Missing",
      },
    ];
  });
  const doneCount = $derived(steps.filter((s) => s.done).length);
  const ready = $derived(!!status?.deps_installed && !status?.installing);

  /** The headline: where things stand, in one sentence. */
  const headline = $derived.by(() => {
    const s = status;
    if (!s) return { title: "", sub: "", tone: "muted" };
    if (s.installing) return { title: "Installing Snapchat support", sub: "Downloading the packages. It carries on if you leave this page.", tone: "working" };
    if (ready) return { title: "Snapchat is ready to run", sub: "Everything it needs is installed.", tone: "good" };
    if (!s.node) return { title: "Node.js is missing", sub: "Install it from nodejs.org, then come back here.", tone: "bad" };
    if (s.modules_installed && !s.browser) return { title: "The browser did not finish downloading", sub: "Repairing clears the partial download and fetches it again.", tone: "warn" };
    return { title: "Snapchat needs installing", sub: "One click, into a folder of its own. It uses your browser if you have one.", tone: "warn" };
  });

  /** The end of a long path, which is the part that says anything. */
  const tail = (p: string) => (p.length > 30 ? `…${p.slice(-29)}` : p);

  /** What to show next to the browser step: yours, or the downloaded one's version. */
  function browserLabel(s: SnapStatus): string {
    if (s.browser_name) return `Your ${s.browser_name}`;
    const m = (s.browser ?? "").match(/(?:win64|mac[-\w]*|linux)[-_]([\d.]+)/i) ?? (s.browser ?? "").match(/(\d+\.\d+\.\d+\.\d+)/);
    return m ? `Chrome ${m[1]}` : "Installed";
  }

  onMount(() => {
    load();
    // /api/snapchat/status shells out to node to locate Chrome, so polling it
    // behind a hidden window kept the backend busy for a view nobody had open.
    const stopPoll = visiblePoll(load, 3000);
    const offLogs = subscribeLogs((entry) => {
      if (entry.source === "snapchat-install") logs = [...logs.slice(-99), entry as any];
    });
    return () => {
      stopPoll();
      offLogs();
    };
  });

  async function load() {
    try {
      status = await api.snapStatus();
    } catch {
      /* the panel still works without it */
    }
  }

  async function install() {
    try {
      await api.snapInstall();
      toast("Install started. Watch the log below.", "info");
      // Downloads a browser: minutes, and nobody watches the log the whole time.
      trackUntil("settings", "Installing Snapchat support",
                 async () => !(await api.snapStatus())?.installing, 4000);
      load();
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  // ── Filling up, seen and heard as one ─────────────────────────────────────
  // Once the card and the steps under it have landed, each part that is in
  // place lights up in turn: its segment of the bar fills, its step's tick
  // pops, and a note rises, a step higher each time. When all four are in, the
  // finish: a shine runs along the bar, 4/4 and the Ready badge spring up, the
  // ghost bounces and its ring goes out, with a soft bell. One timeline drives
  // what is seen and what is heard, so every sound has its motion: the bar's
  // own animations used to be held while the card dropped in (a segment sat as
  // a small square), and the bell came after it had all stopped moving.
  // An install getting a part in later lights that one the same way.
  let hero: HTMLElement | null = $state(null);
  let stepList: HTMLElement | null = $state(null);
  /** The parts shown in place, by name. */
  let lit = $state<Record<string, boolean>>({});
  /** All four in, and the finish played (or shown at once). */
  let complete = $state(false);
  let landed = false;
  let heard = false;
  const timers: number[] = [];
  const GAP_MS = 150;

  $effect(() => {
    const el = hero;
    const list = stepList;
    if (!el || !list || landed) return;
    whenShown(el).then(() => {
      // Both blocks down (the steps are a block of their own, lower on the page), then it begins.
      afterLanding(el, () => afterLanding(list, async () => {
        heard = await onScreen(el);
        landed = true;
        light();
      }));
    });
  });
  // An install getting a part in while the page is open lights it the same way.
  $effect(() => {
    void steps;
    if (landed) untrack(light);
  });
  $effect(() => () => timers.forEach(clearTimeout));

  function light() {
    const fresh = steps.filter((s) => s.done && !lit[s.name]);
    if (!fresh.length) return finish();
    if (!get(motionEnabled)) {
      lit = { ...lit, ...Object.fromEntries(fresh.map((s) => [s.name, true])) };
      return finish(true);
    }
    fresh.forEach((s, k) => {
      timers.push(window.setTimeout(() => {
        lit = { ...lit, [s.name]: true };
        if (heard) play("rise", { p: steps.indexOf(s) / 3 });
      }, k * GAP_MS));
    });
    // The finish comes as the last segment settles.
    timers.push(window.setTimeout(() => finish(), (fresh.length - 1) * GAP_MS + 420));
  }

  function finish(quiet = false) {
    if (complete || steps.length !== 4 || !steps.every((s) => lit[s.name])) return;
    complete = true;
    if (heard && !quiet) play("done");
  }

  /** How many are shown in place, for the count beside the bar: it counts up as they light. */
  const litCount = $derived(steps.filter((s) => lit[s.name]).length);

  const ago = (at: number) => {
    const s = Math.max(0, Date.now() / 1000 - at);
    return s < 90 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
  };
</script>

{#if !status}
  <div class="sn-skeleton"></div>
{:else}
  <div class="sn">
    <!-- Where things stand, in one sentence, and each account's own state. -->
    <section class="sn-hero is-{headline.tone}" class:is-complete={complete && doneCount === 4} bind:this={hero}>
      <!-- Snapchat's logo as Snapchat draws it: a white ghost outlined in black, on its yellow. -->
      <div class="sn-ghost" aria-hidden="true">
        <span class="sn-ghost-ring"></span>
        <svg class="sn-logo" viewBox="-1 -1 26 26" width="34" height="34">
          <path d={SNAPCHAT_GHOST} />
        </svg>
      </div>
      <div class="min-w-0 flex-1">
        <h3 class="sn-title">{headline.title}</h3>
        <p class="sn-sub">{headline.sub}</p>
        <div class="sn-meter" aria-label="{doneCount} of 4 in place">
          <span class="sn-bar">
            {#each steps as s (s.name)}
              <span class="sn-seg" class:is-lit={s.done && lit[s.name]} class:is-working={s.working}></span>
            {/each}
            <i class="sn-shine" aria-hidden="true"></i>
          </span>
          {#key litCount}<b class="sn-count">{litCount}/4</b>{/key}
        </div>
      </div>
      <div class="sn-action">
        {#if status.installing}
          <Button loading disabled>Installing</Button>
        {:else if !status.deps_installed}
          <Button onclick={install} disabled={!status.npm}>
            {status.modules_installed ? "Repair install" : "Install Snapchat support"}
          </Button>
        {:else}
          <span class="sn-ready"><Icon name="check" size={13} />Ready</span>
        {/if}
      </div>
    </section>

    {#if live.length}
      <div class="sn-runners">
        {#each live as r (r.account ?? 0)}
          {@const tone = r.stale ? "muted" : (TONE[r.state] ?? "muted")}
          <div class="sn-runner is-{tone}">
            <span class="sn-dot"></span>
            <div class="min-w-0 flex-1">
              <div class="sn-runner-head">
                <b>{r.account ? `Account #${r.account}` : "Snapchat"}</b>
                {#if r.stale}
                  <span class="sn-chip">Not running</span><span class="sn-faint">last said</span>
                {/if}
                <span class="sn-state">{SAYS[r.state] ?? r.state}</span>
                {#if r.at}<span class="sn-faint">· {ago(r.at)}</span>{/if}
              </div>
              {#if r.detail}<p class="sn-detail">{r.detail}</p>{/if}
            </div>
          </div>
        {/each}
      </div>
    {/if}

    <!-- The four things it needs, ticked off in order, joined where they are done. -->
    <ol class="sn-steps" bind:this={stepList}>
      {#each steps as s, i (s.name)}
        <li class="sn-step" class:is-done={s.done} class:is-working={s.working} class:is-lit={s.done && lit[s.name]}
            class:is-linked={s.done && lit[s.name] && !!steps[i + 1]?.done && lit[steps[i + 1].name]}>
          <span class="sn-mark" aria-hidden="true">
            {#if s.working}<span class="sn-spin"></span>{:else if s.done}<Icon name="check" size={12} />{:else}<Icon name="close" size={11} />{/if}
          </span>
          <div class="min-w-0 flex-1">
            <div class="sn-step-name">{s.name}</div>
            <p class="sn-step-what">{s.what}</p>
          </div>
          <span class="sn-step-shows" title={s.shows}>{s.shows}</span>
        </li>
      {/each}
    </ol>

    <FootNote icon="folder">
      Installs into <code>{status.dir}</code>, outside the app, so it survives updates.
    </FootNote>

    {#if logs.length}
      <div class="sn-log">
        <div class="sn-log-head"><span></span><span></span><span></span>Install log</div>
        <div class="sn-log-body">
          {#each logs as l}
            <div><span class="sn-faint">{l.time}</span> {l.text}</div>
          {/each}
        </div>
      </div>
    {/if}

    <div class="sn-tips">
      <button type="button" class="sn-tip" onclick={() => settingsSection.set("snapchat/browser")}>
        <Icon name="monitor" size={15} />
        <span><b>The first login needs the browser window.</b> Keep "Hide the browser window" off for it; once
          the cookies are saved, later runs can hide it.</span>
        <Icon name="chevron" size={12} class="sn-tip-go" />
      </button>
      <a class="sn-tip" href="#/accounts">
        <Icon name="accounts" size={15} />
        <span><b>Logins are on the Accounts page.</b> Each Snapchat account has its own username and password there.</span>
        <Icon name="chevron" size={12} class="sn-tip-go" />
      </a>
    </div>
  </div>
{/if}

<style>
  .sn { display: flex; flex-direction: column; gap: 14px; }
  .sn-skeleton { height: 180px; border-radius: 16px; background: rgb(255 255 255 / 0.03); animation: sn-pulse 1.6s ease-in-out infinite; }
  @keyframes sn-pulse { 50% { opacity: 0.5; } }

  /* ── The headline ──────────────────────────────────────────────────────── */
  .sn-hero {
    --tone: #fffc00;
    position: relative;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 16px;
    overflow: hidden;
    padding: 18px;
    border-radius: 16px;
    border: 1px solid color-mix(in srgb, var(--tone) 22%, var(--color-edge));
    background:
      radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, var(--tone) 12%, transparent), transparent 55%),
      linear-gradient(180deg, rgb(255 255 255 / 0.035), rgb(0 0 0 / 0.12));
  }
  .sn-hero.is-good { --tone: #fffc00; }
  .sn-hero.is-warn { --tone: var(--color-warn); }
  .sn-hero.is-bad { --tone: var(--color-bad); }
  .sn-hero.is-working { --tone: var(--color-accent); }
  .sn-ghost {
    position: relative;
    display: grid;
    width: 54px;
    height: 54px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 17px;
    color: #111;
    background: linear-gradient(145deg, #fffc00, #ffd400);
    box-shadow: 0 10px 26px -10px rgb(255 230 0 / 0.55), inset 0 1px 0 rgb(255 255 255 / 0.6);
  }
  .sn-hero:not(.is-good) .sn-ghost { filter: saturate(0.45) brightness(0.8); }
  .sn-logo { overflow: visible; filter: drop-shadow(0 1px 1px rgb(0 0 0 / 0.15)); }
  .sn-logo path { fill: #fff; stroke: #000; stroke-width: 1.35; stroke-linejoin: round; }
  /* Ready: a slow ring breathes out from it, starting with the finish. */
  .sn-ghost-ring {
    position: absolute;
    inset: -5px;
    border-radius: 21px;
    border: 1.5px solid rgb(255 245 80 / 0.5);
    opacity: 0;
  }
  .sn-hero.is-good.is-complete .sn-ghost-ring { animation: sn-ring 2.8s ease-out infinite; }
  @keyframes sn-ring { 0% { opacity: 0.7; transform: scale(0.92); } 100% { opacity: 0; transform: scale(1.25); } }
  /* The finish: the ghost hops, with the bell. */
  .sn-hero.is-complete .sn-ghost { animation: sn-hop 0.62s var(--jelly); }
  @keyframes sn-hop {
    0% { transform: none; }
    30% { transform: translateY(-5px) scale(1.06) rotate(-4deg); }
    60% { transform: translateY(1px) scale(0.98, 1.02); }
    100% { transform: none; }
  }
  .sn-title { font-size: 16px; font-weight: 700; letter-spacing: -0.01em; color: var(--color-ink); }
  .sn-sub { margin-top: 2px; font-size: 12px; color: var(--color-muted); }

  /* The bar: four segments, each filling from the left as its part lights, a
     shine along all four at the finish, and the count beside it counting up. */
  .sn-meter { display: flex; align-items: center; gap: 10px; margin-top: 11px; }
  /* Nothing clipped: the shine fades in and out on its own, and cut off by the bar it had flat edges. */
  .sn-bar { position: relative; display: flex; gap: 4px; padding: 2px 0; }
  .sn-seg {
    position: relative;
    width: 36px;
    height: 6px;
    overflow: hidden;
    border-radius: 999px;
    background: rgb(255 255 255 / 0.08);
    transition: box-shadow 0.5s ease;
  }
  .sn-seg::before {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: inherit;
    background: linear-gradient(90deg, color-mix(in srgb, var(--color-good) 75%, #fffc00), var(--color-good));
    transform: scaleX(0);
    transform-origin: left center;
    transition: transform 0.46s cubic-bezier(0.22, 1.2, 0.36, 1);
  }
  .sn-seg.is-lit::before { transform: scaleX(1); }
  .sn-seg.is-lit { box-shadow: 0 0 10px -2px color-mix(in srgb, var(--color-good) 70%, transparent); }
  .sn-seg.is-working { background: linear-gradient(90deg, rgb(255 255 255 / 0.08), var(--color-accent), rgb(255 255 255 / 0.08)); background-size: 200% 100%; animation: sn-shimmer 1.2s linear infinite; }
  @keyframes sn-shimmer { to { background-position: -200% 0; } }
  /* A soft light passing along the bar: round and blurred at every edge. It was a band wider than a
     segment, so it filled each one in turn and the segment's own hard ends were its edges. */
  .sn-shine {
    position: absolute;
    top: -5px;
    left: 0;
    width: 26px;
    height: 20px;
    opacity: 0;
    pointer-events: none;
    border-radius: 50%;
    background: radial-gradient(closest-side, rgb(255 255 255 / 0.8), rgb(255 255 255 / 0.28) 55%, transparent);
    filter: blur(3px);
    mix-blend-mode: screen;
  }
  .sn-hero.is-complete .sn-shine { animation: sn-shine 0.9s cubic-bezier(0.35, 0.2, 0.25, 1); }
  @keyframes sn-shine {
    0% { opacity: 0; transform: translateX(-30px); }
    18% { opacity: 1; }
    80% { opacity: 1; }
    100% { opacity: 0; transform: translateX(165px); }
  }
  .sn-count {
    font-size: 11px;
    font-weight: 700;
    color: var(--color-faint);
    font-variant-numeric: tabular-nums;
    animation: sn-count 0.36s var(--jelly);
    transition: color 0.3s ease;
  }
  @keyframes sn-count { from { transform: translateY(4px) scale(0.8); opacity: 0.4; } }
  .sn-hero.is-complete .sn-count { color: var(--color-good); }
  .sn-action { flex-shrink: 0; }
  /* Ready: waiting, a little faded, while the parts light; it springs in with the finish. */
  .sn-ready {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border-radius: 999px;
    font-size: 12.5px;
    font-weight: 650;
    color: var(--color-good);
    background: color-mix(in srgb, var(--color-good) 12%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-good) 30%, transparent);
    opacity: 0.35;
    transform: scale(0.92);
    transition: opacity 0.25s ease, transform 0.25s ease;
  }
  .sn-hero.is-complete .sn-ready { opacity: 1; transform: none; animation: sn-ready 0.6s var(--jelly); }
  @keyframes sn-ready {
    0% { transform: scale(0.8); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-good) 30%, transparent), 0 0 0 0 color-mix(in srgb, var(--color-good) 55%, transparent); }
    45% { transform: scale(1.1); }
    100% { transform: none; box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-good) 30%, transparent), 0 0 0 12px color-mix(in srgb, var(--color-good) 0%, transparent); }
  }

  /* ── Each account, as it last said ─────────────────────────────────────── */
  .sn-runners { display: flex; flex-direction: column; gap: 6px; }
  .sn-runner {
    --tone: var(--color-muted);
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 12px;
    border-radius: 12px;
    border: 1px solid color-mix(in srgb, var(--tone) 25%, var(--color-edge));
    background: color-mix(in srgb, var(--tone) 6%, transparent);
  }
  .sn-runner.is-good { --tone: var(--color-good); }
  .sn-runner.is-warn { --tone: var(--color-warn); }
  .sn-runner.is-bad { --tone: var(--color-bad); }
  .sn-dot { width: 8px; height: 8px; margin-top: 5px; flex-shrink: 0; border-radius: 999px; background: var(--tone); box-shadow: 0 0 10px var(--tone); }
  .sn-runner.is-good .sn-dot { animation: sn-beat 2s ease-in-out infinite; }
  @keyframes sn-beat { 50% { opacity: 0.45; } }
  .sn-runner-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; font-size: 12.5px; color: var(--color-ink); }
  .sn-runner-head b { font-weight: 650; }
  .sn-state { font-weight: 600; color: var(--tone); }
  .sn-chip { padding: 0 6px; border-radius: 999px; font-size: 10.5px; color: var(--color-muted); background: rgb(255 255 255 / 0.06); }
  .sn-faint { font-size: 11px; color: var(--color-faint); }
  .sn-detail { margin-top: 2px; font-size: 12px; line-height: 1.5; color: var(--color-muted); }

  /* ── The four steps ────────────────────────────────────────────────────── */
  .sn-steps { display: flex; flex-direction: column; padding: 4px 2px; }
  .sn-step { position: relative; display: flex; align-items: center; gap: 12px; padding: 9px 0; }
  /* The line down to the next step, lit when both ends are done. */
  .sn-step:not(:last-child)::after {
    content: "";
    position: absolute;
    left: 12px;
    top: 36px;
    bottom: -10px;
    width: 2px;
    border-radius: 2px;
    background: rgb(255 255 255 / 0.08);
  }
  /* The line fills down to the next step as both light, from the top. */
  .sn-step:not(:last-child)::before {
    content: "";
    position: absolute;
    z-index: 1;                /* over the grey track (::after), under the tick, which comes after it */
    left: 12px;
    top: 36px;
    bottom: -10px;
    width: 2px;
    border-radius: 2px;
    background: linear-gradient(180deg, var(--color-good), color-mix(in srgb, var(--color-good) 55%, transparent));
    transform: scaleY(0);
    transform-origin: top center;
    transition: transform 0.4s cubic-bezier(0.3, 0.8, 0.3, 1);
  }
  .sn-step.is-linked::before { transform: scaleY(1); }
  .sn-mark {
    position: relative;
    z-index: 1;
    display: grid;
    width: 26px;
    height: 26px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    color: var(--color-bad);
    background: color-mix(in srgb, var(--color-bad) 12%, var(--color-surface));
    box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--color-bad) 45%, transparent);
  }
  /* In place, not lit yet: a quiet tick, waiting its turn. Lit: it pops green, with its segment of the bar. */
  .sn-step.is-done .sn-mark {
    color: color-mix(in srgb, var(--color-good) 70%, var(--color-muted));
    background: color-mix(in srgb, var(--color-good) 8%, var(--color-surface));
    box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--color-good) 25%, transparent);
    transform: scale(0.88);
    transition: transform 0.3s ease, background-color 0.3s ease, color 0.3s ease;
  }
  .sn-step.is-lit .sn-mark {
    color: #06240f;
    background: var(--color-good);
    box-shadow: 0 0 14px -2px color-mix(in srgb, var(--color-good) 70%, transparent);
    transform: none;
    animation: sn-tick 0.5s var(--jelly);
  }
  @keyframes sn-tick { 0% { transform: scale(0.5); } 55% { transform: scale(1.18); } 100% { transform: none; } }
  .sn-step.is-working .sn-mark { color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 12%, var(--color-surface)); box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--color-accent) 45%, transparent); }
  .sn-spin { width: 12px; height: 12px; border-radius: 999px; border: 2px solid currentColor; border-right-color: transparent; animation: sn-spin 0.8s linear infinite; }
  @keyframes sn-spin { to { transform: rotate(360deg); } }
  .sn-step-name { font-size: 13px; font-weight: 600; color: var(--color-ink); }
  .sn-step-what { margin-top: 1px; font-size: 11.5px; color: var(--color-faint); }
  .sn-step-shows {
    max-width: 42%;
    overflow: hidden;
    padding: 3px 8px;
    border-radius: 8px;
    font-family: ui-monospace, monospace;
    font-size: 10.5px;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--color-bad);
    background: rgb(0 0 0 / 0.22);
  }
  .sn-step.is-done .sn-step-shows { color: var(--color-good); }
  .sn-step.is-working .sn-step-shows { color: var(--color-accent); }


  /* ── The install log, as a little terminal ─────────────────────────────── */
  .sn-log { overflow: hidden; border-radius: 12px; border: 1px solid var(--color-edge); background: rgb(0 0 0 / 0.45); }
  .sn-log-head { display: flex; align-items: center; gap: 5px; padding: 7px 10px; font-size: 10.5px; color: var(--color-faint); background: rgb(255 255 255 / 0.03); }
  .sn-log-head span { width: 8px; height: 8px; border-radius: 999px; background: rgb(255 255 255 / 0.12); }
  .sn-log-head span:nth-child(1) { background: #ff5f57aa; }
  .sn-log-head span:nth-child(2) { background: #febc2eaa; }
  .sn-log-head span:nth-child(3) { background: #28c840aa; margin-right: 6px; }
  .sn-log-body { height: 200px; overflow-y: auto; padding: 10px 12px; font-family: ui-monospace, monospace; font-size: 11px; line-height: 1.6; word-break: break-all; color: color-mix(in srgb, var(--color-ink) 85%, transparent); }

  /* ── Tips ──────────────────────────────────────────────────────────────── */
  .sn-tips { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 8px; }
  .sn-tip {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 11px 12px;
    border-radius: 12px;
    border: 1px solid var(--color-edge);
    background: rgb(255 255 255 / 0.02);
    text-align: left;
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--color-muted);
    transition: border-color 0.18s var(--swift), background-color 0.18s var(--swift), transform 0.3s var(--spring);
  }
  .sn-tip:hover { border-color: color-mix(in srgb, var(--color-accent) 40%, var(--color-edge)); background: rgb(255 255 255 / 0.04); transform: translateY(-1px); }
  .sn-tip b { display: block; margin-bottom: 1px; font-size: 12px; font-weight: 650; color: var(--color-ink); }
  .sn-tip > :global(svg:first-child) { margin-top: 1px; flex-shrink: 0; color: var(--color-accent); }
  .sn-tip :global(.sn-tip-go) { margin-top: 3px; margin-left: auto; flex-shrink: 0; color: var(--color-faint); }

  :global(:root[data-motion="off"]) .sn-ghost-ring,
  :global(:root[data-motion="off"]) .sn-ghost,
  :global(:root[data-motion="off"]) .sn-seg,
  :global(:root[data-motion="off"]) .sn-shine,
  :global(:root[data-motion="off"]) .sn-count,
  :global(:root[data-motion="off"]) .sn-ready,
  :global(:root[data-motion="off"]) .sn-dot,
  :global(:root[data-motion="off"]) .sn-mark,
  :global(:root[data-motion="off"]) .sn-skeleton { animation: none; }
  :global(:root[data-motion="off"]) .sn-seg::before,
  :global(:root[data-motion="off"]) .sn-step::before,
  :global(:root[data-motion="off"]) .sn-ready,
  :global(:root[data-motion="off"]) .sn-mark { transition: none; }
</style>
