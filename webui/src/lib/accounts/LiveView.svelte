<script lang="ts">
  /**
   * A TikTok account's LIVE, while the persona co-hosts it: what viewers say
   * (comments, gifts, follows, joins) as it comes, and what the persona
   * answered, out loud and in the chat (app/platforms/snapchat_bridge.py,
   * _live_event). Its voice can play here, or on the OBS page, which shows the
   * answers as captions and plays them, for a stream to pick up.
   *
   * And out on TikTok: someone else's LIVE it is in as a viewer (its chat, and
   * what the persona says there), one to go to now, a few minutes of For You,
   * and what it has liked, commented and visited today.
   */
  import { onMount } from "svelte";
  import { fly } from "svelte/transition";
  import { api } from "../api";
  import { visiblePoll } from "../poll";
  import { copyText } from "../contextmenu";
  import { motionEnabled } from "../stores";
  import { play } from "../uisound";
  import Icon from "../components/Icon.svelte";
  import Toggle from "../components/Toggle.svelte";
  import { toast } from "../stores";

  let { account, name = "", onsettings }: { account: string; name?: string; onsettings?: () => void } = $props();

  type Line = { t: string; event?: string; name?: string; to?: string; text?: string; audio?: string[]; id?: string;
                at: number };
  let live = $state(false);
  let feed = $state<Line[]>([]);
  let loaded = $state(false);
  // Someone else's LIVE it is visiting as a viewer (tiktok.visits), and what it has done out there today.
  type Visit = { on: boolean; host: string; name: string; why: string; since: number; feed: Line[] };
  let visit = $state<Visit | null>(null);
  type Out = { busy: string; visiting: string; used: Record<string, number>; left: Record<string, number> };
  let out = $state<Out | null>(null);
  let goTo = $state("");
  let going = $state(false);
  let speakHere = $state(false);
  try {
    speakHere = localStorage.getItem("liveSpeakHere") === "1";
  } catch {
    // private window: off
  }
  const played = new Set<string>();
  const queue: string[] = [];
  let playing = false;

  function playNext() {
    if (playing || !queue.length) return;
    playing = true;
    const audio = new Audio(api.liveAudio(account, queue.shift()!));
    const done = () => { playing = false; playNext(); };
    audio.onended = done;
    audio.onerror = done;
    audio.play().catch(done);
  }

  async function refresh() {
    try {
      const r: any = await api.liveFeed(account);
      const was = feed.length;
      const wasLive = live;
      live = !!r?.live;
      feed = Array.isArray(r?.feed) ? r.feed : [];
      if (loaded && live !== wasLive) play(live ? "glint" : "off", { level: 0.6 });
      if (loaded && feed.length > was) {
        const fresh = feed.slice(was);
        if (fresh.some((l) => l.t === "live_say")) play("receive", { level: 0.5 });
        else play("tick", { level: 0.25 });
      }
      const v: Visit | null = r?.visit && typeof r.visit === "object" ? r.visit : null;
      const wasOn = !!visit?.on;
      const seen = visit?.feed?.length ?? 0;
      visit = v;
      if (loaded && !!v?.on !== wasOn) play(v?.on ? "rise" : "off", { level: 0.5 });
      else if (loaded && v?.on && v.feed.length > seen) {
        play(v.feed.slice(seen).some((l) => l.t === "visit_say") ? "receive" : "tick", { level: v.feed.slice(seen).some((l) => l.t === "visit_say") ? 0.5 : 0.2 });
      }
      for (const l of feed) {
        if (l.t !== "live_say" || !l.id || played.has(l.id)) continue;
        played.add(l.id);
        // Only what is said from now on: opening the view does not replay the last few answers.
        if (loaded && speakHere) queue.push(...(l.audio || []));
      }
      playNext();
      loaded = true;
    } catch {
      loaded = true;
    }
  }

  // A first look now: visiblePoll's first comes a whole period later.
  onMount(() => {
    lookOut();
    refresh();
    return visiblePoll(refresh, 2500);
  });

  /** What it is doing out there and what is left of today's: asked of the account itself, now and after each ask. */
  function lookOut() {
    api.tiktokOut(account).then((r: Out) => (out = r)).catch(() => (out = null));
  }

  async function visitNow() {
    const handle = goTo.trim().replace(/^@/, "");
    if (!handle || going) return;
    going = true;
    play("send");
    try {
      await api.tiktokVisit(account, handle);
      goTo = "";
      toast(`Going to @${handle}'s LIVE.`, "ok");
      refresh();
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      going = false;
      lookOut();
    }
  }

  async function leaveNow() {
    play("off");
    try {
      await api.tiktokLeave(account);
      toast("Leaving the LIVE.", "info");
    } catch (e) {
      toast((e as Error).message, "err");
    }
    lookOut();
  }

  async function forYouNow() {
    if (going) return;
    going = true;
    play("tap");
    try {
      await api.tiktokForYou(account);
      toast("Scrolling For You for a few minutes.", "ok");
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      going = false;
      lookOut();
    }
  }

  const today = $derived(out ? [["likes", "like"], ["comments", "comment"], ["visits", "visit"]]
    .map(([k, one]) => `${out!.used[k] ?? 0} ${(out!.used[k] ?? 0) === 1 ? one : k}`).join(", ") : "");

  function setSpeakHere(v: boolean) {
    speakHere = v;
    try { localStorage.setItem("liveSpeakHere", v ? "1" : "0"); } catch { /* this visit only */ }
  }

  const overlay = $derived(`${location.origin}/?live=${encodeURIComponent(account)}`);
  const ICONS: Record<string, string> = { comment: "chats", gift: "sparkle", follow: "userPlus", join: "accounts", share: "external" };
  const dur = $derived($motionEnabled ? 1 : 0);
