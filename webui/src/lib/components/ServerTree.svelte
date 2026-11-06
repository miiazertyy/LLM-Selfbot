<script lang="ts">
  /**
   * The servers an account is in, to walk into and type in: the servers along the top, then that server's channels
   * under the category they sit in, as Discord itself arranges them.
   *
   * The Chats list only ever showed a server channel once someone had spoken to the account there. This is the rest
   * of them. Picking one opens it on the right like any other conversation: a channel's row id is "ch<id>", which
   * the history and send routes already understand.
   *
   * Under a voice channel, who is in it and whether they are muted, deafened or live. Only that: rows to read, not
   * to press. Discord's only, as nothing else here has voice channels.
   */
  import { slide } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { get } from "svelte/store";
  import { api } from "../api";
  import Avatar from "./Avatar.svelte";
  import Icon from "./Icon.svelte";
  import { motionEnabled } from "../stores";
  import { play } from "../uisound";
  import { fold, splitWords } from "../chatsearch";
  import { hscroll } from "../hscroll";
  import { visiblePoll } from "../poll";

  type Channel = { id: string; name: string; category: string; topic: string; nsfw: boolean;
                   voice: boolean; can_send: boolean; waiting: boolean };
  type Guild = { id: string; name: string; icon: string; members: number; channels: Channel[] };
  type Person = { id: string; name: string; avatar: string; muted: boolean; deaf: boolean; live: boolean; video: boolean };
  type Call = { count: number; people: Person[] };

  /** How often who is in the calls is asked again. Out of the gateway's own cache, so it costs Discord nothing. */
  const CALLS_EVERY = 6000;
  /** When the last answer was heard. Longer ago than a couple of asks, or none yet, and what it brings just appears:
   *  a big server has hundreds of lists, and all of them sliding open at once would crawl. */
  let heardAt = 0;
  let sliding = false;
  /** Over this many people in calls, a change just appears too: each slide makes the browser work out the whole list
   *  again, about 14 ms a person in a server with a thousand, every few seconds. */
  const SLIDE_UP_TO = 150;
  /** A slide, or nothing at all: slide() itself asks for the element's computed style, even for no time, and that is the cost. */
  function arrive(node: Element, ms: number) {
    return sliding && get(motionEnabled) ? slide(node, { duration: ms, easing: cubicOut }) : { duration: 0 };
  }

  let {
    target,
    open = "",
    query = "",
    waiting = new Set<string>(),
    word = "server",
    onpick,
  }: {
    target: string;
    /** The row open on the right ("ch<id>"), so the channel it belongs to is lit. */
    open?: string;
    /** The list's own search box, which narrows channels by name here. */
    query?: string;
    /** Channels someone is waiting in, from the list the page already has. */
    waiting?: Set<string>;
    /** What this platform calls one: Discord has servers, Telegram has groups. */
    word?: string;
    onpick: (channel: Channel, guild: Guild) => void;
  } = $props();

  let guilds = $state<Guild[]>([]);
  let loading = $state(true);
  let error = $state("");
  let pickedId = $state("");
  let shut = $state<Record<string, boolean>>({});   // categories folded away, per server
  /** Who is in each voice channel of the server in view, by channel id. */
  let calls = $state.raw<Record<string, Call>>({});
  let chansEl: HTMLElement | null = $state(null);

  const guild = $derived(guilds.find((g) => g.id === pickedId) ?? guilds[0]);
  const guildId = $derived(guild?.id ?? "");
  const words = $derived(splitWords(query).map(fold).filter(Boolean));

  /** That server's channels, narrowed by the list's search, grouped under their category in Discord's own order. */
  const groups = $derived.by(() => {
    // A key of its own: two categories can share a name, and a repeated key stops the whole list drawing.
    const out: { key: string; name: string; channels: Channel[] }[] = [];
    const seen = new Map<string, number>();
    for (const ch of guild?.channels ?? []) {
      if (words.length) {
        const hay = fold(`${ch.name} ${ch.topic} ${(calls[ch.id]?.people ?? []).map((p) => p.name).join(" ")}`);
        if (!words.every((w) => hay.includes(w))) continue;
      }
      const last = out[out.length - 1];
      if (last && last.name === ch.category) last.channels.push(ch);
      else {
        const again = seen.get(ch.category) ?? 0;
        seen.set(ch.category, again + 1);
        out.push({ key: `${ch.category}#${again}`, name: ch.category, channels: [ch] });
      }
    }
    return out;
  });

  const total = $derived(guild?.channels.length ?? 0);

  async function load() {
    loading = true;
    error = "";
    try {
      const r = await api.chatsServers(target);
      guilds = r.guilds ?? [];
      if (!guilds.some((g) => g.id === pickedId)) pickedId = guilds[0]?.id ?? "";
    } catch (e: any) {
      error = e?.message || "Could not read them";
      guilds = [];
    } finally {
      loading = false;
    }
  }

  // Each account has its own servers, so switching accounts starts again.
  let loadedFor = "";
  $effect(() => {
    const t = target;
    if (t && t !== loadedFor) {
      loadedFor = t;
      guilds = [];
      void load();
    }
  });

  // At once for the server in view, then every few seconds while this list is on screen. An answer for a server left
  // meanwhile is dropped; one that fails leaves what it knew, and the next is only a few seconds away.
  $effect(() => {
    const t = target;
    const g = guildId;
    calls = {};
    if (word !== "server" || !t || !g) return;
    let left = false;
    let asking = false;
    let looked = false;
    heardAt = 0;
    const read = async () => {
      // One at a time: a slow or stopped account would have them queuing up in its command file.
      if (asking || left) return;
      asking = true;
      try {
        const r = await api.chatsVoice(t, g, inView());
        if (left) return;
        const next = r.channels ?? {};
        sliding = performance.now() - heardAt < CALLS_EVERY * 2.5
          && Object.values(next).reduce((n, c) => n + c.people.length, 0) <= SLIDE_UP_TO;
        heardAt = performance.now();
        calls = next;
        // The first look's missing names are being asked for right now: look again in a moment, not a few seconds.
        if (!looked && Object.values(calls).some((c) => c.people.some((p) => !p.name))) setTimeout(read, 1500);
        looked = true;
      } catch {
      } finally {
        asking = false;
      }
    };
    void read();
    const stop = visiblePoll(read, CALLS_EVERY);
    return () => {
      left = true;
      stop();
    };
  });

  /** The calls on screen, so the names asked for first are the ones being looked at. */
  function inView(): string[] {
    if (!chansEl) return [];
    const box = chansEl.getBoundingClientRect();
    const out: string[] = [];
    for (const call of chansEl.querySelectorAll<HTMLElement>(".st-call")) {
      const r = call.getBoundingClientRect();
      if (r.top >= box.bottom) break;
      if (r.bottom > box.top && call.dataset.ch) out.push(call.dataset.ch);
    }
    return out.slice(0, 50);
  }

  function pickGuild(g: Guild) {
    if (g.id === pickedId) return;
    play("tap");
    pickedId = g.id;
  }

  function pickChannel(ch: Channel) {
    play("open");
    onpick(ch, guild!);
  }

  function fold_(name: string) {
    play("tap");
    shut = { ...shut, [`${pickedId}:${name}`]: !shut[`${pickedId}:${name}`] };
  }

  const isShut = (name: string) => !!shut[`${pickedId}:${name}`];
  /** Two letters off a server with no icon of its own, the way Discord stands in for one. */
  const initials = (name: string) =>
    name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => [...w][0]).join("").toUpperCase() || "?";
