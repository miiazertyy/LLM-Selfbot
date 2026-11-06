<script lang="ts">
  /** A platform's own mark on its own colour, as a little app icon, at any size: the same tile, centred and sized the way
   *  Settings' is (app.css), so a logo means one thing wherever it is. */
  import { PLATFORMS, type PlatformId } from "../platforms";
  import Icon from "./Icon.svelte";

  let { platform, size = 18 }: { platform: string; size?: number } = $props();

  const brand = $derived(PLATFORMS[platform as PlatformId]);
</script>

{#if brand}
  <span class="settings-mark is-social is-{brand.id}" title={brand.name} aria-label={brand.name} role="img"
        style="--tone: {brand.tone}; width: {size}px; height: {size}px; border-radius: {Math.round(size * 0.3)}px">
    <Icon name={brand.icon} size={Math.round(size * 0.56)} />
  </span>
{/if}
