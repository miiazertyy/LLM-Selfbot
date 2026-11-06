/**
 * Reddit, driven through reddit.com in the account's own Chrome: its chats, the replies and mentions in its
 * inbox, the comments it writes, its own posts, and the upvotes, saves, joins and follows it does out there.
 *
 * Reddit's API stopped taking new apps on 31 October 2026 and closes altogether in March 2027, so the page is the
 * only way in. old.reddit.com would be far easier, but it now needs a login and is being taken away from new
 * accounts, which is exactly what a bot account is, so everything here is new Reddit.
 *
 * Three things make Reddit different from the four platforms before it:
 *
 *   Reading is easier than X and writing is harder. A post is a <shreddit-post> whose content is ordinary light
 *   DOM, slotted in, and whose facts are attributes on the element itself: its id, its author, its subreddit, its
 *   score, its comment count, its permalink. So the readers below take attributes, not words, and a redesign of
 *   what the page looks like does not touch them. The buttons are the other way round: they live inside the
 *   elements' shadow roots, where document.querySelector does not reach, so everything that presses one goes
 *   through deep(), which walks the shadow roots, or through Puppeteer's own ">>>".
 *
 *   The box to write in is a Lexical editor, which is Draft.js's problem by another name: setting .value or the
 *   text inside one changes what is drawn and nothing else, the editor's own state stays empty, and the button
 *   stays disabled. Only real typing works, which is what typeInto does.
 *
 *   Reddit does not lock an account it dislikes. It hides it: a shadowbanned account's words are there for the
 *   account itself and for nobody else. Nothing says so, so notHidden() looks for its own newest comment from a
 *   signed-out window of the same browser, which is the only place the difference shows.
 *
 * Nothing here has been seen against the real reddit.com - there was no account to try it on - so every marker is
 * a list, the hooks first, and selectorHealth() says which of them still find anything. reddit_probe.js prints
 * that list against a real page.
 */
import fs from "fs";
import path from "path";
import { launchBrowser, delay, typeDelay, persona, showWindow, hideWindow } from "./browser.js";
// The six digits from a 2FA key are RFC 6238 and nobody's in particular; instagrambot.js already has them, and one
// copy is better than two. Imported here rather than where it is used, so a missing file is a loud start, not a
// quiet failure halfway through a sign-in.
import { totp } from "./instagrambot.js";

export const HOME = "https://www.reddit.com/";
export const CHAT_HOME = "https://chat.reddit.com/";

/**
 * Everything looked for on the page. Each is a list: the hook first, then whatever else has stood in for it.
 * Grouped as the pages are. A ⚠ is one nothing has ever confirmed.
 */
export const SEL = {
  // ── Signing in (/login) ──
  // Only ever used when the session has run out and a password was saved for it; a person signing in does it in
  // the window reddit_login.js opens, and none of this is touched.
  loginUser: ['input[name="username"]', '#login-username input', 'input[autocomplete="username"]'],
  loginPassword: ['input[name="password"]', '#login-password input', 'input[type="password"]'],
  loginSubmit: ['button[type="submit"]', 'faceplate-button[type="submit"]'],
  loginError: ['[data-testid="login-error"]', 'faceplate-form [slot="error"]', 'div[role="alert"]'],
  otpInput: ['input[name="otp"]', 'input[autocomplete="one-time-code"]', 'input[inputmode="numeric"]'],
  loggedOut: ['a[href*="/login"]', 'faceplate-tracker[noun="login"]'],

  // ── The app's shell: what being in looks like ──
  loggedIn: ['#expand-user-drawer-button', 'shreddit-app[user-logged-in="true"]', 'faceplate-tracker[noun="user"]'],
  appShell: ['shreddit-app', '#main-content', 'main'],
  feed: ['shreddit-feed', 'main [data-testid="posts-list"]'],
  toast: ['faceplate-toast', '[data-testid="toast"]'],
  dialog: ['faceplate-dialog[open]', 'dialog[open]', 'div[role="dialog"]'],

  // ── A post ──
  // Its facts are its attributes: id (t3_…), author, subreddit-prefixed-name, score, comment-count, permalink,
  // created-timestamp, post-title.
  post: ["shreddit-post", "article"],
  postBody: ['div[slot="text-body"]', 'div[slot="post-media-container"]', "[data-post-click-location=text-body]"],
  postTitle: ['[slot="title"]', "h1", "h2"],
  // By where it sits on the post: which host serves it has changed twice and will again.
  postImage: ['div[slot="post-media-container"] img', 'shreddit-aspect-ratio img',
              'img[src*="redd.it"]', 'figure img'],
  postVideo: ["shreddit-player", "shreddit-player-2", "video"],
  postLink: ['a[slot="full-post-link"]', 'a[data-click-id="body"]'],
  // ⚠ the buttons, all of them inside the post's shadow root.
  upvote: ['button[upvote]', 'button[aria-label*="pvote"]', '[data-post-click-location="vote"] button:first-of-type'],
  downvote: ['button[downvote]', 'button[aria-label*="ownvote"]'],
  saveItem: ['[data-post-click-location="save"]', 'button[aria-label*="ave"]'],
  commentButton: ['a[data-post-click-location="comments-button"]', 'a[href*="/comments/"]'],
  shareButton: ['[data-post-click-location="share"]'],

  // ── A comment ──
  // thingid (t1_…), author, depth, permalink, score are attributes on the element.
  comment: ["shreddit-comment", "div[data-testid='comment']"],
  commentBody: ['div[slot="comment"]', "[data-testid='comment-body']", ".md"],
  commentReply: ['button[slot="reply-button"]', 'button[aria-label*="eply"]'],
  // ⚠ the editor Reddit writes in, which is Lexical and not a textarea.
  composer: ['div[contenteditable="true"][role="textbox"]', 'shreddit-composer div[contenteditable="true"]',
             "faceplate-textarea-input textarea"],
  composerSubmit: ['button[slot="submit-button"]', 'button[type="submit"]', 'faceplate-button[type="submit"]'],

  // ── Writing a post ──
  postTitleBox: ['textarea[name="title"]', 'faceplate-textarea-input[name="title"] textarea', 'input[name="title"]'],
  postBodyBox: ['div[contenteditable="true"][role="textbox"]', 'shreddit-composer div[contenteditable="true"]'],
  postLinkBox: ['input[name="link"]', 'input[name="url"]', 'textarea[name="link"]'],
  postFile: ['input[type="file"]'],
  postSubmit: ['#submit-post-button', 'button[type="submit"]', 'faceplate-button[type="submit"]'],
  // ⚠ many subreddits refuse a post with no flair on it.
  flairButton: ['#post-submit-flair-button', 'button[aria-label*="lair"]'],
  flairOption: ['faceplate-tracker[noun="flair"]', '[role="option"]', "li[role='option']"],
  flairApply: ['#post-flair-modal-apply-button', 'button[type="submit"]'],
  // What a subreddit says when it will not take a post from this account.
  postError: ['[data-testid="post-error"]', 'faceplate-form [slot="error"]', 'div[role="alert"]'],

  // ── Its inbox: the replies and the u/ mentions ──
  notification: ["shreddit-notification", 'div[data-testid="notification"]', "li.notification"],
  inboxLink: ['a[href*="/notifications"]', 'a[href*="/message/inbox"]'],
  // The older message pages, which some accounts still have.
  messageRow: ["div.message", "shreddit-message"],

  // ── Chat, which is a different app on a different host ──
  // ⚠ none of these has been seen; chat.reddit.com is its own Matrix client.
  chatRoomList: ["rs-room-list", '[data-testid="room-list"]', "nav[aria-label*='hat']"],
  chatRoom: ["rs-room-list-item", '[data-testid="room-list-item"]', 'a[href*="/room/"]'],
  chatUnread: ["[data-unread]", '[data-testid="unread-badge"]', ".unread"],
  chatTimeline: ["rs-timeline", '[data-testid="timeline"]', "ol[role='list']"],
  chatMessage: ["rs-message", '[data-testid="message"]', "li[data-event-id]"],
  chatComposer: ['div[contenteditable="true"][role="textbox"]', "rs-composer textarea", "textarea"],
  chatSend: ['button[aria-label*="end"]', "rs-composer button[type='submit']"],
  chatFile: ['input[type="file"]'],
  chatInvites: ['a[href*="/invites"]', '[data-testid="invites"]'],
  chatAccept: ['button[aria-label*="ccept"]', "rs-invite button"],
  chatReact: ['button[aria-label*="eact"]', '[data-testid="react-button"]'],

  // ── People ──
  profileKarma: ['[data-testid="karma"]', 'faceplate-number[number]', "#profile--id-card--highlight-cell--karma"],
  profileAge: ['[data-testid="cake-day"]', "#profile--id-card--highlight-cell--age"],
  profileBio: ['[data-testid="profile-description"]', 'div[slot="description"]'],
  followButton: ['button[aria-label*="ollow"]', 'faceplate-tracker[noun="follow"] button'],
  joinButton: ['button[aria-label*="oin"]', "shreddit-join-button button", "shreddit-join-button"],

  // ── The checks Reddit puts up ──
  captcha: ['iframe[src*="recaptcha"]', 'iframe[title*="challenge"]', "#px-captcha"],
  blocked: ['[data-testid="banned"]', "#blocked-message"],
};

