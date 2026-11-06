<script lang="ts">
  /**
   * People: everyone it talks to, on every account, on a shelf along the bottom,
   * with the one in hand large above it. Who they are to you (the Memory summary,
   * as a headline and short labelled points), how the conversation last went, and
   * the way to open it.
   *
   * Move along the shelf and the card and the room follow. That only ever reads
   * what is already stored here: no messages are read and no model is asked, until
   * someone presses for that. Left alone, on the tour, it shows someone new each
   * time it comes round, someone with something written about them first.
   */
  import { onDestroy, untrack } from "svelte";
  import { fade } from "svelte/transition";
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import MessageBody from "../components/MessageBody.svelte";
  import PlatformMark from "../components/PlatformMark.svelte";
  import RankBadge from "../components/RankBadge.svelte";
  import SummaryText from "../components/SummaryText.svelte";
  import { conversations, convKey } from "../chats";
  import { hscroll } from "../hscroll";
  import { motionEnabled } from "../stores";
  import { play as uiPlay } from "../uisound";
  import { fitText } from "./fit";
  import { focusable } from "./focus";
  import { popIn } from "./motion";
  import { ago } from "./scenes";
  import type { MemoryLine, PageActions, Person, QRow } from "./types";
  import type { World } from "./world.svelte";

  let {
    world,
    act,
    now = 0,
    queue = [],
    replying = {},
    onreply,
  }: {
    world: World;
    act: PageActions;
    now?: number;
    queue?: QRow[];
    replying?: Record<string, boolean>;
    onreply?: (r: QRow) => void;
  } = $props();

  let sort = $state<"recent" | "most">("recent");
  const sorted = $derived.by<Person[]>(() => {
    const week = (p: Person) => world.weekCounts[p.id] ?? 0;
    return sort === "recent" ? world.people
      : world.people.slice().sort((a, b) => week(b) - week(a) || b.messages - a.messages);
  });

  /** Chosen by hand, or else whose turn it is on the tour. */
  let chosen = $state<string | null>(null);
  const turnFor = $derived.by<Person | null>(() => {
    const written = world.people.filter((p) => world.memory[p.id]);
    const pool = written.length ? written : world.people;
    return pool.length ? pool[Math.max(0, world.turn - 1) % pool.length] : null;
  });
  const hero = $derived(world.people.find((p) => p.key === chosen) ?? turnFor);
  const told = $derived(hero ? world.memory[hero.id] : undefined);
  /** In the queue right now: then it can be hurried from here. */
  const row = $derived(hero ? queue.find((r) => r.key === hero.key) : undefined);
  const canHurry = $derived(!!row && (row.st.phase === "needs" || row.st.step === 1 || row.st.step === 3));
  /** The lines kept with the summary, or the conversation if it has been read this visit. */
  const lines = $derived.by<MemoryLine[]>(() => {
    if (!hero) return [];
    const held = $conversations[convKey(hero.target, hero.id)]?.messages;
    const read = held?.filter((m) => m.text).slice(-4).map((m) => ({ mine: !!m.mine, text: m.text ?? "" }));
    return read?.length ? read : told?.recent ?? [];
  });

  // The stored summary, and the room lit for them, as they come up.
  $effect(() => {
    const p = hero;
    untrack(() => {
      if (p) {
        world.askSummary(p.id);
        act.light("people", { seed: p.id, art: p.avatar });
      } else {
        act.light("people", null);
      }
    });
  });
  onDestroy(() => act.light("people", null));

  function choose(p: Person) {
    if (chosen === p.key) return;
    chosen = p.key;
  }
  function setSort(s: "recent" | "most") {
    sort = s;
    uiPlay("select");
    act.hold();
    // The new order starts at the start.
    shelf?.scrollTo({ left: 0, behavior: $motionEnabled ? "smooth" : "auto" });
  }

  let shelf: HTMLElement | null = $state(null);
  // Whoever comes up by themselves is brought into view on the shelf.
  $effect(() => {
    const key = hero?.key;
    const box = shelf;
    if (!key || !box) return;
    const t = setTimeout(() => {
      const el = box.querySelector<HTMLElement>(`[data-key="${CSS.escape(key)}"]`);
      if (!el) return;
      // Along the shelf alone: on a phone the view itself scrolls, and must not move for this.
      const b = box.getBoundingClientRect(), r = el.getBoundingClientRect();
      if (r.left < b.left + 40 || r.right > b.right - 40) {
        box.scrollBy({ left: r.left + r.width / 2 - (b.left + b.width / 2), behavior: $motionEnabled ? "smooth" : "auto" });
      }
    }, 60);
    return () => clearTimeout(t);
  });
</script>

