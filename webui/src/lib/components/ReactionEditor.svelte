<script lang="ts">
  /**
   * When the bot taps an emoji on a message instead of, or as well as, replying.
   *
   * This belongs with the persona rather than in Settings, for the same reason
   * the moods do: how often this character laughs at something without saying
   * anything is a trait, not a preference about the app.
   *
   * The two sliders do different jobs and the difference matters:
   *
   *   "How often it reacts" is the rate control. The model is asked to react
   *   only when a human would, and it turns out that from inside a single reply
   *   there is always some reason to, so it reached for one nearly every time.
   *   It picks the emoji; this decides whether to use it.
   *
   *   "Reacting instead of replying" caps the rarer thing: answering with only
   *   an emoji and no words.
   */
  import { onMount } from "svelte";
  import { api } from "../api";
  import { toast } from "../stores";
  import Button from "./Button.svelte";
  import Toggle from "./Toggle.svelte";
  import EmojiPicker from "./EmojiPicker.svelte";
  import { springValue } from "../spring";

  let enabled = $state(true);
  let chance = $state(0.3);
  let onlyRatio = $state(0.1);
  let emojis = $state<string[]>([]);
  let draft = $state("");
  let picking = $state(false);
  let loading = $state(true);
  let saving = $state(false);
  let stored = $state("");

  const dirty = $derived(
    !loading && JSON.stringify({ enabled, chance, onlyRatio, emojis }) !== stored,
  );

  /**
   * The set the app ships with, so "put it back" is possible without knowing
   * what it was. Kept in step with DEFAULT_REACTION_EMOJI in behavior.py.
   */
  const DEFAULTS = [
    "😂", "🤣", "😭", "💀", "😅", "😆", "😊", "🥹", "😍", "😳",
    "🤔", "👍", "❤️", "🔥", "🙏", "😎", "🥲", "😢", "😤", "🫡",
    "🙂", "🫠", "🤝", "👀", "🙄", "😴", "🤷", "🫶", "😐", "🥰",
  ];
  const MAX = 40;

  /**
   * Pull emoji out of whatever was typed or pasted.
   *
   * People paste "😭 💀", "😭,💀" and "😭💀" interchangeably. Splitting on
   * whitespace alone loses the third, and splitting on characters breaks every
   * emoji made of more than one code point, which is most of the interesting
   * ones: flags, skin tones, and anything with a variation selector. Intl's
   * segmenter knows where the boundaries actually are.
   */
  function parseEmoji(text: string): string[] {
    const cleaned = text.replace(/[,\s]+/g, "");
    if (!cleaned) return [];
    try {
      const seg = new Intl.Segmenter(undefined, { granularity: "grapheme" });
      return [...seg.segment(cleaned)].map((s) => s.segment).filter(Boolean);
    } catch {
      return [...cleaned];
    }
  }

  /**
   * Add or remove one emoji from the set.
   *
   * The picker is the way in now. Pasting is still supported through the same
   * path, because an emoji copied from somewhere else is a perfectly reasonable
   * thing to want and the picker only offers what Unicode ships.
   */
  function toggleEmoji(e: string) {
    if (emojis.includes(e)) {
      emojis = emojis.filter((x) => x !== e);
    } else if (emojis.length < MAX) {
      emojis = [...emojis, e];
    } else {
      toast(`That is the limit of ${MAX}. Remove one first.`, "err");
    }
  }

  function addDraft() {
    const found = parseEmoji(draft);
    if (!found.length) return;
    const next = [...emojis];
    for (const e of found) {
      if (!next.includes(e) && next.length < MAX) next.push(e);
    }
    emojis = next;
    draft = "";
  }

  const remove = (e: string) => (emojis = emojis.filter((x) => x !== e));

  /** Plain words for a number, because 0.3 does not mean anything on its own. */
  const rateWord = $derived(
    chance <= 0 ? "never" :
    chance < 0.15 ? "hardly ever" :
    chance < 0.35 ? "now and then" :
    chance < 0.6 ? "fairly often" :
    chance < 0.9 ? "most of the time" : "whenever it wants to",
  );

  const onlyWord = $derived(
    onlyRatio <= 0 ? "never, it always says something" :
    onlyRatio < 0.12 ? "very rarely" :
    onlyRatio < 0.3 ? "occasionally" : "often",
  );

  onMount(load);

  async function load() {
    try {
      const cfg = await api.config();
      const r = (cfg?.bot?.reactions ?? {}) as any;
      enabled = r.enabled !== false;
      // Absent from a config file seeded before this setting existed, so the
      // fallbacks here have to match what the runner uses.
      chance = typeof r.chance === "number" ? r.chance : 0.3;
      onlyRatio = typeof r.react_only_max_ratio === "number" ? r.react_only_max_ratio : 0.1;
      emojis = Array.isArray(r.emojis) && r.emojis.length ? r.emojis.slice() : DEFAULTS.slice();
      stored = JSON.stringify({ enabled, chance, onlyRatio, emojis });
    } catch (e: any) {
      toast(e?.message || "Could not load the reaction settings", "err");
    } finally {
      loading = false;
    }
  }

  async function save() {
    if (enabled && !emojis.length) {
      toast("Add at least one emoji, or turn reactions off.", "err");
      return;
    }
    saving = true;
    try {
      await api.configField("bot.reactions.enabled", enabled);
      await api.configField("bot.reactions.chance", chance);
      await api.configField("bot.reactions.react_only_max_ratio", onlyRatio);
      await api.configField("bot.reactions.emojis", emojis);
      stored = JSON.stringify({ enabled, chance, onlyRatio, emojis });
      toast("Reactions saved.", "ok");
    } catch (e: any) {
      toast(e?.message || "Could not save", "err");
    }
    saving = false;
  }

  const pct = (v: number) => `${Math.round(Math.max(0, Math.min(1, v)) * 100)}%`;
