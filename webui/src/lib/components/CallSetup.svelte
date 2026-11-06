<script lang="ts">
  /**
   * Calls, in Settings: what does the work on a call, the voice it talks in, and Try a call.
   *
   * The choices go through Settings' own Save, like the rows under it (`get` and `set` are its). Try a call uses
   * what is on screen, saved or not: the whole call brain (app/voice/session.py) with your microphone as the other
   * person, over /api/calls/try. Nothing reaches any platform and nothing is remembered.
   *
   * On its own brain each leg - what hears them, what thinks of the answer, what says it - is what voice messages and
   * replies use (Settings > Models) unless the call picks its own, from any provider that can (app/voice/speech.py),
   * with the same picker the Models tab has. A pick is tried first and the rest after it. This computer's own voice
   * (app/voice/onboard.py) is fetched from the card here, since llama.cpp neither hears nor speaks.
   */
  import { onDestroy, onMount } from "svelte";
  import { api } from "../api";
  import { play } from "../uisound";
  import { settingsSection, toast } from "../stores";
  import { loadModels, loadProviders, providerById, providersLoaded, shortModel, type Entry } from "../providers";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import ModelChooser from "./ModelChooser.svelte";
  import NotHere from "./NotHere.svelte";
  import ProviderTile from "./ProviderTile.svelte";
  import Segmented from "./Segmented.svelte";

  let { scope = "", get, set }: {
    scope?: string;
    get: (key: string) => any;
    set: (key: string, value: any) => void;
  } = $props();

  type Voice = { id: string; name: string; about: string };
  type LegKey = "hear" | "think" | "speak";
  type Leg = { provider: string; name: string; model: string; voice?: string; local: boolean; builtin?: boolean; own?: boolean };
  type LocalModel = { id: string; job: string; name: string; about: string; mb: number; ready: boolean };
  type Local = {
    supported: boolean;
    engine: boolean;
    models: LocalModel[];
    job: { model: string; state: string; what: string; done: number; total: number; error: string };
  };
  type Catalogue = {
    realtime: Record<string, { voices: Voice[]; has_key: boolean }>;
    legs: Record<LegKey, Leg> & { all_local: boolean };
    defaults: Record<LegKey, Leg> & { all_local: boolean };
    local: Local;
  };

  let cat = $state<Catalogue | null>(null);
  let local = $state<Local | null>(null);
  $effect(() => {
    const persona = scope;
    api.callVoices(persona).then((c: Catalogue) => {
      cat = c;
      local = c.local ?? null;
      if (fetching()) watchLocal();
    }).catch(() => (cat = null));
  });
  onMount(() => {
    // The pickers list what Settings · Models knows of: loaded here too, for someone who opens Calls first.
    if (!$providersLoaded) loadProviders().catch(() => {});
  });

  const engine = $derived((get("bot.calls.engine") ?? "realtime") as string);
  const provider = $derived((get("bot.calls.realtime_provider") ?? "gemini") as string);
  const rvoice = $derived((get("bot.calls.realtime_voice") ?? "Kore") as string);
  const speaker = $derived((get("bot.calls.speaker") ?? "same") as string);
  const ovoice = $derived((get("bot.calls.voice") ?? "") as string);

  const hasKey = $derived(!!cat?.realtime?.[provider]?.has_key);
  const REALTIME_NAMES: Record<string, string> = { gemini: "Gemini", openai: "OpenAI", xai: "xAI" };
  const providerName = $derived(REALTIME_NAMES[provider] ?? provider);

  /** The three legs of a turn, in the order they happen, with what each goes back to when nothing is picked. */
  const LEGS = [
    { key: "hear", title: "Hears", need: "stt", same: "Same as voice messages" },
    { key: "think", title: "Thinks", need: "chat", same: "Same as replies" },
    { key: "speak", title: "Speaks", need: "tts", same: "Same as voice messages" },
  ] as const;

  /** A call keeps its pick as "provider:model". */
  function parse(raw: unknown): Entry | null {
    const s = String(raw ?? "").trim();
    const at = s.indexOf(":");
    return at > 0 && at < s.length - 1 ? { provider: s.slice(0, at), model: s.slice(at + 1) } : null;
  }
  const nameOf = (pid: string) => providerById(pid)?.name ?? (pid === "local" ? "This computer" : pid);
  /** `author/model-name` is too long for a card and the author is already named beside it. */
  const modelName = (m: string) => shortModel((m || "").replace(/^builtin:/, ""));

  /** What each leg is, from what is on screen: the call's own pick, or what it goes back to without one. */
  const legs = $derived.by(() => {
    if (!cat?.defaults) return null;
    const out = {} as Record<LegKey, Leg>;
    for (const l of LEGS) {
      const pick = parse(get(`bot.calls.${l.key}`));
      out[l.key] = pick
        ? { provider: pick.provider, name: nameOf(pick.provider), model: pick.model, local: pick.provider === "local",
            builtin: pick.model.startsWith("builtin:"), own: true }
        : { ...cat.defaults[l.key], own: false };
    }
    // ElevenLabs, picked before a call could have any speaker of its own.
    if (!parse(get("bot.calls.speak")) && speaker === "elevenlabs") {
      out.speak = { provider: "elevenlabs", name: "ElevenLabs", model: "", local: false, own: true };
    }
    return { ...out, all_local: LEGS.every((l) => out[l.key].local) };
  });

  // ── Picking a leg ──────────────────────────────────────────────────────────
  let chooserOpen = $state(false);
  let chooserLeg = $state<(typeof LEGS)[number] | null>(null);
  let chooserAnchor = $state<HTMLElement | null>(null);

  function choose(l: (typeof LEGS)[number], e: MouseEvent) {
    play("open");
    chooserLeg = l;
    chooserAnchor = e.currentTarget as HTMLElement;
    chooserOpen = true;
  }

  function picked(e: Entry) {
    if (!chooserLeg) return;
    pick(chooserLeg.key, `${e.provider}:${e.model}`);
  }

  function pick(key: LegKey, value: string) {
    set(`bot.calls.${key}`, value);
    if (key === "speak") {
      // A voice is a speaker's own: the one picked for another would not fit this one.
      set("bot.calls.speaker", "same");
      set("bot.calls.voice", "");
    }
  }

  function unpick(key: LegKey) {
    play("select");
    pick(key, "");
  }

  /**
   * Whether this computer's server is actually answering, when a leg runs on it.
   *
   * A job set to this computer falls back to Groq on its own when the server is down, quietly and by design -
   * better a call that happens than one that does not. Quiet would read as proof the call is local when it is not.
   * This computer's own voice needs no server, so it does not count.
   */
  let localUp = $state<boolean | null>(null);
  $effect(() => {
    const anyServer = !!legs && LEGS.some((l) => legs[l.key].local && !legs[l.key].builtin);
    if (!anyServer) {
      localUp = null;
      return;
    }
    api.localStatus().then((s: any) => (localUp = !!s?.reachable)).catch(() => (localUp = null));
  });

  function goto(path: string) {
    play("select");
    settingsSection.set(path);
  }

  // ── Its voice ───────────────────────────────────────────────────────────────
  /** The speaker's own voices: a list, fetched from its provider, or typed when they cannot be listed. */
  let speakerVoices = $state<{ voices: Voice[]; typed: boolean; error: string } | null>(null);
  const speakFor = $derived(legs ? `${legs.speak.provider}|${legs.speak.model}` : "");
  $effect(() => {
    const wanted = speakFor;
    if (!wanted || engine !== "own") return;
    const [pid, model] = wanted.split("|");
    speakerVoices = null;
    api.callSpeakerVoices(pid, model, scope)
      .then((r: any) => { if (speakFor === wanted) speakerVoices = r; })
      .catch((e: any) => { if (speakFor === wanted) speakerVoices = { voices: [], typed: true, error: e?.message || "" }; });
  });

  /** The voices on offer for what is picked, and which one is chosen. */
  const voices = $derived(engine === "realtime" ? cat?.realtime[provider]?.voices ?? [] : speakerVoices?.voices ?? []);
  /** With none picked, a speaker of its own speaks in the first of its voices (app/voice/speech.py puts it there). */
  const chosen = $derived(engine === "realtime" ? rvoice
    : ovoice || legs?.speak.voice || (legs?.speak.own ? speakerVoices?.voices[0]?.id ?? "" : ""));
  const typed = $derived(engine === "own" && !!speakerVoices?.typed);

  function choiceOf(v: Voice) {
    play("select");
    set(engine === "realtime" ? "bot.calls.realtime_voice" : "bot.calls.voice", v.id);
  }

  // ── Hear it ─────────────────────────────────────────────────────────────────
  let hearing = $state(false);
  let sample: HTMLAudioElement | null = null;
  async function hear() {
    if (hearing) return;
    hearing = true;
    try {
      const own = engine === "own" && !!legs?.speak.own;
      const blob = await api.callPreview({
        engine, provider: engine === "realtime" ? provider : own ? legs!.speak.provider : "same",
        model: own ? legs!.speak.model : "", voice: chosen, persona: scope,
      });
      sample?.pause();
      sample = new Audio(URL.createObjectURL(blob));
      await sample.play();
    } catch (e: any) {
      toast(e.message || "That voice could not be heard.", "err");
    } finally {
      hearing = false;
    }
  }

  // ── How long a turn takes ──────────────────────────────────────────────────
  type Timing = { ok: boolean; ms: number; reason: string; legs: Record<string, { ms: number; reason: string; failed?: boolean }> };
  let speed = $state<Timing | null>(null);
  let timing = $state(false);
  const onScreen = () => ({
    speaker, voice: ovoice,
    hear: String(get("bot.calls.hear") ?? ""), think: String(get("bot.calls.think") ?? ""), speak: String(get("bot.calls.speak") ?? ""),
  });
  async function checkSpeed() {
    timing = true;
    try {
      speed = await api.callSpeed({ persona: scope, ...onScreen() });
      play(speed?.ok ? "ok" : "info");
    } catch (e: any) {
      toast(e.message, "err");
    } finally {
      timing = false;
    }
  }
  const secs = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`);

  // ── This computer's own voice ──────────────────────────────────────────────
  const FETCHING = ["engine", "model", "unpacking"];
  const fetching = () => !!local && FETCHING.includes(local.job.state);
  let poll: ReturnType<typeof setTimeout> | null = null;

  function watchLocal() {
    if (poll) clearTimeout(poll);
    poll = setTimeout(async () => {
      poll = null;
      try {
        local = await api.callLocal();
      } catch {
        /* asked again in a moment */
      }
      if (fetching()) watchLocal();
      else if (local?.job.state === "ready") {
        play("done");
        // So the pickers have it straight away.
        loadModels("local", true).catch(() => {});
      } else if (local?.job.state === "error") {
        play("err");
        toast(local.job.error || "It could not be fetched.", "err");
      }
    }, 700);
  }

  async function getLocal(m: LocalModel) {
    play("select");
    try {
      local = await api.callLocalGet(m.id);
      watchLocal();
    } catch (e: any) {
      toast(e.message || "It could not be fetched.", "err");
    }
  }

  function useLocal(m: LocalModel) {
    play("select");
    pick(m.job === "stt" ? "hear" : "speak", `local:${m.id}`);
  }

  async function removeLocal(m: LocalModel) {
    play("delete");
    try {
      local = await api.callLocalRemove(m.id);
      for (const key of ["hear", "speak"] as const) if (parse(get(`bot.calls.${key}`))?.model === m.id) pick(key, "");
      loadModels("local", true).catch(() => {});
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  const fetchLine = (l: Local) =>
    l.job.state === "unpacking" ? "Unpacking"
      : l.job.state === "engine" && !l.job.total ? "Getting ready"
        : l.job.total ? `${Math.round(l.job.done / 1e6)} of ${Math.round(l.job.total / 1e6)} MB` : "Starting";

  // ── Try a call ──────────────────────────────────────────────────────────────
  type Line = { who: "me" | "them" | "note"; text: string; cut?: boolean };
  let call = $state<{ state: string; lines: Line[]; engine: string } | null>(null);
  let ws: WebSocket | null = null;
  let ctx: AudioContext | null = null;
  let mic: MediaStream | null = null;
  let rate = 24000;
  let nextAt = 0;
  let sources: AudioBufferSourceNode[] = [];
  let transcript = $state<HTMLDivElement | null>(null);

  /** The microphone, brought down to 16 kHz 16-bit in the audio thread and handed over every 20 ms. */
  const WORKLET = `
    class CallMic extends AudioWorkletProcessor {
      constructor() { super(); this.step = sampleRate / 16000; this.at = 0; this.out = []; }
      process(inputs) {
        const ch = inputs[0] && inputs[0][0];
        if (!ch) return true;
        while (this.at < ch.length) {
          const i = Math.floor(this.at), f = this.at - i;
          const a = ch[i], b = i + 1 < ch.length ? ch[i + 1] : a;
          this.out.push(a + (b - a) * f);
          this.at += this.step;
        }
        this.at -= ch.length;
        if (this.out.length >= 320) {
          const pcm = new Int16Array(this.out.length);
          for (let k = 0; k < this.out.length; k++) pcm[k] = Math.max(-1, Math.min(1, this.out[k])) * 32767;
          this.port.postMessage(pcm.buffer, [pcm.buffer]);
          this.out = [];
        }
        return true;
      }
    }
    registerProcessor("call-mic", CallMic);`;

  async function startCall() {
    if (call && call.state !== "ended") return;
    // Browsers only give a page the microphone over https or on the computer's own address, so a panel opened from
    // another device has none to ask for.
    if (!navigator.mediaDevices) {
      toast("Your browser only allows the microphone on the computer running the app, or over https.", "err");
      return;
    }
    try {
      mic = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    } catch (e: any) {
      toast(e?.name === "NotAllowedError"
        ? "The microphone was blocked. Allow it when asked, or open the panel in your browser."
        : "No microphone was found.", "err");
      return;
    }
    ctx = new AudioContext();
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    await ctx.audioWorklet.addModule(url);
    const node = new AudioWorkletNode(ctx, "call-mic");
    const hush = ctx.createGain();
    hush.gain.value = 0;
    ctx.createMediaStreamSource(mic).connect(node);
    node.connect(hush).connect(ctx.destination);

    call = { state: "ringing", lines: [], engine: "" };
    ws = new WebSocket(api.callTryUrl({
      persona: scope, engine, realtime_provider: provider, realtime_voice: rvoice, ...onScreen(),
    }));
    ws.binaryType = "arraybuffer";
    node.port.onmessage = (e) => { if (ws?.readyState === WebSocket.OPEN) ws.send(e.data); };
    ws.onmessage = (e) => (typeof e.data === "string" ? onEvent(JSON.parse(e.data)) : hearChunk(e.data));
    ws.onclose = () => stopAudio();
  }

  function hearChunk(buf: ArrayBuffer) {
    if (!ctx) return;
    const pcm = new Int16Array(buf);
    const f = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) f[i] = pcm[i] / 32768;
    const b = ctx.createBuffer(1, f.length, rate);
    b.copyToChannel(f, 0);
    const s = ctx.createBufferSource();
    s.buffer = b;
    s.connect(ctx.destination);
    const at = Math.max(ctx.currentTime + 0.05, nextAt);
    s.start(at);
    nextAt = at + b.duration;
    sources.push(s);
    s.onended = () => (sources = sources.filter((x) => x !== s));
  }

  function silenceIt() {
    for (const s of sources) {
      try { s.stop(); } catch { /* already over */ }
    }
    sources = [];
    nextAt = 0;
  }

  function onEvent(ev: any) {
    if (!call) return;
    if (ev.t === "ready") {
      rate = ev.rate || 24000;
      play("on");
    } else if (ev.t === "state") {
      call.state = ev.state;
      if (ev.engine) call.engine = ev.engine;
    } else if (ev.t === "line") {
      call.lines = [...call.lines, { who: ev.who, text: ev.text }];
    } else if (ev.t === "note") {
      call.lines = [...call.lines, { who: "note", text: ev.text }];
    } else if (ev.t === "cut") {
      // Talked over: what it had left to say goes, here as on the call.
      silenceIt();
      const last = [...call.lines].reverse().find((l) => l.who === "me");
      if (last) last.cut = true;
    } else if (ev.t === "done" || ev.t === "end") {
      if (call.state !== "ended") play("off");
      call.state = "ended";
    } else if (ev.t === "error") {
      toast(ev.text, "err");
    }
    queueMicrotask(() => transcript?.scrollTo({ top: transcript.scrollHeight, behavior: "smooth" }));
  }

  function hangUp() {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ t: "hangup" }));
    else stopAudio();
  }

  function stopAudio() {
    silenceIt();
    mic?.getTracks().forEach((t) => t.stop());
    mic = null;
    ctx?.close().catch(() => {});
    ctx = null;
    ws = null;
    if (call && call.state !== "ended") call.state = "ended";
  }

  onDestroy(() => {
    try { ws?.close(); } catch { /* gone */ }
    stopAudio();
    sample?.pause();
    if (poll) clearTimeout(poll);
  });

  const STATES: Record<string, string> = {
    ringing: "Ringing", listening: "Listening", thinking: "Thinking", speaking: "Talking", ended: "Call ended",
  };
  const live = $derived(!!call && call.state !== "ended");
</script>

<div class="cl">
  <section class="cl-hero" class:is-live={live}>
    <div class="cl-hero-main">
      <span class="cl-mark" aria-hidden="true"><Icon name="phone" size={18} /></span>
      <div class="min-w-0 flex-1">
        <div class="cl-name">Try a call</div>
        <p class="cl-sub">Talk to it with your microphone, the way someone calling it would. Headphones help.</p>
      </div>
      {#if live}
        <span class="cl-state is-{call?.state}"><span class="cl-dot"></span>{STATES[call?.state ?? ""] ?? "On a call"}</span>
        <Button kind="danger" size="sm" onclick={hangUp}>Hang up</Button>
      {:else}
        <Button size="sm" onclick={startCall}>Call it</Button>
      {/if}
    </div>
    {#if call && call.lines.length}
      <div class="cl-lines" bind:this={transcript}>
        {#each call.lines as line, i (i)}
          {#if line.who === "note"}
            <p class="cl-note">{line.text}</p>
          {:else}
            <p class="cl-line is-{line.who}" class:is-cut={line.cut}>
              <span class="cl-who">{line.who === "me" ? "It" : "You"}</span>{line.text}
            </p>
          {/if}
        {/each}
      </div>
    {/if}
  </section>

  <div class="cl-block">
    <div class="cl-label">How it talks</div>
    <Segmented label="How it talks" value={engine} onchange={(id) => set("bot.calls.engine", id)} options={[
      { id: "realtime", label: "Voice model", icon: "sparkle" },
      { id: "own", label: "Its own brain", icon: "persona" },
    ]} />
    <p class="cl-hint">
      {engine === "realtime"
        ? "Hears your tone, can be talked over, answers in about half a second. Runs on their servers."
        : "Exactly how it texts, out loud. Slower, and it runs wherever you pick, this computer included."}
    </p>
  </div>

  {#if engine === "realtime"}
    <div class="cl-block">
      <div class="cl-label">Voice model</div>
      <Segmented label="Voice model" value={provider} onchange={(id) => set("bot.calls.realtime_provider", id)}
                 options={[{ id: "gemini", label: "Gemini" }, { id: "openai", label: "OpenAI" }, { id: "xai", label: "Grok" }]} />
      {#if cat && !hasKey}
        <div class="cl-warn">
          <Icon name="key" size={13} />
          <span class="min-w-0 flex-1">No {providerName} key yet, so calls use its own brain until one is added.
            {provider === "gemini" ? "Gemini's is free." : ""}</span>
          <button type="button" class="cl-btn" onclick={() => goto("groq/keys")}>Add a key</button>
        </div>
      {/if}
      <p class="cl-hint">There is no voice model for this computer. For a call that never leaves it, pick its own brain.</p>
    </div>
  {:else}
    <div class="cl-block">
      <div class="cl-label-row">
        <div class="cl-label">What does the work</div>
        <Button kind="ghost" size="sm" loading={timing} onclick={checkSpeed}>Time a turn</Button>
      </div>
      {#if legs}
        <div class="cl-legs">
          {#each LEGS as l (l.key)}
            {@const leg = legs[l.key]}
            <div class="cl-leg" class:is-local={leg.local} class:is-own={leg.own}>
              <button type="button" class="cl-leg-pick" data-sound="self" onclick={(e) => choose(l, e)}
                      aria-label="{l.title}: {leg.name}. Pick another">
                <span class="cl-leg-job">{l.title}{#if leg.own}<em>calls only</em>{/if}</span>
                <span class="cl-leg-who"><ProviderTile id={leg.provider} size={16} />{leg.name}</span>
                {#if leg.model}<span class="cl-leg-model" title={leg.model}>{modelName(leg.model)}</span>{/if}
              </button>
              {#if leg.own}
                <button type="button" class="cl-leg-x" data-sound="self" onclick={() => unpick(l.key)}
                        title={l.same} aria-label={l.same}><Icon name="close" size={11} /></button>
              {/if}
            </div>
          {/each}
        </div>
        {#if localUp === false}
          <div class="cl-warn">
            <Icon name="alert" size={13} />
            <span class="min-w-0 flex-1">This computer is not answering, so a call would go to Groq instead.</span>
            <button type="button" class="cl-btn" onclick={() => goto("groq/local")}>Start it</button>
          </div>
        {:else}
          <p class="cl-hint" class:is-good={legs.all_local}>
            {legs.all_local
              ? "All three are on this computer, so nothing said on a call leaves it."
              : "Pick any of them just for calls. The rest stay as Settings · Models has them."}
          </p>
        {/if}
      {/if}
      {#if speed}
        <!-- Beside the three it timed, not under the voices: the number is about them. -->
        <div class="cl-timing" class:is-bad={!speed.ok}>
          <div class="cl-turn">
            <span class="cl-turn-total">{secs(speed.ms)}</span>
            <span class="cl-turn-word">a turn</span>
          </div>
          <div class="cl-turn-legs">
            {#each LEGS as l (l.key)}
              {@const leg = speed.legs?.[l.key]}
              <span class="cl-turn-leg">
                <span class="cl-turn-job">{l.title}</span>
                <span class="cl-turn-ms">{leg?.failed ? "failed" : secs(leg?.ms ?? 0)}</span>
              </span>
            {/each}
          </div>
        </div>
        {#if speed.reason}<p class="cl-hint" class:is-bad={!speed.ok}>{speed.reason}</p>{/if}
      {/if}
    </div>

    {#if local}
      <!-- This computer's own voice: llama.cpp neither hears nor speaks, so without this a call on This computer
           still sent its audio out. Fetched once, then picked like any other. -->
      <div class="cl-block">
        <div class="cl-label">Voice on this computer</div>
        {#if !local.supported}
          <NotHere feature="local_voice" variant="line" />
        {:else}
          <p class="cl-hint">Hears and speaks with no server and no key. Nothing said leaves this computer.</p>
          <div class="cl-local">
            {#each local.models as m (m.id)}
              {@const inUse = (m.job === "stt" ? legs?.hear : legs?.speak)?.model === m.id}
              {@const mine = local.job.model === m.id && fetching()}
              <div class="cl-local-row">
                <span class="cl-local-job">{m.job === "stt" ? "Hears" : "Speaks"}</span>
                <span class="cl-local-name">{m.name}<small>{m.about}</small></span>
                {#if mine}
                  <span class="cl-local-bar" aria-hidden="true">
                    <i style="width: {local.job.total ? Math.min(100, (local.job.done / local.job.total) * 100) : 4}%"></i>
                  </span>
                  <span class="cl-local-what">{fetchLine(local)}</span>
                {:else if m.ready}
                  {#if inUse}
                    <span class="cl-local-on"><Icon name="check" size={12} />In use</span>
                  {:else}
                    <button type="button" class="cl-btn" data-sound="self" onclick={() => useLocal(m)}>Use it</button>
                  {/if}
                  <button type="button" class="cl-local-x" data-sound="self" onclick={() => removeLocal(m)}
                          title="Remove it" aria-label="Remove {m.name}"><Icon name="trash" size={12} /></button>
                {:else}
                  <button type="button" class="cl-btn" data-sound="self" disabled={fetching()} onclick={() => getLocal(m)}>
                    <Icon name="download" size={12} />Get it · {m.mb} MB
                  </button>
                {/if}
              </div>
            {/each}
          </div>
          {#if local.job.state === "error"}<p class="cl-hint is-bad">{local.job.error}</p>{/if}
        {/if}
      </div>
    {/if}
  {/if}

  <div class="cl-block">
    <div class="cl-label-row">
      <div class="cl-label">Its voice</div>
      <Button kind="ghost" size="sm" loading={hearing} onclick={hear}>Hear it</Button>
    </div>
    {#if typed}
      <input class="field w-full" type="text" placeholder="The voice's name on {legs?.speak.name ?? 'it'}"
             value={ovoice} spellcheck="false" oninput={(e) => set("bot.calls.voice", (e.target as HTMLInputElement).value)} />
      {#if speakerVoices?.error}<p class="cl-hint is-bad">{speakerVoices.error}</p>{/if}
    {:else if voices.length}
      <div class="cl-voices" data-sound="self">
        {#each voices as v (v.id)}
          <button type="button" class="cl-voice" class:is-on={v.id === chosen} aria-pressed={v.id === chosen}
                  onclick={() => choiceOf(v)}>
            <span class="cl-voice-name">{v.name}</span>
            {#if v.about}<span class="cl-voice-about">{v.about}</span>{/if}
          </button>
        {/each}
      </div>
    {:else if cat && (engine === "realtime" || speakerVoices)}
      <p class="cl-hint">No voices to pick from here yet.</p>
    {/if}
  </div>
</div>

{#if chooserLeg}
  <ModelChooser bind:open={chooserOpen} anchor={chooserAnchor} need={chooserLeg.need}
                title="{chooserLeg.title} on a call" current={legs ? { provider: legs[chooserLeg.key].provider, model: legs[chooserLeg.key].model } : null}
                onpick={picked} />
{/if}

<style>
  .cl { display: flex; flex-direction: column; gap: 18px; }
  .cl-hero {
    --tone: var(--color-accent);
    padding: 16px;
    border-radius: 18px;
    background:
      radial-gradient(120% 150% at 0% 0%, color-mix(in srgb, var(--tone) 12%, transparent), transparent 58%),
      color-mix(in srgb, var(--color-accent) 4%, transparent);
    transition: background-color 0.3s var(--swift);
  }
  .cl-hero.is-live { --tone: var(--color-good); }
  .cl-hero-main { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .cl-mark {
    display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0;
    width: 36px; height: 36px; border-radius: 12px; color: var(--tone);
    background: color-mix(in srgb, var(--tone) 16%, transparent);
  }
  .cl-name { font-size: 15px; font-weight: 650; letter-spacing: -0.01em; color: var(--color-ink); }
  .cl-sub { margin-top: 1px; font-size: 12px; line-height: 1.45; color: var(--color-muted); }
  .cl-state {
    display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--color-ink);
  }
  .cl-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--color-good); }
  .cl-state.is-speaking .cl-dot { animation: cl-pulse 1.1s ease-in-out infinite; }
  .cl-state.is-thinking .cl-dot { background: var(--color-warn); }
  @keyframes cl-pulse { 50% { transform: scale(1.45); opacity: 0.55; } }
  :global(:root[data-motion="off"]) .cl-state.is-speaking .cl-dot { animation: none; }
  .cl-lines {
    display: flex; flex-direction: column; gap: 6px; max-height: 220px; overflow-y: auto; margin-top: 14px;
    padding-top: 12px; border-top: 1px solid color-mix(in srgb, var(--color-edge) 60%, transparent);
  }
  .cl-line { font-size: 13px; line-height: 1.45; color: var(--color-ink); }
  .cl-line.is-them { color: var(--color-muted); }
  .cl-line.is-cut::after { content: " \2014"; color: var(--color-faint); }
  .cl-who { display: inline-block; min-width: 30px; margin-right: 6px; font-size: 11px; font-weight: 600;
            color: var(--color-faint); }
  .cl-note { font-size: 11.5px; color: var(--color-faint); }
  .cl-block { display: flex; flex-direction: column; gap: 8px; }
  .cl-label { font-size: 12px; font-weight: 600; color: var(--color-muted); }
  .cl-label-row { display: flex; align-items: center; gap: 8px; }
  .cl-label-row .cl-label { flex: 1; }
  .cl-hint { font-size: 11.5px; line-height: 1.45; color: var(--color-faint); }
  .cl-hint.is-bad { color: var(--color-warn); }
  .cl-hint.is-good { color: var(--color-good); }
  .cl-warn {
    display: flex; align-items: center; gap: 8px; padding: 9px 11px; border-radius: 12px; font-size: 12px;
    color: var(--color-ink); background: color-mix(in srgb, var(--color-warn) 10%, transparent);
  }
  .cl-btn {
    display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; border-radius: 9px; font-size: 12px;
    font-weight: 600; white-space: nowrap; color: var(--color-ink);
  }
  .cl-btn:disabled { opacity: 0.5; cursor: default; }

  /* Hears, thinks, speaks: what a turn actually goes through, in the order it happens. Each one is a way to pick. */
  .cl-legs { display: grid; grid-template-columns: repeat(auto-fit, minmax(132px, 1fr)); gap: 6px; }
  .cl-leg { position: relative; min-width: 0; border-radius: 12px; }
  .cl-leg.is-local { background: color-mix(in srgb, var(--color-good) 11%, transparent); }
  .cl-leg-pick {
    display: flex; flex-direction: column; align-items: flex-start; gap: 1px; width: 100%; min-width: 0;
    padding: 9px 11px; border-radius: 12px; text-align: left; color: var(--color-ink);
  }
  .cl-leg-job { display: inline-flex; align-items: center; gap: 6px; font-size: 10.5px; font-weight: 650;
                letter-spacing: 0.04em; text-transform: uppercase; color: var(--color-faint); }
  .cl-leg-job em { font-style: normal; font-weight: 600; letter-spacing: 0; text-transform: none; color: var(--color-accent); }
  .cl-leg.is-local .cl-leg-job { color: color-mix(in srgb, var(--color-good) 80%, var(--color-ink)); }
  .cl-leg-who { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600; color: var(--color-ink); }
  .cl-leg-model, .cl-voice-about {
    font-size: 11px; color: var(--color-faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    max-width: 100%;
  }
  .cl-leg-x {
    position: absolute; top: 6px; right: 6px; display: grid; place-items: center; width: 20px; height: 20px;
    border-radius: 999px; color: var(--color-faint); transition: color 0.15s ease, background-color 0.15s ease;
  }
  .cl-leg-x:hover { color: var(--color-ink); background: color-mix(in srgb, var(--color-ink) 8%, transparent); }

  .cl-voices { display: grid; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); gap: 6px; }
  .cl-voice {
    display: flex; flex-direction: column; align-items: flex-start; gap: 1px; min-width: 0; padding: 8px 10px;
    border-radius: 11px; text-align: left; color: var(--color-ink);
  }
  .cl-voice.is-on { background: color-mix(in srgb, var(--color-accent) 16%, transparent); }
  .cl-voice.is-on .cl-voice-about { color: color-mix(in srgb, var(--color-ink) 55%, var(--color-accent)); }
  .cl-voice-name { font-size: 12.5px; font-weight: 600; }

  /* This computer's own voice: one row a model, what it does, and getting it or using it. */
  .cl-local { display: flex; flex-direction: column; gap: 4px; }
  .cl-local-row {
    display: flex; align-items: center; gap: 10px; min-height: 44px; padding: 6px 8px 6px 12px; border-radius: 12px;
    background: color-mix(in srgb, var(--color-ink) 4%, transparent);
  }
  .cl-local-job { width: 52px; flex-shrink: 0; font-size: 10.5px; font-weight: 650; letter-spacing: 0.04em;
                  text-transform: uppercase; color: var(--color-faint); }
  .cl-local-name { display: flex; min-width: 0; flex: 1; flex-direction: column; font-size: 12.5px; font-weight: 600;
                   color: var(--color-ink); }
  .cl-local-name small { overflow: hidden; font-size: 11px; font-weight: 400; text-overflow: ellipsis; white-space: nowrap;
                         color: var(--color-faint); }
  .cl-local-bar { width: 90px; height: 5px; overflow: hidden; flex-shrink: 0; border-radius: 999px;
                  background: rgb(255 255 255 / 0.07); }
  .cl-local-bar i { display: block; height: 100%; border-radius: 999px; background: var(--color-accent);
                    transition: width 0.4s var(--swift); }
  .cl-local-what { min-width: 86px; font-size: 11px; text-align: right; color: var(--color-muted);
                   font-variant-numeric: tabular-nums; }
  .cl-local-on { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 600;
                 color: var(--color-good); }
  .cl-local-x {
    display: grid; place-items: center; width: 26px; height: 26px; flex-shrink: 0; border-radius: 8px;
    color: var(--color-faint); transition: color 0.15s ease, background-color 0.15s ease;
  }
  .cl-local-x:hover { color: var(--color-ink); background: color-mix(in srgb, var(--color-ink) 8%, transparent); }

  /* How long a turn took, leg by leg: the number that decides whether a call is worth having. */
  .cl-timing {
    display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding: 11px 13px; border-radius: 13px;
    background: color-mix(in srgb, var(--color-good) 10%, transparent);
  }
  .cl-timing.is-bad { background: color-mix(in srgb, var(--color-warn) 10%, transparent); }
  .cl-turn { display: flex; align-items: baseline; gap: 5px; }
  .cl-turn-total { font-size: 19px; font-weight: 650; letter-spacing: -0.02em; color: var(--color-ink);
                   font-variant-numeric: tabular-nums; }
  .cl-turn-word { font-size: 11.5px; color: var(--color-muted); }
  .cl-turn-legs { display: flex; gap: 14px; flex-wrap: wrap; }
  .cl-turn-leg { display: flex; flex-direction: column; gap: 0; }
  .cl-turn-job { font-size: 10.5px; font-weight: 650; letter-spacing: 0.04em; text-transform: uppercase;
                 color: var(--color-faint); }
  .cl-turn-ms { font-size: 12.5px; font-weight: 600; color: var(--color-ink); font-variant-numeric: tabular-nums; }
  :global(:root[data-motion="off"]) .cl-local-bar i { transition: none; }
</style>
