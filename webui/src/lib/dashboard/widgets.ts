/**
 * What can go on the Dashboard, and how each one can be set up.
 *
 * The page used to be five fixed sections that could only be reordered. It is
 * now a list of widget placements (stores.dashLayout): add any of these, more
 * than once where that makes sense, remove them, fold them up, make them half
 * or full width, and change what each one shows.
 *
 * A widget's options are plain choices rather than free input, so every value a
 * widget can receive is one it was written to handle.
 */
import { get } from "svelte/store";
import { dashLayout, dashOrder, type WidgetInstance } from "../stores";

export type OptionDef = {
  key: string;
  label: string;
  choices: { value: string | number; label: string }[];
  default: string | number;
};

export type WidgetDef = {
  type: string;
  title: string;
  blurb: string;
  icon: string;
  size: "half" | "full";
  /** Several copies make sense - the same chart over different windows. */
  multiple?: boolean;
  options?: OptionDef[];
};

const WINDOW: OptionDef = {
  key: "days",
  label: "Covers",
  choices: [
    { value: 7, label: "7 days" },
    { value: 30, label: "30 days" },
    { value: 90, label: "90 days" },
  ],
  default: 30,
};

export const WIDGETS: Record<string, WidgetDef> = {
  figures: {
    type: "figures", title: "Headline figures", icon: "stats", size: "full",
    blurb: "Accounts up, replies today and this week, people talked to. Click one for the detail.",
  },
  activity: {
    type: "activity", title: "Replies over time", icon: "stats", size: "full", multiple: true,
    blurb: "How many replies went out each day, and the last 24 hours hour by hour.",
    options: [{
      key: "days", label: "Covers",
      choices: [{ value: 7, label: "7 days" }, { value: 14, label: "14 days" },
                { value: 30, label: "30 days" }, { value: 90, label: "90 days" }],
      default: 14,
    }],
  },
  accounts: {
    type: "accounts", title: "Accounts", icon: "accounts", size: "full",
    blurb: "Every account, whether it is up, and start, stop or restart it.",
    options: [{
      key: "view", label: "Show as",
      choices: [{ value: "cards", label: "Cards" }, { value: "list", label: "Compact list" }],
      default: "cards",
    }],
  },
  people: {
    type: "people", title: "Most active people", icon: "memory", size: "half", multiple: true,
    blurb: "Who the bot talks to most, ranked.",
    options: [
      { ...WINDOW, default: 7 },
      { key: "count", label: "Show", choices: [{ value: 5, label: "Top 5" }, { value: 10, label: "Top 10" }],
        default: 5 },
    ],
  },
  log: {
    type: "log", title: "Live log", icon: "logs", size: "half", multiple: true,
    blurb: "What the bot is doing, as it does it.",
    options: [
      { key: "filter", label: "Lines",
        choices: [{ value: "all", label: "Everything" }, { value: "replies", label: "Replies only" },
                  { value: "problems", label: "Errors and warnings" }],
        default: "all" },
      { key: "height", label: "Height",
        choices: [{ value: "short", label: "Short" }, { value: "tall", label: "Tall" }],
        default: "short" },
    ],
  },
  hours: {
    type: "hours", title: "Time of day", icon: "stats", size: "half", multiple: true,
    blurb: "When replies go out across the day. Hover a bar for the exact count.",
    options: [WINDOW],
  },
  weekdays: {
    type: "weekdays", title: "Day of the week", icon: "stats", size: "half", multiple: true,
    blurb: "Which days are busiest.",
    options: [WINDOW],
  },
  platforms: {
    type: "platforms", title: "Discord and Snapchat", icon: "chats", size: "half", multiple: true,
    blurb: "How replies split between the two, against the window before.",
    options: [WINDOW],
  },
  waiting: {
    type: "waiting", title: "Waiting for a reply", icon: "chats", size: "half",
    blurb: "People who messaged and have not been answered yet.",
    // "Up to 6", not "6": the label also shows as a chip beside the title, and a
    // bare number there read as "6 people waiting" above "Nobody is waiting".
    options: [{ key: "count", label: "Show", choices: [{ value: 3, label: "Up to 3" },
                                                      { value: 6, label: "Up to 6" },
                                                      { value: 10, label: "Up to 10" }], default: 6 }],
  },
  health: {
    type: "health", title: "Needs attention", icon: "alert", size: "half",
    blurb: "Anything wrong with the setup, and a link to where it is fixed.",
  },
  actions: {
    type: "actions", title: "Quick actions", icon: "command", size: "half",
    blurb: "One click to the things you do most.",
  },
};

