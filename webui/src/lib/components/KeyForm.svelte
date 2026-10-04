<script lang="ts">
  /**
   * Paste a provider's API key. It goes to .env on this computer, like the
   * Discord tokens, and is never sent back to the page afterwards.
   */
  import { api } from "../api";
  import { toast } from "../stores";
  import { loadProviders, type Provider } from "../providers";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";

  let { provider, compact = false, label = "", onsaved }: {
    provider: Provider;
    compact?: boolean;
    /** Button text; "Save key" by default. */
    label?: string;
    onsaved?: () => void;
  } = $props();

  let key = $state("");
  let saving = $state(false);

  async function save() {
    const k = key.trim();
    if (!k) return;
    saving = true;
    try {
      await api.providerKey(provider.id, k);
      key = "";
      await loadProviders();
      toast(`${provider.name} is connected.`, "ok");
      onsaved?.();
    } catch (e: any) {
      toast(e?.message || "Could not save the key", "err");
    } finally {
      saving = false;
    }
  }
</script>

<div class="flex flex-col gap-2 {compact ? '' : 'sm:flex-row'}">
  <input
    type="password"
    bind:value={key}
    placeholder="Paste the API key"
    autocomplete="off"
    spellcheck="false"
    onkeydown={(e) => e.key === "Enter" && save()}
    class="field min-w-0 flex-1 font-mono text-[12px]"
  />
  <div class="flex shrink-0 items-center gap-2">
    <Button size="sm" onclick={save} loading={saving} disabled={!key.trim()}>{label || "Save key"}</Button>
    <a href={provider.site} target="_blank" rel="noopener noreferrer"
       class="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11.5px] text-muted hover:bg-white/[0.05] hover:text-ink">
      Get a key <Icon name="external" size={11} />
    </a>
  </div>
</div>
