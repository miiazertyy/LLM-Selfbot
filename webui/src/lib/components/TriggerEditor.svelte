<script lang="ts">
  /**
   * The names the bot answers to: say one in a group chat and it replies
   * without being mentioned.
   *
   * These were "Trigger words (comma-separated)" in Settings, a text box among
   * the command prefixes. They are the character's names and nicknames, so they
   * live with the persona, one chip per name.
   *
   * Saved in the same "Alicia, Ali, Alycia" form the box wrote, so matching is
   * exactly what it was. Clearing every name means no trigger words at all:
   * the runner drops empty words, where an empty one used to match everything.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import { usePersona } from "../personas/context";
  import { toast } from "../stores";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";

  /** The persona this edits (the page gives it): its own settings, on everyone's. "" is everyone's. */
  const persona = usePersona();

  const MAX = 30;

  let names = $state<string[]>([]);
  let draft = $state("");
  let stored = $state("");
  let loading = $state(true);
  let saving = $state(false);
  let input: HTMLInputElement | null = $state(null);

  const value = $derived(names.join(", "));
  const dirty = $derived(!loading && value !== stored);

  /** Names as the setting holds them: comma separated, spacing and blanks tidied away. */
  const split = (text: string) => text.split(",").map((w) => w.trim()).filter(Boolean);

  onMount(async () => {
    try {
      const cfg = await api.config(persona);
      names = split(String(cfg?.bot?.trigger ?? ""));
      stored = names.join(", ");
    } catch (e: any) {
      toast(e?.message || "Could not load the names", "err");
    } finally {
      loading = false;
    }
  });

  /** Whatever was typed or pasted, split on commas, each name once whatever its case. */
  function addDraft() {
    const next = [...names];
    for (const n of split(draft)) {
      if (next.length >= MAX) {
        toast(`That is the limit of ${MAX}. Remove one first.`, "err");
        break;
      }
      if (!next.some((x) => x.toLowerCase() === n.toLowerCase())) next.push(n);
    }
    names = next;
    draft = "";
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addDraft();
    } else if (e.key === "Backspace" && !draft && names.length) {
      names = names.slice(0, -1);
    }
  }

  const remove = (n: string) => (names = names.filter((x) => x !== n));

  function revert() {
    names = split(stored);
    draft = "";
  }

  async function save() {
    if (draft.trim()) addDraft();
    saving = true;
    try {
      await api.configField("bot.trigger", value, { persona });
      stored = value;
      toast(names.length ? "Names saved. It answers to them from the next message." : "No names now: group chats need a mention.", "ok");
    } catch (e: any) {
      toast(e?.message || "Could not save", "err");
    }
    saving = false;
  }
</script>

{#if loading}
  <div class="h-11 animate-pulse rounded-lg bg-white/[0.03]"></div>
{:else}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="te-box" onclick={() => input?.focus()}>
    {#each names as n (n)}
      <span class="te-chip">
        {n}
        <button class="te-x" onclick={(e) => { e.stopPropagation(); remove(n); }} aria-label="Remove {n}" title="Remove {n}">
          <Icon name="close" size={10} />
        </button>
      </span>
    {/each}
    <input
      bind:this={input}
      bind:value={draft}
      onkeydown={onKey}
      onblur={() => draft.trim() && addDraft()}
      placeholder={names.length ? "Add another" : "A name or nickname"}
      spellcheck="false"
      class="te-input"
    />
  </div>

  <div class="mt-2.5 flex flex-wrap items-center gap-2">
    <p class="min-w-0 flex-1 text-[11px] leading-relaxed text-faint">
      {#if names.length}
        Any of these in a group chat gets a reply without a mention. Servers still need a mention or a
        reply. Enter or a comma adds one.
      {:else}
        No names: in a group chat it replies only when mentioned or replied to.
      {/if}
    </p>
    {#if dirty}
      <Button kind="ghost" size="sm" onclick={revert} disabled={saving}>Revert</Button>
      <Button size="sm" onclick={save} loading={saving}>Save names</Button>
    {/if}
  </div>
{/if}

<style>
  .te-box {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    min-height: 44px;
    padding: 6px;
    border-radius: 12px;
    border: 1px solid var(--color-edge);
    background: rgb(0 0 0 / 0.22);
    cursor: text;
    transition: border-color 0.18s ease, box-shadow 0.18s ease;
  }
  .te-box:focus-within {
    border-color: color-mix(in srgb, var(--color-accent) 60%, transparent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .te-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 5px 4px 10px;
    border-radius: 999px;
    font-size: 13px;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 16%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 28%, transparent);
    animation: te-in 0.18s ease both;
  }
  @keyframes te-in {
    from { opacity: 0; transform: scale(0.92); }
    to { opacity: 1; transform: none; }
  }
  :global(:root[data-motion="off"]) .te-chip { animation: none; }
  .te-x {
    display: grid;
    width: 18px;
    height: 18px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-muted);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .te-x:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.1); }
  .te-input {
    min-width: 120px;
    flex: 1;
    padding: 4px 6px;
    font-size: 13px;
    color: var(--color-ink);
    background: transparent;
    outline: none;
  }
  .te-input::placeholder { color: var(--color-faint); }
</style>
