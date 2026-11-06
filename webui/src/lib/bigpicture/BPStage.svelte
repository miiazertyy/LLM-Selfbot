<script lang="ts">
  /**
   * The conversation on stage, big: the middle of the Now page.
   *
   * Their picture in a ring that counts down to the reply, who they are and where,
   * six slim segments from Received to Sent with the one under way filling, and the
   * conversation itself in large bubbles, each run of them with one face and one
   * time. New messages pop in; while the model writes or the reply is typed out,
   * dots bounce where it will appear, with what it is thinking in a faint bubble
   * above them when it is a model that says. When the reply has gone, a check, and
   * the thought folds away.
   *
   * A change of who is on stage pulls the next one up from below (motion.ts), and
   * the face flies in from its row in the queue, and back to it when it leaves,
   * under the key it arrived with (flightKey).
   *
   * The buttons say only what can be done now: Reply now when there is a wait to
   * skip, Cancel when a reply is lined up, Ignore, and Answer again once they have
   * been ignored. They rest with the pointer, so the view plays clean when nobody
   * is touching it.
   */
  import { slide } from "svelte/transition";
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import MessageBody from "../components/MessageBody.svelte";
  import PlatformMark from "../components/PlatformMark.svelte";
  import { FULL_WHEN, fmtDate, whenSent } from "../fmt";
  import { STEPS, progress } from "../chatstatus";
  import { convKey, drafts, setDraft, typingNow, type ConvMessage } from "../chats";
  import { platformOfUser } from "../platforms";
  import { shortModel } from "../providers";
  import { motionEnabled } from "../stores";
  import type { Thought } from "../thoughts";
  import { fitText } from "./fit";
  import { focusable } from "./focus";
  import { sparkOnMount } from "./fx";
  import { flightKey, popIn, receiveAvatar, sendFace } from "./motion";
  import { ago, runsOf } from "./scenes";
  import type { Spot } from "./types";

  let {
    spot,
    messages = [],
    now = 0,
    multi = false,
    thought = null,
    busy = false,
    replying = false,
    onearlier,
    onreply,
    oncancel,
    onignore,
    onsend,
    composer = $bindable(null),
  }: {
    spot: Spot;
    messages?: ConvMessage[];
    now?: number;
    multi?: boolean;
    /** What the model thought for this reply, when it says. */
    thought?: Thought | null;
    busy?: boolean;
    replying?: boolean;
    /** Scrolled to the top: read further back. */
    onearlier?: () => void;
    /** Answer them now, skipping the wait. */
    onreply?: () => void;
    /** Drop the reply that is lined up. */
    oncancel?: () => void;
    /** Stop answering them, or start again. */
    onignore?: () => void;
    /** Send this text as the account. */
    onsend?: (text: string) => void;
    /** The box to write in, for W. */
    composer?: HTMLInputElement | null;
  } = $props();

  /** On the tracker: 0 received ... 5 sent. */
  const stage = $derived(spot.answered ? 5 : spot.st.phase === "live" ? spot.st.step ?? 0 : 0);
  const quietly = $derived(!!spot.browsing || !!spot.ignored);
  const typing = $derived(!spot.answered && !quietly && spot.st.phase === "live" && (spot.st.step === 2 || spot.st.step === 4));
  /** They are typing to it right now (lib/chats.ts typingNow): their dots, as the bot has its own. */
  const theyType = $derived(!!$typingNow[convKey(spot.target, String(spot.u.id))]);
  /** How far round the ring is: the wait counting down, or all of it while it works. */
  const ring = $derived(spot.answered ? 1 : quietly ? 0 : spot.st.step === 1 || spot.st.step === 3 ? progress(spot.st, now) : spot.st.step ? 1 : 0);
  const canHurry = $derived(!spot.answered && !quietly && (spot.st.phase === "needs" || spot.st.step === 1 || spot.st.step === 3));
  const canCancel = $derived(!spot.answered && !quietly && spot.st.phase === "live");

  const statusWord = $derived(spot.ignored ? "The bot is off for them" : spot.browsing
    ? (spot.u.ts ? `Last message ${ago(spot.u.ts, now)}` : "Not waiting")
    : spot.answered ? "Replied" : spot.st.title);
  const statusTone = $derived(spot.ignored ? "warn" : spot.browsing ? "muted" : spot.answered ? "good" : spot.st.tone);

  /**
   * The conversation, both sides, as far back as it has been read; the row's own
   * last message when the history has not been read yet.
   */
  const shown = $derived.by<ConvMessage[]>(() => {
    if (messages.length) return messages.slice(-100);
    const u = spot.u;
    if (!u.text && !u.snippet && !u.attachments?.length) return [];
    return [{ mine: false, ts: u.ts ?? now, mid: u.mid, text: u.text || u.snippet || "",
              attachments: u.attachments, stickers: u.stickers, embeds: u.embeds }];
  });
  const ends = $derived(runsOf(shown));
  const where = $derived.by(() => {
    if (spot.u.kind === "server") return spot.u.where ?? "A server";
    const acct = spot.account?.display_name || spot.account?.username;
    return multi && acct ? `Direct message, to ${acct}` : "Direct message";
  });
  const C = 2 * Math.PI * 52;

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
  // The bubbles below the last message come and go: keep the newest in view while they do.
  $effect(() => {
    void typing;
    void theyType;
    void thought;
    if (stick) queueMicrotask(() => msgsEl && (msgsEl.scrollTop = msgsEl.scrollHeight));
  });

  // ── What it is thinking, typed out ───────────────────────────────────────
  let typed = $state(0);
  let thoughtEl: HTMLElement | null = $state(null);
  $effect(() => {
    const text = thought?.text ?? "";
    void thought?.at;
    typed = 0;
    if (!text) return;
    if (!$motionEnabled) {
      typed = text.length;
      return;
    }
    const id = setInterval(() => {
      typed = Math.min(text.length, typed + 3);
      if (typed >= text.length) clearInterval(id);
    }, 16);
    return () => clearInterval(id);
  });
  $effect(() => {
    void typed;
    const box = thoughtEl;
    if (box && box.scrollHeight > box.clientHeight) box.scrollTop = box.scrollHeight;
    if (stick && msgsEl) msgsEl.scrollTop = msgsEl.scrollHeight;
  });

  // ── Writing to them from here ────────────────────────────────────────────
  // The Chats tab's own drafts: a half-written line follows them there and back.
  const draftKey = $derived(convKey(spot.target, String(spot.u.id)));
  const draft = $derived($drafts[draftKey] ?? "");
  function say() {
    const text = draft.trim();
    if (!text) return;
    setDraft(draftKey, "");
    onsend?.(text);
  }
