<script lang="ts">
  /**
   * Big Picture Mode: the whole screen, watching everything the bots do, live.
   *
   * Nothing to type into and nothing to set up: it follows what is already
   * streaming. The queue from every account down the left, the conversation
   * the director has picked in the middle (director.ts), which model is
   * working and what it is thinking on the right, and the day's numbers along
   * the bottom. With nobody waiting it cycles through idle scenes, one for
   * every part of the app: the people you talk to (Memory), the day, the
   * accounts, recent conversations, the bot's pictures, who it talks to most,
   * its persona, and, when there are any, friend requests and anything broken.
   * The chapters under the stage name them and go straight to one.
   *
   * It reads the same live data the rest of the app keeps: the Chats cache
   * (kept live app-wide by App.svelte), model usage (modelusage.ts), the log
   * stream for thoughts and the log face, the Health poll, and the stats. The
   * one thing it does that costs the account anything is reading a
   * conversation's history, so that happens only for the one on stage, only
   * when it is not already loaded, and at most once every twenty seconds:
   * history reads come out of the account's hourly allowance. Friend requests
   * are a call to Discord each, so they are asked for on opening, when the log
   * says one arrived, and otherwise every five minutes.
   */
  import { onDestroy, onMount, untrack } from "svelte";
  import { get } from "svelte/store";
  import { cubicIn, cubicOut } from "svelte/easing";
  import { fade } from "svelte/transition";
  import { api } from "../api";
  import { bigPicture, bigPictureArriving, bigPictureCloser, bigPictureCovering, bigPictureSound, health, motionEnabled,
           picturesBlur, setBigPicture, toast } from "../stores";
  import { cancelReply, chatAccounts, chatCache, conversations, convKey, loadChatAccounts, loadConversation, loadEarlier,
           refreshChats, replying, sendOwnMessage, sendReply, toggleIgnore } from "../chats";
  import { statusOf } from "../chatstatus";
  import { subscribeEvents, subscribeLogs } from "../logsocket";
  import { loadUsage, startUsageLive, usage } from "../modelusage";
  import { loadProviders, savedPlan, shortModel } from "../providers";
  import { loadMoods } from "../accounts/state";
  import { personasRes } from "../personas/store";
  import { platformName } from "../accounts/condition";
  import { isMore, isRule, kindOf, sourceInfo, tidy } from "../logrows";
  import { setFullscreen, isDesktop } from "../window";
  import { HOUR_MINUTE, fmtDate } from "../fmt";
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import { MANUAL_HOLD, cycleFor, hold, initial, live, pick, ranked, sceneOf, sceneProgress, showScene, step, tick,
           togglePin, type Row, type Scene } from "./director";
  import { chapterOrder, personaLines, personaName, sentPictures } from "./scenes";
  import { SCENE_LOOK, energyFor, lookFor, type LookName } from "./looks";
  import { paletteForTrouble, themePalette, type RGB } from "./palette";
  import { play, primeAudio } from "./sounds";
  import { burstFrom, pointerActivity } from "./fx";
  import BPBackdrop from "./BPBackdrop.svelte";
  import BPQueue from "./BPQueue.svelte";
  import BPStage from "./BPStage.svelte";
  import BPBrain from "./BPBrain.svelte";
  import BPThoughts from "./BPThoughts.svelte";
  import BPStats from "./BPStats.svelte";
  import BPRotate from "./BPRotate.svelte";
  import BPChapters from "./BPChapters.svelte";
  import type { Active, BPAccount, BPActivity, FeedItem, FriendReq, HealthIssue, LogLite, MemoryLine, MemoryPerson,
                Picture, QRow, SceneActions, SceneWorld, SentPicture, Spot, Thought } from "./types";

  let now = $state(Date.now() / 1000);
  let dir = $state(initial(Date.now() / 1000));
  let hideText = $state(false);
  /** The top bar and the cursor: there while the mouse moves, gone after a few seconds, like a film. */
  let awake = $state(true);
  let sleepTimer: ReturnType<typeof setTimeout> | null = null;
  /** The list of shortcuts, over everything. */
  let help = $state(false);

  // ── The queue, every account together ───────────────────────────────────
  const queue = $derived.by<QRow[]>(() => {
    const out: QRow[] = [];
    for (const a of $chatAccounts) {
      const e = $chatCache[a.id];
      if (!e) continue;
      for (const u of e.users) {
        if (u.ignored) continue;
        out.push({ key: `${a.id}:${u.id}`, target: a.id, u, st: statusOf(u, { now, paused: e.paused }), account: a });
      }
    }
    return out;
  });
  const rowsFor = (q: QRow[]): Row[] =>
    q.map((r) => ({ key: r.key, phase: r.st.phase, step: r.st.step ?? 0, eta: r.st.eta ?? null, ts: r.u.ts }));
  /** The rail in the director's order: what is happening first. */
  const railed = $derived.by(() => {
    const order = ranked(rowsFor(queue), now).map((r) => r.key);
    return queue.slice().sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
  });
  const multi = $derived($chatAccounts.length > 1);

  // The one on stage stays drawn after it leaves the queue (it was answered), from its last snapshot.
  const snapshots = new Map<string, QRow>();
  $effect(() => {
    for (const r of queue) snapshots.set(r.key, r);
  });
  const spot = $derived.by<Spot | null>(() => {
    const k = dir.spotlight;
    if (!k) return null;
    const live = queue.find((r) => r.key === k);
    if (live) return { ...live, answered: false };
    const snap = snapshots.get(k);
    return snap ? { ...snap, answered: true } : null;
  });
  const messages = $derived(spot ? $conversations[convKey(spot.target, spot.u.id)]?.messages ?? [] : []);

  // The director follows every change in the queue as it happens, and the clock besides.
  $effect(() => {
    const rows = rowsFor(queue);
    untrack(() => {
      if (!gone()) dir = tick(dir, rows, now, cycle);
    });
  });

  // History for the one on stage: only if not already loaded, at most one read every 20 seconds.
  let lastHistory = 0;
  const asked = new Set<string>();
  $effect(() => {
    void now;
    const s = spot;
    if (!s || s.answered) return;
    const k = convKey(s.target, s.u.id);
    if (asked.has(k) || get(conversations)[k]) return;
    if (Date.now() - lastHistory < 20000) return;
    lastHistory = Date.now();
    asked.add(k);
    loadConversation(s.target, s.u.id).catch(() => {});
  });

  // ── The numbers ──────────────────────────────────────────────────────────
  let stats = $state({ replies: 0, people: 0, hourly: [] as number[], top: [] as { user_id: string; username: string; count: number; avatar?: string }[] });
  let recent = $state<{ id: string; name: string; avatar?: string; messages: number; last_ts?: number }[]>([]);
  let accts = $state<BPAccount[]>([]);
  let accountsAt = 0;

  async function loadStats() {
    try {
      const d: any = await api.statsOverview();
      stats = {
        replies: d?.windows?.today ?? 0,
        people: d?.people_7d ?? 0,
        hourly: (d?.hourly ?? []).map((h: any) => h.count ?? 0),
        top: (d?.top ?? []).map((t: any) => ({ ...t, avatar: avatarOf(String(t.user_id)) })),
      };
    } catch {
      /* the stage does not depend on it */
    }
  }
  let recentSeq = 0;
  async function loadRecent() {
    const seq = ++recentSeq;
    try {
      // Every account's: Discord's together, and each Snapchat account's own, newest first.
      const snaps = accts.filter((a) => a.platform === "snapchat").map((a) => a.id);
      const lists = await Promise.all([api.chatArchive(12), ...snaps.map((id) => api.chatArchive(12, id).catch(() => null))]);
      if (seq !== recentSeq) return;      // a later look, with more accounts in it, is on its way
      const all = lists.flatMap((d: any) => d?.conversations ?? []);
      all.sort((a: any, b: any) => (b.last_ts ?? 0) - (a.last_ts ?? 0));
      recent = all.slice(0, 12).map((c: any) => ({ id: String(c.id), name: c.name, avatar: c.avatar, messages: c.messages, last_ts: c.last_ts }));
    } catch {
      /* the idle scene falls back to Today */
    }
  }
  /** Every account, who it is and how it is: the supervisor's word, and the worker's own when it answers. */
  async function loadAccounts() {
    accountsAt = Date.now();
    try {
      const d: any = await api.accounts();
      const rows = (d?.accounts ?? []).filter((a: any) => a.platform !== "telegram");
      const details = await Promise.all(rows.map((a: any) =>
        a.state === "running" ? api.accountDetails(a.id).catch(() => null) : Promise.resolve(null)));
      accts = rows.map((a: any, i: number): BPAccount => {
        const det: any = details[i];
        return {
          id: a.id, platform: a.platform, account: a.account ?? null,
          // One that has never connected has no name of its own yet: "Snapchat #1", as the Accounts page says it.
          name: a.display_name || a.username || `${platformName(a.platform)}${a.account ? ` #${a.account}` : ""}`,
          username: a.username, avatar: a.avatar, banner: a.banner,
          accent: a.accent, state: a.state, uptime: a.uptime, enabled: a.enabled,
          live: !!det?.live, ping: det?.latency_ms ?? null, mood: det?.mood ?? "", presence: det?.presence,
          paused: !!det?.paused, night: !!det?.night, guilds: det?.guilds, friends: det?.friends,
        };
      });
    } catch {
      /* keep what was there */
    }
  }
  // ── The rest of the app, for its scenes ──────────────────────────────────
  let activity = $state<Record<string, BPActivity>>({});
  let activityDates = $state<string[]>([]);
  async function loadActivity() {
    try {
      const d: any = await api.accountActivity(7);
      activity = d?.accounts ?? {};
      activityDates = d?.dates ?? [];
    } catch {
      /* the cards go without their week */
    }
  }

  let pictures = $state<Picture[]>([]);
  /** The pictures that went out while watching, by file name. */
  let sentPics = $state<Record<string, SentPicture>>({});
  /** "Show pictures" was pressed: for the rest of this visit, like the Pictures tab. */
  let picsShown = $state(false);
  const picturesBlurred = $derived($picturesBlur && !picsShown);
  /** Whose pictures the gallery shows: the persona of the account on show ("" for Default's). */
  let picturesOf = "";
  async function loadPictures() {
    const as = facePersona === "default" ? "" : facePersona;
    try {
      const d: any = await api.pictures(as);
      picturesOf = as;
      pictures = (d?.pictures ?? []).map((p: any) => ({
        name: String(p.name), description: String(p.description ?? ""),
        // A video shows as its still.
        url: api.pictureThumb({ name: String(p.name), id: String(p.id ?? ""), video: !!p.video }, as),
      }));
    } catch {
      /* no pictures scene this time */
    }
  }

  let personaText = $state("");
  let moods = $state<string[]>([]);
  /** Who the account on show speaks as: its own text, moods and pictures (app/utils/personas.py). */
  async function loadPersona() {
    const pid = facePersona;
    try {
      const d: any = await api.personaText(pid);
      if (pid !== facePersona) return;
      personaText = String(d?.text ?? "");
    } catch {
      /* no persona scene this time */
    }
    moods = await loadMoods(false, pid).catch(() => []);
  }
  const pLines = $derived(personaLines(personaText));
  /** Whose face the persona wears: the account that is running, if one is. */
  const faceAcct = $derived(accts.find((a) => a.state === "running" && a.platform === "discord") ?? accts[0] ?? null);
  const facePersona = $derived(faceAcct ? $personasRes.data.accounts[faceAcct.id] || "default" : "default");
  /** The name the persona goes by (its own, or the one its text gives), unless it has none but "Default". */
  const facePersonaName = $derived.by(() => {
    const p = $personasRes.data.personas.find((x) => x.id === facePersona);
    return p && !(p.is_default && p.name === "Default") ? p.name : "";
  });
  const persona = $derived({ lines: pLines, name: personaName(pLines) || facePersonaName || faceAcct?.name || "", face: faceAcct });
  // Another account on show, speaking as another persona: its text, moods and pictures instead.
  let shownPersona = "";
  $effect(() => {
    const pid = facePersona;
    if (!arrived || pid === shownPersona) return;
    shownPersona = pid;
    untrack(() => {
      loadPersona();
      loadPictures();
    });
  });

  const issues = $derived<HealthIssue[]>(($health.issues ?? []) as HealthIssue[]);
  /** What needs fixing; an available update and the like are not a problem. */
  const urgent = $derived(issues.filter((i) => i.level === "error" || i.level === "warn"));

  // Friend requests: one call to Discord per running account each time, so not often.
  let friendReqs = $state<FriendReq[]>([]);
  let friendGone = $state<Record<string, "accept" | "decline">>({});
  let friendsAt = 0;
  let friendsQueued: ReturnType<typeof setTimeout> | null = null;
  async function loadFriends() {
    friendsAt = Date.now();
    const targets = accts.filter((a) => a.state === "running");
    if (!targets.length) {
      friendReqs = [];
      return;
    }
    const lists = await Promise.all(targets.map((a) =>
      api.friends(a.id)
        .then((d: any) => (d?.requests ?? []).filter((r: any) => r.incoming).map((r: any): FriendReq => ({
          id: String(r.id), username: String(r.username ?? ""), display_name: r.display_name || "",
          avatar: r.avatar || "", accept_at: r.accept_at ?? null, target: a.id,
        })))
        .catch(() => null)));
    if (gone()) return;
    // An account that did not answer keeps what it had, rather than emptying the list.
    friendReqs = targets.flatMap((a, i) => lists[i] ?? friendReqs.filter((r) => r.target === a.id));
  }
  /** Soon, but never more than once every twenty seconds: each look is a call to Discord. */
  function friendsSoon(delay = 2500) {
    if (friendsQueued) return;
    const wait = Math.max(delay, 20000 - (Date.now() - friendsAt));
    friendsQueued = setTimeout(() => {
      friendsQueued = null;
      if (!gone()) loadFriends();
    }, wait);
  }

  // ── Memory: what you talk about with each of them, for the idle scenes ──
  // Everyone it might show is asked for their stored summary first, which is a
  // local read and writes nothing. Only then, in the background and only while
  // nothing else is on stage, does it have a few new ones written: one at a
  // time, a while apart, a handful per visit. Each of those is one call to the
  // small model and at most one read of that DM, within the same history
  // allowance every other reader spends.
  let memPeople = $state<MemoryPerson[]>([]);
  const MEM_CANDIDATES = 8;
  const MEM_WRITES = 4;
  const MEM_GAP = 45_000;
  const memAsked = new Set<string>();
  const memTried = new Set<string>();
  let memWrites = 0;
  let memLastWrite = 0;
  let memWriting = false;
  /** Summaries are turned off in Settings, or nothing is running that could write one. */
  let memOff = false;

  function addMemory(c: (typeof recent)[number], r: any) {
    const lines: MemoryLine[] = (r.recent ?? [])
      .filter((l: any) => l && typeof l.text === "string" && l.text.trim())
      .map((l: any) => ({ mine: !!l.mine, text: String(l.text) }));
    const p: MemoryPerson = {
      id: c.id, name: c.name, avatar: c.avatar, messages: c.messages, last_ts: c.last_ts,
      summary: String(r.summary), generated_at: r.generated_at, count: r.count, recent: lines,
    };
    // The most recent conversation comes round first.
    memPeople = [...memPeople.filter((x) => x.id !== p.id), p].sort((a, b) => (b.last_ts ?? 0) - (a.last_ts ?? 0));
  }
  async function loadMemoryStored() {
    for (const c of recent.slice(0, MEM_CANDIDATES)) {
      if (gone() || memOff) return;
      if (memAsked.has(c.id)) continue;
      memAsked.add(c.id);
      try {
        const r: any = await api.memorySummary(c.id, false, true);
        if (r?.enabled === false) {
          memOff = true;
          return;
        }
        if (r?.ok && r.summary) addMemory(c, r);
      } catch {
        /* the idle scenes go on without them */
      }
    }
  }
  async function writeOneMemory() {
    if (memOff || memWriting || gone() || document.hidden || dir.spotlight) return;
    if (memWrites >= MEM_WRITES || Date.now() - memLastWrite < MEM_GAP) return;
    const c = recent.slice(0, MEM_CANDIDATES)
      .find((x) => memAsked.has(x.id) && !memTried.has(x.id) && !memPeople.some((p) => p.id === x.id));
    if (!c) return;
    memTried.add(c.id);
    memWriting = true;
    memWrites += 1;
    memLastWrite = Date.now();
    try {
      const r: any = await api.memorySummary(c.id);
      if (r?.ok && r.summary) addMemory(c, r);
      else if (r?.enabled === false || /No account is running/i.test(r?.reason ?? "")) memOff = true;
    } catch {
      /* someone else next time */
    } finally {
      memWriting = false;
    }
  }

  // ── The scenes, and the chapters that name them ──────────────────────────
  /** Every scene there is something to show in; the director takes them in this order. */
  const cycle = $derived(cycleFor({
    memory: memPeople.length > 0,
    recent: recent.length > 0,
    people: stats.top.length > 0,
    accounts: accts.length > 0,
    pictures: pictures.length > 0,
    friends: friendReqs.length > 0,
    persona: pLines.length > 0,
    health: urgent.length > 0,
  }));
  const scene = $derived(sceneOf(dir));
  const chapters = $derived(chapterOrder(cycle));
  const badges = $derived<Partial<Record<Scene, number>>>({
    ...(friendReqs.length ? { friends: friendReqs.length } : {}),
    ...(urgent.length ? { health: urgent.length } : {}),
  });
  /** Held by hand, or by the pointer moving over the stage. */
  const held = $derived(dir.pinned || now < dir.manualUntil);

  /** Whose turn it is: the next one each time a memory scene comes up. */
  let memTurn = $state(0);
  let memSeen = -1;
  $effect(() => {
    const idle = dir.idle;
    if (scene !== "memory" || !idle) return;
    // Each showing has its own number; a held scene's clock moving is not a new one.
    if (idle.scene === memSeen) return;
    memSeen = idle.scene;
    untrack(() => (memTurn += 1));
  });
  /** The one on show, with the latest messages if this visit has already read them. */
  const memPerson = $derived.by<MemoryPerson | null>(() => {
    if (!memPeople.length) return null;
    const p = memPeople[(Math.max(1, memTurn) - 1) % memPeople.length];
    for (const a of $chatAccounts) {
      const held = $conversations[convKey(a.id, p.id)]?.messages;
      if (held?.length) {
        const lines = held.filter((m) => m.text).slice(-4).map((m) => ({ mine: !!m.mine, text: m.text ?? "" }));
        if (lines.length) return { ...p, recent: lines };
      }
    }
    return p;
  });

  // The accounts scene is worth fresh detail: a ping and a mood from a minute ago read as stale.
  $effect(() => {
    if (scene === "accounts") untrack(() => {
      if (Date.now() - accountsAt > 20000) loadAccounts();
    });
  });

  /** A face for someone the stats only know by id: from the queue, or the recent list. */
  function avatarOf(uid: string): string | undefined {
    for (const e of Object.values(get(chatCache))) {
      const u = e.users.find((x) => x.id === uid);
      if (u?.avatar) return u.avatar;
    }
    return recent.find((r) => r.id === uid)?.avatar;
  }
  const tokensToday = $derived($usage.models.reduce((n, m) => n + m.today.in + m.today.out, 0));
  const requestsToday = $derived($usage.models.reduce((n, m) => n + m.today.requests, 0));
  const today = $derived({ replies: stats.replies, people: stats.people, tokens: tokensToday, requests: requestsToday });

  // ── The room: whoever is on stage lights it ───────────────────────────────
  /** The theme's own colours, for the scenes about no one in particular. Read once it is on the page. */
  let themeColours = $state<RGB[] | null>(null);
  /** Counts replies gone out on stage and things done by hand: each sends a ring of light across the room. */
  let roomPulse = $state(0);
  const TROUBLE = { errors: paletteForTrouble(true), warnings: paletteForTrouble(false) };
  type Room = { seed: string; art: string; look: LookName; energy: number; palette: RGB[] | null };
  /**
   * What the background is for: the person on stage, in their own colours and
   * their own look, lively while their reply is written and typed; else the
   * scene's subject (a person's memory, an account, a picture, whoever asked
   * to be friends), or the theme's colours for the scenes about no one.
   */
  const room = $derived.by<Room>(() => {
    if (spot) {
      return { seed: spot.u.id, art: spot.u.avatar || "", look: lookFor(spot.u.id),
               energy: energyFor(spot.st.phase, spot.st.step ?? 0, spot.answered), palette: null };
    }
    const calm = 0.2;
    switch (scene) {
      case "memory":
        if (memPerson) return { seed: memPerson.id, art: memPerson.avatar || "", look: lookFor(memPerson.id), energy: calm, palette: null };
        break;
      case "accounts":
        return { seed: `accounts:${faceAcct?.id ?? ""}`, art: accts.find((a) => a.banner)?.banner || faceAcct?.avatar || "",
                 look: SCENE_LOOK.accounts, energy: calm, palette: null };
      case "persona":
        return { seed: `persona:${faceAcct?.id ?? ""}`, art: faceAcct?.avatar || "", look: SCENE_LOOK.persona, energy: calm, palette: null };
      case "friends":
        return { seed: `friends:${friendReqs[0]?.id ?? ""}`, art: friendReqs[0]?.avatar || "", look: SCENE_LOOK.friends,
                 energy: 0.35, palette: null };
      case "pictures":
        // The pictures' own colours only while they may be seen: blurred, the room keeps the theme's.
        if (!picturesBlurred && !hideText && pictures[0]) {
          return { seed: "pictures", art: pictures[0].url, look: SCENE_LOOK.pictures, energy: calm, palette: null };
        }
        break;
      case "health":
        return { seed: "health", art: "", look: SCENE_LOOK.health, energy: 0.35,
                 palette: urgent.some((i) => i.level === "error") ? TROUBLE.errors : TROUBLE.warnings };
    }
    return { seed: `scene:${scene ?? "room"}`, art: "", look: scene ? SCENE_LOOK[scene] : "silk", energy: calm, palette: themeColours };
  });

  // ── What just happened ───────────────────────────────────────────────────
  let feed = $state<FeedItem[]>([]);
  let feedId = 0;
  let active = $state<Active | null>(null);
  /** The model that last wrote for each person, by their id. */
  let byConv = $state<Record<string, Active>>({});
  /** What the Brain shows: the model working on the conversation on stage, and
      only otherwise the last one to answer anywhere. */
  const brainModel = $derived((spot && byConv[spot.u.id]) || active);
  /** A model doing background work (memory, pictures, voice), shown under the replies model for a moment. */
  let helper = $state<{ model: string; job: string; at: number } | null>(null);
  let pulse = $state(0);
  let thoughts = $state<Thought[]>([]);
  let logs = $state<LogLite[]>([]);

  function pushFeed(kind: FeedItem["kind"], text: string, avatar?: string, name?: string) {
    feed = [{ id: ++feedId, kind, text, avatar, name, at: Date.now() / 1000 }, ...feed].slice(0, 12);
  }
  /** Who a row is, from the queue as it is, or as it was when it left (answered), or the recent list. */
  function whoIs(target: string, uid: string): { name: string; avatar?: string } {
    const u = get(chatCache)[target]?.users.find((x) => x.id === uid) ?? snapshots.get(`${target}:${uid}`)?.u;
    if (u) return { name: u.name, avatar: u.avatar };
    const r = recent.find((x) => x.id === uid);
    return r ? { name: r.name, avatar: r.avatar } : { name: "someone" };
  }
  const nameOf = (target: string, uid: string) => whoIs(target, uid).name;
  function onChat(evt: Record<string, any> | null) {
    if (!evt || gone()) return;
    const target = String(evt.target ?? "");
    const uid = String(evt.uid ?? "");
    if (evt.t === "msg") {
      play("arrive");
      const what = (evt.snippet || evt.text || (evt.attachments?.length ? "sent a picture" : "sent a message")).replace(/\s+/g, " ");
      pushFeed("arrive", `${evt.name || nameOf(target, uid)}: ${what}`, evt.avatar, evt.name);
    } else if (evt.t === "state" && evt.state?.state === "writing") {
      play("write");
      pushFeed("write", `Writing a reply to ${nameOf(target, uid)}`);
    } else if (evt.t === "sent") {
      stats.replies += 1;
      // The reply on stage went out: a ring of light across the room.
      if (spot && spot.target === target && spot.u.id === uid) roomPulse += 1;
      const who = whoIs(target, uid);
      // One of its own pictures went out: the gallery marks it, and says to whom. Only one of the gallery's own
      // persona: another persona's IMG_3 is another picture.
      const sender = $personasRes.data.accounts[target] || "default";
      const mine = (sender === "default" ? "" : sender) === picturesOf;
      const pics = mine ? sentPictures(evt.attachments, pictures.map((p) => p.name)) : [];
      if (pics.length) {
        const at = Date.now() / 1000;
        const next = { ...sentPics };
        for (const p of pics) next[p] = { to: who.name, avatar: who.avatar, at };
        sentPics = next;
        play("picture");
        pushFeed("picture", `Sent ${who.name} one of its pictures`, who.avatar, who.name);
      } else {
        play("sent");
        pushFeed("sent", `Replied to ${who.name}`);
      }
    }
  }
  function onModel(evt: Record<string, any> | null) {
    if (!evt || gone()) return;
    const name = shortModel(String(evt.model ?? ""));
    if (evt.ok && evt.job !== "replies") {
      // memory, pictures, voice: the brain mentions it, the feed stays for the conversation
      helper = { model: String(evt.model ?? ""), job: String(evt.job ?? ""), at: evt.at || Date.now() / 1000 };
    } else if (evt.ok) {
      const one: Active = { provider: evt.provider, model: evt.model, at: evt.at || Date.now() / 1000, ms: evt.ms || 0, ok: true };
      active = one;
      // Which model wrote for whom, so the Brain can show the one working on the
      // conversation on stage instead of whichever answered last anywhere.
      if (evt.uid) byConv = { ...byConv, [String(evt.uid)]: one };
      pulse += 1;
      pushFeed("model", `${name} wrote a reply in ${((evt.ms || 0) / 1000).toFixed(1)}s`);
    } else {
      play("limit");
      pushFeed("limit", evt.limited ? `${name} is rate limited, the next one takes over` : `${name} did not answer`);
    }
  }

  // The log: thoughts to their own panel, the rest to the log face, a line or a
  // burst of them at a time, and friend requests noticed as they are announced.
  let logId = 0;
  let logBuf: LogLite[] = [];
  let logFrame = 0;
  const FRIEND_ASK = /^(?:pending )?friend request from (.+?)(?: \(was previously a friend\))?,? (?:will accept|accepting) in \d+s/i;
  const FRIEND_TAKEN = /^accepted friend request from (.+)$/i;
  function friendNews(text: string) {
    const ask = FRIEND_ASK.exec(text);
    if (ask) {
      play("friend");
      pushFeed("friend", `${ask[1]} wants to be friends`, undefined, ask[1]);
      friendsSoon();
      return;
    }
    const took = FRIEND_TAKEN.exec(text);
    if (took) {
      // Taken from here, the runner logs an id and the feed already said so; by its own timer, a name.
      if (!/^\d+$/.test(took[1])) pushFeed("friend", `Now friends with ${took[1]}`, undefined, took[1]);
      friendsSoon();
    }
  }
  function onLog(e: { level?: string; text?: string; source?: string; ts?: number }) {
    if (!e.text || gone()) return;
    if (e.level === "think") {
      const [head, ...rest] = e.text.split("\n");
      const model = /\((.*)\)/.exec(head)?.[1] ?? "";
      thoughts = [...thoughts, { model, text: rest.join("\n").trim(), at: Date.now() / 1000 }].slice(-4);
      return;
    }
    if (isRule(e.text.trim()) || isMore(e.text)) return;
    const text = tidy(e.text.split("\n")[0]);
    if (!text) return;
    const src = sourceInfo(e.source ?? "", get(chatAccounts));
    logBuf.push({ id: ++logId, at: e.ts ?? Date.now() / 1000, level: kindOf(e.level ?? "info"), text,
                  who: src.name, avatar: src.avatar, icon: src.icon });
    if (!logFrame) {
      logFrame = requestAnimationFrame(() => {
        logFrame = 0;
        logs = [...logs, ...logBuf].slice(-30);
        logBuf = [];
      });
    }
    friendNews(text);
  }

  // ── Controls ─────────────────────────────────────────────────────────────
  function wake() {
    awake = true;
    if (sleepTimer) clearTimeout(sleepTimer);
    sleepTimer = setTimeout(() => (awake = false), 3200);
  }
  /**
   * Out of fullscreen first, while this view still covers everything, and
   * only then away: the window shrinks under this view alone, and the app is
   * laid out once, at the size it ends up. Closing the other way round laid
   * the whole app out at fullscreen size and then again at its own.
   */
  let closing = false;
  async function close() {
    if (closing) return;
    closing = true;
    bigPictureCloser.fn = null;
    await leaveFullscreen();
    // The app drawn again behind this view, which still covers it, a couple of
    // frames before the fade: drawing it is the work, and done now it is not
    // done in the fade's first frames.
    bigPictureArriving.set(false);
    bigPictureCovering.set(false);
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    setBigPicture(false);
  }
  /** Out of fullscreen, and the window settled at its own size again, or a moment's wait if it never moves. */
  async function leaveFullscreen() {
    let settle = () => {};
    const settled = new Promise<void>((done) => (settle = done));
    const onResize = () => requestAnimationFrame(() => settle());
    addEventListener("resize", onResize, { once: true });
    const changed = await setFullscreen(false);
    if (changed) setTimeout(settle, 400);
    else settle();
    await settled;
    removeEventListener("resize", onResize);
  }
  /** Closed or closing: the clock and the feeds stop at once, not after the fade. */
  const gone = () => !get(bigPicture);
  function toggleSound() {
    bigPictureSound.update((v) => !v);
    if (get(bigPictureSound)) {
      primeAudio();
      play("sent");
    }
  }
  function onKey(e: KeyboardEvent) {
    if (gone()) return;
    // Writing to someone: the letters are theirs, not shortcuts. Escape still
    // works, to step out of the box and then out of the view.
    const el = document.activeElement;
    const typing = !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA");
    if (typing && e.key !== "Escape") return;
    if (typing && e.key === "Escape") {
      e.preventDefault();
      (el as HTMLElement).blur();
      return;
    }
    const k = e.key.toLowerCase();
    const plain = !e.ctrlKey && !e.metaKey && !e.altKey;
    if (e.key === "Escape") {
      e.preventDefault();
      // The list of shortcuts first, then the view.
      if (help) help = false;
      else close();
    } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      dir = step(dir, rowsFor(queue), e.key === "ArrowRight" ? 1 : -1, now, cycle);
    } else if (e.key === " ") {
      e.preventDefault();
      dir = togglePin(dir);
    } else if (/^[1-9]$/.test(e.key) && plain) {
      const c = chapters[Number(e.key) - 1];
      if (c) goChapter(c);
    } else if (k === "l" && plain) {
      goLive();
    } else if (e.key === "?" || (k === "/" && e.shiftKey)) {
      help = !help;
    } else if (k === "m" && plain) {
      toggleSound();
    } else if (k === "h" && plain) {
      hideText = !hideText;
    }
    wake();
  }
  function pickRow(key: string) {
    dir = pick(dir, key, now);
  }
  /** A chapter chosen: that scene now, held a while, even with people waiting. */
  function goChapter(s: Scene) {
    dir = showScene(dir, s, cycle, Date.now() / 1000);
    play("tap");
  }
  /**
   * Back to the conversations: the one the director ranks first, held a while.
   * Even an old one nobody is answering, which it would not put up by itself:
   * asking for Live and getting nothing would look broken.
   */
  function goLive() {
    const t = Date.now() / 1000;
    const top = ranked(rowsFor(queue), t)[0];
    dir = top ? pick(live(dir), top.key, t) : live(dir);
    play("tap");
  }
  /** The pointer moving over the stage: nothing slides away from under it. */
  let lastHold = 0;
  function holdStage() {
    const t = Date.now();
    if (t - lastHold < 400) return;
    lastHold = t;
    dir = hold(dir, t / 1000);
  }
  /** Leave for a page of the app: the address is what App.svelte follows. */
  function openRoute(route: string) {
    close();
    window.location.hash = `/${route}`;
  }

  // ── Doing something about the conversation on stage ──────────────────────
  // The same four things the Chats tab offers, so Big Picture is not only
  // something to watch. Each holds the stage on that conversation for a while,
  // since acting on one and then having it slide away would be maddening.
  let acting = $state(false);

  async function act(s: Spot, run: () => Promise<unknown>, done: string) {
    if (acting) return;
    acting = true;
    dir = pick(dir, s.key, now);
    try {
      await run();
      if (done) toast(done, "ok");
    } catch (e: any) {
      toast(e?.message || "That did not work", "err");
    } finally {
      acting = false;
    }
  }

  const doReply = (s: Spot) => act(s, () => sendReply(s.target, s.u.id), "");
  const doCancel = (s: Spot) => act(s, () => cancelReply(s.target, s.u.id), `The reply to ${s.u.name} was dropped.`);
  const doIgnore = (s: Spot) => act(s, () => toggleIgnore(s.target, s.u.id), `No longer answering ${s.u.name}.`);
  const doSend = (s: Spot, text: string) =>
    act(s, async () => {
      const r = await sendOwnMessage(s.target, s.u.id, text);
      if (!r.ok) throw new Error(r.error || "Could not send it");
    }, "");

  // ── Doing something in the other scenes ──────────────────────────────────
  // Each keeps its scene up a while, for the same reason, and lands with a
  // little flourish (fx.ts) so it is plain that it worked.
  let busy = $state<Record<string, boolean>>({});
  const setBusy = (id: string, on: boolean) => {
    const next = { ...busy };
    if (on) next[id] = true;
    else delete next[id];
    busy = next;
  };

  async function answerFriend(r: FriendReq, action: "accept" | "decline", el: HTMLElement | null) {
    if (busy[r.id]) return;
    setBusy(r.id, true);
    dir = hold(dir, Date.now() / 1000, MANUAL_HOLD);
    const who = r.display_name || r.username;
    try {
      const res: any = await api.friendAction(action, r.id, r.target);
      if (res?.ok) {
        friendGone = { ...friendGone, [r.id]: action };
        if (action === "accept") {
          burstFrom(el, { count: 28, spread: 160 });
          roomPulse += 1;
          play("accept");
        }
        friendReqs = friendReqs.filter((x) => x.id !== r.id);
        pushFeed("friend", action === "accept" ? `Now friends with ${who}` : `Declined ${who}`, r.avatar, who);
        toast(`${action === "accept" ? "Accepted" : "Declined"} ${who}.`, "ok");
      } else {
        toast(res?.reason || "Discord refused that", "err");
      }
    } catch (e: any) {
      toast(e?.message || "That did not work", "err");
    } finally {
      setBusy(r.id, false);
    }
  }

  async function togglePause(a: BPAccount) {
    if (busy[a.id]) return;
    setBusy(a.id, true);
    dir = hold(dir, Date.now() / 1000, MANUAL_HOLD);
    try {
      const res: any = await api.accountAction(a.id, "pause");
      // The worker answers with where the toggle landed.
      if (typeof res?.paused === "boolean") {
        accts = accts.map((x) => (x.id === a.id ? { ...x, live: true, paused: res.paused } : x));
        play(res.paused ? "limit" : "accept");
        toast(res.paused ? `${a.name} stopped replying` : `${a.name} is replying again`, "ok");
      } else {
        toast(res?.reason || "The account did not answer", "err");
      }
    } catch (e: any) {
      toast(e?.message || "That did not work", "err");
    } finally {
      setBusy(a.id, false);
    }
  }

  async function setMood(a: BPAccount, mood: string, el: HTMLElement) {
    if (busy[a.id]) return;
    setBusy(a.id, true);
    dir = hold(dir, Date.now() / 1000, MANUAL_HOLD);
    try {
      const res: any = await api.accountMood(a.id, mood);
      if (res && res.ok === false) throw new Error(res.reason || "The account did not answer");
      accts = accts.map((x) => (x.id === a.id ? { ...x, live: true, mood } : x));
      burstFrom(el, { count: 16, spread: 90 });
      roomPulse += 1;
      play("accept");
      toast(`${a.name} is now ${mood}`, "ok");
    } catch (e: any) {
      toast(e?.message || "That did not work", "err");
    } finally {
      setBusy(a.id, false);
    }
  }

  const world = $derived<SceneWorld>({
    accounts: accts, activity, dates: activityDates, pictures, sent: sentPics, picturesBlurred,
    friends: friendReqs, friendGone, persona, moods, issues, busy,
  });
  const actions: SceneActions = {
    onpause: togglePause,
    onmood: setMood,
    onanswer: answerFriend,
    onreveal: () => {
      picsShown = true;
      dir = hold(dir, Date.now() / 1000, MANUAL_HOLD);
    },
    onhold: () => (dir = hold(dir, Date.now() / 1000, MANUAL_HOLD)),
    onopen: openRoute,
  };

  // ── On and off ───────────────────────────────────────────────────────────
  const stops: (() => void)[] = [];
  let clock: ReturnType<typeof setInterval> | null = null;
  let slow: ReturnType<typeof setInterval> | null = null;
  let slowTicks = 0;
  let wasFull = false;
  const onFullscreenChange = () => {
    // The browser's own Esc ends fullscreen without a key event reaching the page.
    if (!isDesktop() && wasFull && !document.fullscreenElement) close();
    wasFull = !!document.fullscreenElement;
  };

  /**
   * Work that is not on the first screen, left until the view has arrived. A
   * dozen answers landing at once each re-rendered the view in the middle of
   * its entrance, and each of those was a dropped frame.
   */
  const ARRIVED_MS = 650;
  let mountedAt = 0;
  const later: ReturnType<typeof setTimeout>[] = [];
  function onceArrived(fn: () => void) {
    later.push(setTimeout(() => {
      if (!gone()) fn();
    }, Math.max(0, ARRIVED_MS - (performance.now() - mountedAt))));
  }
  let covering: ReturnType<typeof setTimeout> | null = null;
  /** The view has arrived: what is not on the first screen can be built now. */
  let arrived = $state(false);

  onMount(() => {
    mountedAt = performance.now();
    bigPictureCloser.fn = close;
    themeColours = themePalette();
    // The app underneath fades out as this fades in (App.svelte), and once it
    // is gone it is not drawn at all. Only then does the window go fullscreen,
    // so the resize lays out this view alone rather than the whole app too.
    covering = setTimeout(() => {
      if (gone() || closing) return;
      bigPictureArriving.set(false);
      bigPictureCovering.set(true);
      setFullscreen(true);
    }, 180);
    document.addEventListener("fullscreenchange", onFullscreenChange);
    wake();
    // The first screen: who is waiting, and the accounts across the top.
    (get(chatAccounts).length ? Promise.resolve(get(chatAccounts)) : loadChatAccounts())
      .then((list) => list.forEach((a) => refreshChats(a.id, { maxAge: 15000, quiet: true })))
      .catch(() => {});
    loadRecent().then(() => onceArrived(() => {
      loadStats();
      loadMemoryStored();
    }));
    loadAccounts().then(() => {
      // The first look went before the accounts were known: Snapchat's conversations join it now.
      if (accts.some((a) => a.platform === "snapchat")) loadRecent().then(loadMemoryStored);
      onceArrived(loadFriends);
    });
    // Everything else, once it is on screen.
    onceArrived(() => {
      // Its pictures and persona come with it, as the account on show's (the effect by loadPersona).
      arrived = true;
      startUsageLive();
      loadUsage().catch(() => {});
      loadProviders().catch(() => {});
      loadActivity();
      personasRes.refresh({ maxAge: 15_000, quiet: true });
    });
    stops.push(subscribeEvents("chat", onChat), subscribeEvents("model", onModel), subscribeLogs(onLog));
    clock = setInterval(() => {
      if (document.hidden || gone()) return;
      now = Date.now() / 1000;
      dir = tick(dir, rowsFor(queue), now, cycle);
      writeOneMemory();
    }, 1000);
    slow = setInterval(() => {
      if (document.hidden || gone()) return;
      slowTicks += 1;
      loadStats();
      loadAccounts();
      loadActivity();
      loadPictures();
      // Someone new may have talked since: the recent list, and any summary they already have.
      loadRecent().then(loadMemoryStored);
      // Friend requests also come in through the log as they arrive; this catches the rest.
      if (slowTicks % 5 === 0) loadFriends();
    }, 60000);
  });
  onDestroy(() => {
    if (bigPictureCloser.fn === close) bigPictureCloser.fn = null;
    if (covering) clearTimeout(covering);
    later.forEach(clearTimeout);
    bigPictureArriving.set(false);
    bigPictureCovering.set(false);
    stops.forEach((s) => s());
    if (clock) clearInterval(clock);
    if (slow) clearInterval(slow);
    if (sleepTimer) clearTimeout(sleepTimer);
    if (friendsQueued) clearTimeout(friendsQueued);
    if (logFrame) cancelAnimationFrame(logFrame);
    document.removeEventListener("fullscreenchange", onFullscreenChange);
    setFullscreen(false);
  });

  const hhmm = $derived(fmtDate(now * 1000, HOUR_MINUTE));

  /**
   * The whole view arriving, out of a slight zoom like a scene cut, and
   * leaving the same way. Opacity and scale only, which the graphics card
   * does by itself: they used to blur the whole screen as well, and a blur the
   * size of the screen, redrawn every frame on top of everything in it, was
   * where the frames went.
   */
  function enter(_node: Element) {
    if (!get(motionEnabled)) return { duration: 200, css: (t: number) => `opacity:${t}` };
    return {
      duration: 520,
      easing: cubicOut,
      css: (t: number, u: number) => `opacity:${t}; transform: scale(${1 + 0.035 * u})`,
    };
  }
  function leave(_node: Element) {
    if (!get(motionEnabled)) return { duration: 150, css: (t: number) => `opacity:${t}` };
    return {
      duration: 260,
      easing: cubicIn,
      css: (t: number, u: number) => `opacity:${t}; transform: scale(${1 - 0.025 * u})`,
    };
  }
