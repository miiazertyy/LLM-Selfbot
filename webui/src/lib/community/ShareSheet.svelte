<script lang="ts">
  /**
   * Sharing one of your profiles to the community, or sending an update of one you shared. Three steps: its
   * details; what goes with it (the pictures and videos you pick, the settings you tick); and a check that shows
   * exactly what becomes public, says what never leaves, and points out anything to look at. Then sign in with
   * GitHub if you haven't, and send. The app follows it until it is live, or says why not.
   */
  import Modal from "../components/Modal.svelte";
  import Button from "../components/Button.svelte";
  import Icon from "../components/Icon.svelte";
  import Toggle from "../components/Toggle.svelte";
  import PersonaOrb from "../personas/PersonaOrb.svelte";
  import { api } from "../api";
  import { visiblePoll } from "../poll";
  import { play } from "../uisound";
  import { toast } from "../stores";
  import { openGitHub } from "../window";
  import RiskText from "./RiskText.svelte";
  import SignInPanel from "./SignInPanel.svelte";
  import { requestLine, sizeText, SLUG, slugFrom, valueText } from "./logic";
  import type { Persona } from "../personas/logic";

  let { pid = $bindable(""), personas = [], onsent }: {
    /** The profile to share; "*" to pick one first. */
    pid?: string;
    personas?: Persona[];
    onsent?: () => void;
  } = $props();

  type Form = {
    pid: string; action: string; slug: string; name: string; tagline: string; color: string; author: string;
    language: string; tags: string[]; adult: boolean; has_avatar: boolean; shared: any;
    settings: { key: string; label: string; value: unknown; own: boolean; trigger: boolean }[];
    never: { label: string; count: number }[]; media: { name: string; video: boolean; bytes: number }[];
    limits: { pictures: number; videos: number; video_seconds: number }; tags_allowed: string[];
  };

  let step = $state(0);
  let form = $state<Form | null>(null);
  let error = $state("");
  let picked = $state<string[]>([]);
  let ticked = $state<string[]>([]);
  let description = $state("");
  let note = $state("");
  let slugEdited = $state(false);
  let ids = $state<Record<string, string>>({});
  let preview = $state<any>(null);
  let checking = $state(false);
  let checked = $state(false);
  let sending = $state(false);
  let sent = $state<{ number: number } | null>(null);
  let result = $state<{ text: string; tone: string } | null>(null);
  let signedIn = $state(false);
  let stopFollow: (() => void) | null = null;

  const open = $derived(!!pid);
  const target = $derived(pid === "*" ? "" : pid);
  const personaArg = $derived(target === "default" ? "" : target);
  const pickable = $derived(personas.filter((p) => !p.community));

  let loadedFor = "";
  $effect(() => {
    const id = target;
    if (!id || id === loadedFor) return;
    loadedFor = id;
    reset();
    api.communityShareForm(id).then((f: Form) => {
      if (target !== id) return;
      form = f;
      ticked = f.settings.filter((s) => s.own || s.trigger).map((s) => s.key);
      slugEdited = !!f.shared;
    }).catch((e: any) => { if (target === id) error = e?.message || "It couldn't be opened."; });
    api.pictures(id === "default" ? "" : id).then((r: any) => {
      ids = Object.fromEntries((r?.pictures ?? []).map((x: any) => [x.name, x.id ?? ""]));
    }).catch(() => {});
    api.githubSignin().then((s: any) => (signedIn = !!s?.me?.signed_in)).catch(() => {});
  });

  function reset() {
    step = 0; form = null; error = ""; picked = []; ticked = []; description = ""; note = ""; preview = null;
    checked = false; sent = null; result = null; stopFollow?.(); stopFollow = null;
  }

  function close() {
    stopFollow?.();
    stopFollow = null;
    pid = "";
    loadedFor = "";
  }

  function choose(p: Persona) {
    play("select");
    pid = p.id;
  }

  const pics = $derived(form ? form.media.filter((m) => picked.includes(m.name) && !m.video).length : 0);
  const vids = $derived(form ? form.media.filter((m) => picked.includes(m.name) && m.video).length : 0);

  function togglePick(name: string, video: boolean) {
    if (!form) return;
    if (picked.includes(name)) {
      picked = picked.filter((n) => n !== name);
      play("off", { level: 0.5 });
      return;
    }
    if (video ? vids >= form.limits.videos : pics >= form.limits.pictures) {
      play("err", { level: 0.4 });
      toast(video ? `At most ${form.limits.videos} videos.` : `At most ${form.limits.pictures} pictures.`, "info");
      return;
    }
    picked = [...picked, name];
    play("on", { level: 0.5 });
  }

  function toggleSetting(key: string, on: boolean) {
    ticked = on ? [...ticked, key] : ticked.filter((k) => k !== key);
  }

  function body() {
    if (!form) return {};
    return { slug: form.slug, name: form.name, tagline: form.tagline, description, tags: form.tags, color: form.color,
             author: form.author, adult: form.adult, language: form.language, note, settings: ticked, media: picked,
             checked };
  }

  function setName(v: string) {
    if (!form) return;
    form.name = v;
    if (!slugEdited) form.slug = slugFrom(v);
  }

  function toggleTag(t: string) {
    if (!form) return;
    if (form.tags.includes(t)) {
      form.tags = form.tags.filter((x) => x !== t);
      play("off", { level: 0.5 });
    } else if (form.tags.length < 5) {
      form.tags = [...form.tags, t];
      play("on", { level: 0.5 });
    }
  }

  async function go(n: number) {
    play("select");
    step = n;
    if (n === 2) await check();
  }

  async function check() {
    if (!form) return;
    checking = true;
    try {
      preview = await api.communitySharePreview(form.pid, body());
      if (preview.warnings.length || preview.problems.length) play("info", { level: 0.5 });
    } catch (e: any) {
      preview = null;
      error = e?.message || "It couldn't be checked.";
    } finally {
      checking = false;
    }
  }

  async function send() {
    if (!form || !preview?.ready) return;
    sending = true;
    play("tap");
    try {
      const r: any = await api.communityShare(form.pid, body());
      sent = r;
      play("send");
      result = { text: "Sent. The checks run in a moment.", tone: "busy" };
      follow(r.number);
      onsent?.();
    } catch (e: any) {
      play("err", { level: 0.6 });
      toast(e?.message || "It couldn't be sent.", "err");
    } finally {
      sending = false;
    }
  }

  /** Following what you sent until it is live, or refused and why. */
  function follow(number: number) {
    stopFollow?.();
    stopFollow = visiblePoll(async () => {
      const m: any = await api.communityMine(true);
      const r = (m?.requests ?? []).find((x: any) => x.number === number);
      if (!r || r.state === "checking") return;
      result = requestLine(r);
      stopFollow?.();
      stopFollow = null;
      if (r.state === "published") {
        play("medal");
        play("glint", { delay: 200, strong: true });
      } else {
        play("err", { level: 0.6 });
      }
      onsent?.();
    }, 3000);
  }

  const STEPS = ["Details", "What goes with it", "Check and send"];
  const slugOk = $derived(!!form && SLUG.test(form.slug) && form.slug.length >= 3 && form.slug.length <= 32);
  const canNext = $derived(!!form && form.name.trim().length > 0 && slugOk && form.author.trim().length >= 2);
