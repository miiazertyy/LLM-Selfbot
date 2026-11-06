<script lang="ts">
  /**
   * The community, on the Profiles page: profiles people made and shared, on GitHub. Browse them (popular, new,
   * trending; search; tags; 18+ only when asked for), look inside one before adding it, follow what you shared, and,
   * for the repo's owner, moderate. Opening it reads the catalog GitHub Pages serves: no sign-in needed to look.
   */
  import { onMount } from "svelte";
  import Segmented from "../components/Segmented.svelte";
  import Icon from "../components/Icon.svelte";
  import Toggle from "../components/Toggle.svelte";
  import Button from "../components/Button.svelte";
  import Num from "../dashboard/Num.svelte";
  import { chime, domino } from "../domino";
  import { play } from "../uisound";
  import { reloadPersonas } from "../personas/store";
  import CommunityCard from "./CommunityCard.svelte";
  import ProfileInspect from "./ProfileInspect.svelte";
  import MyShared from "./MyShared.svelte";
  import Moderation from "./Moderation.svelte";
  import DownloadsChart from "./DownloadsChart.svelte";
  import { communityRes, communityStatsRes, inspectSlug } from "./store";
  import { filterProfiles, installState, sortProfiles, timeAgo, type CommunityProfile, type Sort } from "./logic";
  import type { Persona } from "../personas/logic";

  let { personas = [], onshare, onupdate }: {
    personas?: Persona[];
    onshare: (pid: string) => void;
    onupdate: (pid: string) => void;
  } = $props();

  const home = $derived($communityRes.data);
  const stats = $derived($communityStatsRes.data);
  let tab = $state("browse");
  let sort = $state<Sort>("popular");
  let q = $state("");
  let tags = $state<string[]>([]);
  let adult = $state(false);

  onMount(() => {
    communityRes.refresh({ maxAge: 60_000 });
    communityStatsRes.refresh({ maxAge: 300_000, quiet: true });
  });

  const all = $derived(home.index.profiles ?? []);
  const shown = $derived(sortProfiles(filterProfiles(all, { q, tags, adult }), sort));
  const tagList = $derived((home.meta.tags ?? []).filter((t) => all.some((p) => (p.tags ?? []).includes(t))));
  const tabs = $derived([
    { id: "browse", label: "Browse", icon: "globe" },
    { id: "mine", label: "Shared by me", icon: "upload" },
    ...(home.moderator ? [{ id: "mod", label: "Moderation", icon: "alert" }] : []),
  ]);

  // The results moving under a search: one soft note when they settle, not one per key.
  let searchTimer = 0;
  let lastCount = -1;
  function searched() {
    clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      if (shown.length !== lastCount) play("slot", { level: 0.3 });
      lastCount = shown.length;
    }, 220);
  }

  function toggleTag(t: string) {
    const on = !tags.includes(t);
    tags = on ? [...tags, t] : tags.filter((x) => x !== t);
    play(on ? "on" : "off", { level: 0.6 });
  }

  function inspect(p: CommunityProfile) {
    play("open");
    inspectSlug.set(p.slug);
  }

  async function added() {
    await reloadPersonas();
    communityRes.refresh({ force: true, quiet: true });
  }

  function refresh() {
    play("tap");
    communityRes.refresh({ force: true });
    communityStatsRes.refresh({ force: true, quiet: true });
  }
</script>

