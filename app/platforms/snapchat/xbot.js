/**
 * X, driven through x.com in the account's own Chrome: signing in through its own flow, its messages, what people
 * say to it in public, its own posts, and the likes, reposts and follows it does out there.
 *
 * X's API is paid and its free tier can neither read a mention nor send a message, so the page is read and used the
 * way a person would. Unlike Instagram's pages, X's are full of test hooks: data-testid is the one thing its app
 * keeps across redesigns, and it kept the old names through the rename - the box to write in is still
 * "tweetTextarea_0" and the repost button still "retweet", while the words on them changed. So every marker here
 * goes through the hook and only falls back to the words, and the words are matched in both the new wording and the
 * old. selectorHealth() says which markers still find anything.
 *
 * Two things make X harder than Instagram rather than easier:
 *
 *   Every list it draws is virtualized. A row scrolled past is taken off the page, so a list is never read in one
 *   go: it is read a window at a time, scrolled, read again, and merged on each row's own id. Nothing found in one
 *   pass may be held and clicked in the next either - the element is gone by then - so anything to be pressed is
 *   found again by its id in the same breath as the press.
 *
 *   Both boxes to type in are Draft.js editors. Setting .value or the text inside one changes what is drawn and
 *   nothing else: the editor's own state stays empty, the button stays disabled, and the send does nothing. Only
 *   real typing works, which is what typeInto does, and it checks the button woke up before it presses it.
 */
import fs from "fs";
import path from "path";
import { launchBrowser, delay, typeDelay, persona, showWindow, hideWindow } from "./browser.js";
// The six digits from a 2FA key are RFC 6238 and nobody's in particular; instagrambot.js already has them, and one
// copy is better than two. Imported here rather than where it is used, so a missing file is a loud start, not a
// quiet failure halfway through a sign-in.
import { totp } from "./instagrambot.js";

export const HOME = "https://x.com/";

/**
 * Everything looked for on the page. Each is a list: the hook first, then whatever else has stood in for it.
 * Grouped as the pages are.
 */
export const SEL = {
  // ── Signing in (/i/flow/login) ──
  // One box at a time in a dialog: the handle, then the password, then whatever X decided to ask. Every step's box
  // and its Next carry the flow's own hooks, which is the only steady thing about it.
  loginUser: ['input[autocomplete="username"]', 'input[name="text"]', '[data-testid="ocfEnterTextTextInput"]'],
  loginPassword: ['input[name="password"]', 'input[autocomplete="current-password"]', 'input[type="password"]'],
  loginNext: ['[data-testid="ocfEnterTextNextButton"]', '[data-testid="LoginForm_Login_Button"]'],
  loginSubmit: ['[data-testid="LoginForm_Login_Button"]'],
  // The "unusual login activity" step and the 2FA step share a box; what the dialog says tells them apart.
  challengeInput: ['[data-testid="ocfEnterTextTextInput"]', 'input[name="text"]',
                   'input[autocomplete="one-time-code"]', 'input[inputmode="numeric"]'],
  loginError: ['[data-testid="error-detail"]', 'div[role="alert"]'],
  // Signed out, x.com is a wall and nothing else: this is what being out looks like.
  loggedOut: ['[data-testid="loginButton"]', '[data-testid="signupButton"]', '[data-testid="login"]',
              'a[href="/i/flow/login"]'],
  // The ways in it offers that this account never uses, pressed by accident otherwise.
  ssoButtons: ['[data-testid="google_sign_in_container"]', '[data-testid="apple_sign_in_button"]'],

  // ── The app's shell: what being in looks like ──
  loggedIn: ['[data-testid="SideNav_AccountSwitcher_Button"]', '[data-testid="AppTabBar_Home_Link"]',
             '[data-testid="SideNav_NewTweet_Button"]'],
  primary: ['[data-testid="primaryColumn"]'],
  accountSwitcher: ['[data-testid="SideNav_AccountSwitcher_Button"]'],
  // Every row of every list X draws: the timeline, the notifications, the messages, the people lists. These are
  // the ones taken off the page as they scroll by.
  cell: ['[data-testid="cellInnerDiv"]'],
  // What X puts up on its own: the "show N posts" pill, its little black bar, an empty page, a broken one.
  pill: ['[data-testid="pillLabel"]'],
  toast: ['[data-testid="toast"]'],
  emptyState: ['[data-testid="emptyState"]', '[data-testid="empty_state_header_text"]'],
  errorDetail: ['[data-testid="error-detail"]'],
  // Its own sheets (delete a post, undo a repost, leave a conversation).
  confirm: ['[data-testid="confirmationSheetConfirm"]'],
  sheetDialog: ['div[role="dialog"]'],

  // ── A post, wherever it is drawn ──
  tweet: ['article[data-testid="tweet"]', '[data-testid="tweet"]'],
  tweetText: ['[data-testid="tweetText"]'],
  // Who wrote it. The block holds the shown name and the @handle; the handle is read off the link, not the words,
  // because a shown name can be anything, another @handle included.
  userName: ['[data-testid="User-Name"]'],
  // Its own address, and with it its number and its real moment: X puts a <time datetime> inside the permalink, so
  // a post's moment is never guessed from "2h" the way the other platforms' are.
  statusLink: ['a[href*="/status/"]'],
  socialContext: ['[data-testid="socialContext"]'],
  tweetPhoto: ['[data-testid="tweetPhoto"]'],
  tweetVideo: ['[data-testid="videoPlayer"]', '[data-testid="videoComponent"]'],
  card: ['[data-testid="card.wrapper"]'],
  // Its buttons. X kept the old names in the hooks and changed only the words on them.
  like: ['[data-testid="like"]'],
  unlike: ['[data-testid="unlike"]'],
  repost: ['[data-testid="retweet"]'],
  unrepost: ['[data-testid="unretweet"]'],
  repostConfirm: ['[data-testid="retweetConfirm"]'],
  unrepostConfirm: ['[data-testid="unretweetConfirm"]'],
  reply: ['[data-testid="reply"]'],
  caret: ['[data-testid="caret"]'],
  menuItem: ['div[role="menuitem"]'],

  // ── Writing a post ──
  // A Draft.js editor, not a box with a value. _0 is the post; a thread's second is _1, its third _2, which is how
  // a thread is written.
  composer: ['[data-testid="tweetTextarea_0"]', 'div[contenteditable="true"][data-testid^="tweetTextarea_"]'],
  postButton: ['[data-testid="tweetButton"]', '[data-testid="tweetButtonInline"]'],
  addToThread: ['[data-testid="addButton"]'],
  composerFile: ['[data-testid="fileInput"]', 'input[type="file"]'],
  composerOpen: ['[data-testid="SideNav_NewTweet_Button"]', 'a[href="/compose/post"]', 'a[href="/compose/tweet"]'],

  // ── Messages (/messages) ──
  // X draws these as two panes: the conversations down the left, the open one on the right. Both are virtualized,
  // and the open one grows upwards - its newest at the bottom, older ones loaded on the way up - so a conversation
  // is read from its bottom and scrolled up in steps.
  conversation: ['[data-testid="conversation"]'],
  dmScroller: ['[data-testid="DmScrollerContainer"]', 'div[data-viewportview="true"]'],
  messageEntry: ['[data-testid="messageEntry"]'],
  dmComposer: ['[data-testid="dmComposerTextInput"]',
               '[data-testid="dmComposerTextInputContainer"] div[contenteditable="true"]'],
  dmSend: ['[data-testid="dmComposerSendButton"]'],
  dmFile: ['[data-testid="dmComposerFileInput"]', 'input[type="file"]'],
  dmTyping: ['[data-testid="DmActivity"]', '[data-testid="typingIndicator"]'],
  dmRequests: ['a[href="/messages/requests"]', 'a[href*="/messages/requests"]'],
  // Reacting to a message: X shows the button only while the pointer is over it, and its picker's search takes any
  // emoji there is, which is why the bridge's row for X says any_reaction.
  dmReact: ['[data-testid="messageEntryReaction"]', '[role="button"][aria-label*="React" i]'],
  emojiSearch: ['input[placeholder*="Search emojis" i]', 'input[type="text"][role="combobox"]'],
  emojiOption: ['[data-testid="emoji"]', '[role="option"]'],

  // ── People ──
  // A person's row in any list, and the Follow button on it, which X names for their account number:
  // "<id>-follow" when it is not following them and "<id>-unfollow" when it is. That ending is the one sure way to
  // tell Follow from Following without reading the word on the button.
  userCell: ['[data-testid="UserCell"]'],
  follow: ['[data-testid$="-follow"]'],
  unfollow: ['[data-testid$="-unfollow"]'],
  userDescription: ['[data-testid="UserDescription"]'],
  // Its own counts have no hooks at all: they are the words inside the links to those pages.
  followersLink: ['a[href$="/verified_followers"]', 'a[href$="/followers"]'],
  followingLink: ['a[href$="/following"]'],
  userAvatar: ['[data-testid^="UserAvatar-Container-"]'],

  // ── What is said to it in public ──
  notification: ['[data-testid="notification"]'],

  // ── The checks X puts up ──
  // Arkose is its sliding puzzle, in a frame of its own. /account/access is the page of an account it has locked.
  captcha: ['iframe[src*="arkoselabs"]', 'iframe[id^="arkose"]', '#arkose', 'iframe[src*="funcaptcha"]',
            'iframe[title*="challenge" i]'],
  emptyHeader: ['[data-testid="empty_state_header_text"]'],
};

