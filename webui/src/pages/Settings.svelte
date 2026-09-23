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
  import { toast, snowEnabled, motionEnabled, themeId, settingsSection, settingsPath, fontId, health,
           appearance, appearanceVersion, customBgOn, customBgDim, loadAppearance,
           backdropId, surfaceId } from "../lib/stores";
  import { CUSTOM_FONT_ID } from "../lib/fonts";
  import { BACKDROPS } from "../lib/backdrops";

  const SURFACES = [
    { id: "solid", name: "Solid", hint: "Opaque panels, cheapest to draw" },
    { id: "glass", name: "Glass", hint: "See the background through them" },
    { id: "frost", name: "Frosted", hint: "Heavier blur, more opaque" },
  ];
  import Importer from "../lib/components/Importer.svelte";
  import StatusDot from "../lib/components/StatusDot.svelte";
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
  import { resource } from "../lib/resource";

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

  // Held outside the page like every other tab's data. The schema is the
  // slowest thing in the panel to build cold, and rebuilding it on every visit
  // meant a blank Settings each time - including the first, which the startup
  // warm-up now covers (lib/warm.ts).
  const schema = resource("settingsSchema", () => api.schema(), { fields: [] as FieldDef[] });
  const fields = $derived($schema.data?.fields ?? []);
  let dirty = $state<Record<string, any>>({});
  let saving = $state(false);
  const loading = $derived($schema.loading);
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

  /** The field scan runs one beat behind the input: it walks every setting,
      lowercasing label, key and description for each one. */
  let queryDebounced = $state("");
  $effect(() => {
    const v = query;
    const t = setTimeout(() => { queryDebounced = v; }, 120);
    return () => clearTimeout(t);
  });

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
    const q = queryDebounced.trim().toLowerCase();
    if (!q) return [];
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
  // Exactly what Discord calls them. The shape of the dot says the rest, and
  // an explanation glued onto the name only makes the list harder to scan.
  /**
   * The voices each speech model offers, and the delivery tags it understands.
   *
   * Groq publishes models over the API but not the voices inside them, so
   * unlike the model pickers there is nothing to fetch: these come from the
   * model cards. Listing them still beats the alternative, which was reading
   * the docs to find out that the word to type is "diana".
   */
  const TTS_VOICES: Record<string, string[]> = {
    "canopylabs/orpheus-v1-english": ["autumn", "diana", "hannah", "austin", "daniel", "troy"],
    "canopylabs/orpheus-arabic-saudi": ["fahad", "huda", "sara", "yazeed"],
  };
  const TTS_TONES = [
    "[casual]", "[warm]", "[calm]", "[cheerful]", "[excited]", "[serious]",
    "[soft]", "[whisper]", "[fast]", "[slow]", "[sad]", "[angry]",
    "[laugh]", "[sigh]", "[gasp]", "[sarcastic]",
  ];

  /** Voices belong to a model, so the list follows whatever is selected. */
  const ttsVoices = $derived.by(() => {
    const model = String(byKey["bot.groq_tts_model"]?.current || "").trim()
      || "canopylabs/orpheus-v1-english";
    return TTS_VOICES[model] ?? TTS_VOICES["canopylabs/orpheus-v1-english"];
  });

  function toggleTone(f: FieldDef, tone: string) {
    const current: string[] = Array.isArray(value(f)) ? value(f) : [];
    const next = current.includes(tone)
      ? current.filter((t) => t !== tone)
      : [...current, tone];
    setValue(f, next);
  }

  const PRESENCES = [
    { value: "online", label: "Online" },
    { value: "idle", label: "Idle" },
    { value: "dnd", label: "Do Not Disturb" },
    { value: "invisible", label: "Invisible" },
  ];

  const CHOICES: Record<string, { value: string; label: string }[]> = {
    "bot.desktop.build_source": [
      { value: "auto", label: "Automatic, follow Discord" },
      { value: "custom", label: "Custom, use the number below" },
    ],
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
   * The statuses Discord actually has.
   *
   * The rotation list used to be free text, so a typo ("onlien") was accepted
   * and silently never matched, leaving the account stuck on whatever it had.
   */
  const PRESENCE_KEYS = PRESENCES.map((p) => p.value);

  /**
   * Add or remove one status from the rotation pool.
   *
   * Kept in PRESENCE_KEYS order rather than click order, so the optional
   * weights list in config.yaml, which is positional, stays meaningful.
   * The last one cannot be removed: an empty pool leaves the runner with
   * nothing to pick and the account frozen on whatever it had.
   */
  function togglePresence(f: FieldDef, key: string) {
    const current: string[] = Array.isArray(value(f)) ? value(f) : [];
    const next = current.includes(key)
      ? current.filter((v) => v !== key)
      : [...current, key];
    if (!next.length) return;
    setValue(f, PRESENCE_KEYS.filter((k) => next.includes(k)));
  }

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
    // maxAge 0 on an explicit reload, but the warm-up or a previous visit
    // usually means this returns something to look at straight away.
    await schema.refresh({ maxAge: 15000 });
    loadError = $schema.error;
    dirty = {};
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
    revalidate();
  }

  /**
   * Re-run the health checks against what was just saved.
   *
   * /api/health hands back the last snapshot and only refreshes behind it, so
   * a warning you have just fixed - a model that cannot do vision, say - stayed
   * on screen until the background refresh and the next 15s poll had both come
   * round. Saving is exactly the moment to find out whether it worked, so this
   * asks for the uncached answer and updates the banner with it.
   */
  let bgBusy = $state(false);
  let fontBusy = $state(false);

  /**
   * Take one uploaded file and make it live immediately.
   *
   * The version bump is what makes a replacement show up: both files are
   * served with a long max-age, so without it the browser would happily go on
   * using the previous image or face.
   */
  async function uploadAppearance(kind: "background" | "font", file: File) {
    if (kind === "background") bgBusy = true;
    else fontBusy = true;
    try {
      await api.uploadAppearance(kind, file);
      await loadAppearance();
      appearanceVersion.set(Date.now());
      // Switching it on is the obvious intent of having just dropped it in.
      if (kind === "background") customBgOn.set(true);
      else fontId.set(CUSTOM_FONT_ID);
      toast(kind === "background" ? "Background set." : "Typeface set.", "ok");
    } catch (e: any) {
      toast(e?.message || "Could not use that file", "err");
    }
    bgBusy = false;
    fontBusy = false;
  }

  async function clearAppearance(kind: "background" | "font") {
    try {
      await api.clearAppearance(kind);
      await loadAppearance();
      appearanceVersion.set(Date.now());
      // Nothing to fall back to, so move off it rather than leaving the panel
      // pointing at a file that is no longer there.
      if (kind === "background") customBgOn.set(false);
      else if ($fontId === CUSTOM_FONT_ID) fontId.set("mikhak");
      toast("Removed.", "ok");
    } catch (e: any) {
      toast(e?.message || "Could not remove it", "err");
    }
  }

  async function revalidate() {
    try {
      const h = await api.healthNow();
      if (h && Array.isArray(h.issues) && h.routes) health.set(h);
    } catch {
      /* the 15s poll still catches up; this is only about being prompt */
    }
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
      revalidate();
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
  <!-- Label left, control right, at every width.
       It used to stack below the breakpoint, which put every toggle on its own
       line under its own description: a narrow window became a tall column of
       text with switches adrift in the middle of it, and nothing tying a
       switch to the thing it switched. Wide controls still wrap themselves,
       because they state their own width.
       The hover rail is there so a row reads as one object rather than as
       paragraphs that happen to be near each other. -->
  <div class="settings-row group flex items-start gap-3 py-3 sm:gap-4">
    <div class="min-w-0 flex-1">
      <div class="flex items-center gap-1.5 text-[13px] text-ink">
        <span class="min-w-0 break-words sm:truncate">{f.label}</span>
        {#if f.key in dirty}
          <span class="settings-dirty h-1.5 w-1.5 shrink-0 rounded-full bg-accent" title="unsaved"></span>
        {/if}
      </div>
      {#if f.description}
        <p class="mt-0.5 text-[11px] leading-relaxed text-faint">{f.description}</p>
      {/if}
      <p class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-faint/70">
        {#if f.requires_restart}
          <span class="rounded-full bg-warn/10 px-1.5 py-0.5 text-warn/90">needs a restart</span>
        {/if}
        {#if showHome}
          <button class="underline decoration-dotted hover:text-ink" onclick={() => goToKey(f.key)}>
            {whereIs(f.key)}
          </button>
        {/if}
        <span class="settings-key break-all font-mono" title={f.key}>{f.key}</span>
      </p>
    </div>

    <div class="flex shrink-0 items-center justify-end gap-2">
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

      {#if f.key === "bot.batch_wait_times" || f.key === "bot.server_batch_wait_times"}
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
      <!-- The voice belongs to the selected speech model, so the options move
           with it rather than being a free-text field you have to look up. -->
      {:else if f.key === "bot.tts.voice"}
        <select
          value={value(f)}
          onchange={(e) => setValue(f, (e.target as HTMLSelectElement).value)}
          class="field w-full text-[12px] sm:w-56"
        >
          {#each ttsVoices as v}
            <option value={v}>{v}</option>
          {/each}
          <!-- Whatever is stored stays selectable even if the model changed
               under it, so saving cannot silently rewrite it. -->
          {#if value(f) && !ttsVoices.includes(value(f))}
            <option value={value(f)}>{value(f)} (not in this model)</option>
          {/if}
        </select>
      {:else if f.key === "bot.tts.tones"}
        <div class="flex w-full flex-wrap justify-end gap-1.5 sm:w-80">
          {#each TTS_TONES as t}
            {@const picked = Array.isArray(value(f)) && value(f).includes(t)}
            <button
              type="button"
              aria-pressed={picked}
              onclick={() => toggleTone(f, t)}
              class="jelly rounded-lg border px-2 py-1 font-mono text-[11px]
                {picked
                  ? 'border-accent/60 bg-accent/10 text-ink'
                  : 'border-edge text-muted hover:bg-white/[0.04]'}"
            >
              {t}
            </button>
          {/each}
        </div>
      <!-- One status, picked the same way as the pool below. A native select
           cannot carry the indicator, and the indicator is the point. -->
      {:else if f.key === "bot.night_invisible.status"}
        <div class="flex w-full flex-wrap justify-end gap-1.5 sm:w-80">
          {#each PRESENCES as p}
            {@const picked = value(f) === p.value}
            <button
              type="button"
              aria-pressed={picked}
              onclick={() => setValue(f, p.value)}
              class="jelly flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[12px]
                {picked
                  ? 'border-accent/60 bg-accent/10 text-ink'
                  : 'border-edge text-muted hover:bg-white/[0.04]'}"
            >
              <StatusDot status={p.value} size={11} />
              {p.label}
            </button>
          {/each}
        </div>
      <!-- The rotation pool is a fixed set, not free text. Typing "onlien"
           used to be accepted and then never match anything. -->
      {:else if f.key === "bot.status.statuses"}
        <div class="flex w-full flex-wrap justify-end gap-1.5 sm:w-80">
          {#each PRESENCES as p}
            {@const picked = Array.isArray(value(f)) && value(f).includes(p.value)}
            <button
              type="button"
              aria-pressed={picked}
              onclick={() => togglePresence(f, p.value)}
              class="jelly flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[12px]
                {picked
                  ? 'border-accent/60 bg-accent/10 text-ink'
                  : 'border-edge text-muted hover:bg-white/[0.04]'}"
            >
              <StatusDot status={p.value} size={11} />
              {p.label}
            </button>
          {/each}
        </div>
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

<ErrorNote text={loadError} onretry={() => { loadError = ""; schema.refresh({ force: true }); }} />

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

              <!-- What moves behind the app. Drawn from the theme variables
                   above, so each one takes on whatever palette is selected
                   rather than needing its own artwork. -->
              <div class="mt-5">
                <div class="mb-2 text-[12px] font-medium text-ink">Background</div>
                <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {#each BACKDROPS as b}
                    <button
                      onclick={() => backdropId.set(b.id)}
                      class="jelly relative overflow-hidden rounded-xl border p-3 text-left
                        {$backdropId === b.id
                          ? 'border-accent/60 bg-accent/10'
                          : 'border-edge hover:bg-white/[0.04]'}"
                    >
                      <span class="backdrop-swatch mb-2 h-10 w-full rounded-lg border border-edge/60"
                            data-kind={b.id}></span>
                      <span class="block truncate text-[12px] text-ink">{b.name}</span>
                      <span class="mt-0.5 block text-[10px] leading-snug text-faint">{b.hint}</span>
                    </button>
                  {/each}
                </div>
                {#if $customBgOn && $appearance.background.present && $backdropId !== "none"}
                  <p class="mt-2 text-[11px] leading-relaxed text-warn">
                    Your own image is switched on below, so it is showing instead.
                    Turn it off to see this again.
                  </p>
                {/if}
              </div>

              <!-- How solid the panels sitting on that background are. -->
              <div class="mt-5">
                <div class="mb-2 text-[12px] font-medium text-ink">Cards</div>
                <div class="grid grid-cols-3 gap-2">
                  {#each SURFACES as s}
                    <button
                      onclick={() => surfaceId.set(s.id)}
                      class="jelly rounded-xl border p-3 text-left
                        {$surfaceId === s.id
                          ? 'border-accent/60 bg-accent/10'
                          : 'border-edge hover:bg-white/[0.04]'}"
                    >
                      <span class="block truncate text-[12px] text-ink">{s.name}</span>
                      <span class="mt-0.5 block text-[10px] leading-snug text-faint">{s.hint}</span>
                    </button>
                  {/each}
                </div>
                <p class="mt-2 text-[11px] leading-relaxed text-faint">
                  Glass lets the background through every panel, which means the
                  machine re-blurs what is behind each one. If a busy page ever
                  feels heavy, Solid is the reason it is still here.
                </p>
              </div>

              <!-- A picture of your own, behind the whole panel. The themes
                   above still set the palette; this sits under them. -->
              <div class="mt-5 space-y-3">
                <Importer
                  title="Drop a background image here"
                  hint="Any format works, including HEIC straight off a phone. It is
                        converted for you, sits behind the whole panel, and the
                        theme you picked above still decides the colours."
                  accept="image/*,.heic,.heif,.avif,.bmp,.tif,.tiff"
                  busy={bgBusy}
                  busyLabel="Adding background"
                  onpick={(f) => uploadAppearance("background", f)}
                />

                {#if $appearance.background.present}
                  <div class="glass flex flex-wrap items-center gap-3 rounded-xl p-3">
                    <img
                      src="/api/appearance/background?v={$appearanceVersion}"
                      alt="" aria-hidden="true"
                      class="h-12 w-20 shrink-0 rounded-lg object-cover ring-1 ring-edge"
                    />
                    <div class="min-w-0 flex-1">
                      <div class="truncate text-[12px] text-ink">{$appearance.background.name}</div>
                      <div class="text-[11px] text-faint">
                        {Math.round(($appearance.background.size ?? 0) / 1024)} KB
                      </div>
                    </div>
                    <Toggle checked={$customBgOn} onchange={(v) => customBgOn.set(v)} />
                    <Button kind="ghost" size="sm" onclick={() => clearAppearance("background")}>
                      Remove
                    </Button>
                    <div class="flex w-full items-center gap-3">
                      <span class="shrink-0 text-[11px] text-muted">Dim</span>
                      <input
                        type="range" min="0" max="1" step="0.02"
                        value={$customBgDim}
                        oninput={(e) => customBgDim.set(parseFloat((e.target as HTMLInputElement).value))}
                        style="--fill: {Math.round($customBgDim * 100)}%"
                        class="slider min-w-0 flex-1"
                        disabled={!$customBgOn}
                      />
                      <span class="slider-value shrink-0 font-mono text-[12px] text-ink">
                        {Math.round($customBgDim * 100)}%
                      </span>
                    </div>
                    <p class="w-full text-[11px] leading-relaxed text-faint">
                      Dim is the theme's own background colour laid over the picture.
                      Turn it down to see more of the image, up if text is getting
                      hard to read.
                    </p>
                  </div>
                {/if}
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

                {#if $appearance.font.present}
                  <button
                    onclick={() => fontId.set(CUSTOM_FONT_ID)}
                    class="jelly rounded-xl border p-3 text-left
                      {$fontId === CUSTOM_FONT_ID
                        ? 'border-accent/60 bg-accent/10'
                        : 'border-edge hover:bg-white/[0.04]'}"
                  >
                    <div class="truncate text-[15px] text-ink" style="font-family: 'PanelCustom', ui-sans-serif, system-ui, sans-serif">
                      Yours
                    </div>
                    <div class="mt-0.5 truncate text-[11px] text-muted" style="font-family: 'PanelCustom', ui-sans-serif, system-ui, sans-serif">
                      The quick brown fox jumps
                    </div>
                    <div class="mt-1 truncate text-[10px] leading-snug text-faint">
                      {$appearance.font.name}
                    </div>
                  </button>
                {/if}
              </div>

              <div class="mt-4 space-y-3">
                <Importer
                  title="Drop a font file here"
                  hint="woff2, woff, ttf or otf. It is stored with the app, so the
                        panel looks the same from any machine you open it on."
                  accept=".woff2,.woff,.ttf,.otf,font/woff2,font/woff,font/ttf,font/otf"
                  busy={fontBusy}
                  busyLabel="Adding typeface"
                  onpick={(f) => uploadAppearance("font", f)}
                />
                {#if $appearance.font.present}
                  <div class="glass flex items-center gap-3 rounded-xl p-3">
                    <div class="min-w-0 flex-1">
                      <div class="truncate text-[12px] text-ink">{$appearance.font.name}</div>
                      <div class="text-[11px] text-faint">
                        {Math.round(($appearance.font.size ?? 0) / 1024)} KB
                      </div>
                    </div>
                    <Button kind="ghost" size="sm" onclick={() => clearAppearance("font")}>
                      Remove
                    </Button>
                  </div>
                {/if}
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
