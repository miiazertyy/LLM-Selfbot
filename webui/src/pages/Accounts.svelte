<script lang="ts">
  /**
   * Accounts: each one as a card you can run it from.
   *
   * The page used to be a single list, one row per account, which only looked
   * like anything once you had a stack of accounts - with one or two it was a
   * strip at the top of an empty page. Each account now gets a card with its
   * picture, what it is doing in words, what it has done lately and one
   * obvious control, next to a tile for adding another. What the whole set is
   * doing sits in a strip above them. Everything the card knows about an
   * account's state is worked out in lib/accounts/condition.ts.
   */
  import { onMount } from "svelte";
  import { scale } from "svelte/transition";
  import { api } from "../lib/api";
  import { track } from "../lib/busy";
  import { visiblePoll } from "../lib/poll";
  import { chatCache, chatsFocus } from "../lib/chats";
  import { logsFocus, motionEnabled, settingsSection, toast } from "../lib/stores";
  import Button from "../lib/components/Button.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import Modal from "../lib/components/Modal.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import Profile from "../lib/components/Profile.svelte";
  import Avatar from "../lib/components/Avatar.svelte";
  import ProgressRing from "../lib/components/ProgressRing.svelte";
  import AccountCard from "../lib/accounts/AccountCard.svelte";
  import Segmented from "../lib/components/Segmented.svelte";
  import NotHere from "../lib/components/NotHere.svelte";
  import { missing, notHere } from "../lib/device";
  import Toggle from "../lib/components/Toggle.svelte";
  import { DISCORD_MARK, SNAPCHAT_GHOST } from "../lib/brands";
  import {
    condition, platformName, ready, type Runtime, type Slot,
  } from "../lib/accounts/condition";
  import {
    accountDetails, accountsRes, activityRes, loadMoods, refreshDetails, slotsRes,
  } from "../lib/accounts/state";
  import PersonaOrb from "../lib/personas/PersonaOrb.svelte";
  import { colorOf, withAccount } from "../lib/personas/logic";
  import { personasRes, reloadPersonas } from "../lib/personas/store";
  import { play } from "../lib/uisound";

  const runtime = $derived(($accountsRes.data.accounts ?? []) as Runtime[]);
  const slots = $derived(($slotsRes.data.slots ?? []) as Slot[]);
  const activity = $derived($activityRes.data);
  /** Only a genuinely cold start shows placeholders; a refresh never does. */
  const cold = $derived(!$slotsRes.fetched && !$slotsRes.error);

  let moods = $state<string[]>([]);
  let acting = $state("");

  // ── Personas: who each account speaks as ──────────────────────────────────
  const cast = $derived($personasRes.data);
  const personaIdOf = (s: Slot) => cast.accounts[s.id] || "default";
  /** Each persona's own moods, for the cards of the accounts speaking as it. */
  let moodsBy = $state<Record<string, string[]>>({});
  $effect(() => {
    for (const pid of new Set(["default", ...Object.values(cast.accounts)])) {
      if (moodsBy[pid]) continue;
      loadMoods(false, pid).then((m) => (moodsBy = { ...moodsBy, [pid]: m }));
    }
  });

  async function setPersona(s: Slot, pid: string) {
    const who = nameOf(s);
    const name = cast.personas.find((p) => p.id === pid)?.name ?? pid;
    // Seen at once: the chip changes while the server keeps it.
    personasRes.update((d) => withAccount(d, s.id, pid));
    try {
      const r: any = await api.assignPersona(pid, s.id);
      toast(r?.restarted?.length ? `${who} is ${name} now. Restarting it.` : `${who} is ${name} now.`, "ok");
      setTimeout(() => accountsRes.refresh({ force: true, quiet: true }).then(refreshAllDetails), 700);
    } catch (e: any) {
      toast(e?.message || "Could not do that", "err");
    }
    reloadPersonas();
  }

  function runtimeFor(s: Slot): Runtime | undefined {
    return runtime.find((r) => r.platform === s.platform && r.account === s.index);
  }

  const rows = $derived(slots.map((s) => {
    const rt = runtimeFor(s);
    const d = $accountDetails[s.id];
    const cache = $chatCache[s.id];
    return {
      slot: s,
      rt,
      d,
      cond: condition(s, rt, d),
      act: activity.accounts?.[s.id],
      waiting: cache?.fetched ? cache.users.length : null,
    };
  }));

  const summary = $derived.by(() => {
    // "Running" here means up: a worker that keeps crashing has a process
    // but is not doing anything, and counting it made a set with a broken
    // account read "3 of 3 running" in green.
    let running = 0, live = 0, startable = 0, attention = 0, today = 0, waiting = 0, waitingKnown = false;
    for (const r of rows) {
      if (r.rt?.state === "running" || r.rt?.state === "starting") running++;
      if (r.cond.running) live++;
      else if (r.cond.canStart) startable++;
      if (r.cond.alert) attention++;
      today += r.act?.today ?? 0;
      if (r.waiting != null) {
        waiting += r.waiting;
        waitingKnown = true;
      }
    }
    return { running, live, startable, attention, today, waiting, waitingKnown };
  });

  /**
   * What the set is doing, said the way you would say it. "1 of 1 running"
   * read as a fraction to work out; "All running" is the answer.
   */
  const headline = $derived.by(() => {
    const n = slots.length, up = summary.running;
    if (up === 0) return n === 1 ? "Not running" : "Nothing running";
    if (up === n) return n === 1 ? "Running" : n === 2 ? "Both running" : `All ${n} running`;
    return `${up} running`;
  });
  const subline = $derived.by(() => {
    const n = slots.length;
    const crashing = rows.filter((r) => r.rt?.state === "crashing").length;
    const down = n - summary.running - crashing;
    const parts: string[] = [];
    if (summary.running && (down || crashing)) {
      if (crashing) parts.push(`${crashing} crashing`);
      if (down) parts.push(`${down} stopped`);
    }
    else if (!summary.running) parts.push(n === 1 ? "Start it from its card" : `${n} accounts, all stopped`);
    else parts.push(n === 1 ? "1 account" : `${n} accounts`);
    if (summary.attention) parts.push(`${summary.attention} need${summary.attention === 1 ? "s" : ""} a look`);
    return parts.join(" · ");
  });

  onMount(() => {
    // Whatever the warm-up or the last visit left is already on screen; these
    // only replace it if it has gone stale.
    slotsRes.refresh({ maxAge: 30_000 });
    accountsRes.refresh({ maxAge: 3_000 }).then(refreshAllDetails);
    activityRes.refresh({ maxAge: 30_000 });
    personasRes.refresh({ maxAge: 15_000 });
    loadMoods().then((m) => (moods = m));

    const fast = visiblePoll(() => {
      accountsRes.refresh({ force: true, quiet: true }).then(refreshAllDetails);
    }, 5000);
    const slow = visiblePoll(() => activityRes.refresh({ force: true, quiet: true }), 60_000);
    return () => {
      fast();
      slow();
    };
  });

  /**
   * Live detail for every running account, together rather than one after
   * another: each is a round trip to a different process. Stopped accounts
   * are skipped, there is nobody on the other end.
   */
  async function refreshAllDetails() {
    const live = runtime.filter((r) => r.state === "running");
    await Promise.all(live.map((rt) => refreshDetails(rt.id)));
  }

  function nameOf(s: Slot) {
    const rt = runtimeFor(s);
    return rt?.display_name || rt?.username || s.username || `${platformName(s.platform)} #${s.index}`;
  }

  const DONE: Record<string, string> = {
    start: "Starting", stop: "Stopped", restart: "Restarting",
    reload: "Commands reloaded for", wipe: "Forgot the conversations of",
  };

  async function action(s: Slot, act: string) {
    const rt = runtimeFor(s);
    if (!rt) return;
    acting = `${rt.id}:${act}`;
    const who = nameOf(s);
    try {
      const res: any = await track("accounts", api.accountAction(rt.id, act), `${DONE[act] ?? act} ${who}`);
      if (res && res.ok === false) {
        toast(res.reason || `Could not ${act} ${who}`, "err");
      } else if (act === "pause") {
        // The worker answers with where the toggle landed.
        if (typeof res?.paused === "boolean") {
          accountDetails.update((all) => ({ ...all, [s.id]: { ...all[s.id], live: true, paused: res.paused } }));
          toast(res.paused ? `${who} stopped replying` : `${who} is replying again`, "ok");
        } else {
          toast(res?.reason || "The account did not answer", "err");
        }
      } else {
        toast(`${DONE[act] ?? act} ${who}`, "ok");
      }
    } catch (e: any) {
      toast(e.message, "err");
    } finally {
      acting = "";
    }
    setTimeout(() => accountsRes.refresh({ force: true, quiet: true }).then(refreshAllDetails), 700);
  }

  async function setMood(s: Slot, mood: string) {
    const rt = runtimeFor(s);
    if (!rt) return;
    try {
      const res: any = await api.accountMood(rt.id, mood);
      if (res && res.ok === false) throw new Error(res.reason || "The account did not answer");
      accountDetails.update((all) => ({ ...all, [s.id]: { ...all[s.id], live: true, mood } }));
      toast(`${nameOf(s)} is now ${mood}`, "ok");
      refreshDetails(rt.id);
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  // ── Everything at once ────────────────────────────────────────────────────
  let bulk = $state("");

  /**
   * One action for every account it applies to.
   *
   * Sequential on purpose: each start spawns a process and connects a session,
   * and several at the same instant is both heavy and exactly the pattern that
   * looks automated from the outside.
   */
  async function bulkAction(act: "start" | "stop" | "restart") {
    bulk = act;
    const targets = rows.filter((r) => r.rt && (act === "start" ? !r.cond.running && r.cond.canStart : r.cond.running));
    let failed = 0;
    const job = track("accounts", (async () => {
      for (const r of targets) {
        try {
          const res: any = await api.accountAction(r.rt!.id, act);
          if (res && res.ok === false) failed++;
        } catch {
          failed++;
        }
      }
    })(), `${DONE[act]} ${targets.length} accounts`);
    await job;
    bulk = "";
    const n = targets.length - failed;
    toast(failed
      ? `${n} of ${targets.length} done, ${failed} failed`
      : `${DONE[act]} ${n} account${n === 1 ? "" : "s"}`,
      failed ? "err" : "ok");
    accountsRes.refresh({ force: true, quiet: true }).then(refreshAllDetails);
  }

  // ── Going elsewhere, already pointed at this account ──────────────────────
  function openChats(s: Slot) {
    chatsFocus.set(s.id);
    window.location.hash = "/chats";
  }
  function openLogs(s: Slot) {
    logsFocus.set(s.id);
    window.location.hash = "/logs";
  }
  function openSettings(to: string) {
    settingsSection.set(to);
    window.location.hash = "/settings";
  }

  // ── Add / edit ────────────────────────────────────────────────────────────
  let editOpen = $state(false);
  let editPlatform = $state("discord");
  let editIndex = $state(0);            // 0 = adding a new one
  let fToken = $state("");
  let fProxy = $state("");
  let fUser = $state("");
  let fPass = $state("");
  let reveal = $state(false);
  let startNow = $state(true);
  /** The proxy field, folded away until wanted (or already set). */
  let showProxy = $state(false);
  let saving = $state(false);
  let addMenu = $state(false);
  let addMenuEl: HTMLElement | null = $state(null);
  /** Who a new account speaks as: given before it first starts. */
  let addPersona = $state("default");

  const adding = $derived(editIndex === 0);

  async function giveNewPersona(id: string) {
    if (addPersona === "default") return;
    try {
      await api.assignPersona(addPersona, id);
    } catch (e: any) {
      toast(e?.message || "Could not give it that persona", "err");
    }
    reloadPersonas();
  }

  /** Enter in a field saves, as it would in a form. Not an actual <form>:
   *  Button renders without a type, so every button in one - Cancel too -
   *  would submit it. */
  function enter(e: KeyboardEvent) {
    if (e.key === "Enter" && canSave && !saving) saveSlot();
  }
  const editing = $derived(adding ? undefined : slots.find((s) => s.platform === editPlatform && s.index === editIndex));
  // A platform this device cannot run (Snapchat on a phone) is not added here:
  // the dialog says why instead.
  const blocked = $derived(!!$notHere(editPlatform === "discord" ? "discord" : "snapchat"));
  const canSave = $derived(
    !blocked && (!adding || (editPlatform === "discord" ? !!fToken.trim() : !!(fUser.trim() && fPass))),
  );

  function openAdd(platform: string) {
    addMenu = false;
    editPlatform = platform;
    editIndex = 0;
    fToken = fProxy = fUser = fPass = "";
    reveal = false;
    startNow = true;
    showProxy = false;
    addPersona = "default";
    // Signing in opens a Chrome window, which a phone does not have.
    discordMode = missing("browser_login") ? "token" : "login";
    loginNote = "";
    loginState = "idle";
    stopLoginPoll();
    editOpen = true;
  }

  function openEdit(s: Slot) {
    editPlatform = s.platform;
    editIndex = s.index;
    // Never prefilled: the server does not hand credentials back, so these
    // stay blank and a blank field means "leave the stored one alone".
    fToken = fPass = "";
    fProxy = s.proxy ?? "";
    fUser = s.username ?? "";
    reveal = false;
    showProxy = !!fProxy;
    // Editing only ever replaces a stored token, never logs in again.
    discordMode = "token";
    loginNote = "";
    loginState = "idle";
    stopLoginPoll();
    editOpen = true;
  }

  // ── Add a Discord account by signing in, in a browser ───────────────────────
  // Default to signing in: it is what most people would rather do than hunt for
  // a token. The paste-a-token path is one click away and always works.
  let discordMode = $state<"login" | "token">("login");
  let loginBusy = $state(false);
  let loginNote = $state("");           // why it did not finish, if it did not
  // What the sign-in window is doing, polled while it is open.
  let loginState = $state<"idle" | "opening" | "waiting">("idle");
  let loginPoll: ReturnType<typeof setInterval> | null = null;

  function stopLoginPoll() {
    if (loginPoll) clearInterval(loginPoll);
    loginPoll = null;
  }

  /** Once a login (or token) has produced a slot, finish adding it the same way. */
  async function finishAdd(res: any) {
    slotsRes.set({ ...$slotsRes.data, slots: res.slots || [] });
    editOpen = false;
    await accountsRes.refresh({ force: true, quiet: true });
    const id = `discord_${res.index}`;
    await giveNewPersona(id);
    const slot = (res.slots || []).find((s: Slot) => s.id === id);
    if (startNow && slot && runtimeFor(slot)) {
      toast("Account added. Starting it now.", "ok");
      await action(slot, "start");
    } else {
      toast("Account added.", "ok");
    }
  }

  async function loginDiscord() {
    loginBusy = true;
    loginNote = "";
    loginState = "opening";
    try {
      const res: any = await api.discordBrowserLoginStart({ proxy: fProxy });
      if (res?.state === "failed") {
        loginNote = res.reason || "Could not open the browser.";
        loginBusy = false;
        loginState = "idle";
        return;
      }
      loginState = res?.state === "waiting" ? "waiting" : "opening";
      // The window is the interface now; this just watches for the outcome.
      stopLoginPoll();
      loginPoll = setInterval(pollBrowserLogin, 1500);
    } catch (e: any) {
      loginNote = e?.message || "Could not open the browser.";
      loginBusy = false;
      loginState = "idle";
    }
  }

  async function pollBrowserLogin() {
    try {
      const res: any = await api.discordBrowserLoginStatus(fProxy);
      if (res?.state === "done" && res?.slots) {
        stopLoginPoll();
        loginBusy = false;
        loginState = "idle";
        await finishAdd(res);
      } else if (res?.state === "failed") {
        stopLoginPoll();
        loginBusy = false;
        loginState = "idle";
        loginNote = res.reason || "The sign-in did not finish.";
      } else if (res?.state === "waiting" || res?.state === "opening") {
        loginState = res.state;
      }
    } catch {
      // A dropped poll is not a failure; the next one covers it.
    }
  }

  async function cancelBrowserLogin() {
    stopLoginPoll();
    loginBusy = false;
    loginState = "idle";
    try {
      await api.discordBrowserLoginCancel();
    } catch {
      // The window may already be gone, which is the same outcome.
    }
  }

  async function saveSlot() {
    saving = true;
    try {
      const body: any = editPlatform === "discord"
        ? { token: fToken, proxy: fProxy }
        : { username: fUser, password: fPass };
      const res: any = adding
        ? await api.addSlot(editPlatform, body)
        : await api.updateSlot(editPlatform, editIndex, body);
      slotsRes.set({ ...$slotsRes.data, slots: res.slots || [] });
      editOpen = false;
      await accountsRes.refresh({ force: true, quiet: true });
      if (adding) {
        const id = `${editPlatform}_${res.index}`;
        await giveNewPersona(id);
        const slot = (res.slots || []).find((s: Slot) => s.id === id);
        if (startNow && slot && runtimeFor(slot)) {
          toast("Account added. Starting it now.", "ok");
          await action(slot, "start");
        } else {
          toast("Account added.", "ok");
        }
      } else {
        const rt = editing ? runtimeFor(editing) : undefined;
        const changedLogin = editPlatform === "discord" ? !!fToken || fProxy !== (editing?.proxy ?? "") : !!fPass || fUser !== (editing?.username ?? "");
        toast(rt && rt.state === "running" && changedLogin
          ? "Saved. Restart it to sign in with the new login."
          : "Saved.", "ok");
      }
    } catch (e: any) {
      toast(e.message || "Could not save", "err");
    } finally {
      saving = false;
    }
  }

  $effect(() => {
    if (!addMenu) return;
    const off = (e: MouseEvent) => {
      if (addMenuEl && !addMenuEl.contains(e.target as Node)) addMenu = false;
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && (addMenu = false);
    const t = setTimeout(() => window.addEventListener("click", off), 0);
    window.addEventListener("keydown", esc);
    return () => {
      clearTimeout(t);
      window.removeEventListener("click", off);
      window.removeEventListener("keydown", esc);
    };
  });

  // ── Remove ────────────────────────────────────────────────────────────────
  let confirmDelete = $state<Slot | null>(null);
  let deleting = $state(false);
  const later = $derived(confirmDelete
    ? slots.filter((s) => s.platform === confirmDelete!.platform && s.index > confirmDelete!.index)
    : []);

  async function doDelete(s: Slot) {
    deleting = true;
    try {
      const res: any = await api.deleteSlot(s.platform, s.index);
      slotsRes.set({ ...$slotsRes.data, slots: res.slots || [] });
      confirmDelete = null;
      toast("Account removed.", "ok");
      accountsRes.refresh({ force: true, quiet: true });
      activityRes.refresh({ force: true, quiet: true });
    } catch (e: any) {
      toast(e.message || "Could not remove it", "err");
    } finally {
      deleting = false;
    }
  }

  let profileFor = $state<Runtime | null>(null);

  const dur = $derived($motionEnabled ? 1 : 0);
</script>

<ErrorNote text={!$slotsRes.fetched ? $slotsRes.error : ""}
           onretry={() => { slotsRes.refresh({ force: true }); accountsRes.refresh({ force: true }); }} />

<div class="space-y-5">
  {#if cold}
    <!-- First ever visit with nothing warmed yet: the shape of what is coming. -->
    <div class="h-[74px] animate-pulse rounded-2xl bg-white/[0.03]"></div>
    <div class="acct-grid">
      {#each [0, 1] as i (i)}
        <div class="h-[430px] animate-pulse rounded-[20px] bg-white/[0.03]"></div>
      {/each}
    </div>
  {:else if !slots.length}
    <!-- ── First run ──────────────────────────────────────────────────────── -->
    <section class="glass hero rise relative overflow-hidden rounded-[24px] px-6 py-10 text-center sm:px-10">
      <div class="hero-glow" aria-hidden="true"></div>
      <div class="relative">
        <div class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/15 text-accent">
          <Icon name="accounts" size={26} />
        </div>
        <h2 class="text-[22px] font-semibold tracking-tight text-ink">Connect your first account</h2>
        <p class="mx-auto mt-2 max-w-md text-[13px] leading-relaxed text-muted">
          The bot talks as you, from an account you already have. Pick where it
          should live. You can add more later and run them side by side.
        </p>
        <div class="mx-auto mt-7 grid max-w-2xl gap-3 text-left sm:grid-cols-2">
          <button class="platform-card" onclick={() => openAdd("discord")}>
            <span class="platform-icon"><Icon name="discord" size={24} /></span>
            <span class="flex items-center gap-2 text-[15px] font-semibold text-ink">Discord<NotHere feature="discord" variant="chip" /></span>
            <span class="mt-1 block text-[12px] leading-snug text-muted">
              Signs in with the account's token. Replies in DMs, and in the groups
              and servers you allow.
            </span>
            <span class="platform-go">Add a Discord account <Icon name="chevron" size={12} /></span>
          </button>
          <button class="platform-card" onclick={() => openAdd("snapchat")}>
            <span class="platform-icon"><Icon name="snapchat" size={24} /></span>
            <span class="flex items-center gap-2 text-[15px] font-semibold text-ink">Snapchat<NotHere feature="snapchat" variant="chip" /></span>
            <span class="mt-1 block text-[12px] leading-snug text-muted">
              Signs in with a username and password, in a browser that runs out
              of sight. Needs the Snapchat install from Settings.
            </span>
            <span class="platform-go">Add a Snapchat account <Icon name="chevron" size={12} /></span>
          </button>
        </div>
      </div>
    </section>
  {:else}
    <!-- What a phone asks of you: keep the app open, and one Discord account at a time. -->
    <NotHere feature="background" />
    <NotHere feature="discord_many" when={slots.filter((s) => s.platform === "discord").length > 1} />
    <!-- ── The whole set, at a glance ─────────────────────────────────────── -->
    <section class="fleet glass flex flex-wrap items-center gap-x-7 gap-y-4 rounded-2xl px-5 py-4"
             class:is-raised={addMenu}>
      <div class="flex items-center gap-3">
        <span class="fleet-ring" class:is-all={summary.running === slots.length && !summary.attention}>
          <ProgressRing done={summary.running} total={slots.length} size={40} />
        </span>
        <div>
          <div class="text-[17px] font-semibold leading-tight text-ink">{headline}</div>
          <div class="mt-0.5 text-[11.5px] {summary.attention ? 'text-warn' : 'text-faint'}">{subline}</div>
        </div>
      </div>
      <div class="fleet-fig">
        <div class="fleet-n">{summary.today}</div>
        <div class="fleet-l">replies today</div>
      </div>
      <div class="fleet-fig">
        <div class="fleet-n {summary.waiting ? 'text-warn' : ''}">{summary.waitingKnown ? summary.waiting : "–"}</div>
        <div class="fleet-l">waiting for a reply</div>
      </div>

      <div class="ml-auto flex flex-wrap items-center gap-2">
        {#if slots.length > 1}
          {#if summary.startable}
            <Button size="sm" kind="ghost" loading={bulk === "start"} onclick={() => bulkAction("start")}>
              {#if bulk !== "start"}<Icon name="play" size={11} />{/if}Start all {summary.startable}
            </Button>
          {/if}
          {#if summary.live}
            <Button size="sm" kind="ghost" loading={bulk === "restart"} onclick={() => bulkAction("restart")}>
              {#if bulk !== "restart"}<Icon name="refresh" size={12} />{/if}Restart all
            </Button>
            <Button size="sm" kind="ghost" loading={bulk === "stop"} onclick={() => bulkAction("stop")}>
              {#if bulk !== "stop"}<Icon name="stop" size={11} />{/if}Stop all
            </Button>
          {/if}
        {/if}
        <div class="relative" bind:this={addMenuEl}>
          <Button size="sm" onclick={() => (addMenu = !addMenu)}>
            <Icon name="plus" size={13} />Add account
          </Button>
          {#if addMenu}
            <div class="glass floating pop absolute right-0 top-full z-30 mt-2 w-52 rounded-xl p-1.5" role="menu">
              <button class="add-item" role="menuitem" onclick={() => openAdd("discord")}>
                <Icon name="discord" size={15} />Discord
                <span class="ml-auto"><NotHere feature="discord" variant="chip" /></span>
              </button>
              <button class="add-item" role="menuitem" onclick={() => openAdd("snapchat")}>
                <Icon name="snapchat" size={15} />Snapchat
                <span class="ml-auto"><NotHere feature="snapchat" variant="chip" /></span>
              </button>
            </div>
          {/if}
        </div>
      </div>
    </section>

    <!-- ── One card each, and a way to add the next ───────────────────────── -->
    <div class="acct-grid">
      {#each rows as r (r.slot.id)}
        <!-- No animate:flip: cards do not move, and flip measured every card
             on every five-second refresh, forcing a layout each time. -->
        <div in:scale={{ start: 0.96, duration: 260 * dur }}
             out:scale={{ start: 0.96, duration: 180 * dur }} class="flex">
          <div class="flex w-full flex-col [&>article]:flex-1">
            <AccountCard
              slot={r.slot}
              rt={r.rt}
              d={r.d}
              act={r.act}
              dates={activity.dates ?? []}
              waiting={r.waiting}
              moods={moodsBy[personaIdOf(r.slot)] ?? moods}
              {acting}
              onpersona={(pid) => setPersona(r.slot, pid)}
              onaction={(a) => action(r.slot, a)}
              onedit={() => openEdit(r.slot)}
              ondelete={() => (confirmDelete = r.slot)}
              onprofile={r.rt && r.slot.platform === "discord" ? () => (profileFor = r.rt ?? null) : undefined}
              onmood={(m) => setMood(r.slot, m)}
              onchats={() => openChats(r.slot)}
              onlogs={() => openLogs(r.slot)}
              onsettings={openSettings}
            />
          </div>
        </div>
      {/each}

      <div class="add-tile">
        <div class="add-orb"><Icon name="plus" size={22} /></div>
        <div class="text-[15px] font-semibold text-ink">Add {slots.length ? "another" : "an"} account</div>
        <p class="max-w-[19rem] text-[12px] leading-relaxed text-muted">
          Each one runs on its own, with its own login, mood and profile.
        </p>
        <div class="mt-1 grid w-full max-w-[19rem] grid-cols-2 gap-2">
          <button class="add-platform" onclick={() => openAdd("discord")}>
            <Icon name="discord" size={16} />Discord
          </button>
          <button class="add-platform" onclick={() => openAdd("snapchat")}>
            <Icon name="snapchat" size={16} />Snapchat
          </button>
        </div>
      </div>
    </div>
  {/if}
</div>

<!-- ── Add / edit ─────────────────────────────────────────────────────────── -->
<Modal
  open={editOpen}
  title={adding ? "Add an account" : `Edit ${editing ? nameOf(editing) : `${platformName(editPlatform)} #${editIndex}`}`}
  onclose={() => (editOpen = false)}
>
  <div class="aa" data-platform={editPlatform}>
    {#if adding}
      <!-- The platform as itself: its own mark on its own colour, which
           springs in and swaps with a turn when the platform does. -->
      <div class="aa-hero">
        <span class="aa-hero-glow" aria-hidden="true"></span>
        {#key editPlatform}
          <span class="aa-mark" aria-hidden="true">
            <svg viewBox="-1 -1 26 26"><path d={editPlatform === "discord" ? DISCORD_MARK : SNAPCHAT_GHOST} /></svg>
          </span>
          <span class="aa-hero-text">
            <span class="aa-hero-title">{platformName(editPlatform)}</span>
            <span class="aa-hero-sub">
              {editPlatform === "discord"
                ? "Sign in once. The app keeps it online and replying."
                : "It signs in through a real browser, the way you would."}
            </span>
          </span>
        {/key}
      </div>
      <!-- Which platform, switchable here rather than by closing and
           starting over from the other button. -->
      <Segmented label="Platform" bind:value={editPlatform} options={[
        { id: "discord", label: "Discord", icon: "discord", tone: "#5865f2" },
        { id: "snapchat", label: "Snapchat", icon: "snapchat", tone: "#fffc00" },
      ]} />
      <NotHere feature={editPlatform === "discord" ? "discord" : "snapchat"} />
    {:else if editing}
      {@const rt = runtimeFor(editing)}
      <div class="flex items-center gap-3 rounded-xl bg-white/[0.03] p-3">
        <Avatar src={rt?.avatar} name={nameOf(editing)} size={36} zoom={false} />
        <div class="min-w-0">
          <div class="truncate text-[13px] font-semibold text-ink">{nameOf(editing)}</div>
          <div class="text-[11px] text-faint">{platformName(editing.platform)} #{editing.index}</div>
        </div>
      </div>
    {/if}

    {#if editPlatform === "discord"}
      {#if adding && $notHere("browser_login")}
        <!-- No browser to sign in with here: a token is the way in. -->
        <NotHere feature="browser_login" variant="line" />
      {:else if adding}
        <!-- Sign in through a browser window and the app takes the token from
             the session; or paste one if you already have it. -->
        <Segmented label="How to add it" value={discordMode}
          onchange={(m) => { discordMode = m as "login" | "token"; loginNote = ""; if (m === "token") cancelBrowserLogin(); }}
          options={[{ id: "login", label: "Sign in", icon: "key" }, { id: "token", label: "Paste token", icon: "clipboard" }]} />
      {/if}

      {#if adding && discordMode === "login"}
        <!-- The three things that happen, lit as they do: the browser opening,
             you signing in, the account arriving. -->
        <div class="aa-panel">
          <ol class="aa-steps" class:is-idle={loginState === "idle"}
              style="--at: {loginState === 'waiting' ? 1 : loginState === 'opening' ? 0.5 : 0}">
            <li class="aa-step" class:is-now={loginState === "opening"} class:is-done={loginState === "waiting"}>
              <span class="aa-step-i"><Icon name="globe" size={16} /></span>
              <span class="aa-step-t">A browser opens</span>
            </li>
            <li class="aa-step" class:is-now={loginState === "waiting"}>
              <span class="aa-step-i"><Icon name="key" size={16} /></span>
              <span class="aa-step-t">You sign in</span>
            </li>
            <li class="aa-step">
              <span class="aa-step-i"><Icon name="check" size={16} /></span>
              <span class="aa-step-t">It is added</span>
            </li>
          </ol>
          {#if loginState !== "idle"}
            <p class="aa-status">
              <span class="aa-spin" aria-hidden="true"></span>
              {loginState === "opening" ? "Opening the browser…" : "Waiting for you to sign in. The window is open."}
            </p>
          {:else}
            <p class="aa-fine">
              <Icon name="eyeOff" size={12} />
              Your password never reaches the app. The token stays in config/.env on this computer.
            </p>
          {/if}
        </div>
        {#if loginNote}
          <div class="login-note">
            <span class="mt-0.5 shrink-0"><Icon name="alert" size={14} /></span>
            <span class="min-w-0">
              {loginNote}
              <button type="button" class="ml-1 font-semibold underline underline-offset-2"
                      onclick={() => { discordMode = "token"; loginNote = ""; cancelBrowserLogin(); }}>
                Paste a token instead
              </button>
            </span>
          </div>
        {/if}
      {:else}
      <div class="aa-field">
        <label for="tok" class="mb-1 block text-xs font-medium text-muted">
          Token {#if !adding}<span class="text-faint">, leave blank to keep the current one</span>{/if}
        </label>
        <div class="relative">
          <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
            <Icon name="key" size={14} />
          </span>
          <input
            id="tok"
            type={reveal ? "text" : "password"}
            bind:value={fToken} onkeydown={enter}
            autocomplete="off"
            spellcheck="false"
            placeholder={adding ? "The account's token" : "••••••••  (unchanged)"}
            class="field w-full pl-8 pr-9 font-mono"
          />
          <button type="button" class="reveal" onclick={() => (reveal = !reveal)}
                  aria-label={reveal ? "Hide it" : "Show it"} title={reveal ? "Hide it" : "Show it"}>
            <Icon name={reveal ? "eyeOff" : "eye"} size={14} />
          </button>
        </div>
        <p class="mt-1 text-[11px] text-faint">
          Kept in config/.env on this machine and never sent back to the page,
          so it can be replaced but not read.
        </p>
      </div>
      {/if}
      <!-- The proxy folds away: most accounts do without one, and it made the
           dialog look like a form to fill in before anything else. -->
      <div>
        <button type="button" class="aa-more" aria-expanded={showProxy} onclick={() => (showProxy = !showProxy)}>
          <Icon name="chevron" size={11} />Proxy <span class="text-faint">optional</span>
          {#if fProxy.trim() && !showProxy}<span class="aa-set">set</span>{/if}
        </button>
        {#if showProxy}
          <div class="aa-reveal">
            <input id="prx" type="text" bind:value={fProxy} onkeydown={enter} spellcheck="false" aria-label="Proxy"
                   placeholder="http://user:pass@host:port" class="field font-mono" />
            <p class="mt-1 text-[11px] text-faint">
              Left empty, it connects from this computer's own address. With several
              accounts, one proxy each keeps them from sharing it.
            </p>
          </div>
        {/if}
      </div>
    {:else}
      <div class="aa-field">
        <label for="usr" class="mb-1 block text-xs font-medium text-muted">Username</label>
        <div class="relative">
          <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
            <Icon name="accounts" size={14} />
          </span>
          <input id="usr" type="text" bind:value={fUser} onkeydown={enter} spellcheck="false" autocomplete="off"
                 placeholder="Snapchat username" class="field w-full pl-8" />
        </div>
      </div>
      <div class="aa-field">
        <label for="pwd" class="mb-1 block text-xs font-medium text-muted">
          Password {#if !adding}<span class="text-faint">, leave blank to keep the current one</span>{/if}
        </label>
        <div class="relative">
          <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
            <Icon name="key" size={14} />
          </span>
          <input id="pwd" type={reveal ? "text" : "password"} bind:value={fPass} onkeydown={enter} autocomplete="off"
                 placeholder={adding ? "Password" : "••••••••  (unchanged)"}
                 class="field w-full pl-8 pr-9" />
          <button type="button" class="reveal" onclick={() => (reveal = !reveal)}
                  aria-label={reveal ? "Hide it" : "Show it"} title={reveal ? "Hide it" : "Show it"}>
            <Icon name={reveal ? "eyeOff" : "eye"} size={14} />
          </button>
        </div>
        <p class="mt-1 text-[11px] text-faint">
          If Snapchat asks to confirm it is you, it waits for you to approve the
          login rather than giving up.
        </p>
      </div>
    {/if}

    {#if adding && cast.personas.length > 1}
      <div class="aa-persona">
        <span class="aa-persona-label">Profile</span>
        <div class="aa-persona-list" role="radiogroup" aria-label="Profile">
          {#each cast.personas as p (p.id)}
            <button type="button" role="radio" aria-checked={addPersona === p.id} class="aa-persona-opt"
                    class:is-on={addPersona === p.id} style="--pc: {colorOf(p)}"
                    onclick={() => { if (addPersona !== p.id) play("select"); addPersona = p.id; }}>
              <PersonaOrb {p} size={20} ring={false} />
              <span>{p.name}</span>
            </button>
          {/each}
        </div>
      </div>
    {/if}

    {#if adding}
      <label class="aa-start">
        <Toggle size="sm" bind:checked={startNow} name="Start it as soon as it is added" />
        <span>Start it as soon as it is added</span>
      </label>
    {/if}

    <div class="aa-foot">
      <Button kind="ghost" onclick={() => (editOpen = false)}>Cancel</Button>
      {#if adding && editPlatform === "discord" && discordMode === "login"}
        {#if loginBusy}
          <Button kind="ghost" onclick={cancelBrowserLogin}>Stop waiting</Button>
        {:else}
          <Button onclick={loginDiscord}><Icon name="external" size={13} />Open browser and sign in</Button>
        {/if}
      {:else}
        <Button onclick={saveSlot} loading={saving} disabled={!canSave}>
          {#if !saving}<Icon name={adding ? "plus" : "check"} size={13} />{/if}{adding ? "Add account" : "Save"}
        </Button>
      {/if}
    </div>
  </div>
</Modal>

<!-- ── Remove ─────────────────────────────────────────────────────────────── -->
<Modal open={!!confirmDelete} title="Remove this account?" onclose={() => (confirmDelete = null)}>
  {#if confirmDelete}
    {@const rt = runtimeFor(confirmDelete)}
    <div class="flex items-center gap-3 rounded-xl bg-white/[0.03] p-3">
      <Avatar src={rt?.avatar} name={nameOf(confirmDelete)} size={40} zoom={false} />
      <div class="min-w-0">
        <div class="truncate text-[13.5px] font-semibold text-ink">{nameOf(confirmDelete)}</div>
        <div class="text-[11px] text-faint">{platformName(confirmDelete.platform)} #{confirmDelete.index}</div>
      </div>
    </div>
    <ul class="mt-4 space-y-1.5 text-[12.5px] text-muted">
      <li>Its saved login is deleted from this computer.</li>
      {#if rt && rt.state !== "stopped"}<li>It is running, and will be stopped first.</li>{/if}
      {#if later.length}
        <li>
          {later.map((s) => `${platformName(s.platform)} #${s.index}`).join(", ")}
          move{later.length === 1 ? "s" : ""} up a number to close the gap.
        </li>
      {/if}
      <li>Its reply history and what the bot remembers about people are kept.</li>
    </ul>
    <div class="mt-6 flex justify-end gap-2">
      <Button kind="ghost" onclick={() => (confirmDelete = null)}>Keep it</Button>
      <Button kind="danger" onclick={() => doDelete(confirmDelete!)} loading={deleting}>Remove</Button>
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

<style>
  /* Wide enough that a card never has to squeeze its figures, and the add
     tile always takes a cell, so one account is a card and an invitation
     rather than a card and a void. */
  .acct-grid {
    display: grid;
    gap: 16px;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 380px), 1fr));
    align-items: stretch;
  }

  /* With the glass look every card is its own layer, so the Add account menu
     could not rise above the card after it: it opened underneath the first
     account. The strip is lifted above its neighbours while the menu is open. */
  .fleet {
    position: relative;
  }
  .fleet.is-raised {
    z-index: 25;
  }

  .fleet-fig {
    padding-left: 22px;
    border-left: 1px solid color-mix(in srgb, var(--color-edge) 80%, transparent);
  }
  .fleet-n {
    font-size: 19px;
    font-weight: 600;
    line-height: 1.2;
    color: var(--color-ink);
    font-variant-numeric: tabular-nums;
  }
  .fleet-l {
    font-size: 11.5px;
    color: var(--color-faint);
  }
  .fleet-ring {
    display: inline-flex;
    color: var(--color-accent);
  }
  .fleet-ring.is-all {
    color: var(--color-good);
  }

  .add-item {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    border-radius: 9px;
    font-size: 13px;
    color: var(--color-ink);
    transition: background-color 0.12s ease;
  }
  .add-item:hover { background: rgb(255 255 255 / 0.07); }

  .add-tile {
    display: flex;
    min-height: 280px;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 28px 24px;
    text-align: center;
    border-radius: 20px;
    border: 1.5px dashed color-mix(in srgb, var(--color-edge) 100%, transparent);
    background: rgb(255 255 255 / 0.012);
    transition: border-color 0.25s ease, background-color 0.25s ease;
  }
  .add-tile:hover {
    border-color: color-mix(in srgb, var(--color-accent) 45%, var(--color-edge));
    background: color-mix(in srgb, var(--color-accent) 4%, transparent);
  }
  .add-orb {
    display: flex;
    width: 48px;
    height: 48px;
    align-items: center;
    justify-content: center;
    margin-bottom: 4px;
    border-radius: 16px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 13%, transparent);
    transition: transform 0.45s var(--spring);
  }
  .add-tile:hover .add-orb { transform: rotate(90deg) scale(1.06); }
  .add-platform {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    padding: 8px 10px;
    border-radius: 11px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    transition: background-color 0.15s ease, box-shadow 0.15s ease, transform 0.2s var(--spring);
  }
  .add-platform:hover {
    background: color-mix(in srgb, var(--color-accent) 12%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 40%, transparent);
  }
  .add-platform:active { transform: scale(0.96); }

  .hero-glow {
    position: absolute;
    inset: 0;
    background:
      radial-gradient(60% 80% at 20% 0%, color-mix(in srgb, var(--color-accent) 22%, transparent), transparent 70%),
      radial-gradient(50% 70% at 90% 10%, color-mix(in srgb, var(--color-accent-2, var(--color-accent)) 14%, transparent), transparent 70%);
    pointer-events: none;
  }
  /* A button centres its content both ways by default, which set the two
     cards' text centred under left-aligned icons, at different heights. */
  .platform-card {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    text-align: left;
    padding: 18px;
    border-radius: 16px;
    background: rgb(255 255 255 / 0.035);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    transition: background-color 0.2s ease, box-shadow 0.2s ease, transform 0.35s var(--spring);
  }
  .platform-card:hover {
    transform: translateY(-2px);
    background: color-mix(in srgb, var(--color-accent) 8%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 45%, transparent);
  }
  .platform-card:active { transform: scale(0.98); }
  .platform-icon {
    display: flex;
    width: 42px;
    height: 42px;
    align-items: center;
    justify-content: center;
    margin-bottom: 12px;
    border-radius: 13px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 13%, transparent);
  }
  .platform-go {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-top: auto;
    padding-top: 14px;
    font-size: 12px;
    font-weight: 600;
    color: var(--color-accent);
  }


  /* ── Add an account ───────────────────────────────────────────────────
     Everything settles in one after another when the dialog opens, and a
     part that appears later (the token field, the proxy) rises into place. */
  .aa { display: flex; flex-direction: column; gap: 14px; }
  .aa > :global(*) { animation: aa-in 0.45s var(--swift) both; }
  .aa > :global(*:nth-child(2)) { animation-delay: 50ms; }
  .aa > :global(*:nth-child(3)) { animation-delay: 100ms; }
  .aa > :global(*:nth-child(4)) { animation-delay: 150ms; }
  .aa > :global(*:nth-child(5)) { animation-delay: 200ms; }
  .aa > :global(*:nth-child(n + 6)) { animation-delay: 250ms; }
  @keyframes aa-in { from { opacity: 0; transform: translateY(8px); } }

  .aa-hero {
    --brand: #5865f2;
    --wash: 26%;
    position: relative;
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 16px;
    overflow: hidden;
    border-radius: 16px;
    background: linear-gradient(135deg, color-mix(in srgb, var(--brand) var(--wash), transparent),
                                        color-mix(in srgb, var(--brand) 4%, transparent) 72%);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--brand) 28%, transparent);
  }
  /* Snapchat's yellow at the same strength as Discord's blue would glare. */
  .aa[data-platform="snapchat"] .aa-hero { --brand: #fffc00; --wash: 14%; }
  .aa-hero-glow {
    position: absolute;
    top: -90px;
    left: -50px;
    width: 200px;
    height: 200px;
    border-radius: 999px;
    background: radial-gradient(circle, color-mix(in srgb, var(--brand) 45%, transparent), transparent 70%);
    opacity: 0.7;
    pointer-events: none;
    animation: aa-drift 8s ease-in-out infinite alternate;
  }
  @keyframes aa-drift { to { transform: translate(60px, 40px) scale(1.2); } }
  .aa-mark {
    position: relative;
    display: grid;
    width: 50px;
    height: 50px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 15px;
    background: var(--brand);
    box-shadow: 0 12px 28px -10px color-mix(in srgb, var(--brand) 85%, transparent), inset 0 1px 0 rgb(255 255 255 / 0.3);
    animation: aa-mark-in 0.7s var(--jelly) both, aa-float 4.5s ease-in-out 0.7s infinite;
  }
  .aa-mark svg { width: 30px; height: 30px; overflow: visible; }
  .aa-mark path { fill: #fff; }
  .aa[data-platform="snapchat"] .aa-mark path { stroke: #000; stroke-width: 1.4; stroke-linejoin: round; }
  @keyframes aa-mark-in { from { opacity: 0; transform: scale(0.4) rotate(-24deg); } }
  @keyframes aa-float { 50% { transform: translateY(-3px) rotate(-3deg); } }
  .aa-hero-text {
    position: relative;
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 2px;
    animation: aa-in 0.5s var(--swift) 0.1s both;
  }
  .aa-hero-title { font-size: 16px; font-weight: 700; letter-spacing: -0.01em; color: var(--color-ink); }
  .aa-hero-sub { font-size: 12px; line-height: 1.4; color: var(--color-muted); }

  .aa-panel {
    padding: 16px 14px 12px;
    border-radius: 14px;
    background: rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
  }
  .aa-steps {
    position: relative;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    margin: 0 0 12px;
    padding: 0;
    list-style: none;
  }
  /* The line the steps sit on, and how far along it things have got. */
  .aa-steps::before,
  .aa-steps::after {
    content: "";
    position: absolute;
    top: 18px;
    left: 16.7%;
    right: 16.7%;
    height: 2px;
    border-radius: 2px;
    background: rgb(255 255 255 / 0.08);
  }
  .aa-steps::after {
    background: linear-gradient(90deg, var(--color-accent-2), var(--color-accent));
    transform: scaleX(var(--at));
    transform-origin: left center;
    transition: transform 0.7s var(--jelly);
  }
  .aa-step {
    position: relative;
    z-index: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 7px;
    text-align: center;
  }
  .aa-step-i {
    display: grid;
    width: 38px;
    height: 38px;
    place-items: center;
    border-radius: 12px;
    color: var(--color-muted);
    background: var(--color-card);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    transition: color 0.3s ease, background-color 0.3s ease, box-shadow 0.3s ease, transform 0.45s var(--jelly);
  }
  .aa-step-t { font-size: 11.5px; color: var(--color-muted); transition: color 0.3s ease; }
  .aa-step.is-now .aa-step-i {
    color: var(--color-accent);
    transform: scale(1.08);
    box-shadow: inset 0 0 0 1.5px var(--color-accent), 0 0 0 5px color-mix(in srgb, var(--color-accent) 16%, transparent);
    animation: aa-pulse 1.5s ease-in-out infinite;
  }
  .aa-step.is-done .aa-step-i {
    color: rgb(22 16 28);
    background: var(--color-accent);
    box-shadow: 0 6px 16px -6px var(--color-accent);
  }
  .aa-step.is-now .aa-step-t,
  .aa-step.is-done .aa-step-t { color: var(--color-ink); }
  @keyframes aa-pulse {
    50% { box-shadow: inset 0 0 0 1.5px var(--color-accent), 0 0 0 9px color-mix(in srgb, var(--color-accent) 5%, transparent); }
  }
  /* Before it starts, the first step nods, to say where it begins. */
  .aa-steps.is-idle .aa-step:first-child .aa-step-i { animation: aa-nod 2.6s ease-in-out 1s infinite; }
  @keyframes aa-nod { 0%, 70%, 100% { transform: none; } 80% { transform: translateY(-3px); } 90% { transform: translateY(1px); } }
  .aa-status {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    font-size: 12px;
    color: var(--color-accent);
    animation: aa-in 0.35s var(--swift) both;
  }
  .aa-spin {
    width: 12px;
    height: 12px;
    border-radius: 999px;
    border: 2px solid color-mix(in srgb, var(--color-accent) 25%, transparent);
    border-top-color: var(--color-accent);
    animation: aa-turn 0.8s linear infinite;
  }
  @keyframes aa-turn { to { transform: rotate(360deg); } }
  .aa-fine {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    font-size: 11px;
    color: var(--color-faint);
  }

  .aa-more {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 2px 0;
    font-size: 12.5px;
    font-weight: 500;
    color: var(--color-muted);
  }
  .aa-more:hover { color: var(--color-ink); }
  .aa-more :global(svg) { transition: transform 0.35s var(--jelly); }
  .aa-more[aria-expanded="true"] :global(svg) { transform: rotate(90deg); }
  .aa-set {
    padding: 0 7px;
    border-radius: 999px;
    font-size: 10.5px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .aa-reveal { margin-top: 8px; animation: aa-in 0.35s var(--swift) both; }
  .aa-start {
    display: flex;
    align-items: center;
    gap: 11px;
    padding: 10px 12px;
    border-radius: 12px;
    font-size: 12.5px;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.03);
    cursor: pointer;
  }
  .aa-foot { display: flex; justify-content: flex-end; gap: 8px; padding-top: 2px; }

  /* Who the new account speaks as, when there is more than one to choose. */
  .aa-persona { display: flex; flex-direction: column; gap: 7px; }
  .aa-persona-label { font-size: 12px; font-weight: 500; color: var(--color-muted); }
  .aa-persona-list { display: flex; flex-wrap: wrap; gap: 6px; }
  .aa-persona-opt {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 3px 11px 3px 3px;
    border-radius: 999px;
    font-size: 12.5px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06);
    transition: color 0.15s ease, background-color 0.2s ease, box-shadow 0.2s ease, transform 0.35s var(--jelly);
  }
  .aa-persona-opt:hover { color: var(--color-ink); }
  .aa-persona-opt:active { transform: scale(0.96); }
  .aa-persona-opt.is-on {
    color: var(--color-ink);
    background: color-mix(in srgb, var(--pc) 16%, transparent);
    box-shadow: inset 0 0 0 1px var(--pc), 0 0 14px -6px var(--pc);
  }
  :global(:root[data-motion="off"]) .aa-persona-opt { transition: none; }

  :global(:root[data-motion="off"]) .aa > :global(*),
  :global(:root[data-motion="off"]) .aa-hero-glow,
  :global(:root[data-motion="off"]) .aa-mark,
  :global(:root[data-motion="off"]) .aa-hero-text,
  :global(:root[data-motion="off"]) .aa-step-i,
  :global(:root[data-motion="off"]) .aa-status,
  :global(:root[data-motion="off"]) .aa-reveal,
  :global(:root[data-motion="off"]) .aa-steps::after { animation: none !important; transition: none; }

  /* Why a login did not go through, with the way round it right there. */
  .login-note {
    display: flex;
    gap: 8px;
    padding: 9px 11px;
    border-radius: 11px;
    font-size: 12px;
    line-height: 1.45;
    color: var(--color-warn);
    background: color-mix(in srgb, var(--color-warn) 9%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-warn) 22%, transparent);
  }

  .reveal {
    position: absolute;
    right: 6px;
    top: 50%;
    display: flex;
    width: 26px;
    height: 26px;
    align-items: center;
    justify-content: center;
    border-radius: 7px;
    color: var(--color-faint);
    transform: translateY(-50%);
  }
  .reveal:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.06); }
</style>
