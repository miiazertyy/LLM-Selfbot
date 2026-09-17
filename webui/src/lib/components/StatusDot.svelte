<script lang="ts">
  /**
   * Discord's presence indicator, drawn the way Discord draws it.
   *
   * The colour alone is not the signal: Discord gives each status a distinct
   * SHAPE so it is still readable to anyone who cannot separate the green from
   * the red. Online is a filled disc, idle a crescent, do-not-disturb a bar,
   * and offline/invisible a hollow ring. Reproduced here with masks rather than
   * four icon files, and it stays crisp at any size.
   */
  let { status = "offline", size = 12, title = "" } = $props<{
    status?: string;
    size?: number;
    title?: string;
  }>();

  // Discord's own palette, so the dot reads as the same thing it does there.
  const COLOURS: Record<string, string> = {
    online: "#23a55a",
    idle: "#f0b232",
    dnd: "#f23f43",
    invisible: "#80848e",
    offline: "#80848e",
  };

  const kind = $derived(COLOURS[status] ? status : "offline");
  const colour = $derived(COLOURS[kind]);
  // Unique per instance: two SVGs sharing a mask id would both take the first.
  const uid = `sd${Math.random().toString(36).slice(2, 9)}`;
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 16 16"
  class="shrink-0"
  role={title ? "img" : "presentation"}
  aria-label={title || undefined}
  aria-hidden={title ? undefined : "true"}
>
  {#if title}<title>{title}</title>{/if}
  <mask id={uid}>
    <!-- White keeps, black cuts away. -->
    <rect x="0" y="0" width="16" height="16" fill="black" />
    <circle cx="8" cy="8" r="8" fill="white" />
    {#if kind === "idle"}
      <!-- Offset bite out of the top left, which is what makes the crescent. -->
      <circle cx="4" cy="4" r="6" fill="black" />
    {:else if kind === "dnd"}
      <rect x="3" y="6.4" width="10" height="3.2" rx="1.6" fill="black" />
    {:else if kind === "invisible" || kind === "offline"}
      <circle cx="8" cy="8" r="4" fill="black" />
    {/if}
  </mask>
  <rect x="0" y="0" width="16" height="16" fill={colour} mask="url(#{uid})" />
</svg>
