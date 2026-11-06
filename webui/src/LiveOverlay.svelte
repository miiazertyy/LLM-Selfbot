<script lang="ts">
  /**
   * The page for OBS (a Browser source, /?live=tiktok_1): the persona's answers
   * on a TikTok LIVE, each one shown as a caption while its voice plays, then
   * gone. Transparent everywhere else, so it sits over the stream. OBS picks up
   * the sound itself ("Control audio via OBS" on the source).
   *
   * How it shows them is in Settings, TikTok, OBS page (tiktok.live.overlay_*),
   * handed over with the feed: how long each one stays, where, how big, which
   * look, and the comment it answers above it.
   */
  import { onMount } from "svelte";
  import { api } from "./lib/api";

  const account = new URLSearchParams(location.search).get("live") || "";
  type Say = { id: string; to: string; text: string; audio: string[]; comment: string };
  type Look = { seconds: number; position: string; comment: boolean; size: string; theme: string };
  let shown = $state<Say | null>(null);
  let showing = $state(false);
  let look = $state<Look>({ seconds: 8, position: "bottom", comment: true, size: "medium", theme: "dark" });
  const seen = new Set<string>();
  const queue: Say[] = [];
  let busy = false;
  let first = true;

  function playAll(files: string[]): Promise<void> {
    return new Promise((resolve) => {
      const next = () => {
        const f = files.shift();
        if (!f) return resolve();
        const a = new Audio(api.liveAudio(account, f));
        a.onended = next;
        a.onerror = next;
        a.play().catch(next);
      };
      next();
    });
  }

  async function run() {
    if (busy) return;
    const say = queue.shift();
    if (!say) return;
    busy = true;
    shown = say;
    showing = true;
    // Up for as long as the settings say, and never gone before its voice is.
    const minimum = new Promise((r) => setTimeout(r, Math.max(3, look.seconds || 8) * 1000));
    await Promise.all([playAll([...say.audio]), minimum]);
    showing = false;
    await new Promise((r) => setTimeout(r, 450));
    busy = false;
    run();
  }

  async function poll() {
    try {
      const r: any = await api.liveFeed(account);
      if (r?.overlay) look = { ...look, ...r.overlay };
      for (const l of r?.feed || []) {
        if (l.t !== "live_say" || !l.id || seen.has(l.id)) continue;
        seen.add(l.id);
        // Opened mid-LIVE: what was said before is not said again.
        if (!first) queue.push({ id: l.id, to: l.to || "", text: l.text || "", audio: l.audio || [], comment: l.comment || "" });
      }
      first = false;
      run();
    } catch {
      // the app is restarting: the next look catches up
    }
  }

  onMount(() => {
    // Marked, so its see-through page is its own: its styles are in the app's one stylesheet too.
    document.documentElement.classList.add("is-live-overlay");
    document.documentElement.style.background = "transparent";
    document.body.style.background = "transparent";
    poll();
    const t = setInterval(poll, 1500);
    return () => clearInterval(t);
  });
</script>

<div class="ov is-{look.position} is-{look.size}">
  {#if shown}
    <div class="ov-cap is-{look.theme}" class:is-on={showing}>
      {#if look.comment && shown.comment && shown.to}
        <span class="ov-q"><b>{shown.to}</b> {shown.comment}</span>
      {:else if shown.to}
        <span class="ov-to">To {shown.to}</span>
      {/if}
      <span class="ov-text">{#if look.theme === "tiktok"}<i class="ov-host">Host</i>{/if}{shown.text}</span>
    </div>
  {/if}
</div>

<style>
  /* Only on the OBS page (main.ts mounts this alone there): Svelte bundles these into the app's stylesheet too,
     where unscoped they hid the whole app. */
  :global(html.is-live-overlay), :global(html.is-live-overlay body) { background: transparent !important; }
  .ov {
    --ov-text: 26px;
    position: fixed;
    inset: 0;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    padding: 0 6vw 7vh;
    pointer-events: none;
    font-family: system-ui, "Segoe UI", sans-serif;
  }
  .ov.is-middle { align-items: center; padding: 0 6vw; }
  .ov.is-top { align-items: flex-start; padding: 7vh 6vw 0; }
  .ov.is-small { --ov-text: 20px; }
  .ov.is-large { --ov-text: 36px; }
  .ov-cap {
    display: flex;
    max-width: 900px;
    flex-direction: column;
    gap: 5px;
    padding: calc(var(--ov-text) * 0.54) calc(var(--ov-text) * 0.85);
    border-radius: calc(var(--ov-text) * 0.85);
    background: rgb(12 12 16 / 0.82);
    box-shadow: 0 0 0 1px rgb(255 255 255 / 0.1), 0 18px 40px -12px rgb(0 0 0 / 0.6),
                -3px -2px 0 rgb(37 244 238 / 0.55), 3px 2px 0 rgb(254 44 85 / 0.55);
    opacity: 0;
    transform: translateY(18px) scale(0.96);
    transition: opacity 0.35s ease, transform 0.45s cubic-bezier(0.3, 1.3, 0.5, 1);
  }
  .ov.is-top .ov-cap:not(.is-on) { transform: translateY(-18px) scale(0.96); }
  .ov-cap.is-on { opacity: 1; transform: none; }
  .ov-to { font-size: calc(var(--ov-text) * 0.58); font-weight: 800; letter-spacing: 0.03em; color: #fe2c55; }
  .ov-q {
    font-size: calc(var(--ov-text) * 0.62);
    font-weight: 500;
    line-height: 1.3;
    color: rgb(255 255 255 / 0.72);
  }
  .ov-q b { font-weight: 800; color: #fe2c55; }
  .ov-text { font-size: var(--ov-text); font-weight: 700; line-height: 1.25; color: #fff; }

  /* Light: a white card. */
  .ov-cap.is-light {
    background: rgb(255 255 255 / 0.95);
    box-shadow: 0 0 0 1px rgb(0 0 0 / 0.06), 0 18px 44px -14px rgb(0 0 0 / 0.45);
  }
  .ov-cap.is-light .ov-text { color: #121218; }
  .ov-cap.is-light .ov-q { color: rgb(18 18 24 / 0.62); }

  /* TikTok: a line of its LIVE chat, see-through, with the Host badge. */
  .ov-cap.is-tiktok {
    border-radius: 999px;
    padding: calc(var(--ov-text) * 0.42) calc(var(--ov-text) * 0.9);
    background: rgb(0 0 0 / 0.42);
    -webkit-backdrop-filter: blur(10px);
    backdrop-filter: blur(10px);
    box-shadow: none;
    gap: 2px;
  }
  .ov-cap.is-tiktok .ov-q { color: rgb(255 255 255 / 0.66); }
  .ov-cap.is-tiktok .ov-q b { color: rgb(255 255 255 / 0.66); font-weight: 600; }
  .ov-cap.is-tiktok .ov-text { font-weight: 600; text-shadow: 0 1px 2px rgb(0 0 0 / 0.35); }
  .ov-host {
    display: inline-block;
    margin-right: 0.4em;
    padding: 0.1em 0.45em;
    border-radius: 0.35em;
    background: #fe2c55;
    font-size: 0.55em;
    font-style: normal;
    font-weight: 800;
    vertical-align: 0.25em;
    color: #fff;
  }
</style>