/** Words matched where there is no hook. Both the word X uses now and the one it used before. */
const SAY = {
  next: /^next$/i,
  logIn: /^(log in|sign in)$/i,
  post: /^(post|tweet|reply)$/i,
  repost: /^(repost|retweet)$/i,
  undoRepost: /^(undo repost|undo retweet)$/i,
  follow: /^(follow|follow back)$/i,
  accept: /^accept$/i,
  notNow: /^(not now|maybe later|skip for now|dismiss|close|got it)$/i,
  cookies: /^(accept all cookies|refuse non-essential cookies|accept all)$/i,
};

/** What X says when it is unhappy, each turned into one plain line. */
export const WARNINGS = [
  [/over the daily limit for sending (posts|tweets)/i, "X says this account has posted as much as it may today"],
  [/you are over the daily limit for sending messages/i,
   "X says this account has sent as many messages as it may today"],
  [/you are unable to follow more people/i, "X will not let this account follow anyone else for now"],
  [/caught in our automated systems|flagged as automated|looks like it might be automated/i,
   "X has flagged this account as automated"],
  [/rate limit|too many requests/i, "X asked it to wait before doing that again"],
  [/you cannot send messages to|does not allow|not accepting messages/i,
   "X does not let this account message them"],
  [/your account has been locked/i, "X has locked this account: a person has to unlock it"],
  [/your account is suspended|account suspended/i, "X has suspended this account"],
  [/this post is unavailable|post not found|hasn.t sent any posts/i, "That post is not on X any more"],
  [/something went wrong|try again/i, "X did not take it and asked for another go"],
];

export function warningReason(text) {
  const t = String(text || "");
  for (const [re, said] of WARNINGS) if (re.test(t)) return said;
  return "";
}

// ── Who is who ───────────────────────────────────────────────────────────────

const HANDLE = /^[a-z0-9_]{1,15}$/;
/** X's own pages, which are not people. */
const RESERVED = new Set(["home", "explore", "notifications", "messages", "i", "settings", "compose", "intent",
                          "search", "hashtag", "login", "logout", "signup", "about", "tos", "privacy", "download",
                          "jobs", "status", "share", "account", "topics", "lists", "bookmarks", "communities",
                          "premium", "following", "followers", "verified_followers", "personalization"]);

/** The handle as X would write it, or "". Takes an @, a bare name, or a link to a profile. */
export function cleanHandle(name) {
  let h = String(name || "").trim().toLowerCase();
  const m = h.match(/^(?:https?:\/\/)?(?:www\.|mobile\.)?(?:x|twitter)\.com\/([a-z0-9_]{1,15})\/?(?:\?.*)?$/);
  if (m) h = m[1];
  h = h.replace(/^@/, "");
  return HANDLE.test(h) && !RESERVED.has(h) ? h : "";
}

/** A person's chat id: "x_" and their handle. Underscores are legal in a handle, so nothing is changed. */
export function chatIdFor(handle) {
  const h = cleanHandle(handle);
  return h ? `x_${h}` : "";
}

/** The handle behind a chat id; "" for a group, whose id carries no handle. */
export function handleOf(chatId) {
  const s = String(chatId || "");
  // "xg_" first: an underscore is legal in a handle, so only a group has no letter before it.
  if (s.startsWith("xg_")) return "";
  return s.startsWith("x_") ? s.slice(2) : "";
}

/** A group message's chat id: "xg_" and the conversation's own number. */
export function groupIdFor(conversationId) {
  const id = String(conversationId || "").replace(/[^0-9-]/g, "");
  return /^\d[\d-]{3,40}$/.test(id) ? `xg_${id.replace(/-/g, "")}` : "";
}

export const CHAT_ID = /^(x_[a-z0-9_]{1,15}|xg_\d{4,30})$/;

