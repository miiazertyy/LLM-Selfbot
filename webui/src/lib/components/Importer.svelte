<script lang="ts">
  /**
   * The drop area from the Pictures tab, reused wherever one file is taken in.
   *
   * Pictures grew its own copy first; the theme and typeface panels want the
   * same thing, and three near-identical blocks of dropzone markup is how they
   * end up drifting apart.
   */
  import Icon from "./Icon.svelte";

  let {
    title,
    hint,
    accept,
    busy = false,
    busyLabel = "Uploading",
    onpick,
  } = $props<{
    title: string;
    hint: string;
    accept: string;
    busy?: boolean;
    busyLabel?: string;
    onpick: (file: File) => void;
  }>();

  let dragOver = $state(false);

  /** One file: everything using this replaces rather than accumulates. */
  function take(files: FileList | null) {
    const file = files?.[0];
    if (file) onpick(file);
  }
</script>

<div
  role="button"
  tabindex="0"
  aria-label={title}
  class="glass flex flex-col items-center justify-center gap-2.5 rounded-2xl border border-dashed p-6 text-center transition-colors
    {dragOver ? 'border-accent bg-accent/[0.06]' : 'border-edge'}"
  ondragover={(e) => {
    e.preventDefault();
    dragOver = true;
  }}
  ondragleave={() => (dragOver = false)}
  ondrop={(e) => {
    e.preventDefault();
    dragOver = false;
    take(e.dataTransfer?.files ?? null);
  }}
>
  <span class="text-accent {busy ? 'animate-pulse' : ''}">
    <Icon name={busy ? "sparkle" : "upload"} size={24} />
  </span>
  <div>
    <p class="text-[13px] text-ink">{busy ? busyLabel : title}</p>
    <p class="mt-0.5 text-[11px] leading-relaxed text-faint">{hint}</p>
  </div>
  <label class="cursor-pointer rounded-lg bg-accent px-3.5 py-1.5 text-[13px] font-medium text-bg transition-colors hover:bg-accent/90">
    Browse files
    <input
      type="file"
      {accept}
      class="hidden"
      onchange={(e) => {
        const input = e.target as HTMLInputElement;
        take(input.files);
        // Cleared so picking the same file twice still fires a change.
        input.value = "";
      }}
    />
  </label>
</div>
