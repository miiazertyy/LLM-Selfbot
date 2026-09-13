<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { toast } from "../lib/stores";
  import Card from "../lib/components/Card.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import Badge from "../lib/components/Badge.svelte";
  import Button from "../lib/components/Button.svelte";
  import Empty from "../lib/components/Empty.svelte";
  import Modal from "../lib/components/Modal.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import Profile from "../lib/components/Profile.svelte";

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

  onMount(() => {
    load();
    const t = setInterval(loadRuntime, 5000);
    return () => clearInterval(t);
  });

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
</script>

<ErrorNote text={loadError} onretry={() => { loadError = ""; loading = true; load(); }} />

<div class="space-y-4">
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
              <!-- Avatar and real name once the account has connected. -->
              {#if rt?.avatar}
                <img src={rt.avatar} alt="" class="h-9 w-9 shrink-0 rounded-full ring-1 ring-edge" />
              {:else}
                <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-accent">
                  <Icon name={s.platform === "snapchat" ? "snapchat" : "accounts"} size={17} />
                </span>
              {/if}

              <div class="min-w-0 flex-1">
                <div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                  <!-- min-w-0 on the name itself: `truncate` cannot shrink a
                       flex child below its content without it, so a long name
                       pushed the whole row wider than the card. -->
                  <span class="min-w-0 truncate text-sm font-semibold">
                    {rt?.display_name || rt?.username || title(s.platform) + " #" + s.index}
                  </span>
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
                {#if rt}
                  <Button kind="ghost" size="sm" loading={acting === rt.id + ":start"}
                          onclick={() => action(rt.id, "start", "Starting")}>Start</Button>
                  <Button kind="ghost" size="sm" loading={acting === rt.id + ":stop"}
                          onclick={() => action(rt.id, "stop", "Stopped")}>Stop</Button>
                  <Button kind="ghost" size="sm" loading={acting === rt.id + ":restart"}
                          onclick={() => action(rt.id, "restart", "Restarting")}>Restart</Button>
                  <Button kind="ghost" size="sm" loading={acting === rt.id + ":pause"}
                          onclick={() => action(rt.id, "pause", "Toggled pause")}>
                    {d?.paused ? "Resume" : "Pause"}
                  </Button>
                  {#if s.platform === "discord"}
                    <Button kind="ghost" size="sm" onclick={() => (profileFor = rt)}>Profile</Button>
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
