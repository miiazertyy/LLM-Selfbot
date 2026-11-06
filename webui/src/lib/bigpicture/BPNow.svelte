<script lang="ts">
  /**
   * Now: the page that plays by itself. The queue down the left, the conversation
   * on stage in the middle, the model and what just happened on the right.
   *
   * With nobody on stage the rails slide out of the way and the room has the
   * screen, with a big clock in it and a line saying how things stand. The queue's
   * rail comes back the moment there is someone in it, and the right one with a
   * conversation, or with someone come here on purpose. They keep their width as
   * their column folds, so they slide away under the edge instead of squeezing.
   */
  import Odometer from "../components/Odometer.svelte";
  import Icon from "../components/Icon.svelte";
  import { fmtDate, HOUR_MINUTE } from "../fmt";
  import type { ConvMessage } from "../chats";
  import type { ModelUsage } from "../modelusage";
  import type { Plan } from "../providers";
  import type { Thought } from "../thoughts";
  import BPQueue from "./BPQueue.svelte";
  import BPRail from "./BPRail.svelte";
  import BPStage from "./BPStage.svelte";
  import { focusable } from "./focus";
  import { liftOut, popIn, riseIn } from "./motion";
  import { ago, untilText } from "./scenes";
  import type { PageActions, QRow, Spot } from "./types";
  import type { World } from "./world.svelte";

  let {
    world,
    act,
    spot = null,
    messages = [],
    answering = [],
    next = [],
    waiting = [],
    multi = false,
    now = 0,
    driving = false,
    thought = null,
    otherThought = null,
    busy = false,
    replying = {},
    writing = false,
    plan = null,
    models = [],
    composer = $bindable(null),
    onpick,
    onreply,
    onearlier,
    onstagereply,
    oncancel,
    onignore,
    onsend,
    onmodel,
  }: {
    world: World;
    act: PageActions;
    spot?: Spot | null;
    messages?: ConvMessage[];
    answering?: QRow[];
    next?: QRow[];
    waiting?: QRow[];
    multi?: boolean;
    now?: number;
    /** Someone is using it, not only watching. */
    driving?: boolean;
    thought?: Thought | null;
    otherThought?: Thought | null;
    busy?: boolean;
    replying?: Record<string, boolean>;
    writing?: boolean;
    plan?: Plan | null;
    models?: ModelUsage[];
    composer?: HTMLInputElement | null;
    onpick?: (key: string) => void;
    onreply?: (r: QRow) => void;
    onearlier?: () => void;
    onstagereply?: () => void;
    oncancel?: () => void;
    onignore?: () => void;
    onsend?: (text: string) => void;
    onmodel?: () => void;
  } = $props();

  const inQueue = $derived(answering.length + next.length + waiting.length);
  const brain = $derived((spot && world.byConv[spot.u.id]) || world.active);
  const forName = $derived(spot && world.byConv[spot.u.id] ? spot.u.name : "");

  // The clock: its figures roll over on their wheels. "08:23 AM" comes apart into the figures and the rest.
  const clock = $derived(fmtDate(now * 1000, HOUR_MINUTE));
  const figures = $derived(clock.replace(/[^\d:.]/g, "").trim());
  const period = $derived(clock.replace(/[\d:.]/g, "").trim());
  const date = $derived(fmtDate(now * 1000, { weekday: "long", day: "numeric", month: "long" }));

  /** How things stand, in a line. */
  const standing = $derived.by(() => {
    if (!world.accounts.some((a) => a.state === "running")) return world.accounts.length ? "Nothing is running" : "No accounts yet";
    const soonest = next.map((r) => r.st.eta ?? 0).filter(Boolean).sort((a, b) => a - b)[0];
    if (next.length) return `${next.length} up next${soonest ? `, the first ${untilText(soonest, now)}` : ""}`;
    if (waiting.length) return `${waiting.length} waiting on you`;
    return "Everyone's answered";
  });
  const last = $derived(world.lastReply);
</script>

