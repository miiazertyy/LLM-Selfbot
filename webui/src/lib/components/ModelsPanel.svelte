<script lang="ts">
  /**
   * Which model does which job.
   *
   * Replies are a chain, in the order they are tried: drag to reorder, and the
   * second one only ever writes when the first is rate limited, down or out of
   * credit. It used to be a switch between "Groq" and "this computer", with the
   * other jobs greyed out until the switch was on; now every job can be on any
   * provider that can do it, and anything left unset stays on Groq.
   */
  import { autowidth } from "../autowidth";
  import { onMount, tick } from "svelte";
  import { flip } from "svelte/animate";
  import { get } from "svelte/store";
  import { api } from "../api";
  import { toast, settingsSection } from "../stores";
  import {
    JOB_NAMES, jobDefaults, loadModels, loadProviders, maxReplyTokens, modelLists, planPersona, providerList, providersLoaded,
    same, savedPlan, shortModel,
    type Entry,
  } from "../providers";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import ModelChooser from "./ModelChooser.svelte";
  import ProviderTile from "./ProviderTile.svelte";
  import RankBadge from "./RankBadge.svelte";
  import { lastUse, loadUsage, startUsageLive, usage, usageFor, usageKey } from "../modelusage";
  import { play } from "../uisound";
  import { domino } from "../domino";

  type JobKey = keyof typeof JOB_NAMES;
  const JOB_KEYS = Object.keys(JOB_NAMES) as JobKey[];

  let chain = $state<Entry[]>([]);
  // Each job's models in the order they are tried. Empty means Groq's default,
  // which is also what every job falls back to after its own list.
  let jobs = $state<Record<JobKey, Entry[]>>({} as any);
  let tokens = $state(320);
  let saving = $state(false);
  let loadError = $state("");

  /**
   * The saved jobs, with "on Groq's default model" written as unset. The
   * server resolves every job to something, so without this a job nobody ever
   * touched would look like a deliberate choice of Groq.
   */
  const savedJobs = $derived.by(() => {
    const p = $savedPlan;
    const out = {} as Record<JobKey, Entry[]>;
    if (!p) return out;
    for (const k of JOB_KEYS) {
      const d = $jobDefaults[k];
      const c: Entry[] = (p.chains?.[k] ?? [p[k]]).filter((e): e is Entry => !!e).map((e) => ({ ...e }));
      out[k] = c.length === 1 && d && c[0].provider === "groq" && c[0].model === d.model ? [] : c;
    }
    return out;
  });

  function reset() {
    const p = $savedPlan;
    if (!p) return;
    chain = p.replies.map((e) => ({ ...e }));
    jobs = Object.fromEntries(JOB_KEYS.map((k) => [k, savedJobs[k].map((e) => ({ ...e }))])) as any;
    tokens = $maxReplyTokens;
  }

  /** Whether the server on this computer answers, for its rows' status. */
  let localUp = $state<boolean | null>(null);
  /** A model there that would not load, and what is being done about it (app/utils/localfix.py). */
  let localFix = $state<{ model: string; state: string; why: string; to: string } | null>(null);

  onMount(async () => {
    // Each answer lights up the row of the model that gave it (see modelusage.ts).
    startUsageLive();
    loadUsage().catch(() => {});
    if ($providersLoaded) reset();
    try {
      await loadProviders();
      reset();
    } catch (e: any) {
      loadError = e?.message || "Could not load the models";
    }
    // The lists of every provider in use, so a model it no longer has (retired,
    // renamed, never downloaded) is flagged here rather than by a failed reply.
    const inUse = new Set([...chain.map((e) => e.provider), ...JOB_KEYS.flatMap((k) => (jobs[k] ?? []).map((e) => e.provider))]);
    for (const pid of inUse) if (prov(pid)?.ready) loadModels(pid);
    const usesLocal = inUse.has("local");
    if (usesLocal) {
      api.localStatus().then((s: any) => {
        localUp = !!s?.reachable;
        localFix = s?.fix?.state ? s.fix : null;
      }).catch(() => (localUp = false));
    }
  });

  const key = (e: Entry) => `${e.provider}:${e.model}`;
  const prov = (id: string) => $providerList.find((p) => p.id === id);
  const provName = (id: string) => prov(id)?.name ?? id;

  const dirty = $derived.by(() => {
    const p = $savedPlan;
    if (!p) return false;
    if (tokens !== $maxReplyTokens) return true;
    if (chain.length !== p.replies.length || chain.some((e, i) => !same(e, p.replies[i]))) return true;
    return JOB_KEYS.some((k) => {
      const a = jobs[k] ?? [], b = savedJobs[k] ?? [];
      return a.length !== b.length || a.some((e, i) => !same(e, b[i]));
    });
  });

  // ── The chain ────────────────────────────────────────────────────────
  let rows: HTMLElement[] = $state([]);
  let dragging = $state<number | null>(null);

  function move(from: number, to: number) {
    if (to < 0 || to >= chain.length || from === to) return;
    const next = [...chain];
    const [it] = next.splice(from, 1);
    next.splice(to, 0, it);
    chain = next;
  }

  // Heard as it is moved: lifted, a woody click each place it passes (lower
  // down the list a little lower), and put down.
  const placeP = (to: number) => (chain.length > 1 ? to / (chain.length - 1) : 0.5);

  function startDrag(i: number, e: PointerEvent) {
    dragging = i;
    play("lift");
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    e.preventDefault();
  }

  function onDrag(e: PointerEvent) {
    if (dragging === null) return;
    // The row the pointer is over, by midpoints, so a row swaps as soon as
    // you are more than halfway across it.
    let to = dragging;
    for (let j = 0; j < chain.length; j++) {
      const el = rows[j];
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (e.clientY < r.top + r.height / 2) { to = j; break; }
      to = j;
    }
    if (to !== dragging) {
      move(dragging, to);
      dragging = to;
      play("slot", { p: placeP(to) });
    }
  }

  function endDrag() {
    if (dragging === null) return;
    dragging = null;
    play("drop");
  }

  async function keyMove(i: number, e: KeyboardEvent) {
    const to = e.key === "ArrowUp" ? i - 1 : e.key === "ArrowDown" ? i + 1 : -1;
    if (to < 0 || to >= chain.length) return;
    e.preventDefault();
    move(i, to);
    play("slot", { p: placeP(to) });
    await tick();
    rows[to]?.querySelector<HTMLElement>(".mp-grip")?.focus();
  }

  function remove(i: number) {
    // The last one too: one removed from the computer it ran on could not be taken off before.
    chain = chain.filter((_, j) => j !== i);
  }

  // ── Trying a model ───────────────────────────────────────────────────
  let trying = $state<Record<string, boolean>>({});
  let tried = $state<Record<string, { ok: boolean; ms?: number; error?: string; detail?: string }>>({});

  async function tryIt(e: Entry) {
    const k = key(e);
    trying[k] = true;
    try {
      tried[k] = await api.providerTry(e.provider, e.model);
    } catch (err: any) {
      tried[k] = { ok: false, error: err?.message || "Could not try it" };
    } finally {
      delete trying[k];
    }
  }

  // ── Choosing ─────────────────────────────────────────────────────────
  let chooser = $state<{ need: any; title: string; current: Entry | null; job: JobKey | "add" | number;
                         anchor: HTMLElement | null; fallback?: boolean; exclude?: Entry[] } | null>(null);
  let chooserOpen = $state(false);

  /** Opens the model dropdown under the button that was clicked; the same button closes it. */
  function openChooser(job: JobKey | "add" | number, e: MouseEvent) {
    const anchor = e.currentTarget as HTMLElement;
    if (chooserOpen && chooser?.anchor === anchor) {
      chooserOpen = false;
      return;
    }
    if (job === "add") chooser = { need: "chat", title: "Add a model to write replies", current: null, job, anchor };
    else if (typeof job === "number") chooser = { need: "chat", title: "Swap this model", current: chain[job], job, anchor };
    else chooser = { need: JOB_NAMES[job].needs, title: JOB_NAMES[job].title, current: jobs[job]?.[0] ?? null, job, anchor };
    chooserOpen = true;
  }

  /** The dropdown again, to add a model that takes over when the ones before it fail. */
  function openFallback(k: JobKey, e: MouseEvent) {
    const anchor = e.currentTarget as HTMLElement;
    if (chooserOpen && chooser?.anchor === anchor) {
      chooserOpen = false;
      return;
    }
    chooser = { need: JOB_NAMES[k].needs, title: `${JOB_NAMES[k].title}: add a fallback`, current: null, job: k,
                anchor, fallback: true, exclude: effectiveChain(k) };
    chooserOpen = true;
  }

  function picked(e: Entry) {
    if (!chooser) return;
    const j = chooser.job;
    if (j === "add") chain = [...chain, e];
    else if (typeof j === "number") chain = chain.map((x, i) => (i === j ? e : x));
    else if (chooser.fallback) {
      // A fallback after Groq's default makes no sense on its own: start the
      // list from the default, so what is added really comes second.
      const base = jobs[j]?.length ? jobs[j] : ($jobDefaults[j] ? [{ ...$jobDefaults[j] }] : []);
      jobs = { ...jobs, [j]: [...base, e] };
    } else jobs = { ...jobs, [j]: [e, ...(jobs[j] ?? []).slice(1)] };
  }

  function resetJob(k: JobKey) {
    jobs = { ...jobs, [k]: [] };
  }

  function removeFallback(k: JobKey, i: number) {
    jobs = { ...jobs, [k]: (jobs[k] ?? []).filter((_, j) => j !== i) };
  }

  // ── Saving ───────────────────────────────────────────────────────────
  async function save() {
    saving = true;
    try {
      const body: any = { replies: chain };
      for (const k of JOB_KEYS) body[k] = jobs[k] ?? [];
      // Everyone's, or the persona Settings is set to.
      const persona = get(planPersona);
      await api.savePlan(body, persona);
      if (tokens !== $maxReplyTokens) {
        await api.configField("bot.max_reply_tokens", Math.max(96, Math.round(tokens)), persona ? { persona } : {});
      }
      await loadProviders();
      reset();
      toast("Saved. The next reply uses it, no restart needed.", "ok");
    } catch (e: any) {
      toast(e?.message || "Could not save", "err");
    } finally {
      saving = false;
    }
  }

  function status(e: Entry): { tone: "good" | "warn" | "muted"; text: string; why?: string } {
    const p = prov(e.provider);
    if (!p) return { tone: "warn", text: "unknown provider" };
    if (!p.ready) return { tone: "warn", text: p.id === "local" ? "not set up" : "no key" };
    // One that would not load: said here, with why on hover, rather than only in the log.
    if (p.id === "local" && localFix?.model === e.model && localFix.state !== "fixed") {
      return { tone: "warn", text: localFix.state === "fixing" ? "won't load, getting the model itself" : "won't load",
               why: localFix.why };
    }
    const list = $modelLists[p.id];
    if (list && !list.loading && list.models.length && !list.models.some((m) => m.id === e.model)) {
      return { tone: "warn", text: p.id === "local" ? "not downloaded on this computer" : `${p.name} does not offer it` };
    }
    if (p.id === "local") {
      if (localUp === false) return { tone: "warn", text: "server not answering" };
      return { tone: localUp ? "good" : "muted", text: localUp ? "server running" : "checking the server" };
    }
    return { tone: "good", text: "connected" };
  }

  /** A job left unset runs on its Groq model. */
  const isDefault = (k: JobKey) => !(jobs[k]?.length);
  const effective = (k: JobKey): Entry | null => (jobs[k]?.length ? jobs[k][0] : $jobDefaults[k] ?? null);
  /** What the job tries, in order, as it will run. */
  const effectiveChain = (k: JobKey): Entry[] => (jobs[k]?.length ? jobs[k] : $jobDefaults[k] ? [$jobDefaults[k]] : []);
  /** Whether Groq's default still comes last, after everything picked. */
  const groqLast = (k: JobKey) => {
    const d = $jobDefaults[k];
    return !!d && !isDefault(k) && !jobs[k].some((e) => e.provider === "groq" && e.model === d.model);
  };
