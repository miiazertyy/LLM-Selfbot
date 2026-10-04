<script lang="ts">
  /**
   * The centre of Big Picture: the conversation in the spotlight, big.
   *
   * Their picture in a ring that counts down to the reply, who they are and
   * where, the tracker from Received to Sent, and the conversation itself in
   * large bubbles. New messages pop in; while the model writes or the reply is
   * typed out, dots bounce where it will appear; when it has gone, a check.
   * A change of spotlight pulls the next one up from below (motion.ts), and the
   * avatar flies in from its card in the queue, and back to it when it leaves,
   * under the key it arrived with (flightKey).
   */
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import MessageBody from "../components/MessageBody.svelte";
  import { FULL_WHEN, fmtDate, whenSent } from "../fmt";
  import { STEPS, progress, type Status } from "../chatstatus";
  import { convKey, typingNow, type ChatAccount, type ChatUser, type ConvMessage } from "../chats";
  import type { Scene } from "./director";
  import BPScenes from "./BPScenes.svelte";
  import { fitText } from "./fit";
  import { sparkOnMount } from "./fx";
  import { flightKey, liftOut, popIn, receiveAvatar, riseIn, sendFace } from "./motion";
  import type { MemoryPerson, SceneActions, SceneWorld } from "./types";

  type Spot = { key: string; target: string; u: ChatUser; st: Status; account?: ChatAccount; answered: boolean };

  let {
    spot = null,
    messages = [],
    onearlier,
    now = 0,
    hideText = false,
    multi = false,
    scene = null,
    sceneKey = 0,
    sceneData,
    onreply,
    oncancel,
    onignore,
    onsend,
    busy = false,
    replying = false,
  }: {
    spot?: Spot | null;
    messages?: ConvMessage[];
    /** Scrolled to the top: read further back. */
    onearlier?: () => void;
    now?: number;
    hideText?: boolean;
    multi?: boolean;
    scene?: Scene | null;
    sceneKey?: number;
    sceneData: {
      recent: any[];
      today: { replies: number; people: number; tokens: number; requests: number };
      hourly: number[];
      top: any[];
      memory?: MemoryPerson | null;
      /** How many are in the queue while the stage is idle: old ones nobody is answering. */
      waiting?: number;
      /** The rest of the app, for its scenes: accounts, pictures, requests, persona, health. */
      world?: SceneWorld | null;
      act?: SceneActions;
    };
    /** Answer them now, skipping the wait. */
    onreply?: () => void;
    /** Drop the reply that is lined up. */
    oncancel?: () => void;
    /** Stop answering them at all. */
    onignore?: () => void;
    /** Send this text as the account. */
    onsend?: (text: string) => void;
    busy?: boolean;
    replying?: boolean;
  } = $props();

  const layerKey = $derived(spot ? `spot:${spot.key}` : `scene:${sceneKey}`);
  /** On the tracker: 0 received ... 5 sent. */
  const stage = $derived(spot ? (spot.answered ? 5 : spot.st.phase === "live" ? spot.st.step ?? 0 : 0) : 0);
  const typing = $derived(!!spot && !spot.answered && spot.st.phase === "live" && (spot.st.step === 2 || spot.st.step === 4));
  /** They are typing to it right now (lib/chats.ts typingNow): their dots, as the bot has its own. */
  const theyType = $derived(!!spot && !!$typingNow[convKey(spot.target, String(spot.u.id))]);
  const ring = $derived(spot ? (spot.answered ? 1 : spot.st.step === 1 || spot.st.step === 3 ? progress(spot.st, now) : spot.st.step ? 1 : 0) : 0);

  /**
   * The conversation, both sides, as far back as it has been read (it used to
   * be the last five, with no way to see the rest); the row's own last
   * message when the history has not been read yet.
   */
  const shown = $derived.by<ConvMessage[]>(() => {
    if (!spot) return [];
    if (messages.length) return messages.slice(-100);
    const u = spot.u;
    return [{ mine: false, ts: u.ts ?? now, mid: u.mid, text: u.text || u.snippet || "",
              attachments: u.attachments, stickers: u.stickers, embeds: u.embeds }];
  });
  const where = $derived.by(() => {
    if (!spot) return "";
    if (spot.u.kind === "server") return spot.u.where ?? "A server";
    const acct = spot.account?.display_name || spot.account?.username;
    return multi && acct ? `Direct message · to ${acct}` : "Direct message";
  });
  const C = 2 * Math.PI * 78;

  // ── Scrolling back ───────────────────────────────────────────────────────
  // It starts at the newest message and follows new ones as they come, until
  // you scroll up; then it leaves you where you are (earlier messages arriving
  // above keep what you were reading in place) and offers a way back down.
  let msgsEl: HTMLElement | null = $state(null);
  let stick = $state(true);
  let above = $state(false);
  let beforeH = 0;
  let beforeTop = 0;
  let firstId = "";
  const idOf = (m?: ConvMessage) => (m ? m.mid ?? `${m.ts}` : "");
  function onMsgsScroll() {
    const el = msgsEl;
    if (!el) return;
    stick = el.scrollTop + el.clientHeight > el.scrollHeight - 60;
    above = el.scrollTop > 4;
    if (el.scrollTop < 80) onearlier?.();
  }
  function toNewest(smooth = true) {
    const el = msgsEl;
    if (!el) return;
    stick = true;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }
  $effect.pre(() => {
    void shown;
    if (msgsEl) {
      beforeH = msgsEl.scrollHeight;
      beforeTop = msgsEl.scrollTop;
    }
  });
  $effect(() => {
    const list = shown;
    const el = msgsEl;
    if (!el) return;
    const first = idOf(list[0]);
    if (firstId && first !== firstId && !stick) {
      el.scrollTop = beforeTop + (el.scrollHeight - beforeH);
    } else if (stick) {
      el.scrollTop = el.scrollHeight;
    }
    firstId = first;
    above = el.scrollTop > 4;
  });
  // Someone new on stage: start at their newest message.
  $effect(() => {
    void spot?.key;
    stick = true;
    firstId = "";
    queueMicrotask(() => {
      if (msgsEl) msgsEl.scrollTop = msgsEl.scrollHeight;
    });
  });

  /** What is being written to them from here, kept per person. */
  let drafts = $state<Record<string, string>>({});
  const key = $derived(spot?.key ?? "");
  let draft = $state("");
  $effect(() => {
    // Switching conversation swaps the draft, so a half-written line is not lost
    // when the director moves on and comes back.
    const k = key;
    draft = drafts[k] ?? "";
  });
  $effect(() => {
    const k = key;
    if (k) drafts[k] = draft;
  });
  function say() {
    const text = draft.trim();
    if (!text) return;
    draft = "";
    onsend?.(text);
  }
