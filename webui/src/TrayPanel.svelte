<script lang="ts">
  /**
   * The quick panel that opens from the tray icon: the app at a glance, and
   * the few things worth doing without opening the whole window.
   *
   * The tray only had a plain menu (Open window, which opened a browser tab,
   * Pause / resume all, Restart, Quit). This is a small window of the app's
   * own (app/desktop.py opens it by the tray, as "?tray"), so it looks like
   * the app: each account with whether it is replying and a switch to pause
   * just that one, today's replies, the pages one click away, and pause all,
   * restart and quit. It closes itself as soon as you click anywhere else.
   */
  import { onMount } from "svelte";
  import { api } from "./lib/api";
  import { themeId, fontId, motionEnabled, loadPrefs } from "./lib/stores";
  import { applyTheme } from "./lib/themes";
  import { applyFont } from "./lib/fonts";
  import Toggle from "./lib/components/Toggle.svelte";
  import Icon from "./lib/components/Icon.svelte";
  import Avatar from "./lib/components/Avatar.svelte";
  import Odometer from "./lib/components/Odometer.svelte";

  type Account = {
    id: string; platform: string; account: number | null; state: string; uptime?: number;
    username?: string; display_name?: string; avatar?: string; enabled?: boolean; gave_up?: boolean;
  };
  let accounts = $state<Account[]>([]);
  let paused = $state<Record<string, boolean>>({});
  let waiting = $state<Record<string, number>>({});
  let today = $state(0);
  let loaded = $state(false);
  let opened = $state(0);

  const bridge = () => (window as any).pywebview?.api;

  async function refresh() {
    try {
      const r = await api.accounts();
      accounts = (r.accounts ?? []).filter((a: Account) => a.platform !== "telegram");
      loaded = true;
      for (const a of accounts) {
        if (a.state !== "running") continue;
        api.chats(a.id).then((c: any) => {
          paused = { ...paused, [a.id]: !!c?.paused };
          waiting = { ...waiting, [a.id]: (c?.users ?? []).length };
        }).catch(() => {});
      }
    } catch { /* the app is starting or stopping */ }
    api.statsOverview().then((s: any) => (today = Number(s?.windows?.today) || 0)).catch(() => {});
  }

  onMount(() => {
    document.documentElement.classList.add("is-tray");
    loadPrefs();
    refresh();
    const t = setInterval(() => { if (document.hasFocus()) refresh(); }, 3000);
    // The tray shows the panel again rather than making a new one: it says so here.
    (window as any).__trayShown = () => {
      opened++;
      refresh();
    };
    // Clicking anywhere else closes it, as a menu would.
    const onBlur = () => setTimeout(() => { if (!document.hasFocus()) bridge()?.hide_panel?.(); }, 120);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") bridge()?.hide_panel?.(); };
    window.addEventListener("blur", onBlur);
    window.addEventListener("keydown", onKey);
    return () => {
      clearInterval(t);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("keydown", onKey);
    };
  });
  $effect(() => { applyTheme($themeId); });
  $effect(() => { applyFont($fontId); });
  $effect(() => { document.documentElement.dataset.motion = $motionEnabled ? "full" : "off"; });

  const running = $derived(accounts.filter((a) => a.state === "running"));
  const troubled = $derived(accounts.filter((a) => a.state === "crashing" || a.gave_up));
  const allPaused = $derived(running.length > 0 && running.every((a) => paused[a.id]));
  const summary = $derived.by(() => {
    if (!loaded) return { word: "Starting", tone: "warn" };
    if (troubled.length) return { word: troubled.length === 1 ? "1 needs a look" : `${troubled.length} need a look`, tone: "bad" };
    if (!running.length) return { word: "Nothing running", tone: "idle" };
    if (allPaused) return { word: "All paused", tone: "warn" };
    const nPaused = running.filter((a) => paused[a.id]).length;
    if (nPaused) return { word: `${nPaused} paused`, tone: "warn" };
    return { word: running.length === accounts.length ? "All running" : `${running.length} of ${accounts.length} running`, tone: "good" };
  });
  const waitingTotal = $derived(Object.values(waiting).reduce((n, x) => n + x, 0));

  const nameOf = (a: Account) => a.display_name || a.username || `${a.platform === "snapchat" ? "Snapchat" : "Discord"} #${a.account ?? 1}`;
  function stateOf(a: Account): { word: string; tone: string } {
    if (a.gave_up) return { word: "Stopped after crashing", tone: "bad" };
    if (a.state === "crashing") return { word: "Restarting", tone: "bad" };
    if (a.state === "starting") return { word: "Starting", tone: "warn" };
    if (a.state !== "running") return { word: a.enabled === false ? "Turned off" : "Stopped", tone: "idle" };
    if (paused[a.id]) return { word: "Paused", tone: "warn" };
    return { word: waiting[a.id] ? `Replying · ${waiting[a.id]} waiting` : "Replying", tone: "good" };
  }
  function upFor(s?: number): string {
    if (!s) return "";
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h >= 24 ? `${Math.floor(h / 24)} d` : h ? `${h} h ${m} min` : `${m} min`;
  }

  let busy = $state<Record<string, boolean>>({});
  async function togglePause(a: Account) {
    busy = { ...busy, [a.id]: true };
    paused = { ...paused, [a.id]: !paused[a.id] };
    try {
      const r = await api.accountAction(a.id, "pause");
      if (r && typeof r.paused === "boolean") paused = { ...paused, [a.id]: r.paused };
    } catch {
      paused = { ...paused, [a.id]: !paused[a.id] };
    }
    busy = { ...busy, [a.id]: false };
  }
  async function startOrRestart(a: Account) {
    busy = { ...busy, [a.id]: true };
    try { await api.accountAction(a.id, a.state === "running" ? "restart" : "start"); } catch { /* shown on refresh */ }
    busy = { ...busy, [a.id]: false };
    setTimeout(refresh, 800);
  }
  async function pauseAll() {
    const want = !allPaused;
    for (const a of running) if (!!paused[a.id] !== want) togglePause(a);
  }
  async function restartAll() {
    for (const a of accounts) if (a.state === "running" || a.gave_up) api.accountAction(a.id, "restart").catch(() => {});
    setTimeout(refresh, 1000);
  }
  const go = (route: string) => bridge()?.open_main?.(route);
  const quit = () => bridge()?.quit_app?.();

  const PAGES = [
    { route: "dashboard", icon: "dashboard", label: "Open" },
    { route: "chats", icon: "chats", label: "Chats" },
    { route: "logs", icon: "logs", label: "Logs" },
    { route: "settings", icon: "settings", label: "Settings" },
  ];
