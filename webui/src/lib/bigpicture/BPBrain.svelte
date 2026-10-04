<script lang="ts">
  /**
   * Which AI is doing the work: the model that answered last, pulsing each time
   * it answers again, what it has done today, the chain of models that take
   * over when one is busy, and gauges for what is left of its limits.
   */
  import ProviderTile from "../components/ProviderTile.svelte";
  import { providerById, shortModel, type Plan } from "../providers";
  import type { ModelUsage } from "../modelusage";
  import Counter from "./Counter.svelte";

  type Active = { provider: string; model: string; at: number; ms: number; ok: boolean };

  let {
    active = null,
    forName = "",
    helper = null,
    pulse = 0,
    plan = null,
    models = [],
    now = 0,
  }: {
    active?: Active | null;
    /** Whose conversation this model is the one for, when it is the one on stage. */
    forName?: string;
    helper?: { model: string; job: string; at: number } | null;
    pulse?: number;
    plan?: Plan | null;
    models?: ModelUsage[];
    now?: number;
  } = $props();
  const JOB: Record<string, string> = { small: "background work", vision: "reading a picture", stt: "hearing a voice note", tts: "speaking" };

  const cur = $derived(active ?? (plan?.replies?.[0] ? { ...plan.replies[0], at: 0, ms: 0, ok: true } : null));
  const usageFor = (provider: string, model: string) => models.find((m) => m.provider === provider && m.model === model);
  const u = $derived(cur ? usageFor(cur.provider, cur.model) : undefined);
  /** 1200 as "1.2k": a chip has room for a number, not for six digits. */
  const fmtTokens = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));
  const avg = $derived(u && u.today.requests ? `${(u.today.ms / u.today.requests / 1000).toFixed(1)}s` : "–");
  function ago(ts: number): string {
    const s = Math.max(0, now - ts);
    if (s < 5) return "just now";
    if (s < 60) return `${Math.floor(s)}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    return `${Math.floor(s / 3600)}h ago`;
  }
  const WINDOW: Record<string, string> = { day: "today", minute: "this minute", hour: "this hour", month: "this month", second: "now" };
  /** An arc over the top half of a circle: from the left end round to `f` of the way. */
  function arc(f: number): string {
    const a = Math.PI * (1 - Math.max(0, Math.min(1, f)));
    const x = 50 + 40 * Math.cos(a), y = 50 - 40 * Math.sin(a);
    return `M10,50 A40,40 0 0 1 ${x.toFixed(2)},${y.toFixed(2)}`;
  }
</script>

<section class="bbr">
  <header class="bp-label">Brain <span class="bbr-live" class:is-on={!!active && now - active.at < 8}>live</span></header>
  {#if cur}
    <div class="bbr-hero">
      <span class="bbr-tile">
        {#key pulse}<span class="bbr-pulse" aria-hidden="true"></span>{/key}
        <ProviderTile id={cur.provider} size={68} />
      </span>
      <span class="min-w-0">
        <span class="bbr-model" title={cur.model}>{shortModel(cur.model)}</span>
        <span class="bbr-sub">
          {providerById(cur.provider)?.name ?? cur.provider}{#if forName} · writing to {forName}{:else if active} · answered {ago(active.at)}{:else} · first choice{/if}
        </span>
      </span>
    </div>
    {#if helper && now - helper.at < 15}
      <div class="bbr-helper">Also working: <b>{shortModel(helper.model)}</b>, {JOB[helper.job] ?? helper.job}</div>
    {/if}
    <div class="bbr-nums">
      <div><b><Counter value={u?.today.requests ?? 0} /></b><span>answers today</span></div>
      <div><b><Counter value={(u?.today.in ?? 0) + (u?.today.out ?? 0)} /></b><span>tokens</span></div>
      <div><b>{avg}</b><span>per answer</span></div>
    </div>
    {#if plan?.replies?.length}
      <!-- Every model that can write a reply, and what each has actually done
           today: which one is carrying the work is the thing worth seeing. -->
      <div class="bbr-chain">
        {#each plan.replies as e, i (e.provider + e.model)}
          {@const eu = usageFor(e.provider, e.model)}
          <span class="bbr-chip" class:is-on={cur.provider === e.provider && cur.model === e.model}
                class:is-idle={!eu}
                title="{shortModel(e.model)}{eu ? `: ${eu.today.requests} answer${eu.today.requests === 1 ? '' : 's'} today, ${fmtTokens(eu.today.in + eu.today.out)} tokens` : ': nothing today'}">
            <ProviderTile id={e.provider} size={18} /><span class="bbr-chip-name">{shortModel(e.model)}</span>
            {#if eu?.today.requests}<b class="bbr-chip-n">{eu.today.requests}</b>{/if}
            {#if i === 0}<em>1st</em>{/if}
          </span>
        {/each}
      </div>
    {/if}
    {#if u?.limits?.length}
      <div class="bbr-gauges">
        {#each u.limits.slice(0, 2) as g (g.what + g.window)}
          {@const f = g.limit ? g.remaining / g.limit : 1}
          <div class="bbr-gauge" data-tone={f < 0.1 ? "bad" : f < 0.3 ? "warn" : "ok"}>
            <svg viewBox="0 0 100 56" aria-hidden="true">
              <path d={arc(1)} class="track" />
              <path d={arc(f)} class="fill" />
            </svg>
            <b><Counter value={g.remaining} /></b>
            <span>{g.what} left {WINDOW[g.window] ?? ""}</span>
          </div>
        {/each}
      </div>
    {/if}
  {:else}
    <p class="bbr-empty">No model has answered yet.</p>
  {/if}
</section>

<style>
  .bbr {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 18px;
    border-radius: 24px;
    background: rgb(255 255 255 / 0.045);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.07);
    backdrop-filter: blur(20px);
  }
  .bbr-live { margin-left: auto; padding: 1px 8px; border-radius: 999px; font-size: 10px; color: var(--bp-faint); background: rgb(255 255 255 / 0.06); transition: color 0.3s ease, background-color 0.3s ease; }
  .bbr-live.is-on { color: #fff; background: var(--color-good); box-shadow: 0 0 22px color-mix(in srgb, var(--color-good) 42%, transparent); }
  .bbr-hero { display: flex; align-items: center; gap: 16px; }
  .bbr-tile { position: relative; display: grid; place-items: center; }
  .bbr-pulse {
    position: absolute;
    inset: -6px;
    border-radius: 26px;
    pointer-events: none;
    box-shadow: 0 0 0 2px var(--color-accent), 0 0 48px color-mix(in srgb, var(--color-accent) 42%, transparent);
    animation: bbr-pulse 1.4s ease-out forwards;
  }
  @keyframes bbr-pulse { from { opacity: 1; transform: scale(0.9); } to { opacity: 0; transform: scale(1.5); } }
  .bbr-model { display: block; overflow: hidden; font-size: 24px; font-weight: 750; letter-spacing: -0.02em; color: #fff; text-overflow: ellipsis; white-space: nowrap; }
  .bbr-sub { display: block; font-size: 12.5px; color: var(--bp-muted); }
  .bbr-helper { margin-top: -6px; font-size: 12px; color: var(--bp-faint); animation: bbr-fade 0.5s ease both; }
  .bbr-helper b { color: var(--bp-muted); font-weight: 600; }
  @keyframes bbr-fade { from { opacity: 0; transform: translateY(-4px); } }
  .bbr-nums { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
  .bbr-nums div { display: flex; flex-direction: column; padding: 10px 12px; border-radius: 14px; background: rgb(0 0 0 / 0.2); }
  .bbr-nums b { font-size: 20px; font-weight: 750; color: #fff; }
  .bbr-nums span { font-size: 10.5px; color: var(--bp-faint); }
  .bbr-chain { display: flex; flex-wrap: wrap; gap: 6px; }
  .bbr-chip {
    display: inline-flex;
    min-width: 0;
    max-width: 100%;
    align-items: center;
    gap: 6px;
    padding: 4px 10px 4px 5px;
    border-radius: 999px;
    font-size: 12px;
    color: var(--bp-muted);
    background: rgb(255 255 255 / 0.05);
    transition: color 0.3s ease, background-color 0.3s ease, box-shadow 0.3s ease;
  }
  .bbr-chip-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bbr-chip em { flex-shrink: 0; font-style: normal; font-size: 10px; color: var(--bp-faint); }
  /* How many that model has answered today, right on it. */
  .bbr-chip-n {
    flex-shrink: 0;
    min-width: 17px;
    padding: 0 5px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 700;
    text-align: center;
    color: #fff;
    background: rgb(255 255 255 / 0.14);
    font-variant-numeric: tabular-nums;
  }
  .bbr-chip.is-on .bbr-chip-n { background: rgb(255 255 255 / 0.28); }
  /* One that has not been needed today sits back rather than looking broken. */
  .bbr-chip.is-idle { opacity: 0.55; }
  .bbr-chip.is-on { color: #fff; background: color-mix(in srgb, var(--color-accent) 30%, transparent); box-shadow: 0 0 18px -4px var(--color-accent); }
  .bbr-gauges { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  /* A short screen: the gauges give way, so the panels under the Brain keep room to say something. */
  @media (max-height: 800px) {
    .bbr-gauges { display: none; }
  }
  .bbr-gauge { position: relative; display: flex; flex-direction: column; align-items: center; text-align: center; }
  /* overflow: visible, or the glow is sliced off flat where it crosses the
     viewBox: the arc sits near the bottom edge, so its bloom was cut into a
     hard horizontal line right under it. */
  .bbr-gauge svg { width: 100%; max-width: 130px; overflow: visible; }
  .bbr-gauge path { fill: none; stroke-width: 8; stroke-linecap: round; }
  .bbr-gauge .track { stroke: rgb(255 255 255 / 0.08); }
  .bbr-gauge .fill { stroke: var(--color-accent); filter: drop-shadow(0 0 14px color-mix(in srgb, var(--color-accent) 42%, transparent)); transition: d 0.8s var(--swift); }
  .bbr-gauge[data-tone="warn"] .fill { stroke: var(--color-warn); filter: drop-shadow(0 0 14px color-mix(in srgb, var(--color-warn) 42%, transparent)); }
  .bbr-gauge[data-tone="bad"] .fill { stroke: var(--color-bad); filter: drop-shadow(0 0 14px color-mix(in srgb, var(--color-bad) 42%, transparent)); }
  .bbr-gauge b { margin-top: -22px; font-size: 18px; font-weight: 750; color: #fff; }
  .bbr-gauge span { font-size: 10.5px; color: var(--bp-faint); }
  .bbr-empty { font-size: 13px; color: var(--bp-faint); }
  :global(:root[data-motion="off"]) .bbr-pulse { animation-duration: 0.01s; }
</style>
