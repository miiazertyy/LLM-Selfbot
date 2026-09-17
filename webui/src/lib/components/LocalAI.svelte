<script lang="ts">
  /**
   * Running the brain on this machine instead of sending it to Groq.
   *
   * The app does not run the model itself, it talks to something that does:
   * Ollama, LM Studio, llama.cpp's server, vLLM. app/utils/localai.py explains
   * why that is the right shape rather than a compromise. This page hides the
   * plumbing: it looks for a server, offers what that server already has, and
   * can fetch a new model by name, HuggingFace names included.
   */
  import { onMount, onDestroy } from "svelte";
  import { api } from "../api";
  import { resource } from "../resource";
  import { get } from "svelte/store";
  import { toast } from "../stores";
  import Button from "./Button.svelte";
  import Toggle from "./Toggle.svelte";
  import Icon from "./Icon.svelte";

  type Server = {
    id: string; name: string; root: string; site: string;
    can_pull: boolean; running: boolean; models: string[]; base_url: string;
  };
  type Pull = {
    active: boolean; model: string; status: string;
    percent: number; done: number; total: number; error: string;
  };

  let servers = $state<Server[]>([]);
  let models = $state<string[]>([]);
  let reachable = $state(false);
  let probeError = $state("");
  let canPull = $state(false);
  let modelMissing = $state(false);
  let pull = $state<Pull | null>(null);

  let enabled = $state(false);
  let baseUrl = $state("");
  let model = $state("");
  let vision = $state(false);

  let loading = $state(true);
  let saving = $state(false);
  let checking = $state(false);
  let pullName = $state("");
  let stored = $state("");

  const dirty = $derived(
    !loading && JSON.stringify({ enabled, baseUrl, model, vision }) !== stored,
  );
  const running = $derived(servers.filter((s) => s.running));

  let timer: any = null;

  // Both of these probe network endpoints that wait out their own timeouts when
  // nothing is listening, and the subtab remounts every time it is opened. They
  // ran one after the other, uncached, so leaving and coming back cost the full
  // round again. Cached and concurrent: a return visit paints from what is
  // already held and revalidates behind it.
  const statusRes = resource("localStatus", () => api.localStatus(), null as any);
  const detectRes = resource("localDetect", () => api.localDetect(), null as any);

  onMount(async () => {
    // Only show the skeleton when there is genuinely nothing to show.
    loading = !get(statusRes).data;
    await Promise.all([load(), refresh()]);
    loading = false;
  });
  onDestroy(() => clearInterval(timer));

  function apply(s: any) {
    enabled = s.settings.enabled;
    baseUrl = s.settings.base_url;
    model = s.settings.model;
    vision = s.settings.vision;
    reachable = s.reachable;
    probeError = s.error || "";
    models = s.models || [];
    canPull = s.can_pull;
    modelMissing = s.model_missing;
    pull = s.pull;
    stored = JSON.stringify({ enabled, baseUrl, model, vision });
    watchPull();
  }

  async function load(force = false) {
    // Paint from whatever is already held before touching the network. Both
    // endpoints probe a server that is usually not there, so each waits out its
    // own timeout, and this subtab remounts every single time it is opened -
    // which is why leaving and coming back used to mean sitting through the
    // whole round again. A stale answer on screen while the fresh one arrives
    // is the right trade for something that changes this rarely.
    const held = !force && get(statusRes).data;
    if (held) apply(held);

    try {
      const s = await statusRes.refresh(force ? { force: true } : { maxAge: 20000 });
      if (s) apply(s);
    } catch (e: any) {
      if (!held) toast(e?.message || "Could not read the local settings", "err");
    }
  }

  /** Look for servers that are running, so nothing has to be typed. */
  async function refresh(force = false) {
    const held = !force && get(detectRes).data;
    if (held) servers = held.servers || [];
    try {
      const d = await detectRes.refresh(force ? { force: true } : { maxAge: 20000 });
      if (d) servers = d.servers || [];
    } catch {
      if (!held) servers = [];
    }
  }

  function use(s: Server) {
    baseUrl = s.base_url;
    models = s.models;
    reachable = true;
    probeError = "";
    canPull = s.can_pull;
    if (!model && s.models.length) model = s.models[0];
  }

  async function check() {
    checking = true;
    try {
      const r = await api.localProbe(baseUrl);
      baseUrl = r.base_url;
      reachable = r.ok;
      models = r.models || [];
      probeError = r.error || "";
      toast(r.ok ? `Found ${r.models.length} model(s).` : r.error, r.ok ? "ok" : "err");
    } catch (e: any) {
      toast(e?.message || "Could not reach it", "err");
    }
    checking = false;
  }

  async function save() {
    if (enabled && !model) {
      toast("Pick a model first, or it has nothing to run.", "err");
      return;
    }
    saving = true;
    try {
      await api.configField("bot.local.base_url", baseUrl);
      await api.configField("bot.local.model", model);
      await api.configField("bot.local.vision", vision);
      await api.configField("bot.local.enabled", enabled);
      stored = JSON.stringify({ enabled, baseUrl, model, vision });
      toast(
        enabled
          ? "Saved. Restart the accounts to switch them over."
          : "Saved. Replies go to Groq again after a restart.",
        "ok",
      );
      await load(true);
    } catch (e: any) {
      toast(e?.message || "Could not save", "err");
    }
    saving = false;
  }

  async function startPull() {
    const name = pullName.trim();
    if (!name) return;
    try {
      const r = await api.localPull(name, baseUrl);
      toast(`Downloading ${r.model}. It can take a while.`, "info");
      pullName = "";
      watchPull(true);
    } catch (e: any) {
      toast(e?.message || "Could not start the download", "err");
    }
  }

  /** Poll only while something is actually downloading. */
  function watchPull(force = false) {
    clearInterval(timer);
    if (!force && !pull?.active) return;
    timer = setInterval(async () => {
      try {
        pull = await api.localPullStatus();
        if (!pull!.active) {
          clearInterval(timer);
          if (pull!.error) toast(pull!.error, "err");
          else {
            toast(`${pull!.model} is ready.`, "ok");
            await check();
            if (!model) model = pull!.model;
          }
        }
      } catch {
        clearInterval(timer);
      }
    }, 1200);
  }

  const gb = (n: number) => (n > 0 ? `${(n / 1e9).toFixed(1)} GB` : "");
