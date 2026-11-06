/**
 * TikTok, driven through tiktok.com in the account's own Chrome: its inbox
 * (www.tiktok.com/messages), its profile, its videos' comments and its LIVE.
 *
 * TikTok has no API for any of this that a person's account can use, so the
 * page is read and used the way a person would: open a conversation, read it,
 * type, press Enter. TikTok signs and sends everything itself.
 *
 * Its pages have changed under people before. The inbox moved into an iframe
 * with new markers (data-e2e="dm-new-*") in 2025; the older one used
 * chat-list-item, chat-item and chat-uniqueid. Every lookup here tries the new
 * markers, then the old, then a guess from the page's layout, and
 * selectorHealth() says which still match, so the account card can say when
 * TikTok changed something instead of going quiet. All of them are in SEL.
 */
import fs from "fs";
import path from "path";
import { delay, typeDelay, launchBrowser, showWindow, hideWindow, persona } from "./browser.js";
import { atOfLabel } from "./runner_core.js";

// Every marker the bot relies on, newest first. data-e2e attributes are TikTok's own test hooks, the steadiest
// thing on its pages; class fragments are the fallback.
// The inbox's markers were read off the signed-in page and TikTok's own scripts (2026-10): the inbox is on the page
// itself now, not in a frame, and every part of it has a dm-new-* marker.
export const SEL = {
  inboxFrame: ['iframe[src*="/messages"]', 'iframe[src*="message"]'],
  conversationList: ['[data-e2e="dm-new-conversation-list"]', '[class*="DivConversationListContainer"]'],
  conversation: ['[data-e2e="dm-new-conversation-item"]', '[data-e2e="chat-list-item"]',
                 '[class*="ConversationItem"]', '[class*="ChatListItem"]'],
  conversationName: ['[data-e2e="dm-new-conversation-nickname"]', '[class*="InfoNickname"]', '[class*="Nickname"]'],
  conversationPreview: ['[class*="SpanInfoExtract"]', '[data-e2e="dm-new-conversation-last-message"]', '[class*="LastMessage"]',
                        '[class*="InfoExtract"]'],
  conversationTime: ['[class*="SpanInfoTime"]', '[class*="InfoTime"]'],
  // A count on the row while it has unread messages; a muted one shows a muted bell instead, and no count.
  conversationUnread: ['[data-e2e="dm-new-conversation-unread"]'],
  conversationMuted: ['[data-e2e="dm-new-conversation-mute-icon"]'],
  // "Message requests", at the top of the list while someone not followed back has written.
  requestHeader: ['[class*="ConversationRequestHeader"]'],
  totalUnread: ['[data-e2e="dm-total-unread-count"]'],
  chatbox: ['[data-e2e="dm-new-chatbox"]', '[data-e2e="chat-box"]', '[class*="ChatBox"]', '[class*="ChatMain"]'],
  chatName: ['[data-e2e="dm-new-chat-nickname"]', '[data-e2e="chat-nickname"]', '[class*="PNickname"]'],
  chatHandle: ['[data-e2e="chat-uniqueid"]', '[data-e2e="dm-new-chat-header"] a[href*="/@"]', '[class*="ChatHeader"] a[href*="/@"]'],
  messageList: ['[data-e2e="dm-new-message-list"]'],
  message: ['[data-e2e="dm-new-chat-item"]', '[data-e2e="dm-new-message-item"]', '[data-e2e="chat-item"]',
            '[class*="ChatItemWrapper"]', '[class*="MessageItem"]'],
  messageText: ['[data-e2e="dm-new-message-text"]', '[class*="DivTextContainer"]'],
  // Each message's sender, as their picture linking to their profile: whose it is, in a group too.
  messageAuthor: ['[data-e2e="chat-avatar"]'],
  // Over a run of messages: the time, alone for today ("21:43"), with the date before ("September 4, 2026 00:15").
  timeSeparator: ['[data-e2e="dm-new-time-separator"]', '[class*="DivTimeContainer"]'],
  sharedVideo: ['[data-e2e="dm-new-shared-video"]'],
  sharedLive: ['[data-e2e="dm-new-shared-live"]'],
  quoted: ['[data-e2e="dm-new-ref-message"]'],
  // Reply, on a message as the pointer passes; the message box then quotes it, with its own close button.
  replyButton: ['[data-e2e="dm-new-reply-btn"]'],
  replyBar: ['[data-e2e="dm-new-ref-close-btn"]'],
  reactionShown: ['[data-e2e="dm-new-reaction-display"]'],
  reactionButton: ['[data-e2e="dm-new-reaction-btn"]'],
  composer: ['[data-e2e="dm-new-input-editor"]', '[data-e2e="message-input-area"] [contenteditable="true"]',
             'div.public-DraftEditor-content[contenteditable="true"]', 'div[contenteditable="true"][role="textbox"]',
             '[aria-label*="message" i][contenteditable="true"]', 'textarea[data-e2e="message-input"]', '[data-e2e="message-input"]'],
  sendButton: ['[data-e2e="dm-new-send-btn"]', '[data-e2e="message-send"]', '[class*="StyledSendButton"]', 'button[aria-label*="send" i]'],
  // A chat TikTok lets pictures into has this button; its picker sends with dm-new-send-media-btn.
  mediaButton: ['[data-e2e="dm-new-media-btn"]'],
  mediaSend: ['[data-e2e="dm-new-send-media-btn"]'],
  // A message request, open: "X wants to send you a message", Delete first and Accept last.
  requestBox: ['[data-e2e="dm-new-stranger-accept"]'],
  blocked: ['[data-e2e="dm-new-blocked-box"]'],
  warning: ['[data-e2e="dm-warning"]', '[class*="DMWarning"]', '[class*="ErrorTip"]'],
  // The activity panel (the bell): new followers, each with Follow back.
  activityButton: ['[data-e2e="nav-activity"]'],
  activityFollowers: ['[data-e2e="followers"]'],
  activityItem: ['[data-e2e="inbox-list-item"]'],
  followBackButton: ['[data-e2e="follow-back"]'],
  loginButton: ['[data-e2e="top-login-button"]', '[data-e2e="nav-login-button"]', 'a[href*="/login"]'],
  profileLink: ['a[data-e2e="nav-profile"]', '[data-e2e="profile-icon"] a', 'a[href^="/@"][data-e2e*="profile"]'],
  followButton: ['[data-e2e="follow-button"]', 'button[data-e2e*="follow"]'],
  messageButton: ['[data-e2e="message-button"]', 'a[href*="/messages"][data-e2e*="message"]'],
  followersCount: ['[data-e2e="followers-count"]'],
  videoLink: ['[data-e2e="user-post-item"] a[href*="/video/"]', 'a[href*="/video/"]'],
  comment: ['[data-e2e="comment-level-1"]', '[class*="CommentItemContainer"]', '[class*="DivCommentObjectWrapper"]'],
  commentReply: ['[data-e2e="comment-reply-1"]', '[data-e2e*="comment-reply"]'],
  commentInput: ['[data-e2e="comment-input"] [contenteditable="true"]', 'div[contenteditable="true"][data-e2e*="comment"]',
                 '[class*="CommentInput"] [contenteditable="true"]'],
  commentPost: ['[data-e2e="comment-post"]', 'div[data-e2e*="comment-post"]'],
  // A LIVE's chat (checked on a public LIVE, 2026-10): its lines are chat-message (a comment, its author in
  // message-owner-name), enter-message (someone joined), and others ending in -message (gifts, follows, shares).
  liveChatList: ['[data-e2e="live-chat-container"]', '[class*="DivChatMessageList"]', '[data-e2e="chat-room"]'],
  liveChatInput: ['[data-e2e="room-chat-input-field"]', 'div[contenteditable="plaintext-only"]', '[data-e2e="comment-text"]'],
  liveChatSend: ['[data-e2e="room-chat-send-btn"]'],
  // Someone else's LIVE, as a viewer (2026-10): its host's name and Follow over the stream, hearts beside the chat box.
  liveHost: ['[data-e2e="room-header-anchor-name"]'],
  liveFollow: ['[data-e2e="room-header-follow-btn"]'],
  liveHeart: ['[data-e2e="room-chat-like-btn"]'],
  // The LIVE page's side lists: "Following" (accounts it follows that are live) and TikTok's suggestions.
  liveChannel: ['[data-e2e="live-side-nav-channel"]'],
  liveChannelTitle: ['[data-e2e="live-side-nav-channel-title"]'],
  // A video's page and the For You feed draw each video the same way (2026-10): an item holding the video, then the
  // column beside it, Like (aria-pressed), comments, Favorites (its label says Add when not saved), share.
  feedItem: ['[data-e2e="recommend-list-item-container"]'],
  likeButton: ['[data-e2e="like-icon"]', '[data-e2e="browse-like-icon"]'],
  saveButton: ['[data-e2e="favorite-icon"]', '[data-e2e="undefined-icon"]'],
  commentButton: ['[data-e2e="comment-icon"]', '[data-e2e="browse-comment-icon"]'],
  feedNext: ['[data-e2e="feed-navigation-next"]', '[data-e2e="arrow-right"]'],
  authorAvatar: ['[data-e2e="video-author-avatar"]', '[data-e2e="browse-user-avatar"]'],
  videoDesc: ['[data-e2e="video-desc"]', '[data-e2e="browse-video-desc"]'],
  commentAuthor: ['[data-e2e="comment-username-1"]'],
  // Someone's profile: their posts, newest first after any pinned ones, each with its views.
  postItem: ['[data-e2e="user-post-item"]'],
  postViews: ['[data-e2e="video-views"]'],
  // The activity panel's tabs and rows: a mention reads "mentioned you in a comment: ...", with links to who and to
  // the video.
  activityTab: { mentions: ['[data-e2e="mentions"]'], comments: ['[data-e2e="comments"]'], followers: ['[data-e2e="followers"]'] },
  activityList: ['[data-e2e="inbox-list"]'],
  activityTitle: ['[data-e2e="inbox-title"]'],
  activityContent: ['[data-e2e="inbox-content"]'],
  // TikTok Studio's upload page (2026-10): a file input for videos; once a file is in, the form, with its caption box
  // (filled with the file's name), who can see it (a combobox, its options Everyone, Friends, Only you), and Post,
  // Save draft and Discard (which asks "Discard this post?").
  uploadInput: ['input[type="file"][accept*="video"]', 'input[type="file"]'],
  uploadButton: ['[data-e2e="select_video_button"]'],
  uploadCaption: ['[data-e2e="caption_container"] [contenteditable="true"]', '[contenteditable="true"]'],
  uploadPrivacy: ['[data-e2e="video_visibility_container"] [role="combobox"]'],
  uploadPost: ['[data-e2e="post_video_button"]'],
  uploadDiscard: ['[data-e2e="discard_post_button"]'],
  captcha: ['#captcha-verify-container-main-page', '#captcha_container', '.captcha-verify-container', '.captcha_verify_container',
            'iframe[src*="captcha"]', '[id*="secsdk-captcha"]'],
};

// TikTok's own wording for "not sent", in English and French, to the plain reason the panel shows.
export const WARNINGS = [
  [/sending messages too fast|too many messages|envoyez des messages trop/i, "TikTok says it is sending too fast; it waits a while"],
  [/only friends can send|seuls les amis/i, "TikTok only lets friends message each other here"],
  [/privacy settings|parametres de confidentialite|paramètres de confidentialité/i, "Their privacy settings don't let this account message them"],
  [/limit reached|limite atteinte/i, "TikTok's message limit for this chat is reached"],
  [/has been suspended|a ete suspendu|a été suspendu/i, "That account is suspended"],
  [/community guidelines|regles de la communaute|règles de la communauté/i, "TikTok held it back for its guidelines"],
  [/couldn.?t be sent|could not be sent|n.?a pas pu etre envoye|n.?a pas pu être envoyé/i, "TikTok did not send it"],
];

export function warningReason(text) {
  for (const [re, why] of WARNINGS) if (re.test(String(text || ""))) return why;
  return "";
}

/** "theo.wav" (or "@Theo.Wav") as the bridge keeps it: tt_theo-wav. */
export function chatIdFor(handle) {
  const h = String(handle || "").trim().replace(/^@/, "").toLowerCase();
  return h ? "tt_" + h.replace(/[^a-z0-9_]/g, "-") : "";
}

export function handleOf(chatId) {
  const c = String(chatId || "");
  return c.startsWith("tt_") ? c.slice(3).replace(/-/g, ".") : "";
}

