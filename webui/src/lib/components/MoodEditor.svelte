<script lang="ts">
  /**
   * The moods the bot drifts between, and what each one does to its writing.
   *
   * These were a raw YAML blob in Settings, which is the wrong place twice
   * over: a mood is a piece of the persona, not a preference, and a mapping of
   * name to instruction is not something anyone should edit as JSON. Each mood
   * here is a name and a sentence, added, renamed, rewritten or removed.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import { toast } from "../stores";
  import Button from "./Button.svelte";
  import Toggle from "./Toggle.svelte";
  import Icon from "./Icon.svelte";

  type Mood = { name: string; prompt: string };

  let moods = $state<Mood[]>([]);
  let enabled = $state(true);
  let minMinutes = $state(30);
  let maxMinutes = $state(60);
  let loading = $state(true);
  let saving = $state(false);
  let stored = $state("");
  let adding = $state(false);
  let draftName = $state("");
  let draftPrompt = $state("");

  /**
   * The whole set as plain text, one mood per line.
   *
   * Rewriting a dozen moods one field at a time is tedious, and the obvious
   * thing anyone wants to do is describe the character to a model and paste
   * back what it writes. The format is deliberately the simplest thing that
   * survives a round trip through a chat window: "name: how it writes".
   */
  let asText = $state(false);
  let textDraft = $state("");
  let textError = $state("");

  function toText() {
    textDraft = moods.map((m) => `${m.name}: ${m.prompt}`).join("\n");
    textError = "";
    asText = true;
  }

  function fromText() {
    const parsed: Mood[] = [];
    const seen = new Set<string>();
    for (const raw of textDraft.split("\n")) {
      const line = raw.trim();
      if (!line || line.startsWith("#")) continue;
      // Tolerate a colon, a dash or an equals between the two halves, because
      // a model asked for "name: description" will use whichever it likes.
      const at = line.search(/[:=]|\s-\s/);
      if (at < 0) {
        textError = `This line has no name and description: "${line.slice(0, 48)}"`;
        return;
      }
      const name = line.slice(0, at).trim().replace(/^[-*\d.\s]+/, "");
      const prompt = line.slice(at).replace(/^[:=]|^\s-\s/, "").trim();
      if (!name || !prompt) {
        textError = `This line is missing one half: "${line.slice(0, 48)}"`;
        return;
      }
      if (seen.has(name.toLowerCase())) {
        textError = `"${name}" appears twice.`;
        return;
      }
      seen.add(name.toLowerCase());
      parsed.push({ name, prompt });
    }
    if (!parsed.length) {
      textError = "Nothing to read. One mood per line, as name: description.";
      return;
    }
    moods = parsed;
    textError = "";
    asText = false;
  }

  /** Compared as text so a reorder or a single letter both count as a change. */
  const snapshot = $derived(
    JSON.stringify({ moods, enabled, minMinutes, maxMinutes }),
  );
  const dirty = $derived(!loading && snapshot !== stored);

  const nameTaken = $derived(
    moods.some((m) => m.name.trim().toLowerCase() === draftName.trim().toLowerCase()),
  );

  onMount(load);

  async function load() {
    try {
      const cfg = await api.config();
      const mood = (cfg?.bot?.mood ?? {}) as any;
      enabled = mood.enabled !== false;
      minMinutes = Math.round((mood.shift_interval_min ?? 1800) / 60);
      maxMinutes = Math.round((mood.shift_interval_max ?? 3600) / 60);
      moods = Object.entries(mood.moods ?? {}).map(([name, prompt]) => ({
        name,
        prompt: String(prompt),
      }));
      stored = JSON.stringify({ moods, enabled, minMinutes, maxMinutes });
    } catch (e: any) {
      toast(e?.message || "Could not load the moods", "err");
    } finally {
      loading = false;
    }
  }

  function add() {
    const name = draftName.trim();
    if (!name || nameTaken) return;
    moods = [...moods, { name, prompt: draftPrompt.trim() }];
    draftName = "";
    draftPrompt = "";
    adding = false;
  }

  function remove(i: number) {
    moods = moods.filter((_, n) => n !== i);
  }

  async function save() {
    // A mood with no name cannot be selected, and one with no instruction does
    // nothing to the writing, so neither is worth storing.
    const clean = moods
      .map((m) => ({ name: m.name.trim(), prompt: m.prompt.trim() }))
      .filter((m) => m.name && m.prompt);

    const names = new Set(clean.map((m) => m.name.toLowerCase()));
    if (names.size !== clean.length) {
      toast("Two moods share a name. They have to be different.", "err");
      return;
    }
    if (!clean.length && enabled) {
      toast("Add at least one mood, or turn moods off.", "err");
      return;
    }
    if (minMinutes > maxMinutes) {
      toast("The shortest gap cannot be longer than the longest.", "err");
      return;
    }

    saving = true;
    try {
      const table: Record<string, string> = {};
      for (const m of clean) table[m.name] = m.prompt;
      await api.configField("bot.mood.moods", table);
      await api.configField("bot.mood.enabled", enabled);
      await api.configField("bot.mood.shift_interval_min", minMinutes * 60);
      await api.configField("bot.mood.shift_interval_max", maxMinutes * 60);
      moods = clean;
      stored = JSON.stringify({ moods, enabled, minMinutes, maxMinutes });
      toast("Moods saved.", "ok");
    } catch (e: any) {
      toast(e?.message || "Could not save", "err");
    }
    saving = false;
  }

  function revert() {
    loading = true;
    load();
  }
