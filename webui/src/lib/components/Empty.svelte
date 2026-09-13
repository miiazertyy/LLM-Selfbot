<script lang="ts">
  import Icon from "./Icon.svelte";
  /** Borderless on purpose: this often sits inside a Card, and a bordered
      empty state there reads as a box inside a box. */
  let { text = "", icon = "search", hint = "" } = $props<{
    text?: string;
    icon?: string;
    hint?: string;
  }>();
</script>

<div class="pop flex flex-col items-center gap-3 px-6 py-12 text-center">
  <div class="flex h-11 w-11 items-center justify-center rounded-xl bg-white/[0.04] text-faint">
    <Icon name={icon} size={20} />
  </div>
  <div class="max-w-sm text-sm text-muted">{text}</div>
  {#if hint}<div class="max-w-sm text-[11px] text-faint">{hint}</div>{/if}
</div>
