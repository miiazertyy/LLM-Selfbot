<script lang="ts">
  /**
   * A list of personas to pick from, opening from whatever was pressed: an
   * account's persona chip, "Use it on another account", the persona pill on
   * Pictures, Memory and Settings. Drawn at the end of the page so no card's
   * own layer paints over it; under the thing pressed, or above it when there
   * is no room below. Its rows come in one after another, the picked one
   * marked.
   */
  import { tick } from "svelte";
  import Icon from "../components/Icon.svelte";
  import PersonaOrb from "./PersonaOrb.svelte";
  import { accountLabel, colorOf, type Persona } from "./logic";
  import { play } from "../uisound";

  let {
    open = $bindable(false),
    anchor,
    list,
    selected = "",
    everyone = false,
    title = "",
    footer = null,
    onpick,
  }: {
    open?: boolean;
    anchor: HTMLElement | null;
    list: Persona[];
    selected?: string;
    /** A row for everyone's settings above the personas (Settings), picked as "". */
    everyone?: boolean;
    title?: string;
    footer?: { label: string; icon?: string; onclick: () => void } | null;
    onpick: (pid: string) => void;
  } = $props();

  let menu: HTMLElement | null = $state(null);
  let pos = $state({ left: 0, top: 0, up: false, width: 260 });

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  async function place() {
    if (!anchor) return;
    const r = anchor.getBoundingClientRect();
    const width = 268;
    const rows = list.length + (everyone ? 1 : 0);
    const tall = Math.min(380, rows * 50 + (title ? 34 : 0) + (footer ? 44 : 0) + 12);
    const up = window.innerHeight - r.bottom < tall + 16 && r.top > window.innerHeight - r.bottom;
    pos = {
      width,
      up,
      left: Math.max(8, Math.min(r.left, window.innerWidth - width - 8)),
      top: up ? r.top - 8 : r.bottom + 8,
    };
    await tick();
  }

  $effect(() => {
    if (!open) return;
    place();
    const off = (e: MouseEvent) => {
      const t = e.target as Node;
      if (menu && !menu.contains(t) && !(anchor && anchor.contains(t))) open = false;
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        open = false;
      }
    };
    const shut = () => (open = false);
    const t = setTimeout(() => {
      window.addEventListener("click", off);
      window.addEventListener("scroll", shut, true);
    }, 0);
    window.addEventListener("keydown", esc, true);
    window.addEventListener("resize", shut);
    return () => {
      clearTimeout(t);
      window.removeEventListener("click", off);
      window.removeEventListener("scroll", shut, true);
      window.removeEventListener("keydown", esc, true);
      window.removeEventListener("resize", shut);
    };
  });

  function pick(pid: string) {
    play("select");
    open = false;
    if (pid !== selected) onpick(pid);
  }
</script>

{#if open}
  <div class="pm glass floating" class:is-up={pos.up} bind:this={menu} use:portal role="listbox" data-sound="self"
       aria-label={title || "Personas"} tabindex="-1"
       style="left: {pos.left}px; {pos.up ? `bottom: ${window.innerHeight - pos.top}px` : `top: ${pos.top}px`}; width: {pos.width}px">
    {#if title}<div class="pm-title">{title}</div>{/if}
    <div class="pm-list">
      {#if everyone}
        <button type="button" role="option" class="pm-row" class:is-on={selected === ""} aria-selected={selected === ""}
                style="--i: 0; --pc: var(--color-accent)" onclick={() => pick("")}>
          <span class="pm-all"><Icon name="accounts" size={14} /></span>
          <span class="pm-text"><b>Everyone</b><small>What every profile starts from</small></span>
          {#if selected === ""}<span class="pm-check"><Icon name="check" size={13} /></span>{/if}
        </button>
      {/if}
      {#each list as p, i (p.id)}
        {@const on = p.id === selected}
        <button type="button" role="option" class="pm-row" class:is-on={on} aria-selected={on}
                style="--i: {i + (everyone ? 1 : 0)}; --pc: {colorOf(p)}" onclick={() => pick(p.id)}>
          <PersonaOrb {p} size={28} ring={false} />
          <span class="pm-text">
            <b>{p.name}</b>
            <small>{p.accounts.length ? p.accounts.map(accountLabel).join(", ") : (p.line || "No accounts")}</small>
          </span>
          {#if on}<span class="pm-check"><Icon name="check" size={13} /></span>{/if}
        </button>
      {/each}
    </div>
    {#if footer}
      <button type="button" class="pm-foot" onclick={() => { open = false; footer?.onclick(); }}>
        <Icon name={footer.icon ?? "persona"} size={12} /> {footer.label}
      </button>
    {/if}
  </div>
{/if}

<style>
  .pm {
    position: fixed;
    z-index: 120;
    display: flex;
    max-height: 380px;
    flex-direction: column;
    overflow: hidden;
    padding: 6px;
    border-radius: 16px;
    transform-origin: top left;
    animation: pm-in 0.26s var(--jelly);
    box-shadow: 0 24px 60px -18px rgb(0 0 0 / 0.65), inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 90%, transparent);
  }
  .pm.is-up { transform-origin: bottom left; }
  @keyframes pm-in { from { opacity: 0; transform: scale(0.94) translateY(-4px); } }
  .pm-title {
    padding: 6px 8px 8px;
    font-size: 10.5px;
    font-weight: 650;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--color-faint);
  }
  .pm-list { display: flex; flex-direction: column; gap: 2px; overflow-y: auto; }
  .pm-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 8px;
    border-radius: 11px;
    text-align: left;
    animation: pm-row 0.3s var(--jelly) backwards;
    animation-delay: calc(var(--i) * 30ms);
    transition: background-color 0.15s ease;
  }
  @keyframes pm-row { from { opacity: 0; transform: translateX(-6px); } }
  .pm-row:hover { background: rgb(255 255 255 / 0.06); }
  .pm-row.is-on { background: color-mix(in srgb, var(--pc) 14%, transparent); }
  .pm-text { display: flex; min-width: 0; flex: 1; flex-direction: column; }
  .pm-text b { overflow: hidden; font-size: 13px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; color: var(--color-ink); }
  .pm-text small { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; color: var(--color-faint); }
  .pm-check { display: grid; color: var(--pc); }
  .pm-all {
    display: grid;
    width: 28px;
    height: 28px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .pm-foot {
    display: flex;
    align-items: center;
    gap: 7px;
    margin-top: 4px;
    padding: 9px 10px;
    border-top: 1px solid color-mix(in srgb, var(--color-edge) 70%, transparent);
    font-size: 12px;
    color: var(--color-muted);
    transition: color 0.15s ease;
  }
  .pm-foot:hover { color: var(--color-ink); }
  :global(:root[data-motion="off"]) .pm,
  :global(:root[data-motion="off"]) .pm-row { animation: none; }
</style>
