<script lang="ts">
  /**
   * The selfies the bot can send, and what it thinks each one shows.
   *
   * The description is the part that matters: the model never sees the image
   * when it is picking one, only this text, so a picture without a description
   * can never be sent. That used to be a grey "no desc" label in a corner. It
   * is now the loudest thing on the card, with a button that fixes it.
   *
   * Pictures are known by their id here (media_routes.py _pic_id), not their
   * name. Deleting one renumbers the rest (IMG_3 becomes IMG_2), and when the
   * page went by name it kept showing the old image under each name, so the
   * card you saw as IMG_2 could be the file now called IMG_3, and Delete took
   * the wrong picture. The id is in each picture's address and in every
   * delete, so what goes is exactly what you saw.
   *
   * A description shows three lines, fading out where there is more, with
   * its Markdown drawn rather than printed as asterisks. A click opens it out
   * in place, easing to its full height, and another folds it back. They
   * used to be cut at 240 characters with "..." and a small "Read all of it".
   * New ones are a caption, a line or two (DESCRIBE_PROMPT in
   * app/utils/pictures.py); the long ones from before can be shortened.
   *
   * Deleting is quiet: the picture leaves the page at once with an undo bar,
   * and the disk only when that runs out (or the page is left). A box asking
   * "Delete this picture? This cannot be undone." stood in front of every
   * delete; the undo does the same job without stopping you.
   *
   * A look (warm, film, black and white...) can go on any picture, or on a
   * selection, from LookEditor; the original is kept, so it comes off again.
   * New pictures can get one on their own: the pill by the selection says
   * which, and opens its settings (Settings, AI behaviour, Pictures).
   *
   * Videos go here too, any kind (app/utils/videos.py): each becomes an MP4,
   * made smaller when it is too big to send, and is described from frames
   * across it and what is said in it. A video's card shows its still and how
   * long it is, and plays, muted, while the pointer is on it; opened, it plays
   * with its sound.
   */
  import { onDestroy, onMount, tick } from "svelte";
  import { flip } from "svelte/animate";
  import { scale } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { api } from "../lib/api";
  import { get } from "svelte/store";
  import { picturesBlur, settingsSection, viewPersona } from "../lib/stores";
  import PersonaScope from "../lib/personas/PersonaScope.svelte";
  import { personasRes } from "../lib/personas/store";
  import { play } from "../lib/uisound";
  import { domino } from "../lib/domino";
  import LookEditor from "../lib/components/LookEditor.svelte";
  import Toggle from "../lib/components/Toggle.svelte";
  import { toast } from "../lib/stores";
  import { addPictures, addState, clock, describeState, describeTick, isVideoFile, lookState, VIDEO_EXTS, watchDescribe } from "../lib/pictures";
  import { resource } from "../lib/resource";
  import Card from "../lib/components/Card.svelte";
  import Button from "../lib/components/Button.svelte";
  import Empty from "../lib/components/Empty.svelte";
  import Modal from "../lib/components/Modal.svelte";
  import UndoBar from "../lib/components/UndoBar.svelte";
  import PictureViewer from "../lib/components/PictureViewer.svelte";
  import Icon from "../lib/components/Icon.svelte";
  import Select from "../lib/components/Select.svelte";
  import { renderMarkdown } from "../lib/markdown";
  import { openMenuAt } from "../lib/contextmenu";
  import { saveUrlAs } from "../lib/window";
  import { copyImageFrom } from "../lib/imagecopy";
  import ErrorNote from "../lib/components/ErrorNote.svelte";
  import NotHere from "../lib/components/NotHere.svelte";
  import { notHere } from "../lib/device";

  type Pic = {
    name: string; id?: string; description: string; size?: number; look?: string; strength?: number; moving?: boolean;
    /** An MP4, and how long it is in seconds. */
    video?: boolean; duration?: number;
  };
  /** Who a picture is: its id, which a rename does not change; its name only where there is no id. */
  const keyOf = (p: Pic) => p.id || p.name;

  // ── Whose pictures ────────────────────────────────────────────────────────
  // Each persona sends its own (app/utils/personas.py): Default's are the ones there always were. The one picked
  // here is the one the Personas page last showed, and the other way round.
  let pid = $state(get(viewPersona) || "default");
  /** As the server is told it: "" for Default, whose pictures keep their addresses. */
  const who = $derived(pid === "default" ? "" : pid);
  const cast = $derived($personasRes.data.personas);
  /** Only worth a pill when there is another persona to switch to. */
  const many = $derived(cast.length > 1);
  const whoName = $derived(cast.find((p) => p.id === pid)?.name ?? "");
  // A persona deleted since: Default's.
  $effect(() => {
    if ($personasRes.fetched && cast.length && !cast.some((p) => p.id === pid)) switchTo("default");
  });

  // Kept between visits, one list per persona: the list and its thumbnails are already correct when
  // you come back, and only refresh behind what is on screen.
  function galleryOf(p: string) {
    const as = p === "default" ? "" : p;
    return resource(as ? `pictures:${as}` : "pictures", () => api.pictures(as), { pictures: [] as Pic[] });
  }
  const gallery = $derived(galleryOf(pid));

  function switchTo(next: string) {
    if (next === pid) return;
    // What is waiting to be deleted goes now, from the persona it was deleted from.
    if (leaving.length) commit();
    selected = new Set();
    editing = null;
    view = null;
    lookOpen = false;
    expanded = {};
    pid = next;
    viewPersona.set(next);
    galleryOf(next).refresh({ maxAge: 10000 });
    loadLooks();
  }
  const pics = $derived<Pic[]>($gallery.data.pictures ?? []);
  const loading = $derived(!$gallery.fetched && $gallery.loading);
  const loadError = $derived($gallery.error);
  const adding = $derived($addState);
  const uploading = $derived(!!adding);
  /** How far the adding has got, 0 to 100: the ring round the drop zone's icon and the line along its foot. */
  const addPct = $derived(adding ? Math.round((adding.done / Math.max(1, adding.total)) * 100) : 0);
  /** A video converting: the ring fills with it. Watched to describe it, or one picture alone: the ring turns. */
  const ringPct = $derived(adding?.video?.step === "convert" ? adding.video.percent : addPct);
  const ringSpin = $derived(!!adding && (adding.video ? adding.video.step === "describe" : adding.total === 1));
  // Made an MP4: a click as it slots in, and the watching starts.
  let lastStep = "";
  $effect(() => {
    const step = adding?.video?.step ?? "";
    if (lastStep === "convert" && step === "describe") play("slot", { level: 0.6 });
    lastStep = step;
  });
  /** What a card shows for it: a small copy of the picture, or of a video's still (a full photo per card made the page
      heavy to scroll). Opened, it is the picture itself. */
  const thumbOf = (p: Pic) => api.pictureSmall(p, 480, who);
  /** The video playing under the pointer, muted, by its key. */
  let live = $state("");
  let editing = $state<Pic | null>(null);
  let editDesc = $state("");
  let dragOver = $state(false);
  let busy = $state<Record<string, boolean>>({});
  /** Pictures ticked for bulk delete, by id. Empty means the page is in its normal mode. */
  let selected = $state<Set<string>>(new Set());
  /** Right-click menu: which picture, and where to put it. */
  let copying = $state("");
  let view = $state<Pic | null>(null);
  let queueing = $state(false);
  /** Descriptions opened out to their full length, by picture. */
  let expanded = $state<Record<string, boolean>>({});
  /** Ones folding back: the fade is back on while the height eases down. */
  let closing = $state<Record<string, boolean>>({});
  /** Ones longer than their three lines, which is what makes them open at all. */
  let over = $state<Record<string, boolean>>({});

  /** Opens a description out in place, or folds it back to three lines, easing its height between the two. */
  async function toggleDesc(k: string, box: HTMLElement) {
    // Selecting some of the text is not asking to fold it.
    if (window.getSelection()?.toString()) return;
    const text = box.querySelector<HTMLElement>(".pd-text");
    if (!text || document.documentElement.dataset.motion === "off") {
      expanded[k] = !expanded[k];
      return;
    }
    text.getAnimations().forEach((a) => a.cancel());
    const from = text.getBoundingClientRect().height;
    if (!expanded[k]) {
      expanded[k] = true;
      await tick();
      // Past the full height and back a touch: it lands rather than stops.
      text.animate([{ height: `${from}px` }, { height: `${text.scrollHeight}px` }],
                   { duration: 480, easing: "cubic-bezier(0.22, 1.25, 0.36, 1)" });
    } else {
      closing[k] = true;
      const to = parseFloat(getComputedStyle(text).lineHeight) * 3;
      const fold = text.animate([{ height: `${from}px` }, { height: `${to}px` }],
                                { duration: 320, easing: "cubic-bezier(0.4, 0, 0.2, 1)", fill: "forwards" });
      fold.onfinish = async () => {
        expanded[k] = false;
        closing[k] = false;
        await tick();
        fold.cancel();
      };
      fold.oncancel = () => (closing[k] = false);
    }
  }

  // Whether a description runs past its three lines, looked at again when the
  // card changes width. One observer for every card.
  const overChecks = new WeakMap<Element, () => void>();
  const overObs = new ResizeObserver((entries) => {
    for (const e of entries) overChecks.get(e.target)?.();
  });
  onDestroy(() => overObs.disconnect());
  function overflowing(node: HTMLElement, arg: { text: string; set: (v: boolean) => void }) {
    let cur = arg;
    const check = () => {
      // Opened out, it fits by definition: it still has more than three lines.
      if (node.closest(".pd")?.classList.contains("is-open")) return;
      cur.set(node.scrollHeight > node.clientHeight + 1);
    };
    overChecks.set(node, check);
    overObs.observe(node);
    return {
      update(next: typeof arg) {
        cur = next;
        requestAnimationFrame(check);
      },
      destroy() {
        overObs.unobserve(node);
        overChecks.delete(node);
      },
    };
  }

  // Owned by lib/pictures.ts so the bar keeps its place when you leave the tab
  // and come back: the work is on the server, so the progress belongs outside
  // any one page.
  const describing = $derived($describeState);
  const lookJob = $derived($lookState);

  // ── Looks ─────────────────────────────────────────────────────────────────
  type Look = { id: string; name: string };
  let looksList = $state<Look[]>([]);
  let autoLook = $state<{ mode: string; look: string } | null>(null);
  let lookOpen = $state(false);
  let lookPics = $state<Pic[]>([]);
  const lookName = (id?: string) => looksList.find((l) => l.id === id)?.name ?? "";
  async function loadLooks() {
    const asked = pid;
    try {
      const r: any = await api.pictureLooks(who);
      if (asked !== pid) return;
      looksList = r.looks ?? [];
      autoLook = r.auto ?? null;
    } catch {
      /* the cards still work, with no look button */
    }
  }
  function openLook(list: Pic[]) {
    if (!list.length || !looksList.length) return;
    play("open");
    lookPics = list;
    lookOpen = true;
  }
  /** What new pictures get, as the bar's tag says it. */
  const autoValue = $derived(!autoLook || autoLook.mode === "off" ? "Off"
    : autoLook.mode === "one" ? lookName(autoLook.look) || "On"
    : autoLook.mode === "random" ? "Random" : "AI picks");
  /** What new pictures get, picked where they go in: no filter, the AI's pick, a random one, or one look for all. */
  const autoOptions = $derived([
    { value: "off", label: "No filter", icon: "pictures" },
    { value: "ai", label: "AI picks", hint: "A filter that suits each one", icon: "sparkle" },
    { value: "random", label: "Random", hint: "Any of the filters, each time", icon: "refresh" },
    ...looksList.map((l) => ({ value: `one:${l.id}`, label: l.name, icon: "palette" })),
  ]);
  const autoChoice = $derived(!autoLook || autoLook.mode === "off" ? "off"
    : autoLook.mode === "one" ? `one:${autoLook.look}` : autoLook.mode);
  async function setAuto(v: string | number) {
    const s = String(v);
    const [mode, look] = s.startsWith("one:") ? ["one", s.slice(4)] : [s, autoLook?.look ?? ""];
    const was = autoLook;
    autoLook = { mode, look };
    // This persona's own: what its new pictures get.
    const persona = pid;
    try {
      if (mode === "one") await api.configField("bot.pictures.auto_look.look", look, { persona });
      await api.configField("bot.pictures.auto_look.mode", mode, { persona });
    } catch (e: any) {
      autoLook = was;
      toast(e?.message || "Could not save it", "err");
    }
  }
  function openLookSettings() {
    play("tap");
    settingsSection.set("ai/media");
    window.location.hash = "/settings";
  }

  // ── Deleting, with an undo ────────────────────────────────────────────────
  /** Gone from the page, and can still be brought back. */
  let leaving = $state<Pic[]>([]);
  /** Being deleted now: gone from the page, too late to bring back. */
  let going = $state<Pic[]>([]);
  let undoKey = $state("");
  let commitTimer = 0;
  const UNDO_MS = 6000;
  const isGone = (p: Pic) => leaving.some((l) => keyOf(l) === keyOf(p)) || going.some((g) => keyOf(g) === keyOf(p));
  const shownPics = $derived(pics.filter((p) => !isGone(p)));

  function removeLater(list: Pic[]) {
    const fresh = list.filter((p) => !isGone(p));
    if (!fresh.length) return;
    leaving = [...leaving, ...fresh];
    undoKey = `${Date.now()}`;
    if (selected.size) {
      const next = new Set(selected);
      for (const p of fresh) next.delete(keyOf(p));
      selected = next;
    }
    clearTimeout(commitTimer);
    commitTimer = window.setTimeout(commit, UNDO_MS);
  }
  function undoRemove() {
    clearTimeout(commitTimer);
    leaving = [];
  }
  /** Off the disk: the whole batch in one request, each by its id, then the list as it now is. */
  async function commit() {
    clearTimeout(commitTimer);
    const batch = leaving;
    if (!batch.length) return;
    // Whose they are, taken now: a switch to another persona is what can bring this on.
    const owner = who;
    const list = gallery;
    leaving = [];
    going = [...going, ...batch];
    try {
      const r = await api.deletePictures(batch.map((p) => ({ name: p.name, id: p.id })), owner);
      if (r.missing?.length) toast("Some were already gone.", "info");
    } catch (e: any) {
      toast(e.message || "Could not delete them.", "err");
    }
    await list.refresh({ force: true }).catch(() => {});
    going = going.filter((g) => !batch.includes(g));
  }
  // Leaving the page is the undo running out: what is waiting goes now.
  onDestroy(() => {
    if (leaving.length) commit();
  });

  const missing = $derived(pics.filter((p) => !p.description).length);
  /** Longer than a caption needs to be (LONG_DESCRIPTION in app/utils/pictures.py). */
  const LONG_DESC = 320;
  const longOnes = $derived(pics.filter((p) => p.description.trim().length > LONG_DESC).length);
  let longHidden = $state((() => {
    try { return localStorage.getItem("pictures.longHidden") === "1"; } catch { return false; }
  })());
  function hideLong() {
    longHidden = true;
    try { localStorage.setItem("pictures.longHidden", "1"); } catch {}
  }
  async function shortenLong() {
    queueing = true;
    try {
      const r = await api.describeMissing({ long: true }, who);
      if (r.queued) {
        toast(`Describing ${r.queued} again, shorter.`, "ok");
        watchDescribe();
      } else {
        toast("Nothing to shorten.", "info");
      }
    } catch (e: any) {
      toast(e.message, "err");
    }
    queueing = false;
  }
  const dirty = $derived(editing ? editDesc.trim() !== editing.description.trim() : false);
  const editWords = $derived(editDesc.trim() ? editDesc.trim().split(/\s+/).length : 0);

  onMount(() => {
    gallery.refresh({ maxAge: 10000 });
    personasRes.refresh({ maxAge: 15_000 });
    loadLooks();
    // Picks up a run already in progress, which is exactly the case that used
    // to show an empty page while the server was still working.
    watchDescribe();
  });

  const load = () => gallery.refresh({ force: true });

  // Blurred each time the tab is opened, while the preference is on. Showing
  // them lasts until you leave; the preference is what decides next time.
  let shown = $state(!get(picturesBlur));

  /**
   * Ctrl+V anywhere on the page adds the pictures on the clipboard, as a drop
   * does: a screenshot, or an image copied in a browser. Pasting into a box
   * (a description being edited) still pastes its text there. A clipboard
   * picture has no name of its own ("image.png" every time), so it is given
   * one from the time it was pasted.
   */
  let pasted = $state(false);
  function onPaste(e: ClipboardEvent) {
    const items = Array.from(e.clipboardData?.items ?? []);
    const images = items.filter((i) => i.kind === "file" && (i.type.startsWith("image/") || i.type.startsWith("video/")))
      .map((i) => i.getAsFile()).filter((f): f is File => !!f);
    if (!images.length) return;
    const el = e.target as HTMLElement | null;
    const inBox = !!el?.closest?.("input, textarea, [contenteditable='true']");
    if (inBox && items.some((i) => i.kind === "string" && i.type === "text/plain")) return;
    e.preventDefault();
    const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "");
    const named = images.map((f, i) => {
      const ext = (f.type.split("/")[1] || "png").replace("jpeg", "jpg").replace(/[^a-z0-9]/g, "");
      return new File([f], `pasted-${stamp}${images.length > 1 ? `-${i + 1}` : ""}.${ext}`, { type: f.type });
    });
    pasted = true;
    setTimeout(() => (pasted = false), 700);
    uploadFiles(named);
  }

  // The files go up from lib/pictures.ts, whose count outlives this page: leaving the tab and coming back used to
  // show an idle drop zone while pictures were still going in.
  function uploadFiles(files: FileList | File[] | null) {
    if (!files || files.length === 0) return;
    addPictures(Array.from(files), () => load(), who);
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
      const r = await api.describeMissing({}, who);
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
    busy[keyOf(p)] = true;
    try {
      const r = await api.analysePicture(p.name, p.id, who);
      if (r.ok) toast("Described.", "ok");
      else toast(r.reason || "Could not describe it.", "err");
    } catch (e: any) {
      toast(e.message, "err");
    }
    busy[keyOf(p)] = false;
    load();
  }

  /**
   * Put the actual image on the clipboard, not a link to it.
   *
   * The clipboard wants a PNG: Chromium refuses image/jpeg outright, so
   * anything that is not already a PNG is redrawn through a canvas first.
   * ClipboardItem also has to be constructed synchronously with a promise
   * inside it, rather than awaited first, or Safari treats the write as having
   * lost the user gesture that allowed it.
   */
  async function copyImage(p: Pic) {
    copying = p.name;
    try {
      await copyImageFrom(api.pictureUrl(p.name, p.id, who));
      toast("Copied the image.", "ok");
    } catch (e: any) {
      toast(e?.message || "Could not copy it", "err");
    }
    copying = "";
  }

  /** Right-click on a picture: the app's menu, with what can be done with it. */
  function openMenu(e: MouseEvent, p: Pic) {
    openMenuAt(e, [
      { title: p.name },
      !p.video && { label: "Copy image", icon: "copy", run: () => copyImage(p) },
      // Its real Save dialog in the desktop app: the download link this was did nothing there.
      { label: "Save as…", icon: "download",
        run: () => saveUrlAs(api.pictureUrl(p.name, p.id, who), p.name).then((w) => w && toast("Saved.", "ok")) },
      { label: "Edit description", icon: "edit", run: () => openEdit(p) },
      !p.moving && looksList.length > 0 && { label: "Filter…", icon: "palette", run: () => openLook([p]) },
      { label: selected.has(keyOf(p)) ? "Unselect" : "Select", icon: "check", run: () => toggleSelect(keyOf(p)) },
      "sep",
      { label: "Delete", icon: "trash", danger: true, run: () => removeLater([p]) },
    ]);
  }

  function toggleSelect(name: string) {
    // Reassigned rather than mutated: a Set is not deeply reactive.
    const next = new Set(selected);
    next.has(name) ? next.delete(name) : next.add(name);
    selected = next;
  }

  function selectAll() {
    selected = new Set(shownPics.map(keyOf));
  }

  function clearSelection() {
    selected = new Set();
  }

  function removeSelected() {
    removeLater(shownPics.filter((p) => selected.has(keyOf(p))));
    clearSelection();
  }

  function openEdit(p: Pic) {
    editing = p;
    editDesc = p.description;
  }

  async function saveDesc() {
    if (!editing) return;
    try {
      await api.setPictureDesc(editing.name, editDesc, editing.id, who);
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

{#if many}
  <!-- Whose pictures: each persona sends its own. -->
  <div class="pz-scope">
    <PersonaScope value={pid} label="Pictures of" onchange={switchTo} />
  </div>
{/if}

<!-- ── Drop zone ────────────────────────────────────────────────────────── -->
<svelte:window onpaste={onPaste} />

<div
  role="button"
  tabindex="0"
  aria-label="Drop pictures or videos here to add them"
  class="pz glass mb-4 flex flex-col items-center justify-center gap-2.5 rounded-2xl border border-dashed p-8 text-center transition-colors
    {dragOver || pasted ? 'border-accent bg-accent/[0.06]' : 'border-edge'}"
  class:is-adding={uploading}
  ondragover={(e) => {
    e.preventDefault();
    // Something held over it: an airy lift as it lights up, and a soft thunk where it is let go.
    if (!dragOver) play("hover");
    dragOver = true;
  }}
  ondragleave={() => (dragOver = false)}
  ondrop={(e) => {
    e.preventDefault();
    dragOver = false;
    play("drop");
    uploadFiles(e.dataTransfer?.files ?? null);
  }}
>
  <!-- Adding: a ring fills round a twinkling sparkle as they go in, the count rolls on with each, and a light runs
       along the foot of the zone, filled as far as they have got. One picture alone: the ring turns. -->
  <span class="pz-icon">
    {#if adding}
      <svg class="pz-ring" class:is-spin={ringSpin} viewBox="0 0 48 48" aria-hidden="true">
        <circle class="pz-track" cx="24" cy="24" r="21" />
        <circle class="pz-fill" cx="24" cy="24" r="21" pathLength="100"
                style="stroke-dashoffset: {ringSpin ? 72 : 100 - ringPct}" />
      </svg>
      <span class="pz-spark"><Icon name={adding.video ? "play" : "sparkle"} size={adding.video ? 15 : 18} /></span>
    {:else}
      <Icon name="upload" size={26} />
    {/if}
  </span>
  <div>
    <p class="text-[13px] text-ink">
      {#if adding?.video}
        <!-- A video: made an MP4 first, the percent rolling on, then watched to describe it. -->
        {#if adding.video.step === "convert"}
          Converting <b class="pz-who">{adding.name}</b>, {#key adding.video.percent}<b class="pz-n">{adding.video.percent}%</b>{/key}
        {:else}
          Watching <b class="pz-who">{adding.name}</b> to describe it
        {/if}
        {#if adding.total > 1}<span class="text-faint"> · {Math.min(adding.done + 1, adding.total)} of {adding.total}</span>{/if}
      {:else if adding && adding.total > 1}
        Adding {#key adding.done}<b class="pz-n">{Math.min(adding.done + 1, adding.total)}</b>{/key} of {adding.total}
      {:else if adding}
        Adding {adding.name}
      {:else if many && whoName}
        Drop pictures or videos for <b class="pz-who">{whoName}</b> here, or a zip, or paste one
      {:else}
        Drop pictures, videos or a zip here, or paste one
      {/if}
    </p>
    <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
      Any format works, it is converted for you. Videos become MP4, made
      smaller when too big to send. A zip is unpacked including its subfolders.
      Each one is described automatically, and that description is all the
      bot has to go on when it picks one.
    </p>
    <!-- Where the phone app cannot pick files, or this build cannot open HEIC. -->
    <div class="flex flex-col items-center">
      <NotHere feature="files_pick" variant="line" />
      <NotHere feature="heic" variant="line" />
    </div>
  </div>
  <label class="cursor-pointer rounded-lg bg-accent px-3.5 py-1.5 text-[13px] font-medium text-bg transition-colors hover:bg-accent/90"
         class:hidden={!!$notHere("files_pick")}>
    Browse files
    <input
      type="file"
      accept={`image/*,video/*,.zip,.heic,.heif,.avif,.bmp,.tif,.tiff,application/zip,${VIDEO_EXTS.join(",")}`}
      multiple
      class="hidden"
      onchange={(e) => uploadFiles((e.target as HTMLInputElement).files)}
    />
  </label>
  {#if looksList.length}
    <!-- The filter new ones get, picked right here rather than in Settings. -->
    <div class="pz-auto">
      <Icon name="palette" size={13} />
      <span>New pictures get</span>
      <Select size="sm" value={autoChoice} options={autoOptions} onchange={setAuto} />
    </div>
  {/if}
  {#if adding}<span class="pz-bar" style="--p: {addPct}%" aria-hidden="true"></span>{/if}
</div>

{#if describing}
  <!-- The archive is already on disk; this is only the descriptions catching
       up, so it reads as progress rather than as a blocking upload. -->
  <div class="glass mb-4 rounded-xl px-4 py-3">
    <div class="flex items-baseline justify-between gap-3">
      <span class="text-[12px] text-ink">
        Describing pictures, {describing.done} of {describing.total}
        <!-- Worth saying: with several keys this is genuinely running that many
             at once, so the rate is not what one key would manage. -->
        {#if (describing.workers ?? 1) > 1}
          <span class="text-muted">· {describing.workers} keys at once</span>
        {/if}
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

{#if lookJob}
  <div class="glass mb-4 rounded-xl px-4 py-3">
    <span class="text-[12px] text-ink">Adding filters, {lookJob.done} of {lookJob.total}</span>
    <div class="mt-2 h-1 overflow-hidden rounded-full bg-white/[0.06]">
      <div class="h-full rounded-full bg-accent transition-[width] duration-500"
           style="width: {Math.round((lookJob.done / Math.max(1, lookJob.total)) * 100)}%"></div>
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

{#if longOnes > 0 && missing === 0 && !longHidden && !loading && !describing}
  <!-- From before descriptions were captions: offered, never done on its own,
       since a long one may be one somebody wrote. -->
  <div class="pd-long">
    <span class="pd-long-mark"><Icon name="sparkle" size={13} /></span>
    <p class="min-w-0 flex-1">
      {longOnes} {longOnes === 1 ? "description is" : "descriptions are"} long. A line or two is all the bot needs.
    </p>
    <Button size="sm" kind="ghost" loading={queueing} onclick={shortenLong}>Shorten {longOnes === 1 ? "it" : "them"}</Button>
    <button type="button" class="pd-long-x" onclick={hideLong} title="Hide this" aria-label="Hide this">
      <Icon name="close" size={11} />
    </button>
  </div>
{/if}

{#if !loading && pics.length > 0}
  <!-- One bar for what can be done to the pictures: picking several, the filter new ones get, and keeping them out of
       sight. Buttons of one kind and size, and nothing written in faint grey beside them. -->
  <div class="pt-bar domino" use:domino={{ step: 45, level: 0.5, once: true }}>
    {#if selected.size}
      <span class="pt-count"><b>{selected.size}</b> selected</span>
      <button type="button" class="pt-btn" onclick={selectAll} disabled={selected.size === shownPics.length}>
        <Icon name="selectall" size={14} />All {shownPics.length}
      </button>
      <button type="button" class="pt-btn" onclick={clearSelection}><Icon name="close" size={12} />Clear</button>
      {#if looksList.length}
        <button type="button" class="pt-btn" onclick={() => openLook(shownPics.filter((p) => selected.has(keyOf(p))))}>
          <Icon name="palette" size={14} />Filter {selected.size}
        </button>
      {/if}
      <button type="button" class="pt-btn is-danger" onclick={removeSelected}><Icon name="trash" size={13} />Delete {selected.size}</button>
    {:else}
      <button type="button" class="pt-btn" onclick={selectAll} title="Then untick the ones to leave out">
        <Icon name="selectall" size={14} />Select all
      </button>
      {#if looksList.length}
        <button type="button" class="pt-auto" class:is-on={!!autoLook && autoLook.mode !== "off"} onclick={openLookSettings}
                title="The filter new pictures get. Opens its settings.">
          <Icon name="palette" size={14} /><span class="pt-auto-label">Auto filter</span>
          <span class="pt-auto-value">{autoValue}</span><Icon name="chevron" size={11} />
        </button>
      {/if}
    {/if}
    <!-- Privacy: nothing is on screen at full size until you ask for it. -->
    <span class="pt-right">
      <span class="pt-blur" title="Blur the pictures every time this tab is opened">
        <Toggle size="sm" checked={$picturesBlur} name="Blur when opened" onchange={(v) => picturesBlur.set(v)} />
        <span>Blur when opened</span>
      </span>
      <button type="button" class="pt-btn" class:is-on={shown} onclick={() => (shown = !shown)}>
        <Icon name={shown ? "eyeOff" : "eye"} size={14} />{shown ? "Hide pictures" : "Show pictures"}
      </button>
    </span>
  </div>
{/if}

{#if loading}
  <div class="glass h-40 animate-pulse"></div>
{:else if shownPics.length === 0}
  <Empty
    text="No pictures yet. These are the selfies and videos the bot sends when someone asks for one."
    icon="pictures"
  />
{:else}
  <!-- As the tab opens the cards pop in one after another, each a note up the scale (lib/domino.ts); after that a
       picture added grows in its own way. -->
  <div class="grid grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-3 domino" use:domino={{ step: 70, once: true }}>
    {#each shownPics as p (keyOf(p))}
      <!-- Going, it shrinks away and the others close up; brought back, it grows in again. -->
      <div class="pic-card" class:is-picking={selected.size > 0}
           animate:flip={{ duration: 360, easing: cubicOut }}
           in:scale={{ start: 0.92, duration: 260, easing: cubicOut }}
           out:scale={{ start: 0.88, duration: 220, easing: cubicOut }}>
      <Card pad={false}>
        <div class="relative" role="group" aria-label={p.name} oncontextmenu={(e) => openMenu(e, p)}>
          <!-- Sits over the thumbnail so ticking one never opens the viewer. -->
          <!-- A round check over the corner, there when the pointer is on the card, and for every card once one is picked. -->
          <label class="pc-select" class:is-on={selected.has(keyOf(p))} title="Select, to delete several at once">
            <input
              type="checkbox"
              class="sr-only"
              checked={selected.has(keyOf(p))}
              onchange={() => toggleSelect(keyOf(p))}
            />
            <span class="pc-check" aria-hidden="true"><Icon name="check" size={10} /></span>
            {selected.has(keyOf(p)) ? "Selected" : "Select"}
          </label>
        <button
          type="button"
          class="pic-frame relative block w-full overflow-hidden bg-black/25"
          class:is-veiled={!shown}
          class:is-picked={selected.has(keyOf(p))}
          onclick={() => (view = p)}
          onpointerenter={() => { if (p.video) live = keyOf(p); }}
          onpointerleave={() => { if (live === keyOf(p)) live = ""; }}
          title={p.video ? "Play it" : shown ? "View full size" : "Hover to peek, click to open"}
        >
          <!-- contain, not cover: these are the pictures the bot sends, so
               seeing the whole frame matters more than a tidy grid. The plate
               behind fills whatever the aspect ratio leaves over. -->
          <img
            src={thumbOf(p)}
            alt={p.name}
            data-pic={keyOf(p)}
            loading="lazy"
            class="pic-thumb h-56 w-full rounded-t-[var(--radius-card)] object-contain
                   {selected.has(keyOf(p)) ? 'opacity-70' : ''}"
          />
          {#if p.video}
            <!-- Under the pointer it plays, muted, from its still; a play mark and how long it is the rest of the time. -->
            {#if live === keyOf(p)}
              <video class="pic-thumb pc-live rounded-t-[var(--radius-card)]" src={api.pictureUrl(p.name, p.id, who)}
                     poster={thumbOf(p)} muted autoplay loop playsinline aria-hidden="true"></video>
            {/if}
            <span class="pc-play" class:is-live={live === keyOf(p)} aria-hidden="true"><Icon name="play" size={17} /></span>
            {#if p.duration}<span class="pc-dur">{clock(p.duration)}</span>{/if}
          {/if}
          {#if !shown}
            <span class="pic-veil-mark" aria-hidden="true"><Icon name="eye" size={18} /></span>
          {/if}
          {#if p.look}
            <span class="pc-look" title="Its filter">{lookName(p.look) || p.look} · {Math.round((p.strength ?? 0) * 100)}%</span>
          {/if}
        </button>
        </div>

        <div class="p-4">
          <div class="flex items-baseline justify-between gap-2">
            <span class="truncate font-mono text-[13px] text-ink">{p.name}</span>
            <span class="shrink-0 text-[11px] text-faint">{kb(p.size)}</span>
          </div>

          {#if p.description}
            {@const k = keyOf(p)}
            {@const opens = !!(over[k] || expanded[k])}
            <!-- Three lines, fading where there is more. A click opens it out in
                 place and another folds it back; selecting text does neither. -->
            <!-- svelte-ignore a11y_no_static_element_interactions, a11y_no_noninteractive_tabindex -->
            <div class="pd" class:is-open={expanded[k]} class:is-closing={closing[k]} class:is-over={over[k]} class:opens
                 role={opens ? "button" : undefined} tabindex={opens ? 0 : undefined}
                 aria-expanded={opens ? !!expanded[k] : undefined}
                 onclick={(e) => opens && toggleDesc(k, e.currentTarget)}
                 onkeydown={(e) => {
                   if (opens && (e.key === "Enter" || e.key === " ")) {
                     e.preventDefault();
                     toggleDesc(k, e.currentTarget);
                   }
                 }}>
              <span class="pd-mark"><Icon name="sparkle" size={14} /></span>
              <div class="min-w-0 flex-1">
                <div class="pd-text markdown" use:overflowing={{ text: p.description, set: (v) => (over[k] = v) }}>
                  {@html renderMarkdown(p.description)}
                </div>
                {#if opens}
                  <span class="pd-more">{expanded[k] && !closing[k] ? "Less" : "More"}<Icon name="chevron" size={10} /></span>
                {/if}
              </div>
            </div>
          {:else}
            <p class="mt-2.5 text-[13px] leading-relaxed text-warn">
              Not described, so the bot can never send it.
            </p>
          {/if}

          <!-- What can be done to it, as a row of its own under the words; Delete keeps to the far side. -->
          <div class="pc-actions">
            <button type="button" class="pc-btn" onclick={() => openEdit(p)}>
              <Icon name="edit" size={13} />{p.description ? "Edit" : "Write one"}
            </button>
            {#if looksList.length && !p.moving}
              <button type="button" class="pc-btn is-look" onclick={() => openLook([p])}>
                <Icon name="palette" size={13} />Filter
              </button>
            {/if}
            <button type="button" class="pc-btn is-describe" disabled={busy[keyOf(p)]} onclick={() => reanalyse(p)}>
              {#if busy[keyOf(p)]}<span class="pc-spin" aria-hidden="true"></span>{:else}<Icon name="sparkle" size={13} />{/if}
              {busy[keyOf(p)] ? "Describing" : p.description ? "Describe again" : "Describe it"}
            </button>
            <button type="button" class="pc-btn is-danger" onclick={() => removeLater([p])} aria-label="Delete {p.name}">
              <Icon name="trash" size={13} />Delete
            </button>
          </div>
        </div>
      </Card>
      </div>
    {/each}
  </div>
{/if}

<!-- A deleted picture's undo, along the bottom: Ctrl+Z works too. -->
<UndoBar what={leaving.length === 1 ? leaving[0].name : leaving.length ? `${leaving.length} pictures` : ""}
         verb="Deleted" images={leaving.map(thumbOf)} veil={!shown}
         ms={UNDO_MS} key={undoKey} onundo={undoRemove} />

<!-- ── Description editor ───────────────────────────────────────────────── -->
<Modal open={!!editing} title={editing?.name ?? ""} onclose={() => (editing = null)}>
  {#if editing}
    <div class="flex gap-3">
      <img
        src={thumbOf(editing)}
        alt=""
        class="h-24 w-24 shrink-0 rounded-lg object-cover ring-1 ring-edge"
      />
      <p class="text-[12px] leading-relaxed text-muted">
        {#if editing.video}
          What happens in the video, like a caption: who, what they do, where.
          The bot reads it when it sends the video. Markdown works.
        {:else}
          What is in the picture, like a caption: who, what they are wearing or
          doing, where. The bot reads it when it sends the picture. Markdown works.
        {/if}
      </p>
    </div>
    <textarea
      bind:value={editDesc}
      rows={7}
      class="mt-3 w-full rounded-lg border border-edge bg-black/40 p-3 text-[13px] leading-relaxed outline-none focus:border-accent/50"
      placeholder="A mirror selfie in a bathroom, black hoodie, phone in hand, evening light."
    ></textarea>
    <div class="mt-1.5 flex items-center justify-between text-[11px] text-faint">
      <span>
        {editWords} {editWords === 1 ? "word" : "words"}{#if editWords > 60}<span class="text-warn"> · a line or two is enough</span>{/if}
      </span>
      {#if dirty}<span class="text-warn">unsaved</span>{/if}
    </div>
    <div class="mt-4 flex justify-end gap-2">
      <Button kind="ghost" onclick={() => (editing = null)}>Cancel</Button>
      <Button onclick={saveDesc} disabled={!editDesc.trim()}>Save</Button>
    </div>
  {/if}
</Modal>

<!-- ── A look, for one picture or a selection ──────────────────────────── -->
<LookEditor bind:open={lookOpen} pics={lookPics} looks={looksList} persona={who}
            onapplied={() => { clearSelection(); load(); }} />

<!-- ── Full size ────────────────────────────────────────────────────────── -->
<!-- Grown out of its card, with what the bot reads under it; the arrows step through the rest. -->
<PictureViewer items={shownPics} current={view} src={(x) => api.pictureUrl(x.name, x.id, who)} thumb={thumbOf}
               originOf={(x) => document.querySelector<HTMLElement>(`img[data-pic="${CSS.escape(keyOf(x))}"]`)}
               onnav={(x) => (view = x)} onclose={() => (view = null)} onedit={(x) => { view = null; openEdit(x); }} />

<style>
  /* ── A card's own controls ───────────────────────────────────────── */
  .pc-select {
    position: absolute;
    left: 10px;
    top: 10px;
    z-index: 10;
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 5px 11px 5px 6px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 600;
    color: #fff;
    background: rgb(8 8 16 / 0.5);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.14), 0 6px 18px -10px rgb(0 0 0 / 0.9);
    backdrop-filter: blur(10px);
    cursor: pointer;
    opacity: 0;
    transform: translateY(-4px) scale(0.96);
    transition: opacity 0.18s ease, transform 0.28s var(--spring), background-color 0.2s ease, box-shadow 0.2s ease;
  }
  .pic-card:hover .pc-select, .pic-card.is-picking .pc-select, .pc-select.is-on, .pc-select:focus-within {
    opacity: 1;
    transform: none;
  }
  .pc-select:focus-within { outline: 2px solid var(--color-accent); outline-offset: 2px; }
  .pc-select:hover { background: rgb(8 8 16 / 0.7); }
  .pc-check {
    display: grid;
    width: 17px;
    height: 17px;
    place-items: center;
    border-radius: 999px;
    color: transparent;
    box-shadow: inset 0 0 0 1.5px rgb(255 255 255 / 0.6);
    transition: background-color 0.2s ease, box-shadow 0.2s ease, color 0.15s ease, transform 0.3s var(--spring);
  }
  .pc-select.is-on {
    background: color-mix(in srgb, var(--color-accent) 82%, rgb(0 0 0));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 60%, #fff 10%),
                0 8px 22px -10px var(--color-accent);
  }
  .pc-select.is-on .pc-check { color: var(--color-accent); background: #fff; box-shadow: none; transform: scale(1.06); }
  .pic-frame.is-picked { box-shadow: inset 0 0 0 2px var(--color-accent); }
  /* No pointer to hover with: the check is always there. */
  @media (hover: none) {
    .pc-select { opacity: 1; transform: none; }
  }

  .pc-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid color-mix(in srgb, var(--color-edge) 60%, transparent);
  }
  .pc-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 30px;
    padding: 0 12px 0 10px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 600;
    white-space: nowrap;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 85%, transparent);
    transition: color 0.15s ease, background-color 0.15s ease, box-shadow 0.18s ease, transform 0.22s var(--spring);
  }
  .pc-btn :global(svg) { color: var(--color-faint); transition: color 0.15s ease, transform 0.35s var(--spring); }
  .pc-btn:hover:not(:disabled) {
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.08);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 40%, transparent),
                0 8px 18px -12px color-mix(in srgb, var(--color-accent) 70%, transparent);
    transform: translateY(-1px);
  }
  .pc-btn:hover:not(:disabled) :global(svg) { color: var(--color-accent); }
  .pc-btn.is-describe:hover:not(:disabled) :global(svg) { transform: rotate(18deg) scale(1.12); }
  .pc-btn.is-look:hover:not(:disabled) :global(svg) { transform: rotate(-16deg) scale(1.12); }

  /* The look a picture has on it, over its top right corner. */
  .pc-look {
    position: absolute;
    right: 10px;
    top: 10px;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    color: #fff;
    background: rgb(8 8 16 / 0.5);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.14);
    backdrop-filter: blur(10px);
    pointer-events: none;
  }
  /* A video: a round play mark in the middle, and how long it is in the corner. Under the pointer it plays, the
     mark shrinking away as the picture starts to move. */
  .pc-live {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
    animation: pc-live-in 0.35s ease both;
  }
  @keyframes pc-live-in { from { opacity: 0; } }
  .pc-play {
    position: absolute;
    left: 50%;
    top: 50%;
    display: grid;
    width: 48px;
    height: 48px;
    place-items: center;
    padding-left: 3px;
    border-radius: 999px;
    color: #fff;
    background: rgb(8 8 16 / 0.42);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.22), 0 10px 30px -10px rgb(0 0 0 / 0.9);
    backdrop-filter: blur(10px);
    transform: translate(-50%, -50%);
    pointer-events: none;
    transition: opacity 0.25s ease, transform 0.4s var(--jelly);
  }
  .pic-frame:hover .pc-play:not(.is-live) { transform: translate(-50%, -50%) scale(1.1); }
  .pc-play.is-live { opacity: 0; transform: translate(-50%, -50%) scale(0.6); }
  .pc-dur {
    position: absolute;
    right: 10px;
    bottom: 10px;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: #fff;
    background: rgb(8 8 16 / 0.55);
    backdrop-filter: blur(8px);
    pointer-events: none;
  }
  :global(:root[data-motion="off"]) .pc-live { animation: none; }
  :global(:root[data-motion="off"]) .pc-play { transition: none; }
  /* ── The bar above the pictures ──────────────────────────────────── */
  .pt-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-bottom: 14px;
    padding: 7px;
    border-radius: 16px;
    background: rgb(255 255 255 / 0.025);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
  }
  .pt-btn, .pt-auto, .pt-count {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    height: 32px;
    padding: 0 13px 0 11px;
    border-radius: 11px;
    font-size: 12.5px;
    font-weight: 600;
    white-space: nowrap;
  }
  .pt-btn, .pt-auto {
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 85%, transparent);
    transition: color 0.15s ease, background-color 0.15s ease, box-shadow 0.18s ease, transform 0.22s var(--spring);
  }
  .pt-btn :global(svg), .pt-auto :global(svg) { color: var(--color-faint); transition: color 0.15s ease, transform 0.3s var(--spring); }
  .pt-btn:hover:not(:disabled), .pt-auto:hover {
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.08);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 40%, transparent);
    transform: translateY(-1px);
  }
  .pt-btn:hover:not(:disabled) :global(svg), .pt-auto:hover :global(svg) { color: var(--color-accent); }
  .pt-btn:active:not(:disabled), .pt-auto:active { transform: scale(0.96); }
  .pt-btn:disabled { opacity: 0.45; cursor: default; }
  .pt-btn.is-danger:hover:not(:disabled) { color: #fff; background: var(--color-bad); box-shadow: 0 8px 20px -10px var(--color-bad); }
  .pt-btn.is-danger:hover:not(:disabled) :global(svg) { color: #fff; }
  .pt-btn.is-on { color: var(--color-ink); }
  /* How many are picked, in the accent. */
  .pt-count {
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 45%, transparent);
  }
  .pt-count b { font-weight: 800; font-variant-numeric: tabular-nums; }
  /* The filter new pictures get: its name, and its setting as a tag. */
  /* The drop zone while pictures go in (lib/pictures.ts keeps the count, so it is still there after leaving the tab). */
  .pz { position: relative; overflow: hidden; }
  /* Whose pictures, above the drop zone; and their name in it, in their colour. */
  .pz-scope { display: flex; align-items: center; margin-bottom: 10px; }
  .pz-who { font-weight: 650; color: var(--color-ink); }
  .pz.is-adding {
    border-color: color-mix(in srgb, var(--color-accent) 50%, transparent);
    background: radial-gradient(80% 120% at 50% 0%, color-mix(in srgb, var(--color-accent) 9%, transparent), transparent 70%);
  }
  .pz-icon { position: relative; display: grid; place-items: center; min-width: 48px; min-height: 48px; color: var(--color-accent); }
  .pz-ring { position: absolute; inset: 0; width: 48px; height: 48px; transform: rotate(-90deg); }
  .pz-ring.is-spin { animation: pz-spin 1.1s linear infinite; }
  @keyframes pz-spin { from { transform: rotate(-90deg); } to { transform: rotate(270deg); } }
  .pz-track { fill: none; stroke: rgb(255 255 255 / 0.08); stroke-width: 3; }
  .pz-fill {
    fill: none;
    stroke: var(--color-accent);
    stroke-width: 3;
    stroke-linecap: round;
    stroke-dasharray: 100;
    transition: stroke-dashoffset 0.6s var(--spring);
    filter: drop-shadow(0 0 4px color-mix(in srgb, var(--color-accent) 70%, transparent));
  }
  .pz-spark { display: grid; animation: pz-twinkle 1.4s ease-in-out infinite; }
  @keyframes pz-twinkle { 50% { transform: scale(1.18) rotate(16deg); } }
  .pz-n { display: inline-block; font-weight: 700; font-variant-numeric: tabular-nums; animation: pz-roll 0.4s var(--jelly); }
  @keyframes pz-roll { from { opacity: 0; transform: translateY(55%); } }
  .pz-bar {
    position: absolute;
    left: 0;
    bottom: 0;
    width: var(--p);
    height: 2px;
    border-radius: 0 2px 2px 0;
    background: var(--color-accent);
    box-shadow: 0 0 10px var(--color-accent);
    transition: width 0.6s var(--spring);
  }
  .pz-bar::after {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg, transparent, rgb(255 255 255 / 0.85), transparent) no-repeat;
    background-size: 35% 100%;
    animation: pz-run 1.2s linear infinite;
  }
  @keyframes pz-run { from { background-position: -50% 0; } to { background-position: 150% 0; } }
  .pz-auto { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 8px; margin-top: 2px;
    font-size: 12px; color: var(--color-muted); }
  .pz-auto > :global(svg) { color: var(--color-faint); }
  :global(:root[data-motion="off"]) .pz-ring,
  :global(:root[data-motion="off"]) .pz-spark,
  :global(:root[data-motion="off"]) .pz-n,
  :global(:root[data-motion="off"]) .pz-bar::after { animation: none; }
  .pt-auto { padding-right: 9px; }
  .pt-auto-label { color: var(--color-muted); }
  .pt-auto-value {
    padding: 2px 9px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 700;
    color: var(--color-ink);
    background: rgb(255 255 255 / 0.08);
  }
  .pt-auto.is-on .pt-auto-value { color: var(--color-bg); background: var(--color-accent); }
  .pt-auto.is-on > :global(svg:first-child) { color: var(--color-accent); }
  .pt-auto:hover > :global(svg:last-child) { transform: translateX(2px); }
  .pt-right { display: flex; align-items: center; gap: 12px; margin-left: auto; }
  .pt-blur { display: none; align-items: center; gap: 9px; padding: 0 4px; font-size: 12.5px; font-weight: 600; color: var(--color-muted); }
  @media (min-width: 640px) {
    .pt-blur { display: inline-flex; }
  }
  :global(:root[data-motion="off"]) .pt-btn,
  :global(:root[data-motion="off"]) .pt-auto { transition: none; }
  .pc-btn:active:not(:disabled) { transform: scale(0.95); }
  .pc-btn:disabled { cursor: progress; color: var(--color-ink); }
  .pc-btn.is-danger { margin-left: auto; }
  .pc-btn.is-danger:hover:not(:disabled) {
    color: #fff;
    background: var(--color-bad);
    box-shadow: 0 8px 20px -10px var(--color-bad);
  }
  .pc-btn.is-danger:hover:not(:disabled) :global(svg) { color: #fff; }
  .pc-spin {
    width: 12px;
    height: 12px;
    border-radius: 999px;
    border: 1.5px solid color-mix(in srgb, var(--color-accent) 30%, transparent);
    border-top-color: var(--color-accent);
    animation: pc-spin 0.7s linear infinite;
  }
  @keyframes pc-spin { to { transform: rotate(360deg); } }
  :global(:root[data-motion="off"]) .pc-select,
  :global(:root[data-motion="off"]) .pc-btn { transition: none; }

  /* Blurred until hovered, while the tab is set to hide its pictures. A strong
     blur, scaled up so the soft edge does not leave a readable rim. Opening one
     (clicking) always shows it: that is asking to see it. */
  .pic-thumb {
    transition: filter 0.35s ease, transform 0.45s var(--spring);
  }
  .is-veiled .pic-thumb {
    filter: blur(22px) saturate(0.7);
    transform: scale(1.14);
  }
  .is-veiled:hover .pic-thumb,
  .is-veiled:focus-visible .pic-thumb {
    filter: none;
    transform: none;
  }
  .pic-veil-mark {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    color: rgb(255 255 255 / 0.85);
    pointer-events: none;
    transition: opacity 0.2s ease;
  }
  .is-veiled:hover .pic-veil-mark,
  .is-veiled:focus-visible .pic-veil-mark {
    opacity: 0;
  }
  :global(:root[data-motion="off"]) .pic-thumb {
    transition: none;
  }

  /* ── A description ───────────────────────────────────────────────────── */
  .pd {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    margin: 8px -8px 0;
    padding: 6px 8px;
    border-radius: 12px;
    outline: none;
    transition: background-color 0.2s var(--swift);
  }
  .pd.opens { cursor: pointer; }
  .pd.opens:hover { background: rgb(255 255 255 / 0.035); }
  .pd:focus-visible { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 55%, transparent); }
  .pd-mark {
    display: grid;
    margin-top: 3px;
    flex-shrink: 0;
    color: color-mix(in srgb, var(--color-accent) 70%, transparent);
    transition: transform 0.55s var(--jelly), color 0.2s ease;
  }
  /* A twinkle as it opens. */
  .pd.is-open:not(.is-closing) .pd-mark { transform: rotate(72deg) scale(1.12); color: var(--color-accent); }
  .pd-text {
    max-height: 4.8em;
    overflow: hidden;
    font-size: 13px;
    line-height: 1.6;
    color: color-mix(in srgb, var(--color-ink) 86%, transparent);
    overflow-wrap: anywhere;
  }
  .pd-text :global(.md-p) { margin-bottom: 0.45em; }
  .pd.is-open .pd-text { max-height: none; }
  /* Where there is more, the last line fades out. */
  .pd.is-over:not(.is-open) .pd-text,
  .pd.is-closing .pd-text {
    -webkit-mask-image: linear-gradient(180deg, #000 40%, transparent 98%);
    mask-image: linear-gradient(180deg, #000 40%, transparent 98%);
  }
  .pd-more {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    margin-top: 3px;
    font-size: 11px;
    font-weight: 600;
    color: var(--color-faint);
    transition: color 0.15s ease;
  }
  .pd.opens:hover .pd-more { color: var(--color-accent); }
  .pd-more :global(svg) { transform: rotate(90deg); transition: transform 0.45s var(--jelly); }
  .pd.is-open:not(.is-closing) .pd-more :global(svg) { transform: rotate(-90deg); }

  /* Long ones from before: offered a shorter description. */
  .pd-long {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 16px;
    padding: 6px 6px 6px 12px;
    border-radius: 12px;
    font-size: 12px;
    color: var(--color-muted);
    background: color-mix(in srgb, var(--color-accent) 6%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 16%, transparent);
  }
  .pd-long-mark { display: grid; flex-shrink: 0; color: var(--color-accent); }
  .pd-long-x {
    display: grid;
    width: 26px;
    height: 26px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 8px;
    color: var(--color-faint);
  }
  .pd-long-x:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.06); }

  :global(:root[data-motion="off"]) .pd-mark,
  :global(:root[data-motion="off"]) .pd-more :global(svg) { transition: none; }
</style>
