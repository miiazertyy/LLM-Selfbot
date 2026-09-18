<script lang="ts">
  /**
   * Editor for a numbered key family, GROQ_API_KEY_1, _2, _3 and so on.
   *
   * The generic variable list below can only show the handful of numbered
   * slots the template happens to document, which made it look as though one
   * key was the limit. There is no limit: add as many as you like and the bot
   * falls through them in order as each hits its rate limit.
   *
   * Values are write-only, like account tokens: a key is shown masked and can
   * be replaced but not read back.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import { toast } from "../stores";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";

  let { name, hint = "" } = $props<{ name: string; hint?: string }>();

  type Extra = { prefix: string; label: string; secret: boolean; placeholder?: string };
  type Key = {
    index: number;
    preview: string;
    set: boolean;
    extras: Record<string, { preview: string; set: boolean }>;
  };

  let keys = $state<Key[]>([]);
  let label = $state("key");
  let secret = $state(true);
  /** Fields that belong to the same slot: a token's proxy, a login's password. */
  let extras = $state<Extra[]>([]);
  let loading = $state(true);
  let adding = $state("");
  let addingExtras = $state<Record<string, string>>({});
  let editing = $state<Record<number, string>>({});
  let editingExtras = $state<Record<string, string>>({});
  let busy = $state(false);

  const extraKey = (i: number, prefix: string) => `${i}:${prefix}`;

  onMount(load);

  async function load() {
    try {
      const r = await api.keyList(name);
      keys = r.keys || [];
      label = r.label || "key";
      secret = r.secret !== false;
      extras = r.extras || [];
    } catch (e: any) {
      toast(e.message || "Could not load keys", "err");
    } finally {
      loading = false;
    }
  }

  async function run(fn: () => Promise<any>, ok: string) {
    busy = true;
    try {
      keys = (await fn()).keys || keys;
      toast(ok, "ok");
    } catch (e: any) {
      toast(e.message || "That did not work", "err");
    } finally {
      busy = false;
    }
  }

  async function add() {
    const v = adding.trim();
    if (!v) return;
    const body: Record<string, string> = {};
    for (const e of extras) {
      const val = (addingExtras[e.prefix] || "").trim();
      if (val) body[e.prefix] = val;
    }
    await run(() => api.addKey(name, v, body), `${label} added.`);
    adding = "";
    addingExtras = {};
  }

  async function replace(index: number) {
    const v = (editing[index] || "").trim();
    const body: Record<string, string> = {};
    let touched = false;
    for (const e of extras) {
      const k = extraKey(index, e.prefix);
      if (k in editingExtras) {
        body[e.prefix] = (editingExtras[k] || "").trim();
        touched = true;
      }
    }
    // Replacing only the proxy should not require retyping the token, so the
    // stored value is reused when the main box is left alone.
    if (!v && !touched) return;
    await run(
      () => api.replaceKey(name, index, v, body, !v),
      `${label} ${index} updated.`,
    );
    delete editing[index];
    for (const e of extras) delete editingExtras[extraKey(index, e.prefix)];
  }
</script>

<section>
  <h3 class="mb-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
    {label}s
  </h3>
  {#if hint}
    <p class="mb-2 text-[11px] leading-relaxed text-faint">{hint}</p>
  {/if}

  {#if loading}
    <div class="h-11 animate-pulse rounded-lg bg-white/[0.03]"></div>
  {:else}
    <div class="divide-y divide-edge/60">
      {#each keys as k (k.index)}
        <div class="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:gap-3">
          <span class="shrink-0 font-mono text-[12px] text-muted">#{k.index}</span>
          <input
            value={editing[k.index] ?? ""}
            placeholder={k.preview || "set"}
            spellcheck="false"
            autocomplete="off"
            oninput={(e) => (editing[k.index] = (e.target as HTMLInputElement).value)}
            class="field min-w-0 flex-1 font-mono text-[12px]"
          />
          <div class="flex shrink-0 gap-2">
            <Button size="sm" kind="ghost" disabled={busy}
                    onclick={() => replace(k.index)}>
              Save
            </Button>
            <button
              onclick={() => run(() => api.deleteKey(name, k.index), `${label} ${k.index} removed.`)}
              title="Remove this {label.toLowerCase()}"
              aria-label="Remove {label} {k.index}"
              class="jelly rounded-lg p-1.5 text-faint hover:bg-bad/15 hover:text-bad"
            >
              <Icon name="close" size={13} />
            </button>
          </div>
        </div>
        {#if extras.length}
          <!-- Fields belonging to the same account. They are renumbered with
               it, so removing an account never leaves its password behind on
               somebody else's. -->
          <div class="flex flex-col gap-2 pb-3 pl-0 sm:pl-8">
            {#each extras as e (e.prefix)}
              <label class="flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-3">
                <span class="w-20 shrink-0 text-[11px] text-faint">{e.label}</span>
                <input
                  value={editingExtras[extraKey(k.index, e.prefix)] ?? ""}
                  placeholder={k.extras?.[e.prefix]?.preview || e.placeholder || "not set"}
                  spellcheck="false"
                  autocomplete="off"
                  oninput={(ev) =>
                    (editingExtras[extraKey(k.index, e.prefix)] =
                      (ev.target as HTMLInputElement).value)}
                  class="field min-w-0 flex-1 font-mono text-[11px]"
                />
              </label>
            {/each}
          </div>
        {/if}
      {:else}
        <p class="py-3 text-[12px] text-faint">None yet, add one below.</p>
      {/each}
    </div>

    <div class="mt-3 flex flex-col gap-2 sm:flex-row">
      <!-- The icon says what kind of thing the box wants, so the placeholder
           does not have to narrate the action as well: "Groq API key", not
           "Paste another groq api key". -->
      <label class="relative min-w-0 flex-1">
        <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
          <Icon name="key" size={14} />
        </span>
        <input
          bind:value={adding}
          placeholder={label}
          spellcheck="false"
          autocomplete="off"
          class="field w-full pl-8 font-mono text-[12px]"
        />
      </label>
      <Button size="sm" onclick={add} disabled={!adding.trim() || busy}>Add</Button>
    </div>
    {#if extras.length}
      <div class="mt-2 flex flex-col gap-2 sm:pl-0">
        {#each extras as e (e.prefix)}
          <label class="flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-3">
            <span class="w-20 shrink-0 text-[11px] text-faint">{e.label}</span>
            <span class="relative min-w-0 flex-1">
              <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
                <Icon name={e.secret ? "key" : "accounts"} size={13} />
              </span>
              <input
                bind:value={addingExtras[e.prefix]}
                placeholder={e.placeholder || e.label}
                spellcheck="false"
                autocomplete="off"
                class="field w-full pl-8 font-mono text-[11px]"
              />
            </span>
          </label>
        {/each}
      </div>
    {/if}
    <p class="mt-2 text-[11px] text-faint">
      Stored as numbered entries and always renumbered to stay consecutive,
      because the loader stops at the first gap. Each one gets its own IPC
      channel, so they run as separate accounts.
    </p>
  {/if}
</section>
