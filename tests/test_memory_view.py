"""Memory's people: put in order, narrowed down, searched, and the page filling the window (2026-11-06).

Asked for: "filter from most recent, oldest, most remembers etc, add a bunch of filters and a search thing"; the
list to expand to the whole page; and the brain, picking someone at random, not to scroll the page down for no
reason. The order, the filters and the search are webui/src/lib/memoryview.ts, run for real under Node by
tests/memoryview_logic.mjs; this checks that, and how the page wires it in.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


page = read("webui/src/pages/Memory.svelte")
logic = read("webui/src/lib/memoryview.ts")
stores = read("webui/src/lib/stores.ts")

print("== the order, the filters and the search, run for real ==")
node = shutil.which("node")
if not node:
    print("  SKIP  needs Node")
else:
    proc = subprocess.run([node, str(ROOT / "tests" / "memoryview_logic.mjs")], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120)
    print("\n".join("  " + line for line in proc.stdout.strip().splitlines()[-3:]))
    check("memoryview_logic.mjs passes", proc.returncode == 0, (proc.stdout + proc.stderr)[-800:])

print("\n== the choices, in plain words ==")
for label in ("Most recent", "Oldest", "Most remembered", "Least remembered", "Most messages", "Just learned", "Newest",
              "Known longest", "A to Z", "Any time", "Today", "This week", "This month", "Older", "Learned today",
              "2+ facts", "Own tone", "Linked"):
    check(f'"{label}"', f'label: "{label}"' in logic)

print("\n== on the page ==")
check("the list is what lib/memoryview.ts makes of it, the old name-or-fact filter gone",
      "arrange(users, view, { query: queryDebounced, now: Date.now() / 1000, nameOf, present })" in page
      and "const shown = $derived(arranged.list);" in page and "u.user_id.includes(q)" not in page)
check("the order is the app's own dropdown, with Sort before it",
      '<Select size="sm" prefix="Sort" value={view.sort} options={SORT_OPTIONS} search={false} listMax={380}' in page)
check("the filters grow in place under it, pushing the list down rather than covering it",
      '<div class="mm-filters-box" use:smoothHeight={{ duration: 300 }}>' in page and ".mm-filters-box { overflow: hidden;" in page)
check("when they talked: one of five, the highlight springing across",
      '<div class="chips is-one" data-sound="self" role="group" aria-label="Talked" use:glide={view.talked}>' in page
      and 'class:is-active={view.talked === t.id}' in page)
check("a platform only where someone is on it, in its own colour, with how many",
      "{#if present.length > 1}" in page and 'style="--tone: {p.tone}"' in page
      and '<span class="mm-chip-n">{perPlatform[id]}</span>' in page and ".mm-plat[aria-pressed=\"true\"] { --color-accent: var(--tone); }" in page)
check("a platform switched off in Settings is not among them: the list is already without its people",
      "u.platform ? platformOn($socialsOn, u.platform) : personOn($socialsOn, u.user_id)" in page
      and "PLATFORM_IDS.filter((id) => perPlatform[id])" in page)
check("each chip heard as it is picked (lib/feel.ts), each row of them saying so",
      page.count('class="chips" data-sound="self" role="group"') == 2)
check("Filters says how many are on, and Clear puts them all back but the order",
      '{#if filtering}<span class="mm-tool-n">{filtering}</span>{/if}' in page
      and "memoryView.set({ ...DEFAULT_VIEW, sort: view.sort });" in page and 'play("undo");' in page)
check("heard opening and closing", 'play(filtersOpen ? "open" : "off");' in page)
check("a button like every other: tinted, in app.css's one list", ".mm-forget, .mm-tool, .mp-choice" in read("webui/src/app.css")
      and ".mm-tool.is-open::before { --d3-lit: 1; }" in page)
check("nobody left: says so, and one press shows everyone again",
      "<p>Nobody matches that.</p>" in page and 'onclick={() => clearFilters(true)}>Show everyone</button>' in page)
check("a new order or new filters glide the list back to its top", "glideTo(listEl, 0);" in page
      and "export function glideTo(" in read("webui/src/lib/smoothscroll.ts"))
check("the rows slide to their new places, rather than jumping, and not with Animations off",
      "animate:flip={{ duration: $motionEnabled ? 320 : 0, easing: cubicOut }}" in page)
check("and do not pop in again as they move: the arrival plays once", "use:domino={{ step: 35, max: 14, once: true }}" in page)

print("\n== the search ==")
check("cleared with its x or Escape, heard", 'class="mm-search-x" data-sound="self" onclick={clearSearch}' in page
      and 'if (e.key === "Escape" && query) { e.preventDefault(); clearSearch(); }' in page and 'play("off");' in page)
check("found by a fact: the row says which, its words lit", "{@const hit = arranged.matches.get(u.user_id)?.fact}" in page
      and '<span class="mm-found-key">{words(hit.key)}</span>' in page and '<mark class="mm-hit">{text}</mark>' in page)
check("the name lit where it was found", "marks(nameOf(u), inNames)" in page)
check("the line under a name says what the list is sorted by", "function metaOf(u: MemUser): string {" in page
      and "`learned ${ago(u.learned_at)}`" in page and "`met ${fmtDate(u.first_seen * 1000, DAY_MONTH)}`" in page)

print("\n== kept between visits ==")
check("in the panel's preferences, on the server too", 'export const memoryView = persisted<Record<string, unknown>>("memoryView", {}, true);' in stores)
from app.web.routes import prefs_routes  # noqa: E402

check("which the server keeps", "memoryView" in prefs_routes.ALLOWED)
check("read through mend, so what another build kept can't break the list", "const view = $derived(mend($memoryView));" in page)
check("the search is not kept: it is for now", "query" not in stores[stores.index("export const memoryView"):][:200])

print("\n== the whole window ==")
fill = read("webui/src/lib/fillheight.ts")
check("the list and the person beside it fill the window to its bottom", '<div class="mm-body" use:fillHeight={320}>' in page
      and "height: var(--fill-h, auto);" in page and "grid-template-rows: minmax(0, 1fr);" in page)
check("each scrolling on its own; only the list gives way in its card",
      ".mm-people > .mm-list { flex: 1 1 auto; min-height: 0; max-height: none; }" in page
      and ".mm-people > * { flex-shrink: 0; }" in page and ".mm-detail { min-height: 0; overflow-y: auto; }" in page)
check("only on a wide window: narrow, the halves stack and the page scrolls", "@media (min-width: 1024px) {\n    .mm-body {" in page)
check("one helper for it, Chats' inbox the same", "export function fillHeight(" in fill
      and "function fillHeight(" not in read("webui/src/pages/Chats.svelte")
      and 'import { fillHeight } from "../lib/fillheight";' in read("webui/src/pages/Chats.svelte")
      and "height: var(--fill-h, calc(100dvh - 120px));" in read("webui/src/pages/Chats.svelte"))
check("measured again once the tab has dropped into place", "window.setTimeout(set, 800)" in fill)

print("\n== the brain ==")
spin = page[page.index("async function spinBrain()"):page.index("// ── One person, several accounts")]
bring = page[page.index("async function bringUp("):page.index("/** Opens what the line beside the brain points at")]
check("its pick moves the list to them and leaves the page where it is",
      'await bringUp(anyOf(Object.keys(detail?.facts ?? {})) ?? "");' in spin
      and "async function bringUp(key: string, toFact = false) {" in bring
      and bring.index("if (!toFact) return;") < bring.index("if (fact) glideInto(fact);")
      and 'glideInto(row, { within: row?.closest(".mm-list") ?? null });' in bring)
check("the line beside it still shows the fact it names", 'await bringUp(latest && latest.user_id === uid ? latest.key : "", true);' in page)
check("and it lands among whoever the list shows", "const known = $derived(shown.filter((u) => (u.fact_count ?? 0) > 0));" in page)

print("\n== the empty card and the link picker, apart ==")
# They shared .mm-pick: the picker's `top: calc(100% + 6px)` pushed the "Pick someone" card out of the column once the
# column had a height of its own, and the card's rules had made the picker a padded block in the page.
check("the picker has class names of its own", '<div class="mm-link-pop unroll" data-link-picker' in page
      and 'class="mm-pick ' not in page.replace('class="mm-pick glass"', ""))
check("and nothing of a popover is left on the empty card", "top: calc(100% + 6px)" not in page)
check("it unrolls under its button, floated out of the scrolling column, and its clicks count as inside",
      'use:floatFrom={{ anchor: linkAnchor, up: false, align: "left", onaway: () => (linkOpen = false) }}' in page
      and 'use:unroll={".mm-link-find, .mm-link-row, .mm-link-none"}' in page
      and '!(e.target as HTMLElement).closest?.("[data-link-picker]")' in page)
check("floatFrom can line a list up with its box's left edge", 'align?: "left" | "right"' in read("webui/src/lib/floatfrom.ts"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
