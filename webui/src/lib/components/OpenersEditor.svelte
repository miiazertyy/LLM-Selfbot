<script lang="ts">
  /**
   * What the persona opens with when it answers hours late.
   *
   * This lived in Settings next to timeouts and thresholds, which is the wrong
   * shelf: how someone says "sorry, was busy" is their voice, not a preference
   * about the app - the same reason the moods and reactions are here.
   *
   * It used to be two fixed lists, English and French, chosen by looking for
   * French words in the message. Any language is a list now, and a language
   * with no list gets its opener written by the model in that language, so
   * Portuguese works without anyone adding Portuguese.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import { toast } from "../stores";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import ListEditor from "./ListEditor.svelte";

  /** Codes worth offering by name; anything else can still be typed. */
  const KNOWN: Record<string, string> = {
    en: "English", fr: "French", es: "Spanish", de: "German", it: "Italian",
    pt: "Portuguese", nl: "Dutch", pl: "Polish", ru: "Russian", tr: "Turkish",
    ar: "Arabic", he: "Hebrew", hi: "Hindi", id: "Indonesian", vi: "Vietnamese",
    th: "Thai", ja: "Japanese", ko: "Korean", zh: "Chinese",
  };

  let openers = $state<Record<string, string[]>>({});
  let style = $state("");
  let loading = $state(true);
  let saving = $state(false);
  let stored = $state("");
  let adding = $state("");

  const dirty = $derived(!loading && JSON.stringify({ openers, style }) !== stored);
  const langs = $derived(Object.keys(openers).sort());
  const name = (code: string) => KNOWN[code] ?? code.toUpperCase();

  onMount(load);

  async function load() {
    try {
      const cfg = await api.config();
      const lr = (cfg?.bot?.late_reply ?? {}) as any;
      // Read the old shape too, so a config written before this still opens.
      const legacy: Record<string, string[]> = {};
      for (const k of Object.keys(lr)) {
        if (k.startsWith("openers_") && Array.isArray(lr[k])) legacy[k.slice(8)] = lr[k];
      }
      openers = { ...(legacy), ...(lr.openers ?? {}) };
      style = lr.style ?? "";
      stored = JSON.stringify({ openers, style });
    } catch (e: any) {
      toast(e?.message || "Could not load the openers", "err");
    } finally {
      loading = false;
    }
  }

  function addLang() {
    const code = adding.trim().toLowerCase();
    if (!code) return;
    if (!openers[code]) openers = { ...openers, [code]: [] };
    adding = "";
  }

  function removeLang(code: string) {
    const next = { ...openers };
    delete next[code];
    openers = next;
  }

  function setList(code: string, list: string[]) {
    openers = { ...openers, [code]: list };
  }

  async function save() {
    saving = true;
    try {
      await api.configField("bot.late_reply.openers", openers);
      await api.configField("bot.late_reply.style", style);
      stored = JSON.stringify({ openers, style });
      toast("Saved.", "ok");
    } catch (e: any) {
      toast(e?.message || "Could not save", "err");
    }
    saving = false;
  }
</script>

{#if loading}
  <div class="h-24 animate-pulse rounded-xl bg-white/[0.03]"></div>
{:else}
  <p class="text-[11px] leading-relaxed text-faint">
    A language with no list here still gets an opener: the model writes one in
    that language, following the description below. So this is for pinning down
    exact wording, not for covering every language.
  </p>

  <label class="mt-3 block">
    <span class="mb-1 block text-[11px] text-muted">How it should sound, when it writes its own</span>
    <input
      bind:value={style}
      placeholder="casual and offhand, never formal"
      class="field w-full text-[12px]"
    />
  </label>

  <div class="mt-4 space-y-3">
    {#each langs as code (code)}
      <div class="rounded-xl border border-edge/70 bg-black/15 p-3">
        <div class="mb-2 flex items-center gap-2">
          <span class="text-[12px] font-medium text-ink">{name(code)}</span>
          <span class="font-mono text-[10px] text-faint">{code}</span>
          <button
            class="jelly ml-auto rounded-lg p-1 text-muted hover:bg-bad/10 hover:text-bad"
            title="Remove {name(code)}"
            aria-label="Remove {name(code)}"
            onclick={() => removeLang(code)}
          >
            <Icon name="trash" size={13} />
          </button>
        </div>
        <ListEditor
          value={openers[code]}
          onchange={(list) => setList(code, list)}
          placeholder="Add an opener"
        />
      </div>
    {:else}
      <p class="text-[12px] text-muted">
        No written openers. Every language is being written by the model.
      </p>
    {/each}
  </div>

  <div class="mt-3 flex flex-col gap-2 sm:flex-row">
    <input
      bind:value={adding}
      placeholder="Language code, e.g. es"
      onkeydown={(e) => e.key === "Enter" && (e.preventDefault(), addLang())}
      class="field min-w-0 flex-1 text-[12px]"
    />
    <Button kind="ghost" size="sm" onclick={addLang} disabled={!adding.trim()}>Add language</Button>
  </div>

  <div class="mt-4 flex items-center gap-2">
    <Button size="sm" onclick={save} loading={saving} disabled={!dirty}>
      {dirty ? "Save changes" : "Saved"}
    </Button>
    {#if dirty}
      <Button kind="ghost" size="sm" onclick={load}>Revert</Button>
    {/if}
  </div>
{/if}
