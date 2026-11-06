<script lang="ts">
  /**
   * The practice LIVE (Settings, TikTok, under each of the LIVE subtabs): a pretend TikTok LIVE, to try the co-host
   * without going live.
   *
   * The screen is drawn as TikTok draws a LIVE to the people watching it: the host's capsule with its likes and a
   * follow button, the top gifters and how many are watching, the ranking pill, the chat going up the left in
   * see-through bubbles with each viewer's level, people joining just above the comment box, gift combos, hearts
   * floating up the right, and the comment box with a Rose, gifts and share. The camera is one of the persona's own
   * videos or pictures. A made-up crowd joins, chats, taps hearts, follows, shares and sends gifts at the pace picked;
   * you can be a viewer too (tap the screen for hearts). The persona answers as it would on a real LIVE
   * (app/utils/livecohost.py, through app/web/routes/livedemo_routes.py), with every LIVE setting as it is on the
   * page, saved or not: a line in the chat, said out loud with its voice, and shown over the camera as the OBS page
   * would show it over the stream. Nothing goes to TikTok.
   */
  import { onMount, tick } from "svelte";
  import { fade } from "svelte/transition";
  import { api } from "../api";
  import { ask } from "../ask";
  import { play } from "../uisound";
  import { LIVE_SCREEN, liveScreen, motionEnabled, toast, type LiveScreen, type LiveScreenSource } from "../stores";
  import Icon from "./Icon.svelte";
  import Segmented from "./Segmented.svelte";
  import Toggle from "./Toggle.svelte";
  import {
    GIFTS, LEVELS, compactCount, crowdEvent, driftViewers, giftText, hueOf, levelHue, levelOf, nextDelay, pick,
    type CrowdEvent, type Gift, type Level, type LiveKind,
  } from "../livecrowd";

  let { get, persona = "" }: {
    /** A setting's value as it is on the page, saved or not. */
    get: (key: string) => unknown;
    /** The persona being edited ("" for everyone's settings). */
    persona?: string;
  } = $props();

  /** The LIVE settings (tiktok.live), as app/utils/livecohost.py reads them. */
  type Live = {
    enabled: boolean; chat: boolean; voice: boolean; per_minute: number; reply_delay: number;
    answer_comments: boolean; answer_mode: string; thank_gifts: boolean; gift_min_coins: number;
    welcome_follows: boolean; greet_joins: boolean; thank_shares: boolean; thank_likes: boolean;
    viewer_cooldown: number; max_per_viewer: number; skip_emoji_only: boolean; blocked_words: string[];
    ignore_viewers: string[]; tone: string; topic: string; language: string; max_words: number; use_names: boolean;
    emoji: boolean; read_comment: boolean; fill_silence: boolean; silence_seconds: number; overlay_seconds: number;
    overlay_position: string; overlay_comment: boolean; overlay_size: string; overlay_theme: string;
  };
  /** As config.yaml ships them, until the panel says what is saved. */
  const SHIPPED: Live = {
    enabled: false, chat: true, voice: true, per_minute: 4, reply_delay: 2, answer_comments: true, answer_mode: "all",
    thank_gifts: true, gift_min_coins: 1, welcome_follows: true, greet_joins: false, thank_shares: true,
    thank_likes: false, viewer_cooldown: 30, max_per_viewer: 10, skip_emoji_only: true, blocked_words: [],
    ignore_viewers: [], tone: "persona", topic: "", language: "viewer", max_words: 15, use_names: true, emoji: true,
    read_comment: false, fill_silence: false, silence_seconds: 60, overlay_seconds: 8, overlay_position: "bottom",
    overlay_comment: true, overlay_size: "medium", overlay_theme: "dark",
  };
  type Info = {
    persona: { id: string; name: string };
    host: { name: string; handle: string; avatar: string };
    live: Live;
    voice: boolean;
    account: string;
    /** Why no model can write its lines, "" when one can. */
    not_ready?: string;
  };
  type Line = {
    id: number; kind: LiveKind | "host" | "typing" | "system" | "quiet"; name: string; text: string;
    gift?: Gift; count?: number; mine?: boolean; why?: string; to?: string;
  };
  /** One of its answers over the camera, as the OBS page shows it: to whom, the comment, the answer. */
  type Cap = { text: string; to: string; comment: string };

  let info = $state<Info | null>(null);
  let failed = $state("");

  // ── The LIVE settings, as they are on the page ──────────────────────────────
  const live = $derived.by(() => {
    const base: Record<string, unknown> = { ...SHIPPED, ...(info?.live ?? {}) };
    const out: Record<string, unknown> = {};
    for (const [key, was] of Object.entries(base)) {
      const v = get(`tiktok.live.${key}`);
      const x = v === undefined || v === null ? was : v;
      out[key] = typeof was === "boolean" ? !!x
        : typeof was === "number" ? (Number.isFinite(Number(x)) ? Number(x) : was)
        : Array.isArray(was) ? (Array.isArray(x) ? x.map(String) : String(x ?? "").split(",")).filter((w) => w.trim())
        : String(x ?? "");
    }
    return out as Live;
  });
  const speaks = $derived(live.voice && !!info?.voice);
  const personaArg = $derived(info && info.persona.id !== "default" ? info.persona.id : "");
  /** What the crowd calls the host when they talk to it by name: its first name, else its @handle. */
  const hostCall = $derived(
    ((info?.host.name || "").trim().split(/\s+/)[0] || "").replace(/[^\p{L}\p{N}._]/gu, "") || info?.host.handle || "",
  );

  // ── The host's camera: blurred unless you say otherwise, and what's on it is yours to pick ────────────────────
  // Picked for you (its first video, else one of its pictures, else its face), one of its own pictures or videos, a
  // file of your own (kept with the persona), its face, or nothing. Saved per persona; blur, fit and zoom for all.
  type Pic = { name: string; id?: string; video?: boolean; duration?: number };
  /** What the screen shows: the picture or video, and a still to fill around it when it's shown whole. */
  type Cam = { kind: "video" | "image"; url: string; fill: string; key: string };
  type Own = { present: boolean; kind?: "video" | "image"; still?: boolean; version?: number };
  let pics = $state<Pic[]>([]);
  let own = $state<Own>({ present: false });
  /** The picture "picked for you" settled on, so it doesn't change every time the page looks. */
  let settled = $state<Pic | null>(null);
  let uploading = $state(false);
  let fileInput: HTMLInputElement | null = $state(null);

  const look = $derived<LiveScreen>({ ...LIVE_SCREEN, ...$liveScreen });
  const pid = $derived(info?.persona.id ?? "");
  const source = $derived<LiveScreenSource>(look.sources?.[pid] ?? { kind: "auto" });
  const BLUR: Record<LiveScreen["blur"], number> = { off: 0, light: 6, medium: 14, strong: 26 };
  const BLUR_OPTIONS = [
    { id: "off", label: "Off" }, { id: "light", label: "Light" }, { id: "medium", label: "Medium" },
    { id: "strong", label: "Strong" },
  ];
  const FIT_OPTIONS = [{ id: "fill", label: "Fill" }, { id: "whole", label: "Whole" }];
  const picKey = (p: Pic) => `p:${p.id || p.name}`;
  const ownUrl = (still = false) => (own.present && own.version ? api.liveScreenUrl(pid, own.version, still) : "");

  function shown(p: Pic): Cam {
    const still = api.pictureSmall(p, 360, personaArg);
    return p.video
      ? { kind: "video", url: api.pictureUrl(p.name, p.id, personaArg), fill: still, key: picKey(p) }
      : { kind: "image", url: api.pictureSmall(p, 720, personaArg), fill: still, key: picKey(p) };
  }
  const face = $derived<Cam | null>(
    info?.host.avatar ? { kind: "image", url: info.host.avatar, fill: info.host.avatar, key: "face" } : null,
  );
  /** What the screen shows, and which tile is lit for it: one picked that's gone since is "picked for you" again. */
  const screen = $derived.by((): { cam: Cam | null; tile: string } => {
    const s = source;
    if (s.kind === "none") return { cam: null, tile: "none" };
    if (s.kind === "face") return { cam: face, tile: "face" };
    if (s.kind === "own" && own.present) {
      const url = ownUrl();
      return { cam: { kind: own.kind === "video" ? "video" : "image", url,
                      fill: own.kind === "video" ? (own.still ? ownUrl(true) : "") : url, key: `own:${own.version}` },
               tile: "own" };
    }
    if (s.kind === "pick") {
      const p = pics.find((x) => (s.id ? x.id === s.id : x.name === s.name));
      if (p) return { cam: shown(p), tile: picKey(p) };
    }
    const v = pics.find((p) => p.video);
    return { cam: v ? shown(v) : settled ? shown(settled) : face, tile: "auto" };
  });
  const camera = $derived(screen.cam);

  async function loadScreen() {
    pics = [];
    own = { present: false };
    settled = null;
    if (!info) return;
    const [list, mine] = await Promise.allSettled([api.pictures(personaArg), api.liveScreen(info.persona.id)]);
    if (list.status === "fulfilled") {
      pics = ((list.value as any)?.pictures ?? []) as Pic[];
      const stills = pics.filter((p) => !p.video);
      settled = stills.length ? pick(stills) : null;
    }
    if (mine.status === "fulfilled") own = (mine.value as Own) ?? { present: false };
  }

  function setLook(change: Partial<LiveScreen>) {
    liveScreen.update((v) => ({ ...LIVE_SCREEN, ...v, ...change }));
  }
  function setSource(s: LiveScreenSource) {
    if (pid) setLook({ sources: { ...(look.sources ?? {}), [pid]: s } });
  }
  function choose(s: LiveScreenSource) {
    play("select");
    setSource(s);
  }

  async function upload(file: File | undefined | null) {
    if (!file || !pid || uploading) return;
    uploading = true;
    play("send", { level: 0.6 });
    try {
      own = (await api.uploadLiveScreen(file, pid)) as Own;
      setSource({ kind: "own" });
      play("done");
    } catch (e: any) {
      play("err");
      toast(e?.message || "That file couldn't be used.", "err");
    } finally {
      uploading = false;
      if (fileInput) fileInput.value = "";
    }
  }
  function pickFile() {
    play("open", { level: 0.5 });
    fileInput?.click();
  }
  async function removeOwn() {
    play("tap");
    if (!(await ask("Remove your file from its screen?", { yes: "Remove", danger: true }))) return;
    try {
      own = (await api.clearLiveScreen(pid)) as Own;
      if (source.kind === "own") setSource({ kind: "auto" });
      play("delete");
    } catch (e: any) {
      play("err");
      toast(e?.message || "It couldn't be removed.", "err");
    }
  }

  // A picture or video dropped on the screen becomes it.
  let dropping = $state(false);
  let dragDepth = 0;
  const hasFiles = (e: DragEvent) => !!e.dataTransfer && [...e.dataTransfer.types].includes("Files");
  function dragEnter(e: DragEvent) {
    if (!hasFiles(e)) return;
    e.preventDefault();
    if (dragDepth++ === 0) {
      dropping = true;
      play("hover", { level: 0.5 });
    }
  }
  function dragOver(e: DragEvent) {
    if (hasFiles(e)) e.preventDefault();
  }
  function dragLeave() {
    if (dragDepth > 0 && --dragDepth === 0) dropping = false;
  }
  function dropFile(e: DragEvent) {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth = 0;
    dropping = false;
    play("drop");
    void upload(e.dataTransfer?.files?.[0]);
  }

  async function load() {
    failed = "";
    try {
      info = (await api.liveDemo(persona)) as Info;
      await loadScreen();
    } catch (e: any) {
      failed = e?.message || "Could not load it";
    }
  }
  onMount(() => {
    void load();
    return () => stop(false);
  });
  // Another persona picked to edit: its LIVE, its voice, its camera.
  let loadedFor = "";
  $effect(() => {
    const p = persona;
    if (p === loadedFor) return;
    const first = loadedFor === "" && !info;
    loadedFor = p;
    if (!first) {
      stop(false);
      void load();
    }
  });

  // ── The room ───────────────────────────────────────────────────────────────
  let running = $state(false);
  let ended = $state<{ secs: number; peak: number; likes: number; answered: number } | null>(null);
  let feed = $state<Line[]>([]);
  let viewers = $state(0);
  let peak = 0;
  let likes = $state(0);
  let level = $state<Level>("lively");
  let crowdOn = $state(true);
  let hearts = $state<{ id: number; dx: number; hue: number; big: boolean }[]>([]);
  let banner = $state<{ id: number; name: string; gift: Gift; count: number } | null>(null);
  let entrance = $state<{ id: number; name: string; mine: boolean } | null>(null);
  let caption = $state<(Cap & { id: number; spoken: boolean }) | null>(null);
  let thinking = $state(false);
  let answered = $state(0);
  let skipped = $state(0);
  let saidAt = $state<number[]>([]);
  let now = $state(Date.now());
  let myName = $state("you");
  let draft = $state("");
  let chatBox: HTMLElement | null = $state(null);
  let here = $state<string[]>([]);
  /** Coins each viewer gave this LIVE: the top three are shown top right, as TikTok does. */
  let gifted = $state<Record<string, number>>({});
  let startedAt = 0;
  let seq = 0;
  let recent: string[] = [];
  /** Who has liked the LIVE already: TikTok says so once a viewer, and that is what thanking hearts answers. */
  let liked = new Set<string>();
  /** When the chat last had something said in it, for talking when it goes quiet. */
  let lastTalk = 0;
  /** When you were last answered, for tiktok.live.viewer_cooldown. */
  let myLast = 0;
  let timers: ReturnType<typeof setTimeout>[] = [];
  const LIMIT_MS = 15 * 60 * 1000;

  const thisMinute = $derived(saidAt.filter((t) => now - t < 60000).length);
  const elapsed = $derived(running ? Math.max(0, Math.floor((now - startedAt) / 1000)) : 0);
  const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  const top3 = $derived.by(() => {
    const byCoins = Object.entries(gifted).sort((a, b) => b[1] - a[1]).map(([n]) => n);
    return [...byCoins, ...[...here].reverse().filter((n) => !byCoins.includes(n))].slice(0, 3);
  });

  function later(fn: () => void, ms: number) {
    const t = setTimeout(() => {
      timers = timers.filter((x) => x !== t);
      fn();
    }, ms);
    timers.push(t);
  }

  async function goLive() {
    if (running || !info) return;
    try {
      await api.liveDemoStart();
    } catch {
      /* a fresh start is a nicety */
    }
    feed = [{ id: ++seq, kind: "system", name: "", text: "Welcome to the LIVE! Be kind and have fun. This one is practice: nothing goes to TikTok." }];
    waiting = [];
    hearts = [];
    banner = null;
    entrance = null;
    caption = null;
    answered = skipped = 0;
    saidAt = [];
    likes = 0;
    here = [];
    gifted = {};
    recent = [];
    liked = new Set();
    lastTalk = Date.now();
    myLast = 0;
    ended = null;
    viewers = Math.max(1, Math.round(LEVELS[level].viewers[0] * 0.4));
    peak = viewers;
    startedAt = Date.now();
    running = true;
    play("rise", { level: 0.8 });
    crowdLoop(900);
    tickLoop();
  }

  function stop(sound = true) {
    for (const t of timers) clearTimeout(t);
    timers = [];
    audioQueue.length = 0;
    player?.pause();
    player = null;
    if (!running) return;
    running = false;
    thinking = false;
    ended = { secs: Math.floor((Date.now() - startedAt) / 1000), peak, likes, answered };
    caption = null;
    entrance = null;
    if (sound) play("off", { level: 0.8 });
  }

  /** The clock, who is watching, a line of its own when the chat is quiet, and a LIVE left running too long ended. */
  function tickLoop() {
    if (!running) return;
    now = Date.now();
    viewers = driftViewers(viewers, level);
    peak = Math.max(peak, viewers);
    pump();
    if (live.fill_silence && !thinking && now - lastTalk >= live.silence_seconds * 1000) {
      lastTalk = now;
      void answer({ id: ++seq, kind: "quiet", name: "", text: "" });
    }
    if (now - startedAt > LIMIT_MS) {
      stop();
      return;
    }
    later(tickLoop, 2500);
  }

  /** The crowd: something happens, then the next after a wait; nothing while the page is out of sight. */
  function crowdLoop(wait: number) {
    later(() => {
      if (!running) return;
      if (crowdOn && !document.hidden) void happen(crowdEvent(Math.random, recent, here, hostCall));
      crowdLoop(nextDelay(level));
    }, wait);
  }

  async function scrollChat() {
    await tick();
    chatBox?.scrollTo({ top: chatBox.scrollHeight, behavior: $motionEnabled ? "smooth" : "auto" });
  }

  function say(line: Line, scroll = true) {
    feed = [...feed, line].slice(-60);
    if (scroll) void scrollChat();
  }

  function mark(id: number, why: string) {
    feed = feed.map((l) => (l.id === id ? { ...l, why } : l));
  }

  /** Hearts up the right side: a few for a tap, one for each of the crowd's. */
  function burst(n: number, big = false) {
    likes += n;
    if (!$motionEnabled) return;
    for (let i = 0; i < Math.min(n, 6); i++) {
      const id = ++seq;
      hearts = [...hearts, { id, dx: Math.round((Math.random() - 0.5) * 46), hue: [350, 330, 10, 290, 200][i % 5], big }];
      later(() => (hearts = hearts.filter((h) => h.id !== id)), 2300 + i * 90);
    }
  }

  function showGift(name: string, gift: Gift, count: number) {
    const id = ++seq;
    banner = { id, name, gift, count };
    play(gift.coins >= 100 ? "medal" : "glint", { level: gift.coins >= 100 ? 0.55 : 0.35 });
    later(() => {
      if (banner?.id === id) banner = null;
    }, gift.coins >= 100 ? 4200 : 2800);
  }

  /** Someone coming in, just above the comment box, as TikTok shows it. */
  function enter(name: string, mine: boolean) {
    const id = ++seq;
    entrance = { id, name, mine };
    later(() => {
      if (entrance?.id === id) entrance = null;
    }, 2600);
  }

  /** Something in the chat (the crowd's, or yours): shown, then answered as a real LIVE would. */
  async function happen(e: CrowdEvent, mine = false) {
    if (!running || !info) return;
    // Whoever says or does anything is in the room (and may be among the three shown top right).
    if (!mine && !here.includes(e.name)) here = [...here, e.name].slice(-40);
    if (e.event === "like") {
      burst(mine ? 4 : 1 + Math.floor(Math.random() * 3), mine);
      play(mine ? "pluck" : "tick", { level: mine ? 0.45 : 0.06 });
      if (liked.has(e.name)) return;
      liked.add(e.name);
    }
    if (e.event === "join") {
      viewers += 1;
      enter(e.name, mine);
      play(mine ? "seat" : "tick", { level: mine ? 0.4 : 0.05 });
      const join: Line = { id: ++seq, kind: "join", name: e.name, text: "", mine };
      // Yours is in the chat too, to say why it was not greeted.
      if (mine) say(join);
      await answer(join);
      return;
    }
    if (e.event === "comment") {
      recent = [...recent, e.text].slice(-12);
      lastTalk = Date.now();
    }
    const line: Line = { id: ++seq, kind: e.event, name: e.name, text: e.text, gift: e.gift, count: e.count, mine };
    say(line);
    if (e.event === "gift" && e.gift) {
      gifted = { ...gifted, [e.name]: (gifted[e.name] ?? 0) + e.gift.coins * (e.count ?? 1) };
      showGift(e.name, e.gift, e.count ?? 1);
    } else if (e.event === "follow") play("pluck", { level: mine ? 0.5 : 0.25 });
    else if (e.event === "share") play(mine ? "zip" : "tick", { level: mine ? 0.4 : 0.1 });
    else if (!mine && e.event === "comment") play("tick", { level: 0.1 });
    await answer(line);
  }

  // Your own lines, waiting for the pace to allow them: on a real LIVE a line that comes while it is answering, or
  // once it has said its so many this minute, is let go; here yours wait their turn, the crowd's still go.
  let waiting: Line[] = [];
  const minuteFull = () => saidAt.filter((t) => Date.now() - t < 60000).length >= live.per_minute;
  /** You were answered a moment ago: yours wait out tiktok.live.viewer_cooldown; the crowd's are not held up by it. */
  const coolingDown = () => live.viewer_cooldown > 0 && Date.now() - myLast < live.viewer_cooldown * 1000;

  function wait(line: Line) {
    if (!waiting.some((l) => l.id === line.id)) waiting = [...waiting, line];
    mark(line.id, "Waiting its turn");
  }

  /** The next of your lines, as soon as it may be said. */
  function pump() {
    if (!running || thinking || !waiting.length || minuteFull() || coolingDown()) return;
    const next = waiting[0];
    waiting = waiting.slice(1);
    mark(next.id, "");
    void answer(next);
  }

  /** The persona's line to it, when the settings answer it and it is not answering someone else already. */
  async function answer(line: Line) {
    if (!info || line.kind === "host" || line.kind === "typing" || line.kind === "system") return;
    // Yours first: the crowd's are let go while one of yours is waiting and may be answered now.
    if (!line.mine && waiting.length && !coolingDown()) {
      if (line.kind !== "quiet") skipped++;
      return;
    }
    if (thinking || minuteFull() || (line.mine && coolingDown())) {
      if (line.mine) wait(line);
      else if (line.kind !== "quiet") skipped++;
      return;
    }
    thinking = true;
    const typingId = ++seq;
    const typingShown = setTimeout(() => {
      if (running && live.chat) say({ id: typingId, kind: "typing", name: info!.host.name, text: "" });
    }, 450);
    let r: any = null;
    try {
      r = await api.liveDemoAnswer({ event: line.kind, name: line.name, text: line.text, persona: info.persona.id,
                                     live: $state.snapshot(live) });
    } catch (err: any) {
      r = { answered: false, why: err?.message || "The AI did not answer" };
    } finally {
      clearTimeout(typingShown);
      feed = feed.filter((l) => l.id !== typingId);
      thinking = false;
      later(pump, 400);
    }
    if (!running) return;
    if (!r?.answered && line.mine && /Still answering|this minute|a moment ago/.test(r?.why || "")) {
      wait(line);
      return;
    }
    if (!r?.answered) {
      if (line.kind !== "quiet") skipped++;
      // Said where it helps: on your own lines, and whenever the AI itself did not answer.
      if (line.mine || /AI/.test(r?.why || "")) mark(line.id, r?.why || "Not answered");
      return;
    }
    answered++;
    if (line.mine) {
      mark(line.id, "");
      myLast = Date.now();
    }
    lastTalk = Date.now();
    saidAt = [...saidAt.filter((t) => Date.now() - t < 60000), Date.now()];
    const cap: Cap = { text: r.text, to: line.kind === "quiet" ? "" : line.name, comment: line.kind === "comment" ? line.text : "" };
    if (live.chat) say({ id: ++seq, kind: "host", name: info.host.name, text: r.text, to: cap.to });
    play("receive", { level: 0.5 });
    if (speaks) void speak(r.id, cap);
    else showCaption(cap, false);
  }

  // ── Out loud, and over the camera as the OBS page shows it ───────────────────
  const audioQueue: { cap: Cap; files: string[] }[] = [];
  let player: HTMLAudioElement | null = null;

  async function speak(id: string, cap: Cap) {
    try {
      const r: any = await api.liveDemoVoice(id);
      if (!running) return;
      if (r?.audio?.length) {
        audioQueue.push({ cap, files: r.audio });
        if (!player) playNext();
        return;
      }
    } catch {
      /* the caption alone, below */
    }
    if (running) showCaption(cap, false);
  }

  /** The next spoken line: up while it is said, and for at least as long as the OBS page keeps one up. */
  function playNext() {
    const next = audioQueue.shift();
    if (!next || !running) {
      player = null;
      caption = null;
      return;
    }
    caption = { ...next.cap, id: ++seq, spoken: true };
    const until = Date.now() + live.overlay_seconds * 1000;
    const files = [...next.files];
    const one = () => {
      const f = files.shift();
      if (!f) {
        later(playNext, Math.max(250, until - Date.now()));
        return;
      }
      player = new Audio(api.liveDemoAudio(f));
      player.onended = one;
      player.onerror = one;
      player.play().catch(one);
    };
    one();
  }

  function showCaption(cap: Cap, spoken: boolean) {
    // A line being said keeps the screen; this one is in the chat.
    if (player) return;
    const id = ++seq;
    caption = { ...cap, id, spoken };
    later(() => {
      if (caption?.id === id) caption = null;
    }, live.overlay_seconds * 1000);
  }

  // ── You, as a viewer ─────────────────────────────────────────────────────────
  const me = $derived(myName.trim().replace(/\s+/g, "_").slice(0, 24) || "you");
  function send() {
    const text = draft.trim();
    if (!text || !running) return;
    draft = "";
    play("send");
    void happen({ event: "comment", name: me, text }, true);
  }
  function tapHeart() {
    if (running) void happen({ event: "like", name: me, text: "" }, true);
  }
  function giveGift() {
    if (!running) return;
    const gift = pick(GIFTS.slice(0, 6));
    const count = gift.coins <= 5 ? 1 + Math.floor(Math.random() * 5) : 1;
    void happen({ event: "gift", name: me, text: giftText(gift, count), gift, count }, true);
  }
  function giveRose() {
    if (running) void happen({ event: "gift", name: me, text: giftText(GIFTS[0], 1), gift: GIFTS[0], count: 1 }, true);
  }
  const asYou = (event: LiveKind) => () => {
    if (running) void happen({ event, name: me, text: "" }, true);
  };

  const initial = (n: string) => ([...(n || "?")][0] ?? "?").toUpperCase();
  const LEVEL_OPTIONS = [
    { id: "quiet", label: "Quiet" },
    { id: "lively", label: "Lively" },
    { id: "busy", label: "Busy" },
  ];
  const doing: Record<string, string> = {
    join: "joined", follow: "followed the host", share: "shared the LIVE", like: "liked the LIVE",
  };

  // ── What it goes by: the settings above, as they are on the page now ─────────
  const secs = (n: number) => (n >= 60 && n % 60 === 0 ? `${n / 60} min` : `${n} s`);
  const listed = (words: string[]) => words.filter((w) => w.trim()).length;
  const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  const MODES: Record<string, string> = { all: "All comments", questions: "Questions", named: "When named" };
  const TONES: Record<string, string> = { persona: "Its usual self", hype: "Hype", chill: "Chill", funny: "Funny", sweet: "Sweet" };
  const answersChips = $derived([
    { on: live.chat, text: "In the chat" },
    { on: speaks, text: "Out loud" },
    { on: live.answer_comments, text: MODES[live.answer_mode] ?? "All comments" },
    { on: live.thank_gifts, text: live.gift_min_coins > 1 ? `Gifts from ${live.gift_min_coins} coins` : "Thanks gifts" },
    { on: live.welcome_follows, text: "Welcomes follows" },
    { on: live.greet_joins, text: "Greets joins" },
    { on: live.thank_shares, text: "Thanks shares" },
    { on: live.thank_likes, text: "Thanks hearts" },
    { on: live.skip_emoji_only, text: "Skips emoji only" },
    { on: true, text: live.viewer_cooldown ? `Same viewer after ${secs(live.viewer_cooldown)}` : "Same viewer any time" },
    { on: true, text: `${live.max_per_viewer} per viewer` },
    ...(listed(live.blocked_words) ? [{ on: true, text: count(listed(live.blocked_words), "word", "words") + " ignored" }] : []),
    ...(listed(live.ignore_viewers) ? [{ on: true, text: count(listed(live.ignore_viewers), "viewer", "viewers") + " ignored" }] : []),
  ]);
  const styleChips = $derived([
    { on: true, text: TONES[live.tone] ?? "Its usual self" },
    ...(live.topic.trim() ? [{ on: true, text: `About ${live.topic.trim().slice(0, 28)}` }] : []),
    { on: true, text: live.language === "persona" ? "Its own language" : "Their language" },
    { on: true, text: `Up to ${live.max_words} words` },
    { on: live.use_names, text: "Says names" },
    { on: live.emoji, text: "Emoji" },
    { on: live.read_comment, text: "Reads comments out" },
    { on: live.fill_silence, text: live.fill_silence ? `Talks after ${secs(live.silence_seconds)} quiet` : "Talks when quiet" },
    { on: true, text: live.reply_delay ? `Waits ${secs(live.reply_delay)}` : "Answers at once" },
  ]);
