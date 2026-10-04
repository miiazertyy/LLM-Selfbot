<script lang="ts">
  /**
   * A Discord sticker that is an animation rather than a picture, played the
   * way Discord plays it.
   *
   * Discord's own stickers ("Wave" and the rest) are Lottie: a file of shapes
   * and keyframes, not an image, so the Chats tab could only show their names.
   * The file comes through the app (/api/media/sticker/<id>.json, fetched once
   * and kept) and plays here with lottie-web's light player, which is loaded
   * the first time a sticker needs it rather than with the app. It plays while
   * it is on screen, rests when scrolled away, and holds still with the app's
   * Animations switch off. If it cannot be had, its name shows instead.
   */
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { motionEnabled } from "../stores";
  import Icon from "./Icon.svelte";

  let { id, name = "", size = 144 }: { id: string; name?: string; size?: number } = $props();

  let box: HTMLElement | null = $state(null);
  let failed = $state(false);
  let ready = $state(false);

  onMount(() => {
    let anim: import("lottie-web").AnimationItem | null = null;
    let io: IntersectionObserver | null = null;
    let alive = true;
    import("lottie-web/build/player/lottie_light")
      .then((m) => {
        if (!alive || !box) return;
        anim = m.default.loadAnimation({
          container: box,
          renderer: "svg",
          loop: true,
          autoplay: false,
          path: `/api/media/sticker/${id}.json`,
          rendererSettings: { preserveAspectRatio: "xMidYMid meet" },
        });
        anim.addEventListener("data_failed", () => (failed = true));
        anim.addEventListener("DOMLoaded", () => {
          ready = true;
          if (!get(motionEnabled)) anim?.goToAndStop(0, true);
        });
        // Only what is on screen moves: a long chat of stickers costs nothing.
        io = new IntersectionObserver(([e]) => {
          if (!anim) return;
          if (e.isIntersecting && get(motionEnabled)) anim.play();
          else anim.pause();
        });
        io.observe(box);
      })
      .catch(() => (failed = true));
    return () => {
      alive = false;
      io?.disconnect();
      anim?.destroy();
    };
  });
</script>

{#if failed}
  <span class="ls-name"><Icon name="sparkle" size={12} />Sticker: {name}</span>
{:else}
  <span class="ls" class:is-ready={ready} bind:this={box} style="width: {size}px; height: {size}px"
        role="img" aria-label="Sticker: {name}" title="Sticker: {name}"></span>
{/if}

<style>
  .ls {
    display: inline-block;
    vertical-align: bottom;
    opacity: 0;
    transform: scale(0.9);
    transition: opacity 0.25s var(--swift), transform 0.4s var(--jelly);
  }
  .ls.is-ready { opacity: 1; transform: none; }
  .ls-name {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 12px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.06);
  }
  :global(:root[data-motion="off"]) .ls { transition: none; }
</style>
