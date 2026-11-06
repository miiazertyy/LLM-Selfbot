<script lang="ts">
  /**
   * What you shared: each profile live in the community with its downloads, whether you changed it since, and what
   * you sent lately and how each went (checking, live, refused and why). Send an update or remove one from here.
   */
  import { onMount } from "svelte";
  import Button from "../components/Button.svelte";
  import Icon from "../components/Icon.svelte";
  import PersonaOrb from "../personas/PersonaOrb.svelte";
  import { api } from "../api";
  import { ask } from "../ask";
  import { visiblePoll } from "../poll";
  import { play } from "../uisound";
  import { toast } from "../stores";
  import { openGitHub } from "../window";
  import { domino } from "../domino";
  import SignInPanel from "./SignInPanel.svelte";
  import { communityMineRes } from "./store";
  import { appFit, compact, requestLine, timeAgo } from "./logic";
  import type { Persona } from "../personas/logic";

  let { personas = [], onshare, app = "" }: {
    personas?: Persona[];
    onshare: (pid: string) => void;
    /** Your app's version: one you shared from an older one is worth sending again. */
    app?: string;
  } = $props();

  const mine = $derived($communityMineRes.data);
  const byPid = $derived(Object.fromEntries(personas.map((p) => [p.id, p])));
  const pending = $derived(mine.requests.some((r) => r.state === "checking"));

  onMount(() => {
    communityMineRes.refresh({ force: true, quiet: true });
    // Only while something you sent is being checked: the issue is read with your token each time.
    return visiblePoll(() => {
      if (pending) communityMineRes.refresh({ force: true, quiet: true });
    }, 5000);
  });

  let seen = new Map<number, string>();
  $effect(() => {
    for (const r of mine.requests) {
      const was = seen.get(r.number);
      seen.set(r.number, r.state);
      if (!was || was === r.state) continue;
      if (r.state === "published") {
        play("medal");
        play("glint", { delay: 200, strong: true });
        toast(`${r.slug} is live.`, "ok");
      } else if (r.state === "refused") {
        play("err", { level: 0.5 });
      }
    }
  });

  async function remove(slug: string) {
    if (!(await ask(`Take ${slug} out of the community?`, { yes: "Remove it", danger: true,
                                                          detail: "Copies people already added stay theirs." }))) return;
    try {
      await api.communityRemove(slug);
      play("delete");
      play("slide", { delay: 120, level: 0.5 });
      toast("Asked to remove it. It goes in a minute.", "ok");
      communityMineRes.refresh({ force: true, quiet: true });
    } catch (e: any) {
      play("err", { level: 0.6 });
      toast(e?.message || "It couldn't be removed.", "err");
    }
  }
</script>

