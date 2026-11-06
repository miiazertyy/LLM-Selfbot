<script lang="ts">
  /**
   * Settings, as tabs with subtabs inside them.
   *
   * The tree lives in lib/settingsmap.ts, which explains why it is shaped the
   * way it is. This file renders it: the tab rail, the subtab strip, the control
   * for each field, and saving.
   *
   * There is no "show more advanced settings" disclosure any more. Every subtab
   * is small enough to show whole, which was the only reason the disclosure
   * existed.
   */
  import { onDestroy, onMount, tick, untrack } from "svelte";
  import { get } from "svelte/store";
  import { api } from "../lib/api";
  import { track } from "../lib/busy";
  import { toast, settingsSection, settingsPath, settingsScope, health } from "../lib/stores";
  import PersonaScope from "../lib/personas/PersonaScope.svelte";
  import { personasRes, reloadPersonas } from "../lib/personas/store";
  import { providePersona } from "../lib/personas/context";
  import { colorOf, shortValue } from "../lib/personas/logic";
  import { loadProviders, planPersona } from "../lib/providers";
  import { play } from "../lib/uisound";
  import StatusDot from "../lib/components/StatusDot.svelte";
  import Appearance from "../lib/components/Appearance.svelte";
  import { TABS, PATHS, homeOf, restHomeOf, resolveTarget, type Tab, type Sub } from "../lib/settingsmap";
  import Button from "../lib/components/Button.svelte";
  import Toggle from "../lib/components/Toggle.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import EnvEditor from "../lib/components/EnvEditor.svelte";
  import WaitTimes from "../lib/components/WaitTimes.svelte";
  import HourRange from "../lib/components/HourRange.svelte";
  import Dial from "../lib/components/Dial.svelte";
  import TypingSpeed from "../lib/components/TypingSpeed.svelte";
  import Tape from "../lib/components/Tape.svelte";
  import Odometer from "../lib/components/Odometer.svelte";
  import { isTimeUnit } from "../lib/durations";
  import { countScale, timeScale } from "../lib/dialscale";
  import { autowidth } from "../lib/autowidth";
  import { localZone } from "../lib/clock";
  import TimezonePicker from "../lib/components/TimezonePicker.svelte";
  import LanguagePicker from "../lib/components/LanguagePicker.svelte";
  import { DISCORD_LOCALES, COMMON_LANGUAGES, allLanguages } from "../lib/languages";
  import { scrub, timeStep } from "../lib/scrub";
  import ListEditor from "../lib/components/ListEditor.svelte";
  import ModelPicker from "../lib/components/ModelPicker.svelte";
  import Select from "../lib/components/Select.svelte";
  import { springValue } from "../lib/spring";
  import { hscroll } from "../lib/hscroll";
  import { glide } from "../lib/glide";
  import FootNote from "../lib/components/FootNote.svelte";
  import SnapchatSetup from "../lib/components/SnapchatSetup.svelte";
  import MinecraftSetup from "../lib/components/MinecraftSetup.svelte";
  import ImessageSetup from "../lib/components/ImessageSetup.svelte";
  import PlatformReady from "../lib/components/PlatformReady.svelte";
  import TelegramPanel from "../lib/components/TelegramPanel.svelte";
  import SwitchDemo from "../lib/components/SwitchDemo.svelte";
  import { hasDemo } from "../lib/switchdemos";
  import SettingsFile from "../lib/components/SettingsFile.svelte";
  import { menu as contextMenu, copyText, type MenuEntry } from "../lib/contextmenu";
  import { cascade } from "../lib/cascade";
  import { sweep } from "../lib/arrive";
  import NotHere from "../lib/components/NotHere.svelte";
  import LocalAI from "../lib/components/LocalAI.svelte";
  import CallSetup from "../lib/components/CallSetup.svelte";
  import ModelsPanel from "../lib/components/ModelsPanel.svelte";
  import ModelsHero from "../lib/components/ModelsHero.svelte";
  import ProvidersPanel from "../lib/components/ProvidersPanel.svelte";
  import UsagePanel from "../lib/components/UsagePanel.svelte";
  import PicturesPanel from "../lib/components/PicturesPanel.svelte";
  import TypingPreview from "../lib/components/TypingPreview.svelte";
  import LiveDemo from "../lib/components/LiveDemo.svelte";
  import { resource } from "../lib/resource";
  import { lastUsed, startUseLive } from "../lib/settinguse";
  import { platformOn, refreshSocials, socialsOn } from "../lib/socials";
  import { PLATFORMS, type PlatformId } from "../lib/platforms";

  type FieldDef = {
    key: string;
    label: string;
    type: string;
    section: string;
    requires_restart?: boolean;
    description?: string;
    common?: boolean;
    min?: number;
    max?: number;
    step?: number;
    /** What the app uses when config.yaml does not say; null where blank means "not sent". */
    default?: any;
    /** A feature (app/utils/compat.py) this needs: the row warns where it does not work. */
    needs?: string;
    current: any;
    /** The same for every persona (app/utils/personas.py GLOBAL_ONLY): saved to everyone's whatever the scope. */
    global_only?: boolean;
    /** Set to a persona: whether this is its own value, and what everyone has. */
    overridden?: boolean;
    base?: any;
  };

  // ── Whose settings ────────────────────────────────────────────────────────
  // Everyone's ("", config.yaml: what every persona starts from), or one persona's own on top of them. Picked with
  // the pill by the search, or arrived at from a persona's "Change settings for" (settingsScope). Not kept between
  // visits: Settings opens on everyone's, so nobody changes one persona's settings thinking they are everyone's.
  let scope = $state("");
  const cast = $derived($personasRes.data.personas);
  const scopePersona = $derived(cast.find((p) => p.id === scope) ?? null);
  const scopeName = $derived(scopePersona?.name ?? "");
  const scopeColor = $derived(colorOf(scopePersona));
  let scopeShake = $state(false);
  // The panels below (Pictures, Models) work on it too; they are made again for another (the {#key} round them).
  providePersona(() => scope);

  // Held outside the page like every other tab's data, one per scope. The schema is the
  // slowest thing in the panel to build cold, and rebuilding it on every visit
  // meant a blank Settings each time - including the first, which the startup
  // warm-up now covers (lib/warm.ts).
  // Typed explicitly: api.schema() returns any, which would otherwise make the
  // whole field list any and switch type checking off for this page.
  function schemaOf(s: string) {
    return resource<{ fields: FieldDef[] }>(
      s ? `settingsSchema:${s}` : "settingsSchema", () => api.schema(s), { fields: [] as FieldDef[] });
  }
  const schema = $derived(schemaOf(scope));

  /** Another scope: only with nothing unsaved, which would otherwise be saved to the wrong one. */
  async function setScope(next: string) {
    if (next === scope) return;
    if (changed) {
      toast("Save or undo first.", "info");
      scopeShake = false;
      await tick();
      scopeShake = true;
      setTimeout(() => (scopeShake = false), 450);
      return;
    }
    applyScope(next);
  }
  function applyScope(next: string) {
    // The plan the Models panels show follows it, set before they are made again and load it.
    planPersona.set(next);
    scope = next;
    rawOpen = false;
    // What is held for it is shown at once, and asked for again behind it: its own values change on the Personas page.
    schemaOf(next).refresh({ force: true }).then(() => {
      if (scope === next) loadError = $schema.error;
    });
  }
  // "Change settings for" on a persona: arrives set to it.
  $effect(() => {
    const want = $settingsScope;
    if (!want) return;
    settingsScope.set("");
    untrack(() => {
      if (!changed && want !== scope) applyScope(want);
    });
  });
  // A persona deleted while it is shown: everyone's again.
  $effect(() => {
    if (scope && $personasRes.fetched && !cast.some((p) => p.id === scope)) untrack(() => applyScope(""));
  });
  onDestroy(() => {
    if (get(planPersona)) {
      planPersona.set("");
      loadProviders().catch(() => {});
    }
  });
  const fields = $derived($schema.data?.fields ?? []);
  let dirty = $state<Record<string, any>>({});
  let saving = $state(false);
  const loading = $derived($schema.loading);
  let loadError = $state("");
  let raw = $state("");
  let rawOpen = $state(false);
  let query = $state("");

  // Where you were last time, so coming back lands on the thing you were
  // changing rather than on the first tab.
  let path = $state($settingsPath);
  $effect(() => {
    settingsPath.set(path);
  });

  /** The tabs shown: a social switched off has none (lib/socials.ts). Its tab's id is the platform's. */
  const tabs = $derived(TABS.filter((t) => platformOn($socialsOn, t.id)));
  /** The tabs that open a run (settingsmap's ORDER): a hairline above each sets the runs apart. Computed over the
      tabs actually shown, so a social switched off never leaves a hairline with nothing under it. */
  const runStarts = $derived(
    new Set(tabs.filter((t, i) => i > 0 && t.group !== tabs[i - 1].group).map((t) => t.id)),
  );
  const tabShown = (id: string | undefined) => !!id && tabs.some((t) => t.id === id);
  const tab = $derived(tabs.find((t) => t.id === path.split("/")[0]) ?? tabs[0]);
  const sub = $derived(tab.subs.find((s) => s.id === path.split("/")[1]) ?? tab.subs[0]);

  const changed = $derived(Object.keys(dirty).length);
  const searching = $derived(query.trim().length > 0);

  /** The field scan runs one beat behind the input: it walks every setting,
      lowercasing label, key and description for each one. */
  let queryDebounced = $state("");
  $effect(() => {
    const v = query;
    const t = setTimeout(() => { queryDebounced = v; }, 120);
    return () => clearTimeout(t);
  });

  /** Every field, by key, so the tree can pull them out in its own order. */
  const byKey = $derived.by(() => {
    const out: Record<string, FieldDef> = {};
    for (const f of fields) out[f.key] = f;
    return out;
  });

  /**
   * The fields a subtab shows.
   *
   * A key the tree names but config.yaml does not have is skipped rather than
   * rendered as an empty row: bot.groq_tts_model only exists once voice
   * messages have been set up, for instance.
   */
  function fieldsFor(t: Tab, s: Sub): FieldDef[] {
    if (s.rest) {
      const want = `${t.id}/${s.id}`;
      return fields.filter((f) => !homeOf(f.key) && restHomeOf(f.key) === want);
    }
    const list = (s.keys ?? []).map((k) => byKey[k]).filter(Boolean);
    // A platform's second switch is drawn by its first (see BOTH).
    return list.filter((f) => !list.some((g) => BOTH[g.key] === f.key));
  }

  /**
   * A platform has two switches in config.yaml, services.X.enabled and
   * X.enabled, and starts only when both are on. That was two rows, with a
   * note saying both had to be on. Now it is one switch drawn over both: on
   * when both are, and turning it sets both.
   */
  const BOTH: Record<string, string> = {
    "services.discord.enabled": "discord.enabled",
    "services.snapchat.enabled": "snapchat.enabled",
    "services.tiktok.enabled": "tiktok.enabled",
    "services.instagram.enabled": "instagram.enabled",
    "services.x.enabled": "x.enabled",
    "services.reddit.enabled": "reddit.enabled",
    "services.whatsapp.enabled": "whatsapp.enabled",
    "services.minecraft.enabled": "minecraft.enabled",
    "services.imessage.enabled": "imessage.enabled",
    "services.telegram_accounts.enabled": "telegram.enabled",
  };
  /** Which social a switch is: its row has the social's own mark beside it. */
  const SOCIAL_OF: Record<string, PlatformId> = Object.fromEntries(Object.entries(BOTH).flatMap(([a, b]) => {
    const id = b.split(".")[0] as PlatformId;
    return [[a, id], [b, id]];
  }));
  /** The other rows of What runs, with a mark of their own so the column of names lines up. */
  const RUN_MARK: Record<string, string> = {
    "services.telegram.enabled": "chats",
    "services.webui.enabled": "monitor",
    "services.webui.port": "link",
    "services.webui.bind": "globe",
  };
  const PARTNER: Record<string, string> = {
    ...BOTH, ...Object.fromEntries(Object.entries(BOTH).map(([a, b]) => [b, a])),
  };
  const partnerOf = (f: FieldDef): FieldDef | null => (PARTNER[f.key] ? byKey[PARTNER[f.key]] ?? null : null);

  const shown = $derived(fieldsFor(tab, sub));

  /**
   * A subtab's rows go on the page a few at a time: the first ones at once,
   * the rest a handful a frame after that. Every row mounted in one go (a
   * page of dials, clocks and charts) was one long frame that the opening
   * animation stuttered through. What arrives after the first frame still
   * drops in with the rest (lib/cascade.ts takes in blocks that turn up
   * while it runs), and it is below the fold by then anyway.
   */
  const FIRST_ROWS = 4;
  let grown = $state<{ path: string; n: number }>({ path: "", n: FIRST_ROWS });
  const drawnRows = $derived(grown.path === path ? grown.n : FIRST_ROWS);
  $effect(() => {
    const p = path;
    // Tracked, this one: the settings arrive after this first runs. It used to be read inside the loop, found none, and
    // stopped there for good, so the subtab Settings opened on showed six rows until another was picked.
    const total = rowsOf(shown).length;
    let n = untrack(() => (grown.path === p ? grown.n : FIRST_ROWS));
    let raf = 0;
    untrack(() => (grown = { path: p, n }));
    if (n >= total) return;
    const more = () => {
      n += 2;
      grown = { path: p, n };
      if (n < total) raf = requestAnimationFrame(more);
    };
    // After the first frame with the first rows is on screen.
    raf = requestAnimationFrame(() => (raf = requestAnimationFrame(more)));
    return () => cancelAnimationFrame(raf);
  });

  /**
   * An icon for each subtab, so the strip can be scanned by shape as well as
   * read. Keyed on the subtab id; anything unlisted gets the tab's own icon.
   */
  const SUB_ICONS: Record<string, string> = {
    tokens: "key", keys: "key", logins: "key", env: "key",
    replies: "chats", followups: "chats", telegram: "chats",
    triggers: "terminal", friends: "accounts", profiles: "accounts",
    presence: "eye", fingerprint: "system", browser: "system", local: "monitor", comments: "chats", live: "speaker",
    "live-answers": "chats", "live-style": "sparkle", "live-overlay": "monitor",
    watching: "eye", engage: "heart", visits: "external", foryou: "play", posting: "send", videos: "play",
    setup: "upload", pacing: "refresh", timing: "refresh",
    models: "sparkle", summaries: "sparkle", motion: "sparkle",
    style: "persona", human: "memory", media: "pictures", typing: "keyboard",
    services: "play", panel: "dashboard", alerts: "alert", usage: "stats",
    theme: "palette", typeface: "edit", rest: "more",
    texting: "chats", who: "accounts", pace: "refresh", mac: "monitor", itself: "persona", web: "globe",
  };
  const subIcon = (t: Tab, s: Sub) => SUB_ICONS[s.id] ?? t.icon;
  /** The TikTok subtabs of its own LIVE: the practice LIVE is under each of them. */
  const LIVE_SUBS = new Set(["live", "live-answers", "live-style", "live-overlay"]);

  /** How many settings a subtab holds; null for the ones that are a panel. */
  function subCount(t: Tab, s: Sub): number | null {
    if (s.panel) return null;
    return rowsOf(fieldsFor(t, s)).length;
  }

  /**
   * Settings that are the two ends of one range. Each pair is one row, with
   * one dial and a hand for each end, instead of a "min" row and a "max" row
   * that read as two unrelated numbers and could be set the wrong way round.
   */
  type Pair = { max: string; label: string; description: string; names: [string, string]; hint: string };
  const PAIRS: Record<string, Pair> = {
    "bot.typing.wpm_min": {
      max: "bot.typing.wpm_max", label: "Typing speed", names: ["Slowest", "Fastest"], hint: "",
      description: "How fast it types, in words per minute. 30 to 72 is a normal person; much past 90 looks like pasting.",
    },
    "bot.typing.think_min": {
      max: "bot.typing.think_max", label: "Thinking before typing", names: ["At least", "At most"], hint: "random in between",
      description: "How long it waits after reading before it starts typing.",
    },
    "bot.read_delay_dm_min": {
      max: "bot.read_delay_dm_max", label: "Reading a DM", names: ["At least", "At most"], hint: "random in between",
      description: "How long before it reads a DM. People see read receipts in DMs, so this one shows.",
    },
    "bot.read_delay_group_min": {
      max: "bot.read_delay_group_max", label: "Reading a group chat", names: ["At least", "At most"], hint: "random in between",
      description: "How long before it reads a message in a group chat.",
    },
    "bot.read_delay_server_min": {
      max: "bot.read_delay_server_max", label: "Reading a server message", names: ["At least", "At most"], hint: "random in between",
      description: "How long before it reads a message in a server.",
    },
    "bot.global_cooldown_min": {
      max: "bot.global_cooldown_max", label: "Pause between replies", names: ["At least", "At most"], hint: "random in between",
      description: "The pause between any two replies, to anyone.",
    },
    "bot.friend_requests.accept_delay_min": {
      max: "bot.friend_requests.accept_delay_max", label: "Wait before accepting", names: ["Soonest", "Latest"], hint: "random in between",
      description: "How long it waits before accepting a friend request.",
    },
    "bot.status.change_interval_min": {
      max: "bot.status.change_interval_max", label: "Time between status changes", names: ["At least", "At most"], hint: "random in between",
      description: "How long a status stays before it changes.",
    },
    "snapchat.min_send_gap_ms": {
      max: "snapchat.max_send_gap_ms", label: "Gap between sends", names: ["At least", "At most"], hint: "random in between",
      description: "How long it leaves between two sends.",
    },
    "tiktok.min_send_gap_ms": {
      max: "tiktok.max_send_gap_ms", label: "Gap between sends", names: ["At least", "At most"], hint: "random in between",
      description: "How long it leaves between two sends. TikTok limits fast senders.",
    },
  };
  /** The far end of each pair, to its near end. */
  const NEAR_OF: Record<string, string> = Object.fromEntries(Object.entries(PAIRS).map(([k, p]) => [p.max, k]));
  /** A pair drawn as one row, when both its ends are settings this config has. */
  const pairOf = (f: FieldDef) => (PAIRS[f.key] && byKey[PAIRS[f.key].max] ? PAIRS[f.key] : null);
  /** The rows of a list: a pair is one row, where the first of its two ends comes, even when only one matched a search. */
  /**
   * A row that only means something given another's value, and is left out otherwise: under Automatic, the box for
   * Discord's build number is a number nobody should touch, sitting right under the choice that says not to.
   */
  const ONLY_IF: Record<string, () => boolean> = {
    "bot.desktop.build_number": () => {
      const source = byKey["bot.desktop.build_source"];
      return !source || value(source) === "custom";
    },
  };

  function rowsOf(list: FieldDef[]): FieldDef[] {
    const out: FieldDef[] = [];
    const seen = new Set<string>();
    for (const f of list) {
      const near = NEAR_OF[f.key] && byKey[NEAR_OF[f.key]] ? byKey[NEAR_OF[f.key]] : f;
      if (seen.has(near.key) || ONLY_IF[near.key]?.() === false) continue;
      seen.add(near.key);
      out.push(near);
    }
    return out;
  }

  /**
   * The least a time dial should reach, in the setting's unit, where fitting
   * the dial to the value would make it too small: a value of 0 ("off") would
   * otherwise get a dial to ten seconds. Every other dial fits its value.
   */
  const DIAL_TOP: Record<string, number> = {
    "bot.late_reply.threshold": 3600,
    "snapchat.verify_wait_ms": 600000,
    "snapchat.reload_interval_ms": 7200000,
    "tiktok.reload_interval_ms": 7200000,
  };
  /** Counts on a dial, and what they count. */
  const COUNTS: Record<string, { one: string; many: string; hint: string }> = {
    "snapchat.max_recipients": { one: "chat", many: "chats", hint: "each look" },
    "bot.web.per_hour": { one: "lookup", many: "lookups", hint: "an hour, at most" },
    "bot.web.sessions_per_day": { one: "visit", many: "visits", hint: "a day" },
    "snapchat.max_sends_per_hour": { one: "send", many: "sends", hint: "an hour, at most" },
    "tiktok.max_recipients": { one: "chat", many: "chats", hint: "each look" },
    "tiktok.max_sends_per_hour": { one: "send", many: "sends", hint: "an hour, at most" },
    "tiktok.comments.per_hour": { one: "reply", many: "replies", hint: "an hour, at most" },
    "tiktok.comments.videos": { one: "video", many: "videos", hint: "its newest" },
    "tiktok.live.per_minute": { one: "answer", many: "answers", hint: "a minute, at most" },
    "tiktok.live.gift_min_coins": { one: "coin", many: "coins", hint: "a gift, at least" },
    "tiktok.live.max_per_viewer": { one: "answer", many: "answers", hint: "a viewer, each LIVE" },
    "tiktok.live.max_words": { one: "word", many: "words", hint: "an answer, at most" },
    "tiktok.engage.likes_per_day": { one: "like", many: "likes", hint: "a day, at most" },
    "tiktok.engage.comments_per_day": { one: "comment", many: "comments", hint: "a day, at most" },
    "tiktok.visits.lines_per_5min": { one: "line", many: "lines", hint: "every 5 minutes, at most" },
    "tiktok.visits.per_day": { one: "visit", many: "visits", hint: "a day, at most" },
    "tiktok.foryou.sessions_per_day": { one: "time", many: "times", hint: "a day, at most" },
    "tiktok.foryou.like_percent": { one: "in 100", many: "in 100", hint: "liked" },
    "tiktok.posting.per_day": { one: "post", many: "posts", hint: "a day, at most" },
    "bot.pictures.video_max_mb": { one: "MB", many: "MB", hint: "per video, at most" },
  };
  /**
   * Counts with no top, on a tape (Tape.svelte), and what they count. Any
   * other whole number with no top and no unit gets one too, bar the ones
   * that are not amounts at all.
   */
  const TAPES: Record<string, { one: string; many: string }> = {
    "bot.stale_reply.max_messages": { one: "newer message", many: "newer messages" },
    "bot.cache.max_messages": { one: "message", many: "messages" },
  };
  const NOT_AMOUNTS = new Set(["services.webui.port", "bot.desktop.build_number"]);
  const onTape = (f: FieldDef) => f.type === "int" && (f.key in TAPES
    || (f.max == null && !unitOf(f) && !NOT_AMOUNTS.has(f.key) && !f.key.endsWith("_id")));

  /** Quiet hours, wherever there are any: all on the same clock, and on this computer's time as all of them read it. */
  const QUIET_KEYS = new Set(["snapchat.quiet_hours", "tiktok.quiet_hours", "instagram.quiet_hours",
                              "x.quiet_hours", "reddit.quiet_hours", "whatsapp.quiet_hours",
                              "telegram.quiet_hours", "imessage.quiet_hours", "bot.calls.quiet_hours"]);
  /** Snapchat's quiet hours, said as what they are rather than as a night. */
  const QUIET_WORDS = {
    label: "Quiet hours", what: "quiet", none: "No quiet hours", on: "Quiet", off: "Sending",
    goesOn: "quiet", goesOff: "sends", starts: "Quiet from", ends: "Quiet until",
    moves: "Drag to move the whole quiet spell",
  };
  /** The same, for calls: outside its quiet hours it picks up rather than sends. */
  const CALL_QUIET_WORDS = { ...QUIET_WORDS, off: "Picking up", goesOff: "picks up" };

  /** The hours nudges may be sent in, said as a window rather than a night. */
  const NUDGE_WORDS = {
    label: "Nudge hours", what: "of nudging", none: "Never", on: "Nudging now", off: "Not now",
    goesOn: "starts", goesOff: "stops", starts: "From", ends: "Until",
    moves: "Drag to move the whole window",
  };

  /** What 0 means, for the settings where it is not simply no time at all. */
  const ZERO_SAYS: Record<string, string> = {
    "bot.memory_summary.refresh_minutes": "Never reused",
    "snapchat.verify_wait_ms": "No limit",
    "snapchat.reload_interval_ms": "Off",
    "tiktok.reload_interval_ms": "Off",
    "tiktok.live.reply_delay": "At once",
    "tiktok.live.viewer_cooldown": "Any time",
  };
  const num = (v: any) => (isFinite(Number(v)) ? Number(v) : 0);
  /** Both ends of a pair from its dial, writing only the end that moved. */
  function setPair(f: FieldDef, far: FieldDef, [a, b]: number[]) {
    if (a !== num(value(f))) setValue(f, a);
    if (b !== num(value(far))) setValue(far, b);
  }

  /**
   * The unit a number is in, read off its key or its description, which state
   * it consistently ("_ms", "in seconds", "_hours"). A bare "1800" said
   * nothing about whether it was seconds or minutes.
   */
  function unitOf(f: FieldDef): string {
    const k = f.key;
    const d = (f.description || "").toLowerCase();
    if (k.endsWith("_ms") || d.includes("milliseconds")) return "ms";
    if (k.endsWith("_minutes") || d.includes("in minutes")) return "min";
    if (k.endsWith("_hours") || d.includes("in hours")) return "h";
    if (k.endsWith("_days") || d.startsWith("days ")) return "days";
    if (d.includes("in seconds")) return "s";
    if (k.includes("wpm") || d.includes("words per minute")) return "wpm";
    return "";
  }

  /** "30 min", "2 h 15 min", "45 s" - a long number of seconds, readable. */
  function human(f: FieldDef, v: any): string {
    const n = Number(v);
    if (!n || !isFinite(n)) return "";
    const u = unitOf(f);
    const secs = u === "ms" ? n / 1000 : u === "s" ? n : u === "min" ? n * 60 : u === "h" ? n * 3600 : 0;
    if (!secs || (u === "s" && secs < 60) || (u === "min" && n < 60) || u === "h" || u === "days") {
      return u === "ms" && secs < 60 ? `${+secs.toFixed(1)} s` : "";
    }
    const d = Math.floor(secs / 86400), h = Math.floor((secs % 86400) / 3600);
    const m = Math.floor((secs % 3600) / 60), s = Math.round(secs % 60);
    const parts = [d && `${d} d`, h && `${h} h`, m && `${m} min`, !d && !h && s && `${s} s`].filter(Boolean);
    return parts.slice(0, 2).join(" ");
  }

  /**
   * Move an element to <body>. The page wrapper carries a transform (its enter
   * animation), and a transformed ancestor becomes the box that position:fixed
   * is measured against - so the save bar sat at the bottom of the page rather
   * than of the window, out of sight below the fold.
   */
  function toBody(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  /** A probability shown as one: 0.08 is "8%". */
  const isChance = (f: FieldDef) => /chance|probab/.test(f.key);
  const pct = (v: any) => `${Math.round(Number(v) * 1000) / 10}%`;

  /** Subtabs with nothing in them are not worth a tab. */
  function subVisible(t: Tab, s: Sub): boolean {
    if (s.panel) return true;
    return fieldsFor(t, s).length > 0;
  }

  const subs = $derived(tab.subs.filter((s) => subVisible(tab, s)));

  const results = $derived.by(() => {
    if (!searching) return [];
    const q = queryDebounced.trim().toLowerCase();
    if (!q) return [];
    return fields
      .filter(
        (f) =>
          (f.label.toLowerCase().includes(q) ||
            f.key.toLowerCase().includes(q) ||
            (f.description || "").toLowerCase().includes(q))
          && tabShown((homeOf(f.key) ?? restHomeOf(f.key) ?? "app/").split("/")[0]),
      )
      .slice(0, 60);
  });

  /** "Discord, Where it replies" for a search hit, so the result has a home. */
  function whereIs(key: string): string {
    const p = homeOf(key) ?? restHomeOf(key);
    const hit = PATHS.find((x) => x.path === p);
    return hit ? `${hit.tab.name}, ${hit.sub.name}` : "";
  }

  function goToKey(key: string) {
    const p = homeOf(key) ?? restHomeOf(key);
    if (p) {
      path = p;
      query = "";
    }
  }

  /** The settings the persona shown has of its own, counted per tab and subtab, for the dots in its colour. */
  const own = $derived.by(() => {
    const out: Record<string, number> = {};
    if (!scope) return out;
    for (const f of fields) {
      if (!f.overridden) continue;
      const p = homeOf(f.key) ?? restHomeOf(f.key);
      if (!p) continue;
      out[p] = (out[p] ?? 0) + 1;
      const t = p.split("/")[0];
      out[t] = (out[t] ?? 0) + 1;
    }
    return out;
  });
  /** Parts of Settings that are the app's, not a persona's: the same whichever is shown. */
  const GLOBAL_PANELS = new Set(["env", "local", "usage", "providers", "telegram", "snapchat-setup", "tiktok-setup",
                                 "instagram-setup", "x-setup", "reddit-setup", "whatsapp-setup",
                                 "minecraft-setup", "imessage-setup", "discord-setup", "telegram-setup", "theme", "typeface", "interface",
                                 "profiles"]);

  /** A persona's own value given up: it has everyone's again (a pair's two ends go together). */
  async function useEveryones(f: FieldDef, far: FieldDef | null) {
    if (!scope) return;
    play("undo");
    try {
      for (const x of far ? [f, far] : [f]) {
        if (x.overridden) await api.resetPersonaSetting(scope, x.key);
      }
    } catch (e: any) {
      toast(e?.message || "Could not do that", "err");
    }
    await schema.refresh({ force: true });
    reloadPersonas();
  }

  /** Unsaved changes, counted per tab and per subtab, for the dots. */
  const unsaved = $derived.by(() => {
    const out: Record<string, number> = {};
    for (const key of Object.keys(dirty)) {
      const p = homeOf(key) ?? restHomeOf(key);
      if (!p) continue;
      out[p] = (out[p] ?? 0) + 1;
      const t = p.split("/")[0];
      out[t] = (out[t] ?? 0) + 1;
    }
    return out;
  });

  /**
   * Settings that hold a Groq model id, and what each one needs the model to
   * be able to do. The picker only offers models with that capability: a
   * speech model cannot write replies and a text model cannot read an image,
   * and picking one fails on every request with an unhelpful error.
   */
  const MODEL_FIELDS: Record<string, string> = {
    "bot.groq_models": "chat",
    "bot.groq_small_model": "chat",
    "bot.groq_image_model": "vision",
    "bot.groq_whisper_model": "stt",
    "bot.groq_tts_model": "tts",
  };

  /**
   * Settings that only accept certain values.
   *
   * A free text box for "short, balanced or chatty" invites a typo that reads
   * as valid and silently falls back to the default.
   */
  // Exactly what Discord calls them. The shape of the dot says the rest, and
  // an explanation glued onto the name only makes the list harder to scan.
  /**
   * The voices each speech model offers, and the delivery tags it understands.
   *
   * Groq publishes models over the API but not the voices inside them, so
   * unlike the model pickers there is nothing to fetch: these come from the
   * model cards. Listing them still beats the alternative, which was reading
   * the docs to find out that the word to type is "diana".
   */
  const TTS_VOICES: Record<string, string[]> = {
    "canopylabs/orpheus-v1-english": ["autumn", "diana", "hannah", "austin", "daniel", "troy"],
    "canopylabs/orpheus-arabic-saudi": ["fahad", "huda", "sara", "yazeed"],
  };
  /** Whose voice each one is, for the line under its name. */
  const VOICE_KIND: Record<string, string> = {
    autumn: "Woman's voice", diana: "Woman's voice", hannah: "Woman's voice",
    austin: "Man's voice", daniel: "Man's voice", troy: "Man's voice",
    fahad: "Man's voice", huda: "Woman's voice", sara: "Woman's voice", yazeed: "Man's voice",
  };
  /** "diana" is what the model wants; "Diana" is how a name reads. */
  const voiceName = (v: string) => v.charAt(0).toUpperCase() + v.slice(1);
  const TTS_TONES = [
    "[casual]", "[warm]", "[calm]", "[cheerful]", "[excited]", "[serious]",
    "[soft]", "[whisper]", "[fast]", "[slow]", "[sad]", "[angry]",
    "[laugh]", "[sigh]", "[gasp]", "[sarcastic]",
  ];

  /** Voices belong to a model, so the list follows whatever is selected. */
  const ttsVoices = $derived.by(() => {
    const model = String(byKey["bot.groq_tts_model"]?.current || "").trim()
      || "canopylabs/orpheus-v1-english";
    return TTS_VOICES[model] ?? TTS_VOICES["canopylabs/orpheus-v1-english"];
  });

  /** "[casual]" is how the voice model wants it; "casual" is how it reads. */
  const toneName = (t: string) => t.replace(/^\[|\]$/g, "");

  function toggleTone(f: FieldDef, tone: string) {
    const current: string[] = Array.isArray(value(f)) ? value(f) : [];
    const next = current.includes(tone)
      ? current.filter((t) => t !== tone)
      : [...current, tone];
    setValue(f, next);
  }

  const PRESENCES = [
    { value: "online", label: "Online" },
    { value: "idle", label: "Idle" },
    { value: "dnd", label: "Do Not Disturb" },
    { value: "invisible", label: "Invisible" },
  ];

  // Each choice with a mark and a line saying what it does, so the list reads
  // at a glance instead of as bare words (Select draws them).
  type Choice = { value: string; label: string; hint?: string; icon?: string; mark?: string };
  const CHOICES: Record<string, Choice[]> = {
    "bot.desktop.build_source": [
      { value: "auto", label: "Automatic", hint: "Discord's current build, looked up", icon: "refresh" },
      { value: "custom", label: "Custom", hint: "The number you put in below", icon: "edit" },
    ],
    "telegram.gifts": [
      { value: "notify", label: "Tell me", hint: "It waits in Chats for you to accept", icon: "alert" },
      { value: "accept", label: "Accept it", hint: "Taken as it lands", icon: "check" },
      { value: "off", label: "Leave them", hint: "Nothing is said and nothing is taken", icon: "eyeOff" },
    ],
    "discord.gifts.mode": [
      { value: "notify", label: "Tell me", hint: "It waits in Chats for you to accept", icon: "alert" },
      { value: "accept", label: "Accept it", hint: "Taken as it lands, before it expires", icon: "check" },
      { value: "off", label: "Leave them", hint: "Nothing is said and nothing is taken", icon: "eyeOff" },
    ],
    "reddit.posting.where": [
      { value: "profile", label: "Its own profile", hint: "Always takes a post, whatever its karma", icon: "accounts" },
      { value: "subreddits", label: "The subreddits above", hint: "A young account may be refused", icon: "chats" },
    ],
    "bot.memory_summary.length": [
      { value: "short", label: "Short", hint: "A line or two", icon: "minimize" },
      { value: "medium", label: "Medium", hint: "A short paragraph", icon: "order" },
      { value: "detailed", label: "Detailed", hint: "Everything worth keeping", icon: "logs" },
    ],
    "bot.memory_summary.language": [
      { value: "auto", label: "Same as the chat", hint: "Whatever language they talk in", icon: "chats" },
      { value: "en", label: "English", mark: "🇬🇧" },
      { value: "fr", label: "French", mark: "🇫🇷" },
      { value: "es", label: "Spanish", mark: "🇪🇸" },
      { value: "de", label: "German", mark: "🇩🇪" },
      { value: "pt", label: "Portuguese", mark: "🇵🇹" },
      { value: "it", label: "Italian", mark: "🇮🇹" },
      { value: "ar", label: "Arabic", mark: "🇸🇦" },
      { value: "nl", label: "Dutch", mark: "🇳🇱" },
    ],
    "bot.calls.answer": [
      { value: "known", label: "People it knows", hint: "Anyone it has talked to", icon: "accounts" },
      { value: "anyone", label: "Anyone", hint: "Strangers too", icon: "globe" },
      { value: "nobody", label: "Nobody", hint: "Every call rings out", icon: "eyeOff" },
    ],
    "bot.message_style.mode": [
      { value: "short", label: "Short", hint: "One line, like a text", icon: "send" },
      { value: "balanced", label: "Balanced", hint: "A few sentences", icon: "chats" },
      { value: "chatty", label: "Chatty", hint: "Longer, several messages", icon: "sparkle" },
    ],
    "bot.web.search_with": [
      { value: "auto", label: "Automatic", hint: "Google, then DuckDuckGo. Free", icon: "globe" },
      { value: "google", label: "Google", hint: "In its own hidden browser", icon: "search" },
      { value: "duckduckgo", label: "DuckDuckGo", hint: "No browser needed", icon: "search" },
      { value: "brave", label: "Brave", hint: "Needs BRAVE_API_KEY", icon: "key" },
      { value: "tavily", label: "Tavily", hint: "Needs TAVILY_API_KEY", icon: "key" },
    ],
    "bot.client_profile": [
      { value: "web", label: "Web browser", hint: "Looks like Discord in Chrome", icon: "globe" },
      { value: "desktop", label: "Desktop app", hint: "Looks like the Discord app", icon: "monitor" },
    ],
    "tiktok.live.answer_mode": [
      { value: "all", label: "All of them", hint: "Any comment, at its pace", icon: "chats" },
      { value: "questions", label: "Questions", hint: "Questions, and lines that name it", icon: "info" },
      { value: "named", label: "When named", hint: "Only lines that name it", icon: "persona" },
    ],
    "tiktok.live.tone": [
      { value: "persona", label: "Its usual self", hint: "As the persona is", icon: "persona" },
      { value: "hype", label: "Hype", hint: "Loud and excited", mark: "🔥" },
      { value: "chill", label: "Chill", hint: "Calm and easy", mark: "🌙" },
      { value: "funny", label: "Funny", hint: "Jokes around", mark: "😂" },
      { value: "sweet", label: "Sweet", hint: "Warm and soft", mark: "🌸" },
    ],
    "tiktok.live.language": [
      { value: "viewer", label: "Theirs", hint: "Each viewer's own language", icon: "chats" },
      { value: "persona", label: "Its own", hint: "Always the persona's language", icon: "persona" },
    ],
    "tiktok.live.overlay_position": [
      { value: "bottom", label: "Bottom", hint: "Along the bottom", icon: "download" },
      { value: "middle", label: "Middle", hint: "In the middle", icon: "minimize" },
      { value: "top", label: "Top", hint: "Along the top", icon: "upload" },
    ],
    "tiktok.live.overlay_size": [
      { value: "small", label: "Small", hint: "Out of the way" },
      { value: "medium", label: "Medium", hint: "Easy to read" },
      { value: "large", label: "Large", hint: "Big and bold" },
    ],
    "tiktok.live.overlay_theme": [
      { value: "dark", label: "Dark", hint: "Dark glass, white text", mark: "⬛" },
      { value: "light", label: "Light", hint: "White card, dark text", mark: "⬜" },
      { value: "tiktok", label: "TikTok", hint: "Like TikTok's own chat", icon: "tiktok" },
    ],
    "tiktok.posting.privacy": [
      { value: "everyone", label: "Everyone", hint: "Anyone on TikTok", icon: "globe" },
      { value: "friends", label: "Friends", hint: "Followers it follows back", icon: "accounts" },
      { value: "only_me", label: "Only me", hint: "Nobody else", icon: "key" },
    ],
    "minecraft.auth": [
      { value: "offline", label: "No account", hint: "A LAN world, or online mode off", icon: "globe" },
      { value: "microsoft", label: "Microsoft", hint: "A real server, signed in once", icon: "key" },
    ],
    "minecraft.translate_versions": [
      { value: "auto", label: "When needed", hint: "Through ViaProxy for servers not on 1.21", icon: "refresh" },
      { value: "always", label: "Always", hint: "Every server through ViaProxy", icon: "globe" },
      { value: "off", label: "Never", hint: "Join every server directly", icon: "close" },
    ],
    "minecraft.persona": [
      { value: "brief", label: "Brief", hint: "A short telling, fits free models", icon: "minimize" },
      { value: "full", label: "Full", hint: "The whole persona, every time", icon: "persona" },
    ],
    "imessage.thread_replies": [
      { value: "late", label: "When needed", hint: "When others wrote since", icon: "chats" },
      { value: "always", label: "Always", hint: "Every answer in a thread", icon: "undo" },
      { value: "never", label: "Never", hint: "Always in the chat", icon: "close" },
    ],
    "imessage.send_method": [
      { value: "auto", label: "Automatic", hint: "The best the Mac has", icon: "refresh" },
      { value: "private-api", label: "Private API", hint: "Needs it on the Mac", icon: "key" },
      { value: "apple-script", label: "AppleScript", hint: "Works without it", icon: "terminal" },
    ],
    "services.webui.bind": [
      { value: "127.0.0.1", label: "This computer", hint: "Only this computer can open the panel", icon: "monitor" },
      { value: "0.0.0.0", label: "Local network", hint: "Phones on your Wi-Fi can open it too", icon: "globe" },
    ],
  };

  /**
   * The statuses Discord actually has.
   *
   * The rotation list used to be free text, so a typo ("onlien") was accepted
   * and silently never matched, leaving the account stuck on whatever it had.
   */
  const PRESENCE_KEYS = PRESENCES.map((p) => p.value);

  /**
   * Add or remove one status from the rotation pool.
   *
   * Kept in PRESENCE_KEYS order rather than click order, so the optional
   * weights list in config.yaml, which is positional, stays meaningful.
   * The last one cannot be removed: an empty pool leaves the runner with
   * nothing to pick and the account frozen on whatever it had.
   */
  function togglePresence(f: FieldDef, key: string) {
    const current: string[] = Array.isArray(value(f)) ? value(f) : [];
    const next = current.includes(key)
      ? current.filter((v) => v !== key)
      : [...current, key];
    if (!next.length) return;
    setValue(f, PRESENCE_KEYS.filter((k) => next.includes(k)));
  }

  /**
   * Where a setting left blank really sits: the provider's own default, which
   * for these is the same nearly everywhere. Blank means "not sent".
   *
   * A range input handed null falls back to its midpoint, so a blank
   * temperature showed its thumb at 1, its fill at 0 and the word "null".
   * Then the thumb rested hollow on the provider's default, which put one in
   * the middle and another at the far end, and read as knobs left in random
   * places. Now a blank one has no knob at all, an empty track that says
   * "Default"; the value here is only where a click on it starts from.
   */
  const LEFT_BLANK: Record<string, number> = {
    "bot.sampling.temperature": 1,
    "bot.sampling.top_p": 1,
    "bot.sampling.frequency_penalty": 0,
    "bot.sampling.presence_penalty": 0,
  };
  const isBlank = (v: any) => v == null || v === "";
  /** A setting whose blank means "leave it to the provider", so it can be put back to blank. */
  const blankable = (f: FieldDef) => f.default === null || f.key in LEFT_BLANK;
  const restOf = (f: FieldDef) => LEFT_BLANK[f.key] ?? ((f.min ?? 0) + (f.max ?? 1)) / 2;

  /**
   * The filled part of a slider's track, as percentages from and to.
   *
   * A range input otherwise shows one flat line with no sense of where in the
   * range you are. A range either side of zero (the penalties, -2 to 2) fills
   * from zero, so a little less and a little more both look it.
   */
  function band(f: FieldDef): [number, number] {
    const lo = f.min ?? 0;
    const hi = f.max ?? 1;
    const v = Number(value(f));
    if (isBlank(value(f)) || !isFinite(v) || hi === lo) return [0, 0];
    const at = (x: number) => Math.max(0, Math.min(100, ((x - lo) / (hi - lo)) * 100));
    const origin = lo < 0 && hi > 0 ? 0 : lo;
    return [at(Math.min(origin, v)), at(Math.max(origin, v))];
  }

  function pickTab(t: Tab) {
    const first = t.subs.find((s) => subVisible(t, s)) ?? t.subs[0];
    path = `${t.id}/${first.id}`;
    query = "";
  }
  // On a social that has just been switched off, or was when this was last open: the first tab instead.
  $effect(() => {
    const id = path.split("/")[0];
    if (tabs.length && !tabShown(id)) untrack(() => pickTab(tabs[0]));
  });

  onMount(load);
  // The prefixes' rows light up when they are used, like the models' rows.
  onMount(startUseLive);

  // The dependency doctor and the health banners link straight to a setting.
  $effect(() => {
    const want = $settingsSection;
    if (!want) return;
    settingsSection.set("");
    const target = resolveTarget(want);
    if (target) {
      path = target;
      query = "";
    }
  });

  /** `fresh` after a save: what was just written, not the answer from a few seconds before it. */
  async function load(fresh = false) {
    // On opening, the warm-up or a previous visit usually means this returns
    // something to look at straight away.
    await schema.refresh(fresh === true ? { force: true } : { maxAge: 15000 });
    loadError = $schema.error;
    dirty = {};
  }

  const value = (f: FieldDef) => (f.key in dirty ? dirty[f.key] : f.current);

  /**
   * The versions the Minecraft bot plays (mineflayer's tested ones, 1.8.8 to 26.1), newest first, for its Game
   * version: the server's own when it says, each of these, or one typed in (Custom). A value typed earlier that is
   * not on the list shows as Custom, with it in the box.
   */
  const MC_VERSIONS: Choice[] = [
    { value: "auto", label: "Match the server", hint: "1.21.4, and ViaProxy for other servers", icon: "refresh" },
    { value: "26.1", label: "26.1", hint: "The newest it plays" },
    { value: "1.21.11", label: "1.21.11" },
    { value: "1.21.8", label: "1.21.8" },
    { value: "1.21.4", label: "1.21.4", hint: "The one it knows best" },
    { value: "1.21.1", label: "1.21.1" },
    { value: "1.20.6", label: "1.20.6" },
    { value: "1.20.4", label: "1.20.4" },
    { value: "1.20.1", label: "1.20.1" },
    { value: "1.19.4", label: "1.19.4" },
    { value: "1.18.2", label: "1.18.2" },
    { value: "1.17.1", label: "1.17.1" },
    { value: "1.16.5", label: "1.16.5" },
    { value: "1.12.2", label: "1.12.2" },
    { value: "1.8.8", label: "1.8.8", hint: "And 1.8.9 servers" },
    { value: "custom", label: "Custom", hint: "Type the version", icon: "edit" },
  ];
  const mcKnown = (v: string) => MC_VERSIONS.some((c) => c.value === v && c.value !== "custom");

  /** A value the way it reads in a row, for copying. */
  const plain = (v: unknown) => (v === null || v === undefined ? "" : typeof v === "string" ? v : JSON.stringify(v));

  /**
   * Right-click on a row: take back an unsaved change, put it back to what the
   * app ships with, or copy it. A pair (a min and a max) is one row, so both
   * ends go together.
   */
  function rowMenu(f: FieldDef, far: FieldDef | null): MenuEntry[] {
    const both = far ? [f, far] : [f];
    const changed = both.some((x) => x.key in dirty);
    const resettable = both.filter((x) => "default" in x && JSON.stringify(value(x)) !== JSON.stringify(x.default));
    return [
      { title: f.label },
      changed && { label: "Undo this change", icon: "undo", run: () => {
        const next = { ...dirty };
        for (const x of both) delete next[x.key];
        dirty = next;
      } },
      !!scope && !changed && both.some((x) => x.overridden) && { label: "Use everyone's", icon: "undo",
                                                              run: () => useEveryones(f, far) },
      resettable.length > 0 && { label: "Reset to default", icon: "refresh", run: () => {
        for (const x of resettable) setValue(x, x.default);
      } },
      "sep",
      { label: "Copy value", icon: "copy",
        run: () => copyText(both.map((x) => plain(value(x))).join(" - "), "Copied the value.") },
      { label: "Copy name", icon: "copy", run: () => copyText(f.label, "Copied the name.") },
    ];
  }
  const setValue = (f: FieldDef, v: any) => (dirty[f.key] = v);
  /** The clock the night hours are kept on: their own timezone, else the persona's. */
  const nightZone = () => {
    const own = byKey["bot.night_invisible.timezone"];
    const persona = byKey["bot.timezone"];
    return String((own && value(own)) || (persona && value(persona)) || "");
  };
  /** A number that is an amount (it has a unit or bounds) can be dragged; an id or a build number cannot. */
  const scrubbable = (f: FieldDef) => !!unitOf(f) || f.min != null || f.max != null;

  /** Discord's current build number, fetched when "Latest" is pressed. */
  let buildBusy = $state(false);
  let freshBuild = $state(false);
  async function latestBuild(f: FieldDef) {
    buildBusy = true;
    try {
      const r = await api.discordBuildNumber();
      const n = Number(r?.build_number);
      if (!n) throw new Error("Discord did not say.");
      if (n === Number(value(f))) {
        toast(`Already the latest: ${n}.`, "ok");
      } else {
        setValue(f, n);
        toast(`Discord is on build ${n}. Save to use it.`, "ok");
      }
      freshBuild = true;
      setTimeout(() => (freshBuild = false), 1400);
    } catch (e: any) {
      toast(e?.message || "Could not read it off Discord just now.", "err");
    }
    buildBusy = false;
  }

  /** Put a field back to what is stored, for a mis-click. */
  function undo(f: FieldDef) {
    const next = { ...dirty };
    delete next[f.key];
    dirty = next;
  }

  function undoAll() {
    dirty = {};
    toast("Reverted every unsaved change.", "ok");
  }

  /** What is unsaved, by the names the rows show: a pair's two ends are one. */
  const changedNames = $derived.by(() => {
    const out: string[] = [];
    for (const key of Object.keys(dirty)) {
      const near = NEAR_OF[key] && byKey[NEAR_OF[key]] ? byKey[NEAR_OF[key]] : byKey[key];
      const name = near ? (PAIRS[near.key]?.label ?? near.label) : key;
      if (!out.includes(name)) out.push(name);
    }
    return out;
  });
  const changedSummary = $derived(
    changedNames.length <= 2
      ? changedNames.join(", ")
      : `${changedNames.slice(0, 2).join(", ")} and ${changedNames.length - 2} more`,
  );
  /** After saving, the bar says so for a moment, then goes. */
  let savedFlash = $state(false);
  let leaving = $state(false);
  let savedTimer = 0;
  const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  /** Ctrl+S (Cmd+S) saves, while there is something to save. */
  function saveKey(e: KeyboardEvent) {
    if (!changed || saving || !(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "s" || rawOpen) return;
    e.preventDefault();
    save();
  }

  async function save() {
    clearTimeout(savedTimer);
    savedFlash = leaving = false;
    saving = true;
    let failed = 0;
    // To the scope the changes were made in: it cannot change while any are unsaved (setScope).
    const persona = scope;
    for (const [key, v] of Object.entries(dirty)) {
      try {
        await track("settings", api.configField(key, v, persona ? { persona } : {}), "Saving settings");
      } catch (e: any) {
        failed++;
        toast(`${key}: ${e.message}`, "err");
      }
    }
    if (persona) reloadPersonas();
    // A social switched on or off: shown or hidden everywhere now, its accounts with it (App.svelte asks for them).
    if (Object.keys(dirty).some((k) => k in SOCIAL_OF)) refreshSocials();
    // The edited values stay on screen until the saved ones are read back: cleared first, the rows showed the
    // values from before the save for a moment (and for as long as 15s, while the held answer counted as fresh).
    await load(true);
    saving = false;
    if (failed) toast("Some settings failed to save.", "err");
    else {
      savedFlash = true;
      savedTimer = window.setTimeout(() => {
        leaving = true;
        savedTimer = window.setTimeout(() => (savedFlash = leaving = false), 280);
      }, 1100);
    }
    revalidate();
  }

  /**
   * Re-run the health checks against what was just saved.
   *
   * /api/health hands back the last snapshot and only refreshes behind it, so
   * a warning you have just fixed - a model that cannot do vision, say - stayed
   * on screen until the background refresh and the next 15s poll had both come
   * round. Saving is exactly the moment to find out whether it worked, so this
   * asks for the uncached answer and updates the banner with it.
   */
  async function revalidate() {
    try {
      const h = await api.healthNow();
      if (h && Array.isArray(h.issues) && h.routes) health.set(h);
    } catch {
      /* the 15s poll still catches up; this is only about being prompt */
    }
  }

  // As text both ways, parsed only on the server: parsed here, the owner ID
  // (a Discord ID, past 2^53) came back rounded, and saving wrote that back.
  // The editor (CodeMirror) is fetched with the text, the first time it opens.
  let RawEditorView = $state<any>(null);
  async function openRaw() {
    try {
      const [mod, r] = await Promise.all([import("../lib/components/RawEditor.svelte"), api.configRaw()]);
      RawEditorView = mod.default;
      raw = r.text;
      rawOpen = true;
    } catch (e: any) {
      toast(e.message || "Could not open the config.", "err");
    }
  }

  /** Saving from the editor: it says why when the server refuses. */
  async function saveRaw(text: string) {
    await api.saveConfigRaw(text);
    raw = text;
    toast("Config saved.", "ok");
    load(true);
    revalidate();
  }

  // The stored profiles panel.
  let people = $state<{ enabled: boolean; cached: number } | null>(null);
  onMount(async () => {
    try {
      people = await api.peopleSettings();
    } catch {
      /* optional */
    }
  });

  async function clearPeople() {
    try {
      const r = await api.clearPeopleCache();
      toast(`Cleared ${r.removed} stored profile${r.removed === 1 ? "" : "s"}.`, "ok");
      people = await api.peopleSettings();
    } catch (e: any) {
      toast(e.message, "err");
    }
  }
</script>

<!-- One row for one setting, used by both the subtabs and the search results. -->
{#snippet row(f: FieldDef, showHome: boolean)}
  {@const pair = pairOf(f)}
  {@const far = pair ? byKey[pair.max] : null}
  {@const touched = f.key in dirty || (!!far && far.key in dirty)}
  {@const used = $lastUsed[f.key]}
  <!-- Label left, control right, at every width.
       It used to stack below the breakpoint, which put every toggle on its own
       line under its own description: a narrow window became a tall column of
       text with switches adrift in the middle of it, and nothing tying a
       switch to the thing it switched. Wide controls still wrap themselves,
       because they state their own width.
       The hover rail is there so a row reads as one object rather than as
       paragraphs that happen to be near each other. -->
  <div class="settings-row group flex flex-wrap items-center gap-x-4 gap-y-2.5 sm:flex-nowrap"
       class:is-switch={f.type === "bool" || (QUIET_KEYS.has(f.key) && !value(f))}
       use:contextMenu={() => rowMenu(f, far)}>
    <!-- A social's switch has its mark beside it, in its own colour; the rest of What runs a quiet one. -->
    {#if SOCIAL_OF[f.key]}
      {@const p = PLATFORMS[SOCIAL_OF[f.key]]}
      {@const lit = !!value(f) && (!partnerOf(f) || !!value(partnerOf(f)!))}
      <span class="settings-mark is-social is-{p.id}" class:is-off={!lit} style="--tone: {p.tone}" title={p.name}
            aria-hidden="true">
        <Icon name={p.icon} size={19} />
      </span>
    {:else if RUN_MARK[f.key]}
      <span class="settings-mark" aria-hidden="true"><Icon name={RUN_MARK[f.key]} size={15} /></span>
    {/if}
    <!-- Just used (a command run with this prefix): the row lights, as a model's does when it answers. -->
    {#if used}{#key used.n}<span class="settings-used" aria-hidden="true"></span>{/key}{/if}
    <div class="settings-text min-w-0 flex-1 basis-60">
      <div class="flex items-center gap-1.5 text-[13.5px] font-medium text-ink">
        <span class="min-w-0 break-words">{pair ? pair.label : f.label}</span>
        {#if touched}
          <span class="settings-dirty h-1.5 w-1.5 shrink-0 rounded-full bg-accent" title="unsaved"></span>
        {/if}
        <!-- Set to a persona: which rows are its own, and which are the app's whoever is shown. -->
        {#if scope}
          {#if f.global_only}
            <span class="settings-scope-tag is-global" title="The same for every profile">Same for everyone</span>
          {:else if f.overridden || far?.overridden}
            <span class="settings-scope-tag is-own" style="--pc: {scopeColor}" title="Everyone's: {shortValue(f.base)}">
              {scopeName}'s own
            </span>
          {/if}
        {/if}
        {#if used}
          {#key used.n}
            <span class="settings-used-tag"><Icon name="sparkle" size={10} />{used.detail ? `${used.detail} · ` : ""}just now</span>
          {/key}
        {/if}
      </div>
      {#if pair || f.description}
        <p class="mt-0.5 text-[12px] leading-relaxed text-muted">{pair ? pair.description : f.description}</p>
      {/if}
      {#if f.needs ?? partnerOf(f)?.needs}<NotHere feature={(f.needs ?? partnerOf(f)?.needs)!} variant="line" />{/if}
      <p class="settings-meta mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-faint/70">
        {#if f.requires_restart || far?.requires_restart}
          <span class="settings-restart" title="Saved straight away, used once the account restarts">
            <Icon name="refresh" size={10} />Needs a restart
          </span>
        {/if}
        {#if showHome}
          <button class="underline decoration-dotted hover:text-ink" onclick={() => goToKey(f.key)}>
            {whereIs(f.key)}
          </button>
        {/if}
        <span class="settings-key break-all font-mono" title={f.key}>{f.key}</span>
        {#if far}<span class="settings-key break-all font-mono" title={far.key}>{far.key}</span>{/if}
      </p>
    </div>

    <!-- A switch's row has room between its words and the switch: a little
         example of what it does plays there (SwitchDemo), when the row is
         wide enough. Every switch row has the slot, so the switches still
         line up down the page. -->
    {#if f.type === "bool" || (QUIET_KEYS.has(f.key) && !value(f))}
      <div class="settings-demo">
        {#if hasDemo(f.key)}
          <SwitchDemo key={f.key} on={!!value(f) && (!partnerOf(f) || !!value(partnerOf(f)!))} />
        {/if}
      </div>
    {/if}

    <div class="flex max-w-full shrink-0 items-center justify-end gap-2 max-sm:w-full">
      <!-- A persona's own value, given up for everyone's in one click. -->
      {#if scope && !touched && !f.global_only && (f.overridden || far?.overridden)}
        <button type="button" class="settings-use-everyones" onclick={() => useEveryones(f, far)}
                title="Everyone's: {shortValue(f.base)}">
          <Icon name="undo" size={12} /><span>Use everyone's</span>
        </button>
      {/if}
      <!-- Undo sits next to the control it reverts, so a mis-click is one
           click to put back rather than remembering the old value. -->
      {#if touched}
        <button
          onclick={() => { undo(f); if (far) undo(far); }}
          title="Undo this change"
          aria-label="Undo {pair ? pair.label : f.label}"
          class="settings-undo jelly shrink-0 rounded-lg p-1.5 text-accent hover:bg-accent/10"
        >
          <Icon name="refresh" size={13} />
        </button>
      {/if}

      {#if f.key === "bot.batch_wait_times" || f.key === "bot.server_batch_wait_times"}
        <!-- The server table, left empty, is one small line: at the chart's
             width it squeezed its words into four lines beside an empty box. -->
        {@const followsDms = f.key === "bot.server_batch_wait_times" && !(Array.isArray(value(f)) && value(f).length)}
        <div class={followsDms ? "max-sm:w-full" : "w-full sm:w-[30rem]"}>
          <WaitTimes value={value(f)} canEmpty={f.key === "bot.server_batch_wait_times"}
                     fallback={f.key === "bot.server_batch_wait_times" && byKey["bot.batch_wait_times"] ? value(byKey["bot.batch_wait_times"]) : []}
                     onchange={(rows) => setValue(f, rows)} />
        </div>
      <!-- Model names come from Groq rather than from memory. A typo used to
           fail silently, and a retirement failed months later. -->
      <!-- Hours on a clock you drag, and timezones picked with their time,
           rather than "2-8" and "Europe/Paris" typed into boxes. -->
      {:else if f.key === "bot.night_invisible.hours"}
        <HourRange value={value(f)} timezone={nightZone()} onchange={(v) => setValue(f, v)} />
      <!-- Snapchat's quiet hours on the same clock as the night, on this computer's
           time, which is what the Snapchat script reads. Blank is none at all. -->
      <!-- When nudges may go out: a window on the same clock, on this computer's
           time, which is what the runner reads. Stored as [start, end]. -->
      {:else if f.key === "bot.nudge.send_during_hours"}
        {@const pairOf = Array.isArray(value(f)) ? value(f) : [10, 22]}
        <HourRange value={`${Number(pairOf[0]) || 0}-${Number(pairOf[1]) || 0}`} timezone={localZone()} words={NUDGE_WORDS}
                   onchange={(v) => { const [a, b] = v.split("-").map(Number); setValue(f, [a, b]); }} />
      {:else if QUIET_KEYS.has(f.key)}
        {@const on = !!String(value(f) ?? "").trim()}
        <div class="flex flex-col items-end gap-3">
          <Toggle checked={on} name="Quiet hours" onchange={(v) => setValue(f, v ? "2-9" : "")} />
          {#if on}
            <HourRange value={value(f)} timezone={localZone()}
                       words={f.key === "bot.calls.quiet_hours" ? CALL_QUIET_WORDS : QUIET_WORDS}
                       onchange={(v) => setValue(f, v)} />
          {/if}
        </div>
      <!-- How long a call rings: one setting holding both ends, on the dial the two-setting ranges use. Sorted because
           the call reads a pair written the wrong way round (voice/session.py), and a dial should show it the same. -->
      {:else if f.key === "bot.calls.ring_seconds"}
        {@const span = Array.isArray(value(f)) && value(f).length >= 2 ? [num(value(f)[0]), num(value(f)[1])] : [2, 7]}
        <Dial values={[Math.min(...span), Math.max(...span)]} scale={timeScale("s", { min: 0, max: 30, integer: true })}
              names={["At least", "At most"]} hint="random in between" onchange={(v) => setValue(f, v)} />
      {:else if f.key in COUNTS && (f.type === "int" || f.type === "float")}
        <Dial values={[num(value(f))]} scale={countScale({ min: f.min, max: f.max, ...COUNTS[f.key] })}
              hint={COUNTS[f.key].hint} names={[f.label, f.label]} onchange={([v]) => setValue(f, v)} />
      {:else if f.key === "bot.night_invisible.timezone" || f.key === "bot.timezone"}
        <TimezonePicker value={value(f)} onchange={(v) => setValue(f, v)} />
      <!-- Languages by name, not codes typed from memory: Discord's own list for
           the locale it is sent as, every language for the fallback. -->
      {:else if f.key === "bot.locale"}
        <LanguagePicker value={value(f)} options={DISCORD_LOCALES} onchange={(v) => setValue(f, v)}
                        unknown="Not a language Discord offers" />
      {:else if f.key === "bot.default_language"}
        <LanguagePicker value={value(f)} options={allLanguages()} common={COMMON_LANGUAGES}
                        onchange={(v) => setValue(f, v)} unknown="Not a two-letter language code" />
      <!-- How fast it types: a dial for the two speeds, and a keyboard typing at them. -->
      {:else if pair && far && f.key === "bot.typing.wpm_min"}
        <TypingSpeed slow={num(value(f))} fast={num(value(far))} min={f.min} max={far.max ?? f.max}
                     onchange={(v) => setPair(f, far, v)} />
      <!-- Amounts of time on a dial: one hand, or a hand for each end of a range. -->
      {:else if pair && far && isTimeUnit(unitOf(f))}
        {@const u = unitOf(f)}
        {#if isTimeUnit(u)}
          <Dial values={[num(value(f)), num(value(far))]}
                scale={timeScale(u, { min: f.min, max: far.max ?? f.max, least: f.step, integer: f.type === "int" })}
                top={DIAL_TOP[f.key]} names={pair.names} hint={pair.hint} onchange={(v) => setPair(f, far, v)} />
        {/if}
      {:else if (f.type === "int" || f.type === "float") && isTimeUnit(unitOf(f))}
        {@const u = unitOf(f)}
        {#if isTimeUnit(u)}
          <Dial values={[num(value(f))]}
                scale={timeScale(u, { min: f.min, max: f.max, least: f.step, integer: f.type === "int" })}
                top={DIAL_TOP[f.key]} names={[f.label, f.label]} zero={ZERO_SAYS[f.key] ?? ""}
                onchange={([v]) => setValue(f, v)} />
        {/if}
      {:else if f.key in MODEL_FIELDS}
        <ModelPicker
          value={value(f)}
          need={MODEL_FIELDS[f.key]}
          multiple={f.key === "bot.groq_models"}
          onchange={(v) => setValue(f, v)}
        />
      {:else if f.type === "bool"}
        {@const partner = partnerOf(f)}
        <Toggle checked={!!value(f) && (!partner || !!value(partner))} name={f.label}
                onchange={(v) => { setValue(f, v); if (partner) setValue(partner, v); }} />
      <!-- A count with no top: a tape to pull, not a bare box. -->
      {:else if onTape(f)}
        <Tape value={num(value(f))} min={f.min ?? 0} max={f.max} words={TAPES[f.key] ?? { one: "", many: "" }}
              name={f.label} onchange={(v) => setValue(f, v)} />
      {:else if f.type === "int" && f.min != null && f.max != null && f.max - f.min <= 1000 && !unitOf(f)}
        {@const lo = Number(f.min)}
        {@const hi = Number(f.max)}
        {@const v = Math.min(hi, Math.max(lo, Number(value(f)) || lo))}
        <input
          type="range"
          min={lo}
          max={hi}
          step={f.step ?? 1}
          value={v}
          oninput={(e) => setValue(f, parseInt((e.target as HTMLInputElement).value))}
          style="--from: 0%; --fill: {((v - lo) / Math.max(1, hi - lo)) * 100}%"
          class="slider min-w-0 flex-1 sm:w-44 sm:flex-none"
          data-default={typeof f.default === "number" ? f.default : undefined}
          use:springValue
          use:sweep
        />
        <span class="slider-value w-14 shrink-0 text-right font-mono text-[12px] text-ink">{v}</span>
      {:else if f.type === "float"}
        {@const blank = isBlank(value(f))}
        {@const [from, to] = band(f)}
        <input
          type="range"
          min={f.min ?? 0}
          max={f.max ?? 1}
          step={f.step ?? 0.01}
          value={blank ? restOf(f) : value(f)}
          oninput={(e) => setValue(f, parseFloat((e.target as HTMLInputElement).value))}
          style="--from: {from}%; --fill: {to}%"
          class="slider min-w-0 flex-1 sm:w-44 sm:flex-none"
          class:is-blank={blank}
          class:is-centered={(f.min ?? 0) < 0 && (f.max ?? 1) > 0}
          title={blank ? "Left to the provider. Drag to set your own." : undefined}
          data-default={typeof f.default === "number" ? f.default : undefined}
          use:springValue
          use:sweep
        />
        <span class="slider-value w-14 shrink-0 text-right text-[12px]"
              class:is-blank={blank}
              class:font-mono={!blank} class:text-ink={!blank}>
          {blank ? "Default" : isChance(f) ? pct(value(f)) : `${value(f)}${unitOf(f) ? ` ${unitOf(f)}` : ""}`}
        </span>
        {#if blankable(f)}
          <!-- Back to Default: a button that says so, there once there is something to go back from. -->
          <button
            type="button"
            onclick={() => setValue(f, null)}
            disabled={blank}
            title="Back to the provider's default, not sent at all"
            aria-label="Put {f.label} back to the provider's default"
            class="slider-clear jelly"
          ><Icon name="undo" size={11} />Default</button>
        {/if}
      <!-- Discord's build number moves every few days and is published nowhere:
           "Latest" reads the current one off Discord's web app and puts it in. -->
      {:else if f.key === "bot.desktop.build_number"}
        <span class="flex items-center gap-2">
          <span class="num-field" class:is-fresh={freshBuild}>
            <input
              type="number"
              value={value(f)}
              oninput={(e) => setValue(f, parseInt((e.target as HTMLInputElement).value))}
              class="bg-transparent text-right font-mono text-[13px] text-ink outline-none"
              use:autowidth={{ value: value(f) }}
            />
          </span>
          <button type="button" class="latest-btn jelly" onclick={() => latestBuild(f)} disabled={buildBusy}
                  title="Read Discord's current build number off its web app">
            <span class="grid place-items-center" class:animate-spin={buildBusy}><Icon name="refresh" size={12} /></span>
            {buildBusy ? "Asking Discord" : "Latest"}
          </button>
        </span>
      {:else if f.type === "int"}
        <!-- A real field, with its unit beside it and the long numbers said in
             words underneath: "2700000" is 45 minutes, which nobody reads off
             seven digits. It used to be borderless until hovered, so it did not
             look like something you could change at all. -->
        <span class="flex flex-col items-end gap-1">
          <span class="num-field" class:is-scrubbable={scrubbable(f)}
                title={scrubbable(f) ? "Drag sideways to change it, or click to type" : undefined}
                use:scrub={{ get: () => Number(value(f)) || 0, set: (v) => setValue(f, v), min: f.min, max: f.max,
                             step: f.step ?? ((from: number) => timeStep(unitOf(f), from)), enabled: scrubbable(f) }}>
            <input
              type="number"
              value={value(f)}
              oninput={(e) => setValue(f, parseInt((e.target as HTMLInputElement).value))}
              class="bg-transparent text-right font-mono text-[13px] text-ink outline-none"
              use:autowidth={{ value: value(f) }}
            />
            {#if unitOf(f)}<span class="num-unit">{unitOf(f)}</span>{/if}
          </span>
          {#if human(f, value(f))}
            <span class="text-[11px] text-faint">= {human(f, value(f))}</span>
          {/if}
        </span>
      {:else if f.key === "minecraft.version"}
        <!-- A dropdown of the versions it plays, and a box for any other. -->
        {@const v = String(value(f) ?? "auto").trim()}
        <span class="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          <Select value={mcKnown(v) ? v : "custom"} options={MC_VERSIONS} width="w-full sm:w-64"
                  onchange={(n) => setValue(f, n === "custom" ? (mcKnown(v) ? "" : v) : n)} />
          {#if !mcKnown(v)}
            <input class="field w-full font-mono sm:w-28" placeholder="1.19.2" aria-label="The version" spellcheck="false"
                   value={v} oninput={(e) => setValue(f, e.currentTarget.value.trim())} />
          {/if}
        </span>
      {:else if f.key in CHOICES}
        <Select
          value={value(f)}
          options={CHOICES[f.key]}
          onchange={(v) => setValue(f, v)}
          width="w-full sm:w-64"
        />
      <!-- The voice belongs to the selected speech model, so the options move
           with it rather than being a free-text field you have to look up. -->
      {:else if f.key === "bot.tts.voice"}
        {@const opts = ttsVoices.map((v) => ({ value: v, label: voiceName(v), hint: VOICE_KIND[v], badge: true }))}
        <Select
          value={value(f)}
          options={value(f) && !ttsVoices.includes(value(f))
            ? [...opts, { value: value(f), label: voiceName(String(value(f))), hint: "Not in this model", badge: true }]
            : opts}
          onchange={(v) => setValue(f, v)}
          width="w-full sm:w-64"
        />
      {:else if f.key === "bot.tts.tones"}
        <div class="chips w-full justify-end sm:w-80" data-sound="self">
          {#each TTS_TONES as t}
            {@const picked = Array.isArray(value(f)) && value(f).includes(t)}
            <!-- Shown as the word; the brackets are only how the voice model
                 wants it written, and that is what is stored. -->
            <button type="button" class="chip" aria-pressed={picked} onclick={() => toggleTone(f, t)} title="Sent as {t}">
              {toneName(t)}
            </button>
          {/each}
        </div>
      <!-- One status, picked the same way as the pool below. A native select
           cannot carry the indicator, and the indicator is the point. -->
      {:else if f.key === "bot.night_invisible.status"}
        <!-- One of four: the highlight springs across to the one picked, down a line too. -->
        <div class="chips is-one w-full justify-end sm:w-80" data-sound="self" use:glide={value(f)}>
          <span class="glide-mark chip-glide" aria-hidden="true"></span>
          {#each PRESENCES as p}
            {@const picked = value(f) === p.value}
            <button type="button" class="chip" class:is-active={picked} aria-pressed={picked}
                    onclick={() => setValue(f, p.value)}>
              <span class="chip-mark"><StatusDot status={p.value} size={11} /></span>
              {p.label}
            </button>
          {/each}
        </div>
      <!-- The rotation pool is a fixed set, not free text. Typing "onlien"
           used to be accepted and then never match anything. -->
      {:else if f.key === "bot.status.statuses"}
        <div class="chips w-full justify-end sm:w-80" data-sound="self">
          {#each PRESENCES as p}
            {@const picked = Array.isArray(value(f)) && value(f).includes(p.value)}
            <button type="button" class="chip" aria-pressed={picked} onclick={() => togglePresence(f, p.value)}>
              <span class="chip-mark"><StatusDot status={p.value} size={11} /></span>
              {p.label}
            </button>
          {/each}
        </div>
      <!-- A plain list of words or phrases is edited as items, not as JSON:
           adding one word should not mean getting the quoting and the commas
           right, with a missing bracket rejecting the save. -->
      {:else if f.type === "json" && Array.isArray(value(f))
                && value(f).every((v: any) => typeof v === "string")}
        <ListEditor
          value={value(f)}
          onchange={(list) => setValue(f, list)}
          placeholder={f.key === "tiktok.live.ignore_viewers" ? "Add a name or @handle" : "Add a word or phrase"}
        />
      {:else if f.type === "json"}
        <textarea
          rows={2}
          value={typeof value(f) === "string" ? value(f) : JSON.stringify(value(f))}
          oninput={(e) => setValue(f, (e.target as HTMLTextAreaElement).value)}
          spellcheck="false"
          class="field w-full font-mono text-[11px] sm:w-80"
        ></textarea>
      {:else}
        <!-- As wide as what is in it, growing as you type and back as you delete (lib/autowidth.ts). -->
        <input
          type="text"
          value={value(f)}
          oninput={(e) => setValue(f, (e.target as HTMLInputElement).value)}
          class="field max-w-full text-[13px] sm:max-w-[26rem]"
          use:autowidth={{ value: value(f) }}
        />
      {/if}
    </div>
  </div>
{/snippet}

<ErrorNote text={loadError} onretry={() => { loadError = ""; schema.refresh({ force: true }); }} />

{#if loading}
  <div class="space-y-2">
    {#each Array(6) as _}<div class="h-11 animate-pulse rounded-lg bg-white/[0.03]"></div>{/each}
  </div>
{:else}
  <div class="mb-4 flex flex-wrap items-center gap-2">
    <label class="relative min-w-0 flex-1">
      <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
        <Icon name="search" size={14} />
      </span>
      <input bind:value={query} placeholder="Search every setting" class="field py-1.5 pl-8 pr-3 text-[13px]" />
    </label>
    {#if cast.length > 1}
      <!-- Whose settings: everyone's, or one persona's own on top of them. -->
      <PersonaScope value={scope} everyone label="Settings for" onchange={setScope} shake={scopeShake} />
    {/if}
    <!-- A file of settings, and the raw file, are everyone's: not there while one persona's are shown. -->
    {#if !scope}
      <div class="flex shrink-0 gap-2">
        <SettingsFile onraw={openRaw} onimported={() => { load(true); revalidate(); }} />
      </div>
    {/if}
  </div>

  <div class="grid gap-5 lg:grid-cols-[214px_minmax(0,1fr)]">
    <!-- ── Tabs ────────────────────────────────────────────────────────────
         A vertical list rather than a wrapped row of pills: names read left to
         right instead of hunting across two lines, and there is room to say
         what each one holds. It becomes a horizontal scroller on a phone,
         where vertical space is the scarce thing. -->
    <div class="hscroll">
    <nav class="settings-rail" aria-label="Settings" use:hscroll>
      {#each tabs as t (t.id)}
        {#if runStarts.has(t.id)}<span class="settings-rail-sep" role="separator"></span>{/if}
        <button
          onclick={() => pickTab(t)}
          aria-current={tab.id === t.id && !searching}
          class="settings-tab {tab.id === t.id && !searching ? 'is-active' : ''}"
        >
          <span class="settings-tab-bar" aria-hidden="true"></span>
          <span class="settings-tab-icon"><Icon name={t.icon} size={15} /></span>
          <span class="min-w-0 flex-1">
            <span class="flex items-center gap-1.5">
              <span class="truncate text-[13px]">{t.name}</span>
              {#if unsaved[t.id]}
                <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-accent"
                      title="unsaved changes"></span>
              {:else if own[t.id]}
                <span class="settings-own-dot" style="--pc: {scopeColor}" title="{scopeName}'s own settings here"></span>
              {/if}
            </span>
            <span class="settings-tab-blurb">{t.blurb}</span>
          </span>
        </button>
      {/each}
    </nav>
    </div>

    <div class="min-w-0">
      {#if searching}
        <p class="mb-3 text-[12px] text-faint">
          {results.length} setting{results.length === 1 ? "" : "s"} matching "{query}"
        </p>
        <div class="settings-card">
          {#each rowsOf(results) as f (f.key)}
            {@render row(f, true)}
          {:else}
            <p class="py-6 text-center text-[13px] text-faint">Nothing matches.</p>
          {/each}
        </div>
      {:else}
        <!-- ── Subtabs ─────────────────────────────────────────────────────
             A segmented strip, not a second vertical list: the tab already
             owns the left edge, and these are short. -->
        <div class="hscroll settings-subs-wrap">
        <div class="settings-subs" role="tablist" aria-label="{tab.name} sections" use:hscroll use:glide={path}>
          <!-- The highlight under the one you are on, gliding from one to the next (lib/glide.ts). -->
          <span class="glide-mark settings-sub-glide" aria-hidden="true"></span>
          {#each subs as s (s.id)}
            {@const n = subCount(tab, s)}
            <button
              role="tab"
              aria-selected={sub.id === s.id}
              onclick={() => (path = `${tab.id}/${s.id}`)}
              class="settings-sub {sub.id === s.id ? 'is-active' : ''}"
            >
              <Icon name={subIcon(tab, s)} size={13} />
              <span>{s.name}</span>
              {#if unsaved[`${tab.id}/${s.id}`]}
                <span class="h-1.5 w-1.5 rounded-full bg-accent" title="unsaved changes"></span>
              {:else if own[`${tab.id}/${s.id}`]}
                <span class="settings-own-dot" style="--pc: {scopeColor}" title="{scopeName}'s own settings here"></span>
              {:else if n}
                <span class="settings-sub-n">{n}</span>
              {/if}
            </button>
          {/each}
        </div>
        </div>

        <!-- Keyed on the subtab so the panel is rebuilt, and therefore
             re-animated, on every switch; and on whose settings they are, so a
             panel never holds on to another persona's. -->
        {#key `${path}|${scope}`}
          <!-- The Models tabs are tools, opened to be read: their wave runs in under half the time. -->
          <div class="settings-panel" use:cascade={path} data-cascade={tab.id === "groq" ? "quick" : undefined}>
            {#if tab.id === "groq"}
              <!-- Models: an orb, what this part is for, and how things stand there now (ModelsHero). -->
              <ModelsHero which={sub.id} name={sub.name} blurb={sub.blurb ?? ""} icon={subIcon(tab, sub)} />
            {:else}
            <header class="settings-head">
              <span class="settings-head-icon"><Icon name={subIcon(tab, sub)} size={18} /></span>
              <div class="min-w-0 flex-1">
                <div class="text-[11px] font-medium uppercase tracking-[0.12em] text-faint">{tab.name}</div>
                <h2 class="text-[17px] font-semibold tracking-tight text-ink">{sub.name}</h2>
                {#if sub.blurb}
                  <p class="mt-0.5 text-[12.5px] text-muted">{sub.blurb}</p>
                {/if}
              </div>
              {#if subCount(tab, sub)}
                <span class="shrink-0 self-start rounded-full bg-white/[0.05] px-2.5 py-1 text-[11px] text-muted">
                  {subCount(tab, sub)} setting{subCount(tab, sub) === 1 ? "" : "s"}
                </span>
              {/if}
            </header>
            {/if}

            {#if scope && GLOBAL_PANELS.has(sub.panel ?? "")}
              <p class="settings-scope-note"><Icon name="layers" size={12} />Same for every profile.</p>
            {/if}

            <!-- Snapchat, TikTok, Instagram, X and Reddit drive Chrome: on a phone, none of these tabs can run. -->
            {#if tab.id === "snapchat" || tab.id === "tiktok" || tab.id === "instagram" || tab.id === "x"
                 || tab.id === "reddit" || tab.id === "whatsapp"}
              <NotHere feature={tab.id} />
            {/if}

            {#if (tab.id === "discord" || tab.id === "snapchat" || tab.id === "tiktok" || tab.id === "instagram"
                  || tab.id === "x" || tab.id === "reddit" || tab.id === "whatsapp")
              && sub.id === tab.subs[0].id}
              <a class="settings-pointer" href="#/accounts">
                <Icon name="accounts" size={14} />
                <span class="min-w-0 flex-1">
                  {tab.id === "discord" ? "Discord accounts, their tokens and proxies"
                    : tab.id === "tiktok" ? "TikTok sign-ins"
                    : tab.id === "instagram" ? "Instagram logins"
                    : tab.id === "x" ? "X logins"
                    : tab.id === "reddit" ? "Reddit sign-ins"
                    : tab.id === "whatsapp" ? "WhatsApp numbers" : "Snapchat logins"} are on the Accounts page.
                </span>
                <span class="settings-pointer-go">Open Accounts <Icon name="chevron" size={11} /></span>
              </a>
            {/if}

            {#if sub.panel === "env"}
              <EnvEditor
                sections={sub.env?.sections ?? null}
                keyLists={sub.env?.keyLists ?? []}
                extras={sub.env?.extras ?? false}
              />
            {:else if sub.panel === "local"}
              <LocalAI />
            {:else if sub.panel === "models"}
              <ModelsPanel />
            {:else if sub.panel === "usage"}
              <UsagePanel />
            {:else if sub.panel === "providers"}
              <ProvidersPanel />
            {:else if sub.panel === "telegram"}
              <TelegramPanel>
                {#snippet alerts()}
                  {#if rowsOf(fieldsFor(tab, sub)).length}
                    <h3 class="settings-part">Alerts on Telegram</h3>
                    <div class="settings-card">
                      {#each rowsOf(fieldsFor(tab, sub)) as f (f.key)}
                        {@render row(f, false)}
                      {/each}
                    </div>
                  {/if}
                {/snippet}
              </TelegramPanel>
            {:else if sub.panel === "snapchat-setup"}
              <SnapchatSetup />
              {#if byKey["snapchat.enabled"]}
                <div class="settings-card mt-6">
                  {@render row(byKey["snapchat.enabled"], false)}
                </div>
              {/if}
            {:else if sub.panel === "tiktok-setup"}
              <SnapchatSetup platform="tiktok" />
              {#if byKey["tiktok.enabled"]}
                <div class="settings-card mt-6">
                  {@render row(byKey["tiktok.enabled"], false)}
                </div>
              {/if}
            {:else if sub.panel === "instagram-setup"}
              <SnapchatSetup platform="instagram" />
              {#if byKey["instagram.enabled"]}
                <div class="settings-card mt-6">
                  {@render row(byKey["instagram.enabled"], false)}
                </div>
              {/if}
            {:else if sub.panel === "x-setup"}
              <SnapchatSetup platform="x" />
              {#if byKey["x.enabled"]}
                <div class="settings-card mt-6">
                  {@render row(byKey["x.enabled"], false)}
                </div>
              {/if}
            {:else if sub.panel === "reddit-setup"}
              <SnapchatSetup platform="reddit" />
              {#if byKey["reddit.enabled"]}
                <div class="settings-card mt-6">
                  {@render row(byKey["reddit.enabled"], false)}
                </div>
              {/if}
            {:else if sub.panel === "whatsapp-setup"}
              <SnapchatSetup platform="whatsapp" />
              {#if byKey["whatsapp.enabled"]}
                <div class="settings-card mt-6">
                  {@render row(byKey["whatsapp.enabled"], false)}
                </div>
              {/if}
            {:else if sub.panel === "minecraft-setup"}
              <MinecraftSetup />
              {#if byKey["minecraft.enabled"]}
                <div class="settings-card mt-6">
                  {@render row(byKey["minecraft.enabled"], false)}
                </div>
              {/if}
            {:else if sub.panel === "discord-setup"}
              <PlatformReady platform="discord" />
            {:else if sub.panel === "telegram-setup"}
              <PlatformReady platform="telegram" />
              {#if byKey["telegram.enabled"]}
                <div class="settings-card mt-6">
                  {@render row(byKey["telegram.enabled"], false)}
                </div>
              {/if}
            {:else if sub.panel === "imessage-setup"}
              <ImessageSetup />
              {#if byKey["imessage.enabled"]}
                <div class="settings-card mt-6">
                  {@render row(byKey["imessage.enabled"], false)}
                </div>
              {/if}
            <!-- Colours, background, panels, typeface, motion: shown, not described (Appearance.svelte). -->
            {:else if sub.panel === "theme" || sub.panel === "typeface" || sub.panel === "interface"}
              <Appearance which={sub.panel} />
            {:else if sub.panel === "pictures"}
              <!-- Sending pictures and voice notes at all, as rows; the looks and the AI's touches, as the panel. -->
              {@const switches = rowsOf(fieldsFor(tab, sub)).filter((f) => !/^bot\.pictures\.(auto_look|touches)\./.test(f.key))}
              {#if switches.length}
                <div class="settings-card mb-6">
                  {#each switches as f (f.key)}
                    {@render row(f, false)}
                  {/each}
                </div>
              {/if}
              <PicturesPanel />
            {:else if sub.panel === "calls"}
              <!-- How it talks, what does the work and its voice are the panel's own controls (with Hear it, Time a
                   turn and Try a call). Picking up is its own subtab now. Anything else listed here still draws as
                   an ordinary row under the panel, and saves with the same button. -->
              {@const own = new Set(["bot.calls.engine", "bot.calls.realtime_provider", "bot.calls.realtime_voice",
                                     "bot.calls.speaker", "bot.calls.voice", "bot.calls.hear", "bot.calls.think",
                                     "bot.calls.speak"])}
              <!-- Which version of a voice model is a row, not a panel control, but it says nothing at all when
                   the call is on its own brain, so it waits until a voice model is the one talking. -->
              {@const callRows = rowsOf(fieldsFor(tab, sub)).filter((f) => !own.has(f.key)
                && !(f.key === "bot.calls.realtime_model"
                     && (byKey["bot.calls.engine"] ? value(byKey["bot.calls.engine"]) : "realtime") !== "realtime"))}
              <CallSetup {scope} get={(k: string) => (byKey[k] ? value(byKey[k]) : undefined)}
                         set={(k: string, v: any) => { if (byKey[k]) setValue(byKey[k], v); }} />
              {#if callRows.length}
                <div class="settings-card mt-6">
                  {#each callRows as f (f.key)}
                    {@render row(f, false)}
                  {/each}
                </div>
              {/if}
            {:else if sub.panel === "profiles"}
              <div class="settings-card">
                {#if byKey["bot.profile_cache.enabled"]}
                  {@render row(byKey["bot.profile_cache.enabled"], false)}
                {/if}
                <div class="settings-row flex flex-wrap items-center gap-4">
                  <div class="min-w-0 flex-1">
                    <div class="text-[13.5px] font-medium text-ink">Stored profiles</div>
                    <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
                      {people?.cached ?? 0} people cached on this machine. Clearing
                      removes every stored name, avatar and bio.
                    </p>
                  </div>
                  <Button kind="ghost" size="sm" onclick={clearPeople}>Clear stored profiles</Button>
                </div>
              </div>
            {:else}
              <div class="settings-card">
                {#each rowsOf(shown).slice(0, drawnRows) as f (f.key)}
                  {@render row(f, false)}
                {:else}
                  <p class="py-6 text-center text-[13px] text-faint">Nothing here.</p>
                {/each}
              </div>
              {#if sub.id === "typing" && drawnRows >= rowsOf(shown).length}
                <!-- The numbers above, added up for one real reply, live as they are edited. -->
                <TypingPreview get={(k) => (byKey[k] ? value(byKey[k]) : undefined)} />
              {/if}
            {/if}
          </div>
        {/key}

        {#if tab.id === "tiktok" && LIVE_SUBS.has(sub.id)}
          <!-- A practice LIVE, answered with the settings above as they are on the page, saved or not. Outside the
               subtab's own block, so a LIVE going on stays on from one LIVE subtab to the next. -->
          <LiveDemo get={(k) => (byKey[k] ? value(byKey[k]) : undefined)} persona={scope} />
        {/if}

        <!-- Appearance applies as it is clicked: nothing there is saved, so nothing to say about saving. -->
        {#if !(sub.panel === "theme" || sub.panel === "typeface" || sub.panel === "interface")}
          <FootNote class="mt-6" icon="check">
            Saving applies the change to the running account straight away. Only rows
            marked <span class="settings-restart is-inline"><Icon name="refresh" size={9} />Needs a restart</span> wait for the
            account to be restarted.
          </FootNote>
        {/if}
      {/if}
    </div>
  </div>
{/if}

<svelte:window onkeydown={saveKey} />

{#if changed || savedFlash}
  <!-- What is unsaved, and the two things to do about it, where they cannot be
       missed. Save used to be a small button in the top corner that was out of
       sight as soon as the page scrolled. The count rolls as it changes, the
       names say what the changes are, and once saved the bar says so before
       it goes, rather than vanishing the moment Save is pressed. -->
  <div class="save-bar glass floating" class:is-saved={!changed} class:is-leaving={leaving && !changed}
       role="status" use:toBody>
    {#if !changed}
      <span class="save-ok"><Icon name="check" size={15} /></span>
      <span class="save-text">
        <b>{scope && scopeName ? `Saved for ${scopeName}` : "Saved"}</b>
        <small>{scope ? "Applied to its running accounts." : "Applied to the running accounts."}</small>
      </span>
    {:else}
      <span class="save-count"><Odometer value={changed} /></span>
      <span class="save-text">
        <b>{changed === 1 ? "Unsaved change" : "Unsaved changes"}</b>
        <small title={changedNames.join(", ")}>{changedSummary}</small>
      </span>
      <span class="save-actions">
        <button type="button" class="save-undo" onclick={undoAll} disabled={saving}><Icon name="undo" size={13} />Undo all</button>
        <button type="button" class="save-go" onclick={save} disabled={saving}>
          {#if saving}<span class="save-spin" aria-hidden="true"></span>Saving{:else}<Icon name="check" size={13} />Save<kbd>{isMac ? "⌘" : "Ctrl"} S</kbd>{/if}
        </button>
      </span>
    {/if}
  </div>
{/if}

{#if rawOpen && RawEditorView}
  <RawEditorView text={raw} onsave={saveRaw} onclose={() => (rawOpen = false)} />
{/if}
