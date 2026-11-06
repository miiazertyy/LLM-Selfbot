<script lang="ts">
  /**
   * Everything that would come with a community profile, before adding it: its text (risky parts lit), each setting
   * beside yours and what it can't bring, its pictures and videos, its versions, and its downloads. Adding it makes
   * it one of your profiles; your accounts, models, keys and limits stay as they are.
   */
  import Modal from "../components/Modal.svelte";
  import Button from "../components/Button.svelte";
  import Icon from "../components/Icon.svelte";
  import PersonaOrb from "../personas/PersonaOrb.svelte";
  import { api } from "../api";
  import { chime, domino } from "../domino";
  import { play } from "../uisound";
  import { toast } from "../stores";
  import { openGitHub } from "../window";
  import RiskText from "./RiskText.svelte";
  import SettingRows from "./SettingRows.svelte";
  import DownloadsChart from "./DownloadsChart.svelte";
  import { appWords, compact, plural, riskLabel, timeAgo, type CommunityHome } from "./logic";
  import type { CommunityStats } from "./store";

  let { slug = $bindable(""), home, stats, oninstalled, onupdate }: {
    slug?: string;
    home: CommunityHome;
    stats: CommunityStats;
    oninstalled?: (pid: string) => void;
    onupdate?: (pid: string) => void;
  } = $props();

  let data = $state<any>(null);
  let error = $state("");
  let busy = $state(false);
  let reporting = $state(false);
  let reason = $state("A scam or a trick");
  let details = $state("");
  const REASONS = ["A scam or a trick", "Someone's private info", "A real person without their consent",
                   "Hate or harassment", "Sexual content involving minors", "Copied from someone else", "Something else"];

  const open = $derived(!!slug);
  let loadedFor = "";
  $effect(() => {
    const s = slug;
    if (!s || s === loadedFor) return;
    loadedFor = s;
    data = null;
    error = "";
    reporting = false;
    api.communityProfile(s).then((d) => {
      if (slug !== s) return;
      data = d;
    }).catch((e: any) => {
      if (slug !== s) return;
      error = e?.message || "It couldn't be opened.";
      play("err", { level: 0.5 });
    });
  });

  function close() {
    slug = "";
    loadedFor = "";
  }

  const p = $derived(data?.profile ?? null);
  const face = $derived(p ? { name: p.name, color: p.color, avatar: p.avatar ? api.communityFile(p.slug, "avatar.jpg", p.version) : "" } : null);
  const mine = $derived(p ? home.installed[p.slug] : undefined);
  /** Whether it was made for the app you have. */
  const fit = $derived(appWords(p?.app, home.app));
  const daily = $derived(p ? stats.profiles?.[p.slug]?.daily ?? [] : []);
  const thumbs = $derived((p?.thumbs ?? []).map((t: string) => {
    const name = t.split("/").pop() ?? "";
    const m = (data?.media ?? []).find((x: any) => x.name.replace(/\.\w+$/, "") === name.replace(/\.\w+$/, ""));
    return { src: api.communityFile(p.slug, `thumbs/${name}`, p.version), video: m?.kind === "video", seconds: m?.seconds ?? 0 };
  }));

  async function add(copy = false) {
    if (!p || busy) return;
    busy = true;
    play("tap");
    try {
      const r: any = await api.communityInstall(p.slug, copy);
      play("done");
      play("glint", { delay: 180, strong: true });
      toast(`${p.name} is one of your profiles now.`, "ok");
      oninstalled?.(r.persona.id);
      close();
    } catch (e: any) {
      play("err", { level: 0.6 });
      toast(e?.message || "It couldn't be added.", "err");
    } finally {
      busy = false;
    }
  }

  async function report() {
    if (!p) return;
    if (!home.me.signed_in) {
      play("open");
      openGitHub("report", { slug: p.slug });
      return;
    }
    if (!reporting) {
      play("open");
      reporting = true;
      return;
    }
    busy = true;
    try {
      await api.communityReport(p.slug, reason, details);
      play("send");
      toast("Reported. A moderator will look at it.", "ok");
      reporting = false;
      details = "";
    } catch (e: any) {
      play("err", { level: 0.6 });
      toast(e?.message || "The report didn't go.", "err");
    } finally {
      busy = false;
    }
  }
</script>

