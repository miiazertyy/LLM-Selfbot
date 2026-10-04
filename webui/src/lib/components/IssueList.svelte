<script module lang="ts">
  import { writable } from "svelte/store";
  /** Notices dismissed this session, by level and title. Only info-level ones
   *  can be: a problem that is hidden is still a problem. */
  export const dismissedIssues = writable<Set<string>>(new Set());
</script>

<script lang="ts">
  /**
   * Problems and notices, drawn one way everywhere.
   *
   * The first version gave every notice its own heavy box with the same
   * warning triangle, so "an update is available" looked as alarming as "the
   * bot cannot reply". The second fixed the levels but drew them loudly: a
   * coloured outline all the way round, a stripe down the edge, a tinted icon
   * tile and a tinted button, four accents saying the same thing, on top of
   * the page's own colours.
   *
   * Now it is one quiet glass card. The level is said once, by the icon and the
   * soft light it casts; the text carries the rest, and the button is neutral
   * so it reads as a way out rather than as more alarm.
   */
  import { health, settingsSection, toast } from "../stores";
  import { api } from "../api";
  import { loadProviders } from "../providers";
  import Icon from "./Icon.svelte";

  type Issue = {
    route: string;
    level: string;
    title: string;
    detail?: string;
    where?: string;
    section?: string;
    fix?: { label: string; call: string; models?: string[] };
  };

  let { issues = [], here = "" }: { issues?: Issue[]; here?: string } = $props();

  const PAGE: Record<string, string> = {
    dashboard: "Dashboard", accounts: "Accounts", chats: "Chats", profiles: "Profiles", persona: "Persona",
    memory: "Memory", pictures: "Pictures", logs: "Logs", settings: "Settings", system: "System",
  };
  const ORDER: Record<string, number> = { error: 0, warn: 1, info: 2 };
  const key = (i: Issue) => `${i.level}:${i.title}`;

  const shown = $derived(
    issues
      .filter((i) => !(i.level === "info" && $dismissedIssues.has(key(i))))
      .slice()
      .sort((a, b) => (ORDER[a.level] ?? 3) - (ORDER[b.level] ?? 3)),
  );
  const worst = $derived(shown[0]?.level ?? "info");

  const counts = $derived([
    { level: "error", n: shown.filter((i) => i.level === "error").length, one: "problem", many: "problems" },
    { level: "warn", n: shown.filter((i) => i.level === "warn").length, one: "warning", many: "warnings" },
    { level: "info", n: shown.filter((i) => i.level === "info").length, one: "notice", many: "notices" },
  ].filter((c) => c.n));

  /** "the Updates card" -> "Updates card"; "Models, This computer" -> "Models › This computer". */
  function hint(i: Issue): string {
    const w = (i.where || "").trim().replace(/^the\s+/i, "");
    if (!w) return "";
    const t = w.replace(/\s*(→|,)\s*/g, " › ");
    return t[0].toUpperCase() + t.slice(1);
  }

  /** What the button says, or "" when there is nowhere better to be. */
  function action(i: Issue): string {
    if (i.route && i.route !== here) return `Open ${PAGE[i.route] ?? i.route}`;
    if (i.section) return "Show me";
    return "";
  }

  function go(i: Issue) {
    if (i.section) settingsSection.set(i.section);
    if (i.route !== here) window.location.hash = `/${i.route}`;
  }

  /** The fixes the app can run itself, by name. */
  const FIXES: Record<string, (i: Issue) => Promise<any>> = {
    local_start: () => api.localStart(),
    // A model the computer does not have any more, out of every job that names it.
    local_forget: (i) => api.localForget(i.fix?.models ?? []),
  };
  let fixing = $state<Record<string, boolean>>({});

  async function fix(i: Issue) {
    const run = i.fix && FIXES[i.fix.call];
    if (!run || fixing[key(i)]) return;
    fixing[key(i)] = true;
    try {
      const r = await run(i);
      if (r && r.ok === false) toast(r.reason || "That did not work", "err");
      else if (r?.forgotten) {
        toast((r.unused ?? []).includes("replies") ? "Not used any more. Replies are on Groq until you pick another."
          : "Not used any more.", "ok");
        loadProviders().catch(() => {});
      } else toast(r?.name ? `${r.name} is running.` : "Done.", "ok");
      const h = await api.healthNow();
      if (h && Array.isArray(h.issues) && h.routes) health.set(h);
    } catch (e: any) {
      toast(e?.message || "That did not work", "err");
    } finally {
      delete fixing[key(i)];
    }
  }

  function dismiss(i: Issue) {
    dismissedIssues.update((s) => new Set(s).add(key(i)));
  }

  const icon = (level: string) => (level === "error" ? "alertCircle" : level === "warn" ? "alert" : "info");
