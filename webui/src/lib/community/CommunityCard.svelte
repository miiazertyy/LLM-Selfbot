<script lang="ts">
  /** One community profile in the catalog: its face, name and line, who made it, its tags and downloads, and its
   *  version, with whether it was made for the app you have. */
  import Icon from "../components/Icon.svelte";
  import PersonaOrb from "../personas/PersonaOrb.svelte";
  import { api } from "../api";
  import { appWords, compact, type CommunityProfile } from "./logic";

  let { p, state = "none", app = "", onopen }: {
    p: CommunityProfile;
    state?: "none" | "installed" | "update";
    /** Your app's version, to say whether it was made for it. */
    app?: string;
    onopen: (p: CommunityProfile) => void;
  } = $props();

  const face = $derived({ name: p.name, color: p.color, avatar: p.avatar ? api.communityFile(p.slug, "avatar.jpg", p.version) : "" });
  const fit = $derived(appWords(p.app, app));
</script>

<button type="button" class="cc" style="--pc: {p.color || 'var(--color-accent)'}" onclick={() => onopen(p)} data-sound="self"
        aria-label="Look inside {p.name}">
  <span class="cc-wash" aria-hidden="true"></span>
  <span class="cc-head">
    <PersonaOrb p={face} size={50} />
    <span class="cc-who">
      <b class="cc-name">{p.name}</b>
      <small class="cc-by">by {p.author || "someone"}</small>
    </span>
    {#if state === "update"}
      <span class="cc-chip is-update"><Icon name="refresh" size={10} />v{p.version}</span>
    {:else if state === "installed"}
      <span class="cc-chip is-have"><Icon name="check" size={10} />Yours</span>
    {/if}
  </span>
  {#if p.tagline}<span class="cc-line">{p.tagline}</span>{/if}
  <span class="cc-tags">
    {#each (p.tags ?? []).slice(0, 4) as t (t)}<span class="cc-tag">{t}</span>{/each}
    {#if p.adult}<span class="cc-tag is-adult">18+</span>{/if}
  </span>
  <span class="cc-foot">
    <span title="Downloads"><Icon name="download" size={11} />{compact(p.downloads)}</span>
    {#if p.week}<span class="cc-week" title="This week">+{compact(p.week)} this week</span>{/if}
    {#if p.pictures}<span title="Pictures"><Icon name="pictures" size={11} />{p.pictures}</span>{/if}
    {#if p.videos}<span title="Videos"><Icon name="play" size={10} />{p.videos}</span>{/if}
    <span class="cc-v is-{fit.tone || 'plain'}" title={fit.long || `Version ${p.version}`}>v{p.version}{#if fit.short}<i>{fit.short}</i>{/if}</span>
  </span>
</button>

<style>
  .cc {
    position: relative;
    isolation: isolate;
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 9px;
    padding: 15px 15px 13px;
    overflow: hidden;
    border-radius: 20px;
    text-align: left;
    background: var(--color-card);
    box-shadow: inset 0 0 0 1px var(--color-edge), 0 10px 28px -22px rgb(0 0 0 / 0.8);
    transition: transform 0.28s var(--spring), box-shadow 0.25s ease;
  }
  .cc-wash {
    position: absolute;
    inset: 0;
    z-index: -1;
    background:
      radial-gradient(120% 90% at 0% 0%, color-mix(in srgb, var(--pc) 20%, transparent), transparent 62%),
      radial-gradient(80% 60% at 100% 100%, color-mix(in srgb, var(--pc) 9%, transparent), transparent 70%);
    opacity: 0.85;
    transition: opacity 0.25s ease;
  }
  .cc:hover {
    transform: translateY(-3px);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--pc) 45%, transparent),
                0 18px 36px -22px color-mix(in srgb, var(--pc) 75%, transparent);
  }
  .cc:hover .cc-wash { opacity: 1; }
  .cc:active { transform: translateY(-1px) scale(0.99); }
  .cc-head { display: flex; align-items: center; gap: 11px; min-width: 0; }
  .cc-who { display: flex; min-width: 0; flex: 1; flex-direction: column; }
  .cc-name { overflow: hidden; font-size: 14.5px; font-weight: 650; color: var(--color-ink); text-overflow: ellipsis; white-space: nowrap; }
  .cc-by { overflow: hidden; font-size: 11.5px; color: var(--color-faint); text-overflow: ellipsis; white-space: nowrap; }
  .cc-chip {
    display: inline-flex; flex-shrink: 0; align-items: center; gap: 4px; padding: 3px 8px; border-radius: 999px;
    font-size: 10.5px; font-weight: 600;
  }
  .cc-chip.is-have { color: var(--color-good); background: color-mix(in srgb, var(--color-good) 14%, transparent); }
  .cc-chip.is-update {
    color: var(--color-ink); background: color-mix(in srgb, var(--pc) 26%, transparent);
    box-shadow: 0 0 14px -4px color-mix(in srgb, var(--pc) 80%, transparent);
    animation: cc-glow 2.4s ease-in-out infinite;
  }
  @keyframes cc-glow { 50% { box-shadow: 0 0 20px -2px color-mix(in srgb, var(--pc) 95%, transparent); } }
  .cc-line {
    display: -webkit-box; overflow: hidden; font-size: 12.5px; line-height: 1.45; color: var(--color-muted);
    -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2;
  }
  .cc-tags { display: flex; flex-wrap: wrap; gap: 4px; min-height: 18px; }
  .cc-tag {
    padding: 1px 8px; border-radius: 999px; font-size: 10.5px; color: var(--color-muted);
    background: rgb(255 255 255 / 0.04); box-shadow: inset 0 0 0 1px var(--color-edge);
  }
  .cc-tag.is-adult { color: var(--color-warn); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-warn) 40%, transparent); }
  .cc-foot {
    display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; margin-top: auto; font-size: 11.5px;
    color: var(--color-faint);
  }
  .cc-foot > span { display: inline-flex; align-items: center; gap: 4px; }
  .cc-week { color: var(--color-good); }
  /* Its version, and whether it was made for your app: up to date, an older app, a newer one. */
  .cc-v { margin-left: auto; gap: 5px; font-variant-numeric: tabular-nums; }
  .cc-v i {
    padding: 1px 7px; border-radius: 999px; font-size: 10px; font-style: normal; font-weight: 600; white-space: nowrap;
  }
  .cc-v.is-good i { color: var(--color-good); background: color-mix(in srgb, var(--color-good) 13%, transparent); }
  .cc-v.is-warn i { color: var(--color-warn); background: color-mix(in srgb, var(--color-warn) 14%, transparent); }
  .cc-v.is-info i { color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 15%, transparent); }
  :global(:root[data-motion="off"]) .cc, :global(:root[data-motion="off"]) .cc-wash { transition: none; }
  :global(:root[data-motion="off"]) .cc-chip.is-update { animation: none; }
</style>
