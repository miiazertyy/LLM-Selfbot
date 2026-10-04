<script lang="ts">
  /**
   * A timezone, picked from the real list with the time it is there right now,
   * instead of "Europe/Paris" typed from memory.
   *
   * The button is a small live clock showing that zone's time, its city and
   * how far it is from UTC. Opened, it is the full list, searchable by city,
   * region or offset ("paris", "america", "+2"), each with its own time, and
   * this computer's zone one click away. A name that is not a zone this
   * computer knows says so rather than being quietly kept: the runner would
   * fall back to its own clock with it.
   *
   * Every zone carries its country's flag and name, and the country finds it
   * too: "japan" as well as "tokyo".
   */
  import { onMount, tick, untrack } from "svelte";
  import Icon from "./Icon.svelte";
  import { focusStill, showInList } from "../inlist";
  import { allZones, countryName, countryOf, flagOf, localZone, searchZones, validZone, zoneLabel, zoneNow,
           zoneOffset } from "../clock";

  let { value = "", onchange }: { value?: string; onchange?: (v: string) => void } = $props();

  let open = $state(false);
  let q = $state("");
  let active = $state(0);
  let up = $state(false);
  let root: HTMLElement | null = $state(null);
  let list: HTMLElement | null = $state(null);
  let input: HTMLInputElement | null = $state(null);

  let now = $state(new Date());

  /*
   * The hands count on from when the clock was put up, a second at a time,
   * rather than being set from the time of day. Set from the time of day, the
   * minute hand ran back round the whole dial at the top of every hour, and
   * the second hand, turned by the seconds since 1970 so it would not do the
   * same, had an angle too large to draw exactly and jumped about as it swept.
   *
   * `s` is the seconds on this clock's face: the zone's time of day when it
   * was put up, then only ever counted on. Anything that is not the next
   * second (waking from sleep, a background tab the browser stopped timing, a
   * new zone, a clock change) moves the hands straight there without sweeping.
   */
  const daySeconds = (tz: string, d: Date) => {
    const n = zoneNow(tz, d);
    return n ? n.hour * 3600 + n.minute * 60 + n.second : null;
  };
  let s = $state(untrack(() => (validZone(value) ? daySeconds(value, new Date()) ?? 0 : 0)));
  let jump = $state(false);

  function sync(force = false) {
    const d = new Date();
    now = d;
    const truth = validZone(value) ? daySeconds(value, d) : null;
    if (truth == null) return;
    const ahead = (((truth - s) % 86400) + 86400) % 86400;
    if (!force && ahead <= 2) {
      s += ahead;
      return;
    }
    jump = true;
    s = truth;
    requestAnimationFrame(() => requestAnimationFrame(() => (jump = false)));
  }

  onMount(() => {
    // Just after each second turns, so one tick is one second: ticking on a
    // plain interval drifts across the turn, standing still one tick and
    // taking two the next.
    let id = 0;
    const next = () => {
      sync();
      id = window.setTimeout(next, 1000 - (Date.now() % 1000) + 8);
    };
    id = window.setTimeout(next, 1000 - (Date.now() % 1000) + 8);
    return () => clearTimeout(id);
  });
  // A different zone: its time, straight away.
  $effect(() => {
    void value;
    untrack(() => sync(true));
  });

  const zones = allZones();
  const here = localZone();
  const known = $derived(validZone(value));
  const label = $derived(value ? zoneLabel(value) : { city: "Not set", region: "" });
  const cc = $derived(countryOf(value));
  const found = $derived(searchZones(zones, q, now).slice(0, 80));
  /** Where each hand points: a turn a minute, a turn an hour, a turn every twelve hours. */
  const secAngle = $derived(s * 6);
  const minAngle = $derived(s * 0.1);
  const hourAngle = $derived(s / 120);
  /** "France", else the zone's region for the ones in no country ("Etc"). */
  const whereOf = (tz: string) => countryName(countryOf(tz)) || zoneLabel(tz).region;

  const time = (tz: string) => {
    const n = zoneNow(tz, now);
    return n ? `${String(n.hour).padStart(2, "0")}:${String(n.minute).padStart(2, "0")}` : "";
  };

  async function openList() {
    const r = root?.getBoundingClientRect();
    up = !!r && window.innerHeight - r.bottom < 360 && r.top > window.innerHeight - r.bottom;
    q = "";
    open = true;
    await tick();
    active = Math.max(0, found.indexOf(value));
    // The list scrolls to the zone, the page stays where it is (lib/inlist.ts).
    focusStill(input);
    showInList(list, list?.querySelector<HTMLElement>('[data-active="true"]'), "center");
  }
  function choose(tz: string) {
    open = false;
    if (tz !== value) onchange?.(tz);
    focusStill(root?.querySelector<HTMLButtonElement>(".tz-trigger"));
  }
  async function move(by: number) {
    active = Math.max(0, Math.min(found.length - 1, active + by));
    await tick();
    showInList(list, list?.querySelector<HTMLElement>('[data-active="true"]'));
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); open = false; return; }
    if (e.key === "ArrowDown") { e.preventDefault(); move(1); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); move(-1); return; }
    if (e.key === "Enter") { e.preventDefault(); if (found[active]) choose(found[active]); }
  }
  $effect(() => {
    void q;
    active = 0;
  });
  /** A click anywhere else closes it. */
  function outside(e: PointerEvent) {
    if (open && root && !root.contains(e.target as Node)) open = false;
  }
