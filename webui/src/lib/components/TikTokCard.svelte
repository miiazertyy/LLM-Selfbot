<script lang="ts">
  /**
   * A shared TikTok in a conversation, any platform's: its cover, its caption
   * and whose it is, the way the TikTok app shows a share, instead of a bare
   * link. Asked of TikTok's public oEmbed once per link (and kept here for the
   * session); while it answers, or if it will not, the link alone. Once the
   * persona has watched it (app/utils/tiktokwatch.py), what it saw in it too.
   */
  import Icon from "./Icon.svelte";
  import { api } from "../api";
  import { play } from "../uisound";

  let { url }: { url: string } = $props();

  type Card = { url: string; title: string; author: string; author_name: string; cover: string;
                seen?: string; said?: string };
  let card = $state<Card | null>(null);
  let coverOk = $state(true);

  const known = (globalThis as any).__ttCards ??= new Map<string, Promise<Card | null>>();

  $effect(() => {
    const u = url;
    let gone = false;
    // A sound when it arrives from TikTok, not when a kept one is drawn again.
    const asked = !known.has(u);
    if (asked) {
      const p = api.tiktokCard(u).catch(() => null);
      known.set(u, p);
      // Not watched yet: asked again the next time it is drawn, a minute on, as the persona may be watching it now.
      p.then((c: Card | null) => {
        if (!c?.seen) setTimeout(() => { if (known.get(u) === p) known.delete(u); }, 60_000);
      });
    }
    known.get(u)!.then((c: Card | null) => {
      if (gone || !c) return;
      card = c;
      if (asked) play("glint", { level: 0.35 });
    });
    return () => { gone = true; };
  });

  const seenTip = $derived(card?.seen ? `What it saw: ${card.seen}${card.said ? `\nWhat is said: "${card.said}"` : ""}` : "");
</script>

<a class="tt-card" class:is-loaded={!!card} href={url} target="_blank" rel="noopener noreferrer"
   title="Open it on TikTok">
  <span class="tt-cover">
    {#if card?.cover && coverOk}
      <img src={card.cover} alt="" loading="lazy" referrerpolicy="no-referrer" onerror={() => (coverOk = false)} />
    {/if}
    <span class="tt-play"><Icon name="play" size={14} /></span>
  </span>
  <span class="tt-meta">
    <span class="tt-from"><Icon name="tiktok" size={11} />TikTok</span>
    {#if card}
      {#if card.title}<span class="tt-title">{card.title}</span>{/if}
      {#if card.author}<span class="tt-author">@{card.author}</span>{/if}
      {#if card.seen}
        <span class="tt-seen" title={seenTip}><Icon name="eye" size={11} /><span>{card.seen}</span></span>
      {/if}
    {:else}
      <span class="tt-title tt-link">{url.replace(/^https?:\/\/(www\.)?/, "")}</span>
    {/if}
  </span>
</a>

<style>
  .tt-card {
    display: flex;
    max-width: 340px;
    gap: 10px;
    margin-top: 8px;
    padding: 7px;
    border-radius: 12px;
    background: linear-gradient(160deg, rgb(255 255 255 / 0.05), rgb(255 255 255 / 0.02));
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06), 0 6px 16px -10px rgb(0 0 0 / 0.6);
    transition: background-color 0.15s ease, box-shadow 0.2s ease, transform 0.2s ease;
  }
  .tt-card:hover {
    box-shadow: inset 0 0 0 1px rgb(254 44 85 / 0.28), 0 10px 22px -12px rgb(254 44 85 / 0.45);
    transform: translateY(-1px);
  }
  .tt-cover {
    position: relative;
    width: 58px;
    height: 78px;
    flex-shrink: 0;
    overflow: hidden;
    border-radius: 8px;
    background: linear-gradient(150deg, #25f4ee22, #fe2c5522), #111;
  }
  .tt-cover img { width: 100%; height: 100%; object-fit: cover; }
  .tt-play {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    color: #fff;
    filter: drop-shadow(0 1px 3px rgb(0 0 0 / 0.7));
  }
  .tt-meta { display: flex; min-width: 0; flex-direction: column; gap: 3px; padding: 2px 4px 2px 0; }
  .tt-from {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 10.5px;
    color: var(--color-faint);
  }
  .tt-title {
    display: -webkit-box;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    font-size: 12.5px;
    line-height: 1.35;
    color: var(--color-ink);
  }
  .tt-link { color: var(--color-accent); word-break: break-all; }
  .tt-author { font-size: 11.5px; font-weight: 600; color: #fe5c7c; }
  .tt-seen {
    display: flex;
    gap: 5px;
    margin-top: 2px;
    font-size: 11px;
    line-height: 1.35;
    color: var(--color-muted);
  }
  .tt-seen :global(svg) { flex-shrink: 0; margin-top: 1px; color: #25f4ee; opacity: 0.8; }
  .tt-seen span {
    display: -webkit-box;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
  }
  .tt-card.is-loaded .tt-meta { animation: tt-in 0.25s ease-out both; }
  @keyframes tt-in { from { opacity: 0; transform: translateY(3px); } }
  /* The app's own Animations switch, not Windows' setting, as everywhere else in it. */
  :global(html[data-motion="off"]) .tt-card,
  :global(html[data-motion="off"]) .tt-card.is-loaded .tt-meta { animation: none; transition: none; }
</style>
