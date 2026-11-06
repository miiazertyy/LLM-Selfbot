<script lang="ts">
  /**
   * What an account is thinking, as it thinks it, typed out (lib/thoughts.ts). Only models that think out loud send these
   * (gpt-oss, qwen3, deepseek-r1 and the like), and a Minecraft account's every decision.
   *
   *   card     on the Dashboard: each account's latest, the newest typed out, or a line saying none has come
   *   line     on an account's card: its latest, for as long as it is fresh, and no room at all otherwise
   *   overlay  over the picture of what a Minecraft account sees: its latest, fading away when it has gone quiet
   *
   * The parent places an overlay. Its text is white on dark, whatever the theme, since what is under it is a game.
   */
  import { onDestroy, onMount } from "svelte";
  import { fade, slide } from "svelte/transition";
  import { chatAccounts } from "../chats";
  import { sourceInfo } from "../logrows";
  import { shortModel } from "../providers";
  import { socialsOn, sourceOn } from "../socials";
  import { motionEnabled } from "../stores";
  import { thoughts, useThoughts, type Thought } from "../thoughts";
  import { play } from "../uisound";
  import PlatformMark from "./PlatformMark.svelte";

  let { source = "", variant = "card" }: { source?: string; variant?: "card" | "line" | "overlay" } = $props();

  /** How long a thought stays up where it goes away, in seconds. */
  const FRESH = { line: 120, overlay: 45, card: Infinity };

  let now = $state(Date.now() / 1000);
  let clock = 0;
  onMount(() => {
    clock = window.setInterval(() => (now = Date.now() / 1000), 5000);
    return useThoughts();
  });
  onDestroy(() => clearInterval(clock));

  const mine = $derived($thoughts.filter((t) => (source ? t.source === source : sourceOn($socialsOn, t.source))));
  /** Newest first, each account's latest. */
  const rows = $derived.by((): Thought[] => {
    const seen = new Set<string>();
    const out: Thought[] = [];
    for (let i = mine.length - 1; i >= 0 && out.length < 4; i--) {
      if (seen.has(mine[i].source)) continue;
      seen.add(mine[i].source);
      out.push(mine[i]);
    }
    return out;
  });
  const latest = $derived(rows[0] ?? null);
  const showing = $derived(!!latest && now - latest.at < FRESH[variant]);

  // Typed out at a speed you can follow, however long it is: a long one is not much slower to read through than a short
  // one. Restarts with every new thought.
  let shown = $state(0);
  let box: HTMLElement | null = $state(null);
  let lastAt = 0;
  $effect(() => {
    const t = latest;
    if (!t || !showing) return;
    if (t.at !== lastAt && lastAt && variant !== "line") play("glint", { level: 0.3 });
    lastAt = t.at;
    // Typed only if it has only just come: one read back from before this was opened is simply there.
    if (!$motionEnabled || Date.now() / 1000 - t.at > 20) {
      shown = t.text.length;
      return;
    }
    shown = 0;
    const step = Math.max(2, Math.ceil(t.text.length / 400));
    const id = setInterval(() => {
      shown = Math.min(t.text.length, shown + step);
      if (shown >= t.text.length) clearInterval(id);
    }, 16);
    return () => clearInterval(id);
  });
  // The newest words stay in view, top down, without the text being upside down.
  $effect(() => {
    void shown;
    const el = box;
    if (el) requestAnimationFrame(() => (el.scrollTop = el.scrollHeight));
  });

  const who = (t: Thought) => sourceInfo(t.source, $chatAccounts).name;
  const platform = (t: Thought) => t.source.replace(/_\d+$/, "");
  function ago(at: number): string {
    const s = Math.max(0, now - at);
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    return `${Math.round(s / 3600)} h ago`;
  }
</script>

