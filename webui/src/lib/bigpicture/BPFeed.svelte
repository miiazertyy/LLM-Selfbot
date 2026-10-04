<script lang="ts">
  /**
   * Everything that just happened, as it happens: a message arriving, a reply
   * being written and sent, which model answered and how fast, a model being
   * refused, a friend request. Each slides in, and fades after half a minute.
   */
  import Avatar from "../components/Avatar.svelte";
  import Icon from "../components/Icon.svelte";
  import { slideIn, slideOut } from "./motion";
  import type { FeedItem } from "./types";

  let {
    items = [],
    now = 0,
    hideText = false,
    /** How far back counts. Half a minute where it is a live ticker beside the
        stage; longer where it is a panel of its own, which would otherwise be an
        empty box for most of the time nothing is happening. */
    window: secs = 30,
    max = 5,
    when = false,
  }: {
    items?: FeedItem[];
    now?: number;
    hideText?: boolean;
    window?: number;
    max?: number;
    /** Show how long ago each one was; worth it once the window is long. */
    when?: boolean;
  } = $props();

  const ICON: Record<FeedItem["kind"], string> = {
    arrive: "chats", write: "sparkle", sent: "check", model: "sparkle", limit: "alert", friend: "userPlus",
    picture: "pictures",
  };
  const fresh = $derived(items.filter((i) => now - i.at < secs).slice(0, max));
  function ago(at: number): string {
    const s = Math.max(0, now - at);
    if (s < 10) return "now";
    if (s < 60) return `${Math.floor(s)}s`;
    return `${Math.floor(s / 60)}m`;
  }
</script>

<section class="bpf" aria-live="polite">
  {#each fresh as it (it.id)}
    <div class="bpf-item" data-kind={it.kind} in:slideIn out:slideOut>
      {#if it.avatar || it.name}
        <Avatar src={it.avatar} name={it.name ?? ""} size={22} zoom={false} />
      {:else}
        <span class="bpf-icon"><Icon name={ICON[it.kind]} size={12} /></span>
      {/if}
      <span class="bpf-text" class:is-hidden={hideText && it.kind === "arrive"}>{it.text}</span>
      {#if when}<span class="bpf-when">{ago(it.at)}</span>{/if}
      <span class="bpf-kind"><Icon name={ICON[it.kind]} size={11} /></span>
    </div>
  {/each}
</section>

<style>
  .bpf { display: flex; min-height: 0; flex-direction: column; gap: 6px; }
  .bpf-item {
    display: flex;
    flex-shrink: 0;
    align-items: center;
    gap: 9px;
    padding: 7px 10px 7px 7px;
    border-radius: 14px;
    font-size: 12.5px;
    color: #fff;
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06);
    backdrop-filter: blur(14px);
  }
  .bpf-icon { display: grid; width: 22px; height: 22px; place-items: center; border-radius: 999px; background: rgb(255 255 255 / 0.08); }
  .bpf-text { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bpf-text.is-hidden { filter: blur(5px); }
  .bpf-when { flex-shrink: 0; font-size: 11px; color: var(--bp-faint); font-variant-numeric: tabular-nums; }
  .bpf-kind { flex-shrink: 0; color: var(--bp-faint); }
  .bpf-item[data-kind="sent"] .bpf-kind { color: var(--color-good); }
  .bpf-item[data-kind="write"] .bpf-kind, .bpf-item[data-kind="model"] .bpf-kind { color: var(--color-accent); }
  .bpf-item[data-kind="limit"] .bpf-kind { color: var(--color-warn); }
  .bpf-item[data-kind="friend"] .bpf-kind, .bpf-item[data-kind="picture"] .bpf-kind { color: var(--color-accent); }
</style>
