<script lang="ts">
  /**
   * A person's name, anywhere in the app, as something you can click.
   *
   * Clicking opens a card built entirely from what is already stored locally:
   * the cached bio, the facts the bot has remembered, and the message log.
   * Nothing is fetched from Discord, so clicking a name costs nothing and
   * works for accounts that are stopped.
   *
   * The whole thing can be switched off in Settings, in which case the name
   * renders as plain text with no affordance at all.
   */
  import { api } from "../api";
  import Icon from "./Icon.svelte";

  let { id, name, sub = "", size = "sm" } = $props<{
    id?: string | number;
    name: string;
    sub?: string;
    size?: "sm" | "md";
  }>();

  let open = $state(false);
  let loading = $state(false);
  let person = $state<any>(null);
  let avatarBroken = $state(false);
  let copied = $state(false);
  let anchor: HTMLElement | null = $state(null);
  let card: HTMLElement | null = $state(null);
  let pos = $state({ top: 0, left: 0 });

  /**
   * Place the card next to the name that opened it.
   *
   * Fixed positioning, measured from the trigger, because the card has to
   * escape whatever narrow scrolling column the name sits in. An ancestor with
   * a transform would capture a fixed element, so the card is rendered at the
   * end of <body> via the portal action below.
   */
  function place() {
    if (!anchor) return;
    const r = anchor.getBoundingClientRect();
    const w = card?.offsetWidth || 320;
    // The real height once it exists. Guessing 320 before the card rendered
    // was the bug: a name near the bottom "did not fit", flipped above, and
    // r.top minus a made up 320 clamped to the top of the window, which is how
    // a profile ended up in the opposite corner from the name it belongs to.
    const h = card?.offsetHeight || 0;

    let left = r.left;
    let top = r.bottom + 6;

    if (h) {
      const below = window.innerHeight - r.bottom - 6;
      const above = r.top - 6;
      // Only flip when there is genuinely more room above, and even then keep
      // it attached to the name rather than pinned to the top of the screen.
      if (below < h && above > below) top = Math.max(8, r.top - h - 6);
      // Still too tall for either side: sit as low as it can while staying on.
      if (top + h > window.innerHeight - 8) {
        top = Math.max(8, window.innerHeight - h - 8);
      }
    }

    if (left + w > window.innerWidth - 8) left = window.innerWidth - w - 8;
    if (left < 8) left = 8;

    // Idempotent: this runs from an effect after every render, and writing an
    // unchanged value would re-render and run it again, forever.
    if (pos.top !== top || pos.left !== left) pos = { top, left };
  }

  /**
   * Re-place once the card is real, and again when its contents change size.
   *
   * The first call happens before the card exists, so it can only guess. The
   * avatar loading and the facts arriving both change the height.
   */
  $effect(() => {
    if (!open || !card) return;
    void person;
    void loading;
    const id = requestAnimationFrame(place);
    return () => cancelAnimationFrame(id);
  });

  /** Render at the end of <body>, out of any transformed ancestor. */
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  async function show() {
    if (!id) return;
    if (open) {                 // a second click on the same name closes it
      open = false;
      return;
    }
    open = true;
    loading = true;
    avatarBroken = false;
    place();
    try {
      person = await api.person(String(id));
    } catch {
      person = { enabled: true, cached: false };
    } finally {
      loading = false;
    }
  }

  function when(ts?: number): string {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  }

  /**
   * Two different names, and the difference matters.
   *
   * `heading` is what Discord shows in the chat, which is what you recognise
   * someone by. `handle` is the @name, which is the one you actually type to
   * add them as a friend, so it is worth being able to copy.
   */
  const heading = $derived(
    person?.display_name || person?.username || name,
  );
  const handle = $derived(person?.username || "");

  async function copyHandle() {
    if (!handle) return;
    try {
      await navigator.clipboard.writeText(handle);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch {
      /* clipboard is blocked in some browsers, the text is still selectable */
    }
  }

  const factList = $derived(Object.entries(person?.facts ?? {}));
</script>

<svelte:window
  onkeydown={(e) => e.key === "Escape" && (open = false)}
  onresize={() => open && place()}
/>

{#if id}
  <button
    bind:this={anchor}
    onclick={show}
    title="See what is known about {name}"
    class="user-chip {size === 'md' ? 'text-sm' : 'text-[13px]'}"
  >{name}</button>
{:else}
  <span class={size === "md" ? "text-sm" : "text-[13px]"}>{name}</span>
{/if}

{#if open}
  <!-- Clicking anywhere else closes it, the way a Discord profile does, rather
       than a dialog with a close button you have to aim at. The backdrop is
       transparent and catches the click; the card sits above it. -->
  <div
    use:portal
    class="fixed inset-0 z-[60]"
    role="presentation"
    onclick={() => (open = false)}
    oncontextmenu={() => (open = false)}
  >
    <div
      bind:this={card}
      role="dialog"
      aria-label="About {heading}"
      tabindex="-1"
      onclick={(e) => e.stopPropagation()}
      class="user-card glass absolute w-[320px] max-w-[calc(100vw-16px)] overflow-y-auto rounded-xl p-4 shadow-2xl"
      style="top: {pos.top}px; left: {pos.left}px; max-height: min(70vh, 520px);"
    >
  {#if loading}
    <div class="space-y-2">
      <div class="h-16 animate-pulse rounded-lg bg-white/[0.04]"></div>
      <div class="h-24 animate-pulse rounded-lg bg-white/[0.03]"></div>
    </div>
  {:else if person?.enabled === false}
    <p class="text-[13px] text-muted">
      Profile cards are turned off. Settings, Appearance, Profile cards.
    </p>
  {:else}
    <div class="flex items-start gap-3">
      <!-- The avatar is a Discord CDN link cached when the bot last saw them.
           A link can rot, so a failed load falls back to the placeholder
           rather than leaving a broken image icon in the card. -->
      {#if person?.avatar && !avatarBroken}
        <img
          src={person.avatar}
          alt=""
          referrerpolicy="no-referrer"
          onerror={() => (avatarBroken = true)}
          class="h-14 w-14 shrink-0 rounded-full object-cover ring-1 ring-edge"
        />
      {:else}
        <span class="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-muted">
          <Icon name="accounts" size={22} />
        </span>
      {/if}
      <div class="min-w-0 flex-1">
        <div class="truncate text-[15px] font-semibold text-ink">{heading}</div>
        {#if handle}
          <button
            type="button"
            onclick={copyHandle}
            title="Copy the @name, this is what you search to add them"
            class="mt-0.5 flex max-w-full items-center gap-1.5 text-[12px] text-muted transition-colors hover:text-accent"
          >
            <span class="truncate">@{handle}</span>
            <span class="shrink-0 text-[10px] text-faint">{copied ? "copied" : "copy"}</span>
          </button>
        {/if}
        {#if sub}<div class="truncate text-[11px] text-faint">{sub}</div>{/if}
        <div class="mt-1 font-mono text-[10px] text-faint">{id}</div>
      </div>
    </div>

    {#if person?.bio}
      <div class="mt-4">
        <div class="mb-1 text-[10px] uppercase tracking-[0.12em] text-faint">About them</div>
        <p class="whitespace-pre-wrap text-[13px] leading-relaxed text-ink/90">{person.bio}</p>
      </div>
    {/if}

    {#if person?.messages}
      <div class="mt-4 grid grid-cols-3 gap-2 text-center">
        <div class="rounded-lg bg-white/5 py-2">
          <div class="text-sm font-semibold">{person.messages.toLocaleString()}</div>
          <div class="text-[10px] text-muted">messages</div>
        </div>
        <div class="rounded-lg bg-white/5 py-2">
          <div class="text-sm font-semibold">{person.messages_7d ?? 0}</div>
          <div class="text-[10px] text-muted">this week</div>
        </div>
        <div class="rounded-lg bg-white/5 py-2">
          <div class="text-sm font-semibold">{when(person.first_seen) || "?"}</div>
          <div class="text-[10px] text-muted">first seen</div>
        </div>
      </div>
    {/if}

    {#if factList.length}
      <div class="mt-4">
        <div class="mb-1.5 text-[10px] uppercase tracking-[0.12em] text-faint">Remembered</div>
        <div class="divide-y divide-edge/60">
          {#each factList as [k, v]}
            <div class="flex gap-3 py-1.5">
              <span class="w-28 shrink-0 font-mono text-[11px] text-faint">{k}</span>
              <span class="min-w-0 flex-1 break-words text-[13px] text-ink/90">{v}</span>
            </div>
          {/each}
        </div>
      </div>
    {/if}

    {#if person?.persona}
      <div class="mt-4">
        <div class="mb-1 text-[10px] uppercase tracking-[0.12em] text-faint">Persona for them</div>
        <p class="text-[13px] leading-relaxed text-ink/90">{person.persona}</p>
      </div>
    {/if}

    {#if !person?.cached && !factList.length && !person?.messages}
      <p class="mt-4 text-[13px] text-faint">
        Nothing stored about this person yet. Details appear once the bot has
        spoken with them.
      </p>
    {/if}
  {/if}
    </div>
  </div>
{/if}
