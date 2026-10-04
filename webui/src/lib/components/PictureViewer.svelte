<script lang="ts">
  /**
   * A picture at full size, without a box round it: it grows out of its card
   * to the middle of the window over a light veil, what the bot reads about
   * it in a slim caption underneath, and it goes back into its card when put
   * away (a click anywhere off it, Escape, the cross). The arrows, or ← and
   * →, step through the others, each sliding in from its side. A video plays
   * with its sound and its controls.
   *
   * It used to open in a dialog the width of the page, with a title bar and a
   * plate of empty space round a tall picture.
   */
  import { tick } from "svelte";
  import { get } from "svelte/store";
  import { motionEnabled } from "../stores";
  import { play } from "../uisound";
  import { renderMarkdown } from "../markdown";
  import { clock } from "../pictures";
  import Icon from "./Icon.svelte";

  type Pic = { name: string; id?: string; description: string; size?: number; video?: boolean; duration?: number };

  let {
    items,
    current = null,
    src,
    thumb,
    originOf,
    onnav,
    onclose,
    onedit,
  }: {
    items: Pic[];
    /** The one on show; null when shut. */
    current?: Pic | null;
    src: (p: Pic) => string;
    thumb: (p: Pic) => string;
    /** Its picture on the page, to grow out of and go back into. */
    originOf: (p: Pic) => HTMLElement | null;
    onnav: (p: Pic) => void;
    onclose: () => void;
    onedit: (p: Pic) => void;
  } = $props();

  const keyOf = (p: Pic) => p.id || p.name;
  const at = $derived(current ? items.findIndex((x) => keyOf(x) === keyOf(current!)) : -1);
  const many = $derived(items.length > 1);
  /** Which way the last step went, for the side the next one slides in from. */
  let dir = $state(0);
  let media: HTMLElement | null = $state(null);
  let root: HTMLElement | null = $state(null);
  let leaving = $state(false);
  const moving = () => get(motionEnabled) && document.documentElement.dataset.motion !== "off";

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  /** Where a picture shows inside its card's box: the card fits the whole picture in (object-fit: contain). */
  function shownRect(el: HTMLElement, aspect: number): DOMRect {
    const r = el.getBoundingClientRect();
    if (!aspect || !r.width || !r.height) return r;
    const boxAspect = r.width / r.height;
    const w = aspect > boxAspect ? r.width : r.height * aspect;
    const h = aspect > boxAspect ? r.width / aspect : r.height;
    return new DOMRect(r.left + (r.width - w) / 2, r.top + (r.height - h) / 2, w, h);
  }
  function aspectOf(el: HTMLElement | null): number {
    if (el instanceof HTMLImageElement) return el.naturalWidth / (el.naturalHeight || 1);
    if (el instanceof HTMLVideoElement) return el.videoWidth / (el.videoHeight || 1);
    return 0;
  }
  const onScreen = (r: DOMRect) => r.width > 0 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;

  /** From the card's picture to here: the same shape, moved and scaled, landing with a little give. */
  async function growFrom(p: Pic) {
    await tick();
    const el = media;
    const from = originOf(p);
    if (!el || !from || !moving()) return;
    if (el instanceof HTMLImageElement && !el.complete) await el.decode().catch(() => {});
    const to = el.getBoundingClientRect();
    const start = shownRect(from, aspectOf(el) || (from instanceof HTMLImageElement ? from.naturalWidth / (from.naturalHeight || 1) : 0));
    if (!onScreen(start) || !to.width) return;
    const s = start.width / to.width;
    const dx = start.left + start.width / 2 - (to.left + to.width / 2);
    const dy = start.top + start.height / 2 - (to.top + to.height / 2);
    el.animate([{ transform: `translate(${dx}px, ${dy}px) scale(${s})`, borderRadius: "14px" }, { transform: "none" }],
               { duration: 460, easing: "cubic-bezier(0.2, 0.95, 0.25, 1.04)" });
  }

  // Opened: grown out of its card, with a whoosh. Stepping: no grow, a slide (the {#key} below).
  let shownKey = "";
  $effect(() => {
    const p = current;
    if (!p) {
      shownKey = "";
      return;
    }
    const k = keyOf(p);
    const opening = !shownKey;
    shownKey = k;
    if (opening) {
      leaving = false;
      dir = 0;
      play("open");
      growFrom(p);
      tick().then(() => root?.focus({ preventScroll: true }));
    }
    // The ones either side, fetched ahead so a step is instant.
    for (const n of [items[at + 1], items[at - 1]]) if (n && !n.video) new Image().src = src(n);
  });

  function step(by: number) {
    if (!many || at < 0) return;
    dir = by;
    play("slide", { level: 0.5 });
    onnav(items[(at + by + items.length) % items.length]);
  }

  /** Back into its card when that is on screen, else shrinking away; then shut. */
  async function close() {
    if (!current || leaving) return;
    leaving = true;
    const el = media;
    const from = originOf(current);
    if (el && moving()) {
      const to = el.getBoundingClientRect();
      const end = from ? shownRect(from, aspectOf(el)) : null;
      const anim = end && onScreen(end) && to.width
        ? el.animate([{ transform: "none" }, {
            transform: `translate(${end.left + end.width / 2 - (to.left + to.width / 2)}px, ${end.top + end.height / 2 - (to.top + to.height / 2)}px) scale(${end.width / to.width})`,
            borderRadius: "14px" }], { duration: 300, easing: "cubic-bezier(0.4, 0, 0.6, 1)", fill: "forwards" })
        : el.animate([{ opacity: 1 }, { opacity: 0, transform: "scale(0.92)" }], { duration: 200, easing: "ease-in", fill: "forwards" });
      await anim.finished.catch(() => {});
    }
    onclose();
  }

  function onKey(e: KeyboardEvent) {
    if (!current) return;
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
  }

  function kb(bytes?: number): string {
    if (!bytes) return "";
    return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
  }
