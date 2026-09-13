<script lang="ts">
  /**
   * Editor for every value in config/.env.
   *
   * The list merges what is actually set with everything the template
   * documents, so options you have never used are still discoverable - each
   * one carrying the explanation from resources/example.env.
   *
   * Secrets arrive masked. Leaving a masked value alone sends nothing for that
   * key, so it cannot be clobbered; typing over it replaces it.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import { toast } from "../stores";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import KeyList from "./KeyList.svelte";

  /**
   * Settings shows this editor once per subtab, each time narrowed to the one
   * subject that tab is about: the Discord tab shows tokens and proxies, the
   * Groq tab shows API keys. One long list of every variable is still reachable
   * under App, so nothing is unreachable.
   */
  let {
    sections = null,
    keyLists = ["discord", "groq", "snapchat"],
    extras = true,
  }: {
    sections?: string[] | null;
    keyLists?: string[];
    extras?: boolean;
  } = $props();

  type Var = {
    key: string;
    value: string;
    secret: boolean;
    set: boolean;
    managed: boolean;
    help: string;
    example: string;
    section: string;
  };

  let vars = $state<Var[]>([]);
  let edits = $state<Record<string, string>>({});
  let loading = $state(true);
  let saving = $state(false);
  let loadError = $state("");
  let query = $state("");
  let showUnset = $state(false);

  let newKey = $state("");
  let newValue = $state("");

  const changed = $derived(Object.keys(edits).length);

  // Owned by the dedicated key editor above; listing them twice would let one
  // copy overwrite the other's edits.
  const OWNED = /^GROQ_API_KEY(_\d+)?$/;

  const filtered = $derived.by(() => {
    const q = query.trim().toLowerCase();
    return vars.filter((v) => {
      if (OWNED.test(v.key)) return false;
      if (sections && !sections.includes(v.section)) return false;
      if (!showUnset && !v.set && !(v.key in edits) && !q) return false;
      if (!q) return true;
      return v.key.toLowerCase().includes(q) || v.help.toLowerCase().includes(q);
    });
  });

  const grouped = $derived.by(() => {
    const out: Record<string, Var[]> = {};
    for (const v of filtered) (out[v.section] ||= []).push(v);
    return Object.entries(out);
  });

  const unsetCount = $derived(
    vars.filter(
      (v) => !v.set && !OWNED.test(v.key) && (!sections || sections.includes(v.section)),
    ).length,
  );

  onMount(load);

  async function load() {
    try {
      vars = (await api.env()).vars || [];
      edits = {};
    } catch (e: any) {
      loadError = e?.message || "Could not load";
    } finally {
      loading = false;
    }
  }

  const valueOf = (v: Var) => (v.key in edits ? edits[v.key] : v.value);

  async function save() {
    saving = true;
    try {
      const res = await api.saveEnv(edits);
      vars = res.vars || vars;
      edits = {};
      toast("Environment saved, restart accounts to apply.", "ok");
    } catch (e: any) {
      toast(e.message || "Could not save", "err");
    } finally {
      saving = false;
    }
  }

  async function remove(v: Var) {
    try {
      const res = await api.saveEnv({}, [v.key]);
      vars = res.vars || vars;
      delete edits[v.key];
      toast(`${v.key} removed.`, "ok");
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  async function addVar() {
    const key = newKey.trim().toUpperCase();
    if (!key) return;
    if (!/^[A-Z_][A-Z0-9_]*$/.test(key)) {
      toast("Names may only use letters, digits and underscores.", "err");
      return;
    }
    try {
      const res = await api.saveEnv({ [key]: newValue });
      vars = res.vars || vars;
      newKey = newValue = "";
      toast(`${key} added.`, "ok");
    } catch (e: any) {
      toast(e.message, "err");
    }
  }
</script>

{#if loadError}
  <p class="text-[13px] text-bad">{loadError}</p>
{:else if loading}
  <div class="space-y-2">
    {#each Array(5) as _}<div class="h-11 animate-pulse rounded-lg bg-white/[0.03]"></div>{/each}
  </div>
{:else}
  <div class="mb-4 flex flex-wrap items-center gap-2">
    <label class="relative min-w-0 flex-1">
      <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
        <Icon name="search" size={14} />
      </span>
      <input bind:value={query} placeholder="Search variables…" class="field pl-8" />
    </label>
    <Button size="sm" onclick={save} loading={saving} disabled={!changed}>
      Save
    </Button>
  </div>

  <!-- The numbered key families get a dedicated editor. In the generic list
       below they appear as whatever slots the template documents, which made
       it look like one Groq key was the maximum. -->
  <div class="mb-7 space-y-7">
    {#if keyLists.includes("discord")}
      <KeyList
        name="discord"
        hint="Each token is a separate account with its own memory, settings and proxy. Add as many as you want to run at once."
      />
    {/if}
    {#if keyLists.includes("groq")}
      <KeyList
        name="groq"
        hint="Add as many as you like. When one hits its rate limit the bot falls through to the next, and once all are exhausted it moves to the next model in config.yaml."
      />
    {/if}
    {#if keyLists.includes("snapchat")}
      <KeyList
        name="snapchat"
        hint="Each login gets its own browser and cookies. Snapchat has to be installed first, under Snapchat, Install."
      />
    {/if}
  </div>

  {#if unsetCount}
    <label class="mb-4 flex cursor-pointer items-center gap-2 text-[12px] text-muted">
      <input type="checkbox" bind:checked={showUnset} class="accent-[#7c8cff]" />
      Show the {unsetCount} option{unsetCount === 1 ? "" : "s"} that aren't set yet
    </label>
  {/if}

  <div class="space-y-7">
    {#each grouped as [section, list]}
      <section>
        {#if !sections || sections.length > 1}
          <h3 class="mb-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">{section}</h3>
        {/if}
        <div class="divide-y divide-edge/60">
          {#each list as v (v.key)}
            <div class="py-3">
              <div class="flex flex-col gap-2 sm:flex-row sm:items-start sm:gap-4">
                <div class="min-w-0 sm:flex-1">
                  <div class="flex flex-wrap items-center gap-1.5">
                    <span class="break-all font-mono text-[12px] text-ink">{v.key}</span>
                    {#if v.key in edits}
                      <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" title="unsaved"></span>
                    {/if}
                    {#if !v.set && !(v.key in edits)}
                      <span class="rounded bg-white/[0.06] px-1 text-[9px] uppercase tracking-wide text-faint">unset</span>
                    {/if}
                    {#if v.managed}
                      <span class="rounded bg-accent/15 px-1 text-[9px] uppercase tracking-wide text-accent"
                            title="Also editable on the Accounts page">account</span>
                    {/if}
                  </div>
                  {#if v.help}
                    <p class="mt-0.5 text-[11px] leading-relaxed text-faint">{v.help}</p>
                  {/if}
                </div>

                <div class="flex items-center gap-2 sm:w-64 sm:shrink-0">
                  <input
                    type="text"
                    value={valueOf(v)}
                    placeholder={v.example || (v.secret ? "not set" : "")}
                    spellcheck="false"
                    oninput={(e) => (edits[v.key] = (e.target as HTMLInputElement).value)}
                    class="field font-mono text-[12px]"
                  />
                  {#if v.set}
                    <button
                      onclick={() => remove(v)}
                      title="Remove this variable"
                      aria-label="Remove {v.key}"
                      class="jelly shrink-0 rounded-lg p-1.5 text-faint hover:bg-bad/15 hover:text-bad"
                    >
                      <Icon name="close" size={13} />
                    </button>
                  {/if}
                </div>
              </div>
            </div>
          {/each}
        </div>
      </section>
    {:else}
      <p class="py-6 text-center text-[13px] text-faint">Nothing matches.</p>
    {/each}
  </div>

  <!-- Anything the template doesn't know about can still be added by hand. -->
  {#if extras}
  <div class="mt-8 border-t border-edge/60 pt-4">
    <h3 class="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">Add a variable</h3>
    <div class="flex flex-col gap-2 sm:flex-row">
      <input bind:value={newKey} placeholder="MY_VARIABLE" spellcheck="false"
             class="field font-mono uppercase sm:w-56" />
      <input bind:value={newValue} placeholder="value" spellcheck="false" class="field font-mono" />
      <Button size="sm" onclick={addVar} disabled={!newKey.trim()}>Add</Button>
    </div>
  </div>
  {/if}

  <p class="mt-4 text-[11px] text-faint">
    Stored in config/.env on this machine. Most values are read when an account
    starts, so restart the affected account after changing one.
  </p>
{/if}
