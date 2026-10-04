<script lang="ts">
  /**
   * Searching one conversation, the way Discord does.
   *
   * Words and filters in one box - from:, has:, before:, after:, during: -
   * each filter a chip once it is complete, suggestions as you type, results
   * grouped by day with what matched highlighted, and a jump to each one.
   *
   * What is kept here (app/utils/chatlog.py) is searched as you type: instant,
   * and it finds deleted messages, which Discord's own search cannot. Enter
   * asks Discord too, on a Discord account, for everything ever said, 25 at a
   * time; the deleted ones kept here are put back in among its results.
   */
  import { tick } from "svelte";
  import { api } from "../api";
  import { discordInline } from "../discordmd";
  import { fmtDate, FULL_WHEN, HOUR_MINUTE } from "../fmt";
  import { mentionNames, resolveMention } from "../mentions";
  import { play } from "../uisound";
  import {
    HAS, KEYS, KEY_HINT, fold, forgetSearches, hasInfo, highlighted, isEmpty, matchRanges, noFilters, parseSpan,
    quickSpans, recentSearches, rememberSearch, takeFilters, toQuery, tokenAt,
    type DateKind, type Filters, type HasKind, type Key, type Recent, type Sort, type Span,
  } from "../chatsearch";
  import Avatar from "./Avatar.svelte";
  import Icon from "./Icon.svelte";

  type Att = { url: string; name: string; type?: string; size?: number };
  type Hit = {
    mid?: string; mine: boolean; ts: number; text?: string; deleted?: number; edited?: number; approx?: boolean;
    attachments?: Att[]; stickers?: { name: string; url?: string }[]; embeds?: { title?: string; url?: string; image?: string }[];
  };
  type Side = { name: string; username?: string; avatar?: string };

  let {
    target,
    uid,
    platform,
    them,
    me,
    focusKey = 0,
    onjump,
    onclose,
  }: {
    target: string;
    uid: string;
    platform: string;
    them: Side;
    me: Side;
    /** Changes when the search should take the keyboard again (Ctrl+F while it is open). */
    focusKey?: number;
    onjump: (mid: string) => Promise<unknown> | void;
    onclose: () => void;
  } = $props();

  const discord = $derived(platform === "discord");
  const KEY_ICON: Record<Key, string> = { from: "accounts", has: "pictures", before: "calendar", after: "calendar", during: "calendar" };
  const DATE_WORD: Record<DateKind, string> = { before: "Before", after: "After", during: "On" };
  const KEY_NAME: Record<Key, string> = { from: "From", has: "Has", before: "Before", after: "After", during: "On" };
  const SORTS: { id: Sort; label: string }[] = [
    { id: "newest", label: "Newest" },
    { id: "oldest", label: "Oldest" },
    { id: "relevant", label: "Best match" },
  ];

  let text = $state("");
  let filters = $state<Filters>(noFilters());
  let sort = $state<Sort>("newest");
  let input: HTMLInputElement | null = $state(null);
  let dayPicker: HTMLInputElement | null = $state(null);
  let caret = $state(0);
  let focused = $state(false);
  let recent = $state<Recent[]>(recentSearches());

  const query = $derived(toQuery(text, filters));
  const empty = $derived(isEmpty(query));
  const queryKey = $derived(JSON.stringify([query, sort]));

  // ── What is kept, as you type ──────────────────────────────────────────
  type Local = { messages: Hit[]; total: number; kept: number; since: number | null; loading: boolean; error: string; key: string };
  let local = $state<Local>({ messages: [], total: 0, kept: 0, since: null, loading: false, error: "", key: "" });

  /** A further page added to what is shown: a message already there is not there twice (new ones arriving between
   * two pages shift what the next one starts with). */
  function joined(shown: Hit[], page: Hit[]): Hit[] {
    const have = new Set(shown.map((m) => m.mid).filter(Boolean));
    return [...shown, ...page.filter((m) => !m.mid || !have.has(m.mid))];
  }

  async function runLocal(append = false) {
    const key = queryKey;
    if (empty) {
      local = { ...local, messages: [], total: 0, loading: false, error: "", key };
      return;
    }
    local = { ...local, loading: true, error: "" };
    try {
      const r = await api.chatsSearch(uid, target, query, sort, append ? local.messages.length : 0, 50);
      if (key !== queryKey) return;
      local = {
        messages: append ? joined(local.messages, r.messages || []) : r.messages || [],
        total: r.total ?? 0, kept: r.kept ?? 0, since: r.since ?? null, loading: false, error: "", key,
      };
    } catch (e: any) {
      if (key === queryKey) local = { ...local, loading: false, error: e?.message || "Could not search" };
    }
  }

  // ── Discord's own, on Enter ────────────────────────────────────────────
  type Remote = { on: boolean; messages: Hit[]; total: number; more: boolean; loading: boolean; error: string; indexing: boolean };
  const idle = (): Remote => ({ on: false, messages: [], total: 0, more: false, loading: false, error: "", indexing: false });
  let remote = $state<Remote>(idle());

  async function runRemote(more = false) {
    if (!discord || empty || remote.loading) return;
    const key = queryKey;
    const last = remote.messages[remote.messages.length - 1];
    const page = !more ? {} : sort === "relevant" ? { offset: remote.messages.length } : { cursor: last?.mid };
    remote = more ? { ...remote, loading: true, error: "" } : { ...idle(), on: true, loading: true };
    try {
      const r = await api.chatsSearchDiscord(uid, target, query, sort, page);
      if (key !== queryKey) return;
      const messages = more ? joined(remote.messages, r.messages || []) : r.messages || [];
      remote = {
        on: true, messages, total: r.total ?? 0, loading: false, error: "", indexing: !!r.indexing,
        // A page that brought nothing new is the end, whatever it says.
        more: !!r.more && messages.length > (more ? remote.messages.length : 0),
      };
    } catch (e: any) {
      if (key === queryKey) remote = { ...remote, loading: false, error: e?.message || "Discord did not answer" };
    }
  }

  let active = $state(-1);

  // A new search: what Discord found was for the old one, and what is kept is searched again.
  let timer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    queryKey;
    clearTimeout(timer);
    remote = idle();
    active = -1;
    timer = setTimeout(() => runLocal(false), empty ? 0 : 160);
    return () => clearTimeout(timer);
  });

  /** Discord's results, with the deleted messages kept here put back in where they were (it no longer has them). */
  const hits = $derived.by((): Hit[] => {
    if (!remote.on || (remote.loading && !remote.messages.length) || (remote.error && !remote.messages.length)) return local.messages;
    const out = [...remote.messages];
    const have = new Set(out.map((m) => m.mid));
    const edge = remote.more && out.length ? out[out.length - 1].ts : null;
    for (const m of local.messages) {
      if (!m.deleted || have.has(m.mid)) continue;
      if (edge !== null && (sort === "oldest" ? m.ts > edge : m.ts < edge)) continue;
      out.push(m);
    }
    if (sort === "newest") out.sort((a, b) => b.ts - a.ts);
    else if (sort === "oldest") out.sort((a, b) => a.ts - b.ts);
    return out;
  });
  const fromDiscord = $derived(remote.on && !!remote.messages.length);
  const count = $derived(fromDiscord ? remote.total + (hits.length - remote.messages.length) : local.total);
  const searching = $derived((local.loading && !local.messages.length) || (remote.on && remote.loading && !remote.messages.length));

  /** Grouped by day, the way the conversation is; by best match there is no order of days to follow. */
  const groups = $derived.by(() => {
    const out: { key: string; label: string; items: { m: Hit; i: number }[] }[] = [];
    hits.forEach((m, i) => {
      const key = sort === "relevant" ? "all" : new Date(m.ts * 1000).toDateString();
      let g = out[out.length - 1];
      if (!g || g.key !== key) out.push((g = { key, label: sort === "relevant" ? "" : dayLabel(m.ts), items: [] }));
      g.items.push({ m, i });
    });
    return out;
  });

  function dayLabel(ts: number): string {
    const d = new Date(ts * 1000);
    const today = new Date();
    const y = new Date();
    y.setDate(today.getDate() - 1);
    if (d.toDateString() === today.toDateString()) return "Today";
    if (d.toDateString() === y.toDateString()) return "Yesterday";
    return fmtDate(d, d.getFullYear() === today.getFullYear()
      ? { weekday: "long", day: "numeric", month: "long" }
      : { day: "numeric", month: "long", year: "numeric" });
  }

  function more() {
    if (fromDiscord) {
      if (remote.more && !remote.loading) runRemote(true);
    } else if (!local.loading && local.messages.length < local.total && local.key === queryKey) {
      runLocal(true);
    }
  }

  /** Asks for the next page as the end of the list comes into view. */
  function sentinel(node: HTMLElement) {
    const io = new IntersectionObserver((es) => es.some((e) => e.isIntersecting) && more(),
      { root: node.closest(".cs-results"), rootMargin: "240px" });
    io.observe(node);
    return { destroy: () => io.disconnect() };
  }

  // ── The box ────────────────────────────────────────────────────────────
  $effect(() => {
    focusKey;
    tick().then(() => {
      input?.focus();
      input?.select();
    });
  });

  function syncCaret() {
    caret = input?.selectionStart ?? text.length;
  }

  function onInput() {
    sugHidden = false;
    sugAt = -1;
    // A filter typed in full, with a space after it, becomes a chip.
    const r = takeFilters(text, filters, them);
    if (r.took) {
      const at = Math.max(0, (input?.selectionStart ?? text.length) - (text.length - r.text.length));
      text = r.text;
      filters = r.filters;
      play("select");
      tick().then(() => input?.setSelectionRange(at, at));
    }
    syncCaret();
  }

  /** Enter: every filter typed becomes a chip, the search is remembered, and Discord is asked too. */
  function commit() {
    const r = takeFilters(text, filters, them, true);
    if (r.took) {
      text = r.text;
      filters = r.filters;
    }
    if (isEmpty(toQuery(text, filters))) return;
    rememberSearch(text, $state.snapshot(filters));
    recent = recentSearches();
    if (discord) runRemote();
  }

  function onKey(e: KeyboardEvent) {
    if (e.isComposing) return;
    if (sugs.length) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        sugAt = (sugAt + 1) % sugs.length;
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        sugAt = sugAt <= 0 ? sugs.length - 1 : sugAt - 1;
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && sugAt >= 0)) {
        e.preventDefault();
        sugs[Math.max(0, sugAt)].run();
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        sugHidden = true;
        return;
      }
    }
    if (e.key === "ArrowDown" && hits.length) {
      e.preventDefault();
      active = Math.min(hits.length - 1, active + 1);
      showActive();
    } else if (e.key === "ArrowUp" && active >= 0) {
      e.preventDefault();
      active -= 1;
      showActive();
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (active >= 0 && hits[active]) jump(hits[active]);
      else commit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      if (text || chips.length) clearAll();
      else onclose();
    } else if (e.key === "Backspace" && input?.selectionStart === 0 && input?.selectionEnd === 0 && chips.length) {
      e.preventDefault();
      chips[chips.length - 1].remove();
    }
  }

  let results: HTMLElement | null = $state(null);
  function showActive() {
    tick().then(() => results?.querySelector(".cs-hit.is-active")?.scrollIntoView({ block: "nearest" }));
  }

  function clearAll() {
    text = "";
    filters = noFilters();
    input?.focus();
  }

  // ── Chips ──────────────────────────────────────────────────────────────
  const chips = $derived.by(() => {
    const out: { id: string; icon: string; label: string; side?: Side; remove: () => void }[] = [];
    if (filters.from) {
      const mine = filters.from === "me";
      out.push({ id: "from", icon: "accounts", side: mine ? me : them, label: `From: ${mine ? "you" : them.name}`,
                 remove: () => (filters.from = null) });
    }
    for (const h of filters.has) {
      out.push({ id: `has:${h}`, icon: hasInfo(h).icon, label: `Has: ${hasInfo(h).label.toLowerCase()}`,
                 remove: () => (filters.has = filters.has.filter((x) => x !== h)) });
    }
    for (const d of filters.dates) {
      out.push({ id: `date:${d.kind}`, icon: "calendar", label: `${DATE_WORD[d.kind]}: ${d.label}`,
                 remove: () => (filters.dates = filters.dates.filter((x) => x.kind !== d.kind)) });
    }
    return out;
  });

  // ── Suggestions, as a filter is typed ──────────────────────────────────
  type Sug = { id: string; icon: string; label: string; hint?: string; side?: Side; run: () => void };
  let sugHidden = $state(false);
  let sugAt = $state(-1);
  const tok = $derived(tokenAt(text, caret));

  const sugs = $derived.by((): Sug[] => {
    if (!focused || sugHidden) return [];
    const t = tok;
    if (t.value === null) {
      const k = fold(t.key);
      if (!k) return [];
      return KEYS.filter((key) => key.startsWith(k) && key !== k)
        .map((key) => ({ id: `k:${key}`, icon: KEY_ICON[key], label: `${key}:`, hint: KEY_HINT[key], run: () => insertKey(key) }));
    }
    const key = fold(t.key) === "on" ? "during" : fold(t.key);
    const v = fold(t.value);
    if (key === "from") {
      return [
        { who: "me" as const, side: me, label: "You", hint: "your messages", words: ["me", "you", fold(me.name)] },
        { who: "them" as const, side: them, label: them.name, hint: "their messages", words: ["them", fold(them.name), fold(them.username ?? "")] },
      ]
        .filter((o) => !v || o.words.some((w) => w && w.startsWith(v)))
        .map((o) => ({ id: `f:${o.who}`, icon: "accounts", side: o.side, label: o.label, hint: o.hint, run: () => setFrom(o.who) }));
    }
    if (key === "has") {
      return HAS.filter((h) => !v || h.id.startsWith(v) || fold(h.label).startsWith(v) || h.words.some((w) => w.startsWith(v)))
        .map((h) => ({ id: `h:${h.id}`, icon: h.icon, label: h.label, run: () => addHas(h.id) }));
    }
    if (key === "before" || key === "after" || key === "during") {
      const kind = key as DateKind;
      const list: Sug[] = [];
      const typed = v ? parseSpan(t.value) : null;
      if (typed) list.push({ id: "d:typed", icon: "calendar", label: typed.label, run: () => addDate(kind, typed) });
      if (!v) for (const s of quickSpans()) list.push({ id: `d:${s.label}`, icon: "calendar", label: s.label, run: () => addDate(kind, s) });
      list.push({ id: "d:pick", icon: "calendar", label: "Pick a day", run: () => pickDay(kind) });
      return list;
    }
    return [];
  });

  /** The token being typed, taken out of the box. */
  function dropToken() {
    const t = tok;
    const before = text.slice(0, t.start).replace(/\s+$/, "");
    const after = text.slice(t.end).replace(/^\s+/, "");
    text = before && after ? `${before} ${after}` : before + after;
    const at = before.length + (before && after ? 1 : 0);
    tick().then(() => {
      input?.focus();
      input?.setSelectionRange(at, at);
      syncCaret();
    });
  }

  function insertKey(key: Key) {
    const t = tok;
    text = `${text.slice(0, t.start)}${key}:${text.slice(t.end)}`;
    const at = t.start + key.length + 1;
    sugAt = -1;
    tick().then(() => {
      input?.focus();
      input?.setSelectionRange(at, at);
      syncCaret();
    });
  }

  function setFrom(who: "me" | "them") {
    dropToken();
    filters = { ...filters, from: who };
    play("select");
  }

  function addHas(h: HasKind) {
    dropToken();
    if (!filters.has.includes(h)) filters = { ...filters, has: [...filters.has, h] };
    play("select");
  }

  function addDate(kind: DateKind, span: Span) {
    dropToken();
    filters = { ...filters, dates: [...filters.dates.filter((d) => d.kind !== kind), { kind, ...span }] };
    play("select");
  }

  let pickKind = $state<DateKind>("during");
  function pickDay(kind: DateKind) {
    pickKind = kind;
    try {
      dayPicker?.showPicker();
    } catch {
      dayPicker?.focus();
    }
  }
  function picked() {
    const span = dayPicker?.value ? parseSpan(dayPicker.value) : null;
    if (span) addDate(pickKind, span);
    if (dayPicker) dayPicker.value = "";
  }

  // ── Remembered searches ────────────────────────────────────────────────
  function useRecent(r: Recent) {
    text = r.text;
    filters = { from: r.filters.from ?? null, has: [...(r.filters.has ?? [])], dates: [...(r.filters.dates ?? [])] };
    tick().then(() => {
      input?.focus();
      commit();
    });
  }
  function describe(r: Recent): string {
    const bits = [r.text.trim()];
    if (r.filters.from) bits.push(`from:${r.filters.from === "me" ? "you" : them.name}`);
    for (const h of r.filters.has ?? []) bits.push(`has:${h}`);
    for (const d of r.filters.dates ?? []) bits.push(`${d.kind}:${d.label}`);
    return bits.filter(Boolean).join(" ");
  }
  function clearRecent() {
    forgetSearches();
    recent = [];
  }

  // ── A result ───────────────────────────────────────────────────────────
  // Names for the @mentions in the results, fetched once each.
  $effect(() => {
    for (const m of hits) for (const x of (m.text ?? "").matchAll(/<@!?(\d+)>/g)) resolveMention(x[1]);
  });

  /** Mentions as names, so they read (and match) as they show; a long one starts near what was found. */
  function shown(t: string): string {
    const s = t.replace(/<@!?(\d+)>/g, (_, id) => `@${$mentionNames[id] || "someone"}`);
    if (s.length <= 320) return s;
    const first = matchRanges(s, query.words)[0];
    if (!first || first[0] < 160) return s;
    const from = s.lastIndexOf(" ", first[0] - 90);
    return `…${s.slice(from > 0 ? from + 1 : first[0] - 90)}`;
  }

  const isImage = (a: Att) => (a.type || "").startsWith("image/") || /\.(png|jpe?g|gif|webp|avif)(\?|$)/i.test(a.name || a.url);
  const isVideo = (a: Att) => (a.type || "").startsWith("video/") || /\.(mp4|webm|mov|mkv)(\?|$)/i.test(a.name || a.url);
  const isSound = (a: Att) => (a.type || "").startsWith("audio/") || /\.(ogg|mp3|wav|m4a|opus)(\?|$)/i.test(a.name || a.url);

  let jumping = $state("");
  async function jump(m: Hit) {
    if (!m.mid || jumping) return;
    rememberSearch(text, $state.snapshot(filters));
    jumping = m.mid;
    try {
      await onjump(m.mid);
    } finally {
      jumping = "";
    }
  }

  const sinceLabel = $derived(local.since ? fmtDate(local.since * 1000, { day: "numeric", month: "short", year: "numeric" }) : "");