<Modal {open} wide title={p ? p.name : "Community profile"} onclose={close}>
  {#if error}
    <p class="pi-error">{error}</p>
  {:else if !data}
    <div class="pi-wait"><span class="pi-spin" aria-hidden="true"></span>Opening it</div>
  {:else}
    <div class="pi" style="--pc: {p.color || 'var(--color-accent)'}">
      <header class="pi-head" use:chime={{ sound: "rise", delay: 60 }}>
        <span class="pi-orb" use:chime={{ sound: "land", delay: 160 }}><PersonaOrb p={face} size={68} ring /></span>
        <div class="pi-who">
          <h3>{p.name}</h3>
          <p class="pi-by">by {p.author || "someone"} · v{p.version}{#if p.updated}{" · "}updated {timeAgo(p.updated)}{/if}</p>
          {#if fit.long}<p class="pi-app is-{fit.tone || 'plain'}"><i></i>{fit.long}</p>{/if}
          {#if p.tagline}<p class="pi-line">{p.tagline}</p>{/if}
          <div class="pi-tags">
            {#each p.tags ?? [] as t (t)}<span>{t}</span>{/each}
            {#if p.adult}<span class="is-adult">18+</span>{/if}
          </div>
        </div>
        <div class="pi-nums">
          <span><b>{compact(p.downloads)}</b>downloads</span>
          <span><b>{compact(p.week)}</b>this week</span>
          <span><b>{compact(p.words ?? 0)}</b>words</span>
        </div>
      </header>

      <div class="pi-actions">
        {#if data.update && mine}
          <Button onclick={() => { play("open"); onupdate?.(mine.pid); close(); }}><Icon name="refresh" size={13} />Update to v{p.version}</Button>
          <Button kind="ghost" onclick={() => add(true)} loading={busy}>Add another copy</Button>
        {:else if mine}
          <span class="pi-have"><Icon name="check" size={13} />In your profiles</span>
          <Button kind="ghost" onclick={() => add(true)} loading={busy}>Add another copy</Button>
        {:else}
          <Button onclick={() => add(false)} loading={busy}><Icon name="plus" size={13} />Add to my profiles</Button>
        {/if}
        <span class="pi-grow"></span>
        <button type="button" class="pi-link" data-sound="self" onclick={report}><Icon name="alert" size={12} />Report</button>
        <button type="button" class="pi-link" data-sound="self" onclick={() => { play("open"); openGitHub("profile", { slug: p.slug }); }}>
          <Icon name="github" size={12} />On GitHub
        </button>
      </div>
      <p class="pi-safe"><Icon name="key" size={11} />Only how it talks comes with it. Your accounts, models, keys and limits stay yours.</p>

      {#if reporting}
        <div class="pi-report">
          <select bind:value={reason} aria-label="Why" onchange={() => play("select")}>
            {#each REASONS as r (r)}<option value={r}>{r}</option>{/each}
          </select>
          <input bind:value={details} maxlength="500" placeholder="What's wrong, in a line (optional)" aria-label="What's wrong" />
          <Button size="sm" kind="danger" onclick={report} loading={busy}>Send report</Button>
          <Button size="sm" kind="ghost" onclick={() => { play("off"); reporting = false; }}>Cancel</Button>
        </div>
      {/if}

      <div class="pi-sections domino" use:domino={{ step: 70, sound: "wind", level: 0.4 }}>
        <section>
          <h4>Who it is</h4>
          <RiskText segments={data.segments} />
          {#if data.flags.length}
            <p class="pi-flags"><Icon name="alert" size={11} />{data.flags.map((f: any) => riskLabel(f.kind)).join(", ")}: lit above.</p>
          {/if}
        </section>
        <section>
          <h4>How it talks</h4>
          <SettingRows rows={data.settings} />
        </section>
        {#if thumbs.length}
          <section>
            <h4>{plural(p.pictures ?? 0, "picture", "pictures")}{#if p.videos}, {plural(p.videos, "video", "videos")}{/if}</h4>
            <div class="pi-thumbs">
              {#each thumbs as t (t.src)}
                <span class="pi-thumb">
                  <img src={t.src} alt="" loading="lazy" />
                  {#if t.video}<i><Icon name="play" size={9} />{Math.round(t.seconds)}s</i>{/if}
                </span>
              {/each}
            </div>
          </section>
        {/if}
        <section>
          <h4>Downloads</h4>
          <DownloadsChart {daily} days={stats.days ?? []} color={p.color || "var(--color-accent)"} />
        </section>
        {#if data.changelog.length}
          <section>
            <h4>Versions</h4>
            <ol class="pi-versions">
              {#each data.changelog as c (c.version)}
                <li><b>v{c.version}</b><span>{c.note || "No note"}</span><small>{c.date}</small></li>
              {/each}
            </ol>
          </section>
        {/if}
      </div>
    </div>
  {/if}
</Modal>

<style>
  .pi { display: flex; flex-direction: column; gap: 14px; }
  .pi-head {
    display: flex; flex-wrap: wrap; align-items: center; gap: 14px 18px; padding: 16px; border-radius: 18px;
    background: radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, var(--pc) 20%, transparent), transparent 60%),
                rgb(255 255 255 / 0.02);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--pc) 22%, var(--color-edge));
  }
  .pi-who { min-width: 0; flex: 1; }
  .pi-who h3 { margin: 0; font-size: 19px; font-weight: 700; color: var(--color-ink); }
  .pi-by { margin: 2px 0 0; font-size: 12px; color: var(--color-faint); }
  /* Whether it was made for your app: a lit dot, and the sentence. */
  .pi-app { display: flex; align-items: center; gap: 7px; margin: 5px 0 0; font-size: 12px; color: var(--color-muted); }
  .pi-app i { width: 7px; height: 7px; flex-shrink: 0; border-radius: 999px; background: var(--color-faint); }
  .pi-app.is-good i { background: var(--color-good); box-shadow: 0 0 8px var(--color-good); }
  .pi-app.is-warn { color: var(--color-warn); }
  .pi-app.is-warn i { background: var(--color-warn); box-shadow: 0 0 8px var(--color-warn); }
  .pi-app.is-info i { background: var(--color-accent); box-shadow: 0 0 8px var(--color-accent); }
  .pi-line { margin: 6px 0 0; font-size: 13px; color: var(--color-muted); }
  .pi-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
  .pi-tags span { padding: 2px 9px; border-radius: 999px; font-size: 11px; color: var(--color-muted);
                  box-shadow: inset 0 0 0 1px var(--color-edge); }
  .pi-tags .is-adult { color: var(--color-warn); }
  .pi-nums { display: flex; gap: 16px; }
  .pi-nums span { display: flex; flex-direction: column; align-items: flex-end; font-size: 11px; color: var(--color-faint); }
  .pi-nums b { font-size: 18px; font-weight: 700; color: var(--color-ink); font-variant-numeric: tabular-nums; }
  .pi-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .pi-grow { flex: 1; }
  .pi-have { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 999px; font-size: 12.5px;
             color: var(--color-good); background: color-mix(in srgb, var(--color-good) 12%, transparent); }
  .pi-link { display: inline-flex; align-items: center; gap: 5px; padding: 6px 10px; border-radius: 10px; font-size: 12px;
             color: var(--color-muted); transition: background-color 0.15s ease, color 0.15s ease; }
  .pi-link:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.06); }
  .pi-safe { display: flex; align-items: center; gap: 6px; margin: -4px 0 0; font-size: 11.5px; color: var(--color-faint); }
  .pi-report { display: flex; flex-wrap: wrap; gap: 8px; padding: 10px; border-radius: 14px;
               background: color-mix(in srgb, var(--color-bad) 7%, transparent); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-bad) 25%, transparent); }
  .pi-report select, .pi-report input { min-width: 0; flex: 1 1 180px; padding: 7px 10px; border-radius: 10px; font-size: 12.5px;
                                        color: var(--color-ink); background: rgb(0 0 0 / 0.25); box-shadow: inset 0 0 0 1px var(--color-edge); }
  .pi-sections { display: grid; gap: 12px; }
  .pi-sections section { padding: 14px 16px; border-radius: 16px; background: rgb(255 255 255 / 0.025); box-shadow: inset 0 0 0 1px var(--color-edge); }
  .pi-sections h4 { margin: 0 0 10px; font-size: 11px; font-weight: 650; letter-spacing: 0.08em; text-transform: uppercase; color: var(--color-faint); }
  .pi-flags { display: flex; align-items: center; gap: 6px; margin: 10px 0 0; font-size: 11.5px; color: var(--color-warn); }
  .pi-thumbs { display: grid; grid-template-columns: repeat(auto-fill, minmax(92px, 1fr)); gap: 8px; }
  .pi-thumb { position: relative; overflow: hidden; border-radius: 12px; aspect-ratio: 1; background: rgb(0 0 0 / 0.3); }
  .pi-thumb img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.35s var(--swift); }
  .pi-thumb:hover img { transform: scale(1.05); }
  .pi-thumb i { position: absolute; right: 6px; bottom: 6px; display: inline-flex; align-items: center; gap: 3px; padding: 1px 6px;
                border-radius: 999px; font-size: 10px; font-style: normal; color: #fff; background: rgb(0 0 0 / 0.6); }
  .pi-versions { display: grid; gap: 6px; margin: 0; padding: 0; list-style: none; }
  .pi-versions li { display: grid; grid-template-columns: auto 1fr auto; gap: 10px; align-items: baseline; font-size: 12.5px; color: var(--color-muted); }
  .pi-versions b { color: var(--pc); }
  .pi-versions small { font-size: 11px; color: var(--color-faint); }
  .pi-wait { display: flex; align-items: center; gap: 10px; padding: 30px 0; font-size: 13px; color: var(--color-faint); }
  .pi-spin { width: 16px; height: 16px; border-radius: 999px; border: 2px solid var(--color-edge); border-top-color: var(--color-accent);
             animation: pi-spin 0.8s linear infinite; }
  @keyframes pi-spin { to { transform: rotate(360deg); } }
  .pi-error { padding: 20px 0; font-size: 13px; color: var(--color-bad); }
  :global(:root[data-motion="off"]) .pi-spin { animation: none; }
  :global(:root[data-motion="off"]) .pi-thumb img, :global(:root[data-motion="off"]) .pi-link { transition: none; }
</style>
