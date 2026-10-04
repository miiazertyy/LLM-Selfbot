/**
 * Big Picture's room, drawn off the page's own thread.
 *
 * The canvas is handed over (transferControlToOffscreen) and everything that
 * touches the graphics card happens here: making the WebGL context, compiling
 * the shader, drawing thirty frames a second. The page only says where the
 * room is headed. Made on the page, the context alone held it up for over
 * 200 ms the first time Big Picture opened, right in its entrance, and every
 * frame drawn there was time taken from everything else on screen.
 *
 * Messages in: init (the canvas and how to start), set, pulse, pointer, still,
 * resize, destroy. Out: ready, failed, lost.
 */
import { Sky, type SkyTarget } from "./sky";

type In =
  | { type: "init"; canvas: OffscreenCanvas; scale: number; w: number; h: number; still: boolean; target: SkyTarget }
  | { type: "set"; target: SkyTarget; now?: boolean }
  | { type: "pulse" }
  | { type: "pointer"; x: number; y: number }
  | { type: "still"; still: boolean }
  | { type: "resize"; w: number; h: number }
  | { type: "destroy" };

let sky: Sky | null = null;
let gone = false;

self.onmessage = async (e: MessageEvent<In>) => {
  const m = e.data;
  if (m.type === "init") {
    const made = await Sky.create(m.canvas, m.scale).catch(() => null);
    if (gone) {
      made?.destroy();
      return;
    }
    if (!made) {
      self.postMessage({ type: "failed" });
      return;
    }
    sky = made;
    sky.onLost = () => {
      sky = null;
      self.postMessage({ type: "lost" });
    };
    sky.resize(m.w, m.h);
    sky.setStill(m.still);
    sky.set(m.target, true);
    sky.start();
    self.postMessage({ type: "ready" });
    return;
  }
  if (m.type === "destroy") {
    gone = true;
    sky?.destroy();
    sky = null;
    self.close();
    return;
  }
  if (!sky) return;
  if (m.type === "set") sky.set(m.target, m.now);
  else if (m.type === "pulse") sky.pulse();
  else if (m.type === "pointer") sky.pointer(m.x, m.y);
  else if (m.type === "still") sky.setStill(m.still);
  else if (m.type === "resize") sky.resize(m.w, m.h);
};
