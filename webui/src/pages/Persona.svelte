<script lang="ts">
  /**
   * The instructions that decide how the bot talks.
   *
   * Read only until you press Edit. It is the single most load bearing piece
   * of text in the app, and an always-live textarea makes it far too easy to
   * change by leaning on a key. Saving returns it to read only, so the state
   * of the page tells you whether your work is stored.
   */
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { toast } from "../lib/stores";
  import { resource } from "../lib/resource";
  import { api as _api } from "../lib/api";
  import Card from "../lib/components/Card.svelte";
  import Button from "../lib/components/Button.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import MoodEditor from "../lib/components/MoodEditor.svelte";
  import ReactionEditor from "../lib/components/ReactionEditor.svelte";
  import OpenersEditor from "../lib/components/OpenersEditor.svelte";
  import { renderMarkdown } from "../lib/markdown";

  let text = $state("");
  const persona = resource("instructions", () => api.instructions(), { text: "" });

  let saved = $state("");            // what is on disk
  let loading = $state(true);
  let loadError = $state("");
  let saving = $state(false);
  let editing = $state(false);
  /** Formatted or raw in the read-only view. */
  let raw = $state(false);
  let area: HTMLTextAreaElement | null = $state(null);

  const dirty = $derived(editing && text !== saved);
  const chars = $derived(text.length);
  const words = $derived(text.trim() ? text.trim().split(/\s+/).length : 0);
  const lines = $derived(text ? text.split("\n").length : 0);

  // The persona is a long document: reloading it on every visit meant a blank
  // page and a wait to be shown the same text again. An edit in progress is
  // never clobbered, because a refresh only replaces the text when you are not
  // editing it.
  onMount(async () => {
    const cached = persona.refresh({ maxAge: 30000 });
    if ($persona.fetched) {
      text = saved = $persona.data.text || "";
      loading = false;
    }
    await cached;
    if (!editing) text = saved = $persona.data.text || "";
    else saved = $persona.data.text || "";
    loading = false;
    loadError = $persona.error;
  });

  async function startEdit() {
    editing = true;
    await Promise.resolve();
    area?.focus();
  }

  function cancel() {
    text = saved;
    editing = false;
  }

  async function save() {
    saving = true;
    try {
      await api.saveInstructions(text);
      saved = text;
      editing = false;
      toast("Persona saved.", "ok");
    } catch (e: any) {
      toast(e.message, "err");
    } finally {
      saving = false;
    }
  }
</script>

<ErrorNote text={loadError} />

{#if loading}
  <div class="glass h-96 animate-pulse"></div>
{:else}
  <Card
    title="Persona"
    subtitle={editing ? "Editing. Save to apply, or cancel to discard." : "How the bot talks and behaves"}
  >
    {#snippet actions()}
      {#if editing}
        <Button kind="ghost" size="sm" onclick={cancel} disabled={saving}>Cancel</Button>
        <Button size="sm" onclick={save} loading={saving} disabled={!dirty}>
          {dirty ? "Save changes" : "Saved"}
        </Button>
      {:else}
        <Button kind="ghost" size="sm" onclick={startEdit}>
          <Icon name="persona" size={13} /> Edit
        </Button>
      {/if}
    {/snippet}

    {#if editing}
      <textarea
        bind:this={area}
        bind:value={text}
        rows={20}
        spellcheck="false"
        class="w-full rounded-lg border border-accent/40 bg-black/40 p-4 font-mono text-[13px] leading-relaxed text-ink"
        placeholder="You are... (write how the bot should talk and behave)"
      ></textarea>
    {:else}
      <!-- Read only view. The persona is written in Markdown, so it is shown
           that way: **French slang** reading as literal asterisks made the
           page look like a config file rather than a description of a person.
           Raw is one click away, because the asterisks matter when you are
           about to edit them. -->
      <div class="mb-2 flex items-center gap-2">
        <button
          class="jelly rounded-lg px-2 py-1 text-[11px] {raw ? 'text-muted hover:bg-white/[0.05]' : 'bg-accent/15 text-ink'}"
          onclick={() => (raw = false)}
        >Formatted</button>
        <button
          class="jelly rounded-lg px-2 py-1 text-[11px] {raw ? 'bg-accent/15 text-ink' : 'text-muted hover:bg-white/[0.05]'}"
          onclick={() => (raw = true)}
        >Raw</button>
      </div>
      {#if raw}
        <div
          class="max-h-[60vh] overflow-y-auto whitespace-pre-wrap rounded-lg border border-edge bg-black/25 p-4 font-mono text-[13px] leading-relaxed text-ink/90"
        >
          {#if text.trim()}{text}{:else}
            <span class="text-faint">Nothing written yet.</span>
          {/if}
        </div>
      {:else}
        <div class="markdown max-h-[60vh] overflow-y-auto rounded-lg border border-edge bg-black/25 p-4 text-[13px] leading-relaxed text-ink/90">
          {#if text.trim()}
            <!-- renderMarkdown escapes everything before it emits a single tag;
                 see the note at the top of lib/markdown.ts. -->
            {@html renderMarkdown(text)}
          {:else}
            <span class="text-faint">
              No persona written yet. Press Edit and describe how the bot should
              talk, what it likes, and how it should treat people.
            </span>
          {/if}
        </div>
      {/if}
    {/if}

    <div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-faint">
      <span>{words.toLocaleString()} words</span>
      <span>{chars.toLocaleString()} characters</span>
      <span>{lines.toLocaleString()} lines</span>
      {#if dirty}
        <span class="flex items-center gap-1.5 text-warn">
          <span class="h-1.5 w-1.5 rounded-full bg-warn"></span> unsaved changes
        </span>
      {/if}
      <span class="ml-auto">A timestamped backup is kept on every save.</span>
    </div>
  </Card>

  <!-- Moods and reactions belong with the persona, not in Settings: they are
       how this character behaves, not preferences about the app. -->
  <div class="mt-4">
    <Card title="Moods" subtitle="How the persona shifts through the day">
      <MoodEditor />
    </Card>
  </div>

  <div class="mt-4">
    <Card title="Reactions" subtitle="When it taps an emoji instead of writing back">
      <ReactionEditor />
    </Card>
  </div>

  <div class="mt-4">
    <Card title="Late openers" subtitle="How it comes back after leaving you on read">
      <OpenersEditor />
    </Card>
  </div>

{/if}
