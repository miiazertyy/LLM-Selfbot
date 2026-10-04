<script lang="ts">
  /**
   * The idle scene for what is stopping the bot working: the same list that
   * puts the dots in the sidebar (App.svelte polls it), each with the page
   * that fixes it. It only comes round while there is something to fix, and
   * "Open" leaves Big Picture for that page, since fixing it means a form.
   */
  import Icon from "../components/Icon.svelte";
  import { popIn } from "./motion";
  import { ripple } from "./fx";
  import type { HealthIssue } from "./types";

  let { issues = [], onopen }: { issues?: HealthIssue[]; onopen?: (route: string) => void } = $props();

  const PAGE: Record<string, string> = {
    dashboard: "Dashboard", accounts: "Accounts", chats: "Chats", profiles: "Profiles", persona: "Persona", memory: "Memory",
    pictures: "Pictures", logs: "Logs", settings: "Settings", system: "System",
  };
  const ICON: Record<string, string> = { error: "alertCircle", warn: "alert", info: "info" };
  const RANK: Record<string, number> = { error: 0, warn: 1, info: 2 };
  const sorted = $derived(issues.slice().sort((a, b) => (RANK[a.level] ?? 3) - (RANK[b.level] ?? 3)));
  const errors = $derived(issues.filter((i) => i.level === "error").length);
  /** Counted the way the top bar counts: an available update is a note, not a problem. */
  const serious = $derived(issues.filter((i) => i.level === "error" || i.level === "warn").length);
  const notes = $derived(issues.length - serious);
</script>

<div class="bph">
  <div class="bp-kicker" in:popIn|global={{ delay: 40, from: 0.96 }}>
    Health · {serious} to look at{notes ? ` · ${notes} ${notes === 1 ? "note" : "notes"}` : ""}
  </div>
  <h2 class="bp-title" in:popIn|global={{ delay: 90, from: 0.96 }}>{errors ? "Something is broken" : "Needs attention"}</h2>

  {#if sorted.length}
    <ul class="bph-list">
      {#each sorted.slice(0, 5) as it, i (it.title + it.route)}
        <li class="bph-item" data-level={it.level} in:popIn|global={{ delay: 160 + i * 100, from: 0.92 }}>
          <span class="bph-icon"><Icon name={ICON[it.level] ?? "info"} size={20} /></span>
          <div class="bph-text">
            <div class="bph-title">{it.title}</div>
            {#if it.detail}<div class="bph-detail">{it.detail}</div>{/if}
          </div>
          {#if onopen && PAGE[it.route]}
            <button class="bph-btn" use:ripple onclick={() => onopen?.(it.route)} title="Leave Big Picture and open {PAGE[it.route]}">
              Open {PAGE[it.route]}<Icon name="chevron" size={13} />
            </button>
          {/if}
        </li>
      {/each}
    </ul>
    {#if sorted.length > 5}<div class="bph-more">and {sorted.length - 5} more on the Dashboard</div>{/if}
  {:else}
    <div class="bph-ok" in:popIn|global={{ delay: 120, from: 0.8 }}>
      <span class="bph-check"><Icon name="check" size={36} /></span>
      <p>Everything is working.</p>
    </div>
  {/if}
</div>

<style>
  .bph { display: flex; height: 100%; min-width: 0; flex-direction: column; justify-content: safe center; gap: 12px; padding: 10px 6px; }
  .bph-list { display: flex; min-width: 0; flex-direction: column; gap: 10px; }
  .bph-item {
    position: relative;
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 16px;
    padding: 16px 18px;
    overflow: hidden;
    border-radius: 22px;
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08);
  }
  /* A bar of the level's colour down the left edge. */
  .bph-item::before { content: ""; position: absolute; left: 0; top: 14px; bottom: 14px; width: 4px; border-radius: 0 4px 4px 0; background: var(--bp-faint); }
  .bph-item[data-level="error"]::before { background: var(--color-bad); box-shadow: 0 0 18px color-mix(in srgb, var(--color-bad) 42%, transparent); }
  .bph-item[data-level="warn"]::before { background: var(--color-warn); }
  .bph-icon { display: grid; width: 44px; height: 44px; flex-shrink: 0; place-items: center; border-radius: 14px; color: var(--bp-muted); background: rgb(255 255 255 / 0.06); }
  .bph-item[data-level="error"] .bph-icon { color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 16%, transparent); }
  .bph-item[data-level="warn"] .bph-icon { color: var(--color-warn); background: color-mix(in srgb, var(--color-warn) 14%, transparent); }
  /* A note, not a problem: it sits back behind the ones that are. */
  .bph-item[data-level="info"] { background: rgb(255 255 255 / 0.03); }
  .bph-item[data-level="info"] .bph-title { font-size: clamp(14px, 1.1vw, 17px); color: var(--bp-muted); }
  .bph-text { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 3px; }
  .bph-title { font-size: clamp(16px, 1.3vw, 20px); font-weight: 700; color: #fff; }
  .bph-detail {
    display: -webkit-box;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    font-size: 13.5px;
    line-height: 1.45;
    color: var(--bp-muted);
  }
  .bph-btn {
    position: relative;
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 6px;
    height: 40px;
    padding: 0 16px;
    overflow: hidden;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 650;
    color: #fff;
    background: rgb(255 255 255 / 0.08);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.1);
    transition: transform 0.25s var(--spring), background-color 0.2s ease;
  }
  .bph-btn:hover { transform: translateX(2px); background: color-mix(in srgb, var(--color-accent) 35%, transparent); }
  .bph-btn:active { transform: scale(0.95); }
  .bph-more { font-size: 13px; color: var(--bp-faint); text-align: center; }
  .bph-ok { display: flex; flex-direction: column; align-items: center; gap: 14px; padding: 20px; }
  .bph-check {
    display: grid;
    width: 84px;
    height: 84px;
    place-items: center;
    border-radius: 999px;
    color: #fff;
    background: var(--color-good);
    box-shadow: 0 0 0 10px color-mix(in srgb, var(--color-good) 18%, transparent), 0 0 70px color-mix(in srgb, var(--color-good) 40%, transparent);
  }
  .bph-ok p { font-size: 17px; color: var(--bp-muted); }
  /* A phone: the words get the width, and the button goes under them. */
  @media (max-width: 720px) {
    .bph-item { flex-wrap: wrap; }
    .bph-text { flex: 1 1 220px; }
    .bph-btn { margin-left: 60px; }
  }
</style>
