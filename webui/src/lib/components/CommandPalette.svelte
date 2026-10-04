<script lang="ts">
  /**
   * Search, from anywhere: Ctrl+K.
   *
   * Everything the panel knows, in one box: the pages, every setting, the
   * people it remembers, the accounts, the pictures, the log, the secrets, and
   * a few things to do (a theme, animations, snow). Built for the keyboard
   * first, so it never needs the mouse:
   *
   *   type          search everything, every word must match
   *   ↑ ↓           move, round from the bottom to the top
   *   PgUp PgDn     move a page at a time
   *   Tab           the next kind of thing (Settings, People, Logs...), Shift+Tab back
   *   Enter         open it, or do it
   *   Esc           clear what is typed, then close
   *
   * Each result says what it is (an icon, a face or a thumbnail) and where it
   * lives, and the one selected is shown in full beside the list: a setting's
   * description and value, a person's facts, a picture, a log line entire.
   * With nothing typed it is not an empty box: what you opened last, and every
   * page to jump to.
   */
  import { tick, untrack } from "svelte";
  import { buildIndex, search, highlight, indexAge, type Hit, type PaletteAction } from "../search";
  import { settingsSection, motionEnabled, snowEnabled, smoothScroll, themeId, viewPersona } from "../stores";
  import { THEMES } from "../themes";
  import { sweepTo } from "../themesweep";
  import Icon from "./Icon.svelte";

  let { open = false, seed = "", onclose, routes, onpick } = $props<{
    open?: boolean;
    /** Opens already searching for this: the right-click menu's "Search for". */
    seed?: string;
    onclose?: () => void;
    routes: Record<string, { title: string; section: string; icon?: string }>;
    onpick?: (id: string) => void;
  }>();

  /** The kinds of thing, in the order Tab goes through them. */
  const SCOPES = [
    { id: "All", icon: "search" },
    { id: "Pages", icon: "command" },
    { id: "Settings", icon: "settings" },
    { id: "Profiles", icon: "layers" },
    { id: "People", icon: "memory" },
    { id: "Accounts", icon: "accounts" },
    { id: "Pictures", icon: "pictures" },
    { id: "Logs", icon: "logs" },
    { id: "Secrets", icon: "system" },
    { id: "Actions", icon: "sparkle" },
  ];

  let q = $state("");
  let scope = $state("All");
  let sel = $state(0);
  let loading = $state(false);
  let input: HTMLInputElement | null = $state(null);
  let listEl: HTMLElement | null = $state(null);
  let version = $state(0);

  // ── What it can do, not just open ──────────────────────────────────────────
  function actions(): PaletteAction[] {
    const motion = $motionEnabled;
    const snow = $snowEnabled;
    const smooth = $smoothScroll;
    return [
      { title: motion ? "Turn animations off" : "Turn animations on", subtitle: "Springy motion throughout the app",
        icon: "sparkle", words: "motion animation reduce", run: () => motionEnabled.set(!motion) },
      { title: snow ? "Turn cursor snow off" : "Turn cursor snow on", subtitle: "Snow falls from your cursor",
        icon: "sparkle", words: "snow decoration cursor", run: () => snowEnabled.set(!snow) },
      { title: smooth ? "Turn smooth scrolling off" : "Turn smooth scrolling on", subtitle: "The mouse wheel glides instead of jumping",
        icon: "sparkle", words: "scroll scrolling smooth wheel glide", run: () => smoothScroll.set(!smooth) },
      ...THEMES.map((t) => ({
        title: `Theme: ${t.name}`, subtitle: t.id === $themeId ? `${t.hint} (in use)` : t.hint,
        icon: "palette", words: "theme colours colors look appearance", run: () => sweepTo(t.id),
      })),
      { title: "Reload the panel", subtitle: "Load the page again", icon: "refresh", words: "refresh reload",
        run: () => location.reload() },
    ];
  }

  async function refresh() {
    if (indexAge() < 15000) return;
    loading = true;
    await buildIndex(routes, actions());
    loading = false;
    version++;
  }

  // ── What was opened last ───────────────────────────────────────────────────
  type Recent = Pick<Hit, "title" | "subtitle" | "group" | "route" | "section" | "kind" | "icon" | "image" | "where">;
  const RECENT_KEY = "palette.recent";
  function loadRecent(): Recent[] {
    try {
      const raw = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
      return Array.isArray(raw) ? raw.slice(0, 6) : [];
    } catch {
      return [];
    }
  }
  let recent = $state<Recent[]>([]);
  function remember(h: Hit) {
    if (h.kind === "action") return;
    const r: Recent = { title: h.title, subtitle: h.subtitle, group: h.group, route: h.route, section: h.section,
                        kind: h.kind, icon: h.icon, image: h.image, where: h.where };
    const same = (x: Recent) => x.route === r.route && x.title === r.title && x.section === r.section;
    recent = [r, ...recent.filter((x) => !same(x))].slice(0, 6);
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
    } catch {
      /* a private window: it just does not remember */
    }
  }

  $effect(() => {
    if (!open) return;
    q = untrack(() => seed);
    scope = "All";
    sel = 0;
    recent = loadRecent();
    // Always rebuilt on open when it is stale, and the actions' wording follows the switches.
    refresh();
    tick().then(() => input?.focus());
  });

  // Debounced: search() sweeps the whole index - every settings field, secret,
  // account, memory user, picture and 250 log lines - and this ran on every
  // keystroke.
  let qd = $state("");
  $effect(() => {
    const v = q;
    const t = setTimeout(() => (qd = v), 90);
    return () => clearTimeout(t);
  });

  /** Everything that matches, before the tab narrows it: the counts on the tabs come from here. */
  const all = $derived.by(() => {
    void version;
    return search(qd, 400);
  });
  const counts = $derived.by(() => {
    const out: Record<string, number> = { All: all.length };
    for (const h of all) out[h.group] = (out[h.group] ?? 0) + 1;
    return out;
  });
  /** The tabs worth showing: every kind while browsing, only the ones with a match while searching. */
  const scopes = $derived(SCOPES.filter((s) => s.id === "All" || (counts[s.id] ?? 0) > 0));
  /** The tab in use: the one picked, unless what is typed now has nothing under it, then All. */
  const tab = $derived(scopes.some((s) => s.id === scope) ? scope : "All");

  type Row = { hit: Hit; head?: string };
  /** What the list shows, with a heading where the kind changes. */
  const rows = $derived.by((): Row[] => {
    let list: Hit[];
    if (!qd.trim() && tab === "All") {
      // Nothing typed: what you opened last, every page, and the things it can do.
      const rec = recent.map((r) => ({ ...r, score: 0, group: "Recent" }) as Hit);
      list = [...rec, ...all.filter((h) => h.group === "Pages"), ...all.filter((h) => h.group === "Actions")];
    } else if (tab === "All") {
      list = all.slice(0, 60);
    } else {
      list = all.filter((h) => h.group === tab).slice(0, 120);
    }
    return list.map((hit, i) => ({ hit, head: i === 0 || list[i - 1].group !== hit.group ? hit.group : undefined }));
  });
  const current = $derived(rows[sel]?.hit ?? null);

  $effect(() => {
    void qd;
    void tab;
    sel = 0;
  });

  // ── Moving ─────────────────────────────────────────────────────────────────
  function move(by: number, wrap = true) {
    const n = rows.length;
    if (!n) return;
    sel = wrap ? (sel + by + n) % n : Math.max(0, Math.min(n - 1, sel + by));
  }
  function nextScope(by: number) {
    const ids = scopes.map((s) => s.id);
    const at = Math.max(0, ids.indexOf(tab));
    scope = ids[(at + by + ids.length) % ids.length];
  }

  function choose(h: Hit | null) {
    if (!h) return;
    remember(h);
    if (h.action) h.action();
    else {
      // A persona opens on itself; a setting, at itself.
      if (h.kind === "persona") { if (h.section) viewPersona.set(h.section); }
      else if (h.section) settingsSection.set(h.section);
      onpick?.(h.route);
    }
    onclose?.();
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      if (q) q = "";
      else onclose?.();
      return;
    }
    if (e.key === "ArrowDown") { e.preventDefault(); move(1); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); move(-1); return; }
    if (e.key === "PageDown") { e.preventDefault(); move(6, false); return; }
    if (e.key === "PageUp") { e.preventDefault(); move(-6, false); return; }
    if (e.key === "Tab") { e.preventDefault(); nextScope(e.shiftKey ? -1 : 1); return; }
    if (e.key === "Enter") { e.preventDefault(); choose(current); }
  }

  // ── The travelling highlight ───────────────────────────────────────────────
  // One element moved between rows, rather than a background switched on and
  // off, so the selection slides and settles instead of blinking across.
  let pill = $state({ y: 0, h: 0, shown: false });
  function placePill() {
    const row = listEl?.querySelector<HTMLElement>(`#pal-${sel}`);
    if (!row) {
      pill = { ...pill, shown: false };
      return;
    }
    pill = { y: row.offsetTop, h: row.offsetHeight, shown: true };
    row.scrollIntoView({ block: "nearest" });
  }
  $effect(() => {
    void sel;
    void rows;
    if (!open) return;
    requestAnimationFrame(placePill);
  });

  const LEVEL_TONE: Record<string, string> = { error: "bad", warn: "warn", recv: "accent2", reply: "good" };
