<script lang="ts">
  /**
   * The little notifications in the corner: what `toast()` says.
   *
   * They used to be see-through (the app's glass, so whatever was behind them ran through the words), under anything
   * else that floats, gone in four seconds whatever they said, and popping in. Now each is a solid card above
   * everything, sliding in from the edge and out again. Pointing at one holds it there for as long as you need, its
   * words can be selected and copied, and it can be closed. The same thing said again counts up rather than stacking.
   */
  import { flip } from "svelte/animate";
  import { cubicIn, cubicOut } from "svelte/easing";
  import { dismissToast, holdToast, letGoToast, motionEnabled, toasts } from "../stores";
  import Icon from "./Icon.svelte";

  const ICON: Record<string, string> = { ok: "check", err: "alert", info: "info" };

  /** Only ever a move and a fade, which the graphics card does alone: no bounce, no pop. */
  function slide(_node: Element, { going = false }: { going?: boolean }) {
    return {
      duration: $motionEnabled ? (going ? 220 : 340) : 0,
      easing: going ? cubicIn : cubicOut,
      css: (t: number, u: number) => `transform: translate3d(${u * 112}%, 0, 0); opacity: ${Math.min(1, t * 1.5)}`,
    };
  }
</script>

<div class="toast-stack" role="status" aria-live="polite">
  {#each $toasts as t (t.id)}
    <div class="notice is-{t.kind}" role={t.kind === "err" ? "alert" : undefined}
         animate:flip={{ duration: $motionEnabled ? 260 : 0, easing: cubicOut }}
         in:slide={{}} out:slide={{ going: true }}
         onpointerenter={() => holdToast(t.id)} onpointerleave={() => letGoToast(t.id)}>
      <span class="notice-mark" aria-hidden="true"><Icon name={ICON[t.kind] ?? "info"} size={14} /></span>
      <p class="notice-text">{t.text}{#if t.n > 1}<b class="notice-n"> ×{t.n}</b>{/if}</p>
      <button type="button" class="notice-x" aria-label="Close" onclick={() => dismissToast(t.id)}>
        <Icon name="close" size={12} />
      </button>
    </div>
  {/each}
</div>

<style>
  .toast-stack {
    position: fixed;
    /* Above everything that floats, dialogs and menus included: a notice nobody can see has said nothing. */
    z-index: 10000;
    right: calc(1rem + env(safe-area-inset-right, 0px));
    bottom: calc(1rem + env(safe-area-inset-bottom, 0px));
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 8px;
    width: min(360px, calc(100vw - 2rem));
    pointer-events: none;
  }
  .notice {
    --tone: var(--color-accent);
    display: flex;
    align-items: flex-start;
    gap: 10px;
    width: 100%;
    padding: 10px 8px 10px 10px;
    border-radius: 14px;
    pointer-events: auto;
    /* Solid: the theme's own card, a touch of the notice's colour in it, and nothing showing through. */
    background: color-mix(in srgb, var(--tone) 7%, var(--color-card));
    box-shadow: 0 14px 34px -14px rgb(0 0 0 / 0.65), 0 3px 10px -4px rgb(0 0 0 / 0.4);
  }
  .notice.is-ok { --tone: var(--color-good); }
  .notice.is-err { --tone: var(--color-bad); }
  .notice-mark {
    display: grid;
    width: 26px;
    height: 26px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 8px;
    color: var(--tone);
    background: color-mix(in srgb, var(--tone) 16%, transparent);
  }
  .notice-text {
    min-width: 0;
    flex: 1;
    padding: 3px 0;
    font-size: 12.5px;
    line-height: 1.45;
    color: var(--color-ink);
    overflow-wrap: anywhere;
    user-select: text;
  }
  .notice-n { font-weight: 650; color: var(--color-muted); }
  .notice-x {
    display: grid;
    width: 22px;
    height: 22px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 7px;
    color: var(--color-faint);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .notice-x:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
</style>
