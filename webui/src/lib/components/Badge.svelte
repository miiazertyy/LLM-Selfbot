<script lang="ts">
  let { tone = "muted", dot = false, children } = $props<{
    tone?: "muted" | "good" | "bad" | "warn" | "accent";
    dot?: boolean;
    children?: any;
  }>();

  const styles = {
    muted: "bg-white/[0.06] text-muted ring-white/[0.06]",
    good: "bg-good/12 text-good ring-good/20",
    bad: "bg-bad/12 text-bad ring-bad/20",
    warn: "bg-warn/12 text-warn ring-warn/20",
    accent: "bg-accent/12 text-accent ring-accent/20",
  } as const;

  const dots = {
    muted: "bg-muted", good: "bg-good", bad: "bg-bad", warn: "bg-warn", accent: "bg-accent",
  } as const;
</script>

<span
  class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset {styles[tone]}"
>
  {#if dot}<span class="h-1.5 w-1.5 rounded-full {dots[tone]}"></span>{/if}
  {@render children?.()}
</span>
