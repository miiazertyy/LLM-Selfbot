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
   * Every entry is a chip as wide as its own words, and the chips run on like
   * a sentence, wrapping where the line ends. Sentences used to get a
   * full-width row each, which made seven openers a tall column of boxes that
   * were mostly empty. The box to add one is the last thing on the line, where
   * the next entry will go, and takes whatever room the line has left.
   */
  import { flip } from "svelte/animate";
  import { scale } from "svelte/transition";
  import { backOut, cubicIn } from "svelte/easing";
  import { motionEnabled } from "../stores";
  import Icon from "./Icon.svelte";

  let { value, onchange, placeholder = "Add one", width = "w-full sm:w-[26rem]" } = $props<{
    value: string[] | any;
    onchange: (v: string[]) => void;
    placeholder?: string;
    /** Its width: a settings row's control column by default; a card passes "w-full". */
    width?: string;
  }>();

  let draft = $state("");
  let editing = $state<number | null>(null);
  let editValue = $state("");
  // An edit gives the entry a new key. Without this it would shrink away and
  // a copy grow in beside it, when all that happened was a word changed.
  let calm = $state(false);

  const items = $derived(Array.isArray(value) ? value.map((v: any) => String(v)) : []);

  /** Keys by text, counting repeats, so a list that holds a line twice still renders both. */
  const keyed = $derived.by(() => {
    const seen: Record<string, number> = {};
    return items.map((text: string) => {
      const n = (seen[text] = (seen[text] ?? -1) + 1);
      return { text, key: `${text}\u0000${n}` };
    });
  });

  /** Transition times, none when the app's motion is off or an entry was only edited. */
  const ms = (t: number) => ($motionEnabled && !calm ? t : 0);

  function add() {
    const text = draft.trim();
    if (!text) return;
    draft = "";
    if (items.includes(text)) return;      // a duplicate would be dead weight
    onchange([...items, text]);
  }

  function remove(i: number) {
    onchange(items.filter((_: string, n: number) => n !== i));
  }

  function edit(i: number) {
    editing = i;
    editValue = items[i];
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
    if (text === items[i]) return;
    calm = true;
    onchange(items.map((t: string, n: number) => (n === i ? text : t)));
    requestAnimationFrame(() => requestAnimationFrame(() => (calm = false)));
  }

  /** The draft box: Enter adds, Backspace in an empty box picks up the last entry to edit. */
  function draftKey(e: KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      add();
    } else if (e.key === "Backspace" && !draft && items.length) {
      e.preventDefault();
      edit(items.length - 1);
    }
  }

  function focusIn(node: HTMLInputElement) {
    node.focus();
    node.select();
  }
</script>

