<script lang="ts">
  /**
   * The batch waits: how long it sits on a burst of messages before replying, as a few waits it picks between at
   * random, each with its chance.
   *
   * The value is a list of {time, weight}: seconds, and how often that wait is picked relative to the others (the
   * runner hands both to random.choices). {time, to, weight} is a range: any whole second from time to to, so the
   * wait is never quite the same twice.
   *
   * One row per wait, on one time scale, each part doing one thing: the time on the left (click it to type "45s" or a
   * range, "20s-1m"); a bar where the wait falls on the scale, which drags to move it and has an end on each side to
   * pull it into a range or back into one time; and its chance on a meter of its own, with the number to type. It
   * used to be a chart of heads to drag sideways for the time and up for the chance at once, with side handles and
   * the times staggered under the axis: neighbours' heads and labels piled on each other, and moving one dragged the
   * other ("messy and hard to use", 2026-11-11). Rows can't overlap, and a drag changes one thing.
   *
   * The scale is logarithmic, from a couple of seconds to past the longest wait, so 20 s, 40 s and 90 s get as much
   * room as 5 and 15 minutes (the waits people pick span that much). A likelier wait's bar is stronger. The chances
   * always add up to 100: one changed, the others give way, keeping their proportions between them.
   *
   * The DM table always keeps one wait: the runner cannot pick from nothing. The server table can be emptied, which
   * means servers use the DM waits: then it is a small line, with the DM waits drawn faintly in it.
   */
  import { tick, untrack } from "svelte";
  import { Tween } from "svelte/motion";
  import { quintOut } from "svelte/easing";
  import { motionEnabled } from "../stores";
  import { compact, niceTop, readTime, say, snap, stepFor } from "../durations";
  import { onScreen, whenShown } from "../cascade";
  import { play } from "../uisound";

  /** A wait in seconds and its weight; with `to`, any time from `time` to `to`. */
  type Row = { time: number; weight: number; to?: number };

  let { value = [], onchange, canEmpty = false, fallback = [] }: {
    value?: Row[];
    onchange?: (rows: Row[]) => void;
    /** Whether it may be emptied: the server table, which then follows the DM one. */
    canEmpty?: boolean;
    /** The waits it follows while empty (the DM ones), drawn faintly. */
    fallback?: Row[];
  } = $props();

  /** The waits as they are shown and dragged, with a key each so a drag follows the same one. */
  type Wait = { key: number; time: number; to: number | null; share: number };
  let made = 0;
  let waits = $state<Wait[]>([]);
  let lastSent = "";
  /** The key of the wait being dragged, if one is. */
  let dragging = $state<number | null>(null);

  const clean = (rows: Row[]): Row[] => (Array.isArray(rows) ? rows : [])
    .map((r) => {
      const time = Math.max(1, Number(r?.time) || 0);
      const to = Math.round(Number(r?.to));
      const row: Row = { time, weight: Math.max(0, Number(r?.weight) || 0) };
      if (isFinite(to) && to > time) row.to = to;
      return row;
    })
    .filter((r) => r.time > 0);
  /** Where a wait ends: its own time, or the far end of its range. */
  const endOf = (w: { time: number; to?: number | null }) => w.to ?? w.time;

  // The parent's value, unless it is the one this editor just sent: a drag must not be re-seeded under the pointer.
  // Both sides are compared as clean() writes them (a range sent as {time, to, weight} came back as {time, weight,
  // to}: the same wait, not the same text, and every step of a drag re-seeded the waits with new keys). And never
  // while a drag is under way: what comes back then is only this editor's own echo.
  $effect(() => {
    const incoming = JSON.stringify(clean(value));
    if (incoming === lastSent || untrack(() => dragging) != null) return;
    lastSent = incoming;
    const rows = clean(value);
    const total = rows.reduce((n, r) => n + r.weight, 0) || 1;
    untrack(() => {
      waits = rows.map((r) => ({ key: ++made, time: r.time, to: r.to ?? null, share: rows.length ? r.weight / total : 0 }));
    });
  });

  /** Odds as whole percentages that add up to 100, the largest remainders rounded up. */
  function percents(shares: number[]): number[] {
    const raw = shares.map((s) => Math.max(0, s) * 100);
    const floor = raw.map(Math.floor);
    let left = 100 - floor.reduce((a, b) => a + b, 0);
    const order = raw.map((r, i) => [r - floor[i], i]).sort((a, b) => b[0] - a[0]);
    for (const [, i] of order) {
      if (left <= 0) break;
      floor[i]++;
      left--;
    }
    return floor;
  }

  function send(next: Wait[]) {
    waits = next;
    const pcts = percents(next.map((w) => w.share));
    const rows = next.map((w, i): Row => (w.to != null && w.to > w.time
      ? { time: w.time, to: w.to, weight: pcts[i] }
      : { time: w.time, weight: pcts[i] }))
      .sort((a, b) => a.time - b.time);
    lastSent = JSON.stringify(clean(rows));
    onchange?.(rows);
  }

  // ── The scale ──────────────────────────────────────────────────────────────
  const longest = $derived(Math.max(10, ...waits.map(endOf)));
  /** The far end of the scale: room past the longest wait, grown only between drags. */
  let top = $state(untrack(() => niceTop(Math.max(10, ...clean(value).map(endOf)), "s")));
  $effect(() => {
    const l = longest;
    if (dragging != null) return;
    if (l >= top * 0.98 || l < top / 8) untrack(() => (top = niceTop(l, "s")));
  });
  // The scale eases to a new length like the clocks do: quick, then a soft finish.
  const topSmooth = new Tween(0, { duration: 750, easing: quintOut });
  $effect(() => {
    topSmooth.set(top, { duration: $motionEnabled && topSmooth.current ? 750 : 0 });
  });
  /** The short end of the scale, in seconds: nothing waits less. */
  const LO = 2;
  const logFrac = (t: number, hi: number) => Math.max(0, Math.min(1, Math.log(Math.max(t, LO) / LO) / Math.log(hi / LO)));
  /** Where a time sits along a row, 0 to 1, as drawn (the scale easing to a new length). */
  const along = (t: number) => logFrac(t, topSmooth.current || top);
  /** The time at a place along a row, rounded the way times are. */
  const timeAt = (f: number) => {
    const raw = LO * Math.pow(top / LO, Math.max(0, Math.min(1, f)));
    return Math.max(1, snap(raw, "s", { least: 1, integer: true, lo: 1, hi: top }));
  };

  /** The rows' width in pixels, so the scale's amounts never crowd. */
  let laneW = $state(260);
  /** Round amounts along the scale, as far apart as their words need. */
  const ruler = $derived.by(() => {
    const hi = topSmooth.current || top;
    const gap = 38 / Math.max(120, laneW);
    const out: { v: number; f: number; text: string; end?: boolean }[] = [];
    for (const v of [5, 10, 30, 60, 120, 300, 600, 1800, 3600, 7200, 21600, 43200, 86400, 172800, 604800]) {
      // Short of the end, whichever way the scale is easing (the end's own mark is `top`).
      if (v >= Math.min(hi, top) * 0.999) break;
      const f = logFrac(v, hi);
      if (f - (out.at(-1)?.f ?? -1) < gap || 1 - f < gap) continue;
      out.push({ v, f, text: compact(v) });
    }
    // Its far end too, so the last stretch of the rows has a time on it.
    out.push({ v: top, f: 1, text: compact(top), end: true });
    return out;
  });

  // ── The rows ───────────────────────────────────────────────────────────────
  const total = $derived(waits.reduce((n, w) => n + w.share, 0) || 1);
  const most = $derived(Math.max(0.01, ...waits.map((w) => w.share)));
  /** The order held while dragging, so the row under the pointer stays under it until it is let go. */
  let frozen: number[] | null = null;
  const rows = $derived.by(() => {
    if (dragging == null || !frozen) return [...waits].sort((a, b) => a.time - b.time || a.key - b.key);
    const rank = new Map(frozen.map((k, i) => [k, i]));
    return [...waits].sort((a, b) => (rank.get(a.key) ?? 99) - (rank.get(b.key) ?? 99));
  });
  const pctOf = (w: Wait) => Math.round((w.share / total) * 100);

  /** A wait as a person reads it: "40s", or "20s–1m" for a range. */
  const short = (w: { time: number; to: number | null }) => (w.to != null ? `${compact(w.time)}–${compact(w.to)}` : compact(w.time));
  const spoken = (w: { time: number; to: number | null }) =>
    (w.to != null ? `between ${say(w.time, "s")} and ${say(w.to, "s")}` : say(w.time, "s"));

  // ── In words, under it ─────────────────────────────────────────────────────
  // A range is any second across it, evenly, so on average its middle.
  const mean = $derived(waits.reduce((n, w) => n + ((w.time + endOf(w)) / 2) * w.share, 0) / total);
  const usual = $derived([...waits].sort((a, b) => b.share - a.share)[0]);

  /** The DM waits as a small faint hill, for the empty server table. */
  const ghost = $derived.by(() => {
    const rows = clean(fallback);
    if (!rows.length) return "";
    const gw = 88, gh = 26, hi = niceTop(Math.max(10, ...rows.map(endOf)), "s");
    const sum = rows.reduce((n, r) => n + r.weight, 0) || 1;
    const xs = Array.from({ length: 45 }, (_, k) => (gw * k) / 44);
    const bumps = rows.flatMap((r) => {
      const a = gw * logFrac(r.time, hi), b = gw * logFrac(endOf(r), hi);
      const n = Math.max(1, Math.ceil((b - a) / 4));
      return Array.from({ length: n }, (_, k) => ({ x: n === 1 ? a : a + ((b - a) * k) / (n - 1), s: r.weight / sum / n }));
    });
    const ds = xs.map((x) => bumps.reduce((d, b) => d + b.s * Math.exp(-((x - b.x) ** 2) / 18), 0));
    const peak = Math.max(...ds) || 1;
    return `M 0 ${gh} ` + xs.map((x, k) => `L ${x.toFixed(1)} ${(gh - (ds[k] / peak) * (gh - 3)).toFixed(1)}`).join(" ") + ` L ${gw} ${gh} Z`;
  });

  // ── Arriving with its tab ──────────────────────────────────────────────────
  // The bars grow out along their rows and the meters fill, one wait after another, as the row drops in.
  let root: HTMLElement | null = $state(null);
  let arrived = $state(false);
  let arriving = $state(false);
  $effect(() => {
    const el = root;
    if (!el) return;
    whenShown(el).then(() => onScreen(el)).then((seen) => {
      arrived = arriving = true;
      setTimeout(() => (arriving = false), 1800);
      if (!seen || !$motionEnabled) return;
      // Heard as they grow: each wait into place in its turn (70 ms apart, as drawn), a step higher each.
      const n = untrack(() => waits.length);
      for (let i = 0; i < n; i++) setTimeout(() => play("rise", { p: n > 1 ? i / (n - 1) : 0.5 }), 90 + i * 70);
    });
  });

  // ── Changing them ──────────────────────────────────────────────────────────
  /** One wait's chance set to `share`, the others keeping their proportions between them. */
  function withShare(list: Wait[], i: number, share: number): Wait[] {
    if (list.length === 1) return [{ ...list[0], share: 1 }];
    const others = list.reduce((n, w, j) => (j === i ? n : n + w.share), 0) || 1;
    return list.map((w, j) => (j === i ? { ...w, share } : { ...w, share: (w.share / others) * (1 - share) }));
  }
  /** Two ends made into a wait: a range, or one time again when they have met. */
  function span(a: number, b: number): { time: number; to: number | null } {
    const lo = Math.min(a, b);
    const hi = Math.max(a, b);
    return hi / lo < 1.08 || hi - lo < 1 ? { time: lo, to: null } : { time: lo, to: hi };
  }
  function change(k: number, next: Partial<Wait>) {
    send(waits.map((w) => (w.key === k ? { ...w, ...next } : w)));
  }
  function remove(k: number) {
    if (!canEmpty && waits.length <= 1) return;
    const left = waits.filter((w) => w.key !== k);
    const sum = left.reduce((n, w) => n + w.share, 0) || 1;
    play("delete");
    send(left.map((w) => ({ ...w, share: w.share / sum })));
  }
  /** Another wait, after the longest, with a fair chance. */
  function add() {
    const time = snap(Math.min(Math.max(10, Math.max(0, ...waits.map(endOf)) * 1.8), 86400), "s", { least: 1, integer: true, lo: 1 });
    const list = [...waits, { key: ++made, time, to: null, share: 0 }];
    play("select");
    send(withShare(list, list.length - 1, 1 / list.length));
  }

  /**
   * What a drag holds: the bar (the whole wait along the scale), one of its ends (sideways, against the other end,
   * its anchor), or the chance meter. Where the pointer and the wait were when it was taken hold of, so a bar moves
   * from where it was taken hold of rather than jumping to the pointer, and whether it has moved since.
   */
  type Hold = { key: number; part: "all" | "start" | "end" | "odds"; box: DOMRect; px: number; f0: number; f1: number;
                anchor: number; moved: boolean };
  let hold = $state<Hold | null>(null);
  const ENDS = ["start", "end"] as const;

  function grab(w: Wait, e: PointerEvent, part: Hold["part"]) {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const node = e.currentTarget as HTMLElement;
    const box = (part === "odds" ? node : node.closest(".wt-lane"))?.getBoundingClientRect();
    if (!box) return;
    node.setPointerCapture(e.pointerId);
    node.focus({ preventScroll: true });
    hold = { key: w.key, part, box, px: e.clientX, f0: logFrac(w.time, top), f1: logFrac(endOf(w), top),
             anchor: part === "start" ? endOf(w) : w.time, moved: false };
    frozen = rows.map((r) => r.key);
    play("grab");
    dragging = w.key;
    heard = "";
    detent(w.key);         // where it starts from: no sound for that
    if (part === "odds") dragOdds(e);   // a press on the meter sets the chance there
  }
  function moveHold(e: PointerEvent) {
    // An end's move is the end's alone, not its bar's as well.
    e.stopPropagation();
    const h = hold;
    if (!h || dragging == null) return;
    // A shaky click is still a click: nothing moves until the pointer has.
    if (!h.moved && h.part !== "odds" && Math.abs(e.clientX - h.px) < 3) return;
    h.moved = true;
    if (h.part === "odds") dragOdds(e);
    else dragBar(e);
  }
  /** The bar along its row: the whole wait (a range keeping its span), or one end against the other. */
  function dragBar(e: PointerEvent) {
    const h = hold!;
    const w = waits.find((x) => x.key === h.key);
    if (!w) return;
    const d = (e.clientX - h.px) / h.box.width;
    if (h.part === "all") {
      change(h.key, w.to == null ? { time: timeAt(h.f0 + d), to: null } : span(timeAt(h.f0 + d), timeAt(h.f1 + d)));
    } else {
      change(h.key, span(h.anchor, timeAt((e.clientX - h.box.left) / h.box.width)));
    }
    detent(h.key);
  }
  /** The chance, from where the pointer is along its meter. */
  function dragOdds(e: PointerEvent) {
    const h = hold!;
    const i = waits.findIndex((x) => x.key === h.key);
    if (i < 0) return;
    const share = Math.max(0.01, Math.min(0.97, (e.clientX - h.box.left) / h.box.width));
    send(withShare(waits, i, share));
    detent(h.key);
  }
  function release(e: PointerEvent) {
    e.stopPropagation();
    if (!hold) return;
    hold = null;
    frozen = null;
    dragging = null;
    play("release");
    (e.currentTarget as HTMLElement | null)?.releasePointerCapture?.(e.pointerId);
  }
  /** What a drag last made a sound for: a detent each time the wait lands on another time, or another percent. */
  let heard = "";
  function detent(k: number) {
    const w = waits.find((x) => x.key === k);
    if (!w) return;
    const now = `${w.time}|${w.to ?? ""}|${pctOf(w)}`;
    if (heard && now !== heard) play("tick", { p: logFrac(w.time, top) });
    heard = now;
  }

  /** The keyboard on a bar: arrows move the wait (a range whole, both ends by the step for where each is). */
  function barKey(w: Wait, e: KeyboardEvent) {
    if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      remove(w.key);
      return;
    }
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const step = (t: number) => snap(Math.max(1, t + d * stepFor(t, "s", 1)), "s", { least: 1, integer: true, lo: 1 });
    change(w.key, w.to == null ? { time: step(w.time) } : span(step(w.time), step(w.to)));
  }
  /** The keyboard on a meter: a percent at a time, five with Page Up and Down. */
  function oddsKey(w: Wait, e: KeyboardEvent) {
    const by: Record<string, number> = { ArrowRight: 0.01, ArrowUp: 0.01, ArrowLeft: -0.01, ArrowDown: -0.01, PageUp: 0.05, PageDown: -0.05 };
    if (!(e.key in by)) return;
    e.preventDefault();
    const i = waits.findIndex((x) => x.key === w.key);
    send(withShare(waits, i, Math.max(0.01, Math.min(0.97, w.share / total + by[e.key]))));
  }

  // ── Typing a time or a percentage ──────────────────────────────────────────
  let editing = $state<{ key: number; what: "time" | "share" } | null>(null);
  let draft = $state("");
  let box: HTMLInputElement | null = $state(null);
  async function edit(k: number, what: "time" | "share") {
    const w = waits.find((x) => x.key === k);
    if (!w) return;
    editing = { key: k, what };
    draft = what === "time"
      ? (w.to != null ? `${compact(w.time)}-${compact(w.to)}` : compact(w.time))
      : String(pctOf(w));
    await tick();
    box?.select();
  }
  function typed() {
    if (!editing) return;
    const { key: k, what } = editing;
    editing = null;
    const i = waits.findIndex((x) => x.key === k);
    if (i < 0) return;
    if (what === "time") {
      const next = readSpan(draft);
      if (!next) return;
      change(k, next);
    } else {
      const p = Number(String(draft).replace("%", "").replace(",", ".").trim());
      if (!isFinite(p) || p <= 0) return;
      send(withShare(waits, i, Math.min(0.99, p / 100)));
    }
  }
  /**
   * A typed wait: "45s", "2m", or a range, "20s-1m", "20-40s" or "1 to 2m". A bare number before the dash takes the
   * unit after it, so "1-2m" is one to two minutes, not one second to two minutes.
   */
  function readSpan(text: string): { time: number; to: number | null } | null {
    const parts = text.split(/\s*(?:-|–|\u2014|\bto\b)\s*/i).map((s) => s.trim()).filter(Boolean);
    if (parts.length === 1) {
      const t = readTime(parts[0], "s");
      return t == null || t < 1 ? null : { time: Math.round(t), to: null };
    }
    if (parts.length !== 2) return null;
    const unit = parts[1].match(/[a-z]+$/i)?.[0] ?? "";
    const first = /[a-z]/i.test(parts[0]) ? parts[0] : parts[0] + unit;
    const a = readTime(first, "s");
    const b = readTime(parts[1], "s");
    if (a == null || b == null || a < 1 || b < 1) return null;
    return span(Math.round(a), Math.round(b));
  }
  function typingKey(e: KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      typed();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      editing = null;
    }
  }
