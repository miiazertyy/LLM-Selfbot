<script lang="ts">
  /**
   * What a Minecraft account sees, live, and its controls: prismarine-viewer's own page, drawn here in the panel's
   * browser from what the bot's process sends it (agent_hooks.mjs), through the panel's own path
   * (minecraft_routes.py), so it works wherever the panel does. Its eyes, or from above.
   *
   * The viewer draws the world and nothing else: no chat, no hotbar, no health, nothing of what a player actually
   * has on screen. All of that is drawn here instead, over the picture, from what the bot's own process reports
   * (its `hud` route), with Minecraft's own pictures for items, hearts and effects where the viewer ships them.
   *
   * And it can be played: "Take control" pauses its AI and hands the body to the keyboard and mouse (or, on a
   * phone, a stick and buttons), the way the game itself is played, and anything can be typed into its chat at
   * any time, commands included. Letting go gives it back to the AI, which carries on.
   */
  import { onMount, untrack } from "svelte";
  import { fade, scale } from "svelte/transition";
  import Segmented from "../components/Segmented.svelte";
  import Icon from "../components/Icon.svelte";
  import LiveThought from "../components/LiveThought.svelte";
  import { api, type McHud, type McInput, type McSlot } from "../api";
  import { visiblePoll } from "../poll";
  import { play } from "../uisound";
  import { saveUrlAs } from "../window";

  let { account, name = "", full = false }: { account: string; name?: string; full?: boolean } = $props();

  type Slot = McSlot;
  type Hud = McHud;
  type Keys = McInput["keys"];

  let mode = $state<"eyes" | "above">("eyes");
  let ready = $state(false);
  let error = $state("");
  let version = $state("");
  let stage: HTMLElement | null = $state(null);
  let frameEl: HTMLIFrameElement | null = $state(null);
  let cap: HTMLElement | null = $state(null);
  let chatBox: HTMLInputElement | null = $state(null);
  let hud = $state<Hud | null>(null);
  let showBag = $state(false);
  let showChat = $state(true);
  let showThoughts = $state(true);
  let showDebug = $state(false);
  let showTab = $state(false);
  let hideHud = $state(false);
  let notice = $state("");
  let fps = $state(0);
  let broken = $state<Record<string, true>>({});

  // ── Played by hand ─────────────────────────────────────────────────────────
  let driving = $state(false);
  let taking = $state(false);
  let locked = $state(false);
  let chatting = $state(false);
  let chatText = $state("");
  let sending = $state(false);
  const keys = $state<Keys>({ forward: false, back: false, left: false, right: false, jump: false, sprint: false, sneak: false });
  const mouse = $state({ attack: false, use: false });
  // Pressed since the last send: a tap shorter than one send still reaches it (a jump, a click).
  const latch = { keys: new Set<keyof Keys>(), attack: false, use: false };
  let look = { yaw: 0, pitch: 0 };
  let dirty = false;
  let busy = false;
  let lastSent = 0;
  let drivingSince = 0;
  let drivingNow = false;
  let ctrlSprint = false;
  let tapSprint = false;
  let lastForward = 0;
  let lastWheel = 0;
  const said: string[] = [];
  let saidAt = -1;
  const touch = typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;
  const SENS = 0.0024;          // radians a pixel of mouse: about the game's own default
  const TOUCH_SENS = 0.0065;

  const base = $derived(`/api/minecraft/${encodeURIComponent(account)}/view/`);
  // The page as first loaded. Switching between its eyes and above happens in place over its connection, so the
  // world it already has stays; only a page that cannot (no connection) is loaded again the other way.
  let frameMode = $state<"eyes" | "above">("eyes");
  const src = $derived(`${base}${frameMode === "above" ? "?view=above" : ""}`);
  $effect(() => {
    const m = mode;
    if (m === frameMode) return;
    const sock = untrack(() => viewSocket());
    const w = untrack(() => frameEl?.contentWindow as any);
    if (sock && w) {
      sock.emit("lsb:view", { above: m === "above" });
      w.__lsbAbove = m === "above";
    } else {
      frameMode = m;
    }
  });
  /** One of Minecraft's own pictures, from the viewer's textures for the version it draws. */
  const tex = (rel: string | undefined | null) => (hud?.tex && rel ? `${base}textures/${hud.tex}/${rel}` : "");
  const who = $derived(hud?.who || name || "it");

  onMount(() => {
    const look_ = async () => {
      try {
        const r: any = await api.minecraftView(account);
        const was = ready;
        ready = !!r?.ready;
        error = String(r?.error || "");
        version = String(r?.version || "");
        if (ready && !was) play("rise", { level: 0.5 });
      } catch {
        ready = false;
      }
    };
    look_();
    const stopStatus = visiblePoll(look_, 3000);
    const onLock = () => {
      locked = !!cap && document.pointerLockElement === cap;
      // The mouse let out (Esc): its buttons let go with it, as the game does when it pauses.
      if (!locked && (mouse.attack || mouse.use)) {
        mouse.attack = mouse.use = false;
        dirty = true;
      }
    };
    document.addEventListener("pointerlockchange", onLock);
    return () => {
      stopStatus();
      document.removeEventListener("pointerlockchange", onLock);
      if (document.pointerLockElement) document.exitPointerLock?.();
      // Closed while playing it: it goes back to its AI rather than standing there.
      if (drivingNow) api.minecraftDrive(account, false).catch(() => {});
    };
  });

  /** Asked every `ms` while the page can be seen, whether or not its window is the one in front: a view is
   *  watched from beside something else. */
  function livePoll(fn: () => void, ms: number): () => void {
    const t = setInterval(() => { if (!document.hidden) fn(); }, ms);
    return () => clearInterval(t);
  }

  // Its own side of the screen: often enough to feel live, and four times a second while it is being played. The
  // bot reads it off itself each time, so it costs nothing but the round trip.
  $effect(() => {
    if (!ready) {
      hud = null;
      return;
    }
    const acc = account;
    const ask = { debug: showDebug, tab: showTab };
    const every = driving ? 250 : 1000;
    let gone = false;
    const read = async () => {
      try {
        const r = await api.minecraftHud(acc, ask);
        if (gone || !r?.ok) return;
        hud = r;
        // It let go by itself (no word from here for a while, or a goal was given): so does this.
        if (drivingNow && r.driving === false && Date.now() - drivingSince > 3000) dropControl("It plays by itself again.");
      } catch {
        /* between worlds; the next one will do */
      }
      if (ask.debug) fps = Number((frameEl?.contentWindow as any)?.__lsbFps || 0);
    };
    read();
    const stop = livePoll(read, every);
    return () => {
      gone = true;
      stop();
    };
  });

  $effect(() => {
    if (!notice) return;
    const t = setTimeout(() => (notice = ""), 2800);
    return () => clearTimeout(t);
  });

  function fullscreen() {
    play("open");
    stage?.requestFullscreen?.().catch(() => {});
  }

  /** Its view in a window of its own, beside the panel: the app's own window on a computer, a tab in a browser. */
  async function popOut() {
    play("open");
    const opened = await window.pywebview?.api?.open_view?.(account, name).catch(() => false);
    if (!opened) window.open(`/?watch=${encodeURIComponent(account)}&name=${encodeURIComponent(name)}`, "_blank", "noopener");
  }

  // ── Taking it over ─────────────────────────────────────────────────────────
  async function takeControl() {
    if (taking || driving) return;
    taking = true;
    play("rise");
    try {
      const r = await api.minecraftDrive(account, true);
      if (!r?.ok) {
        notice = r?.reason || "It could not be taken over.";
        play("err");
        return;
      }
      look = { yaw: Number(hud?.yaw ?? 0), pitch: Number(hud?.pitch ?? 0) };
      driving = drivingNow = true;
      drivingSince = Date.now();
      showBag = false;
      if (!touch) notice = "Click the view to play.";
    } catch {
      notice = "It could not be taken over.";
      play("err");
    } finally {
      taking = false;
    }
  }

  /** Letting go here: every key up, the mouse let out, and the body back to its AI. */
  function dropControl(why = "") {
    releaseAll();
    driving = drivingNow = false;
    chatting = false;
    if (document.pointerLockElement) document.exitPointerLock?.();
    const w = frameEl?.contentWindow as any;
    if (w) w.__lsbLook = null;
    if (why) notice = why;
  }

  async function letGo() {
    play("undo");
    dropControl();
    try { await api.minecraftDrive(account, false); } catch { /* it gives itself back before long */ }
  }

  function releaseAll() {
    for (const k of Object.keys(keys) as (keyof Keys)[]) keys[k] = false;
    mouse.attack = mouse.use = false;
    ctrlSprint = tapSprint = false;
    latch.keys.clear();
    latch.attack = latch.use = false;
    dirty = true;
  }

  function lockMouse() {
    if (!driving || touch || !cap) return;
    try {
      const p: any = cap.requestPointerLock?.();
      p?.catch?.(() => {});
    } catch { /* clicked again, it locks */ }
  }

  /** Where it looks and what is held, sent whole: the newest state is all that matters, so one lost costs nothing. */
  async function send() {
    if (!drivingNow) return;
    if (busy) {
      dirty = true;
      return;
    }
    busy = true;
    dirty = false;
    lastSent = Date.now();
    const held: Keys = { ...keys };
    for (const k of latch.keys) held[k] = true;
    const body: McInput = { keys: held, yaw: look.yaw, pitch: look.pitch,
                            attack: mouse.attack || latch.attack, use: mouse.use || latch.use };
    latch.keys.clear();
    latch.attack = latch.use = false;
    // Over the view's own connection, already open, as the hands move: no web request each. The panel's route
    // when there is no such connection (a viewer this does not know).
    const sock = viewSocket();
    if (sock) {
      sock.emit("lsb:input", body);
      busy = false;
      return;
    }
    try {
      await api.minecraftInput(account, body);
    } catch {
      /* the next one carries the same */
    }
    busy = false;
  }

  /** The view page's connection to the bot (agent_hooks.mjs exposes it), when it is up. */
  function viewSocket(): any {
    try {
      const s = (frameEl?.contentWindow as any)?.__lsbSocket;
      return s && s.connected ? s : null;
    } catch {
      return null;
    }
  }

  // While it is played: what the hands do goes out as it changes, and twice a second anyway so it knows they are
  // still there; the camera in its eyes turns with the mouse at once rather than a round trip later.
  $effect(() => {
    if (!driving) return;
    const t = setInterval(() => {
      const w = frameEl?.contentWindow as any;
      if (w) w.__lsbLook = { yaw: look.yaw, pitch: look.pitch, at: Date.now(), above: mode === "above" };
      if (dirty || Date.now() - lastSent > 400) send();
    }, 33);
    return () => clearInterval(t);
  });

  // An accidental Ctrl+W in a browser tab would close it mid-game: it asks first. (The app's own window has none.)
  $effect(() => {
    if (!driving || (window as any).pywebview) return;
    const stay = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", stay);
    return () => window.removeEventListener("beforeunload", stay);
  });

  const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a));
  const clampPitch = (p: number) => Math.max(-1.5707, Math.min(1.5707, p));

  function turn(dx: number, dy: number, sens: number) {
    look = { yaw: wrap(look.yaw - dx * sens), pitch: clampPitch(look.pitch - dy * sens) };
    dirty = true;
    const w = frameEl?.contentWindow as any;
    if (w) w.__lsbLook = { yaw: look.yaw, pitch: look.pitch, at: Date.now(), above: mode === "above" };
  }

  function onMouseMove(e: MouseEvent) {
    if (driving && locked) turn(e.movementX, e.movementY, SENS);
  }

  function onCapDown(e: MouseEvent) {
    if (!driving || touch) return;
    e.preventDefault();
    if (!locked) {
      showBag = false;
      lockMouse();
      return;
    }
    if (e.button === 0) {
      mouse.attack = true;
      latch.attack = true;
    } else if (e.button === 2) {
      mouse.use = true;
      latch.use = true;
    }
    send();
  }

  function onMouseUp(e: MouseEvent) {
    if (e.button === 0 && mouse.attack) mouse.attack = false;
    else if (e.button === 2 && mouse.use) mouse.use = false;
    else return;
    dirty = true;
  }

  function onWheel(e: WheelEvent) {
    if (!driving || !hud) return;
    e.preventDefault();
    if (Date.now() - lastWheel < 70 || !e.deltaY) return;
    lastWheel = Date.now();
    pickSlot((hud.held + (e.deltaY > 0 ? 1 : 8)) % 9);
  }

  // ── The keyboard, the game's own keys ──────────────────────────────────────
  const MOVES: Record<string, keyof Keys> = {
    KeyW: "forward", ArrowUp: "forward", KeyS: "back", ArrowDown: "back", KeyA: "left", ArrowLeft: "left",
    KeyD: "right", ArrowRight: "right", Space: "jump", ShiftLeft: "sneak", ShiftRight: "sneak",
  };

  function setKey(k: keyof Keys, down: boolean) {
    if (keys[k] === down) return;
    keys[k] = down;
    if (down) latch.keys.add(k);
    dirty = true;
  }

  function onKey(e: KeyboardEvent) {
    if (!driving) return;
    const t = e.target as HTMLElement | null;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
    const down = e.type === "keydown";
    const move = MOVES[e.code];
    if (move) {
      e.preventDefault();
      e.stopPropagation();
      // Forward twice quickly sprints, as in the game; Ctrl held does too.
      if (move === "forward" && down && !e.repeat) {
        if (Date.now() - lastForward < 300) tapSprint = true;
        lastForward = Date.now();
      }
      if (move === "forward" && !down) tapSprint = false;
      setKey(move, down);
      setKey("sprint", ctrlSprint || tapSprint);
      if (down) send();
      return;
    }
    if (e.code === "ControlLeft" || e.code === "ControlRight") {
      ctrlSprint = down;
      setKey("sprint", ctrlSprint || tapSprint);
      return;
    }
    if (e.code === "Tab") {
      e.preventDefault();
      e.stopPropagation();
      showTab = down;
      return;
    }
    if (!down || e.repeat) return;
    const digit = /^Digit([1-9])$/.exec(e.code);
    let done = true;
    if (digit) pickSlot(Number(digit[1]) - 1);
    else if (e.code === "KeyQ") drop(e.ctrlKey);
    else if (e.code === "KeyF") swapHands();
    else if (e.code === "KeyE") toggleBag();
    else if (e.code === "KeyT") openChat("");
    else if (e.code === "Slash") openChat("/");
    else if (e.code === "F1") hideHud = !hideHud;
    else if (e.code === "F2") screenshot();
    else if (e.code === "F3") toggleDebug();
    else if (e.code === "F5") switchView();
    else if (e.code === "Escape" && (showBag || hud?.window)) closePanels();
    // Escape is the mouse let out (the browser does that); here it never closes the window around the view.
    else if (e.code === "Escape") done = true;
    else done = false;
    if (done) {
      e.preventDefault();
      e.stopPropagation();
    }
  }

  // The wheel picks a hotbar slot rather than scrolling the page: a listener that may say so (not a passive one).
  $effect(() => {
    const el = cap;
    if (!el) return;
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });

  // Something opened (a chest, a furnace): the mouse is let out so its slots can be clicked.
  const windowOpen = $derived(!!hud?.window);
  $effect(() => {
    if (windowOpen && document.pointerLockElement) document.exitPointerLock?.();
  });

  // Ahead of everything else on the page (capture), so the game's keys never reach the dialog around it.
  $effect(() => {
    if (!driving) return;
    const blur = () => releaseAll();
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("keyup", onKey, true);
    window.addEventListener("blur", blur);
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("keyup", onKey, true);
      window.removeEventListener("blur", blur);
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
  });

  // ── One thing done ─────────────────────────────────────────────────────────
  async function act(body: Parameters<typeof api.minecraftAct>[1]) {
    try {
      const sock = viewSocket();
      const r: any = sock
        ? await new Promise((resolve) => {
            const t = setTimeout(() => resolve({ ok: false, reason: "It did not answer." }), 8000);
            sock.emit("lsb:act", body, (answer: any) => { clearTimeout(t); resolve(answer); });
          })
        : await api.minecraftAct(account, body);
      if (r && !r.ok && r.reason) notice = r.reason;
    } catch {
      notice = "It did not answer.";
    }
  }

  function pickSlot(n: number) {
    if (!hud || !driving) return;
    if (hud.held === n) return;
    hud = { ...hud, held: n };
    play("tick", { level: 0.45 });
    act({ do: "slot", slot: n });
  }

  function drop(all = false) {
    if (!hud?.hotbar[hud.held]) return;
    play("drop", { level: 0.6 });
    act({ do: "drop", all });
  }

  function swapHands() {
    play("slot", { level: 0.6 });
    act({ do: "swap" });
  }

  function toggleBag() {
    if (hud?.window) {
      closePanels();
      return;
    }
    showBag = !showBag;
    play(showBag ? "open" : "undo", { level: 0.6 });
    if (showBag && document.pointerLockElement) document.exitPointerLock?.();
  }

  function closePanels() {
    play("undo", { level: 0.6 });
    showBag = false;
    if (hud?.window) act({ do: "close" });
  }

  function toggleDebug() {
    showDebug = !showDebug;
    play("tap");
  }

  function switchView() {
    mode = mode === "eyes" ? "above" : "eyes";
    play("slide", { level: 0.6 });
  }

  /** Something in its bag, clicked: into its hand, or on, if it is armour. */
  function useFromBag(s: Slot) {
    if (!s || s.slot == null) return;
    if (!driving) {
      notice = "Take control to use what it carries.";
      return;
    }
    play("slot");
    act({ do: "equip", slot: s.slot });
  }

  /** A slot of what is open (a server's menu, a chest), clicked as the game clicks it: left, right, or with Shift
   *  to move it across. A menu's items are its buttons. `at` is the slot's place, empty slots included. */
  function clickSlot(e: MouseEvent, at: number, own: boolean, button: 0 | 1 = 0) {
    e.preventDefault();
    if (!driving) {
      notice = "Take control to use it.";
      return;
    }
    play(e.shiftKey ? "grab" : "tap", { level: 0.7 });
    act({ do: "click", slot: at, own, button, shift: e.shiftKey });
  }

  /** What a slot says, for its tooltip: its name, then its own lines. */
  const tip = (s: Slot) => (s ? [s.name + (s.count > 1 ? ` x${s.count}` : ""), ...(s.lore ?? [])].join("\n") : "empty");

  async function respawn() {
    play("rise");
    await act({ do: "respawn" });
  }

  /** A picture of the view as it is now (F2), saved where you choose: the app's own Save dialog, a download in a
   *  browser. The HUD is the panel's, so it is the world alone, as the game's own F1 then F2 would be. */
  async function screenshot() {
    const w = frameEl?.contentWindow as any;
    const url: string = w?.__lsbShot ? await w.__lsbShot() : "";
    if (!url) {
      notice = "There is no picture to take yet.";
      play("err");
      return;
    }
    const when = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
    try {
      const where = await saveUrlAs(url, `${(who || "minecraft").replace(/[^\w-]+/g, "_")}-${when}.png`);
      if (!where) return;
      play("glint");
      notice = "Picture saved.";
    } catch {
      notice = "The picture could not be saved.";
      play("err");
    }
  }

  // ── Its chat ───────────────────────────────────────────────────────────────
  function openChat(start: string) {
    releaseAll();
    if (document.pointerLockElement) document.exitPointerLock?.();
    chatText = start;
    chatting = true;
    play("open", { level: 0.5 });
    queueMicrotask(() => {
      chatBox?.focus();
      chatBox?.setSelectionRange(start.length, start.length);
    });
  }

  async function sendChat(e?: Event) {
    e?.preventDefault();
    const text = chatText.trim();
    if (!text || sending) return;
    sending = true;
    try {
      const r = await api.minecraftSay(account, text);
      if (r?.ok) {
        said.push(text);
        if (said.length > 30) said.shift();
        saidAt = -1;
        chatText = "";
        play("send");
      } else {
        notice = r?.reason || "It could not say that.";
        play("err");
      }
    } catch {
      notice = "It could not say that.";
      play("err");
    }
    sending = false;
    if (driving) backToGame();
  }

  function backToGame() {
    chatting = false;
    chatBox?.blur();
    lockMouse();
  }

  function chatKeys(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      chatText = "";
      if (driving) backToGame();
      else chatBox?.blur();
    } else if (e.key === "ArrowUp" && said.length) {
      e.preventDefault();
      saidAt = saidAt < 0 ? said.length - 1 : Math.max(0, saidAt - 1);
      chatText = said[saidAt];
    } else if (e.key === "ArrowDown" && saidAt >= 0) {
      e.preventDefault();
      saidAt += 1;
      if (saidAt >= said.length) {
        saidAt = -1;
        chatText = "";
      } else {
        chatText = said[saidAt];
      }
    }
  }

  // ── On a phone: a stick, the view to drag, and buttons ─────────────────────
  let stick = $state({ x: 0, y: 0, id: -1 });
  let lookTouch = { id: -1, x: 0, y: 0 };
  const STICK = 46;

  function stickAt(e: PointerEvent, el: HTMLElement) {
    const r = el.getBoundingClientRect();
    let x = e.clientX - (r.left + r.width / 2), y = e.clientY - (r.top + r.height / 2);
    const d = Math.hypot(x, y);
    if (d > STICK) {
      x = (x / d) * STICK;
      y = (y / d) * STICK;
    }
    stick = { x, y, id: e.pointerId };
    const dead = 14;
    setKey("forward", y < -dead);
    setKey("back", y > dead);
    setKey("left", x < -dead);
    setKey("right", x > dead);
    // Pushed right to the edge, forward: running.
    setKey("sprint", y < -STICK * 0.92);
  }

  function stickDown(e: PointerEvent) {
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    stickAt(e, e.currentTarget as HTMLElement);
    send();
  }

  function stickMove(e: PointerEvent) {
    if (e.pointerId === stick.id) stickAt(e, e.currentTarget as HTMLElement);
  }

  function stickUp(e: PointerEvent) {
    if (e.pointerId !== stick.id) return;
    stick = { x: 0, y: 0, id: -1 };
    for (const k of ["forward", "back", "left", "right", "sprint"] as (keyof Keys)[]) setKey(k, false);
  }

  function capTouchDown(e: PointerEvent) {
    if (!driving || e.pointerType === "mouse") return;
    lookTouch = { id: e.pointerId, x: e.clientX, y: e.clientY };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }

  function capTouchMove(e: PointerEvent) {
    if (e.pointerId !== lookTouch.id) return;
    turn(e.clientX - lookTouch.x, e.clientY - lookTouch.y, TOUCH_SENS);
    lookTouch = { ...lookTouch, x: e.clientX, y: e.clientY };
  }

  function capTouchUp(e: PointerEvent) {
    if (e.pointerId === lookTouch.id) lookTouch = { id: -1, x: 0, y: 0 };
  }

  function holdKey(k: keyof Keys, down: boolean) {
    setKey(k, down);
    if (down) send();
  }

  function holdButton(b: "attack" | "use", down: boolean) {
    mouse[b] = down;
    if (down) latch[b] = true;
    dirty = true;
    if (down) send();
  }

  // ── What the numbers mean ────────────────────────────────────────────────
  /** Minecraft counts health and food in halves: ten hearts, ten drumsticks. */
  const hearts = (n: number) => Math.max(0, Math.min(10, n / 2));
  const bubbles = $derived(hud?.air == null ? 0 : Math.max(0, Math.min(10, hud.air / 2)));
  /** The world's own clock: 0 is dawn, 6000 noon, 13000 dusk. */
  const clock = $derived.by(() => {
    const t = ((hud?.ticks ?? 0) + 6000) % 24000;
    const h = Math.floor(t / 1000);
    const m = Math.floor(((t % 1000) / 1000) * 60);
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
  });
  const night = $derived((hud?.ticks ?? 0) > 13000 && (hud?.ticks ?? 0) < 23000);
  /** A short word for a slot, since there is no room for "Diamond Pickaxe" under a 40px square. */
  const short = (s: Slot) => (s ? s.name.replace(/^(Block of|Raw) /, "") : "");
  /** Two letters to stand for an item that has no picture. */
  const mark = (s: Slot) =>
    s ? s.name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => [...w][0]).join("").toUpperCase() : "";
  const chatLines = $derived((hud?.chat ?? []).slice(chatting ? -14 : -7));
  const hasEffect = (n: string) => !!hud?.effects?.some((e) => e.name.toLowerCase() === n);
  /** Hearts as the game draws them: poisoned green, withered black, a hardcore world's with eyes. */
  const heartKind = $derived(hasEffect("poison") ? "poisoned_" : hasEffect("wither") ? "withered_" : "");
  const heart = (fill: "full" | "half") => tex(`gui/sprites/hud/heart/${heartKind}${hud?.hardcore ? "hardcore_" : ""}${fill}.png`);
  const heartBox = $derived(tex(`gui/sprites/hud/heart/container${hud?.hardcore ? "_hardcore" : ""}.png`));
  const hungry = $derived(hasEffect("hunger") ? "_hunger" : "");
  const roman = (n: number) => ["", "", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"][n] ?? String(n);
  const timeLeft = (s: number | null) =>
    s == null ? "∞" : s >= 3600 ? `${Math.floor(s / 3600)}h` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  /** Green when new, through yellow, to red when about to break, as the game colours a wear bar. */
  const wearColour = (left: number) => `hsl(${Math.round(left * 120)} 85% 52%)`;
  /** The game's five bars for a connection. */
  const pingBars = (ms: number) => (ms <= 0 ? 0 : ms < 150 ? 5 : ms < 300 ? 4 : ms < 600 ? 3 : ms < 1000 ? 2 : 1);
  const BOSS: Record<string, string> = {
    pink: "#ec5fb4", blue: "#4a9cf0", red: "#ec4a4a", green: "#5fd068", yellow: "#f0d04a", purple: "#a55ff0", white: "#f2f2f2",
  };
  const bag = $derived.by(() => {
    const main = Array.from({ length: 27 }, (_, i) => hud?.carried.find((s) => s.slot === 9 + i) ?? null);
    return { main, hotbar: hud?.hotbar ?? [] };
  });
  const lowHealth = $derived(!!hud && hud.health > 0 && hud.health <= 4);
  const KEY_HINTS: [string, string][] = [
    ["WASD", "move"], ["Space", "jump"], ["Shift", "sneak"], ["Ctrl", "sprint"], ["Click", "hit"],
    ["Right click", "use"], ["1-9", "hotbar"], ["Q", "drop"], ["F", "swap"], ["E", "bag"], ["T", "chat"],
    ["Tab", "players"], ["F3", "info"], ["F5", "view"], ["Esc", "free the mouse"],
  ];
</script>

{#snippet item(s: Slot)}
  {#if s}
    {#if s.icon && !broken[s.icon]}
      <img class="it-pic" src={tex(s.icon)} alt="" draggable="false"
           onerror={() => (broken = { ...broken, [s.icon as string]: true })} />
    {:else}
      <span class="it-mark">{mark(s)}</span>
    {/if}
    {#if s.ench}<span class="it-glint"></span>{/if}
    {#if s.count > 1}<span class="it-n">{s.count}</span>{/if}
    {#if s.left != null && s.left < 1}
      <span class="it-wear"><i style="width: {Math.round(s.left * 100)}%; background: {wearColour(s.left)}"></i></span>
    {/if}
  {/if}
{/snippet}

<div class="wv" class:is-full={full}>
  <div class="wv-bar">
    <Segmented label="View" bind:value={mode} options={[
      { id: "eyes", label: "Its eyes" },
      { id: "above", label: "From above" },
    ]} />
    <span class="wv-note">
      {#if driving}<i class="wv-live-dot"></i>You're playing{:else}{ready ? (version ? `Live, ${version}` : "Live") : "Waiting for it to be in a world"}{/if}
    </span>
    {#if driving}
      <button class="wv-take is-on" onclick={letGo}>
        <Icon name="undo" size={13} />Let go
      </button>
    {:else}
      <button class="wv-take" onclick={takeControl} disabled={!ready || taking}>
        <Icon name="keyboard" size={13} />{taking ? "Taking over" : "Take control"}
      </button>
    {/if}
    <div class="wv-tools">
      <button class="wv-tool" class:is-on={showThoughts} onclick={() => { play("tap"); showThoughts = !showThoughts; }}
              disabled={!ready} title="What it is thinking" aria-label="What it is thinking" aria-pressed={showThoughts}>
        <Icon name="sparkle" size={14} />
      </button>
      <button class="wv-tool" class:is-on={showChat} onclick={() => { play("tap"); showChat = !showChat; }}
              disabled={!ready} title="Its chat" aria-label="Its chat" aria-pressed={showChat}>
        <Icon name="chats" size={14} />
      </button>
      <button class="wv-tool" class:is-on={showBag} onclick={toggleBag}
              disabled={!ready} title="What it is carrying (E)" aria-label="What it is carrying" aria-pressed={showBag}>
        <Icon name="layers" size={14} />
      </button>
      <button class="wv-tool" class:is-on={showTab} onclick={() => { play("tap"); showTab = !showTab; }}
              disabled={!ready} title="Who is on the server (Tab)" aria-label="Players" aria-pressed={showTab}>
        <Icon name="accounts" size={14} />
      </button>
      <button class="wv-tool" class:is-on={showDebug} onclick={toggleDebug}
              disabled={!ready} title="Debug screen (F3)" aria-label="Debug screen" aria-pressed={showDebug}>
        <Icon name="terminal" size={14} />
      </button>
      <button class="wv-tool" onclick={screenshot} disabled={!ready} title="Save a picture (F2)" aria-label="Save a picture">
        <Icon name="download" size={14} />
      </button>
      {#if !full}
        <button class="wv-tool" onclick={popOut} disabled={!ready} title="In a window of its own" aria-label="In a window">
          <Icon name="external" size={14} />
        </button>
      {/if}
      <button class="wv-tool" onclick={fullscreen} disabled={!ready} title="Full screen" aria-label="Full screen">
        <Icon name="expand" size={14} />
      </button>
    </div>
  </div>

  <div class="wv-stage" bind:this={stage}>
    <div class="wv-frame" class:is-driving={driving}>
      {#if ready}
        {#key src}
          <iframe bind:this={frameEl} {src} title={`What ${name || "it"} sees`} allow="fullscreen"></iframe>
        {/key}

        {#if hud && !hideHud}
          <!-- ── Over the picture, the way a player has it ─────────────────── -->
          <!-- Nothing here takes the pointer: the world underneath can still be dragged about. -->
          <div class="hud" class:is-big={full}>
            <!-- Where it is, and when. -->
            <div class="hud-where">
              <span class="hud-chip"><b>{hud.at.x}</b> <b>{hud.at.y}</b> <b>{hud.at.z}</b></span>
              {#if hud.where}<span class="hud-chip is-dim">{hud.where.replace(/_/g, " ")}</span>{/if}
              <span class="hud-chip is-dim">
                <Icon name={night ? "eyeOff" : "sparkle"} size={10} />{clock}
                {#if hud.raining}· rain{/if}
              </span>
              {#if hud.near.length}<span class="hud-chip is-dim">{hud.near.length} nearby</span>{/if}
              {#if hud.mode && hud.mode !== "survival"}<span class="hud-chip is-dim">{hud.mode}</span>{/if}
            </div>

            <!-- Its debug screen, F3. -->
            {#if showDebug && hud.debug}
              {@const d = hud.debug}
              <div class="hud-debug" transition:fade={{ duration: 120 }}>
                <span>Minecraft {d.version}{d.brand ? ` (${d.brand})` : ""}</span>
                <span>{fps || "-"} fps · {d.tps ?? "-"} tps · {d.ping} ms</span>
                <span class="gap">XYZ: {d.xyz.map((n) => n.toFixed(3)).join(" / ")}</span>
                <span>Block: {d.block.join(" ")}</span>
                <span>Chunk: {d.inChunk.join(" ")} in {d.chunk.join(" ")}</span>
                <span>Facing: {d.facing} (Towards {d.toward}) ({d.yaw.toFixed(1)} / {d.pitch.toFixed(1)})</span>
                {#if d.biome}<span>Biome: minecraft:{d.biome}</span>{/if}
                {#if d.light != null}<span>Light: {Math.max(d.light, d.sky ?? 0)} ({d.sky ?? 0} sky, {d.light} block)</span>{/if}
                <span class="gap">Speed: {d.speed} m/s{d.ground ? ", on the ground" : ", in the air"}</span>
                {#if d.looking}<span>Looking at: {d.looking.name} {d.looking.at.join(" ")}</span>{/if}
                {#if d.target}<span>Targeted: {d.target.name}, {d.target.away} m</span>{/if}
                <span class="gap">Entities: {d.entities} · Players: {d.players}</span>
                <span>Difficulty: {d.difficulty || "-"} · Day {hud.day}</span>
                <span>Memory: {d.memory} MB · AI {hud.driving ? "paused" : "playing"}</span>
                {#if d.net?.sent?.length}<span class="gap">Sent: {d.net.sent.join(" · ")}</span>{/if}
                {#if d.net?.got?.length}<span>Got: {d.net.got.join(" · ")}</span>{/if}
              </div>
            {/if}

            <!-- Boss bars, top centre. -->
            {#if hud.bossBars?.length}
              <div class="hud-boss">
                {#each hud.bossBars as b, i (i)}
                  <div class="boss">
                    {#if b.title}<span class="boss-title">{b.title}</span>{/if}
                    <span class="boss-track"><i style="width: {b.health * 100}%; --c: {BOSS[b.color] ?? BOSS.pink}"></i></span>
                  </div>
                {/each}
              </div>
            {/if}

            <!-- What is on it, top right: good ones first, as the game puts them. -->
            {#if hud.effects?.length}
              <div class="hud-effects">
                {#each [...hud.effects].sort((a, b) => Number(b.good) - Number(a.good)) as e (e.id)}
                  <span class="fx" class:is-bad={!e.good} title="{e.name} {roman(e.level)}">
                    {#if e.icon && !broken[e.icon]}
                      <img src={tex(e.icon)} alt="" onerror={() => (broken = { ...broken, [e.icon]: true })} />
                    {:else}
                      <b>{e.name.slice(0, 2)}</b>
                    {/if}
                    <i>{e.level > 1 ? roman(e.level) : timeLeft(e.left)}</i>
                  </span>
                {/each}
              </div>
            {/if}

            <!-- The server's board, down the right. -->
            {#if hud.sidebar && (hud.sidebar.title || hud.sidebar.rows.length)}
              <div class="hud-side">
                {#if hud.sidebar.title}<span class="side-title">{hud.sidebar.title}</span>{/if}
                {#each hud.sidebar.rows as r, i (i)}
                  <span class="side-row"><b>{r.text}</b>{#if r.fixed}<i>{r.fixed}</i>{:else if r.value != null && Number.isFinite(r.value)}<i>{r.value}</i>{/if}</span>
                {/each}
              </div>
            {/if}

            <!-- A title, in the middle of the screen. -->
            {#if hud.title && (hud.title.text || hud.title.sub)}
              {#key hud.title.at}
                <div class="hud-title" style="--for: {hud.title.for}ms">
                  {#if hud.title.text}<span class="t-main">{hud.title.text}</span>{/if}
                  {#if hud.title.sub}<span class="t-sub">{hud.title.sub}</span>{/if}
                </div>
              {/key}
            {/if}

            <!-- Where the game's crosshair is, while it is played. -->
            {#if driving}<span class="hud-cross" aria-hidden="true"></span>{/if}

            <!-- What it is thinking, under where it is. Not over the debug screen, which takes that side. -->
            {#if showThoughts && !showDebug}
              <div class="hud-thought"><LiveThought source={account} variant="overlay" /></div>
            {/if}

            <!-- What it has heard. Where a player's chat is, and shaped like one. -->
            {#if (showChat || chatting) && chatLines.length}
              <div class="hud-chat" class:is-open={chatting}>
                {#each chatLines as line (line.at + line.text)}
                  <span class="hud-chat-line">{line.text}</span>
                {/each}
              </div>
            {/if}

            <!-- Hearts, food, armour and air, the bar of experience, then the nine slots, as on a real screen. -->
            <div class="hud-bottom">
              {#if hud.overHotbar}<span class="hud-over">{hud.overHotbar}</span>{/if}
              {#if hud.sprites}
                <div class="hud-meters">
                  <span class="hud-meter">
                    {#if (hud.armourPoints ?? 0) > 0}
                      {#each Array(10) as _, i}
                        {@const v = (hud.armourPoints ?? 0) / 2 - i}
                        <img class="spr" alt="" src={tex(`gui/sprites/hud/armor_${v >= 1 ? "full" : v >= 0.5 ? "half" : "empty"}.png`)} />
                      {/each}
                    {/if}
                  </span>
                  <span class="hud-meter is-right">
                    {#if bubbles > 0 && bubbles < 10}
                      {#each Array(10) as _, i}
                        <img class="spr" alt="" src={tex(`gui/sprites/hud/${bubbles - i > 0 ? "air" : "air_empty"}.png`)} />
                      {/each}
                    {/if}
                  </span>
                </div>
                <div class="hud-meters">
                  <span class="hud-meter" class:is-low={lowHealth} title="{hud.health} of 20">
                    {#each Array(10) as _, i}
                      {@const v = hud.health / 2 - i}
                      <span class="spr-stack" style="--i: {i}">
                        <img class="spr" alt="" src={heartBox} />
                        {#if v >= 1}<img class="spr" alt="" src={heart("full")} />
                        {:else if v >= 0.5}<img class="spr" alt="" src={heart("half")} />{/if}
                      </span>
                    {/each}
                  </span>
                  <span class="hud-meter is-right" title="{hud.food} of 20">
                    {#each Array(10) as _, i}
                      {@const v = hud.food / 2 - i}
                      <span class="spr-stack">
                        <img class="spr" alt="" src={tex(`gui/sprites/hud/food_empty${hungry}.png`)} />
                        {#if v >= 1}<img class="spr" alt="" src={tex(`gui/sprites/hud/food_full${hungry}.png`)} />
                        {:else if v >= 0.5}<img class="spr" alt="" src={tex(`gui/sprites/hud/food_half${hungry}.png`)} />{/if}
                      </span>
                    {/each}
                  </span>
                </div>
              {:else}
                <div class="hud-meters">
                  <span class="hud-meter" title="{hud.health} of 20">
                    {#each Array(10) as _, i}
                      <i class="pip is-heart" class:is-half={hearts(hud.health) - i > 0 && hearts(hud.health) - i < 1}
                         class:is-off={hearts(hud.health) - i <= 0}></i>
                    {/each}
                  </span>
                  <span class="hud-meter is-right" title="{hud.food} of 20">
                    {#each Array(10) as _, i}
                      <i class="pip is-food" class:is-half={hearts(hud.food) - i > 0 && hearts(hud.food) - i < 1}
                         class:is-off={hearts(hud.food) - i <= 0}></i>
                    {/each}
                  </span>
                </div>
                {#if bubbles > 0 && bubbles < 10}
                  <div class="hud-meters">
                    <span class="hud-meter"></span>
                    <span class="hud-meter is-right">
                      {#each Array(10) as _, i}<i class="pip is-air" class:is-off={bubbles - i <= 0}></i>{/each}
                    </span>
                  </div>
                {/if}
              {/if}
              {#if hud.xp && hud.mode !== "creative" && hud.mode !== "spectator"}
                <div class="hud-xp" title="Level {hud.xp.level}">
                  <i style="width: {hud.xp.progress * 100}%"></i>
                  {#if hud.xp.level > 0}<b>{hud.xp.level}</b>{/if}
                </div>
              {/if}
              <div class="hud-row">
                {#if hud.offhand}
                  <span class="hud-slot is-off" title="Other hand: {hud.offhand.name}">{@render item(hud.offhand)}</span>
                {/if}
                <div class="hud-bar">
                  {#each hud.hotbar as s, i (i)}
                    <button class="hud-slot" class:is-held={i === hud.held} tabindex="-1" disabled={!driving}
                            onclick={() => pickSlot(i)}
                            title={s ? `${s.name}${s.count > 1 ? ` x${s.count}` : ""}` : "empty"}>
                      {@render item(s)}
                    </button>
                  {/each}
                </div>
              </div>
              {#if hud.hotbar[hud.held]}
                {#key hud.held}
                  <span class="hud-held" in:fade={{ duration: 120 }}>{short(hud.hotbar[hud.held])}</span>
                {/key}
              {/if}
            </div>

            <!-- Everyone on the server, when you ask for it (Tab). -->
            {#if showTab}
              <div class="hud-tab" transition:fade={{ duration: 120 }}>
                {#if hud.tabTop}<p class="tab-edge">{hud.tabTop}</p>{/if}
                {#if hud.players?.length}
                  <div class="tab-grid">
                    {#each hud.players as p (p.name)}
                      <span class="tab-row">
                        <b>{p.shown}</b>
                        {#if p.away != null}<em>{p.away}m</em>{/if}
                        <i class="ping" data-bars={pingBars(p.ping)} title="{p.ping} ms"><s></s><s></s><s></s><s></s><s></s></i>
                      </span>
                    {/each}
                  </div>
                {:else}
                  <p class="tab-edge">Nobody else is listed.</p>
                {/if}
                {#if hud.tabBottom}<p class="tab-edge">{hud.tabBottom}</p>{/if}
              </div>
            {/if}

            <!-- A chest, a furnace, anything it has open. -->
            {#if hud.window}
              <div class="hud-bag is-window" transition:scale={{ start: 0.96, duration: 160 }}>
                <div class="hud-bag-head">
                  <Icon name="inbox" size={12} />{hud.window.title || "Open"}
                  <button class="bag-x" onclick={closePanels} aria-label="Close"><Icon name="close" size={12} /></button>
                </div>
                <div class="hud-bag-grid">
                  {#each hud.window.slots as s, i (i)}
                    <button class="hud-slot" tabindex="-1" title={tip(s)}
                            onclick={(e) => clickSlot(e, i, false)} oncontextmenu={(e) => clickSlot(e, i, false, 1)}>
                      {@render item(s)}
                    </button>
                  {/each}
                </div>
                {#if hud.window.cursor}
                  <p class="hud-bag-none">Holding {hud.window.cursor.name}. Click a slot to put it down.</p>
                {/if}
                <div class="hud-bag-head">Its inventory</div>
                <div class="hud-bag-grid">
                  {#each [...bag.main, ...bag.hotbar] as s, i (i)}
                    <button class="hud-slot" tabindex="-1" title={tip(s)}
                            onclick={(e) => clickSlot(e, 9 + i, true)} oncontextmenu={(e) => clickSlot(e, 9 + i, true, 1)}>
                      {@render item(s)}
                    </button>
                  {/each}
                </div>
                <p class="hud-bag-none">{driving ? "Click to use. Shift-click moves it across. Right-click for half." : "Take control to use it."}</p>
              </div>
            {:else if showBag}
              <!-- What it is carrying, when you ask for it (E). -->
              <div class="hud-bag" transition:scale={{ start: 0.96, duration: 160 }}>
                <div class="hud-bag-head">
                  <Icon name="layers" size={12} />Carrying
                  <span class="hud-bag-n">{hud.carried.length}</span>
                  <button class="bag-x" onclick={closePanels} aria-label="Close"><Icon name="close" size={12} /></button>
                </div>
                <div class="bag-top">
                  <div class="bag-worn">
                    {#each hud.armour as s, i (i)}
                      <button class="hud-slot" tabindex="-1" onclick={() => useFromBag(s)}
                              title={s?.name ?? ["Head", "Body", "Legs", "Feet"][i]}>
                        {#if s}{@render item(s)}{:else}<span class="slot-ghost">{["H", "B", "L", "F"][i]}</span>{/if}
                      </button>
                    {/each}
                    <span class="hud-slot" title={hud.offhand?.name ?? "Other hand"}>
                      {#if hud.offhand}{@render item(hud.offhand)}{:else}<span class="slot-ghost">O</span>{/if}
                    </span>
                  </div>
                  <div class="bag-stats">
                    <span><b>{hud.health}</b> health</span>
                    <span><b>{hud.food}</b> food</span>
                    <span><b>{hud.armourPoints ?? 0}</b> armour</span>
                    <span><b>{hud.xp?.level ?? 0}</b> level</span>
                  </div>
                </div>
                <div class="hud-bag-grid">
                  {#each bag.main as s, i (i)}
                    <button class="hud-slot" tabindex="-1" onclick={() => useFromBag(s)} title={s?.name ?? "empty"}>
                      {@render item(s)}
                    </button>
                  {/each}
                </div>
                <div class="hud-bag-grid is-hotbar">
                  {#each bag.hotbar as s, i (i)}
                    <button class="hud-slot" class:is-held={i === hud.held} tabindex="-1" onclick={() => useFromBag(s)}
                            title={s?.name ?? "empty"}>
                      {@render item(s)}
                    </button>
                  {/each}
                </div>
                <p class="hud-bag-none">
                  {hud.carried.length || bag.hotbar.some(Boolean) ? (driving ? "Click one to hold it, or put it on." : "Take control to use them.") : "Its bag is empty."}
                </p>
              </div>
            {/if}

            {#if hud.dead}
              <div class="hud-dead" transition:fade={{ duration: 200 }}>
                <span class="dead-title">You died!</span>
                <button class="wv-take" onclick={respawn}>Respawn</button>
              </div>
            {/if}
          </div>
        {/if}

        <!-- While it is played, this takes the mouse: the first click locks it in, as the game does. -->
        {#if driving}
          <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
          <div class="wv-cap" bind:this={cap} role="application" aria-label="Play {who}"
               class:is-locked={locked}
               onmousedown={onCapDown} oncontextmenu={(e) => e.preventDefault()}
               onpointerdown={capTouchDown} onpointermove={capTouchMove} onpointerup={capTouchUp}
               onpointercancel={capTouchUp}>
            {#if !locked && !touch && !chatting && !showBag && !hud?.window}
              <div class="cap-hint" transition:fade={{ duration: 140 }}>
                <Icon name="play" size={18} />
                <b>Click to play</b>
                <span>Esc frees the mouse</span>
              </div>
            {/if}
          </div>
          {#if touch}
            <div class="pad-stick" onpointerdown={stickDown} onpointermove={stickMove} onpointerup={stickUp}
                 onpointercancel={stickUp} role="presentation">
              <span class="pad-knob" style="transform: translate({stick.x}px, {stick.y}px)"></span>
            </div>
            <div class="pad-keys">
              <button class="pad-key" class:is-on={mouse.attack}
                      onpointerdown={() => holdButton("attack", true)} onpointerup={() => holdButton("attack", false)}
                      onpointercancel={() => holdButton("attack", false)}>Hit</button>
              <button class="pad-key" class:is-on={mouse.use}
                      onpointerdown={() => holdButton("use", true)} onpointerup={() => holdButton("use", false)}
                      onpointercancel={() => holdButton("use", false)}>Use</button>
              <button class="pad-key" class:is-on={keys.jump}
                      onpointerdown={() => holdKey("jump", true)} onpointerup={() => holdKey("jump", false)}
                      onpointercancel={() => holdKey("jump", false)}>Jump</button>
              <button class="pad-key" class:is-on={keys.sneak} onclick={() => holdKey("sneak", !keys.sneak)}>Sneak</button>
              <button class="pad-key" onclick={toggleBag}>Bag</button>
              <button class="pad-key" onclick={() => openChat("")}>Chat</button>
            </div>
          {/if}
        {/if}

        {#if notice}
          <span class="wv-notice" transition:fade={{ duration: 160 }}>{notice}</span>
        {/if}
      {:else}
        <div class="wv-empty">
          <Icon name="minecraft" size={28} />
          <span>Nothing to watch yet.</span>
          <span class="wv-sub">It shows once {name || "it"} is in a world.</span>
        </div>
      {/if}
    </div>

    {#if ready}
      <!-- Its chat, typed into as it: words, or a /command. -->
      <form class="wv-say" class:is-open={chatting} onsubmit={sendChat}>
        <Icon name="chats" size={14} />
        <input bind:this={chatBox} bind:value={chatText} maxlength={256} spellcheck="false" autocomplete="off"
               placeholder={driving ? "Press T to chat, or / for a command" : `Say something as ${who}, or a /command`}
               onfocus={() => (chatting = true)} onblur={() => (chatting = false)} onkeydown={chatKeys} />
        <button type="submit" class="wv-send" disabled={!chatText.trim() || sending} aria-label="Send">
          <Icon name="send" size={13} />
        </button>
      </form>
    {/if}
  </div>

  {#if driving && !touch}
    <div class="wv-keys" transition:fade={{ duration: 160 }}>
      {#each KEY_HINTS as [k, what] (k)}
        <span class="wv-key" class:is-on={(k === "WASD" && (keys.forward || keys.back || keys.left || keys.right))
                                       || (k === "Space" && keys.jump) || (k === "Shift" && keys.sneak)
                                       || (k === "Ctrl" && keys.sprint) || (k === "Click" && mouse.attack)
                                       || (k === "Right click" && mouse.use)}>
          <kbd>{k}</kbd>{what}
        </span>
      {/each}
    </div>
  {:else if error}
    <p class="wv-error"><Icon name="info" size={12} /> {error}</p>
  {:else}
    <p class="wv-hint">{mode === "above" ? "Over its shoulder, following it about." : "What it sees, as it moves."}
      It shows the world a few chunks around it.</p>
  {/if}
</div>

<style>
  .wv { display: flex; flex-direction: column; gap: 10px; }
  .wv.is-full { height: 100%; }
  .wv-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 10px; }
  .wv-note {
    display: inline-flex; align-items: center; gap: 6px; margin-left: auto;
    font-size: 11.5px; color: var(--color-faint);
  }
  .wv-live-dot {
    width: 7px; height: 7px; border-radius: 50%; background: #ff5a5a;
    box-shadow: 0 0 0 3px rgb(255 90 90 / 0.18), 0 0 10px rgb(255 90 90 / 0.6);
    animation: wv-beat 1.6s ease-in-out infinite;
  }
  @keyframes wv-beat { 50% { opacity: 0.45; } }
  :root[data-motion="off"] .wv-live-dot { animation: none; }

  .wv-take {
    display: inline-flex; align-items: center; gap: 6px; height: 30px; border-radius: 10px; padding: 0 12px;
    font-size: 12px; font-weight: 650; color: var(--color-bg);
    background: linear-gradient(180deg, color-mix(in srgb, var(--color-accent) 92%, #fff), var(--color-accent));
    box-shadow: 0 6px 18px -8px color-mix(in srgb, var(--color-accent) 80%, transparent),
                inset 0 1px 0 rgb(255 255 255 / 0.25);
    transition: transform 0.18s var(--spring, ease), filter 0.15s ease, opacity 0.15s ease;
  }
  .wv-take:hover:not(:disabled) { transform: translateY(-1px); filter: brightness(1.06); }
  .wv-take:active:not(:disabled) { transform: translateY(0) scale(0.98); }
  .wv-take:disabled { opacity: 0.45; }
  .wv-take.is-on {
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 18%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 45%, transparent);
  }

  .wv-tools { display: flex; gap: 4px; }
  .wv-tool {
    display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px;
    color: var(--color-muted); background: rgb(255 255 255 / 0.05);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .wv-tool:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.1); }
  .wv-tool:disabled { opacity: 0.4; }
  .wv-tool.is-on { color: var(--color-ink); background: color-mix(in srgb, var(--color-accent) 24%, transparent); }

  .wv-stage { position: relative; display: flex; flex-direction: column; gap: 8px; }
  .wv.is-full .wv-stage { flex: 1; min-height: 0; }
  .wv-stage:fullscreen { gap: 0; background: #07060a; }

  .wv-frame {
    position: relative;
    aspect-ratio: 16 / 9;
    overflow: hidden;
    border-radius: 14px;
    background: #0d0a0d;
    container-type: inline-size;
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent),
                0 18px 40px -22px rgb(0 0 0 / 0.7);
    transition: box-shadow 0.25s ease;
  }
  .wv-frame.is-driving {
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 55%, transparent),
                0 0 0 3px color-mix(in srgb, var(--color-accent) 14%, transparent),
                0 18px 46px -20px color-mix(in srgb, var(--color-accent) 45%, rgb(0 0 0 / 0.7));
  }
  .wv.is-full .wv-frame { flex: 1; aspect-ratio: auto; min-height: 0; }
  .wv-stage:fullscreen .wv-frame { flex: 1; border-radius: 0; aspect-ratio: auto; }
  .wv-frame iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }
  .wv-empty {
    position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 6px; color: var(--color-muted); font-size: 13px;
  }
  .wv-empty :global(svg) { color: #7cbd4a; opacity: 0.8; margin-bottom: 4px; }
  .wv-sub { font-size: 11.5px; color: var(--color-faint); }
  .wv-hint, .wv-error { font-size: 11.5px; color: var(--color-faint); }
  .wv-error { display: flex; align-items: center; gap: 6px; color: var(--color-warn); }

  /* ── The chat line ─────────────────────────────────────────────────────── */
  .wv-say {
    display: flex; align-items: center; gap: 8px; border-radius: 12px; padding: 4px 4px 4px 12px;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
    transition: box-shadow 0.18s ease, background-color 0.18s ease;
  }
  .wv-say.is-open, .wv-say:focus-within {
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 7%, rgb(255 255 255 / 0.03));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 50%, transparent),
                0 0 0 3px color-mix(in srgb, var(--color-accent) 12%, transparent);
  }
  .wv-stage:fullscreen .wv-say { margin: 8px; }
  .wv-say input {
    flex: 1; min-width: 0; height: 30px; border: 0; outline: 0; background: transparent;
    font-size: 13px; color: var(--color-ink);
  }
  .wv-say input::placeholder { color: var(--color-faint); }
  .wv-send {
    display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px;
    color: var(--color-bg); background: var(--color-accent);
    transition: opacity 0.15s ease, transform 0.15s ease;
  }
  .wv-send:disabled { opacity: 0.25; }
  .wv-send:not(:disabled):hover { transform: scale(1.05); }

  .wv-keys { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 11px; color: var(--color-faint); }
  .wv-key { display: inline-flex; align-items: center; gap: 4px; transition: color 0.12s ease; }
  .wv-key kbd {
    border-radius: 6px; padding: 1px 5px; font: inherit; font-size: 10.5px; font-weight: 650; color: var(--color-muted);
    background: rgb(255 255 255 / 0.06); box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08);
    transition: color 0.12s ease, background-color 0.12s ease, box-shadow 0.12s ease;
  }
  .wv-key.is-on { color: var(--color-ink); }
  .wv-key.is-on kbd {
    color: var(--color-bg); background: var(--color-accent);
    box-shadow: 0 0 10px color-mix(in srgb, var(--color-accent) 60%, transparent);
  }

  /* ── Taking the mouse ─────────────────────────────────────────────────── */
  .wv-cap { position: absolute; inset: 0; z-index: 3; cursor: pointer; touch-action: none; }
  .wv-cap.is-locked { cursor: none; }
  .cap-hint {
    position: absolute; top: 50%; left: 50%; display: flex; flex-direction: column; align-items: center; gap: 4px;
    border-radius: 16px; padding: 14px 22px; transform: translate(-50%, -50%);
    color: #fff; background: rgb(10 9 14 / 0.62); backdrop-filter: blur(10px);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.14), 0 20px 50px -20px rgb(0 0 0 / 0.9),
                0 0 40px -10px color-mix(in srgb, var(--color-accent) 50%, transparent);
    pointer-events: none;
  }
  .cap-hint b { font-size: 14px; }
  .cap-hint span { font-size: 11px; color: rgb(255 255 255 / 0.6); }
  .cap-hint :global(svg) { color: var(--color-accent); }

  .wv-notice {
    position: absolute; bottom: 14px; left: 50%; z-index: 6; transform: translateX(-50%);
    border-radius: 10px; padding: 6px 12px; font-size: 12px; font-weight: 600; color: #fff;
    background: rgb(10 9 14 / 0.78); backdrop-filter: blur(8px);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.12); pointer-events: none; white-space: nowrap;
  }

  /* ── On a phone ───────────────────────────────────────────────────────── */
  .pad-stick {
    position: absolute; bottom: 18px; left: 18px; z-index: 4; display: grid; width: 112px; height: 112px;
    place-items: center; border-radius: 50%; touch-action: none;
    background: radial-gradient(circle, rgb(255 255 255 / 0.1), rgb(255 255 255 / 0.04));
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.16);
    backdrop-filter: blur(6px);
  }
  .pad-knob {
    width: 44px; height: 44px; border-radius: 50%;
    background: color-mix(in srgb, var(--color-accent) 70%, #fff 10%);
    box-shadow: 0 6px 16px -6px rgb(0 0 0 / 0.7), 0 0 18px color-mix(in srgb, var(--color-accent) 50%, transparent);
  }
  .pad-keys {
    position: absolute; right: 14px; bottom: 14px; z-index: 4; display: grid; grid-template-columns: repeat(2, 58px);
    gap: 8px;
  }
  .pad-key {
    height: 44px; border-radius: 14px; font-size: 12px; font-weight: 700; color: #fff; touch-action: none;
    background: rgb(10 9 14 / 0.5); backdrop-filter: blur(6px); box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.16);
  }
  .pad-key.is-on { color: var(--color-bg); background: var(--color-accent); }

  /* ── The screen a player would have ─────────────────────────────────────
     Over the picture, never in front of it: the pointer goes straight through
     to the world, which can still be dragged around. */
  .hud {
    --u: 2px;                      /* one of the game's pixels */
    position: absolute; inset: 0; pointer-events: none;
    font-variant-numeric: tabular-nums;
    text-shadow: 0 1px 2px rgb(0 0 0 / 0.85);
  }
  @container (max-width: 640px) { .hud { --u: 1.5px; } }
  @container (min-width: 1200px) { .hud { --u: 2.5px; } }
  .hud-chip {
    display: inline-flex; align-items: center; gap: 5px; border-radius: 8px; padding: 3px 7px;
    font-size: 11px; font-weight: 600; color: #fff; background: rgb(12 10 16 / 0.52);
    backdrop-filter: blur(6px);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.1);
  }
  .hud-chip.is-dim { color: rgb(255 255 255 / 0.74); font-weight: 500; text-transform: capitalize; }
  .hud-chip b { font-weight: 700; }
  .hud-where { position: absolute; top: 10px; left: 10px; display: flex; max-width: 46%; flex-wrap: wrap; gap: 5px; }

  .hud-debug {
    position: absolute; top: 40px; left: 10px; display: flex; max-width: 52%; flex-direction: column; gap: 1px;
    font: 500 10.5px/1.45 ui-monospace, "Cascadia Mono", Consolas, monospace; color: #f2f2f2;
    text-shadow: none;
  }
  .hud-debug span {
    width: fit-content; max-width: 100%; border-radius: 4px; padding: 0 5px; overflow: hidden;
    background: rgb(10 9 14 / 0.62); text-overflow: ellipsis; white-space: nowrap;
  }
  .hud-debug .gap { margin-top: 5px; }

  .hud-boss {
    position: absolute; top: 10px; left: 50%; display: flex; width: min(46%, 380px); flex-direction: column; gap: 6px;
    transform: translateX(-50%);
  }
  .boss { display: flex; flex-direction: column; align-items: center; gap: 3px; }
  .boss-title { max-width: 100%; overflow: hidden; font-size: 11.5px; font-weight: 600; color: #fff; text-overflow: ellipsis; white-space: nowrap; }
  .boss-track {
    width: 100%; height: 6px; overflow: hidden; border-radius: 999px; background: rgb(10 9 14 / 0.6);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.1);
  }
  .boss-track i {
    display: block; height: 100%; border-radius: inherit; background: var(--c);
    box-shadow: 0 0 10px var(--c); transition: width 0.4s ease;
  }

  .hud-effects {
    position: absolute; top: 10px; right: 10px; display: flex; max-width: 40%; flex-wrap: wrap; justify-content: flex-end;
    gap: 4px;
  }
  .fx {
    display: flex; width: calc(var(--u) * 15); flex-direction: column; align-items: center; gap: 1px;
    border-radius: 9px; padding: 4px 2px 3px; background: rgb(12 10 16 / 0.55); backdrop-filter: blur(6px);
    box-shadow: inset 0 0 0 1px rgb(120 200 255 / 0.28);
  }
  .fx.is-bad { box-shadow: inset 0 0 0 1px rgb(255 110 110 / 0.32); }
  .fx img { width: calc(var(--u) * 9); height: calc(var(--u) * 9); image-rendering: pixelated; }
  .fx b { font-size: 10px; color: #fff; }
  .fx i { font-size: 9px; font-style: normal; font-weight: 700; color: rgb(255 255 255 / 0.85); }

  .hud-side {
    position: absolute; top: 50%; right: 10px; display: flex; min-width: 110px; max-width: 34%; flex-direction: column;
    gap: 1px; border-radius: 10px; padding: 6px 9px; transform: translateY(-50%);
    background: rgb(10 9 14 / 0.5); backdrop-filter: blur(6px); box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08);
  }
  .side-title { margin-bottom: 3px; font-size: 11.5px; font-weight: 700; color: #fff; text-align: center; }
  .side-row { display: flex; gap: 10px; font-size: 10.5px; color: rgb(255 255 255 / 0.92); }
  .side-row b { min-width: 0; overflow: hidden; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
  .side-row i { margin-left: auto; font-style: normal; color: #ff7070; }

  .hud-title {
    position: absolute; top: 34%; left: 50%; display: flex; width: 90%; flex-direction: column; align-items: center;
    gap: 6px; transform: translate(-50%, -50%); text-align: center;
    animation: hud-title var(--for, 3500ms) ease forwards;
  }
  @keyframes hud-title { 0% { opacity: 0; transform: translate(-50%, -46%) scale(0.96); } 8%, 82% { opacity: 1; transform: translate(-50%, -50%) scale(1); } 100% { opacity: 0; } }
  :root[data-motion="off"] .hud-title { animation: none; }
  .t-main {
    font-size: clamp(22px, 6cqw, 58px); font-weight: 800; line-height: 1.05; color: #fff; letter-spacing: 0.01em;
    text-shadow: 0 3px 0 rgb(0 0 0 / 0.35), 0 8px 30px rgb(0 0 0 / 0.6);
  }
  .t-sub { font-size: clamp(12px, 2.4cqw, 22px); font-weight: 600; color: rgb(255 255 255 / 0.9); }

  .hud-cross {
    position: absolute; top: 50%; left: 50%; width: 18px; height: 18px; transform: translate(-50%, -50%);
    mix-blend-mode: difference;
  }
  .hud-cross::before, .hud-cross::after { content: ""; position: absolute; background: #fff; }
  .hud-cross::before { top: 8px; left: 0; width: 18px; height: 2px; }
  .hud-cross::after { top: 0; left: 8px; width: 2px; height: 18px; }

  .hud-thought { position: absolute; top: 44px; left: 10px; width: min(44%, 400px); }
  @container (max-width: 640px) { .hud-thought { width: 76%; } }

  /* Chat where a player's is, bottom left, oldest fading out. */
  .hud-chat {
    position: absolute; bottom: calc(var(--u) * 52); left: 10px; display: flex; max-width: min(46%, 460px);
    flex-direction: column; gap: 2px;
  }
  .hud-chat-line {
    width: fit-content; max-width: 100%; border-radius: 7px; padding: 2px 7px;
    font-size: 11.5px; line-height: 1.45; color: #fff; background: rgb(12 10 16 / 0.5);
    overflow-wrap: anywhere;
  }
  /* Narrow (a phone, a small window): the bars below take the whole width, so the chat sits above them. */
  @container (max-width: 640px) {
    .hud-chat { bottom: calc(var(--u) * 46 + 70px); max-width: 76%; }
  }
  .hud-chat:not(.is-open) .hud-chat-line:nth-last-child(n + 6) { opacity: 0.45; }
  .hud-chat:not(.is-open) .hud-chat-line:nth-last-child(5) { opacity: 0.7; }
  .hud-chat.is-open .hud-chat-line { background: rgb(12 10 16 / 0.66); }

  /* ── Hearts, food, and the nine slots ─────────────────────────────────── */
  .hud-bottom {
    position: absolute; bottom: 10px; left: 50%; display: flex; flex-direction: column; align-items: center;
    gap: calc(var(--u) * 1.5); transform: translateX(-50%);
  }
  .hud-over { margin-bottom: 4px; font-size: 12px; font-weight: 600; color: #fff; white-space: nowrap; }
  .hud-meters { display: flex; width: calc(var(--u) * 182); justify-content: space-between; gap: 12px; }
  .hud-meter { display: flex; gap: 0; }
  .hud-meter.is-right { flex-direction: row-reverse; }
  .spr { display: block; width: calc(var(--u) * 9); height: calc(var(--u) * 9); margin-right: calc(var(--u) * -1); image-rendering: pixelated; filter: drop-shadow(0 1px 1px rgb(0 0 0 / 0.5)); }
  .hud-meter.is-right .spr { margin-right: 0; margin-left: calc(var(--u) * -1); }
  .spr-stack { position: relative; display: block; }
  .spr-stack .spr + .spr { position: absolute; top: 0; left: 0; filter: none; }
  .hud-meter.is-low .spr-stack { animation: hud-jiggle 0.36s steps(2) infinite; animation-delay: calc(var(--i, 0) * -0.11s); }
  @keyframes hud-jiggle { 50% { transform: translateY(calc(var(--u) * -1)); } }
  :root[data-motion="off"] .hud-meter.is-low .spr-stack { animation: none; }
  .pip {
    width: 9px; height: 9px; margin-right: 2px; border-radius: 2px;
    box-shadow: 0 1px 2px rgb(0 0 0 / 0.6);
  }
  .pip.is-heart { background: #e8443c; }
  .pip.is-food { background: #c08a3e; }
  .pip.is-air { background: #4fb6e8; border-radius: 50%; }
  .pip.is-half { opacity: 0.55; }
  .pip.is-off { background: rgb(255 255 255 / 0.16); box-shadow: none; }

  .hud-xp {
    position: relative; width: calc(var(--u) * 182); height: calc(var(--u) * 3.5); border-radius: 999px;
    background: rgb(10 9 14 / 0.62); box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08);
  }
  .hud-xp i {
    position: absolute; inset: 0 auto 0 0; display: block; border-radius: inherit;
    background: linear-gradient(90deg, #6fd84a, #b8f55a); box-shadow: 0 0 10px rgb(150 240 80 / 0.55);
    transition: width 0.4s ease;
  }
  .hud-xp b {
    position: absolute; bottom: 1px; left: 50%; transform: translateX(-50%);
    font-size: 12px; font-weight: 800; color: #9cff4a; line-height: 1;
    text-shadow: 0 0 2px #000, 0 1px 0 #000, 1px 0 0 #000, -1px 0 0 #000, 0 -1px 0 #000;
  }

  .hud-row { display: flex; align-items: center; gap: 8px; }
  .hud-bar {
    display: flex; gap: 3px; border-radius: 12px; padding: 3px;
    background: rgb(12 10 16 / 0.52); backdrop-filter: blur(6px);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.1), 0 10px 26px -14px rgb(0 0 0 / 0.8);
  }
  .hud-slot {
    position: relative; display: grid; width: calc(var(--u) * 18); height: calc(var(--u) * 18); place-items: center;
    border-radius: 8px; background: rgb(255 255 255 / 0.07);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06);
    transition: background-color 0.15s ease, box-shadow 0.15s ease, transform 0.18s var(--spring, ease);
  }
  .hud-slot:disabled { cursor: default; }
  .hud-slot.is-off { background: rgb(12 10 16 / 0.52); backdrop-filter: blur(6px); }
  .hud-slot.is-held {
    background: rgb(255 255 255 / 0.16);
    box-shadow: inset 0 0 0 2px rgb(255 255 255 / 0.85), 0 0 14px color-mix(in srgb, var(--color-accent) 55%, rgb(255 255 255 / 0.3));
    transform: translateY(-1px);
  }
  .it-pic { width: 72%; height: 72%; object-fit: cover; object-position: top; image-rendering: pixelated; filter: drop-shadow(0 1px 1px rgb(0 0 0 / 0.6)); }
  .it-mark { font-size: 11px; font-weight: 700; color: rgb(255 255 255 / 0.92); }
  .it-glint {
    position: absolute; inset: 14%; border-radius: 4px; mix-blend-mode: screen;
    background: linear-gradient(115deg, transparent 30%, rgb(200 120 255 / 0.55) 48%, transparent 66%) 0 0 / 250% 100%;
    animation: it-glint 2.6s linear infinite;
  }
  @keyframes it-glint { from { background-position: 120% 0; } to { background-position: -120% 0; } }
  :root[data-motion="off"] .it-glint { animation: none; }
  .it-n {
    position: absolute; right: 3px; bottom: 1px; font-size: 10px; font-weight: 800; color: #fff;
    text-shadow: 1px 1px 0 #3a3a3a;
  }
  .it-wear {
    position: absolute; right: 4px; bottom: 3px; left: 4px; height: 2px; border-radius: 999px;
    background: rgb(0 0 0 / 0.7);
  }
  .it-wear i { display: block; height: 100%; border-radius: 999px; }
  .hud-held { font-size: 11.5px; font-weight: 600; color: #fff; }

  /* Who is on the server, held on Tab. */
  .hud-tab {
    position: absolute; top: 40px; left: 50%; display: flex; width: min(560px, 84%); max-height: 70%;
    flex-direction: column; gap: 6px; overflow: hidden; border-radius: 14px; padding: 10px 12px;
    transform: translateX(-50%); background: rgb(10 9 14 / 0.74); backdrop-filter: blur(10px);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.12), 0 24px 50px -20px rgb(0 0 0 / 0.9);
  }
  .tab-edge { font-size: 11px; color: rgb(255 255 255 / 0.75); text-align: center; white-space: pre-line; }
  .tab-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 2px 8px; overflow: auto; }
  .tab-row {
    display: flex; align-items: center; gap: 6px; border-radius: 6px; padding: 2px 6px; font-size: 11px; color: #fff;
    background: rgb(255 255 255 / 0.05);
  }
  .tab-row b { min-width: 0; overflow: hidden; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
  .tab-row em { margin-left: auto; font-style: normal; color: rgb(255 255 255 / 0.5); }
  .ping { display: inline-flex; align-items: flex-end; gap: 1px; height: 9px; margin-left: auto; }
  .tab-row em + .ping { margin-left: 4px; }
  .ping s { width: 2px; border-radius: 1px; background: rgb(255 255 255 / 0.18); text-decoration: none; }
  .ping s:nth-child(1) { height: 2px; } .ping s:nth-child(2) { height: 4px; } .ping s:nth-child(3) { height: 5px; }
  .ping s:nth-child(4) { height: 7px; } .ping s:nth-child(5) { height: 9px; }
  .ping[data-bars="5"] s, .ping[data-bars="4"] s:nth-child(-n + 4), .ping[data-bars="3"] s:nth-child(-n + 3) { background: #6fd84a; }
  .ping[data-bars="2"] s:nth-child(-n + 2) { background: #f0c04a; }
  .ping[data-bars="1"] s:nth-child(1) { background: #ec4a4a; }

  /* What it is carrying, asked for from the bar (E), and anything it has open. */
  .hud-bag {
    position: absolute; top: 50%; left: 50%; z-index: 5; width: min(390px, 90%); max-height: 92%; display: flex;
    flex-direction: column; gap: 7px; overflow: auto; border-radius: 16px; padding: 12px; transform: translate(-50%, -50%);
    background: rgb(10 9 14 / 0.8); backdrop-filter: blur(12px);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.12), 0 24px 50px -20px rgb(0 0 0 / 0.9),
                0 0 50px -24px color-mix(in srgb, var(--color-accent) 60%, transparent);
    pointer-events: auto;
  }
  .hud-bag .hud-slot { width: 100%; height: auto; aspect-ratio: 1; }
  .hud-bag .hud-slot:hover { background: rgb(255 255 255 / 0.14); }
  .hud-bag-head {
    display: flex; align-items: center; gap: 6px; font-size: 10px; font-weight: 700; letter-spacing: 0.06em;
    text-transform: uppercase; color: rgb(255 255 255 / 0.62);
  }
  .hud-bag-n { margin-left: auto; font-weight: 600; letter-spacing: 0; text-transform: none; }
  .bag-x {
    display: grid; width: 22px; height: 22px; margin-left: auto; place-items: center; border-radius: 7px;
    color: rgb(255 255 255 / 0.7); background: rgb(255 255 255 / 0.06);
  }
  .hud-bag-n + .bag-x { margin-left: 4px; }
  .bag-x:hover { color: #fff; background: rgb(255 255 255 / 0.14); }
  .hud-bag-grid { display: grid; grid-template-columns: repeat(9, 1fr); gap: 3px; }
  .hud-bag-grid.is-hotbar { margin-top: 3px; }
  .bag-top { display: flex; gap: 10px; }
  .bag-worn { display: grid; grid-template-columns: repeat(5, 34px); gap: 3px; }
  .bag-worn .hud-slot { width: 34px; }
  .bag-stats { display: flex; flex-direction: column; justify-content: center; gap: 1px; font-size: 10.5px; color: rgb(255 255 255 / 0.6); }
  .bag-stats b { color: #fff; }
  .slot-ghost { font-size: 10px; font-weight: 700; color: rgb(255 255 255 / 0.22); }
  .hud-bag-none { font-size: 11.5px; color: rgb(255 255 255 / 0.55); }

  .hud-dead {
    position: absolute; inset: 0; z-index: 5; display: flex; flex-direction: column; align-items: center;
    justify-content: center; gap: 14px; pointer-events: auto;
    background: radial-gradient(circle at 50% 45%, rgb(150 20 20 / 0.35), rgb(60 0 0 / 0.6));
  }
  .dead-title { font-size: clamp(24px, 6cqw, 52px); font-weight: 800; color: #fff; text-shadow: 0 4px 24px rgb(0 0 0 / 0.6); }
</style>
