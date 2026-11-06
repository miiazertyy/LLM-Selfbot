<script lang="ts">
  /**
   * Their TikToks, beside a TikTok conversation: who they are on TikTok and
   * what they post, as the account last read their profile (when they write,
   * every few hours), with what the persona saw in the posts it watched. Each
   * post can be liked, saved or commented on from here, as the account: your
   * own choice, whatever the automatic switches in Settings say.
   */
  import Icon from "./Icon.svelte";
  import { api } from "../api";
  import { play } from "../uisound";
  import { toast } from "../stores";

  let { target, uid, them }: { target: string; uid: string; them: { name: string; avatar?: string } } = $props();

  type Post = {
    id: string; url: string; caption: string; views: string; pinned: boolean; cover: string; photo: boolean;
    seen: string; said: string; likes: number; created: number;
  };
  type Theirs = {
    handle: string; name: string; bio: string; followers: number | null; verified: boolean;
    posts: Post[]; posts_at: number; newest: string;
  };

  let info = $state<Theirs | null>(null);
  let failed = $state("");
  let looking = $state(false);
  let busy = $state<Record<string, string>>({});
  let done = $state<Record<string, { liked?: boolean; saved?: boolean; commented?: boolean }>>({});
  let writing = $state("");
  let draft = $state("");
  let drafting = $state(false);
  let badCover = $state<Record<string, true>>({});

  // Each conversation's own: what one asked for is never shown for another (it captures its own keys).
  function load(t: string, u: string, sound: boolean) {
    api.tiktokTheirs(t, u)
      .then((r: Theirs) => {
        if (t !== target || u !== uid) return;
        info = r;
        failed = "";
        if (sound && r.posts.length) play("glint", { level: 0.4 });
      })
      .catch((e: Error) => { if (t === target && u === uid) failed = e.message; });
  }

  $effect(() => {
    const t = target, u = uid;
    info = null;
    load(t, u, true);
  });

  async function lookNow() {
    if (looking) return;
    looking = true;
    play("tap");
    const t = target, u = uid;
    try {
      const r: Theirs = await api.tiktokTheirsRefresh(t, u);
      if (t === target && u === uid) {
        info = r;
        play(r.posts.length ? "glint" : "info");
      }
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      looking = false;
    }
  }

  async function act(p: Post, action: "like" | "save") {
    if (busy[p.id]) return;
    busy[p.id] = action;
    play("tap");
    try {
      const r = await api.tiktokAction(target, p.url, action);
      done[p.id] = { ...done[p.id], [action === "like" ? "liked" : "saved"]: true };
      play(action === "like" ? "pluck" : "seat");
      if (r.dry) toast("Dry run: nothing was pressed on TikTok.", "info");
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      delete busy[p.id];
    }
  }

  function openComment(p: Post) {
    if (writing === p.id) {
      writing = "";
      play("off");
      return;
    }
    writing = p.id;
    draft = "";
    play("open");
  }

  async function suggest(p: Post) {
    if (drafting) return;
    drafting = true;
    play("tap");
    try {
      const r = await api.tiktokCommentText(target, p.url);
      if (writing === p.id) {
        draft = r.text || "";
        play("glint", { level: 0.5 });
      }
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      drafting = false;
    }
  }

  async function comment(p: Post) {
    const text = draft.trim();
    if (!text || busy[p.id]) return;
    busy[p.id] = "comment";
    play("send");
    try {
      const r = await api.tiktokAction(target, p.url, "comment", text);
      done[p.id] = { ...done[p.id], commented: true };
      writing = "";
      draft = "";
      toast(r.dry ? "Dry run: the comment was typed, not posted." : "Commented.", r.dry ? "info" : "ok");
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      delete busy[p.id];
    }
  }

  const ago = (secs: number) => {
    if (!secs) return "";
    const d = Math.floor((Date.now() / 1000 - secs) / 86400);
    return d < 1 ? "today" : d === 1 ? "yesterday" : d < 30 ? `${d} days ago` : d < 365 ? `${Math.floor(d / 30)} mo ago` : `${Math.floor(d / 365)} y ago`;
  };
  const followers = (n: number | null) =>
    n == null ? "" : n >= 1e6 ? `${(Math.floor(n / 1e5) / 10).toString()}M` : n >= 1e4 ? `${(Math.floor(n / 100) / 10).toString()}K` : String(n);
</script>

