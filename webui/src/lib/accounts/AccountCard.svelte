<script lang="ts">
  /**
   * One account, as a card you can run it from.
   *
   * The old page was a row per account with six buttons of equal weight in a
   * line - Stop, Restart, Pause replies, Edit, Delete and a chevron - so the
   * thing you do most looked exactly like the thing you almost never want, and
   * everything worth knowing about the account sat behind the chevron. It also
   * read as an empty page unless you had a stack of accounts to fill it.
   *
   * Now each account carries its own picture: who it is, what it is doing in
   * words rather than a process state, what it has done this week, and one
   * obvious power control. The rest - pausing replies, the login, its chats
   * and log - lives in the ⋯ menu, with removal set apart at the bottom.
   */
  import Avatar from "../components/Avatar.svelte";
  import Badge from "../components/Badge.svelte";
  import Button from "../components/Button.svelte";
  import Icon from "../components/Icon.svelte";
  import WeekBars from "./WeekBars.svelte";
  import StatusDot from "../components/StatusDot.svelte";
  import UserChip from "../components/UserChip.svelte";
  import { menu as contextMenu, copyText, type MenuEntry } from "../contextmenu";
  import {
    ago, condition, platformName, presenceName, presenceOf, uptime,
    type Details, type Runtime, type Slot,
  } from "./condition";
  import type { Activity } from "./state";
  import { fly } from "svelte/transition";
  import { get } from "svelte/store";
  import { motionEnabled } from "../stores";
  import { play } from "../uisound";
  import PersonaOrb from "../personas/PersonaOrb.svelte";
  import PersonaMenu from "../personas/PersonaMenu.svelte";
  import { colorOf, personaOf } from "../personas/logic";
  import { personasRes } from "../personas/store";

  let {
    slot,
    rt,
    d,
    act,
    dates = [],
    waiting = null,
    moods = [],
    acting = "",
    onaction,
    onedit,
    ondelete,
    onprofile,
    onmood,
    onchats,
    onlogs,
    onsettings,
    onpersona,
  }: {
    slot: Slot;
    rt?: Runtime;
    d?: Details;
    act?: Activity;
    /** The calendar day of each value in act.series, oldest first. */
    dates?: string[];
    /** People waiting for a reply on this account, null when not known yet. */
    waiting?: number | null;
    moods?: string[];
    /** "<id>:<action>" while one is in flight. */
    acting?: string;
    onaction: (act: string) => void;
    onedit: () => void;
    ondelete: () => void;
    onprofile?: () => void;
    onmood: (m: string) => void;
    onchats: () => void;
    onlogs: () => void;
    onsettings: (to: string) => void;
    /** Give it another persona (the page saves it and restarts the account). */
    onpersona?: (pid: string) => void;
  } = $props();

  // ── Who it speaks as ───────────────────────────────────────────────────────
  // A chip on the banner, opposite the platform's: pressed, the personas to give it.
  const cast = $derived($personasRes.data);
  const persona = $derived(cast.personas.length ? personaOf(cast, slot.id) : undefined);
  let personaOpen = $state(false);
  let personaEl: HTMLElement | null = $state(null);
  /** The banner lights up in the colour picked, once, as the account takes it. */
  let flashKey = $state(0);
  let flashColor = $state("");
  function pickPersona(pid: string) {
    flashColor = colorOf(cast.personas.find((p) => p.id === pid));
    flashKey++;
    play("glint", { delay: 80 });
    onpersona?.(pid);
  }
  // The chip grows or shrinks to the new name rather than jumping to it: its width before the change, then a glide.
  let chipWas = 0;
  $effect.pre(() => {
    void persona?.name;
    if (personaEl) chipWas = personaEl.offsetWidth;
  });
  $effect(() => {
    void persona?.name;
    const el = personaEl;
    if (!el || !chipWas) return;
    const now = el.offsetWidth;
    if (now !== chipWas && get(motionEnabled)) {
      el.animate([{ width: `${chipWas}px` }, { width: `${now}px` }],
                 { duration: 420, easing: "cubic-bezier(0.22, 1.25, 0.36, 1)" });
    }
  });

  const cond = $derived(condition(slot, rt, d));
  const name = $derived(rt?.display_name || rt?.username || slot.username || `${platformName(slot.platform)} #${slot.index}`);

  /** Right-click on the card: what the buttons and the ... menu do, in one place. */
  function cardMenu(): MenuEntry[] {
    return [
      { title: name },
      cond.running
        ? { label: "Restart", icon: "refresh", run: () => onaction("restart") }
        : { label: "Start", icon: "play", disabled: !cond.canStart, run: () => onaction("start") },
      cond.running && { label: "Stop", icon: "stop", run: () => onaction("stop") },
      cond.reachable && { label: cond.paused ? "Resume replies" : "Pause replies", icon: cond.paused ? "play" : "pause",
                          run: () => onaction("pause") },
      "sep",
      { label: "Chats", icon: "chats", run: onchats },
      { label: "Logs", icon: "logs", run: onlogs },
      onprofile && slot.platform === "discord" && rt && { label: "Profile", icon: "accounts", run: onprofile },
      { label: "Edit login", icon: "edit", run: onedit },
      cond.reachable && slot.platform === "discord" && { label: "Reload commands", icon: "terminal", run: () => onaction("reload") },
      "sep",
      { label: "Copy name", icon: "copy", run: () => copyText(name, "Copied the name.") },
      rt?.username && { label: "Copy username", icon: "copy", run: () => copyText(rt?.username ?? "", "Copied the username.") },
      "sep",
      { label: "Remove account", icon: "trash", danger: true, run: ondelete },
    ];
  }
  // The @handle under the name, when the name is not already it.
  const handle = $derived(rt?.username && rt.username !== name ? rt.username : "");
  // It can be selected like any text, and copied in one click: it is what someone searches to add the account.
  let handleCopied = $state(false);
  async function copyHandle() {
    await copyText(handle, "Copied the username.");
    handleCopied = true;
    setTimeout(() => (handleCopied = false), 1400);
  }
  /** A Snapchat account the runner has read, with no photo or Bitmoji: Snapchat's own empty silhouette, as Snapchat draws it. */
  const silhouette = $derived(slot.platform === "snapchat" && !rt?.avatar && !!rt?.username);
  const presence = $derived(presenceOf(slot, rt, d));
  const busyWith = (a: string) => acting === `${rt?.id}:${a}`;

  // ── Popovers ───────────────────────────────────────────────────────────────
  let menu = $state<"" | "more" | "mood">("");
  let confirmWipe = $state(false);
  let menuEl: HTMLElement | null = $state(null);
  let moodEl: HTMLElement | null = $state(null);

  $effect(() => {
    if (!menu) {
      confirmWipe = false;
      return;
    }
    const el = menu === "more" ? menuEl : moodEl;
    const off = (e: MouseEvent) => {
      if (el && !el.contains(e.target as Node)) menu = "";
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && (menu = "");
    const t = setTimeout(() => window.addEventListener("click", off), 0);
    window.addEventListener("keydown", esc);
    return () => {
      clearTimeout(t);
      window.removeEventListener("click", off);
      window.removeEventListener("keydown", esc);
    };
  });

  function pick(fn: () => void) {
    menu = "";
    fn();
  }

  function wipe() {
    // Two clicks, in place: a dialog for this would be heavier than the thing
    // it guards, but one stray click should not clear every conversation.
    if (!confirmWipe) {
      confirmWipe = true;
      return;
    }
    pick(() => onaction("wipe"));
  }

  // ── Figures ────────────────────────────────────────────────────────────────
  // The last seven days: the chart is a week, the same week as the figure.
  const week = $derived((act?.series ?? []).slice(-7));
  const weekDates = $derived(dates.slice(-7));
  const top = $derived(act?.top ?? []);
  const topMax = $derived(Math.max(1, ...top.map((t) => t.count)));

  function alertAct() {
    const a = cond.alert?.action;
    if (!a) return;
    if (a.kind === "edit") onedit();
    else if (a.kind === "logs") onlogs();
    else if (a.kind === "settings") onsettings(a.to || "");
    else if (a.kind === "start") onaction("start");
  }

  const ping = $derived(d?.latency_ms ?? null);
</script>

<article
  class="acct glass"
  use:contextMenu={cardMenu}
  class:is-live={cond.live}
  class:is-busy={cond.busy}
  class:is-down={!cond.running}
  class:is-paused={cond.paused}
  class:is-bad={cond.tone === "bad"}
  class:is-raised={!!menu || personaOpen}
>
  <!-- ── Who it speaks as: top left, opposite the platform. Ahead of the banner
       so the banner, platform and name stay next to each other (the banner
       styles look along them). ──────────────────────────────────────────── -->
  {#if persona && onpersona}
    <button type="button" class="acct-persona" class:is-open={personaOpen} bind:this={personaEl}
            style="--persona-color: {colorOf(persona)}" aria-haspopup="listbox" aria-expanded={personaOpen}
            title="Its profile" data-sound="self"
            onclick={() => { if (!personaOpen) play("open"); personaOpen = !personaOpen; }}>
      <PersonaOrb p={persona} size={16} ring={false} />
      {#key persona.id}
        <span class="acct-persona-name" in:fly={{ y: 6, duration: get(motionEnabled) ? 280 : 0 }}>{persona.name}</span>
      {/key}
      <span class="acct-persona-chev"><Icon name="chevron" size={9} /></span>
    </button>
    <PersonaMenu bind:open={personaOpen} anchor={personaEl} list={cast.personas} selected={persona.id} title="Profile"
                 footer={{ label: "Edit profiles", icon: "layers", onclick: () => (window.location.hash = "/profiles") }}
                 onpick={pickPersona} />
  {/if}
  <!-- ── Banner: the account's own, as on its Discord profile. The colour it
       picked instead of one, when that is all it has, and otherwise its
       picture blown up and blurred. ─────────────────────────────────────── -->
  <div class="acct-banner" class:has-banner={!!rt?.banner} class:has-colour={!rt?.banner && !!rt?.accent}
       style={!rt?.banner && rt?.accent ? `--acct-colour: ${rt.accent}` : undefined} aria-hidden="true">
    {#if rt?.banner}
      <img src={rt.banner} alt="" referrerpolicy="no-referrer" class="acct-banner-img is-banner" />
    {:else if rt?.accent}
      <div class="acct-banner-colour"></div>
    {:else if rt?.avatar}
      <img src={rt.avatar} alt="" referrerpolicy="no-referrer" class="acct-banner-img" />
    {/if}
    <div class="acct-banner-glow"></div>
    {#key flashKey}
      {#if flashKey}<div class="acct-banner-flash" style="--flash: {flashColor}"></div>{/if}
    {/key}
  </div>
  <span class="acct-platform">
    <Icon name={slot.platform === "snapchat" ? "snapchat" : "discord"} size={12} />
    {platformName(slot.platform)} #{slot.index}
  </span>

  <!-- ── Who, and what it is doing ────────────────────────────────────────── -->
  <div class="relative flex items-end gap-3.5 px-5">
    <span class="acct-avatar halo" class:is-live={cond.live} class:is-busy={cond.busy} title={cond.label}>
      {#if rt?.avatar || silhouette}
        <Avatar src={rt?.avatar ?? ""} {name} size={68} ring="ring-[3px] ring-black/30" {silhouette} />
      {:else}
        <span class="flex h-[68px] w-[68px] items-center justify-center rounded-full bg-white/[0.07] text-accent ring-[3px] ring-black/30">
          <Icon name={slot.platform === "snapchat" ? "snapchat" : "discord"} size={28} />
        </span>
      {/if}
      <span class="acct-dot">
        <StatusDot status={presence} size={14} title={slot.platform === "discord" ? presenceName(presence) : cond.label} />
      </span>
    </span>
    <div class="min-w-0 flex-1 pb-1">
      <div class="flex min-w-0 items-center gap-2">
        {#if onprofile && slot.platform === "discord" && rt}
          <button class="user-chip min-w-0 truncate text-left text-[16px] font-semibold tracking-tight"
                  onclick={onprofile} title="See this account's profile">{name}</button>
        {:else}
          <span class="selectable min-w-0 truncate text-[16px] font-semibold tracking-tight text-ink">{name}</span>
        {/if}
      </div>
      <div class="mt-0.5 flex min-w-0 items-center gap-1.5 text-[12px] text-muted">
        {#if handle}
          <span class="selectable acct-handle truncate">@{handle}</span>
          <button type="button" class="acct-copy" class:is-done={handleCopied} onclick={copyHandle}
                  aria-label="Copy @{handle}" title="Copy @{handle}">
            <Icon name={handleCopied ? "check" : "copy"} size={11} />
          </button>
          <span class="text-faint">·</span>
        {/if}
        <span class="truncate">{cond.line}</span>
      </div>
    </div>
    <span class="acct-state pb-1.5">
      <!-- One sign that it is working on something, not a dot and a spinner. -->
      <Badge tone={cond.tone} dot={!cond.busy}>
        {#if cond.busy}<span class="acct-spin"></span>{/if}{cond.label}
      </Badge>
    </span>
  </div>

  <div class="space-y-4 px-5 pb-4 pt-4">
    <!-- ── Anything that needs doing, with the button that does it ────────── -->
    {#if cond.alert}
      <div class="acct-alert" class:is-bad={cond.alert.tone === "bad"} role="status">
        <span class="mt-0.5 shrink-0"><Icon name="alert" size={15} /></span>
        <div class="min-w-0 flex-1">
          <div class="text-[12.5px] font-semibold">{cond.alert.title}</div>
          <div class="mt-0.5 break-words text-[12px] leading-snug opacity-85">{cond.alert.text}</div>
        </div>
        {#if cond.alert.action}
          <button class="acct-alert-btn" onclick={alertAct}>{cond.alert.action.label}</button>
        {/if}
      </div>
    {/if}

    <!-- ── Figures ────────────────────────────────────────────────────────── -->
    <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <div class="acct-fig">
        <div class="acct-fig-n">{act?.today ?? 0}</div>
        <div class="acct-fig-l">replies today</div>
      </div>
      <div class="acct-fig">
        <div class="acct-fig-n">{act?.week ?? 0}</div>
        <div class="acct-fig-l">this week</div>
      </div>
      <button class="acct-fig acct-fig-btn text-left" class:is-waiting={!!waiting} onclick={onchats}
              title="Open this account's chats">
        <div class="acct-fig-n">{waiting ?? "–"}</div>
        <div class="acct-fig-l">waiting</div>
      </button>
      <div class="acct-fig">
        {#if rt?.state === "crashing"}
          <!-- Uptime means nothing for a worker that keeps falling over. -->
          <div class="acct-fig-n text-bad">{rt.restarts}</div>
          <div class="acct-fig-l">restarts</div>
        {:else if cond.running && rt?.uptime}
          <div class="acct-fig-n">{uptime(rt.uptime)}</div>
          <div class="acct-fig-l">up for</div>
        {:else}
          <div class="acct-fig-n truncate">{act?.last ? ago(act.last.ts).replace(" ago", "") : "–"}</div>
          <div class="acct-fig-l">{act?.last ? "since a reply" : "no replies yet"}</div>
        {/if}
      </div>
    </div>

    <!-- ── This week ──────────────────────────────────────────────────────── -->
    <div>
      <div class="mb-1 flex items-baseline justify-between gap-3 text-[11px]">
        <span class="font-medium text-muted">Replies this week</span>
        {#if act?.last}
          <span class="min-w-0 truncate text-faint">
            Last to <span class="text-muted">{act.last.name}</span> · {ago(act.last.ts)}
          </span>
        {/if}
      </div>
      {#if week.length}
        <WeekBars values={week} dates={weekDates} />
      {/if}
    </div>

    <!-- Who it has been talking to, as faces with a bar for how much: names
         alone in a row of pills said nothing about either. -->
    {#if top.length}
      <div>
        <div class="mb-1.5 text-[11px] font-medium text-muted">Talked to most this week</div>
        <div class="grid grid-cols-2 gap-1.5">
          {#each top as t (t.id)}
            <div class="acct-person">
              <span class="acct-person-fill" style="width:{Math.round((t.count / topMax) * 100)}%"></span>
              {#if t.avatar}
                <Avatar src={t.avatar} name={t.name} size={22} ring="ring-1 ring-white/10" zoom={false} />
              {:else}
                <span class="acct-initial">{(t.name || "?").slice(0, 1).toUpperCase()}</span>
              {/if}
              <span class="relative min-w-0 flex-1 truncate text-[12px]">
                <UserChip id={t.id} name={t.name} />
              </span>
              <span class="relative text-[11px] tabular-nums text-muted">{t.count}</span>
            </div>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Live facts, only what the worker actually reported. -->
    {#if cond.reachable && d}
      <div class="flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-muted">
        {#if ping != null}
          <!-- Discord's own thresholds for its ping readout. -->
          <span><span class={ping < 200 ? "text-good" : ping < 500 ? "text-warn" : "text-bad"}>{ping} ms</span> ping</span>
        {/if}
        {#if d.guilds != null}<span><span class="text-ink">{d.guilds}</span> servers</span>{/if}
        {#if d.friends != null}<span><span class="text-ink">{d.friends}</span> friends</span>{/if}
        <span><span class="text-ink">{d.active_channels ?? 0}</span> {slot.platform === "snapchat" ? "chats watched" : "chats open"}</span>
        {#if d.ignored_users}<span><span class="text-ink">{d.ignored_users}</span> ignored</span>{/if}
      </div>
    {/if}
  </div>

  <!-- ── Controls ─────────────────────────────────────────────────────────── -->
  <footer class="acct-controls">
    <div class="flex min-w-0 items-center gap-2.5">
      {#if cond.reachable}
        <div class="relative" bind:this={moodEl}>
          <button class="acct-chip" class:is-on={menu === "mood"} onclick={() => (menu = menu === "mood" ? "" : "mood")}
                  title="Set its mood" aria-expanded={menu === "mood"}>
            <span class="text-faint">Mood</span>
            <span class="max-w-[7rem] truncate">{d?.mood || "not set"}</span>
          </button>
          {#if menu === "mood"}
            <div class="acct-pop glass floating pop left-0 w-56" role="menu">
              <div class="mb-1.5 px-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-faint">Mood</div>
              {#if moods.length}
                <div class="flex flex-wrap gap-1">
                  {#each moods as m}
                    <button
                      class="jelly rounded-lg px-2 py-1 text-[11.5px] transition-colors
                             {d?.mood === m ? 'bg-accent/20 text-accent' : 'bg-white/[0.05] text-muted hover:bg-white/[0.09] hover:text-ink'}"
                      onclick={() => pick(() => onmood(m))}
                    >{m}</button>
                  {/each}
                </div>
              {:else}
                <p class="px-1 text-[11.5px] text-faint">No moods are set up. Add some under Persona.</p>
              {/if}
              <p class="mt-2 px-1 text-[10.5px] leading-snug text-faint">Until it drifts to another on its own.</p>
            </div>
          {/if}
        </div>
      {/if}
    </div>

    <div class="ml-auto flex shrink-0 items-center gap-1.5">
      {#if cond.running}
        <Button size="sm" kind="ghost" loading={busyWith("restart")} onclick={() => onaction("restart")}>
          {#if !busyWith("restart")}<Icon name="refresh" size={13} />{/if}Restart
        </Button>
        <Button size="sm" kind="ghost" loading={busyWith("stop")} onclick={() => onaction("stop")}>
          {#if !busyWith("stop")}<Icon name="stop" size={12} />{/if}Stop
        </Button>
      {:else}
        <Button size="sm" loading={busyWith("start")} disabled={!cond.canStart} onclick={() => onaction("start")}>
          {#if !busyWith("start")}<Icon name="play" size={12} />{/if}Start
        </Button>
      {/if}

      <div class="relative" bind:this={menuEl}>
        <button class="acct-icon-btn" class:is-on={menu === "more"} onclick={() => (menu = menu === "more" ? "" : "more")}
                aria-label="More for this account" aria-expanded={menu === "more"} title="More">
          <Icon name="more" size={16} />
        </button>
        {#if menu === "more"}
          <div class="acct-pop glass floating pop right-0 w-60" role="menu">
            {#if cond.reachable}
              <!-- Stays signed in and online, just stops answering. -->
              <button class="acct-item" role="menuitem" onclick={() => pick(() => onaction("pause"))}>
                <Icon name={cond.paused ? "play" : "pause"} size={14} />
                <span>{cond.paused ? "Resume replies" : "Pause replies"}</span>
              </button>
              <div class="acct-sep"></div>
            {/if}
            <button class="acct-item" role="menuitem" onclick={() => pick(onedit)}>
              <Icon name="edit" size={14} /><span>Edit login</span>
            </button>
            {#if onprofile && slot.platform === "discord" && rt}
              <button class="acct-item" role="menuitem" onclick={() => pick(onprofile)}>
                <Icon name="accounts" size={14} /><span>Profile</span>
              </button>
            {/if}
            <button class="acct-item" role="menuitem" onclick={() => pick(onchats)}>
              <Icon name="chats" size={14} /><span>Chats</span>
            </button>
            <button class="acct-item" role="menuitem" onclick={() => pick(onlogs)}>
              <Icon name="logs" size={14} /><span>Logs</span>
            </button>
            {#if cond.reachable}
              <div class="acct-sep"></div>
              {#if slot.platform === "discord"}
                <button class="acct-item" role="menuitem" onclick={() => pick(() => onaction("reload"))}>
                  <Icon name="terminal" size={14} /><span>Reload commands</span>
                </button>
              {/if}
              <button class="acct-item" class:is-danger={confirmWipe} role="menuitem" onclick={wipe}>
                <Icon name="eraser" size={14} />
                <span>{confirmWipe ? "Click again to forget them" : "Forget conversations"}</span>
              </button>
            {/if}
            <div class="acct-sep"></div>
            <button class="acct-item is-danger" role="menuitem" onclick={() => pick(ondelete)}>
              <Icon name="trash" size={14} /><span>Remove account</span>
            </button>
          </div>
        {/if}
      </div>
    </div>
  </footer>
</article>

<style>
  .acct {
    position: relative;
    display: flex;
    flex-direction: column;
    border-radius: 20px;
    transition: border-color 0.25s ease, box-shadow 0.3s ease, transform 0.35s var(--spring);
  }
  .acct.is-raised {
    z-index: 20;
  }
  .acct.is-live {
    border-color: color-mix(in srgb, var(--color-accent) 22%, var(--color-edge));
  }
  .acct.is-bad {
    border-color: color-mix(in srgb, var(--color-bad) 35%, var(--color-edge));
  }

  /* The banner takes the account's own picture, blown up and blurred into a
     wash of its colours, so every card looks like the account it is. Faded
     out with a mask rather than a gradient to the card colour: under the glass
     surfaces the card is see-through, and a gradient to a solid colour would
     draw a band across it. */
  .acct-banner {
    position: relative;
    height: 78px;
    overflow: hidden;
    border-radius: 20px 20px 0 0;
    -webkit-mask-image: linear-gradient(to bottom, #000 35%, transparent);
    mask-image: linear-gradient(to bottom, #000 35%, transparent);
  }
  .acct-banner-img {
    position: absolute;
    inset: -40%;
    width: 180%;
    height: 180%;
    object-fit: cover;
    filter: blur(26px) saturate(1.5);
    opacity: 0.55;
    transition: filter 0.5s ease, opacity 0.5s ease;
  }
  /* A real banner is the picture itself, so it is only softened: the avatar
     above is blown up until it is just its colours, a banner is meant to be
     seen. Scaled a little so the blur has no hard edge at the sides. */
  .acct-banner-img.is-banner {
    inset: 0;
    width: 100%;
    height: 100%;
    filter: blur(4px) saturate(1.1);
    opacity: 0.85;
    transform: scale(1.05);
  }
  /* A real banner: a band as tall as Discord's own profile header, blurred
     just enough to sit behind the card and still read as the picture, with
     the avatar overlapping its lower edge. Shown whole at 5:2 it was over
     180px of picture with nothing on it above the name. */
  .acct-banner.has-banner {
    height: 112px;
    -webkit-mask-image: linear-gradient(to bottom, #000 55%, transparent);
    mask-image: linear-gradient(to bottom, #000 55%, transparent);
  }
  .acct-banner.has-banner + .acct-platform + div .acct-avatar { margin-top: -46px; }
  .acct-banner.has-colour { height: 104px; }
  .acct-banner-colour {
    position: absolute;
    inset: -30%;
    background:
      radial-gradient(60% 90% at 25% 30%, var(--acct-colour), transparent 70%),
      radial-gradient(70% 90% at 80% 20%, color-mix(in srgb, var(--acct-colour) 80%, white 20%), transparent 70%),
      color-mix(in srgb, var(--acct-colour) 55%, transparent);
    filter: blur(22px);
    opacity: 0.75;
    transition: filter 0.5s ease, opacity 0.5s ease;
  }
  /* The account's own colours lead; the theme's glow only tints them. */
  .acct-banner.has-banner .acct-banner-glow,
  .acct-banner.has-colour .acct-banner-glow {
    opacity: 0.3;
  }
  .acct-banner-glow {
    position: absolute;
    inset: 0;
    background:
      radial-gradient(120% 140% at 15% 0%, color-mix(in srgb, var(--color-accent) 42%, transparent), transparent 60%),
      radial-gradient(90% 120% at 100% 0%, color-mix(in srgb, var(--color-accent-2, var(--color-accent)) 26%, transparent), transparent 65%);
    opacity: 0.8;
    transition: opacity 0.5s ease, filter 0.5s ease;
  }
  /* Not running: the colour drains out, so a stopped account reads as one
     from across the room. */
  /* The blur is restated: a filter replaces the whole list, so grayscale on
     its own dropped the blur and left the picture sharp with a hard edge. */
  .acct.is-down .acct-banner-img {
    filter: blur(26px) grayscale(1);
    opacity: 0.28;
  }
  .acct.is-down .acct-banner-img.is-banner {
    filter: blur(4px) grayscale(1);
    opacity: 0.4;
  }
  .acct.is-down .acct-banner-colour {
    filter: blur(22px) grayscale(1);
    opacity: 0.3;
  }
  .acct.is-down .acct-banner-glow {
    filter: grayscale(1);
    opacity: 0.28;
  }
  .acct.is-paused .acct-banner-glow {
    background: radial-gradient(120% 140% at 15% 0%, color-mix(in srgb, var(--color-warn) 30%, transparent), transparent 62%);
  }
  .acct.is-bad .acct-banner-glow {
    background: radial-gradient(120% 140% at 15% 0%, color-mix(in srgb, var(--color-bad) 34%, transparent), transparent 62%);
    opacity: 1;
    filter: none;
  }

  .acct-platform {
    position: absolute;
    top: 12px;
    right: 12px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 8px 3px 7px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: var(--color-ink);
    background: rgb(0 0 0 / 0.32);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08);
  }

  /* Who it speaks as: the platform pill's twin on the other side, in the
     persona's colour. The colour glides to a new one (--persona-color is
     registered in app.css) as the width does (the script). */
  .acct-persona {
    position: absolute;
    top: 10px;
    left: 12px;
    z-index: 2;
    display: inline-flex;
    max-width: calc(100% - 150px);
    align-items: center;
    gap: 6px;
    overflow: hidden;
    padding: 3px 8px 3px 3px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.02em;
    white-space: nowrap;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--persona-color) 26%, rgb(0 0 0 / 0.38));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--persona-color) 45%, transparent);
    transition: --persona-color 0.5s var(--swift), box-shadow 0.25s ease, transform 0.35s var(--jelly);
  }
  .acct-persona:hover { box-shadow: inset 0 0 0 1px var(--persona-color), 0 0 14px -4px var(--persona-color); }
  .acct-persona:active { transform: scale(0.96); }
  .acct-persona.is-open { box-shadow: inset 0 0 0 1px var(--persona-color), 0 0 16px -4px var(--persona-color); }
  .acct-persona-name { overflow: hidden; text-overflow: ellipsis; }
  .acct-persona-chev { display: grid; opacity: 0.6; transform: rotate(90deg); transition: transform 0.3s var(--jelly); }
  .acct-persona.is-open .acct-persona-chev { transform: rotate(-90deg); }
  /* The banner lights up in the persona's colour as the account takes it, and fades back. */
  /* Screened on, so it lights any banner up, a busy photo as much as a plain colour. */
  .acct-banner-flash {
    position: absolute;
    inset: 0;
    background:
      radial-gradient(110% 160% at 14% 0%, var(--flash), transparent 68%),
      radial-gradient(80% 130% at 92% 8%, color-mix(in srgb, var(--flash) 60%, transparent), transparent 72%);
    mix-blend-mode: screen;
    opacity: 0;
    pointer-events: none;
    animation: acct-flash 0.9s ease-out;
  }
  @keyframes acct-flash { 18% { opacity: 1; } 100% { opacity: 0; } }

  /* A fixed square. The ring around it is the app's shared .halo (app.css):
     a slow breath while the account is up and replying, amber and faster while
     it connects. Paused and down get none. */
  /* The copy button by the @username: there when the pointer is near, ticked once it has copied. */
  .acct-copy {
    display: grid;
    width: 20px;
    height: 20px;
    flex-shrink: 0;
    place-items: center;
    margin-left: -2px;
    border-radius: 6px;
    color: var(--color-faint);
    opacity: 0;
    transition: opacity 0.15s ease, color 0.15s ease, background-color 0.15s ease, transform 0.2s var(--spring);
  }
  div:hover > .acct-copy, .acct-copy:focus-visible, .acct-copy.is-done { opacity: 1; }
  .acct-copy:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
  .acct-copy:active { transform: scale(0.88); }
  .acct-copy.is-done { color: var(--color-good); }
  .acct-avatar {
    width: 68px;
    height: 68px;
    margin-top: -40px;
  }
  .acct.is-down .acct-avatar :global(img) {
    filter: grayscale(0.85);
    opacity: 0.8;
  }
  .acct.is-down .acct-avatar :global(.avatar-silhouette) { opacity: 0.8; }
  @keyframes acct-turn {
    to { transform: rotate(360deg); }
  }
  /* The presence dot sits on a notch cut out of the avatar, as Discord draws
     its own: without the notch it reads as a sticker. */
  .acct-dot {
    position: absolute;
    right: 0;
    bottom: 1px;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: 999px;
    background: var(--color-card);
  }

  .acct-spin {
    width: 9px;
    height: 9px;
    margin-right: 1px;
    border-radius: 999px;
    border: 1.5px solid currentColor;
    border-top-color: transparent;
    animation: acct-turn 0.9s linear infinite;
  }

  .acct-alert {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 12px;
    border-radius: 12px;
    color: var(--color-warn);
    background: color-mix(in srgb, var(--color-warn) 9%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-warn) 22%, transparent);
  }
  .acct-alert.is-bad {
    color: var(--color-bad);
    background: color-mix(in srgb, var(--color-bad) 9%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-bad) 24%, transparent);
  }
  .acct-alert-btn {
    flex-shrink: 0;
    align-self: center;
    padding: 5px 10px;
    border-radius: 9px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.08);
    transition: background-color 0.15s ease, transform 0.15s var(--spring);
  }
  .acct-alert-btn:hover { background: rgb(255 255 255 / 0.14); }
  .acct-alert-btn:active { transform: scale(0.95); }

  .acct-fig {
    min-width: 0;
    padding: 9px 11px;
    border-radius: 12px;
    background: rgb(255 255 255 / 0.035);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.03);
  }
  .acct-fig-n {
    font-size: 17px;
    font-weight: 600;
    line-height: 1.2;
    color: var(--color-ink);
    font-variant-numeric: tabular-nums;
  }
  .acct-fig-l {
    margin-top: 1px;
    font-size: 10.5px;
    color: var(--color-faint);
    white-space: nowrap;
  }
  .acct-fig-btn {
    transition: background-color 0.15s ease, box-shadow 0.15s ease, transform 0.2s var(--spring);
  }
  .acct-fig-btn:hover {
    background: rgb(255 255 255 / 0.06);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 30%, transparent);
  }
  .acct-fig-btn:active { transform: scale(0.97); }
  .acct-fig-btn.is-waiting .acct-fig-n { color: var(--color-warn); }

  .acct-person {
    position: relative;
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 8px;
    padding: 5px 9px 5px 5px;
    overflow: hidden;
    border-radius: 10px;
    background: rgb(255 255 255 / 0.03);
  }
  /* How much, as a wash behind the row, relative to the one talked to most. */
  .acct-person-fill {
    position: absolute;
    inset: 0 auto 0 0;
    background: color-mix(in srgb, var(--color-accent) 13%, transparent);
    border-radius: inherit;
  }
  .acct-initial {
    position: relative;
    display: flex;
    width: 22px;
    height: 22px;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 700;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 16%, transparent);
  }

  .acct-controls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    margin-top: auto;
    padding: 12px 16px 12px 20px;
    border-top: 1px solid color-mix(in srgb, var(--color-edge) 70%, transparent);
  }

  .acct-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 9px;
    border-radius: 9px;
    font-size: 11.5px;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.05);
    transition: background-color 0.15s ease;
  }
  .acct-chip:hover, .acct-chip.is-on { background: rgb(255 255 255 / 0.09); }

  .acct-icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 28px;
    border-radius: 9px;
    color: var(--color-muted);
    transition: background-color 0.15s ease, color 0.15s ease, transform 0.15s var(--spring);
  }
  .acct-icon-btn:hover, .acct-icon-btn.is-on {
    background: rgb(255 255 255 / 0.07);
    color: var(--color-ink);
  }
  .acct-icon-btn:active { transform: scale(0.9); }

  /* Menus open upwards: they hang off the bottom edge of the card, and
     downwards they would run off the page on the last row. */
  .acct-pop {
    position: absolute;
    bottom: calc(100% + 8px);
    z-index: 30;
    padding: 6px;
    border-radius: 14px;
  }
  .acct-item {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 10px;
    padding: 7px 9px;
    border-radius: 9px;
    font-size: 12.5px;
    color: var(--color-ink);
    text-align: left;
    transition: background-color 0.12s ease, color 0.12s ease;
  }
  .acct-item :global(svg) { color: var(--color-muted); }
  .acct-item:hover { background: rgb(255 255 255 / 0.07); }
  .acct-item.is-danger, .acct-item.is-danger :global(svg) { color: var(--color-bad); }
  .acct-item.is-danger:hover { background: color-mix(in srgb, var(--color-bad) 12%, transparent); }
  .acct-sep {
    height: 1px;
    margin: 5px 6px;
    background: var(--color-edge);
  }

  /* Only the app's Motion switch. This also stopped for Windows' "animation
     effects" being off, so on such a PC the Starting spinner stood still and
     the account looked stuck (see stores.ts). */
  :global(:root[data-motion="off"]) .acct-avatar::before,
  :global(:root[data-motion="off"]) .acct-spin,
  :global(:root[data-motion="off"]) .acct-banner-flash {
    animation: none;
  }
  :global(:root[data-motion="off"]) .acct-banner-flash { opacity: 0; }
  :global(:root[data-motion="off"]) .acct-persona,
  :global(:root[data-motion="off"]) .acct-persona-chev { transition: none; }
</style>
