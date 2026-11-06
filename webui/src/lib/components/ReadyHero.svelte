<script lang="ts" module>
  export type ReadyStep = {
    name: string;
    what: string;
    done: boolean;
    /** Being done right now: it spins. */
    working?: boolean;
    /** What it shows at the end of its row: a version, an address, "None yet". */
    shows: string;
    /** Nice to have: the rest being in is enough to be ready. */
    optional?: boolean;
  };
</script>

<script lang="ts">
  /**
   * "It is ready to run": a platform's mark, where it stands in a sentence, a bar of four parts, and the parts listed
   * underneath. Each part in place lights in turn, its segment filling and its tick popping with a note a step higher
   * than the last; when they are all in, a shine runs along the bar, the count and the Ready badge spring up and the mark
   * hops, with a soft bell. What is seen and heard is one timeline.
   *
   * Snapchat's page had this first, and the browser platforms share that one (SnapchatSetup.svelte). This is the same
   * thing for a platform that has nothing to install: what it needs comes in as `steps`, and what to do about it as
   * `action`, in the Ready badge's place. Whatever goes between the card and the list is `children`.
   */
  import { untrack, type Snippet } from "svelte";
  import { get } from "svelte/store";
  import { afterLanding, onScreen, whenShown } from "../cascade";
  import { PLATFORMS, type PlatformId } from "../platforms";
  import { motionEnabled } from "../stores";
  import { play } from "../uisound";
  import Icon from "./Icon.svelte";

  let { platform, title, sub, tone = "working", steps, action, go, children }: {
    platform: PlatformId;
    title: string;
    sub: string;
    /** "good" lights the card in the platform's colour; the rest grey its mark. */
    tone?: "good" | "warn" | "bad" | "working";
    steps: ReadyStep[];
    /** What to do next, in the Ready badge's place, when it is more than a link. */
    action?: Snippet;
    /** What to do next, when it is somewhere to go. */
    go?: { label: string; href?: string; onclick?: () => void } | null;
    children?: Snippet;
  } = $props();

  const ready = $derived(steps.every((s) => s.optional || s.done));

  const brand = $derived(PLATFORMS[platform]);

  let hero: HTMLElement | null = $state(null);
  let list: HTMLElement | null = $state(null);
  /** The parts shown in place, by name. */
  let lit = $state<Record<string, boolean>>({});
  /** All in, and the finish played (or shown at once). */
  let complete = $state(false);
  let landed = false;
  let heard = false;
  const timers: number[] = [];
  const booked = new Set<string>();
  const GAP_MS = 150;

  $effect(() => {
    const el = hero;
    const ol = list;
    if (!el || !ol || landed) return;
    whenShown(el).then(() => {
      // Both blocks down, then it begins: held back while the card drops in, a segment sat as a small square.
      afterLanding(el, () => afterLanding(ol, async () => {
        heard = await onScreen(el);
        landed = true;
        light();
      }));
    });
  });
  // A part coming in while the page is open lights the same way.
  $effect(() => {
    void steps;
    if (landed) untrack(light);
  });
  $effect(() => () => timers.forEach(clearTimeout));

  function light() {
    // One that has stopped being true goes out, and lights again if it comes back.
    const out = steps.filter((s) => !s.done && lit[s.name]);
    if (out.length) {
      const left = { ...lit };
      for (const s of out) delete left[s.name];
      lit = left;
      complete = false;
    }
    const fresh = steps.filter((s) => s.done && !lit[s.name] && !booked.has(s.name));
    if (!fresh.length) return finish();
    if (!get(motionEnabled)) {
      lit = { ...lit, ...Object.fromEntries(fresh.map((s) => [s.name, true])) };
      return finish(true);
    }
    fresh.forEach((s, k) => {
      booked.add(s.name);
      timers.push(window.setTimeout(() => {
        booked.delete(s.name);
        lit = { ...lit, [s.name]: true };
        if (heard) play("rise", { p: steps.indexOf(s) / Math.max(1, steps.length - 1) });
      }, k * GAP_MS));
    });
    // The finish comes as the last segment settles.
    timers.push(window.setTimeout(() => finish(), (fresh.length - 1) * GAP_MS + 420));
  }

  function finish(quiet = false) {
    if (complete || !steps.every((s) => s.optional || (s.done && lit[s.name]))) return;
    complete = true;
    if (heard && !quiet) play("done");
  }

  /** How many are shown in place, for the count beside the bar: it counts up as they light. */
  const litCount = $derived(steps.filter((s) => s.done && lit[s.name]).length);
  const doneCount = $derived(steps.filter((s) => s.done).length);
