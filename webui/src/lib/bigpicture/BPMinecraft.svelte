<script lang="ts">
  /**
   * Watching a Minecraft account play: what it sees, live, drawn by the same page its
   * Accounts view uses (accounts/WatchView.svelte), with where it is and how it is
   * doing, and what it is thinking over the top. Nobody plays it from here, so nothing
   * on the picture takes the pointer. A page of its own, or `inset` in its grown card.
   */
  import { onDestroy, onMount } from "svelte";
  import { api, type McHud } from "../api";
  import LiveThought from "../components/LiveThought.svelte";
  import PlatformMark from "../components/PlatformMark.svelte";
  import { popIn } from "./motion";
  import type { BPAccount } from "./types";

  let { account, inset = false }: { account: BPAccount; inset?: boolean } = $props();

  let hud = $state<McHud | null>(null);
  let timer = 0;
  onMount(() => {
    const look = () => api.minecraftHud(account.id).then((h: McHud) => { if (h?.ok) hud = h; }).catch(() => {});
    look();
    timer = window.setInterval(look, 1500);
  });
  onDestroy(() => clearInterval(timer));

  const src = $derived(`/api/minecraft/${encodeURIComponent(account.id)}/view/`);
  const where = $derived(hud?.where ? hud.where.replace(/_/g, " ") : "");
</script>

<div class="bmc" class:is-inset={inset}>
  <div class="bmc-view" in:popIn|global={{ delay: 60, from: 0.97 }}>
    <iframe {src} title="What {account.name} sees" tabindex="-1"></iframe>
    <div class="bmc-thought"><LiveThought source={account.id} variant="overlay" /></div>
    <div class="bmc-chips">
      {#if !inset}<span class="bmc-chip bmc-who"><PlatformMark platform="minecraft" size={18} />{hud?.who || account.name}</span>{/if}
      {#if hud}
        <span class="bmc-chip"><b>{hud.at.x}</b> <b>{hud.at.y}</b> <b>{hud.at.z}</b></span>
        {#if where}<span class="bmc-chip">{where}</span>{/if}
        <span class="bmc-chip">{Math.ceil(hud.health / 2)} hearts · {Math.ceil(hud.food / 2)} food</span>
        {#if hud.near.length}<span class="bmc-chip">{hud.near.length} nearby</span>{/if}
      {/if}
    </div>
  </div>
</div>

<style>
  .bmc { display: grid; height: 100%; min-height: 0; place-items: center; }
  .bmc-view {
    position: relative;
    width: min(100%, calc((100vh - 150px) * 16 / 9));
    aspect-ratio: 16 / 9;
    overflow: hidden;
    border-radius: var(--bp-r);
    background: #000;
  }
  .bmc.is-inset .bmc-view { width: 100%; }
  .bmc-view iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; pointer-events: none; }
  .bmc-thought { position: absolute; top: 14px; left: 14px; width: min(46%, 440px); }
  .bmc-chips { position: absolute; bottom: 14px; left: 14px; right: 14px; display: flex; flex-wrap: wrap; gap: 6px; }
  .bmc-chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 10px; font-size: 12.5px; color: #fff; background: rgb(12 10 16 / 0.6); font-variant-numeric: tabular-nums; }
  .bmc-chip b { font-weight: 600; }
  .bmc-who { font-weight: 650; }
</style>
