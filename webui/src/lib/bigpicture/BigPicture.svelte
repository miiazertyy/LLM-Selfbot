<script lang="ts">
  /**
   * Big Picture Mode: the whole screen, a set of pages about everything the bots
   * do, live, that plays by itself and can be walked into at any moment.
   *
   * Left alone it follows the bots (director.ts): whoever is being answered goes on
   * stage on Now, and when nobody is, it walks round the same pages anyone can use.
   * Reach out and everything on screen can be pressed: with the mouse, the keys
   * (focus.ts) or a gamepad (gamepad.ts). Nothing is taken from under you meanwhile.
   * Now says who is being answered instead, and Auto comes back when you have been
   * gone a while, with a ring on its button saying when.
   *
   * Each fact lives in one place. What the pages show is world.svelte.ts; this keeps
   * who is on stage, what is held, what the room is lit for, and the keys.
   *
   * The one thing it does by itself that costs the account anything is reading a
   * conversation's history, so that happens only for the one on stage, only when it
   * is not already loaded, and at most once every twenty seconds: history reads come
   * out of the account's hourly allowance. Opening someone by hand reads them at once,
   * as the Chats tab does.
   */
  import "./bp.css";
  import { onDestroy, onMount, tick as domUpdated, untrack } from "svelte";
  import { get } from "svelte/store";
  import { cubicIn, cubicOut } from "svelte/easing";
  import { bigPicture, bigPictureArriving, bigPictureCloser, bigPictureCovering, bigPictureSound, health, motionEnabled,
           picturesBlur, setBigPicture, toast } from "../stores";
  import { cancelReply, chatAccounts, chatCache, conversations, convKey, loadChatAccounts, loadConversation, loadDrafts,
           loadEarlier, refreshChats, replying, sendOwnMessage, sendReply, toggleIgnore } from "../chats";
  import { statusOf } from "../chatstatus";
  import { subscribeEvents, subscribeLogs } from "../logsocket";
  import { loadUsage, startUsageLive, usage, working } from "../modelusage";
  import { loadProviders, savedPlan } from "../providers";
  import { personasRes } from "../personas/store";
  import { socialsOn, sourceOn } from "../socials";
  import { thoughts, useThoughts } from "../thoughts";
  import { play as uiPlay } from "../uisound";
  import { setFullscreen, isDesktop } from "../window";
  import { HOUR_MINUTE, fmtDate } from "../fmt";
  import { MANUAL_HOLD, autoState, groupQueue, hold, initial, live, pageOf, pageProgress, pick, ranked, score, showPage, tabsFor,
           tick, togglePin, tourFor, type Page, type Row } from "./director";
  import { PAGE_LOOK, energyFor, lookFor, type LookName } from "./looks";
  import { cssColour, paletteForTrouble, themePalette, type RGB } from "./palette";
  import { personaName } from "./scenes";
  import { arrivals, primeAudio } from "./sounds";
  import { pageIn, pageOut } from "./motion";
  import { pointerActivity } from "./fx";
  import { clearFocus, focusAt, focusPage, focusPlate, inputMode, moveFocus, pressFocus, setFocus } from "./focus";
  import { startGamepad, type PadCommand } from "./gamepad";
  import { World } from "./world.svelte";
  import BPAccounts from "./BPAccounts.svelte";
  import BPBackdrop from "./BPBackdrop.svelte";
  import BPHints from "./BPHints.svelte";
  import BPInbox from "./BPInbox.svelte";
  import BPMinecraft from "./BPMinecraft.svelte";
  import BPNav from "./BPNav.svelte";
  import BPNow from "./BPNow.svelte";
  import BPPeople from "./BPPeople.svelte";
  import BPPersona from "./BPPersona.svelte";
  import BPPictures from "./BPPictures.svelte";
  import BPToday from "./BPToday.svelte";
  import type { HealthIssue, PageActions, Person, QRow, Spot } from "./types";

  let now = $state(Date.now() / 1000);
  let dir = $state(initial(Date.now() / 1000));
  /** H: what is written, and the pictures, blurred. */
  let hideText = $state(false);
  /** The pointer has been still a while: the cursor and the keys sit out. */
  let awake = $state(true);
  let sleepTimer: ReturnType<typeof setTimeout> | null = null;
  /** The list of keys, unrolled from the bar. */
  let help = $state(false);

  /** Closed or closing: the clock and the feeds stop at once, not after the fade. */
  const gone = () => !get(bigPicture);
  const world: World = new World({
    gone,
    onStage: (target: string, uid: string): boolean => !!spot && spot.target === target && String(spot.u.id) === uid,
    hold: (secs) => (dir = hold(dir, Date.now() / 1000, secs)),
    pulse: () => (roomPulse += 1),
  });

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
  const rowsFor = (q: QRow[]): (Row & { r: QRow })[] =>
    q.map((r) => ({ key: r.key, phase: r.st.phase, step: r.st.step ?? 0, eta: r.st.eta ?? null, ts: r.u.ts, r }));
  const groups = $derived.by(() => {
    const g = groupQueue(rowsFor(queue), now);
    return { answering: g.answering.map((x) => x.r), next: g.next.map((x) => x.r), waiting: g.waiting.map((x) => x.r) };
  });
  const multi = $derived($chatAccounts.length > 1);

  // The one on stage stays drawn after it leaves the queue (it was answered), from its last snapshot.
  $effect(() => {
    for (const r of queue) world.snapshots.set(r.key, r);
  });
  const spot = $derived.by<Spot | null>(() => {
    const k = dir.spotlight;
    if (!k) return null;
    const row = queue.find((r) => r.key === k);
    if (row) return { ...row, answered: false };
    const snap = world.snapshots.get(k);
    if (!snap) return null;
    const ignored = !!$chatCache[snap.target]?.users.find((u) => String(u.id) === String(snap.u.id))?.ignored;
    return { ...snap, answered: !snap.browsing && !ignored, ignored };
  });
  const messages = $derived(spot ? $conversations[convKey(spot.target, spot.u.id)]?.messages ?? [] : []);

  // ── The pages ────────────────────────────────────────────────────────────
  const issues = $derived<HealthIssue[]>(($health.issues ?? []) as HealthIssue[]);
  /** What needs fixing; an available update and the like are not a problem. */
  const urgent = $derived(issues.filter((i) => i.level === "error" || i.level === "warn"));
  const inboxCount = $derived(world.friends.length + urgent.length);

  /** Where the tour goes: every page there is something to show on. */
  const tour = $derived(tourFor({
    people: world.people.length > 0,
    accounts: world.accounts.length > 0,
    pictures: world.pictures.length > 0,
    persona: world.personaLines.length > 0,
    inbox: inboxCount > 0,
    minecraft: !!world.minecraft,
  }));
  const page = $derived(pageOf(dir));
  /** A tab that has emptied stays while it is on show: the last friend request answered says "all caught up". */
  const tabs = $derived(tabsFor({ minecraft: !!world.minecraft || page === "minecraft", inbox: inboxCount > 0 || page === "inbox" }));
  const auto = $derived(autoState(dir, now));
  const held = $derived(auto.mode !== "auto");
  /** Someone has their hands on it: pressed something, rather than only moved the pointer past. */
  const driving = $derived(dir.pinned || (auto.mode === "held" && dir.holdFor >= MANUAL_HOLD));
  /** Each showing of a page starts it afresh; Now stays itself as people come and go on its stage. */
  const pageKey = $derived(page === "now" ? "now" : `${page}:${dir.idle?.scene ?? 0}`);

  // Which way a page goes: to one further along it comes in from the right.
  let slide = $state(1);
  let lastIx = -1;
  $effect.pre(() => {
    const i = tabs.indexOf(page);
    untrack(() => {
      if (lastIx >= 0 && i !== lastIx) slide = i > lastIx ? 1 : -1;
      lastIx = i;
    });
  });

  // The director follows every change in the queue as it happens, and the clock besides.
  $effect(() => {
    const rows = rowsFor(queue);
    untrack(() => {
      if (!gone()) dir = tick(dir, rows, now, tour);
    });
  });

  // The list on the right starts with who wrote lately, once the queue has been read.
  $effect(() => {
    if (arrived && queue.length) untrack(() => world.seedFeed(queue));
  });

  // What a page shows is asked for as it comes up.
  $effect(() => {
    const p = page;
    untrack(() => {
      if (arrived) world.ensure(p);
    });
  });
  // Whose turn it is on People: the next one each time it comes round. A held page's clock moving is not a new showing.
  let turnSeen = -1;
  $effect(() => {
    const idle = dir.idle;
    if (page !== "people" || !idle || idle.scene === turnSeen) return;
    turnSeen = idle.scene;
    untrack(() => (world.turn += 1));
  });

  // History for the one on stage: only if not already loaded, at most one read every 20 seconds.
  let lastHistory = 0;
  const asked = new Set<string>();
  $effect(() => {
    void now;
    const s = spot;
    if (!s || s.answered || s.browsing) return;
    const k = convKey(s.target, s.u.id);
    if (asked.has(k) || get(conversations)[k]) return;
    if (Date.now() - lastHistory < 20000) return;
    lastHistory = Date.now();
    asked.add(k);
    loadConversation(s.target, s.u.id).catch(() => {});
  });

  // ── Whose persona ────────────────────────────────────────────────────────
  /** Chosen on Persona or Pictures; until then the account running, Discord's first. */
  let faceId = $state("");
  const faceAcct = $derived(world.accounts.find((a) => a.id === faceId)
    ?? world.accounts.find((a) => a.state === "running" && a.platform === "discord")
    ?? world.accounts.find((a) => a.state === "running") ?? world.accounts[0] ?? null);
  const personaOfAccount = (id: string) => $personasRes.data.accounts[id] || "default";
  const facePersona = $derived(faceAcct ? personaOfAccount(faceAcct.id) : "default");
  /** The name the persona goes by (its own, or the one its text gives), unless it has none but "Default". */
  const facePersonaName = $derived.by(() => {
    const p = $personasRes.data.personas.find((x) => x.id === facePersona);
    return p && !(p.is_default && p.name === "Default") ? p.name : "";
  });
  const pName = $derived(personaName(world.personaLines) || facePersonaName || faceAcct?.name || "");
  const speakers = $derived(world.accounts.filter((a) => personaOfAccount(a.id) === facePersona));
  /** One account for each persona there is, to choose between them. */
  const choices = $derived.by(() => {
    const seen = new Map<string, { account: (typeof world.accounts)[number]; persona: string; name: string }>();
    for (const a of world.accounts) {
      const pid = personaOfAccount(a.id);
      if (seen.has(pid)) continue;
      const p = $personasRes.data.personas.find((x) => x.id === pid);
      seen.set(pid, { account: a, persona: pid, name: p && !(p.is_default && p.name === "Default") ? p.name : a.name });
    }
    return [...seen.values()];
  });
  // Another account on show, speaking as another persona: its text, moods and pictures instead.
  $effect(() => {
    const pid = facePersona;
    if (!arrived) return;
    untrack(() => {
      world.loadPersona(pid);
      world.loadPictures(pid);
    });
  });
  function chooseFace(id: string) {
    faceId = id;
    uiPlay("select");
    actions.hold();
  }
  /** "Show pictures" was pressed: for the rest of this visit, like the Pictures tab. */
  let picsShown = $state(false);
  const picturesBlurred = $derived($picturesBlur && !picsShown);

  // ── The numbers on the bar ───────────────────────────────────────────────
  const tokensToday = $derived($usage.models.reduce((n, m) => n + m.today.in + m.today.out, 0));
  const requestsToday = $derived($usage.models.reduce((n, m) => n + m.today.requests, 0));
  const workingNow = $derived(Object.values($working).find((w) => w.job === "replies" || !w.job) ?? null);

  // ── What the model is thinking ───────────────────────────────────────────
  /** How long a thought stays with the reply it was for. */
  const THOUGHT_FOR = 120;
  const latestThought = $derived.by(() => {
    const list = $thoughts;
    for (let i = list.length - 1; i >= 0; i--) {
      const t = list[i];
      // A Minecraft account's every decision is one: those stay over its own picture.
      if (!t.source.startsWith("minecraft") && sourceOn($socialsOn, t.source)) return t;
    }
    return null;
  });
  /** One for the conversation on stage goes in the conversation, where its reply will land. */
  const stageThought = $derived.by(() => {
    const t = latestThought;
    if (!t || !spot || spot.answered || spot.browsing || t.source !== spot.target) return null;
    if (![2, 3, 4].includes(spot.st.step ?? 0) || now - t.at > THOUGHT_FOR) return null;
    return t;
  });
  /** One that has been up on the stage is done with: it folded away with its reply, and does not come back on the rail. */
  let thoughtOnStage = 0;
  $effect(() => {
    if (stageThought) thoughtOnStage = stageThought.at;
  });
  const railThought = $derived(latestThought && !stageThought && latestThought.at !== thoughtOnStage
    && !(spot && latestThought.source === spot.target) && now - latestThought.at < 60 ? latestThought : null);

  // ── The room: whoever is on stage lights it ───────────────────────────────
  /** The theme's own colours, for the pages about no one in particular. Read once it is on the page. */
  let themeColours = $state<RGB[] | null>(null);
  let themeAccent = $state<RGB | null>(null);
  /** Counts replies gone out on stage and things done by hand: each sends a ring of light across the room. */
  let roomPulse = $state(0);
  const TROUBLE = { errors: paletteForTrouble(true), warnings: paletteForTrouble(false) };
  /** Who a page says the room is for: the person in hand on People, the account grown on Accounts. */
  let pageLight = $state<{ page: Page; seed: string; art?: string } | null>(null);
  type Room = { seed: string; art: string; look: LookName; energy: number; palette: RGB[] | null };
  /**
   * What the background is for: the person on stage, in their own colours and their
   * own look, lively while their reply is written and typed; else who the page is
   * about; or the theme's colours for the pages about no one.
   */
  const room = $derived.by<Room>(() => {
    if (spot) {
      return { seed: spot.u.id, art: spot.u.avatar || "", look: lookFor(spot.u.id),
               energy: energyFor(spot.st.phase, spot.st.step ?? 0, spot.answered), palette: null };
    }
    const calm = 0.2;
    if (page === "inbox" && urgent.length) {
      return { seed: "inbox", art: "", look: PAGE_LOOK.inbox, energy: 0.35,
               palette: urgent.some((i) => i.level === "error") ? TROUBLE.errors : TROUBLE.warnings };
    }
    if (pageLight?.page === page) {
      return { seed: pageLight.seed, art: pageLight.art || "", look: page === "people" ? lookFor(pageLight.seed) : PAGE_LOOK[page], energy: calm, palette: null };
    }
    if (page === "persona" && faceAcct) {
      return { seed: `persona:${faceAcct.id}`, art: faceAcct.avatar || "", look: PAGE_LOOK.persona, energy: calm, palette: null };
    }
    return { seed: `page:${page}`, art: "", look: PAGE_LOOK[page], energy: calm, palette: themeColours };
  });
  /**
   * The accent of everything in here: the colour the room has gone to, melting with
   * it. On a page about no one the theme's own, and on one that is all warnings too:
   * Accept in the colour of an error would say the wrong thing.
   */
  let roomColour = $state<RGB | null>(null);
  const accent = $derived(room.palette || !roomColour ? themeAccent : roomColour);
  /**
   * It melts into a new colour a tenth of a second at a time, set from here rather
   * than eased in CSS. Every change of it is the whole view styled again, and a CSS
   * transition did that every frame, at the screen's 143 a second, for well over a
   * second each time the room changed: with the plate's own easing, that was nearly
   * all a move cost the iGPU. Ten steps still read as one melt.
   */
  let bpEl = $state<HTMLElement | null>(null);
  let shownAccent: RGB | null = null;
  let melting: ReturnType<typeof setTimeout> | null = null;
  const MELT_STEPS = 10;
  const rgbCss = (c: RGB) => `rgb(${Math.round(c[0] * 255)} ${Math.round(c[1] * 255)} ${Math.round(c[2] * 255)})`;
  /** What reads on a colour: the room's run from a dark magenta to a light gold. */
  const onColour = (c: RGB) => (0.2126 * c[0] ** 2.2 + 0.7152 * c[1] ** 2.2 + 0.0722 * c[2] ** 2.2 > 0.3 ? "#0b0b12" : "#fff");
  function setAccent(el: HTMLElement, c: RGB) {
    shownAccent = c;
    el.style.setProperty("--color-accent", rgbCss(c));
    el.style.setProperty("--bp-on", onColour(c));
  }
  $effect(() => {
    const to = accent;
    const el = bpEl;
    if (!el || !to) return;
    untrack(() => {
      if (melting) clearTimeout(melting);
      melting = null;
      const from = shownAccent;
      if (!from || !get(motionEnabled)) return setAccent(el, to);
      let i = 0;
      const step = () => {
        i += 1;
        const k = 1 - (1 - i / MELT_STEPS) ** 2;
        setAccent(el, [0, 1, 2].map((j) => from[j] + (to[j] - from[j]) * k) as RGB);
        melting = i < MELT_STEPS ? setTimeout(step, 110) : null;
      };
      step();
    });
  });
  /** The light gathers behind whatever has the focus, without chasing it to the very edge. */
  const lightX = $derived($focusAt ? 0.5 + ($focusAt.x - 0.5) * 0.7 : 0.5);
  const lightY = $derived($focusAt ? 0.45 + ($focusAt.y - 0.45) * 0.7 : 0.42);

  // ── Doing something about the conversation on stage ──────────────────────
  // The same things the Chats tab offers. Each holds the stage on that conversation
  // for a while, since acting on one and then having it slide away would be maddening.
  let acting = $state(false);
  async function conv(s: Pick<Spot, "key">, run: () => Promise<unknown>, done: string) {
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
  const canHurry = $derived(!!spot && !spot.answered && !spot.browsing && !spot.ignored
    && (spot.st.phase === "needs" || spot.st.step === 1 || spot.st.step === 3));
  const doReply = (s: Spot) => conv(s, () => sendReply(s.target, s.u.id), "");
  const doCancel = (s: Spot) => conv(s, () => cancelReply(s.target, s.u.id), `The reply to ${s.u.name} was dropped.`);
  const doIgnore = (s: Spot) => conv(s, async () => {
    const off = await toggleIgnore(s.target, s.u.id);
    toast(off ? `No longer answering ${s.u.name}.` : `Answering ${s.u.name} again.`, "ok");
  }, "");
  const doSend = (s: Spot, text: string) =>
    conv(s, async () => {
      const r = await sendOwnMessage(s.target, s.u.id, text);
      if (!r.ok) throw new Error(r.error || "Could not send it");
    }, "");
  /** Reply now on a row: from the queue or a person's card, without putting them on stage. */
  async function replyRow(r: QRow) {
    actions.hold();
    uiPlay("send", { level: 0.6 });
    try {
      await sendReply(r.target, r.u.id);
    } catch (e: any) {
      toast(e?.message || "That did not work", "err");
    }
  }

  // ── Going places ─────────────────────────────────────────────────────────
  /** Where Esc goes from a conversation opened from another page: back there. */
  let cameFrom = $state<Page | null>(null);
  /** Esc, when a page has something open to close first. */
  let pageBack = $state<(() => void) | null>(null);

  function goPage(p: Page) {
    cameFrom = null;
    if (p === "now") return goNow();
    const t = Date.now() / 1000;
    if (page === p) {
      dir = hold(dir, t, MANUAL_HOLD);
      uiPlay("select");
      return;
    }
    dir = showPage(dir, p, tour, t);
    afterGoing();
  }
  /**
   * Back to what is happening: whoever is being answered, or just landed. With nobody,
   * the quiet page, rather than an old conversation nobody is answering.
   */
  function goNow() {
    const t = Date.now() / 1000;
    const top = ranked(rowsFor(queue), t).find((r) => score(r, t) > 0);
    const was = page;
    dir = top ? pick(live(dir), top.key, t) : showPage(live(dir), "now", tour, t);
    if (was !== "now") afterGoing();
    else uiPlay("select");
  }
  /** A page gone to by hand is heard arriving, and the focus goes with it when the keys took it there. */
  function afterGoing() {
    uiPlay("whoosh");
    arrivals(6);
    const m = get(inputMode);
    if (m === "pointer") clearFocus();
    else domUpdated().then(() => requestAnimationFrame(() => focusPage(m)));
  }
  function stepPage(d: 1 | -1) {
    const i = tabs.indexOf(page);
    goPage(tabs[(i + d + tabs.length) % tabs.length]);
  }
  function pickRow(key: string) {
    dir = pick(dir, key, now);
    uiPlay("select");
  }
  /** Put someone on stage who is not in the queue: their real history, read now because someone asked. */
  function openPerson(p: Person) {
    const was = page;
    if (!queue.some((r) => r.key === p.key)) {
      world.snapshots.set(p.key, {
        key: p.key, target: p.target, browsing: true, account: $chatAccounts.find((a) => a.id === p.target),
        u: { id: p.id, name: p.name, avatar: p.avatar, username: "", snippet: "", count: 0, ts: p.last_ts },
        st: { phase: "needs", tone: "muted", short: "", title: "" },
      });
      asked.add(convKey(p.target, p.id));
      loadConversation(p.target, p.id).catch(() => {});
    }
    dir = pick(dir, p.key, Date.now() / 1000);
    if (was !== "now") {
      cameFrom = was;
      afterGoing();
    } else {
      uiPlay("select");
    }
  }
  /** The same from just an account and an id: a row in a list, the last reply. */
  function openConversation(target: string, id: string, as?: { name: string; avatar?: string }) {
    const known = world.people.find((p) => p.id === id && p.target === target);
    const who = as ?? world.whoIs(target, id);
    openPerson(known ?? { key: `${target}:${id}`, target, id, name: who.name, avatar: who.avatar,
                          platform: world.accounts.find((a) => a.id === target)?.platform ?? "discord", messages: 0 });
  }
  /** Back one level: what is open on the page, then where the conversation was opened from, then out. */
  function goBack() {
    if (pageBack) return pageBack();
    if (cameFrom) {
      const to = cameFrom;
      goPage(to);
      return;
    }
    close();
  }
  /** Leave for a page of the app: the address is what App.svelte follows. */
  function openRoute(route: string) {
    close();
    window.location.hash = `/${route}`;
  }
  const actions: PageActions = {
    open: openConversation,
    openPerson,
    go: goPage,
    leaveTo: openRoute,
    hold: () => (dir = hold(dir, Date.now() / 1000, MANUAL_HOLD)),
    // Asked for by the page it is for. A page on its way out saying "nothing now" comes after the next one has
    // said what it wants, so it only takes back its own.
    light: (from, r) => {
      if (r) pageLight = { page: from, ...r };
      else if (pageLight?.page === from) pageLight = null;
    },
    onBack: (fn) => (pageBack = fn),
    reply: (target, id) => {
      const r = queue.find((x) => x.target === target && String(x.u.id) === id);
      if (r) replyRow(r);
    },
  };

  function togglePinned() {
    dir = togglePin(dir);
    uiPlay(dir.pinned ? "on" : "off");
  }
  function toggleSound() {
    bigPictureSound.update((v) => !v);
    if (get(bigPictureSound)) {
      primeAudio();
      uiPlay("on");
    } else {
      uiPlay("off");
    }
  }
  function toggleHide() {
    hideText = !hideText;
    uiPlay(hideText ? "off" : "on");
  }
  function toggleHelp() {
    help = !help;
    uiPlay(help ? "open" : "release");
  }

  // ── Keys ─────────────────────────────────────────────────────────────────
  let composer = $state<HTMLInputElement | null>(null);
  function write() {
    composer?.focus();
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
      if (help) toggleHelp();
      else goBack();
    } else if (!plain) {
      return;
    } else if (e.key === "ArrowRight" || (e.key === "Tab" && !e.shiftKey)) {
      e.preventDefault();
      moveFocus("right");
    } else if (e.key === "ArrowLeft" || (e.key === "Tab" && e.shiftKey)) {
      e.preventDefault();
      moveFocus("left");
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      moveFocus("up");
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      moveFocus("down");
    } else if (e.key === "Enter") {
      e.preventDefault();
      inputMode.set("keys");
      if (!pressFocus()) moveFocus("down");
    } else if (e.key === " ") {
      e.preventDefault();
      togglePinned();
    } else if (k === "q" || e.key === "[") {
      inputMode.set("keys");
      stepPage(-1);
    } else if (k === "e" || e.key === "]") {
      inputMode.set("keys");
      stepPage(1);
    } else if (/^[1-9]$/.test(e.key)) {
      const p = tabs[Number(e.key) - 1];
      inputMode.set("keys");
      if (p) goPage(p);
    } else if (k === "l") {
      inputMode.set("keys");
      goPage("now");
    } else if (k === "r") {
      if (spot && canHurry) doReply(spot);
    } else if (k === "w") {
      if (spot) {
        e.preventDefault();
        write();
      }
    } else if (e.key === "?" || (k === "/" && e.shiftKey)) {
      toggleHelp();
    } else if (k === "m") {
      toggleSound();
    } else if (k === "h") {
      toggleHide();
    } else {
      return;
    }
    wake();
    dir = hold(dir, Date.now() / 1000, MANUAL_HOLD);
  }
  function onPad(cmd: PadCommand) {
    if (gone()) return;
    wake();
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    inputMode.set("pad");
    if (cmd === "up" || cmd === "down" || cmd === "left" || cmd === "right") moveFocus(cmd, "pad");
    else if (cmd === "ok") {
      if (!pressFocus()) focusPage("pad");
    } else if (cmd === "back") {
      if (help) toggleHelp();
      else goBack();
    } else if (cmd === "prev") stepPage(-1);
    else if (cmd === "next") stepPage(1);
    else if (cmd === "stay") togglePinned();
    else if (cmd === "hide") toggleHide();
    else if (cmd === "keys") toggleHelp();
    else if (cmd === "reply" && spot && canHurry) doReply(spot);
    dir = hold(dir, Date.now() / 1000, MANUAL_HOLD);
  }

  // ── The pointer ──────────────────────────────────────────────────────────
  function wake() {
    awake = true;
    if (sleepTimer) clearTimeout(sleepTimer);
    sleepTimer = setTimeout(() => (awake = false), 3200);
  }
  function onPointerMove(e: PointerEvent) {
    wake();
    // Back from the keys: the plate stops waiting where they left it.
    if (e.pointerType === "mouse" && (e.movementX || e.movementY) && get(inputMode) !== "pointer") {
      inputMode.set("pointer");
      setFocus(null);
    }
  }
  function onPointerDown(e: PointerEvent) {
    wake();
    if (help && !(e.target as Element | null)?.closest?.(".bph-list, .bph-key")) help = false;
  }
  /** The pointer moving: nothing slides away from under it. */
  let lastHold = 0;
  function holdStage() {
    const t = Date.now();
    if (t - lastHold < 400) return;
    lastHold = t;
    dir = hold(dir, t / 1000);
  }

  // ── Closing ──────────────────────────────────────────────────────────────
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
  /** The view has arrived: what is not on the first screen can be asked for now. */
  let arrived = $state(false);

  onMount(() => {
    mountedAt = performance.now();
    bigPictureCloser.fn = close;
    themeColours = themePalette();
    themeAccent = cssColour(getComputedStyle(document.documentElement).getPropertyValue("--color-accent"));
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
    uiPlay("dawn");
    arrivals(8, 260);
    // The first screen: who is waiting, and the accounts across the top.
    (get(chatAccounts).length ? Promise.resolve(get(chatAccounts)) : loadChatAccounts())
      .then((list) => list.forEach((a) => refreshChats(a.id, { maxAge: 15000, quiet: true })))
      .catch(() => {});
    world.loadDay();
    world.loadAccounts().then(() => {
      world.loadMinecraft();
      onceArrived(() => {
        world.loadFriends();
        world.loadPeople();
      });
    });
    // Everything else, once it is on screen.
    onceArrived(() => {
      // Its pictures and persona come with it, as the account on show's (the effect by facePersona).
      arrived = true;
      startUsageLive();
      loadUsage().catch(() => {});
      loadProviders().catch(() => {});
      world.loadActivity();
      world.loadWeek();
      personasRes.refresh({ maxAge: 15_000, quiet: true });
      void loadDrafts();
      world.loadBacklog();
    });
    stops.push(subscribeEvents("chat", world.onChat), subscribeEvents("model", world.onModel), subscribeLogs(world.onLog),
               useThoughts(), startGamepad(onPad));
    clock = setInterval(() => {
      if (document.hidden || gone()) return;
      now = Date.now() / 1000;
      dir = tick(dir, rowsFor(queue), now, tour);
      world.writeOneSummary(!dir.spotlight);
    }, 1000);
    slow = setInterval(() => {
      if (document.hidden || gone()) return;
      slowTicks += 1;
      world.slow(slowTicks);
      world.ensure(page);
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
    if (melting) clearTimeout(melting);
    world.destroy();
    document.removeEventListener("fullscreenchange", onFullscreenChange);
    setFullscreen(false);
  });

  const hhmm = $derived(fmtDate(now * 1000, HOUR_MINUTE));

  /**
   * The whole view arriving, out of a slight zoom like a scene cut, and leaving the
   * same way. Opacity and scale only, which the graphics card does by itself: they
   * used to blur the whole screen as well, and a blur the size of the screen, redrawn
   * every frame on top of everything in it, was where the frames went.
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

<svelte:window onkeydown={onKey} onpointermove={onPointerMove} onpointerdown={onPointerDown} />

<div class="bp" class:is-asleep={!awake} class:is-private={hideText} data-input={$inputMode} bind:this={bpEl}
     role="dialog" aria-modal="true" aria-label="Big Picture Mode" in:enter out:leave>
  <BPBackdrop art={room.art} seed={room.seed} look={room.look} energy={room.energy} palette={room.palette}
              pulse={roomPulse} focus={lightX} focusY={lightY} oncolours={(c) => (roomColour = c[0] ?? null)} />
  <div class="bp-plate" use:focusPlate aria-hidden="true"></div>

  <BPNav {tabs} {page} progress={pageProgress(dir, now)} sceneKey={dir.idle?.scene ?? 0} {auto} live={groups.answering}
         arrivals={world.arrivals} {inboxCount} inboxBad={urgent.some((i) => i.level === "error")} accounts={world.accounts}
         clock={hhmm} showClock={!(page === "now" && !spot)} {awake} sound={$bigPictureSound} hidden={hideText}
         ongo={goPage} onauto={togglePinned} onsound={toggleSound} onhide={toggleHide} onleave={close} />

  <!-- The pointer moving holds it: nothing slides away from under a click. -->
  <main class="bp-main" use:pointerActivity={holdStage}>
    {#key pageKey}
      <section class="bp-page" data-page={page} in:pageIn={{ dir: slide }} out:pageOut={{ dir: slide }}>
        {#if page === "now"}
          <BPNow {world} act={actions} {spot} {messages} answering={groups.answering} next={groups.next} waiting={groups.waiting}
                 {multi} {now} {driving} thought={stageThought} otherThought={railThought} busy={acting} replying={$replying}
                 writing={!!workingNow || (!!spot && spot.st.step === 2)} plan={$savedPlan} models={$usage.models} bind:composer
                 onpick={pickRow} onreply={replyRow} onearlier={spot ? () => loadEarlier(spot.target, spot.u.id) : undefined}
                 onstagereply={spot ? () => doReply(spot) : undefined} oncancel={spot ? () => doCancel(spot) : undefined}
                 onignore={spot ? () => doIgnore(spot) : undefined} onsend={spot ? (t) => doSend(spot, t) : undefined}
                 onmodel={() => goPage("today")} />
        {:else if page === "people"}
          <BPPeople {world} act={actions} {now} {queue} replying={$replying} onreply={replyRow} />
        {:else if page === "accounts"}
          <BPAccounts {world} act={actions} {now} moodsOf={(id) => world.moodsFor(personaOfAccount(id))} />
        {:else if page === "today"}
          <BPToday {world} act={actions} tokens={tokensToday} requests={requestsToday} models={$usage.models} plan={$savedPlan}
                   working={workingNow ? `${workingNow.provider}|${workingNow.model}` : null} driven={held} />
        {:else if page === "persona"}
          <BPPersona {world} act={actions} name={pName} face={faceAcct} {speakers} {choices} current={facePersona} onwho={chooseFace} />
        {:else if page === "pictures"}
          <BPPictures {world} act={actions} {now} blurred={picturesBlurred} {hideText} {choices} current={facePersona} onwho={chooseFace}
                      onreveal={() => { picsShown = true; actions.hold(); }} />
        {:else if page === "minecraft" && world.minecraft}
          <BPMinecraft account={world.minecraft} />
        {:else if page === "inbox"}
          <BPInbox {world} act={actions} {issues} {now} />
        {/if}
      </section>
    {/key}
  </main>

  <BPHints {page} mode={$inputMode} canReply={canHurry && page === "now"} canWrite={!!spot && page === "now"}
           backLabel={pageBack || cameFrom ? "Back" : "Leave"} showScore={page !== "today"}
           replies={world.day.replies} people={world.day.people} tokens={tokensToday} {help}
           onreply={spot ? () => doReply(spot) : undefined} onwrite={write} onpage={stepPage} onstay={togglePinned}
           onback={goBack} onhelp={toggleHelp} onscore={() => goPage("today")} />
</div>

<style>
  .bp-main { position: relative; z-index: 1; display: grid; min-width: 0; min-height: 0; grid-template: minmax(0, 1fr) / minmax(0, 1fr); }
  /* The leaving and the arriving share the one cell, so one slides off as the other slides in. */
  .bp-page { grid-area: 1 / 1; min-width: 0; min-height: 0; padding: clamp(2px, 0.6vh, 8px) var(--bp-side) 0; will-change: transform, opacity; }
  /* A phone, or the app shrunk to its pocket size: the view scrolls, and each page is as tall as what is on it. */
  @media (max-width: 720px) {
    /* align-content: start, or the rows share out what is left of the screen and the bar floats down it. */
    :global(.bp) { overflow-x: hidden; overflow-y: auto; grid-template-rows: auto auto auto; align-content: start; }
    .bp-main { min-height: auto; grid-template: auto / minmax(0, 1fr); }
  }
</style>
