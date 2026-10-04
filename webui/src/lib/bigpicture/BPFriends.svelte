<script lang="ts">
  /**
   * The idle scene for friend requests waiting on the accounts: who is asking,
   * which account they asked, and when it will take them by itself (the
   * automatic accept is spread over hours on purpose, so an account does not
   * look like a script). Accept or Decline takes one now, the way the Chats tab
   * does. An accepted card lifts off in a shower of sparks, a declined one
   * sinks away, and the last one leaves "all caught up" behind.
   */
  import { flip } from "svelte/animate";
  import { backOut, cubicIn } from "svelte/easing";
  import { get } from "svelte/store";
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import { bigPictureExit, motionEnabled } from "../stores";
  import { popIn } from "./motion";
  import { ripple } from "./fx";
  import { untilText } from "./scenes";
  import type { BPAccount, FriendReq } from "./types";

  let {
    requests = [],
    accounts = [],
    now = 0,
    busy = {},
    gone = {},
    onanswer,
  }: {
    requests?: FriendReq[];
    accounts?: BPAccount[];
    now?: number;
    /** Requests with an answer on its way, by id. */
    busy?: Record<string, boolean>;
    /** How each answered one went, so it leaves the right way. */
    gone?: Record<string, "accept" | "decline">;
    onanswer?: (r: FriendReq, action: "accept" | "decline", el: HTMLElement | null) => void;
  } = $props();

  const multi = $derived(new Set(requests.map((r) => r.target)).size > 1 || accounts.length > 1);
  const shown = $derived(requests.slice(0, 6));
  const acct = (id: string) => accounts.find((a) => a.id === id);
  const cards: Record<string, HTMLElement | null> = {};

  /** Accepted: up and away, a little bigger, like it was lifted. Declined: down and gone. */
  function leave(_node: Element, { how }: { how?: "accept" | "decline" }) {
    if (bigPictureExit.on) return { duration: 0 };
    if (!get(motionEnabled)) return { duration: 160, css: (t: number) => `opacity:${t}` };
    if (how === "accept") {
      return {
        duration: 620,
        easing: backOut,
        css: (t: number, u: number) => `transform: translate3d(0, ${-70 * u}px, 0) scale(${1 + 0.12 * u}); opacity: ${t}`,
      };
    }
    return {
      duration: 380,
      easing: cubicIn,
      css: (t: number, u: number) => `transform: translate3d(0, ${40 * u}px, 0) scale(${1 - 0.08 * u}); opacity: ${t}`,
    };
  }
</script>

