<script lang="ts">
  /**
   * What does not work on this device, said where it would be used.
   *
   * Nothing at all when the feature works: the page only speaks up about what
   * it cannot do here (lib/device.ts, from app/utils/compat.py). `block` is a
   * notice across a section, `line` sits under a setting, `chip` is a tag
   * beside a name with the reason on hover. `when` keeps it quiet until it
   * matters, say only once there is more than one account.
   */
  import Icon from "./Icon.svelte";
  import { notHere } from "../device";
  import { toast } from "../stores";

  let {
    feature,
    variant = "block",
    when = true,
  }: { feature: string; variant?: "block" | "line" | "chip"; when?: boolean } = $props();

  const problem = $derived(when ? $notHere(feature) : null);

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied.", "ok");
    } catch {
      toast(text, "info");
    }
  }
</script>

{#snippet fix()}
  {#if problem?.fix?.command}
    <button type="button" class="nh-cmd" onclick={() => copy(problem!.fix!.command!)} title="Copy">
      <code>{problem.fix.command}</code><Icon name="copy" size={11} />
    </button>
  {:else if problem?.fix?.route}
    <a class="nh-go" href="#/{problem.fix.route}">{problem.fix.label ?? "Fix it"}<Icon name="chevron" size={11} /></a>
  {/if}
{/snippet}

{#if problem}
  {#if variant === "chip"}
    <span class="nh-chip" title={problem.why}><Icon name="alert" size={11} />{problem.tag}</span>
  {:else if variant === "line"}
    <p class="nh-line">
      <span class="nh-line-icon"><Icon name="alert" size={12} /></span>
      <span>{problem.why}</span>
      {@render fix()}
    </p>
  {:else}
    <div class="nh pop" role="note">
      <span class="nh-icon"><Icon name="alert" size={15} /></span>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span class="text-[13px] font-semibold text-ink">{problem.label}</span>
          <span class="nh-tag">{problem.tag}</span>
        </div>
        <p class="mt-0.5 text-[12px] leading-relaxed text-muted">{problem.why}</p>
      </div>
      {@render fix()}
    </div>
  {/if}
{/if}

<style>
  /* Drawn like ErrorNote, in the warning colour: the app's one way of saying
     "not here" rather than "broken". */
  .nh {
    position: relative;
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 14px;
    padding: 11px 14px 11px 16px;
    border-radius: 16px;
    background:
      linear-gradient(90deg, color-mix(in srgb, var(--color-warn) 9%, transparent), transparent 70%),
      color-mix(in srgb, var(--color-card) 55%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-warn) 26%, var(--color-edge));
  }
  .nh::before {
    content: "";
    position: absolute;
    left: 0;
    top: 10px;
    bottom: 10px;
    width: 3px;
    border-radius: 0 3px 3px 0;
    background: var(--color-warn);
  }
  .nh-icon {
    display: grid;
    width: 30px;
    height: 30px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 10px;
    color: var(--color-warn);
    background: color-mix(in srgb, var(--color-warn) 14%, transparent);
  }

  .nh-tag {
    padding: 1px 7px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 600;
    color: var(--color-warn);
    background: color-mix(in srgb, var(--color-warn) 12%, transparent);
  }

  .nh-line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 6px;
    margin-top: 5px;
    font-size: 11.5px;
    line-height: 1.45;
    color: color-mix(in srgb, var(--color-warn) 80%, var(--color-ink));
  }
  .nh-line-icon { display: inline-flex; flex-shrink: 0; }

  .nh-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px 2px 6px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 600;
    white-space: nowrap;
    color: var(--color-warn);
    background: color-mix(in srgb, var(--color-warn) 12%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-warn) 28%, transparent);
    cursor: help;
  }

  .nh-cmd,
  .nh-go {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: 6px;
    padding: 4px 9px;
    border-radius: 9px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--color-ink);
    background: color-mix(in srgb, var(--color-warn) 13%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-warn) 30%, transparent);
    transition: background-color 0.15s ease;
  }
  .nh-cmd code { font-family: var(--font-mono, ui-monospace, monospace); font-size: 11px; }
  .nh-cmd:hover,
  .nh-go:hover { background: color-mix(in srgb, var(--color-warn) 22%, transparent); }
</style>