/** The handle a link points at, or "": "/theo_wav" and "https://x.com/theo_wav/status/1" both give "theo_wav". */
export function handleFromHref(href) {
  const s = String(href || "");
  const m = s.match(/^(?:https?:\/\/(?:www\.|mobile\.)?(?:x|twitter)\.com)?\/([A-Za-z0-9_]{1,15})(?:[/?#]|$)/);
  return m ? cleanHandle(m[1]) : "";
}

/** The number of the post a link points at, or "". */
export function statusIdFromHref(href) {
  const m = String(href || "").match(/\/status\/(\d{5,25})/);
  return m ? m[1] : "";
}

/** The conversation a messages link points at, or "". */
export function conversationIdFromHref(href) {
  const m = String(href || "").match(/\/messages\/([0-9-]{4,45})/);
  return m ? m[1] : "";
}

/** A post's address from its handle and number, as X writes it. */
export const postUrl = (handle, id) => `https://x.com/${handle || "i"}/status/${id}`;

// ── Read off the page ────────────────────────────────────────────────────────
// Each of these runs inside the page, so it stands alone: no closures, everything through its arguments. They are
// exported so the tests can run them against a saved copy of one of X's pages, which is the only way to check
// them without an account (tests/x_logic.mjs).

/** The conversations mounted in the list right now. */
export function readConversationsInPage(sel) {
  const pick = (sels, where = document) => {
    for (const s of sels) {
      const el = where.querySelector(s);
      if (el) return el;
    }
    return null;
  };
  const pickAll = (sels, where = document) => {
    for (const s of sels) {
      const all = where.querySelectorAll(s);
      if (all.length) return [...all];
    }
    return [];
  };
  return pickAll(sel.conversation).map((row) => {
    // The row may be the link itself, hold one, or sit inside one: X has drawn it each of those ways.
    const link = (row.matches('a[href*="/messages/"]') && row)
      || row.querySelector('a[href*="/messages/"]')
      || row.closest('a[href*="/messages/"]');
    const href = link ? link.getAttribute("href") || "" : "";
    const who = [...row.querySelectorAll('a[href^="/"]')]
      .map((a) => a.getAttribute("href") || "")
      .filter((h) => /^\/[A-Za-z0-9_]{1,15}$/.test(h))
      .map((h) => h.slice(1));
    const img = row.querySelector("img[src]");
    const text = (row.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean);
    // X marks an unread conversation with a dot of its own; failing that, the row's own aria-label says so.
    const label = (row.getAttribute("aria-label") || "").toLowerCase();
    const unread = !!row.querySelector('[data-testid="cellInnerDiv"] [aria-label*="nread" i]')
      || /unread/.test(label)
      || !!row.querySelector('div[style*="background-color: rgb(29, 155, 240)"]');
    return {
      conversation: (href.match(/\/messages\/([0-9-]{4,45})/) || [, ""])[1],
      handles: [...new Set(who)],
      name: text[0] || "",
      preview: text.length > 2 ? text[text.length - 1] : "",
      avatar: img ? img.src : "",
      group: who.length > 1,
      unread,
      typing: !!pick(sel.dmTyping, row),
    };
  });
}

/** The open conversation's mounted messages, oldest first as the page draws them. */
export function readDmInPage(sel, ownHandle) {
  const pickAll = (sels, where = document) => {
    for (const s of sels) {
      const all = where.querySelectorAll(s);
      if (all.length) return [...all];
    }
    return [];
  };
  const pane = (() => {
    for (const s of sel.dmScroller) {
      const el = document.querySelector(s);
      if (el) return el;
    }
    return document.querySelector('[data-testid="primaryColumn"]') || document.body;
  })();
  const mid = pane.getBoundingClientRect().left + pane.getBoundingClientRect().width / 2;
  const rows = pickAll(sel.messageEntry, pane);
  const out = [];
  rows.forEach((row, i) => {
    const box = row.getBoundingClientRect();
    if (!box.width) return;
    // X draws its own messages to the right of the pane's middle and theirs to the left. In a group, the avatar
    // inside the row says whose it is, which is the cross-check.
    const mine = box.left + box.width / 2 > mid;
    const bits = (row.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean);
    const timeEl = row.querySelector("time[datetime]")
      || (row.nextElementSibling && row.nextElementSibling.querySelector("time[datetime]"));
    const at = timeEl ? Date.parse(timeEl.getAttribute("datetime") || "") || 0 : 0;
    const links = [...row.querySelectorAll("a[href]")].map((a) => a.href)
      .filter((h) => /^https?:/.test(h) && !/\/i\/status\//.test(h));
    const img = row.querySelector('img[src*="media"], img[alt="Image"]');
    const video = row.querySelector("video");
    const card = row.querySelector('[data-testid="card.wrapper"]');
    // The words, without the time and the "Seen" the row also holds. X draws those inline, so they come back on
    // the same line as the message rather than on one of their own: taken off the end, not filtered out as lines.
    const text = bits
      .filter((b) => !/^\d{1,2}:\d{2}(\s?[AP]M)?$/i.test(b) && b !== "Seen")
      .join(" ")
      .replace(/\s*\d{1,2}:\d{2}(\s?[AP]M)?\s*$/i, "")
      .replace(/\s*Seen\s*$/, "")
      .trim();
    let kind = "";
    if (video) kind = "video";
    else if (img) kind = "photo";
    else if (card && !text) kind = "link";
    const author = (() => {
      const a = row.querySelector('[data-testid^="UserAvatar-Container-"]');
      const id = a ? (a.getAttribute("data-testid") || "").replace("UserAvatar-Container-", "") : "";
      return id && id.toLowerCase() !== String(ownHandle || "").toLowerCase() ? id : "";
    })();
    const reactions = [...row.querySelectorAll('[data-testid="messageEntryReactions"] img[alt], '
                                               + '[data-testid="messageEntryReactions"] span')]
      .map((e) => (e.getAttribute("alt") || e.textContent || "").trim())
      .filter((s) => s && s.length <= 4);
    out.push({ mine, text, kind, at, links, reactions, idx: i, author, day: "" });
  });
  return out;
}

/** Every post mounted right now, in the order the page draws them. */
export function readTweetsInPage(sel, ownHandle) {
  const pickAll = (sels, where = document) => {
    for (const s of sels) {
      const all = where.querySelectorAll(s);
      if (all.length) return [...all];
    }
    return [];
  };
  const me = String(ownHandle || "").toLowerCase();
  return pickAll(sel.tweet).map((art) => {
    const box = art.getBoundingClientRect();
    const links = [...art.querySelectorAll('a[href*="/status/"]')];
    const permalink = links.find((a) => a.querySelector("time[datetime]")) || links[0] || null;
    const href = permalink ? permalink.getAttribute("href") || "" : "";
    const id = (href.match(/\/status\/(\d{5,25})/) || [, ""])[1];
    const handle = (href.match(/^\/([A-Za-z0-9_]{1,15})\//) || [, ""])[1].toLowerCase();
    const timeEl = permalink ? permalink.querySelector("time[datetime]") : art.querySelector("time[datetime]");
    const at = timeEl ? Date.parse(timeEl.getAttribute("datetime") || "") || 0 : 0;
    const nameBlock = art.querySelector('[data-testid="User-Name"]');
    const name = nameBlock ? (nameBlock.innerText || "").split("\n")[0].trim() : "";
    const textEl = art.querySelector('[data-testid="tweetText"]');
    const text = textEl ? (textEl.innerText || "").trim() : "";
    const avatarImg = art.querySelector('[data-testid^="UserAvatar-Container-"] img[src]');
    const media = [];
    for (const p of art.querySelectorAll('[data-testid="tweetPhoto"] img[src]')) media.push({ kind: "photo", url: p.src });
    if (art.querySelector('[data-testid="videoPlayer"], [data-testid="videoComponent"]')) media.push({ kind: "video", url: "" });
    const ctx = art.querySelector('[data-testid="socialContext"]');
    const ctxText = ctx ? (ctx.innerText || "").trim() : "";
    const count = (which) => {
      const b = art.querySelector(`[data-testid="${which}"]`);
      if (!b) return 0;
      const said = (b.getAttribute("aria-label") || "").match(/([\d,.]+)/);
      return said ? parseInt(said[1].replace(/[,.]/g, ""), 10) || 0 : 0;
    };
    // "Replying to @someone" sits above a reply and has no hook of its own. The people it names are links to
    // them, and those are what say it is a reply - not X's words, which are in whatever language it is in.
    const replyTo = [...art.querySelectorAll('a[href^="/"]')]
      .map((a) => a.getAttribute("href") || "")
      .filter((h) => /^\/[A-Za-z0-9_]{1,15}$/.test(h) && h.slice(1).toLowerCase() !== handle)
      .map((h) => h.slice(1));
    return {
      id, url: id ? `https://x.com/${handle || "i"}/status/${id}` : "", handle, name, at, text,
      avatar: avatarImg ? avatarImg.src : "",
      mine: !!handle && handle === me,
      reply: replyTo.length > 0,
      replyTo: replyTo.slice(0, 4),
      repostOf: /reposted|retweeted/i.test(ctxText) ? ctxText : "",
      media,
      liked: !!art.querySelector('[data-testid="unlike"]'),
      reposted: !!art.querySelector('[data-testid="unretweet"]'),
      counts: { replies: count("reply"), reposts: count("retweet"), likes: count("like") },
      top: Math.round(box.top + window.scrollY), height: Math.round(box.height),
    };
  }).filter((t) => t.id);
}

/** The people in whatever list is on screen. */
export function readUserCellsInPage(sel) {
  const pickAll = (sels, where = document) => {
    for (const s of sels) {
      const all = where.querySelectorAll(s);
      if (all.length) return [...all];
    }
    return [];
  };
  return pickAll(sel.userCell).map((cell) => {
    const links = [...cell.querySelectorAll('a[href^="/"]')]
      .map((a) => a.getAttribute("href") || "")
      .filter((h) => /^\/[A-Za-z0-9_]{1,15}$/.test(h));
    const handle = links.length ? links[0].slice(1).toLowerCase() : "";
    const img = cell.querySelector("img[src]");
    const bioEl = cell.querySelector('[data-testid="UserDescription"]');
    const followBtn = cell.querySelector('[data-testid$="-follow"]');
    const unfollowBtn = cell.querySelector('[data-testid$="-unfollow"]');
    const lines = (cell.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean);
    return {
      handle,
      name: lines[0] || handle,
      avatar: img ? img.src : "",
      bio: bioEl ? (bioEl.innerText || "").trim() : "",
      following: !!unfollowBtn,
      followId: (followBtn || unfollowBtn || {}).getAttribute
        ? (followBtn || unfollowBtn).getAttribute("data-testid") : "",
    };
  }).filter((p) => p.handle);
}

/** Whoever's profile page is open: their counts, their words, and whether X lets anyone see them. */
export function profileInPage(sel) {
  const num = (href) => {
    const a = document.querySelector(`a[href$="${href}"]`);
    if (!a) return 0;
    const said = (a.innerText || "").replace(/\s/g, "");
    const m = said.match(/([\d.,]+)\s*([KMB])?/i);
    if (!m) return 0;
    const base = parseFloat(m[1].replace(/,/g, ""));
    const mult = { k: 1e3, m: 1e6, b: 1e9 }[(m[2] || "").toLowerCase()] || 1;
    return Math.round(base * mult);
  };
  const here = location.pathname.split("/").filter(Boolean)[0] || "";
  const bioEl = document.querySelector('[data-testid="UserDescription"]');
  const nameEl = document.querySelector('[data-testid="UserName"]');
  const avatar = document.querySelector(`[data-testid^="UserAvatar-Container-"] img[src]`);
  const body = document.body.innerText || "";
  return {
    handle: here.toLowerCase(),
    name: nameEl ? (nameEl.innerText || "").split("\n")[0].trim() : "",
    bio: bioEl ? (bioEl.innerText || "").trim() : "",
    avatar: avatar ? avatar.src : "",
    followers: num("/verified_followers") || num("/followers"),
    following: num("/following"),
    verified: !!document.querySelector('[data-testid="icon-verified"]'),
    protected: /these posts are protected|account.s posts are protected/i.test(body),
    exists: !/this account doesn.t exist|account doesn.t exist/i.test(body),
  };
}

/** Where a scroller has got to, so a read in steps knows when it has reached the end. */
export function scrollStateInPage(sel) {
  let pane = null;
  for (const s of sel.dmScroller) {
    const el = document.querySelector(s);
    if (el && el.scrollHeight > el.clientHeight) { pane = el; break; }
  }
  if (!pane) {
    return { y: Math.round(window.scrollY), height: Math.round(document.body.scrollHeight),
             view: window.innerHeight, atBottom: window.scrollY + window.innerHeight >= document.body.scrollHeight - 50,
             atTop: window.scrollY <= 5, own: false };
  }
  return { y: Math.round(pane.scrollTop), height: Math.round(pane.scrollHeight), view: pane.clientHeight,
           atBottom: pane.scrollTop + pane.clientHeight >= pane.scrollHeight - 50, atTop: pane.scrollTop <= 5,
           own: true };
}

/** A button named by what it says, pressed. */
export function clickSaidInPage(source, flags) {
  const re = new RegExp(source, flags);
  const all = [...document.querySelectorAll('div[role="button"], button, a[role="link"], [role="menuitem"]')];
  for (const el of all) {
    const said = (el.innerText || el.getAttribute("aria-label") || "").trim();
    if (said && said.length <= 40 && re.test(said) && el.offsetParent !== null) {
      el.click();
      return said;
    }
  }
  return "";
}

// ── The bot ──────────────────────────────────────────────────────────────────

export default class XBot {
  constructor({ account = 1, handle = "", dataDir, locale = "en-US", timezone = "", tag = "[X]" } = {}) {
    this.account = account;
    this.handle = cleanHandle(handle);
    this.dataDir = dataDir;
    this.locale = locale;
    this.timezone = timezone;
    this.tag = tag;
    this.browser = null;
    this.page = null;        // the messages
    this.side = null;        // its own posts and what is said under them
    this.out = null;         // going out: someone's profile, a post, posting
    this.hidden = false;
    this.health = {};
    this.gone = false;
  }

  get lang() {
    return String(this.locale || "en-US").split("-")[0];
  }

  log(...args) {
    console.log(this.tag, ...args);
  }

  // ── The browser ────────────────────────────────────────────────────────────

  async launch({ profileDir, hidden = false, proxy = "", args = [] }) {
    this.hidden = hidden;
    this.launchOpts = { profileDir, hidden, proxy, args };
    this.gone = false;
    this.browser = await launchBrowser({ profileDir, hidden, locale: this.locale, proxy, args });
    this.browser.on("disconnected", () => { this.gone = true; });
    const pages = await this.browser.pages();
    this.page = pages[0] || (await this.browser.newPage());
    await this.dress(this.page);
    return this.page;
  }

  /** One person: the persona's language and clock, a proxy's login, and the page's own pop-ups answered. */
  async dress(page) {
    if (this.browser?.__proxyAuth) {
      try { await page.authenticate(this.browser.__proxyAuth); } catch { /* none needed */ }
    }
    await persona(page, { locale: this.locale, timezone: this.timezone });
    page.on("dialog", async (d) => {
      try { await (d.type() === "beforeunload" ? d.accept() : d.dismiss()); } catch { /* gone */ }
    });
  }

  /** A tab behind the first one, made to behave as one in front: Chrome draws nothing behind. */
  async awake(page) {
    try {
      const s = await page.target().createCDPSession();
      await s.send("Emulation.setFocusEmulationEnabled", { enabled: true });
    } catch { /* an older Chrome: DOM clicks still work */ }
  }

  async newTab() {
    const page = await this.browser.newPage();
    await this.dress(page);
    await this.awake(page);
    try { await this.page.bringToFront(); } catch { /* fine */ }
    return page;
  }

  usable(page) {
    try {
      return !!page && !page.isClosed() && !page.mainFrame().detached;
    } catch {
      return false;
    }
  }

  async sidePage() {
    if (this.usable(this.side)) return this.side;
    const old = this.side;
    this.side = await this.newTab();
    if (old && !old.isClosed()) await old.close().catch(() => {});
    return this.side;
  }

  async outPage() {
    if (this.usable(this.out)) return this.out;
    const old = this.out;
    this.out = await this.newTab();
    if (old && !old.isClosed()) await old.close().catch(() => {});
    return this.out;
  }

  /** The browser still there and its messages tab usable. */
  async ensure() {
    if (this.gone || !this.browser) return "gone";
    if (!this.usable(this.page)) {
      try {
        this.page = await this.browser.newPage();
        await this.dress(this.page);
      } catch {
        return "gone";
      }
      return "new";
    }
    return "ok";
  }

  /**
   * Go somewhere and wait for the app to have drawn itself. Never networkidle: x.com keeps streams open and never
   * goes idle, so waiting for that times out every time.
   */
  async goto(url, page = this.page) {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 }).catch(() => {});
    await page.waitForSelector(SEL.primary.join(","), { timeout: 20000 }).catch(() => {});
    await delay(400 + Math.random() * 600);
    await this.dismissDialogs(page);
  }

  /** The cookie bar, the "see new posts" pill, and whatever X is nagging about, out of the way. */
  async dismissDialogs(page = this.page) {
    try {
      await page.evaluate(clickSaidInPage, SAY.cookies.source, SAY.cookies.flags);
      await page.evaluate((sel) => {
        // The pill reorders the timeline when pressed, so it is only ever dismissed, never used mid-read.
        for (const s of sel.toast) document.querySelectorAll(s).forEach((e) => e.remove());
      }, SEL);
      // "Not now" only inside a dialog of X's own: elsewhere it is part of a page.
      await page.evaluate((src, flags) => {
        const re = new RegExp(src, flags);
        for (const dlg of document.querySelectorAll('div[role="dialog"]')) {
          for (const b of dlg.querySelectorAll('div[role="button"], button')) {
            const said = (b.innerText || "").trim();
            if (said && said.length <= 30 && re.test(said)) { b.click(); return; }
          }
        }
      }, SAY.notNow.source, SAY.notNow.flags);
    } catch { /* nothing in the way */ }
  }

  // ── Who and where ──────────────────────────────────────────────────────────

  /** The cookies X gives a signed-in browser. */
  async hasSession() {
    try {
      const cookies = await this.page.cookies("https://x.com");
      return cookies.some((c) => c.name === "auth_token" && c.value);
    } catch {
      return false;
    }
  }

  async isLogged(page = this.page) {
    try {
      if (/\/i\/flow\/(login|signup)/.test(page.url())) return false;
      return await page.evaluate((sel) => {
        const any = (sels) => sels.some((s) => document.querySelector(s));
        return any(sel.loggedIn) && !any(sel.loggedOut);
      }, SEL);
    } catch {
      return false;
    }
  }

  async captchaShown(page = this.page) {
    try {
      return await page.evaluate((sel) => sel.captcha.some((s) => document.querySelector(s)), SEL);
    } catch {
      return false;
    }
  }

  /** X has suspended the account: its own word for it is on the page, not in a hook. */
  async suspended(page = this.page) {
    try {
      const body = await page.evaluate(() => document.body.innerText || "");
      return /account is suspended|account has been suspended/i.test(body);
    } catch {
      return false;
    }
  }

  /** X has locked the account, which is a different thing and ends on a page of its own. */
  async locked(page = this.page) {
    try {
      if (/\/account\/access/.test(page.url())) return true;
      const body = await page.evaluate(() => document.body.innerText || "");
      return /your account has been locked|we.ve temporarily limited/i.test(body);
    } catch {
      return false;
    }
  }

  /** What X is complaining about right now, in one plain line, or "". */
  async warning(page = this.page) {
    try {
      const said = await page.evaluate((sel) => {
        const bits = [];
        for (const s of [...sel.toast, ...sel.errorDetail]) {
          for (const e of document.querySelectorAll(s)) bits.push(e.innerText || "");
        }
        return bits.join(" \n ");
      }, SEL);
      return warningReason(said);
    } catch {
      return "";
    }
  }

  /** Which of its markers still find anything, so drift is seen before it becomes silence. */
  async selectorHealth(page = this.page) {
    const url = page.url();
    const want = ["primary", "loggedIn"];
    if (/\/messages/.test(url)) want.push("conversation");
    if (/\/messages\/[0-9-]+/.test(url)) want.push("dmComposer", "messageEntry");
    if (/\/notifications/.test(url)) want.push("tweet");
    try {
      const found = await page.evaluate((sel, names) => {
        const out = {};
        for (const name of names) out[name] = sel[name].some((s) => !!document.querySelector(s));
        return out;
      }, SEL, want);
      const missing = want.filter((n) => !found[n]);
      this.health = { matched: want.length - missing.length, missing, url };
      return this.health;
    } catch {
      return { matched: 0, missing: want, url };
    }
  }

  // ── Typing into a Draft.js box ─────────────────────────────────────────────

  /**
   * Type into one of X's editors. They are contenteditable with their own state behind them, so what is set on the
   * element is ignored: only real keys reach the editor. Emoji go through sendCharacter, which keyboard.type cannot
   * always manage.
   */
  async typeInto(page, el, text, { enter = false } = {}) {
    await el.click({ delay: 40 + Math.random() * 60 });
    await delay(120 + Math.random() * 200);
    for (const ch of Array.from(String(text || ""))) {
      if (ch === "\n") {
        await page.keyboard.down("Shift");
        await page.keyboard.press("Enter");
        await page.keyboard.up("Shift");
      } else if (ch.codePointAt(0) > 0xffff || /[←-⯿️‍]/.test(ch)) {
        // Anything outside the plain range: typed as one character rather than as keys.
        await page.keyboard.sendCharacter(ch);
      } else {
        await page.keyboard.type(ch, { delay: typeDelay() });
      }
    }
    if (enter) await page.keyboard.press("Enter");
  }

  async clearTyped(page) {
    await page.keyboard.down("Control");
    await page.keyboard.press("KeyA");
    await page.keyboard.up("Control");
    await page.keyboard.press("Backspace");
    await delay(120);
  }

  /** The first of a list of markers that is on the page, as a handle. */
  async first(page, sels) {
    for (const s of sels) {
      const el = await page.$(s).catch(() => null);
      if (el) return el;
    }
    return null;
  }

  // ── Reading lists that unmount as they scroll ──────────────────────────────

  /**
   * Read a virtualized list in steps and merge what each step saw, keyed by `idOf`. Stops when a step adds nothing,
   * at `steps` steps, or at `max` rows.
   */
  async readInSteps(page, reader, args, idOf, { steps = 3, max = 60, up = false } = {}) {
    const seen = new Map();
    for (let i = 0; i <= steps; i++) {
      const batch = await page.evaluate(reader, ...args).catch(() => []);
      const before = seen.size;
      for (const row of batch || []) {
        const id = idOf(row);
        if (id && !seen.has(id)) seen.set(id, row);
      }
      if (seen.size >= max) break;
      if (i && seen.size === before) break;                 // a step that found nothing new: the end
      if (i === steps) break;
      await page.evaluate((goUp, sel) => {
        let pane = null;
        for (const s of sel.dmScroller) {
          const el = document.querySelector(s);
          if (el && el.scrollHeight > el.clientHeight) { pane = el; break; }
        }
        const by = (pane ? pane.clientHeight : window.innerHeight) * 0.8 * (goUp ? -1 : 1);
        if (pane) pane.scrollBy(0, by);
        else window.scrollBy(0, by);
      }, up, SEL).catch(() => {});
      await delay(700 + Math.random() * 600);
    }
    return [...seen.values()].slice(0, max);
  }

  // ── Messages ───────────────────────────────────────────────────────────────

  async openInbox() {
    if (!/\/messages\/?$/.test(this.page.url())) await this.goto("https://x.com/messages", this.page);
    else await this.dismissDialogs(this.page);
  }

  /** The conversations, read in steps and merged. */
  async listThreads({ scrolls = 2 } = {}) {
    return this.readInSteps(this.page, readConversationsInPage, [SEL],
                            (r) => r.conversation || r.handles[0] || r.name, { steps: scrolls, max: 40 });
  }

  /** Open a conversation by its chat id. A person is opened by their handle, a group by its conversation. */
  async openChat(chatId, { conversation = "" } = {}) {
    const handle = handleOf(chatId);
    const id = conversation || (String(chatId).startsWith("xg_") ? String(chatId).slice(3) : "");
    if (id) {
      await this.goto(`https://x.com/messages/${id}`, this.page);
    } else if (handle) {
      // The address that opens (or starts) a conversation with one person.
      await this.goto(`https://x.com/messages/compose?recipient_id=${encodeURIComponent(handle)}`, this.page);
      if (!(await this.page.$(SEL.dmComposer.join(",")))) {
        // Compose did not take a handle: find them in the list instead.
        await this.openInbox();
        const rows = await this.listThreads({ scrolls: 3 });
        const row = rows.find((r) => r.handles.includes(handle));
        if (row?.conversation) await this.goto(`https://x.com/messages/${row.conversation}`, this.page);
        else return false;
      }
    } else {
      return false;
    }
    const box = await this.page.waitForSelector(SEL.dmComposer.join(","), { timeout: 12000 }).catch(() => null);
    return !!box;
  }

  /** The open conversation. `scrollUps` loads older messages first. */
  async readChat({ scrollUps = 0 } = {}) {
    if (scrollUps > 0) {
      await this.readInSteps(this.page, readDmInPage, [SEL, this.handle], (m) => `${m.idx}`,
                             { steps: scrollUps, max: 400, up: true });
      await this.page.evaluate((sel) => {
        for (const s of sel.dmScroller) {
          const el = document.querySelector(s);
          if (el && el.scrollHeight > el.clientHeight) { el.scrollTop = el.scrollHeight; return; }
        }
      }, SEL).catch(() => {});
      await delay(500);
    }
    const messages = await this.page.evaluate(readDmInPage, SEL, this.handle).catch(() => []);
    const header = await this.page.evaluate(() => {
      const links = [...document.querySelectorAll('[data-testid="primaryColumn"] a[href^="/"]')]
        .map((a) => a.getAttribute("href") || "")
        .filter((h) => /^\/[A-Za-z0-9_]{1,15}$/.test(h))
        .map((h) => h.slice(1));
      return { handles: [...new Set(links)].slice(0, 12) };
    }).catch(() => ({ handles: [] }));
    const conversation = conversationIdFromHref(this.page.url());
    return { conversation, handles: header.handles, messages: messages || [] };
  }

  /** Send what is typed. In a conversation Enter sends; the button is the fallback when it did not. */
  async sendText(text, { dryRun = false } = {}) {
    const box = await this.first(this.page, SEL.dmComposer);
    if (!box) return { ok: false, reason: "its box to write in is not there" };
    await this.typeInto(this.page, box, text);
    const ready = await this.page.evaluate((sel) => {
      const b = (() => {
        for (const s of sel.dmSend) { const el = document.querySelector(s); if (el) return el; }
        return null;
      })();
      return !b || b.getAttribute("aria-disabled") !== "true";
    }, SEL).catch(() => true);
    if (!ready) {
      await this.clearTyped(this.page);
      return { ok: false, reason: "what was typed did not reach X's box" };
    }
    if (dryRun) {
      await this.clearTyped(this.page);
      return { ok: true, dry: true };
    }
    await delay(250 + Math.random() * 400);
    await this.page.keyboard.press("Enter");
    await delay(600 + Math.random() * 500);
    const left = await this.page.evaluate((sel) => {
      for (const s of sel.dmComposer) {
        const el = document.querySelector(s);
        if (el) return (el.innerText || "").trim().length;
      }
      return 0;
    }, SEL).catch(() => 0);
    if (left) {
      const btn = await this.first(this.page, SEL.dmSend);
      if (btn) await btn.click().catch(() => {});
      await delay(600);
    }
    const said = await this.warning(this.page);
    if (said) return { ok: false, reason: said };
    // Confirm it landed: the last message of ours says what we sent.
    for (let i = 0; i < 10; i++) {
      const msgs = await this.page.evaluate(readDmInPage, SEL, this.handle).catch(() => []);
      const mine = (msgs || []).filter((m) => m.mine);
      const last = mine[mine.length - 1];
      if (last && String(text).trim().startsWith(last.text.trim().slice(0, 24)) && last.text.trim()) {
        return { ok: true };
      }
      await delay(600);
    }
    return { ok: true, unconfirmed: true };
  }

  async sendImage(filePath, { dryRun = false } = {}) {
    if (!fs.existsSync(filePath)) return { ok: false, reason: "that picture is not there any more" };
    if (dryRun) return { ok: true, dry: true };
    const input = await this.first(this.page, SEL.dmFile);
    if (!input) return { ok: false, reason: "X offered nowhere to attach it" };
    await input.uploadFile(filePath);
    await delay(1800 + Math.random() * 1200);
    await this.page.keyboard.press("Enter");
    await delay(1200);
    const said = await this.warning(this.page);
    return said ? { ok: false, reason: said } : { ok: true };
  }

  /** React to one message, by where it sits in the read that just happened. */
  async react(idx, emoji) {
    const rows = await this.page.$$(SEL.messageEntry[0]);
    const row = rows[idx];
    if (!row) return { ok: false, reason: "that message is not on the page any more" };
    await row.hover().catch(() => {});
    await delay(300 + Math.random() * 300);
    const btn = await this.first(this.page, SEL.dmReact);
    if (!btn) return { ok: false, reason: "X offered no way to react to it" };
    await btn.click().catch(() => {});
    await delay(500 + Math.random() * 400);
    const search = await this.first(this.page, SEL.emojiSearch);
    if (search) {
      await this.typeInto(this.page, search, emoji);
      await delay(600);
    }
    const picked = await this.page.evaluate((sel, want) => {
      for (const s of sel.emojiOption) {
        for (const el of document.querySelectorAll(s)) {
          const said = el.getAttribute("aria-label") || el.textContent || "";
          if (said.includes(want) || !want) { el.click(); return true; }
        }
      }
      return false;
    }, SEL, emoji).catch(() => false);
    await delay(500);
    return picked ? { ok: true } : { ok: false, reason: "that reaction was not among the ones it offers" };
  }

  /** The people asking to message it, from the requests page. */
  async messageRequests() {
    await this.goto("https://x.com/messages/requests", this.page);
    const rows = await this.readInSteps(this.page, readConversationsInPage, [SEL],
                                        (r) => r.conversation || r.name, { steps: 1, max: 20 });
    return rows.map((r) => ({
      name: r.name, username: r.handles[0] || "", avatar: r.avatar, preview: r.preview,
      id: r.conversation || r.handles[0] || r.name,
    }));
  }

  /** Accept a request, or leave it. */
  async answerRequest(want, accept) {
    await this.goto("https://x.com/messages/requests", this.page);
    const rows = await this.readInSteps(this.page, readConversationsInPage, [SEL],
                                        (r) => r.conversation || r.name, { steps: 1, max: 20 });
    const row = rows.find((r) => r.name === want || r.handles.includes(cleanHandle(want)) || r.conversation === want);
    if (!row?.conversation) return { ok: false, reason: "that request is not there any more" };
    await this.goto(`https://x.com/messages/${row.conversation}`, this.page);
    const said = await this.page.evaluate(clickSaidInPage,
                                          accept ? SAY.accept.source : "^(delete|leave conversation)$",
                                          accept ? SAY.accept.flags : "i");
    await delay(700);
    return said ? { ok: true } : { ok: false, reason: "X offered no way to answer it" };
  }

  // ── What people say to it in public ────────────────────────────────────────

  /** The @s on its notifications, newest first. */
  async mentions({ scrolls = 3 } = {}) {
    const page = await this.sidePage();
    await this.goto("https://x.com/notifications/mentions", page);
    const rows = await this.readInSteps(page, readTweetsInPage, [SEL, this.handle], (t) => t.id,
                                        { steps: scrolls, max: 40 });
    return rows.filter((t) => !t.mine && t.text);
  }

  /** The replies under its own recent posts. */
  async repliesToOwn({ posts = 3, scrolls = 2 } = {}) {
    const mine = await this.ownPosts(posts);
    const out = [];
    for (const post of mine) {
      const thread = await this.readThread(post.url, { scrolls });
      for (const t of thread) {
        if (!t.mine && t.id !== post.id && t.text) out.push({ ...t, under: post.url });
      }
    }
    return out;
  }

  /** A post and what is under it. */
  async readThread(url, { page = null, scrolls = 2 } = {}) {
    const p = page || (await this.sidePage());
    await this.goto(url, p);
    return this.readInSteps(p, readTweetsInPage, [SEL, this.handle], (t) => t.id, { steps: scrolls, max: 40 });
  }

  /** Answer a post in its own thread. */
  async replyTo(url, text, { dryRun = false, page = null } = {}) {
    const p = page || (await this.sidePage());
    await this.goto(url, p);
    const btn = await this.first(p, SEL.reply);
    if (!btn) return { ok: false, reason: "that post is not there any more" };
    await btn.click().catch(() => {});
    await delay(800 + Math.random() * 600);
    const box = await p.waitForSelector(SEL.composer.join(","), { timeout: 10000 }).catch(() => null);
    if (!box) return { ok: false, reason: "X did not open a box to answer in" };
    await this.typeInto(p, box, text);
    return this.pressPost(p, { dryRun });
  }

  // ── Posting ────────────────────────────────────────────────────────────────

  /** Press the button that puts a post up, once the words are in. Enter never posts here, so it is the button. */
  async pressPost(page, { dryRun = false } = {}) {
    const ready = await page.evaluate((sel) => {
      for (const s of sel.postButton) {
        const b = document.querySelector(s);
        if (b) return b.getAttribute("aria-disabled") !== "true";
      }
      return false;
    }, SEL).catch(() => false);
    if (!ready) {
      await this.clearTyped(page);
      return { ok: false, reason: "what was typed did not reach X's box" };
    }
    if (dryRun) {
      await this.clearTyped(page);
      return { ok: true, dry: true };
    }
    const before = page.url();
    const btn = await this.first(page, SEL.postButton);
    if (!btn) return { ok: false, reason: "X offered no way to post it" };
    await delay(300 + Math.random() * 500);
    await btn.click().catch(() => {});
    await delay(2000 + Math.random() * 1500);
    const said = await this.warning(page);
    if (said) return { ok: false, reason: said };
    return { ok: true, from: before };
  }

  /** A post of its own, with pictures beside it if there are any, and more posts after it as a thread. */
  async post(text, { images = [], dryRun = false, thread = [] } = {}) {
    const page = await this.outPage();
    await this.goto("https://x.com/compose/post", page);
    let box = await page.waitForSelector(SEL.composer.join(","), { timeout: 12000 }).catch(() => null);
    if (!box) {
      await this.goto("https://x.com/home", page);
      const opener = await this.first(page, SEL.composerOpen);
      if (opener) await opener.click().catch(() => {});
      box = await page.waitForSelector(SEL.composer.join(","), { timeout: 10000 }).catch(() => null);
    }
    if (!box) return { ok: false, reason: "X did not open a box to write in" };
    await this.typeInto(page, box, text);
    for (const file of (images || []).slice(0, 4)) {
      if (!fs.existsSync(file)) continue;
      const input = await this.first(page, SEL.composerFile);
      if (!input) break;
      await input.uploadFile(file);
      await delay(2000 + Math.random() * 1500);
    }
    for (const more of (thread || []).slice(0, 9)) {
      const add = await this.first(page, SEL.addToThread);
      if (!add) break;
      await add.click().catch(() => {});
      await delay(500 + Math.random() * 400);
      const next = await page.$$(SEL.composer[1]);
      const el = next[next.length - 1];
      if (!el) break;
      await this.typeInto(page, el, more);
    }
    const out = await this.pressPost(page, { dryRun });
    if (!out.ok || out.dry) return out;
    // Its address, from its own profile: the composer does not say where it went.
    const mine = await this.ownPosts(1).catch(() => []);
    return { ok: true, url: mine[0]?.url || "" };
  }

  /** Its own recent posts, newest first. */
  async ownPosts(n = 5) {
    if (!this.handle) return [];
    const page = await this.outPage();
    await this.goto(`https://x.com/${this.handle}`, page);
    const rows = await this.readInSteps(page, readTweetsInPage, [SEL, this.handle], (t) => t.id,
                                        { steps: 1, max: Math.max(n, 5) });
    return rows.filter((t) => t.mine && !t.reply).slice(0, n);
  }

  async deletePost(url) {
    const page = await this.outPage();
    await this.goto(url, page);
    const caret = await this.first(page, SEL.caret);
    if (!caret) return { ok: false, reason: "that post is not there any more" };
    await caret.click().catch(() => {});
    await delay(500);
    const said = await page.evaluate(clickSaidInPage, "^delete$", "i");
    if (!said) return { ok: false, reason: "X offered no way to delete it" };
    await delay(400);
    const yes = await this.first(page, SEL.confirm);
    if (yes) await yes.click().catch(() => {});
    await delay(900);
    return { ok: true };
  }

  // ── Likes, reposts, follows ────────────────────────────────────────────────

  /**
   * Press one of a post's buttons. `which` is like, unlike, repost or unrepost. `readMs` is how long it looks at
   * the post first: pressing the moment the page draws is the one thing no person does.
   */
  async press(url, which, { dryRun = false, readMs = 0 } = {}) {
    const page = await this.outPage();
    await this.goto(url, page);
    const already = await page.evaluate((sel) => ({
      liked: !!document.querySelector(sel.unlike[0]),
      reposted: !!document.querySelector(sel.unrepost[0]),
    }), SEL).catch(() => ({}));
    if ((which === "like" && already.liked) || (which === "unlike" && !already.liked)
        || (which === "repost" && already.reposted) || (which === "unrepost" && !already.reposted)) {
      return { ok: true, already: true };
    }
    if (readMs) await delay(readMs);
    if (dryRun) return { ok: true, dry: true };
    const marks = { like: SEL.like, unlike: SEL.unlike, repost: SEL.repost, unrepost: SEL.unrepost }[which];
    if (!marks) return { ok: false, reason: `nothing on X called ${which}` };
    const btn = await this.first(page, marks);
    if (!btn) return { ok: false, reason: "that post is not there any more" };
    await btn.click().catch(() => {});
    await delay(500 + Math.random() * 500);
    // A repost asks once more, in a little menu.
    if (which === "repost" || which === "unrepost") {
      const confirm = await this.first(page, which === "repost" ? SEL.repostConfirm : SEL.unrepostConfirm);
      if (confirm) await confirm.click().catch(() => {});
      else await page.evaluate(clickSaidInPage, (which === "repost" ? SAY.repost : SAY.undoRepost).source, "i");
      await delay(700);
    }
    const said = await this.warning(page);
    return said ? { ok: false, reason: said } : { ok: true };
  }

  likePost(url, opts = {}) { return this.press(url, "like", opts); }
  repost(url, opts = {}) { return this.press(url, "repost", opts); }

  /** Whoever's profile, with their counts: used to know who it is talking to. */
  async profileInfo(handle) {
    const h = cleanHandle(handle);
    if (!h) return { exists: false };
    const page = await this.outPage();
    await this.goto(`https://x.com/${h}`, page);
    const info = await page.evaluate(profileInPage, SEL).catch(() => ({}));
    const following = await page.evaluate((sel) => !!document.querySelector(sel.unfollow[0]), SEL).catch(() => false);
    return { ...info, handle: h, i_follow: following };
  }

  /** Its own profile, for the card and the counts. */
  async whoAmI() {
    const page = await this.outPage();
    const handle = this.handle || (await page.evaluate((sel) => {
      const b = document.querySelector(sel.accountSwitcher[0]);
      const m = (b ? b.innerText || "" : "").match(/@([A-Za-z0-9_]{1,15})/);
      return m ? m[1] : "";
    }, SEL).catch(() => ""));
    if (!handle) return {};
    await this.goto(`https://x.com/${handle}`, page);
    const info = await page.evaluate(profileInPage, SEL).catch(() => ({}));
    const mine = await this.readInSteps(page, readTweetsInPage, [SEL, handle], (t) => t.id, { steps: 0, max: 10 });
    return { ...info, handle: cleanHandle(handle) || handle, posts: mine.length, profiled: !!info.name };
  }

  async follow(handle) {
    const h = cleanHandle(handle);
    if (!h) return { ok: false, reason: "that is not an X handle" };
    const page = await this.outPage();
    await this.goto(`https://x.com/${h}`, page);
    if (await page.evaluate((sel) => !!document.querySelector(sel.unfollow[0]), SEL).catch(() => false)) {
      return { ok: true, already: true };
    }
    const btn = await this.first(page, SEL.follow);
    if (!btn) {
      const said = await page.evaluate(clickSaidInPage, SAY.follow.source, SAY.follow.flags);
      if (!said) return { ok: false, reason: "X offered no way to follow them" };
    } else {
      await btn.click().catch(() => {});
    }
    await delay(900 + Math.random() * 600);
    const warned = await this.warning(page);
    if (warned) return { ok: false, reason: warned };
    const body = await page.evaluate(() => document.body.innerText || "").catch(() => "");
    return { ok: true, requested: /pending|request sent/i.test(body) };
  }

  async unfollow(handle) {
    const h = cleanHandle(handle);
    const page = await this.outPage();
    await this.goto(`https://x.com/${h}`, page);
    const btn = await this.first(page, SEL.unfollow);
    if (!btn) return { ok: true, already: true };
    await btn.click().catch(() => {});
    await delay(400);
    const yes = await this.first(page, SEL.confirm);
    if (yes) await yes.click().catch(() => {});
    await delay(700);
    return { ok: true };
  }

  /** Its followers, for following back. */
  async followers({ max = 40 } = {}) {
    if (!this.handle) return [];
    const page = await this.outPage();
    await this.goto(`https://x.com/${this.handle}/followers`, page);
    return this.readInSteps(page, readUserCellsInPage, [SEL], (p) => p.handle, { steps: 2, max });
  }

  // ── Signing in ─────────────────────────────────────────────────────────────

  /**
   * Sign in through X's own flow: the handle, the password, and then whatever it decided to ask. Every way this can
   * end that a person has to fix ends here with `needs`, never with another try: X locks an account that is signed
   * into over and over, and a lock takes a person, a phone and a code to undo.
   */
  async signIn({ password = "", totpKey = "", email = "", onState = null, getCode = null, onPerson = null } = {}) {
    const say = (state, detail = "") => { try { onState && onState(state, detail); } catch { /* logged anyway */ } };
    if (!this.handle) return { ok: false, needs: false, reason: "no handle to sign in as" };
    if (!password) return { ok: false, needs: true, reason: "its password is not saved" };

    say("signing-in", "opening X's sign-in");
    await this.goto("https://x.com/i/flow/login", this.page);

    const box = await this.page.waitForSelector(SEL.loginUser.join(","), { timeout: 20000 }).catch(() => null);
    if (!box) {
      if (await this.isLogged()) return { ok: true, already: true };
      return { ok: false, needs: true, reason: "X did not offer a sign-in box" };
    }
    await this.typeInto(this.page, box, this.handle);
    await delay(300 + Math.random() * 400);
    await this.page.evaluate(clickSaidInPage, SAY.next.source, SAY.next.flags);
    await delay(1500 + Math.random() * 1000);

    return this.afterLogin({ password, totpKey, email, say, getCode, onPerson });
  }

  /** Everything after the handle: the password, and each of the ways X can stop. */
  async afterLogin({ password, totpKey, email, say, getCode, onPerson }) {
    for (let step = 0; step < 8; step++) {
      await delay(900 + Math.random() * 700);
      if (await this.isLogged()) return { ok: true };

      if (await this.locked()) {
        say("locked", "X has locked this account");
        return { ok: false, needs: true, reason: "X has locked this account: unlock it on x.com, then start it" };
      }
      if (await this.suspended()) {
        say("suspended", "X has suspended this account");
        return { ok: false, needs: true, reason: "X has suspended this account" };
      }
      if (await this.captchaShown()) {
        say("needs-you", "X wants its sliding check solved");
        if (onPerson) {
          const solved = await onPerson("captcha");
          if (solved) continue;
        }
        return { ok: false, needs: true, reason: "X put up a check only a person can solve" };
      }

      const body = await this.page.evaluate(() => document.body.innerText || "").catch(() => "");

      // The password step.
      const pwd = await this.first(this.page, SEL.loginPassword);
      if (pwd) {
        say("signing-in", "typing its password");
        await this.typeInto(this.page, pwd, password);
        await delay(400 + Math.random() * 400);
        const submit = await this.first(this.page, SEL.loginSubmit);
        if (submit) await submit.click().catch(() => {});
        else await this.page.evaluate(clickSaidInPage, SAY.logIn.source, SAY.logIn.flags);
        continue;
      }

      const asks = await this.first(this.page, SEL.challengeInput);
      if (asks) {
        // X's own step when it does not like the look of a login: the email or phone on the account.
        if (/unusual login activity|confirm it.s you|phone number or email|email or phone/i.test(body)) {
          if (!email) {
            say("needs-you", "X is asking for the account's email or phone");
            return { ok: false, needs: true,
                     reason: "X asked for the email or phone on the account. Add it on the Accounts page." };
          }
          say("signing-in", "answering what X asked");
          await this.typeInto(this.page, asks, email);
          await delay(300 + Math.random() * 400);
          await this.page.evaluate(clickSaidInPage, SAY.next.source, SAY.next.flags);
          continue;
        }
        // The six digits from the account's own key.
        if (/two-factor|authentication (app|code)|enter the (verification|security) code|6-digit|backup code/i
            .test(body) && totpKey) {
          say("two-factor", "making the six digits");
          const code = await totp(totpKey);
          await this.typeInto(this.page, asks, code);
          await delay(300);
          await this.page.evaluate(clickSaidInPage, SAY.next.source, SAY.next.flags);
          continue;
        }
        // A code only a person has.
        say("needs-code", "X sent a code to the account");
        if (getCode) {
          const code = await getCode();
          if (code) {
            await this.typeInto(this.page, asks, String(code));
            await delay(300);
            await this.page.evaluate(clickSaidInPage, SAY.next.source, SAY.next.flags);
            continue;
          }
        }
        return { ok: false, needs: true, reason: "X asked for a code it sent to the account" };
      }

      const wrong = await this.page.evaluate((sel) => {
        for (const s of sel.loginError) {
          const el = document.querySelector(s);
          if (el) return (el.innerText || "").trim();
        }
        return "";
      }, SEL).catch(() => "");
      if (wrong && /password|could not find|incorrect|wrong/i.test(wrong)) {
        say("logged-out", wrong.slice(0, 120));
        return { ok: false, needs: true, reason: `X refused the login: ${wrong.slice(0, 120)}` };
      }
    }
    return (await this.isLogged())
      ? { ok: true }
      : { ok: false, needs: true, reason: "the sign-in did not finish" };
  }

  // ── Pictures off the page ──────────────────────────────────────────────────

  _tempDir() {
    const dir = path.join(this.dataDir, "config", "temp");
    fs.mkdirSync(dir, { recursive: true });
    return dir;
  }

  /** Something it was sent, saved beside the app so another part can look at it. */
  async captureMedia(url, stem = "x_media") {
    const page = await this.outPage();
    try {
      const got = await page.evaluate(async (u) => {
        const r = await fetch(u, { credentials: "include" });
        if (!r.ok) return null;
        const b = await r.arrayBuffer();
        if (b.byteLength > 12e6) return null;
        return { type: r.headers.get("content-type") || "", data: [...new Uint8Array(b)] };
      }, url).catch(() => null);
      if (!got) return null;
      const ext = /png/.test(got.type) ? "png" : /webp/.test(got.type) ? "webp" : /mp4|video/.test(got.type) ? "mp4" : "jpg";
      const file = path.join(this._tempDir(), `${stem}_${this.account}.${ext}`);
      fs.writeFileSync(file, Buffer.from(got.data));
      return { file, kind: ext === "mp4" ? "video" : "photo" };
    } catch {
      return null;
    }
  }

  async showWindow() { try { await showWindow(this.page); } catch { /* not hidden */ } }
  async hideWindow() { try { await hideWindow(this.page); } catch { /* not hidden */ } }

  async close() {
    this.gone = true;
    try { await this.browser?.close(); } catch { /* already gone */ }
  }
}