</script>

<div class="bps">
  <div class="bps-hero">
    <div class="bps-halo" data-tone={statusTone} data-step={spot.answered ? 5 : quietly ? 0 : spot.st.step ?? 0}>
      <svg class="bps-ring" viewBox="0 0 116 116" aria-hidden="true"><circle cx="58" cy="58" r="52" class="track" /></svg>
      <svg class="bps-ring is-fill" viewBox="0 0 116 116" aria-hidden="true">
        <circle cx="58" cy="58" r="52" class="fill" style="stroke-dasharray: {C}; stroke-dashoffset: {C * (1 - ring)}" />
      </svg>
      <span class="bps-face" use:flightKey={spot.key} in:receiveAvatar|global={{ key: spot.key }} out:sendFace|global>
        <Avatar src={spot.u.avatar} name={spot.u.name} size={92} zoom={false} />
      </span>
      {#if spot.answered}
        <!-- The reply went out: the check pops in with a shower of sparks. -->
        <span class="bps-done" in:popIn use:sparkOnMount={{ count: 22, spread: 130 }}><Icon name="check" size={18} /></span>
      {/if}
    </div>
    <div class="bps-who">
      <div class="bp-name" use:fitText={{ min: 26, text: spot.u.name }}>{spot.u.name}</div>
      <div class="bps-line">
        {#key statusWord}
          <span class="bps-status" data-tone={statusTone} in:popIn={{ from: 0.94 }}>{statusWord}</span>
        {/key}
        <span class="bps-where"><PlatformMark platform={spot.account?.platform ?? platformOfUser(spot.u.id).id} size={18} />{where}</span>
      </div>
      {#if !quietly}
        <ol class="bps-track" aria-label="Where the reply is">
          {#each STEPS as label, i}
            <li class="bps-step" class:is-done={i < stage || stage === 5} class:is-now={i === stage && stage < 5}
                data-moving={i === stage && (stage === 1 || stage === 3) ? "yes" : undefined}>
              <span class="bps-seg"><i style="--f: {i === stage && (stage === 1 || stage === 3) ? progress(spot.st, now) : i < stage || stage === 5 ? 1 : i === stage ? 1 : 0}"></i></span>
              <span class="bps-step-label">{label}</span>
            </li>
          {/each}
        </ol>
      {/if}
    </div>
  </div>

  <div class="bps-msgs bp-scrolls" class:is-above={above} bind:this={msgsEl} onscroll={onMsgsScroll}>
    {#each shown as m, i (m.mid ?? `${m.ts}:${i}`)}
      <div class="bps-msg" class:is-mine={m.mine} class:is-end={ends[i]} class:is-deleted={!!m.deleted} in:popIn>
        {#if !m.mine}
          <span class="bps-msg-av">
            {#if ends[i]}<Avatar src={m.author?.avatar ?? spot.u.avatar} name={m.author?.name ?? spot.u.name} size={32} zoom={false} />{/if}
          </span>
        {/if}
        <div class="bps-bubble" data-private>
          {#if m.author && !m.mine}<div class="bps-author">{m.author.name}</div>{/if}
          <MessageBody text={m.text ?? ""} attachments={m.attachments ?? []} stickers={m.stickers ?? []} embeds={m.embeds ?? []} clamp={4} />
          {#if m.deleted}
            <!-- Deleted on Discord and kept: a bin on its corner. -->
            <span class="bps-bin" title="{m.mine ? 'You deleted this' : `${m.author?.name ?? spot.u.name} deleted this`} · {fmtDate(m.deleted * 1000, FULL_WHEN)}"><Icon name="trash" size={13} /></span>
          {:else if m.edited}
            <span class="bps-edited">edited</span>
          {/if}
        </div>
        <!-- When it was sent, once for each run of them, quietly: this view is watched more than pointed at. -->
        {#if m.ts && ends[i]}<span class="bps-time" title={fmtDate(m.ts * 1000, FULL_WHEN)}>{whenSent(m.ts)}</span>{/if}
      </div>
    {/each}
    {#if theyType && !typing}
      <div class="bps-msg is-end" in:popIn>
        <span class="bps-msg-av"><Avatar src={spot.u.avatar} name={spot.u.name} size={32} zoom={false} /></span>
        <div class="bps-bubble bps-typing" title="{spot.u.name} is typing"><i></i><i></i><i></i></div>
      </div>
    {/if}
    {#if thought && !spot.answered && !quietly}
      <div class="bps-msg is-mine bps-think" transition:slide={{ duration: $motionEnabled ? 280 : 0 }}>
        <div class="bps-thought" data-private>
          <div class="bps-thought-head">Thinking · {shortModel(thought.model || "model")}</div>
          <p bind:this={thoughtEl}>{thought.text.slice(0, typed)}</p>
        </div>
      </div>
    {/if}
    {#if typing}
      <div class="bps-msg is-mine is-end" in:popIn>
        <div class="bps-bubble bps-typing" title={spot.st.title}><i></i><i></i><i></i></div>
      </div>
    {/if}
  </div>
  {#if !stick}
    <button type="button" class="bp-btn is-small bps-newest" onclick={() => toNewest()} in:popIn>
      <Icon name="arrowDown" size={14} />Newest
    </button>
  {/if}

  <div class="bps-do">
    <form class="bps-say" onsubmit={(e) => { e.preventDefault(); say(); }}>
      <input bind:this={composer} value={draft} oninput={(e) => setDraft(draftKey, e.currentTarget.value)}
             placeholder="Write to {spot.u.name}…" maxlength="2000" spellcheck="false" aria-label="Write to {spot.u.name}"
             use:focusable={{ id: `write:${spot.key}` }} data-private="soft"
             onkeydown={(e) => { if (e.key !== "Escape") e.stopPropagation(); }} />
      <button type="submit" class="bp-btn is-small is-round bps-send" class:is-go={!!draft.trim()} disabled={!draft.trim() || busy}
              title="Send as the account" aria-label="Send">
        <Icon name="send" size={15} />
      </button>
    </form>
    {#if canHurry}
      <button class="bp-btn" use:focusable={{ id: "do:reply" }} onclick={onreply} disabled={busy || replying} title="Write and send a reply now (R)">
        <Icon name="reply" size={15} />{replying ? "Replying" : "Reply now"}
      </button>
    {/if}
    {#if canCancel}
      <button class="bp-btn" use:focusable={{ id: "do:cancel" }} onclick={oncancel} disabled={busy} title="Drop the reply that is lined up">
        <Icon name="close" size={14} />Cancel
      </button>
    {/if}
    {#if spot.ignored}
      <button class="bp-btn" use:focusable={{ id: "do:again" }} onclick={onignore} disabled={busy} title="Let the bot answer them again">
        <Icon name="eye" size={15} />Answer again
      </button>
    {:else if !spot.browsing}
      <button class="bp-btn bps-off" use:focusable={{ id: "do:ignore" }} onclick={onignore} disabled={busy} title="Stop answering them">
        <Icon name="eyeOff" size={15} />Ignore
      </button>
    {/if}
  </div>
</div>

<style>
  /* One cell exactly as wide as its column, and no wider than reads well: its
     width used to come from the content, so a long name made the whole stage wider. */
  .bps {
    position: relative;
    display: flex;
    width: min(100%, 1120px);
    height: 100%;
    min-width: 0;
    min-height: 0;
    flex-direction: column;
    gap: clamp(10px, 1.6vh, 18px);
    margin-inline: auto;
    padding-bottom: 6px;
  }
  .bps-hero { display: flex; flex-shrink: 0; align-items: center; gap: clamp(14px, 1.5vw, 26px); }
  .bps-halo { position: relative; display: grid; width: 116px; height: 116px; flex-shrink: 0; place-items: center; }
  .bps-ring { position: absolute; inset: 0; transform: rotate(-90deg); overflow: visible; }
  .bps-ring circle { fill: none; stroke-width: 3.5; }
  .bps-ring .track { stroke: var(--bp-line); }
  /* A ring is drawn on the page's own thread, every frame its arc moves: a smooth second's worth of it, begun again
     every second, was a style pass at the screen's 143 a second for as long as the view was open, and most of what it
     cost sitting still. Four steps a second look the same on a ring this size. */
  .bps-ring .fill { stroke: var(--bp-lit); stroke-linecap: round; transition: stroke-dashoffset 1s steps(4, jump-none); }
  /* Writing: the whole ring breathes rather than a dashed arc whipping round.
     The spinner read as a loading gif stuck on someone's face; a slow swell of
     light says "working on it" without demanding attention, and it is opacity
     only, so it composites. */
  .bps-halo[data-step="2"] .bps-ring.is-fill,
  .bps-halo[data-step="3"] .bps-ring.is-fill { animation: bps-breathe 2.6s ease-in-out infinite; }
  .bps-halo[data-step="2"] .bps-ring .fill { stroke-dasharray: none !important; stroke-dashoffset: 0 !important; }
  .bps-halo[data-tone="good"] .bps-ring .fill { stroke: var(--color-good); }
  @keyframes bps-breathe { 0%, 100% { opacity: 0.45; } 50% { opacity: 1; } }
  .bps-face { display: grid; place-items: center; border-radius: 999px; }
  .bps-done {
    position: absolute;
    right: 4px;
    bottom: 4px;
    display: grid;
    width: 32px;
    height: 32px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-bg);
    background: var(--color-good);
  }
  /* All the room beside the face, whatever the name: fitText measures against it. */
  .bps-who { display: flex; min-width: 0; flex: 1 1 0; flex-direction: column; gap: 3px; }
  .bps-line { display: flex; min-width: 0; flex-wrap: wrap; align-items: baseline; gap: 2px 14px; }
  .bps-status { font-size: clamp(16px, 1.25vw, 22px); font-weight: 650; color: var(--bp-lit); }
  .bps-status[data-tone="good"] { color: var(--color-good); }
  .bps-status[data-tone="warn"] { color: var(--color-warn); }
  .bps-status[data-tone="bad"] { color: var(--color-bad); }
  .bps-status[data-tone="muted"] { color: var(--bp-muted); }
  .bps-where { display: inline-flex; min-width: 0; align-items: center; align-self: center; gap: 7px; overflow: hidden; font-size: 13px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; color: var(--bp-faint); }

  /* Six slim segments, one running on from the last, the way a story's do. */
  .bps-track { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 5px; margin-top: 7px; max-width: 620px; }
  .bps-step { display: flex; min-width: 0; flex-direction: column; gap: 5px; }
  .bps-seg { display: block; height: 4px; overflow: hidden; border-radius: 999px; background: var(--bp-line); }
  .bps-seg i { display: block; height: 100%; border-radius: 999px; background: var(--bp-lit); transform: scaleX(var(--f, 0)); transform-origin: left; transition: transform 1s linear; }
  /* Under way with nothing to count: it breathes, as the ring does. */
  .bps-step.is-now:not([data-moving]) .bps-seg i { animation: bps-breathe 2.6s ease-in-out infinite; }
  .bps-step-label { overflow: hidden; font-size: 11.5px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; color: var(--bp-faint); transition: color 0.3s ease; }
  .bps-step.is-now .bps-step-label { color: var(--color-ink); }

  .bps-msgs {
    display: flex;
    min-height: 0;
    flex: 1 1 0;
    flex-direction: column;
    gap: 3px;
    padding: 4px 2px 6px;
  }
  /* Scrolled up: what is above fades in from the top edge. */
  .bps-msgs.is-above {
    -webkit-mask-image: linear-gradient(to bottom, transparent, #000 36px);
    mask-image: linear-gradient(to bottom, transparent, #000 36px);
  }
  /* Pushed to the bottom as a chat is, and flex-shrink 0 so a long one scrolls rather than squashing. */
  .bps-msg:first-child { margin-top: auto; }
  .bps-msg { display: flex; flex-shrink: 0; max-width: 76%; align-items: flex-end; gap: 10px; }
  .bps-msg.is-end { margin-bottom: 12px; }
  .bps-msg.is-mine { align-self: flex-end; flex-direction: row-reverse; }
  .bps-msg-av { display: grid; width: 32px; flex-shrink: 0; place-items: center; }
  .bps-time {
    flex-shrink: 0;
    margin-bottom: 7px;
    font-size: 12px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    color: var(--bp-faint);
  }
  .bps-bubble {
    position: relative;
    min-width: 0;
    padding: clamp(9px, 1.1vh, 13px) clamp(13px, 1vw, 18px);
    overflow-wrap: anywhere;
    border-radius: 21px;
    font-size: clamp(16px, 1.22vw, 24px);
    line-height: 1.36;
    /* No backdrop-filter here on purpose. A bubble is small and sits on a dark
       room, so a flat translucent fill is indistinguishable from a blurred one -
       and a backdrop blur per bubble has to re-sample the moving backdrop on
       every frame of every stage change, which is most of what made picking a
       conversation stutter. */
    background: color-mix(in srgb, var(--color-ink) 11%, transparent);
  }
  .bps-msg.is-end .bps-bubble { border-bottom-left-radius: 6px; }
  .bps-msg.is-mine .bps-bubble { background: color-mix(in srgb, var(--color-accent) 58%, rgb(0 0 0 / 0.3)); }
  .bps-msg.is-mine.is-end .bps-bubble { border-bottom-left-radius: 21px; border-bottom-right-radius: 6px; }
  .bps-author { margin-bottom: 2px; font-size: 12px; font-weight: 700; color: var(--bp-lit); }
  .bps-typing { display: flex; gap: 6px; padding: 15px 19px; }
  .bps-typing i { width: 8px; height: 8px; border-radius: 999px; background: var(--color-ink); animation: bps-bounce 1.2s ease-in-out infinite; }
  .bps-typing i:nth-child(2) { animation-delay: 0.15s; }
  .bps-typing i:nth-child(3) { animation-delay: 0.3s; }
  @keyframes bps-bounce { 0%, 60%, 100% { transform: translateY(0); opacity: 0.4; } 30% { transform: translateY(-6px); opacity: 1; } }
  /* What the model is thinking: where the reply will land, faint, and folded away when it does. */
  .bps-think { max-width: 66%; margin-bottom: 4px; }
  .bps-thought { min-width: 0; padding: 10px 15px 11px; border-radius: 18px; background: color-mix(in srgb, var(--color-accent) 13%, transparent); }
  .bps-thought-head { margin-bottom: 3px; font-size: 12px; font-weight: 650; color: var(--bp-lit); }
  .bps-thought p {
    max-height: 7.2em;
    overflow: hidden;
    font-size: clamp(13px, 0.92vw, 16px);
    line-height: 1.44;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    color: var(--bp-muted);
    -webkit-mask-image: linear-gradient(to bottom, transparent, #000 1.2em);
    mask-image: linear-gradient(to bottom, transparent, #000 1.2em);
  }
  /* Deleted on Discord, and kept: faded, a bin on its corner. */
  .bps-msg.is-deleted .bps-bubble { opacity: 0.6; }
  .bps-bin {
    position: absolute;
    top: -8px;
    right: -8px;
    display: grid;
    width: 24px;
    height: 24px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-ink);
    background: var(--color-bad);
  }
  .bps-msg.is-mine .bps-bin { right: auto; left: -8px; }
  .bps-edited { display: block; margin-top: 3px; font-size: 12px; opacity: 0.55; }
  /* A message that is only a picture is shown as the picture: no bubble
     behind it, no padding around it. A background plus the image's own
     rounded corners read as a box drawn around every photo. */
  .bps-bubble:has(:global(.mb-media)):not(:has(:global(.mb-text))):not(:has(:global(.mb-chip))) {
    padding: 0;
    background: none;
  }
  .bps-newest { position: absolute; right: 4px; bottom: 70px; z-index: 3; background: color-mix(in srgb, var(--color-accent) 60%, #10111a); }

  /* Doing something about them. */
  .bps-do { display: flex; flex-shrink: 0; flex-wrap: wrap; align-items: center; gap: 8px; transition: opacity 0.6s ease; }
  /* Nobody touching it: it plays clean, with the box to write in still there for whoever comes back. */
  :global(.bp.is-asleep) .bps-do:not(:focus-within) { opacity: 0.25; }
  .bps-say {
    display: flex;
    min-width: 240px;
    flex: 1 1 300px;
    align-items: center;
    gap: 6px;
    height: 44px;
    padding: 0 4px 0 18px;
    border-radius: 999px;
    background: var(--bp-fill);
    transition: background-color 0.2s ease;
  }
  .bps-say:focus-within { background: var(--bp-fill-hi); }
  .bps-say input { min-width: 0; height: 100%; flex: 1; font-size: 15px; color: var(--color-ink); background: transparent; outline: none; }
  .bps-say input::placeholder { color: var(--bp-faint); }
  .bps-off:hover:not(:disabled) { color: var(--color-bad); }
  /* A phone: a smaller face, and the segments fit across the screen. */
  @media (max-width: 720px) {
    .bps { height: auto; }
    .bps-msgs { flex: none; max-height: 56vh; }
    .bps-hero { align-items: flex-start; }
    .bps-halo { width: 84px; height: 84px; }
    .bps-face { transform: scale(0.72); }
    .bps-step-label { font-size: 9.5px; }
    .bps-msg { max-width: 92%; }
    .bps-say { min-width: 0; flex-basis: 100%; }
  }
  @media (max-width: 460px) {
    .bps-step-label { display: none; }
    .bps-step.is-now .bps-step-label { display: block; overflow: visible; }
  }
  /* A short screen: the conversation keeps the room. */
  @media (max-height: 720px) {
    .bps-halo { width: 88px; height: 88px; }
    .bps-face { transform: scale(0.76); }
    .bps-step-label { display: none; }
  }
  :global(:root[data-motion="off"]) .bps-ring.is-fill,
  :global(:root[data-motion="off"]) .bps-ring .fill,
  :global(:root[data-motion="off"]) .bps-seg i,
  :global(:root[data-motion="off"]) .bps-typing i { animation: none; transition: none; }
</style>
