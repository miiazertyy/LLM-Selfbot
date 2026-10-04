<script lang="ts">
  /**
   * A little example of what a switch does, beside it in Settings, played on
   * a loop: a few lines of a chat for most switches, a small scene for the
   * rest (lib/switchdemos.ts has them all). Flipping the switch plays the
   * other version at once, so the difference is seen, not read.
   *
   * It only plays while it is on screen and the Animations switch is on;
   * otherwise it shows how the loop ends, standing still. It is decoration
   * for the eye: screen readers skip it, the switch's own words say it.
   *
   * It wakes only at the moments something changes (a line comes or goes,
   * the loop fades out), not every ninety milliseconds: a page of them ticking
   * was work the browser did while the tab was opening, for nothing. And it
   * starts a moment after its row has landed.
   */
  import { onMount } from "svelte";
  import { motionEnabled } from "../stores";
  import { DEMOS, linesAt, parts, type Chat, type Line } from "../switchdemos";

  let { key, on }: { key: string; on: boolean } = $props();

  const demo = $derived(DEMOS[key]);
  const LOOP = $derived(demo?.loop ?? 5200);
  const side = $derived(demo ? (on ? demo.on : demo.off) : null);
  const chat = $derived(side && "lines" in side ? (side as Chat) : null);
  const scene = $derived(side && "scene" in side ? side.scene : "");

  // ── The loop's clock ───────────────────────────────────────────────────────
  let t = $state(0);
  let start = 0;
  let playing = $state(false);
  let root: HTMLDivElement | null = $state(null);
  const still = () => !$motionEnabled || document.documentElement.dataset.motion === "off";

  /** The moments in the loop at which something changes, in order. */
  const moments = $derived.by(() => {
    const out = new Set<number>([LOOP - 420]);
    if (chat) {
      for (const l of chat.lines) for (const m of [l.at, l.until, l.thenAt]) if (m != null) out.add(m);
      if (chat.glowAt) out.add(chat.glowAt);
    } else if (scene === "status") {
      out.add(LOOP / 3);
      out.add((2 * LOOP) / 3);
    } else if (scene === "night") {
      out.add(LOOP * 0.45);
    }
    return [...out].filter((m) => m > 0 && m < LOOP).sort((a, b) => a - b);
  });

  let timer = 0;
  let seen = false;
  /** Where the loop is now, and a wake-up for the next moment something changes. */
  function step() {
    clearTimeout(timer);
    if (!seen || document.hidden || still()) {
      playing = false;
      t = LOOP - 1;
      return;
    }
    playing = true;
    const phase = performance.now() - start;
    const at = ((phase % LOOP) + LOOP) % LOOP;
    // Before it starts (just after its row lands), nothing yet.
    t = phase < 0 ? 0 : at;
    const next = phase < 0 ? -phase : (moments.find((m) => m > at + 1) ?? LOOP) - at;
    timer = window.setTimeout(step, next + 8);
  }

  onMount(() => {
    const io = new IntersectionObserver(([e]) => {
      const was = seen;
      seen = e.isIntersecting;
      // Coming into view: from the top, a moment after its row lands.
      if (seen && !was) start = performance.now() + 450;
      step();
    });
    if (root) io.observe(root);
    const vis = () => step();
    document.addEventListener("visibilitychange", vis);
    return () => {
      io.disconnect();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", vis);
    };
  });
  // Flipping the switch starts the other version from the top, at once.
  $effect(() => {
    void on;
    start = performance.now();
    if (seen) step();
  });

  const lines = $derived(chat ? linesAt(chat, t) : []);
  /** The last moment of the loop fades out, so it starts again from nothing rather than jumping. */
  const ending = $derived(playing && t > LOOP - 420);
  const glowing = $derived(!!chat?.glowAt && t >= chat.glowAt);
  const swapped = (l: Line) => l.then != null && l.thenAt != null && t >= l.thenAt;
  /** Typing dots and the reply after them are one line, so the reply takes the dots' place rather than sliding in over them. */
  const lineKey = (l: Line) => (l.kind === "typing" ? `${l.who}-${l.until}` : `${l.who}-${l.at}`);
  const AVATAR: Record<string, string> = { M: "#f39ac7", G: "#9d8cff", "#": "#6fb4ff", S: "#fffc00", K: "#7ee0b5" };

  // Scenes that move on their own clock (a status cycling, day into night).
  const STATUS_ORDER = ["online", "idle", "dnd"] as const;
  const status = $derived(on ? STATUS_ORDER[Math.floor(Math.max(0, t) / (LOOP / 3)) % 3] : "online");
  const night = $derived(t > LOOP * 0.45);
