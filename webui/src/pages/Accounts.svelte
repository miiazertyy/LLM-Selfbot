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
  import { fly, scale } from "svelte/transition";
  import { api } from "../lib/api";
  import { track } from "../lib/busy";
  import { visiblePoll } from "../lib/poll";
  import { chatCache, chatsFocus } from "../lib/chats";
  import { logsFocus, motionEnabled, settingsSection, toast } from "../lib/stores";
  import { openUrl } from "../lib/window";
  import Button from "../lib/components/Button.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import Modal from "../lib/components/Modal.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import Profile from "../lib/components/Profile.svelte";
  import Avatar from "../lib/components/Avatar.svelte";
  import ProgressRing from "../lib/components/ProgressRing.svelte";
  import AccountCard from "../lib/accounts/AccountCard.svelte";
  import LiveView from "../lib/accounts/LiveView.svelte";
  import WatchView from "../lib/accounts/WatchView.svelte";
  import McSkin from "../lib/accounts/McSkin.svelte";
  import Segmented from "../lib/components/Segmented.svelte";
  import NotHere from "../lib/components/NotHere.svelte";
  import { missing, notHere } from "../lib/device";
  import Toggle from "../lib/components/Toggle.svelte";
  import { DISCORD_MARK, SNAPCHAT_GHOST, TIKTOK_MARK, INSTAGRAM_MARK, X_MARK, REDDIT_SNOO, WHATSAPP_MARK,
         MINECRAFT_CUBE,
         IMESSAGE_BUBBLE,
           TELEGRAM_PLANE } from "../lib/brands";
  import {
    condition, platformName, ready, type Runtime, type Slot,
  } from "../lib/accounts/condition";
  import {
    accountDetails, accountsRes, activityRes, loadMoodLines, loadMoods, refreshDetails, slotsRes,
  } from "../lib/accounts/state";
  import { SOCIALS, platformOn, socialsOn } from "../lib/socials";
  import { PLATFORMS, platformName as fullPlatformName, type PlatformId } from "../lib/platforms";
  import PersonaOrb from "../lib/personas/PersonaOrb.svelte";
  import { colorOf, withAccount } from "../lib/personas/logic";
  import { personasRes, reloadPersonas } from "../lib/personas/store";
  import { play } from "../lib/uisound";
  import { unroll } from "../lib/unroll";

  const runtime = $derived(($accountsRes.data.accounts ?? []) as Runtime[]);
  const slots = $derived((($slotsRes.data.slots ?? []) as Slot[]).filter((s) => platformOn($socialsOn, s.platform)));
  /** A social switched off in Settings is shown nowhere: not its accounts (the server leaves them out), not a way to
      add one (lib/socials.ts). */
  const on = (id: PlatformId) => $socialsOn[id] !== false;
  const anyOn = $derived(SOCIALS.some((id) => $socialsOn[id] !== false));
  const activity = $derived($activityRes.data);
  /** Only a genuinely cold start shows placeholders; a refresh never does. */
  const cold = $derived(!$slotsRes.fetched && !$slotsRes.error);

  let moods = $state<string[]>([]);
  /** What each mood tells it: the line under its name in a card's mood picker. */
  let moodLines = $state<Record<string, string>>({});
  let acting = $state("");

  // ── Personas: who each account speaks as ──────────────────────────────────
  const cast = $derived($personasRes.data);
  const personaIdOf = (s: Slot) => cast.accounts[s.id] || "default";
  /** Each persona's own moods, for the cards of the accounts speaking as it. */
  let moodsBy = $state<Record<string, string[]>>({});
  let moodLinesBy = $state<Record<string, Record<string, string>>>({});
  $effect(() => {
    for (const pid of new Set(["default", ...Object.values(cast.accounts)])) {
      if (moodsBy[pid]) continue;
      loadMoods(false, pid).then((m) => (moodsBy = { ...moodsBy, [pid]: m }));
      loadMoodLines(false, pid).then((t) => (moodLinesBy = { ...moodLinesBy, [pid]: t }));
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
    loadMoodLines().then((t) => (moodLines = t));

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
  /** Everything but iMessage, which talks to your own Mac or phone rather than to a service. */
  const hasProxy = $derived(editPlatform !== "imessage");
  let saving = $state(false);
  let addMenu = $state(false);
  let addMenuEl: HTMLElement | null = $state(null);
  /** The menu fading out once closed: the strip stays raised over the cards until it has gone. */
  let addMenuLeaving = $state(false);
  /** The one highlight in the Add account menu, gliding to the row pointed at, as in every list of choices. */
  let addGlide = $state({ y: 0, h: 0, on: false, snap: true });
  /** Who a new account speaks as: given before it first starts. */
  let addPersona = $state("default");
  // Instagram keeps the whole login: its 2FA key beside the password, and the code it may ask for.
  let fTotp = $state("");
  /** X only: the email or phone on the account, which X asks for when it questions a login. */
  let fEmail = $state("");
  let igCode = $state("");
  let igCodeBusy = $state(false);
  /** The six digits the typed key makes right now, so the key can be checked before anything uses it. */
  let igShown = $state("");
  let igLeft = $state(0);
  // Minecraft: the world it joins, and how it signs in there. Empty server means the one Settings names.
  let fHost = $state("");
  let fAuth = $state<"offline" | "microsoft">("offline");
  /** A name Minecraft would take: 3 to 16 letters, digits or underscores. */
  const mcNameOk = $derived(/^[A-Za-z0-9_]{3,16}$/.test(fUser.trim()));
  // iMessage: the BlueBubbles Server on a Mac it reads through, and that server's password; Test asks it first.
  let fServer = $state("");
  // iMessage: through an iPhone or iPad (a Shortcuts automation on it passes each message here), or a Mac running
  // BlueBubbles. Most people have no Mac, so the phone comes first.
  let imVia = $state<"phone" | "mac">("phone");
  // Telegram: what my.telegram.org gives you once, the account's number, and what Telegram asks back.
  let tgApiId = $state("");
  let tgApiHash = $state("");
  let tgPhone = $state("");
  let tgCode = $state("");
  let tgPassword = $state("");
  let tgStep = $state("");
  let tgDetail = $state("");
  let tgBusy = $state(false);
  let imRenew = $state(false);
  let imTest = $state<Awaited<ReturnType<typeof api.imessageTest>> | null>(null);
  let imTesting = $state(false);

  async function testImessage() {
    imTesting = true;
    imTest = null;
    try {
      imTest = await api.imessageTest({ server: fServer.trim(), password: fPass, ...(adding ? {} : { index: editIndex }) });
      play(imTest?.ok ? "ok" : "err");
    } catch (e: any) {
      imTest = { ok: false, reason: e?.message || "Could not ask it" };
      play("err");
    } finally {
      imTesting = false;
    }
  }

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

  /**
   * The one thing the dialog's button does, whichever platform it is on: add it, sign it in, or save a change.
   * Each platform needs something different of you - a token, a password, a browser window, a code by text - and
   * before this each put its own button somewhere else in the dialog, with a dead "Add account" underneath. The
   * words always say what is about to happen.
   */
  const addAction = $derived.by(() => {
    const add = { icon: adding ? "plus" : "check", label: adding ? "Add account" : "Save",
                  busy: saving, off: !canSave, run: saveSlot,
                  leave: "Cancel", leaveRun: () => (editOpen = false) };
    // Something it asked for is on its way to the account, and only you can read it.
    if (igStep === "needs-code") {
      return { ...add, icon: "check", label: "Send the code", busy: igCodeBusy,
               leave: "Stop waiting", leaveRun: cancelBrowserLogin,
               off: !igCode.replace(/\D/g, ""), run: sendInstagramCode };
    }
    if (tgStep === "code" || tgStep === "password") {
      const code = tgStep === "code";
      return { ...add, icon: "check", leave: "Start again", leaveRun: cancelTelegram, busy: tgBusy,
               label: code ? "Send the code" : "Send the password",
               off: code ? !tgCode.replace(/\D/g, "") : !tgPassword,
               run: code ? sendTelegramCode : sendTelegramPassword };
    }
    // A Microsoft account is added by signing in. Editing one keeps Save, for its server; the bot asks Microsoft
    // again by itself, on its card, if its saved login ever runs out.
    if (editPlatform === "minecraft" && fAuth === "microsoft" && adding) {
      if (mcSigning) {
        return { ...add, icon: "check", label: mcSign.state === "code" ? "Waiting for you to sign in" : "Asking Microsoft",
                 busy: true, off: true, leave: "Stop waiting", leaveRun: cancelMinecraft };
      }
      return { ...add, icon: "external", label: "Sign in with Microsoft", busy: false, off: blocked,
               run: signInMinecraft };
    }
    // A sign-in window is open; it is signing itself in, and there is nothing to press until it is done.
    if (loginBusy) return { ...add, icon: "check", label: "Signing in", busy: true, off: true,
                            leave: "Stop waiting", leaveRun: cancelBrowserLogin };
    if (blocked) return { ...add, off: true };
    if (editPlatform === "telegram") {
      // Signing an account in again uses what is already stored, and the api pair is the same for every Telegram
      // account here, so only the first one has to be told it.
      const first = adding && !slots.some((s) => s.platform === "telegram");
      return { ...add, icon: "telegram", busy: tgBusy, run: signInTelegram,
               label: adding ? "Sign in to Telegram" : "Sign in again",
               off: (adding && !tgPhone.trim()) || (first && !(tgApiId.trim() && tgApiHash.trim())) };
    }
    if (editPlatform === "tiktok") {
      return { ...add, icon: "external", busy: loginBusy, off: false, run: loginDiscord,
               label: adding ? "Open TikTok and sign in" : "Sign in again" };
    }
    if (editPlatform === "reddit") {
      return { ...add, icon: "external", busy: loginBusy, off: false, run: loginDiscord,
               label: adding ? "Open Reddit and sign in" : "Sign in again" };
    }
    if (editPlatform === "whatsapp") {
      if (waLinking) {
        return { ...add, icon: "check", busy: true, off: true,
                 label: waLink.state === "asking" ? "Asking WhatsApp" : "Waiting for the phone",
                 leave: "Stop waiting", leaveRun: cancelWhatsapp };
      }
      return { ...add, icon: "phone", busy: false, run: linkWhatsapp,
               label: adding ? "Link a phone" : "Link it again",
               off: blocked || (waWay === "code" && waNumber.replace(/\D/g, "").length < 7) };
    }
    if (editPlatform === "instagram") {
      return { ...add, icon: "external", busy: loginBusy, off: false, run: loginDiscord,
               label: adding ? "Open Instagram and sign in" : "Sign in again" };
    }
    if (editPlatform === "x") {
      return { ...add, icon: "external", busy: loginBusy, off: false, run: loginDiscord,
               label: adding ? "Open X and sign in" : "Sign in again" };
    }
    if (adding && editPlatform === "discord" && discordMode === "login") {
      return { ...add, icon: "external", busy: loginBusy, off: false, run: loginDiscord,
               label: "Open Discord and sign in" };
    }
    return add;
  });
  // A platform this device cannot run (Snapchat on a phone) is not added here:
  // the dialog says why instead.
  const blocked = $derived(!!$notHere(editPlatform));
  const canSave = $derived(
    !blocked && (editPlatform === "minecraft" ? mcNameOk
      : editPlatform === "telegram" ? false
      : editPlatform === "imessage" ? imVia === "phone" || (!!fServer.trim() && (!adding || !!fPass))
      : !adding || (editPlatform === "discord" ? !!fToken.trim() : !!(fUser.trim() && fPass))),
  );
  /** my.telegram.org gives one api pair per person, not per account, so after the first it is already here. */
  const tgPairKnown = $derived(slots.some((s) => s.platform === "telegram" && s.api_hash_set));
  /** A 2FA key, when one was typed, has to be one the platform could have given. */
  const igKeyBad = $derived((editPlatform === "instagram" || editPlatform === "x"
                             || editPlatform === "reddit") && !!fTotp.trim() && !igShown);

  function openAdd(platform: string) {
    addMenu = false;
    editPlatform = platform;
    editIndex = 0;
    fToken = fProxy = fUser = fPass = fTotp = fHost = fServer = fEmail = "";
    fAuth = "offline";
    imTest = null;
    tgApiHash = tgPhone = tgCode = tgPassword = tgStep = tgDetail = "";
    // The api pair is one per person: a second Telegram account starts with the first one's, the hash included
    // (it stays on the server, so a blank one there means "the stored one").
    tgApiId = slots.find((s) => s.platform === "telegram" && !!s.api_id)?.api_id ?? "";
    imVia = "phone";
    imRenew = false;
    igCode = "";
    waWay = "code";
    waNumber = "";
    waLink = { ...WA_IDLE };
    stopWaPoll();
    reveal = false;
    startNow = true;
    showProxy = false;
    addPersona = "default";
    // Signing in opens a Chrome window, which a phone does not have. (TikTok has no other way in.)
    discordMode = missing("browser_login") ? "token" : "login";
    loginNote = "";
    loginState = "idle";
    stopLoginPoll();
    if (mcSigning) void cancelMinecraft();
    mcSign = { ...MC_IDLE };
    editOpen = true;
  }

  function openEdit(s: Slot) {
    editPlatform = s.platform;
    editIndex = s.index;
    // Never prefilled: the server does not hand credentials back, so these
    // stay blank and a blank field means "leave the stored one alone".
    fToken = fPass = fTotp = "";
    igCode = "";
    fProxy = s.proxy ?? "";
    fUser = s.username ?? "";
    // A running account whose own runner is waiting for a code: the box for it is open with the dialog, and what
    // is typed goes to that runner over IPC. Nothing else ever opens it now that a sign-in window is answered in
    // the window.
    igStep = runtimeFor(s)?.web?.state === "needs-code" ? "needs-code" : "";
    // X's email is no secret, so it comes back and shows: it is the one field a person has to correct by hand.
    fEmail = s.email ?? "";
    fHost = s.host ? (s.port ? `${s.host}:${s.port}` : s.host) : "";
    fAuth = s.auth === "microsoft" ? "microsoft" : "offline";
    imVia = s.server === "phone" ? "phone" : "mac";
    imRenew = false;
    fServer = s.server === "phone" ? "" : s.server ?? "";
    imTest = null;
    // Telegram's number and api_id are not secrets, so they show; the hash and the session stay on the server, and
    // signing in again sends the slot's number, which is what tells Telegram which account to send a code to.
    tgPhone = s.phone ?? "";
    tgApiId = s.api_id ?? "";
    tgApiHash = tgCode = tgPassword = tgStep = tgDetail = "";
    reveal = false;
    showProxy = !!fProxy;
    // Editing only ever replaces a stored token, never logs in again.
    discordMode = "token";
    loginNote = "";
    loginState = "idle";
    stopLoginPoll();
    if (mcSigning) void cancelMinecraft();
    mcSign = { ...MC_IDLE };
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
    const wasAdding = adding;
    editOpen = false;
    await accountsRes.refresh({ force: true, quiet: true });
    const id = `${editPlatform}_${res.index}`;
    if (!wasAdding) {
      // Signed in again: the same account, with a fresh session. A running one picks it up as it restarts.
      const slot = (res.slots || []).find((s: Slot) => s.id === id);
      toast("Signed in again.", "ok");
      if (slot && runtimeFor(slot)?.state === "running") await action(slot, "restart");
      return;
    }
    await giveNewPersona(id);
    const slot = (res.slots || []).find((s: Slot) => s.id === id);
    if (startNow && slot && runtimeFor(slot)) {
      toast("Account added. Starting it now.", "ok");
      await action(slot, "start");
    } else {
      toast("Account added.", "ok");
    }
  }

  // ── Telegram: it signs in the way Telegram signs anyone in ────────────────
  // api_id and api_hash come from my.telegram.org, once, and are the same for every account here. Then the
  // number, the code Telegram sends to it, and the two-step password where the account has one.
  async function signInTelegram() {
    tgBusy = true;
    loginNote = "";
    tgDetail = "";
    try {
      const res: any = await api.telegramSignInStart({
        ...(adding ? {} : { index: editIndex }),
        api_id: tgApiId.trim(), api_hash: tgApiHash.trim(), phone: tgPhone.trim(), proxy: fProxy.trim(),
      });
      tgStep = res?.state || "";
      tgDetail = res?.detail || "";
      if (res?.state === "failed") {
        loginNote = res.detail || "Telegram would not take it.";
        tgStep = "";
      }
    } catch (e: any) {
      loginNote = e?.message || "Could not reach Telegram.";
    } finally {
      tgBusy = false;
    }
  }

  async function cancelTelegram() {
    tgStep = "";
    tgDetail = "";
    tgCode = tgPassword = "";
    try {
      await api.telegramSignInCancel();
    } catch {
      /* nothing was waiting */
    }
  }

  async function sendTelegramCode() {
    const code = tgCode.replace(/\D/g, "");
    if (!code) return;
    tgBusy = true;
    try {
      const res: any = await api.telegramSignInCode(code);
      tgStep = res?.state || "";
      tgDetail = res?.detail || "";
      if (res?.state === "done") await finishTelegram();
      else if (res?.state === "failed") { loginNote = res.detail || "That did not work."; tgStep = ""; }
    } catch (e: any) {
      loginNote = e?.message || "Telegram would not take it";
    } finally {
      tgBusy = false;
      tgCode = "";
    }
  }

  async function sendTelegramPassword() {
    if (!tgPassword) return;
    tgBusy = true;
    try {
      const res: any = await api.telegramSignInPassword(tgPassword);
      tgStep = res?.state || "";
      tgDetail = res?.detail || "";
      if (res?.state === "done") await finishTelegram();
      else if (res?.state === "failed") { loginNote = res.detail || "That did not work."; tgStep = ""; }
    } catch (e: any) {
      loginNote = e?.message || "Telegram would not take it";
    } finally {
      tgBusy = false;
      tgPassword = "";
    }
  }

  /** Telegram has let it in: the slot is stored by then, so the dialog closes on it. */
  async function finishTelegram() {
    const res: any = await api.telegramSignInStatus();
    tgStep = "";
    if (res?.slots) await finishAdd(res);
    else {
      editOpen = false;
      toast("Signed in again.", "ok");
      await accountsRes.refresh({ force: true, quiet: true });
    }
  }

  // ── Minecraft with Microsoft: signed in, not typed in ───────────────────────
  // A Microsoft account already knows its Minecraft name, so asking for one asked you to type what the sign-in would
  // say, and to get it exactly right - it is also what the bot files its saved login under. Microsoft's own code is
  // shown here instead, and the account is added with the name Microsoft gives once you have signed in.
  const MC_IDLE = { state: "", code: "", link: "", uri: "", reason: "" };
  let mcSign = $state({ ...MC_IDLE });
  let mcPoll: ReturnType<typeof setInterval> | null = null;
  const mcSigning = $derived(mcSign.state === "asking" || mcSign.state === "code");

  function stopMcPoll() {
    if (mcPoll) clearInterval(mcPoll);
    mcPoll = null;
  }

  function showMcSign(r: any) {
    mcSign = { state: r?.state || "", code: r?.code || "", link: r?.link || "", uri: r?.uri || "",
               reason: r?.reason || "" };
    if (r?.state === "failed") loginNote = r.reason || "Microsoft did not let it in.";
  }

  async function signInMinecraft() {
    loginNote = "";
    const [host, port] = fHost.trim().split(":");
    mcSign = { ...MC_IDLE, state: "asking" };
    try {
      const res = await api.minecraftSignInStart({ host: host || "", port: port || "",
                                                   ...(adding ? {} : { index: editIndex }) });
      showMcSign(res);
      if (res.state === "failed") return;
      stopMcPoll();
      mcPoll = setInterval(pollMinecraft, 2000);
    } catch (e: any) {
      showMcSign({ state: "failed", reason: e?.message || "Could not reach Microsoft." });
    }
  }

  async function pollMinecraft() {
    try {
      const r: any = await api.minecraftSignInStatus();
      if (r?.state === "done" && r?.slots) {
        stopMcPoll();
        mcSign = { ...MC_IDLE };
        play("rise");
        await finishAdd(r);
        if (r.name) toast(`Signed in as ${r.name}.`, "ok");
        return;
      }
      if (r?.code !== mcSign.code && r?.state === "code") play("tap");
      showMcSign(r);
      if (r?.state === "failed" || r?.state === "idle") stopMcPoll();
    } catch {
      /* the next look will do */
    }
  }

  async function cancelMinecraft() {
    stopMcPoll();
    mcSign = { ...MC_IDLE };
    try {
      await api.minecraftSignInCancel();
    } catch {
      /* nothing was waiting */
    }
  }

  /**
   * What a sign-in says it is doing. Nothing sets this from a sign-in window any more - X and Instagram stopped
   * typing their own logins, so every platform here signs in through loginDiscord and pollBrowserLogin - but a
   * running account's own runner can still ask for a code, and openEdit puts that state here so the box for it
   * is there when the dialog opens.
   */
  let igStep = $state("");

  async function sendInstagramCode() {
    const code = igCode.replace(/\D/g, "");
    if (!code) return;
    const where = editPlatform === "x" ? "X" : editPlatform === "reddit" ? "Reddit" : "Instagram";
    igCodeBusy = true;
    try {
      if (editPlatform === "x") await api.xSignInCode(code, editIndex);
      else if (editPlatform === "reddit") await api.redditSignInCode(code, editIndex);
      else await api.instagramSignInCode(code, editIndex);
      igCode = "";
      toast(`Code sent to ${where}.`, "ok");
    } catch (e: any) {
      toast(e?.message || `${where} would not take it`, "err");
    } finally {
      igCodeBusy = false;
    }
  }

  // The six digits the typed key makes, kept current while the dialog is open: the person checks it against their
  // own authenticator app and knows the key is the right one.
  $effect(() => {
    const key = fTotp.trim();
    if ((editPlatform !== "instagram" && editPlatform !== "x" && editPlatform !== "reddit")
        || !editOpen || !key) {
      igShown = "";
      igLeft = 0;
      return;
    }
    let alive = true;
    const tick = async () => {
      const { totp, secondsLeft } = await import("../lib/totp");
      if (!alive) return;
      igShown = await totp(key);
      igLeft = secondsLeft();
    };
    tick();
    const t = setInterval(tick, 1000);
    return () => { alive = false; clearInterval(t); };
  });

  /**
   * The platforms whose sign-in is a window you sign in yourself: the app opens their own login page on a fresh
   * browser profile, waits, and keeps the session that window was given. Three calls each, the same three, so
   * they are a table rather than a branch per platform.
   */
  const BROWSER_SIGNIN: Record<string, { start: () => Promise<any>; status: () => Promise<any>;
                                         cancel: () => Promise<any> }> = {
    tiktok: { start: () => api.tiktokBrowserLoginStart({ proxy: fProxy.trim() }), status: api.tiktokBrowserLoginStatus,
              cancel: api.tiktokBrowserLoginCancel },
    reddit: { start: () => api.redditBrowserLoginStart({ proxy: fProxy.trim() }), status: api.redditBrowserLoginStatus,
              cancel: api.redditBrowserLoginCancel },
    // X's and Instagram's kept their own addresses when they stopped typing the login themselves, so these are
    // the same three calls under the older names.
    x: { start: () => api.xSignInStart({ proxy: fProxy.trim() }), status: api.xSignInStatus, cancel: api.xSignInCancel },
    instagram: { start: () => api.instagramSignInStart({ proxy: fProxy.trim() }), status: api.instagramSignInStatus,
                 cancel: api.instagramSignInCancel },
  };

  async function loginDiscord() {
    loginBusy = true;
    loginNote = "";
    loginState = "opening";
    try {
      const flow = BROWSER_SIGNIN[editPlatform];
      const res: any = flow ? await flow.start() : await api.discordBrowserLoginStart({ proxy: fProxy });
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
      const flow = BROWSER_SIGNIN[editPlatform];
      const res: any = flow ? await flow.status() : await api.discordBrowserLoginStatus(fProxy);
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
      } else if (res?.state === "checking") {
        loginState = "waiting";
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
      const flow = BROWSER_SIGNIN[editPlatform];
      if (flow) await flow.cancel();
      else if (editPlatform === "instagram") await api.instagramSignInCancel();
      else if (editPlatform === "x") await api.xSignInCancel();
      else await api.discordBrowserLoginCancel();
    } catch {
      // The window may already be gone, which is the same outcome.
    }
  }

  async function saveSlot() {
    saving = true;
    try {
      const body: any = editPlatform === "discord"
        ? { token: fToken, proxy: fProxy }
        : editPlatform === "instagram"
          ? { username: fUser, password: fPass, totp: fTotp.trim() }
          : editPlatform === "x"
          ? { username: fUser, password: fPass, totp: fTotp.trim(), email: fEmail.trim() }
          : editPlatform === "whatsapp"
          // Its number is all there is: the keys its phone handed over are the login, and they are not here.
          ? { username: fUser.trim() }
          : editPlatform === "reddit"
          // Its username names its browser profile; the other two are optional and only for signing itself back
          // in later. A blank one leaves whatever is stored alone.
          ? { username: fUser.trim(), password: fPass, totp: fTotp.trim() }
          : editPlatform === "minecraft"
            // "host:port" as typed; the server splits it, and an empty one is whatever Settings names.
            ? { username: fUser.trim(), host: fHost.trim(), port: "", auth: fAuth }
            : editPlatform === "imessage"
              ? (imVia === "phone" ? { server: "phone", ...(imRenew ? { renew_relay: true } : {}) }
                                   : { server: fServer.trim(), password: fPass })
              : { username: fUser, password: fPass };
      if (hasProxy) body.proxy = fProxy.trim();
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
        if (editPlatform === "imessage" && imVia === "phone") openSettings("imessage/setup");
      } else {
        const rt = editing ? runtimeFor(editing) : undefined;
        const changedLogin = (hasProxy && fProxy.trim() !== (editing?.proxy ?? "")) || (editPlatform === "discord" ? !!fToken
          : editPlatform === "imessage" ? imRenew || (imVia === "phone") !== (editing?.server === "phone")
            || (imVia === "mac" && (!!fPass || fServer.trim() !== (editing?.server ?? "")))
          : !!fPass || fUser !== (editing?.username ?? ""));
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

  function toggleAddMenu() {
    if (!addMenu) {
      play("open");
      addGlide = { y: 0, h: 0, on: false, snap: true };
    }
    addMenu = !addMenu;
  }

  /** The highlight to the row under the pointer, or the one the keyboard is on. */
  function glideTo(e: Event) {
    const row = (e.target as Element | null)?.closest?.<HTMLElement>(".add-item");
    if (!row || (addGlide.on && addGlide.y === row.offsetTop)) return;
    addGlide = { y: row.offsetTop, h: row.offsetHeight, on: true, snap: !addGlide.on };
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
  // ── WhatsApp: a number linked from a phone ────────────────────────────────
  // WhatsApp gives either a code to type into the phone or a QR to point it at, and nothing at all happens on
  // this computer. The shape is Minecraft's: ask, show what came back, poll until the phone has done it.
  const WA_IDLE = { state: "", code: "", qr_svg: "", detail: "", reason: "" };
  let waWay = $state<"code" | "qr">("code");
  let waNumber = $state("");
  let waLink = $state({ ...WA_IDLE });
  let waPoll: ReturnType<typeof setInterval> | null = null;
  const waLinking = $derived(waLink.state === "asking" || waLink.state === "code" || waLink.state === "qr");

  function stopWaPoll() {
    if (waPoll) clearInterval(waPoll);
    waPoll = null;
  }

  function showWaLink(r: any) {
    waLink = { state: r?.state || "", code: r?.code || "", qr_svg: r?.qr_svg || "",
               detail: r?.detail || "", reason: r?.reason || "" };
    if (r?.state === "failed") loginNote = r.reason || "WhatsApp would not link it.";
  }

  async function linkWhatsapp() {
    loginNote = "";
    waLink = { ...WA_IDLE, state: "asking" };
    try {
      const res: any = await api.whatsappLinkStart({ number: waNumber.trim(), way: waWay, proxy: fProxy.trim() });
      showWaLink(res);
      if (res?.state === "failed") return;
      stopWaPoll();
      waPoll = setInterval(pollWhatsapp, 2000);
    } catch (e: any) {
      loginNote = e?.message || "WhatsApp would not link it.";
      waLink = { ...WA_IDLE };
    }
  }

  async function pollWhatsapp() {
    try {
      const r: any = await api.whatsappLinkStatus();
      if (r?.state === "linked" && r?.slots) {
        stopWaPoll();
        waLink = { ...WA_IDLE };
        play("rise");
        await finishAdd(r);
        toast(r.name ? `Linked as ${r.name}.` : "Linked.", "ok");
        return;
      }
      // A new code or a new QR is worth a tap; WhatsApp replaces the QR every twenty seconds or so.
      if ((r?.code && r.code !== waLink.code) || (r?.qr_svg && r.qr_svg !== waLink.qr_svg)) play("tap");
      showWaLink(r);
      if (r?.state === "failed" || r?.state === "idle") stopWaPoll();
    } catch {
      // A dropped poll is not a failure; the next one covers it.
    }
  }

  async function cancelWhatsapp() {
    stopWaPoll();
    waLink = { ...WA_IDLE };
    try {
      await api.whatsappLinkCancel();
    } catch {
      // It may already have gone, which is the same outcome.
    }
  }

  /** The TikTok account whose LIVE is open. */
  let liveFor = $state<Slot | null>(null);
  // A Minecraft account whose live view is open.
  let watchFor = $state<Slot | null>(null);

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
        {#if !anyOn}
          <div class="mt-6 flex flex-col items-center gap-3">
            <p class="text-[12.5px] text-faint">Every social is switched off.</p>
            <Button size="sm" onclick={() => { play("open"); openSettings("services"); }}>
              <Icon name="settings" size={13} />Turn one on in Settings
            </Button>
          </div>
        {/if}
        <div class="mx-auto mt-7 grid max-w-4xl gap-3 text-left sm:grid-cols-2 lg:grid-cols-3">
          {#if on("discord")}
            <button class="platform-card" onclick={() => openAdd("discord")}>
              <span class="platform-icon"><Icon name="discord" size={24} /></span>
              <span class="flex items-center gap-2 text-[15px] font-semibold text-ink">Discord<NotHere feature="discord" variant="chip" /></span>
              <span class="mt-1 block text-[12px] leading-snug text-muted">
                Signs in with the account's token. Replies in DMs, and in the groups
                and servers you allow.
              </span>
              <span class="platform-go">Add a Discord account <Icon name="chevron" size={12} /></span>
            </button>
          {/if}
          {#if on("snapchat")}
            <button class="platform-card" onclick={() => openAdd("snapchat")}>
              <span class="platform-icon"><Icon name="snapchat" size={24} /></span>
              <span class="flex items-center gap-2 text-[15px] font-semibold text-ink">Snapchat<NotHere feature="snapchat" variant="chip" /></span>
              <span class="mt-1 block text-[12px] leading-snug text-muted">
                Signs in with a username and password, in a browser that runs out
                of sight. Needs the Snapchat install from Settings.
              </span>
              <span class="platform-go">Add a Snapchat account <Icon name="chevron" size={12} /></span>
            </button>
          {/if}
          {#if on("instagram")}
            <button class="platform-card" onclick={() => openAdd("instagram")}>
              <span class="platform-icon"><Icon name="instagram" size={24} /></span>
              <span class="flex items-center gap-2 text-[15px] font-semibold text-ink">Instagram<NotHere feature="instagram" variant="chip" /></span>
              <span class="text-[12px] text-faint">DMs, stories and reels</span>
            </button>
          {/if}
          {#if on("tiktok")}
            <button class="platform-card" onclick={() => openAdd("tiktok")}>
              <span class="platform-icon"><Icon name="tiktok" size={24} /></span>
              <span class="flex items-center gap-2 text-[15px] font-semibold text-ink">TikTok<NotHere feature="tiktok" variant="chip" /></span>
              <span class="mt-1 block text-[12px] leading-snug text-muted">
                Sign in once in a window of its own. Answers DMs, and can answer comments and co-host your LIVE.
              </span>
              <span class="platform-go">Add a TikTok account <Icon name="chevron" size={12} /></span>
            </button>
          {/if}
          {#if on("x")}
            <button class="platform-card" onclick={() => openAdd("x")}>
              <span class="platform-icon"><Icon name="x" size={24} /></span>
              <span class="flex items-center gap-2 text-[15px] font-semibold text-ink">X (Twitter)<NotHere feature="x" variant="chip" /></span>
              <span class="text-[12px] text-faint">Messages, replies and posts</span>
            </button>
          {/if}
          {#if on("reddit")}
            <button class="platform-card" onclick={() => openAdd("reddit")}>
              <span class="platform-icon"><Icon name="reddit" size={24} /></span>
              <span class="flex items-center gap-2 text-[15px] font-semibold text-ink">Reddit<NotHere feature="reddit" variant="chip" /></span>
              <span class="text-[12px] text-faint">Chats, replies and comments</span>
              <span class="platform-go">Add a Reddit account <Icon name="chevron" size={12} /></span>
            </button>
          {/if}
          {#if on("whatsapp")}
            <button class="platform-card" onclick={() => openAdd("whatsapp")}>
              <span class="platform-icon"><Icon name="whatsapp" size={24} /></span>
              <span class="flex items-center gap-2 text-[15px] font-semibold text-ink">WhatsApp<NotHere feature="whatsapp" variant="chip" /></span>
              <span class="text-[12px] text-faint">Messages, groups and status</span>
              <span class="platform-go">Add a WhatsApp account <Icon name="chevron" size={12} /></span>
            </button>
          {/if}
          {#if on("minecraft")}
            <button class="platform-card" onclick={() => openAdd("minecraft")}>
              <span class="platform-icon"><Icon name="minecraft" size={24} /></span>
              <span class="flex items-center gap-2 text-[15px] font-semibold text-ink">Minecraft<NotHere feature="minecraft" variant="chip" /></span>
              <span class="mt-1 block text-[12px] leading-snug text-muted">
                Joins a world as a player of its own, plays, and talks with the people there. Needs the Minecraft
                install from Settings.
              </span>
              <span class="platform-go">Add a Minecraft account <Icon name="chevron" size={12} /></span>
            </button>
          {/if}
          {#if on("telegram")}
            <button class="platform-card" onclick={() => openAdd("telegram")}>
              <span class="platform-icon"><Icon name="telegram" size={24} /></span>
              <span class="flex items-center gap-2 text-[15px] font-semibold text-ink">Telegram</span>
              <span class="mt-1 block text-[12px] leading-snug text-muted">
                Chats on a Telegram account of its own: groups, photos, voice messages and reactions.
              </span>
              <span class="platform-go">Add a Telegram account <Icon name="chevron" size={12} /></span>
            </button>
          {/if}
          {#if on("imessage")}
            <button class="platform-card" onclick={() => openAdd("imessage")}>
              <span class="platform-icon"><Icon name="imessage" size={24} /></span>
              <span class="flex items-center gap-2 text-[15px] font-semibold text-ink">iMessage<NotHere feature="imessage" variant="chip" /></span>
              <span class="mt-1 block text-[12px] leading-snug text-muted">
                Texts as you, groups included, through BlueBubbles on a Mac signed in to iMessage.
              </span>
              <span class="platform-go">Add an iMessage account <Icon name="chevron" size={12} /></span>
            </button>
          {/if}
        </div>
      </div>
    </section>
  {:else}
    <!-- What a phone asks of you: keep the app open, and one Discord account at a time. -->
    <NotHere feature="background" />
    <NotHere feature="discord_many" when={slots.filter((s) => s.platform === "discord").length > 1} />
    <!-- ── The whole set, at a glance ─────────────────────────────────────── -->
    <section class="fleet glass flex flex-wrap items-center gap-x-7 gap-y-4 rounded-2xl px-5 py-4"
             class:is-raised={addMenu || addMenuLeaving}>
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
        <!-- A flex box, not a line of text: a line box left room for letters' tails under the button, and the menu
             hung that much lower than it looked. -->
        <div class="relative" bind:this={addMenuEl} class:flex={anyOn} class:hidden={!anyOn}>
          <Button size="sm" onclick={toggleAddMenu}>
            <Icon name="plus" size={13} />Add account
          </Button>
          {#if addMenu}
            <!-- Each platform as its own little app icon, the way Settings shows them beside their switches. -->
            {#snippet addMark(id: PlatformId)}
              <span class="add-mark settings-mark is-social is-{id}" style="--tone: {PLATFORMS[id].tone}" aria-hidden="true">
                <Icon name={PLATFORMS[id].icon} size={12} />
              </span>
            {/snippet}
            <div class="add-menu glass floating unroll" role="menu" tabindex="-1" use:unroll={".add-item"}
                 onpointerover={glideTo} onfocusin={glideTo} onpointerleave={() => (addGlide = { ...addGlide, on: false })}
                 out:fly={{ y: -4, duration: 150 * dur, opacity: 0 }}
                 onoutrostart={() => (addMenuLeaving = true)} onoutroend={() => (addMenuLeaving = false)}>
              <span class="add-glide" class:is-on={addGlide.on} class:is-snap={addGlide.snap} aria-hidden="true"
                    style="transform: translateY({addGlide.y}px); height: {addGlide.h}px"></span>
              {#if on("discord")}
                <button class="add-item" role="menuitem" onclick={() => openAdd("discord")}>
                  {@render addMark("discord")}<span class="add-name">Discord</span>
                  <span class="ml-auto"><NotHere feature="discord" variant="chip" /></span>
                </button>
              {/if}
              {#if on("snapchat")}
                <button class="add-item" role="menuitem" onclick={() => openAdd("snapchat")}>
                  {@render addMark("snapchat")}<span class="add-name">Snapchat</span>
                  <span class="ml-auto"><NotHere feature="snapchat" variant="chip" /></span>
                </button>
              {/if}
              {#if on("tiktok")}
                <button class="add-item" role="menuitem" onclick={() => openAdd("tiktok")}>
                  {@render addMark("tiktok")}<span class="add-name">TikTok</span>
                  <span class="ml-auto"><NotHere feature="tiktok" variant="chip" /></span>
                </button>
              {/if}
              {#if on("instagram")}
                <button class="add-item" role="menuitem" onclick={() => openAdd("instagram")}>
                  {@render addMark("instagram")}<span class="add-name">Instagram</span>
                  <span class="ml-auto"><NotHere feature="instagram" variant="chip" /></span>
                </button>
              {/if}
              {#if on("x")}
                <button class="add-item" role="menuitem" onclick={() => openAdd("x")}>
                  {@render addMark("x")}<span class="add-name">X (Twitter)</span>
                  <span class="ml-auto"><NotHere feature="x" variant="chip" /></span>
                </button>
              {/if}
              {#if on("reddit")}
                <button class="add-item" role="menuitem" onclick={() => openAdd("reddit")}>
                  {@render addMark("reddit")}<span class="add-name">Reddit</span>
                  <span class="ml-auto"><NotHere feature="reddit" variant="chip" /></span>
                </button>
              {/if}
              {#if on("whatsapp")}
                <button class="add-item" role="menuitem" onclick={() => openAdd("whatsapp")}>
                  {@render addMark("whatsapp")}<span class="add-name">WhatsApp</span>
                  <span class="ml-auto"><NotHere feature="whatsapp" variant="chip" /></span>
                </button>
              {/if}
              {#if on("minecraft")}
                <button class="add-item" role="menuitem" onclick={() => openAdd("minecraft")}>
                  {@render addMark("minecraft")}<span class="add-name">Minecraft</span>
                  <span class="ml-auto"><NotHere feature="minecraft" variant="chip" /></span>
                </button>
              {/if}
              {#if on("imessage")}
                <button class="add-item" role="menuitem" onclick={() => openAdd("imessage")}>
                  {@render addMark("imessage")}<span class="add-name">iMessage</span>
                  <span class="ml-auto"><NotHere feature="imessage" variant="chip" /></span>
                </button>
              {/if}
              {#if on("telegram")}
                <button class="add-item" role="menuitem" onclick={() => openAdd("telegram")}>
                  {@render addMark("telegram")}<span class="add-name">Telegram</span>
                </button>
              {/if}
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
              moodLines={moodLinesBy[personaIdOf(r.slot)] ?? moodLines}
              {acting}
              onpersona={(pid) => setPersona(r.slot, pid)}
              onaction={(a) => action(r.slot, a)}
              onedit={() => openEdit(r.slot)}
              ondelete={() => (confirmDelete = r.slot)}
              onprofile={r.rt && r.slot.platform === "discord" ? () => (profileFor = r.rt ?? null) : undefined}
              onmood={(m) => setMood(r.slot, m)}
              onchats={() => openChats(r.slot)}
              onlive={r.slot.platform === "tiktok" ? () => (liveFor = r.slot) : undefined}
              onwatch={r.slot.platform === "minecraft" ? () => (watchFor = r.slot) : undefined}
              onlogs={() => openLogs(r.slot)}
              onsettings={openSettings}
            />
          </div>
        </div>
      {/each}

      <div class="add-tile" class:hidden={!anyOn}>
        <div class="add-orb"><Icon name="plus" size={22} /></div>
        <div class="text-[15px] font-semibold text-ink">Add {slots.length ? "another" : "an"} account</div>
        <p class="max-w-[19rem] text-[12px] leading-relaxed text-muted">
          Each one runs on its own, with its own login, mood and profile.
        </p>
        <div class="add-platforms mt-1 w-full max-w-[22rem]">
          {#if on("discord")}
            <button class="add-platform" onclick={() => openAdd("discord")}>
              <Icon name="discord" size={16} />Discord
            </button>
          {/if}
          {#if on("snapchat")}
            <button class="add-platform" onclick={() => openAdd("snapchat")}>
              <Icon name="snapchat" size={16} />Snapchat
            </button>
          {/if}
          {#if on("tiktok")}
            <button class="add-platform" onclick={() => openAdd("tiktok")}>
              <Icon name="tiktok" size={16} />TikTok
            </button>
          {/if}
          {#if on("instagram")}
            <button class="add-platform" onclick={() => openAdd("instagram")}>
              <Icon name="instagram" size={16} />Instagram
            </button>
          {/if}
          {#if on("x")}
            <button class="add-platform" onclick={() => openAdd("x")}>
              <Icon name="x" size={16} />X
            </button>
          {/if}
          {#if on("reddit")}
            <button class="add-platform" onclick={() => openAdd("reddit")}>
              <Icon name="reddit" size={16} />Reddit
            </button>
          {/if}
          {#if on("whatsapp")}
            <button class="add-platform" onclick={() => openAdd("whatsapp")}>
              <Icon name="whatsapp" size={16} />WhatsApp
            </button>
          {/if}
          {#if on("minecraft")}
            <button class="add-platform" onclick={() => openAdd("minecraft")}>
              <Icon name="minecraft" size={16} />Minecraft
            </button>
          {/if}
          {#if on("imessage")}
            <button class="add-platform" onclick={() => openAdd("imessage")}>
              <Icon name="imessage" size={16} />iMessage
            </button>
          {/if}
          {#if on("telegram")}
            <button class="add-platform" onclick={() => openAdd("telegram")}>
              <Icon name="telegram" size={16} />Telegram
            </button>
          {/if}
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
            <svg viewBox="-1 -1 26 26">
              {#if editPlatform === "instagram"}
                <defs>
                  <linearGradient id="aa-ig-grad" x1="0" y1="1" x2="1" y2="0">
                    <stop offset="0%" stop-color="#feda75" /><stop offset="25%" stop-color="#fa7e1e" />
                    <stop offset="55%" stop-color="#d62976" /><stop offset="80%" stop-color="#962fbf" />
                    <stop offset="100%" stop-color="#4f5bd5" />
                  </linearGradient>
                </defs>
              {/if}
              <path d={editPlatform === "discord" ? DISCORD_MARK : editPlatform === "tiktok" ? TIKTOK_MARK
                       : editPlatform === "instagram" ? INSTAGRAM_MARK
                       : editPlatform === "x" ? X_MARK
                       : editPlatform === "reddit" ? REDDIT_SNOO
                       : editPlatform === "whatsapp" ? WHATSAPP_MARK
                       : editPlatform === "minecraft" ? MINECRAFT_CUBE
                       : editPlatform === "imessage" ? IMESSAGE_BUBBLE
                       : editPlatform === "telegram" ? TELEGRAM_PLANE : SNAPCHAT_GHOST}
                    fill-rule={editPlatform === "instagram" ? "evenodd" : undefined}
                    fill={editPlatform === "instagram" ? "url(#aa-ig-grad)" : undefined} />
            </svg>
          </span>
          <span class="aa-hero-text">
            <!-- The whole name here, where there is room for it: the cards use the short one. -->
            <span class="aa-hero-title">{fullPlatformName(editPlatform)}</span>
            <span class="aa-hero-sub">
              {editPlatform === "discord"
                ? "Sign in once. The app keeps it online and replying."
                : editPlatform === "tiktok"
                  ? "Sign in once, in its own window. It stays signed in."
                  : editPlatform === "instagram"
                    ? "Sign in once, in its own window. It stays signed in."
                    : editPlatform === "x"
                      ? "Sign in once, in its own window. It stays signed in."
                    : editPlatform === "reddit"
                      ? "Sign in once, in its own window. It stays signed in."
                    : editPlatform === "whatsapp"
                      ? "Linked from your phone, the way a second device is. Nothing opens here."
                    : editPlatform === "minecraft"
                      ? "It joins a world and plays there, as itself."
                      : editPlatform === "imessage"
                        ? (imVia === "phone" ? "It texts through your iPhone or iPad. No Mac needed."
                                             : "It texts through BlueBubbles on a Mac signed in to iMessage.")
                      : editPlatform === "telegram"
                        ? "It chats on a Telegram account of its own, signed in by phone."
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
        { id: "tiktok", label: "TikTok", icon: "tiktok", tone: "#fe2c55" },
        { id: "instagram", label: "Instagram", icon: "instagram", tone: "#e1306c" },
        { id: "x", label: "X", icon: "x", tone: "#e7e9ea" },
        { id: "reddit", label: "Reddit", icon: "reddit", tone: "#ff4500" },
        { id: "whatsapp", label: "WhatsApp", icon: "whatsapp", tone: "#25d366" },
        { id: "minecraft", label: "Minecraft", icon: "minecraft", tone: "#5b8731" },
        { id: "imessage", label: "iMessage", icon: "imessage", tone: "#0a84ff" },
        { id: "telegram", label: "Telegram", icon: "telegram", tone: "#2aabee" },
      ]} />
      <NotHere feature={editPlatform} />
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

    {#if editPlatform === "tiktok"}
      <!-- TikTok has no login a script can use: a window opens on TikTok's own sign-in, and you sign in there any way
           it offers. The session stays in that account's own browser profile. -->
      <div class="aa-panel">
        <ol class="aa-steps" class:is-idle={loginState === "idle"}
            style="--at: {loginState === 'waiting' ? 1 : loginState === 'opening' ? 0.5 : 0}">
          <li class="aa-step" class:is-now={loginState === "opening"} class:is-done={loginState === "waiting"}>
            <span class="aa-step-i"><Icon name="globe" size={16} /></span>
            <span class="aa-step-t">A window opens</span>
          </li>
          <li class="aa-step" class:is-now={loginState === "waiting"}>
            <span class="aa-step-i"><Icon name="key" size={16} /></span>
            <span class="aa-step-t">You sign in</span>
          </li>
          <li class="aa-step">
            <span class="aa-step-i"><Icon name="check" size={16} /></span>
            <span class="aa-step-t">{adding ? "It is added" : "It is back in"}</span>
          </li>
        </ol>
        {#if loginState !== "idle"}
          <p class="aa-status">
            <span class="aa-spin" aria-hidden="true"></span>
            {loginState === "opening" ? "Opening the window…" : "Waiting for you to sign in. The window is open."}
          </p>
        {:else}
          <p class="aa-fine">
            <Icon name="eyeOff" size={12} />
            Scan the QR code with the TikTok app, or use a password. Your password never reaches the app.
          </p>
        {/if}
      </div>
      {#if loginNote}
        <div class="login-note">
          <span class="mt-0.5 shrink-0"><Icon name="alert" size={14} /></span>
          <span class="min-w-0">{loginNote}</span>
        </div>
      {/if}
    {:else if editPlatform === "whatsapp"}
      <!-- WhatsApp links a device two ways and allows exactly one of them per attempt: a code it gives for a
           number, typed into the phone, or a QR the phone's camera reads. Nothing opens on this machine either
           way, and what the phone hands back is the whole of the login. -->
      {#if !adding}
        <div class="aa-field">
          <label for="wa-num" class="mb-1 block text-xs font-medium text-muted">Its number</label>
          <div class="relative">
            <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">+</span>
            <input id="wa-num" type="text" inputmode="tel" bind:value={fUser} onkeydown={enter} spellcheck="false"
                   autocomplete="off" placeholder="447700900123" class="field w-full pl-6" />
          </div>
          <p class="mt-1 text-[11px] text-faint">Linking it again replaces the keys this number already has here.</p>
        </div>
      {/if}

      {#if !waLinking}
        <Segmented label="How to link it" bind:value={waWay} options={[
          { id: "code", label: "A code to type", icon: "key", tone: "#25d366" },
          { id: "qr", label: "A code to scan", icon: "pictures", tone: "#25d366" },
        ]} />
      {/if}

      {#if waWay === "code" && !waLinking}
        <div class="aa-field">
          <label for="wa-link-num" class="mb-1 block text-xs font-medium text-muted">
            The phone's number
          </label>
          <div class="relative">
            <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">+</span>
            <input id="wa-link-num" type="text" inputmode="tel" bind:value={waNumber} onkeydown={enter}
                   spellcheck="false" autocomplete="off" placeholder="447700900123"
                   class="field w-full pl-6" />
          </div>
          <p class="mt-1 text-[11px] text-faint">
            With its country code and no symbols. WhatsApp gives a code for this number alone.
          </p>
        </div>
      {/if}

      <div class="aa-panel">
        <ol class="aa-steps" class:is-idle={!waLink.state}
            style="--at: {waLink.state === 'code' || waLink.state === 'qr' ? 1 : waLink.state === 'asking' ? 0.5 : 0}">
          <li class="aa-step" class:is-now={waLink.state === "asking"}
              class:is-done={waLink.state === "code" || waLink.state === "qr"}>
            <span class="aa-step-i"><Icon name="key" size={16} /></span>
            <span class="aa-step-t">{waWay === "qr" ? "WhatsApp draws a code" : "WhatsApp gives a code"}</span>
          </li>
          <li class="aa-step" class:is-now={waLink.state === "code" || waLink.state === "qr"}>
            <span class="aa-step-i"><Icon name="phone" size={16} /></span>
            <span class="aa-step-t">{waWay === "qr" ? "You scan it" : "You type it into the phone"}</span>
          </li>
          <li class="aa-step">
            <span class="aa-step-i"><Icon name="check" size={16} /></span>
            <span class="aa-step-t">{adding ? "It is added" : "It is linked again"}</span>
          </li>
        </ol>

        {#if waLink.state === "code" && waLink.code}
          <div class="mc-code-ask">
            <span class="mc-code" aria-label="The code">{waLink.code}</span>
            <p class="aa-status">
              <span class="aa-spin" aria-hidden="true"></span>
              On the phone: WhatsApp, Linked devices, Link with phone number. Type that in and it is added here
              by itself.
            </p>
          </div>
        {:else if waLink.state === "qr" && waLink.qr_svg}
          <div class="wa-qr-ask">
            <!-- Dark on a white plate: an inverted code is what a lot of phone cameras quietly refuse to read. -->
            <div class="wa-qr" role="img" aria-label="The code to scan">{@html waLink.qr_svg}</div>
            <p class="aa-status">
              <span class="aa-spin" aria-hidden="true"></span>
              On the phone: WhatsApp, Linked devices, Link a device. Point it at this.
            </p>
          </div>
        {:else if waLink.state === "asking"}
          <p class="aa-status"><span class="aa-spin" aria-hidden="true"></span>Asking WhatsApp…</p>
        {:else}
          <p class="aa-fine">
            <Icon name="eyeOff" size={12} />
            Nothing opens on this computer. The phone does the linking, and keeps the account.
          </p>
        {/if}
      </div>
      {#if loginNote}
        <div class="login-note">
          <span class="mt-0.5 shrink-0"><Icon name="alert" size={14} /></span>
          <span class="min-w-0">{loginNote}</span>
        </div>
      {/if}
    {:else if editPlatform === "reddit"}
      <!-- Reddit signs in the way TikTok does: a window opens on Reddit's own page and you sign in there, however
           you like. The app never sees a password, and nothing it does looks like a script signing in - which
           matters more here than anywhere else, because Reddit's answer to an account it dislikes is to hide it
           rather than to lock it, and nothing tells you when it has. -->
      {#if !adding}
        <div class="aa-field">
          <label for="rd-usr" class="mb-1 block text-xs font-medium text-muted">Username</label>
          <div class="relative">
            <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">u/</span>
            <input id="rd-usr" type="text" bind:value={fUser} onkeydown={enter} spellcheck="false" autocomplete="off"
                   placeholder="username" class="field w-full pl-8" />
          </div>
          <p class="mt-1 text-[11px] text-faint">Changing it here takes its signed-in browser profile with it.</p>
        </div>
      {/if}
      <div class="aa-panel">
        <ol class="aa-steps" class:is-idle={loginState === "idle"}
            style="--at: {loginState === 'waiting' ? 1 : loginState === 'opening' ? 0.5 : 0}">
          <li class="aa-step" class:is-now={loginState === "opening"} class:is-done={loginState === "waiting"}>
            <span class="aa-step-i"><Icon name="globe" size={16} /></span>
            <span class="aa-step-t">A window opens</span>
          </li>
          <li class="aa-step" class:is-now={loginState === "waiting"}>
            <span class="aa-step-i"><Icon name="key" size={16} /></span>
            <span class="aa-step-t">You sign in</span>
          </li>
          <li class="aa-step">
            <span class="aa-step-i"><Icon name="check" size={16} /></span>
            <span class="aa-step-t">{adding ? "It is added" : "It is back in"}</span>
          </li>
        </ol>
        {#if loginState !== "idle"}
          <p class="aa-status">
            <span class="aa-spin" aria-hidden="true"></span>
            {loginState === "opening" ? "Opening the window…" : "Waiting for you to sign in. The window is open."}
          </p>
        {:else}
          <p class="aa-fine">
            <Icon name="eyeOff" size={12} />
            Sign in any way Reddit offers. Your password never reaches the app.
          </p>
        {/if}
      </div>
      {#if !adding}
        <!-- Neither is needed, and nothing waits for them: they are only what lets it sign itself back in months
             later with nobody here. Reddit sessions last, so most accounts never need either. -->
        <div class="aa-field">
          <label for="rd-pwd" class="mb-1 block text-xs font-medium text-muted">
            Password <span class="text-faint">optional, to sign itself back in</span>
          </label>
          <div class="relative">
            <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
              <Icon name="key" size={13} />
            </span>
            <input id="rd-pwd" type={reveal ? "text" : "password"} bind:value={fPass} onkeydown={enter}
                   autocomplete="new-password" placeholder="leave blank to keep the current one"
                   class="field w-full pl-8 pr-9" />
            <button type="button" class="reveal" onclick={() => (reveal = !reveal)}
                    aria-label={reveal ? "Hide" : "Show"}>
              <Icon name={reveal ? "eyeOff" : "eye"} size={14} />
            </button>
          </div>
          <p class="mt-1 text-[11px] text-faint">Kept in config/.env on this machine and never sent back to the page.</p>
        </div>
        <div class="aa-field">
          <label for="rd-totp" class="mb-1 block text-xs font-medium text-muted">
            2FA key <span class="text-faint">optional</span>
          </label>
          <div class="relative">
            <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
              <Icon name="clock" size={13} />
            </span>
            <input id="rd-totp" type="text" bind:value={fTotp} onkeydown={enter} spellcheck="false"
                   autocomplete="off" placeholder="G54M E4E3 T37W 6IXH" class="field w-full pl-8 font-mono" />
          </div>
          {#if igShown}
            <p class="ig-code-now">
              <span class="ig-code-digits">{igShown}</span>
              <span class="ig-code-left">{igLeft}s</span>
              <span class="ig-code-what">Check this against your authenticator app.</span>
            </p>
          {:else if fTotp.trim()}
            <p class="mt-1 text-[11px] text-warn">That is not a 2FA key. It is the letters beside the QR code.</p>
          {:else}
            <p class="mt-1 text-[11px] text-faint">Only needed if 2FA is on and you want it to sign itself back in.</p>
          {/if}
        </div>
      {/if}
      {#if loginNote}
        <div class="login-note">
          <span class="mt-0.5 shrink-0"><Icon name="alert" size={14} /></span>
          <span class="min-w-0">{loginNote}</span>
        </div>
      {/if}
    {:else if editPlatform === "discord"}
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
              <span class="aa-step-t">A window opens</span>
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
              {loginState === "opening" ? "Opening the window…" : "Waiting for you to sign in. The window is open."}
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
    {:else if editPlatform === "instagram"}
      <!-- Instagram signs in the way TikTok does: a window opens on its own login page and you sign in there,
           however you like. Nothing is typed by the app. A scripted login is what Instagram acts on, and the account here was suspended for one. -->
      {#if !adding}
        <div class="aa-field">
          <label for="ig-usr" class="mb-1 block text-xs font-medium text-muted">Username</label>
          <div class="relative">
            <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
              <Icon name="accounts" size={14} />
            </span>
            <input id="ig-usr" type="text" bind:value={fUser} onkeydown={enter} spellcheck="false"
                   autocomplete="off" placeholder="username" class="field w-full pl-8" />
          </div>
        </div>
      {/if}
      <!-- What happens when it signs in, lit as it does. -->
      <div class="aa-panel">
        <ol class="aa-steps" class:is-idle={loginState === "idle"}
            style="--at: {loginState === 'waiting' ? 1 : loginState === 'opening' ? 0.5 : 0}">
          <li class="aa-step" class:is-now={loginState === "opening"} class:is-done={loginState === "waiting"}>
            <span class="aa-step-i"><Icon name="globe" size={16} /></span>
            <span class="aa-step-t">A window opens</span>
          </li>
          <li class="aa-step" class:is-now={loginState === "waiting"}>
            <span class="aa-step-i"><Icon name="key" size={16} /></span>
            <span class="aa-step-t">You sign in</span>
          </li>
          <li class="aa-step">
            <span class="aa-step-i"><Icon name="check" size={16} /></span>
            <span class="aa-step-t">{adding ? "It is added" : "It is back in"}</span>
          </li>
        </ol>
        {#if loginState !== "idle"}
          <p class="aa-status">
            <span class="aa-spin" aria-hidden="true"></span>
            {loginState === "opening" ? "Opening the window…" : "Waiting for you to sign in. The window is open."}
          </p>
        {:else}
          <p class="aa-fine">
            <Icon name="eyeOff" size={12} />
            Sign in any way Instagram offers. Your password never reaches the app.
          </p>
        {/if}
        {#if igStep === "needs-code"}
          <!-- The one thing the app cannot make up: a code Instagram sent to the account, which a running account's
               own runner can ask for long after this window has gone. -->
          <div class="ig-code-ask">
            <label for="ig-code" class="text-[11.5px] font-semibold text-ink">Instagram sent a code</label>
            <p class="text-[11px] text-muted">Check the account's email or phone, and type it here.</p>
            <input id="ig-code" type="text" inputmode="numeric" bind:value={igCode} spellcheck="false"
                   autocomplete="one-time-code" maxlength="8" placeholder="123456"
                   class="field mt-1.5 w-28 text-center font-mono tracking-[0.2em]"
                   onkeydown={(e) => { if (e.key === "Enter") sendInstagramCode(); }} />
          </div>
        {/if}
      </div>
      {#if !adding}
        <!-- None of this is needed, and nothing waits for it: it is only what lets the account sign itself back in,
             months later, with nobody here. -->
        <div class="aa-field">
          <label for="ig-pwd" class="mb-1 block text-xs font-medium text-muted">
            Password <span class="text-faint">optional, to sign itself back in</span>
          </label>
          <div class="relative">
            <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
              <Icon name="key" size={14} />
            </span>
            <input id="ig-pwd" type={reveal ? "text" : "password"} bind:value={fPass} onkeydown={enter}
                   autocomplete="off" placeholder="leave blank to keep the current one"
                   class="field w-full pl-8 pr-9" />
            <button type="button" class="reveal" onclick={() => (reveal = !reveal)}
                    aria-label={reveal ? "Hide it" : "Show it"} title={reveal ? "Hide it" : "Show it"}>
              <Icon name={reveal ? "eyeOff" : "eye"} size={14} />
            </button>
          </div>
          <p class="mt-1 text-[11px] text-faint">
            Kept in config/.env on this machine and never sent back to the page.
          </p>
        </div>
        <div class="aa-field">
          <label for="ig-totp" class="mb-1 block text-xs font-medium text-muted">
            2FA key <span class="text-faint">optional</span>
          </label>
          <div class="relative">
            <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
              <Icon name="clock" size={14} />
            </span>
            <input id="ig-totp" type="text" bind:value={fTotp} onkeydown={enter} spellcheck="false"
                   autocomplete="off" placeholder="G54M E4E3 T37W 6IXH" class="field w-full pl-8 font-mono" />
          </div>
          {#if igShown}
            <!-- The code that key makes right now: check it against your own app and you know the key is right. -->
            <p class="ig-code-now">
              <span class="ig-code">{igShown.slice(0, 3)} {igShown.slice(3)}</span>
              <span class="ig-code-left" style="--left: {igLeft / 30}">{igLeft}s</span>
              <span class="text-faint">should match your authenticator app</span>
            </p>
          {:else if fTotp.trim()}
            <p class="mt-1 text-[11px] text-bad">That is not a 2FA key. It is the letters beside the QR code.</p>
          {:else}
            <p class="mt-1 text-[11px] text-faint">
              Only needed if 2FA is on and you want it to sign itself back in without you.
            </p>
          {/if}
        </div>
      {/if}
      {#if loginNote}
        <div class="login-note">
          <span class="mt-0.5 shrink-0"><Icon name="alert" size={14} /></span>
          <span class="min-w-0">{loginNote}</span>
        </div>
      {/if}
    {:else if editPlatform === "x"}
      <!-- X signs in the way TikTok does: a window opens on its own login page and you sign in there,
           however you like. Nothing is typed by the app. A scripted login is what X locks an account over, and it takes a person to undo. -->
      {#if !adding}
        <div class="aa-field">
          <label for="x-usr" class="mb-1 block text-xs font-medium text-muted">Handle</label>
          <div class="relative">
            <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
              <Icon name="accounts" size={14} />
            </span>
            <input id="x-usr" type="text" bind:value={fUser} onkeydown={enter} spellcheck="false"
                   autocomplete="off" placeholder="handle" class="field w-full pl-8" />
          </div>
        </div>
      {/if}
      <!-- What happens when it signs in, lit as it does. -->
      <div class="aa-panel">
        <ol class="aa-steps" class:is-idle={loginState === "idle"}
            style="--at: {loginState === 'waiting' ? 1 : loginState === 'opening' ? 0.5 : 0}">
          <li class="aa-step" class:is-now={loginState === "opening"} class:is-done={loginState === "waiting"}>
            <span class="aa-step-i"><Icon name="globe" size={16} /></span>
            <span class="aa-step-t">A window opens</span>
          </li>
          <li class="aa-step" class:is-now={loginState === "waiting"}>
            <span class="aa-step-i"><Icon name="key" size={16} /></span>
            <span class="aa-step-t">You sign in</span>
          </li>
          <li class="aa-step">
            <span class="aa-step-i"><Icon name="check" size={16} /></span>
            <span class="aa-step-t">{adding ? "It is added" : "It is back in"}</span>
          </li>
        </ol>
        {#if loginState !== "idle"}
          <p class="aa-status">
            <span class="aa-spin" aria-hidden="true"></span>
            {loginState === "opening" ? "Opening the window…" : "Waiting for you to sign in. The window is open."}
          </p>
        {:else}
          <p class="aa-fine">
            <Icon name="eyeOff" size={12} />
            Sign in any way X offers. Your password never reaches the app.
          </p>
        {/if}
        {#if igStep === "needs-code"}
          <!-- The one thing the app cannot make up: a code X sent to the account, which a running account's
               own runner can ask for long after this window has gone. -->
          <div class="ig-code-ask">
            <label for="x-code" class="text-[11.5px] font-semibold text-ink">X sent a code</label>
            <p class="text-[11px] text-muted">Check the account's email or phone, and type it here.</p>
            <input id="x-code" type="text" inputmode="numeric" bind:value={igCode} spellcheck="false"
                   autocomplete="one-time-code" maxlength="8" placeholder="123456"
                   class="field mt-1.5 w-28 text-center font-mono tracking-[0.2em]"
                   onkeydown={(e) => { if (e.key === "Enter") sendInstagramCode(); }} />
          </div>
        {/if}
      </div>
      {#if !adding}
        <!-- None of this is needed, and nothing waits for it: it is only what lets the account sign itself back in,
             months later, with nobody here. -->
        <div class="aa-field">
          <label for="x-email" class="mb-1 block text-xs font-medium text-muted">
            Email or phone on the account <span class="text-faint">optional</span>
          </label>
          <div class="relative">
            <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
              <Icon name="accounts" size={14} />
            </span>
            <input id="x-email" type="text" bind:value={fEmail} onkeydown={enter} spellcheck="false"
                   autocomplete="off" placeholder="name@example.com" class="field w-full pl-8" />
          </div>
          <p class="mt-1 text-[11px] text-faint">
            X asks for this when it does not like the look of a login it was not expecting.
          </p>
        </div>
        <div class="aa-field">
          <label for="x-pwd" class="mb-1 block text-xs font-medium text-muted">
            Password <span class="text-faint">optional, to sign itself back in</span>
          </label>
          <div class="relative">
            <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
              <Icon name="key" size={14} />
            </span>
            <input id="x-pwd" type={reveal ? "text" : "password"} bind:value={fPass} onkeydown={enter}
                   autocomplete="off" placeholder="leave blank to keep the current one"
                   class="field w-full pl-8 pr-9" />
            <button type="button" class="reveal" onclick={() => (reveal = !reveal)}
                    aria-label={reveal ? "Hide it" : "Show it"} title={reveal ? "Hide it" : "Show it"}>
              <Icon name={reveal ? "eyeOff" : "eye"} size={14} />
            </button>
          </div>
          <p class="mt-1 text-[11px] text-faint">
            Kept in config/.env on this machine and never sent back to the page.
          </p>
        </div>
        <div class="aa-field">
          <label for="x-totp" class="mb-1 block text-xs font-medium text-muted">
            2FA key <span class="text-faint">optional</span>
          </label>
          <div class="relative">
            <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
              <Icon name="clock" size={14} />
            </span>
            <input id="x-totp" type="text" bind:value={fTotp} onkeydown={enter} spellcheck="false"
                   autocomplete="off" placeholder="G54M E4E3 T37W 6IXH" class="field w-full pl-8 font-mono" />
          </div>
          {#if igShown}
            <!-- The code that key makes right now: check it against your own app and you know the key is right. -->
            <p class="ig-code-now">
              <span class="ig-code">{igShown.slice(0, 3)} {igShown.slice(3)}</span>
              <span class="ig-code-left" style="--left: {igLeft / 30}">{igLeft}s</span>
              <span class="text-faint">should match your authenticator app</span>
            </p>
          {:else if fTotp.trim()}
            <p class="mt-1 text-[11px] text-bad">That is not a 2FA key. It is the letters beside the QR code.</p>
          {:else}
            <p class="mt-1 text-[11px] text-faint">
              Only needed if 2FA is on and you want it to sign itself back in without you.
            </p>
          {/if}
        </div>
      {/if}
      {#if loginNote}
        <div class="login-note">
          <span class="mt-0.5 shrink-0"><Icon name="alert" size={14} /></span>
          <span class="min-w-0">{loginNote}</span>
        </div>
      {/if}
    {:else if editPlatform === "minecraft"}
      <!-- How it signs in comes first: it decides whether there is a name to type at all. A Microsoft account's
           name is Microsoft's, and comes from the sign-in. -->
      <div class="aa-field">
        <span class="mb-1 block text-xs font-medium text-muted">Signs in</span>
        <Segmented label="Signs in" bind:value={fAuth} options={[
          { id: "offline", label: "No account" },
          { id: "microsoft", label: "Microsoft" },
        ]} />
        <p class="mt-1 text-[11px] text-faint">
          {fAuth === "microsoft"
            ? "For real servers. It plays as your Minecraft name, which Microsoft gives when you sign in."
            : "For a LAN world, or a server with online mode off."}
        </p>
      </div>
      {#if fAuth === "offline"}
        <div class="aa-field">
          <label for="mc-name" class="mb-1 block text-xs font-medium text-muted">Its name in the game</label>
          <div class="relative">
            <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
              <Icon name="minecraft" size={14} />
            </span>
            <input id="mc-name" type="text" bind:value={fUser} onkeydown={enter} spellcheck="false" autocomplete="off"
                   maxlength="16" placeholder="Alicia" class="field w-full pl-8" />
          </div>
          {#if fUser.trim() && !mcNameOk}
            <p class="mt-1 text-[11px] text-bad">3 to 16 letters, digits or underscores. No spaces.</p>
          {:else}
            <p class="mt-1 text-[11px] text-faint">Any name. Nobody owns it on an offline server.</p>
          {/if}
        </div>
      {/if}
      <!-- Each account's own: two accounts can play on two servers. -->
      <div class="aa-field">
        <label for="mc-host" class="mb-1 block text-xs font-medium text-muted">Server</label>
        <div class="relative">
          <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
            <Icon name="globe" size={14} />
          </span>
          <input id="mc-host" type="text" bind:value={fHost} onkeydown={enter} spellcheck="false" autocomplete="off"
                 placeholder="play.example.net" class="field w-full pl-8 font-mono" disabled={mcSigning} />
        </div>
        <p class="mt-1 text-[11px] text-faint">This account's own. A LAN world shows its port when opened.</p>
      </div>
      <!-- A premium account's own skin, which Minecraft keeps: the same on every server. -->
      {#if !adding && fAuth === "microsoft"
           && slots.some((s) => s.platform === "minecraft" && s.index === editIndex && s.auth === "microsoft")}
        <McSkin index={editIndex} />
      {/if}
      {#if fAuth === "microsoft" && adding}
        <div class="aa-panel">
          <!-- The same three steps the other sign-ins show, lit as they happen. -->
          <ol class="aa-steps" class:is-idle={!mcSign.state}
              style="--at: {mcSign.state === 'code' ? 1 : mcSign.state === 'asking' ? 0.5 : 0}">
            <li class="aa-step" class:is-now={mcSign.state === "asking"} class:is-done={mcSign.state === "code"}>
              <span class="aa-step-i"><Icon name="key" size={16} /></span>
              <span class="aa-step-t">Microsoft gives a code</span>
            </li>
            <li class="aa-step" class:is-now={mcSign.state === "code"}>
              <span class="aa-step-i"><Icon name="globe" size={16} /></span>
              <span class="aa-step-t">You sign in</span>
            </li>
            <li class="aa-step">
              <span class="aa-step-i"><Icon name="check" size={16} /></span>
              <span class="aa-step-t">It is added</span>
            </li>
          </ol>
          {#if mcSign.state === "code"}
            <div class="mc-code-ask">
              <span class="mc-code" aria-label="The code">{mcSign.code}</span>
              <Button size="sm" onclick={() => { play("open"); openUrl(mcSign.link || mcSign.uri); }}>
                <Icon name="external" size={12} />Open microsoft.com/link
              </Button>
              <p class="aa-status">
                <span class="aa-spin" aria-hidden="true"></span>
                The code is already filled in there. Sign in, and it is added here by itself.
              </p>
            </div>
          {:else if mcSign.state === "asking"}
            <p class="aa-status"><span class="aa-spin" aria-hidden="true"></span>Asking Microsoft for a code…</p>
          {:else}
            <p class="aa-fine">
              <Icon name="eyeOff" size={12} />
              You sign in on Microsoft's own page. Your password never reaches the app.
            </p>
          {/if}
        </div>
      {/if}
    {:else if editPlatform === "telegram"}
      <!-- Telegram signs in by phone: a code to the account, and its two-step password where it has one. -->
      <div class="aa-field">
        <label for="tg-phone" class="mb-1 block text-xs font-medium text-muted">Its phone number</label>
        <div class="relative">
          <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
            <Icon name="phone" size={14} />
          </span>
          <input id="tg-phone" type="tel" bind:value={tgPhone} onkeydown={enter} spellcheck="false"
                 autocomplete="off" placeholder="+33 6 12 34 56 78" class="field w-full pl-8 font-mono"
                 disabled={!!tgStep} />
        </div>
        <p class="mt-1 text-[11px] text-faint">The account's own number, with its country code. A second number,
          not the one you use yourself.</p>
      </div>
      <div class="aa-field">
        <span class="mb-1 block text-xs font-medium text-muted">
          From my.telegram.org
          {#if tgPairKnown}<span class="text-faint">, kept from the first account</span>{/if}
        </span>
        <div class="flex gap-2">
          <input bind:value={tgApiId} placeholder="api_id" aria-label="api_id" spellcheck="false" autocomplete="off"
                 class="field w-28 font-mono" disabled={!!tgStep} />
          <input bind:value={tgApiHash} placeholder={tgPairKnown ? "••••  (unchanged)" : "api_hash"}
                 aria-label="api_hash" spellcheck="false"
                 autocomplete="off" class="field min-w-0 flex-1 font-mono" disabled={!!tgStep} />
        </div>
        <p class="mt-1 text-[11px] text-faint">
          {#if tgPairKnown}
            Already stored. Leave them as they are unless you made a new pair.
          {:else}
            Sign in at <button type="button" class="aa-link" onclick={() => openUrl("https://my.telegram.org")}>my.telegram.org</button>,
            then API development tools. The same pair works for every Telegram account here.
          {/if}
        </p>
      </div>
      <div class="aa-panel">
        <!-- The same three steps the other sign-ins show, lit as they happen. -->
        <ol class="aa-steps" class:is-idle={!tgStep && !tgBusy}
            style="--at: {tgStep === 'code' || tgStep === 'password' ? 1 : tgBusy ? 0.5 : 0}">
          <li class="aa-step" class:is-now={tgBusy && !tgStep}
              class:is-done={tgStep === "code" || tgStep === "password"}>
            <span class="aa-step-i"><Icon name="send" size={16} /></span>
            <span class="aa-step-t">Telegram sends a code</span>
          </li>
          <li class="aa-step" class:is-now={tgStep === "code" || tgStep === "password"}>
            <span class="aa-step-i"><Icon name="key" size={16} /></span>
            <span class="aa-step-t">You type it in</span>
          </li>
          <li class="aa-step">
            <span class="aa-step-i"><Icon name="check" size={16} /></span>
            <span class="aa-step-t">{adding ? "It is added" : "It is back in"}</span>
          </li>
        </ol>
        {#if tgStep === "code"}
          <div class="ig-code-ask">
            <label for="tg-code" class="text-[11.5px] font-semibold text-ink">Telegram sent a code</label>
            <p class="text-[11px] text-muted">{tgDetail || "It is in the Telegram app, or in a text message."}</p>
            <input id="tg-code" type="text" inputmode="numeric" bind:value={tgCode} spellcheck="false"
                   autocomplete="one-time-code" maxlength="8" placeholder="12345"
                   class="field mt-1.5 w-28 text-center font-mono tracking-[0.2em]"
                   onkeydown={(e) => { if (e.key === "Enter") sendTelegramCode(); }} />
          </div>
        {:else if tgStep === "password"}
          <div class="ig-code-ask">
            <label for="tg-pw" class="text-[11.5px] font-semibold text-ink">Its two-step password</label>
            <p class="text-[11px] text-muted">{tgDetail || "This account has two-step verification."}</p>
            <input id="tg-pw" type="password" bind:value={tgPassword} autocomplete="off"
                   class="field mt-1.5 w-full" placeholder="password"
                   onkeydown={(e) => { if (e.key === "Enter") sendTelegramPassword(); }} />
            <p class="mt-1 text-[11px] text-faint">It is not kept: it is only used to finish signing in.</p>
          </div>
        {:else if tgBusy}
          <p class="aa-status">
            <span class="aa-spin" aria-hidden="true"></span>
            {tgDetail || "Asking Telegram for a code…"}
          </p>
        {:else}
          <p class="aa-fine">
            <Icon name="eyeOff" size={12} />
            The login is kept in config/.env on this computer. Nothing is stored until Telegram lets it in.
          </p>
        {/if}
      </div>
    {:else if editPlatform === "imessage"}
      <div class="aa-field">
        <span class="mb-1 block text-xs font-medium text-muted">How it reaches iMessage</span>
        <Segmented label="How it reaches iMessage" bind:value={imVia} options={[
          { id: "phone", label: "iPhone or iPad", icon: "phone", tone: "#30d158" },
          { id: "mac", label: "A Mac", icon: "monitor", tone: "#0a84ff" },
        ]} />
      </div>
      {#if imVia === "phone"}
        <!-- No Mac: the phone itself passes each message here with a Shortcuts automation, and sends back the
             reply. Nothing to type here; the shortcut's address is made with the account. -->
        <div class="aa-panel im-phone">
          <p class="im-phone-lead">
            <Icon name="phone" size={14} />
            <span>A Shortcuts automation on your iPhone passes each message here and sends back the reply.</span>
          </p>
          <p class="aa-fine">
            <Icon name="info" size={12} />
            {adding ? "Once added, Settings, iMessage, Setup shows the four steps on the phone."
                    : "Its steps are in Settings, iMessage, Setup."}
            It answers; sending first, typing dots and tapbacks need a Mac.
          </p>
          {#if !adding}
            <label class="im-renew">
              <Toggle size="sm" bind:checked={imRenew} />
              <span>New address for the shortcut <span class="text-faint">(the old one stops working)</span></span>
            </label>
          {/if}
        </div>
      {:else}
      <!-- BlueBubbles' address and password. The Apple account itself stays on the Mac. -->
      <div class="aa-field">
        <label for="im-server" class="mb-1 block text-xs font-medium text-muted">BlueBubbles address</label>
        <div class="relative">
          <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
            <Icon name="globe" size={14} />
          </span>
          <input id="im-server" type="text" bind:value={fServer} onkeydown={enter} spellcheck="false"
                 autocomplete="off" placeholder="https://xyz.trycloudflare.com" class="field w-full pl-8 font-mono"
                 oninput={() => (imTest = null)} />
        </div>
        <p class="mt-1 text-[11px] text-faint">Shown in BlueBubbles Server on the Mac. Its own address works on your network.</p>
      </div>
      <div class="aa-field">
        <label for="im-pwd" class="mb-1 block text-xs font-medium text-muted">
          Password {#if !adding}<span class="text-faint">, leave blank to keep the current one</span>{/if}
        </label>
        <div class="relative">
          <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
            <Icon name="key" size={14} />
          </span>
          <input id="im-pwd" type={reveal ? "text" : "password"} bind:value={fPass} onkeydown={enter} autocomplete="off"
                 placeholder={adding ? "The one set in BlueBubbles" : "••••••••  (unchanged)"}
                 class="field w-full pl-8 pr-9" oninput={() => (imTest = null)} />
          <button type="button" class="reveal" onclick={() => (reveal = !reveal)}
                  aria-label={reveal ? "Hide it" : "Show it"} title={reveal ? "Hide it" : "Show it"}>
            <Icon name={reveal ? "eyeOff" : "eye"} size={14} />
          </button>
        </div>
      </div>
      <div class="aa-panel im-test">
        <div class="flex items-center gap-2">
          <Button size="sm" kind="ghost" onclick={testImessage} loading={imTesting}
                  disabled={!fServer.trim() || (adding && !fPass)}>
            {#if !imTesting}<Icon name="refresh" size={12} />{/if}Test it
          </Button>
          {#if imTest?.ok}
            <span class="im-ok"><Icon name="check" size={13} />Connected{imTest.account ? ` as ${imTest.account}` : ""}</span>
          {:else if imTest}
            <span class="im-bad"><Icon name="alert" size={13} />{imTest.reason}</span>
          {/if}
        </div>
        {#if imTest?.ok}
          <p class="mt-1.5 text-[11px] text-faint">
            macOS {imTest.macos || "?"}, BlueBubbles {imTest.bluebubbles || "?"}.
            {imTest.private_api && imTest.helper ? "Private API on: typing dots, read receipts and tapbacks."
              : "Private API off: it texts, without typing dots, read receipts or tapbacks."}
          </p>
          {#if imTest.warning}<p class="mt-1 text-[11px] text-warn">{imTest.warning}</p>{/if}
        {:else}
          <p class="aa-fine">
            <Icon name="info" size={12} />
            Needs a Mac signed in to iMessage, running BlueBubbles Server (free, bluebubbles.app).
          </p>
        {/if}
      </div>
      {/if}
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

    <!-- The proxy folds away: most accounts do without one, and it made the dialog look like a form to fill in before
         anything else. -->
    {#if hasProxy}
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

    {#if adding && !blocked}
      <label class="aa-start">
        <Toggle size="sm" bind:checked={startNow} name="Start it as soon as it is added" />
        <span>Start it as soon as it is added</span>
      </label>
    {/if}

    <div class="aa-foot">
      <Button kind="ghost" onclick={addAction.leaveRun}>{addAction.leave}</Button>
      <Button onclick={addAction.run} loading={addAction.busy} disabled={addAction.off}>
        {#if !addAction.busy}<Icon name={addAction.icon} size={13} />{/if}{addAction.label}
      </Button>
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

<!-- ── A TikTok account's LIVE ────────────────────────────────────────────── -->
<Modal open={!!watchFor} wide title={watchFor ? `What ${nameOf(watchFor)} sees` : ""} onclose={() => (watchFor = null)}>
  {#if watchFor}
    <WatchView account={watchFor.id} name={nameOf(watchFor)} />
  {/if}
</Modal>

<Modal open={!!liveFor} title={liveFor ? `LIVE, ${nameOf(liveFor)}` : ""} onclose={() => (liveFor = null)}>
  {#if liveFor}
    <LiveView account={liveFor.id} name={nameOf(liveFor)}
              onsettings={() => { liveFor = null; openSettings("tiktok/live"); }} />
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

  /* The Add account menu: it unrolls out of its button (app.css .unroll), 6px under it, rows close together. */
  .add-menu {
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    z-index: 30;
    min-width: 12rem;
    width: max-content;
    padding: 5px;
    border-radius: 14px;
    box-shadow: 0 22px 50px -20px rgb(0 0 0 / 0.75), inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 22%, transparent),
                0 0 0 1px rgb(0 0 0 / 0.25), 0 0 30px -12px color-mix(in srgb, var(--color-accent) 45%, transparent);
  }
  /* One highlight for the whole menu, gliding to the row pointed at, as Select's does. */
  .add-glide {
    position: absolute;
    top: 0;
    left: 5px;
    right: 5px;
    border-radius: 9px;
    pointer-events: none;
    opacity: 0;
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 20%, transparent);
    transition: transform 0.26s var(--spring), height 0.2s var(--swift), opacity 0.15s ease;
  }
  .add-glide.is-on { opacity: 1; }
  .add-glide.is-snap { transition: opacity 0.15s ease; }
  .add-item {
    position: relative;
    display: flex;
    width: 100%;
    align-items: center;
    gap: 9px;
    padding: 5px 10px 5px 5px;
    border-radius: 9px;
    font-size: 13px;
    font-weight: 500;
    line-height: 1.3;
    color: var(--color-ink);
    text-align: left;
  }
  .add-name { transition: transform 0.2s var(--swift); }
  .add-item:hover .add-name,
  .add-item:focus-visible .add-name { transform: translateX(2px); }
  /* Settings' social marks (app.css), at the height of a row. */
  .add-mark.settings-mark {
    width: 20px;
    height: 20px;
    border-radius: 6px;
  }
  :global(:root[data-motion="off"]) .add-glide,
  :global(:root[data-motion="off"]) .add-name { transition: none; }

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
  /* As many to a row as fit with their names whole: three across in a wide window, two in a narrow one. A fixed three
     squeezed "Snapchat" and "Instagram" until their logos were dots beside them. */
  .add-platforms {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(6.9rem, 1fr));
    gap: 8px;
  }
  .add-platform {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    white-space: nowrap;
    padding: 8px 10px;
    border-radius: 11px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--color-ink);
    /* Tinted with the theme like every button (app.css, "Buttons with depth"), pointed at too: no outline of its
       own, which read as an old bordered button. */
    transition: transform 0.2s var(--swift);
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
  .ig-code-now { margin-top: 0.3rem; display: flex; align-items: center; gap: 0.5rem; font-size: 11px; }
  .ig-code { font-family: var(--font-mono, ui-monospace), monospace; font-size: 13px; font-weight: 600;
             letter-spacing: 0.12em; color: var(--color-ink); }
  /* The seconds left, draining as they do: a ring that empties rather than a number alone. */
  .ig-code-left { display: grid; place-items: center; width: 1.45rem; height: 1.45rem; border-radius: 999px;
                  font-size: 9.5px; font-variant-numeric: tabular-nums; color: var(--color-muted);
                  background: conic-gradient(var(--color-accent) calc(var(--left) * 360deg), rgb(255 255 255 / 0.07) 0); }
  .mc-code-ask { margin-top: 0.7rem; display: grid; justify-items: center; gap: 0.55rem;
                 border-top: 1px solid rgb(255 255 255 / 0.07); padding-top: 0.8rem; }
  .mc-code {
    font-family: var(--font-mono, ui-monospace, monospace); font-size: 1.55rem; font-weight: 700;
    letter-spacing: 0.22em; color: var(--color-ink); padding: 0.35rem 0.8rem; border-radius: 12px;
    background: color-mix(in srgb, #5b8731 16%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, #7cbd4a 38%, transparent);
    user-select: all;
  }
  .ig-code-ask { margin-top: 0.7rem; display: grid; gap: 0.2rem; border-top: 1px solid rgb(255 255 255 / 0.07);
                 padding-top: 0.7rem; }
  .aa[data-platform="instagram"] .aa-hero { --brand: #e1306c; --wash: 18%; }
  .aa[data-platform="instagram"] .aa-mark { background: #16090f; box-shadow: 0 12px 28px -10px rgb(225 48 108 / 0.7),
                                            inset 0 0 0 1px rgb(255 255 255 / 0.1); }
  .aa[data-platform="instagram"] .aa-mark svg path { stroke: none; }
  /* X is black and white: the tile is the black, the mark the white. */
  .aa[data-platform="x"] .aa-hero { --brand: #e7e9ea; --wash: 10%; }
  .aa[data-platform="x"] .aa-mark { background: linear-gradient(145deg, #1c1f24, #000);
                                    box-shadow: 0 12px 28px -10px rgb(0 0 0 / 0.8),
                                                inset 0 0 0 1px rgb(255 255 255 / 0.14); }
  .aa[data-platform="x"] .aa-mark svg path { fill: #fff; stroke: none; }
  /* WhatsApp: its own green, with the bubble in white on it. */
  .aa[data-platform="whatsapp"] .aa-hero { --brand: #25d366; --wash: 18%; }
  .aa[data-platform="whatsapp"] .aa-mark { background: linear-gradient(145deg, #3ae07a, #15a84c);
                                           box-shadow: 0 12px 28px -10px rgb(37 211 102 / 0.7),
                                                       inset 0 0 0 1px rgb(255 255 255 / 0.16); }
  .aa[data-platform="whatsapp"] .aa-mark svg path { fill: #fff; stroke: none; }
  /* The code to scan, on a white plate, beside what to do with it. */
  .wa-qr-ask { display: flex; align-items: center; gap: 12px; margin-top: 10px; }
  .wa-qr { width: 116px; height: 116px; flex-shrink: 0; padding: 7px; border-radius: 12px; background: #fff;
           box-shadow: 0 10px 24px -12px rgb(0 0 0 / 0.7); }
  .wa-qr :global(svg) { display: block; width: 100%; height: 100%; }

  /* Reddit: its own orange, with the snoo in white on it. */
  .aa[data-platform="reddit"] .aa-hero { --brand: #ff4500; --wash: 18%; }
  .aa[data-platform="reddit"] .aa-mark { background: linear-gradient(145deg, #ff6a33, #e03d00);
                                         box-shadow: 0 12px 28px -10px rgb(255 69 0 / 0.7),
                                                     inset 0 0 0 1px rgb(255 255 255 / 0.16); }
  .aa[data-platform="reddit"] .aa-mark svg path { fill: #fff; stroke: none; }
  .aa[data-platform="minecraft"] .aa-hero { --brand: #5b8731; --wash: 18%; }
  .aa[data-platform="minecraft"] .aa-mark { background: linear-gradient(145deg, #23301c, #141b10);
                                            box-shadow: 0 12px 28px -10px rgb(106 168 58 / 0.65),
                                            inset 0 0 0 1px rgb(255 255 255 / 0.1); }
  .aa[data-platform="minecraft"] .aa-mark svg path { fill: #7cbd4a; stroke: none; }
  /* iMessage: a white bubble on Messages' green, lit from above, as the app itself is drawn. */
  .aa[data-platform="imessage"] .aa-hero { --brand: #0a84ff; --wash: 18%; }
  .aa[data-platform="imessage"] .aa-mark { background: linear-gradient(180deg, #5df67a, #0cbd2a);
                                           box-shadow: 0 12px 28px -10px rgb(12 189 42 / 0.6),
                                           inset 0 1px 0 rgb(255 255 255 / 0.35), inset 0 0 0 1px rgb(255 255 255 / 0.12); }
  .aa[data-platform="imessage"] .aa-mark svg path { fill: #fff; stroke: none; }
  .im-test { display: grid; gap: 0.15rem; }
  .im-phone { display: grid; gap: 0.5rem; }
  .im-phone-lead { display: flex; align-items: flex-start; gap: 0.5rem; font-size: 12.5px; line-height: 1.45;
                   color: var(--color-ink); }
  .im-phone-lead :global(svg) { margin-top: 2px; flex-shrink: 0; color: #30d158; }
  .im-renew { display: flex; align-items: center; gap: 0.6rem; font-size: 12px; color: var(--color-muted); cursor: pointer; }
  .im-ok { display: inline-flex; align-items: center; gap: 0.3rem; font-size: 11.5px; font-weight: 600;
           color: var(--color-good); }
  .im-bad { display: inline-flex; align-items: flex-start; gap: 0.3rem; font-size: 11.5px; color: var(--color-bad);
            min-width: 0; }
  .aa[data-platform="tiktok"] .aa-hero { --brand: #fe2c55; --wash: 18%; }
  .aa[data-platform="tiktok"] .aa-mark { background: #010101; box-shadow: 0 12px 28px -10px rgb(254 44 85 / 0.7),
                                         inset 0 0 0 1px rgb(255 255 255 / 0.12); }
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
  .aa[data-platform="tiktok"] .aa-mark svg { filter: drop-shadow(-1.2px -1px 0 #25f4ee) drop-shadow(1.2px 1px 0 #fe2c55); }
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
