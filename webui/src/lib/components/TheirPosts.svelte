<script lang="ts">
  /**
   * Their stories and posts, beside an Instagram conversation: who they are on
   * Instagram and what they put up, as the account last read their profile
   * (when they write, every few hours), with what the persona saw in the ones
   * it watched. Their story can be watched or answered from here, and each post
   * liked, saved or commented on, as the account: your own choice, whatever the
   * automatic switches in Settings say.
   */
  import Icon from "./Icon.svelte";
  import { api } from "../api";
  import { play } from "../uisound";
  import { toast } from "../stores";

  let { target, uid, them }: { target: string; uid: string; them: { name: string; avatar?: string } } = $props();

  type Post = {
    id: string; url: string; caption: string; kind: string; pinned: boolean; cover: string;
    seen: string; said: string; likes: number; created: number;
  };
  type Story = { at: number; seen: string; url: string };
  type Theirs = {
    username: string; name: string; bio: string; followers: number | null; verified: boolean; private: boolean;
    posts: Post[]; posts_at: number; newest: string; story: Story | null;
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
  // Whether they have a story up right now, asked of the runner; null until it has answered.
  let storyUp = $state<boolean | null>(null);
  let storyBusy = $state("");
  let storyDraft = $state("");
  let storyOpen = $state(false);

  // Each conversation's own: what one asked for is never shown for another (it captures its own keys).
  function load(t: string, u: string, sound: boolean) {
    api.instagramTheirs(t, u)
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
    storyUp = null;
    storyOpen = false;
    load(t, u, true);
    // Whether there is a story up is a question for Instagram, so it is asked once a conversation is opened.
    api.instagramStories(t, u)
      .then((r: any) => { if (t === target && u === uid) storyUp = !!r?.story; })
      .catch(() => { if (t === target && u === uid) storyUp = false; });
  });

  async function lookNow() {
    if (looking) return;
    looking = true;
    play("tap");
    const t = target, u = uid;
    try {
      const r: Theirs = await api.instagramTheirsRefresh(t, u);
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

  async function story(action: "watch" | "reply") {
    if (storyBusy) return;
    const text = action === "reply" ? storyDraft.trim() : "";
    if (action === "reply" && !text) return;
    storyBusy = action;
    play(action === "reply" ? "send" : "tap");
    try {
      const r: any = await api.instagramStory(target, uid, action, text);
      if (action === "reply") {
        storyOpen = false;
        storyDraft = "";
      }
      toast(r?.dry ? "Dry run: nothing was sent." : action === "reply" ? "Answered their story." : "Watched their story.",
            r?.dry ? "info" : "ok");
      load(target, uid, false);
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      storyBusy = "";
    }
  }

  async function act(p: Post, action: "like" | "save") {
    if (busy[p.id]) return;
    busy[p.id] = action;
    play("tap");
    try {
      const r = await api.instagramAction(target, p.url, action);
      done[p.id] = { ...done[p.id], [action === "like" ? "liked" : "saved"]: true };
      play(action === "like" ? "pluck" : "seat");
      if (r.dry) toast("Dry run: nothing was pressed on Instagram.", "info");
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
      const r = await api.instagramCommentText(target, p.url);
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
      const r = await api.instagramAction(target, p.url, "comment", text);
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

<div class="ig">
  <header class="ig-who">
    <div class="ig-id">
      <span class="ig-name">{info?.name || them.name}{#if info?.verified}<span class="ig-tick" title="Verified"><Icon name="check" size={9} /></span>{/if}</span>
      {#if info?.username}<span class="ig-handle">@{info.username}</span>{/if}
      <span class="ig-counts">
        {#if info?.followers != null}<span>{followers(info.followers)} followers</span>{/if}
        {#if info?.private}<span class="ig-private"><Icon name="eyeOff" size={10} />private</span>{/if}
      </span>
    </div>
    <button type="button" class="ig-look" class:is-busy={looking} onclick={lookNow} disabled={looking}
            title="Look at their profile now" aria-label="Look at their profile now">
      <Icon name="refresh" size={13} />
    </button>
  </header>
  {#if info?.bio}<p class="ig-bio">{info.bio}</p>{/if}

  <!-- Their story: whether one is up, what the persona saw in the last one it watched, and a word back. -->
  <section class="ig-story" class:is-up={storyUp === true}>
    <div class="ig-story-head">
      <span class="ig-ring" class:is-up={storyUp === true} aria-hidden="true"></span>
      <span class="ig-story-what">
        {storyUp === null ? "Looking for a story…" : storyUp ? "They have a story up" : "No story up right now"}
      </span>
      {#if storyUp}
        <button type="button" class="ig-story-go" onclick={() => story("watch")} disabled={!!storyBusy}>
          <Icon name="eye" size={12} />{storyBusy === "watch" ? "Watching…" : "Watch it"}
        </button>
        <button type="button" class="ig-story-go" onclick={() => { storyOpen = !storyOpen; play(storyOpen ? "off" : "open"); }}
                disabled={!!storyBusy}>
          <Icon name="reply" size={12} />Answer
        </button>
      {/if}
    </div>
    {#if info?.story?.seen}
      <p class="ig-seen"><Icon name="eye" size={11} /><span>{info.story.seen}</span></p>
    {/if}
    {#if storyOpen}
      <div class="ig-write">
        <input type="text" maxlength="300" placeholder="A word about their story" bind:value={storyDraft}
               onkeydown={(e) => { if (e.key === "Enter") story("reply"); if (e.key === "Escape") (storyOpen = false); }} />
        <button type="button" class="ig-send" onclick={() => story("reply")}
                disabled={!storyDraft.trim() || !!storyBusy} title="Send it" aria-label="Send it">
          <Icon name="send" size={13} />
        </button>
      </div>
    {/if}
  </section>

  {#if failed}
    <p class="ig-empty">{failed}</p>
  {:else if !info}
    <p class="ig-empty">Loading...</p>
  {:else if !info.posts.length}
    <div class="ig-empty">
      <span>{info.private ? "Their account is private."
             : info.posts_at ? "No posts on their profile." : "Their posts are read when they write."}</span>
      <button type="button" class="ig-now" onclick={lookNow} disabled={looking}>{looking ? "Looking..." : "Look now"}</button>
    </div>
  {:else}
    <ul class="ig-posts">
      {#each info.posts as p, i (p.id)}
        <li class="ig-post" style="--i: {i}">
          <a class="ig-cover" class:is-reel={p.kind === "reel"} href={p.url} target="_blank" rel="noopener noreferrer"
             title="Open it on Instagram">
            {#if p.cover && !badCover[p.id]}
              <img src={p.cover} alt="" loading="lazy" referrerpolicy="no-referrer" onerror={() => (badCover[p.id] = true)} />
            {/if}
            {#if p.kind === "reel"}<span class="ig-reel"><Icon name="play" size={9} />Reel</span>{/if}
            {#if p.pinned}<span class="ig-pin">Pinned</span>{/if}
          </a>
          <div class="ig-meta">
            <p class="ig-cap">{p.caption || (p.kind === "reel" ? "A reel" : "No caption")}</p>
            {#if p.seen}
              <p class="ig-seen" title={p.said ? `What is said: "${p.said}"` : ""}><Icon name="eye" size={11} /><span>{p.seen}</span></p>
            {/if}
            {#if p.created}<span class="ig-when">{ago(p.created)}{p.url === info.newest ? " · newest" : ""}</span>{/if}
            <div class="ig-acts">
              <button type="button" class:is-on={done[p.id]?.liked} disabled={!!busy[p.id] || done[p.id]?.liked}
                      onclick={() => act(p, "like")} title="Like it" aria-label="Like it">
                <Icon name="heart" size={13} />{busy[p.id] === "like" ? "..." : done[p.id]?.liked ? "Liked" : "Like"}
              </button>
              <button type="button" class:is-on={done[p.id]?.saved} disabled={!!busy[p.id] || done[p.id]?.saved}
                      onclick={() => act(p, "save")} title="Save it" aria-label="Save it">
                <Icon name="bookmark" size={13} />{busy[p.id] === "save" ? "..." : done[p.id]?.saved ? "Saved" : "Save"}
              </button>
              <button type="button" class:is-on={writing === p.id || done[p.id]?.commented} disabled={!!busy[p.id]}
                      onclick={() => openComment(p)} title="Comment on it" aria-label="Comment on it">
                <Icon name="chats" size={13} />{done[p.id]?.commented ? "Commented" : "Comment"}
              </button>
            </div>
            {#if writing === p.id}
              <div class="ig-write">
                <input type="text" maxlength="150" placeholder="A comment, in public" bind:value={draft}
                       onkeydown={(e) => { if (e.key === "Enter") comment(p); if (e.key === "Escape") openComment(p); }} />
                <button type="button" class="ig-ai" onclick={() => suggest(p)} disabled={drafting}
                        title="Let the persona write one" aria-label="Let the persona write one">
                  <Icon name="sparkle" size={13} />
                </button>
                <button type="button" class="ig-send" onclick={() => comment(p)} disabled={!draft.trim() || !!busy[p.id]}
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
  .ig { display: flex; min-height: 0; flex: 1; flex-direction: column; gap: 10px; overflow-y: auto; padding: 12px; }
  .ig-who { display: flex; align-items: center; gap: 8px; }
  .ig-id { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 1px; }
  .ig-name { display: inline-flex; align-items: center; gap: 5px; font-size: 13.5px; font-weight: 700; color: var(--color-ink); }
  .ig-tick {
    display: inline-grid;
    width: 14px;
    height: 14px;
    place-items: center;
    border-radius: 50%;
    color: #fff;
    background: #3897f0;
  }
  .ig-handle { font-size: 11.5px; color: #f06292; font-weight: 600; }
  .ig-counts { display: flex; gap: 8px; font-size: 11px; color: var(--color-faint); }
  .ig-private { display: inline-flex; align-items: center; gap: 3px; }
  .ig-look {
    display: grid;
    width: 30px;
    height: 30px;
    place-items: center;
    border-radius: 10px;
    color: var(--color-faint);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .ig-look:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
  .ig-look.is-busy :global(svg) { animation: ig-spin 0.9s linear infinite; }
  @keyframes ig-spin { to { transform: rotate(360deg); } }
  .ig-bio { margin: 0; font-size: 12px; line-height: 1.4; color: var(--color-muted); white-space: pre-line; }

  .ig-story {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 8px 9px;
    border-radius: 12px;
    background: rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.05);
  }
  .ig-story.is-up { box-shadow: inset 0 0 0 1px rgb(225 48 108 / 0.3); }
  .ig-story-head { display: flex; align-items: center; gap: 7px; }
  /* The ring Instagram draws round someone with a story up, in its own gradient. */
  .ig-ring {
    width: 15px;
    height: 15px;
    flex-shrink: 0;
    border-radius: 50%;
    background: rgb(255 255 255 / 0.1);
  }
  .ig-ring.is-up {
    background: conic-gradient(from 200deg, #feda75, #fa7e1e, #d62976, #962fbf, #4f5bd5, #feda75);
    box-shadow: inset 0 0 0 2.5px var(--color-panel, #15131a);
  }
  .ig-story-what { min-width: 0; flex: 1; font-size: 12px; color: var(--color-muted); }
  .ig-story-go {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    border-radius: 8px;
    font-size: 11px;
    font-weight: 600;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .ig-story-go:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.09); }
  .ig-story-go:disabled { opacity: 0.55; }

  .ig-empty { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; margin: 8px 0; font-size: 12.5px; color: var(--color-faint); }
  .ig-now {
    padding: 6px 12px;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 600;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 20%, rgb(255 255 255 / 0.04));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 40%, transparent);
  }
  .ig-posts { display: flex; flex-direction: column; gap: 10px; margin: 0; padding: 0; list-style: none; }
  .ig-post {
    display: flex;
    gap: 10px;
    padding: 8px;
    border-radius: 14px;
    background: linear-gradient(160deg, rgb(255 255 255 / 0.05), rgb(255 255 255 / 0.02));
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06), 0 8px 18px -12px rgb(0 0 0 / 0.6);
    animation: ig-in 0.3s ease-out both;
    animation-delay: calc(var(--i) * 40ms);
  }
  @keyframes ig-in { from { opacity: 0; transform: translateY(4px); } }
  .ig-cover {
    position: relative;
    width: 82px;
    height: 82px;
    flex-shrink: 0;
    overflow: hidden;
    border-radius: 9px;
    background: linear-gradient(150deg, #feda7522, #d6297622, #4f5bd522), #121014;
  }
  /* A reel is tall where a post is square, as Instagram's own grid shows them. */
  .ig-cover.is-reel { width: 68px; height: 96px; }
  .ig-cover img { width: 100%; height: 100%; object-fit: cover; }
  .ig-reel, .ig-pin {
    position: absolute;
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: 10px;
    font-weight: 700;
    color: #fff;
    text-shadow: 0 1px 3px rgb(0 0 0 / 0.8);
  }
  .ig-reel { left: 5px; bottom: 4px; }
  .ig-pin { left: 4px; top: 4px; padding: 1px 5px; border-radius: 5px; background: #e1306c; text-shadow: none; }
  .ig-meta { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 4px; }
  .ig-cap {
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
  .ig-seen { display: flex; gap: 5px; margin: 0; font-size: 11px; line-height: 1.35; color: var(--color-muted); }
  .ig-seen :global(svg) { flex-shrink: 0; margin-top: 1px; color: #fa7e1e; opacity: 0.85; }
  .ig-seen span {
    display: -webkit-box;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
    line-clamp: 3;
  }
  .ig-when { font-size: 10.5px; color: var(--color-faint); }
  .ig-acts { display: flex; flex-wrap: wrap; gap: 5px; margin-top: auto; }
  .ig-acts button {
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
  .ig-acts button:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.09); }
  .ig-acts button.is-on {
    color: #f06292;
    background: rgb(225 48 108 / 0.12);
    box-shadow: inset 0 0 0 1px rgb(225 48 108 / 0.3);
  }
  .ig-acts button:disabled:not(.is-on) { opacity: 0.55; }
  .ig-write { display: flex; gap: 5px; align-items: center; }
  .ig-write input {
    min-width: 0;
    flex: 1;
    padding: 6px 9px;
    border-radius: 9px;
    font-size: 12px;
    color: var(--color-ink);
    background: rgb(0 0 0 / 0.25);
    box-shadow: inset 0 0 0 1px var(--color-edge);
  }
  .ig-write input:focus { outline: none; box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, transparent); }
  .ig-ai, .ig-send {
    display: grid;
    width: 28px;
    height: 28px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 9px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.06);
  }
  .ig-send:not(:disabled) { color: #fff; background: #e1306c; }
  .ig-ai:hover:not(:disabled) { color: var(--color-ink); }
  :global(:root[data-motion="off"]) .ig-post { animation: none; }
  :global(:root[data-motion="off"]) .ig-look.is-busy :global(svg) { animation: none; }
</style>
