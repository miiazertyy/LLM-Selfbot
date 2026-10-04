<script lang="ts">
  /**
   * A video in a chat, played in the app's own player.
   *
   * The browser's <video controls> is a different design in every engine,
   * small, and fiddly to use: no speed, no looping, no keyboard beyond the
   * space bar, a volume that forgets itself. This is the same <video>
   * underneath with controls of the app's own:
   *
   *  - click to play or pause, double-click for full screen, a big play
   *    button over the first frame, and a spinner while it buffers;
   *  - a seek bar that shows what has loaded, the time under the pointer,
   *    and can be dragged; the time played and the length;
   *  - volume with a slider, mute, and both remembered for next time;
   *  - speed (0.25x to 2x), loop, picture in picture where the engine has
   *    it, save, and full screen;
   *  - the keys people know: Space or K, J and L for ten seconds, the arrows
   *    for five and for volume, M, F, 0 to 9 to jump, < and > for speed,
   *    and , . a frame at a time while paused.
   *
   * The controls step aside while it plays and the pointer is still, and come
   * back as soon as it moves.
   */
  import { onMount } from "svelte";
  import Icon from "./Icon.svelte";
  import { saveUrlAs } from "../window";
  import { toast } from "../stores";
  import { play } from "../uisound";

  let { src, name = "video" }: { src: string; name?: string } = $props();

  let video: HTMLVideoElement | null = $state(null);
  let box: HTMLDivElement | null = $state(null);
  let paused = $state(true);
  let time = $state(0);
  let duration = $state(0);
  let volume = $state(1);
  let muted = $state(false);
  let rate = $state(1);
  let loop = $state(false);
  let buffered = $state<{ start: number; end: number }[]>([]);
  let vw = $state(0);
  let vh = $state(0);
  let waiting = $state(false);
  let ended = $state(false);
  let failed = $state(false);
  let started = $state(false);
  let full = $state(false);
  let pip = $state(false);
  const canPip = typeof document !== "undefined" && !!(document as any).pictureInPictureEnabled;
  // Whether it is in the corner, told by the video itself (Svelte has no attribute for these events).
  $effect(() => {
    const v = video;
    if (!v) return;
    const on = () => (pip = true);
    const off = () => (pip = false);
    v.addEventListener("enterpictureinpicture", on);
    v.addEventListener("leavepictureinpicture", off);
    return () => {
      v.removeEventListener("enterpictureinpicture", on);
      v.removeEventListener("leavepictureinpicture", off);
    };
  });

  // The volume is remembered, per viewer: a convenience, so a failure to read it is no loss.
  onMount(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("llm-video-volume") || "null");
      if (saved && typeof saved.v === "number") {
        volume = Math.max(0, Math.min(1, saved.v));
        muted = !!saved.m;
      }
    } catch { /* private window */ }
    const onFull = () => (full = document.fullscreenElement === box);
    document.addEventListener("fullscreenchange", onFull);
    return () => document.removeEventListener("fullscreenchange", onFull);
  });
  function remember() {
    try { localStorage.setItem("llm-video-volume", JSON.stringify({ v: volume, m: muted })); } catch { /* fine */ }
  }

  // ── Playing ────────────────────────────────────────────────────────────────
  /** A play or pause shown for a moment in the middle, as it happens. */
  let flash = $state<{ icon: string; n: number } | null>(null);
  function toggle() {
    if (!video || failed) return;
    if (video.paused || video.ended) {
      video.play().catch(() => {});
      flash = { icon: "play", n: (flash?.n ?? 0) + 1 };
    } else {
      video.pause();
      flash = { icon: "pause", n: (flash?.n ?? 0) + 1 };
    }
    poke();
  }
  function seekTo(t: number) {
    if (!video || !isFinite(duration) || !duration) return;
    video.currentTime = Math.max(0, Math.min(duration, t));
    ended = false;
    poke();
  }
  const skip = (by: number) => seekTo(time + by);
  function setVolume(v: number) {
    volume = Math.max(0, Math.min(1, v));
    muted = volume === 0;
    remember();
    poke();
  }
  function toggleMute() {
    if (muted && volume === 0) volume = 0.6;
    muted = !muted;
    remember();
  }
  const RATES = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
  function stepRate(by: number) {
    const i = RATES.indexOf(rate);
    rate = RATES[Math.max(0, Math.min(RATES.length - 1, (i < 0 ? 3 : i) + by))];
    poke();
  }
  async function toggleFull() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await box?.requestFullscreen();
    } catch { /* not allowed here */ }
  }
  async function togglePip() {
    try {
      if ((document as any).pictureInPictureElement) await (document as any).exitPictureInPicture();
      else await (video as any)?.requestPictureInPicture();
    } catch { /* not allowed here */ }
  }
  let saving = $state(false);
  async function save() {
    saving = true;
    menu = false;
    try {
      const where = await saveUrlAs(src, name);
      if (where) toast(`Saved ${where.split(/[\\/]/).pop()}.`, "ok");
    } catch (e: any) {
      toast(e?.message || "Could not save it.", "err");
    }
    saving = false;
  }

  // ── The controls come and go ───────────────────────────────────────────────
  let menu = $state(false);
  let dragging = $state(false);
  let awake = $state(true);
  let idle = 0;
  function poke() {
    awake = true;
    clearTimeout(idle);
    idle = window.setTimeout(() => { if (!paused && !dragging && !menu) awake = false; }, 2200);
  }
  $effect(() => () => clearTimeout(idle));
  const showControls = $derived(awake || paused || ended || failed || menu || dragging);

  // ── The seek bar ───────────────────────────────────────────────────────────
  let bar: HTMLDivElement | null = $state(null);
  let hoverAt = $state<number | null>(null);
  const fracAt = (e: PointerEvent) => {
    const r = bar!.getBoundingClientRect();
    return Math.max(0, Math.min(1, (e.clientX - r.left) / (r.width || 1)));
  };
  // Heard as it is scrubbed: taken hold of, a soft detent every twentieth of the way, and let go.
  let notch = -1;
  function barDown(e: PointerEvent) {
    if (!bar || e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    bar.setPointerCapture(e.pointerId);
    dragging = true;
    play("grab");
    notch = Math.floor(fracAt(e) * 20);
    seekTo(fracAt(e) * duration);
  }
  function barMove(e: PointerEvent) {
    if (!bar) return;
    hoverAt = fracAt(e);
    if (dragging) {
      seekTo(hoverAt * duration);
      const k = Math.floor(hoverAt * 20);
      if (k !== notch) {
        notch = k;
        play("tick", { p: hoverAt });
      }
    }
  }
  function barUp(e: PointerEvent) {
    if (!dragging) return;
    dragging = false;
    play("release");
    bar?.releasePointerCapture?.(e.pointerId);
  }
  const played = $derived(duration ? Math.min(1, time / duration) : 0);
  const loaded = $derived(duration && buffered.length ? Math.min(1, Math.max(...buffered.map((b) => b.end)) / duration) : 0);

  // ── Keys, while the player has focus ───────────────────────────────────────
  function key(e: KeyboardEvent) {
    if ((e.target as HTMLElement)?.closest?.("input")) return;
    const k = e.key;
    const done = () => { e.preventDefault(); e.stopPropagation(); poke(); };
    if (k === " " || k === "k" || k === "K") { toggle(); done(); }
    else if (k === "j" || k === "J") { skip(-10); done(); }
    else if (k === "l" || k === "L") { skip(10); done(); }
    else if (k === "ArrowLeft") { skip(-5); done(); }
    else if (k === "ArrowRight") { skip(5); done(); }
    else if (k === "ArrowUp") { setVolume(volume + 0.1); muted = false; done(); }
    else if (k === "ArrowDown") { setVolume(volume - 0.1); done(); }
    else if (k === "m" || k === "M") { toggleMute(); done(); }
    else if (k === "f" || k === "F") { toggleFull(); done(); }
    else if (k === "Home") { seekTo(0); done(); }
    else if (k === "End") { seekTo(duration); done(); }
    else if (/^[0-9]$/.test(k)) { seekTo((Number(k) / 10) * duration); done(); }
    else if (k === ">" || (k === "." && e.shiftKey)) { stepRate(1); done(); }
    else if (k === "<" || (k === "," && e.shiftKey)) { stepRate(-1); done(); }
    else if ((k === "." || k === ",") && paused) { seekTo(time + (k === "." ? 1 : -1) / 30); done(); }
    else if (k === "Escape" && menu) { menu = false; done(); }
  }

  function mmss(s: number): string {
    if (!isFinite(s) || s < 0) s = 0;
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
  }
  const ratio = $derived(vw && vh ? vw / vh : 16 / 9);
  const volIcon = $derived(muted || volume === 0 ? "speakerOff" : "speaker");
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div class="vp" class:is-full={full} class:is-idle={!showControls} class:is-portrait={ratio < 1}
     style="--ratio: {ratio}" bind:this={box} tabindex="0" role="group" aria-label="Video: {name}"
     onkeydown={key} onpointermove={poke} onpointerleave={() => { hoverAt = null; if (!paused) awake = false; }}>
  <!-- svelte-ignore a11y_media_has_caption -->
  <video bind:this={video} {src} preload="metadata" playsinline {loop}
         bind:paused bind:currentTime={time} bind:duration bind:volume bind:muted bind:playbackRate={rate}
         bind:buffered bind:videoWidth={vw} bind:videoHeight={vh}
         onplay={() => { started = true; ended = false; poke(); }} onended={() => (ended = true)}
         onwaiting={() => (waiting = true)} onplaying={() => (waiting = false)} oncanplay={() => (waiting = false)}
         onerror={() => (failed = true)}
         onclick={toggle} ondblclick={toggleFull}></video>

  <!-- The middle: the first play, buffering, a play or pause as it happens, a replay, or why it cannot. -->
  {#if failed}
    <div class="vp-middle is-failed">
      <span>Can't play this one here.</span>
      <button type="button" onclick={save} disabled={saving}><Icon name="download" size={12} />Save it</button>
    </div>
  {:else if waiting && !paused}
    <div class="vp-middle"><span class="vp-spin"></span></div>
  {:else if ended}
    <button type="button" class="vp-big" onclick={() => { seekTo(0); video?.play(); }} aria-label="Play again"><Icon name="refresh" size={22} /></button>
  {:else if paused && !started}
    <button type="button" class="vp-big" onclick={toggle} aria-label="Play"><Icon name="play" size={24} /></button>
  {:else if flash}
    {#key flash.n}<span class="vp-flash" aria-hidden="true"><Icon name={flash.icon} size={20} /></span>{/key}
  {/if}

  {#if !failed}
    <div class="vp-controls" class:is-shown={showControls}>
      <div class="vp-bar" bind:this={bar} role="slider" tabindex="-1" aria-label="Seek"
           aria-valuemin="0" aria-valuemax={Math.round(duration) || 0} aria-valuenow={Math.round(time)} aria-valuetext={mmss(time)}
           onpointerdown={barDown} onpointermove={barMove} onpointerup={barUp} onpointercancel={barUp}
           onpointerleave={() => { if (!dragging) hoverAt = null; }}>
        <span class="vp-track">
          <span class="vp-loaded" style="transform: scaleX({loaded})"></span>
          {#if hoverAt != null}<span class="vp-hover" style="transform: scaleX({hoverAt})"></span>{/if}
          <span class="vp-played" style="transform: scaleX({played})"></span>
        </span>
        <span class="vp-thumb" style="left: {played * 100}%"></span>
        {#if hoverAt != null && duration}
          <span class="vp-tip" style="left: {hoverAt * 100}%">{mmss(hoverAt * duration)}</span>
        {/if}
      </div>
      <div class="vp-row">
        <button type="button" class="vp-btn" onclick={toggle} aria-label={paused ? "Play" : "Pause"} title="{paused ? 'Play' : 'Pause'} (K)">
          <Icon name={paused ? "play" : "pause"} size={15} />
        </button>
        <span class="vp-vol">
          <button type="button" class="vp-btn" onclick={toggleMute} aria-label={muted ? "Unmute" : "Mute"} title="{muted ? 'Unmute' : 'Mute'} (M)">
            <Icon name={volIcon} size={15} />
          </button>
          <input type="range" min="0" max="1" step="0.02" value={muted ? 0 : volume} aria-label="Volume"
                 style="--v: {(muted ? 0 : volume) * 100}%"
                 oninput={(e) => { setVolume(Number((e.target as HTMLInputElement).value)); muted = volume === 0; }} />
        </span>
        <span class="vp-time">{mmss(time)} <i>/ {mmss(duration)}</i></span>
        <span class="flex-1"></span>
        {#if rate !== 1}<button type="button" class="vp-chip" onclick={() => (rate = 1)} title="Back to normal speed">{rate}×</button>{/if}
        <span class="vp-more">
          <button type="button" class="vp-btn" class:is-on={menu} onclick={() => (menu = !menu)} aria-label="More" aria-expanded={menu} title="Speed, loop and more">
            <Icon name="settings" size={14} />
          </button>
          {#if menu}
            <div class="vp-menu" role="menu">
              <div class="vp-menu-row">
                <span>Speed</span>
                <span class="vp-rates">
                  {#each RATES as r (r)}
                    <button type="button" class:is-on={rate === r} onclick={() => (rate = r)}>{r === 1 ? "1×" : String(r).replace(/^0\./, ".")}</button>
                  {/each}
                </span>
              </div>
              <button type="button" class="vp-menu-item" role="menuitemcheckbox" aria-checked={loop} onclick={() => (loop = !loop)}>
                <Icon name="refresh" size={13} />Loop<span class="vp-check" class:is-on={loop}></span>
              </button>
              {#if canPip}
                <button type="button" class="vp-menu-item" role="menuitem" onclick={() => { menu = false; togglePip(); }}>
                  <Icon name="minimize" size={13} />{pip ? "Back from the corner" : "Picture in picture"}
                </button>
              {/if}
              <button type="button" class="vp-menu-item" role="menuitem" onclick={save} disabled={saving}>
                <Icon name="download" size={13} />{saving ? "Saving" : "Save the video"}
              </button>
            </div>
          {/if}
        </span>
        <button type="button" class="vp-btn" onclick={toggleFull} aria-label={full ? "Leave full screen" : "Full screen"} title="{full ? 'Leave full screen' : 'Full screen'} (F)">
          <Icon name={full ? "collapse" : "expand"} size={14} />
        </button>
      </div>
    </div>
  {/if}
</div>

<style>
  .vp {
    position: relative;
    width: min(340px, 100%);
    height: clamp(150px, calc(min(340px, 100%) / var(--ratio)), 300px);
    /* Not clipped, so the menu can open past its top; the video and the controls round their own corners. */
    border-radius: 12px;
    background: #000;
    outline: none;
    user-select: none;
    box-shadow: 0 10px 28px -18px rgb(0 0 0 / 0.9);
  }
  .vp:focus-visible { box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-accent) 55%, transparent); }
  .vp.is-full, .vp.is-full .vp-controls { width: 100%; height: 100%; border-radius: 0; }
  .vp.is-full .vp-controls { height: auto; }
  .vp.is-idle { cursor: none; }
  .vp video { display: block; width: 100%; height: 100%; border-radius: inherit; object-fit: contain; background: #000; cursor: pointer; }
  .vp.is-idle video { cursor: none; }

  .vp-middle { position: absolute; inset: 0; display: grid; place-items: center; pointer-events: none; }
  .vp-middle.is-failed { gap: 8px; align-content: center; justify-items: center; font-size: 12px; color: rgb(255 255 255 / 0.75); pointer-events: auto; }
  .vp-middle.is-failed button { display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; border-radius: 9px; font-size: 12px; font-weight: 600; color: #fff; background: rgb(255 255 255 / 0.12); }
  .vp-spin { width: 34px; height: 34px; border-radius: 999px; border: 3px solid rgb(255 255 255 / 0.2); border-top-color: #fff; animation: vp-spin 0.8s linear infinite; }
  @keyframes vp-spin { to { transform: rotate(360deg); } }
  .vp-big {
    position: absolute;
    left: 50%;
    top: 50%;
    display: grid;
    width: 58px;
    height: 58px;
    place-items: center;
    border-radius: 999px;
    color: #fff;
    background: rgb(0 0 0 / 0.45);
    backdrop-filter: blur(8px);
    box-shadow: inset 0 0 0 1.5px rgb(255 255 255 / 0.25), 0 10px 30px -10px rgb(0 0 0 / 0.8);
    transform: translate(-50%, -50%);
    transition: transform 0.3s var(--jelly), background-color 0.15s var(--swift);
  }
  .vp-big:hover { background: color-mix(in srgb, var(--color-accent) 70%, rgb(0 0 0 / 0.4)); transform: translate(-50%, -50%) scale(1.08); }
  .vp-flash {
    position: absolute;
    left: 50%;
    top: 50%;
    display: grid;
    width: 52px;
    height: 52px;
    place-items: center;
    border-radius: 999px;
    color: #fff;
    background: rgb(0 0 0 / 0.45);
    pointer-events: none;
    transform: translate(-50%, -50%);
    animation: vp-flash 0.6s var(--swift) forwards;
  }
  @keyframes vp-flash { from { opacity: 1; transform: translate(-50%, -50%) scale(0.8); } to { opacity: 0; transform: translate(-50%, -50%) scale(1.35); } }

  .vp-controls {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 22px 8px 6px;
    border-radius: 0 0 12px 12px;
    background: linear-gradient(180deg, transparent, rgb(0 0 0 / 0.72));
    opacity: 0;
    transform: translateY(6px);
    transition: opacity 0.22s var(--swift), transform 0.22s var(--swift);
    pointer-events: none;
  }
  .vp-controls.is-shown { opacity: 1; transform: none; pointer-events: auto; }
  .vp-bar { position: relative; height: 14px; margin: 0 4px; cursor: pointer; touch-action: none; }
  .vp-track { position: absolute; left: 0; right: 0; top: 5px; height: 4px; overflow: hidden; border-radius: 4px; background: rgb(255 255 255 / 0.2); transition: height 0.15s var(--swift), top 0.15s var(--swift); }
  .vp-bar:hover .vp-track { top: 4px; height: 6px; }
  .vp-loaded, .vp-hover, .vp-played { position: absolute; inset: 0; transform-origin: left; }
  .vp-loaded { background: rgb(255 255 255 / 0.25); }
  .vp-hover { background: rgb(255 255 255 / 0.2); }
  .vp-played { background: var(--color-accent); }
  .vp-thumb {
    position: absolute;
    top: 7px;
    width: 12px;
    height: 12px;
    margin: -6px 0 0 -6px;
    border-radius: 999px;
    background: #fff;
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 40%, transparent);
    transform: scale(0);
    transition: transform 0.2s var(--spring);
  }
  .vp-bar:hover .vp-thumb, .vp-bar:active .vp-thumb { transform: scale(1); }
  .vp-tip {
    position: absolute;
    bottom: 16px;
    padding: 2px 6px;
    border-radius: 6px;
    font-size: 10.5px;
    font-weight: 650;
    color: #fff;
    background: rgb(0 0 0 / 0.75);
    transform: translateX(-50%);
    pointer-events: none;
    font-variant-numeric: tabular-nums;
  }
  .vp-row { display: flex; align-items: center; gap: 2px; margin-top: 2px; }
  .vp-btn {
    display: grid;
    width: 28px;
    height: 28px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 8px;
    color: rgb(255 255 255 / 0.9);
    transition: background-color 0.15s var(--swift), transform 0.25s var(--jelly);
  }
  .vp-btn:hover, .vp-btn.is-on { background: rgb(255 255 255 / 0.14); color: #fff; }
  .vp-btn:active { transform: scale(0.9); }
  .vp-time { padding: 0 4px; font-size: 11px; font-weight: 600; color: #fff; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .vp-time i { font-style: normal; color: rgb(255 255 255 / 0.6); }
  .vp-vol { display: inline-flex; align-items: center; }
  .vp-vol input {
    width: 0;
    height: 4px;
    opacity: 0;
    appearance: none;
    border-radius: 4px;
    background: linear-gradient(90deg, #fff var(--v), rgb(255 255 255 / 0.25) var(--v));
    cursor: pointer;
    transition: width 0.2s var(--swift), opacity 0.2s var(--swift), margin 0.2s var(--swift);
  }
  .vp-vol:hover input, .vp-vol:focus-within input { width: 60px; opacity: 1; margin: 0 6px 0 2px; }
  .vp-vol input::-webkit-slider-thumb { width: 10px; height: 10px; appearance: none; border-radius: 999px; background: #fff; }
  .vp-chip { padding: 2px 7px; border-radius: 7px; font-size: 10.5px; font-weight: 700; color: #111; background: #fff; }
  .vp-more { position: relative; }
  .vp-menu {
    position: absolute;
    right: -34px;
    bottom: 34px;
    z-index: 2;
    display: flex;
    width: 240px;
    flex-direction: column;
    gap: 1px;
    padding: 5px;
    border-radius: 12px;
    background: rgb(22 24 34 / 0.96);
    box-shadow: 0 16px 40px -14px rgb(0 0 0 / 0.9), inset 0 0 0 1px rgb(255 255 255 / 0.08);
    animation: vp-menu 0.18s var(--swift) both;
  }
  @keyframes vp-menu { from { opacity: 0; transform: translateY(6px) scale(0.97); } }
  .vp-menu-row { display: flex; flex-direction: column; gap: 4px; padding: 4px 5px 6px; font-size: 10.5px; color: rgb(255 255 255 / 0.6); }
  .vp-rates { display: flex; gap: 2px; }
  .vp-rates button { flex: 1; padding: 2px 0; border-radius: 6px; font-size: 10.5px; font-weight: 600; color: rgb(255 255 255 / 0.85); background: rgb(255 255 255 / 0.07); }
  .vp-rates button:hover { background: rgb(255 255 255 / 0.14); }
  .vp-rates button.is-on { color: var(--color-bg); background: var(--color-accent); }
  .vp-menu-item { display: flex; align-items: center; gap: 8px; padding: 5px 8px; border-radius: 8px; font-size: 12px; color: #fff; text-align: left; }
  .vp-menu-item:hover { background: rgb(255 255 255 / 0.1); }
  .vp-check { width: 26px; height: 15px; margin-left: auto; border-radius: 999px; background: rgb(255 255 255 / 0.18); position: relative; transition: background-color 0.2s var(--swift); }
  .vp-check::after { content: ""; position: absolute; left: 2px; top: 2px; width: 11px; height: 11px; border-radius: 999px; background: #fff; transition: transform 0.25s var(--spring); }
  .vp-check.is-on { background: var(--color-accent); }
  .vp-check.is-on::after { transform: translateX(11px); }

  :global(:root[data-motion="off"]) .vp-flash,
  :global(:root[data-motion="off"]) .vp-menu { animation: none; }
  :global(:root[data-motion="off"]) .vp-flash { display: none; }
</style>
