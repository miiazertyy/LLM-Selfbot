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
  import { toast, settingsSection } from "../lib/stores";
  import { resource } from "../lib/resource";
  import { pickFolder, pickFile, openExternal } from "../lib/window";
  import Card from "../lib/components/Card.svelte";
  import Badge from "../lib/components/Badge.svelte";
  import Button from "../lib/components/Button.svelte";
  import Toggle from "../lib/components/Toggle.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import Icon from "../lib/components/Icon.svelte";

  type Action = {
    kind: "install" | "link" | "goto" | "open";
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
  const checks = $derived($doctor.data.checks ?? []);

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

  const failing = $derived(checks.filter((c) => !c.ok).length);

  onMount(() => {
    // Fired together, awaited separately: whichever answers first is shown
    // first, and the slow one never holds up the others.
    sysInfo.refresh({ maxAge: 30000 });
    network.refresh({ maxAge: 15000 });
    updates.refresh({ maxAge: 300000 });
    // Separately, so a slow probe never holds up the rest of the page.
    doctor.refresh({ maxAge: 60000 });
    // The installers report progress over the same log stream the rest of the
    // app uses, so the page can show what is happening instead of a spinner.
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/ws`);
    ws.onmessage = (e) => {
      const entry = JSON.parse(e.data);
      if (entry.source === "ffmpeg-install" || entry.source === "snapchat-install") {
        installLog = [...installLog.slice(-40), entry.text];
      }
    };
    return () => ws.close();
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
      window.open(a.url, "_blank", "noopener");
      return;
    }
    if (a.kind === "goto" && a.route) {
      if (a.section) settingsSection.set(a.section);
      window.location.hash = `/${a.route}`;
      return;
    }
    busy[c.id] = true;
    try {
      if (a.kind === "open") {
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

  async function restartApp() {
    if (!confirm("Close the app and start it again? Accounts reconnect after a few seconds.")) {
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

  async function runUpdate() {
    updating = true;
    try {
      await api.updateRun();
      toast("Update queued. The app will restart.", "info");
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
      const r = await api.exportAll(folder);
      lastExport = r.path;
      toast(`Exported ${r.files} files.`, "ok");
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
    if (!confirm("Replace the current config, keys, memory and pictures with this backup?")) return;
    importing = true;
    try {
      const r = await api.importAll(path);
      toast(`Imported ${r.files} files. Restart the app.`, "ok");
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

{#if loading}
  <div class="glass h-64 animate-pulse"></div>
{:else}
  <div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
    <!-- ── Dependency doctor ─────────────────────────────────────────────── -->
    <Card title="Dependency doctor">
      {#snippet actions()}
        <span class="text-[11px] {failing ? 'text-warn' : 'text-good'}">
          {doctorLoading ? "checking" : failing ? `${failing} need attention` : "all good"}
        </span>
      {/snippet}

      {#if doctorLoading}
        <div class="space-y-1.5">
          {#each [1, 2, 3, 4, 5] as _}
            <div class="h-11 animate-pulse rounded-lg bg-white/[0.03]"></div>
          {/each}
          <p class="pt-1 text-[11px] text-faint">
            Checking what is installed. Finding Chrome starts node, which takes
            a few seconds.
          </p>
        </div>
      {/if}
      <div class="space-y-1.5">
        {#each checks as c (c.id)}
          <div class="rounded-lg border {c.ok ? 'border-transparent bg-white/[0.03]' : 'border-warn/25 bg-warn/[0.05]'}">
            <button
              type="button"
              class="flex w-full items-center gap-3 px-3 py-2.5 text-left"
              onclick={() => (open[c.id] = !open[c.id])}
            >
              <span class="shrink-0">
                <Badge tone={c.ok ? "good" : "bad"}>{c.ok ? "ok" : "missing"}</Badge>
              </span>
              <!-- min-w-0 is what actually lets `truncate` work: without it the
                   flex child refuses to shrink below its content, so a long
                   path like C:\Program Files\nodejs\node.EXE pushed the card
                   wide. -->
              <span class="min-w-0 flex-1">
                <span class="block text-[13px] text-ink">{c.name}</span>
                {#if c.detail}
                  <span class="block truncate font-mono text-[11px] text-faint" title={c.detail}>
                    {c.detail}
                  </span>
                {/if}
              </span>
              <span
                class="shrink-0 text-faint transition-transform duration-200"
                style="transform: rotate({open[c.id] ? 90 : 0}deg)"
              >
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                  <path d="M4.5 2.5 8 6l-3.5 3.5" stroke="currentColor" stroke-width="1.4"
                        stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </span>
            </button>

            {#if open[c.id]}
              <div class="space-y-2.5 border-t border-edge/50 px-3 py-3">
                {#if c.why}
                  <p class="text-[12px] leading-relaxed text-muted">{c.why}</p>
                {/if}
                {#if c.fix}
                  <p class="text-[12px] leading-relaxed text-ink/80">{c.fix}</p>
                {/if}
                {#if c.action}
                  <Button size="sm" loading={busy[c.id]} onclick={() => act(c)}>
                    {c.action.label}
                  </Button>
                {/if}
              </div>
            {/if}
          </div>
        {/each}
      </div>

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

    <div class="space-y-4">
      <!-- ── Reaching the panel from a phone ─────────────────────────────── -->
      <Card title="Open on another device">
        {#if !net}
          <div class="h-32 animate-pulse rounded-lg bg-white/[0.03]"></div>
        {:else}
          <div class="flex flex-col gap-4 sm:flex-row sm:items-start">
            {#if net.qr}
              <div class="mx-auto w-32 shrink-0 rounded-lg bg-white p-2 sm:mx-0">
                <!-- Rendered server side by segno, so nothing is fetched from
                     a QR service and the address never leaves the machine. -->
                {@html net.qr}
              </div>
            {/if}

            <div class="min-w-0 flex-1 space-y-3">
              <div>
                <div class="text-[10px] uppercase tracking-[0.12em] text-faint">
                  {net.reachable ? "On this network" : "On this machine"}
                </div>
                <button
                  type="button"
                  class="mt-1 block max-w-full truncate font-mono text-[13px] text-accent hover:underline"
                  onclick={() => copy(net.qr_target)}
                  title="Copy"
                >
                  {net.qr_target}
                </button>
                <div class="mt-0.5 text-[11px] text-faint">
                  {copied === net.qr_target ? "Copied." : "Click to copy."}
                </div>
              </div>

              {#if net.ip}
                <div class="flex items-baseline justify-between gap-3 text-[12px]">
                  <span class="text-muted">This machine</span>
                  <span class="truncate font-mono text-ink">{net.ip}</span>
                </div>
              {/if}
              <div class="flex items-baseline justify-between gap-3 text-[12px]">
                <span class="text-muted">Port</span>
                <span class="font-mono text-ink">{net.port}</span>
              </div>
            </div>
          </div>

          <div class="mt-4 flex items-center justify-between gap-3 border-t border-edge/50 pt-3">
            <div class="min-w-0">
              <div class="text-[13px] text-ink">Let other devices on this network in</div>
              <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
                Off means only this machine can open the panel. Turn it on to
                scan the code from your phone. Takes effect after a restart.
              </p>
            </div>
            <div class="shrink-0">
              <Toggle
                checked={net.bind !== "127.0.0.1"}
                disabled={bindBusy}
                onchange={(v: boolean) => setBind(v)}
              />
            </div>
          </div>

          {#if net.bind !== "127.0.0.1"}
            <p class="mt-2 rounded-lg border border-warn/30 bg-warn/[0.06] px-3 py-2 text-[11px] leading-relaxed text-warn">
              Anyone who can reach this machine can open the panel, and the
              panel holds your tokens and keys. Keep it to networks you trust,
              and never forward the port from your router.
            </p>
          {/if}

          {#if !net.enabled}
            <p class="mt-2 text-[11px] text-faint">
              The panel is switched off for the next start.
              <button
                type="button"
                class="text-accent hover:underline"
                onclick={() => {
                  settingsSection.set("Services");
                  window.location.hash = "/settings";
                }}>Turn it back on in Settings.</button>
            </p>
          {/if}
        {/if}
      </Card>

      <Card title="Restart">
        <p class="mb-3 text-[12px] leading-relaxed text-muted">
          Closes the app and opens it again, exactly as if you had quit and
          reopened it. Some settings, the port and the data folder among them,
          are only read at startup, so this is how they take effect.
        </p>
        <Button kind="ghost" loading={restarting} onclick={restartApp}>
          {restarting ? "Restarting" : "Restart the app"}
        </Button>
      </Card>

      <Card title="Backup and restore">
        <p class="text-[12px] leading-relaxed text-muted">
          Everything the app knows: config, keys, persona, memory, pictures and
          account identities, in one zip. It contains your tokens, so keep it
          somewhere private.
        </p>

        {#if storageInfo}
          <div class="mt-3 flex items-baseline justify-between gap-3 text-[11px]">
            <span class="text-muted">{storageInfo.files} files</span>
            <span class="font-mono text-faint">{mb(storageInfo.size)}</span>
          </div>
          <button
            type="button"
            class="mt-0.5 block w-full truncate text-left font-mono text-[10px] text-faint hover:text-accent"
            title={storageInfo.data_dir}
            onclick={() => api.openFolder("data").catch(() => {})}
          >{storageInfo.data_dir}</button>
          {#if storageInfo.portable}
            <p class="mt-2 rounded-lg border border-good/30 bg-good/[0.06] px-2.5 py-1.5 text-[11px] text-good">
              Portable install. Everything lives beside the app, nothing is
              written to AppData.
            </p>
          {:else}
            <p class="mt-2 text-[10px] leading-relaxed text-faint">
              To keep everything beside the app instead, make a folder called
              <code class="text-accent">portable</code> next to it and restart.
              Export first, then import once it restarts.
            </p>
          {/if}
        {/if}

        <div class="mt-3 flex flex-wrap gap-2">
          <Button kind="good" size="sm" loading={exporting} onclick={exportAll}>Export everything</Button>
          <Button kind="ghost" size="sm" loading={importing} onclick={importAll}>Import a backup</Button>
        </div>
        {#if lastExport}
          <p class="mt-2 break-all text-[11px] text-good">Saved to {lastExport}</p>
        {/if}
      </Card>

      <Card title="Updates">
        {#snippet actions()}
          <span class="font-mono text-[11px] text-faint">v{info?.version ?? "?"}</span>
        {/snippet}

        {#if updateLoading}
          <div class="h-14 animate-pulse rounded-lg bg-white/[0.03]"></div>
        {:else if update?.ok}
          <!-- "Latest is v1.6.0" says nothing on its own: what matters is
               whether that is newer than what is running. -->
          {#if update.update_available}
            <div class="flex items-baseline justify-between gap-3">
              <p class="text-[13px] text-ink">
                <span class="font-semibold text-accent">{update.latest}</span> is available
              </p>
              <span class="shrink-0 text-[11px] text-faint">you have {update.current}</span>
            </div>
            <p class="mt-1 line-clamp-4 whitespace-pre-line text-[11px] leading-relaxed text-muted">
              {update.notes}
            </p>
            <div class="mt-3 flex flex-wrap items-center gap-2">
              <Button onclick={runUpdate} loading={updating}>Update now</Button>
              <!-- Dismissing it clears the dot as well, and stays dismissed
                   until there is a release newer than this one. -->
              <button class="px-1 text-[11px] text-faint hover:text-ink"
                      onclick={ignoreUpdate}>Ignore this version</button>
            </div>
          {:else}
            <p class="text-[13px] text-good">You are on the latest version.</p>
            <p class="mt-0.5 text-[11px] text-faint">
              {update.current} matches the newest release{update.latest && update.latest !== "unknown"
                ? ` (${update.latest})` : ""}.
            </p>
          {/if}
        {:else}
          <p class="text-[12px] text-muted">{update?.reason || "Could not check for updates."}</p>
        {/if}
      </Card>

      <Card title="About">
        {#snippet actions()}
          <button
            type="button"
            onclick={() => openExternal("project", PROJECT_URL)}
            title="The project on GitHub"
            aria-label="Open the project on GitHub"
            class="jelly flex h-7 w-7 items-center justify-center rounded-lg text-muted
                   hover:bg-white/10 hover:text-ink"
          >
            <Icon name="github" size={16} />
          </button>
        {/snippet}
        {#if infoLoading}
          <div class="space-y-1.5">
            {#each [1, 2, 3] as _}
              <div class="h-4 animate-pulse rounded bg-white/[0.03]"></div>
            {/each}
          </div>
        {:else}
        <div class="space-y-1.5 text-[12px]">
          <div class="flex justify-between gap-3">
            <span class="text-muted">Version</span><span>{info?.version}</span>
          </div>
          <div class="flex justify-between gap-3">
            <span class="text-muted">Packaged</span>
            <span>{info?.frozen ? "yes, exe" : "no, source"}</span>
          </div>
          <div class="flex justify-between gap-3">
            <span class="text-muted">Python</span><span>{info?.python}</span>
          </div>
          <button
            type="button"
            class="mt-1 block w-full truncate text-left text-[11px] text-faint hover:text-accent"
            title={info?.data_dir}
            onclick={() => api.openFolder("data").catch(() => {})}
          >
            Data: {info?.data_dir}
          </button>
        </div>
        {/if}
      </Card>
    </div>
  </div>
{/if}
