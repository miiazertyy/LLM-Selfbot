<script lang="ts">
  /**
   * Where ask() shows its question: once, in App.svelte. See lib/ask.ts.
   *
   * Its own small card rather than the general dialog: that one opened under
   * the raw config editor, so leaving it with changes asked a question
   * nobody could see, and X and Cancel seemed to do nothing. This sits over
   * everything, Big Picture and the picture viewer included.
   *
   * Enter answers yes, Escape or a click outside answers no. When the yes is
   * destructive the safe answer has the focus, so Enter by reflex does no harm.
   */
  import { tick } from "svelte";
  import Icon from "./Icon.svelte";
  import { answer, asking } from "../ask";

  let yesBtn: HTMLButtonElement | null = $state(null);
  let noBtn: HTMLButtonElement | null = $state(null);

  $effect(() => {
    if (!$asking) return;
    const danger = $asking.danger;
    tick().then(() => (danger ? noBtn : yesBtn)?.focus());
  });

  function onKey(e: KeyboardEvent) {
    if (!$asking) return;
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopImmediatePropagation();
      answer(false);
    } else if (e.key === "Enter" && !(e.target instanceof HTMLButtonElement)) {
      e.preventDefault();
      answer(!$asking.danger);
    }
  }

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }
</script>

<svelte:window onkeydowncapture={onKey} />

{#if $asking}
  {#key $asking.id}
    <div class="ask-back" use:portal role="presentation" onclick={(e) => e.target === e.currentTarget && answer(false)}>
      <div class="ask" class:is-danger={$asking.danger} role="alertdialog" aria-modal="true"
           aria-labelledby="ask-q" aria-describedby={$asking.detail ? "ask-d" : undefined}>
        <span class="ask-icon"><Icon name={$asking.danger ? "alert" : "info"} size={18} /></span>
        <div class="min-w-0 flex-1">
          <p id="ask-q" class="ask-q">{$asking.text}</p>
          {#if $asking.detail}<p id="ask-d" class="ask-d">{$asking.detail}</p>{/if}
          <div class="ask-actions">
            <button type="button" class="ask-btn is-no" bind:this={noBtn} onclick={() => answer(false)}>{$asking.no}</button>
            <button type="button" class="ask-btn is-yes" bind:this={yesBtn} onclick={() => answer(true)}>{$asking.yes}</button>
          </div>
        </div>
      </div>
    </div>
  {/key}
{/if}

<style>
  .ask-back {
    position: fixed;
    inset: 0;
    /* Over everything: the raw editor (60), Big Picture (200), a picture (400). */
    z-index: 500;
    display: grid;
    place-items: center;
    padding: 20px;
    background: rgb(0 0 0 / 0.5);
    backdrop-filter: blur(3px);
    animation: ask-fade 0.18s var(--swift) both;
  }
  @keyframes ask-fade { from { opacity: 0; } }
  .ask {
    display: flex;
    width: min(420px, 94vw);
    gap: 14px;
    padding: 18px 18px 16px;
    border-radius: 18px;
    background:
      linear-gradient(160deg, color-mix(in srgb, var(--ask-tone) 9%, transparent), transparent 55%),
      color-mix(in srgb, var(--color-card) 96%, #000);
    box-shadow:
      0 30px 70px -24px rgb(0 0 0 / 0.85),
      inset 0 0 0 1px color-mix(in srgb, var(--ask-tone) 22%, rgb(255 255 255 / 0.07));
    animation: ask-in 0.34s var(--spring) both;
    --ask-tone: var(--color-accent);
  }
  .ask.is-danger { --ask-tone: var(--color-bad); }
  @keyframes ask-in { from { opacity: 0; transform: translateY(10px) scale(0.95); } }
  .ask-icon {
    display: grid;
    width: 38px;
    height: 38px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 12px;
    color: var(--ask-tone);
    background: color-mix(in srgb, var(--ask-tone) 15%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ask-tone) 25%, transparent);
  }
  .ask-q {
    margin-top: 2px;
    font-size: 14.5px;
    font-weight: 600;
    line-height: 1.4;
    color: var(--color-ink);
  }
  .ask-d {
    margin-top: 4px;
    font-size: 12.5px;
    line-height: 1.5;
    color: var(--color-muted);
  }
  .ask-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 16px;
  }
  .ask-btn {
    padding: 7px 15px;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 600;
    transition: background-color 0.15s ease, transform 0.3s var(--jelly), box-shadow 0.15s ease;
  }
  .ask-btn:active { transform: scale(0.95); }
  .ask-btn:focus-visible { outline: none; box-shadow: 0 0 0 3px color-mix(in srgb, var(--ask-tone) 35%, transparent); }
  .ask-btn.is-no {
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.07);
  }
  .ask-btn.is-no:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.09); }
  .ask-btn.is-yes {
    color: #fff;
    background: color-mix(in srgb, var(--ask-tone) 78%, #000);
    box-shadow: 0 6px 18px -8px color-mix(in srgb, var(--ask-tone) 70%, transparent);
  }
  .ask-btn.is-yes:hover { background: var(--ask-tone); }

  :global(:root[data-motion="off"]) .ask,
  :global(:root[data-motion="off"]) .ask-back { animation: none; }
</style>
