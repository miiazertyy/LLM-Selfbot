<script lang="ts">
  /**
   * What the model is thinking, as it thinks it: a reasoning model's thoughts
   * before it answers, typed out on a HUD screen. Only models that think out
   * loud send these (gpt-oss, qwen3, deepseek-r1 and the like).
   *
   * As big as what it has to say: it opens to the full height of the column
   * while a thought is fresh, and folds back to a small card (the last thought
   * in two lines, or a line saying none has come) once it has been a while.
   */
  import { motionEnabled } from "../stores";
  import { shortModel } from "../providers";

  type Thought = { model: string; text: string; at: number };
  let { thoughts = [], hideText = false, now = 0 }: { thoughts?: Thought[]; hideText?: boolean; now?: number } = $props();

  /** Seconds a thought keeps the panel open after it arrives. */
  const OPEN_FOR = 120;

  const latest = $derived(thoughts[thoughts.length - 1]);
  const open = $derived(!!latest && now - latest.at < OPEN_FOR);
  let shown = $state(0);
  let screen: HTMLDivElement | null = $state(null);

  // Reading top down, the caret can run off the bottom of a long thought; follow
  // it, so the newest words stay in view without the text being upside down.
  $effect(() => {
    void shown;
    const box = screen;
    if (!box) return;
    requestAnimationFrame(() => {
      if (box.scrollHeight > box.clientHeight) box.scrollTop = box.scrollHeight;
    });
  });

  // Typed out: restarts with every new thought, at a speed you can follow.
  $effect(() => {
    const text = latest?.text ?? "";
    const at = latest?.at;
    void at;
    shown = 0;
    if (!text) return;
    if (!$motionEnabled) {
      shown = text.length;
      return;
    }
    const id = setInterval(() => {
      shown = Math.min(text.length, shown + 3);
      if (shown >= text.length) clearInterval(id);
    }, 16);
    return () => clearInterval(id);
  });

  function ago(ts: number): string {
    const s = Math.max(0, now - ts);
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
    return `${Math.round(s / 3600)} h ago`;
  }
</script>

<section class="bpt" class:is-open={open}>
  <header class="bp-label">
    Thoughts
    {#if latest}<span class="bpt-model">{shortModel(latest.model || "model")}{open ? "" : ` · ${ago(latest.at)}`}</span>{/if}
  </header>
  <div class="bpt-screen" class:is-hidden={hideText} bind:this={screen}>
    {#if latest && open}
      <p class="bpt-text">{latest.text.slice(0, shown)}<span class="bpt-caret" class:is-done={shown >= latest.text.length}></span></p>
    {:else if latest}
      <p class="bpt-text is-past">{latest.text}</p>
    {:else}
      <p class="bpt-idle">None yet. A model that reasons before it answers shows it here, as it happens.</p>
    {/if}
  </div>
</section>

<style>
  .bpt {
    display: flex;
    min-height: 0;
    flex: 0 1 auto;
    flex-direction: column;
    gap: 10px;
    padding: 18px;
    border-radius: 24px;
    background: rgb(255 255 255 / 0.045);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.07);
    backdrop-filter: blur(20px);
    /* 0 to 1 grows smoothly: it takes that share of the free room, so it opens instead of jumping. */
    transition: flex-grow 0.8s var(--swift);
  }
  .bpt.is-open { flex-grow: 1; }
  .bpt-model { min-width: 0; margin-left: auto; overflow: hidden; font-size: 11px; letter-spacing: 0.02em; text-overflow: ellipsis; text-transform: none; white-space: nowrap; color: var(--bp-muted); }
  /* Top down, the way it is written and the way it is read. It used to be
     anchored to the bottom, so a thought typing itself out grew upwards and the
     beginning of it sat under the fade: it read as though it were upside down. */
  .bpt-screen {
    position: relative;
    display: flex;
    min-height: 0;
    flex: 1;
    flex-direction: column;
    justify-content: flex-start;
    overflow-y: auto;
    scrollbar-width: none;
  }
  .bpt-screen::-webkit-scrollbar { display: none; }
  /* A long one runs off the bottom, so that is the edge that fades. */
  .bpt.is-open .bpt-screen {
    -webkit-mask-image: linear-gradient(to bottom, #000 72%, transparent);
    mask-image: linear-gradient(to bottom, #000 72%, transparent);
  }
  .bpt-screen::after {
    content: "";
    position: absolute;
    inset: 0;
    pointer-events: none;
    background: repeating-linear-gradient(to bottom, rgb(255 255 255 / 0.025) 0 1px, transparent 1px 3px);
  }
  .bpt-screen.is-hidden .bpt-text { filter: blur(6px); }
  .bpt-text {
    font-family: ui-monospace, "Cascadia Code", monospace;
    font-size: 13px;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
    color: color-mix(in srgb, var(--color-accent) 35%, #e2e8f0);
  }
  /* Folded: the last thought in two lines, dimmer, as a reminder rather than a screen. */
  .bpt-text.is-past {
    display: -webkit-box;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    white-space: normal;
    opacity: 0.7;
  }
  .bpt-caret {
    display: inline-block;
    width: 8px;
    height: 15px;
    margin-left: 2px;
    vertical-align: -2px;
    background: var(--color-accent);
    box-shadow: 0 0 16px color-mix(in srgb, var(--color-accent) 42%, transparent);
    animation: bpt-blink 1s steps(2) infinite;
  }
  .bpt-caret.is-done { opacity: 0.5; }
  @keyframes bpt-blink { 50% { opacity: 0; } }
  .bpt-idle { font-size: 13px; line-height: 1.5; color: var(--bp-faint); }
  :global(:root[data-motion="off"]) .bpt { transition: none; }
</style>