</script>

{#if loading}
  <div class="space-y-2">
    {#each Array(4) as _}<div class="h-12 animate-pulse rounded-lg bg-white/[0.03]"></div>{/each}
  </div>
{:else}
  <!-- What this actually does, because "local models" means several different
       things and the limits matter before anyone turns it on. -->
  <p class="mb-4 text-[12px] leading-relaxed text-faint">
    Replies get written on this machine instead of by Groq: no rate limits, no
    key, and nothing leaves the computer. The app does not run the model itself,
    it talks to a server that does. Voice messages still need a Groq key, and so
    do images unless the model you pick can see.
  </p>

  <!-- ── Servers found ────────────────────────────────────────────────────── -->
  <section class="mb-6">
    <div class="mb-2 flex items-center justify-between">
      <h3 class="text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
        Servers on this machine
      </h3>
      <Button kind="ghost" size="sm" onclick={refresh}>
        <Icon name="refresh" size={12} /> Look again
      </Button>
    </div>

    {#if !running.length}
      <div class="rounded-xl border border-warn/40 bg-warn/[0.06] px-4 py-3">
        <div class="text-[13px] text-ink">Nothing is running yet</div>
        <p class="mt-1 text-[11px] leading-relaxed text-muted">
          Install one and leave it running, then press Look again. Ollama is the
          easiest, and it is the only one here that can download a model for you.
        </p>
        <div class="mt-2 flex flex-wrap gap-2">
          {#each servers as s}
            <a
              href={s.site}
              target="_blank"
              rel="noopener"
              class="jelly rounded-lg border border-edge px-2.5 py-1 text-[11px] text-muted hover:border-accent/50 hover:text-ink"
            >{s.name}</a>
          {/each}
        </div>
      </div>
    {:else}
      <div class="space-y-2">
        {#each running as s (s.id)}
          <button
            onclick={() => use(s)}
            class="jelly flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left
              {baseUrl === s.base_url
                ? 'border-accent/60 bg-accent/10'
                : 'border-edge hover:bg-white/[0.04]'}"
          >
            <span class="h-2 w-2 shrink-0 rounded-full bg-good"></span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[13px] text-ink">{s.name}</span>
              <span class="block truncate text-[11px] text-faint">
                {s.models.length} model{s.models.length === 1 ? "" : "s"} · {s.root}
              </span>
            </span>
            {#if s.can_pull}
              <span class="shrink-0 rounded bg-accent/15 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-accent">
                can download
              </span>
            {/if}
          </button>
        {/each}
      </div>
    {/if}
  </section>

  <!-- ── Download a model ─────────────────────────────────────────────────── -->
  {#if canPull}
    <section class="mb-6">
      <h3 class="mb-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
        Get a model
      </h3>
      <p class="mb-2 text-[11px] leading-relaxed text-faint">
        An Ollama name like <span class="font-mono text-ink/70">llama3.1:8b</span>, or a
        HuggingFace repo like <span class="font-mono text-ink/70">openai/gpt-oss-20b</span>,
        which is fetched straight from HuggingFace. A 7-8B model is the realistic
        size for a desktop and is several gigabytes.
      </p>
      <div class="flex flex-col gap-2 sm:flex-row">
        <input
          bind:value={pullName}
          placeholder="llama3.1:8b"
          spellcheck="false"
          disabled={pull?.active}
          onkeydown={(e) => e.key === "Enter" && startPull()}
          class="field font-mono text-[12px]"
        />
        <Button size="sm" onclick={startPull} disabled={!pullName.trim() || pull?.active}>
          Download
        </Button>
      </div>

      {#if pull?.active}
        <div class="mt-3 rounded-xl border border-edge bg-black/20 px-3 py-2.5">
          <div class="flex items-center justify-between text-[12px]">
            <span class="min-w-0 truncate font-mono text-ink">{pull.model}</span>
            <span class="shrink-0 text-faint">
              {pull.status}{pull.total ? ` · ${gb(pull.done)} of ${gb(pull.total)}` : ""}
            </span>
          </div>
          <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
            <div
              class="h-full rounded-full bg-accent transition-[width] duration-300"
              style="width: {pull.percent}%"
            ></div>
          </div>
        </div>
      {:else if pull?.error}
        <p class="mt-2 text-[11px] text-bad">{pull.error}</p>
      {/if}
    </section>
  {/if}

  <!-- ── Where it is, and which model ─────────────────────────────────────── -->
  <section class="mb-6">
    <h3 class="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
      Server address
    </h3>
    <div class="flex flex-col gap-2 sm:flex-row">
      <input
        bind:value={baseUrl}
        placeholder="http://127.0.0.1:11434/v1"
        spellcheck="false"
        class="field font-mono text-[12px]"
      />
      <Button kind="ghost" size="sm" onclick={check} loading={checking}>Test</Button>
    </div>
    {#if probeError && !reachable}
      <p class="mt-1.5 text-[11px] text-bad">{probeError}</p>
    {:else if reachable}
      <p class="mt-1.5 text-[11px] text-good">
        Answering, with {models.length} model{models.length === 1 ? "" : "s"}.
      </p>
    {/if}

    <h3 class="mb-2 mt-5 text-[11px] font-semibold uppercase tracking-[0.14em] text-faint">
      Model
    </h3>
    {#if models.length}
      <select bind:value={model} class="field w-full text-[12px]">
        <option value="">Pick one</option>
        {#each models as m}
          <option value={m}>{m}</option>
        {/each}
      </select>
    {:else}
      <input
        bind:value={model}
        placeholder="the model name on that server"
        spellcheck="false"
        class="field font-mono text-[12px]"
      />
    {/if}
    {#if modelMissing}
      <p class="mt-1.5 text-[11px] text-warn">
        That server does not have "{model}". Every reply would fail with a 404.
      </p>
    {/if}
  </section>

  <!-- ── The switch ───────────────────────────────────────────────────────── -->
  <div class="divide-y divide-edge/60 border-t border-edge/60">
    <div class="flex items-center gap-4 py-3">
      <div class="min-w-0 flex-1">
        <div class="text-[13px] text-ink">Write replies here, not on Groq</div>
        <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
          If the server stops, replies stop. They are not quietly sent to Groq
          instead, because that is the one thing turning this on was meant to
          avoid. The logs say when it happens.
        </p>
      </div>
      <Toggle checked={enabled} onchange={(v) => (enabled = v)} />
    </div>

    <div class="flex items-center gap-4 py-3 {enabled ? '' : 'pointer-events-none opacity-40'}">
      <div class="min-w-0 flex-1">
        <div class="text-[13px] text-ink">Use it for images too</div>
        <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
          Only if the model you picked can actually see. A text model handed a
          picture does not say it cannot read it, it describes something that was
          never there.
        </p>
      </div>
      <Toggle checked={vision} onchange={(v) => (vision = v)} />
    </div>
  </div>

  <div class="mt-4 flex items-center gap-2">
    <Button size="sm" onclick={save} loading={saving} disabled={!dirty}>
      {dirty ? "Save changes" : "Saved"}
    </Button>
    {#if dirty}
      <Button kind="ghost" size="sm" onclick={() => { loading = true; load(true).then(() => (loading = false)); }}>
        Revert
      </Button>
    {/if}
    <span class="text-[11px] text-faint">Accounts pick this up when they restart.</span>
  </div>
{/if}
