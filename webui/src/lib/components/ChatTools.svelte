<script lang="ts">
  /**
   * The panel beside a conversation: search it, or see what was shared in it,
   * its pictures and videos, its files, its links. Opened from the buttons by
   * the name at the top, the way Discord's are. A tab keeps where it was while
   * another is shown, so going back finds the search, or the scroll, as it was.
   */
  import { untrack } from "svelte";
  import { play } from "../uisound";
  import Icon from "./Icon.svelte";
  import ChatSearch from "./ChatSearch.svelte";
  import ChatShared from "./ChatShared.svelte";

  type Tab = "search" | "media" | "files" | "links";
  type Side = { name: string; username?: string; avatar?: string };

  let {
    tab = $bindable("search"),
    target,
    uid,
    platform,
    them,
    me,
    focusKey = 0,
    onjump,
    onclose,
  }: {
    tab?: Tab;
    target: string;
    uid: string;
    platform: string;
    them: Side;
    me: Side;
    focusKey?: number;
    onjump: (mid: string) => Promise<unknown> | void;
    onclose: () => void;
  } = $props();

  const TABS: { id: Tab; label: string; icon: string }[] = [
    { id: "search", label: "Search", icon: "search" },
    { id: "media", label: "Media", icon: "pictures" },
    { id: "files", label: "Files", icon: "file" },
    { id: "links", label: "Links", icon: "link" },
  ];
  const at = $derived(Math.max(0, TABS.findIndex((t) => t.id === tab)));

  // Tabs already opened stay mounted, hidden; the search takes the keyboard each time it is shown.
  let seen = $state<Record<string, true>>({});
  let searchFocus = $state(0);
  $effect(() => {
    const now = tab;
    focusKey;
    untrack(() => {
      seen[now] = true;
      if (now === "search") searchFocus++;
    });
  });

  function choose(id: Tab) {
    if (id === tab) return;
    tab = id;
    play("select");
  }
</script>

<aside class="ct" aria-label="Search and shared things">
  <header class="ct-head">
    <div class="ct-tabs" role="tablist" style="--n: {TABS.length}; --at: {at}" data-sound="self">
      <span class="ct-pill" aria-hidden="true"></span>
      {#each TABS as t (t.id)}
        <button type="button" role="tab" aria-selected={tab === t.id} class:is-on={tab === t.id} onclick={() => choose(t.id)}>
          <Icon name={t.icon} size={13} /><span>{t.label}</span>
        </button>
      {/each}
    </div>
    <button type="button" class="ct-close" onclick={onclose} aria-label="Close" title="Close (Esc)">
      <Icon name="close" size={12} />
    </button>
  </header>
  {#each TABS as t (t.id)}
    {#if seen[t.id]}
      <div class="ct-body" class:is-hidden={tab !== t.id} role="tabpanel" aria-label={t.label}>
        {#if t.id === "search"}
          <ChatSearch {target} {uid} {platform} {them} {me} focusKey={searchFocus} {onjump} {onclose} />
        {:else}
          <ChatShared kind={t.id} {target} {uid} {platform} {them} {onjump} />
        {/if}
      </div>
    {/if}
  {/each}
</aside>

<style>
  .ct { display: flex; height: 100%; min-height: 0; flex-direction: column; }
  .ct-head {
    display: flex;
    flex-shrink: 0;
    align-items: center;
    gap: 8px;
    padding: 10px 10px 0 12px;
  }
  .ct-tabs {
    position: relative;
    display: grid;
    min-width: 0;
    flex: 1;
    grid-template-columns: repeat(var(--n), minmax(0, 1fr));
    padding: 3px;
    border-radius: 12px;
    background: rgb(0 0 0 / 0.22);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
  }
  /* One pill, sliding to the tab picked, the way the app's other choices move. */
  .ct-pill {
    position: absolute;
    top: 3px;
    bottom: 3px;
    left: 3px;
    width: calc((100% - 6px) / var(--n));
    border-radius: 9px;
    background: color-mix(in srgb, var(--color-accent) 22%, rgb(255 255 255 / 0.05));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 40%, transparent);
    transform: translateX(calc(var(--at) * 100%));
    transition: transform 0.38s var(--spring);
  }
  .ct-tabs button {
    position: relative;
    display: inline-flex;
    min-width: 0;
    align-items: center;
    justify-content: center;
    gap: 5px;
    padding: 6px 4px;
    border-radius: 9px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--color-faint);
    transition: color 0.2s ease;
  }
  .ct-tabs button span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ct-tabs button:hover { color: var(--color-muted); }
  .ct-tabs button.is-on { color: var(--color-ink); }
  .ct-close {
    display: grid;
    width: 30px;
    height: 30px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 10px;
    color: var(--color-faint);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .ct-close:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
  .ct-body { display: flex; min-height: 0; flex: 1; flex-direction: column; }
  .ct-body.is-hidden { display: none; }
  /* Narrow: the labels go, the icons stay. */
  @container (max-width: 330px) {
    .ct-tabs button span { display: none; }
  }
  :global(:root[data-motion="off"]) .ct-pill { transition: none; }
</style>
