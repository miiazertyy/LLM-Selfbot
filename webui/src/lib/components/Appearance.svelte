<script lang="ts">
  import { sweep } from "../arrive";
  import { colorwave } from "../colorwave";
  /**
   * The Appearance tab: colours, background, panels and your own picture
   * (Theme), the typeface (Typeface), and motion and snow (Interface).
   *
   * Everything here shows itself rather than describing itself: each theme is
   * its colours, side by side, each background moves as it will
   * behind the app, each kind of panel sits over some colour so the glass can
   * be seen to be glass, and each typeface is set in itself. The choices apply
   * the moment they are clicked; there is nothing to save.
   */
  import { api } from "../api";
  import { toast, themeId, fontId, backdropId, surfaceId, customBgOn, customBgDim, appearance, appearanceVersion,
           loadAppearance, motionEnabled, snowEnabled, smoothScroll } from "../stores";
  import { THEMES, DEFAULT_THEME } from "../themes";
  import { FONTS, CUSTOM_FONT_ID } from "../fonts";
  import { BACKDROPS } from "../backdrops";
  import { revealChange, sweepTo } from "../themesweep";

  // The background, the panels and the typeface change the way a theme does:
  // the new look spreads out from the card you clicked (lib/themesweep.ts).
  const pickBackdrop = (id: string) => { if (id !== $backdropId) revealChange(() => backdropId.set(id)); };
  const pickSurface = (id: string) => { if (id !== $surfaceId) revealChange(() => surfaceId.set(id)); };
  /** A typeface waits a moment for its file, so the new look is not taken in the fallback font. */
  const pickFont = (id: string) => {
    if (id === $fontId) return;
    revealChange(() => fontId.set(id), () => {
      const stack = getComputedStyle(document.documentElement).getPropertyValue("--font-sans").trim();
      return stack ? document.fonts.load(`16px ${stack}`) : Promise.resolve();
    });
  };
  import Importer from "./Importer.svelte";
  import Toggle from "./Toggle.svelte";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";

  let { which }: { which: "theme" | "typeface" | "interface" } = $props();

  // What a new install starts with (see stores.ts), marked in the pickers.
  const DEFAULT_BACKDROP = "aurora";
  const DEFAULT_SURFACE = "glass";
  const SURFACES = [
    { id: "glass", name: "Glass", hint: "See the background through them" },
    { id: "solid", name: "Solid", hint: "Opaque, the lightest to draw" },
    { id: "frost", name: "Frosted", hint: "More blur, more opaque" },
  ];

  let bgBusy = $state(false);
  let fontBusy = $state(false);

  /**
   * Take one uploaded file and make it live immediately.
   *
   * The version bump is what makes a replacement show up: both files are
   * served with a long max-age, so without it the browser would happily go on
   * using the previous image or face.
   */
  async function upload(kind: "background" | "font", file: File) {
    if (kind === "background") bgBusy = true;
    else fontBusy = true;
    try {
      await api.uploadAppearance(kind, file);
      await loadAppearance();
      appearanceVersion.set(Date.now());
      // Switching it on is the obvious intent of having just dropped it in.
      if (kind === "background") customBgOn.set(true);
      else fontId.set(CUSTOM_FONT_ID);
      toast(kind === "background" ? "Background set." : "Typeface set.", "ok");
    } catch (e: any) {
      toast(e?.message || "Could not use that file", "err");
    }
    bgBusy = false;
    fontBusy = false;
  }

  async function clear(kind: "background" | "font") {
    try {
      await api.clearAppearance(kind);
      await loadAppearance();
      appearanceVersion.set(Date.now());
      // Nothing to fall back to, so move off it rather than leaving the panel
      // pointing at a file that is no longer there.
      if (kind === "background") customBgOn.set(false);
      else if ($fontId === CUSTOM_FONT_ID) fontId.set("mikhak");
      toast("Removed.", "ok");
    } catch (e: any) {
      toast(e?.message || "Could not remove it", "err");
    }
  }

  /** The colours a theme is shown by: its accents, and its good and warning colours. */
  const SWATCHES = ["--color-accent", "--color-accent-2", "--color-good", "--color-warn"];
</script>