<div class="le {width}">
  <div class="le-flow">
    {#each keyed as { text, key }, i (key)}
      <span
        class="le-chip"
        class:is-editing={editing === i}
        animate:flip={{ duration: ms(260) }}
        in:scale={{ start: 0.5, duration: ms(320), easing: backOut }}
        out:scale={{ start: 0.5, duration: ms(150), easing: cubicIn }}
      >
        {#if editing === i}
          <input
            class="le-edit"
            bind:value={editValue}
            use:focusIn
            aria-label="Edit {text}"
            onkeydown={(e) => {
              if (e.key === "Enter") commit();
              if (e.key === "Escape") editing = null;
            }}
            onblur={commit}
          />
        {:else}
          <button type="button" class="le-text" title="Click to edit" onclick={() => edit(i)}>{text}</button>
          <button type="button" class="le-x" onclick={() => remove(i)} aria-label="Remove {text}" title="Remove">
            <Icon name="close" size={9} />
          </button>
        {/if}
      </span>
    {/each}

    <span class="le-add">
      <input bind:value={draft} onkeydown={draftKey} {placeholder} aria-label={placeholder} />
      <button type="button" class="le-plus" onclick={add} disabled={!draft.trim()} aria-label="Add">
        <Icon name="plus" size={12} />
      </button>
    </span>
  </div>
  <p class="le-count">
    {items.length} item{items.length === 1 ? "" : "s"}.
    {#if items.length}Click one to edit it.{/if}
  </p>
</div>

<style>
  .le-flow {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }

  /* One entry: as wide as its words, never wider than the line. */
  .le-chip {
    position: relative;
    display: inline-flex;
    align-items: center;
    max-width: 100%;
    border-radius: 10px;
    border: 1px solid rgb(255 255 255 / 0.07);
    background: rgb(255 255 255 / 0.05);
    transition:
      background-color 0.18s var(--swift),
      border-color 0.18s var(--swift),
      box-shadow 0.24s var(--swift);
  }
  .le-chip:hover {
    background: rgb(255 255 255 / 0.08);
    border-color: color-mix(in srgb, var(--color-accent) 30%, transparent);
  }
  .le-chip.is-editing {
    border-color: color-mix(in srgb, var(--color-accent) 60%, transparent);
    background: color-mix(in srgb, var(--color-accent) 8%, transparent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 14%, transparent);
  }

  .le-text {
    min-width: 0;
    padding: 4px 10px;
    font-size: 12.5px;
    line-height: 1.35;
    text-align: left;
    color: color-mix(in srgb, var(--color-ink) 90%, transparent);
    overflow-wrap: anywhere;
    transition: color 0.18s var(--swift);
  }
  .le-text:hover {
    color: var(--color-ink);
  }

  /* The way to remove one sits on its corner, so it takes no room from the
     words and the chips do not shift about when one is pointed at. */
  .le-x {
    position: absolute;
    top: -6px;
    right: -6px;
    display: grid;
    place-items: center;
    width: 16px;
    height: 16px;
    border-radius: 999px;
    border: 1px solid var(--color-edge);
    background: var(--color-card);
    color: var(--color-muted);
    opacity: 0;
    transform: scale(0.5);
    transition:
      opacity 0.16s var(--swift),
      transform 0.32s var(--jelly),
      background-color 0.16s var(--swift),
      color 0.16s var(--swift);
  }
  .le-chip:hover .le-x,
  .le-x:focus-visible {
    opacity: 1;
    transform: scale(1);
  }
  .le-x:hover {
    background: var(--color-bad);
    border-color: var(--color-bad);
    color: #fff;
  }

  /* An entry being edited keeps the size of its words as they change. */
  .le-edit {
    field-sizing: content;
    min-width: 4ch;
    max-width: 100%;
    padding: 4px 10px;
    font-size: 12.5px;
    line-height: 1.35;
    color: var(--color-ink);
    background: transparent;
    outline: none;
  }

  /* The next entry goes here: the rest of the last line, at least 9rem. */
  .le-add {
    display: inline-flex;
    flex: 1 0 9rem;
    align-items: center;
    min-width: 9rem;
    border-radius: 10px;
    border: 1px dashed rgb(255 255 255 / 0.14);
    transition:
      border-color 0.18s var(--swift),
      background-color 0.18s var(--swift);
  }
  .le-add:focus-within {
    border-style: solid;
    border-color: color-mix(in srgb, var(--color-accent) 55%, transparent);
    background: rgb(255 255 255 / 0.03);
  }
  .le-add input {
    min-width: 0;
    flex: 1;
    padding: 4px 10px;
    font-size: 12.5px;
    line-height: 1.35;
    color: var(--color-ink);
    background: transparent;
    outline: none;
  }
  .le-add input::placeholder {
    color: var(--color-faint);
  }
  .le-plus {
    display: grid;
    place-items: center;
    margin-right: 3px;
    width: 20px;
    height: 20px;
    border-radius: 7px;
    color: var(--color-accent);
    transition:
      opacity 0.16s var(--swift),
      transform 0.32s var(--jelly),
      background-color 0.16s var(--swift);
  }
  .le-plus:hover:not(:disabled) {
    background: color-mix(in srgb, var(--color-accent) 16%, transparent);
  }
  .le-plus:disabled {
    opacity: 0;
    transform: scale(0.5);
  }

  .le-count {
    margin-top: 6px;
    font-size: 10px;
    color: var(--color-faint);
  }

  :global(:root[data-motion="off"]) .le-chip,
  :global(:root[data-motion="off"]) .le-x,
  :global(:root[data-motion="off"]) .le-plus {
    transition: none;
  }
</style>
