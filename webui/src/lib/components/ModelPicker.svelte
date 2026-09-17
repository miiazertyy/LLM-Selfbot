<script lang="ts">
  /**
   * Choosing a Groq model from what Groq actually has.
   *
   * Model ids were typed by hand into a text box, which meant a typo failed
   * silently and a retirement failed loudly months later. Groq publishes the
   * live list, so this offers it: pick from a menu, or type a name anyway for
   * something the list has not caught up with.
   *
   * Two shapes, because the config has two: a single model (the image model)
   * and an ordered list the bot falls through when one is rate limited.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import Icon from "./Icon.svelte";

  let { value, multiple = false, need = "chat", onchange } = $props<{
    value: string | string[];
    multiple?: boolean;
    /** What this setting needs the model to do: chat, vision, stt or tts. */
    need?: string;
    onchange: (v: any) => void;
  }>();

  const NEED_LABEL: Record<string, string> = {
    chat: "write replies",
    vision: "read images",
    stt: "transcribe speech",
    tts: "speak out loud",
  };

  type Model = {
    id: string;
    kind: string;
    owned_by?: string;
    context_window?: number;
    max_completion_tokens?: number;
    capabilities?: string[];
    active: boolean;
  };

  let models = $state<Model[]>([]);
  let error = $state("");
  let loading = $state(true);
  let open = $state(false);
  let custom = $state("");

  const chosen = $derived(
    multiple ? ((value as string[]) ?? []) : [String(value ?? "")].filter(Boolean),
  );

  /** Anything selected that Groq no longer lists is the interesting case. */
  const unknown = $derived(
    models.length ? chosen.filter((id) => !models.some((m) => m.id === id)) : [],
  );

  /**
   * Only the models that can do this particular job.
   *
   * Every model used to be offered for every setting, so a speech model could
   * be picked to write replies and a text model to read images. Both fail on
   * every single request, with an error that never says the model was simply
   * the wrong sort.
   */
  const offerable = $derived(
    models.filter((m) => (m.capabilities ?? ["chat"]).includes(need)),
  );

  /** Chosen models that cannot do what this setting needs. */
  const wrongKind = $derived(
    models.length
      ? chosen.filter((id) => {
          const m = models.find((x) => x.id === id);
          return m && !(m.capabilities ?? ["chat"]).includes(need);
        })
      : [],
  );

  onMount(load);

  async function load(refresh = false) {
    loading = true;
    try {
      const data = await api.models(refresh);
      models = data.models || [];
      error = data.error || "";
    } catch (e: any) {
      error = e?.message || "Could not reach Groq";
    } finally {
      loading = false;
    }
  }

  function pick(id: string) {
    if (!multiple) {
      onchange(id);
      open = false;
      return;
    }
    const list = [...chosen];
    const at = list.indexOf(id);
    if (at >= 0) list.splice(at, 1);
    else list.push(id);
    onchange(list);
  }

  /**
   * Reordering by dragging the handle.
   *
   * Order matters here: the bot walks the list top down and moves to the next
   * model when one is rate limited. Two buttons per row was a lot of clicking
   * to express "this one first", and a lot of chrome on every row.
   */
  let dragging = $state<string | null>(null);
  let over = $state<string | null>(null);

  function drop(target: string) {
    const from = dragging;
    dragging = null;
    over = null;
    if (!from || from === target) return;
    const list = chosen.filter((m) => m !== from);
    list.splice(list.indexOf(target), 0, from);
    onchange(list);
  }

  /** Keyboard equivalent, so the order is not mouse-only. */
  function nudge(id: string, delta: number) {
    const list = [...chosen];
    const i = list.indexOf(id);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    onchange(list);
  }

  function addCustom() {
    const id = custom.trim();
    if (!id) return;
    custom = "";
    if (multiple) {
      if (!chosen.includes(id)) onchange([...chosen, id]);
    } else {
      onchange(id);
      open = false;
    }
  }

  function ctx(m: Model): string {
    if (!m.context_window) return "";
    return m.context_window >= 1000
      ? `${Math.round(m.context_window / 1000)}k context`
      : `${m.context_window} context`;
  }

  function dismiss(e: MouseEvent) {
    if (!open) return;
    if (!(e.target as HTMLElement).closest?.("[data-model-picker]")) open = false;
  }
</script>

<svelte:window onclick={dismiss} onkeydown={(e) => e.key === "Escape" && (open = false)} />