</script>

{#if demo}
  <div class="sd" class:is-ending={ending} class:is-still={!playing} bind:this={root} aria-hidden="true">
    {#if chat}
      <div class="sd-chat">
        {#each lines as l (lineKey(l))}
          <div class="sd-line is-{l.who}" class:is-dim={l.dim} class:is-glow={l.glow && glowing}>
            {#if l.who === "them" && l.kind !== "request"}
              <span class="sd-av" style="--av: {AVATAR[l.from ?? 'M'] ?? '#f39ac7'}">{l.from ?? "M"}</span>
            {/if}
            {#if l.kind === "typing"}
              <span class="sd-bub is-typing"><i></i><i></i><i></i></span>
            {:else if l.kind === "voice"}
              <span class="sd-bub is-voice">
                <svg viewBox="0 0 8 8"><path d="M2 1.2v5.6L6.8 4Z" /></svg>
                {#each [3, 6, 4, 8, 5, 7, 3, 6, 4, 5] as h, i (i)}<b style="--h: {h}px; --d: {i * 70}ms"></b>{/each}
                <em>0:04</em>
              </span>
            {:else if l.kind === "image"}
              <span class="sd-bub is-image"><svg viewBox="0 0 30 20"><circle cx="22" cy="6" r="2.6" /><path d="M0 20 9 9l6 7 4-4 11 8Z" /></svg></span>
            {:else if l.kind === "reply"}
              <span class="sd-bub is-reply"><small>↱ {l.then}</small>{l.text}</span>
            {:else if l.kind === "bio"}
              <span class="sd-card is-bio"><span class="sd-scan"></span><b>Bio</b> {l.text}</span>
            {:else if l.kind === "summary"}
              <span class="sd-card is-summary"><b>Summary · {l.text}</b><i style="--w: 92%"></i><i style="--w: 70%"></i></span>
            {:else if l.kind === "request"}
              <span class="sd-card is-request" class:is-done={swapped(l)}>
                <span class="sd-av" style="--av: {AVATAR[l.from ?? 'K'] ?? '#7ee0b5'}">{(l.text ?? "?")[0]}</span>
                <span class="min-w-0 flex-1"><b>{l.text}</b><small>{l.from === "S" ? "added you" : "wants to be friends"}</small></span>
                {#if swapped(l)}<span class="sd-ok">✓ {l.then}</span>{:else}<span class="sd-ask"><i>✓</i><i>✕</i></span>{/if}
              </span>
            {:else if l.kind === "alert"}
              <span class="sd-alert" class:is-ringing={l.mark === "bell"}>
                <span class="sd-tg">{#if l.mark === "hook"}<svg viewBox="0 0 10 10"><path d="M3.2 6.8a2.2 2.2 0 1 1 1.3-4L6 5.4M6.8 3.4a2.2 2.2 0 1 1-1.9 3.9H2" /></svg>{:else}<svg viewBox="0 0 24 24"><path d="M20.7 4.3 2.9 11.2c-1.2.5-1.2 1.2-.2 1.5l4.6 1.4 1.8 5.4c.2.6.4.8.9.8.4 0 .6-.2.9-.5l2.2-2.1 4.6 3.4c.8.5 1.4.2 1.6-.8l3-14c.3-1.3-.5-1.8-1.6-1.4Z" /></svg>{/if}</span>
                <span class="min-w-0 flex-1 truncate">{l.text}</span>
                {#if l.mark === "bell"}<span class="sd-bell">🔔</span>{:else if l.mark === "bellOff"}<span class="sd-bell is-off">🔕</span>{/if}
              </span>
            {:else if l.who === "note"}
              <span class="sd-note is-{l.mark ?? 'plain'}">
                {#if l.mark === "cross"}✕{:else if l.mark === "check"}✓{:else if l.mark === "dice"}⚄{:else if l.mark === "clock"}◷{:else if l.mark === "zzz"}z{:else if l.mark === "warn"}!{:else if l.mark === "chats"}+{/if}
                {l.text}
              </span>
            {:else}
              <span class="sd-bub" class:is-swapped={swapped(l)}>
                {#if swapped(l)}
                  <s>{l.text}</s> {l.then}
                {:else}
                  {#each parts(l.text ?? "") as p, i (i)}{#if p.lit}<mark>{p.text}</mark>{:else}{p.text}{/if}{/each}
                {/if}
              </span>
            {/if}
          </div>
        {/each}
      </div>

    {:else if scene === "status"}
      <div class="sd-scene">
        <span class="sd-me"><span class="sd-av is-big" style="--av: var(--color-accent)">J</span><i class="sd-dot is-{status}"></i></span>
        <span class="sd-says"><b>{status === "online" ? "Online" : status === "idle" ? "Idle" : "Do Not Disturb"}</b><small>{on ? "changes every so often" : "stays as it is"}</small></span>
      </div>

    {:else if scene === "night"}
      <div class="sd-scene">
        <span class="sd-sky" class:is-night={night}><span class="sd-sun"></span><span class="sd-moon"></span></span>
        <span class="sd-me"><span class="sd-av is-big" style="--av: var(--color-accent)">J</span><i class="sd-dot {night && on ? 'is-invisible' : 'is-online'}"></i></span>
        <span class="sd-says"><b>{night && on ? "Invisible" : "Online"}</b><small>{night ? (on ? "at night, still replying" : "all night long") : "in the day"}</small></span>
      </div>

    {:else if scene === "persona"}
      <div class="sd-scene is-persona" class:is-on={on}>
        {#each [1, 2] as n (n)}
          <span class="sd-acct"><span class="sd-av" style="--av: {n === 1 ? '#f39ac7' : '#6fb4ff'}">{n}</span><i class="sd-wire"></i>
            <span class="sd-file">{on ? `persona ${n}` : "one persona"}</span></span>
        {/each}
      </div>

    {:else if scene === "profile"}
      <div class="sd-scene is-profile" class:is-on={on}>
        <span class="sd-name">@mara<span class="sd-cursor"></span></span>
        {#if on}
          <span class="sd-pcard"><span class="sd-av" style="--av: #f39ac7">M</span><span><b>Mara</b><small>loves cats · paris</small></span></span>
        {:else}
          <span class="sd-note is-cross">✕ No card</span>
        {/if}
      </div>

    {:else if scene === "browser"}
      <div class="sd-scene is-browser" class:is-on={on}>
        <span class="sd-window">
          <span class="sd-bar"><i></i><i></i><i></i></span>
          <span class="sd-page"><i style="--w: 70%"></i><i style="--w: 45%"></i></span>
        </span>
        <span class="sd-says"><b>{on ? "No window" : "Chrome shows"}</b><small>{on ? "runs out of sight" : "you can watch it"}</small></span>
      </div>

    {:else if scene.startsWith("run-")}
      {@const what = scene.slice(4)}
      <div class="sd-scene is-run is-{what}" class:is-on={on}>
        <span class="sd-app">{what === "discord" ? "D" : what === "snapchat" ? "S" : what === "telegram" ? "T" : "W"}</span>
        <svg class="sd-beat" viewBox="0 0 110 22" preserveAspectRatio="none">
          <path d={on ? "M0 11h30l4-7 5 14 5-12 3 5h63" : "M0 11h110"} />
        </svg>
        <span class="sd-says is-short"><b>{on ? "Running" : "Off"}</b></span>
      </div>
    {/if}
  </div>
{/if}

<style>
  .sd {
    position: relative;
    width: 188px;
    height: 56px;
    overflow: hidden;
    font-size: 10px;
    line-height: 1.25;
    user-select: none;
    pointer-events: none;
    /* Older lines fade out at the very top rather than being cut. */
    mask-image: linear-gradient(180deg, transparent, #000 8px);
    transition: opacity 0.4s var(--swift);
  }
  .sd.is-ending { opacity: 0; }
  /* Its own little world: what moves in here never makes the page around it
     lay itself out again. */
  .sd { contain: strict; }
  .sd-chat { position: absolute; inset: 0; display: flex; flex-direction: column; justify-content: flex-end; gap: 3px; }
  /* A line comes in from nothing, pushing the ones above it up as it grows:
     plain CSS, where Svelte's transitions measured every line as it came, in
     the middle of the page being built. */
  .sd-line {
    display: flex;
    max-height: 40px;
    align-items: flex-end;
    gap: 4px;
    transition: opacity 0.4s var(--swift);
    animation: sd-in 0.32s var(--spring) backwards;
  }
  /* From only: where it ends is the line's own style (a dimmed one stays dim). */
  @keyframes sd-in {
    from { max-height: 0; opacity: 0; transform: translateY(6px); }
  }
  .sd-line.is-me { justify-content: flex-end; }
  .sd-line.is-note { justify-content: center; }
  .sd-line.is-dim { opacity: 0.4; }
  .sd-av {
    display: grid;
    width: 13px;
    height: 13px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    font-size: 7.5px;
    font-weight: 800;
    color: rgb(0 0 0 / 0.7);
    background: var(--av);
  }
  .sd-av.is-big { width: 26px; height: 26px; font-size: 12px; }
  .sd-bub {
    max-width: 150px;
    overflow: hidden;
    padding: 1px 7px 2px;
    border-radius: 9px 9px 9px 3px;
    color: var(--color-ink);
    white-space: nowrap;
    text-overflow: ellipsis;
    background: rgb(255 255 255 / 0.13);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.05);
  }
  .is-me .sd-bub { border-radius: 9px 9px 3px 9px; color: var(--color-bg); background: color-mix(in srgb, var(--color-accent) 88%, white); }
  .sd-bub mark { padding: 0 2px; border-radius: 4px; color: #b9c6ff; background: rgb(88 101 242 / 0.35); }
  .is-me .sd-bub mark { color: #1c2566; background: rgb(88 101 242 / 0.3); }
  .sd-line.is-glow .sd-bub { box-shadow: 0 0 0 1.5px #ffd76a, 0 0 10px -2px #ffd76a; }
  .sd-bub.is-swapped s { opacity: 0.55; }
  .sd-bub.is-swapped { animation: sd-swap 0.4s var(--spring); }
  @keyframes sd-swap { 40% { transform: scale(1.06); } }
  .sd-bub.is-typing { display: inline-flex; gap: 2.5px; padding: 5px 7px; }
  .sd-bub.is-typing i { width: 4px; height: 4px; border-radius: 999px; background: currentColor; opacity: 0.5; animation: sd-dot 1s ease-in-out infinite; }
  .sd-bub.is-typing i:nth-child(2) { animation-delay: 0.15s; }
  .sd-bub.is-typing i:nth-child(3) { animation-delay: 0.3s; }
  @keyframes sd-dot { 30% { opacity: 1; transform: translateY(-2px); } }
  .sd-bub.is-voice { display: inline-flex; align-items: center; gap: 1.5px; padding: 3px 7px; }
  .sd-bub.is-voice svg { width: 8px; height: 8px; margin-right: 3px; fill: currentColor; }
  .sd-bub.is-voice b { width: 2px; height: var(--h); border-radius: 2px; background: currentColor; opacity: 0.8; animation: sd-wave 0.9s ease-in-out var(--d) infinite; }
  .sd-bub.is-voice em { margin-left: 4px; font-style: normal; font-size: 8.5px; opacity: 0.7; }
  @keyframes sd-wave { 50% { transform: scaleY(0.4); } }
  .sd-bub.is-image { padding: 2px; }
  .sd-bub.is-image svg { display: block; width: 38px; height: 26px; border-radius: 7px; background: linear-gradient(160deg, #7fd3ff, #b58cff); }
  .sd-bub.is-image svg circle { fill: #fff3b0; }
  .sd-bub.is-image svg path { fill: rgb(20 30 60 / 0.55); }
  .sd-bub.is-reply small { display: block; font-size: 8px; opacity: 0.7; }
  .sd-note {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 1px 7px;
    border-radius: 999px;
    font-size: 9.5px;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.04);
  }
  .sd-note.is-cross { color: color-mix(in srgb, var(--color-bad) 80%, var(--color-faint)); }
  .sd-note.is-check { color: var(--color-good); }
  .sd-note.is-dice, .sd-note.is-warn { color: var(--color-warn); }
  .sd-card {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 5px;
    padding: 4px 7px;
    border-radius: 9px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.06);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06);
  }
  .sd-card b { color: var(--color-ink); font-weight: 650; }
  .sd-card small { display: block; font-size: 8.5px; color: var(--color-faint); }
  .sd-card.is-bio { position: relative; overflow: hidden; }
  .sd-scan { position: absolute; inset: 0; background: linear-gradient(90deg, transparent, rgb(255 255 255 / 0.18), transparent); transform: translateX(-100%); animation: sd-scan 1.6s ease-in-out 0.3s infinite; }
  .is-dim .sd-scan { display: none; }
  @keyframes sd-scan { 60%, 100% { transform: translateX(100%); } }
  .sd-card.is-summary { width: 160px; flex-direction: column; align-items: flex-start; gap: 3px; }
  .sd-card.is-summary i { display: block; height: 3px; width: var(--w); border-radius: 3px; background: rgb(255 255 255 / 0.2); transform-origin: left; animation: sd-write 1.3s var(--swift) both; }
  .sd-card.is-summary i:last-child { animation-delay: 0.5s; }
  @keyframes sd-write { from { transform: scaleX(0); } }
  .sd-card.is-request { width: 168px; }
  .sd-card.is-request.is-done { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-good) 50%, transparent); }
  .sd-ask { display: inline-flex; gap: 3px; }
  .sd-ask i { display: grid; width: 14px; height: 14px; place-items: center; border-radius: 999px; font-style: normal; font-size: 8px; background: rgb(255 255 255 / 0.08); }
  .sd-ok { font-size: 9px; font-weight: 700; color: var(--color-good); animation: sd-swap 0.4s var(--spring); }
  .sd-alert {
    display: flex;
    width: 176px;
    align-items: center;
    gap: 6px;
    padding: 4px 7px;
    border-radius: 10px;
    font-size: 9.5px;
    color: var(--color-ink);
    background: rgb(30 36 52 / 0.95);
    box-shadow: 0 6px 16px -8px rgb(0 0 0 / 0.8), inset 0 0 0 1px rgb(255 255 255 / 0.08);
  }
  .sd-tg { display: grid; width: 15px; height: 15px; flex-shrink: 0; place-items: center; border-radius: 999px; background: linear-gradient(160deg, #37bbfe, #1e96d7); }
  .sd-tg svg { width: 9px; height: 9px; fill: #fff; stroke: none; }
  .sd-tg svg path[d^="M3.2"] { fill: none; stroke: #fff; stroke-width: 1.2; stroke-linecap: round; }
  .sd-bell { font-size: 10px; }
  .sd-alert.is-ringing .sd-bell { animation: sd-ring 1.2s ease-in-out infinite; transform-origin: 50% 0; }
  .sd-bell.is-off { opacity: 0.6; }
  @keyframes sd-ring { 0%, 50%, 100% { transform: rotate(0); } 10%, 30% { transform: rotate(16deg); } 20%, 40% { transform: rotate(-16deg); } }

  /* ── Scenes ─────────────────────────────────────────────────────────────── */
  .sd:has(.sd-scene) { mask-image: none; }
  .sd-scene { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; gap: 9px; }
  .sd-says { display: flex; min-width: 0; flex-direction: column; }
  .sd-says b { font-size: 11px; font-weight: 650; color: var(--color-ink); }
  .sd-says small { font-size: 9px; color: var(--color-faint); }
  .sd-me { position: relative; display: inline-flex; }
  .sd-dot {
    position: absolute;
    right: -2px;
    bottom: -2px;
    width: 10px;
    height: 10px;
    border-radius: 999px;
    border: 2px solid var(--color-card, #1a1b26);
    transition: background-color 0.4s var(--swift), box-shadow 0.4s var(--swift);
  }
  .sd-dot.is-online { background: #23a55a; }
  .sd-dot.is-idle { background: #f0b232; }
  .sd-dot.is-dnd { background: #f23f43; }
  .sd-dot.is-invisible { background: #80848e; box-shadow: inset 0 0 0 2px #80848e, inset 0 0 0 5px var(--color-card, #1a1b26); }
  .sd-sky { position: relative; width: 22px; height: 22px; flex-shrink: 0; }
  .sd-sun, .sd-moon { position: absolute; inset: 3px; border-radius: 999px; transition: transform 0.7s var(--spring), opacity 0.5s var(--swift); }
  .sd-sun { background: #ffcf6a; box-shadow: 0 0 10px #ffcf6a; }
  .sd-moon { background: #c9c1ff; box-shadow: inset -4px -2px 0 0 #6d5dfc; opacity: 0; transform: translateY(8px) scale(0.6); }
  .sd-sky.is-night .sd-sun { opacity: 0; transform: translateY(8px) scale(0.6); }
  .sd-sky.is-night .sd-moon { opacity: 1; transform: none; }
  .sd-scene.is-persona { flex-direction: column; align-items: flex-start; gap: 4px; padding-left: 14px; }
  .sd-acct { display: flex; align-items: center; gap: 4px; }
  .sd-wire { width: 18px; height: 1.5px; border-radius: 2px; background: rgb(255 255 255 / 0.25); transform-origin: left; animation: sd-write 0.8s var(--swift) both; }
  .sd-file { padding: 1px 6px; border-radius: 5px; font-size: 9px; color: var(--color-muted); background: rgb(255 255 255 / 0.06); }
  .sd-scene.is-persona.is-on .sd-acct:nth-child(2) .sd-file { color: #9fd0ff; }
  .sd-scene.is-persona.is-on .sd-acct:nth-child(1) .sd-file { color: #f8b6d8; }
  .sd-scene.is-profile { justify-content: flex-start; padding-left: 8px; gap: 8px; }
  .sd-name { position: relative; font-weight: 650; color: #b9c6ff; }
  .sd-cursor { position: absolute; left: 60%; top: 70%; width: 8px; height: 10px; background: #fff; clip-path: polygon(0 0, 0 100%, 30% 72%, 55% 100%, 70% 92%, 45% 66%, 100% 62%); animation: sd-point 2.6s ease-in-out infinite; }
  @keyframes sd-point { 0% { transform: translate(14px, 8px); } 40%, 100% { transform: none; } }
  .sd-pcard { display: flex; align-items: center; gap: 5px; padding: 4px 8px 4px 5px; border-radius: 10px; background: rgb(30 36 52 / 0.95); box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08); animation: sd-pop 2.6s var(--spring) infinite; }
  .sd-pcard b { display: block; font-size: 9.5px; color: var(--color-ink); }
  .sd-pcard small { font-size: 8px; color: var(--color-faint); }
  @keyframes sd-pop { 0%, 35% { opacity: 0; transform: scale(0.85) translateY(4px); } 45%, 90% { opacity: 1; transform: none; } 100% { opacity: 0; } }
  .sd-scene.is-browser { gap: 10px; }
  .sd-window { display: flex; width: 58px; height: 38px; flex-direction: column; overflow: hidden; border-radius: 6px; background: rgb(255 255 255 / 0.06); box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.12); transition: opacity 0.5s var(--swift), transform 0.5s var(--spring); }
  .sd-bar { display: flex; gap: 2px; padding: 3px 4px; background: rgb(255 255 255 / 0.07); }
  .sd-bar i { width: 3px; height: 3px; border-radius: 999px; background: rgb(255 255 255 / 0.35); }
  .sd-page { display: flex; flex-direction: column; gap: 3px; padding: 5px; }
  .sd-page i { display: block; height: 3px; width: var(--w); border-radius: 3px; background: #fffc00; opacity: 0.6; }
  .sd-scene.is-browser.is-on .sd-window { opacity: 0.25; transform: scale(0.9); box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.3); background: transparent; }
  .sd-scene.is-browser.is-on .sd-page, .sd-scene.is-browser.is-on .sd-bar { visibility: hidden; }
  .sd-scene.is-run { gap: 8px; }
  .sd-app { display: grid; width: 22px; height: 22px; flex-shrink: 0; place-items: center; border-radius: 7px; font-size: 11px; font-weight: 800; color: #fff; background: #5865f2; transition: filter 0.4s var(--swift), opacity 0.4s var(--swift); }
  .is-snapchat .sd-app { color: #111; background: #fffc00; }
  .is-telegram .sd-app { background: #2aabee; }
  .is-webui .sd-app { background: var(--color-accent); color: var(--color-bg); }
  .sd-scene.is-run:not(.is-on) .sd-app { filter: grayscale(1); opacity: 0.45; }
  .sd-beat { width: 96px; height: 22px; overflow: visible; }
  .sd-beat path { fill: none; stroke: var(--color-good); stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; stroke-dasharray: 150; animation: sd-beat 1.6s linear infinite; }
  .sd-scene.is-run:not(.is-on) .sd-beat path { stroke: rgb(255 255 255 / 0.18); animation: none; stroke-dasharray: 3 4; }
  @keyframes sd-beat { from { stroke-dashoffset: 150; } to { stroke-dashoffset: -150; } }
  .sd-says.is-short b { font-size: 10.5px; }
  .sd-scene.is-run:not(.is-on) .sd-says b { color: var(--color-faint); }

  /* Standing still (off screen, or Animations off): nothing loops. */
  .sd.is-still *, :global(:root[data-motion="off"]) .sd * { animation: none !important; }
</style>
