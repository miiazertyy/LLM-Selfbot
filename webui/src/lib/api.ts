import { writable } from "svelte/store";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/**
 * Requests currently in flight that a page is waiting on.
 *
 * Every page loads through this one helper, so tracking it here is enough to
 * know when the panel is stuck waiting rather than broken, without touching a
 * single page.
 *
 * Only reads count. A reply legitimately takes up to two minutes because the
 * bot is reading, thinking and typing, and an install is minutes of
 * downloading: neither is a page failing to load, and warning about them would
 * make the hint noise that people learn to ignore.
 */
export const inflight = writable<{ path: string; started: number }[]>([]);

const SLOW_EXEMPT = [
  "/api/chats/reply",
  "/api/pictures",
  "/api/snapchat/install",
  "/api/minecraft/",
  "/api/system/update",
  "/api/system/ffmpeg/install",
  "/api/friends/",
  "/api/local/",
  // A provider's model list is a round trip to that provider.
  "/api/providers/",
  // The community catalog, a profile's files and its download: GitHub, at GitHub's pace.
  "/api/community",
  // Who is in each call, asked again and again behind the list of channels.
  "/api/chats/voice",
];

function watched(path: string, method: string): boolean {
  if (method !== "GET") return false;
  return !SLOW_EXEMPT.some((p) => path.startsWith(p));
}

async function request(path: string, options: RequestInit = {}): Promise<any> {
  const method = options.method || "GET";
  // Says it is the panel itself: changes that act as you on GitHub refuse anything without it, so another website's
  // page can't make them (it can't send this header without asking first, and the panel never says yes).
  const headers: Record<string, string> = { "x-llmselfbot": "1", ...(options.headers as any) };
  if (options.body && !(options.body instanceof FormData)) {
    headers["content-type"] = "application/json";
  }

  const track = watched(path, method);
  const entry = { path, started: Date.now() };
  if (track) inflight.update((l) => [...l, entry]);

  try {
    const res = await fetch(path, { ...options, method, headers, credentials: "same-origin" });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const data = await res.json();
        detail = data.detail || JSON.stringify(data);
      } catch {}
      throw new ApiError(res.status, detail);
    }
    const ct = res.headers.get("content-type") || "";
    // Awaited, not returned bare: `finally` runs the moment the function
    // returns, so an unawaited promise would drop the entry before the body
    // had actually arrived.
    if (ct.includes("application/json")) return await res.json();
    return res;
  } finally {
    if (track) inflight.update((l) => l.filter((e) => e !== entry));
  }
}

/** A file sent as a request's body, read off the disk as it goes (never held in memory), with how far it has got.
 *  `abort` stops it, rejecting with status 0. */
function sendFile(url: string, file: File, onProgress: (done: number, total: number) => void) {
  const xhr = new XMLHttpRequest();
  const done = new Promise<any>((resolve, reject) => {
    xhr.open("POST", url);
    xhr.setRequestHeader("x-llmselfbot", "1");
    xhr.setRequestHeader("content-type", "application/octet-stream");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded, e.total); };
    xhr.onload = () => {
      let data: any = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {}
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new ApiError(xhr.status, data?.detail || xhr.statusText));
    };
    xhr.onerror = () => reject(new ApiError(-1, "The file could not be sent."));
    xhr.onabort = () => reject(new ApiError(0, "Stopped."));
    xhr.send(file);
  });
  return { done, abort: () => xhr.abort() };
}

// ── A Minecraft account's screen, as its bot reports it (agent_hooks.mjs hudOf) ──
/** One slot: its picture is textures/<tex>/<icon> under the view, and `slot` is where it is, for a click. */
export type McSlot = { name: string; id: string; count: number; left: number | null; icon?: string; ench?: boolean;
                       slot?: number; lore?: string[] } | null;
export type McHud = {
  ok: boolean; reason?: string; who: string; health: number; food: number; saturation?: number; air: number | null;
  at: { x: number; y: number; z: number }; where: string; day: number; ticks: number; raining: number;
  yaw?: number; pitch?: number; held: number;
  hotbar: McSlot[]; carried: NonNullable<McSlot>[]; armour: McSlot[]; armourPoints?: number; offhand?: McSlot;
  xp?: { level: number; progress: number }; mode?: string; hardcore?: boolean;
  effects?: { id: number; name: string; level: number; left: number | null; good: boolean; icon: string }[];
  bossBars?: { title: string; health: number; color: string; notches: number }[];
  sidebar?: { title: string; rows: { text: string; value: number | null; fixed?: string }[] } | null;
  title?: { text: string; sub: string; at: number; for: number } | null;
  overHotbar?: string;
  window?: { title: string; kind: string; slots: McSlot[]; cursor?: McSlot } | null;
  dead?: boolean; sleeping?: boolean; driving?: boolean;
  near: { name: string; away: number }[];
  chat: { text: string; from: string; at: number }[];
  tex?: string; sprites?: boolean;
  players?: { name: string; shown: string; ping: number; away: number | null }[];
  tabTop?: string; tabBottom?: string;
  debug?: {
    xyz: number[]; block: number[]; chunk: number[]; inChunk: number[]; facing: string; toward: string;
    yaw: number; pitch: number; biome: string; light: number | null; sky: number | null;
    looking: { name: string; at: number[] } | null; target: { name: string; away: number } | null;
    speed: number; ground: boolean; entities: number; players: number; ping: number; tps: number | null;
    version: string; brand: string; difficulty: string; memory: number;
    net?: { sent: string[]; got: string[] };
  };
};
/** One thing a persona saw online in its free time. */
export type WebSeen = { ts: number; title: string; url: string; site: string; note: string };
export type WebJournal = {
  persona: string; entries: WebSeen[]; free_time: boolean; sessions_per_day: number; next_at: number | null;
  browser: { ready: boolean; why: string; running: boolean; resting: boolean }; busy: boolean;
};
export type WebNow = {
  busy: boolean; persona: string; name: string; step: string; steps: string[]; url: string; since: number;
  shot: string; shot_at: number;
  last: { persona: string; at: number; saw: { title: string; url: string; site: string; note: string }[];
          seconds: number } | null;
};
/** What the hands are doing, sent whole each time. */
export type McInput = {
  keys: { forward: boolean; back: boolean; left: boolean; right: boolean; jump: boolean; sprint: boolean; sneak: boolean };
  yaw: number; pitch: number; attack: boolean; use: boolean;
};

/** A path asked as one persona (app/utils/personas.py). Left as it is for "", which the server reads as Default. */
function scoped(path: string, persona = ""): string {
  if (!persona) return path;
  return `${path}${path.includes("?") ? "&" : "?"}persona=${encodeURIComponent(persona)}`;
}

