<script lang="ts">
  /**
   * The strip along the bottom: today's numbers rolling up as replies go out,
   * the last day's activity as a wave, and every account's live state.
   */
  import Avatar from "../components/Avatar.svelte";
  import Counter from "./Counter.svelte";
  import BPWave from "./BPWave.svelte";

  type Acct = { id: string; name: string; avatar?: string; state: string; ping?: number | null; mood?: string };
  let {
    today = { replies: 0, people: 0, tokens: 0, requests: 0 },
    hourly = [],
    accounts = [],
  }: {
    today?: { replies: number; people: number; tokens: number; requests: number };
    hourly?: number[];
    accounts?: Acct[];
  } = $props();
</script>

<section class="bst">
  <div class="bst-nums">
    <div><b><Counter value={today.replies} /></b><span>replies today</span></div>
    <div><b><Counter value={today.people} /></b><span>people this week</span></div>
    <div><b><Counter value={today.tokens} /></b><span>tokens today</span></div>
    <div><b><Counter value={today.requests} /></b><span>AI requests today</span></div>
  </div>
  <div class="bst-wave">
    <span class="bst-wave-label">Last 24 hours</span>
    <BPWave values={hourly} height={54} label="Replies per hour, the last day" />
  </div>
  <div class="bst-accts">
    {#each accounts as a (a.id)}
      <span class="bst-acct" data-state={a.state} title="{a.name}: {a.state}">
        <span class="bst-acct-av"><Avatar src={a.avatar} name={a.name} size={30} zoom={false} /><i></i></span>
        <span class="min-w-0">
          <span class="bst-acct-name">{a.name}</span>
          <span class="bst-acct-sub">{a.state === "running" ? (a.ping != null ? `${a.ping} ms` : "online") : a.state}{a.mood ? ` · ${a.mood}` : ""}</span>
        </span>
      </span>
    {/each}
  </div>
</section>

<style>
  .bst {
    display: grid;
    grid-template-columns: auto minmax(160px, 1fr) minmax(0, auto);
    align-items: center;
    gap: clamp(16px, 2.5vw, 36px);
    padding: 16px 22px;
    border-radius: 26px;
    background: rgb(255 255 255 / 0.045);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.07);
    backdrop-filter: blur(22px);
  }
  .bst-nums { display: flex; gap: clamp(14px, 2vw, 30px); }
  .bst-nums div { display: flex; flex-direction: column; }
  .bst-nums b { font-size: clamp(24px, 2.4vw, 36px); font-weight: 800; line-height: 1; letter-spacing: -0.03em; color: #fff; }
  .bst-nums span { margin-top: 4px; font-size: 10.5px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--bp-faint); }
  .bst-wave { position: relative; min-width: 0; }
  .bst-wave-label { position: absolute; top: -4px; left: 0; font-size: 10.5px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--bp-faint); }
  /* Many accounts wrap onto a second row rather than pushing the bar past the screen's edge. */
  .bst-accts { display: flex; min-width: 0; flex-wrap: wrap; justify-content: flex-end; gap: 10px; }
  .bst-acct { display: flex; align-items: center; gap: 9px; padding: 6px 12px 6px 6px; border-radius: 999px; background: rgb(0 0 0 / 0.2); }
  .bst-acct-av { position: relative; display: grid; }
  .bst-acct-av i {
    position: absolute;
    right: -1px;
    bottom: -1px;
    width: 10px;
    height: 10px;
    border-radius: 999px;
    background: var(--bp-faint);
    box-shadow: 0 0 0 2px rgb(0 0 0 / 0.6);
  }
  .bst-acct[data-state="running"] .bst-acct-av i { background: var(--color-good); box-shadow: 0 0 0 2px rgb(0 0 0 / 0.6), 0 0 16px color-mix(in srgb, var(--color-good) 42%, transparent); }
  .bst-acct[data-state="crashing"] .bst-acct-av i { background: var(--color-bad); }
  .bst-acct-name { display: block; max-width: 140px; overflow: hidden; font-size: 13px; font-weight: 650; color: #fff; text-overflow: ellipsis; white-space: nowrap; }
  .bst-acct-sub { display: block; font-size: 11px; color: var(--bp-muted); }
</style>
