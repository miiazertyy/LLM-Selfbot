<script lang="ts" module>
  /**
   * Summaries already fetched this session, by person. Going back to someone
   * you just looked at paints their summary at once; the server keeps them too,
   * but that is still a round trip.
   */
  const seen = new Map<string, Summary>();

  type Summary = {
    ok: boolean;
    enabled?: boolean;
    summary?: string;
    generated_at?: number;
    count?: number;
    source?: string;
    cached?: boolean;
    stale?: boolean;
    reason?: string;
  };
</script>

<script lang="ts">
  /**
   * What you and this person have been talking about.
   *
   * Written from their last few messages the first time you open them, then
   * kept, so it is only rewritten when it is older than the setting says or
   * when you ask. The model call takes a few seconds, which is why there is a
   * proper loading state rather than an empty box.
   */
  import { api } from "../api";
  import { track } from "../busy";
  import Icon from "./Icon.svelte";
  import SummaryText from "./SummaryText.svelte";

  /** `persona`: whose summary ("" for Default's, or the newest any persona has where only one is read). */
  let { uid, name = "", persona = "" }: { uid: string; name?: string; persona?: string } = $props();

  let data = $state<Summary | null>(null);
  let loading = $state(false);
  let error = $state("");
  /** The request that is allowed to land. Anything older is for someone else. */
  let ticket = 0;

  async function load(force = false) {
    const mine = ++ticket;
    const who = uid;
    const as = persona;
    // Each persona has its own summary of someone: it remembers its own talks with them.
    const key = `${as}|${who}`;
    error = "";
    const held = seen.get(key);
    if (held && !force) data = held;
    loading = !held || force;
    try {
      // Writing one takes seconds; leaving Memory meanwhile is the normal case.
      const r: Summary = await track("memory", api.memorySummary(who, force, false, as),
                                     `Summary for ${name || "someone"}`);
      if (mine !== ticket) return;          // clicked someone else meanwhile
      if (r.ok) seen.set(key, r);
      data = r;
      if (!r.ok && r.enabled !== false) error = r.reason || "Could not write a summary.";
    } catch (e: any) {
      if (mine !== ticket) return;
      error = e?.message || "Could not write a summary.";
    } finally {
      if (mine === ticket) loading = false;
    }
  }

  // A different person (or persona): start over, but show what is already known for them.
  $effect(() => {
    const key = `${persona}|${uid}`;
    data = seen.get(key) ?? null;
    void load(false);
  });

  function ago(ts?: number) {
    if (!ts) return "";
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 86400) return `${Math.round(s / 3600)} h ago`;
    return `${Math.round(s / 86400)} d ago`;
  }
</script>

{#if data?.enabled === false}
  <!-- Turned off in Settings: take up no room at all. -->
{:else}
  <div class="glass summary-card relative overflow-hidden rounded-2xl p-4">
    <div class="mb-2.5 flex items-center gap-2">
      <span class="flex h-6 w-6 items-center justify-center rounded-lg bg-accent/15 text-accent">
        <Icon name="sparkle" size={13} />
      </span>
      <h3 class="text-[13px] font-semibold text-ink">
        What you've been talking about
      </h3>
      <button
        class="jelly ml-auto flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] text-muted
               hover:bg-white/[0.06] hover:text-ink disabled:opacity-40"
        onclick={() => load(true)}
        disabled={loading}
        title="Write it again from the latest messages"
      >
        <span class:spin={loading}><Icon name="refresh" size={12} /></span>
        {loading && data?.summary ? "Rewriting" : "Rewrite"}
      </button>
    </div>

    {#if loading && !data?.summary}
      <!-- First time for this person: the model is reading. -->
      <div class="space-y-2" aria-live="polite">
        <div class="shimmer h-3 w-[92%] rounded"></div>
        <div class="shimmer h-3 w-[86%] rounded"></div>
        <div class="shimmer h-3 w-[70%] rounded"></div>
        <p class="pt-1 text-[11px] text-faint">
          Reading your last messages with {name || "them"}…
        </p>
      </div>
    {:else if data?.summary}
      <div class="transition-opacity {loading ? 'opacity-50' : ''}">
        <!-- Typed in as it arrives, a caret ahead and soft keys heard (lib/typewrite.ts); again when rewritten. -->
        {#key data.summary}<SummaryText text={data.summary} type />{/key}
      </div>
      <p class="mt-2.5 text-[11px] text-faint">
        From the last {data.count} message{data.count === 1 ? "" : "s"}
        {#if data.source === "recent"}· what this session has seen{/if}
        · {ago(data.generated_at)}
        {#if data.stale}
          <span class="text-warn">· could not refresh it: {data.reason}</span>
        {/if}
      </p>
    {:else if error}
      <div class="flex items-start gap-2 text-[12px] text-muted">
        <span class="mt-0.5 text-warn"><Icon name="alert" size={13} /></span>
        <span class="min-w-0 flex-1">{error}</span>
        <button class="shrink-0 text-accent hover:underline" onclick={() => load(true)}>Try again</button>
      </div>
    {/if}
  </div>
{/if}

<style>
  .shimmer {
    background: linear-gradient(
      90deg,
      color-mix(in srgb, var(--color-ink) 6%, transparent) 0%,
      color-mix(in srgb, var(--color-ink) 13%, transparent) 50%,
      color-mix(in srgb, var(--color-ink) 6%, transparent) 100%
    );
    background-size: 200% 100%;
    animation: summary-shimmer 1.3s ease-in-out infinite;
  }
  @keyframes summary-shimmer {
    from { background-position: 100% 0; }
    to { background-position: -100% 0; }
  }
  .spin {
    display: inline-flex;
    animation: summary-spin 0.9s linear infinite;
  }
  @keyframes summary-spin {
    to { transform: rotate(360deg); }
  }
  .summary-card {
    animation: summary-in 0.32s var(--spring, ease-out) both;
  }
  @keyframes summary-in {
    from { opacity: 0; transform: translate3d(0, 6px, 0); }
    to { opacity: 1; transform: none; }
  }
  /* The app's Motion switch, not Windows' animation effects (see stores.ts). */
  :global(:root[data-motion="off"]) .shimmer,
  :global(:root[data-motion="off"]) .spin,
  :global(:root[data-motion="off"]) .summary-card { animation: none; }
</style>
