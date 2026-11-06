/**
 * Community profiles' data, kept between visits like every page's (resource.ts), and which view of the Profiles
 * page is up: yours or the community's, remembered for this session.
 */
import { writable } from "svelte/store";
import { api } from "../api";
import { resource } from "../resource";
import { EMPTY_HOME, type CommunityHome } from "./logic";

export const communityRes = resource<CommunityHome>("community", () => api.community(), EMPTY_HOME);

export type CommunityStats = {
  state?: string;
  days: string[];
  total: { downloads?: number; week?: number; daily?: number[] };
  profiles: Record<string, { downloads: number; week: number; daily: number[]; versions: Record<string, number> }>;
};
export const communityStatsRes = resource<CommunityStats>("communityStats", () => api.communityStats(),
                                                          { days: [], total: {}, profiles: {} });

export type MineRequest = {
  number: number; slug: string; action: string; pid: string; sent: number; state: string; version?: number;
  reasons?: string[];
};
export type MineProfile = { slug: string; pid: string; version: number; live: boolean; downloads: number; week: number;
                            changed: boolean; app?: string };
export type Mine = { requests: MineRequest[]; profiles: MineProfile[]; author: string; signed_in: boolean };
export const communityMineRes = resource<Mine>("communityMine", () => api.communityMine(),
                                               { requests: [], profiles: [], author: "", signed_in: false });

function remembered(): "yours" | "community" {
  try {
    return sessionStorage.getItem("profiles.view") === "community" ? "community" : "yours";
  } catch {
    return "yours";
  }
}

/** Yours or the community's, on the Profiles page. */
export const profilesView = writable<"yours" | "community">(remembered());
profilesView.subscribe((v) => {
  try {
    sessionStorage.setItem("profiles.view", v);
  } catch {
    /* a private window: just not remembered */
  }
});

/** A profile to open in Inspect, from anywhere on the page (a card's Update badge). */
export const inspectSlug = writable("");