</script>

<Modal {open} wide title={form ? (form.action === "update" ? `Update ${form.name} in the community` : `Share ${form.name}`) : "Share a profile"} onclose={close}>
  {#if pid === "*"}
    <p class="sh-say">Which of your profiles?</p>
    <div class="sh-pick">
      {#each pickable as p (p.id)}
        <button type="button" class="sh-pick-btn" data-sound="self" onclick={() => choose(p)} style="--pc: {p.color || 'var(--color-accent)'}">
          <PersonaOrb {p} size={40} /><span><b>{p.name}</b><small>{p.shared ? `Shared as ${p.shared.slug}` : p.line || "Not shared yet"}</small></span>
        </button>
      {:else}
        <p class="sh-note">Your profiles that came from the community can't be shared again.</p>
      {/each}
    </div>
  {:else if error}
    <p class="sh-bad">{error}</p>
  {:else if !form}
    <p class="sh-note">Getting it ready</p>
  {:else}
    <ol class="sh-steps" style="--at: {step}">
      {#each STEPS as s, i (s)}
        <li class:is-on={i === step} class:is-done={i < step}><i>{i < step ? "✓" : i + 1}</i>{s}</li>
      {/each}
    </ol>

    {#if step === 0}
      <div class="sh-grid">
        <label class="sh-field"><span>Name</span>
          <input value={form.name} oninput={(e) => setName((e.target as HTMLInputElement).value)} maxlength="40" /></label>
        <label class="sh-field"><span>Short name</span>
          <input value={form.slug} disabled={form.action === "update"} maxlength="32" class:is-bad={!slugOk}
                 oninput={(e) => { slugEdited = true; form!.slug = (e.target as HTMLInputElement).value.toLowerCase(); }} />
          <small>{form.action === "update" ? "It keeps its short name." : "Letters, numbers and dashes. Its address in the catalog."}</small></label>
        <label class="sh-field is-wide"><span>One line about it</span>
          <input bind:value={form.tagline} maxlength="90" placeholder="Night owl who texts in lowercase" /></label>
        <label class="sh-field is-wide"><span>More about it (optional)</span>
          <textarea bind:value={description} maxlength="600" rows="3"></textarea></label>
        <label class="sh-field"><span>Shown as made by</span>
          <input bind:value={form.author} maxlength="32" placeholder="A name you pick" />
          <small>Not your GitHub name.</small></label>
        {#if form.action === "update"}
          <label class="sh-field"><span>What changed</span>
            <input bind:value={note} maxlength="200" placeholder="Calmer moods" /></label>
        {/if}
        <div class="sh-field is-wide"><span>Tags</span>
          <div class="sh-tags" data-sound="self">
            {#each form.tags_allowed as t (t)}
              <button type="button" class="sh-tag" class:is-on={form.tags.includes(t)} onclick={() => toggleTag(t)}>{t}</button>
            {/each}
          </div></div>
        <div class="sh-field is-wide sh-row"><Toggle bind:checked={form.adult} label="For adults (18+)" size="sm" />
          <small>Hidden in the catalog unless someone asks to see 18+.</small></div>
      </div>
      <div class="sh-actions">
        <Button kind="ghost" size="sm" onclick={() => { play("off"); close(); }}>Cancel</Button>
        <Button size="sm" onclick={() => go(1)} disabled={!canNext}>Next<Icon name="chevron" size={12} /></Button>
      </div>
    {:else if step === 1}
      <h4 class="sh-h">Pictures and videos <small>{pics} of {form.limits.pictures} pictures, {vids} of {form.limits.videos} videos (up to {form.limits.video_seconds | 0} s each)</small></h4>
      {#if form.media.length}
        <div class="sh-media" data-sound="self">
          {#each form.media as m (m.name)}
            <button type="button" class="sh-tile" class:is-on={picked.includes(m.name)} onclick={() => togglePick(m.name, m.video)}
                    title="{m.name} · {sizeText(m.bytes)}">
              <img src={api.pictureSmall({ name: m.name, id: ids[m.name], video: m.video }, 160, personaArg)} alt="" loading="lazy" />
              {#if m.video}<i class="sh-vid"><Icon name="play" size={9} /></i>{/if}
              <span class="sh-check"><Icon name="check" size={11} /></span>
            </button>
          {/each}
        </div>
      {:else}
        <p class="sh-note">It has no pictures or videos. That's fine.</p>
      {/if}
      <h4 class="sh-h">Settings that come with it <small>Who it is and how it talks, nothing else</small></h4>
      <ul class="sh-settings">
        {#each form.settings as s (s.key)}
          <li><Toggle checked={ticked.includes(s.key)} size="sm" name={s.label} onchange={(v) => toggleSetting(s.key, v)} />
            <span>{s.label}</span><small>{valueText(s.value)}{s.own ? "" : " (everyone's)"}</small></li>
        {/each}
      </ul>
      {#if form.never.length}
        <details class="sh-never"><summary data-sound="self" onclick={() => play("open", { level: 0.4 })}>Never shared</summary>
          <ul>{#each form.never as n (n.label)}<li>{n.label}</li>{/each}</ul>
          <p>Nor its memory, chats, accounts, keys, or the pictures you didn't pick.</p>
        </details>
      {/if}
      <div class="sh-actions">
        <Button kind="ghost" size="sm" onclick={() => go(0)}>Back</Button>
        <Button size="sm" onclick={() => go(2)}>Check it<Icon name="chevron" size={12} /></Button>
      </div>
    {:else}
      {#if checking || !preview}
        <p class="sh-note">Checking it</p>
      {:else}
        <p class="sh-public"><Icon name="globe" size={12} />This goes public. Everything you send is public on GitHub.</p>
        <div class="sh-summary">
          <b>{preview.public.meta.name}</b> by {preview.public.meta.author}
          <span>{preview.public.words} words · {preview.public.settings.length} settings · {preview.public.media.length} pictures and videos{preview.public.avatar ? " · its face" : ""}</span>
        </div>
        <div class="sh-text"><RiskText segments={preview.segments} /></div>
        {#if preview.problems.length}
          <ul class="sh-problems">{#each preview.problems as p (p)}<li><Icon name="close" size={11} />{p}</li>{/each}</ul>
        {/if}
        {#if preview.warnings.length}
          <ul class="sh-warnings">{#each preview.warnings as w (w)}<li><Icon name="alert" size={11} />{w}</li>{/each}</ul>
        {/if}
        {#if preview.needs_check}
          <div class="sh-row"><Toggle bind:checked={checked} size="sm" label="I checked the highlighted parts" /></div>
        {/if}
        {#if !signedIn}
          <SignInPanel onsignedin={() => (signedIn = true)} />
        {/if}
        {#if result}
          <p class="sh-result is-{result.tone}">{result.text}
            {#if sent}<button type="button" class="sh-link" data-sound="self" onclick={() => { play("open"); openGitHub("issue", { number: sent!.number }); }}>See it on GitHub</button>{/if}</p>
        {/if}
        <div class="sh-actions">
          <Button kind="ghost" size="sm" onclick={() => go(1)} disabled={sending || !!sent}>Back</Button>
          {#if sent}
            <Button size="sm" onclick={() => { play("off"); close(); }}>Done</Button>
          {:else}
            <Button size="sm" onclick={send} loading={sending}
                    disabled={!preview.ready || !signedIn || (preview.needs_check && !checked)}>
              <Icon name="send" size={12} />{preview.action === "update" ? "Send the update" : "Share it"}
            </Button>
          {/if}
        </div>
      {/if}
    {/if}
  {/if}
</Modal>

<style>
  .sh-say { margin: 0 0 10px; font-size: 13px; color: var(--color-muted); }
  .sh-pick { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
  .sh-pick-btn { display: flex; align-items: center; gap: 10px; padding: 10px; border-radius: 14px; text-align: left;
                 background: rgb(255 255 255 / 0.03); box-shadow: inset 0 0 0 1px var(--color-edge); transition: box-shadow 0.2s ease, transform 0.2s var(--spring); }
  .sh-pick-btn:hover { transform: translateY(-1px); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--pc) 50%, transparent); }
  .sh-pick-btn span { display: flex; min-width: 0; flex-direction: column; }
  .sh-pick-btn b { font-size: 13.5px; color: var(--color-ink); }
  .sh-pick-btn small { overflow: hidden; font-size: 11.5px; color: var(--color-faint); text-overflow: ellipsis; white-space: nowrap; }
  .sh-steps { display: flex; gap: 8px; margin: 0 0 16px; padding: 0; list-style: none; }
  .sh-steps li { display: inline-flex; align-items: center; gap: 7px; padding: 5px 11px 5px 6px; border-radius: 999px; font-size: 12px;
                 color: var(--color-faint); background: rgb(255 255 255 / 0.03); transition: color 0.2s ease, background-color 0.2s ease; }
  .sh-steps li i { display: grid; width: 20px; height: 20px; place-items: center; border-radius: 999px; font-size: 11px; font-style: normal;
                   background: rgb(255 255 255 / 0.06); }
  .sh-steps li.is-on { color: var(--color-ink); background: color-mix(in srgb, var(--color-accent) 16%, transparent); }
  .sh-steps li.is-on i, .sh-steps li.is-done i { color: #fff; background: var(--color-accent); }
  .sh-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .sh-field { display: flex; min-width: 0; flex-direction: column; gap: 5px; font-size: 12px; color: var(--color-muted); }
  .sh-field.is-wide { grid-column: 1 / -1; }
  .sh-field > span { font-weight: 600; }
  .sh-field small { font-size: 11px; color: var(--color-faint); }
  .sh-field input, .sh-field textarea { padding: 8px 11px; border-radius: 11px; font-size: 13px; color: var(--color-ink);
                                        background: rgb(0 0 0 / 0.22); box-shadow: inset 0 0 0 1px var(--color-edge); outline: none; resize: vertical; }
  .sh-field input:focus, .sh-field textarea:focus { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, transparent); }
  .sh-field input.is-bad { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-bad) 60%, transparent); }
  .sh-field input:disabled { opacity: 0.6; }
  .sh-row { display: flex; flex-direction: row; flex-wrap: wrap; align-items: center; justify-content: flex-start; gap: 10px; }
  .sh-tags { display: flex; flex-wrap: wrap; gap: 5px; }
  .sh-tag { padding: 4px 11px; border-radius: 999px; font-size: 12px; color: var(--color-muted); background: rgb(255 255 255 / 0.03);
            box-shadow: inset 0 0 0 1px var(--color-edge); transition: background-color 0.15s ease, color 0.15s ease, transform 0.2s var(--spring); }
  .sh-tag.is-on { color: var(--color-ink); background: color-mix(in srgb, var(--color-accent) 20%, transparent);
                  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 50%, transparent); }
  .sh-tag:active { transform: scale(0.95); }
  .sh-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
  .sh-h { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; margin: 4px 0 10px; font-size: 13px; color: var(--color-ink); }
  .sh-h small { font-size: 11.5px; font-weight: 400; color: var(--color-faint); }
  .sh-media { display: grid; grid-template-columns: repeat(auto-fill, minmax(84px, 1fr)); gap: 8px; margin-bottom: 14px; }
  .sh-tile { position: relative; overflow: hidden; border-radius: 12px; aspect-ratio: 1; background: rgb(0 0 0 / 0.3);
             box-shadow: inset 0 0 0 1px var(--color-edge); transition: transform 0.2s var(--spring), box-shadow 0.2s ease; }
  .sh-tile img { width: 100%; height: 100%; object-fit: cover; opacity: 0.55; transition: opacity 0.2s ease; }
  .sh-tile.is-on { box-shadow: 0 0 0 2px var(--color-accent), 0 8px 20px -10px var(--color-accent); }
  .sh-tile.is-on img { opacity: 1; }
  .sh-tile:active { transform: scale(0.96); }
  .sh-vid { position: absolute; left: 6px; bottom: 6px; display: grid; width: 18px; height: 18px; place-items: center; border-radius: 999px;
            font-style: normal; color: #fff; background: rgb(0 0 0 / 0.6); }
  .sh-check { position: absolute; top: 6px; right: 6px; display: grid; width: 20px; height: 20px; place-items: center; border-radius: 999px;
              color: #fff; background: var(--color-accent); opacity: 0; transform: scale(0.6); transition: opacity 0.2s ease, transform 0.25s var(--spring); }
  .sh-tile.is-on .sh-check { opacity: 1; transform: none; }
  .sh-settings { display: grid; gap: 4px; margin: 0 0 12px; padding: 0; list-style: none; }
  .sh-settings li { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 10px; padding: 6px 8px;
                    border-radius: 10px; font-size: 12.5px; color: var(--color-ink); background: rgb(255 255 255 / 0.02); }
  .sh-settings small { overflow: hidden; max-width: 220px; color: var(--color-faint); text-overflow: ellipsis; white-space: nowrap; }
  .sh-never { font-size: 12px; color: var(--color-faint); }
  .sh-never summary { cursor: pointer; color: var(--color-muted); }
  .sh-never ul { margin: 6px 0; padding-left: 18px; }
  .sh-never p { margin: 0; }
  .sh-public { display: flex; align-items: center; gap: 7px; margin: 0 0 10px; padding: 8px 12px; border-radius: 12px; font-size: 12.5px;
               color: var(--color-ink); background: color-mix(in srgb, var(--color-warn) 10%, transparent);
               box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-warn) 30%, transparent); }
  .sh-summary { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; margin-bottom: 8px; font-size: 13px; color: var(--color-muted); }
  .sh-summary b { color: var(--color-ink); }
  .sh-summary span { width: 100%; font-size: 12px; color: var(--color-faint); }
  .sh-text { max-height: 220px; overflow: auto; padding: 10px 12px; border-radius: 12px; background: rgb(0 0 0 / 0.2); box-shadow: inset 0 0 0 1px var(--color-edge); }
  .sh-problems, .sh-warnings { display: grid; gap: 4px; margin: 10px 0 0; padding: 0; list-style: none; font-size: 12.5px; }
  .sh-problems li { display: flex; gap: 6px; color: var(--color-bad); }
  .sh-warnings li { display: flex; gap: 6px; color: var(--color-warn); }
  .sh-result { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 12px 0 0; padding: 10px 12px; border-radius: 12px; font-size: 13px; }
  .sh-result.is-busy { color: var(--color-ink); background: color-mix(in srgb, var(--color-accent) 10%, transparent); }
  .sh-result.is-good { color: var(--color-good); background: color-mix(in srgb, var(--color-good) 12%, transparent); }
  .sh-result.is-bad { color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 10%, transparent); }
  .sh-link { font-size: 12px; color: var(--color-accent); text-decoration: underline; text-underline-offset: 2px; }
  .sh-note { font-size: 12.5px; color: var(--color-faint); }
  .sh-bad { font-size: 13px; color: var(--color-bad); }
  @media (max-width: 560px) { .sh-grid { grid-template-columns: minmax(0, 1fr); } .sh-steps { flex-wrap: wrap; } }
  :global(:root[data-motion="off"]) .sh-tile, :global(:root[data-motion="off"]) .sh-tile img,
  :global(:root[data-motion="off"]) .sh-check, :global(:root[data-motion="off"]) .sh-tag,
  :global(:root[data-motion="off"]) .sh-steps li, :global(:root[data-motion="off"]) .sh-pick-btn { transition: none; }
</style>
