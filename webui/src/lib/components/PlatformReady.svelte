<script lang="ts">
  /**
   * A platform with nothing to install, where it stands: Discord's library and Telegram's come with the app, so what it
   * needs is an account, a model to write with, and to be started. Those are ticked off (ReadyHero.svelte), with the one
   * thing to do next on the card, and how each account is doing under it.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import { PLATFORMS } from "../platforms";
  import { visiblePoll } from "../poll";
  import { loadProviders, providerList, savedPlan, shortModel } from "../providers";
  import { settingsSection, toast } from "../stores";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import ReadyHero, { type ReadyStep } from "./ReadyHero.svelte";

  let { platform }: { platform: "discord" | "telegram" } = $props();

  type Acct = { id: string; platform: string; account: number | null; state: string; username?: string; name?: string;
                gave_up?: boolean; enabled?: boolean; last_error?: string | null;
                web?: { state: string; detail: string; at: number; stale: boolean } | null };

  const brand = $derived(PLATFORMS[platform]);
  let loaded = $state(false);
  let slots = $state<{ id: string; index: number }[]>([]);
  let accts = $state<Acct[]>([]);
  let starting = $state(false);

  async function load() {
    try {
      const [s, a]: any = await Promise.all([api.slots(), api.accounts()]);
      slots = (s?.slots ?? []).filter((x: any) => x.platform === platform);
      accts = (a?.accounts ?? []).filter((x: any) => x.platform === platform);
    } catch {
      /* the page still works without it */
    }
    loaded = true;
  }

  onMount(() => {
    load();
    loadProviders().catch(() => {});
    return visiblePoll(load, 4000);
  });

  const alive = (a: Acct) => a.state === "running" || a.state === "starting";
  /** Connected, where its runner says, else simply up: Discord's says nothing, and is online while it runs. */
  const online = (a: Acct) => a.state === "running" && (!a.web || a.web.stale || a.web.state === "ready");

  /** Who it is, recorded the last time it connected. */
  const who = (a: Acct) => a.username || a.name || "";

  const up = $derived(accts.filter(online));
  const rising = $derived(accts.some((a) => alive(a) && !online(a)));
  const signedIn = $derived(accts.filter((a) => !!who(a)));
  const writer = $derived(($savedPlan?.replies ?? []).find((e) => $providerList.find((p) => p.id === e.provider)?.ready));

  const steps = $derived.by((): ReadyStep[] => [
    { name: "An account", done: slots.length > 0,
      what: platform === "discord" ? "Its token, on the Accounts page." : "Its login, on the Accounts page.",
      shows: slots.length ? `${slots.length} account${slots.length === 1 ? "" : "s"}` : "None yet" },
    { name: "Signed in", done: signedIn.length > 0, working: rising && !signedIn.length,
      what: `${brand.name} has let it in at least once.`,
      shows: signedIn.length ? who(signedIn[0]) : rising ? "Signing in" : "Not yet" },
    { name: "A model", done: !!writer, what: "What writes its replies, under Models.",
      shows: writer ? shortModel(writer.model) : "None yet" },
    { name: "Online", done: up.length > 0, working: rising && !up.length, what: "Connected, and answering messages.",
      shows: up.length ? `${up.length} of ${accts.length || up.length}` : rising ? "Starting" : "Not running" },
  ]);

  const headline = $derived.by((): { title: string; sub: string; tone: "good" | "warn" | "bad" | "working" } => {
    if (!slots.length) return { title: `Add a ${brand.name} account`, sub: `It needs one to run. They are added on the Accounts page.`, tone: "warn" };
    if (!writer) return { title: "It has nothing to write with", sub: "Connect a provider and pick a model under Models.", tone: "warn" };
    if (up.length) return { title: `${brand.name} is ready to run`, sub: "Online, and answering messages.", tone: "good" };
    const stuck = accts.find((a) => a.gave_up || a.state === "crashing");
    if (stuck) return { title: "It keeps stopping", sub: stuck.last_error || "Its log on the Accounts page says why.", tone: "bad" };
    if (rising) return { title: "Connecting", sub: `Signing in to ${brand.name}.`, tone: "working" };
    return { title: `${brand.name} is ready to run`, sub: "It only needs starting.", tone: "good" };
  });

  /** Whatever is next. Nothing, and it is the Ready badge. */
  const next = $derived(!slots.length ? "account" : !writer ? "model" : !up.length && !rising ? "start" : "");

  async function startAll() {
    starting = true;
    try {
      await Promise.all(accts.filter((a) => !alive(a)).map((a) => api.accountAction(a.id, "start")));
      await load();
    } catch (e: any) {
      toast(e?.message || "Could not start it", "err");
    } finally {
      starting = false;
    }
  }

  const stateOf = (a: Acct) => (a.gave_up || a.state === "crashing" ? "Keeps stopping" : !alive(a) ? "Stopped"
    : online(a) ? "Answering messages" : "Starting up");
  const toneOf = (a: Acct) => (a.gave_up || a.state === "crashing" ? "bad" : online(a) ? "good" : alive(a) ? "working" : "muted");
</script>

{#snippet start()}
  <Button onclick={startAll} loading={starting}>{#if !starting}<Icon name="play" size={10} />{/if}Start</Button>
{/snippet}

{#if !loaded}
  <div class="pr-skeleton"></div>
{:else}
  <ReadyHero {platform} title={headline.title} sub={headline.sub} tone={headline.tone} {steps}
             action={next === "start" ? start : undefined}
             go={next === "account" ? { label: "Add an account", href: "#/accounts" }
               : next === "model" ? { label: "Choose a model", onclick: () => settingsSection.set("groq/models") } : null}>
    {#if accts.length}
      <div class="pr-accounts">
        {#each accts as a (a.id)}
          {@const tone = toneOf(a)}
          <div class="pr-account is-{tone}">
            <span class="pr-dot"></span>
            <div class="min-w-0 flex-1">
              <div class="pr-account-head">
                <b>{who(a) || `Account #${a.account ?? 1}`}</b>
                <span class="pr-state">{stateOf(a)}</span>
              </div>
              {#if a.web && !a.web.stale && a.web.detail}<p class="pr-detail">{a.web.detail}</p>{/if}
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </ReadyHero>
{/if}

<style>
  .pr-skeleton { height: 132px; border-radius: 16px; background: rgb(255 255 255 / 0.03); }
  .pr-accounts { display: flex; flex-direction: column; gap: 6px; }
  .pr-account {
    --tone: var(--color-muted);
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 12px;
    border-radius: 12px;
    background: color-mix(in srgb, var(--tone) 7%, transparent);
  }
  .pr-account.is-good { --tone: var(--color-good); }
  .pr-account.is-bad { --tone: var(--color-bad); }
  .pr-account.is-working { --tone: var(--color-accent); }
  .pr-dot { width: 8px; height: 8px; margin-top: 5px; flex-shrink: 0; border-radius: 999px; background: var(--tone); }
  .pr-account-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; font-size: 12.5px; color: var(--color-ink); }
  .pr-account-head b { font-weight: 650; }
  .pr-state { font-weight: 600; color: var(--tone); }
  .pr-detail { margin-top: 2px; font-size: 12px; line-height: 1.5; color: var(--color-muted); }
</style>
