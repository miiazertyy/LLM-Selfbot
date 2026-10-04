<script lang="ts">
  /**
   * Who the bot is: one profile's persona (app/utils/personas.py), the profile picked with the pill at the top
   * when there is more than one (made, named and given accounts on the Profiles page).
   *
   * The page wears the profile's colour. Its face lands, its name types itself in, how long its text is counts up;
   * the text comes in a line at a time, and below it what else makes it who it is: the names it answers to, its
   * openers, moods and reactions, each that profile's own.
   *
   * The text is read only until you press Edit: it is the single most load
   * bearing piece of text in the app, and an always-live textarea makes it far
   * too easy to change by leaning on a key.
   */
  import { onMount, tick, untrack } from "svelte";
  import { get } from "svelte/store";
  import { api } from "../lib/api";
  import { track } from "../lib/busy";
  import { motionEnabled, toast, viewPersona } from "../lib/stores";
  import Button from "../lib/components/Button.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import Segmented from "../lib/components/Segmented.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import MoodEditor from "../lib/components/MoodEditor.svelte";
  import ReactionEditor from "../lib/components/ReactionEditor.svelte";
  import OpenersEditor from "../lib/components/OpenersEditor.svelte";
  import TriggerEditor from "../lib/components/TriggerEditor.svelte";
  import Num from "../lib/dashboard/Num.svelte";
  import { chime, domino } from "../lib/domino";
  import { renderMarkdown } from "../lib/markdown";
  import { play } from "../lib/uisound";
  import PersonaOrb from "../lib/personas/PersonaOrb.svelte";
  import PersonaScope from "../lib/personas/PersonaScope.svelte";
  import { personasRes, reloadPersonas } from "../lib/personas/store";
  import { providePersona } from "../lib/personas/context";
  import { colorOf } from "../lib/personas/logic";

  // ── Whose ──────────────────────────────────────────────────────────────────
  const list = $derived($personasRes.data.personas);
  let selected = $state(get(viewPersona) || "default");
  const current = $derived(list.find((p) => p.id === selected) ?? list.find((p) => p.is_default) ?? null);
  const color = $derived(colorOf(current));
  // Kept for Pictures and Memory, which open on the profile picked here, and the other way round.
  $effect(() => viewPersona.set(selected));
  // Picked elsewhere while this page is open (the search, Profiles): shown here too, unless the text has changes to save.
  $effect(() => {
    const want = $viewPersona;
    untrack(async () => {
      if (!want || want === selected || !list.some((p) => p.id === want)) return;
      await select(want);
      if (selected !== want) viewPersona.set(selected);
    });
  });
  // The editors below are this profile's (each reads it as it starts, and is made again for another: {#key}).
  providePersona(() => selected);

  let loadError = $state("");

  onMount(async () => {
    await personasRes.refresh({ maxAge: 10_000 });
    loadError = $personasRes.error;
    // A profile picked before, deleted since: Default.
    if (!list.some((p) => p.id === selected)) selected = "default";
    await loadText(selected);
  });

  // ── Its text ───────────────────────────────────────────────────────────────
  let text = $state("");
  let saved = $state("");
  /** Whose text `text` is. Another profile's stays up, dimmed, until the picked one's arrives, and only then reads itself out. */
  let textFor = $state("");
  let textLoading = $state(true);
  let saving = $state(false);
  let editing = $state(false);
  let raw = $state(false);
  let area: HTMLTextAreaElement | null = $state(null);
  const dirty = $derived(editing && text !== saved);
  const chars = $derived(text.length);
  const words = $derived(text.trim() ? text.trim().split(/\s+/).length : 0);
  const lines = $derived(text ? text.split("\n").length : 0);

  async function loadText(pid: string) {
    try {
      const r = await api.personaText(pid);
      if (pid !== selected) return;
      if (!editing) text = saved = r?.text || "";
      else saved = r?.text || "";
      textFor = pid;
    } catch (e: any) {
      loadError = e?.message || "Could not read it";
    } finally {
      textLoading = false;
    }
  }

  async function startEdit() {
    editing = true;
    await tick();
    area?.focus();
  }

  function cancel() {
    text = saved;
    editing = false;
  }

  async function save() {
    saving = true;
    const pid = selected;
    try {
      await track("persona", api.savePersonaText(pid, text), "Saving the persona");
      saved = text;
      editing = false;
      toast(`${current?.name ?? "Persona"} saved.`, "ok");
      reloadPersonas();
    } catch (e: any) {
      toast(e.message, "err");
    } finally {
      saving = false;
    }
  }

  // ── Picking another ────────────────────────────────────────────────────────
  let saveFlash = $state(false);
  /** Its text has changes not saved: they would go with a switch, so the Save button shakes instead. */
  async function mayLeave() {
    if (!dirty) return true;
    toast("Save or cancel the text first.", "info");
    saveFlash = false;
    await tick();
    saveFlash = true;
    return false;
  }
  async function select(pid: string) {
    if (pid === selected) return;
    if (!(await mayLeave())) return;
    editing = false;
    selected = pid;
    if (get(motionEnabled)) {
      play("glint", { delay: 60, level: 0.5 });
      play("seat", { delay: 360 });
    }
    await loadText(pid);
  }

  const SECTIONS = [
    { id: "names", title: "Names it answers to", sub: "Said in a group chat, any of these gets a reply without a mention", icon: "chats", tone: "var(--persona-color)" },
    { id: "openers", title: "Late openers", sub: "How it comes back after leaving you on read", icon: "send", tone: "var(--color-good)" },
    { id: "moods", title: "Moods", sub: "How it shifts through the day", icon: "sparkle", tone: "color-mix(in srgb, var(--persona-color) 45%, #e879f9)" },
    { id: "reactions", title: "Reactions", sub: "When it taps an emoji instead of writing back", icon: "smilePlus", tone: "var(--color-warn)" },
  ];
