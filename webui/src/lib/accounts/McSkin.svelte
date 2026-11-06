<script lang="ts">
  /**
   * A premium Minecraft account's skin, from its card's edit window (app/platforms/minecraft/skin_change.py): a
   * picture put on it, classic or slim arms, or its skin taken off so it wears the game's default. Minecraft keeps a
   * premium account's skin itself, so it is the same on every server; an offline account has none to change.
   *
   * A picture chosen is checked here first, as Minecraft will check it (a PNG, 64 by 64, or the old 64 by 32), and
   * shown standing as it will look, before anything is sent.
   */
  import { onMount } from "svelte";
  import { fade } from "svelte/transition";
  import Segmented from "../components/Segmented.svelte";
  import Button from "../components/Button.svelte";
  import Icon from "../components/Icon.svelte";
  import { api } from "../api";
  import { toast } from "../stores";
  import { play } from "../uisound";

  let { index }: { index: number } = $props();

  let picture = $state("");
  let arms = $state<"classic" | "slim">("classic");
  let had = $state<"classic" | "slim">("classic");
  let own = $state(false);
  let chosen = $state<File | null>(null);
  let problem = $state("");
  let busy = $state<"" | "set" | "reset">("");
  let canvas: HTMLCanvasElement | null = $state(null);
  let fileInput: HTMLInputElement | null = $state(null);
  let img: HTMLImageElement | null = null;

  async function load() {
    try {
      const r = await api.minecraftSkin(index);
      picture = r.picture || "";
      had = arms = r.slim ? "slim" : "classic";
      own = r.source === "mojang";
    } catch {
      /* the card's picture stays as it was */
    }
  }
  onMount(load);

  const changed = $derived(!!chosen || (own && arms !== had));

  function loadImage(url: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = () => reject(new Error("not a picture"));
      i.src = url;
    });
  }

  /** A slim skin leaves its arms' last two columns empty: the way the game's own skin tools tell them apart. */
  function looksSlim(i: HTMLImageElement): boolean {
    if (i.height !== 64) return false;
    const c = document.createElement("canvas");
    c.width = 64;
    c.height = 64;
    const g = c.getContext("2d");
    if (!g) return false;
    g.drawImage(i, 0, 0);
    const px = g.getImageData(54, 20, 2, 12).data;
    for (let k = 3; k < px.length; k += 4) if (px[k] !== 0) return false;
    return true;
  }

  async function pick(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const f = input.files?.[0];
    input.value = "";
    if (!f) return;
    problem = "";
    const url = URL.createObjectURL(f);
    try {
      const i = await loadImage(url);
      if (i.width !== 64 || (i.height !== 64 && i.height !== 32)) {
        problem = `A skin is 64 by 64 pixels. That one is ${i.width} by ${i.height}.`;
        play("err");
        return;
      }
      img = i;
      chosen = f;
      arms = looksSlim(i) ? "slim" : "classic";
      play("pluck");
    } catch {
      problem = "That is not a picture Minecraft can use.";
      play("err");
    } finally {
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  }

  // The chosen skin, standing, front on: each part's front square, its outer layer over it, at six to a pixel.
  $effect(() => {
    const c = canvas;
    const slim = arms === "slim";
    if (!c || !chosen || !img) return;
    const g = c.getContext("2d");
    if (!g) return;
    const S = 6;
    g.clearRect(0, 0, c.width, c.height);
    g.imageSmoothingEnabled = false;
    const legacy = img.height === 32;
    const w = slim ? 3 : 4;
    const part = (sx: number, sy: number, sw: number, sh: number, dx: number, dy: number, flip = false) => {
      if (!img) return;
      g.save();
      if (flip) {
        g.translate((dx + sw) * S, dy * S);
        g.scale(-1, 1);
        g.drawImage(img, sx, sy, sw, sh, 0, 0, sw * S, sh * S);
      } else {
        g.drawImage(img, sx, sy, sw, sh, dx * S, dy * S, sw * S, sh * S);
      }
      g.restore();
    };
    // Its right side is on the left as it faces you.
    part(8, 8, 8, 8, 4, 0);                                  // head
    part(20, 20, 8, 12, 4, 8);                               // body
    part(44, 20, w, 12, 4 - w, 8);                           // right arm
    part(4, 20, 4, 12, 4, 20);                               // right leg
    if (legacy) {
      part(44, 20, w, 12, 12, 8, true);                      // the old skins have one of each, mirrored
      part(4, 20, 4, 12, 8, 20, true);
    } else {
      part(36, 52, w, 12, 12, 8);                            // left arm
      part(20, 52, 4, 12, 8, 20);                            // left leg
      part(20, 36, 8, 12, 4, 8);                             // jacket
      part(44, 36, w, 12, 4 - w, 8);                         // sleeves
      part(52, 52, w, 12, 12, 8);
      part(4, 36, 4, 12, 4, 20);                             // trousers
      part(4, 52, 4, 12, 8, 20);
    }
    part(40, 8, 8, 8, 4, 0);                                 // hat
  });

  async function apply() {
    if (!changed || busy) return;
    busy = "set";
    problem = "";
    try {
      const r = await api.minecraftSkinSet(index, chosen, arms === "slim");
      if (r?.ok) {
        chosen = null;
        img = null;
        await load();
        play("done");
        toast("Skin changed. It shows in the game the next time it joins.", "ok");
      } else {
        problem = r?.reason || "Minecraft did not take it.";
        play("err");
      }
    } catch (e: any) {
      problem = e?.message || "Minecraft did not take it.";
      play("err");
    } finally {
      busy = "";
    }
  }

  async function reset() {
    if (busy) return;
    busy = "reset";
    problem = "";
    try {
      const r = await api.minecraftSkinReset(index);
      if (r?.ok) {
        chosen = null;
        img = null;
        await load();
        play("undo");
        toast("Its skin is the game's default again.", "ok");
      } else {
        problem = r?.reason || "Minecraft did not take it off.";
        play("err");
      }
    } catch (e: any) {
      problem = e?.message || "Minecraft did not take it off.";
      play("err");
    } finally {
      busy = "";
    }
  }
</script>

<div class="mk">
  <div class="mk-stand" class:is-new={!!chosen}>
    {#if chosen}
      <canvas bind:this={canvas} width="96" height="192" aria-label="The skin chosen" in:fade={{ duration: 160 }}></canvas>
    {:else if picture}
      <img src={picture} alt="Its skin" in:fade={{ duration: 160 }} />
    {:else}
      <Icon name="minecraft" size={26} />
    {/if}
  </div>
  <div class="mk-side">
    <span class="mk-label">Skin</span>
    <Segmented label="Arms" bind:value={arms} options={[
      { id: "classic", label: "Classic arms" },
      { id: "slim", label: "Slim arms" },
    ]} />
    <div class="mk-row">
      <Button size="sm" kind="ghost" onclick={() => { play("open"); fileInput?.click(); }}>
        <Icon name="upload" size={12} />{chosen ? "Another" : "Choose a skin"}
      </Button>
      {#if changed}
        <Button size="sm" onclick={apply} loading={busy === "set"} disabled={busy === "reset"}>
          {#if busy !== "set"}<Icon name="check" size={12} />{/if}Use it
        </Button>
      {/if}
    </div>
    {#if problem}
      <p class="mk-note is-bad" transition:fade={{ duration: 120 }}>{problem}</p>
    {:else}
      <p class="mk-note">A 64 by 64 PNG. It is the same on every server.</p>
    {/if}
    {#if own && !chosen}
      <button type="button" class="mk-link" onclick={reset} disabled={!!busy}>
        {busy === "reset" ? "Taking it off..." : "Back to the default skin"}
      </button>
    {/if}
  </div>
  <input bind:this={fileInput} type="file" accept="image/png" hidden onchange={pick} />
</div>

<style>
  .mk {
    display: flex; gap: 14px; align-items: center; border-radius: 14px; padding: 12px;
    background: rgb(255 255 255 / 0.03);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-edge) 70%, transparent);
  }
  .mk-stand {
    position: relative; display: grid; width: 84px; height: 132px; flex-shrink: 0; place-items: center; overflow: hidden;
    border-radius: 12px; color: var(--color-faint);
    background:
      radial-gradient(80% 60% at 50% 30%, color-mix(in srgb, #7cbd4a 22%, transparent), transparent 70%),
      rgb(255 255 255 / 0.03);
    transition: box-shadow 0.2s ease;
  }
  .mk-stand.is-new { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 50%, transparent),
                                 0 0 22px -8px color-mix(in srgb, var(--color-accent) 60%, transparent); }
  .mk-stand img { max-width: 100%; max-height: 100%; object-fit: contain; filter: drop-shadow(0 8px 10px rgb(0 0 0 / 0.45)); }
  .mk-stand canvas { width: 60px; height: 120px; image-rendering: pixelated; filter: drop-shadow(0 8px 10px rgb(0 0 0 / 0.45)); }
  .mk-side { display: flex; min-width: 0; flex: 1; flex-direction: column; align-items: flex-start; gap: 8px; }
  .mk-label { font-size: 12px; font-weight: 500; color: var(--color-muted); }
  .mk-row { display: flex; gap: 6px; }
  .mk-note { font-size: 11px; color: var(--color-faint); }
  .mk-note.is-bad { color: var(--color-bad); }
  .mk-link { font-size: 11.5px; color: var(--color-muted); text-decoration: underline; text-underline-offset: 2px; }
  .mk-link:hover:not(:disabled) { color: var(--color-ink); }
  .mk-link:disabled { opacity: 0.5; }
</style>
