<script lang="ts">
  /**
   * A number whose digits roll to their new value, like a counter's wheels.
   *
   * Each digit is a column of 0 to 9 slid to its place, so 19 to 20 rolls the
   * tens up one and the ones round, rather than the text swapping. Columns
   * are keyed from the right, so the ones stay the ones when a digit is added
   * in front, and the new one rolls in. Screen readers get the plain number.
   */
  let { value, class: cls = "" }: { value: number | string; class?: string } = $props();

  const DIGITS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
  const chars = $derived(String(value).split(""));
</script>

<span class="odo {cls}" aria-hidden="true">
  {#each chars as ch, i (chars.length - i)}
    {#if ch >= "0" && ch <= "9"}
      <span class="odo-col"><span class="odo-strip" style="transform: translateY({-Number(ch) * 10}%)">{#each DIGITS as d (d)}<span>{d}</span>{/each}</span></span>
    {:else}
      <span class="odo-sep">{ch}</span>
    {/if}
  {/each}
</span>
<span class="sr-only">{value}</span>

<style>
  .odo {
    display: inline-flex;
    height: 1.15em;
    overflow: hidden;
    line-height: 1.15em;
    font-variant-numeric: tabular-nums;
    vertical-align: bottom;
  }
  .odo-col { display: inline-block; height: 1.15em; overflow: hidden; animation: odo-in 0.35s var(--spring) both; }
  .odo-strip { display: flex; flex-direction: column; transition: transform 0.45s cubic-bezier(0.2, 0.9, 0.25, 1); }
  .odo-strip > span { display: block; height: 1.15em; text-align: center; }
  .odo-sep { display: inline-block; }
  @keyframes odo-in { from { opacity: 0; transform: translateY(40%); } }
  :global(:root[data-motion="off"]) .odo-strip { transition: none; }
  :global(:root[data-motion="off"]) .odo-col { animation: none; }
</style>