<div class="bpfr">
  <div class="bp-kicker" in:popIn|global={{ delay: 40, from: 0.96 }}>
    Friend requests · {requests.length ? `${requests.length} waiting` : "none waiting"}
  </div>
  <h2 class="bp-title" in:popIn|global={{ delay: 90, from: 0.96 }}>
    {requests.length === 1 ? "Someone wants to be friends" : requests.length ? "They want to be friends" : "All caught up"}
  </h2>

  {#if shown.length}
    <div class="bpfr-grid">
      {#each shown as r, i (r.id)}
        {@const a = acct(r.target)}
        {@const who = r.display_name || r.username}
        <!-- The ones left glide into the gap an answered one leaves, rather than jumping. -->
        <article class="bpfr-card" bind:this={cards[r.id]} in:popIn|global={{ delay: 160 + i * 110, from: 0.88 }}
                 out:leave={{ how: gone[r.id] }} animate:flip={{ duration: 520, easing: backOut }}>
          <span class="bpfr-face">
            <Avatar src={r.avatar} name={who} size={76} zoom={false} />
            <i class="bpfr-plus"><Icon name="plus" size={13} /></i>
          </span>
          <div class="bpfr-who">
            <div class="bpfr-name">{who}</div>
            {#if r.display_name && r.username}<div class="bpfr-user selectable">@{r.username}</div>{/if}
            <div class="bpfr-when">
              {#if r.accept_at}
                <Icon name="check" size={12} />Taken by itself {untilText(r.accept_at, now)}
              {:else}
                Waiting on you
              {/if}
            </div>
            {#if multi && a}
              <div class="bpfr-for">to <Avatar src={a.avatar} name={a.name} size={16} zoom={false} /><span>{a.name}</span></div>
            {/if}
          </div>
          {#if onanswer}
            <div class="bpfr-do">
              <button class="bpfr-btn is-yes" use:ripple={"rgb(255 255 255 / 0.5)"} disabled={!!busy[r.id]}
                      onclick={() => onanswer?.(r, "accept", cards[r.id] ?? null)} title="Accept now, instead of on the timer">
                <Icon name="check" size={14} />Accept
              </button>
              <button class="bpfr-btn" use:ripple disabled={!!busy[r.id]}
                      onclick={() => onanswer?.(r, "decline", cards[r.id] ?? null)} title="Decline it">
                <Icon name="close" size={13} />Decline
              </button>
            </div>
          {/if}
        </article>
      {/each}
    </div>
    {#if requests.length > shown.length}
      <div class="bpfr-more">and {requests.length - shown.length} more in Chats</div>
    {/if}
  {:else}
    <div class="bpfr-done" in:popIn|global={{ delay: 120, from: 0.8 }}>
      <span class="bpfr-check"><Icon name="check" size={38} /></span>
      <p>Nobody else is waiting to be friends.</p>
    </div>
  {/if}
</div>

<style>
  .bpfr { display: flex; height: 100%; min-width: 0; flex-direction: column; justify-content: safe center; gap: 12px; padding: 10px 6px; }
  .bpfr-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 330px), 1fr)); gap: 14px; }
  /* The buttons along the bottom, level from card to card whatever is written above them. */
  .bpfr-card {
    position: relative;
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    grid-template-rows: 1fr auto;
    align-items: center;
    gap: 8px 16px;
    padding: 18px;
    border-radius: 26px;
    /* A flat fill, no backdrop blur: on the dark room they look the same, and a
       blur per card is what makes a scene stutter as it arrives (see BPStage). */
    background: rgb(255 255 255 / 0.055);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08), 0 30px 70px -40px rgb(0 0 0 / 0.9);
  }
  .bpfr-face {
    position: relative;
    display: grid;
    border-radius: 999px;
    box-shadow: 0 0 0 4px rgb(10 11 18), 0 0 0 6px color-mix(in srgb, var(--color-accent) 55%, transparent);
    animation: bpfr-glow 3s ease-in-out infinite;
  }
  @keyframes bpfr-glow { 50% { box-shadow: 0 0 0 4px rgb(10 11 18), 0 0 0 6px color-mix(in srgb, var(--color-accent) 55%, transparent), 0 0 44px color-mix(in srgb, var(--color-accent) 36%, transparent); } }
  .bpfr-plus {
    position: absolute;
    right: -2px;
    bottom: -2px;
    display: grid;
    width: 26px;
    height: 26px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-bg);
    background: var(--color-accent);
    box-shadow: 0 0 0 3px rgb(10 11 18);
  }
  .bpfr-who { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
  .bpfr-name { overflow: hidden; font-size: 21px; font-weight: 750; letter-spacing: -0.02em; color: #fff; text-overflow: ellipsis; white-space: nowrap; }
  .bpfr-user { overflow: hidden; font-size: 13px; color: var(--bp-muted); text-overflow: ellipsis; white-space: nowrap; }
  .bpfr-when { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; gap: 5px; margin-top: 4px; font-size: 12.5px; color: var(--bp-faint); }
  .bpfr-for { display: flex; min-width: 0; align-items: center; gap: 5px; font-size: 12px; color: var(--bp-faint); }
  .bpfr-for span { min-width: 0; overflow: hidden; color: var(--bp-muted); text-overflow: ellipsis; white-space: nowrap; }
  .bpfr-do { grid-column: 1 / -1; align-self: end; display: flex; gap: 8px; margin-top: 6px; }
  .bpfr-btn {
    position: relative;
    display: inline-flex;
    flex: 1;
    align-items: center;
    justify-content: center;
    gap: 7px;
    height: 42px;
    overflow: hidden;
    border-radius: 999px;
    font-size: 14px;
    font-weight: 650;
    color: #fff;
    background: rgb(255 255 255 / 0.08);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.1);
    transition: transform 0.25s var(--spring), background-color 0.2s ease, box-shadow 0.25s ease;
  }
  .bpfr-btn:hover:not(:disabled) { transform: translateY(-1px); background: rgb(255 255 255 / 0.14); }
  .bpfr-btn:active:not(:disabled) { transform: scale(0.95); }
  .bpfr-btn:disabled { opacity: 0.45; }
  .bpfr-btn.is-yes {
    color: var(--color-bg);
    background: var(--color-accent);
    box-shadow: 0 12px 30px -12px color-mix(in srgb, var(--color-accent) 70%, transparent);
  }
  .bpfr-btn.is-yes:hover:not(:disabled) { background: color-mix(in srgb, var(--color-accent) 85%, white); }
  .bpfr-more { font-size: 13px; color: var(--bp-faint); text-align: center; }
  .bpfr-done { display: flex; flex-direction: column; align-items: center; gap: 14px; padding: 20px; text-align: center; }
  .bpfr-check {
    display: grid;
    width: 86px;
    height: 86px;
    place-items: center;
    border-radius: 999px;
    color: #fff;
    background: var(--color-good);
    box-shadow: 0 0 0 10px color-mix(in srgb, var(--color-good) 18%, transparent), 0 0 70px color-mix(in srgb, var(--color-good) 40%, transparent);
  }
  .bpfr-done p { font-size: 17px; color: var(--bp-muted); }
  :global(:root[data-motion="off"]) .bpfr-face { animation: none; }
</style>
