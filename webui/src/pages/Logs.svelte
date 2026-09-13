<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { toast } from "../lib/stores";
  import { saveTextFile } from "../lib/window";
  import { highlight } from "../lib/search";
  import Button from "../lib/components/Button.svelte";
  import Icon from "../lib/components/Icon.svelte";

  type Line = { time: string; source: string; text: string; level: string };

  let lines = $state<Line[]>([]);
  let query = $state("");
  let paused = $state(false);
  let wrap = $state(true);
  let ws: WebSocket | null = null;
  let box: HTMLDivElement | null = $state(null);
  let stick = $state(true);

  /**
   * Every source ever seen, kept separately from the visible lines.
   *
   * The old page refetched with a server side source filter and then rebuilt
   * this list from the filtered result, so choosing one source erased all the
   * others from the picker. You had to go back to "all" before you could pick
   * a different one. Filtering happens here now, against the full stream.
   */
  let sources = $state<string[]>([]);
  let hidden = $state<Set<string>>(new Set());     // sources switched off
  let levels = $state<Set<string>>(new Set());     // empty means every level

  const LEVELS = [
    { id: "error", label: "Errors", cls: "text-bad" },
    { id: "warn", label: "Warnings", cls: "text-warn" },
    { id: "recv", label: "Incoming", cls: "text-accent-2" },
    { id: "reply", label: "Replies", cls: "text-good" },
    { id: "system", label: "System", cls: "text-accent" },
  ];

  const shown = $derived.by(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    return lines.filter((l) => {
      if (hidden.has(l.source)) return false;
      if (levels.size && !levels.has(l.level)) return false;
      if (!words.length) return true;
      const hay = `${l.time} ${l.source} ${l.text}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    });
  });

  const counts = $derived.by(() => {
    const out: Record<string, number> = {};
    for (const l of lines) out[l.source] = (out[l.source] ?? 0) + 1;
    return out;
  });

  const errorCount = $derived(lines.filter((l) => l.level === "error").length);

  onMount(() => {
    load();
    connect();
    return () => ws?.close();
  });

  function remember(entry: Line) {
    if (!sources.includes(entry.source)) sources = [...sources, entry.source].sort();
  }

  async function load() {
    try {
      const data = await api.logs(500);
      lines = data.lines || [];
      for (const l of lines) remember(l);
    } catch {
      /* the stream below will fill it in */
    }
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/api/ws`);
    ws.onmessage = (e) => {
      const entry = JSON.parse(e.data);
      if (!entry.text) return;
      remember(entry);                 // keep the picker complete even if paused
      if (paused) return;
      lines = [...lines.slice(-499), entry];
      if (stick) queueMicrotask(() => box?.scrollTo({ top: box.scrollHeight }));
    };
  }

  function toggleSource(s: string) {
    const next = new Set(hidden);
    next.has(s) ? next.delete(s) : next.add(s);
    hidden = next;
  }

  function toggleLevel(id: string) {
    const next = new Set(levels);
    next.has(id) ? next.delete(id) : next.add(id);
    levels = next;
  }

  function onScroll() {
    if (!box) return;
    stick = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  }

  /**
   * A browser download is an anchor with a download attribute, and the
   * embedded WebView has no download handler for one: the button did nothing
   * at all, with nowhere to choose. saveTextFile uses the native Save dialog
   * on the desktop and a normal download in a browser.
   */
  async function download() {
    const when = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    const text = shown.map((l) => `${l.time} [${l.source}] ${l.text}`).join("\n");
    try {
      const path = await saveTextFile(`selfbot-logs-${when}.txt`, text);
      if (path) toast(`Saved ${shown.length} line${shown.length === 1 ? "" : "s"}.`, "ok");
    } catch (e: any) {
      toast(e.message || "Could not save the log", "err");
    }
  }

  /** Colour per kind of line. */
  const textClass = (level: string) =>
    level === "error" ? "text-bad"
    : level === "warn" ? "text-warn"
    : level === "reply" ? "text-good"
    : level === "recv" ? "text-accent-2"
    : level === "system" ? "text-ink/80"
    : "text-ink/70";

  const dotClass = (level: string) =>
    level === "error" ? "bg-bad"
    : level === "warn" ? "bg-warn"
    : level === "reply" ? "bg-good"
    : level === "recv" ? "bg-accent-2"
    : level === "system" ? "bg-accent"
    : "bg-white/20";
</script>

<div class="space-y-3">
  <!-- Controls, grouped: search, then what to show. -->
  <div class="glass p-3">
    <div class="flex flex-wrap items-center gap-2">
      <label class="relative min-w-[180px] flex-1">
        <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
          <Icon name="search" size={14} />
        </span>
        <input
          bind:value={query}
          class="field py-1.5 pl-8 pr-8 text-[12px]"
          placeholder="Search the log"
          spellcheck="false"
        />
        {#if query}
          <button
            class="jelly absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-faint hover:text-ink"
            onclick={() => (query = "")}
            aria-label="Clear search"
          >
            <Icon name="close" size={12} />
          </button>
        {/if}
      </label>

      <button
        onclick={() => (paused = !paused)}
        class="jelly flex shrink-0 items-center gap-1.5 rounded-[10px] border px-2.5 py-1.5 text-[12px]
          {paused ? 'border-warn/40 bg-warn/10 text-warn' : 'border-edge text-muted hover:bg-white/5'}"
      >
        <Icon name={paused ? "play" : "pause"} size={12} />
        {paused ? "Paused" : "Live"}
      </button>
      <button
        onclick={() => (wrap = !wrap)}
        title="Wrap long lines"
        class="jelly shrink-0 rounded-[10px] border px-2.5 py-1.5 text-[12px]
          {wrap ? 'border-accent/40 bg-accent/10 text-ink' : 'border-edge text-muted hover:bg-white/5'}"
      >
        Wrap
      </button>
      <Button kind="ghost" size="sm" onclick={download}>Download</Button>
    </div>

    <!-- Kinds of line. Nothing selected means everything, so the page never
         starts out hiding things. -->
    <div class="mt-2.5 flex flex-wrap items-center gap-1.5">
      <span class="mr-0.5 text-[10px] uppercase tracking-[0.12em] text-faint">Show</span>
      {#each LEVELS as l}
        <button
          onclick={() => toggleLevel(l.id)}
          class="jelly flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px]
            {levels.has(l.id)
              ? 'border-accent/50 bg-accent/15 text-ink'
              : 'border-edge text-muted hover:bg-white/[0.05] hover:text-ink'}"
        >
          <span class="h-1.5 w-1.5 rounded-full {dotClass(l.id)}"></span>
          {l.label}
        </button>
      {/each}
      {#if levels.size}
        <button class="text-[11px] text-accent hover:underline" onclick={() => (levels = new Set())}>
          show all kinds
        </button>
      {/if}
    </div>

    <!-- Sources toggle independently, so switching between two accounts does
         not mean going back through "all" each time. -->
    {#if sources.length > 1}
      <div class="mt-2 flex flex-wrap items-center gap-1.5">
        <span class="mr-0.5 text-[10px] uppercase tracking-[0.12em] text-faint">From</span>
        {#each sources as s}
          <button
            onclick={() => toggleSource(s)}
            class="jelly rounded-full border px-2.5 py-1 text-[11px]
              {hidden.has(s)
                ? 'border-edge text-faint line-through hover:text-muted'
                : 'border-accent/40 bg-accent/10 text-ink'}"
          >
            {s} <span class="text-faint">{counts[s] ?? 0}</span>
          </button>
        {/each}
        {#if hidden.size}
          <button class="text-[11px] text-accent hover:underline" onclick={() => (hidden = new Set())}>
            show all sources
          </button>
        {/if}
      </div>
    {/if}
  </div>

  <!-- The stream -->
  <div class="glass overflow-hidden">
    <div class="flex items-center gap-2 border-b border-edge px-3 py-2 text-[11px] text-faint">
      <span>{shown.length.toLocaleString()} of {lines.length.toLocaleString()} lines</span>
      {#if errorCount}
        <button
          onclick={() => toggleLevel("error")}
          class="rounded-full bg-bad/15 px-2 py-0.5 text-bad hover:bg-bad/25"
        >{errorCount} error{errorCount === 1 ? "" : "s"}</button>
      {/if}
      {#if !stick}
        <button
          class="jelly ml-auto rounded px-1.5 py-0.5 text-accent hover:bg-accent/10"
          onclick={() => { stick = true; box?.scrollTo({ top: box.scrollHeight, behavior: "smooth" }); }}
        >
          Jump to latest
        </button>
      {/if}
    </div>

    <div
      bind:this={box}
      onscroll={onScroll}
      class="selectable h-[56vh] overflow-y-auto bg-black/30 px-2 py-2 font-mono text-[11px] leading-[1.6]"
    >
      {#each shown as l}
        <div class="group flex gap-2 rounded px-1.5 py-[1px] hover:bg-white/[0.05]">
          <span class="mt-[6px] h-1.5 w-1.5 shrink-0 rounded-full {dotClass(l.level)}"></span>
          <span class="shrink-0 text-faint">{l.time}</span>
          <span class="w-24 shrink-0 truncate text-accent/80">{@html highlight(l.source, query)}</span>
          <span class="min-w-0 flex-1 {wrap ? 'break-words' : 'truncate'} {textClass(l.level)}">
            {@html highlight(l.text, query)}
          </span>
        </div>
      {:else}
        <div class="px-2 py-8 text-center text-muted">
          {lines.length ? "Nothing matches those filters." : "No log lines yet."}
        </div>
      {/each}
    </div>
  </div>
</div>
