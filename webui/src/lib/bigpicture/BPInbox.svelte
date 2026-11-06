<script lang="ts">
  /**
   * Needs you: what only a person can sort out, and the tab is only there while
   * something is. Who is asking to be friends, which account they asked, and when it
   * will take them by itself (the automatic accept is spread over hours on purpose,
   * so an account does not look like a script); and anything broken, each with the
   * page that fixes it, the same list that puts the dots in the sidebar.
   *
   * An accepted card lifts off in a shower of sparks, a declined one sinks away, and
   * the last one leaves "all caught up" behind.
   */
  import { flip } from "svelte/animate";
  import { backOut, cubicIn } from "svelte/easing";
  import { get } from "svelte/store";
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import { bigPictureExit, motionEnabled } from "../stores";
  import { play as uiPlay } from "../uisound";
  import { focusable } from "./focus";
  import { popIn } from "./motion";
  import { untilText } from "./scenes";
  import type { FriendReq, HealthIssue, PageActions } from "./types";
  import type { World } from "./world.svelte";

  let { world, act, issues = [], now = 0 }: { world: World; act: PageActions; issues?: HealthIssue[]; now?: number } = $props();

  const requests = $derived(world.friends);
  const shown = $derived(requests.slice(0, 6));
  const multi = $derived(new Set(requests.map((r) => r.target)).size > 1 || world.accounts.length > 1);
  const acct = (id: string) => world.accounts.find((a) => a.id === id);
  const cards: Record<string, HTMLElement | null> = {};

  const PAGE: Record<string, string> = {
    dashboard: "Dashboard", accounts: "Accounts", chats: "Chats", profiles: "Profiles", persona: "Persona", memory: "Memory",
    pictures: "Pictures", logs: "Logs", settings: "Settings", system: "System",
  };
  const ICON: Record<string, string> = { error: "alertCircle", warn: "alert", info: "info" };
  const RANK: Record<string, number> = { error: 0, warn: 1, info: 2 };
  const sorted = $derived(issues.slice().sort((a, b) => (RANK[a.level] ?? 3) - (RANK[b.level] ?? 3)));
  /** Counted the way the tab counts: an available update is a note, not a problem. */
  const serious = $derived(issues.filter((i) => i.level === "error" || i.level === "warn").length);
  const nothing = $derived(!requests.length && !serious);

  function answer(r: FriendReq, action: "accept" | "decline") {
    if (action === "decline") uiPlay("delete");
    world.answerFriend(r, action, cards[r.id] ?? null);
  }

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

