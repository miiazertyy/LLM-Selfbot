<script lang="ts">
  /**
   * Pictures, in Settings: the look new pictures get, and what the AI may put
   * on a picture as it sends it, like on Snapchat (a caption, big text, the
   * time, the day, emoji, a look), on the accounts picked here.
   *
   * Every change is saved as it is made (POST /api/config/field), as the Local
   * AI panel's are. The tiles are the looks drawn on one of your own pictures
   * (app/utils/looks.py), and "See what it would add" asks the AI for real, on
   * that picture, as if someone had just asked for one.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import { play } from "../uisound";
  import { picturesBlur, toast } from "../stores";
  import { springValue } from "../spring";
  import { watchDescribe } from "../pictures";
  import { platformName } from "../accounts/condition";
  import { usePersona } from "../personas/context";
  import Icon from "./Icon.svelte";
  import Avatar from "./Avatar.svelte";
  import Button from "./Button.svelte";
  import Toggle from "./Toggle.svelte";

  type Look = { id: string; name: string };
  type Acct = { id: string; platform: string; name: string; avatar?: string };
  type Sample = { name: string; id: string };

  /** Everyone's settings (""), or the persona Settings is set to; Settings remakes this panel for another. */
  const persona = usePersona();
  /** Whose pictures it is shown on: that persona's, Default's for everyone's. */
  const who = persona === "default" ? "" : persona;

  const MODES = [
    { id: "off", name: "No filter", hint: "New pictures stay as they are.", icon: "pictures" },
    { id: "one", name: "Same filter", hint: "Every new picture gets the filter you pick.", icon: "palette" },
    { id: "random", name: "Random filter", hint: "Each one gets a filter from the ones you tick.", icon: "refresh" },
    { id: "ai", name: "AI picks", hint: "The AI picks a filter that suits each picture.", icon: "sparkle" },
  ];
  const KINDS = [
    { id: "caption", name: "Caption", icon: "caption" },
    { id: "big_text", name: "Big text", icon: "type" },
    { id: "time", name: "Time", icon: "clock" },
    { id: "day", name: "Day", icon: "calendar" },
    { id: "emoji", name: "Emoji", icon: "smile" },
    { id: "look", name: "Filter", icon: "palette" },
  ];
  /** How often, in a word beside the number. */
  const oftenWord = (v: number) => v <= 0 ? "never" : v < 0.2 ? "rarely" : v < 0.4 ? "sometimes" : v < 0.6 ? "half the time"
    : v < 0.85 ? "often" : v < 1 ? "almost always" : "every time";

  let looks = $state<Look[]>([]);
  let mode = $state("off");
  let look = $state("warm");
  let picks = $state<string[]>([]);
  let strength = $state(0.7);
  let vary = $state(0.1);
  let accounts = $state<string[]>([]);
  let chance = $state(0.5);
  let kinds = $state<string[]>(KINDS.map((k) => k.id));
  let accts = $state<Acct[]>([]);
  let sample = $state<Sample | null>(null);
  let total = $state(0);
  let loaded = $state(false);
  let loadError = $state("");
  let applying = $state(false);
  // The preview beside the filters: the one under the pointer while it is there, the strength a beat behind the
  // slider (a drag is not forty renders), the original while held, and the AI's pick once asked for.
  let hovered = $state("");
  let shownStrength = $state(0.7);
  let holding = $state(false);
  let aiPick = $state<{ look: string; name: string } | null>(null);
  let asking = $state(false);
  let prevLoaded = $state(false);
  /** The picture's own shape, once it has loaded: a tall phone picture is shown whole, not cut to 3:4. */
  let ratio = $state(3 / 4);
  const frame = $derived(ratio >= 260 / 440 ? { w: 260, h: Math.round(260 / ratio) } : { w: Math.round(440 * ratio), h: 440 });

  // The previews here, unblurred, while pictures are kept blurred elsewhere: asked for with the eye on the preview,
  // and remembered on this computer.
  const REVEAL_KEY = "pictures.settingsReveal";
  let reveal = $state((() => {
    try { return localStorage.getItem(REVEAL_KEY) === "1"; } catch { return false; }
  })());
  function toggleReveal() {
    reveal = !reveal;
    play(reveal ? "on" : "off");
    try { localStorage.setItem(REVEAL_KEY, reveal ? "1" : "0"); } catch { /* remembered for this visit only */ }
  }
  function onPreviewLoad(e: Event) {
    prevLoaded = true;
    const img = e.currentTarget as HTMLImageElement;
    if (img.naturalWidth && img.naturalHeight) ratio = img.naturalWidth / img.naturalHeight;
  }
  let previewing = $state<"" | "ai" | "all">("");
  let preview = $state<{ image: string; note: string } | null>(null);

  onMount(async () => {
    try {
      const [lk, ac, pics]: any[] = await Promise.all([
        api.pictureLooks(who), api.accounts().catch(() => null), api.pictures(who).catch(() => null),
      ]);
      looks = lk.looks ?? [];
      mode = lk.auto?.mode ?? "off";
      look = lk.auto?.look ?? "warm";
      picks = lk.auto?.looks ?? [];
      strength = lk.auto?.strength ?? 0.7;
      shownStrength = strength;
      vary = lk.auto?.vary ?? 0.1;
      accounts = lk.touches?.accounts ?? [];
      chance = lk.touches?.chance ?? 0.5;
      kinds = lk.touches?.kinds ?? KINDS.map((k) => k.id);
      accts = (ac?.accounts ?? [])
        .filter((a: any) => a.platform !== "telegram")
        .map((a: any) => ({
          id: a.id, platform: a.platform, avatar: a.avatar || "",
          name: a.display_name || a.username || `${platformName(a.platform)}${a.account ? ` #${a.account}` : ""}`,
        }));
      const list = (pics?.pictures ?? []).filter((p: any) => p.id && !p.moving);
      total = (pics?.pictures ?? []).length;
      const best = list.find((p: any) => p.description) ?? list[0];
      sample = best ? { name: best.name, id: best.id } : null;
    } catch (e: any) {
      loadError = e?.message || "Could not load the picture settings";
    }
    loaded = true;
  });

  async function save(key: string, value: unknown) {
    try {
      await api.configField(key, value, persona ? { persona } : {});
    } catch (e: any) {
      play("err");
      toast(e?.message || "Could not save it", "err");
    }
  }

  function pickMode(id: string) {
    if (id === mode) return;
    play("select");
    hovered = "";
    mode = id;
    save("bot.pictures.auto_look.mode", id);
  }
  function pickLook(id: string) {
    if (mode === "random") {
      play(picks.includes(id) ? "off" : "on");
      picks = picks.includes(id) ? picks.filter((x) => x !== id) : looks.map((l) => l.id).filter((x) => x === id || picks.includes(x));
      save("bot.pictures.auto_look.looks", picks);
    } else {
      if (id === look) return;
      play("select");
      look = id;
      save("bot.pictures.auto_look.look", id);
    }
  }
  const lookOn = (id: string) => (mode === "random" ? picks.includes(id) : look === id);

  function toggleAccount(id: string, on: boolean) {
    accounts = on ? [...accounts.filter((x) => x !== id), id] : accounts.filter((x) => x !== id);
    save("bot.pictures.touches.accounts", accounts);
  }
  function toggleKind(id: string) {
    // Its sound comes with its chip's pop (lib/feel.ts).
    kinds = kinds.includes(id) ? kinds.filter((x) => x !== id) : KINDS.map((k) => k.id).filter((x) => x === id || kinds.includes(x));
    save("bot.pictures.touches.kinds", kinds);
    preview = null;
  }

  async function applyAll() {
    applying = true;
    try {
      const r: any = await api.autoLookAll(who);
      play("ok");
      toast(r.queued ? `Adding filters to ${r.queued} picture${r.queued === 1 ? "" : "s"}.` : "Already doing it.", "ok");
      watchDescribe();
    } catch (e: any) {
      play("err");
      toast(e?.message || "Could not start it", "err");
    }
    applying = false;
  }

  /** What the AI would add to one of your pictures, asked for real; or every kind at once, to see each drawn. */
  async function tryTouch(all = false) {
    if (!sample) return;
    previewing = all ? "all" : "ai";
    try {
      const r: any = await api.touchPreview(sample.name, sample.id, kinds, all, who);
      preview = { image: r.image || "", note: r.note || r.said || "" };
      play(r.image ? "receive" : "info");
    } catch (e: any) {
      play("err");
      toast(e?.message || "Could not ask the AI", "err");
    }
    previewing = "";
  }

  const pct = (v: number, lo = 0, hi = 1) => `${Math.round(((v - lo) / (hi - lo)) * 100)}%`;

  let follow = 0;
  function onStrength(v: number) {
    strength = v;
    clearTimeout(follow);
    follow = window.setTimeout(() => (shownStrength = strength), 140);
  }

  /** The filter the preview shows: the one under the pointer, else what new pictures get. */
  const previewLook = $derived(holding ? ""
    : (mode === "one" || mode === "random") && hovered ? hovered
    : mode === "one" ? look : mode === "random" ? (picks[0] ?? looks[0]?.id ?? "")
    : mode === "ai" ? (aiPick?.look ?? "") : "");
  const previewName = $derived(holding || !previewLook ? "Original" : looks.find((l) => l.id === previewLook)?.name ?? previewLook);
  const previewSrc = $derived(sample ? api.lookPreviewUrl(sample.id, previewLook, shownStrength, 520, who)
    : api.samplePreviewUrl(previewLook, shownStrength, 520));
  $effect(() => {
    void previewSrc;
    prevLoaded = false;
  });

  async function askAi() {
    if (!sample) return;
    asking = true;
    try {
      const r: any = await api.aiLookFor(sample.name, sample.id, who);
      aiPick = { look: r.look, name: r.name };
      play("receive");
    } catch (e: any) {
      play("err");
      toast(e?.message || "Could not ask the AI", "err");
    }
    asking = false;
  }
  const tile = (id: string) => (sample ? api.lookPreviewUrl(sample.id, id, 0.85, 132, who) : "");
  // Pictures hidden on the Pictures tab stay hidden here: colours for the tiles, and the preview blurred until hovered.
  const showPics = $derived(!!sample && (!$picturesBlur || reveal));
  const veiled = $derived(!!sample && $picturesBlur && !reveal);
