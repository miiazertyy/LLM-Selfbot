/**
 * What each model has done, and the moment it is used.
 *
 * The counts come from /api/models/usage, which the runners fill in from every
 * answer they get (app/utils/usage.py). Each answer is also announced live on
 * the shared socket as a "model" event: the count moves at once, the model's
 * row in Models blinks, and a quiet reload a moment later picks up what the
 * answer said about the limits, which only the server can add up across keys.
 */
import { get, writable } from "svelte/store";
import { api } from "./api";
import { subscribeEvents } from "./logsocket";

export type Limit = {
  what: string;
  window: string;
  limit: number;
  remaining: number;
  keys: number;
  reset_at: number | null;
};
export type Today = { requests: number; errors: number; limited: number; in: number; out: number; reasoning: number; ms: number };
export type ModelUsage = {
  provider: string;
  model: string;
  last_at: number;
  jobs: Record<string, number>;
  today: Today;
  days: { day: string; requests: number; tokens: number }[];
  limits: Limit[];
};
export type UsageEvent = {
  provider: string;
  model: string;
  job: string;
  ok: boolean;
  limited: boolean;
  in: number;
  out: number;
  ms: number;
  at: number;
};

type State = { models: ModelUsage[]; today: string; days: string[]; loaded: boolean };

export const usage = writable<State>({ models: [], today: "", days: [], loaded: false });

/** provider|model of the models used in the last couple of seconds, with when: the blink. */
export const lastUse = writable<Record<string, number>>({});

/**
 * Requests to a model under way right now, by request: a model at work, for as
 * long as it is (the echo round the local server's logo in Settings). From the
 * runners' "work" events (app/utils/usage.py), started and ended. One that never
 * says it ended (its connection broke) is let go of after two minutes.
 */
export type Work = { provider: string; model: string; job: string; at: number };
export const working = writable<Record<string, Work>>({});
const WORK_LIMIT_MS = 120_000;

function pruneWork() {
  working.update((w) => {
    const now = Date.now();
    const stale = Object.entries(w).filter(([, v]) => now - v.at > WORK_LIMIT_MS);
    if (!stale.length) return w;
    const next = { ...w };
    for (const [k] of stale) delete next[k];
    return next;
  });
}

/** Whether anything is at work on a provider right now ("local": the server on this computer). */
export const busyOn = (w: Record<string, Work>, provider: string) => Object.values(w).some((v) => v.provider === provider);

export const usageKey = (provider: string, model: string) => `${provider}|${model}`;

export function usageFor(state: State, provider: string, model: string): ModelUsage | undefined {
  return state.models.find((m) => m.provider === provider && m.model === model);
}

export async function loadUsage(): Promise<void> {
  const d = await api.modelsUsage(7);
  usage.set({ models: d.models ?? [], today: d.today ?? "", days: d.days ?? [], loaded: true });
}

function emptyDays(state: State) {
  return state.days.map((day) => ({ day, requests: 0, tokens: 0 }));
}

/** One answer, counted where it lands, so nothing waits on a reload to move. */
function apply(state: State, e: UsageEvent): State {
  const models = state.models.slice();
  let i = models.findIndex((m) => m.provider === e.provider && m.model === e.model);
  if (i < 0) {
    models.push({
      provider: e.provider,
      model: e.model,
      last_at: 0,
      jobs: {},
      today: { requests: 0, errors: 0, limited: 0, in: 0, out: 0, reasoning: 0, ms: 0 },
      days: emptyDays(state),
      limits: [],
    });
    i = models.length - 1;
  }
  const m = { ...models[i], today: { ...models[i].today }, jobs: { ...models[i].jobs }, days: models[i].days.slice() };
  m.last_at = Math.max(m.last_at, e.at || Date.now() / 1000);
  if (e.ok) {
    m.today.requests += 1;
    m.today.in += e.in || 0;
    m.today.out += e.out || 0;
    m.today.ms += e.ms || 0;
    m.jobs[e.job || "other"] = (m.jobs[e.job || "other"] ?? 0) + 1;
    const last = m.days.length - 1;
    if (last >= 0) {
      m.days[last] = { ...m.days[last], requests: m.days[last].requests + 1,
                       tokens: m.days[last].tokens + (e.in || 0) + (e.out || 0) };
    }
  } else if (e.limited) {
    m.today.limited += 1;
  } else {
    m.today.errors += 1;
  }
  models[i] = m;
  return { ...state, models };
}

let started = false;
let reload: ReturnType<typeof setTimeout> | null = null;

/** Once for the whole app: the socket is shared, and so are the counts. */
export function startUsageLive(): void {
  if (started) return;
  started = true;
  subscribeEvents("work", (evt) => {
    // The socket came back: what was under way has ended, or will say so again.
    if (!evt) return working.set({});
    const e = evt as { rid?: string; state?: string; provider?: string; model?: string; job?: string };
    if (!e.rid) return;
    const key = `${(evt as any).target ?? ""}:${e.rid}`;
    working.update((w) => {
      const next = { ...w };
      if (e.state === "start") next[key] = { provider: e.provider ?? "", model: e.model ?? "", job: e.job ?? "", at: Date.now() };
      else delete next[key];
      return next;
    });
  });
  setInterval(pruneWork, 15_000);
  subscribeEvents("model", (evt) => {
    if (!evt) {
      // The socket came back: whatever happened while it was away is in the database.
      loadUsage().catch(() => {});
      return;
    }
    const e = evt as UsageEvent;
    const k = usageKey(e.provider, e.model);
    const now = Date.now();
    lastUse.update((m) => ({ ...m, [k]: now }));
    setTimeout(() => {
      lastUse.update((m) => {
        if (m[k] !== now) return m;
        const next = { ...m };
        delete next[k];
        return next;
      });
    }, 2000);
    if (get(usage).loaded) usage.update((s) => apply(s, e));
    if (reload) clearTimeout(reload);
    reload = setTimeout(() => loadUsage().catch(() => {}), 2500);
  });
}
