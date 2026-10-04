/**
 * The Models tab's shared state: providers, the plan, and model lists.
 *
 * Three panels read it (Models, Providers, This computer) and the model picker
 * is opened from two of them, so it lives here rather than in any one of them.
 * See app/utils/providers.py for what a plan is.
 */
import { get, writable } from "svelte/store";
import { api } from "./api";

export type Job = "chat" | "vision" | "stt" | "tts";
export type Provider = {
  id: string;
  name: string;
  site: string;
  blurb: string;
  jobs: Job[];
  env: string;
  multi: boolean;
  keys: number;
  ready: boolean;
  base_url: string;
  stored: boolean;
  /** "free" (a free tier or local), "some" (some free models) or "paid". */
  cost: "free" | "some" | "paid";
  cost_note: string;
};

export const COST_LABEL: Record<string, string> = { free: "Free", some: "Some free", paid: "Paid" };
export type Entry = { provider: string; model: string; voice?: string };
export type Plan = {
  replies: Entry[];
  small: Entry;
  vision: Entry;
  stt: Entry;
  tts: Entry;
  /** Every model each job tries, in order (the entries above are each one's first). */
  chains?: Record<string, Entry[]>;
};
export type ModelInfo = { id: string; capabilities: string[] };

export const providerList = writable<Provider[]>([]);
export const savedPlan = writable<Plan | null>(null);
export const maxReplyTokens = writable<number>(320);
/** What each job does when nothing is picked for it: its Groq model. */
export const jobDefaults = writable<Record<string, Entry>>({});
export const providersLoaded = writable(false);
/**
 * Whose model choices the plan is: "" for everyone's, else one persona's own (Settings, while it is set to one).
 * Every load follows it, so the panels on one page never show two different plans.
 */
export const planPersona = writable("");

export async function loadProviders(): Promise<void> {
  const persona = get(planPersona);
  const d = await api.providers(persona);
  // Asked for another persona's meanwhile: that answer is the one to keep.
  if (get(planPersona) !== persona) return;
  providerList.set(d.providers || []);
  jobDefaults.set(d.defaults || {});
  savedPlan.set(d.plan || null);
  maxReplyTokens.set(d.max_reply_tokens ?? 320);
  providersLoaded.set(true);
}

export function providerById(id: string): Provider | undefined {
  return get(providerList).find((p) => p.id === id);
}

/**
 * Each provider's own colour, for its tile. Identity only: every one also
 * carries its name, so nothing is told apart by colour alone.
 */
export const TINT: Record<string, string> = {
  groq: "#f55036",
  openai: "#10a37f",
  anthropic: "#d97757",
  gemini: "#4c8df6",
  openrouter: "#6566f1",
  mistral: "#fa520f",
  deepseek: "#4d6bfe",
  xai: "#a3a3b5",
  together: "#0f6fff",
  cerebras: "#f15a29",
  local: "#4ecdc4",
  llamacpp: "#9a9ab0",
  vllm: "#30a2ff",
  // The servers on this computer, under This computer.
  jan: "#f5b83d",
  gpt4all: "#4caf50",
  koboldcpp: "#5fbf6a",
  localai: "#2bb6d4",
  textgen: "#f08a3c",
  tabbyapi: "#b58ae8",
  docker: "#2496ed",
  sglang: "#e0674a",
};

/** Two letters for the tile. This computer gets an icon instead. */
export const MONOGRAM: Record<string, string> = {
  groq: "Gq", openai: "OA", anthropic: "An", gemini: "Ge", openrouter: "OR",
  mistral: "Mi", deepseek: "DS", xai: "xA", together: "To", cerebras: "Ce",
  llamacpp: "Ll", vllm: "vL",
  jan: "Ja", gpt4all: "G4", koboldcpp: "Kc", localai: "LA", textgen: "TG", tabbyapi: "Tb",
  docker: "Dk", sglang: "SG",
};

export const JOB_NAMES: Record<Exclude<keyof Plan, "replies" | "chains">, { title: string; hint: string; needs: Job; icon: string }> = {
  small: { title: "Background work", hint: "Remembering facts, spotting the language, summaries", needs: "chat", icon: "memory" },
  vision: { title: "Reading pictures", hint: "Describes images and stickers people send", needs: "vision", icon: "pictures" },
  stt: { title: "Hearing voice messages", hint: "Turns a voice note into text", needs: "stt", icon: "mic" },
  tts: { title: "Speaking", hint: "Voice messages the bot sends back", needs: "tts", icon: "volume" },
};

/** Model lists, per provider, fetched once and shared by every picker. */
const lists = writable<Record<string, { models: ModelInfo[]; error: string; loading: boolean; at: number }>>({});
export const modelLists = { subscribe: lists.subscribe };

export async function loadModels(pid: string, refresh = false): Promise<void> {
  const cur = get(lists)[pid];
  if (cur?.loading) return;
  // This computer's list changes under the app's own hands (a model downloaded, one removed): asked again soon.
  const fresh = pid === "local" ? 15_000 : 10 * 60 * 1000;
  if (cur && !refresh && Date.now() - cur.at < fresh && cur.models.length) return;
  lists.update((l) => ({ ...l, [pid]: { models: cur?.models ?? [], error: "", loading: true, at: cur?.at ?? 0 } }));
  try {
    const d = await api.providerModels(pid, refresh);
    lists.update((l) => ({ ...l, [pid]: { models: d.models || [], error: d.error || "", loading: false, at: Date.now() } }));
  } catch (e: any) {
    lists.update((l) => ({ ...l, [pid]: { models: cur?.models ?? [], error: e?.message || "Could not load", loading: false, at: Date.now() } }));
  }
}

export const same = (a?: Entry | null, b?: Entry | null) =>
  (a?.provider || "") === (b?.provider || "") && (a?.model || "") === (b?.model || "")
  && (a?.voice || "") === (b?.voice || "");

/** "gpt-oss-120b" from "openai/gpt-oss-120b": the part people recognise. */
export function shortModel(id: string): string {
  const tail = id.includes("/") ? id.slice(id.lastIndexOf("/") + 1) : id;
  return tail || id;
}