</script>

{#if !loaded}
  <div class="settings-card"><div class="h-40 animate-pulse rounded-xl bg-white/[0.03]"></div></div>
{:else if loadError}
  <div class="settings-card"><p class="p-4 text-[13px] text-warn">{loadError}</p></div>
{:else}
  <!-- ── New pictures ─────────────────────────────────────────────────── -->
  <h3 class="settings-part">New pictures</h3>
  <div class="settings-card pp">
    <div class="pp-modes" role="radiogroup" aria-label="Filter on new pictures">
      {#each MODES as m (m.id)}
        <button type="button" class="pp-mode" class:is-on={mode === m.id} role="radio" aria-checked={mode === m.id}
                onclick={() => pickMode(m.id)}>
          <span class="pp-mode-icon"><Icon name={m.icon} size={15} /></span>
          <span class="pp-mode-name">{m.name}</span>
          <span class="pp-mode-hint">{m.hint}</span>
        </button>
      {/each}
    </div>

    {#if mode !== "off"}
    <div class="pp-split">
    <div class="pp-left">
    {#if mode === "one" || mode === "random"}
      <div class="pp-sub">
        {mode === "one" ? "Filter" : picks.length ? `Random from these ${picks.length}` : "Random from all of them, or tick the ones to use"}
      </div>
      <div class="pp-looks" role={mode === "one" ? "radiogroup" : "group"} aria-label="Filters">
        {#each looks as l (l.id)}
          <button type="button" class="pp-look" class:is-on={lookOn(l.id)} aria-pressed={lookOn(l.id)}
                  onclick={() => pickLook(l.id)} onmouseenter={() => (hovered = l.id)} onmouseleave={() => (hovered = "")}
                  onfocus={() => (hovered = l.id)} onblur={() => (hovered = "")}>
            <span class="pp-look-tile">
              {#if showPics}<img src={tile(l.id)} alt="" loading="lazy" />{:else}<span class="pp-look-swatch pp-sw-{l.id}"></span>{/if}
              {#if lookOn(l.id)}<span class="pp-look-tick"><Icon name="check" size={10} /></span>{/if}
            </span>
            <span class="pp-look-name">{l.name}</span>
          </button>
        {/each}
      </div>
    {/if}

    {#if mode === "ai"}
      <p class="pp-lead">The AI looks at what each new picture shows and picks the filter that suits it.</p>
      {#if sample}
        <div>
          <Button size="sm" kind="ghost" loading={asking} onclick={askAi}>
            <span class="inline-flex items-center gap-1.5"><Icon name="sparkle" size={13} />{aiPick ? `It picked ${aiPick.name}. Ask again` : "See what it picks"}</span>
          </Button>
        </div>
      {/if}
    {/if}
      <div class="pp-row" data-slider-row>
        <span class="pp-label">Strength</span>
        <input type="range" class="slider" min="0.05" max="1" step="0.05" value={strength} style="--fill: {pct(strength, 0.05, 1)}"
               aria-label="Strength" use:springValue
               oninput={(e) => onStrength(parseFloat((e.target as HTMLInputElement).value))}
               onchange={() => { play("tick"); save("bot.pictures.auto_look.strength", strength); }} />
        <span class="pp-val slider-value">{Math.round(strength * 100)}%</span>
      </div>
      <div class="pp-row" data-slider-row>
        <span class="pp-label">Vary strength</span>
        <input type="range" class="slider" min="0" max="0.5" step="0.05" value={vary} style="--fill: {pct(vary, 0, 0.5)}"
               aria-label="Vary the strength by" use:springValue
               oninput={(e) => (vary = parseFloat((e.target as HTMLInputElement).value))}
               onchange={() => { play("tick"); save("bot.pictures.auto_look.vary", vary); }} />
        <span class="pp-val slider-value">±{Math.round(vary * 100)}%</span>
      </div>
    </div>

    <!-- What it does: on one of your pictures (blurred until hovered, while pictures are hidden), or on a made-up one
         when there are none; held down, the original. -->
    <div class="pp-preview">
      <div class="pp-prev-wrap" style="width: {frame.w}px; aspect-ratio: {ratio};">
        <button type="button" class="pp-prev-frame" class:is-veiled={veiled} class:is-holding={holding}
                onpointerdown={() => (holding = true)} onpointerup={() => (holding = false)}
                onpointerleave={() => (holding = false)} onpointercancel={() => (holding = false)}
                aria-label="Preview. Hold to see the original">
          <img src={previewSrc} alt="" class:is-loading={!prevLoaded} onload={onPreviewLoad} draggable="false" />
          <span class="pp-prev-tag">{previewName}{previewLook && !holding ? ` · ${Math.round(shownStrength * 100)}%` : ""}</span>
        </button>
        {#if sample && $picturesBlur}
          <button type="button" class="pp-reveal" onclick={toggleReveal} aria-pressed={reveal}
                  title={reveal ? "Blur the previews again" : "Show the previews unblurred"}>
            <Icon name={reveal ? "eyeOff" : "eye"} size={13} />{reveal ? "Blur" : "Show"}
          </button>
        {/if}
      </div>
      <span class="pp-prev-hint">{sample ? "Hold to compare" : "A sample picture. Hold to compare"}</span>
    </div>
    </div>
      {#if total}
        <div class="pp-foot">
          <span>Originals are kept, so a filter can be removed from the Pictures tab.</span>
          <Button size="sm" kind="ghost" loading={applying} onclick={applyAll}>
            {total === 1 ? "Apply to the picture now" : `Apply to all ${total} pictures now`}
          </Button>
        </div>
      {/if}
    {/if}
  </div>

  <!-- ── When it sends one ────────────────────────────────────────────── -->
  <!-- The choices on the left, and on the right a phone with what it would send on it, the way the filters above
       have their preview beside them. -->
  <h3 class="settings-part">When it sends a picture</h3>
  <div class="settings-card pp">
    <div class="pp-split">
      <div class="pp-left">
        <p class="pp-lead">It can add a caption, big text, the time, the day, emoji or a filter, the way people do on
          Snapchat. Often it sends the picture as it is.</p>

        <div class="pp-sub">On these accounts</div>
        {#if accts.length}
          <div class="pp-accts">
            {#each accts as a (a.id)}
              {@const on = accounts.includes(a.id)}
              <div class="pp-acct" class:is-on={on}>
                <span class="pp-acct-face">
                  <Avatar src={a.avatar} name={a.name} size={30} zoom={false} silhouette={a.platform === "snapchat" && !a.avatar} />
                  <span class="pp-acct-mark" class:is-snap={a.platform === "snapchat"}>
                    <Icon name={a.platform === "snapchat" ? "snapchat" : "discord"} size={9} />
                  </span>
                </span>
                <span class="pp-acct-text">
                  <span class="pp-acct-name">{a.name}</span>
                  <span class="pp-acct-says">{on ? "Adds things" : "Sends them plain"}</span>
                </span>
                <Toggle checked={on} name="Touches on {a.name}" size="sm" onchange={(v) => toggleAccount(a.id, v)} />
              </div>
            {/each}
          </div>
        {:else}
          <p class="pp-lead">Add an account first, on the Accounts tab.</p>
        {/if}

        <div class="pp-sub">How often</div>
        <div class="pp-often" class:is-off={!accounts.length} data-slider-row>
          <input type="range" class="slider" min="0" max="1" step="0.05" value={chance} style="--fill: {pct(chance)}"
                 aria-label="How often it considers adding something" use:springValue disabled={!accounts.length}
                 oninput={(e) => (chance = parseFloat((e.target as HTMLInputElement).value))}
                 onchange={() => save("bot.pictures.touches.chance", chance)} />
          <span class="pp-often-val"><b>{Math.round(chance * 100)}%</b>{oftenWord(chance)}</span>
        </div>

        <div class="pp-sub">What it may add</div>
        <div class="chips" data-sound="self" role="group" aria-label="What it may add">
          {#each KINDS as k (k.id)}
            <button type="button" class="chip" aria-pressed={kinds.includes(k.id)} onclick={() => toggleKind(k.id)}>
              <span class="chip-mark"><Icon name={k.icon} size={13} /></span>{k.name}
            </button>
          {/each}
        </div>
      </div>

      <div class="pp-preview">
        <div class="pp-phone" class:is-busy={!!previewing}>
          <div class="pp-phone-screen">
            {#if preview?.image}
              {#key preview.image}
                <img class="pp-snap" src={preview.image} alt="What it would send" class:is-veiled={veiled} />
              {/key}
            {:else if sample}
              <img class="pp-snap is-plain" src={api.lookPreviewUrl(sample.id, "", 1, 520, who)} alt="One of your pictures"
                   class:is-veiled={veiled} />
              <span class="pp-phone-hint">Press Try to see what it adds</span>
            {:else}
              <span class="pp-phone-empty"><Icon name="pictures" size={22} />Add a picture on the Pictures tab to try it.</span>
            {/if}
            {#if previewing}<span class="pp-phone-shimmer" aria-hidden="true"></span>{/if}
          </div>
        </div>
        {#if preview?.note}<span class="pp-said">{preview.note}</span>{/if}
        {#if sample}
          <div class="pp-try-buttons">
            <Button size="sm" loading={previewing === "ai"} disabled={!kinds.length || !!previewing} onclick={() => tryTouch()}>
              <span class="inline-flex items-center gap-1.5"><Icon name="sparkle" size={13} />{preview ? "Try again" : "Try"}</span>
            </Button>
            <Button size="sm" kind="ghost" loading={previewing === "all"} disabled={!kinds.length || !!previewing} onclick={() => tryTouch(true)}>
              <span class="inline-flex items-center gap-1.5"><Icon name="pictures" size={13} />Show all</span>
            </Button>
          </div>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  .pp { display: flex; flex-direction: column; gap: 14px; padding: 16px; }
  .pp-lead { font-size: 12.5px; line-height: 1.55; color: var(--color-muted); }
  .pp-sub { font-size: 11px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: var(--color-faint); }

  .pp-modes { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; }
  .pp-mode {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 2px 10px;
    align-items: center;
    padding: 11px 12px;
    border-radius: 14px;
    text-align: left;
    background: rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    transition: background-color 0.15s ease, box-shadow 0.2s ease, transform 0.25s var(--spring);
  }
  .pp-mode:hover { background: rgb(255 255 255 / 0.06); transform: translateY(-1px); }
  .pp-mode:active { transform: scale(0.98); }
  .pp-mode.is-on {
    background: color-mix(in srgb, var(--color-accent) 12%, transparent);
    box-shadow: inset 0 0 0 1.5px var(--color-accent), 0 10px 24px -14px var(--color-accent);
  }
  .pp-mode-icon {
    display: grid;
    grid-row: span 2;
    width: 30px;
    height: 30px;
    place-items: center;
    border-radius: 10px;
    color: var(--color-faint);
    background: rgb(255 255 255 / 0.05);
  }
  .pp-mode.is-on .pp-mode-icon { color: var(--color-bg); background: var(--color-accent); }
  .pp-mode-name { font-size: 13px; font-weight: 600; color: var(--color-ink); }
  .pp-mode-hint { font-size: 11px; line-height: 1.35; color: var(--color-faint); }

  /* Two even rows of six, rather than a row that leaves one alone on the next. */
  .pp-looks { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 14px 8px; max-width: 560px; }
  @media (max-width: 640px) {
    .pp-looks { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  }
  .pp-look {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    min-width: 0;
    font-size: 11px;
    font-weight: 600;
    color: var(--color-muted);
    transition: color 0.15s ease;
  }
  .pp-look-tile {
    position: relative;
    display: block;
    width: 58px;
    height: 58px;
    border-radius: 999px;
    overflow: visible;
    transition: transform 0.3s var(--spring);
  }
  .pp-look-tile img, .pp-look-swatch {
    display: block;
    width: 100%;
    height: 100%;
    border-radius: 999px;
    object-fit: cover;
    box-shadow: 0 0 0 2px transparent;
    transition: box-shadow 0.25s var(--spring);
  }
  .pp-look:hover .pp-look-tile { transform: translateY(-2px) scale(1.04); }
  .pp-look.is-on { color: var(--color-ink); }
  .pp-look.is-on .pp-look-tile img, .pp-look.is-on .pp-look-swatch {
    box-shadow: 0 0 0 2px var(--color-bg), 0 0 0 4px var(--color-accent);
  }
  .pp-look-tick {
    position: absolute;
    right: -2px;
    bottom: -2px;
    display: grid;
    width: 18px;
    height: 18px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-bg);
    background: var(--color-accent);
    box-shadow: 0 0 0 2px var(--color-bg);
  }
  /* A long name ("Golden hour") wraps under its circle rather than ending in "...". */
  .pp-look-name { max-width: 100%; text-align: center; line-height: 1.25; overflow-wrap: anywhere; }
  /* Without a picture of yours to show them on, a colour for each. */
  .pp-sw-warm { background: linear-gradient(135deg, #f6c38a, #d9824f); }
  .pp-sw-golden { background: linear-gradient(135deg, #ffd88a, #e39a3b); }
  .pp-sw-rosy { background: linear-gradient(135deg, #f7b6c4, #d77a95); }
  .pp-sw-cool { background: linear-gradient(135deg, #a9d3f2, #5d8fc7); }
  .pp-sw-night { background: linear-gradient(135deg, #42507a, #141a33); }
  .pp-sw-vivid { background: linear-gradient(135deg, #ff5f7e, #3fd2ff); }
  .pp-sw-soft { background: linear-gradient(135deg, #fbe9f0, #cfd8f5); }
  .pp-sw-faded { background: linear-gradient(135deg, #cfc6b8, #9aa3a6); }
  .pp-sw-vintage { background: linear-gradient(135deg, #e3c79a, #8f7a5c); }
  .pp-sw-film { background: linear-gradient(135deg, #b9cfa8, #6d8a77); }
  .pp-sw-mono { background: linear-gradient(135deg, #e6e6e6, #5c5c5c); }
  .pp-sw-noir { background: linear-gradient(135deg, #8a8a8a, #0d0d0d); }

  /* The filters and their sliders on the left, what they do on the right. */
  .pp-split { display: grid; grid-template-columns: minmax(0, 1fr) 260px; gap: 22px; align-items: start; }
  .pp-left { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  @media (max-width: 900px) {
    .pp-split { grid-template-columns: minmax(0, 1fr); }
  }
  .pp-preview { display: flex; flex-direction: column; align-items: center; gap: 8px; }
  .pp-prev-wrap { position: relative; max-width: 100%; }
  .pp-prev-frame {
    position: relative;
    display: grid;
    width: 100%;
    height: 100%;
    place-items: center;
    overflow: hidden;
    border-radius: 18px;
    background: rgb(0 0 0 / 0.3);
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent), 0 18px 40px -22px rgb(0 0 0 / 0.95);
    cursor: zoom-in;
    user-select: none;
    -webkit-user-select: none;
    touch-action: none;
  }
  .pp-prev-frame img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    transition: opacity 0.25s ease, filter 0.3s ease;
  }
  .pp-prev-frame img.is-loading { opacity: 0.8; filter: blur(2px); }
  .pp-prev-frame.is-veiled img { filter: blur(18px) saturate(0.7); }
  .pp-prev-frame.is-veiled:hover img, .pp-prev-frame.is-veiled.is-holding img { filter: none; }
  .pp-prev-tag {
    position: absolute;
    left: 50%;
    bottom: 10px;
    padding: 4px 11px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 600;
    white-space: nowrap;
    color: #fff;
    background: rgb(8 8 16 / 0.55);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.14);
    backdrop-filter: blur(10px);
    transform: translateX(-50%);
    pointer-events: none;
  }
  .pp-prev-frame.is-holding .pp-prev-tag { background: color-mix(in srgb, var(--color-accent) 70%, rgb(0 0 0)); }
  /* The eye in the corner: the blur off, and on again. */
  .pp-reveal {
    position: absolute;
    top: 10px;
    right: 10px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    height: 26px;
    padding: 0 10px 0 8px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 600;
    color: #fff;
    background: rgb(8 8 16 / 0.55);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.16);
    backdrop-filter: blur(10px);
    transition: background-color 0.15s ease, transform 0.25s var(--spring);
  }
  .pp-reveal:hover { background: color-mix(in srgb, var(--color-accent) 65%, rgb(0 0 0)); transform: translateY(-1px); }
  .pp-reveal:active { transform: scale(0.95); }
  .pp-prev-hint { font-size: 11px; color: var(--color-faint); }

  .pp-row { display: flex; align-items: center; gap: 12px; transition: opacity 0.2s ease; }
  .pp-row.is-off { opacity: 0.45; }
  .pp-label { width: 92px; flex-shrink: 0; font-size: 12.5px; font-weight: 600; color: var(--color-muted); }
  .pp-row .slider { flex: 1; min-width: 0; }
  .pp-val { width: 48px; text-align: right; font-size: 12.5px; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--color-ink); }
  .pp-foot {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding-top: 12px;
    border-top: 1px solid color-mix(in srgb, var(--color-edge) 60%, transparent);
    font-size: 11.5px;
    color: var(--color-faint);
  }

  /* The accounts: a card each, its face with its platform on it, lit while it adds things. */
  .pp-accts { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 8px; }
  .pp-acct {
    display: flex;
    align-items: center;
    gap: 11px;
    padding: 9px 12px 9px 10px;
    border-radius: 14px;
    background: rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    transition: background-color 0.25s var(--swift), box-shadow 0.3s var(--swift), transform 0.35s var(--jelly);
  }
  .pp-acct:hover { transform: translateY(-1px); }
  .pp-acct.is-on {
    background: linear-gradient(180deg, color-mix(in srgb, var(--color-accent) 13%, transparent), color-mix(in srgb, var(--color-accent) 5%, transparent));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 45%, transparent), 0 10px 24px -16px var(--color-accent);
  }
  .pp-acct-face { position: relative; display: inline-flex; flex-shrink: 0; }
  .pp-acct-mark {
    position: absolute;
    right: -3px;
    bottom: -3px;
    display: grid;
    width: 15px;
    height: 15px;
    place-items: center;
    border-radius: 999px;
    color: #fff;
    background: #5865f2;
    box-shadow: 0 0 0 2px var(--color-card);
  }
  .pp-acct-mark.is-snap { color: #141414; background: #fffc00; }
  .pp-acct-text { display: flex; min-width: 0; flex: 1; flex-direction: column; }
  .pp-acct-name { overflow: hidden; font-size: 13px; font-weight: 600; color: var(--color-ink); text-overflow: ellipsis; white-space: nowrap; }
  .pp-acct-says { font-size: 11px; color: var(--color-faint); transition: color 0.2s ease; }
  .pp-acct.is-on .pp-acct-says { color: color-mix(in srgb, var(--color-accent) 70%, var(--color-ink)); }

  /* How often: the slider, and the number with the word for it. */
  .pp-often { display: flex; align-items: center; gap: 14px; transition: opacity 0.2s ease; }
  .pp-often.is-off { opacity: 0.45; }
  .pp-often .slider { flex: 1; min-width: 0; }
  .pp-often-val { display: flex; min-width: 92px; flex-direction: column; font-size: 11px; line-height: 1.3; color: var(--color-faint); }
  .pp-often-val b { font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--color-ink); }

  /* The phone, with what it would send on its screen. */
  .pp-phone {
    position: relative;
    width: 232px;
    aspect-ratio: 9 / 19;
    padding: 7px;
    border-radius: 36px;
    background: linear-gradient(155deg, #34343c, #101014 55%, #1c1c22);
    box-shadow:
      inset 0 0 0 1px rgb(255 255 255 / 0.14),
      inset 0 0 0 3px rgb(0 0 0 / 0.55),
      0 0 0 1px color-mix(in srgb, var(--color-edge) 60%, transparent),
      0 28px 56px -26px rgb(0 0 0 / 0.95);
    transition: transform 0.4s var(--jelly);
  }
  .pp-phone:hover { transform: translateY(-3px) rotate(-1deg); }
  /* The camera, an island at the top. */
  .pp-phone::before {
    content: "";
    position: absolute;
    top: 15px;
    left: 50%;
    z-index: 3;
    width: 66px;
    height: 19px;
    border-radius: 999px;
    background: #000;
    transform: translateX(-50%);
  }
  .pp-phone-screen {
    position: relative;
    display: grid;
    width: 100%;
    height: 100%;
    place-items: center;
    overflow: hidden;
    border-radius: 29px;
    background: #0b0b0e;
  }
  .pp-snap {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    transition: filter 0.3s ease, opacity 0.3s ease;
    animation: pp-snap-in 0.55s var(--jelly);
  }
  /* A picture just made comes onto the screen like a snap opening. */
  @keyframes pp-snap-in { from { opacity: 0; transform: scale(1.08); } }
  .pp-snap.is-plain { opacity: 0.55; filter: saturate(0.85); animation: none; }
  .pp-snap.is-veiled { filter: blur(18px) saturate(0.7); }
  .pp-phone:hover .pp-snap.is-veiled { filter: none; }
  .pp-phone-hint, .pp-phone-empty {
    position: relative;
    z-index: 2;
    display: flex;
    max-width: 80%;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 600;
    text-align: center;
    color: #fff;
    background: rgb(8 8 16 / 0.5);
    backdrop-filter: blur(8px);
  }
  .pp-phone-empty { border-radius: 14px; background: transparent; color: rgb(255 255 255 / 0.6); }
  /* Asking: a light passing down the screen. */
  .pp-phone-shimmer {
    position: absolute;
    inset: 0;
    z-index: 2;
    background: linear-gradient(180deg, transparent 30%, rgb(255 255 255 / 0.16) 50%, transparent 70%);
    background-size: 100% 220%;
    animation: pp-shimmer 1.1s ease-in-out infinite;
  }
  @keyframes pp-shimmer { from { background-position: 0 120%; } to { background-position: 0 -120%; } }
  .pp-said {
    max-width: 232px;
    padding: 5px 12px;
    border-radius: 999px;
    font-size: 12px;
    text-align: center;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 80%, transparent);
    animation: pp-said-in 0.4s var(--jelly);
  }
  @keyframes pp-said-in { from { opacity: 0; transform: translateY(-4px) scale(0.96); } }
  .pp-try-buttons { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; }

  :global(:root[data-motion="off"]) .pp-mode,
  :global(:root[data-motion="off"]) .pp-look-tile,
  :global(:root[data-motion="off"]) .pp-acct,
  :global(:root[data-motion="off"]) .pp-phone,
  :global(:root[data-motion="off"]) .pp-snap,
  :global(:root[data-motion="off"]) .pp-said,
  :global(:root[data-motion="off"]) .pp-phone-shimmer { transition: none; animation: none; }
</style>