{#if which === "theme"}
  <!-- ── Colours ─────────────────────────────────────────────────────────── -->
  <section class="ap-sec" use:colorwave>
    <header class="ap-head"><h3>Colours</h3></header>
    <div class="ap-grid is-3">
      {#each THEMES as t (t.id)}
        {@const on = $themeId === t.id}
        <button type="button" class="ap-card jelly" class:is-on={on} onclick={() => sweepTo(t.id)} aria-pressed={on}>
          <!-- The theme's colours, side by side. -->
          <span class="ap-swatches" aria-hidden="true">
            {#each SWATCHES as v, k (v)}
              <i style="background: {t.vars[v]}; --k: {k}"></i>
            {/each}
          </span>
          <span class="ap-name">{t.name}{#if t.id === DEFAULT_THEME}<span class="default-tag">Default</span>{/if}</span>
          <span class="ap-hint">{t.hint}</span>
          {#if on}<span class="ap-tick"><Icon name="check" size={11} /></span>{/if}
        </button>
      {/each}
    </div>
  </section>

  <!-- ── Background ─────────────────────────────────────────────────────── -->
  <section class="ap-sec" use:colorwave>
    <header class="ap-head"><h3>Background</h3></header>
    <div class="ap-grid is-4">
      {#each BACKDROPS as b (b.id)}
        {@const on = $backdropId === b.id}
        <button type="button" class="ap-card jelly" class:is-on={on} onclick={() => pickBackdrop(b.id)} aria-pressed={on}>
          <span class="ap-scene backdrop-swatch" data-kind={b.id} aria-hidden="true">
            <span class="ap-scene-pane"></span>
          </span>
          <span class="ap-name">{b.name}{#if b.id === DEFAULT_BACKDROP}<span class="default-tag">Default</span>{/if}</span>
          <span class="ap-hint">{b.hint}</span>
          {#if on}<span class="ap-tick"><Icon name="check" size={11} /></span>{/if}
        </button>
      {/each}
    </div>
    {#if $customBgOn && $appearance.background.present && $backdropId !== "none"}
      <p class="ap-note is-warn">Your own picture is on, so it shows instead.</p>
    {/if}
  </section>

  <!-- ── Panels ─────────────────────────────────────────────────────────── -->
  <section class="ap-sec" use:colorwave>
    <header class="ap-head"><h3>Panels</h3></header>
    <div class="ap-grid is-3">
      {#each SURFACES as s (s.id)}
        {@const on = $surfaceId === s.id}
        <button type="button" class="ap-card jelly" class:is-on={on} onclick={() => pickSurface(s.id)} aria-pressed={on}>
          <!-- A panel over some colour, so glass can be seen to be glass. -->
          <span class="ap-surface" aria-hidden="true">
            <span class="ap-surface-blob is-a"></span><span class="ap-surface-blob is-b"></span>
            <span class="ap-surface-pane is-{s.id}"><b></b><em></em></span>
          </span>
          <span class="ap-name">{s.name}{#if s.id === DEFAULT_SURFACE}<span class="default-tag">Default</span>{/if}</span>
          <span class="ap-hint">{s.hint}</span>
          {#if on}<span class="ap-tick"><Icon name="check" size={11} /></span>{/if}
        </button>
      {/each}
    </div>
  </section>

  <!-- ── Your own picture ───────────────────────────────────────────────── -->
  <section class="ap-sec" use:colorwave>
    <header class="ap-head"><h3>Your own background</h3></header>
    {#if $appearance.background.present}
      <div class="ap-own">
        <img src="/api/appearance/background?v={$appearanceVersion}" alt="" aria-hidden="true" class="ap-own-img"
             style="--dim: {$customBgOn ? $customBgDim : 0}" />
        <div class="ap-own-body">
          <div class="ap-own-top">
            <div class="min-w-0 flex-1">
              <div class="ap-own-name">{$appearance.background.name}</div>
              <div class="ap-hint">{Math.round(($appearance.background.size ?? 0) / 1024)} KB</div>
            </div>
            <Toggle checked={$customBgOn} onchange={(v) => customBgOn.set(v)} />
          </div>
          <label class="ap-dim" class:is-off={!$customBgOn}>
            <span>Dim</span>
            <input type="range" min="0" max="1" step="0.02" value={$customBgDim} disabled={!$customBgOn}
                   oninput={(e) => customBgDim.set(parseFloat((e.target as HTMLInputElement).value))}
                   style="--fill: {Math.round($customBgDim * 100)}%" class="slider min-w-0 flex-1" use:sweep />
            <b>{Math.round($customBgDim * 100)}%</b>
          </label>
          <div class="ap-own-actions">
            <Button kind="ghost" size="sm" onclick={() => clear("background")}>Remove</Button>
          </div>
        </div>
      </div>
    {/if}
    <Importer
      title={$appearance.background.present ? "Drop another picture to replace it" : "Drop a picture here"}
      hint="Any image, even HEIC from a phone."
      accept="image/*,.heic,.heif,.avif,.bmp,.tif,.tiff"
      busy={bgBusy}
      busyLabel="Adding background"
      onpick={(f) => upload("background", f)}
    />
  </section>
{:else if which === "typeface"}
  <section class="ap-sec" use:colorwave>
    <div class="ap-grid is-2">
      {#each FONTS as f (f.id)}
        {@const on = $fontId === f.id}
        <button type="button" class="ap-card ap-font jelly" class:is-on={on} onclick={() => pickFont(f.id)} aria-pressed={on}>
          <!-- Set in the face itself, so the sample is the decision. -->
          <span class="ap-aa" style="font-family: {f.stack}" aria-hidden="true">Aa</span>
          <span class="min-w-0 flex-1">
            <span class="ap-name" style="font-family: {f.stack}">{f.name}</span>
            <span class="ap-sample" style="font-family: {f.stack}">The quick brown fox jumps</span>
            <span class="ap-hint">{f.note}</span>
          </span>
          {#if on}<span class="ap-tick"><Icon name="check" size={11} /></span>{/if}
        </button>
      {/each}
      {#if $appearance.font.present}
        {@const on = $fontId === CUSTOM_FONT_ID}
        <button type="button" class="ap-card ap-font jelly" class:is-on={on} onclick={() => pickFont(CUSTOM_FONT_ID)} aria-pressed={on}>
          <span class="ap-aa" style="font-family: 'PanelCustom', ui-sans-serif, system-ui, sans-serif" aria-hidden="true">Aa</span>
          <span class="min-w-0 flex-1">
            <span class="ap-name" style="font-family: 'PanelCustom', ui-sans-serif, system-ui, sans-serif">Yours</span>
            <span class="ap-sample" style="font-family: 'PanelCustom', ui-sans-serif, system-ui, sans-serif">The quick brown fox jumps</span>
            <span class="ap-hint">{$appearance.font.name} · {Math.round(($appearance.font.size ?? 0) / 1024)} KB</span>
          </span>
          {#if on}<span class="ap-tick"><Icon name="check" size={11} /></span>{/if}
        </button>
      {/if}
    </div>
  </section>
  {#if $appearance.font.present}
    <div class="ap-own-font">
      <span class="min-w-0 flex-1 truncate">Yours: {$appearance.font.name}</span>
      <Button kind="ghost" size="sm" onclick={() => clear("font")}>Remove</Button>
    </div>
  {/if}
  <section class="ap-sec" use:colorwave>
    <header class="ap-head"><h3>Your own typeface</h3></header>
    <Importer
      title="Drop a font file here"
      hint="woff2, woff, ttf or otf."
      accept=".woff2,.woff,.ttf,.otf,font/woff2,font/woff,font/ttf,font/otf"
      busy={fontBusy}
      busyLabel="Adding typeface"
      onpick={(f) => upload("font", f)}
    />
  </section>
{:else}
  <div class="settings-card">
    <div class="settings-row flex items-center gap-4">
      <div class="min-w-0 flex-1">
        <div class="text-[13.5px] font-medium text-ink">Animations</div>
        <p class="mt-0.5 text-[12px] leading-relaxed text-muted">Springy motion throughout the app.</p>
      </div>
      <Toggle checked={$motionEnabled} onchange={(v) => motionEnabled.set(v)} />
    </div>
    <div class="settings-row flex items-center gap-4">
      <div class="min-w-0 flex-1">
        <div class="text-[13.5px] font-medium text-ink">Smooth scrolling</div>
        <p class="mt-0.5 text-[12px] leading-relaxed text-muted">The mouse wheel glides instead of jumping.</p>
      </div>
      <Toggle checked={$smoothScroll} name="Smooth scrolling" onchange={(v) => smoothScroll.set(v)} />
    </div>
    <div class="settings-row flex items-center gap-4">
      <div class="min-w-0 flex-1">
        <div class="text-[13.5px] font-medium text-ink">Cursor snow</div>
        <p class="mt-0.5 text-[12px] leading-relaxed text-muted">Snow falls from your cursor as you move it.</p>
      </div>
      <Toggle checked={$snowEnabled} onchange={(v) => snowEnabled.set(v)} />
    </div>
  </div>
{/if}

<style>
  .ap-sec + .ap-sec { margin-top: 22px; }
  .ap-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 9px; }
  .ap-head h3 { font-size: 11px; font-weight: 650; letter-spacing: 0.1em; text-transform: uppercase; color: var(--color-faint); }
  .ap-grid { display: grid; gap: 10px; grid-template-columns: 1fr; }
  @media (min-width: 380px) { .ap-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  @media (min-width: 1024px) {
    .ap-grid.is-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .ap-grid.is-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  }
  .ap-note { margin-top: 8px; font-size: 11.5px; color: var(--color-muted); }
  .ap-note.is-warn { color: var(--color-warn); }

  /* ── A choice ─────────────────────────────────────────────────────────── */
  .ap-card {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 8px 8px 11px;
    border-radius: 14px;
    border: 1px solid var(--color-edge);
    background: rgb(255 255 255 / 0.02);
    text-align: left;
    transition:
      transform 0.5s var(--jelly),
      border-color 0.18s var(--swift),
      background-color 0.18s var(--swift),
      box-shadow 0.24s var(--swift);
  }
  .ap-card:hover { border-color: color-mix(in srgb, var(--color-accent) 35%, var(--color-edge)); background: rgb(255 255 255 / 0.04); }
  .ap-card.is-on {
    border-color: color-mix(in srgb, var(--color-accent) 70%, transparent);
    background: color-mix(in srgb, var(--color-accent) 8%, transparent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 14%, transparent), 0 12px 30px -18px var(--color-accent);
  }
  .ap-name { display: flex; align-items: center; gap: 6px; margin-top: 7px; padding: 0 3px; font-size: 12.5px; font-weight: 650; color: var(--color-ink); }
  .ap-hint { display: block; padding: 0 3px; font-size: 10.5px; line-height: 1.4; color: var(--color-faint); }
  .ap-tick {
    position: absolute;
    top: 13px;
    right: 13px;
    display: grid;
    width: 20px;
    height: 20px;
    place-items: center;
    border-radius: 999px;
    color: #fff;
    background: var(--color-accent);
    box-shadow: 0 2px 10px -2px var(--color-accent);
    animation: ap-tick 0.45s var(--jelly) both;
  }
  @keyframes ap-tick { from { transform: scale(0.3); opacity: 0; } }

  /* ── A theme's colours ────────────────────────────────────────────────── */
  .ap-swatches { display: flex; gap: 5px; padding: 5px 3px 0; }
  .ap-swatches i {
    width: 18px;
    height: 18px;
    border-radius: 6px;
    box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.3);
    transition: transform 0.4s var(--jelly);
  }
  .ap-card:hover .ap-swatches i { transform: translateY(-2px); }
  .ap-card:hover .ap-swatches i:nth-child(2) { transition-delay: 30ms; }
  .ap-card:hover .ap-swatches i:nth-child(3) { transition-delay: 60ms; }
  .ap-card:hover .ap-swatches i:nth-child(4) { transition-delay: 90ms; }

  /* ── A background, moving, with a panel on it for scale ───────────────── */
  .ap-scene { height: 74px !important; border-radius: 9px; box-shadow: inset 0 0 0 1px var(--color-edge); }
  /* A small window in the corner, for scale, clear of what moves in the middle. */
  .ap-scene-pane {
    position: absolute;
    z-index: 1;
    left: 8%;
    bottom: 12%;
    width: 36%;
    height: 34%;
    border-radius: 6px;
    background: color-mix(in srgb, var(--color-card) 55%, transparent);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08);
    backdrop-filter: blur(3px);
  }

  /* The ripple's rings, big enough to read at this size. */
  .ap-scene[data-kind="ripple"]::before,
  .ap-scene[data-kind="ripple"]::after { width: 60px; height: 60px; margin: -30px 0 0 -30px; }

  /* ── A panel over colour ──────────────────────────────────────────────── */
  .ap-surface {
    position: relative;
    display: block;
    height: 74px;
    overflow: hidden;
    border-radius: 9px;
    background: var(--color-bg);
    box-shadow: inset 0 0 0 1px var(--color-edge);
  }
  .ap-surface-blob { position: absolute; width: 60%; height: 120%; border-radius: 999px; filter: blur(8px); }
  .ap-surface-blob.is-a { left: -8%; top: -30%; background: color-mix(in srgb, var(--color-accent) 80%, transparent); }
  .ap-surface-blob.is-b { right: -10%; bottom: -40%; background: color-mix(in srgb, var(--color-accent-2) 75%, transparent); }
  .ap-surface-pane {
    position: absolute;
    inset: 16px 18px;
    display: flex;
    flex-direction: column;
    gap: 5px;
    padding: 8px;
    border-radius: 8px;
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.1);
  }
  .ap-surface-pane b { width: 50%; height: 4px; border-radius: 2px; background: var(--color-ink); opacity: 0.9; }
  .ap-surface-pane em { width: 78%; height: 3px; border-radius: 2px; background: var(--color-muted); opacity: 0.6; }
  .ap-surface-pane.is-glass { background: color-mix(in srgb, var(--color-card) 45%, transparent); backdrop-filter: blur(4px); }
  .ap-surface-pane.is-solid { background: var(--color-card); }
  .ap-surface-pane.is-frost { background: color-mix(in srgb, var(--color-card) 72%, transparent); backdrop-filter: blur(12px); }

  /* ── Your own picture ─────────────────────────────────────────────────── */
  .ap-own {
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    margin-bottom: 10px;
    padding: 10px;
    border-radius: 14px;
    border: 1px solid var(--color-edge);
    background: rgb(255 255 255 / 0.02);
  }
  .ap-own-img {
    width: 150px;
    height: 94px;
    flex-shrink: 0;
    border-radius: 10px;
    object-fit: cover;
    box-shadow: inset 0 0 0 1px var(--color-edge);
    filter: brightness(calc(1 - var(--dim) * 0.75));
    transition: filter 0.2s var(--swift);
  }
  .ap-own-body { display: flex; min-width: 200px; flex: 1; flex-direction: column; gap: 10px; }
  .ap-own-top { display: flex; align-items: center; gap: 10px; }
  .ap-own-name { overflow: hidden; font-size: 12.5px; font-weight: 600; color: var(--color-ink); text-overflow: ellipsis; white-space: nowrap; }
  .ap-dim { display: flex; align-items: center; gap: 10px; font-size: 11.5px; color: var(--color-muted); }
  .ap-dim b { width: 34px; font-family: ui-monospace, monospace; font-size: 11.5px; font-weight: 500; text-align: right; color: var(--color-ink); }
  .ap-dim.is-off { opacity: 0.5; }
  .ap-own-actions { display: flex; justify-content: flex-end; }

  /* ── Typefaces, set in themselves ─────────────────────────────────────── */
  .ap-font { flex-direction: row; align-items: center; gap: 14px; padding: 14px; }
  .ap-font .ap-name { margin-top: 0; font-size: 14px; }
  .ap-aa {
    display: grid;
    width: 58px;
    height: 58px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 14px;
    font-size: 26px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 9%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 22%, transparent);
    transition: transform 0.45s var(--jelly);
  }
  .ap-font:hover .ap-aa { transform: rotate(-4deg) scale(1.05); }
  .ap-sample { display: block; margin-top: 2px; padding: 0 3px; overflow: hidden; font-size: 12px; color: var(--color-muted); text-overflow: ellipsis; white-space: nowrap; }
  .ap-own-font { display: flex; align-items: center; gap: 10px; margin-top: 10px; font-size: 11.5px; color: var(--color-muted); }

  /* ── Opening: the colours flood in (lib/colorwave.ts) ──────────────────────
     Not the other tabs' drop and pop: out of grey along a quick diagonal wave
     (--d, a card's column plus its row), each section a little after the one
     above (--wave-at). Ease out, no bounce, about a third of a second each. */
  .ap-sec:not(:global(.is-in)) .ap-head h3,
  .ap-sec:not(:global(.is-in)) .ap-grid > * { opacity: 0; }
  .ap-sec:global(.is-in) .ap-head h3 { animation: ap-label 0.34s cubic-bezier(0.2, 0.8, 0.2, 1) backwards; animation-delay: var(--wave-at, 0ms); }
  @keyframes ap-label { from { opacity: 0; letter-spacing: 0.4em; } }
  .ap-sec:global(.is-in) .ap-grid > * {
    animation: ap-flood 0.36s cubic-bezier(0.2, 0.8, 0.2, 1) backwards;
    animation-delay: calc(var(--wave-at, 0ms) + var(--d, 0) * 26ms);
  }
  @keyframes ap-flood {
    0% { opacity: 0; transform: translate(-10px, 8px) scale(0.96); filter: grayscale(1) brightness(0.5); }
    45% { opacity: 1; }
  }
  /* A glint of light crossing each card as its colour comes. */
  .ap-card::after {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: inherit;
    pointer-events: none;
    opacity: 0;
    background: linear-gradient(115deg, transparent 38%, rgb(255 255 255 / 0.18) 50%, transparent 62%) no-repeat;
    background-size: 260% 100%;
  }
  .ap-sec:global(.is-in) .ap-card::after {
    animation: ap-sheen 0.5s ease-out backwards;
    animation-delay: calc(var(--wave-at, 0ms) + var(--d, 0) * 26ms + 40ms);
  }
  @keyframes ap-sheen { from { opacity: 1; background-position: 110% 0; } to { opacity: 1; background-position: -10% 0; } }
  /* A theme's colours spill out one after another, a glint each. */
  .ap-sec:global(.is-in) .ap-swatches i {
    animation: ap-dot 0.28s cubic-bezier(0.3, 1.7, 0.5, 1) backwards;
    animation-delay: calc(var(--wave-at, 0ms) + var(--d, 0) * 26ms + 60ms + var(--k, 0) * 22ms);
  }
  @keyframes ap-dot { from { transform: scale(0) rotate(-30deg); } }
  /* A background's preview develops like a photo. */
  .ap-sec:global(.is-in) .ap-scene {
    animation: ap-develop 0.5s ease-out backwards;
    animation-delay: calc(var(--wave-at, 0ms) + var(--d, 0) * 26ms + 30ms);
  }
  @keyframes ap-develop { from { filter: blur(6px) brightness(1.8) saturate(0.3); } }
  /* A panel's colours bloom, and its glass settles on them. */
  .ap-sec:global(.is-in) .ap-surface-blob {
    animation: ap-bloom 0.5s cubic-bezier(0.2, 0.8, 0.2, 1) backwards;
    animation-delay: calc(var(--wave-at, 0ms) + var(--d, 0) * 26ms);
  }
  @keyframes ap-bloom { from { opacity: 0; transform: scale(0.3); } }
  .ap-sec:global(.is-in) .ap-surface-pane {
    animation: ap-pane 0.4s cubic-bezier(0.3, 1.4, 0.5, 1) backwards;
    animation-delay: calc(var(--wave-at, 0ms) + var(--d, 0) * 26ms + 110ms);
  }
  @keyframes ap-pane { from { opacity: 0; transform: translateY(12px) scale(0.92); } }
  /* A typeface inks itself in, its sample written after it. */
  .ap-sec:global(.is-in) .ap-aa {
    animation: ap-ink 0.42s cubic-bezier(0.2, 0.8, 0.2, 1) backwards;
    animation-delay: calc(var(--wave-at, 0ms) + var(--d, 0) * 26ms + 40ms);
  }
  .ap-sec:global(.is-in) .ap-sample {
    animation: ap-ink 0.5s cubic-bezier(0.2, 0.8, 0.2, 1) backwards;
    animation-delay: calc(var(--wave-at, 0ms) + var(--d, 0) * 26ms + 110ms);
  }
  @keyframes ap-ink { from { clip-path: inset(0 100% 0 0); } to { clip-path: inset(0 0 0 0); } }
  /* The chosen one's tick, last, with its two notes; a tick that comes later, from a click, is quick. Held until
     the wave starts: popping as the page was put in, it was over before its card could be seen. */
  .ap-sec:not(:global(.is-in)) .ap-tick { animation: none; }
  .ap-sec:global(.is-waving) .ap-tick { animation-delay: calc(var(--wave-at, 0ms) + var(--d, 0) * 26ms + 260ms); }

  :global(:root[data-motion="off"]) .ap-tick { animation: none; }
  :global(:root[data-motion="off"]) .ap-swatches i,
  :global(:root[data-motion="off"]) .ap-aa { transition: none; }
  :global(:root[data-motion="off"]) .ap-sec .ap-head h3,
  :global(:root[data-motion="off"]) .ap-sec .ap-grid > *,
  :global(:root[data-motion="off"]) .ap-sec .ap-card::after,
  :global(:root[data-motion="off"]) .ap-sec .ap-swatches i,
  :global(:root[data-motion="off"]) .ap-sec .ap-scene,
  :global(:root[data-motion="off"]) .ap-sec .ap-surface-blob,
  :global(:root[data-motion="off"]) .ap-sec .ap-surface-pane,
  :global(:root[data-motion="off"]) .ap-sec .ap-aa,
  :global(:root[data-motion="off"]) .ap-sec .ap-sample { animation: none; opacity: 1; }
</style>
