<script lang="ts">
  /**
   * One stroke-based icon set, nothing in the chrome is an emoji.
   *
   * Paths sit on the 24px grid using whole or half units. Rendering at 18px
   * (a clean 0.75 scale) keeps strokes off half-pixels, and non-scaling-stroke
   * pins stroke width to device pixels so nothing looks furry or folded when
   * the sidebar collapses to the icon rail.
   */
  let { name, size = 18, class: cls = "" } = $props<{
    name: string;
    size?: number;
    class?: string;
  }>();

  const paths: Record<string, string> = {
    // ── Nav ──────────────────────────────────────────────────────────────
    dashboard: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
    accounts:
      "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM3 20v-1a6 6 0 0 1 12 0v1M16 4.5a3.5 3.5 0 0 1 0 7M17 14.5a6 6 0 0 1 4 5.5",
    chats: "M8 16.5H7a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v6.5a3 3 0 0 1-3 3h-5L8 20v-3.5Z",
    persona: "M4 20h4L19 9a2.5 2.5 0 0 0-3.5-3.5L4 16.5V20ZM14.5 6.5l3 3",
    // Two mirrored lobes over a centre line, symmetric, so it stays legible
    // at 16px instead of collapsing into a blob.
    memory:
      "M12 6.5a2.5 2.5 0 0 0-4.6-1.4A2.5 2.5 0 0 0 5 7.5a2.5 2.5 0 0 0-.4 4.8A2.5 2.5 0 0 0 5.6 16.5 2.5 2.5 0 0 0 9 18.9a2.5 2.5 0 0 0 3-.4M12 6.5a2.5 2.5 0 0 1 4.6-1.4A2.5 2.5 0 0 1 19 7.5a2.5 2.5 0 0 1 .4 4.8 2.5 2.5 0 0 1-1 4.2 2.5 2.5 0 0 1-3.4 2.4 2.5 2.5 0 0 1-3-.4M12 6.5v12",
    // Square 16x16 frame like the rest of the set. It used to be 16x14, which
    // made it visibly shorter than its neighbours in the rail.
    pictures:
      "M6 4h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2ZM4 16.5l4.5-4.5L12 15.5 15.5 12 20 16.5M9 11a1.6 1.6 0 1 1 0-3.2A1.6 1.6 0 0 1 9 11Z",
    stats: "M4 20h16M7 20v-7M12 20V5M17 20v-4",
    logs: "M4 6h16M4 11h16M4 16h10M4 21h6",
    // A true 8-tooth involute-ish gear: tips and valleys are placed on exact
    // radial angles (tip half-width 13 degrees, valley 6) so the silhouette is
    // regular. The old hand-drawn path was 19 units tall and lumpy, bursting
    // out of the 16x16 box every other icon sits in.
    settings:
      "M10.2 4.2L13.8 4.2L13.8 6L15 6.5L16.2 5.2L18.8 7.8L17.5 9L18 10.2L19.8 10.2L19.8 13.8L18 13.8L17.5 15L18.8 16.2L16.2 18.8L15 17.5L13.8 18L13.8 19.8L10.2 19.8L10.2 18L9 17.5L7.8 18.8L5.2 16.2L6.5 15L6 13.8L4.2 13.8L4.2 10.2L6 10.2L6.5 9L5.2 7.8L7.8 5.2L9 6.5L10.2 6ZM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z",
    // Ghost: a clean dome over a zig-zag hem, which reads as the scalloped
    // Snapchat skirt but survives 16px. The previous one was 18 wide and began
    // at x=0.9, so it sat noticeably larger and off-centre next to the others.
    // Ghost: domed head, the cheeks that flare out at the sides, and a hem of
    // rounded scallops. Earlier versions used a hard zig-zag for the hem,
    // which read as a sawtooth rather than the soft skirt of the real mark.
    snapchat:
      "M12 4a6 6 0 0 0-6 6v4.4c-.9.4-2 .8-2 1.6 0 .7 1.1.9 1.9 1.2.7.2 1.1.8 1.7.8.6 0 1-.5 1.8-.5.9 0 1.3 1 2.6 1s1.7-1 2.6-1c.8 0 1.2.5 1.8.5.6 0 1-.6 1.7-.8.8-.3 1.9-.5 1.9-1.2 0-.8-1.1-1.2-2-1.6V10a6 6 0 0 0-6-6Z",
    system: "M4 6h9M17 6h3M4 12h3M11 12h9M4 18h9M17 18h3M15 4v4M9 10v4M15 16v4",

    // ── Chrome / actions ─────────────────────────────────────────────────
    search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14ZM20 20l-4-4",
    minimize: "M5 12h14",
    close: "M6 6l12 12M18 6 6 18",
    expand: "M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7",
    collapse: "M10 4v6H4M14 20v-6h6M4 10l6-6M20 14l-6 6",
    rail: "M4 6h16M4 12h16M4 18h16",
    plus: "M12 5v14M5 12h14",
    chevron: "M9 5l7 7-7 7",
    signout: "M9 20H5V4h4M16 16l4-4-4-4M20 12H9",
    play: "M7 4l13 8-13 8V4Z",
    pause: "M8 4v16M16 4v16",
    refresh: "M20 12a8 8 0 1 1-2.6-5.9M20 4v5h-5",
    check: "M5 12l5 5L19 7",
    alert: "M12 9v4M12 17h.01M12 3 2 20h20L12 3Z",
    command: "M6 3a3 3 0 1 1 0 6h12a3 3 0 1 1 0-6v12a3 3 0 1 1 0 6H6a3 3 0 1 1 0-6",
    palette:
      "M12 3.5a8.5 8.5 0 1 0 0 17 2 2 0 0 0 1.5-3.3 2 2 0 0 1 1.5-3.2h1.7a3.8 3.8 0 0 0 3.8-3.8c0-3.7-3.8-6.7-8.5-6.7ZM7.5 12a1 1 0 1 1 0-2 1 1 0 0 1 0 2ZM10.5 8.5a1 1 0 1 1 0-2 1 1 0 0 1 0 2ZM15 8.5a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z",
    // ── Pictures ─────────────────────────────────────────────────────────
    // Tray with an arrow rising out of it: the drop zone, without an emoji.
    upload: "M12 16V4M8 8l4-4 4 4M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3",
    // A sparkle, for anything the model wrote rather than you.
    sparkle: "M12 4l1.7 4.8L18.5 10.5 13.7 12.2 12 17l-1.7-4.8L5.5 10.5l4.8-1.7L12 4ZM19 16.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8Z",
    trash: "M4 7h16M10 7V5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v2M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M10 11v6M14 11v6",
    edit: "M4 20h4L19 9a2.5 2.5 0 0 0-3.5-3.5L4 16.5V20ZM14.5 6.5l3 3",
    grip: "M9 6h.01M9 12h.01M9 18h.01M15 6h.01M15 12h.01M15 18h.01",
    undo: "M4 9h10a5 5 0 0 1 0 10h-6M4 9l4-4M4 9l4 4",

    // ── Filled ───────────────────────────────────────────────────────────
    // Somebody else's mark, so it is drawn as they draw it. An outline traced
    // version of this would be a different logo that reads as a mistake.
    github:
      "M12 .3a12 12 0 0 0-3.8 23.4c.6.1.8-.3.8-.6v-2c-3.3.7-4-1.6-4-1.6-.6-1.4-1.4-1.8-1.4-1.8-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1.1 1.9 2.8 1.3 3.5 1 .1-.8.4-1.3.8-1.6-2.7-.3-5.5-1.3-5.5-6 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0C17.2 4.7 18.2 5 18.2 5c.6 1.7.2 2.9.1 3.2a4.6 4.6 0 0 1 1.2 3.2c0 4.6-2.8 5.6-5.5 5.9.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0 0 12 .3Z",
  };

  /** Marks that are a solid shape rather than a line drawing. */
  const FILLED = new Set(["github"]);
  const solid = $derived(FILLED.has(name));
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill={solid ? "currentColor" : "none"}
  stroke={solid ? "none" : "currentColor"}
  stroke-width="1.75"
  stroke-linecap="round"
  stroke-linejoin="round"
  vector-effect="non-scaling-stroke"
  shape-rendering="geometricPrecision"
  class={cls}
  aria-hidden="true"
>
  <path d={paths[name] ?? paths.dashboard} />
</svg>
