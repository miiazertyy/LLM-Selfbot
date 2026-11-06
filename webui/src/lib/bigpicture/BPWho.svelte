<script lang="ts">
  /**
   * Whose this page is, where the accounts speak as more than one persona: a row of
   * their faces. Persona and Pictures are each one persona's own, and used to show
   * only the first running Discord account's, with no way to see the rest.
   */
  import Avatar from "../components/Avatar.svelte";
  import { focusable } from "./focus";
  import type { BPAccount } from "./types";

  let { choices = [], current = "", onpick }: {
    /** One account for each persona there is. */
    choices?: { account: BPAccount; persona: string; name: string }[];
    current?: string;
    onpick?: (accountId: string) => void;
  } = $props();
</script>

{#if choices.length > 1}
  <div class="bpo" data-sound="self">
    {#each choices as c (c.persona)}
      <button class="bp-chip bpo-chip" class:is-on={c.persona === current} use:focusable={{ id: `who:${c.persona}` }} onclick={() => onpick?.(c.account.id)}>
        <Avatar src={c.account.avatar} name={c.account.name} size={24} zoom={false} />{c.name}
      </button>
    {/each}
  </div>
{/if}

<style>
  .bpo { display: flex; flex-shrink: 0; flex-wrap: wrap; gap: 4px; }
  :global(.bpo-chip) { padding: 0 13px 0 6px; }
</style>
