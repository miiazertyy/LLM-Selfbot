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


export const api = {
  request,
  status: () => request("/api/status"),
  accounts: () => request("/api/accounts"),
  accountAction: (id: string, action: string) =>
    request(`/api/accounts/${id}/${action}`, { method: "POST" }),
  accountDetails: (id: string) => request(`/api/accounts/${id}/details`),
  accountMood: (id: string, mood: string) =>
    request(`/api/accounts/${id}/mood`, { method: "POST", body: JSON.stringify({ mood }) }),
  serviceAction: (name: string, action: string) =>
    request(`/api/services/${name}/${action}`, { method: "POST" }),
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
  config: () => request("/api/config"),
  saveConfig: (config: any) =>
    request("/api/config", { method: "POST", body: JSON.stringify({ config }) }),
  configField: (key: string, value: any, target?: string) =>
    request("/api/config/field", { method: "POST", body: JSON.stringify({ key, value, target }) }),
  schema: () => request("/api/config/schema"),
  // What Groq actually offers right now, so model names are picked not typed.
  models: (refresh = false) => request(`/api/models${refresh ? "?refresh=true" : ""}`),
  // What is stopping the bot working, tagged by the page that fixes it.
  health: () => request("/api/health"),
  // The uncached answer. /api/health serves the last snapshot and refreshes
  // behind it, which is right for a background poll and wrong straight after
  // a save, when the whole point is to see whether the change fixed anything.
  healthNow: () => request("/api/health/blocking"),
  // Profile card behind a clicked name, assembled from local data only.
  person: (uid: string) => request(`/api/people/${uid}`),
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
  // Conversations already dealt with, read from the message log.
  chatArchive: (limit = 40) => request(`/api/chats/archive?limit=${limit}`),
  // Friend requests, answered now rather than on the background timer.
  friends: (target = "") =>
    request(`/api/friends${target ? `?target=${encodeURIComponent(target)}` : ""}`),
  friendAction: (action: "accept" | "decline", user_id: string, target = "") =>
    request(`/api/friends/${action}`, {
      method: "POST",
      body: JSON.stringify({ user_id, target }),
    }),
  memory: () => request("/api/memory"),
  memoryUser: (uid: string) => request(`/api/memory/${uid}`),
  memoryPut: (uid: string, body: any) =>
    request(`/api/memory/${uid}`, { method: "PUT", body: JSON.stringify(body) }),
  memoryDelete: (uid: string, body: any) =>
    request(`/api/memory/${uid}`, { method: "DELETE", body: JSON.stringify(body) }),
  // ── A background and a typeface of your own ──────────────────────────────
  appearance: () => request("/api/appearance"),
  uploadAppearance: (kind: "background" | "font", file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request(`/api/appearance/${kind}`, { method: "POST", body: fd });
  },
  clearAppearance: (kind: "background" | "font") =>
    request(`/api/appearance/${kind}`, { method: "DELETE" }),

  pictures: () => request("/api/pictures"),
  uploadPicture: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("/api/pictures", { method: "POST", body: fd });
  },
  setPictureDesc: (name: string, description: string) =>
    request(`/api/pictures/${encodeURIComponent(name)}/desc`, {
      method: "POST",
      body: JSON.stringify({ description }),
    }),
  // One request for the whole selection, not a loop: deleting renumbers every
  // remaining picture, so after the first call the names the page is holding
  // point at different files.
  deletePictures: (names: string[]) =>
    request("/api/pictures/delete", { method: "POST", body: JSON.stringify({ names }) }),
  deletePicture: (name: string) =>
    request(`/api/pictures/${encodeURIComponent(name)}`, { method: "DELETE" }),
  pictureUrl: (name: string) => `/api/pictures/${encodeURIComponent(name)}`,
  analysePicture: (name: string) =>
    request(`/api/pictures/${encodeURIComponent(name)}/analyse`, { method: "POST" }),
  // Progress of the background pass that describes a freshly imported batch.
  pictureStatus: () => request("/api/pictures/status"),
  describeMissing: () => request("/api/pictures/describe-missing", { method: "POST" }),
  leaderboard: (target = "", filter = "") =>
    request(`/api/stats/leaderboard${target || filter ? "?" : ""}${target ? `target=${encodeURIComponent(target)}` : ""}${target && filter ? "&" : ""}${filter ? `filter=${encodeURIComponent(filter)}` : ""}`),
  statsOverview: () => request("/api/stats/overview"),
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
  localProbe: (base_url: string) =>
    request("/api/local/probe", { method: "POST", body: JSON.stringify({ base_url }) }),
  localPull: (model: string, base_url?: string) =>
    request("/api/local/pull", { method: "POST", body: JSON.stringify({ model, base_url }) }),
  localPullStatus: () => request("/api/local/pull/status"),
  snapStatus: () => request("/api/snapchat/status"),
  snapInstall: () => request("/api/snapchat/install", { method: "POST" }),
  sysInfo: () => request("/api/system/info"),
  restartApp: () => request("/api/system/restart", { method: "POST" }),
  network: () => request("/api/system/network"),
  ffmpegStatus: () => request("/api/system/ffmpeg"),
  ffmpegInstall: () => request("/api/system/ffmpeg/install", { method: "POST" }),
  openFolder: (target: string) =>
    request("/api/system/open", { method: "POST", body: JSON.stringify({ target }) }),
};
