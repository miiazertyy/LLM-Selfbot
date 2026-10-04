<script lang="ts">
  /**
   * The batch waits: how long it sits on a burst of messages before replying,
   * as a few waits it picks between at random, each with its odds.
   *
   * The value is a list of {time, weight}: seconds, and how often that wait is
   * picked relative to the others (the runner hands both to random.choices).
   * It used to be raw JSON, then a row of sliders per wait, which showed the
   * numbers but not the shape: whether it mostly answers in half a minute or
   * spreads out over ten.
   *
   * So it is drawn as the odds over time. A scale from a couple of seconds to
   * past the longest wait, logarithmic, so 20 s, 40 s and 90 s get as much
   * room as 5 and 15 minutes (the waits people pick span that much); a stem at
   * each wait, as tall as its chance of being picked; and the spread of it all
   * as a soft hill behind, which is where replies land. Drag a
   * stem's head sideways to change the wait, up or down to change its odds
   * (the others give way, as odds must add up); click the scale to add a wait
   * there; click a time or a percentage to type it. The heads are sliders, so
   * the keyboard works too: arrows move it, Delete removes it.
   *
   * Each wait's chance is written inside its head. It used to sit above it in
   * a dark pill, lifted clear of its neighbours' pills where they would have
   * overlapped, which left a cluster of waits under a jumble of boxes. A head
   * never sits lower than its own size above the axis, so the small chances
   * stay readable, and a drag moves it from where it was taken hold of: with
   * the number in it the head is bigger, and a press on its edge used to jump
   * the chance to wherever the pointer was.
   *
   * A wait can also be a range: {time, to, weight} is any whole second from
   * time to to, picked with that weight, so the wait is never quite the same
   * twice. It is drawn as a plateau across its span, as tall as its odds, with
   * a handle at each end; a single wait has the same two handles tucked in at
   * its sides, and pulling one out stretches it into a range (pushing it back
   * makes it one time again). Typing "20s-1m" in its time does the same.
   *
   * The DM table always keeps one wait: the runner cannot pick from nothing.
   * The server table can be emptied, which means servers use the DM waits:
   * then it is a small line, with the DM waits drawn faintly in it, rather
   * than a box as wide as the chart with nothing in it.
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

  // Drawn at the size it is shown (Settings gives it 30rem), so the numbers
  // over it are a comfortable size to read and to click.
  const W = 480;
  const H = 214;
  const L = 22;
  const RIGHT = W - 22;
  const TOP = 24;
  const BASE = 146;
  /** The heads' radius, and the least a head sits above the axis: its own size. */
  const HEAD = 12.5;
  const LOWEST = BASE - HEAD - 3;

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

  // The parent's value, unless it is the one this editor just sent: a drag must
  // not be re-seeded under the pointer. Both sides are compared as clean()
  // writes them. A range used to be sent as {time, to, weight} and read back
  // as {time, weight, to}: the same wait, but not the same text, so every
  // step of pulling a range out re-seeded the waits with new keys, the drag
  // lost hold of its wait, and the handle would not move. And never while a
  // drag is under way: what comes back then is only this editor's own echo.
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
  const xOf = (t: number) => L + (RIGHT - L) * logFrac(t, topSmooth.current || top);
  /** How tall the odds are drawn: to the next round share past the likeliest, fixed while dragging. */
  let tallest = $state(0.5);
  $effect(() => {
    const most = Math.max(0.05, ...waits.map((w) => w.share));
    if (dragging != null) return;
    untrack(() => (tallest = [0.25, 0.5, 0.75, 1].find((t) => t >= most * 1.12) ?? 1));
  });
  const yOf = (share: number) => BASE - (BASE - TOP) * Math.min(1, share / tallest);
  /** Where a head sits: at its odds, but never down on the axis. */
  const headY = (share: number) => Math.min(LOWEST, yOf(share));

  // A range's head sits in the middle of its span, its ends at x0 and x1.
  const shown = $derived(waits.map((w, i) => {
    const x0 = xOf(w.time);
    const x1 = xOf(endOf(w));
    return { ...w, i, x0, x1, x: (x0 + x1) / 2, y: headY(w.share) };
  }));
  /** A wait as a person reads it: "40s", or "20s–1m" for a range. */
  const short = (w: { time: number; to: number | null }) => (w.to != null ? `${compact(w.time)}–${compact(w.to)}` : compact(w.time));
  const spoken = (w: { time: number; to: number | null }) =>
    (w.to != null ? `between ${say(w.time, "s")} and ${say(w.to, "s")}` : say(w.time, "s"));
  /** Time labels under the stems, staggered onto a second line where two would touch. */
  const labels = $derived.by(() => {
    const sorted = [...shown].sort((a, b) => a.x - b.x);
    const out: Record<number, number> = {};
    let lastX = -99;
    let lastRow = 1;
    let lastWide = false;
    for (const w of sorted) {
      // A range's label ("20s–1m") needs more room than a single time's.
      const room = w.to != null || lastWide ? 64 : 48;
      const row = w.x - lastX < room && lastRow === 0 ? 1 : 0;
      out[w.key] = row;
      lastX = w.x;
      lastRow = row;
      lastWide = w.to != null;
    }
    return out;
  });
  /** Round amounts along the scale, spaced so they do not crowd. */
  const ruler = $derived.by(() => {
    const hi = topSmooth.current || top;
    const out: { v: number; x: number; text: string }[] = [];
    for (const v of [5, 10, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 21600, 43200, 86400, 172800, 604800]) {
      if (v >= hi * 0.999) break;
      const x = xOf(v);
      if (x - (out.at(-1)?.x ?? L - 99) < 40 || RIGHT - x < 24) continue;
      out.push({ v, x, text: compact(v) });
    }
    return out;
  });

  /**
   * The spread: each wait a soft bump as tall as its odds, all added up, and
   * scaled so its peak stands no taller than the likeliest wait. Where
   * replies land.
   */
  const hill = $derived.by(() => {
    if (!shown.length) return "";
    const sigma = 16;
    const xs = Array.from({ length: 91 }, (_, k) => L + ((RIGHT - L) * k) / 90);
    // A range spreads its odds evenly across its span: a row of small bumps
    // along it that add up to one wide, flat-topped one.
    const bumps = shown.flatMap((w) => {
      if (w.to == null) return [{ x: w.x, s: w.share }];
      const n = Math.max(2, Math.ceil((w.x1 - w.x0) / 8));
      return Array.from({ length: n + 1 }, (_, k) => ({ x: w.x0 + ((w.x1 - w.x0) * k) / n, s: w.share / (n + 1) }));
    });
    const ds = xs.map((x) => bumps.reduce((d, b) => d + b.s * Math.exp(-((x - b.x) ** 2) / (2 * sigma * sigma)), 0));
    const peak = Math.max(...ds) || 1;
    const most = Math.max(...shown.map((w) => w.share));
    const pts = xs.map((x, k) => `${x.toFixed(1)} ${yOf((ds[k] / peak) * most * 0.9).toFixed(1)}`);
    return `M ${L} ${BASE} L ${pts.join(" L ")} L ${RIGHT} ${BASE} Z`;
  });

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

  // ── In words, under it ─────────────────────────────────────────────────────
  const total = $derived(waits.reduce((n, w) => n + w.share, 0) || 1);
  // A range is any second across it, evenly, so on average its middle.
  const mean = $derived(waits.reduce((n, w) => n + ((w.time + endOf(w)) / 2) * w.share, 0) / total);
  const usual = $derived([...waits].sort((a, b) => b.share - a.share)[0]);

  // ── Dragging ───────────────────────────────────────────────────────────────
  let svg: SVGSVGElement | null = $state(null);

  // Arriving with its tab: the stems grow up out of the axis and the heads
  // rise into place one after another, as the row drops in.
  let arrived = $state(false);
  let arriving = $state(false);
  $effect(() => {
    const el = svg;
    if (!el) return;
    whenShown(el).then(() => {
      arrived = arriving = true;
      setTimeout(() => (arriving = false), 1800);
      // Heard as they grow: each wait up into place in its turn (70 ms apart, as drawn), a step higher each.
      if ($motionEnabled) onScreen(el).then((seen) => {
        if (!seen) return;
        const n = untrack(() => waits.length);
        for (let i = 0; i < n; i++) setTimeout(() => play("rise", { p: n > 1 ? i / (n - 1) : 0.5 }), 90 + i * 70);
      });
    });
  });
  const at = (e: PointerEvent) => {
    const r = svg!.getBoundingClientRect();
    return { x: ((e.clientX - r.left) * W) / r.width, y: ((e.clientY - r.top) * H) / r.height };
  };
  const timeAt = (x: number) => {
    const f = Math.max(0, Math.min(1, (x - L) / (RIGHT - L)));
    const raw = LO * Math.pow(top / LO, f);
    return Math.max(1, snap(raw, "s", { least: 1, integer: true, lo: 1, hi: top }));
  };
  const shareAt = (y: number) => Math.max(0.01, Math.min(0.97, ((BASE - y) / (BASE - TOP)) * tallest));

  /** One wait's odds set to `share`, the others keeping their proportions between them. */
  function withShare(list: Wait[], i: number, share: number): Wait[] {
    if (list.length === 1) return [{ ...list[0], share: 1 }];
    const others = list.reduce((n, w, j) => (j === i ? n : n + w.share), 0) || 1;
    return list.map((w, j) => (j === i ? { ...w, share } : { ...w, share: (w.share / others) * (1 - share) }));
  }

  /**
   * What a drag holds: the head (the whole wait, sideways and up) or one end
   * of it (sideways only), and for a head the pointer's offset from each end,
   * so a range keeps its span as it moves. An end remembers the other end, the
   * anchor, so it can be pulled past it or pushed back into it.
   */
  let hold = $state<{ part: "all" | "start" | "end"; d0: number; d1: number; anchor: number }>({ part: "all", d0: 0, d1: 0, anchor: 0 });
  /** Where the pointer and the head were when it was taken hold of, and whether it has moved since. */
  let from = { px: 0, py: 0, hx: 0, share: 0, moved: false };
  const ENDS = ["start", "end"] as const;

  function grab(i: number, e: PointerEvent, part: "all" | "start" | "end" = "all") {
    if (!svg || e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    svg.setPointerCapture(e.pointerId);
    const w = shown[i];
    const p = at(e);
    hold = w.to == null && part === "all"
      ? { part, d0: 0, d1: 0, anchor: 0 }
      : { part, d0: w.x0 - p.x, d1: w.x1 - p.x, anchor: part === "start" ? endOf(w) : w.time };
    from = { px: p.x, py: p.y, hx: w.x, share: w.share, moved: false };
    if (dragging == null) play("grab");
    dragging = waits[i].key;
    heard = "";
    detent(i);             // where it starts from: no sound for that
  }
  /** What a drag last made a sound for: a detent each time the wait lands on another time, or another percent. */
  let heard = "";
  function detent(i: number) {
    const w = waits[i];
    if (!w) return;
    const now = `${w.time}|${w.to ?? ""}|${Math.round((w.share / total) * 100)}`;
    if (heard && now !== heard) play("tick", { p: Math.min(1, Math.max(0, Math.log(w.time / LO) / Math.log(top / LO))) });
    heard = now;
  }

  /** Two ends made into a wait: a range, or one time again when they have met. */
  function span(a: number, b: number): { time: number; to: number | null } {
    const lo = Math.min(a, b);
    const hi = Math.max(a, b);
    return hi / lo < 1.08 || hi - lo < 1 ? { time: lo, to: null } : { time: lo, to: hi };
  }
  /** A press on the empty scale: a new wait there, with fair odds, and it follows the pointer. */
  function pressScale(e: PointerEvent) {
    if (!svg || e.button !== 0 || editing) return;
    const p = at(e);
    if (p.y > BASE + 6) return;
    const fresh: Wait = { key: ++made, time: timeAt(p.x), to: null, share: 0 };
    const list = [...waits, fresh];
    send(withShare(list, list.length - 1, Math.min(0.3, 1 / list.length)));
    grab(list.length - 1, e);
    from = { ...from, moved: true, share: waits[list.length - 1]?.share ?? from.share };
  }
  function move(e: PointerEvent) {
    if (dragging == null) return;
    const i = waits.findIndex((w) => w.key === dragging);
    if (i < 0) return;
    const p = at(e);
    // A shaky click is still a click: it types the chance rather than nudging it.
    if (!from.moved && Math.hypot(p.x - from.px, p.y - from.py) < 3) return;
    from.moved = true;
    if (hold.part !== "all") {
      // An end: sideways only, the odds stay where they are.
      const next = span(hold.anchor, timeAt(p.x));
      send(waits.map((w, j) => (j === i ? { ...w, ...next } : w)));
      detent(i);
      return;
    }
    const w = waits[i];
    const moved = w.to == null
      ? { ...w, time: timeAt(from.hx + p.x - from.px) }
      : { ...w, ...span(timeAt(p.x + hold.d0), timeAt(p.x + hold.d1)) };
    // Up for more, from the chance it had: not the chance at the pointer's height.
    const share = Math.max(0.01, Math.min(0.97, from.share + ((from.py - p.y) / (BASE - TOP)) * tallest));
    send(withShare(waits.map((x, j) => (j === i ? moved : x)), i, share));
    detent(i);
  }
  function release(e: PointerEvent) {
    if (dragging == null) return;
    const k = dragging;
    const clicked = !from.moved && hold.part === "all";
    dragging = null;
    play("release");
    svg?.releasePointerCapture?.(e.pointerId);
    // A click on a head, not a drag: type its chance.
    if (clicked) edit(k, "share");
  }
  function remove(i: number) {
    if (!canEmpty && waits.length <= 1) return;
    const left = waits.filter((_, j) => j !== i);
    const sum = left.reduce((n, w) => n + w.share, 0) || 1;
    send(left.map((w) => ({ ...w, share: w.share / sum })));
  }
  function key(i: number, e: KeyboardEvent) {
    const w = waits[i];
    if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      remove(i);
      return;
    }
    const sideways: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1 };
    const upDown: Record<string, number> = { ArrowUp: 0.01, ArrowDown: -0.01, PageUp: 0.05, PageDown: -0.05 };
    if (e.key in sideways) {
      e.preventDefault();
      // A range moves whole, both ends by the step for where each is.
      const step = (t: number) =>
        snap(Math.max(1, t + sideways[e.key] * stepFor(t, "s", 1)), "s", { least: 1, integer: true, lo: 1 });
      const next = w.to == null ? { time: step(w.time) } : span(step(w.time), step(w.to));
      send(waits.map((x, j) => (j === i ? { ...x, ...next } : x)));
    } else if (e.key in upDown) {
      e.preventDefault();
      send(withShare(waits, i, Math.max(0.01, Math.min(0.97, w.share + upDown[e.key]))));
    }
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
      : String(Math.round((w.share / total) * 100));
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
      send(waits.map((x, j) => (j === i ? { ...x, ...next } : x)));
    } else {
      const p = Number(String(draft).replace("%", "").replace(",", ".").trim());
      if (!isFinite(p) || p <= 0) return;
      send(withShare(waits, i, Math.min(0.99, p / 100)));
    }
  }
  /**
   * A typed wait: "45s", "2m", or a range, "20s-1m", "20-40s" or "1 to 2m".
   * A bare number before the dash takes the unit after it, so "1-2m" is one
   * to two minutes, not one second to two minutes.
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
  function press(node: SVGElement, fn: (e: PointerEvent) => void) {
    let call = fn;
    const on = (e: PointerEvent) => call(e);
    node.addEventListener("pointerdown", on);
    return {
      update(next: (e: PointerEvent) => void) {
        call = next;
      },
      destroy() {
        node.removeEventListener("pointerdown", on);
      },
    };
  }
</script>

<div class="wt" class:is-dragging={dragging != null} class:is-in={arrived} class:is-arriving={arriving}>
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
    <div class="wt-chart">
      <svg bind:this={svg} viewBox="0 0 {W} {H}" role="group" aria-label="Waits and their odds"
           onpointermove={move} onpointerup={release} onpointercancel={release}>
        <defs>
          <linearGradient id="wt-hill" x1="0" y1={TOP} x2="0" y2={BASE} gradientUnits="userSpaceOnUse">
            <stop offset="0" stop-color="var(--color-accent)" stop-opacity="0.34" />
            <stop offset="1" stop-color="var(--color-accent-2)" stop-opacity="0.04" />
          </linearGradient>
          <linearGradient id="wt-stem" x1="0" y1={TOP} x2="0" y2={BASE} gradientUnits="userSpaceOnUse">
            <stop offset="0" stop-color="var(--color-accent)" />
            <stop offset="1" stop-color="var(--color-accent-2)" />
          </linearGradient>
        </defs>

        <!-- The scale: faint guides for the odds, the time along the bottom. A press on it adds a wait. -->
        {#each [0.5, 1] as g (g)}
          <line x1={L} x2={RIGHT} y1={yOf(tallest * g)} y2={yOf(tallest * g)} class="wt-guide" />
          <text x={RIGHT} y={yOf(tallest * g) - 4} class="wt-guide-label">{Math.round(tallest * g * 100)}%</text>
        {/each}
        <rect x={L - 8} y={TOP - 8} width={RIGHT - L + 16} height={BASE - TOP + 14} class="wt-hit" use:press={pressScale} />
        <path d={hill} class="wt-hill" />
        <line x1={L} x2={RIGHT} y1={BASE} y2={BASE} class="wt-axis" />
        {#each ruler as m (m.v)}
          <line x1={m.x} x2={m.x} y1={BASE} y2={BASE + 4} class="wt-tick" />
          <text x={m.x} y={H - 5} class="wt-mark">{m.text}</text>
        {/each}


        <!-- Each wait: a stem as tall as its odds, or for a range a plateau
             across its span; its head to drag, and a handle at each side to
             pull it into a range, or to move a range's ends. -->
        {#each shown as w (w.key)}
          {@const pct = Math.round((w.share / total) * 100)}
          {@const held = dragging === w.key}
          {@const rise = `--rise: ${BASE - w.y}px; --i: ${w.i}`}
          {#if w.to != null}
            <rect x={w.x0} y={w.y} width={Math.max(0, w.x1 - w.x0)} height={Math.max(0, BASE - w.y)} rx="3" class="wt-band" style={rise} />
            <line x1={w.x0} x2={w.x1} y1={w.y} y2={w.y} class="wt-bar" style={rise} />
            <line x1={w.x0} x2={w.x0} y1={BASE} y2={w.y} class="wt-side" style={rise} />
            <line x1={w.x1} x2={w.x1} y1={BASE} y2={w.y} class="wt-side" style={rise} />
          {:else}
            <line x1={w.x} x2={w.x} y1={BASE} y2={w.y} class="wt-stem" style={rise} />
          {/if}
          {#each ENDS as part (part)}
            {@const hx = w.to != null ? (part === "start" ? w.x0 : w.x1) : w.x + (part === "start" ? -19 : 19)}
            <rect x={hx - 3} y={w.y - 8} width="6" height="16" rx="3" class="wt-end" class:is-stub={w.to == null}
                  class:is-held={held && hold.part === part} aria-hidden="true" style={rise}
                  use:press={(e) => grab(w.i, e, part)} />
          {/each}
          <g class="wt-head" class:is-grabbed={held && hold.part === "all"} transform="translate({w.x} {w.y})"
             role="slider" tabindex="0" aria-label="Wait of {spoken(w)}"
             aria-valuemin="0" aria-valuemax="100" aria-valuenow={pct} aria-valuetext="{spoken(w)}, picked {pct}% of the time"
             onpointerdown={(e) => grab(w.i, e)} onkeydown={(e) => key(w.i, e)}>
            <g class="wt-rise" style={rise}>
              <circle r={HEAD} class="wt-knob" />
              {#if !(editing?.key === w.key && editing.what === "share")}
                <text class="wt-num" class:is-long={pct >= 100}>{pct}<tspan class="wt-pc" dx="0.5">%</tspan></text>
              {/if}
            </g>
          </g>
        {/each}
      </svg>

      <!-- Over the chart as HTML: the box to type a chance in (a click on a
           head opens it), and the button that removes a wait. -->
      {#each shown as w (w.key)}
        {@const row = labels[w.key] ?? 0}
        {#if editing?.key === w.key && editing.what === "share"}
          <div class="wt-pct" style="left: {(w.x / W) * 100}%; top: {(w.y / H) * 100}%">
            <input bind:this={box} bind:value={draft} class="wt-type is-share" onkeydown={typingKey} onblur={typed}
                   aria-label="Chance of this wait, in percent" />
          </div>
        {:else if canEmpty || waits.length > 1}
          <button type="button" class="wt-x" style="left: {((w.x + HEAD + 2) / W) * 100}%; top: {((w.y - HEAD - 2) / H) * 100}%"
                  onclick={() => remove(w.i)} aria-label="Remove the wait of {spoken(w)}" title="Remove">×</button>
        {/if}
        <div class="wt-time" style="left: {(w.x / W) * 100}%; top: {((BASE + 6 + row * 20) / H) * 100}%; --i: {w.i}">
          {#if editing?.key === w.key && editing.what === "time"}
            <input bind:this={box} bind:value={draft} class="wt-type" class:is-wide={w.to != null} onkeydown={typingKey}
                   onblur={typed} aria-label="This wait, like 45s, or a range like 20s-1m" />
          {:else}
            <button type="button" onclick={() => edit(w.key, "time")}
                    title="Click to type the wait, or a range like 20s-1m">{short(w)}</button>
          {/if}
        </div>
      {/each}
    </div>

    <p class="wt-say">
      {#if usual}Usually <b>{spoken(usual)}</b>{/if}
      <span>· {say(Math.round(mean), "s")} on average</span>
    </p>
    <p class="wt-hint">Drag a dot sideways for the wait, up for its chance, or click it to type. Pull its sides out for a range. Click the scale to add one.</p>
  {/if}
</div>

<style>
  .wt { width: 100%; user-select: none; }
  .wt-chart { position: relative; width: 100%; }
  .wt svg { display: block; width: 100%; height: auto; overflow: visible; touch-action: none; }
  .wt-hit { fill: transparent; cursor: copy; }
  .wt.is-dragging .wt-hit { cursor: grabbing; }
  .wt-guide { stroke: rgb(255 255 255 / 0.05); stroke-dasharray: 2 4; pointer-events: none; }
  .wt-guide-label { font-size: 9.5px; fill: var(--color-faint); text-anchor: end; pointer-events: none; }
  .wt-hill { fill: url(#wt-hill); pointer-events: none; transition: d 0.3s var(--swift); }
  .wt.is-dragging .wt-hill { transition: none; }
  .wt-axis { stroke: rgb(255 255 255 / 0.16); stroke-width: 1.2; pointer-events: none; }
  .wt-tick { stroke: rgb(255 255 255 / 0.2); pointer-events: none; }
  .wt-mark { font-size: 10px; font-weight: 650; fill: var(--color-faint); text-anchor: middle; pointer-events: none; }
  .wt-stem { stroke: url(#wt-stem); stroke-width: 3.5; stroke-linecap: round; pointer-events: none; }
  /* A range: its span shaded up to its odds, a bar along the top, thin sides. */
  .wt-band { fill: url(#wt-hill); opacity: 0.9; pointer-events: none; }
  .wt-bar { stroke: url(#wt-stem); stroke-width: 3.5; stroke-linecap: round; pointer-events: none; }
  .wt-side { stroke: color-mix(in srgb, var(--color-accent) 45%, transparent); stroke-width: 1.5; pointer-events: none; }
  /* The ends: a range's to drag, a single wait's tucked beside it, showing on hover, to pull out into one. */
  .wt-end {
    fill: rgb(20 22 34);
    stroke: var(--color-accent);
    stroke-width: 2;
    cursor: ew-resize;
    transition: opacity 0.18s var(--swift), transform 0.3s var(--jelly);
    transform-box: fill-box;
    transform-origin: center;
  }
  .wt-end:hover, .wt-end.is-held { transform: scaleY(1.25); stroke-width: 2.5; }
  .wt-end.is-stub { opacity: 0; }
  .wt-chart:hover .wt-end.is-stub { opacity: 0.7; }
  .wt-end.is-stub:hover, .wt-end.is-stub.is-held { opacity: 1; }
  .wt.is-dragging .wt-end.is-stub:not(.is-held) { opacity: 0; }

  .wt-head { cursor: grab; outline: none; }
  .wt.is-dragging .wt-head { cursor: grabbing; }
  .wt-knob {
    fill: rgb(20 22 34);
    stroke: var(--color-accent);
    stroke-width: 2.5;
    transition: transform 0.35s var(--spring), stroke-width 0.2s ease;
    transform-box: fill-box;
    transform-origin: center;
  }
  /* The chance, inside its head. */
  .wt-num {
    font-size: 10px;
    font-weight: 750;
    letter-spacing: -0.02em;
    fill: var(--color-ink);
    text-anchor: middle;
    dominant-baseline: central;
    font-variant-numeric: tabular-nums;
    pointer-events: none;
    transition: transform 0.35s var(--spring);
    transform-box: fill-box;
    transform-origin: center;
  }
  .wt-num.is-long { font-size: 8.5px; }
  .wt-pc { font-size: 7px; font-weight: 650; fill: var(--color-faint); }
  .wt-head:hover .wt-knob, .wt-head:focus-visible .wt-knob { transform: scale(1.12); }
  .wt-head.is-grabbed .wt-knob { transform: scale(1.22); stroke-width: 3; }
  .wt-head:hover .wt-num, .wt-head:focus-visible .wt-num { transform: scale(1.12); }
  .wt-head.is-grabbed .wt-num { transform: scale(1.22); }
  .wt-head:focus-visible .wt-knob { stroke-width: 3.5; }

  .wt-pct, .wt-time { position: absolute; display: flex; align-items: center; gap: 2px; transform: translateX(-50%); white-space: nowrap; }
  /* The box a chance is typed in sits where its head is. */
  .wt-pct { z-index: 2; transform: translate(-50%, -50%); }
  /* The times, with room round them to click: each lights up when pointed
     at, and turns into a box to type in. */
  .wt-time button {
    padding: 2px 7px;
    border-radius: 7px;
    font-variant-numeric: tabular-nums;
    cursor: text;
    transition: background-color 0.18s var(--swift), color 0.18s var(--swift);
  }
  .wt-time button { font-size: 12px; font-weight: 600; color: var(--color-muted); }
  .wt-time button:hover {
    background: color-mix(in srgb, var(--color-accent) 18%, transparent);
    color: var(--color-ink);
  }
  .wt-type {
    width: 7ch;
    padding: 2px 6px;
    border-radius: 7px;
    border: 1px solid color-mix(in srgb, var(--color-accent) 60%, transparent);
    background: var(--color-surface);
    font-size: 12.5px;
    text-align: center;
    color: var(--color-ink);
    outline: none;
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 16%, transparent);
  }
  .wt-type.is-wide { width: 11ch; }
  .wt-type.is-share { width: 5.5ch; padding: 3px 4px; font-weight: 700; }
  /* Remove, at the top right of its head, there only when the chart is pointed at. */
  .wt-x {
    position: absolute;
    z-index: 2;
    margin: -9px 0 0 -9px;
    display: grid;
    width: 18px;
    height: 18px;
    place-items: center;
    border-radius: 999px;
    border: 1px solid var(--color-edge);
    background: var(--color-card);
    font-size: 12px;
    line-height: 1;
    color: var(--color-muted);
    opacity: 0;
    transform: scale(0.5);
    transition: opacity 0.16s var(--swift), transform 0.3s var(--jelly), background-color 0.16s var(--swift);
  }
  .wt-chart:hover .wt-x { opacity: 0.8; transform: scale(1); }
  .wt-x:hover { opacity: 1; background: var(--color-bad); border-color: var(--color-bad); color: #fff; }
  .wt-x:focus-visible { opacity: 1; transform: scale(1); }
  .wt.is-dragging .wt-x { opacity: 0; }

  .wt-say { margin-top: 6px; font-size: 12px; color: var(--color-muted); }
  .wt-say b { font-weight: 650; color: var(--color-ink); }
  .wt-say span { color: var(--color-faint); }
  .wt-hint { margin-top: 2px; font-size: 10.5px; color: var(--color-faint); }

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
  /* More particular than the chart's own svg rule, which would stretch it across the row. */
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
     Before its row drops in, everything sits on the axis: stems and bands at
     no height, heads and handles down at the base, the numbers not yet there.
     Then each wait grows up in turn, the hill swelling behind them. */
  .wt-stem, .wt-band, .wt-side, .wt-hill { transform-box: fill-box; transform-origin: 50% 100%; }
  .wt-stem, .wt-band, .wt-side, .wt-bar, .wt-rise {
    transition: transform 0.95s cubic-bezier(0.2, 1.15, 0.3, 1) calc(var(--i, 0) * 70ms);
  }
  /* The ends keep their quick hover; the slow rise is only for the arrival. */
  .wt.is-arriving .wt-end {
    transition: transform 0.95s cubic-bezier(0.2, 1.15, 0.3, 1) calc(var(--i, 0) * 70ms), opacity 0.18s var(--swift);
  }
  .wt-hill { transition: d 0.3s var(--swift), transform 1.1s cubic-bezier(0.2, 1, 0.3, 1), opacity 0.8s var(--swift); }
  .wt:not(.is-in) .wt-stem,
  .wt:not(.is-in) .wt-band,
  .wt:not(.is-in) .wt-side { transform: scaleY(0); }
  .wt:not(.is-in) .wt-bar,
  .wt:not(.is-in) .wt-rise,
  .wt:not(.is-in) .wt-end { transform: translateY(var(--rise, 0)); }
  .wt:not(.is-in) .wt-hill { transform: scaleY(0.2); opacity: 0; }
  .wt-time { transition: opacity 0.5s var(--swift) calc(0.35s + var(--i, 0) * 70ms); }
  .wt:not(.is-in) .wt-time { opacity: 0; }
  /* While dragging, the head follows the pointer and nothing waits. */
  .wt.is-dragging .wt-rise, .wt.is-dragging .wt-stem, .wt.is-dragging .wt-band { transition: none; }

  :global(:root[data-motion="off"]) .wt-stem,
  :global(:root[data-motion="off"]) .wt-band,
  :global(:root[data-motion="off"]) .wt-side,
  :global(:root[data-motion="off"]) .wt-bar,
  :global(:root[data-motion="off"]) .wt-rise,
  :global(:root[data-motion="off"]) .wt-time,
  :global(:root[data-motion="off"]) .wt-knob,
  :global(:root[data-motion="off"]) .wt-num,
  :global(:root[data-motion="off"]) .wt-end,
  :global(:root[data-motion="off"]) .wt-x,
  :global(:root[data-motion="off"]) .wt-hill { transition: none; }
</style>
