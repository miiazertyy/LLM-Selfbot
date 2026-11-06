<script lang="ts">
  /**
   * Who is waiting, down the left, read in the order it matters: who is being
   * answered, who is next, and who is waiting on you (the ones it will not answer
   * unless told to). Rows, not cards: they sit straight on the room, with the
   * plate sliding under the one in hand. The one on stage has its face lifted out:
   * it flew to the stage (motion.ts).
   *
   * What is waiting on you can pile up (everything that came in while the bot was
   * off), so past a few it folds, and opens in place. Any row that can be hurried
   * has Reply now on it as the pointer comes.
   *
   * One flat list for all of it, headings and all, so a row going from "next" to
   * "being answered" glides there instead of vanishing and popping up.
   */
  import { flip } from "svelte/animate";
  import { backOut } from "svelte/easing";
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import PlatformMark from "../components/PlatformMark.svelte";
  import { progress } from "../chatstatus";
  import type { ChatUser } from "../chats";
  import { platformOfUser } from "../platforms";
  import { focusable, follow } from "./focus";
  import { popIn, receiveAvatar, sendAvatar } from "./motion";
  import type { QRow } from "./types";

  let {
    answering = [],
    next = [],
    waiting = [],
    spotlight = null,
    multi = false,
    now = 0,
    replying = {},
    onpick,
    onreply,
  }: {
    answering?: QRow[];
    next?: QRow[];
    waiting?: QRow[];
    spotlight?: string | null;
    multi?: boolean;
    now?: number;
    /** Replies asked for by hand, on their way, by the row's id. */
    replying?: Record<string, boolean>;
    onpick?: (key: string) => void;
    onreply?: (r: QRow) => void;
  } = $props();

  /** How many of the ones waiting on you show before the rest fold. */
  const FOLD = 4;
  let unfolded = $state(false);

  type Item = { kind: "head"; key: string; label: string; n: number } | { kind: "row"; key: string; r: QRow }
            | { kind: "more"; key: string; n: number };
  const items = $derived.by<Item[]>(() => {
    const out: Item[] = [];
    const add = (id: string, label: string, rows: QRow[]) => {
      if (!rows.length) return;
      out.push({ kind: "head", key: `head:${id}`, label, n: rows.length });
      for (const r of rows) out.push({ kind: "row", key: r.key, r });
    };
    add("answering", "Answering", answering);
    add("next", "Up next", next);
    add("waiting", "Waiting on you", unfolded ? waiting : waiting.slice(0, FOLD));
    if (waiting.length > FOLD) out.push({ kind: "more", key: "more", n: waiting.length - FOLD });
    return out;
  });

  /** "[sticker: Wave]" and the like are what the bot's own records say; read them as words. */
  function plain(text: string): string {
    const m = text.trim().match(/^\[(sticker|attachment|image|video|voice message|file)(?::\s*([^\]]+))?\]$/i);
    if (!m) return text;
    const what = m[1].toLowerCase();
    if (what === "sticker") return m[2] ? `Sticker: ${m[2].trim()}` : "Sent a sticker";
    return { attachment: "Sent an attachment", image: "Sent a picture", video: "Sent a video",
             "voice message": "Sent a voice message", file: "Sent a file" }[what] ?? text;
  }
  const snippet = (u: ChatUser) =>
    plain(u.text || u.snippet || (u.attachments?.length ? "Sent an attachment"
      : u.stickers?.length ? `Sticker: ${u.stickers[0].name}` : "")).replace(/\s+/g, " ");
  /** One still being written or typed cannot be hurried: there is nothing left to skip. */
  const hurried = (r: QRow) => r.st.phase === "needs" || r.st.step === 1 || r.st.step === 3;
  const C = 2 * Math.PI * 25;

  // ── Scrolling ────────────────────────────────────────────────────────────
  // A long queue scrolls, fading out at whichever edge has more behind it, and
  // whoever is put on stage is brought into view.
  let listEl: HTMLElement | null = $state(null);
  let above = $state(false);
  let below = $state(false);
  function edges() {
    const el = listEl;
    if (!el) return;
    above = el.scrollTop > 4;
    below = el.scrollTop + el.clientHeight < el.scrollHeight - 4;
  }
  $effect(() => {
    const el = listEl;
    if (!el) return;
    const ro = new ResizeObserver(edges);
    ro.observe(el);
    edges();
    return () => ro.disconnect();
  });
  $effect(() => {
    void items.length;
    // The rows have moved under the plate.
    follow(700);
    queueMicrotask(edges);
  });
  $effect(() => {
    const key = spotlight;
    if (!key || !listEl) return;
    const list = listEl;
    const card = list.querySelector<HTMLElement>(`[data-key="${CSS.escape(key)}"]`);
    if (!card || list.scrollHeight <= list.clientHeight) return;
    // Inside its own list, never by moving the view: on a phone the view itself scrolls, and
    // someone arriving in the queue took the stage they had just gone on off the screen.
    const l = list.getBoundingClientRect(), r = card.getBoundingClientRect();
    if (r.top < l.top) list.scrollBy({ top: r.top - l.top - 8, behavior: "smooth" });
    else if (r.bottom > l.bottom) list.scrollBy({ top: r.bottom - l.bottom + 8, behavior: "smooth" });
  });
