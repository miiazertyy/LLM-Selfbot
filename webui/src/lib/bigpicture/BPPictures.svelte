<script lang="ts">
  /**
   * The idle scene about the bot's own pictures: the ones it sends when
   * someone asks to see it.
   *
   * One at a time large, drifting slowly, with what the model is told it shows
   * underneath, since that text is all the model ever sees of it. The rest as
   * a wall beside it; the one on show changes every few seconds, and a click
   * on any puts that one up. A picture the bot has just sent says to whom.
   *
   * Blurred while the Pictures tab's own preference says to (a shared screen
   * is exactly what that is for), with one button to show them for the rest
   * of the visit; H blurs them again, like every other text on this screen.
   *
   * Shown whole, in its own shape: the frame takes each picture's proportions,
   * as large as the space allows, and eases from one shape to the next. It
   * was a fixed wide box with the picture cropped to fill it and zoomed in on
   * top, so a photo taken upright lost most of itself.
   */
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import { fade } from "svelte/transition";
  import { motionEnabled } from "../stores";
  import { popIn } from "./motion";
  import { discordInline } from "../discordmd";
  import type { Picture, SentPicture } from "./types";

  let {
    pictures = [],
    sent = {},
    now = 0,
    blurred = false,
    hideText = false,
    onreveal,
    onhold,
  }: {
    pictures?: Picture[];
    /** The pictures that went out this visit, by file name. */
    sent?: Record<string, SentPicture>;
    now?: number;
    /** The Pictures preference: blurred until shown. */
    blurred?: boolean;
    hideText?: boolean;
    onreveal?: () => void;
    /** A picture chosen by hand: keep this scene up a while. */
    onhold?: () => void;
  } = $props();

  /** Seconds each picture stays up before the next one takes its place. */
  const EVERY = 4;
  /** How many fit on the wall beside it. */
  const WALL = 12;

  /** The one sent most recently, if it was within the hour: that is the one worth seeing first. */
  const latestSent = $derived.by(() => {
    let best = "";
    let at = 0;
    for (const [name, s] of Object.entries(sent)) {
      if (s.at > at && now - s.at < 3600) {
        best = name;
        at = s.at;
      }
    }
    return best;
  });

  let at = $state(-1);
  let since = $state(0);
  let picked = $state(false);
  /** The last sent picture this scene has already put up. */
  let seenSent = "";
  $effect(() => {
    const n = pictures.length;
    if (!n) return;
    if (at < 0) {
      const first = latestSent ? pictures.findIndex((p) => p.name === latestSent) : -1;
      // Otherwise wherever the clock says, so each visit to the scene starts somewhere new.
      at = first >= 0 ? first : Math.floor(now / EVERY) % n;
      since = now;
      seenSent = latestSent;
      return;
    }
    // One going out while the gallery is up: that one, now, and for longer.
    if (latestSent && latestSent !== seenSent) {
      seenSent = latestSent;
      const i = pictures.findIndex((p) => p.name === latestSent);
      if (i >= 0) {
        at = i;
        since = now;
        picked = true;
        return;
      }
    }
    if (now - since < (picked ? EVERY * 3 : EVERY)) return;
    at = (at + 1) % n;
    since = now;
    picked = false;
  });
  const cur = $derived(pictures.length ? pictures[Math.max(0, at) % pictures.length] : null);

  /** The wall: the pictures around the one on show, so the highlight walks along it. */
  const wall = $derived.by(() => {
    const n = pictures.length;
    if (n <= WALL) return pictures;
    const start = Math.floor(Math.max(0, at) / WALL) * WALL;
    const out = pictures.slice(start, start + WALL);
    return out.length < WALL ? [...out, ...pictures.slice(0, WALL - out.length)] : out;
  });
  const missing = $derived(pictures.filter((p) => !p.description).length);

  /**
   * How tall the picture is: as much as leaves room for its caption and the
   * wall, which sits beside it on a wide stage and under it on a narrow one.
   */
  let width = $state(0);
  let tall = $state(1080);
  const frameH = $derived(Math.round(width && width < 720
    ? Math.min(tall * (tall < 820 ? 0.24 : 0.32), 380)
    : Math.min(tall * (tall < 820 ? 0.38 : 0.46), 520)));
  const veiled = $derived(blurred || hideText);

  /** Each picture's shape (width over height), learned as it loads, the wall's thumbnails included, so it is known before the picture comes up. */
  let shapes = $state<Record<string, number>>({});
  function learn(e: Event, url: string) {
    const img = e.currentTarget as HTMLImageElement;
    if (img.naturalWidth && img.naturalHeight && !shapes[url]) shapes = { ...shapes, [url]: img.naturalWidth / img.naturalHeight };
  }
  /** How wide the picture's column is: the most the frame can be. */
  let boxW = $state(0);
  /** The frame: the picture's own shape, as large as fits the column and the height there is. */
  const frame = $derived.by(() => {
    const aspect = (cur && shapes[cur.url]) || 0.8;
    const maxW = boxW || 600;
    let w = frameH * aspect;
    let h = frameH;
    if (w > maxW) {
      w = maxW;
      h = maxW / aspect;
    }
    return { w: Math.round(w), h: Math.round(h) };
  });
  const label = (name: string) => name.replace(/\.[^.]+$/, "").replace(/^IMG_/, "#");

  function show(p: Picture) {
    const i = pictures.indexOf(p);
    if (i < 0) return;
    at = i;
    since = now;
    picked = true;
    onhold?.();
  }
  function ago(ts: number): string {
    const s = Math.max(0, now - ts);
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    return `${Math.round(s / 3600)} h ago`;
  }
