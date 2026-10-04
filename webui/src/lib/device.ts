/**
 * The device the app is running on, and what does not work on it.
 *
 * Asked once at startup (app/utils/compat.py answers, from probes of this copy
 * of the app). The page says nothing about what works; NotHere puts a short
 * warning where something that does not would be used.
 */
import { derived, get, writable } from "svelte/store";
import { api } from "./api";

export type Fix = { command?: string; route?: string; label?: string };
export type Missing = { label: string; why: string; tag: string; fix?: Fix };
export type Device = {
  name: string;
  label: string;
  family: string;
  phone: boolean;
  install: string;
  single_process: boolean;
  asset: string | null;
  update: string;
  pretend: boolean;
};
export type DeviceInfo = { device: Device; missing: Record<string, Missing> };

export const deviceInfo = writable<DeviceInfo | null>(null);

export async function loadDevice(): Promise<void> {
  try {
    deviceInfo.set((await api.device()) as DeviceInfo);
  } catch {
    /* an older server, or offline for a moment: nothing to warn about */
  }
}

/** What does not work here about `feature`, or null when it works. */
export function missing(feature: string): Missing | null {
  return get(deviceInfo)?.missing?.[feature] ?? null;
}

/** The same, as a store, for markup that should follow it. */
export const notHere = derived(deviceInfo, ($d) => (feature: string): Missing | null =>
  $d?.missing?.[feature] ?? null);

/** In the phone app: the panel is the app's own web view there. */
export function inPhoneApp(): boolean {
  const d = get(deviceInfo)?.device;
  return !!d && d.phone && d.single_process;
}
