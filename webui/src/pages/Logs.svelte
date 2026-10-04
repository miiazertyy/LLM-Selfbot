<script lang="ts">
  /**
   * Logs, made to be read.
   *
   * It was a terminal in a box: monospace lines, a coloured dot each, sources
   * named "discord_1", and a message someone sent split across three lines
   * with a row of box-drawing characters under it. Everything useful was in
   * there and nothing stood out.
   *
   * Now each thing that happened is one row: an icon for what kind of thing it
   * was, who it came from by name (the account's own name and picture), and
   * the text, with a message that came in or went out shown as the message,
   * quoted under the line that introduced it. Kinds and sources filter with
   * one click and say how many there are; the last hour is a bar chart that
   * filters to a minute when clicked; newest-first or oldest-first is a toggle.
   *
   * It keeps the performance work of the old page: a bounded ring buffer
   * mutated in place, keyed rows, a debounced search, and no highlighting at
   * all unless something is being searched for.
   */
  import { onMount, tick } from "svelte";
  import { get } from "svelte/store";
  import { api } from "../lib/api";
  import { subscribeLogs } from "../lib/logsocket";
  import { logsFocus, toast } from "../lib/stores";
  import { saveTextFile } from "../lib/window";
  import { HOUR_MINUTE, fmtDate } from "../lib/fmt";
  import { chatAccounts, loadChatAccounts } from "../lib/chats";
  import Icon from "../lib/components/Icon.svelte";
  import LogRow from "../lib/components/LogRow.svelte";
  import { domino } from "../lib/domino";
  import { arriving } from "../lib/growin";
  import { openMenuAt } from "../lib/contextmenu";
  import { KINDS, foldRows, sourceInfo as sourceOf, type LogLine as Line, type LogRow as Row } from "../lib/logrows";

  let seq = 0;
  const MAX_LINES = 600;

  let lines = $state<Line[]>([]);
  let query = $state("");
  let q = $state("");
  let paused = $state(false);
  let compact = $state(false);
  let newestFirst = $state(readPref("logs.newestFirst", false));
  let box: HTMLDivElement | null = $state(null);
  let searchEl: HTMLInputElement | null = $state(null);
  let stick = $state(true);
  let fresh = $state(0);                 // lines that arrived while scrolled away
  let hidden = $state<Set<string>>(new Set());
  let levels = $state<Set<string>>(new Set());
  let minute = $state<number | null>(null);   // a bar clicked in the chart: that minute only
  let openRows = $state<Set<number>>(new Set());
  let now = $state(Date.now() / 1000);

  function readPref(key: string, fallback: boolean): boolean {
    try {
      const v = localStorage.getItem(key);
      return v === null ? fallback : v === "1";
    } catch {
      return fallback;
    }
  }
  $effect(() => {
    try { localStorage.setItem("logs.newestFirst", newestFirst ? "1" : "0"); } catch { /* private window */ }
  });

  // ── Kinds and sources: lib/logrows.ts, shared with the Dashboard's log widget ──
  /** Who a line came from, by name: the account's own name and picture, or the part of the app. */
  const sourceInfo = (s: string) => sourceOf(s, $chatAccounts);

  // ── Reading the stream ─────────────────────────────────────────────────
  onMount(() => {
    load();
    if (!get(chatAccounts).length) loadChatAccounts().catch(() => {});
    const clock = setInterval(() => (now = Date.now() / 1000), 15000);
    const off = subscribeLogs((entry) => {
      if (!entry.text) return;
      if (paused) return;
      push({ ...(entry as Line), ts: entry.ts || Date.now() / 1000 });
      if (stick) follow();
      else fresh++;
    });
    const key = (e: KeyboardEvent) => {
      // "/" jumps to the search, like most log viewers.
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
        e.preventDefault();
        searchEl?.focus();
      }
    };
    window.addEventListener("keydown", key);
    return () => {
      off();
      clearInterval(clock);
      window.removeEventListener("keydown", key);
    };
  });

  async function load() {
    try {
      const data = await api.logs(500);
      lines = (data.lines || []).map((l: Line) => ({ ...l, id: seq++ }));
    } catch {
      /* the stream fills it in */
    }
    // Opened from an account card: just that account.
    const want = get(logsFocus);
    if (want) {
      logsFocus.set("");
      hidden = new Set(sources.map((s) => s.id).filter((s) => s !== want));
    }
    await tick();
    // Straight to the newest, not gliding there: the lines coming in as the tab opens are the ones seen once there
    // (lib/domino.ts measures them the frame after they are put in), and a glide still on its way had them measured
    // at the top, so the newest lines came in with nothing.
    stick = true;
    fresh = 0;
    if (box) box.scrollTop = newestFirst ? 0 : box.scrollHeight;
  }

  /** One line in, the oldest out once full. Mutated in place: see the note at the top. */
  function push(entry: Line) {
    entry.id = seq++;
    if (lines.length >= MAX_LINES) lines.splice(0, lines.length - MAX_LINES + 1);
    lines.push(entry);
  }

  // One scroll per frame however many lines arrive in it.
  let followFrame = 0;
  function follow() {
    if (followFrame) return;
    followFrame = requestAnimationFrame(() => {
      followFrame = 0;
      if (!box) return;
      box.scrollTo({ top: newestFirst ? 0 : box.scrollHeight, behavior: "smooth" });
    });
  }
  function jump() {
    stick = true;
    fresh = 0;
    box?.scrollTo({ top: newestFirst ? 0 : box.scrollHeight, behavior: "smooth" });
  }
  function onScroll() {
    if (!box) return;
    stick = newestFirst ? box.scrollTop < 40 : box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    if (stick) fresh = 0;
  }
  $effect(() => {
    newestFirst;
    tick().then(jump);
  });

  // Search one beat behind the typing.
  $effect(() => {
    const v = query;
    const t = setTimeout(() => (q = v), 120);
    return () => clearTimeout(t);
  });

  // ── What a line says ───────────────────────────────────────────────────
  /** Lines into rows (lib/logrows.ts): continuations folded into the line they belong to, rules dropped. */
  const rows = $derived(foldRows(lines));

  const sources = $derived.by(() => {
    const counts = new Map<string, number>();
    for (const r of rows) counts.set(r.source, (counts.get(r.source) ?? 0) + 1);
    return [...counts.entries()].map(([id, n]) => ({ id, n, ...sourceInfo(id) }))
      .sort((a, b) => b.n - a.n);
  });

  const kindCounts = $derived.by(() => {
    const out: Record<string, number> = {};
    for (const r of rows) if (!hidden.has(r.source)) out[r.level] = (out[r.level] ?? 0) + 1;
    return out;
  });

  const shown = $derived.by(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const list = rows.filter((r) => {
      if (hidden.has(r.source)) return false;
      if (levels.size && !levels.has(r.level)) return false;
      if (minute !== null && (r.ts < minute || r.ts >= minute + 60)) return false;
      if (!words.length) return true;
      const hay = `${r.time} ${sourceInfo(r.source).name} ${r.text} ${r.more.join(" ")} ${r.think?.body ?? ""}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    });
    return newestFirst ? list.slice().reverse() : list;
  });

  // ── The last hour, as bars ─────────────────────────────────────────────
  const BUCKETS = 60;
  const chart = $derived.by(() => {
    const end = Math.floor(now / 60) * 60 + 60;
    const start = end - BUCKETS * 60;
    const bars = Array.from({ length: BUCKETS }, (_, i) => ({ t: start + i * 60, n: 0, bad: 0 }));
    for (const r of rows) {
      if (hidden.has(r.source) || r.ts < start || r.ts >= end) continue;
      const b = bars[Math.floor((r.ts - start) / 60)];
      b.n++;
      if (r.level === "error" || r.level === "warn") b.bad++;
    }
    const max = Math.max(1, ...bars.map((b) => b.n));
    const total = bars.reduce((s, b) => s + b.n, 0);
    const bad = bars.reduce((s, b) => s + b.bad, 0);
    const busiest = bars.reduce((a, b) => (b.n > a.n ? b : a), bars[0]);
    return { bars, max, total, bad, busiest };
  });
  const hhmm = (t: number) => fmtDate(t * 1000, HOUR_MINUTE);

  // ── Doing things ───────────────────────────────────────────────────────
  function toggleKind(id: string) {
    const next = new Set(levels);
    next.has(id) ? next.delete(id) : next.add(id);
    levels = next;
  }
  function toggleSource(id: string) {
    const next = new Set(hidden);
    next.has(id) ? next.delete(id) : next.add(id);
    hidden = next;
  }
  function only(id: string) {
    hidden = new Set(sources.map((s) => s.id).filter((s) => s !== id));
  }
  function toggleRow(id: number) {
    const next = new Set(openRows);
    next.has(id) ? next.delete(id) : next.add(id);
    openRows = next;
  }
  const filtering = $derived(!!(levels.size || hidden.size || minute !== null || q));
  function clearFilters() {
    levels = new Set();
    hidden = new Set();
    minute = null;
    query = "";
  }

  /** One entry as text: the line, whatever was quoted under it, and any thought. */
  function rowText(r: Row): string {
    return [`${r.time} [${sourceInfo(r.source).name}] ${r.text}`, ...r.more, r.think?.body ?? ""]
      .filter(Boolean).join("\n");
  }

  async function copyText(text: string, what = "Copied.") {
    try {
      await navigator.clipboard.writeText(text);
      toast(what, "ok");
    } catch {
      toast("Could not copy", "err");
    }
  }

  /** Right-click on an entry: the app's menu, with what can be done with it.
      A menu rather than a button on every row, which put a copy icon on each one. */
  function openMenu(e: MouseEvent, r: Row) {
    const picked = window.getSelection()?.toString().trim();
    openMenuAt(e, [
      picked && { label: "Copy the selection", icon: "copy", keys: "Ctrl C", run: () => copyText(picked) },
      { label: "Copy this entry", icon: "copy", run: () => copyText(rowText(r)) },
      r.text && { label: "Copy just the message", icon: "chats", run: () => copyText(r.text, "Copied the message.") },
      "sep",
      { label: `Only ${sourceInfo(r.source).name}`, icon: "accounts", run: () => only(r.source) },
      { label: "Only this kind", icon: "logs", run: () => (levels = new Set([r.level])) },
      "sep",
      { label: "Copy everything shown", icon: "clipboard",
        run: () => copyText(shown.map(rowText).join("\n"), `Copied ${shown.length} entries.`) },
    ]);
  }

  async function download() {
    const when = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    const text = shown
      .map((r) => [`${r.time} [${sourceInfo(r.source).name}] ${r.text}`, ...r.more.map((m) => `    ${m}`),
                   r.think?.body ? `    ${r.think.body.replace(/\n/g, "\n    ")}` : ""].filter(Boolean).join("\n"))
      .join("\n");
    try {
      const path = await saveTextFile(`LLMSelfbot-logs-${when}.txt`, text);
      if (path) toast(`Saved ${shown.length} entr${shown.length === 1 ? "y" : "ies"}.`, "ok");
    } catch (e: any) {
      toast(e.message || "Could not save the log", "err");
    }
  }

  /** Only new lines slide in; a filter change must not replay the whole list. */
  const isNew = (r: Row) => now - r.ts < 20 && r.id >= seq - 30;
</script>

<div class="lg">
  <!-- ── Find: search, order, and the switches ─────────────────────────── -->
  <div class="lg-bar glass">
    <div class="lg-search">
      <Icon name="search" size={15} />
      <input bind:this={searchEl} bind:value={query} placeholder="Search everything that happened" spellcheck="false" />
      {#if query}
        <button class="lg-x" onclick={() => (query = "")} aria-label="Clear search"><Icon name="close" size={12} /></button>
      {:else}
        <kbd class="lg-kbd">/</kbd>
      {/if}
    </div>
    <div class="lg-switches">
      <button class="lg-switch" class:is-on={!paused} onclick={() => (paused = !paused)}
              title={paused ? "Paused: new lines are not added" : "Live: new lines appear as they happen"}>
        {#if paused}<Icon name="play" size={11} />Paused{:else}<span class="lg-live"></span>Live{/if}
      </button>
      <button class="lg-switch" onclick={() => (newestFirst = !newestFirst)} title="Which end the newest lines are at">
        <Icon name="order" size={13} />{newestFirst ? "Newest first" : "Oldest first"}
      </button>
      <button class="lg-switch" class:is-on={compact} onclick={() => (compact = !compact)} title="One line per entry">
        <Icon name="collapse" size={12} />Compact
      </button>
      <button class="lg-switch" onclick={download} title="Save what is shown to a text file">
        <Icon name="upload" size={12} />Save
      </button>
    </div>

    <!-- What kind of thing, with how many of each. Nothing picked is everything. -->
    <div class="lg-chips domino" use:domino={{ step: 40, level: 0.5 }}>
      {#each KINDS as k (k.id)}
        {@const n = kindCounts[k.id] ?? 0}
        {#if n || levels.has(k.id)}
          <button class="lg-kind" data-kind={k.id} class:is-on={levels.has(k.id)} onclick={() => toggleKind(k.id)}>
            <Icon name={k.icon} size={12} />{k.label}<span class="lg-n">{n}</span>
          </button>
        {/if}
      {/each}
    </div>

    <!-- Who it came from, by name. Click to show or hide; double-click for only that one. -->
    {#if sources.length > 1}
      <div class="lg-chips">
        {#each sources as s (s.id)}
          <button class="lg-src" class:is-off={hidden.has(s.id)} onclick={() => toggleSource(s.id)}
                  ondblclick={() => only(s.id)} title="Click to hide or show, double-click to show only this">
            {#if s.avatar}<img src={s.avatar} alt="" />{:else}<span class="lg-src-icon"><Icon name={s.icon} size={11} /></span>{/if}
            {s.name}<span class="lg-n">{s.n}</span>
          </button>
        {/each}
      </div>
    {/if}
  </div>

  <!-- ── The last hour ─────────────────────────────────────────────────── -->
  <div class="lg-chart glass">
    <div class="lg-chart-head">
      <span class="text-[12.5px] font-semibold text-ink">The last hour</span>
      <span class="text-[11.5px] text-muted">
        {chart.total} entr{chart.total === 1 ? "y" : "ies"}{#if chart.bad} · <span class="text-warn">{chart.bad} problem{chart.bad === 1 ? "" : "s"}</span>{/if}
        {#if chart.busiest?.n} · busiest at {hhmm(chart.busiest.t)}{/if}
      </span>
      {#if minute !== null}
        <button class="lg-minute" onclick={() => (minute = null)}>
          {hhmm(minute)} only <Icon name="close" size={10} />
        </button>
      {/if}
    </div>
    <!-- As the tab opens the minutes grow up from the left, a dry tick each, higher the busier (lib/growin.ts). -->
    <div class="lg-bars" role="group" aria-label="Entries per minute, click a bar for that minute"
         use:arriving={{ heights: () => chart.bars.map((x) => x.n), stagger: 8, level: 0.7, sound: "wind" }}>
      {#each chart.bars as b, i (b.t)}
        <button class="lg-b" style="--i: {i}" class:is-sel={minute === b.t} class:is-dim={minute !== null && minute !== b.t}
                disabled={!b.n} onclick={() => (minute = minute === b.t ? null : b.t)}
                title="{hhmm(b.t)}: {b.n} entr{b.n === 1 ? 'y' : 'ies'}{b.bad ? `, ${b.bad} problem${b.bad === 1 ? '' : 's'}` : ''}">
          <span class="lg-b-fill" style="height:{(b.n / chart.max) * 100}%">
            {#if b.bad}<span class="lg-b-bad" style="height:{(b.bad / b.n) * 100}%"></span>{/if}
          </span>
        </button>
      {/each}
    </div>
    <div class="lg-axis"><span>60 min ago</span><span>30 min</span><span>now</span></div>
  </div>

  <!-- ── What happened ─────────────────────────────────────────────────── -->
  <div class="lg-stream glass">
    <div class="lg-stream-head">
      <span>{shown.length.toLocaleString()} of {rows.length.toLocaleString()}</span>
      {#if filtering}<button class="text-accent hover:underline" onclick={clearFilters}>show everything</button>{/if}
      {#if (kindCounts.error ?? 0) && !levels.has("error")}
        <button class="lg-errs" onclick={() => (levels = new Set(["error"]))}>
          {kindCounts.error} error{kindCounts.error === 1 ? "" : "s"}
        </button>
      {/if}
    </div>

    <!-- The newest lines come in one after another as the tab opens, a tick each, like a ticker starting up;
         after that, a new line slides in its own way (LogRow). -->
    <div class="lg-list domino" bind:this={box} onscroll={onScroll} class:is-compact={compact}
         use:domino={{ step: 28, sound: "wind", level: 0.8, max: 16, once: true }}>
      {#each shown as r (r.id)}
        <LogRow row={r} who={sourceInfo(r.source)} {q} {compact} open={openRows.has(r.id)} fresh={isNew(r)}
                ontoggle={() => toggleRow(r.id)} onmenu={(e) => openMenu(e, r)} />
      {:else}
        <div class="lg-empty">
          <Icon name={lines.length ? "search" : "logs"} size={22} />
          <p>{lines.length ? "Nothing matches that." : "Nothing has happened yet."}</p>
          {#if filtering}<button class="text-accent hover:underline" onclick={clearFilters}>Show everything</button>{/if}
        </div>
      {/each}
    </div>

    {#if !stick}
      <button class="lg-jump" onclick={jump}>
        <Icon name="chevron" size={11} />{fresh ? `${fresh} new` : newestFirst ? "Back to the newest" : "Jump to the newest"}
      </button>
    {/if}
  </div>
</div>

<style>
  .lg { display: flex; flex-direction: column; gap: 12px; }

  /* ── Find ───────────────────────────────────────────────────────── */
  .lg-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 12px; padding: 12px; border-radius: 18px; }
  .lg-search {
    display: flex;
    min-width: 220px;
    flex: 1;
    align-items: center;
    gap: 9px;
    padding: 9px 12px;
    border-radius: 12px;
    color: var(--color-faint);
    background: rgb(0 0 0 / 0.25);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    transition: box-shadow 0.18s ease;
  }
  .lg-search:focus-within { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, transparent), 0 0 0 3px color-mix(in srgb, var(--color-accent) 12%, transparent); }
  .lg-search input { min-width: 0; flex: 1; background: transparent; font-size: 13.5px; color: var(--color-ink); outline: none; }
  .lg-kbd {
    padding: 0 6px;
    border-radius: 5px;
    font-family: ui-monospace, monospace;
    font-size: 11px;
    color: var(--color-faint);
    box-shadow: inset 0 0 0 1px var(--color-edge);
  }
  .lg-x { display: inline-flex; padding: 2px; border-radius: 6px; }
  .lg-x:hover { color: var(--color-ink); }
  .lg-switches { display: flex; flex-wrap: wrap; gap: 6px; }
  .lg-switch {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 7px 11px;
    border-radius: 11px;
    font-size: 12px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    transition: color 0.15s ease, background-color 0.15s ease, transform 0.15s var(--spring);
  }
  .lg-switch:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.07); }
  .lg-switch:active { transform: scale(0.96); }
  .lg-switch.is-on { color: var(--color-ink); background: color-mix(in srgb, var(--color-accent) 14%, transparent); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 35%, transparent); }
  .lg-live { width: 7px; height: 7px; border-radius: 999px; background: var(--color-good); animation: lg-pulse 1.6s ease-in-out infinite; }

  .lg-chips { display: flex; width: 100%; flex-wrap: wrap; gap: 6px; }
  .lg-kind, .lg-src {
    --k: var(--color-muted);
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 9px 5px 8px;
    border-radius: 999px;
    font-size: 12px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.035);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
    transition: color 0.15s ease, background-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s var(--spring), opacity 0.15s ease;
  }
  .lg-kind :global(svg) { color: var(--k); }
  .lg-kind:hover, .lg-src:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.07); }
  .lg-kind:active, .lg-src:active { transform: scale(0.95); }
  .lg-kind.is-on {
    color: var(--color-ink);
    background: color-mix(in srgb, var(--k) 16%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--k) 45%, transparent);
  }
  .lg-n {
    min-width: 18px;
    padding: 0 5px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 600;
    text-align: center;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.06);
    font-variant-numeric: tabular-nums;
  }
  [data-kind="error"] { --k: var(--color-bad); }
  [data-kind="warn"] { --k: var(--color-warn); }
  [data-kind="recv"] { --k: var(--color-accent-2); }
  [data-kind="reply"] { --k: var(--color-good); }
  [data-kind="think"] { --k: color-mix(in srgb, var(--color-accent) 50%, #e879f9); }
  [data-kind="system"] { --k: var(--color-accent); }
  [data-kind="info"] { --k: var(--color-faint); }
  .lg-src img { width: 16px; height: 16px; border-radius: 999px; object-fit: cover; }
  .lg-src-icon { display: inline-flex; color: var(--color-faint); }
  .lg-src.is-off { opacity: 0.45; text-decoration: line-through; }

  /* ── The last hour ──────────────────────────────────────────────── */
  .lg-chart { padding: 12px 14px 8px; border-radius: 18px; }
  .lg-chart-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; margin-bottom: 8px; }
  .lg-minute {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    margin-left: auto;
    padding: 2px 9px;
    border-radius: 999px;
    font-size: 11.5px;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 18%, transparent);
  }
  .lg-bars { display: flex; height: 44px; align-items: flex-end; gap: 2px; }
  .lg-b {
    display: flex;
    height: 100%;
    flex: 1;
    align-items: flex-end;
    border-radius: 3px;
    transition: background-color 0.12s ease;
  }
  .lg-b:hover:not(:disabled) { background: rgb(255 255 255 / 0.05); }
  .lg-b:disabled { cursor: default; }
  .lg-b-fill {
    position: relative;
    display: flex;
    width: 100%;
    min-height: 0;
    flex-direction: column-reverse;
    overflow: hidden;
    border-radius: 3px 3px 1px 1px;
    background: color-mix(in srgb, var(--color-accent) 55%, transparent);
    transition: height 0.4s var(--spring), background-color 0.15s ease;
  }
  /* Growing up from the foot as the tab opens, a minute after the minute before (lib/growin.ts adds is-in). */
  .lg-b-fill { transform-origin: bottom; }
  .lg-bars:not(:global(.is-in)) .lg-b-fill { transform: scaleY(0); }
  .lg-bars:global(.is-in) .lg-b-fill { animation: lg-grow 0.5s var(--spring) backwards; animation-delay: calc(var(--i, 0) * 8ms); }
  @keyframes lg-grow { from { transform: scaleY(0); } }
  :global(:root[data-motion="off"]) .lg-b-fill { animation: none; transform: none; }
  .lg-b:hover .lg-b-fill, .lg-b.is-sel .lg-b-fill { background: var(--color-accent); }
  .lg-b.is-dim .lg-b-fill { background: color-mix(in srgb, var(--color-accent) 22%, transparent); }
  /* The problems in that minute, at the foot of its bar, with a gap above. */
  .lg-b-bad { width: 100%; border-top: 2px solid var(--color-card); background: var(--color-warn); }
  .lg-axis { display: flex; justify-content: space-between; margin-top: 5px; font-size: 10px; color: var(--color-faint); }

  /* ── What happened ──────────────────────────────────────────────── */
  .lg-stream { position: relative; overflow: hidden; border-radius: 18px; }
  .lg-stream-head {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 9px 16px;
    font-size: 11.5px;
    color: var(--color-faint);
    border-bottom: 1px solid color-mix(in srgb, var(--color-edge) 70%, transparent);
  }
  .lg-errs {
    margin-left: auto;
    padding: 1px 9px;
    border-radius: 999px;
    color: var(--color-bad);
    background: color-mix(in srgb, var(--color-bad) 14%, transparent);
  }
  .lg-list {
    height: max(360px, calc(100dvh - 430px));
    overflow-y: auto;
    padding: 6px;
  }
  /* The rows themselves: lib/components/LogRow.svelte, shared with the Dashboard. */
  .lg-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 60px 20px;
    font-size: 12.5px;
    color: var(--color-faint);
  }
  .lg-jump {
    position: absolute;
    left: 50%;
    bottom: 14px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 7px 14px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    color: var(--color-bg);
    background: var(--color-accent);
    box-shadow: 0 10px 26px -10px color-mix(in srgb, var(--color-accent) 80%, transparent);
    transform: translateX(-50%);
    animation: lg-pop 0.3s var(--spring) both;
  }
  .lg-jump :global(svg) { transform: rotate(90deg); }

  @keyframes lg-pop { from { opacity: 0; transform: translate(-50%, 8px) scale(0.9); } to { opacity: 1; transform: translateX(-50%); } }
  @keyframes lg-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
  :global(:root[data-motion="off"]) .lg-live { animation: none; }
</style>
