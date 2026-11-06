<script lang="ts">
  /**
   * What this profile saw online in its free time (app/utils/web/journal.py): each page, its site and what it
   * thought of it, newest first, and a way to send it browsing now. While it browses, the page it is on shows here
   * as it goes, with the step it is at (app/web/routes/web_routes.py). It brings these up in chats by itself, when
   * they fit; one forgotten here never comes up.
   */
  import { onMount } from "svelte";
  import { api, type WebJournal, type WebNow, type WebSeen } from "../api";
  import { usePersona } from "./context";
  import { play } from "../uisound";
  import { toast } from "../stores";
  import { openUrl } from "../window";
  import { ago } from "../accounts/condition";
  import { HOUR_MINUTE, fmtDate } from "../fmt";
  import Button from "../components/Button.svelte";
  import Icon from "../components/Icon.svelte";

  const persona = usePersona() || "default";
  const SHOWN = 8;

  let data = $state<WebJournal | null>(null);
  let now = $state<WebNow | null>(null);
  let starting = $state(false);
  let clock = $state(Date.now() / 1000);

  /** This profile is the one browsing, now. */
  const mine = $derived(!!now?.busy && now.persona === persona);
  /** Another profile is: one at a time. */
  const elsewhere = $derived(!!now?.busy && now.persona !== persona);

  const status = $derived.by(() => {
    if (!data) return "";
    if (!data.free_time) return "Off. Settings, AI behaviour, The web.";
    if (elsewhere) return `${now?.name || "Another profile"} is browsing right now.`;
    if (data.next_at && data.next_at > clock) return `Next look around ${fmtDate(data.next_at * 1000, HOUR_MINUTE)}.`;
    return "A few times a day, while one of its accounts runs.";
  });

  /** A site's own colour, the same every time. */
  function hue(site: string): number {
    let h = 7;
    for (const ch of site || "?") h = (h * 31 + ch.charCodeAt(0)) % 360;
    return h;
  }

  async function load() {
    try {
      data = await api.webJournal(persona);
    } catch {
      /* the next look */
    }
  }

  let lastStep = "";
  async function poll() {
    try {
      const was = mine;
      now = await api.webNow();
      if (mine && now.step && now.step !== lastStep) {
        lastStep = now.step;
        play("tick", { level: 0.4 });
      }
      if (was && !now.busy) {
        // Done: what it kept arrives in the list.
        play("done");
        await load();
      }
    } catch {
      /* the next look */
    }
  }

  onMount(() => {
    load();
    let alive = true;
    (async () => {
      while (alive) {
        await poll();
        clock = Date.now() / 1000;
        await new Promise((r) => setTimeout(r, now?.busy ? 1800 : 15000));
      }
    })();
    return () => {
      alive = false;
    };
  });

  async function browseNow() {
    if (starting || now?.busy) return;
    starting = true;
    play("open");
    try {
      const r: any = await api.webBrowseNow(persona);
      if (r?.ok === false) toast(r.reason || "It could not start.", "info");
      await poll();
    } catch (e: any) {
      toast(e?.message || "It could not start.", "err");
    } finally {
      starting = false;
    }
  }

  function open(e: WebSeen) {
    play("tap");
    openUrl(e.url);
  }

  async function forget(e: WebSeen) {
    play("delete");
    try {
      const r: any = await api.webForget(persona, e.ts);
      if (data) data = { ...data, entries: r.entries ?? data.entries.filter((x) => x.ts !== e.ts) };
    } catch (err: any) {
      toast(err?.message || "Could not forget it.", "err");
    }
  }
</script>