<div class="tt">
  <header class="tt-who">
    <div class="tt-id">
      <span class="tt-name">{info?.name || them.name}{#if info?.verified}<span class="tt-tick" title="Verified"><Icon name="check" size={9} /></span>{/if}</span>
      {#if info?.handle}<span class="tt-handle">@{info.handle}</span>{/if}
      {#if info?.followers != null}<span class="tt-count">{followers(info.followers)} followers</span>{/if}
    </div>
    <button type="button" class="tt-look" class:is-busy={looking} onclick={lookNow} disabled={looking}
            title="Look at their profile now" aria-label="Look at their profile now">
      <Icon name="refresh" size={13} />
    </button>
  </header>
  {#if info?.bio}<p class="tt-bio">{info.bio}</p>{/if}

  {#if failed}
    <p class="tt-empty">{failed}</p>
  {:else if !info}
    <p class="tt-empty">Loading...</p>
  {:else if !info.posts.length}
    <div class="tt-empty">
      <span>{info.posts_at ? "No posts on their profile." : "Their posts are read when they write."}</span>
      <button type="button" class="tt-now" onclick={lookNow} disabled={looking}>{looking ? "Looking..." : "Look now"}</button>
    </div>
  {:else}
    <ul class="tt-posts">
      {#each info.posts as p, i (p.id)}
        <li class="tt-post" style="--i: {i}">
          <a class="tt-cover" href={p.url} target="_blank" rel="noopener noreferrer" title="Open it on TikTok">
            {#if p.cover && !badCover[p.id]}
              <img src={p.cover} alt="" loading="lazy" referrerpolicy="no-referrer" onerror={() => (badCover[p.id] = true)} />
            {/if}
            {#if p.views}<span class="tt-views"><Icon name="play" size={9} />{p.views}</span>{/if}
            {#if p.pinned}<span class="tt-pin">Pinned</span>{/if}
          </a>
          <div class="tt-meta">
            <p class="tt-cap">{p.caption || (p.photo ? "A photo post" : "No caption")}</p>
            {#if p.seen}
              <p class="tt-seen" title={p.said ? `What is said: "${p.said}"` : ""}><Icon name="eye" size={11} /><span>{p.seen}</span></p>
            {/if}
            {#if p.created}<span class="tt-when">{ago(p.created)}{p.id === info.newest ? " · newest" : ""}</span>{/if}
            <div class="tt-acts">
              <button type="button" class:is-on={done[p.id]?.liked} disabled={!!busy[p.id] || done[p.id]?.liked}
                      onclick={() => act(p, "like")} title="Like it" aria-label="Like it">
                <Icon name="heart" size={13} />{busy[p.id] === "like" ? "..." : done[p.id]?.liked ? "Liked" : "Like"}
              </button>
              <button type="button" class:is-on={done[p.id]?.saved} disabled={!!busy[p.id] || done[p.id]?.saved}
                      onclick={() => act(p, "save")} title="Save it to Favorites" aria-label="Save it">
                <Icon name="bookmark" size={13} />{busy[p.id] === "save" ? "..." : done[p.id]?.saved ? "Saved" : "Save"}
              </button>
              <button type="button" class:is-on={writing === p.id || done[p.id]?.commented} disabled={!!busy[p.id]}
                      onclick={() => openComment(p)} title="Comment on it" aria-label="Comment on it">
                <Icon name="chats" size={13} />{done[p.id]?.commented ? "Commented" : "Comment"}
              </button>
            </div>
            {#if writing === p.id}
              <div class="tt-write">
                <input type="text" maxlength="150" placeholder="A comment, in public" bind:value={draft}
                       onkeydown={(e) => { if (e.key === "Enter") comment(p); if (e.key === "Escape") openComment(p); }} />
                <button type="button" class="tt-ai" onclick={() => suggest(p)} disabled={drafting}
                        title="Let the persona write one" aria-label="Let the persona write one">
                  <Icon name="sparkle" size={13} />
                </button>
                <button type="button" class="tt-send" onclick={() => comment(p)} disabled={!draft.trim() || !!busy[p.id]}
                        title="Post the comment" aria-label="Post the comment">
                  <Icon name="send" size={13} />
                </button>
              </div>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .tt { display: flex; min-height: 0; flex: 1; flex-direction: column; gap: 10px; overflow-y: auto; padding: 12px; }
  .tt-who { display: flex; align-items: center; gap: 8px; }
  .tt-id { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 1px; }
  .tt-name { display: inline-flex; align-items: center; gap: 5px; font-size: 13.5px; font-weight: 700; color: var(--color-ink); }
  .tt-tick {
    display: inline-grid;
    width: 14px;
    height: 14px;
    place-items: center;
    border-radius: 50%;
    color: #fff;
    background: #20d5ec;
  }
  .tt-handle { font-size: 11.5px; color: #fe5c7c; font-weight: 600; }
  .tt-count { font-size: 11px; color: var(--color-faint); }
  .tt-look {
    display: grid;
    width: 30px;
    height: 30px;
    place-items: center;
    border-radius: 10px;
    color: var(--color-faint);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .tt-look:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
  .tt-look.is-busy :global(svg) { animation: tt-spin 0.9s linear infinite; }
  @keyframes tt-spin { to { transform: rotate(360deg); } }
  .tt-bio { margin: 0; font-size: 12px; line-height: 1.4; color: var(--color-muted); white-space: pre-line; }
  .tt-empty { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; margin: 8px 0; font-size: 12.5px; color: var(--color-faint); }
  .tt-now {
    padding: 6px 12px;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 600;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 20%, rgb(255 255 255 / 0.04));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 40%, transparent);
  }
  .tt-posts { display: flex; flex-direction: column; gap: 10px; margin: 0; padding: 0; list-style: none; }
  .tt-post {
    display: flex;
    gap: 10px;
    padding: 8px;
    border-radius: 14px;
    background: linear-gradient(160deg, rgb(255 255 255 / 0.05), rgb(255 255 255 / 0.02));
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06), 0 8px 18px -12px rgb(0 0 0 / 0.6);
    animation: tt-in 0.3s ease-out both;
    animation-delay: calc(var(--i) * 40ms);
  }
  @keyframes tt-in { from { opacity: 0; transform: translateY(4px); } }
  .tt-cover {
    position: relative;
    width: 72px;
    height: 96px;
    flex-shrink: 0;
    overflow: hidden;
    border-radius: 9px;
    background: linear-gradient(150deg, #25f4ee22, #fe2c5522), #111;
  }
  .tt-cover img { width: 100%; height: 100%; object-fit: cover; }
  .tt-views, .tt-pin {
    position: absolute;
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: 10px;
    font-weight: 700;
    color: #fff;
    text-shadow: 0 1px 3px rgb(0 0 0 / 0.8);
  }
  .tt-views { left: 5px; bottom: 4px; }
  .tt-pin { left: 4px; top: 4px; padding: 1px 5px; border-radius: 5px; background: #fe2c55; text-shadow: none; }
  .tt-meta { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 4px; }
  .tt-cap {
    display: -webkit-box;
    overflow: hidden;
    margin: 0;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    font-size: 12.5px;
    line-height: 1.35;
    color: var(--color-ink);
  }
  .tt-seen { display: flex; gap: 5px; margin: 0; font-size: 11px; line-height: 1.35; color: var(--color-muted); }
  .tt-seen :global(svg) { flex-shrink: 0; margin-top: 1px; color: #25f4ee; opacity: 0.8; }
  .tt-seen span {
    display: -webkit-box;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
    line-clamp: 3;
  }
  .tt-when { font-size: 10.5px; color: var(--color-faint); }
  .tt-acts { display: flex; flex-wrap: wrap; gap: 5px; margin-top: auto; }
  .tt-acts button {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    border-radius: 8px;
    font-size: 11px;
    font-weight: 600;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
    transition: color 0.15s ease, background-color 0.15s ease, box-shadow 0.2s ease;
  }
  .tt-acts button:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.09); }
  .tt-acts button.is-on {
    color: #fe5c7c;
    background: rgb(254 44 85 / 0.12);
    box-shadow: inset 0 0 0 1px rgb(254 44 85 / 0.3);
  }
  .tt-acts button:disabled:not(.is-on) { opacity: 0.55; }
  .tt-write { display: flex; gap: 5px; align-items: center; }
  .tt-write input {
    min-width: 0;
    flex: 1;
    padding: 6px 9px;
    border-radius: 9px;
    font-size: 12px;
    color: var(--color-ink);
    background: rgb(0 0 0 / 0.25);
    box-shadow: inset 0 0 0 1px var(--color-edge);
  }
  .tt-write input:focus { outline: none; box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, transparent); }
  .tt-ai, .tt-send {
    display: grid;
    width: 28px;
    height: 28px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 9px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.06);
  }
  .tt-send:not(:disabled) { color: #fff; background: #fe2c55; }
  .tt-ai:hover:not(:disabled) { color: var(--color-ink); }
  :global(:root[data-motion="off"]) .tt-post { animation: none; }
  :global(:root[data-motion="off"]) .tt-look.is-busy :global(svg) { animation: none; }
</style>
