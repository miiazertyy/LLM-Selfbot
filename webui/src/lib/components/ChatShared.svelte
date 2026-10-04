<script lang="ts">
  /**
   * What was shared in a conversation: its pictures and videos, its files and
   * voice messages, its links. Newest first, by month, each a click away from
   * the message it came in.
   *
   * From what is kept here (app/utils/chatlog.py), where pictures are saved so
   * they still show after Discord's own links have expired. On a Discord
   * account, "Older" asks Discord's search (has:image and the rest) for what
   * came before that.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import { fmtDate, FULL_WHEN } from "../fmt";
  import { play } from "../uisound";
  import { domainOf, fold, prettyUrl } from "../chatsearch";
  import { menu as contextMenu, copyText, type MenuEntry } from "../contextmenu";
  import { saveUrlAs } from "../window";
  import { toast } from "../stores";
  import Icon from "./Icon.svelte";
  import VoiceNote from "./VoiceNote.svelte";
  import VideoPlayer from "./VideoPlayer.svelte";

  type Kind = "media" | "files" | "links";
  type Item = {
    mid: string; ts: number; mine: boolean; deleted?: number;
    url: string; name?: string; type?: string; size?: number;
    kind?: string; title?: string; image?: string; text?: string;
  };
  type Side = { name: string; avatar?: string };

  let {
    kind,
    target,
    uid,
    platform,
    them,
    onjump,
  }: {
    kind: Kind;
    target: string;
    uid: string;
    platform: string;
    them: Side;
    onjump: (mid: string) => Promise<unknown> | void;
  } = $props();

  const WORDS: Record<Kind, { none: string; filter: string }> = {
    media: { none: "No pictures or videos yet", filter: "" },
    files: { none: "No files yet", filter: "Filter files" },
    links: { none: "No links yet", filter: "Filter links" },
  };

  let items = $state<Item[]>([]);
  let loading = $state(true);
  let error = $state("");
  let kept = $state(0);
  let since = $state<number | null>(null);
  let filter = $state("");
  let broken = $state<Record<string, true>>({});

  async function load() {
    loading = true;
    error = "";
    try {
      const r = await api.chatsShared(uid, target, kind);
      items = r.items || [];
      kept = r.kept ?? 0;
      since = r.since ?? null;
    } catch (e: any) {
      error = e?.message || "Could not read it";
    } finally {
      loading = false;
    }
  }
  onMount(load);

  // ── Older, from Discord's search ───────────────────────────────────────
  const HAS_FOR: Record<Kind, string[]> = { media: ["image", "video"], files: ["file", "sound"], links: ["link", "embed"] };
  const URL_RE = /https?:\/\/[^\s<>"'`)\]]+/gi;
  let older = $state({ on: false, loading: false, more: true, error: "", cursor: "" });

  function attKind(a: { type?: string; name?: string; url?: string }): string {
    const t = (a.type || "").toLowerCase();
    const n = (a.name || a.url || "").toLowerCase().split("?")[0];
    if (t.startsWith("image/") || /\.(png|jpe?g|gif|webp|avif|bmp|heic)$/.test(n)) return "image";
    if (t.startsWith("video/") || /\.(mp4|webm|mov|mkv|m4v)$/.test(n)) return "video";
    if (t.startsWith("audio/") || /\.(ogg|mp3|wav|m4a|opus|flac|aac)$/.test(n)) return "sound";
    return "file";
  }

  /** A message found by Discord's search, as the items this tab lists (the same as the server's shared()). */
  function itemsOf(m: any): Item[] {
    const base = { mid: String(m.mid), ts: m.ts, mine: !!m.mine, deleted: m.deleted };
    if (kind === "links") {
      const seen = new Set<string>();
      const out: Item[] = [];
      for (const raw of (m.text || "").match(URL_RE) || []) {
        const url = raw.replace(/[.,;:!?]+$/, "");
        if (!seen.has(url)) {
          seen.add(url);
          out.push({ ...base, url, text: m.text });
        }
      }
      for (const e of m.embeds || []) {
        if (e.url && /^https?:\/\//.test(e.url) && !seen.has(e.url)) {
          seen.add(e.url);
          out.push({ ...base, url: e.url, title: e.title, image: e.image, text: m.text });
        }
      }
      return out;
    }
    return (m.attachments || [])
      .map((a: any) => ({ ...base, ...a, kind: attKind(a) }))
      .filter((it: Item) => (kind === "media") === (it.kind === "image" || it.kind === "video"));
  }

  async function loadOlder() {
    if (older.loading || !older.more) return;
    older = { ...older, on: true, loading: true, error: "" };
    try {
      let added = 0;
      // A page of has:file can be all pictures, which this tab does not list: a few pages before giving up on one click.
      for (let pages = 0; pages < 4 && !added && older.more; pages++) {
        const q = { words: [], mine: null, has: HAS_FOR[kind], before: older.cursor ? null : since, after: null };
        const r = await api.chatsSearchDiscord(uid, target, q, "newest", older.cursor ? { cursor: older.cursor } : {});
        const msgs = r.messages || [];
        const have = new Set(items.map((i) => `${i.mid}|${i.url}`));
        const add = msgs.flatMap(itemsOf).filter((i: Item) => !have.has(`${i.mid}|${i.url}`));
        items = [...items, ...add];
        added += add.length;
        older = { ...older, more: !!r.more && msgs.length > 0, cursor: msgs.length ? String(msgs[msgs.length - 1].mid) : older.cursor };
      }
      older = { ...older, loading: false };
    } catch (e: any) {
      older = { ...older, loading: false, error: e?.message || "Discord did not answer" };
    }
  }

  // ── What is shown ──────────────────────────────────────────────────────
  const shown = $derived.by(() => {
    const f = fold(filter.trim());
    if (!f) return items;
    return items.filter((it) => fold([it.name, it.url, it.title, it.text].filter(Boolean).join(" ")).includes(f));
  });

  const months = $derived.by(() => {
    const out: { key: string; label: string; items: { it: Item; i: number }[] }[] = [];
    const now = new Date();
    shown.forEach((it, i) => {
      const d = new Date(it.ts * 1000);
      const key = `${d.getFullYear()}-${d.getMonth()}`;
      let g = out[out.length - 1];
      if (!g || g.key !== key) {
        const label = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()
          ? "This month"
          : fmtDate(d, d.getFullYear() === now.getFullYear() ? { month: "long" } : { month: "long", year: "numeric" });
        out.push((g = { key, label, items: [] }));
      }
      g.items.push({ it, i });
    });
    return out;
  });

  const who = (it: Item) => (it.mine ? "You" : them.name);
  const day = (ts: number) => fmtDate(ts * 1000, { day: "numeric", month: "short" });
  function size(n?: number): string {
    if (!n) return "";
    return n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
  }
  /** A colour of its own for each site, steady from one visit to the next. */
  const hue = (s: string) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);

  function itemMenu(it: Item): MenuEntry[] {
    const picture = it.kind === "image" || it.kind === "video";
    return [
      { label: "Jump to message", icon: "jump", run: () => onjump(it.mid) },
      { label: "Open", icon: "external", run: () => window.open(it.url, "_blank", "noopener") },
      picture && { label: it.kind === "video" ? "Save video" : "Save picture", icon: "download", run: () => save(it) },
      { label: "Copy link", icon: "link", run: () => copyText(it.url, "Copied the link.") },
    ];
  }

  async function save(it: Item) {
    try {
      const where = await saveUrlAs(it.url, it.name || "picture");
      if (where) toast("Saved.", "ok");
    } catch (e: any) {
      toast(e?.message || "Could not save it", "err");
    }
  }

  // ── Seeing one large ───────────────────────────────────────────────────
  let viewing = $state(-1);
  const cur = $derived(viewing >= 0 && viewing < shown.length ? shown[viewing] : null);

  function openAt(i: number) {
    viewing = i;
    play("open");
  }
  function step(d: number) {
    if (!shown.length) return;
    viewing = (viewing + d + shown.length) % shown.length;
    play("tick");
  }
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }
  // The arrows and Escape belong to the picture while it is open, and only to it.
  $effect(() => {
    if (viewing < 0) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") viewing = -1;
      else if (e.key === "ArrowRight") step(1);
      else if (e.key === "ArrowLeft") step(-1);
      else return;
      e.preventDefault();
      e.stopImmediatePropagation();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });
