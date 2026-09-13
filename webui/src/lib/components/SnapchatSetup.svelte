<script lang="ts">
  /**
   * Getting Snapchat able to run.
   *
   * This used to be a whole tab of its own, which was odd for something you
   * touch once: it is setup, so it lives in Settings with the rest of the
   * setup.
   *
   * Snapchat has no API, so it drives a real Chrome through Puppeteer. Two
   * separate things have to be in place, and they fail independently, so they
   * are reported separately.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import { toast } from "../stores";
  import Button from "./Button.svelte";
  import Badge from "./Badge.svelte";

  type SnapStatus = {
    node: string | null;
    npm: string | null;
    modules_installed?: boolean;
    browser?: string;
    deps_installed: boolean;
    installing: boolean;
    dir: string;
  };

  let status = $state<SnapStatus | null>(null);
  let logs = $state<{ time: string; text: string }[]>([]);
  let ws: WebSocket | null = null;

  onMount(() => {
    load();
    const t = setInterval(load, 3000);
    connect();
    return () => {
      clearInterval(t);
      ws?.close();
    };
  });

  async function load() {
    try {
      status = await api.snapStatus();
    } catch {
      /* the panel still works without it */
    }
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/api/ws`);
    ws.onmessage = (e) => {
      const entry = JSON.parse(e.data);
      if (entry.source === "snapchat-install") logs = [...logs.slice(-99), entry];
    };
  }

  async function install() {
    try {
      await api.snapInstall();
      toast("Install started. Watch the log below.", "info");
    } catch (e: any) {
      toast(e.message, "err");
    }
  }
</script>

{#if !status}
  <div class="h-40 animate-pulse rounded-xl bg-white/[0.03]"></div>
{:else}
  <div class="space-y-5">
    <div class="divide-y divide-edge/60">
      <div class="flex items-center justify-between gap-3 py-3">
        <div class="min-w-0">
          <div class="text-[13px] text-ink">Node.js</div>
          <p class="mt-0.5 text-[11px] text-faint">Runs the browser automation.</p>
        </div>
        <span class="min-w-0 truncate text-right font-mono text-[11px] {status.node ? 'text-good' : 'text-bad'}"
              title={status.node || "not found"}>
          {status.node ? status.node : "not found"}
        </span>
      </div>

      <div class="flex items-center justify-between gap-3 py-3">
        <div class="min-w-0">
          <div class="text-[13px] text-ink">npm</div>
          <p class="mt-0.5 text-[11px] text-faint">Installs the packages below.</p>
        </div>
        <span class="min-w-0 truncate text-right font-mono text-[11px] {status.npm ? 'text-good' : 'text-bad'}"
              title={status.npm || "not found"}>
          {status.npm ? status.npm : "not found"}
        </span>
      </div>

      <div class="flex items-center justify-between gap-3 py-3">
        <div class="min-w-0">
          <div class="text-[13px] text-ink">Node packages</div>
          <p class="mt-0.5 text-[11px] text-faint">Puppeteer and the stealth plugins.</p>
        </div>
        <Badge tone={status.modules_installed ? "good" : status.installing ? "warn" : "muted"}>
          {status.modules_installed ? "installed" : status.installing ? "installing" : "missing"}
        </Badge>
      </div>

      <div class="flex items-center justify-between gap-3 py-3">
        <div class="min-w-0">
          <div class="text-[13px] text-ink">Chrome</div>
          <p class="mt-0.5 text-[11px] text-faint">
            About 180 MB, downloaded once. Tracked separately because the
            download can fail on its own.
          </p>
        </div>
        {#if status.browser}
          <span class="min-w-0 truncate text-right font-mono text-[11px] text-good" title={status.browser}>
            {status.browser}
          </span>
        {:else}
          <Badge tone={status.installing ? "warn" : "bad"}>
            {status.installing ? "downloading" : "missing"}
          </Badge>
        {/if}
      </div>
    </div>

    {#if status.modules_installed && !status.browser && !status.installing}
      <p class="rounded-lg border border-warn/40 bg-warn/[0.07] px-3 py-2 text-[12px] text-warn">
        The packages are there but Chrome is not. That usually means the
        download was interrupted. Repairing clears the partial download and
        fetches it again.
      </p>
    {/if}

    <div class="flex flex-wrap items-center gap-3">
      {#if !status.deps_installed && !status.installing}
        <Button onclick={install} disabled={!status.npm}>
          {status.modules_installed ? "Repair install" : "Install Snapchat support"}
        </Button>
      {:else if status.installing}
        <Button loading disabled>Installing</Button>
      {:else}
        <span class="text-[12px] text-good">Snapchat is ready to run.</span>
      {/if}
      {#if !status.node}
        <span class="text-[12px] text-bad">Install Node.js from nodejs.org first.</span>
      {/if}
    </div>

    <p class="text-[11px] leading-relaxed text-faint">
      Installs into <code class="break-all text-accent">{status.dir}</code>,
      outside the app, so it survives updates.
    </p>

    {#if logs.length}
      <div>
        <div class="mb-1.5 text-[10px] uppercase tracking-[0.12em] text-faint">Install log</div>
        <div class="h-56 overflow-y-auto rounded-lg bg-black/40 p-3 font-mono text-[11px] leading-relaxed">
          {#each logs as l}
            <div class="flex gap-2">
              <span class="shrink-0 text-faint">{l.time}</span>
              <span class="break-all text-ink/85">{l.text}</span>
            </div>
          {/each}
        </div>
      </div>
    {/if}

    <div class="border-t border-edge/60 pt-3 text-[11px] leading-relaxed text-muted">
      <p>The first login needs a visible browser window, so turn off
        <span class="font-mono text-faint">snapchat.headless</span> for it.
        Cookies are saved afterwards, so later runs can be headless.</p>
      <p class="mt-1.5">Credentials live under Keys and secrets, as
        <span class="font-mono text-faint">SNAP_USERNAME</span> and
        <span class="font-mono text-faint">SNAP_PASSWORD</span>.</p>
    </div>
  </div>
{/if}