</script>

<div class="st">
  {#if loading}
    <div class="st-note"><span class="st-spin" aria-hidden="true"></span>Reading its {word}s…</div>
  {:else if error}
    <div class="st-note is-bad">
      <Icon name="alert" size={13} />{error}
      <button type="button" class="st-again" onclick={() => load()}>Try again</button>
    </div>
  {:else if !guilds.length}
    <div class="st-note">
      <Icon name="globe" size={13} />It is in no {word}s yet.
    </div>
  {:else}
    <!-- The servers: its icon, or its initials where it has none. -->
    <div class="hscroll st-rail-wrap">
    <div class="st-rail" role="tablist" aria-label={word === "group" ? "Groups" : "Servers"} use:hscroll>
      {#each guilds as g (g.id)}
        <button type="button" role="tab" aria-selected={g.id === guild?.id} class="st-server"
                class:is-on={g.id === guild?.id} title={g.name} onclick={() => pickGuild(g)}>
          {#if g.icon}
            <img src={g.icon} alt="" loading="lazy" />
          {:else}
            <span class="st-initials">{initials(g.name)}</span>
          {/if}
          {#if g.channels.some((c) => waiting.has(c.id) || c.waiting)}<span class="st-dot"></span>{/if}
        </button>
      {/each}
    </div>
    </div>

    {#if guild}
      <div class="st-head">
        <span class="st-name" title={guild.name}>{guild.name}</span>
        {#if guild.members}<span class="st-members">{guild.members.toLocaleString()}</span>{/if}
      </div>

      <div class="st-chans" bind:this={chansEl}>
        {#each groups as grp (grp.key)}
          {#if grp.name}
            <button type="button" class="st-cat" class:is-shut={isShut(grp.name)} onclick={() => fold_(grp.name)}
                    aria-expanded={!isShut(grp.name)}>
              <Icon name="chevron" size={10} />{grp.name}
            </button>
          {/if}
          {#if !grp.name || !isShut(grp.name)}
            {#each grp.channels as ch (ch.id)}
              <button type="button" class="st-chan" class:is-on={open === `ch${ch.id}`}
                      class:is-quiet={!ch.can_send} title={ch.topic || ch.name} onclick={() => pickChannel(ch)}>
                {#if word === "server"}<span class="st-hash">{ch.voice ? "♪" : "#"}</span>{/if}
                <span class="st-chan-name">{ch.name}</span>
                {#if waiting.has(ch.id) || ch.waiting}
                  <span class="st-waiting" title="Someone is waiting here"></span>
                {:else if !ch.can_send}
                  <span class="st-read" title="It can read this one, not type in it"><Icon name="eye" size={11} /></span>
                {/if}
              </button>
              {#if calls[ch.id]?.people.length}
                <ul class="st-call" data-ch={ch.id} style="contain-intrinsic-block-size: {(calls[ch.id].people.length + (calls[ch.id].count > calls[ch.id].people.length ? 1 : 0)) * 25 + 3}px"
                    transition:arrive={220}>
                  {#each calls[ch.id].people as p (p.id)}
                    <li class="st-person" transition:arrive={180}>
                      <Avatar src={p.avatar} name={p.name} size={20} ring="" zoom={false} lazy />
                      <span class="st-person-name" title={p.name}>{p.name || "Someone"}</span>
                      {#if p.live}<span class="st-live">Live</span>{/if}
                      {#if p.video}<span class="st-mark" title="Camera on"><Icon name="camera" size={12} /></span>{/if}
                      {#if p.muted}<span class="st-mark" title="Muted"><Icon name="micOff" size={12} /></span>{/if}
                      {#if p.deaf}<span class="st-mark" title="Deafened"><Icon name="headphonesOff" size={12} /></span>{/if}
                    </li>
                  {/each}
                  {#if calls[ch.id].count > calls[ch.id].people.length}
                    <li class="st-person is-more">and {(calls[ch.id].count - calls[ch.id].people.length).toLocaleString()} more</li>
                  {/if}
                </ul>
              {/if}
            {/each}
          {/if}
        {:else}
          <p class="st-none">{query ? "Nothing by that name." : "Nothing here it can read."}</p>
        {/each}
      </div>

      {#if words.length && total}
        <p class="st-count">{groups.reduce((n, g) => n + g.channels.length, 0)} of {total}</p>
      {/if}
    {/if}
  {/if}
</div>

<style>
  .st { display: flex; min-height: 0; flex: 1; flex-direction: column; gap: 8px; }

  /* ── The servers ──────────────────────────────────────────────────────── */
  .st-rail-wrap { flex: 0 0 auto; }
  .st-rail {
    display: flex; gap: 7px; overflow-x: auto; padding: 2px 2px 7px;
    scrollbar-width: none;
  }
  .st-rail::-webkit-scrollbar { display: none; }
  .st-server {
    position: relative; display: grid; flex: 0 0 auto; place-items: center;
    width: 38px; height: 38px; overflow: hidden; border-radius: 13px;
    background: rgb(255 255 255 / 0.05); color: var(--color-muted); font-size: 12.5px; font-weight: 650;
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.07), 0 6px 14px -10px rgb(0 0 0 / 0.9);
    transition: border-radius 0.28s var(--jelly), transform 0.2s var(--jelly), box-shadow 0.24s ease;
  }
  .st-server img { width: 100%; height: 100%; object-fit: cover; }
  .st-server:hover { transform: translateY(-1px); border-radius: 11px; }
  .st-server.is-on {
    color: var(--color-ink); border-radius: 11px;
    box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--color-accent) 85%, transparent),
                0 10px 20px -12px color-mix(in srgb, var(--color-accent) 70%, transparent);
  }
  .st-initials { letter-spacing: 0.02em; }
  .st-dot {
    position: absolute; right: 3px; bottom: 3px; width: 7px; height: 7px; border-radius: 50%;
    background: var(--color-accent); box-shadow: 0 0 0 2px var(--color-sunk, #0e0d12);
  }

  /* ── Which server, and how big ────────────────────────────────────────── */
  .st-head { display: flex; align-items: baseline; gap: 7px; padding: 0 3px; }
  .st-name {
    min-width: 0; overflow: hidden; font-size: 12.5px; font-weight: 650; color: var(--color-ink);
    text-overflow: ellipsis; white-space: nowrap;
  }
  .st-members { margin-left: auto; font-size: 10.5px; color: var(--color-faint); }

  /* ── Its channels ─────────────────────────────────────────────────────── */
  .st-chans { display: flex; min-height: 0; flex: 1; flex-direction: column; gap: 1px; overflow-y: auto; padding-bottom: 6px; }
  .st-cat {
    display: flex; align-items: center; gap: 4px; margin-top: 8px; padding: 3px 4px;
    font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
    color: var(--color-faint); transition: color 0.15s ease;
  }
  .st-cat:hover { color: var(--color-muted); }
  .st-cat :global(svg) { transform: rotate(90deg); transition: transform 0.24s var(--jelly); }
  .st-cat.is-shut :global(svg) { transform: none; }
  .st-chan {
    position: relative; display: flex; align-items: center; gap: 6px;
    border-radius: 9px; padding: 5px 8px; font-size: 12.5px; color: var(--color-muted);
    transition: background-color 0.16s ease, color 0.16s ease;
  }
  .st-chan:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.05); }
  .st-chan.is-on {
    color: var(--color-ink); background: color-mix(in srgb, var(--color-accent) 16%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 30%, transparent);
  }
  .st-chan.is-quiet { opacity: 0.62; }
  .st-hash { width: 11px; text-align: center; font-size: 13px; color: var(--color-faint); }
  .st-chan.is-on .st-hash { color: var(--color-accent); }
  .st-chan-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .st-waiting {
    margin-left: auto; width: 7px; height: 7px; flex: 0 0 auto; border-radius: 50%;
    background: var(--color-accent); box-shadow: 0 0 8px color-mix(in srgb, var(--color-accent) 70%, transparent);
  }
  .st-read { margin-left: auto; display: flex; color: var(--color-faint); }

  /* ── Who is in a call: under its channel, lined up with the channel's name ── */
  /* Off screen it isn't laid out or drawn, at the size it says it will be: a big server has hundreds of these. */
  .st-call { display: flex; flex: 0 0 auto; flex-direction: column; gap: 1px; padding: 1px 0 3px 25px; content-visibility: auto; }
  .st-person { display: flex; min-width: 0; align-items: center; gap: 6px; min-height: 24px; padding-right: 8px; font-size: 11.5px; color: var(--color-muted); }
  .st-person.is-more { color: var(--color-faint); }
  .st-person-name { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .st-mark { display: flex; flex: 0 0 auto; color: var(--color-faint); }
  .st-live {
    flex: 0 0 auto; padding: 1px 5px; border-radius: 6px; font-size: 9px; font-weight: 750; letter-spacing: 0.04em;
    text-transform: uppercase; color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 16%, transparent);
  }

  /* ── While it reads, and when there is nothing ────────────────────────── */
  .st-note {
    display: flex; align-items: center; gap: 7px; padding: 14px 6px; font-size: 12px; color: var(--color-muted);
  }
  .st-note.is-bad { color: var(--color-warn); }
  .st-again { margin-left: auto; font-size: 11.5px; color: var(--color-accent); text-decoration: underline; }
  .st-spin {
    width: 12px; height: 12px; border-radius: 50%; border: 2px solid rgb(255 255 255 / 0.18);
    border-top-color: var(--color-accent); animation: st-turn 0.7s linear infinite;
  }
  @keyframes st-turn { to { transform: rotate(360deg); } }
  .st-none, .st-count { padding: 10px 6px; font-size: 11.5px; color: var(--color-faint); }
  .st-count { padding: 0 6px 4px; }
  :global(:root[data-motion="off"]) .st-spin { animation-duration: 2s; }
  :global(:root[data-motion="off"]) .st-server,
  :global(:root[data-motion="off"]) .st-chan,
  :global(:root[data-motion="off"]) .st-cat :global(svg) { transition: none; }
</style>