<section class="cv">
  <div class="cv-bar">
    <span class="cv-tabs"><Segmented label="What to show" options={tabs} bind:value={tab} /></span>
    {#if home.state === "offline"}
      <span class="cv-chip is-warn" title="GitHub couldn't be reached"><Icon name="alert" size={11} />Offline. Showing the list from {home.fetched ? timeAgo(new Date(home.fetched * 1000).toISOString()) : "before"}.</span>
    {/if}
    <span class="cv-grow"></span>
    <button type="button" class="cv-icon" data-sound="self" onclick={refresh} title="Look again" aria-label="Look again">
      <span class:cv-spin={$communityRes.refreshing}><Icon name="refresh" size={14} /></span>
    </button>
  </div>

  {#if tab === "browse"}
    {#if home.state === "closed"}
      <div class="cv-empty" use:chime={"land"}>
        <Icon name="globe" size={22} />
        <b>The community isn't open yet.</b>
        <span>Its catalog on GitHub isn't there. Check again later.</span>
      </div>
    {:else}
      <div class="cv-stats domino" use:domino={{ step: 80, sound: "key", level: 0.45 }}>
        <span class="cv-stat"><Icon name="layers" size={13} /><b><Num value={home.index.totals.profiles} /></b>profiles</span>
        <span class="cv-stat"><Icon name="download" size={13} /><b><Num value={home.index.totals.downloads} /></b>downloads</span>
        <span class="cv-stat"><Icon name="stats" size={13} /><b><Num value={home.index.totals.week} /></b>this week</span>
        <span class="cv-spark"><DownloadsChart daily={stats.total?.daily ?? []} days={stats.days ?? []} n={30} /></span>
      </div>

      <div class="cv-tools" use:chime={{ sound: "land", delay: 120 }}>
        <label class="cv-search"><Icon name="search" size={13} />
          <input bind:value={q} oninput={searched} placeholder="Search profiles" aria-label="Search profiles" />
          {#if q}<button type="button" data-sound="self" aria-label="Clear the search" onclick={() => { q = ""; play("off"); searched(); }}><Icon name="close" size={11} /></button>{/if}
        </label>
        <span class="cv-sort"><Segmented label="Order" bind:value={sort} options={[
          { id: "popular", label: "Popular" }, { id: "new", label: "New" }, { id: "trending", label: "Trending" },
        ]} /></span>
        <Toggle bind:checked={adult} size="sm" label="Show 18+" />
      </div>
      {#if tagList.length}
        <div class="cv-tags" data-sound="self">
          {#each tagList as t (t)}
            <button type="button" class="cv-tag" class:is-on={tags.includes(t)} onclick={() => toggleTag(t)}>{t}</button>
          {/each}
        </div>
      {/if}

      {#if shown.length}
        <div class="cv-grid domino" use:domino={{ step: 55, sound: "pluck", max: 12 }}>
          {#each shown as p (p.slug)}
            <CommunityCard {p} state={installState(p, home.installed)} app={home.app ?? ""} onopen={inspect} />
          {/each}
        </div>
      {:else if all.length}
        <p class="cv-none">Nothing matches. Try fewer words or tags.</p>
      {:else}
        <div class="cv-empty" use:chime={"land"}>
          <Icon name="sparkle" size={22} />
          <b>No profiles yet.</b>
          <span>Be the first: share one of yours.</span>
          {#if home.sharing}<Button size="sm" onclick={() => { play("open"); onshare("*"); }}><Icon name="upload" size={12} />Share one</Button>{/if}
        </div>
      {/if}
    {/if}
  {:else if tab === "mine"}
    {#if home.sharing}
      <MyShared {personas} {onshare} app={home.app ?? ""} />
    {:else}
      <p class="cv-none">Sharing isn't open right now.</p>
    {/if}
  {:else if tab === "mod" && home.moderator}
    <Moderation />
  {/if}
</section>

<ProfileInspect bind:slug={$inspectSlug} {home} {stats} oninstalled={added} onupdate={(pid) => onupdate(pid)} />

<style>
  .cv { display: flex; flex-direction: column; gap: 14px; }
  .cv-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
  .cv-tabs { display: block; width: min(440px, 100%); }
  .cv-grow { flex: 1; }
  .cv-chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px; font-size: 11.5px; }
  .cv-chip.is-warn { color: var(--color-warn); background: color-mix(in srgb, var(--color-warn) 12%, transparent); }
  .cv-icon { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 10px; color: var(--color-muted);
             transition: background-color 0.15s ease, color 0.15s ease; }
  .cv-icon:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.06); }
  .cv-spin { display: grid; animation: cv-spin 0.9s linear infinite; }
  @keyframes cv-spin { to { transform: rotate(360deg); } }
  .cv-stats { display: flex; flex-wrap: wrap; align-items: stretch; gap: 10px; }
  .cv-stat { display: flex; flex-direction: column; gap: 2px; min-width: 110px; padding: 12px 16px; border-radius: 16px; font-size: 11.5px;
             color: var(--color-faint); background: var(--color-card); box-shadow: inset 0 0 0 1px var(--color-edge); }
  .cv-stat b { font-size: 21px; font-weight: 700; color: var(--color-ink); font-variant-numeric: tabular-nums; }
  .cv-stat :global(svg) { color: var(--color-accent); }
  .cv-spark { flex: 1; min-width: 220px; padding: 10px 14px 6px; border-radius: 16px; background: var(--color-card);
              box-shadow: inset 0 0 0 1px var(--color-edge); }
  .cv-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
  .cv-search { display: flex; min-width: 200px; flex: 1; align-items: center; gap: 8px; padding: 0 12px; border-radius: 12px;
               color: var(--color-faint); background: rgb(0 0 0 / 0.22); box-shadow: inset 0 0 0 1px var(--color-edge); }
  .cv-search:focus-within { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 55%, transparent); }
  .cv-search input { min-width: 0; flex: 1; height: 36px; font-size: 13px; color: var(--color-ink); background: none; outline: none; }
  .cv-search button { display: grid; place-items: center; color: var(--color-faint); }
  .cv-sort { display: block; width: 280px; max-width: 100%; }
  .cv-tags { display: flex; flex-wrap: wrap; gap: 6px; }
  .cv-tag { padding: 4px 11px; border-radius: 999px; font-size: 12px; color: var(--color-muted); background: rgb(255 255 255 / 0.03);
            box-shadow: inset 0 0 0 1px var(--color-edge); transition: background-color 0.15s ease, color 0.15s ease, transform 0.2s var(--spring); }
  .cv-tag.is-on { color: var(--color-ink); background: color-mix(in srgb, var(--color-accent) 20%, transparent);
                  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 50%, transparent); }
  .cv-tag:active { transform: scale(0.95); }
  .cv-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
  .cv-none { margin: 10px 0; font-size: 13px; color: var(--color-faint); }
  .cv-empty { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 40px 20px; border-radius: 20px; text-align: center;
              color: var(--color-faint); background: rgb(255 255 255 / 0.02); box-shadow: inset 0 0 0 1px var(--color-edge); }
  .cv-empty b { font-size: 15px; color: var(--color-ink); }
  .cv-empty :global(svg) { color: var(--color-accent); }
  :global(:root[data-motion="off"]) .cv-spin { animation: none; }
  :global(:root[data-motion="off"]) .cv-tag, :global(:root[data-motion="off"]) .cv-icon { transition: none; }
</style>