/** What Reddit says when it will not do a thing, and the plain line for the card. */
export const WARNINGS = [
  [/you(?:'| a)re doing that too much/i, "Reddit says it is doing that too much. It waits."],
  [/try again in (\d+) (second|minute|hour)/i, "Reddit asked it to wait before trying again."],
  [/rate ?limit/i, "Reddit is rate limiting it."],
  [/you don'?t have enough karma|requires? .{0,20}karma/i, "That subreddit wants more karma than it has."],
  [/account (?:is too new|must be at least)/i, "That subreddit will not take a new account."],
  [/you are not allowed to post|banned from/i, "It is not allowed to post there."],
  [/this (?:post|comment|thread) (?:has been )?(?:locked|archived)/i, "That thread takes no more comments."],
  [/removed by (?:the )?moderators/i, "The moderators removed it."],
  [/suspended/i, "Reddit has suspended the account. A person has to sort that out."],
  [/verify your email/i, "Reddit wants the account's email verified first."],
  [/something went wrong/i, "Reddit said something went wrong."],
];

export function warningReason(text) {
  const said = String(text || "");
  for (const [re, line] of WARNINGS) if (re.test(said)) return line;
  return "";
}

//: Reddit's own rule for a username. A hyphen is a real character here, unlike X's handles.
const USERNAME = /^[a-z0-9_-]{3,20}$/;
//: Reddit's own paths, which are never somebody's name.
const RESERVED = new Set(["r", "u", "user", "settings", "notifications", "message", "submit", "login", "logout",
                          "search", "best", "hot", "new", "top", "rising", "all", "popular", "coins", "premium",
                          "subreddits", "about", "help", "wiki", "media", "gallery", "chat", "appeal"]);

/** The username as an id carries it, or "" when it is not one Reddit could have given. */
export function cleanUser(name) {
  let n = String(name || "").trim();
  const link = n.match(/reddit\.com\/u(?:ser)?\/([A-Za-z0-9_-]{3,20})/i);
  if (link) n = link[1];
  n = n.replace(/^\/+/, "").replace(/^u\//i, "").replace(/^user\//i, "").replace(/^@/, "").replace(/\/+$/, "")
    .toLowerCase();
  return USERNAME.test(n) && !RESERVED.has(n) ? n : "";
}

/** A person's chat id: "rd_" and their username. */
export function chatIdFor(name) {
  const n = cleanUser(name);
  return n ? `rd_${n}` : "";
}

/** A group chat's id: "rdg_" and its room, with Matrix's punctuation taken off. */
export function groupIdFor(room) {
  const r = String(room || "").trim().replace(/^!/, "").split(":")[0].replace(/[^A-Za-z0-9_-]/g, "");
  return r ? `rdg_${r}` : "";
}

/**
 * The username behind a chat id, "" for a group. "rdg_" is tested first: an underscore is legal in a username, so
 * "rd_g_tom" is a person and only "rdg_" without one is a group.
 */
export function userOf(chatId) {
  const id = String(chatId || "");
  if (id.startsWith("rdg_")) return "";
  return id.startsWith("rd_") ? id.slice(3) : "";
}

export const CHAT_ID = /^(rd_[a-z0-9_-]{3,20}|rdg_[A-Za-z0-9_-]{2,60})$/;

/** The username in a link, however the link was written. */
export function userFromHref(href) {
  const m = String(href || "").match(/\/u(?:ser)?\/([A-Za-z0-9_-]{3,20})/);
  return m ? cleanUser(m[1]) : "";
}

/** The post's own id in a link: base 36, and the same whichever way the link was written. */
export function postIdFromHref(href) {
  const h = String(href || "");
  const m = h.match(/\/comments\/([a-z0-9]{2,12})/i) || h.match(/redd\.it\/([a-z0-9]{2,12})/i);
  return m ? m[1].toLowerCase() : "";
}

/** The comment's own id in a permalink, which is the last piece of it. */
export function commentIdFromHref(href) {
  const m = String(href || "").match(/\/comments\/[a-z0-9]{2,12}\/[^/]*\/([a-z0-9]{2,12})/i);
  return m ? m[1].toLowerCase() : "";
}

/** The subreddit in a link, without its r/. */
export function subOfHref(href) {
  const m = String(href || "").match(/\/r\/([A-Za-z0-9_]{2,21})/);
  return m ? m[1] : "";
}

/** Where a post lives, from its id and its subreddit. */
export function postUrl(sub, id) {
  const s = String(sub || "").replace(/^r\//, "");
  return s ? `https://www.reddit.com/r/${s}/comments/${id}/` : `https://www.reddit.com/comments/${id}/`;
}

/** A thing id ("t3_abc") as the bare base-36 id Reddit's links carry. */
export function bareId(thing) {
  return String(thing || "").replace(/^t[1-6]_/, "").toLowerCase();
}

/** The words Reddit puts on things, each in the wordings it has used. */
const SAY = {
  accept: /^(accept|join chat|accept invite)$/i,
  cookies: /^(accept all|accept|agree|got it|i agree)$/i,
  notNow: /^(not now|maybe later|skip|no thanks|dismiss|close)$/i,
  reply: /^(reply|add a comment|comment)$/i,
  post: /^(post|submit|create post)$/i,
  save: /^(save|unsave)$/i,
  join: /^(join|joined|leave)$/i,
  follow: /^(follow|following|unfollow)$/i,
};

// ── The things that run inside the page ─────────────────────────────────────
// Each of these runs inside the page, so it stands alone: no closures, everything through its arguments. They are
// exported so the tests can run them against a saved copy of one of Reddit's pages, which is the only way to check
// them without an account (tests/reddit_logic.mjs).

/**
 * Press the first thing whose words match, wherever it is - the light DOM or inside any open shadow root. The
 * regex comes in as its source and its flags, because a RegExp cannot cross the line into the page.
 */
export function clickSaidInPage(source, flags, scope) {
  const re = new RegExp(source, flags);
  const roots = [document];
  const out = [];
  // Breadth-first through every open shadow root: Reddit keeps its buttons in them.
  for (let i = 0; i < roots.length && roots.length < 4000; i++) {
    const root = roots[i];
    let here = [];
    try {
      here = Array.from(root.querySelectorAll(scope || "button, a, faceplate-button, [role='button']"));
    } catch { continue; }
    for (const el of here) out.push(el);
    let all = [];
    try { all = Array.from(root.querySelectorAll("*")); } catch { all = []; }
    for (const el of all) if (el.shadowRoot) roots.push(el.shadowRoot);
  }
  for (const el of out) {
    const words = (el.getAttribute("aria-label") || el.textContent || "").trim();
    if (words && words.length < 40 && re.test(words)) {
      el.click();
      return words;
    }
  }
  return "";
}

/** Press one thing inside a named post or comment, by one of a list of selectors, shadow roots and all. */
export function clickDeepInPage(hostSelector, id, selectors) {
  const hosts = Array.from(document.querySelectorAll(hostSelector));
  const host = hosts.find((h) => (h.getAttribute("id") || h.getAttribute("thingid") || "") === id)
    || hosts.find((h) => (h.getAttribute("permalink") || "").includes(id));
  if (!host) return { ok: false, reason: "gone from the page" };
  const roots = [host.shadowRoot || host];
  for (let i = 0; i < roots.length && roots.length < 500; i++) {
    const root = roots[i];
    for (const sel of selectors) {
      let found = null;
      try { found = root.querySelector(sel); } catch { found = null; }
      if (found) {
        found.scrollIntoView({ block: "center" });
        found.click();
        return { ok: true, pressed: sel };
      }
    }
    let all = [];
    try { all = Array.from(root.querySelectorAll("*")); } catch { all = []; }
    for (const el of all) if (el.shadowRoot) roots.push(el.shadowRoot);
    if (root === host && host.shadowRoot) roots.push(host);
  }
  return { ok: false, reason: "nothing to press" };
}

/**
 * The posts on whatever page is open. Everything comes off the element's own attributes rather than its words:
 * that is the one part of Reddit that a redesign does not move.
 */
export function readPostsInPage(sel, me) {
  const out = [];
  const seen = new Set();
  for (const s of sel.post) {
    for (const el of document.querySelectorAll(s)) {
      const id = (el.getAttribute("id") || "").replace(/^t3_/, "");
      if (!id || seen.has(id)) continue;
      seen.add(id);
      const attr = (n) => el.getAttribute(n) || "";
      const num = (n) => {
        const v = parseInt(attr(n), 10);
        return Number.isFinite(v) ? v : 0;
      };
      const pick = (list) => {
        for (const q of list) {
          const f = el.querySelector(q);
          if (f) return f;
        }
        return null;
      };
      const bodyEl = pick(sel.postBody);
      const titleEl = pick(sel.postTitle);
      const media = [];
      for (const q of sel.postImage) {
        for (const img of el.querySelectorAll(q)) {
          if (img.src) media.push({ kind: "photo", url: img.src });
        }
      }
      for (const q of sel.postVideo) {
        for (const v of el.querySelectorAll(q)) {
          const src = v.getAttribute("src") || v.getAttribute("packaged-media-json") || "";
          if (src) media.push({ kind: "video", url: src });
        }
      }
      const author = attr("author").replace(/^u\//, "").toLowerCase();
      const permalink = attr("permalink");
      const at = Date.parse(attr("created-timestamp")) || 0;
      out.push({
        id,
        thing: `t3_${id}`,
        url: permalink ? new URL(permalink, location.origin).href : "",
        author,
        mine: !!me && author === String(me).toLowerCase(),
        subreddit: attr("subreddit-prefixed-name").replace(/^r\//, ""),
        title: (attr("post-title") || (titleEl ? titleEl.innerText : "")).trim(),
        text: bodyEl ? bodyEl.innerText.trim() : "",
        score: num("score"),
        comments: num("comment-count"),
        at,
        media: media.slice(0, 4),
        promoted: attr("promoted") === "true" || !!el.querySelector("shreddit-ad-post"),
        locked: attr("locked") === "true",
        nsfw: attr("nsfw") === "true",
      });
    }
    if (out.length) break;
  }
  return out;
}

/** The comments under whatever thread is open, each with how deep it sits. */
export function readCommentsInPage(sel, me) {
  const out = [];
  const seen = new Set();
  for (const s of sel.comment) {
    for (const el of document.querySelectorAll(s)) {
      const attr = (n) => el.getAttribute(n) || "";
      const id = (attr("thingid") || attr("id")).replace(/^t1_/, "");
      if (!id || seen.has(id)) continue;
      seen.add(id);
      let body = null;
      for (const q of sel.commentBody) {
        body = el.querySelector(q);
        if (body) break;
      }
      const author = attr("author").replace(/^u\//, "").toLowerCase();
      const permalink = attr("permalink");
      out.push({
        id,
        thing: `t1_${id}`,
        url: permalink ? new URL(permalink, location.origin).href : "",
        author,
        mine: !!me && author === String(me).toLowerCase(),
        depth: parseInt(attr("depth"), 10) || 0,
        score: parseInt(attr("score"), 10) || 0,
        text: body ? body.innerText.trim() : "",
        at: Date.parse(attr("created-timestamp")) || 0,
        post: postIdOf(permalink),
      });
    }
    if (out.length) break;
  }
  return out;

  function postIdOf(href) {
    const m = String(href || "").match(/\/comments\/([a-z0-9]{2,12})/i);
    return m ? m[1].toLowerCase() : "";
  }
}

/** What is waiting in its inbox: who said it, what they said, and where. */
export function readInboxInPage(sel) {
  const out = [];
  const rows = [];
  for (const s of sel.notification) {
    for (const el of document.querySelectorAll(s)) rows.push(el);
    if (rows.length) break;
  }
  if (!rows.length) {
    for (const s of sel.messageRow) {
      for (const el of document.querySelectorAll(s)) rows.push(el);
      if (rows.length) break;
    }
  }
  for (const el of rows) {
    const link = el.querySelector('a[href*="/comments/"]') || el.querySelector("a[href]");
    const href = link ? new URL(link.getAttribute("href"), location.origin).href : "";
    const words = (el.innerText || "").trim();
    const who = (el.getAttribute("author") || "").replace(/^u\//, "").toLowerCase()
      || (words.match(/u\/([A-Za-z0-9_-]{3,20})/) || [])[1] || "";
    const m = href.match(/\/comments\/([a-z0-9]{2,12})/i);
    const c = href.match(/\/comments\/[a-z0-9]{2,12}\/[^/]*\/([a-z0-9]{2,12})/i);
    const id = (c && c[1]) || (el.getAttribute("id") || "").replace(/^t1_/, "") || (m && m[1]) || "";
    if (!id) continue;
    // What kind it is, from what the row carries rather than from its words, which are in whatever language the
    // account is set to.
    const kind = /username mention|u\//i.test(el.getAttribute("type") || "") ? "mention"
      : (el.getAttribute("type") || (c ? "reply" : "other"));
    out.push({
      id,
      url: href,
      author: who ? who.toLowerCase() : "",
      subreddit: (href.match(/\/r\/([A-Za-z0-9_]{2,21})/) || [])[1] || "",
      post: (m && m[1].toLowerCase()) || "",
      text: words.slice(0, 2000),
      kind,
      unread: el.hasAttribute("unread") || el.getAttribute("data-read") === "false"
        || /\bunread\b/i.test(el.className || ""),
      at: Date.parse(el.getAttribute("created-timestamp") || "") || 0,
    });
  }
  return out;
}

/** The chat rooms down the side of chat.reddit.com, and which of them have something new. */
export function readRoomsInPage(sel) {
  const out = [];
  const seen = new Set();
  for (const s of sel.chatRoom) {
    for (const el of document.querySelectorAll(s)) {
      const href = el.getAttribute("href") || (el.querySelector("a[href]") || {}).getAttribute?.("href") || "";
      const room = (String(href).match(/\/room\/([^/?#]+)/) || [])[1]
        || el.getAttribute("room-id") || el.getAttribute("data-room-id") || "";
      if (!room || seen.has(room)) continue;
      seen.add(room);
      const words = (el.innerText || "").split("\n").map((w) => w.trim()).filter(Boolean);
      let unread = false;
      for (const q of sel.chatUnread) if (el.querySelector(q)) unread = true;
      if (el.hasAttribute("data-unread") || /\bunread\b/i.test(el.className || "")) unread = true;
      const people = [];
      for (const a of el.querySelectorAll('a[href*="/user/"], a[href*="/u/"]')) {
        const m = (a.getAttribute("href") || "").match(/\/u(?:ser)?\/([A-Za-z0-9_-]{3,20})/);
        if (m && !people.includes(m[1].toLowerCase())) people.push(m[1].toLowerCase());
      }
      const img = el.querySelector("img[src]");
      out.push({
        room,
        name: words[0] || room,
        preview: words.slice(1).join(" ").slice(0, 200),
        people,
        group: people.length > 1 || /group/i.test(el.getAttribute("room-type") || ""),
        unread,
        avatar: img ? img.src : "",
      });
    }
    if (out.length) break;
  }
  return out;
}

/**
 * The messages in the chat that is open. Whose a message is comes from the element saying so where it does, and
 * from which side of the pane it is drawn on where it does not, as X's are.
 */
export function readChatInPage(sel, me) {
  const rows = [];
  for (const s of sel.chatMessage) {
    for (const el of document.querySelectorAll(s)) rows.push(el);
    if (rows.length) break;
  }
  let pane = null;
  for (const s of sel.chatTimeline) {
    pane = document.querySelector(s);
    if (pane) break;
  }
  const box = pane ? pane.getBoundingClientRect() : { left: 0, width: window.innerWidth };
  const mid = box.left + box.width / 2;
  const out = [];
  rows.forEach((el, idx) => {
    const attrFrom = (el.getAttribute("sender") || el.getAttribute("data-sender") || "")
      .replace(/^@/, "").split(":")[0].toLowerCase();
    const r = el.getBoundingClientRect();
    const mine = attrFrom && me ? attrFrom === String(me).toLowerCase()
      : r.left + r.width / 2 > mid;
    const time = el.querySelector("time[datetime]");
    const img = el.querySelector("img[src]:not([alt*='avatar'])");
    const video = el.querySelector("video[src], video source[src]");
    const link = el.querySelector("a[href^='http']");
    let text = (el.innerText || "").replace(/\s+/g, " ").trim();
    // The time and the sender's name are drawn in the row, and a row can come back as one line rather than
    // three, so they are taken off the ends of the joined text rather than filtered out as lines.
    const clock = (time ? time.innerText || "" : "").replace(/\s+/g, " ").trim();
    if (clock && text.endsWith(clock)) text = text.slice(0, -clock.length).trim();
    if (attrFrom) {
      const lead = new RegExp(`^(u/)?${attrFrom.replace(/[.*+?^${}()|[\]\\-]/g, "\\$&")}\\b[:\\s]*`, "i");
      text = text.replace(lead, "").trim();
    }
    // Its words ARE the link's: nothing was said about it, it was just sent.
    const linkWords = link ? (link.innerText || "").replace(/\s+/g, " ").trim() : "";
    out.push({
      idx,
      mine,
      author: attrFrom,
      text,
      kind: video ? "video" : img ? "photo" : (link && (!text || text === linkWords)) ? "link" : "",
      at: time ? Date.parse(time.getAttribute("datetime")) || 0 : 0,
      links: link ? [link.href] : [],
      media: video ? [{ kind: "video", url: video.getAttribute("src") || "" }]
        : img ? [{ kind: "photo", url: img.src }] : [],
      day: "",
    });
  });
  return out;
}

/** What a profile page says about somebody. */
export function profileInPage(sel, name) {
  const pick = (list) => {
    for (const q of list) {
      const f = document.querySelector(q);
      if (f) return f;
    }
    return null;
  };
  const number = (el) => {
    if (!el) return 0;
    const raw = el.getAttribute("number") || el.innerText || "";
    const m = String(raw).replace(/,/g, "").match(/([\d.]+)\s*([km])?/i);
    if (!m) return 0;
    const n = parseFloat(m[1]);
    const mul = (m[2] || "").toLowerCase() === "m" ? 1e6 : (m[2] || "").toLowerCase() === "k" ? 1e3 : 1;
    return Math.round(n * mul);
  };
  const bio = pick(sel.profileBio);
  const age = pick(sel.profileAge);
  const years = (() => {
    const said = age ? (age.getAttribute("datetime") || age.innerText || "") : "";
    const when = Date.parse(said);
    if (!when) return 0;
    return Math.max(0, Math.round((Date.now() - when) / (365.25 * 86400000)));
  })();
  return {
    name: String(name || "").toLowerCase(),
    karma: number(pick(sel.profileKarma)),
    years,
    bio: bio ? bio.innerText.trim().slice(0, 400) : "",
    exists: !/page not found|nobody on reddit goes by/i.test(document.body.innerText || ""),
    suspended: /account (?:has been )?suspended/i.test(document.body.innerText || ""),
  };
}

/** Where the page is scrolled to, so a list can be read a window at a time. */
export function scrollStateInPage() {
  const el = document.scrollingElement || document.documentElement;
  return {
    y: el.scrollTop,
    height: el.scrollHeight,
    view: el.clientHeight,
    atBottom: el.scrollTop + el.clientHeight >= el.scrollHeight - 40,
  };
}

/**
 * Reddit, driven. Four pages by what they are for: the chat, its inbox, what it is reading, and whatever it is
 * going out to do, so one never loses the other's place.
 */
export default class RedditBot {
  constructor({ account = 1, username = "", dataDir, locale = "en-US", timezone = "", tag = "[Reddit]" } = {}) {
    this.account = account;
    this.username = cleanUser(username);
    this.dataDir = dataDir;
    this.locale = locale;
    this.timezone = timezone;
    this.tag = tag;
    this.browser = null;
    this.page = null;      // its chats
    this.side = null;      // its inbox and its own posts
    this.out = null;       // going out: somebody's profile, a thread, posting
    this.lurker = null;    // a signed-out window, only ever used to check it is not being hidden
    this.hidden = false;
    this.health = {};
    this.gone = false;
  }

  profileDir() {
    return path.join(this.dataDir, "config", `reddit-${this.username || "unknown"}-profile`);
  }

  // ── The browser ───────────────────────────────────────────────────────────
  async launch({ hidden = false, proxy = "" } = {}) {
    this.hidden = hidden;
    this.browser = await launchBrowser({ profileDir: this.profileDir(), hidden, locale: this.locale, proxy });
    this.page = (await this.browser.pages())[0] || (await this.browser.newPage());
    await this.dress(this.page);
    this.browser.on("disconnected", () => { this.gone = true; });
    return this.browser;
  }

  async dress(page) {
    await persona(page, { locale: this.locale, timezone: this.timezone }).catch(() => {});
  }

  async newTab() {
    const page = await this.browser.newPage();
    await this.dress(page);
    return page;
  }

  usable(page) {
    return !!page && !page.isClosed();
  }

  async sidePage() {
    if (!this.usable(this.side)) this.side = await this.newTab();
    return this.side;
  }

  async outPage() {
    if (!this.usable(this.out)) this.out = await this.newTab();
    return this.out;
  }

  async ensure() {
    if (this.gone || !this.browser || !this.browser.connected) return "gone";
    if (!this.usable(this.page)) {
      this.page = await this.newTab().catch(() => null);
      if (!this.page) return "gone";
    }
    return "ok";
  }

  /**
   * Go somewhere and wait for the page to be a page. Never networkidle: Reddit keeps connections open and never
   * goes idle, so waiting for that times out every time.
   */
  async goto(url, page = this.page) {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 }).catch(() => {});
    await page.waitForSelector(SEL.appShell.join(","), { timeout: 20000 }).catch(() => {});
    await delay(400 + Math.random() * 600);
    await this.dismissDialogs(page);
  }

  async dismissDialogs(page) {
    await page.evaluate(clickSaidInPage, SAY.cookies.source, SAY.cookies.flags, null).catch(() => {});
    // The toast reorders what is on the page when it is pressed, so it is only ever got rid of.
    await page.evaluate((list) => {
      for (const q of list) for (const el of document.querySelectorAll(q)) el.remove();
    }, SEL.toast).catch(() => {});
    await page.evaluate(clickSaidInPage, SAY.notNow.source, SAY.notNow.flags,
                        "faceplate-dialog[open] button, dialog[open] button, div[role='dialog'] button")
      .catch(() => {});
  }

  // ── Who and where ─────────────────────────────────────────────────────────
  async isLogged(page = this.page) {
    return await page.evaluate((list) => list.some((q) => !!document.querySelector(q)), SEL.loggedIn)
      .catch(() => false);
  }

  async captchaShown(page = this.page) {
    return await page.evaluate((list) => list.some((q) => !!document.querySelector(q)), SEL.captcha)
      .catch(() => false);
  }

  /** The account this window is actually signed in as, which is not always the one that was asked for. */
  async whoAmI() {
    const page = await this.sidePage();
    await this.goto("https://www.reddit.com/user/me/", page);
    const fromUrl = userFromHref(page.url());
    if (fromUrl) return fromUrl;
    const said = await page.evaluate(() => {
      const a = document.querySelector('a[href^="/user/"]');
      return a ? a.getAttribute("href") : "";
    }).catch(() => "");
    return userFromHref(said);
  }

  /** What Reddit is complaining about on this page, in a line, or "". */
  async warning(page = this.page) {
    const said = await page.evaluate(() => (document.body ? document.body.innerText.slice(0, 4000) : ""))
      .catch(() => "");
    return warningReason(said);
  }

  /** Which markers still find something on the page that is open: what reddit_probe.js prints. */
  async selectorHealth(page = this.page) {
    const url = page.url();
    const want = ["appShell", "loggedIn"];
    if (/chat\.reddit\.com/.test(url)) want.push("chatRoomList", "chatRoom");
    else if (/\/comments\//.test(url)) want.push("post", "comment", "composer");
    else if (/\/notifications/.test(url)) want.push("notification");
    else want.push("post", "feed");
    const found = await page.evaluate((pairs) => {
      const out = {};
      for (const [name, list] of pairs) {
        out[name] = list.some((q) => {
          try { return !!document.querySelector(q); } catch { return false; }
        });
      }
      return out;
    }, want.map((k) => [k, SEL[k]])).catch(() => ({}));
    this.health = found;
    return found;
  }

  // ── Typing into a Lexical box ─────────────────────────────────────────────
  /**
   * Real typing, because that is the only kind the editor's own state hears. Emoji go in as one character rather
   * than as keys, and Enter is a newline here: the send is always a button.
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
        await page.keyboard.sendCharacter(ch);
      } else {
        await page.keyboard.type(ch, { delay: typeDelay() });
      }
    }
    if (enter) await page.keyboard.press("Enter");
  }

  /** Whatever was typed, taken back out, so an abandoned send leaves nothing in the box. */
  async clearTyped(page) {
    await page.keyboard.down("Control");
    await page.keyboard.press("KeyA");
    await page.keyboard.up("Control");
    await page.keyboard.press("Backspace");
  }

  /** The first of a list of selectors that is actually on the page. */
  async first(page, list, timeout = 0) {
    if (timeout) await page.waitForSelector(list.join(","), { timeout }).catch(() => {});
    for (const q of list) {
      const el = await page.$(q).catch(() => null);
      if (el) return el;
    }
    return null;
  }

  /** The same, but reaching into shadow roots, which is where Reddit keeps its buttons. */
  async firstDeep(page, list) {
    for (const q of list) {
      const el = await page.$(`>>> ${q}`).catch(() => null);
      if (el) return el;
    }
    return null;
  }

  /**
   * A list read a window at a time and merged on each row's own id: Reddit takes rows off the page as they go by,
   * so nothing found in one pass may be held into the next.
   */
  async readInSteps(page, reader, args, idOf, { steps = 3, max = 60 } = {}) {
    const seen = new Map();
    for (let i = 0; i <= steps; i++) {
      const before = seen.size;
      const batch = await page.evaluate(reader, ...args).catch(() => []);
      for (const row of batch || []) {
        const id = idOf(row);
        if (id && !seen.has(id)) seen.set(id, row);
      }
      if (i && seen.size === before) break;        // a step that found nothing new: the end
      if (seen.size >= max || i === steps) break;
      await page.evaluate(() => {
        const el = document.scrollingElement || document.documentElement;
        el.scrollBy(0, el.clientHeight * 0.8);
      }).catch(() => {});
      await delay(700 + Math.random() * 600);
    }
    return Array.from(seen.values()).slice(0, max);
  }

  // ── Chat ──────────────────────────────────────────────────────────────────
  async openChatHome() {
    if (!/chat\.reddit\.com/.test(this.page.url() || "")) await this.goto(CHAT_HOME, this.page);
    return !!(await this.first(this.page, SEL.chatRoomList, 8000));
  }

  async listRooms({ scrolls = 2 } = {}) {
    await this.openChatHome();
    const rows = await this.readInSteps(this.page, readRoomsInPage, [SEL], (r) => r.room,
                                        { steps: scrolls, max: 40 });
    return rows.map((r) => ({
      ...r,
      chat: r.group ? groupIdFor(r.room) : (chatIdFor(r.people[0]) || groupIdFor(r.room)),
    })).filter((r) => CHAT_ID.test(r.chat));
  }

  /** Open one chat by the id the rest of the app knows it as. */
  async openChat(chatId) {
    const id = String(chatId || "");
    if (!CHAT_ID.test(id)) return { ok: false, reason: "not a chat id" };
    const rooms = await this.listRooms({ scrolls: 1 });
    const row = rooms.find((r) => r.chat === id);
    if (!row) {
      // Never talked to before: a person can be opened by their name.
      const user = userOf(id);
      if (!user) return { ok: false, reason: "no such chat" };
      await this.goto(`${CHAT_HOME}user/${user}`, this.page);
    } else {
      await this.goto(`${CHAT_HOME}room/${row.room}`, this.page);
    }
    const box = await this.first(this.page, SEL.chatComposer, 10000);
    return box ? { ok: true } : { ok: false, reason: "the chat would not open" };
  }

  async readChat(chatId, { scrollUps = 2 } = {}) {
    const open = await this.openChat(chatId);
    if (!open.ok) return open;
    for (let i = 0; i < scrollUps; i++) {
      await this.page.evaluate((list) => {
        for (const q of list) {
          const el = document.querySelector(q);
          if (el) { el.scrollBy(0, -el.clientHeight * 0.8); return; }
        }
      }, SEL.chatTimeline).catch(() => {});
      await delay(600 + Math.random() * 500);
    }
    await this.page.evaluate((list) => {
      for (const q of list) {
        const el = document.querySelector(q);
        if (el) { el.scrollTop = el.scrollHeight; return; }
      }
    }, SEL.chatTimeline).catch(() => {});
    await delay(400);
    const messages = await this.page.evaluate(readChatInPage, SEL, this.username).catch(() => []);
    return { ok: true, messages: messages || [] };
  }

  async sendText(chatId, text) {
    const open = await this.openChat(chatId);
    if (!open.ok) return open;
    const box = await this.first(this.page, SEL.chatComposer, 8000);
    if (!box) return { ok: false, reason: "no box to write in" };
    await this.typeInto(this.page, box, text);
    await delay(200 + Math.random() * 300);
    // Enter sends a chat message; the button is the fallback where it does not.
    await this.page.keyboard.press("Enter").catch(() => {});
    await delay(700);
    const still = await this.page.evaluate((list) => {
      for (const q of list) {
        const el = document.querySelector(q);
        if (el) return (el.innerText || el.value || "").trim().length;
      }
      return 0;
    }, SEL.chatComposer).catch(() => 0);
    if (still) {
      const send = await this.firstDeep(this.page, SEL.chatSend);
      if (send) await send.click().catch(() => {});
      await delay(600);
    }
    const said = await this.warning(this.page);
    if (said) {
      await this.clearTyped(this.page).catch(() => {});
      return { ok: false, reason: said };
    }
    return { ok: true };
  }

  async sendImage(chatId, file) {
    const open = await this.openChat(chatId);
    if (!open.ok) return open;
    const input = await this.first(this.page, SEL.chatFile, 5000);
    if (!input) return { ok: false, reason: "nowhere to put a picture" };
    await input.uploadFile(file);
    await delay(1500 + Math.random() * 1500);
    const send = await this.firstDeep(this.page, SEL.chatSend);
    if (send) await send.click().catch(() => {});
    await delay(1200);
    const said = await this.warning(this.page);
    return said ? { ok: false, reason: said } : { ok: true };
  }

  async react(chatId, idx, emoji) {
    const open = await this.openChat(chatId);
    if (!open.ok) return open;
    const pressed = await this.page.evaluate((sel, n) => {
      const rows = [];
      for (const s of sel.chatMessage) {
        for (const el of document.querySelectorAll(s)) rows.push(el);
        if (rows.length) break;
      }
      const row = rows[n];
      if (!row) return false;
      row.scrollIntoView({ block: "center" });
      for (const q of sel.chatReact) {
        const b = row.querySelector(q);
        if (b) { b.click(); return true; }
      }
      return false;
    }, SEL, Number(idx) || 0).catch(() => false);
    if (!pressed) return { ok: false, reason: "no way to react to that" };
    await delay(500);
    const got = await this.page.evaluate(clickSaidInPage, `^${emoji}$`, "", "[role='option'], button").catch(() => "");
    return got ? { ok: true } : { ok: false, reason: "that reaction was not offered" };
  }

  async chatInvites() {
    await this.goto(`${CHAT_HOME}invites`, this.page);
    return await this.readInSteps(this.page, readRoomsInPage, [SEL], (r) => r.room, { steps: 1, max: 20 });
  }

  async acceptInvite(room) {
    await this.goto(`${CHAT_HOME}room/${room}`, this.page);
    const got = await this.page.evaluate(clickSaidInPage, SAY.accept.source, SAY.accept.flags, null).catch(() => "");
    await delay(800);
    return got ? { ok: true } : { ok: false, reason: "nothing to accept" };
  }

  // ── Its inbox: what people said to it in public ──────────────────────────
  async inbox({ scrolls = 3 } = {}) {
    const page = await this.sidePage();
    await this.goto("https://www.reddit.com/notifications/", page);
    const rows = await this.readInSteps(page, readInboxInPage, [SEL], (r) => r.id, { steps: scrolls, max: 40 });
    return rows;
  }

  /** A post and what is said under it. */
  async readThread(url, { scrolls = 2 } = {}) {
    const page = await this.outPage();
    await this.goto(url, page);
    const posts = await page.evaluate(readPostsInPage, SEL, this.username).catch(() => []);
    const comments = await this.readInSteps(page, readCommentsInPage, [SEL, this.username], (c) => c.id,
                                            { steps: scrolls, max: 60 });
    return { post: (posts || [])[0] || null, comments: comments || [] };
  }

  /**
   * Reply under something, by its permalink. The same path answers a reply in its inbox, a u/ mention, and a
   * comment it decided to write itself: on Reddit they are all one thing.
   */
  async replyTo(url, text) {
    const page = await this.outPage();
    await this.goto(url, page);
    const said = await this.warning(page);
    if (said) return { ok: false, reason: said };
    // The reply button on the thing itself, then the box it opens.
    const reply = await this.firstDeep(page, SEL.commentReply);
    if (reply) {
      await reply.click().catch(() => {});
      await delay(600 + Math.random() * 600);
    }
    const box = await this.first(page, SEL.composer, 10000);
    if (!box) return { ok: false, reason: "no box to write in" };
    await this.typeInto(page, box, text);
    await delay(400 + Math.random() * 600);
    const submit = await this.firstDeep(page, SEL.composerSubmit);
    if (!submit) {
      await this.clearTyped(page).catch(() => {});
      return { ok: false, reason: "no way to send it" };
    }
    const off = await submit.evaluate((el) => el.disabled || el.getAttribute("aria-disabled") === "true")
      .catch(() => false);
    if (off) {
      await this.clearTyped(page).catch(() => {});
      return { ok: false, reason: "the button never woke up" };
    }
    await submit.click().catch(() => {});
    await delay(1500 + Math.random() * 1000);
    const after = await this.warning(page);
    return after ? { ok: false, reason: after } : { ok: true, url };
  }

  // ── Posts of its own ──────────────────────────────────────────────────────
  /**
   * Put up a post. `where` is a subreddit's name or "" for its own profile, which always takes one whatever the
   * account's karma is.
   */
  async post({ title, text = "", link = "", image = "", where = "", flair = true, dryRun = false }) {
    const page = await this.outPage();
    const sub = String(where || "").replace(/^r\//, "").trim();
    const target = sub ? `https://www.reddit.com/r/${sub}/submit/` : `https://www.reddit.com/submit/?type=TEXT`;
    await this.goto(target, page);
    const said = await this.warning(page);
    if (said) return { ok: false, reason: said };
    const titleBox = await this.first(page, SEL.postTitleBox, 10000);
    if (!titleBox) return { ok: false, reason: "no title box" };
    await this.typeInto(page, titleBox, String(title || "").slice(0, 300));
    if (link) {
      const linkBox = await this.first(page, SEL.postLinkBox, 3000);
      if (linkBox) await this.typeInto(page, linkBox, link);
    } else if (text) {
      const bodyBox = await this.first(page, SEL.postBodyBox, 5000);
      if (bodyBox) await this.typeInto(page, bodyBox, text);
    }
    if (image) {
      const file = await this.first(page, SEL.postFile, 3000);
      if (file) {
        await file.uploadFile(image);
        await delay(2500 + Math.random() * 2000);
      }
    }
    if (flair && sub) await this.pickFlair(page);
    if (dryRun) {
      await this.goto(HOME, page);
      return { ok: true, dry: true };
    }
    const submit = await this.firstDeep(page, SEL.postSubmit);
    if (!submit) return { ok: false, reason: "no way to post it" };
    const off = await submit.evaluate((el) => el.disabled || el.getAttribute("aria-disabled") === "true")
      .catch(() => false);
    if (off) return { ok: false, reason: "the button never woke up" };
    await submit.click().catch(() => {});
    await delay(3000 + Math.random() * 2000);
    const after = await this.warning(page);
    if (after) return { ok: false, reason: after };
    const url = page.url();
    return { ok: true, url, id: postIdFromHref(url) };
  }

  /** The nearest flair the subreddit offers, where it wants one. Many refuse a post without one. */
  async pickFlair(page) {
    const button = await this.firstDeep(page, SEL.flairButton);
    if (!button) return false;
    await button.click().catch(() => {});
    await delay(800);
    const picked = await page.evaluate((list) => {
      for (const q of list) {
        const el = document.querySelector(q);
        if (el) { el.click(); return true; }
      }
      return false;
    }, SEL.flairOption).catch(() => false);
    if (picked) {
      await delay(400);
      const apply = await this.firstDeep(page, SEL.flairApply);
      if (apply) await apply.click().catch(() => {});
      await delay(600);
    }
    return picked;
  }

  /** Its own posts and comments, newest first. */
  async ownPosts(n = 5) {
    const page = await this.sidePage();
    await this.goto(`https://www.reddit.com/user/${this.username}/submitted/`, page);
    return await this.readInSteps(page, readPostsInPage, [SEL, this.username], (p) => p.id,
                                  { steps: 1, max: Math.max(n, 5) });
  }

  async ownComments(n = 10) {
    const page = await this.sidePage();
    await this.goto(`https://www.reddit.com/user/${this.username}/comments/`, page);
    return await this.readInSteps(page, readCommentsInPage, [SEL, this.username], (c) => c.id,
                                  { steps: 1, max: Math.max(n, 10) });
  }

  // ── Upvotes, saves, joins, follows ───────────────────────────────────────
  /** Press one of a post's own buttons, found again by its id in the same breath as the press. */
  async press(url, which) {
    const page = await this.outPage();
    await this.goto(url, page);
    const id = postIdFromHref(url);
    const list = { upvote: SEL.upvote, downvote: SEL.downvote, save: SEL.saveItem }[which];
    if (!list) return { ok: false, reason: `nothing called ${which}` };
    const got = await page.evaluate(clickDeepInPage, SEL.post[0], `t3_${id}`, list).catch(() => null);
    if (!got || !got.ok) return { ok: false, reason: (got && got.reason) || "not on the page" };
    await delay(700 + Math.random() * 600);
    const said = await this.warning(page);
    return said ? { ok: false, reason: said } : { ok: true };
  }

  async joinSub(sub) {
    const page = await this.outPage();
    const name = String(sub || "").replace(/^r\//, "");
    await this.goto(`https://www.reddit.com/r/${name}/`, page);
    const button = await this.firstDeep(page, SEL.joinButton);
    if (!button) return { ok: false, reason: "no way to join it" };
    const words = await button.evaluate((el) => (el.textContent || "").trim().toLowerCase()).catch(() => "");
    if (/joined|leave/.test(words)) return { ok: true, already: true };
    await button.click().catch(() => {});
    await delay(1000);
    const said = await this.warning(page);
    return said ? { ok: false, reason: said } : { ok: true };
  }

  async follow(name) {
    const page = await this.outPage();
    const who = cleanUser(name);
    if (!who) return { ok: false, reason: "not a username" };
    await this.goto(`https://www.reddit.com/user/${who}/`, page);
    const button = await this.firstDeep(page, SEL.followButton);
    if (!button) return { ok: false, reason: "no way to follow them" };
    const words = await button.evaluate((el) => (el.textContent || "").trim().toLowerCase()).catch(() => "");
    if (/following|unfollow/.test(words)) return { ok: true, already: true };
    await button.click().catch(() => {});
    await delay(1000);
    const said = await this.warning(page);
    return said ? { ok: false, reason: said } : { ok: true };
  }

  async profileInfo(name) {
    const page = await this.outPage();
    const who = cleanUser(name);
    if (!who) return null;
    await this.goto(`https://www.reddit.com/user/${who}/`, page);
    return await page.evaluate(profileInPage, SEL, who).catch(() => null);
  }

  /** Somebody's newest posts, for knowing what they are up to. */
  async theirPosts(name, n = 3) {
    const page = await this.outPage();
    const who = cleanUser(name);
    if (!who) return [];
    await this.goto(`https://www.reddit.com/user/${who}/submitted/`, page);
    return await this.readInSteps(page, readPostsInPage, [SEL, this.username], (p) => p.id,
                                  { steps: 0, max: Math.max(n, 3) });
  }

  // ── Is anybody else seeing this ───────────────────────────────────────────
  /**
   * Whether the account is being hidden. Reddit's answer to a bot is not a lock, it is a shadowban: its words stay
   * there for the account itself and for nobody else, and nothing says so. The only place the difference shows is
   * from outside the session, so this opens one window with no cookies at all and looks for the account from
   * there.
   *
   * { hidden: false } is the good answer. { hidden: true } means every public thing it does is going nowhere.
   */
  async notHidden(commentUrl = "") {
    if (!this.username) return { hidden: false, checked: false };
    let context = null;
    try {
      context = await this.browser.createBrowserContext();
      const page = await context.newPage();
      await page.goto(`https://www.reddit.com/user/${this.username}/about.json`,
                      { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
      const body = await page.evaluate(() => (document.body ? document.body.innerText.slice(0, 2000) : ""))
        .catch(() => "");
      // A shadowbanned account is a 404 to everybody else, however its own window draws it.
      if (/"error":\s*404|Not Found|page not found|nobody on reddit goes by/i.test(body)) {
        return { hidden: true, checked: true, why: "Its profile is not there when signed out." };
      }
      // The stronger check, when there is something it just said: is that comment there for a stranger?
      if (commentUrl) {
        await page.goto(commentUrl, { waitUntil: "domcontentloaded", timeout: 35000 }).catch(() => {});
        await delay(1200);
        const mine = await page.evaluate((sel, me) => {
          for (const s of sel.comment) {
            for (const el of document.querySelectorAll(s)) {
              const who = (el.getAttribute("author") || "").replace(/^u\//, "").toLowerCase();
              if (who === String(me).toLowerCase()) return true;
            }
          }
          return false;
        }, SEL, this.username).catch(() => null);
        if (mine === false) {
          return { hidden: true, checked: true, why: "What it just said is not there when signed out." };
        }
      }
      return { hidden: false, checked: true };
    } catch {
      return { hidden: false, checked: false };
    } finally {
      try { await context?.close(); } catch { /* going away anyway */ }
    }
  }

  // ── Signing in, only when nobody is here ─────────────────────────────────
  /**
   * The account signing itself back in, months later, with a password that was saved for it. A person adding an
   * account never comes through here: they sign in themselves, in the window reddit_login.js opens, which is
   * what Reddit would far rather see.
   */
  async signIn({ password = "", totpKey = "", onState = () => {}, getCode = null } = {}) {
    if (!this.username) return { ok: false, needs: false, reason: "no account" };
    if (!password) {
      return { ok: false, needs: true,
               reason: "Its session has run out and no password was saved. Sign it in again on Accounts." };
    }
    onState("signing-in", "");
    await this.goto("https://www.reddit.com/login/", this.page);
    if (await this.isLogged(this.page)) return { ok: true, already: true };
    const user = await this.first(this.page, SEL.loginUser, 15000);
    const pass = await this.first(this.page, SEL.loginPassword, 5000);
    if (!user || !pass) return { ok: false, needs: true, reason: "Reddit's login page did not look as expected." };
    await this.typeInto(this.page, user, this.username);
    await delay(300 + Math.random() * 400);
    await this.typeInto(this.page, pass, password);
    await delay(300 + Math.random() * 400);
    const submit = await this.firstDeep(this.page, SEL.loginSubmit);
    if (submit) await submit.click().catch(() => {});
    else await this.page.keyboard.press("Enter").catch(() => {});
    return await this.afterLogin({ totpKey, onState, getCode });
  }

  /** What Reddit does next, which is one of five things, and four of them need a person. */
  async afterLogin({ totpKey = "", onState = () => {}, getCode = null } = {}) {
    for (let i = 0; i < 8; i++) {
      await delay(900 + Math.random() * 700);
      if (await this.isLogged(this.page)) {
        onState("ready", "");
        return { ok: true };
      }
      if (await this.captchaShown(this.page)) {
        onState("needs-you", "Reddit put up a check only a person can pass.");
        return { ok: false, needs: true, reason: "Reddit put up a check only a person can pass." };
      }
      const body = await this.page.evaluate(() => (document.body ? document.body.innerText.slice(0, 3000) : ""))
        .catch(() => "");
      if (/suspended/i.test(body)) {
        onState("suspended", "");
        return { ok: false, needs: true, reason: "Reddit has suspended the account." };
      }
      const otp = await this.first(this.page, SEL.otpInput, 1200);
      if (otp) {
        let code = "";
        if (totpKey) {
          onState("two-factor", "");
          code = await totp(totpKey).catch(() => "");
        } else if (getCode) {
          onState("needs-code", "Reddit sent a code to the account.");
          code = await getCode();
        }
        if (!code) {
          return { ok: false, needs: true, reason: "Reddit asked for a code and there was none to give it." };
        }
        await this.typeInto(this.page, otp, code, { enter: true });
        continue;
      }
      const err = await this.first(this.page, SEL.loginError, 500);
      if (err) {
        const words = await err.evaluate((el) => (el.textContent || "").trim()).catch(() => "");
        onState("needs-you", words);
        return { ok: false, needs: true, reason: words || "Reddit refused the login." };
      }
    }
    onState("logged-out", "");
    return { ok: false, needs: true, reason: "The sign-in did not finish." };
  }

  // ── Pictures off the page ────────────────────────────────────────────────
  _tempDir() {
    const dir = path.join(this.dataDir, "cache", "reddit_media");
    fs.mkdirSync(dir, { recursive: true });
    return dir;
  }

  /** One picture or video off a page, fetched on the session's own cookies and saved to a file. */
  async captureMedia(url) {
    const page = await this.outPage();
    const data = await page.evaluate(async (u) => {
      try {
        const r = await fetch(u, { credentials: "include" });
        if (!r.ok) return null;
        const buf = new Uint8Array(await r.arrayBuffer());
        let s = "";
        for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
        return { b64: btoa(s), type: r.headers.get("content-type") || "" };
      } catch {
        return null;
      }
    }, url).catch(() => null);
    if (!data || !data.b64) return "";
    const ext = /mp4|video/.test(data.type) ? ".mp4" : /png/.test(data.type) ? ".png" : ".jpg";
    const file = path.join(this._tempDir(), `rd_${Date.now()}_${Math.random().toString(36).slice(2, 8)}${ext}`);
    fs.writeFileSync(file, Buffer.from(data.b64, "base64"));
    return file;
  }

  async showWindow() {
    if (this.page) await showWindow(this.page).catch(() => {});
  }

  async hideWindow() {
    if (this.page) await hideWindow(this.page).catch(() => {});
  }

  async close() {
    try { await this.browser?.close(); } catch { /* going away anyway */ }
  }
}