/** The order a fresh Dashboard starts in: what it always showed. */
export const DEFAULT_TYPES = ["figures", "activity", "accounts", "people", "log"];

function newId(type: string) {
  return `${type}-${Math.random().toString(36).slice(2, 8)}`;
}

export function makeInstance(type: string): WidgetInstance {
  const def = WIDGETS[type];
  const options: Record<string, string | number> = {};
  for (const o of def?.options ?? []) options[o.key] = o.default;
  return { id: newId(type), type, collapsed: false, size: def?.size ?? "half", options };
}

/** A fresh layout: the old saved order if there is one, the defaults if not. */
export function initialLayout(): WidgetInstance[] {
  const old = (get(dashOrder) ?? []).filter((t) => WIDGETS[t]);
  const types = old.length ? [...old, ...DEFAULT_TYPES.filter((t) => !old.includes(t))] : DEFAULT_TYPES;
  return types.map(makeInstance);
}

/**
 * The saved layout, cleaned up: widgets that no longer exist are dropped, and
 * options that were removed or renamed fall back to their defaults, so an old
 * layout never hands a widget a value it cannot handle.
 */
export function normalise(layout: WidgetInstance[] | null): WidgetInstance[] {
  if (!Array.isArray(layout)) return initialLayout();
  const out: WidgetInstance[] = [];
  const seen = new Set<string>();
  for (const w of layout) {
    const def = w && WIDGETS[w.type];
    if (!def || seen.has(w.id)) continue;
    seen.add(w.id);
    const options: Record<string, string | number> = {};
    for (const o of def.options ?? []) {
      const v = w.options?.[o.key];
      options[o.key] = o.choices.some((c) => c.value === v) ? (v as string | number) : o.default;
    }
    out.push({ id: w.id, type: w.type, collapsed: !!w.collapsed,
               size: w.size === "full" || w.size === "half" ? w.size : def.size, options });
  }
  return out;
}

/** Change one placement and save. */
export function updateWidget(id: string, change: Partial<WidgetInstance>) {
  dashLayout.update((l) => normalise(l).map((w) => (w.id === id ? { ...w, ...change } : w)));
}

export function setOption(id: string, key: string, value: string | number) {
  dashLayout.update((l) =>
    normalise(l).map((w) => (w.id === id ? { ...w, options: { ...w.options, [key]: value } } : w)));
}

export type Seat = { w: WidgetInstance; wide: boolean; right: boolean; row: number };

/**
 * Where each widget sits on the Dashboard's one sheet. Its seams come from
 * this: one above it unless it starts the page, one beside it when it is the
 * right half of a pair. A half-width widget with no half beside it takes the
 * whole row, so the sheet never has a hole in it.
 */
export function placeOnSheet(layout: WidgetInstance[]): Seat[] {
  const out: Seat[] = [];
  let row = 0;
  let col = 0;
  layout.forEach((w, i) => {
    const next = layout[i + 1];
    if (w.size !== "half") {
      if (col) {
        row++;
        col = 0;
      }
      out.push({ w, wide: true, right: false, row: row++ });
    } else if (col === 0 && !(next && next.size === "half")) {
      out.push({ w, wide: true, right: false, row: row++ });
    } else if (col === 0) {
      out.push({ w, wide: false, right: false, row });
      col = 1;
    } else {
      out.push({ w, wide: false, right: true, row: row++ });
      col = 0;
    }
  });
  return out;
}
