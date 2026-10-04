<script lang="ts">
  /**
   * Where models come from. One card per provider: what it can do, whether it
   * is connected, and the key box. Connecting one does not change anything on
   * its own; its models become choosable under Models.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import { toast, settingsSection } from "../stores";
  import { loadProviders, providerList, providersLoaded, TINT, type Provider } from "../providers";
  import { domino } from "../domino";
  import Icon from "./Icon.svelte";
  import KeyForm from "./KeyForm.svelte";
  import ProviderTile from "./ProviderTile.svelte";
  import EnvEditor from "./EnvEditor.svelte";

  onMount(() => {
    loadProviders().catch((e) => toast(e?.message || "Could not load the providers", "err"));
  });

  let open = $state<Record<string, boolean>>({});
  let removing = $state<Record<string, boolean>>({});
  let groqKeys = $state(false);

  const CAN: Record<string, string> = { chat: "Writes", vision: "Sees", stt: "Hears", tts: "Speaks" };

  const connected = $derived($providerList.filter((p) => p.ready));
  const others = $derived($providerList.filter((p) => !p.ready));

  async function remove(p: Provider) {
    removing[p.id] = true;
    try {
      await api.providerKey(p.id, "");
      await loadProviders();
      toast(`${p.name} is disconnected. Anything that used it falls through to the next model.`, "ok");
    } catch (e: any) {
      toast(e?.message || "Could not remove it", "err");
    } finally {
      delete removing[p.id];
    }
  }
</script>

{#snippet card(p: Provider)}
  <!-- Lit in its own colour, a check on its mark once connected. -->
  <div class="pp-card" class:is-ready={p.ready} style="--tint: {TINT[p.id] ?? 'var(--color-accent)'}">
    <div class="flex items-start gap-3">
      <span class="pp-tile">
        <ProviderTile id={p.id} size={40} />
        {#if p.ready}<span class="pp-ok"><Icon name="check" size={10} /></span>{/if}
      </span>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span class="text-[14px] font-semibold text-ink">{p.name}</span>
          {#if p.ready}
            <span class="pp-pill is-good">
              <span class="pp-dot"></span>
              {p.id === "local" ? "on this computer" : p.multi && p.keys > 1 ? `${p.keys} keys` : "connected"}
            </span>
          {/if}
        </div>
        <p class="mt-0.5 text-[12px] leading-relaxed text-muted">{p.blurb}</p>
        <div class="mt-2 flex flex-wrap gap-1">
          {#each p.jobs as j}<span class="pp-can">{CAN[j]}</span>{/each}
        </div>
      </div>
    </div>

    <div class="mt-3">
      {#if p.id === "local"}
        <button class="pp-link" onclick={() => settingsSection.set("groq/local")}>
          Find a server and download models <Icon name="chevron" size={11} />
        </button>
      {:else if !p.ready}
        <KeyForm provider={p} label="Connect" />
      {:else if open[p.id]}
        <KeyForm provider={p} label={p.multi ? "Add key" : "Replace"} onsaved={() => (open[p.id] = false)} />
      {:else}
        <div class="flex flex-wrap items-center gap-1">
          <button class="pp-link" onclick={() => (open[p.id] = true)}>
            <Icon name={p.multi ? "plus" : "key"} size={11} />{p.multi ? "Add another key" : "Replace key"}
          </button>
          {#if p.multi}
            <button class="pp-link" onclick={() => (groqKeys = !groqKeys)}>
              <Icon name="edit" size={11} />{groqKeys ? "Hide keys" : "Manage keys"}
            </button>
          {:else}
            <button class="pp-link pp-danger" onclick={() => remove(p)} disabled={!!removing[p.id]}>
              <Icon name="trash" size={11} />Disconnect
            </button>
          {/if}
          <a class="pp-link ml-auto" href={p.site} target="_blank" rel="noopener noreferrer">
            Dashboard <Icon name="external" size={10} />
          </a>
        </div>
      {/if}
      {#if p.multi && groqKeys}
        <div class="mt-3 rounded-xl bg-black/20 p-3">
          <p class="mb-2 text-[11.5px] text-faint">
            When one key hits its rate limit the next one takes over, before moving on to the next model.
          </p>
          <EnvEditor sections={["Groq API"]} keyLists={["groq"]} extras={false} />
        </div>
      {/if}
    </div>
  </div>
{/snippet}

{#if !$providersLoaded}
  <div class="grid gap-3 sm:grid-cols-2">
    {#each Array(6) as _}<div class="h-40 animate-pulse rounded-2xl bg-white/[0.03]"></div>{/each}
  </div>
{:else}
  <!-- The cards come in one after another as the tab opens, a soft note each (lib/domino.ts). -->
  {#if connected.length}
    <h3 class="pp-h">Connected <span>{connected.length}</span></h3>
    <div class="grid gap-3 lg:grid-cols-2 domino" use:domino={{ step: 32, sound: "pluck", level: 0.5, once: true }}>
      {#each connected as p (p.id)}{@render card(p)}{/each}
    </div>
  {/if}

  <h3 class="pp-h mt-6">Add a provider <span>{others.length}</span></h3>
  <p class="-mt-1 mb-3 text-[12px] text-muted">
    Paste a key and its models show up under Models. Keys stay in .env on this computer.
  </p>
  <div class="grid gap-3 lg:grid-cols-2 domino" use:domino={{ step: 24, sound: "wind", level: 0.45, once: true }}>
    {#each others as p (p.id)}{@render card(p)}{/each}
  </div>
{/if}

<style>
  .pp-h {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--color-faint);
  }
  .pp-h span {
    padding: 0 6px;
    border-radius: 999px;
    font-size: 10.5px;
    letter-spacing: 0;
    background: rgb(255 255 255 / 0.06);
  }
  .pp-card {
    padding: 14px;
    border-radius: 16px;
    background:
      radial-gradient(90% 120% at 0% 0%, color-mix(in srgb, var(--tint) 7%, transparent), transparent 60%),
      rgb(255 255 255 / 0.022);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    transition: box-shadow 0.2s ease, background-color 0.18s ease, transform 0.3s var(--jelly);
  }
  .pp-card:hover { transform: translateY(-1px); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--tint) 35%, var(--color-edge)); }
  /* Connected: its own colour comes up through it. */
  .pp-card.is-ready {
    background:
      radial-gradient(90% 130% at 0% 0%, color-mix(in srgb, var(--tint) 18%, transparent), transparent 65%),
      rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--tint) 30%, var(--color-edge)),
                0 14px 32px -22px var(--tint);
  }
  .pp-tile { position: relative; flex-shrink: 0; }
  .pp-ok {
    position: absolute;
    right: -4px;
    bottom: -4px;
    display: grid;
    place-items: center;
    width: 18px;
    height: 18px;
    border-radius: 999px;
    color: var(--color-bg);
    background: var(--color-good);
    box-shadow: 0 0 0 2px var(--color-card);
    animation: pp-ok-in 0.45s var(--jelly) 0.25s backwards;
  }
  @keyframes pp-ok-in { from { transform: scale(0); } }
  :global(:root[data-motion="off"]) .pp-ok { animation: none; }
  .pp-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 1px 8px;
    border-radius: 999px;
    font-size: 10.5px;
  }
  .pp-pill.is-good { color: var(--color-good); background: color-mix(in srgb, var(--color-good) 12%, transparent); }
  .pp-dot { width: 6px; height: 6px; border-radius: 999px; background: currentColor; }
  .pp-can {
    padding: 1px 7px;
    border-radius: 999px;
    font-size: 10.5px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
  }
  .pp-link {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 5px 9px;
    border-radius: 8px;
    font-size: 11.5px;
    color: var(--color-muted);
    transition: color 0.14s ease, background-color 0.14s ease;
  }
  .pp-link:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.06); }
  .pp-danger:hover:not(:disabled) { color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 12%, transparent); }
</style>
