<script lang="ts">
  /**
   * Making a profile from your own chats, inside the new profile card (NewPersona.svelte). What you wrote yourself, from
   * the data export each social lets you download, read for how you text and who you are (app/utils/chatpersona.py).
   * Never the people you talk to: nothing here can pick them.
   *
   * A tile for each social with its logo; pressed, how to get its export, in a few steps. Then the files dropped in, with
   * how many of your messages each has, and then a model reads samples of them and shows what it made. Left part way, it
   * is where it was the next time.
   */
  import { onDestroy, onMount } from "svelte";
  import { fade, slide } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { api } from "../api";
  import { smoothHeight } from "../smoothheight";
  import { notHere } from "../device";
  import NotHere from "../components/NotHere.svelte";
  import { motionEnabled, toast } from "../stores";
  import { play } from "../uisound";
  import { platformOn, socialsOn } from "../socials";
  import Button from "../components/Button.svelte";
  import Icon from "../components/Icon.svelte";
  import PlatformMark from "../components/PlatformMark.svelte";
  import { ENOUGH, GUIDES } from "./exports";

  let {
    name = $bindable(""),
    color,
    color2 = "",
    oncancel,
    oncreated,
  }: {
    name?: string;
    color: string;
    color2?: string;
    oncancel: () => void;
    oncreated: (persona: any) => void;
  } = $props();

  type FileRow = { key: string; name: string; platform: string; label: string; count: number; why: string };
  type Result = { name: string; text: string; examples: string[]; settings: Record<string, any>; count: number;
                  stats: { messages: number; median_length: number; lowercase: number; with_emoji: number;
                           top_emoji: string[]; laughs: string[]; burst: number } };
  type Status = { id: string; files: FileRow[]; total: number;
                  write: { state: string; step: string; done: number; total: number; why: string };
                  result: Result | null; model: { label: string; local: boolean } };

  let st = $state<Status | null>(null);
  let guide = $state("");
  let uploads = $state<{ id: number; name: string; done: number; total: number; abort: () => void }[]>([]);
  let over = $state(false);
  let busy = $state(false);
  let showText = $state(false);
  let picker: HTMLInputElement | null = $state(null);
  let timer = 0;
  let upId = 0;

  const guides = $derived(GUIDES.filter((g) => platformOn($socialsOn, g.id)));
  const opened = $derived(guides.find((g) => g.id === guide) ?? null);
  const files = $derived(st?.files ?? []);
  const total = $derived(st?.total ?? 0);
  const result = $derived(st?.result ?? null);
  const writing = $derived(st?.write?.state === "writing");
  const failed = $derived(st?.write?.state === "failed" ? st.write.why : "");
  /** How many of your messages each social's exports have given, for its tile. */
  const counts = $derived.by(() => {
    const out: Record<string, number> = {};
    for (const f of files) if (f.platform && !f.why) out[f.platform] = (out[f.platform] ?? 0) + f.count;
    return out;
  });

  onMount(async () => {
    try {
      st = await api.fromChatsStatus();
      if (st?.result && !name) name = st.result.name;
      watch();
    } catch (e: any) {
      toast(e?.message || "Could not look at what is there", "err");
    }
  });
  onDestroy(() => clearInterval(timer));

  /** Asked again every second and a half while it is writing. The end is heard. */
  function watch() {
    clearInterval(timer);
    if (!writing) return;
    timer = window.setInterval(async () => {
      try {
        const was = st;
        const now: Status = await api.fromChatsStatus();
        if (was?.write?.state === "writing" && now.write.state === "done") {
          play("done");
          if (!name && now.result?.name) name = now.result.name;
        }
        st = now;
        if (now.write.state !== "writing") clearInterval(timer);
      } catch {
        /* the next look */
      }
    }, 1500);
  }

  function pick(id: string) {
    guide = guide === id ? "" : id;
    play(guide ? "open" : "tick");
  }

  // ── Exports ──────────────────────────────────────────────────────────────
  function addFiles(list: FileList | File[] | null | undefined) {
    for (const f of Array.from(list ?? [])) send(f);
  }

  async function send(file: File) {
    const id = ++upId;
    const job = api.fromChatsUpload(file, (done, whole) => {
      uploads = uploads.map((u) => (u.id === id ? { ...u, done, total: whole } : u));
    });
    uploads = [...uploads, { id, name: file.name, done: 0, total: file.size, abort: job.abort }];
    try {
      const r: any = await job.done;
      st = r;
      const added: FileRow[] = r.added ?? [];
      if (added.some((f) => f.count && !f.why)) play("rise");
      for (const f of added) if (f.why) toast(`${f.label}: ${f.why}`, "info");
    } catch (e: any) {
      if (e?.status !== 0) toast(e?.message || `Could not read ${file.name}`, "err");
    } finally {
      uploads = uploads.filter((u) => u.id !== id);
    }
  }

  async function removeFile(key: string) {
    play("delete");
    try {
      st = await api.fromChatsRemove(key);
    } catch (e: any) {
      toast(e?.message || "Could not take it out", "err");
    }
  }

  function held(e: DragEvent) {
    if (!e.dataTransfer?.types?.includes("Files")) return;
    e.preventDefault();
    if (!over) play("lift");
    over = true;
  }
  function dropped(e: DragEvent) {
    if (!e.dataTransfer?.types?.includes("Files")) return;
    e.preventDefault();
    e.stopPropagation();
    over = false;
    play("drop");
    addFiles(e.dataTransfer?.files);
  }

  // ── Writing it, and making it ────────────────────────────────────────────
  async function writeIt() {
    busy = true;
    try {
      st = await api.fromChatsWrite();
      watch();
    } catch (e: any) {
      toast(e?.message || "Could not start writing it", "err");
    } finally {
      busy = false;
    }
  }

  async function make() {
    busy = true;
    try {
      const r: any = await api.fromChatsCreate(name.trim(), color, color2);
      st = null;
      oncreated(r.persona);
    } catch (e: any) {
      toast(e?.message || "Could not make it", "err");
    } finally {
      busy = false;
    }
  }

  async function startOver() {
    try {
      st = await api.fromChatsReset();
      showText = false;
    } catch (e: any) {
      toast(e?.message || "Could not start over", "err");
    }
  }

  const gb = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(n / 1e6))} MB`);
  const pct = (x: number) => `${Math.round((x || 0) * 100)}%`;
  const LENGTH: Record<string, string> = { short: "Short messages", balanced: "Medium messages", chatty: "Long messages" };
  const writeLine = $derived.by(() => {
    const w = st?.write;
    if (!w) return "";
    if (w.step === "notes") return `Reading your messages, part ${Math.min(w.done + 1, w.total)} of ${w.total}`;
    if (w.step === "writing") return "Writing it";
    return "Getting your messages together";
  });
  const writeFill = $derived.by(() => {
    const w = st?.write;
    if (!w || !w.total) return 6;
    return Math.min(96, 8 + ((w.step === "writing" ? w.total : w.done) / w.total) * 80);
  });
  const moving = (ms: number) => ({ duration: $motionEnabled ? ms : 0, easing: cubicOut });
</script>

<div class="fx">
  {#if writing}
    <div class="fx-writing">
      <b>{writeLine}</b>
      <span class="fx-bar is-wide"><i style="width: {writeFill}%"></i></span>
      <small>{st?.model?.local ? "On this computer: nothing leaves it." : `Samples of your messages go to ${st?.model?.label || "the background work model"}.`}</small>
    </div>
  {:else if result}
    <p class="fx-lead">Made from {result.count} of your messages.</p>
    <div class="fx-chips">
      <span>{LENGTH[result.settings["bot.message_style.mode"]] ?? "Medium messages"}</span>
      <span>{pct(result.stats.lowercase)} lowercase</span>
      <span>{pct(result.stats.with_emoji)} with emoji {result.stats.top_emoji.slice(0, 5).join(" ")}</span>
      {#if result.stats.laughs.length}<span>Laughs: {result.stats.laughs.join(", ")}</span>{/if}
      <span>{result.stats.burst < 1.3 ? "One message at a time" : `${result.stats.burst} messages in a row`}</span>
    </div>
    {#if result.examples.length}
      <div class="fx-bubbles">
        {#each result.examples as line, i (i)}<span class="fx-bubble">{line}</span>{/each}
      </div>
    {/if}
    <pre class="fx-text" class:is-open={showText}>{result.text}</pre>
    <button type="button" class="fx-link" onclick={() => (showText = !showText)}>{showText ? "Show less" : "Show all of what it is told"}</button>
    <div class="fx-foot">
      <button type="button" class="fx-link is-first" onclick={startOver}>Start over</button>
      <Button kind="ghost" size="sm" onclick={writeIt} loading={busy}>Write it again</Button>
      <Button size="sm" onclick={make} loading={busy} disabled={!name.trim()}>Create</Button>
    </div>
  {:else}
    <p class="fx-lead">It learns how you text from what you wrote yourself, never from the people you talk to. Pick a social to see how to get its export.</p>

    <!-- Together, with none of the card's gap between: the panel's own margin folds with it, so nothing jumps. -->
    <div>
    <div class="fx-tiles" data-sound="self">
      {#each guides as g (g.id)}
        <button type="button" class="fx-tile" class:is-on={guide === g.id} aria-expanded={guide === g.id} onclick={() => pick(g.id)}>
          <PlatformMark platform={g.id} size={26} />
          <span class="fx-tile-text">
            <b>{g.name}</b>
            <small class:is-in={counts[g.id]}>{counts[g.id] ? `${counts[g.id]} of yours` : g.wait}</small>
          </span>
        </button>
      {/each}
    </div>

    <!-- Opening and closing are this {#if}'s, so the slide is on what it holds: inside the {#key} it never played. From one
         social to another it stays open, glides to the new height, and the new steps fade in. -->
    {#if opened}
      <div class="fx-guide" transition:slide={moving(280)}>
        <div class="fx-guide-box" use:smoothHeight={{ duration: 280 }}>
          <div>
            {#key opened.id}
              <div class="fx-guide-body" in:fade={moving(220)}>
                <ol>
                  {#each opened.steps as step, i (i)}<li><b>{i + 1}</b><span>{step}</span></li>{/each}
                </ol>
                {#if opened.note}<p class="fx-note">{opened.note}</p>{/if}
                {#if opened.link}
                  <a class="fx-link is-out" href={opened.link.url} target="_blank" rel="noopener noreferrer">{opened.link.text}<Icon name="external" size={10} /></a>
                {/if}
              </div>
            {/key}
          </div>
        </div>
      </div>
    {/if}
    </div>

    <NotHere feature="files_pick" variant="line" />
    <div class="fx-zone" class:hidden={!!$notHere("files_pick")} class:is-over={over} role="button" tabindex="0" data-sound="self"
         ondragenter={held} ondragover={held} ondragleave={() => (over = false)} ondrop={dropped}
         onclick={() => picker?.click()} onkeydown={(e) => (e.key === "Enter" || e.key === " ") && picker?.click()}>
      <Icon name="upload" size={17} />
      <b>Drop your exports here</b>
      <input bind:this={picker} type="file" multiple hidden accept=".zip,.json,.csv,.txt,.js"
             onchange={(e) => { addFiles(e.currentTarget.files); e.currentTarget.value = ""; }} />
    </div>

    {#each uploads as u (u.id)}
      <div class="fx-up" transition:slide={moving(200)}>
        <span class="fx-up-name">{u.name}</span>
        <span class="fx-up-size">{u.done >= u.total && u.total ? "Reading it" : `${gb(u.done)} of ${gb(u.total)}`}</span>
        <span class="fx-bar"><i style="width: {u.total ? Math.round((u.done / u.total) * 100) : 0}%"></i></span>
        <button type="button" class="fx-x" onclick={() => u.abort()} aria-label="Stop"><Icon name="close" size={11} /></button>
      </div>
    {/each}
    {#each files as f (f.key)}
      <div class="fx-file" class:is-off={!!f.why} transition:slide={moving(220)}>
        {#if f.platform}<PlatformMark platform={f.platform} size={22} />{:else}<span class="fx-file-q"><Icon name="alert" size={12} /></span>{/if}
        <span class="fx-tile-text">
          <b>{f.label}</b>
          <small>{f.why || `${f.count} of your messages`}</small>
        </span>
        <button type="button" class="fx-x" onclick={() => removeFile(f.key)} data-sound="self" aria-label="Take {f.label} out"><Icon name="close" size={11} /></button>
      </div>
    {/each}

    {#if failed}<p class="fx-bad">{failed}</p>{/if}

    <div class="fx-foot">
      <span class="fx-total">
        {#if total}{total} of your messages{#if total < ENOUGH}, {ENOUGH} at least{/if}{/if}
      </span>
      <Button kind="ghost" size="sm" onclick={oncancel}>Cancel</Button>
      <Button size="sm" onclick={writeIt} loading={busy} disabled={total < ENOUGH}>Write it</Button>
    </div>
  {/if}
</div>

<style>
  .fx { display: flex; flex-direction: column; gap: 10px; }
  .fx-lead { font-size: 12px; line-height: 1.5; color: var(--color-muted); }

  /* ── A tile for each social ── */
  .fx-tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(132px, 1fr)); gap: 6px; }
  .fx-tile {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 9px;
    padding: 7px 9px;
    border-radius: 12px;
    text-align: left;
    background: rgb(255 255 255 / 0.04);
    transition: background-color 0.15s ease;
  }
  .fx-tile:hover { background: rgb(255 255 255 / 0.07); }
  .fx-tile.is-on { background: color-mix(in srgb, var(--color-accent) 16%, transparent); }
  .fx-tile-text { display: flex; min-width: 0; flex: 1; flex-direction: column; }
  .fx-tile-text b { overflow: hidden; font-size: 12.5px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; color: var(--color-ink); }
  .fx-tile-text small { overflow: hidden; font-size: 10.5px; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; color: var(--color-faint); }
  .fx-tile-text small.is-in { color: var(--color-good); }
  .fx-file .fx-tile-text small { white-space: normal; }

  /* ── How to get one ── */
  .fx-guide { margin-top: 6px; padding: 11px 13px; border-radius: 13px; background: color-mix(in srgb, var(--color-accent) 7%, rgb(255 255 255 / 0.02)); }
  .fx-guide-box { overflow: hidden; }
  .fx-guide-body { display: flex; flex-direction: column; gap: 7px; }
  .fx-guide ol { display: flex; flex-direction: column; gap: 6px; }
  .fx-guide li { display: flex; gap: 9px; font-size: 12.5px; line-height: 1.4; color: var(--color-ink); }
  .fx-guide li b {
    display: grid;
    width: 18px;
    height: 18px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 650;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 15%, transparent);
  }
  .fx-note { font-size: 11.5px; line-height: 1.45; color: var(--color-muted); }
  .fx-link { align-self: flex-start; font-size: 12px; color: var(--color-muted); }
  .fx-link:hover { color: var(--color-ink); }
  .fx-link.is-out { display: inline-flex; align-items: center; gap: 4px; color: var(--color-accent); }
  .fx-link.is-out:hover { text-decoration: underline; }
  .fx-link.is-first { margin-right: auto; align-self: center; }

  /* ── Dropping them in ── */
  .fx-zone {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 13px;
    border-radius: 13px;
    cursor: pointer;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.03);
    transition: background-color 0.15s ease, color 0.15s ease;
  }
  .fx-zone:hover, .fx-zone.is-over { color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 11%, transparent); }
  .fx-zone b { font-size: 12.5px; font-weight: 600; color: var(--color-ink); }
  .fx-file { display: flex; align-items: center; gap: 10px; padding: 6px 9px; border-radius: 11px; background: rgb(255 255 255 / 0.035); }
  .fx-file.is-off small { color: var(--color-warn); }
  .fx-file-q { display: grid; width: 22px; height: 22px; flex-shrink: 0; place-items: center; border-radius: 7px; color: var(--color-warn);
               background: color-mix(in srgb, var(--color-warn) 14%, transparent); }
  .fx-up { display: flex; align-items: center; gap: 10px; padding: 4px 9px; font-size: 12px; color: var(--color-muted); }
  .fx-up-name { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--color-ink); }
  .fx-up-size { flex-shrink: 0; font-variant-numeric: tabular-nums; }
  .fx-bar { position: relative; width: 110px; height: 5px; flex-shrink: 0; overflow: hidden; border-radius: 999px; background: rgb(255 255 255 / 0.08); }
  .fx-bar.is-wide { width: min(320px, 80%); }
  .fx-bar i { position: absolute; inset: 0 auto 0 0; border-radius: inherit; background: var(--color-accent); transition: width 0.4s var(--swift); }
  .fx-x { display: grid; width: 24px; height: 24px; flex-shrink: 0; place-items: center; border-radius: 8px; color: var(--color-faint);
          transition: background-color 0.15s ease, color 0.15s ease; }
  .fx-x:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
  .fx-bad { font-size: 12px; line-height: 1.45; color: var(--color-warn); }
  .fx-foot { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px; padding-top: 2px; }
  .fx-total { margin-right: auto; font-size: 12px; color: var(--color-muted); }

  /* ── Writing it, and what it wrote ── */
  .fx-writing { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 28px 10px; text-align: center; }
  .fx-writing b { font-size: 13.5px; font-weight: 600; color: var(--color-ink); }
  .fx-writing small { max-width: 420px; font-size: 12px; line-height: 1.5; color: var(--color-muted); }
  .fx-chips { display: flex; flex-wrap: wrap; gap: 5px; }
  .fx-chips span { padding: 3px 9px; border-radius: 999px; font-size: 11.5px; color: var(--color-ink); background: rgb(255 255 255 / 0.05); }
  .fx-bubbles { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
  .fx-bubble { max-width: 85%; padding: 6px 11px; border-radius: 15px 15px 4px 15px; font-size: 12.5px; color: var(--color-bg); background: var(--color-accent); }
  .fx-text {
    max-height: 7em;
    overflow: hidden;
    padding: 10px 12px;
    border-radius: 12px;
    font-family: ui-monospace, monospace;
    font-size: 11px;
    line-height: 1.55;
    white-space: pre-wrap;
    color: var(--color-muted);
    background: rgb(0 0 0 / 0.22);
  }
  .fx-text.is-open { max-height: 44vh; overflow-y: auto; }
</style>