</script>

<svelte:window onkeydown={onKey} onmousemove={wake} onpointerdown={wake} />

<!-- no-queue: nobody is waiting, so the queue's column folds away and the stage has the room. -->
<div class="bp" class:is-asleep={!awake} class:no-queue={!railed.length} role="dialog" aria-modal="true"
     aria-label="Big Picture Mode" in:enter out:leave>
  <BPBackdrop art={room.art} seed={room.seed} look={room.look} energy={room.energy} palette={room.palette}
              pulse={roomPulse} focus={railed.length ? 0.47 : 0.4} />

  <!-- The bar itself stays: the time, which accounts are on and how they are
       doing are the things worth being able to glance at, and having them
       disappear whenever the mouse sat still read as the panel breaking. Only
       the buttons, which are chrome, fade back when nothing is happening. -->
  <header class="bp-top">
    <div class="bp-brand">
      <!-- A small beat each time something happens, so the mark itself is alive. -->
      {#key feed[0]?.id ?? 0}<span class="bp-beat"><Icon name="bigpicture" size={20} /></span>{/key}
      <span>Big Picture</span>
    </div>
    <div class="bp-clock">{hhmm}</div>
    <div class="bp-accts">
      {#each accts as a (a.id)}
        <button class="bp-acct" data-state={a.state} class:is-paused={a.paused} onclick={() => goChapter("accounts")}
                title="{a.name}: {a.paused ? 'paused' : a.state}{a.ping != null ? `, ${a.ping} ms` : ''}">
          <Avatar src={a.avatar} name={a.name} size={26} zoom={false} /><i></i>
        </button>
      {/each}
    </div>
    <div class="bp-pills">
      {#if urgent.length}
        <button class="bp-pill" data-tone={urgent.some((i) => i.level === "error") ? "bad" : "warn"}
                onclick={() => goChapter("health")} title={urgent.map((i) => i.title).join(" · ")}>
          <i></i>{urgent.length} to look at
        </button>
      {:else}
        <span class="bp-pill" data-tone="good" title="Nothing needs attention"><i></i>All good</span>
      {/if}
      {#if friendReqs.length}
        <button class="bp-pill is-friends" onclick={() => goChapter("friends")} in:fade={{ duration: 300 }}
                title="Friend requests waiting">
          <Avatar src={friendReqs[0].avatar} name={friendReqs[0].display_name || friendReqs[0].username} size={20} zoom={false} />
          {friendReqs.length} friend request{friendReqs.length === 1 ? "" : "s"}
        </button>
      {/if}
    </div>
    <div class="bp-ctrls" class:is-dim={!awake}>
      <button class="bp-btn" onclick={() => (help = !help)} title="Shortcuts (?)" aria-label="Shortcuts">
        <Icon name="keyboard" size={17} />
      </button>
      <button class="bp-btn" class:is-on={$bigPictureSound} onclick={toggleSound} title="Sound (M)" aria-label="Sound">
        <Icon name={$bigPictureSound ? "speaker" : "speakerOff"} size={17} />
      </button>
      <button class="bp-btn" class:is-on={dir.pinned} onclick={() => (dir = togglePin(dir))}
              title={dir.pinned ? "Let it move on (Space)" : "Hold what is on stage (Space)"} aria-label="Hold">
        <Icon name={dir.pinned ? "pause" : "play"} size={15} />
      </button>
      <button class="bp-btn" class:is-on={hideText} onclick={() => (hideText = !hideText)} title="Hide message text and pictures (H)" aria-label="Hide text">
        <Icon name={hideText ? "eyeOff" : "eye"} size={16} />
      </button>
      <button class="bp-btn is-close" onclick={close} title="Leave Big Picture (Esc)" aria-label="Leave Big Picture">
        <Icon name="close" size={17} />
      </button>
    </div>
  </header>

  <main class="bp-main">
    <aside class="bp-left" aria-hidden={!railed.length}>
      <BPQueue rows={railed} spotlight={dir.spotlight} {multi} {hideText} {now} onpick={pickRow} />
    </aside>
    <!-- Moving the pointer over the stage holds it: nothing slides away from under a click. -->
    <section class="bp-center" use:pointerActivity={holdStage}>
      <BPStage {spot} {messages} {now} {hideText} {multi}
               onearlier={spot ? () => loadEarlier(spot.target, spot.u.id) : undefined}
               busy={acting} replying={!!spot && !!$replying[spot.u.id]}
               onreply={spot ? () => doReply(spot) : undefined}
               oncancel={spot ? () => doCancel(spot) : undefined}
               onignore={spot ? () => doIgnore(spot) : undefined}
               onsend={spot ? (t) => doSend(spot, t) : undefined}
               {scene} sceneKey={dir.idle?.scene ?? 0}
               sceneData={{ recent, today, hourly: stats.hourly, top: stats.top, memory: memPerson, waiting: railed.length,
                            world, act: actions }} />
      <BPChapters {chapters} current={spot ? null : scene} live={!!spot} waiting={railed.length}
                  progress={sceneProgress(dir, now)} sceneKey={dir.idle?.scene ?? 0} {held} pinned={dir.pinned}
                  {badges} tones={{ health: urgent.some((i) => i.level === "error") ? "bad" : "warn" }}
                  ongo={goChapter} onlive={goLive} onpin={() => (dir = togglePin(dir))} />
    </section>
    <!-- Built once the view has arrived, and faded in: the first frame has the stage and the queue to build, not everything. -->
    <aside class="bp-right" class:is-waiting={!arrived}>
      {#if arrived}
        <BPBrain active={brainModel} forName={spot && byConv[spot.u.id] ? spot.u.name : ""}
                 {helper} {pulse} plan={$savedPlan} models={$usage.models} {now} />
        <BPThoughts {thoughts} {hideText} {now} />
        <BPRotate items={feed} {now} {hideText} {today} top={stats.top} accounts={accts} {logs} />
      {/if}
    </aside>
  </main>

  <footer class="bp-bottom">
    <BPStats {today} hourly={stats.hourly} accounts={accts} />
  </footer>

  {#if help}
    <!-- Every shortcut in one place; a click anywhere, or Esc, puts it away. -->
    <div class="bp-help" role="presentation" onclick={() => (help = false)} transition:fade={{ duration: 180 }}>
      <div class="bp-help-card" role="dialog" aria-label="Shortcuts">
        <div class="bp-label">Shortcuts</div>
        <dl>
          <dt><kbd>←</kbd><kbd>→</kbd></dt><dd>The next conversation, or the next scene</dd>
          <dt><kbd>1</kbd>–<kbd>9</kbd></dt><dd>Go to a chapter</dd>
          <dt><kbd>L</kbd></dt><dd>Back to whoever is being answered</dd>
          <dt><kbd>Space</kbd></dt><dd>Hold what is on stage, or let it move on</dd>
          <dt><kbd>H</kbd></dt><dd>Hide message text and pictures</dd>
          <dt><kbd>M</kbd></dt><dd>Sound on or off</dd>
          <dt><kbd>?</kbd></dt><dd>This list</dd>
          <dt><kbd>Esc</kbd></dt><dd>Leave Big Picture</dd>
        </dl>
        <p>Moving the pointer over the stage holds it while you look.</p>
      </div>
    </div>
  {/if}
</div>

<style>
  .bp {
    --bp-faint: rgb(255 255 255 / 0.46);
    --bp-muted: rgb(255 255 255 / 0.7);
    position: fixed;
    inset: 0;
    z-index: 200;
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto;
    gap: clamp(12px, 1.6vh, 22px);
    padding-bottom: clamp(12px, 2vh, 26px);
    overflow: hidden;
    color: #fff;
    color-scheme: dark;
    background: #04050a;
    transform-origin: 50% 45%;
  }
  .bp.is-asleep { cursor: none; }
  /* Over the backdrop, which is absolutely placed under everything. */
  .bp-top, .bp-main, .bp-bottom { position: relative; z-index: 1; }
  .bp-top {
    display: flex;
    align-items: center;
    gap: 18px;
    padding: clamp(12px, 2vh, 22px) clamp(16px, 2.2vw, 32px) 0;
    transition: opacity 0.6s ease, transform 0.6s var(--swift);
  }
  /* Idle: the buttons sit back, but stay there and stay clickable. */
  .bp-ctrls.is-dim { opacity: 0.25; }
  .bp-ctrls:hover { opacity: 1; }
  .bp-brand { display: flex; align-items: center; gap: 9px; font-size: 15px; font-weight: 750; letter-spacing: 0.02em; }
  .bp-beat { display: grid; animation: bp-beat 0.7s var(--spring) both; }
  @keyframes bp-beat { 0% { transform: scale(1); } 35% { transform: scale(1.22); } 100% { transform: scale(1); } }
  /* overflow: visible so the glow is not cut square at the icon's own viewBox. */
  .bp-brand :global(svg) {
    overflow: visible;
    color: var(--color-accent);
    filter: drop-shadow(0 0 14px color-mix(in srgb, var(--color-accent) 42%, transparent));
  }
  .bp-clock { font-size: 15px; font-weight: 600; color: var(--bp-muted); font-variant-numeric: tabular-nums; }
  .bp-accts { display: flex; gap: 6px; margin-left: 6px; }
  .bp-acct { position: relative; display: grid; border-radius: 999px; transition: transform 0.3s var(--spring); }
  .bp-acct:hover { transform: scale(1.1); }
  .bp-acct i { position: absolute; right: -1px; bottom: -1px; width: 9px; height: 9px; border-radius: 999px; background: var(--bp-faint); box-shadow: 0 0 0 2px #04050a; }
  .bp-acct[data-state="running"] i { background: var(--color-good); box-shadow: 0 0 0 2px #04050a, 0 0 14px color-mix(in srgb, var(--color-good) 42%, transparent); }
  .bp-acct[data-state="running"].is-paused i { background: var(--color-warn); box-shadow: 0 0 0 2px #04050a; }
  .bp-acct[data-state="crashing"] i { background: var(--color-bad); }

  /* What is worth knowing without looking for it: whether anything is wrong, and who is asking to be friends. */
  .bp-pills { display: flex; min-width: 0; gap: 8px; }
  .bp-pill {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 7px;
    height: 30px;
    padding: 0 12px 0 10px;
    border-radius: 999px;
    font-size: 12.5px;
    font-weight: 600;
    white-space: nowrap;
    color: var(--bp-muted);
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.07);
    transition: transform 0.3s var(--spring), background-color 0.2s ease, color 0.2s ease;
  }
  button.bp-pill:hover { transform: translateY(-1px); color: #fff; background: rgb(255 255 255 / 0.1); }
  button.bp-pill:active { transform: scale(0.95); }
  .bp-pill i { width: 8px; height: 8px; border-radius: 999px; background: var(--bp-faint); }
  .bp-pill[data-tone="good"] i { background: var(--color-good); box-shadow: 0 0 12px color-mix(in srgb, var(--color-good) 42%, transparent); }
  .bp-pill[data-tone="warn"] { color: #fff; }
  .bp-pill[data-tone="warn"] i { background: var(--color-warn); animation: bp-blink 1.8s ease-in-out infinite; }
  .bp-pill[data-tone="bad"] { color: #fff; background: color-mix(in srgb, var(--color-bad) 22%, transparent); }
  .bp-pill[data-tone="bad"] i { background: var(--color-bad); animation: bp-blink 1.2s ease-in-out infinite; }
  @keyframes bp-blink { 50% { opacity: 0.35; } }
  .bp-pill.is-friends { padding-left: 5px; color: #fff; background: color-mix(in srgb, var(--color-accent) 30%, transparent); }

  .bp-ctrls { display: flex; gap: 6px; margin-left: auto; transition: opacity 0.6s ease; }
  .bp-btn {
    display: grid;
    width: 40px;
    height: 40px;
    place-items: center;
    border-radius: 14px;
    color: var(--bp-muted);
    background: rgb(255 255 255 / 0.06);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08);
    backdrop-filter: blur(14px);
    transition: transform 0.3s var(--spring), color 0.2s ease, background-color 0.2s ease;
  }
  .bp-btn:hover { transform: scale(1.08); color: #fff; background: rgb(255 255 255 / 0.12); }
  .bp-btn:active { transform: scale(0.92); }
  .bp-btn.is-on { color: #fff; background: color-mix(in srgb, var(--color-accent) 40%, transparent); }
  .bp-btn.is-close:hover { background: var(--color-bad); }

  /* Each column is as wide as what it has to say. With nobody waiting the
     queue's column folds to nothing and the stage takes its room; the moment
     someone writes, it opens again. The queue keeps its full width while its
     column folds, so it slides away under the edge instead of squeezing. */
  .bp-main {
    --bp-lw-open: clamp(250px, 21vw, 420px);
    --bp-lw: var(--bp-lw-open);
    --bp-rw: clamp(290px, 24vw, 460px);
    display: grid;
    grid-template-columns: var(--bp-lw) minmax(0, 1fr) var(--bp-rw);
    gap: clamp(16px, 2vw, 30px);
    min-height: 0;
    padding: 0 clamp(16px, 2.2vw, 32px);
    transition: grid-template-columns 0.85s var(--swift);
  }
  .bp.no-queue .bp-main { --bp-lw: 0px; }
  .bp-left, .bp-center, .bp-right { display: flex; min-width: 0; min-height: 0; flex-direction: column; }
  .bp-left { overflow: hidden; transition: opacity 0.45s ease; }
  .bp-left > :global(.bpq) { width: var(--bp-lw-open); flex: 1 1 auto; }
  .bp.no-queue .bp-left { opacity: 0; pointer-events: none; }
  .bp-center { gap: 10px; }
  .bp-right { gap: 12px; transition: opacity 0.4s ease; }
  .bp-right.is-waiting { opacity: 0; }
  :global(:root[data-motion="off"]) .bp-main { transition: none; }
  .bp-bottom { padding: 0 clamp(16px, 2.2vw, 32px); }
  .bp :global(.bp-label) {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11.5px;
    font-weight: 700;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: var(--bp-faint);
  }
  .bp :global(.bp-n) {
    padding: 1px 8px;
    border-radius: 999px;
    font-size: 11px;
    letter-spacing: 0;
    color: #fff;
    background: color-mix(in srgb, var(--color-accent) 45%, transparent);
  }
  /* The scenes' own headings, the same in every one of them. */
  .bp :global(.bp-kicker) { font-size: 12px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--bp-faint); }
  /* By the width and the height both: on a short screen a 58px heading is a sixth of the stage. */
  .bp :global(.bp-title) {
    margin-bottom: 8px;
    font-size: clamp(28px, min(4vw, 6.4vh), 58px);
    font-weight: 750;
    line-height: 1.04;
    letter-spacing: -0.03em;
    color: #fff;
  }

  .bp-help {
    position: absolute;
    inset: 0;
    z-index: 5;
    display: grid;
    place-items: center;
    padding: 16px;
    background: rgb(0 0 0 / 0.55);
    backdrop-filter: blur(6px);
  }
  .bp-help-card {
    display: flex;
    width: min(460px, 100%);
    flex-direction: column;
    gap: 14px;
    padding: 24px 26px;
    border-radius: 26px;
    background: rgb(20 22 32 / 0.92);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.1), 0 40px 100px -30px rgb(0 0 0 / 0.9);
  }
  .bp-help-card dl { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 10px 18px; align-items: center; }
  .bp-help-card dt { display: flex; gap: 4px; justify-content: flex-end; color: var(--bp-faint); }
  .bp-help-card dd { font-size: 14px; color: #fff; }
  .bp-help-card kbd {
    min-width: 26px;
    padding: 3px 7px;
    border-radius: 7px;
    font-family: inherit;
    font-size: 12px;
    font-weight: 700;
    text-align: center;
    color: #fff;
    background: rgb(255 255 255 / 0.1);
    box-shadow: inset 0 -2px 0 rgb(0 0 0 / 0.35), inset 0 0 0 1px rgb(255 255 255 / 0.12);
  }
  .bp-help-card p { font-size: 12.5px; color: var(--bp-faint); }

  /* Narrower screens: the queue and the stage; the brain gives way. */
  @media (max-width: 1100px) {
    .bp-main { --bp-lw-open: clamp(220px, 34vw, 340px); grid-template-columns: var(--bp-lw) minmax(0, 1fr); }
    .bp-right { display: none; }
  }
  @media (max-width: 960px) {
    .bp-pill.is-friends, .bp-clock { display: none; }
  }
  /* A phone, or the app shrunk to its pocket size: one column, stage first. */
  @media (max-width: 720px) {
    .bp { overflow-x: hidden; overflow-y: auto; grid-template-rows: auto auto auto; }
    /* minmax(0, ...): a column may be narrower than its longest line, which is what keeps it on screen.
       min-height auto: the view scrolls here, so the middle row is as tall as the stage in it. At 0
       it was squeezed into what the screen had left, and a tall scene ran on under the numbers. */
    .bp-main { grid-template-columns: minmax(0, 1fr); min-height: auto; }
    .bp-left > :global(.bpq) { width: auto; }
    .bp.no-queue .bp-left { display: none; }
    .bp-center { order: -1; min-height: 62vh; }
    .bp-accts, .bp-clock, .bp-pills { display: none; }
    .bp-top { flex-wrap: wrap; gap: 10px; }
    .bp-btn { width: 36px; height: 36px; }
    .bp-bottom :global(.bst) { grid-template-columns: minmax(0, 1fr); }
    .bp-bottom :global(.bst-nums) { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .bp-bottom :global(.bst-accts) { flex-wrap: wrap; }
  }
  :global(:root[data-motion="off"]) .bp-beat,
  :global(:root[data-motion="off"]) .bp-pill i { animation: none; }
</style>