<div class="relative w-full sm:w-72" data-model-picker>
  <!-- ── What is chosen ─────────────────────────────────────────────────── -->
  {#if multiple}
    <div class="mb-1.5 space-y-1">
      {#each chosen as id, i (id)}
        <div
          draggable="true"
          role="listitem"
          ondragstart={() => (dragging = id)}
          ondragend={() => { dragging = null; over = null; }}
          ondragover={(e) => { if (dragging) { e.preventDefault(); over = id; } }}
          ondrop={(e) => { e.preventDefault(); drop(id); }}
          class="group flex items-center gap-1.5 rounded-lg border px-1.5 py-1 transition-colors
            {dragging === id ? 'opacity-40' : ''}
            {over === id && dragging !== id ? 'border-accent bg-accent/[0.06]' : 'border-transparent bg-white/[0.05]'}"
        >
          <span
            class="shrink-0 cursor-grab text-faint transition-colors hover:text-ink active:cursor-grabbing"
            title="Drag to reorder"
            aria-hidden="true"
          ><Icon name="grip" size={13} /></span>
          <span class="w-3 shrink-0 text-[10px] text-faint">{i + 1}</span>
          <span class="min-w-0 flex-1 truncate font-mono text-[11px] text-ink" title={id}>{id}</span>
          {#if unknown.includes(id)}
            <span class="shrink-0 text-[10px] text-warn" title="Groq no longer lists this">gone</span>
          {/if}
          <!-- Keyboard reordering, revealed on focus so the row stays clean. -->
          <button class="shrink-0 px-1 text-[10px] text-faint opacity-0 focus:opacity-100 hover:text-ink group-hover:opacity-100"
                  onclick={() => nudge(id, -1)} aria-label="Move {id} up">&uarr;</button>
          <button class="shrink-0 px-1 text-[10px] text-faint opacity-0 focus:opacity-100 hover:text-ink group-hover:opacity-100"
                  onclick={() => nudge(id, 1)} aria-label="Move {id} down">&darr;</button>
          <button class="shrink-0 px-1 text-[11px] text-faint hover:text-bad"
                  onclick={() => pick(id)} aria-label="Remove {id}">&times;</button>
        </div>
      {:else}
        <p class="text-[11px] text-warn">No model chosen, so nothing can reply.</p>
      {/each}
    </div>
  {/if}

  <button
    type="button"
    onclick={() => (open = !open)}
    aria-haspopup="listbox"
    aria-expanded={open}
    class="flex w-full items-center gap-2 rounded-lg border border-edge bg-surface px-2.5 py-1.5
      text-left transition-colors hover:border-accent/40 {open ? 'border-accent/50' : ''}"
  >
    <span class="min-w-0 flex-1 truncate font-mono text-[12px] {multiple ? 'text-muted' : 'text-ink'}">
      {multiple ? "Add a model" : chosen[0] || "Pick a model"}
    </span>
    {#if !multiple && unknown.length}
      <span class="shrink-0 text-[10px] text-warn">not available</span>
    {/if}
    <span class="shrink-0 text-faint transition-transform duration-200"
          style="transform: rotate({open ? 180 : 0}deg)">
      <svg width="11" height="11" viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <path d="M2.5 4.5 6 8l3.5-3.5" stroke="currentColor" stroke-width="1.4"
              stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </span>
  </button>

  <!-- ── The live list ──────────────────────────────────────────────────── -->
  {#if open}
    <div
      role="listbox"
      class="glass floating absolute right-0 z-40 mt-1 max-h-80 w-full min-w-[260px] overflow-y-auto rounded-xl p-1 shadow-xl"
    >
      {#if loading}
        <div class="space-y-1 p-1">
          {#each Array(4) as _}<div class="h-8 animate-pulse rounded-lg bg-white/[0.04]"></div>{/each}
        </div>
      {:else}
        {#if error}
          <p class="px-2 py-2 text-[11px] leading-relaxed text-warn">{error}</p>
        {/if}
        {#if !offerable.length && !error}
          <p class="px-2 py-2 text-[11px] leading-relaxed text-warn">
            None of the models on your account can {NEED_LABEL[need] ?? need}.
          </p>
        {/if}
        {#each offerable as m (m.id)}
          <button
            role="option"
            aria-selected={chosen.includes(m.id)}
            onclick={() => pick(m.id)}
            class="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors
              {chosen.includes(m.id) ? 'bg-accent/10' : 'hover:bg-white/[0.05]'}"
          >
            <span class="min-w-0 flex-1">
              <span class="block truncate font-mono text-[11.5px] text-ink">{m.id}</span>
              <span class="block truncate text-[10px] text-faint">
                {m.owned_by || ""}{m.owned_by && ctx(m) ? " · " : ""}{ctx(m)}
                {#if (m.capabilities ?? []).includes("vision") && need !== "vision"}
                  · reads images
                {/if}
                {#if !m.active} · retired{/if}
              </span>
            </span>
            {#if chosen.includes(m.id)}
              <span class="shrink-0 text-accent"><Icon name="check" size={13} /></span>
            {/if}
          </button>
        {/each}

        <!-- An escape hatch: a model can exist before it reaches this list. -->
        <div class="mt-1 flex items-center gap-1 border-t border-edge/60 p-1 pt-2">
          <input
            bind:value={custom}
            onkeydown={(e) => e.key === "Enter" && addCustom()}
            placeholder="or type a name"
            class="min-w-0 flex-1 rounded-md border border-edge bg-surface px-2 py-1 font-mono text-[11px] outline-none focus:border-accent/50"
          />
          <button class="shrink-0 px-1.5 py-1 text-[11px] text-faint hover:text-accent"
                  onclick={() => load(true)} title="Ask Groq again">refresh</button>
        </div>
      {/if}
    </div>
  {/if}

  {#if unknown.length && !open}
    <p class="mt-1 text-[10px] leading-relaxed text-warn">
      {unknown.join(", ")} {unknown.length === 1 ? "is" : "are"} not on Groq's list.
      Requests using {unknown.length === 1 ? "it" : "them"} will fail.
    </p>
  {/if}
  {#if wrongKind.length && !open}
    <p class="mt-1 text-[10px] leading-relaxed text-warn">
      {wrongKind.join(", ")} cannot {NEED_LABEL[need] ?? need}. Pick one that can.
    </p>
  {/if}
</div>