</script>

<section class="ld">
  <header class="ld-head">
    <div class="min-w-0">
      <h3 class="ld-title"><Icon name="tiktok" size={15} />Try a LIVE</h3>
      <p class="ld-sub">A practice LIVE with a pretend crowd. It answers with the settings above, saved or not. Nothing goes to TikTok.</p>
    </div>
  </header>

  {#if failed}
    <p class="ld-note is-bad">{failed}</p>
  {:else}
  <div class="ld-grid">
    <!-- ── The screen, as TikTok shows a LIVE ──────────────────────────── -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="ld-phone" class:is-live={running} class:is-drop={dropping} style="--blur: {BLUR[look.blur] ?? 14}px"
         ondragenter={dragEnter} ondragover={dragOver} ondragleave={dragLeave} ondrop={dropFile}>
      <div class="ld-cam" class:is-whole={look.fit === "whole"} class:is-still={!look.zoom} aria-hidden="true">
        {#key camera?.key ?? screen.tile}
          <div class="ld-cam-in" in:fade={{ duration: $motionEnabled ? 420 : 0 }} out:fade={{ duration: $motionEnabled ? 420 : 0 }}>
            <div class="ld-pan">
              {#if camera}
                {#if look.fit === "whole" && camera.fill}
                  <!-- The whole of it, on a blurred copy filling the rest, as TikTok shows a wide one. -->
                  <img class="ld-fill" src={camera.fill} alt="" />
                {/if}
                {#if camera.kind === "video"}
                  <video class="ld-media" src={camera.url} muted loop autoplay playsinline></video>
                {:else}
                  <img class="ld-media" src={camera.url} alt="" />
                {/if}
              {:else if screen.tile === "none"}
                <span class="ld-cam-empty"></span>
              {:else}
                <span class="ld-cam-empty">{initial(info?.host.name ?? "")}</span>
              {/if}
            </div>
          </div>
        {/key}
      </div>
      <div class="ld-shade" aria-hidden="true"></div>
      {#if dropping || uploading}
        <div class="ld-drop" transition:fade={{ duration: $motionEnabled ? 160 : 0 }}>
          <Icon name="upload" size={22} />
          <b>{uploading ? "Putting it on the screen" : "Drop to use it as the screen"}</b>
        </div>
      {/if}

      {#if running}
        <!-- Tapping the screen sends hearts, as on TikTok. -->
        <button type="button" class="ld-tap" onclick={tapHeart} aria-label="Tap hearts" data-sound="self"></button>
      {/if}

      <!-- Who is live, who gave the most, how many are watching. -->
      <div class="ld-top">
        <span class="ld-host">
          {#if info?.host.avatar}<img src={info.host.avatar} alt="" />{:else}<i>{initial(info?.host.name ?? "")}</i>{/if}
          <span class="ld-host-t">
            <b>{info?.host.name ?? "…"}</b>
            <small>{compactCount(likes)} likes</small>
          </span>
          {#if running}
            <button type="button" class="ld-follow" onclick={asYou("follow")} title="Follow" aria-label="Follow the host"
                    data-sound="self"><Icon name="plus" size={13} /></button>
          {/if}
        </span>
        {#if running}
          <span class="ld-right">
            <span class="ld-tops">
              {#each top3 as n, i (n)}
                <span class="ld-top-av is-{i + 1}" style="--h: {hueOf(n)}" title={n}>{initial(n)}<i>{i + 1}</i></span>
              {/each}
            </span>
            <span class="ld-viewers" title="Watching">{compactCount(viewers)}</span>
            <button type="button" class="ld-close" onclick={() => stop()} title="End the LIVE" aria-label="End the LIVE"
                    data-sound="self"><Icon name="close" size={14} /></button>
          </span>
        {/if}
      </div>

      {#if running}
        <div class="ld-pills" aria-hidden="true">
          <span class="ld-pill"><i></i>Hourly ranking</span>
        </div>

        <!-- The chat, up the left in see-through bubbles, older lines fading out at the top. -->
        <div class="ld-chat" bind:this={chatBox} aria-label="LIVE chat">
          {#each feed as l (l.id)}
            {#if l.kind === "system"}
              <div class="ld-line is-system">{l.text}</div>
            {:else}
              <div class="ld-line is-{l.kind}" class:is-mine={l.mine}>
                {#if l.kind === "host" || l.kind === "typing"}
                  <span class="ld-av is-host">
                    {#if info?.host.avatar}<img src={info.host.avatar} alt="" />{:else}{initial(l.name)}{/if}
                  </span>
                {:else}
                  <span class="ld-av" style="--h: {hueOf(l.name)}">{initial(l.name)}</span>
                {/if}
                <span class="ld-say">
                  <span class="ld-who">
                    {#if l.kind === "host" || l.kind === "typing"}
                      <b>{l.name}</b><em>Host</em>
                    {:else}
                      <i class="ld-lv" style="--lv: {levelHue(levelOf(l.name))}">{levelOf(l.name)}</i><b>{l.name}</b>
                    {/if}
                  </span>
                  {#if l.kind === "typing"}
                    <span class="ld-dots"><i></i><i></i><i></i></span>
                  {:else if l.kind === "gift"}
                    <span class="ld-text">sent {l.gift?.name} <span class="ld-gift-e">{l.gift?.emoji}</span>{#if (l.count ?? 1) > 1}<span class="ld-times">x{l.count}</span>{/if}</span>
                  {:else if doing[l.kind]}
                    <span class="ld-text ld-did">{doing[l.kind]}</span>
                  {:else}
                    <span class="ld-text">{l.text}</span>
                  {/if}
                  {#if l.why}<small class="ld-why">{l.why}</small>{/if}
                </span>
              </div>
            {/if}
          {/each}
        </div>

        <!-- Hearts, floating up the right. -->
        <div class="ld-hearts" aria-hidden="true">
          {#each hearts as h (h.id)}
            <span class="ld-heart" class:is-big={h.big} style="--dx: {h.dx}px; --hue: {h.hue}">♥</span>
          {/each}
        </div>

        <!-- A gift combo, sliding in over the top of the chat. -->
        {#key banner?.id}
          {#if banner}
            <div class="ld-banner" class:is-big={banner.gift.coins >= 100}>
              <span class="ld-av" style="--h: {hueOf(banner.name)}">{initial(banner.name)}</span>
              <span class="ld-banner-t">
                <b>{banner.name}</b>
                <small>sent {banner.gift.name}</small>
              </span>
              <span class="ld-banner-e">{banner.gift.emoji}</span>
              {#if banner.count > 1}<span class="ld-banner-x">x{banner.count}</span>{/if}
            </div>
          {/if}
        {/key}

        <!-- Someone coming in. -->
        {#key entrance?.id}
          {#if entrance}
            <div class="ld-enter" class:is-mine={entrance.mine}>
              <i class="ld-lv" style="--lv: {levelHue(levelOf(entrance.name))}">{levelOf(entrance.name)}</i>
              <b>{entrance.name}</b><span>joined</span>
            </div>
          {/if}
        {/key}

        {#if caption}
          <!-- Its answer over the camera, as the OBS page shows it over the stream (Settings, OBS page). -->
          <div class="ld-capwrap" data-pos={live.overlay_position}>
            {#key caption.id}
              <div class="ld-caption" class:is-spoken={caption.spoken} data-size={live.overlay_size} data-look={live.overlay_theme}>
                {#if live.overlay_comment && caption.comment && caption.to}
                  <span class="ld-cap-q"><b>{caption.to}</b> {caption.comment}</span>
                {:else if caption.to}
                  <span class="ld-cap-to">To {caption.to}</span>
                {/if}
                <span class="ld-cap-text">{#if live.overlay_theme === "tiktok"}<i class="ld-cap-host">Host</i>{/if}{caption.text}</span>
              </div>
            {/key}
          </div>
        {/if}

        <!-- You, as a viewer: the comment box, a Rose, gifts, share. -->
        <form class="ld-bar" onsubmit={(e) => { e.preventDefault(); send(); }}>
          <input bind:value={draft} maxlength="150" placeholder="Add comment..." aria-label="Say something in the LIVE as {me}" />
          <button type="button" class="ld-round" onclick={giveRose} title="Send a Rose" aria-label="Send a Rose"
                  data-sound="self">🌹</button>
          <button type="button" class="ld-round is-gift" onclick={giveGift} title="Send a gift" aria-label="Send a gift"
                  data-sound="self">🎁</button>
          <button type="button" class="ld-round" onclick={asYou("share")} title="Share" aria-label="Share the LIVE"
                  data-sound="self">
            <svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true">
              <path d="M13.5 4.5v4.1C7.6 9.3 4.4 13 3.6 19.2c2.2-3.2 5.3-4.7 9.9-4.8v4.1l7.4-7z" fill="currentColor" />
            </svg>
          </button>
        </form>
      {:else}
        <!-- Before it starts, and after it ends. -->
        <div class="ld-idle">
          {#if ended}
            <b>LIVE ended</b>
            <span class="ld-idle-facts">
              <span><em>{clock(ended.secs)}</em>long</span>
              <span><em>{compactCount(ended.peak)}</em>watching at most</span>
              <span><em>{compactCount(ended.likes)}</em>likes</span>
              <span><em>{ended.answered}</em>answered</span>
            </span>
          {:else}
            <b>{info ? `${info.host.name} is ready` : "Getting ready"}</b>
            <small>Speaking as {info?.persona.name ?? "…"}</small>
          {/if}
          <button type="button" class="ld-go" onclick={goLive} disabled={!info} data-sound="self">
            {ended ? "Go LIVE again" : "Go LIVE"}
          </button>
        </div>
      {/if}
    </div>

    <!-- ── The controls ───────────────────────────────────────────────── -->
    <div class="ld-side">
      <div class="ld-card">
        <div class="ld-row">
          <span class="ld-k">The LIVE</span>
          {#if running}
            <button type="button" class="ld-end" onclick={() => stop()} data-sound="self">
              <Icon name="stop" size={12} />End · {clock(elapsed)}
            </button>
          {:else}
            <button type="button" class="ld-start" onclick={goLive} disabled={!info} data-sound="self">
              <i></i>Go LIVE
            </button>
          {/if}
        </div>
        <div class="ld-row">
          <span class="ld-k">Crowd</span>
          <span class="ld-seg"><Segmented label="How busy the crowd is" bind:value={level} options={LEVEL_OPTIONS} /></span>
        </div>
        <div class="ld-row">
          <span class="ld-k">They chat on their own</span>
          <Toggle bind:checked={crowdOn} size="sm" name="The crowd chats on its own" />
        </div>
      </div>

      <div class="ld-card">
        <div class="ld-row">
          <span class="ld-k">The screen</span>
          {#if own.present}
            <span class="ld-links">
              <button type="button" onclick={pickFile} disabled={uploading} data-sound="self">Change your file</button>
              <button type="button" onclick={removeOwn} disabled={uploading} data-sound="self">Remove</button>
            </span>
          {/if}
        </div>
        <div class="ld-shots" class:is-blurred={look.blur !== "off"} role="radiogroup" aria-label="What the screen shows"
             data-sound="self">
          <button type="button" role="radio" aria-checked={screen.tile === "auto"} class="ld-shot is-word"
                  class:is-on={screen.tile === "auto"} onclick={() => choose({ kind: "auto" })}
                  title="Picked for you: its first video, else one of its pictures">
            <Icon name="sparkle" size={15} /><span>Auto</span>
          </button>
          {#if own.present}
            <button type="button" role="radio" aria-checked={screen.tile === "own"} class="ld-shot"
                    class:is-on={screen.tile === "own"} onclick={() => choose({ kind: "own" })} title="Your file">
              {#if own.kind === "image" || own.still}<img src={ownUrl(own.kind === "video")} alt="" />{/if}
              {#if own.kind === "video"}<i class="ld-shot-mark"><Icon name="play" size={9} /></i>{/if}
              <em>Yours</em>
            </button>
          {:else}
            <button type="button" class="ld-shot is-word is-add" onclick={pickFile} disabled={uploading}
                    title="A picture or video of your own, just for this screen">
              <Icon name="upload" size={15} /><span>{uploading ? "Adding" : "Add"}</span>
            </button>
          {/if}
          <button type="button" role="radio" aria-checked={screen.tile === "face"} class="ld-shot"
                  class:is-word={!face} class:is-on={screen.tile === "face"} onclick={() => choose({ kind: "face" })}
                  title="Its face">
            {#if face}<img src={face.url} alt="" /><em>Face</em>{:else}<Icon name="smile" size={15} /><span>Face</span>{/if}
          </button>
          <button type="button" role="radio" aria-checked={screen.tile === "none"} class="ld-shot is-word is-none"
                  class:is-on={screen.tile === "none"} onclick={() => choose({ kind: "none" })} title="Nothing, just dark">
            <Icon name="eyeOff" size={15} /><span>None</span>
          </button>
          {#each pics as p (picKey(p))}
            <button type="button" role="radio" aria-checked={screen.tile === picKey(p)} class="ld-shot"
                    class:is-on={screen.tile === picKey(p)} onclick={() => choose({ kind: "pick", id: p.id, name: p.name })}
                    title={p.video ? "One of its videos" : "One of its pictures"}>
              <img src={api.pictureSmall(p, 160, personaArg)} alt="" loading="lazy" />
              {#if p.video}<i class="ld-shot-mark"><Icon name="play" size={9} />{#if p.duration}{clock(Math.round(p.duration))}{/if}</i>{/if}
            </button>
          {/each}
        </div>
        <input class="ld-file" type="file" accept="image/*,video/*,.heic,.heif,.mov,.mkv" bind:this={fileInput}
               onchange={(e) => upload(e.currentTarget.files?.[0])} tabindex="-1" aria-hidden="true" />
        <p class="ld-hint">Or drop a picture or video on the screen. It's only shown here, never sent.</p>
        <div class="ld-row">
          <span class="ld-k">Blur</span>
          <span class="ld-seg is-4"><Segmented label="How blurred the screen is" options={BLUR_OPTIONS}
            bind:value={() => look.blur, (v) => setLook({ blur: v as LiveScreen["blur"] })} /></span>
        </div>
        <div class="ld-row">
          <span class="ld-k">Fit</span>
          <span class="ld-seg is-2"><Segmented label="How the screen fits" options={FIT_OPTIONS}
            bind:value={() => look.fit, (v) => setLook({ fit: v as LiveScreen["fit"] })} /></span>
        </div>
        <div class="ld-row">
          <span class="ld-k">Slow zoom</span>
          <Toggle bind:checked={() => look.zoom, (v) => setLook({ zoom: v })} size="sm" name="The screen slowly zooms" />
        </div>
      </div>

      <div class="ld-card">
        <div class="ld-row">
          <span class="ld-k">You, as</span>
          <input class="ld-name" bind:value={myName} maxlength="24" aria-label="Your name as a viewer" />
        </div>
        <div class="ld-acts">
          <button type="button" onclick={asYou("join")} disabled={!running} data-sound="self">Join</button>
          <button type="button" onclick={asYou("follow")} disabled={!running} data-sound="self">Follow</button>
          <button type="button" onclick={giveGift} disabled={!running} data-sound="self">Gift</button>
          <button type="button" onclick={asYou("share")} disabled={!running} data-sound="self">Share</button>
          <button type="button" onclick={tapHeart} disabled={!running} data-sound="self">Hearts</button>
        </div>
      </div>

      <div class="ld-card">
        <div class="ld-stats">
          <span><b>{answered}</b>answered</span>
          <span><b>{skipped}</b>let go</span>
          <span class:is-full={thisMinute >= live.per_minute}><b>{thisMinute}/{live.per_minute}</b>this minute</span>
        </div>
        <span class="ld-chiphead">What it answers</span>
        <div class="ld-chips">
          {#each answersChips as c, i (i)}<span class:is-on={c.on}>{c.text}</span>{/each}
        </div>
        <span class="ld-chiphead">How it sounds</span>
        <div class="ld-chips">
          {#each styleChips as c, i (i)}<span class:is-on={c.on}>{c.text}</span>{/each}
        </div>
        {#if info?.not_ready}
          <p class="ld-note is-bad">{info.not_ready}</p>
        {/if}
        {#if live.voice && info && !info.voice && !info.not_ready}
          <p class="ld-note">No voice is set up to speak with, so it only shows its answers.</p>
        {/if}
        {#if !live.chat && !live.voice}
          <p class="ld-note">In the chat and out loud are both off: on a real LIVE it has nowhere to answer.</p>
        {/if}
        {#if info && !live.enabled}
          <p class="ld-note">On real LIVEs it stays quiet until Co-host its LIVE is on.</p>
        {/if}
      </div>
    </div>
  </div>
  {/if}
</section>

<style>
  .ld { margin-top: 28px; container-type: inline-size; }
  .ld-head { margin-bottom: 12px; }
  .ld-title { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 650; color: var(--color-ink); }
  .ld-sub { margin-top: 3px; font-size: 12px; color: var(--color-faint); }
  .ld-grid { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 18px; align-items: start; }
  @container (max-width: 640px) {
    .ld-grid { grid-template-columns: minmax(0, 1fr); justify-items: center; }
    .ld-side { width: 100%; }
  }

  /* ── The screen ── */
  .ld-phone {
    position: relative;
    width: 100%;
    max-width: 300px;
    aspect-ratio: 9 / 16;
    overflow: hidden;
    border-radius: 26px;
    background: #060608;
    box-shadow: 0 0 0 1px rgb(255 255 255 / 0.08), 0 0 0 6px rgb(255 255 255 / 0.025),
                0 28px 60px -28px rgb(0 0 0 / 0.85), 0 0 46px -18px rgb(254 44 85 / 0.25);
    isolation: isolate;
    color: #fff;
    font-family: "TikTok Sans", "Proxima Nova", system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  .ld-phone.is-live { box-shadow: 0 0 0 1px rgb(254 44 85 / 0.28), 0 0 0 6px rgb(255 255 255 / 0.025),
                                  0 28px 60px -28px rgb(0 0 0 / 0.85), 0 0 60px -14px rgb(254 44 85 / 0.45); }
  /* The camera: past the screen's edges by as much as it's blurred, so a blur never leaves a pale rim. */
  .ld-cam { position: absolute; inset: calc(var(--blur, 0px) * -1.6); z-index: -2; }
  .ld-cam-in, .ld-pan { position: absolute; inset: 0; }
  .ld-pan { animation: ld-pan 26s ease-in-out infinite alternate; }
  .ld-cam.is-still .ld-pan { animation: none; }
  @keyframes ld-pan { from { transform: scale(1.06) translate(0, 0); } to { transform: scale(1.16) translate(-2%, -1.5%); } }
  .ld-media {
    position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; filter: blur(var(--blur, 0px));
  }
  .ld-cam.is-whole .ld-media { object-fit: contain; }
  /* Shown whole: a darker, softer copy of itself fills the rest. */
  .ld-fill {
    position: absolute; inset: -40px; width: calc(100% + 80px); height: calc(100% + 80px); object-fit: cover;
    filter: blur(calc(var(--blur, 0px) + 22px)) brightness(0.62) saturate(1.15);
  }
  .ld-phone.is-drop {
    box-shadow: 0 0 0 2px rgb(254 44 85 / 0.75), 0 0 0 6px rgb(255 255 255 / 0.025),
                0 28px 60px -28px rgb(0 0 0 / 0.85), 0 0 60px -10px rgb(254 44 85 / 0.55);
  }
  .ld-drop {
    position: absolute; inset: 0; z-index: 3; display: flex; flex-direction: column; align-items: center;
    justify-content: center; gap: 9px; padding: 0 28px; text-align: center; pointer-events: none;
    font-size: 13px; color: #fff; background: rgb(6 6 8 / 0.5); -webkit-backdrop-filter: blur(6px); backdrop-filter: blur(6px);
  }
  .ld-drop :global(svg) { color: #fe2c55; filter: drop-shadow(0 0 10px rgb(254 44 85 / 0.6)); }
  .ld-cam-empty {
    display: grid; width: 100%; height: 100%; place-items: center;
    font-size: 96px; font-weight: 700; color: rgb(255 255 255 / 0.18);
    background: radial-gradient(120% 80% at 30% 20%, rgb(254 44 85 / 0.45), transparent 60%),
                radial-gradient(100% 70% at 80% 90%, rgb(37 244 238 / 0.35), transparent 60%), #0b0b10;
  }
  .ld-shade {
    position: absolute; inset: 0; z-index: -1; pointer-events: none;
    background: linear-gradient(to bottom, rgb(0 0 0 / 0.45), transparent 20%, transparent 50%, rgb(0 0 0 / 0.6));
  }
  .ld-tap { position: absolute; inset: 0; z-index: 0; cursor: pointer; background: transparent; }
  .ld-top, .ld-pills, .ld-chat, .ld-banner, .ld-enter, .ld-capwrap, .ld-bar, .ld-idle { z-index: 1; }
  .ld-hearts { z-index: 1; }

  /* Who is live, top left; the top gifters, how many watch and the way out, top right. */
  .ld-top { position: absolute; top: 10px; left: 8px; right: 8px; display: flex; align-items: center; gap: 6px; }
  .ld-host {
    display: flex; min-width: 0; flex: 0 1 auto; align-items: center; gap: 5px; height: 34px;
    padding: 2px 3px 2px 2px; border-radius: 999px; background: rgb(0 0 0 / 0.3);
    -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
  }
  .ld-host img, .ld-host > i {
    display: grid; width: 30px; height: 30px; flex-shrink: 0; place-items: center; border-radius: 999px; object-fit: cover;
    font-size: 12px; font-style: normal; font-weight: 700; background: #fe2c55;
  }
  .ld-host-t { min-width: 0; flex: 1; padding-right: 2px; }
  .ld-host-t b {
    display: block; overflow: hidden; font-size: 11.5px; font-weight: 700; line-height: 1.15; text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ld-host-t small { display: block; font-size: 9.5px; line-height: 1.25; color: rgb(255 255 255 / 0.75); white-space: nowrap; }
  .ld-follow {
    display: grid; width: 28px; height: 24px; flex-shrink: 0; place-items: center; border-radius: 999px; color: #fff;
    background: #fe2c55; box-shadow: 0 4px 12px -4px rgb(254 44 85 / 0.85);
    transition: transform 0.2s var(--spring), filter 0.15s ease;
  }
  .ld-follow:hover { filter: brightness(1.08); }
  .ld-follow:active { transform: scale(0.9); }
  .ld-right { display: flex; flex-shrink: 0; align-items: center; gap: 4px; margin-left: auto; }
  .ld-tops { display: flex; gap: 3px; }
  .ld-top-av {
    position: relative; display: grid; width: 22px; height: 22px; place-items: center; border-radius: 999px;
    font-size: 9px; font-weight: 700;
    background: radial-gradient(circle at 30% 25%, hsl(var(--h) 70% 62%), hsl(var(--h) 55% 36%));
    box-shadow: 0 0 0 1.5px var(--ring), 0 0 10px -3px var(--ring);
  }
  .ld-top-av.is-1 { --ring: #ffcf4a; }
  .ld-top-av.is-2 { --ring: #d9e2ec; }
  .ld-top-av.is-3 { --ring: #f0a46e; }
  .ld-top-av i {
    position: absolute; bottom: -5px; left: 50%; min-width: 11px; height: 9px; padding: 0 2px; border-radius: 5px;
    transform: translateX(-50%); font-size: 7px; font-style: normal; font-weight: 800; line-height: 9px;
    text-align: center; color: #1b1b1f; background: var(--ring);
  }
  .ld-viewers {
    display: inline-flex; height: 24px; align-items: center; padding: 0 7px; border-radius: 999px;
    font-size: 10.5px; font-weight: 700; font-variant-numeric: tabular-nums;
    background: rgb(0 0 0 / 0.3); -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
  }
  .ld-close {
    display: grid; width: 22px; height: 22px; place-items: center; border-radius: 999px; color: rgb(255 255 255 / 0.95);
    transition: background-color 0.15s ease, transform 0.2s var(--spring);
  }
  .ld-close:hover { background: rgb(255 255 255 / 0.14); }
  .ld-close:active { transform: scale(0.9); }

  .ld-pills { position: absolute; top: 52px; left: 8px; display: flex; gap: 5px; }
  .ld-pill {
    display: inline-flex; height: 20px; align-items: center; gap: 5px; padding: 0 9px 0 7px; border-radius: 999px;
    font-size: 10px; font-weight: 600; color: rgb(255 255 255 / 0.94);
    background: rgb(0 0 0 / 0.26); -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
  }
  .ld-pill i {
    width: 7px; height: 7px; border-radius: 2px; transform: rotate(45deg);
    background: linear-gradient(135deg, #ffe08a, #ffad33); box-shadow: 0 0 6px rgb(255 190 60 / 0.7);
  }

  /* The chat: see-through bubbles, newest at the bottom, the oldest fading out at the top. */
  .ld-chat {
    position: absolute; left: 8px; right: 62px; bottom: 84px; height: 30%;
    display: flex; flex-direction: column; align-items: flex-start; gap: 4px; overflow-y: auto; scrollbar-width: none;
    mask-image: linear-gradient(to bottom, transparent, #000 24%);
    -webkit-mask-image: linear-gradient(to bottom, transparent, #000 24%);
    padding-top: 32%;
  }
  .ld-chat::-webkit-scrollbar { display: none; }
  .ld-line {
    display: flex; max-width: 100%; flex-shrink: 0; align-items: flex-start; gap: 6px; padding: 4px 10px 5px 4px;
    border-radius: 14px; font-size: 12px; line-height: 1.3; background: rgb(0 0 0 / 0.2);
    animation: ld-in 0.32s var(--swift) both;
  }
  @keyframes ld-in { from { opacity: 0; transform: translateY(6px); } }
  .ld-av {
    display: grid; width: 24px; height: 24px; flex-shrink: 0; place-items: center; overflow: hidden; border-radius: 999px;
    font-size: 10px; font-weight: 700; color: #fff;
    background: radial-gradient(circle at 30% 25%, hsl(var(--h, 330) 70% 62%), hsl(var(--h, 330) 55% 36%));
  }
  .ld-av img { width: 100%; height: 100%; object-fit: cover; }
  .ld-av.is-host { background: #fe2c55; box-shadow: 0 0 0 1.5px #fe2c55; }
  .ld-say { display: flex; min-width: 0; flex-direction: column; }
  .ld-who {
    display: flex; min-width: 0; align-items: center; gap: 4px; font-size: 11px; font-weight: 600; line-height: 1.35;
    color: rgb(255 255 255 / 0.66);
  }
  .ld-who b { overflow: hidden; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
  .ld-who em {
    flex-shrink: 0; padding: 0 5px; border-radius: 4px; font-size: 9px; font-style: normal; font-weight: 800; color: #fff;
    background: #fe2c55;
  }
  .ld-lv {
    display: inline-flex; height: 13px; flex-shrink: 0; align-items: center; gap: 2px; padding: 0 5px 0 4px; border-radius: 7px;
    font-size: 8.5px; font-style: normal; font-weight: 800; line-height: 1; color: #fff;
    background: linear-gradient(135deg, hsl(var(--lv) 80% 62%), hsl(var(--lv) 70% 44%));
  }
  .ld-lv::before {
    content: ""; width: 4px; height: 4px; border-radius: 1px; transform: rotate(45deg); background: rgb(255 255 255 / 0.92);
  }
  .ld-text { overflow-wrap: anywhere; color: #fff; }
  .ld-line.is-host { background: rgb(254 44 85 / 0.2); box-shadow: inset 0 0 0 1px rgb(254 44 85 / 0.32); }
  .ld-line.is-system {
    padding: 6px 10px; font-size: 11px; font-weight: 500; line-height: 1.4; color: #ffd38a; background: rgb(0 0 0 / 0.28);
  }
  .ld-line.is-join .ld-did, .ld-line.is-share .ld-did, .ld-line.is-like .ld-did { color: rgb(255 255 255 / 0.78); }
  .ld-line.is-follow .ld-did { color: #ff9db1; }
  .ld-line.is-gift .ld-text { color: #ffd97a; }
  .ld-line.is-mine .ld-who b { color: #7ff3ee; }
  .ld-gift-e { font-size: 14px; }
  .ld-times { margin-left: 3px; font-weight: 800; font-style: italic; }
  .ld-why { display: block; margin-top: 1px; font-size: 10px; color: rgb(255 255 255 / 0.55); }
  .ld-dots { display: inline-flex; gap: 3px; padding: 4px 0 2px; }
  .ld-dots i { width: 4px; height: 4px; border-radius: 999px; background: #fff; animation: ld-dot 1s ease-in-out infinite; }
  .ld-dots i:nth-child(2) { animation-delay: 0.15s; }
  .ld-dots i:nth-child(3) { animation-delay: 0.3s; }
  @keyframes ld-dot { 50% { opacity: 0.3; transform: translateY(-2px); } }

  /* Hearts, up the right. */
  .ld-hearts { position: absolute; right: 12px; bottom: 54px; width: 38px; height: 56%; pointer-events: none; }
  .ld-heart {
    position: absolute; bottom: 0; left: 8px; font-size: 20px; color: hsl(var(--hue) 90% 62%);
    filter: drop-shadow(0 2px 4px rgb(0 0 0 / 0.4));
    animation: ld-float 2.2s cubic-bezier(0.2, 0.6, 0.3, 1) forwards;
  }
  .ld-heart.is-big { font-size: 26px; }
  @keyframes ld-float {
    0% { opacity: 0; transform: translate(0, 0) scale(0.4); }
    12% { opacity: 1; transform: translate(0, -14px) scale(1.1); }
    100% { opacity: 0; transform: translate(var(--dx), -240px) scale(0.8); }
  }

  /* A gift combo, just above the chat: who, what, and how many, big. */
  .ld-banner {
    position: absolute; left: 8px; bottom: calc(90px + 30%); display: flex; max-width: 88%; height: 40px;
    align-items: center; gap: 7px; padding: 0 8px 0 4px; border-radius: 999px;
    background: linear-gradient(90deg, rgb(0 0 0 / 0.55), rgb(0 0 0 / 0.2) 72%, transparent);
    animation: ld-slide 0.42s var(--spring) both;
  }
  .ld-banner.is-big {
    background: linear-gradient(90deg, rgb(255 168 40 / 0.78), rgb(254 44 85 / 0.45) 70%, transparent);
    box-shadow: 0 0 26px -10px rgb(255 190 60 / 0.8);
  }
  .ld-banner .ld-av { width: 32px; height: 32px; font-size: 13px; }
  .ld-banner-t { min-width: 0; }
  .ld-banner-t b { display: block; overflow: hidden; font-size: 11.5px; text-overflow: ellipsis; white-space: nowrap; }
  .ld-banner-t small { display: block; font-size: 10px; color: rgb(255 255 255 / 0.85); }
  .ld-banner-e {
    font-size: 32px; line-height: 1; filter: drop-shadow(0 3px 6px rgb(0 0 0 / 0.45));
    animation: ld-pop 0.5s var(--spring) 0.1s both;
  }
  .ld-banner-x {
    font-size: 26px; font-weight: 900; font-style: italic; letter-spacing: -0.02em; line-height: 1;
    background: linear-gradient(180deg, #fff 35%, #ffe08a); -webkit-background-clip: text; background-clip: text;
    color: transparent; filter: drop-shadow(0 2px 3px rgb(0 0 0 / 0.55));
    animation: ld-pop 0.45s var(--spring) 0.2s both;
  }
  @keyframes ld-slide { from { opacity: 0; transform: translateX(-30px); } }
  @keyframes ld-pop { from { transform: scale(0.3); } }

  /* Someone coming in, just above the comment box. */
  .ld-enter {
    position: absolute; left: 8px; bottom: 54px; display: inline-flex; max-width: 72%; height: 24px; align-items: center;
    gap: 5px; padding: 0 11px 0 5px; border-radius: 999px; font-size: 11px; color: rgb(255 255 255 / 0.9);
    background: linear-gradient(90deg, rgb(255 255 255 / 0.24), rgb(255 255 255 / 0.05));
    animation: ld-slide 0.4s var(--spring) both;
  }
  .ld-enter b { overflow: hidden; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
  .ld-enter span { flex-shrink: 0; color: rgb(255 255 255 / 0.78); }
  .ld-enter.is-mine b { color: #7ff3ee; }

  /* Its answer over the camera, as the OBS page shows it: where, how big and which look are settings. */
  .ld-capwrap { position: absolute; left: 12px; right: 12px; display: flex; justify-content: center; pointer-events: none; }
  /* Top under the ranking pill, bottom just above where gifts show, middle between. */
  .ld-capwrap[data-pos="top"] { top: 80px; }
  .ld-capwrap[data-pos="middle"] { top: 25%; }
  .ld-capwrap[data-pos="bottom"] { bottom: calc(136px + 30%); }
  .ld-caption {
    --cap: 13.5px;
    display: flex; max-width: 100%; flex-direction: column; align-items: center; gap: 3px; text-align: center;
    padding: calc(var(--cap) * 0.55) calc(var(--cap) * 0.95); border-radius: calc(var(--cap) * 0.95);
    background: rgb(12 12 16 / 0.82);
    box-shadow: 0 0 0 1px rgb(255 255 255 / 0.1), 0 14px 30px -12px rgb(0 0 0 / 0.6),
                -2px -1px 0 rgb(37 244 238 / 0.55), 2px 1px 0 rgb(254 44 85 / 0.55);
    animation: ld-cap 0.42s cubic-bezier(0.3, 1.3, 0.5, 1) both;
  }
  @keyframes ld-cap { from { opacity: 0; transform: translateY(10px) scale(0.96); } }
  .ld-caption[data-size="small"] { --cap: 11px; }
  .ld-caption[data-size="large"] { --cap: 16.5px; }
  .ld-cap-to { font-size: calc(var(--cap) * 0.64); font-weight: 800; letter-spacing: 0.03em; color: #fe2c55; }
  .ld-cap-q { font-size: calc(var(--cap) * 0.72); line-height: 1.3; color: rgb(255 255 255 / 0.72); }
  .ld-cap-q b { font-weight: 800; color: #fe2c55; }
  .ld-cap-text { font-size: var(--cap); font-weight: 700; line-height: 1.28; color: #fff; }
  .ld-caption.is-spoken { box-shadow: 0 0 0 1px rgb(255 255 255 / 0.1), 0 14px 30px -12px rgb(0 0 0 / 0.6),
                                      -2px -1px 0 rgb(37 244 238 / 0.55), 2px 1px 0 rgb(254 44 85 / 0.55),
                                      0 0 26px -6px rgb(37 244 238 / 0.45); }
  .ld-caption[data-look="light"] { background: rgb(255 255 255 / 0.95); box-shadow: 0 0 0 1px rgb(0 0 0 / 0.06), 0 14px 30px -12px rgb(0 0 0 / 0.5); }
  .ld-caption[data-look="light"] .ld-cap-text { color: #121218; }
  .ld-caption[data-look="light"] .ld-cap-q { color: rgb(18 18 24 / 0.62); }
  .ld-caption[data-look="tiktok"] {
    gap: 1px; border-radius: calc(var(--cap) * 1.3); background: rgb(0 0 0 / 0.42); box-shadow: none;
    -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
  }
  .ld-caption[data-look="tiktok"] .ld-cap-q, .ld-caption[data-look="tiktok"] .ld-cap-q b { color: rgb(255 255 255 / 0.66); }
  .ld-caption[data-look="tiktok"] .ld-cap-q b { font-weight: 600; }
  .ld-caption[data-look="tiktok"] .ld-cap-text { font-weight: 600; text-shadow: 0 1px 2px rgb(0 0 0 / 0.35); }
  .ld-cap-host {
    display: inline-block; margin-right: 0.4em; padding: 0.1em 0.45em; border-radius: 0.35em; font-size: 0.62em;
    font-style: normal; font-weight: 800; vertical-align: 0.2em; color: #fff; background: #fe2c55;
  }

  /* You, as a viewer: the comment box and its buttons. */
  .ld-bar { position: absolute; left: 8px; right: 8px; bottom: 10px; display: flex; align-items: center; gap: 6px; }
  .ld-bar input {
    min-width: 0; flex: 1; height: 36px; padding: 0 14px; border-radius: 999px; font-size: 12.5px; color: #fff;
    background: rgb(0 0 0 / 0.32); -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px); outline: none;
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08);
  }
  .ld-bar input::placeholder { color: rgb(255 255 255 / 0.62); }
  .ld-bar input:focus { box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.28); }
  .ld-round {
    display: grid; width: 36px; height: 36px; flex-shrink: 0; place-items: center; border-radius: 999px; font-size: 17px;
    color: #fff; background: rgb(0 0 0 / 0.32); -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
    transition: transform 0.2s var(--spring), background-color 0.15s ease;
  }
  .ld-round:hover { background: rgb(0 0 0 / 0.45); }
  .ld-round:active { transform: scale(0.88); }
  .ld-round.is-gift {
    background: radial-gradient(circle at 35% 30%, rgb(255 120 160 / 0.55), rgb(254 44 85 / 0.35) 60%, rgb(0 0 0 / 0.3));
  }

  /* Before and after. */
  .ld-idle {
    position: absolute; inset: auto 16px 18px; display: flex; flex-direction: column; align-items: center; gap: 6px;
    text-align: center;
  }
  .ld-idle b { font-size: 15px; font-weight: 700; text-shadow: 0 2px 8px rgb(0 0 0 / 0.6); }
  .ld-idle small { font-size: 11.5px; color: rgb(255 255 255 / 0.75); }
  .ld-idle-facts { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 14px; margin: 4px 0 6px; font-size: 10.5px; color: rgb(255 255 255 / 0.7); }
  .ld-idle-facts em { display: block; font-size: 15px; font-style: normal; font-weight: 700; color: #fff; }
  .ld-go {
    width: 100%; margin-top: 10px; padding: 12px 0; border-radius: 10px; font-size: 14px; font-weight: 700; color: #fff;
    background: linear-gradient(135deg, #ff4468, #fe2c55); box-shadow: 0 10px 24px -10px rgb(254 44 85 / 0.9),
                inset 0 1px 0 rgb(255 255 255 / 0.25);
    transition: transform 0.25s var(--spring), box-shadow 0.2s ease;
  }
  .ld-go:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 14px 30px -10px rgb(254 44 85 / 1), inset 0 1px 0 rgb(255 255 255 / 0.3); }
  .ld-go:active:not(:disabled) { transform: scale(0.98); }
  .ld-go:disabled { opacity: 0.5; }
  .ld-start i { width: 7px; height: 7px; border-radius: 999px; background: #fff; }

  /* ── The controls ── */
  .ld-side { display: flex; min-width: 0; flex-direction: column; gap: 10px; }
  .ld-card {
    display: flex; flex-direction: column; gap: 10px; padding: 12px 14px; border-radius: 14px;
    background: rgb(255 255 255 / 0.03); box-shadow: inset 0 0 0 1px var(--color-edge);
  }
  .ld-row { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 12px; }
  .ld-k { font-size: 12.5px; font-weight: 550; color: var(--color-ink); }
  .ld-seg { display: block; width: 230px; max-width: 62%; }
  .ld-start, .ld-end {
    display: inline-flex; align-items: center; gap: 7px; padding: 7px 15px; border-radius: 999px;
    font-size: 12.5px; font-weight: 650; transition: transform 0.25s var(--spring), background-color 0.15s ease;
  }
  .ld-start { color: #fff; background: linear-gradient(135deg, #ff4468, #fe2c55); box-shadow: 0 8px 20px -10px rgb(254 44 85 / 0.9); }
  .ld-start:disabled { opacity: 0.5; }
  .ld-end { color: var(--color-ink); background: rgb(255 255 255 / 0.07); box-shadow: inset 0 0 0 1px var(--color-edge); }
  .ld-end:hover { background: rgb(255 255 255 / 0.1); }
  .ld-start:active, .ld-end:active { transform: scale(0.96); }
  .ld-name {
    width: 140px; height: 30px; padding: 0 10px; border-radius: 9px; font-size: 12.5px; color: var(--color-ink);
    background: rgb(255 255 255 / 0.05); box-shadow: inset 0 0 0 1px var(--color-edge); outline: none;
  }
  .ld-name:focus { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, transparent); }
  .ld-acts { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 6px; }
  .ld-acts button {
    padding: 7px 0; border-radius: 9px; font-size: 12px; font-weight: 550; color: var(--color-ink);
    background: rgb(255 255 255 / 0.05); box-shadow: inset 0 0 0 1px var(--color-edge);
    transition: background-color 0.15s ease, transform 0.2s var(--spring);
  }
  .ld-acts button:hover:not(:disabled) { background: rgb(255 255 255 / 0.09); }
  .ld-acts button:active:not(:disabled) { transform: scale(0.95); }
  .ld-acts button:disabled { opacity: 0.45; cursor: default; }
  .ld-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
  .ld-stats span { display: flex; flex-direction: column; font-size: 11px; color: var(--color-faint); }
  .ld-stats b { font-size: 17px; font-weight: 700; color: var(--color-ink); font-variant-numeric: tabular-nums; }
  .ld-stats .is-full b { color: var(--color-warn); }
  .ld-chiphead { margin-bottom: -4px; font-size: 10.5px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--color-faint); }
  .ld-chips { display: flex; flex-wrap: wrap; gap: 5px; }
  .ld-chips span {
    padding: 3px 9px; border-radius: 999px; font-size: 11px; color: var(--color-faint);
    background: rgb(255 255 255 / 0.03); box-shadow: inset 0 0 0 1px var(--color-edge); text-decoration: line-through;
    text-decoration-color: rgb(255 255 255 / 0.25);
  }
  .ld-chips span.is-on {
    text-decoration: none; color: var(--color-ink);
    background: color-mix(in srgb, #fe2c55 14%, transparent); box-shadow: inset 0 0 0 1px rgb(254 44 85 / 0.35);
  }
  .ld-note { font-size: 11.5px; line-height: 1.4; color: var(--color-faint); }
  .ld-note.is-bad { color: var(--color-bad); }

  /* The screen: what it shows, as a row of tiles; the one on screen lit in TikTok's red. */
  .ld-links { display: flex; gap: 12px; }
  .ld-links button { font-size: 11.5px; color: var(--color-faint); transition: color 0.15s ease; }
  .ld-links button:hover:not(:disabled) { color: var(--color-ink); }
  .ld-shots {
    display: flex; gap: 6px; margin: -2px -4px 0; padding: 4px 4px 6px; overflow-x: auto;
    scroll-snap-type: x proximity;
  }
  .ld-shot {
    position: relative; display: block; width: 46px; height: 64px; flex: 0 0 auto; overflow: hidden; border-radius: 10px;
    scroll-snap-align: start; background: rgb(255 255 255 / 0.04);
    transition: transform 0.2s var(--spring), box-shadow 0.2s ease, background-color 0.15s ease;
  }
  .ld-shot::after {
    content: ""; position: absolute; inset: 0; border-radius: inherit; pointer-events: none;
    box-shadow: inset 0 0 0 1px var(--color-edge); transition: box-shadow 0.2s ease;
  }
  .ld-shot:hover::after { box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.22); }
  .ld-shot.is-on { box-shadow: 0 0 16px -4px rgb(254 44 85 / 0.75); }
  .ld-shot.is-on::after { box-shadow: inset 0 0 0 2px #fe2c55; }
  .ld-shot:active:not(:disabled) { transform: scale(0.94); }
  .ld-shot:disabled { opacity: 0.5; }
  .ld-shot img { width: 100%; height: 100%; object-fit: cover; transition: filter 0.2s ease; }
  /* Blurred like the screen, until you look closer. */
  .ld-shots.is-blurred .ld-shot img { filter: blur(3px); }
  .ld-shots.is-blurred .ld-shot:hover img, .ld-shots.is-blurred .ld-shot:focus-visible img { filter: none; }
  .ld-shot.is-word {
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;
    font-size: 10px; font-weight: 550; color: var(--color-faint);
  }
  .ld-shot.is-word:hover { color: var(--color-ink); }
  .ld-shot.is-word.is-on { color: var(--color-ink); background: rgb(254 44 85 / 0.12); }
  .ld-shot.is-word.is-on :global(svg) { color: #fe2c55; }
  .ld-shot.is-add { background: rgb(255 255 255 / 0.02); }
  .ld-shot.is-add::after { box-shadow: none; border: 1px dashed rgb(255 255 255 / 0.2); }
  .ld-shot.is-none { background: radial-gradient(120% 80% at 30% 20%, rgb(254 44 85 / 0.18), transparent 60%), #0b0b10; }
  .ld-shot em {
    position: absolute; left: 0; right: 0; bottom: 0; padding: 9px 0 3px; font-size: 9.5px; font-style: normal;
    font-weight: 650; text-align: center; color: #fff; background: linear-gradient(transparent, rgb(0 0 0 / 0.7));
  }
  .ld-shot-mark {
    position: absolute; right: 3px; bottom: 3px; display: inline-flex; align-items: center; gap: 2px; padding: 1px 4px;
    border-radius: 5px; font-size: 8.5px; font-style: normal; font-weight: 700; font-variant-numeric: tabular-nums;
    color: #fff; background: rgb(0 0 0 / 0.58);
  }
  .ld-shot:has(em) .ld-shot-mark { bottom: auto; top: 3px; }
  .ld-file { display: none; }
  .ld-hint { margin-top: -4px; font-size: 11px; line-height: 1.4; color: var(--color-faint); }
  .ld-seg.is-4 { width: 264px; max-width: 72%; }
  .ld-seg.is-2 { width: 150px; }

  /* The app's own Animations switch: nothing floats, slides or pans. */
  :global(:root[data-motion="off"]) .ld-pan,
  :global(:root[data-motion="off"]) .ld-line, :global(:root[data-motion="off"]) .ld-banner,
  :global(:root[data-motion="off"]) .ld-banner-e, :global(:root[data-motion="off"]) .ld-banner-x,
  :global(:root[data-motion="off"]) .ld-caption, :global(:root[data-motion="off"]) .ld-enter,
  :global(:root[data-motion="off"]) .ld-dots i { animation: none; }
  :global(:root[data-motion="off"]) .ld-go, :global(:root[data-motion="off"]) .ld-round,
  :global(:root[data-motion="off"]) .ld-acts button, :global(:root[data-motion="off"]) .ld-follow,
  :global(:root[data-motion="off"]) .ld-close, :global(:root[data-motion="off"]) .ld-shot,
  :global(:root[data-motion="off"]) .ld-shot::after, :global(:root[data-motion="off"]) .ld-shot img,
  :global(:root[data-motion="off"]) .ld-links button { transition: none; }
</style>
