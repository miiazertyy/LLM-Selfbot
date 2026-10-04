<script lang="ts">
  /**
   * Everything about the machine the bot runs on.
   *
   * The doctor used to be a list of red crosses with no way to act on them,
   * which told you something was wrong and then left you there. Every failing
   * row now carries what the thing is for, what to do about it, and a button
   * that does it: installs the missing piece, opens the page that fixes it, or
   * sends you to the download.
   */
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { track } from "../lib/busy";
  import { subscribeLogs } from "../lib/logsocket";
  import { toast, settingsSection } from "../lib/stores";
  import { resource } from "../lib/resource";
  import { pickFolder, pickFile, openExternal, openUrl } from "../lib/window";
  import { deviceInfo, notHere } from "../lib/device";
  // Named so, because restartApp's own "ask" parameter would hide it.
  import { ask as askFirst } from "../lib/ask";
  import NotHere from "../lib/components/NotHere.svelte";
  import Card from "../lib/components/Card.svelte";
  import Badge from "../lib/components/Badge.svelte";
  import Button from "../lib/components/Button.svelte";
  import Toggle from "../lib/components/Toggle.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import FootNote from "../lib/components/FootNote.svelte";
  import ProgressRing from "../lib/components/ProgressRing.svelte";
  import { chime, domino } from "../lib/domino";

  type Action = {
    kind: "install" | "link" | "goto" | "open" | "start_local";
    label: string;
    url?: string;
    route?: string;
    section?: string;
    target?: string;
  };
  type Check = {
    id: string;
    name: string;
    ok: boolean;
    detail?: string;
    why?: string;
    fix?: string;
    action?: Action | null;
  };
  /** Named in app/web/routes/system_routes.py as well, which is what the
      desktop shell opens; this is the browser's copy of the same address. */
  const PROJECT_URL = "https://github.com/miiazertyy/LLM-Selfbot";

  type Info = { version: string; python: string; os: string; frozen: boolean; data_dir: string };
  type Net = {
    port: number;
    bind: string;
    enabled: boolean;
    ip: string;
    local_url: string;
    lan_url: string;
    reachable: boolean;
    qr: string;
    qr_target: string;
  };

  /**
   * One resource per card, so each appears the moment its own answer arrives.
   *
   * These four reads take wildly different times: the network details are
   * instant, the version check is a call to GitHub, and the dependency doctor
   * starts node to ask Puppeteer where Chrome is, which is four and a half
   * seconds from cold. Loading them together meant the whole page sat on a
   * skeleton for as long as the slowest one, so the tab looked broken.
   *
   * Nothing here waits on anything else. Every card is cached between visits
   * too, so coming back to the tab shows the last answer straight away.
   */
  const sysInfo = resource("systemInfo", () => api.sysInfo(), null as Info | null);
  const network = resource("systemNetwork", () => api.network(), null as Net | null);
  const updates = resource("systemUpdate", () => api.updateCheck(), null as any);
  const doctor = resource("systemDoctor", () => api.doctor(), { checks: [] as Check[] });

  const info = $derived($sysInfo.data);
  const net = $derived($network.data);
  const checks = $derived<Check[]>($doctor.data.checks ?? []);

  // Each card knows only about its own wait.
  const infoLoading = $derived(!$sysInfo.fetched && $sysInfo.loading);
  const netLoading = $derived(!$network.fetched && $network.loading);
  const updateLoading = $derived(!$updates.fetched && $updates.loading);
  const doctorLoading = $derived(!$doctor.fetched && $doctor.loading);

  // The page itself is never blocked: it renders its cards immediately and
  // they fill in individually.
  const loading = false;
  const loadError = $derived($network.error || $sysInfo.error || "");

  // Local, because Ignore edits it without a round trip.
  let updateOverride = $state<any>(null);
  const update = $derived(updateOverride ?? $updates.data);
  let updating = $state(false);
  let open = $state<Record<string, boolean>>({});
  let busy = $state<Record<string, boolean>>({});
  let installLog = $state<string[]>([]);
  let bindBusy = $state(false);
  let copied = $state("");
  let storageInfo = $state<any>(null);
  let exporting = $state(false);
  let importing = $state(false);
  let lastExport = $state("");
  let qrOpen = $state(false);

  function toBody(node: HTMLElement) {
    document.body.appendChild(node);
    node.focus();
    return { destroy: () => node.remove() };
  }

  const failing = $derived(checks.filter((c) => !c.ok).length);
  const problems = $derived(checks.filter((c) => !c.ok));
  const passing = $derived(checks.filter((c) => c.ok));

  // How long the app has been up, for the header. The panel's own uptime is
  // the app's: they start and stop together.
  let uptime = $state(0);
  const upFor = $derived.by(() => {
    if (!uptime) return "";
    const d = Math.floor(uptime / 86400), h = Math.floor((uptime % 86400) / 3600);
    const m = Math.floor((uptime % 3600) / 60);
    return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
  });

  /** "Ollama is not running", from a check: what is wrong, said plainly. */
  const sayProblem = (c: Check) =>
    /^(not |missing|none)/i.test(c.detail || "") ? `${c.name} is ${c.detail}` : c.detail ? `${c.name}: ${c.detail}` : c.name;

  /**
   * The one line the page leads with: is everything all right?
   *
   * It said "1 thing needs a look" and left you to find which, while the
   * brightest thing beside it was the update button, so the update read as the
   * problem. One problem is now named in the headline, with its fix as the
   * button next to it; the update is a quiet button unless nothing is wrong.
   */
  const headline = $derived(
    doctorLoading ? "Checking everything"
    : failing === 1 ? sayProblem(problems[0])
    : failing ? `${failing} things need a look`
    : "Everything is working",
  );
  /** The fix for the first problem, as the header's main button. */
  const heroFix = $derived(problems.find((c) => c.action));
  const healthTone = $derived(doctorLoading ? "busy" : failing ? "warn" : "good");

  onMount(() => {
    // Fired together, awaited separately: whichever answers first is shown
    // first, and the slow one never holds up the others.
    sysInfo.refresh({ maxAge: 30000 });
    network.refresh({ maxAge: 15000 });
    updates.refresh({ maxAge: 300000 });
    // Separately, so a slow probe never holds up the rest of the page.
    doctor.refresh({ maxAge: 60000 });
    // The backup card's size was only ever read after an export or import, so
    // it never showed on opening the page. The walk runs on a server thread.
    loadStorage();
    api.status().then((s: any) => (uptime = s?.uptime ?? 0)).catch(() => {});
    // The installers report progress over the same log stream the rest of the
    // app uses, so the page can show what is happening instead of a spinner.
    return subscribeLogs((entry) => {
      if (entry.source === "ffmpeg-install" || entry.source === "snapchat-install") {
        installLog = [...installLog.slice(-40), entry.text ?? ""];
      }
    });
  });

  function load() {
    sysInfo.refresh({ force: true });
    network.refresh({ force: true });
    updates.refresh({ force: true });
    doctor.refresh({ force: true });
  }

  async function act(c: Check) {
    const a = c.action;
    if (!a) return;
    if (a.kind === "link" && a.url) {
      openUrl(a.url);
      return;
    }
    if (a.kind === "goto" && a.route) {
      if (a.section) settingsSection.set(a.section);
      window.location.hash = `/${a.route}`;
      return;
    }
    busy[c.id] = true;
    try {
      if (a.kind === "start_local") {
        const r = await api.localStart();
        toast(r?.ok ? `${r.name || "The server"} is running.` : r?.reason || "Could not start it", r?.ok ? "ok" : "err");
      } else if (a.kind === "open") {
        await api.openFolder(a.target || "data");
      } else if (a.kind === "install" && a.target === "ffmpeg") {
        await api.ffmpegInstall();
        toast("Downloading ffmpeg. Progress is below.", "info");
        // The download runs in a thread, so poll until the doctor turns green.
        const poll = setInterval(async () => {
          const s = await api.ffmpegStatus().catch(() => null);
          if (s && !s.installing) {
            clearInterval(poll);
            busy[c.id] = false;
            load();
          }
        }, 2000);
        return;
      }
    } catch (e: any) {
      toast(e.message, "err");
    }
    busy[c.id] = false;
    load();
  }

  async function setBind(lan: boolean) {
    bindBusy = true;
    try {
      await api.configField("services.webui.bind", lan ? "0.0.0.0" : "127.0.0.1");
      toast(
        lan
          ? "Saved. Restart the app to start listening on the network."
          : "Saved. Restart the app to go back to this machine only.",
        "ok",
      );
      await network.refresh({ force: true });
    } catch (e: any) {
      toast(e.message, "err");
    }
    bindBusy = false;
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      copied = text;
      setTimeout(() => (copied = ""), 1500);
    } catch {
      toast("Could not copy", "err");
    }
  }

  let restarting = $state(false);

  async function restartApp(ask: unknown = true) {
    const question = phoneApp ? "Restart the accounts?" : "Restart the app?";
    if (ask !== false && !(await askFirst(question, {
      detail: phoneApp ? "They reconnect after a few seconds." : "It closes and opens again. Accounts reconnect after a few seconds.",
      yes: phoneApp ? "Restart accounts" : "Restart",
    }))) {
      return;
    }
    restarting = true;
    try {
      await api.restartApp();
      toast("Restarting. This window will reconnect on its own.", "info");
      // The server is on its way down, so keep retrying until the new one
      // answers, then reload into it.
      const until = Date.now() + 60000;
      const tick = setInterval(async () => {
        try {
          await api.sysInfo();
          clearInterval(tick);
          location.reload();
        } catch {
          if (Date.now() > until) {
            clearInterval(tick);
            restarting = false;
            toast("It is taking a while. Open the app again by hand.", "err");
          }
        }
      }, 1500);
    } catch (e: any) {
      restarting = false;
      toast(e.message, "err");
    }
  }

  async function ignoreUpdate() {
    if (!update?.latest) return;
    try {
      await api.ignoreUpdate(update.latest);
      // Held locally so the card and the sidebar dot both clear at once,
      // without waiting for the next poll.
      updateOverride = { ...update, update_available: false, ignored: true };
      toast(`You will not be told about ${update.latest} again.`, "ok");
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  // ── This device ─────────────────────────────────────────────────────────
  const device = $derived($deviceInfo?.device ?? null);
  const phoneApp = $derived(!!device?.phone && !!device?.single_process);
  const cantHere = $derived(Object.entries($deviceInfo?.missing ?? {}));

  /** What the update button says: what it will actually do on this device. */
  const updateWord = $derived(
    update?.method === "download" ? "Download the update"
      : update?.method === "sideload" ? "Get the new IPA"
      : "Update now",
  );

  async function runUpdate() {
    updating = true;
    try {
      const r: any = await api.updateRun();
      if (r?.method === "download" || r?.method === "sideload") {
        // The phone installs it: Android offers the APK, an iPhone gets the release page.
        if (!r.opened && r.url) openUrl(r.url);
        toast(r.method === "download" ? "Downloading it. Tap it when it finishes to install."
                                      : "Opening the release. Install the new IPA with AltStore or SideStore.", "info");
      } else {
        toast("Downloading the update. The app restarts when it is ready.", "info");
      }
    } catch (e: any) {
      toast(e.message, "err");
    }
    updating = false;
  }

  /**
   * Export and import through the native file dialogs.
   *
   * A browser download is inert in the embedded WebView, so the export asks
   * for a folder and the server writes the zip into it. In a plain browser
   * there is no dialog, so it falls back to the app data folder and says
   * where it went.
   */
  async function exportAll() {
    exporting = true;
    lastExport = "";
    try {
      const folder = await pickFolder();
      const r = await track("system", api.exportAll(folder), "Exporting everything");
      lastExport = r.path;
      toast(r.skipped_count
        ? `Exported ${r.files} files. ${r.skipped_count} were in use by another program and left out.`
        : `Exported ${r.files} files.`, "ok");
      loadStorage();
    } catch (e: any) {
      toast(e.message || "Export failed", "err");
    }
    exporting = false;
  }

  async function importAll() {
    const path = await pickFile(["LLMSelfbot export (*.zip)", "All files (*.*)"]);
    if (!path) {
      toast("Pick the zip you exported earlier.", "info");
      return;
    }
    if (!(await askFirst("Replace everything with this backup?",
                         { detail: "The config, keys, memory and pictures here are replaced by the backup's.",
                           yes: "Replace", danger: true }))) return;
    importing = true;
    try {
      const r = await track("system", api.importAll(path), "Importing a backup");
      // The files go in place on the next start, before anything has them
      // open; replacing them under the running accounts is what failed.
      if (await askFirst("Restart now to finish restoring?",
                         { detail: `${r.files} files are ready. They go in place when the app starts.`,
                           yes: "Restart now", no: "Later" })) {
        await restartApp(false);
      } else {
        toast("The backup is restored the next time the app starts.", "info");
      }
      loadStorage();
    } catch (e: any) {
      toast(e.message || "Import failed", "err");
    }
    importing = false;
  }

  async function loadStorage() {
    try {
      storageInfo = await api.storage();
    } catch {
      /* the rest of the page still works */
    }
  }

  function mb(bytes: number): string {
    if (!bytes) return "0 KB";
    return bytes > 1024 * 1024
      ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
      : `${Math.round(bytes / 1024)} KB`;
  }
</script>

<ErrorNote text={loadError} />

{#if qrOpen && net?.qr}
  <div use:toBody class="qr-view" role="dialog" aria-modal="true" aria-label="Scan to open the panel" tabindex="-1"
       onclick={() => (qrOpen = false)} onkeydown={(e) => e.key === "Escape" && (qrOpen = false)}>
    <div class="qr-card" onclick={(e) => e.stopPropagation()} role="presentation">
      <div class="qr-big" class:is-off={net.bind === "127.0.0.1"}>{@html net.qr}</div>
      <div class="mt-4 text-center">
        <div class="text-[15px] font-semibold text-ink">Scan with your phone's camera</div>
        <div class="mt-1 font-mono text-[13px] text-accent">{net.qr_target}</div>
        {#if net.bind === "127.0.0.1"}
          <div class="mt-2 text-[12px] text-warn">Only this computer can open it until "On this network" is turned on below.</div>
        {/if}
      </div>
      <button class="qr-close" onclick={() => (qrOpen = false)} aria-label="Close"><Icon name="close" size={14} /></button>
    </div>
  </div>
{/if}

<!-- ── How it is, at a glance ─────────────────────────────────────────────── -->
<!-- The page used to open on a list of eleven checks, nine of them "ok", and
     make you read all of them to find out whether anything was wrong. The
     answer comes first now, with the things you come here to do beside it. -->
<section class="sys-hero glass" data-tone={healthTone}>
  <div class="flex min-w-0 items-center gap-4">
    <!-- As the tab opens: the ring draws itself round (a breath of air), then its mark pops (a chime). -->
    <span class="sys-ring" use:chime={"zip"}>
      {#if doctorLoading}
        <ProgressRing size={54} />
      {:else}
        <ProgressRing done={passing.length} total={Math.max(1, checks.length)} size={54} />
      {/if}
      <span class="sys-ring-icon" use:chime={{ sound: failing ? "land" : "done", delay: 500 }}>
        <Icon name={doctorLoading ? "refresh" : failing ? "alert" : "check"} size={18} />
      </span>
    </span>
    <div class="min-w-0">
      <h2 class="text-[20px] font-semibold tracking-tight text-ink">{headline}</h2>
      <p class="mt-0.5 flex flex-wrap items-center gap-x-2 text-[12.5px] text-muted">
        <span>LLMSelfbot {info?.version ?? ""}</span>
        {#if device}<span class="text-faint">·</span><span>{device.label}</span>{/if}
        {#if upFor}<span class="text-faint">·</span><span>up {upFor}</span>{/if}
        {#if storageInfo}<span class="text-faint">·</span><span>{mb(storageInfo.size)} of data</span>{/if}
        {#if !doctorLoading}
          <span class="text-faint">·</span><span>{passing.length} of {checks.length} checks passing</span>
        {/if}
        {#if failing > 1}
          <span class="text-faint">·</span><span class="text-warn">{problems.map((c) => c.name).join(", ")}</span>
        {/if}
      </p>
    </div>
  </div>
  <div class="flex flex-wrap items-center gap-2 lg:ml-auto">
    {#if heroFix?.action}
      <Button size="sm" loading={busy[heroFix.id]} onclick={() => act(heroFix!)}>
        {#if !busy[heroFix.id]}<Icon name={heroFix.action.kind === "start_local" ? "play" : "chevron"} size={12} />{/if}{heroFix.action.label}
      </Button>
    {/if}
    {#if update?.ok && update.update_available && update.ready !== false}
      <Button size="sm" kind={failing ? "ghost" : "primary"} onclick={runUpdate} loading={updating}>
        {#if !updating}<Icon name="upload" size={13} />{/if}{update.method === "sideload" ? "Get" : "Update to"} {update.latest}
      </Button>
    {/if}
    <Button kind="ghost" size="sm" onclick={load} disabled={doctorLoading}>
      <Icon name="refresh" size={13} />Check again
    </Button>
    <span title="Some settings, the port and the data folder among them, are only read at startup">
      <Button kind="ghost" size="sm" loading={restarting} onclick={restartApp}>
        {#if !restarting}<Icon name="signout" size={13} />{/if}{restarting ? "Restarting" : phoneApp ? "Restart accounts" : "Restart app"}
      </Button>
    </span>
    <!-- No file manager on a phone: the button stays, and says why it cannot. -->
    <button class="sys-icon-btn" onclick={() => api.openFolder("data").catch(() => {})}
            disabled={!!$notHere("folders")}
            title={$notHere("folders")?.why ?? "Open the data folder"} aria-label="Open the data folder">
      <Icon name="folder" size={15} />
    </button>
  </div>
</section>

<div class="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
  <div class="min-w-0 space-y-4">
    <!-- ── Health ─────────────────────────────────────────────────────────── -->
    <Card title="Health checks">
      {#snippet actions()}
        <span class="text-[11px] {failing ? 'text-warn' : 'text-good'}">
          {doctorLoading ? "checking" : failing ? `${failing} to fix` : "all passing"}
        </span>
      {/snippet}

      {#if doctorLoading && !checks.length}
        <div class="grid grid-cols-2 gap-2">
          {#each [1, 2, 3, 4, 5, 6] as _}
            <div class="h-14 animate-pulse rounded-xl bg-white/[0.03]"></div>
          {/each}
        </div>
        <p class="pt-2 text-[11px] text-faint">
          Checking what is installed. Finding Chrome starts node, which takes a few seconds.
        </p>
      {/if}

      <!-- What is wrong comes first, open, with what to do and the button that
           does it. There is nothing to click through to. -->
      {#if problems.length}
        <div class="mb-3 space-y-2 domino" use:domino={{ step: 90 }}>
          {#each problems as c (c.id)}
            <div class="sys-problem">
              <div class="flex items-start gap-3">
                <span class="sys-problem-icon"><Icon name="alert" size={15} /></span>
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="text-[13.5px] font-semibold text-ink">{c.name}</span>
                    {#if c.detail}<span class="text-[11.5px] text-warn">{c.detail}</span>{/if}
                  </div>
                  {#if c.why}<p class="mt-1 text-[12px] leading-relaxed text-muted">{c.why}</p>{/if}
                  {#if c.fix}<p class="mt-1 text-[12px] leading-relaxed text-ink/85">{c.fix}</p>{/if}
                </div>
                {#if c.action}
                  <span class="shrink-0 self-center">
                    <Button size="sm" loading={busy[c.id]} onclick={() => act(c)}>{c.action.label}</Button>
                  </span>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      {/if}

      <!-- Everything that is fine, as small tiles: there to see, not to read. -->
      {#if passing.length}
        <div class="grid grid-cols-1 gap-1.5 min-[480px]:grid-cols-2 domino" use:domino={{ step: 30, level: 0.5 }}>
          {#each passing as c (c.id)}
            <button type="button" class="sys-ok" onclick={() => (open[c.id] = !open[c.id])}
                    title={c.detail || c.name} aria-expanded={!!open[c.id]}>
              <span class="sys-ok-icon"><Icon name="check" size={12} /></span>
              <span class="min-w-0 flex-1 text-left">
                <span class="block truncate text-[12.5px] text-ink">{c.name}</span>
                {#if c.detail}
                  <span class="block {open[c.id] ? 'break-all' : 'truncate'} font-mono text-[10.5px] text-faint">{c.detail}</span>
                {/if}
              </span>
            </button>
          {/each}
        </div>
      {/if}

      {#if installLog.length}
        <div class="mt-3">
          <div class="mb-1.5 text-[10px] uppercase tracking-[0.12em] text-faint">Install log</div>
          <div class="max-h-40 overflow-y-auto rounded-lg bg-black/40 p-2.5 font-mono text-[11px] leading-relaxed text-ink/80">
            {#each installLog as line}
              <div class="break-all">{line}</div>
            {/each}
          </div>
        </div>
      {/if}
    </Card>

    <!-- ── Backup ─────────────────────────────────────────────────────────── -->
    <Card title="Backup and restore">
      <NotHere feature="files_save" />
      <div class="grid grid-cols-1 gap-2 min-[480px]:grid-cols-2 domino" use:domino={{ step: 100 }}>
        <button type="button" class="sys-action" onclick={exportAll} disabled={exporting || !!$notHere("files_save")}>
          <span class="sys-action-icon is-good">
            {#if exporting}<span class="sys-spin"></span>{:else}<Icon name="upload" size={16} />{/if}
          </span>
          <span class="min-w-0 text-left">
            <span class="block text-[13px] font-semibold text-ink">Export everything</span>
            <span class="block text-[11.5px] text-faint">One zip: config, keys, persona, memory, pictures</span>
          </span>
        </button>
        <button type="button" class="sys-action" onclick={importAll} disabled={importing || !!$notHere("files_pick")}
                title={$notHere("files_pick")?.why}>
          <span class="sys-action-icon">
            {#if importing}<span class="sys-spin"></span>{:else}<Icon name="undo" size={16} />{/if}
          </span>
          <span class="min-w-0 text-left">
            <span class="block text-[13px] font-semibold text-ink">Import a backup</span>
            <span class="block text-[11.5px] text-faint">Replaces what is here with the zip's contents</span>
          </span>
        </button>
      </div>
      <FootNote class="mt-3" icon="key" tone="warn">
        A backup holds your tokens and keys, so keep it somewhere private.
      </FootNote>
      {#if lastExport}
        <p class="mt-2 break-all text-[11px] text-good">Saved to {lastExport}</p>
      {/if}

      {#if storageInfo}
        <div class="sys-storage">
          <div class="flex items-baseline justify-between gap-3">
            <span class="text-[12px] text-muted">Data folder</span>
            <span class="text-[12px] text-ink">{mb(storageInfo.size)} <span class="text-faint">· {storageInfo.files.toLocaleString()} files</span></span>
          </div>
          <button type="button" class="mt-1 block w-full truncate text-left font-mono text-[10.5px] text-faint hover:text-accent"
                  disabled={!!$notHere("folders")}
                  title={$notHere("folders")?.why ?? `Open ${storageInfo.data_dir}`} onclick={() => api.openFolder("data").catch(() => {})}>
            {storageInfo.data_dir}
          </button>
          {#if storageInfo.portable}
            <p class="mt-2 text-[11px] text-good">Portable install: everything lives beside the app.</p>
          {:else if !device?.phone}
            <FootNote class="mt-2" icon="folder">
              To keep everything beside the app instead, make a folder called
              <code>portable</code> next to it and restart. Export first, then import once it restarts.
            </FootNote>
          {/if}
        </div>
      {/if}
    </Card>
  </div>

  <div class="min-w-0 space-y-4">
    <!-- ── What this device cannot do ─────────────────────────────────────── -->
    <!-- Only what does not work, each where it is used as well as here; a
         device where everything works has no such card. -->
    {#if cantHere.length}
      <Card title="Not available here">
        <ul class="space-y-3">
          {#each cantHere as [id, m] (id)}
            <li class="flex gap-2.5">
              <span class="mt-[2px] shrink-0 text-warn"><Icon name="alert" size={13} /></span>
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-x-2 text-[12.5px] font-medium text-ink">
                  {m.label}<NotHere feature={id} variant="chip" />
                </div>
                <p class="mt-0.5 text-[11.5px] leading-relaxed text-muted">{m.why}</p>
                {#if m.fix?.command}
                  <code class="mt-1 inline-block rounded-md bg-white/[0.05] px-1.5 py-0.5 font-mono text-[10.5px] text-accent">{m.fix.command}</code>
                {/if}
              </div>
            </li>
          {/each}
        </ul>
      </Card>
    {/if}

    <!-- ── Updates ────────────────────────────────────────────────────────── -->
    <Card title="Updates">
      {#if updateLoading}
        <div class="h-16 animate-pulse rounded-lg bg-white/[0.03]"></div>
      {:else if update?.ok}
        {#if update.update_available}
          <!-- What you have, and what you would get, side by side. -->
          <div class="flex items-center gap-3">
            <span class="sys-ver">{update.current}</span>
            <span class="text-faint"><Icon name="chevron" size={14} /></span>
            <span class="sys-ver is-new">{update.latest}</span>
          </div>
          <!-- An iPhone app cannot replace itself; a device with no build has nothing to fetch. -->
          <NotHere feature="update" variant="line" />
          {#if update.ready === false && update.why && update.method !== "none"}
            <p class="mt-1.5 flex items-center gap-1.5 text-[11.5px] text-warn"><Icon name="alert" size={12} />{update.why}</p>
          {/if}
          {#if update.notes}
            <ul class="mt-3 space-y-1">
              {#each String(update.notes).split("\n").map((l) => l.replace(/^[-*•\s]+/, "").trim()).filter(Boolean).slice(0, 6) as line}
                <li class="flex gap-2 text-[12px] leading-relaxed text-muted">
                  <span class="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-accent"></span>{line}
                </li>
              {/each}
            </ul>
          {/if}
          <div class="mt-3.5 flex flex-wrap items-center gap-2">
            {#if update.ready !== false}
              <Button onclick={runUpdate} loading={updating}>{updateWord}</Button>
            {/if}
            <!-- Dismissing it clears the dot as well, and stays dismissed
                 until there is a release newer than this one. -->
            <button class="px-1 text-[11.5px] text-faint hover:text-ink" onclick={ignoreUpdate}>Ignore this version</button>
          </div>
        {:else}
          <div class="flex items-center gap-3">
            <span class="sys-action-icon is-good"><Icon name="check" size={16} /></span>
            <div>
              <p class="text-[13px] font-medium text-ink">You are on the latest version</p>
              <p class="text-[11.5px] text-faint">{update.current}{update.latest && update.latest !== "unknown" ? ` matches ${update.latest}` : ""}</p>
            </div>
          </div>
        {/if}
      {:else}
        <p class="text-[12px] text-muted">{update?.reason || "Could not check for updates."}</p>
      {/if}
    </Card>

    <!-- ── Reaching the panel from a phone ─────────────────────────────────── -->
    <Card title={device?.phone ? "Open on another device" : "Open on your phone"}>
      {#if !net}
        <div class="h-32 animate-pulse rounded-lg bg-white/[0.03]"></div>
      {:else}
        <div class="flex items-center gap-4">
          {#if net.qr}
            <!-- Click for a big one: 104px is readable up close, not across a desk. -->
            <button type="button" class="sys-qr" class:is-off={net.bind === "127.0.0.1"}
                    onclick={() => (qrOpen = true)} title="Show it big, to scan" aria-label="Show the QR code big">
              <!-- Rendered server side by segno, so nothing is fetched from a
                   QR service and the address never leaves the machine. -->
              {@html net.qr}
              <span class="sys-qr-zoom"><Icon name="expand" size={12} /></span>
            </button>
          {/if}
          <div class="min-w-0 flex-1">
            <div class="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-faint">
              {net.reachable ? "On this network" : "On this machine only"}
            </div>
            <button type="button" class="mt-1 block max-w-full truncate font-mono text-[13px] text-accent hover:underline"
                    onclick={() => copy(net.qr_target)} title="Copy">{net.qr_target}</button>
            <div class="mt-0.5 text-[11px] text-faint">{copied === net.qr_target ? "Copied." : "Click to copy."}</div>
            <div class="mt-2 flex gap-4 text-[11.5px]">
              {#if net.ip}<span class="text-muted">IP <span class="font-mono text-ink">{net.ip}</span></span>{/if}
              <span class="text-muted">Port <span class="font-mono text-ink">{net.port}</span></span>
            </div>
          </div>
        </div>

        <div class="mt-4 flex items-center justify-between gap-3 border-t border-edge/50 pt-3">
          <div class="min-w-0">
            <div class="text-[13px] text-ink">Let other devices on this network in</div>
            <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
              Needed to scan the code from your phone. Takes effect after a restart.
            </p>
          </div>
          <div class="shrink-0">
            <Toggle checked={net.bind !== "127.0.0.1"} disabled={bindBusy} onchange={(v: boolean) => setBind(v)} />
          </div>
        </div>

        {#if net.bind !== "127.0.0.1"}
          <p class="mt-2 rounded-lg border border-warn/30 bg-warn/[0.06] px-3 py-2 text-[11px] leading-relaxed text-warn">
            Anyone who can reach this machine can open the panel, and the panel
            holds your tokens and keys. Keep it to networks you trust, and never
            forward the port from your router.
          </p>
        {/if}

        {#if !net.enabled}
          <p class="mt-2 text-[11px] text-faint">
            The WebUI is switched off for the next start.
            <button type="button" class="text-accent hover:underline"
                    onclick={() => { settingsSection.set("Services"); window.location.hash = "/settings"; }}>
              Turn it back on in Settings.
            </button>
          </p>
        {/if}
      {/if}
    </Card>

    <!-- ── About ──────────────────────────────────────────────────────────── -->
    <Card title="About">
      {#snippet actions()}
        <button type="button" onclick={() => openExternal("project", PROJECT_URL)}
                title="The project on GitHub" aria-label="Open the project on GitHub"
                class="jelly flex h-7 w-7 items-center justify-center rounded-lg text-muted hover:bg-white/10 hover:text-ink">
          <Icon name="github" size={16} />
        </button>
      {/snippet}
      {#if infoLoading}
        <div class="space-y-1.5">
          {#each [1, 2, 3] as _}<div class="h-4 animate-pulse rounded bg-white/[0.03]"></div>{/each}
        </div>
      {:else}
        <div class="grid grid-cols-2 gap-2 domino" use:domino={{ step: 60, level: 0.5 }}>
          <div class="sys-fact"><span>Version</span><b>{info?.version}</b></div>
          <div class="sys-fact"><span>Build</span><b>{info?.frozen ? "App (exe)" : "From source"}</b></div>
          <div class="sys-fact"><span>Python</span><b>{info?.python}</b></div>
          <div class="sys-fact"><span>System</span><b class="truncate" title={info?.os}>{info?.os}</b></div>
        </div>
      {/if}
    </Card>
  </div>
</div>

<style>
  .sys-hero {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 16px;
    margin-bottom: 16px;
    padding: 18px 20px;
    border-radius: 20px;
    background-image: radial-gradient(90% 140% at 0% 0%, var(--hero-tint), transparent 60%);
    --hero-tint: color-mix(in srgb, var(--color-good) 14%, transparent);
  }
  .sys-hero[data-tone="warn"] { --hero-tint: color-mix(in srgb, var(--color-warn) 14%, transparent); }
  .sys-hero[data-tone="busy"] { --hero-tint: color-mix(in srgb, var(--color-accent) 12%, transparent); }
  .sys-ring {
    position: relative;
    display: grid;
    flex-shrink: 0;
    place-items: center;
    color: var(--color-good);
  }
  .sys-hero[data-tone="warn"] .sys-ring { color: var(--color-warn); }
  .sys-hero[data-tone="busy"] .sys-ring { color: var(--color-accent); }
  .sys-ring-icon {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
  }
  /* As the tab opens: the ring draws itself round from twelve o'clock, then its
     mark pops in, the chime with it (lib/domino.ts chime). */
  .sys-ring :global(.fill) { animation: sys-draw 0.85s cubic-bezier(0.3, 0.9, 0.3, 1) backwards; }
  @keyframes sys-draw { from { stroke-dashoffset: 37.7; } }
  .sys-ring-icon :global(svg) { animation: sys-mark 0.6s var(--jelly) 0.5s backwards; }
  @keyframes sys-mark { from { opacity: 0; transform: scale(0.3) rotate(-25deg); } }
  :global(:root[data-motion="off"]) .sys-ring :global(.fill),
  :global(:root[data-motion="off"]) .sys-ring-icon :global(svg) { animation: none; }
  .sys-icon-btn {
    display: inline-flex;
    width: 32px;
    height: 30px;
    align-items: center;
    justify-content: center;
    border-radius: 10px;
    color: var(--color-muted);
    box-shadow: inset 0 0 0 1px var(--color-edge);
    transition: background-color 0.15s ease, color 0.15s ease;
  }
  .sys-icon-btn:hover { background: rgb(255 255 255 / 0.07); color: var(--color-ink); }

  .sys-problem {
    padding: 12px 14px;
    border-radius: 14px;
    background: color-mix(in srgb, var(--color-warn) 7%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-warn) 24%, transparent);
  }
  .sys-problem-icon {
    display: grid;
    width: 28px;
    height: 28px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 9px;
    color: var(--color-warn);
    background: color-mix(in srgb, var(--color-warn) 14%, transparent);
  }
  .sys-ok {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 9px;
    padding: 8px 10px;
    border-radius: 11px;
    background: rgb(255 255 255 / 0.03);
    transition: background-color 0.15s ease, transform 0.4s var(--jelly);
  }
  .sys-ok:hover { background: rgb(255 255 255 / 0.055); transform: translateY(-1px); }
  .sys-ok:active { transform: scale(0.97); transition-duration: 0.08s; }
  .sys-ok:hover .sys-ok-icon { transform: scale(1.15) rotate(-8deg); }
  .sys-ok-icon {
    display: grid;
    width: 20px;
    height: 20px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    color: var(--color-good);
    background: color-mix(in srgb, var(--color-good) 15%, transparent);
    transition: transform 0.4s var(--jelly);
  }
  :global(:root[data-motion="off"]) .sys-ok,
  :global(:root[data-motion="off"]) .sys-ok-icon { transition: none; }

  .sys-action {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 12px;
    padding: 12px;
    border-radius: 14px;
    background: rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
    transition: background-color 0.15s ease, box-shadow 0.15s ease, transform 0.2s var(--spring);
  }
  .sys-action:hover:not(:disabled) {
    background: color-mix(in srgb, var(--color-accent) 7%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 40%, transparent);
  }
  .sys-action:active:not(:disabled) { transform: scale(0.98); }
  .sys-action:disabled { opacity: 0.7; cursor: default; }
  .sys-action-icon {
    display: grid;
    width: 36px;
    height: 36px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 11px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  }
  .sys-action-icon.is-good {
    color: var(--color-good);
    background: color-mix(in srgb, var(--color-good) 14%, transparent);
  }
  .sys-spin {
    width: 14px;
    height: 14px;
    border-radius: 999px;
    border: 1.5px solid currentColor;
    border-top-color: transparent;
    animation: sys-turn 0.9s linear infinite;
  }
  @keyframes sys-turn { to { transform: rotate(360deg); } }
  .sys-storage {
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid color-mix(in srgb, var(--color-edge) 60%, transparent);
  }

  .sys-ver {
    padding: 4px 10px;
    border-radius: 999px;
    font-family: ui-monospace, monospace;
    font-size: 12px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.05);
  }
  .sys-ver.is-new {
    color: var(--color-ink);
    font-weight: 600;
    background: color-mix(in srgb, var(--color-accent) 20%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 45%, transparent);
  }

  .sys-qr {
    position: relative;
    display: block;
    width: 104px;
    flex-shrink: 0;
    padding: 7px;
    border-radius: 12px;
    background: #fff;
    cursor: zoom-in;
    transition: opacity 0.2s ease, filter 0.2s ease, transform 0.2s var(--spring), box-shadow 0.2s ease;
  }
  .sys-qr:hover { transform: scale(1.04); box-shadow: 0 10px 28px -12px rgb(0 0 0 / 0.8); }
  .sys-qr-zoom {
    position: absolute;
    right: -6px;
    bottom: -6px;
    display: grid;
    width: 22px;
    height: 22px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-bg);
    background: var(--color-accent);
    opacity: 0;
    transition: opacity 0.15s ease;
  }
  .sys-qr:hover .sys-qr-zoom { opacity: 1; }
  .qr-view {
    position: fixed;
    inset: 0;
    z-index: 80;
    display: grid;
    place-items: center;
    padding: 20px;
    background: rgb(0 0 0 / 0.72);
    backdrop-filter: blur(8px);
    animation: qr-fade 0.2s ease both;
  }
  .qr-card {
    position: relative;
    padding: 22px 22px 18px;
    border-radius: 24px;
    background: var(--color-card);
    box-shadow: 0 30px 80px -30px rgb(0 0 0 / 0.9), inset 0 0 0 1px rgb(255 255 255 / 0.06);
    animation: qr-pop 0.35s var(--spring) both;
  }
  /* As big as the window allows, on white, with the quiet zone scanners need. */
  .qr-big {
    width: min(78vw, 64vh, 440px);
    padding: 18px;
    border-radius: 18px;
    background: #fff;
  }
  .qr-big :global(svg) { display: block; width: 100%; height: auto; }
  .qr-big.is-off { opacity: 0.5; }
  .qr-close {
    position: absolute;
    right: 10px;
    top: 10px;
    display: grid;
    width: 30px;
    height: 30px;
    place-items: center;
    border-radius: 999px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.06);
  }
  .qr-close:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.12); }
  @keyframes qr-fade { from { opacity: 0; } to { opacity: 1; } }
  @keyframes qr-pop { from { opacity: 0; transform: scale(0.9); } to { opacity: 1; transform: none; } }
  /* Only this machine can use the address while the panel is local-only, so
     the code is shown, but dimmed, until the network toggle is on. */
  .sys-qr.is-off { opacity: 0.35; filter: grayscale(1); }

  .sys-fact {
    display: flex;
    min-width: 0;
    flex-direction: column;
    padding: 9px 11px;
    border-radius: 11px;
    background: rgb(255 255 255 / 0.03);
  }
  .sys-fact span { font-size: 10.5px; color: var(--color-faint); }
  .sys-fact b { margin-top: 1px; font-size: 12.5px; font-weight: 500; color: var(--color-ink); }

  :global(:root[data-motion="off"]) .sys-spin { animation: none; }
</style>
