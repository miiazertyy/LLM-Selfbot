<script lang="ts">
  import Icon from "./Icon.svelte";

  let { open = $bindable(false), title = "", onclose, children, wide = false } = $props<{
    open?: boolean;
    title?: string;
    onclose?: () => void;
    children?: any;
    /** For content that is mostly a picture, where 560px wastes the screen. */
    wide?: boolean;
  }>();

  /**
   * Move the dialog to <body>.
   *
   * Modals are rendered inside the page container, which carries a transform
   * (`.page-enter` keeps its final keyframe via `animation … both`, plus
   * `will-change: transform`). A transformed ancestor becomes the containing
   * block for `position: fixed` descendants, so `inset-0` resolved against the
   * scrolled page instead of the viewport and the dialog was positioned partly
   * off-screen, the top of a tall form was unreachable.
   */
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  /** Closed by its x, Escape or a press outside it: the page's own way when it has one, else simply closed. A
   * window that gave none (the Filter one) had an x that did nothing, and could only be left by Cancel. */
  const close = () => (onclose ? onclose() : (open = false));

  /**
   * Focus in it as it opens, where the page has not put it in a field of its own: Escape is only heard inside it,
   * and a window with no field to type in (a picture to pick) could not be closed with Escape at all. A frame
   * later, so a field the page focuses itself goes first.
   */
  function takeFocus(node: HTMLElement) {
    requestAnimationFrame(() => {
      if (!node.contains(document.activeElement)) node.focus({ preventScroll: true });
    });
  }
</script>

{#if open}
  <div
    use:portal
    use:takeFocus
    class="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4 outline-none backdrop-blur-sm"
    role="dialog"
    aria-modal="true"
    tabindex="-1"
    onclick={(e) => e.target === e.currentTarget && close()}
    onkeydown={(e) => e.key === "Escape" && close()}
  >
    <!-- Column layout with a scrolling body. Without a max height a tall form
         simply overflowed the viewport, and because the dialog is centred the
         overflow went off the TOP of the screen where it could not be reached. -->
    <div class="glass floating glow pop flex max-h-[88vh] flex-col overflow-hidden
                {wide ? 'w-[min(880px,94vw)]' : 'w-[min(560px,94vw)]'}">
      <div class="flex shrink-0 items-center justify-between gap-3 border-b border-edge px-5 py-3.5">
        <h3 class="min-w-0 truncate text-[15px] font-semibold tracking-tight">{title}</h3>
        <button
          class="jelly shrink-0 rounded-lg p-1.5 text-muted hover:bg-white/10 hover:text-ink"
          onclick={close}
          aria-label="Close"
        >
          <Icon name="close" size={15} />
        </button>
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {@render children?.()}
      </div>
    </div>
  </div>
{/if}
