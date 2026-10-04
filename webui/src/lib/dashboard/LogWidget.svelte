<script lang="ts">
  /**
   * The Dashboard's live log, drawn the way the Logs page draws it: one row per
   * thing that happened (LogRow), with an icon for its kind, the account's own
   * name and picture, and a message that came in or went out quoted under the
   * line that introduced it, instead of the console's raw text.
   *
   * The newest lines are at whichever end the Logs page keeps them (its
   * "Newest first" switch), and followed as they arrive, unless you have
   * scrolled away to read something.
   */
  import { tick } from "svelte";
  import LogRow from "../components/LogRow.svelte";
  import { chatAccounts } from "../chats";
  import { foldRows, sourceInfo, type LogLine } from "../logrows";
  import { openMenuAt, copyText } from "../contextmenu";

  /** Right-click on a line: copy it, or open the whole log. */
  function lineMenu(e: MouseEvent, r: { time: string; source: string; text: string; more: string[] }) {
    const who = sourceInfo(r.source, $chatAccounts).name;
    openMenuAt(e, [
      { label: "Copy this entry", icon: "copy",
        run: () => copyText([`${r.time} [${who}] ${r.text}`, ...r.more.map((m) => `    ${m}`)].join("\n")) },
      r.text && { label: "Copy just the message", icon: "chats", run: () => copyText(r.text, "Copied the message.") },
      "sep",
      { label: "Open the log", icon: "logs", run: () => (location.hash = "/logs") },
    ]);
  }

  let { lines = [], filter = "all", tall = false }: { lines?: LogLine[]; filter?: string; tall?: boolean } = $props();

  const newestFirst = (() => {
    try {
      return localStorage.getItem("logs.newestFirst") === "1";
    } catch {
      return false;
    }
  })();

  let box: HTMLDivElement | null = $state(null);
  let stick = true;
  let open = $state<Set<number>>(new Set());

  const rows = $derived.by(() => {
    const all = foldRows(lines);
    const picked = filter === "replies" ? all.filter((r) => r.level === "reply")
      : filter === "problems" ? all.filter((r) => r.level === "error" || r.level === "warn")
      : all;
    return newestFirst ? picked.slice().reverse() : picked;
  });

  // Keep the newest in view while you are at that end; once you scroll away to read, leave the list where it is.
  $effect(() => {
    void rows.length;
    void rows[newestFirst ? 0 : rows.length - 1]?.more.length;
    if (!stick) return;
    tick().then(() => box?.scrollTo({ top: newestFirst ? 0 : box.scrollHeight }));
  });
  function onScroll() {
    if (!box) return;
    stick = newestFirst ? box.scrollTop < 30 : box.scrollHeight - box.scrollTop - box.clientHeight < 30;
  }
  function toggle(id: number) {
    const next = new Set(open);
    next.has(id) ? next.delete(id) : next.add(id);
    open = next;
  }
  /** Only a line that just came in slides in, never the whole list when it first draws. */
  const mountedAt = Date.now() / 1000;
  const isFresh = (ts: number) => ts > mountedAt;
</script>

<div class="lw {tall ? 'h-96' : 'h-56'}" bind:this={box} onscroll={onScroll}>
  {#each rows as r (r.id)}
    <LogRow row={r} who={sourceInfo(r.source, $chatAccounts)} compact open={open.has(r.id)} fresh={isFresh(r.ts)}
            ontoggle={() => toggle(r.id)} onmenu={(e) => lineMenu(e, r)} />
  {:else}
    <p class="lw-empty">{filter === "problems" ? "No errors or warnings. Good." : "Waiting for something to happen."}</p>
  {/each}
</div>

<style>
  .lw {
    overflow-y: auto;
    /* Straight on the Dashboard's surface, not in a dark panel of its own:
       the lines fade out at the top and bottom edges instead of being boxed. */
    padding: 2px 0;
    -webkit-mask-image: linear-gradient(180deg, transparent, #000 14px, #000 calc(100% - 14px), transparent);
    mask-image: linear-gradient(180deg, transparent, #000 14px, #000 calc(100% - 14px), transparent);
    container-type: inline-size;
  }
  .lw-empty { padding: 28px 12px; font-size: 12.5px; text-align: center; color: var(--color-faint); }
</style>
