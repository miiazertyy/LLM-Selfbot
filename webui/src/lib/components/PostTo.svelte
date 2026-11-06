<script lang="ts">
  /**
   * Put one of the persona's pictures up on X, on Reddit, or as a WhatsApp status, from the Pictures page:
   * which account, where it goes, and what it says. The account's runner does it the way that platform does it,
   * as a person would (app/web/routes/x_routes.py, reddit_routes.py, whatsapp_routes.py). "Try it first" fills
   * everything in and leaves without posting.
   *
   * One dialog for the three, because they differ in exactly two things: Reddit wants a title and somewhere to
   * put it, and the other two do not. Reddit's "somewhere" is its own profile or one of the subreddits it was
   * told it may take part in - never anywhere else, and the server refuses it either way. A WhatsApp status goes
   * to the people who have its number and nowhere else, so it has no "where" at all.
   */
  import Modal from "./Modal.svelte";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import Toggle from "./Toggle.svelte";
  import { api } from "../api";
  import { play } from "../uisound";
  import { toast } from "../stores";
  import { PLATFORMS } from "../platforms";

  let { open = $bindable(false), platform = "reddit", name = "", onposted }: {
    open?: boolean; platform?: "reddit" | "x" | "whatsapp"; name?: string; onposted?: () => void;
  } = $props();

  type Info = { enabled: boolean; accounts: string[]; subreddits: string[]; where: string; max_chars: number };
  let info = $state<Info | null>(null);
  let account = $state("");
  let title = $state("");
  let words = $state("");
  let where = $state("");
  let trial = $state(false);
  let posting = $state(false);

  const brand = $derived(PLATFORMS[platform].name);
  const isReddit = $derived(platform === "reddit");
  const isStatus = $derived(platform === "whatsapp");
  // A status is not posted anywhere: it goes to the people who have its number, for a day.
  const what = $derived(isStatus ? "Put up a WhatsApp status" : `Post to ${brand}`);
  const most = $derived(info?.max_chars ?? (isReddit ? 1500 : platform === "whatsapp" ? 700 : 270));
  const tooLong = $derived(words.length > most);
  const ready = $derived(!!account && !tooLong
    && (isReddit ? !!title.trim() : isStatus ? (!!words.trim() || !!name) : !!words.trim()));

  $effect(() => {
    if (!open) return;
    title = "";
    words = "";
    trial = false;
    const ask = platform === "reddit" ? api.redditPosting()
      : platform === "whatsapp" ? api.whatsappPosting() : api.xPosting();
    ask.then((r: Info) => {
      info = r;
      account = r.accounts[0] || "";
      // Its own profile unless the settings say subreddits and there is one to use.
      where = r.where === "subreddits" ? (r.subreddits[0] || "") : "";
    }).catch((e: Error) => {
      info = { enabled: false, accounts: [], subreddits: [], where: "", max_chars: most };
      toast(e.message, "err");
    });
  });

  async function send() {
    if (posting || !ready) return;
    posting = true;
    play("send");
    try {
      const body: any = { target: account, text: words, picture: name, dry_run: trial };
      if (isReddit) { body.title = title.trim(); body.where = where; }
      const r: any = platform === "reddit" ? await api.redditPost(body)
        : isStatus ? await api.whatsappStatus(body) : await api.xPost(body);
      toast(r?.dry ? `It filled it in on ${brand} and left it.`
                   : isStatus ? "Put up as its status." : `Posted to ${brand}.`, "ok");
      open = false;
      onposted?.();
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      posting = false;
    }
  }
</script>

<Modal bind:open title={what}>
  <div class="pt">
    {#if info && !info.accounts.length}
      <p class="pt-none">
        <Icon name="alert" size={14} />
        No {brand} account is set up yet. Add one on the Accounts page.
      </p>
    {:else}
      {#if (info?.accounts.length ?? 0) > 1}
        <label class="pt-field">
          <span class="pt-label">Which account</span>
          <select class="field" bind:value={account}>
            {#each info?.accounts ?? [] as a (a)}<option value={a}>{a.replace("_", " #")}</option>{/each}
          </select>
        </label>
      {/if}

      {#if isReddit}
        <label class="pt-field">
          <span class="pt-label">Where it goes</span>
          <select class="field" bind:value={where}>
            <option value="">Its own profile</option>
            {#each info?.subreddits ?? [] as s (s)}<option value={s}>r/{s}</option>{/each}
          </select>
          {#if !(info?.subreddits.length)}
            <span class="pt-fine">Its own profile always takes a post. To use a subreddit, list it in Settings,
              Reddit, Comments.</span>
          {/if}
        </label>
        <label class="pt-field">
          <span class="pt-label">Title</span>
          <input class="field" type="text" bind:value={title} maxlength="300" placeholder="what it is" />
        </label>
      {/if}

      <label class="pt-field">
        <span class="pt-label">{isReddit ? "Anything else to say" : "What it says"}</span>
        {#if isStatus}<span class="pt-fine">Everyone who has its number can see a status, for a day.</span>{/if}
        <textarea class="field pt-words" bind:value={words} rows={isReddit ? 4 : 3}
                  placeholder={isReddit ? "optional" : "say something"}></textarea>
        <span class="pt-count" class:is-over={tooLong}>{words.length} / {most}</span>
      </label>

      <label class="pt-try">
        <Toggle size="sm" checked={trial} name="Try it first" onchange={(v: boolean) => (trial = v)} />
        <span>
          <b>Try it first</b>
          <span class="pt-fine">It fills the post in and leaves without putting it up.</span>
        </span>
      </label>
    {/if}
  </div>


  <div class="pt-go">
    <Button kind="ghost" onclick={() => (open = false)}>Cancel</Button>
    <Button loading={posting} disabled={!ready} onclick={send}>{trial ? "Try it" : what}</Button>
  </div>
  {#if posting}<p class="pt-fine">Putting it up on {brand}. This can take a minute.</p>{/if}
</Modal>

<style>
  .pt { display: flex; flex-direction: column; gap: 12px; }
  .pt-field { display: flex; flex-direction: column; gap: 4px; position: relative; }
  .pt-label { font-size: 12px; font-weight: 500; color: var(--color-muted); }
  .pt-fine { font-size: 11px; color: var(--color-faint); }
  .pt-words { resize: vertical; min-height: 70px; }
  .pt-count { align-self: flex-end; font-size: 11px; color: var(--color-faint); }
  .pt-count.is-over { color: var(--color-bad); }
  .pt-try { display: flex; align-items: flex-start; gap: 10px; font-size: 12.5px; }
  .pt-try span { display: flex; flex-direction: column; gap: 1px; }
  .pt-go { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
  .pt-none { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--color-muted); }
</style>