</script>

{#if loading}
  <div class="space-y-2">
    {#each Array(3) as _}<div class="h-11 animate-pulse rounded-lg bg-white/[0.03]"></div>{/each}
  </div>
{:else}
  <div class="divide-y divide-edge/60">
    <div class="flex items-center gap-4 pb-3">
      <div class="min-w-0 flex-1">
        <div class="text-[13px] text-ink">React with emoji</div>
        <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
          Let it tap an emoji on a message when the moment calls for one. Off
          means it only ever replies with words.
        </p>
      </div>
      <Toggle checked={enabled} onchange={(v) => (enabled = v)} />
    </div>

    <div class="py-3 {enabled ? '' : 'pointer-events-none opacity-40'}">
      <div class="flex flex-col gap-2 sm:flex-row sm:items-start sm:gap-4">
        <div class="min-w-0 sm:flex-1">
          <div class="text-[13px] text-ink">How often it reacts</div>
          <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
            It reacts <span class="text-ink/80">{rateWord}</span>. The AI asks
            for a reaction on almost every reply, so this is what keeps it
            occasional rather than constant.
          </p>
        </div>
        <div class="flex items-center gap-2 sm:shrink-0">
          <input
            type="range"
            min="0" max="1" step="0.05"
            value={chance}
            oninput={(e) => (chance = parseFloat((e.target as HTMLInputElement).value))}
            style="--fill: {pct(chance)}"
            class="slider min-w-0 flex-1 sm:w-44 sm:flex-none"
            use:springValue
          />
          <span class="slider-value w-10 shrink-0 text-right font-mono text-[12px] text-ink">
            {pct(chance)}
          </span>
        </div>
      </div>
    </div>

    <div class="py-3 {enabled ? '' : 'pointer-events-none opacity-40'}">
      <div class="flex flex-col gap-2 sm:flex-row sm:items-start sm:gap-4">
        <div class="min-w-0 sm:flex-1">
          <div class="text-[13px] text-ink">Reacting instead of replying</div>
          <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
            Answering with only an emoji and no words, the way you laugh
            something off. Happens <span class="text-ink/80">{onlyWord}</span>.
            Never used on a question.
          </p>
        </div>
        <div class="flex items-center gap-2 sm:shrink-0">
          <input
            type="range"
            min="0" max="0.5" step="0.02"
            value={onlyRatio}
            oninput={(e) => (onlyRatio = parseFloat((e.target as HTMLInputElement).value))}
            style="--fill: {pct(onlyRatio * 2)}"
            class="slider min-w-0 flex-1 sm:w-44 sm:flex-none"
            use:springValue
          />
          <span class="slider-value w-10 shrink-0 text-right font-mono text-[12px] text-ink">
            {pct(onlyRatio)}
          </span>
        </div>
      </div>
    </div>
    <!-- Which emoji, not just how often. A fixed set made every persona react
         identically, which is the kind of tell the rest of this app works to
         avoid. -->
    <div class="py-3 {enabled ? '' : 'pointer-events-none opacity-40'}">
      <div class="text-[13px] text-ink">The emoji it uses</div>
      <p class="mt-0.5 text-[11px] leading-relaxed text-faint">
        The AI picks from this list and nothing else, so anything it invents is
        ignored rather than sent and rejected by Discord. Click one below to
        remove it, or browse the full set to add more.
      </p>

      <div class="mt-2.5 flex flex-wrap gap-1.5">
        {#each emojis as e (e)}
          <button
            onclick={() => remove(e)}
            title="Remove {e}"
            aria-label="Remove {e}"
            class="jelly group relative rounded-lg border border-edge bg-white/[0.03] px-2 py-1
                   text-[16px] leading-none hover:border-bad/50 hover:bg-bad/10"
          >
            {e}
          </button>
        {:else}
          <p class="text-[11px] text-warn">
            Nothing left. Add at least one, or turn reactions off above.
          </p>
        {/each}
      </div>

      <div class="mt-2.5 flex flex-wrap gap-2">
        <Button kind="ghost" size="sm" onclick={() => (picking = !picking)}>
          {picking ? "Done picking" : "Browse emoji"}
        </Button>
        <Button
          kind="ghost"
          size="sm"
          onclick={() => (emojis = DEFAULTS.slice())}
          disabled={JSON.stringify(emojis) === JSON.stringify(DEFAULTS)}
        >Reset</Button>
      </div>

      {#if picking}
        <div class="mt-2.5 space-y-2">
          <EmojiPicker chosen={emojis} full={emojis.length >= MAX} onpick={toggleEmoji} />
          <!-- The escape hatch. The picker carries what Unicode shipped when
               this was generated, so anything newer, or a sequence it does not
               list, still has a way in. -->
          <div class="flex flex-col gap-2 sm:flex-row">
            <input
              bind:value={draft}
              placeholder="Or paste emoji the list does not have"
              onkeydown={(e) => e.key === "Enter" && (e.preventDefault(), addDraft())}
              class="field text-[14px]"
            />
            <Button kind="ghost" size="sm" onclick={addDraft} disabled={!draft.trim()}>Add</Button>
          </div>
        </div>
      {/if}
      <p class="mt-1.5 text-[10px] text-faint/70">
        {emojis.length} of {MAX}. They are sent to the AI on every reply, so a
        long list costs a little of every request.
      </p>
    </div>
  </div>

  <div class="mt-4 flex items-center gap-2">
    <Button size="sm" onclick={save} loading={saving} disabled={!dirty}>
      {dirty ? "Save changes" : "Saved"}
    </Button>
    {#if dirty}
      <Button kind="ghost" size="sm" onclick={() => { loading = true; load(); }}>Revert</Button>
    {/if}
  </div>
{/if}