</script>

<div class="rh">
  <section class="rh-hero is-{tone}" class:is-complete={complete} bind:this={hero}>
    <div class="rh-markwrap" aria-hidden="true">
      <span class="rh-ring"></span>
      <span class="settings-mark is-social is-{platform} rh-mark" style="--tone: {brand.tone}">
        <Icon name={brand.icon} size={30} />
      </span>
    </div>
    <div class="min-w-0 flex-1">
      <h3 class="rh-title">{title}</h3>
      <p class="rh-sub">{sub}</p>
      <div class="rh-meter" aria-label="{doneCount} of {steps.length} in place">
        <span class="rh-bar">
          {#each steps as s (s.name)}
            <span class="rh-seg" class:is-lit={s.done && lit[s.name]} class:is-working={s.working}></span>
          {/each}
          <i class="rh-shine" aria-hidden="true"></i>
        </span>
        {#key litCount}<b class="rh-count">{litCount}/{steps.length}</b>{/key}
      </div>
    </div>
    <div class="rh-action">
      {#if action}
        {@render action()}
      {:else if go?.href}
        <a class="rh-go" href={go.href} onclick={() => { play("open"); go?.onclick?.(); }}>{go.label} <Icon name="chevron" size={11} /></a>
      {:else if go}
        <button type="button" class="rh-go" onclick={go.onclick}>{go.label} <Icon name="chevron" size={11} /></button>
      {:else if ready}
        <span class="rh-ready"><Icon name="check" size={13} />Ready</span>
      {/if}
    </div>
  </section>

  {@render children?.()}

  <!-- What it needs, ticked off in order, joined where they are done. -->
  <ol class="rh-steps" bind:this={list}>
    {#each steps as s, i (s.name)}
      <li class="rh-step" class:is-done={s.done} class:is-working={s.working} class:is-optional={s.optional && !s.done}
          class:is-lit={s.done && lit[s.name]}
          class:is-linked={s.done && lit[s.name] && !!steps[i + 1]?.done && lit[steps[i + 1].name]}>
        <span class="rh-tick" aria-hidden="true">
          {#if s.working}<span class="rh-spin"></span>{:else if s.done}<Icon name="check" size={12} />{:else if s.optional}<Icon name="minus" size={11} />{:else}<Icon name="close" size={11} />{/if}
        </span>
        <div class="min-w-0 flex-1">
          <div class="rh-step-name">{s.name}</div>
          <p class="rh-step-what">{s.what}</p>
        </div>
        <span class="rh-step-shows" title={s.shows}>{s.shows}</span>
      </li>
    {/each}
  </ol>
</div>

<style>
  .rh { display: flex; flex-direction: column; gap: 14px; }

  /* ── The headline ──────────────────────────────────────────────────────── */
  .rh-hero {
    --tone: var(--color-accent);
    position: relative;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 16px;
    overflow: hidden;
    padding: 18px;
    border-radius: 16px;
    border: 1px solid color-mix(in srgb, var(--tone) 22%, var(--color-edge));
    background:
      radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, var(--tone) 12%, transparent), transparent 55%),
      linear-gradient(180deg, rgb(255 255 255 / 0.035), rgb(0 0 0 / 0.12));
    transition: border-color 0.4s ease;
  }
  .rh-hero.is-good { --tone: var(--color-good); }
  .rh-hero.is-warn { --tone: var(--color-warn); }
  .rh-hero.is-bad { --tone: var(--color-bad); }

  .rh-markwrap { position: relative; flex-shrink: 0; width: 54px; height: 54px; }
  .rh-mark { width: 54px; height: 54px; border-radius: 16px; transition: filter 0.4s ease; }
  .rh-hero:not(.is-good) .rh-mark { filter: saturate(0.45) brightness(0.8); }
  /* Ready: a slow ring breathes out from it, starting with the finish. */
  .rh-ring {
    position: absolute;
    inset: -5px;
    border-radius: 21px;
    border: 1.5px solid color-mix(in srgb, var(--color-good) 50%, transparent);
    opacity: 0;
  }
  .rh-hero.is-good.is-complete .rh-ring { animation: rh-ring 2.8s ease-out infinite; }
  @keyframes rh-ring { 0% { opacity: 0.7; transform: scale(0.92); } 100% { opacity: 0; transform: scale(1.25); } }
  /* The finish: the mark hops, with the bell. */
  .rh-hero.is-complete .rh-markwrap { animation: rh-hop 0.62s var(--jelly); }
  @keyframes rh-hop {
    0% { transform: none; }
    30% { transform: translateY(-5px) scale(1.06) rotate(-4deg); }
    60% { transform: translateY(1px) scale(0.98, 1.02); }
    100% { transform: none; }
  }
  .rh-title { font-size: 16px; font-weight: 700; letter-spacing: -0.01em; color: var(--color-ink); }
  .rh-sub { margin-top: 2px; font-size: 12px; color: var(--color-muted); }

  /* The bar: a segment for each part, filling from the left as it lights, a shine along them all at the finish, and
     the count beside it counting up. */
  .rh-meter { display: flex; align-items: center; gap: 10px; margin-top: 11px; }
  /* Nothing clipped: the shine fades in and out on its own, and cut off by the bar it had flat edges. */
  .rh-bar { position: relative; display: flex; gap: 4px; padding: 2px 0; }
  .rh-seg {
    position: relative;
    width: 36px;
    height: 6px;
    overflow: hidden;
    border-radius: 999px;
    background: rgb(255 255 255 / 0.08);
    transition: box-shadow 0.5s ease;
  }
  .rh-seg::before {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: inherit;
    background: var(--color-good);
    transform: scaleX(0);
    transform-origin: left center;
    transition: transform 0.46s cubic-bezier(0.22, 1.2, 0.36, 1);
  }
  .rh-seg.is-lit::before { transform: scaleX(1); }
  .rh-seg.is-lit { box-shadow: 0 0 10px -2px color-mix(in srgb, var(--color-good) 70%, transparent); }
  .rh-seg.is-working {
    background: linear-gradient(90deg, rgb(255 255 255 / 0.08), var(--color-accent), rgb(255 255 255 / 0.08));
    background-size: 200% 100%;
    animation: rh-shimmer 1.2s linear infinite;
  }
  @keyframes rh-shimmer { to { background-position: -200% 0; } }
  .rh-shine {
    position: absolute;
    top: -5px;
    left: 0;
    width: 26px;
    height: 20px;
    opacity: 0;
    pointer-events: none;
    border-radius: 50%;
    background: radial-gradient(closest-side, rgb(255 255 255 / 0.8), rgb(255 255 255 / 0.28) 55%, transparent);
    filter: blur(3px);
    mix-blend-mode: screen;
  }
  .rh-hero.is-complete .rh-shine { animation: rh-shine 0.9s cubic-bezier(0.35, 0.2, 0.25, 1); }
  @keyframes rh-shine {
    0% { opacity: 0; transform: translateX(-30px); }
    18% { opacity: 1; }
    80% { opacity: 1; }
    100% { opacity: 0; transform: translateX(165px); }
  }
  .rh-count {
    font-size: 11px;
    font-weight: 700;
    color: var(--color-faint);
    font-variant-numeric: tabular-nums;
    animation: rh-count 0.36s var(--jelly);
    transition: color 0.3s ease;
  }
  @keyframes rh-count { from { transform: translateY(4px) scale(0.8); opacity: 0.4; } }
  .rh-hero.is-complete .rh-count { color: var(--color-good); }
  .rh-action { flex-shrink: 0; }
  /* The tinted button, as a link when it goes somewhere. */
  .rh-go {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 7px 12px;
    border-radius: 10px;
    font-size: 12.5px;
    font-weight: 600;
    white-space: nowrap;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 16%, transparent);
    transition: background-color 0.15s var(--swift);
  }
  .rh-go:hover { background: color-mix(in srgb, var(--color-accent) 24%, transparent); }
  /* Ready: waiting, a little faded, while the parts light; it springs in with the finish. */
  .rh-ready {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border-radius: 999px;
    font-size: 12.5px;
    font-weight: 650;
    color: var(--color-good);
    background: color-mix(in srgb, var(--color-good) 12%, transparent);
    opacity: 0.35;
    transform: scale(0.92);
    transition: opacity 0.25s ease, transform 0.25s ease;
  }
  .rh-hero.is-complete .rh-ready { opacity: 1; transform: none; animation: rh-ready 0.6s var(--jelly); }
  @keyframes rh-ready { 0% { transform: scale(0.8); } 45% { transform: scale(1.1); } 100% { transform: none; } }

  /* ── The parts ─────────────────────────────────────────────────────────── */
  .rh-steps { display: flex; flex-direction: column; padding: 4px 2px; }
  .rh-step { position: relative; display: flex; align-items: center; gap: 12px; padding: 9px 0; }
  /* The line down to the next part, lit when both ends are done. */
  .rh-step:not(:last-child)::after {
    content: "";
    position: absolute;
    left: 12px;
    top: 36px;
    bottom: -10px;
    width: 2px;
    border-radius: 2px;
    background: rgb(255 255 255 / 0.08);
  }
  .rh-step:not(:last-child)::before {
    content: "";
    position: absolute;
    z-index: 1;                /* over the grey track (::after), under the tick, which comes after it */
    left: 12px;
    top: 36px;
    bottom: -10px;
    width: 2px;
    border-radius: 2px;
    background: linear-gradient(180deg, var(--color-good), color-mix(in srgb, var(--color-good) 55%, transparent));
    transform: scaleY(0);
    transform-origin: top center;
    transition: transform 0.4s cubic-bezier(0.3, 0.8, 0.3, 1);
  }
  .rh-step.is-linked::before { transform: scaleY(1); }
  .rh-tick {
    position: relative;
    z-index: 1;
    display: grid;
    width: 26px;
    height: 26px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    color: var(--color-bad);
    background: color-mix(in srgb, var(--color-bad) 14%, var(--color-surface));
  }
  .rh-step.is-optional .rh-tick { color: var(--color-faint); background: color-mix(in srgb, var(--color-faint) 14%, var(--color-surface)); }
  /* In place, not lit yet: a quiet tick, waiting its turn. Lit: it pops green, with its segment of the bar. */
  .rh-step.is-done .rh-tick {
    color: color-mix(in srgb, var(--color-good) 70%, var(--color-muted));
    background: color-mix(in srgb, var(--color-good) 10%, var(--color-surface));
    transform: scale(0.88);
    transition: transform 0.3s ease, background-color 0.3s ease, color 0.3s ease;
  }
  .rh-step.is-lit .rh-tick {
    color: #06240f;
    background: var(--color-good);
    transform: none;
    animation: rh-tick 0.5s var(--jelly);
  }
  @keyframes rh-tick { 0% { transform: scale(0.5); } 55% { transform: scale(1.18); } 100% { transform: none; } }
  .rh-step.is-working .rh-tick { color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 14%, var(--color-surface)); }
  .rh-spin { width: 12px; height: 12px; border-radius: 999px; border: 2px solid currentColor; border-right-color: transparent; animation: rh-spin 0.8s linear infinite; }
  @keyframes rh-spin { to { transform: rotate(360deg); } }
  .rh-step-name { font-size: 13px; font-weight: 600; color: var(--color-ink); }
  .rh-step-what { margin-top: 1px; font-size: 11.5px; color: var(--color-faint); }
  .rh-step-shows {
    max-width: 42%;
    overflow: hidden;
    padding: 3px 8px;
    border-radius: 8px;
    font-family: ui-monospace, monospace;
    font-size: 10.5px;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--color-bad);
    background: rgb(0 0 0 / 0.22);
  }
  .rh-step.is-optional .rh-step-shows { color: var(--color-faint); }
  .rh-step.is-done .rh-step-shows { color: var(--color-good); }
  .rh-step.is-working .rh-step-shows { color: var(--color-accent); }

  :global(:root[data-motion="off"]) .rh-ring,
  :global(:root[data-motion="off"]) .rh-markwrap,
  :global(:root[data-motion="off"]) .rh-shine,
  :global(:root[data-motion="off"]) .rh-count,
  :global(:root[data-motion="off"]) .rh-ready,
  :global(:root[data-motion="off"]) .rh-tick,
  :global(:root[data-motion="off"]) .rh-seg { animation: none !important; }
</style>
