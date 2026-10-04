<script lang="ts">
  /**
   * A look for a picture, or for several at once.
   *
   * The picture big on the left, on a soft glow of its own colours, each look
   * crossfading in over the one before; the looks on the right as tiles of the
   * picture itself, named, popping in one after another as the window opens,
   * with a tile at the top that lets the AI pick. Holding the picture down shows
   * it as it was. Apply puts the look on, made from the original, which is
   * always kept (app/web/routes/media_routes.py), so "Original" takes it off
   * again whenever. The previews are the server's own renders
   * (app/utils/looks.py), so what you see is what the bot sends.
   */
  import Modal from "./Modal.svelte";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import { api } from "../api";
  import { play } from "../uisound";
  import { toast } from "../stores";
  import { springValue } from "../spring";
  import { domino } from "../domino";

  type Pic = { name: string; id?: string; look?: string; strength?: number; moving?: boolean };
  type Look = { id: string; name: string; group?: string };

  let {
    pics = [],
    looks = [],
    open = $bindable(false),
    onapplied,
    persona = "",
  }: {
    pics: Pic[];
    looks: Look[];
    open?: boolean;
    onapplied?: () => void;
    /** Whose pictures these are ("" for Default's): each persona's are in a folder of their own. */
    persona?: string;
  } = $props();

  /** The picture the previews are drawn on: the first one a look can go on. */
  const first = $derived(pics.find((p) => p.id && !p.moving) ?? null);
  const still = $derived(pics.filter((p) => !p.moving));
  let look = $state("");
  let strength = $state(0.7);
  /** The strength the big preview is drawn at: follows the slider, a beat behind, so a drag is not forty renders. */
  let shownStrength = $state(0.7);
  let holding = $state(false);
  let saving = $state(false);

  // ── Auto: the AI picks, from what the picture shows ──────────────────────
  /** Picked by the AI: shown on the picture at once; with several, each gets its own pick on Apply. */
  let auto = $state(false);
  let thinking = $state(false);
  /** The look the AI picked for the picture shown, marked on its tile. */
  let aiPick = $state("");
  /** Which ask may land: one still on its way when the window was closed, or Auto left, is not wanted any more. */
  let ticket = 0;

  // Opened: start from what the picture has on it now.
  let openedFor = "";
  $effect(() => {
    const key = open && first ? `${first.id}:${pics.length}` : "";
    if (!key || key === openedFor) {
      if (!open) {
        openedFor = "";
        ticket++;
        thinking = false;
      }
      return;
    }
    openedFor = key;
    look = first?.look ?? "";
    strength = first?.strength && first.strength > 0 ? first.strength : 0.7;
    shownStrength = strength;
    auto = false;
    aiPick = "";
    thinking = false;
    shownSrc = "";
    underSrc = "";
  });

  let follow = 0;
  function onStrength(v: number) {
    strength = v;
    clearTimeout(follow);
    follow = window.setTimeout(() => (shownStrength = strength), 140);
  }

  function pick(id: string) {
    // Picking one by hand while the AI thinks: what it says when it answers is not wanted any more.
    if (auto) ticket++;
    auto = false;
    thinking = false;
    if (id === look) return;
    play("select");
    look = id;
  }

  async function pickAuto() {
    if (thinking || !first) return;
    play("select");
    const mine = ++ticket;
    auto = true;
    thinking = true;
    try {
      const r: any = await api.aiLookFor(first.name, first.id ?? "", persona);
      if (mine !== ticket || !open) return;
      aiPick = r.look;
      look = r.look;
      play("glint", { p: 1, strong: true });
    } catch (e: any) {
      if (mine !== ticket || !open) return;
      auto = false;
      play("err");
      toast(e?.message || "The AI could not pick one", "err");
    } finally {
      if (mine === ticket) thinking = false;
    }
  }

  // ── The big picture, crossfading from one look to the next ───────────────
  const big = $derived(first?.id ? api.lookPreviewUrl(first.id, holding ? "" : look, shownStrength, 760, persona) : "");
  /** On top, and the one before it under, fading out as the new one fades in once it has loaded. */
  let shownSrc = $state("");
  let underSrc = $state("");
  $effect(() => {
    const src = big;
    if (!src || src === shownSrc) return;
    const img = new Image();
    img.onload = () => {
      if (big !== src) return;
      underSrc = shownSrc;
      shownSrc = src;
    };
    img.src = src;
  });
  const drawing = $derived(!!big && big !== shownSrc);

  const thumb = (id: string) => (first?.id ? api.lookPreviewUrl(first.id, id, id ? 0.85 : 0, 180, persona) : "");
  const fill = $derived(`${Math.round(((strength - 0.05) / 0.95) * 100)}%`);
  const changed = $derived(!!first && (look !== (first.look ?? "") || (look !== "" && Math.abs(strength - (first.strength ?? 0)) > 0.001)));
  const nameOf = (id: string) => looks.find((l) => l.id === id)?.name ?? "";

  async function apply() {
    if (!still.length) return;
    saving = true;
    if (auto && still.length > 1) return applyEach();
    try {
      const r: any = await api.putLook(still.map((p) => ({ name: p.name, id: p.id })), look, strength, persona);
      const done = (r.results ?? []).filter((x: any) => !x.error).length;
      const failed = (r.results ?? []).find((x: any) => x.error);
      play("ok");
      toast(look
        ? `${nameOf(look)} filter added${done === 1 ? "" : ` to ${done} pictures`}.`
        : `Filter removed${done === 1 ? "" : ` from ${done} pictures`}.`, "ok");
      if (failed) toast(`${failed.name}: ${failed.error}`, "info");
      open = false;
      onapplied?.();
    } catch (e: any) {
      play("err");
      toast(e?.message || "Could not add the filter", "err");
    }
    saving = false;
  }

  /** Auto on several: each picture gets the look the AI picks for it. One it cannot pick for is left as it is. */
  async function applyEach() {
    let done = 0;
    let missed = "";
    for (const p of still) {
      try {
        const r: any = await api.aiLookFor(p.name, p.id ?? "", persona);
        await api.putLook([{ name: p.name, id: p.id }], r.look, strength, persona);
        done++;
      } catch (e: any) {
        missed ||= `${p.name}: ${e?.message || "no pick"}`;
      }
    }
    saving = false;
    if (done) {
      play("ok");
      toast(`Filters picked and added to ${done} picture${done === 1 ? "" : "s"}.`, "ok");
      open = false;
      onapplied?.();
    } else play("err");
    if (missed) toast(missed, done ? "info" : "err");
  }
