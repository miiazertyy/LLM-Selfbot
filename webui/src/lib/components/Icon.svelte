<script module lang="ts">
  import { DISCORD_MARK, SNAPCHAT_GHOST } from "../brands";
  /* Allocated once for the whole app. These were instance-level, so the
     ~60-entry path table was rebuilt for every <Icon> mounted, and
     {#key route} destroys and recreates every icon on each navigation. */
  const paths: Record<string, string> = {
    // ── Nav ──────────────────────────────────────────────────────────────
    dashboard: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
    accounts:
      "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM3 20v-1a6 6 0 0 1 12 0v1M16 4.5a3.5 3.5 0 0 1 0 7M17 14.5a6 6 0 0 1 4 5.5",
    chats: "M8 16.5H7a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v6.5a3 3 0 0 1-3 3h-5L8 20v-3.5Z",
    persona: "M4 20h4L19 9a2.5 2.5 0 0 0-3.5-3.5L4 16.5V20ZM14.5 6.5l3 3",
    // Profiles: three sheets stacked, each a bot of its own.
    layers: "M12 3.5 3.5 8 12 12.5 20.5 8 12 3.5ZM3.5 12l8.5 4.5 8.5-4.5M3.5 16l8.5 4.5 8.5-4.5",
    // A brain from the side, the way it is usually drawn: the dome, the
    // cerebellum tucked under the back with the stem running down from it,
    // and its folds - the one across the middle, the one down from the top,
    // and a few more - each starting from the edge rather than floating.
    memory:
      "M6.9 20.6C7.3 19.4 7.8 18.4 8.4 17.4C6.6 17.6 4.6 16.9 4.2 15.1C3.1 14.4 2.6 12.9 2.9 11.3C2.8 7.6 5.8 4.4 10 4.2C12.4 3.3 15.8 3.5 17.6 5C20.4 5.9 21.8 8.6 21.2 11.4C20.9 13.4 19.4 14.8 17.5 15C16.2 16.3 13.8 16.6 12 16C11.2 17.8 9.6 19.6 8.2 20.9ZM4.4 15.1C6 14.6 7.7 15 8.9 16.2M17.4 12.3C15.6 11.3 13.4 11.4 11.7 12.7M13.5 4C12.8 5.8 13.2 7.9 14.6 9.2M17.9 5.2C16.9 6.2 16.6 7.6 17.1 8.9M21.1 9.5C19.8 9.2 18.5 9.6 17.7 10.6M9.3 4.4C9.4 5.9 10.2 7.1 11.5 7.8M5.1 6.3C6.6 6.6 7.8 7.5 8.4 8.9M3.3 11.7C4.7 11.3 6.1 11.6 7.1 12.5",
    // Square 16x16 frame like the rest of the set. It used to be 16x14, which
    // made it visibly shorter than its neighbours in the rail.
    pictures:
      "M6 4h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2ZM4 16.5l4.5-4.5L12 15.5 15.5 12 20 16.5M9 11a1.6 1.6 0 1 1 0-3.2A1.6 1.6 0 0 1 9 11Z",
    stats: "M4 20h16M7 20v-7M12 20V5M17 20v-4",
    // A key: Providers' keys, Replace key (it was asked for and drew nothing).
    key: "M15 3.5a5.5 5.5 0 0 0-5.3 7L3.5 16.7v3.8h3.8v-2h2v-2h2l1.2-1.2A5.5 5.5 0 1 0 15 3.5ZM16.5 7.5h.01",
    // Big Picture Mode: a little TV, its antenna, and a play mark on the screen,
    // centred on the grid (3 to 21 across, 4.8 to 18.5 down) so it sits in its
    // button like the window icons.
    bigpicture:
      "M5 8h14a2 2 0 0 1 2 2v6.5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2ZM9 4.8l3 3.2 3-3.2M11 11.6v3.3l2.9-1.65-2.9-1.65Z",
    speaker: "M4 9.5h3.5L12 5.5v13l-4.5-4H4v-5ZM15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11",
    speakerOff: "M4 9.5h3.5L12 5.5v13l-4.5-4H4v-5ZM16 9.5l5 5M21 9.5l-5 5",
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
    // Snapchat's own ghost, as an outline to sit with the rest of the set (see
    // brands.ts). The ghost drawn from memory that stood here read as a bell.
    snapchat: SNAPCHAT_GHOST,
    system: "M4 6h9M17 6h3M4 12h3M11 12h9M4 18h9M17 18h3M15 4v4M9 10v4M15 16v4",
    // Discord's face, as a line drawing to sit with the rest of the set: the
    // rounded controller outline, the brow and the chin, and the two eyes.
    // Discord's own mark (see brands.ts), solid.
    discord: DISCORD_MARK,

    // ── Chrome / actions ─────────────────────────────────────────────────
    search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14ZM20 20l-4-4",
    // For the Chats tab's search and what was shared in a conversation.
    calendar: "M7.5 3.5v3M16.5 3.5v3M5.5 5.5h13A1.5 1.5 0 0 1 20 7v11.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5V7a1.5 1.5 0 0 1 1.5-1.5ZM4 10h16",
    file: "M13.5 3.5h-6A1.5 1.5 0 0 0 6 5v14a1.5 1.5 0 0 0 1.5 1.5h9A1.5 1.5 0 0 0 18 19V8ZM13.5 3.5V8H18",
    arrowDown: "M12 5v14M6.5 13.5 12 19l5.5-5.5",
    filter: "M4 6.5h16M7 12h10M10 17.5h4",
    jump: "M4 12h11M11 7l5 5-5 5M20 5v14",
    minimize: "M5 12h14",
    close: "M6 6l12 12M18 6 6 18",
    eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12ZM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
    eyeOff: "M3 3l18 18M10.6 5.1A9.8 9.8 0 0 1 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-3.2 4.2M6.6 6.6A17.4 17.4 0 0 0 2 12s3.5 7 10 7a9.6 9.6 0 0 0 5.4-1.6M9.9 9.9a3 3 0 0 0 4.2 4.2",
    expand: "M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7",
    collapse: "M10 4v6H4M14 20v-6h6M4 10l6-6M20 14l-6 6",
    rail: "M4 6h16M4 12h16M4 18h16",
    plus: "M12 5v14M5 12h14",
    minus: "M5 12h14",
    // React: a smile with a plus where its top right would be, as the apps draw it.
    smilePlus: "M18.5 13a7.5 7.5 0 1 1-6.2-7.39M8.5 11.5h.01M13.5 11.5h.01M8.3 15.2a3.6 3.6 0 0 0 5.4 0M18.5 3v5M16 5.5h5",
    chevron: "M9 5l7 7-7 7",
    signout: "M9 20H5V4h4M16 16l4-4-4-4M20 12H9",
    play: "M7 4l13 8-13 8V4Z",
    stop: "M8 6h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2Z",
    // Three dots, drawn as tiny rings rather than zero-length strokes: a
    // round cap on a zero-length line is only as wide as the stroke, which at
    // 16px left three specks you could barely click on.
    more: "M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM13 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM20 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z",
    folder: "M3.5 7.5a2 2 0 0 1 2-2h3.8l2 2h7.2a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-9Z",
    eraser: "M14.6 4.6a1.5 1.5 0 0 1 2.1 0l2.7 2.7a1.5 1.5 0 0 1 0 2.1L11 17.8H7.2l-2.6-2.6a1.5 1.5 0 0 1 0-2.1ZM9 10.2l4.8 4.8M11 17.8h9",
    pause: "M8 4v16M16 4v16",
    refresh: "M20 12a8 8 0 1 1-2.6-5.9M20 4v5h-5",
    check: "M5 12l5 5L19 7",
    alert: "M12 9v4M12 17h.01M12 3 2 20h20L12 3Z",
    alertCircle: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 7.5V13M12 16.4h.01",
    info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 11v5.5M12 7.6h.01",
    // The looped-square command symbol, drawn properly: four loops on the
    // corners of a square. The old path was one broken stroke that read as a
    // small cat face at 13px.
    command: "M9 9H6a3 3 0 1 1 3-3v3ZM15 9V6a3 3 0 1 1 3 3h-3ZM15 15h3a3 3 0 1 1-3 3v-3ZM9 15v3a3 3 0 1 1-3-3h3ZM9 9h6v6H9Z",
    // A prompt in a window, for bot commands and the words that trigger it.
    terminal: "M4.5 5h15A1.5 1.5 0 0 1 21 6.5v11a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5v-11A1.5 1.5 0 0 1 4.5 5ZM7 9.5l3 2.5-3 2.5M12.5 15h4.5",
    clipboard: "M8 5H6.5A1.5 1.5 0 0 0 5 6.5v13A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5v-13A1.5 1.5 0 0 0 17.5 5H16M9 3h6a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z",
    palette:
      "M12 3.5a8.5 8.5 0 1 0 0 17 2 2 0 0 0 1.5-3.3 2 2 0 0 1 1.5-3.2h1.7a3.8 3.8 0 0 0 3.8-3.8c0-3.7-3.8-6.7-8.5-6.7ZM7.5 12a1 1 0 1 1 0-2 1 1 0 0 1 0 2ZM10.5 8.5a1 1 0 1 1 0-2 1 1 0 0 1 0 2ZM15 8.5a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z",
    // ── Pictures ─────────────────────────────────────────────────────────
    // What can go on a picture as it is sent: a caption's band with its words, a big T, a clock, a smile.
    caption: "M3.5 9h17v6h-17ZM8 12h8",
    type: "M5 7.5V5h14v2.5M12 5v14M9 19h6",
    clock: "M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17ZM12 7.5V12l3 2",
    smile: "M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17ZM9 10h.01M15 10h.01M8.4 14a4.6 4.6 0 0 0 7.2 0",
    // Tray with an arrow rising out of it: the drop zone, without an emoji.
    upload: "M12 16V4M8 8l4-4 4 4M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3",
    // For the right-click menu's edits. Copy: one page over another.
    copy: "M10 9h9a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 21h-9a1.5 1.5 0 0 1-1.5-1.5v-9A1.5 1.5 0 0 1 10 9ZM15.5 5.5V5A1.5 1.5 0 0 0 14 3.5H5A1.5 1.5 0 0 0 3.5 5v9A1.5 1.5 0 0 0 5 15.5h.5",
    // Scissors: the two handles on the left, the blades crossing to the right.
    cut: "M6.5 9.5a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM6.5 20.5a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM8.9 8.3 20 19M8.9 15.7 20 5",
    // Two links of a chain.
    link: "M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1",
    // Select all: the corners of a frame round a filled middle.
    selectall: "M4 7.5v-2A1.5 1.5 0 0 1 5.5 4h2M16.5 4h2A1.5 1.5 0 0 1 20 5.5v2M20 16.5v2a1.5 1.5 0 0 1-1.5 1.5h-2M7.5 20h-2A1.5 1.5 0 0 1 4 18.5v-2M9 9h6v6H9Z",
    // upload, turned round: the arrow comes down into the tray.
    download: "M12 4v12M8 12l4 4 4-4M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3",
    // Curly braces, for the raw file: it is JSON.
    braces: "M8.5 4H8a2 2 0 0 0-2 2v3.5a2 2 0 0 1-2 2 2 2 0 0 1 2 2V17a2 2 0 0 0 2 2h.5M15.5 4h.5a2 2 0 0 1 2 2v3.5a2 2 0 0 0 2 2 2 2 0 0 0-2 2V17a2 2 0 0 1-2 2h-.5",
    // A sparkle, for anything the model wrote rather than you.
    // A large four-point star and a small one, together filling the grid the
    // way the other icons do (3 to 21). The old pair left most of the box
    // empty and sat off-centre, the big star up and left and the small one
    // in the bottom corner.
    sparkle: "M10 6c.6 3.6 3.4 6.4 7 7-3.6.6-6.4 3.4-7 7-.6-3.6-3.4-6.4-7-7 3.6-.6 6.4-3.4 7-7ZM18 3c.3 1.5 1.5 2.7 3 3-1.5.3-2.7 1.5-3 3-.3-1.5-1.5-2.7-3-3 1.5-.3 2.7-1.5 3-3Z",
    trash: "M4 7h16M10 7V5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v2M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M10 11v6M14 11v6",
    edit: "M4 20h4L19 9a2.5 2.5 0 0 0-3.5-3.5L4 16.5V20ZM14.5 6.5l3 3",
    grip: "M9 6h.01M9 12h.01M9 18h.01M15 6h.01M15 12h.01M15 18h.01",
    undo: "M4 9h10a5 5 0 0 1 0 10h-6M4 9l4-4M4 9l4 4",
    // A tray with an arrow into it, for messages coming in.
    inbox: "M4 13.5h4.2l1.6 2.5h4.4l1.6-2.5H20M12 4v7.5M8.8 8.3 12 11.5l3.2-3.2M4 13.5 5.8 8H7M20 13.5 18.2 8H17M4 13.5V18a1.5 1.5 0 0 0 1.5 1.5h13A1.5 1.5 0 0 0 20 18v-4.5",
    // A paper plane, for replies going out.
    send: "M20.5 3.5 3.5 10.6l6.8 2.6 2.6 6.8 7.6-16.5ZM10.3 13.2l4.4-4.4",
    // A keyboard, for the typing settings.
    keyboard: "M4 6.5h16A1.5 1.5 0 0 1 21.5 8v8a1.5 1.5 0 0 1-1.5 1.5H4A1.5 1.5 0 0 1 2.5 16V8A1.5 1.5 0 0 1 4 6.5ZM6.5 10h.01M10 10h.01M13.5 10h.01M17 10h.01M8 14h8",
    // A capsule mic on a stand, for hearing voice messages.
    mic: "M12 3.5a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0v-5a3 3 0 0 1 3-3ZM5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M9 21h6",
    // A speaker with two waves, for speaking.
    volume: "M4 9.5h3l4.5-4v13L7 14.5H4v-5ZM15 9a4 4 0 0 1 0 6M17.8 6.5a7.5 7.5 0 0 1 0 11",
    // A screen on a foot, for "this computer".
    monitor: "M5 4.5h14a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 15V6A1.5 1.5 0 0 1 5 4.5ZM9 20h6M12 16.5V20",
    // A link out, for "get a key" pages.
    external: "M14 4h6v6M20 4l-8.5 8.5M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10",
    // Arrows up and down, for "tried in this order".
    order: "M8 4v16M8 4 4.5 7.5M8 4l3.5 3.5M16 20V4M16 20l-3.5-3.5M16 20l3.5-3.5",
    // Someone asking to be friends: a person, and a plus beside them.
    userPlus: "M10 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM3.5 20v-1a6.5 6.5 0 0 1 11-4.7M18 13.5v6M15 16.5h6",
    // For a zone or a language that is no one country: UTC, Esperanto.
    globe: "M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17ZM3.8 9.5h16.4M3.8 14.5h16.4M12 3.5c2.3 2.4 3.4 5.2 3.4 8.5s-1.1 6.1-3.4 8.5M12 3.5C9.7 5.9 8.6 8.7 8.6 12s1.1 6.1 3.4 8.5",
    // A round bow and a shaft with two teeth, for API keys.

    // ── Filled ───────────────────────────────────────────────────────────
    // Somebody else's mark, so it is drawn as they draw it. An outline traced
    // version of this would be a different logo that reads as a mistake.
    github:
      "M12 .3a12 12 0 0 0-3.8 23.4c.6.1.8-.3.8-.6v-2c-3.3.7-4-1.6-4-1.6-.6-1.4-1.4-1.8-1.4-1.8-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1.1 1.9 2.8 1.3 3.5 1 .1-.8.4-1.3.8-1.6-2.7-.3-5.5-1.3-5.5-6 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0C17.2 4.7 18.2 5 18.2 5c.6 1.7.2 2.9.1 3.2a4.6 4.6 0 0 1 1.2 3.2c0 4.6-2.8 5.6-5.5 5.9.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0 0 12 .3Z",
  };
  // A key, for the fields that take a secret: the bow top right with its
  // hole, the bit stepping down to the bottom left, drawn as one closed
  // outline. That outline is what makes it look smooth; a version built from
  // a bare diagonal line and loose teeth rendered jagged at small sizes. It is
  // the original shape scaled up 1.3x and moved to span the grid (3 to 21):
  // at its old size it sat in the bottom right of the box, looking shrunk
  // beside the other icons.
  paths.key = "M11.45 7.55a4.55 4.55 0 1 1 4.55 4.55c-.65 0-1.3-.13-1.82-.39L12.1 13.79V16H9.5v2.6H6.9v2.6H3v-3.38l7.54-7.54c-.26-.52-.39-1.17-.39-1.82ZM16 6.38h.01";
  const FILLED = new Set(["github", "discord", "snapchat"]);
  /**
   * Marks drawn edge to edge on the grid, pulled in to the 2 to 22 the rest
   * keep to: a line along the very edge is half cut off by the box.
   */
  const INSET: Record<string, string> = {
    snapchat: "translate(1.2 1.2) scale(0.9)",
    discord: "translate(1.2 1.2) scale(0.9)",
  };
</script>

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


  /** Marks that are a solid shape rather than a line drawing. */
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
  <path d={paths[name] ?? paths.dashboard} transform={INSET[name]} />
</svg>
