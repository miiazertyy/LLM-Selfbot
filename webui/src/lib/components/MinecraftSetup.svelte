<script lang="ts">
  /**
   * Getting Minecraft able to run: mindcraft-ce, which plays the game, installed on demand.
   *
   * The same shape as the browser platforms' Install page (SnapchatSetup.svelte), and the same feel: one sentence
   * says where things stand, four things it needs are ticked off in turn, each lighting with a rising note and a
   * bell at the end, and each running account says what it is doing. Its own page rather than that one widened,
   * because none of its parts are the same: there is no browser, there is a Node version to check, a pinned version
   * of mindcraft to be on, and 1.4 GB of it, so the room on the disk matters.
   */
  import { onMount, untrack } from "svelte";
  import { get } from "svelte/store";
  import { api } from "../api";
  import { ask } from "../ask";
  import { trackUntil } from "../busy";
  import { subscribeLogs } from "../logsocket";
  import { visiblePoll } from "../poll";
  import { motionEnabled, toast } from "../stores";
  import Button from "./Button.svelte";
  import GrassBlock from "./GrassBlock.svelte";
  import Icon from "./Icon.svelte";
  import FootNote from "./FootNote.svelte";
  import { play } from "../uisound";
  import { afterLanding, onScreen, whenShown } from "../cascade";

  type Runner = { account: number | null; state: string; detail: string; at: number; stale: boolean };
  type McStatus = {
    node: string;
    node_version: string;
    node_ok: boolean;
    npm: string;
    installed: boolean;
    commit: string;
    pinned: string;
    up_to_date: boolean;
    dir: string;
    free_gb: number;
    installing: boolean;
    runners?: Runner[];
  };

  const TONE: Record<string, "good" | "warn" | "bad" | "muted"> = {
    ready: "good", starting: "muted", "logging-in": "muted", "needs-you": "warn", "logged-out": "bad",
  };
  const SAYS: Record<string, string> = {
    ready: "In the world, playing",
    starting: "Starting up",
    "logging-in": "Joining the server",
    "needs-you": "Waiting for you",
    "logged-out": "Not connected",
  };
  /** A Microsoft sign-in and anything else it waits on are both "needs-you"; the detail says which. */
  const says = (r: Runner) =>
    r.state === "needs-you" && /microsoft|code/i.test(r.detail || "") ? "Waiting for you to sign in" : SAYS[r.state] ?? r.state;

  let status = $state<McStatus | null>(null);
  // ViaProxy, for servers of any version (app/platforms/minecraft/viaproxy.py).
  type ViaStatus = { java: string; java_major: number; java_ok: boolean; installed: boolean; version: string;
                     installing: boolean };
  let via = $state<ViaStatus | null>(null);
  let logs = $state<{ time: string; text: string; level?: string }[]>([]);
  const live = $derived(status?.runners ?? []);
  const short = (sha: string) => (sha ? sha.slice(0, 7) : "");

  type Step = { name: string; what: string; done: boolean; working: boolean; shows: string };
  const steps = $derived.by((): Step[] => {
    const s = status;
    if (!s) return [];
    return [
      { name: "Node.js", what: "Runs mindcraft. Version 22 or newer.", done: s.node_ok, working: false,
        shows: s.node_ok ? s.node_version : s.node ? `${s.node_version || "Unknown"}, too old` : "Not found" },
      { name: "npm", what: "Installs its packages.", done: !!s.npm, working: false, shows: s.npm ? "Found" : "Not found" },
      { name: "mindcraft-ce", what: "The bot that plays: walking, mining, building.", done: s.installed,
        working: s.installing && !s.installed, shows: s.installed ? "Installed" : s.installing ? "Installing" : "Missing" },
      { name: "This version", what: "The one this app was built and tested with.", done: s.up_to_date,
        working: s.installing && s.installed && !s.up_to_date,
        shows: s.up_to_date ? short(s.pinned) : s.installed ? `${short(s.commit) || "Unknown"}, not ${short(s.pinned)}` : short(s.pinned) },
    ];
  });
  const doneCount = $derived(steps.filter((s) => s.done).length);
  const ready = $derived(!!status?.up_to_date && !status?.installing);
  const lowDisk = $derived(!!status && status.free_gb > 0 && status.free_gb < 5 && !status.installed);

  const headline = $derived.by(() => {
    const s = status;
    if (!s) return { title: "", sub: "", tone: "muted" };
    if (s.installing) return { title: "Installing Minecraft support", sub: "About 5 to 15 minutes. It carries on if you leave this page.", tone: "working" };
    if (ready) return { title: "Minecraft is ready to play", sub: "Add an account on the Accounts page, then point it at a world.", tone: "good" };
    if (!s.node) return { title: "Node.js is missing", sub: "Install version 22 or newer from nodejs.org, then come back.", tone: "bad" };
    if (!s.node_ok) return { title: "Node.js is too old", sub: `mindcraft needs 22 or newer; this computer has ${s.node_version || "an unknown one"}.`, tone: "bad" };
    if (s.installed) return { title: "Another version is installed", sub: "Reinstalling puts the right one in place. What its bots remember stays.", tone: "warn" };
    if (lowDisk) return { title: "Not enough room", sub: `It needs about 5 GB; there is ${s.free_gb} GB free.`, tone: "bad" };
    return { title: "Minecraft needs installing", sub: "About 1.4 GB, into a folder of its own.", tone: "warn" };
  });

  onMount(() => {
    load();
    const stopPoll = visiblePoll(load, 3000);
    const offLogs = subscribeLogs((entry) => {
      if (entry.source === "minecraft-install") logs = [...logs.slice(-199), entry as any];
    });
    return () => {
      stopPoll();
      offLogs();
    };
  });

  async function load() {
    try {
      status = await api.minecraftStatus();
    } catch {
      /* the page still works without it */
    }
    try {
      via = await api.viaProxyStatus();
    } catch {
      /* nor without this */
    }
  }

  async function installVia() {
    play("tap");
    try {
      const r = await api.viaProxyInstall();
      if (r?.ok === false) {
        toast(r.reason || "Could not start it", "err");
        return;
      }
      toast("Installing ViaProxy. The log below shows how it is going.", "info");
      trackUntil("settings", "Installing ViaProxy", async () => !(await api.viaProxyStatus())?.installing, 3000);
      load();
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  async function removeVia() {
    const yes = await ask("Remove ViaProxy?", {
      yes: "Remove", danger: true,
      detail: "Servers that are not on 1.21 are then joined directly, which works when the bot knows their version.",
    });
    if (!yes) return;
    try {
      await api.viaProxyUninstall();
      load();
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  async function install() {
    try {
      const r = await api.minecraftInstall();
      if (r?.ok === false) {
        toast(r.reason || "Could not start the install", "err");
        return;
      }
      toast("Install started. The log below shows how it is going.", "info");
      trackUntil("settings", "Installing Minecraft support", async () => !(await api.minecraftStatus())?.installing, 4000);
      load();
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  async function uninstall() {
    const yes = await ask("Remove mindcraft-ce?", {
      yes: "Remove", danger: true,
      detail: "Frees about 1.4 GB. Minecraft accounts stop until it is installed again. What its bots remember is kept.",
    });
    if (!yes) return;
    try {
      await api.minecraftUninstall();
      trackUntil("settings", "Removing mindcraft-ce", async () => !(await api.minecraftStatus())?.installing, 2000);
      load();
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  // ── Filling up, seen and heard as one (the same timeline as SnapchatSetup) ──
  let hero: HTMLElement | null = $state(null);
  let stepList: HTMLElement | null = $state(null);
  let lit = $state<Record<string, boolean>>({});
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
      afterLanding(el, () => afterLanding(list, async () => {
        heard = await onScreen(el);
        landed = true;
        light();
      }));
    });
  });
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
    timers.push(window.setTimeout(() => finish(), (fresh.length - 1) * GAP_MS + 420));
  }
  function finish(quiet = false) {
    if (complete || steps.length !== 4 || !steps.every((s) => lit[s.name])) return;
    complete = true;
    if (heard && !quiet) play("done");
  }
  const litCount = $derived(steps.filter((s) => lit[s.name]).length);

  const ago = (at: number) => {
    const s = Math.max(0, Date.now() / 1000 - at);
    return s < 90 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
  };
</script>

{#if !status}
  <div class="mc-skeleton"></div>
{:else}
  <div class="mc">
    <section class="mc-hero is-{headline.tone}" class:is-complete={complete && doneCount === 4} bind:this={hero}>
      <!-- The grass block, as the game draws it. -->
      <div class="mc-block" aria-hidden="true">
        <span class="mc-block-ring"></span>
        <GrassBlock size={36} />
      </div>
      <div class="min-w-0 flex-1">
        <h3 class="mc-title">{headline.title}</h3>
        <p class="mc-sub">{headline.sub}</p>
        <div class="mc-meter" aria-label="{doneCount} of 4 in place">
          <span class="mc-bar">
            {#each steps as s (s.name)}
              <span class="mc-seg" class:is-lit={s.done && lit[s.name]} class:is-working={s.working}></span>
            {/each}
            <i class="mc-shine" aria-hidden="true"></i>
          </span>
          {#key litCount}<b class="mc-count">{litCount}/4</b>{/key}
        </div>
      </div>
      <div class="mc-action">
        {#if status.installing}
          <Button loading disabled>Installing</Button>
        {:else if !ready}
          <Button onclick={install} disabled={!status.npm || !status.node_ok || lowDisk}>
            {status.installed ? "Reinstall" : "Install Minecraft support"}
          </Button>
        {:else}
          <span class="mc-ready"><Icon name="check" size={13} />Ready</span>
        {/if}
      </div>
    </section>

    {#if live.length}
      <div class="mc-runners">
        {#each live as r (r.account ?? 0)}
          {@const tone = r.stale ? "muted" : (TONE[r.state] ?? "muted")}
          <div class="mc-runner is-{tone}">
            <span class="mc-dot"></span>
            <div class="min-w-0 flex-1">
              <div class="mc-runner-head">
                <b>{r.account ? `Account #${r.account}` : "Minecraft"}</b>
                {#if r.stale}<span class="mc-chip">Not running</span><span class="mc-faint">last said</span>{/if}
                <span class="mc-state">{says(r)}</span>
                {#if r.at}<span class="mc-faint">· {ago(r.at)}</span>{/if}
              </div>
              {#if r.detail}<p class="mc-detail">{r.detail}</p>{/if}
            </div>
          </div>
        {/each}
      </div>
    {/if}

    <ol class="mc-steps" bind:this={stepList}>
      {#each steps as s, i (s.name)}
        <li class="mc-step" class:is-done={s.done} class:is-working={s.working} class:is-lit={s.done && lit[s.name]}
            class:is-linked={s.done && lit[s.name] && !!steps[i + 1]?.done && lit[steps[i + 1].name]}>
          <span class="mc-mark" aria-hidden="true">
            {#if s.working}<span class="mc-spin"></span>{:else if s.done}<Icon name="check" size={12} />{:else}<Icon name="close" size={11} />{/if}
          </span>
          <div class="min-w-0 flex-1">
            <div class="mc-step-name">{s.name}</div>
            <p class="mc-step-what">{s.what}</p>
          </div>
          <span class="mc-step-shows" title={s.shows}>{s.shows}</span>
        </li>
      {/each}
    </ol>

    {#if via}
      <!-- Servers of any version: ViaProxy between the bot and the server, speaking the server's own. -->
      <section class="mc-via" class:is-on={via.installed}>
        <span class="mc-via-mark" aria-hidden="true"><Icon name="globe" size={16} /></span>
        <div class="min-w-0 flex-1">
          <div class="mc-via-name">Servers of any version <span class="mc-faint">ViaProxy</span></div>
          <p class="mc-via-what">
            {via.installed
              ? `Installed, ${via.version}. A server not on 1.21 is joined through it, when it signs in without Microsoft.`
              : !via.java_ok
                ? "It runs on Java, which this computer does not have. Install Java 21 from adoptium.net."
                : "Lets it join a server of any version, older or newer. About 50 MB."}
          </p>
        </div>
        {#if via.installing}
          <Button size="sm" loading disabled>Installing</Button>
        {:else if via.installed}
          <button type="button" class="mc-remove" onclick={removeVia}>Remove</button>
        {:else}
          <Button size="sm" onclick={installVia} disabled={!via.java_ok}>Install</Button>
        {/if}
      </section>
    {/if}

    <FootNote icon="folder">
      Installs into <code>{status.dir}</code>, outside the app, so it survives updates. {status.free_gb} GB free.
      {#if status.installed && !status.installing}
        <button type="button" class="mc-remove" onclick={uninstall}>Remove it</button>
      {/if}
    </FootNote>

    {#if logs.length}
      <div class="mc-log">
        <div class="mc-log-head"><span></span><span></span><span></span>Install log</div>
        <div class="mc-log-body">
          {#each logs as l}
            <div class:is-error={l.level === "error"} class:is-warn={l.level === "warn"}><span class="mc-faint">{l.time}</span> {l.text}</div>
          {/each}
        </div>
      </div>
    {/if}

    <div class="mc-tips">
      <a class="mc-tip" href="#/accounts">
        <Icon name="accounts" size={15} />
        <span><b>Add it on the Accounts page.</b> A name, and the world it joins.</span>
        <Icon name="chevron" size={12} class="mc-tip-go" />
      </a>
      <div class="mc-tip">
        <Icon name="minecraft" size={15} />
        <span><b>Start on a world of your own.</b> Open one to LAN, or run a server with online mode off. No account needed for either.</span>
      </div>
    </div>
  </div>
{/if}

<style>
  .mc { display: flex; flex-direction: column; gap: 14px; }
  .mc-via {
    display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 14px;
    border: 1px solid var(--color-edge);
    background: linear-gradient(180deg, rgb(255 255 255 / 0.03), rgb(0 0 0 / 0.08));
    transition: border-color 0.3s ease;
  }
  .mc-via.is-on { border-color: color-mix(in srgb, #6aa83a 30%, var(--color-edge)); }
  .mc-via-mark {
    display: grid; place-items: center; width: 32px; height: 32px; flex-shrink: 0; border-radius: 10px;
    color: #7cbd4a; background: rgb(124 189 74 / 0.1); box-shadow: inset 0 0 0 1px rgb(124 189 74 / 0.22);
  }
  .mc-via-name { font-size: 13px; font-weight: 600; color: var(--color-ink); }
  .mc-via-name .mc-faint { margin-left: 6px; font-size: 11px; font-weight: 500; }
  .mc-via-what { margin-top: 2px; font-size: 11.5px; line-height: 1.45; color: var(--color-muted); }
  .mc-skeleton { height: 180px; border-radius: 16px; background: rgb(255 255 255 / 0.03); animation: mc-pulse 1.6s ease-in-out infinite; }
  @keyframes mc-pulse { 50% { opacity: 0.5; } }

  .mc-hero {
    --tone: #5b8731;
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
      radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, var(--tone) 13%, transparent), transparent 55%),
      linear-gradient(180deg, rgb(255 255 255 / 0.035), rgb(0 0 0 / 0.12));
  }
  .mc-hero.is-good { --tone: #6aa83a; }
  .mc-hero.is-warn { --tone: var(--color-warn); }
  .mc-hero.is-bad { --tone: var(--color-bad); }
  .mc-hero.is-working { --tone: var(--color-accent); }
  .mc-block {
    position: relative;
    display: grid;
    width: 54px;
    height: 54px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 17px;
    background: linear-gradient(145deg, #23301c, #141b10);
    box-shadow: 0 10px 26px -10px rgb(106 168 58 / 0.55), inset 0 0 0 1px rgb(255 255 255 / 0.1);
  }
  .mc-hero:not(.is-good) .mc-block { filter: saturate(0.5) brightness(0.85); }
  .mc-block :global(svg) { overflow: visible; filter: drop-shadow(0 2px 2px rgb(0 0 0 / 0.35)); }
  .mc-block-ring { position: absolute; inset: -5px; border-radius: 21px; border: 1.5px solid rgb(124 189 74 / 0.5); opacity: 0; }
  .mc-hero.is-good.is-complete .mc-block-ring { animation: mc-ring 2.8s ease-out infinite; }
  @keyframes mc-ring { 0% { opacity: 0.7; transform: scale(0.92); } 100% { opacity: 0; transform: scale(1.25); } }
  .mc-hero.is-complete .mc-block { animation: mc-hop 0.62s var(--jelly); }
  @keyframes mc-hop {
    0% { transform: none; }
    30% { transform: translateY(-5px) scale(1.06) rotate(-4deg); }
    60% { transform: translateY(1px) scale(0.98, 1.02); }
    100% { transform: none; }
  }
  .mc-title { font-size: 16px; font-weight: 700; letter-spacing: -0.01em; color: var(--color-ink); }
  .mc-sub { margin-top: 2px; font-size: 12px; color: var(--color-muted); }

  .mc-meter { display: flex; align-items: center; gap: 10px; margin-top: 11px; }
  .mc-bar { position: relative; display: flex; gap: 4px; padding: 2px 0; }
  .mc-seg { position: relative; width: 36px; height: 6px; overflow: hidden; border-radius: 999px; background: rgb(255 255 255 / 0.08); transition: box-shadow 0.5s ease; }
  .mc-seg::before {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: inherit;
    background: linear-gradient(90deg, #7cbd4a, var(--color-good));
    transform: scaleX(0);
    transform-origin: left center;
    transition: transform 0.46s cubic-bezier(0.22, 1.2, 0.36, 1);
  }
  .mc-seg.is-lit::before { transform: scaleX(1); }
  .mc-seg.is-lit { box-shadow: 0 0 10px -2px color-mix(in srgb, var(--color-good) 70%, transparent); }
  .mc-seg.is-working { background: linear-gradient(90deg, rgb(255 255 255 / 0.08), var(--color-accent), rgb(255 255 255 / 0.08)); background-size: 200% 100%; animation: mc-shimmer 1.2s linear infinite; }
  @keyframes mc-shimmer { to { background-position: -200% 0; } }
  .mc-shine {
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
  .mc-hero.is-complete .mc-shine { animation: mc-shine 0.9s cubic-bezier(0.35, 0.2, 0.25, 1); }
  @keyframes mc-shine { 0% { opacity: 0; transform: translateX(-30px); } 18% { opacity: 1; } 80% { opacity: 1; } 100% { opacity: 0; transform: translateX(165px); } }
  .mc-count { font-size: 11px; font-weight: 700; color: var(--color-faint); font-variant-numeric: tabular-nums; animation: mc-count 0.36s var(--jelly); transition: color 0.3s ease; }
  @keyframes mc-count { from { transform: translateY(4px) scale(0.8); opacity: 0.4; } }
  .mc-hero.is-complete .mc-count { color: var(--color-good); }
  .mc-action { flex-shrink: 0; }
  .mc-ready {
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
  .mc-hero.is-complete .mc-ready { opacity: 1; transform: none; animation: mc-ready 0.6s var(--jelly); }
  @keyframes mc-ready { 0% { transform: scale(0.8); } 45% { transform: scale(1.1); } 100% { transform: none; } }

  .mc-runners { display: flex; flex-direction: column; gap: 6px; }
  .mc-runner {
    --tone: var(--color-muted);
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 12px;
    border-radius: 12px;
    border: 1px solid color-mix(in srgb, var(--tone) 25%, var(--color-edge));
    background: color-mix(in srgb, var(--tone) 6%, transparent);
  }
  .mc-runner.is-good { --tone: var(--color-good); }
  .mc-runner.is-warn { --tone: var(--color-warn); }
  .mc-runner.is-bad { --tone: var(--color-bad); }
  .mc-dot { width: 8px; height: 8px; margin-top: 5px; flex-shrink: 0; border-radius: 999px; background: var(--tone); box-shadow: 0 0 10px var(--tone); }
  .mc-runner.is-good .mc-dot { animation: mc-beat 2s ease-in-out infinite; }
  @keyframes mc-beat { 50% { opacity: 0.45; } }
  .mc-runner-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; font-size: 12.5px; color: var(--color-ink); }
  .mc-runner-head b { font-weight: 650; }
  .mc-state { font-weight: 600; color: var(--tone); }
  .mc-chip { padding: 0 6px; border-radius: 999px; font-size: 10.5px; color: var(--color-muted); background: rgb(255 255 255 / 0.06); }
  .mc-faint { font-size: 11px; color: var(--color-faint); }
  .mc-detail { margin-top: 2px; font-size: 12px; line-height: 1.5; color: var(--color-muted); }

  .mc-steps { display: flex; flex-direction: column; padding: 4px 2px; }
  .mc-step { position: relative; display: flex; align-items: center; gap: 12px; padding: 9px 0; }
  .mc-step:not(:last-child)::after { content: ""; position: absolute; left: 12px; top: 36px; bottom: -10px; width: 2px; border-radius: 2px; background: rgb(255 255 255 / 0.08); }
  .mc-step:not(:last-child)::before {
    content: "";
    position: absolute;
    z-index: 1;
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
  .mc-step.is-linked::before { transform: scaleY(1); }
  .mc-mark {
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
  .mc-step.is-done .mc-mark {
    color: color-mix(in srgb, var(--color-good) 70%, var(--color-muted));
    background: color-mix(in srgb, var(--color-good) 8%, var(--color-surface));
    box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--color-good) 25%, transparent);
    transform: scale(0.88);
    transition: transform 0.3s ease, background-color 0.3s ease, color 0.3s ease;
  }
  .mc-step.is-lit .mc-mark { color: #06240f; background: var(--color-good); box-shadow: 0 0 14px -2px color-mix(in srgb, var(--color-good) 70%, transparent); transform: none; animation: mc-tick 0.5s var(--jelly); }
  @keyframes mc-tick { 0% { transform: scale(0.5); } 55% { transform: scale(1.18); } 100% { transform: none; } }
  .mc-step.is-working .mc-mark { color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 12%, var(--color-surface)); box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--color-accent) 45%, transparent); }
  .mc-spin { width: 12px; height: 12px; border-radius: 999px; border: 2px solid currentColor; border-right-color: transparent; animation: mc-spin 0.8s linear infinite; }
  @keyframes mc-spin { to { transform: rotate(360deg); } }
  .mc-step-name { font-size: 13px; font-weight: 600; color: var(--color-ink); }
  .mc-step-what { margin-top: 1px; font-size: 11.5px; color: var(--color-faint); }
  .mc-step-shows {
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
  .mc-step.is-done .mc-step-shows { color: var(--color-good); }
  .mc-step.is-working .mc-step-shows { color: var(--color-accent); }

  .mc-remove { margin-left: 6px; color: var(--color-faint); text-decoration: underline; text-underline-offset: 2px; }
  .mc-remove:hover { color: var(--color-bad); }

  .mc-log { overflow: hidden; border-radius: 12px; border: 1px solid var(--color-edge); background: rgb(0 0 0 / 0.45); }
  .mc-log-head { display: flex; align-items: center; gap: 5px; padding: 7px 10px; font-size: 10.5px; color: var(--color-faint); background: rgb(255 255 255 / 0.03); }
  .mc-log-head span { width: 8px; height: 8px; border-radius: 999px; background: rgb(255 255 255 / 0.12); }
  .mc-log-head span:nth-child(1) { background: #ff5f57aa; }
  .mc-log-head span:nth-child(2) { background: #febc2eaa; }
  .mc-log-head span:nth-child(3) { background: #28c840aa; margin-right: 6px; }
  .mc-log-body { height: 200px; overflow-y: auto; padding: 10px 12px; font-family: ui-monospace, monospace; font-size: 11px; line-height: 1.6; word-break: break-all; color: color-mix(in srgb, var(--color-ink) 85%, transparent); }
  .mc-log-body .is-error { color: var(--color-bad); }
  .mc-log-body .is-warn { color: var(--color-warn); }

  .mc-tips { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 8px; }
  .mc-tip {
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
  a.mc-tip:hover { border-color: color-mix(in srgb, var(--color-accent) 40%, var(--color-edge)); background: rgb(255 255 255 / 0.04); transform: translateY(-1px); }
  .mc-tip b { display: block; margin-bottom: 1px; font-size: 12px; font-weight: 650; color: var(--color-ink); }
  .mc-tip > :global(svg:first-child) { margin-top: 1px; flex-shrink: 0; color: var(--color-accent); }
  .mc-tip :global(.mc-tip-go) { margin-top: 3px; margin-left: auto; flex-shrink: 0; color: var(--color-faint); }

  :global(:root[data-motion="off"]) .mc-block-ring,
  :global(:root[data-motion="off"]) .mc-block,
  :global(:root[data-motion="off"]) .mc-seg,
  :global(:root[data-motion="off"]) .mc-shine,
  :global(:root[data-motion="off"]) .mc-count,
  :global(:root[data-motion="off"]) .mc-ready,
  :global(:root[data-motion="off"]) .mc-dot,
  :global(:root[data-motion="off"]) .mc-mark,
  :global(:root[data-motion="off"]) .mc-skeleton { animation: none; }
  :global(:root[data-motion="off"]) .mc-seg::before,
  :global(:root[data-motion="off"]) .mc-step::before,
  :global(:root[data-motion="off"]) .mc-ready,
  :global(:root[data-motion="off"]) .mc-mark { transition: none; }
</style>