</script>

<ErrorNote text={loadError} />

<div class="pp" style="--persona-color: {color}">
  {#if list.length > 1}
    <!-- Whose persona: each profile has its own. -->
    <div class="ps-scope"><PersonaScope value={selected} label="Persona of" onchange={select} /></div>
  {/if}

  {#if current}
    <!-- ── Who it is ──────────────────────────────────────────────────────────── -->
    <section class="ps-hero glass" class:is-editing={editing}>
      <span class="ps-orb" use:chime={"land"}>
        {#key current.id}<PersonaOrb p={current} size={66} spin />{/key}
      </span>
      <div class="ps-who">
        <span class="ps-kicker">{list.length > 1 ? (current.is_default ? "Default profile" : "Profile") : "Persona"}</span>
        <!-- The name types itself in, a soft key each letter, again for each profile. -->
        {#key current.id + current.name}
          <h2 class="ps-name domino" use:domino={{ step: 55, sound: "key", level: 0.7, once: true }} aria-label={current.name}>
            {#each [...current.name] as ch, i (i)}<span class="ps-l">{ch === " " ? " " : ch}</span>{/each}
          </h2>
        {/key}
        <p class="ps-sub">Who it is, in plain words. Every reply starts from this.</p>
      </div>
      <!-- How much of it there is, counting up. -->
      <div class="ps-stats domino" use:domino={{ step: 90, level: 0.55 }}>
        <span class="ps-stat"><b><Num value={words} /></b>words</span>
        <span class="ps-stat"><b><Num value={lines} /></b>lines</span>
        <span class="ps-stat"><b><Num value={chars} /></b>characters</span>
      </div>
      <div class="ps-actions">
        {#if editing}
          <Button kind="ghost" size="sm" onclick={cancel} disabled={saving}>Cancel</Button>
          <span class="ps-save" class:is-flash={saveFlash} onanimationend={() => (saveFlash = false)}>
            <Button size="sm" onclick={save} loading={saving} disabled={!dirty}>{dirty ? "Save changes" : "Saved"}</Button>
          </span>
        {:else}
          <Button size="sm" onclick={startEdit}><Icon name="persona" size={13} /> Edit</Button>
        {/if}
      </div>
    </section>

    <!-- ── What it is told ────────────────────────────────────────────────────── -->
    <section class="ps-doc glass" class:is-editing={editing} class:is-switching={!textLoading && textFor !== selected}>
      <div class="ps-doc-head">
        {#if editing}
          <span class="ps-editing"><span class="ps-editing-dot"></span>Editing</span>
        {:else}
          <span class="ps-view">
            <Segmented label="How it is shown" value={raw ? "raw" : "formatted"}
                       options={[{ id: "formatted", label: "Formatted", icon: "eye" }, { id: "raw", label: "Raw", icon: "braces" }]}
                       onchange={(id) => (raw = id === "raw")} />
          </span>
        {/if}
        <span class="ps-doc-note">
          {#if dirty}<span class="ps-unsaved"><span class="ps-unsaved-dot"></span>unsaved changes</span>
          {:else}A timestamped backup is kept on every save.{/if}
        </span>
      </div>

      {#if textLoading}
        <div class="h-64 animate-pulse rounded-2xl bg-white/5"></div>
      {:else if editing}
        <textarea bind:this={area} bind:value={text} rows={20} spellcheck="false" class="ps-editor"
                  placeholder="You are... (write how it should talk and behave)"></textarea>
      {:else if raw}
        <div class="ps-raw">
          {#if text.trim()}{text}{:else}<span class="text-faint">Nothing written yet.</span>{/if}
        </div>
      {:else if text.trim()}
        <!-- renderMarkdown escapes everything before it emits a single tag; see the note at the top of lib/markdown.ts.
             A line at a time as it opens, a soft tick each, like it is being read out. -->
        {#key textFor}
          <div class="ps-text markdown domino" use:domino={{ step: 34, sound: "wind", level: 0.6, max: 18, once: true }}>
            {@html renderMarkdown(text)}
          </div>
        {/key}
      {:else}
        <p class="ps-raw text-faint">
          Nothing written yet. Press Edit and say who it is, how it talks, and how it treats people.
        </p>
      {/if}
    </section>

    <!-- ── The rest of who it is: this profile's own, each card set down in turn ── -->
    {#key selected}
      <div class="ps-grid domino" use:domino={{ step: 90, sound: "seat", level: 0.5, once: true }}>
        {#each SECTIONS as s (s.id)}
          <section class="ps-card glass" style="--tone: {s.tone}">
            <header class="ps-card-head">
              <span class="ps-card-icon"><Icon name={s.icon} size={16} /></span>
              <span class="min-w-0">
                <h3 class="ps-card-title">{s.title}</h3>
                <p class="ps-card-sub">{s.sub}</p>
              </span>
            </header>
            {#if s.id === "names"}<TriggerEditor />
            {:else if s.id === "openers"}<OpenersEditor />
            {:else if s.id === "moods"}<MoodEditor />
            {:else}<ReactionEditor />{/if}
          </section>
        {/each}
      </div>
    {/key}
  {:else}
    <div class="glass h-40 animate-pulse rounded-[22px]"></div>
  {/if}
</div>

<style>
  /* The page wears the picked profile's colour, and changes it smoothly (app.css registers the property). */
  .pp { transition: --persona-color 0.6s var(--swift); }
  .ps-scope { display: flex; align-items: center; margin-bottom: 12px; }

  /* ── The hero ── */
  .ps-hero {
    position: relative;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 16px 22px;
    margin-bottom: 16px;
    padding: 22px 24px;
    border-radius: 22px;
    background-image:
      radial-gradient(70% 150% at 0% 0%, color-mix(in srgb, var(--persona-color) 22%, transparent), transparent 60%),
      radial-gradient(50% 120% at 100% 100%, color-mix(in srgb, var(--persona-color) 10%, transparent), transparent 70%);
    transition: box-shadow 0.4s var(--swift);
  }
  .ps-hero.is-editing { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--persona-color) 50%, transparent), 0 18px 40px -26px var(--persona-color); }
  .ps-orb {
    position: relative;
    display: grid;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    animation: ps-orb-in 0.7s var(--jelly) backwards;
    transition: transform 0.45s var(--jelly);
  }
  .ps-orb:hover { transform: scale(1.06) rotate(-4deg); }
  @keyframes ps-orb-in { from { opacity: 0; transform: scale(0.4) rotate(-30deg); } }
  .ps-who { display: flex; min-width: 0; flex: 1 1 260px; flex-direction: column; gap: 4px; }
  .ps-kicker { font-size: 10.5px; font-weight: 650; letter-spacing: 0.16em; text-transform: uppercase; color: var(--color-faint); }
  /* A letter a box, so each can pop in on its own; kept on one line, as a break could come inside a word. */
  .ps-name {
    display: flex;
    max-width: 100%;
    overflow: hidden;
    font-size: 30px;
    font-weight: 700;
    line-height: 1.1;
    letter-spacing: -0.02em;
    color: var(--color-ink);
  }
  .ps-l { display: inline-block; white-space: pre; }
  .ps-sub { font-size: 12.5px; color: var(--color-muted); }
  .ps-stats { display: flex; gap: 8px; }
  .ps-stat {
    display: flex;
    min-width: 76px;
    flex-direction: column;
    align-items: center;
    gap: 1px;
    padding: 8px 12px;
    border-radius: 14px;
    font-size: 10.5px;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.035);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    transition: transform 0.4s var(--jelly), background-color 0.2s ease;
  }
  .ps-stat:hover { transform: translateY(-2px); background: rgb(255 255 255 / 0.06); }
  .ps-stat b { font-size: 17px; font-weight: 700; color: var(--color-ink); }
  .ps-actions { display: flex; align-items: center; gap: 8px; }
  .ps-save.is-flash { display: inline-flex; animation: ps-flash 0.6s ease; }
  @keyframes ps-flash { 20%, 60% { transform: translateX(-4px); } 40%, 80% { transform: translateX(4px); } }

  /* ── The text ── */
  .ps-doc { margin-bottom: 16px; padding: 16px 18px 18px; border-radius: 22px; transition: box-shadow 0.35s var(--swift); }
  .ps-doc.is-editing { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--persona-color) 45%, transparent), 0 20px 44px -28px var(--persona-color); }
  .ps-doc-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 14px; margin-bottom: 12px; }
  .ps-view { width: 230px; }
  .ps-doc-note { font-size: 11px; color: var(--color-faint); }
  .ps-unsaved { display: inline-flex; align-items: center; gap: 6px; color: var(--color-warn); }
  .ps-unsaved-dot, .ps-editing-dot { width: 6px; height: 6px; border-radius: 999px; background: currentColor; animation: ps-breathe 1.6s ease-in-out infinite; }
  .ps-editing { display: inline-flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 650; color: var(--persona-color); }
  @keyframes ps-breathe { 50% { opacity: 0.35; transform: scale(0.8); } }
  .ps-text, .ps-raw {
    max-height: 60vh;
    overflow-y: auto;
    padding: 16px 18px;
    border-radius: 16px;
    font-size: 13.5px;
    line-height: 1.7;
    color: color-mix(in srgb, var(--color-ink) 92%, transparent);
    background: linear-gradient(180deg, rgb(0 0 0 / 0.28), rgb(0 0 0 / 0.18));
    box-shadow: inset 0 1px 2px rgb(0 0 0 / 0.35), inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
  }
  .ps-raw { white-space: pre-wrap; font-family: ui-monospace, monospace; font-size: 12.5px; }
  .ps-text, .ps-raw { transition: opacity 0.2s ease; }
  .ps-doc.is-switching .ps-text, .ps-doc.is-switching .ps-raw { opacity: 0.35; }
  .ps-text :global(hr) { border: 0; height: 1px; margin: 14px 0; background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--persona-color) 55%, transparent), transparent); }
  .ps-editor {
    width: 100%;
    min-height: 420px;
    padding: 16px 18px;
    border-radius: 16px;
    font-family: ui-monospace, monospace;
    font-size: 13px;
    line-height: 1.7;
    color: var(--color-ink);
    caret-color: var(--persona-color);
    background: rgb(0 0 0 / 0.4);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--persona-color) 40%, transparent), 0 0 0 4px color-mix(in srgb, var(--persona-color) 10%, transparent);
    outline: none;
    resize: vertical;
    animation: ps-editor-in 0.4s var(--jelly);
  }
  @keyframes ps-editor-in { from { opacity: 0.4; transform: scale(0.985); } }

  /* ── The rest of who it is ── */
  /* Two across on a usual window, each card as tall as it is: stretched to a row, the short ones were tall empty boxes. */
  .ps-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 560px), 1fr));
    align-items: start;
    gap: 16px;
  }
  .ps-card { padding: 18px 20px 20px; border-radius: 22px; transition: transform 0.45s var(--jelly), box-shadow 0.3s var(--swift); }
  .ps-card:hover { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--tone) 30%, transparent), 0 18px 40px -28px var(--tone); }
  .ps-card-head { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 14px; }
  .ps-card-icon {
    display: grid;
    width: 36px;
    height: 36px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 12px;
    color: var(--tone);
    background: color-mix(in srgb, var(--tone) 15%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--tone) 30%, transparent);
    transition: transform 0.45s var(--jelly);
  }
  .ps-card:hover .ps-card-icon { transform: rotate(-10deg) scale(1.12); }
  .ps-card-title { font-size: 14px; font-weight: 650; letter-spacing: -0.01em; color: var(--color-ink); }
  .ps-card-sub { margin-top: 2px; font-size: 11.5px; line-height: 1.45; color: var(--color-muted); }

  :global(:root[data-motion="off"]) .pp,
  :global(:root[data-motion="off"]) .ps-orb,
  :global(:root[data-motion="off"]) .ps-stat,
  :global(:root[data-motion="off"]) .ps-card,
  :global(:root[data-motion="off"]) .ps-card-icon { transition: none; }
  :global(:root[data-motion="off"]) .ps-orb,
  :global(:root[data-motion="off"]) .ps-editor,
  :global(:root[data-motion="off"]) .ps-save.is-flash,
  :global(:root[data-motion="off"]) .ps-unsaved-dot,
  :global(:root[data-motion="off"]) .ps-editing-dot { animation: none; }
</style>
