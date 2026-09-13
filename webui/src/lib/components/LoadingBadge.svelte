<script lang="ts">
  /**
   * A small spinning mark in the header while the panel is waiting on something.
   *
   * This replaced a banner that pushed the page down after four seconds to
   * explain that things were slow and suggest opening Settings. It was right
   * about the problem and wrong about the answer: by the time it appeared you
   * had already been staring at a still page wondering whether it had hung, and
   * then the fix for that was a paragraph that moved the content.
   *
   * So it shows up quickly and takes no room. The app's own mark turns while a
   * request is out, and clicking it opens the log, which is the one place that
   * says what the bot is actually doing right now.
   *
   * It waits a beat before appearing. Most reads come back in well under a
   * quarter of a second, and a mark that blinks on and off with every one of
   * them is worse than no mark at all.
   */
  import { onMount } from "svelte";
  import { inflight } from "../api";
  import { health } from "../stores";
  import logo from "../../assets/icon.png";

  /** Long enough that a quick read never flashes it. */
  const AFTER_MS = 450;
  /** Long enough to be worth naming a likely cause. */
  const SLOW_MS = 5000;

  let now = $state(Date.now());

  onMount(() => {
    // Only ticks while something is actually out, so an idle panel does nothing
    // four times a second for ever.
    let timer: any = null;
    const stop = inflight.subscribe((list) => {
      if (list.length && timer === null) {
        now = Date.now();
        timer = setInterval(() => (now = Date.now()), 250);
      } else if (!list.length && timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    });
    return () => {
      stop();
      if (timer !== null) clearInterval(timer);
    };
  });

  /** The longest running read, and how long it has been going. */
  const oldest = $derived.by(() => {
    const worst = $inflight.reduce(
      (w, e) => (w === null || e.started < w.started ? e : w),
      null as { path: string; started: number } | null,
    );
    if (!worst) return null;
    return { ...worst, waited: now - worst.started };
  });

  const showing = $derived(!!oldest && oldest.waited >= AFTER_MS);
  const slow = $derived(!!oldest && oldest.waited >= SLOW_MS);
  const seconds = $derived(oldest ? Math.max(1, Math.round(oldest.waited / 1000)) : 0);

  /** What is most likely holding this up, when anything is known to be wrong. */
  const blocker = $derived(
    ($health.issues ?? []).find((i) => i.level === "error")
      ?? ($health.issues ?? []).find((i) => i.level === "warn")
      ?? null,
  );

  const doing = $derived.by(() => {
    const p = oldest?.path ?? "";
    if (p.startsWith("/api/chats") || p.startsWith("/api/friends")) return "Asking the account";
    if (p.startsWith("/api/models")) return "Asking Groq for its models";
    if (p.startsWith("/api/system")) return "Checking this machine";
    if (p.startsWith("/api/logs")) return "Reading the log";
    if (p.startsWith("/api/stats")) return "Counting messages";
    return "Loading";
  });

  const tip = $derived(
    `${doing}, ${seconds}s so far. Click to see what the bot is doing.`
    + (blocker ? `\n\nThis may be why: ${blocker.title}. ${blocker.detail}` : ""),
  );
</script>

{#if showing}
  <button
    class="load-badge no-drag"
    class:is-slow={slow}
    title={tip}
    aria-label={tip}
    onclick={() => (window.location.hash = "/logs")}
  >
    <span class="load-badge-mark">
      <img src={logo} alt="" width="16" height="16" />
      <svg class="load-badge-ring" viewBox="0 0 32 32" aria-hidden="true">
        <circle cx="16" cy="16" r="14" />
      </svg>
    </span>
    <!-- Only once it is slow enough to be worth explaining, and only where
         there is width for it. The mark alone carries the rest of the time. -->
    {#if slow}
      <span class="load-badge-text">
        {blocker ? blocker.title : doing} · {seconds}s
      </span>
    {/if}
  </button>
{/if}

<style>
  .load-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    flex: 0 0 auto;
    max-width: 46%;
    padding: 2px 6px 2px 2px;
    border-radius: 999px;
    color: var(--color-faint);
    animation: load-badge-in 0.25s var(--swift) both;
    transition: background-color 0.18s var(--swift), color 0.18s var(--swift);
  }
  .load-badge:hover {
    background: rgb(255 255 255 / 0.06);
    color: var(--color-ink);
  }
  .load-badge:active {
    transform: scale(0.96);
  }

  .load-badge-mark {
    position: relative;
    display: grid;
    place-items: center;
    width: 22px;
    height: 22px;
    flex: 0 0 auto;
  }
  .load-badge-mark img {
    /* Breathing rather than spinning: the mark is a face, and a face turning
       end over end reads as broken rather than busy. The ring does the turning. */
    animation: load-badge-breathe 1.6s ease-in-out infinite;
    opacity: 0.9;
  }

  .load-badge-ring {
    position: absolute;
    inset: 0;
    width: 22px;
    height: 22px;
    animation: load-badge-spin 0.9s linear infinite;
  }
  .load-badge-ring circle {
    fill: none;
    stroke: var(--color-accent);
    stroke-width: 2.5;
    stroke-linecap: round;
    /* A quarter of the circumference, so it reads as one travelling arc. */
    stroke-dasharray: 22 66;
    opacity: 0.85;
  }

  .load-badge-text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 11px;
    animation: load-badge-in 0.25s var(--swift) both;
  }
  /* Waiting this long is worth a warmer colour than "busy". */
  .load-badge.is-slow {
    color: var(--color-muted);
  }
  .load-badge.is-slow .load-badge-ring circle {
    stroke: var(--color-warn);
  }

  @keyframes load-badge-spin {
    to {
      transform: rotate(360deg);
    }
  }
  @keyframes load-badge-breathe {
    0%,
    100% {
      transform: scale(1);
      opacity: 0.9;
    }
    50% {
      transform: scale(0.86);
      opacity: 0.6;
    }
  }
  @keyframes load-badge-in {
    from {
      opacity: 0;
      transform: translateX(6px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }

  /* Still says it is working, just without the motion. */
  :global(:root[data-motion="off"]) .load-badge,
  :global(:root[data-motion="off"]) .load-badge-text {
    animation: none;
  }
  :global(:root[data-motion="off"]) .load-badge-ring {
    animation: none;
  }
  :global(:root[data-motion="off"]) .load-badge-mark img {
    animation: none;
    opacity: 0.75;
  }
</style>