</script>

{#key opened}
  <div class="tp">
    <header class="tp-head">
      <span class="tp-logo"><img src="/favicon.png" alt="" /></span>
      <div class="min-w-0 flex-1">
        <div class="tp-title">LLMSelfbot</div>
        <div class="tp-sub"><b><Odometer value={today} /></b> {today === 1 ? "reply" : "replies"} today{#if waitingTotal} · {waitingTotal} waiting{/if}</div>
      </div>
      <span class="tp-pill is-{summary.tone}"><i></i>{summary.word}</span>
    </header>

    <ul class="tp-list">
      {#each accounts as a, i (a.id)}
        {@const s = stateOf(a)}
        <li class="tp-acct is-{s.tone}" style="--i: {i}">
          <span class="tp-av">
            <Avatar src={a.avatar ?? ""} name={nameOf(a)} size={34} zoom={false} />
            <i class="tp-dot is-{s.tone}"></i>
          </span>
          <span class="min-w-0 flex-1">
            <span class="tp-name">{nameOf(a)}<em>{a.platform === "snapchat" ? "Snapchat" : "Discord"} #{a.account ?? 1}</em></span>
            <span class="tp-state">{s.word}{#if a.state === "running" && a.uptime} · up {upFor(a.uptime)}{/if}</span>
          </span>
          {#if a.state === "running"}
            <button type="button" class="tp-mini" title="Restart it" aria-label="Restart {nameOf(a)}" disabled={busy[a.id]} onclick={() => startOrRestart(a)}>
              <Icon name="refresh" size={13} />
            </button>
            <Toggle checked={!paused[a.id]} name="Replying, {nameOf(a)}" size="sm" disabled={busy[a.id]} onchange={() => togglePause(a)} />
          {:else}
            <button type="button" class="tp-start" disabled={busy[a.id] || a.enabled === false} onclick={() => startOrRestart(a)}>
              <Icon name="play" size={11} />Start
            </button>
          {/if}
        </li>
      {:else}
        <li class="tp-empty">{loaded ? "No accounts yet. Add one in the app." : "Starting up…"}</li>
      {/each}
    </ul>

    <nav class="tp-pages">
      {#each PAGES as p, i (p.route)}
        <button type="button" class="tp-page" style="--i: {i}" onclick={() => go(p.route)}>
          <span><Icon name={p.icon} size={17} /></span>{p.label}
        </button>
      {/each}
    </nav>

    <footer class="tp-foot">
      <button type="button" class="tp-act" onclick={pauseAll} disabled={!running.length}>
        <Icon name={allPaused ? "play" : "pause"} size={13} />{allPaused ? "Resume all" : "Pause all"}
      </button>
      <button type="button" class="tp-act" onclick={restartAll} disabled={!accounts.length}><Icon name="refresh" size={13} />Restart all</button>
      <button type="button" class="tp-act is-quit" onclick={quit}><Icon name="signout" size={13} />Quit</button>
    </footer>
  </div>
{/key}

<style>
  :global(html.is-tray), :global(html.is-tray body) { height: 100%; overflow: hidden; background: var(--color-bg); }
  .tp {
    display: flex;
    height: 100vh;
    flex-direction: column;
    gap: 10px;
    padding: 14px;
    background:
      radial-gradient(120% 70% at 0% 0%, color-mix(in srgb, var(--color-accent) 16%, transparent), transparent 60%),
      radial-gradient(90% 60% at 100% 100%, color-mix(in srgb, var(--color-accent-2) 10%, transparent), transparent 60%),
      var(--color-bg);
    color: var(--color-ink);
    user-select: none;
    animation: tp-in 0.32s var(--spring) both;
  }
  @keyframes tp-in { from { opacity: 0; transform: translateY(10px) scale(0.98); } }
  .tp-head { display: flex; align-items: center; gap: 10px; }
  .tp-logo { display: grid; width: 36px; height: 36px; flex-shrink: 0; place-items: center; border-radius: 11px; background: color-mix(in srgb, var(--color-accent) 18%, transparent); }
  .tp-logo img { width: 22px; height: 22px; }
  .tp-title { font-size: 14px; font-weight: 700; letter-spacing: -0.01em; }
  .tp-sub { font-size: 11.5px; color: var(--color-muted); }
  .tp-sub b { color: var(--color-ink); font-weight: 700; }
  .tp-pill { display: inline-flex; flex-shrink: 0; align-items: center; gap: 6px; padding: 4px 9px; border-radius: 999px; font-size: 11px; font-weight: 650; background: rgb(255 255 255 / 0.05); }
  .tp-pill i { width: 7px; height: 7px; border-radius: 999px; background: currentColor; }
  .is-good { color: var(--color-good); }
  .is-warn { color: var(--color-warn); }
  .is-bad { color: var(--color-bad); }
  .is-idle { color: var(--color-faint); }
  .tp-pill.is-good i { animation: tp-breathe 2.4s ease-in-out infinite; }
  @keyframes tp-breathe { 50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-good) 25%, transparent); } }

  .tp-list { display: flex; min-height: 0; flex: 1; flex-direction: column; gap: 4px; overflow-y: auto; margin: 0 -4px; padding: 0 4px; }
  .tp-acct {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px 8px 8px;
    border-radius: 14px;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.035);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.05);
    transition: background-color 0.15s var(--swift);
    animation: tp-row 0.4s var(--spring) both;
    animation-delay: calc(60ms + var(--i) * 45ms);
  }
  @keyframes tp-row { from { opacity: 0; transform: translateY(8px); } }
  .tp-acct:hover { background: rgb(255 255 255 / 0.06); }
  .tp-av { position: relative; display: inline-flex; flex-shrink: 0; }
  .tp-dot { position: absolute; right: -2px; bottom: -2px; width: 11px; height: 11px; border-radius: 999px; border: 2.5px solid var(--color-bg); background: currentColor; }
  .tp-name { display: flex; min-width: 0; align-items: baseline; gap: 6px; overflow: hidden; font-size: 13px; font-weight: 650; white-space: nowrap; text-overflow: ellipsis; }
  .tp-name em { font-style: normal; font-size: 10.5px; font-weight: 500; color: var(--color-faint); }
  .tp-state { display: block; overflow: hidden; font-size: 11px; color: var(--color-muted); white-space: nowrap; text-overflow: ellipsis; }
  .tp-acct.is-bad .tp-state { color: var(--color-bad); }
  .tp-mini { display: grid; width: 26px; height: 26px; place-items: center; border-radius: 8px; color: var(--color-faint); opacity: 0; transition: opacity 0.15s var(--swift), background-color 0.15s var(--swift), color 0.15s var(--swift); }
  .tp-acct:hover .tp-mini { opacity: 1; }
  .tp-mini:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
  .tp-start { display: inline-flex; align-items: center; gap: 5px; padding: 5px 10px; border-radius: 9px; font-size: 11.5px; font-weight: 650; color: var(--color-bg); background: var(--color-accent); }
  .tp-start:disabled { opacity: 0.45; }
  .tp-empty { padding: 20px 8px; font-size: 12px; text-align: center; color: var(--color-faint); }

  .tp-pages { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
  .tp-page {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 5px;
    padding: 9px 4px 8px;
    border-radius: 13px;
    font-size: 11px;
    font-weight: 600;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.035);
    transition: background-color 0.15s var(--swift), color 0.15s var(--swift), transform 0.3s var(--jelly);
    animation: tp-row 0.4s var(--spring) both;
    animation-delay: calc(140ms + var(--i) * 35ms);
  }
  .tp-page span { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 10px; color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 12%, transparent); transition: transform 0.35s var(--spring); }
  .tp-page:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.07); }
  .tp-page:hover span { transform: translateY(-2px) scale(1.06); }
  .tp-page:active { transform: scale(0.95); }

  .tp-foot { display: flex; gap: 6px; padding-top: 10px; border-top: 1px solid rgb(255 255 255 / 0.06); }
  .tp-act { display: inline-flex; flex: 1; align-items: center; justify-content: center; gap: 6px; padding: 8px 6px; border-radius: 11px; font-size: 12px; font-weight: 600; color: var(--color-muted); background: rgb(255 255 255 / 0.04); transition: background-color 0.15s var(--swift), color 0.15s var(--swift), transform 0.3s var(--jelly); }
  .tp-act:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
  .tp-act:active:not(:disabled) { transform: scale(0.95); }
  .tp-act:disabled { opacity: 0.45; }
  .tp-act.is-quit:hover { color: #fff; background: var(--color-bad); }

  :global(:root[data-motion="off"]) .tp,
  :global(:root[data-motion="off"]) .tp-acct,
  :global(:root[data-motion="off"]) .tp-page,
  :global(:root[data-motion="off"]) .tp-pill i { animation: none; }
</style>