</script>

<svelte:window bind:innerHeight={tall} />

<div class="bpp" class:is-veiled={veiled} bind:clientWidth={width} style="--frame-h: {frameH}px">
  <div class="bp-kicker" in:popIn|global={{ delay: 40, from: 0.96 }}>
    Pictures · {pictures.length}{missing ? ` · ${missing} without a description, so never sent` : " · what it sends when asked"}
  </div>
  <h2 class="bp-title" in:popIn|global={{ delay: 90, from: 0.96 }}>Pictures</h2>

  {#if cur}
    <div class="bpp-grid">
      <figure class="bpp-hero" in:popIn|global={{ delay: 160, from: 0.94 }} style="--cap-w: {frame.w}px">
        <div class="bpp-box" bind:clientWidth={boxW}>
        <div class="bpp-frame" style="width: {frame.w}px; height: {frame.h}px">
          {#key cur.name}
            <div class="bpp-slide" in:fade={{ duration: $motionEnabled ? 900 : 0 }} out:fade={{ duration: $motionEnabled ? 900 : 0 }}>
              <img src={cur.url} alt={cur.description || cur.name} draggable="false" decoding="async"
                   onload={(e) => learn(e, cur.url)} />
            </div>
          {/key}
          {#if sent[cur.name] && now - sent[cur.name].at < 3600}
            {@const s = sent[cur.name]}
            <span class="bpp-sent" in:popIn>
              <Avatar src={s.avatar} name={s.to} size={22} zoom={false} />Sent to {s.to} · {ago(s.at)}
            </span>
          {/if}
          {#if blurred && !hideText && onreveal}
            <button class="bpp-reveal" onclick={onreveal} title="Show them for the rest of this visit">
              <Icon name="eye" size={16} />Show pictures
            </button>
          {/if}
        </div>
        </div>
        <figcaption class="bpp-cap" class:is-hidden={hideText}>
          <span class="bpp-name">{label(cur.name)}</span>
          {#key cur.name}
            <span class="bpp-desc" class:is-missing={!cur.description} in:popIn={{ from: 0.98 }}>
              {#if cur.description}{@html discordInline(cur.description)}{:else}No description yet, so the model cannot choose this one.{/if}
            </span>
          {/key}
        </figcaption>
      </figure>

      <div class="bpp-wall" style="--cols: {wall.length > 9 ? 4 : 3}">
        {#each wall as p, i (p.name)}
          <button class="bpp-thumb" class:is-on={cur.name === p.name} class:is-sent={!!sent[p.name]}
                  class:is-bare={!p.description} onclick={() => show(p)}
                  title={p.description || `${p.name}: no description yet`}
                  in:popIn|global={{ delay: 220 + i * 45, from: 0.85 }}>
            <img src={p.url} alt="" loading="lazy" decoding="async" draggable="false" onload={(e) => learn(e, p.url)} />
            {#if sent[p.name]}<i class="bpp-badge"><Icon name="send" size={10} /></i>{/if}
          </button>
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  .bpp { display: flex; height: 100%; min-width: 0; flex-direction: column; justify-content: safe center; gap: 12px; padding: 10px 6px; container-type: inline-size; }
  .bpp-grid { display: grid; min-height: 0; grid-template-columns: minmax(0, 1fr); gap: clamp(16px, 2vw, 30px); align-items: center; }
  @container (min-width: 720px) {
    .bpp-grid { grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); }
  }
  .bpp-hero { display: flex; min-width: 0; flex-direction: column; gap: 12px; margin: 0; }
  /* As tall as the space there is, whatever the picture's shape, so the
     caption and the wall stay where they are as the frame changes; the
     picture sits on its caption, the room left over above it. */
  .bpp-box {
    display: flex;
    height: var(--frame-h, min(46vh, 520px));
    min-width: 0;
    align-items: flex-end;
    justify-content: center;
  }
  .bpp-frame {
    position: relative;
    display: grid;
    max-width: 100%;
    overflow: hidden;
    border-radius: 28px;
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.1), 0 40px 90px -40px rgb(0 0 0 / 0.95);
    transition: width 0.8s var(--spring), height 0.8s var(--spring);
  }
  /* The old and the new picture share the frame, one dissolving into the other. */
  .bpp-slide { grid-area: 1 / 1; min-width: 0; min-height: 0; overflow: hidden; }
  /* A slow drift across the picture, transform only, so it runs on the compositor. */
  .bpp-slide img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    animation: bpp-drift 14s ease-in-out both;
    will-change: transform;
  }
  /* Barely a drift now: the frame is the picture's own shape, so a zoom would only cut into it. */
  @keyframes bpp-drift { from { transform: scale(1); } to { transform: scale(1.035); } }
  .bpp.is-veiled .bpp-slide img,
  .bpp.is-veiled .bpp-thumb img { filter: blur(22px) saturate(1.25); }
  .bpp-sent {
    position: absolute;
    left: 14px;
    bottom: 14px;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 5px 12px 5px 5px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 600;
    color: #fff;
    background: color-mix(in srgb, var(--color-good) 38%, rgb(0 0 0 / 0.55));
    backdrop-filter: blur(12px);
  }
  .bpp-reveal {
    position: absolute;
    top: 50%;
    left: 50%;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    height: 44px;
    padding: 0 20px;
    border-radius: 999px;
    font-size: 14px;
    font-weight: 650;
    white-space: nowrap;
    color: #fff;
    background: rgb(0 0 0 / 0.45);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.18);
    backdrop-filter: blur(12px);
    transform: translate(-50%, -50%);
    transition: transform 0.25s var(--spring), background-color 0.2s ease;
  }
  .bpp-reveal:hover { transform: translate(-50%, -50%) scale(1.05); background: color-mix(in srgb, var(--color-accent) 45%, rgb(0 0 0 / 0.4)); }
  .bpp-reveal:active { transform: translate(-50%, -50%) scale(0.96); }

  /* Under the picture, as wide as it is, or a little wider for an upright one. */
  .bpp-cap {
    display: flex;
    width: max(var(--cap-w, 100%), 26rem);
    max-width: 100%;
    min-width: 0;
    flex-direction: column;
    align-self: center;
    gap: 4px;
    padding: 0 4px;
    transition: width 0.8s var(--spring);
  }
  .bpp-name { font-size: 12px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: var(--bp-faint); }
  .bpp-desc {
    display: -webkit-box;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    font-size: clamp(15px, 1.25vw, 19px);
    line-height: 1.45;
    color: #fff;
  }
  .bpp-desc.is-missing { color: var(--color-warn); }
  .bpp-cap.is-hidden .bpp-desc { filter: blur(7px); }

  .bpp-wall { display: grid; min-width: 0; grid-template-columns: repeat(var(--cols), minmax(0, 1fr)); gap: 10px; }
  .bpp-thumb {
    position: relative;
    aspect-ratio: 1;
    overflow: hidden;
    border-radius: 18px;
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08);
    transition: transform 0.35s var(--spring), box-shadow 0.3s ease, opacity 0.3s ease;
  }
  .bpp-thumb img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.6s var(--swift); }
  .bpp-thumb:hover { transform: translateY(-3px) scale(1.04); }
  .bpp-thumb:hover img { transform: scale(1.08); }
  .bpp-thumb:active { transform: scale(0.95); }
  .bpp-thumb.is-on {
    box-shadow: 0 0 0 2.5px var(--color-accent), 0 14px 36px -12px color-mix(in srgb, var(--color-accent) 55%, transparent);
    transform: scale(1.03);
  }
  /* Never sent without a description: it sits back. */
  .bpp-thumb.is-bare { opacity: 0.5; }
  .bpp-badge {
    position: absolute;
    right: 6px;
    top: 6px;
    display: grid;
    width: 22px;
    height: 22px;
    place-items: center;
    border-radius: 999px;
    color: #fff;
    background: var(--color-good);
    box-shadow: 0 0 16px color-mix(in srgb, var(--color-good) 42%, transparent);
  }
  /* Narrow (the queue is open, or a phone): one strip of six under the picture,
     which is as many as fit without the scene running off the stage. */
  @container (max-width: 719px) {
    .bpp-wall { grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; }
    .bpp-thumb { border-radius: 12px; }
    .bpp-thumb:nth-child(n + 7) { display: none; }
  }
  @media (max-height: 820px) {
    .bpp-desc { -webkit-line-clamp: 2; line-clamp: 2; }
  }
  :global(:root[data-motion="off"]) .bpp-slide img { animation: none; }
  :global(:root[data-motion="off"]) .bpp-frame,
  :global(:root[data-motion="off"]) .bpp-cap { transition: none; }
</style>