<div class="bpi bp-scrolls">
  {#if nothing}
    <div class="bp-empty">
      <span class="bp-tick" in:popIn|global={{ delay: 80, from: 0.7 }}><Icon name="check" size={36} /></span>
      <b in:popIn|global={{ delay: 160, from: 0.94 }}>All caught up</b>
      <p in:popIn|global={{ delay: 220, from: 0.94 }}>Nothing needs you.</p>
    </div>
  {:else}
    {#if requests.length}
      <section class="bpi-part">
        <div class="bp-label">{requests.length === 1 ? "Someone wants to be friends" : `${requests.length} people want to be friends`}</div>
        <div class="bpi-cards">
          {#each shown as r, i (r.id)}
            {@const a = acct(r.target)}
            {@const who = r.display_name || r.username}
            <!-- The ones left glide into the gap an answered one leaves, rather than jumping. -->
            <article class="bp-panel bpi-card" bind:this={cards[r.id]} in:popIn|global={{ delay: 60 + i * 70, from: 0.92 }}
                     out:leave={{ how: world.friendGone[r.id] }} animate:flip={{ duration: 520, easing: backOut }}>
              <span class="bp-face">
                <Avatar src={r.avatar} name={who} size={64} zoom={false} />
                <i class="bpi-plus"><Icon name="plus" size={12} /></i>
              </span>
              <div class="bpi-who">
                <div class="bpi-name">{who}</div>
                {#if r.display_name && r.username}<div class="bpi-user selectable">@{r.username}</div>{/if}
                <div class="bpi-when">
                  {#if r.accept_at}
                    Taken by itself {untilText(r.accept_at, now)}
                  {:else}
                    Waiting on you
                  {/if}
                </div>
                {#if multi && a}
                  <div class="bpi-for">to <Avatar src={a.avatar} name={a.name} size={16} zoom={false} /><span>{a.name}</span></div>
                {/if}
              </div>
              <div class="bpi-do">
                <button class="bp-btn is-go" use:focusable={{ id: `yes:${r.id}`, first: i === 0 }} disabled={!!world.busy[r.id]}
                        onclick={() => answer(r, "accept")} title="Accept now, instead of on the timer">
                  <Icon name="check" size={14} />Accept
                </button>
                <button class="bp-btn" use:focusable={{ id: `no:${r.id}` }} disabled={!!world.busy[r.id]}
                        onclick={() => answer(r, "decline")} title="Decline it">
                  <Icon name="close" size={13} />Decline
                </button>
              </div>
            </article>
          {/each}
        </div>
        {#if requests.length > shown.length}
          <button class="bp-btn is-small bpi-more" use:focusable={{ id: "friends:more" }} onclick={() => act.leaveTo("chats")}>
            {requests.length - shown.length} more in Chats<Icon name="chevron" size={13} />
          </button>
        {/if}
      </section>
    {/if}

    {#if sorted.length}
      <section class="bpi-part">
        <div class="bp-label">{serious ? `${serious} to look at` : "Notes"}</div>
        <ul class="bpi-list">
          {#each sorted.slice(0, 6) as it, i (it.title + it.route)}
            <li class="bpi-item" data-level={it.level} in:popIn|global={{ delay: 100 + i * 60, from: 0.96 }}>
              <span class="bpi-icon"><Icon name={ICON[it.level] ?? "info"} size={20} /></span>
              <div class="bpi-text">
                <div class="bpi-title">{it.title}</div>
                {#if it.detail}<div class="bpi-detail">{it.detail}</div>{/if}
              </div>
              {#if PAGE[it.route]}
                <button class="bp-btn is-small" use:focusable={{ id: `fix:${it.title}` }} onclick={() => act.leaveTo(it.route)} title="Leave Big Picture and open {PAGE[it.route]}">
                  Open {PAGE[it.route]}<Icon name="chevron" size={13} />
                </button>
              {/if}
            </li>
          {/each}
        </ul>
      </section>
    {/if}
  {/if}
</div>

<style>
  .bpi { display: flex; height: 100%; min-height: 0; flex-direction: column; justify-content: safe center; gap: clamp(18px, 3vh, 40px); width: min(100%, 1320px); margin-inline: auto; padding-bottom: 2vh; }
  .bpi-part { display: flex; min-width: 0; flex-direction: column; gap: 10px; }
  .bpi-part > :global(.bp-label) { font-size: clamp(15px, 1.2vw, 22px); font-weight: 700; color: var(--color-ink); }
  .bpi-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr)); gap: 12px; }
  /* The buttons along the bottom, level from card to card whatever is written above them. */
  .bpi-card { position: relative; display: grid; grid-template-columns: auto minmax(0, 1fr); grid-template-rows: 1fr auto; align-items: center; gap: 10px 14px; padding: 16px; }
  .bpi-plus { position: absolute; right: -2px; bottom: -2px; display: grid; width: 24px; height: 24px; place-items: center; border-radius: 999px; color: var(--bp-on); background: var(--color-accent); }
  .bpi-who { display: flex; min-width: 0; flex-direction: column; gap: 1px; }
  .bpi-name { overflow: hidden; font-size: clamp(18px, 1.3vw, 23px); font-weight: 700; letter-spacing: -0.02em; text-overflow: ellipsis; white-space: nowrap; }
  .bpi-user { overflow: hidden; font-size: 13px; color: var(--bp-muted); text-overflow: ellipsis; white-space: nowrap; }
  .bpi-when { margin-top: 3px; font-size: 13px; font-weight: 600; color: var(--bp-lit); }
  .bpi-for { display: flex; min-width: 0; align-items: center; gap: 5px; margin-top: 2px; font-size: 12.5px; color: var(--bp-faint); }
  .bpi-for span { min-width: 0; overflow: hidden; color: var(--bp-muted); text-overflow: ellipsis; white-space: nowrap; }
  .bpi-do { grid-column: 1 / -1; align-self: end; display: flex; gap: 8px; }
  .bpi-do :global(.bp-btn) { flex: 1; }
  .bpi-more { align-self: flex-start; }

  .bpi-list { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
  .bpi-item { display: flex; min-width: 0; align-items: center; gap: 14px; padding: 12px 14px; border-radius: var(--bp-r); background: var(--bp-fill); }
  .bpi-icon { display: grid; width: 42px; height: 42px; flex-shrink: 0; place-items: center; border-radius: 14px; color: var(--bp-muted); background: var(--bp-fill); }
  .bpi-item[data-level="error"] .bpi-icon { color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 16%, transparent); }
  .bpi-item[data-level="warn"] .bpi-icon { color: var(--color-warn); background: color-mix(in srgb, var(--color-warn) 14%, transparent); }
  /* A note, not a problem: it sits back behind the ones that are. */
  .bpi-item[data-level="info"] { background: none; }
  .bpi-item[data-level="info"] .bpi-title { font-size: clamp(14px, 1vw, 17px); color: var(--bp-muted); }
  .bpi-text { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 2px; }
  .bpi-title { font-size: clamp(15px, 1.15vw, 20px); font-weight: 650; }
  .bpi-detail { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2; font-size: 13.5px; line-height: 1.42; color: var(--bp-muted); }
  /* A phone: the words get the width, and the button goes under them. */
  @media (max-width: 720px) {
    .bpi { height: auto; }
    .bpi-item { flex-wrap: wrap; }
    .bpi-text { flex: 1 1 220px; }
  }
</style>