</script>

<div class="lv">
  <div class="lv-head">
    <span class="lv-state" class:is-live={live}><span class="lv-dot" aria-hidden="true"></span>{live ? "Live now" : "Not live"}</span>
    <span class="text-[12px] text-muted">{live ? `${name || "It"} is co-hosting.` : "It starts co-hosting when the account goes live."}</span>
  </div>

  <div class="lv-feed" aria-live="polite">
    {#if !feed.length}
      <p class="lv-empty">{loaded ? "Nothing yet. Viewers' comments and its answers show here." : "Looking…"}</p>
    {/if}
    {#each feed.slice(-40) as l, i (`${l.at}-${i}`)}
      {#if l.t === "live_say"}
        <div class="lv-say" in:fly={{ y: 8, duration: 260 * dur }}>
          <span class="lv-say-to">{l.to ? `To ${l.to}` : "To everyone"}</span>
          <span class="lv-say-text">{l.text}</span>
          {#if l.audio?.length}<span class="lv-say-voice" title="Said out loud"><Icon name="speaker" size={12} /></span>{/if}
        </div>
      {:else if l.t === "live"}
        <div class="lv-line" in:fly={{ y: 6, duration: 200 * dur }}>
          <span class="lv-ic"><Icon name={ICONS[l.event || ""] || "chats"} size={12} /></span>
          <b>{l.name}</b>
          <span class="min-w-0 truncate text-muted">{l.event === "comment" ? l.text : l.event === "gift" ? `sent ${l.text}` : l.event === "follow" ? "followed" : l.event === "join" ? "joined" : l.text}</span>
        </div>
      {/if}
    {/each}
  </div>

  <!-- Out on TikTok: someone else's LIVE it is in as a viewer, or one to go to now, and For You. -->
  <section class="lv-out" class:is-on={visit?.on}>
    <div class="lv-out-head">
      <span class="lv-visit"><Icon name="external" size={12} />{visit?.on ? `In @${visit.host}'s LIVE` : "Out on TikTok"}</span>
      {#if visit?.on}
        <button class="lv-copy" onclick={leaveNow}><Icon name="signout" size={13} />Leave</button>
      {/if}
    </div>
    {#if visit?.on}
      <div class="lv-feed lv-feed-out" aria-live="polite">
        {#if !visit.feed.length}<p class="lv-empty">Watching. Its chat shows here.</p>{/if}
        {#each visit.feed.slice(-30) as l, i (`${l.at}-${i}`)}
          {#if l.t === "visit_say"}
            <div class="lv-say lv-say-out" in:fly={{ y: 8, duration: 260 * dur }}>
              <span class="lv-say-to">{l.to ? `To ${l.to}` : "It said"}</span>
              <span class="lv-say-text">{l.text}</span>
            </div>
          {:else}
            <div class="lv-line" in:fly={{ y: 6, duration: 200 * dur }}>
              <span class="lv-ic"><Icon name={ICONS[l.event || ""] || "chats"} size={12} /></span>
              <b>{l.name}</b>
              <span class="min-w-0 truncate text-muted">{l.event === "comment" ? l.text : l.event === "gift" ? `sent ${l.text}` : l.event === "join" ? "joined" : l.text}</span>
            </div>
          {/if}
        {/each}
      </div>
    {:else}
      <div class="lv-go">
        <input type="text" placeholder="@username" bind:value={goTo} aria-label="Whose LIVE to visit"
               onkeydown={(e) => { if (e.key === "Enter") visitNow(); }} />
        <button class="lv-copy" onclick={visitNow} disabled={!goTo.trim() || going}><Icon name="external" size={13} />Visit</button>
        <button class="lv-copy" onclick={forYouNow} disabled={going} title="A few minutes on For You, now"><Icon name="play" size={12} />For You</button>
      </div>
    {/if}
    {#if today}
      <p class="lv-today">Today: {today}{out?.busy ? ` · now ${out.busy}` : ""}</p>
    {/if}
  </section>

  <label class="lv-row">
    <Toggle size="sm" checked={speakHere} name="Play the voice here" onchange={setSpeakHere} />
    <span>Play the voice here <span class="text-faint">(not needed with the OBS page)</span></span>
  </label>

  <div class="lv-obs">
    <div class="min-w-0">
      <div class="text-[12.5px] font-semibold text-ink">For OBS</div>
      <div class="text-[11.5px] text-muted">Add this as a Browser source. It shows each answer and says it.</div>
    </div>
    <button class="lv-copy" onclick={() => { play("select"); copyText(overlay, "Copied the OBS link."); }}>
      <Icon name="copy" size={13} />Copy link
    </button>
  </div>
  {#if onsettings}
    <button class="lv-settings" onclick={onsettings}><Icon name="settings" size={13} />LIVE settings</button>
  {/if}
</div>

<style>
  .lv { display: flex; flex-direction: column; gap: 12px; }
  .lv-head { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
  .lv-state {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 4px 11px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
  }
  .lv-dot { width: 8px; height: 8px; border-radius: 999px; background: var(--color-faint); }
  .lv-state.is-live { color: #fff; background: linear-gradient(180deg, #ff3b5c, #e0153d); box-shadow: 0 8px 20px -8px rgb(254 44 85 / 0.8); }
  .lv-state.is-live .lv-dot { background: #fff; animation: lv-beat 1.2s ease-in-out infinite; }
  @keyframes lv-beat { 50% { transform: scale(0.55); opacity: 0.6; } }
  .lv-feed {
    display: flex;
    max-height: 340px;
    min-height: 160px;
    flex-direction: column;
    gap: 6px;
    overflow-y: auto;
    padding: 10px;
    border-radius: 14px;
    background: color-mix(in srgb, var(--color-bg) 55%, transparent);
    box-shadow: inset 0 0 0 1px var(--color-edge);
  }
  .lv-empty { margin: auto; font-size: 12px; color: var(--color-faint); }
  .lv-line { display: flex; min-width: 0; align-items: center; gap: 7px; font-size: 12.5px; color: var(--color-ink); }
  .lv-line b { flex-shrink: 0; font-weight: 650; }
  .lv-ic { display: grid; flex-shrink: 0; color: var(--color-faint); }
  .lv-say {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin: 2px 0 2px 18px;
    padding: 8px 12px;
    border-radius: 14px 14px 14px 4px;
    background: linear-gradient(135deg, color-mix(in srgb, var(--color-accent) 22%, transparent),
                color-mix(in srgb, var(--color-accent) 8%, transparent));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 30%, transparent);
  }
  .lv-say-to { font-size: 10.5px; font-weight: 700; letter-spacing: 0.04em; color: var(--color-accent); }
  .lv-say-text { font-size: 13px; color: var(--color-ink); }
  .lv-say-voice { position: absolute; right: 9px; top: 7px; color: var(--color-accent); }
  .lv-row { display: flex; align-items: center; gap: 10px; font-size: 12.5px; color: var(--color-ink); }
  .lv-obs {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px;
    border-radius: 14px;
    background: rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px var(--color-edge);
  }
  .lv-copy, .lv-settings {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 6px;
    margin-left: auto;
    padding: 7px 12px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 600;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.06);
  }
  .lv-copy:hover, .lv-settings:hover { background: rgb(255 255 255 / 0.1); }
  .lv-settings { align-self: flex-start; margin-left: 0; color: var(--color-muted); }
  .lv-copy:disabled { opacity: 0.5; }
  .lv-out {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px;
    border-radius: 14px;
    background: rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    transition: box-shadow 0.3s ease, background-color 0.3s ease;
  }
  .lv-out.is-on {
    background: linear-gradient(160deg, rgb(37 244 238 / 0.07), rgb(255 255 255 / 0.02));
    box-shadow: inset 0 0 0 1px rgb(37 244 238 / 0.28), 0 10px 26px -18px rgb(37 244 238 / 0.8);
  }
  .lv-out-head { display: flex; align-items: center; gap: 10px; }
  .lv-visit { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 700; color: var(--color-ink); }
  .lv-out.is-on .lv-visit { color: #c9fbff; }
  .lv-feed-out { max-height: 240px; min-height: 110px; }
  .lv-say-out { background: linear-gradient(135deg, rgb(37 244 238 / 0.18), rgb(37 244 238 / 0.06));
                box-shadow: inset 0 0 0 1px rgb(37 244 238 / 0.3); }
  .lv-say-out .lv-say-to { color: #25f4ee; }
  .lv-go { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .lv-go input {
    min-width: 0;
    flex: 1 1 140px;
    padding: 7px 11px;
    border-radius: 10px;
    font-size: 12.5px;
    color: var(--color-ink);
    background: rgb(0 0 0 / 0.25);
    box-shadow: inset 0 0 0 1px var(--color-edge);
  }
  .lv-go input:focus { outline: none; box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, transparent); }
  .lv-go .lv-copy { margin-left: 0; }
  .lv-today { margin: 0; font-size: 11.5px; color: var(--color-faint); }
  :global(:root[data-motion="off"]) .lv-out { transition: none; }
  :global(:root[data-motion="off"]) .lv-state.is-live .lv-dot { animation: none; }
</style>
