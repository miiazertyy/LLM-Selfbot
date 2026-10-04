<script lang="ts">
  /**
   * Who is waiting, down the left: each one a card with where its reply is, a
   * ring counting down to it, and their last message. The one on stage has its
   * avatar lifted out: it flew to the stage (see motion.ts). A click puts
   * someone on stage, with a ripple where it landed.
   */
  import { flip } from "svelte/animate";
  import { backOut } from "svelte/easing";
  import Avatar from "../components/Avatar.svelte";
  import { progress, type Status } from "../chatstatus";
  import type { ChatUser, ChatAccount } from "../chats";
  import { popIn, receiveAvatar, sendAvatar } from "./motion";

  type QRow = { key: string; target: string; u: ChatUser; st: Status; account?: ChatAccount };

  let {
    rows = [],
    spotlight = null,
    multi = false,
    hideText = false,
    now = 0,
    onpick,
  }: {
    rows?: QRow[];
    spotlight?: string | null;
    multi?: boolean;
    hideText?: boolean;
    now?: number;
    onpick?: (key: string) => void;
  } = $props();

  /** A ripple from where the card was pressed, gone when its animation ends. */
  function ripple(node: HTMLElement) {
    function down(e: PointerEvent) {
      const r = node.getBoundingClientRect();
      const dot = document.createElement("span");
      dot.className = "bpq-ripple";
      dot.style.left = `${e.clientX - r.left}px`;
      dot.style.top = `${e.clientY - r.top}px`;
      node.appendChild(dot);
      dot.addEventListener("animationend", () => dot.remove(), { once: true });
    }
    node.addEventListener("pointerdown", down);
    return { destroy: () => node.removeEventListener("pointerdown", down) };
  }

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
  const C = 2 * Math.PI * 26;

  // ── Scrolling ────────────────────────────────────────────────────────────
  // A long queue scrolls, fading out at whichever edge has more behind it,
  // and whoever is put on stage is brought into view.
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
    for (const c of Array.from(el.children)) ro.observe(c);
    edges();
    return () => ro.disconnect();
  });
  $effect(() => {
    void rows.length;
    queueMicrotask(edges);
  });
  $effect(() => {
    const key = spotlight;
    if (!key || !listEl) return;
    const card = listEl.querySelector<HTMLElement>(`[data-key="${CSS.escape(key)}"]`);
    card?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
</script>

<section class="bpq">
  <header class="bp-label">Queue <span class="bp-n">{rows.length}</span></header>
  {#if !rows.length}
    <p class="bpq-empty" in:popIn>Nobody is waiting. Everyone has been answered.</p>
  {/if}
  <div class="bpq-list" class:is-above={above} class:is-below={below} bind:this={listEl} onscroll={edges}>
    {#each rows as r (r.key)}
      <button class="bpq-card" class:is-spot={r.key === spotlight} data-tone={r.st.tone} data-step={r.st.step ?? 0}
              data-key={r.key}
              use:ripple onclick={() => onpick?.(r.key)} animate:flip={{ duration: 520, easing: backOut }} in:popIn>
        <span class="bpq-av">
          <svg class="bpq-ring" viewBox="0 0 60 60" aria-hidden="true">
            <circle cx="30" cy="30" r="26" class="track" />
            <circle cx="30" cy="30" r="26" class="fill"
                    style="stroke-dasharray: {C}; stroke-dashoffset: {r.st.step === 1 || r.st.step === 3 ? C * (1 - progress(r.st, now)) : r.st.step ? 0 : C}" />
          </svg>
          {#if r.key !== spotlight}
            <span class="bpq-face" in:receiveAvatar|global={{ key: r.key }} out:sendAvatar|global={{ key: r.key }}>
              <Avatar src={r.u.avatar} name={r.u.name} size={42} zoom={false} />
            </span>
          {:else}
            <span class="bpq-face is-away"></span>
          {/if}
        </span>
        <span class="bpq-body">
          <span class="bpq-top">
            <span class="bpq-name">{r.u.name}</span>
            {#if r.u.kind === "server"}<span class="bpq-where">{(r.u.where ?? "").split(" · ")[0]}</span>{/if}
          </span>
          <span class="bpq-state">{r.st.short}</span>
          <span class="bpq-snip" class:is-hidden={hideText}>{snippet(r.u)}</span>
        </span>
        {#if multi && r.account}
          <span class="bpq-acct" title={r.account.display_name || r.account.username || r.account.id}>
            <Avatar src={r.account.avatar} name={r.account.display_name || r.account.id} size={18} zoom={false} />
          </span>
        {/if}
      </button>
    {/each}
  </div>
</section>

<style>
  .bpq { display: flex; min-height: 0; flex-direction: column; gap: 12px; }
  .bpq-empty { padding: 18px 4px; font-size: 14px; line-height: 1.5; color: var(--bp-faint); }
  .bpq-list {
    display: flex;
    min-height: 0;
    flex-direction: column;
    gap: 10px;
    overflow-y: auto;
    /* Room on every side for a card's glow. Scrolling vertically means this box
       clips horizontally too, and with a couple of pixels of padding the
       spotlighted card's bloom was sliced off straight down both edges. */
    padding: 10px 16px 18px;
    overscroll-behavior: contain;
    scrollbar-width: none;
    --fade-top: 0px;
    --fade-bottom: 0px;
    -webkit-mask-image: linear-gradient(to bottom, transparent, #000 var(--fade-top), #000 calc(100% - var(--fade-bottom)), transparent);
    mask-image: linear-gradient(to bottom, transparent, #000 var(--fade-top), #000 calc(100% - var(--fade-bottom)), transparent);
  }
  .bpq-list.is-above { --fade-top: 28px; }
  .bpq-list.is-below { --fade-bottom: 56px; }
  .bpq-list::-webkit-scrollbar { display: none; }
  .bpq-card {
    position: relative;
    display: flex;
    /* Each card keeps its height and the list scrolls. With overflow hidden a
       flex item may shrink to nothing, so a long queue squeezed the cards
       until the names spilled over each other instead of scrolling. */
    flex-shrink: 0;
    align-items: center;
    gap: 12px;
    padding: 12px 14px 12px 12px;
    overflow: hidden;
    border-radius: 20px;
    text-align: left;
    background: rgb(255 255 255 / 0.045);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.07);
    backdrop-filter: blur(18px);
    transition: transform 0.35s var(--spring), background-color 0.25s ease, box-shadow 0.25s ease;
  }
  .bpq-card:hover { transform: translateX(4px) scale(1.015); background: rgb(255 255 255 / 0.07); }
  .bpq-card:active { transform: scale(0.97); }
  .bpq-card.is-spot {
    background: color-mix(in srgb, var(--color-accent) 16%, rgb(255 255 255 / 0.04));
    box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--color-accent) 60%, transparent),
                0 10px 40px -12px color-mix(in srgb, var(--color-accent) 60%, transparent);
  }
  .bpq-av { position: relative; display: grid; width: 60px; height: 60px; flex-shrink: 0; place-items: center; }
  /* overflow: visible, or the ring's glow is cut flat at the viewBox edge. */
  .bpq-ring { position: absolute; inset: 0; transform: rotate(-90deg); overflow: visible; }
  .bpq-ring circle { fill: none; stroke-width: 3; }
  .bpq-ring .track { stroke: rgb(255 255 255 / 0.08); }
  .bpq-ring .fill { stroke: var(--color-accent); stroke-linecap: round; transition: stroke-dashoffset 1s linear; }
  /* The same calm breath as the stage's ring, instead of a spinner. */
  .bpq-card[data-step="2"] .bpq-ring .fill,
  .bpq-card[data-step="3"] .bpq-ring .fill { animation: bpq-breathe 2.6s ease-in-out infinite; }
  .bpq-card[data-step="2"] .bpq-ring .fill { stroke-dasharray: none !important; stroke-dashoffset: 0 !important; }
  .bpq-card[data-step="4"] .bpq-ring .fill { stroke: var(--color-good); }
  .bpq-card[data-tone="bad"] .bpq-ring .fill { stroke: var(--color-bad); }
  @keyframes bpq-breathe { 0%, 100% { opacity: 0.45; } 50% { opacity: 1; } }
  .bpq-face { position: relative; display: grid; place-items: center; border-radius: 999px; }
  /* Where the avatar was: it is on stage now. */
  .bpq-face.is-away { width: 42px; height: 42px; border: 1.5px dashed color-mix(in srgb, var(--color-accent) 55%, transparent); }
  .bpq-body { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 1px; }
  .bpq-top { display: flex; min-width: 0; align-items: baseline; gap: 6px; }
  .bpq-name { overflow: hidden; font-size: 15.5px; font-weight: 650; color: #fff; text-overflow: ellipsis; white-space: nowrap; }
  /* A long channel name gives way before the person's name does, and neither leaves the card. */
  .bpq-where { min-width: 0; max-width: 45%; flex-shrink: 1; overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; color: var(--bp-faint); }
  .bpq-state { font-size: 12.5px; font-weight: 600; color: color-mix(in srgb, var(--color-accent) 80%, white); }
  .bpq-card[data-tone="good"] .bpq-state { color: var(--color-good); }
  .bpq-card[data-tone="warn"] .bpq-state { color: var(--color-warn); }
  .bpq-card[data-tone="bad"] .bpq-state { color: var(--color-bad); }
  .bpq-card[data-tone="muted"] .bpq-state { color: var(--bp-faint); }
  .bpq-snip { overflow: hidden; font-size: 12.5px; color: var(--bp-muted); text-overflow: ellipsis; white-space: nowrap; }
  .bpq-snip.is-hidden { filter: blur(5px); }
  .bpq-acct { position: absolute; right: 10px; top: 10px; opacity: 0.8; }
  :global(.bpq-ripple) {
    position: absolute;
    width: 24px;
    height: 24px;
    margin: -12px 0 0 -12px;
    border-radius: 999px;
    pointer-events: none;
    background: color-mix(in srgb, var(--color-accent) 55%, white);
    animation: bpq-ripple 0.7s ease-out forwards;
  }
  @keyframes bpq-ripple { from { opacity: 0.55; transform: scale(0); } to { opacity: 0; transform: scale(16); } }
  :global(:root[data-motion="off"]) .bpq-ring .fill { animation: none; }
</style>
