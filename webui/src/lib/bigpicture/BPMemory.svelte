<script lang="ts">
  /**
   * The idle scene about one person: who they are to you, in a few lines.
   *
   * Their face and name, what you two talk about (the Memory summary, drawn as
   * a headline and short labelled points), and how the conversation last went,
   * as bubbles. The summary is the stored one: BigPicture.svelte reads those
   * first and has a few new ones written in the background. The messages are
   * the ones it was written from, or this visit's own when the conversation has
   * been read since.
   */
  import Avatar from "../components/Avatar.svelte";
  import MessageBody from "../components/MessageBody.svelte";
  import SummaryText from "../components/SummaryText.svelte";
  import { fitText } from "./fit";
  import { popIn } from "./motion";
  import type { MemoryPerson } from "./types";

  let { person, now = 0, hideText = false }: { person: MemoryPerson; now?: number; hideText?: boolean } = $props();

  function ago(ts?: number): string {
    if (!ts) return "";
    const s = Math.max(0, now - ts);
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 86400) return `${Math.round(s / 3600)} h ago`;
    return `${Math.round(s / 86400)} d ago`;
  }
</script>

<div class="bpm">
  <div class="bpm-kicker" in:popIn|global={{ delay: 40, from: 0.96 }}>Memory · what you two talk about</div>
  <div class="bpm-grid">
    <div class="bpm-main">
      <div class="bpm-who" in:popIn|global={{ delay: 110 }}>
        <span class="halo is-live"><Avatar src={person.avatar} name={person.name} size={92} zoom={false} /></span>
        <div class="bpm-id">
          <div class="bpm-name" use:fitText={{ min: 24, text: person.name }}>{person.name}</div>
          <div class="bpm-meta">
            {person.messages} message{person.messages === 1 ? "" : "s"} from them{person.last_ts ? ` · the last one ${ago(person.last_ts)}` : ""}
          </div>
        </div>
      </div>
      <div class="bpm-card" class:is-hidden={hideText} in:popIn|global={{ delay: 220, from: 0.94 }}>
        <SummaryText text={person.summary} size="lg" reveal />
      </div>
      {#if person.generated_at}
        <div class="bpm-foot">
          Written {ago(person.generated_at)}{person.count ? `, from the last ${person.count} messages` : ""}
        </div>
      {/if}
    </div>

    {#if person.recent.length}
      <div class="bpm-msgs" class:is-hidden={hideText}>
        <div class="bpm-label" in:popIn|global={{ delay: 420, from: 0.96 }}>How it last went</div>
        {#each person.recent as m, i (i)}
          <div class="bpm-msg" class:is-mine={m.mine} in:popIn|global={{ delay: 520 + i * 170 }}>
            {#if !m.mine}
              <span class="bpm-msg-av"><Avatar src={person.avatar} name={person.name} size={30} zoom={false} /></span>
            {/if}
            <div class="bpm-bubble"><MessageBody text={m.text} clamp={3} /></div>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>

<style>
  .bpm {
    --sm-ink: #fff;
    --sm-muted: rgb(255 255 255 / 0.8);
    --sm-accent: color-mix(in srgb, var(--color-accent) 70%, white);
    display: flex;
    height: 100%;
    min-width: 0;
    flex-direction: column;
    /* safe: a long summary on a short screen starts at the top rather than losing the name off it */
    justify-content: safe center;
    gap: 18px;
    padding: 10px 6px;
    container-type: inline-size;
  }
  .bpm-kicker { font-size: 12px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--bp-faint); }
  /* Side by side when the stage is wide (the queue folded away), one above the other when it is not. */
  .bpm-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 22px; align-items: start; }
  @container (min-width: 760px) {
    .bpm-grid { grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr); gap: clamp(24px, 3vw, 48px); align-items: center; }
  }
  .bpm-main { display: flex; min-width: 0; flex-direction: column; gap: 16px; }
  .bpm-who { display: flex; min-width: 0; align-items: center; gap: 20px; }
  .bpm-id { display: flex; min-width: 0; flex: 1 1 0; flex-direction: column; gap: 2px; }
  .bpm-name {
    overflow: hidden;
    font-size: clamp(34px, 3.6vw, 58px);
    font-weight: 800;
    line-height: 1.16;
    letter-spacing: -0.035em;
    color: #fff;
    text-overflow: ellipsis;
    white-space: nowrap;
    /* Room above and below for an emoji, which stands taller than the letters:
       at a line height of 1 the box it is cut to sliced them flat. The margin
       takes the room back, so the layout is where it was. */
    padding-block: 0.1em;
    margin-block: -0.1em;
  }
  .bpm-meta { font-size: 15px; color: var(--bp-muted); }
  .bpm-card {
    padding: clamp(18px, 2vw, 28px);
    border-radius: 26px;
    background: rgb(255 255 255 / 0.06);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08), 0 30px 80px -40px rgb(0 0 0 / 0.8);
    backdrop-filter: blur(22px);
  }
  .bpm-card.is-hidden :global(.sm-text),
  .bpm-card.is-hidden :global(.sm-lead),
  .bpm-card.is-hidden :global(.sm-para) { filter: blur(9px); }
  .bpm-foot { font-size: 12px; color: var(--bp-faint); }

  .bpm-msgs { display: flex; min-width: 0; flex-direction: column; gap: 10px; }
  .bpm-label { margin-bottom: 2px; font-size: 11.5px; font-weight: 700; letter-spacing: 0.2em; text-transform: uppercase; color: var(--bp-faint); }
  .bpm-msg { display: flex; min-width: 0; max-width: 88%; align-items: flex-end; gap: 9px; }
  .bpm-msg.is-mine { align-self: flex-end; flex-direction: row-reverse; }
  .bpm-bubble {
    min-width: 0;
    padding: 11px 16px;
    overflow-wrap: anywhere;
    border-radius: 20px 20px 20px 6px;
    font-size: clamp(15px, 1.2vw, 18px);
    line-height: 1.4;
    color: #fff;
    /* Flat fill rather than a backdrop blur, for the reason in BPStage. */
    background: rgb(255 255 255 / 0.1);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.09);
  }
  .bpm-msg.is-mine .bpm-bubble {
    border-radius: 20px 20px 6px 20px;
    background: color-mix(in srgb, var(--color-accent) 42%, rgb(0 0 0 / 0.2));
    box-shadow: 0 10px 34px -12px color-mix(in srgb, var(--color-accent) 70%, transparent);
  }
  .bpm-msgs.is-hidden .bpm-bubble :global(.mb-text) { filter: blur(9px); }
  @media (max-width: 720px) {
    .bpm-who { gap: 14px; }
    .bpm-who :global(.halo) { transform: scale(0.8); transform-origin: left center; }
  }
  /* A message that is only a picture is shown as the picture: no bubble
     behind it, no padding around it. A background plus the image's own
     rounded corners read as a box drawn around every photo. */
  .bpm-bubble:has(:global(.mb-media)):not(:has(:global(.mb-text))):not(:has(:global(.mb-chip))) {
    padding: 0;
    background: none;
    box-shadow: none;
    backdrop-filter: none;
  }
</style>
