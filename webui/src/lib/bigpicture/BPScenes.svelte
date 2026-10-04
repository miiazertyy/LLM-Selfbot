<script lang="ts">
  /**
   * What the stage shows when nobody is waiting: the director cycles through
   * these every few seconds (see director.ts). Someone you talk to and what
   * about (BPMemory), recent conversations, today in big numbers, the people
   * talked to most this week, and the rest of the app, a scene each: the
   * accounts, the pictures, friend requests, the persona and anything broken.
   */
  import Avatar from "../components/Avatar.svelte";
  import RankBadge from "../components/RankBadge.svelte";
  import Counter from "./Counter.svelte";
  import BPMemory from "./BPMemory.svelte";
  import BPWave from "./BPWave.svelte";
  import BPAccounts from "./BPAccounts.svelte";
  import BPPictures from "./BPPictures.svelte";
  import BPFriends from "./BPFriends.svelte";
  import BPPersona from "./BPPersona.svelte";
  import BPHealth from "./BPHealth.svelte";
  import { popIn } from "./motion";
  import type { Scene } from "./director";
  import type { MemoryPerson, SceneActions, SceneWorld } from "./types";

  type Recent = { id: string; name: string; avatar?: string; messages: number; last_ts?: number };
  type Top = { user_id: string; username: string; count: number; avatar?: string };

  let {
    scene,
    recent = [],
    today = { replies: 0, people: 0, tokens: 0, requests: 0 },
    hourly = [],
    top = [],
    now = 0,
    memory = null,
    waiting = 0,
    hideText = false,
    world = null,
    act = {},
  }: {
    scene: Scene;
    recent?: Recent[];
    today?: { replies: number; people: number; tokens: number; requests: number };
    hourly?: number[];
    top?: Top[];
    now?: number;
    memory?: MemoryPerson | null;
    /** Older conversations still in the queue: then it is quiet, but not everyone has been answered. */
    waiting?: number;
    hideText?: boolean;
    world?: SceneWorld | null;
    act?: SceneActions;
  } = $props();

  function ago(ts?: number): string {
    if (!ts) return "";
    const s = Math.max(0, now - ts);
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    return `${Math.round(s / 86400)}d ago`;
  }
  // A scene with nothing to show gives way to "today", which always has something.
  // Friend requests and health keep their own scene when emptied: "all caught up"
  // is the point of having answered the last one.
  const shown = $derived<Scene>(
    (scene === "recent" && !recent.length) || (scene === "people" && !top.length) || (scene === "memory" && !memory)
      || (scene === "accounts" && !world?.accounts.length) || (scene === "pictures" && !world?.pictures.length)
      || (scene === "persona" && !world?.persona.lines.length) || ((scene === "friends" || scene === "health") && !world)
      ? "today"
      : scene,
  );
  const lull = $derived(
    // The scenes play while replies only wait, so "idle" would be untrue then.
    waiting ? `Between replies · ${waiting} waiting in the queue` : "Idle · everyone has been answered",
  );
</script>

