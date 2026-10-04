<script lang="ts">
  /**
   * Making a persona: a name, where it starts from, a colour. Fresh, it starts
   * from the template with its name in; as a copy, from another's text,
   * settings and pictures, and its memory too when asked. The face at the top
   * is the one it will have, changing as you type and pick.
   */
  import { tick } from "svelte";
  import Modal from "../components/Modal.svelte";
  import Button from "../components/Button.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Toggle from "../components/Toggle.svelte";
  import PersonaOrb from "./PersonaOrb.svelte";
  import ColorDots from "./ColorDots.svelte";
  import { nextColor, type Persona } from "./logic";

  let {
    open = $bindable(false),
    list,
    palette,
    copyOf = "",
    busy = false,
    oncreate,
  }: {
    open?: boolean;
    list: Persona[];
    palette: { id: string; name: string; hex: string }[];
    /** Opened as "Duplicate": starts as a copy of this one. */
    copyOf?: string;
    busy?: boolean;
    oncreate: (body: { name: string; color: string; copy_from?: string; copy_memory?: boolean }) => void;
  } = $props();

  let name = $state("");
  let color = $state("");
  let from = $state<"fresh" | "copy">("fresh");
  let source = $state("default");
  let withMemory = $state(false);
  let field: HTMLInputElement | null = $state(null);

  // Each time it opens: a clean form, the next colour nobody has, the name box ready to type in.
  $effect(() => {
    if (!open) return;
    name = "";
    color = nextColor(list, palette);
    from = copyOf ? "copy" : "fresh";
    source = copyOf || list.find((p) => p.is_default)?.id || "default";
    withMemory = false;
    tick().then(() => field?.focus());
  });

  const preview = $derived({ name: name.trim() || "?", color, avatar: "" });
  const sourceName = $derived(list.find((p) => p.id === source)?.name ?? "");
  const ready = $derived(name.trim().length > 0 && !busy);

  function submit() {
    if (!ready) return;
    oncreate({
      name: name.trim(),
      color,
      ...(from === "copy" ? { copy_from: source, copy_memory: withMemory } : {}),
    });
  }
</script>

<Modal bind:open title="New profile">
  <!-- Not a <form>: Button has no type, so every button in one (Cancel too) would send it. Enter in the name does. -->
  <div class="np">
    <div class="np-face" style="--pc: {color}">
      <PersonaOrb p={preview} size={72} spin />
    </div>
    <label class="np-field">
      <span>Name</span>
      <input bind:this={field} bind:value={name} maxlength="40" placeholder="Who is it?" spellcheck="false"
             onkeydown={(e) => { if (e.key === "Enter") submit(); }} />
    </label>
    <div class="np-field">
      <span>Colour</span>
      <ColorDots {palette} value={color} onpick={(hex) => (color = hex)} />
    </div>
    <div class="np-field">
      <span>Start from</span>
      <Segmented label="Start from" value={from}
                 options={[{ id: "fresh", label: "Fresh" }, { id: "copy", label: "Copy" }]}
                 onchange={(id) => (from = id as "fresh" | "copy")} />
    </div>
    {#if from === "copy"}
      <div class="np-copy">
        <div class="np-sources">
          {#each list as p (p.id)}
            <button type="button" class="np-source" class:is-on={source === p.id} style="--pc: {p.color || 'var(--color-accent)'}"
                    onclick={() => (source = p.id)}>
              <PersonaOrb {p} size={22} ring={false} />
              <span>{p.name}</span>
            </button>
          {/each}
        </div>
        <p class="np-note">Its text, settings and pictures come with it.</p>
        <div class="np-row">
          <span>Copy its memory too<small>What {sourceName} knows about people</small></span>
          <Toggle checked={withMemory} onchange={(v: boolean) => (withMemory = v)} name="Copy its memory" />
        </div>
      </div>
    {:else}
      <p class="np-note">Starts from the template with its name in. No pictures or memory yet.</p>
    {/if}
    <div class="np-actions">
      <Button kind="ghost" size="sm" onclick={() => (open = false)}>Cancel</Button>
      <Button size="sm" onclick={submit} disabled={!ready} loading={busy}>Create</Button>
    </div>
  </div>
</Modal>

<style>
  .np { display: flex; flex-direction: column; gap: 14px; }
  .np-face {
    display: grid;
    place-items: center;
    padding: 6px 0 2px;
    background: radial-gradient(40% 80% at 50% 50%, color-mix(in srgb, var(--pc) 22%, transparent), transparent 70%);
    transition: background 0.4s var(--swift);
  }
  .np-field { display: flex; flex-direction: column; gap: 7px; }
  .np-field > span { font-size: 11px; font-weight: 650; letter-spacing: 0.08em; text-transform: uppercase; color: var(--color-faint); }
  .np-field input {
    padding: 10px 12px;
    border-radius: 12px;
    font-size: 15px;
    font-weight: 600;
    color: var(--color-ink);
    background: rgb(0 0 0 / 0.25);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    outline: none;
    transition: box-shadow 0.2s var(--swift);
  }
  .np-field input:focus { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, transparent), 0 0 0 3px color-mix(in srgb, var(--color-accent) 16%, transparent); }
  .np-copy { display: flex; flex-direction: column; gap: 10px; animation: np-in 0.3s var(--jelly); }
  @keyframes np-in { from { opacity: 0; transform: translateY(-4px); } }
  .np-sources { display: flex; flex-wrap: wrap; gap: 6px; }
  .np-source {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 4px 10px 4px 4px;
    border-radius: 999px;
    font-size: 12.5px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06);
    transition: color 0.15s ease, background-color 0.15s ease, box-shadow 0.15s ease;
  }
  .np-source:hover { color: var(--color-ink); }
  .np-source.is-on { color: var(--color-ink); background: color-mix(in srgb, var(--pc) 16%, transparent); box-shadow: inset 0 0 0 1px var(--pc); }
  .np-note { font-size: 12px; line-height: 1.5; color: var(--color-muted); }
  .np-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 13px; color: var(--color-ink); }
  .np-row small { display: block; font-size: 11px; color: var(--color-faint); }
  .np-actions { display: flex; justify-content: flex-end; gap: 8px; padding-top: 4px; }
  :global(:root[data-motion="off"]) .np-copy { animation: none; }
</style>