</script>

<div class="cs">
  <div class="cs-box" class:is-focused={focused}>
    <span class="cs-glass"><Icon name="search" size={14} /></span>
    <div class="cs-field">
      {#each chips as c (c.id)}
        <span class="cs-chip">
          {#if c.side}
            <Avatar src={c.side.avatar} name={c.side.name} size={16} zoom={false} />
          {:else}
            <Icon name={c.icon} size={11} />
          {/if}
          {c.label}
          <button type="button" class="cs-chip-x" onclick={c.remove} aria-label="Remove {c.label}"><Icon name="close" size={9} /></button>
        </span>
      {/each}
      <input
        bind:this={input}
        bind:value={text}
        type="text"
        spellcheck="false"
        autocomplete="off"
        placeholder={chips.length ? "" : "Search"}
        aria-label="Search this chat"
        oninput={onInput}
        onkeydown={onKey}
        onkeyup={syncCaret}
        onclick={syncCaret}
        onfocus={() => { focused = true; syncCaret(); }}
        onblur={() => (focused = false)}
      />
    </div>
    {#if text || chips.length}
      <button type="button" class="cs-clear" onclick={clearAll} aria-label="Clear the search"><Icon name="close" size={11} /></button>
    {/if}
    <input bind:this={dayPicker} type="date" class="cs-daypicker" tabindex="-1" aria-hidden="true" onchange={picked} />

    {#if sugs.length}
      <!-- What can come next: a filter, who, what kind, which day. -->
      <div class="cs-sugs glass floating" role="listbox" aria-label="Suggestions">
        {#each sugs as s, i (s.id)}
          <button type="button" role="option" aria-selected={i === sugAt} class="cs-sug" class:is-on={i === sugAt}
                  onmousedown={(e) => e.preventDefault()} onmouseenter={() => (sugAt = i)} onclick={s.run}>
            {#if s.side}
              <Avatar src={s.side.avatar} name={s.side.name} size={20} zoom={false} />
            {:else}
              <span class="cs-sug-icon"><Icon name={s.icon} size={13} /></span>
            {/if}
            <span class="cs-sug-label">{s.label}</span>
            {#if s.hint}<span class="cs-sug-hint">{s.hint}</span>{/if}
          </button>
        {/each}
      </div>
    {/if}
  </div>

  {#if empty}
    <!-- Nothing asked yet: what can be asked, and what was. -->
    <div class="cs-start">
      <div class="cs-sec">Search by</div>
      <div class="cs-keys">
        {#each KEYS as key, i (key)}
          <button type="button" class="cs-key" style="--i: {i}" onmousedown={(e) => e.preventDefault()} onclick={() => insertKey(key)}>
            <span class="cs-key-icon"><Icon name={KEY_ICON[key]} size={15} /></span>
            <span class="cs-key-text"><b>{KEY_NAME[key]}</b><small>{KEY_HINT[key]}</small></span>
            <code>{key}:</code>
          </button>
        {/each}
      </div>
      {#if recent.length}
        <div class="cs-sec">
          Recent
          <button type="button" class="cs-sec-btn" onclick={clearRecent}>Clear</button>
        </div>
        <div class="cs-recent">
          {#each recent as r (r.at)}
            <button type="button" class="cs-recent-chip" onclick={() => useRecent(r)} title={describe(r)}>
              <Icon name="refresh" size={11} /><span>{describe(r)}</span>
            </button>
          {/each}
        </div>
      {/if}
      <p class="cs-tip">
        {#if discord}<kbd>Enter</kbd> searches all of Discord<span class="cs-tip-dot"></span>{/if}<kbd>Ctrl</kbd><kbd>F</kbd> opens this
      </p>
    </div>
  {:else}
    <div class="cs-head">
      <span class="cs-count" aria-live="polite">
        {#if searching}
          <span class="cs-spin"></span>{remote.on ? "Searching Discord" : "Searching"}
        {:else}
          {count} result{count === 1 ? "" : "s"}
        {/if}
      </span>
      <div class="cs-sort" role="tablist" aria-label="Order">
        {#each SORTS as s (s.id)}
          <button type="button" role="tab" aria-selected={sort === s.id} class:is-on={sort === s.id}
                  onclick={() => { if (sort !== s.id) { sort = s.id; play("select"); } }}>{s.label}</button>
        {/each}
      </div>
    </div>
    <div class="cs-scope">
      {#if fromDiscord}
        <Icon name="discord" size={11} />All of Discord{#if remote.indexing}<span class="text-faint"> · still indexing this chat</span>{/if}
      {:else if remote.error}
        <span class="text-warn">{remote.error}</span>
        <button type="button" class="cs-link" onclick={() => runRemote()}>Try again</button>
      {:else}
        <span class="min-w-0 truncate">{local.kept ? `Last ${local.kept} messages${sinceLabel ? `, since ${sinceLabel}` : ""}` : "Nothing kept here yet"}</span>
        {#if discord && !remote.loading}
          <button type="button" class="cs-link" onclick={() => { commit(); }}>Search all of Discord</button>
        {/if}
      {/if}
    </div>

    <div class="cs-results" bind:this={results}>
      {#if local.error && !hits.length}
        <p class="cs-note text-warn">{local.error}</p>
      {:else if searching}
        {#each [70, 48, 62] as w, i (i)}
          <div class="cs-skel"><span class="cs-skel-av"></span><span class="cs-skel-lines"><i style="width:{w}%"></i><i style="width:{w - 20}%"></i></span></div>
        {/each}
      {:else if !hits.length}
        <div class="cs-none">
          <span class="cs-none-icon"><Icon name="search" size={20} /></span>
          <b>Nothing found</b>
          {#if discord && !remote.on}
            <span>Only the last {local.kept} messages are kept here.</span>
            <button type="button" class="cs-cta" onclick={() => commit()}>Search all of Discord</button>
          {/if}
        </div>
      {/if}

      {#each groups as g (g.key)}
        {#if g.label}<div class="cs-day"><span>{g.label}</span></div>{/if}
        {#each g.items as { m, i } (m.mid ?? `${m.ts}:${i}`)}
          {@const media = (m.attachments ?? []).filter((a) => isImage(a) || isVideo(a))}
          {@const files = (m.attachments ?? []).filter((a) => !isImage(a) && !isVideo(a))}
          <button type="button" class="cs-hit" class:is-active={i === active} class:is-busy={jumping === m.mid}
                  class:is-deleted={!!m.deleted} onclick={() => jump(m)} onmouseenter={() => (active = i)}
                  title="Jump to this message">
            <span class="cs-hit-av">
              <Avatar src={m.mine ? me.avatar : them.avatar} name={m.mine ? me.name : them.name} size={30} zoom={false}
                      silhouette={!discord} />
            </span>
            <span class="cs-hit-main">
              <span class="cs-hit-top">
                <b>{m.mine ? "You" : them.name}</b>
                <time title={fmtDate(m.ts * 1000, FULL_WHEN)}>
                  {sort === "relevant" || m.approx ? fmtDate(m.ts * 1000, { day: "numeric", month: "short", year: "numeric" }) + " " : ""}{m.approx ? "" : fmtDate(m.ts * 1000, HOUR_MINUTE)}
                </time>
                {#if m.deleted}<span class="cs-tag is-bad"><Icon name="trash" size={9} />deleted</span>{/if}
                {#if m.edited && !m.deleted}<span class="cs-tag">edited</span>{/if}
              </span>
              {#if m.text}
                <span class="cs-hit-text">{@html highlighted(shown(m.text), query.words, discordInline)}</span>
              {/if}
              {#if media.length}
                <span class="cs-hit-media">
                  {#each media.slice(0, 4) as a, n (a.url + n)}
                    <span class="cs-thumb">
                      {#if isVideo(a)}
                        <span class="cs-thumb-video"><Icon name="play" size={12} /></span>
                      {:else}
                        <img src={a.url} alt={a.name} loading="lazy" referrerpolicy="no-referrer" />
                      {/if}
                      {#if n === 3 && media.length > 4}<span class="cs-thumb-more">+{media.length - 4}</span>{/if}
                    </span>
                  {/each}
                </span>
              {/if}
              {#each files.slice(0, 2) as a, n (a.url + n)}
                <span class="cs-file">
                  <Icon name={isSound(a) ? "mic" : "file"} size={12} />
                  <span class="truncate">{@html highlighted(a.name, query.words, (s) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`))}</span>
                </span>
              {/each}
              {#if !m.text && !media.length && !files.length && m.stickers?.length}
                <span class="cs-file"><Icon name="sparkle" size={12} />Sticker: {m.stickers[0].name}</span>
              {/if}
            </span>
            <span class="cs-jump">{#if jumping === m.mid}<span class="cs-spin"></span>{:else}Jump{/if}</span>
          </button>
        {/each}
      {/each}

      {#if hits.length && ((fromDiscord && remote.more) || (!fromDiscord && local.messages.length < local.total))}
        <div class="cs-more" use:sentinel>
          {#if remote.loading || local.loading}<span class="cs-spin"></span>Loading more{:else}
            <button type="button" class="cs-link" onclick={more}>More</button>{/if}
        </div>
      {:else if hits.length && discord && !fromDiscord && !remote.loading && !remote.error}
        <div class="cs-more">
          <button type="button" class="cs-cta" onclick={() => commit()}>Search all of Discord</button>
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .cs { display: flex; min-height: 0; flex: 1; flex-direction: column; }

  /* ── The box ─────────────────────────────────────────────────────── */
  .cs-box {
    position: relative;
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 12px 12px 8px;
    padding: 5px 8px 5px 11px;
    min-height: 40px;
    border-radius: 13px;
    background: rgb(0 0 0 / 0.22);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    transition: box-shadow 0.18s ease;
  }
  .cs-box.is-focused {
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, transparent),
                0 0 0 3px color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .cs-glass { display: inline-flex; flex-shrink: 0; color: var(--color-faint); }
  .cs-box.is-focused .cs-glass { color: var(--color-accent); }
  .cs-field { display: flex; min-width: 0; flex: 1; flex-wrap: wrap; align-items: center; gap: 5px; }
  .cs-field input {
    min-width: 80px;
    flex: 1;
    padding: 4px 0;
    font-size: 13px;
    color: var(--color-ink);
    background: transparent;
    outline: none;
  }
  .cs-field input::placeholder { color: var(--color-faint); }
  .cs-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    max-width: 100%;
    padding: 2px 4px 2px 6px;
    border-radius: 8px;
    font-size: 11.5px;
    font-weight: 600;
    white-space: nowrap;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 20%, rgb(255 255 255 / 0.03));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 35%, transparent);
    animation: cs-pop 0.28s var(--spring) both;
  }
  .cs-chip-x {
    display: grid;
    width: 16px;
    height: 16px;
    place-items: center;
    border-radius: 5px;
    color: var(--color-muted);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .cs-chip-x:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.12); }
  .cs-clear {
    display: grid;
    width: 22px;
    height: 22px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.06);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .cs-clear:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.12); }
  .cs-daypicker { position: absolute; right: 8px; bottom: 0; width: 1px; height: 1px; opacity: 0; pointer-events: none; }

  .cs-sugs {
    position: absolute;
    left: 0;
    right: 0;
    top: calc(100% + 6px);
    z-index: 20;
    max-height: 280px;
    overflow-y: auto;
    padding: 5px;
    border-radius: 13px;
    box-shadow: 0 18px 44px -18px rgb(0 0 0 / 0.85);
    animation: cs-drop 0.18s var(--swift) both;
  }
  .cs-sug {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 9px;
    padding: 7px 9px;
    border-radius: 9px;
    font-size: 12.5px;
    text-align: left;
    color: var(--color-ink);
    transition: background-color 0.12s ease;
  }
  .cs-sug.is-on { background: rgb(255 255 255 / 0.07); }
  .cs-sug-icon {
    display: grid;
    width: 22px;
    height: 22px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 7px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 13%, transparent);
  }
  .cs-sug-label { flex-shrink: 0; font-weight: 600; }
  .cs-sug-hint { min-width: 0; margin-left: auto; overflow: hidden; font-size: 11.5px; color: var(--color-faint); white-space: nowrap; text-overflow: ellipsis; }

  /* ── Before anything is asked ────────────────────────────────────── */
  .cs-start { min-height: 0; flex: 1; overflow-y: auto; padding: 4px 10px 16px; }
  .cs-sec {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 12px 8px 6px;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--color-faint);
  }
  .cs-sec-btn {
    margin-left: auto;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0;
    text-transform: none;
    color: var(--color-faint);
  }
  .cs-sec-btn:hover { color: var(--color-ink); }
  .cs-keys { display: flex; flex-direction: column; gap: 3px; }
  .cs-key {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 12px;
    padding: 8px 10px 8px 8px;
    border-radius: 13px;
    text-align: left;
    transition: background-color 0.15s ease, transform 0.25s var(--spring);
    animation: cs-in 0.3s var(--swift) both;
    animation-delay: calc(var(--i, 0) * 35ms);
  }
  .cs-key:hover { background: rgb(255 255 255 / 0.05); }
  .cs-key:active { transform: scale(0.98); }
  .cs-key-icon {
    display: grid;
    width: 34px;
    height: 34px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 11px;
    color: var(--color-accent);
    background: linear-gradient(135deg, color-mix(in srgb, var(--color-accent) 20%, transparent),
                                        color-mix(in srgb, var(--color-accent) 7%, transparent));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 24%, transparent);
    transition: transform 0.35s var(--spring), background-color 0.2s ease;
  }
  .cs-key:hover .cs-key-icon { transform: scale(1.08) rotate(-6deg); }
  .cs-key-text { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 2px; }
  .cs-key-text b { font-size: 13px; font-weight: 600; line-height: 1.2; color: var(--color-ink); }
  .cs-key-text small { overflow: hidden; font-size: 11.5px; line-height: 1.25; color: var(--color-faint); white-space: nowrap; text-overflow: ellipsis; }
  .cs-key code {
    flex-shrink: 0;
    padding: 2px 7px;
    border-radius: 7px;
    font-family: ui-monospace, "Cascadia Code", monospace;
    font-size: 11px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
    opacity: 0.75;
    transition: opacity 0.15s ease, color 0.15s ease;
  }
  .cs-key:hover code { opacity: 1; color: var(--color-accent); }
  .cs-recent { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 6px; }
  .cs-recent-chip {
    display: inline-flex;
    max-width: 100%;
    align-items: center;
    gap: 6px;
    padding: 5px 11px 5px 9px;
    border-radius: 999px;
    font-size: 12px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 75%, transparent);
    transition: color 0.15s ease, background-color 0.15s ease, transform 0.2s var(--spring);
  }
  .cs-recent-chip span { min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .cs-recent-chip:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.08); transform: translateY(-1px); }
  .cs-tip {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 4px;
    margin: 18px 8px 0;
    font-size: 11px;
    color: var(--color-faint);
  }
  .cs-tip kbd {
    display: inline-grid;
    min-width: 20px;
    height: 19px;
    place-items: center;
    padding: 0 6px;
    border-radius: 6px;
    font-family: inherit;
    font-size: 10px;
    font-weight: 600;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.06);
    box-shadow: inset 0 -1.5px 0 rgb(0 0 0 / 0.35), inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
  }
  .cs-tip-dot { width: 3px; height: 3px; margin: 0 6px; border-radius: 999px; background: var(--color-faint); opacity: 0.6; }

  /* ── Results ─────────────────────────────────────────────────────── */
  .cs-head { display: flex; align-items: center; gap: 10px; padding: 2px 14px 0; }
  .cs-count {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-size: 12.5px;
    font-weight: 700;
    color: var(--color-ink);
    font-variant-numeric: tabular-nums;
  }
  .cs-sort { display: flex; margin-left: auto; padding: 2px; border-radius: 9px; background: rgb(255 255 255 / 0.04); }
  .cs-sort button {
    padding: 3px 8px;
    border-radius: 7px;
    font-size: 11px;
    color: var(--color-faint);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .cs-sort button:hover { color: var(--color-ink); }
  .cs-sort button.is-on { color: var(--color-ink); background: rgb(255 255 255 / 0.1); }
  .cs-scope {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 6px;
    padding: 4px 14px 8px;
    font-size: 11px;
    color: var(--color-faint);
    border-bottom: 1px solid color-mix(in srgb, var(--color-edge) 70%, transparent);
  }
  .cs-link { flex-shrink: 0; margin-left: auto; font-size: 11px; font-weight: 600; color: var(--color-accent); }
  .cs-link:hover { text-decoration: underline; }

  .cs-results { min-height: 0; flex: 1; overflow-y: auto; padding: 4px 8px 14px; }
  .cs-day {
    position: sticky;
    top: -4px;
    z-index: 1;
    display: flex;
    margin: 6px 0 2px;
    padding: 4px 6px;
  }
  .cs-day span {
    padding: 2px 9px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 600;
    color: var(--color-muted);
    background: color-mix(in srgb, var(--color-surface) 92%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
    backdrop-filter: blur(8px);
  }
  .cs-hit {
    position: relative;
    display: flex;
    width: 100%;
    align-items: flex-start;
    gap: 10px;
    padding: 9px 10px;
    border-radius: 12px;
    text-align: left;
    transition: background-color 0.14s ease, box-shadow 0.14s ease;
    animation: cs-in 0.25s var(--swift) both;
  }
  .cs-hit.is-active { background: rgb(255 255 255 / 0.05); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 90%, transparent); }
  .cs-hit-av { flex-shrink: 0; padding-top: 1px; }
  .cs-hit-main { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 3px; }
  .cs-hit-top { display: flex; min-width: 0; align-items: baseline; gap: 7px; font-size: 12.5px; }
  .cs-hit-top b { min-width: 0; overflow: hidden; font-weight: 600; color: var(--color-ink); white-space: nowrap; text-overflow: ellipsis; }
  .cs-hit-top time { flex-shrink: 0; font-size: 10.5px; color: var(--color-faint); font-variant-numeric: tabular-nums; }
  .cs-tag {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 3px;
    padding: 0 6px;
    border-radius: 999px;
    font-size: 10px;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.06);
  }
  .cs-tag.is-bad { color: color-mix(in srgb, var(--color-bad) 80%, var(--color-ink)); background: color-mix(in srgb, var(--color-bad) 14%, transparent); }
  .cs-hit-text {
    display: -webkit-box;
    overflow: hidden;
    font-size: 13px;
    line-height: 1.45;
    color: color-mix(in srgb, var(--color-ink) 88%, transparent);
    white-space: pre-wrap;
    word-break: break-word;
    -webkit-line-clamp: 5;
    line-clamp: 5;
    -webkit-box-orient: vertical;
  }
  .cs-hit.is-deleted .cs-hit-text { opacity: 0.7; }
  .cs-hit-text :global(mark), .cs-file :global(mark) {
    padding: 0 2px;
    border-radius: 4px;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 38%, transparent);
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-accent) 30%, transparent);
  }
  .cs-hit-text :global(strong) { font-weight: 700; }
  .cs-hit-text :global(em) { font-style: italic; }
  .cs-hit-text :global(.dm-code), .cs-hit-text :global(.dm-pre) {
    padding: 0 4px;
    border-radius: 5px;
    font-family: ui-monospace, monospace;
    font-size: 0.9em;
    background: rgb(0 0 0 / 0.3);
  }
  .cs-hit-text :global(.dm-link) { color: var(--color-accent); }
  .cs-hit-text :global(.dm-emoji) { display: inline-block; width: 1.3em; height: 1.3em; vertical-align: -0.3em; object-fit: contain; }
  .cs-hit-text :global(.dm-spoiler) { border-radius: 4px; background: color-mix(in srgb, var(--color-ink) 18%, transparent); }
  .cs-hit-media { display: flex; gap: 5px; margin-top: 2px; }
  .cs-thumb {
    position: relative;
    display: grid;
    width: 54px;
    height: 54px;
    overflow: hidden;
    place-items: center;
    border-radius: 9px;
    background: rgb(255 255 255 / 0.05);
  }
  .cs-thumb img { width: 100%; height: 100%; object-fit: cover; }
  .cs-thumb-video { display: grid; width: 26px; height: 26px; place-items: center; border-radius: 999px; color: #fff; background: rgb(0 0 0 / 0.5); }
  .cs-thumb-more {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    font-size: 12px;
    font-weight: 700;
    color: #fff;
    background: rgb(0 0 0 / 0.55);
  }
  .cs-file {
    display: inline-flex;
    max-width: 100%;
    align-items: center;
    gap: 6px;
    align-self: flex-start;
    padding: 3px 9px 3px 7px;
    border-radius: 8px;
    font-size: 11.5px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
  }
  .cs-jump {
    display: inline-flex;
    align-items: center;
    align-self: center;
    flex-shrink: 0;
    padding: 4px 9px;
    border-radius: 8px;
    font-size: 11px;
    font-weight: 600;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.08);
    opacity: 0;
    transform: translateX(4px);
    transition: opacity 0.15s ease, transform 0.2s var(--spring), background-color 0.15s ease;
  }
  .cs-hit:hover .cs-jump, .cs-hit.is-active .cs-jump, .cs-hit.is-busy .cs-jump { opacity: 1; transform: none; }
  .cs-hit:hover .cs-jump { background: var(--color-accent); color: var(--color-bg); }

  .cs-none {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 40px 18px;
    text-align: center;
    font-size: 12px;
    color: var(--color-faint);
  }
  .cs-none b { font-size: 13.5px; color: var(--color-ink); }
  .cs-none-icon {
    display: grid;
    width: 46px;
    height: 46px;
    margin-bottom: 4px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.05);
  }
  .cs-cta {
    margin-top: 6px;
    padding: 6px 13px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 600;
    color: var(--color-bg);
    background: var(--color-accent);
    transition: transform 0.2s var(--spring), filter 0.15s ease;
  }
  .cs-cta:hover { filter: brightness(1.08); transform: translateY(-1px); }
  .cs-more { display: flex; justify-content: center; align-items: center; gap: 7px; padding: 12px; font-size: 11.5px; color: var(--color-faint); }
  .cs-note { padding: 18px; text-align: center; font-size: 12px; }
  .cs-skel { display: flex; gap: 10px; padding: 10px; }
  .cs-skel-av { width: 30px; height: 30px; flex-shrink: 0; border-radius: 999px; background: rgb(255 255 255 / 0.05); }
  .cs-skel-lines { display: flex; flex: 1; flex-direction: column; gap: 7px; padding-top: 3px; }
  .cs-skel-lines i { height: 10px; border-radius: 6px; background: rgb(255 255 255 / 0.05); animation: cs-pulse 1.3s ease-in-out infinite; }
  .cs-spin {
    width: 11px;
    height: 11px;
    border-radius: 999px;
    border: 1.5px solid color-mix(in srgb, var(--color-accent) 30%, transparent);
    border-top-color: var(--color-accent);
    animation: cs-spin 0.7s linear infinite;
  }

  @keyframes cs-spin { to { transform: rotate(360deg); } }
  @keyframes cs-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
  @keyframes cs-pop { from { opacity: 0; transform: scale(0.7); } to { opacity: 1; transform: none; } }
  @keyframes cs-drop { from { opacity: 0; transform: translateY(-4px) scale(0.98); } to { opacity: 1; transform: none; } }
  @keyframes cs-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
  :global(:root[data-motion="off"]) .cs-chip,
  :global(:root[data-motion="off"]) .cs-sugs,
  :global(:root[data-motion="off"]) .cs-hit,
  :global(:root[data-motion="off"]) .cs-key { animation: none; }
</style>