</script>

<Modal bind:open title={pics.length > 1 ? `Filter for ${still.length} pictures` : "Filter"} wide>
  {#if first}
    <div class="le">
      <!-- The picture, on a glow of its own colours. Held down: as it was. -->
      <div class="le-stage">
        {#if shownSrc}<img class="le-glow" src={shownSrc} alt="" aria-hidden="true" />{/if}
        <button type="button" class="le-big" class:is-holding={holding}
                onpointerdown={() => (holding = true)} onpointerup={() => (holding = false)}
                onpointerleave={() => (holding = false)} onpointercancel={() => (holding = false)}
                title="Hold to see the original" aria-label="Hold to see the original">
          {#if underSrc}<img class="le-under" src={underSrc} alt="" draggable="false" />{/if}
          {#key shownSrc}{#if shownSrc}<img class="le-top" src={shownSrc} alt="" draggable="false" />{/if}{/key}
          {#if drawing}<span class="le-drawing" aria-hidden="true"></span>{/if}
          <span class="le-hint">
            {#if holding}Original{:else}<Icon name="eye" size={12} /> Hold to compare{/if}
          </span>
        </button>
      </div>

      <div class="le-side">
        <!-- The AI picks one from what the picture shows (its description). -->
        <button type="button" class="le-auto" class:is-on={auto} class:is-thinking={thinking} onclick={pickAuto}
                aria-pressed={auto} aria-busy={thinking}>
          <span class="le-auto-icon"><Icon name="sparkle" size={17} /></span>
          <span class="min-w-0 flex-1 text-left">
            <span class="le-auto-title">Auto</span>
            <span class="le-auto-sub">
              {#if thinking}Picking one for this picture
              {:else if auto && aiPick}The AI picked {nameOf(aiPick)}
              {:else}The AI picks one that suits it{/if}
            </span>
          </span>
          {#if auto && !thinking}<span class="le-auto-check"><Icon name="check" size={12} /></span>{/if}
        </button>

        <!-- In groups (Colour, Mood, Film, Black & white), scrolling on its own so the picture stays in view. -->
        <div class="le-grid domino" role="radiogroup" aria-label="Filters"
             use:domino={{ step: 22, sound: "wind", level: 0.45, once: true }}>
          {#if looks[0]?.group}<span class="le-group">{looks[0].group}</span>{/if}
          <button type="button" class="le-tile" class:is-on={!auto && look === ""} role="radio"
                  aria-checked={!auto && look === ""} onclick={() => pick("")}>
            <img src={thumb("")} alt="" loading="lazy" />
            <span class="le-name">Original</span>
          </button>
          {#each looks as l, i (l.id)}
            {#if i > 0 && l.group && l.group !== looks[i - 1].group}<span class="le-group">{l.group}</span>{/if}
            <button type="button" class="le-tile" class:is-on={look === l.id && (!auto || !thinking)}
                    class:is-ai={auto && aiPick === l.id} role="radio" aria-checked={look === l.id}
                    onclick={() => pick(l.id)}>
              <img src={thumb(l.id)} alt="" loading="lazy" />
              <span class="le-name">{l.name}</span>
              {#if auto && aiPick === l.id}<span class="le-ai-badge"><Icon name="sparkle" size={10} /></span>{/if}
            </button>
          {/each}
        </div>

        <div class="le-strength" class:is-off={!look} data-slider-row>
          <span class="le-label">{look ? nameOf(look) : "Strength"}</span>
          <input type="range" class="slider" min="0.05" max="1" step="0.05" value={strength} disabled={!look}
                 style="--fill: {fill}" aria-label="Strength"
                 oninput={(e) => onStrength(parseFloat((e.target as HTMLInputElement).value))}
                 onchange={() => play("tick")} use:springValue />
          <span class="le-pct slider-value">{Math.round(strength * 100)}%</span>
        </div>

        {#if pics.length !== still.length}
          <p class="le-note">{pics.length - still.length === 1 ? "One is animated, so it stays as it is." : `${pics.length - still.length} are animated, so they stay as they are.`}</p>
        {/if}

        <div class="le-actions">
          <Button kind="ghost" onclick={() => (open = false)}>Cancel</Button>
          <Button loading={saving} disabled={thinking || (!changed && pics.length === 1)} onclick={apply}>
            {auto || look ? "Apply" : "Remove filter"}
          </Button>
        </div>
      </div>
    </div>
  {:else}
    <p class="text-[13px] text-muted">Animated pictures can't take a filter.</p>
  {/if}
</Modal>

<style>
  .le {
    display: grid;
    grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr);
    /* The one row held to the window's height: left to its content it grew to the whole list of looks, the picture
       stretched with it and sat at the foot, and the list never scrolled. */
    grid-template-rows: minmax(0, 1fr);
    gap: 20px;
    align-items: stretch;
    height: min(600px, calc(88vh - 110px));
  }
  @media (max-width: 760px) {
    .le { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto; height: auto; }
    .le-stage { min-height: 260px; max-height: 46vh; }
  }

  /* ── The picture ── */
  .le-stage {
    position: relative;
    display: grid;
    place-items: center;
    min-height: 300px;
    overflow: hidden;
    border-radius: 20px;
    background: rgb(0 0 0 / 0.4);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    isolation: isolate;
  }
  /* Its own colours, blurred, as light behind it. */
  .le-glow {
    position: absolute;
    inset: -20%;
    z-index: -1;
    width: 140%;
    height: 140%;
    object-fit: cover;
    filter: blur(42px) saturate(1.5);
    opacity: 0.5;
    transition: opacity 0.4s ease;
  }
  .le-big {
    position: relative;
    display: grid;
    place-items: center;
    width: 100%;
    height: 100%;
    max-height: 62vh;
    padding: 14px;
    cursor: zoom-in;
    user-select: none;
    -webkit-user-select: none;
    touch-action: none;
  }
  .le-big img {
    grid-area: 1 / 1;
    max-width: 100%;
    max-height: calc(62vh - 28px);
    border-radius: 14px;
    object-fit: contain;
    box-shadow: 0 18px 44px -18px rgb(0 0 0 / 0.9);
  }
  .le-top { animation: le-fade 0.32s ease both; }
  @keyframes le-fade { from { opacity: 0; } }
  .le-big.is-holding .le-top { transition: transform 0.25s var(--spring); transform: scale(0.985); }
  /* A new look being drawn: a thin light running round the corner, rather than the picture blurring. */
  .le-drawing {
    position: absolute;
    top: 22px;
    right: 22px;
    width: 18px;
    height: 18px;
    border-radius: 999px;
    border: 2px solid rgb(255 255 255 / 0.25);
    border-top-color: #fff;
    animation: le-spin 0.7s linear infinite;
  }
  @keyframes le-spin { to { transform: rotate(360deg); } }
  .le-hint {
    position: absolute;
    left: 50%;
    bottom: 22px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 12px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 600;
    color: #fff;
    background: rgb(8 8 16 / 0.55);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.14);
    backdrop-filter: blur(10px);
    transform: translateX(-50%);
    pointer-events: none;
    transition: background-color 0.2s ease;
  }
  .le-big.is-holding .le-hint { background: color-mix(in srgb, var(--color-accent) 70%, rgb(0 0 0)); }

  /* ── The side ── */
  .le-side { display: flex; flex-direction: column; gap: 14px; min-width: 0; min-height: 0; }

  /* Auto: a tile of its own, the AI's sparkle on the accent; a ring turning round it while it thinks. */
  .le-auto {
    position: relative;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 11px 14px;
    border-radius: 16px;
    background: linear-gradient(120deg, color-mix(in srgb, var(--color-accent) 16%, transparent),
                color-mix(in srgb, var(--color-accent-2, var(--color-accent)) 10%, transparent));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 30%, transparent);
    transition: transform 0.3s var(--jelly), box-shadow 0.2s ease;
  }
  .le-auto:hover { transform: translateY(-1px); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 55%, transparent); }
  .le-auto:active { transform: scale(0.98); }
  .le-auto.is-on { box-shadow: inset 0 0 0 1.5px var(--color-accent), 0 10px 26px -14px var(--color-accent); }
  .le-auto-icon {
    position: relative;
    display: grid;
    place-items: center;
    width: 36px;
    height: 36px;
    flex-shrink: 0;
    border-radius: 12px;
    color: #fff;
    background: var(--color-accent);
    box-shadow: 0 6px 16px -6px var(--color-accent);
  }
  .le-auto.is-thinking .le-auto-icon { animation: le-twinkle 0.9s ease-in-out infinite; }
  .le-auto.is-thinking .le-auto-icon::after {
    content: "";
    position: absolute;
    inset: -4px;
    border-radius: 15px;
    padding: 2px;
    background: conic-gradient(from var(--le-turn, 0deg), var(--color-accent), transparent 55%, var(--color-accent));
    -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    -webkit-mask-composite: xor;
    mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    mask-composite: exclude;
    animation: le-turn 0.9s linear infinite;
  }
  @property --le-turn { syntax: "<angle>"; inherits: false; initial-value: 0deg; }
  @keyframes le-turn { to { --le-turn: 360deg; } }
  @keyframes le-twinkle { 50% { transform: scale(1.08) rotate(10deg); } }
  .le-auto-title { display: block; font-size: 13.5px; font-weight: 700; color: var(--color-ink); }
  .le-auto-sub { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11.5px;
    color: var(--color-muted); }
  .le-auto-check {
    display: grid;
    place-items: center;
    width: 22px;
    height: 22px;
    border-radius: 999px;
    color: var(--color-bg);
    background: var(--color-accent);
    animation: le-pop 0.4s var(--jelly);
  }

  /* The looks: tiles of the picture itself, named on a shade along their foot, in their groups. */
  .le-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(76px, 1fr));
    /* Each row its tiles' own height, the grid scrolling: held to the space left, the rows were squeezed to share it
       and the square tiles lay over one another. */
    grid-auto-rows: max-content;
    gap: 7px;
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    margin: 0 -6px;
    padding: 2px 6px 6px;
    align-content: start;
  }
  @media (max-width: 760px) {
    .le-grid { overflow: visible; }
  }
  .le-group {
    grid-column: 1 / -1;
    margin-top: 6px;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--color-faint);
  }
  .le-group:first-child { margin-top: 0; }
  .le-tile {
    position: relative;
    aspect-ratio: 1;
    overflow: hidden;
    border-radius: 14px;
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06);
    transition: transform 0.3s var(--jelly), box-shadow 0.2s ease;
  }
  .le-tile img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.4s var(--spring); }
  .le-tile:hover { transform: translateY(-2px); }
  .le-tile:hover img { transform: scale(1.08); }
  .le-tile:active { transform: scale(0.95); }
  .le-name {
    position: absolute;
    inset: auto 0 0 0;
    padding: 14px 6px 5px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 11px;
    font-weight: 650;
    color: #fff;
    background: linear-gradient(transparent, rgb(0 0 0 / 0.72));
  }
  .le-tile.is-on {
    box-shadow: inset 0 0 0 2px var(--color-accent), 0 10px 24px -12px var(--color-accent);
    transform: translateY(-2px);
  }
  .le-tile.is-ai { animation: le-picked 0.5s var(--jelly); }
  .le-ai-badge {
    position: absolute;
    top: 5px;
    right: 5px;
    display: grid;
    place-items: center;
    width: 20px;
    height: 20px;
    border-radius: 999px;
    color: #fff;
    background: var(--color-accent);
    box-shadow: 0 2px 8px -2px var(--color-accent);
    animation: le-pop 0.4s var(--jelly);
  }
  @keyframes le-picked { 40% { transform: scale(1.1); } }
  @keyframes le-pop { from { transform: scale(0.3); opacity: 0; } }

  .le-strength { display: flex; align-items: center; gap: 12px; margin-top: auto; transition: opacity 0.2s ease; }
  .le-strength.is-off { opacity: 0.45; }
  .le-label { min-width: 68px; font-size: 12.5px; font-weight: 650; color: var(--color-muted); }
  .le-strength .slider { flex: 1; min-width: 0; }
  .le-pct { width: 42px; text-align: right; font-size: 12.5px; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--color-ink); }
  .le-note { font-size: 12px; color: var(--color-faint); }
  .le-actions { display: flex; justify-content: flex-end; gap: 8px; }

  :global(:root[data-motion="off"]) .le-tile,
  :global(:root[data-motion="off"]) .le-tile img,
  :global(:root[data-motion="off"]) .le-auto { transition: none; }
  :global(:root[data-motion="off"]) .le-top,
  :global(:root[data-motion="off"]) .le-drawing,
  :global(:root[data-motion="off"]) .le-auto-icon,
  :global(:root[data-motion="off"]) .le-auto-icon::after,
  :global(:root[data-motion="off"]) .le-tile.is-ai,
  :global(:root[data-motion="off"]) .le-ai-badge,
  :global(:root[data-motion="off"]) .le-auto-check { animation: none; }
</style>
