<script lang="ts">
  /**
   * A Minecraft account's view in a window of its own ("?watch=minecraft_1", opened by app/desktop.py, or a tab in
   * a browser): the same Watch as the Accounts page has, HUD, chat and controls included, filling the window.
   */
  import { onMount } from "svelte";
  import WatchView from "./lib/accounts/WatchView.svelte";
  import { themeId, fontId, motionEnabled, loadPrefs } from "./lib/stores";
  import { applyTheme } from "./lib/themes";
  import { applyFont } from "./lib/fonts";

  const params = new URLSearchParams(location.search);
  const account = /^minecraft_\d{1,3}$/.test(params.get("watch") || "") ? String(params.get("watch")) : "";
  const name = (params.get("name") || "").slice(0, 40);

  onMount(() => {
    document.documentElement.classList.add("is-watch");
    document.title = name ? `What ${name} sees` : "What it sees";
    loadPrefs();
  });
  $effect(() => { applyTheme($themeId); });
  $effect(() => { applyFont($fontId); });
  $effect(() => { document.documentElement.dataset.motion = $motionEnabled ? "full" : "off"; });
</script>

<main class="ww">
  {#if account}
    <WatchView {account} {name} full />
  {:else}
    <p class="ww-none">No Minecraft account to show.</p>
  {/if}
</main>

<style>
  .ww {
    box-sizing: border-box; height: 100vh; padding: 12px; overflow: hidden;
    background:
      radial-gradient(120% 70% at 0% 0%, color-mix(in srgb, var(--color-accent) 10%, transparent), transparent 60%),
      var(--color-bg);
    color: var(--color-ink);
  }
  .ww-none { display: grid; height: 100%; place-items: center; font-size: 13px; color: var(--color-faint); }
</style>