<div class="bsc">
  {#if shown === "memory" && memory}
    <BPMemory person={memory} {now} {hideText} />
  {:else if shown === "accounts" && world}
    <BPAccounts accounts={world.accounts} activity={world.activity} dates={world.dates} {now}
                busy={world.busy} onpause={act.onpause} />
  {:else if shown === "pictures" && world}
    <BPPictures pictures={world.pictures} sent={world.sent} {now} blurred={world.picturesBlurred} {hideText}
                onreveal={act.onreveal} onhold={act.onhold} />
  {:else if shown === "friends" && world}
    <BPFriends requests={world.friends} accounts={world.accounts} {now} busy={world.busy}
               gone={world.friendGone} onanswer={act.onanswer} />
  {:else if shown === "persona" && world}
    <BPPersona lines={world.persona.lines} name={world.persona.name} face={world.persona.face}
               accounts={world.accounts} moods={world.moods} {hideText} busy={world.busy} onmood={act.onmood} />
  {:else if shown === "health" && world}
    <BPHealth issues={world.issues} onopen={act.onopen} />
  {:else if shown === "recent"}
    <div class="bsc-kicker">{lull}</div>
    <h2 class="bsc-title">Recent conversations</h2>
    <div class="bsc-grid">
      {#each recent.slice(0, 8) as c, i (c.id)}
        <div class="bsc-card" in:popIn|global={{ delay: 120 + i * 80 }}>
          <span class="halo"><Avatar src={c.avatar} name={c.name} size={56} zoom={false} /></span>
          <span class="min-w-0">
            <span class="bsc-name">{c.name}</span>
            <span class="bsc-sub">{c.messages} message{c.messages === 1 ? "" : "s"}{c.last_ts ? ` · ${ago(c.last_ts)}` : ""}</span>
          </span>
        </div>
      {/each}
    </div>
  {:else if shown === "today"}
    <div class="bsc-kicker">Idle · the day so far</div>
    <h2 class="bsc-title">Today</h2>
    <div class="bsc-nums">
      <div in:popIn|global={{ delay: 100 }}><b><Counter value={today.replies} /></b><span>replies</span></div>
      <div in:popIn|global={{ delay: 200 }}><b><Counter value={today.people} /></b><span>people this week</span></div>
      <div in:popIn|global={{ delay: 300 }}><b><Counter value={today.tokens} /></b><span>tokens</span></div>
    </div>
    <div class="bsc-wave" in:popIn|global={{ delay: 380, from: 0.95 }}>
      <BPWave values={hourly} height={150} label="Replies per hour, the last day" />
      <div class="bsc-wave-axis"><span>24h ago</span><span>now</span></div>
    </div>
  {:else}
    <div class="bsc-kicker">Idle · this week</div>
    <h2 class="bsc-title">Talked to most</h2>
    <div class="bsc-podium">
      {#each [1, 0, 2] as rank, i}
        {@const p = top[rank]}
        {#if p}
          <div class="bsc-place" data-rank={rank + 1} in:popIn|global={{ delay: 150 + i * 140 }}>
            <span class="halo"><Avatar src={p.avatar} name={p.username} size={rank === 0 ? 112 : 88} zoom={false} /></span>
            <span class="bsc-rank"><RankBadge n={rank + 1} size={rank === 0 ? 38 : 32} delay={450} quiet /></span>
            <span class="bsc-name">{p.username}</span>
            <span class="bsc-sub"><Counter value={p.count} /> messages</span>
          </div>
        {/if}
      {/each}
    </div>
    {#if top.length > 3}
      <div class="bsc-rest">
        {#each top.slice(3, 8) as p, i (p.user_id)}
          <span class="bsc-chip" in:popIn|global={{ delay: 600 + i * 70 }}>
            <Avatar src={p.avatar} name={p.username} size={22} zoom={false} /><span class="bsc-chip-name">{p.username}</span><b>{p.count}</b>
          </span>
        {/each}
      </div>
    {/if}
  {/if}
</div>

<style>
  /* A scene taller than the stage keeps its heading in view and is cut at the
     stage's foot, a little past it for the glows, rather than drawing over the
     chapters and the numbers below. Clip, not hidden: nothing here scrolls. */
  .bsc {
    display: flex;
    height: 100%;
    min-width: 0;
    flex-direction: column;
    justify-content: safe center;
    gap: 14px;
    padding: 10px 6px;
    overflow: clip;
    overflow-clip-margin: 32px;
  }
  @media (max-width: 720px) {
    .bsc { overflow: visible; }
  }
  .bsc-kicker { font-size: 12px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--bp-faint); }
  .bsc-title { margin-bottom: 14px; font-size: clamp(34px, 4.4vw, 64px); font-weight: 750; letter-spacing: -0.03em; color: #fff; }
  .bsc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
  .bsc-card {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px;
    border-radius: 22px;
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.07);
    backdrop-filter: blur(16px);
  }
  .bsc-name { display: block; overflow: hidden; font-size: 17px; font-weight: 650; color: #fff; text-overflow: ellipsis; white-space: nowrap; }
  .bsc-sub { display: block; font-size: 13px; color: var(--bp-muted); }
  .bsc-nums { display: flex; flex-wrap: wrap; gap: clamp(20px, 4vw, 64px); }
  .bsc-nums div { display: flex; flex-direction: column; }
  .bsc-nums b { font-size: clamp(56px, 7.5vw, 120px); font-weight: 800; line-height: 1; letter-spacing: -0.04em; color: #fff; }
  .bsc-nums span { margin-top: 6px; font-size: 15px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--bp-muted); }
  .bsc-wave { margin-top: 18px; }
  .bsc-wave-axis { display: flex; justify-content: space-between; margin-top: 6px; font-size: 11px; color: var(--bp-faint); }
  .bsc-podium { display: flex; min-width: 0; align-items: flex-end; justify-content: center; gap: clamp(16px, 4vw, 60px); }
  /* A third of the row each at most: a long name is cut short instead of pushing the podium out past both sides. */
  .bsc-place { position: relative; display: flex; min-width: 0; max-width: 30%; flex: 0 1 auto; flex-direction: column; align-items: center; gap: 6px; text-align: center; }
  .bsc-place .bsc-name { max-width: 100%; }
  .bsc-place[data-rank="1"] { transform: translateY(-26px); }
  /* Where the medal sits on the photo: its top right. */
  .bsc-rank {
    position: absolute;
    top: -6px;
    right: -6px;
    display: grid;
  }
  .bsc-rest { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-top: 18px; }
  .bsc-chip {
    display: inline-flex;
    min-width: 0;
    max-width: 100%;
    align-items: center;
    gap: 7px;
    padding: 5px 12px 5px 6px;
    border-radius: 999px;
    font-size: 13px;
    color: #fff;
    background: rgb(255 255 255 / 0.06);
  }
  .bsc-chip-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bsc-chip b { flex-shrink: 0; margin-left: 4px; color: var(--bp-muted); font-weight: 600; }
</style>