{#if variant === "card"}
  {#if rows.length}
    <div class="lt-list">
      {#each rows as t, i (t.source)}
        <div class="lt-row" transition:slide={{ duration: $motionEnabled ? 220 : 0 }}>
          <div class="lt-head">
            <PlatformMark platform={platform(t)} size={20} />
            <b class="lt-who">{who(t)}</b>
            <span class="lt-model">{shortModel(t.model || "model")} · {ago(t.at)}</span>
          </div>
          {#if i === 0}
            <p class="lt-text is-open selectable" bind:this={box}>{t.text.slice(0, shown)}{#if shown < t.text.length}<span class="lt-caret"></span>{/if}</p>
          {:else}
            <p class="lt-text is-past selectable">{t.text}</p>
          {/if}
        </div>
      {/each}
    </div>
  {:else}
    <p class="lt-none">None yet. A model that reasons before it answers shows it here, as it happens.</p>
  {/if}
{:else if showing && latest}
  {#if variant === "line"}
    <div class="lt-line" transition:slide={{ duration: $motionEnabled ? 240 : 0 }}>
      <div class="lt-head">
        <span class="lt-pulse" aria-hidden="true"></span>
        <b class="lt-who">Thinking</b>
        <span class="lt-model">{shortModel(latest.model || "model")}</span>
      </div>
      <p class="lt-text is-short selectable" bind:this={box}>{latest.text.slice(0, shown)}{#if shown < latest.text.length}<span class="lt-caret"></span>{/if}</p>
    </div>
  {:else}
    <div class="lt-overlay" transition:fade={{ duration: $motionEnabled ? 240 : 0 }}>
      <div class="lt-head">
        <span class="lt-pulse" aria-hidden="true"></span>
        <b class="lt-who">Thinking</b>
      </div>
      <p class="lt-text is-short" bind:this={box}>{latest.text.slice(0, shown)}{#if shown < latest.text.length}<span class="lt-caret"></span>{/if}</p>
    </div>
  {/if}
{/if}

<style>
  .lt-list { display: flex; flex-direction: column; gap: 12px; }
  .lt-row { min-width: 0; }
  .lt-head { display: flex; min-width: 0; align-items: center; gap: 7px; }
  .lt-who { min-width: 0; overflow: hidden; font-size: 12.5px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; color: var(--color-ink); }
  .lt-model { margin-left: auto; flex-shrink: 0; font-size: 11px; color: var(--color-faint); }
  .lt-none { padding: 6px 0; font-size: 12.5px; line-height: 1.5; color: var(--color-faint); }
  .lt-text { margin-top: 5px; overflow: hidden; font-size: 12.5px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--color-muted); }
  .lt-text.is-open { max-height: 190px; overflow-y: auto; color: var(--color-ink); }
  .lt-text.is-past { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2; color: var(--color-faint); }
  .lt-text.is-short { max-height: 4.65em; overflow-y: auto; scrollbar-width: none; }
  .lt-caret {
    display: inline-block;
    width: 2px;
    height: 1em;
    margin-left: 1px;
    vertical-align: -0.15em;
    background: var(--color-accent);
    animation: lt-caret 1s steps(2, jump-none) infinite;
  }
  @keyframes lt-caret { from { opacity: 1; } to { opacity: 0.25; } }
  .lt-pulse { width: 7px; height: 7px; flex-shrink: 0; border-radius: 999px; background: var(--color-accent); animation: lt-pulse 1.6s ease-in-out infinite; }
  @keyframes lt-pulse { 50% { opacity: 0.35; } }

  .lt-line {
    padding: 9px 11px;
    border-radius: 12px;
    background: color-mix(in srgb, var(--color-accent) 9%, transparent);
  }

  .lt-overlay {
    padding: 8px 10px;
    border-radius: 11px;
    pointer-events: none;
    color: #fff;
    background: rgb(12 10 16 / 0.62);
  }
  .lt-overlay .lt-who { font-size: 11px; color: rgb(255 255 255 / 0.75); }
  .lt-overlay .lt-text { margin-top: 3px; font-size: 11.5px; line-height: 1.45; color: #fff; }

  :global(:root[data-motion="off"]) .lt-caret,
  :global(:root[data-motion="off"]) .lt-pulse { animation: none; }
</style>
