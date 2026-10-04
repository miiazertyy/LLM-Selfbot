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
   * So it shows up quickly and takes no room. A small arc turns while a request
   * is out - the same one the sidebar uses for a page still loading, so the two
   * read as one thing - and clicking it opens the log, which is the one place
   * that says what the bot is actually doing right now. (It used to turn around
   * the app's logo; the logo inside the ring was clutter, so it went.)
   *
   * It waits a beat before appearing. Most reads come back in well under a
   * quarter of a second, and a mark that blinks on and off with every one of
   * them is worse than no mark at all.
   */
  import { onMount } from "svelte";
  import { inflight } from "../api";
  import { health } from "../stores";
  import { busyRoutes, progressText } from "../busy";
  import ProgressRing from "./ProgressRing.svelte";

  /** The page on screen, so its own progress can be shown here. */
  let { route = "" }: { route?: string } = $props();

  // Work on this page that knows how far along it is - reply to all, a folder
  // of pictures. While that runs the badge shows it exactly, instead of a
  // spinner and "Asking the account" for minutes.
  const own = $derived($busyRoutes[route]);
  const ownPct = $derived(progressText(own));

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
      {#if ownPct}
        <ProgressRing done={own?.done} total={own?.total} size={14} />
      {:else}
        <ProgressRing size={14} />
      {/if}
    </span>
    <!-- Real progress is worth saying at once. Otherwise only once it is slow
         enough to be worth explaining; the mark alone carries the rest. -->
    {#if ownPct}
      <span class="load-badge-text">
        {own?.labels?.[0] || doing} · {ownPct}
      </span>
    {:else if slow}
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
    padding: 3px 8px 3px 6px;
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
    display: grid;
    place-items: center;
    width: 14px;
    height: 14px;
    flex: 0 0 auto;
    color: var(--color-accent);
    filter: drop-shadow(0 0 4px color-mix(in srgb, currentColor 50%, transparent));
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
  .load-badge.is-slow .load-badge-mark {
    color: var(--color-warn);
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

</style>
