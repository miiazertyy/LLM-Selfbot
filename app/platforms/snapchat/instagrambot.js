/**
 * Instagram, driven through instagram.com in the account's own Chrome: signing in (with the account's 2FA key when it
 * has one), its inbox (www.instagram.com/direct), stories, reels, its posts and their comments.
 *
 * Instagram has no API a person's account may use for any of this, so the page is read and used the way a person
 * would: open a conversation, read it, type, press Enter. Instagram signs and sends everything itself.
 *
 * Its pages carry almost no test hooks and their class names are generated, so every lookup leans on what a page
 * must keep to work: links (/direct/t/<id>/, /<username>/, /reel/<code>/, /stories/<user>/<id>/), ARIA roles and
 * labels, input names. The UI language is kept English (en-US) so the labels match. Every marker is in SEL, and
 * selectorHealth() says which still match, so the account card can say when Instagram changed something instead of
 * going quiet.
 */
import crypto from "crypto";
import fs from "fs";
import path from "path";
import { delay, typeDelay, launchBrowser, showWindow, hideWindow, persona } from "./browser.js";
// The day labels over a run of messages read the same way on every platform (runner_core.js).
import { atOfLabel } from "./runner_core.js";

// The web app's own id, sent with the few JSON reads the page itself makes (who an account is).
export const WEB_APP_ID = "936619743392459";
export const HOME = "https://www.instagram.com/";

export const SEL = {
  // Signing in.
  loginUser: ['input[name="username"]', 'input[name="email"]', 'input[autocomplete="username"]',
              'input[aria-label*="username" i]', 'input[aria-label*="mobile" i]'],
  loginPassword: ['input[name="password"]', 'input[name="pass"]', 'input[type="password"]'],
  loginSubmit: ['button[type="submit"]', 'div[role="button"][aria-label*="log in" i]'],
  // The 2FA code (an authentication app's six digits) and a code sent by email or text. Instagram's own
  // two-step page (/accounts/login/two_step_verification, read off it 2026-10) gives its box no name, no label and
  // no autocomplete at all: codeBox() falls back to the one text box on the page, which is what a person types in.
  twoFactor: ['input[name="verificationCode"]', 'input[aria-label*="security code" i]', 'input[name="approvals_code"]',
              'input[autocomplete="one-time-code"]'],
  challengeCode: ['input[name="security_code"]', 'input[name="code"]', 'input[aria-label*="code" i]',
                  'input[autocomplete="one-time-code"]', 'input[inputmode="numeric"]'],
  // "Trust this device and skip this step from now on": ticked, so the next sign-in does not ask again.
  trustDevice: ['input[type="checkbox"][name="checkbox"]', 'input[type="checkbox"]'],
  loginError: ['#slfErrorAlert', 'div[role="alert"]', 'p[aria-atomic="true"]', '[data-testid="login-error-message"]'],

  // ── The inbox (/direct/inbox/) ──
  // Every conversation is a link to /direct/t/<id>/, which is the one thing the page cannot do without: the rows,
  // whoever they are with, and which is open all hang off that.
  // A conversation's own link, where the page has one. This build gives its rows no link at all: the id only
  // appears in the address once a row is opened, so threadLink is a bonus rather than the way in.
  threadLink: ['a[href^="/direct/t/"]', 'a[href*="/direct/t/"]'],
  // The list itself, which Instagram labels in words. Its rows are buttons: wide, about seventy tall, each with a
  // picture, a name, what was last said and when. The little notes along its top are the opposite shape, so the
  // rows are told from them by their size (readListInPage).
  threadList: ['[aria-label="Thread list"]', '[aria-label*="thread list" i]', '[aria-label*="Chats" i]',
               'div[role="list"]:has(a[href^="/direct/t/"])'],
  threadRow: ['div[role="button"]', '[role="listitem"]', 'li'],
  // Instagram marks an unread row with a dot and bolds its name; it also says so in words for a screen reader.
  threadUnread: ['[aria-label*="unread" i]', 'span[aria-label*="Unread" i]'],
  // The open conversation: its own scrolling list of messages, and the box to type in under it.
  // The open conversation. Instagram marks the whole pane as an article; inside it the messages are plain divs,
  // so they are read by where they sit (readChatInPage), as Snapchat's and TikTok's fallbacks do.
  pane: ['div[role="article"]', '[role="article"]'],
  messageList: ['div[role="grid"]', 'div[aria-label*="Messages" i]', 'div[role="log"]'],
  message: ['div[role="row"]', 'div[role="listitem"]', 'div[data-scope="messages_table"] > div'],
  messageText: ['div[dir="auto"]', 'span[dir="auto"]'],
  // The box to type in: a Lexical editor with no label and no placeholder of its own.
  composer: ['div[role="textbox"][data-lexical-editor="true"]', 'div[role="textbox"][contenteditable="true"]',
             'div[aria-label*="Message" i][contenteditable="true"]', 'textarea[placeholder*="Message" i]',
             'p[contenteditable="true"]'],
  sendButton: ['div[role="button"]:has(> div > svg[aria-label="Send" i])', 'button[type="submit"]'],
  // What a chat offers beside the box: a photo, a voice note, the heart.
  // Its file box is the way in; the button beside the composer is the fallback, and Instagram puts that label on
  // the icon rather than on the button round it ("Add Photo or Video", read off the page 2026-10), so the button is
  // reached through the icon it holds.
  mediaButton: ['input[type="file"][accept*="image"]', 'input[type="file"][accept*=".jpg"]',
                'input[type="file"]', 'div[role="button"]:has(svg[aria-label*="Add Photo" i])',
                'div[role="button"][aria-label*="Add Photo" i]',
                'div[role="button"][aria-label*="photo" i]'],
  // The same box takes sound (its accept list is "audio/*,.mp4,.mov,.png,.jpg,.jpeg"), which is how a voice note
  // goes: as a file, rather than through a microphone nobody is holding.
  audioInput: ['input[type="file"][accept*="audio"]'],
  // "Voice Clip", and again the label is on the icon, not the button.
  voiceButton: ['div[role="button"]:has(svg[aria-label*="Voice" i])',
                'div[role="button"][aria-label*="voice" i]', 'div[role="button"][aria-label*="Record" i]',
                'button[aria-label*="voice" i]'],
  // The quick heart a conversation used to carry. This build has none (its composer offers an emoji, a GIF, a
  // photo and a voice clip, nothing else), so nothing uses this; it costs nothing if one comes back.
  likeButton: ['div[role="button"][aria-label="Like" i]', 'svg[aria-label="Like" i]'],
  // On a message as the pointer passes: more (unsend, edit), react, reply.
  moreButton: ['div[role="button"][aria-label*="See more options" i]', 'div[role="button"][aria-label*="More" i]'],
  reactButton: ['div[role="button"][aria-label*="React" i]', 'div[role="button"][aria-label*="emoji" i]'],
  replyButton: ['div[role="button"][aria-label*="Reply" i]'],
  // The emoji picker a reaction opens: its search box takes any emoji by name.
  emojiSearch: ['input[placeholder*="Search emoji" i]', 'input[aria-label*="emoji" i]', 'input[type="search"]'],
  emojiOption: ['[role="option"]', '[role="button"][aria-label]'],
  // A reaction already on a message, and what the message quotes.
  reactionShown: ['div[role="button"][aria-label*="reaction" i]', 'div[aria-label*="Reactions" i]'],
  quoted: ['div[aria-label*="Replied to" i]', 'div[role="blockquote"]'],
  // Message requests, which sit behind their own link above the list.
  requestsLink: ['a[href^="/direct/requests/"]', 'a[href*="/direct/requests"]'],
  requestAccept: ['div[role="button"]', 'button'],
  // Instagram's own words when a message would not go.
  warning: ['div[role="alert"]', '[data-visualcompletion="ignore-dynamic"] div[role="alert"]'],
  // A call ringing in a conversation.
  calling: ['div[aria-label*="calling" i]', 'div[aria-label*="Incoming" i]', 'div[role="button"][aria-label*="Join" i]'],

  // ── Stories ──
  storyRing: ['div[role="button"]:has(canvas)', 'div[role="menuitem"]:has(canvas)'],
  storyNext: ['div[role="button"][aria-label="Next" i]', 'button[aria-label="Next" i]'],
  storyPause: ['div[role="button"][aria-label*="Pause" i]'],
  storyReply: ['textarea[placeholder*="Reply" i]', 'div[role="textbox"][aria-label*="Reply" i]',
               'input[placeholder*="Reply" i]'],
  storyLike: ['div[role="button"][aria-label*="Like" i]', 'svg[aria-label="Like" i]'],
  storySeen: ['a[href*="/seen_by/"]', 'div[role="button"][aria-label*="Seen by" i]'],

  // ── Reels, posts and their comments ──
  reelItem: ['div:has(> video)', 'article:has(video)'],
  // A post's or a reel's own address. The closing slash matters: the Reels page's own links are /reels/ and
  // /reels/audio/<code>/, neither of which is a reel, and "/reel" without it took an audio page for one. The Reels
  // page has no permalinks at all (its reels are videos in a feed, which is what reelItem and reelsInPage read),
  // so matching nothing there is the right answer rather than a miss.
  postLink: ['a[href^="/p/"]', 'a[href^="/reel/"]', 'a[href*="/p/"]', 'a[href*="/reel/"]'],
  postLike: ['div[role="button"]:has(svg[aria-label="Like" i])', 'span:has(svg[aria-label="Like" i])'],
  postUnlike: ['div[role="button"]:has(svg[aria-label="Unlike" i])', 'span:has(svg[aria-label="Unlike" i])'],
  postSave: ['div[role="button"]:has(svg[aria-label="Save" i])'],
  postCaption: ['h1', 'div[role="button"] + div span[dir="auto"]'],
  comment: ['ul ul[role="menu"] li', 'ul > div > li', 'article ul li'],
  commentBox: ['textarea[aria-label*="comment" i]', 'form textarea', 'div[role="textbox"][aria-label*="comment" i]'],
  commentPost: ['div[role="button"]:has(> div)', 'button[type="submit"]'],

  // ── Its own profile, its Note, its settings ──
  profileLink: ['a[href^="/"][role="link"]:has(img[alt*="profile picture" i])', 'a[href*="/?next=" i]'],
  // Its Note sits above its own picture at the top of the inbox. ":text()" is not a selector Chrome knows, so the
  // words are matched in clickSaidInPage instead; only what can be a selector is one.
  noteButton: ['div[role="button"][aria-label*="note" i]', 'div[role="button"][aria-label*="Your note" i]'],
  // Instagram's note sheet does not say "note" anywhere in its box: the placeholder is its own invitation
  // ("Share a thought...", and whatever it is next month), so the sheet it sits in is what it is found by.
  noteBox: ['div[role="dialog"] textarea', 'div[role="dialog"] div[role="textbox"]',
            'textarea[placeholder*="note" i]', 'textarea[placeholder*="thought" i]',
            'div[role="textbox"][aria-label*="note" i]'],
  activityStatus: ['input[type="checkbox"]', '[role="switch"]'],

  // ── Posting (the create flow) ──
  createButton: ['div[role="button"][aria-label*="New post" i]', 'a[href="/create/style/"]',
                 'svg[aria-label*="New post" i]'],
  createInput: ['input[type="file"][accept*="video"]', 'input[type="file"]'],
  createCaption: ['div[role="textbox"][aria-label*="caption" i]', 'textarea[aria-label*="caption" i]'],
  // The create flow's Next and Share, which are plain buttons with those words.
  createNext: ['div[role="button"]', 'button'],

  // ── Checks Instagram puts up ──
  captcha: ['iframe[src*="recaptcha"]', 'iframe[title*="challenge" i]', '#recaptcha', '[id*="captcha" i]',
            'form[action*="challenge"]'],
  suspended: ['[id*="suspended" i]', '[data-bloks-name*="suspend" i]'],
};

// What the buttons Instagram puts in the way say, in the English it is kept in.
const SAY = {
  cookies: /^(allow all cookies|allow essential and optional cookies|accept all|only allow essential cookies|decline optional cookies)$/i,
  saveLogin: /^(save info|save login info|save)$/i,
  notNow: /^(not now|not now\.|cancel|skip)$/i,
  confirm: /^(confirm|submit|next|continue|send security code|send code|verify)$/i,
  logIn: /^(log in|log into instagram|sign in)$/i,
  emailOption: /email|e-mail/i,
};

// ── 2FA: the six digits an authenticator app would show, made from the account's key (RFC 6238) ───────────────────

