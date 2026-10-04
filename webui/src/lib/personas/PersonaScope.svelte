<script lang="ts">
  /**
   * Whose this page is: a pill with the persona's face and name, in its colour,
   * on Pictures, Memory and Settings. Pressed, the personas to switch to.
   * Settings adds "Everyone" for the settings every persona starts from.
   */
  import { onMount } from "svelte";
  import Icon from "../components/Icon.svelte";
  import PersonaOrb from "./PersonaOrb.svelte";
  import PersonaMenu from "./PersonaMenu.svelte";
  import { colorOf } from "./logic";
  import { personasRes } from "./store";
  import { play } from "../uisound";

  let {
    value,
    everyone = false,
    label = "",
    onchange,
    shake = false,
  }: {
    value: string;
    everyone?: boolean;
    /** A word before the pill: "Settings for". */
    label?: string;
    onchange: (pid: string) => void;
    /** Shakes it no, for a switch that has to wait (unsaved changes). */
    shake?: boolean;
  } = $props();

  let open = $state(false);
  let pill: HTMLElement | null = $state(null);
  const list = $derived($personasRes.data.personas);
  const current = $derived(list.find((p) => p.id === value) ?? null);

  onMount(() => {
    personasRes.refresh({ maxAge: 15_000 });
  });

  function toggle() {
    if (!open) play("open");
    open = !open;
  }
</script>

<span class="psc">
  {#if label}<span class="psc-label">{label}</span>{/if}
  <button type="button" class="psc-pill" class:is-open={open} class:is-shake={shake} bind:this={pill}
          style="--pc: {value ? colorOf(current) : 'var(--color-accent)'}" aria-haspopup="listbox" aria-expanded={open}
          data-sound="self" onclick={toggle}>
    {#if value && current}
      <PersonaOrb p={current} size={20} ring={false} />
      <span class="psc-name">{current.name}</span>
    {:else}
      <span class="psc-all"><Icon name="accounts" size={11} /></span>
      <span class="psc-name">Everyone</span>
    {/if}
    <span class="psc-chev"><Icon name="chevron" size={11} /></span>
  </button>
</span>
<PersonaMenu bind:open anchor={pill} {list} selected={value} {everyone} title="Profiles" onpick={onchange} />

<style>
  .psc { display: inline-flex; align-items: center; gap: 8px; }
  .psc-label { font-size: 12px; color: var(--color-faint); }
  .psc-pill {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 3px 9px 3px 4px;
    border-radius: 999px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--pc) 13%, rgb(255 255 255 / 0.03));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--pc) 40%, transparent);
    transition: background-color 0.25s var(--swift), box-shadow 0.25s var(--swift), transform 0.35s var(--jelly);
  }
  .psc-pill:hover { background: color-mix(in srgb, var(--pc) 20%, rgb(255 255 255 / 0.03)); }
  .psc-pill:active { transform: scale(0.97); }
  .psc-pill.is-open { box-shadow: inset 0 0 0 1px var(--pc), 0 0 16px -6px var(--pc); }
  .psc-pill.is-shake { animation: psc-no 0.42s ease; }
  @keyframes psc-no { 20%, 60% { transform: translateX(-4px); } 40%, 80% { transform: translateX(4px); } }
  .psc-name { max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .psc-all {
    display: grid;
    width: 20px;
    height: 20px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 16%, transparent);
  }
  .psc-chev { display: grid; color: var(--color-faint); transform: rotate(90deg); transition: transform 0.3s var(--jelly); }
  .psc-pill.is-open .psc-chev { transform: rotate(-90deg); }
  :global(:root[data-motion="off"]) .psc-pill { transition: none; animation: none; }
</style>