</script>

{#if loadError && !$providersLoaded}
  <p class="text-[12.5px] text-bad">{loadError}</p>
{:else if !$providersLoaded || !$savedPlan}
  <div class="space-y-2">
    {#each Array(5) as _}<div class="h-14 animate-pulse rounded-xl bg-white/[0.03]"></div>{/each}
  </div>
{:else}
  <!-- ── Replies ──────────────────────────────────────────────────────── -->
  <section class="mp-card">
    <header class="mp-head">
      <span class="mp-head-icon"><Icon name="chats" size={16} /></span>
      <div class="min-w-0 flex-1">
        <h3 class="text-[14.5px] font-semibold text-ink">Replies</h3>
        <p class="text-[12px] text-muted">
          Tried top to bottom. When one is rate limited, down or out of credit, the next one writes the reply.
        </p>
      </div>
      <Button size="sm" kind="ghost" onclick={(e) => openChooser("add", e)}><Icon name="plus" size={12} />Add a model</Button>
    </header>

    <!-- As the tab opens the models plug in one after another, top to bottom, the way a reply tries them: each slides
         in, a beam of light runs across it, its light comes on, and it is heard landing, a step higher down the chain
         (lib/domino.ts). Only then: a model added later, or a reorder, is not a show. -->
    <ol class="mp-chain domino" onpointermove={onDrag} onpointerup={endDrag} onpointercancel={endDrag}
        use:domino={{ step: 45, variant: "plug", sound: "seat", soundAt: 120, level: 0.85, once: true }}>
      {#each chain as e, i (key(e))}
        {@const st = status(e)}
        {@const t = tried[key(e)]}
        {@const used = $lastUse[usageKey(e.provider, e.model)]}
        {@const today = usageFor($usage, e.provider, e.model)?.jobs?.replies ?? 0}
        <li class="mp-row" class:is-drag={dragging === i} bind:this={rows[i]} animate:flip={{ duration: 220 }}>
          {#if used}{#key used}<span class="mp-blink" aria-hidden="true"></span>{/key}{/if}
          <button class="mp-grip" aria-label="Move {e.model}, use the arrow keys" title="Drag to change the order" data-sound="self"
                  onpointerdown={(ev) => startDrag(i, ev)} onkeydown={(ev) => keyMove(i, ev)}>
            <Icon name="grip" size={14} />
          </button>
          <RankBadge n={i + 1} kind="step" />
          <ProviderTile id={e.provider} size={36} />
          <span class="min-w-0 flex-1">
            <span class="flex min-w-0 items-baseline gap-2">
              <span class="truncate text-[13.5px] font-medium text-ink" title={e.model}>{shortModel(e.model)}</span>
              {#if i === 0}<span class="mp-badge">first choice</span>{:else}<span class="mp-then">if the one above can't</span>{/if}
            </span>
            <span class="flex min-w-0 items-center gap-1.5 text-[11.5px]">
              <span class="text-muted">{provName(e.provider)}</span>
              <span class="mp-dot" data-tone={st.tone}></span>
              <span class={st.tone === "good" ? "text-faint" : "text-warn"} title={st.why ?? ""}>{st.text}</span>
              {#if today}<span class="mp-today" title="Replies it wrote today">· {today.toLocaleString()} today</span>{/if}
              {#if t?.ok}
                <span class="truncate text-good">· answered in {((t.ms ?? 0) / 1000).toFixed(1)}s</span>
              {:else if t}
                <span class="text-bad">· did not answer</span>
              {/if}
            </span>
            <!-- Why it did not, in full under it: cut to the row's width, "not enough memory" read as a code. -->
            {#if t && !t.ok}<span class="mp-why" title={t.detail || ""}>{t.error}</span>{/if}
          </span>
          <div class="mp-actions">
            <button class="mp-act" onclick={() => tryIt(e)} disabled={!!trying[key(e)] || st.tone !== "good"}
                    title="Send it one tiny message to see that it answers">
              <span class="inline-flex" class:animate-spin={trying[key(e)]}><Icon name={trying[key(e)] ? "refresh" : "play"} size={11} /></span>Try
            </button>
            <button class="mp-act" onclick={(e) => openChooser(i, e)} title="Pick a different model for this spot">
              <Icon name="edit" size={11} />Change
            </button>
            <button class="mp-act mp-x" onclick={() => remove(i)}
                    title={chain.length <= 1 ? "Take it off: Groq's models write replies" : "Take it out of the list"} aria-label="Remove">
              <Icon name="close" size={12} />
            </button>
          </div>
        </li>
      {/each}
    </ol>
    {#if !chain.length}
      <!-- The last one taken off: said what happens then, rather than refused. -->
      <p class="mp-none">
        <Icon name="info" size={13} />
        <span>None picked. Groq's models write replies until you add one.</span>
      </p>
    {/if}

    <div class="mp-tokens">
      <span class="min-w-0 flex-1">
        <span class="block text-[12.5px] text-ink">Longest reply</span>
        <span class="block text-[11.5px] text-faint">
          In tokens, about ¾ of a word each. Replies are cut to a few hundred characters anyway; this stops a thinking model spending its allowance on thinking.
        </span>
      </span>
      <label class="num-field">
        <input type="number" min="96" max="4096" step="16" bind:value={tokens} class="bg-transparent text-right font-mono text-[12.5px] text-ink outline-none"
               use:autowidth={{ value: tokens }} />
        <span class="text-[11px] text-faint">tokens</span>
      </label>
    </div>
  </section>

  <!-- ── The other jobs ───────────────────────────────────────────────── -->
  <section class="mp-card mt-4">
    <header class="mp-head">
      <span class="mp-head-icon"><Icon name="sparkle" size={16} /></span>
      <div class="min-w-0 flex-1">
        <h3 class="text-[14.5px] font-semibold text-ink">Everything else</h3>
        <p class="text-[12px] text-muted">
          A model for each job, with fallbacks tried in order when it fails. Groq's default is always the last resort.
        </p>
      </div>
    </header>

    <!-- Each job comes in after the one above it, and its model plugs into it from the right, a tock as it seats. -->
    <div class="mp-jobs domino" use:domino={{ step: 35, variant: "plug", sound: "seat", soundAt: 150, level: 0.65, once: true }}>
      {#each JOB_KEYS as k (k)}
        {@const eff = effective(k)}
        {@const used = eff ? $lastUse[usageKey(eff.provider, eff.model)] : 0}
        {@const today = eff ? usageFor($usage, eff.provider, eff.model)?.jobs?.[k] ?? 0 : 0}
        <div class="mp-job-wrap">
        <div class="mp-job">
          <span class="mp-job-icon"><Icon name={JOB_NAMES[k].icon} size={16} /></span>
          <span class="min-w-0 flex-1">
            <span class="block text-[13px] font-medium text-ink">{JOB_NAMES[k].title}</span>
            <span class="block truncate text-[11.5px] text-faint">{JOB_NAMES[k].hint}</span>
          </span>
          <button class="mp-choice" onclick={(e) => openChooser(k, e)} title="Choose the model for this">
            {#if used}{#key used}<span class="mp-blink" aria-hidden="true"></span>{/key}{/if}
            {#if eff}
              <ProviderTile id={eff.provider} size={24} />
              <span class="min-w-0 text-left">
                <span class="block truncate text-[12.5px] text-ink" title={eff.model}>{shortModel(eff.model)}</span>
                <span class="block truncate text-[10.5px] text-faint">
                  {provName(eff.provider)}{isDefault(k) ? " · default" : ""}{eff.voice ? ` · ${eff.voice}` : ""}{today ? ` · ${today.toLocaleString()} today` : ""}
                </span>
              </span>
            {:else}
              <span class="text-[12px] text-faint">Groq's default</span>
            {/if}
            <span class="ml-auto shrink-0 text-faint"><Icon name="chevron" size={12} /></span>
          </button>
          <!-- Always there, so every choice box lines up; only usable when set. -->
          <button class="mp-act mp-reset" class:is-hidden={isDefault(k)} onclick={() => resetJob(k)}
                  disabled={isDefault(k)} title="Back to Groq's default" aria-label="Back to Groq's default">
            <Icon name="undo" size={12} />
          </button>
        </div>
        <!-- Then, in order, what takes over when the one before it fails. -->
        <div class="mp-falls">
          {#each (jobs[k] ?? []).slice(1) as f, i (f.provider + ":" + f.model)}
            <span class="mp-fall">
              <span class="mp-then">then</span>
              <ProviderTile id={f.provider} size={18} />
              <span class="truncate" title={f.model}>{shortModel(f.model)}</span>
              <button class="mp-fall-x" onclick={() => removeFallback(k, i + 1)} aria-label="Remove this fallback"
                      title="Remove this fallback"><Icon name="close" size={10} /></button>
            </span>
          {/each}
          <button class="mp-fall-add" onclick={(e) => openFallback(k, e)}>
            <Icon name="plus" size={10} />{isDefault(k) || (jobs[k]?.length ?? 0) < 2 ? "Add a fallback" : "Another"}
          </button>
          {#if groqLast(k)}<span class="mp-then">then Groq's default</span>{/if}
        </div>
        </div>
      {/each}
    </div>
  </section>

  <div class="mt-3 flex flex-wrap gap-2">
    <button class="mp-link" onclick={() => settingsSection.set("groq/keys")}>
      <Icon name="key" size={12} />Connect more providers
    </button>
    <button class="mp-link" onclick={() => settingsSection.set("groq/local")}>
      <Icon name="monitor" size={12} />Run models on this computer
    </button>
  </div>

  {#if dirty}
    <div class="mp-save glass floating">
      <span class="text-[12.5px] text-ink">Unsaved changes to your models</span>
      <span class="ml-auto flex gap-2">
        <Button size="sm" kind="ghost" onclick={reset} disabled={saving}>Discard</Button>
        <Button size="sm" onclick={save} loading={saving}>Save</Button>
      </span>
    </div>
  {/if}
{/if}

{#if chooser}
  <ModelChooser bind:open={chooserOpen} anchor={chooser.anchor} need={chooser.need} title={chooser.title} current={chooser.current}
                exclude={chooser.exclude ?? (typeof chooser.job === "string" && chooser.job !== "add" ? [] : chain)} onpick={picked} />
{/if}

<style>
  .mp-card {
    padding: 16px;
    border-radius: 18px;
    background: rgb(255 255 255 / 0.022);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
  }
  .mp-head {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    gap: 12px;
    margin-bottom: 14px;
  }
  .mp-head-icon, .mp-job-icon {
    display: grid;
    width: 34px;
    height: 34px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 11px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 13%, transparent);
  }

  .mp-chain {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 6px;
    touch-action: none;
  }
  .mp-row {
    position: relative;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 10px 9px 4px;
    border-radius: 14px;
    background: rgb(255 255 255 / 0.025);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
    transition: box-shadow 0.18s ease, background-color 0.18s ease, transform 0.18s var(--spring);
  }
  .mp-row:hover { background: rgb(255 255 255 / 0.04); }
  /* The order a reply tries them in, drawn: a line of light from each step's number down to the next one's, and the
     first choice lit in the accent. */
  .mp-row + .mp-row::before {
    content: "";
    position: absolute;
    left: 48px;
    bottom: calc(50% + 12px);
    width: 2px;
    height: calc(100% - 16px);
    border-radius: 2px;
    background: linear-gradient(to bottom, color-mix(in srgb, var(--color-accent) 70%, transparent),
                color-mix(in srgb, var(--color-accent) 22%, transparent));
    pointer-events: none;
  }
  .mp-chain > .mp-row:first-child {
    background: color-mix(in srgb, var(--color-accent) 7%, rgb(255 255 255 / 0.02));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 30%, transparent),
                0 10px 26px -18px var(--color-accent);
  }
  .mp-row.is-drag {
    z-index: 2;
    background: color-mix(in srgb, var(--color-accent) 10%, var(--color-card));
    box-shadow: 0 14px 34px -14px rgb(0 0 0 / 0.8), inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 45%, transparent);
    transform: scale(1.012);
  }
  .mp-grip {
    display: grid;
    width: 24px;
    height: 34px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 8px;
    color: var(--color-faint);
    cursor: grab;
    touch-action: none;
  }
  .mp-grip:hover, .mp-grip:focus-visible { color: var(--color-ink); background: rgb(255 255 255 / 0.05); outline: none; }
  .mp-row.is-drag .mp-grip { cursor: grabbing; color: var(--color-accent); }
  .mp-badge {
    flex-shrink: 0;
    padding: 1px 7px;
    border-radius: 999px;
    font-size: 10px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .mp-then { flex-shrink: 0; font-size: 10.5px; color: var(--color-faint); }
  .mp-why {
    display: block;
    margin-top: 4px;
    padding: 5px 9px;
    border-radius: 9px;
    font-size: 11.5px;
    line-height: 1.45;
    color: color-mix(in srgb, var(--color-bad) 85%, white);
    background: color-mix(in srgb, var(--color-bad) 10%, transparent);
    animation: mp-why-in 0.35s var(--jelly);
  }
  @keyframes mp-why-in { from { opacity: 0; transform: translateY(-4px); } }
  :global(:root[data-motion="off"]) .mp-why { animation: none; }
  .mp-dot { width: 6px; height: 6px; flex-shrink: 0; border-radius: 999px; background: var(--color-faint); }
  .mp-dot[data-tone="good"] { background: var(--color-good); }
  .mp-dot[data-tone="warn"] { background: var(--color-warn); }
  .mp-actions {
    display: flex;
    flex-shrink: 0;
    align-items: center;
    gap: 2px;
  }
  .mp-act {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 5px 8px;
    border-radius: 8px;
    font-size: 11.5px;
    color: var(--color-muted);
    transition: color 0.14s ease, background-color 0.14s ease;
  }
  .mp-act:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.06); }
  .mp-act:disabled { opacity: 0.4; cursor: default; }
  .mp-x:hover:not(:disabled) { color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 12%, transparent); }

  .mp-tokens {
    display: flex;
    align-items: center;
    gap: 14px;
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid color-mix(in srgb, var(--color-edge) 60%, transparent);
  }

  .mp-jobs {
    display: grid;
    /* minmax(0, ...), not 1fr: a plain 1fr track is at least as wide as its
       widest unbreakable word, and a long local model name pushed every
       choice box out past the edge of the card. */
    grid-template-columns: minmax(0, 1fr);
    gap: 6px;
  }
  .mp-job {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 8px 8px 8px;
    border-radius: 14px;
    transition: background-color 0.15s ease;
  }
  .mp-job:hover { background: rgb(255 255 255 / 0.025); }
  /* A job and its fallbacks, together: they arrive as one, spaced as they were. */
  .mp-job-wrap { display: grid; grid-template-columns: minmax(0, 1fr); gap: 6px; }
  .mp-none {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 2px;
    padding: 12px 14px;
    border-radius: 14px;
    border: 1px dashed color-mix(in srgb, var(--color-edge) 90%, white 10%);
    font-size: 12.5px;
    color: var(--color-muted);
    animation: mp-none-in 0.4s var(--jelly) both;
  }
  @keyframes mp-none-in { from { opacity: 0; transform: scale(0.96); } }
  :global(:root[data-motion="off"]) .mp-none { animation: none; }

  /* ── Opening: plugged in (lib/domino.ts gives each its turn, --i) ──
     A beam of light runs across each model of the chain as it lands, then its
     light comes on; each job's model plugs in from the right a moment after
     its row. The cards' icons pop as they land. */
  .mp-chain:global(.is-in) > .mp-row:not([data-there])::after {
    content: "";
    position: absolute;
    inset: 0;
    z-index: 0;
    border-radius: inherit;
    pointer-events: none;
    opacity: 0;
    background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--color-accent) 26%, transparent), transparent) no-repeat;
    background-size: 45% 100%;
    animation: mp-beam 0.36s cubic-bezier(0.3, 0.1, 0.3, 1) backwards;
    animation-delay: calc(var(--i, 0) * var(--domino-step, 45ms) + 60ms);
  }
  @keyframes mp-beam { from { opacity: 1; background-position: -60% 0; } to { opacity: 1; background-position: 160% 0; } }
  .mp-chain:global(.is-in) > .mp-row:not([data-there]) .mp-dot {
    animation: mp-light 0.32s var(--jelly) backwards;
    animation-delay: calc(var(--i, 0) * var(--domino-step, 45ms) + 190ms);
  }
  @keyframes mp-light { from { transform: scale(0); } 50% { transform: scale(1.8); box-shadow: 0 0 10px currentColor; } }
  .mp-jobs:global(.is-in) > :not([data-there]) .mp-choice {
    animation: mp-plug 0.32s cubic-bezier(0.3, 1.4, 0.5, 1) backwards;
    animation-delay: calc(var(--i, 0) * var(--domino-step, 35ms) + 40ms);
  }
  @keyframes mp-plug { from { opacity: 0; transform: translateX(22px); } 40% { opacity: 1; } }
  .mp-jobs:global(.is-in) > :not([data-there]) .mp-job-icon {
    animation: mp-icon 0.36s var(--jelly) backwards;
    animation-delay: calc(var(--i, 0) * var(--domino-step, 35ms) + 20ms);
  }
  .mp-head-icon { animation: mp-icon 0.4s var(--jelly) backwards; }
  @keyframes mp-icon { from { opacity: 0; transform: scale(0.4) rotate(-20deg); } }
  :global(:root[data-motion="off"]) .mp-row::after,
  :global(:root[data-motion="off"]) .mp-dot,
  :global(:root[data-motion="off"]) .mp-choice,
  :global(:root[data-motion="off"]) .mp-job-icon,
  :global(:root[data-motion="off"]) .mp-head-icon { animation: none; }
  .mp-job-icon { width: 32px; height: 32px; border-radius: 10px; color: var(--color-muted); background: rgb(255 255 255 / 0.05); }
  /* The moment a model answers, its row blinks: twice, then gone. */
  .mp-blink {
    position: absolute;
    inset: 0;
    z-index: 0;
    border-radius: inherit;
    pointer-events: none;
    box-shadow:
      inset 0 0 0 1.5px color-mix(in srgb, var(--color-accent) 75%, transparent),
      0 0 18px -2px color-mix(in srgb, var(--color-accent) 45%, transparent);
    background: color-mix(in srgb, var(--color-accent) 9%, transparent);
    animation: mp-blink 1.7s ease-out forwards;
  }
  @keyframes mp-blink {
    0% { opacity: 0; }
    10% { opacity: 1; }
    32% { opacity: 0.2; }
    52% { opacity: 1; }
    100% { opacity: 0; }
  }
  :global(:root[data-motion="off"]) .mp-blink { animation-duration: 0.9s; animation-name: mp-blink-once; }
  @keyframes mp-blink-once { 0%, 60% { opacity: 1; } 100% { opacity: 0; } }
  .mp-today { flex-shrink: 0; color: var(--color-faint); font-variant-numeric: tabular-nums; }
  .mp-choice {
    position: relative;
    display: flex;
    width: min(270px, 46%);
    min-width: 0;
    flex-shrink: 0;
    align-items: center;
    gap: 9px;
    padding: 6px 10px 6px 7px;
    border-radius: 11px;
    background: rgb(0 0 0 / 0.2);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    transition: box-shadow 0.16s ease;
  }
  .mp-choice:hover { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 50%, var(--color-edge)); }
  .mp-reset { padding: 6px; }
  .mp-falls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    margin: -2px 0 8px 52px;
  }
  .mp-fall {
    display: inline-flex;
    max-width: 240px;
    align-items: center;
    gap: 6px;
    padding: 3px 4px 3px 8px;
    border-radius: 999px;
    font-size: 11.5px;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
  }
  .mp-fall .mp-then { margin-right: 1px; }
  .mp-fall-x {
    display: grid;
    width: 18px;
    height: 18px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    color: var(--color-faint);
  }
  .mp-fall-x:hover { color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 14%, transparent); }
  .mp-fall-add {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 9px;
    border-radius: 999px;
    font-size: 11px;
    color: var(--color-muted);
    border: 1px dashed color-mix(in srgb, var(--color-edge) 100%, transparent);
    transition: color 0.15s ease, border-color 0.15s ease;
  }
  .mp-fall-add:hover { color: var(--color-accent); border-color: color-mix(in srgb, var(--color-accent) 55%, transparent); }
  .mp-reset.is-hidden { visibility: hidden; }
  .mp-link {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 11px;
    border-radius: 10px;
    font-size: 12px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    transition: color 0.14s ease, background-color 0.14s ease;
  }
  .mp-link:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.06); }

  .mp-save {
    position: sticky;
    bottom: 12px;
    z-index: 5;
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 16px;
    padding: 10px 12px 10px 16px;
    border-radius: 14px;
    animation: mp-in 0.3s var(--spring) both;
  }
  @keyframes mp-in {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: none; }
  }
  @media (max-width: 640px) {
    .mp-row { flex-wrap: wrap; padding-left: 8px; }
    .mp-actions { width: 100%; justify-content: flex-end; }
    .mp-job { flex-wrap: wrap; }
    .mp-choice { width: 100%; }
  }
  :global(:root[data-motion="off"]) .mp-save { animation: none; }
</style>
