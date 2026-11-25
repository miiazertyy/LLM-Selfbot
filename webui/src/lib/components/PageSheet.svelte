<script lang="ts">
  /**
   * A form in the page, where it was asked for: a card that grows out of what was pressed (a tile, a button, an
   * account's card) and goes back into it when it closes. The page stays around it, nothing dimmed and nothing in
   * front: a dialog over a dimmed page "looks like a new window" (New profile 2026-11-04, Share and Add an account
   * 2026-11-11). Its x and Escape close it, the page's own way when it has one.
   *
   * It takes Modal's place as is (open, title, onclose, the contents), plus `from`: the place of what was pressed,
   * to grow out of. Closed any way, it goes back into it: the leaving is a transition, so a page that simply sets
   * open to false still gets it.
   */
  import { get } from "svelte/store";
  import { motionEnabled } from "../stores";
  import { glideInto } from "../smoothscroll";
  import Icon from "./Icon.svelte";

  let { open = $bindable(false), title = "", from = null, wide = false, onclose, children }: {
    open?: boolean;
    title?: string;
    /** Where what was pressed is, to grow out of and go back into. Without one it settles in from a little above. */
    from?: DOMRect | null;
    /** The whole width of the page, for what is mostly a picture (a live view), rather than a form's. */
    wide?: boolean;
    onclose?: () => void;
    children?: any;
  } = $props();

  const close = () => (onclose ? onclose() : (open = false));

  /** What shows of the card at the start (the pressed thing's place on it), and how far it is moved to sit there. */
  function frame(node: HTMLElement, rect: DOMRect | null) {
    const to = node.getBoundingClientRect();
    if (!rect) return { left: 0, right: 0, bottom: Math.max(0, to.height - 60), dy: -10 };
    // Pressed off to one side of the card (Add account's list sits right of it): it starts as a sliver at that edge.
    const left = Math.min(Math.max(0, rect.left - to.left), Math.max(0, to.width - 40));
    const right = Math.min(Math.max(0, to.right - rect.right), Math.max(0, to.width - 40 - left));
    return { left, right, bottom: Math.max(0, to.height - Math.max(rect.height, 40)), dy: rect.top - to.top };
  }
  const clip = (f: ReturnType<typeof frame>, u: number) =>
    `clip-path: inset(0px ${f.right * u}px ${f.bottom * u}px ${f.left * u}px round 22px); transform: translateY(${f.dy * u}px);`;

  function grow(node: HTMLElement, rect: DOMRect | null) {
    if (!get(motionEnabled)) return { duration: 0 };
    const f = frame(node, rect);
    return { duration: 460, easing: (t: number) => 1 - Math.pow(1 - t, 4), css: (_t: number, u: number) => clip(f, u) };
  }
  function shrink(node: HTMLElement, rect: DOMRect | null) {
    if (!get(motionEnabled)) return { duration: 0 };
    const f = frame(node, rect);
    return { duration: 240, easing: (t: number) => t * t, css: (t: number, u: number) => `${clip(f, u)} opacity: ${t};` };
  }

  /**
   * In view as it opens, glided to only if it is not (lib/smoothscroll.ts), and the focus in it where the page has
   * not put it in a field of its own, so Escape is heard. A frame later, so a field the page focuses goes first.
   */
  function arrive(node: HTMLElement) {
    requestAnimationFrame(() => {
      glideInto(node, { block: "nearest" });
      if (!node.contains(document.activeElement)) node.focus({ preventScroll: true });
    });
  }
</script>

{#if open}
  <div class="psheet glass" class:is-wide={wide} role="dialog" aria-label={title} tabindex="-1" use:arrive
       in:grow={from} out:shrink={from}
       onkeydown={(e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } }}>
    <header class="psheet-head">
      <h3 class="psheet-title">{title}</h3>
      <button type="button" class="psheet-x" onclick={close} aria-label="Close"><Icon name="close" size={15} /></button>
    </header>
    <div class="psheet-body">
      {@render children?.()}
    </div>
  </div>
{/if}

<style>
  .psheet {
    width: min(100%, 680px);
    border-radius: 22px;
    outline: none;
  }
  .psheet.is-wide { width: 100%; }
  .psheet-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 14px 18px 0 20px;
  }
  .psheet-title {
    min-width: 0;
    overflow: hidden;
    font-size: 15px;
    font-weight: 600;
    letter-spacing: -0.01em;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--color-ink);
  }
  .psheet-x {
    display: grid;
    width: 30px;
    height: 30px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 9px;
    color: var(--color-muted);
    transition: color 0.15s ease, background-color 0.15s ease, transform 0.3s var(--jelly);
  }
  .psheet-x:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
  .psheet-x:active { transform: scale(0.9); }
  .psheet-body { padding: 12px 20px 18px; }
  :global(:root[data-motion="off"]) .psheet-x { transition: none; }
</style>
