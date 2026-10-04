<script lang="ts">
  /**
   * A profile's face, picked in a small panel beside the face itself rather
   * than in a box over the whole page: the page stays as it was, nothing is
   * dimmed, and a click anywhere else puts it away.
   *
   * Its pictures as small tiles (blurred while the Pictures blur is on, each
   * clear under the pointer, all of them with the eye), an Upload tile first,
   * each a small copy of the picture (media_routes.py, thumb): full photos
   * decoded and blurred for 58px tiles made the grid stutter as it scrolled,
   * as did a fade mask on the scroller and every tile's hover zoom firing as
   * the pointer swept past while it moved (held off while it scrolls),
   * and the bin when it has a face to take off. A picture picked or uploaded
   * opens the crop in the same panel, which widens for it (FaceCrop.svelte);
   * Back returns to the tiles. Only ever shown in this app.
   */
  import { tick } from "svelte";
  import { api } from "../api";
  import { picturesBlur, toast } from "../stores";
  import { play } from "../uisound";
  import Icon from "../components/Icon.svelte";
  import FaceCrop from "./FaceCrop.svelte";
  import PersonaOrb from "./PersonaOrb.svelte";
  import { colorOf, type Persona } from "./logic";

  let {
    persona = null,
    anchor = null,
    onclose,
    onchanged,
  }: {
    /** The profile whose face it is; null when shut. */
    persona?: Persona | null;
    /** What it opens beside: the face on the card. */
    anchor?: HTMLElement | null;
    onclose: () => void;
    /** A face set or taken off: the page refreshes and pops it. */
    onchanged: (pid: string) => void;
  } = $props();

  type Pic = { name: string; id: string };
  const WIDE = 460;
  const NARROW = 336;

  let panel: HTMLElement | null = $state(null);
  let pics = $state<Pic[]>([]);
  let loaded = $state(false);
  let busy = $state(false);
  /** Unblurred for this look: blurred again each time it opens, while the blur preference is on. */
  let shown = $state(false);
  let upload: HTMLInputElement | null = $state(null);
  /** The picture being cropped: one of its own, by name, or a file from this computer. */
  let crop = $state<{ src: string; name?: string; file?: File } | null>(null);
  let pos = $state({ left: 0, top: 0, origin: "left top" });
  /** Scrolling: the tiles' hover zoom and unblur held off, so they do not fire one after another under the pointer. */
  let scrolling = $state(false);
  let scrollTimer = 0;
  function onGridScroll() {
    scrolling = true;
    clearTimeout(scrollTimer);
    scrollTimer = window.setTimeout(() => (scrolling = false), 160);
  }

  const asked = (p: Persona) => (p.id === "default" ? "" : p.id);
  const blurred = $derived($picturesBlur && !shown);

  // Opened for a profile: its pictures, fresh, and blurred again.
  let openFor = "";
  $effect(() => {
    const p = persona;
    if (!p) {
      openFor = "";
      dropCrop();
      return;
    }
    if (openFor === p.id) return;
    openFor = p.id;
    pics = [];
    loaded = false;
    shown = false;
    dropCrop();
    api.pictures(asked(p)).then((r: any) => {
      if (persona?.id !== p.id) return;
      // Videos and moving pictures cannot be a face.
      pics = (r?.pictures ?? []).filter((x: any) => !x.moving).slice(0, 40);
    }).catch(() => {}).finally(() => (loaded = true));
  });

  /** Beside the face when there is room, under it when not, and always on screen. */
  function place() {
    if (!anchor) return;
    const r = anchor.getBoundingClientRect();
    const w = Math.min(crop ? WIDE : NARROW, innerWidth - 16);
    const h = crop ? 540 : 330;
    let left = r.right + 12;
    let top = r.top - 6;
    let origin = "left top";
    if (left + w > innerWidth - 8) {
      left = Math.max(8, Math.min(r.left - 6, innerWidth - w - 8));
      top = r.bottom + 10;
      origin = "top left";
    }
    top = Math.max(8, Math.min(top, innerHeight - h - 8));
    pos = { left, top, origin };
  }
  $effect(() => {
    if (!persona || !anchor) return;
    void crop;
    place();
  });

  // Put away by a click elsewhere, Escape (from the crop, back to the tiles first), the page scrolling or resizing.
  $effect(() => {
    if (!persona) return;
    const off = (e: MouseEvent) => {
      const t = e.target as Node;
      if (busy || !panel || panel.contains(t) || anchor?.contains(t)) return;
      onclose();
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (crop) back();
      else onclose();
    };
    const scrolled = (e: Event) => {
      if (panel && e.target instanceof Node && panel.contains(e.target)) return;
      if (!busy) onclose();
    };
    const t = setTimeout(() => {
      window.addEventListener("pointerdown", off, true);
      window.addEventListener("scroll", scrolled, true);
    }, 0);
    window.addEventListener("keydown", esc);
    window.addEventListener("resize", place);
    tick().then(() => panel?.focus({ preventScroll: true }));
    return () => {
      clearTimeout(t);
      window.removeEventListener("pointerdown", off, true);
      window.removeEventListener("scroll", scrolled, true);
      window.removeEventListener("keydown", esc);
      window.removeEventListener("resize", place);
    };
  });

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  // ── Picking ────────────────────────────────────────────────────────────────
  function pick(pic: Pic) {
    if (!persona) return;
    play("slide");
    crop = { src: api.pictureUrl(pic.name, pic.id, asked(persona)), name: pic.name };
  }
  function uploaded(e: Event) {
    const file = (e.target as HTMLInputElement).files?.[0];
    if (upload) upload.value = "";
    if (!file || !persona) return;
    play("slide");
    crop = { src: URL.createObjectURL(file), file };
  }
  function dropCrop() {
    if (crop?.file) URL.revokeObjectURL(crop.src);
    crop = null;
  }
  function back() {
    play("slide");
    dropCrop();
  }
  /** The cut square, as the face. */
  async function useCrop(file: File) {
    await send((pid) => api.uploadPersonaAvatar(pid, file));
  }
  /** The browser cannot open it (a HEIC on some machines): sent as it is, the server crops it. */
  async function cropFailed() {
    const c = crop;
    if (!c) return;
    await send((pid) => (c.file ? api.uploadPersonaAvatar(pid, c.file) : api.setPersonaAvatar(pid, c.name ?? "")));
  }
  async function send(go: (pid: string) => Promise<unknown>) {
    const p = persona;
    if (!p) return;
    busy = true;
    try {
      await go(p.id);
      dropCrop();
      onchanged(p.id);
    } catch (err: any) {
      toast(err?.message || "Could not use that one", "err");
    } finally {
      busy = false;
    }
  }
  async function remove() {
    const p = persona;
    if (!p) return;
    play("delete", { level: 0.5 });
    await api.clearPersonaAvatar(p.id).catch(() => {});
    onchanged(p.id);
  }
