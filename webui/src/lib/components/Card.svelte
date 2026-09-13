<script lang="ts">
  let { title = "", subtitle = "", actions = null, children, pad = true } = $props<{
    title?: string;
    subtitle?: string;
    actions?: any;
    children?: any;
    pad?: boolean;
  }>();
</script>

<!-- overflow-hidden so an unpadded child with its own background (a log pane,
     a table) clips to the card's radius instead of squaring off its corners. -->
<div class="glass card-enter overflow-hidden transition-colors duration-200 hover:border-edge/80 {pad ? 'p-5' : ''}">
  {#if title}
    <!-- With pad={false} the card supplies no inset, so the header has to
         carry its own or the title sits flush in the corner. -->
    <div class="flex items-start justify-between gap-3 {pad ? 'mb-4' : 'px-5 pb-3 pt-4'}">
      <div class="min-w-0">
        <h2 class="text-[13px] font-semibold tracking-tight text-ink">{title}</h2>
        {#if subtitle}<p class="mt-0.5 text-[11px] text-muted">{subtitle}</p>{/if}
      </div>
      <div class="flex shrink-0 items-center gap-2">{@render actions?.()}</div>
    </div>
  {/if}
  {@render children?.()}
</div>
