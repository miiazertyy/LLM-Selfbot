<script lang="ts">
  /**
   * The raw config, in a real code editor.
   *
   * It was a plain text box in a small dialog: no colours, no line numbers,
   * no way to tell where the JSON broke until the server refused it. This is
   * CodeMirror, dressed in the app's colours: keys, strings, numbers and
   * literals each their own colour, line numbers, the active line lit,
   * brackets matched and foldable, search (Ctrl+F), and the JSON checked as
   * it is typed, the broken spot marked and named in the header. Format
   * tidies it without rounding the big owner ID (lib/jsontext.ts). Ctrl+S
   * saves, Escape closes, and leaving with changes asks first.
   *
   * Loaded only when it is opened (Settings imports it on demand), so the
   * editor costs the panel nothing until then.
   */
  import { onMount, untrack } from "svelte";
  import { EditorState } from "@codemirror/state";
  import {
    EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter,
    drawSelection, dropCursor, highlightSpecialChars, rectangularSelection,
  } from "@codemirror/view";
  import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
  import { HighlightStyle, syntaxHighlighting, bracketMatching, foldGutter, foldKeymap, indentOnInput } from "@codemirror/language";
  import { json, jsonParseLinter } from "@codemirror/lang-json";
  import { linter, lintGutter } from "@codemirror/lint";
  import { search, searchKeymap, highlightSelectionMatches } from "@codemirror/search";
  import { closeBrackets, closeBracketsKeymap } from "@codemirror/autocomplete";
  import { tags as t } from "@lezer/highlight";
  import Icon from "./Icon.svelte";
  import Button from "./Button.svelte";
  import { ask } from "../ask";
  import { toast } from "../stores";
  import { formatJson, jsonError } from "../jsontext";

  let { text, onsave, onclose }: {
    text: string;
    /** Save it; throws with the server's reason when it will not take it. */
    onsave: (text: string) => Promise<void>;
    onclose: () => void;
  } = $props();

  let host: HTMLElement | null = $state(null);
  let view: EditorView | null = null;
  // What the editor started from: it edits its own copy, and the prop is only
  // read once, as it opens.
  const opened = untrack(() => text);
  let current = $state(opened);
  let saved = $state(opened);
  let cursor = $state({ line: 1, col: 1 });
  let lines = $state(opened.split("\n").length);
  let saving = $state(false);
  let justSaved = $state(false);
  let shake = $state(0);
  const dirty = $derived(current !== saved);
  const problem = $derived(jsonError(current));

  // Each part of JSON its own colour, from the app's palette where it has one.
  const colours = HighlightStyle.define([
    { tag: t.propertyName, color: "color-mix(in srgb, var(--color-accent) 72%, #ffffff)", fontWeight: "500" },
    { tag: t.string, color: "#9fe0b4" },
    { tag: t.number, color: "#f6c27f" },
    { tag: t.bool, color: "#9fb8ff", fontWeight: "600" },
    { tag: t.null, color: "#c7a6ff", fontStyle: "italic" },
    { tag: [t.brace, t.squareBracket], color: "rgb(255 255 255 / 0.55)" },
    { tag: t.separator, color: "rgb(255 255 255 / 0.32)" },
  ]);

  const look = EditorView.theme({
    "&": { height: "100%", fontSize: "13px", backgroundColor: "transparent", color: "var(--color-ink)" },
    ".cm-scroller": {
      fontFamily: '"Cascadia Code", "JetBrains Mono", "Fira Code", Consolas, ui-monospace, monospace',
      lineHeight: "1.65",
    },
    ".cm-content": { padding: "14px 0 40vh", caretColor: "var(--color-accent)" },
    ".cm-line": { padding: "0 18px 0 6px" },
    ".cm-gutters": {
      backgroundColor: "rgb(0 0 0 / 0.18)",
      color: "var(--color-faint)",
      border: "none",
      borderRight: "1px solid rgb(255 255 255 / 0.05)",
    },
    ".cm-lineNumbers .cm-gutterElement": { padding: "0 10px 0 16px", minWidth: "3ch" },
    ".cm-activeLineGutter": { backgroundColor: "transparent", color: "var(--color-accent)" },
    ".cm-activeLine": { backgroundColor: "color-mix(in srgb, var(--color-accent) 7%, transparent)" },
    ".cm-cursor, .cm-dropCursor": { borderLeft: "2px solid var(--color-accent)" },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection": {
      backgroundColor: "color-mix(in srgb, var(--color-accent) 28%, transparent) !important",
    },
    ".cm-selectionMatch": { backgroundColor: "color-mix(in srgb, var(--color-accent-2) 18%, transparent)" },
    "&.cm-focused .cm-matchingBracket": {
      backgroundColor: "color-mix(in srgb, var(--color-accent) 22%, transparent)",
      outline: "1px solid color-mix(in srgb, var(--color-accent) 55%, transparent)",
      borderRadius: "3px",
    },
    ".cm-foldGutter .cm-gutterElement": { color: "var(--color-faint)", cursor: "pointer", padding: "0 4px" },
    ".cm-foldPlaceholder": {
      backgroundColor: "color-mix(in srgb, var(--color-accent) 16%, transparent)",
      border: "none", color: "var(--color-accent)", borderRadius: "6px", padding: "0 6px",
    },
    ".cm-lintRange-error": {
      backgroundImage: "none",
      textDecoration: "underline wavy var(--color-bad)",
      textUnderlineOffset: "3px",
    },
    ".cm-lint-marker": { width: "0.9em", height: "0.9em" },
    ".cm-tooltip": {
      backgroundColor: "var(--color-card)", border: "1px solid var(--color-edge)",
      borderRadius: "10px", color: "var(--color-ink)", boxShadow: "0 12px 30px -12px rgb(0 0 0 / 0.7)",
    },
    ".cm-diagnostic-error": { borderLeft: "3px solid var(--color-bad)" },
    ".cm-panels": { backgroundColor: "rgb(0 0 0 / 0.25)", color: "var(--color-ink)" },
    ".cm-panels-bottom": { borderTop: "1px solid var(--color-edge)" },
    ".cm-search": { padding: "8px 12px", gap: "6px", fontSize: "12.5px" },
    ".cm-search input, .cm-search button, .cm-search label": { fontSize: "12.5px" },
    ".cm-textfield": {
      backgroundColor: "rgb(0 0 0 / 0.3)", border: "1px solid var(--color-edge)", borderRadius: "8px",
      color: "var(--color-ink)", padding: "4px 8px",
    },
    ".cm-button": {
      backgroundImage: "none", backgroundColor: "rgb(255 255 255 / 0.06)", border: "1px solid var(--color-edge)",
      borderRadius: "8px", color: "var(--color-ink)", padding: "3px 10px",
    },
    ".cm-searchMatch": {
      backgroundColor: "color-mix(in srgb, var(--color-warn) 25%, transparent)",
      outline: "1px solid color-mix(in srgb, var(--color-warn) 45%, transparent)", borderRadius: "2px",
    },
    ".cm-searchMatch-selected": { backgroundColor: "color-mix(in srgb, var(--color-warn) 45%, transparent)" },
  }, { dark: true });

  onMount(() => {
    if (!host) return;
    view = new EditorView({
      parent: host,
      state: EditorState.create({
        doc: opened,
        extensions: [
          lineNumbers(),
          highlightActiveLineGutter(),
          foldGutter({ openText: "▾", closedText: "▸" }),
          highlightSpecialChars(),
          history(),
          drawSelection(),
          dropCursor(),
          indentOnInput(),
          bracketMatching(),
          closeBrackets(),
          rectangularSelection(),
          highlightActiveLine(),
          highlightSelectionMatches(),
          search({ top: false }),
          json(),
          linter(jsonParseLinter(), { delay: 250 }),
          lintGutter(),
          syntaxHighlighting(colours),
          look,
          EditorState.tabSize.of(2),
          keymap.of([
            { key: "Mod-s", preventDefault: true, run: () => (save(), true) },
            { key: "Shift-Alt-f", preventDefault: true, run: () => (format(), true) },
            ...closeBracketsKeymap, ...defaultKeymap, ...searchKeymap, ...historyKeymap, ...foldKeymap, indentWithTab,
          ]),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) {
              current = u.state.doc.toString();
              lines = u.state.doc.lines;
            }
            if (u.docChanged || u.selectionSet) {
              const head = u.state.selection.main.head;
              const line = u.state.doc.lineAt(head);
              cursor = { line: line.number, col: head - line.from + 1 };
            }
          }),
        ],
      }),
    });
    view.focus();
    return () => view?.destroy();
  });

  function format() {
    if (!view) return;
    const tidy = formatJson(current);
    if (tidy === null) {
      shake++;
      return;
    }
    if (tidy === current) return;
    const head = view.state.selection.main.head;
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: tidy },
                    selection: { anchor: Math.min(head, tidy.length) } });
    view.focus();
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(current);
      toast("Copied.", "ok");
    } catch {
      toast("Could not copy it.", "err");
    }
  }

  function toProblem() {
    if (!view || !problem) return;
    view.dispatch({ selection: { anchor: problem.pos }, scrollIntoView: true });
    view.focus();
  }

  async function save() {
    if (saving) return;
    if (problem) {
      shake++;
      toProblem();
      return;
    }
    saving = true;
    try {
      await onsave(current);
      saved = current;
      justSaved = true;
      setTimeout(() => onclose(), 650);
    } catch (e: any) {
      toast(e?.message || "Could not save it.", "err");
    } finally {
      saving = false;
    }
  }

  async function close() {
    if (dirty && !(await ask("Leave without saving?", {
      detail: "Your changes to the config will be lost.", yes: "Leave", no: "Keep editing", danger: true,
    }))) return;
    onclose();
  }

  // Escape closes, unless it is closing the editor's own search first.
  function onKey(e: KeyboardEvent) {
    if (e.key !== "Escape" || e.defaultPrevented) return;
    if (host?.querySelector(".cm-search")) return;
    e.preventDefault();
    close();
  }

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="re-back" use:portal role="dialog" aria-modal="true" aria-label="Raw config" tabindex="-1"
     onclick={(e) => e.target === e.currentTarget && close()} onkeydown={() => {}}>
  <div class="re glass floating" class:is-saved={justSaved}>
    <header class="re-head">
      <span class="re-icon"><Icon name="braces" size={17} /></span>
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <h3 class="text-[15px] font-semibold tracking-tight text-ink">Raw config</h3>
          {#if dirty}<span class="re-dirty" title="Changed, not saved">Edited</span>{/if}
        </div>
        <p class="truncate text-[11.5px] text-faint">Every setting, as JSON. Saved back to config.yaml.</p>
      </div>

      {#key shake}
        <!-- Three parts, so a long message shortens itself with "…" (the whole
             of it on hover) instead of clipping the icon and the pill's edge. -->
        <button type="button" class="re-status" class:is-bad={!!problem} class:is-shake={shake > 0}
                onclick={toProblem} disabled={!problem}
                title={problem ? `Line ${problem.line}: ${problem.message}. Click to go there.` : "The JSON is valid"}>
          <span class="re-status-icon"><Icon name={problem ? "alert" : "check"} size={11} /></span>
          {#if problem}
            <span class="re-status-line">Line {problem.line}</span>
            <span class="re-status-text">{problem.message}</span>
          {:else}
            <span class="re-status-text">Valid JSON</span>
          {/if}
        </button>
      {/key}
      <button type="button" class="re-tool" onclick={format} disabled={!!problem} title="Tidy the indenting (Shift+Alt+F)">
        <Icon name="braces" size={13} />Format
      </button>
      <button type="button" class="re-tool" onclick={copy} title="Copy all of it">
        <Icon name="copy" size={13} />Copy
      </button>
      <button type="button" class="re-close" onclick={close} aria-label="Close"><Icon name="close" size={15} /></button>
    </header>

    <div class="re-body" bind:this={host}></div>

    <footer class="re-foot">
      <span class="re-keys">
        <span><kbd>Ctrl</kbd><kbd>S</kbd> save</span>
        <span><kbd>Ctrl</kbd><kbd>F</kbd> search</span>
        <span><kbd>Esc</kbd> close</span>
      </span>
      <span class="re-pos">Ln {cursor.line}, Col {cursor.col} · {lines} lines</span>
      <span class="ml-auto flex items-center gap-2">
        <Button kind="ghost" onclick={close}>Cancel</Button>
        <Button onclick={save} loading={saving} disabled={!!problem || (!dirty && !justSaved)}>
          {#if justSaved}<Icon name="check" size={13} />Saved{:else}Save{/if}
        </Button>
      </span>
    </footer>
  </div>
</div>

<style>
  .re-back {
    position: fixed;
    inset: 0;
    z-index: 60;
    display: grid;
    place-items: center;
    padding: 20px;
    background: rgb(0 0 0 / 0.62);
    backdrop-filter: blur(6px);
    animation: re-fade 0.2s var(--swift) both;
  }
  @keyframes re-fade { from { opacity: 0; } }
  .re {
    display: flex;
    width: min(1180px, 96vw);
    height: min(88vh, 940px);
    flex-direction: column;
    overflow: hidden;
    border-radius: 18px;
    box-shadow: 0 30px 80px -30px rgb(0 0 0 / 0.85), inset 0 0 0 1px rgb(255 255 255 / 0.06);
    animation: re-in 0.38s var(--spring) both;
    transition: box-shadow 0.4s var(--swift);
  }
  @keyframes re-in {
    from { opacity: 0; transform: translateY(14px) scale(0.975); }
  }
  /* Saved: the frame lights up green for a moment before it closes. */
  .re.is-saved {
    box-shadow: 0 30px 80px -30px rgb(0 0 0 / 0.85),
                inset 0 0 0 1.5px color-mix(in srgb, var(--color-good) 70%, transparent),
                0 0 40px -10px color-mix(in srgb, var(--color-good) 55%, transparent);
  }

  .re-head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 14px 12px 16px;
    border-bottom: 1px solid rgb(255 255 255 / 0.06);
  }
  .re-icon {
    display: grid;
    width: 34px;
    height: 34px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 10px;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 14%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 22%, transparent);
  }
  .re-dirty {
    padding: 1px 7px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 600;
    color: var(--color-warn);
    background: color-mix(in srgb, var(--color-warn) 13%, transparent);
    animation: re-pop 0.3s var(--jelly) both;
  }
  @keyframes re-pop { from { opacity: 0; transform: scale(0.6); } }

  .re-status {
    display: inline-flex;
    min-width: 0;
    max-width: min(46ch, 40vw);
    align-items: center;
    gap: 7px;
    padding: 4px 12px 4px 4px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 600;
    line-height: 1.3;
    white-space: nowrap;
    color: var(--color-good);
    background: color-mix(in srgb, var(--color-good) 11%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-good) 22%, transparent);
    transition: color 0.2s ease, background-color 0.2s ease;
  }
  .re-status:disabled { cursor: default; }
  .re-status-icon {
    display: grid;
    width: 20px;
    height: 20px;
    flex-shrink: 0;
    place-items: center;
    border-radius: 999px;
    background: color-mix(in srgb, currentColor 16%, transparent);
  }
  .re-status-line {
    flex-shrink: 0;
    padding: 1px 7px;
    border-radius: 999px;
    font-variant-numeric: tabular-nums;
    background: color-mix(in srgb, var(--color-bad) 22%, transparent);
  }
  .re-status-text {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    font-weight: 500;
  }
  .re-status.is-bad {
    color: color-mix(in srgb, var(--color-bad) 85%, #fff);
    background: color-mix(in srgb, var(--color-bad) 13%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-bad) 30%, transparent);
    cursor: pointer;
  }
  .re-status.is-shake { animation: re-shake 0.38s var(--swift); }
  @keyframes re-shake {
    20% { transform: translateX(-5px); }
    45% { transform: translateX(4px); }
    70% { transform: translateX(-2px); }
  }

  .re-tool {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 11px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 500;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.04);
    box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06);
    transition: background-color 0.15s ease, color 0.15s ease, transform 0.3s var(--jelly);
  }
  .re-tool:hover:not(:disabled) { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }
  .re-tool:active:not(:disabled) { transform: scale(0.94); }
  .re-tool:disabled { opacity: 0.4; cursor: default; }
  .re-close {
    display: grid;
    width: 32px;
    height: 32px;
    place-items: center;
    border-radius: 10px;
    color: var(--color-muted);
    transition: background-color 0.15s ease, color 0.15s ease;
  }
  .re-close:hover { color: var(--color-ink); background: rgb(255 255 255 / 0.08); }

  .re-body {
    min-height: 0;
    flex: 1;
    overflow: hidden;
    background: rgb(0 0 0 / 0.22);
    animation: re-text 0.5s var(--swift) 0.12s both;
  }
  @keyframes re-text { from { opacity: 0; transform: translateY(6px); } }

  .re-foot {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px 16px;
    padding: 10px 14px 10px 16px;
    border-top: 1px solid rgb(255 255 255 / 0.06);
    font-size: 11.5px;
    color: var(--color-faint);
  }
  .re-keys { display: flex; flex-wrap: wrap; gap: 12px; }
  .re-keys kbd {
    display: inline-block;
    margin-right: 3px;
    padding: 1px 5px;
    border-radius: 5px;
    font-family: inherit;
    font-size: 10.5px;
    color: var(--color-muted);
    background: rgb(255 255 255 / 0.06);
    box-shadow: inset 0 -1px 0 rgb(0 0 0 / 0.4);
  }
  .re-pos { font-variant-numeric: tabular-nums; }

  @media (max-width: 640px) {
    .re { height: 94vh; }
    .re-keys, .re-pos, .re-tool { display: none; }
    .re-back { padding: 8px; }
  }

  :global(:root[data-motion="off"]) .re,
  :global(:root[data-motion="off"]) .re-back,
  :global(:root[data-motion="off"]) .re-body,
  :global(:root[data-motion="off"]) .re-status { animation: none; }
</style>
