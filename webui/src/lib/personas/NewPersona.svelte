<script lang="ts">
  /**
   * Making a profile, in place. The "New profile" tile grows into this card where it stands, the page still there
   * around it, rather than a window over a dimmed page; put away, it goes back into the tile.
   *
   * On one side what it will look like, changing as you type and pick; on the other its name, its colour or a theme of
   * two colours, and where it starts from. Fresh, it starts from the template with its name in; as a copy, from another's
   * text, settings and pictures, and its memory too when asked; or from your own chats, whose exports go in here too
   * (FromExports.svelte). The whole card takes the colour picked, its button and its focus rings too.
   */
  import { onDestroy, onMount, untrack } from "svelte";
  import { get } from "svelte/store";
  import { motionEnabled } from "../stores";
  import { play } from "../uisound";
  import Button from "../components/Button.svelte";
  import Icon from "../components/Icon.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Toggle from "../components/Toggle.svelte";
  import PersonaOrb from "./PersonaOrb.svelte";
  import ColorDots from "./ColorDots.svelte";
  import FromExports from "./FromExports.svelte";
  import { nextColor, type Persona, type PersonaTheme } from "./logic";

  let {
    open = $bindable(false),
    list,
    palette,
    themes = [],
    copyOf = "",
    busy = false,
    from = null,
    only = "",
    oncreate,
    oncreated,
  }: {
    open?: boolean;
    list: Persona[];
    palette: { id: string; name: string; hex: string }[];
    themes?: PersonaTheme[];
    /** Opened as "Duplicate": starts as a copy of this one. */
    copyOf?: string;
    busy?: boolean;
    /** Where the tile was when it was pressed: the card grows out of there. */
    from?: DOMRect | null;
    /** Opened for one way of starting only, with no choosing: the Persona page's "From your chats". */
    only?: "" | "chats";
    oncreate?: (body: { name: string; color: string; color2?: string; copy_from?: string; copy_memory?: boolean; face?: File | null }) => void;
    /** Made from your own chats: that part makes it itself. Its picture is the caller's to put on. */
    oncreated?: (persona: any, face: File | null) => void;
  } = $props();

  let name = $state("");
  let color = $state(untrack(() => nextColor(list, palette)));
  let second = $state("");
  let start = $state<"fresh" | "copy" | "chats">(untrack(() => (only === "chats" ? "chats" : copyOf ? "copy" : "fresh")));
  let source = $state(untrack(() => copyOf || list.find((p) => p.is_default)?.id || "default"));
  let withMemory = $state(false);
  let face = $state<File | null>(null);
  let faceUrl = $state("");
  let over = $state(false);
  let root: HTMLElement | null = $state(null);
  let field: HTMLInputElement | null = $state(null);
  let picker: HTMLInputElement | null = $state(null);

  // "Duplicate" pressed on another card while this is open: a copy of that one, what is typed kept.
  $effect(() => {
    if (copyOf) {
      start = "copy";
      source = copyOf;
    }
  });

  const sourceP = $derived(list.find((p) => p.id === source));
  const sourceName = $derived(sourceP?.name ?? "");
  const preview = $derived({ name: name.trim() || "?", color, color2: second,
                             avatar: faceUrl || (start === "copy" ? sourceP?.avatar ?? "" : "") });
  const ready = $derived(name.trim().length > 0 && !busy);
  const line = $derived(start === "copy" ? `A copy of ${sourceName}`
    : start === "chats" ? "Made from your own messages" : "A fresh start");

  // ── Growing out of the tile, and going back into it ──────────────────────
  const EASE = "cubic-bezier(0.22, 1, 0.36, 1)";
  const WHOLE = "inset(0px 0px 0px 0px round 22px)";

  /** The tile's place on this card: what shows of it, and how far it is moved to sit where the tile was. */
  function tileFrame() {
    if (!root || !from) return null;
    const to = root.getBoundingClientRect();
    const left = Math.max(0, from.left - to.left);
    const right = Math.max(0, to.right - from.right);
    const bottom = Math.max(0, to.height - from.height);
    return { clipPath: `inset(0px ${right}px ${bottom}px ${left}px round 22px)`, transform: `translateY(${from.top - to.top}px)` };
  }

  onMount(() => {
    if (only !== "chats") field?.focus({ preventScroll: true });
    const moving = get(motionEnabled);
    const frame = tileFrame();
    root?.scrollIntoView({ block: "nearest", behavior: moving ? "smooth" : "auto" });
    if (moving && frame) {
      root?.animate([frame, { clipPath: WHOLE, transform: "none" }], { duration: 460, easing: EASE });
    }
  });
  onDestroy(() => {
    if (faceUrl) URL.revokeObjectURL(faceUrl);
  });

  let shutting = false;
  function shut() {
    if (shutting) return;
    const frame = get(motionEnabled) ? tileFrame() : null;
    if (!frame || !root) {
      open = false;
      return;
    }
    shutting = true;
    const leaving = root.animate([{ clipPath: WHOLE, transform: "none", opacity: 1 }, { ...frame, opacity: 0 }],
                                 { duration: 240, easing: "cubic-bezier(0.4, 0, 0.7, 0.4)", fill: "forwards" });
    leaving.onfinish = () => (open = false);
  }

  // ── What is picked ───────────────────────────────────────────────────────
  function pickColor(hex: string) {
    color = hex;
    second = "";
  }
  function pickTheme(t: PersonaTheme) {
    if (t.a === color && t.b === second) return;
    play("glint", { strong: true });
    color = t.a;
    second = t.b;
  }

  function takeFace(file: File | null | undefined) {
    if (!file || !file.type.startsWith("image/")) return;
    if (faceUrl) URL.revokeObjectURL(faceUrl);
    face = file;
    faceUrl = URL.createObjectURL(file);
    play("drop");
  }
  function dropFace() {
    if (faceUrl) URL.revokeObjectURL(faceUrl);
    face = null;
    faceUrl = "";
  }
  const holdsFile = (e: DragEvent) => !!e.dataTransfer?.types?.includes("Files");
  function held(e: DragEvent) {
    if (!holdsFile(e)) return;
    e.preventDefault();
    if (!over) play("lift");
    over = true;
  }
  function dropped(e: DragEvent) {
    if (!holdsFile(e)) return;
    e.preventDefault();
    over = false;
    takeFace(e.dataTransfer?.files?.[0]);
  }

  function submit() {
    if (!ready || start === "chats") return;
    oncreate?.({
      name: name.trim(),
      color,
      color2: second,
      face,
      ...(start === "copy" ? { copy_from: source, copy_memory: withMemory } : {}),
    });
  }
