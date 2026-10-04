<script lang="ts">
  /**
   * A message, with its @mentions drawn as the people they point at.
   *
   * `<@123…>` in the raw text becomes a chip carrying the person's name (from
   * what the panel knows locally), clickable the same way every other name in
   * the app is - it opens the same card. An id the bot has never seen stays a
   * plain "@user" chip that still opens whatever is on file. Everything that is
   * not a mention is rendered as-is.
   */
  import { onMount } from "svelte";
  import UserChip from "./UserChip.svelte";
  import { mentionNames, resolveMention, segments } from "../mentions";

  let { text = "", size = "sm" }: { text?: string; size?: "sm" | "md" } = $props();

  const parts = $derived(segments(text));

  onMount(() => {
    for (const p of parts) if (p.kind === "mention") resolveMention(p.id);
  });
  // A message can change (a new preview in the same row); resolve any new ids.
  $effect(() => {
    for (const p of parts) if (p.kind === "mention") resolveMention(p.id);
  });
</script>

{#each parts as part}{#if part.kind === "text"}{part.text}{:else}<span class="mention"><UserChip
        id={part.id}
        name={$mentionNames[part.id] || "user"}
        {size}
      /></span>{/if}{/each}

<style>
  /* A quiet pill so a mention reads as a reference to a person, not as running
     text, and lines up with the accent the rest of the app uses for names. */
  .mention :global(.user-chip),
  .mention :global(button) {
    border-radius: 6px;
    padding: 0 4px;
    background: color-mix(in srgb, var(--color-accent) 15%, transparent);
    color: color-mix(in srgb, var(--color-accent) 90%, var(--color-ink));
    font-weight: 500;
  }
  .mention :global(.user-chip)::before,
  .mention :global(button)::before {
    content: "@";
    opacity: 0.7;
  }
  .mention :global(button:hover) {
    background: color-mix(in srgb, var(--color-accent) 26%, transparent);
  }
</style>