</script>

<svelte:window onkeydown={onKey} />

{#if current}
  {@const p = current}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
  <div class="pv" class:is-leaving={leaving} bind:this={root} use:portal role="dialog" aria-label={p.name} tabindex="-1"
       onclick={(e) => { if (e.target === e.currentTarget || (e.target as HTMLElement).classList.contains("pv-stage")) close(); }}>
    <button type="button" class="pv-x" onclick={close} aria-label="Close" title="Close (Esc)"><Icon name="close" size={14} /></button>
    {#if many}
      <button type="button" class="pv-nav is-prev" onclick={() => step(-1)} aria-label="The one before" title="The one before (←)">
        <Icon name="chevron" size={16} />
      </button>
      <button type="button" class="pv-nav is-next" onclick={() => step(1)} aria-label="The next one" title="The next one (→)">
        <Icon name="chevron" size={16} />
      </button>
    {/if}

    <div class="pv-stage">
      {#key keyOf(p)}
        <figure class="pv-fig" style="--dir: {dir}">
          {#if p.video}
            <video bind:this={media} class="pv-media" src={src(p)} poster={thumb(p)} controls autoplay loop playsinline><track kind="captions" /></video>
          {:else}
            <img bind:this={media} class="pv-media" src={src(p)} alt={p.name} />
          {/if}
          <!-- What the bot reads about it, and what can be done, slim under it. -->
          <figcaption class="pv-cap">
            {#if p.description}
              <div class="pv-text markdown"><span class="pv-mark"><Icon name="sparkle" size={12} /></span>{@html renderMarkdown(p.description)}</div>
            {:else}
              <p class="pv-text is-none">No description, so the bot can never send this one.</p>
            {/if}
            <div class="pv-meta">
              <span class="pv-name">{p.name}</span>
              {#if p.video && p.duration}<span>{clock(p.duration)}</span>{/if}
              {#if p.size}<span>{kb(p.size)}</span>{/if}
              {#if many && at >= 0}<span>{at + 1} of {items.length}</span>{/if}
              <button type="button" class="pv-edit" onclick={() => onedit(p)}>
                <Icon name="edit" size={11} />{p.description ? "Edit" : "Write one"}
              </button>
            </div>
          </figcaption>
        </figure>
      {/key}
    </div>
  </div>
{/if}

<style>
  /* A light veil, not a dark room: the page is still there behind it. */
  .pv {
    position: fixed;
    inset: 0;
    z-index: 130;
    display: grid;
    place-items: center;
    outline: none;
    background: rgb(6 6 14 / 0.42);
    backdrop-filter: blur(6px) saturate(0.95);
    -webkit-backdrop-filter: blur(6px) saturate(0.95);
    animation: pv-veil 0.28s ease both;
  }
  @keyframes pv-veil { from { background-color: rgb(6 6 14 / 0); backdrop-filter: blur(0); } }
  .pv.is-leaving { animation: pv-unveil 0.3s ease both; }
  @keyframes pv-unveil { to { background-color: rgb(6 6 14 / 0); backdrop-filter: blur(0); } }
  .pv-stage { display: grid; width: 100%; height: 100%; place-items: center; padding: 28px 72px; overflow: hidden; }
  .pv-fig {
    display: flex;
    max-width: 100%;
    max-height: 100%;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    margin: 0;
    animation: pv-step 0.38s cubic-bezier(0.25, 1, 0.35, 1);
  }
  /* A step: in from the side it was stepped towards. Opening (no side): no slide, it grows from its card instead. */
  @keyframes pv-step { from { opacity: calc(1 - min(1, var(--dir) * var(--dir))); transform: translateX(calc(var(--dir) * 46px)); } }
  .pv-media {
    display: block;
    max-width: min(86vw, 1100px);
    max-height: calc(100vh - 190px);
    border-radius: 14px;
    background: #000;
    box-shadow: 0 30px 80px -20px rgb(0 0 0 / 0.8), 0 0 0 1px rgb(255 255 255 / 0.06);
    transform-origin: center;
    will-change: transform;
  }
  .pv-cap {
    display: flex;
    width: min(620px, 86vw);
    flex-direction: column;
    gap: 6px;
    padding: 10px 14px;
    border-radius: 14px;
    background: color-mix(in srgb, var(--color-card) 82%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent), 0 16px 40px -18px rgb(0 0 0 / 0.7);
    animation: pv-cap 0.42s var(--swift) 0.16s backwards;
  }
  @keyframes pv-cap { from { opacity: 0; transform: translateY(10px); } }
  .pv.is-leaving .pv-cap { opacity: 0; transition: opacity 0.15s ease; }
  .pv-text { max-height: 7.2em; overflow-y: auto; font-size: 13px; line-height: 1.6; color: color-mix(in srgb, var(--color-ink) 88%, transparent); }
  .pv-text :global(.md-p) { display: inline; }
  .pv-text.is-none { color: var(--color-warn); }
  .pv-mark { display: inline-grid; margin-right: 6px; vertical-align: -1px; color: var(--color-accent); }
  .pv-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 12px; font-size: 11px; color: var(--color-faint); }
  .pv-name { font-family: ui-monospace, monospace; color: var(--color-muted); }
  .pv-edit {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    margin-left: auto;
    padding: 3px 9px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .pv-edit:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.1); }

  /* Round glass buttons at the edges, quiet until pointed at. */
  .pv-x, .pv-nav {
    position: absolute;
    z-index: 2;
    display: grid;
    place-items: center;
    border-radius: 999px;
    color: rgb(255 255 255 / 0.85);
    background: rgb(255 255 255 / 0.08);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.12);
    backdrop-filter: blur(8px);
    transition: background-color 0.15s ease, transform 0.35s var(--jelly), opacity 0.2s ease;
    animation: pv-fade 0.3s ease 0.1s backwards;
  }
  @keyframes pv-fade { from { opacity: 0; } }
  .pv-x { top: 16px; right: 16px; width: 36px; height: 36px; }
  .pv-nav { top: 50%; width: 44px; height: 44px; margin-top: -22px; }
  .pv-nav.is-prev { left: 16px; }
  .pv-nav.is-prev :global(svg) { transform: rotate(180deg); }
  .pv-nav.is-next { right: 16px; }
  .pv-x:hover, .pv-nav:hover { background: rgb(255 255 255 / 0.16); }
  .pv-nav.is-prev:hover { transform: translateX(-2px) scale(1.06); }
  .pv-nav.is-next:hover { transform: translateX(2px) scale(1.06); }
  .pv-x:hover { transform: rotate(90deg); }
  .pv.is-leaving .pv-x, .pv.is-leaving .pv-nav { opacity: 0; }
  @media (max-width: 640px) {
    .pv-stage { padding: 56px 12px 16px; }
    .pv-nav { top: auto; bottom: 18px; margin-top: 0; }
    .pv-media { max-height: calc(100vh - 230px); }
  }

  :global(:root[data-motion="off"]) .pv,
  :global(:root[data-motion="off"]) .pv-fig,
  :global(:root[data-motion="off"]) .pv-cap,
  :global(:root[data-motion="off"]) .pv-x,
  :global(:root[data-motion="off"]) .pv-nav { animation: none; transition: none; }
</style>
