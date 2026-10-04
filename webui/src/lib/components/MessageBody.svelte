<script lang="ts">
  /**
   * A Discord message, the way Discord shows it: formatted text with real
   * @mentions, then what came with it - pictures (click to see them large),
   * video, voice messages, files, stickers and link previews.
   *
   * The Chats tab used to show a 60-character plain snippet, and anything that
   * was not text was "[attachment]". Everything here comes from the message
   * itself; the links are Discord's own, signed, and good for a while.
   */
  import Icon from "./Icon.svelte";
  import UserChip from "./UserChip.svelte";
  import VoiceNote from "./VoiceNote.svelte";
  import VideoPlayer from "./VideoPlayer.svelte";
  import LottieSticker from "./LottieSticker.svelte";
  import { mentionNames, resolveMention, segments } from "../mentions";
  import { discordInline } from "../discordmd";

  type Attachment = { url: string; name: string; type?: string; w?: number | null; h?: number | null; size?: number };
  /** `format` "lottie" is an animation with no picture: played from its id. */
  type Sticker = { name: string; url?: string; id?: string; format?: string };
  type Embed = { title?: string; url?: string; image?: string; provider?: string };

  let {
    text = "",
    attachments = [],
    stickers = [],
    embeds = [],
    clamp = 0,
    onreveal,
  }: {
    text?: string;
    attachments?: Attachment[];
    stickers?: Sticker[];
    embeds?: Embed[];
    /** Cut the text after this many lines (0 = never). */
    clamp?: number;
    /**
     * Fetch the real message behind an "[attachment]" row. When given, that
     * chip is a button: pressing it loads the message and opens its picture.
     */
    onreveal?: () => Promise<unknown>;
  } = $props();

  let revealing = $state(false);
  let revealError = $state("");
  let openWhenLoaded = $state(false);

  async function reveal() {
    if (!onreveal || revealing) return;
    revealing = true;
    revealError = "";
    try {
      await onreveal();
      openWhenLoaded = true;
    } catch (e: any) {
      revealError = e?.message || "Could not fetch it";
    } finally {
      revealing = false;
    }
  }

  /**
   * What an older row has instead of its message: "[attachment]", "[image]",
   * "[sticker: wave]". Only the text was stored for those, so the picture is
   * gone; saying what it was, as a chip, beats printing the brackets.
   */
  const placeholder = $derived.by(() => {
    const m = (text || "").trim().match(/^\[(attachment|image|video|voice message|file|link|snap|call|sticker(?::\s*[^\]]+)?|\d+ attachments)\]$/i);
    if (!m) return null;
    const what = m[1].toLowerCase();
    // Snapchat's: a Snap, and a call, which are neither pictures nor files.
    const icon = what === "snap" ? "snapchat" : what === "call" ? "volume" : what.startsWith("sticker") ? "sparkle"
      : what === "voice message" ? "mic" : what === "link" ? "external" : what === "video" ? "play" : "pictures";
    const label = what === "snap" ? "Sent a Snap" : what === "call" ? "A call"
      : what.startsWith("sticker:") ? `Sticker: ${m[1].slice(8).trim()}`
      : /^\d/.test(what) ? `Sent ${what}` : `Sent ${/^[aeiou]/.test(what) ? "an" : "a"} ${what}`;
    return { icon, label };
  });
  const parts = $derived(placeholder ? [] : segments(text));
  $effect(() => {
    for (const p of parts) if (p.kind === "mention") resolveMention(p.id);
  });

  const isImage = (a: Attachment) =>
    (a.type || "").startsWith("image/") || /\.(png|jpe?g|gif|webp|avif)(\?|$)/i.test(a.url);
  const isVideo = (a: Attachment) => (a.type || "").startsWith("video/") || /\.(mp4|webm|mov)(\?|$)/i.test(a.url);
  const isAudio = (a: Attachment) => (a.type || "").startsWith("audio/") || /\.(ogg|mp3|wav|m4a)(\?|$)/i.test(a.url);

  const images = $derived(attachments.filter(isImage));
  const videos = $derived(attachments.filter((a) => !isImage(a) && isVideo(a)));
  const audios = $derived(attachments.filter((a) => !isImage(a) && !isVideo(a) && isAudio(a)));
  const files = $derived(attachments.filter((a) => !isImage(a) && !isVideo(a) && !isAudio(a)));
  const drawnStickers = $derived(stickers.filter((s) => s.url));
  const playedStickers = $derived(stickers.filter((s) => !s.url && s.id && s.format === "lottie"));
  const namedStickers = $derived(stickers.filter((s) => !s.url && !(s.id && s.format === "lottie")));

  function kb(n?: number): string {
    if (!n) return "";
    return n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
  }

  let viewing = $state<string | null>(null);
  // The picture that was just asked for opens by itself once it arrives.
  $effect(() => {
    if (openWhenLoaded && images.length) {
      viewing = images[0].url;
      openWhenLoaded = false;
    }
  });
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }
  // Escape closes the picture, and only the picture: Big Picture listens for
  // it too, and used to take the whole view down with it.
  $effect(() => {
    if (!viewing) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopImmediatePropagation();
      viewing = null;
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });
</script>