</script>

<svelte:window onpointerdown={outside} />

<div class="tz" bind:this={root}>
  <button type="button" class="tz-trigger" class:is-bad={!!value && !known} onclick={() => (open ? (open = false) : openList())}
          aria-haspopup="listbox" aria-expanded={open}>
    <!-- A little clock, set to that zone's time, its second hand sweeping,
         with the zone's flag on its shoulder. -->
    <span class="tz-dial">
      <svg class="tz-clock" class:is-jumping={jump} viewBox="-20 -20 40 40" aria-hidden="true">
        <circle r="18" class="tz-face" />
        {#each Array(12) as _, i}
          <line y1="-15.5" y2={i % 3 === 0 ? -12.5 : -14} transform="rotate({i * 30})" class="tz-mark" />
        {/each}
        {#if known}
          <line y1="2" y2="-8.5" class="tz-hour" style="transform: rotate({hourAngle}deg)" />
          <line y1="2.5" y2="-13" class="tz-min" style="transform: rotate({minAngle}deg)" />
          <line y1="3.5" y2="-14" class="tz-sec" style="transform: rotate({secAngle}deg)" />
        {/if}
        <circle r="1.6" class="tz-pin" />
      </svg>
      {#if cc}
        {#key cc}<span class="tz-badge flag" aria-hidden="true">{flagOf(cc)}</span>{/key}
      {/if}
    </span>
    <span class="tz-text">
      <span class="tz-city">{label.city}</span>
      <span class="tz-meta">
        {#if known}{time(value)} · {zoneOffset(value, now)}{whereOf(value) ? ` · ${whereOf(value)}` : ""}{:else if value}Not a timezone this computer knows{:else}Pick one{/if}
      </span>
    </span>
    <Icon name="chevron" size={13} class="tz-chev" />
  </button>

  {#if open}
    <div class="tz-pop" class:is-up={up} role="presentation" onkeydown={onKey}>
      <label class="tz-search">
        <Icon name="search" size={13} />
        <input bind:this={input} bind:value={q} placeholder="City, region or offset (+2)" spellcheck="false"
               aria-label="Search timezones" />
      </label>
      {#if here && here !== value}
        <button type="button" class="tz-here" onclick={() => choose(here)}>
          <Icon name="monitor" size={13} />This computer:
          {#if countryOf(here)}<span class="flag tz-here-flag">{flagOf(countryOf(here))}</span>{/if}<b>{zoneLabel(here).city}</b>
          <span class="tz-here-time">{time(here)}</span>
        </button>
      {/if}
      <div class="tz-list" role="listbox" aria-label="Timezones" bind:this={list}>
        {#each found as tz, i (tz)}
          {@const l = zoneLabel(tz)}
          {@const code = countryOf(tz)}
          {@const where = whereOf(tz)}
          <button type="button" role="option" aria-selected={tz === value} data-active={i === active}
                  class="tz-row" class:is-on={tz === value} class:is-active={i === active}
                  onpointerenter={() => (active = i)} onclick={() => choose(tz)}>
            {#if code}
              <span class="tz-row-flag flag" title={where}>{flagOf(code)}</span>
            {:else}
              <span class="tz-row-flag is-none"><Icon name="globe" size={15} /></span>
            {/if}
            <span class="tz-row-name"><b>{l.city}</b>{#if where}<span>{where}</span>{/if}</span>
            <span class="tz-row-off">{zoneOffset(tz, now)}</span>
            <span class="tz-row-time">{time(tz)}</span>
          </button>
        {:else}
          <p class="tz-none">No timezone matches "{q}".</p>
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  .tz { position: relative; width: 100%; max-width: 20rem; }
  .tz-trigger {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 11px;
    padding: 7px 10px 7px 8px;
    border-radius: 12px;
    border: 1px solid var(--color-edge);
    background: rgb(0 0 0 / 0.22);
    text-align: left;
    transition: border-color 0.18s var(--swift), box-shadow 0.18s var(--swift), transform 0.25s var(--spring);
  }
  .tz-trigger:hover { border-color: color-mix(in srgb, var(--color-accent) 45%, var(--color-edge)); }
  .tz-trigger:active { transform: scale(0.985); }
  .tz-trigger:focus-visible { outline: none; box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 22%, transparent); }
  .tz-trigger.is-bad { border-color: color-mix(in srgb, var(--color-warn) 60%, transparent); }
  .tz-dial { position: relative; display: grid; flex-shrink: 0; }
  .tz-clock { width: 38px; height: 38px; overflow: visible; }
  /* The flag, pinned to the clock like a sticker, landing with a little bounce
     when the zone changes to another country. */
  .tz-badge {
    position: absolute;
    right: -5px;
    bottom: -3px;
    font-size: 14px;
    filter: drop-shadow(0 1px 1.5px rgb(0 0 0 / 0.6));
    animation: tz-badge 0.5s var(--jelly) both;
  }
  @keyframes tz-badge { from { transform: scale(0.3) rotate(-25deg); opacity: 0; } }
  .tz-face { fill: rgb(255 255 255 / 0.05); stroke: rgb(255 255 255 / 0.14); stroke-width: 1.2; }
  .tz-mark { stroke: rgb(255 255 255 / 0.3); stroke-width: 1.1; stroke-linecap: round; }
  .tz-hour { stroke: var(--color-ink); stroke-width: 2.4; stroke-linecap: round; transition: transform 1s linear; }
  .tz-min { stroke: var(--color-ink); stroke-width: 1.6; stroke-linecap: round; transition: transform 1s linear; }
  .tz-sec { stroke: var(--color-accent); stroke-width: 1; stroke-linecap: round; transition: transform 1s linear; }
  .tz-clock.is-jumping line { transition: none; }
  .tz-pin { fill: var(--color-accent); }
  .tz-text { display: flex; min-width: 0; flex: 1; flex-direction: column; }
  .tz-city { overflow: hidden; font-size: 13.5px; font-weight: 650; color: var(--color-ink); text-overflow: ellipsis; white-space: nowrap; }
  .tz-meta { overflow: hidden; font-size: 11px; color: var(--color-muted); text-overflow: ellipsis; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .tz-trigger.is-bad .tz-meta { color: var(--color-warn); }
  .tz-trigger :global(.tz-chev) { flex-shrink: 0; color: var(--color-faint); transform: rotate(90deg); }

  .tz-pop {
    position: absolute;
    right: 0;
    top: calc(100% + 6px);
    z-index: 40;
    display: flex;
    width: min(22rem, 90vw);
    flex-direction: column;
    gap: 6px;
    padding: 8px;
    border-radius: 14px;
    border: 1px solid var(--color-edge);
    background: var(--color-surface);
    box-shadow: 0 24px 60px -20px rgb(0 0 0 / 0.65);
    animation: tz-in 0.16s var(--swift) both;
    transform-origin: top right;
  }
  .tz-pop.is-up { top: auto; bottom: calc(100% + 6px); transform-origin: bottom right; }
  @keyframes tz-in { from { opacity: 0; transform: scale(0.96) translateY(-4px); } }
  .tz-search {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 6px 9px;
    border-radius: 9px;
    color: var(--color-faint);
    background: rgb(0 0 0 / 0.25);
  }
  .tz-search input { min-width: 0; flex: 1; font-size: 13px; color: var(--color-ink); background: transparent; outline: none; }
  .tz-here {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 6px 9px;
    border-radius: 9px;
    font-size: 12px;
    color: var(--color-muted);
    text-align: left;
    background: color-mix(in srgb, var(--color-accent) 10%, transparent);
  }
  .tz-here b { color: var(--color-ink); font-weight: 650; }
  .tz-here-flag { font-size: 14px; }
  .tz-here-time { margin-left: auto; font-variant-numeric: tabular-nums; }
  .tz-here:hover { background: color-mix(in srgb, var(--color-accent) 18%, transparent); }
  .tz-list { display: flex; max-height: 260px; flex-direction: column; overflow-y: auto; }
  .tz-row {
    display: grid;
    grid-template-columns: 20px minmax(0, 1fr) auto auto;
    align-items: center;
    gap: 10px;
    padding: 6px 9px;
    border-radius: 8px;
    text-align: left;
    font-size: 12.5px;
    color: var(--color-muted);
  }
  .tz-row.is-active { background: rgb(255 255 255 / 0.06); color: var(--color-ink); }
  .tz-row.is-on { color: var(--color-ink); background: color-mix(in srgb, var(--color-accent) 16%, transparent); }
  .tz-row-flag { display: grid; place-items: center; font-size: 16px; transition: transform 0.4s var(--jelly); }
  .tz-row-flag.is-none { color: var(--color-faint); }
  .tz-row.is-active .tz-row-flag { transform: scale(1.18) rotate(-6deg); }
  .tz-row-name { display: flex; min-width: 0; align-items: baseline; gap: 6px; }
  .tz-row-name b { overflow: hidden; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
  .tz-row-name span { overflow: hidden; font-size: 10.5px; color: var(--color-faint); text-overflow: ellipsis; white-space: nowrap; }
  .tz-row-off { font-size: 10.5px; color: var(--color-faint); font-variant-numeric: tabular-nums; }
  .tz-row-time { font-family: ui-monospace, monospace; font-size: 12px; color: var(--color-ink); }
  .tz-none { padding: 10px; font-size: 12px; color: var(--color-faint); }
  :global(:root[data-motion="off"]) .tz-sec,
  :global(:root[data-motion="off"]) .tz-hour,
  :global(:root[data-motion="off"]) .tz-min,
  :global(:root[data-motion="off"]) .tz-row-flag { transition: none; }
  :global(:root[data-motion="off"]) .tz-badge { animation: none; }
</style>
