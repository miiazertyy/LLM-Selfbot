<script lang="ts">
  let { kind = "primary", loading = false, onclick, children, disabled = false, size = "md" } = $props<{
    kind?: "primary" | "ghost" | "danger" | "good";
    size?: "sm" | "md";
    loading?: boolean;
    disabled?: boolean;
    onclick?: () => void;
    children?: any;
  }>();

  const styles = {
    primary: "bg-accent text-bg hover:bg-accent/90 shadow-[0_6px_20px_-8px] shadow-accent/60",
    ghost: "border border-edge text-ink hover:bg-white/[0.07] hover:border-edge",
    danger: "border border-bad/40 text-bad hover:bg-bad/10",
    good: "bg-good/15 text-good hover:bg-good/25",
  } as const;

  const sizes = { sm: "px-2.5 py-1 text-xs", md: "px-3.5 py-2 text-sm" } as const;
</script>

<button
  {onclick}
  disabled={disabled || loading}
  class="jelly jelly-lift inline-flex items-center justify-center gap-1.5 rounded-[10px] font-medium
         disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0
         {styles[kind]} {sizes[size]}"
>
  {#if loading}
    <span class="h-3 w-3 animate-spin rounded-full border border-current border-t-transparent"></span>
  {/if}
  {@render children?.()}
</button>