<div class="ms">
  {#if !mine.signed_in}
    <div class="ms-signin">
      <p>Sign in to share your profiles and follow what you sent.</p>
      <SignInPanel onsignedin={() => communityMineRes.refresh({ force: true })} />
    </div>
  {/if}

  <div class="ms-head">
    <h3>Your shared profiles</h3>
    <Button size="sm" onclick={() => { play("open"); onshare("*"); }}><Icon name="upload" size={12} />Share one</Button>
  </div>
  {#if mine.profiles.length}
    <div class="ms-list domino" use:domino={{ step: 60, sound: "pluck", max: 10 }}>
      {#each mine.profiles as s (s.slug)}
        {@const p = byPid[s.pid]}
        {@const fit = s.live ? appFit(s.app, app) : ""}
        <div class="ms-row" style="--pc: {p?.color || 'var(--color-accent)'}">
          <PersonaOrb p={p ?? { name: s.slug, color: "", avatar: "" }} size={40} />
          <span class="ms-who">
            <b>{p?.name ?? s.slug}</b>
            <small>{s.live ? `Live, v${s.version}` : "Not in the catalog"}{#if fit === "same"}<span class="ms-fit is-good">{" · up to date"}</span>{:else if fit === "older"}<span class="ms-fit is-warn" title="Made with app {s.app}, older than yours ({app})">{" · made with an older app"}</span>{/if}{s.changed ? " · changed since you shared it" : ""}</small>
          </span>
          <span class="ms-num"><b>{compact(s.downloads)}</b>downloads</span>
          <span class="ms-num"><b>{compact(s.week)}</b>this week</span>
          <span class="ms-acts">
            {#if p}<Button size="sm" kind={s.changed || fit === "older" ? "primary" : "ghost"} onclick={() => { play("open"); onshare(s.pid); }}>Send update</Button>{/if}
            <button type="button" class="ms-x" data-sound="self" title="Take it out of the community" aria-label="Remove {s.slug}"
                    onclick={() => { play("open"); remove(s.slug); }}><Icon name="trash" size={13} /></button>
          </span>
        </div>
      {/each}
    </div>
  {:else}
    <p class="ms-none">Nothing shared yet. Share one of yours from its card's menu, or here.</p>
  {/if}

  {#if mine.requests.length}
    <h3 class="ms-h">What you sent</h3>
    <ul class="ms-reqs">
      {#each mine.requests as r (r.number)}
        {@const line = requestLine(r)}
        <li class="is-{line.tone}">
          <span class="ms-dot"></span>
          <span class="ms-what"><b>{r.slug}</b> {r.action === "remove" ? "removal" : r.action === "update" ? "update" : "share"}, {timeAgo(new Date(r.sent * 1000).toISOString())}</span>
          <span class="ms-state">{line.text}</span>
          <button type="button" class="ms-link" data-sound="self" onclick={() => { play("open"); openGitHub("issue", { number: r.number }); }}>On GitHub</button>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .ms { display: flex; flex-direction: column; gap: 12px; }
  .ms-signin { padding: 14px; border-radius: 16px; background: rgb(255 255 255 / 0.025); box-shadow: inset 0 0 0 1px var(--color-edge); }
  .ms-signin p { margin: 0 0 10px; font-size: 12.5px; color: var(--color-muted); }
  .ms-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .ms-head h3, .ms-h { margin: 0; font-size: 14px; font-weight: 650; color: var(--color-ink); }
  .ms-list { display: grid; gap: 8px; }
  .ms-row { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 16px;
            background: radial-gradient(100% 140% at 0% 0%, color-mix(in srgb, var(--pc) 12%, transparent), transparent 60%), var(--color-card);
            box-shadow: inset 0 0 0 1px var(--color-edge); }
  .ms-who { display: flex; min-width: 140px; flex: 1; flex-direction: column; }
  .ms-who b { font-size: 13.5px; color: var(--color-ink); }
  .ms-who small { font-size: 11.5px; color: var(--color-faint); }
  .ms-fit.is-good { color: var(--color-good); }
  .ms-fit.is-warn { color: var(--color-warn); }
  .ms-num { display: flex; flex-direction: column; align-items: flex-end; font-size: 10.5px; color: var(--color-faint); }
  .ms-num b { font-size: 16px; color: var(--color-ink); font-variant-numeric: tabular-nums; }
  .ms-acts { display: flex; align-items: center; gap: 6px; }
  .ms-x { display: grid; width: 30px; height: 30px; place-items: center; border-radius: 10px; color: var(--color-faint);
          transition: background-color 0.15s ease, color 0.15s ease; }
  .ms-x:hover { color: var(--color-bad); background: color-mix(in srgb, var(--color-bad) 10%, transparent); }
  .ms-none { margin: 0; font-size: 12.5px; color: var(--color-faint); }
  .ms-reqs { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; }
  .ms-reqs li { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 12px; font-size: 12.5px;
                color: var(--color-muted); background: rgb(255 255 255 / 0.02); }
  .ms-dot { width: 8px; height: 8px; border-radius: 999px; background: var(--color-faint); }
  .is-good .ms-dot { background: var(--color-good); box-shadow: 0 0 8px var(--color-good); }
  .is-bad .ms-dot { background: var(--color-bad); }
  .is-busy .ms-dot { background: var(--color-accent); animation: ms-beat 1.2s ease-in-out infinite; }
  @keyframes ms-beat { 50% { opacity: 0.35; } }
  .ms-what { flex: 1; min-width: 160px; }
  .ms-what b { color: var(--color-ink); }
  .ms-state { color: var(--color-ink); }
  .is-bad .ms-state { color: var(--color-bad); }
  .ms-link { font-size: 11.5px; color: var(--color-accent); }
  :global(:root[data-motion="off"]) .is-busy .ms-dot { animation: none; }
  :global(:root[data-motion="off"]) .ms-x { transition: none; }
</style>