</script>

{#if loading}
  <div class="h-40 animate-pulse rounded-xl bg-white/[0.03]"></div>
{:else}
  <div class="flex flex-wrap items-center justify-between gap-3 border-b border-edge/60 pb-3">
    <div class="min-w-0 flex-1">
      <div class="text-[13px] text-ink">Drift between moods</div>
      <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
        The bot picks one of these and writes that way for a while, then
        changes. Off means it always sounds the same.
      </p>
    </div>
    <Toggle checked={enabled} onchange={(v) => (enabled = v)} />
  </div>

  {#if enabled}
    <div class="flex flex-wrap items-center gap-3 border-b border-edge/60 py-3">
      <span class="text-[12px] text-muted">Change mood every</span>
      <input
        type="number" min="1" max="1440" bind:value={minMinutes}
        class="field w-20 text-center font-mono text-[12px]"
      />
      <span class="text-[12px] text-muted">to</span>
      <input
        type="number" min="1" max="1440" bind:value={maxMinutes}
        class="field w-20 text-center font-mono text-[12px]"
      />
      <span class="text-[12px] text-muted">minutes</span>
    </div>
  {/if}

  {#if asText}
    <div class="py-3">
      <p class="mb-2 text-[11px] leading-relaxed text-faint">
        One mood per line, written as <span class="font-mono text-muted">name: how it writes</span>.
        Paste a set here, or ask a model for one and paste that. Replacing the
        text replaces every mood.
      </p>
      <textarea
        bind:value={textDraft}
        rows={12}
        spellcheck="false"
        class="w-full rounded-lg border border-edge bg-black/40 p-3 font-mono text-[12px] leading-relaxed outline-none focus:border-accent/50"
      ></textarea>
      {#if textError}
        <p class="mt-1.5 text-[11px] text-bad">{textError}</p>
      {/if}
      <div class="mt-2 flex justify-end gap-2">
        <Button size="sm" kind="ghost" onclick={() => { asText = false; textError = ""; }}>
          Cancel
        </Button>
        <Button size="sm" onclick={fromText}>Use this</Button>
      </div>
    </div>
  {:else}
  <div class="divide-y divide-edge/60">
    {#each moods as m, i (i)}
      <div class="group py-3">
        <div class="flex items-center gap-2">
          <span class="shrink-0 text-accent/70"><Icon name="sparkle" size={13} /></span>
          <input
            bind:value={m.name}
            placeholder="mood name"
            class="bare min-w-0 flex-1 text-[13px] font-medium text-ink"
          />
          <button
            class="shrink-0 rounded-lg p-1.5 text-faint opacity-0 transition-opacity hover:bg-bad/15 hover:text-bad group-hover:opacity-100"
            onclick={() => remove(i)}
            aria-label="Remove {m.name}"
          ><Icon name="close" size={13} /></button>
        </div>
        <textarea
          bind:value={m.prompt}
          rows={2}
          placeholder="How it writes in this mood, in a sentence or two."
          class="mt-1.5 w-full rounded-lg border border-edge bg-surface px-2.5 py-1.5 text-[12px] leading-relaxed outline-none focus:border-accent/50"
        ></textarea>
      </div>
    {:else}
      <p class="py-4 text-[13px] text-muted">
        No moods yet, so the bot always sounds the same.
      </p>
    {/each}
  </div>

  {#if adding}
    <div class="mt-3 rounded-xl border border-accent/40 bg-accent/[0.04] p-3">
      <input
        bind:value={draftName}
        placeholder="Name, for example sleepy"
        class="field w-full text-[13px]"
      />
      {#if draftName.trim() && nameTaken}
        <p class="mt-1 text-[11px] text-warn">There is already a mood called that.</p>
      {/if}
      <textarea
        bind:value={draftPrompt}
        rows={2}
        placeholder="How it writes in this mood."
        class="mt-2 w-full rounded-lg border border-edge bg-surface px-2.5 py-1.5 text-[12px] outline-none focus:border-accent/50"
      ></textarea>
      <div class="mt-2 flex justify-end gap-2">
        <Button size="sm" kind="ghost" onclick={() => (adding = false)}>Cancel</Button>
        <Button size="sm" onclick={add} disabled={!draftName.trim() || nameTaken}>Add</Button>
      </div>
    </div>
  {:else}
    <div class="mt-3 flex gap-2">
      <button
        class="flex-1 rounded-xl border border-dashed border-edge py-2.5 text-[12px] text-muted transition-colors hover:bg-white/[0.03] hover:text-ink"
        onclick={() => (adding = true)}
      >Add a mood</button>
      <button
        class="rounded-xl border border-dashed border-edge px-3 py-2.5 text-[12px] text-muted transition-colors hover:bg-white/[0.03] hover:text-ink"
        onclick={toText}
        title="Edit every mood at once, as text"
      >Edit as text</button>
    </div>
  {/if}
  {/if}

  <div class="mt-4 flex items-center justify-between gap-3 border-t border-edge/60 pt-3">
    <p class="text-[11px] text-faint">
      {moods.length} mood{moods.length === 1 ? "" : "s"}.
      {#if dirty}<span class="text-warn">Unsaved.</span>{/if}
    </p>
    <div class="flex gap-2">
      {#if dirty}
        <Button size="sm" kind="ghost" onclick={revert}>Undo</Button>
      {/if}
      <Button size="sm" onclick={save} loading={saving} disabled={!dirty}>Save</Button>
    </div>
  </div>
{/if}
