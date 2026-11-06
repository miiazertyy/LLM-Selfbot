<script lang="ts">
  /**
   * Post one of the persona's videos to TikTok, from the Pictures page: which
   * TikTok account, its caption (the persona can write one from what the video
   * shows), who can watch it. The account's runner does it on TikTok Studio,
   * as a person would (app/web/routes/tiktok_routes.py). "Try it first" fills
   * everything in on TikTok and leaves without posting.
   */
  import Modal from "./Modal.svelte";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import Toggle from "./Toggle.svelte";
  import { api } from "../api";
  import { play } from "../uisound";
  import { toast } from "../stores";

  let { open = $bindable(false), name = "", persona = "", onposted }: {
    open?: boolean; name?: string; persona?: string; onposted?: () => void;
  } = $props();

  type Info = { enabled: boolean; accounts: string[]; privacy: string };
  let info = $state<Info | null>(null);
  let account = $state("");
  let caption = $state("");
  let privacy = $state("everyone");
  let trial = $state(false);
  let writing = $state(false);
  let posting = $state(false);

  const WHO = [
    { value: "everyone", label: "Everyone", icon: "globe" },
    { value: "friends", label: "Friends", icon: "accounts" },
    { value: "only_me", label: "Only me", icon: "key" },
  ];

  $effect(() => {
    if (!open) return;
    caption = "";
    trial = false;
    api.tiktokPosting().then((r: Info) => {
      info = r;
      account = r.accounts[0] || "";
      privacy = r.privacy || "everyone";
    }).catch((e: Error) => {
      info = { enabled: false, accounts: [], privacy: "everyone" };
      toast(e.message, "err");
    });
  });

  async function write() {
    if (writing) return;
    writing = true;
    play("tap");
    try {
      const r = await api.tiktokCaption(persona, name);
      caption = r.caption || caption;
      play("glint", { level: 0.5 });
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      writing = false;
    }
  }

  function choose(v: string) {
    if (v === privacy) return;
    privacy = v;
    play("select");
  }

  async function post() {
    if (posting || !account) return;
    posting = true;
    play("send");
    try {
      const r = await api.tiktokPost({ target: account, persona, name, caption: caption.trim(), privacy, dry_run: trial });
      toast(r.dry ? "Tried it: filled in on TikTok, not posted." : "Posted to TikTok.", "ok");
      play(r.dry ? "done" : "medal");
      open = false;
      onposted?.();
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      posting = false;
    }
  }
</script>

<Modal bind:open title="Post to TikTok">
  {#if !info}
    <p class="pt-note">Looking...</p>
  {:else if !info.enabled}
    <p class="pt-note">Posting is off. Turn it on in Settings, TikTok, Posting.</p>
  {:else if !info.accounts.length}
    <p class="pt-note">No TikTok account yet. Add one on the Accounts page.</p>
  {:else}
    <div class="pt">
      <p class="pt-file"><Icon name="play" size={12} />{name}</p>
      {#if info.accounts.length > 1}
        <label class="pt-label" for="pt-account">Account</label>
        <select id="pt-account" class="pt-field" bind:value={account} onchange={() => play("select")}>
          {#each info.accounts as a (a)}<option value={a}>TikTok {a.split("_")[1]}</option>{/each}
        </select>
      {/if}
      <div class="pt-row">
        <label class="pt-label" for="pt-caption">Caption</label>
        <button type="button" class="pt-ai" onclick={write} disabled={writing} title="Let the persona write it">
          <Icon name="sparkle" size={12} />{writing ? "Writing..." : "Write one"}
        </button>
      </div>
      <textarea id="pt-caption" class="pt-field" rows="3" maxlength="2000" placeholder="What goes under the video"
                bind:value={caption}></textarea>
      <span class="pt-label">Who can watch</span>
      <div class="pt-who" role="radiogroup" aria-label="Who can watch">
        {#each WHO as w (w.value)}
          <button type="button" role="radio" aria-checked={privacy === w.value} class:is-on={privacy === w.value}
                  onclick={() => choose(w.value)}>
            <Icon name={w.icon} size={12} />{w.label}
          </button>
        {/each}
      </div>
      <label class="pt-trial">
        <Toggle size="sm" checked={trial} name="Try it first" onchange={(v: boolean) => (trial = v)} />
        Try it first: fill it in on TikTok, then leave without posting
      </label>
      <div class="pt-go">
        <Button kind="ghost" onclick={() => (open = false)}>Cancel</Button>
        <Button onclick={post} loading={posting} disabled={!account}>{trial ? "Try it" : "Post"}</Button>
      </div>
      {#if posting}<p class="pt-note">Uploading to TikTok. This can take a minute or two.</p>{/if}
    </div>
  {/if}
</Modal>

<style>
  .pt { display: flex; flex-direction: column; gap: 8px; min-width: min(420px, 80vw); }
  .pt-note { margin: 0; font-size: 12.5px; color: var(--color-muted); }
  .pt-file { display: inline-flex; align-items: center; gap: 6px; margin: 0; font-size: 12px; color: var(--color-faint); }
  .pt-label { font-size: 11.5px; font-weight: 600; color: var(--color-muted); }
  .pt-row { display: flex; align-items: center; justify-content: space-between; }
  .pt-field {
    width: 100%;
    padding: 8px 10px;
    border-radius: 10px;
    font-size: 13px;
    color: var(--color-ink);
    background: rgb(0 0 0 / 0.25);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    resize: vertical;
  }
  .pt-field:focus { outline: none; box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, transparent); }
  .pt-ai {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 9px;
    border-radius: 8px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 18%, rgb(255 255 255 / 0.04));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 35%, transparent);
  }
  .pt-ai:disabled { opacity: 0.6; }
  .pt-who { display: flex; flex-wrap: wrap; gap: 6px; }
  .pt-who button {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 6px 11px;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 600;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
    transition: color 0.15s ease, background-color 0.15s ease, box-shadow 0.2s ease;
  }
  .pt-who button.is-on {
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 22%, rgb(255 255 255 / 0.05));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 40%, transparent);
  }
  .pt-trial { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--color-muted); }
  .pt-go { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
  :global(:root[data-motion="off"]) .pt-who button { transition: none; }
</style>
