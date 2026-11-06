<script lang="ts">
  /**
   * Pictures: the bot's own, the ones it sends when someone asks to see it.
   *
   * One at a time large, with what the model is told it shows underneath, since
   * that text is all the model ever sees of it. The rest as a wall beside it; the one
   * on show changes every few seconds, and pressing any puts that one up. A picture
   * the bot has just sent says to whom.
   *
   * Blurred while the Pictures tab's own preference says to (a shared screen is
   * exactly what that is for), with one button to show them for the rest of the
   * visit; H blurs them again, like everything else written on this screen.
   *
   * Shown whole, in its own shape: the frame takes each picture's proportions, as
   * large as the space allows, and eases from one shape to the next. It was a fixed
   * wide box with the picture cropped to fill it and zoomed in on top, so a photo
   * taken upright lost most of itself.
   */
  import { onDestroy } from "svelte";
  import { fade } from "svelte/transition";
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import { discordInline } from "../discordmd";
  import { motionEnabled } from "../stores";
  import BPWho from "./BPWho.svelte";
  import { focusable } from "./focus";
  import { popIn } from "./motion";
  import { ago } from "./scenes";
  import type { BPAccount, PageActions, Picture } from "./types";
  import type { World } from "./world.svelte";

  let {
    world,
    act,
    now = 0,
    blurred = false,
    hideText = false,
    choices = [],
    current = "",
    onwho,
    onreveal,
  }: {
    world: World;
    act: PageActions;
    now?: number;
    /** The Pictures preference: blurred until shown. */
    blurred?: boolean;
    hideText?: boolean;
    choices?: { account: BPAccount; persona: string; name: string }[];
    current?: string;
    onwho?: (accountId: string) => void;
    onreveal?: () => void;
  } = $props();

  const pictures = $derived(world.pictures);
  const sent = $derived(world.sentPics);

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
  /** The last sent picture this page has already put up. */
  let seenSent = "";
  $effect(() => {
    const n = pictures.length;
    if (!n) return;
    if (at < 0) {
      const first = latestSent ? pictures.findIndex((p) => p.name === latestSent) : -1;
      // Otherwise wherever the clock says, so each visit starts somewhere new.
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

  /** How tall the picture is: as much as leaves room for its caption, and the wall if that is under it. */
  let width = $state(0);
  let tall = $state(1080);
  const frameH = $derived(Math.round(width && width < 760
    ? Math.min(tall * (tall < 820 ? 0.3 : 0.38), 420)
    : Math.min(tall * (tall < 820 ? 0.5 : 0.6), 720)));
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
    act.hold();
  }

  // The pictures' own colours in the room only while they may be seen: blurred, it keeps the theme's.
  $effect(() => {
    act.light("pictures", cur && !veiled ? { seed: "pictures", art: pictures[0]?.url } : null);
  });
  onDestroy(() => act.light("pictures", null));
</script>

<svelte:window bind:innerHeight={tall} />

<div class="bpp" class:is-veiled={veiled} bind:clientWidth={width} style="--frame-h: {frameH}px">
  {#if cur}
    <div class="bpp-grid">
      <figure class="bpp-hero" in:popIn|global={{ delay: 60, from: 0.96 }} style="--cap-w: {frame.w}px">
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
                <Avatar src={s.avatar} name={s.to} size={22} zoom={false} />Sent to {s.to} · {ago(s.at, now)}
              </span>
            {/if}
            {#if blurred && !hideText && onreveal}
              <button class="bp-btn bpp-reveal" use:focusable={{ id: "pictures:show", first: true }} onclick={onreveal} title="Show them for the rest of this visit">
                <Icon name="eye" size={16} />Show pictures
              </button>
            {/if}
          </div>
        </div>
        <figcaption class="bpp-cap" data-private>
          {#key cur.name}
            <span class="bpp-desc" class:is-missing={!cur.description} in:popIn={{ from: 0.98 }}>
              <b>{label(cur.name)}</b>
              {#if cur.description}{@html discordInline(cur.description)}{:else}No description yet, so it never gets sent.{/if}
            </span>
          {/key}
        </figcaption>
      </figure>

      <div class="bpp-side">
        <BPWho {choices} {current} onpick={onwho} />
        <div class="bpp-wall" style="--cols: {wall.length > 9 ? 4 : 3}">
          {#each wall as p, i (p.name)}
            <button class="bpp-thumb" class:is-on={cur.name === p.name} class:is-bare={!p.description}
                    use:focusable={{ id: `pic:${p.name}`, first: !blurred && i === 0, onfocus: () => show(p) }} onclick={() => show(p)}
                    title={p.description || `${p.name}: no description yet`} in:popIn|global={{ delay: 120 + i * 38, from: 0.88 }}>
              <img src={p.url} alt="" loading="lazy" decoding="async" draggable="false" onload={(e) => learn(e, p.url)} />
              {#if sent[p.name]}<i class="bpp-badge"><Icon name="send" size={10} /></i>{/if}
            </button>
          {/each}
        </div>
        <div class="bpp-foot">
          <span>{pictures.length} picture{pictures.length === 1 ? "" : "s"}{missing ? `, ${missing} without a description` : ""}</span>
          <button class="bp-btn is-small" use:focusable={{ id: "pictures:page" }} onclick={() => act.leaveTo("pictures")}>
            Open Pictures<Icon name="chevron" size={13} />
          </button>
        </div>
      </div>
    </div>
  {:else}
    <div class="bp-empty">
      <BPWho {choices} {current} onpick={onwho} />
      <b>No pictures yet</b>
      <button class="bp-btn is-go" use:focusable={{ id: "pictures:add", first: true }} onclick={() => act.leaveTo("pictures")}><Icon name="plus" size={15} />Add some</button>
    </div>
  {/if}
</div>

<style>
  .bpp { display: flex; height: 100%; min-width: 0; min-height: 0; flex-direction: column; justify-content: safe center; container-type: inline-size; }
  .bpp-grid { display: grid; min-height: 0; grid-template-columns: minmax(0, 1fr); gap: clamp(14px, 2.4vw, 48px); align-items: center; width: min(100%, 1560px); margin-inline: auto; }
  @container (min-width: 760px) {
    .bpp-grid { grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); }
  }
  .bpp-hero { display: flex; min-width: 0; flex-direction: column; gap: 12px; margin: 0; }
  /* As tall as the space there is, whatever the picture's shape, so the caption
     and the wall stay where they are as the frame changes; the picture sits on its
     caption, the room left over above it. */
  .bpp-box { display: flex; height: var(--frame-h, min(46vh, 520px)); min-width: 0; align-items: flex-end; justify-content: center; }
  .bpp-frame {
    position: relative;
    display: grid;
    max-width: 100%;
    overflow: hidden;
    border-radius: 26px;
    background: var(--bp-fill);
    transition: width 0.8s var(--spring), height 0.8s var(--spring);
  }
  /* The old and the new picture share the frame, one dissolving into the other. */
  .bpp-slide { grid-area: 1 / 1; min-width: 0; min-height: 0; overflow: hidden; }
  /* A slow drift across the picture, transform only, so it runs on the compositor. */
  .bpp-slide img { width: 100%; height: 100%; object-fit: cover; animation: bpp-drift 14s ease-in-out both; will-change: transform; }
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
    padding: 5px 13px 5px 5px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 600;
    color: #fff;
    background: color-mix(in srgb, var(--color-good) 45%, rgb(0 0 0 / 0.6));
  }
  .bpp-frame :global(.bpp-reveal) {
    position: absolute;
    top: 50%;
    left: 50%;
    translate: -50% -50%;
    background: rgb(0 0 0 / 0.45);
  }

  /* Under the picture, as wide as it is, or a little wider for an upright one. */
  .bpp-cap { display: flex; width: max(var(--cap-w, 100%), 26rem); max-width: 100%; min-width: 0; flex-direction: column; align-self: center; transition: width 0.8s var(--spring); }
  .bpp-desc {
    display: -webkit-box;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    font-size: clamp(15px, 1.15vw, 20px);
    line-height: 1.4;
  }
  .bpp-desc b { margin-right: 6px; font-weight: 700; color: var(--bp-faint); }
  .bpp-desc.is-missing { color: var(--color-warn); }

  .bpp-side { display: flex; min-width: 0; flex-direction: column; gap: 12px; }
  .bpp-wall { display: grid; min-width: 0; grid-template-columns: repeat(var(--cols), minmax(0, 1fr)); gap: clamp(6px, 0.6vw, 10px); }
  .bpp-thumb {
    position: relative;
    aspect-ratio: 1;
    overflow: hidden;
    border-radius: 16px;
    background: var(--bp-fill);
    transition: transform 0.45s var(--spring), opacity 0.3s ease;
  }
  .bpp-thumb img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.6s var(--swift); }
  .bpp-thumb:global(.is-focus) { transform: translateY(-3px) scale(1.05); }
  .bpp-thumb:global(.is-focus) img { transform: scale(1.08); }
  .bpp-thumb:active { transform: scale(0.95); }
  .bpp-thumb.is-on { outline: 3px solid var(--bp-lit); outline-offset: 2px; }
  /* Never sent without a description: it sits back. */
  .bpp-thumb.is-bare { opacity: 0.5; }
  .bpp-badge { position: absolute; right: 6px; top: 6px; display: grid; width: 22px; height: 22px; place-items: center; border-radius: 999px; color: var(--color-bg); background: var(--color-good); }
  .bpp-foot { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; font-size: 13px; color: var(--bp-faint); }
  /* Narrow (a phone, or the app small): one strip of six under the picture. */
  @container (max-width: 759px) {
    .bpp-wall { grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 6px; }
    .bpp-thumb { border-radius: 12px; }
    .bpp-thumb:nth-child(n + 7) { display: none; }
  }
  @media (max-height: 820px) {
    .bpp-desc { -webkit-line-clamp: 1; line-clamp: 1; }
  }
  :global(:root[data-motion="off"]) .bpp-slide img { animation: none; }
  :global(:root[data-motion="off"]) .bpp-frame,
  :global(:root[data-motion="off"]) .bpp-cap { transition: none; }
</style>
