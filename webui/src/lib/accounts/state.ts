/**
 * The Accounts page's data, kept between visits.
 *
 * The page used to fetch everything on mount into component state, so it
 * opened on a grey block every time, and the presence dots came back grey
 * until the first round of live detail landed five seconds later. These live
 * outside the component: the lists are resources the startup warm-up fills
 * (warm.ts), and the live detail is a store the page keeps topped up.
 */
import { writable } from "svelte/store";
import { api } from "../api";
import { track } from "../busy";
import { resource } from "../resource";
import { toast } from "../stores";
import type { Details, Runtime, Slot } from "./condition";

export type Activity = {
  today: number;
  week: number;
  people_week: number;
  series: number[];
  top: { id: string; name: string; count: number; avatar?: string }[];
  last: { id: string; name: string; ts: number } | null;
};

export type ActivityReply = {
  days: number;
  /** This computer's calendar day for each entry of every series, oldest first. */
  dates: string[];
  accounts: Record<string, Activity>;
};

/** How far back each card's chart goes: a week, today last. */
export const ACTIVITY_DAYS = 7;

export const accountsRes = resource("accounts", () => api.accounts(), { accounts: [] as Runtime[] });
export const slotsRes = resource("accountSlots", () => api.slots(), { slots: [] as Slot[] });
export const activityRes = resource(
  "accountActivity",
  () => api.accountActivity(ACTIVITY_DAYS),
  { days: ACTIVITY_DAYS, dates: [], accounts: {} } as ActivityReply,
);

/** Live detail per account id, as each worker last reported it. */
export const accountDetails = writable<Record<string, Details>>({});

/** Ask one worker how it is, and keep the answer. */
export async function refreshDetails(id: string): Promise<Details | null> {
  try {
    const d = (await api.accountDetails(id)) as Details;
    accountDetails.update((all) => ({ ...all, [id]: d }));
    return d;
  } catch {
    return null;           // keep whatever was there; a missed poll is not news
  }
}

const moodsPromises = new Map<string, Promise<string[]>>();

/**
 * The moods the bot can be put in, as configured.
 *
 * The page had its own hard-coded six, so a mood added in Settings could not be
 * picked here and a removed one still could - and the worker would then be set
 * to a mood it has no instruction for.
 *
 * Each persona has its own moods (app/utils/personas.py): an account's are its
 * persona's. With none named, everyone's.
 */
export function loadMoods(force = false, persona = ""): Promise<string[]> {
  let promise = moodsPromises.get(persona);
  if (!promise || force) {
    promise = api
      .config(persona)
      .then((cfg: any) => Object.keys(cfg?.bot?.mood?.moods ?? {}))
      .catch(() => {
        moodsPromises.delete(persona);   // try again next time rather than caching a failure
        return [];
      });
    moodsPromises.set(persona, promise);
  }
  return promise;
}

const DONE: Record<string, string> = { start: "Starting", stop: "Stopped", restart: "Restarting" };

/**
 * Start, stop or restart an account from anywhere, saying who in the toast.
 * The Dashboard used to toast "stop discord_1", its internal id.
 */
export async function runAccountAction(id: string, act: "start" | "stop" | "restart",
                                       who: string, route = "accounts") {
  try {
    const res: any = await track(route, api.accountAction(id, act), `${DONE[act]} ${who}`);
    if (res && res.ok === false) toast(res.reason || `Could not ${act} ${who}`, "err");
    else toast(`${DONE[act]} ${who}`, "ok");
  } catch (e: any) {
    toast(e?.message || `Could not ${act} ${who}`, "err");
  }
  setTimeout(() => accountsRes.refresh({ force: true, quiet: true }), 700);
}
