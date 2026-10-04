<script lang="ts">
  /**
   * The card every Dashboard widget sits in.
   *
   * The header is the same for all of them, so they behave alike: click the
   * title (or the chevron) to fold it away and back, the arrows to make it half
   * or full width, the cog for what it shows, and - while customising - the
   * cross to take it off the page. Folded, a widget keeps its title and what it
   * is set to, so the page still reads as a list of what is there.
   *
   * No card of its own: every widget sits on the Dashboard's one surface, and
   * the seams between them are the Dashboard's to draw.
   */
  import { slide } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import Icon from "../components/Icon.svelte";
  import { motionEnabled, type WidgetInstance } from "../stores";
  import { WIDGETS, setOption, updateWidget } from "./widgets";

  let {
    inst,
    arranging = false,
    onremove,
    children,
  }: {
    inst: WidgetInstance;
    arranging?: boolean;
    onremove?: () => void;
    children?: any;
  } = $props();

  const def = $derived(WIDGETS[inst.type]);
  const collapsed = $derived(!!inst.collapsed);
  let menu = $state(false);
  let menuEl: HTMLElement | null = $state(null);

  /** What it is set to, as short chips next to the title: "30 days · Top 5". */
  const chips = $derived(
    (def?.options ?? [])
      .map((o) => o.choices.find((c) => c.value === inst.options?.[o.key])?.label)
      .filter((x): x is string => !!x && x !== "Everything" && x !== "Cards" && x !== "Short"),
  );

  function toggle() {
    updateWidget(inst.id, { collapsed: !collapsed });
  }
  function resize() {
    updateWidget(inst.id, { size: inst.size === "full" ? "half" : "full" });
  }

  // Close the settings when clicking anywhere else, the way a menu should.
  $effect(() => {
    if (!menu) return;
    const off = (e: MouseEvent) => {
      if (menuEl && !menuEl.contains(e.target as Node)) menu = false;
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && (menu = false);
    setTimeout(() => window.addEventListener("click", off), 0);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("click", off);
      window.removeEventListener("keydown", esc);
    };
  });
</script>

<section class="widget group/widget relative" class:is-collapsed={collapsed} class:is-arranging={arranging}
         class:is-raised={menu}>
  <header class="flex items-center gap-2 px-4 py-3">
    {#if arranging}
      <span class="-ml-1 cursor-grab text-faint active:cursor-grabbing" title="Drag to move">
        <Icon name="grip" size={14} />
      </span>
    {/if}
    <button class="widget-title flex min-w-0 flex-1 items-center gap-2 text-left" onclick={toggle}
            aria-expanded={!collapsed} title={collapsed ? "Show" : "Fold away"}>
      <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-accent/12 text-accent">
        <Icon name={def?.icon ?? "stats"} size={13} />
      </span>
      <span class="truncate text-[13px] font-semibold tracking-tight text-ink">{def?.title ?? inst.type}</span>
      {#each chips as c}
        <span class="hidden shrink-0 rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-muted sm:inline">{c}</span>
      {/each}
    </button>

    <div class="widget-tools flex shrink-0 items-center gap-0.5">
      {#if def?.options?.length}
        <div class="relative" bind:this={menuEl}>
          <button class="widget-btn" class:is-on={menu} onclick={() => (menu = !menu)}
                  title="What it shows" aria-label="Widget settings" aria-expanded={menu}>
            <Icon name="settings" size={13} />
          </button>
          {#if menu}
            <div class="widget-menu glass floating pop absolute right-0 top-full z-30 mt-1.5 w-60 rounded-xl p-3">
              {#each def.options as o}
                <div class="mb-2.5 last:mb-0">
                  <div class="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-faint">{o.label}</div>
                  <div class="flex flex-wrap gap-1">
                    {#each o.choices as c}
                      <button
                        class="jelly rounded-lg px-2 py-1 text-[11px] transition-colors
                               {inst.options?.[o.key] === c.value
                                 ? 'bg-accent/20 text-accent'
                                 : 'bg-white/[0.05] text-muted hover:bg-white/[0.09] hover:text-ink'}"
                        onclick={() => setOption(inst.id, o.key, c.value)}
                      >{c.label}</button>
                    {/each}
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      {/if}
      <button class="widget-btn hidden lg:inline-flex" onclick={resize}
              title={inst.size === "full" ? "Make it half width" : "Make it full width"}
              aria-label={inst.size === "full" ? "Half width" : "Full width"}>
        <Icon name={inst.size === "full" ? "collapse" : "expand"} size={13} />
      </button>
      <button class="widget-btn widget-chevron" onclick={toggle}
              aria-label={collapsed ? "Show widget" : "Fold widget away"}>
        <Icon name="chevron" size={13} />
      </button>
      {#if arranging}
        <button class="widget-btn widget-remove" onclick={() => onremove?.()}
                title="Take it off the Dashboard" aria-label="Remove widget">
          <Icon name="close" size={13} />
        </button>
      {/if}
    </div>
  </header>

  <!-- Folded, the content is not just hidden but gone: slide measures the real
       height and animates to and from it, and a folded widget stops fetching
       and polling for data nobody can see.
       (This used to animate grid rows between 1fr and 0fr. Measured in a
       browser, the first fold after the page opened did not shrink at all, and
       with the spring easing the height lagged a click behind - the spring
       overshoots, which takes 0fr negative. Guessing at CSS internals twice was
       enough; slide measures instead.) -->
  {#if !collapsed}
    <div transition:slide={{ duration: $motionEnabled ? 380 : 0, easing: cubicOut }}>
      <!-- A size container: what is inside lays itself out by the widget's
           width, so half and full width each get a layout of their own. -->
      <div class="@container px-4 pb-4">{@render children?.()}</div>
    </div>
  {/if}
</section>

<style>
  .widget {
    border-radius: 18px;
    transition: border-color 0.2s ease, box-shadow 0.25s ease;
  }
  /* Lifted while its settings are open, or the widget below - its own layer
     under the glass look - covers the menu. app.css lifts the grid cell too. */
  .widget.is-raised {
    z-index: 25;
  }
  .widget-title {
    border-radius: 10px;
  }
  .widget-title:focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 2px;
  }

  .widget-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border-radius: 8px;
    color: var(--color-faint);
    transition: background-color 0.15s ease, color 0.15s ease, transform 0.15s var(--spring);
  }
  .widget-btn:hover,
  .widget-btn.is-on {
    background: rgb(255 255 255 / 0.07);
    color: var(--color-ink);
  }
  .widget-btn:active {
    transform: scale(0.88);
  }
  .widget-remove:hover {
    background: color-mix(in srgb, var(--color-bad) 18%, transparent);
    color: var(--color-bad);
  }

  /* The tools stay out of the way until the widget is pointed at, except while
     customising, when they are the point. The chevron always shows: folding is
     the thing people reach for without thinking about it. */
  .widget-tools > :not(.widget-chevron) {
    opacity: 0;
    transition: opacity 0.15s ease;
  }
  .widget:hover .widget-tools > *,
  .widget:focus-within .widget-tools > *,
  .widget.is-arranging .widget-tools > * {
    opacity: 1;
  }
  @media (hover: none) {
    .widget-tools > * {
      opacity: 1;
    }
  }

  .widget-chevron :global(svg) {
    transform: rotate(90deg);
    transition: transform 0.35s var(--spring);
  }
  .widget.is-collapsed .widget-chevron :global(svg) {
    transform: rotate(0deg);
  }

  :global(:root[data-motion="off"]) .widget-chevron :global(svg) {
    transition: none;
  }
</style>
