<script lang="ts">
  let { checked = $bindable(false), disabled = false, label = "", onchange } = $props<{
    checked?: boolean;
    disabled?: boolean;
    label?: string;
    onchange?: (v: boolean) => void;
  }>();

  function toggle() {
    if (disabled) return;
    checked = !checked;
    onchange?.(checked);
  }
</script>

<button
  type="button"
  onclick={toggle}
  {disabled}
  class="relative h-[22px] w-10 shrink-0 rounded-full border transition-colors duration-200
    {checked ? 'border-accent/50 bg-accent' : 'border-edge bg-edge-soft'}
    {disabled ? 'opacity-50' : ''}"
  role="switch"
  aria-checked={checked}
  aria-label={label || "Toggle"}
>
  <!-- The knob overshoots and settles, the squish that sells "jello". -->
  <span
    class="absolute top-[2px] h-[16px] rounded-full bg-white shadow-sm"
    style="left: {checked ? '20px' : '2px'}; width: {checked ? '16px' : '16px'};
           transition: left 0.42s var(--jelly), width 0.42s var(--jelly);"
  ></span>
</button>
{#if label}<span class="text-sm text-ink">{label}</span>{/if}