</script>

<div class="wt" bind:this={root} class:is-dragging={dragging != null} class:is-in={arrived} class:is-arriving={arriving}>
  {#if !waits.length}
    <!-- The server table, emptied: servers use the DM waits. -->
    <div class="wt-empty">
      {#if ghost}
        <svg class="wt-ghost" viewBox="0 0 88 26" aria-hidden="true"><path d={ghost} /><line x1="0" x2="88" y1="25.5" y2="25.5" /></svg>
      {/if}
      <span>Same waits as DMs</span>
      <button type="button" onclick={() => send([{ key: ++made, time: 20, to: null, share: 1 }])}>Give servers their own</button>
    </div>
  {:else}
    <!-- The scale, over the rows' bars: round amounts where each falls. -->
    <div class="wt-grid wt-scale" aria-hidden="true">
      <span></span>
      <div class="wt-lane-head" bind:clientWidth={laneW}>
        {#each ruler as m (m.v)}<span class="wt-mark" class:is-end={m.end} style="left: {m.f * 100}%">{m.text}</span>{/each}
      </div>
      <span class="wt-head-odds">Chance</span>
    </div>

    <ol class="wt-rows">
      {#each rows as w, i (w.key)}
        {@const pct = pctOf(w)}
        {@const held = dragging === w.key}
        {@const f0 = along(w.time)}
        {@const f1 = along(endOf(w))}
        <li class="wt-grid wt-row" class:is-held={held} style="--i: {i}">
          <!-- The time: click to type it, or a range. -->
          <span class="wt-when">
            {#if editing?.key === w.key && editing.what === "time"}
              <input bind:this={box} bind:value={draft} class="wt-type" onkeydown={typingKey} onblur={typed}
                     aria-label="This wait, like 45s, or a range like 20s-1m" />
            {:else}
              <button type="button" onclick={() => edit(w.key, "time")} title="Type it, like 45s or 20s-1m">{short(w)}</button>
            {/if}
          </span>

          <!-- Where it falls on the scale: drag the bar to move it, an end to make it a range. -->
          <div class="wt-lane">
            {#each ruler as m (m.v)}{#if !m.end}<span class="wt-guide" style="left: {m.f * 100}%"></span>{/if}{/each}
            <span class="wt-bar" class:is-range={w.to != null} class:is-grabbed={held && hold?.part === "all"}
                  style="left: {f0 * 100}%; width: {(f1 - f0) * 100}%; --s: {(w.share / most).toFixed(3)}"
                  role="slider" tabindex="0" aria-label="Wait of {spoken(w)}" aria-valuetext={spoken(w)}
                  aria-valuemin="1" aria-valuemax={top} aria-valuenow={w.time}
                  title="Drag to move it. Drag an end for a range."
                  onpointerdown={(e) => grab(w, e, "all")} onpointermove={moveHold}
                  onpointerup={release} onpointercancel={release} onkeydown={(e) => barKey(w, e)}>
              {#each ENDS as part (part)}
                <span class="wt-grip is-{part}" class:is-held={held && hold?.part === part} aria-hidden="true"
                      onpointerdown={(e) => grab(w, e, part)} onpointermove={moveHold}
                      onpointerup={release} onpointercancel={release}></span>
              {/each}
            </span>
          </div>

          <!-- How often: drag along the meter, or type the number. -->
          <span class="wt-odds" role="slider" tabindex="0" aria-label="Chance of {spoken(w)}"
                aria-valuemin="0" aria-valuemax="100" aria-valuenow={pct} aria-valuetext="{pct}%"
                onpointerdown={(e) => grab(w, e, "odds")} onpointermove={moveHold}
                onpointerup={release} onpointercancel={release} onkeydown={(e) => oddsKey(w, e)}>
            <span class="wt-odds-fill" style="width: {pct}%"></span>
          </span>
          <span class="wt-pct">
            {#if editing?.key === w.key && editing.what === "share"}
              <input bind:this={box} bind:value={draft} class="wt-type is-share" onkeydown={typingKey} onblur={typed}
                     aria-label="Chance of this wait, in percent" />
            {:else}
              <button type="button" onclick={() => edit(w.key, "share")} title="Type it">{pct}%</button>
            {/if}
          </span>

          {#if canEmpty || waits.length > 1}
            <button type="button" class="wt-x" onclick={() => remove(w.key)} aria-label="Remove the wait of {spoken(w)}"
                    title="Remove">×</button>
          {:else}
            <span></span>
          {/if}
        </li>
      {/each}
    </ol>

    <div class="wt-foot">
      <button type="button" class="wt-add" onclick={add}>+ Add a wait</button>
      <p class="wt-say">
        {#if usual}Usually <b>{spoken(usual)}</b>{/if}
        <span>· {say(Math.round(mean), "s")} on average</span>
      </p>
    </div>
  {/if}
</div>

<style>
  .wt { width: 100%; user-select: none; }
  /* One grid for the scale and every row, so the bars and the amounts over them line up: the time, the row, the
     chance meter, its number, and remove. */
  .wt-grid {
    display: grid;
    grid-template-columns: 5.4rem minmax(0, 1fr) 3.6rem 2.7rem 1.1rem;
    align-items: center;
    column-gap: 8px;
  }
  .wt-scale { height: 18px; margin-bottom: 2px; }
  .wt-lane-head { position: relative; height: 100%; }
  .wt-mark {
    position: absolute;
    top: 50%;
    font-size: 10px;
    font-weight: 650;
    color: var(--color-faint);
    white-space: nowrap;
    transform: translate(-50%, -50%);
  }
  .wt-mark.is-end { transform: translate(-100%, -50%); }
  .wt-head-odds { grid-column: 3 / span 2; font-size: 10px; font-weight: 650; color: var(--color-faint); }
  .wt-rows { display: flex; flex-direction: column; gap: 2px; margin: 0; padding: 0; list-style: none; }
  .wt-row { min-height: 32px; border-radius: 10px; transition: background-color 0.15s ease; }
  .wt-row:hover, .wt-row.is-held { background: rgb(255 255 255 / 0.025); }

  /* The time, light until pointed at; a box to type in when clicked. */
  .wt-when { display: flex; justify-content: flex-end; min-width: 0; }
  .wt-when button, .wt-pct button {
    padding: 2px 6px;
    border-radius: 7px;
    font-size: 12px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    color: var(--color-muted);
    cursor: text;
    transition: background-color 0.18s var(--swift), color 0.18s var(--swift);
  }
  .wt-row:hover .wt-when button, .wt-row.is-held .wt-when button { color: var(--color-ink); }
  .wt-when button:hover, .wt-pct button:hover { background: color-mix(in srgb, var(--color-accent) 16%, transparent); color: var(--color-ink); }
  .wt-type {
    width: 100%;
    min-width: 0;
    padding: 2px 6px;
    border-radius: 7px;
    border: 1px solid color-mix(in srgb, var(--color-accent) 60%, transparent);
    background: var(--color-surface);
    font-size: 12px;
    text-align: center;
    color: var(--color-ink);
    outline: none;
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 16%, transparent);
  }
  .wt-type.is-share { padding: 2px 3px; font-weight: 700; }

  /* The row's scale: a faint track with the round amounts' guides, and the wait's bar on it. */
  .wt-lane {
    position: relative;
    height: 22px;
    border-radius: 999px;
    background: rgb(255 255 255 / 0.035);
  }
  .wt-guide { position: absolute; top: 5px; bottom: 5px; width: 1px; background: rgb(255 255 255 / 0.06); pointer-events: none; }
  /* A likelier wait's bar is stronger (--s, its chance against the likeliest's). One time is a dot; a range spans. */
  .wt-bar {
    position: absolute;
    top: 50%;
    min-width: 14px;
    height: 14px;
    margin-left: -7px;
    border-radius: 999px;
    background: linear-gradient(90deg,
      color-mix(in srgb, var(--color-accent-2, var(--color-accent)) calc(30% + 55% * var(--s)), transparent),
      color-mix(in srgb, var(--color-accent) calc(30% + 55% * var(--s)), transparent));
    transform: translateY(-50%);
    transform-origin: left center;
    cursor: grab;
    outline: none;
    transition: left 0.3s var(--swift), width 0.3s var(--swift), box-shadow 0.2s ease;
  }
  .wt-bar.is-range { margin-left: 0; }
  .wt-bar:hover, .wt-bar:focus-visible { box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 22%, transparent); }
  .wt-bar.is-grabbed { cursor: grabbing; box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-accent) 28%, transparent); }
  .wt.is-dragging .wt-bar { transition: box-shadow 0.2s ease; }
  /* The ends: a range's to drag, a single time's tucked beside its dot, there when the row is pointed at. */
  .wt-grip {
    position: absolute;
    top: 50%;
    width: 6px;
    height: 16px;
    border-radius: 3px;
    background: var(--color-card);
    box-shadow: inset 0 0 0 2px var(--color-accent);
    transform: translate(-50%, -50%);
    cursor: ew-resize;
    opacity: 0;
    transition: opacity 0.16s var(--swift), transform 0.25s var(--jelly);
  }
  .wt-grip.is-start { left: 0; }
  .wt-grip.is-end { left: 100%; }
  .wt-bar:not(.is-range) .wt-grip.is-start { left: -6px; }
  .wt-bar:not(.is-range) .wt-grip.is-end { left: calc(100% + 6px); }
  /* A wider place to take hold of each end than the end itself, outward only: inward it covered a short range's
     middle, and the bar could not be taken hold of to move it whole. */
  .wt-grip::before { content: ""; position: absolute; top: -6px; bottom: -6px; }
  .wt-grip.is-start::before { left: -9px; right: 0; }
  .wt-grip.is-end::before { left: 0; right: -9px; }
  .wt-row:hover .wt-grip, .wt-bar:focus-visible .wt-grip { opacity: 0.85; }
  .wt-grip:hover, .wt-grip.is-held { opacity: 1; transform: translate(-50%, -50%) scaleY(1.2); }
  .wt.is-dragging .wt-grip:not(.is-held) { opacity: 0; }

  /* The chance: a meter to drag along, its number beside it. */
  .wt-odds {
    position: relative;
    height: 22px;
    cursor: pointer;
    outline: none;
  }
  .wt-odds::before {
    content: "";
    position: absolute;
    top: 50%;
    left: 0;
    right: 0;
    height: 6px;
    border-radius: 999px;
    background: rgb(255 255 255 / 0.07);
    transform: translateY(-50%);
  }
  .wt-odds-fill {
    position: absolute;
    top: 50%;
    left: 0;
    height: 6px;
    border-radius: 999px;
    background: linear-gradient(90deg, var(--color-accent-2, var(--color-accent)), var(--color-accent));
    transform: translateY(-50%);
    transition: width 0.3s var(--swift);
  }
  .wt-odds:focus-visible::before { box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 30%, transparent); }
  .wt.is-dragging .wt-odds-fill { transition: none; }
  .wt-pct { display: flex; justify-content: flex-start; }

  /* Remove, at the row's end, there when the row is pointed at. */
  .wt-x {
    display: grid;
    width: 18px;
    height: 18px;
    place-items: center;
    border-radius: 999px;
    font-size: 13px;
    line-height: 1;
    color: var(--color-faint);
    opacity: 0;
    transition: opacity 0.16s var(--swift), background-color 0.16s var(--swift), color 0.16s var(--swift);
  }
  .wt-row:hover .wt-x, .wt-x:focus-visible { opacity: 1; }
  .wt-x:hover { background: var(--color-bad); color: #fff; }
  .wt.is-dragging .wt-x { opacity: 0; }

  .wt-foot { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 12px; margin-top: 6px; }
  .wt-add {
    padding: 4px 10px;
    border-radius: 9px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 12%, transparent);
    transition: background-color 0.15s ease;
  }
  .wt-add:hover { background: color-mix(in srgb, var(--color-accent) 20%, transparent); }
  .wt-say { font-size: 12px; color: var(--color-muted); }
  .wt-say b { font-weight: 650; color: var(--color-ink); }
  .wt-say span { color: var(--color-faint); }

  /* The empty server table: one small line, the DM waits faint in it. */
  .wt-empty {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 7px 7px 7px 10px;
    border-radius: 12px;
    border: 1px dashed rgb(255 255 255 / 0.14);
    font-size: 12px;
    white-space: nowrap;
    color: var(--color-muted);
  }
  .wt-empty svg.wt-ghost { display: block; width: 64px; height: 19px; flex-shrink: 0; overflow: visible; }
  .wt-ghost path { fill: color-mix(in srgb, var(--color-accent) 22%, transparent); stroke: color-mix(in srgb, var(--color-accent) 45%, transparent); stroke-width: 1; }
  .wt-ghost line { stroke: rgb(255 255 255 / 0.16); stroke-width: 1; }
  .wt-empty button {
    padding: 5px 10px;
    border-radius: 9px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 12%, transparent);
  }
  .wt-empty button:hover { background: color-mix(in srgb, var(--color-accent) 20%, transparent); }

  /* ── Arriving ─────────────────────────────────────────────────────────────
     Before its row drops in, the bars sit at no length at their start and the meters empty; then each wait grows
     out along its row in turn, its meter filling with it. */
  .wt.is-arriving .wt-bar,
  .wt.is-arriving .wt-odds-fill {
    transition: transform 0.95s cubic-bezier(0.2, 1.15, 0.3, 1) calc(var(--i, 0) * 70ms),
                width 0.95s cubic-bezier(0.2, 1, 0.3, 1) calc(var(--i, 0) * 70ms), opacity 0.4s var(--swift) calc(var(--i, 0) * 70ms);
  }
  .wt:not(.is-in) .wt-bar { transform: translateY(-50%) scaleX(0); opacity: 0; }
  .wt:not(.is-in) .wt-odds-fill { width: 0 !important; }
  .wt-when, .wt-pct { transition: opacity 0.5s var(--swift) calc(0.25s + var(--i, 0) * 70ms); }
  .wt:not(.is-in) .wt-when, .wt:not(.is-in) .wt-pct { opacity: 0; }
  /* While dragging, the bar follows the pointer and nothing waits. */
  .wt.is-dragging .wt-bar, .wt.is-dragging .wt-odds-fill { transition: none; }

  :global(:root[data-motion="off"]) .wt-bar,
  :global(:root[data-motion="off"]) .wt-odds-fill,
  :global(:root[data-motion="off"]) .wt-when,
  :global(:root[data-motion="off"]) .wt-pct,
  :global(:root[data-motion="off"]) .wt-grip,
  :global(:root[data-motion="off"]) .wt-x,
  :global(:root[data-motion="off"]) .wt-row { transition: none; }
</style>
