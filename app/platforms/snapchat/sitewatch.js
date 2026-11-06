/**
 * For when a website changes under a runner, which is the one thing every platform driven through its website can count
 * on. Two things:
 *
 * applySiteFixes puts new selectors in without a new build of the app. config/sitefixes/<platform>.json in the data
 * folder holds { "composer": ["div[role=textbox]"] }, named as in that bot's SEL table. What it names goes in front of
 * what was there, so a fix that turns out wrong costs nothing, and it is read as the runner starts. Only selectors:
 * nothing in that file is run.
 *
 * SiteWatch says when something has stopped being there. A runner whose selectors have gone stale looks like one that
 * has nothing to do: it reads no chats and it says nothing. So now and then, on tabs it already has open and doing
 * nothing a person's browser would not, it looks for the few things that should always be on the page it is on, and
 * what has been missing several looks running goes on the account's card. It never opens or reloads anything: a look
 * that cannot be made is simply not made.
 */
import fs from "fs";
import path from "path";

const asList = (v) => (Array.isArray(v) ? v : [v]).filter((s) => typeof s === "string" && s);

/** Puts the fixes in `sel` (a bot's SEL table), and says what it did. */
export function applySiteFixes(sel, platform, dataDir, log = () => {}) {
  const file = path.join(dataDir, "config", "sitefixes", `${platform}.json`);
  let fixes;
  try {
    fixes = JSON.parse(fs.readFileSync(file, "utf-8"));
  } catch (e) {
    if (e.code !== "ENOENT") log(`${file} could not be read, so it is left out: ${e.message}`);
    return [];
  }
  const done = [];
  for (const [key, value] of Object.entries(fixes && typeof fixes === "object" ? fixes : {})) {
    const fix = asList(value);
    if (!(key in sel) || !fix.length) {
      log(`${path.basename(file)}: nothing is called ${key}`);
      continue;
    }
    sel[key] = [...new Set([...fix, ...asList(sel[key])])];
    done.push(key);
  }
  if (done.length) log(`Using this computer's fixes for: ${done.join(", ")}`);
  return done;
}

export class SiteWatch {
  /**
   * @param core     [{ name: "the list of chats", sel: [...selectors], on: /\/messages/ }]: only looked for on an address
   *                 it has to be on, since a page that is meant not to have it says nothing.
   * @param pages    () => the tabs it may look in, or a promise of them.
   * @param report   (names) => told what is missing, whenever that changes.
   */
  constructor({ core, pages, report, everyMs = 10 * 60 * 1000, misses = 3 }) {
    Object.assign(this, { core, pages, report, everyMs, misses });
    this.next = Date.now() + everyMs;
    this.count = new Map();
    this.said = "";
  }

  /** Call as often as you like: it looks only when a look is due. */
  async tick() {
    if (Date.now() < this.next) return;
    this.next = Date.now() + this.everyMs;
    await this.look();
  }

  async look() {
    let tabs = [];
    try {
      tabs = (await this.pages()) || [];
    } catch {
      return;
    }
    for (const want of this.core) {
      const tab = tabs.find((p) => {
        try {
          return !p.isClosed() && want.on.test(p.url());
        } catch {
          return false;
        }
      });
      if (!tab) continue;
      const found = await this.has(tab, asList(want.sel));
      if (found === null) continue;
      this.count.set(want.name, found ? 0 : (this.count.get(want.name) || 0) + 1);
    }
    const missing = this.core.filter((c) => (this.count.get(c.name) || 0) >= this.misses).map((c) => c.name);
    const now = missing.join("|");
    if (now !== this.said) {
      this.said = now;
      this.report(missing);
    }
  }

  /** Whether any of these is on the tab, in any of its frames (TikTok's inbox has one). null when it could not be asked. */
  async has(tab, selectors) {
    let asked = false;
    for (const frame of tab.frames()) {
      try {
        const hit = await frame.evaluate((sels) => sels.some((s) => {
          try {
            return !!document.querySelector(s);
          } catch {
            return false;
          }
        }), selectors);
        asked = true;
        if (hit) return true;
      } catch {
        /* a frame going away as it is asked */
      }
    }
    return asked ? false : null;
  }
}
