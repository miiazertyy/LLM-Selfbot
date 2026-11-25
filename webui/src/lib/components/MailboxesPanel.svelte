<script lang="ts">
  /**
   * Settings > App > Mailboxes: where the codes Instagram, X and Reddit email at sign-in are read from
   * (app/utils/mailcodes.py). The app finds how to reach each mailbox by itself, opens it once to be sure before
   * keeping it, and says what the provider wants when it wants an app password.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import { ask as askFirst } from "../ask";
  import { whenSent } from "../fmt";
  import { smoothHeight } from "../smoothheight";
  import { toast } from "../stores";
  import { play } from "../uisound";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";

  type Box = { index: number; address: string; server: string; has_password: boolean;
               last?: { platform: string; ts: number } | null };
  const NAMES: Record<string, string> = { instagram: "Instagram", x: "X", reddit: "Reddit" };

  let boxes = $state<Box[]>([]);
  let adding = $state(false);
  let address = $state("");
  let password = $state("");
  let server = $state("");
  let askServer = $state(false);
  let busy = $state(false);
  let reply = $state<{ ok: boolean; reason?: string; note?: string; found?: string } | null>(null);
  let checking = $state<number | null>(null);
  let checked = $state<Record<number, string>>({});

  async function load() {
    try {
      boxes = (await api.mailboxes()).mailboxes;
    } catch {
      /* shown as empty; the next visit tries again */
    }
  }
  onMount(load);

  function toggleAdd() {
    adding = !adding;
    play(adding ? "open" : "menu");
    reply = null;
  }

  async function connect(e: Event) {
    e.preventDefault();
    if (busy || !address.trim() || !password) return;
    busy = true;
    reply = null;
    play("send");
    try {
      const r = await api.mailboxAdd(address.trim(), password, askServer ? server.trim() : "");
      if (r.ok) {
        play("done");
        toast(`Connected to ${address.trim()}.`, "ok");
        address = password = server = "";
        askServer = false;
        adding = false;
        await load();
      } else {
        play("err");
        reply = r;
        // A server it only guessed at, or the one it found refusing: let a person who knows say which.
        if (r.found === "a guess" || /reach/i.test(r.reason || "")) askServer = true;
      }
    } catch (err: any) {
      play("err");
      reply = { ok: false, reason: err.message };
    }
    busy = false;
  }

  async function check(b: Box) {
    checking = b.index;
    try {
      const r = await api.mailboxTest(b.index);
      checked[b.index] = r.ok ? "Still opens." : r.reason;
      play(r.ok ? "done" : "err");
    } catch (e: any) {
      checked[b.index] = e.message;
      play("err");
    }
    checking = null;
  }

  async function remove(b: Box) {
    if (!(await askFirst(`Remove ${b.address}?`, { detail: "Codes sent there will need typing again.", yes: "Remove", danger: true }))) return;
    try {
      await api.mailboxRemove(b.index);
      play("delete");
      await load();
    } catch (e: any) {
      toast(e.message, "err");
    }
  }
</script>

<div class="settings-card">
  <div class="settings-row flex flex-wrap items-center gap-4">
    <div class="min-w-0 flex-1">
      <div class="text-[13.5px] font-medium text-ink">Codes from your mail</div>
      <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
        Sign-in codes from Instagram, X and Reddit are read here and typed in.
      </p>
    </div>
    <span data-sound="self"><Button kind={adding ? "primary" : "ghost"} size="sm" onclick={toggleAdd}><Icon name="plus" size={12} />Add a mailbox</Button></span>
  </div>
  <div use:smoothHeight class="mb-box">
    <div>
      {#if adding}
        <form class="settings-row mb-form" onsubmit={connect} data-sound="self">
          <input bind:value={address} type="email" autocomplete="off" placeholder="Address" aria-label="Address" class="field py-1.5 px-3 text-[13px]" />
          <input bind:value={password} type="password" autocomplete="new-password" placeholder="Password" aria-label="Password" class="field py-1.5 px-3 text-[13px]" />
          {#if askServer}
            <input bind:value={server} placeholder="IMAP server, if you know it" aria-label="IMAP server" class="field py-1.5 px-3 text-[13px]" />
          {/if}
          <Button size="sm" loading={busy} disabled={busy || !address.trim() || !password}>Connect</Button>
          {#if reply && !reply.ok}
            <p class="mb-reply">{reply.reason}{reply.note ? ` ${reply.note}` : ""}</p>
          {/if}
        </form>
      {/if}
    </div>
  </div>
  {#each boxes as b (b.index)}
    <div class="settings-row flex flex-wrap items-center gap-3">
      <span class="mb-mark"><Icon name="inbox" size={15} /></span>
      <div class="min-w-0 flex-1">
        <div class="text-[13px] text-ink">{b.address}</div>
        <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
          {b.server}{b.last ? `. Last code: ${NAMES[b.last.platform] ?? b.last.platform}, ${whenSent(b.last.ts)}` : ""}{checked[b.index] ? `. ${checked[b.index]}` : ""}
        </p>
      </div>
      <Button kind="ghost" size="sm" loading={checking === b.index} onclick={() => check(b)}>Check</Button>
      <span data-sound="self"><Button kind="ghost" size="sm" onclick={() => remove(b)}>Remove</Button></span>
    </div>
  {:else}
    {#if !adding}
      <div class="settings-row"><p class="text-[12px] text-faint">No mailbox yet.</p></div>
    {/if}
  {/each}
</div>
<p class="mt-3 px-1 text-[11px] leading-relaxed text-faint">
  Only mail from the socials is opened. Nothing is marked read, moved or deleted.
</p>

<style>
  .mb-box {
    overflow: hidden;
  }
  .mb-form {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
    gap: 8px;
    align-items: center;
  }
  .mb-form :global(input:nth-of-type(3)) {
    grid-column: 1 / 3;
  }
  .mb-reply {
    grid-column: 1 / -1;
    color: var(--color-warn);
    font-size: 12px;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }
  .mb-mark {
    display: inline-flex;
    color: var(--color-accent);
  }
  @media (max-width: 640px) {
    .mb-form {
      grid-template-columns: minmax(0, 1fr);
    }
    .mb-form :global(input:nth-of-type(3)) {
      grid-column: auto;
    }
  }
</style>
