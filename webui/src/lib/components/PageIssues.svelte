<script lang="ts">
  import { settingsSection } from "../stores";

  /** Open the page that fixes this, and the category holding the control. */
  function goThere(issue: { route: string; section?: string }) {
    if (issue.section) settingsSection.set(issue.section);
    window.location.hash = `/${issue.route}`;
  }

  /**
   * The issues belonging to the page you are currently on.
   *
   * The sidebar dot tells you WHICH tab has a problem; this tells you where on
   * that tab, so arriving does not turn into hunting for the right control.
   *
   * Rendered once in App.svelte above the routed page, so every tab gets it
   * without each page having to remember to include it.
   */
  import { health } from "../stores";
  import Icon from "./Icon.svelte";

  let { route } = $props<{ route: string }>();

  const mine = $derived(($health.issues ?? []).filter((i) => i.route === route));
</script>

{#if mine.length}
  <div class="mb-4 space-y-2">
    {#each mine as issue}
      <div
        class="rise flex items-start gap-3 rounded-xl border px-4 py-3
          {issue.level === 'error'
            ? 'border-bad/40 bg-bad/[0.07]'
            : 'border-warn/40 bg-warn/[0.06]'}"
      >
        <span class="mt-0.5 shrink-0 {issue.level === 'error' ? 'text-bad' : issue.level === 'info' ? 'text-accent' : 'text-warn'}">
          <Icon name="alert" size={16} />
        </span>
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-ink">{issue.title}</div>
          <p class="mt-0.5 text-[11px] leading-relaxed text-muted">{issue.detail}</p>
          {#if issue.where}
            <!-- A label telling you where to look still leaves you looking.
                 This opens the exact category, so the control is on screen
                 when you arrive. -->
            <p class="mt-1.5 text-[11px] text-faint">
              <button
                type="button"
                onclick={() => goThere(issue)}
                class="rounded bg-white/[0.07] px-1.5 py-0.5 font-medium text-ink transition-colors
                       hover:bg-accent/20 hover:text-accent"
              >{issue.where}</button>
              <span class="ml-1">take me there</span>
            </p>
          {/if}
        </div>
      </div>
    {/each}
  </div>
{/if}
