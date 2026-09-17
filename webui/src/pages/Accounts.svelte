<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { visiblePoll } from "../lib/poll";
  import { toast } from "../lib/stores";
  import Card from "../lib/components/Card.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import Badge from "../lib/components/Badge.svelte";
  import Button from "../lib/components/Button.svelte";
  import Empty from "../lib/components/Empty.svelte";
  import Modal from "../lib/components/Modal.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import Profile from "../lib/components/Profile.svelte";
  import StatusDot from "../lib/components/StatusDot.svelte";

  type Runtime = {
    id: string;
    platform: string;
    account: number | null;
    target: string;
    state: string;
    pid: number | null;
    restarts: number;
    uptime: number;
    // Recorded by the runner when it connects, so it survives a stop.
    username?: string;
    display_name?: string;
    avatar?: string;
  };
  type Details = {
    live: boolean;
    reason?: string;
    paused?: boolean;
    mood?: string;
    active_channels?: number;
    ignored_users?: number;
    /** The presence the account is actually showing on Discord. */
    presence?: string;
    /** True while the night schedule is holding it on its night status. */
    night?: boolean;
    latency_ms?: number | null;
    guilds?: number;
    friends?: number;
  };
  type Slot = {
    id: string;
    platform: string;
    index: number;
    token_set?: boolean;
    proxy?: string;
    username?: string;
    password_set?: boolean;
  };

  let runtime = $state<Runtime[]>([]);
  let slots = $state<Slot[]>([]);
  let loading = $state(true);
  let loadError = $state("");

  // ── Editor state ──────────────────────────────────────────────────────────
  let editOpen = $state(false);
  let editPlatform = $state("discord");
  let editIndex = $state(0);          // 0 = adding a new account
  let fToken = $state("");
  let fProxy = $state("");
  let fUser = $state("");
  let fPass = $state("");
  let busy = $state(false);

  let confirmDelete = $state<Slot | null>(null);
  let profileFor = $state<Runtime | null>(null);

  // Live detail is fetched only for the row you open, not on every poll.
  let expanded = $state<string | null>(null);
  let details = $state<Record<string, Details>>({});
  let detailBusy = $state<string | null>(null);
  let acting = $state<string>("");

  const MOODS = ["chill", "playful", "busy", "tired", "annoyed", "flirty"];

  async function toggleExpand(s: Slot) {
    const key = s.id;
    if (expanded === key) {
      expanded = null;
      return;
    }
    expanded = key;
    const rt = runtimeFor(s);
    if (!rt) return;
    detailBusy = key;
    try {
      details[key] = await api.accountDetails(rt.id);
    } catch (e: any) {
      details[key] = { live: false, reason: e.message || "could not reach the account" };
    } finally {
      detailBusy = null;
    }
  }

  async function refreshDetails(s: Slot) {
    const rt = runtimeFor(s);
    if (!rt) return;
    try {
      details[s.id] = await api.accountDetails(rt.id);
    } catch {
      /* leave whatever was there */
    }
  }

  async function setMood(s: Slot, mood: string) {
    const rt = runtimeFor(s);
    if (!rt) return;
    try {
      await api.accountMood(rt.id, mood);
      toast(`Mood set to ${mood}`, "ok");
      refreshDetails(s);
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  function uptime(secs?: number) {
    if (!secs) return "";
    const d = Math.floor(secs / 86400);
    const h = Math.floor((secs % 86400) / 3600);
    const m = Math.floor((secs % 3600) / 60);
    if (d) return `${d}d ${h}h`;
    return h ? `${h}h ${m}m` : `${m}m`;
  }

  const adding = $derived(editIndex === 0);

  /** Whether this slot has enough set on it to be worth starting. */
  function ready(s: Slot): boolean {
    return s.platform === "discord"
      ? !!s.token_set
      : !!(s.username && s.password_set);
  }

  onMount(() => {
    load();
    return visiblePoll(() => {
      loadRuntime();
      refreshAllDetails();
    }, 5000);
  });

  /**
   * Pull live detail for every running account.
   *
   * It used to be fetched only for the row you expanded, to keep the IPC
   * traffic down. The status dot beside each avatar needs it for all of them,
   * so this asks for them together rather than one after another - each is a
   * round trip to a different process, so they do not queue behind each other.
   * Stopped accounts are skipped: there is nothing on the other end.
   */
  async function refreshAllDetails() {
    const live = runtime.filter((r) => r.state === "running");
    await Promise.all(live.map(async (rt) => {
      const slot = slots.find((s) => runtimeFor(s)?.id === rt.id);
      if (!slot) return;
      try {
        details[slot.id] = await api.accountDetails(rt.id);
      } catch {
        /* keep whatever was there; a missed poll is not an error */
      }
    }));
  }

  /** What the dot beside the avatar should show. */
  function presenceOf(s: Slot): string {
    const rt = runtimeFor(s);
    if (!rt || rt.state !== "running") return "offline";
    const d = details[s.id];
    if (!d?.live) return "offline";
    return d.presence || "online";
  }

  function presenceLabel(s: Slot): string {
    const d = details[s.id];
    const p = presenceOf(s);
    const names: Record<string, string> = {
      online: "Online", idle: "Idle", dnd: "Do Not Disturb",
      invisible: "Invisible", offline: "Offline",
    };
    const base = names[p] || "Offline";
    return d?.night && p === "invisible" ? `${base}, night schedule` : base;
  }

  async function load() {
    try {
      const [r, s] = await Promise.all([api.accounts(), api.slots()]);
      runtime = r.accounts || [];
      slots = s.slots || [];
    } catch (e: any) {
      loadError = e?.message || "Could not load";
    } finally {
      loading = false;
    }
  }

  async function loadRuntime() {
    try {
      runtime = (await api.accounts()).accounts || [];
    } catch {
      /* the periodic refresh must not replace the page with an error */
    }
  }

  function runtimeFor(s: Slot): Runtime | undefined {
    return runtime.find((r) => r.platform === s.platform && r.account === s.index);
  }

  async function action(id: string, act: string, label = "") {
    acting = `${id}:${act}`;
    try {
      const res = await api.accountAction(id, act);
      if (res && res.ok === false) toast(res.reason || `${act} failed`, "err");
      else toast(label || `${act} sent`, "ok");
    } catch (e: any) {
      toast(e.message, "err");
    } finally {
      acting = "";
    }
    setTimeout(loadRuntime, 600);
    const slot = slots.find((x) => runtimeFor(x)?.id === id);
    if (slot && expanded === slot.id) refreshDetails(slot);
  }

  function openAdd(platform: string) {
    editPlatform = platform;
    editIndex = 0;
    fToken = fProxy = fUser = fPass = "";
    editOpen = true;
  }

  function openEdit(s: Slot) {
    editPlatform = s.platform;
    editIndex = s.index;
    // Never prefilled, the server does not return credentials, so these stay
    // blank and an empty field means "leave the stored one alone".
    fToken = fPass = "";
    fProxy = s.proxy ?? "";
    fUser = s.username ?? "";
    editOpen = true;
  }

  async function saveSlot() {
    busy = true;
    try {
      const body: any =
        editPlatform === "discord"
          ? { token: fToken, proxy: fProxy }
          : { username: fUser, password: fPass };
      const res = adding
        ? await api.addSlot(editPlatform, body)
        : await api.updateSlot(editPlatform, editIndex, body);
      slots = res.slots || [];
      editOpen = false;
      toast(adding ? "Account added." : "Account updated.", "ok");
      loadRuntime();
    } catch (e: any) {
      toast(e.message || "Could not save", "err");
    } finally {
      busy = false;
    }
  }

  async function doDelete(s: Slot) {
    busy = true;
    try {
      const res = await api.deleteSlot(s.platform, s.index);
      slots = res.slots || [];
      confirmDelete = null;
      toast("Account removed.", "ok");
      loadRuntime();
    } catch (e: any) {
      toast(e.message || "Could not delete", "err");
    } finally {
      busy = false;
    }
  }

  function tone(s: string) {
    return s === "running" ? "good" : s === "crashing" ? "bad" : s === "starting" ? "warn" : "muted";
  }

  const title = (p: string) => p[0].toUpperCase() + p.slice(1);

  const counts = $derived.by(() => {
    let running = 0, paused = 0, crashing = 0, unconfigured = 0, startable = 0;
    for (const s of slots) {
      const rt = runtimeFor(s);
      const live = rt?.state === "running" || rt?.state === "starting";
      if (live) running++;
      if (details[s.id]?.paused) paused++;
      if (rt?.state === "crashing") crashing++;
      if (!ready(s)) unconfigured++;
      else if (!live) startable++;
    }
    return { running, paused, crashing, unconfigured, startable };
  });

  let bulk = $state("");

  /**
   * Apply one action to every account it makes sense for.
   *
   * Sequential on purpose: each start spawns a process and connects a Discord
   * session, and firing several at the same instant is both heavy and exactly
   * the pattern that looks automated from the outside.
   */
  async function bulkAction(act: "start" | "stop" | "restart") {
    bulk = act;
    const targets = slots.filter((s) => {
      const rt = runtimeFor(s);
      if (!rt) return false;
      const live = rt.state === "running" || rt.state === "starting";
      return act === "start" ? !live && ready(s) : live;
    });
    let failed = 0;
    for (const s of targets) {
      const rt = runtimeFor(s);
      if (!rt) continue;
      try {
        await api.accountAction(rt.id, act);
      } catch {
        failed++;
      }
    }
    bulk = "";
    toast(failed
      ? `${act}: ${targets.length - failed} done, ${failed} failed`
      : `${act}: ${targets.length} account${targets.length === 1 ? "" : "s"}`,
      failed ? "err" : "ok");
    loadRuntime();
  }
</script>

<ErrorNote text={loadError} onretry={() => { loadError = ""; loading = true; load(); }} />

<div class="space-y-4">
  <!-- What the whole set is doing, before the per-account detail. Working that
       out meant counting the badges down the list. -->
  {#if !loading && slots.length}
    <div class="glass flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl px-4 py-3">
      <div class="flex items-baseline gap-1.5">
        <span class="text-[18px] font-semibold text-ink">{counts.running}</span>
        <span class="text-[12px] text-muted">of {slots.length} running</span>
      </div>
      {#if counts.paused}
        <span class="text-[12px] text-warn">{counts.paused} paused</span>
      {/if}
      {#if counts.crashing}
        <span class="text-[12px] text-bad">{counts.crashing} crashing</span>
      {/if}
      {#if counts.unconfigured}
        <span class="text-[12px] text-faint">{counts.unconfigured} need credentials</span>
      {/if}
      <div class="ml-auto flex flex-wrap gap-2">
        {#if counts.startable}
          <Button size="sm" kind="ghost" loading={bulk === "start"} onclick={() => bulkAction("start")}>
            Start all {counts.startable}
          </Button>
        {/if}
        {#if counts.running}
          <Button size="sm" kind="ghost" loading={bulk === "restart"} onclick={() => bulkAction("restart")}>
            Restart running
          </Button>
          <Button size="sm" kind="ghost" loading={bulk === "stop"} onclick={() => bulkAction("stop")}>
            Stop all
          </Button>
        {/if}
      </div>
    </div>
  {/if}

  <div class="flex flex-wrap gap-2">
    <Button size="sm" onclick={() => openAdd("discord")}>Add Discord account</Button>
    <Button kind="ghost" size="sm" onclick={() => openAdd("snapchat")}>Add Snapchat account</Button>
  </div>

  <Card pad={false}>
    {#if loading}
      <div class="h-40 animate-pulse"></div>
    {:else if slots.length === 0}
      <div class="p-5">
        <Empty text="No accounts yet. Add one above, its token is stored in config/.env on this machine." icon="accounts" />
      </div>
    {:else}
      <div class="divide-y divide-edge">
        {#each slots as s (s.id)}
          {@const rt = runtimeFor(s)}
          {@const d = details[s.id]}
          <div class="px-4 py-4 sm:px-5">
            <div class="flex flex-wrap items-center gap-x-4 gap-y-3">
              <!-- Avatar with the presence badge sitting on its corner, the
                   way Discord shows your own account bottom left. The notch
                   behind the dot is what stops it reading as a sticker: the
                   avatar is actually cut away under it. -->
              <span class="relative block h-10 w-10 shrink-0" title={presenceLabel(s)}>
                {#if rt?.avatar}
                  <img src={rt.avatar} alt="" class="h-10 w-10 rounded-full ring-1 ring-edge" />
                {:else}
                  <span class="flex h-10 w-10 items-center justify-center rounded-full bg-white/[0.06] text-accent">
                    <Icon name={s.platform === "snapchat" ? "snapchat" : "accounts"} size={18} />
                  </span>
                {/if}
                {#if s.platform === "discord"}
                  <span class="absolute -bottom-0.5 -right-0.5 flex h-[15px] w-[15px] items-center
                               justify-center rounded-full bg-card">
                    <StatusDot status={presenceOf(s)} size={11} title={presenceLabel(s)} />
                  </span>
                {/if}
              </span>

              <div class="min-w-0 flex-1">
                <div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                  <!-- min-w-0 on the name itself: `truncate` cannot shrink a
                       flex child below its content without it, so a long name
                       pushed the whole row wider than the card. -->
                  <!-- The name is the way into the profile, the same as every
                       other name in the panel. There was a Profile button for
                       this and nothing else was clickable, which is backwards:
                       the name is the thing you point at. -->
                  {#if s.platform === "discord" && rt}
                    <button
                      class="user-chip min-w-0 truncate text-left text-sm font-semibold"
                      onclick={() => (profileFor = rt)}
                      title="See this account's profile"
                    >
                      {rt.display_name || rt.username || title(s.platform) + " #" + s.index}
                    </button>
                  {:else}
                    <span class="min-w-0 truncate text-sm font-semibold">
                      {rt?.display_name || rt?.username || title(s.platform) + " #" + s.index}
                    </span>
                  {/if}
                  <span class="truncate text-[11px] text-faint">{title(s.platform)} #{s.index}</span>
                  {#if d?.paused}<Badge tone="warn">paused</Badge>{/if}
                </div>
                <div class="mt-0.5 flex flex-wrap gap-x-2 truncate text-xs text-muted">
                  {#if rt?.username}<span>@{rt.username}</span>{/if}
                  {#if s.platform === "discord"}
                    <span>{s.token_set ? "token set" : "no token"}</span>
                    {#if s.proxy}<span class="truncate">proxy {s.proxy}</span>{:else}<span>local IP</span>{/if}
                  {:else}
                    <span>{s.username || "no username"}</span>
                    <span>{s.password_set ? "password set" : "no password"}</span>
                  {/if}
                  {#if rt?.pid}<span>pid {rt.pid}</span>{/if}
                  {#if rt?.uptime}<span>up {uptime(rt.uptime)}</span>{/if}
                  {#if rt?.restarts}<span class="text-warn/80">{rt.restarts} restarts</span>{/if}
                </div>
              </div>

              <Badge tone={tone(rt?.state ?? "stopped")}>{rt?.state ?? "stopped"}</Badge>

              <div class="flex w-full flex-wrap items-center gap-2 xl:w-auto">
                <!-- One primary action, decided by what the account is doing.
                     Start and Stop used to sit side by side permanently, so
                     half the row was always a no-op and neither told you what
                     state you were in. -->
                {#if rt}
                  {@const running = rt.state === "running" || rt.state === "starting"}
                  {#if running}
                    <Button size="sm" kind="ghost" loading={acting === rt.id + ":stop"}
                            onclick={() => action(rt.id, "stop", "Stopped")}>Stop</Button>
                    <Button size="sm" kind="ghost" loading={acting === rt.id + ":restart"}
                            onclick={() => action(rt.id, "restart", "Restarting")}
                            title="Stop and start it again">Restart</Button>
                    <!-- Pause leaves it connected but silent, which is a
                         different thing from stopping it, so it says which. -->
                    <Button size="sm" kind="ghost" loading={acting === rt.id + ":pause"}
                            onclick={() => action(rt.id, "pause", "Toggled pause")}
                            title={d?.paused
                              ? "Start replying again"
                              : "Stay online but stop replying"}>
                      {d?.paused ? "Resume replies" : "Pause replies"}
                    </Button>
                  {:else}
                    <Button size="sm" loading={acting === rt.id + ":start"}
                            disabled={!ready(s)}
                            title={ready(s)
                              ? "Connect this account"
                              : "Add its credentials first"}
                            onclick={() => action(rt.id, "start", "Starting")}>Start</Button>
                  {/if}
                {/if}
                <Button kind="ghost" size="sm" onclick={() => openEdit(s)}>Edit</Button>
                <Button kind="ghost" size="sm" onclick={() => (confirmDelete = s)}>Delete</Button>
                <button
                  onclick={() => toggleExpand(s)}
                  aria-expanded={expanded === s.id}
                  aria-label="More about this account"
                  title="More"
                  class="jelly rounded-lg p-1.5 text-muted hover:bg-white/[0.07] hover:text-ink"
                >
                  <span class="inline-block transition-transform duration-200"
                        style="transform: rotate({expanded === s.id ? 90 : 0}deg)">
                    <Icon name="chevron" size={14} />
                  </span>
                </button>
              </div>
            </div>

            <!-- Live detail, fetched only for the row you open. Folding this
                 into /api/accounts would mean an IPC round trip per account on
                 every poll, for information nobody is usually looking at. -->
            {#if expanded === s.id}
              <div class="rise mt-3 rounded-xl border border-edge/70 bg-black/15 p-4">
                {#if detailBusy === s.id}
                  <div class="h-16 animate-pulse rounded-lg bg-white/[0.03]"></div>
                {:else if d?.live}
                  <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <div>
                      <div class="text-[10px] uppercase tracking-[0.12em] text-faint">Showing as</div>
                      <div class="mt-0.5 flex items-center gap-1.5 text-[13px] text-ink">
                        <StatusDot status={presenceOf(s)} size={11} />
                        {presenceLabel(s)}
                      </div>
                    </div>
                    {#if d.latency_ms != null}
                      <div>
                        <div class="text-[10px] uppercase tracking-[0.12em] text-faint">Gateway</div>
                        <!-- Discord's own thresholds for the ping readout. -->
                        <div class="mt-0.5 text-[13px] {d.latency_ms < 200 ? 'text-good' : d.latency_ms < 500 ? 'text-warn' : 'text-bad'}">
                          {d.latency_ms} ms
                        </div>
                      </div>
                    {/if}
                    {#if d.guilds != null}
                      <div>
                        <div class="text-[10px] uppercase tracking-[0.12em] text-faint">Servers</div>
                        <div class="mt-0.5 text-[13px] text-ink">{d.guilds}</div>
                      </div>
                    {/if}
                    {#if d.friends != null}
                      <div>
                        <div class="text-[10px] uppercase tracking-[0.12em] text-faint">Friends</div>
                        <div class="mt-0.5 text-[13px] text-ink">{d.friends}</div>
                      </div>
                    {/if}
                    <div>
                      <div class="text-[10px] uppercase tracking-[0.12em] text-faint">Mood</div>
                      <div class="mt-0.5 text-[13px] text-ink">{d.mood || "not set"}</div>
                    </div>
                    <div>
                      <div class="text-[10px] uppercase tracking-[0.12em] text-faint">Replying</div>
                      <div class="mt-0.5 text-[13px] {d.paused ? 'text-warn' : 'text-good'}">
                        {d.paused ? "paused" : "active"}
                      </div>
                    </div>
                    <div>
                      <div class="text-[10px] uppercase tracking-[0.12em] text-faint">Active channels</div>
                      <div class="mt-0.5 text-[13px] text-ink">{d.active_channels ?? 0}</div>
                    </div>
                    <div>
                      <div class="text-[10px] uppercase tracking-[0.12em] text-faint">Ignored people</div>
                      <div class="mt-0.5 text-[13px] text-ink">{d.ignored_users ?? 0}</div>
                    </div>
                  </div>

                  <div class="mt-4">
                    <div class="mb-1.5 text-[10px] uppercase tracking-[0.12em] text-faint">Set mood</div>
                    <div class="flex flex-wrap gap-1.5">
                      {#each MOODS as m}
                        <button
                          onclick={() => setMood(s, m)}
                          class="jelly rounded-full border px-2.5 py-1 text-[11px]
                            {d.mood === m
                              ? 'border-accent/50 bg-accent/15 text-ink'
                              : 'border-edge text-muted hover:bg-white/[0.05] hover:text-ink'}"
                        >{m}</button>
                      {/each}
                    </div>
                  </div>

                  <div class="mt-4 flex flex-wrap items-center gap-2 border-t border-edge/60 pt-3">
                    <Button kind="ghost" size="sm" loading={acting === (rt ? rt.id : "") + ":reload"}
                            onclick={() => rt && action(rt.id, "reload", "Commands reloaded")}>
                      Reload commands
                    </Button>
                    <Button kind="ghost" size="sm" loading={acting === (rt ? rt.id : "") + ":wipe"}
                            onclick={() => rt && action(rt.id, "wipe", "Conversation history cleared")}>
                      Wipe history
                    </Button>
                    <Button kind="ghost" size="sm" onclick={() => (window.location.hash = "/chats")}>
                      Open chats
                    </Button>
                    <Button kind="ghost" size="sm" onclick={() => (window.location.hash = "/logs")}>
                      View logs
                    </Button>
                    {#if rt}
                      <span class="ml-auto font-mono text-[11px] text-faint">target {rt.target}</span>
                    {/if}
                  </div>
                {:else}
                  <p class="text-[12px] text-faint">
                    {d?.reason || "Start the account to see its live status."}
                  </p>
                {/if}
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  </Card>
</div>

<!-- ── Add / edit ─────────────────────────────────────────────────────────── -->
<Modal
  open={editOpen}
  title={adding ? `Add ${title(editPlatform)} account` : `${title(editPlatform)} #${editIndex}`}
  onclose={() => (editOpen = false)}
>
  <div class="space-y-4">
    {#if editPlatform === "discord"}
      <div>
        <label for="tok" class="mb-1 block text-xs font-medium text-muted">
          Token {#if !adding}<span class="text-faint">, leave blank to keep the current one</span>{/if}
        </label>
        <input
          id="tok"
          type="password"
          bind:value={fToken}
          autocomplete="off"
          spellcheck="false"
          placeholder={adding ? "Paste the account token" : "••••••••  (unchanged)"}
          class="field font-mono"
        />
        <p class="mt-1 text-[11px] text-faint">
          Stored in config/.env on this machine. It is never sent back to the
          browser, so it can be replaced but not read.
        </p>
      </div>
      <div>
        <label for="prx" class="mb-1 block text-xs font-medium text-muted">Proxy (optional)</label>
        <input id="prx" type="text" bind:value={fProxy} spellcheck="false"
               placeholder="http://user:pass@host:port" class="field font-mono" />
      </div>
    {:else}
      <div>
        <label for="usr" class="mb-1 block text-xs font-medium text-muted">Username</label>
        <input id="usr" type="text" bind:value={fUser} spellcheck="false" autocomplete="off"
               class="field" />
      </div>
      <div>
        <label for="pwd" class="mb-1 block text-xs font-medium text-muted">
          Password {#if !adding}<span class="text-faint">, leave blank to keep the current one</span>{/if}
        </label>
        <input id="pwd" type="password" bind:value={fPass} autocomplete="off"
               placeholder={adding ? "" : "••••••••  (unchanged)"} class="field" />
      </div>
    {/if}
  </div>

  <div class="mt-6 flex justify-end gap-2">
    <Button kind="ghost" onclick={() => (editOpen = false)}>Cancel</Button>
    <Button onclick={saveSlot} loading={busy}>{adding ? "Add account" : "Save"}</Button>
  </div>
</Modal>

<!-- ── Delete ─────────────────────────────────────────────────────────────── -->
<Modal
  open={!!confirmDelete}
  title="Remove account"
  onclose={() => (confirmDelete = null)}
>
  {#if confirmDelete}
    <p class="text-sm text-muted">
      Remove <span class="font-semibold text-ink">{title(confirmDelete.platform)} #{confirmDelete.index}</span>
      and its stored credentials? Later accounts move up a number to close the gap.
    </p>
    <div class="mt-6 flex justify-end gap-2">
      <Button kind="ghost" onclick={() => (confirmDelete = null)}>Cancel</Button>
      <Button kind="danger" onclick={() => doDelete(confirmDelete!)} loading={busy}>Remove</Button>
    </div>
  {/if}
</Modal>

<!-- ── Discord profile ────────────────────────────────────────────────────── -->
<Modal
  open={!!profileFor}
  title={profileFor ? `Profile, Discord #${profileFor.account}` : ""}
  onclose={() => (profileFor = null)}
>
  {#if profileFor}
    <Profile target={profileFor.target} />
  {/if}
</Modal>
