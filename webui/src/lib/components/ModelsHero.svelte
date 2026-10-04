<script lang="ts">
  /**
   * The top of each part of Settings > Models: its icon in a glowing orb with a
   * ring of light turning slowly round it, what it is for, and how things stand
   * there right now as a row of chips (how many models write replies, how many
   * providers are connected, whether the computer's server is running, how much
   * has been asked today). The chips pop in one after another as it opens, a
   * soft note each (lib/domino.ts), the orb with a thud of its own. The plain
   * header every other part of Settings has said only the part's name.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import { chime, domino } from "../domino";
  import { providerList, providersLoaded, savedPlan, shortModel } from "../providers";
  import { usage, loadUsage } from "../modelusage";
  import Icon from "./Icon.svelte";

  let { which, name, blurb = "", icon }: { which: string; name: string; blurb?: string; icon: string } = $props();

  type Chip = { icon: string; text: string; tone?: "good" | "warn" | "muted" };

  let local = $state<{ reachable: boolean; name: string; models: number; bytes: number } | null>(null);
  onMount(() => {
    if (which === "local") {
      api.localStatus().then((s: any) => {
        const sizes = Object.values(s?.sizes ?? {}) as number[];
        local = { reachable: !!s?.reachable, name: s?.server_name || "The server", models: (s?.models ?? []).length,
                  bytes: sizes.reduce((a, b) => a + (b || 0), 0) };
      }).catch(() => (local = { reachable: false, name: "The server", models: 0, bytes: 0 }));
    }
    if (which === "usage" && !$usage.loaded) loadUsage().catch(() => {});
  });

  const gb = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.round(n / 1e6)} MB`);
  const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

  const chips = $derived.by((): Chip[] => {
    const connected = $providerList.filter((p) => p.ready && p.id !== "local");
    if (which === "models") {
      const chain = $savedPlan?.replies ?? [];
      return [
        ...(chain[0] ? [{ icon: "chats", text: `Replies: ${shortModel(chain[0].model)}` }] : []),
        { icon: "order", text: chain.length > 1 ? `${chain.length - 1} to fall back on` : "Nothing to fall back on",
          tone: chain.length > 1 ? "good" : "muted" },
        { icon: "link", text: plural(connected.length, "provider") + " connected", tone: connected.length ? "good" : "warn" },
      ];
    }
    if (which === "keys") {
      const all = $providerList.filter((p) => p.id !== "local");
      const groq = $providerList.find((p) => p.id === "groq");
      return [
        { icon: "link", text: `${connected.length} of ${all.length} connected`, tone: connected.length ? "good" : "warn" },
        ...(groq?.keys ? [{ icon: "key", text: plural(groq.keys, "Groq key") }] : []),
      ];
    }
    if (which === "local") {
      if (!local) return [{ icon: "refresh", text: "Looking", tone: "muted" }];
      return [
        { icon: local.reachable ? "check" : "alert", text: `${local.name} ${local.reachable ? "running" : "not running"}`,
          tone: local.reachable ? "good" : "warn" },
        ...(local.reachable ? [{ icon: "monitor", text: plural(local.models, "model") + (local.bytes ? ` · ${gb(local.bytes)}` : "") }] : []),
      ];
    }
    if (which === "usage") {
      const t = $usage.models.reduce((a, m) => ({ r: a.r + (m.today?.requests ?? 0), k: a.k + (m.today?.in ?? 0) + (m.today?.out ?? 0),
                                                   bad: a.bad + (m.today?.errors ?? 0) + (m.today?.limited ?? 0) }), { r: 0, k: 0, bad: 0 });
      return [
        { icon: "stats", text: plural(t.r, "request") + " today" },
        { icon: "sparkle", text: `${t.k >= 1000 ? `${(t.k / 1000).toFixed(t.k >= 10000 ? 0 : 1)}k` : t.k} tokens` },
        ...(t.bad ? [{ icon: "alert", text: `${t.bad} refused or failed`, tone: "warn" as const }] : []),
      ];
    }
    return [];
  });
  /** Chips from data still on its way: the row is drawn once there is something to say. */
  const ready = $derived(which === "local" ? !!local : which === "usage" ? $usage.loaded : $providersLoaded);
