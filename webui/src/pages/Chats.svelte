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
    sendOwnMessage, typingNow, drafts, setDraft, loadDrafts, stagedFiles, loadEarlier, joinConversation,
    reactTo, SNAP_REACTIONS,
    type ChatUser, type ConvMessage, type StagedFile, type Reaction,
  } from "../lib/chats";
  import ReactPicker from "../lib/components/ReactPicker.svelte";
  import { fold, highlighted, splitWords } from "../lib/chatsearch";
  import { discordInline } from "../lib/discordmd";
  import { saveTextFile } from "../lib/window";
  import ChatTools from "../lib/components/ChatTools.svelte";
  import Badge from "../lib/components/Badge.svelte";
  import Button from "../lib/components/Button.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import UserChip from "../lib/components/UserChip.svelte";
  import MessageBody from "../lib/components/MessageBody.svelte";
  import Avatar from "../lib/components/Avatar.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import { mentionNames, resolveMention } from "../lib/mentions";
  import { menu as contextMenu, copyText, openMenu, type MenuEntry } from "../lib/contextmenu";

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
  // Per account: a Snapchat account's are its own chats, not the Discord ones.
  const pastRes = $derived(resource(`chatArchive:${target}`, () => api.chatArchive(100, target), { conversations: [] as Past[] }));
  let pastList = $state<Past[]>([]);
  $effect(() => {
    const r = pastRes;
    const stop = r.subscribe((s) => (pastList = s.data.conversations ?? []));
    if (target) r.refresh({ maxAge: 30000, quiet: true });
    return stop;
  });
  let showPast = $state(false);

  // ── Replies in flight ──────────────────────────────────────────────────
  // Held in the store, so a reply that takes two minutes still shows as
  // running after leaving the tab and coming back.
  const replying = $derived($replyingStore);
  const replyingAll = $derived(!!$replyingAllStore[target]);
  const allProgress = $derived($replyAllProgress[target]);
  const busy = $derived(replyingAll);

  const accounts = $derived($chatAccounts);
  const entry = $derived($chatCache[target] ?? { users: [], fetched: 0, loading: false, error: "" });
  const users = $derived(entry.users);
  const loading = $derived(!accounts.length || (!entry.fetched && entry.loading));
  const refreshing = $derived(entry.loading && entry.fetched > 0);
  const current = $derived(accounts.find((a) => a.id === target));
  const unread = $derived(users.reduce((n, u) => n + (u.count || 0), 0));
  const isSnap = $derived(current?.platform === "snapchat");

  /** Anyone still waiting is in the list above, so they are not history yet. Nor is anyone ignored. */
  const archived = $derived(
    pastList.filter((c: Past) => !users.some((u) => u.id === c.id) && !ignoredIds.has(c.id)),
  );

  onMount(() => {
    void start();
    // What was being typed to whom, from before the app last closed.
    void loadDrafts();
    const clock = setInterval(() => (now = Date.now() / 1000), 1000);
    // The list is live (see startChatLive); this slower pass only catches what
    // no event describes, like messages that arrived while the bot was off.
    const t = setInterval(() => {
      if (document.hidden) return;
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
      if (want) {
        chatsFocus.set("");
        if (list.some((a) => a.id === want)) target = want;
      }
      if (list.length && !target) target = list[0].id;
      await Promise.all([
        refreshChats(target, { maxAge: 10000 }),
        loadFriends(),
      ]);
    } catch (e: any) {
      loadError = e?.message || "Could not load";
    }
  }

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

  async function answerRequest(r: FriendRequest, action: "accept" | "decline") {
    friendBusy[r.id] = true;
    try {
      const res = await api.friendAction(action, r.id, target);
      if (res?.ok) {
        requests = requests.filter((x) => x.id !== r.id);
        toast(`${action === "accept" ? "Accepted" : "Declined"} ${r.display_name || r.username}.`, "ok");
      } else {
        toast(res?.reason || `${isSnap ? "Snapchat" : "Discord"} refused that`, "err");
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
    const platform = a.platform === "discord" ? "Discord" : "Snapchat";
    return `${platform}${a.account ? ` #${a.account}` : ""}`;
  }
  const named = (a: Account) => who(a) !== slot(a);
  const multiple = $derived(accounts.length > 1);
  let picking = $state(false);

  function choose(id: string) {
    picking = false;
    if (id !== target) switchTarget(id);
  }
  function dismiss(event: MouseEvent) {
    const el = event.target as HTMLElement;
    if (picking && !el.closest?.("[data-account-picker]")) picking = false;
    if (ignoredOpen && !el.closest?.("[data-ignored-panel]")) ignoredOpen = false;
  }
  async function switchTarget(id: string) {
    target = id;
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

  const statusOf = (u: ChatUser): Status => statusFor(u, { now, paused: entry.paused, failed: failedReplies });
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

  /** The X on a row: stop answering them, and stop trying, until they are let back in. */
  async function ignorePerson(u: IgnoredPerson, e?: MouseEvent) {
    e?.stopPropagation();
    if (ignoreBusy[u.id]) return;
    ignoreBusy[u.id] = true;
    try {
      await setIgnored(target, u.id, true);
      if (!ignoredList.some((p) => p.id === u.id)) {
        ignoredList = [...ignoredList, { id: u.id, name: u.name, username: u.username, avatar: u.avatar }];
      }
      if (selectedId === u.id && !showDetail) selectedId = "";
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
  type Person = ChatUser & { archived?: boolean };
  let selectedId = $state("");
  let snapshot = $state<Person | null>(null);
  // On a narrow window the list and the conversation take turns.
  let showDetail = $state(false);

  $effect(() => {
    const u = users.find((x) => x.id === selectedId);
    if (u) snapshot = { ...u };
  });
  // Nothing open yet: open the first one, so the right side is never empty.
  $effect(() => {
    if (!selectedId && flat.length) selectedId = flat[0].id;
  });

  const selected = $derived<Person | null>(
    users.find((u) => u.id === selectedId) ?? (snapshot?.id === selectedId ? snapshot : null),
  );
  const answered = $derived(!!selected && !users.some((u) => u.id === selected.id));
  const st = $derived(selected && !answered ? statusOf(selected) : null);

  function select(id: string) {
    selectedId = id;
    showDetail = true;
  }

  // ── Writing to them yourself ─────────────────────────────────────────────
  // What you are typing is a draft per conversation (lib/chats.ts): opening someone else, leaving the tab or
  // closing the app keeps it, and the list shows it under their name until it is sent.
  const draftKey = $derived(selected ? convKey(target, selected.id) : "");
  const draftOf = (id: string) => ($drafts[convKey(target, id)] ?? "").replace(/\s+/g, " ").trim();
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
        toast(isSnap ? `${f.name}: Snapchat takes pictures from here.` : `${f.name}: that kind of file can't be sent.`, "err");
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
    sendingOwn = true;
    setDraft(k, "");
    setStaged(k, []);
    // What is sent goes at the bottom, where now is.
    if (older) older = null;
    await tick();
    grow();
    const r = await sendOwnMessage(target, who.id, text, files);
    sendingOwn = false;
    if (!r.ok) {
      setDraft(k, text);
      setStaged(k, files);
      toast(r.error || "Could not send it", "err");
    } else {
      playSound("send");
      if (r.dropped) toast(`Sent. The bot's reply to ${who.name} was dropped: you answered them yourself.`, "ok");
    }
    await tick();
    grow();
    convBox?.scrollTo({ top: convBox.scrollHeight, behavior: "smooth" });
    composer?.focus();
  }

  function onComposerKey(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      sendDraft();
    }
  }

  /** Inbox zero lists the answered conversations under its card, the first dozen until asked for more. */
  const RECENT_FIRST = 12;
  let showAllRecent = $state(false);

  function openArchived(c: Past) {
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
  type ToolTab = "search" | "media" | "files" | "links";
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
  type ListFilter = "all" | "unread" | "needs" | "live" | "answered" | "drafts" | "servers";
  let listQuery = $state("");
  let listFilter = $state<ListFilter>("all");
  const listWords = $derived(splitWords(listQuery).map(fold).filter(Boolean));
  const searchingList = $derived(listWords.length > 0);

  function rowMatches(name: string, username: string | undefined, text: string): boolean {
    if (!listWords.length) return true;
    const hay = fold(`${name} ${username ?? ""} ${text}`);
    return listWords.every((w) => hay.includes(w));
  }

  const hasDraft = (id: string) => !!draftOf(id);
  function passes(u: ChatUser, section: string): boolean {
    const f = listFilter;
    if (f === "unread" && !(u.count > 0)) return false;
    if ((f === "needs" || f === "live") && section !== f) return false;
    if (f === "answered") return false;
    if (f === "drafts" && !hasDraft(u.id)) return false;
    if (f === "servers" && u.kind !== "server") return false;
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

  const listChips = $derived.by(() => {
    const live = users.filter((u) => !u.ignored);
    const list: { id: ListFilter; label: string; n: number }[] = [
      { id: "all", label: "All", n: 0 },
      { id: "unread", label: "Unread", n: live.filter((u) => u.count > 0).length },
      { id: "needs", label: "Needs you", n: sections.find((s) => s.id === "needs")?.rows.length ?? 0 },
      { id: "live", label: "Being answered", n: sections.find((s) => s.id === "live")?.rows.length ?? 0 },
      { id: "drafts", label: "Drafts", n: [...live.map((u) => u.id), ...archived.map((c: Past) => c.id)].filter(hasDraft).length },
      { id: "answered", label: "Answered", n: archived.length },
      { id: "servers", label: "Servers", n: live.filter((u) => u.kind === "server").length },
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
    if (q.length < 2 || !t) {
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

  /**
   * Size the inbox to exactly the space left in the window, so the list and
   * the conversation each scroll on their own and the Reply button is always
   * on screen. It used to be a sticky panel taller than what was left below the
   * header, so its bottom, with the buttons, started off screen.
   */
  function fillHeight(node: HTMLElement) {
    const scroller = node.closest<HTMLElement>(".overflow-y-auto");
    const wrap = node.parentElement;
    let raf = 0;
    const set = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        if (!scroller) return;
        const pb = wrap ? parseFloat(getComputedStyle(wrap).paddingBottom) || 0 : 0;
        node.style.marginBottom = `${16 - pb}px`;
        const top = node.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
        // A low floor: the pocket window is only about 600px tall, and a floor
        // above what is left pushed the Reply button off the bottom.
        node.style.setProperty("--inbox-h", `${Math.floor(Math.max(280, scroller.clientHeight - top - 16))}px`);
      });
    };
    set();
    // Anything above it (a notice, the friend requests) moves its top.
    const ro = new ResizeObserver(set);
    if (scroller) ro.observe(scroller);
    if (wrap) ro.observe(wrap);
    window.addEventListener("resize", set);
    return {
      destroy() {
        ro.disconnect();
        window.removeEventListener("resize", set);
        cancelAnimationFrame(raf);
      },
    };
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

  async function reply(u: ChatUser) {
    if (busy) return;
    try {
      const res = await sendReply(target, u.id);
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

  async function cancel(u: ChatUser) {
    if (rowBusy[u.id]) return;
    rowBusy[u.id] = "cancel";
    try {
      await cancelReply(target, u.id);
      toast(`Won't reply to ${u.name}. You can still answer by hand.`, "ok");
    } catch (e: any) {
      toast(e?.status === 504 ? "The account did not answer, it may be stopped" : e.message, "err");
    } finally {
      delete rowBusy[u.id];
    }
  }

  /** The person a row is about: for a server conversation, whoever is asking in it, not the channel. */
  const personOf = (u: ChatUser): IgnoredPerson =>
    u.kind === "server" && u.author_id ? { id: u.author_id, name: u.name, username: u.username, avatar: u.avatar } : u;

  async function flipIgnore(u: ChatUser) {
    if (rowBusy[u.id]) return;
    rowBusy[u.id] = "ignore";
    try {
      const off = await toggleIgnore(target, personOf(u).id);
      toast(off ? `The bot is off for ${u.name}.` : `The bot is on for ${u.name} again.`, "ok");
    } catch (e: any) {
      toast(e?.status === 504 ? "The account did not answer, it may be stopped" : e.message, "err");
    } finally {
      delete rowBusy[u.id];
    }
  }

  /** Right-click on someone waiting: open them, answer now or not at all, or stop answering them. */
  function rowMenu(u: ChatUser): MenuEntry[] {
    const who = personOf(u);
    return [
      { title: u.name },
      { label: "Open", icon: "chats", run: () => select(u.id) },
      u.kind !== "server" && { label: "Search in this chat", icon: "search", run: () => { select(u.id); openTools("search"); } },
      { label: "Reply now", icon: "send", disabled: busy, run: () => reply(u) },
      cancellable(u) && { label: "Don't reply", icon: "stop", run: () => cancel(u) },
      "sep",
      { label: "Copy name", icon: "copy", run: () => copyText(u.name, "Copied the name.") },
      u.username && u.username !== u.name && { label: `Copy @${u.username}`, icon: "copy", run: () => copyText(u.username ?? "", "Copied the username.") },
      who.id && !isSnap && { label: "Copy user ID", icon: "copy", run: () => copyText(String(who.id), "Copied the ID.") },
      "sep",
      { label: `Ignore ${who.name}`, icon: "close", danger: true, run: () => ignorePerson(who) },
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
    if (isSnap && !SNAP_REACTIONS.includes(r.name)) return;
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
      // the run ends as they come back, and says what it did.
      void stopReplyAll(target);
      return;
    }
    if (busy) return;
    try {
      const res = await sendReplyAll(target);
      if (!res) return;
      const results = (res?.results || []) as any[];
      const stuck = results.filter((r) => !r.success && !r.dropped && !r.cancelled);
      failedReplies = new Set(stuck.map((r) => String(r.id)));
      const n = res?.total ?? users.length;
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
    const t = (u.text ?? u.snippet ?? "")
      .replace(/<@!?(\d+)>/g, (_, id) => `@${$mentionNames[id] || "someone"}`)
      .replace(/<a?:(\w+):\d+>/g, ":$1:")
      .replace(/```[\s\S]*?```/g, "code")
      .replace(/\|\|[\s\S]+?\|\|/g, "spoiler")
      .replace(/^\s*>+\s?/gm, "")
      .replace(/[*_~`]/g, "")
      .replace(/\s+/g, " ")
      .trim();
    if (t && !/^\[(attachment|image|video|file|link|voice message|snap|call|\d+ attachments|sticker.*)\]$/i.test(t)) return t;
    // Snapchat's kinds of message, said the way Snapchat says them.
    const said: Record<string, string> = { "[snap]": "Sent a Snap", "[call]": "A call", "[voice message]": "Voice message",
                                           "[image]": "Sent a picture", "[video]": "Sent a video", "[sticker]": "Sent a sticker" };
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
      {#if current?.avatar}
        <img src={current.avatar} alt="" class="h-9 w-9 shrink-0 rounded-full object-cover ring-1 ring-edge" />
      {:else}
        <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-accent">
          <Icon name={current?.platform === "snapchat" ? "snapchat" : "accounts"} size={17} />
        </span>
      {/if}
      <span class="min-w-0">
        <span class="flex min-w-0 items-center gap-2">
          <span class="truncate text-[14px] font-semibold text-ink">{current ? who(current) : "No account"}</span>
          {#if current && named(current)}
            <span class="shrink-0 rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-faint">{slot(current)}</span>
          {/if}
        </span>
        <span class="block truncate text-[11px] text-faint">
          {multiple ? "Answering as this account, click to switch" : "Answering as this account"}
        </span>
      </span>
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
        {#each accounts as a (a.id)}
          <button role="option" aria-selected={a.id === target} onclick={() => choose(a.id)}
                  class="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors
                    {a.id === target ? 'bg-accent/10' : 'hover:bg-white/[0.05]'}">
            {#if a.avatar}
              <img src={a.avatar} alt="" class="h-8 w-8 shrink-0 rounded-full object-cover ring-1 ring-edge" />
            {:else}
              <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-accent">
                <Icon name={a.platform === "snapchat" ? "snapchat" : "accounts"} size={15} />
              </span>
            {/if}
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[13px] text-ink">{who(a)}</span>
              <span class="block truncate text-[11px] text-faint">
                {named(a) ? `${slot(a)}${a.username && a.username !== who(a) ? ` · @${a.username}` : ""}` : "never connected"}
              </span>
            </span>
            {#if a.state && a.state !== "running"}<span class="shrink-0"><Badge tone="muted">{a.state}</Badge></span>{/if}
            {#if a.id === target}<span class="shrink-0 text-accent"><Icon name="check" size={14} /></span>{/if}
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
    <div class="relative" data-ignored-panel>
      <button class="ch-ignored-btn" class:is-open={ignoredOpen} onclick={() => { ignoredOpen = !ignoredOpen; if (ignoredOpen) loadIgnored(); }}
              title="People the bot does not answer" aria-expanded={ignoredOpen}>
        <Icon name="eyeOff" size={13} />Ignored{#if ignoredCount}<b>{ignoredCount}</b>{/if}
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
    <span class="ch-livebadge" title="New messages and every step of a reply show up here as they happen">
      <i class:is-busy={refreshing}></i>{refreshing ? "Checking" : "Live"}
    </span>
    <Button kind={replyingAll ? "ghost" : "good"} onclick={replyAll}
            disabled={(!replyingAll && users.length === 0) || !!allProgress?.stopping} loading={!!allProgress?.stopping}>
      {#if allProgress?.stopping}
        Stopping
      {:else if replyingAll && allProgress}
        <Icon name="stop" size={11} />Stop ({allProgress.done}/{allProgress.total})
      {:else if replyingAll}
        <Icon name="stop" size={11} />Stop
      {:else}
        <Icon name="chats" size={13} />Reply to all
      {/if}
    </Button>
  </div>
</div>

<!-- ── Friend requests: a strip, not a block ──────────────────────────────── -->
{#if incoming.length || (friendsError && friendsSupported)}
  <div class="ch-friends" class:narrow-hide={showDetail && !!selected}>
    <span class="ch-friends-label">
      <Icon name="accounts" size={13} />Friend requests
      {#if incoming.length}<b>{incoming.length}</b>{/if}
    </span>
    {#if friendsError && friendsSupported && !incoming.length}
      <span class="text-[12px] text-warn">{friendsError}</span>
      <button class="text-[11.5px] text-faint hover:text-ink" onclick={loadFriends}>Try again</button>
    {/if}
    <div class="ch-friends-list domino" use:domino={{ step: 70 }}>
      {#each incoming as r (r.id)}
        <div class="ch-fr" title={isSnap ? "Accept adds them as a friend." : "Accepted over hours on its own so it does not look scripted. Accept does it now."}>
          <Avatar src={r.avatar} name={r.display_name || r.username} size={30} silhouette={isSnap} />
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
{:else if !users.length && !selected}
  <!-- ── Inbox zero ─────────────────────────────────────────────────────── -->
  <div class="ch-zero glass" class:is-compact={archived.length > 0}>
    <span class="ch-zero-mark" use:chime={"done"}><Icon name="check" size={26} /></span>
    <div class="text-[18px] font-semibold tracking-tight text-ink">Everyone has been answered</div>
    <p class="max-w-md text-[12.5px] leading-relaxed text-muted">
      Anyone who messages this account and has not had a reply shows up here the moment they do,
      with where the bot is with their reply.
    </p>
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
              <span class="halo ch-recent-av"><Avatar src={c.avatar} name={c.name} size={40} zoom={false} silhouette={isSnap} /></span>
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
              <Avatar src={p.avatar} name={p.name} size={32} zoom={false} silhouette={isSnap} />
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
          <input bind:value={listQuery} placeholder="Search chats" spellcheck="false" autocomplete="off" aria-label="Search chats"
                 onkeydown={(e) => { if (e.key === "Escape" && listQuery) { e.stopPropagation(); listQuery = ""; } }} />
          {#if listQuery}
            <button type="button" class="ch-find-x" onclick={() => (listQuery = "")} aria-label="Clear the search">
              <Icon name="close" size={10} />
            </button>
          {/if}
        </label>
        {#if listChips.length > 1}
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
      <div class="ch-list domino" use:domino={{ step: 40, max: 12 }}>
      {#each shownSections as sec (sec.id)}
        <div class="ch-sec" data-tone={sec.tone}>
          <span class="ch-sec-dot"></span>{sec.title}<span class="ch-sec-n">{sec.rows.length}</span>
        </div>
        {#each sec.rows as { u, st: s } (u.id)}
          <div class="ch-item-wrap" class:is-bad={s.tone === "bad"} animate:flip={{ duration: 260 }} use:contextMenu={() => rowMenu(u)}>
          <button class="ch-item" class:is-sel={u.id === selectedId} data-tone={s.tone} data-phase={s.phase}
                  onclick={() => select(u.id)}>
            <span class="ch-av halo" class:is-live={s.phase === "live"} class:is-fast={s.step === 2 || s.step === 4}>
              <Avatar src={u.avatar} name={u.name} size={42} zoom={false} silhouette={isSnap} />
              {#if u.count > 1}<span class="ch-badge">{u.count}</span>{/if}
            </span>
            <span class="ch-item-main">
              <span class="ch-item-top">
                <span class="ch-name">{u.name}</span>
                {#if u.kind === "server" && u.where}<span class="ch-where" title={u.where}>{u.where}</span>{/if}
                <span class="ch-time">{ago(u.ts)}</span>
              </span>
              <span class="ch-preview">
                {#if $typingNow[convKey(target, u.id)]}
                  <!-- They are writing to it right now. -->
                  <span class="ch-typing">typing<i></i><i></i><i></i></span>
                {:else if u.id !== selectedId && hasDraft(u.id)}
                  <!-- Something you started writing to them and have not sent. -->
                  <span class="ch-draft">Draft:</span><span class="ch-draft-text">{draftOf(u.id)}</span>
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
          <button class="ch-x" onclick={(e) => ignorePerson(personOf(u), e)} disabled={!!ignoreBusy[personOf(u).id]}
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
            <div class="ch-item-wrap" use:contextMenu={() => pastMenu(c)}>
              <button class="ch-item is-past" class:is-sel={c.id === selectedId} onclick={() => openArchived(c)}>
                <span class="ch-av"><Avatar src={c.avatar} name={c.name} size={34} zoom={false} silhouette={isSnap} /></span>
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
            <Avatar src={p.avatar} name={p.name} size={32} zoom={false} silhouette={isSnap} />
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
            <Avatar src={selected.avatar} name={selected.name} size={48} silhouette={isSnap} />
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex min-w-0 items-center gap-2">
              <UserChip id={selected.id} name={selected.name} size="md" />
              {#if selected.count > 1 && !answered}<span class="cd-unread">{selected.count} unread</span>{/if}
            </div>
            <div class="truncate text-[11.5px] text-faint">
              {#if selected.username && selected.username !== selected.name}<span class="selectable">@{selected.username}</span> · {/if}
              {selected.kind === "server" && selected.where ? `${selected.where} · ` : ""}{selected.archived ? "answered" : `last message ${ago(selected.ts) === "now" ? "just now" : `${ago(selected.ts)} ago`}`}
              {#if selected.ts} · {at(selected.ts)}{/if}
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
              <button type="button" class="cd-tool" onclick={moreMenu} title="More" aria-label="More">
                <Icon name="more" size={15} />
              </button>
            </div>
          {/if}
          {#if !selected.archived}
            <button class="cd-toggle" class:is-off={selected.ignored} onclick={() => flipIgnore(selected!)}
                    disabled={!!rowBusy[selected.id]}
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
        {#if answered}
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
                    <Avatar src={d.m.author?.avatar ?? selected.avatar}
                            name={d.m.author?.name ?? selected.name} size={26} zoom={false} silhouette={isSnap} />
                  {/if}
                </span>
              {/if}
              <div class="cd-wrap">
                <div class="cd-bubble">
                  <MessageBody text={d.m.text ?? ""} attachments={d.m.attachments ?? []} stickers={d.m.stickers ?? []}
                               embeds={d.m.embeds ?? []}
                               onreveal={!d.m.mine && !selected.archived && !isSnap ? () => loadMessage(target, selected!.id) : undefined} />
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
                              disabled={!reactable(d.m) || (isSnap && !SNAP_REACTIONS.includes(r.name))}
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
                {d.m.mine ? "You" : (d.m.author?.name ?? selected.name)}{#if d.m.pending} · sending{:else if d.m.failed} · not sent{:else if !d.m.approx} · {at(d.m.ts)}{/if}
              </div>
            {/if}
          {/each}
          {#if $typingNow[convKey(target, selected.id)] && !selected.archived}
            <!-- They are typing to it right now: the same dots as the bot's, on their side. -->
            <div class="cd-msg is-first is-last cd-their-typing">
              <span class="cd-msg-av"><Avatar src={selected.avatar} name={selected.name} size={26} zoom={false} /></span>
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
              <Button kind="ghost" onclick={() => cancel(selected!)} disabled={!!rowBusy[selected.id]}>
                <Icon name="close" size={12} />Cancel the reply
              </Button>
            {/if}
          </footer>
        {/if}
        {#if selected}
          <!-- Write to them yourself, as the account. A reply the bot had lined up is dropped when you do. -->
          <form class="cd-compose" onsubmit={(e) => { e.preventDefault(); sendDraft(); }}>
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
              <button type="button" class="cd-attach" onclick={() => filePick?.click()}
                      aria-label={isSnap ? "Attach a picture" : "Attach files"}
                      title={isSnap ? "Attach a picture. You can also paste or drop one" : "Attach files. You can also paste or drop them"}>
                <Icon name={isSnap ? "pictures" : "plus"} size={15} />
              </button>
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
                           them={{ name: selected.name, username: selected.username, avatar: selected.avatar }}
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
    <ReactPicker anchor={reactingTo.anchor} snap={isSnap}
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
    height: var(--inbox-h, calc(100dvh - 120px));
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
  .ch-recent-card {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    border-radius: 16px;
    background: rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.05);
    transition: background-color 0.18s ease, box-shadow 0.18s ease, transform 0.25s var(--spring);
  }
  /* Pressed: squashed a little, as everything you press is. */
  .ch-recent-card:active { transform: scale(0.96); transition-duration: 0.08s; }
  .ch-recent-card:hover {
    background: rgb(255 255 255 / 0.06);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 30%, transparent);
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
       below that scrolls sideways, rather than wrapping into three. */
    .ch-top { gap: 8px 10px; margin-bottom: 10px; }
    .ch-top-account { order: 1; flex: 1; }
    .ch-top-actions { order: 2; }
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
