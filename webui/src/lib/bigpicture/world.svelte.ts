/**
 * Everything Big Picture knows, apart from who is on stage: the accounts, the
 * day's numbers, the people, the pictures, the persona, the friend requests,
 * and what just happened.
 *
 * It reads the same live data the rest of the app keeps: the Chats cache (kept
 * live app-wide by App.svelte), model usage (modelusage.ts), the log stream for
 * the log and for friend requests, the Health poll, and the stats. What is not
 * on screen is not asked for: each page says when it comes up (ensure), and
 * the rest waits. Most of this is a local read and costs nothing.
 *
 * The things that do cost the account something are kept scarce. Friend requests
 * are a call to Discord each, so they are asked for on opening, when the log says
 * one arrived, and otherwise every five minutes. A new Memory summary is a call
 * to the small model and at most one read of that DM, so stored ones are read
 * first, which writes nothing, and only a handful of new ones are written, a while
 * apart, while nothing else is going on.
 *
 * The day's numbers come from api.statsDetail, which counts every platform. The
 * overview the Dashboard polls is Discord's own, past its per-platform totals,
 * and using it here left every other platform out of them.
 */
import { get } from "svelte/store";
import { api } from "../api";
import { toast } from "../stores";
import { chatAccounts, chatCache, type ChatUser } from "../chats";
import { shortModel } from "../providers";
import { loadMoods } from "../accounts/state";
import { personasRes } from "../personas/store";
import { platformName } from "../accounts/condition";
import { platformOfUser } from "../platforms";
import { platformOn, socialsOn } from "../socials";
import { isMore, isRule, kindOf, sourceInfo, tidy } from "../logrows";
import type { Page } from "./director";
import { MANUAL_HOLD } from "./director";
import { burstFrom } from "./fx";
import { rumble } from "./gamepad";
import { lastDay, mergePeople, personaLines, sentPictures } from "./scenes";
import { play } from "./sounds";
import { play as uiPlay } from "../uisound";
import type { Active, BPAccount, BPActivity, DayStats, FeedItem, FriendReq, LogLite, MemoryLine, Person, Picture, QRow,
              Remembered, SentPicture } from "./types";

type Hooks = {
  /** Closed or closing: nothing more is asked for or said. */
  gone: () => boolean;
  /** Is this the conversation on stage? */
  onStage: (target: string, uid: string) => boolean;
  /** Something was done by hand: keep what is up, up. */
  hold: (secs: number) => void;
  /** Something landed: a ring of light across the room. */
  pulse: () => void;
};

const EMPTY_DAY: DayStats = { replies: 0, repliesBefore: 0, people: 0, peopleBefore: 0, hourly: [], platform: {}, loaded: false };

/** How many people are read, per account. */
const PEOPLE_PER_ACCOUNT = 30;
/** Of everyone, how many are worth asking for a stored summary before they are looked at. */
const MEM_CANDIDATES = 10;
/** New summaries written by themselves, per visit, and how far apart. */
const MEM_WRITES = 4;
const MEM_GAP = 45_000;
/** One look at the friend requests, at most this often: each is a call to Discord. */
const FRIENDS_EVERY = 20_000;

const FRIEND_ASK = /^(?:pending )?friend request from (.+?)(?: \(was previously a friend\))?,? (?:will accept|accepting) in \d+s/i;
const FRIEND_TAKEN = /^accepted friend request from (.+)$/i;

export class World {
  private hooks: Hooks;
  constructor(hooks: Hooks) {
    this.hooks = hooks;
  }

  // ── The accounts ─────────────────────────────────────────────────────────
  accounts = $state<BPAccount[]>([]);
  activity = $state<Record<string, BPActivity>>({});
  /** The calendar day of each entry of an activity series, oldest first. */
  dates = $state<string[]>([]);
  /** A Minecraft account with a picture to watch: only one that is in a world has one. */
  minecraft = $state<BPAccount | null>(null);
  /** Anything with an action on its way, by the id of what it is on. */
  busy = $state<Record<string, boolean>>({});
  /** Only this platform's accounts on the Accounts page. */
  platformFilter = $state<string | null>(null);
  private accountsAt = 0;

