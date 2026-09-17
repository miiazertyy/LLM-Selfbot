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

  function choose(h: Hit) {
    if (h.action) h.action();
    else onpick?.(h.route);
    onclose?.();
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") return onclose?.();
    if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); }
    if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(sel - 1, 0); }
    if (e.key === "Enter" && hits[sel]) { e.preventDefault(); choose(hits[sel]); }
  }

  $effect(() => {
    if (!open) return;
    document.getElementById(`pal-${sel}`)?.scrollIntoView({ block: "nearest" });
  });
</script>

{#if open}
  <div
    class="fixed inset-0 z-50 flex items-start justify-center bg-black/55 p-4 pt-[12vh] backdrop-blur-sm"
    role="dialog"
    aria-modal="true"
    aria-label="Search"
    tabindex="-1"
    onclick={(e) => e.target === e.currentTarget && onclose?.()}
    onkeydown={onKey}
  >
    <div class="glass glow pop w-[min(660px,95vw)] overflow-hidden p-0">
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

      <div class="max-h-[52vh] overflow-y-auto py-2">
        {#if !hits.length}
          <div class="px-4 py-10 text-center text-sm text-muted">
            {q ? `Nothing matches “${q}”` : "Start typing to search everything"}
          </div>
        {:else}
          {#each grouped as g}
            <div class="px-4 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-widest text-faint">
              {g.group}
            </div>
            {#each g.items as { hit, i }}
              <button
                id={`pal-${i}`}
                class="flex w-full items-center gap-3 px-4 py-2 text-left transition-colors
                  {i === sel ? 'bg-accent/15' : 'hover:bg-white/5'}"
                onclick={() => choose(hit)}
                onmouseenter={() => (sel = i)}
              >
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-sm text-ink">{@html highlight(hit.title, q)}</span>
                  {#if hit.subtitle}
                    <span class="block truncate text-[11px] text-muted">{@html highlight(hit.subtitle, q)}</span>
                  {/if}
                </span>
                {#if i === sel}
                  <Icon name="chevron" size={14} class="shrink-0 text-accent" />
                {/if}
              </button>
            {/each}
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