<div class="bpe">
  {#if hero}
    <div class="bpe-stage">
      {#key hero.key}
        <article class="bpe-hero" in:popIn={{ from: 0.985 }} out:fade={{ duration: $motionEnabled ? 120 : 0 }}>
          <div class="bpe-who">
            <span class="bp-face">
              <Avatar src={hero.avatar} name={hero.name} size={104} zoom={false} />
              <span class="bp-mark"><PlatformMark platform={hero.platform} size={30} /></span>
            </span>
            <div class="bpe-id">
              <div class="bp-name" use:fitText={{ min: 24, text: hero.name }}>{hero.name}</div>
              <div class="bp-sub">
                {hero.messages} message{hero.messages === 1 ? "" : "s"}{hero.last_ts ? ` · last one ${ago(hero.last_ts, now)}` : ""}{#if row}<span class="bpe-state" data-tone={row.st.tone}> · {row.st.short}</span>{/if}
              </div>
              <div class="bpe-do">
                <button class="bp-btn is-go" use:focusable={{ id: "people:open" }} onclick={() => act.openPerson(hero)}>
                  <Icon name="chats" size={15} />Open conversation
                </button>
                {#if canHurry && row}
                  <button class="bp-btn" use:focusable={{ id: "people:reply" }} disabled={!!replying[row.u.id]} onclick={() => onreply?.(row)}>
                    <Icon name="reply" size={15} />{replying[row.u.id] ? "Replying" : "Reply now"}
                  </button>
                {/if}
              </div>
            </div>
          </div>

          <div class="bpe-grid">
            <div class="bpe-told bp-panel" data-private>
              {#if told}
                <SummaryText text={told.summary} size="lg" reveal />
                {#if told.generated_at}
                  <div class="bpe-foot">Written {ago(told.generated_at, now)}{told.count ? `, from the last ${told.count} messages` : ""}</div>
                {/if}
              {:else if world.memOff}
                <p class="bpe-none">Summaries are off, or no account is running to write one.</p>
              {:else}
                <p class="bpe-none">Nothing written about them yet.</p>
                <button class="bp-btn bpe-write" use:focusable={{ id: "people:write" }} disabled={!!world.writing[hero.id]} onclick={() => world.writeSummary(hero)}>
                  <Icon name="sparkle" size={15} />{world.writing[hero.id] ? "Writing" : "Write it"}
                </button>
              {/if}
            </div>
            {#if lines.length}
              <div class="bpe-msgs" data-private>
                <div class="bp-label">How it last went</div>
                {#each lines as m, i (i)}
                  <div class="bpe-msg" class:is-mine={m.mine} in:popIn|global={{ delay: 120 + i * 90 }}>
                    <div class="bpe-bubble"><MessageBody text={m.text} clamp={3} /></div>
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        </article>
      {/key}
    </div>

    <div class="bpe-shelfwrap">
      <div class="bpe-sort">
        <button class="bp-chip" class:is-on={sort === "recent"} data-sound="self" use:focusable={{ id: "people:recent" }} onclick={() => setSort("recent")}>Recent</button>
        <button class="bp-chip" class:is-on={sort === "most"} data-sound="self" use:focusable={{ id: "people:most" }} onclick={() => setSort("most")}>Most</button>
      </div>
      <div class="hscroll bpe-shelfbox">
        <div class="bpe-shelf" bind:this={shelf} use:hscroll>
          {#each sorted as p, i (p.key)}
            {@const inQueue = queue.some((r) => r.key === p.key)}
            <button class="bp-row bpe-person" class:is-on={p.key === hero.key} data-key={p.key}
                    use:focusable={{ id: p.key, first: p.key === hero.key, onfocus: () => choose(p) }}
                    onclick={() => act.openPerson(p)} title="Open {p.name}" in:popIn|global={{ delay: 80 + Math.min(i, 14) * 34, from: 0.86 }}>
              <span class="bp-face">
                <Avatar src={p.avatar} name={p.name} size={68} zoom={false} />
                <span class="bp-mark"><PlatformMark platform={p.platform} size={20} /></span>
                {#if sort === "most" && i < 3 && (world.weekCounts[p.id] ?? 0) > 0}
                  <span class="bpe-medal"><RankBadge n={i + 1} size={26} quiet /></span>
                {/if}
                {#if inQueue}<i class="bpe-waiting" title="In the queue"></i>{/if}
              </span>
              <span class="bpe-pname">{p.name}</span>
              <span class="bpe-psub">{sort === "most" ? `${world.weekCounts[p.id] ?? 0} this week` : ago(p.last_ts, now)}</span>
            </button>
          {/each}
        </div>
      </div>
    </div>
  {:else}
    <div class="bp-empty">
      <b>Nobody yet</b>
      <p>Whoever it talks to shows up here.</p>
    </div>
  {/if}
</div>

<style>
  .bpe {
    --sm-ink: var(--color-ink);
    --sm-muted: var(--bp-muted);
    --sm-accent: var(--bp-lit);
    display: flex;
    height: 100%;
    min-height: 0;
    flex-direction: column;
    gap: clamp(8px, 1.4vh, 16px);
  }
  .bpe-stage { display: grid; min-height: 0; flex: 1 1 0; grid-template: minmax(0, 1fr) / minmax(0, 1fr); }
  .bpe-hero { display: flex; grid-area: 1 / 1; min-width: 0; min-height: 0; flex-direction: column; justify-content: safe center; gap: clamp(12px, 2vh, 24px); width: min(100%, 1320px); margin-inline: auto; overflow: hidden; }
  .bpe-who { display: flex; flex-shrink: 0; align-items: center; gap: clamp(14px, 1.6vw, 28px); }
  .bpe-id { display: flex; min-width: 0; flex: 1 1 0; flex-direction: column; gap: 3px; }
  .bpe-state { color: var(--bp-lit); font-weight: 600; }
  .bpe-state[data-tone="muted"] { color: var(--bp-muted); }
  .bpe-state[data-tone="warn"] { color: var(--color-warn); }
  .bpe-state[data-tone="bad"] { color: var(--color-bad); }
  .bpe-state[data-tone="good"] { color: var(--color-good); }
  .bpe-do { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }

  .bpe-grid { display: grid; min-height: 0; grid-template-columns: minmax(0, 1fr); gap: clamp(14px, 2vw, 40px); align-items: start; container-type: inline-size; }
  @media (min-width: 1000px) {
    .bpe-grid { grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr); }
  }
  .bpe-told { display: flex; min-width: 0; flex-direction: column; gap: 10px; padding: clamp(14px, 1.7vw, 30px); overflow: hidden; }
  .bpe-foot { font-size: 12.5px; color: var(--bp-faint); }
  .bpe-none { font-size: 16px; color: var(--bp-muted); }
  .bpe-write { align-self: flex-start; }
  .bpe-msgs { display: flex; min-width: 0; flex-direction: column; gap: 6px; overflow: hidden; }
  .bpe-msgs .bp-label { margin-bottom: 4px; }
  .bpe-msg { display: flex; min-width: 0; max-width: 88%; }
  .bpe-msg.is-mine { align-self: flex-end; }
  .bpe-bubble {
    min-width: 0;
    padding: 10px 15px;
    overflow-wrap: anywhere;
    border-radius: 19px;
    font-size: clamp(14.5px, 1.1vw, 19px);
    line-height: 1.36;
    background: color-mix(in srgb, var(--color-ink) 11%, transparent);
  }
  .bpe-msg.is-mine .bpe-bubble { background: color-mix(in srgb, var(--color-accent) 58%, rgb(0 0 0 / 0.3)); }

  .bpe-shelfwrap { display: flex; flex-shrink: 0; min-width: 0; flex-direction: column; gap: 6px; }
  .bpe-sort { display: flex; gap: 4px; }
  .bpe-sort .bp-chip { height: 30px; padding: 0 12px; font-size: 13px; }
  .bpe-shelfbox { position: relative; min-width: 0; }
  /* The shelf's bar (lib/hscroll.ts) stays a hairline: it only says how far along you are, and the plate is what is lit. */
  .bpe-shelfbox.hscroll:global(.can-scroll:hover) :global(.hscroll-bar) { height: 3px; background: none; }
  .bpe-shelfbox.hscroll:global(.can-scroll) :global(.hscroll-thumb) { background: var(--bp-line); }
  .bpe-shelf { display: flex; min-width: 0; gap: 2px; overflow-x: auto; overscroll-behavior: contain; scrollbar-width: none; padding-bottom: 2px; }
  .bpe-shelf::-webkit-scrollbar { display: none; }
  :global(.bpe-person) {
    width: clamp(96px, 7vw, 124px);
    flex-shrink: 0;
    flex-direction: column;
    gap: 5px;
    padding: 9px 6px 8px;
    text-align: center;
  }
  /* The one on the card above: its face a touch larger, and its name lit. */
  :global(.bpe-person) .bp-face { transition: transform 0.45s var(--spring); }
  :global(.bpe-person.is-on) .bp-face { transform: scale(1.1); }
  .bpe-pname { width: 100%; overflow: hidden; font-size: 13.5px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; transition: color 0.2s ease; }
  :global(.bpe-person:not(.is-on)) .bpe-pname { color: var(--bp-muted); }
  .bpe-psub { width: 100%; overflow: hidden; font-size: 11.5px; text-overflow: ellipsis; white-space: nowrap; color: var(--bp-faint); }
  .bpe-medal { position: absolute; top: -5px; right: -7px; display: grid; }
  .bpe-waiting { position: absolute; top: 1px; left: 1px; width: 13px; height: 13px; border-radius: 999px; background: var(--bp-lit); }

  /* A short screen: the shelf and the words keep the room, and the face gets smaller. */
  @media (max-height: 760px) {
    .bpe-who :global(.bp-face) { transform: scale(0.8); transform-origin: left center; margin-right: -14px; }
    .bpe-told :global(.sm-lead) { font-size: 18px; }
  }
  @media (max-width: 720px) {
    .bpe { height: auto; }
    .bpe-stage { flex: none; }
    .bpe-hero { overflow: visible; }
    .bpe-who { flex-wrap: wrap; }
  }
</style>
