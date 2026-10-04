<script lang="ts">
  /**
   * Settings as a file: Export, Import and the raw file, as one group of
   * buttons beside the search.
   *
   * Export saves every setting to a .json file. Your owner ID and keys stay out
   * of it unless you ask for them, because a settings file is the kind of thing
   * that gets passed around.
   *
   * Import never writes a file straight over your settings. The server reads it
   * setting by setting and this shows what would change, grouped the way the
   * Settings tabs are, with a box to untick any of them. Your owner ID, keys,
   * the local server's address and how this panel is reached start unticked:
   * a shared file is exactly how someone would try to change those.
   *
   * The file stays text all the way to the server. Parsed here, a Discord ID
   * (past 2^53) is rounded, and the rounded one would have been written back.
   */
  import { onDestroy } from "svelte";
  import { api } from "../api";
  import { toast } from "../stores";
  import { saveTextFile } from "../window";
  import { fmtDate } from "../fmt";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import Modal from "./Modal.svelte";
  import Toggle from "./Toggle.svelte";
  import NotHere from "./NotHere.svelte";
  import { notHere } from "../device";

  let { onraw, onimported } = $props<{
    /** Open the raw editor. */
    onraw: () => void;
    /** Settings were written: reload what the page shows. */
    onimported?: () => void;
  }>();

  type Change = {
    key: string; label: string; section: string; old: unknown; new: unknown;
    guarded: boolean; why: string; restart: boolean;
  };
  type Plan = {
    meta: { version?: string; exported_at?: string; personal?: boolean };
    changes: Change[]; same: number; skipped: { key: string; label: string; reason: string }[];
  };

  // ── Export ─────────────────────────────────────────────────────────────
  let exportOpen = $state(false);
  let withPersonal = $state(false);
  let exporting = $state(false);
  let group = $state<HTMLElement | null>(null);

  function away(e: PointerEvent) {
    if (group && !group.contains(e.target as Node)) exportOpen = false;
  }
  function esc(e: KeyboardEvent) {
    if (e.key === "Escape") exportOpen = false;
  }
  $effect(() => {
    if (!exportOpen) return;
    window.addEventListener("pointerdown", away, true);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("pointerdown", away, true);
      window.removeEventListener("keydown", esc);
    };
  });

  async function doExport() {
    exporting = true;
    try {
      const r = await api.exportSettings(withPersonal);
      const where = await saveTextFile(r.filename, r.text);
      exportOpen = false;
      // "" is a Save dialog closed without saving: nothing to report.
      if (where) toast(`Saved ${r.count} settings${where.includes("\\") || where.includes("/") ? ` to ${where}` : ""}.`, "ok");
      else if (!(window as any).pywebview?.api) toast(`Downloaded ${r.count} settings.`, "ok");
    } catch (e: any) {
      toast(e?.message || "Could not export the settings", "err");
    } finally {
      exporting = false;
    }
  }

  // ── Import ─────────────────────────────────────────────────────────────
  let fileInput = $state<HTMLInputElement | null>(null);
  let fileName = $state("");
  let fileText = $state("");
  let reading = $state(false);
  let plan = $state<Plan | null>(null);
  let picked = $state<Set<string>>(new Set());
  let applying = $state(false);
  let showSkipped = $state(false);

  function pickFile() {
    exportOpen = false;
    fileInput?.click();
  }

  async function onFile(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";          // the same file can be picked again after a Cancel
    if (!file) return;
    if (file.size > 2_000_000) {
      toast("That file is too big to be a settings file.", "err");
      return;
    }
    reading = true;
    try {
      const text = await file.text();
      const p: Plan = await api.importPreview(text);
      fileName = file.name;
      fileText = text;
      plan = p;
      picked = new Set(p.changes.filter((c) => !c.guarded).map((c) => c.key));
      showSkipped = false;
    } catch (err: any) {
      toast(err?.message || "Could not read that file", "err");
    } finally {
      reading = false;
    }
  }

  function close() {
    plan = null;
    fileText = "";
  }

  function flip(key: string) {
    const next = new Set(picked);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    picked = next;
  }

  async function apply() {
    if (!plan || !picked.size) return;
    applying = true;
    try {
      const r = await api.importSettings(fileText, [...picked]);
      toast(`Imported ${r.applied} setting${r.applied === 1 ? "" : "s"}.`
        + (r.restart?.length ? " Some apply after the account restarts." : "")
        + " The old ones are in backups.", "ok");
      close();
      onimported?.();
    } catch (e: any) {
      toast(e?.message || "Could not import the settings", "err");
    } finally {
      applying = false;
    }
  }

  /** The changes in the order the Settings tabs go, personal and careful ones last. */
  const groups = $derived.by(() => {
    if (!plan) return [] as { name: string; guarded: boolean; items: Change[] }[];
    const out: { name: string; guarded: boolean; items: Change[] }[] = [];
    const bySection = new Map<string, Change[]>();
    for (const c of plan.changes.filter((c) => !c.guarded)) {
      if (!bySection.has(c.section)) bySection.set(c.section, []);
      bySection.get(c.section)!.push(c);
    }
    for (const [name, items] of bySection) out.push({ name, guarded: false, items });
    const guarded = plan.changes.filter((c) => c.guarded);
    if (guarded.length) out.push({ name: "Left as they are unless you tick them", guarded: true, items: guarded });
    return out;
  });
  const allPicked = $derived(!!plan && plan.changes.length > 0 && picked.size === plan.changes.length);

  function pickAll(on: boolean) {
    picked = new Set(on && plan ? plan.changes.map((c) => c.key) : []);
  }

  /** A value the way the Settings rows say it. */
  function show(v: unknown): string {
    if (v === null || v === undefined) return "Default";
    if (typeof v === "boolean") return v ? "On" : "Off";
    if (typeof v === "number") return v.toLocaleString();
    if (typeof v === "string") return v === "" ? "Empty" : v.length > 34 ? v.slice(0, 33) + "…" : v;
    if (Array.isArray(v)) {
      if (!v.length) return "None";
      const plain = v.every((x) => typeof x !== "object" || x === null) ? v.join(", ") : "";
      return plain && plain.length <= 34 ? plain : `${v.length} item${v.length === 1 ? "" : "s"}`;
    }
    const n = Object.keys(v as object).length;
    return `${n} entr${n === 1 ? "y" : "ies"}`;
  }
  const full = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

  const WHEN: Intl.DateTimeFormatOptions = { dateStyle: "medium", timeStyle: "short" };
  function when(iso?: string): string {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(+d) ? "" : fmtDate(d, WHEN);
  }

  onDestroy(() => (exportOpen = false));
