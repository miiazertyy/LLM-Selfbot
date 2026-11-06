<script lang="ts">
  /**
   * The mark at the end of a dropdown's closed box, the way Apple draws a pop-up button's: a small chevron up over
   * a chevron down, in the text's quiet colour. It used to be a chevron on a disc of the accent, filled in while
   * open, which read as an old web control. Used by Select, LanguagePicker and TimezonePicker.
   */
  let { class: cls = "" }: { class?: string } = $props();
</script>

<svg class={cls} width="9" height="14" viewBox="0 0 9 14" fill="none" stroke="currentColor" stroke-width="1.6"
     stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M1.5 5 4.5 2 7.5 5M1.5 9 4.5 12 7.5 9" />
</svg>
