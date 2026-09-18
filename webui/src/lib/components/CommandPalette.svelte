<script lang="ts">
  import { buildIndex, search, highlight, indexAge, type Hit } from "../search";
  import Icon from "./Icon.svelte";

  let { open = false, onclose, routes, onpick } = $props<{
    open?: boolean;
    onclose?: () => void;
    routes: Record<string, { title: string; section: string }>;
    onpick?: (id: string) => void;
  }>();

  let q = $state("");
  let sel = $state(0);
  let loading = $state(false);
  let hits = $state<Hit[]>([]);
  let input: HTMLInputElement | null = $state(null);

  async function refresh() {
    if (indexAge() < 15000) return;
    loading = true;
    await buildIndex(routes);
    loading = false;
  }

  $effect(() => {
    if (open) {
      q = "";
      sel = 0;
      refresh().then(() => (hits = search(q)));
      queueMicrotask(() => input?.focus());
    }
  });

  // Debounced: search() sweeps the whole index - every settings field, secret,
  // account, memory user, picture and 250 log lines - and this ran on every
  // keystroke.
  let qDebounced = $state("");
  $effect(() => {
    const v = q;
    const t = setTimeout(() => { qDebounced = v; }, 120);
    return () => clearTimeout(t);
  });

  $effect(() => {
    hits = search(qDebounced);
    sel = 0;
  });

  // Group consecutive hits under their section heading.
  const grouped = $derived(
    hits.reduce<{ group: string; items: { hit: Hit; i: number }[] }[]>((acc, hit, i) => {
      const last = acc[acc.length - 1];
      if (last && last.group === hit.group) last.items.push({ hit, i });
      else acc.push({ group: hit.group, items: [{ hit, i }] });
      return acc;
    }, []),
  );

  /** A face for each folder, from the icon set the rest of the panel uses. */
  const FOLDER_ICON: Record<string, string> = {
    Pages: "command",
    Settings: "settings",
    Accounts: "accounts",
    Memory: "memory",
    Pictures: "pictures",
    Logs: "logs",
    Secrets: "system",
  };

  /**
   * Which folders are open.
   *
   * Everything is open while searching - hiding a match behind a closed folder
   * would be the one thing a search must never do. With no query it is a
   * browsable index instead, so only Pages starts open and the rest wait to be
   * asked for.
   */
  let collapsed = $state<Record<string, boolean>>({});
  const isOpen = (g: string) => (qDebounced ? true : !collapsed[g]);

  function toggleFolder(g: string) {
    if (qDebounced) return;   // nothing to fold away while searching
    collapsed = { ...collapsed, [g]: !collapsed[g] };
  }

  $effect(() => {
    if (!open) return;
    // Reopened: browse mode again, everything but Pages folded away.
    collapsed = Object.fromEntries(
      Object.keys(FOLDER_ICON).filter((g) => g !== "Pages").map((g) => [g, true]),
    );
  });

  /** Indices that the arrow keys may land on: rows inside open folders only. */
  const reachable = $derived(
    grouped.filter((g) => isOpen(g.group)).flatMap((g) => g.items.map((it) => it.i)),
  );

  function step(delta: number) {
    if (!reachable.length) return;
    const at = reachable.indexOf(sel);
    // Selection sitting in a closed folder: jump to the nearest reachable row
    // rather than refusing to move.
    const next = at === -1
      ? (delta > 0 ? 0 : reachable.length - 1)
      : Math.min(Math.max(at + delta, 0), reachable.length - 1);
    sel = reachable[next];
  }

  // ── The travelling highlight ────────────────────────────────────────────
  // One element moved between rows, rather than a background switched on and
  // off, so the selection slides and settles instead of blinking across.
  let listEl: HTMLElement | null = $state(null);
  let pill = $state({ y: 0, h: 0, shown: false });

  function placePill() {
    if (!listEl) return;
    const row = listEl.querySelector<HTMLElement>(`#pal-${sel}`);
    if (!row) {
      pill = { ...pill, shown: false };
      return;
    }
    pill = { y: row.offsetTop, h: row.offsetHeight, shown: true };
  }

  $effect(() => {
    // Re-read after the rows have actually been laid out, and again once the
    // folder transition has settled, or the pill lands where a row used to be.
    void sel; void hits; void collapsed; void qDebounced;
    if (!open) return;
    requestAnimationFrame(placePill);
    const t = setTimeout(placePill, 360);
    return () => clearTimeout(t);
  });

  function choose(h: Hit) {
    if (h.action) h.action();
    else onpick?.(h.route);
    onclose?.();
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") return onclose?.();
    if (e.key === "ArrowDown") { e.preventDefault(); step(1); }
    if (e.key === "ArrowUp") { e.preventDefault(); step(-1); }
    // Left and right fold the group the selection is in, so the whole thing is
    // reachable without leaving the keyboard.
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      const g = hits[sel]?.group;
      if (g && !qDebounced) {
        e.preventDefault();
        collapsed = { ...collapsed, [g]: e.key === "ArrowLeft" };
      }
    }
    if (e.key === "Enter" && hits[sel]) { e.preventDefault(); choose(hits[sel]); }
  }

  $effect(() => {
    if (!open) return;
    document.getElementById(`pal-${sel}`)?.scrollIntoView({ block: "nearest" });
  });
