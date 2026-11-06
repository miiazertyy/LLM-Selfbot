<script lang="ts">
  /**
   * Someone's profile picture, with a click to see it properly.
   *
   * There were nine places drawing an avatar, each with its own <img>, its own
   * ring and its own idea of what to do when the link was dead. They are all
   * this now, so a fix lands everywhere at once.
   *
   * Two things every one of them needs:
   *
   *  - A fallback. These are Discord CDN links cached whenever the bot last saw
   *    the person, and a link rots when they change their picture. A broken
   *    image icon is worse than the placeholder glyph it replaced.
   *  - A way to actually look at it. 28 to 40 pixels is enough to recognise
   *    someone and not enough to see anything, and the full-size original is
   *    one query parameter away.
   *
   * Opened, it can be looked at closer still: held down on, a round loupe
   * follows the pointer with the picture magnified in it, and the wheel turns
   * the magnification up and down while it is held (1.5x to 8x, said in the
   * loupe as it changes). Let go and it is gone; a click outside the picture
   * still closes it.
   */
  import Icon from "./Icon.svelte";
  import { openMenuAt } from "../contextmenu";
  import { saveUrlAs } from "../window";
  import { copyImageFrom } from "../imagecopy";
  import { toast } from "../stores";
  import { play } from "../uisound";

  let {
    src = "",
    name = "",
    /** Rendered size in px. The glyph scales with it. */
    size = 36,
    /** Extra classes for the ring, mostly. */
    ring = "ring-1 ring-edge",
    /** Off where a click already means something else, e.g. inside a button. */
    zoom = true,
    /**
     * With no picture: Snapchat's own empty silhouette, a grey figure on a
     * pale disc, instead of the generic glyph. For a Snapchat account the
     * runner has read and found no photo or Bitmoji on: it is what Snapchat
     * itself shows for it.
     */
    silhouette = false,
    /** Fetched only once scrolled near: for a list of hundreds. */
    lazy = false,
  }: {
    src?: string;
    name?: string;
    size?: number;
    ring?: string;
    zoom?: boolean;
    silhouette?: boolean;
    lazy?: boolean;
  } = $props();

  let broken = $state(false);
  // One more try a moment after a picture fails: a link that failed once (the network hiccupped, Discord's CDN
  // said "slow down") usually loads the second time, and the placeholder used to stay for good.
  let attempt = $state(0);
  let open = $state(false);
  let bigBroken = $state(false);
  /** Right-click menu over the opened picture: where it was clicked, or null. */

  // A new person in the same slot deserves a fresh attempt at their picture.
  let lastSrc = $state("");
  $effect(() => {
    if (src !== lastSrc) {
      lastSrc = src;
      broken = false;
      bigBroken = false;
      attempt = 0;
    }
  });

  const shownSrc = $derived(attempt && src ? `${src}${src.includes("?") ? "&" : "?"}retry=${attempt}` : src);
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  function failed() {
    if (attempt === 0 && /^(https?:|\/)/.test(src)) {
      const was = src;
      if (retryTimer) clearTimeout(retryTimer);
      retryTimer = setTimeout(() => { if (src === was) attempt = 1; }, 2500);
      broken = true;
      return;
    }
    broken = true;
  }
  $effect(() => {
    if (attempt) broken = false;
  });
  $effect(() => () => { if (retryTimer) clearTimeout(retryTimer); });

  const shown = $derived(!!src && !broken);
  const clickable = $derived(shown && zoom);

  /**
   * The same picture, as large as it is stored.
   *
   * Discord serves whatever `size` is asked for, and the cached link asks for
   * 128 because that is all a row needs. Opening one at 128px wide would defeat
   * the point, so the parameter is rewritten rather than the image upscaled.
   * Anything that is not a sized CDN link is left exactly as it is.
   */
  const big = $derived.by(() => {
    if (!src) return "";
    try {
      const u = new URL(src, window.location.origin);
      if (u.searchParams.has("size")) u.searchParams.set("size", "1024");
      else if (/cdn\.discordapp\.com|discordapp\.net/.test(u.hostname))
        u.searchParams.set("size", "1024");
      else return src;
      return u.toString();
    } catch {
      return src;
    }
  });

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  /** The picture actually on screen: the large one, unless only the small one loaded. */
  const shownBig = $derived(bigBroken ? src : big);

  // ── Looking closer: a loupe while it is held, the wheel zooming it ─────────
  /** The loupe's size, in px. */
  const LOUPE = 190;
  const MIN_ZOOM = 1.5;
  const MAX_ZOOM = 8;
  /** Where the pointer is, on screen and on the picture as drawn, and the picture's drawn size. */
  let loupe = $state<{ x: number; y: number; bx: number; by: number; w: number; h: number } | null>(null);
  let loupeZoom = $state(2.5);
  /** The magnification shown in the loupe for a moment after the wheel changes it. */
  let zoomShown = $state(false);
  let zooming = $state(false);
  let zoomTimer = 0;
  let notch = 0;
  function look(e: PointerEvent, img: HTMLElement) {
    const r = img.getBoundingClientRect();
    loupe = {
      x: e.clientX, y: e.clientY,
      bx: Math.max(0, Math.min(r.width, e.clientX - r.left)), by: Math.max(0, Math.min(r.height, e.clientY - r.top)),
      w: r.width, h: r.height,
    };
  }
  function holdDown(e: PointerEvent) {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    const img = e.currentTarget as HTMLElement;
    img.setPointerCapture?.(e.pointerId);
    look(e, img);
    notch = Math.round(loupeZoom * 2);
    play("lift", { level: 0.45 });
  }
  function holdMove(e: PointerEvent) {
    if (loupe) look(e, e.currentTarget as HTMLElement);
  }
  function holdUp() {
    if (!loupe) return;
    loupe = null;
    zoomShown = false;
    play("release", { level: 0.4 });
  }
  /** The wheel while it is held: closer or further, around the same point. Not passive, so the page does not scroll. */
  function wheelZoom(node: HTMLElement) {
    const onWheel = (e: WheelEvent) => {
      if (!loupe) return;
      e.preventDefault();
      e.stopPropagation();
      loupeZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, loupeZoom * Math.exp(-e.deltaY * 0.0018)));
      // A tick for each half step, a note higher as it goes in.
      const n = Math.round(loupeZoom * 2);
      if (n !== notch) {
        notch = n;
        play("tick", { level: 0.3, p: (loupeZoom - MIN_ZOOM) / (MAX_ZOOM - MIN_ZOOM) });
      }
      zoomShown = true;
      zooming = true;
      clearTimeout(zoomTimer);
      zoomTimer = window.setTimeout(() => {
        zoomShown = false;
        zooming = false;
      }, 900);
    };
    node.addEventListener("wheel", onWheel, { passive: false });
    return { destroy: () => node.removeEventListener("wheel", onWheel) };
  }

  async function copyIt() {
    try {
      await copyImageFrom(shownBig);
      toast("Copied the picture.", "ok");
    } catch (e: any) {
      toast(e?.message || "Could not copy it", "err");
    }
  }
