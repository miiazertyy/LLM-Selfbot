<script lang="ts">
  /**
   * An account that needs a person right now (a check to solve, a code to type, an email check to finish): a card on
   * every page, with a sound, until the account is past it. The runners already wait for the person; until now the
   * panel was told and did nothing with it (app/web/attention.py says it now).
   *
   * Whether it is still needed is read from the accounts themselves, so a card goes by itself when the check is
   * solved or the code goes in, with a sound of its own. One that no account state stands behind (Discord's captcha)
   * goes after a few minutes, or with its close button.
   */
  import { onMount } from "svelte";
  import { flip } from "svelte/animate";
  import { cubicIn, cubicOut } from "svelte/easing";
  import { api } from "../api";
  import { subscribeEvents } from "../logsocket";
  import { platformName } from "../platforms";
  import { motionEnabled } from "../stores";
  import { play } from "../uisound";
  import Icon from "./Icon.svelte";
  import PlatformMark from "./PlatformMark.svelte";

  type Ask = { id: string; platform: string; what: string; text: string; at: number };

  /** Not tied to an account state that ends: put away by itself after this long. */
  const LONE_MS = 3 * 60 * 1000;

  let asks = $state<Ask[]>([]);
  /** Put away by hand: kept away while the account stays stuck on the same thing. The account asking again (a new
   *  event), or getting past it and stuck again later, brings it back. */
  const dismissed = new Set<string>();
  const keyOf = (a: { id: string; what: string }) => `${a.id}:${a.what}`;

  /** The states that mean an account is still waiting for its person. */
  const waiting = (state?: string) => state === "needs-you" || state === "awaiting-verification";

  function add(a: Ask) {
    const i = asks.findIndex((x) => x.id === a.id);
    if (i >= 0) {
      // The same account asking again, or saying something new (no code in the mail: now it needs typing).
      if (asks[i].what === a.what) return;
      asks[i] = a;
    } else {
      asks = [...asks, a];
    }
    // Looking in the mailboxes is the app's own work: softer than a check only a person can solve.
    play(a.what === "code_mail" ? "info" : "err");
  }

  function close(id: string, byHand = false) {
    if (byHand) for (const a of asks) if (a.id === id) dismissed.add(keyOf(a));
    asks = asks.filter((a) => a.id !== id);
  }

  /** What the accounts say now: cards the account is past go (with a sound), and any it is waiting on come. */
  async function look() {
    let rows: any[];
    try {
      rows = (await api.accounts()).accounts ?? [];
    } catch {
      return;
    }
    const byId = new Map(rows.map((r) => [r.id, r]));
    const now = Date.now();
    for (const a of [...asks]) {
      const row = byId.get(a.id);
      const lone = a.platform === "discord";
      if (lone ? now - a.at > LONE_MS : !row || !waiting(row.web?.state)) {
        close(a.id);
        if (!lone) play("done");
      }
    }
    for (const r of rows) {
      const st = r.web?.state;
      if (!waiting(st)) {
        for (const k of [...dismissed]) if (k.startsWith(`${r.id}:`)) dismissed.delete(k);
        continue;
      }
      if (asks.some((a) => a.id === r.id)) continue;
      const detail = String(r.web?.detail || "");
      // Only what a person can do: a code, a check, an email check. Telegram asking it to wait is not one.
      if (r.platform === "telegram" || r.platform === "whatsapp" || r.platform === "minecraft") continue;
      const what = st === "awaiting-verification" ? "verify" : /code/i.test(detail) ? "code" : /check|captcha|puzzle/i.test(detail) ? "captcha" : "";
      if (!what || dismissed.has(keyOf({ id: r.id, what }))) continue;
      add({ id: r.id, platform: r.platform, what, text: detail, at: now });
    }
  }

  onMount(() => {
    look();
    const off = subscribeEvents("attention", (evt) => {
      if (!evt) return void look();      // reconnected: whatever was missed is in the accounts' states
      dismissed.delete(keyOf({ id: String(evt.id), what: String(evt.what) }));
      add({ id: String(evt.id), platform: String(evt.platform), what: String(evt.what), text: String(evt.text),
            at: Date.now() });
    });
    // Often while a card is up, so it goes the moment the check is solved; rarely otherwise.
    let timer = 0;
    const tick = () => {
      if (document.visibilityState === "visible") look();
      timer = window.setTimeout(tick, asks.length ? 3000 : 20000);
    };
    timer = window.setTimeout(tick, 3000);
    return () => {
      off();
      clearTimeout(timer);
    };
  });

  function slide(_node: Element, { going = false }: { going?: boolean }) {
    return {
      duration: $motionEnabled ? (going ? 220 : 340) : 0,
      easing: going ? cubicIn : cubicOut,
      css: (t: number, u: number) => `transform: translate3d(0, ${-u * 24}px, 0); opacity: ${Math.min(1, t * 1.4)}`,
    };
  }