</script>

<section class="bpq">
  <div class="bpq-list bp-scrolls" class:is-above={above} class:is-below={below} bind:this={listEl} onscroll={edges}>
    {#each items as it (it.key)}
      <div class="bpq-item" class:is-head={it.kind === "head"} animate:flip={{ duration: 520, easing: backOut }} in:popIn={{ from: 0.94 }}>
        {#if it.kind === "head"}
          <div class="bp-label bpq-head">{it.label}<span class="bpq-n">{it.n}</span></div>
        {:else if it.kind === "more"}
          <button class="bp-row bpq-more" use:focusable={{ id: "queue:more" }} onclick={() => (unfolded = !unfolded)}>
            <Icon name="chevron" size={13} />{unfolded ? "Fewer" : `${it.n} more`}
          </button>
        {:else}
          {@const r = it.r}
          <div class="bpq-rowwrap">
            <button class="bp-row bpq-row" class:is-spot={r.key === spotlight} data-tone={r.st.tone} data-step={r.st.step ?? 0} data-key={r.key}
                    use:focusable={{ id: r.key, first: r.key === spotlight }} onclick={() => onpick?.(r.key)}>
              <span class="bp-face bpq-av">
                <svg class="bpq-ring" viewBox="0 0 56 56" aria-hidden="true"><circle cx="28" cy="28" r="25" class="track" /></svg>
                <svg class="bpq-ring is-fill" viewBox="0 0 56 56" aria-hidden="true">
                  <circle cx="28" cy="28" r="25" class="fill"
                          style="stroke-dasharray: {C}; stroke-dashoffset: {r.st.step === 1 || r.st.step === 3 ? C * (1 - progress(r.st, now)) : r.st.step ? 0 : C}" />
                </svg>
                {#if r.key !== spotlight}
                  <span class="bpq-face" in:receiveAvatar|global={{ key: r.key }} out:sendAvatar|global={{ key: r.key }}>
                    <Avatar src={r.u.avatar} name={r.u.name} size={42} zoom={false} />
                  </span>
                {:else}
                  <span class="bpq-face is-away"></span>
                {/if}
                <span class="bp-mark"><PlatformMark platform={r.account?.platform ?? platformOfUser(r.u.id).id} size={17} /></span>
              </span>
              <span class="bpq-body">
                <span class="bpq-top">
                  <span class="bpq-name">{r.u.name}</span>
                  {#if r.u.kind === "server"}<span class="bpq-where">{(r.u.where ?? "").split(" · ")[0]}</span>{/if}
                </span>
                <span class="bpq-state">{r.st.short}</span>
                <span class="bpq-snip" data-private="soft">{snippet(r.u)}</span>
              </span>
              {#if multi && r.account}
                <span class="bpq-acct" title={r.account.display_name || r.account.username || r.account.id}>
                  <Avatar src={r.account.avatar} name={r.account.display_name || r.account.id} size={16} zoom={false} />
                </span>
              {/if}
            </button>
            {#if hurried(r)}
              <button class="bp-btn is-small is-round bpq-now" onclick={() => onreply?.(r)} disabled={!!replying[r.u.id]}
                      title="Reply now" aria-label="Reply now to {r.u.name}">
                <Icon name="reply" size={15} />
              </button>
            {/if}
          </div>
        {/if}
      </div>
    {/each}
  </div>
</section>

<style>
  .bpq { display: flex; height: 100%; min-height: 0; flex-direction: column; }
  .bpq-list {
    display: flex;
    min-height: 0;
    flex: 1 1 auto;
    flex-direction: column;
    gap: 2px;
    overflow-y: auto;
    padding-bottom: 12px;
    --fade-top: 0px;
    --fade-bottom: 0px;
    -webkit-mask-image: linear-gradient(to bottom, transparent, #000 var(--fade-top), #000 calc(100% - var(--fade-bottom)), transparent);
    mask-image: linear-gradient(to bottom, transparent, #000 var(--fade-top), #000 calc(100% - var(--fade-bottom)), transparent);
  }
  .bpq-list.is-above { --fade-top: 28px; }
  .bpq-list.is-below { --fade-bottom: 56px; }
  /* Each keeps its height and the list scrolls: with overflow hidden a flex item
     may shrink to nothing, and a long queue squeezed its rows until the names
     spilled over each other. */
  .bpq-item { flex-shrink: 0; }
  .bpq-item.is-head { padding: 14px 10px 5px; }
  .bpq-item.is-head:first-child { padding-top: 2px; }
  .bpq-head { justify-content: space-between; }
  .bpq-n { font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .bpq-more { gap: 6px; height: 40px; padding: 0 12px; font-size: 13.5px; font-weight: 600; color: var(--bp-muted); }
  .bpq-more :global(svg) { transform: rotate(90deg); }

  .bpq-rowwrap { position: relative; }
  .bpq-row { padding: 8px 10px; }
  .bpq-row.is-spot { background: var(--bp-fill); }
  .bpq-av { width: 56px; height: 56px; }
  /* overflow: visible, or the ring's round cap is cut flat at the viewBox edge. */
  .bpq-ring { position: absolute; inset: 0; transform: rotate(-90deg); overflow: visible; }
  .bpq-ring circle { fill: none; stroke-width: 3; }
  .bpq-ring .track { stroke: var(--bp-line); }
  /* A ring is drawn on the page's own thread, every frame its arc moves: a smooth second's worth of it, begun again
     every second, was a style pass at the screen's 143 a second for as long as the view was open, and most of what it
     cost sitting still. Four steps a second look the same on a ring this size. */
  .bpq-ring .fill { stroke: var(--bp-lit); stroke-linecap: round; transition: stroke-dashoffset 1s steps(4, jump-none); }
  /* The same calm breath as the stage's ring, instead of a spinner. */
  /* The breath on the fill's own svg, which the graphics card fades by itself; a circle in an svg it cannot. */
  .bpq-row[data-step="2"] .bpq-ring.is-fill,
  .bpq-row[data-step="3"] .bpq-ring.is-fill { animation: bpq-breathe 2.6s ease-in-out infinite; }
  .bpq-row[data-step="2"] .bpq-ring .fill { stroke-dasharray: none !important; stroke-dashoffset: 0 !important; }
  .bpq-row[data-step="4"] .bpq-ring .fill { stroke: var(--color-good); }
  .bpq-row[data-tone="bad"] .bpq-ring .fill { stroke: var(--color-bad); }
  @keyframes bpq-breathe { 0%, 100% { opacity: 0.45; } 50% { opacity: 1; } }
  .bpq-face { position: relative; display: grid; place-items: center; border-radius: 999px; }
  /* Where the face was: it is on stage now. */
  .bpq-face.is-away { width: 42px; height: 42px; background: var(--bp-fill); }
  .bpq-body { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 1px; }
  .bpq-top { display: flex; min-width: 0; align-items: baseline; gap: 6px; }
  .bpq-name { overflow: hidden; font-size: clamp(14.5px, 0.95vw, 17px); font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
  /* A long channel name gives way before the person's name does, and neither leaves the row. */
  .bpq-where { min-width: 0; max-width: 45%; flex-shrink: 1; overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; color: var(--bp-faint); }
  .bpq-state { font-size: 12.5px; font-weight: 600; color: var(--bp-lit); }
  .bpq-row[data-tone="good"] .bpq-state { color: var(--color-good); }
  .bpq-row[data-tone="warn"] .bpq-state { color: var(--color-warn); }
  .bpq-row[data-tone="bad"] .bpq-state { color: var(--color-bad); }
  .bpq-row[data-tone="muted"] .bpq-state { color: var(--bp-faint); }
  .bpq-snip { overflow: hidden; font-size: 12.5px; color: var(--bp-faint); text-overflow: ellipsis; white-space: nowrap; }
  .bpq-acct { position: absolute; right: 10px; top: 9px; opacity: 0.8; }
  /* Comes as the pointer does: the row can always be pressed, this is only the short way. */
  .bpq-now {
    position: absolute;
    right: 8px;
    bottom: 10px;
    opacity: 0;
    transition: opacity 0.18s ease, transform 0.45s var(--jelly);
  }
  .bpq-rowwrap:hover .bpq-now, .bpq-now:focus-visible { opacity: 1; }
  @media (hover: none) { .bpq-now { opacity: 1; } }
  :global(:root[data-motion="off"]) .bpq-ring.is-fill { animation: none; }
  :global(:root[data-motion="off"]) .bpq-ring .fill { transition: none; }
</style>
