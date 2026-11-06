<script lang="ts">
  /**
   * A shared Instagram reel, post or story in a conversation, any platform's:
   * its picture, its caption and whose it is, the way Instagram shows a share,
   * instead of a bare link. Asked of Instagram's embed page once per link (and
   * kept here for the session); while it answers, or if it will not, the link
   * alone. Once the persona has watched it (app/utils/instagramwatch.py), what
   * it saw in it too.
   *
   * A story, and a post Instagram will not embed, say only what the link is:
   * the card says as much rather than pretending to know.
   */
  import Icon from "./Icon.svelte";
  import { api } from "../api";
  import { play } from "../uisound";

  let { url }: { url: string } = $props();

  type Card = { url: string; kind: string; title: string; author: string; author_name: string; cover: string;
                seen?: string; said?: string; private?: boolean };
  let card = $state<Card | null>(null);
  let coverOk = $state(true);

  const known = (globalThis as any).__igCards ??= new Map<string, Promise<Card | null>>();

  $effect(() => {
    const u = url;
    let gone = false;
    // A sound when it arrives from Instagram, not when a kept one is drawn again.
    const asked = !known.has(u);
    if (asked) {
      const p = api.instagramCard(u).catch(() => null);
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

  const what = $derived(card?.kind === "reel" ? "Reel" : card?.kind === "story" ? "Story" : "Post");
  const seenTip = $derived(card?.seen ? `What it saw: ${card.seen}${card.said ? `\nWhat is said: "${card.said}"` : ""}` : "");
</script>

<a class="ig-card" class:is-loaded={!!card} class:is-still={card?.kind === "post"}
   href={url} target="_blank" rel="noopener noreferrer" title="Open it on Instagram">
  <span class="ig-cover">
    {#if card?.cover && coverOk}
      <img src={card.cover} alt="" loading="lazy" referrerpolicy="no-referrer" onerror={() => (coverOk = false)} />
    {/if}
    {#if card?.kind !== "post"}
      <span class="ig-play"><Icon name="play" size={14} /></span>
    {/if}
  </span>
  <span class="ig-meta">
    <span class="ig-from"><Icon name="instagram" size={11} />{card ? what : "Instagram"}</span>
    {#if card}
      {#if card.title}<span class="ig-title">{card.title}</span>{/if}
      {#if card.author}<span class="ig-author">@{card.author}</span>{/if}
      {#if card.seen}
        <span class="ig-seen" title={seenTip}><Icon name="eye" size={11} /><span>{card.seen}</span></span>
      {:else if card.private}
        <span class="ig-seen"><Icon name="eyeOff" size={11} /><span>Instagram shows this only to someone signed in</span></span>
      {/if}
    {:else}
      <span class="ig-title ig-link">{url.replace(/^https?:\/\/(www\.)?/, "")}</span>
    {/if}
  </span>
</a>

<style>
  .ig-card {
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
  .ig-card:hover {
    box-shadow: inset 0 0 0 1px rgb(225 48 108 / 0.28), 0 10px 22px -12px rgb(225 48 108 / 0.45);
    transform: translateY(-1px);
  }
  .ig-cover {
    position: relative;
    width: 58px;
    height: 78px;
    flex-shrink: 0;
    overflow: hidden;
    border-radius: 8px;
    /* Instagram's own gradient, faint, where there is no picture yet. */
    background: linear-gradient(150deg, #feda7522, #d6297622, #4f5bd522), #121014;
  }
  /* A post is a square, not a tall one: the shape says which it is before the words do. */
  .ig-card.is-still .ig-cover { width: 70px; height: 70px; }
  .ig-cover img { width: 100%; height: 100%; object-fit: cover; }
  .ig-play {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    color: #fff;
    filter: drop-shadow(0 1px 3px rgb(0 0 0 / 0.7));
  }
  .ig-meta { display: flex; min-width: 0; flex-direction: column; gap: 3px; padding: 2px 4px 2px 0; }
  .ig-from {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 10.5px;
    color: var(--color-faint);
  }
  .ig-title {
    display: -webkit-box;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    font-size: 12.5px;
    line-height: 1.35;
    color: var(--color-ink);
  }
  .ig-link { color: var(--color-accent); word-break: break-all; }
  .ig-author { font-size: 11.5px; font-weight: 600; color: #f06292; }
  .ig-seen {
    display: flex;
    gap: 5px;
    margin-top: 2px;
    font-size: 11px;
    line-height: 1.35;
    color: var(--color-muted);
  }
  .ig-seen :global(svg) { flex-shrink: 0; margin-top: 1px; color: #fa7e1e; opacity: 0.85; }
  .ig-seen span {
    display: -webkit-box;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
  }
  .ig-card.is-loaded .ig-meta { animation: ig-in 0.25s ease-out both; }
  @keyframes ig-in { from { opacity: 0; transform: translateY(3px); } }
  /* The app's own Animations switch, not Windows' setting, as everywhere else in it. */
  :global(html[data-motion="off"]) .ig-card,
  :global(html[data-motion="off"]) .ig-card.is-loaded .ig-meta { animation: none; transition: none; }
</style>