/** A handle out of a link to a profile: /@theo.wav, https://www.tiktok.com/@theo.wav?lang=en. */
export function handleFromHref(href) {
  const m = String(href || "").match(/\/@([A-Za-z0-9._]{2,24})(?:[/?#]|$)/);
  return m ? m[1].toLowerCase() : "";
}

// ── In the page ──────────────────────────────────────────────────────────────
// These run inside TikTok's page (or its inbox frame) and must stand alone: no closures, only their arguments.

/** The first selector of a list that matches something on the page. */
function pickIn(sels) {
  for (const s of sels) {
    let n = 0;
    try { n = document.querySelectorAll(s).length; } catch { n = 0; }
    if (n) return s;
  }
  return "";
}

/** The conversation list, as rows. */
function readListInPage(sel) {
  const pick = (root, sels) => { for (const s of sels) { try { if (root.querySelector(s)) return root.querySelector(s); } catch { /* bad */ } } return null; };
  const pickAll = (root, sels) => { for (const s of sels) { try { const a = [...root.querySelectorAll(s)]; if (a.length) return a; } catch { /* bad */ } } return []; };
  const visible = (el) => !!el && el.getClientRects().length > 0;
  const weight = (el) => parseInt(getComputedStyle(el).fontWeight, 10) || 400;
  const rows = pickAll(document, sel.conversation).filter(visible);
  // TikTok's own unread count on a row, where the page has its markers; the old guesses (a badge, bold) otherwise.
  const marked = !!document.querySelector(sel.conversation[0]);
  return rows.slice(0, 60).map((row, index) => {
    const nameEl = pick(row, sel.conversationName);
    const lines = (row.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean);
    const name = (nameEl?.innerText || lines[0] || "").trim();
    const previewEl = pick(row, sel.conversationPreview);
    const timeEl = pick(row, sel.conversationTime);
    const preview = (previewEl?.innerText || lines.find((l) => l !== name && !/^\d{1,2}[:h]\d{2}/.test(l)) || "").trim();
    const link = row.querySelector('a[href*="/@"]');
    const img = row.querySelector("img");
    const unreadEl = pick(row, sel.conversationUnread);
    const unreadCount = unreadEl ? (parseInt((unreadEl.innerText || "").replace(/\D+/g, ""), 10) || 1) : 0;
    const badge = [...row.querySelectorAll("*")].some((e) => {
      const c = String(e.className || "");
      if (!/badge|unread/i.test(c) || !visible(e)) return false;
      const r = e.getBoundingClientRect();
      return r.width > 3 && r.width < 40;
    });
    const bold = nameEl ? weight(nameEl) >= 600 && (previewEl ? weight(previewEl) >= 600 : true) : false;
    const time = (timeEl?.innerText || "").trim()
      || lines.find((l) => /^(\d{1,2}[:h]\d{2}|yesterday|hier|\d{1,2}\/\d{1,2}|\d+[smhdw]$)/i.test(l)) || "";
    return {
      index, name, preview, time, unreadCount,
      href: link ? link.getAttribute("href") : "",
      avatar: img ? (img.currentSrc || img.src || "") : "",
      unread: marked ? unreadCount > 0 : badge || (previewEl ? weight(previewEl) >= 600 : bold),
      muted: !!pick(row, sel.conversationMuted),
      typing: /\btyping|is writing|écrit|en train d.écrire/i.test(preview),
      group: (row.querySelectorAll("img").length > 1 && /,/.test(name)) || /\(\d+\)$/.test(name),
      request: /message request|demande de message/i.test(row.innerText || ""),
    };
  });
}

/** The open conversation: whose it is, its messages, and whether there is a photo button. */
function readChatInPage(sel, ownHandle) {
  const pick = (root, sels) => { for (const s of sels) { try { const e = root.querySelector(s); if (e) return e; } catch { /* bad */ } } return null; };
  const pickAll = (root, sels) => { for (const s of sels) { try { const a = [...root.querySelectorAll(s)]; if (a.length) return a; } catch { /* bad */ } } return []; };
  const visible = (el) => !!el && el.getClientRects().length > 0;
  const composer = pick(document, sel.composer);
  // The conversation is whatever holds the box to type in.
  let box = pick(document, sel.chatbox);
  if (!box && composer) {
    box = composer;
    for (let i = 0; i < 8 && box.parentElement; i++) {
      box = box.parentElement;
      if (box.getBoundingClientRect().height > window.innerHeight * 0.6) break;
    }
  }
  if (!box) return null;
  const handleEl = pick(box, sel.chatHandle) || pick(document, sel.chatHandle);
  let handle = "";
  if (handleEl) {
    const href = handleEl.getAttribute("href") || handleEl.closest("a")?.getAttribute("href") || "";
    const m = href.match(/\/@([A-Za-z0-9._]{2,24})/);
    handle = m ? m[1] : (handleEl.innerText || "").trim().replace(/^@/, "");
  }
  if (!handle) {
    const a = [...box.querySelectorAll('a[href*="/@"]')].find((x) => x.getBoundingClientRect().top < box.getBoundingClientRect().top + 120);
    const m = a ? (a.getAttribute("href") || "").match(/\/@([A-Za-z0-9._]{2,24})/) : null;
    if (m) handle = m[1];
  }
  const nameEl = pick(box, sel.chatName);
  const header = (handleEl?.closest("[class]")?.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean);
  const name = (nameEl?.innerText || "").trim() || header.find((l) => !l.startsWith("@")) || handle;
  const own = String(ownHandle || "").toLowerCase();
  const handleIn = (href) => { const m = String(href || "").match(/\/@([A-Za-z0-9._]{2,24})/); return m ? m[1].toLowerCase() : ""; };
  const photoButton = !!pick(box, sel.mediaButton) || !!box.querySelector('input[type="file"][accept*="image"]');
  const request = !!pick(box, sel.requestBox);
  const blocked = !!pick(box, sel.blocked);
  // What a shared card is for, from the props TikTok's page drew it with (the card has no link in it): its post's id
  // and author, or its LIVE's host. An object counts as the post when it has a post's id beside its author, caption
  // or video; the message's own id, higher up, has none of those.
  const sharedOf = (el) => {
    const out = { id: "", author: "", host: "" };
    const key = Object.keys(el).find((k) => k.startsWith("__reactFiber$"));
    let f = key ? el[key] : null;
    const num = (v) => (/^\d{15,25}$/.test(String(v ?? "")) ? String(v) : "");
    const name = (v) => (/^[A-Za-z0-9._]{2,24}$/.test(String(v ?? "")) ? String(v).toLowerCase() : "");
    const look = (o, depth) => {
      if (!o || typeof o !== "object" || Array.isArray(o) || depth > 3 || o.$$typeof || o instanceof Node) return;
      const id = num(o.itemId) || num(o.item_id) || num(o.awemeId) || num(o.aweme_id) || num(o.videoId)
        || (o.author || o.desc !== undefined || o.video || o.authorId ? num(o.id) : "");
      if (id && !out.id) {
        out.id = id;
        const a = o.author;
        out.author = name(typeof a === "object" && a ? a.uniqueId || a.unique_id : a) || name(o.authorUniqueId) || name(o.uniqueId) || out.author;
      }
      if (!out.host && (num(o.roomId) || num(o.room_id))) {
        const h = o.owner || o.anchor || o.user || o.author || {};
        out.host = name(typeof h === "object" ? h.uniqueId || h.unique_id || h.display_id : h) || name(o.uniqueId) || name(o.unique_id);
      }
      for (const v of Object.values(o)) if (v && typeof v === "object") look(v, depth + 1);
    };
    for (let i = 0; f && i < 12 && !out.id && !out.host; i++, f = f.return) {
      try { look(f.memoizedProps, 0); } catch { /* an odd prop: the next level up */ }
    }
    return out;
  };

  // TikTok's markers: its messages and the time labels over them, in the page's order.
  const list = pick(box, sel.messageList) || box;
  const msgSel = sel.message.find((s) => { try { return !!list.querySelector(s); } catch { return false; } });
  const sepSel = sel.timeSeparator.find((s) => { try { return !!list.querySelector(s); } catch { return false; } });
  if (msgSel && msgSel.includes("data-e2e")) {
    const out = [];
    let label = "";
    let idx = -1;
    for (const node of list.querySelectorAll(sepSel ? `${msgSel}, ${sepSel}` : msgSel)) {
      if (sepSel && node.matches(sepSel)) {
        label = (node.innerText || "").trim();
        continue;
      }
      idx++;
      const authorEl = pick(node, sel.messageAuthor);
      const author = handleIn((authorEl?.closest("a") || authorEl?.querySelector("a"))?.getAttribute("href"));
      const r = node.querySelector('[class*="DivTextContainer"], [class*="Container"]')?.getBoundingClientRect();
      const B = box.getBoundingClientRect();
      const mine = author ? author === own : !!r && r.left + r.width / 2 > B.left + B.width / 2;
      const textEl = pick(node, sel.messageText);
      const quoteEl = pick(node, sel.quoted);
      let text = (textEl?.innerText || "").trim().replace(/\n{2,}/g, "\n");
      let kind = "";
      const media = {};
      let title = "";
      const video = pick(node, sel.sharedVideo);
      const live = pick(node, sel.sharedLive);
      if (/message type isn.t supported|type de message n.est pas pris en charge|download tiktok app to view/i.test(text)) {
        // Something only the app shows (a sticker, a voice note, a story...): said as that, not as TikTok's words.
        kind = "unsupported";
        text = "";
      } else if (video) {
        kind = "video";
        const bg = (video.style?.backgroundImage || getComputedStyle(video).backgroundImage || "").match(/url\(["']?(https:[^"')]+)["']?\)/);
        if (bg) media.cover = bg[1];
        title = (video.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean).join(" · ").slice(0, 200);
        if (textEl && video.contains(textEl)) text = "";
        // Its link, so it can be watched: any handle opens a post by its id.
        const it = sharedOf(video);
        if (it.id) media.url = `https://www.tiktok.com/@${it.author || "i"}/video/${it.id}`;
      } else if (live) {
        kind = "live";
        title = (live.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean).join(" · ").slice(0, 200);
        const it = sharedOf(live);
        if (it.host) media.host = it.host;
      }
      if (!kind) {
        const imgs = [...node.querySelectorAll("img")].filter((i) => !i.closest('[data-e2e="chat-avatar"]'));
        const img = imgs.find((i) => i.getBoundingClientRect().width > 60);
        const sticker = !img && imgs.find((i) => i.getBoundingClientRect().width > 24);
        if (node.querySelector("audio")) { kind = "voice"; media.audio = true; }
        // A video they sent from their phone (not a shared TikTok, which is a card): captured whole to be watched.
        else if (node.querySelector("video")) { kind = "clip"; media.video = true; }
        else if (img) { kind = "photo"; media.img = true; }
        else if (sticker && !text) kind = "sticker";
      }
      const links = [...node.querySelectorAll('a[href^="http"], a[href^="/"]')]
        .filter((a) => !a.closest('[data-e2e="chat-avatar"]') && !a.querySelector('[data-e2e="chat-avatar"]'))
        .map((a) => ({ url: new URL(a.getAttribute("href"), location.href).href, title: (a.innerText || "").trim().slice(0, 140) }))
        .filter((l) => /tiktok\.com\/@[^/]+\/(video|photo)\//.test(l.url) || !/tiktok\.com/.test(l.url));
      if (!kind && links.some((l) => /\/(video|photo)\//.test(l.url))) kind = "video";
      if (!text && !kind) continue;
      const shown = pick(node, sel.reactionShown);
      const reactions = shown ? [...shown.children].map((c) => {
        const t = (c.innerText || "").trim();
        const emoji = t.replace(/\d+/g, "").trim();
        return emoji ? { name: emoji, count: parseInt(t.replace(/\D+/g, ""), 10) || 1, mine: false } : null;
      }).filter(Boolean) : [];
      out.push({ idx, mine, author, text, kind, day: label, links: links.slice(0, 3), reactions, title,
                 quote: quoteEl ? (quoteEl.innerText || "").trim().slice(0, 200) : "",
                 media: Object.keys(media).length ? media : undefined });
    }
    return { handle: (handle || "").toLowerCase(), name, messages: out.slice(-150), photoButton, request, blocked, own: ownHandle };
  }

  // No markers: the rows of the tallest scrolling list in the conversation, placed by where they sit.
  let items = pickAll(box, sel.message).filter(visible);
  if (!items.length) {
    const lists = [...box.querySelectorAll("*")].filter((e) => {
      const s = getComputedStyle(e);
      return /(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 20;
    }).sort((a, b) => b.scrollHeight - a.scrollHeight);
    const list = lists[0];
    if (list) {
      items = [...list.children];
      while (items.length === 1 && items[0].children.length > 1) items = [...items[0].children];
      items = items.filter(visible);
    }
  }
  const B = box.getBoundingClientRect();
  const mid = B.left + B.width / 2;
  let day = "";
  const out = [];
  for (const el of items) {
    const text = (el.innerText || "").trim();
    const r = el.getBoundingClientRect();
    if (r.height < 6) continue;
    // A line on its own across the middle with a date or a time in it is a day label, not a message.
    const leafs = [...el.querySelectorAll("*")].filter((e) => !e.children.length && (e.innerText || "").trim());
    const content = leafs.length ? leafs : [el];
    const xs = content.map((e) => e.getBoundingClientRect()).filter((x) => x.width > 0);
    const left = Math.min(...xs.map((x) => x.left)), right = Math.max(...xs.map((x) => x.right));
    const centred = Math.abs((left + right) / 2 - mid) < B.width * 0.08 && right - left < B.width * 0.6;
    if (centred && /(\d{1,2}[:h]\d{2}|today|yesterday|hier|aujourd|\d{4}|mon|tue|wed|thu|fri|sat|sun|lun|mar|mer|jeu|ven|sam|dim)/i.test(text) && text.length < 40) {
      day = text;
      continue;
    }
    const mineByAttr = /(^|[^a-z])(self|mine|own|right)([^a-z]|$)/i.test(String(el.className || "") + " " + (el.getAttribute("data-e2e") || ""));
    const mine = mineByAttr || (left + right) / 2 > mid + B.width * 0.05;
    const video = el.querySelector('a[href*="/video/"]');
    const img = [...el.querySelectorAll("img")].filter((i) => i.getBoundingClientRect().width > 60)[0];
    const sticker = !img && [...el.querySelectorAll("img")].find((i) => i.getBoundingClientRect().width > 30);
    const audio = el.querySelector("audio");
    const links = [...el.querySelectorAll('a[href^="http"], a[href^="/"]')]
      .map((a) => ({ url: new URL(a.getAttribute("href"), location.href).href, title: (a.innerText || "").trim().slice(0, 140) }))
      .filter((l) => /tiktok\.com\/@[^/]+\/(video|photo)\//.test(l.url) || !/tiktok\.com/.test(l.url));
    let kind = "";
    if (video || links.some((l) => /\/(video|photo)\//.test(l.url))) kind = "video";
    else if (audio) kind = "voice";
    else if (img) kind = "photo";
    else if (sticker && !text) kind = "sticker";
    if (!text && !kind) continue;
    const reactions = [...el.querySelectorAll('[class*="Reaction"], [data-e2e*="reaction"]')]
      .map((x) => (x.innerText || "").trim()).filter((t) => /\p{Extended_Pictographic}/u.test(t))
      .map((t) => ({ name: t.replace(/\d+/g, "").trim(), count: parseInt(t.replace(/\D+/g, ""), 10) || 1, mine: false }));
    out.push({ idx: items.indexOf(el), mine, text: kind === "video" && !text ? "" : text.replace(/\n{2,}/g, "\n"), kind, day,
               links: links.slice(0, 3), reactions, media: img ? { img: true } : audio ? { audio: true } : undefined });
  }
  return { handle: (handle || "").toLowerCase(), name, messages: out.slice(-150), photoButton, request, blocked, own: ownHandle };
}

/** Whether "Message requests" is at the top of the list, and how many it says. */
/**
 * The videos a feed has drawn (a video's own page, For You): each one's id, author, caption, whether it is liked and
 * saved, where it sits and whether it plays. The id is in its player's wrapper (xgwrapper-<n>-<id>) or its menu.
 */
function feedInPage(sel) {
  const pickAll = (sels, root = document) => {
    for (const s of sels) { try { const a = [...root.querySelectorAll(s)]; if (a.length) return a; } catch { /* bad */ } }
    return [];
  };
  const pick = (sels, root) => pickAll(sels, root)[0] || null;
  return pickAll(sel.feedItem).map((it) => {
    const wrap = it.querySelector('[id^="xgwrapper-"]');
    let id = wrap ? (wrap.id.match(/(\d{15,25})$/) || [])[1] || "" : "";
    if (!id) id = it.querySelector("[data-more-menu-item-id]")?.getAttribute("data-more-menu-item-id") || "";
    const a = pick(sel.authorAvatar, it);
    const m = (a?.getAttribute("href") || "").match(/\/@([A-Za-z0-9._]{2,24})/);
    const like = pick(sel.likeButton, it);
    const save = pick(sel.saveButton, it);
    const r = it.getBoundingClientRect();
    const video = it.querySelector("video");
    return {
      id, handle: m ? m[1].toLowerCase() : "",
      caption: (pick(sel.videoDesc, it)?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 300),
      liked: like ? like.getAttribute("aria-pressed") === "true" : null,
      // "Add to Favorites. 936 added to Favorites" until it is saved.
      saved: save ? !/^(add to favorites|ajouter aux favoris)/i.test((save.getAttribute("aria-label") || "").trim()) : null,
      top: Math.round(r.top), height: Math.round(r.height), playing: !!(video && !video.paused),
    };
  });
}

/** Click the first of these that is on screen (TikTok keeps hidden copies of some, its activity panel's tabs). */
function clickShownInPage(sels) {
  for (const s of sels) {
    const b = [...document.querySelectorAll(s)].find((x) => x.getClientRects().length && !x.disabled);
    if (b) { b.click(); return true; }
  }
  return false;
}

/** Press Like, Favorites or comments on the feed item of one video (the first item when none says which it is). */
function pressInPage(sel, id, which) {
  const pickAll = (sels, root = document) => {
    for (const s of sels) { try { const a = [...root.querySelectorAll(s)]; if (a.length) return a; } catch { /* bad */ } }
    return [];
  };
  const items = pickAll(sel.feedItem);
  const it = items.find((x) => id && x.querySelector(`[id$="-${id}"], [data-more-menu-item-id="${id}"]`)) || items[0];
  if (!it) return false;
  const b = pickAll(sel[which], it)[0];
  if (!b) return false;
  (b.closest('button, [role="button"]') || b).click();
  return true;
}

/** Someone's posts on their profile: [{ id, url, cover, caption, views, pinned }], as the grid shows them. */
function postsInPage(sel, n) {
  const pickAll = (sels, root = document) => {
    for (const s of sels) { try { const a = [...root.querySelectorAll(s)]; if (a.length) return a; } catch { /* bad */ } }
    return [];
  };
  const out = [];
  for (const it of pickAll(sel.postItem)) {
    const a = it.querySelector('a[href*="/video/"], a[href*="/photo/"]');
    const href = a ? a.href : "";
    const m = href.match(/\/(video|photo)\/(\d{6,25})/);
    if (!m) continue;
    const img = it.querySelector("img");
    out.push({
      id: m[2], kind: m[1], url: href.split("?")[0], cover: img ? img.currentSrc || img.src || "" : "",
      caption: (img?.getAttribute("alt") || "").replace(/\s+/g, " ").trim().slice(0, 300),
      views: (pickAll(sel.postViews, it)[0]?.innerText || "").trim(),
      pinned: /\b(pinned|épinglé|epingle)\b/i.test(it.innerText || ""),
    });
    if (out.length >= n) break;
  }
  return out;
}

function requestsInPage(sel) {
  for (const s of sel.requestHeader) {
    const h = document.querySelector(s);
    if (h && h.getClientRects().length) return parseInt((h.innerText || "").replace(/\D+/g, ""), 10) || 1;
  }
  const el = [...document.querySelectorAll("p, span, div")].find((e) => !e.children.length
    && /^(message requests|demandes de message)/i.test((e.innerText || "").trim()));
  return el ? 1 : 0;
}

export default class TikTokBot {
  constructor({ account = 1, handle = "", dataDir, locale = "en-US", timezone = "", tag = "[TikTok]" } = {}) {
    this.account = account;
    this.handle = String(handle || "").replace(/^@/, "").toLowerCase();
    this.dataDir = dataDir;
    this.locale = locale;
    this.timezone = timezone;
    this.tag = tag;
    this.browser = null;
    this.page = null;
    this.side = null;            // a second tab, for its own LIVE and comments, so the inbox stays open
    this.out = null;             // a third, for going out: other people's videos and LIVEs, For You, posting
    this.hidden = false;
    this.health = {};
  }

  get lang() {
    return String(this.locale || "en-US").split("-")[0];
  }

  async launch({ profileDir, hidden = false, proxy = "" }) {
    this.hidden = hidden;
    this.launchOpts = { profileDir, hidden, proxy };
    this.gone = false;
    this.browser = await launchBrowser({ profileDir, hidden, locale: this.locale, proxy });
    // Its window closed (by hand, or Chrome fell over): ensure() opens it again rather than waiting on a dead page.
    this.browser.on("disconnected", () => { this.gone = true; });
    const pages = await this.browser.pages();
    this.page = pages[0] || (await this.browser.newPage());
    await this.dress(this.page);
    return this.page;
  }

  async dress(page) {
    if (this.browser.__proxyAuth) await page.authenticate(this.browser.__proxyAuth);
    await persona(page, { locale: this.locale, timezone: this.timezone });
    // A page's own pop-ups are dismissed; "Leave site?" is answered yes, or the bot would stay stuck on that page.
    page.on("dialog", async (d) => {
      try { await (d.type() === "beforeunload" ? d.accept() : d.dismiss()); } catch { /* gone */ }
    });
  }

  /**
   * A tab behind the inbox, made to behave as one in front: Chrome draws nothing in a tab behind another, so its
   * videos stop, its pointer never lands and Puppeteer's clicks wait forever. With focus emulation it is "visible"
   * and drawn, and the inbox stays the tab in front.
   */
  async awake(page) {
    try {
      const s = await page.target().createCDPSession();
      await s.send("Emulation.setFocusEmulationEnabled", { enabled: true });
    } catch { /* an older Chrome: DOM clicks still work */ }
  }

  /** A tab of its own beside the inbox, dressed and awake, with the inbox kept in front. */
  async newTab() {
    const page = await this.browser.newPage();
    await this.dress(page);
    await this.awake(page);
    try { await this.page.bringToFront(); } catch { /* fine */ }
    return page;
  }

  /** Whether a tab is still there to use: open, and its frame not come loose. */
  usable(page) {
    try {
      return !!page && !page.isClosed() && !page.mainFrame().detached;
    } catch {
      return false;
    }
  }

  /** The browser and its page, working: "ok", or "reopened" after its window closed, or "newpage" after its page went away. */
  async ensure() {
    const connected = this.browser && !this.gone
      && (typeof this.browser.connected === "boolean" ? this.browser.connected : this.browser.isConnected?.() !== false);
    if (!connected) {
      console.warn(`${this.tag} Its Chrome window closed; opening it again.`);
      try { await this.browser?.close(); } catch { /* gone */ }
      this.side = null;
      this.out = null;
      await this.launch(this.launchOpts);
      return "reopened";
    }
    const frame = this.page && !this.page.isClosed() ? this.page.mainFrame() : null;
    if (!frame || frame.detached) {
      // A page whose frame came loose stays broken: a new one in its place, the old one closed.
      const old = this.page;
      this.page = await this.browser.newPage();
      await this.dress(this.page);
      if (old && !old.isClosed()) await old.close().catch(() => {});
      await this.page.bringToFront().catch(() => {});
      return "newpage";
    }
    return "ok";
  }

  async close() {
    try { await this.browser?.close(); } catch { /* gone */ }
  }

  async goto(url, page = this.page) {
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
        break;
      } catch (e) {
        // A page that went away under it (after a check, or its window closed): opened again, and tried once more.
        if (attempt === 0 && /detached|target closed|session closed|has been closed|not attached/i.test(e.message || "")) {
          const which = page === this.side ? "side" : page === this.out ? "out" : "page";
          await this.ensure();
          if (which === "side") page = await this.sidePage();
          else if (which === "out") page = await this.outPage();
          else page = this.page;
          continue;
        }
        console.warn(`${this.tag} Could not open ${url}: ${e.message}`);
        return false;
      }
    }
    await delay(2500 + Math.random() * 1500);
    await this.dismissDialogs(page);
    return true;
  }

  /** Cookie banners, "keyboard shortcuts", "turn on notifications": closed, as a person would. */
  async dismissDialogs(page = this.page) {
    for (const frame of page.frames()) {
      try {
        await frame.evaluate(() => {
          const said = /^(decline optional cookies|refuser les cookies optionnels|accept all|tout accepter|not now|pas maintenant|got it|ok|close|fermer|later|plus tard|skip|ignorer)$/i;
          for (const b of [...document.querySelectorAll('button, [role="button"]')]) {
            const t = (b.innerText || b.getAttribute("aria-label") || "").trim();
            if (said.test(t) && b.getClientRects().length && b.closest('[role="dialog"], [class*="Modal"], [class*="Banner"], tiktok-cookie-banner')) {
              b.click();
            }
          }
          const close = document.querySelector('[data-e2e="modal-close-inner-button"]');
          if (close && close.getClientRects().length) close.click();
          // The cookie banner lives in a shadow root of its own.
          const banner = document.querySelector("tiktok-cookie-banner");
          const btn = banner?.shadowRoot?.querySelector("button");
          if (btn) btn.click();
        });
      } catch { /* a frame that went away */ }
    }
  }

  // ── Signed in? Who as? ──────────────────────────────────────────────────────

  async hasSession() {
    try {
      const cookies = await this.page.cookies("https://www.tiktok.com");
      return cookies.some((c) => c.name === "sessionid" && c.value);
    } catch {
      return false;
    }
  }

  async isLogged() {
    if (!(await this.hasSession())) return false;
    const url = this.page.url();
    if (/\/login/.test(url)) return false;
    return true;
  }

  /**
   * The signed-in account: its @handle from TikTok's account endpoint (else the page's profile link), then its name,
   * picture, bio and counts from its own profile, as TikTok shows them. The account endpoint's name and picture are
   * the login's (a Google account's, say), not the TikTok profile's: only a fallback.
   */
  async whoAmI() {
    let me = null;
    try {
      const info = await this.page.evaluate(async () => {
        try {
          const r = await fetch("https://www.tiktok.com/passport/web/account/info/?aid=1459", { credentials: "include" });
          const j = await r.json();
          const d = j && j.data;
          if (d && d.username) return { handle: d.username, name: d.screen_name || "", avatar: d.avatar_url || "" };
        } catch { /* below */ }
        return null;
      });
      if (info && info.handle) me = { handle: String(info.handle).toLowerCase(), name: info.name, avatar: info.avatar };
    } catch { /* below */ }
    if (!me) {
      try {
        const href = await this.page.evaluate((sels) => {
          for (const s of sels) { const a = document.querySelector(s); if (a) return a.getAttribute("href") || a.closest("a")?.getAttribute("href") || ""; }
          const a = [...document.querySelectorAll('a[href^="/@"]')].find((x) => /profile/i.test(x.getAttribute("data-e2e") || ""));
          return a ? a.getAttribute("href") : "";
        }, SEL.profileLink);
        const handle = handleFromHref(href);
        if (handle) me = { handle, name: "", avatar: "" };
      } catch { /* unknown */ }
    }
    if (!me) return null;
    const p = await this.profileInfo(me.handle).catch(() => null);
    // `profiled`: read off its TikTok profile; without it the name and picture are the login's, which a caller keeps
    // from replacing the profile's.
    return p ? { ...p, name: p.name || me.name, avatar: p.avatar || me.avatar, profiled: true } : { ...me, profiled: false };
  }

  /**
   * Someone's public profile as TikTok's own page carries it (its rehydration data): name, picture, bio, counts.
   * One request, made by the page with its own session; null when TikTok will not say.
   */
  async profileInfo(handle) {
    const h = String(handle || "").trim().replace(/^@/, "").toLowerCase();
    if (!/^[a-z0-9._]{2,24}$/.test(h)) return null;
    return await this.page.evaluate(async (h) => {
      const r = await fetch(`https://www.tiktok.com/@${h}?lang=en`, { credentials: "include" });
      if (!r.ok) return null;
      const html = await r.text();
      const m = html.match(/<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>([\s\S]*?)<\/script>/);
      if (!m) return null;
      const info = JSON.parse(m[1])?.__DEFAULT_SCOPE__?.["webapp.user-detail"]?.userInfo;
      const u = info?.user;
      if (!u || !u.uniqueId) return null;
      const s = info.stats || info.statsV2 || {};
      const n = (v) => Number(v) || 0;
      // A LIVE going on has its room's id here; none, or "0", when they are not live.
      const room = String(u.roomId || "");
      return {
        handle: String(u.uniqueId).toLowerCase(), name: u.nickname || "", bio: u.signature || "",
        avatar: u.avatarLarger || u.avatarMedium || u.avatarThumb || "",
        verified: !!u.verified, private: !!u.privateAccount,
        followers: n(s.followerCount), following: n(s.followingCount), likes: n(s.heartCount ?? s.heart),
        videos: n(s.videoCount), friends: n(s.friendCount), live: /^[1-9]\d*$/.test(room),
      };
    }, h).catch(() => null);
  }

  async captchaShown(page = this.page) {
    for (const frame of page.frames()) {
      try {
        const hit = await frame.evaluate((sels) => {
          for (const s of sels) {
            const e = document.querySelector(s);
            if (e && e.getClientRects().length) return true;
          }
          return /drag the slider|faites glisser|verify to continue|select 2 objects|rotate the image|puzzle/i
            .test((document.body?.innerText || "").slice(0, 4000)) && !!document.querySelector('[role="dialog"], [class*="captcha" i]');
        }, SEL.captcha);
        if (hit) return true;
      } catch { /* gone */ }
    }
    return false;
  }

  /** Something only a person can do (a captcha, signing in): the window comes up, and down again after, when hidden. */
  async waitForPerson(check, { timeoutMs = 0, onWait } = {}) {
    await showWindow(this.page);
    const started = Date.now();
    while (true) {
      // Its window closed while it waited: opened again, and brought up for the person again.
      if ((await this.ensure().catch(() => "ok")) !== "ok") await showWindow(this.page);
      if (await check().catch(() => false)) break;
      if (timeoutMs && Date.now() - started > timeoutMs) return false;
      if (onWait) onWait(Date.now() - started);
      await delay(4000);
    }
    if (this.hidden) await hideWindow(this.page);
    return true;
  }

  // ── The inbox ───────────────────────────────────────────────────────────────

  async openInbox() {
    const url = `https://www.tiktok.com/messages?lang=${this.lang}`;
    if (!/tiktok\.com\/messages/.test(this.page.url())) await this.goto(url);
    return this.inbox();
  }

  /** Where the inbox lives: its own frame (since 2025), or the page itself. */
  async inbox() {
    // A page whose frame came loose (TikTok swapped it out from under it) is replaced before anything is asked of it:
    // a loose frame throws at once, where nothing catches it.
    if (!this.page || this.page.isClosed() || this.page.mainFrame().detached) await this.ensure();
    const frames = this.page.frames();
    const framed = frames.find((f) => f !== this.page.mainFrame() && /\/messages|message/i.test(f.url()));
    return framed || this.page.mainFrame();
  }

  async listConversations() {
    const f = await this.inbox();
    const rows = await f.evaluate(readListInPage, SEL);
    if (!Array.isArray(rows)) throw new Error("no conversation list");
    this.requestsWaiting = await f.evaluate(requestsInPage, SEL).catch(() => 0);
    return rows.map((r) => ({ ...r, handle: handleFromHref(r.href) }));
  }

  /** The conversation open now, with each message's time (from the labels over them) worked out. */
  async readChat() {
    const f = await this.inbox();
    const chat = await f.evaluate(readChatInPage, SEL, this.handle);
    if (chat && Array.isArray(chat.messages)) {
      for (const m of chat.messages) {
        const at = atOfLabel(m.day);
        if (at) m.at = at;
      }
    }
    return chat;
  }

  /** Open one by its row's place in the list (and name, to be sure it is still that one). */
  /**
   * The link of a shared video the page did not say (sharedOf found nothing): its card is opened, and wherever TikTok
   * shows it (a tab of its own, this page moving to it, a player over the inbox), its address is read and the inbox
   * put back. "" when it could not be told. `idx` is the message's place on the page.
   */
  async resolveShared(idx) {
    const f = await this.inbox();
    // Not the bot's own other tabs, which may be on a video of their own at the time.
    const mine = [this.side, this.out].filter((p) => p && !p.isClosed()).map((p) => p.target());
    const opened = this.browser.waitForTarget((t) => !mine.includes(t) && /\/(video|photo)\/\d{6,}/.test(t.url()),
                                              { timeout: 6000 }).catch(() => null);
    const clicked = await f.evaluate((sel, idx) => {
      const pickAll = (sels) => { for (const s of sels) { try { const a = [...document.querySelectorAll(s)]; if (a.length) return a; } catch { /* bad */ } } return []; };
      const node = pickAll(sel.message)[idx];
      const card = node && sel.sharedVideo.map((s) => node.querySelector(s)).find(Boolean);
      if (!card) return false;
      card.click();
      return true;
    }, SEL, idx).catch(() => false);
    if (!clicked) return "";
    const target = await opened;
    let url = target ? target.url() : "";
    const there = target ? await target.page().catch(() => null) : null;
    if (there && there !== this.page) {
      await there.close().catch(() => {});
    } else if (/\/(video|photo)\/\d{6,}/.test(this.page.url())) {
      url = this.page.url();
      await this.goto(`https://www.tiktok.com/messages?lang=${this.lang}`);
    } else if (!url) {
      // A player over the inbox: its id, then closed.
      const id = await this.page.evaluate(() => (document.querySelector('[id^="xgwrapper-"]')?.id.match(/(\d{15,25})$/) || [])[1] || "").catch(() => "");
      if (id) url = `https://www.tiktok.com/@i/video/${id}`;
      await this.page.keyboard.press("Escape").catch(() => {});
    }
    const m = url.match(/https:\/\/www\.tiktok\.com\/@[A-Za-z0-9._]+\/(?:video|photo)\/\d{6,25}/);
    return m ? m[0] : "";
  }

  async openRow(row) {
    const f = await this.inbox();
    const ok = await f.evaluate((sel, index, name) => {
      const pickAll = (sels) => { for (const s of sels) { try { const a = [...document.querySelectorAll(s)]; if (a.length) return a; } catch { /* bad */ } } return []; };
      const rows = pickAll(sel.conversation).filter((e) => e.getClientRects().length);
      let el = rows.find((r) => name && (r.innerText || "").split("\n").map((s) => s.trim()).includes(name)) || rows[index];
      if (!el) return false;
      el.scrollIntoView({ block: "center" });
      el.click();
      return true;
    }, SEL, row.index, row.name);
    if (!ok) return false;
    await delay(1200 + Math.random() * 800);
    return true;
  }

  /** Open someone's conversation by their @handle: from the list when it is there, else their profile's Message button. */
  async openChatWith(handle, { name = "" } = {}) {
    const h = String(handle || "").replace(/^@/, "").toLowerCase();
    if (!h) return false;
    await this.openInbox();
    const open = await this.readChat().catch(() => null);
    if (open && open.handle === h) return true;
    try {
      const rows = await this.listConversations();
      const row = rows.find((r) => r.handle === h) || (name ? rows.find((r) => r.name === name) : null);
      if (row && (await this.openRow(row))) {
        const now = await this.readChat().catch(() => null);
        if (now && (!now.handle || now.handle === h)) return true;
      }
    } catch { /* the profile, below */ }
    if (!(await this.goto(`https://www.tiktok.com/@${h}?lang=${this.lang}`))) return false;
    const clicked = await this.page.evaluate((sels) => {
      for (const s of sels) { const b = document.querySelector(s); if (b) { b.click(); return true; } }
      const b = [...document.querySelectorAll('button, a, [role="button"]')].find((x) => /^(message|envoyer un message|messages?)$/i.test((x.innerText || "").trim()));
      if (b) { b.click(); return true; }
      return false;
    }, SEL.messageButton);
    if (!clicked) return false;
    await delay(3500);
    const now = await this.readChat().catch(() => null);
    return !!now && (!now.handle || now.handle === h);
  }

  async composer() {
    const f = await this.inbox();
    for (const s of SEL.composer) {
      const el = await f.$(s).catch(() => null);
      if (el) return { frame: f, el, sel: s };
    }
    return null;
  }

  /**
   * What TikTok wrote after a send, said plainly; "" when it said nothing. Every message has a warning slot
   * (dm-warning), empty unless TikTok refused it: their words, the newest last. The page's last words only where
   * there are no such slots.
   */
  async warning() {
    const f = await this.inbox();
    const text = await f.evaluate((sels) => {
      for (const s of sels) {
        const all = [...document.querySelectorAll(s)];
        if (all.length) return all.map((e) => (e.innerText || "").trim()).filter(Boolean).slice(-2).join("\n");
      }
      return (document.body?.innerText || "").slice(-3000);
    }, SEL.warning).catch(() => "");
    return warningReason(text);
  }

  /** Type into the open conversation, as a person types, and send. { ok, reason }. */
  async sendText(text, { dryRun = false } = {}) {
    const box = await this.composer();
    if (!box) return { ok: false, reason: "TikTok's message box is not there" };
    const before = await this.readChat().catch(() => null);
    await box.el.click({ delay: 40 + Math.random() * 60 });
    await delay(200 + Math.random() * 300);
    const lines = String(text).split("\n");
    for (let i = 0; i < lines.length; i++) {
      for (const ch of lines[i]) await this.page.keyboard.type(ch, { delay: typeDelay() });
      if (i < lines.length - 1) {
        await this.page.keyboard.down("Shift");
        await this.page.keyboard.press("Enter");
        await this.page.keyboard.up("Shift");
      }
    }
    if (dryRun) {
      // Typed, then cleared: everything but the send.
      await this.page.keyboard.down("Control");
      await this.page.keyboard.press("a");
      await this.page.keyboard.up("Control");
      await this.page.keyboard.press("Backspace");
      console.log(`${this.tag} (dry run) would have sent: ${String(text).slice(0, 120)}`);
      return { ok: true, dry: true };
    }
    await delay(250 + Math.random() * 400);
    await this.page.keyboard.press("Enter");
    // Enter sends; where it only made a new line, its send button (dm-new-send-btn) does.
    await delay(700);
    const left = await box.frame.evaluate((el) => (el.innerText || el.value || "").trim(), box.el).catch(() => "");
    if (left) {
      for (const s of SEL.sendButton) {
        const b = await box.frame.$(s).catch(() => null);
        if (b) { await b.click().catch(() => {}); break; }
      }
    }
    // Sent when it shows as the account's newest message; a warning says why not.
    for (let i = 0; i < 12; i++) {
      await delay(600);
      const why = await this.warning();
      if (why) return { ok: false, reason: why };
      const now = await this.readChat().catch(() => null);
      const last = now?.messages?.filter((m) => m.mine).pop();
      if (last && last.text.replace(/\s+/g, " ").includes(String(text).replace(/\s+/g, " ").slice(0, 40))
          && (now.messages.length !== before?.messages?.length || last.text !== before?.messages?.filter((m) => m.mine).pop()?.text)) {
        return { ok: true };
      }
    }
    // Not seen on screen, and no warning: TikTok may still have taken it.
    const empty = await box.frame.evaluate((el) => !(el.innerText || el.value || "").trim(), box.el).catch(() => false);
    return empty ? { ok: true, unconfirmed: true } : { ok: false, reason: "TikTok did not take the message" };
  }

  /** The first element of a list of selectors, as a handle, in a frame or page. */
  async firstOf(where, sels) {
    for (const s of sels) {
      const el = await where.$(s).catch(() => null);
      if (el) return el;
    }
    return null;
  }

  /**
   * A picture into the open conversation, where TikTok gives the chat its photo button (dm-new-media-btn: not every
   * chat, not every country). Its picker takes the file; the preview it opens sends with its own button.
   */
  async sendImage(imagePath, { dryRun = false } = {}) {
    const f = await this.inbox();
    const btn = await this.firstOf(f, SEL.mediaButton);
    let input = (btn && await btn.$('input[type="file"]').catch(() => null))
      || await f.$('input[type="file"][accept*="image"]').catch(() => null);
    if (!btn && !input) return { ok: false, reason: "TikTok gives this chat no photo button" };
    if (dryRun) {
      console.log(`${this.tag} (dry run) would have sent the picture ${path.basename(imagePath)}`);
      return { ok: true, dry: true };
    }
    if (input) {
      await input.uploadFile(imagePath);
    } else {
      const [chooser] = await Promise.all([this.page.waitForFileChooser({ timeout: 6000 }).catch(() => null), btn.click()]);
      if (!chooser) return { ok: false, reason: "TikTok's photo picker did not open" };
      await chooser.accept([imagePath]);
    }
    await delay(2200);
    const send = await this.firstOf(f, SEL.mediaSend);
    if (send) await send.click(); else await this.page.keyboard.press("Enter");
    await delay(3000);
    const why = await this.warning();
    return why ? { ok: false, reason: why } : { ok: true };
  }

  /**
   * TikTok's own Reply on one message of the open conversation, by its place on the page (idx): the message box then
   * quotes it, and what is typed next goes as the answer to it. True when the box shows the quote.
   */
  async startReply(idx) {
    const f = await this.inbox();
    let items = [];
    for (const s of SEL.message) { items = await f.$$(s).catch(() => []); if (items.length) break; }
    const el = items[idx];
    if (!el) return false;
    await this.page.bringToFront().catch(() => {});
    const within = (p) => Promise.race([p.catch(() => {}), delay(6000)]);
    await el.evaluate((e) => e.scrollIntoView({ block: "center" })).catch(() => {});
    await delay(300);
    await within(el.hover());
    await delay(400 + Math.random() * 300);
    const btn = await this.firstOf(el, SEL.replyButton);
    if (!btn) return false;
    await btn.click().catch(() => {});
    await delay(600);
    return !!(await this.firstOf(f, SEL.replyBar)) || !!(await this.firstOf(f, SEL.quoted));
  }

  /** The quote in the message box taken away, when a reply was started and is not going. */
  async cancelReply() {
    const f = await this.inbox();
    const close = await this.firstOf(f, SEL.replyBar);
    if (close) await close.click().catch(() => {});
  }

  /**
   * A reaction on one message of the open conversation, by its place on the page (idx): its React button shows on
   * hover, and opens TikTok's twelve, each a data-emoji. Picking one already there takes it back.
   */
  async react(idx, emoji) {
    const f = await this.inbox();
    let items = [];
    for (const s of SEL.message) { items = await f.$$(s).catch(() => []); if (items.length) break; }
    const el = items[idx];
    if (!el) return { ok: false, reason: "that message is not on TikTok's page any more" };
    // A tab behind another is not drawn, and a hover there waits for a frame that never comes.
    await this.page.bringToFront().catch(() => {});
    const within = (p) => Promise.race([p.catch(() => {}), delay(6000)]);
    await el.evaluate((e) => e.scrollIntoView({ block: "center" })).catch(() => {});
    await delay(300);
    await within(el.hover());
    await delay(400 + Math.random() * 300);
    const btn = await this.firstOf(el, SEL.reactionButton);
    if (!btn) return { ok: false, reason: "TikTok has no reactions on this message" };
    await within(btn.hover());
    await delay(700);
    const want = `[data-emoji="${String(emoji).replace(/"/g, "")}"]`;
    let choice = await f.$(want).catch(() => null);
    if (!choice) {
      await btn.click().catch(() => {});
      await delay(600);
      choice = await f.$(want).catch(() => null);
    }
    if (!choice) return { ok: false, reason: "TikTok has no such reaction" };
    await choice.click();
    await delay(900);
    return { ok: true };
  }

  // ── Message requests, follows ───────────────────────────────────────────────

  /** "Message requests" at the top of the list, opened; false when there is none. */
  async openRequests() {
    const f = await this.openInbox();
    return await f.evaluate((sels) => {
      let el = null;
      for (const s of sels) { el = document.querySelector(s); if (el && el.getClientRects().length) break; el = null; }
      if (!el) el = [...document.querySelectorAll("p, span, div")].find((e) => !e.children.length && /^(message requests|demandes de message)/i.test((e.innerText || "").trim()));
      if (!el) return false;
      (el.closest('[role="button"], button, a, [class*="Item"]') || el).click();
      return true;
    }, SEL.requestHeader).catch(() => false);
  }

  /** The message requests waiting: [{ name, preview, avatar }]. */
  async messageRequests() {
    const opened = await this.openRequests();
    if (!opened) return [];
    await delay(1800);
    const rows = await this.listConversations().catch(() => []);
    // Back to the inbox, for the rest of the pass.
    await this.goto(`https://www.tiktok.com/messages?lang=${this.lang}`);
    return rows.map((r) => ({ name: r.name, preview: r.preview, avatar: r.avatar, handle: r.handle }));
  }

  /** Accept a message request, or delete it, by the name it shows. */
  async answerRequest(name, accept) {
    await this.openRequests();
    await delay(1800);
    const rows = await this.listConversations().catch(() => []);
    const row = rows.find((r) => r.name === name);
    if (!row || !(await this.openRow(row))) return { ok: false, reason: "that request is not there any more" };
    // The request's own box: Delete first, Accept last, in any language; the words only where it is not there.
    const done = await (await this.inbox()).evaluate((sels, accept) => {
      let box = null;
      for (const s of sels) { box = document.querySelector(s); if (box) break; }
      const buttons = box ? [...box.querySelectorAll('[role="button"], button')] : [];
      let b = buttons.length >= 2 ? (accept ? buttons[buttons.length - 1] : buttons[0]) : null;
      if (!b) {
        const want = accept ? /^(accept|accepter)$/i : /^(delete|supprimer|decline|refuser)$/i;
        b = [...document.querySelectorAll('button, [role="button"]')].find((x) => want.test((x.innerText || "").trim()));
      }
      if (!b) return false;
      b.click();
      return true;
    }, SEL.requestBox, accept).catch(() => false);
    await delay(1500);
    if (!accept) {
      // TikTok asks "Delete this request?" once more: its dialog's last button.
      await (await this.inbox()).evaluate(() => {
        const dlg = [...document.querySelectorAll('[role="dialog"], [class*="Modal"]')].pop();
        const bs = dlg ? [...dlg.querySelectorAll('button, [role="button"]')] : [];
        const b = bs.reverse().find((x) => /^(delete|supprimer)$/i.test((x.innerText || "").trim())) || bs[0];
        if (b) b.click();
      }).catch(() => {});
    }
    await this.goto(`https://www.tiktok.com/messages?lang=${this.lang}`);
    return done ? { ok: true } : { ok: false, reason: accept ? "TikTok's Accept was not there" : "TikTok's Delete was not there" };
  }

  /** Follow someone by their @handle. { ok, reason } */
  async follow(handle) {
    const h = String(handle || "").trim().replace(/^@/, "").toLowerCase();
    if (!/^[a-z0-9._]{2,24}$/.test(h)) return { ok: false, reason: "That is not a TikTok username" };
    if (!(await this.goto(`https://www.tiktok.com/@${h}?lang=${this.lang}`))) return { ok: false, reason: "TikTok did not open their profile" };
    const state = await this.page.evaluate((sels) => {
      if (/couldn.?t find this account|ce compte est introuvable/i.test(document.body?.innerText || "")) return "none";
      // The profile's own button is the topmost; suggested accounts further down carry the same marker.
      let b = null;
      for (const s of sels) {
        const all = [...document.querySelectorAll(s)].filter((x) => x.getClientRects().length);
        if (all.length) { b = all.sort((x, y) => x.getBoundingClientRect().top - y.getBoundingClientRect().top)[0]; break; }
      }
      if (!b) b = [...document.querySelectorAll("button")].find((x) => /^(follow|follow back|suivre|suivre en retour)$/i.test((x.innerText || "").trim()));
      if (!b) return "nobutton";
      const t = (b.innerText || "").trim();
      if (/following|friends|abonn|amis|message/i.test(t) && !/^follow/i.test(t)) return "already";
      b.click();
      return "clicked";
    }, SEL.followButton).catch(() => "nobutton");
    if (state === "none") return { ok: false, reason: "Nobody on TikTok has that username" };
    if (state === "already") return { ok: false, reason: "Already following them" };
    if (state !== "clicked") return { ok: false, reason: "TikTok showed no Follow button" };
    await delay(1500);
    return { ok: true };
  }

  /** Who it has tried to follow back in the last day, by handle: kept in a file, so a restart does not try them all
   *  again either. */
  followTried() {
    const file = path.join(this.dataDir || ".", "cache", `tiktok_followback_${this.account}.json`);
    if (!this._followTried) {
      try { this._followTried = JSON.parse(fs.readFileSync(file, "utf-8")) || {}; } catch { this._followTried = {}; }
    }
    const now = Date.now();
    for (const [h, at] of Object.entries(this._followTried)) if (now - at > 24 * 3600 * 1000) delete this._followTried[h];
    return { tried: this._followTried, file };
  }

  noteFollowTried(handle) {
    if (!handle) return;
    const { tried, file } = this.followTried();
    tried[handle] = Date.now();
    try {
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, JSON.stringify(tried));
    } catch { /* kept for this run */ }
  }

  /**
   * The first Follow back button on the page whose person has not been tried today, pressed as a person presses it
   * (a click made up inside the page does nothing for a follow), then looked at again: it reads Friends or Following
   * once TikTok took it. { handle, took }, or null when there is none left to press.
   */
  async pressFollowBack(find) {
    const { tried } = this.followTried();
    const href = await this.page.evaluate(find, SEL, Object.keys(tried)).catch(() => "");
    if (!href) return null;
    const handle = handleFromHref(href) || "";
    const btn = await this.page.$('[data-llm-fb="1"]');
    if (!btn) return null;
    await btn.click().catch(() => {});
    await delay(1800 + Math.random() * 800);
    const took = await this.page.evaluate(() => {
      const b = document.querySelector('[data-llm-fb="1"]');
      if (!b || !b.isConnected) return true;     // its row went: followed
      b.removeAttribute("data-llm-fb");
      return /friends|amis|following|abonn|message/i.test((b.innerText || "").trim());
    }).catch(() => false);
    this.noteFollowTried(handle);
    return { handle: handle || "someone", took };
  }

  /**
   * Follow back up to `max` of the newest followers not followed yet: { done, refused }, by handle, refused being
   * the ones TikTok did not take. TikTok's activity panel lists new followers, each with Follow back (follow-back)
   * beside a link to them; the profile's followers list is the way when the panel has none.
   */
  async followBack(max = 3) {
    const done = [], refused = [];
    if (!this.handle) return { done, refused };
    // In the page: the first button not tried today, marked to be pressed from outside it.
    const inPanel = (sel, skip) => {
      for (const old of document.querySelectorAll("[data-llm-fb]")) old.removeAttribute("data-llm-fb");
      const btns = sel.followBackButton.flatMap((s) => [...document.querySelectorAll(s)])
        .filter((x) => x.getClientRects().length && !/friends|amis|following|abonn/i.test(x.innerText || ""));
      for (const b of btns) {
        let row = null;
        for (const s of sel.activityItem) { row = b.closest(s); if (row) break; }
        const a = (row || b.parentElement)?.querySelector('a[href*="/@"]');
        const href = a ? a.getAttribute("href") || "" : "";
        const h = ((href.match(/\/@([^/?#]+)/) || [])[1] || "").toLowerCase();
        if (h && skip.includes(h)) continue;
        b.setAttribute("data-llm-fb", "1");
        return href || "?";
      }
      return "";
    };
    const inList = (sel, skip) => {
      for (const old of document.querySelectorAll("[data-llm-fb]")) old.removeAttribute("data-llm-fb");
      const dlg = document.querySelector('[role="dialog"], [class*="Modal"]') || document;
      for (const b of dlg.querySelectorAll("button")) {
        if (!/^(follow back|suivre en retour)$/i.test((b.innerText || "").trim())) continue;
        const row = b.closest("li, [class*='Item'], div");
        const a = row ? row.querySelector('a[href*="/@"]') : null;
        const href = a ? a.getAttribute("href") || "" : "";
        const h = ((href.match(/\/@([^/?#]+)/) || [])[1] || "").toLowerCase();
        if (h && skip.includes(h)) continue;
        b.setAttribute("data-llm-fb", "1");
        return href || "?";
      }
      return "";
    };
    const pressSome = async (find) => {
      for (let i = 0; i < max; i++) {
        const r = await this.pressFollowBack(find);
        if (!r) break;
        (r.took ? done : refused).push(r.handle);
        await delay(4000 + Math.random() * 6000);
      }
    };
    try {
      await this.openInbox();
      const opened = await this.page.evaluate((sels) => {
        for (const s of sels) { const b = document.querySelector(s); if (b) { b.click(); return true; } }
        return false;
      }, SEL.activityButton).catch(() => false);
      if (opened) {
        await delay(1500 + Math.random() * 800);
        await this.page.evaluate((sels) => {
          for (const s of sels) { const t = document.querySelector(s); if (t) { t.click(); return; } }
        }, SEL.activityFollowers).catch(() => {});
        await delay(1800);
        await pressSome(inPanel);
        await this.page.keyboard.press("Escape").catch(() => {});
      }
    } catch { /* the profile's list, below */ }
    if (done.length || refused.length) return { done, refused };
    if (!(await this.goto(`https://www.tiktok.com/@${this.handle}?lang=${this.lang}`))) return { done, refused };
    const opened = await this.page.evaluate((sels) => {
      for (const s of sels) { const e = document.querySelector(s); if (e) { (e.closest("div, a, span") || e).click(); return true; } }
      return false;
    }, SEL.followersCount).catch(() => false);
    if (!opened) return { done, refused };
    await delay(2500);
    await pressSome(inList);
    return { done, refused };
  }

  // ── Comments on the account's own videos ────────────────────────────────────

  async ownVideos(n = 3) {
    if (!this.handle) return [];
    const page = await this.sidePage();
    if (!(await this.goto(`https://www.tiktok.com/@${this.handle}?lang=${this.lang}`, page))) return [];
    return await page.evaluate((sels, n) => {
      for (const s of sels) {
        const links = [...document.querySelectorAll(s)].map((a) => a.href).filter((h) => /\/video\/\d+/.test(h));
        if (links.length) return [...new Set(links)].slice(0, n);
      }
      return [];
    }, SEL.videoLink, n).catch(() => []);
  }

  /**
   * The top-level comments on a video: [{ handle, name, text, index }]. Its comments panel is opened if it is shut.
   * In the side tab (its own videos), or the tab given (the out tab, for someone else's).
   */
  async readComments(videoUrl, page = null) {
    page = page || (await this.sidePage());
    if (!page.url().startsWith(videoUrl.split("?")[0])) {
      if (!(await this.goto(videoUrl, page))) return [];
    }
    await page.evaluate(() => {
      if (document.querySelector('[data-e2e="comment-level-1"]')) return;
      const b = document.querySelector('[data-e2e="comment-icon"], [data-e2e="browse-comment-icon"]');
      if (b) (b.closest("button") || b).click();
    }).catch(() => {});
    await delay(2500);
    return await page.evaluate((sel) => {
      const pickAll = (sels) => { for (const s of sels) { try { const a = [...document.querySelectorAll(s)]; if (a.length) return a; } catch { /* bad */ } } return []; };
      // The words are comment-level-1; its author (comment-username-1) and Reply (comment-reply-1) sit beside it in the
      // comment's own block, the nearest ancestor holding all three.
      return pickAll(sel.comment).slice(0, 40).map((c, index) => {
        let block = c;
        for (let i = 0; i < 6 && block.parentElement; i++) {
          block = block.parentElement;
          if (block.querySelector('[data-e2e="comment-username-1"]') && block.querySelector('[data-e2e="comment-reply-1"]')) break;
        }
        const who = block.querySelector('[data-e2e="comment-username-1"]');
        const link = who ? (who.closest("a") || who.querySelector("a")) : block.querySelector('a[href*="/@"]');
        const m = link ? (link.getAttribute("href") || "").match(/\/@([A-Za-z0-9._]{2,24})/) : null;
        return { index, handle: m ? m[1].toLowerCase() : "", name: (who?.innerText || "").trim(), text: (c.innerText || "").trim() };
      }).filter((c) => c.text);
    }, SEL).catch(() => []);
  }

  /** A public reply to one comment of the video open in the side tab (or the tab given). */
  async replyToComment(index, text, { dryRun = false, page = null } = {}) {
    page = page || (await this.sidePage());
    const opened = await page.evaluate((sel, index) => {
      const pickAll = (sels) => { for (const s of sels) { try { const a = [...document.querySelectorAll(s)]; if (a.length) return a; } catch { /* bad */ } } return []; };
      const c = pickAll(sel.comment)[index];
      if (!c) return false;
      c.scrollIntoView({ block: "center" });
      let wrap = c;
      for (let i = 0; i < 6 && wrap.parentElement; i++) {
        wrap = wrap.parentElement;
        if (wrap.querySelector('[data-e2e="comment-reply-1"]')) break;
      }
      let b = null;
      for (const s of sel.commentReply) { b = wrap.querySelector(s); if (b) break; }
      if (!b) b = [...wrap.querySelectorAll('[role="button"], span, button')].find((x) => /^(reply|répondre|repondre)$/i.test((x.innerText || "").trim()));
      if (!b) return false;
      b.click();
      return true;
    }, SEL, index).catch(() => false);
    if (!opened) return { ok: false, reason: "TikTok's Reply was not there" };
    await delay(900);
    let input = null;
    for (const s of SEL.commentInput) { input = await page.$(s).catch(() => null); if (input) break; }
    if (!input) return { ok: false, reason: "TikTok's comment box was not there" };
    await input.click();
    for (const ch of String(text)) await page.keyboard.type(ch, { delay: typeDelay() });
    if (dryRun) {
      await page.keyboard.down("Control"); await page.keyboard.press("a"); await page.keyboard.up("Control");
      await page.keyboard.press("Backspace");
      console.log(`${this.tag} (dry run) would have replied: ${String(text).slice(0, 120)}`);
      return { ok: true, dry: true };
    }
    await delay(500);
    const posted = await page.evaluate((sels) => {
      for (const s of sels) { const e = document.querySelector(s); if (e) { e.click(); return true; } }
      return false;
    }, SEL.commentPost).catch(() => false);
    if (!posted) await page.keyboard.press("Enter");
    await delay(2000);
    return { ok: true };
  }

  // ── Going out: other people's posts, in the out tab ─────────────────────────

  /** Someone's newest posts as their profile shows them: [{ id, kind, url, cover, caption, views, pinned }]. */
  async profilePosts(handle, n = 6) {
    const h = String(handle || "").trim().replace(/^@/, "").toLowerCase();
    if (!/^[a-z0-9._]{2,24}$/.test(h)) return [];
    const page = await this.outPage();
    if (!(await this.goto(`https://www.tiktok.com/@${h}?lang=${this.lang}`, page))) return [];
    // The grid comes in after the page, and its view counts a moment after the grid: looked for a few times.
    let posts = [];
    for (let i = 0; i < 8; i++) {
      posts = await page.evaluate(postsInPage, SEL, n).catch(() => []);
      if (posts.length && (posts.some((p) => p.views) || i >= 5)) return posts;
      await delay(1200);
    }
    return posts;
  }

  /** A video's page open in the out tab, its item drawn: { page, id, item } (item from feedInPage), or null. */
  async openVideo(url) {
    const id = (String(url || "").match(/\/(?:video|photo)\/(\d{6,25})/) || [])[1];
    if (!id) return null;
    const page = await this.outPage();
    if (!page.url().includes(id) && !(await this.goto(url, page))) return null;
    for (let i = 0; i < 10; i++) {
      const items = await page.evaluate(feedInPage, SEL).catch(() => []);
      // A photo post's item may not say its id: the page's first item is the post the page is for.
      const item = items.find((x) => x.id === id) || (items[0] && !items[0].id ? items[0] : null);
      if (item) return { page, id, item };
      await delay(800);
    }
    return null;
  }

  async itemNow(page, id) {
    const items = await page.evaluate(feedInPage, SEL).catch(() => []);
    return items.find((x) => x.id === id) || (items[0] && !items[0].id ? items[0] : null);
  }

  /** Like (`which` "likeButton", state "liked") or save ("saveButton", "saved") a video, after a moment on it. */
  async pressVideo(url, which, state, { dryRun = false, watchMs = 0 } = {}) {
    const v = await this.openVideo(url);
    if (!v) return { ok: false, reason: "TikTok did not open the video" };
    const word = which === "likeButton" ? "Like" : "Favorites";
    if (v.item[state] === null) return { ok: false, reason: `TikTok's ${word} was not there` };
    if (v.item[state]) return { ok: true, already: true };
    await delay(watchMs || 2000 + Math.random() * 5000);           // watched a moment first, as a thumb would
    if (dryRun) {
      console.log(`${this.tag} (dry run) would have pressed ${word} on ${url}`);
      return { ok: true, dry: true };
    }
    if (!(await v.page.evaluate(pressInPage, SEL, v.id, which).catch(() => false))) return { ok: false, reason: `TikTok's ${word} was not there` };
    await delay(1500);
    const after = await this.itemNow(v.page, v.id);
    return after && after[state] ? { ok: true } : { ok: false, reason: `TikTok did not take the ${word === "Like" ? "like" : "save"}` };
  }

  likeVideo(url, opts = {}) {
    return this.pressVideo(url, "likeButton", "liked", opts);
  }

  saveVideo(url, opts = {}) {
    return this.pressVideo(url, "saveButton", "saved", opts);
  }

  /** The comment box of the open video, opened when it is shut. */
  async commentBox(page, id) {
    const find = async () => {
      for (const s of SEL.commentInput) {
        const e = await page.$(s).catch(() => null);
        if (e) return e;
      }
      return null;
    };
    let box = await find();
    if (!box) {
      await page.evaluate(pressInPage, SEL, id, "commentButton").catch(() => false);
      await delay(2500);
      box = await find();
    }
    return box;
  }

  /** Type into a box of a page: clicked (a page that draws, the out tab), else focused in it. */
  async typeInto(page, box, text) {
    const clicked = await Promise.race([box.click().then(() => true), delay(4000).then(() => false)]).catch(() => false);
    if (!clicked) await page.evaluate((e) => e.focus(), box).catch(() => {});
    await delay(300 + Math.random() * 400);
    for (const ch of String(text)) await page.keyboard.type(ch, { delay: typeDelay() });
  }

  async clearTyped(page) {
    await page.keyboard.down("Control");
    await page.keyboard.press("a");
    await page.keyboard.up("Control");
    await page.keyboard.press("Backspace");
  }

  /** A comment under someone's video, in public. Looked for after, to know it went. { ok, dry, unconfirmed, reason } */
  async commentOnVideo(url, text, { dryRun = false } = {}) {
    const words = String(text || "").replace(/\s+/g, " ").trim().slice(0, 150);
    if (!words) return { ok: false, reason: "nothing to say" };
    const v = await this.openVideo(url);
    if (!v) return { ok: false, reason: "TikTok did not open the video" };
    const box = await this.commentBox(v.page, v.id);
    if (!box) return { ok: false, reason: "TikTok's comment box was not there" };
    await delay(1500 + Math.random() * 3000);
    await this.typeInto(v.page, box, words);
    if (dryRun) {
      await this.clearTyped(v.page);
      console.log(`${this.tag} (dry run) would have commented on ${url}: ${words.slice(0, 120)}`);
      return { ok: true, dry: true };
    }
    await delay(500 + Math.random() * 700);
    const posted = await v.page.evaluate(clickShownInPage, SEL.commentPost).catch(() => false);
    if (!posted) await v.page.keyboard.press("Enter");
    await delay(2500);
    const seen = await v.page.evaluate((sel, handle, start) => {
      for (const s of sel.commentAuthor) {
        for (const who of document.querySelectorAll(s)) {
          const link = who.closest("a") || who.querySelector("a");
          if (!(link?.getAttribute("href") || "").toLowerCase().includes(`/@${handle}`)) continue;
          let block = who;
          for (let i = 0; i < 6 && block.parentElement; i++) {
            block = block.parentElement;
            if (block.querySelector('[data-e2e="comment-level-1"]')) break;
          }
          if ((block.innerText || "").includes(start)) return true;
        }
      }
      return false;
    }, SEL, this.handle, words.slice(0, 20)).catch(() => false);
    return seen ? { ok: true } : { ok: true, unconfirmed: true };
  }

  // ── For You, in the out tab ─────────────────────────────────────────────────

  /** For You open, and the video in view: { id, handle, url, caption, liked, saved } or null. */
  async forYou() {
    const page = await this.outPage();
    if (!/\/foryou/.test(page.url())) {
      if (!(await this.goto(`https://www.tiktok.com/foryou?lang=${this.lang}`, page))) return null;
      await delay(2500);
    }
    return await this.forYouNow();
  }

  /** The For You video in view: the one playing, else the one nearest the top. */
  async forYouNow() {
    const page = await this.outPage();
    const items = await page.evaluate(feedInPage, SEL).catch(() => []);
    const now = items.find((x) => x.playing)
      || items.filter((x) => x.top > -x.height / 2).sort((a, b) => Math.abs(a.top) - Math.abs(b.top))[0];
    if (!now || !now.id) return null;
    return { ...now, url: now.handle ? `https://www.tiktok.com/@${now.handle}/video/${now.id}` : "" };
  }

  /** On to the next video, as a thumb would: TikTok's own down arrow, else the key. */
  async forYouNext() {
    const page = await this.outPage();
    const clicked = await page.evaluate(clickShownInPage, SEL.feedNext).catch(() => false);
    if (!clicked) await page.keyboard.press("ArrowDown").catch(() => {});
    await delay(1200 + Math.random() * 800);
  }

  /** Like the For You video in view. */
  async forYouLike(id, { dryRun = false } = {}) {
    const page = await this.outPage();
    if (dryRun) {
      console.log(`${this.tag} (dry run) would have liked a For You video`);
      return { ok: true, dry: true };
    }
    if (!(await page.evaluate(pressInPage, SEL, id, "likeButton").catch(() => false))) return { ok: false, reason: "no Like" };
    await delay(1200);
    const after = await this.itemNow(page, id);
    return after && after.liked ? { ok: true } : { ok: false, reason: "TikTok did not take the like" };
  }

  // ── Someone else's LIVE, as a viewer, in the out tab ────────────────────────

  /** Their LIVE open in the out tab: { live, name } (live false when they are not live). */
  async openLive(handle) {
    const h = String(handle || "").trim().replace(/^@/, "").toLowerCase();
    if (!/^[a-z0-9._]{2,24}$/.test(h)) return { live: false };
    const page = await this.outPage();
    if (!(await this.goto(`https://www.tiktok.com/@${h}/live?lang=${this.lang}`, page))) return { live: false };
    await delay(2500);
    return await this.liveThere();
  }

  /** Whether the LIVE open in the out tab is still on, and its host's name. */
  async liveThere() {
    const page = await this.outPage();
    return await page.evaluate((sel) => {
      const words = (document.body?.innerText || "").slice(0, 6000);
      if (/live has ended|this live has ended|isn.?t live|is not live|n.?est pas en live|le live est terminé/i.test(words)) return { live: false };
      const first = (sels) => { for (const s of sels) { const e = document.querySelector(s); if (e) return e; } return null; };
      return { live: !!first(sel.liveChatList), name: (first(sel.liveHost)?.innerText || "").trim() };
    }, SEL).catch(() => ({ live: false }));
  }

  /** A few hearts for the LIVE being watched, as viewers tap them. */
  async liveHearts(times = 3) {
    const page = await this.outPage();
    let n = 0;
    for (let i = 0; i < times; i++) {
      if (!(await page.evaluate(clickShownInPage, SEL.liveHeart).catch(() => false))) break;
      n++;
      await delay(250 + Math.random() * 600);
    }
    return n;
  }

  /** Follow the host of the LIVE being watched: true when it did, or already did. */
  async followLiveHost() {
    const page = await this.outPage();
    return await page.evaluate((sels) => {
      for (const s of sels) {
        const b = document.querySelector(s);
        if (!b) continue;
        const t = (b.innerText || "").trim();
        if (/following|friends|abonné|amis/i.test(t)) return true;
        if (/follow|suivre/i.test(t)) { b.click(); return true; }
      }
      return false;
    }, SEL.liveFollow).catch(() => false);
  }

  /** The accounts it follows that are LIVE now, from the LIVE page's "Following" list: their @handles. */
  async followingLive() {
    const page = await this.outPage();
    if (!(await this.goto(`https://www.tiktok.com/live?lang=${this.lang}`, page))) return [];
    await delay(2500);
    return await page.evaluate((sel) => {
      const out = [];
      for (const s of sel.liveChannel) {
        for (const c of document.querySelectorAll(s)) {
          let title = "";
          for (const t of sel.liveChannelTitle) { title = c.querySelector(t)?.innerText || title; }
          if (!/following|abonnements|suivis/i.test(title)) continue;
          for (const a of c.querySelectorAll('a[href*="/live"]')) {
            const m = (a.getAttribute("href") || "").match(/\/@([A-Za-z0-9._]{2,24})\/live/);
            if (m) out.push(m[1].toLowerCase());
          }
        }
      }
      return [...new Set(out)];
    }, SEL).catch(() => []);
  }

  // ── Mentions ────────────────────────────────────────────────────────────────

  /** Comments that mention the account, from the activity panel's Mentions tab: [{ handle, name, text, video }]. */
  async mentions() {
    const page = await this.outPage();
    if (!/tiktok\.com\/(foryou|explore|following|@)/.test(page.url())) {
      if (!(await this.goto(`https://www.tiktok.com/foryou?lang=${this.lang}`, page))) return [];
    }
    if (!(await page.evaluate(clickShownInPage, SEL.activityButton).catch(() => false))) return [];
    await delay(1800 + Math.random() * 800);
    await page.evaluate(clickShownInPage, SEL.activityTab.mentions).catch(() => false);
    await delay(2200);
    const rows = await page.evaluate((sel) => {
      const lists = sel.activityList.flatMap((s) => [...document.querySelectorAll(s)]).filter((x) => x.getClientRects().length);
      const out = [];
      for (const row of (lists[0] ? [...lists[0].querySelectorAll(sel.activityItem.join(", "))] : []).slice(0, 15)) {
        const content = (sel.activityContent.map((s) => row.querySelector(s)).find(Boolean)?.innerText || "").trim();
        // "mentioned you in a comment: words" (a tag in a video has no words to answer).
        const m = content.match(/^(?:mentioned you in a comment|vous a mentionné dans un commentaire|t'a mentionné dans un commentaire)\s*[:：]\s*([\s\S]+)$/i);
        if (!m) continue;
        const links = [...row.querySelectorAll("a[href]")].map((a) => a.getAttribute("href") || "");
        const who = links.map((h) => h.match(/^\/@([A-Za-z0-9._]{2,24})(?:[?/]|$)/)).find((x) => x && !/\/video\//.test(x.input));
        const video = links.find((h) => /\/(video|photo)\/\d+/.test(h)) || "";
        out.push({
          handle: who ? who[1].toLowerCase() : "", name: (sel.activityTitle.map((s) => row.querySelector(s)).find(Boolean)?.innerText || "").trim(),
          text: m[1].trim().slice(0, 300), video: video ? new URL(video, location.origin).href.split("?")[0] : "",
        });
      }
      return out;
    }, SEL).catch(() => []);
    await page.keyboard.press("Escape").catch(() => {});
    return rows.filter((r) => r.handle && r.video && r.handle !== this.handle);
  }

  // ── Posting ─────────────────────────────────────────────────────────────────

  /**
   * Post a video: TikTok Studio's upload page, the file, the caption, who can watch it, then Post, and TikTok's word
   * that it went. `dryRun` fills everything in and leaves the page without posting. { ok, dry, reason }
   */
  async postVideo(file, caption, { privacy = "everyone", dryRun = false } = {}) {
    if (!file || !fs.existsSync(file)) return { ok: false, reason: "That video is not on this computer any more" };
    const page = await this.outPage();
    if (!(await this.goto(`https://www.tiktok.com/tiktokstudio/upload?from=webapp&lang=${this.lang}`, page))) {
      return { ok: false, reason: "TikTok Studio did not open" };
    }
    let input = null;
    for (let i = 0; i < 8 && !input; i++) {
      for (const s of SEL.uploadInput) { input = await page.$(s).catch(() => null); if (input) break; }
      if (!input) await delay(1500);
    }
    if (!input) return { ok: false, reason: "TikTok Studio's upload box was not there" };
    await input.uploadFile(file);
    // The form, once TikTok has the file; Post works once the upload is done ("Uploaded (1.9MB)").
    const ready = async () => await page.evaluate((sel) => {
      const first = (sels) => { for (const s of sels) { const e = document.querySelector(s); if (e) return e; } return null; };
      const post = first(sel.uploadPost);
      const words = document.body?.innerText || "";
      return { form: !!post, uploaded: /\buploaded\b|téléchargé|importé/i.test(words) && !/\buploading\b|en cours d/i.test(words),
               disabled: !post || post.disabled || post.getAttribute("aria-disabled") === "true" };
    }, SEL).catch(() => ({ form: false, uploaded: false, disabled: true }));
    let state = await ready();
    for (let i = 0; i < 150 && (!state.form || state.disabled || !state.uploaded); i++) {
      await delay(2000);
      state = await ready();
    }
    // Whatever stops it from here on, the upload is thrown away rather than left half done.
    const fail = async (reason) => {
      await this.discardUpload(page);
      return { ok: false, reason };
    };
    if (!state.form) return await fail("TikTok Studio did not take the video");
    // TikTok's own prompts over the form: automatic checks declined (left as they were), tips closed.
    await page.evaluate(() => {
      for (const dlg of document.querySelectorAll('[role="dialog"], [class*="modal" i]')) {
        if (!dlg.getClientRects().length || !/automatic content checks|vérifications automatiques/i.test(dlg.innerText || "")) continue;
        const cancel = [...dlg.querySelectorAll("button")].find((b) => /^(cancel|annuler)$/i.test((b.innerText || "").trim()));
        if (cancel) cancel.click();
      }
      const tip = [...document.querySelectorAll("button")].find((b) => /^(got it|compris)$/i.test((b.innerText || "").trim()) && b.getClientRects().length);
      if (tip) tip.click();
    }).catch(() => {});
    await delay(800);
    // The caption: TikTok fills in the file's name; replaced with the persona's.
    let editor = null;
    for (const s of SEL.uploadCaption) { editor = await page.$(s).catch(() => null); if (editor) break; }
    if (!editor) return await fail("TikTok Studio's caption box was not there");
    await this.typeInto(page, editor, "");
    await this.clearTyped(page);
    for (const ch of String(caption || "").slice(0, 2000)) await page.keyboard.type(ch, { delay: typeDelay() });
    await delay(800);
    // Who can see it: TikTok's combobox, opened with the pointer, and its option picked by its first line.
    if (privacy !== "everyone") {
      let combo = null;
      for (const s of SEL.uploadPrivacy) { combo = await page.$(s).catch(() => null); if (combo) break; }
      if (combo) await Promise.race([combo.click(), delay(4000)]).catch(() => {});
      await delay(900);
      const picked = await page.evaluate((privacy) => {
        const want = { friends: /^(friends|amis)$/i, only_me: /^(only you|only me|private|moi uniquement|vous uniquement|privé)$/i }[privacy];
        const option = [...document.querySelectorAll('[role="option"]')].find((o) => want && want.test((o.innerText || "").split("\n")[0].trim()));
        if (option) { option.click(); return true; }
        return false;
      }, privacy).catch(() => false);
      if (!picked) return await fail("TikTok Studio's who-can-see choice was not there; nothing was posted");
      await delay(700);
    }
    if (state.disabled || !state.uploaded) return await fail("TikTok Studio was still taking the video; nothing was posted");
    if (dryRun) {
      console.log(`${this.tag} (dry run) would have posted ${path.basename(file)}: ${String(caption || "").slice(0, 120)}`);
      await this.discardUpload(page);
      return { ok: true, dry: true };
    }
    await page.evaluate(clickShownInPage, SEL.uploadPost);
    // Its word that it went: Studio moves on to its posts, or says so.
    for (let i = 0; i < 60; i++) {
      await delay(2000);
      const done = await page.evaluate(() => /\/tiktokstudio\/content/.test(location.pathname)
        || /your video (has been|is being) (posted|uploaded)|video published|vidéo publiée|manage your posts/i.test(document.body?.innerText || "")).catch(() => false);
      if (done) return { ok: true };
    }
    return { ok: false, reason: "TikTok Studio did not say the video was posted; look in TikTok Studio" };
  }

  /** The upload on Studio's page thrown away, with its own Discard and the "Discard this post?" that follows. */
  async discardUpload(page) {
    await page.evaluate(clickShownInPage, SEL.uploadDiscard).catch(() => false);
    await delay(1500);
    await page.evaluate(() => {
      for (const dlg of document.querySelectorAll('[role="dialog"], [class*="modal" i]')) {
        if (!dlg.getClientRects().length) continue;
        const b = [...dlg.querySelectorAll("button")].find((x) => /^(discard|supprimer|abandonner)$/i.test((x.innerText || "").trim()));
        if (b) { b.click(); return; }
      }
    }).catch(() => {});
    await delay(1500);
    await this.goto("about:blank", page).catch(() => {});
  }

  // ── LIVE ────────────────────────────────────────────────────────────────────

  /** The tab for the account's own things: its LIVE, the comments under its videos, its settings. */
  async sidePage() {
    if (this.usable(this.side)) return this.side;
    const old = this.side;
    this.side = await this.newTab();
    if (old && !old.isClosed()) await old.close().catch(() => {});
    return this.side;
  }

  /**
   * The tab for going out: someone's profile and videos, liking, saving and commenting, visiting a LIVE as a viewer,
   * For You, posting. One thing at a time in it (the runner's outJob); the inbox and its own LIVE keep theirs.
   */
  async outPage() {
    if (this.usable(this.out)) return this.out;
    const old = this.out;
    this.out = await this.newTab();
    if (old && !old.isClosed()) await old.close().catch(() => {});
    return this.out;
  }

  /** Whether the account is live now, its own LIVE open in the side tab when it is. */
  async liveNow() {
    if (!this.handle) return false;
    const page = await this.sidePage();
    // Its own LIVE, not whichever LIVE the tab was last on.
    if (!page.url().toLowerCase().includes(`/@${this.handle}/live`)) {
      if (!(await this.goto(`https://www.tiktok.com/@${this.handle}/live?lang=${this.lang}`, page))) return false;
    }
    return await page.evaluate((sels) => {
      if (/live has ended|n.?est pas en live|isn.?t live|le live est terminé/i.test(document.body?.innerText || "")) return false;
      for (const s of sels) if (document.querySelector(s)) return true;
      return false;
    }, SEL.liveChatList).catch(() => false);
  }

  /** The LIVE's chat as it is now: comments, gifts, follows and joins, oldest first. Its own (the side tab), or the
   * one it is visiting (the tab given). */
  async readLive(page = null) {
    page = page || (await this.sidePage());
    return await page.evaluate((sels) => {
      let list = null;
      for (const s of sels) { list = document.querySelector(s); if (list) break; }
      if (!list) return [];
      // Its lines are marked *-message; a line inside a line is part of it, not one of its own.
      let rows = [...list.querySelectorAll("[data-e2e]")].filter((e) => /-message$/.test(e.getAttribute("data-e2e"))
        && !e.parentElement?.closest('[data-e2e$="-message"]'));
      if (!rows.length) rows = [...list.children];
      return rows.slice(-80).map((row) => {
        const mark = row.getAttribute("data-e2e") || "";
        const owner = row.querySelector('[data-e2e="message-owner-name"]');
        const name = (owner?.innerText || "").trim();
        const all = (row.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean).join(" ");
        const text = name && all.startsWith(name) ? all.slice(name.length).replace(/^[\s:：]+/, "").trim() : all;
        const a = row.querySelector('a[href*="/@"]');
        const m = a ? (a.getAttribute("href") || "").match(/\/@([A-Za-z0-9._]{2,24})/) : null;
        let kind = mark === "chat-message" ? "comment" : mark === "enter-message" ? "join" : "event";
        if (kind === "event") {
          if (/gift/.test(mark) || /\bsent\b|a envoyé|×\s?\d+/i.test(all)) kind = "gift";
          else if (/followed|a suivi|s.est abonné/i.test(all)) kind = "follow";
          else if (/\bjoined\b|a rejoint/i.test(all)) kind = "join";
          else if (/shared|a partagé/i.test(all)) kind = "share";
          else if (/liked|a aimé/i.test(all)) kind = "like";
        }
        return { kind, name, handle: m ? m[1].toLowerCase() : "", text };
      });
    }, SEL.liveChatList).catch(() => []);
  }

  async sendLive(text, { dryRun = false, page = null } = {}) {
    page = page || (await this.sidePage());
    let input = null;
    for (const s of SEL.liveChatInput) { input = await page.$(s).catch(() => null); if (input) break; }
    if (!input) return { ok: false, reason: "The LIVE's chat box was not there" };
    await input.click();
    for (const ch of String(text)) await page.keyboard.type(ch, { delay: 40 + Math.random() * 90 });
    if (dryRun) {
      await page.keyboard.down("Control"); await page.keyboard.press("a"); await page.keyboard.up("Control");
      await page.keyboard.press("Backspace");
      console.log(`${this.tag} (dry run) would have said in the LIVE: ${String(text).slice(0, 120)}`);
      return { ok: true, dry: true };
    }
    await page.keyboard.press("Enter");
    await delay(600);
    // Enter sends on TikTok's LIVE chat; where it did not, its send button.
    const left = await page.evaluate((el) => (el.innerText || "").trim(), input).catch(() => "");
    if (left) {
      for (const s of SEL.liveChatSend) {
        const b = await page.$(s).catch(() => null);
        if (b) { await b.click(); break; }
      }
    }
    await delay(400);
    return { ok: true };
  }

  // ── Settings ────────────────────────────────────────────────────────────────

  /** TikTok's "Activity status" switch, set on or off; null when the site has no such switch. */
  async setActivityStatus(on) {
    const page = await this.sidePage();
    if (!(await this.goto(`https://www.tiktok.com/setting?lang=${this.lang}`, page))) return null;
    return await page.evaluate((on) => {
      const label = [...document.querySelectorAll("*")].find((e) => !e.children.length && /^(activity status|statut d.activité)$/i.test((e.innerText || "").trim()));
      if (!label) return null;
      let row = label;
      for (let i = 0; i < 5 && row; i++) {
        const sw = row.querySelector('[role="switch"], input[type="checkbox"]');
        if (sw) {
          const now = sw.getAttribute("aria-checked") === "true" || sw.checked === true;
          if (now !== on) sw.click();
          return on;
        }
        row = row.parentElement;
      }
      return null;
    }, !!on).catch(() => null);
  }

  // ── Health ──────────────────────────────────────────────────────────────────

  /** Which of the inbox's markers still match: { matched: {name: selector}, missing: [names] }. */
  async selectorHealth() {
    const f = await this.inbox();
    // The list is there with no conversations in it yet; the message box only with a conversation open.
    const names = ["conversationList"];
    if (await f.evaluate(pickIn, SEL.chatHandle).catch(() => "")) names.push("composer");
    const out = { matched: {}, missing: [] };
    for (const n of names) {
      const hit = await f.evaluate(pickIn, SEL[n]).catch(() => "");
      if (hit) out.matched[n] = hit; else out.missing.push(n);
    }
    this.health = out;
    return out;
  }

  /** A picture shown in the open conversation, saved as a file (its newest one, a photo they sent). */
  async capturePhoto(stem) {
    const f = await this.inbox();
    const handle = await f.evaluateHandle((sel) => {
      const pickAll = (sels) => { for (const s of sels) { try { const a = [...document.querySelectorAll(s)]; if (a.length) return a; } catch { /* bad */ } } return []; };
      const imgs = pickAll(sel.message).flatMap((m) => [...m.querySelectorAll("img")]).filter((i) => i.getBoundingClientRect().width > 60);
      return imgs.pop() || null;
    }, SEL).catch(() => null);
    const el = handle && handle.asElement ? handle.asElement() : null;
    if (!el) return "";
    const dir = path.join(this.dataDir, "config", "temp");
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, `${stem}_${Date.now()}.png`);
    try {
      await el.screenshot({ path: file });
      return file;
    } catch {
      return "";
    }
  }

  /**
   * A video in the open conversation (one they sent from their phone, not a shared TikTok), its newest, saved as a
   * file to be watched: fetched from inside the page, where its link resolves. "" when it will not come.
   */
  async captureVideo(stem) {
    const f = await this.inbox();
    const data = await f.evaluate(async (sel) => {
      const shared = sel.sharedVideo.join(", ");
      const v = [...document.querySelectorAll("video")].filter((x) => !x.closest(shared)).pop();
      const src = v ? (v.currentSrc || v.src) : "";
      if (!src) return null;
      try {
        const r = await fetch(src);
        const buf = await r.arrayBuffer();
        if (buf.byteLength < 2000 || buf.byteLength > 40000000) return null;
        const bytes = new Uint8Array(buf);
        let s = "";
        for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
        return { b64: btoa(s), type: r.headers.get("content-type") || "" };
      } catch {
        return null;
      }
    }, SEL).catch(() => null);
    if (!data || !data.b64) return "";
    const ext = /webm/.test(data.type) ? ".webm" : /quicktime/.test(data.type) ? ".mov" : ".mp4";
    const dir = path.join(this.dataDir, "config", "temp");
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, `${stem}_${Date.now()}${ext}`);
    fs.writeFileSync(file, Buffer.from(data.b64, "base64"));
    return file;
  }

  /** A voice note in the open conversation, its newest, saved as a file to be transcribed. */
  async captureVoice(stem) {
    const f = await this.inbox();
    const data = await f.evaluate(async () => {
      const a = [...document.querySelectorAll("audio")].pop();
      const src = a ? (a.currentSrc || a.src) : "";
      if (!src) return null;
      try {
        const buf = await (await fetch(src)).arrayBuffer();
        let s = "";
        const bytes = new Uint8Array(buf);
        for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
        return { b64: btoa(s), type: (await fetch(src)).headers.get("content-type") || "" };
      } catch {
        return null;
      }
    }).catch(() => null);
    if (!data || !data.b64) return "";
    const ext = /ogg|opus/.test(data.type) ? ".ogg" : /mpeg|mp3/.test(data.type) ? ".mp3" : /wav/.test(data.type) ? ".wav" : ".m4a";
    const dir = path.join(this.dataDir, "config", "temp");
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, `${stem}_${Date.now()}${ext}`);
    fs.writeFileSync(file, Buffer.from(data.b64, "base64"));
    return file;
  }
}