{#if placeholder && onreveal}
  <button type="button" class="mb-chip is-button" onclick={reveal} disabled={revealing}
          title="Fetch the message from Discord and show it">
    {#if revealing}<span class="mb-spin"></span>{:else}<Icon name={placeholder.icon} size={12} />{/if}
    {revealing ? "Fetching it from Discord" : placeholder.label}
    {#if !revealing}<span class="mb-chip-go">Show</span>{/if}
  </button>
  {#if revealError}<span class="ml-2 text-[11.5px] text-warn">{revealError}</span>{/if}
{:else if placeholder}
  <span class="mb-chip"><Icon name={placeholder.icon} size={12} />{placeholder.label}</span>
{:else if text}
  <div class="mb-text" class:is-clamped={clamp > 0} style={clamp ? `-webkit-line-clamp:${clamp};line-clamp:${clamp}` : ""}>{#each parts as part}{#if part.kind === "text"}{@html discordInline(part.text)}{:else}<span class="mb-mention"><UserChip id={part.id} name={$mentionNames[part.id] || "user"} /></span>{/if}{/each}</div>
{/if}

{#if images.length || videos.length || drawnStickers.length || playedStickers.length}
  <div class="mb-media">
    {#each images as a (a.url)}
      <button type="button" class="mb-img" onclick={() => (viewing = a.url)} title="{a.name}, click to see it large">
        <img src={a.url} alt={a.name} loading="lazy" referrerpolicy="no-referrer" />
      </button>
    {/each}
    <!-- The app's own player (VideoPlayer), not the engine's controls. -->
    {#each videos as a (a.url)}
      <VideoPlayer src={a.url} name={a.name} />
    {/each}
    {#each drawnStickers as s (s.url)}
      <img class="mb-sticker" src={s.url} alt={s.name} title="Sticker: {s.name}" loading="lazy" referrerpolicy="no-referrer" />
    {/each}
    <!-- Discord's own stickers are animations, not pictures: played, not named. -->
    {#each playedStickers as s (s.id)}
      <LottieSticker id={s.id ?? ""} name={s.name} />
    {/each}
  </div>
{/if}

{#each namedStickers as s (s.name)}
  <span class="mb-chip"><Icon name="sparkle" size={12} />Sticker: {s.name}</span>
{/each}

{#each audios as a (a.url)}
  <VoiceNote src={a.url} name={a.name} />
{/each}

{#each files as a (a.url)}
  <a class="mb-file" href={a.url} target="_blank" rel="noopener noreferrer" title="Open {a.name}">
    <span class="mb-file-icon"><Icon name="clipboard" size={15} /></span>
    <span class="min-w-0 flex-1 truncate">{a.name}</span>
    {#if a.size}<span class="shrink-0 text-[11px] text-faint">{kb(a.size)}</span>{/if}
  </a>
{/each}

{#each embeds as e (e.url || e.title)}
  <a class="mb-embed" href={e.url || undefined} target="_blank" rel="noopener noreferrer">
    {#if e.image}<img src={e.image} alt="" loading="lazy" referrerpolicy="no-referrer" />{/if}
    <span class="min-w-0">
      {#if e.provider}<span class="block truncate text-[10.5px] text-faint">{e.provider}</span>{/if}
      {#if e.title}<span class="block truncate text-[12.5px] font-medium text-accent">{e.title}</span>{/if}
    </span>
  </a>
{/each}

{#if viewing}
  <div use:portal class="mb-view" role="dialog" aria-modal="true" aria-label="Picture" tabindex="-1"
       onclick={() => (viewing = null)} onkeydown={(e) => e.key === "Escape" && (viewing = null)}>
    <img src={viewing} alt="" referrerpolicy="no-referrer" />
    <a class="mb-view-open" href={viewing} target="_blank" rel="noopener noreferrer"
       onclick={(e) => e.stopPropagation()}>Open original</a>
  </div>
{/if}

<style>
  .mb-text {
    white-space: pre-wrap;
    word-break: break-word;
  }
  .mb-text.is-clamped {
    display: -webkit-box;
    overflow: hidden;
    -webkit-box-orient: vertical;
  }
  .mb-text :global(strong) { font-weight: 700; color: var(--color-ink); }
  .mb-text :global(em) { font-style: italic; }
  .mb-text :global(del) { opacity: 0.7; }
  .mb-text :global(.dm-code) {
    padding: 1px 5px;
    border-radius: 5px;
    font-family: ui-monospace, monospace;
    font-size: 0.88em;
    background: rgb(0 0 0 / 0.35);
  }
  .mb-text :global(.dm-pre) {
    display: block;
    margin: 4px 0;
    padding: 8px 10px;
    overflow-x: auto;
    border-radius: 8px;
    font-family: ui-monospace, monospace;
    font-size: 12px;
    white-space: pre;
    background: rgb(0 0 0 / 0.35);
  }
  .mb-text :global(.dm-quote) {
    display: inline-block;
    padding-left: 9px;
    border-left: 3px solid color-mix(in srgb, var(--color-faint) 70%, transparent);
  }
  .mb-text :global(.dm-h) { font-weight: 700; color: var(--color-ink); }
  .mb-text :global(.dm-h1) { font-size: 1.25em; }
  .mb-text :global(.dm-h2) { font-size: 1.12em; }
  .mb-text :global(.dm-li)::before { content: "• "; color: var(--color-faint); }
  .mb-text :global(.dm-link) { color: var(--color-accent); text-decoration: none; }
  .mb-text :global(.dm-link:hover) { text-decoration: underline; }
  .mb-text :global(.dm-emoji) {
    display: inline-block;
    width: 1.35em;
    height: 1.35em;
    vertical-align: -0.3em;
    object-fit: contain;
  }
  /* A spoiler stays hidden until it is pointed at, focused or clicked. */
  .mb-text :global(.dm-spoiler) {
    border-radius: 4px;
    color: transparent;
    background: color-mix(in srgb, var(--color-ink) 22%, transparent);
    cursor: pointer;
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .mb-text :global(.dm-spoiler:hover),
  .mb-text :global(.dm-spoiler:focus) {
    color: inherit;
    background: color-mix(in srgb, var(--color-ink) 8%, transparent);
  }

  .mb-mention :global(.user-chip) {
    border-radius: 6px;
    padding: 0 4px;
    background: color-mix(in srgb, var(--color-accent) 15%, transparent);
    color: color-mix(in srgb, var(--color-accent) 90%, var(--color-ink));
    font-weight: 500;
  }
  .mb-mention :global(.user-chip)::before { content: "@"; opacity: 0.7; }

  .mb-media {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 8px;
  }
  /* The picture itself, nothing around it. It used to sit on a dark plate, which
     inside a bubble that already has a background read as a box drawn around
     every image. */
  .mb-img {
    display: block;
    overflow: hidden;
    border-radius: 12px;
    transition: transform 0.2s var(--spring), box-shadow 0.2s ease;
  }
  .mb-img:hover { box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-accent) 55%, transparent); }
  .mb-img:active { transform: scale(0.98); }
  .mb-img img {
    display: block;
    max-width: min(260px, 100%);
    max-height: 180px;
    object-fit: cover;
  }
  .mb-sticker {
    width: 96px;
    height: 96px;
    object-fit: contain;
  }
  .mb-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    margin-top: 6px;
    padding: 3px 8px;
    border-radius: 999px;
    font-size: 11.5px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
  }
  .mb-chip.is-button {
    cursor: pointer;
    transition: background-color 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
  }
  .mb-chip.is-button:hover:not(:disabled) {
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 35%, transparent);
  }
  .mb-chip.is-button:disabled { cursor: default; }
  .mb-chip-go {
    margin-left: 2px;
    padding: 0 6px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 600;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .mb-spin {
    width: 11px;
    height: 11px;
    border-radius: 999px;
    border: 1.5px solid currentColor;
    border-top-color: transparent;
    animation: mb-spin 0.7s linear infinite;
  }
  @keyframes mb-spin { to { transform: rotate(360deg); } }
  .mb-file {
    display: flex;
    max-width: 340px;
    align-items: center;
    gap: 9px;
    margin-top: 8px;
    padding: 8px 10px;
    border-radius: 10px;
    font-size: 12.5px;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    transition: background-color 0.15s ease;
  }
  .mb-file:hover { background: rgb(255 255 255 / 0.07); }
  .mb-file-icon { display: inline-flex; color: var(--color-accent); }
  .mb-embed {
    display: flex;
    max-width: 380px;
    align-items: center;
    gap: 10px;
    margin-top: 8px;
    padding: 8px;
    border-radius: 10px;
    background: rgb(255 255 255 / 0.035);
    box-shadow: inset 3px 0 0 color-mix(in srgb, var(--color-accent) 60%, transparent);
  }
  .mb-embed img {
    width: 56px;
    height: 56px;
    flex-shrink: 0;
    border-radius: 7px;
    object-fit: cover;
  }

  .mb-view {
    position: fixed;
    inset: 0;
    /* Over everything, Big Picture (200) included: under it, a picture clicked
       there opened out of sight and seemed to do nothing. */
    z-index: 400;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 24px;
    background: rgb(0 0 0 / 0.8);
    backdrop-filter: blur(6px);
  }
  .mb-view img {
    /* A small picture is shown at a size you can see, not at its own. */
    min-width: min(320px, 92vw);
    max-width: min(92vw, 1100px);
    max-height: 82vh;
    border-radius: 12px;
    object-fit: contain;
  }
  .mb-view-open {
    padding: 6px 12px;
    border-radius: 9px;
    font-size: 12px;
    color: #fff;
    background: rgb(255 255 255 / 0.12);
  }
</style>
