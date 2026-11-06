<script lang="ts">
  /**
   * For moderators (the repo's owner): open reports and the latest requests, with who sent them, and the commands:
   * take a profile down, ban its author, unban, pause or resume sending. Each command is posted for the repo's
   * workflow to carry out, as a comment on GitHub under your name.
   */
  import { onMount } from "svelte";
  import Button from "../components/Button.svelte";
  import Icon from "../components/Icon.svelte";
  import { api } from "../api";
  import { ask } from "../ask";
  import { play } from "../uisound";
  import { toast } from "../stores";
  import { openGitHub } from "../window";
  import { timeAgo } from "./logic";

  let q = $state<{ reports: any[]; requests: any[] } | null>(null);
  let error = $state("");
  let target = $state("");
  let reason = $state("");
  let busy = $state("");

  async function load() {
    try {
      q = await api.communityQueue();
      error = "";
    } catch (e: any) {
      error = e?.message || "It couldn't be loaded.";
    }
  }
  onMount(load);

  function slugOf(title: string): string {
    const m = /\(([a-z0-9-]{3,32})\)\s*$/.exec(title) || /:\s*([a-z0-9-]{3,32})\s*$/.exec(title);
    return m ? m[1] : "";
  }

  async function run(command: string, what = target, number = 0) {
    const t = what.trim();
    if (["takedown", "ban", "unban", "restore"].includes(command) && !t) {
      play("err", { level: 0.4 });
      toast("Say which profile (or @login for a ban).", "info");
      return;
    }
    const words: Record<string, string> = { takedown: `Take down ${t}?`, ban: `Ban the author of ${t}?`, unban: `Unban ${t}?`,
                                            restore: `Bring ${t} back?`, close: "Pause sending for everyone?", open: "Open sending again?" };
    if (!(await ask(words[command], { yes: "Do it", danger: command === "takedown" || command === "ban" }))) return;
    busy = command;
    try {
      await api.communityModerate(command, t, reason, number);
      play(command === "takedown" || command === "ban" ? "delete" : command === "close" ? "off" : "medal");
      toast("Sent. The repo does it in a minute.", "ok");
      reason = "";
    } catch (e: any) {
      play("err", { level: 0.6 });
      toast(e?.message || "It didn't go.", "err");
    } finally {
      busy = "";
    }
  }
</script>

<div class="md">
  <div class="md-tools">
    <input bind:value={target} placeholder="Profile short name, or @login" aria-label="Which profile or author" />
    <input bind:value={reason} placeholder="Why (optional)" aria-label="Why" maxlength="200" />
    <Button size="sm" kind="danger" loading={busy === "takedown"} onclick={() => run("takedown")}>Take down</Button>
    <Button size="sm" kind="ghost" loading={busy === "restore"} onclick={() => run("restore")}>Restore</Button>
    <Button size="sm" kind="danger" loading={busy === "ban"} onclick={() => run("ban")}>Ban</Button>
    <Button size="sm" kind="ghost" loading={busy === "unban"} onclick={() => run("unban")}>Unban</Button>
    <span class="md-grow"></span>
    <Button size="sm" kind="ghost" loading={busy === "close"} onclick={() => run("close", "")}>Pause sending</Button>
    <Button size="sm" kind="ghost" loading={busy === "open"} onclick={() => run("open", "")}>Open sending</Button>
  </div>
  {#if error}
    <p class="md-bad">{error}</p>
  {:else if !q}
    <p class="md-note">Loading</p>
  {:else}
    <h3>Reports <small>{q.reports.length} open</small></h3>
    {#if q.reports.length}
      <ul class="md-list">
        {#each q.reports as r (r.number)}
          <li class="is-report">
            <Icon name="alert" size={12} />
            <span class="md-what"><b>{r.title}</b> from {r.by}, {timeAgo(r.created)}</span>
            {#if slugOf(r.title)}<button type="button" class="md-btn" data-sound="self" onclick={() => { play("select"); target = slugOf(r.title); }}>Pick</button>{/if}
            <button type="button" class="md-btn" data-sound="self" onclick={() => { play("open"); openGitHub("issue", { number: r.number }); }}>Open</button>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="md-note">No open reports.</p>
    {/if}
    <h3>Latest requests</h3>
    <ul class="md-list">
      {#each q.requests as r (r.number)}
        <li class:is-refused={r.labels.includes("refused")} class:is-live={r.labels.includes("published")}>
          <span class="md-dot"></span>
          <span class="md-what"><b>{r.title}</b> from {r.by}, {timeAgo(r.created)}</span>
          {#if slugOf(r.title)}<button type="button" class="md-btn" data-sound="self" onclick={() => { play("select"); target = slugOf(r.title); }}>Pick</button>{/if}
          <button type="button" class="md-btn" data-sound="self" onclick={() => { play("open"); openGitHub("issue", { number: r.number }); }}>Open</button>
        </li>
      {:else}
        <li class="md-note">Nothing sent yet.</li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .md { display: flex; flex-direction: column; gap: 12px; }
  .md-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 12px; border-radius: 16px;
              background: rgb(255 255 255 / 0.025); box-shadow: inset 0 0 0 1px var(--color-edge); }
  .md-tools input { min-width: 0; flex: 1 1 160px; padding: 7px 10px; border-radius: 10px; font-size: 12.5px; color: var(--color-ink);
                    background: rgb(0 0 0 / 0.22); box-shadow: inset 0 0 0 1px var(--color-edge); outline: none; }
  .md-grow { flex: 1; }
  .md h3 { margin: 4px 0 0; font-size: 13.5px; color: var(--color-ink); }
  .md h3 small { font-size: 11.5px; font-weight: 400; color: var(--color-faint); }
  .md-list { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; }
  .md-list li { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 12px; font-size: 12.5px;
                color: var(--color-muted); background: rgb(255 255 255 / 0.02); }
  .md-list li.is-report { color: var(--color-warn); }
  .md-what { flex: 1; min-width: 180px; }
  .md-what b { color: var(--color-ink); font-weight: 600; }
  .md-dot { width: 8px; height: 8px; border-radius: 999px; background: var(--color-faint); }
  .is-live .md-dot { background: var(--color-good); }
  .is-refused .md-dot { background: var(--color-bad); }
  .md-btn { padding: 3px 9px; border-radius: 8px; font-size: 11.5px; color: var(--color-accent); transition: background-color 0.15s ease; }
  .md-btn:hover { background: color-mix(in srgb, var(--color-accent) 12%, transparent); }
  .md-note { margin: 0; font-size: 12.5px; color: var(--color-faint); }
  .md-bad { margin: 0; font-size: 12.5px; color: var(--color-bad); }
  :global(:root[data-motion="off"]) .md-btn { transition: none; }
</style>
