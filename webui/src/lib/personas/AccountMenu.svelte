<script lang="ts">
  /**
   * The accounts to give a persona to, each with the persona it speaks as now:
   * "Use it on another account" on the Personas page. Drawn at the end of the
   * page, under what was pressed.
   */
  import { tick } from "svelte";
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import { accountLabel, colorOf, personaOf, type PersonaList } from "./logic";
  import { play } from "../uisound";

  type Face = { name: string; avatar: string; platform: string };

  let {
    open = $bindable(false),
    anchor,
    data,
    faces,
    persona,
    onpick,
  }: {
    open?: boolean;
    anchor: HTMLElement | null;
    data: PersonaList;
    faces: Record<string, Face>;
    /** The persona being given: its own accounts are left out. */
    persona: string;
    onpick: (webId: string) => void;
  } = $props();

  let menu: HTMLElement | null = $state(null);
  let pos = $state({ left: 0, top: 0, up: false });
  const others = $derived(Object.keys(data.accounts).filter((a) => data.accounts[a] !== persona));

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  $effect(() => {
    if (!open || !anchor) return;
    const r = anchor.getBoundingClientRect();
    const tall = Math.min(340, others.length * 52 + 50);
    const up = window.innerHeight - r.bottom < tall + 16 && r.top > window.innerHeight - r.bottom;
    pos = { left: Math.max(8, Math.min(r.left, window.innerWidth - 280)), top: up ? r.top - 8 : r.bottom + 8, up };
    void tick();
    const off = (e: MouseEvent) => {
      const t = e.target as Node;
      if (menu && !menu.contains(t) && !anchor?.contains(t)) open = false;
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && (open = false);
    const shut = () => (open = false);
    const t = setTimeout(() => {
      window.addEventListener("click", off);
      window.addEventListener("scroll", shut, true);
    }, 0);
    window.addEventListener("keydown", esc);
    window.addEventListener("resize", shut);
    return () => {
      clearTimeout(t);
      window.removeEventListener("click", off);
      window.removeEventListener("scroll", shut, true);
      window.removeEventListener("keydown", esc);
      window.removeEventListener("resize", shut);
    };
  });

  function pick(webId: string) {
    play("select");
    open = false;
    onpick(webId);
  }
</script>

{#if open}
  <div class="am glass floating" class:is-up={pos.up} bind:this={menu} use:portal role="listbox" tabindex="-1"
       aria-label="Accounts" data-sound="self"
       style="left: {pos.left}px; {pos.up ? `bottom: ${window.innerHeight - pos.top}px` : `top: ${pos.top}px`}">
    <div class="am-title">Move here</div>
    {#if others.length}
      {#each others as a, i (a)}
        {@const f = faces[a]}
        {@const now = personaOf(data, a)}
        <button type="button" role="option" aria-selected="false" class="am-row" style="--i: {i}" onclick={() => pick(a)}>
          <Avatar src={f?.avatar ?? ""} name={f?.name || accountLabel(a)} size={28} zoom={false}
                  silhouette={f?.platform === "snapchat" && !f?.avatar} />
          <span class="am-text">
            <b>{f?.name || accountLabel(a)}</b>
            <small>
              <Icon name={a.startsWith("snapchat") ? "snapchat" : "discord"} size={10} /> {accountLabel(a)}
              {#if now}· now <i style="color: {colorOf(now)}">{now.name}</i>{/if}
            </small>
          </span>
        </button>
      {/each}
    {:else}
      <p class="am-none">Every account is on it already.</p>
    {/if}
  </div>
{/if}

<style>
  .am {
    position: fixed;
    z-index: 120;
    display: flex;
    width: 272px;
    max-height: 340px;
    flex-direction: column;
    gap: 2px;
    overflow-y: auto;
    padding: 6px;
    border-radius: 16px;
    animation: am-in 0.26s var(--jelly);
    box-shadow: 0 24px 60px -18px rgb(0 0 0 / 0.65), inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 90%, transparent);
  }
  @keyframes am-in { from { opacity: 0; transform: scale(0.94) translateY(-4px); } }
  .am-title { padding: 6px 8px 8px; font-size: 10.5px; font-weight: 650; letter-spacing: 0.12em; text-transform: uppercase; color: var(--color-faint); }
  .am-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 8px;
    border-radius: 11px;
    text-align: left;
    animation: am-row 0.3s var(--jelly) backwards;
    animation-delay: calc(var(--i) * 30ms);
    transition: background-color 0.15s ease;
  }
  @keyframes am-row { from { opacity: 0; transform: translateX(-6px); } }
  .am-row:hover { background: rgb(255 255 255 / 0.06); }
  .am-text { display: flex; min-width: 0; flex: 1; flex-direction: column; }
  .am-text b { overflow: hidden; font-size: 13px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; color: var(--color-ink); }
  .am-text small { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; color: var(--color-faint); }
  .am-text i { font-style: normal; font-weight: 600; }
  .am-none { padding: 6px 8px 10px; font-size: 12px; color: var(--color-muted); }
  :global(:root[data-motion="off"]) .am,
  :global(:root[data-motion="off"]) .am-row { animation: none; }
</style>
