<script lang="ts">
  /**
   * Settings, as tabs with subtabs inside them.
   *
   * The tree lives in lib/settingsmap.ts, which explains why it is shaped the
   * way it is. This file renders it: the tab rail, the subtab strip, the control
   * for each field, and saving.
   *
   * There is no "show more advanced settings" disclosure any more. Every subtab
   * is small enough to show whole, which was the only reason the disclosure
   * existed.
   */
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { toast, snowEnabled, motionEnabled, themeId, settingsSection, settingsPath, fontId } from "../lib/stores";
  import { THEMES } from "../lib/themes";
  import { FONTS } from "../lib/fonts";
  import { sweepTo } from "../lib/themesweep";
  import { TABS, PATHS, homeOf, restHomeOf, resolveTarget, type Tab, type Sub } from "../lib/settingsmap";
  import Button from "../lib/components/Button.svelte";
  import Toggle from "../lib/components/Toggle.svelte";
  import Modal from "../lib/components/Modal.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import EnvEditor from "../lib/components/EnvEditor.svelte";
  import WaitTimes from "../lib/components/WaitTimes.svelte";
  import ListEditor from "../lib/components/ListEditor.svelte";
  import ModelPicker from "../lib/components/ModelPicker.svelte";
  import { springValue } from "../lib/spring";
  import { hscroll } from "../lib/hscroll";
  import SnapchatSetup from "../lib/components/SnapchatSetup.svelte";
  import LocalAI from "../lib/components/LocalAI.svelte";

  type FieldDef = {
    key: string;
    label: string;
    type: string;
    section: string;
    requires_restart?: boolean;
    description?: string;
    common?: boolean;
    min?: number;
    max?: number;
    step?: number;
    current: any;
  };

  let fields = $state<FieldDef[]>([]);
  let dirty = $state<Record<string, any>>({});
  let saving = $state(false);
  let loading = $state(true);
  let loadError = $state("");
  let raw = $state("");
  let rawOpen = $state(false);
  let query = $state("");

  // Where you were last time, so coming back lands on the thing you were
  // changing rather than on the first tab.
  let path = $state($settingsPath);
  $effect(() => {
    settingsPath.set(path);
  });

  const tab = $derived(TABS.find((t) => t.id === path.split("/")[0]) ?? TABS[0]);
  const sub = $derived(tab.subs.find((s) => s.id === path.split("/")[1]) ?? tab.subs[0]);

  const changed = $derived(Object.keys(dirty).length);
  const searching = $derived(query.trim().length > 0);

  /** Every field, by key, so the tree can pull them out in its own order. */
  const byKey = $derived.by(() => {
    const out: Record<string, FieldDef> = {};
    for (const f of fields) out[f.key] = f;
    return out;
  });

  /**
   * The fields a subtab shows.
   *
   * A key the tree names but config.yaml does not have is skipped rather than
   * rendered as an empty row: bot.groq_tts_model only exists once voice
   * messages have been set up, for instance.
   */
  function fieldsFor(t: Tab, s: Sub): FieldDef[] {
    if (s.rest) {
      const want = `${t.id}/${s.id}`;
      return fields.filter((f) => !homeOf(f.key) && restHomeOf(f.key) === want);
    }
    return (s.keys ?? []).map((k) => byKey[k]).filter(Boolean);
  }

  const shown = $derived(fieldsFor(tab, sub));

  /** Subtabs with nothing in them are not worth a tab. */
  function subVisible(t: Tab, s: Sub): boolean {
    if (s.panel) return true;
    return fieldsFor(t, s).length > 0;
  }

  const subs = $derived(tab.subs.filter((s) => subVisible(tab, s)));

  const results = $derived.by(() => {
    if (!searching) return [];
    const q = query.trim().toLowerCase();
    return fields
      .filter(
        (f) =>
          f.label.toLowerCase().includes(q) ||
          f.key.toLowerCase().includes(q) ||
          (f.description || "").toLowerCase().includes(q),
      )
      .slice(0, 60);
  });

  /** "Discord, Where it replies" for a search hit, so the result has a home. */
  function whereIs(key: string): string {
    const p = homeOf(key) ?? restHomeOf(key);
    const hit = PATHS.find((x) => x.path === p);
    return hit ? `${hit.tab.name}, ${hit.sub.name}` : "";
  }

  function goToKey(key: string) {
    const p = homeOf(key) ?? restHomeOf(key);
    if (p) {
      path = p;
      query = "";
    }
  }

  /** Unsaved changes, counted per tab and per subtab, for the dots. */
  const unsaved = $derived.by(() => {
    const out: Record<string, number> = {};
    for (const key of Object.keys(dirty)) {
      const p = homeOf(key) ?? restHomeOf(key);
      if (!p) continue;
      out[p] = (out[p] ?? 0) + 1;
      const t = p.split("/")[0];
      out[t] = (out[t] ?? 0) + 1;
    }
    return out;
  });

  /**
   * Settings that hold a Groq model id, and what each one needs the model to
   * be able to do. The picker only offers models with that capability: a
   * speech model cannot write replies and a text model cannot read an image,
   * and picking one fails on every request with an unhelpful error.
   */
  const MODEL_FIELDS: Record<string, string> = {
    "bot.groq_models": "chat",
    "bot.groq_small_model": "chat",
    "bot.groq_image_model": "vision",
    "bot.groq_whisper_model": "stt",
    "bot.groq_tts_model": "tts",
  };

  /**
   * Settings that only accept certain values.
   *
   * A free text box for "short, balanced or chatty" invites a typo that reads
   * as valid and silently falls back to the default.
   */
  const CHOICES: Record<string, { value: string; label: string }[]> = {
    "bot.message_style.mode": [
      { value: "short", label: "Short, a line or two" },
      { value: "balanced", label: "Balanced" },
      { value: "chatty", label: "Chatty, longer replies" },
    ],
    "bot.client_profile": [
      { value: "web", label: "Web browser, safer" },
      { value: "desktop", label: "Desktop app" },
    ],
    "services.webui.bind": [
      { value: "127.0.0.1", label: "This machine only" },
      { value: "0.0.0.0", label: "Anything on this network" },
    ],
  };

  /**
   * How far along a slider's value sits, as a percentage.
   *
   * The filled part of the track is drawn from this: a range input otherwise
   * shows one flat line with no sense of where in the range you are.
   */
  function fillPct(f: FieldDef): number {
    const lo = f.min ?? 0;
    const hi = f.max ?? 1;
    const v = Number(value(f));
    if (!isFinite(v) || hi === lo) return 0;
    return Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
  }

  function pickTab(t: Tab) {
    const first = t.subs.find((s) => subVisible(t, s)) ?? t.subs[0];
    path = `${t.id}/${first.id}`;
    query = "";
  }

  onMount(load);

  // The dependency doctor and the health banners link straight to a setting.
  $effect(() => {
    const want = $settingsSection;
    if (!want) return;
    settingsSection.set("");
    const target = resolveTarget(want);
    if (target) {
      path = target;
      query = "";
    }
  });

  async function load() {
    try {
      const data = await api.schema();
      fields = data.fields || [];
      dirty = {};
    } catch (e: any) {
      loadError = e?.message || "Could not load";
    } finally {
      loading = false;
    }
  }

  const value = (f: FieldDef) => (f.key in dirty ? dirty[f.key] : f.current);
  const setValue = (f: FieldDef, v: any) => (dirty[f.key] = v);

  /** Put a field back to what is stored, for a mis-click. */
  function undo(f: FieldDef) {
    const next = { ...dirty };
    delete next[f.key];
    dirty = next;
  }

  function undoAll() {
    dirty = {};
    toast("Reverted every unsaved change.", "ok");
  }

  async function save() {
    saving = true;
    let failed = 0;
    for (const [key, v] of Object.entries(dirty)) {
      try {
        await api.configField(key, v);
      } catch (e: any) {
        failed++;
        toast(`${key}: ${e.message}`, "err");
      }
    }
    saving = false;
    dirty = {};
    toast(failed ? "Some settings failed to save." : "Saved.", failed ? "err" : "ok");
    load();
  }

  async function openRaw() {
    raw = JSON.stringify(await api.config(), null, 2);
    rawOpen = true;
  }

  async function saveRaw() {
    try {
      await api.saveConfig(JSON.parse(raw));
      toast("Config saved.", "ok");
      rawOpen = false;
      load();
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  // The stored profiles panel.
  let people = $state<{ enabled: boolean; cached: number } | null>(null);
  onMount(async () => {
    try {
      people = await api.peopleSettings();
    } catch {
      /* optional */
    }
  });

  async function clearPeople() {
    try {
      const r = await api.clearPeopleCache();
      toast(`Cleared ${r.removed} stored profile${r.removed === 1 ? "" : "s"}.`, "ok");
      people = await api.peopleSettings();
    } catch (e: any) {
      toast(e.message, "err");
    }
  }
</script>

<!-- One row for one setting, used by both the subtabs and the search results. -->
{#snippet row(f: FieldDef, showHome: boolean)}
  <div class="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:gap-4">
    <div class="min-w-0 sm:flex-1">
      <div class="flex items-center gap-1.5 text-[13px] text-ink">
        <span class="min-w-0 break-words sm:truncate">{f.label}</span>
        {#if f.key in dirty}
          <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" title="unsaved"></span>
        {/if}
      </div>
      {#if f.description}
        <p class="mt-0.5 text-[11px] leading-relaxed text-faint">{f.description}</p>
      {/if}
      <p class="mt-0.5 flex flex-wrap items-center gap-x-2 text-[10px] text-faint/70">
        {#if f.requires_restart}<span class="text-warn/80">needs a restart</span>{/if}
        {#if showHome}
          <button class="underline decoration-dotted hover:text-ink" onclick={() => goToKey(f.key)}>
            {whereIs(f.key)}
          </button>
        {/if}
        <span class="break-all font-mono opacity-60" title={f.key}>{f.key}</span>
      </p>
    </div>

    <div class="flex items-center gap-2 sm:shrink-0">
      <!-- Undo sits next to the control it reverts, so a mis-click is one
           click to put back rather than remembering the old value. -->
      {#if f.key in dirty}
        <button
          onclick={() => undo(f)}
          title="Undo this change"
          aria-label="Undo {f.label}"
          class="jelly shrink-0 rounded-lg p-1.5 text-accent hover:bg-accent/10"
        >
          <Icon name="refresh" size={13} />
        </button>
      {/if}

      {#if f.key === "bot.batch_wait_times"}
        <div class="w-full sm:w-80">
          <WaitTimes value={value(f)} onchange={(rows) => setValue(f, rows)} />
        </div>
      <!-- Model names come from Groq rather than from memory. A typo used to
           fail silently, and a retirement failed months later. -->
      {:else if f.key in MODEL_FIELDS}
        <ModelPicker
          value={value(f)}
          need={MODEL_FIELDS[f.key]}
          multiple={f.key === "bot.groq_models"}
          onchange={(v) => setValue(f, v)}
        />
      {:else if f.type === "bool"}
        <Toggle checked={value(f)} onchange={(v) => setValue(f, v)} />
      {:else if f.type === "float"}
        <input
          type="range"
          min={f.min ?? 0}
          max={f.max ?? 1}
          step={f.step ?? 0.01}
          value={value(f)}
          oninput={(e) => setValue(f, parseFloat((e.target as HTMLInputElement).value))}
          style="--fill: {fillPct(f)}%"
          class="slider min-w-0 flex-1 sm:w-44 sm:flex-none"
          use:springValue
        />
        <span class="slider-value shrink-0 font-mono text-[12px] text-ink">{value(f)}</span>
      {:else if f.type === "int"}
        <input
          type="number"
          value={value(f)}
          oninput={(e) => setValue(f, parseInt((e.target as HTMLInputElement).value))}
          class="bare w-full text-right font-mono sm:w-28"
        />
      {:else if f.key in CHOICES}
        <select
          value={value(f)}
          onchange={(e) => setValue(f, (e.target as HTMLSelectElement).value)}
          class="field w-full text-[12px] sm:w-56"
        >
          {#each CHOICES[f.key] as opt}
            <option value={opt.value}>{opt.label}</option>
          {/each}
        </select>
      <!-- A plain list of words or phrases is edited as items, not as JSON:
           adding one word should not mean getting the quoting and the commas
           right, with a missing bracket rejecting the save. -->
      {:else if f.type === "json" && Array.isArray(value(f))
                && value(f).every((v: any) => typeof v === "string")}
        <ListEditor
          value={value(f)}
          onchange={(list) => setValue(f, list)}
          placeholder="Add a word or phrase"
        />
      {:else if f.type === "json"}
        <textarea
          rows={2}
          value={typeof value(f) === "string" ? value(f) : JSON.stringify(value(f))}
          oninput={(e) => setValue(f, (e.target as HTMLTextAreaElement).value)}
          spellcheck="false"
          class="field w-full font-mono text-[11px] sm:w-80"
        ></textarea>
      {:else}
        <input
          type="text"
          value={value(f)}
          oninput={(e) => setValue(f, (e.target as HTMLInputElement).value)}
          class="bare w-full text-right sm:w-56 lg:w-72"
        />
      {/if}
    </div>
  </div>
{/snippet}

<ErrorNote text={loadError} onretry={() => { loadError = ""; loading = true; load(); }} />

{#if loading}
  <div class="space-y-2">
    {#each Array(6) as _}<div class="h-11 animate-pulse rounded-lg bg-white/[0.03]"></div>{/each}
  </div>
{:else}
  <div class="mb-4 flex flex-wrap items-center gap-2">
    <label class="relative min-w-0 flex-1">
      <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
        <Icon name="search" size={14} />
      </span>
      <input bind:value={query} placeholder="Search every setting" class="field py-1.5 pl-8 pr-3 text-[13px]" />
    </label>
    <div class="flex shrink-0 gap-2">
      {#if changed}
        <Button kind="ghost" size="sm" onclick={undoAll}>Undo all</Button>
      {/if}
      <Button kind="ghost" size="sm" onclick={openRaw}>Raw file</Button>
      <Button size="sm" onclick={save} loading={saving} disabled={!changed}>
        Save{changed ? ` ${changed}` : ""}
      </Button>
    </div>
  </div>

  <div class="grid gap-5 lg:grid-cols-[214px_minmax(0,1fr)]">
    <!-- ── Tabs ────────────────────────────────────────────────────────────
         A vertical list rather than a wrapped row of pills: names read left to
         right instead of hunting across two lines, and there is room to say
         what each one holds. It becomes a horizontal scroller on a phone,
         where vertical space is the scarce thing. -->
    <div class="hscroll">
    <nav class="settings-rail" aria-label="Settings" use:hscroll>
      {#each TABS as t (t.id)}
        <button
          onclick={() => pickTab(t)}
          aria-current={tab.id === t.id && !searching}
          class="settings-tab {tab.id === t.id && !searching ? 'is-active' : ''}"
        >
          <span class="settings-tab-bar" aria-hidden="true"></span>
          <span class="settings-tab-icon"><Icon name={t.icon} size={15} /></span>
          <span class="min-w-0 flex-1">
            <span class="flex items-center gap-1.5">
              <span class="truncate text-[13px]">{t.name}</span>
              {#if unsaved[t.id]}
                <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-accent"
                      title="unsaved changes"></span>
              {/if}
            </span>
            <span class="settings-tab-blurb">{t.blurb}</span>
          </span>
        </button>
      {/each}
    </nav>
    </div>

    <div class="min-w-0">
      {#if searching}
        <p class="mb-3 text-[12px] text-faint">
          {results.length} setting{results.length === 1 ? "" : "s"} matching "{query}"
        </p>
        <div class="divide-y divide-edge/60">
          {#each results as f (f.key)}
            {@render row(f, true)}
          {:else}
            <p class="py-6 text-center text-[13px] text-faint">Nothing matches.</p>
          {/each}
        </div>
      {:else}
        <!-- ── Subtabs ─────────────────────────────────────────────────────
             A segmented strip, not a second vertical list: the tab already
             owns the left edge, and these are short. -->
        <div class="hscroll settings-subs-wrap">
        <div class="settings-subs" role="tablist" aria-label="{tab.name} sections" use:hscroll>
          {#each subs as s (s.id)}
            <button
              role="tab"
              aria-selected={sub.id === s.id}
              onclick={() => (path = `${tab.id}/${s.id}`)}
              class="settings-sub {sub.id === s.id ? 'is-active' : ''}"
            >
              {s.name}
              {#if unsaved[`${tab.id}/${s.id}`]}
                <span class="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-accent align-middle"
                      title="unsaved changes"></span>
              {/if}
            </button>
          {/each}
        </div>
        </div>

        <!-- Keyed on the subtab so the panel is rebuilt, and therefore
             re-animated, on every switch. -->
        {#key path}
          <div class="settings-panel">
            <header class="mb-4">
              <h2 class="text-[15px] font-medium text-ink">{sub.name}</h2>
              {#if sub.blurb}
                <p class="mt-0.5 text-[12px] text-faint">{sub.blurb}</p>
              {/if}
            </header>

            {#if sub.panel === "env"}
              <EnvEditor
                sections={sub.env?.sections ?? null}
                keyLists={sub.env?.keyLists ?? []}
                extras={sub.env?.extras ?? false}
              />
            {:else if sub.panel === "local"}
              <LocalAI />
            {:else if sub.panel === "snapchat-setup"}
              <SnapchatSetup />
              {#if byKey["snapchat.enabled"]}
                <div class="mt-6 divide-y divide-edge/60 border-t border-edge/60 pt-2">
                  {@render row(byKey["snapchat.enabled"], false)}
                </div>
              {/if}
            {:else if sub.panel === "theme"}
              <div class="grid grid-cols-1 gap-2 min-[380px]:grid-cols-2 lg:grid-cols-3">
                {#each THEMES as t}
                  <button
                    onclick={() => sweepTo(t.id)}
                    class="jelly group relative overflow-hidden rounded-xl border p-3 text-left
                      {$themeId === t.id
                        ? 'border-accent/60 bg-accent/10'
                        : 'border-edge hover:border-edge hover:bg-white/[0.04]'}"
                  >
                    <div class="mb-2 flex gap-1">
                      {#each ["--color-accent", "--color-accent-2", "--color-good", "--color-warn"] as v}
                        <span class="h-4 w-4 rounded-md ring-1 ring-black/30" style="background: {t.vars[v]}"></span>
                      {/each}
                    </div>
                    <div class="truncate text-[12px] font-medium text-ink">{t.name}</div>
                    <div class="mt-0.5 text-[10px] leading-snug text-faint">{t.hint}</div>
                    {#if $themeId === t.id}
                      <span class="pop absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-accent"></span>
                    {/if}
                  </button>
                {/each}
              </div>
            {:else if sub.panel === "typeface"}
              <div class="grid grid-cols-1 gap-2 min-[380px]:grid-cols-2">
                {#each FONTS as f}
                  <button
                    onclick={() => fontId.set(f.id)}
                    class="jelly rounded-xl border p-3 text-left
                      {$fontId === f.id
                        ? 'border-accent/60 bg-accent/10'
                        : 'border-edge hover:bg-white/[0.04]'}"
                  >
                    <!-- Set in the face itself, so the sample is the decision. -->
                    <div class="truncate text-[15px] text-ink" style="font-family: {f.stack}">
                      {f.name}
                    </div>
                    <div class="mt-0.5 truncate text-[11px] text-muted" style="font-family: {f.stack}">
                      The quick brown fox jumps
                    </div>
                    <div class="mt-1 text-[10px] leading-snug text-faint">{f.note}</div>
                  </button>
                {/each}
              </div>
            {:else if sub.panel === "interface"}
              <div class="divide-y divide-edge/60">
                <div class="flex items-center gap-4 py-3">
                  <div class="min-w-0 flex-1">
                    <div class="text-[13px] text-ink">Animations</div>
                    <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
                      Springy motion throughout. On by default even when Windows has
                      animation effects turned off.
                    </p>
                  </div>
                  <Toggle checked={$motionEnabled} onchange={(v) => motionEnabled.set(v)} />
                </div>
                <div class="flex items-center gap-4 py-3">
                  <div class="min-w-0 flex-1">
                    <div class="text-[13px] text-ink">Cursor snow</div>
                    <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
                      Snow falls from your cursor as you move it around the app.
                      Purely decorative.
                    </p>
                  </div>
                  <Toggle checked={$snowEnabled} onchange={(v) => snowEnabled.set(v)} />
                </div>
              </div>
            {:else if sub.panel === "profiles"}
              <div class="divide-y divide-edge/60">
                {#if byKey["bot.profile_cache.enabled"]}
                  {@render row(byKey["bot.profile_cache.enabled"], false)}
                {/if}
                <div class="flex flex-wrap items-center gap-4 py-3">
                  <div class="min-w-0 flex-1">
                    <div class="text-[13px] text-ink">Stored profiles</div>
                    <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
                      {people?.cached ?? 0} people cached on this machine. Clearing
                      removes every stored name, avatar and bio.
                    </p>
                  </div>
                  <Button kind="ghost" size="sm" onclick={clearPeople}>Clear stored profiles</Button>
                </div>
              </div>
            {:else}
              <div class="divide-y divide-edge/60">
                {#each shown as f (f.key)}
                  {@render row(f, false)}
                {:else}
                  <p class="py-6 text-center text-[13px] text-faint">Nothing here.</p>
                {/each}
              </div>
            {/if}
          </div>
        {/key}

        <p class="mt-6 text-[11px] text-faint">
          Saving applies the change to the running account straight away. Only rows
          marked <em class="not-italic text-warn">needs a restart</em> wait for the
          account to be restarted.
        </p>
      {/if}
    </div>
  </div>
{/if}

<Modal open={rawOpen} title="Raw config" onclose={() => (rawOpen = false)}>
  <textarea
    bind:value={raw}
    rows={18}
    spellcheck="false"
    class="w-full rounded-lg border border-edge bg-black/40 p-3 font-mono text-xs text-ink"
  ></textarea>
  <div class="mt-4 flex justify-end gap-2">
    <Button kind="ghost" onclick={() => (rawOpen = false)}>Cancel</Button>
    <Button onclick={saveRaw}>Save</Button>
  </div>
</Modal>