</script>

{#if asks.length}
  <div class="ny-stack" role="alert" aria-live="assertive">
    {#each asks as a (a.id)}
      <div class="ny-card is-{a.what}" animate:flip={{ duration: $motionEnabled ? 260 : 0, easing: cubicOut }}
           in:slide={{}} out:slide={{ going: true }}>
        <!-- The site's own mark, with a small badge of what it is: a person needed, or the app at work on a code. -->
        <span class="ny-mark">
          <PlatformMark platform={a.platform} size={22} />
          <span class="ny-badge" aria-hidden="true"><Icon name={a.what === "code_mail" ? "inbox" : "alert"} size={9} /></span>
        </span>
        <div class="min-w-0 flex-1">
          <p class="ny-title">{a.what === "code_mail" ? `Getting ${platformName(a.platform)}'s code` : `${platformName(a.platform)} needs you`}</p>
          <p class="ny-text">{a.text}</p>
          {#if a.what === "code"}
            <a class="ny-link" href="#/accounts">Open Accounts</a>
          {/if}
        </div>
        <button type="button" class="ny-x" aria-label="Close" onclick={() => close(a.id, true)}>
          <Icon name="close" size={12} />
        </button>
      </div>
    {/each}
  </div>
{/if}

<style>
  /* Under the title bar at the right, clear of the sidebar's rail in a narrow window: it was a flat brown slab across
     the rail and the page's heading (2026-11-11). Now the corner notices' card (Notices.svelte): solid, a touch of its
     colour, lifted off the page by a soft shadow. */
  .ny-stack {
    position: fixed;
    z-index: 10001;
    top: calc(52px + env(safe-area-inset-top, 0px));
    right: calc(1rem + env(safe-area-inset-right, 0px));
    display: flex;
    flex-direction: column;
    gap: 8px;
    width: min(340px, calc(100vw - 6rem));
  }
  .ny-card {
    --tone: var(--color-warn);
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 12px 10px 12px 12px;
    border-radius: 16px;
    /* The theme's own card: the warning's colour is the badge's alone (a warm tint read as brown in a cool theme). */
    background: color-mix(in srgb, var(--color-accent) 6%, var(--color-card));
    box-shadow: 0 14px 34px -14px rgb(0 0 0 / 0.65), 0 3px 10px -4px rgb(0 0 0 / 0.4);
    color: var(--color-ink);
  }
  .ny-card.is-code_mail {
    --tone: var(--color-accent);
  }
  .ny-mark {
    position: relative;
    display: inline-flex;
    flex-shrink: 0;
    margin-top: 1px;
  }
  .ny-badge {
    position: absolute;
    right: -5px;
    bottom: -4px;
    display: grid;
    width: 15px;
    height: 15px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-bg);
    background: var(--tone);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-accent) 6%, var(--color-card));
  }
  .ny-title {
    font-size: 13px;
    font-weight: 650;
    line-height: 1.3;
  }
  .ny-text {
    margin-top: 3px;
    color: var(--color-muted);
    font-size: 12px;
    line-height: 1.45;
    overflow-wrap: anywhere;
  }
  .ny-link {
    display: inline-flex;
    margin-top: 8px;
    padding: 4px 10px;
    border-radius: 9px;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 16%, transparent);
    font-size: 12px;
    font-weight: 600;
    transition: background-color 0.15s ease;
  }
  .ny-link:hover {
    background: color-mix(in srgb, var(--color-accent) 24%, transparent);
  }
  .ny-x {
    display: grid;
    width: 22px;
    height: 22px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 7px;
    color: var(--color-faint);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .ny-x:hover {
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.08);
  }
</style>
