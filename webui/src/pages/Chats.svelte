<script lang="ts">
  /**
   * Chats, as an inbox.
   *
   * This was a column of identical cards, one per person, each with a message
   * and a status line, which read as a log rather than as conversations. It is
   * laid out like a messaging app now: who is waiting down the left, grouped by
   * what is happening to them (being answered, needs you, bot off), and the
   * selected conversation on the right as the conversation itself - both sides,
   * as chat bubbles, read from Discord - with a live tracker of where the reply
   * is (waiting, writing, pacing, typing, sent) and the things you can do.
   *
   * Everything is live: new messages, each step of a reply and the reply
   * itself arrive as events (lib/chats.ts) and land in place.
   */
  import { onMount, tick, untrack } from "svelte";
  import { play as playSound } from "../lib/uisound";
  import { chime, domino } from "../lib/domino";
  import { subscribeEvents } from "../lib/logsocket";
  import { get } from "svelte/store";
  import { flip } from "svelte/animate";
  import { fade } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { api } from "../lib/api";
  import { HOUR_MINUTE, fmtDate, FULL_WHEN, whenSent } from "../lib/fmt";
  import { STEPS, countdown as countdownFor, progress as progressOf, statusOf as statusFor, type Phase, type Status } from "../lib/chatstatus";
  import { toast, motionEnabled } from "../lib/stores";
  import { resource } from "../lib/resource";
  import {
    chatAccounts, chatCache, chatsFocus, loadChatAccounts, refreshChats,
    replying as replyingStore, replyingAll as replyingAllStore, sendReply, sendReplyAll, stopReplyAll,
    replyAllProgress, cancelReply, toggleIgnore, setIgnored, loadMessage, conversations, convKey, loadConversation,
    sendOwnMessage, typingNow, callsNow, drafts, setDraft, loadDrafts, stagedFiles, loadEarlier, joinConversation,
    reactTo, ALL_CHATS, chatsView, waitingByAccount,
    type ChatUser, type ConvMessage, type StagedFile, type Reaction, type ReplyTo, type Gift,
  } from "../lib/chats";
  import ReactPicker from "../lib/components/ReactPicker.svelte";
  import { fold, highlighted, splitWords } from "../lib/chatsearch";
  import { discordInline } from "../lib/discordmd";
  import { saveTextFile } from "../lib/window";
  import ChatTools from "../lib/components/ChatTools.svelte";
  import ServerTree from "../lib/components/ServerTree.svelte";
  import Badge from "../lib/components/Badge.svelte";
  import Button from "../lib/components/Button.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import UserChip from "../lib/components/UserChip.svelte";
  import MessageBody from "../lib/components/MessageBody.svelte";
  import Avatar from "../lib/components/Avatar.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import { mentionNames, resolveMention } from "../lib/mentions";
  import { platformOf, platformName, platformIcon } from "../lib/platforms";
  import { menu as contextMenu, copyText, openMenu, type MenuEntry } from "../lib/contextmenu";
  import { fillHeight } from "../lib/fillheight";

  type Account = {
    id: string;
    platform: string;
    account: number | null;
    username?: string;
    display_name?: string;
    avatar?: string;
    state?: string;
  };

  let target = $state("");
  let loadError = $state("");

  // One clock for every countdown on the page.
  let now = $state(Date.now() / 1000);

  // ── Friend requests ────────────────────────────────────────────────────
  // The background loop accepts them over hours on purpose, to not look like a
  // script; these are for when you are watching one arrive and want it in.
  type FriendRequest = {
    id: string;
    username: string;
    display_name?: string;
    avatar?: string;
    incoming: boolean;
    /** Unix seconds when the bot will accept it on its own, if scheduled. */
    accept_at?: number | null;
  };
  let requests = $state<FriendRequest[]>([]);
  let friendsSupported = $state(true);
  let friendBusy = $state<Record<string, boolean>>({});
  let friendsError = $state("");
  let friendsLoading = $state(false);
  const incoming = $derived(requests.filter((r) => r.incoming));

  // ── Everyone already answered ───────────────────────────────────────────
  type Past = {
    id: string; name: string; username?: string; avatar?: string;
    messages: number; last_ts?: number;
  };
  // Per account: a Snapchat or TikTok account's are its own chats, not the Discord ones. The account is fixed when its
  // list is made: the list outlives this page, and fetching by whatever `target` was later filled one account's list
  // with another's (the page that made it kept its own `target`, the account it was left on).
  function pastOf(t: string) {
    return resource(`chatArchive:${t}`, () => api.chatArchive(100, t), { conversations: [] as Past[] });
  }
  let pastBy = $state<Record<string, Past[]>>({});
  let showPast = $state(false);

  // ── Replies in flight ──────────────────────────────────────────────────
  // Held in the store, so a reply that takes two minutes still shows as
  // running after leaving the tab and coming back.
  const replying = $derived($replyingStore);

  const accounts = $derived($chatAccounts);

  // ── All chats ──────────────────────────────────────────────────────────
  // `view` is what the list shows: one account, or ALL_CHATS, every account's waiting list in one. `target` stays what
  // it always was, the account the open conversation and everything done to it belong to. In All chats it follows
  // whoever is opened, so the conversation, sending, reactions and the tools work exactly as they do on one account.
  let view = $state("");
  const allView = $derived(view === ALL_CHATS && accounts.length > 1);

  /**
   * Who Reply to all would answer. On one account, that account; in All chats every account with somebody waiting,
   * each answered by its own run, since each has its own pace and its own Stop.
   */
  const replyTargets = $derived(
    allView ? accounts.filter((a) => ($chatCache[a.id]?.users ?? []).some((u) => !u.ignored)).map((a) => a.id)
            : target ? [target] : [],
  );
  const replyingAll = $derived(replyTargets.some((t) => !!$replyingAllStore[t]));
  /** The runs added up, so the button counts them all rather than one account's. */
  const allProgress = $derived.by(() => {
    const parts = replyTargets.map((t) => $replyAllProgress[t]).filter(Boolean);
    if (!parts.length) return undefined;
    return { done: parts.reduce((n, p) => n + p.done, 0), total: parts.reduce((n, p) => n + p.total, 0),
             stopping: parts.some((p) => p.stopping) };
  });
  const busy = $derived(replyingAll);
  /** A row, with the account it came from: in All chats that is not always the one open. */
  type Row = ChatUser & { acc?: string };
  const accOf = (u: Row): string => u.acc ?? target;
  /** The same person can be waiting on two accounts at once, so a row is told apart by both. */
  const keyOf = (u: Row): string => `${accOf(u)}:${u.id}`;
  const accountOf = (id: string) => accounts.find((a) => a.id === id);
  /** The platform a row is on: in All chats, its own account's, not the open one's. */
  const platOfRow = (u: Row) => platformOf(accountOf(accOf(u))?.platform);
  /** The accounts that can answer: asking a stopped one only waits out its timeout (see startChatPrefetch). */
  const answering = (list: { id: string; state?: string }[]) => list.filter((a) => !a.state || a.state === "running");

  const entry = $derived($chatCache[target] ?? { users: [], fetched: 0, loading: false, error: "" });
  const users = $derived<Row[]>(
    allView
      ? accounts.flatMap((a) => ($chatCache[a.id]?.users ?? []).map((u) => ({ ...u, acc: a.id })))
      : entry.users,
  );
  const loading = $derived(
    !accounts.length
    || (allView
      ? accounts.every((a) => !$chatCache[a.id]?.fetched) && accounts.some((a) => !!$chatCache[a.id]?.loading)
      : !entry.fetched && entry.loading),
  );
  const refreshing = $derived(
    allView
      ? accounts.some((a) => !!$chatCache[a.id]?.loading && ($chatCache[a.id]?.fetched ?? 0) > 0)
      : entry.loading && entry.fetched > 0,
  );
  const current = $derived(accounts.find((a) => a.id === target));
  const unread = $derived(users.reduce((n, u) => n + (u.count || 0), 0));
  // The platform of the account shown (lib/platforms.ts). isSnap: a browser account, Snapchat's or TikTok's: pictures
  // only, its own few reactions, no user ids, its people known by chat ids.
  const plat = $derived(platformOf(current?.platform));
  const isSnap = $derived(plat.browser);

  /** Whose archives to read: the open account's, or in All chats every one of them. */
  const pastTargets = $derived(allView ? accounts.map((a) => a.id) : target ? [target] : []);
  $effect(() => {
    const targets = pastTargets;
    // Untracked: a store calls back at once, as it is subscribed to and as refresh() marks it loading, so pastBy was
    // read and written inside this effect, which ran it again, forever. Svelte stopped it with an error and the whole
    // panel stopped changing pages (2026-10-31: "Accounts does nothing").
    const stops = untrack(() => targets.map((t) => {
      const r = pastOf(t);
      const stop = r.subscribe((s) => {
        pastBy = { ...pastBy, [t]: s.data.conversations ?? [] };
      });
      r.refresh({ maxAge: 30000, quiet: true });
      return stop;
    }));
    return () => stops.forEach((s) => s());
  });
  /** One account's, flat; in All chats all of them, each conversation carrying the account it belongs to. */
  const pastList = $derived<Past[]>(
    allView
      ? pastTargets.flatMap((t) => (pastBy[t] ?? []).map((c) => ({ ...c, acc: t })))
      : pastBy[target] ?? [],
  );

  /**
   * Anyone still waiting is in the list above, so they are not history yet. Nor is anyone ignored.
   *
   * In All chats these come from every account at once, so a conversation is only "still waiting" when it is
   * waiting *on its own account*: the same id can be a stranger on one and someone answered on another.
   */
  const archived = $derived(
    pastList.filter((c: Past) => !users.some((u) => u.id === c.id && (!allView || accOf(u) === pastAcc(c)))
                                 && !ignoredIds.has(c.id)),
  );
  /** Which account an answered conversation belongs to. */
  const pastAcc = (c: Past) => (c as Past & { acc?: string }).acc ?? target;

  onMount(() => {
    void start();
    // What was being typed to whom, from before the app last closed.
    void loadDrafts();
    const clock = setInterval(() => (now = Date.now() / 1000), 1000);
    // The list is live (see startChatLive); this slower pass only catches what
    // no event describes, like messages that arrived while the bot was off.
    const t = setInterval(() => {
      if (document.hidden) return;
      if (allView) {
        for (const a of answering(accounts)) refreshChats(a.id, { maxAge: 30000, quiet: true });
        return;
      }
      refreshChats(target, { maxAge: 30000, quiet: true });
      loadFriends();
    }, 45000);
    return () => {
      clearInterval(t);
      clearInterval(clock);
    };
  });

  async function start() {
    try {
      const list = accounts.length ? accounts : await loadChatAccounts();
      const want = get(chatsFocus);
      // Back where it was left: one account, or All chats. An account another page asked for wins over both.
      const was = get(chatsView);
      if (want) {
        chatsFocus.set("");
        if (list.some((a) => a.id === want)) target = want;
      } else if (was === ALL_CHATS && list.length > 1) {
        view = ALL_CHATS;
      } else if (was && list.some((a) => a.id === was)) {
        target = was;
      }
      if (list.length && !target) target = list[0].id;
      if (!view) view = target;
      await Promise.all([
        view === ALL_CHATS
          ? Promise.all(answering(list).map((a) => refreshChats(a.id, { maxAge: 10000, quiet: true })))
          : refreshChats(target, { maxAge: 10000 }),
        loadFriends(),
      ]);
    } catch (e: any) {
      loadError = e?.message || "Could not load";
    }
  }
  // Remembered for the next visit: the page is rebuilt every time the tab is opened.
  $effect(() => {
    if (view) chatsView.set(view);
  });

  async function loadFriends() {
    if (!target) return;
    friendsLoading = true;
    try {
      const data = await api.friends(target);
      requests = data.requests || [];
      friendsSupported = data.supported !== false;
      friendsError = "";
    } catch (e: any) {
      friendsError = e?.status === 504
        ? "The account did not answer. It may be stopped or busy."
        : e?.message || "Could not read friend requests";
    } finally {
      friendsLoading = false;
    }
  }

  // ── Adding a friend, by username ───────────────────────────────────────
  let addOpen = $state(false);
  let addName = $state("");
  /** iMessage's first message to someone new: what starts the conversation. */
  let addText = $state("");
  let adding = $state(false);
  let addBox: HTMLInputElement | null = $state(null);
  async function toggleAdd() {
    addOpen = !addOpen;
    if (!addOpen) return;
    playSound("open");
    await tick();
    addBox?.focus();
  }
  $effect(() => {
    if (!addOpen) return;
    const off = (e: PointerEvent) => {
      if (!(e.target as Element | null)?.closest?.("[data-add-friend]")) addOpen = false;
    };
    const t = setTimeout(() => window.addEventListener("pointerdown", off, true), 0);
    return () => {
      clearTimeout(t);
      window.removeEventListener("pointerdown", off, true);
    };
  });
  async function addFriend() {
    const imsg = plat.id === "imessage";
    // iMessage: a phone number as people type one ("+33 6 12 34 56 78"), sent as its digits; an email as it is.
    const name = imsg
      ? (addName.includes("@") ? addName.trim() : addName.replace(/[\s().-]/g, ""))
      : addName.trim().replace(/^@/, "");
    if (!name || adding || (imsg && !addText.trim())) return;
    adding = true;
    try {
      const r = await api.friendAdd(name, target, imsg ? addText.trim() : "");
      if (r?.ok) {
        toast(plat.id === "tiktok" ? `Following ${name} on TikTok.`
              : plat.id === "instagram" ? `Following ${name} on Instagram.`
              : imsg ? `Texted ${name}${r.service === "SMS" ? ", as a text message (no iMessage there)" : ""}.`
              : isSnap ? `Added ${name} on Snapchat.` : `Friend request sent to ${name}.`, "ok");
        addName = "";
        addText = "";
        addOpen = false;
      } else {
        toast(r?.reason || `${plat.name} did not take it`, "err");
      }
    } catch (e: any) {
      toast(e?.status === 504 ? "The account did not answer, it may be stopped" : e?.message || "Could not add them", "err");
    }
    adding = false;
  }

  // ── Nitro gifts, in Discord DMs ──────────────────────────────────────────
  /** One nobody can take any more: used, run out, or gone from Discord. */
  const GIFT_GONE = new Set(["taken", "expired", "gone"]);
  let giftBusy = $state("");

  function giftSays(g: Gift): string {
    if (g.state === "accepted") return "Accepted";
    if (g.state === "taken") return "Already used";
    if (g.state === "expired") return "Ran out";
    if (g.state === "gone") return "Not there any more";
    return g.reason || "Waiting for you";
  }

  async function takeGift(m: ConvMessage) {
    if (giftBusy || !m.gift?.code) return;
    giftBusy = m.mid ?? "";
    playSound("tap");
    try {
      const r: any = await api.giftAccept(m.gift.code, target, m.mid ?? "", selected?.id ?? "");
      playSound(r?.ok ? "ok" : "err");
      toast(r?.ok ? `Took ${r.what && r.what !== "a gift" ? r.what : "the gift"}.`
                  : r?.reason || "Discord would not take it", r?.ok ? "ok" : "err");
    } catch (e: any) {
      playSound("err");
      toast(e?.status === 504 ? "The account did not answer, it may be stopped"
            : e?.message || "Could not take it", "err");
    }
    giftBusy = "";
  }

  async function answerRequest(r: FriendRequest, action: "accept" | "decline") {
    friendBusy[r.id] = true;
    try {
      const res = await api.friendAction(action, r.id, target);
      if (res?.ok) {
        requests = requests.filter((x) => x.id !== r.id);
        toast(`${action === "accept" ? "Accepted" : "Declined"} ${r.display_name || r.username}.`, "ok");
      } else {
        toast(res?.reason || `${plat.name} refused that`, "err");
      }
    } catch (e: any) {
      toast(e.message, "err");
    }
    friendBusy[r.id] = false;
  }

  // ── The account picker ─────────────────────────────────────────────────
  function who(a: Account): string {
    return a.display_name || a.username || slot(a);
  }
  function slot(a: Account): string {
    const platform = platformName(a.platform);
    return `${platform}${a.account ? ` #${a.account}` : ""}`;
  }
  const named = (a: Account) => who(a) !== slot(a);
  const multiple = $derived(accounts.length > 1);
  let picking = $state(false);

  function choose(id: string) {
    picking = false;
    if (id === ALL_CHATS) {
      if (!allView) showAll();
      return;
    }
    if (id !== target || allView) switchTarget(id);
  }
  /** Every account's waiting chats in one list. */
  async function showAll() {
    view = ALL_CHATS;
    failedReplies = new Set();
    selectedId = "";
    older = null;
    showDetail = false;
    await Promise.all(answering(accounts).map((a) => refreshChats(a.id, { maxAge: 10000, quiet: true })));
  }
  /** Waiting on a reply, per account, from what is cached (lib/chats.ts). */
  const waitingOn = (id: string) => $waitingByAccount[id] ?? 0;
  /** Everyone waiting everywhere, for All chats in the picker. */
  const waitingAll = $derived(accounts.reduce((n, a) => n + waitingOn(a.id), 0));
  /** Waiting on the accounts not on screen: the dot on the closed picker, so they are not missed. */
  const waitingElsewhere = $derived(allView ? 0 : accounts.reduce((n, a) => n + (a.id === target ? 0 : waitingOn(a.id)), 0));
  function dismiss(event: MouseEvent) {
    const el = event.target as HTMLElement;
    if (picking && !el.closest?.("[data-account-picker]")) picking = false;
    if (ignoredOpen && !el.closest?.("[data-ignored-panel]")) ignoredOpen = false;
  }
  async function switchTarget(id: string) {
    target = id;
    view = id;
    failedReplies = new Set();
    selectedId = "";
    older = null;
    loadFriends();
    await refreshChats(id, { maxAge: 10000 });
  }

  // ── Times ──────────────────────────────────────────────────────────────
  const countdown = (atTs?: number | null): string => countdownFor(atTs, now);
  const at = (ts?: number | null) => (ts ? fmtDate(ts * 1000, HOUR_MINUTE) : "");
  function ago(ts?: number): string {
    if (!ts) return "now";
    const secs = Math.max(0, now - ts);
    if (secs < 90) return "now";
    const mins = Math.round(secs / 60);
    if (mins < 60) return `${mins}m`;
    const hours = Math.round(mins / 60);
    if (hours < 24) return `${hours}h`;
    return `${Math.round(hours / 24)}d`;
  }
  const offline = (ts?: number) => !!ts && now - ts > 3600;

  // ── Where each reply is ────────────────────────────────────────────────
  // The words and stages live in lib/chatstatus.ts, shared with Big Picture Mode.

  // Rows a reply-to-all could not answer this run, so they read as "tried, did
  // not go" rather than untouched. Cleared when the account changes.
  let failedReplies = $state<Set<string>>(new Set());

  // Paused is per account, so a row in All chats goes by its own.
  const statusOf = (u: Row): Status =>
    statusFor(u, { now, paused: ($chatCache[accOf(u)] ?? entry).paused, failed: failedReplies });
  /** How far through its wait a countdown is, 0 to 1. */
  const progress = (st: Status): number => progressOf(st, now);

  /** The list, in sections: what is happening, then what needs you, then who is off. */
  // Ignored people are not on the list: that is what ignoring them means. They
  // are under Ignored at the top, where they can be let back in.
  const sections = $derived.by(() => {
    const rows = users.filter((u) => !u.ignored).map((u) => ({ u, st: statusOf(u) }));
    const by = (phase: Phase) => rows.filter((r) => r.st.phase === phase);
    const live = by("live").sort((a, b) => (a.st.eta || Infinity) - (b.st.eta || Infinity));
    const needs = by("needs").sort((a, b) => (a.u.ts || Infinity) - (b.u.ts || Infinity));
    return [
      { id: "live", title: "Being answered", tone: "accent", rows: live },
      { id: "needs", title: "Needs you", tone: "warn", rows: needs },
    ].filter((s) => s.rows.length);
  });

  // ── Ignored ─────────────────────────────────────────────────────────────
  type IgnoredPerson = { id: string; name: string; username?: string; avatar?: string };
  let ignoredOpen = $state(false);
  let ignoredList = $state<IgnoredPerson[]>([]);
  let ignoredLoaded = $state(false);
  let ignoreBusy = $state<Record<string, boolean>>({});

  async function loadIgnored() {
    try {
      ignoredList = (await api.chatsIgnored(target)).people || [];
    } catch {
      /* the button still shows what the waiting list knows */
    }
    ignoredLoaded = true;
  }
  $effect(() => {
    if (target) {
      ignoredLoaded = false;
      loadIgnored();
    }
  });
  const ignoredCount = $derived(ignoredLoaded ? ignoredList.length : users.filter((u) => u.ignored).length);
  const ignoredIds = $derived(new Set(ignoredList.map((p) => p.id)));
  /** A name from the profile cache first, then from the inbox, which often knows people the cache does not. */
  const ignoredShown = $derived(
    ignoredList.map((p) => {
      if (p.name && p.name !== p.id) return p;
      const u = users.find((x) => x.id === p.id);
      return u && u.name && u.name !== u.id
        ? { ...p, name: u.name, username: p.username || u.username, avatar: p.avatar || u.avatar }
        : p;
    }),
  );

  /** The X on a row: stop answering them, and stop trying, until they are let back in. `acc` is the row's account. */
  async function ignorePerson(u: IgnoredPerson, e?: MouseEvent, acc = target) {
    e?.stopPropagation();
    if (ignoreBusy[u.id]) return;
    ignoreBusy[u.id] = true;
    try {
      await setIgnored(acc, u.id, true);
      // The Ignored list at the top is the open account's; one ignored on another account is that account's.
      if (acc === target && !ignoredList.some((p) => p.id === u.id)) {
        ignoredList = [...ignoredList, { id: u.id, name: u.name, username: u.username, avatar: u.avatar }];
      }
      if (selectedId === u.id && acc === target && !showDetail) selectedId = "";
      toast(`Ignoring ${u.name}. Let them back in from Ignored at the top.`, "ok");
    } catch (err: any) {
      toast(err?.message || "Could not ignore them", "err");
    } finally {
      delete ignoreBusy[u.id];
    }
  }

  async function unignore(p: IgnoredPerson) {
    if (ignoreBusy[p.id]) return;
    ignoreBusy[p.id] = true;
    try {
      await setIgnored(target, p.id, false);
      ignoredList = ignoredList.filter((x) => x.id !== p.id);
      toast(`${p.name && p.name !== p.id ? `${p.name} is` : "They are"} back: the bot answers them again.`, "ok");
    } catch (err: any) {
      toast(err?.message || "Could not do that", "err");
    } finally {
      delete ignoreBusy[p.id];
    }
  }
  const flat = $derived(sections.flatMap((s) => s.rows.map((r) => r.u)));

  const nextReply = $derived.by(() => {
    let soonest = 0;
    for (const u of users) {
      const eta = u.state && ["waiting", "cooldown"].includes(u.state.state) ? u.state.eta : u.reply_at;
      if (eta && eta > now && (!soonest || eta < soonest)) soonest = eta;
    }
    return soonest;
  });
  const liveCount = $derived(sections.find((s) => s.id === "live")?.rows.length ?? 0);

  // ── Selection ──────────────────────────────────────────────────────────
  // Who is open on the right. Kept as a snapshot too: once they are answered
  // they leave the waiting list, and the conversation should stay open to show
  // the reply landing rather than vanish from under you.
  type Person = ChatUser & {
    archived?: boolean;
    /** Opened from the servers list rather than because someone wrote: there is nothing waiting in it. */
    browsed?: boolean;
    /** A channel it may read but not write in. */
    readonly?: boolean;
    /** What the channel is for, as the server set it. */
    topic?: string;
  };
  let selectedId = $state("");
  let snapshot = $state<Person | null>(null);
  // On a narrow window the list and the conversation take turns.
  let showDetail = $state(false);

  // Who is open is the person AND the account: in All chats one person can be waiting on two.
  const isOpen = (u: Row) => u.id === selectedId && accOf(u) === target;
  $effect(() => {
    const u = users.find(isOpen);
    if (u) snapshot = { ...u };
  });
  // Nothing open yet: open the first one, so the right side is never empty.
  $effect(() => {
    if (!selectedId && flat.length) {
      const first: Row = flat[0];
      if (first.acc && first.acc !== target) target = first.acc;
      selectedId = first.id;
    }
  });

  const selected = $derived<Person | null>(
    users.find(isOpen) ?? (snapshot?.id === selectedId ? snapshot : null),
  );
  const answered = $derived(!!selected && !users.some(isOpen));
  const st = $derived(selected && !answered ? statusOf(selected) : null);

  function select(id: string) {
    selectedId = id;
    showDetail = true;
  }
  /**
   * A channel picked from the servers list. One someone is waiting in is that row; any other is made up here, which
   * is all the right-hand side needs: a channel's row id is "ch<id>", and reading it and typing in it already work
   * through that (chat_routes.py `_server_row_id`).
   */
  function openChannel(ch: { id: string; name: string; topic: string; can_send: boolean },
                       g: { name: string; icon: string }) {
    const id = `ch${ch.id}`;
    const already = users.find((u) => u.id === id && accOf(u) === target);
    if (already) {
      openRow(already);
      return;
    }
    // Discord writes a channel with a "#" in front of it; a Telegram group is written as its name.
    const named = plat.id === "discord" ? `#${ch.name}` : ch.name;
    snapshot = { id, name: named, snippet: "", count: 0, ts: 0, kind: "server", channel_id: ch.id,
                 avatar: g.icon, where: `${named} \u00b7 ${g.name}`, browsed: true,
                 readonly: !ch.can_send, topic: ch.topic };
    select(id);
  }

  /** A row in the list. In All chats its own account becomes the one the conversation is with. */
  function openRow(u: Row) {
    if (u.acc && u.acc !== target) {
      target = u.acc;
      older = null;
    }
    select(u.id);
  }

  // ── Writing to them yourself ─────────────────────────────────────────────
  // What you are typing is a draft per conversation (lib/chats.ts): opening someone else, leaving the tab or
  // closing the app keeps it, and the list shows it under their name until it is sent.
  const draftKey = $derived(selected ? convKey(target, selected.id) : "");
  const draftOf = (id: string, acc = target) => ($drafts[convKey(acc, id)] ?? "").replace(/\s+/g, " ").trim();
  let sendingOwn = $state(false);
  let composer: HTMLTextAreaElement | null = $state(null);
  let filePick: HTMLInputElement | null = $state(null);

  function grow() {
    if (!composer) return;
    composer.style.height = "auto";
    composer.style.height = `${Math.min(composer.scrollHeight, 140)}px`;
  }

  // ── Pictures and files in the composer ──────────────────────────────────
  /** Staged attachments, per conversation, waiting to be sent with the message (lib/chats.ts keeps them). */
  type Staged = StagedFile;
  const MAX_FILES = 4;
  const MAX_BYTES = 8 * 1024 * 1024;
  /** What Discord takes from here: the runner sends these (_ALLOWED_UPLOAD in discord_runner.py). */
  const SENDABLE = /\.(png|jpe?g|gif|webp|avif|bmp|mp4|mov|webm|mkv|m4v|mp3|ogg|wav|m4a|opus|flac|aac|pdf|txt|md|csv|json|log|rtf|docx?|xlsx?|pptx?|odt|zip|rar|7z)$/i;
  const ACCEPT = "image/*,video/*,audio/*,.pdf,.txt,.md,.csv,.json,.log,.rtf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.odt,.zip,.rar,.7z";

  const stagedHere = $derived(draftKey ? $stagedFiles[draftKey] ?? [] : []);
  function setStaged(k: string, list: Staged[]) {
    stagedFiles.update((s) => {
      const next = { ...s };
      if (list.length) next[k] = list;
      else delete next[k];
      return next;
    });
  }

  /** A File as base64 (no data: prefix), plus a local URL to show it right away. */
  function readFile(f: File): Promise<Staged> {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onerror = () => reject(new Error(`${f.name}: could not be read`));
      r.onload = () => {
        const s = String(r.result ?? "");
        resolve({ name: f.name || "picture.png", data: s.slice(s.indexOf(",") + 1),
                  preview: URL.createObjectURL(f), type: f.type || "image/png", size: f.size });
      };
      r.readAsDataURL(f);
    });
  }

  async function stageFiles(list: File[]) {
    const who = selected;
    const k = draftKey;
    if (!who || !k || !list.length) return;
    const have = get(stagedFiles)[k] ?? [];
    const room = MAX_FILES - have.length;
    if (room <= 0) return toast(`Up to ${MAX_FILES} files in one message.`, "err");
    const take = list.slice(0, room);
    if (list.length > room) toast(`Up to ${MAX_FILES} files in one message: the first ${room} were added.`, "info");
    const added: Staged[] = [];
    for (const f of take) {
      if (f.size > MAX_BYTES) {
        toast(`${f.name} is bigger than 8MB.`, "err");
        continue;
      }
      // Snapchat sends pictures from here, as a Snap; Discord takes the usual kinds of file.
      if (isSnap ? !(f.type || "").startsWith("image/") : !SENDABLE.test(f.name || "") && !(f.type || "").startsWith("image/")) {
        toast(isSnap ? `${f.name}: ${plat.name} takes pictures from here.` : `${f.name}: that kind of file can't be sent.`, "err");
        continue;
      }
      try {
        added.push(await readFile(f));
      } catch (e: any) {
        toast(e?.message || "Could not read that file", "err");
      }
    }
    if (added.length) {
      setStaged(k, [...(get(stagedFiles)[k] ?? []), ...added]);
      playSound("select");
    }
  }

  /** Ctrl+V with a picture on the clipboard, the way Discord takes one. */
  function onComposerPaste(e: ClipboardEvent) {
    const files = [...(e.clipboardData?.items ?? [])]
      .filter((i) => i.kind === "file")
      .map((i) => i.getAsFile())
      .filter((f): f is File => !!f);
    if (!files.length) return;          // plain text pastes as text
    e.preventDefault();
    stageFiles(files);
  }

  function unstage(i: number) {
    const k = draftKey;
    if (!k) return;
    const list = get(stagedFiles)[k] ?? [];
    URL.revokeObjectURL(list[i]?.preview ?? "");
    setStaged(k, list.filter((_, n) => n !== i));
  }

  // ── Files dropped onto the conversation ─────────────────────────────────
  // Anywhere over it, the way Discord takes them: a veil says where they go, and they are added to the message
  // like pasted ones. A file dropped anywhere else on the page is caught too, so the window never opens it in
  // place of the app.
  let dragging = $state(false);
  let dragTimer: ReturnType<typeof setTimeout> | undefined;
  const carriesFiles = (e: DragEvent) => [...(e.dataTransfer?.types ?? [])].includes("Files");
  function onDragOver(e: DragEvent) {
    if (!carriesFiles(e) || !selected) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    // Files held over the conversation: an airy lift as it lights up, and a soft thunk where they are let go.
    if (!dragging) playSound("hover");
    dragging = true;
    // Dragover comes every few dozen milliseconds while files are held over it; when it stops, they have left.
    clearTimeout(dragTimer);
    dragTimer = setTimeout(() => (dragging = false), 350);
  }
  function onDrop(e: DragEvent) {
    if (!carriesFiles(e)) return;
    e.preventDefault();
    e.stopPropagation();
    clearTimeout(dragTimer);
    dragging = false;
    const files = [...(e.dataTransfer?.files ?? [])];
    if (files.length && selected) {
      playSound("drop");
      stageFiles(files);
      composer?.focus();
    }
  }
  function guardDrop(e: DragEvent) {
    if (!carriesFiles(e) || e.defaultPrevented) return;
    e.preventDefault();
    if (e.type === "dragover" && e.dataTransfer) e.dataTransfer.dropEffect = "none";
  }

  // Someone writing in the conversation that is open: a soft bloop, as a message app does.
  onMount(() => subscribeEvents("chat", (evt: any) => {
    if (evt && evt.t === "msg" && evt.target === target && selected && String(evt.uid) === String(selected.id)) {
      playSound("receive");
    }
  }));

  async function sendDraft() {
    const who = selected;
    const k = draftKey;
    if (!who || !k || sendingOwn) return;
    const text = ($drafts[k] ?? "").trim();
    const files = get(stagedFiles)[k] ?? [];
    if (!text && !files.length) return;
    const answering = replyingTo[k] ?? null;
    sendingOwn = true;
    setDraft(k, "");
    setStaged(k, []);
    if (answering) {
      const { [k]: _sent, ...rest } = replyingTo;
      replyingTo = rest;
    }
    // What is sent goes at the bottom, where now is.
    if (older) older = null;
    await tick();
    grow();
    const r = await sendOwnMessage(target, who.id, text, files, answering);
    sendingOwn = false;
    if (!r.ok) {
      setDraft(k, text);
      setStaged(k, files);
      if (answering) replyingTo = { ...replyingTo, [k]: answering };
      toast(r.error || "Could not send it", "err");
    } else {
      playSound("send");
      if (r.dropped) toast(`Sent. The bot's reply to ${who.name} was dropped: you answered them yourself.`, "ok");
      else if (r.notReply) toast(`Sent, as a plain message: ${plat.name} did not offer Reply on that one.`, "info");
    }
    await tick();
    grow();
    convBox?.scrollTo({ top: convBox.scrollHeight, behavior: "smooth" });
    composer?.focus();
  }

  function onComposerKey(e: KeyboardEvent) {
    if (e.key === "Escape" && replyHere) {
      e.preventDefault();
      e.stopPropagation();
      letGoOfReply();
      return;
    }
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      sendDraft();
    }
  }

  /** Inbox zero lists the answered conversations under its card, the first dozen until asked for more. */
  const RECENT_FIRST = 12;
  let showAllRecent = $state(false);

  // ── Calls ──────────────────────────────────────────────────────────────
  /** This account's calls going on now: someone calling it, or in a call with it (lib/chats.ts callsNow). */
  // In All chats, every account's: someone calling is not something to miss because another account is open.
  const calls = $derived(Object.values($callsNow).filter((c) => allView || c.target === target)
    .sort((a, b) => Number(b.state === "ringing") - Number(a.state === "ringing") || (a.since ?? 0) - (b.since ?? 0)));
  const callOf = (id: string, acc = target) => $callsNow[convKey(acc, id)];
  const callWords = (state: string) => (state === "ringing" ? "is calling" : state === "together" ? "on a call with you" : "in a call");
  /** How long, as a call screen says it: 0:42, 12:05. */
  const callFor = (since?: number) => {
    const s = Math.max(0, Math.round(now - (since ?? now)));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };
  function openCall(c: { uid: string; target?: string; name?: string; avatar?: string }) {
    playSound("select");
    // A call on another account, from All chats: that account is the one the conversation is with.
    if (c.target && c.target !== target) {
      target = c.target;
      older = null;
    }
    const row = users.find((u) => u.id === c.uid && accOf(u) === target);
    if (row) select(row.id);
    else openArchived({ id: c.uid, name: c.name || c.uid, avatar: c.avatar, messages: 0, last_ts: now });
  }

  function openArchived(c: Past) {
    // In All chats it belongs to one of the accounts, not the one that happens to be open: its conversation is
    // read from that one, so the account changes with it, as it does for a row still waiting.
    const acc = pastAcc(c);
    if (acc && acc !== target) {
      target = acc;
      older = null;
    }
    snapshot = { id: c.id, name: c.name, username: c.username, avatar: c.avatar, snippet: "", count: 0,
                 ts: c.last_ts, archived: true };
    select(c.id);
  }

  // The conversation itself, read when it is opened and live from then on.
  const ckey = $derived(convKey(target, selectedId));
  const conv = $derived($conversations[ckey]);
  $effect(() => {
    if (target && selectedId) loadConversation(target, selectedId);
  });

  /** What to draw: the conversation, or, before it arrives or on Snapchat, their last message. */
  const messages = $derived.by((): ConvMessage[] => {
    if (conv?.messages.length) return conv.messages;
    if (!selected || selected.archived) return [];
    return [{ mine: false, ts: selected.ts || now, text: selected.text ?? selected.snippet,
              attachments: selected.attachments, stickers: selected.stickers, embeds: selected.embeds }];
  });

  // ── Jumping to a message, and reading back from there ───────────────────
  // A message already drawn is scrolled to and lit up. One further back is read with the messages either side of it
  // (from Discord while the account runs, else from what is kept) and shown in place of the conversation, with a
  // bar to come back to now; scrolling from there reads on in both directions, and once it meets the conversation as
  // it is now the two become one again.
  type Older = { uid: string; messages: ConvMessage[]; loadingUp: boolean; loadingDown: boolean; doneUp: boolean; doneDown: boolean };
  let older = $state<Older | null>(null);
  let flashMid = $state("");
  let jumpPending = false;
  const shownMsgs = $derived(older && older.uid === selectedId ? older.messages : messages);
  const atStart = $derived(older && older.uid === selectedId ? older.doneUp : !!conv?.start);

  // Another conversation opened: whatever was being read back belonged to the last one.
  $effect(() => {
    const id = selectedId;
    untrack(() => {
      if (older && older.uid !== id) older = null;
      flashMid = "";
    });
  });

  function scrollToMid(mid: string, block: ScrollLogicalPosition = "center") {
    const el = convBox?.querySelector<HTMLElement>(`[data-mid="${CSS.escape(mid)}"]`);
    if (!el) return false;
    el.scrollIntoView({ block });
    flashMid = "";
    requestAnimationFrame(() => (flashMid = mid));
    setTimeout(() => {
      if (flashMid === mid) flashMid = "";
    }, 2200);
    return true;
  }

  /** A window read from the server: joined to the conversation when it reaches it, shown on its own when not. */
  function showWindow(uid: string, got: ConvMessage[], first = false) {
    const live = new Set(messages.map((m) => m.mid).filter(Boolean));
    if (got.some((m) => m.mid && live.has(m.mid))) {
      joinConversation(target, uid, got);
      older = null;
    } else {
      older = { uid, messages: got, loadingUp: false, loadingDown: false, doneUp: first, doneDown: false };
    }
  }

  async function jumpTo(mid: string) {
    const person = selected;
    if (!person || !mid) return;
    const uid = person.id;
    if (sideOverlay) toolsOpen = false;
    jumpPending = true;
    try {
      if (shownMsgs.some((m) => String(m.mid) === mid)) {
        await tick();
        scrollToMid(mid);
        return;
      }
      if (older && messages.some((m) => String(m.mid) === mid)) {
        older = null;
        await tick();
        scrollToMid(mid);
        return;
      }
      const r = await api.chatsWindow(uid, target, "around", mid, 50);
      if (selectedId !== uid) return;
      const got: ConvMessage[] = r.messages || [];
      if (!got.some((m) => String(m.mid) === mid)) {
        toast(r.missing ? "That message is not kept here." : "That message is not there any more.", "err");
        return;
      }
      showWindow(uid, got);
      await tick();
      scrollToMid(mid);
    } catch (e: any) {
      toast(e?.message || "Could not go to that message", "err");
    } finally {
      setTimeout(() => (jumpPending = false), 60);
    }
  }

  async function jumpFirst() {
    const person = selected;
    if (!person) return;
    jumpPending = true;
    try {
      const r = await api.chatsWindow(person.id, target, "first", "", 50);
      if (selectedId !== person.id) return;
      const got: ConvMessage[] = r.messages || [];
      if (!got.length) return toast("Nothing to show yet.", "info");
      showWindow(person.id, got, true);
      await tick();
      convBox?.scrollTo({ top: 0 });
      if (got[0].mid) scrollToMid(String(got[0].mid), "start");
    } catch (e: any) {
      toast(e?.message || "Could not read the start of it", "err");
    } finally {
      setTimeout(() => (jumpPending = false), 60);
    }
  }

  /** Back to the newest messages, at the bottom. */
  async function toPresent() {
    older = null;
    await tick();
    convBox?.scrollTo({ top: convBox.scrollHeight, behavior: get(motionEnabled) ? "smooth" : "auto" });
  }

  // Scrolling: near the top reads what came before; near the bottom of an older stretch, what came after.
  let atBottom = true;
  let farFromNow = $state(false);
  function onConvScroll() {
    if (!convBox) return;
    const fromBottom = convBox.scrollHeight - convBox.scrollTop - convBox.clientHeight;
    atBottom = fromBottom < 90;
    farFromNow = fromBottom > 700;
    if (convBox.scrollTop < 160) void earlier();
    if (older && fromBottom < 160) void later();
  }

  /** Keeps what is on screen where it is while messages are put in above it. */
  async function keepPlace(load: () => Promise<unknown>) {
    const box = convBox;
    if (!box) return;
    const h = box.scrollHeight;
    const top = box.scrollTop;
    await load();
    await tick();
    if (convBox === box) box.scrollTop = box.scrollHeight - h + top;
  }

  async function earlier() {
    if (older && older.uid === selectedId) return olderUp();
    if (!selected || !conv || conv.loading || conv.done || !conv.messages.length) return;
    const uid = selected.id;
    await keepPlace(() => loadEarlier(target, uid));
  }

  async function olderUp() {
    const o = older;
    if (!o || o.loadingUp || o.doneUp) return;
    const first = o.messages.find((m) => m.mid && !String(m.mid).startsWith("local-"));
    if (!first?.mid) return;
    older = { ...o, loadingUp: true };
    await keepPlace(async () => {
      try {
        const r = await api.chatsWindow(o.uid, target, "older", String(first.mid), 50);
        if (!older || older.uid !== o.uid) return;
        const have = new Set(older.messages.map((m) => m.mid));
        const add = (r.messages || []).filter((m: ConvMessage) => !m.mid || !have.has(m.mid));
        older = { ...older, messages: [...add, ...older.messages], loadingUp: false, doneUp: !r.more || !add.length };
      } catch {
        if (older) older = { ...older, loadingUp: false, doneUp: true };
      }
    });
  }

  async function later() {
    const o = older;
    if (!o || o.loadingDown || o.doneDown) return;
    const last = [...o.messages].reverse().find((m) => m.mid && !String(m.mid).startsWith("local-"));
    if (!last?.mid) return;
    older = { ...o, loadingDown: true };
    try {
      const r = await api.chatsWindow(o.uid, target, "newer", String(last.mid), 50);
      if (!older || older.uid !== o.uid) return;
      const got: ConvMessage[] = r.messages || [];
      const live = new Set(messages.map((m) => m.mid).filter(Boolean));
      if (!r.more || got.some((m) => m.mid && live.has(m.mid))) {
        // Down to now: one conversation again.
        joinConversation(target, o.uid, [...older.messages, ...got]);
        older = null;
        return;
      }
      const have = new Set(older.messages.map((m) => m.mid));
      older = { ...older, messages: [...older.messages, ...got.filter((m) => !m.mid || !have.has(m.mid))], loadingDown: false };
    } catch {
      if (older) older = { ...older, loadingDown: false, doneDown: true };
    }
  }

  // ── The panel beside the conversation: search, media, files, links ─────
  type ToolTab = "search" | "media" | "files" | "links" | "tiktoks" | "posts";
  /** A TikTok person's chat (not a group): it has their TikToks beside it. */
  const tiktokPerson = $derived(current?.platform === "tiktok" && !!selected?.id?.startsWith("tt_"));
  /** An Instagram person's chat: their stories and posts beside it. */
  const instaPerson = $derived(current?.platform === "instagram" && !!selected?.id?.startsWith("ig_"));
  let toolsOpen = $state(false);
  let toolsTab = $state<ToolTab>("search");
  let toolsFocus = $state(0);
  let headW = $state(0);
  let detailW = $state(0);
  /** Every one-to-one chat has them, Snapchat's too; a server channel does not. */
  const canTools = $derived(!!selected && selected.kind !== "server");
  /** Little room by the name: the media, files and links buttons move into More. */
  const compactHead = $derived(headW > 0 && headW < 620);
  /** Little room beside the conversation: the panel covers it instead. */
  const sideOverlay = $derived(detailW > 0 && detailW < 780);

  function toggleTools(tab: ToolTab) {
    if (toolsOpen && toolsTab === tab) {
      toolsOpen = false;
      return;
    }
    toolsTab = tab;
    toolsOpen = true;
  }
  function openTools(tab: ToolTab) {
    if (toolsOpen && toolsTab === tab) toolsFocus++;
    toolsTab = tab;
    toolsOpen = true;
  }

  /** Opens by sliding in from the side; over the conversation, when it covers it, by moving in a little. */
  function sideIn(node: HTMLElement, { overlay }: { overlay: boolean }) {
    const w = node.offsetWidth;
    return {
      duration: get(motionEnabled) ? 260 : 0,
      easing: cubicOut,
      css: (t: number) => (overlay
        ? `opacity: ${t}; transform: translateX(${(1 - t) * 28}px);`
        : `width: ${t * w}px; opacity: ${0.3 + t * 0.7};`),
    };
  }

  function onWindowKey(e: KeyboardEvent) {
    if (e.key === "Escape") {
      if (picking || ignoredOpen) {
        picking = false;
        ignoredOpen = false;
      } else if (toolsOpen) {
        toolsOpen = false;
      }
      return;
    }
    // Ctrl+F searches the conversation, the way it does in Discord.
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "f" && canTools) {
      e.preventDefault();
      openTools("search");
    }
  }

  function moreMenu(e: MouseEvent) {
    const person = selected;
    if (!person) return;
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const discordUser = current?.platform === "discord";
    openMenu(r.left, r.bottom + 6, [
      { title: person.name },
      compactHead && { label: "Pictures and videos", icon: "pictures", run: () => openTools("media") },
      compactHead && { label: "Files", icon: "file", run: () => openTools("files") },
      compactHead && { label: "Links", icon: "link", run: () => openTools("links") },
      compactHead && "sep",
      { label: "Go to the first message", icon: "jump", run: () => jumpFirst() },
      { label: "Save the chat as text", icon: "download", run: () => exportChat() },
      { label: "Reload the chat", icon: "refresh", run: () => loadConversation(target, person.id, true) },
      "sep",
      person.username && { label: "Copy username", icon: "copy", run: () => copyText(person.username ?? "", "Copied the username.") },
      discordUser && { label: "Copy user ID", icon: "copy", run: () => copyText(personOf(person).id, "Copied the ID.") },
      discordUser && { label: "Open in Discord", icon: "external", run: () => window.open(`https://discord.com/users/${personOf(person).id}`, "_blank", "noopener") },
    ]);
  }

  /** Everything kept of the conversation, as a text file. */
  async function exportChat() {
    const person = selected;
    if (!person) return;
    try {
      const r = await api.chatsExport(person.id, target, person.name, current ? who(current) : "Me");
      if (!r.count) return toast("Nothing kept from this chat yet.", "info");
      const safe = person.name.replace(/[\\/:*?"<>|]+/g, "_").slice(0, 60) || "chat";
      const where = await saveTextFile(`Chat with ${safe}.txt`, r.text);
      if (where) toast(`Saved ${r.count} messages.`, "ok");
    } catch (err: any) {
      toast(err?.message || "Could not save it", "err");
    }
  }

  // ── Finding someone, or something said, from the list ──────────────────
  type ListFilter = "all" | "unread" | "needs" | "live" | "answered" | "drafts";
  let listQuery = $state("");
  let listFilter = $state<ListFilter>("all");
  const listWords = $derived(splitWords(listQuery).map(fold).filter(Boolean));
  const searchingList = $derived(listWords.length > 0);

  function rowMatches(name: string, username: string | undefined, text: string): boolean {
    if (!listWords.length) return true;
    const hay = fold(`${name} ${username ?? ""} ${text}`);
    return listWords.every((w) => hay.includes(w));
  }

  const hasDraft = (id: string, acc = target) => !!draftOf(id, acc);
  function passes(u: Row, section: string): boolean {
    const f = listFilter;
    if (f === "unread" && !(u.count > 0)) return false;
    if ((f === "needs" || f === "live") && section !== f) return false;
    if (f === "answered") return false;
    if (f === "drafts" && !hasDraft(u.id, accOf(u))) return false;
    return rowMatches(u.name, u.username, `${u.where ?? ""} ${preview(u)}`);
  }

  const shownSections = $derived(
    sections.map((s) => ({ ...s, rows: s.rows.filter((r) => passes(r.u, s.id)) })).filter((s) => s.rows.length),
  );
  const shownArchived = $derived(
    archived.filter((c: Past) => {
      if (!["all", "answered", "drafts"].includes(listFilter)) return false;
      if (listFilter === "drafts" && !hasDraft(c.id)) return false;
      return rowMatches(c.name, c.username, "");
    }),
  );
  const pastOpen = $derived(showPast || listFilter === "answered" || searchingList);
  /** With nobody waiting, the recent conversations, narrowed by the same search. */
  const recentShown = $derived(archived.filter((c: Past) => rowMatches(c.name, c.username, "")));

  /** Which platforms have somewhere to go into: Discord's servers, Telegram's groups and channels. */
  const hasServers = $derived(plat.id === "discord" || plat.id === "telegram");
  /** Browsing those, rather than the list of who is waiting. */
  let serversOpen = $state(false);
  const browsingServers = $derived(serversOpen && !allView && hasServers);
  /** Going in and coming back out, which is a different thing from narrowing the list. */
  function toggleServers() {
    playSound(serversOpen ? "undo" : "open");
    serversOpen = !serversOpen;
    listQuery = "";
  }
  // Switching to an account with none, or to All chats, leaves it: there would be nothing to show.
  $effect(() => {
    if (serversOpen && (allView || !hasServers)) serversOpen = false;
  });
  /** Channels someone is waiting in, so the servers list can mark them. */
  const waitingChannels = $derived(
    new Set(users.filter((u) => u.kind === "server" && u.channel_id).map((u) => String(u.channel_id))),
  );

  const listChips = $derived.by(() => {
    const live = users.filter((u) => !u.ignored);
    const list: { id: ListFilter; label: string; n: number }[] = [
      { id: "all", label: "All", n: 0 },
      { id: "unread", label: "Unread", n: live.filter((u) => u.count > 0).length },
      { id: "needs", label: "Needs you", n: sections.find((s) => s.id === "needs")?.rows.length ?? 0 },
      { id: "live", label: "Being answered", n: sections.find((s) => s.id === "live")?.rows.length ?? 0 },
      { id: "drafts", label: "Drafts",
        n: live.filter((u) => hasDraft(u.id, accOf(u))).length + archived.filter((c: Past) => hasDraft(c.id)).length },
      { id: "answered", label: "Answered", n: archived.length },
    ];
    return list.filter((c) => c.id === "all" || c.id === listFilter || c.n > 0);
  });
  // The chips' pill: measured off the chosen chip, again when chips come and go or their counts change their width,
  // and when the column changes size. It only starts sliding once it has been put somewhere, so it never flies in
  // from the corner.
  let chipEls = $state<Record<string, HTMLElement | undefined>>({});
  let chipBox: HTMLElement | null = $state(null);
  let pill = $state({ x: 0, y: 0, w: 0, h: 0, shown: false });
  let pillMoves = $state(false);
  function placePill() {
    const el = chipEls[listFilter];
    if (!el || !el.isConnected) {
      pill = { ...pill, shown: false };
      return;
    }
    const first = !pill.shown;
    pill = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight, shown: true };
    if (first) requestAnimationFrame(() => requestAnimationFrame(() => (pillMoves = true)));
  }
  $effect(() => {
    listFilter;
    listChips;
    tick().then(placePill);
  });
  $effect(() => {
    if (!chipBox) return;
    const ro = new ResizeObserver(() => placePill());
    ro.observe(chipBox);
    return () => ro.disconnect();
  });

  function setListFilter(id: ListFilter) {
    listFilter = listFilter === id ? "all" : id;
    playSound("select");
  }

  // The words of every kept message too, a moment after typing stops.
  type MsgHit = { uid: string; mid: string; ts: number; mine: boolean; text?: string; attachments?: unknown[] };
  let msgHits = $state<{ q: string; messages: MsgHit[]; people: Record<string, any>; loading: boolean }>(
    { q: "", messages: [], people: {}, loading: false });
  let msgTimer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const q = listQuery.trim();
    const t = target;
    clearTimeout(msgTimer);
    // The words of kept messages are searched one account at a time; All chats finds people by name and what they
    // last said, which is what is in front of it.
    if (q.length < 2 || !t || allView) {
      msgHits = { q: "", messages: [], people: {}, loading: false };
      return;
    }
    msgTimer = setTimeout(async () => {
      msgHits = { ...msgHits, loading: true };
      try {
        const r = await api.chatsSearchAll(t, { words: splitWords(q), mine: null, has: [], before: null, after: null }, 40);
        if (listQuery.trim() !== q || target !== t) return;
        msgHits = { q, messages: r.messages || [], people: r.people || {}, loading: false };
      } catch {
        if (listQuery.trim() === q) msgHits = { q, messages: [], people: {}, loading: false };
      }
    }, 260);
    return () => clearTimeout(msgTimer);
  });

  /** Who a conversation found by its words is with, from whatever knows them. */
  function personFor(uid: string): Past {
    const u = users.find((x) => x.id === uid);
    if (u) return { id: u.id, name: u.name, username: u.username, avatar: u.avatar, messages: 0 };
    const c = pastList.find((x) => x.id === uid);
    if (c) return c;
    const p = msgHits.people[uid];
    if (p) return { id: uid, name: p.display_name || p.username || uid, username: p.username, avatar: p.avatar, messages: 0 };
    const ig = ignoredList.find((x) => x.id === uid);
    return { id: uid, name: ig?.name || "Someone", username: ig?.username, avatar: ig?.avatar, messages: 0 };
  }

  /** One line of a found message, starting near what was found, with names for its mentions. */
  function snippetOf(text: string): string {
    const s = text.replace(/<@!?(\d+)>/g, (_, id) => `@${$mentionNames[id] || "someone"}`).replace(/\s+/g, " ").trim();
    const f = fold(s);
    const at = Math.min(...listWords.map((w) => f.indexOf(w)).filter((i) => i >= 0), Infinity);
    if (!Number.isFinite(at) || at < 40) return s;
    const from = s.lastIndexOf(" ", at - 24);
    return `…${s.slice(from > 0 ? from + 1 : at - 24)}`;
  }

  async function openFromSearch(p: Past, mid: string) {
    if (users.some((u) => u.id === p.id)) select(p.id);
    else openArchived(p);
    await loadConversation(target, p.id);
    await tick();
    await jumpTo(mid);
  }

  /** Grouped for drawing: a day line when the day changes, and runs of one side. */
  const drawn = $derived.by(() => {
    const out: { m: ConvMessage; day?: string; first: boolean; last: boolean }[] = [];
    let lastDay = "";
    const messages = shownMsgs;
    messages.forEach((m, i) => {
      const day = dayLabel(m.ts);
      const prev = messages[i - 1];
      const next = messages[i + 1];
      // In a server channel the messages that are not yours come from several people: a new author, a new group.
      const who = (x: ConvMessage) => (x.mine ? "me" : x.author?.id ?? "them");
      const sameAsPrev = prev && who(prev) === who(m) && m.ts - prev.ts < 300 && dayLabel(prev.ts) === day;
      const sameAsNext = next && who(next) === who(m) && next.ts - m.ts < 300 && dayLabel(next.ts) === day;
      out.push({ m, day: day !== lastDay ? day : undefined, first: !sameAsPrev, last: !sameAsNext });
      lastDay = day;
    });
    return out;
  });

  const DAY_LONG: Intl.DateTimeFormatOptions = { weekday: "long", month: "short", day: "numeric" };
  function dayLabel(ts: number): string {
    const d = new Date(ts * 1000);
    const today = new Date();
    const y = new Date(); y.setDate(today.getDate() - 1);
    if (d.toDateString() === today.toDateString()) return "Today";
    if (d.toDateString() === y.toDateString()) return "Yesterday";
    return fmtDate(d, DAY_LONG);
  }

  // Keep the newest message in view as the conversation fills in: when it is opened, when you send, and while you
  // are at the bottom. Reading further up, a new message does not pull you down; reading back from a search or
  // jumping to a message, nothing does.
  let convBox: HTMLElement | null = $state(null);
  let lastShown = "";
  $effect(() => {
    const n = shownMsgs.length;
    const id = selectedId;
    const opened = id !== lastShown;
    lastShown = id;
    const mine = !!shownMsgs[n - 1]?.mine;
    if (untrack(() => !!older && older.uid === id) || jumpPending) return;
    if (!opened && !atBottom && !mine) return;
    tick().then(() => {
      convBox?.scrollTo({ top: convBox.scrollHeight });
      atBottom = true;
      farFromNow = false;
    });
  });
  // The box's height follows the draft of whoever is open.
  $effect(() => {
    draftKey;
    tick().then(grow);
  });

  // ── Doing things ───────────────────────────────────────────────────────
  let rowBusy = $state<Record<string, "cancel" | "ignore">>({});

  const cancellable = (u: ChatUser) =>
    (!!u.state && ["waiting", "writing", "cooldown", "queued"].includes(u.state.state))
    || (!u.state && !!u.reply_at && u.reply_at > now);

  async function reply(u: Row) {
    if (busy) return;
    try {
      const res = await sendReply(accOf(u), u.id);
      if (res?.cancelled) return;             // stopped from the Cancel button, which says so itself
      if (res && res.success === false) {
        toast(res.dropped ? `${u.name}: ${res.reason}. Removed from the list.` : `${u.name}: ${res.reason}`, "err");
      } else if (res) {
        toast(`Replied to ${u.name}`, "ok");
      }
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  async function cancel(u: Row) {
    const k = keyOf(u);
    if (rowBusy[k]) return;
    rowBusy[k] = "cancel";
    try {
      await cancelReply(accOf(u), u.id);
      toast(`Won't reply to ${u.name}. You can still answer by hand.`, "ok");
    } catch (e: any) {
      toast(e?.status === 504 ? "The account did not answer, it may be stopped" : e.message, "err");
    } finally {
      delete rowBusy[k];
    }
  }

  /** The person a row is about: for a server conversation, whoever is asking in it, not the channel. */
  const personOf = (u: ChatUser): IgnoredPerson =>
    u.kind === "server" && u.author_id ? { id: u.author_id, name: u.name, username: u.username, avatar: u.avatar } : u;

  async function flipIgnore(u: Row) {
    const k = keyOf(u);
    if (rowBusy[k]) return;
    rowBusy[k] = "ignore";
    try {
      const off = await toggleIgnore(accOf(u), personOf(u).id);
      toast(off ? `The bot is off for ${u.name}.` : `The bot is on for ${u.name} again.`, "ok");
    } catch (e: any) {
      toast(e?.status === 504 ? "The account did not answer, it may be stopped" : e.message, "err");
    } finally {
      delete rowBusy[k];
    }
  }

  /** Right-click on someone waiting: open them, answer now or not at all, or stop answering them. */
  function rowMenu(u: Row): MenuEntry[] {
    const who = personOf(u);
    return [
      { title: u.name },
      { label: "Open", icon: "chats", run: () => openRow(u) },
      u.kind !== "server" && { label: "Search in this chat", icon: "search", run: () => { openRow(u); openTools("search"); } },
      { label: "Reply now", icon: "send", disabled: busy, run: () => reply(u) },
      cancellable(u) && { label: "Don't reply", icon: "stop", run: () => cancel(u) },
      "sep",
      { label: "Copy name", icon: "copy", run: () => copyText(u.name, "Copied the name.") },
      u.username && u.username !== u.name && { label: `Copy @${u.username}`, icon: "copy", run: () => copyText(u.username ?? "", "Copied the username.") },
      who.id && !platOfRow(u).browser && { label: "Copy user ID", icon: "copy", run: () => copyText(String(who.id), "Copied the ID.") },
      "sep",
      { label: `Ignore ${who.name}`, icon: "close", danger: true, run: () => ignorePerson(who, undefined, accOf(u)) },
    ];
  }

  /** Right-click on an answered conversation: open it, search it, copy who it is with, or stop answering them. */
  function pastMenu(c: Past): MenuEntry[] {
    return [
      { title: c.name },
      { label: "Open", icon: "chats", run: () => openArchived(c) },
      { label: "Search in this chat", icon: "search", run: () => { openArchived(c); openTools("search"); } },
      "sep",
      { label: "Copy name", icon: "copy", run: () => copyText(c.name, "Copied the name.") },
      c.username && c.username !== c.name && { label: `Copy @${c.username}`, icon: "copy", run: () => copyText(c.username ?? "", "Copied the username.") },
      !isSnap && { label: "Copy user ID", icon: "copy", run: () => copyText(c.id, "Copied the ID.") },
      "sep",
      { label: `Ignore ${c.name}`, icon: "close", danger: true, run: () => ignorePerson(c) },
    ];
  }

  /** Right-click on a message: copy it, or its ID; one of the account's own that read like an assistant, add it to the
   * refusal phrases (Settings, Refusals), all of it or the part selected. */
  function messageMenu(m: ConvMessage, e?: MouseEvent): MenuEntry[] {
    const bubble = (e?.target as Element | null)?.closest?.(".cd-msg");
    const sel = window.getSelection();
    const picked = bubble && sel && !sel.isCollapsed && bubble.contains(sel.anchorNode) ? sel.toString().trim() : "";
    const words = (picked || m.text || "").replace(/\s+/g, " ").trim();
    const reactButton = bubble?.querySelector<HTMLElement>(".cd-react-add");
    return [
      reactable(m) && { label: "Reply", icon: "reply", run: () => startReply(m) },
      reactable(m) && reactButton && {
        label: "React", icon: "smilePlus", run: () => (reactingTo = { mid: String(m.mid), anchor: reactButton }),
      },
      m.text && { label: "Copy message", icon: "copy", run: () => copyText(m.text ?? "", "Copied the message.") },
      m.mid && { label: "Copy message ID", icon: "copy", run: () => copyText(String(m.mid), "Copied the ID.") },
      m.mine && words.length >= 3 && "sep",
      m.mine && words.length >= 3 && {
        label: picked ? "Add the selection to refusal phrases" : "Add to refusal phrases",
        icon: "alertCircle",
        danger: true,
        run: () => addRefusal(words),
      },
    ];
  }

  // ── The picture of whoever is open ──────────────────────────────────────
  // A row that came in without one (a message arriving live, an old row) used to leave the header on the
  // placeholder while their card, which asks for them, had it: the header asks the same way, once a person.
  let foundAvatar = $state<Record<string, string>>({});
  const asked = new Set<string>();
  $effect(() => {
    const s = selected;
    if (!s || s.avatar || s.kind === "server" || asked.has(`${target}:${s.id}`)) return;
    asked.add(`${target}:${s.id}`);
    const id = s.id;
    api.person(String(id)).then((p: any) => {
      if (p?.avatar) foundAvatar = { ...foundAvatar, [id]: p.avatar };
    }).catch(() => {});
  });
  const headAvatar = $derived(selected ? selected.avatar || foundAvatar[selected.id] || "" : "");

  // ── Replying to one message ─────────────────────────────────────────────
  // Reply on a message (beside it as the pointer passes, or in its right-click menu): what is typed next goes as
  // its answer, as Discord's reply, Snapchat's and TikTok's own Reply. One per conversation, until sent or let go.
  let replyingTo = $state<Record<string, ReplyTo & { mid: string }>>({});
  const replyHere = $derived(draftKey ? replyingTo[draftKey] : undefined);

  /** What a message is, in a few words, for the bar over the message box. */
  function gist(m: ConvMessage): string {
    const t = (m.text ?? "").replace(/\s+/g, " ").trim();
    // A gift is its link in words, which reads as nothing: say what it is instead.
    if (m.gift) return m.gift.what && m.gift.what !== "a gift" ? `A gift: ${m.gift.what}` : "A Nitro gift";
    if (t && !/^\[[^\]]+\]$/.test(t)) return t.slice(0, 120);
    if (m.attachments?.length) return "A picture";
    if (m.stickers?.length) return "A sticker";
    if (m.kind === "video" || m.embeds?.length) return "A video";
    return "A message";
  }

  function startReply(m: ConvMessage) {
    if (!selected || !draftKey || !reactable(m)) return;
    replyingTo = { ...replyingTo, [draftKey]: { mid: String(m.mid), text: gist(m),
                                                name: m.mine ? "yourself" : (m.author?.name ?? selected.name) } };
    playSound("select");
    tick().then(() => composer?.focus());
  }

  function letGoOfReply() {
    if (!draftKey || !replyingTo[draftKey]) return;
    const { [draftKey]: _gone, ...rest } = replyingTo;
    replyingTo = rest;
    playSound("off");
  }

  // ── Reacting ───────────────────────────────────────────────────────────
  // The account's reaction on a message, from here: the platform's own set
  // (Snapchat's eight, any emoji on Discord), a press on one under a message to
  // add it or take it back, and React in its right-click menu.
  let reactingTo = $state<{ mid: string; anchor: HTMLElement } | null>(null);

  /** A message that can take a reaction: sent, still there, and with an id the account can find it by. */
  const reactable = (m: ConvMessage) =>
    !!m.mid && !String(m.mid).startsWith("local-") && !m.pending && !m.failed && !m.deleted;

  function openReact(m: ConvMessage, e: MouseEvent) {
    const anchor = e.currentTarget as HTMLElement;
    reactingTo = reactingTo?.mid === String(m.mid) ? null : { mid: String(m.mid), anchor };
  }

  async function react(m: ConvMessage, emoji: { name: string; url?: string }, add: boolean) {
    if (!selected || !reactable(m)) return;
    try {
      await reactTo(target, selected.id, String(m.mid), emoji, add, isSnap);
    } catch (err: any) {
      toast(err?.status === 504 ? "The account did not answer, it may be stopped" : err?.message || "Could not react", "err");
    }
  }

  /** A reaction under a message, pressed: the account's own taken back, anyone else's added as its own too. */
  function toggleReaction(m: ConvMessage, r: Reaction) {
    if (isSnap && !plat.reactions.includes(r.name)) return;
    playSound(r.mine ? "off" : "select");
    void react(m, r, !r.mine);
  }

  /** It counts as a refusal from the next reply on: the bot sends one of its "Send instead" words in its place. */
  async function addRefusal(phrase: string) {
    try {
      const r = await api.addRefusalPhrase(phrase);
      if (!r.added) toast("That is already a refusal phrase.", "info");
      else if (r.enabled === false) toast("Added. Catching refusals is off in Settings, Refusals.", "info");
      else toast("Added to the refusal phrases.", "ok");
    } catch (err: any) {
      toast(err?.message || "Could not add it", "err");
    }
  }

  async function replyAll() {
    if (replyingAll) {
      // Stop: the reply being written and any waiting to be sent are cancelled too;
      // the run ends as they come back, and says what it did. Every account's, in All chats.
      for (const t of replyTargets) void stopReplyAll(t);
      return;
    }
    if (busy || !replyTargets.length) return;
    try {
      // Each account answers at its own pace, so they run together rather than one after the other.
      const runs = await Promise.all(replyTargets.map((t) => sendReplyAll(t).catch((e) => ({ error: e }) as any)));
      const got = runs.filter((r) => r && !r.error);
      const failed = runs.find((r) => r && r.error);
      if (!got.length) {
        if (failed) throw failed.error;
        return;
      }
      const res = {
        results: got.flatMap((r: any) => (r.results || []) as any[]),
        total: got.reduce((n: number, r: any) => n + (r.total ?? 0), 0),
        of: got.reduce((n: number, r: any) => n + (r.of ?? r.total ?? 0), 0),
        stopped: got.some((r: any) => r.stopped),
      };
      const results = res.results;
      const stuck = results.filter((r) => !r.success && !r.dropped && !r.cancelled);
      failedReplies = new Set(stuck.map((r) => String(r.id)));
      const n = res.total || users.length;
      const done = n - results.filter((r) => !r.success).length;
      if (res.stopped) {
        toast(done ? `Stopped. ${done} of ${res.of} answered before that.` : "Stopped. Nobody was answered.", "info");
        return;
      }
      toast(
        stuck.length
          ? `Answered ${done} of ${n}. ${stuck.length} couldn't be answered yet, see Logs for why.`
          : done < n ? `Answered ${done}. The rest can't be reached and were removed.`
          : `Replied to ${n} ${n === 1 ? "person" : "people"}`,
        stuck.length ? "info" : "ok",
      );
    } catch (e: any) {
      toast(e.message, "err");
    }
  }


  // Names for the @mentions in the previews, fetched once each.
  $effect(() => {
    for (const u of users) {
      for (const m of (u.text ?? u.snippet ?? "").matchAll(/<@!?(\d+)>/g)) resolveMention(m[1]);
    }
  });

  /** A one-line preview for the list, as plain text: no markdown, mentions as names. */
  function preview(u: ChatUser): string {
    if (u.gift) return u.gift.state === "accepted" ? "A Nitro gift, taken" : "Sent a Nitro gift";
    const t = (u.text ?? u.snippet ?? "")
      .replace(/<@!?(\d+)>/g, (_, id) => `@${$mentionNames[id] || "someone"}`)
      .replace(/<a?:(\w+):\d+>/g, ":$1:")
      .replace(/```[\s\S]*?```/g, "code")
      .replace(/\|\|[\s\S]+?\|\|/g, "spoiler")
      .replace(/^\s*>+\s?/gm, "")
      .replace(/[*_~`]/g, "")
      .replace(/\s+/g, " ")
      .trim();
    if (t && !/^\[(attachment|image|video|file|link|voice message|voice|photo|live|unsupported|snap|call|\d+ attachments|sticker.*)\]$/i.test(t)) return t;
    // Snapchat's kinds of message, said the way Snapchat says them.
    const said: Record<string, string> = { "[snap]": "Sent a Snap", "[call]": "A call", "[voice message]": "Voice message",
                                           "[image]": "Sent a picture", "[video]": "Sent a video", "[sticker]": "Sent a sticker",
                                           "[photo]": "Sent a photo", "[voice]": "Voice message", "[live]": "Shared a LIVE",
                                           "[unsupported]": "Only shows in the TikTok app" };
    if (said[t.toLowerCase()]) return said[t.toLowerCase()];
    if (u.attachments?.length) return u.attachments.length > 1 ? `${u.attachments.length} attachments` : "Sent a picture";
    if (u.stickers?.length) return `Sticker: ${u.stickers[0].name}`;
    return t ? "Sent an attachment" : "";
  }
  const hasMedia = (u: ChatUser) => !!(u.attachments?.length || u.stickers?.length)
    || /^\[/.test((u.text ?? u.snippet ?? "").trim());
</script>

<ErrorNote text={loadError} onretry={() => { loadError = ""; start(); }} />

<svelte:window onclick={dismiss} onkeydown={onWindowKey} ondragover={guardDrop} ondrop={guardDrop} />

<!-- ── The top: who you are answering as, the state of things, reply to all ── -->
<!-- In a narrow window (the pocket one), an open conversation gets the whole
     window, the way a phone's messaging app does: the account, the counts and
     the friend requests step aside, and the back button brings them back. -->
<div class="ch-top" class:narrow-hide={showDetail && !!selected}>
  <div class="ch-top-account relative min-w-0" data-account-picker>
    <svelte:element
      this={multiple ? "button" : "div"}
      role={multiple ? "button" : undefined}
      aria-haspopup={multiple ? "listbox" : undefined}
      aria-expanded={multiple ? picking : undefined}
      onclick={multiple ? () => (picking = !picking) : undefined}
      class="ch-account {multiple ? 'is-button' : ''} {picking ? 'is-open' : ''}"
    >
      {#if allView}
        <!-- Every account at once: their pictures stacked, the way a group shows its members. -->
        <span class="ch-stack" aria-hidden="true">
          {#each accounts.slice(0, 3) as a (a.id)}
            {#if a.avatar}<img src={a.avatar} alt="" />{:else}<span><Icon name={a.platform === "discord" ? "accounts" : platformIcon(a.platform)} size={11} /></span>{/if}
          {/each}
        </span>
      {:else if current?.avatar}
        <img src={current.avatar} alt="" class="h-9 w-9 shrink-0 rounded-full object-cover ring-1 ring-edge" />
      {:else}
        <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-accent">
          <Icon name={plat.id === "discord" ? "accounts" : plat.icon} size={17} />
        </span>
      {/if}
      <span class="min-w-0">
        <span class="flex min-w-0 items-center gap-2">
          <span class="ch-acc-name truncate text-[14px] font-semibold text-ink">
            {allView ? "All chats" : current ? who(current) : "No account"}
          </span>
          {#if allView}
            <span class="ch-slot-chip shrink-0 rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-faint">{accounts.length} accounts</span>
          {:else if current && named(current)}
            <span class="ch-slot-chip shrink-0 rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-faint">{slot(current)}</span>
          {/if}
        </span>
        <span class="block truncate text-[11px] text-faint">
          {allView ? "Every account at once, click to switch"
            : multiple ? "Answering as this account, click to switch" : "Answering as this account"}
        </span>
      </span>
      {#if waitingElsewhere}
        <!-- People waiting on the other accounts, so they are not missed while this one is open. -->
        <span class="ch-elsewhere" title="{waitingElsewhere} waiting on your other accounts">{waitingElsewhere > 99 ? "99+" : waitingElsewhere}</span>
      {/if}
      {#if multiple}
        <span class="ml-1 shrink-0 text-faint transition-transform duration-200" style="transform: rotate({picking ? 180 : 0}deg)">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M2.5 4.5 6 8l3.5-3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </span>
      {/if}
    </svelte:element>

    {#if picking}
      <div role="listbox" aria-label="Account to answer as"
           class="glass floating absolute left-0 top-full z-30 mt-1 w-72 overflow-hidden rounded-xl p-1 shadow-xl">
        <!-- Every account's waiting chats in one list. -->
        <button role="option" aria-selected={allView} onclick={() => choose(ALL_CHATS)}
                class="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors
                  {allView ? 'bg-accent/10' : 'hover:bg-white/[0.05]'}">
          <span class="ch-stack is-small" aria-hidden="true">
            {#each accounts.slice(0, 3) as a (a.id)}
              {#if a.avatar}<img src={a.avatar} alt="" />{:else}<span><Icon name={a.platform === "discord" ? "accounts" : platformIcon(a.platform)} size={10} /></span>{/if}
            {/each}
          </span>
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[13px] text-ink">All chats</span>
            <span class="block truncate text-[11px] text-faint">Every account at once</span>
          </span>
          {#if waitingAll}<span class="ch-waiting" title="{waitingAll} waiting on a reply">{waitingAll > 99 ? "99+" : waitingAll}</span>{/if}
          {#if allView}<span class="shrink-0 text-accent"><Icon name="check" size={14} /></span>{/if}
        </button>
        <div class="ch-pick-sep" aria-hidden="true"></div>
        {#each accounts as a (a.id)}
          {@const on = !allView && a.id === target}
          {@const n = waitingOn(a.id)}
          <button role="option" aria-selected={on} onclick={() => choose(a.id)}
                  class="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors
                    {on ? 'bg-accent/10' : 'hover:bg-white/[0.05]'}">
            {#if a.avatar}
              <img src={a.avatar} alt="" class="h-8 w-8 shrink-0 rounded-full object-cover ring-1 ring-edge" />
            {:else}
              <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-accent">
                <Icon name={a.platform === "discord" ? "accounts" : platformIcon(a.platform)} size={15} />
              </span>
            {/if}
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[13px] text-ink">{who(a)}</span>
              <span class="block truncate text-[11px] text-faint">
                {named(a) ? `${slot(a)}${a.username && a.username !== who(a) ? ` · @${a.username}` : ""}` : "never connected"}
              </span>
            </span>
            {#if a.state && a.state !== "running"}<span class="shrink-0"><Badge tone="muted">{a.state}</Badge></span>{/if}
            {#if n}<span class="ch-waiting" title="{n} waiting on a reply">{n > 99 ? "99+" : n}</span>{/if}
            {#if on}<span class="shrink-0 text-accent"><Icon name="check" size={14} /></span>{/if}
          </button>
        {/each}
      </div>
    {/if}
  </div>

  {#if !loading && users.length}
    <div class="ch-stats">
      <span class="ch-stat"><b>{users.filter((u) => !u.ignored).length}</b> waiting</span>
      {#if unread}<span class="ch-stat"><b>{unread}</b> unread</span>{/if}
      {#if nextReply}<span class="ch-stat is-accent"><b>{countdown(nextReply)}</b> to the next reply</span>{/if}
      {#if liveCount}<span class="ch-stat is-live"><i></i><b>{liveCount}</b> being answered</span>{/if}
    </div>
  {/if}

  <div class="ch-top-actions ml-auto flex shrink-0 items-center gap-2">
    <!-- Who is ignored, adding a friend and replying to everyone are each one account's: in All chats they wait for
         that account to be chosen, rather than quietly acting on whichever was open last. -->
    {#if !allView}
    <div class="relative" data-ignored-panel>
      <button class="ch-ignored-btn" class:is-open={ignoredOpen} onclick={() => { ignoredOpen = !ignoredOpen; if (ignoredOpen) loadIgnored(); }}
              title="People the bot does not answer" aria-label="Ignored" aria-expanded={ignoredOpen}>
        <Icon name="eyeOff" size={13} /><span class="ch-btn-label">Ignored</span>{#if ignoredCount}<b>{ignoredCount}</b>{/if}
      </button>
      {#if ignoredOpen}
        <div class="ch-ignored glass floating" role="dialog" aria-label="Ignored people">
          <div class="ch-ignored-head">
            <span>Ignored</span>
            <span class="text-[11px] font-normal normal-case tracking-normal text-faint">the bot does not answer them</span>
          </div>
          {#if !ignoredShown.length}
            <p class="px-3 py-5 text-center text-[12px] text-faint">
              Nobody. The X on someone in the list ignores them.
            </p>
          {:else}
            <div class="ch-ignored-list">
              {#each ignoredShown as p (p.id)}
                {@const known = !!p.name && p.name !== p.id}
                <div class="ch-ignored-row">
                  <Avatar src={p.avatar} name={known ? p.name : "?"} size={30} zoom={false} />
                  <span class="min-w-0 flex-1">
                    <span class="block truncate text-[13px] text-ink">{known ? p.name : "Unknown"}</span>
                    {#if !known}<span class="block truncate text-[11px] text-faint">ID {p.id}</span>
                    {:else if p.username && p.username !== p.name}<span class="selectable block truncate text-[11px] text-faint">@{p.username}</span>{/if}
                  </span>
                  <button class="ch-unignore" onclick={() => unignore(p)} disabled={!!ignoreBusy[p.id]}>
                    {ignoreBusy[p.id] ? "…" : "Unignore"}
                  </button>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      {/if}
    </div>
    <!-- Adding a friend: their username, sent from this account. Not where there is nobody to add (a game). -->
    {#if plat.add}
    <div class="relative" data-add-friend>
      <button class="ch-ignored-btn" class:is-open={addOpen} onclick={toggleAdd}
              title={plat.id === "imessage" ? "Text someone new, by number or email"
                : plat.add === "Follow" ? "Follow someone by username" : "Send a friend request by username"}
              aria-label={plat.add} aria-expanded={addOpen}>
        <Icon name={plat.id === "imessage" ? "edit" : "userPlus"} size={13} /><span class="ch-btn-label">{plat.add}</span>
      </button>
      {#if addOpen}
        <form class="ch-add glass floating" class:is-text={plat.id === "imessage"}
              onsubmit={(e) => { e.preventDefault(); addFriend(); }}>
          {#if plat.id === "imessage"}
            <!-- iMessage: anyone can be texted, by their number or email; the first message starts it. -->
            <span class="ch-add-head">Text someone new</span>
            <label class="ch-add-box is-who">
              <input bind:this={addBox} bind:value={addName} placeholder="+1 555 123 4567 or name@icloud.com"
                     spellcheck="false" autocomplete="off" aria-label="Their number or email"
                     onkeydown={(e) => { if (e.key === "Escape") addOpen = false; }} />
            </label>
            <label class="ch-add-box">
              <input bind:value={addText} placeholder="Your message" autocomplete="off" aria-label="The first message"
                     onkeydown={(e) => { if (e.key === "Escape") addOpen = false; }} />
            </label>
            <Button size="sm" loading={adding} disabled={!addName.trim() || !addText.trim()}>Send</Button>
          {:else}
            <span class="ch-add-head">{plat.add === "Follow" ? `Follow someone on ${plat.name}` : `Add a friend on ${plat.name}`}</span>
            <label class="ch-add-box">
              <span class="ch-add-at">@</span>
              <input bind:this={addBox} bind:value={addName} placeholder="username" spellcheck="false" autocomplete="off"
                     aria-label="Their username" onkeydown={(e) => { if (e.key === "Escape") addOpen = false; }} />
            </label>
            <Button size="sm" loading={adding} disabled={!addName.trim()}>{plat.add === "Follow" ? "Follow" : "Add"}</Button>
          {/if}
        </form>
      {/if}
    </div>
    {/if}
    {/if}
    <span class="ch-livebadge" title="New messages and every step of a reply show up here as they happen">
      <i class:is-busy={refreshing}></i>{refreshing ? "Checking" : "Live"}
    </span>
    <Button kind={replyingAll ? "ghost" : "good"} onclick={replyAll}
            disabled={(!replyingAll && !replyTargets.length) || !!allProgress?.stopping}
            loading={!!allProgress?.stopping}>
      {#if allProgress?.stopping}
        Stopping
      {:else if replyingAll && allProgress}
        <Icon name="stop" size={11} />Stop ({allProgress.done}/{allProgress.total})
      {:else if replyingAll}
        <Icon name="stop" size={11} />Stop
      {:else}
        <!-- In All chats it answers every account's, so it says so rather than looking like one account's. -->
        <Icon name="chats" size={13} />{allView && replyTargets.length > 1
          ? `Reply to all (${replyTargets.length} accounts)` : "Reply to all"}
      {/if}
    </Button>
  </div>
</div>

<!-- ── Calls: someone calling the account, or in a call with it, live ─────── -->
{#if calls.length}
  <div class="ch-calls" class:narrow-hide={showDetail && !!selected}>
    {#each calls as c (c.uid)}
      <button class="ch-call" class:is-ringing={c.state === "ringing"} onclick={() => openCall(c)}
              transition:fade={{ duration: 180 }} title="Open the conversation">
        <span class="ch-call-av">
          <span class="ch-call-ring" aria-hidden="true"></span><span class="ch-call-ring is-late" aria-hidden="true"></span>
          <Avatar src={c.avatar} name={c.name || "?"} size={34} zoom={false} silhouette={plat.silhouette} />
        </span>
        <span class="ch-call-text">
          <b>{c.name || "Someone"}</b>
          <small><span class="ch-call-icon"><Icon name="phone" size={11} /></span><span>{callWords(c.state)}{#if c.since}{" · "}{callFor(c.since)}{/if}</span></small>
          {#if c.live && c.last}<small class="ch-call-live">{c.last}</small>{/if}
        </span>
      </button>
    {/each}
  </div>
{/if}

<!-- ── Friend requests: a strip, not a block ──────────────────────────────── -->
{#if !allView && (incoming.length || (friendsError && friendsSupported))}
  <div class="ch-friends" class:narrow-hide={showDetail && !!selected}>
    <span class="ch-friends-label">
      <Icon name="accounts" size={13} />{plat.requests}
      {#if incoming.length}<b>{incoming.length}</b>{/if}
    </span>
    {#if friendsError && friendsSupported && !incoming.length}
      <span class="text-[12px] text-warn">{friendsError}</span>
      <button class="text-[11.5px] text-faint hover:text-ink" onclick={loadFriends}>Try again</button>
    {/if}
    <div class="ch-friends-list domino" use:domino={{ step: 70 }}>
      {#each incoming as r (r.id)}
        <div class="ch-fr" title={plat.requests === "Message requests" ? "Accept lets them message it. Delete turns it down." : isSnap ? "Accept adds them as a friend." : "Accepted over hours on its own so it does not look scripted. Accept does it now."}>
          <Avatar src={r.avatar} name={r.display_name || r.username} size={30} silhouette={plat.silhouette} />
          <span class="min-w-0">
            <span class="block truncate text-[12.5px] font-medium text-ink">{r.display_name || r.username}</span>
            <span class="block truncate text-[10.5px] text-faint">
              {#if r.accept_at && countdown(r.accept_at)}auto-accepts in {countdown(r.accept_at)}{:else if r.accept_at}accepting now{:else if r.username}<span class="selectable">@{r.username}</span>{:else}wants to be friends{/if}
            </span>
          </span>
          <button class="ch-fr-btn is-yes" disabled={friendBusy[r.id]} onclick={() => answerRequest(r, "accept")}
                  title="Accept now" aria-label="Accept {r.display_name || r.username}">
            <Icon name="check" size={13} />
          </button>
          <button class="ch-fr-btn" disabled={friendBusy[r.id]} onclick={() => answerRequest(r, "decline")}
                  title="Decline" aria-label="Decline {r.display_name || r.username}">
            <Icon name="close" size={12} />
          </button>
        </div>
      {/each}
    </div>
  </div>
{/if}

{#if loading}
  <div class="ch-inbox" use:fillHeight>
    <div class="ch-list">
      {#each Array(6) as _}<div class="mb-1.5 h-[62px] animate-pulse rounded-2xl bg-white/[0.03]"></div>{/each}
    </div>
    <div class="ch-detail glass"><div class="m-5 h-40 animate-pulse rounded-2xl bg-white/[0.03]"></div></div>
  </div>
{:else if !users.length && !selected && !browsingServers}
  <!-- ── Inbox zero ─────────────────────────────────────────────────────── -->
  <div class="ch-zero glass" class:is-compact={archived.length > 0}>
    <span class="ch-zero-mark" use:chime={"done"}><Icon name="check" size={26} /></span>
    <div class="text-[18px] font-semibold tracking-tight text-ink">Everyone has been answered</div>
    <p class="max-w-md text-[12.5px] leading-relaxed text-muted">
      Anyone who messages {allView ? "any of your accounts" : "this account"} and has not had a reply shows up here
      the moment they do, with where the bot is with their reply.
    </p>
    {#if !allView && hasServers}
      <!-- Nobody waiting is when you are most likely to want to go and say something in one yourself. -->
      <Button kind="ghost" onclick={() => (serversOpen = true)}>
        <Icon name="globe" size={13} />{plat.id === "telegram" ? "Go into its groups" : "Go into its servers"}
      </Button>
    {/if}
  </div>

  <!-- The conversations already answered stay in reach: it used to be one
       link to the latest and nothing else. -->
  {#if archived.length}
    <section class="ch-recent">
      <div class="ch-recent-head">
        <div class="ch-sec">
          <span class="ch-sec-dot"></span>Recent conversations<span class="ch-sec-n">{recentShown.length}</span>
        </div>
        <!-- The same search as the list's: who, and what was said. -->
        <label class="ch-find-box ch-recent-find">
          <Icon name="search" size={13} />
          <input bind:value={listQuery} placeholder="Search chats" spellcheck="false" autocomplete="off" aria-label="Search chats"
                 onkeydown={(e) => { if (e.key === "Escape" && listQuery) { e.stopPropagation(); listQuery = ""; } }} />
          {#if listQuery}
            <button type="button" class="ch-find-x" onclick={() => (listQuery = "")} aria-label="Clear the search">
              <Icon name="close" size={10} />
            </button>
          {/if}
        </label>
      </div>
      <div class="ch-recent-grid domino" use:domino={{ step: 35 }}>
        {#each recentShown.slice(0, showAllRecent || searchingList ? recentShown.length : RECENT_FIRST) as c (c.id)}
          <div class="ch-item-wrap ch-recent-wrap">
            <button class="ch-recent-card" onclick={() => openArchived(c)}>
              <span class="halo ch-recent-av"><Avatar src={c.avatar} name={c.name} size={40} zoom={false} silhouette={plat.silhouette} /></span>
              <span class="min-w-0 flex-1 text-left">
                <span class="block truncate text-[13.5px] font-medium text-ink">{c.name}</span>
                <span class="block truncate text-[11.5px] text-faint">
                  {c.messages} message{c.messages === 1 ? "" : "s"}{c.last_ts ? ` · ${ago(c.last_ts)}` : ""}
                </span>
              </span>
              <span class="ch-recent-go"><Icon name="chevron" size={12} /></span>
            </button>
            <button class="ch-x" onclick={(e) => ignorePerson(c, e)} disabled={!!ignoreBusy[c.id]}
                    title="Ignore {c.name}: the bot stops answering them until you unignore them" aria-label="Ignore {c.name}">
              <Icon name="close" size={11} />
            </button>
          </div>
        {/each}
      </div>
      {#if searchingList && !recentShown.length && !msgHits.messages.length && !msgHits.loading}
        <div class="ch-nothing"><Icon name="search" size={18} /><span>Nothing found</span></div>
      {/if}
      {#if listQuery.trim().length >= 2 && (msgHits.messages.length || msgHits.loading)}
        <div class="ch-sec ch-recent-msgs">
          <span class="ch-sec-dot"></span>Messages
          {#if msgHits.loading && !msgHits.messages.length}<span class="ch-sec-spin"></span>{:else}<span class="ch-sec-n">{msgHits.messages.length}</span>{/if}
        </div>
        <div class="ch-recent-hits">
          {#each msgHits.messages as m (`${m.uid}:${m.mid}`)}
            {@const p = personFor(String(m.uid))}
            <button type="button" class="ch-hit" onclick={() => openFromSearch(p, String(m.mid))}>
              <Avatar src={p.avatar} name={p.name} size={32} zoom={false} silhouette={plat.silhouette} />
              <span class="ch-hit-main">
                <span class="ch-hit-top"><b>{p.name}</b><time>{whenSent(m.ts)}</time></span>
                <span class="ch-hit-text">
                  {#if m.mine}<i>You: </i>{/if}{#if m.text}{@html highlighted(snippetOf(m.text), listWords, discordInline)}{:else}Sent an attachment{/if}
                </span>
              </span>
            </button>
          {/each}
        </div>
      {/if}
      {#if !searchingList && recentShown.length > RECENT_FIRST}
        <button class="ch-recent-more" onclick={() => (showAllRecent = !showAllRecent)}>
          {showAllRecent ? "Show fewer" : `Show all ${recentShown.length}`}
          <span class="inline-flex transition-transform duration-200" style="transform: rotate({showAllRecent ? -90 : 90}deg)">
            <Icon name="chevron" size={11} />
          </span>
        </button>
      {/if}
    </section>
  {/if}
{:else}
  <div class="ch-inbox" class:show-detail={showDetail} use:fillHeight>
    <!-- ── Who is waiting ───────────────────────────────────────────────── -->
    <div class="ch-left">
      <!-- Find someone, or something someone said: names as you type, and the words of every kept message. Above the
           list rather than in it, so the list scrolls under nothing. -->
      <div class="ch-find">
        <label class="ch-find-box">
          <Icon name="search" size={13} />
          <input bind:value={listQuery} placeholder={browsingServers ? "Search channels" : "Search chats"}
                 spellcheck="false" autocomplete="off"
                 aria-label={browsingServers ? "Search channels" : "Search chats"}
                 onkeydown={(e) => { if (e.key === "Escape" && listQuery) { e.stopPropagation(); listQuery = ""; } }} />
          {#if listQuery}
            <button type="button" class="ch-find-x" onclick={() => (listQuery = "")} aria-label="Clear the search">
              <Icon name="close" size={10} />
            </button>
          {/if}
        </label>
        {#if hasServers && !allView}
          <!-- Not a filter: it puts the account's servers in the column instead of who is waiting, so it is a
               button of its own above them rather than one more pill among them. -->
          <button type="button" class="ch-go" class:is-on={browsingServers} data-sound="self" onclick={toggleServers}>
            <span class="ch-go-i"><Icon name={browsingServers ? "chevron" : "globe"} size={14} /></span>
            <span class="ch-go-t">{browsingServers
              ? "Back to chats"
              : plat.id === "telegram" ? "Its groups and channels" : "Its servers and channels"}</span>
            {#if !browsingServers}<span class="ch-go-go"><Icon name="chevron" size={12} /></span>{/if}
          </button>
        {/if}
        {#if listChips.length > 1 && !browsingServers}
          <div class="ch-chips" role="tablist" aria-label="Show" bind:this={chipBox}>
            <!-- One pill, sliding to the chip chosen, the way the app's other choices move. -->
            <span class="ch-chip-pill" class:is-shown={pill.shown} class:is-moving={pillMoves} aria-hidden="true"
                  style="width: {pill.w}px; height: {pill.h}px; transform: translate({pill.x}px, {pill.y}px)"></span>
            {#each listChips as chip (chip.id)}
              <button type="button" role="tab" aria-selected={listFilter === chip.id} class:is-on={listFilter === chip.id}
                      bind:this={chipEls[chip.id]} data-sound="self" onclick={() => setListFilter(chip.id)}>
                {chip.label}{#if chip.n}<b>{chip.n}</b>{/if}
              </button>
            {/each}
          </div>
        {/if}
      </div>
      {#if browsingServers}
        <ServerTree {target} open={selectedId} query={listQuery} waiting={waitingChannels} onpick={openChannel}
                    word={plat.id === "telegram" ? "group" : "server"} />
      {:else}
      <div class="ch-list domino" use:domino={{ step: 40, max: 12 }}>
      {#each shownSections as sec (sec.id)}
        <div class="ch-sec" data-tone={sec.tone}>
          <span class="ch-sec-dot"></span>{sec.title}<span class="ch-sec-n">{sec.rows.length}</span>
        </div>
        {#each sec.rows as { u, st: s } (keyOf(u))}
          {@const acc = accOf(u)}
          {@const via = allView ? accountOf(acc) : undefined}
          <div class="ch-item-wrap" class:is-bad={s.tone === "bad"} animate:flip={{ duration: 260 }} use:contextMenu={() => rowMenu(u)}>
          <button class="ch-item" class:is-sel={isOpen(u)} data-tone={s.tone} data-phase={s.phase}
                  onclick={() => openRow(u)}>
            <span class="ch-av halo" class:is-live={s.phase === "live"} class:is-fast={s.step === 2 || s.step === 4}>
              <Avatar src={u.avatar} name={u.name} size={42} zoom={false} silhouette={platOfRow(u).silhouette} />
              {#if u.count > 1}<span class="ch-badge">{u.count}</span>{/if}
              {#if via}
                <!-- Which of your accounts they wrote to: its picture, or its platform when it has none. -->
                <span class="ch-via" title="To {who(via)}{named(via) ? ` · ${slot(via)}` : ''}">
                  {#if via.avatar}<img src={via.avatar} alt="" />{:else}<Icon name={via.platform === "discord" ? "accounts" : platformIcon(via.platform)} size={9} />{/if}
                </span>
              {/if}
            </span>
            <span class="ch-item-main">
              <span class="ch-item-top">
                <span class="ch-name">{u.name}</span>
                {#if u.kind === "server" && u.where}<span class="ch-where" title={u.where}>{u.where}</span>{/if}
                <span class="ch-time">{ago(u.ts)}</span>
              </span>
              <span class="ch-preview">
                {#if callOf(u.id, acc)}
                  <!-- Calling the account, or in a call: said where the last message would be. -->
                  <span class="ch-call-tag" class:is-ringing={callOf(u.id, acc).state === "ringing"}>
                    <Icon name="phone" size={11} />{callOf(u.id, acc).state === "ringing" ? "Calling" : "In a call"}
                  </span>
                {:else if $typingNow[convKey(acc, u.id)]}
                  <!-- They are writing to it right now. -->
                  <span class="ch-typing">typing<i></i><i></i><i></i></span>
                {:else if !isOpen(u) && hasDraft(u.id, acc)}
                  <!-- Something you started writing to them and have not sent. -->
                  <span class="ch-draft">Draft:</span><span class="ch-draft-text">{draftOf(u.id, acc)}</span>
                {:else}
                  {#if hasMedia(u)}<span class="ch-preview-icon"><Icon name="pictures" size={11} /></span>{/if}
                  {preview(u)}
                {/if}
              </span>
              <span class="ch-state" data-tone={s.tone}>
                {#if s.phase === "live"}<span class="ch-state-pulse"></span>{/if}{s.short}
              </span>
            </span>
            {#if s.phase === "live" && s.eta}
              <svg class="ch-mini-ring" viewBox="0 0 20 20" aria-hidden="true">
                <circle cx="10" cy="10" r="8" class="track" />
                <circle cx="10" cy="10" r="8" class="fill" style="stroke-dashoffset: {50.27 * (1 - progress(s))}" />
              </svg>
            {/if}
          </button>
          <!-- Stop answering them, and stop trying, until they are let back in.
               On every row: it used to be only where a reply had failed. -->
          <button class="ch-x" onclick={(e) => ignorePerson(personOf(u), e, acc)} disabled={!!ignoreBusy[personOf(u).id]}
                  title="Ignore {u.name}: the bot stops answering them until you unignore them" aria-label="Ignore {u.name}">
            <Icon name="close" size={11} />
          </button>
          </div>
        {/each}
      {/each}

      {#if shownArchived.length}
        <button class="ch-sec is-button" onclick={() => (showPast = !showPast)} aria-expanded={pastOpen}>
          <span class="inline-flex transition-transform duration-200" style="transform: rotate({pastOpen ? 90 : 0}deg)">
            <Icon name="chevron" size={11} />
          </span>
          Answered<span class="ch-sec-n">{shownArchived.length}</span>
        </button>
        {#if pastOpen}
          {#each shownArchived as c (c.id)}
            {@const pacc = allView ? accountOf(pastAcc(c)) : undefined}
            <div class="ch-item-wrap" use:contextMenu={() => pastMenu(c)}>
              <button class="ch-item is-past" class:is-sel={c.id === selectedId && pastAcc(c) === target}
                      onclick={() => openArchived(c)}>
                <span class="ch-av">
                  <Avatar src={c.avatar} name={c.name} size={34} zoom={false}
                          silhouette={platformOf(pacc?.platform ?? current?.platform).silhouette} />
                  {#if pacc}
                    <!-- Which of your accounts answered them. -->
                    <span class="ch-via" title="To {who(pacc)}{named(pacc) ? ` \u00b7 ${slot(pacc)}` : ''}">
                      {#if pacc.avatar}<img src={pacc.avatar} alt="" />{:else}<Icon name={pacc.platform === "discord" ? "accounts" : platformIcon(pacc.platform)} size={9} />{/if}
                    </span>
                  {/if}
                </span>
                <span class="ch-item-main">
                  <span class="ch-item-top">
                    <span class="ch-name">{c.name}</span>
                    <span class="ch-time">{ago(c.last_ts)}</span>
                  </span>
                  <span class="ch-preview">
                    {#if c.id !== selectedId && hasDraft(c.id)}
                      <span class="ch-draft">Draft:</span><span class="ch-draft-text">{draftOf(c.id)}</span>
                    {:else}
                      {c.messages} message{c.messages === 1 ? "" : "s"}
                    {/if}
                  </span>
                </span>
              </button>
              <button class="ch-x" onclick={(e) => ignorePerson(c, e)} disabled={!!ignoreBusy[c.id]}
                      title="Ignore {c.name}: the bot stops answering them until you unignore them" aria-label="Ignore {c.name}">
                <Icon name="close" size={11} />
              </button>
            </div>
          {/each}
        {/if}
      {/if}

      {#if listQuery.trim().length >= 2 && (msgHits.messages.length || msgHits.loading)}
        <!-- Found in what was said, across every chat kept for this account. -->
        <div class="ch-sec">
          <span class="ch-sec-dot"></span>Messages
          {#if msgHits.loading && !msgHits.messages.length}<span class="ch-sec-spin"></span>{:else}<span class="ch-sec-n">{msgHits.messages.length}</span>{/if}
        </div>
        {#each msgHits.messages as m (`${m.uid}:${m.mid}`)}
          {@const p = personFor(String(m.uid))}
          <button type="button" class="ch-hit" onclick={() => openFromSearch(p, String(m.mid))}>
            <Avatar src={p.avatar} name={p.name} size={32} zoom={false} silhouette={plat.silhouette} />
            <span class="ch-hit-main">
              <span class="ch-hit-top"><b>{p.name}</b><time>{whenSent(m.ts)}</time></span>
              <span class="ch-hit-text">
                {#if m.mine}<i>You: </i>{/if}{#if m.text}{@html highlighted(snippetOf(m.text), listWords, discordInline)}{:else}Sent an attachment{/if}
              </span>
            </span>
          </button>
        {/each}
      {/if}
      {#if (searchingList || listFilter !== "all") && !shownSections.length && !(pastOpen && shownArchived.length) && !msgHits.messages.length && !msgHits.loading}
        <div class="ch-nothing">
          <Icon name="search" size={18} />
          <span>{searchingList ? "Nothing found" : "Nobody here"}</span>
          <button type="button" onclick={() => { listQuery = ""; listFilter = "all"; }}>Show everyone</button>
        </div>
      {/if}
      </div>
      {/if}
    </div>

    <!-- ── The conversation ─────────────────────────────────────────────── -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <section class="ch-detail glass" bind:clientWidth={detailW}
             ondragenter={onDragOver} ondragover={onDragOver} ondrop={onDrop}>
      {#if selected}
        <header class="cd-head" bind:clientWidth={headW}>
          <button class="cd-back" onclick={() => (showDetail = false)} aria-label="Back to the list">
            <Icon name="chevron" size={14} />
          </button>
          <span class="cd-av halo" class:is-live={st?.phase === "live"} class:is-fast={st?.step === 2 || st?.step === 4}>
            <Avatar src={headAvatar} name={selected.name} size={48} silhouette={plat.silhouette} />
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex min-w-0 items-center gap-2">
              <UserChip id={selected.id} name={selected.name} size="md" />
              {#if selected.count > 1 && !answered}<span class="cd-unread">{selected.count} unread</span>{/if}
              {#if callOf(selected.id)}
                {@const sc = callOf(selected.id)}
                <span class="cd-call" class:is-ringing={sc.state === "ringing"} title="As {plat.name} says it">
                  <Icon name="phone" size={11} /><span>{sc.state === "ringing" ? "Calling" : sc.state === "together" ? "On a call with you" : "In a call"}{#if sc.since}{" · "}{callFor(sc.since)}{/if}</span>
                </span>
              {/if}
            </div>
            <div class="truncate text-[11.5px] text-faint">
              {#if selected.username && selected.username !== selected.name}<span class="selectable">@{selected.username}</span>{" · "}{/if}
              {#if selected.browsed}
                {selected.where}{selected.topic ? ` · ${selected.topic}` : ""}
              {:else}
                {selected.kind === "server" && selected.where ? `${selected.where} · ` : ""}{selected.archived ? "answered" : `last message ${ago(selected.ts) === "now" ? "just now" : `${ago(selected.ts)} ago`}`}
                {#if selected.ts}{" · "}{at(selected.ts)}{/if}
              {/if}
            </div>
          </div>
          {#if canTools}
            <!-- Search the chat, and what was shared in it, the way Discord's buttons by the name do. -->
            <div class="cd-tools" role="toolbar" aria-label="This chat">
              <button type="button" class="cd-tool" class:is-on={toolsOpen && toolsTab === "search"} onclick={() => toggleTools("search")}
                      title="Search (Ctrl+F)" aria-label="Search" aria-pressed={toolsOpen && toolsTab === "search"}>
                <Icon name="search" size={15} />
              </button>
              {#if !compactHead}
                <button type="button" class="cd-tool" class:is-on={toolsOpen && toolsTab === "media"} onclick={() => toggleTools("media")}
                        title="Pictures and videos" aria-label="Pictures and videos" aria-pressed={toolsOpen && toolsTab === "media"}>
                  <Icon name="pictures" size={15} />
                </button>
                <button type="button" class="cd-tool" class:is-on={toolsOpen && toolsTab === "files"} onclick={() => toggleTools("files")}
                        title="Files" aria-label="Files" aria-pressed={toolsOpen && toolsTab === "files"}>
                  <Icon name="file" size={15} />
                </button>
                <button type="button" class="cd-tool" class:is-on={toolsOpen && toolsTab === "links"} onclick={() => toggleTools("links")}
                        title="Links" aria-label="Links" aria-pressed={toolsOpen && toolsTab === "links"}>
                  <Icon name="link" size={15} />
                </button>
              {/if}
              {#if tiktokPerson}
                <button type="button" class="cd-tool" class:is-on={toolsOpen && toolsTab === "tiktoks"} onclick={() => toggleTools("tiktoks")}
                        title="Their TikToks" aria-label="Their TikToks" aria-pressed={toolsOpen && toolsTab === "tiktoks"}>
                  <Icon name="tiktok" size={15} />
                </button>
              {/if}
              {#if instaPerson}
                <button type="button" class="cd-tool" class:is-on={toolsOpen && toolsTab === "posts"} onclick={() => toggleTools("posts")}
                        title="Their stories and posts" aria-label="Their stories and posts"
                        aria-pressed={toolsOpen && toolsTab === "posts"}>
                  <Icon name="instagram" size={15} />
                </button>
              {/if}
              <button type="button" class="cd-tool" onclick={moreMenu} title="More" aria-label="More">
                <Icon name="more" size={15} />
              </button>
            </div>
          {/if}
          {#if !selected.archived}
            <button class="cd-toggle" class:is-off={selected.ignored} onclick={() => flipIgnore(selected!)}
                    disabled={!!rowBusy[keyOf(selected)]}
                    title={selected.ignored ? "Let the bot answer them again" : "Stop the bot answering this person at all"}>
              <span class="cd-toggle-knob"></span>
              {selected.ignored ? "Bot off" : "Bot on"}
            </button>
          {/if}
        </header>

        <div class="cd-body">
        <div class="cd-main">
        <!-- Where the reply is. The tracker when the bot has it in hand, a
             callout when it needs you, a tick once it is answered. -->
        {#if selected.browsed}
          <!-- Walked into from the servers list: nothing is waiting, so there is no reply to report on. -->
        {:else if answered}
          <div class="cd-strip is-done" title={selected.archived ? "Nothing is waiting in this conversation" : "The reply went out"}>
            <span class="cd-strip-mark"><Icon name="check" size={11} /></span>
            <span class="cd-strip-text"><b>{selected.archived ? "Answered" : "Answered just now"}</b>
              <span>{selected.archived ? "nothing waiting" : "the reply went out"}</span></span>
          </div>
        {:else if st?.phase === "live"}
          <!-- Where the reply is, in one line: how long, what it is doing, and the six steps as dots. -->
          <div class="cd-strip is-live" title={st.detail || st.title}>
            {#if st.eta}
              <svg class="cd-ring" viewBox="0 0 40 40" aria-hidden="true">
                <circle cx="20" cy="20" r="16" class="track" />
                <circle cx="20" cy="20" r="16" class="fill" style="stroke-dashoffset: {100.5 * (1 - progress(st))}" />
              </svg>
            {:else}
              <span class="cd-strip-mark is-busy"><Icon name={st.step === 2 ? "sparkle" : "chats"} size={11} /></span>
            {/if}
            <span class="cd-strip-text"><b>{st.title}</b>{#if st.detail}<span>{st.detail}</span>{/if}</span>
            <span class="cd-steps" aria-label="{STEPS[st.step ?? 0]}, step {(st.step ?? 0) + 1} of {STEPS.length}">
              {#each STEPS as label, i}
                {#if i}<i class="cd-step-line" class:is-done={i <= (st.step ?? 0)}></i>{/if}
                <i class="cd-step" class:is-done={i < (st.step ?? 0)} class:is-now={i === st.step} title={label}></i>
              {/each}
            </span>
          </div>
        {:else if st}
          <div class="cd-strip" data-tone={st.tone} title={st.detail || st.title}>
            <span class="cd-strip-mark">
              <Icon name={st.phase === "off" ? "eyeOff" : st.tone === "bad" ? "alertCircle" : "info"} size={11} />
            </span>
            <span class="cd-strip-text"><b>{st.title}</b>{#if st.detail}<span>{st.detail}</span>{/if}</span>
          </div>
        {/if}

        {#if older && older.uid === selected.id}
          <!-- Reading an older stretch, from a search or the first message: the way back to now. -->
          <div class="cd-older-bar" transition:fade={{ duration: 140 }}>
            <Icon name="info" size={13} />
            <span class="min-w-0 flex-1 truncate">Viewing older messages</span>
            <button type="button" onclick={toPresent}>Jump to now<Icon name="arrowDown" size={12} /></button>
          </div>
        {/if}

        <!-- The conversation, as the conversation. -->
        <div class="cd-convwrap">
        <div class="cd-conv" bind:this={convBox} onscroll={onConvScroll}>
          {#if (older && older.uid === selected.id ? older.loadingUp : !!conv?.loading && !!conv.messages.length)}
            <div class="cd-earlier"><span class="cd-spin"></span></div>
          {:else if atStart && shownMsgs.length}
            <div class="cd-start-note"><Icon name="chats" size={13} />The start of your chat with {selected.name}</div>
          {/if}
          {#if conv?.loading && !conv.messages.length}
            <div class="cd-loading">
              {#each [60, 42, 70] as w, i}
                <div class="cd-skel" class:is-mine={i === 1} style="width:{w}%"></div>
              {/each}
            </div>
          {:else if !messages.length}
            <p class="py-10 text-center text-[12px] text-faint">No messages to show.</p>
          {/if}
          {#each drawn as d, i (d.m.mid ?? `${d.m.ts}:${i}`)}
            {#if d.day}<div class="cd-day"><span>{d.day}</span></div>{/if}
            <div class="cd-msg" class:is-mine={d.m.mine} class:is-first={d.first} class:is-last={d.last}
                 class:is-pending={d.m.pending} class:is-failed={d.m.failed} class:is-deleted={!!d.m.deleted}
                 class:is-flash={!!d.m.mid && String(d.m.mid) === flashMid} data-mid={d.m.mid ?? null}
                 use:contextMenu={(e) => messageMenu(d.m, e)}>
              {#if !d.m.mine}
                <!-- One picture per run, on its last message, the way chat apps
                     draw it: the messages above keep its width empty, so the run's
                     bubbles still line up, and a pack of messages reads as one
                     person speaking rather than a column of the same face. -->
                <span class="cd-msg-av">
                  {#if d.last}
                    <Avatar src={d.m.author?.avatar ?? headAvatar}
                            name={d.m.author?.name ?? selected.name} size={26} zoom={false} silhouette={plat.silhouette} />
                  {/if}
                </span>
              {/if}
              <div class="cd-wrap">
                <div class="cd-bubble">
                  {#if d.m.reply_to && (d.m.reply_to.text || d.m.reply_to.name)}
                    <!-- What it answers, as the apps show a reply: the quoted message, small, above it. Pressed, the
                         conversation goes to it, when it is one this conversation has. -->
                    <button type="button" class="cd-quote" title={d.m.reply_to.text}
                            disabled={!d.m.reply_to.mid}
                            onclick={() => { if (d.m.reply_to?.mid) { playSound("tap"); void jumpTo(d.m.reply_to.mid); } }}>
                      <Icon name="reply" size={11} />
                      {#if d.m.reply_to.name}<b>{d.m.reply_to.name}</b>{/if}
                      <span class="truncate">{d.m.reply_to.text || "a message"}</span>
                    </button>
                  {/if}
                  <MessageBody text={d.m.text ?? ""} attachments={d.m.attachments ?? []} stickers={d.m.stickers ?? []}
                               embeds={d.m.embeds ?? []}
                               onreveal={!d.m.mine && !selected.archived && !isSnap ? () => loadMessage(target, selected!.id) : undefined} />
                  {#if d.m.gift}
                    <!-- A Nitro gift link: what it is for and whether it is still there, with the button that
                         takes it. The account redeems it itself, so it lands on the account it was sent to. -->
                    {@const g = d.m.gift}
                    <div class="cd-gift" class:is-done={g.state === "accepted"} class:is-gone={GIFT_GONE.has(g.state ?? "")}>
                      <span class="cd-gift-mark"><Icon name="gift" size={15} /></span>
                      <span class="min-w-0 flex-1">
                        <b class="cd-gift-what">{g.what && g.what !== "a gift" ? g.what : "Nitro gift"}</b>
                        <span class="cd-gift-says">{giftSays(g)}</span>
                      </span>
                      {#if !d.m.mine && !GIFT_GONE.has(g.state ?? "") && g.state !== "accepted"}
                        <Button size="sm" loading={giftBusy === d.m.mid} onclick={() => takeGift(d.m)}>Accept</Button>
                      {/if}
                    </div>
                  {/if}
                  {#if d.m.deleted}
                    <!-- Deleted on Discord, and kept here (app/utils/chatlog.py): a bin on its corner says so. -->
                    <span class="cd-bin" title="{d.m.mine ? 'You deleted this' : `${d.m.author?.name ?? selected.name} deleted this`} · {fmtDate(d.m.deleted * 1000, FULL_WHEN)}">
                      <Icon name="trash" size={11} />
                    </span>
                  {/if}
                </div>
                {#if d.m.edited && !d.m.deleted}
                  <span class="cd-edited" title="Edited {fmtDate(d.m.edited * 1000, FULL_WHEN)}">edited</span>
                {/if}
                {#if d.m.reactions?.length}
                  <!-- What people tapped on it, the way Discord shows them: under
                       the message, the account's own ones marked. A press adds
                       the account's own, or takes it back. -->
                  <div class="cd-reacts">
                    {#each d.m.reactions as r (r.url || r.name)}
                      <button type="button" class="cd-react" class:is-mine={r.mine} data-sound="self"
                              disabled={!reactable(d.m) || (isSnap && !plat.reactions.includes(r.name))}
                              onclick={() => toggleReaction(d.m, r)}
                              title="{r.count} {r.count === 1 ? 'person' : 'people'} reacted with {r.name || 'this'}{r.mine ? ', including this account. Press to take it back' : '. Press to add yours'}">
                        {#if r.url}
                          <img src={r.url} alt={r.name} loading="lazy" referrerpolicy="no-referrer" />
                        {:else}
                          <span class="cd-react-e">{r.name}</span>
                        {/if}
                        <b>{r.count}</b>
                      </button>
                    {/each}
                  </div>
                {/if}
              </div>
              {#if reactable(d.m)}
                <!-- React, beside the message as the pointer passes, the way the apps do it. -->
                <button type="button" class="cd-react-add" class:is-open={reactingTo?.mid === String(d.m.mid)}
                        onclick={(e) => openReact(d.m, e)} title="React" aria-label="React to this message">
                  <Icon name="smilePlus" size={15} />
                </button>
                <button type="button" class="cd-react-add cd-reply-add" class:is-open={replyHere?.mid === String(d.m.mid)}
                        onclick={() => startReply(d.m)} title="Reply" aria-label="Reply to this message">
                  <Icon name="reply" size={14} />
                </button>
              {/if}
              <!-- When it was sent, beside it as the pointer passes. The last of
                   a run already says so underneath. -->
              {#if !d.last && d.m.ts && !d.m.approx}
                <span class="cd-time" title={fmtDate(d.m.ts * 1000, FULL_WHEN)}>{whenSent(d.m.ts)}</span>
              {/if}
            </div>
            {#if d.last}
              <div class="cd-meta" class:is-mine={d.m.mine} class:is-failed={d.m.failed}
                   title={d.m.ts ? fmtDate(d.m.ts * 1000, FULL_WHEN) : undefined}>
                {d.m.mine ? "You" : (d.m.author?.name ?? selected.name)}{#if d.m.pending}{" · "}sending{:else if d.m.failed}{" · "}not sent{:else if !d.m.approx}{" · "}{at(d.m.ts)}{/if}
              </div>
            {/if}
          {/each}
          {#if $typingNow[convKey(target, selected.id)] && !selected.archived}
            <!-- They are typing to it right now: the same dots as the bot's, on their side. -->
            <div class="cd-msg is-first is-last cd-their-typing">
              <span class="cd-msg-av"><Avatar src={headAvatar} name={selected.name} size={26} zoom={false} /></span>
              <div class="cd-bubble cd-typing" title="{selected.name} is typing"><i></i><i></i><i></i></div>
            </div>
          {/if}
          {#if st?.phase === "live" && (st.step === 2 || st.step === 4) && !answered}
            <!-- It is being written or typed right now: say so where the reply will appear. -->
            <div class="cd-msg is-mine is-first is-last">
              <div class="cd-bubble cd-typing" title={st.title}><i></i><i></i><i></i></div>
            </div>
          {/if}
          {#if older && older.uid === selected.id && older.loadingDown}
            <div class="cd-earlier"><span class="cd-spin"></span></div>
          {/if}
          {#if conv?.error && !selected.archived && !(older && older.uid === selected.id)}
            <p class="cd-note">
              Only their last message is shown: {conv.error}.
              <button class="text-accent hover:underline" onclick={() => loadConversation(target, selected!.id, true)}>Try again</button>
            </p>
          {/if}
        </div>
        {#if farFromNow && !(older && older.uid === selected.id)}
          <button type="button" class="cd-down" onclick={toPresent} aria-label="Back to the newest messages" title="Back to the newest"
                  transition:fade={{ duration: 120 }}>
            <Icon name="arrowDown" size={16} />
          </button>
        {/if}
        </div>

        {#if !selected.archived && !answered}
          <footer class="cd-actions">
            <Button onclick={() => reply(selected!)} loading={!!replying[selected.id]} disabled={busy}>
              {#if !replying[selected.id]}<Icon name="chats" size={14} />{/if}{replying[selected.id] ? "Replying" : "Reply now"}
            </Button>
            {#if (cancellable(selected) || replying[selected.id]) && !selected.ignored}
              <!-- There while a reply is being written by hand too: it stops it, and whatever went out already stays. -->
              <Button kind="ghost" onclick={() => cancel(selected!)} disabled={!!rowBusy[keyOf(selected)]}>
                <Icon name="close" size={12} />Cancel the reply
              </Button>
            {/if}
          </footer>
        {/if}
        {#if selected?.readonly}
          <!-- A channel of a server where this account may read but not post: said here rather than letting you
               write something Discord would refuse. -->
          <p class="cd-readonly">
            <Icon name="eye" size={13} />It can read this channel, not post in it.
          </p>
        {:else if selected}
          <!-- Write to them yourself, as the account. A reply the bot had lined up is dropped when you do. -->
          <form class="cd-compose" onsubmit={(e) => { e.preventDefault(); sendDraft(); }}>
            {#if replyHere}
              <div class="cd-replying" transition:fade={{ duration: $motionEnabled ? 140 : 0 }}>
                <Icon name="reply" size={13} />
                <span class="min-w-0 flex-1 truncate">Replying to <b>{replyHere.name}</b> · {replyHere.text}</span>
                <button type="button" class="cd-replying-x" onclick={letGoOfReply} aria-label="Do not reply to it"
                        title="Not a reply (Esc)">
                  <Icon name="close" size={10} />
                </button>
              </div>
            {/if}
            {#if stagedHere.length}
              <!-- Pasted pictures, before they go. -->
              <div class="cd-staged">
                {#each stagedHere as f, i (f.preview)}
                  <span class="cd-staged-item" title="{f.name} · {(f.size / 1024).toFixed(0)}KB">
                    {#if f.type.startsWith("image/")}
                      <img src={f.preview} alt={f.name} />
                    {:else}
                      <span class="cd-staged-file"><Icon name="clipboard" size={15} />{f.name}</span>
                    {/if}
                    <button type="button" class="cd-staged-x" onclick={() => unstage(i)}
                            aria-label="Take {f.name} off">
                      <Icon name="close" size={10} />
                    </button>
                  </span>
                {/each}
              </div>
            {/if}
            <div class="cd-compose-row">
              <!-- Nothing to attach where the chat is words only (a game's). -->
              {#if plat.media !== false}
              <button type="button" class="cd-attach" onclick={() => filePick?.click()}
                      aria-label={isSnap ? "Attach a picture" : "Attach files"}
                      title={isSnap ? "Attach a picture. You can also paste or drop one" : "Attach files. You can also paste or drop them"}>
                <Icon name={isSnap ? "pictures" : "plus"} size={15} />
              </button>
              {/if}
              <input bind:this={filePick} type="file" multiple accept={isSnap ? "image/*" : ACCEPT}
                     class="hidden" onchange={(e) => {
                       const t = e.currentTarget as HTMLInputElement;
                       stageFiles([...(t.files ?? [])]);
                       t.value = "";
                     }} />
              <textarea bind:this={composer} value={$drafts[draftKey] ?? ""} rows="1" maxlength="2000"
                        placeholder="Message {selected.kind === 'server' ? (selected.where ?? '').split(' · ')[0] || selected.name : selected.name}"
                        onkeydown={onComposerKey} onpaste={onComposerPaste}
                        oninput={(e) => { setDraft(draftKey, e.currentTarget.value); grow(); }}
                        aria-label="Message {selected.name}"></textarea>
              <button class="cd-send" type="submit"
                      disabled={(!($drafts[draftKey] ?? "").trim() && !stagedHere.length) || sendingOwn}
                      aria-label="Send" title="Send (Enter). Shift+Enter for a new line">
                <Icon name="send" size={15} />
              </button>
            </div>
          </form>
        {/if}
        </div>

        {#if toolsOpen && canTools}
          <div class="cd-side" class:is-overlay={sideOverlay} transition:sideIn={{ overlay: sideOverlay }}>
            <div class="cd-side-in">
              {#key `${target}:${selected.id}`}
                <ChatTools bind:tab={toolsTab} {target} uid={selected.id} platform={current?.platform ?? "discord"}
                           them={{ name: selected.name, username: selected.username, avatar: headAvatar }}
                           me={{ name: current ? who(current) : "You", avatar: current?.avatar }}
                           focusKey={toolsFocus} onjump={jumpTo} onclose={() => (toolsOpen = false)} />
              {/key}
            </div>
          </div>
        {/if}
        </div>

        {#if dragging}
          <!-- Files over the conversation: where they will go. -->
          <div class="cd-drop" transition:fade={{ duration: 120 }}>
            <div class="cd-drop-card">
              <span class="cd-drop-icon"><Icon name="upload" size={22} /></span>
              <b>Drop to add to your message</b>
              <span>to {selected.name}{isSnap ? ", pictures only" : ""}</span>
            </div>
          </div>
        {/if}
      {:else}
        <div class="flex h-full flex-col items-center justify-center gap-2 p-10 text-center">
          <span class="text-faint"><Icon name="chats" size={26} /></span>
          <p class="text-[12.5px] text-muted">Pick a conversation on the left.</p>
        </div>
      {/if}
    </section>
  </div>
{/if}

{#if reactingTo && selected}
  {@const rm = shownMsgs.find((x) => String(x.mid) === reactingTo?.mid)}
  {#if rm}
    <ReactPicker anchor={reactingTo.anchor} snap={isSnap} set={isSnap ? plat.reactions : undefined}
                 any={!!plat.anyReaction}
                 mine={(rm.reactions ?? []).filter((r) => r.mine).map((r) => r.name)}
                 onpick={(emoji, add) => react(rm, { name: emoji }, add)} onclose={() => (reactingTo = null)} />
  {/if}
{/if}

<style>
  /* ── Top ──────────────────────────────────────────────────────────── */
  .ch-top {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px 16px;
    margin-bottom: 14px;
  }
  .ch-account {
    display: flex;
    align-items: center;
    gap: 10px;
    /* No wider than the space it is given: a button is as wide as its words, and in a narrow window they ran on
       under the buttons beside it instead of being cut short. */
    max-width: 100%;
    padding: 6px 10px 6px 6px;
    border-radius: 14px;
    text-align: left;
    transition: background-color 0.15s ease;
  }
  .ch-account.is-button:hover, .ch-account.is-open { background: rgb(255 255 255 / 0.05); }
  .ch-stats { display: flex; flex-wrap: wrap; gap: 6px; }
  .ch-stat {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 11.5px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
  }
  .ch-stat b { font-weight: 700; color: var(--color-ink); font-variant-numeric: tabular-nums; }
  .ch-stat.is-accent b { color: var(--color-accent); }
  .ch-stat.is-live i {
    width: 6px;
    height: 6px;
    border-radius: 999px;
    background: var(--color-good);
    animation: ch-pulse 1.6s ease-in-out infinite;
  }
  .ch-livebadge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: var(--color-faint);
  }
  .ch-livebadge i {
    width: 7px;
    height: 7px;
    border-radius: 999px;
    background: var(--color-good);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-good) 16%, transparent);
  }
  .ch-livebadge i.is-busy { background: var(--color-accent); animation: ch-pulse 1s ease-in-out infinite; }

  /* ── Calls ───────────────────────────────────────────────────────── */
  .ch-calls { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
  .ch-call {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 6px 14px 6px 6px;
    border-radius: 999px;
    text-align: left;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-good) 10%, var(--color-card));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-good) 35%, transparent), 0 10px 26px -16px var(--color-good);
    transition: transform 0.35s var(--jelly), box-shadow 0.2s ease;
    animation: ch-call-in 0.45s var(--jelly);
  }
  @keyframes ch-call-in { from { opacity: 0; transform: translateY(-6px) scale(0.94); } }
  .ch-call:hover { transform: translateY(-1px); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-good) 60%, transparent), 0 14px 30px -14px var(--color-good); }
  .ch-call-av { position: relative; display: grid; place-items: center; }
  /* Ringing: rings go out from their picture, as a phone's call screen. */
  .ch-call-ring {
    position: absolute;
    inset: 0;
    border-radius: 999px;
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-good) 70%, transparent);
    opacity: 0;
  }
  .ch-call.is-ringing .ch-call-ring { animation: ch-call-ring 1.6s ease-out infinite; }
  .ch-call.is-ringing .ch-call-ring.is-late { animation-delay: 0.8s; }
  @keyframes ch-call-ring { from { opacity: 0.9; transform: scale(1); } to { opacity: 0; transform: scale(1.7); } }
  .ch-call-text { display: flex; min-width: 0; flex-direction: column; line-height: 1.25; }
  .ch-call-text b { font-size: 12.5px; font-weight: 650; }
  .ch-call-text small { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--color-good);
                        font-variant-numeric: tabular-nums; }
  /* The last thing said on a live call, as a call screen shows it. */
  .ch-call-live { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                  color: var(--color-text, inherit); opacity: 0.85; }
  .ch-call-icon { display: grid; }
  .ch-call.is-ringing .ch-call-icon { animation: ch-call-shake 1.2s ease-in-out infinite; transform-origin: 50% 60%; }
  @keyframes ch-call-shake { 0%, 50%, 100% { transform: rotate(0); } 10%, 30% { transform: rotate(-16deg); } 20%, 40% { transform: rotate(16deg); } }
  .ch-call-tag {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-weight: 600;
    color: var(--color-good);
  }
  .ch-call-tag.is-ringing :global(svg) { animation: ch-call-shake 1.2s ease-in-out infinite; transform-origin: 50% 60%; }
  .cd-call {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 2px 9px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 650;
    font-variant-numeric: tabular-nums;
    color: var(--color-good);
    background: color-mix(in srgb, var(--color-good) 13%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-good) 30%, transparent);
    animation: ch-call-in 0.4s var(--jelly);
  }
  .cd-call.is-ringing :global(svg) { animation: ch-call-shake 1.2s ease-in-out infinite; transform-origin: 50% 60%; }

  /* ── Adding a friend ─────────────────────────────────────────────── */
  .ch-add {
    position: absolute;
    right: 0;
    top: calc(100% + 6px);
    z-index: 40;
    display: flex;
    width: 290px;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding: 12px;
    border-radius: 16px;
    animation: ch-add-in 0.25s var(--jelly);
  }
  @keyframes ch-add-in { from { opacity: 0; transform: translateY(-4px) scale(0.96); } }
  .ch-add-head { width: 100%; font-size: 11px; font-weight: 650; letter-spacing: 0.08em; text-transform: uppercase; color: var(--color-faint); }
  .ch-add-box {
    display: flex;
    min-width: 0;
    flex: 1;
    align-items: center;
    gap: 2px;
    padding: 0 10px;
    border-radius: 10px;
    background: rgb(0 0 0 / 0.22);
    box-shadow: inset 0 0 0 1px var(--color-edge);
  }
  .ch-add-box:focus-within { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, transparent),
                                         0 0 0 3px color-mix(in srgb, var(--color-accent) 14%, transparent); }
  .ch-add-at { font-size: 13px; color: var(--color-faint); }
  .ch-add-box input { min-width: 0; flex: 1; padding: 7px 0; font-size: 13px; color: var(--color-ink); background: transparent; outline: none; }
  /* iMessage's: their number or email on a line of its own, the first message and Send under it. */
  .ch-add.is-text { width: min(340px, calc(100vw - 32px)); }
  .ch-add.is-text .ch-add-box.is-who { flex-basis: 100%; }

  /* ── Friend requests ─────────────────────────────────────────────── */
  .ch-friends {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 14px;
    padding: 8px 8px 8px 14px;
    border-radius: 16px;
    background: color-mix(in srgb, var(--color-card) 60%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
  }
  .ch-friends-label {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    font-weight: 600;
    color: var(--color-muted);
  }
  .ch-friends-label b {
    padding: 0 6px;
    border-radius: 999px;
    font-size: 10.5px;
    color: var(--color-bg);
    background: var(--color-accent);
  }
  .ch-friends-list {
    display: flex;
    min-width: 0;
    flex: 1;
    gap: 6px;
    overflow-x: auto;
    scrollbar-width: none;
  }
  .ch-fr {
    display: flex;
    flex-shrink: 0;
    align-items: center;
    gap: 9px;
    max-width: 280px;
    padding: 5px 5px 5px 6px;
    border-radius: 12px;
    background: rgb(255 255 255 / 0.04);
  }
  .ch-fr-btn {
    display: grid;
    width: 26px;
    height: 26px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 8px;
    color: var(--color-faint);
    transition: background-color 0.15s ease, color 0.15s ease, transform 0.15s var(--spring);
  }
  .ch-fr-btn:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
  .ch-fr-btn.is-yes { color: var(--color-good); background: color-mix(in srgb, var(--color-good) 14%, transparent); }
  .ch-fr-btn.is-yes:hover:not(:disabled) { color: var(--color-bg); background: var(--color-good); }
  .ch-fr-btn:active:not(:disabled) { transform: scale(0.9); }

  /* ── The inbox ───────────────────────────────────────────────────── */
  .ch-inbox {
    display: grid;
    /* Exactly the space left in the window (lib/fillheight.ts): the list and the conversation each scroll on their
       own, and the Reply button is always on screen. */
    height: var(--fill-h, calc(100dvh - 120px));
    grid-template-columns: minmax(270px, 340px) minmax(0, 1fr);
    gap: 14px;
  }
  .ch-list {
    display: flex;
    min-height: 0;
    min-width: 0;
    flex-direction: column;
    gap: 3px;
    overflow-y: auto;
    padding: 2px 6px 12px 2px;
  }

  .ch-sec {
    --t: var(--color-accent);
    display: flex;
    align-items: center;
    gap: 7px;
    margin: 10px 6px 4px;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--color-faint);
  }
  .ch-sec:first-child { margin-top: 0; }
  .ch-sec[data-tone="warn"] { --t: var(--color-warn); }
  .ch-sec[data-tone="muted"] { --t: var(--color-faint); }
  .ch-sec-dot { width: 6px; height: 6px; border-radius: 999px; background: var(--t); }
  .ch-sec-n {
    padding: 0 6px;
    border-radius: 999px;
    font-size: 10px;
    letter-spacing: 0;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.06);
  }
  .ch-sec.is-button { cursor: pointer; margin-top: 16px; }
  .ch-sec.is-button:hover { color: var(--color-muted); }

  .ch-item {
    --t: var(--color-accent);
    position: relative;
    display: flex;
    width: 100%;
    align-items: center;
    gap: 11px;
    padding: 9px 11px 9px 9px;
    border-radius: 16px;
    text-align: left;
    transition: background-color 0.16s ease, box-shadow 0.16s ease, transform 0.18s var(--spring);
  }
  .ch-item[data-tone="warn"] { --t: var(--color-warn); }
  .ch-item[data-tone="bad"] { --t: var(--color-bad); }
  .ch-item[data-tone="good"] { --t: var(--color-good); }
  .ch-item[data-tone="muted"] { --t: var(--color-faint); }
  .ch-item:hover { background: rgb(255 255 255 / 0.04); }
  .ch-item:active { transform: scale(0.99); }
  .ch-item.is-sel {
    background: color-mix(in srgb, var(--color-accent) 12%, rgb(255 255 255 / 0.02));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 30%, transparent);
  }
  .ch-item[data-phase="off"] :global(img), .ch-item[data-phase="off"] .ch-name { opacity: 0.55; }

  .ch-av { position: relative; flex-shrink: 0; }
  .ch-badge {
    position: absolute;
    right: -4px;
    top: -4px;
    min-width: 18px;
    padding: 0 5px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 700;
    line-height: 18px;
    text-align: center;
    color: var(--color-bg);
    background: var(--color-accent);
    box-shadow: 0 0 0 2px var(--color-surface);
  }
  /* All chats: which of your accounts a row was written to, on the other corner of its picture from the count. */
  .ch-via {
    position: absolute;
    left: -3px;
    bottom: -3px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    overflow: hidden;
    border-radius: 999px;
    color: var(--color-accent);
    background: var(--color-card);
    box-shadow: 0 0 0 2px var(--color-surface);
  }
  .ch-via img { width: 100%; height: 100%; object-fit: cover; }

  /* All chats in the picker: the accounts' pictures in a cluster, the way a group shows its members, in the same
     square a single account's picture takes so the names beside them line up. */
  .ch-stack { position: relative; flex-shrink: 0; width: 36px; height: 36px; }
  .ch-stack > * {
    position: absolute;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: 999px;
    object-fit: cover;
    color: var(--color-accent);
    background: rgb(255 255 255 / 0.06);
    box-shadow: 0 0 0 2px var(--color-card);
  }
  .ch-stack > :nth-child(1) { left: 0; top: 2px; }
  .ch-stack > :nth-child(2) { right: 0; top: 2px; }
  .ch-stack > :nth-child(3) { left: 7px; bottom: 0; z-index: 1; }
  /* Two accounts sit side by side, centred, rather than in the top half of the square. */
  .ch-stack > :nth-child(1):nth-last-child(2), .ch-stack > :nth-child(2):nth-last-child(1) { top: 7px; }
  .ch-stack.is-small { width: 32px; height: 32px; }
  .ch-stack.is-small > * { width: 19px; height: 19px; }
  .ch-stack.is-small > :nth-child(3) { left: 6.5px; }
  .ch-stack.is-small > :nth-child(1):nth-last-child(2), .ch-stack.is-small > :nth-child(2):nth-last-child(1) { top: 6.5px; }

  /* People waiting on a reply: per account in the picker, and on the closed picker for the accounts not on screen.
     The same solid accent as the counts on the list's own pictures. */
  .ch-waiting, .ch-elsewhere {
    flex-shrink: 0;
    min-width: 18px;
    height: 18px;
    padding: 0 5px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    line-height: 18px;
    text-align: center;
    color: var(--color-bg);
    background: var(--color-accent);
    box-shadow: 0 4px 12px -5px color-mix(in srgb, var(--color-accent) 75%, transparent);
    animation: ch-pop 0.45s var(--spring) both;
  }
  .ch-elsewhere { margin-left: 6px; }
  :global(:root[data-motion="off"]) .ch-waiting, :global(:root[data-motion="off"]) .ch-elsewhere { animation: none; }
  .ch-pick-sep { height: 1px; margin: 3px 8px; background: var(--color-edge); }
  .ch-item-main { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 1px; }
  .ch-item-top { display: flex; align-items: baseline; gap: 8px; }
  /* "#channel · Server", on a server conversation's row. */
  .ch-where {
    min-width: 0;
    max-width: 55%;
    overflow: hidden;
    flex-shrink: 1;
    padding: 1px 7px;
    border-radius: 999px;
    font-size: 10.5px;
    white-space: nowrap;
    text-overflow: ellipsis;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.06);
  }
  .ch-name {
    min-width: 0;
    flex: 1;
    overflow: hidden;
    font-size: 13.5px;
    font-weight: 600;
    color: var(--color-ink);
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .ch-time { flex-shrink: 0; font-size: 11px; color: var(--color-faint); font-variant-numeric: tabular-nums; }
  .ch-preview {
    display: flex;
    align-items: center;
    gap: 5px;
    overflow: hidden;
    font-size: 12.5px;
    color: var(--color-muted);
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .ch-preview-icon { display: inline-flex; flex-shrink: 0; color: var(--color-faint); }
  .ch-state {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    margin-top: 1px;
    font-size: 11px;
    font-weight: 500;
    color: color-mix(in srgb, var(--t) 85%, var(--color-ink));
  }
  .ch-item[data-tone="muted"] .ch-state { color: var(--color-faint); }
  .ch-state-pulse { width: 6px; height: 6px; border-radius: 999px; background: var(--t); animation: ch-pulse 1.4s ease-in-out infinite; }
  .ch-mini-ring { width: 20px; height: 20px; flex-shrink: 0; transform: rotate(-90deg); }
  .ch-mini-ring circle, .cd-ring circle { fill: none; stroke-width: 2.5; }
  .ch-mini-ring .track, .cd-ring .track { stroke: rgb(255 255 255 / 0.08); }
  .ch-mini-ring .fill {
    stroke: var(--color-accent);
    stroke-dasharray: 50.27;
    stroke-linecap: round;
    transition: stroke-dashoffset 1s linear;
  }
  .ch-item.is-past { padding-top: 6px; padding-bottom: 6px; }
  .ch-item-wrap { position: relative; }
  .ch-x {
    position: absolute;
    right: 8px;
    top: 8px;
    display: grid;
    width: 22px;
    height: 22px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.06);
    opacity: 0;
    transition: opacity 0.15s ease, color 0.15s ease, background-color 0.15s ease, transform 0.15s var(--spring);
  }
  .ch-item-wrap:hover .ch-x, .ch-x:focus-visible { opacity: 1; }
  /* On a reply that failed it is always there: that is when you want it. */
  .ch-item-wrap.is-bad .ch-x { opacity: 1; color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 14%, transparent); }
  .ch-x:hover:not(:disabled) { color: #fff; background: var(--color-bad); transform: scale(1.08); }
  .ch-item-wrap:hover .ch-time { visibility: hidden; }
  /* Where the X always shows, the time moves over for it instead of sitting underneath. */
  .ch-item-wrap.is-bad .ch-item-top { padding-right: 24px; }
  .ch-item-wrap.is-bad:hover .ch-time { visibility: visible; }
  /* A reply in progress keeps its ring, except while the X sits over it. */
  .ch-item-wrap:hover .ch-mini-ring { opacity: 0; }

  .ch-ignored-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    border-radius: 10px;
    font-size: 12px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .ch-ignored-btn:hover, .ch-ignored-btn.is-open { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
  .ch-ignored-btn b {
    padding: 0 6px;
    border-radius: 999px;
    font-size: 10.5px;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.1);
  }
  .ch-ignored {
    position: absolute;
    right: 0;
    top: calc(100% + 6px);
    z-index: 40;
    width: min(320px, 86vw);
    overflow: hidden;
    border-radius: 14px;
    box-shadow: 0 20px 50px -20px rgb(0 0 0 / 0.8);
    animation: cd-in 0.2s var(--swift) both;
  }
  .ch-ignored-head {
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 11px 14px 9px;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--color-faint);
    border-bottom: 1px solid color-mix(in srgb, var(--color-edge) 70%, transparent);
  }
  .ch-ignored-list { max-height: 320px; overflow-y: auto; padding: 4px; }
  .ch-ignored-row { display: flex; align-items: center; gap: 10px; padding: 7px 8px; border-radius: 10px; }
  .ch-ignored-row:hover { background: rgb(255 255 255 / 0.04); }
  .ch-unignore {
    flex-shrink: 0;
    padding: 4px 10px;
    border-radius: 8px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
    transition: background-color 0.15s ease, color 0.15s ease;
  }
  .ch-unignore:hover:not(:disabled) { color: var(--color-bg); background: var(--color-accent); }

  /* ── Finding someone ─────────────────────────────────────────────── */
  .ch-left { display: flex; min-width: 0; min-height: 0; flex-direction: column; gap: 10px; }
  .ch-left .ch-list { flex: 1; }
  .ch-find { display: flex; flex-direction: column; gap: 9px; padding: 2px 8px 0 2px; }
  .ch-find-box {
    display: flex;
    align-items: center;
    gap: 9px;
    height: 40px;
    padding: 0 9px 0 13px;
    border-radius: 14px;
    color: var(--color-faint);
    background: linear-gradient(180deg, rgb(255 255 255 / 0.06), rgb(255 255 255 / 0.025));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 90%, transparent),
                0 12px 30px -22px rgb(0 0 0 / 0.95);
    backdrop-filter: blur(14px);
    transition: box-shadow 0.25s var(--swift), color 0.2s ease, background-color 0.25s ease;
  }
  .ch-find-box:hover {
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 28%, var(--color-edge)),
                0 12px 30px -22px rgb(0 0 0 / 0.95);
  }
  .ch-find-box:focus-within {
    color: var(--color-accent);
    background: linear-gradient(180deg, color-mix(in srgb, var(--color-accent) 9%, rgb(255 255 255 / 0.05)), rgb(255 255 255 / 0.025));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, transparent),
                0 0 0 4px color-mix(in srgb, var(--color-accent) 13%, transparent),
                0 14px 32px -18px color-mix(in srgb, var(--color-accent) 55%, transparent);
  }
  .ch-find-box > :global(svg) { flex-shrink: 0; transition: transform 0.4s var(--spring); }
  .ch-find-box:focus-within > :global(svg) { transform: scale(1.12) rotate(-10deg); }
  .ch-find-box input {
    min-width: 0;
    flex: 1;
    font-size: 13px;
    letter-spacing: 0.01em;
    color: var(--color-ink);
    background: transparent;
    outline: none;
  }
  .ch-find-box input::placeholder { color: var(--color-faint); transition: opacity 0.2s ease; }
  .ch-find-box:focus-within input::placeholder { opacity: 0.6; }
  .ch-find-x {
    display: grid;
    width: 22px;
    height: 22px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.08);
    animation: ch-pop 0.25s var(--spring) both;
    transition: color 0.15s ease, background-color 0.15s ease, transform 0.2s var(--spring);
  }
  .ch-find-x:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.15); transform: rotate(90deg); }
  /* The way into the account's servers. A button, not a pill: it changes what the column is, and the chevron says
     it opens onto something rather than filtering what is already there. */
  .ch-go {
    display: flex; width: 100%; align-items: center; gap: 9px; border-radius: 12px; padding: 8px 10px;
    font-size: 12.5px; font-weight: 600; color: var(--color-muted);
    background: rgb(255 255 255 / 0.035);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    transition: color 0.16s ease, background-color 0.16s ease, box-shadow 0.2s ease, transform 0.18s var(--jelly);
  }
  .ch-go:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.07); transform: translateY(-1px); }
  .ch-go:active { transform: scale(0.99); }
  .ch-go.is-on {
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 34%, transparent);
  }
  .ch-go-i { display: flex; color: var(--color-accent); }
  .ch-go.is-on .ch-go-i { transform: rotate(180deg); }
  .ch-go-t { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ch-go-go { margin-left: auto; display: flex; color: var(--color-faint); }
  .ch-go:hover .ch-go-go { color: var(--color-muted); transform: translateX(2px); }
  .ch-go-go, .ch-go-i { transition: transform 0.2s var(--jelly), color 0.16s ease; }
  :global(:root[data-motion="off"]) .ch-go,
  :global(:root[data-motion="off"]) .ch-go-go,
  :global(:root[data-motion="off"]) .ch-go-i { transition: none; }

  .ch-chips { position: relative; display: flex; flex-wrap: wrap; gap: 6px; }
  .ch-chip-pill {
    position: absolute;
    left: 0;
    top: 0;
    border-radius: 999px;
    background: linear-gradient(135deg, color-mix(in srgb, var(--color-accent) 92%, #fff 8%),
                                        color-mix(in srgb, var(--color-accent) 78%, #000 8%));
    box-shadow: 0 6px 18px -8px var(--color-accent), inset 0 1px 0 rgb(255 255 255 / 0.28);
    opacity: 0;
    pointer-events: none;
  }
  .ch-chip-pill.is-shown { opacity: 1; }
  .ch-chip-pill.is-moving {
    transition: transform 0.45s var(--spring), width 0.45s var(--spring), height 0.3s ease, opacity 0.2s ease;
  }
  .ch-chips button {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 28px;
    padding: 0 11px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 600;
    white-space: nowrap;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.035);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 75%, transparent);
    transition: color 0.25s ease, background-color 0.25s ease, box-shadow 0.25s ease, transform 0.22s var(--spring);
  }
  .ch-chips button:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.075); }
  .ch-chips button:active { transform: scale(0.94); }
  /* The chosen one sits on the pill: no box of its own. */
  .ch-chips button.is-on { color: #fff; background: transparent; box-shadow: none; }
  .ch-chips b {
    min-width: 18px;
    padding: 0 5px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 700;
    line-height: 16px;
    text-align: center;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.1);
    transition: color 0.25s ease, background-color 0.25s ease;
  }
  .ch-chips button.is-on b { color: color-mix(in srgb, var(--color-accent) 80%, #000 20%); background: #fff; }
  @keyframes ch-pop { from { opacity: 0; transform: scale(0.6); } to { opacity: 1; transform: none; } }
  :global(:root[data-motion="off"]) .ch-chip-pill.is-moving,
  :global(:root[data-motion="off"]) .ch-find-box > :global(svg),
  :global(:root[data-motion="off"]) .ch-find-x { transition: none; animation: none; }
  .ch-draft { flex-shrink: 0; font-weight: 600; color: var(--color-accent); }
  .ch-draft-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--color-muted); }
  .ch-sec-spin, .cd-spin {
    width: 10px;
    height: 10px;
    border-radius: 999px;
    border: 1.5px solid color-mix(in srgb, var(--color-accent) 30%, transparent);
    border-top-color: var(--color-accent);
    animation: ch-spin 0.7s linear infinite;
  }
  .ch-hit {
    display: flex;
    width: 100%;
    align-items: flex-start;
    gap: 10px;
    padding: 8px 10px 8px 9px;
    border-radius: 14px;
    text-align: left;
    transition: background-color 0.15s ease;
  }
  .ch-hit:hover { background: rgb(255 255 255 / 0.045); }
  .ch-hit-main { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 2px; }
  .ch-hit-top { display: flex; align-items: baseline; gap: 8px; font-size: 12.5px; }
  .ch-hit-top b { min-width: 0; flex: 1; overflow: hidden; font-weight: 600; color: var(--color-ink); white-space: nowrap; text-overflow: ellipsis; }
  .ch-hit-top time { flex-shrink: 0; font-size: 10.5px; color: var(--color-faint); font-variant-numeric: tabular-nums; }
  .ch-hit-text {
    display: -webkit-box;
    overflow: hidden;
    font-size: 12px;
    line-height: 1.4;
    color: var(--color-muted);
    word-break: break-word;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
  }
  .ch-hit-text i { font-style: normal; color: var(--color-faint); }
  .ch-hit-text :global(mark) {
    padding: 0 2px;
    border-radius: 4px;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 36%, transparent);
  }
  .ch-hit-text :global(.dm-emoji) { display: inline-block; width: 1.2em; height: 1.2em; vertical-align: -0.25em; }
  .ch-nothing {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 34px 10px;
    font-size: 12.5px;
    color: var(--color-faint);
  }
  .ch-nothing button { font-size: 11.5px; font-weight: 600; color: var(--color-accent); }
  .ch-nothing button:hover { text-decoration: underline; }

  /* ── The conversation ────────────────────────────────────────────── */
  .ch-detail {
    position: relative;
    display: flex;
    min-height: 0;
    min-width: 0;
    flex-direction: column;
    overflow: hidden;
    border-radius: 20px;
  }
  /* What is under the name: the conversation, and the panel beside it when it is open. */
  .cd-body { position: relative; display: flex; min-height: 0; flex: 1; }
  .cd-main { display: flex; min-width: 0; min-height: 0; flex: 1; flex-direction: column; }
  .cd-convwrap { position: relative; display: flex; min-height: 0; flex: 1; flex-direction: column; }
  .cd-side {
    display: flex;
    width: 384px;
    min-height: 0;
    flex-shrink: 0;
    overflow: hidden;
    border-left: 1px solid color-mix(in srgb, var(--color-edge) 70%, transparent);
    background: rgb(0 0 0 / 0.12);
  }
  .cd-side-in { display: flex; width: 384px; min-width: 384px; min-height: 0; flex-direction: column; container-type: inline-size; }
  /* Over the conversation when there is no room beside it: solid, so the messages behind do not show through it. */
  .cd-side.is-overlay {
    position: absolute;
    inset: 0;
    z-index: 6;
    width: auto;
    border-left: none;
    background: linear-gradient(180deg, color-mix(in srgb, var(--color-bg) 94%, var(--color-accent) 6%), var(--color-bg));
    backdrop-filter: blur(24px);
  }
  .cd-side.is-overlay .cd-side-in { width: 100%; min-width: 0; }
  .cd-tools {
    display: flex;
    flex-shrink: 0;
    align-items: center;
    gap: 2px;
    padding: 3px;
    border-radius: 12px;
    background: rgb(255 255 255 / 0.03);
  }
  .cd-tool {
    display: grid;
    width: 32px;
    height: 32px;
    place-items: center;
    border-radius: 9px;
    color: var(--color-muted);
    transition: color 0.15s ease, background-color 0.15s ease, transform 0.2s var(--spring);
  }
  .cd-tool:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
  .cd-tool:active { transform: scale(0.92); }
  .cd-tool.is-on { color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 16%, transparent); }
  .cd-older-bar {
    display: flex;
    align-items: center;
    gap: 9px;
    margin: 10px 14px 0;
    padding: 7px 7px 7px 12px;
    border-radius: 12px;
    font-size: 12px;
    color: var(--color-muted);
    background: color-mix(in srgb, var(--color-accent) 10%, rgb(255 255 255 / 0.03));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 25%, transparent);
  }
  .cd-older-bar button {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 5px;
    padding: 5px 10px;
    border-radius: 9px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--color-bg);
    background: var(--color-accent);
    transition: filter 0.15s ease, transform 0.2s var(--spring);
  }
  .cd-older-bar button:hover { filter: brightness(1.08); transform: translateY(-1px); }
  .cd-earlier { display: flex; justify-content: center; padding: 10px 0 6px; }
  .cd-start-note {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    margin: 4px 0 10px;
    font-size: 11.5px;
    color: var(--color-faint);
  }
  .cd-down {
    position: absolute;
    right: 18px;
    bottom: 12px;
    z-index: 4;
    display: grid;
    width: 38px;
    height: 38px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-surface) 90%, transparent);
    box-shadow: 0 10px 26px -10px rgb(0 0 0 / 0.85), inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 90%, transparent);
    backdrop-filter: blur(10px);
    transition: transform 0.2s var(--spring), color 0.15s ease;
  }
  .cd-down:hover { color: var(--color-accent); transform: translateY(-2px); }
  /* A message gone to from a search: lit up, then let go. */
  .cd-msg.is-flash .cd-bubble { animation: cd-flash 2s ease-out both; }
  @keyframes cd-flash {
    0%, 20% { box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-accent) 85%, transparent), 0 0 26px -2px color-mix(in srgb, var(--color-accent) 60%, transparent); }
    100% { box-shadow: 0 0 0 2px transparent, 0 0 26px -2px transparent; }
  }
  /* Files being dragged over the conversation. */
  .cd-drop {
    position: absolute;
    inset: 0;
    z-index: 30;
    display: grid;
    place-items: center;
    padding: 18px;
    border-radius: inherit;
    background: color-mix(in srgb, var(--color-bg) 62%, transparent);
    backdrop-filter: blur(6px);
    pointer-events: none;
  }
  .cd-drop-card {
    display: flex;
    width: 100%;
    height: 100%;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    border-radius: 18px;
    font-size: 12.5px;
    color: var(--color-muted);
    border: 2px dashed color-mix(in srgb, var(--color-accent) 65%, transparent);
    background: color-mix(in srgb, var(--color-accent) 7%, transparent);
    animation: cd-drop-in 0.25s var(--spring) both;
  }
  .cd-drop-card b { font-size: 15px; color: var(--color-ink); }
  .cd-drop-icon {
    display: grid;
    width: 54px;
    height: 54px;
    margin-bottom: 4px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-bg);
    background: var(--color-accent);
    animation: cd-drop-bob 1.2s ease-in-out infinite;
  }
  @keyframes cd-drop-in { from { opacity: 0; transform: scale(0.97); } }
  @keyframes cd-drop-bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }
  @keyframes ch-spin { to { transform: rotate(360deg); } }
  .cd-head {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 16px;
    border-bottom: 1px solid color-mix(in srgb, var(--color-edge) 70%, transparent);
  }
  .cd-back { display: none; padding: 6px; border-radius: 9px; color: var(--color-muted); transform: rotate(180deg); }
  .cd-av { position: relative; flex-shrink: 0; }
  .cd-unread {
    padding: 1px 8px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 600;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .cd-toggle {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 8px;
    padding: 5px 11px 5px 6px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--color-good);
    background: color-mix(in srgb, var(--color-good) 12%, transparent);
    transition: background-color 0.18s ease, color 0.18s ease;
  }
  .cd-toggle-knob {
    position: relative;
    width: 26px;
    height: 15px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--color-good) 55%, transparent);
    transition: background-color 0.18s ease;
  }
  .cd-toggle-knob::after {
    content: "";
    position: absolute;
    top: 2px;
    left: 13px;
    width: 11px;
    height: 11px;
    border-radius: 999px;
    background: #fff;
    transition: left 0.22s var(--spring);
  }
  .cd-toggle.is-off { color: var(--color-muted); background: rgb(255 255 255 / 0.05); }
  .cd-toggle.is-off .cd-toggle-knob { background: rgb(255 255 255 / 0.14); }
  .cd-toggle.is-off .cd-toggle-knob::after { left: 2px; }

  /* Where the reply is: one slim line under the name, never more. */
  .cd-strip {
    --t: var(--color-faint);
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 9px;
    padding: 7px 16px;
    font-size: 12px;
    border-bottom: 1px solid color-mix(in srgb, var(--color-edge) 55%, transparent);
    background: linear-gradient(90deg, color-mix(in srgb, var(--t) 8%, transparent), transparent 70%);
  }
  .cd-strip.is-live { --t: var(--color-accent); }
  .cd-strip.is-done { --t: var(--color-good); }
  .cd-strip[data-tone="warn"] { --t: var(--color-warn); }
  .cd-strip[data-tone="bad"] { --t: var(--color-bad); }
  .cd-strip-mark {
    display: grid;
    width: 20px;
    height: 20px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    color: var(--t);
    background: color-mix(in srgb, var(--t) 16%, transparent);
  }
  .cd-strip.is-done .cd-strip-mark { color: var(--color-bg); background: var(--color-good); animation: cd-pop 0.45s var(--spring) both; }
  .cd-strip-mark.is-busy { animation: ch-pulse 1.4s ease-in-out infinite; }
  .cd-strip-text { display: flex; min-width: 0; flex: 1; align-items: baseline; gap: 8px; white-space: nowrap; }
  .cd-strip-text b { flex-shrink: 0; font-weight: 600; color: var(--color-ink); font-variant-numeric: tabular-nums; }
  .cd-strip-text span { min-width: 0; overflow: hidden; text-overflow: ellipsis; font-size: 11.5px; color: var(--color-faint); }
  .cd-ring { width: 20px; height: 20px; flex-shrink: 0; transform: rotate(-90deg); }
  .cd-ring circle { fill: none; stroke-width: 4.5; }
  .cd-ring .track { stroke: rgb(255 255 255 / 0.09); }
  .cd-ring .fill {
    stroke: var(--color-accent);
    stroke-dasharray: 100.5;
    stroke-linecap: round;
    transition: stroke-dashoffset 1s linear;
  }
  .cd-steps { display: flex; flex-shrink: 0; align-items: center; gap: 0; }
  .cd-step {
    display: block;
    width: 7px;
    height: 7px;
    border-radius: 999px;
    background: rgb(255 255 255 / 0.13);
    transition: background-color 0.3s ease, box-shadow 0.3s ease;
  }
  .cd-step.is-done { background: color-mix(in srgb, var(--color-accent) 70%, transparent); }
  .cd-step.is-now {
    background: var(--color-accent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 25%, transparent);
    animation: cd-now 1.6s ease-in-out infinite;
  }
  .cd-step-line { display: block; width: 9px; height: 2px; margin: 0 2px; border-radius: 2px; background: rgb(255 255 255 / 0.08); }
  .cd-step-line.is-done { background: color-mix(in srgb, var(--color-accent) 55%, transparent); }

  .cd-conv {
    display: flex;
    min-height: 0;
    flex: 1;
    flex-direction: column;
    gap: 2px;
    overflow-y: auto;
    padding: 14px 16px 10px;
  }
  .cd-day {
    display: flex;
    justify-content: center;
    margin: 12px 0 8px;
  }
  .cd-day span {
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 600;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.04);
  }
  .cd-msg { display: flex; align-items: flex-end; gap: 8px; max-width: 82%; }
  .cd-msg.is-first { margin-top: 6px; }
  .cd-msg.is-mine { align-self: flex-end; flex-direction: row-reverse; }
  /* The picture's column, kept on every message of theirs so a run lines up, drawn only on its last. */
  .cd-msg-av { width: 26px; flex-shrink: 0; }
  /* The bubble and whatever is under it (reactions) travel together, so the
     reactions sit with the message rather than stretching the row. */
  .cd-wrap { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
  .cd-msg.is-mine .cd-wrap { align-items: flex-end; }
  .cd-reacts { display: flex; flex-wrap: wrap; gap: 4px; padding: 0 2px; }
  .cd-react {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 7px 2px 5px;
    border-radius: 999px;
    font-size: 11.5px;
    line-height: 1.4;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.06);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
  }
  /* One this account added itself, marked the way Discord marks your own. */
  .cd-react.is-mine {
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 16%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 45%, transparent);
  }
  .cd-react img { width: 15px; height: 15px; object-fit: contain; }
  .cd-react-e { font-size: 13px; line-height: 1; }
  .cd-react b { font-weight: 600; font-variant-numeric: tabular-nums; }
  /* A press adds the account's own, or takes it back. */
  .cd-react { transition: background-color 0.15s ease, box-shadow 0.15s ease, transform 0.28s var(--spring); }
  .cd-react:not(:disabled):hover {
    color: var(--color-ink);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 55%, transparent);
    transform: translateY(-1px);
  }
  .cd-react:not(:disabled):active { transform: scale(0.92); }
  .cd-react:disabled { cursor: default; }
  .cd-react.is-mine { animation: cd-react-in 0.36s var(--spring) backwards; }
  @keyframes cd-react-in { from { transform: scale(0.6); } }
  /* React: beside the message as the pointer passes, and while its picker is open. */
  .cd-react-add {
    display: grid;
    width: 28px;
    height: 28px;
    flex-shrink: 0;
    align-self: center;
    place-items: center;
    border-radius: 999px;
    color: var(--color-faint);
    opacity: 0;
    transform: scale(0.8);
    transition: opacity 0.16s var(--swift), transform 0.28s var(--spring), color 0.15s ease, background-color 0.15s ease;
  }
  .cd-msg:hover .cd-react-add, .cd-react-add:focus-visible, .cd-react-add.is-open { opacity: 1; transform: none; }
  .cd-react-add:hover, .cd-react-add.is-open { color: var(--color-ink); background: rgb(255 255 255 / 0.07); }
  .cd-react-add:focus-visible { outline: none; box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-accent) 45%, transparent); }
  :global(:root[data-motion="off"]) .cd-react,
  :global(:root[data-motion="off"]) .cd-react-add { transition: none; animation: none; }
  /* A Nitro gift in a DM: what it is for, where it stands, and the button that takes it. Nitro's own blurple,
     lit from within rather than a flat panel, and green once it is on the account. */
  .cd-gift {
    display: flex;
    align-items: center;
    gap: 9px;
    margin-top: 6px;
    padding: 8px 9px 8px 11px;
    border-radius: 13px;
    background:
      radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, #5865f2 28%, transparent), transparent 70%),
      rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, #5865f2 35%, transparent);
  }
  .cd-gift.is-done {
    background:
      radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, var(--color-good) 26%, transparent), transparent 70%),
      rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-good) 35%, transparent);
  }
  .cd-gift.is-gone { opacity: 0.6; }
  .cd-gift-mark {
    display: grid;
    width: 28px;
    height: 28px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 9px;
    color: #c7ccfb;
    background: color-mix(in srgb, #5865f2 42%, transparent);
  }
  .cd-gift.is-done .cd-gift-mark { color: var(--color-good); background: color-mix(in srgb, var(--color-good) 28%, transparent); }
  .cd-gift-what { display: block; font-size: 12.5px; font-weight: 650; color: var(--color-ink); }
  .cd-gift-says { display: block; font-size: 11px; color: var(--color-muted); }

  .cd-quote {
    display: flex;
    max-width: 320px;
    align-items: center;
    gap: 5px;
    margin-bottom: 4px;
    padding: 3px 8px;
    overflow: hidden;
    border-radius: 7px;
    font-size: 11.5px;
    white-space: nowrap;
    text-align: left;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 2px 0 0 color-mix(in srgb, var(--color-accent) 55%, transparent);
    transition: background-color 0.15s ease, color 0.15s ease;
  }
  .cd-quote b { flex-shrink: 0; font-weight: 650; color: var(--color-ink); }
  .cd-quote:not(:disabled):hover { color: var(--color-ink); background: rgb(255 255 255 / 0.09); }
  .cd-quote:disabled { cursor: default; }
  /* Replying to one message: a slim bar over the message box, with what it answers and a way out. */
  .cd-replying {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 4px 6px;
    padding: 6px 8px 6px 10px;
    border-radius: 10px;
    font-size: 12px;
    color: var(--color-muted);
    background: color-mix(in srgb, var(--color-accent) 9%, rgb(255 255 255 / 0.03));
    box-shadow: inset 2px 0 0 color-mix(in srgb, var(--color-accent) 70%, transparent);
  }
  .cd-replying b { font-weight: 650; color: var(--color-ink); }
  .cd-replying-x {
    display: grid;
    width: 20px;
    height: 20px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    color: var(--color-faint);
    transition: background-color 0.15s ease, color 0.15s ease;
  }
  .cd-replying-x:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
  .cd-bubble {
    min-width: 0;
    padding: 8px 12px;
    border-radius: 6px 18px 18px 6px;
    font-size: 13.5px;
    line-height: 1.45;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.065);
    animation: cd-in 0.28s var(--spring) both;
  }
  .cd-msg.is-first .cd-bubble { border-top-left-radius: 18px; }
  .cd-msg.is-last .cd-bubble { border-bottom-left-radius: 18px; }
  .cd-msg.is-mine .cd-bubble {
    border-radius: 18px 6px 6px 18px;
    background: color-mix(in srgb, var(--color-accent) 26%, rgb(255 255 255 / 0.03));
  }
  .cd-msg.is-mine.is-first .cd-bubble { border-top-right-radius: 18px; }
  .cd-msg.is-mine.is-last .cd-bubble { border-bottom-right-radius: 18px; }
  .cd-meta { margin: 3px 0 4px 34px; font-size: 10.5px; color: var(--color-faint); }
  .cd-time {
    flex-shrink: 0;
    align-self: center;
    font-size: 10.5px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    color: var(--color-faint);
    opacity: 0;
    transform: translateX(-5px);
    transition: opacity 0.18s var(--swift), transform 0.25s var(--spring);
    pointer-events: none;
  }
  .cd-msg.is-mine .cd-time { transform: translateX(5px); }
  .cd-msg:hover .cd-time { opacity: 1; transform: none; }
  .cd-meta.is-mine { align-self: flex-end; margin-right: 2px; }
  .cd-typing { display: inline-flex; gap: 4px; padding: 12px 14px; }
  .cd-typing i {
    width: 6px;
    height: 6px;
    border-radius: 999px;
    background: var(--color-ink);
    opacity: 0.4;
    animation: cd-dot 1.2s ease-in-out infinite;
  }
  .cd-typing i:nth-child(2) { animation-delay: 0.15s; }
  .cd-typing i:nth-child(3) { animation-delay: 0.3s; }
  .cd-their-typing { animation: cd-typing-in 0.3s var(--spring) both; }
  @keyframes cd-typing-in { from { opacity: 0; transform: translateY(6px) scale(0.96); } }
  /* A deleted message: still there, faded, outlined, with a bin on its corner. */
  .cd-msg.is-deleted .cd-bubble {
    position: relative;
    opacity: 0.62;
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-bad) 45%, transparent);
  }
  .cd-msg.is-deleted .cd-bubble :global(img) { filter: grayscale(0.4); }
  .cd-bin {
    position: absolute;
    top: -7px;
    right: -7px;
    display: grid;
    width: 20px;
    height: 20px;
    place-items: center;
    border-radius: 999px;
    color: #fff;
    background: var(--color-bad);
    box-shadow: 0 0 0 2px var(--color-bg), 0 4px 10px -4px rgb(0 0 0 / 0.8);
    opacity: 1;
    animation: cd-bin-in 0.4s var(--spring) both;
  }
  .cd-msg.is-mine .cd-bin { right: auto; left: -7px; }
  @keyframes cd-bin-in { from { transform: scale(0.3) rotate(-25deg); } }
  .cd-edited { margin: 2px 6px 0; font-size: 10px; color: var(--color-faint); }
  /* In the list, while they type. */
  .ch-typing { display: inline-flex; align-items: center; gap: 2px; font-style: italic; color: var(--color-accent); }
  .ch-typing i { width: 3px; height: 3px; border-radius: 999px; background: currentColor; animation: cd-dot 1.2s ease-in-out infinite; }
  .ch-typing i:first-of-type { margin-left: 2px; }
  .ch-typing i:nth-of-type(2) { animation-delay: 0.15s; }
  .ch-typing i:nth-of-type(3) { animation-delay: 0.3s; }
  .cd-loading { display: flex; flex-direction: column; gap: 10px; padding-top: 10px; }
  .cd-skel { height: 34px; border-radius: 16px; background: rgb(255 255 255 / 0.04); animation: ch-pulse 1.4s ease-in-out infinite; }
  .cd-skel.is-mine { align-self: flex-end; }
  .cd-note { margin-top: 10px; font-size: 11px; text-align: center; color: var(--color-faint); }

  /* A column now: staged pictures sit above the row you type in. */
  .cd-readonly {
    display: flex; align-items: center; justify-content: center; gap: 7px;
    border-top: 1px solid var(--color-edge); padding: 14px 16px;
    font-size: 12px; color: var(--color-faint);
  }
  .cd-compose {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin: 10px 14px 12px;
    padding: 6px 6px 6px 8px;
    border-radius: 16px;
    background: rgb(0 0 0 / 0.22);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    transition: box-shadow 0.18s ease;
  }
  .cd-compose:focus-within {
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, transparent),
                0 0 0 3px color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .cd-compose textarea {
    flex: 1;
    min-height: 34px;
    max-height: 140px;
    padding: 7px 0;
    resize: none;
    font-size: 13.5px;
    line-height: 1.45;
    color: var(--color-ink);
    background: transparent;
    outline: none;
  }
  .cd-compose textarea::placeholder { color: var(--color-faint); }
  .cd-send {
    display: grid;
    width: 36px;
    height: 36px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 12px;
    color: var(--color-bg);
    background: var(--color-accent);
    transition: opacity 0.15s ease, transform 0.2s var(--spring);
  }
  .cd-send:hover:not(:disabled) { transform: scale(1.06); }
  .cd-send:disabled { opacity: 0.35; }
  .cd-compose-row { display: flex; align-items: flex-end; gap: 8px; }
  .cd-attach {
    display: grid;
    width: 34px;
    height: 34px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 11px;
    color: var(--color-muted);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .cd-attach:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.07); }
  /* What is about to be sent with the message. */
  .cd-staged { display: flex; flex-wrap: wrap; gap: 7px; padding: 4px 4px 0 6px; }
  .cd-staged-item {
    position: relative;
    display: inline-flex;
    overflow: hidden;
    border-radius: 10px;
    box-shadow: inset 0 0 0 1px var(--color-edge);
  }
  .cd-staged-item img { display: block; width: 62px; height: 62px; object-fit: cover; }
  .cd-staged-file {
    display: inline-flex;
    max-width: 150px;
    align-items: center;
    gap: 6px;
    padding: 0 10px;
    height: 62px;
    overflow: hidden;
    font-size: 11.5px;
    color: var(--color-muted);
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .cd-staged-x {
    position: absolute;
    top: 3px;
    right: 3px;
    display: grid;
    width: 17px;
    height: 17px;
    place-items: center;
    border-radius: 999px;
    color: #fff;
    background: rgb(0 0 0 / 0.65);
  }
  .cd-staged-x:hover { background: var(--color-bad); }
  .cd-msg.is-pending .cd-bubble { opacity: 0.6; }
  .cd-msg.is-failed .cd-bubble { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-bad) 70%, transparent); }
  .cd-meta.is-failed { color: var(--color-bad); }
  .cd-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    border-top: 1px solid color-mix(in srgb, var(--color-edge) 70%, transparent);
    background: rgb(0 0 0 / 0.12);
  }

  /* ── Inbox zero ──────────────────────────────────────────────────── */
  .ch-zero {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 56px 24px;
    border-radius: 22px;
    text-align: center;
  }
  .ch-zero-mark {
    position: relative;
    display: grid;
    width: 60px;
    height: 60px;
    margin-bottom: 6px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-good);
    background: color-mix(in srgb, var(--color-good) 14%, transparent);
    animation: cd-pop 0.6s var(--spring) both;
  }
  .ch-zero-mark::after {
    content: "";
    position: absolute;
    inset: -6px;
    border-radius: 999px;
    border: 1.5px solid color-mix(in srgb, var(--color-good) 40%, transparent);
    animation: ch-ripple 2.8s ease-out infinite;
  }
  .ch-zero.is-compact { padding: 34px 24px 30px; }

  .ch-recent { margin-top: 18px; }
  .ch-recent-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 16px; margin-bottom: 8px; }
  .ch-recent-head .ch-sec { margin: 0 6px; }
  .ch-recent-find { width: min(320px, 100%); }
  .ch-recent-msgs { margin-top: 18px; }
  .ch-recent-hits { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 4px 10px; }
  .ch-recent-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
    gap: 8px;
  }
  /* Tinted with the theme like every button (app.css, "Buttons with depth"): its fill, its light and its glow are
     that layer's, so the card adds only a breath of fill and its lift. No ring of its own: an outline here read as
     an old bordered button. */
  .ch-recent-card {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    border-radius: 16px;
    background: rgb(255 255 255 / 0.02);
    transition: background-color 0.25s var(--swift), transform 0.3s var(--swift);
  }
  /* Pressed: it gives a little, as everything you press does. */
  .ch-recent-card:active { transform: scale(0.98); transition-duration: 0.08s; }
  .ch-recent-card:hover {
    background: rgb(255 255 255 / 0.035);
    transform: translateY(-1px);
  }
  .ch-recent-card:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }
  .ch-recent-av { flex-shrink: 0; }
  .ch-recent-go { flex-shrink: 0; color: var(--color-faint); transition: opacity 0.15s ease; }
  .ch-recent-wrap:hover .ch-recent-go { opacity: 0; }
  .ch-recent-wrap .ch-x { top: 50%; margin-top: -11px; right: 10px; }
  .ch-recent-more {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 10px auto 0;
    padding: 6px 12px;
    border-radius: 999px;
    font-size: 12px;
    color: var(--color-muted);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .ch-recent-more:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.05); }
  :global(:root[data-motion="off"]) .ch-recent-card { animation: none; transition: none; }

  @keyframes ch-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
  @keyframes ch-ripple { 0% { opacity: 0.9; transform: scale(0.92); } 70%, 100% { opacity: 0; transform: scale(1.35); } }
  @keyframes cd-now {
    0%, 100% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-accent) 25%, transparent); }
    50% { box-shadow: 0 0 0 7px color-mix(in srgb, var(--color-accent) 8%, transparent); }
  }
  @keyframes cd-pop { from { opacity: 0; transform: scale(0.6); } to { opacity: 1; transform: none; } }
  @keyframes cd-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  @keyframes cd-dot { 0%, 60%, 100% { transform: translateY(0); opacity: 0.35; } 30% { transform: translateY(-4px); opacity: 0.9; } }

  :global(:root[data-motion="off"]) .cd-step.is-now,
  :global(:root[data-motion="off"]) .cd-strip-mark,
  :global(:root[data-motion="off"]) .cd-bubble,
  :global(:root[data-motion="off"]) .ch-call,
  :global(:root[data-motion="off"]) .ch-call-ring,
  :global(:root[data-motion="off"]) .ch-call-icon,
  :global(:root[data-motion="off"]) .ch-call-tag :global(svg),
  :global(:root[data-motion="off"]) .cd-call,
  :global(:root[data-motion="off"]) .cd-call :global(svg),
  :global(:root[data-motion="off"]) .ch-add,
  :global(:root[data-motion="off"]) .cd-typing i,
  :global(:root[data-motion="off"]) .ch-typing i,
  :global(:root[data-motion="off"]) .cd-their-typing,
  :global(:root[data-motion="off"]) .cd-bin,
  :global(:root[data-motion="off"]) .ch-zero-mark::after,
  :global(:root[data-motion="off"]) .ch-state-pulse,
  :global(:root[data-motion="off"]) .cd-msg.is-flash .cd-bubble,
  :global(:root[data-motion="off"]) .cd-drop-card,
  :global(:root[data-motion="off"]) .cd-drop-icon { animation: none; }

  /* ── Narrow: the list and the conversation take turns ────────────── */
  @media (max-width: 860px) {
    .ch-top.narrow-hide, .ch-friends.narrow-hide { display: none; }
    /* Account and Reply to all share the first row; the counts are one line
       below that scrolls sideways, rather than wrapping into three. Ignored
       and Add friend are their icons here (Ignored keeps its count), and the
       account keeps room for its name: with no room of its own it shrank to
       nothing and its name ran under the buttons. Narrower still, the
       buttons go to a row of their own. */
    .ch-top { gap: 8px 10px; margin-bottom: 10px; }
    .ch-top-account { order: 1; flex: 1 1 9rem; }
    .ch-top-actions { order: 2; position: relative; }
    /* Their panels hang from the row's right edge, not their own button's: from a button mid-row, one wider than
       the room to its left ran off the screen (iMessage's new message form, 340px, on a phone). */
    .ch-top-actions > [data-add-friend], .ch-top-actions > [data-ignored-panel] { position: static; }
    .ch-top-actions .ch-btn-label { display: none; }
    .ch-top-actions .ch-ignored-btn { padding: 7px 9px; }
    /* The name before the "Discord #1" tag: here the tag goes (the picture,
       the name and the list it opens say which account it is), where it had
       pushed the name down to nothing. */
    .ch-acc-name { min-width: 3rem; }
    .ch-slot-chip { display: none; }
    .ch-stats { order: 3; width: 100%; flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; }
    .ch-stats::-webkit-scrollbar { display: none; }
    .ch-stat { flex-shrink: 0; }
    .ch-livebadge { display: none; }
    .ch-friends { margin-bottom: 10px; }
    .ch-inbox { grid-template-columns: minmax(0, 1fr); }
    .ch-detail { border-radius: 16px; }
    .cd-head { padding: 10px 12px; gap: 8px; }
    .cd-tool { width: 30px; height: 30px; }
    .cd-strip { padding: 7px 12px; }
    .cd-strip-text span { display: none; }
    .cd-conv { padding: 10px 12px 8px; }
    .cd-msg { max-width: 90%; }
    .cd-actions { padding: 10px 12px; }
    .ch-inbox .ch-detail { display: none; }
    .ch-inbox.show-detail .ch-left { display: none; }
    .ch-inbox.show-detail .ch-detail { display: flex; }
    .cd-back { display: inline-flex; }

  }
  /* A message that is only a picture is shown as the picture: no bubble
     behind it, no padding around it. A background plus the image's own
     rounded corners read as a box drawn around every photo. */
  .cd-bubble:has(:global(.mb-media)):not(:has(:global(.mb-text))):not(:has(:global(.mb-chip))) {
    padding: 0;
    background: none;
    box-shadow: none;
    backdrop-filter: none;
  }
</style>
