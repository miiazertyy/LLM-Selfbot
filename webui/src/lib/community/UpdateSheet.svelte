<script lang="ts">
  /**
   * What a newer version of a community profile you have would change, before it does: its notes, how much of the
   * text, which settings. If you changed the profile since you added it, that is said first; the old text and
   * settings are kept in backups either way.
   */
  import Modal from "../components/Modal.svelte";
  import Button from "../components/Button.svelte";
  import Icon from "../components/Icon.svelte";
  import { api } from "../api";
  import { play } from "../uisound";
  import { toast } from "../stores";
  import { valueText } from "./logic";

  let { pid = $bindable(""), onupdated }: { pid?: string; onupdated?: () => void } = $props();

  let pv = $state<any>(null);
  let error = $state("");
  let busy = $state(false);
  const open = $derived(!!pid);
  let loadedFor = "";
  $effect(() => {
    const id = pid;
    if (!id || id === loadedFor) return;
    loadedFor = id;
    pv = null;
    error = "";
    api.communityUpdatePreview(id).then((d) => { if (pid === id) pv = d; })
      .catch((e: any) => { if (pid === id) error = e?.message || "It couldn't be checked."; });
  });

  function close() {
    pid = "";
    loadedFor = "";
  }

  async function apply() {
    busy = true;
    try {
      await api.communityUpdate(pid, !!pv?.edited);
      play("done");
      play("settle", { delay: 220 });
      toast(`Updated to v${pv.to}.`, "ok");
      onupdated?.();
      close();
    } catch (e: any) {
      play("err", { level: 0.6 });
      toast(e?.message || "It couldn't be updated.", "err");
    } finally {
      busy = false;
    }
  }
</script>

<Modal {open} title={pv ? `What v${pv.to} changes` : "Update"} onclose={close}>
  {#if error}
    <p class="us-error">{error}</p>
  {:else if !pv}
    <p class="us-wait">Checking what changed</p>
  {:else}
    <div class="us">
      {#if pv.notes.length}
        <ul class="us-notes">
          {#each pv.notes as n (n.version)}<li><b>v{n.version}</b>{n.note || "No note"}</li>{/each}
        </ul>
      {/if}
      <p class="us-line"><Icon name="persona" size={12} />
        {#if pv.text.changed}Its text: {pv.text.added} lines new, {pv.text.removed} gone.{:else}Its text stays the same.{/if}
      </p>
      {#if pv.settings.length}
        <ul class="us-settings">
          {#each pv.settings as s (s.key)}
            <li><span>{s.label}</span><small>{valueText(s.old)}</small><Icon name="chevron" size={10} /><b>{valueText(s.new)}</b></li>
          {/each}
        </ul>
      {:else}
        <p class="us-line"><Icon name="settings" size={12} />Its settings stay the same.</p>
      {/if}
      {#if pv.face_kept}<p class="us-line"><Icon name="check" size={12} />The face you gave it stays.</p>{/if}
      {#if pv.edited}
        <p class="us-warn"><Icon name="alert" size={12} />You changed this profile since you added it. Updating replaces those changes; the old text and settings are kept in backups.</p>
      {/if}
      <div class="us-actions">
        <Button kind="ghost" size="sm" onclick={() => { play("off"); close(); }}>Not now</Button>
        <Button size="sm" onclick={apply} loading={busy}>{pv.edited ? "Replace and update" : `Update to v${pv.to}`}</Button>
      </div>
    </div>
  {/if}
</Modal>

<style>
  .us { display: flex; flex-direction: column; gap: 10px; }
  .us-notes { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; font-size: 13px; color: var(--color-muted); }
  .us-notes b { margin-right: 8px; color: var(--color-accent); }
  .us-line { display: flex; align-items: center; gap: 7px; margin: 0; font-size: 12.5px; color: var(--color-muted); }
  .us-settings { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; }
  .us-settings li { display: grid; grid-template-columns: minmax(0, 1fr) auto auto auto; align-items: center; gap: 8px;
                    padding: 6px 10px; border-radius: 10px; font-size: 12.5px; color: var(--color-ink); background: rgb(255 255 255 / 0.03); }
  .us-settings small { color: var(--color-faint); }
  .us-settings b { color: var(--color-accent); font-weight: 600; }
  .us-warn { display: flex; gap: 7px; margin: 0; padding: 10px 12px; border-radius: 12px; font-size: 12.5px; color: var(--color-ink);
             background: color-mix(in srgb, var(--color-warn) 12%, transparent); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-warn) 35%, transparent); }
  .us-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
  .us-wait { font-size: 13px; color: var(--color-faint); }
  .us-error { font-size: 13px; color: var(--color-bad); }
</style>
