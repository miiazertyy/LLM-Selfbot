<script lang="ts">
  let { label = "", hint = "", children } = $props<{ label?: string; hint?: string; children?: any }>();
</script>

<div class="mb-4">
  {#if label}
    <span class="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-muted">{label}</span>
  {/if}
  {@render children?.()}
  {#if hint}<p class="mt-1.5 text-[11px] leading-relaxed text-faint">{hint}</p>{/if}
</div>