export const api = {
  request,
  status: () => request("/api/status"),
  /** Which socials are switched on (lib/socials.ts). */
  socials: (): Promise<{ on: Record<string, boolean> }> => request("/api/socials"),
  accounts: () => request("/api/accounts"),
  accountAction: (id: string, action: string) =>
    request(`/api/accounts/${id}/${action}`, { method: "POST" }),
  accountDetails: (id: string) => request(`/api/accounts/${id}/details`),
  /** Per account: replies per day, today and this week, who it talks to most. */
  accountActivity: (days = 7) => request(`/api/accounts/activity?days=${days}`),
  accountMood: (id: string, mood: string) =>
    request(`/api/accounts/${id}/mood`, { method: "POST", body: JSON.stringify({ mood }) }),
  serviceAction: (name: string, action: string) =>
    request(`/api/services/${name}/${action}`, { method: "POST" }),
  /** The Telegram page (telegram_routes.py): connecting the control bot, and checking it. */
  telegram: () => request("/api/telegram"),
  telegramCheck: (token = "") =>
    request("/api/telegram/check", { method: "POST", body: JSON.stringify({ token }) }),
  telegramToken: (token: string) =>
    request("/api/telegram/token", { method: "POST", body: JSON.stringify({ token }) }),
  telegramFindOwner: () => request("/api/telegram/find-owner", { method: "POST" }),
  telegramOwner: (id: string) =>
    request("/api/telegram/owner", { method: "POST", body: JSON.stringify({ id }) }),
  telegramTest: () => request("/api/telegram/test", { method: "POST" }),
  telegramCommands: () => request("/api/telegram/commands"),
  command: (target: string, cmd: string, payload: any = {}, timeout = 15) =>
    request("/api/command", {
      method: "POST",
      body: JSON.stringify({ target, cmd, payload, timeout }),
    }),
  // Account slots. Credentials are write-only: `slots` reports token_set /
  // password_set booleans, never the value.
  slots: () => request("/api/accounts/slots"),
  addSlot: (platform: string, body: any) =>
    request(`/api/accounts/slots/${platform}`, { method: "POST", body: JSON.stringify(body) }),
  updateSlot: (platform: string, index: number, body: any) =>
    request(`/api/accounts/slots/${platform}/${index}`, { method: "POST", body: JSON.stringify(body) }),
  deleteSlot: (platform: string, index: number) =>
    request(`/api/accounts/slots/${platform}/${index}`, { method: "DELETE" }),
  // Add a Discord account by signing in, in a real browser window. The app
  // never sees the password: it reads the token out of the session the person
  // ends up signed into, stores it server-side, and never returns it here.
  // Whatever Discord asks for on the way - a captcha, a new-device email, a
  // passkey - the person answers it in the window, which is the whole point.
  discordBrowserLoginStart: (body: { proxy?: string }) =>
    request("/api/accounts/discord/browser-login/start", { method: "POST", body: JSON.stringify(body) }),
  discordBrowserLoginStatus: (proxy?: string) =>
    request(`/api/accounts/discord/browser-login/status${proxy ? `?proxy=${encodeURIComponent(proxy)}` : ""}`),
  discordBrowserLoginCancel: () =>
    request("/api/accounts/discord/browser-login/cancel", { method: "POST" }),
  // A TikTok account, signed in in a browser window of its own (app/utils/tiktok_browser_login.py).
  tiktokBrowserLoginStart: (body: { proxy?: string } = {}) =>
    request("/api/accounts/tiktok/browser-login/start", { method: "POST", body: JSON.stringify(body) }),
  tiktokBrowserLoginStatus: () => request("/api/accounts/tiktok/browser-login/status"),
  tiktokBrowserLoginCancel: () => request("/api/accounts/tiktok/browser-login/cancel", { method: "POST" }),

  // Reddit signs in the same way: a window opens, a person signs in, the session stays in its profile.
  redditBrowserLoginStart: (body: { proxy?: string } = {}) =>
    request("/api/accounts/reddit/browser-login/start", { method: "POST", body: JSON.stringify(body) }),
  redditBrowserLoginStatus: () => request("/api/accounts/reddit/browser-login/status"),
  redditBrowserLoginCancel: () => request("/api/accounts/reddit/browser-login/cancel", { method: "POST" }),
  redditCard: (url: string) => request(`/api/chats/reddit-card?url=${encodeURIComponent(url)}`),
  xCard: (url: string) => request(`/api/chats/x-card?url=${encodeURIComponent(url)}`),
  // WhatsApp: a code to type into the phone, or a QR to point it at. Nothing opens on this machine.
  whatsappLinkStart: (body: { number?: string; way?: "code" | "qr"; proxy?: string }) =>
    request("/api/accounts/whatsapp/link/start", { method: "POST", body: JSON.stringify(body) }),
  whatsappLinkStatus: () => request("/api/accounts/whatsapp/link/status"),
  whatsappLinkCancel: () => request("/api/accounts/whatsapp/link/cancel", { method: "POST" }),
  redditSignInCode: (code: string, index = 0) =>
    request("/api/accounts/reddit/sign-in/code",
            { method: "POST", body: JSON.stringify({ code, index }) }),
  // Instagram signs itself in, in a window you can watch: its login is the app's to keep, so adding an account
  // hands it over once and every sign-in after uses it. A code from the account's email or phone is the one thing
  // only a person has.
  instagramSignInStart: (body: { index?: number; username?: string; password?: string; totp?: string; proxy?: string }) =>
    request("/api/accounts/instagram/sign-in/start", { method: "POST", body: JSON.stringify(body) }),
  instagramSignInStatus: () => request("/api/accounts/instagram/sign-in/status"),
  instagramSignInCode: (code: string, index = 0) =>
    request("/api/accounts/instagram/sign-in/code", { method: "POST", body: JSON.stringify({ code, index }) }),
  instagramSignInCancel: () => request("/api/accounts/instagram/sign-in/cancel", { method: "POST" }),
  // X the same way, with one more thing on it: the email or phone X asks for when it questions a login.
  xSignInStart: (body: { index?: number; username?: string; password?: string; totp?: string; email?: string; proxy?: string }) =>
    request("/api/accounts/x/sign-in/start", { method: "POST", body: JSON.stringify(body) }),
  xSignInStatus: () => request("/api/accounts/x/sign-in/status"),
  xSignInCode: (code: string, index = 0) =>
    request("/api/accounts/x/sign-in/code", { method: "POST", body: JSON.stringify({ code, index }) }),
  xSignInCancel: () => request("/api/accounts/x/sign-in/cancel", { method: "POST" }),
  // iMessage: whether a BlueBubbles server answers at that address with that password, and what it says of the Mac
  // (app/utils/bluebubbles.py). Editing one, an empty password is the one saved for that account.
  /** An iPhone iMessage account's address for its Shortcuts automation, with a QR code of it, and whether the phone
   *  has been heard from. `base` is where this page was opened, when that was not this PC. */
  imessageRelay: (index: number, base = "") =>
    request(`/api/imessage/relay/${index}${base ? `?base=${encodeURIComponent(base)}` : ""}`) as Promise<{
      ok: boolean; reason?: string; url?: string; qr?: string; open?: boolean; bind?: string;
      addresses?: { url: string; kind: string }[]; heard?: { at: number; test: boolean } | null;
    }>,
  /** Signing a Telegram account in: its api_id and api_hash from my.telegram.org, its number, then the code
   *  Telegram sends and, where the account has one, its two-step password. The session never comes back. */
  telegramSignInStart: (body: { index?: number; api_id?: string; api_hash?: string; phone?: string; proxy?: string }) =>
    request("/api/accounts/telegram/sign-in/start", { method: "POST", body: JSON.stringify(body) }) as Promise<{
      state: string; detail?: string; phone?: string;
    }>,
  telegramSignInStatus: () => request("/api/accounts/telegram/sign-in/status") as Promise<{
    state: string; detail?: string; index?: number; slots?: unknown[]; name?: string; username?: string;
  }>,
  telegramSignInCode: (code: string) =>
    request("/api/accounts/telegram/sign-in/code", { method: "POST", body: JSON.stringify({ code }) }),
  telegramSignInPassword: (password: string) =>
    request("/api/accounts/telegram/sign-in/password", { method: "POST", body: JSON.stringify({ password }) }),
  telegramSignInCancel: () => request("/api/accounts/telegram/sign-in/cancel", { method: "POST" }),
  /** A Minecraft account signed in with Microsoft: a code to type (or open) at microsoft.com/link, then its real
   *  name, from Microsoft. The server it plays on comes along, so the account is added whole. */
  minecraftSignInStart: (body: { host?: string; port?: string; index?: number }) =>
    request("/api/accounts/minecraft/sign-in/start", { method: "POST", body: JSON.stringify(body) }) as Promise<{
      state: string; code?: string; link?: string; uri?: string; expires?: number; reason?: string;
    }>,
  minecraftSignInStatus: () => request("/api/accounts/minecraft/sign-in/status") as Promise<{
    state: string; code?: string; link?: string; uri?: string; expires?: number; reason?: string;
    name?: string; index?: number; slots?: unknown[];
  }>,
  minecraftSignInCancel: () => request("/api/accounts/minecraft/sign-in/cancel", { method: "POST" }),
  // A premium account's skin (app/platforms/minecraft/skin_change.py): what its card knows of it, a picture put on
  // it (none: the skin it has, with the arms asked for), or taken off.
  minecraftSkin: (index: number) =>
    request(`/api/accounts/minecraft/${index}/skin`) as Promise<{
      ok: boolean; premium: boolean; slim: boolean; source: string; skin: string; picture: string;
    }>,
  minecraftSkinSet: (index: number, file: File | null, slim: boolean) => {
    const form = new FormData();
    if (file) form.append("file", file, "skin.png");
    form.append("variant", slim ? "slim" : "classic");
    return request(`/api/accounts/minecraft/${index}/skin`, { method: "POST", body: form }) as
      Promise<{ ok: boolean; reason?: string; slim?: boolean }>;
  },
  minecraftSkinReset: (index: number) =>
    request(`/api/accounts/minecraft/${index}/skin`, { method: "DELETE" }) as Promise<{ ok: boolean; reason?: string }>,
  imessageTest: (body: { server: string; password?: string; index?: number }) =>
    request("/api/accounts/imessage/connection/test", { method: "POST", body: JSON.stringify(body) }) as Promise<{
      ok: boolean; reason?: string; server?: string; account?: string; macos?: string; bluebubbles?: string;
      private_api?: boolean; helper?: boolean; warning?: string;
    }>,
  /** A TikTok account's LIVE: on or not, and its last lines and answers. */
  liveFeed: (account: string) => request(`/api/live/${encodeURIComponent(account)}`),
  liveAudio: (account: string, name: string) =>
    `/api/live/${encodeURIComponent(account)}/audio/${encodeURIComponent(name)}`,
  // The practice LIVE (Settings, TikTok, LIVE): who goes live and how, a fresh start, the persona's line to something
  // in its chat (with the LIVE settings on screen), that line said out loud, and its sound.
  // ── Calls (app/web/routes/call_routes.py) ──
  callVoices: (persona = "") => request(`/api/calls/voices${persona ? `?persona=${encodeURIComponent(persona)}` : ""}`),
  callSpeed: (body: { persona: string; speaker: string; voice: string; hear?: string; think?: string; speak?: string }) =>
    request("/api/calls/speed", { method: "POST", body: JSON.stringify(body) }),
  /** A WAV of the voice saying one line. Fetched as a file, not JSON. */
  callPreview: async (body: { engine: string; provider: string; voice: string; persona: string; model?: string }): Promise<Blob> => {
    const r = await fetch("/api/calls/preview", {
      method: "POST", headers: { "content-type": "application/json", "x-llmselfbot": "1" }, body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail || "That voice could not be heard.");
    return r.blob();
  },
  /** Try a call's WebSocket, with the call settings on screen. */
  /** One speaker's voices: listed, fetched from its provider, or typed when they cannot be listed. */
  callSpeakerVoices: (provider: string, model: string, persona = "") =>
    request(`/api/calls/speaker-voices?${new URLSearchParams({ provider, model, ...(persona ? { persona } : {}) })}`),
  /** This computer's own voice (app/voice/onboard.py): what is fetched, and how far a fetch has got. */
  callLocal: () => request("/api/calls/local"),
  callLocalGet: (model: string) => request("/api/calls/local/get", { method: "POST", body: JSON.stringify({ model }) }),
  callLocalRemove: (model: string) => request("/api/calls/local/remove", { method: "POST", body: JSON.stringify({ model }) }),
  callTryUrl: (params: Record<string, string>) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null));
    return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/calls/try?${q}`;
  },
  liveDemo: (persona = "") => request(`/api/live-demo${persona ? `?persona=${encodeURIComponent(persona)}` : ""}`),
  liveDemoStart: () => request("/api/live-demo/start", { method: "POST" }),
  liveDemoAnswer: (body: { event: string; name: string; text: string; persona: string; live: Record<string, unknown> }) =>
    request("/api/live-demo/answer", { method: "POST", body: JSON.stringify(body) }),
  liveDemoVoice: (id: string) => request("/api/live-demo/voice", { method: "POST", body: JSON.stringify({ id }) }),
  liveDemoAudio: (name: string) => `/api/live-demo/audio/${encodeURIComponent(name)}`,
  /** The practice LIVE's screen of its own (livedemo_routes.py): one picture or video per persona, kept with it. */
  liveScreen: (persona: string) => request(`/api/live-demo/screen?persona=${encodeURIComponent(persona)}`),
  uploadLiveScreen: (file: File, persona: string) => {
    const fd = new FormData();
    fd.append("file", file);
    return request(`/api/live-demo/screen?persona=${encodeURIComponent(persona)}`, { method: "POST", body: fd });
  },
  clearLiveScreen: (persona: string) =>
    request(`/api/live-demo/screen?persona=${encodeURIComponent(persona)}`, { method: "DELETE" }),
  /** Its address changes with the file (`version`), so it's kept for good; `still` is a video's still, for its tile. */
  liveScreenUrl: (persona: string, version: number, still = false) =>
    `/api/live-demo/screen/file?persona=${encodeURIComponent(persona)}&v=${version}${still ? "&still=true" : ""}`,
  // TikTok beyond the inbox (app/web/routes/tiktok_routes.py): someone's posts, a video's like, save and comment, a
  // LIVE it is visiting, For You, posting the persona's videos.
  tiktokTheirs: (target: string, user_id: string) =>
    request(`/api/tiktok/theirs?target=${encodeURIComponent(target)}&user_id=${encodeURIComponent(user_id)}`),
  tiktokTheirsRefresh: (target: string, user_id: string) =>
    request("/api/tiktok/theirs/refresh", { method: "POST", body: JSON.stringify({ target, user_id }) }),
  tiktokAction: (target: string, url: string, action: "like" | "save" | "comment", text = "") =>
    request("/api/tiktok/action", { method: "POST", body: JSON.stringify({ target, url, action, text }) }),
  tiktokCommentText: (target: string, url: string) =>
    request("/api/tiktok/comment-text", { method: "POST", body: JSON.stringify({ target, url }) }),
  tiktokOut: (target: string) => request(`/api/tiktok/out?target=${encodeURIComponent(target)}`),
  tiktokVisit: (target: string, handle: string) =>
    request("/api/tiktok/visit", { method: "POST", body: JSON.stringify({ target, handle }) }),
  tiktokLeave: (target: string) => request("/api/tiktok/leave", { method: "POST", body: JSON.stringify({ target }) }),
  tiktokForYou: (target: string) => request("/api/tiktok/foryou", { method: "POST", body: JSON.stringify({ target }) }),
  tiktokPosting: () => request("/api/tiktok/posting"),
  tiktokCaption: (persona: string, name: string) =>
    request("/api/tiktok/caption", { method: "POST", body: JSON.stringify({ persona, name }) }),
  tiktokPost: (body: { target: string; persona: string; name: string; caption: string; privacy: string; dry_run?: boolean }) =>
    request("/api/tiktok/post", { method: "POST", body: JSON.stringify(body) }),
  // A shared TikTok: its caption, whose it is, its cover (TikTok's public oEmbed).
  tiktokCard: (url: string) => request(`/api/chats/tiktok-card?url=${encodeURIComponent(url)}`),
  // ── Instagram beyond the inbox ──
  instagramTheirs: (target: string, user_id: string) =>
    request(`/api/instagram/theirs?target=${encodeURIComponent(target)}&user_id=${encodeURIComponent(user_id)}`),
  instagramTheirsRefresh: (target: string, user_id: string) =>
    request("/api/instagram/theirs/refresh", { method: "POST", body: JSON.stringify({ target, user_id }) }),
  instagramStories: (target: string, user_id: string) =>
    request(`/api/instagram/stories?target=${encodeURIComponent(target)}&user_id=${encodeURIComponent(user_id)}`),
  instagramStory: (target: string, user_id: string, action: "watch" | "reply", text = "", emoji = "") =>
    request("/api/instagram/story", { method: "POST", body: JSON.stringify({ target, user_id, action, text, emoji }) }),
  instagramAction: (target: string, url: string, action: "like" | "save" | "comment", text = "") =>
    request("/api/instagram/action", { method: "POST", body: JSON.stringify({ target, url, action, text }) }),
  instagramCommentText: (target: string, url: string) =>
    request("/api/instagram/comment-text", { method: "POST", body: JSON.stringify({ target, url }) }),
  instagramOut: (target: string) => request(`/api/instagram/out?target=${encodeURIComponent(target)}`),
  instagramReels: (target: string) =>
    request("/api/instagram/reels", { method: "POST", body: JSON.stringify({ target }) }),
  instagramFollow: (target: string, username: string) =>
    request("/api/instagram/follow", { method: "POST", body: JSON.stringify({ target, username }) }),
  instagramNote: (target: string, text = "") =>
    request("/api/instagram/note", { method: "POST", body: JSON.stringify({ target, text }) }),
  instagramPosting: () => request("/api/instagram/posting"),
  // X and Reddit, which share one dialog (PostTo.svelte).
  xPosting: () => request("/api/x/posting"),
  xPost: (body: { target: string; text: string; picture?: string; dry_run?: boolean }) =>
    request("/api/x/post", { method: "POST", body: JSON.stringify(body) }),
  redditPosting: () => request("/api/reddit/posting"),
  redditPost: (body: { target: string; title: string; text: string; where?: string; picture?: string;
                       dry_run?: boolean }) =>
    request("/api/reddit/post", { method: "POST", body: JSON.stringify(body) }),
  whatsappPosting: () => request("/api/whatsapp/posting"),
  whatsappStatus: (body: { target: string; text: string; picture?: string; dry_run?: boolean }) =>
    request("/api/whatsapp/status", { method: "POST", body: JSON.stringify(body) }),
  whatsappGroups: (target: string) => request(`/api/whatsapp/groups?target=${encodeURIComponent(target)}`),
  whatsappLeave: (body: { target: string; chat: string }) =>
    request("/api/whatsapp/group/leave", { method: "POST", body: JSON.stringify(body) }),
  whatsappSeenStatuses: (target: string) =>
    request(`/api/whatsapp/statuses?target=${encodeURIComponent(target)}`),
  instagramCaption: (body: { persona: string; name: string; as: string }) =>
    request("/api/instagram/caption", { method: "POST", body: JSON.stringify(body) }),
  instagramPost: (body: { target: string; persona: string; name: string; caption: string; as: string; dry_run?: boolean }) =>
    request("/api/instagram/post", { method: "POST", body: JSON.stringify(body) }),
  // A shared Instagram post or reel: its caption, whose it is, its picture (the embed page anyone can read).
  instagramCard: (url: string) => request(`/api/chats/instagram-card?url=${encodeURIComponent(url)}`),
  // A persona's settings: everyone's with its own on top (app/utils/personas.py). No persona: everyone's.
  config: (persona = "") => request(`/api/config${persona ? `?persona=${encodeURIComponent(persona)}` : ""}`),
  // The config as JSON text for the raw editor. Text, because parsing it here
  // rounds a Discord ID (past 2^53) and saving then wrote the rounded one.
  configRaw: () => request("/api/config/raw"),
  saveConfigRaw: (text: string) =>
    request("/api/config/raw", { method: "POST", body: JSON.stringify({ text }) }),
  // Settings as a file: every setting as JSON text, and a file read back as a
  // list of changes to pick from before any is written. Both stay text on the
  // way through the page, for the same reason as the raw editor.
  exportSettings: (personal = false) => request(`/api/config/export${personal ? "?personal=true" : ""}`),
  importPreview: (text: string) =>
    request("/api/config/import/preview", { method: "POST", body: JSON.stringify({ text }) }),
  importSettings: (text: string, keys: string[]) =>
    request("/api/config/import", { method: "POST", body: JSON.stringify({ text, keys }) }),
  saveConfig: (config: any) =>
    request("/api/config", { method: "POST", body: JSON.stringify({ config }) }),
  // A reply added to what counts as a refusal (bot.refusal.extra_phrases), from a message's right-click menu.
  addRefusalPhrase: (phrase: string) =>
    request("/api/config/refusal-phrase", { method: "POST", body: JSON.stringify({ phrase }) }),
  // One setting, for everyone, or as one persona's own ({ persona }).
  configField: (key: string, value: any, opts: { persona?: string } = {}) =>
    request("/api/config/field", { method: "POST", body: JSON.stringify({ key, value, persona: opts.persona || undefined }) }),
  schema: (persona = "") => request(`/api/config/schema${persona ? `?persona=${encodeURIComponent(persona)}` : ""}`),
  // ── Persona profiles (app/web/routes/persona_routes.py) ──
  personas: () => request("/api/personas"),
  persona: (pid: string) => request(`/api/personas/${encodeURIComponent(pid)}`),
  createPersona: (body: { name: string; color?: string; color2?: string; copy_from?: string; copy_memory?: boolean }) =>
    request("/api/personas", { method: "POST", body: JSON.stringify(body) }),
  updatePersona: (pid: string, body: { name?: string; color?: string; color2?: string }) =>
    request(`/api/personas/${encodeURIComponent(pid)}`, { method: "PATCH", body: JSON.stringify(body) }),
  deletePersona: (pid: string) => request(`/api/personas/${encodeURIComponent(pid)}`, { method: "DELETE" }),
  assignPersona: (pid: string, account: string) =>
    request(`/api/personas/${encodeURIComponent(pid)}/assign`, { method: "POST", body: JSON.stringify({ account }) }),
  /** What a persona saw online in its free time (app/utils/web/journal.py), and how it browses. */
  webJournal: (persona: string): Promise<WebJournal> =>
    request(`/api/web/journal?persona=${encodeURIComponent(persona)}`),
  /** A free-time session for this persona, now: followed with webNow. */
  webBrowseNow: (persona: string) =>
    request("/api/web/browse-now", { method: "POST", body: JSON.stringify({ persona }) }),
  /** The session as it happens: the step it is on and a picture of the page. */
  webNow: (): Promise<WebNow> => request("/api/web/now"),
  webForget: (persona: string, ts: number) =>
    request(`/api/web/journal/${encodeURIComponent(persona)}/${ts}`, { method: "DELETE" }),
  personaText: (pid: string) => request(`/api/personas/${encodeURIComponent(pid)}/text`),
  // A persona from your own chats (app/utils/chatpersona.py): your side only, from the exports the socials give you.
  fromChatsStatus: () => request("/api/from-chats/status"),
  fromChatsUpload: (file: File, onProgress: (done: number, total: number) => void) =>
    sendFile(`/api/from-chats/upload?name=${encodeURIComponent(file.name)}`, file, onProgress),
  fromChatsRemove: (key: string) =>
    request("/api/from-chats/remove", { method: "POST", body: JSON.stringify({ key }) }),
  fromChatsWrite: () => request("/api/from-chats/write", { method: "POST" }),
  fromChatsCreate: (name: string, color: string, color2 = "") =>
    request("/api/from-chats/create", { method: "POST", body: JSON.stringify({ name, color, color2 }) }),
  fromChatsReset: () => request("/api/from-chats/reset", { method: "POST" }),
  savePersonaText: (pid: string, text: string) =>
    request(`/api/personas/${encodeURIComponent(pid)}/text`, { method: "POST", body: JSON.stringify({ text }) }),
  setPersonaAvatar: (pid: string, picture: string) =>
    request(`/api/personas/${encodeURIComponent(pid)}/avatar`, { method: "POST", body: JSON.stringify({ picture }) }),
  uploadPersonaAvatar: (pid: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request(`/api/personas/${encodeURIComponent(pid)}/avatar`, { method: "POST", body: fd });
  },
  clearPersonaAvatar: (pid: string) => request(`/api/personas/${encodeURIComponent(pid)}/avatar`, { method: "DELETE" }),
  // ── Community profiles (app/web/routes/community_routes.py): the catalog on GitHub, adding one, sharing your own ──
  community: (force = false) => request(`/api/community${force ? "?force=true" : ""}`),
  communityStats: (force = false) => request(`/api/community/stats${force ? "?force=true" : ""}`),
  communityProfile: (slug: string) => request(`/api/community/profiles/${encodeURIComponent(slug)}`),
  communityFile: (slug: string, name: string, v: number) =>
    `/api/community/files/${encodeURIComponent(slug)}/${name}?v=${v}`,
  communityInstall: (slug: string, copy = false) =>
    request("/api/community/install", { method: "POST", body: JSON.stringify({ slug, copy }) }),
  communityUpdatePreview: (pid: string) => request(`/api/community/installed/${encodeURIComponent(pid)}/update`),
  communityUpdate: (pid: string, confirm = false) =>
    request(`/api/community/installed/${encodeURIComponent(pid)}/update`, { method: "POST", body: JSON.stringify({ confirm }) }),
  communityShareForm: (pid: string) => request(`/api/community/share/${encodeURIComponent(pid)}`),
  communitySharePreview: (pid: string, form: Record<string, unknown>) =>
    request(`/api/community/share/${encodeURIComponent(pid)}/preview`, { method: "POST", body: JSON.stringify(form) }),
  communityShare: (pid: string, form: Record<string, unknown>) =>
    request(`/api/community/share/${encodeURIComponent(pid)}`, { method: "POST", body: JSON.stringify(form) }),
  communityRemove: (slug: string) =>
    request("/api/community/remove", { method: "POST", body: JSON.stringify({ slug }) }),
  communityMine: (force = false) => request(`/api/community/mine${force ? "?force=true" : ""}`),
  communityReport: (slug: string, reason: string, details: string) =>
    request("/api/community/report", { method: "POST", body: JSON.stringify({ slug, reason, details }) }),
  communityQueue: () => request("/api/community/queue"),
  communityModerate: (command: string, target: string, reason = "", number = 0) =>
    request("/api/community/moderate", { method: "POST", body: JSON.stringify({ command, target, reason, number }) }),
  githubSignin: () => request("/api/community/signin"),
  githubSigninStart: () => request("/api/community/signin", { method: "POST" }),
  githubSigninCancel: () => request("/api/community/signin", { method: "DELETE" }),
  githubSignout: () => request("/api/community/signout", { method: "POST" }),
  communityLink: (what: string, opts: { slug?: string; number?: number; open?: boolean } = {}) =>
    request("/api/community/link", { method: "POST", body: JSON.stringify({ what, ...opts }) }),
  resetPersonaSetting: (pid: string, key: string) =>
    request(`/api/personas/${encodeURIComponent(pid)}/settings/${key}`, { method: "DELETE" }),
  // Discord's current client build number, read off its web app just now.
  discordBuildNumber: () => request("/api/discord/build-number"),
  // What Groq actually offers right now, so model names are picked not typed.
  models: (refresh = false) => request(`/api/models${refresh ? "?refresh=true" : ""}`),
  // What is stopping the bot working, tagged by the page that fixes it.
  health: () => request("/api/health"),
  // The uncached answer. /api/health serves the last snapshot and refreshes
  // behind it, which is right for a background poll and wrong straight after
  // a save, when the whole point is to see whether the change fixed anything.
  healthNow: () => request("/api/health/blocking"),
  // Profile card behind a clicked name, assembled from local data only.
  person: (uid: string, persona = "") => request(scoped(`/api/people/${uid}`, persona)),
  peopleSettings: () => request("/api/people/settings"),
  clearPeopleCache: () => request("/api/people/cache", { method: "DELETE" }),
  // Everything in config/.env, including options documented in the template
  // but not yet set. Secrets come back masked; sending a masked value back is
  // ignored server-side so it can never overwrite the real one.
  // Numbered key families (GROQ_API_KEY_1, _2, ...). The server keeps the
  // numbering contiguous, because the loaders stop at the first gap.
  keyList: (name: string) => request(`/api/env/keys/${name}`),
  addKey: (name: string, value: string, extras: Record<string, string> = {}) =>
    request(`/api/env/keys/${name}`, {
      method: "POST",
      body: JSON.stringify({ value, ...extras }),
    }),
  // `keep` leaves the stored credential alone, for editing only a proxy or a
  // password without having to retype the token above it.
  replaceKey: (
    name: string,
    index: number,
    value: string,
    extras: Record<string, string> = {},
    keep = false,
  ) =>
    request(`/api/env/keys/${name}/${index}`, {
      method: "POST",
      body: JSON.stringify({ value, keep, ...extras }),
    }),
  deleteKey: (name: string, index: number) =>
    request(`/api/env/keys/${name}/${index}`, { method: "DELETE" }),
  env: () => request("/api/env"),
  saveEnv: (updates: Record<string, string>, deletes: string[] = []) =>
    request("/api/env", { method: "POST", body: JSON.stringify({ updates, deletes }) }),
  secrets: () => request("/api/secrets"),
  saveSecrets: (secrets: Record<string, string>) =>
    request("/api/secrets", { method: "POST", body: JSON.stringify({ secrets }) }),
  instructions: () => request("/api/instructions"),
  saveInstructions: (text: string, target?: string) =>
    request("/api/instructions", { method: "POST", body: JSON.stringify({ text, target }) }),
  chats: (target = "", fresh = false) => {
    // `fresh` skips the server's warm cache. The background prefetch and the
    // first paint are happy with a few-seconds-old answer; a refresh the user
    // asked for is not.
    const q = new URLSearchParams();
    if (target) q.set("target", target);
    if (fresh) q.set("fresh", "1");
    const s = q.toString();
    return request(`/api/chats${s ? `?${s}` : ""}`);
  },
  reply: (user_id: any, target = "") =>
    request("/api/chats/reply", { method: "POST", body: JSON.stringify({ user_id, target }) }),
  replyAll: (target = "") =>
    request("/api/chats/reply-all", { method: "POST", body: JSON.stringify({ target }) }),
  // Stop a reply that is scheduled, being written or waiting out the cooldown.
  chatsCancel: (user_id: string, target = "") =>
    request("/api/chats/cancel", { method: "POST", body: JSON.stringify({ user_id, target }) }),
  /** React to a message as the account, or take the reaction back. A custom Discord emoji goes as "<:name:id>". */
  chatsReact: (user_id: string, mid: string, emoji: string, remove = false, target = "") =>
    request("/api/chats/react", { method: "POST", body: JSON.stringify({ user_id, mid, emoji, remove, target }) }),
  // A message typed in Chats, sent as the account; drops a reply the bot had lined up.
  /** `files` are pictures pasted into the composer: {name, data} with data base64, no prefix. */
  // `reply_to`: the id of the message it answers (Discord's reply; Snapchat's and TikTok's Reply on it).
  chatsSend: (user_id: string, text: string, target = "", files: { name: string; data: string }[] = [], reply_to = "") =>
    request("/api/chats/send", { method: "POST", body: JSON.stringify({ user_id, text, target, files, reply_to }) }),
  // The last messages of a conversation, both sides, oldest first.
  chatsHistory: (user_id: string, target = "", limit = 20) =>
    request("/api/chats/history", { method: "POST", body: JSON.stringify({ user_id, target, limit }) }),
  // The servers the account is in, their categories and the text channels it may read. Discord only.
  chatsServers: (target = "") =>
    request(`/api/chats/servers?target=${encodeURIComponent(target)}`) as Promise<{
      supported: boolean; target: string;
      guilds: { id: string; name: string; icon: string; members: number; channels: {
        id: string; name: string; category: string; topic: string; nsfw: boolean; voice: boolean;
        can_send: boolean; waiting: boolean }[] }[];
    }>,
  // Who is in each voice channel of one server, by channel id. Only looks; Discord only. `first`: the channels on
  // screen, whose names it looks for first.
  chatsVoice: (target: string, guild: string, first: string[] = []) =>
    request(`/api/chats/voice?target=${encodeURIComponent(target)}&guild=${encodeURIComponent(guild)}&first=${first.join(",")}`) as Promise<{
      supported: boolean; target: string;
      channels: Record<string, { count: number; people: { id: string; name: string; avatar: string; muted: boolean;
        deaf: boolean; live: boolean; video: boolean }[] }>;
    }>,
  // Someone's last message in full, pictures included.
  chatsMessage: (user_id: string, target = "") =>
    request("/api/chats/message", { method: "POST", body: JSON.stringify({ user_id, target }) }),
  // Searching one conversation in what is kept of it: instant, deleted messages included.
  chatsSearch: (user_id: string, target: string, q: object, sort = "newest", offset = 0, limit = 50) =>
    request("/api/chats/search", { method: "POST", body: JSON.stringify({ user_id, target, ...q, sort, offset, limit }) }),
  // Discord's own search over a DM: all of it, 25 at a time, by cursor (newest, oldest) or offset (relevant).
  chatsSearchDiscord: (user_id: string, target: string, q: object, sort = "newest", page: { cursor?: string; offset?: number } = {}) =>
    request("/api/chats/search-discord", { method: "POST", body: JSON.stringify({ user_id, target, ...q, sort, ...page }) }),
  // Every conversation of an account searched at once, for the search over the list.
  chatsSearchAll: (target: string, q: object, limit = 60) =>
    request("/api/chats/search-all", { method: "POST", body: JSON.stringify({ target, ...q, limit }) }),
  // What was shared in a conversation: "media", "files" or "links".
  chatsShared: (user_id: string, target: string, kind: "media" | "files" | "links") =>
    request("/api/chats/shared", { method: "POST", body: JSON.stringify({ user_id, target, kind }) }),
  // Part of a conversation near a message: "around" it, "older", "newer", or the "first" ones.
  chatsWindow: (user_id: string, target: string, dir: "around" | "older" | "newer" | "first", mid = "", limit = 50) =>
    request("/api/chats/around", { method: "POST", body: JSON.stringify({ user_id, target, dir, mid, limit }) }),
  // Everything kept of a conversation, as text to save.
  chatsExport: (user_id: string, target: string, name: string, me: string) =>
    request("/api/chats/export", { method: "POST", body: JSON.stringify({ user_id, target, name, me }) }),
  // Everyone this account ignores, and ignoring (or not) one person explicitly.
  chatsIgnored: (target = "") => request(`/api/chats/ignored${target ? `?target=${encodeURIComponent(target)}` : ""}`),
  chatsIgnoreSet: (user_id: string, ignored: boolean, target = "") =>
    request("/api/chats/ignore/set", { method: "POST", body: JSON.stringify({ user_id, ignored, target }) }),
  // Turn the bot off (or back on) for one person.
  chatsIgnore: (user_id: string, target = "") =>
    request("/api/chats/ignore", { method: "POST", body: JSON.stringify({ user_id, target }) }),
  // Conversations already dealt with, read from the message log.
  // `target` gives one account's (a Snapchat account's are its own chats); without it, every Discord account's.
  chatArchive: (limit = 40, target = "") =>
    request(`/api/chats/archive?limit=${limit}${target ? `&target=${encodeURIComponent(target)}` : ""}`),
  // Friend requests, answered now rather than on the background timer.
  friends: (target = "") =>
    request(`/api/friends${target ? `?target=${encodeURIComponent(target)}` : ""}`),
  /** A friend request sent by username, from the Chats tab: Discord's by its API, Snapchat's through its own search.
   *  iMessage's is a conversation started with a phone number or an email, and `text` is its first message. */
  /** Take the Nitro gift in a message (Discord, DMs): the account redeems it, and says what became of it. */
  giftAccept: (code: string, target = "", mid = "", user_id = "") =>
    request("/api/gifts/accept", { method: "POST", body: JSON.stringify({ code, target, mid, user_id }) }),
  friendAdd: (username: string, target = "", text = "") =>
    request("/api/friends/add", { method: "POST", body: JSON.stringify({ username, target, ...(text ? { text } : {}) }) }),
  friendAction: (action: "accept" | "decline", user_id: string, target = "") =>
    request(`/api/friends/${action}`, {
      method: "POST",
      body: JSON.stringify({ user_id, target }),
    }),
  // What one persona remembers about people: each has its own (Default's when none is named).
  memory: (persona = "") => request(scoped("/api/memory", persona)),
  memoryUser: (uid: string, persona = "") => request(scoped(`/api/memory/${uid}`, persona)),
  /** What you and this person have been talking about. `force` rewrites it; `cached` only reads the stored one and never writes. */
  memorySummary: (uid: string, force = false, cached = false, persona = "") =>
    request(scoped(`/api/memory/${encodeURIComponent(uid)}/summary${force ? "?force=true" : cached ? "?cached=true" : ""}`, persona)),
  memoryPut: (uid: string, body: any, persona = "") =>
    request(scoped(`/api/memory/${uid}`, persona), { method: "PUT", body: JSON.stringify(body) }),
  memoryDelete: (uid: string, body: any, persona = "") =>
    request(scoped(`/api/memory/${uid}`, persona), { method: "DELETE", body: JSON.stringify(body) }),
  /** Two accounts that are one person: from then on each knows what the other was told. Not per persona - who
   *  someone is does not change with who is talking to them. */
  memoryLink: (user_id: string, other_id: string) =>
    request("/api/memory/link", { method: "POST", body: JSON.stringify({ user_id, other_id }) }) as
      Promise<{ ok: boolean; group: string[] }>,
  memoryUnlink: (user_id: string) =>
    request("/api/memory/unlink", { method: "POST", body: JSON.stringify({ user_id }) }),
  // ── A background and a typeface of your own ──────────────────────────────
  appearance: () => request("/api/appearance"),
  uploadAppearance: (kind: "background" | "font", file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request(`/api/appearance/${kind}`, { method: "POST", body: fd });
  },
  clearAppearance: (kind: "background" | "font") =>
    request(`/api/appearance/${kind}`, { method: "DELETE" }),

  // Every picture call names the persona whose pictures they are (its own folder and rows); "" is Default's.
  pictures: (persona = "") => request(scoped("/api/pictures", persona)),
  uploadPicture: (file: File, persona = "") => {
    const fd = new FormData();
    fd.append("file", file);
    return request(scoped("/api/pictures", persona), { method: "POST", body: fd });
  },
  setPictureDesc: (name: string, description: string, id = "", persona = "") =>
    request(scoped(`/api/pictures/${encodeURIComponent(name)}/desc`, persona), {
      method: "POST",
      body: JSON.stringify({ description, id }),
    }),
  // One request for the whole selection, not a loop: deleting renumbers every
  // remaining picture, so after the first call the names the page is holding
  // point at different files.
  // By each picture's id where there is one (media_routes.py _pic_id): its
  // name may have moved on since the list was read.
  deletePictures: (items: { name: string; id?: string }[], persona = "") =>
    request(scoped("/api/pictures/delete", persona), { method: "POST", body: JSON.stringify({ items, names: items.map((i) => i.name) }) }),
  deletePicture: (name: string, id = "", persona = "") =>
    request(scoped(`/api/pictures/${encodeURIComponent(name)}${id ? `?id=${encodeURIComponent(id)}` : ""}`, persona), { method: "DELETE" }),
  /** A picture's address: by its id, which never comes to mean another picture, where it has one. */
  pictureUrl: (name: string, id = "", persona = "") =>
    scoped(id ? `/api/pictures/id/${encodeURIComponent(id)}` : `/api/pictures/${encodeURIComponent(name)}`, persona),
  /** A small copy for a tile or a card, its shorter side about `w` (media_routes.py, thumb): a full photo decoded for
   *  a small tile made a scrolling grid of them stutter. A video's is its still. */
  pictureSmall: (p: { name: string; id?: string; video?: boolean }, w = 160, persona = "") =>
    p.id
      ? scoped(`/api/pictures/id/${encodeURIComponent(p.id)}/thumb?w=${w}`, persona)
      : scoped(`/api/pictures/${encodeURIComponent(p.name)}`, persona),
  /** What an <img> shows for one: the picture itself, or a video's still (media_routes.py, poster). */
  pictureThumb: (p: { name: string; id?: string; video?: boolean }, persona = "") =>
    p.video && p.id
      ? scoped(`/api/pictures/id/${encodeURIComponent(p.id)}/poster`, persona)
      : scoped(p.id ? `/api/pictures/id/${encodeURIComponent(p.id)}` : `/api/pictures/${encodeURIComponent(p.name)}`, persona),
  analysePicture: (name: string, id = "", persona = "") =>
    request(scoped(`/api/pictures/${encodeURIComponent(name)}/analyse${id ? `?id=${encodeURIComponent(id)}` : ""}`, persona), { method: "POST" }),
  // Progress of the background pass that describes a freshly imported batch.
  pictureStatus: (persona = "") => request(scoped("/api/pictures/status", persona)),
  describeMissing: (opts: { long?: boolean } = {}, persona = "") =>
    request(scoped("/api/pictures/describe-missing", persona), { method: "POST", body: JSON.stringify(opts) }),
  // Looks (app/utils/looks.py): the list, a picture with one on it, putting one on, and what the AI would add.
  pictureLooks: (persona = "") => request(scoped("/api/pictures/looks", persona)),
  lookPreviewUrl: (id: string, look: string, strength: number, w = 360, persona = "") =>
    scoped(`/api/pictures/id/${encodeURIComponent(id)}/preview?look=${encodeURIComponent(look)}&strength=${strength.toFixed(2)}&w=${w}`, persona),
  putLook: (items: { name: string; id?: string }[], look: string, strength: number, persona = "") =>
    request(scoped("/api/pictures/look", persona), { method: "POST", body: JSON.stringify({ items, look, strength }) }),
  autoLookAll: (persona = "") => request(scoped("/api/pictures/auto-look", persona), { method: "POST" }),
  /** A filter on a made-up picture, for when there is none of yours to show it on. */
  samplePreviewUrl: (look: string, strength: number, w = 360) =>
    `/api/pictures/sample-preview?look=${encodeURIComponent(look)}&strength=${strength.toFixed(2)}&w=${w}`,
  /** The filter the AI would pick for this picture, to preview: nothing is put on it. */
  aiLookFor: (name: string, id = "", persona = "") =>
    request(scoped("/api/pictures/ai-look", persona), { method: "POST", body: JSON.stringify({ name, id }) }),
  touchPreview: (name: string, id = "", kinds?: string[], all = false, persona = "") =>
    request(scoped("/api/pictures/touch-preview", persona), { method: "POST", body: JSON.stringify({ name, id, kinds, all }) }),
  leaderboard: (target = "", filter = "") =>
    request(`/api/stats/leaderboard${target || filter ? "?" : ""}${target ? `target=${encodeURIComponent(target)}` : ""}${target && filter ? "&" : ""}${filter ? `filter=${encodeURIComponent(filter)}` : ""}`),
  statsOverview: () => request("/api/stats/overview"),
  /** Everything behind one dashboard figure, for the last `days` days. */
  statsDetail: (days = 30) => request(`/api/stats/detail?days=${days}`),
  logs: (n = 200, source = "") => request(`/api/logs?n=${n}${source ? `&source=${encodeURIComponent(source)}` : ""}`),
  doctor: () => request("/api/system/doctor"),
  backupUrl: "/api/system/backup",
  // A full copy of the data folder, tokens included, to a folder you choose.
  exportAll: (folder = "") =>
    request("/api/system/export", { method: "POST", body: JSON.stringify({ folder }) }),
  importAll: (path: string) =>
    request("/api/system/import", { method: "POST", body: JSON.stringify({ path }) }),
  storage: () => request("/api/system/storage"),
  updateCheck: () => request("/api/system/update/check"),
  updateRun: () => request("/api/system/update/run", { method: "POST" }),
  ignoreUpdate: (version: string) =>
    request("/api/system/update/ignore", { method: "POST", body: JSON.stringify({ version }) }),
  // Running the brain on this machine instead of Groq.
  localStatus: () => request("/api/local/status"),
  localDetect: () => request("/api/local/detect"),
  // With the key being typed beside the address, when there is one; else the saved key.
  localProbe: (base_url: string, api_key?: string) =>
    request("/api/local/probe", { method: "POST", body: JSON.stringify({ base_url, api_key }) }),
  localHfSearch: (q: string, sort: string, kind = "", size = "", cursor = "") =>
    request(`/api/local/hf/search?${new URLSearchParams({ q, sort, kind, size, cursor })}`),
  localHfSizes: (repo: string, kind: string) =>
    request(`/api/local/hf/sizes?repo=${encodeURIComponent(repo)}&kind=${encodeURIComponent(kind)}`),
  localHfPictures: (authors: string[]) => request(`/api/local/hf/pictures?authors=${encodeURIComponent(authors.join(","))}`),
  localHfPicture: (author: string) => `/api/local/hf/picture?author=${encodeURIComponent(author)}`,
  localPull: (model: string, base_url?: string) =>
    request("/api/local/pull", { method: "POST", body: JSON.stringify({ model, base_url }) }),
  localPullStatus: () => request("/api/local/pull/status"),
  localPullCancel: () => request("/api/local/pull/cancel", { method: "POST" }),
  /** Out of the download queue before its turn. */
  localPullUnqueue: (model: string) =>
    request("/api/local/pull/unqueue", { method: "POST", body: JSON.stringify({ model }) }),
  /** The smaller model offered for one that does not fit this computer (app/utils/localfix.py). */
  localFixUseAlt: () => request("/api/local/fix/use-alt", { method: "POST" }),
  localDelete: (model: string, base_url = "") =>
    request("/api/local/delete", { method: "POST", body: JSON.stringify({ model, base_url }) }),
  // Models the computer does not have, out of every setting that names them (a warning's "Stop using it").
  localForget: (models: string[]) =>
    request("/api/local/forget", { method: "POST", body: JSON.stringify({ models }) }),
  // Stop Ollama and start it again the app's way, so a new context length applies.
  localRestart: () => request("/api/local/restart", { method: "POST" }),
  /** The folder the server keeps its models in, opened whether it has any yet or not. */
  localOpenFolder: (base_url?: string) =>
    request("/api/local/open-folder", { method: "POST", body: JSON.stringify({ base_url }) }),
  /** A model file sent to the models folder, and how far it has got. It can be tens of gigabytes: read off the disk as
   *  it goes, never held in memory. `abort` stops it (rejecting with status 0), and leaves nothing behind. */
  localImport: (file: File, onProgress: (done: number, total: number) => void) =>
    sendFile(`/api/local/import?name=${encodeURIComponent(file.name)}`, file, onProgress),
  localReveal: (model: string, base_url?: string) =>
    request("/api/local/reveal", { method: "POST", body: JSON.stringify({ model, base_url }) }),
  // What each model has done, counted from every answer; balances where a provider will say.
  modelsUsage: (days = 7) => request(`/api/models/usage?days=${days}`),
  modelsLeft: (refresh = false) => request(`/api/models/left${refresh ? "?refresh=1" : ""}`),
  // Start a server the app can start (or open its app) and wait until it answers (up to ~25s).
  localStart: (server = "", base_url = "") =>
    request("/api/local/start", { method: "POST", body: JSON.stringify({ server, base_url }) }),
  // The Models tab: providers, their keys, and which model does which job.
  // A persona's own model choices where it has any, everyone's otherwise ("" is everyone's).
  providers: (persona = "") => request(scoped("/api/providers", persona)),
  providerModels: (pid: string, refresh = false) =>
    request(`/api/providers/${pid}/models${refresh ? "?refresh=true" : ""}`),
  providerKey: (pid: string, key: string) =>
    request(`/api/providers/${pid}/key`, { method: "POST", body: JSON.stringify({ key }) }),
  providerTry: (pid: string, model: string) =>
    request(`/api/providers/${pid}/try`, { method: "POST", body: JSON.stringify({ model }) }),
  savePlan: (plan: any, persona = "") =>
    request(scoped("/api/models/plan", persona), { method: "POST", body: JSON.stringify(plan) }),
  snapStatus: () => request("/api/snapchat/status"),
  snapInstall: () => request("/api/snapchat/install", { method: "POST" }),
  // Minecraft: mindcraft-ce, installed on demand (app/platforms/minecraft/install.py).
  minecraftStatus: () => request("/api/minecraft/status"),
  minecraftInstall: () => request("/api/minecraft/install", { method: "POST" }),
  minecraftUninstall: () => request("/api/minecraft/uninstall", { method: "POST" }),
  // A running account's card: a goal to get done, leaving the world, joining it again, what it is doing, another
  // server to go to (text is its address), or its own server again.
  minecraftOp: (webId: string, op: "goal" | "leave" | "join" | "state" | "server" | "home", text = "") =>
    request(`/api/minecraft/${encodeURIComponent(webId)}/${op}`,
            { method: "POST", body: JSON.stringify(op === "goal" ? { text } : op === "server" ? { address: text } : {}) }),
  // Its live view: whether there is one to watch yet.
  minecraftView: (webId: string) => request(`/api/minecraft/${encodeURIComponent(webId)}/view/status`),
  /** What the panel draws over the picture: its chat, its hotbar, how it is doing, who is near it, and the rest of
   *  a player's screen. Served by the bot's own process on the viewer's own server (agent_hooks.mjs), so it comes
   *  down the same proxied path. The player list and the debug screen only when they are open. */
  minecraftHud: (webId: string, ask: { debug?: boolean; tab?: boolean } = {}) =>
    request(`/api/minecraft/${encodeURIComponent(webId)}/view/hud`
            + (ask.debug || ask.tab ? `?${ask.debug ? "debug=1" : ""}${ask.debug && ask.tab ? "&" : ""}${ask.tab ? "tab=1" : ""}` : ""),
    ) as Promise<McHud>,
  /** A line typed into its chat as it: words, or a /command. */
  minecraftSay: (webId: string, text: string) =>
    request(`/api/minecraft/${encodeURIComponent(webId)}/view/say`, { method: "POST", body: JSON.stringify({ text }) }) as
      Promise<{ ok: boolean; reason?: string }>,
  /** Playing it by hand from its view, or letting go: its AI is paused meanwhile. */
  minecraftDrive: (webId: string, on: boolean) =>
    request(`/api/minecraft/${encodeURIComponent(webId)}/view/drive`, { method: "POST", body: JSON.stringify({ on }) }) as
      Promise<{ ok: boolean; driving?: boolean; mind?: string; reason?: string }>,
  /** The keys held, where it looks, and the mouse buttons: all of it each time. */
  minecraftInput: (webId: string, state: McInput) =>
    request(`/api/minecraft/${encodeURIComponent(webId)}/view/input`, { method: "POST", body: JSON.stringify(state) }) as
      Promise<{ ok: boolean; driving?: boolean; reason?: string }>,
  /** One thing done: a hotbar slot, drop, swap hands, put something on, move something out of a chest, respawn. */
  minecraftAct: (webId: string, body: { do: "slot" | "drop" | "swap" | "equip" | "move" | "click" | "close" | "respawn";
                                        slot?: number; all?: boolean; own?: boolean; button?: 0 | 1; shift?: boolean }) =>
    request(`/api/minecraft/${encodeURIComponent(webId)}/view/act`, { method: "POST", body: JSON.stringify(body) }) as
      Promise<{ ok: boolean; driving?: boolean; reason?: string }>,
  // ViaProxy, for servers of any version (app/platforms/minecraft/viaproxy.py).
  viaProxyStatus: () => request("/api/minecraft/viaproxy/status"),
  viaProxyInstall: () => request("/api/minecraft/viaproxy/install", { method: "POST" }),
  viaProxyUninstall: () => request("/api/minecraft/viaproxy/uninstall", { method: "POST" }),
  sysInfo: () => request("/api/system/info"),
  restartApp: () => request("/api/system/restart", { method: "POST" }),
  network: () => request("/api/system/network"),
  ffmpegStatus: () => request("/api/system/ffmpeg"),
  ffmpegInstall: () => request("/api/system/ffmpeg/install", { method: "POST" }),
  opusStatus: () => request("/api/system/opus"),
  opusInstall: () => request("/api/system/opus/install", { method: "POST" }),
  /** `persona` opens that persona's own pictures folder (target "pictures"). */
  openFolder: (target: string, persona = "") =>
    request("/api/system/open", { method: "POST", body: JSON.stringify(persona ? { target, persona } : { target }) }),
  // This device, and what does not work on it (lib/device.ts).
  device: () => request("/api/system/device"),
  // The phone apps only: a web link, opened in the phone's browser.
  openUrl: (url: string) =>
    request("/api/system/open-url", { method: "POST", body: JSON.stringify({ url }) }),
};