</script>

{#if clickable}
  <button
    type="button"
    class="jelly shrink-0 rounded-full"
    style="height:{size}px;width:{size}px"
    title={name ? `${name}, click to enlarge` : 'Click to enlarge'}
    aria-label={name ? `Enlarge ${name}'s picture` : "Enlarge picture"}
    onclick={(e) => { e.stopPropagation(); open = true; }}
  >
    <img
      src={shownSrc}
      alt=""
      referrerpolicy="no-referrer"
      onerror={failed}
      class="h-full w-full rounded-full object-cover {ring}"
    />
  </button>
{:else if shown}
  <!-- Loading before the address: set after it, the browser has already begun fetching. -->
  <img
    loading={lazy ? "lazy" : undefined}
    src={shownSrc}
    alt=""
    referrerpolicy="no-referrer"
    onerror={failed}
    class="shrink-0 rounded-full object-cover {ring}"
    style="height:{size}px;width:{size}px"
  />
{:else if silhouette}
  <span class="avatar-silhouette shrink-0 rounded-full {ring}" style="height:{size}px;width:{size}px" aria-hidden="true">
    <svg viewBox="0 0 90 90"><path d="M45 15.5a16 16 0 1 1 0 32a16 16 0 0 1 0-32zM12 92c0-19 14.5-32 33-32s33 13 33 32z" /></svg>
  </span>
{:else}
  <span
    class="flex shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-muted {ring}"
    style="height:{size}px;width:{size}px"
  >
    <Icon name="accounts" size={Math.max(11, Math.round(size * 0.44))} />
  </span>
{/if}

{#if open}
  <!-- Portalled, because several of the call sites live inside a card with its
       own stacking context and overflow hidden - the overlay would have been
       clipped to a 40px row. -->
  <div
    use:portal
    class="avatar-zoom fixed inset-0 z-[80] flex items-center justify-center bg-black/70 p-6 backdrop-blur-sm"
    role="dialog"
    aria-modal="true"
    aria-label={name ? `${name}'s picture` : "Profile picture"}
    tabindex="-1"
    onclick={() => (open = false)}
    oncontextmenu={(e) => openMenuAt(e, [
      name && { title: name },
      { label: "Copy image", icon: "copy", run: copyIt },
      // Its real Save dialog in the desktop app: the download link this was did nothing there.
      { label: "Save as…", icon: "download",
        run: () => saveUrlAs(shownBig, name || "picture").then((w) => w && toast("Saved.", "ok")) },
      "sep",
      { label: "Close", icon: "close", keys: "Esc", run: () => (open = false) },
    ])}
    onkeydown={(e) => e.key === "Escape" && (open = false)}
    use:wheelZoom
  >
    <figure class="pop flex max-h-full flex-col items-center gap-3">
      {#if bigBroken}
        <!-- The stored link worked at 128 but not at 1024, which happens with
             a default avatar. Fall back to the one that is already on screen. -->
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
        <img
          src={src}
          alt=""
          referrerpolicy="no-referrer"
          draggable="false"
          onpointerdown={holdDown}
          onpointermove={holdMove}
          onpointerup={holdUp}
          onpointercancel={holdUp}
          onclick={(e) => e.stopPropagation()}
          class:is-held={!!loupe}
          class="avatar-big max-h-[70vh] w-auto max-w-[min(420px,86vw)] rounded-2xl object-contain"
        />
      {:else}
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
        <img
          src={big}
          alt=""
          referrerpolicy="no-referrer"
          onerror={() => (bigBroken = true)}
          draggable="false"
          onpointerdown={holdDown}
          onpointermove={holdMove}
          onpointerup={holdUp}
          onpointercancel={holdUp}
          onclick={(e) => e.stopPropagation()}
          class:is-held={!!loupe}
          class="avatar-big max-h-[70vh] w-auto max-w-[min(420px,86vw)] rounded-2xl object-contain"
        />
      {/if}
      {#if name}
        <figcaption class="text-[13px] text-ink/80">{name}</figcaption>
      {/if}
      <span class="text-[11px] text-faint">Hold on it to look closer and scroll to zoom. Click outside it to close, right click to copy.</span>
    </figure>
    {#if loupe}
      <!-- The loupe: the picture under the pointer, magnified, in a round glass. -->
      <div class="avatar-loupe" class:is-zooming={zooming} style="left: {loupe.x}px; top: {loupe.y}px; --size: {LOUPE}px" aria-hidden="true">
        <!-- Clipped to a true circle on a layer of its own: rounded corners alone let a moved picture show past the edge. -->
        <span class="avatar-loupe-glass">
          <img
            src={shownBig}
            alt=""
            referrerpolicy="no-referrer"
            style="width: {loupe.w * loupeZoom}px; height: {loupe.h * loupeZoom}px;
                   transform: translate({LOUPE / 2 - loupe.bx * loupeZoom}px, {LOUPE / 2 - loupe.by * loupeZoom}px)"
          />
        </span>
        {#if zoomShown}<span class="avatar-loupe-zoom">{loupeZoom.toFixed(1)}×</span>{/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  .avatar-silhouette {
    display: grid;
    overflow: hidden;
    place-items: end center;
    background: linear-gradient(180deg, #f3f4f7, #e2e4ea);
  }
  .avatar-silhouette svg { width: 100%; height: 100%; fill: #a3a7b1; }
  /* The edge is on the picture, so it follows the picture: a ring on the box
     stood away from a tall or wide one on two sides. */
  .avatar-big {
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-edge) 90%, transparent),
                0 30px 80px -30px rgb(0 0 0 / 0.8);
  }
  .avatar-zoom {
    animation: avatar-fade 0.18s ease-out both;
  }
  .avatar-big { cursor: zoom-in; touch-action: none; user-select: none; }
  /* Held: the loupe stands in for the pointer. */
  .avatar-big.is-held { cursor: none; }
  .avatar-loupe {
    position: fixed;
    z-index: 90;
    width: var(--size);
    height: var(--size);
    border-radius: 999px;
    pointer-events: none;
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 70%, #fff 10%), 0 0 0 6px rgb(0 0 0 / 0.35),
                0 24px 60px -16px rgb(0 0 0 / 0.85), inset 0 0 22px rgb(0 0 0 / 0.45);
    transform: translate(-50%, -50%);
    animation: avatar-loupe-in 0.22s cubic-bezier(0.3, 1.4, 0.5, 1);
  }
  @keyframes avatar-loupe-in { from { transform: translate(-50%, -50%) scale(0.4); opacity: 0; } }
  .avatar-loupe-glass {
    position: absolute;
    inset: 0;
    overflow: hidden;
    border-radius: inherit;
    clip-path: circle(50% at 50% 50%);
    background: #000;
  }
  .avatar-loupe img { position: absolute; left: 0; top: 0; max-width: none; transform-origin: 0 0; }
  /* The wheel turning: the magnification eases there rather than jumping. */
  .avatar-loupe.is-zooming img { transition: width 0.12s ease-out, height 0.12s ease-out, transform 0.12s ease-out; }
  /* A glint across the glass. */
  .avatar-loupe-glass::after {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: inherit;
    background: radial-gradient(120% 80% at 30% 15%, rgb(255 255 255 / 0.22), transparent 45%);
    pointer-events: none;
  }
  .avatar-loupe-zoom {
    position: absolute;
    left: 50%;
    bottom: 12px;
    z-index: 1;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: #fff;
    background: rgb(0 0 0 / 0.55);
    transform: translateX(-50%);
  }
  :global(:root[data-motion="off"]) .avatar-loupe { animation: none; }
  :global(:root[data-motion="off"]) .avatar-loupe img { transition: none; }
  @keyframes avatar-fade {
    from { opacity: 0; }
    to { opacity: 1; }
  }
</style>
