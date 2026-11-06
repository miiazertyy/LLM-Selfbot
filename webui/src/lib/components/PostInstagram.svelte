<script lang="ts">
  /**
   * Put one of the persona's pictures up on Instagram, from the Pictures page:
   * which Instagram account, whether it goes as a post, a reel or a story, and
   * its caption (the persona can write one from what the picture shows). The
   * account's runner does it in Instagram's own create flow, as a person would
   * (app/web/routes/instagram_routes.py). "Try it first" fills everything in
   * and leaves without posting.
   *
   * A reel has to be a video; a story goes through Instagram's phone site,
   * which is the only one that takes one, and says so plainly when it will not.
   */
  import Modal from "./Modal.svelte";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import Toggle from "./Toggle.svelte";
  import { api } from "../api";
  import { play } from "../uisound";
  import { toast } from "../stores";

  let { open = $bindable(false), name = "", persona = "", video = false, onposted }: {
    open?: boolean; name?: string; persona?: string; video?: boolean; onposted?: () => void;
  } = $props();

  type Info = { enabled: boolean; accounts: string[]; as: string[] };
  let info = $state<Info | null>(null);
  let account = $state("");
  let caption = $state("");
  let as = $state("post");
  let trial = $state(false);
  let writing = $state(false);
  let posting = $state(false);

  const WAYS = [
    { value: "post", label: "Post", icon: "pictures", needsVideo: false },
    { value: "reel", label: "Reel", icon: "play", needsVideo: true },
    { value: "story", label: "Story", icon: "clock", needsVideo: false },
  ];

  $effect(() => {
    if (!open) return;
    caption = "";
    trial = false;
    as = "post";
    api.instagramPosting().then((r: Info) => {
      info = r;
      account = r.accounts[0] || "";
    }).catch((e: Error) => {
      info = { enabled: false, accounts: [], as: [] };
      toast(e.message, "err");
    });
  });

  async function write() {
    if (writing) return;
    writing = true;
    play("tap");
    try {
      const r = await api.instagramCaption({ persona, name, as });
      caption = r.caption || caption;
      play("glint", { level: 0.5 });
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      writing = false;
    }
  }

  function choose(v: string) {
    if (v === as) return;
    as = v;
    play("select");
  }

  async function post() {
    if (posting || !account) return;
    posting = true;
    play("send");
    try {
      const r = await api.instagramPost({ target: account, persona, name, caption: caption.trim(), as, dry_run: trial });
      toast(r.dry ? "Tried it: filled in on Instagram, not posted." : `Posted to Instagram as a ${as}.`, "ok");
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

<Modal bind:open title="Post to Instagram">
  {#if !info}
    <p class="pi-note">Looking...</p>
  {:else if !info.enabled}
    <p class="pi-note">Posting is off. Turn it on in Settings, Instagram, Posting.</p>
  {:else if !info.accounts.length}
    <p class="pi-note">No Instagram account yet. Add one on the Accounts page.</p>
  {:else}
    <div class="pi">
      <p class="pi-file"><Icon name={video ? "play" : "pictures"} size={12} />{name}</p>
      {#if info.accounts.length > 1}
        <label class="pi-label" for="pi-account">Account</label>
        <select id="pi-account" class="pi-field" bind:value={account} onchange={() => play("select")}>
          {#each info.accounts as a (a)}<option value={a}>Instagram {a.split("_")[1]}</option>{/each}
        </select>
      {/if}
      <span class="pi-label">How it goes up</span>
      <div class="pi-ways" role="radiogroup" aria-label="How it goes up">
        {#each WAYS as w (w.value)}
          <button type="button" role="radio" aria-checked={as === w.value} class:is-on={as === w.value}
                  disabled={w.needsVideo && !video}
                  title={w.needsVideo && !video ? "A reel has to be a video" : ""}
                  onclick={() => choose(w.value)}>
            <Icon name={w.icon} size={12} />{w.label}
          </button>
        {/each}
      </div>
      {#if as !== "story"}
        <div class="pi-row">
          <label class="pi-label" for="pi-caption">Caption</label>
          <button type="button" class="pi-ai" onclick={write} disabled={writing} title="Let the persona write it">
            <Icon name="sparkle" size={12} />{writing ? "Writing..." : "Write one"}
          </button>
        </div>
        <textarea id="pi-caption" class="pi-field" rows="3" maxlength="2200" placeholder="What goes under it"
                  bind:value={caption}></textarea>
      {:else}
        <p class="pi-note">
          A story goes up through Instagram's phone site, in the same session. If its website will not take one, it
          says so and nothing is posted.
        </p>
      {/if}
      <label class="pi-trial">
        <Toggle size="sm" checked={trial} name="Try it first" onchange={(v: boolean) => (trial = v)} />
        Try it first: fill it in on Instagram, then leave without posting
      </label>
      <div class="pi-go">
        <Button kind="ghost" onclick={() => (open = false)}>Cancel</Button>
        <Button onclick={post} loading={posting} disabled={!account}>{trial ? "Try it" : "Post"}</Button>
      </div>
      {#if posting}<p class="pi-note">Uploading to Instagram. This can take a minute or two.</p>{/if}
    </div>
  {/if}
</Modal>

<style>
  .pi { display: flex; flex-direction: column; gap: 8px; min-width: min(420px, 80vw); }
  .pi-note { margin: 0; font-size: 12.5px; line-height: 1.45; color: var(--color-muted); }
  .pi-file { display: inline-flex; align-items: center; gap: 6px; margin: 0; font-size: 12px; color: var(--color-faint); }
  .pi-label { font-size: 11.5px; font-weight: 600; color: var(--color-muted); }
  .pi-row { display: flex; align-items: center; justify-content: space-between; }
  .pi-field {
    width: 100%;
    padding: 8px 10px;
    border-radius: 10px;
    font-size: 13px;
    color: var(--color-ink);
    background: rgb(0 0 0 / 0.25);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    resize: vertical;
  }
  .pi-field:focus { outline: none; box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, transparent); }
  .pi-ai {
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
  .pi-ai:disabled { opacity: 0.6; }
  .pi-ways { display: flex; flex-wrap: wrap; gap: 6px; }
  .pi-ways button {
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
  .pi-ways button.is-on {
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 22%, rgb(255 255 255 / 0.05));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 40%, transparent);
  }
  .pi-ways button:disabled { opacity: 0.45; }
  .pi-trial { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--color-muted); }
  .pi-go { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
  :global(:root[data-motion="off"]) .pi-ways button { transition: none; }
</style>
