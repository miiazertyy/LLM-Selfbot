<script lang="ts">
  /**
   * Running models on this machine: finding the server, and getting models.
   *
   * The app does not run the model itself, it talks to something that does:
   * Ollama, LM Studio, Jan, GPT4All, KoboldCpp, llama.cpp's server, LocalAI,
   * vLLM and the rest in app/utils/localai.py, which explains why that is the
   * right shape rather than a compromise. This page hides the plumbing: it
   * looks for a server, offers what that server already has, and can fetch a
   * new model by name, HuggingFace names included.
   *
   * Laid out by what matters most, top down:
   *
   *  - the server, in a card of its own: what it is, whether it is running,
   *    where it listens, how many models and how much disk, which jobs run
   *    on it, and whatever gets it going (start it, open it, get it);
   *  - its models, with how big each is and how it is squeezed, which are in
   *    memory now, which a job uses; Ollama's can be removed, and a new one
   *    fetched by name, the download showing its speed and time left;
   *  - the settings: starting it with the app, the room for the
   *    conversation, the address and key;
   *  - every other server it works with, as small chips.
   *
   * It used to be one long column of boxes in the order they were written:
   * the list of servers, a grid of every other server, two settings, the
   * download, and the models last of all, under the address.
   *
   * Which job uses which of these models is chosen under Models, alongside
   * every other provider.
   */
  import { onMount, onDestroy, tick } from "svelte";
  import { fly, slide } from "svelte/transition";
  import { flip } from "svelte/animate";
  import { cubicOut } from "svelte/easing";
  import { api } from "../api";
  import { track, trackUntil } from "../busy";
  import { resource } from "../resource";
  import { get } from "svelte/store";
  import { health, toast } from "../stores";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import Toggle from "./Toggle.svelte";
  import Segmented from "./Segmented.svelte";
  import ProviderTile from "./ProviderTile.svelte";
  import NotHere from "./NotHere.svelte";
  import { settingsSection } from "../stores";
  import { loadModels, loadProviders, savedPlan } from "../providers";
  import { busyOn, startUsageLive, working } from "../modelusage";
  import { visiblePoll } from "../poll";
  import { play } from "../uisound";

  // The echo round the server's logo: only while it is at work on something (a
  // reply, a picture), not all the time it is running, and a moment after, so
  // a quick one is still seen.
  onMount(startUsageLive);
  let atWork = $state(false);
  let workLinger = 0;
  $effect(() => {
    if (busyOn($working, "local")) {
      clearTimeout(workLinger);
      atWork = true;
    } else if (atWork) {
      clearTimeout(workLinger);
      workLinger = window.setTimeout(() => (atWork = false), 1400);
    }
  });
  onDestroy(() => clearTimeout(workLinger));

  type Server = {
    id: string; name: string; root: string; site: string;
    can_pull: boolean; running: boolean; models: string[]; base_url: string;
    installed?: boolean; can_start?: boolean; pages?: Record<string, Page>;
    /** Answering, but wants a key the app does not have. */
    locked?: boolean;
    /** How the app brings it up: "command" starts it, "app" opens its window, "" it cannot. */
    start?: "command" | "app" | "";
    /** How to turn its API on, with commands in backticks. */
    hint?: string;
    /** Where its models come from, for one the app cannot give a model to. */
    get?: string;
  };
  type Pull = {
    active: boolean; model: string; status: string;
    percent: number; done: number; total: number; error: string;
    /** Waiting their turn behind the one downloading. */
    queue?: { model: string }[];
    /** How the one before ended: a queue moving straight on would otherwise swallow it. */
    last?: { model: string; asked: string; error: string; cancelled: boolean; at: number } | null;
  };
  type Details = { size: number; params: string; quant: string; family: string };

  type Page = { url: string; site: string };
  /** The mark beside a model, for where its page is. Hugging Face for the rest. */
  const SITE_LOGO: Record<string, string> = { Ollama: "/providers/ollama.png", "Docker Hub": "/providers/docker.png" };
  /** Something to type, for someone who has never fetched a model. */
  const SUGGESTED = ["llama3.1:8b", "openai/gpt-oss-20b"];
  /** For llama.cpp, which the app gives a model file from Hugging Face (localai._start_file_pull). */
  const SUGGESTED_FILES = ["bartowski/Llama-3.2-3B-Instruct-GGUF", "Qwen/Qwen2.5-7B-Instruct-GGUF"];
  /** How a model is got here: "ollama", "file" (the app downloads it, for llama.cpp), or "". */
  let pullKind = $state("");

  let servers = $state<Server[]>([]);
  let models = $state<string[]>([]);
  /** Where each model came from on the web, by name: Hugging Face or Ollama's library. */
  let pages = $state<Record<string, Page>>({});
  /** How much disk each takes, when the server says (Ollama does). */
  let sizes = $state<Record<string, number>>({});
  /** How many parameters and how it is quantised, when the server says (Ollama does). */
  let details = $state<Record<string, Details>>({});
  /** The ones in memory right now, and how much of it they hold. */
  let loaded = $state<Record<string, number>>({});
  let revealing = $state("");
  let reachable = $state(false);
  let probeError = $state("");
  let canPull = $state(false);
  let modelMissing = $state(false);
  let pull = $state<Pull | null>(null);
  /** A model that would not load, and what is being done about it (app/utils/localfix.py). */
  let fix = $state<{ model: string; state: string; why: string; to: string;
                     alt?: { model: string; label: string; tag: string; size: number } | null } | null>(null);
  let switching = $state(false);
  /** Switch to the smaller one by the same maker that fits: it is downloaded where downloads show, below. */
  async function useAlt() {
    switching = true;
    try {
      await api.localFixUseAlt();
      play("ok");
      refresh(true);
    } catch (e: any) {
      play("err");
      toast(e?.message || "Could not switch", "err");
    }
    switching = false;
  }

  let baseUrl = $state("");
  /** The key sent to the server. Blank is none, which goes out as "local". */
  let apiKey = $state("");
  let storedKey = $state("");
  let keyInput = $state<HTMLInputElement | null>(null);
  /** The server at the address answered, but wants a key the app does not have. */
  let locked = $state(false);
  /** Which server the app found at the saved address, where two share a port. */
  let serverId = $state("");
  /** Which of the other servers has its card open. */
  let openId = $state("");
  let looking = $state(false);
  /** Start the server above with the app. */
  let autostart = $state(true);
  /** How many tokens of context Ollama gets when the app starts it. */
  let contextLength = $state(16384);
  let savedContext = $state(16384);
  let restarting = $state(false);
  const CONTEXTS = [4096, 8192, 16384, 32768, 65536];
  /** Tokens, and roughly how many words that is (three quarters of a token each). */
  const wordsFor = (c: number) => `About ${(Math.round((c * 0.75) / 500) * 500).toLocaleString()} words`;
  let startingId = $state("");

  let loading = $state(true);
  let saving = $state(false);
  let checking = $state(false);
  let pullName = $state("");
  let stored = $state("");

  const dirty = $derived(!loading && (baseUrl !== stored || apiKey.trim() !== storedKey));
  /**
   * The server the address points at: the one answering there, else the one
   * the app found there, else the first that lives there. llama.cpp and
   * LocalAI both use 8080, and the web UI and TabbyAPI 5000.
   */
  const pickedId = $derived.by(() => {
    const at = servers.filter((s) => s.base_url === baseUrl);
    return (at.find((s) => s.running || s.locked) ?? at.find((s) => s.id === serverId) ?? at[0])?.id ?? "";
  });
  /** On this computer or in use: running, installed, or the one the address points at. */
  const here = $derived(servers.filter((s) => s.running || s.locked || s.installed || s.id === pickedId));
  /** The one the card at the top is about: the one in use, else one that runs, else the first here. */
  const hero = $derived(here.find((s) => s.id === pickedId) ?? here.find((s) => s.running) ?? here[0] ?? null);
  /** The rest of the ones on this computer, under it. */
  const rest = $derived(here.filter((s) => s !== hero));
  /** Every other server it works with, as small chips. */
  const others = $derived(servers.filter((s) => !here.includes(s)));
  const opened = $derived(others.find((s) => s.id === openId) ?? null);
  /** Where a server listens, for people: no scheme, no API path. */
  const addr = (s: Server) => s.root.replace(/^https?:\/\//, "");
  const totalSize = $derived(models.reduce((n, m) => n + (sizes[m] || 0), 0));
  /** Which jobs are set to run here, from the saved plan, for the summary. */
  const usedFor = $derived.by(() => {
    const p = $savedPlan;
    if (!p) return [] as string[];
    const out: string[] = [];
    if (p.replies.some((e) => e.provider === "local")) out.push("Replies");
    const names: Record<string, string> = { small: "Background work", vision: "Pictures", stt: "Voice messages", tts: "Speaking" };
    for (const k of Object.keys(names)) if ((p as any)[k]?.provider === "local") out.push(names[k]);
    return out;
  });
  /** The word and colour for the server at the top. */
  const heroState = $derived.by(() => {
    const s = hero;
    if (!s) return { tone: "idle", word: "Not found" };
    if (startingId === s.id) return { tone: "warn", word: s.start === "app" ? "Opening" : "Starting" };
    if (s.locked) return { tone: "warn", word: "Needs a key" };
    if (s.running) return { tone: "good", word: "Running" };
    return { tone: "idle", word: s.installed ? "Not running" : "Not installed" };
  });

  /** Local models a job is set to use, so the list can say which. */
  const inUse = $derived.by(() => {
    const p = $savedPlan as any;
    const out = new Set<string>();
    if (!p) return out;
    const add = (e: any) => e?.provider === "local" && e.model && out.add(e.model);
    (p.replies || []).forEach(add);
    for (const list of Object.values(p.chains || {})) if (Array.isArray(list)) list.forEach(add);
    for (const k of ["small", "vision", "stt", "tts"]) add(p[k]);
    return out;
  });

  let timer: any = null;

  // Both of these probe network endpoints that wait out their own timeouts when
  // nothing is listening, and the subtab remounts every time it is opened. They
  // ran one after the other, uncached, so leaving and coming back cost the full
  // round again. Cached and concurrent: a return visit paints from what is
  // already held and revalidates behind it.
  const statusRes = resource("localStatus", () => api.localStatus(), null as any);
  const detectRes = resource("localDetect", () => api.localDetect(), null as any);

  // The server's models asked again every ten seconds while this is open: ones added or removed in the server's own
  // app (Ollama's) stayed on the list, and removing one here said the server did not have it.
  let stopWatch = () => {};
  onMount(async () => {
    // Only show the skeleton when there is genuinely nothing to show.
    loading = !get(statusRes).data;
    loadProviders().catch(() => {});
    await Promise.all([load(), refresh()]);
    loading = false;
    stopWatch = visiblePoll(() => refreshModels(), 10_000);
  });
  onDestroy(() => {
    clearInterval(timer);
    clearTimeout(sureTimer);
    stopWatch();
  });

  function apply(s: any) {
    baseUrl = s.settings.base_url;
    // "local" is the stand-in the app sends when no key is set, not a key anyone typed.
    apiKey = storedKey = s.settings.api_key && s.settings.api_key !== "local" ? s.settings.api_key : "";
    serverId = s.server || "";
    autostart = s.settings.autostart !== false;
    contextLength = savedContext = s.settings.context_length || 16384;
    reachable = s.reachable;
    locked = !!s.locked;
    probeError = s.error || "";
    models = s.models || [];
    pages = { ...pages, ...(s.pages || {}) };
    sizes = s.sizes || {};
    details = s.details || {};
    loaded = s.loaded || {};
    canPull = s.can_pull;
    pullKind = s.pull_kind || (s.can_pull ? "ollama" : "");
    modelMissing = s.model_missing;
    pull = s.pull;
    // What ended before this page looked is not news: only ones that end while it watches are said.
    if (!lastSaid) lastSaid = s.pull?.last?.at ?? 0;
    fix = s.fix?.state ? s.fix : null;
    stored = baseUrl;
    watchPull();
  }

  async function load(force = false) {
    // Paint from whatever is already held before touching the network. Both
    // endpoints probe a server that is usually not there, so each waits out its
    // own timeout, and this subtab remounts every single time it is opened -
    // which is why leaving and coming back used to mean sitting through the
    // whole round again. A stale answer on screen while the fresh one arrives
    // is the right trade for something that changes this rarely.
    const held = !force && get(statusRes).data;
    if (held) apply(held);

    try {
      const s = await statusRes.refresh(force ? { force: true } : { maxAge: 20000 });
      if (s) apply(s);
    } catch (e: any) {
      if (!held) toast(e?.message || "Could not read the local settings", "err");
    }
  }

  /** The models, their sizes and what is loaded, without touching the address being typed. */
  async function refreshModels() {
    try {
      const s = await statusRes.refresh({ force: true });
      if (!s || s.settings.base_url !== baseUrl) return;
      models = s.models || [];
      pages = { ...pages, ...(s.pages || {}) };
      sizes = s.sizes || {};
      details = s.details || {};
      loaded = s.loaded || {};
      reachable = s.reachable;
    } catch {}
  }

  /** Look for servers that are running, so nothing has to be typed. */
  async function refresh(force = false) {
    const held = !force && get(detectRes).data;
    if (held) setServers(held.servers || []);
    try {
      const d = await detectRes.refresh(force ? { force: true } : { maxAge: 20000 });
      if (d) setServers(d.servers || []);
    } catch {
      if (!held) servers = [];
    }
  }

  function setServers(list: Server[]) {
    servers = list;
    const found: Record<string, Page> = {};
    for (const s of list) Object.assign(found, s.pages || {});
    pages = { ...found, ...pages };
  }

  /** Point the address at this server. One that wants a key gets the key box. */
  function use(s: Server) {
    baseUrl = s.base_url;
    models = s.models;
    reachable = s.running;
    locked = !!s.locked;
    probeError = s.locked ? "It answered, but wants an API key." : "";
    // llama.cpp gets its models from the app (a file from Hugging Face); the status that follows says for sure.
    pullKind = s.can_pull ? "ollama" : s.id === "llamacpp" ? "file" : "";
    canPull = !!pullKind;
    openId = "";
    if (s.locked) tick().then(() => keyInput?.focus());
  }

  async function lookAgain() {
    looking = true;
    await Promise.all([refresh(true), refreshModels()]);
    looking = false;
  }

  async function check() {
    checking = true;
    try {
      const r = await api.localProbe(baseUrl, apiKey.trim() || "local");
      baseUrl = r.base_url;
      reachable = r.ok;
      locked = !!r.locked;
      if (r.server) serverId = r.server;
      models = r.models || [];
      pages = { ...pages, ...(r.pages || {}) };
      probeError = r.error || "";
      toast(r.ok ? `Found ${r.models.length} model(s).` : r.error, r.ok ? "ok" : "err");
    } catch (e: any) {
      toast(e?.message || "Could not reach it", "err");
    }
    checking = false;
  }

  /** Start a server that is installed but not running, or open its app, and wait until it answers. */
  async function startServer(s: Server) {
    if (startingId) return;
    startingId = s.id;
    try {
      const r = await api.localStart(s.id, s.base_url);
      if (r?.ok) {
        toast(r.already ? `${s.name} was already running.` : `${s.name} is running.`, "ok");
        // Started while the saved address has nothing answering: the app moves over to it, saved, so it is the one
        // used (and the one started with the app) without a Save to find as well.
        if ((!baseUrl || !reachable) && s.base_url !== stored) {
          baseUrl = s.base_url;
          await api.configField("bot.local.base_url", s.base_url);
          stored = s.base_url;
          loadProviders().catch(() => {});
        }
      } else if (r?.opened) {
        // Open, with its server still switched off inside it: say where the switch is.
        toast(r.reason, "info");
      } else {
        toast(r?.reason || `Could not start ${s.name}`, "err");
      }
      await Promise.all([refresh(true), load(true)]);
      const h = await api.healthNow();
      if (h && Array.isArray(h.issues) && h.routes) health.set(h);
    } catch (e: any) {
      toast(e?.message || `Could not start ${s.name}`, "err");
    } finally {
      startingId = "";
    }
  }

  /** Save the context length and restart Ollama so it takes effect. */
  async function applyContext() {
    restarting = true;
    try {
      if (contextLength !== savedContext) {
        await api.configField("bot.local.context_length", contextLength);
        savedContext = contextLength;
      }
      const r = await api.localRestart();
      toast(r?.ok && !r.already ? `Ollama restarted with room for ${contextLength.toLocaleString()} tokens.`
                                : r?.reason || "Could not restart Ollama", r?.ok && !r.already ? "ok" : "err");
      await Promise.all([refresh(true), load(true)]);
    } catch (e: any) {
      toast(e?.message || "Could not restart Ollama", "err");
    } finally {
      restarting = false;
    }
  }

  async function setAutostart(v: boolean) {
    autostart = v;
    try {
      await api.configField("bot.local.autostart", v);
    } catch (e: any) {
      autostart = !v;
      toast(e?.message || "Could not save that", "err");
    }
  }

  async function save() {
    saving = true;
    try {
      const key = apiKey.trim();
      const writes = async () => {
        if (baseUrl !== stored) await api.configField("bot.local.base_url", baseUrl);
        if (key !== storedKey) await api.configField("bot.local.api_key", key || "local");
      };
      await track("settings", writes(), "Saving the server address");
      stored = baseUrl;
      storedKey = key;
      toast("Saved. The next request goes there.", "ok");
      await load(true);
      await loadProviders();
    } catch (e: any) {
      toast(e?.message || "Could not save", "err");
    }
    saving = false;
  }

  // ── Getting a model ──────────────────────────────────────────────────────
  /** Between the press and the download starting: the server asks Hugging Face which file is the model, which can
   * take ten seconds, and the button sat there as if nothing had been pressed. */
  let asking = $state(false);
  async function startPull() {
    const name = pullName.trim();
    if (!name || asking) return;
    asking = true;
    // Typed while one downloads: it goes in the queue, and starts when its turn comes.
    const busy = !!pull?.active;
    try {
      const r = await api.localPull(name, baseUrl);
      pullName = "";
      if (r.queued) {
        toast(r.queued === 1 ? `${r.model} is next.` : `${r.model} is in line, number ${r.queued}.`, "info");
        pull = await api.localPullStatus();
      } else {
        toast(`Downloading ${r.model}. It can take a while.`, "info");
        rate = 0;
        sample = null;
      }
      if (r.warning) toast(r.warning, "info");
      watchPull(true);
      // watchPull stops when this page does. This one keeps checking, so the
      // Settings spinner stays until every download in line has finished.
      if (!busy) {
        trackUntil("settings", `Downloading ${r.model}`, async (report) => {
          const s = await api.localPullStatus();
          // Ollama reports bytes; the server turns that into a percentage.
          if (s?.active && typeof s.percent === "number") report(s.percent, 100);
          return !s?.active && !(s?.queue?.length);
        }, 2000);
      }
    } catch (e: any) {
      toast(e?.message || "Could not start the download", "err");
    } finally {
      asking = false;
    }
  }

  /** Out of the line before its turn. */
  async function unqueue(model: string) {
    try {
      await api.localPullUnqueue(model);
      pull = await api.localPullStatus();
    } catch (e: any) {
      toast(e?.message || "Could not take it out", "err");
    }
  }

  let stopping = $state(false);
  async function stopPull() {
    stopping = true;
    try {
      await api.localPullCancel();
    } catch (e: any) {
      toast(e?.message || "Could not stop it", "err");
    }
  }

  /** Bytes a second, smoothed, and where it was last looked at. */
  let rate = $state(0);
  let sample: { done: number; at: number } | null = null;
  function measure(p: Pull) {
    const now = performance.now();
    // Each layer counts from nothing again: start the measuring over with it.
    if (!sample || p.done < sample.done) {
      sample = { done: p.done, at: now };
      return;
    }
    const secs = (now - sample.at) / 1000;
    if (secs < 0.5) return;
    const r = (p.done - sample.done) / secs;
    rate = rate ? rate * 0.7 + r * 0.3 : r;
    sample = { done: p.done, at: now };
  }

  /** When the last one this page has said something about ended: each that ends is said once, even when the queue
   * moves straight on to the next and the download never looks idle in between. */
  let lastSaid = 0;
  async function sayEnded(p: Pull) {
    const l = p.last;
    if (!l || l.at <= lastSaid) return;
    lastSaid = l.at;
    stopping = false;
    rate = 0;
    sample = null;
    if (l.cancelled) toast("Download stopped. Start it again to carry on.", "info");
    else if (l.error) toast(l.error, "err");
    else {
      toast(`${l.model} is ready. Pick it under Models.`, "ok");
      await check();
      await refreshModels();
    }
  }

  /** Poll only while something is downloading, or waiting to. */
  function watchPull(force = false) {
    clearInterval(timer);
    if (!force && !pull?.active && !pull?.queue?.length) return;
    timer = setInterval(async () => {
      try {
        pull = await api.localPullStatus();
        if (pull!.active) measure(pull!);
        await sayEnded(pull!);
        if (!pull!.active && !pull!.queue?.length) clearInterval(timer);
      } catch {
        clearInterval(timer);
      }
    }, 1200);
  }

  const gb = (n: number) => (n > 0 ? `${(n / 1e9).toFixed(1)} GB` : "");
  const speed = (bps: number) => (bps >= 1e6 ? `${(bps / 1e6).toFixed(1)} MB/s` : `${Math.max(1, Math.round(bps / 1e3))} KB/s`);
  function timeLeft(secs: number) {
    if (!isFinite(secs) || secs <= 0) return "";
    if (secs < 60) return "under a minute left";
    const m = Math.round(secs / 60);
    return m < 60 ? `${m} min left` : `${Math.floor(m / 60)} h ${m % 60} min left`;
  }
  /** What Ollama is doing, in words: "pulling 115e618e1f73" is a layer's name, not news. */
  function stage(p: Pull) {
    const s = (p.status || "").toLowerCase();
    if (stopping || s === "stopping") return "Stopping";
    if (s === "starting" || s === "pulling manifest") return "Starting";
    if (s.startsWith("pulling")) return "Downloading";
    if (s.startsWith("verifying")) return "Checking it";
    if (s.startsWith("writing") || s.startsWith("removing")) return "Finishing";
    return s ? s[0].toUpperCase() + s.slice(1) : "Starting";
  }
  const pullLine = $derived.by(() => {
    const p = pull;
    if (!p?.active) return "";
    const bits = [stage(p)];
    if (p.total) bits.push(`${gb(p.done) || "0.0 GB"} of ${gb(p.total)}`);
    if (p.total && rate > 0 && !stopping) {
      bits.push(speed(rate));
      const left = timeLeft((p.total - p.done) / rate);
      if (left) bits.push(left);
    }
    return bits.join(" · ");
  });

  // ── Removing one ─────────────────────────────────────────────────────────
  /** Asked once, on the button itself: a second click within a few seconds removes it. */
  let sure = $state("");
  let sureTimer = 0;
  let removing = $state("");
  function askRemove(m: string) {
    sure = m;
    clearTimeout(sureTimer);
    sureTimer = window.setTimeout(() => (sure = ""), 4000);
  }
  async function removeModel(m: string) {
    clearTimeout(sureTimer);
    sure = "";
    removing = m;
    const freed = gb(sizes[m] || 0);
    try {
      const r: any = await api.localDelete(m, baseUrl);
      models = models.filter((x) => x !== m);
      // The settings that used it no longer do (app/utils/localfix.py drop): said, and the Models tab told.
      const unused: string[] = r?.unused ?? [];
      const what = unused.includes("replies") ? " Replies used it, so they're on Groq again until you pick another."
        : unused.length ? " Nothing uses it any more." : "";
      toast((freed ? `Removed. ${freed} back on the disk.` : "Removed.") + what, "ok");
      if (unused.length) loadProviders().catch(() => {});
      loadModels("local", true).catch(() => {});
      await refreshModels();
    } catch (e: any) {
      // Removed some other way already (Ollama's own app): the row goes, and the settings that named it let go of it.
      if (/does not have/i.test(e?.message || "")) {
        models = models.filter((x) => x !== m);
        api.localForget([m]).then((r: any) => { if (r?.unused?.length) loadProviders().catch(() => {}); }).catch(() => {});
        toast("It was already gone from the server.", "info");
        loadModels("local", true).catch(() => {});
        await refreshModels();
      } else toast(e?.message || "Could not remove it", "err");
    } finally {
      removing = "";
    }
  }

  /** Open the file manager on the model's file. The server finds it from the name. */
  async function reveal(m: string) {
    if (revealing) return;
    revealing = m;
    try {
      await api.localReveal(m, baseUrl);
    } catch (e: any) {
      toast(e?.message || "Could not find where that model is", "err");
    } finally {
      revealing = "";
    }
  }

  /** A model's facts in a line, each once: its tag often is its size or its quant ("8b" and "8.0B", "Q4_K_M" twice). */
  function facts(list: (string | undefined)[]) {
    const seen = new Set<string>();
    const key = (t: string) => t.toLowerCase().replace(/\.0+(?=[a-z]*$)/, "").replace(/[^a-z0-9.]/g, "");
    return list.filter((t): t is string => {
      if (!t) return false;
      const k = key(t);
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    }).join(" · ");
  }

  /** A model name the way a person reads it: the model, then who made it and which version. */
  function nameParts(m: string): { title: string; sub: string } {
    let rest = m;
    let from = "";
    const hf = rest.match(/^(?:hf\.co|huggingface\.co)\/([^/]+)\/(.+)$/i);
    if (hf) {
      from = hf[1];
      rest = hf[2];
    } else if (/\.gguf$/i.test(rest)) {
      rest = rest.split(/[\\/]/).pop() || rest;
    } else if (rest.indexOf("/") > 0) {
      from = rest.slice(0, rest.indexOf("/"));
      rest = rest.slice(rest.indexOf("/") + 1);
    }
    const c = rest.lastIndexOf(":");
    const tag = c > 0 ? rest.slice(c + 1) : "";
    return { title: c > 0 ? rest.slice(0, c) : rest, sub: [from, tag].filter(Boolean).join(" · ") };
  }
</script>

<!-- A hint, with its commands in backticks set as code. -->
{#snippet said(text: string)}
  {#each text.split("`") as part, i}{#if i % 2}<code class="ls-code">{part}</code>{:else}{part}{/if}{/each}
{/snippet}

{#if loading}
  <div class="lc-skel" aria-hidden="true">
    <div class="lc-skel-hero"></div>
    {#each Array(3) as _}<div class="lc-skel-row"></div>{/each}
  </div>
{:else}
  <!-- A phone runs no model servers; one elsewhere on the network still works. -->
  <NotHere feature="local_start" />

  <!-- ── The server ───────────────────────────────────────────────────────── -->
  {#if hero}
    {@const s = hero}
    <section class="lc-hero is-{heroState.tone}" class:is-busy={atWork && s.running}
             title={atWork && s.running ? "Working on something right now" : undefined}>
      <div class="lc-hero-main">
        <span class="lc-logo">
          <ProviderTile id={s.id} size={46} />
          <span class="ls-dot" class:is-on={s.running} class:is-warn={s.locked}></span>
        </span>
        <div class="min-w-0 flex-1">
          <div class="lc-name">{s.name}</div>
          <p class="lc-sub">
            {#if s.locked}
              Running · wants its API key · <span class="font-mono">{addr(s)}</span>
            {:else if s.running}
              <span class="font-mono">{addr(s)}</span> · {models.length} model{models.length === 1 ? "" : "s"}{totalSize ? ` · ${gb(totalSize)}` : ""}
            {:else if s.can_start}
              Installed, not running
            {:else if s.installed}
              {@render said(s.hint || "")}
            {:else}
              Not on this computer yet.{#if s.id === "ollama"} The easiest way to run models here.{/if}
            {/if}
          </p>
          <div class="lc-uses">
            {#if usedFor.length}
              <span class="lc-uses-label">Runs</span>
              {#each usedFor as u (u)}<span class="lc-use">{u}</span>{/each}
            {:else}
              <span class="lc-uses-label">Nothing runs on this computer yet.</span>
            {/if}
          </div>
        </div>
        <span class="lc-state is-{heroState.tone}"><i></i>{heroState.word}</span>
      </div>

      <div class="lc-actions">
        {#if !s.running && !s.locked && s.can_start}
          {@const opens = s.start === "app"}
          <Button size="sm" onclick={() => startServer(s)} loading={startingId === s.id} disabled={!!startingId && startingId !== s.id}>
            {#if startingId !== s.id}<Icon name={opens ? "external" : "play"} size={10} />{/if}
            {startingId === s.id ? (opens ? "Opening" : "Starting") : (opens ? "Open" : "Start")}
          </Button>
        {:else if !s.running && !s.locked && !s.installed}
          <a href={s.site} target="_blank" rel="noopener" class="lc-btn is-go">
            {s.id === "ollama" ? "Get Ollama, the easiest" : "Download"} <Icon name="external" size={10} />
          </a>
        {/if}
        {#if s.locked}
          <button type="button" class="lc-btn is-warn" onclick={() => keyInput?.focus()}><Icon name="key" size={11} /> Needs a key</button>
        {/if}
        <button type="button" class="lc-btn" onclick={() => settingsSection.set("groq/models")}>
          Choose models <Icon name="chevron" size={11} />
        </button>
        <button type="button" class="lc-btn is-quiet" onclick={lookAgain} disabled={looking}>
          <span class="lc-turn" class:is-turning={looking}><Icon name="refresh" size={12} /></span>
          {looking ? "Looking" : "Look again"}
        </button>
      </div>

      <!-- The others on this computer: running ones to switch to, installed ones
           to start or open with a click. -->
      {#if rest.length}
        <div class="lc-rest">
          {#each rest as o (o.id)}
            {#if o.running || o.locked}
              <button onclick={() => use(o)} class="ls-row is-running">
                <span class="ls-logo">
                  <ProviderTile id={o.id} size={26} /><span class="ls-dot" class:is-on={o.running} class:is-warn={o.locked}></span>
                </span>
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-[12.5px] font-medium text-ink">{o.name}</span>
                  <span class="block truncate text-[11px] text-faint">
                    {#if o.locked}Running · wants its API key{:else}Running · {o.models.length} model{o.models.length === 1 ? "" : "s"}{/if} · {addr(o)}
                  </span>
                </span>
                {#if o.locked}
                  <span class="ls-chip is-warn"><Icon name="key" size={10} /> Needs a key</span>
                {:else}
                  <span class="ls-use">Use this one</span>
                {/if}
              </button>
            {:else if o.can_start}
              {@const opens = o.start === "app"}
              <div class="ls-row">
                <span class="ls-logo"><ProviderTile id={o.id} size={26} /><span class="ls-dot"></span></span>
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-[12.5px] font-medium text-ink">{o.name}</span>
                  <span class="block truncate text-[11px] text-faint">Installed, not running</span>
                </span>
                <Button size="sm" kind="ghost" onclick={() => startServer(o)} loading={startingId === o.id} disabled={!!startingId && startingId !== o.id}>
                  {#if startingId !== o.id}<Icon name={opens ? "external" : "play"} size={10} />{/if}
                  {startingId === o.id ? (opens ? "Opening" : "Starting") : (opens ? "Open" : "Start")}
                </Button>
              </div>
            {:else}
              <div class="ls-row is-absent">
                <span class="ls-logo is-dim"><ProviderTile id={o.id} size={26} /><span class="ls-dot is-off"></span></span>
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-[12.5px] text-muted">{o.name}</span>
                  <span class="block text-[11px] leading-snug text-faint">
                    {#if o.installed}{@render said(o.hint || "")}{:else}Not installed{/if}
                  </span>
                </span>
              </div>
            {/if}
          {/each}
        </div>
      {/if}
    </section>
  {:else}
    <section class="lc-hero is-idle">
      <div class="lc-hero-main">
        <span class="lc-logo"><ProviderTile id="local" size={46} /></span>
        <div class="min-w-0 flex-1">
          <div class="lc-name">No model server found</div>
          <p class="lc-sub">Ollama is the easiest: once it is installed, it is found here by itself.</p>
        </div>
      </div>
      <div class="lc-actions">
        <a href="https://ollama.com/download" target="_blank" rel="noopener" class="lc-btn is-go">Get Ollama <Icon name="external" size={10} /></a>
        <button type="button" class="lc-btn is-quiet" onclick={lookAgain} disabled={looking}>
          <span class="lc-turn" class:is-turning={looking}><Icon name="refresh" size={12} /></span>
          {looking ? "Looking" : "Look again"}
        </button>
      </div>
    </section>
  {/if}

  <!-- ── Its models ───────────────────────────────────────────────────────── -->
  <section class="lc-sec">
    <header class="lc-head">
      <h3>Models</h3>
      {#if models.length}
        <span class="lc-count">{models.length}{totalSize ? ` · ${gb(totalSize)}` : ""}</span>
      {/if}
    </header>

    {#if canPull}
      <!-- An Ollama name, or a Hugging Face repo, which Ollama fetches straight from there. -->
      <form class="lc-get" class:is-asking={asking} onsubmit={(e) => { e.preventDefault(); startPull(); }}>
        <span class="lc-get-icon"><Icon name="download" size={14} /></span>
        <input
          bind:value={pullName}
          placeholder={pullKind === "file" ? "Get a model: a Hugging Face repo, like user/model or user/model:Q4_K_M"
                                           : "Get a model: an Ollama name or a Hugging Face repo"}
          spellcheck="false"
          disabled={asking}
          aria-label="Model to download"
        />
        <!-- Typed while one downloads, it waits its turn: the box stays open for the next. -->
        <button type="submit" class="lc-get-go" class:is-asking={asking} disabled={!pullName.trim() || asking}
                aria-busy={asking}>
          {#if asking}<span class="lc-get-spin" aria-hidden="true"></span>Looking it up{:else}{pull?.active ? "Queue" : "Download"}{/if}
        </button>
      </form>
      {#if !pull?.active && !models.length}
        <div class="lc-try">
          <span>Try</span>
          {#each pullKind === "file" ? SUGGESTED_FILES : SUGGESTED as t (t)}
            <button type="button" onclick={() => (pullName = t)}>{t}</button>
          {/each}
          <span class="lc-try-note">
            {pullKind === "file" ? "The size that fits this computer is picked for you." : "A 7-8B model suits most computers and is a few gigabytes."}
          </span>
        </div>
      {/if}
    {:else if hero?.get}
      <!-- One the app cannot give a model to: where its models do come from, in the box's place. -->
      <p class="lc-get-else"><span class="lc-get-icon"><Icon name="download" size={13} /></span><span>{@render said(hero.get)}</span></p>
    {/if}

    {#if pull?.active}
      {@const pn = nameParts(pull.model)}
      <div class="lc-pull" transition:slide={{ duration: 260, easing: cubicOut }}>
        <div class="lc-pull-top">
          <span class="lc-pull-icon"><Icon name="download" size={14} /></span>
          <span class="min-w-0 flex-1">
            <span class="lc-pull-name">{pn.title}<em>{pn.sub ? ` · ${pn.sub}` : ""}</em></span>
            <span class="lc-pull-sub">{pullLine}</span>
          </span>
          <span class="lc-pull-pct">{pull.percent}<small>%</small></span>
          <button type="button" class="lc-btn is-quiet" onclick={stopPull} disabled={stopping}>{stopping ? "Stopping" : "Stop"}</button>
        </div>
        <div class="lc-bar"><div class="lc-bar-fill" style="width: {pull.percent}%"></div></div>
        <!-- The ones waiting their turn, in order, each a click from leaving the line. -->
        {#if pull.queue?.length}
          <ol class="lc-queue">
            {#each pull.queue as q, i (q.model)}
              {@const qn = nameParts(q.model)}
              <li class="lc-queue-row" in:fly={{ y: -6, duration: 260, easing: cubicOut }} out:slide={{ duration: 200 }}
                  animate:flip={{ duration: 260 }}>
                <span class="lc-queue-n">{i + 1}</span>
                <span class="min-w-0 flex-1 truncate">{qn.title}<em>{qn.sub ? ` · ${qn.sub}` : ""}</em></span>
                <span class="lc-queue-when">{i === 0 ? "Next" : "Waiting"}</span>
                <button type="button" class="lc-queue-x" aria-label="Take {qn.title} out of the line" title="Take it out"
                        onclick={() => unqueue(q.model)}><Icon name="close" size={11} /></button>
              </li>
            {/each}
          </ol>
        {/if}
      </div>
    {:else if pull?.error}
      <p class="lc-err">{pull.error}</p>
    {/if}

    <!-- A model that would not load: what is wrong with it, and what the app is doing about it. -->
    {#if fix && fix.state !== "checking"}
      <p class="lc-fix" class:is-bad={fix.state === "stuck"} class:is-good={fix.state === "fixed"}>
        <Icon name={fix.state === "stuck" ? "alertCircle" : fix.state === "fixed" ? "check" : "download"} size={13} />
        <span>
          {#if fix.state === "fixed"}
            Fixed: {nameParts(fix.model).title} is swapped for {nameParts(fix.to).title}.
          {:else if fix.state === "fixing"}
            {nameParts(fix.model).title}: {fix.why}.
          {:else if fix.why?.startsWith("it is too big")}
            <!-- It loads, just too slowly to be of use: not "will not load". -->
            {nameParts(fix.model).title} {fix.why.slice(3)}.
          {:else}
            {nameParts(fix.model).title} will not load: {fix.why}.
          {/if}
        </span>
      </p>
      <!-- Something smaller by the same maker that fits: one click, never switched to unasked. -->
      {#if fix.state === "stuck" && fix.alt}
        <div class="lc-alt">
          <span class="lc-alt-text">
            <b>{fix.alt.label}</b>
            <span>Same maker, smaller: {gb(fix.alt.size)}, fits this computer.</span>
          </span>
          <Button size="sm" loading={switching} onclick={useAlt}>Use it instead</Button>
        </div>
      {/if}
    {/if}

    {#if models.length}
      <!-- Each opens where it came from, and the folder shows the file on this
           computer: tens of gigabytes, so "where did it go" is a real question. -->
      <div class="lm-list">
        {#each models as m (m)}
          {@const page = pages[m]}
          {@const n = nameParts(m)}
          {@const d = details[m]}
          {@const sub = facts([...n.sub.split(" · "), d?.params, d?.quant, sizes[m] ? gb(sizes[m]) : ""])}
          <div class="lm-row" class:is-going={removing === m} transition:slide={{ duration: 280, easing: cubicOut }}>
            {#if page?.url}
              <a class="lm-main" href={page.url} target="_blank" rel="noopener noreferrer" title="Open {m} on {page.site}">
                <img class="lm-site" src={SITE_LOGO[page.site] ?? "/providers/huggingface.png"}
                     alt={page.site} draggable="false" />
                <span class="min-w-0 flex-1">
                  <span class="lm-title">{n.title}</span>
                  {#if sub}<span class="lm-sub">{sub}</span>{/if}
                </span>
                <span class="lm-go"><span class="lm-go-label">{page.site}</span><Icon name="external" size={11} /></span>
              </a>
            {:else}
              <span class="lm-main">
                <span class="lm-site is-plain"><Icon name="monitor" size={13} /></span>
                <span class="min-w-0 flex-1">
                  <span class="lm-title">{n.title}</span>
                  {#if sub}<span class="lm-sub">{sub}</span>{/if}
                </span>
              </span>
            {/if}
            {#if loaded[m] != null}
              <span class="lm-mem" title="Loaded{loaded[m] ? `, ${gb(loaded[m])} of memory` : ''}: it answers at once"><i></i>In memory</span>
            {/if}
            {#if inUse.has(m)}<span class="lm-used">In use</span>{/if}
            <button class="lm-folder" onclick={() => reveal(m)} disabled={revealing === m}
                    title="Show it on this computer" aria-label="Show {n.title} on this computer">
              <Icon name="folder" size={15} />
            </button>
            {#if canPull}
              {#if sure === m}
                <button class="lm-sure" onclick={() => removeModel(m)}>
                  <Icon name="trash" size={12} />Remove{#if sizes[m]} {gb(sizes[m])}{/if}
                </button>
              {:else}
                <button class="lm-folder is-bin" onclick={() => askRemove(m)} disabled={!!removing}
                        title="Remove it from this computer" aria-label="Remove {n.title}">
                  <Icon name="trash" size={14} />
                </button>
              {/if}
            {/if}
          </div>
        {/each}
      </div>
    {:else if reachable}
      <p class="lc-empty">No models yet.{#if canPull} Type a name above to get one.{/if}</p>
    {:else}
      <p class="lc-empty">Its models show here once it is running.</p>
    {/if}
  </section>

  <!-- ── Settings ─────────────────────────────────────────────────────────── -->
  <section class="lc-sec">
    <header class="lc-head"><h3>Settings</h3></header>
    <div class="lc-set">
      <div class="lc-row">
        <div class="lc-row-text">
          <b>Start it with the app</b>
          <p>The server above starts when the app opens.</p>
        </div>
        <Toggle checked={autostart} onchange={setAutostart} name="Start it with the app" />
      </div>

      <!-- The model's working memory. Ollama's own default is 4096 tokens, which a
           persona of a few pages fills on its own: every reply then failed with
           "request exceeds the available context size". -->
      <div class="lc-row is-wrap">
        <div class="lc-row-text">
          <b>Room for the conversation</b>
          <p>How much the model reads at once, in tokens. Your persona and the recent messages have to fit.
            Applies when the app starts Ollama or llama.cpp.</p>
        </div>
        <div class="lc-ctx">
          <Segmented label="Room for the conversation" value={String(contextLength)}
                     options={CONTEXTS.map((c) => ({ id: String(c), label: `${c / 1024}K` }))}
                     onchange={(id) => (contextLength = Number(id))} />
          <div class="lc-ctx-foot">
            <span>{contextLength.toLocaleString()} tokens · {wordsFor(contextLength).toLowerCase()}</span>
            <Button size="sm" kind={contextLength !== savedContext ? "primary" : "ghost"} loading={restarting} onclick={applyContext}>
              {#if !restarting}<Icon name="refresh" size={11} />{/if}{contextLength !== savedContext ? "Apply and restart Ollama" : "Restart Ollama"}
            </Button>
          </div>
        </div>
      </div>

      <div class="lc-row is-stack">
        <div class="lc-row-text">
          <b>Server address</b>
          <p>Found by itself. Change it for a server somewhere else on the network.</p>
        </div>
        <div class="lc-addr">
          <input
            bind:value={baseUrl}
            placeholder="http://127.0.0.1:11434/v1"
            spellcheck="false"
            aria-label="Server address"
            class="field font-mono text-[12px]"
          />
          <Button kind="ghost" size="sm" onclick={check} loading={checking}>
            {#if !checking}<Icon name="refresh" size={12} />{/if}Refresh
          </Button>
        </div>
        <!-- Most servers take no key. The ones set to want one (Jan, TabbyAPI,
             anything started with --api-key) turn every request away without it. -->
        <label class="ls-key" class:is-wanted={locked}>
          <Icon name="key" size={13} />
          <input
            bind:this={keyInput}
            bind:value={apiKey}
            type="password"
            placeholder="API key, only if the server asks for one"
            autocomplete="off"
            spellcheck="false"
            class="field font-mono text-[12px]"
          />
        </label>
        {#if locked}
          <p class="lc-note is-warn">It answered, but wants an API key. Put it in above, then Refresh.</p>
        {:else if probeError && !reachable}
          <p class="lc-note is-bad">{probeError}</p>
        {:else if reachable}
          <p class="lc-note is-good"><i></i>Answering, with {models.length} model{models.length === 1 ? "" : "s"}.</p>
        {/if}
        {#if dirty}
          <div class="lc-save" transition:slide={{ duration: 200, easing: cubicOut }}>
            <Button size="sm" onclick={save} loading={saving}>Save</Button>
            <Button kind="ghost" size="sm" onclick={() => { loading = true; load(true).then(() => (loading = false)); }}>
              Revert
            </Button>
            <span>Used from the next request, no restart needed.</span>
          </div>
        {/if}
      </div>
    </div>
  </section>

  <!-- ── Every other server it works with ─────────────────────────────────── -->
  {#if others.length}
    <section class="lc-sec">
      <header class="lc-head">
        <h3>Also works with</h3>
        <span class="lc-count">Found by itself when it runs</span>
      </header>
      <div class="ls-grid">
        {#each others as o (o.id)}
          <button class="ls-tile" class:is-open={openId === o.id} aria-expanded={openId === o.id}
                  onclick={() => (openId = openId === o.id ? "" : o.id)}>
            <ProviderTile id={o.id} size={20} />
            <span class="ls-tile-name">{o.name}</span>
          </button>
        {/each}
      </div>
      {#if opened}
        {#key opened.id}
          <div class="ls-card">
            <ProviderTile id={opened.id} size={34} />
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-baseline gap-x-2">
                <span class="text-[13px] font-medium text-ink">{opened.name}</span>
                <span class="font-mono text-[11px] text-faint">{addr(opened)}</span>
              </div>
              <p class="mt-1 text-[12px] leading-relaxed text-muted">{@render said(opened.hint || "")}</p>
              <div class="mt-2.5 flex flex-wrap items-center gap-2">
                <Button size="sm" kind="ghost" onclick={() => use(opened)}>Use this address</Button>
                <a href={opened.site} target="_blank" rel="noopener" class="lc-btn is-quiet">Get it <Icon name="external" size={10} /></a>
              </div>
            </div>
          </div>
        {/key}
      {/if}
    </section>
  {/if}
{/if}

<style>
  /* ── Loading ─────────────────────────────────────────────────────────── */
  .lc-skel { display: flex; flex-direction: column; gap: 8px; }
  .lc-skel-hero, .lc-skel-row {
    border-radius: 16px;
    background: rgb(255 255 255 / 0.03);
    animation: lc-pulse 1.4s ease-in-out infinite;
  }
  .lc-skel-hero { height: 132px; margin-bottom: 10px; }
  .lc-skel-row { height: 52px; border-radius: 13px; }
  @keyframes lc-pulse { 50% { opacity: 0.5; } }

  /* ── The server ──────────────────────────────────────────────────────── */
  .lc-hero {
    --tone: var(--color-faint);
    position: relative;
    overflow: hidden;
    margin-bottom: 22px;
    padding: 16px;
    border-radius: 18px;
    background:
      radial-gradient(120% 150% at 0% 0%, color-mix(in srgb, var(--tone) 13%, transparent), transparent 58%),
      rgb(255 255 255 / 0.025);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 75%, transparent);
    transition: box-shadow 0.4s var(--swift);
  }
  .lc-hero.is-good { --tone: var(--color-good); }
  .lc-hero.is-warn { --tone: var(--color-warn); }
  .lc-hero-main { display: flex; align-items: flex-start; gap: 14px; }
  .lc-logo { position: relative; display: inline-flex; flex-shrink: 0; }
  .lc-logo .ls-dot {
    position: absolute;
    right: -3px;
    bottom: -3px;
    width: 12px;
    height: 12px;
    box-shadow: 0 0 0 3px var(--color-card);
  }
  /* At work (a request to it under way): a ring goes out from the logo, like a
     signal. Only then, not all the time it is running. */
  .lc-hero.is-good.is-busy .lc-logo::after {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 14px;
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-good) 45%, transparent);
    animation: lc-signal 2.8s ease-out infinite;
  }
  @keyframes lc-signal { to { box-shadow: 0 0 0 14px color-mix(in srgb, var(--color-good) 0%, transparent); } }
  .lc-name { font-size: 16px; font-weight: 650; letter-spacing: -0.01em; color: var(--color-ink); }
  .lc-sub { margin-top: 2px; font-size: 12.5px; line-height: 1.5; color: var(--color-muted); overflow-wrap: anywhere; }
  .lc-uses { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; margin-top: 9px; }
  .lc-uses-label { font-size: 11.5px; color: var(--color-faint); margin-right: 2px; }
  .lc-use {
    padding: 2px 9px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 13%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 20%, transparent);
  }
  .lc-state {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.05);
  }
  .lc-state i { width: 7px; height: 7px; border-radius: 999px; background: currentColor; }
  .lc-state.is-good { color: var(--color-good); }
  .lc-state.is-good i { box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-good) 25%, transparent); }
  .lc-state.is-warn { color: var(--color-warn); }
  .lc-actions { display: flex; flex-wrap: wrap; gap: 6px; margin: 14px 0 0 60px; }

  .lc-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 11px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 600;
    white-space: nowrap;
    text-decoration: none;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.06);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.07);
    transition: background-color 0.15s var(--swift), transform 0.3s var(--jelly), color 0.15s ease;
  }
  .lc-btn:hover:not(:disabled) { background: rgb(255 255 255 / 0.1); }
  .lc-btn:active:not(:disabled) { transform: scale(0.96); }
  .lc-btn:disabled { opacity: 0.6; cursor: default; }
  .lc-btn.is-quiet { color: var(--color-muted); background: transparent; box-shadow: none; }
  .lc-btn.is-quiet:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.06); }
  .lc-btn.is-go {
    color: var(--color-bg, #0b0d12);
    background: var(--color-accent);
    box-shadow: 0 6px 18px -8px color-mix(in srgb, var(--color-accent) 80%, transparent);
  }
  .lc-btn.is-go:hover { filter: brightness(1.08); background: var(--color-accent); }
  .lc-btn.is-warn { color: var(--color-warn); background: color-mix(in srgb, var(--color-warn) 12%, transparent); box-shadow: none; }
  .lc-turn { display: grid; }
  .lc-turn.is-turning { animation: lc-turn 0.8s linear infinite; }
  @keyframes lc-turn { to { transform: rotate(360deg); } }

  /* The others on this computer, inside the card. */
  .lc-rest {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid color-mix(in srgb, var(--color-edge) 60%, transparent);
  }
  .ls-row {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 11px;
    padding: 7px 10px;
    border-radius: 12px;
    text-align: left;
    transition: background-color 0.15s ease;
  }
  .ls-row.is-running:hover { background: rgb(255 255 255 / 0.045); }
  .ls-row.is-absent { opacity: 0.8; }
  .ls-use { flex-shrink: 0; font-size: 11px; font-weight: 600; color: var(--color-faint); transition: color 0.15s ease; }
  .ls-row.is-running:hover .ls-use { color: var(--color-accent); }
  .ls-logo { position: relative; display: inline-flex; flex-shrink: 0; }
  .ls-logo.is-dim { opacity: 0.55; filter: grayscale(0.6); }
  /* The running dot sits on the corner of the logo, like a status badge. */
  .ls-logo .ls-dot {
    position: absolute;
    right: -3px;
    bottom: -3px;
    box-shadow: 0 0 0 2px var(--color-card);
  }
  .ls-dot {
    width: 9px;
    height: 9px;
    flex-shrink: 0;
    border-radius: 999px;
    background: var(--color-faint);
  }
  .ls-dot.is-on { background: var(--color-good); }
  .ls-dot.is-warn { background: var(--color-warn); }
  .ls-dot.is-off { background: var(--color-faint); }
  .ls-chip {
    flex-shrink: 0;
    padding: 1px 7px;
    border-radius: 999px;
    font-size: 10px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 13%, transparent);
  }
  .ls-chip.is-warn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--color-warn);
    background: color-mix(in srgb, var(--color-warn) 13%, transparent);
  }
  .ls-code {
    padding: 0.5px 5px;
    border-radius: 5px;
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 0.92em;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.07);
    overflow-wrap: anywhere;
  }

  /* ── Sections ────────────────────────────────────────────────────────── */
  .lc-sec { margin-bottom: 24px; }
  .lc-head { display: flex; align-items: baseline; gap: 10px; margin: 0 2px 9px; }
  .lc-head h3 {
    font-size: 11px;
    font-weight: 650;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--color-faint);
  }
  .lc-count { font-size: 11.5px; color: var(--color-faint); }
  .lc-empty { padding: 14px 4px; font-size: 12.5px; color: var(--color-faint); }
  .lc-err { margin: 2px 2px 10px; font-size: 12px; color: var(--color-bad); }
  /* The line behind the download: numbered, quieter than it, each one a click from leaving. */
  .lc-queue { display: flex; flex-direction: column; gap: 4px; margin: 10px 0 0; padding: 0; list-style: none; }
  .lc-queue-row {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 6px 6px 6px 8px;
    border-radius: 10px;
    font-size: 12px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.025);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.04);
  }
  .lc-queue-row em { font-style: normal; color: var(--color-faint); }
  .lc-queue-n {
    display: grid;
    width: 18px;
    height: 18px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 650;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .lc-queue-when { flex-shrink: 0; font-size: 11px; color: var(--color-faint); }
  .lc-queue-x {
    display: grid;
    width: 22px;
    height: 22px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 7px;
    color: var(--color-faint);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .lc-queue-x:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.07); }
  .lc-fix {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    margin: 2px 0 12px;
    padding: 9px 12px;
    border-radius: 12px;
    font-size: 12px;
    line-height: 1.45;
    color: var(--color-warn);
    background: color-mix(in srgb, var(--color-warn) 9%, transparent);
  }
  .lc-fix :global(svg) { flex-shrink: 0; margin-top: 2px; }
  .lc-fix.is-bad { color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 9%, transparent); }
  .lc-fix.is-good { color: var(--color-good); background: color-mix(in srgb, var(--color-good) 9%, transparent); }
  /* The way out offered under it: something smaller by the same maker that fits. */
  .lc-alt {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin: -4px 0 12px;
    padding: 10px 12px;
    border-radius: 12px;
    background: color-mix(in srgb, var(--color-accent) 9%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 35%, transparent);
    animation: lc-alt-in 0.45s var(--jelly);
  }
  @keyframes lc-alt-in { from { opacity: 0; transform: translateY(-4px) scale(0.98); } }
  .lc-alt-text { display: flex; min-width: 0; flex-direction: column; gap: 2px; font-size: 12px; color: var(--color-muted); }
  .lc-alt-text b { overflow: hidden; font-size: 12.5px; font-weight: 650; color: var(--color-ink); text-overflow: ellipsis; white-space: nowrap; }
  :global(:root[data-motion="off"]) .lc-alt { animation: none; }

  /* ── Getting a model ─────────────────────────────────────────────────── */
  .lc-get {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
    padding: 4px 4px 4px 12px;
    border-radius: 13px;
    border: 1px solid var(--color-edge);
    background: rgb(0 0 0 / 0.22);
    transition: border-color 0.15s var(--swift), box-shadow 0.15s var(--swift);
  }
  .lc-get:focus-within {
    border-color: color-mix(in srgb, var(--color-accent) 60%, transparent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 16%, transparent);
  }
  .lc-get-icon { display: grid; flex-shrink: 0; color: var(--color-faint); }
  .lc-get:focus-within .lc-get-icon { color: var(--color-accent); }
  .lc-get input {
    min-width: 0;
    flex: 1;
    padding: 6px 0;
    background: transparent;
    font-family: ui-monospace, monospace;
    font-size: 12.5px;
    color: var(--color-ink);
    outline: none;
  }
  .lc-get input::placeholder { font-family: inherit; color: var(--color-faint); }
  .lc-get-go {
    flex-shrink: 0;
    padding: 6px 14px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 650;
    color: var(--color-bg, #0b0d12);
    background: var(--color-accent);
    transition: opacity 0.15s ease, transform 0.3s var(--jelly), filter 0.15s ease;
  }
  .lc-get-go:hover:not(:disabled) { filter: brightness(1.08); }
  .lc-get-go:active:not(:disabled) { transform: scale(0.95); }
  .lc-get-go:disabled { opacity: 0.35; cursor: default; }
  /* Looking it up: the button stays lit with a spinner in it, and a light runs along the field, so a pause of ten
     seconds before the download reads as work, not a dead button. */
  .lc-get-go.is-asking { display: inline-flex; align-items: center; gap: 7px; opacity: 1; cursor: progress;
    animation: lc-ask-in 0.35s var(--jelly); }
  @keyframes lc-ask-in { from { transform: scale(0.9); } }
  .lc-get-spin {
    width: 12px;
    height: 12px;
    border-radius: 999px;
    border: 2px solid color-mix(in srgb, var(--color-bg, #0b0d12) 30%, transparent);
    border-top-color: var(--color-bg, #0b0d12);
    animation: lc-spin 0.7s linear infinite;
  }
  @keyframes lc-spin { to { transform: rotate(360deg); } }
  .lc-get { position: relative; overflow: hidden; }
  .lc-get.is-asking { border-color: color-mix(in srgb, var(--color-accent) 45%, transparent); }
  .lc-get.is-asking::after {
    content: "";
    position: absolute;
    inset: auto 0 0 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--color-accent), transparent) no-repeat;
    background-size: 40% 100%;
    animation: lc-ask-run 1.1s cubic-bezier(0.45, 0, 0.25, 1) infinite;
  }
  @keyframes lc-ask-run { from { background-position: -60% 0; } to { background-position: 160% 0; } }
  :global(:root[data-motion="off"]) .lc-get-go.is-asking,
  :global(:root[data-motion="off"]) .lc-get.is-asking::after { animation: none; }
  .lc-try { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 0 2px 12px; font-size: 11.5px; color: var(--color-faint); }
  .lc-try button {
    padding: 2px 9px;
    border-radius: 999px;
    font-family: ui-monospace, monospace;
    font-size: 11px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .lc-try button:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.09); }
  .lc-try-note { flex-basis: 100%; }
  /* Where the box would be, for a server that gets its models some other way: the same shape, quieter. */
  .lc-get-else {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
    padding: 9px 12px;
    border-radius: 13px;
    border: 1px dashed var(--color-edge);
    font-size: 12px;
    line-height: 1.45;
    color: var(--color-muted);
  }

  /* The download: its speed and time left, over a bar with light running along it. */
  .lc-pull {
    margin-bottom: 10px;
    padding: 11px 12px 12px;
    border-radius: 14px;
    background: color-mix(in srgb, var(--color-accent) 6%, rgb(255 255 255 / 0.02));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 22%, transparent);
  }
  .lc-pull-top { display: flex; align-items: center; gap: 10px; }
  .lc-pull-icon {
    display: grid;
    width: 30px;
    height: 30px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 9px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
    animation: lc-drop 1.6s ease-in-out infinite;
  }
  @keyframes lc-drop { 50% { transform: translateY(2px); } }
  .lc-pull-name, .lc-pull-sub { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .lc-pull-name { font-size: 13px; font-weight: 600; color: var(--color-ink); }
  .lc-pull-name em { font-style: normal; font-weight: 500; color: var(--color-faint); }
  .lc-pull-sub { margin-top: 1px; font-size: 11.5px; color: var(--color-muted); font-variant-numeric: tabular-nums; }
  .lc-pull-pct {
    flex-shrink: 0;
    font-size: 18px;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: var(--color-ink);
    font-variant-numeric: tabular-nums;
  }
  .lc-pull-pct small { margin-left: 1px; font-size: 11px; font-weight: 600; color: var(--color-faint); }
  .lc-bar {
    position: relative;
    height: 6px;
    margin-top: 10px;
    overflow: hidden;
    border-radius: 999px;
    background: rgb(255 255 255 / 0.06);
  }
  .lc-bar-fill {
    position: relative;
    height: 100%;
    overflow: hidden;
    border-radius: 999px;
    background: linear-gradient(90deg, color-mix(in srgb, var(--color-accent) 70%, transparent), var(--color-accent));
    box-shadow: 0 0 12px -2px color-mix(in srgb, var(--color-accent) 70%, transparent);
    transition: width 0.6s var(--swift);
  }
  .lc-bar-fill::after {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg, transparent, rgb(255 255 255 / 0.35), transparent);
    transform: translateX(-100%);
    animation: lc-shine 1.8s ease-in-out infinite;
  }
  @keyframes lc-shine { to { transform: translateX(100%); } }

  /* ── The models ──────────────────────────────────────────────────────── */
  .lm-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .lm-row {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 4px;
    border-radius: 13px;
    background: rgb(255 255 255 / 0.025);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.04);
    transition: opacity 0.2s ease;
  }
  .lm-row.is-going { opacity: 0.5; }
  .lm-main {
    display: flex;
    min-width: 0;
    flex: 1;
    align-items: center;
    gap: 11px;
    padding: 7px 10px 7px 8px;
    border-radius: 10px;
    color: inherit;
    text-decoration: none;
    transition: background-color 0.15s ease;
  }
  a.lm-main:hover { background: rgb(255 255 255 / 0.05); }
  a.lm-main:focus-visible { outline: 2px solid var(--color-accent); outline-offset: -2px; }
  .lm-site {
    width: 24px;
    height: 24px;
    flex-shrink: 0;
    object-fit: contain;
  }
  .lm-site.is-plain {
    display: grid;
    place-items: center;
    border-radius: 7px;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.05);
  }
  .lm-title,
  .lm-sub {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .lm-title { font-size: 13px; color: var(--color-ink); }
  .lm-sub { margin-top: 1px; font-size: 11px; color: var(--color-faint); }
  .lm-go {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    color: var(--color-faint);
    transition: color 0.15s ease;
  }
  .lm-go-label {
    max-width: 0;
    overflow: hidden;
    white-space: nowrap;
    opacity: 0;
    transition: max-width 0.22s ease, opacity 0.15s ease;
  }
  a.lm-main:hover .lm-go,
  a.lm-main:focus-visible .lm-go { color: var(--color-accent); }
  a.lm-main:hover .lm-go-label,
  a.lm-main:focus-visible .lm-go-label { max-width: 110px; opacity: 1; }
  .lm-used, .lm-mem {
    flex-shrink: 0;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 600;
  }
  .lm-used {
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .lm-mem {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    color: var(--color-good);
    background: color-mix(in srgb, var(--color-good) 12%, transparent);
  }
  .lm-mem i {
    width: 6px;
    height: 6px;
    border-radius: 999px;
    background: currentColor;
    animation: lc-breathe 2.4s ease-in-out infinite;
  }
  @keyframes lc-breathe { 50% { opacity: 0.35; } }
  .lm-folder {
    display: grid;
    width: 34px;
    height: 34px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 10px;
    color: var(--color-muted);
    transition: color 0.15s ease, background-color 0.15s ease;
  }
  .lm-folder:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.06); }
  .lm-folder:disabled { opacity: 0.5; }
  .lm-folder.is-bin:hover:not(:disabled) { color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 12%, transparent); }
  /* Asked once: the bin grows into the question. */
  .lm-sure {
    display: inline-flex;
    height: 34px;
    flex-shrink: 0;
    align-items: center;
    gap: 6px;
    padding: 0 12px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 650;
    white-space: nowrap;
    color: #fff;
    background: var(--color-bad);
    animation: lc-sure 0.35s var(--jelly) both;
  }
  @keyframes lc-sure { from { transform: scale(0.6); opacity: 0; } }

  /* ── Settings ────────────────────────────────────────────────────────── */
  .lc-set {
    border-radius: 16px;
    background: rgb(255 255 255 / 0.025);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
  }
  .lc-row {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 14px 16px;
  }
  .lc-row + .lc-row { border-top: 1px solid color-mix(in srgb, var(--color-edge) 55%, transparent); }
  .lc-row.is-wrap { flex-wrap: wrap; }
  .lc-row.is-stack { flex-direction: column; align-items: stretch; gap: 8px; }
  .lc-row.is-stack .lc-row-text { flex: none; }
  .lc-row-text { min-width: 0; flex: 1 1 240px; }
  .lc-row-text b { display: block; font-size: 13px; font-weight: 550; color: var(--color-ink); }
  .lc-row-text p { margin-top: 2px; font-size: 11.5px; line-height: 1.5; color: var(--color-faint); }
  .lc-ctx { display: flex; flex: 0 1 330px; min-width: 260px; flex-direction: column; gap: 8px; }
  .lc-ctx :global(.sg-btn) { height: 30px; font-size: 12px; }
  .lc-ctx-foot { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; font-size: 11.5px; color: var(--color-faint); }
  .lc-addr { display: flex; gap: 8px; }
  .lc-note { display: flex; align-items: center; gap: 6px; font-size: 11.5px; }
  .lc-note.is-good { color: var(--color-good); }
  .lc-note.is-good i { width: 6px; height: 6px; border-radius: 999px; background: currentColor; }
  .lc-note.is-warn { color: var(--color-warn); }
  .lc-note.is-bad { color: var(--color-bad); }
  .lc-save { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding-top: 2px; font-size: 11px; color: var(--color-faint); }

  /* The key, with its mark inside the box. */
  .ls-key { position: relative; display: block; color: var(--color-faint); }
  .ls-key > :global(svg) { position: absolute; top: 50%; left: 10px; transform: translateY(-50%); pointer-events: none; }
  .ls-key input { padding-left: 2rem; }
  .ls-key.is-wanted { color: var(--color-warn); }
  .ls-key.is-wanted input { border-color: color-mix(in srgb, var(--color-warn) 55%, transparent); }

  /* ── Every other server it works with ───────────────────────────────── */
  .ls-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .ls-tile {
    display: inline-flex;
    min-width: 0;
    align-items: center;
    gap: 7px;
    padding: 5px 11px 5px 6px;
    border-radius: 999px;
    text-align: left;
    background: rgb(255 255 255 / 0.025);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 55%, transparent);
    transition: background-color 0.15s ease, box-shadow 0.15s ease, transform 0.35s var(--jelly);
  }
  .ls-tile :global(.ptile) { filter: saturate(0.7); opacity: 0.8; transition: filter 0.15s ease, opacity 0.15s ease; }
  .ls-tile:hover { background: rgb(255 255 255 / 0.05); }
  .ls-tile:hover :global(.ptile),
  .ls-tile.is-open :global(.ptile) { filter: none; opacity: 1; }
  .ls-tile:active { transform: scale(0.96); }
  .ls-tile:focus-visible { outline: none; box-shadow: inset 0 0 0 1px var(--color-accent), 0 0 0 3px color-mix(in srgb, var(--color-accent) 25%, transparent); }
  .ls-tile.is-open {
    background: color-mix(in srgb, var(--color-accent) 10%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 45%, transparent);
  }
  .ls-tile-name {
    min-width: 0;
    overflow: hidden;
    font-size: 12px;
    color: var(--color-muted);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ls-tile:hover .ls-tile-name,
  .ls-tile.is-open .ls-tile-name { color: var(--color-ink); }
  /* How to turn one on, opened under the chips. */
  .ls-card {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    margin-top: 10px;
    padding: 12px 14px;
    border-radius: 14px;
    background: rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 22%, transparent);
    animation: ls-card-in 0.3s var(--swift) both;
  }
  @keyframes ls-card-in {
    from { opacity: 0; transform: translateY(-4px); }
  }

  /* Narrow: the card's actions and the address stack under what they belong to. */
  @media (max-width: 560px) {
    .lc-actions { margin-left: 0; }
    .lc-addr { flex-direction: column; }
    .lc-ctx { min-width: 0; flex-basis: 100%; }
  }

  :global(:root[data-motion="off"]) .ls-tile,
  :global(:root[data-motion="off"]) .ls-card,
  :global(:root[data-motion="off"]) .lc-logo::after,
  :global(:root[data-motion="off"]) .lc-pull-icon,
  :global(:root[data-motion="off"]) .lc-bar-fill::after,
  :global(:root[data-motion="off"]) .lm-mem i,
  :global(:root[data-motion="off"]) .lm-sure,
  :global(:root[data-motion="off"]) .lc-skel-hero,
  :global(:root[data-motion="off"]) .lc-skel-row { transition: none; animation: none; }
</style>
