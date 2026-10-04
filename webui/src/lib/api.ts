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
  "/api/system/update",
  "/api/system/ffmpeg/install",
  "/api/friends/",
  "/api/local/",
  // A provider's model list is a round trip to that provider.
  "/api/providers/",
];

function watched(path: string, method: string): boolean {
  if (method !== "GET") return false;
  return !SLOW_EXEMPT.some((p) => path.startsWith(p));
}

async function request(path: string, options: RequestInit = {}): Promise<any> {
  const method = options.method || "GET";
  const headers: Record<string, string> = { ...(options.headers as any) };
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

/** A path asked as one persona (app/utils/personas.py). Left as it is for "", which the server reads as Default. */
function scoped(path: string, persona = ""): string {
  if (!persona) return path;
  return `${path}${path.includes("?") ? "&" : "?"}persona=${encodeURIComponent(persona)}`;
}

export const api = {
  request,
  status: () => request("/api/status"),
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
  createPersona: (body: { name: string; color?: string; copy_from?: string; copy_memory?: boolean }) =>
    request("/api/personas", { method: "POST", body: JSON.stringify(body) }),
  updatePersona: (pid: string, body: { name?: string; color?: string }) =>
    request(`/api/personas/${encodeURIComponent(pid)}`, { method: "PATCH", body: JSON.stringify(body) }),
  deletePersona: (pid: string) => request(`/api/personas/${encodeURIComponent(pid)}`, { method: "DELETE" }),
  assignPersona: (pid: string, account: string) =>
    request(`/api/personas/${encodeURIComponent(pid)}/assign`, { method: "POST", body: JSON.stringify({ account }) }),
  personaText: (pid: string) => request(`/api/personas/${encodeURIComponent(pid)}/text`),
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
  chatsSend: (user_id: string, text: string, target = "", files: { name: string; data: string }[] = []) =>
    request("/api/chats/send", { method: "POST", body: JSON.stringify({ user_id, text, target, files }) }),
  // The last messages of a conversation, both sides, oldest first.
  chatsHistory: (user_id: string, target = "", limit = 20) =>
    request("/api/chats/history", { method: "POST", body: JSON.stringify({ user_id, target, limit }) }),
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
  localReveal: (model: string, base_url?: string) =>
    request("/api/local/reveal", { method: "POST", body: JSON.stringify({ model, base_url }) }),
  // What each model has done, counted from every answer; balances where a provider will say.
  modelsUsage: (days = 7) => request(`/api/models/usage?days=${days}`),
  modelsBalances: (refresh = false) => request(`/api/models/balances${refresh ? "?refresh=1" : ""}`),
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
  sysInfo: () => request("/api/system/info"),
  restartApp: () => request("/api/system/restart", { method: "POST" }),
  network: () => request("/api/system/network"),
  ffmpegStatus: () => request("/api/system/ffmpeg"),
  ffmpegInstall: () => request("/api/system/ffmpeg/install", { method: "POST" }),
  /** `persona` opens that persona's own pictures folder (target "pictures"). */
  openFolder: (target: string, persona = "") =>
    request("/api/system/open", { method: "POST", body: JSON.stringify(persona ? { target, persona } : { target }) }),
  // This device, and what does not work on it (lib/device.ts).
  device: () => request("/api/system/device"),
  // The phone apps only: a web link, opened in the phone's browser.
  openUrl: (url: string) =>
    request("/api/system/open-url", { method: "POST", body: JSON.stringify({ url }) }),
};
