<script lang="ts">
  /**
   * Settings > App > MCP: what to paste into an AI app so it can work on the settings (app/utils/mcpserver.py), what
   * it can't touch, and every change an AI has made, each with its Undo.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import { copyText } from "../contextmenu";
  import { whenSent } from "../fmt";
  import { toast } from "../stores";
  import { play } from "../uisound";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";

  type Change = { id: string; ts: number; who: string; label: string; scope: string; before: string; after: string; undone: boolean };

  let { onchanged }: { onchanged: () => void } = $props();

  let config = $state("");
  let available = $state(true);
  let changes = $state<Change[]>([]);

  async function loadChanges() {
    if (document.visibilityState !== "visible") return;
    try {
      changes = (await api.aiChanges()).changes;
    } catch {
      /* the next round tries again */
    }
  }

  onMount(() => {
    api.aiConnect().then((c: any) => {
      available = c.available;
      config = c.config ?? "";
    }).catch(() => {});
    loadChanges();
    const timer = setInterval(loadChanges, 5000);
    return () => clearInterval(timer);
  });

  async function undo(id: string) {
    try {
      await api.aiUndo(id);
      play("undo");
      onchanged();
    } catch (e: any) {
      play("err");
      toast(e.message, "err");
    }
    loadChanges();
  }
</script>

{#if available}
  <div class="settings-card">
    <div class="settings-row flex flex-wrap items-center gap-4">
      <div class="min-w-0 flex-1">
        <div class="text-[13.5px] font-medium text-ink">MCP server</div>
        <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
          Paste this into an AI app's MCP settings. Works while this app is open.
        </p>
      </div>
      <Button kind="ghost" size="sm" disabled={!config} onclick={() => copyText(config, "Copied.")}>
        <Icon name="copy" size={12} />Copy
      </Button>
    </div>
    <div class="settings-row">
      <pre class="ai-config">{config}</pre>
    </div>
    <div class="settings-row">
      <p class="text-[11px] leading-relaxed text-faint">
        It can change settings and personas. It can't read chats, memory, keys or logins, and it can't send or post anything.
      </p>
    </div>
  </div>
{/if}

<div class="settings-card" class:mt-4={available}>
  <div class="settings-row">
    <div class="text-[13.5px] font-medium text-ink">Changes by AI</div>
  </div>
  {#each changes as c (c.id)}
    <div class="settings-row flex items-center gap-3" class:is-undone={c.undone}>
      <div class="min-w-0 flex-1">
        <div class="ai-label text-[13px] text-ink">{c.label}</div>
        <p class="ai-meta mt-0.5 text-[11px] leading-relaxed text-faint">
          {c.who}, {whenSent(c.ts)}{c.before || c.after ? `. ${c.before} to ${c.after}` : ""}{(c.before || c.after) && c.scope !== "everyone" ? `, for ${c.scope}` : ""}
        </p>
      </div>
      {#if c.undone}
        <span class="shrink-0 text-[11px] text-faint">Undone</span>
      {:else}
        <span class="shrink-0" data-sound="self"><Button kind="ghost" size="sm" onclick={() => undo(c.id)}>Undo</Button></span>
      {/if}
    </div>
  {:else}
    <div class="settings-row">
      <p class="text-[12px] text-faint">Nothing yet.</p>
    </div>
  {/each}
</div>

<style>
  .ai-config {
    margin: 0;
    padding: 11px 13px;
    border-radius: 11px;
    background: rgb(0 0 0 / 0.22);
    color: var(--color-muted);
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 11.5px;
    line-height: 1.55;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    user-select: text;
  }
  .is-undone .ai-label {
    color: var(--color-faint);
  }
  .ai-meta {
    overflow-wrap: anywhere;
  }
</style>
