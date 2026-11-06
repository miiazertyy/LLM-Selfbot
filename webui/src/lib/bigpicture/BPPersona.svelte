<script lang="ts">
  /**
   * Persona: who the bot is. Its face, the name it is told it has, and the opening
   * of its persona, written in a line at a time, the words every reply starts from
   * (scenes.ts picks them out of the instructions).
   *
   * Under it, the mood each account speaking as this persona is in, and every mood
   * it can be put in: a press switches it, so how it talks can be changed without
   * leaving the big screen.
   */
  import { cubicOut } from "svelte/easing";
  import { get } from "svelte/store";
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import { bigPictureExit, motionEnabled } from "../stores";
  import BPWho from "./BPWho.svelte";
  import { fitText } from "./fit";
  import { focusable } from "./focus";
  import { popIn } from "./motion";
  import type { BPAccount, PageActions } from "./types";
  import type { World } from "./world.svelte";

  let {
    world,
    act,
    name = "",
    face = null,
    speakers = [],
    choices = [],
    current = "",
    onwho,
  }: {
    world: World;
    act: PageActions;
    /** The name the persona gives it, or the account's own. */
    name?: string;
    /** Whose picture. */
    face?: BPAccount | null;
    /** The accounts speaking as this persona. */
    speakers?: BPAccount[];
    choices?: { account: BPAccount; persona: string; name: string }[];
    current?: string;
    onwho?: (accountId: string) => void;
  } = $props();

  const lines = $derived(world.personaLines);
  /** Only an account that answers can be put in a mood. */
  const reachable = $derived(speakers.filter((a) => a.state === "running" && a.live));

  /** A line writing itself out, left to right. */
  function write(_node: Element, { delay = 0 }: { delay?: number } = {}) {
    if (bigPictureExit.on) return { duration: 0 };
    if (!get(motionEnabled)) return { delay, duration: 200, css: (t: number) => `opacity:${t}` };
    return {
      delay,
      duration: 900,
      easing: cubicOut,
      css: (t: number) => `clip-path: inset(-10% ${((1 - t) * 100).toFixed(1)}% -10% 0); opacity: ${Math.min(1, t * 3)}`,
    };
  }
</script>

<div class="bpz bp-scrolls">
  <div class="bpz-grid">
    <div class="bpz-who">
      <BPWho {choices} {current} onpick={onwho} />
      <span class="bpz-face" in:popIn|global={{ delay: 60, from: 0.84 }}>
        <Avatar src={face?.avatar} name={name || face?.name || "?"} size={148} zoom={false} />
      </span>
      <div class="bpz-name" use:fitText={{ min: 26, text: name }} in:popIn|global={{ delay: 130, from: 0.96 }}>{name || face?.name || "The bot"}</div>
      {#if face?.mood}
        <div class="bpz-now" in:popIn|global={{ delay: 200, from: 0.96 }}>Feeling {face.mood} right now</div>
      {/if}
      <button class="bp-btn is-small" use:focusable={{ id: "persona:edit" }} onclick={() => act.leaveTo("persona")} in:popIn|global={{ delay: 260, from: 0.96 }}>
        <Icon name="edit" size={14} />Edit
      </button>
    </div>

    <div class="bpz-words">
      {#if lines.length}
        <div class="bpz-lines" data-private>
          {#each lines as l, i (l)}
            <p in:write|global={{ delay: 240 + i * 340 }}>{l}</p>
          {/each}
        </div>
      {:else}
        <p class="bpz-none">Nothing written yet.</p>
      {/if}

      {#if reachable.length && world.moods.length}
        <div class="bpz-moods" in:popIn|global={{ delay: 360 + lines.length * 180, from: 0.97 }} data-sound="self">
          {#each reachable as a (a.id)}
            <div class="bpz-row">
              {#if reachable.length > 1}
                <span class="bpz-acct" title={a.name}><Avatar src={a.avatar} name={a.name} size={26} zoom={false} /></span>
              {:else}
                <span class="bp-label bpz-label">Mood</span>
              {/if}
              {#each world.moods as m (m)}
                <button class="bp-chip bpz-chip" class:is-on={a.mood === m} disabled={!!world.busy[a.id] || a.mood === m}
                        use:focusable={{ id: `mood:${a.id}:${m}` }} onclick={(e) => world.setMood(a, m, e.currentTarget)}
                        title={a.mood === m ? `${a.name} is ${m}` : `Put ${a.name} in a ${m} mood`}>{m}</button>
              {/each}
            </div>
          {/each}
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  .bpz { display: flex; height: 100%; min-height: 0; flex-direction: column; justify-content: safe center; container-type: inline-size; padding-bottom: 2vh; }
  .bpz-grid { display: grid; width: min(100%, 1400px); margin-inline: auto; grid-template-columns: minmax(0, 1fr); gap: clamp(18px, 3vw, 72px); align-items: center; }
  @container (min-width: 820px) {
    .bpz-grid { grid-template-columns: minmax(0, 0.72fr) minmax(0, 1.28fr); }
  }
  .bpz-who { display: flex; min-width: 0; flex-direction: column; align-items: flex-start; gap: 10px; }
  .bpz-face { display: grid; margin-top: 6px; border-radius: 999px; }
  .bpz-name {
    width: 100%;
    overflow: hidden;
    font-size: clamp(36px, min(4.4vw, 8vh), 80px);
    font-weight: 750;
    line-height: 1.16;
    padding-block: 0.1em;
    margin-block: -0.1em;
    letter-spacing: -0.035em;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .bpz-now { font-size: clamp(15px, 1.1vw, 20px); font-weight: 600; color: var(--bp-lit); }
  .bpz-words { display: flex; min-width: 0; flex-direction: column; gap: clamp(16px, 3vh, 34px); }
  .bpz-lines { display: flex; flex-direction: column; gap: 9px; }
  .bpz-lines p { font-size: clamp(17px, min(1.5vw, 2.8vh), 28px); line-height: 1.4; color: var(--bp-muted); }
  .bpz-lines p:first-child { font-size: clamp(22px, min(2.2vw, 4vh), 42px); font-weight: 700; line-height: 1.2; letter-spacing: -0.02em; color: var(--color-ink); }
  .bpz-none { font-size: 18px; color: var(--bp-muted); }
  .bpz-moods { display: flex; flex-direction: column; gap: 8px; }
  .bpz-row { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; gap: 5px; }
  .bpz-label { margin-right: 6px; }
  .bpz-acct { display: grid; margin-right: 4px; }
  :global(.bpz-chip) { text-transform: capitalize; }
  @media (max-width: 720px) {
    .bpz { height: auto; }
    .bpz-face :global(img) { max-width: 96px; max-height: 96px; }
  }
</style>