/** A base32 key ("G54M E4E3 ...", spaces and case as they come) as bytes; null when it is not one. */
export function base32Bytes(key) {
  const clean = String(key || "").toUpperCase().replace(/[\s-]/g, "").replace(/=+$/, "");
  if (!clean || /[^A-Z2-7]/.test(clean)) return null;
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = 0;
  let value = 0;
  const out = [];
  for (const ch of clean) {
    value = (value << 5) | alphabet.indexOf(ch);
    bits += 5;
    if (bits >= 8) {
      out.push((value >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }
  return Buffer.from(out);
}

/** The code for this moment: HMAC-SHA1 over the 30-second step, six digits. "" for a key that isn't one. */
export function totp(key, at = Date.now(), { step = 30, digits = 6, algorithm = "sha1" } = {}) {
  const secret = Buffer.isBuffer(key) ? key : base32Bytes(key);
  if (!secret || !secret.length) return "";
  const counter = Math.floor(at / 1000 / step);
  const msg = Buffer.alloc(8);
  msg.writeUInt32BE(Math.floor(counter / 2 ** 32), 0);
  msg.writeUInt32BE(counter % 2 ** 32, 4);
  const mac = crypto.createHmac(algorithm, secret).update(msg).digest();
  const off = mac[mac.length - 1] & 0x0f;
  const bin = ((mac[off] & 0x7f) << 24) | (mac[off + 1] << 16) | (mac[off + 2] << 8) | mac[off + 3];
  return String(bin % 10 ** digits).padStart(digits, "0");
}

/** Seconds the current code has left: a code typed in its last moments may be stale by the time it lands. */
export function totpLeft(at = Date.now(), step = 30) {
  return step - (Math.floor(at / 1000) % step);
}

// ── What Instagram says when it will not send something, said plainly ───────────────────────────────────────────

export const WARNINGS = [
  [/try again later|please wait a few|slow down/i, "Instagram asked it to wait a while before sending again"],
  [/action blocked|we restrict certain activity/i, "Instagram has blocked this account's actions for a while"],
  [/couldn.?t send|could not be sent|not delivered|failed to send/i, "Instagram did not send it"],
  [/can.?t message this account|cannot message|not accepting messages/i,
   "Instagram does not let this account message them"],
  [/account is restricted|restricted your account|we restricted/i, "Instagram has restricted this account"],
  [/suspended|disabled your account/i, "Instagram has suspended this account"],
  [/message request/i, "It is a message request until they accept it"],
  [/community guidelines/i, "Instagram held it back for its guidelines"],
];

export function warningReason(text) {
  for (const [re, why] of WARNINGS) if (re.test(String(text || ""))) return why;
  return "";
}

// ── People and chats ────────────────────────────────────────────────────────────────────────────────────────────

// Instagram's rule for a username: up to 30 letters, digits, dots and underscores.
const USERNAME = /^[a-z0-9._]{1,30}$/;

export function cleanUsername(name) {
  const u = String(name || "").trim().replace(/^@/, "").toLowerCase();
  return USERNAME.test(u) && !/^\.|\.$/.test(u) ? u : "";
}

/** A person's id: "ig_" and their username, dots as dashes (as TikTok's "tt_"). */
export function chatIdFor(username) {
  const u = cleanUsername(username);
  return u ? `ig_${u.replace(/\./g, "-")}` : "";
}

/** The username back out of a person's id ("ig_theo-wav" is "theo.wav"). */
export function usernameOf(chatId) {
  const s = String(chatId || "");
  return s.startsWith("ig_") ? s.slice(3).replace(/-/g, ".") : "";
}

/** A group conversation's id: "igg_" and its thread's number. */
export function groupIdFor(threadId) {
  const t = String(threadId || "").replace(/\D/g, "");
  return t ? `igg_${t}` : "";
}

/** The username a profile link points at ("/theo.wav/", "https://www.instagram.com/theo.wav/"); "" for any other page. */
export function usernameFromHref(href) {
  const m = String(href || "").match(/^(?:https?:\/\/(?:www\.)?instagram\.com)?\/([A-Za-z0-9._]{1,30})\/?(?:[?#].*)?$/);
  if (!m) return "";
  const u = m[1].toLowerCase();
  // Instagram's own pages, not people.
  return /^(direct|explore|reels|reel|p|stories|accounts|about|legal|developer|emails|challenge|session|web|api|tv|igtv|lite|privacy|terms)$/.test(u)
    ? "" : cleanUsername(u);
}

/** The thread's number in a conversation's link (/direct/t/<id>/). */
export function threadIdFromHref(href) {
  const m = String(href || "").match(/\/direct\/t\/(\d{5,40})/);
  return m ? m[1] : "";
}

// ── In the page ─────────────────────────────────────────────────────────────────────────────────────────────────
// These run inside Instagram's page and must stand alone: no closures, only their arguments.

/** The first selector of a list that matches something on the page. */
function pickIn(sels) {
  for (const s of sels) {
    let n = 0;
    try { n = document.querySelectorAll(s).length; } catch { n = 0; }
    if (n) return s;
  }
  return "";
}

/** Click the first button on the page whose words match, in any of Instagram's many button shapes. */
function clickSaidInPage(source, flags) {
  const re = new RegExp(source, flags || "i");
  const buttons = [...document.querySelectorAll('div[role="button"], button, [role="menuitem"], a[role="link"]')];
  for (const b of buttons) {
    if (!b.getClientRects().length || b.getAttribute("aria-disabled") === "true" || b.disabled) continue;
    const words = (b.innerText || b.getAttribute("aria-label") || "").trim();
    // A button holding other buttons is the container, not the one to press.
    if (re.test(words) && !b.querySelector('div[role="button"], button')) {
      b.click();
      return words.slice(0, 60) || true;
    }
  }
  return "";
}

/**
 * The conversation list, as rows.
 *
 * Instagram's own inbox gives its rows no link and no id: they are buttons in a list it labels "Thread list", and
 * a conversation's id only appears in the address once one is opened. So a row is known by where it sits and whose
 * it is, and told from the little notes along the top of the list by its shape: wide, about seventy tall, with one
 * picture, a name, what was last said and when.
 *
 * Where a build does give its rows links (/direct/t/<id>/), those are used instead, and each row carries its id.
 */
function readListInPage(sel) {
  const pick = (root, sels) => { for (const s of sels) { try { const e = root.querySelector(s); if (e) return e; } catch { /* bad */ } } return null; };
  const visible = (el) => !!el && el.getClientRects().length > 0;
  const weight = (el) => parseInt(getComputedStyle(el).fontWeight, 10) || 400;
  const isRow = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 200 && r.height > 40 && r.height < 130;
  };

  // ── Where the list is ──
  let box = pick(document, sel.threadList);
  if (!box) {
    // No label to go by: whatever holds the most row-shaped buttons.
    const counts = new Map();
    for (const b of document.querySelectorAll('div[role="button"]')) {
      if (!visible(b) || !isRow(b)) continue;
      for (let p = b.parentElement, i = 0; p && i < 5; p = p.parentElement, i++) {
        counts.set(p, (counts.get(p) || 0) + 1);
      }
    }
    box = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || null;
  }
  if (!box) return [];

  // ── Its rows ──
  let items = [];
  for (const s of sel.threadRow) {
    try { items = [...box.querySelectorAll(s)].filter((e) => visible(e) && isRow(e)); } catch { items = []; }
    if (items.length) break;
  }
  // A row inside a row is the same row: only the outermost of each.
  items = items.filter((e, i, all) => !all.some((o, j) => j !== i && o !== e && o.contains(e)));

  const out = [];
  for (const row of items) {
    const lines = (row.innerText || "").split("\n").map((t) => t.trim()).filter(Boolean);
    if (!lines.length) continue;
    const label = (row.getAttribute("aria-label") || "") + " "
      + [...row.querySelectorAll("[aria-label]")].map((e) => e.getAttribute("aria-label")).join(" ");
    const words = lines.join(" ");
    // Instagram writes the time as "3d", "2h", "now", after a dot; "Unread" is a word of its own on the row.
    const timeAt = lines.findIndex((t) => /^(now|\d+\s*[smhdwy])$/i.test(t));
    const unread = /\bunread\b/i.test(words) || /\bunread\b/i.test(label);
    const name = lines[0] || "";
    const skip = new Set(["·", "Unread", "Active now"]);
    const preview = lines.slice(1).find((t, i) => i + 1 !== timeAt && !skip.has(t)
      && !/^(now|\d+\s*[smhdwy])$/i.test(t) && !/^active\b/i.test(t)) || "";
    const link = row.querySelector('a[href*="/direct/t/"]') || row.closest('a[href*="/direct/t/"]');
    const href = link ? link.getAttribute("href") || "" : "";
    const img = row.querySelector("img");
    const imgs = [...row.querySelectorAll("img")].filter((i) => i.getBoundingClientRect().width > 20);
    const nameEl = [...row.querySelectorAll("span, div")].find((e) => !e.children.length
      && (e.innerText || "").trim() === name);
    out.push({
      // Where it sits, which is how it is opened again: Instagram gives it nothing else to be known by.
      index: out.length,
      id: (href.match(/\/direct\/t\/(\d{5,40})/) || [])[1] || "",
      href, name,
      preview: preview.replace(/\s*·\s*(now|\d+\s*[smhdwy])\s*$/i, "").trim(),
      time: timeAt > 0 ? lines[timeAt] : "",
      avatar: img ? (img.currentSrc || img.src || "") : "",
      unread,
      // Several pictures stacked, or several names, is a group.
      group: imgs.length > 1 || /,/.test(name),
      typing: /\btyping\b|is typing/i.test(words) || /\btyping\b/i.test(label),
      calling: /\bcalling\b|incoming (video )?call|ringing/i.test(words + " " + label),
      // A bolder name is Instagram's other way of saying unread, where the word is not there.
      bold: nameEl ? weight(nameEl) >= 600 : false,
      request: /\bmessage request\b/i.test(words),
    });
    if (out.length >= 60) break;
  }
  // The open conversation is the one the address names, so it is never mistaken for another.
  const open = (location.pathname.match(/\/direct\/t\/(\d{5,40})/) || [])[1] || "";
  for (const r of out) {
    r.active = !!open && r.id === open;
    r.unread = r.unread || (r.bold && !r.active);
  }
  return out;
}

/**
 * The open conversation: whose it is, its messages, and what the chat offers. Instagram's own messages sit to the
 * right of the middle and other people's to the left, which is how "mine" is told where nothing says it in words.
 */
function readChatInPage(sel, ownName) {
  const pick = (root, sels) => { for (const s of sels) { try { const e = root.querySelector(s); if (e) return e; } catch { /* bad */ } } return null; };
  const pickAll = (root, sels) => { for (const s of sels) { try { const a = [...root.querySelectorAll(s)]; if (a.length) return a; } catch { /* bad */ } } return []; };
  const visible = (el) => !!el && el.getClientRects().length > 0;
  const composer = pick(document, sel.composer);
  const thread = (location.pathname.match(/\/direct\/t\/(\d{5,40})/) || [])[1] || "";
  // The pane the conversation is drawn in, and inside it whatever scrolls: that is where the messages are.
  let box = pick(document, sel.messageList);
  if (!box) {
    const pane = pick(document, sel.pane);
    if (pane) {
      const inside = [...pane.querySelectorAll("div")].filter((e) => {
        const style = getComputedStyle(e);
        return /(auto|scroll)/.test(style.overflowY) && e.scrollHeight > e.clientHeight + 20;
      }).sort((a, b) => b.scrollHeight - a.scrollHeight);
      box = inside[0] || pane;
    }
  }
  if (!box && composer) {
    box = composer;
    for (let i = 0; i < 10 && box.parentElement; i++) {
      box = box.parentElement;
      if (box.getBoundingClientRect().height > window.innerHeight * 0.5) break;
    }
  }
  if (!box && !thread) return null;
  if (!box) box = document.body;
  // Who the conversation is with: the profile link in its header, which is not one of Instagram's own pages.
  const own = String(ownName || "").toLowerCase();
  const nameOf = (href) => {
    const m = String(href || "").match(/^\/([A-Za-z0-9._]{1,30})\/?$/);
    if (!m) return "";
    const u = m[1].toLowerCase();
    return /^(direct|explore|reels|reel|p|stories|accounts|about|legal|developer|emails|challenge|session|web|api|tv|igtv|lite|privacy|terms|create)$/.test(u) ? "" : u;
  };
  const top = box.getBoundingClientRect().top;
  const header = [...document.querySelectorAll('a[href^="/"]')]
    .filter((a) => nameOf(a.getAttribute("href")) && nameOf(a.getAttribute("href")) !== own
                   && a.getBoundingClientRect().top < top + 140 && a.getBoundingClientRect().top > -40);
  const people = [...new Set(header.map((a) => nameOf(a.getAttribute("href"))))];
  const username = people[0] || "";
  const titleEl = [...document.querySelectorAll('span[dir="auto"], h1, h2')]
    .find((e) => !e.children.length && (e.innerText || "").trim() && e.getBoundingClientRect().top < top + 120);
  const name = (titleEl ? (titleEl.innerText || "").trim() : "") || username;
  const photoButton = !!pick(document, sel.mediaButton);
  // A voice note can go two ways: the microphone button, where Instagram gives the chat one, or its file box,
  // whose accept list takes sound as well as pictures. Either is enough.
  const voiceButton = !!pick(document, sel.voiceButton)
    || [...document.querySelectorAll('input[type="file"]')].some((i) => /audio/i.test(i.getAttribute("accept") || ""));
  const B = box.getBoundingClientRect();
  const mid = B.left + B.width / 2;

  // Its rows, in the page's order: messages, and the day labels between them.
  let items = pickAll(box, sel.message).filter(visible);
  if (!items.length) {
    // No markers on this build: the rows of whatever scrolls. `box` may already be that, in which case its own
    // children are the rows; a single wrapper round them is stepped through.
    const lists = [...box.querySelectorAll("*")].filter((e) => {
      const s = getComputedStyle(e);
      return /(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 20;
    }).sort((a, b) => b.scrollHeight - a.scrollHeight);
    let list = lists[0] || box;
    items = [...list.children];
    while (items.length === 1 && items[0].children.length > 1) items = [...items[0].children];
    items = items.filter(visible);
    // Instagram wraps every message in a few more layers: the row is whatever first has words of its own, so a
    // wrapper holding the whole conversation is stepped through rather than read as one message.
    const sameWords = (a, b) => (a.innerText || "").trim() === (b.innerText || "").trim();
    for (let depth = 0; depth < 6; depth++) {
      const wordy = items.filter((e) => (e.innerText || "").trim());
      if (wordy.length > 1 || !wordy.length) break;
      const only = wordy[0];
      const kids = [...only.children].filter(visible);
      if (kids.length < 2 || !kids.some((k) => !sameWords(k, only))) break;
      items = kids;
    }
  }
  const out = [];
  let day = "";
  items.forEach((el, idx) => {
    const text = (el.innerText || "").trim();
    const r = el.getBoundingClientRect();
    if (r.height < 6) return;
    const label = (el.getAttribute("aria-label") || "")
      + " " + [...el.querySelectorAll("[aria-label]")].map((e) => e.getAttribute("aria-label")).join(" ");
    // A short line on its own across the middle naming a day or a time is a label, not a message.
    const leafs = [...el.querySelectorAll("*")].filter((e) => !e.children.length && (e.innerText || "").trim());
    const content = leafs.length ? leafs : [el];
    const xs = content.map((e) => e.getBoundingClientRect()).filter((x) => x.width > 0);
    if (!xs.length) return;
    const left = Math.min(...xs.map((x) => x.left));
    const right = Math.max(...xs.map((x) => x.right));
    const centred = Math.abs((left + right) / 2 - mid) < B.width * 0.1 && right - left < B.width * 0.6;
    if (centred && text.length < 44
        && /(\d{1,2}:\d{2}|today|yesterday|\b\d{4}\b|mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/i.test(text)) {
      day = text;
      return;
    }
    // Instagram writes "You sent" / "<name> sent" into the row for a screen reader; where it does not, the side of
    // the conversation it sits on says whose it is.
    const saidMine = /\byou (sent|replied|liked|unsent)\b/i.test(label) || /^you sent\b/i.test(text);
    const mine = saidMine || (left + right) / 2 > mid + B.width * 0.05;
    // Who said it, in a group: the picture beside it links to them.
    let author = "";
    for (const a of el.querySelectorAll('a[href^="/"]')) {
      const u = nameOf(a.getAttribute("href"));
      if (u && u !== own) { author = u; break; }
    }
    const links = [...el.querySelectorAll('a[href^="http"], a[href^="/"]')]
      .map((a) => ({ url: new URL(a.getAttribute("href"), location.href).href, title: (a.innerText || "").trim().slice(0, 140) }))
      .filter((l) => /instagram\.com\/(p|reel|reels|tv|stories)\//.test(l.url) || !/instagram\.com/.test(l.url));
    const imgs = [...el.querySelectorAll("img")].filter((i) => !i.closest("a[href^='/']") || i.getBoundingClientRect().width > 60);
    const big = imgs.find((i) => i.getBoundingClientRect().width > 90);
    const small = !big && imgs.find((i) => i.getBoundingClientRect().width > 24);
    const video = el.querySelector("video");
    const audio = el.querySelector("audio") || /voice message|audio message/i.test(label);
    const media = {};
    let kind = "";
    let title = "";
    let words = text;
    const shared = links.find((l) => /instagram\.com\/(p|reel|reels|tv|stories)\//.test(l.url));
    if (shared) {
      kind = /\/stories\//.test(shared.url) ? "story" : /\/(reel|reels)\//.test(shared.url) ? "reel" : "post";
      media.url = shared.url.split("?")[0];
      title = (shared.title || "").slice(0, 200);
      if (big) media.cover = big.currentSrc || big.src || "";
      // The card carries the post's own words; what they typed is the rest.
      if (words === title) words = "";
    } else if (audio) {
      kind = "voice";
      media.audio = true;
    } else if (video) {
      kind = "clip";
      media.video = true;
    } else if (/\bphoto\b/i.test(label) && /view once|viewed once|disappear/i.test(label + text)) {
      kind = "viewonce";
    } else if (big) {
      kind = /giphy|gif/i.test(big.currentSrc || big.src || "") ? "gif" : "photo";
      media.img = true;
      if (kind === "gif") media.cover = big.currentSrc || big.src || "";
    } else if (small && !words) {
      kind = "sticker";
    }
    // The heart Instagram sends when someone taps the like button beside the box: a message that is only a heart.
    if (!kind && /^(?:❤️?|♥️?|🤍|🖤|💙|💚|💛|🧡|💜|🤎|💖|💗|💓|💕){1,3}$/
        .test(words.trim())) kind = "heart";
    // A story they answered or tagged it in says which story above the words.
    if (!kind && /replied to (your|their) story|mentioned you in (their|a) story/i.test(label + text)) {
      kind = "storyreply";
      title = (label.match(/replied to [^.]*story/i) || [""])[0];
    }
    if (/\bunsent a message\b|removed a message/i.test(label + text)) {
      kind = "unsent";
      words = "";
    }
    if (!words && !kind) return;
    const shown = pick(el, sel.reactionShown);
    const reactions = [];
    if (shown) {
      const t = (shown.getAttribute("aria-label") || shown.innerText || "").trim();
      for (const e of (t.match(/\p{Extended_Pictographic}/gu) || []).slice(0, 6)) {
        reactions.push({ name: e, count: parseInt((t.match(/\d+/) || [1])[0], 10) || 1, mine: /you reacted/i.test(t) });
      }
    }
    const quoteEl = pick(el, sel.quoted);
    out.push({
      idx, mine, author: mine ? "" : author, text: words.replace(/\n{2,}/g, "\n"), kind, day, title,
      links: links.slice(0, 3), reactions,
      edited: /\bedited\b/i.test(label),
      quote: quoteEl ? (quoteEl.innerText || quoteEl.getAttribute("aria-label") || "").trim().slice(0, 200) : "",
      media: Object.keys(media).length ? media : undefined,
    });
  });
  return {
    thread, username, name, people, photoButton, voiceButton, own: ownName,
    messages: out.slice(-150),
    calling: !!pick(document, sel.calling),
  };
}

/** The reels a feed has drawn: each one's code, whose it is, its caption, whether it is liked, and if it plays. */
function reelsInPage(sel) {
  const out = [];
  const videos = [...document.querySelectorAll("video")];
  for (const v of videos) {
    let box = v;
    for (let i = 0; i < 8 && box.parentElement; i++) {
      box = box.parentElement;
      if (box.querySelector('a[href*="/reel/"], a[href*="/p/"]')) break;
    }
    // A reel's permalink, not the Reels page's own /reels/ or /reels/audio/<code>/: the closing slash keeps those
    // out, and "audio" is not a code even where one slips through. The Reels feed has no permalinks, so a reel
    // there has no id and no url, which is honest: it can still be watched, liked and said something about.
    const link = box.querySelector('a[href*="/reel/"], a[href*="/p/"]');
    const said = link ? (link.getAttribute("href").match(/\/(?:p|reel)\/([A-Za-z0-9_-]{5,24})/) || [])[1] || "" : "";
    const code = /^(audio|explore|direct|stories|accounts)$/i.test(said) ? "" : said;
    const who = [...box.querySelectorAll('a[href^="/"]')]
      .map((a) => (a.getAttribute("href").match(/^\/([A-Za-z0-9._]{1,30})\/?$/) || [])[1] || "")
      .find((u) => u && !/^(p|reel|reels|explore|direct|stories|accounts)$/.test(u)) || "";
    const liked = !!box.querySelector('svg[aria-label="Unlike"]');
    const likeThere = liked || !!box.querySelector('svg[aria-label="Like"]');
    const capEl = [...box.querySelectorAll('span[dir="auto"], h1')].find((e) => (e.innerText || "").trim().length > 3);
    const r = v.getBoundingClientRect();
    out.push({
      id: code, handle: who,
      caption: (capEl ? capEl.innerText : "").replace(/\s+/g, " ").trim().slice(0, 300),
      liked: likeThere ? liked : null,
      top: Math.round(r.top), height: Math.round(r.height), playing: !v.paused,
      url: code ? `https://www.instagram.com/reel/${code}/` : "",
    });
    if (out.length >= 8) break;
  }
  return out;
}

/** Someone's posts as their profile shows them: [{ id, kind, url, cover, caption, pinned }]. */
function postsInPage(sel, n) {
  const out = [];
  const seen = new Set();
  for (const a of document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]')) {
    const href = a.getAttribute("href") || "";
    const m = href.match(/\/(p|reel|reels)\/([A-Za-z0-9_-]{5,24})/);
    if (!m || seen.has(m[2])) continue;
    seen.add(m[2]);
    const img = a.querySelector("img");
    const label = (a.innerText || "") + " " + [...a.querySelectorAll("[aria-label]")].map((e) => e.getAttribute("aria-label")).join(" ");
    out.push({
      id: m[2], kind: m[1] === "p" ? "post" : "reel",
      url: `https://www.instagram.com/${m[1] === "p" ? "p" : "reel"}/${m[2]}/`,
      cover: img ? (img.currentSrc || img.src || "") : "",
      caption: (img?.getAttribute("alt") || "").replace(/^Photo (by|shared by)[^:]*:?\s*/i, "").replace(/\s+/g, " ").trim().slice(0, 300),
      pinned: /\bpinned\b/i.test(label),
      video: !!a.querySelector('svg[aria-label*="Clip" i], video') || m[1] !== "p",
    });
    if (out.length >= n) break;
  }
  return out;
}

/** The comments under the post on the page: [{ index, username, text }], its own caption left out. */
function commentsInPage(sel, ownName) {
  const own = String(ownName || "").toLowerCase();
  const rows = [];
  const lists = [...document.querySelectorAll("ul")].sort((a, b) => b.querySelectorAll("li").length - a.querySelectorAll("li").length);
  const list = lists[0];
  if (!list) return rows;
  const items = [...list.querySelectorAll("li")].filter((li) => !li.querySelector("li"));
  items.forEach((li) => {
    const link = li.querySelector('a[href^="/"]');
    const who = link ? (link.getAttribute("href").match(/^\/([A-Za-z0-9._]{1,30})\/?$/) || [])[1] || "" : "";
    if (!who) return;
    const spans = [...li.querySelectorAll('span[dir="auto"]')].filter((e) => !e.children.length);
    // The first line is the account's name; the words after it are the comment.
    const text = spans.map((e) => (e.innerText || "").trim()).filter((t) => t && t.toLowerCase() !== who).join(" ")
      .replace(/\s+/g, " ").trim();
    if (!text) return;
    rows.push({ index: rows.length, username: who.toLowerCase(), text: text.slice(0, 400), mine: who.toLowerCase() === own });
  });
  return rows.slice(0, 40);
}

/** The story on the screen now: whose, which one, and whether its reply box is there. */
function storyNowInPage(sel) {
  const m = location.pathname.match(/\/stories\/([A-Za-z0-9._]{1,30})\/(\d{6,25})/);
  const v = document.querySelector("video");
  const img = [...document.querySelectorAll("img")].sort((a, b) =>
    b.getBoundingClientRect().height - a.getBoundingClientRect().height)[0];
  const words = [...document.querySelectorAll('span[dir="auto"], div[dir="auto"]')]
    .filter((e) => !e.children.length && (e.innerText || "").trim().length > 2)
    .map((e) => (e.innerText || "").trim());
  let reply = false;
  for (const s of sel.storyReply) { try { if (document.querySelector(s)) { reply = true; break; } } catch { /* bad */ } }
  return {
    username: m ? m[1].toLowerCase() : "",
    id: m ? m[2] : "",
    url: m ? `https://www.instagram.com/stories/${m[1]}/${m[2]}/` : "",
    video: !!v, image: img ? (img.currentSrc || img.src || "") : "",
    words: words.slice(0, 6).join(" · ").slice(0, 300),
    reply,
    ended: /story (has )?ended|no (more )?stories/i.test(document.body?.innerText || "").valueOf(),
  };
}

// ── The bot ─────────────────────────────────────────────────────────────────────────────────────────────────────

export default class InstagramBot {
  constructor({ account = 1, username = "", dataDir, locale = "en-US", timezone = "", tag = "[Instagram]" } = {}) {
    this.account = account;
    this.username = cleanUsername(username);
    this.dataDir = dataDir;
    this.locale = locale;
    this.timezone = timezone;
    this.tag = tag;
    this.browser = null;
    this.page = null;        // the inbox
    this.side = null;        // its own things: its posts' comments, its settings, its Note
    this.out = null;         // going out: someone's profile, stories, Reels, posting
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

  /** A tab behind the inbox, made to behave as one in front (see tiktokbot.js: Chrome draws nothing behind). */
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

  /** The tab for the account's own things: its posts' comments, its Note, its settings. */
  async sidePage() {
    if (this.usable(this.side)) return this.side;
    const old = this.side;
    this.side = await this.newTab();
    if (old && !old.isClosed()) await old.close().catch(() => {});
    return this.side;
  }

  /** The tab for going out: someone's profile, their stories, Reels, posting. One thing at a time in it. */
  async outPage() {
    if (this.usable(this.out)) return this.out;
    const old = this.out;
    this.out = await this.newTab();
    if (old && !old.isClosed()) await old.close().catch(() => {});
    return this.out;
  }

  /**
   * A tab that looks like a phone, in the same session: Instagram's phone site can do things its desktop one cannot
   * (putting up a story, most of all). The same cookies, so it is the same account.
   */
  async phonePage() {
    if (this.usable(this.phone)) return this.phone;
    const old = this.phone;
    const page = await this.newTab();
    try {
      await page.setUserAgent("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
                              + "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1");
      await page.setViewport({ width: 414, height: 896, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
    } catch { /* the desktop size, then */ }
    this.phone = page;
    if (old && !old.isClosed()) await old.close().catch(() => {});
    return this.phone;
  }

  /** The browser and its page, working: "ok", "reopened" after its window closed, "newpage" after its page went. */
  async ensure() {
    const connected = this.browser && !this.gone
      && (typeof this.browser.connected === "boolean" ? this.browser.connected : this.browser.isConnected?.() !== false);
    if (!connected) {
      console.warn(`${this.tag} Its Chrome window closed; opening it again.`);
      try { await this.browser?.close(); } catch { /* gone */ }
      this.side = null;
      this.out = null;
      this.phone = null;
      await this.launch(this.launchOpts);
      return "reopened";
    }
    const frame = this.page && !this.page.isClosed() ? this.page.mainFrame() : null;
    if (!frame || frame.detached) {
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
        // A page that went away under it: opened again, and tried once more.
        if (attempt === 0 && /detached|target closed|session closed|has been closed|not attached/i.test(e.message || "")) {
          const which = page === this.side ? "side" : page === this.out ? "out" : page === this.phone ? "phone" : "page";
          await this.ensure();
          if (which === "side") page = await this.sidePage();
          else if (which === "out") page = await this.outPage();
          else if (which === "phone") page = await this.phonePage();
          else page = this.page;
          continue;
        }
        console.warn(`${this.tag} Could not open ${url}: ${e.message}`);
        return false;
      }
    }
    await delay(2200 + Math.random() * 1500);
    await this.dismissDialogs(page);
    return true;
  }

  /** Cookie banners, "Save login info", "Turn on notifications", "Add to home screen": answered, as a person would. */
  async dismissDialogs(page = this.page) {
    try {
      await page.evaluate((say) => {
        const no = new RegExp(say.notNow, "i");
        const cookies = new RegExp(say.cookies, "i");
        for (const b of [...document.querySelectorAll('div[role="button"], button')]) {
          if (!b.getClientRects().length) continue;
          const t = (b.innerText || b.getAttribute("aria-label") || "").trim();
          if (!t) continue;
          if (cookies.test(t)) { b.click(); return; }
          // Only inside something that is in the way, never a button of the page itself.
          if (no.test(t) && b.closest('div[role="dialog"], div[role="alertdialog"]')) b.click();
        }
      }, { notNow: SAY.notNow.source, cookies: SAY.cookies.source });
    } catch { /* a page that went away */ }
  }

  // ── Signed in? Who as? ────────────────────────────────────────────────────────────────────────────────────────

  /** Instagram's own session cookie, which is the whole of being signed in. */
  async hasSession() {
    try {
      const cookies = await this.page.cookies(HOME);
      return cookies.some((c) => c.name === "sessionid" && c.value && c.value.length > 10);
    } catch {
      return false;
    }
  }

  async isLogged() {
    if (!(await this.hasSession())) return false;
    return !/\/accounts\/login|\/challenge|\/accounts\/suspended/.test(this.page.url());
  }

  /**
   * The signed-in account: its username, name, picture and counts, from the page's own profile endpoint (the one
   * instagram.com itself calls, with the web app's id). Its page, its session, its headers.
   */
  async whoAmI() {
    let username = this.username;
    try {
      // Who the page itself says it is: the picture at the top links to that account, and its alt names it. No
      // request, so nothing to be throttled, which is what Instagram does to a new account's API calls.
      const said = await this.page.evaluate(() => {
        const a = [...document.querySelectorAll('a[href^="/"]')]
          .find((x) => /profile picture/i.test(x.querySelector("img")?.getAttribute("alt") || ""));
        const m = a ? (a.getAttribute("href") || "").match(/^\/([A-Za-z0-9._]{1,30})\/?$/) : null;
        if (m) return m[1].toLowerCase();
        // Or the account its own page was drawn for.
        const said = (document.body?.innerHTML || "").match(/"username":"([A-Za-z0-9._]{1,30})"/);
        return said ? said[1].toLowerCase() : "";
      });
      if (said) username = said;
    } catch { /* what it was added as */ }
    if (!username) return null;
    const p = await this.profileInfo(username).catch(() => null);
    return p ? { ...p, profiled: true } : { username, name: "", avatar: "", profiled: false };
  }

  /**
   * Someone's profile as Instagram's own page reads it (web_profile_info): name, picture, bio, counts, whether it is
   * private and whether this account follows them. One request, made by the page with its own session; null when
   * Instagram will not say.
   */
  async profileInfo(username) {
    const u = cleanUsername(username);
    if (!u) return null;
    const api = await this.page.evaluate(async (name, appId) => {
      try {
        const r = await fetch(`/api/v1/users/web_profile_info/?username=${encodeURIComponent(name)}`,
                              { credentials: "include", headers: { "x-ig-app-id": appId } });
        if (!r.ok) return null;
        const user = (await r.json())?.data?.user;
        if (!user || !user.username) return null;
        const n = (v) => Number(v) || 0;
        return {
          username: String(user.username).toLowerCase(),
          name: user.full_name || "",
          bio: user.biography || "",
          avatar: user.profile_pic_url_hd || user.profile_pic_url || "",
          verified: !!user.is_verified,
          private: !!user.is_private,
          followers: n(user.edge_followed_by?.count),
          following: n(user.edge_follow?.count),
          posts: n(user.edge_owner_to_timeline_media?.count),
          follows_me: !!user.follows_viewer,
          i_follow: !!user.followed_by_viewer,
          requested: !!user.requested_by_viewer,
          // Whether they have a story up now, so it can be watched without opening their profile first.
          has_story: !!user.has_story || !!user.reel,
          id: String(user.id || ""),
        };
      } catch {
        return null;
      }
    }, u, WEB_APP_ID).catch(() => null);
    return api || await this.profileFromPage(u);
  }

  /**
   * Someone's profile read off their own page instead of the endpoint behind it: Instagram throttles that endpoint
   * hard for a new account (429), and a page anyone can open says most of the same things. Its description line is
   * "1,234 Followers, 56 Following, 7 Posts - See Instagram photos and videos from Name (@user)".
   */
  async profileFromPage(username) {
    const u = cleanUsername(username);
    if (!u) return null;
    return await this.page.evaluate(async (name) => {
      const num = (v) => {
        const t = String(v || "").trim().toUpperCase().replace(/,/g, "");
        const m = t.match(/^([\d.]+)\s*([KMB])?$/);
        if (!m) return 0;
        return Math.round(parseFloat(m[1]) * ({ K: 1e3, M: 1e6, B: 1e9 }[m[2]] || 1));
      };
      try {
        const r = await fetch(`/${name}/`, { credentials: "include" });
        if (!r.ok) return null;
        const html = await r.text();
        // A page's own words come escaped (&#x627; and the rest): the browser itself is what unescapes them.
        const unescape = (t) => {
          const box = document.createElement("textarea");
          box.innerHTML = String(t || "");
          return box.value;
        };
        const meta = (prop) => {
          const m = html.match(new RegExp(`<meta[^>]+property="og:${prop}"[^>]+content="([^"]*)"`))
            || html.match(new RegExp(`<meta[^>]+content="([^"]*)"[^>]+property="og:${prop}"`));
          return m ? unescape(m[1]) : "";
        };
        const about = meta("description");
        if (!about && !/"username":"/.test(html)) return null;
        const counts = about.match(/([\d.,KMB]+)\s+Followers?,\s*([\d.,KMB]+)\s+Following,\s*([\d.,KMB]+)\s+Posts?/i);
        const who = about.match(/from\s+(.+?)\s*\(@/i);
        const flag = (key) => new RegExp(`"${key}":true`).test(html);
        const id = (html.match(/"profile_id":"(\d+)"/) || html.match(/"id":"(\d+)"/) || [])[1] || "";
        const bio = (html.match(/"biography":"((?:[^"\\]|\\.)*)"/) || [])[1] || "";
        return {
          username: name,
          name: who ? who[1] : (meta("title").split("(")[0] || "").trim(),
          bio: bio ? JSON.parse(`"${bio}"`) : "",
          avatar: meta("image"),
          verified: flag("is_verified") || /"is_verified":true/.test(html),
          private: flag("is_private"),
          followers: counts ? num(counts[1]) : 0,
          following: counts ? num(counts[2]) : 0,
          posts: counts ? num(counts[3]) : 0,
          follows_me: false,
          i_follow: flag("followed_by_viewer"),
          requested: flag("requested_by_viewer"),
          has_story: flag("has_story") || flag("show_story_unseen_state"),
          id,
          // Read off the page rather than the endpoint: the same things, one of them (who follows whom) left out.
          frompage: true,
        };
      } catch {
        return null;
      }
    }, u).catch(() => null);
  }

  /** A check Instagram put up that only a person can answer: a captcha, a "was this you?". */
  async captchaShown(page = this.page) {
    try {
      return await page.evaluate((sels) => {
        for (const s of sels) {
          try {
            const e = document.querySelector(s);
            if (e && e.getClientRects().length) return true;
          } catch { /* bad selector on this build */ }
        }
        return /confirm it.s you|solve this puzzle|help us confirm|unusual (login )?activity/i
          .test((document.body?.innerText || "").slice(0, 4000));
      }, SEL.captcha);
    } catch {
      return false;
    }
  }

  /** Whether Instagram has suspended or disabled the account, which no amount of waiting fixes. */
  async suspended(page = this.page) {
    try {
      if (/\/accounts\/suspended|\/accounts\/disabled/.test(page.url())) return true;
      return await page.evaluate(() => /we suspended your account|your account has been disabled|account was disabled/i
        .test((document.body?.innerText || "").slice(0, 3000)));
    } catch {
      return false;
    }
  }

  /** Something only a person can do: the window comes up, and down again after, when hidden. */
  async waitForPerson(check, { timeoutMs = 0, onWait } = {}) {
    await showWindow(this.page);
    const started = Date.now();
    while (true) {
      if ((await this.ensure().catch(() => "ok")) !== "ok") await showWindow(this.page);
      if (await check().catch(() => false)) break;
      if (timeoutMs && Date.now() - started > timeoutMs) return false;
      if (onWait) onWait(Date.now() - started);
      await delay(4000);
    }
    if (this.hidden) await hideWindow(this.page);
    return true;
  }

  // ── Signing in ────────────────────────────────────────────────────────────────────────────────────────────────

  /** Type into a box as a person types, after clearing whatever was in it. */
  async typeInto(page, el, text) {
    const clicked = await Promise.race([el.click().then(() => true), delay(4000).then(() => false)]).catch(() => false);
    if (!clicked) await page.evaluate((e) => e.focus(), el).catch(() => {});
    await delay(200 + Math.random() * 300);
    await page.keyboard.down("Control");
    await page.keyboard.press("a");
    await page.keyboard.up("Control");
    await page.keyboard.press("Backspace");
    for (const ch of String(text)) await page.keyboard.type(ch, { delay: typeDelay() });
  }

  async firstOf(where, sels) {
    for (const s of sels) {
      const el = await where.$(s).catch(() => null);
      if (el) return el;
    }
    return null;
  }

  /**
   * The box a code goes in: one of the markers when the page has them, else the only text box on the page. Its own
   * two-step page gives the box no name, no label and no autocomplete, so there is nothing else to go on, and
   * nothing else to confuse it with: a sign-in screen asking for a code has exactly one thing to type in.
   */
  async codeBox(page = this.page) {
    const found = await this.firstOf(page, SEL.twoFactor) || await this.firstOf(page, SEL.challengeCode);
    if (found) return found;
    const handle = await page.evaluateHandle(() => {
      const ok = (i) => i.getClientRects().length && !i.disabled && !i.readOnly
        && ["text", "tel", "number", ""].includes((i.type || "").toLowerCase());
      const boxes = [...document.querySelectorAll("input")].filter(ok);
      return boxes.length === 1 ? boxes[0] : null;
    }).catch(() => null);
    const el = handle && handle.asElement ? handle.asElement() : null;
    return el;
  }

  /**
   * The one box on the page there is to write in, when there is exactly one: the same reasoning as codeBox, for the
   * sheets Instagram gives no name or label to at all.
   */
  async onlyTextBox(page = this.page) {
    const handle = await page.evaluateHandle(() => {
      const ok = (e) => e.getClientRects().length && !e.disabled && !e.readOnly;
      const boxes = [...document.querySelectorAll('textarea, div[role="textbox"], input[type="text"]')].filter(ok);
      return boxes.length === 1 ? boxes[0] : null;
    }).catch(() => null);
    return handle && handle.asElement ? handle.asElement() : null;
  }

  /** "Trust this device and skip this step from now on", ticked: the next sign-in is not asked for a code. */
  async trustDevice(page = this.page) {
    return await page.evaluate((sels) => {
      for (const s of sels) {
        const box = [...document.querySelectorAll(s)].find((e) => e.getClientRects().length);
        if (box && !box.checked) { (box.closest("label") || box).click(); return true; }
        if (box) return true;
      }
      return false;
    }, SEL.trustDevice).catch(() => false);
  }

  /** Press the first button whose words match; what it said, or "". */
  async clickSaid(re, page = this.page) {
    return await page.evaluate(clickSaidInPage, re.source, re.flags || "i").catch(() => "");
  }

  /** What Instagram's page says went wrong, in its own words; "" when it says nothing. */
  async pageError(page = this.page) {
    return await page.evaluate((sels) => {
      for (const s of sels) {
        for (const e of document.querySelectorAll(s)) {
          const t = (e.innerText || "").trim();
          if (t && t.length < 300) return t;
        }
      }
      return "";
    }, SEL.loginError).catch(() => "");
  }

  /**
   * Sign in: the username and the password typed, then whatever Instagram asks next.
   *   * an authentication app's six digits, made here from the account's 2FA key;
   *   * a code sent to its email or phone, which only a person has: `getCode` is asked for one (the panel's field,
   *     or the window itself, where someone is watching);
   *   * a captcha or a "was this you?", which `onPerson` hands to a person.
   * Returns { ok, state, reason }. state: "done", "needs_code", "captcha", "suspended", "bad_login", "failed".
   */
  async signIn({ password = "", totpKey = "", onState = null, getCode = null, onPerson = null, tries = 2 } = {}) {
    const say = (state, detail = "") => { if (onState) onState(state, detail); };
    if (!this.username || !password) return { ok: false, state: "failed", reason: "It has no username or password saved." };
    for (let attempt = 1; attempt <= tries; attempt++) {
      say("opening", "Opening Instagram");
      if (!(await this.goto(`${HOME}accounts/login/?hl=${this.lang}`))) {
        return { ok: false, state: "failed", reason: "Instagram's sign-in page would not open." };
      }
      // Already in (the profile kept its session): nothing to type.
      if (await this.isLogged()) {
        say("checking", "Already signed in");
        return { ok: true, state: "done" };
      }
      if (await this.suspended()) return { ok: false, state: "suspended", reason: "Instagram has suspended this account." };
      say("signing-in", `Signing in as @${this.username}`);
      const user = await this.firstOf(this.page, SEL.loginUser);
      const pass = await this.firstOf(this.page, SEL.loginPassword);
      if (!user || !pass) {
        // No form: Instagram may have landed somewhere else entirely.
        if (await this.isLogged()) return { ok: true, state: "done" };
        if (attempt < tries) { await delay(4000); continue; }
        return { ok: false, state: "failed", reason: "Instagram's sign-in boxes were not on the page." };
      }
      await this.typeInto(this.page, user, this.username);
      await delay(400 + Math.random() * 600);
      await this.typeInto(this.page, pass, password);
      await delay(500 + Math.random() * 700);
      if (!(await this.clickSaid(SAY.logIn))) await this.page.keyboard.press("Enter");
      // Where it went: in, 2FA, a code, a check, or a refusal.
      const landed = await this.afterLogin({ totpKey, getCode, onPerson, say });
      if (landed.ok || landed.state !== "retry") return landed;
      await delay(5000);
    }
    return { ok: false, state: "failed", reason: "Instagram would not let it in." };
  }

  /** What Instagram put in the way after the password, dealt with until it is in or it cannot be. */
  async afterLogin({ totpKey = "", getCode = null, onPerson = null, say = () => {} } = {}) {
    const until = Date.now() + 5 * 60 * 1000;
    let askedCode = false;
    while (Date.now() < until) {
      await delay(2500);
      await this.dismissDialogs();
      if (await this.isLogged()) {
        // "Save login info" and notifications: both kept out of the way, the session saved.
        await this.clickSaid(SAY.saveLogin);
        await delay(1200);
        await this.clickSaid(SAY.notNow);
        say("checking", "Signed in, settling the session");
        await delay(2000);
        return { ok: true, state: "done" };
      }
      if (await this.suspended()) return { ok: false, state: "suspended", reason: "Instagram has suspended this account." };
      const url = this.page.url();
      const words = await this.page.evaluate(() => (document.body?.innerText || "").slice(0, 3000)).catch(() => "");
      // The six digits from an authentication app: made here, from the account's own key.
      const wants2fa = /two-?factor|authentication app|security code|6-digit|enter the code/i.test(words)
        || /\/accounts\/login\/two_(factor|step)/.test(url);
      if (wants2fa && totpKey) {
        const box = await this.codeBox();
        if (box) {
          // A code in its last seconds would be stale by the time it lands: the next one is waited for.
          if (totpLeft() < 5) await delay((totpLeft() + 1) * 1000);
          const code = totp(totpKey);
          if (!code) return { ok: false, state: "failed", reason: "That 2FA key is not one Instagram could have given." };
          say("two-factor", "Typing the code from its 2FA key");
          await this.typeInto(this.page, box, code);
          await delay(500);
          // Asked once, rather than on every sign-in from now on.
          await this.trustDevice();
          if (!(await this.clickSaid(SAY.confirm))) await this.page.keyboard.press("Enter");
          await delay(4000);
          const bad = await this.pageError();
          if (/incorrect|wrong|try again/i.test(bad)) {
            // One stale code: tried once more with the next.
            await delay(Math.max(2000, totpLeft() * 1000));
            const again = totp(totpKey);
            const box2 = await this.codeBox();
            if (box2 && again) {
              await this.typeInto(this.page, box2, again);
              if (!(await this.clickSaid(SAY.confirm))) await this.page.keyboard.press("Enter");
              await delay(4000);
            }
          }
          continue;
        }
      }
      // A code sent to the account's email or phone: only a person has that.
      const wantsCode = /\/challenge/.test(url)
        || /we sent (a|an) (code|email|security code)|enter the (confirmation|security) code|check your email|sent you a (code|text)/i.test(words);
      if (wantsCode) {
        // Where Instagram offers email or text, email is the one the person can get at.
        if (/how do you want|choose a way|send (a )?(security )?code/i.test(words)) {
          await this.page.evaluate(() => {
            const radio = [...document.querySelectorAll('input[type="radio"], label')]
              .find((e) => /email/i.test((e.closest("label") || e).innerText || ""));
            if (radio) (radio.closest("label") || radio).click();
          }).catch(() => {});
          await delay(800);
          await this.clickSaid(SAY.confirm);
          await delay(4000);
          continue;
        }
        const box = await this.codeBox();
        if (box && getCode) {
          if (!askedCode) {
            say("needs-code", "Instagram sent a code to the account's email or phone. Type it in.");
            askedCode = true;
          }
          const code = await getCode();
          if (code) {
            await this.typeInto(this.page, box, code);
            await delay(400);
            await this.trustDevice();
            if (!(await this.clickSaid(SAY.confirm))) await this.page.keyboard.press("Enter");
            await delay(5000);
            const bad = await this.pageError();
            if (bad) {
              say("needs-code", `Instagram did not take that code: ${bad}`);
              askedCode = false;
            }
          }
          continue;
        }
        if (box && !getCode) {
          return { ok: false, state: "needs_code",
                   reason: "Instagram wants a code from the account's email or phone." };
        }
      }
      if (await this.captchaShown()) {
        say("needs-you", "Instagram put up a check. It needs a person.");
        if (onPerson) {
          const done = await onPerson("captcha");
          if (done) continue;
        }
        return { ok: false, state: "captcha", reason: "Instagram put up a check only a person can solve." };
      }
      const bad = await this.pageError();
      if (/incorrect|wasn.t correct|didn.t match|try again later|couldn.t log you in/i.test(bad)) {
        if (/try again later|wait a few minutes/i.test(bad)) {
          return { ok: false, state: "retry", reason: bad };
        }
        return { ok: false, state: "bad_login", reason: bad };
      }
    }
    return { ok: false, state: "retry", reason: "Instagram did not finish the sign-in." };
  }

  // ── The inbox ─────────────────────────────────────────────────────────────────────────────────────────────────

  async openInbox() {
    if (!this.page || this.page.isClosed() || this.page.mainFrame().detached) await this.ensure();
    if (!/\/direct\//.test(this.page.url())) await this.goto(`${HOME}direct/inbox/`);
    await this.dismissDialogs();
    return this.page;
  }

  /** The conversations as the list shows them. */
  async listThreads() {
    const rows = await this.page.evaluate(readListInPage, SEL);
    if (!Array.isArray(rows)) throw new Error("no conversation list");
    return rows;
  }

  /** The conversation open now, with each message's time worked out from the labels over them. */
  async readChat() {
    const chat = await this.page.evaluate(readChatInPage, SEL, this.username);
    if (chat && Array.isArray(chat.messages)) {
      for (const m of chat.messages) {
        const at = atOfLabel(m.day);
        if (at) m.at = at;
      }
    }
    return chat;
  }

  /** Open one conversation by its thread id, which is in its own link. */
  async openThread(id) {
    const t = String(id || "").replace(/\D/g, "");
    if (!t) return false;
    if (new RegExp(`/direct/t/${t}`).test(this.page.url())) return true;
    const clicked = await this.page.evaluate((thread) => {
      const a = document.querySelector(`a[href^="/direct/t/${thread}"], a[href*="/direct/t/${thread}"]`);
      if (!a) return false;
      a.scrollIntoView({ block: "center" });
      a.click();
      return true;
    }, t).catch(() => false);
    if (!clicked && !(await this.goto(`${HOME}direct/t/${t}/`))) return false;
    await delay(1600 + Math.random() * 900);
    return new RegExp(`/direct/t/${t}`).test(this.page.url());
  }

  /**
   * One conversation from the list, opened: by its id where the page gives its rows one, else by pressing the row
   * where it sits (and by whose it is, to be sure it is still that one). The id is read off the address after,
   * which is the only place this build of Instagram puts it. Returns the id, or "" when it did not open.
   */
  async openRow(row) {
    if (row && row.id && (await this.openThread(row.id))) return row.id;
    const opened = await this.page.evaluate((sel, index, name) => {
      const visible = (el) => !!el && el.getClientRects().length > 0;
      const isRow = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 200 && r.height > 40 && r.height < 130;
      };
      let box = null;
      for (const s of sel.threadList) { try { box = document.querySelector(s); } catch { box = null; } if (box) break; }
      if (!box) return false;
      let items = [];
      for (const s of sel.threadRow) {
        try { items = [...box.querySelectorAll(s)].filter((e) => visible(e) && isRow(e)); } catch { items = []; }
        if (items.length) break;
      }
      items = items.filter((e, i, all) => !all.some((o, j) => j !== i && o !== e && o.contains(e)));
      // Whose it is first, where it sat second: a list that moved under it still opens the right conversation.
      const named = name ? items.find((e) => (e.innerText || "").split("\n")[0].trim() === name) : null;
      const el = named || items[index];
      if (!el) return false;
      el.scrollIntoView({ block: "center" });
      el.click();
      return true;
    }, SEL, Number(row?.index) || 0, String(row?.name || "")).catch(() => false);
    if (!opened) return "";
    // Instagram puts the id in the address once the conversation is open.
    for (let i = 0; i < 12; i++) {
      await delay(500);
      const at = (this.page.url().match(/\/direct\/t\/(\d{5,40})/) || [])[1];
      if (at) return at;
    }
    return "";
  }

  /** Open someone's conversation by their username: from the list when it is there, else their profile's Message. */
  async openChatWith(username, { name = "", thread = "" } = {}) {
    const u = cleanUsername(username);
    if (thread && (await this.openThread(thread))) {
      const now = await this.readChat().catch(() => null);
      if (now && (!u || !now.username || now.username === u)) return true;
    }
    if (!u) return false;
    await this.openInbox();
    const open = await this.readChat().catch(() => null);
    if (open && open.username === u) return true;
    try {
      const rows = await this.listThreads();
      const row = rows.find((r) => r.name && name && r.name === name)
        || rows.find((r) => (r.name || "").toLowerCase() === u);
      if (row && (await this.openThread(row.id))) {
        const now = await this.readChat().catch(() => null);
        if (now && (!now.username || now.username === u)) return true;
      }
    } catch { /* their profile, below */ }
    if (!(await this.goto(`${HOME}${u}/`))) return false;
    const clicked = await this.clickSaid(/^(message|send message)$/i);
    if (!clicked) return false;
    await delay(3500);
    const now = await this.readChat().catch(() => null);
    return !!now && (!now.username || now.username === u);
  }

  async composer() {
    for (const s of SEL.composer) {
      const el = await this.page.$(s).catch(() => null);
      if (el) return { el, sel: s };
    }
    return null;
  }

  /** What Instagram wrote after a send, said plainly; "" when it said nothing. */
  async warning() {
    const text = await this.page.evaluate((sels) => {
      for (const s of sels) {
        const all = [...document.querySelectorAll(s)].map((e) => (e.innerText || "").trim()).filter(Boolean);
        if (all.length) return all.slice(-2).join("\n");
      }
      return "";
    }, SEL.warning).catch(() => "");
    return warningReason(text);
  }

  /** Type into the open conversation, as a person types, and send. { ok, reason } */
  async sendText(text, { dryRun = false } = {}) {
    const box = await this.composer();
    if (!box) return { ok: false, reason: "Instagram's message box is not there" };
    const before = await this.readChat().catch(() => null);
    await box.el.click({ delay: 40 + Math.random() * 60 }).catch(() => {});
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
      await this.clearTyped(this.page);
      console.log(`${this.tag} (dry run) would have sent: ${String(text).slice(0, 120)}`);
      return { ok: true, dry: true };
    }
    await delay(250 + Math.random() * 400);
    await this.page.keyboard.press("Enter");
    await delay(700);
    // Enter sends; where it only made a new line, Instagram's own Send does.
    const left = await this.page.evaluate((el) => (el.innerText || el.value || "").trim(), box.el).catch(() => "");
    if (left) {
      const btn = await this.firstOf(this.page, SEL.sendButton);
      if (btn) await btn.click().catch(() => {});
      else await this.clickSaid(/^send$/i);
    }
    for (let i = 0; i < 12; i++) {
      await delay(600);
      const why = await this.warning();
      if (why) return { ok: false, reason: why };
      const now = await this.readChat().catch(() => null);
      const last = now?.messages?.filter((m) => m.mine).pop();
      const want = String(text).replace(/\s+/g, " ").slice(0, 40);
      if (last && last.text.replace(/\s+/g, " ").includes(want)
          && (now.messages.length !== before?.messages?.length
              || last.text !== before?.messages?.filter((m) => m.mine).pop()?.text)) {
        return { ok: true };
      }
    }
    const empty = await this.page.evaluate((el) => !(el.innerText || el.value || "").trim(), box.el).catch(() => false);
    return empty ? { ok: true, unconfirmed: true } : { ok: false, reason: "Instagram did not take the message" };
  }

  async clearTyped(page) {
    await page.keyboard.down("Control");
    await page.keyboard.press("a");
    await page.keyboard.up("Control");
    await page.keyboard.press("Backspace");
  }

  /** A picture or a video into the open conversation, through its file box. */
  async sendImage(filePath, { dryRun = false } = {}) {
    let input = await this.page.$('input[type="file"]').catch(() => null);
    if (!input) {
      // The box only appears once the button beside the composer is pressed.
      await this.clickSaid(/^(add photo or video|add photo|photo)$/i);
      await delay(1200);
      input = await this.page.$('input[type="file"]').catch(() => null);
    }
    if (!input) return { ok: false, reason: "Instagram's photo box is not in this chat" };
    if (dryRun) {
      console.log(`${this.tag} (dry run) would have sent the picture ${path.basename(filePath)}`);
      return { ok: true, dry: true };
    }
    await input.uploadFile(filePath);
    await delay(2500);
    // Instagram sends a picture the moment it is picked on most builds; where it waits, its Send does.
    const sent = await this.page.evaluate(() => !document.querySelector('div[role="dialog"] img')).catch(() => true);
    if (!sent) {
      const btn = await this.firstOf(this.page, SEL.sendButton);
      if (btn) await btn.click().catch(() => {});
      else await this.clickSaid(/^send$/i);
    }
    await delay(3000);
    const why = await this.warning();
    return why ? { ok: false, reason: why } : { ok: true };
  }

  /**
   * A voice note, where Instagram gives this chat the microphone: the file is played into the page through a fake
   * microphone (Chrome's own --use-file-for-fake-audio-capture is set for the whole browser when the account has
   * voice notes on), the record button held for as long as it lasts, then sent.
   */
  async sendVoice(filePath, { dryRun = false, seconds = 0 } = {}) {
    if (!filePath || !fs.existsSync(filePath)) return { ok: false, reason: "that voice note is not on this computer" };
    // Its file box takes sound as well as pictures ("audio/*,.mp4,.mov,.png,.jpg,.jpeg", read off the page): a
    // voice note goes the way a photo does, which beats holding a microphone open in real time.
    const input = await this.firstOf(this.page, SEL.audioInput)
      || await this.page.$('input[type="file"]').catch(() => null);
    const accepts = input ? await input.evaluate((i) => /audio/i.test(i.getAttribute("accept") || ""))
      .catch(() => false) : false;
    if (input && accepts) {
      if (dryRun) {
        console.log(`${this.tag} (dry run) would have sent a voice note (${path.basename(filePath)})`);
        return { ok: true, dry: true };
      }
      await input.uploadFile(filePath);
      await delay(2500);
      const left = await this.page.evaluate(() => !!document.querySelector('div[role="dialog"]')).catch(() => false);
      if (left) {
        const send = await this.firstOf(this.page, SEL.sendButton);
        if (send) await send.click().catch(() => {});
        else await this.clickSaid(/^send$/i);
      }
      await delay(3000);
      const why = await this.warning();
      return why ? { ok: false, reason: why } : { ok: true };
    }
    // No file box that takes sound: its microphone button, with the sound played in through a fake one.
    const btn = await this.firstOf(this.page, SEL.voiceButton);
    if (!btn) return { ok: false, reason: "Instagram gives this chat no voice notes" };
    if (dryRun) {
      console.log(`${this.tag} (dry run) would have sent a voice note (${path.basename(filePath)})`);
      return { ok: true, dry: true };
    }
    await btn.click().catch(() => {});
    // The page records what the fake microphone plays, in real time: as long as the file lasts, and a beat more.
    await delay(Math.max(1500, (seconds || 6) * 1000 + 800));
    const stopped = await this.clickSaid(/^(send|stop|done)$/i);
    if (!stopped) {
      const send = await this.firstOf(this.page, SEL.sendButton);
      if (send) await send.click().catch(() => {});
    }
    await delay(2500);
    const why = await this.warning();
    return why ? { ok: false, reason: why } : { ok: true };
  }

  /**
   * The row of one message on the page, by its place in what was read.
   *
   * None of SEL.message matches this build at all (no role="row", no role="listitem", no messages_table), so this
   * returned nothing every time, and with it went reactions, replies, unsending and editing. What Instagram does
   * give every message is a bubble marked role="article", and the row that holds one is its own parent: one bubble
   * and that message's own React, Reply and See-more buttons, which is exactly what the callers reach into.
   *
   * The count lines up with what readChat read: readChatInPage leaves the day labels out of what it returns, and
   * every message it does return has a bubble, so the nth bubble is the nth message either way.
   */
  async messageAt(idx) {
    for (const s of SEL.message) {
      const items = await this.page.$$(s).catch(() => []);
      if (items.length) return items[idx] || null;
    }
    const handle = await this.page.evaluateHandle((n) => {
      const bubbles = [...document.querySelectorAll('div[role="article"]')]
        .filter((e) => e.getClientRects().length);
      const one = bubbles[n];
      return one ? one.parentElement || one : null;
    }, idx).catch(() => null);
    return handle && handle.asElement ? handle.asElement() : null;
  }

  /** Bring a message's own buttons up, as the pointer passing over it does. */
  async hoverMessage(idx) {
    const el = await this.messageAt(idx);
    if (!el) return null;
    await this.page.bringToFront().catch(() => {});
    const within = (p) => Promise.race([p.catch(() => {}), delay(6000)]);
    await el.evaluate((e) => e.scrollIntoView({ block: "center" })).catch(() => {});
    await delay(300);
    await within(el.hover());
    await delay(400 + Math.random() * 300);
    return el;
  }

  /** Instagram's own Reply on one message: what is typed next goes as the answer to it. */
  async startReply(idx) {
    const el = await this.hoverMessage(idx);
    if (!el) return false;
    const btn = await this.firstOf(el, SEL.replyButton);
    if (btn) await btn.click().catch(() => {});
    else if (!(await this.clickSaid(/^reply$/i))) return false;
    await delay(700);
    return await this.page.evaluate((sels) => {
      for (const s of sels) if (document.querySelector(s)) return true;
      return /replying to/i.test(document.body?.innerText || "");
    }, SEL.quoted).catch(() => false);
  }

  async cancelReply() {
    await this.page.keyboard.press("Escape").catch(() => {});
    await this.clickSaid(/^(cancel|close)$/i);
  }

  /**
   * A reaction on one message: its React button opens the picker, whose search takes any emoji there is. Picking one
   * already there takes it back.
   */
  async react(idx, emoji) {
    const el = await this.hoverMessage(idx);
    if (!el) return { ok: false, reason: "that message is not on Instagram's page any more" };
    const btn = await this.firstOf(el, SEL.reactButton);
    if (btn) await btn.click().catch(() => {});
    else if (!(await this.clickSaid(/^react$/i))) return { ok: false, reason: "Instagram has no reactions on this message" };
    await delay(900);
    // The six it offers at a glance are buttons of their own; anything else is found by searching.
    const want = String(emoji || "").trim();
    if (!want) return { ok: false, reason: "which emoji?" };
    let picked = await this.page.evaluate((e) => {
      const hit = [...document.querySelectorAll('[role="button"], [role="option"], button')]
        .find((b) => b.getClientRects().length && (b.innerText || "").trim() === e);
      if (hit) { hit.click(); return true; }
      return false;
    }, want).catch(() => false);
    if (!picked) {
      const search = await this.firstOf(this.page, SEL.emojiSearch);
      if (search) {
        await this.typeInto(this.page, search, want);
        await delay(1200);
        picked = await this.page.evaluate((e) => {
          const hit = [...document.querySelectorAll('[role="option"], [role="button"], button')]
            .find((b) => b.getClientRects().length && ((b.innerText || "").trim() === e
                                                        || (b.getAttribute("aria-label") || "").includes(e)));
          if (hit) { hit.click(); return true; }
          return false;
        }, want).catch(() => false);
      }
    }
    if (!picked) {
      await this.page.keyboard.press("Escape").catch(() => {});
      return { ok: false, reason: "Instagram's reactions did not have that emoji" };
    }
    await delay(900);
    return { ok: true };
  }

  /** Take one of its own messages back, as Instagram's Unsend does. */
  async unsend(idx) {
    const el = await this.hoverMessage(idx);
    if (!el) return { ok: false, reason: "that message is not on the page any more" };
    const more = await this.firstOf(el, SEL.moreButton);
    if (more) await more.click().catch(() => {});
    else if (!(await this.clickSaid(/^(more|see more options)$/i))) return { ok: false, reason: "Instagram's menu was not there" };
    await delay(800);
    if (!(await this.clickSaid(/^unsend$/i))) {
      await this.page.keyboard.press("Escape").catch(() => {});
      return { ok: false, reason: "Instagram has no Unsend on this message" };
    }
    await delay(900);
    await this.clickSaid(/^unsend$/i);                      // its "Unsend message?" asks once more
    await delay(1200);
    return { ok: true };
  }

  /**
   * Fix a typo in a message just sent, where Instagram's website lets a message be edited. {ok, reason}; the reason
   * says plainly when the site has no edit, so the app can say so rather than going quiet.
   *
   * Read off its own message on the live site (2026-10), that menu offers Forward, Copy, Translate, Pin and Unsend
   * and no Edit at all, so this is the path it takes: it says so, and a typo is unsent and sent again instead.
   * Kept because the menu is Instagram's to change, and an Edit that appears will be used the moment it does.
   */
  async editMessage(idx, text) {
    const el = await this.hoverMessage(idx);
    if (!el) return { ok: false, reason: "that message is not on the page any more" };
    const more = await this.firstOf(el, SEL.moreButton);
    if (more) await more.click().catch(() => {});
    await delay(800);
    if (!(await this.clickSaid(/^edit( message)?$/i))) {
      await this.page.keyboard.press("Escape").catch(() => {});
      return { ok: false, reason: "Instagram's website has no Edit on a message; it can only unsend and send again" };
    }
    await delay(900);
    const box = await this.composer();
    if (!box) return { ok: false, reason: "Instagram's edit box was not there" };
    await this.typeInto(this.page, box.el, String(text).slice(0, 1000));
    await delay(400);
    if (!(await this.clickSaid(/^(save|done)$/i))) await this.page.keyboard.press("Enter");
    await delay(1500);
    return { ok: true };
  }

  // ── Message requests, follows ─────────────────────────────────────────────────────────────────────────────────

  /**
   * The rows on the requests page that are requests. The first one is Instagram's own way into the hidden ones, a
   * page rather than a conversation: opening it would lead away from the requests entirely.
   */
  async requestRows() {
    await this.ensure();
    const rows = await this.listThreads().catch(() => []);
    return rows.filter((r) => !/^(hidden requests|requests|general|primary)$/i.test((r.name || "").trim()));
  }

  /** The message requests waiting: [{ name, username, preview, avatar, id }]. */
  async messageRequests() {
    if (!(await this.goto(`${HOME}direct/requests/`))) return [];
    await delay(2200);
    const rows = await this.requestRows();
    await this.goto(`${HOME}direct/inbox/`);
    return rows.map((r) => ({ name: r.name, username: cleanUsername(r.name), preview: r.preview,
                              avatar: r.avatar, id: r.id, index: r.index }));
  }

  /**
   * Accept a message request, or turn it down. `want` is the request: its thread where one is known, else the name
   * it shows, which is all Instagram's own rows carry. Opening one lands on the conversation, where its Accept,
   * Delete and Block sit along the bottom.
   */
  async answerRequest(want, accept) {
    const name = want && typeof want === "object" ? String(want.name || "") : String(want || "");
    const id = want && typeof want === "object" ? String(want.id || "") : /^\d{5,40}$/.test(name) ? name : "";
    const back = async (out) => {
      await this.goto(`${HOME}direct/inbox/`);
      return out;
    };
    if (!(await this.goto(`${HOME}direct/requests/`))) {
      return { ok: false, reason: "Instagram's message requests would not open" };
    }
    await delay(2200);
    let opened = id && (await this.openThread(id)) ? id : "";
    if (!opened) {
      const rows = await this.requestRows();
      if (!rows.length) return await back({ ok: false, reason: "there are no message requests waiting" });
      const named = name ? rows.find((r) => (r.name || "").trim() === name.trim())
        || rows.find((r) => (r.name || "").includes(name) || name.includes((r.name || "").trim())) : null;
      const row = named || (name ? null : rows[0]);
      if (!row) return await back({ ok: false, reason: "that request is not there any more" });
      opened = await this.openRow(row);
    }
    if (!opened) return await back({ ok: false, reason: "Instagram would not open that request" });
    await delay(1600);
    // Its own three buttons, along the bottom of the conversation: Block, Delete, Accept.
    const done = await this.clickSaid(accept ? /^accept$/i : /^delete$/i);
    await delay(1600);
    if (!accept && done) await this.clickSaid(/^delete$/i);   // "Delete this request?" asks once more
    await delay(1200);
    if (!done) {
      return await back({ ok: false,
                          reason: accept ? "Instagram's Accept was not there; it may already be accepted"
                                         : "Instagram's Delete was not there" });
    }
    return await back({ ok: true, thread: opened });
  }

  /** Follow someone by their username. { ok, reason } */
  async follow(username) {
    const u = cleanUsername(username);
    if (!u) return { ok: false, reason: "That is not an Instagram username" };
    const page = await this.outPage();
    if (!(await this.goto(`${HOME}${u}/`, page))) return { ok: false, reason: "Instagram did not open their profile" };
    const gone = await page.evaluate(() => /sorry, this page isn.t available|page not found/i
      .test(document.body?.innerText || "")).catch(() => false);
    if (gone) return { ok: false, reason: "Nobody on Instagram has that username" };
    const already = await page.evaluate(clickSaidInPage, "^(following|requested|message)$", "i").catch(() => "");
    if (already) {
      // Pressing Following would unfollow: Escape closes whatever that opened and nothing changes.
      await page.keyboard.press("Escape").catch(() => {});
      return { ok: false, reason: /requested/i.test(already) ? "Already asked to follow them" : "Already following them" };
    }
    const clicked = await page.evaluate(clickSaidInPage, "^(follow|follow back)$", "i").catch(() => "");
    if (!clicked) return { ok: false, reason: "Instagram showed no Follow button" };
    await delay(1800);
    return { ok: true, requested: /private/i.test(await page.evaluate(() => document.body?.innerText?.slice(0, 500) || "").catch(() => "")) };
  }

  /** Follow back up to `max` of the newest followers not followed yet; the usernames followed. */
  async followBack(max = 2) {
    if (!this.username) return [];
    const page = await this.outPage();
    if (!(await this.goto(`${HOME}${this.username}/followers/`, page))) return [];
    await delay(3000);
    const done = [];
    for (let i = 0; i < max; i++) {
      const who = await page.evaluate(() => {
        const dlg = document.querySelector('div[role="dialog"]') || document;
        const rows = [...dlg.querySelectorAll('div[role="button"], button')]
          .filter((b) => b.getClientRects().length && /^(follow|follow back)$/i.test((b.innerText || "").trim()));
        const b = rows[0];
        if (!b) return "";
        let row = b;
        for (let k = 0; k < 6 && row.parentElement; k++) {
          row = row.parentElement;
          if (row.querySelector('a[href^="/"]')) break;
        }
        const a = row.querySelector('a[href^="/"]');
        b.click();
        return a ? (a.getAttribute("href") || "") : "?";
      }).catch(() => "");
      if (!who) break;
      done.push(usernameFromHref(who) || "someone");
      await delay(5000 + Math.random() * 7000);
    }
    await page.keyboard.press("Escape").catch(() => {});
    return done;
  }

  /** Accept the people waiting to follow a private account; the usernames let in. */
  async acceptFollowRequests(max = 3) {
    const page = await this.outPage();
    if (!(await this.goto(`${HOME}accounts/activity/?followRequests=true`, page))) return [];
    await delay(2500);
    const done = [];
    for (let i = 0; i < max; i++) {
      const who = await page.evaluate(() => {
        const b = [...document.querySelectorAll('div[role="button"], button')]
          .find((x) => x.getClientRects().length && /^confirm$/i.test((x.innerText || "").trim()));
        if (!b) return "";
        let row = b;
        for (let k = 0; k < 6 && row.parentElement; k++) {
          row = row.parentElement;
          if (row.querySelector('a[href^="/"]')) break;
        }
        const a = row.querySelector('a[href^="/"]');
        b.click();
        return a ? (a.getAttribute("href") || "") : "?";
      }).catch(() => "");
      if (!who) break;
      done.push(usernameFromHref(who) || "someone");
      await delay(3000 + Math.random() * 4000);
    }
    return done;
  }

  // ── Stories ───────────────────────────────────────────────────────────────────────────────────────────────────

  /** Whether someone has a story up now, from their profile as Instagram reads it. */
  async hasStory(username) {
    const p = await this.profileInfo(username).catch(() => null);
    return !!(p && p.has_story);
  }

  /**
   * Watch someone's stories: their viewer is opened, each one looked at for a few seconds (they see it as seen), and
   * what was on screen is reported. { ok, seen: [{ id, url, video, words }], reason }
   */
  async watchStories(username, { max = 5, dryRun = false } = {}) {
    const u = cleanUsername(username);
    if (!u) return { ok: false, reason: "That is not an Instagram username" };
    const page = await this.outPage();
    if (dryRun) {
      console.log(`${this.tag} (dry run) would have watched @${u}'s story`);
      return { ok: true, dry: true, seen: [] };
    }
    if (!(await this.goto(`${HOME}stories/${u}/`, page))) return { ok: false, reason: "Instagram did not open their story" };
    await delay(2500);
    // Instagram asks once before it plays, so that it is a person's choice to be seen.
    await page.evaluate(clickSaidInPage, "^(view story|watch story|continue)$", "i").catch(() => {});
    const seen = [];
    for (let i = 0; i < max; i++) {
      const now = await page.evaluate(storyNowInPage, SEL).catch(() => null);
      if (!now || !now.id) break;
      if (!seen.some((s) => s.id === now.id)) {
        seen.push({ id: now.id, url: now.url, video: !!now.video, words: now.words, image: now.image });
      }
      // Watched the way a person watches: a few seconds, longer on a video.
      await delay((now.video ? 6 + Math.random() * 6 : 3 + Math.random() * 3) * 1000);
      const moved = await page.evaluate((sels) => {
        for (const s of sels) {
          const b = document.querySelector(s);
          if (b && b.getClientRects().length) { (b.closest('div[role="button"], button') || b).click(); return true; }
        }
        return false;
      }, SEL.storyNext).catch(() => false);
      if (!moved) await page.keyboard.press("ArrowRight").catch(() => {});
      await delay(1200);
      if (!/\/stories\//.test(page.url())) break;
    }
    await this.goto("about:blank", page).catch(() => {});
    return { ok: seen.length > 0, seen, reason: seen.length ? "" : "They have no story up" };
  }

  /** Answer the story on the screen, or react to it. The viewer must be open on it. */
  async replyToStory(text, { emoji = "", dryRun = false, page = null } = {}) {
    page = page || (await this.outPage());
    if (!/\/stories\//.test(page.url())) return { ok: false, reason: "no story is open" };
    if (dryRun) {
      console.log(`${this.tag} (dry run) would have answered the story: ${String(text || emoji).slice(0, 80)}`);
      return { ok: true, dry: true };
    }
    if (emoji && !text) {
      const liked = await page.evaluate((sels) => {
        for (const s of sels) {
          const b = document.querySelector(s);
          if (b && b.getClientRects().length) { (b.closest('div[role="button"], button') || b).click(); return true; }
        }
        return false;
      }, SEL.storyLike).catch(() => false);
      if (liked) {
        await delay(900);
        return { ok: true };
      }
    }
    const box = await this.firstOf(page, SEL.storyReply);
    if (!box) return { ok: false, reason: "Instagram gives this story no reply box" };
    await this.typeInto(page, box, String(text || emoji).slice(0, 500));
    await delay(500);
    await page.keyboard.press("Enter");
    await delay(1800);
    return { ok: true };
  }

  /**
   * Put up a story of its own. Instagram's desktop site has no story upload, so this goes through the phone version
   * of the site in the same session. { ok, reason }; the reason says plainly when neither will take it.
   */
  async postStory(file, caption = "", { dryRun = false } = {}) {
    if (!file || !fs.existsSync(file)) return { ok: false, reason: "That file is not on this computer any more" };
    const page = await this.phonePage();
    if (!(await this.goto(`${HOME}`, page))) return { ok: false, reason: "Instagram did not open" };
    await delay(2500);
    // The phone site's own "add to story" is the plus over its picture, or the camera at the top left.
    const opened = await page.evaluate(clickSaidInPage, "^(add to story|your story|add story|create)$", "i").catch(() => "");
    let input = await page.$('input[type="file"]').catch(() => null);
    if (!input && opened) {
      await delay(1500);
      input = await page.$('input[type="file"]').catch(() => null);
    }
    if (!input) {
      return { ok: false, reason: "Instagram's website will not put up a story, on the desktop site or the phone one. "
                                  + "It can post a picture or a reel instead." };
    }
    if (dryRun) {
      console.log(`${this.tag} (dry run) would have put up a story: ${path.basename(file)}`);
      return { ok: true, dry: true };
    }
    await input.uploadFile(file);
    await delay(4000);
    if (caption) {
      const box = await this.firstOf(page, SEL.createCaption);
      if (box) {
        await this.typeInto(page, box, String(caption).slice(0, 300));
        await delay(600);
      }
    }
    const shared = await page.evaluate(clickSaidInPage, "^(share|add to story|post|done)$", "i").catch(() => "");
    if (!shared) return { ok: false, reason: "Instagram's Share was not on the page" };
    for (let i = 0; i < 40; i++) {
      await delay(2000);
      const done = await page.evaluate(() => /shared to your story|your story was shared|posted/i
        .test(document.body?.innerText || "") || !document.querySelector('input[type="file"]')).catch(() => false);
      if (done) return { ok: true };
    }
    return { ok: false, reason: "Instagram did not say the story went up; look in the app" };
  }

  // ── Reels ─────────────────────────────────────────────────────────────────────────────────────────────────────

  /** Reels open in the out tab, and the one in view. */
  async reels() {
    const page = await this.outPage();
    if (!/\/reels/.test(page.url())) {
      if (!(await this.goto(`${HOME}reels/`, page))) return null;
      await delay(3000);
    }
    return await this.reelNow();
  }

  /** The reel in view: the one playing, else the one nearest the top. */
  async reelNow() {
    const page = await this.outPage();
    const items = await page.evaluate(reelsInPage, SEL).catch(() => []);
    const now = items.find((x) => x.playing)
      || items.filter((x) => x.top > -x.height / 2).sort((a, b) => Math.abs(a.top) - Math.abs(b.top))[0];
    return now && now.id ? now : null;
  }

  /** On to the next reel, as a thumb would. */
  async reelNext() {
    const page = await this.outPage();
    const clicked = await page.evaluate(() => {
      const b = [...document.querySelectorAll('div[role="button"], button')]
        .find((x) => /^next$/i.test((x.getAttribute("aria-label") || "").trim()) && x.getClientRects().length);
      if (b) { b.click(); return true; }
      return false;
    }).catch(() => false);
    if (!clicked) await page.keyboard.press("ArrowDown").catch(() => {});
    await delay(1400 + Math.random() * 900);
  }

  /** Like the reel in view. */
  async reelLike(id, { dryRun = false } = {}) {
    const page = await this.outPage();
    if (dryRun) {
      console.log(`${this.tag} (dry run) would have liked a reel`);
      return { ok: true, dry: true };
    }
    const pressed = await page.evaluate((code) => {
      const videos = [...document.querySelectorAll("video")];
      for (const v of videos) {
        let box = v;
        for (let i = 0; i < 8 && box.parentElement; i++) {
          box = box.parentElement;
          if (box.querySelector('svg[aria-label="Like"], svg[aria-label="Unlike"]')) break;
        }
        const here = box.querySelector(`a[href*="/${code}/"]`);
        if (code && !here) continue;
        const like = box.querySelector('svg[aria-label="Like"]');
        if (!like) return "already";
        (like.closest('div[role="button"], button, span') || like).click();
        return "clicked";
      }
      return "";
    }, String(id || "")).catch(() => "");
    if (pressed === "already") return { ok: true, already: true };
    if (pressed !== "clicked") return { ok: false, reason: "Instagram's Like was not there" };
    await delay(1300);
    return { ok: true };
  }

  // ── Posts: someone's, and its own ─────────────────────────────────────────────────────────────────────────────

  /** Someone's newest posts as their profile shows them. */
  async profilePosts(username, n = 6) {
    const u = cleanUsername(username);
    if (!u) return [];
    const page = await this.outPage();
    if (!(await this.goto(`${HOME}${u}/`, page))) return [];
    let posts = [];
    for (let i = 0; i < 8; i++) {
      posts = await page.evaluate(postsInPage, SEL, n).catch(() => []);
      if (posts.length) return posts;
      await delay(1200);
    }
    return posts;
  }

  /** Its own newest posts. */
  async ownPosts(n = 3) {
    if (!this.username) return [];
    const page = await this.sidePage();
    if (!(await this.goto(`${HOME}${this.username}/`, page))) return [];
    for (let i = 0; i < 8; i++) {
      const posts = await page.evaluate(postsInPage, SEL, n).catch(() => []);
      if (posts.length) return posts;
      await delay(1200);
    }
    return [];
  }

  /** A post open in a tab: { page, code } or null. */
  async openPost(url, page = null) {
    const code = (String(url || "").match(/\/(?:p|reel|reels|tv)\/([A-Za-z0-9_-]{5,24})/) || [])[1];
    if (!code) return null;
    page = page || (await this.outPage());
    if (!page.url().includes(code) && !(await this.goto(url.split("?")[0], page))) return null;
    for (let i = 0; i < 10; i++) {
      const there = await page.evaluate(() => !!document.querySelector("article, main img, main video")).catch(() => false);
      if (there) return { page, code };
      await delay(800);
    }
    return null;
  }

  /** Like (or save) a post, after a moment on it. */
  async pressPost(url, which, { dryRun = false, watchMs = 0 } = {}) {
    const open = await this.openPost(url);
    if (!open) return { ok: false, reason: "Instagram did not open the post" };
    const word = which === "save" ? "Save" : "Like";
    await delay(watchMs || 2000 + Math.random() * 5000);
    if (dryRun) {
      console.log(`${this.tag} (dry run) would have pressed ${word} on ${url}`);
      return { ok: true, dry: true };
    }
    const state = await open.page.evaluate((what) => {
      const want = what === "save" ? ["Save", "Remove"] : ["Like", "Unlike"];
      const on = document.querySelector(`svg[aria-label="${want[1]}"]`);
      if (on) return "already";
      const off = document.querySelector(`svg[aria-label="${want[0]}"]`);
      if (!off) return "nobutton";
      (off.closest('div[role="button"], button, span') || off).click();
      return "clicked";
    }, which).catch(() => "nobutton");
    if (state === "already") return { ok: true, already: true };
    if (state !== "clicked") return { ok: false, reason: `Instagram's ${word} was not there` };
    await delay(1500);
    const took = await open.page.evaluate((what) => {
      const want = what === "save" ? "Remove" : "Unlike";
      return !!document.querySelector(`svg[aria-label="${want}"]`);
    }, which).catch(() => false);
    return took ? { ok: true } : { ok: false, reason: `Instagram did not take the ${word.toLowerCase()}` };
  }

  likePost(url, opts = {}) {
    return this.pressPost(url, "like", opts);
  }

  savePost(url, opts = {}) {
    return this.pressPost(url, "save", opts);
  }

  /** The comments under a post: [{ index, username, text, mine }]. */
  async readComments(url, page = null) {
    const open = await this.openPost(url, page);
    if (!open) return [];
    // Instagram hides the older ones behind "Load more comments".
    await open.page.evaluate(clickSaidInPage, "^(load more comments|view more comments)$", "i").catch(() => {});
    await delay(1800);
    return await open.page.evaluate(commentsInPage, SEL, this.username).catch(() => []);
  }

  /** A public reply to one comment under a post. */
  async replyToComment(url, index, text, { dryRun = false, page = null } = {}) {
    const open = await this.openPost(url, page);
    if (!open) return { ok: false, reason: "Instagram did not open the post" };
    const opened = await open.page.evaluate((i) => {
      const lists = [...document.querySelectorAll("ul")].sort((a, b) => b.querySelectorAll("li").length - a.querySelectorAll("li").length);
      const items = lists[0] ? [...lists[0].querySelectorAll("li")].filter((li) => !li.querySelector("li")) : [];
      const li = items[i];
      if (!li) return false;
      li.scrollIntoView({ block: "center" });
      const b = [...li.querySelectorAll('div[role="button"], button, span')]
        .find((x) => /^reply$/i.test((x.innerText || "").trim()));
      if (!b) return false;
      b.click();
      return true;
    }, index).catch(() => false);
    if (!opened) return { ok: false, reason: "Instagram's Reply was not there" };
    await delay(900);
    const box = await this.firstOf(open.page, SEL.commentBox);
    if (!box) return { ok: false, reason: "Instagram's comment box was not there" };
    await this.typeInto(open.page, box, String(text).slice(0, 150));
    if (dryRun) {
      await this.clearTyped(open.page);
      console.log(`${this.tag} (dry run) would have replied: ${String(text).slice(0, 120)}`);
      return { ok: true, dry: true };
    }
    await delay(600);
    if (!(await open.page.evaluate(clickSaidInPage, "^post$", "i").catch(() => ""))) {
      await open.page.keyboard.press("Enter");
    }
    await delay(2200);
    return { ok: true };
  }

  /** A comment under someone's post, in public. */
  async commentOnPost(url, text, { dryRun = false } = {}) {
    const words = String(text || "").replace(/\s+/g, " ").trim().slice(0, 150);
    if (!words) return { ok: false, reason: "nothing to say" };
    const open = await this.openPost(url);
    if (!open) return { ok: false, reason: "Instagram did not open the post" };
    const box = await this.firstOf(open.page, SEL.commentBox);
    if (!box) return { ok: false, reason: "Instagram's comment box was not there (comments may be off)" };
    await delay(1500 + Math.random() * 3000);
    await this.typeInto(open.page, box, words);
    if (dryRun) {
      await this.clearTyped(open.page);
      console.log(`${this.tag} (dry run) would have commented on ${url}: ${words.slice(0, 120)}`);
      return { ok: true, dry: true };
    }
    await delay(600 + Math.random() * 800);
    if (!(await open.page.evaluate(clickSaidInPage, "^post$", "i").catch(() => ""))) {
      await open.page.keyboard.press("Enter");
    }
    await delay(2500);
    const seen = await open.page.evaluate((me, start) => {
      const links = [...document.querySelectorAll(`a[href="/${me}/"]`)];
      return links.some((a) => {
        let row = a;
        for (let i = 0; i < 6 && row.parentElement; i++) row = row.parentElement;
        return (row.innerText || "").includes(start);
      });
    }, this.username, words.slice(0, 20)).catch(() => false);
    return seen ? { ok: true } : { ok: true, unconfirmed: true };
  }

  /**
   * Post a picture or a video: Instagram's own create flow (the plus in the sidebar), the file, the caption, Share.
   * `as` is "post" or "reel"; a story goes through postStory. { ok, dry, reason }
   */
  async postMedia(file, caption = "", { as = "post", dryRun = false } = {}) {
    if (!file || !fs.existsSync(file)) return { ok: false, reason: "That file is not on this computer any more" };
    if (as === "story") return await this.postStory(file, caption, { dryRun });
    const page = await this.outPage();
    if (!(await this.goto(`${HOME}`, page))) return { ok: false, reason: "Instagram did not open" };
    await delay(2500);
    await page.evaluate(clickSaidInPage, "^(new post|create)$", "i").catch(() => {});
    await delay(1500);
    await page.evaluate(clickSaidInPage, "^(post|reel)$", "i").catch(() => {});
    await delay(1200);
    let input = null;
    for (let i = 0; i < 8 && !input; i++) {
      input = await this.firstOf(page, SEL.createInput);
      if (!input) {
        await page.evaluate(clickSaidInPage, "^(select from computer|select from device)$", "i").catch(() => {});
        await delay(1200);
      }
    }
    if (!input) return { ok: false, reason: "Instagram's create window did not open" };
    await input.uploadFile(file);
    await delay(4000);
    // Its three steps: crop, then filters, then the caption, each behind Next.
    for (let i = 0; i < 3; i++) {
      const next = await page.evaluate(clickSaidInPage, "^next$", "i").catch(() => "");
      if (!next) break;
      await delay(2000);
    }
    const box = await this.firstOf(page, SEL.createCaption);
    if (!box) {
      await this.discardPost(page);
      return { ok: false, reason: "Instagram's caption box was not there; nothing was posted" };
    }
    await this.typeInto(page, box, String(caption || "").slice(0, 2200));
    await delay(900);
    if (dryRun) {
      console.log(`${this.tag} (dry run) would have posted ${path.basename(file)} as a ${as}: ${String(caption || "").slice(0, 120)}`);
      await this.discardPost(page);
      return { ok: true, dry: true };
    }
    if (!(await page.evaluate(clickSaidInPage, "^share$", "i").catch(() => ""))) {
      await this.discardPost(page);
      return { ok: false, reason: "Instagram's Share was not there; nothing was posted" };
    }
    for (let i = 0; i < 60; i++) {
      await delay(2000);
      const done = await page.evaluate(() => /your (post|reel) has been shared|post shared|reel shared/i
        .test(document.body?.innerText || "")).catch(() => false);
      if (done) {
        await page.evaluate(clickSaidInPage, "^close$", "i").catch(() => {});
        return { ok: true };
      }
    }
    return { ok: false, reason: "Instagram did not say the post went up; look in the app" };
  }

  /** The create window thrown away rather than left half done. */
  async discardPost(page) {
    await page.evaluate(clickSaidInPage, "^close$", "i").catch(() => {});
    await delay(1200);
    await page.evaluate(clickSaidInPage, "^discard$", "i").catch(() => {});
    await delay(1200);
    await this.goto("about:blank", page).catch(() => {});
  }

  // ── Its Note, and its activity status ─────────────────────────────────────────────────────────────────────────

  /** The little note above its name in everyone's inbox, set to `text` (at most 60 characters). */
  async setNote(text) {
    const words = String(text || "").trim().slice(0, 60);
    if (!words) return { ok: false, reason: "nothing to say" };
    const page = await this.sidePage();
    if (!(await this.goto(`${HOME}direct/inbox/`, page))) return { ok: false, reason: "Instagram's inbox would not open" };
    await delay(2200);
    const opened = await page.evaluate(clickSaidInPage, "(leave a note|your note|note\\.\\.\\.)", "i").catch(() => "");
    if (!opened) return { ok: false, reason: "Instagram's website has no Notes for this account" };
    await delay(1500);
    const box = await this.firstOf(page, SEL.noteBox) || await this.onlyTextBox(page);
    if (!box) return { ok: false, reason: "Instagram's note box was not there" };
    await this.typeInto(page, box, words);
    await delay(600);
    if (!(await page.evaluate(clickSaidInPage, "^(share|post|done)$", "i").catch(() => ""))) {
      await page.keyboard.press("Enter");
    }
    await delay(2000);
    return { ok: true, note: words };
  }

  /** Instagram's "Show activity status" switch, set on or off; null when the page has no such switch. */
  async setActivityStatus(on) {
    const page = await this.sidePage();
    if (!(await this.goto(`${HOME}accounts/activity_status/`, page))) return null;
    await delay(2000);
    return await page.evaluate((want) => {
      const sw = document.querySelector('input[type="checkbox"], [role="switch"]');
      if (!sw) return null;
      const now = sw.getAttribute("aria-checked") === "true" || sw.checked === true;
      if (now !== want) (sw.closest("label") || sw).click();
      return want;
    }, !!on).catch(() => null);
  }

  // ── Health ────────────────────────────────────────────────────────────────────────────────────────────────────

  /** Which of the inbox's markers still match: { matched: {name: selector}, missing: [names] }. */
  async selectorHealth() {
    // What must be there: the list itself (an inbox with nothing in it still has one), and, with a conversation
    // open, the box to type in. The rows themselves are only counted, never missed: an empty inbox has none, and
    // that is not Instagram changing its page.
    const names = ["threadList"];
    if (/\/direct\/t\//.test(this.page.url())) names.push("composer");
    const out = { matched: {}, missing: [] };
    for (const n of names) {
      const hit = await this.page.evaluate(pickIn, SEL[n]).catch(() => "");
      if (hit) out.matched[n] = hit; else out.missing.push(n);
    }
    out.rows = (await this.listThreads().catch(() => [])).length;
    this.health = out;
    return out;
  }

  // ── Media off the page ────────────────────────────────────────────────────────────────────────────────────────

  _tempDir() {
    const dir = path.join(this.dataDir, "config", "temp");
    fs.mkdirSync(dir, { recursive: true });
    return dir;
  }

  /** A picture shown in the open conversation, saved as a file (its newest, a photo they sent). */
  async capturePhoto(stem) {
    const handle = await this.page.evaluateHandle((sel) => {
      const pickAll = (sels) => { for (const s of sels) { try { const a = [...document.querySelectorAll(s)]; if (a.length) return a; } catch { /* bad */ } } return []; };
      const imgs = pickAll(sel.message).flatMap((m) => [...m.querySelectorAll("img")])
        .filter((i) => i.getBoundingClientRect().width > 90);
      return imgs.pop() || null;
    }, SEL).catch(() => null);
    const el = handle && handle.asElement ? handle.asElement() : null;
    if (!el) return "";
    const file = path.join(this._tempDir(), `${stem}_${Date.now()}.png`);
    try {
      await el.screenshot({ path: file });
      return file;
    } catch {
      return "";
    }
  }

  /** Whatever is behind a link, fetched from inside the page (where its session signs the request). */
  async fetchInPage(page, url, limit = 40000000) {
    return await page.evaluate(async (src, cap) => {
      try {
        const r = await fetch(src, { credentials: "include" });
        if (!r.ok) return null;
        const buf = await r.arrayBuffer();
        if (buf.byteLength < 1000 || buf.byteLength > cap) return null;
        const bytes = new Uint8Array(buf);
        let s = "";
        for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
        return { b64: btoa(s), type: r.headers.get("content-type") || "" };
      } catch {
        return null;
      }
    }, url, limit).catch(() => null);
  }

  _write(data, stem, kinds) {
    const ext = kinds.find(([re]) => re.test(data.type || ""))?.[1] || kinds[kinds.length - 1][1];
    const file = path.join(this._tempDir(), `${stem}_${Date.now()}${ext}`);
    fs.writeFileSync(file, Buffer.from(data.b64, "base64"));
    return file;
  }

  /** A video in the open conversation (one they sent), its newest, saved as a file to be watched. */
  async captureVideo(stem) {
    const src = await this.page.evaluate(() => {
      const v = [...document.querySelectorAll("video")].pop();
      return v ? (v.currentSrc || v.src || "") : "";
    }).catch(() => "");
    if (!src) return "";
    const data = await this.fetchInPage(this.page, src);
    return data && data.b64
      ? this._write(data, stem, [[/webm/, ".webm"], [/quicktime/, ".mov"], [/./, ".mp4"]])
      : "";
  }

  /** A voice note in the open conversation, its newest, saved as a file to be transcribed. */
  async captureVoice(stem) {
    const src = await this.page.evaluate(() => {
      const a = [...document.querySelectorAll("audio")].pop();
      return a ? (a.currentSrc || a.src || "") : "";
    }).catch(() => "");
    if (!src) return "";
    const data = await this.fetchInPage(this.page, src, 12000000);
    return data && data.b64
      ? this._write(data, stem, [[/ogg|opus/, ".ogg"], [/mpeg|mp3/, ".mp3"], [/wav/, ".wav"], [/./, ".m4a"]])
      : "";
  }

  /**
   * A reel, post or story opened in the out tab and its media saved as a file, so Python can watch it: Instagram
   * shows almost none of this to anyone not signed in. { file, kind, facts } or {}.
   */
  async captureMedia(url, stem = "insta_media") {
    const page = await this.outPage();
    const story = /\/stories\//.test(String(url || ""));
    if (!(await this.goto(String(url).split("?")[0], page))) return {};
    await delay(2800);
    if (story) await page.evaluate(clickSaidInPage, "^(view story|watch story|continue)$", "i").catch(() => {});
    let found = null;
    for (let i = 0; i < 8 && !found; i++) {
      found = await page.evaluate(() => {
        const v = [...document.querySelectorAll("video")].find((x) => x.currentSrc || x.src);
        if (v) return { src: v.currentSrc || v.src, video: true };
        const img = [...document.querySelectorAll("article img, main img, img")]
          .filter((x) => x.getBoundingClientRect().width > 200)
          .sort((a, b) => b.getBoundingClientRect().width - a.getBoundingClientRect().width)[0];
        return img ? { src: img.currentSrc || img.src, video: false } : null;
      }).catch(() => null);
      if (!found) await delay(1200);
    }
    const facts = await page.evaluate(() => {
      const nameOf = (href) => (String(href || "").match(/^\/([A-Za-z0-9._]{1,30})\/?$/) || [])[1] || "";
      const who = [...document.querySelectorAll('a[href^="/"]')]
        .map((a) => nameOf(a.getAttribute("href")))
        .find((u) => u && !/^(p|reel|reels|explore|direct|stories|accounts|about|legal)$/.test(u)) || "";
      const cap = document.querySelector("h1") || [...document.querySelectorAll('span[dir="auto"]')]
        .find((e) => (e.innerText || "").trim().length > 8);
      return { author: who.toLowerCase(), caption: (cap ? cap.innerText : "").replace(/\s+/g, " ").trim().slice(0, 400) };
    }).catch(() => ({}));
    if (!found || !found.src) {
      await this.goto("about:blank", page).catch(() => {});
      return { facts };
    }
    const data = await this.fetchInPage(page, found.src, found.video ? 40000000 : 8000000);
    await this.goto("about:blank", page).catch(() => {});
    if (!data || !data.b64) return { facts };
    const file = found.video
      ? this._write(data, stem, [[/webm/, ".webm"], [/quicktime/, ".mov"], [/./, ".mp4"]])
      : this._write(data, stem, [[/png/, ".png"], [/webp/, ".webp"], [/./, ".jpg"]]);
    return { file, kind: found.video ? "video" : "photo", facts };
  }
}
