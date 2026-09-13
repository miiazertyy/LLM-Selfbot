<script lang="ts">
  /**
   * The selfies the bot can send, and what it thinks each one shows.
   *
   * The description is the part that matters: the model never sees the image
   * when it is picking one, only this text, so a picture without a description
   * can never be sent. That used to be a grey "no desc" label in a corner. It
   * is now the loudest thing on the card, with a button that fixes it.
   */
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { toast } from "../lib/stores";
  import { describeState, describeTick, watchDescribe } from "../lib/pictures";
  import { resource } from "../lib/resource";
  import Card from "../lib/components/Card.svelte";
  import Button from "../lib/components/Button.svelte";
  import Empty from "../lib/components/Empty.svelte";
  import Modal from "../lib/components/Modal.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import ErrorNote from "../lib/components/ErrorNote.svelte";

  type Pic = { name: string; description: string; size?: number };

  // Kept between visits: the list and its thumbnails are already correct when
  // you come back, and only refresh behind what is on screen.
  const gallery = resource("pictures", () => api.pictures(), { pictures: [] as Pic[] });
  const pics = $derived($gallery.data.pictures ?? []);
  const loading = $derived(!$gallery.fetched && $gallery.loading);
  const loadError = $derived($gallery.error);
  let uploading = $state(false);
  let progress = $state("");
  let editing = $state<Pic | null>(null);
  let editDesc = $state("");
  let dragOver = $state(false);
  let busy = $state<Record<string, boolean>>({});
  let confirming = $state<Pic | null>(null);
  let view = $state<Pic | null>(null);
  let queueing = $state(false);
  /** Descriptions run long, so each card can be opened out in place. */
  let expanded = $state<Record<string, boolean>>({});

  // Owned by lib/pictures.ts so the bar keeps its place when you leave the tab
  // and come back: the work is on the server, so the progress belongs outside
  // any one page.
  const describing = $derived($describeState);

  const missing = $derived(pics.filter((p) => !p.description).length);
  const dirty = $derived(editing ? editDesc.trim() !== editing.description.trim() : false);

  onMount(() => {
    gallery.refresh({ maxAge: 10000 });
    // Picks up a run already in progress, which is exactly the case that used
    // to show an empty page while the server was still working.
    watchDescribe();
  });

  const load = () => gallery.refresh({ force: true });

  async function uploadFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    uploading = true;
    const list = Array.from(files);
    let startedDescribing = false;

    for (const [i, file] of list.entries()) {
      progress = list.length > 1 ? `${i + 1} of ${list.length}` : file.name;
      try {
        const r = await api.uploadPicture(file);
        if (r.zip) {
          // A folder of pictures arrives as one archive, so the summary is
          // per archive rather than per file.
          const parts = [`Added ${r.added.length} picture${r.added.length === 1 ? "" : "s"}`];
          if (r.skipped?.length) parts.push(`skipped ${r.skipped.length}`);
          toast(parts.join(", ") + ".", r.added.length ? "ok" : "err");
          for (const s of (r.skipped || []).slice(0, 3)) {
            toast(`${s.name}: ${s.reason}`, "info");
          }
          if (r.describing) startedDescribing = true;
        } else if (r.description) {
          toast(`Added ${r.name} and described it.`, "ok");
        } else {
          toast(r.reason ? `Added ${r.name}. ${r.reason}` : `Added ${r.name}.`, "info");
        }
      } catch (e: any) {
        toast(`${file.name}: ${e.message}`, "err");
      }
    }

    uploading = false;
    progress = "";
    load();
    if (startedDescribing) watchDescribe();
  }

  // A description landing means the list is out of date. An effect always runs
  // once on mount, though, and firing a forced reload there defeated the cache
  // entirely: every visit to the tab went back to the server regardless.
  let lastTick = $state<number | null>(null);
  $effect(() => {
    const tick = $describeTick;
    if (lastTick === null) {
      lastTick = tick;        // the mount run, nothing has actually changed
      return;
    }
    if (tick !== lastTick) {
      lastTick = tick;
      load();
    }
  });

  async function describeMissing() {
    queueing = true;
    try {
      const r = await api.describeMissing();
      if (r.queued) {
        toast(`Describing ${r.queued} picture${r.queued === 1 ? "" : "s"}.`, "ok");
        watchDescribe();
      } else {
        toast("Everything already has a description.", "info");
      }
    } catch (e: any) {
      toast(e.message, "err");
    }
    queueing = false;
  }

  async function reanalyse(p: Pic) {
    busy[p.name] = true;
    try {
      const r = await api.analysePicture(p.name);
      if (r.ok) toast("Described.", "ok");
      else toast(r.reason || "Could not describe it.", "err");
    } catch (e: any) {
      toast(e.message, "err");
    }
    busy[p.name] = false;
    load();
  }

  async function remove(p: Pic) {
    confirming = null;
    try {
      await api.deletePicture(p.name);
      toast("Deleted.", "ok");
      load();
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  function openEdit(p: Pic) {
    editing = p;
    editDesc = p.description;
  }

  async function saveDesc() {
    if (!editing) return;
    try {
      await api.setPictureDesc(editing.name, editDesc);
      toast("Saved.", "ok");
      editing = null;
      load();
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  function kb(bytes?: number): string {
    if (!bytes) return "";
    return bytes > 1024 * 1024
      ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
      : `${Math.round(bytes / 1024)} KB`;
  }
</script>

<ErrorNote text={loadError} onretry={load} />

<!-- ── Drop zone ────────────────────────────────────────────────────────── -->
<div
  role="button"
  tabindex="0"
  aria-label="Drop pictures here to add them"
  class="glass mb-4 flex flex-col items-center justify-center gap-2.5 rounded-2xl border border-dashed p-8 text-center transition-colors
    {dragOver ? 'border-accent bg-accent/[0.06]' : 'border-edge'}"
  ondragover={(e) => {
    e.preventDefault();
    dragOver = true;
  }}
  ondragleave={() => (dragOver = false)}
  ondrop={(e) => {
    e.preventDefault();
    dragOver = false;
    uploadFiles(e.dataTransfer?.files ?? null);
  }}
>
  <span class="text-accent {uploading ? 'animate-pulse' : ''}">
    <Icon name={uploading ? "sparkle" : "upload"} size={26} />
  </span>
  <div>
    <p class="text-[13px] text-ink">
      {uploading ? `Adding ${progress}` : "Drop pictures or a zip here"}
    </p>
    <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
      Any format works, it is converted for you. A zip is unpacked including
      its subfolders. Each picture is described automatically, and that
      description is all the bot has to go on when it picks one.
    </p>
  </div>
  <label class="cursor-pointer rounded-lg bg-accent px-3.5 py-1.5 text-[13px] font-medium text-bg transition-colors hover:bg-accent/90">
    Browse files
    <input
      type="file"
      accept="image/*,.zip,.heic,.heif,.avif,.bmp,.tif,.tiff,application/zip"
      multiple
      class="hidden"
      onchange={(e) => uploadFiles((e.target as HTMLInputElement).files)}
    />
  </label>
</div>

{#if describing}
  <!-- The archive is already on disk; this is only the descriptions catching
       up, so it reads as progress rather than as a blocking upload. -->
  <div class="glass mb-4 rounded-xl px-4 py-3">
    <div class="flex items-baseline justify-between gap-3">
      <span class="text-[12px] text-ink">
        Describing the new pictures, {describing.done} of {describing.total}
      </span>
      {#if describing.failed}
        <span class="shrink-0 text-[11px] text-warn">{describing.failed} failed</span>
      {/if}
    </div>
    {#if describing.reason}
      <!-- Almost always a rate limit, which is worth saying out loud: the bar
           otherwise just stops and looks broken. -->
      <p class="mt-1 text-[11px] leading-relaxed text-faint">{describing.reason}</p>
    {/if}
    <div class="mt-2 h-1 overflow-hidden rounded-full bg-white/[0.06]">
      <div
        class="h-full rounded-full bg-accent transition-[width] duration-500"
        style="width: {Math.round((describing.done / Math.max(1, describing.total)) * 100)}%"
      ></div>
    </div>
  </div>
{/if}

{#if missing > 0 && !loading && !describing}
  <div class="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warn/30 bg-warn/[0.06] px-3 py-2.5">
    <p class="min-w-0 flex-1 text-[12px] leading-relaxed text-warn">
      {missing} {missing === 1 ? "picture has" : "pictures have"} no description,
      so {missing === 1 ? "it" : "they"} will never be sent.
    </p>
    <Button size="sm" loading={queueing} onclick={describeMissing}>
      Describe {missing === 1 ? "it" : `all ${missing}`}
    </Button>
  </div>
{/if}

{#if loading}
  <div class="glass h-40 animate-pulse"></div>
{:else if pics.length === 0}
  <Empty
    text="No pictures yet. These are the selfies the bot sends when someone asks for one."
    icon="pictures"
  />
{:else}
  <div class="grid grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-3">
    {#each pics as p (p.name)}
      <Card pad={false}>
        <button
          type="button"
          class="block w-full bg-black/25"
          onclick={() => (view = p)}
          title="View full size"
        >
          <!-- contain, not cover: these are the pictures the bot sends, so
               seeing the whole frame matters more than a tidy grid. The plate
               behind fills whatever the aspect ratio leaves over. -->
          <img
            src={api.pictureUrl(p.name)}
            alt={p.name}
            loading="lazy"
            class="h-56 w-full rounded-t-[var(--radius-card)] object-contain"
          />
        </button>

        <div class="p-4">
          <div class="flex items-baseline justify-between gap-2">
            <span class="truncate font-mono text-[13px] text-ink">{p.name}</span>
            <span class="shrink-0 text-[11px] text-faint">{kb(p.size)}</span>
          </div>

          {#if p.description}
            <div class="mt-2.5 flex items-start gap-2">
              <span class="mt-1 shrink-0 text-accent/70"><Icon name="sparkle" size={14} /></span>
              <p class="min-w-0 text-[13px] leading-[1.6] text-ink/85">
                {expanded[p.name] || p.description.length <= 240
                  ? p.description
                  : p.description.slice(0, 240).trimEnd() + "..."}
              </p>
            </div>
            {#if p.description.length > 240}
              <button
                class="mt-1 text-[11px] text-faint hover:text-accent"
                onclick={() => (expanded[p.name] = !expanded[p.name])}
              >{expanded[p.name] ? "Show less" : "Read all of it"}</button>
            {/if}
          {:else}
            <p class="mt-2.5 text-[13px] leading-relaxed text-warn">
              Not described, so the bot can never send it.
            </p>
          {/if}

          <div class="mt-3.5 flex flex-wrap gap-2">
            <Button size="sm" kind="ghost" onclick={() => openEdit(p)}>
              {p.description ? "Edit" : "Write one"}
            </Button>
            <Button size="sm" kind="ghost" loading={busy[p.name]} onclick={() => reanalyse(p)}>
              {p.description ? "Describe again" : "Describe it"}
            </Button>
            <Button size="sm" kind="danger" onclick={() => (confirming = p)}>Delete</Button>
          </div>
        </div>
      </Card>
    {/each}
  </div>
{/if}

<!-- ── Description editor ───────────────────────────────────────────────── -->
<Modal open={!!editing} title={editing?.name ?? ""} onclose={() => (editing = null)}>
  {#if editing}
    <div class="flex gap-3">
      <img
        src={api.pictureUrl(editing.name)}
        alt=""
        class="h-24 w-24 shrink-0 rounded-lg object-cover ring-1 ring-edge"
      />
      <p class="text-[12px] leading-relaxed text-muted">
        Write what is in the picture, plainly. The bot matches this text against
        what someone asked for, so details help: who is in it, what they are
        wearing, where it was taken, the mood.
      </p>
    </div>
    <textarea
      bind:value={editDesc}
      rows={7}
      class="mt-3 w-full rounded-lg border border-edge bg-black/40 p-3 text-[13px] leading-relaxed outline-none focus:border-accent/50"
      placeholder="A mirror selfie in a bathroom, black hoodie, phone in hand, evening light."
    ></textarea>
    <div class="mt-1.5 flex items-center justify-between text-[11px] text-faint">
      <span>{editDesc.trim().length} characters</span>
      {#if dirty}<span class="text-warn">unsaved</span>{/if}
    </div>
    <div class="mt-4 flex justify-end gap-2">
      <Button kind="ghost" onclick={() => (editing = null)}>Cancel</Button>
      <Button onclick={saveDesc} disabled={!editDesc.trim()}>Save</Button>
    </div>
  {/if}
</Modal>

<!-- ── Full size ────────────────────────────────────────────────────────── -->
<Modal open={!!view} title={view?.name ?? ""} onclose={() => (view = null)} wide>
  {#if view}
    <img
      src={api.pictureUrl(view.name)}
      alt={view.name}
      class="mx-auto max-h-[62vh] w-auto max-w-full rounded-lg object-contain"
    />
    {#if view.description}
      <div class="mt-4">
        <div class="mb-1 text-[10px] uppercase tracking-[0.12em] text-faint">
          What the bot reads
        </div>
        <p class="whitespace-pre-wrap text-[13px] leading-[1.65] text-ink/85">
          {view.description}
        </p>
      </div>
    {:else}
      <p class="mt-4 text-[13px] text-warn">
        No description, so this one is never sent.
      </p>
    {/if}
  {/if}
</Modal>

<!-- ── Delete confirmation ──────────────────────────────────────────────── -->
<Modal open={!!confirming} title="Delete this picture?" onclose={() => (confirming = null)}>
  {#if confirming}
    <p class="text-[13px] leading-relaxed text-muted">
      <span class="font-mono text-ink">{confirming.name}</span> is removed from
      disk and the remaining pictures are renumbered. This cannot be undone.
    </p>
    <div class="mt-4 flex justify-end gap-2">
      <Button kind="ghost" onclick={() => (confirming = null)}>Keep it</Button>
      <Button kind="danger" onclick={() => remove(confirming!)}>Delete</Button>
    </div>
  {/if}
</Modal>
