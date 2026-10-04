<script lang="ts">
  /**
   * What the bot has learned about people, and a way to correct it.
   *
   * The list is the important half: it is how you find the person you meant.
   * It sorts by who spoke most recently, is searchable, and each row says
   * enough to recognise someone without opening them: their face in a ring
   * that fills with how much is known about them, and how many facts.
   *
   * Someone opened gets a page of their own: who they are and how long they
   * have been talking to it, what the bot makes of them (PersonSummary), and
   * what it has written down, each fact a small card, changed in place.
   *
   * It opens with a glowing brain, its figures counting up, the people coming
   * in one after another; opening someone, their facts do (lib/domino.ts).
   *
   * The brain has a job: it is what the bot learned last. Beside it, who and
   * what ("Learned 5m ago: Mara's city: Paris"), and a click on either opens
   * that person with that fact lit. While the page is open it is asked again
   * every few seconds, and each time the bot writes something new down the
   * brain sparks, with a sound, and counts the people learned about since. With
   * nothing timed yet (facts from before times were kept), it opens the person
   * it knows the most about instead.
   */
  import { autowidth } from "../lib/autowidth";
  import { onMount, tick } from "svelte";
  import { visiblePoll } from "../lib/poll";
  import { play } from "../lib/uisound";
  import { motionEnabled } from "../lib/stores";
  import { get } from "svelte/store";
  import { api } from "../lib/api";
  import { ask } from "../lib/ask";
  import { DAY_MONTH, fmtDate } from "../lib/fmt";
  import { toast, viewPersona } from "../lib/stores";
  import PersonaScope from "../lib/personas/PersonaScope.svelte";
  import { personasRes } from "../lib/personas/store";
  import { resource } from "../lib/resource";
  import Button from "../lib/components/Button.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import FootNote from "../lib/components/FootNote.svelte";
  import UserChip from "../lib/components/UserChip.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import Avatar from "../lib/components/Avatar.svelte";
  import PersonSummary from "../lib/components/PersonSummary.svelte";
  import Num from "../lib/dashboard/Num.svelte";
  import { menu as contextMenu, copyText, type MenuEntry } from "../lib/contextmenu";
  import { chime, domino } from "../lib/domino";

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
    platform?: "snapchat";
    /** When the bot last wrote something down about them, and what (app/utils/memory.py learned_at). */
    learned_at?: number;
    learned?: string;
  };
  type MemDetail = { facts: Record<string, string>; persona: string | null };
  /** The last thing it learned about anyone. */
  type Latest = { user_id: string; name: string; key: string; value: string; at: number };

  // ── Whose memory ──────────────────────────────────────────────────────────
  // Each persona remembers people for itself (app/utils/personas.py): what Default knew is still Default's.
  let pid = $state(get(viewPersona) || "default");
  /** As the server is told it: "" for Default. */
  const who = $derived(pid === "default" ? "" : pid);
  const cast = $derived($personasRes.data.personas);
  const many = $derived(cast.length > 1);
  const whoName = $derived(cast.find((p) => p.id === pid)?.name ?? "");
  const title = $derived(many && whoName ? `What ${whoName} remembers` : "What it remembers");
  // A persona deleted since: Default's.
  $effect(() => {
    if ($personasRes.fetched && cast.length && !cast.some((p) => p.id === pid)) switchTo("default");
  });

  // Held outside the component, one list per persona, so leaving the tab and coming back shows what
  // was there instead of a skeleton and a fresh round trip.
  function peopleOf(p: string) {
    const as = p === "default" ? "" : p;
    return resource(as ? `memory:${as}` : "memory", () => api.memory(as), { users: [] as MemUser[], latest: null as Latest | null });
  }
  const people = $derived(peopleOf(pid));

  function switchTo(next: string) {
    if (next === pid) return;
    sinceAt = -1;
    selected = null;
    detail = null;
    editing = null;
    query = "";
    pid = next;
    viewPersona.set(next);
    peopleOf(next).refresh({ maxAge: 10000 });
  }

  const users = $derived<MemUser[]>($people.data.users ?? []);
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
  /** The most anyone is known by: a row's ring is full at that. */
  const mostKnown = $derived(Math.max(1, ...users.map((u) => u.fact_count ?? 0)));

  const personaDirty = $derived((detail?.persona || "") !== persona);

  // ── The brain: what it learned last ──────────────────────────────────────
  const latest = $derived<Latest | null>(($people.data as { latest?: Latest | null }).latest ?? null);
  /** With nothing timed yet: the person it knows the most about. */
  const best = $derived(users.reduce<MemUser | null>((b, u) => ((u.fact_count ?? 0) > (b?.fact_count ?? 0) ? u : b), null));
  /** What it had learned last when the page opened (or the brain was last pressed): newer is new. */
  let sinceAt = $state(-1);
  /** The people learned about since. */
  const newPeople = $derived(sinceAt < 0 ? 0 : users.filter((u) => (u.learned_at ?? 0) > sinceAt).length);
  let learning = $state(false);
  let learnTimer = 0;
  let flashKey = $state("");
  /** The newest it has sparked for: what it knew when the persona was first shown is not news. */
  let lastHeard = 0;
  $effect(() => {
    if (!$people.fetched) return;
    const at = latest?.at ?? 0;
    if (sinceAt < 0) {
      sinceAt = at;
      lastHeard = at;
      return;
    }
    if (at > lastHeard) {
      // Learned while watching: the brain sparks, heard as a glint and a soft chime.
      lastHeard = at;
      learning = false;
      requestAnimationFrame(() => (learning = true));
      clearTimeout(learnTimer);
      learnTimer = window.setTimeout(() => (learning = false), 1900);
      if (get(motionEnabled)) {
        play("glint", { strong: true });
        play("done", { delay: 240, level: 0.45 });
      }
    }
  });

  /** A fact's name as words: favourite_snack is "favourite snack". */
  const words = (k: string) => k.replace(/_/g, " ");

  /** Opens whoever the brain points at, the fact it learned lit and brought into view. */
  async function openBrain() {
    const uid = latest?.user_id ?? best?.user_id;
    if (!uid) return;
    play("slide", { level: 0.5 });
    if (latest) sinceAt = latest.at;
    await open(uid);
    const key = latest && latest.user_id === uid ? latest.key : "";
    if (!key) return;
    flashKey = "";
    await tick();
    flashKey = key;
    setTimeout(() => { if (flashKey === key) flashKey = ""; }, 2200);
    await tick();
    document.querySelector(`[data-fact="${CSS.escape(key)}"]`)
      ?.scrollIntoView({ block: "center", behavior: get(motionEnabled) ? "smooth" : "auto" });
  }

  const nameOf = (u: MemUser) =>
    u.display_name || u.username || (u.platform === "snapchat" ? "Someone on Snapchat" : `#${u.user_id}`);

  // Stale-while-revalidate: what is cached is already on screen, and this only
  // goes back to the server when that answer has aged out.
  onMount(() => {
    people.refresh({ maxAge: 10000 });
    personasRes.refresh({ maxAge: 15_000 });
    // Asked again every few seconds while the page is in view, so the brain sees the bot learn.
    const stop = visiblePoll(() => people.refresh({ force: true, quiet: true }), 12_000);
    return () => {
      stop();
      clearTimeout(learnTimer);
    };
  });

  const load = () => people.refresh({ force: true });

  async function open(uid: string) {
    selected = uid;
    editing = null;
    const asked = pid;
    try {
      const d: MemDetail = await api.memoryUser(uid, who);
      if (asked !== pid) return;
      detail = d;
      persona = d.persona || "";
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  async function put(body: any) {
    if (!selected) return;
    saving = true;
    try {
      await api.memoryPut(selected, body, who);
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
      await api.memoryDelete(selected, { key }, who);
      await open(selected);
      await load();
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  async function forgetAll() {
    if (!selected || !current) return;
    const who = current.display_name || current.username || selected;
    if (!(await ask(`Forget everything about ${who}?`, { detail: "This cannot be undone.", yes: "Forget", danger: true }))) return;
    try {
      await api.memoryDelete(selected, {}, who);
      toast("Forgotten", "ok");
      selected = null;
      detail = null;
      await load();
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  /** Right-click on someone: open them, copy who they are, or forget them. */
  function personMenu(u: { user_id: string; display_name?: string; username?: string }): MenuEntry[] {
    const who = u.display_name || u.username || `#${u.user_id}`;
    return [
      { title: who },
      { label: "Open", icon: "memory", run: () => open(u.user_id) },
      "sep",
      { label: "Copy name", icon: "copy", run: () => copyText(who, "Copied the name.") },
      { label: "Copy user ID", icon: "copy", run: () => copyText(u.user_id, "Copied the ID.") },
      "sep",
      // forgetAll asks first, and works on whoever is open.
      { label: "Forget everything…", icon: "eraser", danger: true, run: async () => { await open(u.user_id); await forgetAll(); } },
    ];
  }

  /** Right-click on a fact: change it, copy it, or forget just that. */
  function factMenu(key: string, value: string): MenuEntry[] {
    return [
      { label: "Edit", icon: "edit", run: () => startEdit(key, value) },
      { label: "Copy", icon: "copy", run: () => copyText(`${key}: ${value}`, "Copied the fact.") },
      "sep",
      { label: "Forget this", icon: "trash", danger: true, run: () => deleteFact(key) },
    ];
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
    return fmtDate(ts * 1000, DAY_MONTH);
  }
</script>

<ErrorNote text={loadError} onretry={load} />

{#if loading}
  <div class="glass h-40 animate-pulse rounded-[22px]"></div>
  <div class="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-5">
    <div class="glass h-96 animate-pulse rounded-[22px] lg:col-span-2"></div>
    <div class="glass h-96 animate-pulse rounded-[22px] lg:col-span-3"></div>
  </div>
{:else}
  <!-- ── What is in here at a glance ─────────────────────────────────────── -->
  <section class="mm-hero glass">
    <!-- What it learned last, opened with a click; it sparks each time it learns something while you watch. -->
    <button type="button" class="mm-orb" class:is-learning={learning} use:chime={"land"} onclick={openBrain}
            disabled={!latest && !best}
            title={latest ? `Open what it learned last: ${latest.name || "someone"}'s ${words(latest.key)}`
              : best ? `Open who it knows the most about: ${nameOf(best)}` : "Nothing remembered yet"}>
      <span class="mm-orb-ring" aria-hidden="true"></span>
      <span class="mm-orb-icon"><Icon name="memory" size={28} /></span>
      <i class="mm-spark is-a" aria-hidden="true"></i><i class="mm-spark is-b" aria-hidden="true"></i>
      <i class="mm-spark is-c" aria-hidden="true"></i><i class="mm-spark is-d" aria-hidden="true"></i>
      {#if newPeople}
        {#key newPeople}<span class="mm-orb-new" title="People it learned about since you opened this">+{newPeople}</span>{/key}
      {/if}
    </button>
    <div class="mm-who">
      {#if many}
        <!-- Whose memory: each persona remembers people for itself. -->
        <span class="mm-scope"><PersonaScope value={pid} onchange={switchTo} /></span>
      {:else}
        <span class="mm-kicker">Memory</span>
      {/if}
      <!-- The title types itself in, a soft key a letter, again for each persona. -->
      {#key title}
        <h2 class="mm-title domino" use:domino={{ step: 26, sound: "key", level: 0.55, max: 30, once: true }} aria-label={title}>
          {#each [...title] as ch, i (i)}<span class="mm-l">{ch}</span>{/each}
        </h2>
      {/key}
      <!-- What it learned last, said plainly; the same click as the brain. -->
      {#if latest}
        {#key latest.at}
          <button type="button" class="mm-last" onclick={openBrain}>
            <span class="mm-last-dot" aria-hidden="true"></span>
            <span class="mm-last-text">Learned {ago(latest.at)}: <b>{latest.name || "someone"}</b>'s {words(latest.key)}{#if latest.value}: <i>{latest.value}</i>{/if}</span>
            <Icon name="chevron" size={11} />
          </button>
        {/key}
      {:else if best && (best.fact_count ?? 0) > 0}
        <button type="button" class="mm-last is-best" onclick={openBrain}>
          <span class="mm-last-text">Knows the most about <b>{nameOf(best)}</b>, {best.fact_count} {best.fact_count === 1 ? "fact" : "facts"}</span>
          <Icon name="chevron" size={11} />
        </button>
      {:else}
        <p class="mm-sub">What the bot has written down about the people it talks to, as they talk.</p>
      {/if}
    </div>
    <!-- Each pops in after the one before, its number counting up (lib/domino.ts, Num). -->
    <div class="mm-stats domino" use:domino={{ step: 80 }}>
      {#each [{ label: "People", n: totals.people, icon: "accounts" }, { label: "Facts", n: totals.facts, icon: "memory" },
              { label: "Own tone", n: totals.personas, icon: "persona" }] as s (s.label)}
        <span class="mm-stat">
          <span class="mm-stat-icon"><Icon name={s.icon} size={14} /></span>
          <b><Num value={s.n} /></b>
          <span>{s.label}</span>
        </span>
      {/each}
    </div>
  </section>

  <div class="mm-body">
    <!-- ── Who the bot knows ─────────────────────────────────────────────── -->
    <section class="mm-people glass">
      <header class="mm-head">
        <h3>People</h3>
        <span class="mm-count">{shown.length}{shown.length !== users.length ? ` of ${users.length}` : ""}</span>
        {#if refreshing}<span class="mm-checking">checking</span>{/if}
      </header>
      <label class="mm-search">
        <Icon name="search" size={13} />
        <input bind:value={query} placeholder="Search names, ids or facts" spellcheck="false" autocomplete="off" />
      </label>

      {#if users.length === 0}
        <div class="mm-empty">
          <span class="mm-float"><Icon name="memory" size={24} /></span>
          <p>Nothing remembered yet. The bot writes facts down on its own as people talk to it.</p>
        </div>
      {:else if shown.length === 0}
        <p class="mm-none">Nothing matches that.</p>
      {:else}
        <div class="mm-list domino" use:domino={{ step: 35, max: 14 }}>
          {#each shown as u (u.user_id)}
            <button
              class="mm-row"
              class:is-sel={selected === u.user_id}
              onclick={() => open(u.user_id)}
              use:contextMenu={() => personMenu(u)}
            >
              <!-- A face is how you actually recognise someone in a list; the ring round it fills with how much is known. -->
              <span class="mm-av" style="--known: {Math.round(((u.fact_count ?? 0) / mostKnown) * 100)}%">
                <span class="mm-av-in">
                  <Avatar src={u.avatar} name={u.display_name || u.username || ""} size={34} zoom={false}
                          silhouette={u.platform === "snapchat"} />
                </span>
                {#if u.platform === "snapchat"}<span class="mem-snap" title="Snapchat"><Icon name="snapchat" size={9} /></span>{/if}
              </span>
              <span class="mm-row-main">
                <span class="mm-row-name">{nameOf(u)}</span>
                <span class="mm-row-meta">{ago(u.last_seen)}{#if u.messages} · {u.messages} msgs{/if}</span>
              </span>
              {#if u.persona}<span class="mm-own-dot" title="Has its own tone"><Icon name="persona" size={10} /></span>{/if}
              <span class="mm-facts" title="{u.fact_count} {u.fact_count === 1 ? 'fact' : 'facts'}">{u.fact_count}</span>
            </button>
          {/each}
        </div>
      {/if}
    </section>

    <!-- ── One person ────────────────────────────────────────────────────── -->
    <div class="mm-detail">
      {#if selected && current}
        {#key selected}
          <section class="mm-profile glass">
            <span class="mm-profile-av">
              <Avatar src={current.avatar} name={current.display_name || current.username || ""} size={60} zoom={false}
                      silhouette={current.platform === "snapchat"} />
            </span>
            <div class="mm-profile-who">
              <h3><UserChip id={current.user_id} name={nameOf(current)} /></h3>
              <p class="mm-profile-stats">
                <span><b>{current.fact_count ?? 0}</b> {current.fact_count === 1 ? "fact" : "facts"}</span>
                {#if current.messages}<span><b>{current.messages}</b> messages</span>{/if}
                {#if current.first_seen}<span>since <b>{fmtDate(current.first_seen * 1000, DAY_MONTH)}</b></span>{/if}
                <span>last <b>{ago(current.last_seen)}</b></span>
              </p>
            </div>
            <button class="mm-forget" onclick={forgetAll} title="Forget everything about them">
              <Icon name="eraser" size={13} />Forget
            </button>
          </section>
        {/key}
        <!-- Starts reading the moment someone is picked, before their facts
             have even arrived: it is the slow part, so it goes first. -->
        <PersonSummary uid={selected} name={current.display_name || current.username || ""} persona={who} />

        {#if detail}
          <section class="mm-facts-card glass">
            <header class="mm-head">
              <h3>Remembered facts</h3>
              <span class="mm-count">{Object.keys(detail.facts).length}</span>
            </header>
            <!-- Someone opened: what is remembered about them comes in a fact at a time, each a soft note. -->
            {#key selected}
              <div class="mm-fact-grid domino" use:domino={{ step: 45, level: 0.5 }}>
                {#each Object.entries(detail.facts) as [key, value] (key)}
                  <div class="mm-fact" class:is-editing={editing === key} class:is-flash={flashKey === key} data-fact={key}
                       use:contextMenu={() => (editing === key ? [] : factMenu(key, value))}>
                    <span class="mm-fact-key">{key}</span>
                    {#if editing === key}
                      <input
                        bind:value={editValue}
                        onkeydown={(e) => {
                          if (e.key === "Enter") commitEdit();
                          if (e.key === "Escape") editing = null;
                        }}
                        class="mm-fact-input"
                      />
                      <span class="mm-fact-actions">
                        <button class="text-good hover:underline" onclick={commitEdit}>save</button>
                        <button class="text-faint hover:underline" onclick={() => (editing = null)}>cancel</button>
                      </span>
                    {:else}
                      <button class="mm-fact-value" title="Click to change it" onclick={() => startEdit(key, value)}>{value}</button>
                      <button class="mm-fact-x" onclick={() => deleteFact(key)} title="Forget this" aria-label="Forget {key}">
                        <Icon name="close" size={10} />
                      </button>
                    {/if}
                  </div>
                {:else}
                  <p class="mm-none">Nothing written down about them yet.</p>
                {/each}
              </div>
            {/key}

            <div class="mm-add">
              <span class="mm-add-icon"><Icon name="plus" size={13} /></span>
              <input bind:value={newKey} placeholder="what, e.g. city" class="field mm-add-key"
                     use:autowidth={{ value: newKey }} />
              <input
                bind:value={newValue}
                onkeydown={(e) => e.key === "Enter" && addFact()}
                placeholder="value, e.g. Paris"
                class="field min-w-0 flex-1"
              />
              <Button onclick={addFact} loading={saving} disabled={!newKey.trim()}>Add</Button>
            </div>
            <FootNote class="mt-3" icon="memory">
              The bot adds these itself as it talks. Anything you add here is
              treated exactly the same way.
            </FootNote>
          </section>

          <section class="mm-own-card glass">
            <header class="mm-head">
              <h3>How it talks to them</h3>
            </header>
            <p class="mm-own-note">Extra instructions used only when replying to them. Leave it empty for its usual way.</p>
            <textarea
              bind:value={persona}
              rows={3}
              class="field mm-own-text"
              placeholder="For example: be shorter and drier with them."
            ></textarea>
            <div class="mt-3 flex items-center justify-end gap-2">
              {#if personaDirty}
                <button class="text-[11px] text-faint hover:text-ink" onclick={() => (persona = detail?.persona || "")}>Undo</button>
              {/if}
              <Button onclick={() => put({ persona })} loading={saving} disabled={!personaDirty}>Save</Button>
            </div>
          </section>
        {/if}
      {:else}
        <section class="mm-pick glass">
          <span class="mm-float"><Icon name="memory" size={26} /></span>
          <p>Pick someone to see what the bot remembers about them, and change it.</p>
          <span class="mm-pick-arrow" aria-hidden="true"><Icon name="chevron" size={14} /></span>
        </section>
      {/if}
    </div>
  </div>
{/if}

<style>
  /* ── The hero ── */
  .mm-hero {
    position: relative;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 18px 22px;
    margin-bottom: 16px;
    padding: 22px 24px;
    overflow: hidden;
    border-radius: 22px;
    background-image:
      radial-gradient(70% 150% at 0% 0%, color-mix(in srgb, var(--color-accent-2) 20%, transparent), transparent 60%),
      radial-gradient(50% 120% at 100% 100%, color-mix(in srgb, var(--color-accent) 12%, transparent), transparent 70%);
  }
  /* The brain in a ring of light that turns: pressed, it opens what it learned last; sparks fly off it when it learns. */
  .mm-orb {
    position: relative;
    display: grid;
    width: 72px;
    height: 72px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    cursor: pointer;
    animation: mm-orb-in 0.7s var(--jelly) backwards;
    transition: transform 0.45s var(--jelly);
  }
  .mm-orb:hover:not(:disabled) { transform: scale(1.07) rotate(5deg); }
  .mm-orb:active:not(:disabled) { transform: scale(0.94); }
  .mm-orb:disabled { cursor: default; }
  .mm-orb:focus-visible { outline: 2px solid var(--color-accent-2); outline-offset: 3px; }
  /* Learning: a ring of light bursts off it and the brain jumps. */
  .mm-orb::after {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 999px;
    pointer-events: none;
    opacity: 0;
  }
  .mm-orb.is-learning::after { animation: mm-burst 1.1s ease-out; }
  @keyframes mm-burst {
    0% { opacity: 0.9; box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-accent-2) 70%, transparent); }
    100% { opacity: 0; box-shadow: 0 0 0 26px color-mix(in srgb, var(--color-accent-2) 0%, transparent); }
  }
  .mm-orb.is-learning .mm-orb-icon { animation: mm-learn 0.9s var(--jelly); }
  @keyframes mm-learn { 30% { transform: scale(1.18) rotate(-8deg); box-shadow: 0 0 30px -2px var(--color-accent-2); } }
  /* How many people it learned about since the page opened. */
  .mm-orb-new {
    position: absolute;
    right: -4px;
    top: -2px;
    padding: 1px 6px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 750;
    color: var(--color-bg);
    background: var(--color-accent-2);
    box-shadow: 0 0 0 2px var(--color-card), 0 4px 12px -4px var(--color-accent-2);
    animation: mm-new 0.5s var(--jelly);
  }
  @keyframes mm-new { from { transform: scale(0.3); opacity: 0; } }
  @keyframes mm-orb-in { from { opacity: 0; transform: scale(0.4) rotate(30deg); } }
  .mm-orb-ring {
    position: absolute;
    inset: 0;
    border-radius: 999px;
    background: conic-gradient(from 90deg, var(--color-accent-2), var(--color-accent), transparent 60%, var(--color-accent-2));
    -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 2px));
    mask: radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 2px));
    animation: mm-turn 7s linear infinite;
  }
  @keyframes mm-turn { to { transform: rotate(-360deg); } }
  .mm-orb-icon {
    display: grid;
    width: 60px;
    height: 60px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-accent-2);
    background: radial-gradient(circle at 35% 30%, color-mix(in srgb, var(--color-accent-2) 30%, var(--color-card)), var(--color-card));
    animation: mm-think 3.2s ease-in-out infinite;
  }
  @keyframes mm-think { 50% { transform: scale(1.05); box-shadow: 0 0 24px -4px color-mix(in srgb, var(--color-accent-2) 60%, transparent); } }
  .mm-spark {
    position: absolute;
    width: 5px;
    height: 5px;
    border-radius: 999px;
    background: var(--color-accent-2);
    box-shadow: 0 0 8px var(--color-accent-2);
    opacity: 0;
  }
  /* Only when it learns something: a few sparks fly up off it. */
  .mm-orb.is-learning .mm-spark { animation: mm-spark 1.1s ease-out backwards; }
  .mm-spark.is-a { left: 14%; top: 18%; }
  .mm-spark.is-b { right: 8%; top: 34%; }
  .mm-spark.is-c { left: 46%; top: 4%; }
  .mm-spark.is-d { left: 26%; bottom: 10%; }
  .mm-orb.is-learning .mm-spark.is-b { animation-delay: 0.12s; }
  .mm-orb.is-learning .mm-spark.is-c { animation-delay: 0.24s; }
  .mm-orb.is-learning .mm-spark.is-d { animation-delay: 0.08s; }
  @keyframes mm-spark { 0% { opacity: 0; transform: translateY(4px) scale(0.6); } 30% { opacity: 1; } 100% { opacity: 0; transform: translateY(-16px) scale(0.2); } }

  .mm-who { display: flex; min-width: 0; flex: 1 1 240px; flex-direction: column; gap: 2px; }
  .mm-kicker { font-size: 10.5px; font-weight: 650; letter-spacing: 0.16em; text-transform: uppercase; color: var(--color-faint); }
  /* A letter a box, so each can pop in on its own; kept on one line, as a break could come inside a word. */
  .mm-title { max-width: 100%; overflow: hidden; white-space: nowrap; font-size: 26px; font-weight: 700; line-height: 1.15;
              letter-spacing: -0.02em; color: var(--color-ink); }
  .mm-l { display: inline-block; white-space: pre; }
  .mm-scope { display: inline-flex; margin-bottom: 4px; }
  .mm-sub { margin-top: 3px; font-size: 12.5px; color: var(--color-muted); }
  /* What it learned last: a line that opens it. */
  .mm-last {
    display: inline-flex;
    max-width: 100%;
    align-self: flex-start;
    align-items: center;
    gap: 8px;
    margin-top: 5px;
    padding: 4px 10px 4px 9px;
    border-radius: 999px;
    font-size: 12.5px;
    text-align: left;
    color: var(--color-muted);
    background: color-mix(in srgb, var(--color-accent-2) 8%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent-2) 22%, transparent);
    animation: mm-last-in 0.5s var(--jelly);
    transition: background-color 0.15s ease, color 0.15s ease, transform 0.35s var(--jelly);
  }
  @keyframes mm-last-in { from { opacity: 0; transform: translateY(6px); } }
  .mm-last:hover { color: var(--color-ink); background: color-mix(in srgb, var(--color-accent-2) 15%, transparent); transform: translateX(2px); }
  .mm-last b { font-weight: 650; color: var(--color-ink); }
  .mm-last i { font-style: normal; color: var(--color-ink); }
  .mm-last-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .mm-last > :global(svg) { flex-shrink: 0; color: var(--color-accent-2); transition: transform 0.3s var(--jelly); }
  .mm-last:hover > :global(svg) { transform: translateX(2px); }
  .mm-last-dot { position: relative; width: 7px; height: 7px; flex-shrink: 0; border-radius: 999px; background: var(--color-accent-2); }
  .mm-last-dot::after { content: ""; position: absolute; inset: 0; border-radius: inherit; background: inherit; animation: mm-ping 2.2s ease-out infinite; }
  @keyframes mm-ping { from { opacity: 0.7; transform: scale(1); } to { opacity: 0; transform: scale(2.8); } }
  .mm-stats { display: flex; gap: 8px; }
  .mm-stat {
    display: flex;
    min-width: 82px;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    padding: 9px 12px 8px;
    border-radius: 14px;
    font-size: 10.5px;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.035);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    transition: transform 0.4s var(--jelly), background-color 0.2s ease;
  }
  .mm-stat:hover { transform: translateY(-2px); background: rgb(255 255 255 / 0.06); }
  .mm-stat b { font-size: 18px; font-weight: 700; color: var(--color-ink); }
  .mm-stat-icon { display: grid; color: var(--color-accent-2); transition: transform 0.45s var(--jelly); }
  .mm-stat:hover .mm-stat-icon { transform: rotate(-10deg) scale(1.15); }

  /* ── The two halves ── */
  .mm-body { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; align-items: start; }
  @media (min-width: 1024px) { .mm-body { grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); } }
  .mm-head { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
  .mm-head h3 { font-size: 14px; font-weight: 650; letter-spacing: -0.01em; color: var(--color-ink); }
  .mm-count {
    padding: 1px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.06);
  }
  .mm-checking { margin-left: auto; font-size: 11px; color: color-mix(in srgb, var(--color-accent) 70%, transparent); animation: mm-breathe 1.4s ease-in-out infinite; }
  @keyframes mm-breathe { 50% { opacity: 0.35; } }
  .mm-none { padding: 22px 6px; font-size: 12.5px; text-align: center; color: var(--color-muted); }

  /* ── The people ── */
  .mm-people { padding: 16px; border-radius: 22px; }
  .mm-search {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
    padding: 0 12px;
    border-radius: 12px;
    color: var(--color-faint);
    background: linear-gradient(180deg, rgb(0 0 0 / 0.28), rgb(0 0 0 / 0.16));
    box-shadow: inset 0 1px 2px rgb(0 0 0 / 0.3), inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    transition: box-shadow 0.25s var(--swift);
  }
  .mm-search:focus-within { color: var(--color-accent); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 55%, transparent), 0 0 0 3px color-mix(in srgb, var(--color-accent) 16%, transparent); }
  .mm-search input { min-width: 0; flex: 1; padding: 9px 0; font-size: 12.5px; color: var(--color-ink); background: transparent; outline: none; caret-color: var(--color-accent); }
  .mm-list { display: flex; max-height: 58vh; flex-direction: column; gap: 3px; overflow-y: auto; margin: 0 -6px; padding: 0 6px; }
  .mm-row {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 11px;
    padding: 8px 10px;
    border-radius: 14px;
    text-align: left;
    transition: background-color 0.15s ease, transform 0.35s var(--jelly), box-shadow 0.2s ease;
  }
  .mm-row:hover { background: rgb(255 255 255 / 0.045); }
  .mm-row:active { transform: scale(0.97); transition-duration: 0.08s; }
  .mm-row.is-sel {
    background: linear-gradient(90deg, color-mix(in srgb, var(--color-accent) 16%, transparent), color-mix(in srgb, var(--color-accent) 6%, transparent));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 38%, transparent);
  }
  /* The face, in a ring filled to how much is known about them. */
  .mm-av {
    position: relative;
    display: inline-flex;
    flex-shrink: 0;
    padding: 3px;
    border-radius: 999px;
    background: conic-gradient(var(--color-accent-2) var(--known, 0%), rgb(255 255 255 / 0.08) 0);
  }
  /* The face on a solid disc, so only the ring round it shows the fill (a face without a picture is see-through). */
  .mm-av-in { display: inline-flex; border-radius: 999px; background: var(--color-card); box-shadow: 0 0 0 2px var(--color-card); }
  .mm-row-main { display: flex; min-width: 0; flex: 1; flex-direction: column; }
  .mm-row-name { overflow: hidden; font-size: 13px; font-weight: 600; color: var(--color-ink); text-overflow: ellipsis; white-space: nowrap; }
  .mm-row-meta { font-size: 11px; color: var(--color-faint); }
  .mm-facts {
    display: grid;
    min-width: 26px;
    height: 22px;
    flex-shrink: 0;
    place-items: center;
    padding: 0 7px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--color-accent-2);
    background: color-mix(in srgb, var(--color-accent-2) 14%, transparent);
    transition: transform 0.35s var(--jelly);
  }
  .mm-row:hover .mm-facts { transform: scale(1.12); }
  .mm-own-dot { display: grid; width: 20px; height: 20px; flex-shrink: 0; place-items: center; border-radius: 999px; color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 14%, transparent); }
  /* Snapchat's own yellow, as a small mark on the face. */
  .mem-snap {
    position: absolute;
    right: -2px;
    bottom: -2px;
    display: inline-grid;
    width: 14px;
    height: 14px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    color: #141414;
    background: #fffc00;
    box-shadow: 0 0 0 2px var(--color-card);
  }

  /* ── One person ── */
  .mm-detail { display: flex; min-width: 0; flex-direction: column; gap: 16px; }
  .mm-profile {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 14px 16px;
    padding: 18px 20px;
    border-radius: 22px;
    background-image: radial-gradient(80% 160% at 0% 0%, color-mix(in srgb, var(--color-accent) 16%, transparent), transparent 65%);
    animation: mm-profile-in 0.45s var(--jelly) backwards;
  }
  @keyframes mm-profile-in { from { opacity: 0; transform: translateY(10px) scale(0.98); } }
  .mm-profile-av { display: inline-flex; border-radius: 999px; box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 45%, transparent), 0 10px 26px -12px var(--color-accent); animation: mm-orb-in 0.6s var(--jelly) 0.05s backwards; }
  .mm-profile-who { min-width: 0; flex: 1; }
  .mm-profile-who h3 { font-size: 18px; font-weight: 700; letter-spacing: -0.01em; color: var(--color-ink); }
  .mm-profile-stats { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 4px; font-size: 11.5px; color: var(--color-faint); }
  .mm-profile-stats b { font-weight: 650; color: var(--color-muted); }
  .mm-forget {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 11px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 600;
    color: var(--color-faint);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    transition: color 0.15s ease, background-color 0.15s ease, transform 0.3s var(--jelly);
  }
  .mm-forget:hover { color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 10%, transparent); }
  .mm-forget:active { transform: scale(0.94); }

  /* What is written down: a small card each, changed in place. */
  .mm-facts-card, .mm-own-card { padding: 16px 18px 18px; border-radius: 22px; }
  .mm-fact-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 8px; }
  .mm-fact {
    position: relative;
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 3px;
    padding: 9px 30px 10px 12px;
    border-radius: 14px;
    background: rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 75%, transparent);
    transition: background-color 0.15s ease, box-shadow 0.2s ease, transform 0.35s var(--jelly);
  }
  .mm-fact:hover { background: rgb(255 255 255 / 0.055); transform: translateY(-1px); }
  /* The fact the brain opened to: lit for a moment. */
  .mm-fact.is-flash { animation: mm-flash 2s ease-out; }
  @keyframes mm-flash {
    0%, 25% { background: color-mix(in srgb, var(--color-accent-2) 18%, transparent);
              box-shadow: inset 0 0 0 1.5px var(--color-accent-2), 0 0 24px -6px var(--color-accent-2); }
  }
  .mm-fact.is-editing { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 55%, transparent), 0 0 0 3px color-mix(in srgb, var(--color-accent) 14%, transparent); }
  .mm-fact-key { font-family: ui-monospace, monospace; font-size: 10.5px; letter-spacing: 0.02em; color: var(--color-accent-2); }
  .mm-fact-value { overflow-wrap: anywhere; font-size: 13px; text-align: left; color: var(--color-ink); transition: color 0.15s ease; }
  .mm-fact-value:hover { color: var(--color-accent); }
  .mm-fact-x {
    position: absolute;
    top: 7px;
    right: 7px;
    display: grid;
    width: 18px;
    height: 18px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-faint);
    opacity: 0;
    transition: opacity 0.15s ease, color 0.15s ease, background-color 0.15s ease;
  }
  .mm-fact:hover .mm-fact-x, .mm-fact-x:focus-visible { opacity: 1; }
  .mm-fact-x:hover { color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 14%, transparent); }
  .mm-fact-input { width: 100%; padding: 2px 0; font-size: 13px; color: var(--color-ink); background: transparent; outline: none; caret-color: var(--color-accent); border-bottom: 1px solid color-mix(in srgb, var(--color-accent) 60%, transparent); }
  .mm-fact-actions { display: flex; gap: 10px; margin-top: 3px; font-size: 11px; }
  .mm-add { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 14px; }
  .mm-add-icon { display: grid; width: 30px; height: 30px; flex-shrink: 0; place-items: center; border-radius: 10px; color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 12%, transparent); }
  .mm-add-key { flex-shrink: 0; max-width: 45%; }
  .mm-own-note { margin: -4px 0 10px; font-size: 12px; line-height: 1.5; color: var(--color-muted); }
  .mm-own-text { min-height: 84px; resize: vertical; }

  /* Nobody picked, or nobody yet: the brain, floating. */
  .mm-pick, .mm-empty {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    padding: 48px 24px;
    text-align: center;
    font-size: 13px;
    line-height: 1.55;
    color: var(--color-muted);
  }
  .mm-pick { border-radius: 22px; }
  .mm-pick p, .mm-empty p { max-width: 320px; }
  .mm-float {
    display: grid;
    width: 54px;
    height: 54px;
    place-items: center;
    border-radius: 18px;
    color: var(--color-accent-2);
    background: color-mix(in srgb, var(--color-accent-2) 12%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent-2) 25%, transparent);
    animation: mm-float 3.4s ease-in-out infinite;
  }
  @keyframes mm-float { 50% { transform: translateY(-6px) rotate(-4deg); } }
  .mm-pick-arrow { display: none; color: var(--color-faint); }
  @media (min-width: 1024px) {
    .mm-pick-arrow { position: absolute; top: 50%; left: 16px; display: grid; transform: rotate(180deg); animation: mm-nudge 1.6s ease-in-out infinite; }
  }
  @keyframes mm-nudge { 50% { transform: rotate(180deg) translateX(6px); } }

  :global(:root[data-motion="off"]) .mm-orb,
  :global(:root[data-motion="off"]) .mm-orb-ring,
  :global(:root[data-motion="off"]) .mm-orb-icon,
  :global(:root[data-motion="off"]) .mm-spark,
  :global(:root[data-motion="off"]) .mm-orb::after,
  :global(:root[data-motion="off"]) .mm-orb-new,
  :global(:root[data-motion="off"]) .mm-last,
  :global(:root[data-motion="off"]) .mm-last-dot::after,
  :global(:root[data-motion="off"]) .mm-fact.is-flash,
  :global(:root[data-motion="off"]) .mm-profile,
  :global(:root[data-motion="off"]) .mm-profile-av,
  :global(:root[data-motion="off"]) .mm-float,
  :global(:root[data-motion="off"]) .mm-pick-arrow,
  :global(:root[data-motion="off"]) .mm-checking { animation: none; }
  :global(:root[data-motion="off"]) .mm-row,
  :global(:root[data-motion="off"]) .mm-stat,
  :global(:root[data-motion="off"]) .mm-fact,
  :global(:root[data-motion="off"]) .mm-facts { transition: none; }
</style>
