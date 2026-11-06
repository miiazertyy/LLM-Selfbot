"""Chats across accounts, kept working.

  * The account picker's own menu was see-through: at 74% fill it relied on its blur to stay legible, and where the
    blur is not drawn (some webviews skip backdrop-filter outright) the inbox read straight through it.
  * The picker says how many are waiting on each account, and the closed picker how many on the other ones.
  * "All chats" shows every account's waiting list in one, each row marked with the account it was written to.
  * The sidebar says how many are waiting on Chats while another page is open.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra and not cond else ""))


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


css = read("webui/src/app.css")
lib = read("webui/src/lib/chats.ts")
chats = read("webui/src/pages/Chats.svelte")
app = read("webui/src/App.svelte")

print("== the menus read without their blur ==")
check("glass menus are filled enough to read over anything", "--float-fill: 95%;" in css)
check("and frosted ones a touch more", "--float-fill: 97%;" in css)
check("the reason is written down, so it is not tuned back", "filled enough to read WITHOUT the blur" in css)

print("\n== how many are waiting, per account ==")
check("counted from what the prefetch already keeps warm, for every account",
      "export const waitingByAccount = derived([chatCache, chatAccounts]" in lib)
check("an ignored person is not waiting", "filter((u) => !u.ignored).length" in lib)
check("an account since removed counts nothing", "for (const a of accounts) out[a.id]" in lib)
check("and one total, for the sidebar", "export const waitingTotal = derived(waitingByAccount" in lib)

print("\n== the picker ==")
check("each account says how many are waiting on it", "{@const n = waitingOn(a.id)}" in chats
      and '<span class="ch-waiting"' in chats)
check("the closed picker says how many wait on the OTHER accounts",
      "a.id === target ? 0 : waitingOn(a.id)" in chats and '<span class="ch-elsewhere"' in chats)
check("but not in All chats, where everyone is already on screen", "waitingElsewhere = $derived(allView ? 0" in chats)
check("All chats sits at the top of the picker", 'onclick={() => choose(ALL_CHATS)}' in chats
      and chats.index("choose(ALL_CHATS)") < chats.index("{#each accounts as a (a.id)}\n          {@const on"))
check("with the accounts' pictures clustered, in the square one picture takes", ".ch-stack { position: relative;" in chats
      and "width: 36px; height: 36px;" in chats)

print("\n== All chats ==")
check("what the list shows is apart from which account a conversation is with",
      'let view = $state("");' in chats and "const allView = $derived(view === ALL_CHATS && accounts.length > 1);" in chats)
check("every account's waiting list, each row keeping its account",
      "accounts.flatMap((a) => ($chatCache[a.id]?.users ?? []).map((u) => ({ ...u, acc: a.id })))" in chats)
check("rows are told apart by person AND account", "const keyOf = (u: Row): string => `${accOf(u)}:${u.id}`;" in chats
      and "{#each sec.rows as { u, st: s } (keyOf(u))}" in chats)
check("opening a row makes its account the one the conversation is with",
      "function openRow(u: Row)" in chats and "if (u.acc && u.acc !== target) {" in chats
      and "onclick={() => openRow(u)}" in chats)
check("who is open is the person and the account", "const isOpen = (u: Row) => u.id === selectedId && accOf(u) === target;" in chats)
check("replying, cancelling and ignoring go to the row's own account",
      "sendReply(accOf(u), u.id)" in chats and "cancelReply(accOf(u), u.id)" in chats
      and "toggleIgnore(accOf(u), personOf(u).id)" in chats and "ignorePerson(personOf(u), e, acc)" in chats)
check("each row is paused or not by its own account", "paused: ($chatCache[accOf(u)] ?? entry).paused" in chats)
check("drafts, typing and calls by the row's own account",
      "hasDraft(u.id, acc)" in chats and "$typingNow[convKey(acc, u.id)]" in chats and "callOf(u.id, acc)" in chats)
check("each row marked with the account it was written to", '<span class="ch-via"' in chats
      and "{@const via = allView ? accountOf(acc) : undefined}" in chats)
check("a row's picture fallback is its own platform's", "silhouette={platOfRow(u).silhouette}" in chats)
check("what belongs to one account stays with it: ignored, adding a friend, its requests",
      "{#if !allView}\n    <div class=\"relative\" data-ignored-panel>" in chats
      and "{#if !allView && (incoming.length || (friendsError && friendsSupported))}" in chats)
check("but Reply to all answers every account, since that is the point of seeing them together",
      "{#if !allView}\n    <Button kind={replyingAll" not in chats
      and "const replyTargets = $derived(" in chats)
check("and the answered conversations come from every account, each knowing whose it is",
      "allView ? [] : pastList.filter(" not in chats
      and "pastTargets.flatMap((t) => (pastBy[t] ?? []).map((c) => ({ ...c, acc: t })))" in chats)
check("a call on any account still shows, and opens on its account",
      "filter((c) => allView || c.target === target)" in chats and "if (c.target && c.target !== target) {" in chats)
check("the words of kept messages are not searched across accounts", "if (q.length < 2 || !t || allView) {" in chats)
check("stopped accounts are not asked, which would only wait out their timeout",
      "const answering = (list:" in chats and "answering(accounts).map(" in chats)
check("All chats is remembered when the tab is opened again",
      "export const chatsView = writable<string>(\"\");" in lib and "if (view) chatsView.set(view);" in chats
      and "} else if (was === ALL_CHATS && list.length > 1) {" in chats)
check("choosing an account leaves All chats", "if (id !== target || allView) switchTarget(id);" in chats
      and "target = id;\n    view = id;" in chats)

print("\n== the sidebar ==")
check("Chats says how many are waiting while another page is open",
      "key === \"chats\" && route !== key && !bg && !justDone ? $waitingTotal : 0" in app
      and '<span class="nav-waiting ml-auto"' in app)
check("and in the collapsed rail, on the icon's other corner from the attention dot",
      'class="nav-waiting is-rail"' in app and ".nav-waiting.is-rail {" in css and "bottom: -6px;" in css)
check("a big number stays small", '{waiting > 99 ? "99+" : waiting}' in app)


# ── Working from All chats, not just looking at it ──────────────────────────
# It showed who was waiting on every account and let you do nothing with them: Reply to all was hidden, and the
# conversations already answered were dropped, so the one view of everything was the one you could not work from.
print("\n== All chats can be worked from ==")
_page = (ROOT / "webui" / "src" / "pages" / "Chats.svelte").read_text(encoding="utf-8")
check("Reply to all is there too", "{#if !allView}\n    <Button kind={replyingAll" not in _page
      and "const replyTargets = $derived(" in _page)
check("  and it answers every account that has somebody waiting, each at its own pace",
      "Promise.all(replyTargets.map((t) => sendReplyAll(t)" in _page
      and 'allView ? accounts.filter((a) => ($chatCache[a.id]?.users ?? []).some((u) => !u.ignored))' in _page)
check("  Stop stops all of them", "for (const t of replyTargets) void stopReplyAll(t);" in _page)
check("  the count is all of them added up, not one account's",
      "parts.reduce((n, p) => n + p.done, 0)" in _page)
check("  and the button says how many accounts it would answer",
      "Reply to all (${replyTargets.length} accounts)" in _page)
check("the answered conversations are there, from every account",
      "const pastTargets = $derived(allView ? accounts.map((a) => a.id)" in _page
      and "pastTargets.flatMap((t) => (pastBy[t] ?? []).map((c) => ({ ...c, acc: t })))" in _page)
check("  each row saying whose it is", "{@const pacc = allView ? accountOf(pastAcc(c)) : undefined}" in _page)
check("  and opening one opens it on its own account, not whichever was selected",
      "const acc = pastAcc(c);" in _page and "if (acc && acc !== target) {" in _page)
check("  one still waiting on its own account is not called answered on another",
      "!users.some((u) => u.id === c.id && (!allView || accOf(u) === pastAcc(c)))" in _page)


# ── Working from All chats, not just looking at it ──────────────────────────
# It showed who was waiting on every account and let you do nothing with them: Reply to all was hidden, and the
# conversations already answered were dropped, so the one view of everything was the one you could not work from.
print("\n== All chats can be worked from ==")
_page = (ROOT / "webui" / "src" / "pages" / "Chats.svelte").read_text(encoding="utf-8")
check("Reply to all is there too", "{#if !allView}\n    <Button kind={replyingAll" not in _page
      and "const replyTargets = $derived(" in _page)
check("  and it answers every account that has somebody waiting, each at its own pace",
      "Promise.all(replyTargets.map((t) => sendReplyAll(t)" in _page
      and 'allView ? accounts.filter((a) => ($chatCache[a.id]?.users ?? []).some((u) => !u.ignored))' in _page)
check("  Stop stops all of them", "for (const t of replyTargets) void stopReplyAll(t);" in _page)
check("  the count is all of them added up, not one account's",
      "parts.reduce((n, p) => n + p.done, 0)" in _page)
check("  and the button says how many accounts it would answer",
      "Reply to all (${replyTargets.length} accounts)" in _page)
check("the answered conversations are there, from every account",
      "const pastTargets = $derived(allView ? accounts.map((a) => a.id)" in _page
      and "pastTargets.flatMap((t) => (pastBy[t] ?? []).map((c) => ({ ...c, acc: t })))" in _page)
check("  each row saying whose it is", "{@const pacc = allView ? accountOf(pastAcc(c)) : undefined}" in _page)
check("  and opening one opens it on its own account, not whichever was selected",
      "const acc = pastAcc(c);" in _page and "if (acc && acc !== target) {" in _page)
check("  one still waiting on its own account is not called answered on another",
      "!users.some((u) => u.id === c.id && (!allView || accOf(u) === pastAcc(c)))" in _page)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("failed: " + "; ".join(FAIL))
sys.exit(1 if FAIL else 0)