</script>

{#if shown.length}
  <section class="notes" data-worst={worst} aria-label="Things that need attention">
    {#if shown.length > 1}
      <header class="notes-head">
        {#each counts as c (c.level)}
          <span class="notes-count" data-level={c.level}><i></i>{c.n} {c.n === 1 ? c.one : c.many}</span>
        {/each}
      </header>
    {/if}
    {#each shown as issue (key(issue))}
      <div class="note" data-level={issue.level}>
        <span class="note-icon" class:is-live={issue.level === "error"}>
          <Icon name={icon(issue.level)} size={15} />
        </span>
        <div class="min-w-0 flex-1">
          <div class="note-title">{issue.title}</div>
          {#if issue.detail}
            <p class="note-detail">{issue.detail}</p>
          {/if}
          {#if hint(issue) && !action(issue)}
            <p class="note-where">{hint(issue)}</p>
          {/if}
        </div>
        <div class="note-actions">
          {#if issue.fix && FIXES[issue.fix.call]}
            <button type="button" class="note-btn is-fix" onclick={() => fix(issue)} disabled={!!fixing[key(issue)]}>
              {#if fixing[key(issue)]}
                <span class="note-spin"></span>Starting
              {:else}
                <Icon name="play" size={11} />{issue.fix.label}
              {/if}
            </button>
          {/if}
          {#if action(issue)}
            <button type="button" class="note-btn" onclick={() => go(issue)}
                    title={hint(issue) || undefined}>
              {action(issue)}<span class="note-arrow"><Icon name="chevron" size={12} /></span>
            </button>
          {/if}
          {#if issue.level === "info"}
            <button type="button" class="note-x" onclick={() => dismiss(issue)}
                    title="Hide until the app is reopened" aria-label="Dismiss">
              <Icon name="close" size={13} />
            </button>
          {/if}
        </div>
      </div>
    {/each}
  </section>
{/if}

<style>
  .notes {
    --tone: var(--color-accent);
    position: relative;
    margin-bottom: 16px;
    overflow: hidden;
    border-radius: 16px;
    background: color-mix(in srgb, var(--color-card) 72%, transparent);
    box-shadow:
      inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 90%, transparent),
      0 10px 30px -18px rgb(0 0 0 / 0.7);
    animation: notes-in 0.35s var(--spring) both;
  }
  .notes[data-worst="error"] { --tone: var(--color-bad); }
  .notes[data-worst="warn"] { --tone: var(--color-warn); }

  .notes-head {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding: 10px 14px 0;
  }
  .notes-count {
    --c: var(--color-accent);
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 2px 9px 2px 7px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 500;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.045);
  }
  .notes-count i {
    width: 6px;
    height: 6px;
    border-radius: 999px;
    background: var(--c);
  }
  .notes-count[data-level="error"] { --c: var(--color-bad); }
  .notes-count[data-level="warn"] { --c: var(--color-warn); }

  .note {
    --c: var(--color-accent);
    position: relative;
    display: flex;
    align-items: center;
    gap: 13px;
    padding: 13px 14px 13px 15px;
  }
  .note[data-level="error"] { --c: var(--color-bad); }
  .note[data-level="warn"] { --c: var(--color-warn); }
  /* The only colour on the card: a soft light behind the icon. */
  .note::before {
    content: "";
    position: absolute;
    inset: 0;
    pointer-events: none;
    background: radial-gradient(260px 90px at 30px 50%, color-mix(in srgb, var(--c) 13%, transparent), transparent 75%);
  }
  .note + .note::after {
    content: "";
    position: absolute;
    left: 58px;
    right: 14px;
    top: 0;
    height: 1px;
    background: color-mix(in srgb, var(--color-edge) 70%, transparent);
  }

  .note-icon {
    position: relative;
    display: grid;
    width: 30px;
    height: 30px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    color: var(--c);
    background: color-mix(in srgb, var(--c) 16%, rgb(0 0 0 / 0.2));
  }
  /* A problem breathes, once every few seconds: enough to catch the eye, not
     enough to nag. A scaled ring, so it is composited rather than repainted. */
  .note-icon.is-live::after {
    content: "";
    position: absolute;
    inset: -3px;
    border-radius: 999px;
    border: 1.5px solid color-mix(in srgb, var(--c) 55%, transparent);
    animation: note-ring 2.8s ease-out infinite;
  }

  .note-title {
    font-size: 13.5px;
    font-weight: 600;
    line-height: 1.35;
    color: var(--color-ink);
  }
  .note-detail {
    margin-top: 2px;
    font-size: 12px;
    line-height: 1.5;
    color: var(--color-muted);
  }
  .note-where {
    margin-top: 4px;
    font-size: 11.5px;
    color: var(--color-faint);
  }

  .note-actions {
    position: relative;
    display: flex;
    flex-shrink: 0;
    align-items: center;
    gap: 4px;
  }
  .note-btn {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 6px 9px 6px 12px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 500;
    white-space: nowrap;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.06);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.07);
    transition: background-color 0.15s ease, transform 0.15s var(--spring);
  }
  .note-btn:hover { background: rgb(255 255 255 / 0.11); }
  /* The one that fixes it is the obvious one to press. */
  .note-btn.is-fix {
    gap: 6px;
    padding-left: 11px;
    padding-right: 12px;
    color: var(--color-bg);
    background: var(--color-accent);
    box-shadow: 0 6px 18px -8px color-mix(in srgb, var(--color-accent) 70%, transparent);
  }
  .note-btn.is-fix:hover { background: color-mix(in srgb, var(--color-accent) 88%, white); }
  .note-btn:disabled { opacity: 0.75; cursor: default; }
  .note-spin {
    width: 11px;
    height: 11px;
    border-radius: 999px;
    border: 1.5px solid currentColor;
    border-top-color: transparent;
    animation: note-spin 0.7s linear infinite;
  }
  @keyframes note-spin { to { transform: rotate(360deg); } }
  .note-btn:active { transform: scale(0.96); }
  .note-arrow {
    display: inline-flex;
    color: var(--color-muted);
    transition: transform 0.2s var(--spring), color 0.15s ease;
  }
  .note-btn:hover .note-arrow { transform: translateX(2px); color: var(--color-ink); }
  .note-x {
    display: grid;
    width: 28px;
    height: 28px;
    place-items: center;
    border-radius: 9px;
    color: var(--color-faint);
    transition: background-color 0.15s ease, color 0.15s ease;
  }
  .note-x:hover { background: rgb(255 255 255 / 0.07); color: var(--color-ink); }

  @keyframes notes-in {
    from { opacity: 0; transform: translateY(-4px); }
    to { opacity: 1; transform: none; }
  }
  @keyframes note-ring {
    0% { opacity: 0.9; transform: scale(0.9); }
    70%, 100% { opacity: 0; transform: scale(1.35); }
  }
  :global(:root[data-motion="off"]) .notes,
  :global(:root[data-motion="off"]) .note-icon.is-live::after { animation: none; }

  @media (max-width: 520px) {
    .note { flex-wrap: wrap; align-items: flex-start; }
    .note-actions { width: 100%; justify-content: flex-end; }
  }
</style>