</script>

<svelte:window onkeydown={(e) => { if (e.key === "Escape") shut(); }} />

<!-- Not a <form>: Button has no type, so every button in one (Cancel too) would send it. Enter in the name does. -->
<section class="np glass" bind:this={root} aria-label="New profile" style="--color-accent: {color}; --np-a: {color}; --np-b: {second || color}">
  <div class="np-show" class:is-over={over} role="group" aria-label="What it will look like"
       ondragenter={held} ondragover={held} ondragleave={() => (over = false)} ondrop={dropped}>
    <span class="np-orb"><PersonaOrb p={preview} size={104} spin /></span>
    <b class="np-show-name" class:is-empty={!name.trim()}>{name.trim() || "New profile"}</b>
    <small class="np-show-line">{line}</small>
    <span class="np-face-tools">
      <input bind:this={picker} type="file" accept="image/*" hidden
             onchange={(e) => { takeFace(e.currentTarget.files?.[0]); e.currentTarget.value = ""; }} />
      <button type="button" class="np-face-btn" onclick={() => picker?.click()} data-sound="self">
        <Icon name="upload" size={12} />{face ? "Another picture" : "Add a picture"}
      </button>
      {#if face}
        <button type="button" class="np-face-x" onclick={dropFace} aria-label="Take the picture off" title="Take it off"><Icon name="close" size={10} /></button>
      {/if}
    </span>
  </div>

  <div class="np-form">
    <label class="np-field" style="--n: 0">
      <span>Name</span>
      <input class="np-name" bind:this={field} bind:value={name} maxlength="40" placeholder="Who is it?" spellcheck="false"
             onkeydown={(e) => { if (e.key === "Enter") submit(); }} />
    </label>

    <div class="np-field" style="--n: 1">
      <span>Colour</span>
      <ColorDots {palette} value={second ? "" : color} size={22} columns={Math.ceil(palette.length / 2)} onpick={pickColor} />
    </div>

    {#if themes.length}
      <div class="np-field" style="--n: 2">
        <span>Theme</span>
        <div class="np-themes" role="radiogroup" aria-label="Theme">
          {#each themes as t (t.id)}
            {@const on = t.a === color && t.b === second}
            <button type="button" role="radio" aria-checked={on} class="np-theme" class:is-on={on} data-sound="self"
                    style="--a: {t.a}; --b: {t.b}" onclick={() => pickTheme(t)}>
              {t.name}{#if on}<Icon name="check" size={11} />{/if}
            </button>
          {/each}
        </div>
      </div>
    {/if}

    <div class="np-field" style="--n: 3">
      {#if only === "chats"}
        <span>Your chats</span>
      {:else}
        <span>Start from</span>
        <span class="np-start">
          <Segmented label="Start from" value={start}
                     options={[{ id: "fresh", label: "Fresh" }, { id: "copy", label: "A copy" }, { id: "chats", label: "Your chats" }]}
                     onchange={(id) => (start = id as typeof start)} />
        </span>
      {/if}
      {#if start === "copy"}
        <div class="np-copy">
          <div class="np-sources">
            {#each list as p (p.id)}
              <button type="button" class="np-source" class:is-on={source === p.id} style="--pc: {p.color || 'var(--color-accent)'}"
                      onclick={() => (source = p.id)}>
                <PersonaOrb {p} size={22} ring={false} />
                <span>{p.name}</span>
              </button>
            {/each}
          </div>
          <p class="np-note">Its text, settings and pictures come with it.</p>
          <div class="np-row">
            <span>Copy its memory too<small>What {sourceName} knows about people</small></span>
            <Toggle checked={withMemory} onchange={(v: boolean) => (withMemory = v)} name="Copy its memory" />
          </div>
        </div>
      {:else if start === "chats"}
        <div class="np-chats"><FromExports bind:name {color} color2={second} oncancel={shut} oncreated={(p: any) => oncreated?.(p, face)} /></div>
      {:else}
        <p class="np-note">Starts from the template with its name in. No pictures or memory yet.</p>
      {/if}
    </div>

    {#if start !== "chats"}
      <div class="np-actions" style="--n: 4">
        <Button kind="ghost" size="sm" onclick={shut}>Cancel</Button>
        <Button size="sm" onclick={submit} disabled={!ready} loading={busy}>Create</Button>
      </div>
    {/if}
  </div>
</section>

<style>
  /* The colours as colours rather than words, so they can ease from one to the next as they are picked. */
  @property --np-a { syntax: "<color>"; inherits: true; initial-value: #a78bfa; }
  @property --np-b { syntax: "<color>"; inherits: true; initial-value: #a78bfa; }

  .np {
    position: relative;
    display: grid;
    grid-column: 1 / -1;
    grid-template-columns: minmax(230px, 280px) minmax(0, 1fr);
    gap: 20px;
    padding: 16px 20px 16px 16px;
    border-radius: 22px;
    background-image:
      radial-gradient(70% 90% at 0% 0%, color-mix(in srgb, var(--np-a) 12%, transparent), transparent 70%),
      radial-gradient(60% 80% at 100% 100%, color-mix(in srgb, var(--np-b) 10%, transparent), transparent 70%);
    transition: --np-a 0.45s ease, --np-b 0.45s ease;
  }

  /* ── What it will look like ── */
  /* In sight beside a long form: the steps of an export can run on past it. */
  .np-show {
    position: sticky;
    top: 8px;
    display: flex;
    min-height: 320px;
    align-self: start;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 22px 16px;
    border-radius: 18px;
    text-align: center;
    background:
      radial-gradient(95% 70% at 25% 15%, color-mix(in srgb, var(--np-a) 40%, transparent), transparent 74%),
      radial-gradient(95% 70% at 80% 90%, color-mix(in srgb, var(--np-b) 34%, transparent), transparent 74%),
      rgb(255 255 255 / 0.025);
    transition: box-shadow 0.2s ease;
  }
  .np-show.is-over { box-shadow: inset 0 0 0 2px var(--np-a); }
  .np-orb { display: grid; margin-bottom: 10px; place-items: center; animation: np-orb 0.6s var(--jelly) backwards 0.1s; }
  @keyframes np-orb { from { opacity: 0; transform: scale(0.7) rotate(-14deg); } }
  .np-show-name {
    display: block;
    max-width: 100%;
    overflow: hidden;
    font-size: 21px;
    font-weight: 750;
    letter-spacing: -0.015em;
    line-height: 1.25;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--color-ink);
  }
  .np-show-name.is-empty { color: color-mix(in srgb, var(--color-ink) 45%, transparent); }
  .np-show-line { font-size: 12px; color: color-mix(in srgb, var(--color-ink) 62%, transparent); }
  .np-face-tools { display: flex; align-items: center; gap: 4px; margin-top: 12px; }
  .np-face-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    color: var(--color-ink);
  }
  .np-face-x { display: grid; width: 26px; height: 26px; place-items: center; border-radius: 999px; color: var(--color-ink); background: rgb(255 255 255 / 0.08); transition: background-color 0.15s ease; }
  .np-face-x:hover { background: rgb(255 255 255 / 0.16); }

  /* ── Choosing ── */
  .np-form { display: flex; min-width: 0; flex-direction: column; gap: 14px; padding: 4px 0; }
  .np-field, .np-actions { animation: np-rise 0.44s cubic-bezier(0.22, 1, 0.36, 1) backwards; animation-delay: calc(90ms + var(--n, 0) * 38ms); }
  @keyframes np-rise { from { opacity: 0; transform: translateY(10px); } }
  .np-field { display: flex; flex-direction: column; gap: 8px; }
  .np-field > span:first-child { font-size: 11px; font-weight: 650; letter-spacing: 0.08em; text-transform: uppercase; color: var(--color-faint); }
  .np-name {
    width: 100%;
    padding: 11px 14px;
    border-radius: 13px;
    font-size: 18px;
    font-weight: 650;
    letter-spacing: -0.01em;
    color: var(--color-ink);
    caret-color: var(--np-a);
    background: color-mix(in srgb, var(--np-a) 9%, rgb(255 255 255 / 0.03));
    outline: none;
    transition: background-color 0.2s ease, box-shadow 0.2s ease;
  }
  .np-name::placeholder { font-weight: 500; color: var(--color-faint); }
  .np-name:focus { background: color-mix(in srgb, var(--np-a) 13%, rgb(255 255 255 / 0.03)); box-shadow: 0 0 0 3px color-mix(in srgb, var(--np-a) 26%, transparent); }
  .np-themes { display: grid; grid-template-columns: repeat(auto-fill, minmax(82px, 1fr)); gap: 7px; }
  .np-theme {
    display: inline-flex;
    height: 38px;
    align-items: center;
    justify-content: center;
    gap: 4px;
    border-radius: 11px;
    font-size: 12px;
    font-weight: 650;
    color: rgb(10 10 16 / 0.82);
    background: linear-gradient(125deg, var(--a), var(--b));
    transition: transform 0.35s var(--jelly), box-shadow 0.2s var(--swift);
  }
  .np-theme:hover { transform: translateY(-2px) scale(1.03); }
  .np-theme:active { transform: scale(0.97); }
  .np-theme.is-on { box-shadow: 0 0 0 2px var(--color-card), 0 0 0 4px var(--a), 0 8px 18px -8px var(--b); }
  .np-theme:focus-visible { outline: 2px solid var(--a); outline-offset: 3px; }
  .np-start { width: 320px; max-width: 100%; }
  .np-copy { display: flex; flex-direction: column; gap: 10px; animation: np-in 0.3s var(--jelly); }
  @keyframes np-in { from { opacity: 0; transform: translateY(-4px); } }
  .np-sources { display: flex; flex-wrap: wrap; gap: 6px; }
  .np-source {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 4px 10px 4px 4px;
    border-radius: 999px;
    font-size: 12.5px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
    transition: color 0.15s ease, background-color 0.15s ease, box-shadow 0.15s ease;
  }
  .np-source:hover { color: var(--color-ink); }
  .np-source.is-on { color: var(--color-ink); background: color-mix(in srgb, var(--pc) 16%, transparent); box-shadow: inset 0 0 0 1px var(--pc); }
  .np-chats { animation: np-in 0.3s var(--jelly); }
  .np-note { font-size: 12px; line-height: 1.5; color: var(--color-muted); }
  .np-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 13px; color: var(--color-ink); }
  .np-row small { display: block; font-size: 11px; color: var(--color-faint); }
  .np-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: auto; padding-top: 2px; }

  @media (max-width: 860px) {
    .np { grid-template-columns: minmax(0, 1fr); }
    .np-show { position: static; min-height: 0; align-self: stretch; }
  }
  :global(:root[data-motion="off"]) .np { transition: none; }
  :global(:root[data-motion="off"]) .np-orb,
  :global(:root[data-motion="off"]) .np-field,
  :global(:root[data-motion="off"]) .np-actions,
  :global(:root[data-motion="off"]) .np-copy,
  :global(:root[data-motion="off"]) .np-chats { animation: none; }
</style>