<div class="wj">
  {#if mine && now}
    <!-- Browsing now: the page it is on, and what it is doing. -->
    <div class="wj-live">
      <div class="wj-screen">
        {#if now.shot}
          {#key now.shot_at}<img class="wj-shot" src={now.shot} alt="The page it is on" />{/key}
        {:else}
          <div class="wj-screen-wait"><Icon name="globe" size={22} /></div>
        {/if}
        <span class="wj-tag"><i aria-hidden="true"></i>Browsing now</span>
      </div>
      {#key now.step}<p class="wj-step">{now.step || "Getting started"}</p>{/key}
    </div>
  {:else}
    <div class="wj-head">
      <p class="wj-status">{status}</p>
      <Button size="sm" kind="ghost" loading={starting} disabled={elsewhere || !data?.free_time} onclick={browseNow}>
        {#if !starting}<Icon name="globe" size={13} />{/if}Browse now
      </Button>
    </div>
  {/if}

  {#if data?.entries.length}
    <ul class="wj-list">
      {#each data.entries.slice(0, SHOWN) as e (e.ts)}
        <li class="wj-item">
          <span class="wj-badge" style="--h: {hue(e.site)}" aria-hidden="true">{(e.site || "?").charAt(0).toUpperCase()}</span>
          <div class="wj-body">
            <button type="button" class="wj-title" title={e.url} onclick={() => open(e)}>{e.title || e.site}</button>
            <span class="wj-meta">{e.site} · {ago(e.ts, clock)}</span>
            <p class="wj-note">{e.note}</p>
          </div>
          <button type="button" class="wj-forget" title="Forget it" aria-label="Forget {e.title || e.site}"
                  onclick={() => forget(e)}>
            <Icon name="trash" size={13} />
          </button>
        </li>
      {/each}
    </ul>
  {:else if data}
    <p class="wj-empty">Nothing yet.</p>
  {/if}
</div>

<style>
  .wj { display: flex; flex-direction: column; gap: 12px; }
  .wj-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .wj-status { min-width: 0; font-size: 12px; color: var(--color-muted); }

  /* ── Browsing now ── the page in a soft frame lit by the profile's colour. */
  .wj-live { display: flex; flex-direction: column; gap: 9px; }
  .wj-screen {
    position: relative;
    overflow: hidden;
    aspect-ratio: 1280 / 900;
    border-radius: 14px;
    background: rgb(0 0 0 / 0.3);
    box-shadow: 0 14px 34px -18px color-mix(in srgb, var(--persona-color, var(--color-accent)) 70%, transparent),
                inset 0 0 0 1px color-mix(in srgb, var(--persona-color, var(--color-accent)) 30%, transparent);
  }
  .wj-shot { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; object-position: top;
             animation: wj-in 0.5s var(--swift) both; }
  @keyframes wj-in { from { opacity: 0.35; } }
  .wj-screen-wait { position: absolute; inset: 0; display: grid; place-items: center; color: var(--color-faint);
                    animation: wj-breathe 1.6s ease-in-out infinite; }
  @keyframes wj-breathe { 50% { opacity: 0.4; } }
  .wj-tag {
    position: absolute;
    left: 10px;
    top: 10px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 9px 4px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 650;
    color: #fff;
    background: rgb(10 10 14 / 0.62);
    backdrop-filter: blur(8px);
  }
  .wj-tag i { width: 7px; height: 7px; border-radius: 999px; background: var(--color-good);
              box-shadow: 0 0 0 0 var(--color-good); animation: wj-pulse 1.6s ease-out infinite; }
  @keyframes wj-pulse { 70% { box-shadow: 0 0 0 7px transparent; } 100% { box-shadow: 0 0 0 0 transparent; } }
  .wj-step { font-size: 12.5px; color: var(--color-ink); animation: wj-step 0.35s var(--swift) both; }
  @keyframes wj-step { from { opacity: 0; transform: translateY(3px); } }

  /* ── What it saw ── */
  .wj-list { display: flex; flex-direction: column; gap: 2px; }
  .wj-item {
    position: relative;
    display: flex;
    align-items: flex-start;
    gap: 11px;
    padding: 9px 8px;
    border-radius: 12px;
    transition: background-color 0.15s ease;
  }
  .wj-item:hover { background: rgb(255 255 255 / 0.035); }
  .wj-badge {
    display: grid;
    width: 28px;
    height: 28px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 700;
    color: hsl(var(--h) 85% 88%);
    background: linear-gradient(150deg, hsl(var(--h) 55% 42%), hsl(calc(var(--h) + 35) 50% 28%));
    box-shadow: 0 6px 14px -8px hsl(var(--h) 70% 35% / 0.9);
  }
  .wj-body { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 1px; }
  .wj-title { overflow: hidden; text-align: left; font-size: 13px; font-weight: 600; color: var(--color-ink);
              white-space: nowrap; text-overflow: ellipsis; }
  .wj-title:hover { color: var(--color-accent); text-decoration: underline; text-underline-offset: 3px; }
  .wj-meta { font-size: 11px; color: var(--color-faint); }
  .wj-note { margin-top: 3px; font-size: 12px; line-height: 1.5; color: var(--color-muted); font-style: italic; }
  .wj-forget {
    display: grid;
    width: 26px;
    height: 26px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 8px;
    color: var(--color-faint);
    opacity: 0;
    transition: opacity 0.15s ease, color 0.15s ease, background-color 0.15s ease;
  }
  .wj-item:hover .wj-forget, .wj-forget:focus-visible { opacity: 1; }
  .wj-forget:hover { color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 12%, transparent); }
  .wj-empty { font-size: 12px; color: var(--color-faint); }
  :global(:root[data-motion="off"]) .wj-shot, :global(:root[data-motion="off"]) .wj-step { animation: none; }
</style>
