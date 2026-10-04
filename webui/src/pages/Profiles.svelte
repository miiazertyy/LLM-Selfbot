<script lang="ts">
  /**
   * Profiles: each one a bot of its own, with its own persona, pictures, memory and settings, on the accounts
   * given to it, and what each of those accounts is doing now.
   *
   * A card each, in its colour. Its face breathes while one of its accounts is up; its accounts are listed with
   * what each is doing, said the way the Accounts page says it (accounts/condition.ts), and one given to another
   * profile flies across to that one's card. Its parts open from it, already on it. A dashed card makes another.
   *
   * Opening, the hero comes first: a light sweeps across it, its ring winds in round the orb, and the title's
   * letters rise one after another. Then the cards are dealt onto the page one by one, each tipping up into place,
   * and what is on each arrives in turn: its colour washing in, its face popping, its name, its accounts plugging in
   * and its parts coming up, every step with its note booked on the sound card's clock beside its CSS delay (deal).
   * Open, a card leans towards the pointer with a light in its colour following it, a light runs round one that is
   * starting, and one that comes up flashes.
   *
   * Persona, Memory, Pictures and Settings show one profile at a time, picked with the pill at their top; opening
   * a part here opens it on this profile (viewPersona, settingsScope). The real accounts are never changed: a
   * profile's face lives in the app only.
   */
  import { onMount, tick } from "svelte";
  import { flip } from "svelte/animate";
  import { cubicOut } from "svelte/easing";
  import { crossfade, scale } from "svelte/transition";
  import { api } from "../lib/api";
  import { track } from "../lib/busy";
  import { visiblePoll } from "../lib/poll";
  import { motionEnabled, settingsScope, toast, viewPersona } from "../lib/stores";
  import Button from "../lib/components/Button.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import Avatar from "../lib/components/Avatar.svelte";
  import Modal from "../lib/components/Modal.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import StatusDot from "../lib/components/StatusDot.svelte";
  import Num from "../lib/dashboard/Num.svelte";
  import { chime, domino } from "../lib/domino";
  import { play } from "../lib/uisound";
  import { burstFrom, tilt } from "../lib/bigpicture/fx";
  import { afterLanding, onScreen, whenShown } from "../lib/cascade";
  import PersonaOrb from "../lib/personas/PersonaOrb.svelte";
  import ColorDots from "../lib/personas/ColorDots.svelte";
  import NewPersona from "../lib/personas/NewPersona.svelte";
  import AccountMenu from "../lib/personas/AccountMenu.svelte";
  import FacePicker from "../lib/personas/FacePicker.svelte";
  import { personasRes, reloadPersonas } from "../lib/personas/store";
  import { accountLabel, colorOf, joinAnd, runningLine, withAccount, type Persona } from "../lib/personas/logic";
  import { accountDetails, accountsRes, refreshDetails, slotsRes } from "../lib/accounts/state";
  import { condition, presenceOf, type Runtime, type Slot } from "../lib/accounts/condition";
  import { get } from "svelte/store";

  const data = $derived($personasRes.data);
  const list = $derived(data.personas);
  const runtime = $derived(($accountsRes.data.accounts ?? []) as Runtime[]);
  const slots = $derived(($slotsRes.data.slots ?? []) as Slot[]);
  const loading = $derived(!$personasRes.fetched && !list.length);
  let loadError = $state("");
  const defaultName = $derived(list.find((p) => p.is_default)?.name ?? "Default");

  // ── Accounts, as their cards say them ──────────────────────────────────────
  type Acct = {
    id: string; name: string; avatar: string; platform: string; label: string; tone: string;
    running: boolean; live: boolean; canStart: boolean; presence: string; silhouette: boolean;
  };
  function acct(id: string): Acct {
    const slot = slots.find((s) => s.id === id);
    const rt = runtime.find((r) => r.id === id);
    const d = $accountDetails[id];
    const cond = slot ? condition(slot, rt, d) : null;
    const platform = id.startsWith("snapchat") ? "snapchat" : "discord";
    return {
      id, platform,
      name: rt?.display_name || rt?.username || slot?.username || accountLabel(id),
      avatar: rt?.avatar ?? "",
      label: cond?.label ?? "Stopped",
      tone: cond?.tone ?? "muted",
      running: !!cond?.running,
      live: !!cond?.live,
      canStart: !!cond?.canStart,
      presence: slot ? presenceOf(slot, rt, d) : "offline",
      silhouette: platform === "snapchat" && !rt?.avatar && !!rt?.username,
    };
  }
  /** Each profile with its accounts and whether it is running now. */
  const cards = $derived(list.map((p) => {
    const accts = p.accounts.map(acct);
    const live = accts.filter((a) => a.live).length;
    const other = accts.find((a) => a.running && !a.live)?.label ?? "";
    return {
      p, accts, live,
      busy: !live && !!other,
      state: runningLine(accts.length, live, other),
      startable: accts.filter((a) => !a.running && a.canStart).length,
      stoppable: accts.filter((a) => a.running).length,
    };
  }));
  type Card = (typeof cards)[number];
  const totals = $derived({
    profiles: list.length,
    running: cards.filter((c) => c.live).length,
    accounts: Object.keys(data.accounts).length,
  });
  /** The accounts' faces, for the menu that gives one to a profile. */
  const faces = $derived(Object.fromEntries(runtime.filter((r) => r.platform !== "telegram").map((r) => [
    r.id, { name: r.display_name || r.username || "", avatar: r.avatar || "", platform: r.platform },
  ])));

  onMount(() => {
    personasRes.refresh({ maxAge: 10_000 }).then(() => (loadError = $personasRes.error));
    slotsRes.refresh({ maxAge: 30_000 });
    accountsRes.refresh({ maxAge: 3_000 }).then(refreshAllDetails);
    // What the accounts are doing changes by itself: asked again every few seconds while the page is in view.
    return visiblePoll(() => {
      accountsRes.refresh({ force: true, quiet: true }).then(refreshAllDetails);
      reloadPersonas();
    }, 5000);
  });
  async function refreshAllDetails() {
    await Promise.all(runtime.filter((r) => r.state === "running").map((r) => refreshDetails(r.id)));
  }

  // ── The cards dealt in as the page opens ───────────────────────────────────
  /** Between one card and the next. */
  const DEAL_STEP = 130;
  /**
   * Each card on screen tips up into place in turn, and what is on it follows (the CSS under .pr-grid.is-dealing,
   * timed off --i). Every step has its note, booked from the frame the cards start in: a note up the scale as each
   * lands, a glint as its face pops, a tick for each account plugging in, a soft seat as its parts settle. Once,
   * as the page opens; held until the page has landed (cascade.ts); cards off screen are simply there.
   */
  function deal(node: HTMLElement) {
    // Kept whole by the page's opening wave: it would otherwise drop each card in itself.
    node.dataset.rise = "";
    if (!get(motionEnabled)) return;
    node.classList.add("is-waiting");
    let gone = false;
    let done = 0;
    whenShown(node).then(() => afterLanding(node, () => onScreen(node).then((seen) => {
      if (gone) return;
      const kids = Array.from(node.children) as HTMLElement[];
      const view = innerHeight;
      let k = 0;
      for (const c of kids) {
        const r = c.getBoundingClientRect();
        const turn = seen && get(motionEnabled) && r.top < view && r.bottom > 0 && r.width > 0;
        c.style.setProperty("--i", String(turn ? k++ : 0));
        if (turn) delete c.dataset.there;
        else c.dataset.there = "";
      }
      node.style.setProperty("--deal-step", `${DEAL_STEP}ms`);
      node.classList.remove("is-waiting");
      if (!k) return;
      node.classList.add("is-dealing");
      done = window.setTimeout(() => node.classList.remove("is-dealing"), (k - 1) * DEAL_STEP + 1600);
      const dealt = kids.filter((c) => !("there" in c.dataset));
      requestAnimationFrame((frame) => {
        if (gone || !get(motionEnabled)) return;
        const base = frame - performance.now();
        dealt.forEach((c, i) => {
          const t = base + i * DEAL_STEP;
          play("pluck", { p: dealt.length > 1 ? 0.15 + (0.7 * i) / (dealt.length - 1) : 0.5, level: 0.55, delay: t + 60 });
          if (!c.classList.contains("pr-card")) return;
          play("glint", { level: 0.26, delay: t + 300 });
          const rows = Math.min(4, c.querySelectorAll(".pr-acct").length);
          for (let j = 0; j < rows; j++) play("tick", { level: 0.2, p: 0.35 + j * 0.12, delay: t + 400 + j * 70 });
          play("seat", { level: 0.28, delay: t + 700 + rows * 20 });
        });
      });
    })));
    return {
      destroy() {
        gone = true;
        clearTimeout(done);
      },
    };
  }

  // A profile coming up flashes, with a glint; one going quiet, a soft off. Not while the page first fills in: the
  // accounts and what each is doing arrive over its first few seconds, and that is not one coming up.
  const liveWas = new Map<string, number>();
  const openedAt = performance.now();
  let lit = $state("");
  let litTimer = 0;
  $effect(() => {
    const settling = !$accountsRes.fetched || performance.now() - openedAt < 4000;
    for (const c of cards) {
      const was = liveWas.get(c.p.id);
      liveWas.set(c.p.id, c.live);
      if (settling || was === undefined || was === c.live) continue;
      if (c.live > was) {
        lit = c.p.id;
        clearTimeout(litTimer);
        litTimer = window.setTimeout(() => (lit = ""), 1100);
        play("glint", { level: 0.45 });
      } else if (c.live === 0) {
        play("off", { level: 0.4 });
      }
    }
  });

  // ── Its parts, opened on it ────────────────────────────────────────────────
  function openPart(p: Persona, route: string) {
    viewPersona.set(p.id);
    if (route === "/settings") settingsScope.set(p.id);
    window.location.hash = route;
  }

  // ── Starting and stopping all of a profile's accounts ──────────────────────
  let acting = $state("");
  async function power(c: Card, act: "start" | "stop") {
    const targets = c.accts.filter((a) => (act === "start" ? !a.running && a.canStart : a.running));
    if (!targets.length) return;
    acting = `${c.p.id}:${act}`;
    play(act === "start" ? "on" : "off");
    let failed = 0;
    // One after another, as Start all does on Accounts: several logins at the same instant look automated.
    await track("accounts", (async () => {
      for (const a of targets) {
        try {
          const r: any = await api.accountAction(a.id, act);
          if (r && r.ok === false) failed++;
        } catch {
          failed++;
        }
      }
    })(), `${act === "start" ? "Starting" : "Stopping"} ${c.p.name}`);
    acting = "";
    toast(failed ? `${targets.length - failed} of ${targets.length} done, ${failed} failed.`
                 : act === "start" ? `Starting ${c.p.name}.` : `Stopped ${c.p.name}.`, failed ? "err" : "ok");
    setTimeout(() => accountsRes.refresh({ force: true, quiet: true }).then(refreshAllDetails), 700);
  }

  // ── Making one ─────────────────────────────────────────────────────────────
  let newOpen = $state(false);
  let copyOf = $state("");
  let creating = $state(false);
  /** One just made: its card pops into the grid with a burst of its colours. */
  let born = $state("");
  function openNew(from = "") {
    copyOf = from;
    play("open");
    newOpen = true;
  }
  async function create(body: { name: string; color: string; copy_from?: string; copy_memory?: boolean }) {
    creating = true;
    try {
      const r = await api.createPersona(body);
      newOpen = false;
      born = r.persona.id;
      await reloadPersonas();
      setTimeout(() => (born = ""), 1500);
      play("done");
      play("glint", { delay: 180, strong: true });
      toast(`${r.persona.name} is ready.`, "ok");
    } catch (e: any) {
      toast(e?.message || "Could not make it", "err");
    } finally {
      creating = false;
    }
  }
  function arrived(node: HTMLElement, pid: string) {
    if (pid !== born) return;
    const c = getComputedStyle(node).getPropertyValue("--pc").trim() || "#a78bfa";
    const t = window.setTimeout(() => burstFrom(node, { colors: [c, "#fff", `color-mix(in srgb, ${c} 50%, #fbbf24)`], count: 24, spread: 160 }), 260);
    node.scrollIntoView({ behavior: get(motionEnabled) ? "smooth" : "auto", block: "nearest" });
    return { destroy: () => clearTimeout(t) };
  }

  // ── Its name, colour and face ──────────────────────────────────────────────
  let renaming = $state("");
  let newName = $state("");
  let nameBox: HTMLInputElement | null = $state(null);
  async function startRename(p: Persona) {
    newName = p.name;
    renaming = p.id;
    await tick();
    nameBox?.select();
  }
  async function rename(p: Persona) {
    const name = newName.trim();
    renaming = "";
    if (!name || name === p.name) return;
    personasRes.update((d) => ({ ...d, personas: d.personas.map((x) => (x.id === p.id ? { ...x, name } : x)) }));
    play("seat");
    try {
      await api.updatePersona(p.id, { name });
    } catch (e: any) {
      toast(e?.message || "Could not rename it", "err");
    }
    reloadPersonas();
  }
  async function recolor(p: Persona, hex: string) {
    personasRes.update((d) => ({ ...d, personas: d.personas.map((x) => (x.id === p.id ? { ...x, color: hex } : x)) }));
    try {
      await api.updatePersona(p.id, { color: hex });
    } catch (e: any) {
      toast(e?.message || "Could not change it", "err");
      reloadPersonas();
    }
  }

  // ── Its face ───────────────────────────────────────────────────────────────
  // Picked in a small panel beside the face itself (FacePicker.svelte): the page stays as it is, nothing dimmed.
  let faceId = $state("");
  /** The profile as the list has it now, so the panel follows a rename or a new face. */
  const faceFor = $derived(list.find((x) => x.id === faceId) ?? null);
  let faceAt: HTMLElement | null = $state(null);
  /** The profile whose face just changed: it pops as it lands. */
  let popped = $state("");
  function openFace(p: Persona, at?: HTMLElement | null) {
    // Pressed again: put away.
    if (faceId === p.id) {
      faceId = "";
      return;
    }
    play("open");
    faceAt = at ?? document.querySelector<HTMLElement>(`[data-face="${CSS.escape(p.id)}"]`);
    faceId = p.id;
  }
  async function afterFace(pid: string) {
    faceId = "";
    await reloadPersonas();
    popped = "";
    await tick();
    popped = pid;
    play("land", { delay: 200 });
  }

  // ── Its accounts ───────────────────────────────────────────────────────────
  // An account given to another profile flies from its card to that one's.
  const [send, receive] = crossfade({ duration: 420, easing: cubicOut, fallback: (node) => scale(node, { start: 0.9, duration: 220 }) });
  let giveOpen = $state(false);
  let giveFor = $state("");
  let giveBtn: HTMLElement | null = $state(null);
  function openGive(p: Persona, el: HTMLElement) {
    if (giveOpen && giveFor === p.id) {
      giveOpen = false;
      return;
    }
    play("open");
    giveBtn = el;
    giveFor = p.id;
    giveOpen = true;
  }
  async function moveTo(pid: string, webId: string) {
    const name = list.find((x) => x.id === pid)?.name ?? "";
    const who = acct(webId).name;
    personasRes.update((d) => withAccount(d, webId, pid));
    try {
      const r: any = await api.assignPersona(pid, webId);
      const said = pid === "default" ? `${who} is back on ${name}.` : `${who} is ${name} now.`;
      toast(r?.restarted?.length ? `${said} Restarting it.` : said, pid === "default" ? "info" : "ok");
      setTimeout(() => accountsRes.refresh({ force: true, quiet: true }).then(refreshAllDetails), 700);
    } catch (e: any) {
      toast(e?.message || "Could not do that", "err");
    }
    reloadPersonas();
  }
  function give(webId: string) {
    play("zip");
    play("seat", { delay: 400 });
    moveTo(giveFor, webId);
  }
  function takeBack(webId: string) {
    play("drop");
    moveTo("default", webId);
  }

  // ── Its menu, and deleting it ──────────────────────────────────────────────
  let menuFor = $state("");
  $effect(() => {
    if (!menuFor) return;
    // The open one's own corner, found by its profile: a press anywhere else closes it.
    const host = document.querySelector(`[data-menu="${CSS.escape(menuFor)}"]`);
    const off = (e: MouseEvent) => {
      if (!host || !host.contains(e.target as Node)) menuFor = "";
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && (menuFor = "");
    const t = setTimeout(() => window.addEventListener("click", off), 0);
    window.addEventListener("keydown", esc);
    return () => {
      clearTimeout(t);
      window.removeEventListener("click", off);
      window.removeEventListener("keydown", esc);
    };
  });
  function toggleMenu(p: Persona) {
    if (menuFor !== p.id) play("open");
    menuFor = menuFor === p.id ? "" : p.id;
  }
  function fromMenu(fn: () => void) {
    menuFor = "";
    fn();
  }

  let deleteFor = $state<Persona | null>(null);
  const deleteOpen = $derived(!!deleteFor);
  let deleting = $state(false);
  async function remove() {
    const p = deleteFor;
    if (!p || p.is_default) return;
    deleting = true;
    try {
      await api.deletePersona(p.id);
      deleteFor = null;
      play("delete");
      play("slide", { delay: 120, level: 0.5 });
      play("seat", { delay: 480 });
      if (get(viewPersona) === p.id) viewPersona.set("default");
      await reloadPersonas();
    } catch (e: any) {
      toast(e?.message || "Could not delete it", "err");
    } finally {
      deleting = false;
    }
  }

  const PARTS = [
    { route: "/persona", icon: "persona", label: "Persona", of: (p: Persona) => p.words, unit: (n: number) => (n === 1 ? "word" : "words") },
    { route: "/pictures", icon: "pictures", label: "Pictures", of: (p: Persona) => p.pictures,
      unit: (n: number) => (n === 1 ? "picture" : "pictures") },
    { route: "/memory", icon: "memory", label: "Memory", of: (p: Persona) => p.people, unit: (n: number) => (n === 1 ? "person" : "people") },
    { route: "/settings", icon: "settings", label: "Settings", of: (p: Persona) => p.changed, unit: () => "its own" },
  ];
</script>

<ErrorNote text={loadError} onretry={() => { loadError = ""; reloadPersonas(); }} />

<!-- ── What is here, at a glance ──────────────────────────────────────────── -->
<section class="pr-hero glass" use:chime={{ sound: "wind", delay: 140 }}>
  <span class="pr-orb" use:chime={"land"}>
    <span class="pr-orb-ring" aria-hidden="true"></span>
    <span class="pr-orb-icon"><Icon name="layers" size={26} /></span>
  </span>
  <div class="pr-who">
    <span class="pr-kicker">Profiles</span>
    <!-- Its letters rise one after another. -->
    <h2 class="pr-title" aria-label="Your profiles">
      {#each ["Your", "profiles"] as word, w}<span class="pr-word" aria-hidden="true">{#each Array.from(word) as ch, i}<span
        class="pr-l" style="--c: {w * 5 + i}">{ch}</span>{/each}</span>{#if w === 0}{" "}{/if}{/each}
    </h2>
    <p class="pr-sub">Each one is its own bot, with its own persona, pictures, memory and settings, on the accounts you give it.</p>
  </div>
  <div class="pr-stats domino" use:domino={{ step: 80, sound: "key", level: 0.45 }}>
    {#each [{ label: "Profiles", n: totals.profiles, icon: "layers" }, { label: "Running", n: totals.running, icon: "play" },
            { label: "Accounts", n: totals.accounts, icon: "accounts" }] as s (s.label)}
      <span class="pr-stat">
        <span class="pr-stat-icon"><Icon name={s.icon} size={13} /></span>
        <b><Num value={s.n} /></b>
        <span>{s.label}</span>
      </span>
    {/each}
  </div>
</section>

{#if loading}
  <div class="pr-grid">
    {#each Array(2) as _}<div class="glass h-72 animate-pulse rounded-[22px]"></div>{/each}
  </div>
{:else}
  <!-- ── One card each, and a way to make another: dealt in one after another as the page opens ── -->
  <div class="pr-grid" use:deal>
    {#each cards as c (c.p.id)}
      {@const p = c.p}
      <article class="pr-card glass" class:is-live={c.live > 0} class:is-born={p.id === born} class:is-raised={menuFor === p.id}
               class:is-powering={acting === `${p.id}:start`} class:is-lit={lit === p.id}
               style="--pc: {colorOf(p)}" use:arrived={p.id} use:tilt={2.5}
               animate:flip={{ duration: 380, easing: cubicOut }} out:scale={{ start: 0.86, duration: 300, easing: cubicOut }}>
        <div class="pr-banner" aria-hidden="true"></div>

        <header class="pr-head">
          <button type="button" class="pr-face" class:is-live={c.live > 0} class:is-busy={c.busy} class:is-pop={popped === p.id}
                  onanimationend={() => { if (popped === p.id) popped = ""; }} onclick={(e) => openFace(p, e.currentTarget as HTMLElement)}
                  data-face={p.id}
                  title="Its face" aria-label="Change {p.name}'s face">
            <PersonaOrb {p} size={56} spin={c.live > 0} />
            <span class="pr-face-edit"><Icon name="edit" size={10} /></span>
          </button>
          <div class="pr-who-card">
            {#if renaming === p.id}
              <input class="pr-name-box" bind:this={nameBox} bind:value={newName} maxlength="40" aria-label="Its name"
                     onkeydown={(e) => { if (e.key === "Enter") rename(p); else if (e.key === "Escape") renaming = ""; }}
                     onblur={() => rename(p)} />
            {:else}
              <button type="button" class="pr-name" onclick={() => startRename(p)} title="Rename it">{p.name}</button>
            {/if}
            <!-- What it is doing: a new state slides in over the old one. -->
            {#key c.state.text}
              <span class="pr-state is-{c.state.tone}"><span class="pr-state-dot"></span>{c.state.text}</span>
            {/key}
          </div>
          {#if p.is_default}<span class="pr-badge" title="New accounts start on it">Default</span>{/if}
          <span class="pr-more" data-menu={p.id}>
            {#if menuFor === p.id}
              <div class="pr-menu" role="menu" tabindex="-1">
                <div class="pr-menu-dots"><ColorDots palette={data.palette} value={p.color} onpick={(hex) => recolor(p, hex)} /></div>
                <button type="button" role="menuitem" onclick={() => fromMenu(() => startRename(p))}><Icon name="edit" size={13} /> Rename</button>
                <button type="button" role="menuitem" onclick={() => fromMenu(() => openFace(p))}><Icon name="persona" size={13} /> Change its face</button>
                <button type="button" role="menuitem" onclick={() => fromMenu(() => openNew(p.id))}><Icon name="copy" size={13} /> Duplicate</button>
                {#if !p.is_default}
                  <button type="button" role="menuitem" class="is-danger"
                          onclick={() => fromMenu(() => { play("open"); deleteFor = p; })}><Icon name="trash" size={13} /> Delete</button>
                {/if}
              </div>
            {/if}
            <button type="button" class="pr-more-btn" aria-label="More" aria-haspopup="menu" aria-expanded={menuFor === p.id}
                    onclick={() => toggleMenu(p)}><Icon name="more" size={15} /></button>
          </span>
        </header>

        <!-- The accounts on it, and what each is doing. -->
        <div class="pr-accounts">
          {#each c.accts as a, j (a.id)}
            <div class="pr-acct" style="--j: {j}" in:receive={{ key: a.id }} out:send={{ key: a.id }} animate:flip={{ duration: 300 }}>
              <span class="pr-acct-av">
                <Avatar src={a.avatar} name={a.name} size={30} zoom={false} silhouette={a.silhouette} />
                <span class="pr-acct-dot"><StatusDot status={a.presence} size={10} /></span>
              </span>
              <span class="pr-acct-text">
                <b>{a.name}</b>
                <small><Icon name={a.platform} size={10} /> {accountLabel(a.id)}</small>
              </span>
              {#key a.label}<span class="pr-acct-state is-{a.tone}">{a.label}</span>{/key}
              {#if !p.is_default}
                <button type="button" class="pr-acct-x" title="Back to {defaultName}" aria-label="Move {a.name} back to {defaultName}"
                        onclick={() => takeBack(a.id)}><Icon name="close" size={10} /></button>
              {/if}
            </div>
          {/each}
          <button type="button" class="pr-give" style="--j: {c.accts.length}" onclick={(e) => openGive(p, e.currentTarget as HTMLElement)}>
            <Icon name="plus" size={11} /> Add an account
          </button>
        </div>

        <!-- Its parts, each opening on it. -->
        <div class="pr-parts">
          {#each PARTS as part, k (part.route)}
            {@const n = part.of(p)}
            <button type="button" class="pr-part" style="--k: {k}" onclick={() => openPart(p, part.route)} title="Open its {part.label.toLowerCase()}">
              <span class="pr-part-head"><Icon name={part.icon} size={13} /><span>{part.label}</span></span>
              <b><Num value={n} /></b>
              <small>{part.unit(n)}</small>
            </button>
          {/each}
        </div>

        {#if c.accts.length}
          <footer class="pr-foot">
            {#if c.stoppable}
              <Button kind="ghost" size="sm" loading={acting === `${p.id}:stop`} onclick={() => power(c, "stop")}>
                {#if acting !== `${p.id}:stop`}<Icon name="stop" size={11} />{/if}Stop
              </Button>
            {/if}
            {#if c.startable}
              <Button size="sm" loading={acting === `${p.id}:start`} onclick={() => power(c, "start")}>
                {#if acting !== `${p.id}:start`}<Icon name="play" size={11} />{/if}Start{c.startable > 1 ? ` all ${c.startable}` : ""}
              </Button>
            {/if}
          </footer>
        {/if}
      </article>
    {/each}

    <button type="button" class="pr-new" onclick={() => openNew()}>
      <span class="pr-new-orb"><Icon name="plus" size={22} /></span>
      <b>New profile</b>
      <small>Its own persona, pictures, memory and settings</small>
    </button>
  </div>
{/if}

<NewPersona bind:open={newOpen} {list} palette={data.palette} {copyOf} busy={creating} oncreate={create} />
<AccountMenu bind:open={giveOpen} anchor={giveBtn} {data} {faces} persona={giveFor} onpick={give} />

<!-- Its face: a small panel beside it, not a box over the page. -->
<FacePicker persona={faceFor} anchor={faceAt} onclose={() => (faceId = "")} onchanged={afterFace} />

<Modal open={deleteOpen} title={deleteFor ? `Delete ${deleteFor.name}?` : ""} onclose={() => (deleteFor = null)}>
  {#if deleteFor}
    <div class="pd">
      <p>
        Its persona, pictures and memory go.
        {#if deleteFor.accounts.length}
          {joinAnd(deleteFor.accounts.map(accountLabel))} {deleteFor.accounts.length === 1 ? "goes" : "go"} back to {defaultName}.
        {/if}
      </p>
      <div class="pd-actions">
        <Button kind="ghost" size="sm" onclick={() => (deleteFor = null)}>Cancel</Button>
        <Button kind="danger" size="sm" onclick={remove} loading={deleting}>Delete</Button>
      </div>
    </div>
  {/if}
</Modal>

<style>
  /* ── The hero ── */
  .pr-hero {
    position: relative;
    isolation: isolate;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 18px 22px;
    margin-bottom: 16px;
    padding: 22px 24px;
    overflow: hidden;
    border-radius: 22px;
    background-image:
      radial-gradient(70% 150% at 0% 0%, color-mix(in srgb, var(--color-accent) 20%, transparent), transparent 60%),
      radial-gradient(50% 120% at 100% 100%, color-mix(in srgb, var(--color-accent-2, var(--color-accent)) 12%, transparent), transparent 70%);
  }
  /* Opening: a band of light sweeps across it once. */
  .pr-hero::after {
    content: "";
    position: absolute;
    inset: -20% auto -20% 0;
    z-index: -1;
    width: 38%;
    pointer-events: none;
    background: linear-gradient(100deg, transparent, color-mix(in srgb, var(--color-accent) 22%, rgb(255 255 255 / 0.08)), transparent);
    transform: translateX(-120%) skewX(-12deg);
    animation: pr-sheen 1.25s cubic-bezier(0.35, 0.1, 0.2, 1) 0.14s both;
  }
  @keyframes pr-sheen {
    from { transform: translateX(-120%) skewX(-12deg); opacity: 0; }
    20% { opacity: 1; }
    to { transform: translateX(330%) skewX(-12deg); opacity: 0; }
  }
  .pr-orb {
    position: relative;
    display: grid;
    width: 72px;
    height: 72px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    animation: pr-orb-in 0.7s var(--jelly) backwards;
    transition: transform 0.45s var(--jelly);
  }
  .pr-orb:hover { transform: scale(1.07) rotate(-5deg); }
  @keyframes pr-orb-in { from { opacity: 0; transform: scale(0.4) rotate(-30deg); } }
  .pr-orb-ring {
    position: absolute;
    inset: 0;
    border-radius: 999px;
    background: conic-gradient(from 90deg, var(--color-accent), var(--color-accent-2, var(--color-accent)), transparent 60%, var(--color-accent));
    -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 2px));
    mask: radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 2px));
    /* Wound in fast round the orb as it pops, then turning slowly. */
    animation: pr-ring-in 1s cubic-bezier(0.2, 0.9, 0.25, 1) 0.1s backwards, pr-turn 7s linear 1.1s infinite;
  }
  @keyframes pr-turn { to { transform: rotate(360deg); } }
  @keyframes pr-ring-in { from { opacity: 0; transform: rotate(-300deg) scale(0.55); } 50% { opacity: 1; } }
  .pr-orb-icon {
    display: grid;
    width: 60px;
    height: 60px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-accent);
    background: radial-gradient(circle at 35% 30%, color-mix(in srgb, var(--color-accent) 30%, var(--color-card)), var(--color-card));
    animation: pr-icon-in 0.7s var(--jelly) 0.2s backwards, pr-stack 3.4s ease-in-out 0.9s infinite;
  }
  @keyframes pr-icon-in { from { opacity: 0; transform: scale(0.3) translateY(8px); } }
  @keyframes pr-stack { 50% { transform: translateY(-2px) scale(1.04); box-shadow: 0 0 24px -4px color-mix(in srgb, var(--color-accent) 60%, transparent); } }
  .pr-who { display: flex; min-width: 0; flex: 1 1 260px; flex-direction: column; gap: 2px; }
  .pr-kicker { font-size: 10.5px; font-weight: 650; letter-spacing: 0.16em; text-transform: uppercase; color: var(--color-faint);
               animation: pr-fade-x 0.5s var(--swift) 0.06s backwards; }
  .pr-title { font-size: 26px; font-weight: 700; line-height: 1.15; letter-spacing: -0.02em; color: var(--color-ink); }
  /* The title's letters, rising in one after another with a little tip; a word never breaks between them. */
  .pr-word { display: inline-block; white-space: nowrap; }
  .pr-l {
    display: inline-block;
    white-space: pre;
    animation: pr-letter 0.6s cubic-bezier(0.25, 1.4, 0.45, 1) backwards;
    animation-delay: calc(0.12s + var(--c) * 26ms);
  }
  @keyframes pr-letter { from { opacity: 0; transform: translateY(0.55em) rotate(8deg) scale(0.8); } 55% { opacity: 1; } }
  .pr-sub { margin-top: 3px; font-size: 12.5px; color: var(--color-muted); animation: pr-fade-x 0.6s var(--swift) 0.42s backwards; }
  @keyframes pr-fade-x { from { opacity: 0; transform: translateX(-10px); } }
  .pr-stats { display: flex; gap: 8px; }
  .pr-stat {
    display: flex;
    min-width: 82px;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    padding: 10px 12px;
    border-radius: 16px;
    font-size: 11px;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.035);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    transition: transform 0.4s var(--jelly);
  }
  .pr-stat:hover { transform: translateY(-2px); }
  .pr-stat-icon { display: grid; color: var(--color-accent); }
  .pr-stat b { font-size: 18px; font-weight: 700; color: var(--color-ink); }

  /* ── The cards ── */
  .pr-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 360px), 1fr)); align-items: start; gap: 16px; }
  .pr-card {
    --pc: var(--color-accent);
    position: relative;
    display: flex;
    flex-direction: column;
    border-radius: 22px;
    /* Leaning towards the pointer (tilt, from bigpicture/fx.ts), flat again as it leaves. */
    transform: perspective(1100px) rotateX(var(--tx, 0deg)) rotateY(var(--ty, 0deg));
    transition: box-shadow 0.35s var(--swift), transform 0.6s var(--jelly);
  }
  .pr-card:hover { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--pc) 32%, transparent), 0 22px 48px -32px var(--pc); }
  /* Its menu open: flat, so the menu does not lean. */
  .pr-card.is-raised { --tx: 0deg; --ty: 0deg; }
  /* A light in its colour, following the pointer across it. */
  .pr-card::after {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: inherit;
    pointer-events: none;
    background: radial-gradient(380px circle at var(--lx, 50%) var(--ly, 0%), color-mix(in srgb, var(--pc) 13%, transparent), transparent 62%);
    opacity: 0;
    transition: opacity 0.35s ease;
  }
  .pr-card:hover::after { opacity: 1; }
  /* Starting: a light runs round its edge until it is done. */
  .pr-card.is-powering::before {
    content: "";
    position: absolute;
    inset: 0;
    z-index: 2;
    padding: 1.5px;
    border-radius: inherit;
    pointer-events: none;
    background: conic-gradient(from var(--pr-spin), transparent 0 62%, color-mix(in srgb, var(--pc) 70%, transparent) 80%, #fff 88%,
                transparent 94%);
    -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    -webkit-mask-composite: xor;
    mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    mask-composite: exclude;
    animation: pr-spin 1.3s linear infinite;
  }
  @property --pr-spin { syntax: "<angle>"; inherits: false; initial-value: 0deg; }
  @keyframes pr-spin { to { --pr-spin: 360deg; } }
  /* Come up: its colour flashes across the top. */
  .pr-card.is-lit .pr-banner { animation: pr-lit 1.1s ease-out; }
  @keyframes pr-lit { 0% { opacity: 1; filter: brightness(1.9) saturate(1.5); } 100% { filter: none; } }

  /* ── Dealt in as the page opens (deal): each card tips up into place in turn, then what is on it arrives ── */
  .pr-grid:global(.is-waiting) > * { opacity: 0; }
  .pr-grid:global(.is-dealing) > :global(:not([data-there])) {
    --at: calc(var(--i, 0) * var(--deal-step, 130ms));
    transform-origin: 50% 100%;
    animation: pr-deal 0.8s cubic-bezier(0.22, 1.2, 0.36, 1) backwards;
    animation-delay: var(--at);
  }
  @keyframes pr-deal {
    from { opacity: 0; transform: perspective(1100px) translateY(60px) rotateX(18deg) rotateZ(-1.5deg) scale(0.93); }
    55% { opacity: 1; }
  }
  /* Its colour washes in from the left. */
  .pr-grid:global(.is-dealing) > .pr-card:global(:not([data-there])) .pr-banner {
    animation: pr-wash 1s cubic-bezier(0.3, 0.7, 0.2, 1) backwards;
    animation-delay: calc(var(--at) + 140ms);
  }
  @keyframes pr-wash { from { opacity: 0; clip-path: inset(0 100% 0 0); } }
  /* Its face pops, spinning in. */
  .pr-grid:global(.is-dealing) > .pr-card:global(:not([data-there])) .pr-face {
    animation: pr-face-in 0.7s var(--jelly) backwards;
    animation-delay: calc(var(--at) + 240ms);
  }
  @keyframes pr-face-in { from { opacity: 0; transform: scale(0.2) rotate(-50deg); } }
  /* Its name, then what it is doing, then its badge and menu. */
  .pr-grid:global(.is-dealing) > .pr-card:global(:not([data-there])) .pr-who-card > :first-child {
    animation: pr-fade-x 0.5s var(--swift) backwards;
    animation-delay: calc(var(--at) + 300ms);
  }
  .pr-grid:global(.is-dealing) > .pr-card:global(:not([data-there])) .pr-who-card .pr-state {
    animation: pr-fade-x 0.5s var(--swift) backwards;
    animation-delay: calc(var(--at) + 370ms);
  }
  .pr-grid:global(.is-dealing) > .pr-card:global(:not([data-there])) .pr-badge,
  .pr-grid:global(.is-dealing) > .pr-card:global(:not([data-there])) .pr-more {
    animation: pr-fade 0.5s ease backwards;
    animation-delay: calc(var(--at) + 380ms);
  }
  @keyframes pr-fade { from { opacity: 0; } }
  /* Its accounts plugging in, one after another, a touch past their place and back. */
  .pr-grid:global(.is-dealing) > .pr-card:global(:not([data-there])) .pr-acct,
  .pr-grid:global(.is-dealing) > .pr-card:global(:not([data-there])) .pr-give {
    animation: pr-plug 0.55s cubic-bezier(0.3, 1.4, 0.5, 1) backwards;
    animation-delay: calc(var(--at) + 400ms + var(--j, 0) * 70ms);
  }
  @keyframes pr-plug { from { opacity: 0; transform: translateX(-18px) scale(0.97); } 50% { opacity: 1; } }
  /* Its parts coming up, left to right. */
  .pr-grid:global(.is-dealing) > .pr-card:global(:not([data-there])) .pr-part {
    animation: pr-tile 0.6s var(--jelly) backwards;
    animation-delay: calc(var(--at) + 520ms + var(--k, 0) * 55ms);
  }
  @keyframes pr-tile { from { opacity: 0; transform: translateY(14px) scale(0.88); } }
  .pr-grid:global(.is-dealing) > .pr-card:global(:not([data-there])) .pr-foot {
    animation: pr-rise 0.5s var(--swift) backwards;
    animation-delay: calc(var(--at) + 720ms);
  }
  @keyframes pr-rise { from { opacity: 0; transform: translateY(8px); } }
  /* The way to make another: its plus spins in after it lands. */
  .pr-grid:global(.is-dealing) > .pr-new:global(:not([data-there])) .pr-new-orb {
    animation: pr-face-in 0.7s var(--jelly) backwards;
    animation-delay: calc(var(--at) + 220ms);
  }
  .pr-card.is-live { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--pc) 24%, transparent); }
  .pr-card.is-raised { z-index: 20; }
  .pr-card.is-born { animation: pr-born 0.62s cubic-bezier(0.3, 1.4, 0.5, 1) backwards; }
  @keyframes pr-born { from { opacity: 0; transform: scale(0.6) rotate(-4deg); } 60% { opacity: 1; transform: scale(1.04) rotate(0.6deg); } }
  /* Its colour washed across the top, stronger and slowly moving while it runs. */
  .pr-banner {
    position: absolute;
    inset: 0 0 auto 0;
    height: 110px;
    overflow: hidden;
    border-radius: 22px 22px 0 0;
    pointer-events: none;
    background:
      radial-gradient(80% 140% at 8% 0%, color-mix(in srgb, var(--pc) 34%, transparent), transparent 70%),
      radial-gradient(60% 120% at 96% 0%, color-mix(in srgb, var(--pc) 16%, transparent), transparent 72%);
    -webkit-mask-image: linear-gradient(to bottom, #000 30%, transparent);
    mask-image: linear-gradient(to bottom, #000 30%, transparent);
    transition: opacity 0.4s ease;
    opacity: 0.7;
  }
  .pr-card.is-live .pr-banner { opacity: 1; animation: pr-drift 9s ease-in-out infinite alternate; }
  @keyframes pr-drift { to { background-position: 18% 0, 82% 0; filter: saturate(1.25); } }
  .pr-head { position: relative; display: flex; align-items: center; gap: 14px; padding: 18px 16px 10px 18px; }
  /* Its face, in a ring of its colour that breathes while one of its accounts is up (amber while one starts). */
  .pr-face { position: relative; display: grid; flex-shrink: 0; place-items: center; border-radius: 999px; transition: transform 0.45s var(--jelly); }
  .pr-face:hover { transform: scale(1.06) rotate(-4deg); }
  .pr-face::before {
    content: "";
    position: absolute;
    inset: -5px;
    border-radius: 999px;
    opacity: 0;
    transition: opacity 0.3s ease;
  }
  .pr-face.is-live::before {
    opacity: 1;
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--pc) 60%, transparent), 0 0 24px color-mix(in srgb, var(--pc) 40%, transparent);
    animation: pr-breathe 3.2s ease-in-out infinite;
  }
  .pr-face.is-busy::before {
    opacity: 1;
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-warn) 65%, transparent), 0 0 18px color-mix(in srgb, var(--color-warn) 30%, transparent);
    animation: pr-breathe 1.6s ease-in-out infinite;
  }
  @keyframes pr-breathe { 0%, 100% { transform: scale(1); opacity: 0.75; } 50% { transform: scale(1.05); opacity: 1; } }
  .pr-face.is-pop { animation: pr-pop 0.55s var(--jelly); }
  @keyframes pr-pop { 40% { transform: scale(1.18); } }
  .pr-face-edit {
    position: absolute;
    right: -2px;
    bottom: -2px;
    display: grid;
    width: 20px;
    height: 20px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--pc) 60%, var(--color-card));
    box-shadow: 0 0 0 2px var(--color-card);
    opacity: 0;
    transform: scale(0.6);
    transition: opacity 0.2s ease, transform 0.3s var(--jelly);
  }
  .pr-face:hover .pr-face-edit, .pr-face:focus-visible .pr-face-edit { opacity: 1; transform: none; }
  .pr-who-card { display: flex; min-width: 0; flex: 1; flex-direction: column; align-items: flex-start; gap: 5px; }
  .pr-name {
    max-width: 100%;
    overflow: hidden;
    border-radius: 8px;
    font-size: 19px;
    font-weight: 700;
    letter-spacing: -0.01em;
    text-align: left;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--color-ink);
    transition: color 0.2s ease;
  }
  .pr-name:hover { color: color-mix(in srgb, var(--pc) 35%, var(--color-ink)); }
  .pr-name-box {
    width: 100%;
    padding: 1px 8px;
    border-radius: 9px;
    font-size: 17px;
    font-weight: 700;
    color: var(--color-ink);
    background: rgb(0 0 0 / 0.3);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--pc) 60%, transparent);
    outline: none;
  }
  .pr-state { display: inline-flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 600; color: var(--color-faint);
               animation: pr-swap 0.45s var(--jelly); }
  @keyframes pr-swap { from { opacity: 0; transform: translateY(6px); } }
  .pr-state-dot { position: relative; width: 7px; height: 7px; border-radius: 999px; background: currentColor; }
  .pr-state.is-good { color: var(--color-good); }
  .pr-state.is-good .pr-state-dot::after {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 999px;
    background: currentColor;
    animation: pr-ping 2s ease-out infinite;
  }
  @keyframes pr-ping { from { opacity: 0.7; transform: scale(1); } to { opacity: 0; transform: scale(2.8); } }
  .pr-state.is-warn { color: var(--color-warn); }
  .pr-badge {
    align-self: flex-start;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 650;
    letter-spacing: 0.04em;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.06);
  }
  .pr-more { position: relative; align-self: flex-start; }
  .pr-more-btn {
    display: grid;
    width: 30px;
    height: 30px;
    place-items: center;
    border-radius: 10px;
    color: var(--color-muted);
    transition: background-color 0.15s ease, color 0.15s ease;
  }
  .pr-more-btn:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.07); }
  /* Solid, not the menus' glass: inside a glass card a backdrop blur has nothing to blur, and the card's own tiles
     read straight through it. Wide enough for its colours in one row. */
  .pr-menu {
    position: absolute;
    top: calc(100% + 4px);
    right: 0;
    z-index: 30;
    display: flex;
    min-width: 272px;
    flex-direction: column;
    padding: 6px;
    border-radius: 14px;
    background: linear-gradient(180deg, rgb(255 255 255 / 0.06), transparent 40%), var(--color-card);
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 0.1), 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent),
                0 18px 44px -14px rgb(0 0 0 / 0.65);
    transform-origin: top right;
    animation: pr-menu-in 0.22s var(--jelly);
  }
  @keyframes pr-menu-in { from { opacity: 0; transform: scale(0.94) translateY(-4px); } }
  .pr-menu-dots { padding: 6px 6px 8px; margin-bottom: 4px; border-bottom: 1px solid color-mix(in srgb, var(--color-edge) 70%, transparent); }
  .pr-menu button {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 10px;
    border-radius: 9px;
    font-size: 12.5px;
    text-align: left;
    color: var(--color-ink);
  }
  .pr-menu button:hover { background: rgb(255 255 255 / 0.07); }
  .pr-menu > * { animation: pr-item 0.3s var(--swift) backwards; }
  .pr-menu > :nth-child(2) { animation-delay: 30ms; }
  .pr-menu > :nth-child(3) { animation-delay: 60ms; }
  .pr-menu > :nth-child(4) { animation-delay: 90ms; }
  .pr-menu > :nth-child(5) { animation-delay: 120ms; }
  @keyframes pr-item { from { opacity: 0; transform: translateY(-5px); } }
  .pr-menu button.is-danger { color: var(--color-bad); }

  /* Its accounts. */
  .pr-accounts { position: relative; display: flex; flex-direction: column; gap: 4px; padding: 4px 12px 10px; }
  .pr-acct {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 8px;
    border-radius: 13px;
    background: rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 55%, transparent);
    transition: transform 0.4s var(--jelly), background-color 0.2s ease, box-shadow 0.2s ease;
  }
  .pr-acct:hover { transform: translateX(3px); background: color-mix(in srgb, var(--pc) 6%, transparent);
                   box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--pc) 30%, transparent); }
  .pr-acct-av { position: relative; display: inline-grid; flex-shrink: 0; }
  .pr-acct-dot { position: absolute; right: -2px; bottom: -2px; display: grid; border-radius: 999px; box-shadow: 0 0 0 2px var(--color-card); }
  .pr-acct-text { display: flex; min-width: 0; flex: 1; flex-direction: column; }
  .pr-acct-text b { overflow: hidden; font-size: 13px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; color: var(--color-ink); }
  .pr-acct-text small { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; color: var(--color-faint); }
  .pr-acct-state {
    flex-shrink: 0;
    animation: pr-chip 0.45s var(--jelly);
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 650;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.05);
  }
  @keyframes pr-chip { from { opacity: 0; transform: scale(0.7); } }
  .pr-acct-state.is-good { color: var(--color-good); background: color-mix(in srgb, var(--color-good) 12%, transparent); }
  .pr-acct-state.is-warn { color: var(--color-warn); background: color-mix(in srgb, var(--color-warn) 12%, transparent); }
  .pr-acct-state.is-bad { color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 12%, transparent); }
  .pr-acct-x {
    display: grid;
    width: 20px;
    height: 20px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    color: var(--color-faint);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .pr-acct-x:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.1); }
  .pr-give {
    display: inline-flex;
    align-self: flex-start;
    align-items: center;
    gap: 6px;
    margin-top: 2px;
    padding: 5px 11px;
    border-radius: 999px;
    font-size: 12px;
    color: var(--color-muted);
    border: 1px dashed color-mix(in srgb, var(--color-edge) 90%, transparent);
    transition: color 0.15s ease, border-color 0.15s ease, background-color 0.15s ease;
  }
  .pr-give:hover { color: var(--color-ink); border-color: color-mix(in srgb, var(--pc) 60%, transparent);
                   background: color-mix(in srgb, var(--pc) 8%, transparent); }

  /* Its parts, a tile each. */
  .pr-parts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; padding: 2px 12px 12px; }
  .pr-part {
    display: flex;
    min-width: 0;
    flex-direction: column;
    align-items: flex-start;
    gap: 1px;
    padding: 9px 10px 8px;
    border-radius: 14px;
    text-align: left;
    background: rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 65%, transparent);
    transition: transform 0.4s var(--jelly), background-color 0.2s ease, box-shadow 0.2s ease;
  }
  .pr-part:hover { transform: translateY(-2px); background: color-mix(in srgb, var(--pc) 10%, transparent);
                   box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--pc) 42%, transparent); }
  .pr-part:active { transform: scale(0.97); }
  .pr-part-head { display: inline-flex; max-width: 100%; align-items: center; gap: 5px; font-size: 10.5px; font-weight: 650;
                  color: color-mix(in srgb, var(--pc) 70%, var(--color-muted)); }
  .pr-part-head :global(svg) { transition: transform 0.45s var(--jelly); }
  .pr-part:hover .pr-part-head :global(svg) { transform: rotate(-12deg) scale(1.22); }
  .pr-part-head span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pr-part b { margin-top: 4px; font-size: 16px; font-weight: 700; color: var(--color-ink); }
  .pr-part small { font-size: 10.5px; color: var(--color-faint); }
  .pr-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: auto; padding: 0 14px 14px; }

  /* The way to make another. */
  .pr-new {
    display: flex;
    min-height: 260px;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 24px;
    border-radius: 22px;
    text-align: center;
    color: var(--color-muted);
    border: 1.5px dashed color-mix(in srgb, var(--color-edge) 90%, transparent);
    transition: border-color 0.2s ease, background-color 0.2s ease;
  }
  .pr-new { transition: border-color 0.2s ease, background-color 0.2s ease, transform 0.45s var(--jelly); }
  .pr-new:hover { border-color: color-mix(in srgb, var(--color-accent) 55%, transparent); background: color-mix(in srgb, var(--color-accent) 5%, transparent);
                  transform: translateY(-3px); }
  .pr-new:active { transform: scale(0.98); }
  .pr-new b { font-size: 15px; font-weight: 650; color: var(--color-ink); }
  .pr-new small { max-width: 16rem; font-size: 12px; line-height: 1.45; }
  .pr-new-orb {
    display: grid;
    width: 52px;
    height: 52px;
    margin-bottom: 6px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 12%, transparent);
    transition: transform 0.45s var(--jelly);
  }
  .pr-new:hover .pr-new-orb { transform: rotate(90deg) scale(1.08); }

  /* ── Deleting it ── */
  .pd-actions { display: flex; justify-content: flex-end; gap: 8px; }
  .pd { display: flex; flex-direction: column; gap: 14px; font-size: 13px; line-height: 1.55; color: var(--color-muted); }

  @media (max-width: 520px) {
    .pr-parts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }

  :global(:root[data-motion="off"]) .pr-orb,
  :global(:root[data-motion="off"]) .pr-orb-ring,
  :global(:root[data-motion="off"]) .pr-orb-icon,
  :global(:root[data-motion="off"]) .pr-hero::after,
  :global(:root[data-motion="off"]) .pr-kicker,
  :global(:root[data-motion="off"]) .pr-l,
  :global(:root[data-motion="off"]) .pr-sub,
  :global(:root[data-motion="off"]) .pr-grid *,
  :global(:root[data-motion="off"]) .pr-grid > *,
  :global(:root[data-motion="off"]) .pr-card::before,
  :global(:root[data-motion="off"]) .pr-state,
  :global(:root[data-motion="off"]) .pr-acct-state,
  :global(:root[data-motion="off"]) .pr-menu > *,
  :global(:root[data-motion="off"]) .pr-card.is-born,
  :global(:root[data-motion="off"]) .pr-card.is-live .pr-banner,
  :global(:root[data-motion="off"]) .pr-face::before,
  :global(:root[data-motion="off"]) .pr-face.is-pop,
  :global(:root[data-motion="off"]) .pr-state-dot::after,
  :global(:root[data-motion="off"]) .pr-menu { animation: none; }
  :global(:root[data-motion="off"]) .pr-card,
  :global(:root[data-motion="off"]) .pr-card::after,
  :global(:root[data-motion="off"]) .pr-acct,
  :global(:root[data-motion="off"]) .pr-new,
  :global(:root[data-motion="off"]) .pr-part-head :global(svg),
  :global(:root[data-motion="off"]) .pr-face,
  :global(:root[data-motion="off"]) .pr-part,
  :global(:root[data-motion="off"]) .pr-stat,
  :global(:root[data-motion="off"]) .pr-new-orb { transition: none; }
</style>
