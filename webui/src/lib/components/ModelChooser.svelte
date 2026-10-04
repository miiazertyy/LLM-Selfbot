<script lang="ts">
  /**
   * Pick a model for one job, from a dropdown under the button you clicked.
   *
   * This was a full-screen dialog with the providers down one side and one
   * provider's models on the other, so seeing what else you had meant clicking
   * through providers one at a time. Now every connected provider is a group in
   * one list, with its models under it, narrowed to the ones that can do the
   * job. Search runs across all of them. Providers that are not connected yet
   * sit at the bottom, free ones first, with their key box one click away.
   */
  import { tick } from "svelte";
  import { settingsSection, toast } from "../stores";
  import { api } from "../api";
  import {
    loadModels, modelLists, providerList, shortModel,
    type Entry, type Job, type ModelInfo, type Provider,
  } from "../providers";
  import Icon from "./Icon.svelte";
  import { focusStill, showInList } from "../inlist";
  import KeyForm from "./KeyForm.svelte";
  import ProviderTile from "./ProviderTile.svelte";
  import CostTag from "./CostTag.svelte";

  let {
    open = $bindable(false),
    anchor = null,
    need,
    title,
    current = null,
    exclude = [],
    onpick,
  }: {
    open?: boolean;
    /** The button it drops down from. */
    anchor?: HTMLElement | null;
    need: Job;
    title: string;
    current?: Entry | null;
    /** Entries already in use elsewhere (the reply chain), not offered again. */
    exclude?: Entry[];
    onpick: (e: Entry) => void;
  } = $props();

  const COST_ORDER: Record<string, number> = { free: 0, some: 1, paid: 2 };
  const PER_GROUP = 6;

  const able = $derived($providerList.filter((p) => p.jobs.includes(need)));
  const connected = $derived(
    able.filter((p) => p.ready).sort((a, b) =>
      (b.id === current?.provider ? 1 : 0) - (a.id === current?.provider ? 1 : 0)),
  );
  const offline = $derived(
    able.filter((p) => !p.ready).sort((a, b) => (COST_ORDER[a.cost] ?? 3) - (COST_ORDER[b.cost] ?? 3)),
  );

  let query = $state("");
  let showAll = $state(false);
  let more = $state<Record<string, boolean>>({});
  let connecting = $state("");
  let active = $state(0);
  let menu: HTMLElement | null = $state(null);
  let search: HTMLInputElement | null = $state(null);
  let pos = $state({ left: 0, top: 0 as number | null, bottom: null as number | null, width: 400, maxH: 460 });

  const CAP: Record<string, string> = { chat: "writes", vision: "sees", stt: "hears", tts: "speaks" };

  function place() {
    if (!anchor) return;
    const r = anchor.getBoundingClientRect();
    const width = Math.min(410, window.innerWidth - 24);
    let left = r.right - width;
    if (left < 12) left = Math.max(12, Math.min(r.left, window.innerWidth - width - 12));
    const below = window.innerHeight - r.bottom - 14;
    const above = r.top - 14;
    const up = below < 340 && above > below;
    pos = {
      left, width,
      top: up ? null : r.bottom + 6,
      bottom: up ? window.innerHeight - r.top + 6 : null,
      maxH: Math.max(240, Math.min(500, (up ? above : below) - 6)),
    };
  }

  $effect(() => {
    if (!open) return;
    query = "";
    showAll = false;
    more = {};
    connecting = "";
    active = 0;
    place();
    for (const p of connected) loadModels(p.id);
    // Focused without the page scrolling to it: a scroll under it closes it (below).
    tick().then(() => focusStill(search));
  });

  // Closed by a click elsewhere, Escape, a resize, or the page scrolling under it.
  $effect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      const t = e.target as Node;
      if (menu?.contains(t) || anchor?.contains(t)) return;
      open = false;
    };
    const scroll = (e: Event) => { if (!menu?.contains(e.target as Node)) open = false; };
    const resize = () => (open = false);
    const t = setTimeout(() => {
      window.addEventListener("pointerdown", outside, true);
      window.addEventListener("scroll", scroll, true);
      window.addEventListener("resize", resize);
    }, 0);
    return () => {
      clearTimeout(t);
      window.removeEventListener("pointerdown", outside, true);
      window.removeEventListener("scroll", scroll, true);
      window.removeEventListener("resize", resize);
    };
  });

  const taken = (pid: string, m: string) =>
    exclude.some((e) => e.provider === pid && e.model === m) && !(current?.provider === pid && current?.model === m);

  type Row = { pid: string; model: string; custom?: boolean; info?: ModelInfo };

  /** Each connected provider's rows, as shown: filtered, searched, capped. */
  const groups = $derived.by(() => {
    const q = query.trim().toLowerCase();
    return connected.map((p) => {
      const list = $modelLists[p.id];
      const all = list?.models ?? [];
      const fit = showAll ? all : all.filter((m) => m.capabilities.includes(need));
      const hits = q ? fit.filter((m) => m.id.toLowerCase().includes(q)) : fit;
      const capped = q || more[p.id] ? hits : hits.slice(0, PER_GROUP);
      const rows: Row[] = capped.map((m) => ({ pid: p.id, model: m.id, info: m }));
      // Anything the list does not have can still be typed in.
      if (q && !all.some((m) => m.id.toLowerCase() === q)) rows.push({ pid: p.id, model: query.trim(), custom: true });
      return { p, rows, hidden: hits.length - capped.length, loading: !!list?.loading && !all.length, error: list?.error && !all.length ? list.error : "" };
    });
  });

  const flat = $derived(groups.flatMap((g) => g.rows).filter((r) => !taken(r.pid, r.model)));

  function pick(r: Row) {
    if (taken(r.pid, r.model)) return;
    const e: Entry = { provider: r.pid, model: r.model };
    // Which voice it speaks with is a Settings question (AI behaviour), not a
    // model-picker one; whatever is already set is carried across a change of model.
    if (need === "tts" && current?.voice) e.voice = current.voice;
    onpick(e);
    open = false;
    focusStill(anchor);
  }

  async function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") { e.stopPropagation(); open = false; focusStill(anchor); return; }
    if (!flat.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); active = (active + 1) % flat.length; }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = (active - 1 + flat.length) % flat.length; }
    else if (e.key === "Enter") { e.preventDefault(); pick(flat[Math.min(active, flat.length - 1)]); return; }
    else return;
    await tick();
    showInList(menu, menu?.querySelector<HTMLElement>('[data-active="true"]'));
  }
  $effect(() => { query; showAll; active = 0; });

  const isActive = (r: Row) => flat[active] === r || (flat[active]?.pid === r.pid && flat[active]?.model === r.model && flat[active]?.custom === r.custom);
  const isCurrent = (r: Row) => current?.provider === r.pid && current?.model === r.model;
  const freeModel = (p: Provider, id: string) => p.id === "openrouter" && id.endsWith(":free");

  let startingLocal = $state(false);
  async function startLocal() {
    startingLocal = true;
    try {
      const r = await api.localStart();
      if (r?.ok) await loadModels("local", true);
      else toast(r?.reason || "Could not start it", "err");
    } catch (e: any) {
      toast(e?.message || "Could not start it", "err");
    } finally {
      startingLocal = false;
    }
  }

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }
</script>