<div class="bpw" class:no-queue={!inQueue} class:no-rail={!spot && !driving}>
  <aside class="bpw-left" aria-hidden={!inQueue}>
    <div class="bpw-keep"><BPQueue {answering} {next} {waiting} spotlight={spot?.key ?? null} {multi} {now} {replying} {onpick} {onreply} /></div>
  </aside>
  <section class="bpw-mid">
    {#key spot?.key ?? "quiet"}
      <div class="bpw-layer" in:riseIn out:liftOut>
        {#if spot}
          <BPStage {spot} {messages} {now} {multi} {thought} {busy} replying={!!replying[spot.u.id]}
                   bind:composer {onearlier} onreply={onstagereply} {oncancel} {onignore} {onsend} />
        {:else}
          <div class="bpw-quiet">
            <div class="bpw-clock" in:popIn|global={{ delay: 60, from: 0.96 }}>
              <span class="bpw-figures"><Odometer value={figures} /></span>{#if period}<span class="bpw-period">{period}</span>{/if}
            </div>
            <div class="bpw-date" in:popIn|global={{ delay: 130, from: 0.96 }}>{date}</div>
            <div class="bpw-standing" in:popIn|global={{ delay: 210, from: 0.96 }}>{standing}</div>
            {#if last}
              <button class="bp-btn bpw-last" use:focusable={{ id: "now:last", first: true }} in:popIn|global={{ delay: 290, from: 0.96 }}
                      onclick={() => act.open(last.target, last.id, { name: last.name })}>
                <Icon name="reply" size={15} /><span data-private="soft">Last reply to {last.name}, {ago(last.ts, now)}</span>
              </button>
            {:else if !world.accounts.length}
              <button class="bp-btn bpw-last" use:focusable={{ id: "now:accounts", first: true }} in:popIn|global={{ delay: 290, from: 0.96 }}
                      onclick={() => act.leaveTo("accounts")}>
                <Icon name="plus" size={15} />Add an account
              </button>
            {/if}
          </div>
        {/if}
      </div>
    {/key}
  </section>
  <aside class="bpw-right" aria-hidden={!spot && !driving}>
    <div class="bpw-keep">
      <BPRail active={brain} {forName} {writing} pulse={world.answered} helper={world.helper} {plan} {models}
              feed={world.feed} logs={world.logs} thought={otherThought} {now} {onmodel} onopen={act.open} />
    </div>
  </aside>
</div>

<style>
  .bpw {
    --q: clamp(250px, 19.5vw, 380px);
    --r: clamp(260px, 20vw, 400px);
    --ql: var(--q);
    --rl: var(--r);
    display: grid;
    height: 100%;
    min-height: 0;
    grid-template-columns: var(--ql) minmax(0, 1fr) var(--rl);
    gap: clamp(16px, 2vw, 40px);
    transition: grid-template-columns 0.85s var(--swift);
  }
  .bpw.no-queue { --ql: 0px; }
  .bpw.no-rail { --rl: 0px; }
  .bpw-left, .bpw-right { min-width: 0; min-height: 0; overflow: hidden; transition: opacity 0.45s ease; }
  /* The rail's own width, whatever its column is doing: it slides, it does not squeeze. */
  .bpw-left .bpw-keep { width: var(--q); height: 100%; }
  .bpw-right .bpw-keep { width: var(--r); height: 100%; }
  .bpw.no-queue .bpw-left, .bpw.no-rail .bpw-right { opacity: 0; pointer-events: none; }
  .bpw-mid { display: grid; min-width: 0; min-height: 0; grid-template: minmax(0, 1fr) / minmax(0, 1fr); }
  /* The leaving and the arriving share the one cell, so one lifts off the other. */
  .bpw-layer { grid-area: 1 / 1; min-width: 0; min-height: 0; will-change: transform, opacity; }

  /* Nobody on stage: the room, with the time in it. */
  .bpw-quiet { display: flex; height: 100%; flex-direction: column; align-items: center; justify-content: center; gap: 4px; padding-bottom: 5vh; text-align: center; }
  .bpw-clock { display: flex; align-items: baseline; justify-content: center; gap: 0.12em; font-size: clamp(84px, min(15vw, 28vh), 280px); font-weight: 500; line-height: 1; letter-spacing: -0.045em; }
  .bpw-figures { display: inline-flex; }
  .bpw-period { font-size: 0.2em; font-weight: 600; letter-spacing: 0; color: var(--bp-muted); }
  .bpw-date { font-size: clamp(18px, 1.7vw, 32px); font-weight: 600; color: var(--bp-muted); }
  .bpw-standing { margin-top: clamp(12px, 2vh, 26px); font-size: clamp(16px, 1.25vw, 24px); font-weight: 600; }
  .bpw-last { margin-top: 12px; font-weight: 600; color: var(--bp-muted); }
  .bpw-last:hover { color: var(--color-ink); }

  /* Narrower: the queue and the stage; the model and the list give way. */
  @media (max-width: 1100px) {
    .bpw { --q: clamp(220px, 30vw, 320px); grid-template-columns: var(--ql) minmax(0, 1fr); }
    .bpw-right { display: none; }
  }
  /* A phone, or the app shrunk to its pocket size: one column, stage first. */
  @media (max-width: 720px) {
    .bpw { height: auto; grid-template-columns: minmax(0, 1fr); gap: 18px; }
    .bpw-mid { order: -1; min-height: 62vh; }
    .bpw-left .bpw-keep { width: auto; height: auto; }
    .bpw.no-queue .bpw-left { display: none; }
  }
  :global(:root[data-motion="off"]) .bpw { transition: none; }
</style>