</script>

<div class="bps">
  {#key layerKey}
    <div class="bps-layer" in:riseIn out:liftOut>
      {#if spot}
        <div class="bps-hero">
          <div class="bps-halo" data-tone={spot.answered ? "good" : spot.st.tone} data-step={spot.answered ? 5 : spot.st.step ?? 0}>
            <svg class="bps-ring" viewBox="0 0 170 170" aria-hidden="true">
              <circle cx="85" cy="85" r="78" class="track" />
              <circle cx="85" cy="85" r="78" class="fill" style="stroke-dasharray: {C}; stroke-dashoffset: {C * (1 - ring)}" />
            </svg>
            <span class="bps-face" use:flightKey={spot.key} in:receiveAvatar|global={{ key: spot.key }} out:sendFace|global>
              <Avatar src={spot.u.avatar} name={spot.u.name} size={132} zoom={false} />
            </span>
            {#if spot.answered}
              <!-- The reply went out: the check pops in with a shower of sparks. -->
              <span class="bps-done" in:popIn use:sparkOnMount={{ count: 22, spread: 130 }}><Icon name="check" size={24} /></span>
            {/if}
          </div>
          <div class="bps-who">
            <div class="bps-where">{where}</div>
            <div class="bps-name" use:fitText={{ min: 26, text: spot.u.name }}>{spot.u.name}</div>
            {#key spot.answered ? "done" : spot.st.title}
              <div class="bps-status" data-tone={spot.answered ? "good" : spot.st.tone} in:popIn={{ from: 0.92 }}>
                {spot.answered ? "Replied" : spot.st.title}
              </div>
            {/key}
          </div>
        </div>

        <ol class="bps-track" aria-label="Where the reply is">
          {#each STEPS as label, i}
            <li class="bps-step" class:is-done={i < stage || stage === 5} class:is-now={i === stage && stage < 5}>
              <span class="bps-dot"></span><span class="bps-step-label">{label}</span>
            </li>
            {#if i < STEPS.length - 1}<li class="bps-line" class:is-done={i < stage} aria-hidden="true"><i></i></li>{/if}
          {/each}
        </ol>

        <div class="bps-msgs" class:is-hidden={hideText} class:is-above={above}
             bind:this={msgsEl} onscroll={onMsgsScroll}>
          {#each shown as m, i (m.mid ?? `${m.ts}:${i}`)}
            <div class="bps-msg" class:is-mine={m.mine} class:is-deleted={!!m.deleted} in:popIn>
              {#if !m.mine}
                <span class="bps-msg-av"><Avatar src={m.author?.avatar ?? spot.u.avatar} name={m.author?.name ?? spot.u.name} size={34} zoom={false} /></span>
              {/if}
              <div class="bps-bubble">
                {#if m.author && !m.mine}<div class="bps-author">{m.author.name}</div>{/if}
                <MessageBody text={m.text ?? ""} attachments={m.attachments ?? []} stickers={m.stickers ?? []} embeds={m.embeds ?? []} clamp={4} />
                {#if m.deleted}
                  <!-- Deleted on Discord and kept: a bin on its corner. -->
                  <span class="bps-bin" title="{m.mine ? 'You deleted this' : `${m.author?.name ?? spot.u.name} deleted this`} · {fmtDate(m.deleted * 1000, FULL_WHEN)}"><Icon name="trash" size={13} /></span>
                {:else if m.edited}
                  <span class="bps-edited">edited</span>
                {/if}
              </div>
              <!-- When it was sent: always there, quietly, since this view is
                   watched more than pointed at. -->
              {#if m.ts}<span class="bps-time" title={fmtDate(m.ts * 1000, FULL_WHEN)}>{whenSent(m.ts)}</span>{/if}
            </div>
          {/each}
          {#if theyType && !typing}
            <div class="bps-msg" in:popIn>
              <span class="bps-msg-av"><Avatar src={spot.u.avatar} name={spot.u.name} size={34} zoom={false} /></span>
              <div class="bps-bubble bps-typing" title="{spot.u.name} is typing"><i></i><i></i><i></i></div>
            </div>
          {/if}
          {#if typing}
            <div class="bps-msg is-mine" in:popIn>
              <div class="bps-bubble bps-typing" title={spot.st.title}><i></i><i></i><i></i></div>
            </div>
          {/if}
        </div>
        {#if !stick}
          <button type="button" class="bps-newest" onclick={() => toNewest()} in:popIn>
            <Icon name="chevron" size={13} />Newest
          </button>
        {/if}

        <!-- The same things the Chats tab can do, without leaving: answer them
             now, drop the reply that is lined up, stop answering them, or write
             one yourself. Only shown while the mouse is about, so the view still
             plays by itself when nobody is touching it. -->
        {#if onreply || onsend}
          <div class="bps-do">
            <form class="bps-say" onsubmit={(e) => { e.preventDefault(); say(); }}>
              <input bind:value={draft} placeholder="Write to {spot.u.name}…" maxlength="2000"
                     spellcheck="false" aria-label="Write to {spot.u.name}"
                     onkeydown={(e) => e.stopPropagation()} />
              <button type="submit" class="bps-btn is-go" disabled={!draft.trim() || busy}
                      title="Send as the account" aria-label="Send">
                <Icon name="send" size={15} />
              </button>
            </form>
            {#if onreply && !spot.answered}
              <button class="bps-btn" onclick={onreply} disabled={busy || replying}
                      title="Write and send a reply now, skipping the wait">
                <Icon name="chats" size={14} />{replying ? "Replying" : "Reply now"}
              </button>
            {/if}
            {#if oncancel && !spot.answered && spot.st.phase === "live"}
              <button class="bps-btn" onclick={oncancel} disabled={busy}
                      title="Drop the reply that is lined up">
                <Icon name="close" size={13} />Cancel
              </button>
            {/if}
            {#if onignore}
              <button class="bps-btn is-off" onclick={onignore} disabled={busy}
                      title="Stop answering them">
                <Icon name="eyeOff" size={14} />Ignore
              </button>
            {/if}
          </div>
        {/if}
      {:else if scene}
        <BPScenes {scene} {now} {hideText} recent={sceneData.recent} today={sceneData.today} hourly={sceneData.hourly}
                  top={sceneData.top} memory={sceneData.memory ?? null} waiting={sceneData.waiting ?? 0}
                  world={sceneData.world ?? null} act={sceneData.act ?? {}} />
      {/if}
    </div>
  {/key}
</div>

<style>
  /* One cell exactly as wide as the stage's column. Its width used to come from
     the content, so a long name made the whole stage wider, and the tracker and
     your own messages (aligned right) ran on under the panels on the right. */
  /* flex: the rest of the column, with the chapters under it taking what they need. */
  .bps { display: grid; grid-template: minmax(0, 1fr) / minmax(0, 1fr); min-width: 0; min-height: 0; height: 100%; flex: 1 1 0; }
  /* The leaving and the arriving stage share the one cell, so one lifts off the other.
     Centred, and no wider than reads well, however much room the side panels leave it. */
  .bps-layer {
    grid-area: 1 / 1;
    justify-self: center;
    will-change: transform, opacity;
    display: flex;
    width: min(100%, 1180px);
    min-width: 0;
    min-height: 0;
    flex-direction: column;
    /* safe: taller than the stage, it starts at the top rather than losing its heading off it */
    justify-content: safe center;
    gap: 26px;
    padding-bottom: 2vh;
  }
  .bps-hero { display: flex; align-items: center; gap: clamp(18px, 2.4vw, 34px); }
  .bps-halo { position: relative; display: grid; width: 170px; height: 170px; flex-shrink: 0; place-items: center; }
  .bps-ring { position: absolute; inset: 0; transform: rotate(-90deg); overflow: visible; }
  .bps-ring circle { fill: none; stroke-width: 4; }
  .bps-ring .track { stroke: rgb(255 255 255 / 0.1); }
  .bps-ring .fill {
    stroke: var(--color-accent);
    stroke-linecap: round;
    filter: drop-shadow(0 0 16px color-mix(in srgb, var(--color-accent) 42%, transparent));
    transition: stroke-dashoffset 1s linear;
  }
  /* Writing: the whole ring breathes rather than a dashed arc whipping round.
     The spinner read as a loading gif stuck on someone's face; a slow swell of
     light says "working on it" without demanding attention, and it is opacity
     only, so it composites. */
  .bps-halo[data-step="2"] .bps-ring .fill,
  .bps-halo[data-step="3"] .bps-ring .fill { animation: bps-breathe 2.6s ease-in-out infinite; }
  .bps-halo[data-step="2"] .bps-ring .fill { stroke-dasharray: none !important; stroke-dashoffset: 0 !important; }
  .bps-halo[data-tone="good"] .bps-ring .fill { stroke: var(--color-good); filter: drop-shadow(0 0 19px color-mix(in srgb, var(--color-good) 42%, transparent)); }
  @keyframes bps-breathe { 0%, 100% { opacity: 0.45; } 50% { opacity: 1; } }
  .bps-face { display: grid; place-items: center; border-radius: 999px; box-shadow: 0 20px 60px -20px rgb(0 0 0 / 0.8); }
  .bps-done {
    position: absolute;
    right: 8px;
    bottom: 8px;
    display: grid;
    width: 40px;
    height: 40px;
    place-items: center;
    border-radius: 999px;
    color: #fff;
    background: var(--color-good);
    box-shadow: 0 0 0 5px color-mix(in srgb, var(--color-good) 25%, transparent), 0 0 48px color-mix(in srgb, var(--color-good) 42%, transparent);
  }
  /* All the room beside the face, whatever the name: fitText measures against it. */
  .bps-who { display: flex; min-width: 0; flex: 1 1 0; flex-direction: column; gap: 4px; }
  .bps-where { font-size: 13px; font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; color: var(--bp-faint); }
  .bps-name {
    overflow: hidden;
    font-size: clamp(38px, 4.6vw, 72px);
    font-weight: 800;
    line-height: 1.16;
    letter-spacing: -0.035em;
    color: #fff;
    text-overflow: ellipsis;
    white-space: nowrap;
    /* Room above and below for an emoji, which stands taller than the letters:
       at a line height of 1 the box it is cut to sliced them flat. The margin
       takes the room back, so the layout is where it was. */
    padding-block: 0.1em;
    margin-block: -0.1em;
  }
  .bps-status { font-size: clamp(17px, 1.7vw, 24px); font-weight: 600; color: color-mix(in srgb, var(--color-accent) 75%, white); }
  .bps-status[data-tone="good"] { color: var(--color-good); }
  .bps-status[data-tone="warn"] { color: var(--color-warn); }
  .bps-status[data-tone="bad"] { color: var(--color-bad); }
  .bps-status[data-tone="muted"] { color: var(--bp-muted); }

  /* Doing something about the conversation on stage. */
  .bps-do { display: flex; flex-wrap: wrap; align-items: center; gap: 9px; padding: 2px 4px; }
  .bps-say {
    display: flex;
    min-width: 260px;
    flex: 1 1 320px;
    align-items: center;
    gap: 6px;
    padding: 5px 5px 5px 16px;
    border-radius: 999px;
    background: rgb(255 255 255 / 0.07);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.1);
    transition: box-shadow 0.2s ease;
  }
  .bps-say:focus-within { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, transparent); }
  .bps-say input {
    min-width: 0;
    flex: 1;
    font-size: 15px;
    color: #fff;
    background: transparent;
    outline: none;
  }
  .bps-say input::placeholder { color: var(--bp-faint); }
  /* As tall as the box you write in beside them: that is 38px of send button
     inside 5px of padding either side, so these are the same 48 and the row
     reads as one control rather than a tall box next to short buttons. */
  .bps-btn {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 7px;
    height: 48px;
    padding: 0 20px;
    border-radius: 999px;
    font-size: 14px;
    font-weight: 600;
    color: #fff;
    background: rgb(255 255 255 / 0.08);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.1);
    transition: transform 0.25s var(--spring), background-color 0.2s ease;
  }
  .bps-btn:hover:not(:disabled) { transform: translateY(-1px); background: rgb(255 255 255 / 0.14); }
  .bps-btn:active:not(:disabled) { transform: scale(0.96); }
  .bps-btn:disabled { opacity: 0.4; }
  .bps-btn.is-go {
    width: 38px;
    height: 38px;
    justify-content: center;
    padding: 0;
    color: var(--color-bg);
    background: var(--color-accent);
    box-shadow: none;
  }
  .bps-btn.is-off:hover:not(:disabled) { background: color-mix(in srgb, var(--color-bad) 35%, transparent); }
  @media (max-width: 720px) {
    .bps-say { min-width: 0; flex-basis: 100%; }
  }
  .bps-track { display: flex; min-width: 0; align-items: center; gap: 0; padding: 4px 6px; }
  .bps-step { display: flex; flex-shrink: 0; flex-direction: column; align-items: center; gap: 8px; width: 64px; }
  .bps-dot {
    width: 16px;
    height: 16px;
    border-radius: 999px;
    background: rgb(255 255 255 / 0.1);
    box-shadow: inset 0 0 0 1.5px rgb(255 255 255 / 0.18);
    transition: background-color 0.4s ease, box-shadow 0.4s ease, transform 0.5s var(--spring);
  }
  .bps-step.is-done .bps-dot { background: var(--color-accent); box-shadow: 0 0 22px color-mix(in srgb, var(--color-accent) 42%, transparent); }
  .bps-step.is-now .bps-dot {
    transform: scale(1.35);
    background: #fff;
    box-shadow: 0 0 0 5px color-mix(in srgb, var(--color-accent) 40%, transparent), 0 0 35px color-mix(in srgb, var(--color-accent) 42%, transparent);
    animation: bps-now 1.4s ease-in-out infinite;
  }
  @keyframes bps-now { 50% { box-shadow: 0 0 0 10px color-mix(in srgb, var(--color-accent) 8%, transparent), 0 0 48px color-mix(in srgb, var(--color-accent) 42%, transparent); } }
  .bps-step-label { font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--bp-faint); }
  .bps-step.is-now .bps-step-label, .bps-step.is-done .bps-step-label { color: #fff; }
  .bps-line { flex: 1; height: 3px; margin-bottom: 26px; overflow: hidden; border-radius: 999px; background: rgb(255 255 255 / 0.08); }
  .bps-line i { display: block; width: 0; height: 100%; background: var(--color-accent); box-shadow: 0 0 16px color-mix(in srgb, var(--color-accent) 42%, transparent); transition: width 0.7s var(--swift); }
  .bps-line.is-done i { width: 100%; }

  .bps-msgs {
    display: flex;
    min-height: 0;
    flex-direction: column;
    gap: 12px;
    overflow-y: auto;
    overscroll-behavior: contain;
    scrollbar-width: none;
    padding: 4px 4px 8px;
  }
  .bps-msgs::-webkit-scrollbar { display: none; }
  /* Scrolled up: what is above fades in from the top edge. */
  .bps-msgs.is-above {
    -webkit-mask-image: linear-gradient(to bottom, transparent, #000 36px);
    mask-image: linear-gradient(to bottom, transparent, #000 36px);
  }
  .bps-msg { flex-shrink: 0; }
  .bps-newest {
    position: absolute;
    right: 18px;
    bottom: 92px;
    z-index: 3;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 7px 14px 7px 11px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 600;
    color: #fff;
    background: color-mix(in srgb, var(--color-accent) 55%, rgb(20 20 30 / 0.7));
    box-shadow: 0 10px 30px -10px rgb(0 0 0 / 0.7);
    backdrop-filter: blur(12px);
  }
  .bps-newest :global(svg) { transform: rotate(90deg); }
  .bps-msg { display: flex; align-items: flex-end; gap: 10px; max-width: 78%; }
  .bps-msg.is-mine { align-self: flex-end; flex-direction: row-reverse; }
  .bps-time {
    flex-shrink: 0;
    margin-bottom: 8px;
    font-size: 12px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    color: rgb(255 255 255 / 0.5);
  }
  .bps-bubble {
    min-width: 0;
    padding: 13px 18px;
    overflow-wrap: anywhere;
    border-radius: 22px 22px 22px 6px;
    font-size: clamp(16px, 1.45vw, 21px);
    line-height: 1.4;
    color: #fff;
    /* No backdrop-filter here on purpose. A bubble is small and sits on a dark
       room, so a flat translucent fill is indistinguishable from a blurred one -
       and a backdrop blur per bubble has to re-sample the moving backdrop on
       every frame of every stage change, which is most of what made picking a
       conversation stutter. The big panels keep theirs; there are only a few. */
    background: rgb(255 255 255 / 0.1);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.09);
  }
  .bps-msg.is-mine .bps-bubble {
    border-radius: 22px 22px 6px 22px;
    background: color-mix(in srgb, var(--color-accent) 42%, rgb(0 0 0 / 0.2));
    box-shadow: 0 10px 34px -12px color-mix(in srgb, var(--color-accent) 70%, transparent);
  }
  .bps-author { margin-bottom: 2px; font-size: 12px; font-weight: 700; color: color-mix(in srgb, var(--color-accent) 70%, white); }
  .bps-msgs.is-hidden .bps-bubble :global(.mb-text),
  .bps-msgs.is-hidden .bps-bubble :global(img) { filter: blur(9px); }
  .bps-typing { display: flex; gap: 6px; padding: 16px 20px; }
  .bps-typing i { width: 9px; height: 9px; border-radius: 999px; background: #fff; animation: bps-bounce 1.2s ease-in-out infinite; }
  .bps-typing i:nth-child(2) { animation-delay: 0.15s; }
  .bps-typing i:nth-child(3) { animation-delay: 0.3s; }
  /* Deleted on Discord, and kept: faded, outlined, a bin on its corner. */
  .bps-msg.is-deleted .bps-bubble { position: relative; opacity: 0.65; box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--color-bad) 50%, transparent); }
  .bps-bin {
    position: absolute;
    top: -9px;
    right: -9px;
    display: grid;
    width: 26px;
    height: 26px;
    place-items: center;
    border-radius: 999px;
    color: #fff;
    background: var(--color-bad);
    box-shadow: 0 0 0 3px rgb(0 0 0 / 0.5);
  }
  .bps-msg.is-mine .bps-bin { right: auto; left: -9px; }
  .bps-edited { display: block; margin-top: 4px; font-size: 12px; opacity: 0.55; }
  @keyframes bps-bounce { 0%, 60%, 100% { transform: translateY(0); opacity: 0.4; } 30% { transform: translateY(-7px); opacity: 1; } }
  /* A phone: a smaller face, and a tracker that fits across the screen. The
     page scrolls there, so the stage is as tall as what is on it rather than
     a fixed box that a long scene spills out of, over the bar under it. */
  @media (max-width: 720px) {
    .bps { height: auto; flex: none; grid-template: auto / minmax(0, 1fr); }
    .bps-hero { gap: 16px; }
    .bps-halo { width: 118px; height: 118px; }
    .bps-face { transform: scale(0.72); }
    .bps-step { width: auto; flex: 0 1 44px; min-width: 0; }
    .bps-step-label { font-size: 8.5px; letter-spacing: 0; }
    .bps-msg { max-width: 92%; }
  }
  @media (max-width: 460px) {
    .bps-step-label { display: none; }
    .bps-step.is-now .bps-step-label { display: block; position: absolute; margin-top: 30px; }
    .bps-step { position: relative; }
  }
  :global(:root[data-motion="off"]) .bps-halo,
  :global(:root[data-motion="off"]) .bps-ring,
  :global(:root[data-motion="off"]) .bps-step.is-now .bps-dot,
  :global(:root[data-motion="off"]) .bps-ring .fill,
  :global(:root[data-motion="off"]) .bps-typing i { animation: none; }
  /* A message that is only a picture is shown as the picture: no bubble
     behind it, no padding around it. A background plus the image's own
     rounded corners read as a box drawn around every photo. */
  .bps-bubble:has(:global(.mb-media)):not(:has(:global(.mb-text))):not(:has(:global(.mb-chip))) {
    padding: 0;
    background: none;
    box-shadow: none;
    backdrop-filter: none;
  }
</style>