{#if open}
  <div use:portal bind:this={menu} class="mm glass floating" role="dialog" aria-label={title} tabindex="-1"
       onkeydown={onKey}
       style="left:{pos.left}px;width:{pos.width}px;max-height:{pos.maxH}px;{pos.top !== null ? `top:${pos.top}px` : `bottom:${pos.bottom}px`}"
       class:is-up={pos.top === null}>
    <div class="mm-head">
      <div class="mm-title">{title}</div>
      <div class="mm-search">
        <Icon name="search" size={13} />
        <input bind:this={search} bind:value={query} placeholder="Search every model" spellcheck="false" />
        {#if query}<button class="mm-clear" onclick={() => (query = "")} aria-label="Clear"><Icon name="close" size={11} /></button>{/if}
      </div>
    </div>

    <div class="mm-body">
      {#each groups as g (g.p.id)}
        <div class="mm-group">
          <div class="mm-ghead">
            <ProviderTile id={g.p.id} size={20} />
            <span class="mm-gname">{g.p.name}</span>
            <CostTag cost={g.p.cost} note={g.p.cost_note} small />
            <button class="mm-refresh" title="Ask {g.p.name} for its models again" onclick={() => loadModels(g.p.id, true)}>
              <span class="inline-flex" class:animate-spin={$modelLists[g.p.id]?.loading}><Icon name="refresh" size={11} /></span>
            </button>
          </div>
          {#if g.loading}
            <div class="mm-note"><span class="animate-pulse">Asking {g.p.name} what it has…</span></div>
          {:else if g.error}
            <div class="mm-note is-warn">
              {g.error}
              {#if g.p.id === "local"}
                <button class="mm-link" onclick={startLocal} disabled={startingLocal}>
                  {startingLocal ? "Starting…" : "Start it"}
                </button>
                <button class="mm-link" onclick={() => { open = false; settingsSection.set("groq/local"); }}>Settings</button>
              {/if}
            </div>
          {:else if !g.rows.length}
            <div class="mm-note">{query ? "No match here." : "Nothing here looks able to do this."}</div>
          {/if}
          {#each g.rows as r (r.custom ? `custom:${r.model}` : r.model)}
            <button class="mm-row" class:is-active={isActive(r)} class:is-current={isCurrent(r)}
                    data-active={isActive(r)} disabled={taken(r.pid, r.model)}
                    onmouseenter={() => { const i = flat.indexOf(r); if (i >= 0) active = i; }}
                    onclick={() => pick(r)} title={r.model}>
              {#if r.custom}
                <span class="mm-plus"><Icon name="plus" size={11} /></span>
                <span class="min-w-0 flex-1 truncate">Use “<span class="font-mono">{r.model}</span>”</span>
              {:else}
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-ink">{shortModel(r.model)}</span>
                  {#if shortModel(r.model) !== r.model}<span class="block truncate font-mono text-[10px] text-faint">{r.model}</span>{/if}
                </span>
                {#if taken(r.pid, r.model)}<span class="text-[10.5px] text-faint">in the list</span>{/if}
                {#if freeModel(g.p, r.model)}<CostTag cost="free" small />{/if}
                {#if (r.info?.capabilities ?? []).includes("vision") && need === "chat"}<span class="mm-cap">sees</span>{/if}
                {#if showAll && !(r.info?.capabilities ?? []).includes(need)}
                  <span class="mm-cap is-odd">{(r.info?.capabilities ?? []).map((c) => CAP[c]).filter(Boolean).join(", ") || "unknown"}</span>
                {/if}
                {#if isCurrent(r)}<span class="text-accent"><Icon name="check" size={13} /></span>{/if}
              {/if}
            </button>
          {/each}
          {#if g.hidden > 0}
            <button class="mm-more" onclick={() => (more = { ...more, [g.p.id]: true })}>
              {g.hidden} more from {g.p.name}
            </button>
          {/if}
        </div>
      {/each}

      {#if offline.length}
        <div class="mm-sep">Not connected yet</div>
        {#each offline as p (p.id)}
          <div class="mm-off" class:is-open={connecting === p.id}>
            <button class="mm-offrow" onclick={() => (connecting = connecting === p.id ? "" : p.id)} title={p.cost_note}>
              <ProviderTile id={p.id} size={20} />
              <span class="mm-gname">{p.name}</span>
              <CostTag cost={p.cost} note={p.cost_note} small />
              <span class="mm-connect">{p.id === "local" ? "Set up" : "Connect"}<Icon name="chevron" size={11} /></span>
            </button>
            {#if connecting === p.id}
              <div class="mm-key">
                {#if p.id === "local"}
                  <button class="mm-link" onclick={() => { open = false; settingsSection.set("groq/local"); }}>
                    Find a server on this computer
                  </button>
                {:else}
                  <p class="mb-2 text-[11.5px] text-muted">{p.cost_note}</p>
                  <KeyForm provider={p} label="Connect" compact onsaved={() => { connecting = ""; loadModels(p.id); }} />
                {/if}
              </div>
            {/if}
          </div>
        {/each}
      {/if}
    </div>

    <div class="mm-foot">
      <label class="mm-toggle" title="Every model the provider lists, not only the ones whose name says they can do this">
        <input type="checkbox" bind:checked={showAll} /> Show every model
      </label>
      <span class="ml-auto text-[10.5px] text-faint">↑↓ to move, Enter to pick</span>
    </div>
  </div>
{/if}

<style>
  .mm {
    position: fixed;
    z-index: 60;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border-radius: 16px;
    box-shadow: 0 24px 60px -24px rgb(0 0 0 / 0.85), inset 0 0 0 1px rgb(255 255 255 / 0.06);
    animation: mm-in 0.18s var(--swift) both;
    transform-origin: top right;
  }
  .mm.is-up { transform-origin: bottom right; animation-name: mm-in-up; }
  @keyframes mm-in { from { opacity: 0; transform: translateY(-6px) scale(0.98); } to { opacity: 1; transform: none; } }
  @keyframes mm-in-up { from { opacity: 0; transform: translateY(6px) scale(0.98); } to { opacity: 1; transform: none; } }

  .mm-head { padding: 10px 10px 8px; border-bottom: 1px solid color-mix(in srgb, var(--color-edge) 70%, transparent); }
  .mm-title {
    padding: 0 4px 7px;
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--color-faint);
  }
  .mm-search {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 10px;
    border-radius: 10px;
    color: var(--color-faint);
    background: rgb(0 0 0 / 0.25);
    box-shadow: inset 0 0 0 1px var(--color-edge);
  }
  .mm-search:focus-within { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 55%, transparent); }
  .mm-search input {
    min-width: 0;
    flex: 1;
    background: transparent;
    font-size: 13px;
    color: var(--color-ink);
    outline: none;
  }
  .mm-clear { display: inline-flex; padding: 2px; border-radius: 6px; }
  .mm-clear:hover { color: var(--color-ink); }

  .mm-body { min-height: 0; flex: 1; overflow-y: auto; padding: 4px 6px 6px; }
  .mm-group + .mm-group { margin-top: 4px; }
  .mm-ghead {
    position: sticky;
    top: -4px;
    z-index: 1;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 6px 5px;
    background: color-mix(in srgb, var(--color-card) 94%, transparent);
    backdrop-filter: blur(8px);
  }
  .mm-gname { min-width: 0; flex: 1; overflow: hidden; font-size: 12px; font-weight: 600; color: var(--color-ink); white-space: nowrap; text-overflow: ellipsis; text-align: left; }
  .mm-refresh { display: inline-flex; padding: 4px; border-radius: 7px; color: var(--color-faint); }
  .mm-refresh:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.06); }

  .mm-row {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 8px;
    padding: 6px 8px 6px 34px;
    border-radius: 9px;
    font-size: 12.5px;
    color: var(--color-muted);
    text-align: left;
  }
  .mm-row.is-active:not(:disabled) { background: color-mix(in srgb, var(--color-accent) 14%, transparent); }
  .mm-row.is-current .text-ink { color: var(--color-accent); }
  .mm-row:disabled { opacity: 0.45; cursor: default; }
  .mm-plus {
    display: grid;
    width: 18px;
    height: 18px;
    margin-left: -24px;
    margin-right: 6px;
    place-items: center;
    border-radius: 6px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .mm-cap {
    flex-shrink: 0;
    padding: 0 6px;
    border-radius: 999px;
    font-size: 10px;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.05);
  }
  .mm-cap.is-odd { color: var(--color-warn); background: color-mix(in srgb, var(--color-warn) 10%, transparent); }
  .mm-note { padding: 4px 8px 6px 34px; font-size: 11.5px; color: var(--color-faint); }
  .mm-note.is-warn { color: var(--color-warn); }
  .mm-more { padding: 3px 8px 5px 34px; font-size: 11.5px; color: var(--color-accent); }
  .mm-more:hover { text-decoration: underline; }
  .mm-link { margin-left: 6px; font-size: 11.5px; color: var(--color-accent); }
  .mm-link:hover { text-decoration: underline; }

  .mm-sep {
    margin: 10px 6px 4px;
    padding-top: 10px;
    border-top: 1px solid color-mix(in srgb, var(--color-edge) 70%, transparent);
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--color-faint);
  }
  .mm-off { border-radius: 10px; }
  .mm-off.is-open { background: rgb(255 255 255 / 0.03); }
  .mm-offrow {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 8px;
    padding: 6px;
    border-radius: 9px;
    text-align: left;
  }
  .mm-offrow:hover { background: rgb(255 255 255 / 0.04); }
  .mm-offrow .mm-gname { font-weight: 500; color: var(--color-muted); }
  .mm-connect { display: inline-flex; align-items: center; gap: 2px; font-size: 11.5px; color: var(--color-faint); }
  .mm-offrow:hover .mm-connect { color: var(--color-accent); }
  .mm-off.is-open .mm-connect :global(svg) { transform: rotate(90deg); }
  .mm-key { padding: 2px 8px 10px 34px; }

  .mm-foot {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    border-top: 1px solid color-mix(in srgb, var(--color-edge) 70%, transparent);
  }
  .mm-toggle { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--color-muted); cursor: pointer; }
  .mm-toggle input { accent-color: var(--color-accent); }
  :global(:root[data-motion="off"]) .mm { animation: none; }
</style>