</script>

<div class="sf" bind:this={group}>
  <div class="sf-group" role="group" aria-label="Settings file">
    <button class="sf-btn is-export" class:is-open={exportOpen} aria-expanded={exportOpen} aria-haspopup="dialog"
            onclick={() => (exportOpen = !exportOpen)} disabled={!!$notHere("files_save")}
            title={$notHere("files_save")?.why ?? "Save every setting to a file"}>
      <Icon name="download" size={13} /> Export
    </button>
    <button class="sf-btn is-import" class:is-busy={reading} onclick={pickFile} disabled={reading || !!$notHere("files_pick")}
            title={$notHere("files_pick")?.why ?? "Load settings from a file, after a look at what changes"}>
      <Icon name="upload" size={13} /> {reading ? "Reading" : "Import"}
    </button>
    <span class="sf-sep" aria-hidden="true"></span>
    <button class="sf-btn is-raw" onclick={() => { exportOpen = false; onraw(); }} title="Edit the whole config as JSON">
      <Icon name="braces" size={13} /> Raw file
    </button>
  </div>
  <NotHere feature="files_save" variant="chip" />
  <input bind:this={fileInput} type="file" accept=".json,application/json" class="hidden" onchange={onFile} />

  {#if exportOpen}
    <div class="sf-pop" role="dialog" aria-label="Export settings">
      <div class="flex items-start gap-3">
        <span class="sf-pop-mark"><Icon name="download" size={16} /></span>
        <div class="min-w-0">
          <div class="text-[13.5px] font-semibold text-ink">Export settings</div>
          <div class="mt-0.5 text-[11.5px] text-faint">Every setting, in one .json file.</div>
        </div>
      </div>
      <div class="sf-opt">
        <Toggle size="sm" bind:checked={withPersonal} name="Include my owner ID and keys" />
        <span class="min-w-0">
          <span class="block text-[12.5px] text-ink">Include my owner ID and keys</span>
          <span class="block text-[11px] text-faint">Only for a backup of your own.</span>
        </span>
      </div>
      <Button size="sm" onclick={doExport} loading={exporting}>
        {#if !exporting}<Icon name="download" size={12} />{/if} Save file
      </Button>
    </div>
  {/if}
</div>

<Modal open={!!plan} title="Import settings" onclose={close}>
  {#if plan}
    <div class="sf-file">
      <span class="sf-file-mark"><Icon name="braces" size={16} /></span>
      <div class="min-w-0 flex-1">
        <div class="truncate text-[13px] font-medium text-ink">{fileName}</div>
        <div class="truncate text-[11px] text-faint">
          {[plan.meta.version ? `From version ${plan.meta.version}` : "", when(plan.meta.exported_at)].filter(Boolean).join(" · ") || "A settings file"}
        </div>
      </div>
    </div>

    <div class="sf-chips">
      <span class="sf-chip is-change">{plan.changes.length} to change</span>
      {#if plan.same}<span class="sf-chip">{plan.same} already the same</span>{/if}
      {#if plan.skipped.length}
        <button class="sf-chip is-skip" onclick={() => (showSkipped = !showSkipped)} aria-expanded={showSkipped}>
          {plan.skipped.length} not imported <Icon name="chevron" size={10} />
        </button>
      {/if}
    </div>

    {#if showSkipped}
      <ul class="sf-skipped">
        {#each plan.skipped as s (s.key)}
          <li><span class="text-ink/80">{s.label}</span> <span class="text-faint">{s.reason}</span></li>
        {/each}
      </ul>
    {/if}

    {#if plan.changes.length}
      <div class="sf-list">
        {#each groups as g (g.name)}
          <div class="sf-group-name" class:is-guarded={g.guarded}>
            {#if g.guarded}<Icon name="alert" size={11} />{/if}{g.name}
          </div>
          {#each g.items as c (c.key)}
            <label class="sf-row" class:is-off={!picked.has(c.key)} class:is-guarded={c.guarded} title={c.key}>
              <input type="checkbox" checked={picked.has(c.key)} onchange={() => flip(c.key)} />
              <span class="min-w-0 flex-1">
                <span class="flex items-center gap-1.5">
                  <span class="truncate text-[12.5px] text-ink">{c.label}</span>
                  {#if c.restart}<span class="sf-tag">restart</span>{/if}
                </span>
                {#if c.why}<span class="block truncate text-[10.5px] text-faint">{c.why}</span>{/if}
              </span>
              <span class="sf-vals">
                <span class="sf-old" title={full(c.old)}>{show(c.old)}</span>
                <span class="sf-arrow" aria-hidden="true">→</span>
                <span class="sf-new" title={full(c.new)}>{show(c.new)}</span>
              </span>
            </label>
          {/each}
        {/each}
      </div>
    {:else}
      <div class="sf-none">
        <Icon name="check" size={18} />
        <span>Nothing to change. Every setting in this file is already set this way.</span>
      </div>
    {/if}

    <div class="sf-foot">
      {#if plan.changes.length > 1}
        <button class="sf-link" onclick={() => pickAll(!allPicked)}>{allPicked ? "Untick all" : "Tick all"}</button>
      {/if}
      <span class="flex-1"></span>
      <Button kind="ghost" size="sm" onclick={close}>{plan.changes.length ? "Cancel" : "Close"}</Button>
      {#if plan.changes.length}
        <Button size="sm" onclick={apply} loading={applying} disabled={!picked.size}>
          Import {picked.size} setting{picked.size === 1 ? "" : "s"}
        </Button>
      {/if}
    </div>
  {/if}
</Modal>

<style>
  .sf { position: relative; }

  /* ── The buttons: one quiet group, so three reads as one control ───────── */
  .sf-group {
    display: inline-flex;
    align-items: stretch;
    gap: 2px;
    padding: 3px;
    border-radius: 12px;
    background: rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px var(--color-edge);
  }
  .sf-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 11px;
    border-radius: 9px;
    font-size: 12.5px;
    font-weight: 500;
    color: var(--color-muted);
    white-space: nowrap;
    transition: background-color 0.15s ease, color 0.15s ease, transform 0.35s var(--jelly);
  }
  .sf-btn :global(svg) { color: var(--color-faint); transition: color 0.15s ease, transform 0.35s var(--jelly); }
  .sf-btn:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.06); }
  .sf-btn:hover:not(:disabled) :global(svg) { color: var(--color-accent); }
  .sf-btn:active:not(:disabled) { transform: scale(0.95); }
  .sf-btn:focus-visible { outline: none; box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-accent) 55%, transparent); }
  .sf-btn:disabled { cursor: default; }
  /* Each arrow nudges the way the file goes: down into a file, up out of one. */
  .sf-btn.is-export:hover :global(svg) { transform: translateY(1.5px); }
  .sf-btn.is-import:hover:not(:disabled) :global(svg) { transform: translateY(-1.5px); }
  .sf-btn.is-busy :global(svg) { animation: sf-bob 0.9s ease-in-out infinite; }
  @keyframes sf-bob { 50% { transform: translateY(-2px); } }
  .sf-btn.is-open {
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .sf-btn.is-open :global(svg) { color: var(--color-accent); }
  .sf-sep { width: 1px; margin: 5px 1px; background: var(--color-edge); }

  /* ── Export's little card ─────────────────────────────────────────────── */
  .sf-pop {
    position: absolute;
    top: calc(100% + 8px);
    right: 0;
    z-index: 30;
    display: flex;
    width: 272px;
    flex-direction: column;
    gap: 12px;
    padding: 14px;
    border-radius: 14px;
    background: color-mix(in srgb, var(--color-card) 96%, white);
    box-shadow: 0 0 0 1px var(--color-edge), 0 16px 40px -12px rgb(0 0 0 / 0.65);
    transform-origin: 85% 0;
    animation: sf-pop-in 0.26s var(--jelly) both;
  }
  @keyframes sf-pop-in {
    from { opacity: 0; transform: translateY(-6px) scale(0.96); }
  }
  .sf-pop-mark,
  .sf-file-mark {
    display: grid;
    width: 32px;
    height: 32px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 10px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 13%, transparent);
  }
  .sf-opt {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 10px;
    border-radius: 11px;
    background: rgb(255 255 255 / 0.03);
  }

  /* ── Import's preview ─────────────────────────────────────────────────── */
  .sf-file {
    display: flex;
    align-items: center;
    gap: 11px;
    padding: 10px 12px;
    border-radius: 12px;
    background: rgb(255 255 255 / 0.03);
  }
  .sf-chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0 10px; }
  .sf-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 9px;
    border-radius: 999px;
    font-size: 11px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
  }
  .sf-chip.is-change { color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 13%, transparent); }
  .sf-chip.is-skip { color: var(--color-warn); background: color-mix(in srgb, var(--color-warn) 11%, transparent); }
  .sf-chip.is-skip :global(svg) { transform: rotate(90deg); transition: transform 0.25s var(--jelly); }
  .sf-chip.is-skip[aria-expanded="true"] :global(svg) { transform: rotate(-90deg); }
  .sf-skipped {
    display: flex;
    max-height: 120px;
    flex-direction: column;
    gap: 3px;
    margin-bottom: 10px;
    padding: 8px 12px;
    overflow-y: auto;
    border-radius: 10px;
    font-size: 11.5px;
    background: color-mix(in srgb, var(--color-warn) 5%, transparent);
  }
  .sf-list {
    max-height: min(46vh, 420px);
    margin: 0 -6px;
    padding: 0 6px;
    overflow-y: auto;
  }
  .sf-group-name {
    display: flex;
    align-items: center;
    gap: 5px;
    margin: 12px 0 5px;
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--color-faint);
  }
  .sf-group-name:first-child { margin-top: 2px; }
  .sf-group-name.is-guarded { color: var(--color-warn); }
  .sf-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 10px;
    border-radius: 10px;
    cursor: pointer;
    transition: background-color 0.15s ease, opacity 0.2s ease;
  }
  .sf-row:hover { background: rgb(255 255 255 / 0.04); }
  .sf-row.is-off { opacity: 0.55; }
  .sf-row.is-off:hover { opacity: 0.8; }
  /* A box drawn to match the rest: the system's own came out as a flat grey square when unticked. */
  .sf-row input {
    display: grid;
    width: 16px;
    height: 16px;
    flex-shrink: 0;
    margin: 0;
    place-items: center;
    appearance: none;
    border-radius: 5px;
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1.5px rgb(255 255 255 / 0.24);
    cursor: pointer;
    transition: background-color 0.15s ease, box-shadow 0.15s ease, transform 0.3s var(--jelly);
  }
  .sf-row input::after {
    content: "";
    width: 8px;
    height: 4.5px;
    border: solid rgb(22 16 28);
    border-width: 0 0 2px 2px;
    transform: translateY(-1px) rotate(-45deg) scale(0);
    transition: transform 0.25s var(--jelly);
  }
  .sf-row input:checked { background: var(--color-accent); box-shadow: none; }
  .sf-row input:checked::after { transform: translateY(-1px) rotate(-45deg) scale(1); }
  .sf-row.is-guarded input:checked { background: var(--color-warn); }
  .sf-row input:focus-visible { outline: 2px solid color-mix(in srgb, var(--color-accent) 60%, transparent); outline-offset: 2px; }
  .sf-row:active input { transform: scale(0.88); }
  .sf-tag {
    flex-shrink: 0;
    padding: 0 6px;
    border-radius: 999px;
    font-size: 9.5px;
    color: var(--color-warn);
    background: color-mix(in srgb, var(--color-warn) 12%, transparent);
  }
  .sf-vals {
    display: inline-flex;
    max-width: 52%;
    flex-shrink: 0;
    align-items: center;
    gap: 6px;
    font-size: 11.5px;
    font-variant-numeric: tabular-nums;
  }
  .sf-old,
  .sf-new { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sf-old { color: var(--color-faint); text-decoration: line-through; text-decoration-color: rgb(255 255 255 / 0.2); }
  .sf-new { color: var(--color-ink); font-weight: 500; }
  .sf-arrow { flex-shrink: 0; color: var(--color-faint); }
  .sf-none {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px;
    border-radius: 12px;
    font-size: 12.5px;
    color: var(--color-muted);
    background: color-mix(in srgb, var(--color-good) 7%, transparent);
  }
  .sf-none :global(svg) { flex-shrink: 0; color: var(--color-good); }
  .sf-foot {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid var(--color-edge);
  }
  .sf-link { font-size: 12px; color: var(--color-muted); }
  .sf-link:hover { color: var(--color-ink); text-decoration: underline; }

  :global(:root[data-motion="off"]) .sf-pop,
  :global(:root[data-motion="off"]) .sf-btn,
  :global(:root[data-motion="off"]) .sf-row input,
  :global(:root[data-motion="off"]) .sf-row input::after,
  :global(:root[data-motion="off"]) .sf-btn :global(svg) { animation: none; transition: none; }
</style>