  private setBusy(id: string, on: boolean) {
    const next = { ...this.busy };
    if (on) next[id] = true;
    else delete next[id];
    this.busy = next;
  }

  /** Every account, who it is and how it is: the supervisor's word, and the worker's own when it answers. */
  async loadAccounts() {
    this.accountsAt = Date.now();
    try {
      const d: any = await api.accounts();
      const on = get(socialsOn);
      const rows = (d?.accounts ?? []).filter((a: any) => a.platform !== "controller" && platformOn(on, a.platform));
      const details = await Promise.all(rows.map((a: any) =>
        a.state === "running" ? api.accountDetails(a.id).catch(() => null) : Promise.resolve(null)));
      if (this.hooks.gone()) return;
      this.accounts = rows.map((a: any, i: number): BPAccount => {
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

  async loadMinecraft() {
    for (const a of this.accounts.filter((x) => x.platform === "minecraft" && x.state === "running")) {
      try {
        const r: any = await api.minecraftView(a.id);
        if (r?.ready) {
          this.minecraft = a;
          return;
        }
      } catch {
        /* the next one */
      }
    }
    this.minecraft = null;
  }

  async loadActivity() {
    try {
      const d: any = await api.accountActivity(7);
      this.activity = d?.accounts ?? {};
      this.dates = d?.dates ?? [];
    } catch {
      /* the cards go without their week */
    }
  }

  async togglePause(a: BPAccount) {
    if (this.busy[a.id]) return;
    this.setBusy(a.id, true);
    this.hooks.hold(MANUAL_HOLD);
    try {
      const res: any = await api.accountAction(a.id, "pause");
      // The worker answers with where the toggle landed.
      if (typeof res?.paused === "boolean") {
        this.accounts = this.accounts.map((x) => (x.id === a.id ? { ...x, live: true, paused: res.paused } : x));
        toast(res.paused ? `${a.name} stopped replying` : `${a.name} is replying again`, "ok");
      } else {
        toast(res?.reason || "The account did not answer", "err");
      }
      return res?.paused as boolean | undefined;
    } catch (e: any) {
      toast(e?.message || "That did not work", "err");
    } finally {
      this.setBusy(a.id, false);
    }
  }

  async setMood(a: BPAccount, mood: string, el: HTMLElement) {
    if (this.busy[a.id]) return;
    this.setBusy(a.id, true);
    this.hooks.hold(MANUAL_HOLD);
    try {
      const res: any = await api.accountMood(a.id, mood);
      if (res && res.ok === false) throw new Error(res.reason || "The account did not answer");
      this.accounts = this.accounts.map((x) => (x.id === a.id ? { ...x, live: true, mood } : x));
      burstFrom(el, { count: 16, spread: 90 });
      this.hooks.pulse();
      uiPlay("glint", { p: 0.8, strong: true });
      rumble();
      toast(`${a.name} is now ${mood}`, "ok");
    } catch (e: any) {
      toast(e?.message || "That did not work", "err");
    } finally {
      this.setBusy(a.id, false);
    }
  }

  // ── The day ──────────────────────────────────────────────────────────────
  day = $state<DayStats>({ ...EMPTY_DAY });
  /** Replies this week on each platform, for the chips on Accounts and the split on Today. */
  weekPlatform = $state<Record<string, number>>({});
  /** Messages from each person this week, by id, on every platform. */
  weekCounts = $state<Record<string, number>>({});

  async loadDay() {
    try {
      const d: any = await api.statsDetail(1);
      if (this.hooks.gone()) return;
      this.day = {
        replies: d?.total ?? 0, repliesBefore: d?.previous ?? 0,
        people: d?.people?.window ?? 0, peopleBefore: d?.people?.previous ?? 0,
        hourly: lastDay(d?.hourly ?? [], new Date().getHours()),
        platform: d?.platform ?? {},
        loaded: true,
      };
    } catch {
      /* the numbers stay what they were */
    }
  }

  async loadWeek() {
    try {
      const d: any = await api.statsDetail(7);
      if (this.hooks.gone()) return;
      const on = get(socialsOn);
      this.weekPlatform = Object.fromEntries(Object.entries(d?.platform ?? {}).filter(([p]) => on[p as keyof typeof on] !== false)) as Record<string, number>;
      this.weekCounts = Object.fromEntries((d?.top ?? []).map((t: any) => [String(t.id), t.count ?? 0]));
    } catch {
      /* no split this time */
    }
  }

  /** A reply went out while watching: the number moves as it happens, and its hour with it. */
  private countSent() {
    const last = this.day.hourly[this.day.hourly.length - 1];
    this.day = {
      ...this.day,
      replies: this.day.replies + 1,
      hourly: last ? [...this.day.hourly.slice(0, -1), { ...last, count: last.count + 1 }] : this.day.hourly,
    };
  }

  // ── The people ───────────────────────────────────────────────────────────
  people = $state<Person[]>([]);
  /** Their stored summaries, by id. */
  memory = $state<Record<string, Remembered>>({});
  /** Summaries are turned off in Settings, or nothing is running that could write one. */
  memOff = $state(false);
  /** Whose summary is being written because someone asked, by id. */
  writing = $state<Record<string, boolean>>({});
  /** Whose turn it is on the tour: the next one each time People comes round. */
  turn = $state(0);
  private peopleSeq = 0;
  private memAsked = new Set<string>();
  private memTried = new Set<string>();
  private memWrites = 0;
  private memLastWrite = 0;
  private memWriting = false;

  async loadPeople() {
    const seq = ++this.peopleSeq;
    const accounts = this.accounts;
    try {
      // Every account's own, so each person knows which account to open them on.
      const lists = await Promise.all(accounts.map((a) =>
        api.chatArchive(PEOPLE_PER_ACCOUNT, a.id)
          .then((d: any): Person[] => (d?.conversations ?? []).map((c: any) => ({
            key: `${a.id}:${c.id}`, target: a.id, id: String(c.id), name: c.name, avatar: c.avatar, platform: a.platform,
            messages: c.messages ?? 0, last_ts: c.last_ts,
          })))
          .catch((): Person[] => [])));
      if (seq !== this.peopleSeq || this.hooks.gone()) return;   // a later look, with more accounts in it, is on its way
      this.people = mergePeople(lists);
      this.loadStoredSummaries();
    } catch {
      /* People says it has nobody yet */
    }
  }

  /** Someone's stored summary, if it has not been asked for this visit. Local, and writes nothing. */
  async askSummary(id: string) {
    if (this.memOff || this.memAsked.has(id)) return;
    this.memAsked.add(id);
    try {
      const r: any = await api.memorySummary(id, false, true);
      if (r?.enabled === false) {
        this.memOff = true;
        return;
      }
      if (r?.ok && r.summary) this.remember(id, r);
    } catch {
      /* they go without */
    }
  }

  private remember(id: string, r: any) {
    const recent: MemoryLine[] = (r.recent ?? [])
      .filter((l: any) => l && typeof l.text === "string" && l.text.trim())
      .map((l: any) => ({ mine: !!l.mine, text: String(l.text) }));
    this.memory = { ...this.memory, [id]: { summary: String(r.summary), generated_at: r.generated_at, count: r.count, recent } };
  }

  private async loadStoredSummaries() {
    for (const p of this.people.slice(0, MEM_CANDIDATES)) {
      if (this.hooks.gone() || this.memOff) return;
      await this.askSummary(p.id);
    }
  }

  /** The tour's few, in the background: one at a time, a while apart, only while nobody is on stage. */
  async writeOneSummary(quiet: boolean) {
    if (this.memOff || this.memWriting || this.hooks.gone() || document.hidden || !quiet) return;
    if (this.memWrites >= MEM_WRITES || Date.now() - this.memLastWrite < MEM_GAP) return;
    const p = this.people.slice(0, MEM_CANDIDATES)
      .find((x) => this.memAsked.has(x.id) && !this.memTried.has(x.id) && !this.memory[x.id]);
    if (!p) return;
    this.memTried.add(p.id);
    this.memWriting = true;
    this.memWrites += 1;
    this.memLastWrite = Date.now();
    try {
      const r: any = await api.memorySummary(p.id);
      if (r?.ok && r.summary) this.remember(p.id, r);
      else if (r?.enabled === false || /No account is running/i.test(r?.reason ?? "")) this.memOff = true;
    } catch {
      /* someone else next time */
    } finally {
      this.memWriting = false;
    }
  }

  /** Asked for by hand: one summary, now. */
  async writeSummary(p: Person) {
    if (this.writing[p.id]) return;
    this.writing = { ...this.writing, [p.id]: true };
    this.hooks.hold(MANUAL_HOLD);
    try {
      const r: any = await api.memorySummary(p.id);
      if (r?.ok && r.summary) {
        this.remember(p.id, r);
        uiPlay("done");
      } else {
        toast(r?.reason || "It could not write one", "err");
      }
    } catch (e: any) {
      toast(e?.message || "That did not work", "err");
    } finally {
      const next = { ...this.writing };
      delete next[p.id];
      this.writing = next;
    }
  }

  /** Who a row is, from the queue as it is, or as it was when it left (answered), or the people. */
  whoIs(target: string, uid: string): { name: string; avatar?: string } {
    const u: ChatUser | undefined = get(chatCache)[target]?.users.find((x) => x.id === uid) ?? this.snapshots.get(`${target}:${uid}`)?.u;
    if (u) return { name: u.name, avatar: u.avatar };
    const r = this.people.find((x) => x.id === uid);
    return r ? { name: r.name, avatar: r.avatar } : { name: "someone" };
  }

  /** The one on stage stays drawn after it leaves the queue (it was answered), from its last snapshot. */
  snapshots = new Map<string, QRow & { browsing?: boolean }>();

  /** The last reply anyone got, for the quiet screen: as it was sent, or else from the log. */
  lastSent = $state<{ target: string; id: string; name: string; ts: number } | null>(null);
  get lastReply(): { target: string; id: string; name: string; ts: number } | null {
    let best = this.lastSent;
    for (const a of this.accounts) {
      const last = this.activity[a.id]?.last;
      if (last && (!best || last.ts > best.ts)) best = { target: a.id, id: String(last.id), name: last.name, ts: last.ts };
    }
    return best;
  }

  // ── The bot's own: its persona and its pictures ──────────────────────────
  personaText = $state("");
  personaOf = $state("");
  moods = $state<string[]>([]);
  /** Each persona's moods, as they have been read, for an account's grown card. */
  moodsBy = $state<Record<string, string[]>>({});
  private moodsAsked = new Set<string>();
  pictures = $state<Picture[]>([]);
  /** The pictures that went out while watching, by file name. */
  sentPics = $state<Record<string, SentPicture>>({});
  /** Whose pictures the gallery shows: "" for Default's. */
  private picturesOf = "\0";
  private picturesAt = 0;

  get personaLines(): string[] {
    return personaLines(this.personaText);
  }

  /** Who an account speaks as: its own text, moods and pictures (app/utils/personas.py). */
  async loadPersona(pid: string) {
    if (pid === this.personaOf && this.personaText) return;
    try {
      const d: any = await api.personaText(pid);
      this.personaOf = pid;
      this.personaText = String(d?.text ?? "");
    } catch {
      /* the page says it has nothing to show */
    }
    this.moods = await loadMoods(false, pid).catch(() => []);
  }

  /** The moods of the persona an account speaks as, read the first time they are wanted. */
  moodsFor(pid: string): string[] {
    if (!this.moodsAsked.has(pid)) {
      this.moodsAsked.add(pid);
      loadMoods(false, pid).then((m) => (this.moodsBy = { ...this.moodsBy, [pid]: m })).catch(() => {});
    }
    return this.moodsBy[pid] ?? [];
  }

  async loadPictures(pid: string, force = false) {
    const as = pid === "default" ? "" : pid;
    if (!force && as === this.picturesOf && Date.now() - this.picturesAt < 300_000) return;
    this.picturesAt = Date.now();
    try {
      const d: any = await api.pictures(as);
      this.picturesOf = as;
      this.pictures = (d?.pictures ?? []).map((p: any) => ({
        name: String(p.name), description: String(p.description ?? ""),
        // A video shows as its still.
        url: api.pictureThumb({ name: String(p.name), id: String(p.id ?? ""), video: !!p.video }, as),
      }));
    } catch {
      /* the page says it has nothing to show */
    }
  }

  // ── Friend requests ──────────────────────────────────────────────────────
  friends = $state<FriendReq[]>([]);
  friendGone = $state<Record<string, "accept" | "decline">>({});
  private friendsAt = 0;
  private friendsQueued: ReturnType<typeof setTimeout> | null = null;

  async loadFriends() {
    this.friendsAt = Date.now();
    const targets = this.accounts.filter((a) => a.state === "running");
    if (!targets.length) {
      this.friends = [];
      return;
    }
    const lists = await Promise.all(targets.map((a) =>
      api.friends(a.id)
        .then((d: any) => (d?.requests ?? []).filter((r: any) => r.incoming).map((r: any): FriendReq => ({
          id: String(r.id), username: String(r.username ?? ""), display_name: r.display_name || "",
          avatar: r.avatar || "", accept_at: r.accept_at ?? null, target: a.id,
        })))
        .catch(() => null)));
    if (this.hooks.gone()) return;
    // An account that did not answer keeps what it had, rather than emptying the list.
    this.friends = targets.flatMap((a, i) => lists[i] ?? this.friends.filter((r) => r.target === a.id));
  }

  /** Soon, but never more than once every twenty seconds. */
  friendsSoon(delay = 2500) {
    if (this.friendsQueued) return;
    const wait = Math.max(delay, FRIENDS_EVERY - (Date.now() - this.friendsAt));
    this.friendsQueued = setTimeout(() => {
      this.friendsQueued = null;
      if (!this.hooks.gone()) this.loadFriends();
    }, wait);
  }

  async answerFriend(r: FriendReq, action: "accept" | "decline", el: HTMLElement | null) {
    if (this.busy[r.id]) return;
    this.setBusy(r.id, true);
    this.hooks.hold(MANUAL_HOLD);
    const who = r.display_name || r.username;
    try {
      const res: any = await api.friendAction(action, r.id, r.target);
      if (res?.ok) {
        this.friendGone = { ...this.friendGone, [r.id]: action };
        if (action === "accept") {
          burstFrom(el, { count: 28, spread: 160 });
          this.hooks.pulse();
          uiPlay("done");
          rumble(0.6);
        }
        this.friends = this.friends.filter((x) => x.id !== r.id);
        this.pushFeed("friend", action === "accept" ? `Now friends with ${who}` : `Declined ${who}`, { avatar: r.avatar, name: who });
        toast(`${action === "accept" ? "Accepted" : "Declined"} ${who}.`, "ok");
      } else {
        toast(res?.reason || "Discord refused that", "err");
      }
    } catch (e: any) {
      toast(e?.message || "That did not work", "err");
    } finally {
      this.setBusy(r.id, false);
    }
  }

  // ── What just happened ───────────────────────────────────────────────────
  feed = $state<FeedItem[]>([]);
  private feedId = 0;
  logs = $state<LogLite[]>([]);
  private logId = 0;
  private logBuf: LogLite[] = [];
  private logFrame = 0;
  active = $state<Active | null>(null);
  /** The model that last wrote for each person, by their id. */
  byConv = $state<Record<string, Active>>({});
  /** A model doing background work (memory, pictures, voice), mentioned under the replies model for a moment. */
  helper = $state<{ model: string; job: string; at: number } | null>(null);
  /** Counts answers from a model: its tile pulses with each. */
  answered = $state(0);
  /** Counts messages in: the Now tab's faces bounce with each. */
  arrivals = $state(0);

  pushFeed(kind: FeedItem["kind"], text: string, o: { avatar?: string; name?: string; uid?: string; target?: string } = {}) {
    const platform = o.uid ? platformOfUser(o.uid).id : undefined;
    this.feed = [{ id: ++this.feedId, kind, text, avatar: o.avatar, name: o.name, platform, uid: o.uid, target: o.target, at: Date.now() / 1000 }, ...this.feed].slice(0, 30);
  }

  /** Who wrote in the last half hour, once, so the list does not open empty and say nothing has happened. */
  private seeded = false;
  seedFeed(rows: QRow[]) {
    if (this.seeded) return;
    this.seeded = true;
    const since = Date.now() / 1000 - 1800;
    // One that has already come in as it happened is on the list by now.
    const told = new Set(this.feed.filter((i) => i.kind === "arrive").map((i) => i.uid));
    const items: FeedItem[] = rows
      .filter((r) => (r.u.ts ?? 0) > since && !told.has(String(r.u.id)))
      .sort((a, b) => (b.u.ts ?? 0) - (a.u.ts ?? 0))
      .slice(0, 10)
      .map((r) => ({
        id: ++this.feedId, kind: "arrive", text: `${r.u.name}: ${(r.u.text || r.u.snippet || "sent a message").replace(/\s+/g, " ")}`,
        avatar: r.u.avatar, name: r.u.name, platform: r.account?.platform ?? platformOfUser(r.u.id).id,
        uid: String(r.u.id), target: r.target, at: r.u.ts ?? 0,
      }));
    this.feed = [...this.feed, ...items].slice(0, 30);
  }

  /** The last of the log as it stands, so that list has something on it too. A local read. */
  async loadBacklog() {
    try {
      const d: any = await api.logs(40);
      if (this.logs.length) return;
      for (const l of d?.lines ?? []) this.addLog({ ...l, ts: l.ts || Date.now() / 1000 });
    } catch {
      /* it fills as it is written */
    }
  }

  onChat = (evt: Record<string, any> | null) => {
    if (!evt || this.hooks.gone()) return;
    const target = String(evt.target ?? "");
    const uid = String(evt.uid ?? "");
    if (evt.t === "msg") {
      play("arrive");
      this.arrivals += 1;
      const what = (evt.snippet || evt.text || (evt.attachments?.length ? "sent a picture" : "sent a message")).replace(/\s+/g, " ");
      this.pushFeed("arrive", `${evt.name || this.whoIs(target, uid).name}: ${what}`, { avatar: evt.avatar, name: evt.name, uid, target });
    } else if (evt.t === "state" && evt.state?.state === "writing") {
      play("write");
      this.pushFeed("write", `Writing a reply to ${this.whoIs(target, uid).name}`, { uid, target });
    } else if (evt.t === "sent") {
      this.countSent();
      // The reply on stage went out: a ring of light across the room.
      if (this.hooks.onStage(target, uid)) {
        this.hooks.pulse();
        rumble(0.25);
      }
      const who = this.whoIs(target, uid);
      this.lastSent = { target, id: uid, name: who.name, ts: Date.now() / 1000 };
      // One of its own pictures went out: the gallery marks it, and says to whom. Only one of the gallery's own
      // persona: another persona's IMG_3 is another picture.
      const sender = get(personasRes).data.accounts[target] || "default";
      const mine = (sender === "default" ? "" : sender) === this.picturesOf;
      const pics = mine ? sentPictures(evt.attachments, this.pictures.map((p) => p.name)) : [];
      if (pics.length) {
        const at = Date.now() / 1000;
        const next = { ...this.sentPics };
        for (const p of pics) next[p] = { to: who.name, avatar: who.avatar, at };
        this.sentPics = next;
        play("picture");
        this.pushFeed("picture", `Sent ${who.name} one of its pictures`, { avatar: who.avatar, name: who.name, uid, target });
      } else {
        play("sent");
        this.pushFeed("sent", `Replied to ${who.name}`, { avatar: who.avatar, name: who.name, uid, target });
      }
    }
  };

  onModel = (evt: Record<string, any> | null) => {
    if (!evt || this.hooks.gone()) return;
    const name = shortModel(String(evt.model ?? ""));
    if (evt.ok && evt.job !== "replies") {
      // memory, pictures, voice: the model card mentions it, the list stays for the conversations
      this.helper = { model: String(evt.model ?? ""), job: String(evt.job ?? ""), at: evt.at || Date.now() / 1000 };
    } else if (evt.ok) {
      const one: Active = { provider: evt.provider, model: evt.model, at: evt.at || Date.now() / 1000, ms: evt.ms || 0, ok: true };
      this.active = one;
      // Which model wrote for whom, so the card can show the one working on the
      // conversation on stage instead of whichever answered last anywhere.
      if (evt.uid) this.byConv = { ...this.byConv, [String(evt.uid)]: one };
      this.answered += 1;
      this.pushFeed("model", `${name} wrote a reply in ${((evt.ms || 0) / 1000).toFixed(1)}s`);
    } else {
      play("limit");
      this.pushFeed("limit", evt.limited ? `${name} is rate limited, the next one takes over` : `${name} did not answer`);
    }
  };

  /** The log: to its own list, a line or a burst of them at a time, and friend requests noticed as they are announced. */
  onLog = (e: { level?: string; text?: string; source?: string; ts?: number }) => {
    const text = this.addLog(e);
    if (text) this.friendNews(text);
  };

  /** One line of the log for the list, with the runner's dressing taken off: its words, or nothing if it has none. */
  private addLog(e: { level?: string; text?: string; source?: string; ts?: number }): string {
    if (!e.text || this.hooks.gone() || e.level === "think") return "";
    if (isRule(e.text.trim()) || isMore(e.text)) return "";
    const text = tidy(e.text.split("\n")[0]);
    if (!text) return "";
    const src = sourceInfo(e.source ?? "", get(chatAccounts));
    this.logBuf.push({ id: ++this.logId, at: e.ts ?? Date.now() / 1000, level: kindOf(e.level ?? "info"), text,
                       who: src.name, avatar: src.avatar, icon: src.icon });
    if (!this.logFrame) {
      this.logFrame = requestAnimationFrame(() => {
        this.logFrame = 0;
        this.logs = [...this.logs, ...this.logBuf].slice(-30);
        this.logBuf = [];
      });
    }
    return text;
  }

  private friendNews(text: string) {
    const ask = FRIEND_ASK.exec(text);
    if (ask) {
      play("friend");
      this.pushFeed("friend", `${ask[1]} wants to be friends`, { name: ask[1] });
      this.friendsSoon();
      return;
    }
    const took = FRIEND_TAKEN.exec(text);
    if (took) {
      // Taken from here, the runner logs an id and the list already said so; by its own timer, a name.
      if (!/^\d+$/.test(took[1])) this.pushFeed("friend", `Now friends with ${took[1]}`, { name: took[1] });
      this.friendsSoon();
    }
  }

  // ── When to ask for what ─────────────────────────────────────────────────
  private asked: Record<string, number> = {};
  private due(what: string, every: number): boolean {
    const t = Date.now();
    if (t - (this.asked[what] ?? 0) < every) return false;
    this.asked[what] = t;
    return true;
  }

  /** A page came up, or a minute has gone by with it up: what it shows, if that has got old. */
  ensure(page: Page) {
    if (this.hooks.gone()) return;
    if (page === "accounts") {
      // Worth fresh detail: a ping and a mood from a minute ago read as stale.
      if (Date.now() - this.accountsAt > 20_000) this.loadAccounts();
      if (this.due("activity", 60_000)) this.loadActivity();
      if (this.due("week", 300_000)) this.loadWeek();
    } else if (page === "people") {
      if (this.due("people", 60_000)) this.loadPeople();
      if (this.due("week", 300_000)) this.loadWeek();
    } else if (page === "today") {
      if (this.due("week", 300_000)) this.loadWeek();
    }
  }

  /** Every minute: what is always in view (the scoreboard, the accounts, whether anything needs you). */
  slow(ticks: number) {
    if (this.hooks.gone()) return;
    this.loadDay();
    this.loadAccounts().then(() => this.loadMinecraft());
    if (ticks % 5 === 0) this.loadFriends();
    if (this.due("activity", 60_000)) this.loadActivity();
  }

  destroy() {
    if (this.friendsQueued) clearTimeout(this.friendsQueued);
    if (this.logFrame) cancelAnimationFrame(this.logFrame);
  }
}