</script>

{#snippet mark(h: Hit, big = false)}
  <span class="pal-mark is-{h.kind}" class:is-big={big} class:is-tone={h.kind === "log"} data-tone={LEVEL_TONE[h.level ?? ""] ?? ""}>
    {#if h.image}
      <img src={h.image} alt="" loading="lazy" draggable="false" />
    {:else}
      <Icon name={h.icon ?? "search"} size={big ? 22 : 15} />
    {/if}
  </span>
{/snippet}

{#if open}
  <div class="pal-scrim" role="presentation" onclick={(e) => e.target === e.currentTarget && onclose?.()}>
    <div class="pal glass floating" role="dialog" aria-modal="true" aria-label="Search" tabindex="-1" onkeydown={onKey}>
      <!-- The box -->
      <label class="pal-top">
        <Icon name="search" size={18} class="pal-lens" />
        <input bind:this={input} bind:value={q} spellcheck="false" autocomplete="off"
               placeholder="Search pages, settings, people, pictures, the log…"
               role="combobox" aria-expanded="true" aria-controls="pal-list" aria-activedescendant={rows.length ? `pal-${sel}` : undefined} />
        {#if loading}<span class="pal-spin" aria-label="Loading"></span>{/if}
        <kbd class="pal-kbd">Esc</kbd>
      </label>

      <!-- The kinds of thing, as tabs: Tab and Shift+Tab go through them. -->
      <div class="pal-scopes" role="tablist" aria-label="What to search">
        {#each scopes as s (s.id)}
          <button type="button" role="tab" aria-selected={tab === s.id} class="pal-scope" class:is-on={tab === s.id}
                  tabindex="-1" onclick={() => { scope = s.id; input?.focus(); }}>
            <Icon name={s.icon} size={12} />
            {s.id}
            {#if qd.trim() || s.id !== "All"}<span class="pal-count">{counts[s.id] ?? 0}</span>{/if}
          </button>
        {/each}
      </div>

      <div class="pal-body">
        <div class="pal-list" id="pal-list" role="listbox" aria-label="Results" bind:this={listEl}>
          <div class="pal-pill" data-shown={pill.shown} style="height: {pill.h}px; transform: translate3d(0, {pill.y}px, 0)" aria-hidden="true"></div>
          {#each rows as { hit, head }, i (`${hit.group}|${hit.route}|${hit.title}|${hit.section ?? ""}|${i}`)}
            {#if head}<p class="pal-head">{head}</p>{/if}
            <button type="button" id="pal-{i}" role="option" aria-selected={i === sel} class="pal-row" class:is-sel={i === sel}
                    tabindex="-1" onclick={() => choose(hit)} onmousemove={() => (sel = i)}>
              {@render mark(hit)}
              <span class="pal-text">
                <span class="pal-title">{@html highlight(hit.title, qd)}</span>
                {#if hit.subtitle}<span class="pal-sub">{@html highlight(hit.subtitle, qd)}</span>{/if}
              </span>
              {#if hit.where && hit.kind !== "page"}<span class="pal-where">{hit.where}</span>{/if}
              <kbd class="pal-enter" aria-hidden="true">↵</kbd>
            </button>
          {:else}
            <div class="pal-none">
              {#if loading}
                Gathering everything…
              {:else if qd.trim()}
                <b>Nothing matches “{qd}”</b>
                <span>Every word has to match: try fewer.</span>
              {:else}
                <b>Nothing here yet</b>
              {/if}
            </div>
          {/each}
        </div>

        <!-- The one selected, in full. -->
        <aside class="pal-preview" aria-live="polite">
          {#if current}
            {#key `${current.group}|${current.title}|${current.section ?? ""}`}
              <div class="pal-pv">
                {#if current.kind === "picture" && current.image}
                  <img class="pal-pv-pic" src={current.image} alt={current.detail ?? ""} />
                {:else}
                  {@render mark(current, true)}
                {/if}
                <h3 class="pal-pv-title">{current.title}</h3>
                {#if current.where}<p class="pal-pv-where"><Icon name="chevron" size={10} />{current.where}</p>{/if}
                {#if current.kind === "log"}
                  <p class="pal-pv-meta">{current.subtitle}</p>
                {:else if current.detail && current.detail !== current.title}
                  <p class="pal-pv-detail">{current.detail}</p>
                {/if}
                {#if current.value}
                  <div class="pal-pv-value"><span>Now</span><b>{current.value}</b></div>
                {/if}
                {#if current.section && current.kind === "setting"}
                  <code class="pal-pv-key">{current.section}</code>
                {/if}
                {#if current.facts?.length}
                  <dl class="pal-pv-facts">
                    {#each current.facts as [k, v] (k)}
                      <dt>{k}</dt><dd>{v}</dd>
                    {/each}
                  </dl>
                {/if}
                <p class="pal-pv-go">
                  <kbd>↵</kbd> {current.kind === "action" ? "Do it" : current.kind === "setting" ? "Go to the setting" : "Open"}
                </p>
              </div>
            {/key}
          {/if}
        </aside>
      </div>

      <footer class="pal-foot">
        <span><kbd>↑</kbd><kbd>↓</kbd> move</span>
        <span><kbd>↵</kbd> open</span>
        <span><kbd>Tab</kbd> kind</span>
        <span><kbd>Esc</kbd> {q ? "clear" : "close"}</span>
        <span class="pal-total">{rows.length ? `${rows.length} shown` : ""}</span>
      </footer>
    </div>
  </div>
{/if}

<style>
  .pal-scrim {
    position: fixed;
    inset: 0;
    z-index: 60;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 10vh 16px 16px;
    background: rgb(0 0 0 / 0.55);
    backdrop-filter: blur(6px);
    animation: pal-fade 0.22s var(--swift) both;
  }
  @keyframes pal-fade { from { opacity: 0; } }
  .pal {
    display: flex;
    width: min(880px, 100%);
    max-height: min(640px, 80vh);
    flex-direction: column;
    overflow: hidden;
    border-radius: 18px;
    padding: 0;
    box-shadow:
      0 40px 120px -30px rgb(0 0 0 / 0.8),
      0 0 0 1px color-mix(in srgb, var(--color-accent) 22%, transparent),
      0 0 60px -20px color-mix(in srgb, var(--color-accent) 50%, transparent);
    animation: pal-in 0.36s var(--spring) both;
    transform-origin: top center;
  }
  @keyframes pal-in { from { opacity: 0; transform: translateY(-12px) scale(0.97); } }

  /* ── The box ── */
  .pal-top {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 18px 12px;
    cursor: text;
  }
  .pal-top :global(.pal-lens) { flex-shrink: 0; color: var(--color-accent); }
  .pal-top input {
    min-width: 0;
    flex: 1;
    background: transparent;
    font-size: 17px;
    color: var(--color-ink);
    outline: none;
  }
  .pal-top input::placeholder { color: var(--color-faint); }
  .pal-spin { width: 14px; height: 14px; flex-shrink: 0; border-radius: 999px; border: 2px solid var(--color-muted); border-top-color: transparent; animation: pal-rot 0.8s linear infinite; }
  @keyframes pal-rot { to { transform: rotate(360deg); } }
  kbd, .pal-kbd {
    display: inline-grid;
    min-width: 20px;
    height: 20px;
    place-items: center;
    padding: 0 5px;
    border-radius: 6px;
    font-family: inherit;
    font-size: 10.5px;
    font-weight: 600;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 0 -1.5px 0 rgb(0 0 0 / 0.35), inset 0 0 0 1px rgb(255 255 255 / 0.08);
  }

  /* ── The kinds, as tabs ── */
  .pal-scopes {
    display: flex;
    gap: 4px;
    overflow-x: auto;
    padding: 0 14px 10px;
    border-bottom: 1px solid var(--color-edge);
    scrollbar-width: none;
  }
  .pal-scope {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 6px;
    padding: 5px 10px;
    border-radius: 999px;
    font-size: 12px;
    color: var(--color-muted);
    transition: background-color 0.18s var(--swift), color 0.18s var(--swift), transform 0.3s var(--jelly);
  }
  .pal-scope:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.05); }
  .pal-scope.is-on {
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 18%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 40%, transparent);
  }
  .pal-count { padding: 0 6px; border-radius: 999px; font-size: 10.5px; font-variant-numeric: tabular-nums; color: var(--color-faint); background: rgb(255 255 255 / 0.06); }
  .pal-scope.is-on .pal-count { color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 16%, transparent); }

  /* ── The list, and the one selected beside it ── */
  .pal-body { display: grid; min-height: 0; flex: 1; grid-template-columns: minmax(0, 1fr); }
  @media (min-width: 760px) { .pal-body { grid-template-columns: minmax(0, 1fr) 280px; } }
  .pal-list { position: relative; min-height: 180px; max-height: 60vh; overflow-y: auto; padding: 6px 8px 10px; }
  .pal-pill {
    position: absolute;
    left: 8px;
    right: 8px;
    top: 0;
    border-radius: 12px;
    background: color-mix(in srgb, var(--color-accent) 15%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 32%, transparent);
    opacity: 0;
    pointer-events: none;
    transition: transform 0.3s var(--spring), height 0.3s var(--spring), opacity 0.16s var(--swift);
  }
  .pal-pill[data-shown="true"] { opacity: 1; }
  .pal-head {
    position: relative;
    margin: 10px 10px 4px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--color-faint);
  }
  .pal-head:first-of-type { margin-top: 4px; }
  .pal-row {
    position: relative;
    display: flex;
    width: 100%;
    align-items: center;
    gap: 12px;
    padding: 8px 10px;
    border-radius: 12px;
    text-align: left;
  }
  .pal-text { display: flex; min-width: 0; flex: 1; flex-direction: column; }
  .pal-title { overflow: hidden; font-size: 13.5px; color: var(--color-ink); text-overflow: ellipsis; white-space: nowrap; }
  .pal-sub { overflow: hidden; font-size: 11.5px; color: var(--color-muted); text-overflow: ellipsis; white-space: nowrap; }
  .pal-where { flex-shrink: 0; max-width: 34%; overflow: hidden; font-size: 11px; color: var(--color-faint); text-overflow: ellipsis; white-space: nowrap; }
  .pal-enter { opacity: 0; transform: scale(0.7); transition: opacity 0.16s var(--swift), transform 0.3s var(--jelly); }
  .pal-row.is-sel .pal-enter { opacity: 1; transform: none; color: var(--color-accent); }
  .pal-row.is-sel .pal-where { color: var(--color-muted); }
  /* A match: the letters lit in the accent, not a box drawn round them. */
  .pal :global(mark) { padding: 0; border-radius: 0; background: none; color: var(--color-accent); font-weight: 700; }

  /* What each result is: an icon in a tile tinted by its kind, or its face or picture. */
  .pal-mark {
    --tint: var(--color-accent);
    display: grid;
    width: 32px;
    height: 32px;
    flex-shrink: 0;
    place-items: center;
    overflow: hidden;
    border-radius: 10px;
    color: var(--tint);
    background: color-mix(in srgb, var(--tint) 14%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--tint) 24%, transparent);
  }
  .pal-mark img { width: 100%; height: 100%; object-fit: cover; }
  .pal-mark.is-person, .pal-mark.is-account { border-radius: 999px; }
  .pal-mark.is-setting { --tint: var(--color-accent-2); }
  .pal-mark.is-action { --tint: #f5a3ff; }
  .pal-mark.is-secret { --tint: var(--color-warn); }
  .pal-mark.is-log { --tint: var(--color-muted); }
  .pal-mark[data-tone="bad"] { --tint: var(--color-bad); }
  .pal-mark[data-tone="warn"] { --tint: var(--color-warn); }
  .pal-mark[data-tone="good"] { --tint: var(--color-good); }
  .pal-mark[data-tone="accent2"] { --tint: var(--color-accent-2); }
  .pal-mark.is-big { width: 52px; height: 52px; border-radius: 16px; }
  .pal-mark.is-big.is-person, .pal-mark.is-big.is-account { border-radius: 999px; }

  .pal-none { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 48px 16px; text-align: center; font-size: 12.5px; color: var(--color-faint); }
  .pal-none b { font-size: 14px; font-weight: 600; color: var(--color-muted); }

  .pal-preview { display: none; min-height: 0; overflow-y: auto; border-left: 1px solid var(--color-edge); background: rgb(0 0 0 / 0.14); }
  @media (min-width: 760px) { .pal-preview { display: block; } }
  .pal-pv { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; padding: 18px; animation: pal-pv 0.28s var(--swift) both; }
  @keyframes pal-pv { from { opacity: 0; transform: translateY(4px); } }
  .pal-pv-pic { width: 100%; max-height: 180px; border-radius: 12px; object-fit: cover; box-shadow: inset 0 0 0 1px var(--color-edge); }
  .pal-pv-title { margin-top: 4px; font-size: 16px; font-weight: 700; line-height: 1.3; color: var(--color-ink); overflow-wrap: anywhere; }
  .pal-pv-where { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--color-accent); }
  .pal-pv-detail { font-size: 12.5px; line-height: 1.55; color: var(--color-muted); overflow-wrap: anywhere; }
  .pal-pv-meta { font-size: 11.5px; color: var(--color-faint); }
  .pal-pv-value { display: flex; align-items: baseline; gap: 8px; padding: 6px 10px; border-radius: 10px; font-size: 12px; background: rgb(255 255 255 / 0.04); }
  .pal-pv-value span { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-faint); }
  .pal-pv-value b { font-weight: 650; color: var(--color-ink); overflow-wrap: anywhere; }
  .pal-pv-key { font-size: 10.5px; color: var(--color-faint); overflow-wrap: anywhere; }
  .pal-pv-facts { display: grid; width: 100%; grid-template-columns: auto minmax(0, 1fr); gap: 5px 12px; margin-top: 2px; font-size: 12px; }
  .pal-pv-facts dt { color: var(--color-faint); text-transform: capitalize; }
  .pal-pv-facts dd { color: var(--color-ink); overflow-wrap: anywhere; }
  .pal-pv-go { display: flex; align-items: center; gap: 6px; margin-top: 6px; font-size: 11.5px; color: var(--color-muted); }

  .pal-foot {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 9px 16px;
    border-top: 1px solid var(--color-edge);
    font-size: 11px;
    color: var(--color-faint);
  }
  .pal-foot span { display: inline-flex; align-items: center; gap: 4px; }
  .pal-total { margin-left: auto; }

  :global(:root[data-motion="off"]) .pal,
  :global(:root[data-motion="off"]) .pal-scrim,
  :global(:root[data-motion="off"]) .pal-pv { animation: none; }
  :global(:root[data-motion="off"]) .pal-pill,
  :global(:root[data-motion="off"]) .pal-enter { transition: none; }
</style>