</script>

<header class="mh">
  <span class="mh-orb" use:chime={"land"}>
    <span class="mh-ring" aria-hidden="true"></span>
    <Icon name={icon} size={22} />
  </span>
  <div class="min-w-0 flex-1">
    <div class="mh-kicker">Models</div>
    <h2 class="mh-title">{name}</h2>
    {#if blurb}<p class="mh-blurb">{blurb}</p>{/if}
    {#if ready}
      <div class="mh-chips domino" use:domino={{ step: 38, sound: "pluck", level: 0.45, once: true }}>
        {#each chips as c (c.text)}
          <span class="mh-chip" data-tone={c.tone ?? ""}><Icon name={c.icon} size={12} />{c.text}</span>
        {/each}
      </div>
    {/if}
  </div>
</header>

<style>
  .mh {
    position: relative;
    display: flex;
    align-items: flex-start;
    gap: 16px;
    margin-bottom: 18px;
    padding: 18px 20px;
    overflow: hidden;
    border-radius: 20px;
    background:
      radial-gradient(70% 140% at 0% 0%, color-mix(in srgb, var(--color-accent) 16%, transparent), transparent 60%),
      radial-gradient(50% 120% at 100% 100%, color-mix(in srgb, var(--color-accent-2, var(--color-accent)) 10%, transparent), transparent 60%),
      rgb(255 255 255 / 0.02);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 18%, var(--color-edge));
  }
  /* The orb: the part's icon on the accent, a ring of light turning slowly round it. */
  .mh-orb {
    position: relative;
    display: grid;
    place-items: center;
    width: 52px;
    height: 52px;
    flex-shrink: 0;
    border-radius: 17px;
    color: #fff;
    background: linear-gradient(140deg, var(--color-accent), color-mix(in srgb, var(--color-accent-2, var(--color-accent)) 70%, var(--color-accent)));
    box-shadow: 0 10px 28px -10px var(--color-accent), inset 0 1px 0 rgb(255 255 255 / 0.25);
    animation: mh-orb-in 0.4s var(--jelly) backwards;
  }
  .mh-ring {
    position: absolute;
    inset: -5px;
    border-radius: 21px;
    padding: 1.5px;
    background: conic-gradient(from var(--mh-turn, 0deg), transparent 0deg, color-mix(in srgb, var(--color-accent) 85%, white) 70deg,
                transparent 140deg, transparent 360deg);
    -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    -webkit-mask-composite: xor;
    mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    mask-composite: exclude;
    animation: mh-turn 6s linear infinite;
    opacity: 0.8;
  }
  @property --mh-turn { syntax: "<angle>"; inherits: false; initial-value: 0deg; }
  @keyframes mh-turn { to { --mh-turn: 360deg; } }
  @keyframes mh-orb-in { from { opacity: 0; transform: scale(0.5) rotate(-18deg); } }
  .mh-kicker { font-size: 11px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: var(--color-faint); }
  .mh-title { font-size: 19px; font-weight: 650; letter-spacing: -0.01em; color: var(--color-ink); }
  .mh-blurb { margin-top: 2px; font-size: 12.5px; color: var(--color-muted); }
  .mh-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .mh-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    max-width: 100%;
    padding: 4px 10px;
    border-radius: 999px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.06);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06);
  }
  .mh-chip :global(svg) { flex-shrink: 0; color: var(--color-accent); }
  .mh-chip[data-tone="good"] :global(svg) { color: var(--color-good); }
  .mh-chip[data-tone="warn"] { color: var(--color-warn); background: color-mix(in srgb, var(--color-warn) 10%, transparent); }
  .mh-chip[data-tone="warn"] :global(svg) { color: var(--color-warn); }
  .mh-chip[data-tone="muted"] { color: var(--color-muted); }
  .mh-chip[data-tone="muted"] :global(svg) { color: var(--color-faint); }
  :global(:root[data-motion="off"]) .mh-orb,
  :global(:root[data-motion="off"]) .mh-ring { animation: none; }
</style>
