/**
 * Which socials are switched on (Settings, App, What runs). One that is off is shown nowhere: not its tab in
 * Settings, not its accounts, not a way to add one, not its people, its numbers or its lines in the log. Everything
 * is on until someone turns it off.
 *
 * The server already leaves a switched-off social's accounts out of what it sends (app/utils/socials.py). This is
 * for what the panel lists by itself: menus of platforms, filters, people and log lines it was sent anyway.
 *
 * The last answer is kept in this browser, so a social that is off does not flash in for a moment as the panel
 * opens, before the server has been asked.
 */
import { get, writable } from "svelte/store";
import { api } from "./api";
import { PLATFORMS, PLATFORM_IDS, platformOfUser, type PlatformId } from "./platforms";

export type SocialsOn = Record<PlatformId, boolean>;

export const SOCIALS = Object.keys(PLATFORMS) as PlatformId[];
const KEY = "socials.on";

function everyOn(): SocialsOn {
  return Object.fromEntries(SOCIALS.map((id) => [id, true])) as SocialsOn;
}

function remembered(): SocialsOn {
  const on = everyOn();
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "{}");
    for (const id of SOCIALS) if (saved?.[id] === false) on[id] = false;
  } catch {
    /* a private window, or nothing kept yet */
  }
  return on;
}

export const socialsOn = writable<SocialsOn>(remembered());

function keep(on: SocialsOn) {
  const now = get(socialsOn);
  if (SOCIALS.every((id) => now[id] === on[id])) return;
  socialsOn.set(on);
  try {
    localStorage.setItem(KEY, JSON.stringify(on));
  } catch {
    /* a private window */
  }
}

/** Asked again: as the panel opens, with the health check, and after a switch is saved. */
export async function refreshSocials(): Promise<void> {
  try {
    const r = await api.socials();
    if (!r || typeof r.on !== "object" || !r.on) return;
    const next = everyOn();
    for (const id of SOCIALS) next[id] = r.on[id] !== false;
    keep(next);
  } catch {
    /* the last known answer stays */
  }
}

/** Whether a platform, by its id ("snapchat"), is on. Anything that is not a social (the control bot) always is. */
export function platformOn(on: SocialsOn, platform: string | null | undefined): boolean {
  const p = String(platform ?? "") as PlatformId;
  return !(p in on) || on[p] !== false;
}

/**
 * Whether what an id names belongs on screen: an account ("tiktok_2"), a log line's source (the same, or a social's
 * own setup, "snapchat-install"). A bare "telegram" is the bot that controls the app, not a social, and always is.
 */
const SOURCE = new RegExp(`^(${PLATFORM_IDS.join("|")})(?:_\\d+|-install)$`);

export function sourceOn(on: SocialsOn, source: string | null | undefined): boolean {
  const m = String(source ?? "").match(SOURCE);
  return !m || on[m[1] as PlatformId] !== false;
}

/** Whether a person, by their id, is someone on a social that is on. */
export function personOn(on: SocialsOn, uid: string | number | null | undefined): boolean {
  return on[platformOfUser(uid).id] !== false;
}
