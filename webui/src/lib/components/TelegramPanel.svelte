<script lang="ts">
  /**
   * The Telegram page: the control bot, connected step by step, and what it
   * can do once it is.
   *
   * It used to be two .env values in boxes, with the template's placeholder
   * text in them ("your_telegram_user_id_here") and nothing to say whether
   * they worked. Now:
   *
   *  - the top says where things stand: which bot the token is for, whether
   *    the controller is running, with a test message and a restart to hand;
   *  - three steps connect it. The token is checked with Telegram before it
   *    is kept, and names its bot. Your ID, which Telegram shows nowhere, is
   *    read off a message you send the bot: you pick yourself from who wrote.
   *    A test message proves the two fit;
   *  - every command it answers is listed, grouped, searchable, and copied
   *    with a click.
   *
   * The server side is app/web/routes/telegram_routes.py. The alerts it sends
   * are ordinary settings rows, under this panel.
   */
  import { autowidth } from "../autowidth";
  import { onMount, tick, type Snippet } from "svelte";
  import { api } from "../api";
  import { toast, settingsSection } from "../stores";
  import { copyText } from "../contextmenu";
  import Icon from "./Icon.svelte";

  /** The alerts' settings rows, drawn between the steps and the commands. */
  let { alerts }: { alerts?: Snippet } = $props();

  type Bot = { id: number; username: string; name: string };
  type Info = {
    token_set: boolean; token_hint: string; owner_id: string; enabled: boolean;
    bot: Bot | null; state: string; uptime: number;
  };
  type Person = { id: string; name: string; username: string; said: string; at: number };
  type Group = { group: string; commands: { name: string; does: string }[] };

  let info = $state<Info | null>(null);
  let loadErr = $state("");
  let botErr = $state("");
  let groups = $state<Group[]>([]);

  async function load() {
    try {
      info = await api.telegram();
      loadErr = "";
      if (info?.token_set && !info.bot) void who();
    } catch (e: any) {
      loadErr = e?.message || "Could not read the Telegram settings.";
    }
  }
  /** Whose bot the saved token is. */
  async function who() {
    try {
      const r = await api.telegramCheck();
      if (r.ok && info) info = { ...info, bot: r.bot };
      botErr = r.ok ? "" : r.reason;
    } catch (e: any) {
      botErr = e?.message || "";
    }
  }
  onMount(() => {
    load();
    api.telegramCommands().then((r) => (groups = r.groups ?? [])).catch(() => {});
    // The controller's state moves on its own (starting, running): look again now and then.
    const t = setInterval(() => { if (!document.hidden) api.telegram().then((r) => (info = { ...r, bot: r.bot ?? info?.bot ?? null })).catch(() => {}); }, 5000);
    return () => clearInterval(t);
  });

  const connected = $derived(!!info?.token_set && !!info?.owner_id);
  const botLink = $derived(info?.bot?.username ? `https://t.me/${info.bot.username}` : "");

  // ── Step 1: the token ──────────────────────────────────────────────────────
  let changingToken = $state(false);
  let token = $state("");
  let showToken = $state(false);
  let tokenBusy = $state(false);
  let tokenErr = $state("");
  async function saveToken() {
    if (!token.trim()) return;
    tokenBusy = true;
    tokenErr = "";
    try {
      const r = await api.telegramToken(token.trim());
      toast(`Connected to @${r.bot.username}.`, "ok");
      token = "";
      changingToken = false;
      botErr = "";
      await load();
      if (info) info = { ...info, bot: r.bot };
    } catch (e: any) {
      tokenErr = e?.message || "That token didn't work.";
    }
    tokenBusy = false;
  }

  // ── Step 2: who you are ────────────────────────────────────────────────────
  let changingOwner = $state(false);
  let people = $state<Person[] | null>(null);
  let finding = $state(false);
  let findErr = $state("");
  let ownerDraft = $state("");
  let ownerBusy = $state(false);
  async function findMe() {
    finding = true;
    findErr = "";
    try {
      const r = await api.telegramFindOwner();
      if (!r.ok) findErr = r.reason;
      else {
        people = r.people;
        if (!r.people.length) findErr = "No messages yet. Send your bot a message, then press Find me again.";
      }
    } catch (e: any) {
      findErr = e?.message || "Couldn't ask Telegram.";
    }
    finding = false;
  }
  async function saveOwner(id: string) {
    ownerBusy = true;
    try {
      await api.telegramOwner(id.trim());
      toast("Saved. Only you can use the bot now.", "ok");
      changingOwner = false;
      people = null;
      ownerDraft = "";
      await load();
    } catch (e: any) {
      findErr = e?.message || "Couldn't save that.";
    }
    ownerBusy = false;
  }

  // ── Step 3, and the top: a test message, starting it ───────────────────────
  let testing = $state(false);
  let tested = $state<"" | "sent" | string>("");
  async function test() {
    testing = true;
    try {
      const r = await api.telegramTest();
      tested = r.ok ? "sent" : r.reason;
    } catch (e: any) {
      tested = e?.message || "It didn't send.";
    }
    testing = false;
  }
  let starting = $state(false);
  async function service(action: "start" | "restart") {
    starting = true;
    try {
      await api.serviceAction("telegram", action);
      toast(action === "start" ? "Starting the controller." : "Restarting the controller.", "ok");
      setTimeout(load, 1200);
    } catch (e: any) {
      toast(e?.message || "It didn't start.", "err");
    }
    starting = false;
  }

  /** "2 h 5 min", for how long it has been up. */
  function upFor(s: number): string {
    if (!s) return "";
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h ? `${h} h${m ? ` ${m} min` : ""}` : m ? `${m} min` : "under a minute";
  }
  const STATES: Record<string, { word: string; tone: string }> = {
    running: { word: "Running", tone: "good" },
    starting: { word: "Starting", tone: "warn" },
    crashing: { word: "Restarting", tone: "bad" },
    stopped: { word: "Stopped", tone: "idle" },
  };
  const st = $derived(STATES[info?.state ?? "stopped"] ?? STATES.stopped);

  // ── Commands ───────────────────────────────────────────────────────────────
  let q = $state("");
  const shownGroups = $derived.by(() => {
    const t = q.trim().toLowerCase().replace(/^\//, "");
    if (!t) return groups;
    return groups
      .map((g) => ({ ...g, commands: g.commands.filter((c) => c.name.includes(t) || c.does.toLowerCase().includes(t)) }))
      .filter((g) => g.commands.length);
  });
  const count = $derived(groups.reduce((n, g) => n + g.commands.length, 0));

  let tokenBox: HTMLInputElement | null = $state(null);
  async function changeToken() {
    changingToken = true;
    await tick();
    tokenBox?.focus();
  }
</script>

{#if loadErr}
  <p class="tg-err">{loadErr}</p>
{:else if !info}
  <div class="tg-hero is-loading" aria-hidden="true"></div>
{:else}
  <!-- Where things stand. -->
  <section class="tg-hero" class:is-on={connected && info.state === "running"}>
    <span class="tg-logo" aria-hidden="true">
      <svg viewBox="0 0 24 24"><path d="M20.7 4.3 2.9 11.2c-1.2.5-1.2 1.2-.2 1.5l4.6 1.4 1.8 5.4c.2.6.4.8.9.8.4 0 .6-.2.9-.5l2.2-2.1 4.6 3.4c.8.5 1.4.2 1.6-.8l3-14c.3-1.3-.5-1.8-1.6-1.4ZM9.8 14.1l-.4 4.1-1.4-4.4L18 7.7l-8.2 6.4Z" /></svg>
    </span>
    <div class="min-w-0 flex-1">
      <div class="tg-title">
        {#if !info.token_set}
          Not connected yet
        {:else if botErr}
          That token didn't work
        {:else if info.bot}
          {connected ? "Connected as" : "Ready:"} <b>@{info.bot.username}</b>
        {:else}
          Checking the token…
        {/if}
      </div>
      <p class="tg-sub">
        {#if !info.token_set}
          Three short steps below, and you can run the bot from your phone.
        {:else if botErr}
          {botErr}
        {:else if !info.owner_id}
          One more step: tell it who you are.
        {:else}
          {info.bot?.name ?? "Your bot"} answers only you (ID {info.owner_id}).
        {/if}
      </p>
      {#if connected}
        <div class="tg-actions">
          {#if botLink}<a class="tg-btn" href={botLink} target="_blank" rel="noreferrer"><Icon name="external" size={12} />Open in Telegram</a>{/if}
          <button type="button" class="tg-btn" onclick={test} disabled={testing}>
            <Icon name="send" size={12} />{testing ? "Sending" : "Send a test"}
          </button>
          {#if info.enabled}
            <button type="button" class="tg-btn" onclick={() => service(info?.state === "stopped" ? "start" : "restart")} disabled={starting}>
              <Icon name={info.state === "stopped" ? "play" : "refresh"} size={12} />{info.state === "stopped" ? "Start" : "Restart"}
            </button>
          {/if}
        </div>
        {#if tested}
          <p class="tg-note" class:is-bad={tested !== "sent"}>{tested === "sent" ? "Sent. Check Telegram." : tested}</p>
        {/if}
      {/if}
    </div>
    {#if connected}
      {#if info.enabled}
        <span class="tg-state is-{st.tone}" title={info.uptime ? `Up for ${upFor(info.uptime)}` : undefined}>
          <i></i>{st.word}{#if info.state === "running" && info.uptime}<em>· {upFor(info.uptime)}</em>{/if}
        </span>
      {:else}
        <button type="button" class="tg-state is-idle" onclick={() => settingsSection.set("app/services")} title="Turn it on in What runs">
          <i></i>Turned off
        </button>
      {/if}
    {/if}
  </section>

  <!-- The three steps. Done ones fold to a line with a way to change them. -->
  <ol class="tg-steps">
    <li class="tg-step" class:is-done={info.token_set && !botErr && !changingToken}>
      <span class="tg-num">{#if info.token_set && !botErr && !changingToken}<Icon name="check" size={12} />{:else}1{/if}</span>
      <div class="min-w-0 flex-1">
        <div class="tg-step-head">
          <b>Make a bot</b>
          {#if info.token_set && !botErr && !changingToken}
            <span class="tg-done">{info.bot ? `@${info.bot.username}` : `Token ${info.token_hint}`}</span>
            <button type="button" class="tg-link" onclick={changeToken}>Change</button>
          {/if}
        </div>
        {#if !info.token_set || botErr || changingToken}
          <p class="tg-how">In Telegram, message <a href="https://t.me/BotFather" target="_blank" rel="noreferrer">@BotFather</a>, send <code>/newbot</code>, pick a name, and paste the token it gives you.</p>
          <form class="tg-row" onsubmit={(e) => { e.preventDefault(); saveToken(); }}>
            <span class="tg-field">
              <input bind:this={tokenBox} bind:value={token} type={showToken ? "text" : "password"} spellcheck="false"
                     autocomplete="off" placeholder="123456789:AAH…" aria-label="Bot token" />
              <button type="button" class="tg-eye" onclick={() => (showToken = !showToken)} aria-label={showToken ? "Hide the token" : "Show the token"}>
                <Icon name={showToken ? "eyeOff" : "eye"} size={13} />
              </button>
            </span>
            <button type="submit" class="tg-go" disabled={tokenBusy || !token.trim()}>{tokenBusy ? "Checking" : "Check and save"}</button>
            {#if changingToken}<button type="button" class="tg-link" onclick={() => { changingToken = false; tokenErr = ""; }}>Cancel</button>{/if}
          </form>
          {#if tokenErr}<p class="tg-note is-bad">{tokenErr}</p>{/if}
        {/if}
      </div>
    </li>

    <li class="tg-step" class:is-done={!!info.owner_id && !changingOwner} class:is-waiting={!info.token_set}>
      <span class="tg-num">{#if info.owner_id && !changingOwner}<Icon name="check" size={12} />{:else}2{/if}</span>
      <div class="min-w-0 flex-1">
        <div class="tg-step-head">
          <b>Tell it who you are</b>
          {#if info.owner_id && !changingOwner}
            <span class="tg-done">ID {info.owner_id}</span>
            <button type="button" class="tg-link" onclick={() => (changingOwner = true)}>Change</button>
          {/if}
        </div>
        {#if (!info.owner_id || changingOwner) && info.token_set}
          <p class="tg-how">So it answers only you. Send
            {#if botLink}<a href={botLink} target="_blank" rel="noreferrer">@{info.bot?.username}</a>{:else}your bot{/if}
            any message, then press Find me.</p>
          <div class="tg-row">
            <button type="button" class="tg-go" onclick={findMe} disabled={finding}>
              <Icon name="search" size={12} />{finding ? "Looking" : "Find me"}
            </button>
            <span class="tg-or">or type it</span>
            <form class="tg-row is-tight" onsubmit={(e) => { e.preventDefault(); saveOwner(ownerDraft); }}>
              <span class="tg-field is-short"><input bind:value={ownerDraft} inputmode="numeric" placeholder="123456789" aria-label="Your Telegram ID"
                                                      use:autowidth={{ value: ownerDraft }} /></span>
              <button type="submit" class="tg-btn" disabled={ownerBusy || !/^\d+$/.test(ownerDraft.trim())}>Save</button>
            </form>
            {#if changingOwner}<button type="button" class="tg-link" onclick={() => { changingOwner = false; people = null; findErr = ""; }}>Cancel</button>{/if}
          </div>
          {#if people?.length}
            <ul class="tg-people">
              {#each people as p (p.id)}
                <li>
                  <span class="tg-avatar" aria-hidden="true">{(p.name[0] ?? "?").toUpperCase()}</span>
                  <span class="min-w-0 flex-1">
                    <b>{p.name}</b>{#if p.username}<em> @{p.username}</em>{/if}
                    {#if p.said}<small>"{p.said}"</small>{/if}
                  </span>
                  <button type="button" class="tg-go" onclick={() => saveOwner(p.id)} disabled={ownerBusy}>That's me</button>
                </li>
              {/each}
            </ul>
          {/if}
          {#if findErr}<p class="tg-note is-bad">{findErr}</p>{/if}
        {:else if !info.token_set}
          <p class="tg-how">After the bot.</p>
        {/if}
      </div>
    </li>

    <li class="tg-step" class:is-done={tested === "sent"} class:is-waiting={!connected}>
      <span class="tg-num">{#if tested === "sent"}<Icon name="check" size={12} />{:else}3{/if}</span>
      <div class="min-w-0 flex-1">
        <div class="tg-step-head">
          <b>Say hi</b>
          {#if tested === "sent"}<span class="tg-done">It works</span>{/if}
        </div>
        {#if connected && tested !== "sent"}
          <p class="tg-how">A message from the bot to you, to be sure it all fits.</p>
          <div class="tg-row">
            <button type="button" class="tg-go" onclick={test} disabled={testing}><Icon name="send" size={12} />{testing ? "Sending" : "Send a test message"}</button>
          </div>
          {#if tested}<p class="tg-note is-bad">{tested}</p>{/if}
        {:else if !connected}
          <p class="tg-how">Once it knows you.</p>
        {/if}
      </div>
    </li>
  </ol>

  {@render alerts?.()}

  <!-- What it can do. -->
  {#if groups.length}
    <section class="tg-cmds">
      <header>
        <div>
          <h3>What you can do from Telegram</h3>
          <p>{count} commands. Click one to copy it.</p>
        </div>
        <label class="tg-search">
          <Icon name="search" size={12} />
          <input bind:value={q} placeholder="Find a command" aria-label="Find a command" />
        </label>
      </header>
      <div class="tg-groups">
        {#each shownGroups as g (g.group)}
          <div class="tg-group">
            <h4>{g.group}</h4>
            {#each g.commands as c (c.name)}
              <button type="button" class="tg-cmd" onclick={() => copyText(`/${c.name}`, `Copied /${c.name}.`)} title="Copy /{c.name}">
                <code>/{c.name}</code><span>{c.does}</span>
              </button>
            {/each}
          </div>
        {:else}
          <p class="tg-how">No command matches "{q}".</p>
        {/each}
      </div>
    </section>
  {/if}
{/if}

<style>
  .tg-err { font-size: 12.5px; color: var(--color-bad); }
  .tg-hero {
    position: relative;
    display: flex;
    align-items: flex-start;
    gap: 14px;
    overflow: hidden;
    padding: 16px;
    border-radius: 16px;
    background:
      radial-gradient(120% 140% at 0% 0%, rgb(42 171 238 / 0.14), transparent 55%),
      rgb(255 255 255 / 0.025);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
  }
  .tg-hero.is-loading { height: 96px; animation: tg-pulse 1.4s ease-in-out infinite; }
  @keyframes tg-pulse { 50% { opacity: 0.5; } }
  .tg-logo {
    position: relative;
    display: grid;
    width: 46px;
    height: 46px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    background: linear-gradient(160deg, #37bbfe, #1e96d7);
    box-shadow: 0 8px 22px -10px rgb(42 171 238 / 0.9);
  }
  .tg-logo svg { width: 24px; height: 24px; fill: #fff; transform: translateX(-1px); }
  /* Running: a slow ring goes out from the logo, like a signal. */
  .tg-hero.is-on .tg-logo::after {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 999px;
    box-shadow: 0 0 0 0 rgb(42 171 238 / 0.55);
    animation: tg-signal 2.6s ease-out infinite;
  }
  @keyframes tg-signal { to { box-shadow: 0 0 0 14px rgb(42 171 238 / 0); } }
  .tg-title { font-size: 15px; font-weight: 650; color: var(--color-ink); }
  .tg-title b { color: #5ec8ff; font-weight: 700; }
  .tg-sub { margin-top: 2px; font-size: 12.5px; color: var(--color-muted); }
  .tg-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .tg-state {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 600;
    background: rgb(255 255 255 / 0.05);
  }
  .tg-state i { width: 7px; height: 7px; border-radius: 999px; background: currentColor; }
  .tg-state em { font-style: normal; font-weight: 500; opacity: 0.7; }
  .tg-state.is-good { color: var(--color-good); }
  .tg-state.is-good i { box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-good) 25%, transparent); }
  .tg-state.is-warn { color: var(--color-warn); }
  .tg-state.is-bad { color: var(--color-bad); }
  .tg-state.is-idle { color: var(--color-faint); }

  .tg-btn, .tg-go {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 11px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 600;
    white-space: nowrap;
    text-decoration: none;
    transition: background-color 0.15s var(--swift), transform 0.3s var(--jelly);
  }
  .tg-btn { color: var(--color-ink); background: rgb(255 255 255 / 0.06); box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.07); }
  .tg-btn:hover:not(:disabled) { background: rgb(255 255 255 / 0.1); }
  .tg-go { color: #06131c; background: linear-gradient(160deg, #5ec8ff, #2aabee); }
  .tg-go:hover:not(:disabled) { filter: brightness(1.08); }
  .tg-btn:active:not(:disabled), .tg-go:active:not(:disabled) { transform: scale(0.96); }
  .tg-btn:disabled, .tg-go:disabled { opacity: 0.5; cursor: default; }
  .tg-link { font-size: 12px; font-weight: 600; color: var(--color-accent); }
  .tg-link:hover { text-decoration: underline; }
  .tg-note { margin-top: 8px; font-size: 12px; color: var(--color-good); }
  .tg-note.is-bad { color: var(--color-bad); }

  .tg-steps { display: flex; flex-direction: column; gap: 2px; margin-top: 14px; }
  .tg-step {
    position: relative;
    display: flex;
    gap: 12px;
    padding: 12px 14px;
    border-radius: 12px;
    transition: background-color 0.2s var(--swift), opacity 0.2s var(--swift);
  }
  .tg-step:not(.is-done):not(.is-waiting) { background: rgb(255 255 255 / 0.025); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 60%, transparent); }
  .tg-step.is-waiting { opacity: 0.55; }
  /* The line joining the steps' numbers. */
  .tg-step + .tg-step::before {
    content: "";
    position: absolute;
    left: 25px;
    top: -8px;
    height: 14px;
    width: 2px;
    border-radius: 2px;
    background: rgb(255 255 255 / 0.08);
  }
  .tg-num {
    display: grid;
    width: 24px;
    height: 24px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.06);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08);
  }
  .tg-step.is-done .tg-num { color: #06131c; background: var(--color-good); box-shadow: none; animation: tg-done 0.45s var(--spring); }
  @keyframes tg-done { from { transform: scale(0.6); } }
  .tg-step-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; min-height: 24px; padding-top: 2px; }
  .tg-step-head b { font-size: 13.5px; font-weight: 600; color: var(--color-ink); }
  .tg-done { font-size: 12px; color: var(--color-muted); }
  .tg-how { margin-top: 3px; font-size: 12px; line-height: 1.5; color: var(--color-muted); }
  .tg-how a { color: #5ec8ff; }
  .tg-how code { padding: 1px 5px; border-radius: 5px; font-size: 11px; background: rgb(255 255 255 / 0.07); color: var(--color-ink); }
  .tg-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 10px; }
  .tg-row.is-tight { margin-top: 0; gap: 6px; }
  .tg-or { font-size: 11.5px; color: var(--color-faint); }
  .tg-field {
    display: inline-flex;
    min-width: 0;
    flex: 1 1 260px;
    max-width: 380px;
    align-items: center;
    border-radius: 10px;
    border: 1px solid var(--color-edge);
    background: rgb(0 0 0 / 0.22);
    transition: border-color 0.15s var(--swift), box-shadow 0.15s var(--swift);
  }
  /* The ID box: as wide as the number in it (lib/autowidth.ts). */
  .tg-field.is-short { flex: 0 0 auto; max-width: 100%; }
  .tg-field.is-short input { flex: none; }
  .tg-field:focus-within { border-color: color-mix(in srgb, #2aabee 70%, transparent); box-shadow: 0 0 0 3px rgb(42 171 238 / 0.16); }
  .tg-field input { min-width: 0; flex: 1; padding: 6px 10px; background: transparent; font-family: ui-monospace, monospace; font-size: 12.5px; color: var(--color-ink); outline: none; }
  .tg-eye { display: grid; padding: 0 9px; place-items: center; color: var(--color-faint); }
  .tg-eye:hover { color: var(--color-ink); }
  .tg-people { display: flex; flex-direction: column; gap: 4px; margin-top: 10px; }
  .tg-people li {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 8px 7px 7px;
    border-radius: 12px;
    background: rgb(255 255 255 / 0.03);
    animation: tg-in 0.35s var(--spring) both;
  }
  @keyframes tg-in { from { opacity: 0; transform: translateY(4px); } }
  .tg-avatar {
    display: grid;
    width: 30px;
    height: 30px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 700;
    color: #fff;
    background: linear-gradient(160deg, #6fd0ff, #2a8fd6);
  }
  .tg-people b { font-size: 12.5px; font-weight: 600; color: var(--color-ink); }
  .tg-people em { font-style: normal; font-size: 11.5px; color: var(--color-muted); }
  .tg-people small { display: block; overflow: hidden; font-size: 11px; color: var(--color-faint); text-overflow: ellipsis; white-space: nowrap; }

  .tg-cmds { margin-top: 18px; }
  .tg-cmds header { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
  .tg-cmds h3 { font-size: 13.5px; font-weight: 650; color: var(--color-ink); }
  .tg-cmds header p { font-size: 11.5px; color: var(--color-faint); }
  .tg-search {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 10px;
    border-radius: 10px;
    border: 1px solid var(--color-edge);
    background: rgb(0 0 0 / 0.2);
    color: var(--color-faint);
  }
  .tg-search input { width: 150px; background: transparent; font-size: 12px; color: var(--color-ink); outline: none; }
  .tg-groups { columns: 2 260px; column-gap: 14px; }
  .tg-group { break-inside: avoid; margin-bottom: 12px; }
  .tg-group h4 { margin: 0 0 4px 8px; font-size: 10.5px; font-weight: 650; letter-spacing: 0.08em; text-transform: uppercase; color: var(--color-faint); }
  .tg-cmd {
    display: flex;
    width: 100%;
    align-items: baseline;
    gap: 8px;
    padding: 4px 8px;
    border-radius: 8px;
    text-align: left;
    transition: background-color 0.15s var(--swift);
  }
  .tg-cmd:hover { background: rgb(42 171 238 / 0.1); }
  .tg-cmd code { flex-shrink: 0; font-size: 11.5px; font-weight: 600; color: #5ec8ff; }
  .tg-cmd span { min-width: 0; font-size: 11.5px; color: var(--color-muted); }

  :global(:root[data-motion="off"]) .tg-hero .tg-logo::after,
  :global(:root[data-motion="off"]) .tg-step .tg-num,
  :global(:root[data-motion="off"]) .tg-people li,
  :global(:root[data-motion="off"]) .tg-hero.is-loading { animation: none; }
</style>
