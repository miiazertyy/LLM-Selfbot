<script lang="ts">
  /**
   * A shared Reddit or X post in a conversation, any platform's: whose it is, what it says, where it was posted
   * and what it scored, instead of a bare link.
   *
   * One component for both because the two are the same shape, and because neither can be read from outside any
   * more: Reddit's API stopped taking new apps and X's free tier reads nothing, so a signed-out fetch of either
   * gets a login wall. What fills this card is the account's own signed-in browser, asked through its runner
   * (app/utils/redditwatch.py, app/utils/xwatch.py), and what the persona saw in a picture on it once it has
   * looked. With no account of that platform running there is nothing to ask, and the card says only what the
   * link is rather than pretending to know.
   */
  import Icon from "./Icon.svelte";
  import { api } from "../api";
  import { play } from "../uisound";
  import { PLATFORMS } from "../platforms";

  let { url, platform }: { url: string; platform: "reddit" | "x" } = $props();

  type Card = {
    url: string; author: string; title: string; text: string; where: string;
    score: number; comments: number; cover: string; seen?: string; at?: number; unread?: boolean;
  };
  let card = $state<Card | null>(null);
  let coverOk = $state(true);

  const tone = $derived(PLATFORMS[platform].tone);
  const icon = $derived(PLATFORMS[platform].icon);
  /** "u/" on Reddit, "@" on X: the two write a name differently and everyone notices. */
  const at = $derived(platform === "reddit" ? "u/" : "@");

  const known = (globalThis as any).__postCards ??= new Map<string, Promise<Card | null>>();

  $effect(() => {
    const u = `${platform}:${url}`;
    let gone = false;
    // A sound when it arrives, not when a kept one is drawn again.
    const asked = !known.has(u);
    if (asked) {
      const p = (platform === "reddit" ? api.redditCard(url) : api.xCard(url)).catch(() => null);
      known.set(u, p);
      // Nothing came back: asked again the next time it is drawn, a minute on, as the account may be starting.
      p.then((c: Card | null) => {
        if (!c?.title && !c?.text) setTimeout(() => { if (known.get(u) === p) known.delete(u); }, 60_000);
      });
    }
    known.get(u)!.then((c: Card | null) => {
      if (gone || !c) return;
      card = c;
      coverOk = true;
      if (asked) play("glint", { level: 0.35 });
    });
    return () => { gone = true; };
  });

  const count = (n: number) => {
    if (!n) return "";
    if (Math.abs(n) < 1000) return String(n);
    if (Math.abs(n) < 1_000_000) return `${(n / 1000).toFixed(1).replace(".0", "")}k`;
    return `${(n / 1_000_000).toFixed(1).replace(".0", "")}m`;
  };
</script>

{#if card}
  <a class="pc" style="--brand: {tone}" href={card.url || url} target="_blank" rel="noopener noreferrer">
    {#if card.cover && coverOk}
      <img class="pc-cover" src={card.cover} alt="" loading="lazy" onerror={() => (coverOk = false)} />
    {:else}
      <span class="pc-cover pc-cover-none" aria-hidden="true"><Icon name={icon} size={18} /></span>
    {/if}
    <span class="pc-body">
      <span class="pc-who">
        <Icon name={icon} size={11} />
        {#if card.where}<b>{platform === "reddit" ? `r/${card.where}` : card.where}</b>{/if}
        {#if card.author}<span class="pc-by">{at}{card.author}</span>{/if}
      </span>
      {#if card.title}<span class="pc-title">{card.title}</span>{/if}
      {#if card.text}<span class="pc-text">{card.text}</span>{/if}
      {#if card.seen}<span class="pc-seen"><Icon name="eye" size={10} />{card.seen}</span>{/if}
      {#if card.score || card.comments}
        <span class="pc-counts">
          {#if card.score}<span>{count(card.score)} {platform === "reddit" ? "upvotes" : "likes"}</span>{/if}
          {#if card.comments}<span>{count(card.comments)} {platform === "reddit" ? "comments" : "replies"}</span>{/if}
        </span>
      {/if}
    </span>
  </a>
{/if}

<style>
  .pc {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    margin-top: 6px;
    padding: 9px 11px 9px 9px;
    max-width: 520px;
    border-radius: 12px;
    border: 1px solid color-mix(in srgb, var(--brand) 22%, var(--color-edge));
    background:
      radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, var(--brand) 10%, transparent), transparent 60%),
      var(--color-card);
    text-decoration: none;
    color: inherit;
    transition: border-color 0.25s var(--swift), transform 0.25s var(--spring);
  }
  .pc:hover { border-color: color-mix(in srgb, var(--brand) 45%, var(--color-edge)); transform: translateY(-1px); }
  .pc-cover {
    flex: none;
    width: 62px;
    height: 62px;
    border-radius: 9px;
    object-fit: cover;
    background: rgb(255 255 255 / 0.04);
  }
  .pc-cover-none {
    display: grid;
    place-items: center;
    color: color-mix(in srgb, var(--brand) 80%, white);
  }
  .pc-body { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
  .pc-who {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    color: color-mix(in srgb, var(--brand) 70%, var(--color-muted));
  }
  .pc-by { color: var(--color-faint); }
  .pc-title {
    font-size: 13px;
    font-weight: 600;
    line-height: 1.3;
    color: var(--color-ink);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .pc-text {
    font-size: 11.5px;
    line-height: 1.35;
    color: var(--color-muted);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .pc-seen {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-top: 2px;
    font-size: 10.5px;
    font-style: italic;
    color: var(--color-faint);
  }
  .pc-counts { display: flex; gap: 10px; margin-top: 3px; font-size: 10.5px; color: var(--color-faint); }
</style>
