<script lang="ts">
  /**
   * The profile the app is working on, at the top of the sidebar: its face, its name and how many accounts speak as
   * it. Pressed, the profiles to switch to, and a way to the Profiles page. Persona, Pictures, Memory and Settings all
   * follow it (viewPersona), so there is one place to switch rather than a pill on every page. In the rail, its face
   * alone.
   *
   * The card is tinted with the theme, like every button; the profile's own colour is in its face only. Filled with
   * the profile's colour, it stood out of every theme (a blue-grey slab in a purple one, 2026-11-11).
   *
   * Switching is seen and heard: its face pops in, its name slides up, with a soft landing note as the face arrives.
   * A page that can't switch yet (unsaved text) puts it back.
   */
  import { onMount } from "svelte";
  import { viewPersona } from "../stores";
  import { play } from "../uisound";
  import PopupMark from "../components/PopupMark.svelte";
  import PersonaOrb from "./PersonaOrb.svelte";
  import PersonaMenu from "./PersonaMenu.svelte";
  import { personasRes } from "./store";

  let { rail = false }: { rail?: boolean } = $props();

  let open = $state(false);
  let btn: HTMLElement | null = $state(null);
  const list = $derived($personasRes.data.personas);
  const current = $derived(list.find((p) => p.id === $viewPersona) ?? list.find((p) => p.is_default) ?? list[0] ?? null);
  /** Up to two of the others' pictures: there is somewhere to switch to. Real pictures only: a profile with none
   *  showed its initial on a disc there, which read as a picture that had not loaded ("on the right its not the actual
   *  pfp", 2026-11-12). One that fails to load goes too. The arrows beside them say there is a list either way. */
  let unloaded = $state<string[]>([]);            // pictures, by address: a new one is tried again
  const others = $derived(list.filter((p) => p.id !== current?.id && p.avatar && !unloaded.includes(p.avatar)).slice(0, 2));
  const n = $derived(current?.accounts.length ?? 0);
  const line = $derived(n ? `${n} account${n === 1 ? "" : "s"}` : "No accounts yet");

  onMount(() => {
    personasRes.refresh({ maxAge: 15_000 });
  });

  function toggle() {
    play(open ? "menu" : "open");
    open = !open;
  }
  function pick(pid: string) {
    viewPersona.set(pid);
    play("land", { delay: 120 });
  }
  function manage() {
    window.location.hash = "/profiles";
  }
</script>

{#if current}
  <div class="sbp-wrap" class:is-rail={rail}>
    <button type="button" class="sbp" class:is-rail={rail} class:is-open={open} bind:this={btn}
            aria-haspopup="listbox" aria-expanded={open} aria-label="Profile: {current.name}. Switch"
            title={rail ? `${current.name}. Switch profile` : "Switch profile"} data-sound="self" onclick={toggle}>
      {#key current.id}
        <span class="sbp-face"><PersonaOrb p={current} size={rail ? 30 : 34} ring={false} /></span>
      {/key}
      {#if !rail}
        <span class="sbp-text">
          {#key current.id}<b class="sbp-name">{current.name}</b>{/key}
          <small class="sbp-line">{line}</small>
        </span>
        {#if others.length}
          <span class="sbp-others" aria-hidden="true">
            {#each others as p (p.id)}<span class="sbp-other"><img src={p.avatar} alt="" draggable="false"
                 onerror={() => (unloaded = [...unloaded, p.avatar])} /></span>{/each}
          </span>
        {/if}
        <PopupMark class="sbp-mark" />
      {/if}
    </button>
  </div>
  <PersonaMenu bind:open anchor={btn} {list} selected={current.id} title="Profiles"
               footer={{ label: "Manage profiles", icon: "layers", onclick: manage }} onpick={pick} />
{/if}

<style>
  .sbp-wrap { flex-shrink: 0; padding: 4px 8px 10px; }
  .sbp-wrap.is-rail { display: flex; justify-content: center; padding: 4px 0 10px; }

  /* The theme's tint every button has (app.css, the shared ::before): an even fill, deeper and glowing when pointed
     at and while its list is open, nothing round its edge at rest. */
  .sbp {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 9px;
    padding: 7px 10px 7px 7px;
    border-radius: 14px;
    text-align: left;
    color: var(--color-ink);
    transition: transform 0.35s var(--jelly);
  }
  .sbp:active { transform: scale(0.97); }
  .sbp.is-open::before { --d3-lit: 1; }
  .sbp.is-rail { width: 40px; height: 40px; justify-content: center; padding: 0; border-radius: 13px; }

  .sbp-face { display: grid; flex-shrink: 0; animation: sbp-face 0.5s var(--jelly); }
  .sbp-text { display: flex; min-width: 0; flex: 1; flex-direction: column; line-height: 1.2; }
  .sbp-name {
    overflow: hidden;
    font-size: 14px;
    font-weight: 650;
    text-overflow: ellipsis;
    white-space: nowrap;
    animation: sbp-name 0.38s var(--swift);
  }
  .sbp-line { overflow: hidden; font-size: 11px; color: var(--color-faint); text-overflow: ellipsis; white-space: nowrap; }
  .sbp-others { display: inline-flex; flex-shrink: 0; padding-left: 5px; }
  .sbp-other {
    display: grid;
    margin-left: -5px;
    border-radius: 999px;
    box-shadow: 0 0 0 1.5px color-mix(in srgb, var(--color-accent) 9%, var(--color-surface));
    transition: transform 0.35s var(--jelly);
  }
  .sbp-other img { width: 15px; height: 15px; border-radius: 999px; object-fit: cover; }
  .sbp:hover .sbp-other:last-child, .sbp.is-open .sbp-other:last-child { transform: translateX(3px); }
  .sbp :global(.sbp-mark) { flex-shrink: 0; color: color-mix(in srgb, var(--color-accent) 45%, var(--color-faint)); }

  @keyframes sbp-face { from { opacity: 0; transform: scale(0.55) rotate(-25deg); } }
  @keyframes sbp-name { from { opacity: 0; transform: translateY(6px); } }

  :global(:root[data-motion="off"]) .sbp,
  :global(:root[data-motion="off"]) .sbp-other { transition: none; }
  :global(:root[data-motion="off"]) .sbp-face,
  :global(:root[data-motion="off"]) .sbp-name { animation: none; }
</style>