</script>

<div class="sh">
  {#if kind !== "media" && items.length > 4}
    <label class="sh-filter">
      <Icon name="filter" size={13} />
      <input bind:value={filter} placeholder={WORDS[kind].filter} spellcheck="false" />
      {#if filter}<button type="button" onclick={() => (filter = "")} aria-label="Clear"><Icon name="close" size={10} /></button>{/if}
    </label>
  {/if}

  <div class="sh-scroll">
    {#if loading}
      <div class={kind === "media" ? "sh-grid" : "sh-list"}>
        {#each Array(kind === "media" ? 9 : 5) as _, i (i)}<div class={kind === "media" ? "sh-tile is-skel" : "sh-row is-skel"}></div>{/each}
      </div>
    {:else if error}
      <p class="sh-note text-warn">{error} <button type="button" class="sh-link" onclick={load}>Try again</button></p>
    {:else if !shown.length && !older.loading}
      <div class="sh-none">
        <span class="sh-none-icon"><Icon name={kind === "media" ? "pictures" : kind === "files" ? "file" : "link"} size={20} /></span>
        <b>{filter ? "Nothing matches" : WORDS[kind].none}</b>
        {#if !filter && kept}<span>In the last {kept} messages.</span>{/if}
      </div>
    {/if}

    {#each months as g (g.key)}
      <div class="sh-month">{g.label}<span>{g.items.length}</span></div>
      {#if kind === "media"}
        <div class="sh-grid">
          {#each g.items as { it, i } (`${it.mid}|${it.url}`)}
            <button type="button" class="sh-tile" class:is-deleted={!!it.deleted} onclick={() => openAt(i)}
                    use:contextMenu={() => itemMenu(it)} title="{who(it)} · {fmtDate(it.ts * 1000, FULL_WHEN)}">
              {#if broken[it.url]}
                <span class="sh-gone"><Icon name="pictures" size={16} /><small>Expired</small></span>
              {:else if it.kind === "video"}
                <video src="{it.url}#t=0.1" preload="metadata" muted playsinline onerror={() => (broken[it.url] = true)}></video>
                <span class="sh-play"><Icon name="play" size={13} /></span>
              {:else}
                <img src={it.url} alt={it.name ?? ""} loading="lazy" referrerpolicy="no-referrer" onerror={() => (broken[it.url] = true)} />
              {/if}
              {#if it.deleted}<span class="sh-bin" title="Deleted"><Icon name="trash" size={10} /></span>{/if}
            </button>
          {/each}
        </div>
      {:else}
        <div class="sh-list">
          {#each g.items as { it } (`${it.mid}|${it.url}`)}
            <div class="sh-row" class:is-deleted={!!it.deleted} use:contextMenu={() => itemMenu(it)}>
              {#if kind === "links"}
                {#if it.image && !broken[it.image]}
                  <img class="sh-thumb" src={it.image} alt="" loading="lazy" referrerpolicy="no-referrer" onerror={() => (broken[it.image ?? ""] = true)} />
                {:else}
                  <span class="sh-site" style="--h: {hue(domainOf(it.url))}">{(domainOf(it.url)[0] ?? "?").toUpperCase()}</span>
                {/if}
              {:else}
                <span class="sh-ficon" class:is-sound={it.kind === "sound"}><Icon name={it.kind === "sound" ? "mic" : "file"} size={16} /></span>
              {/if}
              <span class="sh-main">
                <a class="sh-name" href={it.url} target="_blank" rel="noopener noreferrer" title={it.url}>
                  {kind === "links" ? it.title || prettyUrl(it.url) : it.name || "File"}
                </a>
                <span class="sh-meta">
                  {#if kind === "links"}{domainOf(it.url)} · {:else if it.size}{size(it.size)} · {/if}{who(it)} · {day(it.ts)}{#if it.deleted} · <span class="text-bad">deleted</span>{/if}
                </span>
                {#if it.kind === "sound"}<span class="sh-voice"><VoiceNote src={it.url} name={it.name ?? ""} /></span>{/if}
              </span>
              <button type="button" class="sh-jump" onclick={() => onjump(it.mid)} title="Jump to message" aria-label="Jump to message">
                <Icon name="jump" size={13} />
              </button>
            </div>
          {/each}
        </div>
      {/if}
    {/each}

    {#if !loading && !error}
      <div class="sh-foot">
        {#if older.error}
          <span class="text-warn">{older.error}</span>
          <button type="button" class="sh-link" onclick={loadOlder}>Try again</button>
        {:else if platform === "discord" && older.more}
          <span>{older.on ? "Older ones from Discord" : kept ? `From the last ${kept} messages` : ""}</span>
          <button type="button" class="sh-older" onclick={loadOlder} disabled={older.loading}>
            {#if older.loading}<span class="sh-spin"></span>{:else}<Icon name="search" size={12} />{/if}Older on Discord
          </button>
        {:else if older.on}
          <span>That's everything.</span>
        {:else if kept}
          <span>From the last {kept} messages.</span>
        {/if}
      </div>
    {/if}
  </div>
</div>

{#if cur}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
  <div use:portal class="sh-view" role="dialog" aria-modal="true" aria-label="Picture" tabindex="-1" onclick={() => (viewing = -1)}>
    {#key cur.url}
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
      <div class="sh-view-stage" onclick={(e) => e.stopPropagation()}>
        {#if cur.kind === "video"}
          <VideoPlayer src={cur.url} name={cur.name ?? "video"} />
        {:else}
          <img src={cur.url} alt={cur.name ?? ""} referrerpolicy="no-referrer" />
        {/if}
      </div>
    {/key}
    {#if shown.length > 1}
      <button type="button" class="sh-view-nav is-prev" onclick={(e) => { e.stopPropagation(); step(-1); }} aria-label="Previous">
        <Icon name="chevron" size={18} />
      </button>
      <button type="button" class="sh-view-nav is-next" onclick={(e) => { e.stopPropagation(); step(1); }} aria-label="Next">
        <Icon name="chevron" size={18} />
      </button>
    {/if}
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div class="sh-view-bar" onclick={(e) => e.stopPropagation()}>
      <span class="min-w-0 truncate">{who(cur)} · {fmtDate(cur.ts * 1000, FULL_WHEN)}{#if shown.length > 1}<span class="text-faint"> · {viewing + 1} of {shown.length}</span>{/if}</span>
      <button type="button" onclick={() => { const m = cur.mid; viewing = -1; onjump(m); }}><Icon name="jump" size={13} />Jump to message</button>
      <button type="button" onclick={() => save(cur)}><Icon name="download" size={13} />Save</button>
      <a href={cur.url} target="_blank" rel="noopener noreferrer"><Icon name="external" size={13} />Open</a>
      <button type="button" class="sh-view-x" onclick={() => (viewing = -1)} aria-label="Close"><Icon name="close" size={13} /></button>
    </div>
  </div>
{/if}

<style>
  .sh { display: flex; min-height: 0; flex: 1; flex-direction: column; }
  .sh-scroll { min-height: 0; flex: 1; overflow-y: auto; padding: 4px 12px 14px; }
  .sh-filter {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 12px 12px 4px;
    padding: 0 10px;
    height: 36px;
    border-radius: 12px;
    color: var(--color-faint);
    background: rgb(0 0 0 / 0.22);
    box-shadow: inset 0 0 0 1px var(--color-edge);
  }
  .sh-filter:focus-within { color: var(--color-accent); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 55%, transparent); }
  .sh-filter input { min-width: 0; flex: 1; font-size: 12.5px; color: var(--color-ink); background: transparent; outline: none; }
  .sh-filter input::placeholder { color: var(--color-faint); }
  .sh-month {
    display: flex;
    align-items: center;
    gap: 7px;
    margin: 12px 2px 7px;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--color-faint);
  }
  .sh-month span { padding: 0 6px; border-radius: 999px; letter-spacing: 0; color: var(--color-muted); background: rgb(255 255 255 / 0.06); }

  /* ── Pictures and videos ─────────────────────────────────────────── */
  .sh-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(92px, 1fr)); gap: 4px; }
  .sh-tile {
    position: relative;
    aspect-ratio: 1;
    overflow: hidden;
    border-radius: 10px;
    background: rgb(255 255 255 / 0.05);
    transition: transform 0.22s var(--spring), box-shadow 0.18s ease, filter 0.18s ease;
  }
  .sh-tile:hover { z-index: 1; transform: scale(1.035); box-shadow: 0 10px 26px -12px rgb(0 0 0 / 0.9), 0 0 0 1.5px color-mix(in srgb, var(--color-accent) 55%, transparent); }
  .sh-tile img, .sh-tile video { width: 100%; height: 100%; object-fit: cover; pointer-events: none; }
  .sh-tile.is-deleted img, .sh-tile.is-deleted video { filter: grayscale(0.5); opacity: 0.75; }
  .sh-tile.is-skel, .sh-row.is-skel { animation: sh-pulse 1.3s ease-in-out infinite; }
  .sh-play {
    position: absolute;
    left: 50%;
    top: 50%;
    display: grid;
    width: 30px;
    height: 30px;
    margin: -15px 0 0 -15px;
    place-items: center;
    border-radius: 999px;
    color: #fff;
    background: rgb(0 0 0 / 0.5);
    backdrop-filter: blur(4px);
  }
  .sh-bin {
    position: absolute;
    top: 5px;
    right: 5px;
    display: grid;
    width: 18px;
    height: 18px;
    place-items: center;
    border-radius: 999px;
    color: #fff;
    background: var(--color-bad);
  }
  .sh-gone { display: flex; height: 100%; flex-direction: column; align-items: center; justify-content: center; gap: 3px; color: var(--color-faint); }
  .sh-gone small { font-size: 10px; }

  /* ── Files and links ─────────────────────────────────────────────── */
  .sh-list { display: flex; flex-direction: column; gap: 3px; }
  .sh-row {
    display: flex;
    align-items: center;
    gap: 11px;
    min-height: 54px;
    padding: 8px 8px 8px 9px;
    border-radius: 12px;
    background: rgb(255 255 255 / 0.025);
    transition: background-color 0.14s ease;
  }
  .sh-row:hover { background: rgb(255 255 255 / 0.055); }
  .sh-row.is-deleted { opacity: 0.7; }
  .sh-ficon, .sh-site, .sh-thumb {
    display: grid;
    width: 38px;
    height: 38px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 10px;
    object-fit: cover;
  }
  .sh-ficon { color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 13%, transparent); }
  .sh-ficon.is-sound { color: var(--color-good); background: color-mix(in srgb, var(--color-good) 13%, transparent); }
  .sh-site {
    font-size: 15px;
    font-weight: 700;
    color: hsl(var(--h) 70% 78%);
    background: hsl(var(--h) 45% 30% / 0.45);
  }
  .sh-main { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 2px; }
  .sh-name {
    overflow: hidden;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--color-ink);
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .sh-name:hover { color: var(--color-accent); text-decoration: underline; }
  .sh-meta { overflow: hidden; font-size: 11px; color: var(--color-faint); white-space: nowrap; text-overflow: ellipsis; }
  .sh-voice { margin-top: 4px; }
  .sh-jump {
    display: grid;
    width: 28px;
    height: 28px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 9px;
    color: var(--color-faint);
    opacity: 0;
    transition: opacity 0.15s ease, color 0.15s ease, background-color 0.15s ease;
  }
  .sh-row:hover .sh-jump, .sh-jump:focus-visible { opacity: 1; }
  .sh-jump:hover { color: var(--color-bg); background: var(--color-accent); }

  .sh-none {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 44px 18px 20px;
    text-align: center;
    font-size: 12px;
    color: var(--color-faint);
  }
  .sh-none b { font-size: 13.5px; color: var(--color-ink); }
  .sh-none-icon {
    display: grid;
    width: 46px;
    height: 46px;
    margin-bottom: 4px;
    place-items: center;
    border-radius: 999px;
    background: rgb(255 255 255 / 0.05);
  }
  .sh-note { padding: 18px; text-align: center; font-size: 12px; }
  .sh-link { font-weight: 600; color: var(--color-accent); }
  .sh-link:hover { text-decoration: underline; }
  .sh-foot { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 6px 10px; padding: 16px 6px 4px; font-size: 11px; color: var(--color-faint); }
  .sh-older {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border-radius: 10px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.07);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    transition: background-color 0.15s ease;
  }
  .sh-older:hover:not(:disabled) { background: rgb(255 255 255 / 0.12); }
  .sh-spin {
    width: 11px;
    height: 11px;
    border-radius: 999px;
    border: 1.5px solid color-mix(in srgb, var(--color-accent) 30%, transparent);
    border-top-color: var(--color-accent);
    animation: sh-spin 0.7s linear infinite;
  }

  /* ── One, large ──────────────────────────────────────────────────── */
  .sh-view {
    position: fixed;
    inset: 0;
    z-index: 200;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 14px;
    padding: 40px 72px 24px;
    background: rgb(4 4 10 / 0.86);
    backdrop-filter: blur(14px);
    animation: sh-fade 0.2s ease both;
  }
  .sh-view-stage { display: flex; min-height: 0; max-width: 100%; flex: 1; align-items: center; justify-content: center; animation: sh-zoom 0.32s var(--spring) both; }
  .sh-view-stage img { max-width: 100%; max-height: 100%; border-radius: 12px; object-fit: contain; box-shadow: 0 30px 80px -30px rgb(0 0 0 / 0.9); }
  .sh-view-stage :global(.vp) { max-height: 100%; }
  .sh-view-bar {
    display: flex;
    max-width: 100%;
    align-items: center;
    gap: 6px;
    padding: 6px 6px 6px 14px;
    border-radius: 14px;
    font-size: 12px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.07);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08);
  }
  .sh-view-bar button, .sh-view-bar a {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    border-radius: 10px;
    font-weight: 600;
    color: var(--color-ink);
    transition: background-color 0.15s ease;
  }
  .sh-view-bar button:hover, .sh-view-bar a:hover { background: rgb(255 255 255 / 0.1); }
  .sh-view-bar .sh-view-x { padding: 6px; }
  .sh-view-nav {
    position: absolute;
    top: 50%;
    display: grid;
    width: 44px;
    height: 44px;
    margin-top: -22px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.08);
    transition: background-color 0.15s ease, transform 0.2s var(--spring);
  }
  .sh-view-nav:hover { background: rgb(255 255 255 / 0.16); transform: scale(1.06); }
  .sh-view-nav.is-prev { left: 16px; transform: rotate(180deg); }
  .sh-view-nav.is-prev:hover { transform: rotate(180deg) scale(1.06); }
  .sh-view-nav.is-next { right: 16px; }

  @keyframes sh-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
  @keyframes sh-spin { to { transform: rotate(360deg); } }
  @keyframes sh-fade { from { opacity: 0; } }
  @keyframes sh-zoom { from { opacity: 0; transform: scale(0.94); } to { opacity: 1; transform: none; } }
  :global(:root[data-motion="off"]) .sh-view,
  :global(:root[data-motion="off"]) .sh-view-stage { animation: none; }
</style>