</script>

{#if persona}
  {@const p = persona}
  <div class="fp glass floating" class:is-crop={!!crop} bind:this={panel} use:portal role="dialog" tabindex="-1"
       aria-label="{p.name}'s face" style="--pc: {colorOf(p)}; left: {pos.left}px; top: {pos.top}px; transform-origin: {pos.origin}">
    {#if crop}
      <!-- The part of it the face shows, in its colour. -->
      <div class="fp-crop">
        <FaceCrop src={crop.src} color={colorOf(p)} {busy} onuse={useCrop} onback={back} onfail={cropFailed} />
      </div>
    {:else}
      <header class="fp-head">
        <span class="fp-now"><PersonaOrb {p} size={34} /></span>
        <span class="fp-title">
          <b>{p.name}'s face</b>
          <small>Only shown in this app</small>
        </span>
        {#if $picturesBlur && pics.length}
          <button type="button" class="fp-icon" class:is-on={shown} onclick={() => (shown = !shown)}
                  title={shown ? "Blur them" : "Show them"} aria-label={shown ? "Blur the pictures" : "Show the pictures"}>
            <Icon name={shown ? "eyeOff" : "eye"} size={14} />
          </button>
        {/if}
        {#if p.avatar}
          <button type="button" class="fp-icon is-danger" onclick={remove} title="Take its face off" aria-label="Remove its face">
            <Icon name="trash" size={13} />
          </button>
        {/if}
        <button type="button" class="fp-icon" onclick={onclose} title="Close" aria-label="Close"><Icon name="close" size={12} /></button>
      </header>

      <!-- Upload first, then its pictures, small. -->
      <div class="fp-grid" class:is-blur={blurred} class:is-scrolling={scrolling} onscroll={onGridScroll}>
        <button type="button" class="fp-tile fp-up" style="--i: 0" onclick={() => upload?.click()} title="Upload one">
          <Icon name="upload" size={15} /><span>Upload</span>
        </button>
        {#each pics as pic, i (pic.id)}
          <button type="button" class="fp-tile" style="--i: {Math.min(i + 1, 16)}" disabled={busy} onclick={() => pick(pic)}
                  aria-label="Use {pic.name}">
            <img src={api.pictureSmall(pic, 160, asked(p))} alt="" loading="lazy" decoding="async" />
          </button>
        {/each}
      </div>
      {#if loaded && !pics.length}
        <p class="fp-none">No pictures yet. Upload one, or add some on the Pictures page.</p>
      {/if}
    {/if}
    <input type="file" accept="image/*" class="hidden" bind:this={upload} onchange={uploaded} />
  </div>
{/if}

<style>
  .fp {
    position: fixed;
    z-index: 120;
    display: flex;
    width: min(336px, calc(100vw - 16px));
    max-height: calc(100vh - 16px);
    flex-direction: column;
    gap: 10px;
    overflow: auto;
    padding: 12px;
    border-radius: 18px;
    outline: none;
    box-shadow: 0 24px 60px -18px rgb(0 0 0 / 0.7), inset 0 0 0 1px color-mix(in srgb, var(--pc) 22%, var(--color-edge)),
                0 0 0 1px rgb(0 0 0 / 0.2);
    animation: fp-in 0.3s var(--jelly);
    transition: width 0.35s var(--swift);
  }
  @keyframes fp-in { from { opacity: 0; transform: scale(0.9); } }
  .fp.is-crop { width: min(460px, calc(100vw - 16px)); }

  .fp-head { display: flex; align-items: center; gap: 10px; }
  .fp-now { display: grid; flex-shrink: 0; }
  .fp-title { display: flex; min-width: 0; flex: 1; flex-direction: column; }
  .fp-title b { overflow: hidden; font-size: 13.5px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; color: var(--color-ink); }
  .fp-title small { font-size: 11px; color: var(--color-faint); }
  .fp-icon {
    display: grid;
    width: 28px;
    height: 28px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 9px;
    color: var(--color-muted);
    transition: color 0.15s ease, background-color 0.15s ease, transform 0.3s var(--jelly);
  }
  .fp-icon:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
  .fp-icon:active { transform: scale(0.9); }
  .fp-icon.is-on { color: var(--pc); }
  .fp-icon.is-danger:hover { color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 12%, transparent); }

  /* Small tiles, a few rows, the rest a scroll away. No mask on it: a masked scroller is painted again whole on every
     frame it moves. */
  .fp-grid {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 6px;
    max-height: 212px;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: 2px;
  }
  .fp-grid.is-scrolling .fp-tile { pointer-events: none; }
  .fp-tile {
    position: relative;
    aspect-ratio: 1;
    overflow: hidden;
    contain: paint;
    border-radius: 12px;
    background: rgb(0 0 0 / 0.25);
    animation: fp-tile 0.35s var(--jelly) backwards;
    animation-delay: calc(80ms + var(--i) * 18ms);
    transition: transform 0.3s var(--jelly), box-shadow 0.2s ease;
  }
  @keyframes fp-tile { from { opacity: 0; transform: scale(0.8); } }
  .fp-tile img { width: 100%; height: 100%; object-fit: cover; transition: filter 0.25s ease, transform 0.35s var(--jelly); }
  .fp-tile:hover { transform: scale(1.06); box-shadow: 0 0 0 2px var(--pc), 0 8px 18px -8px var(--pc); z-index: 1; }
  .fp-tile:hover img { transform: scale(1.08); }
  .fp-tile:active { transform: scale(0.96); }
  .fp-grid.is-blur .fp-tile img { filter: blur(6px) saturate(0.8); }
  .fp-grid.is-blur .fp-tile:hover img { filter: none; }
  .fp-up {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    font-size: 10px;
    font-weight: 600;
    color: var(--color-muted);
    background: color-mix(in srgb, var(--pc) 7%, transparent);
    box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--pc) 35%, transparent);
  }
  .fp-up :global(svg) { color: var(--pc); transition: transform 0.35s var(--jelly); }
  .fp-up:hover { color: var(--color-ink); }
  .fp-up:hover :global(svg) { transform: translateY(-2px); }
  .fp-none { font-size: 12px; line-height: 1.5; color: var(--color-muted); }
  .fp-crop { animation: fp-swap 0.3s var(--swift); }
  @keyframes fp-swap { from { opacity: 0; } }

  :global(:root[data-motion="off"]) .fp,
  :global(:root[data-motion="off"]) .fp-tile,
  :global(:root[data-motion="off"]) .fp-crop { animation: none; }
  :global(:root[data-motion="off"]) .fp,
  :global(:root[data-motion="off"]) .fp-tile,
  :global(:root[data-motion="off"]) .fp-tile img,
  :global(:root[data-motion="off"]) .fp-icon { transition: none; }
</style>
