<script lang="ts" module>
  /**
   * The providers with a logo. The files are the providers' own marks, shipped
   * in public/providers so they work offline and nothing is fetched to draw
   * them, each cut out of its background so they all sit the same way: the
   * mark alone, on the tile's own plate. They came as a mix of white squares,
   * black squares, coloured squares and white circles, which looked like a row
   * of unrelated stickers.
   */
  const LOGOS = new Set([
    "groq", "openai", "anthropic", "openrouter", "xai", "together", "lmstudio",
    "cerebras", "ollama", "gemini", "mistral", "deepseek", "llamacpp", "vllm",
    "jan", "gpt4all", "koboldcpp", "localai", "docker", "sglang", "textgen", "tabbyapi",
    "elevenlabs", "deepgram", "cartesia", "fish", "rime", "minimax",
  ]);
</script>

<script lang="ts">
  /** A provider's mark: its own logo, or its initials on its colour, or a screen for this computer. */
  import Icon from "./Icon.svelte";
  import { MONOGRAM, TINT } from "../providers";

  let { id, size = 34 }: { id: string; size?: number } = $props();
  const tint = $derived(TINT[id] ?? "var(--color-accent)");
  // A logo that fails to load falls back to the initials rather than a broken image.
  let broken = $state(false);
  const hasLogo = $derived(!broken && LOGOS.has(id));
  const radius = $derived(Math.round(size * 0.28));
  // In pixels from the tile's own size: a percentage padding is taken from the
  // width of whatever the tile sits in, which blew these up to half a card.
  const pad = $derived(Math.round(size * 0.17));
</script>

{#if hasLogo}
  <span class="ptile is-logo" style="width:{size}px;height:{size}px;border-radius:{radius}px;padding:{pad}px">
    <img src="/providers/{id}.png" alt="" draggable="false" onerror={() => (broken = true)} />
  </span>
{:else}
  <span class="ptile" style="--tint:{tint};width:{size}px;height:{size}px;font-size:{Math.round(size * 0.36)}px;border-radius:{radius}px">
    {#if id === "local"}
      <Icon name="monitor" size={Math.round(size * 0.52)} />
    {:else}
      {MONOGRAM[id] ?? id.slice(0, 2)}
    {/if}
  </span>
{/if}

<style>
  .ptile {
    position: relative;
    display: inline-grid;
    flex-shrink: 0;
    place-items: center;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: color-mix(in srgb, var(--tint) 88%, white);
    background: color-mix(in srgb, var(--tint) 16%, transparent);
  }
  .ptile.is-logo {
    overflow: hidden;
    background: rgb(255 255 255 / 0.07);
  }
  .ptile.is-logo img {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: contain;
    user-select: none;
  }
</style>
