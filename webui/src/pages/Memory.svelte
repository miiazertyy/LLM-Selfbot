<script lang="ts">
  /**
   * What the bot has learned about people, and a way to correct it.
   *
   * The list is the important half: it is how you find the person you meant.
   * It sorts by who spoke most recently, is searchable, and each row says
   * enough to recognise someone without opening them.
   */
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { toast } from "../lib/stores";
  import { resource } from "../lib/resource";
  import Card from "../lib/components/Card.svelte";
  import Badge from "../lib/components/Badge.svelte";
  import Button from "../lib/components/Button.svelte";
  import Empty from "../lib/components/Empty.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import UserChip from "../lib/components/UserChip.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";

  type MemUser = {
    user_id: string;
    username: string;
    display_name?: string;
    facts: Record<string, string>;
    persona?: string;
    messages?: number;
    first_seen?: number;
    last_seen?: number;
    fact_count?: number;
    avatar?: string;
  };
  type MemDetail = { facts: Record<string, string>; persona: string | null };

  // Held outside the component, so leaving the tab and coming back shows what
  // was there instead of a skeleton and a fresh round trip.
  const people = resource("memory", () => api.memory(), { users: [] as MemUser[] });

  const users = $derived($people.data.users ?? []);
  const loading = $derived(!$people.fetched && $people.loading);
  const refreshing = $derived($people.refreshing);

  let selected = $state<string | null>(null);
  let detail = $state<MemDetail | null>(null);
  let loadError = $derived($people.error);
  let query = $state("");
  /** Drives the filter one beat behind the input, so typing does not re-scan
      every user and every fact on each keystroke. */
  let queryDebounced = $state("");
  $effect(() => {
    const v = query;
    const t = setTimeout(() => { queryDebounced = v; }, 120);
    return () => clearTimeout(t);
  });
  let newKey = $state("");
  let newValue = $state("");
  let persona = $state("");
  let saving = $state(false);
  let editing = $state<string | null>(null);
  let editValue = $state("");

  const current = $derived(users.find((u) => u.user_id === selected) ?? null);

  const shown = $derived.by(() => {
    const q = queryDebounced.trim().toLowerCase();
    if (!q) return users;
    return users.filter(
      (u) =>
        (u.username || "").toLowerCase().includes(q) ||
        (u.display_name || "").toLowerCase().includes(q) ||
        u.user_id.includes(q) ||
        Object.entries(u.facts).some(
          ([k, v]) => k.toLowerCase().includes(q) || String(v).toLowerCase().includes(q),
        ),
    );
  });

  const totals = $derived.by(() => ({
    people: users.length,
    facts: users.reduce((n, u) => n + (u.fact_count ?? 0), 0),
    personas: users.filter((u) => u.persona).length,
  }));

  const personaDirty = $derived((detail?.persona || "") !== persona);

  // Stale-while-revalidate: what is cached is already on screen, and this only
  // goes back to the server when that answer has aged out.
  onMount(() => people.refresh({ maxAge: 10000 }));

  const load = () => people.refresh({ force: true });

  async function open(uid: string) {
    selected = uid;
    editing = null;
    try {
      detail = await api.memoryUser(uid);
      persona = detail.persona || "";
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  async function put(body: any) {
    if (!selected) return;
    saving = true;
    try {
      await api.memoryPut(selected, body);
      await open(selected);
      await load();
    } catch (e: any) {
      toast(e.message, "err");
    }
    saving = false;
  }

  async function addFact() {
    if (!selected || !newKey.trim()) return;
    await put({ key: newKey.trim(), value: newValue });
    newKey = "";
    newValue = "";
    toast("Saved", "ok");
  }

  function startEdit(key: string, value: string) {
    editing = key;
    editValue = value;
  }

  async function commitEdit() {
    if (!editing) return;
    const key = editing;
    editing = null;
    await put({ key, value: editValue });
  }

  async function deleteFact(key: string) {
    if (!selected) return;
    try {
      await api.memoryDelete(selected, { key });
      await open(selected);
      await load();
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  async function forgetAll() {
    if (!selected || !current) return;
    const who = current.display_name || current.username || selected;
    if (!confirm(`Forget everything about ${who}? This cannot be undone.`)) return;
    try {
      await api.memoryDelete(selected, {});
      toast("Forgotten", "ok");
      selected = null;
      detail = null;
      await load();
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  function ago(ts?: number): string {
    if (!ts) return "never";
    const mins = Math.floor((Date.now() / 1000 - ts) / 60);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    if (days < 30) return `${days}d ago`;
    return new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }
</script>

<ErrorNote text={loadError} onretry={load} />

{#if loading}
  <div class="glass h-64 animate-pulse"></div>
{:else}
  <!-- ── What is in here at a glance ─────────────────────────────────────── -->
  <!-- Two columns on a phone: "Personas" plus its tracking does not fit a
       third of 320px, and the label was being clipped. -->
  <div class="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
    <div class="glass rounded-xl px-3 py-3 sm:px-4">
      <div class="text-[10px] uppercase tracking-[0.12em] text-faint">People</div>
      <div class="mt-0.5 text-xl font-semibold text-ink">{totals.people}</div>
    </div>
    <div class="glass rounded-xl px-3 py-3 sm:px-4">
      <div class="text-[10px] uppercase tracking-[0.12em] text-faint">Facts</div>
      <div class="mt-0.5 text-xl font-semibold text-ink">{totals.facts}</div>
    </div>
    <div class="glass col-span-2 rounded-xl px-3 py-3 sm:col-span-1 sm:px-4">
      <div class="text-[10px] uppercase tracking-[0.12em] text-faint">Personas</div>
      <div class="mt-0.5 text-xl font-semibold text-ink">{totals.personas}</div>
    </div>
  </div>

  <div class="grid grid-cols-1 gap-4 lg:grid-cols-5">
    <!-- ── Who the bot knows ─────────────────────────────────────────────── -->
    <div class="lg:col-span-2">
      <Card title="People" pad={false}>
        {#snippet actions()}
          <span class="text-[11px] text-faint">
            {shown.length} of {users.length}{#if refreshing} &middot; <span class="animate-pulse text-accent/70">checking</span>{/if}
          </span>
        {/snippet}

        <div class="border-b border-edge/60 px-4 py-2.5">
          <div class="relative">
            <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
              <Icon name="search" size={13} />
            </span>
            <input
              bind:value={query}
              placeholder="Search names, ids or facts"
              class="w-full rounded-lg border border-edge bg-surface py-1.5 pl-8 pr-3 text-[12px] outline-none focus:border-accent/50"
            />
          </div>
        </div>

        {#if users.length === 0}
          <div class="p-4">
            <Empty
              text="Nothing remembered yet. The bot writes facts down on its own as people talk to it."
              icon="memory"
            />
          </div>
        {:else if shown.length === 0}
          <p class="px-5 py-8 text-center text-[13px] text-muted">Nothing matches that.</p>
        {:else}
          <div class="max-h-[58vh] divide-y divide-edge/60 overflow-y-auto">
            {#each shown as u (u.user_id)}
              <button
                onclick={() => open(u.user_id)}
                class="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors
                  {selected === u.user_id ? 'bg-accent/10' : 'hover:bg-white/[0.04]'}"
              >
                <!-- A face is how you actually recognise someone in a list. -->
                {#if u.avatar}
                  <img src={u.avatar} alt="" loading="lazy" referrerpolicy="no-referrer"
                       class="h-8 w-8 shrink-0 rounded-full object-cover ring-1 ring-edge" />
                {:else}
                  <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-faint">
                    <Icon name="accounts" size={14} />
                  </span>
                {/if}
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-[13px] text-ink">
                    {u.display_name || u.username || `#${u.user_id}`}
                  </span>
                  <span class="mt-0.5 flex items-center gap-2 text-[11px] text-faint">
                    <span>{u.fact_count} {u.fact_count === 1 ? "fact" : "facts"}</span>
                    {#if u.messages}<span>· {u.messages} msgs</span>{/if}
                    <span>· {ago(u.last_seen)}</span>
                  </span>
                </span>
                {#if u.persona}
                  <span class="shrink-0"><Badge tone="accent">persona</Badge></span>
                {/if}
              </button>
            {/each}
          </div>
        {/if}
      </Card>
    </div>

    <!-- ── One person ────────────────────────────────────────────────────── -->
    <div class="space-y-4 lg:col-span-3">
      {#if selected && detail && current}
        <Card title="Remembered facts">
          {#snippet actions()}
            <UserChip
              id={current.user_id}
              name={current.display_name || current.username || `#${current.user_id}`}
            />
          {/snippet}

          <div class="divide-y divide-edge/60">
            {#each Object.entries(detail.facts) as [key, value] (key)}
              <div class="group flex items-start gap-3 py-2">
                <span class="w-28 shrink-0 pt-0.5 font-mono text-[11px] text-accent">{key}</span>
                {#if editing === key}
                  <input
                    bind:value={editValue}
                    onkeydown={(e) => {
                      if (e.key === "Enter") commitEdit();
                      if (e.key === "Escape") editing = null;
                    }}
                    class="min-w-0 flex-1 rounded-md border border-accent/50 bg-surface px-2 py-1 text-[13px] outline-none"
                  />
                  <button class="shrink-0 text-[11px] text-good hover:underline" onclick={commitEdit}>
                    save
                  </button>
                  <button class="shrink-0 text-[11px] text-faint hover:underline" onclick={() => (editing = null)}>
                    cancel
                  </button>
                {:else}
                  <button
                    class="min-w-0 flex-1 break-words text-left text-[13px] text-ink/90 hover:text-accent"
                    title="Click to edit"
                    onclick={() => startEdit(key, value)}
                  >{value}</button>
                  <button
                    class="shrink-0 text-[11px] text-faint opacity-0 transition-opacity hover:text-bad group-hover:opacity-100"
                    onclick={() => deleteFact(key)}
                  >forget</button>
                {/if}
              </div>
            {:else}
              <p class="py-3 text-[13px] text-muted">
                Nothing written down about them yet.
              </p>
            {/each}
          </div>

          <div class="mt-4 flex flex-col gap-2 sm:flex-row">
            <input
              bind:value={newKey}
              placeholder="what, e.g. city"
              class="rounded-lg border border-edge bg-surface px-3 py-2 text-[13px] outline-none focus:border-accent/50 sm:w-40"
            />
            <input
              bind:value={newValue}
              onkeydown={(e) => e.key === "Enter" && addFact()}
              placeholder="value, e.g. Paris"
              class="min-w-0 flex-1 rounded-lg border border-edge bg-surface px-3 py-2 text-[13px] outline-none focus:border-accent/50"
            />
            <Button onclick={addFact} loading={saving} disabled={!newKey.trim()}>Add</Button>
          </div>
          <p class="mt-2 text-[11px] leading-relaxed text-faint">
            The bot adds these itself as it talks. Anything you add here is
            treated exactly the same way.
          </p>
        </Card>

        <Card title="Persona for this person">
          <p class="mb-2 text-[12px] leading-relaxed text-muted">
            Extra instructions used only when replying to them. Leave it empty
            to fall back to the normal persona.
          </p>
          <textarea
            bind:value={persona}
            rows={3}
            class="w-full rounded-lg border border-edge bg-black/40 p-3 text-[13px] outline-none focus:border-accent/50"
            placeholder="For example: be shorter and drier with them."
          ></textarea>
          <div class="mt-3 flex items-center justify-between gap-3">
            <button class="text-[11px] text-faint hover:text-bad" onclick={forgetAll}>
              Forget everything about them
            </button>
            <div class="flex items-center gap-2">
              {#if personaDirty}
                <button class="text-[11px] text-faint hover:text-ink"
                        onclick={() => (persona = detail?.persona || "")}>Undo</button>
              {/if}
              <Button onclick={() => put({ persona })} loading={saving} disabled={!personaDirty}>
                Save
              </Button>
            </div>
          </div>
        </Card>
      {:else}
        <Card>
          <Empty
            text="Pick someone on the left to see what the bot remembers, and change it."
            icon="memory"
          />
        </Card>
      {/if}
    </div>
  </div>
{/if}
