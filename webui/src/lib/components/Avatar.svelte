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
   */
  import Icon from "./Icon.svelte";
  import { openMenuAt } from "../contextmenu";
  import { saveUrlAs } from "../window";
  import { copyImageFrom } from "../imagecopy";
  import { toast } from "../stores";

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
  }: {
    src?: string;
    name?: string;
    size?: number;
    ring?: string;
    zoom?: boolean;
    silhouette?: boolean;
  } = $props();

  let broken = $state(false);
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
    }
  });

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
      {src}
      alt=""
      referrerpolicy="no-referrer"
      onerror={() => (broken = true)}
      class="h-full w-full rounded-full object-cover {ring}"
    />
  </button>
{:else if shown}
  <img
    {src}
    alt=""
    referrerpolicy="no-referrer"
    onerror={() => (broken = true)}
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
  >
    <figure class="pop flex max-h-full flex-col items-center gap-3">
      {#if bigBroken}
        <!-- The stored link worked at 128 but not at 1024, which happens with
             a default avatar. Fall back to the one that is already on screen. -->
        <img
          src={src}
          alt=""
          referrerpolicy="no-referrer"
          class="avatar-big max-h-[70vh] w-auto max-w-[min(420px,86vw)] rounded-2xl object-contain"
        />
      {:else}
        <img
          src={big}
          alt=""
          referrerpolicy="no-referrer"
          onerror={() => (bigBroken = true)}
          class="avatar-big max-h-[70vh] w-auto max-w-[min(420px,86vw)] rounded-2xl object-contain"
        />
      {/if}
      {#if name}
        <figcaption class="text-[13px] text-ink/80">{name}</figcaption>
      {/if}
      <span class="text-[11px] text-faint">Click anywhere, or press Escape, to close. Right click to copy it.</span>
    </figure>
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
  @keyframes avatar-fade {
    from { opacity: 0; }
    to { opacity: 1; }
  }
</style>