</script>

{#if open}
  <div
    class="palette-scrim fixed inset-0 z-50 flex items-start justify-center bg-black/55 p-4 pt-[12vh] backdrop-blur-sm"
    role="dialog"
    aria-modal="true"
    aria-label="Search"
    tabindex="-1"
    onclick={(e) => e.target === e.currentTarget && onclose?.()}
    onkeydown={onKey}
  >
    <div class="palette glass floating glow w-[min(660px,95vw)] overflow-hidden p-0">
      <div class="flex items-center gap-3 border-b border-edge px-4 py-3">
        <Icon name="search" size={17} class="shrink-0 text-muted" />
        <input
          bind:this={input}
          bind:value={q}
          class="w-full bg-transparent text-[15px] text-ink outline-none placeholder:text-faint"
          placeholder="Search settings, accounts, memory, pictures, logs…"
          spellcheck="false"
        />
        {#if loading}
          <span class="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border border-muted border-t-transparent"></span>
        {:else}
          <kbd class="shrink-0 rounded border border-edge px-1.5 py-0.5 text-[10px] text-faint">esc</kbd>
        {/if}
      </div>

      <div bind:this={listEl} class="relative max-h-[52vh] overflow-y-auto py-2">
        <!-- Behind the rows, so it reads as the row lighting up rather than a
             shape sliding over the top of it. -->
        <div
          class="palette-pill"
          data-shown={pill.shown}
          style="height: {pill.h}px; transform: translate3d(0, {pill.y}px, 0)"
          aria-hidden="true"
        ></div>

        {#if !hits.length}
          <div class="px-4 py-10 text-center text-sm text-muted">
            {q ? `Nothing matches “${q}”` : "Start typing, or open a folder below"}
          </div>
        {:else}
          {#each grouped as g (g.group)}
            {@const openFolder = isOpen(g.group)}
            <button
              class="folder-head jelly relative flex w-full items-center gap-2 px-3 py-1.5 text-left"
              aria-expanded={openFolder}
              onclick={() => toggleFolder(g.group)}
              title={qDebounced ? "Everything is shown while searching" : "Open or close this folder"}
            >
              <span class="folder-chevron shrink-0 text-faint">
                <Icon name="chevron" size={12} />
              </span>
              <span class="shrink-0 text-accent/80"><Icon name={FOLDER_ICON[g.group] ?? "command"} size={13} /></span>
              <span class="text-[10px] font-semibold uppercase tracking-widest text-faint">{g.group}</span>
              <span class="folder-count ml-auto shrink-0 rounded-full px-1.5 py-0.5 text-[10px]
                           {openFolder ? 'bg-accent/15 text-accent' : 'bg-white/[0.06] text-muted'}">
                {g.items.length}
              </span>
            </button>

            <div class="folder-body" data-open={openFolder}>
              <div class="folder-inner">
                {#each g.items as { hit, i }, n (hit.route + hit.title + i)}
                  <button
                    id={`pal-${i}`}
                    class="palette-row relative flex w-full items-center gap-3 rounded-xl px-4 py-2 text-left
                           {i === sel ? 'text-ink' : 'hover:bg-white/[0.04]'}"
                    style="--i: {Math.min(n, 10)}"
                    onclick={() => choose(hit)}
                    onmouseenter={() => (sel = i)}
                  >
                    <span class="min-w-0 flex-1">
                      <span class="block truncate text-sm text-ink">{@html highlight(hit.title, qDebounced)}</span>
                      {#if hit.subtitle}
                        <span class="block truncate text-[11px] text-muted">{@html highlight(hit.subtitle, qDebounced)}</span>
                      {/if}
                    </span>
                    {#if i === sel}
                      <span class="pop shrink-0 text-accent"><Icon name="chevron" size={14} /></span>
                    {/if}
                  </button>
                {/each}
              </div>
            </div>
          {/each}
        {/if}
      </div>

      <div class="flex items-center gap-3 border-t border-edge px-4 py-2 text-[10px] text-faint">
        <span><kbd class="rounded border border-edge px-1">↑</kbd><kbd class="ml-0.5 rounded border border-edge px-1">↓</kbd> navigate</span>
        <span><kbd class="rounded border border-edge px-1">↵</kbd> open</span>
        <span class="ml-auto">{hits.length} result{hits.length === 1 ? "" : "s"}</span>
      </div>
    </div>
  </div>
{/if}
