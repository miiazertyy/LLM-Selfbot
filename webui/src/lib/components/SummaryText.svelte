<script lang="ts">
  /**
   * A Memory summary drawn to be read at a glance: the headline, then one short
   * line per point, each label in a column of its own so the eye runs straight
   * down them. A summary from before this shape is shown as the paragraphs it
   * is. The parsing is lib/summarymd.ts; its HTML is escaped there.
   *
   * Colours come from --sm-ink, --sm-muted and --sm-accent, which default to
   * the app's own, so Big Picture can set its white-on-dark ones around it.
   * `reveal` brings the lines in one after another (Big Picture), with the
   * app's motion setting. `type` types it in, fast, a caret running ahead and
   * a soft key heard as it goes (lib/typewrite.ts): Memory, as it arrives.
   */
  import { summaryBlocks, type SummaryBlock } from "../summarymd";
  import { typewrite } from "../typewrite";

  let { text = "", size = "md", reveal = false, type = false }:
    { text?: string; size?: "md" | "lg"; reveal?: boolean; type?: boolean } = $props();

  const typing = (node: HTMLElement, on: boolean) => (on ? typewrite(node) : undefined);

  type Point = Extract<SummaryBlock, { kind: "point" }> & { n: number };
  type Group = { kind: "lead" | "para"; html: string; n: number } | { kind: "points"; items: Point[] };

  /** Points that follow each other share one list, so their labels line up. n is the order they come in. */
  const groups = $derived.by<Group[]>(() => {
    const out: Group[] = [];
    summaryBlocks(text).forEach((b, n) => {
      const last = out[out.length - 1];
      if (b.kind === "point") {
        if (last?.kind === "points") last.items.push({ ...b, n });
        else out.push({ kind: "points", items: [{ ...b, n }] });
      } else {
        out.push({ ...b, n });
      }
    });
    return out;
  });
</script>

<div class="sm" class:is-reveal={reveal} data-size={size} use:typing={type}>
  {#each groups as g, i (i)}
    {#if g.kind === "lead"}
      <p class="sm-lead" style="--n:{g.n}">{@html g.html}</p>
    {:else if g.kind === "para"}
      <p class="sm-para" style="--n:{g.n}">{@html g.html}</p>
    {:else if g.kind === "points"}
      <div class="sm-points">
        {#each g.items as p, j (j)}
          <span class="sm-label" class:is-dot={!p.label} style="--n:{p.n}">{p.label || "•"}</span>
          <span class="sm-text" style="--n:{p.n}">{@html p.html}</span>
        {/each}
      </div>
    {/if}
  {/each}
</div>

<style>
  .sm {
    --ink: var(--sm-ink, var(--color-ink));
    --muted: var(--sm-muted, color-mix(in srgb, var(--color-ink) 82%, transparent));
    --accent: var(--sm-accent, var(--color-accent));
    display: flex;
    flex-direction: column;
    gap: 10px;
    overflow-wrap: anywhere;
    color: var(--muted);
  }
  .sm-lead {
    font-size: 14px;
    font-weight: 650;
    line-height: 1.35;
    letter-spacing: -0.005em;
    color: var(--ink);
  }
  .sm-para { font-size: 13px; line-height: 1.6; }
  .sm-points {
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    align-items: baseline;
    gap: 7px 12px;
  }
  .sm-label {
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--accent);
  }
  .sm-label.is-dot { font-size: 14px; line-height: 1; letter-spacing: 0; }
  .sm-text { font-size: 13px; line-height: 1.5; color: var(--muted); }
  .sm :global(strong) { font-weight: 650; color: var(--ink); }
  .sm :global(code) {
    padding: 0 4px;
    border-radius: 4px;
    font-size: 0.92em;
    background: color-mix(in srgb, var(--ink) 9%, transparent);
  }

  /* Big Picture: read from across the room. */
  .sm[data-size="lg"] { gap: clamp(14px, 1.6vh, 22px); }
  .sm[data-size="lg"] .sm-lead { font-size: clamp(22px, 1.9vw, 32px); font-weight: 750; line-height: 1.2; letter-spacing: -0.02em; }
  .sm[data-size="lg"] .sm-para { font-size: clamp(16px, 1.3vw, 20px); line-height: 1.55; }
  .sm[data-size="lg"] .sm-points { gap: clamp(10px, 1.3vh, 16px) 18px; }
  .sm[data-size="lg"] .sm-label { font-size: clamp(11px, 0.8vw, 13px); letter-spacing: 0.12em; }
  .sm[data-size="lg"] .sm-label.is-dot { font-size: 20px; }
  .sm[data-size="lg"] .sm-text { font-size: clamp(16px, 1.3vw, 21px); line-height: 1.4; }

  /* One line after another, each rising a little into place. */
  .sm.is-reveal .sm-lead,
  .sm.is-reveal .sm-para,
  .sm.is-reveal .sm-label,
  .sm.is-reveal .sm-text {
    animation: sm-in 0.62s var(--spring, ease-out) both;
    animation-delay: calc(0.18s + var(--n, 0) * 0.13s);
  }
  @keyframes sm-in {
    from { opacity: 0; transform: translate3d(0, 10px, 0); }
    to { opacity: 1; transform: none; }
  }
  /* Only the app's Motion switch, not Windows' animation effects (see stores.ts). */
  :global(:root[data-motion="off"]) .sm.is-reveal * { animation: none; }
</style>
