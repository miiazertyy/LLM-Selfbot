<script lang="ts" module>
  /** Whose pictures are in, for as long as the app is open: a list opened again has them at once. */
  const pictureIn = new Set<string>();
  /** What was found last, so coming back to the tab shows it while it looks again. */
  let lastFound: any[] = [];
  /** Pictures of the page after this one, fetched ahead and held on to, so that turning to it has them drawn already. */
  const ahead = new Map<string, HTMLImageElement>();
</script>

<script lang="ts">
  /**
   * Getting a model: a search of Hugging Face, where the models are, rather than a box to paste a name into. Each result
   * has the picture of whoever made it, how many people use it, and whether it will run here; opened, it has its sizes,
   * and one click starts the download, which goes through the same line as anything else (localai.start_pull). Nothing
   * typed, it is what is popular. The searching and the fitting are app/utils/hfsearch.py.
   *
   * What the page is doing just now (a download, a file going in) goes in `between`, under the box and over the list,
   * so it stays in sight.
   *
   * Six at a time, with pages to turn: a long list pushed everything under it off the screen.
   */
  import { onDestroy, tick, untrack, type Snippet } from "svelte";
  import { slide } from "svelte/transition";
  import { flip } from "svelte/animate";
  import { cubicOut } from "svelte/easing";
  import { api } from "../api";
  import { motionEnabled, toast } from "../stores";
  import { play } from "../uisound";
  import Icon from "./Icon.svelte";
  import Segmented from "./Segmented.svelte";

  type Row = { repo: string; name: string; author: string; downloads: number; likes: number; updated: number;
               weights: number; sees: boolean; fit: "" | "fits" | "tight" | "big" };
  type Size = { tag: string; size: number; fits: boolean; best: boolean; have: boolean };
  type Sizes = { ok: boolean; reason?: string; sizes?: Size[]; sees?: boolean; why?: string };
  type Pull = { active: boolean; model: string; percent: number; queue?: { model: string }[] } | null;

  let { kind = "file", pull = null, models = [], pages = {}, starts = false, onget, between }: {
    /** How models are got here: "file" (the app fetches them, for llama.cpp) or "ollama" (it fetches them itself). */
    kind?: string;
    pull?: Pull;
    models?: string[];
    pages?: Record<string, { url: string; site: string }>;
    /** Show what is popular from the start, with nothing pressed: there are no models here yet. */
    starts?: boolean;
    /** Start a download of this: a repo, or a repo and a size. */
    onget: (name: string) => Promise<unknown> | unknown;
    between?: Snippet;
  } = $props();

  const motion = (ms: number) => ($motionEnabled ? ms : 0);
  const PER_PAGE = 6;

  let query = $state("");
  let sort = $state("popular");
  /** Only what will run on this computer, unless asked. */
  let fitting = $state(true);
  /** What kind of model and how big: asked of Hugging Face itself, so each batch is already that (app/utils/hfsearch.py
      KINDS, SIZES). */
  const KINDS = [
    { id: "", label: "Anything" }, { id: "sees", label: "Sees pictures" }, { id: "code", label: "Coding" },
    { id: "reasoning", label: "Reasoning" }, { id: "roleplay", label: "Roleplay" }, { id: "uncensored", label: "Uncensored" },
  ];
  const SCALES = [
    { id: "", label: "Any size" }, { id: "small", label: "Up to 4B" }, { id: "medium", label: "4B to 14B" },
    { id: "large", label: "14B to 40B" }, { id: "huge", label: "Over 40B" },
  ];
  let what = $state("");
  let scale = $state("");
  let filtersOpen = $state(false);
  const narrowed = $derived((what ? 1 : 0) + (scale ? 1 : 0));
  /** Where Hugging Face's next batch is ("" at the end), and whether it is being fetched. */
  let cursor = $state("");
  let more = $state(false);
  let engaged = $state(false);
  const showing = $derived(engaged || starts || !!query.trim());
  let found = $state<Row[]>(lastFound);
  let room = $state(0);
  let looking = $state(false);
  let failed = $state("");
  let asked = $state(false);
  let page = $state(0);
  /** Which way the last turn of the page went, for the cards to come in from that side. */
  let turned = $state(0);
  let box: HTMLInputElement | null = $state(null);

  /** The one opened, and the sizes of each one that has been. */
  let openRepo = $state("");
  let sizes = $state<Record<string, Sizes | "wait">>({});
  let chosen = $state<Record<string, string>>({});
  /** Between the press and the download starting: asking which file is the model can take seconds. */
  let getting = $state("");
  /** Whose pictures are in, for the list to draw. */
  let pictures = $state<string[]>([...pictureIn]);

  const fits = (r: Row) => !fitting || !r.fit || r.fit !== "big";
  const fitted = $derived(found.filter(fits));
  const pageCount = $derived(Math.max(1, Math.ceil(fitted.length / PER_PAGE)));
  /** The page shown: a list that came back shorter cannot leave it on a page that is no longer there. */
  const at = $derived(Math.min(page, pageCount - 1));
  const shown = $derived(fitted.slice(at * PER_PAGE, (at + 1) * PER_PAGE));
  /** Empty places on a short last page, so that the buttons under the cards do not move as the pages turn. */
  const blanks = $derived(pageCount > 1 ? PER_PAGE - shown.length : 0);
  /** The numbers to press: the first, the last and those round this one, with a gap where some are left out. */
  const numbers = $derived.by(() => {
    const out: number[] = [];
    for (let p = 0; p < pageCount; p++) {
      if (p === 0 || p === pageCount - 1 || Math.abs(p - at) <= 1) out.push(p);
      else if (out[out.length - 1] !== -1) out.push(-1);
    }
    return out;
  });

  function turnTo(p: number) {
    const next = Math.max(0, Math.min(pageCount - 1, p));
    if (next === at) return;
    turned = Math.sign(next - at);
    page = next;
    openRepo = "";
    play("tick");
  }
  /** A name that can be fetched as it stands, whatever the search says: a repo, a link, or an Ollama library name. */
  const direct = $derived.by(() => {
    const q = query.trim();
    if (!q) return "";
    if (/^(?:https?:\/\/(?:www\.)?(?:huggingface\.co|hf\.co)\/|hf\.co\/|huggingface\.co\/)?[\w.-]+\/[\w.-]+(?::[\w.-]+)?\/?$/i.test(q)) return q;
    return kind === "ollama" && /^[a-z0-9][\w.-]*(?::[\w.-]+)?$/i.test(q) ? q : "";
  });
  const directOnList = $derived(found.some((r) => r.repo.toLowerCase() === direct.split(":")[0].toLowerCase()));

  // ── Searching ────────────────────────────────────────────────────────────
  let ticket = 0;
  let waitTimer = 0;
  let againTimer = 0;
  async function look(tries = 2, freshen = 0) {
    const mine = ++ticket;
    // Already showing what was kept, and only freshening it: nothing to wait for, so nothing turning in the box.
    looking = !freshen;
    failed = "";
    clearTimeout(againTimer);
    try {
      const r: any = await api.localHfSearch(query.trim(), sort, what, scale);
      if (mine !== ticket) return;
      if (!r.ok) throw new Error(r.reason);
      found = lastFound = r.results;
      room = r.room || 0;
      cursor = r.next || "";
      dry = 0;
      if (!freshen) {
        page = 0;
        turned = 0;
      }
      asked = true;
      // What was kept from last time, with a new look behind it: that one, in a moment, without the page moving.
      if (r.stale && freshen < 4) againTimer = window.setTimeout(() => look(1, freshen + 1), 700);
    } catch (e: any) {
      if (mine !== ticket) return;
      // Cut off: once more by itself before saying so.
      if (tries > 1) {
        againTimer = window.setTimeout(() => look(tries - 1), 800);
        return;
      }
      if (!freshen) failed = e?.message || "Hugging Face did not answer. Try again.";
    }
    if (mine === ticket) looking = false;
  }

  /** The batch after the ones found, added to the end. A run of batches with nothing new that fits counts up `dry`. */
  let dry = 0;
  async function loadMore(): Promise<void> {
    if (!cursor || more) return;
    const mine = ticket;
    const before = fitted.length;
    more = true;
    try {
      const r: any = await api.localHfSearch(query.trim(), sort, what, scale, cursor);
      if (mine !== ticket || !r.ok) return;
      const have = new Set(found.map((x) => x.repo));
      found = lastFound = [...found, ...r.results.filter((x: Row) => !have.has(x.repo))];
      cursor = r.next || "";
      dry = fitted.length > before ? 0 : dry + 1;
    } catch {
      dry += 1;
    } finally {
      more = false;
    }
  }
  // Enough found to fill the page after this one, so the pages never run out under the reader. Four batches in a row
  // with nothing that fits stop it; the arrow fetches on past that.
  $effect(() => {
    const want = (at + 2) * PER_PAGE;
    if (!showing || !asked || looking || more || !cursor || fitted.length >= want || dry >= 4) return;
    untrack(() => loadMore());
  });
  /** The page after: there, or fetched first when this is the last one found so far. */
  async function onward() {
    if (at < pageCount - 1) return turnTo(at + 1);
    dry = 0;
    await loadMore();
    if (at < pageCount - 1) turnTo(at + 1);
  }

  // What is typed is looked for a moment after the typing stops; the order and the filters at once.
  let lastQuery: string | null = null;
  let lastSort = "";
  $effect(() => {
    const q = query.trim();
    const s = `${sort}|${what}|${scale}`;
    if (!showing || (q === lastQuery && s === lastSort)) return;
    const typed = q !== lastQuery && lastQuery !== null;
    lastQuery = q;
    lastSort = s;
    clearTimeout(waitTimer);
    waitTimer = window.setTimeout(() => look(), typed ? 240 : 0);
  });

  // ── The makers' pictures: fetched behind the page, several at once, and drawn as each comes in. This page's, and the
  // next one's so that turning to it has them already. ────────────────────────────────────────────────────────────
  let pictureRound = 0;
  let pictureTimer = 0;
  function watchPictures(wanted: string[], next: string[]) {
    const mine = ++pictureRound;
    clearTimeout(pictureTimer);
    const began = Date.now();
    const ask = async () => {
      const authors = [...wanted, ...next].filter((a) => !pictureIn.has(a));
      if (mine !== pictureRound || !authors.length) return;
      let left = 1;
      try {
        const r: any = await api.localHfPictures(authors);
        if (mine !== pictureRound) return;
        for (const a of r.ready ?? []) {
          pictureIn.add(a);
          if (next.includes(a) && !ahead.has(a)) {
            const img = new Image();
            img.src = api.localHfPicture(a);
            ahead.set(a, img);
          }
        }
        pictures = [...pictureIn];
        left = r.waiting ?? 0;
      } catch {
        /* the next look */
      }
      // Quick while they are coming, which is under a second: this stops as soon as there is nothing to wait for.
      if (left && Date.now() - began < 30000) pictureTimer = window.setTimeout(ask, 200);
    };
    ask();
  }
  // Another page, or a different filter: their pictures too.
  $effect(() => {
    if (!showing || !asked || !shown.length) return;
    const authorsOf = (rows: Row[]) => [...new Set(rows.map((r) => r.author))];
    const next = fitted.slice((at + 1) * PER_PAGE, (at + 2) * PER_PAGE);
    untrack(() => watchPictures(authorsOf(shown), authorsOf(next)));
  });
  onDestroy(() => {
    pictureRound++;
    clearTimeout(pictureTimer);
    clearTimeout(waitTimer);
    clearTimeout(againTimer);
    ticket++;
  });

  /** A picture the browser has already is simply there. Only one still on its way fades in. */
  function arrives(img: HTMLImageElement) {
    if (img.complete && img.naturalWidth) {
      img.classList.add("is-there");
      return;
    }
    const landed = () => img.classList.add("is-in");
    img.addEventListener("load", landed, { once: true });
    return { destroy: () => img.removeEventListener("load", landed) };
  }

  /** A picture that would not draw: the letter stays. */
  function pictureOff(author: string) {
    pictureIn.delete(author);
    pictures = pictures.filter((a) => a !== author);
  }

  // ── One opened ───────────────────────────────────────────────────────────
  async function loadSizes(repo: string, tries = 2) {
    sizes = { ...sizes, [repo]: "wait" };
    try {
      const r: Sizes = await api.localHfSizes(repo, kind);
      // Cut off, as it can be on some computers: once more by itself before saying so.
      if (!r.ok && tries > 1) return loadSizes(repo, tries - 1);
      sizes = { ...sizes, [repo]: r };
      const list = r.sizes ?? [];
      if (!chosen[repo] && list.length) {
        chosen = { ...chosen, [repo]: (list.find((s) => s.best) ?? list[0]).tag };
      }
    } catch (e: any) {
      sizes = { ...sizes, [repo]: { ok: false, reason: e?.message || "Hugging Face did not answer." } };
    }
  }

  function toggle(r: Row, at: HTMLElement) {
    openRepo = openRepo === r.repo ? "" : r.repo;
    play(openRepo ? "open" : "tick");
    if (!openRepo) return;
    const held = sizes[r.repo];
    if (!held || (held !== "wait" && !held.ok)) loadSizes(r.repo);
    // Once it has opened, the whole of it in view.
    setTimeout(() => at.closest(".ms-card")?.scrollIntoView({ block: "nearest", behavior: $motionEnabled ? "smooth" : "auto" }), motion(280));
  }

  // A download that finished: the sizes of the one open say so.
  let hadModels = -1;
  $effect(() => {
    const now = models.length;
    if (hadModels >= 0 && now !== hadModels) untrack(() => { if (openRepo) loadSizes(openRepo); });
    hadModels = now;
  });

  async function get(name: string, key = name) {
    if (getting) return;
    getting = key;
    try {
      await onget(name);
    } finally {
      getting = "";
    }
  }

  // ── What each is doing ───────────────────────────────────────────────────
  const plain = (m: string) => (m || "").replace(/^(?:https?:\/\/)?(?:hf\.co|huggingface\.co)\//i, "");
  /** Of the one downloading, its repo and how far; of those in line, their repos. */
  const pulling = $derived(pull?.active ? plain(pull.model) : "");
  const waitingNames = $derived((pull?.queue ?? []).map((q) => plain(q.model)));
  /** The repos of the models here, from where each came from. */
  const here = $derived.by(() => {
    const out = new Set<string>();
    for (const m of models) {
      const url = pages[m]?.url ?? "";
      const hit = /huggingface\.co\/([^/?#]+\/[^/?#]+)/i.exec(url);
      if (hit) out.add(hit[1].toLowerCase());
    }
    return out;
  });
  const isPulling = (repo: string) => pulling.toLowerCase().startsWith(repo.toLowerCase() + ":") || pulling.toLowerCase() === repo.toLowerCase();
  const isWaiting = (repo: string) => waitingNames.some((w) => w.toLowerCase().split(":")[0] === repo.toLowerCase());
  const isHere = (repo: string) => here.has(repo.toLowerCase());
  const sizePulling = (repo: string, tag: string) => pulling.toLowerCase() === `${repo}:${tag}`.toLowerCase();
  const sizeWaiting = (repo: string, tag: string) => waitingNames.some((w) => w.toLowerCase() === `${repo}:${tag}`.toLowerCase());

  // ── In words ─────────────────────────────────────────────────────────────
  const short = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1).replace(/\.0$/, "")}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1).replace(/\.0$/, "")}k` : String(n));
  const gb = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(n / 1e6))} MB`);
  const weights = (n: number) => (!n ? "" : n >= 1e9 ? `${(n / 1e9).toFixed(n >= 1e10 ? 0 : 1).replace(/\.0$/, "")}B` : `${Math.round(n / 1e6)}M`);
  function ago(ts: number) {
    if (!ts) return "";
    const days = Math.floor((Date.now() / 1000 - ts) / 86400);
    if (days < 1) return "today";
    if (days < 14) return days === 1 ? "yesterday" : `${days} days ago`;
    if (days < 60) return `${Math.floor(days / 7)} weeks ago`;
    if (days < 365) return `${Math.floor(days / 30)} months ago`;
    return days < 730 ? "a year ago" : `${Math.floor(days / 365)} years ago`;
  }
  /** How good a size is, for someone who does not read Q4_K_M: the number of bits in it. */
  function word(tag: string) {
    const bits = /Q(\d)/.exec(tag)?.[1];
    if (!bits) return "Full";
    return ({ "2": "Tiny", "3": "Small", "4": "Balanced", "5": "Good", "6": "Great", "7": "Great", "8": "Best" } as Record<string, string>)[bits] ?? "Balanced";
  }
  const FIT: Record<string, string> = { fits: "Fits", tight: "Small size fits", big: "Too big" };
  /** A letter's colour for a maker with no picture, always the same one for the same maker. */
  function hueOf(name: string) {
    let h = 0;
    for (const c of name) h = (h * 31 + c.charCodeAt(0)) % 360;
    return h;
  }

  function keydown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      if (query) query = "";
      else {
        engaged = false;
        box?.blur();
      }
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (direct && !directOnList) get(direct);
      else if (shown[0]) toggle(shown[0], box as HTMLElement);
    } else if (e.key === "PageDown" || e.key === "PageUp") {
      e.preventDefault();
      turnTo(at + (e.key === "PageDown" ? 1 : -1));
    }
  }

  function close() {
    query = "";
    engaged = false;
    openRepo = "";
    play("tick");
  }
  async function focusBox() {
    await tick();
    box?.focus();
  }
