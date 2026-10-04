<script lang="ts">
  /**
   * A voice message or audio file, played in place.
   *
   * The browser's own <audio controls> is a bright white bar in a dark app, and
   * looks nothing like a voice message. This is the same element underneath,
   * drawn as one: a play button, how far along, and how long.
   */
  import Icon from "./Icon.svelte";

  let { src, name = "" }: { src: string; name?: string } = $props();

  let paused = $state(true);
  let time = $state(0);
  let duration = $state(0);
  let failed = $state(false);
  let audio: HTMLAudioElement | null = $state(null);

  function toggle() {
    if (!audio) return;
    if (audio.paused) audio.play().catch(() => (failed = true));
    else audio.pause();
  }

  function seek(e: MouseEvent) {
    if (!audio || !duration) return;
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    audio.currentTime = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * duration;
  }

  const mmss = (s: number) =>
    !isFinite(s) || s <= 0 ? "0:00" : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const progress = $derived(duration > 0 && isFinite(duration) ? time / duration : 0);
</script>

<div class="vn" class:is-playing={!paused} title={name}>
  <button type="button" class="vn-play" onclick={toggle} aria-label={paused ? "Play" : "Pause"} disabled={failed}>
    <Icon name={paused ? "play" : "pause"} size={13} />
  </button>
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="vn-track" role="slider" tabindex="-1" aria-label="Position" aria-valuemin={0}
       aria-valuemax={Math.round(duration) || 0} aria-valuenow={Math.round(time)} onclick={seek}>
    <span style="transform:scaleX({progress})"></span>
  </div>
  <span class="vn-time">{failed ? "can't play" : paused && !time ? mmss(duration) : mmss(time)}</span>
  <audio bind:this={audio} {src} preload="metadata" bind:paused bind:currentTime={time} bind:duration
         onerror={() => (failed = true)}></audio>
</div>

<style>
  .vn {
    display: flex;
    width: min(300px, 100%);
    align-items: center;
    gap: 10px;
    margin-top: 8px;
    padding: 6px 12px 6px 6px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--color-accent) 10%, rgb(255 255 255 / 0.03));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 18%, transparent);
  }
  .vn audio { display: none; }
  .vn-play {
    display: grid;
    width: 28px;
    height: 28px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    color: var(--color-bg);
    background: var(--color-accent);
    transition: transform 0.18s var(--spring);
  }
  .vn-play:hover:not(:disabled) { transform: scale(1.07); }
  .vn-play:active:not(:disabled) { transform: scale(0.94); }
  .vn-play:disabled { opacity: 0.4; }
  .vn-track {
    position: relative;
    height: 4px;
    flex: 1;
    overflow: hidden;
    border-radius: 999px;
    background: rgb(255 255 255 / 0.1);
    cursor: pointer;
  }
  .vn-track span {
    position: absolute;
    inset: 0;
    border-radius: 999px;
    background: var(--color-accent);
    transform-origin: left;
    transition: transform 0.25s linear;
  }
  .vn-time {
    min-width: 34px;
    flex-shrink: 0;
    font-size: 11px;
    text-align: right;
    color: var(--color-muted);
    font-variant-numeric: tabular-nums;
  }
  :global(:root[data-motion="off"]) .vn-track span { transition: none; }
</style>
