<script lang="ts">
  /**
   * The Ask box at the top of Settings: say what to change, and the model already set up does it, with the same tools a
   * connected AI app gets and under the same limits (app/utils/appchat.py). Each change comes back as a row with its own
   * Undo. It grows in place.
   *
   * It also notices changes made from outside (a connected AI app), so the settings under it never show an old value.
   */
  import { onMount, tick } from "svelte";
  import { api } from "../api";
  import { settingsSection, toast } from "../stores";
  import { play } from "../uisound";
  import { smoothHeight } from "../smoothheight";
  import { glideTo } from "../smoothscroll";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";

  type Change = { id: string; label: string; for?: string | null; from: string; to: string };
  type Step = { kind: "look" | "change" | "blocked"; text: string; restart?: boolean; change?: Change };
  type Turn = { text: string; steps: Step[]; say: string; error: string; where: string; done: boolean };

  let { open, persona = "", onchanged }: { open: boolean; persona?: string; onchanged: () => void } = $props();

  let text = $state("");
  let turns = $state<Turn[]>([]);
  let undone = $state<Record<string, boolean>>({});
  let busy = $state(false);
  let input = $state<HTMLInputElement | null>(null);
  let log = $state<HTMLElement | null>(null);
  let alive = true;

  const wait = (ms: number) => new Promise((done) => setTimeout(done, ms));

  /** "30 to 20, for Nova. Needs a restart": a persona's text or a new persona has no from and to. */
  function detail(s: Step) {
    const c = s.change!;
    const what = c.from || c.to ? `${c.from} to ${c.to}` : "";
    const whose = c.for && c.for !== "everyone" && what ? `, for ${c.for}` : "";
    return what + whose + (s.restart ? `${what ? ". " : ""}Needs a restart` : "");
  }

  $effect(() => {
    if (open) tick().then(() => input?.focus({ preventScroll: true }));
  });

  async function toBottom() {
    await tick();
    if (log) glideTo(log, log.scrollHeight);
  }

  async function send(e: Event) {
    e.preventDefault();
    const asked = text.trim();
    if (!asked || busy) return;
    const history = turns.flatMap((t) => [
      { role: "user", text: t.text },
      ...(t.say ? [{ role: "assistant", text: t.say }] : []),
    ]);
    busy = true;
    text = "";
    play("send");
    turns.push({ text: asked, steps: [], say: "", error: "", where: "", done: false });
    const turn = turns[turns.length - 1];
    toBottom();
    try {
      const { id } = await api.aiAsk(asked, history, persona);
      await follow(id, turn);
    } catch (err: any) {
      turn.error = err?.message || "That did not work.";
      turn.done = true;
      play("err");
    }
    busy = false;
    toBottom();
    await tick();
    input?.focus({ preventScroll: true });
  }

  /** How the question is going, until it is answered: each step, with its own sound, as it happens. */
  async function follow(id: string, turn: Turn) {
    let seen = 0;
    let changed = false;
    while (alive) {
      await wait(600);
      const job = await api.aiAskStatus(id);
      for (const step of job.steps.slice(seen) as Step[]) {
        if (step.kind === "change") changed = true;
        play(step.kind === "change" ? "done" : step.kind === "blocked" ? "err" : "tick");
      }
      if (job.steps.length !== seen) {
        seen = job.steps.length;
        turn.steps = job.steps;
        toBottom();
      }
      if (job.done) {
        turn.say = job.say;
        turn.error = job.error;
        turn.where = job.where ?? "";
        turn.done = true;
        play(job.error ? "err" : "receive");
        if (changed) onchanged();
        return;
      }
    }
  }

  async function undo(id: string) {
    try {
      await api.aiUndo(id);
      undone[id] = true;
      play("undo");
      onchanged();
    } catch (e: any) {
      play("err");
      toast(e.message, "err");
    }
  }

  // What the list of changes looked like last time: anything different came from outside this page.
  let lastSeen: string | undefined;

  async function watch() {
    if (document.visibilityState !== "visible") return;
    let now: string;
    try {
      const { changes } = await api.aiChanges();
      now = changes.map((c: any) => `${c.id}:${c.undone}`).join();
    } catch {
      return;
    }
    if (lastSeen !== undefined && now !== lastSeen) onchanged();
    lastSeen = now;
  }

  onMount(() => {
    watch();
    const timer = setInterval(watch, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  });
</script>

<div class="ask-box" use:smoothHeight>
  <div>
    {#if open}
      <div class="ask-card">
        {#if turns.length}
          <div class="ask-log" bind:this={log}>
            {#each turns as t, i (i)}
              <p class="ask-you">{t.text}</p>
              {#each t.steps as s, n (n)}
                {#if s.kind === "change" && s.change}
                  <div class="ask-change" class:is-undone={undone[s.change.id]}>
                    <span class="ask-mark"><Icon name={undone[s.change.id] ? "undo" : "check"} size={13} /></span>
                    <span class="min-w-0 flex-1">
                      <span class="font-medium text-ink">{s.change.label}</span>
                      <span class="text-faint">{detail(s)}</span>
                    </span>
                    {#if undone[s.change.id]}
                      <span class="shrink-0 text-faint">Undone</span>
                    {:else}
                      <span class="shrink-0" data-sound="self"><Button kind="ghost" size="sm" onclick={() => undo(s.change!.id)}>Undo</Button></span>
                    {/if}
                  </div>
                {:else}
                  <p class="ask-step" class:is-blocked={s.kind === "blocked"}>{s.text}</p>
                {/if}
              {/each}
              {#if t.say}<p class="ask-say">{t.say}</p>{/if}
              <!-- From what really ran, whatever the model said: the rows above are the truth of it. -->
              {#if t.done && !t.error && !t.steps.some((s) => s.kind === "change")}
                <p class="ask-step">Nothing was changed.</p>
              {/if}
              {#if t.error}
                <p class="ask-error">
                  {t.error}
                  {#if t.where}
                    <button type="button" class="ask-link" onclick={() => settingsSection.set(t.where)}>Open Providers</button>
                  {/if}
                </p>
              {/if}
              {#if !t.done}<p class="ask-step ask-working">Working on it</p>{/if}
            {/each}
          </div>
        {/if}
        <form class="ask-row" onsubmit={send} data-sound="self">
          <span class="ask-mark"><Icon name="sparkle" size={15} /></span>
          <input bind:this={input} bind:value={text} maxlength="2000" disabled={busy} aria-label="Say what to change"
                 placeholder="Say what to change" class="field py-1.5 pl-3 pr-3 text-[13px]" />
          <Button size="sm" disabled={!text.trim() || busy} loading={busy}>
            {#if !busy}<Icon name="send" size={12} />{/if}Send
          </Button>
        </form>
      </div>
    {/if}
  </div>
</div>

<style>
  .ask-box {
    overflow: hidden;
  }
  .ask-card {
    margin-bottom: 16px;
    padding: 10px 12px;
    border-radius: 16px;
    background: color-mix(in srgb, var(--color-accent) 7%, transparent);
  }
  .ask-log {
    display: flex;
    max-height: 320px;
    flex-direction: column;
    gap: 8px;
    padding: 4px 2px 12px;
    overflow-y: auto;
  }
  .ask-row {
    display: flex;
    align-items: center;
    gap: 9px;
  }
  .ask-mark {
    display: inline-flex;
    flex-shrink: 0;
    color: var(--color-accent);
  }
  .ask-you {
    align-self: flex-end;
    max-width: 85%;
    padding: 7px 12px;
    border-radius: 13px 13px 4px 13px;
    background: color-mix(in srgb, var(--color-accent) 18%, transparent);
    color: var(--color-ink);
    font-size: 13px;
    overflow-wrap: anywhere;
    animation: ask-in 0.28s var(--swift) both;
  }
  .ask-step {
    color: var(--color-faint);
    font-size: 11.5px;
    animation: ask-in 0.28s var(--swift) both;
  }
  .ask-step.is-blocked {
    color: var(--color-warn, var(--color-muted));
  }
  .ask-working {
    animation: ask-pulse 1.4s ease-in-out infinite;
  }
  .ask-change {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 6px 8px 6px 11px;
    border-radius: 11px;
    background: color-mix(in srgb, var(--color-accent) 11%, transparent);
    font-size: 12.5px;
    overflow-wrap: anywhere;
    animation: ask-in 0.28s var(--swift) both;
  }
  .ask-change .text-faint {
    margin-left: 6px;
  }
  .ask-change.is-undone {
    background: rgb(255 255 255 / 0.03);
  }
  .ask-change.is-undone .ask-mark {
    color: var(--color-faint);
  }
  .ask-say {
    color: var(--color-ink);
    font-size: 13.5px;
    line-height: 1.5;
    overflow-wrap: anywhere;
    animation: ask-in 0.28s var(--swift) both;
  }
  .ask-error {
    color: var(--color-bad);
    font-size: 12.5px;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }
  .ask-link {
    margin-left: 6px;
    color: var(--color-accent);
    font-weight: 500;
  }
  .ask-link:hover {
    text-decoration: underline;
  }
  @keyframes ask-in {
    from {
      opacity: 0;
      transform: translateY(5px);
    }
  }
  @keyframes ask-pulse {
    50% {
      opacity: 0.45;
    }
  }
  :global(:root[data-motion="off"]) .ask-you,
  :global(:root[data-motion="off"]) .ask-step,
  :global(:root[data-motion="off"]) .ask-change,
  :global(:root[data-motion="off"]) .ask-say,
  :global(:root[data-motion="off"]) .ask-working {
    animation: none;
  }
</style>
