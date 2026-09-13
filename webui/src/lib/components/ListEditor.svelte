<script lang="ts">
  /**
   * A list of short strings, edited as tags rather than as JSON.
   *
   * These settings are things like the words that mark a message as French, or
   * the openers used after a long silence. They were rendered as a text box
   * holding ["bonjour","salut","coucou","quoi"], which means adding one word
   * involves getting the quoting and commas right, and a single missing
   * bracket rejects the whole save.
   *
   * Long entries (whole sentences, like the openers) get one row each; short
   * ones flow as chips, because thirty single words as thirty rows is a wall.
   */
  import Icon from "./Icon.svelte";

  let { value, onchange, placeholder = "Add one" } = $props<{
    value: string[] | any;
    onchange: (v: string[]) => void;
    placeholder?: string;
  }>();

  let draft = $state("");
  let editing = $state<number | null>(null);
  let editValue = $state("");

  const items = $derived(Array.isArray(value) ? value.map((v: any) => String(v)) : []);

  /** Sentences need their own line; single words read better side by side. */
  const longform = $derived(items.some((t) => t.length > 24) || items.length <= 6);

  function add() {
    const text = draft.trim();
    if (!text) return;
    draft = "";
    if (items.includes(text)) return;      // a duplicate would be dead weight
    onchange([...items, text]);
  }

  function remove(i: number) {
    onchange(items.filter((_, n) => n !== i));
  }

  function commit() {
    if (editing === null) return;
    const i = editing;
    editing = null;
    const text = editValue.trim();
    if (!text) {
      remove(i);
      return;
    }
    onchange(items.map((t, n) => (n === i ? text : t)));
  }
</script>

<div class="w-full sm:w-80">
  {#if items.length}
    {#if longform}
      <div class="mb-1.5 space-y-1">
        {#each items as item, i (item + i)}
          <div class="group flex items-start gap-1.5 rounded-lg bg-white/[0.05] px-2 py-1">
            {#if editing === i}
              <input
                bind:value={editValue}
                onkeydown={(e) => {
                  if (e.key === "Enter") commit();
                  if (e.key === "Escape") editing = null;
                }}
                onblur={commit}
                class="min-w-0 flex-1 rounded-md border border-accent/50 bg-surface px-1.5 py-0.5 text-[12px] outline-none"
              />
            {:else}
              <button
                class="min-w-0 flex-1 break-words text-left text-[12px] text-ink/90 hover:text-accent"
                title="Click to edit"
                onclick={() => { editing = i; editValue = item; }}
              >{item}</button>
            {/if}
            <button
              class="shrink-0 px-1 text-[11px] text-faint opacity-0 transition-opacity hover:text-bad group-hover:opacity-100"
              onclick={() => remove(i)}
              aria-label="Remove {item}"
            >&times;</button>
          </div>
        {/each}
      </div>
    {:else}
      <div class="mb-1.5 flex flex-wrap gap-1">
        {#each items as item, i (item + i)}
          <span class="group flex items-center gap-1 rounded-md bg-white/[0.06] py-0.5 pl-2 pr-1 text-[12px] text-ink/90">
            <button class="max-w-[14rem] truncate hover:text-accent"
                    title="Click to edit"
                    onclick={() => { editing = i; editValue = item; }}>{item}</button>
            <button class="px-0.5 text-[11px] text-faint hover:text-bad"
                    onclick={() => remove(i)} aria-label="Remove {item}">&times;</button>
          </span>
        {/each}
      </div>
      {#if editing !== null}
        <input
          bind:value={editValue}
          onkeydown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") editing = null;
          }}
          onblur={commit}
          class="mb-1.5 w-full rounded-lg border border-accent/50 bg-surface px-2 py-1 text-[12px] outline-none"
        />
      {/if}
    {/if}
  {/if}

  <div class="flex items-center gap-1.5">
    <input
      bind:value={draft}
      onkeydown={(e) => e.key === "Enter" && add()}
      {placeholder}
      class="min-w-0 flex-1 rounded-lg border border-edge bg-surface px-2.5 py-1.5 text-[12px] outline-none focus:border-accent/50"
    />
    <button
      onclick={add}
      disabled={!draft.trim()}
      class="shrink-0 rounded-lg border border-edge px-2 py-1.5 text-faint transition-colors hover:border-accent/40 hover:text-accent disabled:opacity-40"
      aria-label="Add"
    ><Icon name="plus" size={13} /></button>
  </div>
  <p class="mt-1 text-[10px] text-faint">
    {items.length} item{items.length === 1 ? "" : "s"}. Click one to edit it.
  </p>
</div>
