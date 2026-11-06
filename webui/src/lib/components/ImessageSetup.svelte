<script lang="ts">
  /**
   * iMessage: what it needs, and where each account stands.
   *
   * iMessage only runs on Apple's own machines, so an account here reaches it one of two ways. Through an iPhone or
   * iPad: a Shortcuts automation on it passes each message here and sends back the reply (app/web/routes/
   * relay_routes.py), so this shows its address, a QR code of it for the phone's camera, and the four steps in
   * Shortcuts. Or through a Mac running BlueBubbles Server: four things it needs, ticked off as they come true (each
   * lighting with a rising note, a bell at the end, as on the other platforms' pages), each account's own word on
   * how it is, and the Mac's side in plain steps.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import { visiblePoll } from "../poll";
  import { loadProviders, providerList, savedPlan, shortModel } from "../providers";
  import ReadyHero, { type ReadyStep } from "./ReadyHero.svelte";
  import { openUrl } from "../window";
  import Icon from "./Icon.svelte";
  import Button from "./Button.svelte";
  import Segmented from "./Segmented.svelte";
  import { play } from "../uisound";
  import { copyText } from "../contextmenu";
  import { settingsSection } from "../stores";

  type Acct = { id: string; platform: string; account: number | null; state: string; username?: string;
                web?: { state: string; detail: string; at: number; stale: boolean } | null };
  type Mac = { live?: boolean; private_api?: boolean; helper?: boolean; account?: string; macos?: string;
               bluebubbles?: string; server?: string };

  /** Its worker is up: "starting" is what the supervisor calls its first minute, already connected and texting. */
  const alive = (a: Acct) => a.state === "running" || a.state === "starting";

  let loaded = $state(false);
  let allSlots = $state<{ id: string; index: number; server?: string }[]>([]);
  let allAccts = $state<Acct[]>([]);
  let macs = $state<Record<string, Mac>>({});
  type Relay = Awaited<ReturnType<typeof api.imessageRelay>>;
  let relays = $state<Record<number, Relay>>({});
  /** The PC's address each one's shortcut goes to, when picked (Tailscale's works away from home, the Wi-Fi's only on
   *  the same network); the first the PC has, else. */
  let picked = $state<Record<number, string>>({});

  // Which way is shown: the one the accounts use, the phone when there are none (most people have no Mac), and then
  // whichever was picked.
  let via = $state<"phone" | "mac">("phone");
  let viaPicked = false;
  const phoneSlots = $derived(allSlots.filter((s) => s.server === "phone"));
  // The Mac's part below is about its own accounts only.
  const slots = $derived(allSlots.filter((s) => s.server !== "phone"));
  const accts = $derived(allAccts.filter((a) => slots.some((s) => s.id === a.id)));
  /** This page opened on the PC itself: then the phone needs one of the PC's network addresses, not this one. */
  const local = ["127.0.0.1", "localhost", "[::1]"].includes(location.hostname);

  async function load() {
    try {
      const [s, a]: any = await Promise.all([api.slots(), api.accounts()]);
      allSlots = (s?.slots ?? []).filter((x: any) => x.platform === "imessage");
      allAccts = (a?.accounts ?? []).filter((x: any) => x.platform === "imessage");
      if (!viaPicked) via = allSlots.length && allSlots.every((x) => x.server !== "phone") ? "mac" : "phone";
      const rel: Record<number, Relay> = {};
      for (const x of allSlots.filter((x) => x.server === "phone")) {
        try {
          rel[x.index] = await api.imessageRelay(x.index, local ? picked[x.index] ?? "" : location.origin);
        } catch {
          /* said as not found below */
        }
      }
      relays = rel;
      const out: Record<string, Mac> = {};
      for (const x of accts) {
        if (!alive(x)) continue;
        try {
          const d: any = await api.accountDetails(x.id);
          if (d?.imessage) out[x.id] = d.imessage;
        } catch {
          /* not answering yet */
        }
      }
      macs = out;
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

  const up = $derived(accts.filter((a) => alive(a) && a.web && !a.web.stale && a.web.state === "ready"));
  const anyMac = $derived(Object.values(macs));
  const signedIn = $derived(accts.some((a) => !!a.username) || anyMac.some((m) => !!m.account));
  const papi = $derived(anyMac.some((m) => m.private_api && m.helper));

  const steps = $derived.by((): ReadyStep[] => [
    { name: "A Mac signed in to iMessage", what: "Any Mac, on and awake. The Messages app signed in.", done: signedIn,
      shows: signedIn ? (accts.find((a) => a.username)?.username || anyMac.find((m) => m.account)?.account || "Signed in") : "Not seen yet" },
    { name: "BlueBubbles Server", what: "Free, on that Mac. It is what this app talks to.", done: up.length > 0,
      shows: up.length ? `Reached${anyMac[0]?.bluebubbles ? `, ${anyMac[0].bluebubbles}` : ""}` : slots.length ? "Not reached" : "Not added" },
    { name: "Its Private API", what: "For typing dots, read receipts, tapbacks, replies in a thread, edits.",
      done: papi, optional: true, shows: papi ? "On" : up.length ? "Off, optional" : "Optional" },
    { name: "Added here", what: "Its address and password, on the Accounts page.", done: slots.length > 0,
      shows: slots.length ? `${slots.length} account${slots.length > 1 ? "s" : ""}` : "None yet" },
  ]);

  const headline = $derived.by((): { title: string; sub: string; tone: "good" | "warn" | "bad" | "working" } => {
    if (!slots.length) return { title: "Text from iMessage, through a Mac", tone: "warn",
                                sub: "It needs a Mac signed in to iMessage, running BlueBubbles Server. Then add it on the Accounts page." };
    if (!up.length) {
      const bad = accts.find((a) => a.web && !a.web.stale && (a.web.state === "logged-out" || a.web.state === "needs-you"));
      return bad ? { title: "It cannot reach the Mac yet", tone: "bad", sub: bad.web?.detail || "Check the address and the password." }
                 : { title: "Connecting to the Mac", tone: "working", sub: "Start the account on the Accounts page if it is stopped." };
    }
    return papi ? { title: "iMessage is ready to run", tone: "good", sub: "Typing dots, read receipts and tapbacks are on." }
                : { title: "iMessage is ready to run", tone: "good", sub: "It texts. Turn on BlueBubbles' Private API for typing dots, read receipts and tapbacks." };
  });

  // ── Through the iPhone ──
  /** Heard from: a real message ("test" false), or only the address opened in Safari. */
  const heardReal = $derived(phoneSlots.some((s) => relays[s.index]?.heard && !relays[s.index]?.heard?.test));
  const heardAny = $derived(phoneSlots.some((s) => !!relays[s.index]?.heard));
  const writer = $derived(($savedPlan?.replies ?? []).find((e) => $providerList.find((p) => p.id === e.provider)?.ready));
  const phoneSteps = $derived.by((): ReadyStep[] => [
    { name: "Added here", what: "An iMessage account, the iPhone way, on the Accounts page.", done: phoneSlots.length > 0,
      shows: phoneSlots.length ? `${phoneSlots.length} account${phoneSlots.length > 1 ? "s" : ""}` : "None yet" },
    { name: "Your iPhone reaches this PC", what: "Its address below, opened once in Safari.", done: heardAny,
      shows: heardAny ? "Reached" : "Not yet" },
    { name: "The shortcut", what: "Four steps in Shortcuts, on the iPhone.", done: heardReal,
      shows: heardReal ? "Passing messages" : "Not yet" },
    { name: "A model", what: "What writes its replies, under Models.", done: !!writer,
      shows: writer ? shortModel(writer.model) : "None yet" },
  ]);
  const phoneHead = $derived.by((): { title: string; sub: string; tone: "good" | "warn" | "bad" | "working" } => {
    if (!phoneSlots.length) return { title: "iMessage through your iPhone", tone: "warn",
                                     sub: "No Mac needed. Add an iMessage account on the Accounts page, the iPhone way." };
    if (!heardReal) return { title: "Make the shortcut on your iPhone", tone: "working",
                             sub: "Four steps in Shortcuts. Then every message it gets is answered from here." };
    return { title: "iMessage is ready to run", tone: "good", sub: "Your iPhone passes every message it gets to here." };
  });

  function ago(at: number): string {
    const s = Math.max(0, Date.now() / 1000 - at);
    return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago`
      : `${Math.round(s / 86400)} d ago`;
  }

  function heardSays(r: Relay | undefined): string {
    if (!r) return "Looking";
    if (!r.heard) return "Not heard from yet";
    return r.heard.test ? `Your iPhone reached it ${ago(r.heard.at)}. Now the shortcut.` : `Last message ${ago(r.heard.at)}`;
  }

  async function pick(index: number, url: string) {
    play("select");
    picked = { ...picked, [index]: url };
    try {
      relays = { ...relays, [index]: await api.imessageRelay(index, url) };
    } catch {
      /* the next look brings it */
    }
  }

  async function copy(url: string) {
    play("tap");
    await copyText(url, "Copied the address.");
  }

  function openSwitch() {
    play("open");
    settingsSection.set("app/services");
  }

  const SAYS: Record<string, string> = {
    ready: "Connected, texting", starting: "Connecting", "logging-in": "Connecting", "needs-you": "Waiting for you",
    "logged-out": "Cannot reach the Mac",
  };
  const TONE: Record<string, string> = { ready: "good", starting: "muted", "needs-you": "warn", "logged-out": "bad" };

  function go(url: string) {
    play("open");
    openUrl(url);
  }
</script>

{#if !loaded}
  <div class="im-skeleton"></div>
{:else}
  <div class="im">
    <Segmented label="How it reaches iMessage" bind:value={via} onchange={() => (viaPicked = true)} options={[
      { id: "phone", label: "iPhone or iPad", icon: "phone", tone: "#30d158" },
      { id: "mac", label: "A Mac", icon: "monitor", tone: "#0a84ff" },
    ]} />

    {#if via === "phone"}
    <ReadyHero platform="imessage" title={phoneHead.title} sub={phoneHead.sub} tone={phoneHead.tone} steps={phoneSteps}
               go={!phoneSlots.length ? { label: "Add an account", href: "#/accounts" } : null} />

    {#each phoneSlots as s (s.id)}
      {@const r = relays[s.index]}
      <section class="im-phone">
        <div class="im-runner-head">
          <b>iMessage #{s.index}</b>
          <span class="im-state">{heardSays(r)}</span>
        </div>
        {#if r?.url}
          {#if !r.open && local}
            <!-- The panel only listens on this PC: a phone has nothing to reach. -->
            <p class="im-warn">
              <Icon name="alert" size={13} />
              <span>Your iPhone can't reach this PC yet: the panel only listens on this PC. Open it to your network,
                or use Tailscale. <button type="button" class="im-link" onclick={openSwitch}>Open the switch</button></span>
            </p>
          {/if}
          <div class="im-addr">
            <div class="im-qr" role="img" aria-label="QR code of the address">{@html r.qr}</div>
            <div class="min-w-0 flex-1">
              <span class="im-addr-label">Its address</span>
              <code class="im-addr-url">{r.url}</code>
              <div class="mt-2 flex flex-wrap items-center gap-2">
                <Button size="sm" kind="ghost" onclick={() => copy(r.url ?? "")}><Icon name="copy" size={12} />Copy</Button>
                {#if local && (r.addresses?.length ?? 0) > 1}
                  <!-- Which of the PC's addresses: Tailscale's works anywhere the phone has it, the Wi-Fi's at home. -->
                  <span class="im-kinds" role="radiogroup" aria-label="Which address">
                    {#each r.addresses ?? [] as a (a.url)}
                      <button type="button" role="radio" class="im-kind" aria-checked={!!r.url?.startsWith(a.url + "/")}
                              class:is-on={r.url?.startsWith(a.url + "/")} onclick={() => pick(s.index, a.url)}
                              title={a.kind === "tailscale" ? "Works wherever the phone has Tailscale" : "Works on the same Wi-Fi"}>
                        {a.kind === "tailscale" ? "Tailscale" : "Wi-Fi"}
                      </button>
                    {/each}
                  </span>
                {/if}
              </div>
              <p class="im-faint mt-2">Scan it with the iPhone's camera first: the page it opens says whether your
                iPhone reaches this PC.</p>
            </div>
          </div>
        {:else if r && !r.ok}
          <p class="im-detail">{r.reason}</p>
        {:else if r}
          <p class="im-detail">This PC has no network address a phone could use.</p>
        {/if}
      </section>
    {/each}

    <section class="im-guide">
      <div class="im-guide-head"><Icon name="phone" size={14} />On the iPhone, in Shortcuts</div>
      <ol class="im-guide-steps">
        <li>Automation, <b>+</b>, then <b>Message</b>. Sender: <b>Anybody</b>. Pick <b>Run Immediately</b>, then
            New Blank Automation.</li>
        <li>Add <b>Get Contents of URL</b> and paste the address. Under its arrow: Method <b>POST</b>, Request Body
            <b>JSON</b>, and two Text fields: <b>from</b> is Shortcut Input, tapped and changed to <b>Sender</b>;
            <b>text</b> is <b>Shortcut Input</b>.</li>
        <li>Add <b>If</b>: Contents of URL <b>has any value</b>.</li>
        <li>Inside it, add <b>Send Message</b>: the message is <b>Contents of URL</b>, the recipient
            <b>Shortcut Input</b> (hold Recipients to pick it).</li>
      </ol>
      <p class="im-faint">An iPad works the same. It answers the messages it gets; sending first, typing dots,
        tapbacks and photos need a Mac.</p>
      {#if !phoneSlots.length}
        <a class="im-tip" href="#/accounts" onclick={() => play("open")}>
          <Icon name="accounts" size={15} />
          <span><b>First add it on the Accounts page.</b> iMessage, then iPhone or iPad.</span>
          <Icon name="chevron" size={12} />
        </a>
      {/if}
    </section>
    {:else}
    <ReadyHero platform="imessage" title={headline.title} sub={headline.sub} tone={headline.tone} {steps}
               go={!slots.length ? { label: "Add an account", href: "#/accounts" } : null}>
    {#if accts.length}
      <div class="im-runners">
        {#each accts as a (a.id)}
          {@const w = a.web && !a.web.stale ? a.web : null}
          {@const tone = a.state === "crashing" ? "bad" : !alive(a) ? "muted" : (TONE[w?.state ?? ""] ?? "muted")}
          {@const mac = macs[a.id]}
          <div class="im-runner is-{tone}">
            <span class="im-dot"></span>
            <div class="min-w-0 flex-1">
              <div class="im-runner-head">
                <b>iMessage #{a.account ?? 1}</b>
                <span class="im-state">{a.state === "crashing" ? "Keeps stopping" : !alive(a) ? "Stopped"
                  : SAYS[w?.state ?? ""] ?? "Starting"}</span>
                {#if mac}
                  <span class="im-faint">· {mac.live ? "live" : "checking every few seconds"}</span>
                  <span class="im-faint">· Private API {mac.private_api && mac.helper ? "on" : "off"}</span>
                {/if}
              </div>
              {#if w?.detail}<p class="im-detail">{w.detail}</p>{/if}
            </div>
          </div>
        {/each}
      </div>
    {/if}

    </ReadyHero>

    <section class="im-guide">
      <div class="im-guide-head"><Icon name="info" size={14} />On the Mac</div>
      <ol class="im-guide-steps">
        <li>Sign in to iMessage in the Messages app.</li>
        <li>Install <button type="button" class="im-link" onclick={() => go("https://bluebubbles.app/downloads/")}>BlueBubbles Server</button>,
            open it, and set a password.</li>
        <li>Pick how it is reached. Cloudflare gives an address that works from anywhere; the Mac's own address works on your network.</li>
        <li>For typing dots, read receipts and tapbacks, turn on its
            <button type="button" class="im-link" onclick={() => go("https://docs.bluebubbles.app/private-api/")}>Private API</button>.
            It asks for one setting changed on the Mac.</li>
        <li>Keep the Mac awake. <button type="button" class="im-link" onclick={() => go("https://docs.bluebubbles.app/server/basic-guides/preventing-macos-from-sleeping")}>How</button>.</li>
      </ol>
      <a class="im-tip" href="#/accounts" onclick={() => play("open")}>
        <Icon name="accounts" size={15} />
        <span><b>Then add it on the Accounts page.</b> Its address and its password, and Test.</span>
        <Icon name="chevron" size={12} />
      </a>
    </section>
    {/if}
  </div>
{/if}

<style>
  .im { display: flex; flex-direction: column; gap: 14px; }
  .im-skeleton { height: 160px; border-radius: 16px; background: rgb(255 255 255 / 0.03); animation: im-pulse 1.6s ease-in-out infinite; }
  @keyframes im-pulse { 50% { opacity: 0.5; } }

  .im-runners { display: grid; gap: 8px; }
  .im-runner { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border-radius: 12px;
               border: 1px solid var(--color-edge); background: rgb(255 255 255 / 0.025); }
  .im-dot { margin-top: 6px; width: 8px; height: 8px; border-radius: 999px; flex-shrink: 0; background: var(--color-faint); }
  .im-runner.is-good .im-dot { background: #30d158; box-shadow: 0 0 0 4px rgb(48 209 88 / 0.15); }
  .im-runner.is-warn .im-dot { background: var(--color-warn); }
  .im-runner.is-bad .im-dot { background: var(--color-bad); }
  .im-runner-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; font-size: 12.5px; color: var(--color-ink); }
  .im-state { color: var(--color-muted); }
  .im-faint { color: var(--color-faint); font-size: 11.5px; }
  .im-detail { margin-top: 3px; font-size: 11.5px; line-height: 1.45; color: var(--color-muted); }

  .im-guide { display: grid; gap: 10px; padding: 14px; border-radius: 14px; border: 1px solid var(--color-edge);
              background: linear-gradient(180deg, rgb(255 255 255 / 0.025), rgb(0 0 0 / 0.08)); }
  .im-guide-head { display: flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600; color: var(--color-ink); }
  .im-guide-steps { display: grid; gap: 5px; padding-left: 1.25rem; list-style: decimal; font-size: 12px; line-height: 1.5;
                    color: var(--color-muted); }
  .im-link { color: var(--color-accent); text-decoration: underline; text-decoration-color: color-mix(in srgb, var(--color-accent) 40%, transparent);
             text-underline-offset: 2px; }
  .im-link:hover { text-decoration-color: currentColor; }
  .im-tip { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 12px; font-size: 12px;
            color: var(--color-muted); background: rgb(255 255 255 / 0.03); transition: background 0.2s ease; }
  .im-tip:hover { background: rgb(255 255 255 / 0.06); }
  .im-tip b { color: var(--color-ink); font-weight: 600; }
  .im-tip span { flex: 1; min-width: 0; }

  /* The iPhone's address: a QR code on a white plate (scanners want dark on light), and the address beside it. */
  .im-phone { display: grid; gap: 10px; padding: 12px 14px; border-radius: 14px; border: 1px solid var(--color-edge);
              background: rgb(255 255 255 / 0.025); }
  .im-addr { display: flex; gap: 14px; align-items: flex-start; }
  .im-qr { width: 112px; height: 112px; flex-shrink: 0; padding: 6px; border-radius: 12px; background: #fff;
           box-shadow: 0 8px 22px -12px rgb(0 0 0 / 0.6); }
  .im-qr :global(svg) { display: block; width: 100%; height: 100%; }
  .im-addr-label { display: block; font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase;
                   color: var(--color-faint); }
  .im-addr-url { display: block; margin-top: 4px; font-size: 11.5px; line-height: 1.4; word-break: break-all;
                 color: var(--color-ink); user-select: all; }
  .im-kinds { display: inline-flex; gap: 4px; padding: 3px; border-radius: 10px; background: rgb(0 0 0 / 0.22);
              box-shadow: inset 0 0 0 1px var(--color-edge); }
  .im-kind { padding: 3px 9px; border-radius: 7px; font-size: 11.5px; font-weight: 600; color: var(--color-muted);
             transition: background 0.2s ease, color 0.2s ease; }
  .im-kind:hover { color: var(--color-ink); }
  .im-kind.is-on { color: var(--color-ink); background: color-mix(in srgb, #30d158 22%, transparent);
                   box-shadow: inset 0 0 0 1px color-mix(in srgb, #30d158 45%, transparent); }
  .im-warn { display: flex; gap: 6px; align-items: flex-start; padding: 8px 10px; border-radius: 10px; font-size: 12px;
             line-height: 1.45; color: var(--color-warn); background: color-mix(in srgb, var(--color-warn) 10%, transparent); }
  .im-warn :global(svg) { margin-top: 2px; flex-shrink: 0; }
  @media (max-width: 520px) {
    .im-addr { flex-direction: column; }
  }
</style>
