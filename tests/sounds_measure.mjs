// Renders every sound in webui/src/lib/uisound.ts offline, in headless Chrome,
// and prints how each measures: peak level, and how long until it is gone.
// The engine is bundled on its own with esbuild, its stores swapped for two
// plain ones. Prints {"skip": "..."} when there is no Chrome to do it in.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const WEBUI = path.join(ROOT, "webui");
const CHROME = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium",
].find((p) => fs.existsSync(p));

async function main() {
  if (!CHROME) return { skip: "no Chrome" };
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "llm-sounds-"));
  const require = createRequire(path.join(WEBUI, "package.json"));
  const { build } = require("esbuild");
  fs.writeFileSync(path.join(dir, "stores.ts"),
    'import { writable } from "svelte/store";\nexport const uiSound = writable(true);\nexport const uiVolume = writable(1);\n' +
    'export const toasts = writable<any[]>([]);\n');
  fs.writeFileSync(path.join(dir, "entry.ts"),
    `import { renderSound } from ${JSON.stringify(path.join(WEBUI, "src", "lib", "uisound").replace(/\\/g, "/"))};\n(window as any).renderSound = renderSound;\n`);
  await build({
    entryPoints: [path.join(dir, "entry.ts")], bundle: true, format: "iife", logLevel: "error",
    outfile: path.join(dir, "bundle.js"), nodePaths: [path.join(WEBUI, "node_modules")],
    plugins: [{ name: "stores", setup(b) { b.onResolve({ filter: /^\.\/stores$/ }, () => ({ path: path.join(dir, "stores.ts") })); } }],
  });
  fs.writeFileSync(path.join(dir, "page.html"), '<!doctype html><meta charset="utf-8"><script src="bundle.js"></script>');

  const port = 9400 + Math.floor(Math.random() * 400);
  const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${path.join(dir, "prof")}`,
    "--no-first-run", "--mute-audio", "about:blank"], { stdio: "ignore" });
  try {
    let target;
    for (let i = 0; i < 60 && !target; i++) {
      await new Promise((r) => setTimeout(r, 200));
      try { target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page"); } catch {}
    }
    if (!target) return { skip: "Chrome did not start" };
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((r) => ws.addEventListener("open", r, { once: true }));
    let id = 0;
    const waiting = new Map();
    ws.addEventListener("message", (e) => { const m = JSON.parse(e.data); if (waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); } });
    const cmd = (method, params = {}) => new Promise((r) => { const n = ++id; waiting.set(n, r); ws.send(JSON.stringify({ id: n, method, params })); });
    await cmd("Page.enable");
    await cmd("Page.navigate", { url: "file:///" + path.join(dir, "page.html").replace(/\\/g, "/") });
    await new Promise((r) => setTimeout(r, 800));
    const expr = `(async () => {
      const names = ["tap", "up", "tick", "on", "off", "select", "open", "menu", "ok", "info", "err", "send", "receive", "delete", "undo",
                     "wind", "slide", "rise", "done", "key", "land", "pluck", "zip", "seat", "medal", "settle", "glint", "grow",
                     "lift", "slot", "drop", "grab", "release", "hover"];
      const out = {};
      for (const n of names) {
        const peaks = [], tails = [];
        for (let k = 0; k < 5; k++) {
          const b = await window.renderSound(n);
          const L = b.getChannelData(0), R = b.getChannelData(1);
          let peak = 0, last = 0;
          for (let i = 0; i < L.length; i++) { const v = Math.max(Math.abs(L[i]), Math.abs(R[i])); if (v > peak) peak = v; if (v > 0.00316) last = i; }
          peaks.push(20 * Math.log10(peak || 1e-9)); tails.push(last / b.sampleRate * 1000);
        }
        peaks.sort((a, b) => a - b);
        out[n] = { median: +peaks[2].toFixed(1), loudest: +peaks[4].toFixed(1), tailMs: Math.round(Math.max(...tails)) };
        // As it is heard: the compressor settled (see lead in uisound.ts).
        const heard = [];
        for (let k = 0; k < 5; k++) {
          const b = await window.renderSound(n, {}, 2.5, true);
          const L = b.getChannelData(0), R = b.getChannelData(1);
          let peak = 0;
          for (let i = 0; i < L.length; i++) peak = Math.max(peak, Math.abs(L[i]), Math.abs(R[i]));
          heard.push(20 * Math.log10(peak || 1e-9));
        }
        heard.sort((a, b) => a - b);
        out[n].heard = +heard[2].toFixed(1);
        out[n].heardLoudest = +heard[4].toFixed(1);
      }
      return out;
    })()`;
    const r = await cmd("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    ws.close();
    return r.result?.result?.value ?? { error: JSON.stringify(r.result?.exceptionDetails ?? r).slice(0, 400) };
  } finally {
    chrome.kill();
    setTimeout(() => { try { fs.rmSync(dir, { recursive: true, force: true }); } catch {} }, 500);
  }
}

main().then((r) => { console.log(JSON.stringify(r)); process.exitCode = 0; },
             (e) => { console.log(JSON.stringify({ error: String(e && e.message || e) })); process.exitCode = 0; });