</script>

<div class="ms">
  <label class="ms-box" class:is-on={showing}>
    <span class="ms-box-icon"><Icon name="search" size={15} /></span>
    <input bind:this={box} bind:value={query} onfocus={() => (engaged = true)} onkeydown={keydown} spellcheck="false" autocomplete="off"
           placeholder="Search for a model on Hugging Face" aria-label="Search for a model on Hugging Face" />
    {#if looking}<span class="ms-spin" aria-hidden="true"></span>{/if}
    <img class="ms-box-mark" src="/providers/huggingface.png" alt="" draggable="false" />
    {#if showing && !starts}
      <button type="button" class="ms-x" onclick={close} aria-label="Close the search" title="Close"><Icon name="close" size={11} /></button>
    {:else if query}
      <button type="button" class="ms-x" onclick={() => { query = ""; focusBox(); }} aria-label="Clear it" title="Clear"><Icon name="close" size={11} /></button>
    {/if}
  </label>

  {@render between?.()}

  {#if showing}
    <div class="ms-found" transition:slide={{ duration: motion(280), easing: cubicOut }}>
      <div>
      <div class="ms-tools">
        <span class="ms-order">
          <Segmented label="Order" bind:value={sort}
                     options={[{ id: "popular", label: "Popular" }, { id: "trending", label: "Trending" }, { id: "new", label: "New" }]} />
        </span>
        {#if room}
          <button type="button" class="ms-chip" class:is-on={fitting} aria-pressed={fitting} data-sound="self"
                  onclick={() => { fitting = !fitting; page = 0; turned = 0; play(fitting ? "on" : "off"); }}
                  title="This computer can give a model about {gb(room)} of memory">
            {#if fitting}<Icon name="check" size={11} />{/if}Fits this computer
          </button>
        {/if}
        <button type="button" class="ms-chip" class:is-set={narrowed > 0} aria-expanded={filtersOpen} data-sound="self"
                onclick={() => { filtersOpen = !filtersOpen; play(filtersOpen ? "open" : "tick"); }}>
          <Icon name="filter" size={11} />Filters{#if narrowed}<span class="ms-count">{narrowed}</span>{/if}
        </button>
      </div>
      {#if filtersOpen}
        <!-- What it is and how big: Hugging Face's own tags and count, so every batch is already that. -->
        <div class="ms-filters" transition:slide={{ duration: motion(220), easing: cubicOut }}>
          <div class="ms-filter-row" role="group" aria-label="What it is" data-sound="self">
            <span class="ms-filter-name">What it is</span>
            {#each KINDS as k (k.id)}
              <button type="button" class="ms-opt" class:is-on={what === k.id} aria-pressed={what === k.id}
                      onclick={() => { what = k.id; play("select"); }}>{k.label}</button>
            {/each}
          </div>
          <div class="ms-filter-row" role="group" aria-label="Size" data-sound="self">
            <span class="ms-filter-name">Size</span>
            {#each SCALES as k (k.id)}
              <button type="button" class="ms-opt" class:is-on={scale === k.id} aria-pressed={scale === k.id}
                      onclick={() => { scale = k.id; play("select"); }}>{k.label}</button>
            {/each}
          </div>
        </div>
      {/if}
      </div>

      <!-- A name that can be fetched as it stands, and is not on the list: a repo the search does not show, or one of
           Ollama's own. -->
      {#if direct && !directOnList}
        <div class="ms-direct" transition:slide={{ duration: motion(180), easing: cubicOut }}>
          <span class="ms-direct-text"><b>{plain(direct)}</b><small>{direct.includes("/") ? "From Hugging Face, by its name" : "From Ollama's library"}</small></span>
          <button type="button" class="ms-get is-solid" onclick={() => get(direct)} disabled={!!getting}>
            {#if getting === direct}<span class="ms-spin is-small" aria-hidden="true"></span>{:else}<Icon name="download" size={12} />{/if}Get
          </button>
        </div>
      {/if}

      {#if failed}
        <div class="ms-note">
          <span>{failed}</span>
          <button type="button" class="ms-link" onclick={() => look()}>Try again</button>
        </div>
      {:else if !asked && !found.length}
        <div class="ms-grid" aria-hidden="true">{#each Array(PER_PAGE) as _}<div class="ms-card is-wait"></div>{/each}</div>
      {:else if !fitted.length}
        <div class="ms-note">
          {#if found.length}
            <span>None of these fit this computer.</span>
            <button type="button" class="ms-link" onclick={() => { fitting = false; play("off"); }}>Show them anyway</button>
          {:else if narrowed}
            <span>Nothing on Hugging Face matches these filters.</span>
            <button type="button" class="ms-link" onclick={() => { what = ""; scale = ""; play("off"); }}>Clear filters</button>
          {:else}
            <span>Nothing on Hugging Face by that name.</span>
          {/if}
        </div>
      {:else}
        {#key at}
        <div class="ms-grid" style="--from: {turned * 14}px; --rise: {turned ? 0 : 6}px">
          {#each shown as r, i (r.repo)}
            {@const open = openRepo === r.repo}
            {@const info = sizes[r.repo]}
            {@const pulls = isPulling(r.repo)}
            <article class="ms-card" class:is-open={open} style="--i: {i}" animate:flip={{ duration: motion(240), easing: cubicOut }}>
              <div class="ms-top">
                <button type="button" class="ms-main" aria-expanded={open} data-sound="self"
                        onclick={(e) => toggle(r, e.currentTarget as HTMLElement)}
                        title="{r.repo}: its sizes">
                  <span class="ms-pic" style="--h: {hueOf(r.author)}">
                    <span class="ms-pic-letter">{r.author.slice(0, 1).toUpperCase()}</span>
                    {#if pictures.includes(r.author)}
                      <img src={api.localHfPicture(r.author)} alt="" draggable="false" decoding="sync" use:arrives
                           onerror={() => pictureOff(r.author)} />
                    {/if}
                  </span>
                  <span class="ms-text">
                    <b title={r.name}>{r.name}</b>
                    <small>{r.author}{#if weights(r.weights)}{" · "}{weights(r.weights)}{/if}{#if r.sees}{" · "}Sees pictures{/if}</small>
                    <span class="ms-facts">
                      <span title="Downloads last month"><Icon name="download" size={10} />{short(r.downloads)}</span>
                      <span title="Likes"><Icon name="heart" size={10} />{short(r.likes)}</span>
                      {#if ago(r.updated)}<span>{ago(r.updated)}</span>{/if}
                    </span>
                  </span>
                </button>
                <div class="ms-side">
                  {#if pulls}
                    <span class="ms-state is-going"><span class="ms-spin is-small" aria-hidden="true"></span>{pull?.percent ?? 0}%</span>
                  {:else if isWaiting(r.repo)}
                    <span class="ms-state">In line</span>
                  {:else if isHere(r.repo)}
                    <span class="ms-state is-here"><Icon name="check" size={11} />Here</span>
                  {:else}
                    <!-- The size that suits this computer, picked by the server. Too big: opened, to see. -->
                    <button type="button" class="ms-get" onclick={() => get(r.repo)} disabled={!!getting || r.fit === "big"}
                            title={r.fit === "big" ? "No size of it fits this computer" : "Download the size that suits this computer"}>
                      {#if getting === r.repo}<span class="ms-spin is-small" aria-hidden="true"></span>{:else}<Icon name="download" size={12} />{/if}Get
                    </button>
                  {/if}
                  {#if FIT[r.fit]}<span class="ms-fit is-{r.fit}" title={r.fit === "fits" ? "It should run well here" : r.fit === "tight" ? "Only its smallest sizes will" : "It would barely run here"}>{FIT[r.fit]}</span>{/if}
                </div>
              </div>

              {#if open}
                <div class="ms-open" transition:slide={{ duration: motion(240), easing: cubicOut }}>
                  {#if info === "wait" || !info}
                    <div class="ms-sizes" aria-hidden="true">{#each Array(5) as _}<span class="ms-size is-wait"></span>{/each}</div>
                  {:else if !info.ok}
                    <div class="ms-note">
                      <span>{info.reason}</span>
                      <button type="button" class="ms-link" onclick={() => loadSizes(r.repo)}>Try again</button>
                    </div>
                  {:else if !info.sizes?.length}
                    <div class="ms-note"><span>It has no file that can be fetched from here.</span></div>
                  {:else}
                    {@const pickedTag = chosen[r.repo] ?? info.sizes[0].tag}
                    {@const picked = info.sizes.find((s) => s.tag === pickedTag) ?? info.sizes[0]}
                    <div class="ms-sizes" role="radiogroup" aria-label="Size">
                      {#each info.sizes as s (s.tag)}
                        <button type="button" role="radio" aria-checked={s.tag === picked.tag} class="ms-size" class:is-on={s.tag === picked.tag}
                                class:is-big={!s.fits} data-sound="self" title={s.tag}
                                onclick={() => { chosen = { ...chosen, [r.repo]: s.tag }; play("select"); }}>
                          <b>{word(s.tag)}{#if s.best}<i aria-label="Best for this computer"></i>{/if}</b>
                          <span>{gb(s.size)}</span>
                          <small>{s.have ? "Here" : s.tag}</small>
                        </button>
                      {/each}
                    </div>
                    <div class="ms-foot">
                      <span class="ms-foot-say">
                        {#if picked.have}Already on this computer.
                        {:else if picked.best}Best for this computer.
                        {:else if picked.fits}Fits this computer.
                        {:else}It will be slow here.{/if}
                        {#if info.sees} Can see pictures.{/if}
                      </span>
                      <a class="ms-link" href="https://huggingface.co/{r.repo}" target="_blank" rel="noopener noreferrer">
                        Hugging Face<Icon name="external" size={10} />
                      </a>
                      {#if sizePulling(r.repo, picked.tag)}
                        <span class="ms-state is-going"><span class="ms-spin is-small" aria-hidden="true"></span>{pull?.percent ?? 0}%</span>
                      {:else if sizeWaiting(r.repo, picked.tag)}
                        <span class="ms-state">In line</span>
                      {:else if picked.have}
                        <span class="ms-state is-here"><Icon name="check" size={11} />Here</span>
                      {:else}
                        <button type="button" class="ms-get is-solid" disabled={!!getting} onclick={() => get(`${r.repo}:${picked.tag}`)}>
                          {#if getting === `${r.repo}:${picked.tag}`}<span class="ms-spin is-small" aria-hidden="true"></span>{:else}<Icon name="download" size={12} />{/if}
                          Download {gb(picked.size)}
                        </button>
                      {/if}
                    </div>
                  {/if}
                </div>
              {/if}
            </article>
          {/each}
          {#each Array(blanks) as _}<div class="ms-card is-blank" aria-hidden="true"></div>{/each}
        </div>
        {/key}
        {#if pageCount > 1 || cursor}
          <nav class="ms-pages" aria-label="Pages" data-sound="self">
            <button type="button" class="ms-page is-arrow" disabled={at === 0} onclick={() => turnTo(at - 1)} aria-label="The page before">
              <span class="ms-back"><Icon name="chevron" size={11} /></span>
            </button>
            {#each numbers as p, i (p < 0 ? `gap${i}` : p)}
              {#if p < 0}
                <span class="ms-page-gap" aria-hidden="true">…</span>
              {:else}
                <button type="button" class="ms-page" class:is-on={p === at} aria-current={p === at ? "page" : undefined}
                        aria-label="Page {p + 1}" onclick={() => turnTo(p)}>{p + 1}</button>
              {/if}
            {/each}
            <!-- More on Hugging Face than found so far: the arrow fetches the next batch rather than stopping here. -->
            {#if cursor}<span class="ms-page-gap" aria-hidden="true">…</span>{/if}
            <button type="button" class="ms-page is-arrow" disabled={at === pageCount - 1 && (!cursor || more)} onclick={onward}
                    aria-label="The page after">
              {#if more && at === pageCount - 1}<span class="ms-spin is-small" aria-hidden="true"></span>{:else}<Icon name="chevron" size={11} />{/if}
            </button>
          </nav>
        {/if}
      {/if}
    </div>
  {/if}
</div>

<style>
  .ms { display: flex; flex-direction: column; gap: 10px; }

  /* ── The box ── */
  .ms-box {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 8px 0 13px;
    height: 44px;
    border-radius: 14px;
    cursor: text;
    background: color-mix(in srgb, var(--color-accent) 7%, rgb(255 255 255 / 0.03));
    transition: background-color 0.2s ease, box-shadow 0.2s ease;
  }
  .ms-box:hover { background: color-mix(in srgb, var(--color-accent) 10%, rgb(255 255 255 / 0.03)); }
  .ms-box:focus-within {
    background: color-mix(in srgb, var(--color-accent) 11%, rgb(255 255 255 / 0.03));
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 20%, transparent);
  }
  .ms-box-icon { display: grid; place-items: center; color: var(--color-accent); }
  .ms-box input { min-width: 0; flex: 1; font-size: 13.5px; color: var(--color-ink); background: none; outline: none; }
  .ms-box input::placeholder { color: var(--color-muted); }
  .ms-box-mark { width: 20px; height: 20px; flex-shrink: 0; object-fit: contain; opacity: 0.9; }
  .ms-x {
    display: grid;
    width: 26px;
    height: 26px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 9px;
    color: var(--color-muted);
    transition: background-color 0.15s ease, color 0.15s ease;
  }
  .ms-x:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
  .ms-spin {
    width: 14px;
    height: 14px;
    flex-shrink: 0;
    border-radius: 999px;
    border: 2px solid color-mix(in srgb, var(--color-accent) 25%, transparent);
    border-top-color: var(--color-accent);
    animation: ms-turn 0.8s linear infinite;
  }
  .ms-spin.is-small { width: 11px; height: 11px; border-width: 1.5px; }
  @keyframes ms-turn { to { transform: rotate(360deg); } }

  /* ── The list ── */
  .ms-found { display: flex; flex-direction: column; gap: 10px; overflow: hidden; padding: 2px; margin: -2px; }
  .ms-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .ms-order { width: 260px; max-width: 100%; }
  .ms-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 32px;
    padding: 0 12px;
    border-radius: 999px;
    font-size: 12px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.04);
    transition: background-color 0.15s ease, color 0.15s ease;
  }
  .ms-chip:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.07); }
  .ms-chip.is-on { color: var(--color-good); background: color-mix(in srgb, var(--color-good) 13%, transparent); }
  .ms-chip.is-set { color: var(--color-ink); background: color-mix(in srgb, var(--color-accent) 14%, transparent); }
  .ms-count {
    display: inline-grid; min-width: 16px; height: 16px; place-items: center; padding: 0 4px; border-radius: 999px;
    font-size: 10.5px; font-weight: 650; color: var(--color-bg); background: var(--color-accent);
  }
  .ms-filters { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
  .ms-filter-row { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; }
  .ms-filter-name { width: 74px; flex-shrink: 0; font-size: 11px; font-weight: 600; color: var(--color-faint); }
  .ms-opt {
    height: 28px; padding: 0 11px; border-radius: 999px; font-size: 12px; color: var(--color-muted);
    background: rgb(255 255 255 / 0.04); transition: background-color 0.15s ease, color 0.15s ease;
  }
  .ms-opt:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.07); }
  .ms-opt.is-on { color: var(--color-ink); background: color-mix(in srgb, var(--color-accent) 18%, transparent); }
  /* Two across, three down. An opened one takes the whole row, and `dense` lets the others close the gap it would leave. */
  .ms-grid { display: grid; grid-auto-flow: dense; grid-template-columns: repeat(auto-fill, minmax(min(100%, 290px), 1fr)); gap: 8px; }
  .ms-card {
    display: flex;
    min-width: 0;
    min-height: 68px;
    flex-direction: column;
    justify-content: center;
    border-radius: 14px;
    background: color-mix(in srgb, var(--color-accent) 5%, rgb(255 255 255 / 0.025));
    transition: background-color 0.18s ease;
    animation: ms-in 0.24s cubic-bezier(0.22, 1, 0.36, 1) backwards;
    animation-delay: calc(var(--i, 0) * 16ms);
  }
  @keyframes ms-in { from { opacity: 0; transform: translate(var(--from, 0), var(--rise, 0)); } }
  .ms-card.is-blank { visibility: hidden; animation: none; }
  .ms-card:hover { background: color-mix(in srgb, var(--color-accent) 8%, rgb(255 255 255 / 0.03)); }
  .ms-card.is-open { grid-column: 1 / -1; background: color-mix(in srgb, var(--color-accent) 9%, rgb(255 255 255 / 0.03)); }
  .ms-card.is-wait { height: 68px; animation: ms-wait 1.3s ease-in-out infinite alternate; }
  @keyframes ms-wait { from { opacity: 0.45; } to { opacity: 0.9; } }
  .ms-top { display: flex; align-items: stretch; }
  .ms-main { display: flex; min-width: 0; flex: 1; align-items: center; gap: 10px; padding: 9px 4px 9px 10px; text-align: left; }
  .ms-pic {
    position: relative;
    display: grid;
    width: 44px;
    height: 44px;
    flex-shrink: 0;
    overflow: hidden;
    place-items: center;
    border-radius: 11px;
    background: hsl(var(--h) 45% 32%);
  }
  .ms-pic-letter { font-size: 17px; font-weight: 700; color: hsl(var(--h) 80% 86%); }
  .ms-pic img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    opacity: 0;
    transition: opacity 0.18s ease;
  }
  .ms-pic :global(img.is-in), .ms-pic :global(img.is-there) { opacity: 1; }
  .ms-pic :global(img.is-there) { transition: none; }
  .ms-text { display: flex; min-width: 0; flex-direction: column; gap: 1px; }
  .ms-text b { overflow: hidden; font-size: 13px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; color: var(--color-ink); }
  .ms-text small { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; color: var(--color-muted); }
  .ms-facts { display: flex; gap: 8px; margin-top: 1px; overflow: hidden; font-size: 10.5px; color: var(--color-faint); white-space: nowrap; }
  .ms-facts span { display: inline-flex; align-items: center; gap: 3px; }
  .ms-side { display: flex; flex-shrink: 0; flex-direction: column; align-items: flex-end; justify-content: center; gap: 4px; padding: 8px 10px 8px 2px; }
  .ms-fit { font-size: 10.5px; font-weight: 600; white-space: nowrap; }
  .ms-fit.is-fits { color: var(--color-good); }
  .ms-fit.is-tight { color: var(--color-warn); }
  .ms-fit.is-big { color: var(--color-faint); }
  .ms-get {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    height: 26px;
    padding: 0 9px;
    border-radius: 8px;
    font-size: 11.5px;
    font-weight: 600;
    white-space: nowrap;
    color: var(--color-accent);
    transition: opacity 0.15s ease;
  }
  .ms-get:disabled { opacity: 0.4; }
  .ms-get.is-solid { height: 32px; padding: 0 14px; color: var(--color-bg); background: var(--color-accent); }
  .ms-get.is-solid:hover:not(:disabled) { background: color-mix(in srgb, var(--color-accent) 85%, white); }
  .ms-state { display: inline-flex; align-items: center; gap: 5px; height: 28px; font-size: 12px; font-weight: 600; color: var(--color-muted); white-space: nowrap; }
  .ms-state.is-going { color: var(--color-accent); font-variant-numeric: tabular-nums; }
  .ms-state.is-here { color: var(--color-good); }

  /* ── Opened: its sizes ── */
  .ms-open { display: flex; flex-direction: column; gap: 10px; padding: 0 12px 12px; }
  .ms-sizes { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 6px; }
  .ms-size {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 1px;
    padding: 8px 10px;
    border-radius: 11px;
    text-align: left;
    background: rgb(255 255 255 / 0.04);
    transition: background-color 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease;
  }
  .ms-size:hover { background: rgb(255 255 255 / 0.07); }
  .ms-size.is-on { background: color-mix(in srgb, var(--color-accent) 18%, transparent); box-shadow: inset 0 0 0 1.5px var(--color-accent); }
  .ms-size.is-big:not(.is-on) { opacity: 0.55; }
  .ms-size.is-wait { height: 62px; animation: ms-wait 1.3s ease-in-out infinite alternate; }
  .ms-size b { display: flex; align-items: center; gap: 5px; font-size: 12.5px; font-weight: 650; color: var(--color-ink); }
  .ms-size b i { width: 6px; height: 6px; border-radius: 999px; background: var(--color-good); }
  .ms-size span { font-size: 12px; color: var(--color-muted); font-variant-numeric: tabular-nums; }
  .ms-size small { overflow: hidden; font-family: ui-monospace, monospace; font-size: 9.5px; text-overflow: ellipsis; white-space: nowrap; color: var(--color-faint); }
  .ms-foot { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 12px; }
  .ms-foot-say { margin-right: auto; font-size: 12px; color: var(--color-muted); }
  .ms-link { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--color-accent); }
  .ms-link:hover { text-decoration: underline; }

  .ms-note { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 12px 14px; border-radius: 14px; font-size: 12.5px; color: var(--color-muted); background: rgb(255 255 255 / 0.03); }
  .ms-direct { display: flex; align-items: center; gap: 12px; padding: 10px 12px 10px 14px; border-radius: 14px; background: color-mix(in srgb, var(--color-accent) 10%, transparent); }
  .ms-direct-text { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 1px; }
  .ms-direct-text b { overflow: hidden; font-size: 13px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; color: var(--color-ink); }
  .ms-direct-text small { font-size: 11.5px; color: var(--color-muted); }

  /* ── The pages ── */
  .ms-pages { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 3px; padding-top: 2px; }
  .ms-page {
    display: grid;
    min-width: 28px;
    height: 28px;
    padding: 0 7px;
    place-items: center;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 600;
    color: var(--color-muted);
    font-variant-numeric: tabular-nums;
    transition: color 0.15s ease, opacity 0.15s ease;
  }
  .ms-page:hover:not(:disabled) { color: var(--color-ink); }
  .ms-page.is-on { color: var(--color-bg); background: var(--color-accent); }
  .ms-page.is-on:hover { color: var(--color-bg); }
  .ms-page:disabled { opacity: 0.32; }
  .ms-page-gap { display: grid; width: 18px; place-items: center; font-size: 12px; color: var(--color-faint); }
  .ms-back { display: grid; transform: rotate(180deg); }

  :global(:root[data-motion="off"]) .ms-card,
  :global(:root[data-motion="off"]) .ms-card.is-wait,
  :global(:root[data-motion="off"]) .ms-size.is-wait { animation: none; }
  :global(:root[data-motion="off"]) .ms-spin { animation-duration: 2.4s; }
</style>
